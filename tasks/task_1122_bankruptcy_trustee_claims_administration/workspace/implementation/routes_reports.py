"""Final report endpoints: retrieval (array of length 0-1), filing, approval
(closes the case and remits unclaimed funds)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_STATE, ERR_FINAL_REPORT_NOT_READY
from middleware import auth_context, require_roles, ALL_ROLES
from response import ok_object, paginate
from services_common import (
    bump_case, get_case, ensure_case_open, ensure_trustee_binding, ser_report,
)

bp = Blueprint("reports", __name__)


def _report_of_case(case_id):
    for r in db.reports.values():
        if r["case_id"] == case_id:
            return r
    return None


@bp.route("/trustee/cases/<id>/final_report", methods=["GET"])
def get_final_report(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    report = _report_of_case(id)
    rows = [ser_report(report)] if report is not None else []
    return paginate(rows)


@bp.route("/trustee/cases/<id>/final_report/file", methods=["POST"])
def file_final_report(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    report = _report_of_case(id)
    if case["status"] != "FINAL_REPORT" or report is None or report["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The case must be in FINAL_REPORT with a DRAFT report to file.")
    ensure_trustee_binding(case, uid)
    if any(f["case_id"] == id and f["status"] not in ("PAID", "DENIED")
           for f in db.fees.values()):
        raise ApiError(ERR_FINAL_REPORT_NOT_READY, 409,
                       "Unresolved fee applications remain.")
    case_plans = {p["id"] for p in db.plans.values() if p["case_id"] == id}
    if any(d["plan_id"] in case_plans and d["status"] not in ("POSTED", "VOIDED")
           for d in db.dividends.values()):
        raise ApiError(ERR_FINAL_REPORT_NOT_READY, 409,
                       "Unresolved dividends remain.")
    report["status"] = "FILED"
    return ok_object(ser_report(report))


@bp.route("/trustee/cases/<id>/final_report/approve", methods=["POST"])
def approve_final_report(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    case = get_case(id)
    ensure_case_open(case)
    report = _report_of_case(id)
    if report is None or report["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The final report must be FILED to approve.")
    if any(f["case_id"] == id and f["status"] not in ("PAID", "DENIED")
           for f in db.fees.values()):
        raise ApiError(ERR_FINAL_REPORT_NOT_READY, 409,
                       "Unresolved fee applications remain.")
    report["status"] = "APPROVED"
    case["status"] = "CLOSED"
    case["estate_cash_on_hand_cents"] = 0  # unclaimed funds remitted to the court registry
    bump_case(case)
    return ok_object(ser_report(report))
