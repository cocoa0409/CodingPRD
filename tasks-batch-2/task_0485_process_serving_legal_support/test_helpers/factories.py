"""Payload factories — one per entity, input fields only (PRD section 3)."""


def create_client_payload(**overrides) -> dict:
    defaults = {"firm_name": "Test Law Firm", "email": "firm@law.test"}
    defaults.update(overrides)
    return defaults


def create_county_payload(**overrides) -> dict:
    """Only name + state_code are required; the four policy fields are optional
    and take documented server-side defaults when omitted."""
    defaults = {"name": "Test County", "state_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_server_payload(**overrides) -> dict:
    """max_active_assignments is optional (defaults to 5)."""
    defaults = {"full_name": "Test Server", "license_no": "PS-0000"}
    defaults.update(overrides)
    return defaults


def create_service_request_payload(client_id, county_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "county_id": county_id,
        "recipient_name": "John Doe",
        "service_address": "1 Main St",
        "service_lat": 37.8,
        "service_lng": -122.2,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {"doc_type": "SUMMONS", "page_count": 1}
    defaults.update(overrides)
    return defaults


def offer_assignment_payload(server_id, expected_version, **overrides) -> dict:
    defaults = {
        "server_id": server_id,
        "expected_service_request_version": expected_version,
    }
    defaults.update(overrides)
    return defaults


def create_attempt_payload(attempted_at_utc, outcome, **overrides) -> dict:
    defaults = {
        "attempted_at_utc": attempted_at_utc,
        "gps_lat": 37.8,
        "gps_lng": -122.2,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def record_service_payload(assignment_id, service_type, served_at_utc, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "service_type": service_type,
        "served_at_utc": served_at_utc,
    }
    defaults.update(overrides)
    return defaults


def create_skip_trace_payload(**overrides) -> dict:
    """candidate_addresses is optional (defaults to empty array)."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_stakeout_payload(window_start_utc, window_end_utc, **overrides) -> dict:
    defaults = {
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(affidavit_id, window_start_utc, window_end_utc, **overrides) -> dict:
    defaults = {
        "affidavit_id": affidavit_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    defaults.update(overrides)
    return defaults
