"""Put option exercise endpoints (PRD 3.8)."""

from flask import Blueprint

import calc
import responses
import services
import validation as v
from auth import (PARTICIPANT, READ_ROLES, TRUSTEE, caller_id, endpoint,
                  is_participant_caller)
from clock import CLOCK
from db import DB, insert, serialize, sorted_rows, touch
from errors import fail

bp = Blueprint("puts", __name__)

PRIORITY_BY_ELECTION_TYPE = {
    "DEATH": "DEATH",
    "RETIREMENT": "RETIREMENT_DISABILITY",
    "DISABILITY": "RETIREMENT_DISABILITY",
    "TERMINATION": "TERMINATION",
    "DIVERSIFICATION": "DIVERSIFICATION",
}


@bp.post("/put-option-exercises")
@endpoint([PARTICIPANT])
def create_exercise():
    body = v.body()
    election_id = v.req_string(body, "distribution_election_id")
    shares_tendered = v.req_integer(body, "shares_tendered", minimum=1)

    election = services.get_election(election_id)
    participant = services.get_participant(election["participant_id"])

    if is_participant_caller() and caller_id() != participant["id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    if plan["current_share_price_cents"] <= 0:
        fail("ERR_NO_APPROVED_VALUATION")

    today = CLOCK.today()
    open_date = participant["put_window_open_date"]
    close_date = participant["put_window_close_date"]
    if not open_date or not close_date:
        fail("ERR_PUT_WINDOW_CLOSED")
    if not (calc.iso_to_date(open_date) <= today <= calc.iso_to_date(close_date)):
        fail("ERR_PUT_WINDOW_CLOSED")

    available = participant["distributed_shares_cumulative"] - participant["tendered_shares_cumulative"]
    if shares_tendered > available:
        fail("ERR_INSUFFICIENT_SHARES")

    share_price_cents = plan["current_share_price_cents"]
    exercise = insert(DB.put_option_exercises, {
        "distribution_election_id": election_id,
        "participant_id": participant["id"],
        "shares_tendered": shares_tendered,
        "window_open_date": open_date,
        "window_close_date": close_date,
        "exercise_date": today.isoformat(),
        "share_price_cents": share_price_cents,
        "exercise_amount_cents": share_price_cents * shares_tendered,
        "priority_class": PRIORITY_BY_ELECTION_TYPE[election["election_type"]],
        "funded_cents": 0,
        "funded_by_user_id": None,
        "settled_date": None,
        "status": "PENDING",
        "cancel_reason": None,
    })

    participant["tendered_shares_cumulative"] += shares_tendered
    touch(participant)
    return responses.ok(serialize(exercise), 201)


@bp.get("/put-option-exercises/<exercise_id>")
@endpoint(READ_ROLES)
def read_exercise(exercise_id):
    return responses.ok(serialize(services.get_exercise(exercise_id)))


@bp.get("/put-option-exercises")
@endpoint(READ_ROLES)
def list_exercises():
    limit, offset = v.pagination()
    participant_id = v.query_str("participant_id")
    election_id = v.query_str("distribution_election_id")
    status = v.query_str("status")
    rows = sorted_rows(DB.put_option_exercises)
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if election_id is not None:
        rows = [r for r in rows if r["distribution_election_id"] == election_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return services.paged(rows, limit, offset)


@bp.post("/put-option-exercises/<exercise_id>/fund")
@endpoint([TRUSTEE])
def fund_exercise(exercise_id):
    exercise = services.get_exercise(exercise_id)
    participant = services.get_participant(exercise["participant_id"])
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    if exercise["status"] not in ("PENDING", "DEFERRED"):
        fail("ERR_INVALID_STATE")

    today = CLOCK.today()
    if not (calc.iso_to_date(exercise["window_open_date"]) <= today
            <= calc.iso_to_date(exercise["window_close_date"])):
        fail("ERR_PUT_WINDOW_CLOSED")

    amount = exercise["exercise_amount_cents"]
    if plan["repurchase_reserve_cents"] < amount:
        fail("ERR_INSUFFICIENT_REPURCHASE_RESERVE")

    exercise["status"] = "FUNDED"
    exercise["funded_cents"] = amount
    exercise["funded_by_user_id"] = caller_id()
    touch(exercise)

    plan["repurchase_reserve_cents"] -= amount
    plan["committed_repurchase_cents"] += amount
    posture = services.recompute_repurchase_posture(plan)
    if posture == "UNDERFUNDED":
        services.defer_pending_exercises(plan, skip_id=exercise["id"])
    touch(plan)
    return responses.ok(serialize(exercise))


@bp.post("/put-option-exercises/<exercise_id>/cancel")
@endpoint([TRUSTEE, PARTICIPANT])
def cancel_exercise(exercise_id):
    body = v.body()
    reason = v.req_string(body, "reason")

    exercise = services.get_exercise(exercise_id)

    if is_participant_caller() and caller_id() != exercise["participant_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    participant = services.get_participant(exercise["participant_id"])
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    if exercise["status"] not in ("PENDING", "DEFERRED", "FUNDED"):
        fail("ERR_INVALID_STATE")

    returned = exercise["funded_cents"]
    if returned:
        plan["repurchase_reserve_cents"] += returned
        plan["committed_repurchase_cents"] -= returned
        exercise["funded_cents"] = 0

    exercise["status"] = "CANCELLED"
    exercise["cancel_reason"] = reason
    touch(exercise)

    participant["tendered_shares_cumulative"] -= exercise["shares_tendered"]
    touch(participant)

    posture = services.recompute_repurchase_posture(plan)
    if posture == "FUNDED":
        services.restore_deferred_exercises(plan)
    touch(plan)
    return responses.ok(serialize(exercise))


@bp.post("/put-option-exercises/<exercise_id>/settle")
@endpoint([TRUSTEE])
def settle_exercise(exercise_id):
    exercise = services.get_exercise(exercise_id)
    participant = services.get_participant(exercise["participant_id"])
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    if exercise["status"] != "FUNDED":
        fail("ERR_INVALID_STATE")

    exercise["status"] = "SETTLED"
    exercise["settled_date"] = CLOCK.today_iso()
    touch(exercise)

    funded = exercise["funded_cents"]
    plan["committed_repurchase_cents"] -= funded
    plan["cumulative_repurchase_settled_cents"] += funded
    plan["reacquired_shares"] += exercise["shares_tendered"]
    plan["total_plan_shares"] += exercise["shares_tendered"]
    touch(plan)
    return responses.ok(serialize(exercise))
