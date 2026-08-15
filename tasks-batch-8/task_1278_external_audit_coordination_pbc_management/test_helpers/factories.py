"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS, VALID_SHA256_A


def create_engagement_payload(**overrides) -> dict:
    defaults = {
        "client_name": TEST_DEFAULTS["CLIENT_NAME"],
        "fiscal_year_end": TEST_DEFAULTS["FISCAL_YEAR_END"],
        "base_fee_cents": TEST_DEFAULTS["BASE_FEE_CENTS"],
        "materiality_cents": TEST_DEFAULTS["MATERIALITY_CENTS"],
        "filing_deadline": TEST_DEFAULTS["FILING_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "location_code": "L1",
        "name": "Headquarters",
        "materiality_cents": TEST_DEFAULTS["LOCATION_MATERIALITY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_pbc_request_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "title": TEST_DEFAULTS["PBC_TITLE"],
        "owner_user_id": TEST_DEFAULTS["PBC_OWNER"],
        "due_date": TEST_DEFAULTS["PBC_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_upload_payload(expected_engagement_version, **overrides) -> dict:
    defaults = {
        "file_name": TEST_DEFAULTS["EVIDENCE_FILE_NAME"],
        "file_size_bytes": TEST_DEFAULTS["EVIDENCE_FILE_SIZE_BYTES"],
        "sha256": VALID_SHA256_A,
        "expected_engagement_version": expected_engagement_version,
    }
    defaults.update(overrides)
    return defaults


def create_query_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "subject": TEST_DEFAULTS["QUERY_SUBJECT"],
        "severity": TEST_DEFAULTS["QUERY_SEVERITY"],
    }
    defaults.update(overrides)
    return defaults


def create_sampling_request_payload(engagement_id, location_ids, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "title": TEST_DEFAULTS["SAMPLING_TITLE"],
        "location_ids": list(location_ids),
        "window_start": TEST_DEFAULTS["SAMPLING_WINDOW_START"],
        "window_end": TEST_DEFAULTS["SAMPLING_WINDOW_END"],
        "sample_size": TEST_DEFAULTS["SAMPLE_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_fieldwork_visit_payload(engagement_id, location_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "auditor_user_id": TEST_DEFAULTS["VISIT_AUDITOR"],
        "location_id": location_id,
        "visit_start": TEST_DEFAULTS["VISIT_START"],
        "visit_end": TEST_DEFAULTS["VISIT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "description": TEST_DEFAULTS["ADJUSTMENT_DESCRIPTION"],
        "amount_cents": TEST_DEFAULTS["ADJUSTMENT_AMOUNT_CENTS"],
        "direction": TEST_DEFAULTS["ADJUSTMENT_DIRECTION"],
    }
    defaults.update(overrides)
    return defaults


def create_representation_letter_payload(engagement_id, **overrides) -> dict:
    defaults = {"engagement_id": engagement_id}
    defaults.update(overrides)
    return defaults


def create_fee_change_request_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "scope_description": TEST_DEFAULTS["FEE_SCOPE_DESCRIPTION"],
        "delta_cents": TEST_DEFAULTS["FEE_DELTA_CENTS"],
    }
    defaults.update(overrides)
    return defaults
