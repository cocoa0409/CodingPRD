"""Payload factories — one per created resource, input fields only."""
from typing import Any, Dict, List, Optional

DEFAULTS = {
    "HOST_ORG_NAME": "Test Host Organisation",
    "COMMITTED_CAPACITY_KW": 400.00,
    "POWER_CLASS": "DCFC_150",
    "DECLARED_PORT_COUNT": 1,
    "CONNECTOR_TYPE": "CCS1",
    "RATED_POWER_KW": 150.00,
    "TERMINAL_MODEL": "PT-9",
    "FAULT_CODE": "OCPP-GEN-01",
    "FAULT_CLASS": "MAJOR",
    "TECHNICIAN_CERTIFICATION_CLASS": "DCFC_BASIC",
    "PART_CLASS": "DISPENSER",
    "LEAD_TIME_DAYS": 3,
    "COMPLAINT_TYPE": "SESSION_FAILED",
}


def create_host_site_payload(site_code: str = "HS-1", **overrides) -> dict:
    """Required: site_code, host_org_name, committed_service_capacity_kw."""
    payload: Dict[str, Any] = {
        "site_code": site_code,
        "host_org_name": DEFAULTS["HOST_ORG_NAME"],
        "committed_service_capacity_kw": DEFAULTS["COMMITTED_CAPACITY_KW"],
    }
    payload.update(overrides)
    return payload


def commissionable_host_site_payload(site_code: str = "HS-1", **overrides) -> dict:
    """A host site whose agreement, power upgrade and parking gates all pass."""
    payload = create_host_site_payload(
        site_code,
        agreement_status="EXECUTED",
        power_upgrade_status="ENERGIZED",
        parking_enforcement_mode="TOWING_ENFORCED",
    )
    payload.update(overrides)
    return payload


def create_station_payload(host_site_id: str, station_code: str = "ST-1", **overrides) -> dict:
    """Required: host_site_id, station_code, power_class, declared_port_count."""
    payload: Dict[str, Any] = {
        "host_site_id": host_site_id,
        "station_code": station_code,
        "power_class": DEFAULTS["POWER_CLASS"],
        "declared_port_count": DEFAULTS["DECLARED_PORT_COUNT"],
        "corridor_designated": False,
    }
    payload.update(overrides)
    return payload


def create_charging_port_payload(
    station_id: str, dispenser_serial: str = "DS-1", **overrides
) -> dict:
    """Required: station_id, connector_type, rated_power_kw, dispenser_serial,
    terminal_model.  The four interoperability attributes are optional."""
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "connector_type": DEFAULTS["CONNECTOR_TYPE"],
        "rated_power_kw": DEFAULTS["RATED_POWER_KW"],
        "dispenser_serial": dispenser_serial,
        "terminal_model": DEFAULTS["TERMINAL_MODEL"],
    }
    payload.update(overrides)
    return payload


def fully_interoperable_port_payload(
    station_id: str, dispenser_serial: str = "DS-1", **overrides
) -> dict:
    """A dispenser with all three flags true and a roaming-compliant version."""
    payload = create_charging_port_payload(
        station_id,
        dispenser_serial,
        contactless_enabled=True,
        plug_and_charge_enabled=True,
        price_display_verified=True,
        roaming_ocpi_version="V2_2_1",
    )
    payload.update(overrides)
    return payload


def create_outage_event_payload(
    port_id: str, detected_at: str, fault_class: str = None, **overrides
) -> dict:
    """Required: port_id, fault_code, fault_class, detected_at."""
    payload: Dict[str, Any] = {
        "port_id": port_id,
        "fault_code": DEFAULTS["FAULT_CODE"],
        "fault_class": fault_class or DEFAULTS["FAULT_CLASS"],
        "detected_at": detected_at,
    }
    payload.update(overrides)
    return payload


def classify_outage_payload(fault_class: str, **overrides) -> dict:
    payload: Dict[str, Any] = {"fault_class": fault_class}
    payload.update(overrides)
    return payload


def exclusion_action_payload(action: str, **overrides) -> dict:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def resolution_review_payload(outcome: str, **overrides) -> dict:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_maintenance_dispatch_payload(
    outage_event_id: str,
    port_id: str,
    technician_user_id: str,
    window_start_at: str,
    window_end_at: str,
    **overrides,
) -> dict:
    """Required: outage_event_id, port_id, technician_user_id,
    technician_certification_class, window_start_at, window_end_at."""
    payload: Dict[str, Any] = {
        "outage_event_id": outage_event_id,
        "port_id": port_id,
        "technician_user_id": technician_user_id,
        "technician_certification_class": DEFAULTS["TECHNICIAN_CERTIFICATION_CLASS"],
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


def create_spare_part_payload(part_number: str = "SP-1", **overrides) -> dict:
    """Required: part_number, part_class, lead_time_days."""
    payload: Dict[str, Any] = {
        "part_number": part_number,
        "part_class": DEFAULTS["PART_CLASS"],
        "lead_time_days": DEFAULTS["LEAD_TIME_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_part_reservation_payload(
    dispatch_id: str, spare_part_id: str, qty: int, expected_spare_part_version: int, **overrides
) -> dict:
    """Required: dispatch_id, spare_part_id, qty, expected_spare_part_version."""
    payload: Dict[str, Any] = {
        "dispatch_id": dispatch_id,
        "spare_part_id": spare_part_id,
        "qty": qty,
        "expected_spare_part_version": expected_spare_part_version,
    }
    payload.update(overrides)
    return payload


def create_uptime_report_payload(
    station_id: str, period_start: str, period_end: str, **overrides
) -> dict:
    """Required: station_id, period_start, period_end."""
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def claim_line_item(port_id: str, amount_cents: int, category: str = "OANDM") -> dict:
    return {"port_id": port_id, "category": category, "amount_cents": amount_cents}


def create_reimbursement_claim_payload(
    uptime_report_id: str,
    line_items: List[dict],
    expected_uptime_report_version: int,
    **overrides,
) -> dict:
    """Required: uptime_report_id, line_items, expected_uptime_report_version."""
    payload: Dict[str, Any] = {
        "uptime_report_id": uptime_report_id,
        "line_items": line_items,
        "expected_uptime_report_version": expected_uptime_report_version,
    }
    payload.update(overrides)
    return payload


def create_customer_complaint_payload(
    station_id: str,
    port_id: str,
    session_started_at: str,
    session_ended_at: str,
    session_energy_kwh: float,
    session_price_per_kwh_cents: int,
    session_charged_cents: int,
    **overrides,
) -> dict:
    """Required: station_id, port_id, complaint_type, session_started_at,
    session_ended_at, session_energy_kwh, session_price_per_kwh_cents,
    session_charged_cents.  session_idle_fee_cents is optional."""
    payload: Dict[str, Any] = {
        "station_id": station_id,
        "port_id": port_id,
        "complaint_type": DEFAULTS["COMPLAINT_TYPE"],
        "session_started_at": session_started_at,
        "session_ended_at": session_ended_at,
        "session_energy_kwh": session_energy_kwh,
        "session_price_per_kwh_cents": session_price_per_kwh_cents,
        "session_charged_cents": session_charged_cents,
    }
    payload.update(overrides)
    return payload


def triage_payload(disposition: str, linked_outage_event_id: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"disposition": disposition}
    if linked_outage_event_id is not None:
        payload["linked_outage_event_id"] = linked_outage_event_id
    return payload
