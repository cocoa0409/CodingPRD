"""Request-payload factories.

Each factory returns only the fields a client supplies; server-derived state
(ids, timestamps, versions, statuses, counters, computed money) is never
included. Every factory accepts ``**overrides`` so a test can vary one field.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    BARCODE_ANCHOR_AT,
    DOORS_OPEN_AT,
    EVENT_START_AT,
    TRANSFER_WINDOW_CLOSES_AT,
)
from .types import (
    DistributionType,
    EntitlementLevel,
    Marketplace,
    PriceCapRegime,
    ScanDirection,
    SessionMode,
    TicketType,
)


def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    """Body for moving the logical clock."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def event_payload(**overrides: Any) -> Dict[str, Any]:
    """A complete event-creation body with both optional policy fields set."""
    payload: Dict[str, Any] = {
        "name": "Aurora Night",
        "venue_name": "Northgate Arena",
        "fire_code_capacity": 200,
        "barcode_anchor_at": BARCODE_ANCHOR_AT,
        "doors_open_at": DOORS_OPEN_AT,
        "event_start_at": EVENT_START_AT,
        "transfer_window_closes_at": TRANSFER_WINDOW_CLOSES_AT,
        "price_cap_regime": PriceCapRegime.VENUE_POLICY,
        "transfer_limit_per_ticket": 2,
    }
    payload.update(overrides)
    return payload


def minimal_event_payload(**overrides: Any) -> Dict[str, Any]:
    """Only the required event fields, leaving both policy fields to default."""
    payload: Dict[str, Any] = {
        "name": "Aurora Night",
        "venue_name": "Northgate Arena",
        "fire_code_capacity": 200,
        "barcode_anchor_at": BARCODE_ANCHOR_AT,
        "doors_open_at": DOORS_OPEN_AT,
        "event_start_at": EVENT_START_AT,
        "transfer_window_closes_at": TRANSFER_WINDOW_CLOSES_AT,
    }
    payload.update(overrides)
    return payload


def access_zone_payload(**overrides: Any) -> Dict[str, Any]:
    """A general-admission zone body with both optional fields set."""
    payload: Dict[str, Any] = {
        "zone_code": "GA1",
        "required_entitlement_level": EntitlementLevel.GA,
        "fire_code_capacity": 200,
        "face_value_reference_cents": 8750,
        "credential_capacity": 4,
        "comp_discount_pct": 0.85,
    }
    payload.update(overrides)
    return payload


def minimal_access_zone_payload(**overrides: Any) -> Dict[str, Any]:
    """Only the required zone fields, leaving both optional fields to default."""
    payload: Dict[str, Any] = {
        "zone_code": "GA1",
        "required_entitlement_level": EntitlementLevel.GA,
        "fire_code_capacity": 200,
        "face_value_reference_cents": 8750,
    }
    payload.update(overrides)
    return payload


def gate_payload(access_zone_id: str, **overrides: Any) -> Dict[str, Any]:
    """A two-lane gate body serving ``access_zone_id``."""
    payload: Dict[str, Any] = {
        "gate_code": "G1",
        "access_zone_id": access_zone_id,
        "throughput_per_minute": 20,
        "lanes_open": 2,
    }
    payload.update(overrides)
    return payload


def patron_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"email": "ada@example.com", "display_name": "Ada Lovelace"}
    payload.update(overrides)
    return payload


def verify_identity_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"document_reference": "DL-ADA-1"}
    payload.update(overrides)
    return payload


def ticket_payload(
    event_id: str, access_zone_id: str, holder_patron_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A paid direct-issuance body."""
    payload: Dict[str, Any] = {
        "event_id": event_id,
        "access_zone_id": access_zone_id,
        "holder_patron_id": holder_patron_id,
        "ticket_type": TicketType.PAID,
        "face_value_cents": 12000,
    }
    payload.update(overrides)
    return payload


def device_binding_payload(device_fingerprint: str = "DEV-A", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"device_fingerprint": device_fingerprint}
    payload.update(overrides)
    return payload


def void_payload(refund_to_holder: bool = False, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason": "Compromised entitlement",
        "refund_to_holder": refund_to_holder,
    }
    payload.update(overrides)
    return payload


def transfer_request_payload(ticket_id: str, to_patron_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ticket_id": ticket_id, "to_patron_id": to_patron_id}
    payload.update(overrides)
    return payload


def resale_listing_payload(
    ticket_id: str, ask_price_cents: int, expected_ticket_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "ask_price_cents": ask_price_cents,
        "marketplace": Marketplace.VERIFIED_PRIMARY,
        "expected_ticket_version": expected_ticket_version,
    }
    payload.update(overrides)
    return payload


def credential_request_payload(
    event_id: str,
    access_zone_id: str,
    recipient_patron_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A credential distribution body with a two-hour validity window."""
    payload: Dict[str, Any] = {
        "event_id": event_id,
        "access_zone_id": access_zone_id,
        "recipient_patron_id": recipient_patron_id,
        "distribution_type": DistributionType.CREDENTIAL,
        "quantity": 2,
        "valid_from": "2026-09-12T18:00:00Z",
        "valid_until": "2026-09-12T20:00:00Z",
        "justification": "Stage crew credentials",
    }
    payload.update(overrides)
    return payload


def note_payload(note: str = "Please revise the quantity", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"note": note}
    payload.update(overrides)
    return payload


def scan_session_payload(
    gate_id: str, expected_gate_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "gate_id": gate_id,
        "operator_device_id": "SCN-1",
        "mode": SessionMode.ONLINE,
        "expected_gate_version": expected_gate_version,
    }
    payload.update(overrides)
    return payload


def scan_event_payload(
    presented_barcode: str,
    device_fingerprint: str,
    dedupe_key: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A live entry-scan body."""
    payload: Dict[str, Any] = {
        "presented_barcode": presented_barcode,
        "device_fingerprint": device_fingerprint,
        "direction": ScanDirection.IN,
        "dedupe_key": dedupe_key,
    }
    payload.update(overrides)
    return payload


def offline_scan_item(
    presented_barcode: str,
    device_fingerprint: str,
    dedupe_key: str,
    scanned_at: str,
    direction: str = ScanDirection.IN,
) -> Dict[str, Any]:
    """One item of an offline cache; ``scanned_at`` is mandatory here."""
    return {
        "presented_barcode": presented_barcode,
        "device_fingerprint": device_fingerprint,
        "direction": direction,
        "dedupe_key": dedupe_key,
        "scanned_at": scanned_at,
    }


def offline_batch_payload(scans: List[Dict[str, Any]], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"scans": scans}
    payload.update(overrides)
    return payload


def resolution_payload(
    resolution_note: str = "Reviewed gate footage", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution_note": resolution_note}
    payload.update(overrides)
    return payload


def reconciliation_report_payload(
    reported_attendance: int, expected_event_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reported_attendance": reported_attendance,
        "expected_event_version": expected_event_version,
    }
    payload.update(overrides)
    return payload


def finalize_payload(override_reason: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if override_reason is not None:
        payload["override_reason"] = override_reason
    payload.update(overrides)
    return payload


def reopen_payload(reason: str = "Operations recounted the doors", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def advance_status_payload(target_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_status": target_status}
    payload.update(overrides)
    return payload
