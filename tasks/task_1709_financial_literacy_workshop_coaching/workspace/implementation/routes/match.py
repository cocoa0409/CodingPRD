"""Match pools and match enrollments (deposits, payout, forfeit)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import STORE
from errors import ApiError
from helpers import (
    body,
    invalid,
    opt_datetime,
    paginate,
    pagination_params,
    req_int,
    req_number,
    req_str,
)
from middleware import ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT, forbidden, require_roles
from response import ok
from services.domain import (
    ENROLLMENT_OPEN_STATUSES,
    new_common,
    ser_enrollment,
    ser_pool,
    sort_by_creation,
    touch,
)

bp = Blueprint("match", __name__)


def _load_pool(pid):
    rec = STORE["pools"].get(pid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Match pool not found.", 404)
    return rec


def _load_enrollment(eid):
    rec = STORE["enrollments"].get(eid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Match enrollment not found.", 404)
    return rec


# ---------------------------------------------------------------------------
# Match pools
# ---------------------------------------------------------------------------

@bp.post("/match-pools")
def create_pool():
    require_roles(ROLE_ADMIN)
    data = body()
    name = req_str(data, "name")
    total = req_int(data, "total_funded_cents", minimum=1)
    threshold = req_int(data, "income_threshold_cents")
    ratio_below = req_number(data, "match_ratio_below")
    ratio_above = req_number(data, "match_ratio_above")
    cap = req_int(data, "per_participant_cap_cents", minimum=1)

    rec = new_common()
    rec.update(
        {
            "name": name,
            "total_funded_cents": total,
            "income_threshold_cents": threshold,
            "match_ratio_below": ratio_below,
            "match_ratio_above": ratio_above,
            "per_participant_cap_cents": cap,
            "uncommitted_cents": total,
            "paid_out_cents": 0,
            "status": "ACTIVE",
        }
    )
    STORE["pools"][rec["id"]] = rec
    return ok(ser_pool(rec), 201)


@bp.get("/match-pools/<pid>")
def get_pool(pid):
    require_roles(ROLE_ADMIN, ROLE_COACH)
    return ok(ser_pool(_load_pool(pid)), 200)


@bp.post("/match-pools/<pid>/close")
def close_pool(pid):
    require_roles(ROLE_ADMIN)
    rec = _load_pool(pid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE pool can be closed.", 409)
    if any(
        e["pool_id"] == pid and e["status"] in ENROLLMENT_OPEN_STATUSES
        for e in STORE["enrollments"].values()
    ):
        raise ApiError(
            "ERR_POOL_HAS_OPEN_ENROLLMENTS",
            "Pool still holds enrollments in ACTIVE, MATCH_PAUSED, or GOAL_MET.",
            409,
        )
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(ser_pool(rec), 200)


# ---------------------------------------------------------------------------
# Match enrollments
# ---------------------------------------------------------------------------

@bp.post("/match-enrollments")
def create_enrollment():
    require_roles(ROLE_ADMIN, ROLE_COACH)
    data = body()
    participant_id = req_str(data, "participant_id")
    pool_id = req_str(data, "pool_id")
    goal_plan_id = req_str(data, "goal_plan_id")
    savings_goal = req_int(data, "savings_goal_cents", minimum=1)

    # Existence, left to right in payload order.
    participant = STORE["participants"].get(participant_id)
    if participant is None:
        raise ApiError(
            "ERR_NOT_FOUND", "Referenced participant_id does not resolve.", 404
        )
    pool = STORE["pools"].get(pool_id)
    if pool is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced pool_id does not resolve.", 404)
    plan = STORE["goal_plans"].get(goal_plan_id)
    if plan is None:
        raise ApiError(
            "ERR_NOT_FOUND", "Referenced goal_plan_id does not resolve.", 404
        )

    # The plan check runs first (PRD §3.7).
    if plan["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PLAN_NOT_ACTIVE",
            "Match enrollment requires the referenced goal plan to be ACTIVE.",
            409,
        )
    if pool["status"] != "ACTIVE" or pool["uncommitted_cents"] < pool["per_participant_cap_cents"]:
        raise ApiError(
            "ERR_POOL_INSUFFICIENT",
            "Pool cannot fully back a new enrollment's per-participant cap.",
            402,
        )

    rec = new_common()
    rec.update(
        {
            "participant_id": participant_id,
            "pool_id": pool_id,
            "goal_plan_id": goal_plan_id,
            "savings_goal_cents": savings_goal,
            "status": "ACTIVE",
            "total_deposited_cents": 0,
            "accrued_unpaid_cents": 0,
        }
    )
    STORE["enrollments"][rec["id"]] = rec
    return ok(ser_enrollment(rec), 201)


@bp.get("/match-enrollments")
def list_enrollments():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    limit, offset = pagination_params()
    items = list(STORE["enrollments"].values())
    if role == ROLE_PARTICIPANT:
        supplied = request.args.get("participant_id")
        if supplied is not None and supplied != uid:
            forbidden("Participants may read only their own enrollments.")
        items = [e for e in items if e["participant_id"] == uid]
    for field in ("participant_id", "pool_id", "goal_plan_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [e for e in items if e[field] == v]
    items = sort_by_creation(items)
    page, page_meta = paginate(items, limit, offset)
    return ok([ser_enrollment(e) for e in page], 200, pagination=page_meta)


@bp.get("/match-enrollments/<eid>")
def get_enrollment(eid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["enrollments"].get(eid)
    if role == ROLE_PARTICIPANT and rec is not None and rec["participant_id"] != uid:
        forbidden("Participants may read only their own enrollments.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Match enrollment not found.", 404)
    return ok(ser_enrollment(rec), 200)


@bp.post("/match-enrollments/<eid>/deposits")
def create_deposit(eid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["enrollments"].get(eid)
    if role == ROLE_PARTICIPANT and rec is not None and rec["participant_id"] != uid:
        forbidden("Participants may deposit only against their own enrollments.")
    data = body()
    amount = req_int(data, "amount_cents", minimum=1)
    opt_datetime(data, "deposited_at")  # accepted, optional; not persisted
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Match enrollment not found.", 404)

    if rec["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE",
            "Deposits require an ACTIVE enrollment.",
            409,
        )

    pool = STORE["pools"][rec["pool_id"]]
    participant = STORE["participants"][rec["participant_id"]]
    if participant["annual_income_cents"] < pool["income_threshold_cents"]:
        ratio = Decimal(str(pool["match_ratio_below"]))
    else:
        ratio = Decimal(str(pool["match_ratio_above"]))
    candidate = int(
        (ratio * Decimal(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

    # Fiscal guards: pool solvency before the per-participant cap (PRD §2.7).
    if candidate > pool["uncommitted_cents"]:
        raise ApiError(
            "ERR_POOL_INSUFFICIENT",
            "Pool uncommitted_cents cannot cover the deposit accrual.",
            402,
        )
    cap_remaining = pool["per_participant_cap_cents"] - rec["accrued_unpaid_cents"]
    if candidate > cap_remaining:
        raise ApiError(
            "ERR_MATCH_CAP_EXCEEDED",
            "Deposit accrual exceeds the per-participant cap remaining.",
            409,
        )

    rec["total_deposited_cents"] += amount
    rec["accrued_unpaid_cents"] += candidate
    pool["uncommitted_cents"] -= candidate
    if rec["total_deposited_cents"] >= rec["savings_goal_cents"]:
        rec["status"] = "GOAL_MET"
    touch(rec)
    return ok(ser_enrollment(rec), 201)


@bp.post("/match-enrollments/<eid>/payout")
def payout_enrollment(eid):
    require_roles(ROLE_ADMIN)
    rec = _load_enrollment(eid)
    if rec["status"] != "GOAL_MET":
        raise ApiError(
            "ERR_GOAL_NOT_MET", "Payout requires a GOAL_MET enrollment.", 409
        )
    pool = STORE["pools"][rec["pool_id"]]
    pool["paid_out_cents"] += rec["accrued_unpaid_cents"]
    rec["accrued_unpaid_cents"] = 0
    rec["status"] = "PAID_OUT"
    touch(rec)
    return ok(ser_enrollment(rec), 200)


@bp.post("/match-enrollments/<eid>/forfeit")
def forfeit_enrollment(eid):
    require_roles(ROLE_ADMIN)
    rec = _load_enrollment(eid)
    if rec["status"] not in ("ACTIVE", "MATCH_PAUSED", "GOAL_MET"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE, MATCH_PAUSED, or GOAL_MET enrollment can be forfeited.",
            409,
        )
    pool = STORE["pools"][rec["pool_id"]]
    pool["uncommitted_cents"] += rec["accrued_unpaid_cents"]
    rec["accrued_unpaid_cents"] = 0
    rec["status"] = "FORFEITED"
    touch(rec)
    return ok(ser_enrollment(rec), 200)
