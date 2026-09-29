"""Corrective action plan reads and supervisory review (PRD §3.8)."""

from flask import Blueprint

import validation as v
from errors import ApiError
from middleware import ROLE_SUPERVISING_EXAMINER, authorize, current_user_id
from response import success
from routes.examinations import EXAM_RECORD_READ_ROLES
from services import derive, serialize, transitions
from services.guards import ensure_exam_subject, ensure_exam_writable, get_plan
from db import touch

bp = Blueprint("plans", __name__)

DECISIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")
DECISION_STATUS = {
    "APPROVE": "APPROVED",
    "REJECT": "REJECTED",
    "REQUEST_REVISION": "REVISION_REQUESTED",
}


@bp.get("/corrective-action-plans/<plan_id>")
@authorize(*EXAM_RECORD_READ_ROLES)
def read_plan(plan_id):
    plan = get_plan(plan_id)
    ensure_exam_subject(derive.exam_of_plan(plan))
    return success(serialize.corrective_action_plan(plan))


@bp.post("/corrective-action-plans/<plan_id>/review")
@authorize(ROLE_SUPERVISING_EXAMINER)
def review_plan(plan_id):
    plan = get_plan(plan_id)
    exam = derive.exam_of_plan(plan)
    payload = v.body()
    decision = v.get_enum(payload, "decision", DECISIONS)
    review_note = v.get_str(payload, "review_note", required=False, min_len=None)

    ensure_exam_writable(exam)
    if plan["status"] != "PROPOSED":
        raise ApiError(
            "ERR_ENFORCEMENT_RECORD_STATE_INVALID",
            "Only a PROPOSED plan can be reviewed; this plan is %s." % plan["status"],
        )

    plan["reviewed_by_user_id"] = current_user_id()
    plan["review_note"] = review_note
    plan["status"] = DECISION_STATUS[decision]
    touch(plan)
    if decision == "APPROVE" and exam is not None:
        transitions.exam_plan_approved(exam)
    return success(serialize.corrective_action_plan(plan))
