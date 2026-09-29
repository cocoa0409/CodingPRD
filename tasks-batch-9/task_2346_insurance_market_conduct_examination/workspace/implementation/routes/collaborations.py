"""Multistate collaboration reads and restitution allocation (PRD §3.9)."""

from flask import Blueprint

import validation as v
from db import now_iso, touch
from errors import ApiError
from middleware import ROLE_MULTISTATE_COORDINATOR, authorize
from response import success
from routes.examinations import EXAM_RECORD_READ_ROLES
from services import calculations as calc
from services import derive, serialize
from services.guards import ensure_exam_subject, ensure_exam_writable, get_collaboration

bp = Blueprint("collaborations", __name__)


@bp.get("/collaborations/<collaboration_id>")
@authorize(*EXAM_RECORD_READ_ROLES)
def read_collaboration(collaboration_id):
    collaboration = get_collaboration(collaboration_id)
    ensure_exam_subject(derive.exam_of_collaboration(collaboration))
    return success(serialize.collaboration(collaboration))


@bp.post("/collaborations/<collaboration_id>/allocate-restitution")
@authorize(ROLE_MULTISTATE_COORDINATOR)
def allocate_restitution(collaboration_id):
    collaboration = get_collaboration(collaboration_id)
    exam = derive.exam_of_collaboration(collaboration)
    v.body()

    ensure_exam_writable(exam)
    if collaboration["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENFORCEMENT_RECORD_STATE_INVALID",
            "Allocation requires an ACTIVE collaboration; this collaboration is %s."
            % collaboration["status"],
        )
    if exam is None or derive.executed_order_of_exam(exam["id"]) is None:
        raise ApiError(
            "ERR_ORDER_NOT_EXECUTED",
            "Allocation requires a consent order in EXECUTED on the examination.",
        )
    total = derive.aggregate_restitution_cents(exam)
    if total <= 0:
        raise ApiError(
            "ERR_RESTITUTION_NOT_CONSERVED",
            "The examination has no sustained restitution to allocate.",
        )

    shares = calc.allocate_restitution(collaboration["participating_states"], total)
    for participant in collaboration["participating_states"]:
        participant["allocated_cents"] = shares[participant["state_code"]]
    collaboration["allocation_completed_at"] = now_iso()
    collaboration["status"] = "SETTLED"
    touch(collaboration)
    return success(serialize.collaboration(collaboration))
