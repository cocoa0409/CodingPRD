"""Shared queries and cascades.

Every cascade here is synchronous and complete before the response is returned,
and every row it mutates is registered for a single version bump (PRD 2.8).
"""

from decimal import Decimal

import calc
import clock
import db
import enums
import store


# ------------------------------------------------------------------- selectors

def plan_of(patient):
    return db.insurance_plans[patient["insurance_plan_id"]]


def patient_of_cycle(cycle):
    return db.patients[cycle["patient_id"]]


def lines_of_cycle(cycle_id):
    return store.ordered(
        [line for line in db.cycle_lines.values() if line["cycle_id"] == cycle_id]
    )


def lines_of_prescription(prescription_id):
    return store.ordered(
        [
            line
            for line in db.cycle_lines.values()
            if line["prescription_id"] == prescription_id
        ]
    )


def cycles_of_patient(patient_id):
    return store.ordered(
        [cycle for cycle in db.fill_cycles.values() if cycle["patient_id"] == patient_id]
    )


def prescriptions_of_patient(patient_id):
    return store.ordered(
        [rx for rx in db.prescriptions.values() if rx["patient_id"] == patient_id]
    )


def rolls_of_cycle(cycle_id):
    return store.ordered(
        [roll for roll in db.pouch_rolls.values() if roll["cycle_id"] == cycle_id]
    )


def pouches_of_roll(roll_id):
    return sorted(
        [pouch for pouch in db.pouches.values() if pouch["roll_id"] == roll_id],
        key=lambda p: p["pouch_index"],
    )


def shipments_of_cycle(cycle_id):
    return store.ordered(
        [shp for shp in db.shipments.values() if shp["cycle_id"] == cycle_id]
    )


def shipments_of_patient(patient_id):
    result = []
    for shipment in db.shipments.values():
        cycle = db.fill_cycles.get(shipment["cycle_id"])
        if cycle and cycle["patient_id"] == patient_id:
            result.append(shipment)
    return store.ordered(result)


def memos_of_patient(patient_id):
    return store.ordered(
        [memo for memo in db.credit_memos.values() if memo["patient_id"] == patient_id]
    )


def auth_requests_of_prescription(prescription_id):
    return store.ordered(
        [
            req
            for req in db.refill_authorizations.values()
            if req["prescription_id"] == prescription_id
        ]
    )


def events_of_cycle(cycle_id):
    return [
        event for event in db.adherence_events.values() if event["cycle_id"] == cycle_id
    ]


# ---------------------------------------------------------------- copay totals

def recompute_total_copay(cycle, extra_statuses=()):
    """Sum of already-rounded per-line copays over contributing lines."""
    contributing = ("ADJUDICATED", "PACKED_OUT") + tuple(extra_statuses)
    total = 0
    for line in lines_of_cycle(cycle["id"]):
        if line["line_status"] in contributing:
            total += line["copay_cents"]
    if cycle["total_copay_cents"] != total:
        cycle["total_copay_cents"] = total
        store.touch(cycle)
    return total


def final_copay_cents(cycle):
    """Sum the unrounded per-line amounts, then round the single sum half-up."""
    patient = patient_of_cycle(cycle)
    plan = plan_of(patient)
    total = Decimal(0)
    for line in lines_of_cycle(cycle["id"]):
        if line["line_status"] in ("ADJUDICATED", "PACKED_OUT"):
            prescription = db.prescriptions[line["prescription_id"]]
            total += calc.raw_line_amount(plan, prescription, line["days_supply_filled"])
    return calc.round_half_up(total)


# -------------------------------------------------------------- credit ledger

def recompute_credit_balance(patient):
    balance = sum(
        memo["amount_cents"]
        for memo in db.credit_memos.values()
        if memo["patient_id"] == patient["id"] and memo["status"] == "ISSUED"
    )
    if patient["credit_balance_cents"] != balance:
        patient["credit_balance_cents"] = balance
        store.touch(patient)
    return balance


def issue_memo(patient, cycle_id, reason, amount_cents):
    memo = store.create(
        db.credit_memos,
        {
            "patient_id": patient["id"],
            "cycle_id": cycle_id,
            "applied_to_cycle_id": None,
            "reason": reason,
            "amount_cents": amount_cents,
            "status": "ISSUED",
            "issued_at": clock.now_iso(),
            "applied_at": None,
        },
    )
    recompute_credit_balance(patient)
    return memo


def apply_credits(cycle, patient):
    """Consume outstanding memos against a freshly adjudicated cycle (PRD 2.12)."""
    remaining = cycle["total_copay_cents"]
    applied_total = 0
    for memo in memos_of_patient(patient["id"]):
        if remaining <= 0:
            break
        if memo["status"] != "ISSUED":
            continue
        if memo["cycle_id"] == cycle["id"]:
            continue
        memo["status"] = "APPLIED"
        memo["applied_to_cycle_id"] = cycle["id"]
        memo["applied_at"] = clock.now_iso()
        store.touch(memo)
        applied_total += memo["amount_cents"]
        remaining -= memo["amount_cents"]
    if applied_total:
        cycle["credit_applied_cents"] += applied_total
        store.touch(cycle)
        recompute_credit_balance(patient)
    return applied_total


def void_issued_memos(patient):
    for memo in memos_of_patient(patient["id"]):
        if memo["status"] == "ISSUED":
            memo["status"] = "VOIDED"
            store.touch(memo)
    if patient["credit_balance_cents"] != 0:
        patient["credit_balance_cents"] = 0
        store.touch(patient)


# ----------------------------------------------------------- dispense stamping

def stamp_dispense(prescription, line):
    """Order matters: preserve the prior history before advancing it (PRD 3.3)."""
    prescription["prior_last_dispensed_date"] = prescription["last_dispensed_date"]
    prescription["prior_last_dispensed_days_supply"] = prescription[
        "last_dispensed_days_supply"
    ]
    prescription["last_dispensed_date"] = line["line_start_date"]
    prescription["last_dispensed_days_supply"] = line["days_supply_filled"]
    prescription["days_dispensed_total"] += line["days_supply_filled"]
    prescription["refills_remaining"] -= 1
    prescription["refills_consumed"] += 1
    store.touch(prescription)


def reverse_dispense(prescription, line):
    prescription["days_dispensed_total"] -= line["days_supply_filled"]
    prescription["refills_remaining"] += 1
    prescription["refills_consumed"] -= 1
    prescription["last_dispensed_date"] = prescription["prior_last_dispensed_date"]
    prescription["last_dispensed_days_supply"] = prescription[
        "prior_last_dispensed_days_supply"
    ]
    store.touch(prescription)


# --------------------------------------------------------- payer-dimension flow

def clear_cycle_if_resolved(cycle):
    """EDITS_PENDING -> CLEARED once no hold remains and one line adjudicated."""
    lines = lines_of_cycle(cycle["id"])
    if any(line["line_status"] in ("HELD_AUTH", "HELD_TOO_SOON") for line in lines):
        return False
    if not any(line["line_status"] == "ADJUDICATED" for line in lines):
        return False
    if cycle["insurance_status"] == "EDITS_PENDING":
        cycle["insurance_status"] = "CLEARED"
        store.touch(cycle)
        return True
    return False


# ------------------------------------------------------------- adherence & gate

def rolling_window_counts(patient):
    """Half-open window: [clock - 28 days, clock)."""
    from datetime import timedelta

    window_start = clock.now() - timedelta(days=enums.ROLLING_WINDOW_DAYS)
    window_end = clock.now()
    cycle_ids = {cycle["id"] for cycle in db.fill_cycles.values()
                 if cycle["patient_id"] == patient["id"]}
    taken = 0
    missed = 0
    for event in db.adherence_events.values():
        if event["cycle_id"] not in cycle_ids:
            continue
        if event["event_type"] not in enums.DOSE_EVENT_TYPES:
            continue
        occurred_at = store.ts(event["occurred_at"])
        if occurred_at is None:
            continue
        if window_start <= occurred_at < window_end:
            if event["event_type"] == "POUCH_TAKEN":
                taken += 1
            else:
                missed += 1
    return taken, missed


def expected_pouch_count(patient):
    """Pouches whose dose date has already passed and which are not VOID."""
    today = clock.today()
    cycle_ids = {cycle["id"] for cycle in db.fill_cycles.values()
                 if cycle["patient_id"] == patient["id"]}
    roll_ids = {roll["id"] for roll in db.pouch_rolls.values()
                if roll["cycle_id"] in cycle_ids}
    count = 0
    for pouch in db.pouches.values():
        if pouch["roll_id"] not in roll_ids:
            continue
        if pouch["verification_result"] == "VOID":
            continue
        if store.d(pouch["dose_date"]) < today:
            count += 1
    return count


def adherence_figures(patient):
    taken, missed = rolling_window_counts(patient)
    total = taken + missed
    rolling = 100 if total == 0 else calc.floor_pct(taken, total)
    expected = expected_pouch_count(patient)
    cycle_scoped = 100 if expected == 0 else calc.floor_pct(taken, expected)
    return {
        "taken_count": taken,
        "missed_count": missed,
        "rolling_28_day_score_pct": rolling,
        "expected_pouch_count": expected,
        "cycle_scoped_score_pct": cycle_scoped,
    }


def recompute_adherence_score(patient):
    figures = adherence_figures(patient)
    if patient["adherence_score_pct"] != figures["rolling_28_day_score_pct"]:
        patient["adherence_score_pct"] = figures["rolling_28_day_score_pct"]
        store.touch(patient)
    return figures["rolling_28_day_score_pct"]


def cancel_draft_cycles(patient):
    for cycle in cycles_of_patient(patient["id"]):
        if cycle["packaging_status"] != "DRAFT":
            continue
        cycle["packaging_status"] = "CANCELLED"
        store.touch(cycle)
        for line in lines_of_cycle(cycle["id"]):
            if line["line_status"] == "EXCLUDED_HELD":
                continue
            line["line_status"] = "EXCLUDED_HELD"
            store.touch(line)


def evaluate_pause_gate(patient):
    """Score gate first, then the missed-pickup streak (PRD 3.8)."""
    if patient["autoship_status"] != "ACTIVE":
        return False
    if patient["adherence_score_pct"] < enums.ADHERENCE_PAUSE_THRESHOLD_PCT:
        reason = "ADHERENCE_GAP"
    elif patient["consecutive_missed_pickups"] >= 2:
        reason = "MISSED_PICKUPS"
    else:
        return False
    patient["autoship_status"] = "PAUSED_ADHERENCE"
    patient["pause_reason"] = reason
    store.touch(patient)
    cancel_draft_cycles(patient)
    return True


# ------------------------------------------------------------ adherence events

def append_event(cycle_id, event_type, occurred_at_iso, source, dose_slot=None,
                 pouch_index=None):
    return store.create(
        db.adherence_events,
        {
            "cycle_id": cycle_id,
            "event_type": event_type,
            "occurred_at": occurred_at_iso,
            "dose_slot": dose_slot,
            "pouch_index": pouch_index,
            "source": source,
        },
        versioned=False,
    )


# ------------------------------------------------------------------ roll helper

def recompute_mismatch_count(roll):
    count = 0
    for pouch in pouches_of_roll(roll["id"]):
        if pouch["verification_result"] in ("MISMATCH_COUNT", "UNREADABLE"):
            count += 1
    roll["mismatch_pouch_count"] = count
    return count


def recompute_pouch_count(roll):
    count = sum(
        1
        for pouch in pouches_of_roll(roll["id"])
        if pouch["verification_result"] != "VOID"
    )
    roll["pouch_count"] = count
    return count
