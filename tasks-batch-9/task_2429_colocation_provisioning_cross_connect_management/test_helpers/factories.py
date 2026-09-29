"""Request-body factories — one per creation endpoint, carrying only the fields the
PRD declares as client input. Every factory accepts `**overrides` so a test can vary
exactly the field under examination and leave the rest at a valid default.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CABINET_DEFAULTS,
    CIRCUIT_DEFAULTS,
    CONTRACT_DEFAULTS,
    ROW_DEFAULTS,
)

_counter = itertools.count(1)


def unique_suffix() -> int:
    """A per-process counter for codes the PRD requires to be unique."""
    return next(_counter)


def create_customer_payload(**overrides) -> Dict[str, Any]:
    n = unique_suffix()
    payload = {"legal_name": f"Meridian Colo {n}", "account_code": f"MC{n:04d}"}
    payload.update(overrides)
    return payload


def create_contact_payload(customer_id: str, **overrides) -> Dict[str, Any]:
    n = unique_suffix()
    payload = {
        "customer_id": customer_id,
        "full_name": f"Contact {n}",
        "authorization_scopes": ["REMOTE_HANDS", "SITE_ACCESS"],
        "access_level": "UNESCORTED",
    }
    payload.update(overrides)
    return payload


def create_contract_payload(customer_id: str, **overrides) -> Dict[str, Any]:
    n = unique_suffix()
    payload = {"customer_id": customer_id, "contract_number": f"C-{9000 + n}"}
    payload.update(CONTRACT_DEFAULTS)
    payload.update(overrides)
    return payload


def create_row_payload(**overrides) -> Dict[str, Any]:
    n = unique_suffix()
    payload = {"hall_code": f"H{n}", "row_code": "R1"}
    payload.update(ROW_DEFAULTS)
    payload.update(overrides)
    return payload


def update_row_payload(**fields) -> Dict[str, Any]:
    """The row PATCH body carries only the limits a caller wants to move."""
    return dict(fields)


def create_cabinet_payload(row_id: str, **overrides) -> Dict[str, Any]:
    n = unique_suffix()
    payload = {"row_id": row_id, "cabinet_code": f"C{n:03d}"}
    payload.update(CABINET_DEFAULTS)
    payload.update(overrides)
    return payload


def create_power_circuit_payload(cabinet_id: str, **overrides) -> Dict[str, Any]:
    n = unique_suffix()
    payload = {"cabinet_id": cabinet_id, "circuit_code": f"A-{n}"}
    payload.update(CIRCUIT_DEFAULTS)
    payload.update(overrides)
    return payload


def create_patch_panel_port_payload(row_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "row_id": row_id,
        "panel_code": "PP-A",
        "port_number": 1,
        "media_type": "SMF",
    }
    payload.update(overrides)
    return payload


def create_cross_connect_order_payload(
    contract_id: str,
    requested_by_contact_id: str,
    a_end_cabinet_id: str,
    z_end_cabinet_id: str,
    expected_contract_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "requested_by_contact_id": requested_by_contact_id,
        "a_end_cabinet_id": a_end_cabinet_id,
        "z_end_cabinet_id": z_end_cabinet_id,
        "cable_type": "SMF",
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def propose_route_payload(
    a_end_port_id: str,
    z_end_port_id: str,
    path_hops: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "a_end_port_id": a_end_port_id,
        "z_end_port_id": z_end_port_id,
        "path_hops": list(path_hops) if path_hops is not None else ["PP-A", "PP-Z"],
    }
    payload.update(overrides)
    return payload


def create_remote_hands_ticket_payload(
    contract_id: str,
    requested_by_contact_id: str,
    target_cabinet_id: str,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "requested_by_contact_id": requested_by_contact_id,
        "target_cabinet_id": target_cabinet_id,
        "severity": "STANDARD",
        "description": "Reseat a transceiver",
    }
    payload.update(overrides)
    return payload


def work_segment(started_at: str, ended_at: str) -> Dict[str, str]:
    return {"started_at": started_at, "ended_at": ended_at}


def complete_ticket_payload(*segments: Dict[str, str]) -> Dict[str, Any]:
    return {"work_segments": list(segments)}


def create_access_visit_payload(
    contract_id: str,
    contact_id: str,
    cabinet_id: str,
    window_start: str,
    window_end: str,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "contact_id": contact_id,
        "cabinet_id": cabinet_id,
        "purpose": "MAINTENANCE",
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_decommission_order_payload(
    contract_id: str, cabinet_id: str, requested_by_contact_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "cabinet_id": cabinet_id,
        "requested_by_contact_id": requested_by_contact_id,
    }
    payload.update(overrides)
    return payload


def meter_reading_payload(
    interval_start: str, interval_end: str, kwh: float, peak_kw: float
) -> Dict[str, Any]:
    return {
        "interval_start": interval_start,
        "interval_end": interval_end,
        "kwh": kwh,
        "peak_kw": peak_kw,
    }


def billing_close_payload(period_start: str, period_end: str) -> Dict[str, Any]:
    return {"period_start": period_start, "period_end": period_end}


def invoice_adjustment_payload(invoice_line_id: str, reason: str = "Billed in error") -> Dict[str, Any]:
    return {"invoice_line_id": invoice_line_id, "reason": reason}


def state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload = {"to_state": to_state}
    payload.update(overrides)
    return payload
