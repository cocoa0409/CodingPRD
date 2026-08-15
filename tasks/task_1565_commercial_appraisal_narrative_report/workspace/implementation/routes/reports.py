from decimal import Decimal

from flask import Blueprint, request

import response
from db import store, touch, serialize
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_ASSIGNED_APPRAISER,
    ERR_NOT_ASSIGNED_REVIEWER,
    ERR_INVALID_STATE,
    ERR_STALE_ENGAGEMENT,
    ERR_NO_COMPLETED_APPROACH,
    ERR_WEIGHT_SUM,
    ERR_SIGNER_NOT_MAI,
    ERR_SIGNER_LICENSE,
    ERR_SEGREGATION,
    ERR_REVISION_REQUESTS_OPEN,
    ERR_NOT_FOUND,
)
from middleware import auth, require_role, get_body, req_str, req_int
from response import sort_by_creation
from services import calc, domain

bp = Blueprint("reports", __name__)


@bp.post("/engagements/<engagementId>/reports")
def create_report(engagementId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    eng = domain.get_engagement(engagementId)
    body = get_body()
    expected = req_int(body, "expected_engagement_version")
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    if eng["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS")
    if expected != eng["version"]:
        raise ApiError(
            ERR_STALE_ENGAGEMENT,
            412,
            "expected_engagement_version does not match the engagement's version",
        )
    report = domain.create_report_version(eng)
    return response.success(serialize(report), status=201)


@bp.get("/reports/<reportId>")
def get_report(reportId):
    auth()
    rec = domain.get_report(reportId)
    return response.success(serialize(rec))


@bp.get("/reports")
def list_reports():
    auth()
    items = list(store.reports.values())
    for field in ("engagement_id", "signer_appraiser_id", "supersedes_report_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sort_by_creation(items)
    return response.list_response([serialize(r) for r in items])


def _author_report_context(report, uid, require_in_progress=True):
    eng = domain.engagement_of_report(report)
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    if require_in_progress and eng["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS")
    return eng


@bp.post("/reports/<reportId>/submit_review")
def submit_review(reportId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    report = domain.get_report(reportId)
    eng = _author_report_context(report, uid)
    if report["status"] != "DRAFTING":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in DRAFTING")
    included = [
        a
        for a in store.approaches.values()
        if a["engagement_id"] == eng["id"] and a["status"] == "COMPLETE"
    ]
    if not included:
        raise ApiError(
            ERR_NO_COMPLETED_APPROACH,
            409,
            "No approach in COMPLETE and not EXCLUDED",
        )
    weight_sum = sum(Decimal(str(a["weight_pct"])) for a in included)
    if weight_sum != Decimal("100"):
        raise ApiError(
            ERR_WEIGHT_SUM,
            409,
            "Included approach weights must sum to exactly 100.00",
        )
    report["value_conclusion_cents"] = calc.reconciled_value(included)
    report["status"] = "INTERNAL_REVIEW"
    touch(report)
    return response.success(serialize(report))


def _reviewer_report_context(report, uid, require_in_progress=False):
    eng = domain.engagement_of_report(report)
    if eng["reviewer_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_REVIEWER,
            403,
            "Caller is not the engagement's reviewer appraiser",
        )
    if require_in_progress and eng["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS")
    return eng


@bp.post("/reports/<reportId>/review_approve")
def review_approve(reportId):
    uid, role = auth()
    require_role(role, {"ReviewAppraiser"})
    report = domain.get_report(reportId)
    _reviewer_report_context(report, uid, require_in_progress=True)
    if report["status"] != "INTERNAL_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in INTERNAL_REVIEW")
    report["status"] = "REVIEWED"
    touch(report)
    return response.success(serialize(report))


@bp.post("/reports/<reportId>/review_return")
def review_return(reportId):
    uid, role = auth()
    require_role(role, {"ReviewAppraiser"})
    report = domain.get_report(reportId)
    body = get_body()
    req_str(body, "review_note")
    _reviewer_report_context(report, uid, require_in_progress=False)
    if report["status"] != "INTERNAL_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in INTERNAL_REVIEW")
    report["review_cycle_count"] += 1
    report["status"] = "DRAFTING"
    touch(report)
    return response.success(serialize(report))


@bp.post("/reports/<reportId>/issue_to_client")
def issue_to_client(reportId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    report = domain.get_report(reportId)
    _author_report_context(report, uid)
    if report["status"] != "REVIEWED":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in REVIEWED")
    report["issued_to_client_at"] = store.clock
    report["status"] = "CLIENT_REVIEW"
    touch(report)
    return response.success(serialize(report))


@bp.post("/reports/<reportId>/reissue")
def reissue(reportId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    report = domain.get_report(reportId)
    _author_report_context(report, uid)
    if report["status"] != "REVISION_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in REVISION_REQUESTED")
    if any(
        rr["report_id"] == report["id"] and rr["status"] == "OPEN"
        for rr in store.revision_requests.values()
    ):
        raise ApiError(
            ERR_REVISION_REQUESTS_OPEN, 409, "Report has OPEN revision requests"
        )
    report["issued_to_client_at"] = store.clock
    report["status"] = "CLIENT_REVIEW"
    touch(report)
    return response.success(serialize(report))


@bp.post("/reports/<reportId>/finalize")
def finalize(reportId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    report = domain.get_report(reportId)
    _author_report_context(report, uid)
    if report["status"] != "CLIENT_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in CLIENT_REVIEW")
    if any(
        rr["report_id"] == report["id"] and rr["status"] in ("OPEN", "ESCALATED")
        for rr in store.revision_requests.values()
    ):
        raise ApiError(
            ERR_REVISION_REQUESTS_OPEN,
            409,
            "Report has OPEN or ESCALATED revision requests",
        )
    report["status"] = "FINAL"
    touch(report)
    return response.success(serialize(report))


@bp.post("/reports/<reportId>/sign")
def sign(reportId):
    uid, role = auth()
    require_role(role, {"MAISigner"})
    report = domain.get_report(reportId)
    signer = store.appraisers.get(uid)
    if signer is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Signer appraiser not found")
    if report["status"] != "FINAL":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in FINAL")
    if signer["designation"] != "MAI":
        raise ApiError(
            ERR_SIGNER_NOT_MAI, 409, "Signer appraiser must hold the MAI designation"
        )
    if signer["license_status"] != "ACTIVE":
        raise ApiError(
            ERR_SIGNER_LICENSE, 409, "Signer appraiser's license is not ACTIVE"
        )
    eng = domain.engagement_of_report(report)
    if uid == eng["author_appraiser_id"]:
        raise ApiError(
            ERR_SEGREGATION, 409, "Signer must not be the engagement's author"
        )
    report["signer_appraiser_id"] = uid
    report["signed_at"] = store.clock
    report["status"] = "SIGNED"
    touch(report)
    return response.success(serialize(report))


@bp.post("/reports/<reportId>/deliver")
def deliver(reportId):
    _, role = auth()
    require_role(role, {"StaffAppraiser", "EngagementManager"})
    report = domain.get_report(reportId)
    if report["status"] != "SIGNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in SIGNED")
    report["delivered_at"] = store.clock
    report["status"] = "DELIVERED"
    touch(report)
    eng = domain.engagement_of_report(report)
    domain.complete_engagement(eng)
    return response.success(serialize(report))
