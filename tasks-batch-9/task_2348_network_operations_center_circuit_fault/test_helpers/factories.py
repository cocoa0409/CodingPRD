"""Request-payload factories.

Each factory returns a valid request body for one endpoint, with the smallest
sensible defaults so a test only has to name what it actually cares about.
Every keyword override lands directly in the payload; passing `None` for an
optional field removes it, so a test can exercise the omitted-field branch.
"""

from typing import Any, Optional


def _apply(payload: dict, overrides: dict) -> dict:
    """Merge overrides into a payload, dropping keys explicitly set to None."""
    for key, value in overrides.items():
        if value is None and key in payload:
            del payload[key]
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str, **overrides: Any) -> dict:
    return _apply({"to_iso8601": to_iso8601}, overrides)


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
def carrier_payload(
    name: str = "Plainfield Telecom",
    carrier_code: str = "PFT",
    **overrides: Any,
) -> dict:
    """A carrier with no parameter overrides, so every default applies."""
    return _apply({"name": name, "carrier_code": carrier_code}, overrides)


# ---------------------------------------------------------------------------
# Circuits
# ---------------------------------------------------------------------------
def circuit_payload(
    carrier_id: str,
    carrier_circuit_identifier: str = "PFT-CKT-9001",
    site_a_code: str = "CHI01",
    site_z_code: str = "MSP01",
    bandwidth_mbps: int = 500,
    mrc_cents: int = 275000,
    monitoring_state: Optional[str] = "MONITORED",
    **overrides: Any,
) -> dict:
    candidate = {
        "carrier_id": carrier_id,
        "carrier_circuit_identifier": carrier_circuit_identifier,
        "site_a_code": site_a_code,
        "site_z_code": site_z_code,
        "bandwidth_mbps": bandwidth_mbps,
        "mrc_cents": mrc_cents,
        "monitoring_state": monitoring_state,
    }
    # Passing None for any field omits it, so a test can exercise the
    # omitted-field branch for both required and optional inputs.
    payload = {key: value for key, value in candidate.items() if value is not None}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
def device_payload(
    hostname: str = "chi01-rtr-1",
    site_code: str = "CHI01",
    device_role: str = "EDGE",
    primary_uplink_circuit_id: Optional[str] = None,
    monitoring_state: Optional[str] = "MONITORED",
    **overrides: Any,
) -> dict:
    payload: dict = {
        "hostname": hostname,
        "site_code": site_code,
        "device_role": device_role,
    }
    if primary_uplink_circuit_id is not None:
        payload["primary_uplink_circuit_id"] = primary_uplink_circuit_id
    if monitoring_state is not None:
        payload["monitoring_state"] = monitoring_state
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Application paths and segments
# ---------------------------------------------------------------------------
def application_path_payload(
    name: str = "Guest",
    service_tier: str = "BRONZE",
    protection_scheme: str = "UNPROTECTED",
    min_surviving_legs: Optional[int] = 1,
    **overrides: Any,
) -> dict:
    payload: dict = {
        "name": name,
        "service_tier": service_tier,
        "protection_scheme": protection_scheme,
    }
    if min_surviving_legs is not None:
        payload["min_surviving_legs"] = min_surviving_legs
    return _apply(payload, overrides)


def path_segment_payload(
    application_path_id: str,
    leg_group: str = "LEG_A",
    sequence_index: int = 1,
    circuit_id: Optional[str] = None,
    device_id: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {
        "application_path_id": application_path_id,
        "leg_group": leg_group,
        "sequence_index": sequence_index,
    }
    if circuit_id is not None:
        payload["circuit_id"] = circuit_id
    if device_id is not None:
        payload["device_id"] = device_id
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Alarms
# ---------------------------------------------------------------------------
def alarm_payload(
    raised_at: str,
    alarm_type: str = "LOSS_OF_SIGNAL",
    raw_severity: str = "CRITICAL",
    source_circuit_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {
        "alarm_type": alarm_type,
        "raw_severity": raw_severity,
        "raised_at": raised_at,
    }
    if source_circuit_id is not None:
        payload["source_circuit_id"] = source_circuit_id
    if source_device_id is not None:
        payload["source_device_id"] = source_device_id
    return _apply(payload, overrides)


def alarm_clear_payload(cleared_at: str, **overrides: Any) -> dict:
    return _apply({"cleared_at": cleared_at}, overrides)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
def incident_response_payload(
    target_response_state: str, note: Optional[str] = None, **overrides: Any
) -> dict:
    payload: dict = {"target_response_state": target_response_state}
    if note is not None:
        payload["note"] = note
    return _apply(payload, overrides)


def incident_escalate_payload(target_escalation_state: str, **overrides: Any) -> dict:
    return _apply({"target_escalation_state": target_escalation_state}, overrides)


def incident_resolve_payload(
    resolution_note: Optional[str] = None, **overrides: Any
) -> dict:
    payload: dict = {}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Carrier tickets
# ---------------------------------------------------------------------------
def carrier_ticket_payload(
    incident_id: str,
    circuit_id: str,
    carrier_reference: str = "PFT-TT-1",
    **overrides: Any,
) -> dict:
    return _apply(
        {
            "incident_id": incident_id,
            "circuit_id": circuit_id,
            "carrier_reference": carrier_reference,
        },
        overrides,
    )


def test_result_payload(
    test_type: str = "BERT",
    outcome: str = "FAIL",
    notes: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {"test_type": test_type, "outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    return _apply(payload, overrides)


def ticket_escalate_payload(
    target_tier: int, justification: Optional[str] = None, **overrides: Any
) -> dict:
    payload: dict = {"target_tier": target_tier}
    if justification is not None:
        payload["justification"] = justification
    return _apply(payload, overrides)


def carrier_update_payload(
    update: str, restored_at: Optional[str] = None, **overrides: Any
) -> dict:
    payload: dict = {"update": update}
    if restored_at is not None:
        payload["restored_at"] = restored_at
    return _apply(payload, overrides)


def confirm_restoration_payload(soak_passed: bool, **overrides: Any) -> dict:
    return _apply({"soak_passed": soak_passed}, overrides)


# ---------------------------------------------------------------------------
# SLA credit claims
# ---------------------------------------------------------------------------
def sla_credit_claim_payload(
    carrier_ticket_id: str,
    expected_carrier_ticket_version: int,
    basis: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {
        "carrier_ticket_id": carrier_ticket_id,
        "expected_carrier_ticket_version": expected_carrier_ticket_version,
    }
    if basis is not None:
        payload["basis"] = basis
    return _apply(payload, overrides)


def claim_submit_payload(
    basis: Optional[str] = None,
    attestation_note: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {}
    if basis is not None:
        payload["basis"] = basis
    if attestation_note is not None:
        payload["attestation_note"] = attestation_note
    return _apply(payload, overrides)


def carrier_response_payload(
    response: str, rejection_reason: Optional[str] = None, **overrides: Any
) -> dict:
    payload: dict = {"response": response}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return _apply(payload, overrides)


def claim_settle_payload(paid_amount_cents: int, **overrides: Any) -> dict:
    return _apply({"paid_amount_cents": paid_amount_cents}, overrides)


# ---------------------------------------------------------------------------
# Maintenance windows
# ---------------------------------------------------------------------------
def maintenance_window_payload(
    circuit_id: str,
    window_start: str,
    window_end: str,
    origin: str = "INTERNAL_CHANGE",
    suppresses_monitoring: Optional[bool] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {
        "circuit_id": circuit_id,
        "origin": origin,
        "window_start": window_start,
        "window_end": window_end,
    }
    if suppresses_monitoring is not None:
        payload["suppresses_monitoring"] = suppresses_monitoring
    return _apply(payload, overrides)


def window_review_payload(
    decision: str, risk_acknowledged: Optional[bool] = None, **overrides: Any
) -> dict:
    payload: dict = {"decision": decision}
    if risk_acknowledged is not None:
        payload["risk_acknowledged"] = risk_acknowledged
    return _apply(payload, overrides)


def window_state_payload(target_state: str, **overrides: Any) -> dict:
    return _apply({"target_state": target_state}, overrides)


# ---------------------------------------------------------------------------
# Failover tests
# ---------------------------------------------------------------------------
def failover_test_payload(
    application_path_id: str,
    tested_leg_group: str,
    scheduled_start: str,
    scheduled_end: str,
    **overrides: Any,
) -> dict:
    return _apply(
        {
            "application_path_id": application_path_id,
            "tested_leg_group": tested_leg_group,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
        },
        overrides,
    )


def failover_result_payload(
    outcome: str, surviving_leg_count: Optional[int] = None, **overrides: Any
) -> dict:
    payload: dict = {"outcome": outcome}
    if surviving_leg_count is not None:
        payload["surviving_leg_count"] = surviving_leg_count
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Capacity readings and upgrade orders
# ---------------------------------------------------------------------------
def capacity_reading_payload(
    sample_at: str,
    utilization_pct: float,
    direction: str = "INGRESS",
    **overrides: Any,
) -> dict:
    return _apply(
        {
            "sample_at": sample_at,
            "utilization_pct": utilization_pct,
            "direction": direction,
        },
        overrides,
    )


def upgrade_order_payload(
    circuit_id: str,
    target_bandwidth_mbps: int,
    expected_circuit_version: int,
    expedite: Optional[bool] = None,
    **overrides: Any,
) -> dict:
    payload: dict = {
        "circuit_id": circuit_id,
        "target_bandwidth_mbps": target_bandwidth_mbps,
        "expected_circuit_version": expected_circuit_version,
    }
    if expedite is not None:
        payload["expedite"] = expedite
    return _apply(payload, overrides)


def order_state_payload(target_state: str, **overrides: Any) -> dict:
    return _apply({"target_state": target_state}, overrides)


def order_cancel_payload(cancel_reason: Optional[str] = None, **overrides: Any) -> dict:
    payload: dict = {}
    if cancel_reason is not None:
        payload["cancel_reason"] = cancel_reason
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Vendor reviews
# ---------------------------------------------------------------------------
def vendor_review_payload(
    carrier_id: str, period_start: str, period_end: str, **overrides: Any
) -> dict:
    return _apply(
        {
            "carrier_id": carrier_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def review_decide_payload(
    decision: str, justification: Optional[str] = None, **overrides: Any
) -> dict:
    payload: dict = {"decision": decision}
    if justification is not None:
        payload["justification"] = justification
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Query-parameter helpers
# ---------------------------------------------------------------------------
def availability_params(from_iso8601: str, to_iso8601: str, basis: str) -> dict:
    return {
        "from_iso8601": from_iso8601,
        "to_iso8601": to_iso8601,
        "basis": basis,
    }


def page_params(limit: Optional[int] = None, offset: Optional[int] = None, **filters):
    params: dict = dict(filters)
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return params
