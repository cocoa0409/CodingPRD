"""Payload factories — one per creatable resource, input fields only.

Every factory accepts `**overrides` so a test can control exactly the field it
is exercising and inherit sane defaults for everything else. Passing
`field=None` removes the field from the payload, which is how omission tests
are written.
"""

from typing import Optional

DEFAULTS = {
    "LICENSE_CODE": "LIC-US-CA-KA-01",
    "JURISDICTION_CODE": "US-CA",
    "FREQUENCY_BAND": "KA_FORWARD",
    "MAX_EIRP_DBW": 62.5,
    "LICENSE_EXPIRES_AT": "2027-12-31T00:00:00Z",
    "CONSUMER_DISCLOSURE_VERSION": "CD-2026.1",
    "BEAM_CODE": "BEAM-01",
    "SATELLITE_CODE": "SAT-A",
    "FORWARD_CAPACITY_MBPS": 100,
    "OVERSUBSCRIPTION_LIMIT": 4.0,
    "CELL_CODE": "CELL-001",
    "MAX_ACTIVE_TERMINALS": 1,
    "PLAN_CODE": "PLAN-P1-200",
    "COMMITTED_RATE_MBPS": 200,
    "PRIORITY_TIER": "PRIORITY_1",
    "MONTHLY_FEE_CENTS": 9900,
    "PRIORITY_DATA_GB": 100,
    "DEPRIORITIZED_RATE_MBPS": 20,
    "OVERAGE_RATE_CENTS_PER_GB": 25,
    "EMAIL": "sub1@example.com",
    "FULL_NAME": "Sub One",
    "SERIAL_NUMBER": "TRM-0001",
    "WARRANTY_EXPIRES_AT": "2028-08-01T00:00:00Z",
    "TOTAL_SAMPLE_COUNT": 200,
    "OBSTRUCTED_SAMPLE_COUNT": 1,
}


def _clean(payload: dict) -> dict:
    """Drop keys explicitly set to None so omission can be expressed as an override."""
    return {k: v for k, v in payload.items() if v is not None}


# ───────────────────────── spectrum licences ─────────────────────────

def create_spectrum_license_payload(**overrides) -> dict:
    payload = {
        "license_code": DEFAULTS["LICENSE_CODE"],
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "frequency_band": DEFAULTS["FREQUENCY_BAND"],
        "max_eirp_dbw": DEFAULTS["MAX_EIRP_DBW"],
        "expires_at": DEFAULTS["LICENSE_EXPIRES_AT"],
        "consumer_disclosure_version": DEFAULTS["CONSUMER_DISCLOSURE_VERSION"],
        "in_motion_permitted": True,
    }
    payload.update(overrides)
    return _clean(payload)


def coordination_payload(outcome: str = "GRANTED", **overrides) -> dict:
    payload = {"outcome": outcome, "coordination_note": "no neighbour objection"}
    payload.update(overrides)
    return _clean(payload)


def enforcement_action_payload(action: str = "SUSPEND", **overrides) -> dict:
    payload = {"action": action, "reason": "regulator directive"}
    payload.update(overrides)
    return _clean(payload)


# ─────────────────────────────── beams ───────────────────────────────

def create_beam_payload(spectrum_license_id: Optional[str] = None, **overrides) -> dict:
    payload = {
        "beam_code": DEFAULTS["BEAM_CODE"],
        "satellite_code": DEFAULTS["SATELLITE_CODE"],
        "spectrum_license_id": spectrum_license_id,
        "forward_capacity_mbps": DEFAULTS["FORWARD_CAPACITY_MBPS"],
        "oversubscription_limit": DEFAULTS["OVERSUBSCRIPTION_LIMIT"],
    }
    payload.update(overrides)
    return _clean(payload)


def capacity_policy_payload(
    expected_beam_version: Optional[int] = None,
    oversubscription_limit: float = 4.0,
    deprioritization_grace_gb: int = 0,
    **overrides,
) -> dict:
    payload = {
        "oversubscription_limit": oversubscription_limit,
        "deprioritization_grace_gb": deprioritization_grace_gb,
        "expected_beam_version": expected_beam_version,
    }
    payload.update(overrides)
    return _clean(payload)


# ───────────────────────────── cells ─────────────────────────────────

def create_service_cell_payload(beam_id: Optional[str] = None, **overrides) -> dict:
    payload = {
        "cell_code": DEFAULTS["CELL_CODE"],
        "beam_id": beam_id,
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "max_active_terminals": DEFAULTS["MAX_ACTIVE_TERMINALS"],
    }
    payload.update(overrides)
    return _clean(payload)


# ───────────────────────────── plans ─────────────────────────────────

def create_service_plan_payload(**overrides) -> dict:
    payload = {
        "plan_code": DEFAULTS["PLAN_CODE"],
        "committed_rate_mbps": DEFAULTS["COMMITTED_RATE_MBPS"],
        "priority_tier": DEFAULTS["PRIORITY_TIER"],
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
        "priority_data_gb": DEFAULTS["PRIORITY_DATA_GB"],
        "deprioritized_rate_mbps": DEFAULTS["DEPRIORITIZED_RATE_MBPS"],
        "overage_rate_cents_per_gb": DEFAULTS["OVERAGE_RATE_CENTS_PER_GB"],
        "roaming_allowed": True,
        "in_motion_allowed": True,
    }
    payload.update(overrides)
    return _clean(payload)


# ─────────────────────────── subscribers ─────────────────────────────

def create_subscriber_payload(**overrides) -> dict:
    payload = {
        "email": DEFAULTS["EMAIL"],
        "full_name": DEFAULTS["FULL_NAME"],
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
    }
    payload.update(overrides)
    return _clean(payload)


# ─────────────────────────── service orders ──────────────────────────

def create_service_order_payload(
    subscriber_id: Optional[str] = None,
    service_cell_id: Optional[str] = None,
    requested_plan_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "service_cell_id": service_cell_id,
        "requested_plan_id": requested_plan_id,
    }
    payload.update(overrides)
    return _clean(payload)


def cancel_order_payload(**overrides) -> dict:
    payload = {"cancel_reason": "customer changed their mind"}
    payload.update(overrides)
    return _clean(payload)


# ───────────────────────────── terminals ─────────────────────────────

def create_terminal_payload(subscriber_id: Optional[str] = None, **overrides) -> dict:
    payload = {
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "subscriber_id": subscriber_id,
        "warranty_expires_at": DEFAULTS["WARRANTY_EXPIRES_AT"],
    }
    payload.update(overrides)
    return _clean(payload)


def obstruction_scan_payload(
    obstructed_sample_count: int = DEFAULTS["OBSTRUCTED_SAMPLE_COUNT"],
    total_sample_count: int = DEFAULTS["TOTAL_SAMPLE_COUNT"],
    **overrides,
) -> dict:
    payload = {
        "obstructed_sample_count": obstructed_sample_count,
        "total_sample_count": total_sample_count,
    }
    payload.update(overrides)
    return _clean(payload)


def return_terminal_payload(event: str = "INITIATE", **overrides) -> dict:
    payload = {"event": event}
    payload.update(overrides)
    return _clean(payload)


def warranty_replacement_payload(
    replacement_serial_number: str = "TRM-0001-R",
    replacement_warranty_expires_at: str = "2029-08-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "replacement_serial_number": replacement_serial_number,
        "replacement_warranty_expires_at": replacement_warranty_expires_at,
    }
    payload.update(overrides)
    return _clean(payload)


def transfer_terminal_payload(new_subscriber_id: Optional[str] = None, **overrides) -> dict:
    payload = {"new_subscriber_id": new_subscriber_id}
    payload.update(overrides)
    return _clean(payload)


# ─────────────────────────── subscriptions ───────────────────────────

def create_subscription_payload(
    service_order_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
    expected_service_cell_version: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "service_order_id": service_order_id,
        "terminal_id": terminal_id,
        "expected_service_cell_version": expected_service_cell_version,
    }
    payload.update(overrides)
    return _clean(payload)


def disclosure_acknowledgement_payload(acknowledged_version: Optional[str] = None, **overrides) -> dict:
    payload = {
        "acknowledged_version": (
            acknowledged_version
            if acknowledged_version is not None
            else DEFAULTS["CONSUMER_DISCLOSURE_VERSION"]
        )
    }
    payload.update(overrides)
    return _clean(payload)


def authorize_payload(authorization_mode: str = "FIXED", **overrides) -> dict:
    payload = {"authorization_mode": authorization_mode}
    payload.update(overrides)
    return _clean(payload)


def plan_change_payload(
    new_service_plan_id: Optional[str] = None,
    expected_beam_version: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "new_service_plan_id": new_service_plan_id,
        "expected_beam_version": expected_beam_version,
    }
    payload.update(overrides)
    return _clean(payload)


def suspend_payload(**overrides) -> dict:
    payload = {"suspend_reason": "non-payment"}
    payload.update(overrides)
    return _clean(payload)


def terminate_payload(**overrides) -> dict:
    payload = {"termination_reason": "customer cancelled service"}
    payload.update(overrides)
    return _clean(payload)


def usage_record_payload(gb_used: float = 10.0, billing_cycle_index: int = 0, **overrides) -> dict:
    payload = {"gb_used": gb_used, "billing_cycle_index": billing_cycle_index}
    payload.update(overrides)
    return _clean(payload)


# ─────────────────────── roaming authorisations ──────────────────────

def create_roaming_authorization_payload(
    subscription_id: Optional[str] = None,
    mode: str = "ROAM_TEMPORARY",
    target_jurisdiction_code: str = "US-NV",
    effective_from: str = "2026-09-01T00:00:00Z",
    effective_until: str = "2026-09-10T00:00:00Z",
    target_service_cell_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "mode": mode,
        "target_jurisdiction_code": target_jurisdiction_code,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "target_service_cell_id": target_service_cell_id,
    }
    payload.update(overrides)
    return _clean(payload)


def request_info_payload(**overrides) -> dict:
    payload = {"info_request_note": "please supply the address of record"}
    payload.update(overrides)
    return _clean(payload)


def resubmit_payload(
    effective_from: str = "2026-10-01T00:00:00Z",
    effective_until: str = "2026-10-10T00:00:00Z",
    **overrides,
) -> dict:
    payload = {"effective_from": effective_from, "effective_until": effective_until}
    payload.update(overrides)
    return _clean(payload)


def roaming_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision, "decision_note": "evidence accepted"}
    payload.update(overrides)
    return _clean(payload)


# ───────────────────── outage events and credits ─────────────────────

def create_outage_event_payload(
    beam_id: Optional[str] = None,
    cause: str = "EQUIPMENT_FAILURE",
    severity: str = "FULL_OUTAGE",
    started_at: str = "2026-08-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "beam_id": beam_id,
        "cause": cause,
        "severity": severity,
        "started_at": started_at,
    }
    payload.update(overrides)
    return _clean(payload)


def resolve_outage_payload(ended_at: str = "2026-08-01T01:00:00Z", **overrides) -> dict:
    payload = {"ended_at": ended_at}
    payload.update(overrides)
    return _clean(payload)


def credit_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision, "decision_reason": "impairment confirmed"}
    payload.update(overrides)
    return _clean(payload)


# ───────────────────────────── clock ─────────────────────────────────

def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return _clean(payload)
