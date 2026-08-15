"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_station_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "station_name": f"Station {n}",
        "station_code": f"ST-{n:05d}",
        "access_mode": TEST_DEFAULTS["ACCESS_MODE"],
        "backup_capacity_gge": TEST_DEFAULTS["BACKUP_CAPACITY_GGE"],
    }
    defaults.update(overrides)
    return defaults


def create_compressor_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "compressor_code": f"CMP-{_next()}",
        "capacity_scf_per_minute": TEST_DEFAULTS["CAPACITY_SCF_PER_MINUTE"],
    }
    defaults.update(overrides)
    return defaults


def create_dispenser_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "dispenser_code": f"DSP-{_next()}",
        "fuel_type": TEST_DEFAULTS["FUEL_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_calibration_record_payload(dispenser_id: str, **overrides) -> dict:
    defaults = {
        "dispenser_id": dispenser_id,
        "measured_error_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_policy_payload(station_id: str, expected_station_version: int, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "access_scope": "PRIVATE",
        "fuel_type": TEST_DEFAULTS["FUEL_TYPE"],
        "price_per_gge_cents": TEST_DEFAULTS["PRICE_PER_GGE_CENTS"],
        "effective_from": TEST_DEFAULTS["POLICY_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["POLICY_EFFECTIVE_TO"],
        "expected_station_version": expected_station_version,
    }
    defaults.update(overrides)
    return defaults


def create_fleet_account_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "account_name": f"Fleet Account {n}",
        "billing_email": f"billing{n}@fleet.example",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_fleet_card_payload(fleet_account_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "fleet_account_id": fleet_account_id,
        "card_number": f"FC-{n:05d}",
        "vehicle_plate": f"PLT{n:05d}",
        "daily_gge_limit": TEST_DEFAULTS["DAILY_GGE_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_contract_payload(fleet_account_id: str, station_id: str, **overrides) -> dict:
    defaults = {
        "fleet_account_id": fleet_account_id,
        "station_id": station_id,
        "committed_monthly_gge": TEST_DEFAULTS["CONTRACT_COMMITTED_GGE"],
        "contract_price_per_gge_cents": TEST_DEFAULTS["CONTRACT_PRICE_CENTS"],
        "shortfall_tier1_rate_cents": TEST_DEFAULTS["SHORTFALL_TIER1_RATE"],
        "shortfall_tier2_rate_cents": TEST_DEFAULTS["SHORTFALL_TIER2_RATE"],
        "start_month": "2026-07",
        "end_month": "2026-12",
    }
    defaults.update(overrides)
    return defaults


def authorize_session_payload(
    fleet_card_id: str, dispenser_id: str, client_ref: str,
    estimated_gge: float, expected_fleet_account_version: int, **overrides,
) -> dict:
    defaults = {
        "fleet_card_id": fleet_card_id,
        "dispenser_id": dispenser_id,
        "client_ref": client_ref,
        "estimated_gge": estimated_gge,
        "expected_fleet_account_version": expected_fleet_account_version,
    }
    defaults.update(overrides)
    return defaults


def authorize_public_session_payload(
    dispenser_id: str, client_ref: str, estimated_gge: float, **overrides,
) -> dict:
    defaults = {
        "dispenser_id": dispenser_id,
        "client_ref": client_ref,
        "estimated_gge": estimated_gge,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "starts_at": "2026-08-20T10:00:00Z",
        "ends_at": "2026-08-20T12:00:00Z",
        "window_type": "PREVENTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_backup_arrangement_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "partner_station_code": f"ST-PARTNER-{_next()}",
        "available_from": "2026-08-10T00:00:00Z",
        "available_until": "2026-08-20T00:00:00Z",
        "committed_gge": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_safety_inspection_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "inspection_type": "ODORIZATION_CHECK",
        "scheduled_for": "2026-08-20T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tax_credit_claim_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
