"""Payload factories — one per creatable entity, input fields only.

Required fields get sensible defaults; optional fields are omitted unless
supplied via overrides (so server-side defaults can be exercised).
"""
import itertools

# Monotonic counter to keep FEINs unique across factory calls within a test.
_fein_counter = itertools.count(1)


def make_unique_fein() -> str:
    """Generate a syntactically employer-FEIN-shaped string unique per call."""
    n = next(_fein_counter)
    return f"{n % 100:02d}-{n:07d}"


def create_custodial_party_payload(**overrides) -> dict:
    """Required: full_name, state_code. Optional: assistance_status."""
    payload = {
        "full_name": "Test Payee",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_noncustodial_party_payload(**overrides) -> dict:
    """Required: full_name, ssn_last4. Optional: supports_second_family."""
    payload = {
        "full_name": "Test Obligor",
        "ssn_last4": "0000",
    }
    payload.update(overrides)
    return payload


def create_employer_payload(**overrides) -> dict:
    """Required: legal_name, fein. Optional: remittance_method."""
    payload = {
        "legal_name": "Test Employer",
        "fein": make_unique_fein(),
    }
    payload.update(overrides)
    return payload


def create_support_order_payload(custodial_party_id, noncustodial_party_id, **overrides) -> dict:
    """Required: custodial_party_id, noncustodial_party_id, current_support_cents.
    Optional: frequency, interest_rate_bps, assigned_arrears_cents."""
    payload = {
        "custodial_party_id": custodial_party_id,
        "noncustodial_party_id": noncustodial_party_id,
        "current_support_cents": 30000,
    }
    payload.update(overrides)
    return payload


def create_iwo_payload(support_order_id, employer_id, **overrides) -> dict:
    """Required: support_order_id, employer_id, ordered_amount_cents,
    effective_start_at, effective_end_at."""
    payload = {
        "support_order_id": support_order_id,
        "employer_id": employer_id,
        "ordered_amount_cents": 30000,
        "effective_start_at": "2026-01-01T00:00:00Z",
        "effective_end_at": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_remittance_payload(employer_id, noncustodial_party_id, **overrides) -> dict:
    """Required: employer_id, noncustodial_party_id, disposable_earnings_cents,
    gross_remitted_cents."""
    payload = {
        "employer_id": employer_id,
        "noncustodial_party_id": noncustodial_party_id,
        "disposable_earnings_cents": 100000,
        "gross_remitted_cents": 30000,
    }
    payload.update(overrides)
    return payload


def create_disbursement_payload(support_order_id, custodial_party_id, allocation_id, **overrides) -> dict:
    """Required: support_order_id, custodial_party_id, allocation_id. Optional: method."""
    payload = {
        "support_order_id": support_order_id,
        "custodial_party_id": custodial_party_id,
        "allocation_id": allocation_id,
    }
    payload.update(overrides)
    return payload


def create_modification_payload(support_order_id, **overrides) -> dict:
    """Required: support_order_id, proposed_current_support_cents,
    coverage_start_at, coverage_end_at."""
    payload = {
        "support_order_id": support_order_id,
        "proposed_current_support_cents": 45000,
        "coverage_start_at": "2026-07-01T00:00:00Z",
        "coverage_end_at": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_enforcement_action_payload(support_order_id, expected_support_order_version, **overrides) -> dict:
    """Required: support_order_id, action_type, expected_support_order_version."""
    payload = {
        "support_order_id": support_order_id,
        "action_type": "TAX_INTERCEPT",
        "expected_support_order_version": expected_support_order_version,
    }
    payload.update(overrides)
    return payload
