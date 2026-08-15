"""Participant endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_PARTICIPANT_STATE_INVALID,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_string,
    req_date,
    req_int,
    opt_int,
    get_or_404,
    stamp_new,
    touch,
    recompute_trusts_for_plan,
)
from util import fmt_date

bp = Blueprint("participants", __name__)


def participant_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "plan_id": p["plan_id"],
        "employee_ref": p["employee_ref"],
        "hire_date": p["hire_date"],
        "initial_eligibility_date": p["initial_eligibility_date"],
        "annual_compensation_cents": p["annual_compensation_cents"],
        "status": p["status"],
        "is_specified_employee": p["is_specified_employee"],
        "separation_date": p["separation_date"],
        "inclusion_liability_cents": p["inclusion_liability_cents"],
    }


@bp.post("/api/participants")
def create_participant():
    data = body()
    from errors import ERR_INVALID_REQUEST

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    employee_ref = req_string(data, "employee_ref")
    hire = req_date(data, "hire_date")
    elig = req_date(data, "initial_eligibility_date")
    comp = req_int(data, "annual_compensation_cents", lo=1)

    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to enroll a participant")

    participant = stamp_new(
        {
            "plan_id": plan_id,
            "employee_ref": employee_ref,
            "hire_date": fmt_date(hire),
            "initial_eligibility_date": fmt_date(elig),
            "annual_compensation_cents": comp,
            "status": "ACTIVE",
            "is_specified_employee": False,
            "separation_date": None,
            "inclusion_liability_cents": 0,
        }
    )
    db.participants[participant["id"]] = participant
    return ok_object(participant_view(participant), 201)


@bp.get("/api/participants")
def list_participants():
    user_context()
    items = list(db.participants.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [p for p in items if p["plan_id"] == plan_id]
    return _list_response([participant_view(p) for p in items], request.args)


@bp.get("/api/participants/<participantId>")
def get_participant(participantId):
    user_context()
    p = get_or_404(db.participants, participantId, "Participant")
    return ok_object(participant_view(p))


@bp.patch("/api/participants/<participantId>")
def update_participant(participantId):
    data = body()
    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    p = get_or_404(db.participants, participantId, "Participant")

    new_status = data.get("status")
    if new_status is not None:
        if not isinstance(new_status, str):
            from errors import ERR_INVALID_REQUEST

            raise_err(ERR_INVALID_REQUEST, "status must be a string")
        if new_status == "DISABLED":
            if p["status"] not in ("ACTIVE", "SEPARATION_REVIEW", "SEPARATED"):
                raise_err(ERR_PARTICIPANT_STATE_INVALID, "DISABLED requires ACTIVE, SEPARATION_REVIEW, or SEPARATED")
        elif new_status == "DECEASED":
            if p["status"] == "DECEASED":
                raise_err(ERR_PARTICIPANT_STATE_INVALID, "Participant is already DECEASED")
        else:
            raise_err(ERR_PARTICIPANT_STATE_INVALID, f"Status transition to '{new_status}' is not permitted")
        p["status"] = new_status

    if "annual_compensation_cents" in data:
        p["annual_compensation_cents"] = opt_int(data, "annual_compensation_cents", lo=1)

    if new_status is None and "annual_compensation_cents" not in data:
        # No-op patch still bumps version per "every mutation" — but with no
        # fields mutated there is nothing to do; treat as mutation of nothing.
        pass
    touch(p)
    recompute_trusts_for_plan(p["plan_id"])
    return ok_object(participant_view(p))


@bp.post("/api/participants/<participantId>/rehire")
def rehire_participant(participantId):
    body()
    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    p = get_or_404(db.participants, participantId, "Participant")
    if p["status"] != "SEPARATED":
        raise_err(ERR_PARTICIPANT_STATE_INVALID, "Rehire requires status SEPARATED")
    p["status"] = "ACTIVE"
    p["separation_date"] = None
    p["is_specified_employee"] = False
    touch(p)
    return ok_object(participant_view(p))
