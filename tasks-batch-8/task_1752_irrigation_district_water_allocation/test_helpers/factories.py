"""Payload factories — one per entity, input fields only (PRD §4)."""

from .constants import SEASON_DEFAULTS, TEST_DEFAULTS


def create_water_account_payload(**overrides) -> dict:
    defaults = {
        "holder_name": "Test Holder",
        "parcel_number": "APN-000",
        "irrigated_acres": TEST_DEFAULTS["IRRIGATED_ACRES"],
        "water_right_priority_date": TEST_DEFAULTS["SENIOR_PRIORITY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(**overrides) -> dict:
    defaults = dict(SEASON_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_season_allocation_payload(water_account_id: str, season_id: str,
                                     **overrides) -> dict:
    defaults = {
        "water_account_id": water_account_id,
        "season_id": season_id,
    }
    defaults.update(overrides)
    return defaults


def create_turnout_order_payload(water_account_id: str, season_allocation_id: str,
                                 canal_reach_id: str,
                                 expected_water_account_version: int,
                                 **overrides) -> dict:
    defaults = {
        "water_account_id": water_account_id,
        "season_allocation_id": season_allocation_id,
        "canal_reach_id": canal_reach_id,
        "requested_cfs": 5.0,
        "requested_start_at": TEST_DEFAULTS["ORDER_START"],
        "requested_end_at": TEST_DEFAULTS["ORDER_END"],
        "expected_water_account_version": expected_water_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_canal_reach_payload(**overrides) -> dict:
    defaults = {
        "name": "Reach-1",
        "max_capacity_cfs": TEST_DEFAULTS["REACH_CAPACITY_CFS"],
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(canal_reach_id: str, **overrides) -> dict:
    defaults = {
        "canal_reach_id": canal_reach_id,
        "start_at": "2026-08-10T08:00:00Z",
        "end_at": "2026-08-10T14:00:00Z",
        "reason": "scheduled maintenance",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(from_account_id: str, to_account_id: str,
                                    season_id: str, quantity_af: float,
                                    expected_source_allocation_version: int,
                                    **overrides) -> dict:
    defaults = {
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "season_id": season_id,
        "quantity_af": quantity_af,
        "expected_source_allocation_version": expected_source_allocation_version,
    }
    defaults.update(overrides)
    return defaults


def create_drought_declaration_payload(season_id: str, stage: str = "STAGE_1",
                                       **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "stage": stage,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_invoice_payload(water_account_id: str, season_id: str,
                                      **overrides) -> dict:
    defaults = {
        "water_account_id": water_account_id,
        "season_id": season_id,
    }
    defaults.update(overrides)
    return defaults
