"""AdverseActionCase endpoints."""
from flask import Blueprint, request

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_CASE_NOT_AWAITING, ERR_SOD, ERR_ADVERSE_WAIT,
)
from middleware import (
    auth, require_role, parse_pagination, sort_key, ALL_ROLES,
)
from response import success_object, success_list
from services import refresh_case
from timeutil import now

bp = Blueprint("cases", __name__)


@bp.route("/adverse-action-cases", methods=["GET"])
def list_cases():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.cases.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        rows = [c for c in rows if c["order_id"] == order_id]
    for case in rows:
        refresh_case(case)
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


def _load_case(case_id):
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Adverse action case not found")
    return case


@bp.route("/adverse-action-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    case = _load_case(case_id)
    refresh_case(case)
    return success_object(case, 200)


@bp.route("/adverse-action-cases/<case_id>/send-final-notice",
          methods=["POST"])
def send_final_notice(case_id):
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    case = _load_case(case_id)
    refresh_case(case)
    # state (4)
    if case["status"] not in ("WAITING_PERIOD", "ELIGIBLE_FOR_FINAL"):
        raise ApiError(ERR_CASE_NOT_AWAITING, 409,
                       "Final notice requires case WAITING_PERIOD or "
                       "ELIGIBLE_FOR_FINAL")
    # segregation of duties (5.4) — checked BEFORE the temporal gate
    if uid == case["initiated_by_user_id"]:
        raise ApiError(ERR_SOD, 403,
                       "Final notice issuer must differ from the adjudicator "
                       "who initiated adverse action")
    # temporal (7.2)
    if now() < case["earliest_final_notice_at"]:
        raise ApiError(ERR_ADVERSE_WAIT, 409,
                       "Adverse waiting period has not elapsed")
    case["status"] = "FINAL_NOTICE_SENT"
    case["final_notice_sent_at"] = now()
    case["final_notice_issuer_user_id"] = uid
    bump(case)
    order = db.orders.get(case["order_id"])
    if order is not None:
        order["adjudication_status"] = "FINAL_ADVERSE"
        order["fulfillment_status"] = "CLOSED"
        bump(order)
    return success_object(case, 200)


@bp.route("/adverse-action-cases/<case_id>/abort", methods=["POST"])
def abort_case(case_id):
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    case = _load_case(case_id)
    refresh_case(case)
    if case["status"] not in ("WAITING_PERIOD", "ELIGIBLE_FOR_FINAL"):
        raise ApiError(ERR_CASE_NOT_AWAITING, 409,
                       "Abort requires case WAITING_PERIOD or "
                       "ELIGIBLE_FOR_FINAL")
    case["status"] = "ABORTED"
    case["hold_started_at"] = None
    bump(case)
    order = db.orders.get(case["order_id"])
    if order is not None and order["adjudication_status"] == "PRE_ADVERSE_PENDING":
        order["adjudication_status"] = "PENDING_REVIEW"
        bump(order)
    return success_object(case, 200)
