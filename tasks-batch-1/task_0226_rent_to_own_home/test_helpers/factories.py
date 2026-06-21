"""Payload factories — one per entity, input fields only.

Each test runs against a freshly restarted (empty) server, but within a single
test/fixture several landlords, tenants, and properties may be created. Email is
unique among landlords/tenants and address is unique among properties (§3.1), so
the factories mint a fresh unique suffix on every call unless overridden.
"""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_landlord_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "legal_name": f"Landlord {n}",
        "email": f"landlord{n}@example.com",
        "payout_account_ref": f"acct_l{n}",
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "legal_name": f"Tenant {n}",
        "email": f"tenant{n}@example.com",
        "credit_score": 700,
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(landlord_id: str, **overrides) -> dict:
    n = _uniq()
    defaults = {
        "landlord_id": landlord_id,
        "address": f"{n} Test Street",
        "list_price_cents": 30000000,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(property_id: str, tenant_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "locked_price_cents": 30000000,
        "option_fee_cents": 500000,
        "monthly_payment_cents": 200000,
        "credit_pct": 0.30,
        "lease_start": "2026-01-01T00:00:00Z",
        "option_term_months": 24,
    }
    defaults.update(overrides)
    return defaults


def create_rent_payment_payload(period_index: int, due_date: str, **overrides) -> dict:
    defaults = {
        "period_index": period_index,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_ticket_payload(**overrides) -> dict:
    defaults = {
        "summary": "Repair needed",
        "estimated_cost_cents": 80000,
    }
    defaults.update(overrides)
    return defaults


def create_option_exercise_payload(exercised_at: str, **overrides) -> dict:
    defaults = {"exercised_at": exercised_at}
    defaults.update(overrides)
    return defaults


def create_mortgage_payload(option_exercise_id: str, **overrides) -> dict:
    defaults = {
        "option_exercise_id": option_exercise_id,
        "annual_rate_bps": 0,
        "term_months": 360,
    }
    defaults.update(overrides)
    return defaults
