"""PurchaseReport submission, flag/revise loop, and listings (PRD §3.4)."""

from flask import Blueprint, request

import db
from db import store, new_entity, touch, public
from errors import (err_not_found, err_state, ApiError, err_not_owner,
                    ERR_QUARTER_MISMATCH, ERR_FUTURE_QUARTER, ERR_MEMBER_NOT_ACTIVE)
from middleware import require_roles, body_json, req_int
from response import success_object, success_list, parse_pagination, paginate
from routes.enrollments import get_enrollment_or_404
from services import calc

bp = Blueprint("reports", __name__)

READ_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor", "MemberRep")


def get_report_or_404(report_id):
    report = store.reports.get(report_id)
    if report is None:
        raise err_not_found("PurchaseReport not found")
    return report


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _arg_int(name):
    from errors import err_invalid_request
    v = request.args.get(name)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise err_invalid_request("%s must be an integer" % name)


def _create_report(enrollment, quarter_index, qty, cents, revision_of_id=None):
    report = new_entity()
    report.update({
        "enrollment_id": enrollment["id"],
        "quarter_index": quarter_index,
        "self_report_qty": qty,
        "self_report_cents": cents,
        "audited_qty": None,
        "audited_cents": None,
        "revision_of_id": revision_of_id,
        "status": "SUBMITTED",
        "submitted_at_quarter": db.get_coop()["current_quarter_index"],
    })
    store.reports[report["id"]] = report
    return report


@bp.route("/coop/enrollments/<enrollment_id>/purchase-reports", methods=["POST"])
@require_roles("MemberRep", "CoopAdmin")
def submit_report(uid, role, enrollment_id):
    enr = get_enrollment_or_404(enrollment_id)
    body = body_json(required=True)
    quarter_index = req_int(body, "quarter_index")
    qty = req_int(body, "self_report_qty", minimum=0)
    cents = req_int(body, "self_report_cents", minimum=0)
    coop = db.get_coop()
    # Pipeline order: quarter match (7) fires before future-quarter (12),
    # which fires before member-active (13).
    if quarter_index != coop["current_quarter_index"]:
        raise ApiError(ERR_QUARTER_MISMATCH, 409,
                       "quarter_index must equal the co-op's current_quarter_index")
    if quarter_index > coop["current_quarter_index"]:
        raise ApiError(ERR_FUTURE_QUARTER, 409, "Quarter has not started")
    member = store.members[enr["member_id"]]
    if member["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409,
                       "Member must be ACTIVE to submit a purchase report")
    report = _create_report(enr, quarter_index, qty, cents)
    accrual, created = calc.get_or_create_accrual(enr["id"], quarter_index)
    calc.recompute_provisional(accrual, bump_version=not created)
    return success_object(public(report), code=201)


@bp.route("/coop/purchase-reports/<report_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_report(uid, role, report_id):
    return success_object(public(get_report_or_404(report_id)), code=200)


@bp.route("/coop/enrollments/<enrollment_id>/purchase-reports", methods=["GET"])
@require_roles(*READ_ROLES)
def list_reports_for_enrollment(uid, role, enrollment_id):
    enr = get_enrollment_or_404(enrollment_id)
    limit, offset = parse_pagination()
    items = [r for r in store.reports.values() if r["enrollment_id"] == enr["id"]]
    quarter = _arg_int("quarter_index")
    if quarter is not None:
        items = [r for r in items if r["quarter_index"] == quarter]
    status = _arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/coop/purchase-reports", methods=["GET"])
@require_roles(*READ_ROLES)
def list_reports(uid, role):
    limit, offset = parse_pagination()
    items = list(store.reports.values())
    enrollment_id = _arg("enrollment_id")
    if enrollment_id is not None:
        items = [r for r in items if r["enrollment_id"] == enrollment_id]
    revision_of_id = _arg("revision_of_id")
    if revision_of_id is not None:
        items = [r for r in items if r["revision_of_id"] == revision_of_id]
    quarter = _arg_int("quarter_index")
    if quarter is not None:
        items = [r for r in items if r["quarter_index"] == quarter]
    status = _arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/coop/purchase-reports/<report_id>/volume-audits", methods=["GET"])
@require_roles(*READ_ROLES)
def list_audits_for_report(uid, role, report_id):
    report = get_report_or_404(report_id)
    limit, offset = parse_pagination()
    items = [a for a in store.audits.values() if a["purchase_report_id"] == report["id"]]
    status = _arg("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/coop/purchase-reports/<report_id>/flag", methods=["POST"])
@require_roles("ProgramAuditor")
def flag_report(uid, role, report_id):
    report = get_report_or_404(report_id)
    if report["status"] != "SUBMITTED":
        raise err_state("Only a SUBMITTED report can be flagged")
    report["status"] = "FLAGGED"
    touch(report)
    return success_object(public(report), code=200)


@bp.route("/coop/purchase-reports/<report_id>/revise", methods=["POST"])
@require_roles("MemberRep")
def revise_report(uid, role, report_id):
    report = get_report_or_404(report_id)
    body = body_json(required=True)
    qty = req_int(body, "self_report_qty", minimum=0)
    cents = req_int(body, "self_report_cents", minimum=0)
    if report["status"] != "FLAGGED":
        raise err_state("Only a FLAGGED report can be revised")
    # Pipeline item 18: ownership — the caller must be the owning member.
    enr = store.enrollments[report["enrollment_id"]]
    if enr["member_id"] != uid:
        raise err_not_owner("MemberRep may only revise their own member's reports")
    report["status"] = "SUPERSEDED"
    touch(report)
    new_report = _create_report(enr, report["quarter_index"], qty, cents,
                                revision_of_id=report["id"])
    accrual = calc.find_accrual(enr["id"], report["quarter_index"])
    if accrual is not None:
        calc.recompute_provisional(accrual, bump_version=True)
    return success_object(public(new_report), code=201)
