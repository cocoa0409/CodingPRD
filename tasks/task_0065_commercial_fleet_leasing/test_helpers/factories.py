"""Payload factories — one per entity, input fields only (commercial fleet leasing)."""
import itertools

_seq = itertools.count(1)


def create_lessee_payload(**overrides) -> dict:
    n = next(_seq)
    defaults = {
        "company_name": f"Test Co {n}",
        "billing_email": f"billing{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(lessee_id, **overrides) -> dict:
    n = next(_seq)
    defaults = {
        "lessee_id": lessee_id,
        "full_name": f"Driver {n}",
        "license_number": f"LIC-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    n = next(_seq)
    defaults = {
        "vin": f"VIN{n:08d}",
        "class": "MEDIUM_DUTY",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(lessee_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "lessee_id": lessee_id,
        "vehicle_id": vehicle_id,
        "term_start": "2026-01-01T00:00:00Z",
        "term_end": "2026-12-31T00:00:00Z",
        "contracted_miles": 60000,
        "per_mile_overage_cents": 25,
        "overage_model": "CONTRACT_FLAT",
        "collision_deductible_cents": 100000,
        "waterfall_model": "DEDUCTIBLE_FIRST",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(lease_id, driver_id, expected_lease_version, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "driver_id": driver_id,
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-06-10T00:00:00Z",
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_card_payload(lease_id, **overrides) -> dict:
    n = next(_seq)
    defaults = {
        "lease_id": lease_id,
        "card_number": f"CARD-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_fuel_transaction_payload(fuel_card_id, **overrides) -> dict:
    defaults = {
        "fuel_card_id": fuel_card_id,
        "jurisdiction": "CA",
        "gallons": 100,
        "purchased_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_telematics_reading_payload(vehicle_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "jurisdiction": "CA",
        "odometer_miles": 1000,
        "segment_miles": 1000,
        "recorded_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_order_payload(vehicle_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "kind": "PREVENTIVE",
        "labor_cents": 1000,
        "parts_cents": 1000,
        "window_start": "2026-06-01T10:00:00Z",
        "window_end": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(vehicle_id, lease_id, expected_vehicle_version, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "lease_id": lease_id,
        "expected_vehicle_version": expected_vehicle_version,
    }
    defaults.update(overrides)
    return defaults


def assess_repair_payload(estimate_cents, insurance_cap_cents, **overrides) -> dict:
    defaults = {
        "estimate_cents": estimate_cents,
        "insurance_cap_cents": insurance_cap_cents,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(lease_id, **overrides) -> dict:
    defaults = {"lease_id": lease_id}
    defaults.update(overrides)
    return defaults


def create_ifta_return_payload(lessee_id, quarter="2026Q1", **overrides) -> dict:
    defaults = {"lessee_id": lessee_id, "quarter": quarter}
    defaults.update(overrides)
    return defaults
