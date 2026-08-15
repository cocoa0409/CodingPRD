"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import TEST_DEFAULTS as D

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_account_payload(**overrides) -> dict:
    defaults = {"account_name": f"Test Account {_seq()}"}
    defaults.update(overrides)
    return defaults


def create_asset_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "asset_tag": f"CT-{_seq()}",
        "asset_type": "COOLING_TOWER",
        "recirculation_rate_gpm": D["RECIRCULATION_RATE_GPM"],
        "system_volume_gal": D["SYSTEM_VOLUME_GAL"],
        "metallurgy": "MILD_STEEL",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": f"P-{_seq()}",
        "active_pct": D["ACTIVE_PCT"],
        "container_size_gal": D["CONTAINER_SIZE_GAL"],
        "unit_price_cents_per_gal": D["UNIT_PRICE_CENTS_PER_GAL"],
        "contract_price_cents_per_gal": D["CONTRACT_PRICE_CENTS_PER_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_feed_station_payload(asset_id, product_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "product_id": product_id,
        "capacity_cap_ml_per_min": D["CAPACITY_CAP_ML_PER_MIN"],
    }
    defaults.update(overrides)
    return defaults


def create_program_design_payload(asset_id, **overrides) -> dict:
    defaults = {"asset_id": asset_id}
    defaults.update(overrides)
    return defaults


def design_draft_payload(**overrides) -> dict:
    """Full parameter set for the SURVEYED -> DRAFTED transition."""
    defaults = {
        "proposed_coc": D["PROPOSED_COC"],
        "inhibitor_target_ppm": D["INHIBITOR_TARGET_PPM"],
        "ph_min": D["PH_MIN"],
        "ph_max": D["PH_MAX"],
        "conductivity_max_umhos": D["CONDUCTIVITY_MAX_UMHOS"],
        "service_rate_cents_per_month": D["SERVICE_RATE_CENTS_PER_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_test_route_payload(account_id, **overrides) -> dict:
    defaults = {"account_id": account_id, "route_name": f"ROUTE-{_seq()}"}
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(asset_id, window_start, window_end, sequence_index, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "window_start": window_start,
        "window_end": window_end,
        "sequence_index": sequence_index,
    }
    defaults.update(overrides)
    return defaults


def water_test_result_payload(asset_id, **overrides) -> dict:
    """In-range field measurements for the default control band."""
    defaults = {
        "asset_id": asset_id,
        "ph": 8.0,
        "conductivity_umhos": 2000,
        "calcium_ppm": 300,
        "alkalinity_ppm": 150,
        "temperature_f": 90,
        "inhibitor_residual_ppm": 4,
    }
    defaults.update(overrides)
    return defaults


def out_of_range_result_payload(asset_id, **overrides) -> dict:
    """Out-of-range field measurements for the default control band (ph 9.8 > 9.5)."""
    defaults = {
        "asset_id": asset_id,
        "ph": 9.8,
        "conductivity_umhos": 2900,
        "calcium_ppm": 300,
        "alkalinity_ppm": 150,
        "temperature_f": 90,
        "inhibitor_residual_ppm": 0.5,
    }
    defaults.update(overrides)
    return defaults


def telemetry_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": "2026-08-01T00:00:00Z",
        "feed_pulses": 100,
        "ml_per_pulse": 2.0,
        "level_gal": 50,
    }
    defaults.update(overrides)
    return defaults


def create_rack_payload(asset_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "rack_code": f"RK-{_seq()}",
        "position_count": 4,
    }
    defaults.update(overrides)
    return defaults


def create_coupon_payload(position_index, installed_at, **overrides) -> dict:
    defaults = {
        "position_index": position_index,
        "alloy": "MILD_STEEL",
        "density_g_cm3": 7.87,
        "area_in2": 5.4,
        "pre_weight_g": 50.0,
        "installed_at": installed_at,
    }
    defaults.update(overrides)
    return defaults


def create_legionella_plan_payload(asset_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "plan_text": "Narrative control scheme",
        "validation_interval_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_blowdown_event_payload(occurred_at, blowdown_gal, makeup_gal, **overrides) -> dict:
    defaults = {
        "occurred_at": occurred_at,
        "blowdown_gal": blowdown_gal,
        "makeup_gal": makeup_gal,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_order_payload(account_id, station_id, quantity_gal, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "station_id": station_id,
        "quantity_gal": quantity_gal,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(account_id, period_start, period_end, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults
