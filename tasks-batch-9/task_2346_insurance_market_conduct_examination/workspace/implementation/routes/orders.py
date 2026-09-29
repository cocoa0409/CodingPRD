"""Consent order reads and execution by the carrier (PRD §3.8)."""

from flask import Blueprint

import validation as v
from db import now_iso, touch
from errors import ApiError
from middleware import ROLE_INSURER_RESPONDENT, authorize
from response import success
from routes.examinations import EXAM_RECORD_READ_ROLES
from services import derive, serialize
from services.guards import ensure_exam_subject, ensure_exam_writable, get_order

bp = Blueprint("orders", __name__)


@bp.get("/consent-orders/<order_id>")
@authorize(*EXAM_RECORD_READ_ROLES)
def read_order(order_id):
    order = get_order(order_id)
    ensure_exam_subject(derive.exam_of_order(order))
    return success(serialize.consent_order(order))


@bp.post("/consent-orders/<order_id>/execute")
@authorize(ROLE_INSURER_RESPONDENT)
def execute_order(order_id):
    order = get_order(order_id)
    exam = ensure_exam_subject(derive.exam_of_order(order))
    payload = v.body()
    signed_by = v.get_str(payload, "signed_by", min_len=1)

    ensure_exam_writable(exam)
    if order["status"] != "DRAFT":
        raise ApiError(
            "ERR_ENFORCEMENT_RECORD_STATE_INVALID",
            "Only a DRAFT consent order can be executed; this order is %s."
            % order["status"],
        )

    order["signed_by"] = signed_by
    order["executed_at"] = now_iso()
    order["status"] = "EXECUTED"
    touch(order)
    return success(serialize.consent_order(order))
