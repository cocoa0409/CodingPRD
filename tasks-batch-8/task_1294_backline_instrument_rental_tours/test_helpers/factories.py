"""Payload factories — one per entity, input fields only.

Every factory accepts **overrides so tests can control exactly the fields
they care about while sensible defaults fill the rest.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_artist_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"legal_name": f"Test Artist {n}"}
    defaults.update(overrides)
    return defaults


def create_tour_payload(artist_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "artist_id": artist_id,
        "name": f"Test Tour {n}",
        "start_date": "2026-08-01T00:00:00Z",
        "end_date": "2026-08-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tour_stop_payload(**overrides) -> dict:
    defaults = {
        "city_code": TEST_DEFAULTS["STOP_CITY"],
        "venue_date": "2026-08-10T00:00:00Z",
        "load_in_ts": "2026-08-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rider_line_payload(gear_model_id, **overrides) -> dict:
    defaults = {
        "gear_model_id": gear_model_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_gear_model_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "sku": f"SKU-{n}",
        "category": "AMP",
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "replacement_value_cents": TEST_DEFAULTS["REPLACEMENT_VALUE_CENTS"],
        "weight_class": "HAND_CARRY",
    }
    defaults.update(overrides)
    return defaults


def create_gear_unit_payload(gear_model_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "gear_model_id": gear_model_id,
        "serial_number": f"SN-{n}",
        "home_city_code": TEST_DEFAULTS["HOME_CITY"],
    }
    defaults.update(overrides)
    return defaults


def create_source_payload(**overrides) -> dict:
    defaults = {
        "origin_city_code": TEST_DEFAULTS["HOME_CITY"],
        "dest_city_code": TEST_DEFAULTS["STOP_CITY"],
        "start_date": "2026-08-09T00:00:00Z",
        "end_date": "2026-08-11T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(tour_id, **overrides) -> dict:
    defaults = {
        "tour_id": tour_id,
        "from_city_code": TEST_DEFAULTS["HOME_CITY"],
        "to_city_code": TEST_DEFAULTS["STOP_CITY"],
        "ship_date": "2026-08-09T00:00:00Z",
        "capacity_kg": TEST_DEFAULTS["CAPACITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_line_payload(gear_unit_id, **overrides) -> dict:
    defaults = {
        "gear_unit_id": gear_unit_id,
        "weight_kg": TEST_DEFAULTS["WEIGHT_KG"],
        "labor_minutes": TEST_DEFAULTS["LABOR_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_flight_case_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "case_code": f"CASE-{n}",
        "size_class": "LARGE",
        "home_city_code": TEST_DEFAULTS["HOME_CITY"],
    }
    defaults.update(overrides)
    return defaults


def create_partner_vendor_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Vendor {n}",
        "city_codes": [TEST_DEFAULTS["STOP_CITY"]],
        "commission_bps": TEST_DEFAULTS["COMMISSION_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_cross_rental_request_payload(reservation_line_id, partner_vendor_id,
                                        gear_model_id, **overrides) -> dict:
    defaults = {
        "reservation_line_id": reservation_line_id,
        "partner_vendor_id": partner_vendor_id,
        "gear_model_id": gear_model_id,
        "vendor_rate_cents_per_day": TEST_DEFAULTS["VENDOR_RATE_CENTS_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_ticket_payload(gear_unit_id, **overrides) -> dict:
    defaults = {
        "gear_unit_id": gear_unit_id,
        "opened_reason": "SCHEDULED_CYCLE",
    }
    defaults.update(overrides)
    return defaults
