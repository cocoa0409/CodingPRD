"""Report and record routes."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_APPLICATION_STATE,
    ERR_INVALID_REPORT_STATE,
)
from middleware import (
    get_context, require_role,
    check_landlord_ownership, check_applicant_ownership,
)
from response import success_object, success_list
from services.core import application_report
from util import clock, pagination_params, paginate, touch, serialize

bp = Blueprint("reports", __name__)


def _scoped_read_check(user_id, role, app):
    if app is None:
        return
    if role == "Landlord":
        check_landlord_ownership(user_id, role, app["landlord_id"])
    elif role == "Applicant":
        check_applicant_ownership(user_id, role, app["applicant_id"])


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@bp.route("/api/reports", methods=["GET"])
def list_reports():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    items = sorted(store.reports.values(), key=lambda r: r["created_at"])
    if role in ("Landlord", "Applicant"):
        scoped = []
        for r in items:
            app = store.applications.get(r["application_id"])
            if app is None:
                continue
            if role == "Landlord" and app["landlord_id"] == user_id:
                scoped.append(r)
            elif role == "Applicant" and app["applicant_id"] == user_id:
                scoped.append(r)
        items = scoped
    for param in ("application_id", "source_report_id"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if str(r.get(param)) == v]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/api/reports/<rid>", methods=["GET"])
def get_report(rid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    report = store.reports.get(rid)
    if report is None:
        raise ApiError(ERR_NOT_FOUND, "Report not found", 404)
    _scoped_read_check(user_id, role, store.applications.get(report["application_id"]))
    return success_object(serialize(report))


@bp.route("/api/reports/<rid>/deliver", methods=["POST"])
def deliver_report(rid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    report = store.reports.get(rid)
    if report is None:
        raise ApiError(ERR_NOT_FOUND, "Report not found", 404)
    app = store.applications.get(report["application_id"])

    at = clock()
    if report["status"] == "DRAFT":
        if app is None or app["status"] != "SCORED":
            raise ApiError(
                ERR_INVALID_APPLICATION_STATE,
                "Delivery requires the application SCORED",
                409,
            )
        report["status"] = "DELIVERED"
        report["delivered_at"] = at
        report["last_delivered_at"] = at
    elif report["status"] == "AMENDED":
        if app is None or app["status"] not in ("SCORED", "APPROVED", "DENIED"):
            raise ApiError(
                ERR_INVALID_APPLICATION_STATE,
                "Re-delivery requires the application SCORED, APPROVED, or DENIED",
                409,
            )
        report["status"] = "RE_DELIVERED"
        report["last_delivered_at"] = at
    else:
        raise ApiError(
            ERR_INVALID_REPORT_STATE,
            "Report not in DRAFT or AMENDED",
            409,
        )
    touch(report)
    return success_object(serialize(report))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@bp.route("/api/records", methods=["GET"])
def list_records():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    # Insertion order == creation sequence (input array order of record-searches).
    items = list(store.records.values())
    if role in ("Landlord", "Applicant"):
        scoped = []
        for rec in items:
            report = store.reports.get(rec["report_id"])
            app = store.applications.get(report["application_id"]) if report else None
            if app is None:
                continue
            if role == "Landlord" and app["landlord_id"] == user_id:
                scoped.append(rec)
            elif role == "Applicant" and app["applicant_id"] == user_id:
                scoped.append(rec)
        items = scoped
    report_id = request.args.get("report_id")
    if report_id is not None:
        items = [r for r in items if r["report_id"] == report_id]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/api/records/<rid>", methods=["GET"])
def get_record(rid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    rec = store.records.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Record not found", 404)
    report = store.reports.get(rec["report_id"])
    app = store.applications.get(report["application_id"]) if report else None
    _scoped_read_check(user_id, role, app)
    return success_object(serialize(rec))
