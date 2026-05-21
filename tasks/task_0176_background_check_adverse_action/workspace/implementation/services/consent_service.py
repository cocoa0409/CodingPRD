"""ConsentDisclosure service."""
from __future__ import annotations

from core.errors import (
    err_consent_invalid,
    err_invalid_state,
    err_validation_failed,
)
from core.store import store
from core.clock import logical_now_iso
from services.audit_service import append_event
from services.timestamps import stamp_create, stamp_update
from services.validations import (
    enforce_consent_timestamps,
    get_active_consent_for_candidate,
)


def record_consent(*, candidate: dict, body: dict, actor_role: str, actor_user_id: str) -> dict:
    disclosure_text_hash = body.get("disclosure_text_hash")
    consent_signature = body.get("consent_signature")
    consent_timestamp = body.get("consent_timestamp")
    disclosure_presented_at = body.get("disclosure_presented_at")

    if not isinstance(disclosure_text_hash, str) or disclosure_text_hash == "":
        raise err_validation_failed("disclosure_text_hash is required.")
    if not isinstance(consent_signature, str) or consent_signature == "":
        raise err_validation_failed("consent_signature is required.")
    if not isinstance(consent_timestamp, str) or consent_timestamp == "":
        raise err_validation_failed("consent_timestamp is required.")
    if not isinstance(disclosure_presented_at, str) or disclosure_presented_at == "":
        raise err_validation_failed("disclosure_presented_at is required.")

    enforce_consent_timestamps(
        disclosure_presented_at=disclosure_presented_at,
        consent_timestamp=consent_timestamp,
    )

    # Supersede previous ACTIVE consent.
    prev = get_active_consent_for_candidate(candidate["id"])
    if prev is not None:
        prev["status"] = "SUPERSEDED"
        stamp_update(prev)

    row = {
        "candidate_id": candidate["id"],
        "disclosure_text_hash": disclosure_text_hash,
        "consent_signature": consent_signature,
        "consent_timestamp": consent_timestamp,
        "disclosure_presented_at": disclosure_presented_at,
        "revoked_at": None,
        "status": "ACTIVE",
    }
    stamp_create(row)
    store.consents[row["id"]] = row

    append_event(
        event_type="CONSENT_RECORDED",
        subject_entity="ConsentDisclosure",
        subject_id=row["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return row


def revoke_consent(*, candidate: dict, actor_role: str, actor_user_id: str) -> dict:
    consent = get_active_consent_for_candidate(candidate["id"])
    if consent is None:
        raise err_invalid_state(
            "No ACTIVE consent exists for this candidate to revoke."
        )
    consent["status"] = "REVOKED"
    consent["revoked_at"] = logical_now_iso()
    stamp_update(consent)
    append_event(
        event_type="CONSENT_REVOKED",
        subject_entity="ConsentDisclosure",
        subject_id=consent["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return consent
