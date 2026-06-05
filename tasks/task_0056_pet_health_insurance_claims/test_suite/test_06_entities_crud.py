"""Entity creation, defaults, type constraints, computed fields, and invalid
state transitions on the policy/invoice/claim machines.

Corner queue: entities, state_machines (policy invalid transitions).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_account, create_policy, activate_policy,
    create_account_payload, create_policy_payload,
    make_underwriter_headers, make_policy_holder_headers,
    ApiErrorId,
)


def _uw():
    return make_underwriter_headers()


def test_create_account_returns_201_with_computed_defaults(api):
    """PRD 2.4: "a version integer that begins at 1 and increments by exactly 1 on every
    mutation."
    PRD 3.1: "the account exposes three computed fields that the platform keeps in sync:
    active_policy_count, monthly_premium_cents, and multi_pet_discount_applied. The
    active_policy_count is the number of the account's child policies currently in ACTIVE
    status."

    A brand-new account has no active policies, so version 1, premium 0, count 0.

    Design: Corner/entities/create_account_returns_201_with_fields
    """
    resp = api.create_account(create_account_payload(email="e1@x.com", full_name="C One"), _uw())
    data = validate_success(resp, 201)
    assert data["version"] == 1
    assert data["monthly_premium_cents"] == 0
    assert data["active_policy_count"] == 0


def test_get_account_not_found(api):
    """PRD 2.5: "The request is rejected with ERR_NOT_FOUND at the first path segment
    that does not resolve to an existing resource."

    Design: Corner/entities/get_account_not_found
    """
    resp = api.get_account("00000000-0000-4000-8000-000000000000", _uw())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_policy_missing_reimbursement_rate_rejected(api):
    """PRD 3.2: "An Underwriter issues a Policy under an account by providing the insured
    pet_name, the species ... the reimbursement_rate_bps (an integer from 0 through 10000
    inclusive), the annual_cap_cents (a non-negative integer), the effective_date."
    PRD 2.3 / Section 5: missing required field is ERR_INVALID_REQUEST (400).

    Omitting reimbursement_rate_bps -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_policy_missing_required_field
    """
    acct = create_account(email="e2@x.com")
    payload = {
        "pet_name": "Rex", "species": "DOG", "base_premium_cents": 4500,
        "annual_deductible_cents": 25000, "annual_cap_cents": 500000,
        "effective_date": "2026-01-01T00:00:00Z",
    }
    resp = api.create_policy(acct["id"], payload, _uw())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_policy_optional_defaults_applied(api):
    """PRD 3.2: "optionally waiting_period_days (a non-negative integer that defaults to
    14) and wellness_rider (a boolean that defaults to false) ... A freshly issued policy
    begins in PENDING_PAYMENT status."

    Design: Corner/entities/policy_waiting_period_default_applied
    """
    acct = create_account(email="e3@x.com")
    payload = {
        "pet_name": "Rex", "species": "DOG", "base_premium_cents": 4500,
        "annual_deductible_cents": 25000, "reimbursement_rate_bps": 8000,
        "annual_cap_cents": 500000, "effective_date": "2026-01-01T00:00:00Z",
    }
    data = validate_success(api.create_policy(acct["id"], payload, _uw()), 201)
    assert data["waiting_period_days"] == 14, f"expected default 14, got {data['waiting_period_days']}"
    assert data["wellness_rider"] is False
    assert data["status"] == "PENDING_PAYMENT"


def test_create_policy_invalid_species_rejected(api):
    """PRD 3.2: "the species (one of DOG or CAT)."
    Section 5: bad enum is ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_policy_invalid_species_enum
    """
    acct = create_account(email="e4@x.com")
    resp = api.create_policy(acct["id"], create_policy_payload(species="FERRET"), _uw())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_account_system_fields_minted_not_client_supplied(api):
    """PRD 2.4: "a system-managed id, a server-minted UUID with no type prefix that
    serves as identity only and is never itself a business-decision input ... a version
    integer that begins at 1."
    PRD 3.1: a new account's computed premium reflects zero active policies.

    Design: Corner/entities/account_system_fields_input_ignored
    """
    data = validate_success(
        api.create_account(create_account_payload(email="e5@x.com"), make_policy_holder_headers("anything")), 201)
    assert data["version"] == 1
    assert data["monthly_premium_cents"] == 0


def test_condition_diagnosed_before_coverage_is_pre_existing(api):
    """PRD 3.3: "If the condition's first_diagnosed_date falls strictly before that
    coverage-start date, the condition is PRE_EXISTING; otherwise it is COVERED ... This
    status is computed when the condition is recorded."

    Effective 2026-01-01 + 14d -> coverage start 2026-01-15; diagnosed 2026-01-05 is
    before it -> PRE_EXISTING.

    Design: Corner/entities/condition_computed_exclusion_pre_existing
    """
    acct = create_account(email="e6@x.com")
    pol = create_policy(acct["id"], waiting_period_days=14, effective_date="2026-01-01T00:00:00Z")
    activate_policy(acct["id"], pol["id"])
    data = validate_success(api.create_condition(
        acct["id"], pol["id"], {"name": "old injury", "first_diagnosed_date": "2026-01-05T00:00:00Z"}, _uw()), 201)
    assert data["exclusion_status"] == "PRE_EXISTING", f"got {data['exclusion_status']}"


def test_condition_diagnosed_exactly_at_coverage_start_is_covered(api):
    """PRD 3.3: "the boundary is treated strictly: a diagnosis dated exactly at coverage
    start is COVERED, not pre-existing."

    Effective 2026-01-01 + 14d -> coverage start 2026-01-15; diagnosed exactly 2026-01-15
    -> COVERED.

    Design: Corner/calculations/condition_exactly_at_coverage_start_is_covered
    """
    acct = create_account(email="e17@x.com")
    pol = create_policy(acct["id"], waiting_period_days=14, effective_date="2026-01-01T00:00:00Z")
    activate_policy(acct["id"], pol["id"])
    data = validate_success(api.create_condition(
        acct["id"], pol["id"], {"name": "boundary", "first_diagnosed_date": "2026-01-15T00:00:00Z"}, _uw()), 201)
    assert data["exclusion_status"] == "COVERED", f"got {data['exclusion_status']}"


def test_activate_already_active_policy_invalid_state(api):
    """PRD 3.2: "Activation moves a policy from PENDING_PAYMENT to ACTIVE and is permitted
    only from PENDING_PAYMENT; attempting it from any other status yields
    ERR_INVALID_STATE."

    Design: Corner/state_machines/activate_already_active_policy_returns_invalid_state
    """
    acct = create_account(email="e7@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])

    resp = api.activate_policy(acct["id"], pol["id"], {}, _uw())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_terminal_cancelled_policy_invalid_state(api):
    """PRD 3.2: "the lifecycle states are PENDING_PAYMENT, ACTIVE, LAPSED, and CANCELLED,
    with CANCELLED being terminal ... cancelling moves a policy to CANCELLED ... both
    reject from a disallowed source status with ERR_INVALID_STATE."

    Cancel a policy already CANCELLED -> ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_cancelled_policy_terminal_lockdown
    """
    acct = create_account(email="e8@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])
    validate_success(api.cancel_policy(acct["id"], pol["id"], _uw()))

    resp = api.cancel_policy(acct["id"], pol["id"], _uw())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
