"""The capacity sweep (PRD 3.5 / 3.10): 1 endpoint.

POST /obstetric-units/{unitId}/capacity-sweep

Setting the clock changes nothing, so this driver is the only place where the
consequences of elapsed time are realised. The six booking steps run in the
pinned order of PRD 3.10 and no other; the three other classes of overdue
obligation (checklist items, escalation chains, support passes) are settled
between step 4 and step 5, so that promotion sees the freshest capacity.
"""

from flask import Blueprint

import calc
import clock
import const
import envelope
import rev
from pipeline import begin
from store import S, sort_rows

bp = Blueprint("sweep", __name__)


# ---------------------------------------------------------------- step 2

def _clear_turnover_beds(unit, instant):
    """TURNOVER -> AVAILABLE once turnover_clear_at is at or before now."""
    cleared = 0
    beds = sort_rows(calc.rows("beds", unit_id=unit["id"]), [("bed_label", "asc")])
    for bed in beds:
        if bed["status"] != "TURNOVER":
            continue
        clear_at = bed.get("turnover_clear_at")
        if clear_at is None or clear_at > instant:
            continue
        bed["status"] = "AVAILABLE"
        bed["turnover_clear_at"] = None
        rev.touch(bed)
        cleared += 1
    return cleared


# ---------------------------------------------------------------- step 3

def _expire_holds(unit, instant):
    """CAPACITY_HELD -> EXPIRED, releasing the bed and the held bed-minutes."""
    expired = []
    held = [b for b in calc.rows("bookings", unit_id=unit["id"])
            if b["status"] == "CAPACITY_HELD"
            and b.get("hold_expires_at") is not None
            and b["hold_expires_at"] <= instant]
    for booking in sort_rows(held, [("hold_expires_at", "asc"), ("created_at", "asc")]):
        calc.release_booking_minutes(unit, booking)
        calc.release_booking_bed(booking)
        booking["status"] = "EXPIRED"
        booking["bed_id"] = None
        booking["hold_expires_at"] = None
        rev.touch(booking)
        expired.append(booking["id"])
    return expired


# ---------------------------------------------------------------- step 4

def _settle_bumped(unit, instant):
    """A bump whose window is still open is requeued; the rest expire."""
    requeued, expired = [], []
    bumped = [b for b in calc.rows("bookings", unit_id=unit["id"])
              if b["status"] == "BUMPED"]
    for booking in sort_rows(bumped, [("requested_start_utc", "asc"),
                                      ("created_at", "asc")]):
        if booking["requested_start_utc"] > instant:
            booking["status"] = "REQUESTED"
            booking["priority_class"] = calc.booking_priority_class(booking)
            requeued.append(booking["id"])
        else:
            booking["status"] = "EXPIRED"
            expired.append(booking["id"])
        booking["bed_id"] = None
        booking["hold_expires_at"] = None
        rev.touch(booking)
    return requeued, expired


# ---------------------------------------------------------------- step 5

def _promotion_bed(unit, booking, projection):
    """Lowest bed_label lexicographically among the collision-free LDR beds."""
    free = [b for b in calc.available_ldr_beds(unit["id"])
            if not calc.bed_reservation_conflict(b["id"], booking["requested_start_utc"],
                                                 projection, exclude_id=booking["id"])]
    if not free:
        return None
    return sort_rows(free, [("bed_label", "asc")])[0]


def _promote(unit, instant, posture, buffer_minutes):
    """One at a time: the budget and the bed census are re-tested per promotion,
    so a budget that fits one booking but not two promotes exactly one."""
    promoted = []
    if posture not in ("OPEN", "RATIO_STRAINED"):
        return promoted
    candidates = [b for b in calc.rows("bookings", unit_id=unit["id"])
                  if b["status"] == "REQUESTED"
                  and b["requested_start_utc"] > instant
                  and (b["priority_class"] != "PATIENT_REQUEST" or posture == "OPEN")]
    for booking in calc.promotion_order(candidates):
        projection = booking["expected_labor_minutes"] + buffer_minutes
        day = calc.booking_day(booking)
        if (calc.day_load(unit, day) + projection
                > unit["max_daily_induction_bed_minutes"]):
            continue
        bed = _promotion_bed(unit, booking, projection)
        if bed is None:
            continue
        booking["projected_occupancy_minutes"] = projection
        booking["status"] = "CAPACITY_HELD"
        booking["bed_id"] = bed["id"]
        booking["hold_expires_at"] = clock.plus_minutes(instant, const.HOLD_TTL_MINUTES)
        rev.touch(booking)
        bed["status"] = "HELD"
        bed["held_booking_id"] = booking["id"]
        rev.touch(bed)
        calc.ledger_move(unit, "held_bed_minutes_by_day", day, projection)
        promoted.append(booking["id"])
    return promoted


# --------------------------------------------- overdue checklist items

def _miss_items(unit, instant):
    """PENDING -> MISSED past due_at_activation_anchored plus a 5-minute grace,
    provided the gate has been reached and the activation is in a live stage."""
    missed = []
    activations = sort_rows(calc.rows("activations", unit_id=unit["id"]),
                            [("activated_at", "asc"), ("created_at", "asc")])
    for activation in activations:
        if activation["status"] not in const.ACTIVATION_LIVE_STAGES:
            continue
        reached = activation.get("highest_stage_reached") or 0
        if activation["status"] == "ACTIVATED":
            # Same deliberate exception as completion: gate 1 counts as reached
            # while the activation is still ACTIVATED, since stage 1 is already
            # running and its clock is already ticking.
            reached = max(reached, 1)
        for item in sort_rows(calc.items_of(activation["id"]),
                              [("step_sequence", "asc")]):
            if item["status"] != "PENDING":
                continue
            due = item.get("due_at_activation_anchored")
            if due is None or item["stage_gate"] > reached:
                continue
            if instant <= clock.plus_minutes(due, const.CHECKLIST_GRACE_MINUTES):
                continue
            item["status"] = "MISSED"
            rev.touch(item)
            activation["missed_step_count"] = (activation.get("missed_step_count") or 0) + 1
            rev.touch(activation)
            missed.append(item["id"])
    return missed


# --------------------------------------------- overdue escalation chains

def _settle_chains(unit, instant):
    """A deadline strictly in the past breaches; a reassessment deadline strictly
    in the past re-arms the chain with its high-water mark preserved."""
    breached, rearmed = [], []
    for enc in sort_rows(calc.encounters_of_unit(unit["id"]), [("created_at", "asc")]):
        found = sort_rows(calc.rows("assessments", encounter_id=enc["id"]),
                          [("assessed_at", "asc"), ("created_at", "asc")])
        for assessment in found:
            status = assessment["escalation_status"]
            due = None
            if status == "ESCALATION_DUE":
                due = assessment.get("escalation_due_at")
            elif status in ("TIER_1_NOTIFIED", "TIER_2_NOTIFIED"):
                due = assessment.get("next_tier_due_at")
            elif status == "REASSESSMENT_PENDING":
                due = assessment.get("reassessment_due_at")
                if due is not None and instant > due and calc.rearmable(assessment):
                    calc.rearm_chain(assessment, instant)
                    rearmed.append(assessment["id"])
                continue
            else:
                continue
            if due is not None and instant > due:
                calc.breach_escalation(assessment, unit)
                breached.append(assessment["id"])
    if breached and (unit.get("escalation_breach_count") or 0) >= const.ESCALATION_BREACH_FREEZE:
        # A count of 2 or more forces at least INDUCTION_FROZEN, so the second
        # breach on a unit bumps the held bookings and releases their beds.
        calc.cascade_bump(unit, ("CAPACITY_HELD",))
    return breached, rearmed


# --------------------------------------------- overdue support passes

def _expire_passes(unit, instant):
    """ISSUED or CHECKED_OUT -> EXPIRED once validity has elapsed (inclusive)."""
    expired = []
    ids = set(e["id"] for e in calc.encounters_of_unit(unit["id"]))
    found = [p for p in S.passes.values()
             if p["encounter_id"] in ids
             and p["status"] in ("ISSUED", "CHECKED_OUT")
             and p.get("valid_until") is not None
             and p["valid_until"] <= instant]
    for record in sort_rows(found, [("valid_until", "asc"), ("created_at", "asc")]):
        record["status"] = "EXPIRED"
        rev.touch(record)
        expired.append(record["id"])
    return expired


def _refresh_drill_currency(unit, instant):
    """Currency is a pure function of elapsed time, so the sweep re-derives it
    before readiness (and therefore posture) is recomputed."""
    for member in calc.rows("staff", unit_id=unit["id"]):
        anchor = member.get("last_validated_drill_at")
        state = "LAPSED"
        if anchor is not None and clock.plus_days(anchor, const.DRILL_CURRENCY_DAYS) >= instant:
            state = "CURRENT"
        if member.get("drill_currency_state") != state:
            member["drill_currency_state"] = state
            rev.touch(member)


@bp.post("/obstetric-units/<unit_id>/capacity-sweep")
def capacity_sweep(unit_id):
    ctx = begin(roles=["ChargeNurse", "PatientAccessCoordinator",
                       "PerinatalSafetyOfficer"],
                path=[("unit", unit_id)])
    unit = ctx.p["unit"]
    instant = clock.now()

    # Step 1: freeze the posture and the buffer derived from it for the whole
    # sweep. Nothing computed later in this request feeds back into either.
    posture_at_sweep = unit.get("staffing_posture")
    buffer_minutes = (const.TURNOVER_BUFFER_OPEN if posture_at_sweep == "OPEN"
                      else const.TURNOVER_BUFFER_STRAINED)
    before = dict((e["id"], e["staffing_state"])
                  for e in calc.encounters_of_unit(unit["id"]))

    beds_cleared = _clear_turnover_beds(unit, instant)            # step 2
    holds_expired = _expire_holds(unit, instant)                  # step 3
    requeued, bookings_expired = _settle_bumped(unit, instant)    # step 4

    # The three other classes of overdue obligation settle here, before
    # promotion, so a breach-driven bump frees capacity the promotion can use.
    missed_items = _miss_items(unit, instant)
    breached_assessments, rearmed = _settle_chains(unit, instant)
    breached_encounters = []
    expired_passes = _expire_passes(unit, instant)

    promoted = _promote(unit, instant, posture_at_sweep, buffer_minutes)  # step 5

    _refresh_drill_currency(unit, instant)
    for enc in sort_rows(calc.encounters_of_unit(unit["id"]), [("created_at", "asc")]):
        previous = before.get(enc["id"])
        calc.recompute_staffing_state(enc)
        if (enc["staffing_state"] == "COVERAGE_BREACH"
                and previous != "COVERAGE_BREACH"
                and enc["id"] not in breached_encounters):
            breached_encounters.append(enc["id"])

    # Step 6: the posture is re-derived exactly once, at the very end.
    unit["last_capacity_sweep_at"] = instant
    calc.rederive_unit(unit)

    return envelope.obj({
        "unit_id": unit["id"],
        "swept_at": clock.fmt_dt(instant),
        "posture_at_sweep": posture_at_sweep,
        "beds_cleared_count": beds_cleared,
        "holds_expired_booking_ids": holds_expired,
        "bookings_requeued_booking_ids": requeued,
        "bookings_expired_booking_ids": bookings_expired,
        "promoted_booking_ids": promoted,
        "promoted_count": len(promoted),
        "missed_checklist_item_ids": missed_items,
        "breached_assessment_ids": breached_assessments,
        "rearmed_assessment_ids": rearmed,
        "expired_pass_ids": expired_passes,
        "breached_encounter_ids": breached_encounters,
        "staffing_posture": unit["staffing_posture"],
        "coverage_deficit_units": unit["coverage_deficit_units"],
    })
