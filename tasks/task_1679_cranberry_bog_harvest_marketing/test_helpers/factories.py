"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS as D


def create_season_payload(**overrides) -> dict:
    defaults = {
        "year": D["YEAR"],
        "harvest_window_start": D["HARVEST_WINDOW_START"],
        "harvest_window_end": D["HARVEST_WINDOW_END"],
        "baseline_barrels_per_acre": D["BASELINE_BARRELS_PER_ACRE"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {"member_code": "M100", "full_name": "Alice Grower"}
    defaults.update(overrides)
    return defaults


def create_bog_payload(**overrides) -> dict:
    defaults = {
        "name": "North Bog",
        "acres": 10,
        "variety": "STEVENS",
        "sprinkler_demand_gpm": 500,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(bog_id, season_id, **overrides) -> dict:
    defaults = {
        "bog_id": bog_id,
        "season_id": season_id,
        "estimated_barrels": 2300,
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    defaults = {"name": "Station A", "daily_capacity_barrels": D["STATION_CAPACITY"]}
    defaults.update(overrides)
    return defaults


def create_ticket_payload(bog_id, season_id, **overrides) -> dict:
    defaults = {
        "bog_id": bog_id,
        "season_id": season_id,
        "method": "DRY",
        "window_start": "2026-10-01T00:00:00Z",
        "window_end": "2026-10-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_frost_event_payload(bog_id, season_id, **overrides) -> dict:
    defaults = {
        "bog_id": bog_id,
        "season_id": season_id,
        "window_start": "2026-10-20T00:00:00Z",
        "window_end": "2026-10-20T06:00:00Z",
        "forecast_min_temp_c": -4.0,
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "code": "MAIN",
        "provisional_advance_rate_per_barrel": D["ADVANCE_RATE_MAIN"],
        "retain_pct": D["RETAIN_PCT"],
    }
    defaults.update(overrides)
    return defaults


def patch_pool_payload(rate, expected_pool_version) -> dict:
    return {
        "provisional_advance_rate_per_barrel": rate,
        "expected_pool_version": expected_pool_version,
    }


def patch_quota_payload(base_quota_barrels, expected_quota_version) -> dict:
    return {
        "base_quota_barrels": base_quota_barrels,
        "expected_quota_version": expected_quota_version,
    }


def settle_pool_payload(realized_revenue, operating_costs,
                        expected_pool_version) -> dict:
    return {
        "realized_revenue": realized_revenue,
        "operating_costs": operating_costs,
        "expected_pool_version": expected_pool_version,
    }


def create_delivery_payload(season_id, bog_id, receiving_station_id,
                            **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "bog_id": bog_id,
        "receiving_station_id": receiving_station_id,
        "scheduled_date": D["SCHEDULED_DATE"],
        "expected_barrels": 150,
    }
    defaults.update(overrides)
    return defaults


def receive_delivery_payload(gross_barrels, tare_barrels) -> dict:
    return {"gross_barrels": gross_barrels, "tare_barrels": tare_barrels}


def grade_delivery_payload(color_score, firmness_score, foreign_matter_pct) -> dict:
    return {
        "color_score": color_score,
        "firmness_score": firmness_score,
        "foreign_matter_pct": foreign_matter_pct,
    }
