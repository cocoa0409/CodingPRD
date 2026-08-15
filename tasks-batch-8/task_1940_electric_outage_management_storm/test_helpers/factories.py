"""Payload factories — one per resource, input fields only."""
import itertools
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS

_event_counter = itertools.count(1)
_feeder_counter = itertools.count(1)
_customer_counter = itertools.count(1)
_crew_counter = itertools.count(1)
_ma_counter = itertools.count(1)
_hotel_counter = itertools.count(1)
_stock_counter = itertools.count(1)


def unique_event_name(prefix: str = "Storm") -> str:
    return f"{prefix} {next(_event_counter)}"


def unique_feeder_code(prefix: str = "FDR") -> str:
    return f"{prefix}-{next(_feeder_counter)}"


def unique_account_ref(prefix: str = "ACCT") -> str:
    return f"{prefix}-{next(_customer_counter)}"


def unique_crew_code(prefix: str = "C") -> str:
    return f"{prefix}-{next(_crew_counter)}"


def unique_company_name(prefix: str = "PeerCo") -> str:
    return f"{prefix} {next(_ma_counter)}"


def unique_hotel_name(prefix: str = "Hotel") -> str:
    return f"{prefix} {next(_hotel_counter)}"


def unique_warehouse_code(prefix: str = "W") -> str:
    return f"{prefix}{next(_stock_counter)}"


def create_storm_event_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "event_name": unique_event_name(),
        "event_type": "HURRICANE",
    }
    payload.update(overrides)
    return payload


def create_feeder_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "feeder_code": unique_feeder_code(),
        "county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "service_customer_count": TEST_DEFAULTS["FEEDER_CUSTOMER_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_priority_customer_payload(feeder_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "account_ref": unique_account_ref(),
        "priority_class": "LIFE_SUPPORT",
        "feeder_id": feeder_id,
    }
    payload.update(overrides)
    return payload


def create_trouble_signal_payload(
    feeder_id: str,
    signal_type: str = "CUSTOMER_CALL",
    occurred_at: str = "2026-08-10T00:00:00Z",
    outage_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "signal_type": signal_type,
        "feeder_id": feeder_id,
        "occurred_at": occurred_at,
    }
    if outage_id is not None:
        payload["outage_id"] = outage_id
    payload.update(overrides)
    return payload


def create_outage_payload(
    storm_event_id: str, feeder_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "storm_event_id": storm_event_id,
        "feeder_id": feeder_id,
    }
    payload.update(overrides)
    return payload


def create_confirm_outage_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "customers_affected": 5,
        "cause_code": "EQUIPMENT",
    }
    payload.update(overrides)
    return payload


def create_etr_revision_payload(
    published_etr: str,
    revision_reason: str,
    expected_outage_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "published_etr": published_etr,
        "revision_reason": revision_reason,
        "expected_outage_version": expected_outage_version,
    }
    payload.update(overrides)
    return payload


def create_damage_assessment_payload(outage_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outage_id": outage_id,
        "damage_class": "MINOR",
        "estimated_repair_minutes": 30,
        "requires_switching": False,
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "crew_code": unique_crew_code(),
        "crew_type": "LINE",
        "home_base": TEST_DEFAULTS["HOME_BASE"],
        "hourly_rate_cents": TEST_DEFAULTS["CREW_HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_mutual_aid_crew_payload(
    storm_event_id: str,
    committed_window_start: str = "2026-08-10T00:00:00Z",
    committed_window_end: str = "2026-08-12T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "storm_event_id": storm_event_id,
        "company_name": unique_company_name(),
        "crew_type": "LINE",
        "roster_size": 2,
        "service_county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "daily_rate_cents": TEST_DEFAULTS["MA_DAILY_RATE_CENTS"],
        "per_diem_cents": TEST_DEFAULTS["MA_PER_DIEM_CENTS"],
        "committed_window_start": committed_window_start,
        "committed_window_end": committed_window_end,
    }
    payload.update(overrides)
    return payload


def create_lodging_block_payload(
    storm_event_id: str,
    window_start: str = "2026-08-10T00:00:00Z",
    window_end: str = "2026-08-12T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "storm_event_id": storm_event_id,
        "hotel_name": unique_hotel_name(),
        "county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "room_count": 4,
        "nightly_rate_cents": TEST_DEFAULTS["LODGING_NIGHTLY_RATE_CENTS"],
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(
    outage_id: str,
    work_type: str = "REPAIR",
    required_crew_type: str = "LINE",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outage_id": outage_id,
        "work_type": work_type,
        "required_crew_type": required_crew_type,
        "requires_switching_order": False,
    }
    payload.update(overrides)
    return payload


def create_switching_order_payload(
    work_order_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "work_order_id": work_order_id,
        "switching_steps": ["Open breaker 7"],
    }
    payload.update(overrides)
    return payload


def create_material_stock_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "warehouse_code": unique_warehouse_code(),
        "material_sku": "SKU-1",
        "quantity_on_hand": TEST_DEFAULTS["STOCK_ON_HAND"],
        "unit_cost_cents": TEST_DEFAULTS["STOCK_UNIT_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_material_requisition_payload(
    work_order_id: str, material_stock_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "work_order_id": work_order_id,
        "material_stock_id": material_stock_id,
        "quantity": 10,
    }
    payload.update(overrides)
    return payload


def create_fema_claim_payload(
    storm_event_id: str, county_code: str, threshold_cents: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "storm_event_id": storm_event_id,
        "county_code": county_code,
        "threshold_cents": threshold_cents,
    }
    payload.update(overrides)
    return payload
