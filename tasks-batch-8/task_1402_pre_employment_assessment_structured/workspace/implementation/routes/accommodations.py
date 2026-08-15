"""Accommodation request adjudication (PRD §3.5)."""
import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found, err_ownership)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from util import bump, req_string

bp = Blueprint("accommodations", __name__)

READ_ROLES = ["ComplianceOfficer", "Candidate", "HiringManager", "TalentAssessmentAdmin"]


def _get_ar_or_404(arid):
    ar = db.stores["accommodation_requests"].get(arid)
    if ar is None:
        raise err_not_found("AccommodationRequest not found")
    return ar


def _assessment_of(ar):
    return db.stores["assessments"].get(ar["candidate_assessment_id"])


@bp.get("/talent/accommodation-requests/<arid>")
def get_accommodation(arid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    ar = _get_ar_or_404(arid)
    if ctx.role == "Candidate":
        a = _assessment_of(ar)
        if a is None or a["candidate_id"] != ctx.user_id:
            raise err_ownership("Candidate may only read own accommodation requests")
    return success_object(serializers.accommodation(ar))


@bp.post("/talent/accommodation-requests/<arid>/approve")
def approve_accommodation(arid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer"])
    ar = _get_ar_or_404(arid)
    a = _assessment_of(ar)
    body = util.get_body()
    # Priority per PRD §3.5: assessment state first, then pendency + posture
    # together at the dedicated-state tier, extension-day range last.
    if a is None or a["admin_status"] not in ("INVITED", "SCHEDULED", "ACCOMMODATION_HOLD"):
        raise api_err("ERR_INVALID_STATE",
                      "Assessment must be INVITED, SCHEDULED, or ACCOMMODATION_HOLD")
    if ar["status"] != "PENDING":
        raise api_err("ERR_ACCOMMODATION_NOT_PENDING",
                      "Accommodation request must be PENDING")
    cyc = db.stores["cycles"].get(a["cycle_id"])
    if cyc is not None:
        if cyc["posture"] == "FROZEN":
            raise api_err("ERR_CYCLE_FROZEN", "Cycle is FROZEN")
        if cyc["posture"] != "ACTIVE":
            raise api_err("ERR_CYCLE_NOT_ACTIVE", "Cycle must be ACTIVE")
    approved_days = body.get("approved_extension_days")
    if isinstance(approved_days, bool) or not isinstance(approved_days, int):
        raise err_invalid_request("approved_extension_days is required and must be an integer")
    if approved_days < 1 or approved_days > ar["requested_extension_days"]:
        raise api_err("ERR_EXTENSION_OUT_OF_RANGE",
                      "approved_extension_days must be within 1..requested_extension_days")
    decision_note = body.get("decision_note")
    if not isinstance(decision_note, str) or not decision_note:
        raise err_invalid_request("decision_note is required")
    now = db.get_now()
    ar["status"] = "APPROVED"
    ar["approved_extension_days"] = approved_days
    ar["decision_note"] = decision_note
    ar["decided_by_user_id"] = ctx.user_id
    ar["decided_at"] = now
    bump(ar)
    # Side effects: extend the window; SCHEDULED -> ACCOMMODATION_HOLD
    a["accommodation_extension_days"] += approved_days
    if a["admin_status"] == "SCHEDULED":
        a["admin_status"] = "ACCOMMODATION_HOLD"
    bump(a)
    return success_object(serializers.accommodation(ar))


@bp.post("/talent/accommodation-requests/<arid>/deny")
def deny_accommodation(arid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer"])
    ar = _get_ar_or_404(arid)
    if ar["status"] != "PENDING":
        raise api_err("ERR_ACCOMMODATION_NOT_PENDING",
                      "Accommodation request must be PENDING")
    body = util.get_body()
    decision_note = body.get("decision_note")
    if not isinstance(decision_note, str) or len(decision_note) < 10:
        raise err_invalid_request("decision_note of at least 10 characters is required")
    now = db.get_now()
    ar["status"] = "DENIED"
    ar["decision_note"] = decision_note
    ar["decided_by_user_id"] = ctx.user_id
    ar["decided_at"] = now
    bump(ar)
    return success_object(serializers.accommodation(ar))


@bp.post("/talent/accommodation-requests/<arid>/withdraw")
def withdraw_accommodation(arid):
    ctx = authenticate()
    require_roles(ctx, ["Candidate"])
    ar = _get_ar_or_404(arid)
    a = _assessment_of(ar)
    if a is None or a["candidate_id"] != ctx.user_id:
        raise err_ownership("Candidate may only withdraw own accommodation requests")
    if ar["status"] != "PENDING":
        raise api_err("ERR_ACCOMMODATION_NOT_PENDING",
                      "Accommodation request must be PENDING")
    ar["status"] = "WITHDRAWN"
    bump(ar)
    return success_object(serializers.accommodation(ar))
