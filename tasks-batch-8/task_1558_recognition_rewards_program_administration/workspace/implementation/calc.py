"""Calculation rules (SCAFFOLD Table 3 / PRD section 3). All money is integer
cents via Decimal; rounding is half-up, applied exactly where the rule pins it."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from db import now

FEDERAL_SUPPLEMENTAL_RATE = Decimal("0.22")
FEDERAL_SUPPLEMENTAL_RATE_HIGH = Decimal("0.37")
SUPPLEMENTAL_TIER_THRESHOLD_CENTS = 100000000
FICA_RATE = Decimal("0.0765")
DEMINIMIS_ANNUAL_CAP_CENTS = 10000
FORFEITURE_RECOVERY_RATE = Decimal("0.5")
SHIP_LOOKAHEAD_CALENDAR_DAYS = 45
UTILIZATION_CURVE = {m: Decimal("0.07") for m in range(1, 12)}
UTILIZATION_CURVE[12] = Decimal("0.23")
DEFAULT_WINDOW_DAYS = 90


def rhu(value):
    """Round half-up to integer cents (single rounding of the whole expr)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(x):
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# gross_up_calculation + de_minimis_exclusion
# ---------------------------------------------------------------------------

def federal_rate(employee):
    if employee["ytd_supplemental_wages_cents"] > SUPPLEMENTAL_TIER_THRESHOLD_CENTS:
        return FEDERAL_SUPPLEMENTAL_RATE_HIGH
    return FEDERAL_SUPPLEMENTAL_RATE


def state_rate(program, employee):
    return dec((program.get("state_rate_map") or {}).get(employee["state_code"], 0.0))


def gross_up_cents(program, employee, taxable_value_cents):
    """Closed-form tax-on-tax gross-up; single half-up rounding at the end."""
    if not program.get("grossup_enabled") or taxable_value_cents == 0:
        return 0
    combined = federal_rate(employee) + state_rate(program, employee) + FICA_RATE
    return rhu(Decimal(taxable_value_cents) * combined / (Decimal(1) - combined))


def de_minimis(item, employee, order_value_cents):
    """All-or-nothing annual exclusion. Reaching exactly the cap excludes."""
    if (item["de_minimis_eligible"] and item["taxable_class"] != "GIFT_CARD"
            and employee["ytd_de_minimis_cents"] + order_value_cents
            <= DEMINIMIS_ANNUAL_CAP_CENTS):
        return True
    return False


# ---------------------------------------------------------------------------
# vendor_ship_date_assignment
# ---------------------------------------------------------------------------

def add_business_days(d, n):
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:  # Mon-Fri
            added += 1
    return cur


def next_business_day(d):
    cur = d + timedelta(days=1)
    while cur.weekday() >= 5:
        cur += timedelta(days=1)
    return cur


def vendor_order_count_on(vendor_id, ship_date):
    count = 0
    for o in db.orders.values():
        item = db.catalog_items.get(o["catalog_item_id"])
        if item is None or item["vendor_id"] != vendor_id:
            continue
        if o["fulfillment_status"] in ("SUBMITTED", "SHIPPED") \
                and o["ship_date"] == ship_date:
            count += 1
    return count


def assign_ship_date(vendor):
    today = now().date()
    candidate = add_business_days(today, vendor["lead_time_business_days"])
    while vendor_order_count_on(vendor["id"], candidate) >= vendor["daily_ship_capacity"]:
        candidate = next_business_day(candidate)
    if candidate > today + timedelta(days=SHIP_LOOKAHEAD_CALENDAR_DAYS):
        from errors import raise_err, ERR_VENDOR_CAPACITY_EXCEEDED
        raise_err(ERR_VENDOR_CAPACITY_EXCEEDED,
                  "No ship_date with free capacity within %d calendar days"
                  % SHIP_LOOKAHEAD_CALENDAR_DAYS)
    return candidate


# ---------------------------------------------------------------------------
# chargeback_calculation + budget_accrual
# ---------------------------------------------------------------------------

def period_window(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def eligible_department_ids(program_id):
    """Departments with at least one employee and at least one budget in the
    program (any window, any posture)."""
    dept_ids = set()
    for emp in db.employees.values():
        dept_ids.add(emp["department_id"])
    result = []
    for d in db.departments.values():
        if d["id"] not in dept_ids:
            continue
        has_budget = any(
            b["program_id"] == program_id and b["department_id"] == d["id"]
            for b in db.budgets.values())
        if has_budget:
            result.append(d["id"])
    return result


def compute_department_breakdown(program, year, month):
    """Per-department accrual + chargeback figures for the calendar month.

    Rounding order is pinned: each settled order line is rounded half-up
    first, then summed; forfeiture credit is a single rounding on the
    department aggregate.
    """
    rate = dec(program["point_cost_rate_cents"])
    method = program["accrual_method"]
    win_start, win_end = period_window(year, month)
    month_start_d = win_start.date()
    month_end_d = win_end.date()

    breakdown = []
    for dept_id in eligible_department_ids(program["id"]):
        # budget_accrual: budgets whose windows intersect the period month
        annual = Decimal(0)
        for b in db.budgets.values():
            if b["program_id"] != program["id"] or b["department_id"] != dept_id:
                continue
            if b["period_start_date"] < month_end_d and b["period_end_date"] > month_start_d:
                annual += Decimal(b["allocated_points"]) * rate
        if method == "UTILIZATION_WEIGHTED":
            accrual = rhu(annual * UTILIZATION_CURVE[month])
        else:
            accrual = rhu(annual / Decimal(12))

        emp_ids = {e["id"] for e in db.employees.values()
                   if e["department_id"] == dept_id}

        # Redemption cost: round per settled order line first, then sum.
        redemption_cost = 0
        for o in db.orders.values():
            if o["employee_id"] not in emp_ids:
                continue
            if o["escrow_status"] not in ("SETTLED", "SETTLED_WITH_FEE"):
                continue
            delivered = o["delivered_at"]
            if delivered is None or not (win_start <= delivered < win_end):
                continue
            if o["escrow_status"] == "SETTLED":
                net_pts = o["points_total"]
            else:
                net_pts = o["restocking_fee_points"]
            redemption_cost += rhu(Decimal(net_pts) * rate)

        # Gross-up expense: estimated gross-up of TaxRecords created in window.
        gross_up_expense = 0
        for t in db.tax_records.values():
            if t["employee_id"] in emp_ids \
                    and win_start <= t["created_at"] < win_end:
                gross_up_expense += t["estimated_gross_up_cents"]

        # Forfeiture credit: EXPIRY + CLAWBACK ledger points in window,
        # single rounding on the department aggregate.
        forfeiture_pts = 0
        for entry in db.ledger:
            if entry["employee_id"] in emp_ids \
                    and entry["entry_type"] in ("EXPIRY", "CLAWBACK") \
                    and win_start <= entry["created_at"] < win_end:
                forfeiture_pts += abs(entry["points"])
        forfeiture_credit = rhu(Decimal(forfeiture_pts) * rate
                                * FORFEITURE_RECOVERY_RATE)

        net = redemption_cost + gross_up_expense - forfeiture_credit
        breakdown.append({
            "department_id": dept_id,
            "accrual_cents": accrual,
            "redemption_cost_cents": redemption_cost,
            "gross_up_expense_cents": gross_up_expense,
            "forfeiture_credit_cents": forfeiture_credit,
            "net_chargeback_cents": net,
        })
    return breakdown


def totals(breakdown):
    return (sum(e["accrual_cents"] for e in breakdown),
            sum(e["net_chargeback_cents"] for e in breakdown))


# ---------------------------------------------------------------------------
# participation_inclusion_analytics
# ---------------------------------------------------------------------------

def compute_participation(program_id, window_days):
    now_dt = now()
    window_start = now_dt - timedelta(days=window_days)

    def in_window(dt):
        return dt is not None and window_start <= dt <= now_dt

    # Eligible: department holds >= 1 budget in the program (any window).
    eligible_depts = eligible_department_ids(program_id)
    eligible_emps = [e for e in db.employees.values()
                     if e["department_id"] in eligible_depts]

    participating_ids = set()
    points_in_window = {}  # employee_id -> points granted in window
    for e in eligible_emps:
        participated = False
        for n in db.nominations.values():
            if n["nominator_id"] == e["id"] and n["program_id"] == program_id \
                    and n["status"] != "CANCELLED" and in_window(n["created_at"]):
                participated = True
                break
        if not participated:
            for n in db.nominations.values():
                if n["nominee_id"] == e["id"] and n["program_id"] == program_id \
                        and n["status"] != "CANCELLED" and in_window(n["created_at"]):
                    participated = True
                    break
        if not participated:
            for a in db.awards.values():
                if a["employee_id"] == e["id"] and a["program_id"] == program_id \
                        and in_window(a["granted_at"]):
                    participated = True
                    break
        if not participated:
            for o in db.orders.values():
                if o["employee_id"] == e["id"] and o["program_id"] == program_id \
                        and in_window(o["created_at"]):
                    participated = True
                    break
        if participated:
            participating_ids.add(e["id"])

    for a in db.awards.values():
        if a["program_id"] == program_id and a["employee_id"] in {
                e["id"] for e in eligible_emps} and in_window(a["granted_at"]):
            points_in_window[a["employee_id"]] = \
                points_in_window.get(a["employee_id"], 0) + a["points"]

    total_eligible = len(eligible_emps)
    total_participating = len(participating_ids)
    if total_eligible == 0:
        participation_rate_bp = 0
    else:
        participation_rate_bp = (total_participating * 10000) // total_eligible

    # Per-department rates; departments with zero eligible are excluded from
    # disparity.
    dept_breakdown = []
    rates = []
    for dept in db.departments.values():
        dept_emps = [e for e in eligible_emps
                     if e["department_id"] == dept["id"]]
        if not dept_emps:
            continue
        dept_part = sum(1 for e in dept_emps if e["id"] in participating_ids)
        rate_bp = (dept_part * 10000) // len(dept_emps)
        rates.append(rate_bp)
        dept_breakdown.append({
            "department_id": dept["id"],
            "eligible_employees": len(dept_emps),
            "participating_employees": dept_part,
            "participation_rate_bp": rate_bp,
        })
    if len(rates) < 2:
        inclusion_disparity_bp = 0
    else:
        inclusion_disparity_bp = max(rates) - min(rates)

    # Concentration: rank by points granted in window DESC, tie employee
    # created_at ASC; top_n = max(1, floor(total_eligible * 0.05)).
    ranked = sorted(
        eligible_emps,
        key=lambda e: (-points_in_window.get(e["id"], 0), e["created_at"]))
    top_n = max(1, (total_eligible * 5) // 100)
    top_points = sum(points_in_window.get(e["id"], 0) for e in ranked[:top_n])
    total_points = sum(points_in_window.values())
    if total_points == 0:
        concentration_share_bp = 0
    else:
        concentration_share_bp = (top_points * 10000) // total_points

    return {
        "window_days": window_days,
        "eligible_employees": total_eligible,
        "participating_employees": total_participating,
        "participation_rate_bp": participation_rate_bp,
        "department_breakdown": dept_breakdown,
        "inclusion_disparity_bp": inclusion_disparity_bp,
        "concentration_share_bp": concentration_share_bp,
    }
