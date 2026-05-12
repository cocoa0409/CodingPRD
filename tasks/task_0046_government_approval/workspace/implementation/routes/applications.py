"""Application + correction-notice + sla routes."""

from flask import Blueprint, request

import db
from errors import AppError, ERR_NOT_FOUND
from middleware import require_role
from response import parse_pagination, success, success_list
from services import application as app_svc
from services import calculations
from services import review as review_svc
from services.serializers import (
    serialize_application,
    serialize_correction_notice,
    serialize_review_task,
)

bp = Blueprint("applications", __name__)


# --- Submit ---

@bp.post("/applications")
def submit():
    require_role("Applicant")
    record = app_svc.submit_application(request.get_json(silent=True))
    return success(serialize_application(record), 201)


# --- Read app detail (with sla + fee) ---

@bp.get("/applications/<app_id>")
def read(app_id):
    require_role("Applicant", "Reviewer", "LeadReviewer", "PlatformAdmin")
    app = app_svc.get_application(app_id)
    app_svc.assert_can_read_application(app)
    version = db.find_by_id("matter_versions", app["matter_version_id"])
    sla = calculations.time_limit_warning(app, version)
    fee = calculations.fee_breakdown(app, version)
    return success(serialize_application(app, sla=sla, fee=fee))


@bp.get("/applications/<app_id>/sla")
def read_sla(app_id):
    require_role("Applicant", "Reviewer", "LeadReviewer", "PlatformAdmin")
    app = app_svc.get_application(app_id)
    app_svc.assert_can_read_application(app)
    version = db.find_by_id("matter_versions", app["matter_version_id"])
    sla = calculations.time_limit_warning(app, version)
    return success(sla)


@bp.post("/applications/<app_id>/withdraw")
def withdraw(app_id):
    require_role("Applicant")
    record = app_svc.withdraw_application(app_id, request.get_json(silent=True) or {})
    return success(serialize_application(record), 200)


@bp.post("/applications/<app_id>/escalate")
def escalate(app_id):
    require_role("LeadReviewer")
    record = app_svc.escalate_application(app_id, request.get_json(silent=True) or {})
    return success(serialize_application(record), 200)


@bp.post("/applications/<app_id>/escalation-resolve")
def resolve_escalation(app_id):
    require_role("PlatformAdmin")
    record = app_svc.resolve_escalation(app_id, request.get_json(silent=True))
    return success(serialize_application(record), 200)


@bp.get("/applications/<app_id>/review-tasks")
def list_review_tasks(app_id):
    require_role("Reviewer", "LeadReviewer", "PlatformAdmin", "Applicant")
    app = app_svc.get_application(app_id)
    app_svc.assert_can_read_application(app)
    rows = sorted(
        db.find_many("review_tasks", application_id=app_id),
        key=lambda r: (r.get("stage_index") or 0, r.get("created_at") or ""),
    )
    limit, offset = parse_pagination(request.args)
    page = rows[offset:offset + limit]
    return success_list([serialize_review_task(r) for r in page],
                        len(rows), limit, offset)


# --- Correction notices ---

@bp.post("/applications/<app_id>/correction-notices")
def issue_correction(app_id):
    require_role("Reviewer", "LeadReviewer")
    record = review_svc.issue_correction_notice(app_id, request.get_json(silent=True))
    return success(serialize_correction_notice(record), 201)


@bp.get("/applications/<app_id>/correction-notices")
def list_corrections(app_id):
    require_role("Applicant", "Reviewer", "LeadReviewer", "PlatformAdmin")
    app = app_svc.get_application(app_id)
    app_svc.assert_can_read_application(app)
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    rows, total = review_svc.list_correction_notices(app_id, status_filter,
                                                     limit, offset)
    return success_list([serialize_correction_notice(r) for r in rows],
                        total, limit, offset)


@bp.post("/applications/<app_id>/correction-notices/<cid>/resubmit")
def resubmit(app_id, cid):
    require_role("Applicant")
    record = review_svc.resubmit_correction(app_id, cid,
                                            request.get_json(silent=True))
    return success(serialize_correction_notice(record), 200)


# --- Application's certificate ---

@bp.get("/applications/<app_id>/certificate")
def get_app_certificate(app_id):
    require_role("Applicant", "PlatformAdmin", "CertificateOfficer")
    from services import certificate
    from services.serializers import serialize_certificate
    cert = certificate.get_certificate_for_application(app_id)
    return success(serialize_certificate(cert))
