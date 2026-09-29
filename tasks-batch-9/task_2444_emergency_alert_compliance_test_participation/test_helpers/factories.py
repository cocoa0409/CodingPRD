"""Payload factories — one per entity, operator-supplied input fields only."""

from .constants import SOURCE_CALL_SIGNS, TEST_DEFAULTS
from .test_users import ENGINEER_USER_ID, OFFICER_USER_ID


def state_plan_payload(**overrides) -> dict:
    payload = {
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "plan_version_label": TEST_DEFAULTS["PLAN_LABEL"],
        "required_source_types": ["PEP"],
        "mandatory_relay_event_codes": [],
    }
    payload.update(overrides)
    return payload


def station_payload(state_plan_id, **overrides) -> dict:
    payload = {
        "state_plan_id": state_plan_id,
        "call_sign": TEST_DEFAULTS["CALL_SIGN"],
        "service_type": TEST_DEFAULTS["SERVICE_TYPE"],
        "engineer_user_ids": [ENGINEER_USER_ID],
        "certification_officer_user_id": OFFICER_USER_ID,
    }
    payload.update(overrides)
    return payload


def relay_rule_payload(state_plan_id, **overrides) -> dict:
    payload = {
        "state_plan_id": state_plan_id,
        "event_code": "TOR",
        "fips_codes": [TEST_DEFAULTS["FIPS_CODE"]],
        "relay_class": "MANDATORY",
        "priority": 10,
        "forward_delay_seconds": 30,
    }
    payload.update(overrides)
    return payload


def device_payload(station_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "device_role": TEST_DEFAULTS["DEVICE_ROLE"],
        "firmware_version": TEST_DEFAULTS["FIRMWARE_VERSION"],
    }
    payload.update(overrides)
    return payload


def readiness_check_payload(**overrides) -> dict:
    payload = {"self_test_passed": True, "firmware_current": True}
    payload.update(overrides)
    return payload


def monitoring_assignment_payload(
    station_id, device_id, expected_station_version, source_type="PEP", **overrides
) -> dict:
    payload = {
        "station_id": station_id,
        "device_id": device_id,
        "source_type": source_type,
        "source_call_sign": SOURCE_CALL_SIGNS.get(source_type, "WXPEP"),
        "expected_station_version": expected_station_version,
    }
    payload.update(overrides)
    return payload


def equipment_outage_payload(device_id, detected_at, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "detected_at": detected_at,
        "failure_summary": "decoder RF front end dead",
    }
    payload.update(overrides)
    return payload


def alert_event_payload(station_id, received_at, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "event_code": "TOR",
        "originator_sequence": "KSACC-0001",
        "fips_codes": [TEST_DEFAULTS["FIPS_CODE"]],
        "received_at": received_at,
    }
    payload.update(overrides)
    return payload


def accessibility_payload(**overrides) -> dict:
    payload = {
        "visual_crawl_seconds": 60,
        "audio_loudness_lufs": -24.0,
        "caption_interaction": "NONE",
    }
    payload.update(overrides)
    return payload


def wireless_alert_notice_payload(station_id, wea_sent_at, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "originator_sequence": "KSWEA-0101",
        "event_code": "TOR",
        "wea_sent_at": wea_sent_at,
        "fips_codes": [TEST_DEFAULTS["FIPS_CODE"]],
    }
    payload.update(overrides)
    return payload


def test_event_payload(
    station_id,
    window_start_at="2026-08-12T00:00:00Z",
    window_end_at="2026-08-12T01:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "station_id": station_id,
        "test_type": "WEEKLY",
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


def test_log_entry_payload(test_event_id, device_id, entry_kind="TRANSMISSION", **overrides) -> dict:
    payload = {
        "test_event_id": test_event_id,
        "device_id": device_id,
        "entry_kind": entry_kind,
    }
    if entry_kind == "RECEIPT":
        payload["source_call_sign"] = SOURCE_CALL_SIGNS["PEP"]
    payload.update(overrides)
    return payload


def filing_record_payload(test_event_id, expected_test_event_version, **overrides) -> dict:
    payload = {
        "test_event_id": test_event_id,
        "expected_test_event_version": expected_test_event_version,
        "attestation_note": "weekly test results attested",
    }
    payload.update(overrides)
    return payload


def reversal_payload(**overrides) -> dict:
    payload = {"reversal_reason": "ATTESTATION_WITHDRAWN"}
    payload.update(overrides)
    return payload


def inspection_request_payload(station_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "requested_document_kinds": ["STATION_LOG", "TEST_LOGS"],
    }
    payload.update(overrides)
    return payload


def draft_response_payload(provided_document_kinds=None, **overrides) -> dict:
    payload = {
        "provided_document_kinds": provided_document_kinds
        if provided_document_kinds is not None
        else ["STATION_LOG", "TEST_LOGS"]
    }
    payload.update(overrides)
    return payload


def public_file_document_payload(**overrides) -> dict:
    payload = {"document_kind": "STATION_LOG", "reference_label": "station log 2026-08"}
    payload.update(overrides)
    return payload
