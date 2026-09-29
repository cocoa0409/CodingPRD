"""Payload factories.

Every factory returns a complete, valid request body and accepts keyword
overrides so a test can bend exactly one field. Monetary fields are emitted as
JSON numbers (integer cents) because a monetary amount sent as a string is
malformed.
"""

from .constants import TEST_DEFAULTS


def state_law_profile_payload(**overrides) -> dict:
    """A law profile for one state. Defaults describe a seventy-year,
    registration-demanding jurisdiction with a ten-year retention ceiling."""
    payload = {
        "state_code": TEST_DEFAULTS["DOMICILE_STATE"],
        "postmortem_rights_years": 70,
        "postmortem_requires_registration": True,
        "biometric_retention_max_days": 3650,
        "deletion_grace_days": 30,
        "removal_window_days": 14,
        "disclosure_required_advertising": True,
        "disclosure_required_entertainment": True,
        "min_disclosure_rank_advertising": 3,
        "min_disclosure_rank_entertainment": 2,
    }
    payload.update(overrides)
    return payload


def union_minimum_payload(**overrides) -> dict:
    """One union's floors for one media type as of one effective instant."""
    payload = {
        "union_code": "SAG_AFTRA",
        "media_type": "ADVERTISING",
        "effective_from": "2026-01-01T00:00:00Z",
        "minimum_initial_cents": 300_000,
        "minimum_per_use_cents": 200_000,
    }
    payload.update(overrides)
    return payload


def talent_payload(**overrides) -> dict:
    """A living performer domiciled in the default state with no union."""
    payload = {
        "legal_name": TEST_DEFAULTS["TALENT_NAME"],
        "domicile_state_code": TEST_DEFAULTS["DOMICILE_STATE"],
        "union_code": "NONE",
    }
    payload.update(overrides)
    return payload


def death_record_payload(**overrides) -> dict:
    """The single-field death record body."""
    payload = {"date_of_death": "2026-08-01T00:00:00Z"}
    payload.update(overrides)
    return payload


def estate_authority_payload(**overrides) -> dict:
    """An estate authority claim backed by filed letters testamentary."""
    payload = {
        "executor_name": "Marisol Reyes",
        "court_document_ref": "PROB-2026-11841",
        "registration_number": "CA-REG-77",
    }
    payload.update(overrides)
    return payload


def consent_grant_payload(talent_id: str, expected_talent_version: int, **overrides) -> dict:
    """A single-media, one-year, non-exclusive draft executed by the talent."""
    payload = {
        "talent_id": talent_id,
        "expected_talent_version": expected_talent_version,
        "grantor_kind": "TALENT",
        "estate_authority_id": None,
        "permitted_media_types": ["ADVERTISING"],
        "territory_codes": ["US"],
        "permitted_use_notes": "One national synthetic advertising campaign.",
        "exclusivity": "NON_EXCLUSIVE",
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "effective_until": TEST_DEFAULTS["EFFECTIVE_UNTIL"],
        "initial_creation_fee_cents": TEST_DEFAULTS["INITIAL_CREATION_FEE_CENTS"],
        "per_use_base_fee_cents": TEST_DEFAULTS["PER_USE_BASE_FEE_CENTS"],
        "talent_share_pct": TEST_DEFAULTS["TALENT_SHARE_PCT"],
        "agency_share_pct": TEST_DEFAULTS["AGENCY_SHARE_PCT"],
        "approval_required": True,
        "revocable": True,
    }
    payload.update(overrides)
    return payload


def countersign_payload(**overrides) -> dict:
    """Countersignature carries no required field of its own."""
    payload: dict = {}
    payload.update(overrides)
    return payload


def suspension_payload(action: str = "SUSPEND", **overrides) -> dict:
    """A suspension or reinstatement instruction."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


def revoke_payload(**overrides) -> dict:
    """A revocation with its note."""
    payload = {"revocation_note": "Talent withdraws consent for synthetic use."}
    payload.update(overrides)
    return payload


def biometric_asset_payload(talent_id: str, consent_grant_id: str, **overrides) -> dict:
    """A captured face scan held in the encrypted vault."""
    payload = {
        "talent_id": talent_id,
        "consent_grant_id": consent_grant_id,
        "asset_kind": "FACE_SCAN",
        "capture_ref": "CAP-2026-0801-A",
        "storage_class": "ENCRYPTED_VAULT",
        "payload_digest": "sha256:6f1b0c9d4e2a7b3f5c8d1e0a9b7c6d5e4f3a2b1c",
    }
    payload.update(overrides)
    return payload


def purge_payload(**overrides) -> dict:
    """A manual purge instruction with its note."""
    payload = {"purge_note": "Destroyed at the talent's request ahead of schedule."}
    payload.update(overrides)
    return payload


def digital_replica_payload(
    talent_id: str, consent_grant_id: str, source_asset_ids: list, **overrides
) -> dict:
    """A face replica trained from the supplied stored samples."""
    payload = {
        "talent_id": talent_id,
        "consent_grant_id": consent_grant_id,
        "replica_kind": "FACE",
        "build_ref": "BUILD-2026-0801-01",
        "source_asset_ids": list(source_asset_ids),
    }
    payload.update(overrides)
    return payload


def approve_replica_payload(**overrides) -> dict:
    """Talent-side approval that the built replica may be exploited."""
    payload = {"approval_note": "Approved for the agreed campaign only."}
    payload.update(overrides)
    return payload


def generated_performance_payload(digital_replica_id: str, **overrides) -> dict:
    """An advertising output projecting six hundred thousand impressions."""
    payload = {
        "digital_replica_id": digital_replica_id,
        "licensee_name": TEST_DEFAULTS["LICENSEE_NAME"],
        "media_type": "ADVERTISING",
        "territory_codes": ["US"],
        "intended_use_description": "Thirty-second synthetic spot for the autumn campaign.",
        "projected_impressions": 600_000,
        "scheduled_first_use_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def review_payload(decision: str = "APPROVE", **overrides) -> dict:
    """A review decision from the talent's side of the table."""
    payload = {"decision": decision, "review_note": "Reviewed against the agreed scope."}
    payload.update(overrides)
    return payload


def resubmit_payload(**overrides) -> dict:
    """A resubmission replacing the description and the projection."""
    payload = {
        "intended_use_description": "Revised thirty-second synthetic spot, shorter cut.",
        "projected_impressions": 600_000,
    }
    payload.update(overrides)
    return payload


def usage_license_payload(
    generated_performance_id: str, expected_replica_version: int, **overrides
) -> dict:
    """An advertising license for one territory inside the default consent term."""
    payload = {
        "generated_performance_id": generated_performance_id,
        "expected_replica_version": expected_replica_version,
        "channel": "ADVERTISING",
        "territory_codes": ["US"],
        "distribution_start": "2026-09-01T00:00:00Z",
        "distribution_end": "2026-09-30T00:00:00Z",
        "actual_impressions": 500_000,
    }
    payload.update(overrides)
    return payload


def disclosure_payload(**overrides) -> dict:
    """A disclosure attestation at pre-roll placement."""
    payload = {
        "disclosure_placement": "PRE_ROLL",
        "disclosure_label_text": "This advertisement contains a synthetic performance.",
    }
    payload.update(overrides)
    return payload


def disclosure_verification_payload(decision: str = "ACCEPT", **overrides) -> dict:
    """A compliance decision on an attested disclosure."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def go_live_payload(**overrides) -> dict:
    """A go-live instruction carrying the published reference."""
    payload = {"distribution_reference": "https://cdn.example.com/spots/autumn-2026"}
    payload.update(overrides)
    return payload


def confirm_removal_payload(**overrides) -> dict:
    """Confirmation that distributed content has been pulled down."""
    payload: dict = {}
    payload.update(overrides)
    return payload


def infringement_case_payload(talent_id: str, **overrides) -> dict:
    """A monitoring-feed detection in the default state."""
    payload = {
        "talent_id": talent_id,
        "detection_source": "MONITORING_FEED",
        "suspect_url": "https://videos.example.net/watch/9f31c",
        "detected_channel": "ADVERTISING",
        "detected_state_code": TEST_DEFAULTS["DOMICILE_STATE"],
        "detected_view_count": 400_000,
        "match_confidence": 0.5,
        "matched_usage_license_id": None,
    }
    payload.update(overrides)
    return payload


def triage_payload(decision: str = "ISSUE_TAKEDOWN", **overrides) -> dict:
    """A triage fork decision."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def escalate_payload(**overrides) -> dict:
    """An escalation to legal with its note."""
    payload = {"escalation_note": "Counsel instructed; preserving all material."}
    payload.update(overrides)
    return payload


def close_case_payload(outcome: str = "REMOVED", **overrides) -> dict:
    """A closure carrying the branch-appropriate outcome."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload
