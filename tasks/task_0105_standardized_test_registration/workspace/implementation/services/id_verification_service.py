"""IDVerification service."""

from typing import Optional

import db
from config import ID_DOCUMENT_TYPES
from errors import (
    err_cross_state_id_mismatch,
    err_id_expired_before_test,
    err_id_verification_not_found,
    err_insufficient_permissions,
    err_invalid_id_verification_state,
    err_invalid_registration_state,
    err_invalid_request,
)
from response import parse_iso_utc
from services.common import parse_iso_or_400
from services.registration_service import get_scoped_registration_or_404


def _find_iv(registration_id: str) -> Optional[dict]:
    for v in db.id_verifications.all():
        if v["registration_id"] == registration_id:
            return v
    return None


def get_id_verification(test_event_id: str, registration_id: str, caller_role: str, caller_user_id: str) -> dict:
    r = get_scoped_registration_or_404(test_event_id, registration_id)
    if caller_role == "Candidate" and caller_user_id != r["candidate_id"]:
        raise err_insufficient_permissions()
    v = _find_iv(registration_id)
    if v is None:
        raise err_id_verification_not_found()
    return v


def submit_id_verification(
    test_event_id: str, registration_id: str, body: dict, caller_role: str, caller_user_id: str
) -> dict:
    r = get_scoped_registration_or_404(test_event_id, registration_id)
    if caller_role == "Candidate" and caller_user_id != r["candidate_id"]:
        raise err_insufficient_permissions()

    # Registration must be in STANDBY or CONFIRMED
    if r["status"] not in ("STANDBY", "CONFIRMED"):
        raise err_invalid_registration_state()

    id_document_type = body.get("id_document_type")
    issuing_state_code = body.get("issuing_state_code")
    id_expires_on = body.get("id_expires_on")

    if id_document_type not in ID_DOCUMENT_TYPES:
        raise err_invalid_request("id_document_type is invalid")
    if not id_expires_on:
        raise err_invalid_request("id_expires_on is required")
    # Validate the date is parseable
    try:
        parse_iso_utc(id_expires_on) if "T" in id_expires_on else None
    except Exception:
        # If it's a date-only string, leave verification to the clear step.
        pass

    if id_document_type != "PASSPORT":
        if not isinstance(issuing_state_code, str) or not issuing_state_code:
            raise err_invalid_request("issuing_state_code is required for non-PASSPORT documents")

    v = _find_iv(registration_id)
    if v is None:
        v = db.common_create()
        v.update(
            {
                "registration_id": registration_id,
                "id_document_type": id_document_type,
                "issuing_state_code": issuing_state_code,
                "id_expires_on": id_expires_on,
                "status": "DOCS_SUBMITTED",
                "rejection_reason": None,
                "cross_state_override_granted": False,
            }
        )
        db.id_verifications.insert(v)
        return v

    # Resubmit path: must currently be in NOT_STARTED or REJECTED
    if v["status"] not in ("NOT_STARTED", "REJECTED"):
        raise err_invalid_id_verification_state()
    v["id_document_type"] = id_document_type
    v["issuing_state_code"] = issuing_state_code
    v["id_expires_on"] = id_expires_on
    v["status"] = "DOCS_SUBMITTED"
    v["rejection_reason"] = None
    db.touch(v)
    return v


def clear_id_verification(test_event_id: str, registration_id: str, body: dict) -> dict:
    e = _get_event_for_registration(test_event_id, registration_id)
    r = db.registrations.get(registration_id)
    v = _find_iv(registration_id)
    if v is None:
        raise err_id_verification_not_found()
    if v["status"] != "DOCS_SUBMITTED":
        raise err_invalid_id_verification_state()

    allow_override = bool(body.get("allow_cross_state_override", False)) if body else False

    candidate = db.candidates.get(r["candidate_id"])

    # Priority order: cross-state mismatch first, then expiry.
    if v["id_document_type"] != "PASSPORT":
        issuing = v.get("issuing_state_code")
        if issuing != candidate["home_state_code"]:
            if not allow_override:
                raise err_cross_state_id_mismatch()
            v["cross_state_override_granted"] = True

    # Expiry check: id_expires_on must be > TestEvent.test_date
    test_date = parse_iso_utc(e["test_date"])
    expires_raw = v["id_expires_on"]
    try:
        expires_dt = parse_iso_utc(expires_raw) if "T" in expires_raw else parse_iso_utc(expires_raw + "T00:00:00Z")
    except Exception:
        raise err_id_expired_before_test()
    if expires_dt <= test_date:
        raise err_id_expired_before_test()

    v["status"] = "CLEARED"
    db.touch(v)
    return v


def reject_id_verification(test_event_id: str, registration_id: str, body: dict) -> dict:
    _get_event_for_registration(test_event_id, registration_id)
    v = _find_iv(registration_id)
    if v is None:
        raise err_id_verification_not_found()
    if v["status"] != "DOCS_SUBMITTED":
        raise err_invalid_id_verification_state()
    rejection_reason = body.get("rejection_reason") if body else None
    if not isinstance(rejection_reason, str) or not rejection_reason:
        raise err_invalid_request("rejection_reason is required")
    v["status"] = "REJECTED"
    v["rejection_reason"] = rejection_reason
    db.touch(v)
    return v


def _get_event_for_registration(test_event_id: str, registration_id: str) -> dict:
    from services.test_event_service import get_test_event_or_404

    e = get_test_event_or_404(test_event_id)
    r = db.registrations.get(registration_id)
    if r is None or r["test_event_id"] != test_event_id:
        from errors import err_registration_not_found

        raise err_registration_not_found()
    return e
