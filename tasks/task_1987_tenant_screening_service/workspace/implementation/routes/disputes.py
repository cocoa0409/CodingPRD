"""Dispute routes: filing, reinvestigation, resolution, and the correction cascade."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_DISPUTE_STATE,
    ERR_INVALID_REPORT_STATE,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_RECORD_NOT_ON_REPORT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NOT_REINVESTIGATOR,
    ERR_REINVESTIGATION_OVERDUE,
)
from middleware import (
    get_context, require_role, check_applicant_ownership,
    check_landlord_ownership,
)
from response import success_object, success_list
from services.core import (
    recompute_included_count, report_records, compute_recommendation,
    application_income_verification,
    DISPUTE_WINDOW_DAYS, REINVESTIGATION_SLA_DAYS,
)
from util import (
    clock, get_body, req_string, pagination_params, paginate,
    stamp_new, touch, serialize,
)

bp = Blueprint("disputes", __name__)


def _scoped_read_check(user_id, role, app):
    if app is None:
        return
    if role == "Landlord":
        check_landlord_ownership(user_id, role, app["landlord_id"])
    elif role == "Applicant":
        check_applicant_ownership(user_id, role, app["applicant_id"])


# ---------------------------------------------------------------------------
# File a dispute
# ---------------------------------------------------------------------------

@bp.route("/api/reports/<rid>/disputes", methods=["POST"])
def file_dispute(rid):
    user_id, role = get_context()
    require_role(role, ["Applicant"])
    report = store.reports.get(rid)
    if report is None:
        raise ApiError(ERR_NOT_FOUND, "Report not found", 404)
    app = store.applications.get(report["application_id"])
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)
    check_applicant_ownership(user_id, role, app["applicant_id"])

    body = get_body()
    disputed_ids = body.get("disputed_record_ids")
    if disputed_ids is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: disputed_record_ids", 400)
    if not isinstance(disputed_ids, list) or any(not isinstance(x, str) for x in disputed_ids):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'disputed_record_ids' must be an array of strings", 400)
    reason_text = req_string(body, "reason_text")

    # From-state (stage 6): report must be DELIVERED or RE_DELIVERED.
    if report["status"] not in ("DELIVERED", "RE_DELIVERED"):
        raise ApiError(
            ERR_INVALID_REPORT_STATE,
            "Dispute filing requires the report DELIVERED or RE_DELIVERED",
            409,
        )

    # Temporal gate (stage 9): within last_delivered_at + 30 days, inclusive.
    at = clock()
    last = report.get("last_delivered_at")
    if last is None or at > last + timedelta(days=DISPUTE_WINDOW_DAYS):
        raise ApiError(
            ERR_DISPUTE_WINDOW_CLOSED,
            "Dispute filed after report.last_delivered_at + 30 days",
            422,
        )

    # Referential integrity (stage 11): every id must belong to this report.
    records_by_id = {r["id"]: r for r in report_records(report["id"])}
    for rec_id in disputed_ids:
        if rec_id not in records_by_id:
            raise ApiError(
                ERR_RECORD_NOT_ON_REPORT,
                "A disputed_record_ids entry does not belong to the dispute's report",
                422,
            )

    dispute = stamp_new({
        "report_id": report["id"],
        "applicant_id": user_id,
        "disputed_record_ids": list(disputed_ids),
        "reason_text": reason_text,
        "status": "FILED",
        "filed_at": at,
        "reinvestigation_deadline": at + timedelta(days=REINVESTIGATION_SLA_DAYS),
        "reinvestigator_screener_id": None,
        "resolved_at": None,
        "resolution_notes": None,
    })
    store.disputes[dispute["id"]] = dispute

    # Cascade: report -> UNDER_DISPUTE; each disputed record INCLUDED -> DISPUTED.
    report["status"] = "UNDER_DISPUTE"
    touch(report)
    for rec_id in disputed_ids:
        rec = records_by_id[rec_id]
        if rec["status"] == "INCLUDED":
            rec["status"] = "DISPUTED"
            touch(rec)
    recompute_included_count(report)

    return success_object(serialize(dispute), 201)


@bp.route("/api/disputes", methods=["GET"])
def list_disputes():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    items = sorted(store.disputes.values(), key=lambda d: d["created_at"])
    if role in ("Landlord", "Applicant"):
        scoped = []
        for d in items:
            report = store.reports.get(d["report_id"])
            app = store.applications.get(report["application_id"]) if report else None
            if app is None:
                continue
            if role == "Landlord" and app["landlord_id"] == user_id:
                scoped.append(d)
            elif role == "Applicant" and app["applicant_id"] == user_id:
                scoped.append(d)
        items = scoped
    for param in ("report_id", "applicant_id"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if str(d.get(param)) == v]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(d) for d in page], limit, offset, total)


@bp.route("/api/disputes/<did>", methods=["GET"])
def get_dispute(did):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    d = store.disputes.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, "Dispute not found", 404)
    report = store.reports.get(d["report_id"])
    app = store.applications.get(report["application_id"]) if report else None
    _scoped_read_check(user_id, role, app)
    return success_object(serialize(d))


@bp.route("/api/disputes/<did>/start-reinvestigation", methods=["POST"])
def start_reinvestigation(did):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    d = store.disputes.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, "Dispute not found", 404)
    if d["status"] != "FILED":
        raise ApiError(ERR_INVALID_DISPUTE_STATE, "Dispute not in FILED", 409)
    report = store.reports.get(d["report_id"])
    originator = report.get("originating_screener_id") if report else None
    if originator is not None and user_id == originator:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The reinvestigating screener must differ from the report's originating screener",
            403,
        )
    d["status"] = "UNDER_REINVESTIGATION"
    d["reinvestigator_screener_id"] = user_id
    touch(d)
    return success_object(serialize(d))


@bp.route("/api/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    d = store.disputes.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, "Dispute not found", 404)
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("UPHELD", "CORRECTED"):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'outcome' must be UPHELD or CORRECTED", 400)
    resolution_notes = req_string(body, "resolution_notes")

    if d["status"] != "UNDER_REINVESTIGATION":
        raise ApiError(ERR_INVALID_DISPUTE_STATE, "Dispute not in UNDER_REINVESTIGATION", 409)
    if user_id != d.get("reinvestigator_screener_id"):
        raise ApiError(
            ERR_NOT_REINVESTIGATOR,
            "Only the assigned reinvestigator may resolve the dispute",
            403,
        )
    at = clock()
    if at > d["reinvestigation_deadline"]:
        raise ApiError(
            ERR_REINVESTIGATION_OVERDUE,
            "Dispute resolution attempted after reinvestigation_deadline",
            422,
        )

    report = store.reports[d["report_id"]]
    records_by_id = {r["id"]: r for r in report_records(report["id"])}

    d["resolved_at"] = at
    d["resolution_notes"] = resolution_notes

    if outcome == "UPHELD":
        d["status"] = "RESOLVED_UPHELD"
        for rec_id in d["disputed_record_ids"]:
            rec = records_by_id.get(rec_id)
            if rec is not None and rec["status"] == "DISPUTED":
                rec["status"] = "INCLUDED"
                touch(rec)
        report["status"] = "RE_DELIVERED"
        report["last_delivered_at"] = at
        recompute_included_count(report)
        touch(report)
    else:
        d["status"] = "RESOLVED_CORRECTED"
        for rec_id in d["disputed_record_ids"]:
            rec = records_by_id.get(rec_id)
            if rec is not None and rec["status"] == "DISPUTED":
                rec["status"] = "REMOVED"
                touch(rec)
        report["status"] = "AMENDED"
        recompute_included_count(report)
        touch(report)

        # Cascade hop 3: re-run recommendation with refreshed included counts;
        # verified_income_cents and affordability_passes keep score-time values.
        app = store.applications.get(report["application_id"])
        if app is not None:
            criteria = store.criteria.get(app.get("criteria_id"))
            if criteria is not None:
                included = [r for r in report_records(report["id"]) if r["status"] == "INCLUDED"]
                app["eviction_included_count"] = sum(1 for r in included if r["record_type"] == "EVICTION")
                app["criminal_included_count"] = sum(1 for r in included if r["record_type"] == "CRIMINAL")
                old_recommendation = app.get("recommendation")
                new_recommendation = compute_recommendation(app, criteria)
                app["recommendation"] = new_recommendation
                # Cascade hop 4: flip away from RECOMMEND_DENY -> requires_reconsideration
                if old_recommendation == "RECOMMEND_DENY" and new_recommendation in (
                    "RECOMMEND_APPROVE", "RECOMMEND_CONDITIONAL",
                ):
                    app["requires_reconsideration"] = True
                touch(app)

    touch(d)
    return success_object(serialize(d))
