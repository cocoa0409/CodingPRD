"""Payload factories — one per entity, input fields only (PRD §3).

Each factory provides sensible defaults; pass **overrides to control specific fields.
Field names are PRD-exact.
"""
import itertools

# Monotonic counters so default unique fields (naic_code, npn, state_code) do not
# collide across multiple creations inside one test.
_naic_counter = itertools.count(10000)
_npn_counter = itertools.count(1)


def unique_naic_code() -> str:
    """A fresh 5-digit NAIC code (PRD §3.1: exactly five digits, unique)."""
    return str(next(_naic_counter))[-5:].zfill(5)


def unique_npn() -> str:
    """A fresh non-empty unique National Producer Number (PRD §3.2)."""
    return f"NPN{next(_npn_counter):06d}"


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Carrier",
        "naic_code": unique_naic_code(),
        "download_supported": False,
        "default_new_business_commission_pct": 0.15,
        "default_renewal_commission_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "line_of_business": "AUTO",
        "name": "Test Product",
        "cancellation_basis": "PRO_RATA",
    }
    defaults.update(overrides)
    return defaults


def create_producer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Producer",
        "npn": unique_npn(),
        "default_split_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(producer_id, **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "state_code": "CA",
        "line_of_business": "AUTO",
        "effective_date": "2025-01-01T00:00:00Z",
        "expiration_date": "2030-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(carrier_id, producer_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "producer_id": producer_id,
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(servicing_producer_id, **overrides) -> dict:
    defaults = {
        "name": "Test Account",
        "servicing_producer_id": servicing_producer_id,
        "account_type": "PERSONAL",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(account_id, product_id, writing_producer_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "product_id": product_id,
        "writing_producer_id": writing_producer_id,
        "state_code": "CA",
        "annual_premium_cents": 1_200_000,
        "effective_date": "2026-01-01T00:00:00Z",
        "expiration_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_commission_split_payload(
    policy_id, producer_id, expected_policy_version, **overrides
) -> dict:
    defaults = {
        "policy_id": policy_id,
        "producer_id": producer_id,
        "split_pct": 1.0,
        "role": "WRITING",
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_trust_account_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Trust Account",
        "state_code": "CA",
        "minimum_balance_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(entry_type, amount_cents, expected_trustaccount_version, **overrides) -> dict:
    defaults = {
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "expected_trustaccount_version": expected_trustaccount_version,
    }
    defaults.update(overrides)
    return defaults


def create_commission_statement_payload(producer_id, period_start, period_end, **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_task_payload(policy_id, target_effective_date, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "target_effective_date": target_effective_date,
    }
    defaults.update(overrides)
    return defaults
