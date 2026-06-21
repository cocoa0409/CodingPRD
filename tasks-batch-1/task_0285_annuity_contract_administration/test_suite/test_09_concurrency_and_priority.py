"""Optimistic-concurrency control and validation-precedence scenarios.

The priority-pair scenarios are each constructed so that exactly one check can
fire, and the asserted error is the one PRD §2.9's fixed precedence selects.
Difficulty-queue instances each carry >=2 tests; one corner-design OCC happy
path is also translated here.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_active_fixed_contract, set_clock,
    create_product_payload, create_contract_payload, create_premium_payload,
    create_withdrawal_payload, create_death_claim_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── priority_pair_validation_conflict / frozen_safety_wins_over_state_on_settle ─
def test_settle_on_frozen_contract_rejected_with_frozen(api):
    """PRD §3.9: "While a contract is frozen by an open claim (one in `FILED`,
    `VERIFYING`, or `VALUED`), the system refuses to create new withdrawals, new
    premiums, or new annuitizations on it, and refuses to clear premiums or
    settle withdrawals against it, in each case with `ERR_CONTRACT_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_safety_wins_over_state_on_settle
    """
    # The withdrawal is REQUESTED (valid state for settle), so only the frozen
    # safety check can fire once a death claim freezes the contract.
    set_clock("2026-01-01T00:00:00Z")
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=10000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}])
    wd = validate_success(api.create_withdrawal(create_withdrawal_payload(
        contract["id"], 100000, contract["version"]), ADMIN), 201)
    # Add a beneficiary then file a death claim to freeze the contract.
    validate_success(api.create_beneficiary({
        "contract_id": contract["id"], "full_name": "Bea", "relationship": "SPOUSE",
        "share_bps": 10000}, ADMIN), 201)
    validate_success(api.create_death_claim(
        create_death_claim_payload(contract["id"], "2026-01-01T00:00:00Z"), ADMIN), 201)
    res = api.settle_withdrawal(wd["id"], COMPLIANCE)
    validate_error(res, "ERR_CONTRACT_FROZEN", expected_status=409)


def test_create_withdrawal_on_frozen_contract_rejected_with_frozen(api):
    """PRD §3.9: "the system refuses to create new withdrawals, new premiums, or
    new annuitizations on it ... in each case with `ERR_CONTRACT_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_safety_wins_over_state_on_settle
    """
    set_clock("2026-01-01T00:00:00Z")
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=10000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}])
    validate_success(api.create_beneficiary({
        "contract_id": contract["id"], "full_name": "Bea", "relationship": "SPOUSE",
        "share_bps": 10000}, ADMIN), 201)
    validate_success(api.create_death_claim(
        create_death_claim_payload(contract["id"], "2026-01-01T00:00:00Z"), ADMIN), 201)
    frozen = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    res = api.create_withdrawal(create_withdrawal_payload(
        contract["id"], 100000, frozen["version"]), ADMIN)
    validate_error(res, "ERR_CONTRACT_FROZEN", expected_status=409)


# ─── priority_pair_validation_conflict / stale_version_state_wins_over_fiscal ─
def test_withdrawal_create_stale_version_rejected_before_sizing(api):
    """PRD §2.6: "Requesting a withdrawal requires `expected_contract_version`
    to carry the `version` the client last read on the target `Contract`. If
    another writer has since cleared a premium ... the contract's `version` has
    advanced and the request is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_state_wins_over_fiscal_on_withdraw_create
    """
    # The over-sized amount is irrelevant at create time: sizing happens at
    # settle. OCC (§2.9 concurrency) precedes any fiscal check, so a stale
    # version on create yields 412 regardless of the requested amount.
    set_clock("2026-01-01T00:00:00Z")
    product = validate_success(api.create_product(create_product_payload(
        min_initial_premium_cents=1_000_000), ADMIN), 201)
    contract = validate_success(api.create_contract(
        create_contract_payload(product["id"]), ADMIN), 201)
    prem0 = validate_success(api.create_premium(create_premium_payload(
        contract["id"], contract["version"], gross_premium_cents=1_000_000), ADMIN), 201)
    validate_success(api.clear_premium(prem0["id"], ADMIN), 200)
    fresh = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    stale_version = fresh["version"]
    # A second premium clears, advancing the version so `stale_version` is stale.
    prem1 = validate_success(api.create_premium(create_premium_payload(
        contract["id"], stale_version, gross_premium_cents=1_000_000), ADMIN), 201)
    validate_success(api.clear_premium(prem1["id"], ADMIN), 200)
    res = api.create_withdrawal(create_withdrawal_payload(
        contract["id"], 9_999_999, stale_version), ADMIN)
    validate_error(res, "ERR_STALE_CONTRACT_VERSION", expected_status=412)


def test_premium_create_stale_version_rejected(api):
    """PRD §2.6: "Submitting a subsequent premium likewise requires
    `expected_contract_version` to match the target `Contract`'s current
    `version`; a mismatch is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412)".

    Design: Difficulty/priority_pair_validation_conflict/stale_version_state_wins_over_fiscal_on_withdraw_create
    """
    product, contract, _ = setup_active_fixed_contract(gross_premium_cents=2_000_000)
    stale_version = contract["version"]
    # Clear another submitted premium to advance the version.
    prem = validate_success(api.create_premium(create_premium_payload(
        contract["id"], stale_version, gross_premium_cents=1_000_000), ADMIN), 201)
    validate_success(api.clear_premium(prem["id"], ADMIN), 200)
    res = api.create_premium(create_premium_payload(
        contract["id"], stale_version, gross_premium_cents=1_000_000), ADMIN)
    validate_error(res, "ERR_STALE_CONTRACT_VERSION", expected_status=412)


# NOTE: corner instance
# Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
# is SKIPPED under the PRD-first filter (unique derivability). Its assertion is
# "Contract.version == cv1 + 1" after a withdrawal CREATE, but PRD prose never
# states that requesting a withdrawal bumps Contract.version: §2.5 enumerates the
# version-bumping events (first-premium clear, full-surrender settle, annuitization
# begin, death-claim file/fund/deny, anniversary roll, crediting, premium-clearing)
# and §3.5 says only that *settle* increments the version while request defers all
# computation. A faithful PRD-only implementer could ship a non-version-bumping
# withdrawal create, so the assertion is not uniquely derivable. Gap left as a gap.
