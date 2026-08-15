"""Payload factories — one per creatable entity, input fields only (PRD §3/§4)."""

from .constants import TEST_DEFAULTS

_it_counter = {"n": 0}


def _next() -> int:
    _it_counter["n"] += 1
    return _it_counter["n"]


def create_base_payload(**overrides) -> dict:
    defaults = {
        "name": "GCN",
        "quiet_hours_start_min_utc": 60,
        "quiet_hours_end_min_utc": 780,
        "current_waiver_version": TEST_DEFAULTS["WAIVER_VERSION"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "route_code": f"R{n}",
        "tier": "SHORT",
        "duration_minutes": TEST_DEFAULTS["ROUTE_DURATION_MIN"],
        "base_seat_price_cents": TEST_DEFAULTS["BASE_SEAT_PRICE_CENTS"],
        "fuel_required_lb": TEST_DEFAULTS["ROUTE_FUEL_LB"],
        "min_altitude_ft": 500,
        "noise_sensitive": False,
        "noise_zones": [],
        "min_aircraft_noise_class": "ANY",
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "label": f"S{n}",
        "start_date": "2026-06-01",
        "end_date": "2026-09-01",
        "multiplier_bps": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "tail_number": f"N{n}",
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "empty_weight_lb": TEST_DEFAULTS["EMPTY_WEIGHT_LB"],
        "empty_moment_lb_in": TEST_DEFAULTS["EMPTY_MOMENT_LB_IN"],
        "max_takeoff_weight_lb": TEST_DEFAULTS["MAX_TAKEOFF_WEIGHT_LB"],
        "fuel_arm_inches": TEST_DEFAULTS["FUEL_ARM_INCHES"],
        "seat_arms_inches": [40, 40, 80, 80],
        "cg_forward_limit_in": TEST_DEFAULTS["CG_FORWARD_LIMIT_IN"],
        "cg_aft_limit_in": TEST_DEFAULTS["CG_AFT_LIMIT_IN"],
        "noise_class": "QUIET",
    }
    defaults.update(overrides)
    return defaults


def create_pilot_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "display_name": f"Pat {n}",
        "certificate_no": f"C{n}",
    }
    defaults.update(overrides)
    return defaults


def create_flight_payload(base_id, route_id, aircraft_id, pilot_id,
                          scheduled_departure_utc, **overrides) -> dict:
    payload = {
        "base_id": base_id,
        "route_id": route_id,
        "aircraft_id": aircraft_id,
        "pilot_id": pilot_id,
        "scheduled_departure_utc": scheduled_departure_utc,
    }
    payload.update(overrides)
    return payload


def passenger_entry(full_name, declared_weight_lb) -> dict:
    return {"full_name": full_name, "declared_weight_lb": declared_weight_lb}


def create_booking_payload(flight_id, passengers, **overrides) -> dict:
    n = _next()
    payload = {
        "flight_id": flight_id,
        "contact_name": f"Contact{n}",
        "contact_email": f"contact{n}@example.com",
        "passengers": passengers,
    }
    payload.update(overrides)
    return payload


def create_weather_observation_payload(base_id, observed_at, **overrides) -> dict:
    payload = {
        "base_id": base_id,
        "observed_at": observed_at,
        "ceiling_ft": 5000,
        "visibility_sm": 10,
        "wind_kt": 8,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(base_id, zone, observed_at, **overrides) -> dict:
    n = _next()
    payload = {
        "base_id": base_id,
        "zone": zone,
        "observed_at": observed_at,
        "description": f"noise complaint {n}",
        "reporter_ref": f"res-{n}",
    }
    payload.update(overrides)
    return payload
