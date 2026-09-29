"""Payload factories — one per resource, input fields only."""
from .constants import (
    PROFILE_CONCERT,
    PROFILE_COURT,
    PROFILE_FAMILY,
    PROFILE_ICE,
    VENUE_DEFAULTS,
)


def create_venue_payload(**overrides) -> dict:
    payload = dict(VENUE_DEFAULTS)
    payload.update(overrides)
    return payload


def create_configuration_profile_payload(**overrides) -> dict:
    payload = dict(PROFILE_ICE)
    payload.update(overrides)
    return payload


def ice_profile_payload(**overrides) -> dict:
    payload = dict(PROFILE_ICE)
    payload.update(overrides)
    return payload


def concert_profile_payload(**overrides) -> dict:
    payload = dict(PROFILE_CONCERT)
    payload.update(overrides)
    return payload


def court_profile_payload(**overrides) -> dict:
    payload = dict(PROFILE_COURT)
    payload.update(overrides)
    return payload


def family_profile_payload(**overrides) -> dict:
    payload = dict(PROFILE_FAMILY)
    payload.update(overrides)
    return payload


def create_anchor_tenant_payload(**overrides) -> dict:
    payload = {
        "name": "Lakeside Hockey Club",
        "hold_priority_tier": "TIER_2",
        "guaranteed_holds_per_season": 5,
    }
    payload.update(overrides)
    return payload


def create_event_booking_payload(venue_id: str, config_profile_id: str, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "config_profile_id": config_profile_id,
        "title": "Hockey Sep 10",
        "promoter_name": "Lakeside Hockey Club",
        "event_start_utc": "2026-09-10T00:00:00Z",
        "event_end_utc": "2026-09-10T03:00:00Z",
        "expected_attendance": 15_000,
        "rigging_load_kg": 3_000,
    }
    payload.update(overrides)
    if payload.get("tenant_id") is not None:
        payload.pop("promoter_name", None)
    return payload


def create_equipment_asset_payload(**overrides) -> dict:
    payload = {
        "asset_class": "FLOOR_PANEL_SET",
        "units_total": 10,
        "service_interval_cycles": 12,
    }
    payload.update(overrides)
    return payload


def create_ice_sheet_payload(config_profile_id: str, **overrides) -> dict:
    payload = {
        "config_profile_id": config_profile_id,
        "dehumidification_lph_applied": 120,
        "sheet_thickness_mm": 32,
    }
    payload.update(overrides)
    return payload


def create_dock_slot_reservation_payload(**overrides) -> dict:
    payload = {
        "dock_number": 1,
        "purpose": "LOAD_IN",
        "window_start_utc": "2026-09-09T10:00:00Z",
        "window_end_utc": "2026-09-09T14:00:00Z",
        "truck_count": 6,
    }
    payload.update(overrides)
    return payload


def create_labor_call_payload(**overrides) -> dict:
    payload = {
        "craft": "STAGEHAND",
        "headcount": 10,
        "call_start_utc": "2026-09-10T04:00:00Z",
        "call_end_utc": "2026-09-10T12:00:00Z",
        "guaranteed_hours": 4,
    }
    payload.update(overrides)
    return payload


def create_changeover_order_payload(
    from_booking_id: str, to_booking_id: str, expected_venue_version: int, **overrides
) -> dict:
    payload = {
        "from_booking_id": from_booking_id,
        "to_booking_id": to_booking_id,
        "crew_headcount": 40,
        "expected_venue_version": expected_venue_version,
    }
    payload.update(overrides)
    return payload


def create_hold_challenge_payload(
    booking_id: str, challenger_tenant_id: str, challenger_booking_id: str, **overrides
) -> dict:
    payload = {
        "booking_id": booking_id,
        "challenger_tenant_id": challenger_tenant_id,
        "challenger_booking_id": challenger_booking_id,
    }
    payload.update(overrides)
    return payload


def create_equipment_issue_payload(asset_id: str, changeover_order_id: str, **overrides) -> dict:
    payload = {
        "asset_id": asset_id,
        "changeover_order_id": changeover_order_id,
        "units_issued": 3,
    }
    payload.update(overrides)
    return payload
