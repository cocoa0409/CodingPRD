"""Payload factories — one per creatable entity, input fields only.

Unique codes/emails come from a process-wide counter so multiple creates inside
one test never collide on the uniqueness rules of PRD section 3.1.
"""
import itertools

from .constants import DEFAULT_TARIFF_BANDS, TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_agent_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"Agent Co {n}",
        "agent_code": f"A{n % 1000000:05d}"[:8],
        "capabilities": ["BOOKING"],
        "home_market": "Chicago",
        "commission_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Shipper {n}",
        "email": f"shipper{n}@example.com",
        "phone": f"555-{n % 10000:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_tariff_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "tariff_code": f"T-{n}",
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2027-01-01T00:00:00Z",
        "base_rate_cents_per_cwt": TEST_DEFAULTS["BASE_RATE_CENTS_PER_CWT"],
        "mileage_bands": [dict(b) for b in DEFAULT_TARIFF_BANDS],
        "fuel_surcharge_pct": TEST_DEFAULTS["FUEL_SURCHARGE_PCT"],
        "sit_daily_rate_cents_per_cwt": TEST_DEFAULTS["SIT_DAILY_RATE_CENTS_PER_CWT"],
        "hourly_labor_rate_cents": TEST_DEFAULTS["HOURLY_LABOR_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, tariff_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tariff_id": tariff_id,
        "pricing_mode": "NON_BINDING",
        "origin_city": "Chicago",
        "origin_state": "IL",
        "destination_city": "Denver",
        "destination_state": "CO",
        "mileage": TEST_DEFAULTS["MILEAGE"],
        "pickup_date": TEST_DEFAULTS["PICKUP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(expected_order_version, **overrides) -> dict:
    defaults = {
        "estimate_kind": "NON_BINDING",
        "estimated_weight_lbs": TEST_DEFAULTS["ESTIMATED_WEIGHT_LBS"],
        "packing_services_cents": 0,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_agent_assignment_payload(agent_id, role, **overrides) -> dict:
    defaults = {"agent_id": agent_id, "role": role}
    defaults.update(overrides)
    return defaults


def create_valuation_coverage_payload(expected_order_version, **overrides) -> dict:
    defaults = {
        "coverage_type": "RELEASED_VALUE",
        "declared_value_cents": 0,
        "deductible_cents": 0,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_weight_ticket_payload(**overrides) -> dict:
    defaults = {
        "scale_location": "SCALE-01",
        "weighed_at": "2026-06-10T09:00:00Z",
        "tare_weight_lbs": TEST_DEFAULTS["TARE_WEIGHT_LBS"],
        "gross_weight_lbs": TEST_DEFAULTS["TARE_WEIGHT_LBS"] + 9600,
    }
    defaults.update(overrides)
    return defaults


def create_reweigh_request_payload(**overrides) -> dict:
    defaults = {"requested_by_role": "CUSTOMER"}
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"SIT Warehouse {n}",
        "market": "Denver",
        "capacity_cwt": 500,
    }
    defaults.update(overrides)
    return defaults


def create_sit_lot_payload(warehouse_id, **overrides) -> dict:
    defaults = {"warehouse_id": warehouse_id}
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(**overrides) -> dict:
    defaults = {
        "service_end": "ORIGIN",
        "service_date": TEST_DEFAULTS["PICKUP_DATE"],
        "start_hour": 8,
        "end_hour": 12,
        "crew_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "description": "Loss/damage claim",
        "claimed_amount_cents": 250000,
        "claimed_item_weight_lbs": 200,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"subject_amount_cents": 10000}
    defaults.update(overrides)
    return defaults
