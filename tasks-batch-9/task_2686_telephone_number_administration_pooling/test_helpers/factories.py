"""Payload factories -- one per entity, carrying only the fields a client sends."""
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS

CARRIER_PROFILES = {
    "A": {
        "ocn": "1234",
        "legal_name": "Acme Telecom LLC",
        "carrier_type": "CLEC",
        "home_state_code": "OH",
        "months_in_operation": 24,
    },
    "B": {
        "ocn": "5678",
        "legal_name": "Buckeye Comm Inc",
        "carrier_type": "CLEC",
        "home_state_code": "OH",
        "months_in_operation": 36,
    },
    "C": {
        "ocn": "9012",
        "legal_name": "Scarlet Networks LLC",
        "carrier_type": "WIRELESS",
        "home_state_code": "OH",
        "months_in_operation": 60,
    },
}


def create_carrier_payload(profile: str = "A", **overrides) -> dict:
    payload = dict(CARRIER_PROFILES[profile])
    payload.update(overrides)
    return payload


def license_action_payload(action: str = "GRANT", **overrides) -> dict:
    payload = {"action": action}
    if action in ("GRANT", "RENEW"):
        payload["license_expires_on"] = TEST_DEFAULTS["LICENSE_EXPIRES_ON"]
    payload.update(overrides)
    return payload


def readiness_event_payload(event: str = "ATTEST", **overrides) -> dict:
    payload = {"event": event}
    if event == "ATTEST":
        payload["switch_clli"] = TEST_DEFAULTS["SWITCH_CLLI_A"]
        payload["interconnection_ready"] = True
    payload.update(overrides)
    return payload


def create_npa_payload(**overrides) -> dict:
    payload = {
        "npa_code": TEST_DEFAULTS["NPA_CODE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "npa_type": "GEOGRAPHIC",
    }
    payload.update(overrides)
    return payload


def create_rate_center_payload(npa_id: str, **overrides) -> dict:
    payload = {
        "npa_id": npa_id,
        "name": TEST_DEFAULTS["RATE_CENTER_NAME"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "lata_code": TEST_DEFAULTS["LATA_CODE"],
    }
    payload.update(overrides)
    return payload


def create_block_payload(npa_id: str, rate_center_id: str, nxx_code: str = "554",
                         thousands_digit: int = 0, **overrides) -> dict:
    payload = {
        "npa_id": npa_id,
        "rate_center_id": rate_center_id,
        "nxx_code": nxx_code,
        "thousands_digit": thousands_digit,
    }
    payload.update(overrides)
    return payload


def create_utilization_filing_payload(carrier_id: str, rate_center_id: str,
                                      numbers_assigned: int = 2500,
                                      numbers_intermediate: int = 400,
                                      numbers_reserved: int = 200,
                                      numbers_aging: int = 300,
                                      numbers_administrative: int = 200,
                                      blocks_held_at_period_end: int = 5,
                                      forecast_quarters=None,
                                      reporting_period: str = None,
                                      **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "rate_center_id": rate_center_id,
        "reporting_period": reporting_period or TEST_DEFAULTS["REPORTING_PERIOD"],
        "numbers_assigned": numbers_assigned,
        "numbers_intermediate": numbers_intermediate,
        "numbers_reserved": numbers_reserved,
        "numbers_aging": numbers_aging,
        "numbers_administrative": numbers_administrative,
        "blocks_held_at_period_end": blocks_held_at_period_end,
        "forecast_quarters": list(forecast_quarters) if forecast_quarters is not None
        else [1800, 1200, 900, 600],
    }
    payload.update(overrides)
    return payload


def create_allocation_request_payload(carrier_id: str, rate_center_id: str,
                                      expected_rate_center_version: int,
                                      request_type: str = "GROWTH",
                                      requested_block_count: int = 1,
                                      **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "rate_center_id": rate_center_id,
        "request_type": request_type,
        "requested_block_count": requested_block_count,
        "expected_rate_center_version": expected_rate_center_version,
    }
    payload.update(overrides)
    return payload


def review_payload(action: str = "APPROVE", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def resubmission_payload(revised_requested_block_count: int = 1,
                         response_note: str = "Revised forecast attached.",
                         **overrides) -> dict:
    payload = {
        "revised_requested_block_count": revised_requested_block_count,
        "response_note": response_note,
    }
    payload.update(overrides)
    return payload


def create_audit_finding_payload(finding_type: str = "OVERSTATED_UTILIZATION",
                                 **overrides) -> dict:
    payload = {"finding_type": finding_type}
    payload.update(overrides)
    return payload


def disposition_payload(disposition: str = "ACCEPT", **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_routing_record_payload(expected_block_version: int, lrn: str = "6145560000",
                                  switch_clli: str = None,
                                  effective_at: str = DEFAULT_CLOCK, **overrides) -> dict:
    payload = {
        "lrn": lrn,
        "switch_clli": switch_clli or TEST_DEFAULTS["SWITCH_CLLI_A"],
        "effective_at": effective_at,
        "expected_block_version": expected_block_version,
    }
    payload.update(overrides)
    return payload


def create_port_request_payload(telephone_number: str, number_block_id: str,
                               from_carrier_id: str, to_carrier_id: str,
                               requested_lrn: str = "6145570000",
                               desired_due_at: str = "2026-09-15T00:00:00Z",
                               **overrides) -> dict:
    payload = {
        "telephone_number": telephone_number,
        "number_block_id": number_block_id,
        "from_carrier_id": from_carrier_id,
        "to_carrier_id": to_carrier_id,
        "requested_lrn": requested_lrn,
        "desired_due_at": desired_due_at,
    }
    payload.update(overrides)
    return payload


def create_relief_plan_payload(**overrides) -> dict:
    payload = {"planned_relief_type": "UNDETERMINED"}
    payload.update(overrides)
    return payload


def create_public_comment_payload(commenter_type: str = "CONSUMER",
                                  position: str = "SUPPORT_OVERLAY",
                                  body: str = "Please keep our existing numbers.",
                                  **overrides) -> dict:
    payload = {
        "commenter_type": commenter_type,
        "position": position,
        "body": body,
    }
    payload.update(overrides)
    return payload
