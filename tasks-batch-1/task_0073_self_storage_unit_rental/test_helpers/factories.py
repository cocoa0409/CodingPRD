"""Payload factories — one per entity, input fields only.

Only fields the client supplies on creation are included. System/computed fields
(status, balance_cents, snapshots, redemption_amount_cents, etc.) are never sent.
"""

DEFAULT_START_DATE = "2026-04-01T00:00:00Z"


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Facility",
        "state_code": "TX",
        "climate_premium_pct": 0.20,
        "lien_default_days": 90,
        "late_fee_grace_days": 5,
        "late_fee_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "unit_number": "A-1",
        "size_class": "SIZE_10X10",
        "monthly_rate_cents": 10000,
        "climate_controlled": False,
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "email": "tenant@example.com",
        "full_name": "Test Tenant",
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(unit_id: str, tenant_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "start_date": DEFAULT_START_DATE,
        "billing_day": 1,
        "insurance_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(lease_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {"lease_id": lease_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "coverage_tier": "STANDARD",
        "coverage_start": DEFAULT_START_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_auction_proceeding_payload(lease_id: str, expected_lease_version: int, **overrides) -> dict:
    defaults = {"lease_id": lease_id, "expected_lease_version": expected_lease_version}
    defaults.update(overrides)
    return defaults


def create_transfer_order_payload(lease_id: str, to_unit_id: str, expected_lease_version: int, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "to_unit_id": to_unit_id,
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults
