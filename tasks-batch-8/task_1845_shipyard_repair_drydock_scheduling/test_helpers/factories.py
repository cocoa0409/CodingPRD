"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import (
    DEFAULT_CONTRACT_DELIVERY_DATE,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    TEST_DEFAULTS,
)

_imo_counter = itertools.count(9000001)


def create_dock_payload(**overrides) -> dict:
    defaults = {
        "name": "Drydock 1",
        "max_length_m": TEST_DEFAULTS["DOCK_MAX_LENGTH_M"],
        "max_beam_m": TEST_DEFAULTS["DOCK_MAX_BEAM_M"],
        "max_depth_m": TEST_DEFAULTS["DOCK_MAX_DEPTH_M"],
        "daily_rate_cents": TEST_DEFAULTS["DOCK_DAILY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "name": "MV Gulf Star",
        "imo_number": f"IMO{next(_imo_counter)}",
        "length_m": TEST_DEFAULTS["VESSEL_LENGTH_M"],
        "beam_m": TEST_DEFAULTS["VESSEL_BEAM_M"],
        "draft_m": TEST_DEFAULTS["VESSEL_DRAFT_M"],
        "owner_user_id": TEST_DEFAULTS["VESSEL_OWNER_USER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_payload(**overrides) -> dict:
    defaults = {
        "name": "Gulf Steel LLC",
        "trade_codes": ["HULL_STEEL", "PIPING", "COATINGS", "MACHINERY"],
        "day_rate_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_repair_project_payload(vessel_id: str, dock_id: str, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "dock_id": dock_id,
        "contract_delivery_date": DEFAULT_CONTRACT_DELIVERY_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_work_item_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "description": "Base spec line",
        "trade_code": "PIPING",
        "pricing_mode": "LUMP_SUM",
        "duration_days": 1,
        "quantity": 1,
        "unit_price_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_dock_reservation_payload(
    project_id: str, expected_project_version: int, **overrides
) -> dict:
    defaults = {
        "project_id": project_id,
        "start_utc": DEFAULT_WINDOW_START,
        "end_utc": DEFAULT_WINDOW_END,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(
    project_id: str, expected_project_version: int, **overrides
) -> dict:
    defaults = {
        "project_id": project_id,
        "expected_project_version": expected_project_version,
        "description": "Growth work discovered on opening",
        "trade_code": "HULL_STEEL",
        "pricing_mode": "LUMP_SUM",
        "duration_days": 1,
        "schedule_delta_days": 0,
        "quantity": 1,
        "unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "survey_type": "CLASS_RENEWAL",
        "scheduled_start_utc": "2026-08-02T09:00:00Z",
        "scheduled_end_utc": "2026-08-02T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "permit_type": "HOT_WORK",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_to": "2026-08-15T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(
    project_id: str, work_item_id: str, **overrides
) -> dict:
    defaults = {
        "project_id": project_id,
        "work_item_id": work_item_id,
        "description": "Defect found post-delivery",
    }
    defaults.update(overrides)
    return defaults
