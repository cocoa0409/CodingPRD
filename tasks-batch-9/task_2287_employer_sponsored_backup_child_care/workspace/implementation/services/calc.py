"""Charge, entitlement, admission and reporting calculations (SCAFFOLD §1.3)."""

from datetime import date, timedelta

from db import clock, db
from util import D, dceil, hours_between, jnum, rhu, rhu_int, utc_date

from services.core import (
    CENTER,
    HOUR_ROUNDING_INCREMENT,
    IN_HOME,
    IN_HOME_HOURS_PER_DAY,
    LATE_CANCEL_FACTOR,
    OVERAGE_TIER_1_CENTS,
    OVERAGE_TIER_2_CENTS,
    RISK_LIFETIME_FLOOR,
    RISK_NO_SHOW_HIGH_PCT,
    RISK_NO_SHOW_MEDIUM_PCT,
    TRAVEL_BUFFER_MINUTES,
    benefit_year_for,
    block_occupancy,
    employee_benefit_year,
    employer_accrued_overage,
    provider_quality,
)


def plan_of(reservation):
    return db.benefit_plans.get(reservation["benefit_plan_id"])


def employee_of(reservation):
    return db.employees.get(reservation["employee_id"])


def employer_of_reservation(reservation):
    employee = employee_of(reservation)
    if employee is None:
        return None
    return db.employers.get(employee["employer_id"])


def effective_care_mode(reservation):
    provider = db.providers.get(reservation.get("matched_provider_id"))
    if provider is None:
        return None
    return provider["care_mode"]


# --------------------------------------------------------------------------- #
# reservation_billable_hours
# --------------------------------------------------------------------------- #

def billable_hours(mode, plan, window_start, window_end):
    if mode == CENTER:
        return D(0)
    raw_hours = hours_between(window_start, window_end)
    steps = dceil(raw_hours / HOUR_ROUNDING_INCREMENT)
    stepped = steps * HOUR_ROUNDING_INCREMENT
    floor_hours = D(plan["in_home_min_billable_hours"])
    return rhu(max(floor_hours, stepped), 2)


# --------------------------------------------------------------------------- #
# reservation_day_charge
# --------------------------------------------------------------------------- #

def day_charge(mode, dependent_count, hours):
    if mode == CENTER:
        return D(dependent_count)
    return dceil(D(hours) / IN_HOME_HOURS_PER_DAY)


# --------------------------------------------------------------------------- #
# entitlement_split
# --------------------------------------------------------------------------- #

def entitlement_split(reservation, days_charged):
    employee = employee_of(reservation)
    plan = plan_of(reservation)
    employer = employer_of_reservation(reservation)
    by_start, _ = employee_benefit_year(employee)
    key = by_start.isoformat()

    days_used_before = D(0)
    days_reserved_before = D(0)
    for entry in db.ledger_entries.values():
        if entry["employee_id"] != employee["id"]:
            continue
        if entry["benefit_year_start"] != key:
            continue
        if entry["reservation_id"] == reservation["id"]:
            continue
        if entry["entry_type"] == "COMMIT":
            days_used_before += entry["days_delta"]
        elif entry["entry_type"] in ("RESERVE", "RELEASE"):
            days_reserved_before += entry["days_delta"]

    limit = D(plan["annual_use_limit_days"])
    remaining = max(D(0), limit - days_used_before - days_reserved_before)
    covered_days = min(D(days_charged), remaining)
    overage_days = D(days_charged) - covered_days

    accrued_before = employer_accrued_overage(employer)
    if accrued_before < OVERAGE_TIER_1_CENTS:
        multiplier = D("1.00")
    elif accrued_before < OVERAGE_TIER_2_CENTS:
        multiplier = D("0.90")
    else:
        multiplier = D("0.80")

    return rhu(covered_days, 2), rhu(overage_days, 2), multiplier


# --------------------------------------------------------------------------- #
# reservation_charge_money
# --------------------------------------------------------------------------- #

def charge_money(mode, plan, hours, covered_days, overage_days, days_charged, multiplier):
    if mode == CENTER:
        copay_unit = plan["copay_center_cents_per_day"]
        copay_cents = rhu_int(D(covered_days) * D(copay_unit))
        overage_unit = rhu_int(D(plan["overage_rate_center_cents_per_day"]) * multiplier)
        overage_cents = rhu_int(D(overage_days) * D(overage_unit))
        covered_qty = D(covered_days)
        overage_qty = D(overage_days)
    else:
        if D(days_charged) == 0:
            covered_hours = D(0)
            overage_hours = D(0)
        else:
            covered_hours = rhu(D(hours) * D(covered_days) / D(days_charged), 2)
            overage_hours = rhu(D(hours) - covered_hours, 2)
        copay_unit = plan["copay_in_home_cents_per_hour"]
        copay_cents = rhu_int(covered_hours * D(copay_unit))
        overage_unit = rhu_int(
            D(plan["overage_rate_in_home_cents_per_hour"]) * multiplier
        )
        overage_cents = rhu_int(overage_hours * D(overage_unit))
        covered_qty = covered_hours
        overage_qty = overage_hours
    return {
        "copay_cents": copay_cents,
        "overage_cents": overage_cents,
        "covered_qty": covered_qty,
        "overage_qty": overage_qty,
        "copay_unit": int(copay_unit),
        "overage_unit": int(overage_unit),
    }


# --------------------------------------------------------------------------- #
# cancellation_penalty
# --------------------------------------------------------------------------- #

def cancellation_penalty(reservation, from_state):
    plan = plan_of(reservation)
    is_late = clock() > reservation["cancellation_deadline_utc"]
    if from_state == "CONFIRMED" and is_late:
        return rhu_int(D(plan["no_show_charge_cents"]) * LATE_CANCEL_FACTOR), True
    return 0, is_late


# --------------------------------------------------------------------------- #
# capacity_and_window_admission
# --------------------------------------------------------------------------- #

ADMIT = "ADMIT"
REJECT_WINDOW = "REJECT_WINDOW"
REJECT_CAPACITY = "REJECT_CAPACITY"
REJECT_CAREGIVER = "REJECT_CAREGIVER"


def window_contained(block, reservation):
    return (
        block["start_time_utc"] <= reservation["care_start_utc"]
        and reservation["care_end_utc"] <= block["end_time_utc"]
    )


def center_capacity_ok(block, reservation):
    reserved, committed = block_occupancy(block)
    remaining = block["total_slots"] - reserved - committed
    return remaining >= reservation["dependent_count"]


def in_home_caregiver_ok(provider, reservation):
    buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    conflicts = 0
    for other in db.reservations.values():
        if other["matched_provider_id"] != provider["id"]:
            continue
        if other["fulfillment_status"] not in ("CONFIRMED", "IN_SERVICE"):
            continue
        if other["id"] == reservation["id"]:
            continue
        if (
            reservation["care_start_utc"] < other["care_end_utc"] + buffer
            and other["care_start_utc"] < reservation["care_end_utc"] + buffer
        ):
            conflicts += 1
    return conflicts < provider["max_concurrent_assignments"]


def admission(provider, block, reservation):
    if not window_contained(block, reservation):
        return REJECT_WINDOW
    if provider["care_mode"] == CENTER:
        return ADMIT if center_capacity_ok(block, reservation) else REJECT_CAPACITY
    return ADMIT if in_home_caregiver_ok(provider, reservation) else REJECT_CAREGIVER


# --------------------------------------------------------------------------- #
# employee_entitlement_projection
# --------------------------------------------------------------------------- #

def entitlement_projection(employee):
    from services.core import employee_counters, employee_eligibility

    by_start, by_end = employee_benefit_year(employee)
    days_used, days_reserved, strikes = employee_counters(employee)
    plan = db.benefit_plans.get(employee["benefit_plan_id"])
    days_limit = D(plan["annual_use_limit_days"]) if plan is not None else D(0)
    days_remaining = max(D(0), days_limit - days_used - days_reserved)
    overage_projected = max(D(0), days_used + days_reserved - days_limit)
    return {
        "employee_id": employee["id"],
        "benefit_year_start": by_start.isoformat(),
        "benefit_year_end": by_end.isoformat(),
        "days_limit": jnum(rhu(days_limit, 2)),
        "days_used": jnum(rhu(days_used, 2)),
        "days_reserved": jnum(rhu(days_reserved, 2)),
        "days_remaining": jnum(rhu(days_remaining, 2)),
        "overage_days_projected": jnum(rhu(overage_projected, 2)),
        "no_show_strike_count": strikes,
        "eligibility_status": employee_eligibility(employee, strikes),
    }


# --------------------------------------------------------------------------- #
# employer_utilization_report
# --------------------------------------------------------------------------- #

def utilization_report(employer, period_start, period_end):
    employee_ids = set(
        e["id"] for e in db.employees.values() if e["employer_id"] == employer["id"]
    )
    scope = []
    for res in db.reservations.values():
        if res["employee_id"] not in employee_ids:
            continue
        care_date = date.fromisoformat(res["care_date"])
        if period_start <= care_date <= period_end:
            scope.append(res)

    confirmed_states = ("CONFIRMED", "IN_SERVICE", "COMPLETED", "NO_SHOW")
    reservations_confirmed = len(
        [r for r in scope if r["fulfillment_status"] in confirmed_states]
    )
    reservations_completed = len(
        [r for r in scope if r["fulfillment_status"] == "COMPLETED"]
    )
    no_show_count = len([r for r in scope if r["fulfillment_status"] == "NO_SHOW"])

    delivered = [r for r in scope if r["fulfillment_status"] in ("COMPLETED", "NO_SHOW")]
    days_used = D(0)
    days_overage = D(0)
    for res in delivered:
        days_used += D(res["covered_days"])
        days_overage += D(res["overage_days"])

    unique_employees = set(
        r["employee_id"] for r in scope if r["fulfillment_status"] == "COMPLETED"
    )

    center_done = 0
    for res in scope:
        if res["fulfillment_status"] != "COMPLETED":
            continue
        provider = db.providers.get(res["matched_provider_id"])
        if provider is not None and provider["care_mode"] == CENTER:
            center_done += 1

    if reservations_completed == 0:
        center_share = D(0)
        in_home_share = D(0)
    else:
        center_share = rhu(D(100) * D(center_done) / D(reservations_completed), 2)
        in_home_share = rhu(D(100) - center_share, 2)

    if reservations_confirmed == 0:
        no_show_rate = D(0)
    else:
        no_show_rate = rhu(D(100) * D(no_show_count) / D(reservations_confirmed), 2)

    min_lifetime = None
    for res in delivered:
        provider = db.providers.get(res["matched_provider_id"])
        if provider is None:
            continue
        score = provider_quality(provider, "LIFETIME_UNDECAYED")
        if min_lifetime is None or score < min_lifetime:
            min_lifetime = score

    if no_show_rate >= RISK_NO_SHOW_HIGH_PCT or (
        min_lifetime is not None and min_lifetime < RISK_LIFETIME_FLOOR
    ):
        band = "HIGH"
    elif days_overage > 0 or no_show_rate >= RISK_NO_SHOW_MEDIUM_PCT:
        band = "MEDIUM"
    else:
        band = "LOW"

    return {
        "employer_id": employer["id"],
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "reservations_confirmed": reservations_confirmed,
        "reservations_completed": reservations_completed,
        "no_show_count": no_show_count,
        "no_show_rate_pct": jnum(no_show_rate),
        "days_used": jnum(rhu(days_used, 2)),
        "days_overage": jnum(rhu(days_overage, 2)),
        "unique_employees_served": len(unique_employees),
        "center_share_pct": jnum(center_share),
        "in_home_share_pct": jnum(in_home_share),
        "min_provider_lifetime_score": jnum(min_lifetime) if min_lifetime is not None else None,
        "renewal_risk_band": band,
    }
