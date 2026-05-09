"""
Payload factories — one per request body shape the PRD declares (§3 / §4).

Each factory accepts ``**overrides`` so a test can deviate from the default
shape without re-declaring the entire body. Default values are chosen to
satisfy PRD validation gates; tests that want to exercise a gate failure
override the relevant field explicitly.
"""

import uuid
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Pricing plan
# ---------------------------------------------------------------------------


def create_pricing_plan_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "city_code": "BJ",
        "hourly_rate": 3.00,
        "daily_cap": 30.00,
        "free_minutes": 5,
        "cross_city_surcharge": 10.00,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Location partner
# ---------------------------------------------------------------------------


def create_location_partner_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "partner_code": f"P-{uuid.uuid4().hex[:8].upper()}",
        "name": "Test Partner",
        "revenue_share_pct": 0.5,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Cabinet
# ---------------------------------------------------------------------------


def create_cabinet_payload(
    location_partner_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "cabinet_code": f"C-{uuid.uuid4().hex[:8].upper()}",
        "city_code": "BJ",
        "location_partner_id": location_partner_id,
        "model": "SLOT_8",
        "firmware_version": "v1.0.0",
    }
    defaults.update(overrides)
    return defaults


def heartbeat_payload(timestamp: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"timestamp": timestamp}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


def create_device_payload(
    cabinet_id: str, slot_index: int, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "device_code": f"D-{uuid.uuid4().hex[:8].upper()}",
        "model": "PB_5K",
        "battery_level": 80,
        "current_cabinet_id": cabinet_id,
        "current_slot_index": slot_index,
    }
    defaults.update(overrides)
    return defaults


def report_fault_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"issue_code": "PHYSICAL_DAMAGE"}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


def create_user_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"phone": f"1{uuid.uuid4().int % 10**10:010d}"}
    defaults.update(overrides)
    return defaults


def amount_payload(amount: float = 100.00) -> Dict[str, Any]:
    return {"amount": amount}


# ---------------------------------------------------------------------------
# Rental
# ---------------------------------------------------------------------------


def create_rental_payload(cabinet_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"cabinet_id": cabinet_id}
    defaults.update(overrides)
    return defaults


def return_payload(return_cabinet_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"return_cabinet_id": return_cabinet_id}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Operator task / repair ticket
# ---------------------------------------------------------------------------


def auto_assign_payload(city_code: str = "BJ") -> Dict[str, Any]:
    return {"city_code": city_code}


def resolve_payload(cancel: bool = False) -> Dict[str, Any]:
    return {"cancel": cancel}


def complete_payload(cancel: bool = False) -> Dict[str, Any]:
    return {"cancel": cancel}


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def create_settlement_payload(
    location_partner_id: str,
    period_start: str,
    period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "location_partner_id": location_partner_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Maintenance window
# ---------------------------------------------------------------------------


def create_maintenance_window_payload(
    cabinet_id: str, window_start: str, window_end: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "cabinet_id": cabinet_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Payment event
# ---------------------------------------------------------------------------


def create_payment_event_payload(
    rental_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "idempotency_key": f"idem-{uuid.uuid4().hex}",
        "event_type": "PAYMENT_CONFIRMED",
        "rental_id": rental_id,
        "amount": 3.00,
        "occurred_at": "2026-01-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Clock / sweep / events
# ---------------------------------------------------------------------------


def clock_advance_to(iso_timestamp: str) -> Dict[str, Any]:
    return {"to": iso_timestamp}


def clock_advance_seconds(seconds: int) -> Dict[str, Any]:
    return {"seconds": seconds}


def sweep_payload(sweep_type: str) -> Dict[str, Any]:
    return {"sweep_type": sweep_type}


def emit_event_payload(event_type: str, payload: Any) -> Dict[str, Any]:
    return {"event_type": event_type, "payload": payload}
