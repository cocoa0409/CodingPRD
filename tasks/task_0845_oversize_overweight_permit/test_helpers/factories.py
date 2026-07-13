"""Payload factories — one per entity, input fields only.

Each test runs against a fresh database, so default unique keys (usdot_number,
cert_number) only need to be unique within a single test.
"""

# Default validity window (well after the default logical clock of 2026-03-01).
DEFAULT_VALID_FROM = "2026-06-01T00:00:00Z"
DEFAULT_VALID_UNTIL = "2026-06-30T00:00:00Z"


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Hauling Co",
        "usdot_number": "USDOT-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(carrier_id, **overrides) -> dict:
    """Default is an OVERWEIGHT SINGLE_TRIP load (gross 120000)."""
    defaults = {
        "carrier_id": carrier_id,
        "permit_type": "SINGLE_TRIP",
        "length_in": 900,
        "width_in": 100,
        "height_in": 100,
        "front_overhang_in": 0,
        "rear_overhang_in": 0,
        "gross_weight_lbs": 120000,
        "num_axles": 9,
        "valid_from": DEFAULT_VALID_FROM,
        "valid_until": DEFAULT_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_structure_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Span",
        "highway_id": "I-80",
        "milepost": 5,
        "rated_capacity_tonnage": 200,
        "dead_load_tonnage": 40,
    }
    defaults.update(overrides)
    return defaults


def create_pilot_car_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Test Escort Co",
        "cert_number": "PC-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_travel_restriction_payload(**overrides) -> dict:
    defaults = {
        "restriction_type": "CURFEW",
        "start_utc": "2026-06-05T09:00:00Z",
        "end_utc": "2026-06-05T11:00:00Z",
        "applies_to_classification": "ALL",
    }
    defaults.update(overrides)
    return defaults


def create_route_segment_payload(**overrides) -> dict:
    defaults = {
        "sequence_index": 1,
        "highway_id": "I-80",
        "from_milepost": 0,
        "to_milepost": 10,
    }
    defaults.update(overrides)
    return defaults


def create_escort_assignment_payload(pilot_car_id, **overrides) -> dict:
    defaults = {
        "pilot_car_id": pilot_car_id,
        "role": "FRONT",
        "window_start_utc": "2026-06-05T10:00:00Z",
        "window_end_utc": "2026-06-05T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(permit_id, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "violation_type": "OVER_DIMENSION",
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def escrow_deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
