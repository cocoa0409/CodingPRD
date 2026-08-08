"""The twenty-one calculations of PRD section 3, in one place."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from constants import *  # noqa: F401,F403
from timeutil import Ts, add_days, add_hours, day_diff, floor_minutes, mint


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- 1. intake_screening_due_at -------------------------------------------
def intake_screening_due_at(inmate, screening_type):
    booked = inmate["booked_at"]
    if screening_type == "RECEIVING":
        if inmate.get("admission_type") == "NEW_BOOKING":
            return add_hours(booked, RECEIVING_SCREENING_DUE_HOURS)
        return add_hours(booked, TRANSFER_RECEIVING_DUE_HOURS)
    prior = inmate.get("prior_full_assessment_at")
    if inmate.get("admission_type") == "NEW_BOOKING" or prior is None:
        return add_days(booked, FULL_ASSESSMENT_DUE_DAYS)
    return add_days(prior, FULL_ASSESSMENT_DUE_DAYS)


# --- 2. chronic_tier_assignment -------------------------------------------
def chronic_tier_assignment(severity):
    tier = SEVERITY_TO_TIER[severity]
    return tier, TIER_PERIODICITY_DAYS[tier]


# --- 3. chronic_care_next_due_date ----------------------------------------
def chronic_next_due_date(enrollment):
    anchor = enrollment.get("last_visit_at") or enrollment.get("enrolled_at")
    return add_days(anchor, enrollment["periodicity_days"])


# --- 4. sick_call_response_deadline ---------------------------------------
def sick_call_deadline(request_row, new_acuity, first_triage):
    if first_triage:
        anchor = request_row["submitted_at"]
    else:
        old = request_row.get("acuity")
        if ACUITY_RANK[new_acuity] < ACUITY_RANK[old]:      # upgrade
            anchor = request_row["submitted_at"]
        else:                                                # downgrade
            anchor = store.now()
    return anchor, add_hours(anchor, ACUITY_SLA_HOURS[new_acuity])


# --- 5. sick_call_sla_breach ----------------------------------------------
def sick_call_sla_breached(request_row):
    if request_row["status"] == "CANCELLED" or request_row.get("response_deadline_at") is None:
        return False
    seen = request_row.get("seen_at")
    resolution = seen.dt if seen is not None else store.clock_dt()
    return resolution > request_row["response_deadline_at"].dt


# --- 6. medication_dose_timing_class --------------------------------------
def dose_timing_class(acted_at, scheduled_at):
    delta = floor_minutes(acted_at.dt, scheduled_at.dt)
    if delta < -DOSE_EARLY_TOLERANCE_MINUTES:
        return "MISSED_WINDOW"
    if delta <= DOSE_LATE_TOLERANCE_MINUTES:
        return "ON_TIME"
    if delta <= DOSE_MISSED_AFTER_MINUTES:
        return "LATE"
    return "MISSED_WINDOW"


# --- 7. medication_adherence_pct ------------------------------------------
def order_administrations(order_id):
    return [a for a in store.medication_administrations.values() if a["order_id"] == order_id]


def medication_adherence_pct(order):
    if order["route_mode"] == "DOT":
        rows = [a for a in order_administrations(order["id"])
                if a["outcome"] in ("ADMINISTERED", "REFUSED", "MISSED")]
        scored = len(rows)
        if scored == 0:
            return 0.00
        numerator = len([a for a in rows
                         if a["outcome"] == "ADMINISTERED"
                         and a.get("timing_class") in ("ON_TIME", "LATE")])
        return round_half_up(100.0 * numerator / scored, 2)

    clock_date = store.clock_dt().date()
    end_date = order["end_date"].dt.date()
    start_date = order["start_date"].dt.date()
    last_day = min(clock_date, end_date)
    if last_day < start_date:
        expected = 0
    else:
        expected = order["doses_per_day"] * (day_diff(last_day, start_date) + 1)
    if expected == 0:
        return 0.00
    consumed = order["units_dispensed"] - order["units_returned"]
    raw = 100.0 * consumed / expected
    clamped = min(KOP_ADHERENCE_MAX_PCT, max(KOP_ADHERENCE_MIN_PCT, raw))
    return round_half_up(clamped, 2)


def recompute_adherence(order):
    order["adherence_pct"] = medication_adherence_pct(order)


# --- 8. facility_adherence_index ------------------------------------------
def facility_adherence_index(facility_code):
    candidates = []
    for order in store.medication_orders.values():
        if order["status"] not in ("ACTIVE", "HELD"):
            continue
        inmate = store.inmates.get(order["inmate_id"])
        if inmate is None or inmate.get("facility_code") != facility_code:
            continue
        candidates.append(order)
    candidates = store.sort_rows(candidates)
    n = len(candidates)
    if n < ADHERENCE_INDEX_MIN_ORDERS:
        return 0, 0.00
    # PINNED rounding order: per-order values are already rounded to 2 dp; sum
    # the already-rounded values, divide by n, round the quotient once more.
    total = sum(Decimal(str(o["adherence_pct"])) for o in candidates)
    index = round_half_up(total / Decimal(n), 2)
    return n, index


# --- 9. indigency_determination -------------------------------------------
def inmate_ledger_entries(inmate_id):
    return store.sort_rows(
        [e for e in store.ledger_entries.values() if e["inmate_id"] == inmate_id]
    )


def indigency_determination(inmate):
    clock = store.clock_dt()
    window_start = clock - timedelta(days=INDIGENCY_LOOKBACK_DAYS)
    observed = [e["balance_after_cents"] for e in inmate_ledger_entries(inmate["id"])
                if window_start <= e["created_at"].dt <= clock]
    balance = inmate["account_balance_cents"]
    peak = max(observed) if observed else balance
    return balance < INDIGENCY_THRESHOLD_CENTS and peak < INDIGENCY_THRESHOLD_CENTS


# --- 10/11. inmate_account_balance + ledger walk --------------------------
def recompute_balance(inmate):
    running = LEDGER_OPENING_BALANCE_CENTS
    for entry in inmate_ledger_entries(inmate["id"]):
        running += entry["amount_cents"]
        entry["balance_after_cents"] = running
    inmate["account_balance_cents"] = running
    return running


# --- 12. grievance_response_due -------------------------------------------
def grievance_response_due(grievance):
    return add_days(grievance["stage_entered_at"],
                    GRIEVANCE_RESPONSE_WINDOW_DAYS[grievance["stage"]])


def grievance_response_breached(grievance):
    if grievance["status"] not in ("FILED", "UNDER_REVIEW", "REMANDED"):
        return False
    due = grievance.get("response_due_at")
    if due is None:
        return False
    return store.clock_dt() > due.dt


# --- 13. ur_turnaround_deadline -------------------------------------------
def ur_turnaround_deadline(review, referral):
    if review.get("retrospective"):
        return add_hours(review["opened_at"], UR_RETROSPECTIVE_TURNAROUND_HOURS)
    return add_hours(review["opened_at"], UR_TURNAROUND_HOURS[referral["urgency"]])


# --- 14. ur_turnaround_breach ---------------------------------------------
def ur_turnaround_breached(review):
    deadline = review.get("turnaround_deadline_at")
    if deadline is None:
        return False
    decided = review.get("decided_at")
    reference = decided.dt if decided is not None else store.clock_dt()
    return reference > deadline.dt


# --- 15. transport_escort_requirement -------------------------------------
def transport_escort_requirement(inmate):
    return CUSTODY_ESCORT_LEVEL[inmate["custody_level"]]


# --- 16. transport_lead_time_requirement ----------------------------------
def transport_required_lead_minutes(referral, escort_level):
    component = (ESCORT_LEAD_SURCHARGE_MINUTES[escort_level]
                 + NO_SHOW_LEAD_PENALTY_MINUTES * referral.get("no_show_count", 0))
    capped = min(TRANSPORT_MIN_LEAD_MINUTES["ROUTINE"], component)
    return max(TRANSPORT_MIN_LEAD_MINUTES[referral["urgency"]], capped)


def transport_lead_minutes(appointment_at):
    return floor_minutes(appointment_at.dt, store.clock_dt())


# --- 17. transport_slot_overlap -------------------------------------------
def transport_slot_conflict(inmate_id, appointment_at, exclude_ids=()):
    slot = timedelta(minutes=TRANSPORT_SLOT_MINUTES)
    new_start = appointment_at.dt
    new_end = new_start + slot
    for trip in store.transport_orders.values():
        if trip["id"] in exclude_ids:
            continue
        if trip["status"] not in TRANSPORT_SLOT_OCCUPANCY_STATES:
            continue
        referral = store.specialty_referrals.get(trip["referral_id"])
        if referral is None or referral["inmate_id"] != inmate_id:
            continue
        other_start = trip["appointment_at"].dt
        other_end = other_start + slot
        if new_start < other_end and other_start < new_end:
            return True
    return False


# --- 18. medication_schedule_overlap --------------------------------------
def medication_schedule_conflict(inmate_id, drug_class, drug_name, start_date, end_date):
    new_start = start_date.dt.date()
    new_end = end_date.dt.date()
    for order in store.medication_orders.values():
        if order["inmate_id"] != inmate_id:
            continue
        if order["status"] not in MEDICATION_OVERLAP_STATES:
            continue
        if order["drug_class"] != drug_class:
            continue
        if order["drug_name"] == drug_name:
            continue
        other_start = order["start_date"].dt.date()
        other_end = order["end_date"].dt.date()
        if new_start <= other_end and other_start <= new_end:
            return True
    return False


# --- 19. bridge_supply_days -----------------------------------------------
def bridge_supply(inmate_id, release_type, planned_release_at):
    table = (BRIDGE_SUPPLY_DAYS_SCHEDULED if release_type == "SCHEDULED"
             else BRIDGE_SUPPLY_DAYS_UNEXPECTED)
    eligible = store.sort_rows([
        o for o in store.medication_orders.values()
        if o["inmate_id"] == inmate_id and o["status"] in BRIDGE_ELIGIBLE_ORDER_STATES
    ])
    release_date = planned_release_at.dt.date()
    lines = []
    for order in eligible:
        days_left = max(0, day_diff(order["end_date"].dt.date(), release_date) + 1)
        days = min(table[order["drug_class"]], days_left)
        lines.append({"order_id": order["id"], "drug_class": order["drug_class"], "days": days})
    total = sum(line["days"] for line in lines)
    reentry = any(
        e["inmate_id"] == inmate_id and e["status"] == "ACTIVE"
        and e["tier"] in REENTRY_REFERRAL_REQUIRED_TIERS
        for e in store.chronic_enrollments.values()
    )
    return lines, total, reentry


# --- 20. mortality_review_due_at ------------------------------------------
def mortality_review_due_at(death_at):
    return add_days(death_at, MORTALITY_REVIEW_DUE_DAYS)


# --- 21. dose_partition_conservation --------------------------------------
def dose_partition(order_id):
    buckets = {state: 0 for state in ADMIN_OUTCOME}
    rows = order_administrations(order_id)
    for row in rows:
        buckets[row["outcome"]] += 1
    return buckets, len(rows)


# --- read-time projections on the inmate ----------------------------------
def open_sick_call_count(inmate_id):
    return len([s for s in store.sick_calls.values()
                if s["inmate_id"] == inmate_id and s["status"] in OPEN_SICK_CALL_STATES])


def inmate_no_show_count(inmate_id):
    referral_ids = {r["id"] for r in store.specialty_referrals.values()
                    if r["inmate_id"] == inmate_id}
    return len([t for t in store.transport_orders.values()
                if t["referral_id"] in referral_ids and t["status"] == "NO_SHOW"])


def referral_no_show_count(referral_id):
    return len([t for t in store.transport_orders.values()
                if t["referral_id"] == referral_id and t["status"] == "NO_SHOW"])
