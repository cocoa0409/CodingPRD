"""MediationSession endpoints + cyclic state machine + FULL_AGREEMENT cascade
(PRD §3.5)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MEDIATOR_DOUBLE_BOOKED,
    ERR_PLAN_NOT_AGREED,
    ERR_PLAN_NOT_ADOPTED,
    ERR_FORBIDDEN_ROLE,
)
from middleware import (
    require_auth,
    get_json_body,
    paginate_params,
    slice_page,
    current_role,
    current_user_id,
)
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    assert_case_not_terminal,
    require,
)
from services.support import recompute_final_child_orders

bp = Blueprint("mediation", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]
NON_TERMINAL = {"SCHEDULED", "IN_SESSION", "PARTIAL_AGREEMENT"}
TERMINAL_OUTCOMES = {"FULL_AGREEMENT", "IMPASSE"}


def _plan_for_case(case_id):
    for p in db.parenting_plans.values():
        if p["case_id"] == case_id:
            return p
    return None


@bp.post("/api/mediation-sessions")
def create_session():
    require_auth(["Clerk", "Mediator"])()
    body = get_json_body()

    case_id = body.get("case_id")
    case = get_case(case_id)
    assert_case_not_terminal(case)

    mediator_user_id = body.get("mediator_user_id")
    if not isinstance(mediator_user_id, str) or mediator_user_id == "":
        raise APIError(ERR_INVALID_REQUEST, 422, "mediator_user_id is required")

    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    try:
        start = db.parse_iso_dt(start_raw)
        end = db.parse_iso_dt(end_raw)
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, 422, "scheduled_start/scheduled_end must be ISO 8601")
    if start is None or end is None:
        raise APIError(ERR_INVALID_REQUEST, 422, "scheduled_start/scheduled_end are required")
    if not (end > start):
        raise APIError(ERR_INVALID_REQUEST, 422, "scheduled_end must be after scheduled_start")

    # Must equal Case.mediator_user_id.
    if mediator_user_id != case.get("mediator_user_id"):
        raise APIError(ERR_INVALID_REQUEST, 422, "mediator_user_id must equal the case mediator")

    # Double-booking: closed intervals [start,end] vs same mediator's
    # non-terminal sessions; touching endpoints (gap 0) collide (PRD §3.5).
    for s in db.mediation_sessions.values():
        if s["mediator_user_id"] != mediator_user_id:
            continue
        if s["status"] not in NON_TERMINAL:
            continue
        s_start = db.parse_iso_dt(s["scheduled_start"])
        s_end = db.parse_iso_dt(s["scheduled_end"])
        # closed-interval overlap: start <= s_end AND s_start <= end
        if start <= s_end and s_start <= end:
            raise APIError(ERR_MEDIATOR_DOUBLE_BOOKED, 409, "Mediator double-booked")

    # round_no = 1 + count of prior FULL/PARTIAL/IMPASSE sessions on this case.
    concluded = sum(
        1 for s in db.mediation_sessions.values()
        if s["case_id"] == case_id
        and s["status"] in ("FULL_AGREEMENT", "PARTIAL_AGREEMENT", "IMPASSE")
    )

    session = {
        "case_id": case_id,
        "mediator_user_id": mediator_user_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "round_no": concluded + 1,
        "status": "SCHEDULED",
    }
    db.stamp_common(session)
    db.mediation_sessions[session["id"]] = session
    return ok_object(serialize(session), 201)


@bp.get("/api/mediation-sessions/<rid>")
def get_session(rid):
    require_auth(READ_ROLES)()
    s = require(db.mediation_sessions, rid, "MediationSession")
    return ok_object(serialize(s), 200)


@bp.get("/api/mediation-sessions")
def list_sessions():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.mediation_sessions.values()))
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [s for s in items if s["case_id"] == case_id]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


def _require_mediator_matches(case):
    if current_user_id() != case.get("mediator_user_id"):
        raise APIError(ERR_FORBIDDEN_ROLE, 403, "Acting mediator is not the case mediator")


@bp.post("/api/mediation-sessions/<rid>/start")
def start_session(rid):
    require_auth(["Mediator"])()
    s = require(db.mediation_sessions, rid, "MediationSession")
    case = get_case(s["case_id"])
    assert_case_not_terminal(case)
    _require_mediator_matches(case)
    if s["status"] not in ("SCHEDULED", "PARTIAL_AGREEMENT"):
        raise APIError(ERR_INVALID_STATE, 409, "Start requires SCHEDULED or PARTIAL_AGREEMENT")
    if case["status"] != "MEDIATION":
        raise APIError(ERR_INVALID_STATE, 409, "Case must be in MEDIATION")
    s["status"] = "IN_SESSION"
    db.bump(s)
    return ok_object(serialize(s), 200)


@bp.post("/api/mediation-sessions/<rid>/conclude")
def conclude_session(rid):
    require_auth(["Mediator"])()
    s = require(db.mediation_sessions, rid, "MediationSession")
    case = get_case(s["case_id"])
    assert_case_not_terminal(case)
    body = get_json_body()
    outcome = body.get("outcome")
    if outcome not in ("PARTIAL_AGREEMENT", "FULL_AGREEMENT", "IMPASSE"):
        raise APIError(ERR_INVALID_REQUEST, 422, "outcome must be PARTIAL/FULL_AGREEMENT or IMPASSE")
    if s["status"] != "IN_SESSION":
        raise APIError(ERR_INVALID_STATE, 409, "Conclude requires IN_SESSION")

    if outcome == "PARTIAL_AGREEMENT":
        s["status"] = "PARTIAL_AGREEMENT"
        db.bump(s)
        return ok_object(serialize(s), 200)

    if outcome == "IMPASSE":
        s["status"] = "IMPASSE"
        db.bump(s)
        return ok_object(serialize(s), 200)

    # FULL_AGREEMENT — requires the case ParentingPlan AGREED (ERR_PLAN_NOT_AGREED).
    plan = _plan_for_case(case["id"])
    if plan is None or plan["status"] != "AGREED":
        raise APIError(ERR_PLAN_NOT_AGREED, 409, "Parenting plan must be AGREED")

    s["status"] = "FULL_AGREEMENT"
    db.bump(s)

    # Cascade link 2: ParentingPlan AGREED -> ADOPTED.
    plan["status"] = "ADOPTED"
    db.bump(plan)

    # Cascade link 3: recompute FINAL CHILD support orders against adopted plan.
    recompute_final_child_orders(case)

    # Cascade link 4: Case MEDIATION -> AWAITING_JUDGMENT; requires plan ADOPTED.
    if plan["status"] != "ADOPTED":
        raise APIError(ERR_PLAN_NOT_ADOPTED, 409, "Parenting plan must be ADOPTED")
    case["status"] = "AWAITING_JUDGMENT"
    db.bump(case)

    return ok_object(serialize(s), 200)
