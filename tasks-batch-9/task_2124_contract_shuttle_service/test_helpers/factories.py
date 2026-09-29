"""Payload factories — one per resource, carrying only client-supplied fields."""

import itertools

from .constants import TEST_DEFAULTS

_fleet_code_counter = itertools.count(1)
_driver_counter = itertools.count(1)
_route_counter = itertools.count(1)


def next_fleet_code() -> str:
    """A fleet code that is unique inside a single test run."""
    return f"SHV-{next(_fleet_code_counter):04d}"


def contract_payload(**overrides) -> dict:
    payload = {
        "client_name": "Harborview Hotel",
        "site_type": "HOTEL",
        "base_rate_cents_per_service_hour": TEST_DEFAULTS["BASE_RATE_CENTS_PER_SERVICE_HOUR"],
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "escalation_index_pct": TEST_DEFAULTS["ESCALATION_INDEX_PCT"],
        "sla_on_time_threshold_pct": TEST_DEFAULTS["SLA_ON_TIME_THRESHOLD_PCT"],
        "penalty_rate_cents_per_missed_trip": TEST_DEFAULTS["PENALTY_RATE_CENTS_PER_MISSED_TRIP"],
        "ada_min_accessible_pct": TEST_DEFAULTS["ADA_MIN_ACCESSIBLE_PCT"],
    }
    payload.update(overrides)
    return payload


def route_payload(contract_id: str, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "name": f"Airport Loop {next(_route_counter)}",
        "loop_minutes": TEST_DEFAULTS["LOOP_MINUTES"],
        "headway_minutes": TEST_DEFAULTS["HEADWAY_MINUTES"],
        "service_window_start_min": TEST_DEFAULTS["SERVICE_WINDOW_START_MIN"],
        "service_window_end_min": TEST_DEFAULTS["SERVICE_WINDOW_END_MIN"],
        "demand_forecast_pax_per_hour": 0,
        "reference_seat_capacity": TEST_DEFAULTS["REFERENCE_SEAT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def vehicle_payload(**overrides) -> dict:
    payload = {
        "fleet_code": next_fleet_code(),
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "is_ada_accessible": False,
        "odometer_km": 10_000,
        "service_interval_km": 20_000,
    }
    payload.update(overrides)
    return payload


def driver_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Dana Ruiz {next(_driver_counter)}",
        "license_class": "CDL_B",
        "ada_certified": False,
        "max_duty_minutes_per_day": TEST_DEFAULTS["MAX_DUTY_MINUTES_PER_DAY"],
    }
    payload.update(overrides)
    return payload


def maintenance_order_payload(vehicle_id: str, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "kind": "PREVENTIVE",
        "service_date": TEST_DEFAULTS["SERVICE_DATE"],
        "window_start_min": 600,
        "window_end_min": 660,
    }
    payload.update(overrides)
    return payload


def on_demand_request_payload(contract_id: str, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "service_date": TEST_DEFAULTS["SERVICE_DATE"],
        "requested_pickup_min": 420,
        "party_size": 1,
        "requires_ada": False,
    }
    payload.update(overrides)
    return payload


def ridership_count_payload(trip_id: str, **overrides) -> dict:
    payload = {
        "trip_id": trip_id,
        "boarded": 10,
        "alighted": 10,
        "ada_boardings": 0,
        "source": "DRIVER_TALLY",
    }
    payload.update(overrides)
    return payload


def report_payload(contract_id: str, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "period_start_date": TEST_DEFAULTS["PERIOD_START_DATE"],
        "period_end_date": TEST_DEFAULTS["PERIOD_END_DATE"],
    }
    payload.update(overrides)
    return payload


def credit_memo_payload(contract_id: str, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "amount_cents": 1_000,
        "reason": "GOODWILL",
    }
    payload.update(overrides)
    return payload


def renewal_offer_payload(contract_id: str, expected_contract_version: int, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "proposed_term_months": 12,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def trip_completion_payload(actual_completion_min: int, **overrides) -> dict:
    payload = {
        "actual_completion_min": actual_completion_min,
        "boarded": 5,
        "alighted": 5,
        "ada_boardings": 0,
    }
    payload.update(overrides)
    return payload
