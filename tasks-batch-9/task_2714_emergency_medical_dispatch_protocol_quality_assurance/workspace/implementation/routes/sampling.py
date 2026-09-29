"""Sampling periods and the two selection routes (PRD 3.4)."""
from flask import Blueprint, request

import calc
import cascades
import helpers
import validate
from auth import ALL_OPERATORS, require
from cascades import set_fields
from envelope import ok, ok_array, public
from errors import fail
from routes.dispatchers import CALL_TYPES
from routes.protocols import version_in_force
from store import base_row, clock, db

bp = Blueprint("sampling", __name__)

SAMPLING_MODES = ("RANDOM", "TARGETED", "MIXED")
TARGETED_REASONS = ("COMPLAINT", "HIGH_RISK_OUTCOME", "SENTINEL_FLAG", "NEW_HIRE_AUDIT")


def _high_risk(call):
    """PRD 3.4 — any one of the three conditions makes the review high risk."""
    if call["call_type"] == "CARDIAC_ARREST":
        return True
    if call["cardiac_arrest_confirmed"]:
        return True
    return calc.determinant_level(call["dispatched_determinant_code"]) == "E"


def new_review(period, call, selection_mode, selection_reason, pinned):
    review = base_row()
    review.update(
        {
            "sampling_period_id": period["id"],
            "call_record_id": call["id"],
            "dispatcher_id": call["dispatcher_id"],
            "protocol_version_id": pinned["id"],
            "selection_mode": selection_mode,
            "selection_reason": selection_reason,
            "high_risk": _high_risk(call),
            "status": "SELECTED",
            "current_sheet_round": 0,
            "provisional_composite_score": None,
            "pre_penalty_composite_score": None,
            "determinant_accuracy": None,
            "penalty_points": None,
            "final_composite_score": None,
            "compliant": None,
            "rebuttal_round_count": 0,
            "scored_at": None,
            "finalized_at": None,
            "voided_at": None,
            "void_reason": None,
        }
    )
    db.reviews[review["id"]] = review
    set_fields(call, {"status": "SELECTED"})
    return review


def _in_window(instant, start, end):
    """Half-open: the lower bound is inside, the upper bound is not."""
    return start <= instant < end


@bp.post("/audit-programs/<program_id>/sampling-periods")
@require("QaSupervisor")
def open_period(program_id):
    payload = validate.body()
    call_type = validate.get_enum(payload, "call_type", CALL_TYPES)
    period_start = validate.get_instant(payload, "period_start")
    period_end = validate.get_instant(payload, "period_end")
    mode = validate.get_enum(payload, "sampling_mode", SAMPLING_MODES)
    target = validate.get_int(payload, "target_sample_count", minimum=1)

    program = helpers.program(program_id)

    if period_end <= period_start:
        fail("ERR_INVALID_TIME_WINDOW", "period_end must be after period_start.")

    period = base_row()
    period.update(
        {
            "program_id": program["id"],
            "call_type": call_type,
            "period_start": period_start,
            "period_end": period_end,
            "sampling_mode": mode,
            "target_sample_count": target,
            "selected_review_count": 0,
            "finalized_review_count": 0,
            "status": "OPEN",
            "closed_at": None,
            "locked_at": None,
        }
    )
    db.sampling_periods[period["id"]] = period
    return ok(public(period), 201)


@bp.get("/audit-programs/<program_id>/sampling-periods")
@require(*ALL_OPERATORS)
def list_periods(program_id):
    limit, offset = validate.pagination()
    program = helpers.program(program_id)
    filters = {
        "status": request.args.get("status"),
        "call_type": request.args.get("call_type"),
    }
    rows = [
        p
        for p in db.sampling_periods.values()
        if p["program_id"] == program["id"] and helpers.matches(p, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


def _eligible_pool(period):
    """PRD 3.4 — the systematic-draw candidate pool, deterministically ordered."""
    pool = []
    for call in db.call_records.values():
        if call["call_type"] != period["call_type"]:
            continue
        if call["status"] != "INGESTED":
            continue
        if not _in_window(call["received_at"], period["period_start"], period["period_end"]):
            continue
        dispatcher = db.dispatchers.get(call["dispatcher_id"])
        if dispatcher is None or dispatcher["program_id"] != period["program_id"]:
            continue
        if dispatcher["dispatch_privilege"] == "SUSPENDED":
            continue
        pool.append(call)
    pool.sort(key=lambda c: (c["received_at"], c["call_reference"]))
    return pool


@bp.post("/sampling-periods/<period_id>/draw-random-sample")
@require("QaSupervisor")
def draw_random_sample(period_id):
    payload = validate.body()
    requested_count = validate.get_int(payload, "requested_count", minimum=1)
    period = helpers.sampling_period(period_id)

    if period["status"] != "OPEN":
        fail("ERR_PERIOD_NOT_OPEN", "Selection requires an OPEN sampling period.")

    pool = _eligible_pool(period)
    remaining = period["target_sample_count"] - period["selected_review_count"]
    wanted = min(requested_count, max(0, remaining), len(pool))

    # The whole draw is atomic: every pin is resolved before anything is written.
    drawn = []
    pins = []
    if wanted > 0:
        indices = calc.systematic_indices(len(pool), requested_count, wanted)
        drawn = [pool[index] for index in indices]
        pins = []
        for call in drawn:
            pinned = version_in_force(period["program_id"], call["received_at"])
            if pinned is None:
                fail(
                    "ERR_NO_PROTOCOL_VERSION_IN_FORCE",
                    "No protocol version governs the instant of call %s."
                    % call["call_reference"],
                )
            pins.append(pinned)

    if period["sampling_mode"] not in ("RANDOM", "MIXED"):
        fail(
            "ERR_SAMPLING_MODE_MISMATCH",
            "This period does not accept the systematic random draw.",
        )
    if remaining <= 0:
        fail("ERR_SAMPLE_QUOTA_FILLED", "The period's sample quota is already filled.")
    if not pool:
        fail("ERR_NO_ELIGIBLE_CALLS", "No eligible call records for this period.")

    reviews = []
    for call, pinned in zip(drawn, pins):
        reviews.append(new_review(period, call, "RANDOM", "SYSTEMATIC_DRAW", pinned))
    cascades.recompute_period_counters(period)
    return ok_array([public(review) for review in reviews], 201)


@bp.post("/sampling-periods/<period_id>/target-review")
@require("QaSupervisor", "QaReviewer")
def target_review(period_id):
    payload = validate.body()
    call_record_id = validate.get_str(payload, "call_record_id")
    reason = validate.get_enum(payload, "selection_reason", TARGETED_REASONS)

    period = helpers.sampling_period(period_id)
    call = helpers.call_record(call_record_id)

    if period["status"] != "OPEN":
        fail("ERR_PERIOD_NOT_OPEN", "Selection requires an OPEN sampling period.")

    dispatcher = db.dispatchers.get(call["dispatcher_id"])
    if dispatcher is None or dispatcher["program_id"] != period["program_id"]:
        fail(
            "ERR_PROGRAM_SCOPE_MISMATCH",
            "The call was handled by a dispatcher of another programme.",
        )
    if call["call_type"] != period["call_type"]:
        fail("ERR_CALL_TYPE_MISMATCH", "The call type does not match the period.")

    pinned = version_in_force(period["program_id"], call["received_at"])
    if pinned is None:
        fail(
            "ERR_NO_PROTOCOL_VERSION_IN_FORCE",
            "No protocol version governs the instant of this call.",
        )

    if not _in_window(call["received_at"], period["period_start"], period["period_end"]):
        fail("ERR_CALL_OUTSIDE_PERIOD", "received_at falls outside the period window.")

    if call["status"] == "SELECTED":
        fail("ERR_CALL_ALREADY_SELECTED", "This call has already been selected.")
    if period["sampling_mode"] not in ("TARGETED", "MIXED"):
        fail(
            "ERR_SAMPLING_MODE_MISMATCH",
            "This period does not accept targeted selection.",
        )
    if period["selected_review_count"] >= period["target_sample_count"]:
        fail("ERR_SAMPLE_QUOTA_FILLED", "The period's sample quota is already filled.")

    review = new_review(period, call, "TARGETED", reason, pinned)
    cascades.recompute_period_counters(period)
    return ok(public(review), 201)


@bp.post("/sampling-periods/<period_id>/close")
@require("QaSupervisor")
def close_period(period_id):
    payload = validate.body()
    validate.get_str(payload, "closing_note", required=False)
    period = helpers.sampling_period(period_id)

    if period["status"] != "OPEN":
        fail("ERR_PERIOD_NOT_OPEN", "Only an OPEN period may be closed.")

    if period["selected_review_count"] < period["target_sample_count"]:
        fail("ERR_SAMPLE_QUOTA_NOT_MET", "The period's sample quota is not met.")

    program = db.programs.get(period["program_id"])
    probation = False
    for review in cascades.reviews_of_period(period["id"]):
        if review["status"] == "VOIDED":
            continue
        dispatcher = db.dispatchers.get(review["dispatcher_id"])
        if dispatcher is not None and dispatcher["compliance_posture"] == "PROBATION":
            probation = True
            break
    if (
        probation
        and program is not None
        and period["target_sample_count"] < program["escalated_sample_floor"]
    ):
        fail(
            "ERR_ESCALATED_SAMPLING_REQUIRED",
            "A dispatcher on PROBATION requires the escalated sample floor.",
        )

    set_fields(period, {"status": "CLOSED", "closed_at": clock()})
    return ok(public(period))
