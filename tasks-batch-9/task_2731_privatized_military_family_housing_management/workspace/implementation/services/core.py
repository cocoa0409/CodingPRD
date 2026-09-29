"""Shared side effects: inventory counters, ledger, rent, work orders, cascades."""

from db import (base_row, bump, db, fmt_date, iso, now, now_iso, parse_date,
                period_of, today)
from errors import ApiError
from services import calc, lookup


# ---------------------------------------------------- 2.8 inventory counters

def recount(installation, bump_row=True):
    """Recompute the installation's six inventory counters plus the waitlist depth."""
    if installation is None:
        return False
    units = [u for u in db.housing_units.values()
             if u["installation_id"] == installation["id"]]
    counts = {
        "AVAILABLE": 0, "ASSIGNED": 0, "OCCUPIED": 0,
        "OFFLINE_MAINTENANCE": 0, "HAZARD_HOLD": 0,
    }
    for unit in units:
        counts[unit["status"]] = counts.get(unit["status"], 0) + 1
    pending = len([a for a in db.applications.values()
                   if a["installation_id"] == installation["id"] and a["status"] == "PENDING"])
    before = (
        installation["total_unit_count"], installation["available_unit_count"],
        installation["assigned_unit_count"], installation["occupied_unit_count"],
        installation["offline_unit_count"], installation["hazard_hold_unit_count"],
        installation["pending_application_count"],
    )
    installation["total_unit_count"] = len(units)
    installation["available_unit_count"] = counts["AVAILABLE"]
    installation["assigned_unit_count"] = counts["ASSIGNED"]
    installation["occupied_unit_count"] = counts["OCCUPIED"]
    installation["offline_unit_count"] = counts["OFFLINE_MAINTENANCE"]
    installation["hazard_hold_unit_count"] = counts["HAZARD_HOLD"]
    installation["pending_application_count"] = pending
    after = (
        installation["total_unit_count"], installation["available_unit_count"],
        installation["assigned_unit_count"], installation["occupied_unit_count"],
        installation["offline_unit_count"], installation["hazard_hold_unit_count"],
        installation["pending_application_count"],
    )
    changed = before != after
    if changed and bump_row:
        bump(installation)
    return changed


def recount_for_unit(unit):
    recount(db.installations.get(unit["installation_id"]))


# ------------------------------------------------------------- 2.7 the ledger

def recompute_ledger(lease):
    rows = lookup.transactions_of(lease["id"])
    balance = 0
    abatement = 0
    for row in rows:
        balance += int(row["amount_cents"])
        row["running_balance_cents"] = balance
        if row["type"] in ("ABATEMENT", "ARREARS_ADJUSTMENT"):
            abatement += int(row["amount_cents"])
    lease["allotment_balance_cents"] = balance
    lease["abatement_total_cents"] = -abatement


def post_transaction(lease, txn_type, period_month, amount_cents, source_ref):
    row = base_row(common=False)
    row["lease_id"] = lease["id"]
    row["period_month"] = period_month
    row["type"] = txn_type
    row["amount_cents"] = int(amount_cents)
    row["source_ref"] = source_ref
    row["posted_at"] = now_iso()
    row["running_balance_cents"] = 0
    db.transactions[row["id"]] = row
    recompute_ledger(lease)
    return row


# ------------------------------------------------------------ 3.5 rent engine

def select_bah_rate(installation_id, pay_grade, with_dependents, effective_year):
    matches = [r for r in lookup.bah_rates_of(installation_id)
               if r["pay_grade"] == pay_grade
               and bool(r["with_dependents"]) == bool(with_dependents)
               and int(r["effective_year"]) == int(effective_year)]
    return matches[-1] if matches else None


def apply_rent(lease, unit, sponsor, basis, year_source, dependent_count_source):
    """Compute and store the four money fields plus the basis and effective year."""
    with_dependents = int(dependent_count_source) >= 1
    rate = select_bah_rate(unit["installation_id"], sponsor["pay_grade"],
                           with_dependents, year_source)
    if rate is None:
        raise ApiError("ERR_BAH_RATE_NOT_ON_FILE")
    gross = calc.gross_rent(rate["monthly_rate_cents"], unit["unit_type"],
                            bool(unit["historic_flag"]))
    lease["gross_rent_cents"] = gross
    lease["utility_allowance_cents"] = int(rate["utility_allowance_cents"])
    lease["net_rent_cents"] = gross - int(rate["utility_allowance_cents"])
    lease["daily_rent_cents"] = calc.daily_rent(lease["net_rent_cents"])
    lease["rent_basis"] = basis
    lease["rent_effective_year"] = int(year_source)


def require_bah_rate(unit, sponsor, year_source, dependent_count_source):
    """Rung 45 pre-check, run before any state is mutated."""
    with_dependents = int(dependent_count_source) >= 1
    if select_bah_rate(unit["installation_id"], sponsor["pay_grade"],
                       with_dependents, year_source) is None:
        raise ApiError("ERR_BAH_RATE_NOT_ON_FILE")


# ---------------------------------------------------------- 3.7 work orders

def occupied_lease_on_unit(unit_id):
    for lease in lookup.leases_of_unit(unit_id):
        if lease["occupancy_status"] == "OCCUPIED":
            return lease
    return None


def has_vulnerable_child(unit_id, reference_date):
    lease = occupied_lease_on_unit(unit_id)
    if lease is None:
        return False
    for dependent in lookup.dependents_of(lease["service_member_id"]):
        if dependent["relationship"] != "CHILD":
            continue
        if not dependent.get("is_full_time_custody"):
            continue
        age = calc.age_years(parse_date(dependent["date_of_birth"]), reference_date)
        if age < 6:
            return True
    return False


def create_work_order(unit, lease_id, parent_work_order_id, category, description,
                      habitability_impact, inspection_deficiency_code=None):
    reported_at = now()
    vulnerable = has_vulnerable_child(unit["id"], reported_at.date())
    priority = calc.priority_class(category, bool(habitability_impact), vulnerable)
    response_due, completion_due = calc.sla_due(priority, reported_at,
                                                bool(habitability_impact))
    row = base_row()
    row["housing_unit_id"] = unit["id"]
    row["lease_id"] = lease_id
    row["parent_work_order_id"] = parent_work_order_id
    row["inspection_deficiency_code"] = inspection_deficiency_code
    row["category"] = category
    row["description"] = description
    row["habitability_impact"] = bool(habitability_impact)
    row["priority_class"] = priority
    row["reported_at"] = iso(reported_at)
    row["response_due_at"] = iso(response_due)
    row["completion_due_at"] = iso(completion_due)
    row["first_response_at"] = None
    row["completed_at"] = None
    row["sla_breached"] = False
    row["escalation_level"] = 0
    row["escalated_at"] = None
    row["reopen_count"] = 0
    row["assigned_tech_user_id"] = None
    row["status"] = "SUBMITTED"
    db.work_orders[row["id"]] = row
    return row


# ---------------------------------------------------- 3.6 inspection counters

def recompute_inspection_counts(inspection):
    entries = inspection["deficiencies"]
    inspection["deficiency_count"] = len(entries)
    inspection["critical_open_count"] = len(
        [e for e in entries
         if e["severity"] == "HABITABILITY_CRITICAL" and e["status"] != "RESOLVED"])


def find_inspection_for_order(work_order):
    code = work_order.get("inspection_deficiency_code")
    if not code or not work_order.get("lease_id"):
        return None, None
    for inspection in lookup.inspections_of(work_order["lease_id"]):
        for entry in inspection["deficiencies"]:
            if entry["deficiency_code"] == code \
                    and entry.get("work_order_id") == work_order["id"]:
                return inspection, entry
    return None, None


# ------------------------------------------------------ reinvestment accounts

def recompute_closing(account):
    account["closing_balance_cents"] = (
        int(account["opening_balance_cents"])
        + int(account["contributions_cents"])
        - int(account["expenditures_cents"])
    )


def add_expenditure(installation_id, year, amount_cents):
    """Lodging-closure cascade: bypasses the sufficiency check, silent when absent."""
    if amount_cents == 0:
        return
    for account in lookup.accounts_for(installation_id, year):
        account["expenditures_cents"] = int(account["expenditures_cents"]) + int(amount_cents)
        recompute_closing(account)
        bump(account)


def add_contribution(installation_id, year, amount_cents):
    if amount_cents == 0:
        return
    for account in lookup.accounts_for(installation_id, year):
        account["contributions_cents"] = int(account["contributions_cents"]) + int(amount_cents)
        recompute_closing(account)
        bump(account)


# -------------------------------------------------------------- 3.8 lodgings

def close_lodging(lodging, actual_end_date, cascade_account=True):
    lease = db.leases.get(lodging["lease_id"])
    daily = int(lease["daily_rent_cents"]) if lease else 0
    start = parse_date(lodging["start_date"])
    nights, per_night, authorized, rent_abatement = calc.lodging_figures(
        lodging["nightly_rate_cents"], lodging["occupants_count"], start,
        actual_end_date, daily)
    lodging["actual_end_date"] = fmt_date(actual_end_date)
    lodging["nights_displaced"] = nights
    lodging["per_night_authorized_cents"] = per_night
    lodging["lodging_authorized_cents"] = authorized
    lodging["rent_abatement_cents"] = rent_abatement
    lodging["status"] = "CLOSED"
    bump(lodging)
    if cascade_account and authorized > 0 and lease is not None:
        unit = lookup.lease_unit(lease)
        if unit is not None:
            add_expenditure(unit["installation_id"], actual_end_date.year, authorized)
    return authorized


def close_authorized_lodgings(case, actual_end_date, cascade_account=True):
    total = 0
    for lodging in lookup.lodgings_of_case(case["id"]):
        if lodging["status"] != "AUTHORIZED":
            continue
        if actual_end_date is None:
            end = parse_date(lodging["start_date"])
        else:
            end = actual_end_date
        total += close_lodging(lodging, end, cascade_account=cascade_account)
    return total


# ----------------------------------------------------- 3.8 hazard hold release

OPEN_HAZARD_STATUSES = ("DISPLACEMENT_ACTIVE", "REMEDIATION_IN_PROGRESS", "CLEARANCE_PENDING")
BLOCKING_HAZARD_STATUSES = (
    "REPORTED", "ASSESSED", "REMEDIATION_IN_PROGRESS", "DISPLACEMENT_ACTIVE",
    "CLEARANCE_PENDING",
)


def other_open_case_on_unit(unit_id, exclude_case_id):
    for case in lookup.hazard_cases_of_unit(unit_id):
        if case["id"] == exclude_case_id:
            continue
        if case["status"] in OPEN_HAZARD_STATUSES:
            return True
    return False


def release_hazard_hold(case, force=False):
    """Return the unit to OCCUPIED and reinstate the suspended allotment.

    On a clearance pass a second hazard case still open on the unit keeps the
    hold in place (PRD 3.8).  A void is the compensating action for a case
    opened in error and releases unconditionally, so it passes force=True.
    """
    unit = db.housing_units.get(case["housing_unit_id"])
    if unit is None:
        return
    held = unit["status"] == "HAZARD_HOLD"
    if held and not force and other_open_case_on_unit(unit["id"], case["id"]):
        return
    if held:
        unit["status"] = "OCCUPIED"
        unit["hazard_hold_reason"] = None
        bump(unit)
        recount_for_unit(unit)
    elif not force:
        return
    for lease in lookup.leases_of_unit(unit["id"]):
        if lease["allotment_status"] == "SUSPENDED":
            lease["allotment_status"] = "ACTIVE"
            bump(lease)
