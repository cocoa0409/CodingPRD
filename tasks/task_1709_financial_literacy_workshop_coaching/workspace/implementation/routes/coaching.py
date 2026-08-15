"""Coaching cases, goal plans, outcome snapshots."""
from flask import Blueprint, request

from db import STORE, logical_now
from errors import ApiError
from helpers import (
    body,
    invalid,
    paginate,
    pagination_params,
    req_date,
    req_datetime,
    req_int,
    req_str,
)
from middleware import ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT, forbidden, require_roles
from response import ok
from services.domain import (
    CASELOAD_STATUSES,
    OPEN_CASE_STATUSES,
    active_caseload,
    activate_plan,
    exit_case,
    freeze_plan,
    new_common,
    new_log,
    ser_case,
    ser_plan,
    ser_snapshot,
    sort_by_creation,
    sweep_coach,
    touch,
)

bp = Blueprint("coaching", __name__)

CASE_TARGETS = {"INTAKE", "PLAN_DRAFT", "PLAN_ACTIVE", "ON_HOLD", "COMPLETED", "EXITED"}

REACHABLE = {
    "INTAKE": {"PLAN_DRAFT", "EXITED"},
    "PLAN_DRAFT": {"INTAKE", "PLAN_ACTIVE", "EXITED"},
    "PLAN_ACTIVE": {"ON_HOLD", "COMPLETED", "EXITED"},
    "ON_HOLD": {"PLAN_ACTIVE", "EXITED"},
    "PLAN_STALLED": {"INTAKE", "EXITED"},
    "COMPLETED": set(),
    "EXITED": set(),
}


def _load_case(cid):
    rec = STORE["cases"].get(cid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Coaching case not found.", 404)
    return rec


def _load_plan(pid):
    rec = STORE["goal_plans"].get(pid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Goal plan not found.", 404)
    return rec


# ---------------------------------------------------------------------------
# Coaching cases
# ---------------------------------------------------------------------------

@bp.post("/coaching-cases")
def create_case():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH)
    data = body()
    if role == ROLE_COACH:
        cid = data.get("coach_id")
        if cid is not None and cid != uid:
            forbidden("A coach may open cases only under their own id.")
    participant_id = req_str(data, "participant_id")
    coach_id = req_str(data, "coach_id")
    intake = req_date(data, "intake_date")
    if role == ROLE_COACH and coach_id != uid:
        forbidden("A coach may open cases only under their own id.")

    participant = STORE["participants"].get(participant_id)
    if participant is None:
        raise ApiError(
            "ERR_NOT_FOUND", "Referenced participant_id does not resolve.", 404
        )
    coach = STORE["coaches"].get(coach_id)
    if coach is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced coach_id does not resolve.", 404)

    sweep_coach(coach)
    if coach["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_COACH_NOT_CERTIFIED", "Assigned coach must be CERTIFIED.", 409
        )
    if any(
        c["participant_id"] == participant_id and c["status"] in OPEN_CASE_STATUSES
        for c in STORE["cases"].values()
    ):
        raise ApiError(
            "ERR_OPEN_CASE_EXISTS",
            "Participant already has a coaching case in a non-terminal status.",
            409,
        )
    if active_caseload(coach_id) >= coach["max_caseload"]:
        raise ApiError(
            "ERR_CASELOAD_FULL", "Coach active_caseload has reached max_caseload.", 409
        )

    rec = new_common()
    rec.update(
        {
            "participant_id": participant_id,
            "coach_id": coach_id,
            "intake_date": data["intake_date"],
            "_intake_date": intake,
            "status": "INTAKE",
            "_completed_at": None,
        }
    )
    STORE["cases"][rec["id"]] = rec
    return ok(ser_case(rec), 201)


@bp.get("/coaching-cases")
def list_cases():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    limit, offset = pagination_params()
    items = list(STORE["cases"].values())
    if role == ROLE_PARTICIPANT:
        supplied = request.args.get("participant_id")
        if supplied is not None and supplied != uid:
            forbidden("Participants may read only their own coaching cases.")
        items = [c for c in items if c["participant_id"] == uid]
    participant_id = request.args.get("participant_id")
    coach_id = request.args.get("coach_id")
    status = request.args.get("status")
    if participant_id is not None:
        items = [c for c in items if c["participant_id"] == participant_id]
    if coach_id is not None:
        items = [c for c in items if c["coach_id"] == coach_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_creation(items)
    page, page_meta = paginate(items, limit, offset)
    return ok([ser_case(c) for c in page], 200, pagination=page_meta)


@bp.get("/coaching-cases/<cid>")
def get_case(cid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["cases"].get(cid)
    if role == ROLE_PARTICIPANT and rec is not None and rec["participant_id"] != uid:
        forbidden("Participants may read only their own coaching cases.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Coaching case not found.", 404)
    return ok(ser_case(rec), 200)


@bp.post("/coaching-cases/<cid>/transition")
def transition_case(cid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH)
    rec = STORE["cases"].get(cid)
    data = body()
    target = data.get("target_state")
    new_coach_id = data.get("new_coach_id")

    # Ownership (tier 2): the owning coach, or the coach taking over a stall
    # reassignment. ProgramAdmin is unrestricted.
    if role == ROLE_COACH and rec is not None and rec["coach_id"] != uid:
        takeover = target == "INTAKE" and new_coach_id == uid
        if not takeover:
            forbidden("A coach may drive transitions only on their own cases.")

    # Well-formedness (tier 3).
    if not isinstance(target, str) or target not in CASE_TARGETS:
        invalid(
            "Field 'target_state' must be one of INTAKE, PLAN_DRAFT, PLAN_ACTIVE, "
            "ON_HOLD, COMPLETED, EXITED."
        )
    if new_coach_id is not None and not isinstance(new_coach_id, str):
        invalid("Field 'new_coach_id' must be a string.")

    # Existence (tier 4), left to right: path case id, then new_coach_id.
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Coaching case not found.", 404)
    new_coach = None
    if new_coach_id is not None:
        new_coach = STORE["coaches"].get(new_coach_id)
        if new_coach is None:
            raise ApiError(
                "ERR_NOT_FOUND", "Referenced new_coach_id does not resolve.", 404
            )
        sweep_coach(new_coach)

    # The reassignment path must carry new_coach_id; its absence is malformed
    # and is rejected before transition legality is considered (PRD §3.4).
    if target == "INTAKE" and rec["status"] == "PLAN_STALLED" and new_coach_id is None:
        invalid("Field 'new_coach_id' is required for PLAN_STALLED -> INTAKE.")

    # Transition legality (tier 6/7).
    if target not in REACHABLE[rec["status"]]:
        raise ApiError(
            "ERR_INVALID_TRANSITION",
            "target_state %s is not reachable from %s." % (target, rec["status"]),
            409,
        )

    current = rec["status"]
    if target == "PLAN_DRAFT":  # INTAKE -> PLAN_DRAFT
        coach = STORE["coaches"].get(rec["coach_id"])
        if coach is not None:
            sweep_coach(coach)
        if coach is None or coach["status"] != "CERTIFIED":
            raise ApiError(
                "ERR_COACH_NOT_CERTIFIED",
                "Assigned coach must be CERTIFIED to advance the case.",
                409,
            )
        rec["status"] = "PLAN_DRAFT"

    elif target == "INTAKE" and current == "PLAN_DRAFT":
        # Revision loop: existing DRAFT plans remain DRAFT.
        rec["status"] = "INTAKE"

    elif target == "INTAKE" and current == "PLAN_STALLED":
        # Reassignment path.
        if new_coach["status"] != "CERTIFIED":
            raise ApiError(
                "ERR_COACH_NOT_CERTIFIED",
                "Reassigning coach must be CERTIFIED.",
                409,
            )
        if active_caseload(new_coach_id) >= new_coach["max_caseload"]:
            raise ApiError(
                "ERR_CASELOAD_FULL",
                "Reassigning coach active_caseload has reached max_caseload.",
                409,
            )
        rec["coach_id"] = new_coach_id
        rec["status"] = "INTAKE"
        # A FROZEN plan stays FROZEN until the case again reaches PLAN_ACTIVE.

    elif target == "PLAN_ACTIVE" and current == "PLAN_DRAFT":
        draft = next(
            (
                p
                for p in STORE["goal_plans"].values()
                if p["case_id"] == rec["id"] and p["status"] == "DRAFT"
            ),
            None,
        )
        if draft is None:
            raise ApiError(
                "ERR_PLAN_REQUIRED",
                "PLAN_DRAFT -> PLAN_ACTIVE requires an existing DRAFT goal plan.",
                409,
            )
        draft["status"] = "ACTIVE"
        touch(draft)
        rec["status"] = "PLAN_ACTIVE"

    elif target == "PLAN_ACTIVE" and current == "ON_HOLD":
        coach = STORE["coaches"].get(rec["coach_id"])
        if coach is not None:
            sweep_coach(coach)
        if coach is None or coach["status"] != "CERTIFIED":
            raise ApiError(
                "ERR_COACH_NOT_CERTIFIED",
                "Assigned coach must be CERTIFIED to resume the case.",
                409,
            )
        rec["status"] = "PLAN_ACTIVE"
        for plan in STORE["goal_plans"].values():
            if plan["case_id"] == rec["id"] and plan["status"] == "FROZEN":
                activate_plan(plan)

    elif target == "ON_HOLD":  # PLAN_ACTIVE -> ON_HOLD
        rec["status"] = "ON_HOLD"
        for plan in STORE["goal_plans"].values():
            if plan["case_id"] == rec["id"] and plan["status"] == "ACTIVE":
                freeze_plan(plan)

    elif target == "COMPLETED":  # PLAN_ACTIVE -> COMPLETED
        has_snapshot = any(
            s["participant_id"] == rec["participant_id"]
            for s in STORE["snapshots"].values()
        )
        if not has_snapshot:
            raise ApiError(
                "ERR_OUTCOME_REQUIRED",
                "Case completion requires at least one outcome snapshot for the participant.",
                409,
            )
        rec["status"] = "COMPLETED"
        rec["_completed_at"] = logical_now()
        for plan in STORE["goal_plans"].values():
            if plan["case_id"] == rec["id"] and plan["status"] == "ACTIVE":
                plan["status"] = "ACHIEVED"
                touch(plan)

    elif target == "EXITED":
        exit_case(rec)

    touch(rec)
    return ok(ser_case(rec), 200)


# ---------------------------------------------------------------------------
# Goal plans
# ---------------------------------------------------------------------------

@bp.post("/goal-plans")
def create_goal_plan():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH)
    data = body()
    case = None
    case_id_raw = data.get("case_id")
    if isinstance(case_id_raw, str):
        case = STORE["cases"].get(case_id_raw)
    if role == ROLE_COACH and case is not None and case["coach_id"] != uid:
        forbidden("A coach may create goal plans only for their own cases.")

    case_id = req_str(data, "case_id")
    monthly = req_int(data, "monthly_savings_goal_cents", minimum=1)
    target = req_int(data, "credit_score_target", minimum=300, maximum=850)
    if "expected_case_version" not in data:
        invalid("Field 'expected_case_version' is required.")
    expected = req_int(data, "expected_case_version")

    if case is None:
        case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced case_id does not resolve.", 404)

    # OCC (tier 5) runs before any state or business rule.
    if expected != case["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_case_version does not match the case's current version.",
            412,
        )
    if case["status"] != "PLAN_DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A goal plan can be created only for a PLAN_DRAFT case.",
            409,
        )

    prior_count = sum(
        1 for p in STORE["goal_plans"].values() if p["case_id"] == case["id"]
    )
    for plan in STORE["goal_plans"].values():
        if plan["case_id"] == case["id"] and plan["status"] == "DRAFT":
            plan["status"] = "SUPERSEDED"
            touch(plan)

    rec = new_common()
    rec.update(
        {
            "case_id": case["id"],
            "monthly_savings_goal_cents": monthly,
            "credit_score_target": target,
            "status": "DRAFT",
            "plan_sequence": prior_count + 1,
        }
    )
    STORE["goal_plans"][rec["id"]] = rec
    touch(case)  # goal-plan creation increments the parent case's version
    return ok(ser_plan(rec), 201)


@bp.get("/goal-plans")
def list_goal_plans():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    limit, offset = pagination_params()
    items = list(STORE["goal_plans"].values())
    if role == ROLE_PARTICIPANT:
        own_cases = {
            c["id"] for c in STORE["cases"].values() if c["participant_id"] == uid
        }
        supplied = request.args.get("case_id")
        if supplied is not None and supplied not in own_cases:
            forbidden("Participants may read only their own goal plans.")
        items = [p for p in items if p["case_id"] in own_cases]
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_creation(items)
    page, page_meta = paginate(items, limit, offset)
    return ok([ser_plan(p) for p in page], 200, pagination=page_meta)


@bp.get("/goal-plans/<pid>")
def get_goal_plan(pid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["goal_plans"].get(pid)
    if role == ROLE_PARTICIPANT and rec is not None:
        case = STORE["cases"].get(rec["case_id"])
        if case is None or case["participant_id"] != uid:
            forbidden("Participants may read only their own goal plans.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Goal plan not found.", 404)
    return ok(ser_plan(rec), 200)


# ---------------------------------------------------------------------------
# Outcome snapshots (append-only)
# ---------------------------------------------------------------------------

@bp.post("/outcome-snapshots")
def create_snapshot():
    require_roles(ROLE_ADMIN, ROLE_COACH)
    data = body()
    participant_id = req_str(data, "participant_id")
    recorded_at = req_datetime(data, "recorded_at")
    credit = data.get("credit_score")
    savings = data.get("savings_balance_cents")
    if credit is not None:
        req_int(data, "credit_score", minimum=300, maximum=850)
    if savings is not None:
        req_int(data, "savings_balance_cents", minimum=0)
    if credit is None and savings is None:
        invalid("At least one of credit_score / savings_balance_cents is required.")

    participant = STORE["participants"].get(participant_id)
    if participant is None:
        raise ApiError(
            "ERR_NOT_FOUND", "Referenced participant_id does not resolve.", 404
        )

    rec = new_log()
    rec.update(
        {
            "participant_id": participant_id,
            "recorded_at": recorded_at,
            "credit_score": credit,
            "savings_balance_cents": savings,
        }
    )
    STORE["snapshots"][rec["id"]] = rec
    return ok(ser_snapshot(rec), 201)


@bp.get("/outcome-snapshots")
def list_snapshots():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    limit, offset = pagination_params()
    items = list(STORE["snapshots"].values())
    if role == ROLE_PARTICIPANT:
        supplied = request.args.get("participant_id")
        if supplied is not None and supplied != uid:
            forbidden("Participants may read only their own outcome snapshots.")
        items = [s for s in items if s["participant_id"] == uid]
    participant_id = request.args.get("participant_id")
    if participant_id is not None:
        items = [s for s in items if s["participant_id"] == participant_id]
    # Measurement order: recorded_at ASC, tie-break created_at ASC (PRD §3.6).
    items.sort(key=lambda s: (s["recorded_at"], s["created_at"], s["_seq"]))
    page, page_meta = paginate(items, limit, offset)
    return ok([ser_snapshot(s) for s in page], 200, pagination=page_meta)


@bp.get("/outcome-snapshots/<sid>")
def get_snapshot(sid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["snapshots"].get(sid)
    if role == ROLE_PARTICIPANT and rec is not None and rec["participant_id"] != uid:
        forbidden("Participants may read only their own outcome snapshots.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Outcome snapshot not found.", 404)
    return ok(ser_snapshot(rec), 200)
