"""Payload factories — one per entity, input fields only (Car Sharing PRD §3).

Only fields the client supplies (source: input) appear here. System/computed
fields (status, ledger totals, version, settlement figures) are minted by the
server and never sent.
"""
from .constants import TEST_DEFAULTS


def create_host_payload(**overrides) -> dict:
    payload = {"name": "Test Host", "email": "host@example.com"}
    payload.update(overrides)
    return payload


def create_guest_payload(**overrides) -> dict:
    payload = {"name": "Test Guest", "email": "guest@example.com"}
    payload.update(overrides)
    return payload


def submit_verification_payload(**overrides) -> dict:
    payload = {
        "license_number": "DL-0001",
        "license_state": "CA",
        "license_expiry_date": "2030-01-01",
    }
    payload.update(overrides)
    return payload


def create_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "STANDARD",
        "deductible_cents": TEST_DEFAULTS["PLAN_DEDUCTIBLE_CENTS"],
        "daily_premium_cents": TEST_DEFAULTS["PLAN_DAILY_PREMIUM_CENTS"],
        "coverage_limit_cents": TEST_DEFAULTS["PLAN_COVERAGE_LIMIT_CENTS"],
        "host_earnings_pct": TEST_DEFAULTS["PLAN_HOST_EARNINGS_PCT"],
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(host_id, **overrides) -> dict:
    payload = {
        "host_id": host_id,
        "make": "Toyota",
        "model": "Corolla",
        "year": 2022,
        "base_daily_price_cents": TEST_DEFAULTS["BASE_DAILY_PRICE_CENTS"],
        "location_city": "SF",
    }
    payload.update(overrides)
    return payload


def create_availability_block_payload(start_date, end_date, **overrides) -> dict:
    payload = {"start_date": start_date, "end_date": end_date}
    payload.update(overrides)
    return payload


def create_pricing_rule_payload(vehicle_id, start_date, end_date, daily_price_cents, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "start_date": start_date,
        "end_date": end_date,
        "daily_price_cents": daily_price_cents,
    }
    payload.update(overrides)
    return payload


def create_trip_payload(vehicle_id, guest_id, protection_plan_id, start_date, end_date,
                        expected_vehicle_version, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "guest_id": guest_id,
        "protection_plan_id": protection_plan_id,
        "start_date": start_date,
        "end_date": end_date,
        "expected_vehicle_version": expected_vehicle_version,
    }
    payload.update(overrides)
    return payload


def inspection_payload(odometer_reading, fuel_level_pct, photo_refs=None, **overrides) -> dict:
    payload = {
        "odometer_reading": odometer_reading,
        "fuel_level_pct": fuel_level_pct,
        "photo_refs": photo_refs if photo_refs is not None else ["photo-1"],
    }
    payload.update(overrides)
    return payload


def create_extension_payload(new_end_date, **overrides) -> dict:
    payload = {"new_end_date": new_end_date}
    payload.update(overrides)
    return payload


def create_claim_payload(claimant, damage_amount_cents, description="incident", **overrides) -> dict:
    payload = {
        "claimant": claimant,
        "damage_amount_cents": damage_amount_cents,
        "description": description,
    }
    payload.update(overrides)
    return payload


def create_payout_payload(host_id, amount_cents, expected_host_version, **overrides) -> dict:
    payload = {
        "host_id": host_id,
        "amount_cents": amount_cents,
        "expected_host_version": expected_host_version,
    }
    payload.update(overrides)
    return payload
