"""Payload factories — one per entity, input fields only.

Field names are exact per the PRD; only fields the client actually supplies on
create appear here (system/computed fields are never sent).
"""

# Default booking window: 2026-05-01 -> 2026-06-30 == 60 nights (>= min term).
DEFAULT_MOVE_IN = "2026-05-01T00:00:00Z"
DEFAULT_PLANNED_MOVE_OUT = "2026-06-30T00:00:00Z"
DEFAULT_LEASE_START = "2026-05-01T00:00:00Z"
DEFAULT_LEASE_END = "2027-05-01T00:00:00Z"


def create_corporate_account_payload(**overrides) -> dict:
    payload = {
        "company_name": "Acme",
        "billing_email": "ap@acme.test",
    }
    payload.update(overrides)
    return payload


def create_rate_plan_payload(**overrides) -> dict:
    payload = {
        "name": "RP1",
        "monthly_rate_cents": 300_000,
        "utility_monthly_cents": 15_000,
        "cleaning_fee_cents": 12_000,
        "occupancy_tax_rate_bps": 1_200,
    }
    payload.update(overrides)
    return payload


def create_unit_payload(**overrides) -> dict:
    payload = {
        "name": "U1",
        "property_name": "Maple Court",
        "bedrooms": 1,
    }
    payload.update(overrides)
    return payload


def create_master_lease_payload(corporate_account_id, **overrides) -> dict:
    payload = {
        "corporate_account_id": corporate_account_id,
        "committed_units": 5,
        "negotiated_monthly_rate_cents": 280_000,
        "start_date": DEFAULT_LEASE_START,
        "end_date": DEFAULT_LEASE_END,
    }
    payload.update(overrides)
    return payload


def create_employee_payload(corporate_account_id, **overrides) -> dict:
    payload = {
        "corporate_account_id": corporate_account_id,
        "full_name": "Dana Lee",
        "email": "dana@acme.test",
    }
    payload.update(overrides)
    return payload


def create_stay_payload(unit_id, rate_plan_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "rate_plan_id": rate_plan_id,
        "move_in": DEFAULT_MOVE_IN,
        "planned_move_out": DEFAULT_PLANNED_MOVE_OUT,
        "deposit_held_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_housekeeping_visit_payload(stay_id, **overrides) -> dict:
    payload = {
        "stay_id": stay_id,
        "scheduled_date": "2026-05-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_damage_charge_payload(stay_id, **overrides) -> dict:
    payload = {
        "stay_id": stay_id,
        "amount_cents": 25_000,
        "description": "Wall damage",
    }
    payload.update(overrides)
    return payload


def renegotiate_payload(expected_master_lease_version, negotiated_monthly_rate_cents) -> dict:
    return {
        "expected_master_lease_version": expected_master_lease_version,
        "negotiated_monthly_rate_cents": negotiated_monthly_rate_cents,
    }
