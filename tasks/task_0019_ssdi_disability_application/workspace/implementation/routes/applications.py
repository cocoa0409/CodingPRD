"""Application endpoints + medical-decision + reconsideration + hearing request + evidence."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_EOD_BEFORE_AOD,
    ERR_EVIDENCE_REQUIRED,
    ERR_INVALID_APPLICATION_STATE,
    ERR_LISTING_REFERENCE_REQUIRED,
    ERR_RECONSIDERATION_WINDOW_EXPIRED,
    ERR_STALE_APPLICATION_VERSION,
    forbidden,
    invalid_request,
    not_found,
    ref_not_found,
)
from middleware import require_roles
from response import created, ok, paginated
from services import state as svc_state
from services.utils import (
    opt_str,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_body,
    require_int,
    require_str,
)

bp = Blueprint("applications", __name__)


VALID_CLAIM_TYPES = {"SSDI_ONLY", "CONCURRENT_SSDI_SSI"}
VALID_DECISION_TYPES = {"LISTING_MET", "RFC_DISABLED", "NOT_DISABLED"}
VALID_SOURCE_TYPES = {
    "TREATING_PHYSICIAN",
    "CONSULTATIVE_EXAM",
    "HOSPITAL_RECORD",
    "SPECIALIST_REPORT",
}


# ---------- Applications CRUD ----------
@bp.route("/ssdi/applications", methods=["POST"])
@require_roles("Claimant", "SSAAdmin")
def create_application(user_id, role):
    body = require_body()
    claimant_id = require_str(body, "claimant_id")
    if claimant_id not in db.claimants:
        raise ref_not_found(f"claimant {claimant_id} not found")
    # Claimant role may only file for self.
    if role == "Claimant" and claimant_id != user_id:
        raise forbidden("claimant may only file for self")

    aod = require_str(body, "alleged_onset_date")
    parse_iso8601(aod, "alleged_onset_date")
    pfd = opt_str(body, "protective_filing_date", None)
    if pfd:
        parse_iso8601(pfd, "protective_filing_date")
    claim_type = opt_str(body, "claim_type", "SSDI_ONLY")
    if claim_type not in VALID_CLAIM_TYPES:
        raise invalid_request(f"invalid claim_type: {claim_type}")

    rec = {
        "claimant_id": claimant_id,
        "alleged_onset_date": aod,
        "filing_date": None,
        "protective_filing_date": pfd,
        "status": "DRAFT",
        "insured_status": "PENDING",
        "total_qc_at_filing": 0,
        "recent_qc_in_lookback": 0,
        "medical_decision": "PENDING",
        "established_onset_date": None,
        "claim_type": claim_type,
    }
    db.stamp_create(rec)
    db.applications[rec["id"]] = rec
    return created(rec)


@bp.route("/ssdi/applications/<aid>", methods=["GET"])
@require_roles("Claimant", "SSAAdmin", "DDSExaminer", "ALJ", "BenefitsAdmin")
def get_application(aid, user_id, role):
    rec = db.applications.get(aid)
    if rec is None:
        raise not_found(f"application {aid} not found")
    return ok(rec)


@bp.route("/ssdi/applications", methods=["GET"])
@require_roles("SSAAdmin", "Claimant", "DDSExaminer")
def list_applications(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.applications.values())
    claimant_filter = request.args.get("claimant_id")
    status_filter = request.args.get("status")
    if claimant_filter:
        items = [r for r in items if r.get("claimant_id") == claimant_filter]
    if status_filter:
        items = [r for r in items if r.get("status") == status_filter]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)


# ---------- Submit ----------
@bp.route("/ssdi/applications/<aid>/submit", methods=["POST"])
@require_roles("Claimant")
def submit_app(aid, user_id, role):
    app = db.applications.get(aid)
    if app is None:
        raise not_found(f"application {aid} not found")
    if app.get("status") != "DRAFT":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"application not in DRAFT (current: {app.get('status')})",
        )
    claimant = db.claimants.get(app["claimant_id"])
    if claimant is None or not claimant.get("date_of_birth"):
        raise ref_not_found("claimant or date_of_birth missing")
    svc_state.submit_application(app)
    return ok(app)


# ---------- Medical decision ----------
@bp.route("/ssdi/applications/<aid>/medical-decision", methods=["POST"])
@require_roles("DDSExaminer")
def medical_decision(aid, user_id, role):
    app = db.applications.get(aid)
    if app is None:
        raise not_found(f"application {aid} not found")
    body = require_body()
    # Priority 5: state check
    if app.get("status") != "MEDICAL_REVIEW":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"application not in MEDICAL_REVIEW (current: {app.get('status')})",
        )
    # evidence_required check (priority not explicitly numbered but in catalog)
    has_evidence = any(
        e.get("application_id") == aid for e in db.medical_evidence.values()
    )
    if not has_evidence:
        raise APIError(
            ERR_EVIDENCE_REQUIRED, 422, "at least one MedicalEvidence is required"
        )
    # Priority 8: OCC
    expected_version = require_int(body, "expected_application_version")
    if expected_version != app.get("version"):
        raise APIError(
            ERR_STALE_APPLICATION_VERSION,
            412,
            f"expected_application_version {expected_version} != current {app.get('version')}",
        )
    decision_type = require_str(body, "decision_type")
    if decision_type not in VALID_DECISION_TYPES:
        raise invalid_request(f"invalid decision_type: {decision_type}")
    eod = require_str(body, "established_onset_date")
    eod_dt = parse_iso8601(eod, "established_onset_date")
    aod_dt = parse_iso8601(app["alleged_onset_date"], "alleged_onset_date")
    # Priority 10: EOD >= AOD
    if eod_dt < aod_dt:
        raise APIError(
            ERR_EOD_BEFORE_AOD,
            422,
            "established_onset_date cannot precede alleged_onset_date",
        )
    listing_ref = body.get("listing_reference")
    rfc_score = body.get("rfc_score")
    # Priority 11: LISTING_MET requires listing_reference
    if decision_type == "LISTING_MET":
        if not listing_ref:
            raise APIError(
                ERR_LISTING_REFERENCE_REQUIRED,
                422,
                "listing_reference is required for decision_type=LISTING_MET",
            )
    if decision_type in {"RFC_DISABLED", "NOT_DISABLED"}:
        if rfc_score is None:
            raise invalid_request("rfc_score is required for RFC_DISABLED/NOT_DISABLED")
        if not isinstance(rfc_score, int) or isinstance(rfc_score, bool):
            raise invalid_request("rfc_score must be an integer")
        if not (0 <= rfc_score <= 100):
            raise invalid_request("rfc_score must be 0..100")

    # Priority 16: SSI cascade requires claim_type CONCURRENT_SSDI_SSI;
    # if decision is approving and claim_type was tampered with, we still
    # cascade-create SSI only when claim_type is CONCURRENT_SSDI_SSI, so this
    # never naturally trips except as a defensive check. We honor it as per
    # scaffold: if some upstream wants SSI but claim_type != CONCURRENT_SSDI_SSI,
    # reject — but we have no such upstream input field, so the gate is moot here.

    decision = svc_state.apply_medical_decision(app, body, user_id)
    return created(decision)


# ---------- Reconsideration ----------
@bp.route("/ssdi/applications/<aid>/request-reconsideration", methods=["POST"])
@require_roles("Claimant")
def request_reconsideration(aid, user_id, role):
    app = db.applications.get(aid)
    if app is None:
        raise not_found(f"application {aid} not found")
    if app.get("status") != "DENIED_MEDICAL":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"application not in DENIED_MEDICAL (current: {app.get('status')})",
        )
    # Find latest NOT_DISABLED MedicalDeterminationDecision for this application.
    decisions = [
        d
        for d in db.medical_decisions.values()
        if d.get("application_id") == aid and d.get("decision_type") == "NOT_DISABLED"
    ]
    if not decisions:
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            "no medical decision found to reconsider",
        )
    latest = max(decisions, key=lambda d: d.get("created_at", ""))
    decision_dt = parse_iso8601(latest["created_at"], "decision.created_at")
    if db.now_utc() > decision_dt + timedelta(days=60):
        raise APIError(
            ERR_RECONSIDERATION_WINDOW_EXPIRED,
            422,
            "reconsideration must be requested within 60 days of denial",
        )
    app["status"] = "RECONSIDERATION"
    app["medical_decision"] = "PENDING"
    db.stamp_update(app)
    return ok(app)


# ---------- Request hearing ----------
@bp.route("/ssdi/applications/<aid>/request-hearing", methods=["POST"])
@require_roles("Claimant")
def request_hearing(aid, user_id, role):
    app = db.applications.get(aid)
    if app is None:
        raise not_found(f"application {aid} not found")
    if app.get("status") != "RECONSIDERATION":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"application not in RECONSIDERATION (current: {app.get('status')})",
        )
    hr = {
        "application_id": aid,
        "requested_date": db.iso_now(),
        "scheduled_date": None,
        "status": "REQUESTED",
        "alj_user_id": None,
    }
    db.stamp_create(hr)
    db.hearings[hr["id"]] = hr
    app["status"] = "ALJ_PENDING"
    db.stamp_update(app)
    return created(hr)


# ---------- Evidence ----------
@bp.route("/ssdi/applications/<aid>/evidence", methods=["POST"])
@require_roles("Claimant", "DDSExaminer")
def add_evidence(aid, user_id, role):
    app = db.applications.get(aid)
    if app is None:
        raise not_found(f"application {aid} not found")
    body = require_body()
    source_type = require_str(body, "source_type")
    if source_type not in VALID_SOURCE_TYPES:
        raise invalid_request(f"invalid source_type: {source_type}")
    report_date = require_str(body, "report_date")
    parse_iso8601(report_date, "report_date")
    diagnosis_code = require_str(body, "diagnosis_code")
    severity_score = require_int(body, "severity_score")
    if not (0 <= severity_score <= 100):
        raise invalid_request("severity_score must be 0..100")
    rec = {
        "application_id": aid,
        "source_type": source_type,
        "report_date": report_date,
        "diagnosis_code": diagnosis_code,
        "severity_score": severity_score,
    }
    # MedicalEvidence is immutable: id + created_at only, no updated_at or version.
    rec["id"] = db.new_id()
    rec["created_at"] = db.iso_now()
    db.medical_evidence[rec["id"]] = rec
    return created(rec)


@bp.route("/ssdi/applications/<aid>/evidence", methods=["GET"])
@require_roles("Claimant", "DDSExaminer", "ALJ", "SSAAdmin")
def list_evidence(aid, user_id, role):
    app = db.applications.get(aid)
    if app is None:
        raise not_found(f"application {aid} not found")
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.medical_evidence.values() if e.get("application_id") == aid]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)


@bp.route("/ssdi/applications/<aid>/decisions", methods=["GET"])
@require_roles("Claimant", "DDSExaminer", "ALJ", "SSAAdmin")
def list_decisions(aid, user_id, role):
    app = db.applications.get(aid)
    if app is None:
        raise not_found(f"application {aid} not found")
    limit, offset = parse_pagination(request.args)
    items = [d for d in db.medical_decisions.values() if d.get("application_id") == aid]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)
