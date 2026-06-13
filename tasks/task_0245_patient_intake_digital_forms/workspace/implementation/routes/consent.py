"""ConsentDocument routes (PRD §3.7)."""
from flask import Blueprint, request

import db
import serialize
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_SESSION_EXPIRED,
    ERR_CONSENT_CODE_NOT_REQUIRED,
    ERR_CONSENT_NOT_PENDING,
    ERR_CONSENT_NOT_SIGNED,
    ERR_CONSENT_NOT_REVOKED,
    ERR_SESSION_LOCKED,
)
from middleware import require_roles
from response import success, success_list
from services.common import touch, require_string
from services.lookups import get_session, get_consent
from services.pagination import paginate
from services import sessions as S

bp = Blueprint("consent", __name__)


def _first_in_progress(session):
    if session["workflow_status"] == "DRAFT":
        if S.is_expired(session):
            raise err(ERR_SESSION_EXPIRED, "session expired")
        session["workflow_status"] = "IN_PROGRESS"
        touch(session)


@bp.route("/consent-documents", methods=["POST"])
@require_roles("FrontDeskStaff")
def create_consent():
    body = request.get_json(silent=True) or {}
    intake_session_id = require_string(body, "intake_session_id")
    consent_code = require_string(body, "consent_code")
    session = get_session(intake_session_id)

    provider = db.providers[session["provider_id"]]
    required_codes = provider.get("required_consent_codes") or []
    if consent_code not in required_codes:
        raise err(ERR_CONSENT_CODE_NOT_REQUIRED, "consent_code not required by provider")

    with db.LOCK:
        _first_in_progress(session)
        now = db.now_iso()
        consent = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "intake_session_id": intake_session_id,
            "consent_code": consent_code,
            "signer_name": None,
            "signed_at": None,
            "revision": 1,
            "status": "PENDING",
        }
        db.consent_documents[consent["id"]] = consent
    return success(serialize.consent_document(consent), status=201)


@bp.route("/consent-documents/<cid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk", "Patient")
def get_consent_route(cid):
    consent = get_consent(cid)
    return success(serialize.consent_document(consent), status=200)


@bp.route("/consent-documents", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk", "Patient")
def list_consents():
    records = list(db.consent_documents.values())
    val = request.args.get("intake_session_id")
    if val is not None:
        records = [r for r in records if r["intake_session_id"] == val]
    items, limit, offset, total = paginate(records, serialize.consent_document)
    return success_list(items, limit, offset, total)


@bp.route("/consent-documents/<cid>/sign", methods=["POST"])
@require_roles("Patient")
def sign_consent(cid):
    body = request.get_json(silent=True) or {}
    consent = get_consent(cid)
    with db.LOCK:
        if consent["status"] != "PENDING":
            raise err(ERR_CONSENT_NOT_PENDING, "consent not PENDING")
        session = db.intake_sessions[consent["intake_session_id"]]
        if session["workflow_status"] in {"EXPIRED", "CANCELLED", "COMPLETED"} \
                or S.is_expired(session):
            raise err(ERR_SESSION_EXPIRED, "session expired/cancelled/completed")
        signer_name = body.get("signer_name")
        if not isinstance(signer_name, str) or signer_name == "":
            raise err(ERR_INVALID_REQUEST, "signer_name required")
        clinic = db.clinics[session["clinic_id"]]
        consent["status"] = "SIGNED"
        consent["signer_name"] = signer_name
        consent["signed_at"] = clinic["current_utc"]
        touch(consent)
        S.bubble_up(session)
    return success(serialize.consent_document(consent), status=200)


@bp.route("/consent-documents/<cid>/revoke", methods=["POST"])
@require_roles("Patient")
def revoke_consent(cid):
    consent = get_consent(cid)
    with db.LOCK:
        if consent["status"] != "SIGNED":
            raise err(ERR_CONSENT_NOT_SIGNED, "consent not SIGNED")
        session = db.intake_sessions[consent["intake_session_id"]]
        if session["workflow_status"] in {"CHECKED_IN", "COMPLETED"}:
            raise err(ERR_SESSION_LOCKED, "session locked")
        consent["status"] = "REVOKED"
        consent["signed_at"] = None
        touch(consent)
        # bubble up: forms_complete now false; may revert readiness (PRD §3.7).
        S.bubble_up(session)
    return success(serialize.consent_document(consent), status=200)


@bp.route("/consent-documents/<cid>/reissue", methods=["POST"])
@require_roles("FrontDeskStaff")
def reissue_consent(cid):
    consent = get_consent(cid)
    with db.LOCK:
        if consent["status"] != "REVOKED":
            raise err(ERR_CONSENT_NOT_REVOKED, "consent not REVOKED")
        session = db.intake_sessions[consent["intake_session_id"]]
        if session["workflow_status"] in {"EXPIRED", "CANCELLED", "COMPLETED"} \
                or S.is_expired(session):
            raise err(ERR_SESSION_EXPIRED, "session expired/cancelled/completed")
        consent["status"] = "PENDING"
        consent["revision"] += 1
        touch(consent)
    return success(serialize.consent_document(consent), status=200)
