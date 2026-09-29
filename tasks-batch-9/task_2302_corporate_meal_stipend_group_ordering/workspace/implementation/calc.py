"""Money pipeline, distance, rollups and accrual (PRD §2.6, §2.7, §3.5-§3.9)."""

import calendar
import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, fmt_dt, now_str, touch

# --- pinned constants ------------------------------------------------------
TAX_RATE = Decimal("0.0875")

DELIVERY_FEE_BASE_CENTS = 599
FREE_DELIVERY_THRESHOLD_CENTS = 3500

SERVICE_FEE_RATE = Decimal("0.10")
SERVICE_FEE_MIN_CENTS = 99
SERVICE_FEE_MAX_CENTS = 500
SERVICE_DISCOUNT_TIER_1_CENTS = 5000
SERVICE_DISCOUNT_TIER_2_CENTS = 12000
SERVICE_DISCOUNT_RATE_1 = Decimal("0.10")
SERVICE_DISCOUNT_RATE_2 = Decimal("0.25")

GROUP_DELIVERY_FEE_CENTS = 1250
GROUP_REOPEN_LIMIT = 2

ADMIN_TIER_1_CENTS = 100000
ADMIN_TIER_2_CENTS = 500000
ADMIN_RATE_LOW = Decimal("0.05")
ADMIN_RATE_MID = Decimal("0.04")
ADMIN_RATE_HIGH = Decimal("0.03")

DE_MINIMIS_PER_MEAL_CENTS = 2000
IMPUTED_REPORTING_THRESHOLD_CENTS = 1000


# --- rounding --------------------------------------------------------------
def rhu(value):
    """Round half-up to a whole cent (PRD §2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu3(value):
    """Round half-up to three decimal places (distances)."""
    return Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# --- distance --------------------------------------------------------------
def distance_km(restaurant, location):
    dx = float(restaurant["grid_x_km"]) - float(location["grid_x_km"])
    dy = float(restaurant["grid_y_km"]) - float(location["grid_y_km"])
    raw = math.sqrt(dx * dx + dy * dy)
    return rhu3(Decimal(repr(raw)))


def effective_limit_km(program, restaurant):
    a = Decimal(str(program["max_delivery_radius_km"]))
    b = Decimal(str(restaurant["delivery_radius_km"]))
    return a if a < b else b


def in_range(program, restaurant, location):
    return distance_km(restaurant, location) <= effective_limit_km(program, restaurant)


# --- stage 1: line tax + subtotal -----------------------------------------
def line_base(line):
    return line["unit_price_cents"] * line["quantity"]


def line_tax(line):
    return rhu(Decimal(line_base(line)) * TAX_RATE)


def stage_one(lines):
    subtotal = 0
    tax = 0
    for line in lines:                      # positional order is pinned
        base = line_base(line)
        subtotal += base
        tax += rhu(Decimal(base) * TAX_RATE)
    return subtotal, tax


# --- stage 2: fees ---------------------------------------------------------
def solo_delivery_fee(subtotal):
    if subtotal >= FREE_DELIVERY_THRESHOLD_CENTS:
        return 0
    return DELIVERY_FEE_BASE_CENTS


def service_fee(subtotal, tax):
    raw = rhu(Decimal(subtotal) * SERVICE_FEE_RATE)          # stage 2a
    clamped = min(max(raw, SERVICE_FEE_MIN_CENTS), SERVICE_FEE_MAX_CENTS)  # 2b
    pre_fee_base = subtotal + tax
    if pre_fee_base >= SERVICE_DISCOUNT_TIER_2_CENTS:
        rate = SERVICE_DISCOUNT_RATE_2
    elif pre_fee_base >= SERVICE_DISCOUNT_TIER_1_CENTS:
        rate = SERVICE_DISCOUNT_RATE_1
    else:
        rate = Decimal(0)
    return clamped - rhu(Decimal(clamped) * rate)            # stage 2c


# --- stage 3: employer / employee split -----------------------------------
def employer_employee_split(subtotal, tax, delivery_fee, svc_fee, tip_cents,
                            rule, available_cents):
    tip_employer = tip_cents if rule["tip_coverage_policy"] == "EMPLOYER_COVERS_TIP" else 0
    covered_base = subtotal + tax + delivery_fee + svc_fee + tip_employer
    cap = rule["per_meal_cap_cents"]
    employer = min(min(covered_base, cap), available_cents)
    if employer < 0:
        employer = 0
    employee = (covered_base - employer) + (tip_cents - tip_employer)
    gross = covered_base + tip_cents - tip_employer
    return {
        "tip_covered_by_employer_cents": tip_employer,
        "covered_base_cents": covered_base,
        "employer_covered_cents": employer,
        "employee_card_cents": employee,
        "gross_total_cents": gross,
        "cap_floor": min(covered_base, cap),
    }


# --- stage 4: administration fee ------------------------------------------
def admin_rate(mtd_cents):
    if mtd_cents >= ADMIN_TIER_2_CENTS:
        return ADMIN_RATE_HIGH
    if mtd_cents >= ADMIN_TIER_1_CENTS:
        return ADMIN_RATE_MID
    return ADMIN_RATE_LOW


def admin_fee(employer_covered_cents, mtd_cents):
    return rhu(Decimal(employer_covered_cents) * admin_rate(mtd_cents))


# --- program rollups (PRD §2.7) -------------------------------------------
def order_program_id(order):
    emp = db.employees.get(order["employee_id"])
    return emp["program_id"] if emp else None


def period_program_id(period):
    emp = db.employees.get(period["employee_id"])
    return emp["program_id"] if emp else None


def program_orders(program_id):
    return [o for o in db.orders.values() if order_program_id(o) == program_id]


def recompute_program_rollups(program_id):
    program = db.meal_programs.get(program_id)
    if not program:
        return
    spent = 0
    mtd = 0
    month = db.now.strftime("%Y-%m")
    for order in program_orders(program_id):
        if order["settlement_status"] != "VOIDED":
            spent += order["employer_net_cents"]
        if order["fulfillment_status"] == "DELIVERED" and order.get("delivered_at"):
            if order["delivered_at"][:7] == month:
                mtd += order["employer_covered_cents"]
    reserved = 0
    for period in db.benefit_periods.values():
        if period_program_id(period) == program_id and period["status"] in ("OPEN", "GRACE"):
            reserved += period["reserved_cents"]
    program["program_spent_cents"] = spent
    program["program_reserved_cents"] = reserved
    program["mtd_employer_captured_cents"] = mtd


def recompute_period_available(period):
    period["available_cents"] = (period["allocated_cents"]
                                - period["reserved_cents"]
                                - period["spent_cents"]
                                - period["forfeited_cents"]
                                - period["rollover_out_cents"])


# --- imputed income accrual (PRD §3.7) ------------------------------------
def order_taxable_cents(employer_net_cents, method):
    if method == "FULL_INCLUSION":
        return employer_net_cents
    return max(0, employer_net_cents - DE_MINIMIS_PER_MEAL_CENTS)


def find_imputed_record(employee_id, tax_month):
    for rec in db.imputed_records.values():
        if rec["employee_id"] == employee_id and rec["tax_month"] == tax_month:
            return rec
    return None


def employee_delivered_orders(employee_id, tax_month):
    return [o for o in db.orders.values()
            if o["employee_id"] == employee_id
            and o["fulfillment_status"] == "DELIVERED"
            and o["tax_month"] == tax_month]


def reconcile_imputed(employee_id, tax_month):
    """Re-derive the month's record and the employee's YTD figure / flag."""
    record = find_imputed_record(employee_id, tax_month)
    if record is not None:
        taxable_total = 0
        gross_total = 0
        for order in employee_delivered_orders(employee_id, tax_month):
            order["taxable_cents"] = order_taxable_cents(
                order["employer_net_cents"], record["method"])
            taxable_total += order["taxable_cents"]
            gross_total += order["employer_net_cents"]
        changed = (record["taxable_cents"] != taxable_total
                   or record["gross_employer_paid_cents"] != gross_total)
        record["taxable_cents"] = taxable_total
        record["gross_employer_paid_cents"] = gross_total
        if record.pop("_fresh", False):
            # the record was created by this very operation; its initial
            # persistence already counts as version 1
            pass
        elif changed:
            touch(record)
    employee = db.employees.get(employee_id)
    if employee:
        ytd = sum(r["taxable_cents"] for r in db.imputed_records.values()
                  if r["employee_id"] == employee_id)
        flag = "W2_IMPUTED" if ytd >= IMPUTED_REPORTING_THRESHOLD_CENTS else "NONE"
        if employee["ytd_imputed_cents"] != ytd or employee["tax_treatment_flag"] != flag:
            employee["ytd_imputed_cents"] = ytd
            employee["tax_treatment_flag"] = flag
            touch(employee)


# --- refund ledger --------------------------------------------------------
def write_ledger_entry(order_id, direction, amount_cents, reason, credit_claim_id=None):
    from store import base_row
    row = base_row()
    entry = {
        "id": row["id"],
        "created_at": row["created_at"],
        "order_id": order_id,
        "credit_claim_id": credit_claim_id,
        "direction": direction,
        "amount_cents": amount_cents,
        "reason": reason,
        "_seq": row["_seq"],
    }
    db.refund_entries[entry["id"]] = entry
    return entry


def order_ledger_entries(order_id):
    return [e for e in db.refund_entries.values() if e["order_id"] == order_id]


# --- refund routing (PRD §3.8) -------------------------------------------
def route_refund(order, approved_cents, basis):
    if basis == "EMPLOYEE_FIRST":
        exposure = order["employee_card_cents"] - order["employee_refunded_cents"]
        if exposure < 0:
            exposure = 0
        employee = min(approved_cents, exposure)
    else:  # PROPORTIONAL
        gross = order["gross_total_cents"]
        if gross <= 0:
            employee = 0
        else:
            employee = rhu(Decimal(approved_cents * order["employee_card_cents"]) / Decimal(gross))
    if employee > approved_cents:
        employee = approved_cents
    employer = approved_cents - employee
    return employee, employer


# --- period close (PRD §3.9) ---------------------------------------------
def period_close_rollover(period, program):
    unused = period["available_cents"]
    if unused < 0:
        unused = 0
    policy = program["rollover_policy"]
    if policy == "NONE":
        rollover_out = 0
    elif policy == "FULL":
        rollover_out = unused
    else:  # CAPPED_PCT
        cap = rhu(Decimal(period["allocated_cents"]) * Decimal(str(program["rollover_cap_pct"])))
        rollover_out = min(unused, cap)
    period["rollover_out_cents"] = rollover_out
    period["forfeited_cents"] = unused - rollover_out
    period["available_cents"] = 0


# --- forecast (PRD §3.9) --------------------------------------------------
def _month_dates(ref):
    last = calendar.monthrange(ref.year, ref.month)[1]
    return [date(ref.year, ref.month, day) for day in range(1, last + 1)]


def program_cost_forecast(program):
    ref = db.now.date()
    all_dates = _month_dates(ref)

    groups = [g for g in db.employee_groups.values() if g["program_id"] == program["id"]]
    participating = []
    for group in groups:
        rule = None
        for candidate in db.budget_rules.values():
            if candidate["group_id"] == group["id"] and candidate["status"] == "ACTIVE":
                rule = candidate
                break
        if rule is not None:
            participating.append((group, rule))

    union = set()
    for _group, rule in participating:
        union.update(rule["eligible_weekdays"])

    elapsed_days = len([d for d in all_dates if d <= ref and d.isoweekday() in union])
    total_days = len([d for d in all_dates if d.isoweekday() in union])
    remaining_days = len([d for d in all_dates if d >= ref and d.isoweekday() in union])

    recompute_program_rollups(program["id"])
    program_spent = program["program_spent_cents"]
    basis = program["forecast_basis"]

    if basis == "COMMITMENT":
        committed = 0
        ceiling = 0
        for group, rule in participating:
            rule_remaining = len([d for d in all_dates
                                  if d >= ref and d.isoweekday() in set(rule["eligible_weekdays"])])
            committed += (group["headcount_planned"] * rule["daily_meal_limit"]
                          * rule["per_meal_cap_cents"] * rule_remaining)
            ceiling += group["headcount_planned"] * rule["monthly_allocation_cents"]
        ceiling -= program_spent
        forecast_total = min(committed, ceiling) + program_spent
    else:  # RUN_RATE
        if elapsed_days == 0:
            forecast_total = 0
        else:
            forecast_total = rhu(
                Decimal(program_spent) / Decimal(elapsed_days) * Decimal(total_days))

    fee = rhu(Decimal(forecast_total) * admin_rate(program["mtd_employer_captured_cents"]))
    return {
        "forecast_basis": basis,
        "forecast_total_cents": forecast_total,
        "forecast_admin_fee_cents": fee,
        "remaining_eligible_days": remaining_days,
        "elapsed_eligible_days": elapsed_days,
        "total_eligible_days": total_days,
        "active_rule_group_count": len(participating),
    }


# --- group delivery fee allocation (PRD §3.6) ----------------------------
def allocation_members(group_order_id):
    """Non-cancelled, attached member orders that carry a real reservation."""
    members = [o for o in db.orders.values()
               if o.get("group_order_id") == group_order_id
               and o["fulfillment_status"] not in ("CANCELLED", "DRAFT")]

    def key(order):
        employee = db.employees.get(order["employee_id"]) or {}
        return (order["created_at"], (employee.get("email") or "").lower(), order["_seq"])

    return sorted(members, key=key)


def allocate_group_delivery_fee(members):
    count = len(members)
    if count == 0:
        return {}
    base_share = GROUP_DELIVERY_FEE_CENTS // count
    remainder = GROUP_DELIVERY_FEE_CENTS - base_share * count
    shares = {}
    for index, member in enumerate(members):
        shares[member["id"]] = base_share + (1 if index < remainder else 0)
    return shares
