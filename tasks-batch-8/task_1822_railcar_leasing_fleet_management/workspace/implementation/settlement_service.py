"""calc_car_hire_settlement (PRD 3.7): provisional and final variants."""
from datetime import date

import calc
import domain
from store import db


def report_for(assignment_id, month):
    """The governing mileage report for (assignment, month): the unique
    non-DISPUTED report when one exists, else the latest report."""
    reps = [
        r
        for r in db.reports.values()
        if r["lease_assignment_id"] == assignment_id and r["report_month"] == month
    ]
    if not reps:
        return None
    live = [r for r in reps if r["status"] != "DISPUTED"]
    pool = live if live else reps
    return max(pool, key=lambda r: (r["created_at"], r["_created_seq"]))


def validated_report_for(assignment_id, month):
    reps = [
        r
        for r in db.reports.values()
        if r["lease_assignment_id"] == assignment_id
        and r["report_month"] == month
        and r["status"] == "VALIDATED"
    ]
    if not reps:
        return None
    return max(reps, key=lambda r: (r["created_at"], r["_created_seq"]))


def m_prev_loaded_miles(lease_id, statement_month, exclude_assignment_id):
    """Cumulative VALIDATED loaded miles on this lease in the calendar year of
    statement_month, excluding this statement's (assignment, month) reports.
    DISPUTED reports keep contributing their last validated pair (PRD 3.8).
    "Prior accumulated" (PRD 3.7) is chronological: reports for months after
    the statement month never count toward its prior accumulation."""
    year = statement_month[:4]
    total = 0
    for r in db.reports.values():
        if r["status"] not in ("VALIDATED", "DISPUTED"):
            continue
        if r["validated_loaded_miles"] is None:
            continue
        if not r["report_month"].startswith(year + "-"):
            continue
        if r["report_month"] > statement_month:
            continue
        a = db.assignments.get(r["lease_assignment_id"])
        if a is None or a["lease_id"] != lease_id:
            continue
        if r["lease_assignment_id"] == exclude_assignment_id and r["report_month"] == statement_month:
            continue
        total += r["validated_loaded_miles"]
    return total


def compute_fields(assignment, month, variant):
    """Returns the measured statement fields for the given variant."""
    lease = db.leases[assignment["lease_id"]]
    car = db.railcars[assignment["railcar_id"]]
    first, _last = calc.month_bounds(month)
    days = calc.days_on_lease_in_month(assignment, month)
    m_prev = m_prev_loaded_miles(lease["id"], month, assignment["id"])

    if variant == "final":
        daily_rate = assignment["pinned_car_hire_daily_cents"]
        r = assignment["pinned_mileage_credit_cents"]
        rep = validated_report_for(assignment["id"], month)
        m = rep["validated_loaded_miles"] if rep else 0
    else:
        hire = domain.tariff_at(car["car_type"], "CAR_HIRE_BASE", first)
        cred = domain.tariff_at(car["car_type"], "MILEAGE_CREDIT", first)
        # PRD prices the provisional variant off the current grid; when no
        # current window covers the month, fall back to the pinned snapshot.
        daily_rate = hire["unit_rate_cents"] if hire else assignment["pinned_car_hire_daily_cents"]
        r = cred["unit_rate_cents"] if cred else assignment["pinned_mileage_credit_cents"]
        rep = report_for(assignment["id"], month)
        if rep is None:
            m = 0
        elif rep["validated_loaded_miles"] is not None:
            m = rep["validated_loaded_miles"]
        else:
            m = rep["loaded_miles"]

    return calc.settlement(
        days, daily_rate, lease["car_hire_lessor_share_pct"], m, m_prev, r
    )


def apply_provisional(stmt):
    """Recompute a statement under the provisional variant (current tariff)."""
    assignment = db.assignments[stmt["lease_assignment_id"]]
    f = compute_fields(assignment, stmt["statement_month"], "provisional")
    stmt["days_on_lease"] = f["days_on_lease"]
    stmt["gross_car_hire_cents"] = f["gross_car_hire_cents"]
    stmt["loaded_miles_used"] = f["loaded_miles_used"]
    stmt["tier_excess_miles"] = f["tier_excess_miles"]
    stmt["mileage_credit_cents"] = f["mileage_credit_cents"]
    stmt["provisional_net_cents"] = f["net_cents"]
    stmt["tariff_source"] = "CURRENT"


def apply_final(stmt):
    """Recompute a statement under the final variant (pinned tariff)."""
    assignment = db.assignments[stmt["lease_assignment_id"]]
    f = compute_fields(assignment, stmt["statement_month"], "final")
    stmt["days_on_lease"] = f["days_on_lease"]
    stmt["gross_car_hire_cents"] = f["gross_car_hire_cents"]
    stmt["loaded_miles_used"] = f["loaded_miles_used"]
    stmt["tier_excess_miles"] = f["tier_excess_miles"]
    stmt["mileage_credit_cents"] = f["mileage_credit_cents"]
    stmt["final_net_cents"] = f["net_cents"]
    stmt["tariff_source"] = "PINNED"
    return f["net_cents"]
