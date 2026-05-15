"""Financial aid routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import clock
from core.errors import raise_error
from core.response import success_object
from core.store import store
from services.calculations import compute_financial_aid
from services.engine import check_version, get_aid, get_application
from services.serializers import aid_out
from services.time_utils import parse_iso

bp = Blueprint("financial_aid", __name__)

VALID_METHODS = {"FEDERAL_METHODOLOGY", "INSTITUTIONAL_METHODOLOGY"}


@bp.post("/applications/<application_id>/financial-aid")
@require_roles("Applicant")
def request_aid(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    method = body.get("aid_method")
    if method not in VALID_METHODS:
        raise_error("ERR_VALIDATION", "aid_method must be FEDERAL_METHODOLOGY or INSTITUTIONAL_METHODOLOGY.")
    coa = body.get("cost_of_attendance_cents")
    if not isinstance(coa, int) or isinstance(coa, bool) or coa < 0:
        raise_error("ERR_VALIDATION", "cost_of_attendance_cents must be a non-negative integer.")
    # At most one package per application
    for pkg in store.aid_packages.values():
        if pkg["application_id"] == app["id"]:
            raise_error("ERR_INVALID_STATE", "Application already has a financial aid package.")
    rec = store.stamp_create()
    rec.update(
        {
            "application_id": app["id"],
            "aid_method": method,
            "status": "REQUESTED",
            "cost_of_attendance_cents": coa,
            "grant_cents": 0,
            "loan_cents": 0,
            "work_study_cents": 0,
            "total_award_cents": 0,
        }
    )
    store.aid_packages[rec["id"]] = rec
    return success_object(aid_out(rec), 201)


@bp.get("/financial-aid/<aid_id>")
@require_roles("Applicant", "FinancialAidOfficer", "PlatformAdmin")
def read_aid(aid_id: str):
    rec = get_aid(aid_id)
    return success_object(aid_out(rec), 200)


@bp.post("/financial-aid/<aid_id>/issue-offer")
@require_roles("FinancialAidOfficer")
def issue_offer(aid_id: str):
    pkg = get_aid(aid_id)
    if pkg["status"] != "REQUESTED":
        raise_error("ERR_INVALID_STATE")
    app = store.applications.get(pkg["application_id"])
    if app is None or app["status"] != "ADMITTED":
        raise_error("ERR_INVALID_STATE")
    applicant = store.applicants.get(app["applicant_id"])
    if applicant is None:
        raise_error("ERR_INVALID_STATE")
    if pkg["aid_method"] == "FEDERAL_METHODOLOGY" and applicant.get("fafsa_efc_cents") is None:
        raise_error("ERR_MISSING_EFC")
    if pkg["aid_method"] == "INSTITUTIONAL_METHODOLOGY" and applicant.get("css_profile_efc_cents") is None:
        raise_error("ERR_MISSING_EFC")
    award = compute_financial_aid(pkg["aid_method"], pkg["cost_of_attendance_cents"], applicant)
    pkg.update(award)
    pkg["status"] = "OFFERED"
    store.bump(pkg)
    return success_object(aid_out(pkg), 200)


@bp.post("/financial-aid/<aid_id>/accept")
@require_roles("Applicant")
def accept_aid(aid_id: str):
    pkg = get_aid(aid_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    if pkg["status"] != "OFFERED":
        raise_error("ERR_INVALID_STATE")
    check_version(pkg, body.get("version"))
    app = store.applications.get(pkg["application_id"])
    if app is None or app["status"] != "ADMITTED":
        raise_error("ERR_INVALID_STATE")
    if parse_iso(clock.iso()) > parse_iso(app["enrollment_deadline"]):
        raise_error("ERR_INVALID_STATE")
    pkg["status"] = "ACCEPTED"
    store.bump(pkg)
    return success_object(aid_out(pkg), 200)


@bp.post("/financial-aid/<aid_id>/decline")
@require_roles("Applicant")
def decline_aid(aid_id: str):
    pkg = get_aid(aid_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    if pkg["status"] != "OFFERED":
        raise_error("ERR_INVALID_STATE")
    check_version(pkg, body.get("version"))
    pkg["status"] = "DECLINED"
    store.bump(pkg)
    return success_object(aid_out(pkg), 200)
