"""Death-claim fork-join, death-benefit valuation variants, share-completeness
boundary, and file/deny conservation.

Difficulty-queue instances each carry >=2 tests; one corner-design instance
(future date of death) is also translated here.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_death_claim_filed, setup_death_claim_verifying, setup_death_claim_valued,
    setup_active_fixed_contract, add_beneficiaries, set_clock,
    create_withdrawal_payload, create_death_claim_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _fund_corridor_withdrawal(api, contract_id, amount):
    """Settle a fully-free-corridor partial withdrawal of `amount` cents."""
    fresh = validate_success(api.get_contract(contract_id, ADMIN), 200)
    wd = validate_success(api.create_withdrawal(create_withdrawal_payload(
        contract_id, amount, fresh["version"]), ADMIN), 201)
    validate_success(api.settle_withdrawal(wd["id"], COMPLIANCE), 200)


# ─── dual_variant_calc / death_benefit_return_of_premium_vs_account_value ──
def test_death_benefit_return_of_premium_uses_cumulative_premium(api):
    """PRD §3.9: "For `RETURN_OF_PREMIUM`, the benefit is the larger of the
    contract's `cumulative_premium_cents` and its `accumulation_value_cents`."

    Design: Difficulty/dual_variant_calc/death_benefit_return_of_premium_vs_account_value
    """
    set_clock("2026-01-01T00:00:00Z")
    product, contract, claim, _ = setup_death_claim_verifying(
        gross_premium_cents=2_000_000, death_benefit_type="RETURN_OF_PREMIUM",
        beneficiary_shares=(10000,))
    # Reduce accumulation to 1,800,000 via a 200,000 fully-free-corridor withdrawal
    # BEFORE filing — but the claim is already filed/frozen here, so instead build a
    # parallel RETURN_OF_PREMIUM contract reduced first. We reduce before the claim:
    # (handled by the contrast test below). Here we assert pure RETURN_OF_PREMIUM on
    # an un-reduced contract: cumulative == accumulation == 2,000,000.
    valued = validate_success(api.value_benefit(claim["id"], COMPLIANCE), 200)
    assert valued["death_benefit_cents"] == 2000000


def test_death_benefit_account_value_vs_return_of_premium_diverge(api):
    """PRD §3.9: "For `RETURN_OF_PREMIUM`, the benefit is the larger of the
    contract's `cumulative_premium_cents` and its `accumulation_value_cents`."
    PRD §3.9: "For `ACCOUNT_VALUE`, it is simply the contract's
    `accumulation_value_cents`."

    Design: Difficulty/dual_variant_calc/death_benefit_return_of_premium_vs_account_value
    """
    set_clock("2026-01-01T00:00:00Z")
    # Contract A: RETURN_OF_PREMIUM, reduced to accumulation 1,800,000 (cumulative 2,000,000).
    prod_a, contract_a, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=10000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}],
        death_benefit_type="RETURN_OF_PREMIUM")
    _fund_corridor_withdrawal(api, contract_a["id"], 200000)
    add_beneficiaries(contract_a["id"], (10000,))
    claim_a = validate_success(api.create_death_claim(
        create_death_claim_payload(contract_a["id"], "2026-01-01T00:00:00Z"), ADMIN), 201)
    validate_success(api.verify_identity(claim_a["id"], COMPLIANCE), 200)
    valued_a = validate_success(api.value_benefit(claim_a["id"], COMPLIANCE), 200)

    # Contract B: ACCOUNT_VALUE, reduced identically to accumulation 1,800,000.
    prod_b, contract_b, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=10000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}],
        death_benefit_type="ACCOUNT_VALUE")
    _fund_corridor_withdrawal(api, contract_b["id"], 200000)
    add_beneficiaries(contract_b["id"], (10000,))
    claim_b = validate_success(api.create_death_claim(
        create_death_claim_payload(contract_b["id"], "2026-01-01T00:00:00Z"), ADMIN), 201)
    validate_success(api.verify_identity(claim_b["id"], COMPLIANCE), 200)
    valued_b = validate_success(api.value_benefit(claim_b["id"], COMPLIANCE), 200)

    assert valued_a["death_benefit_cents"] == 2000000
    assert valued_b["death_benefit_cents"] == 1800000
    assert valued_a["death_benefit_cents"] != valued_b["death_benefit_cents"]


# ─── non_linear_state_machine / death_claim_fork_join_two_branches ────────
def test_death_claim_fork_join_reaches_funded_and_terminates(api):
    """PRD §3.9: "Funding then joins both branches: it moves the claim from
    `VALUED` to `FUNDED` only when both `identity_verified` and `benefit_valued`
    are true and the `ACTIVE` beneficiary shares sum to exactly 10000".
    PRD §3.9: "Funding distributes the death benefit across the `ACTIVE`
    beneficiaries, cascades the contract from `DEATH_CLAIM` to `TERMINATED`".

    Design: Difficulty/non_linear_state_machine/death_claim_fork_join_two_branches
    """
    product, contract, claim, _ = setup_death_claim_valued(
        gross_premium_cents=2_000_000, death_benefit_type="ACCOUNT_VALUE",
        beneficiary_shares=(10000,))
    funded = validate_success(api.fund_death_claim(claim["id"], COMPLIANCE), 200)
    assert funded["identity_verified"] is True
    assert funded["benefit_valued"] is True
    assert funded["status"] == "FUNDED"
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["status"] == "TERMINATED"


def test_death_claim_branch_flags_set_by_each_transition(api):
    """PRD §3.9: "The first branch, verify-identity, moves the claim from
    `FILED` to `VERIFYING` and sets `identity_verified` to true."
    PRD §3.9: "The second branch, value-benefit, moves the claim from
    `VERIFYING` to `VALUED`, requires that `identity_verified` already be true,
    sets `benefit_valued` to true, and computes the `death_benefit_cents`."

    Design: Difficulty/non_linear_state_machine/death_claim_fork_join_two_branches
    """
    product, contract, claim, _ = setup_death_claim_filed(
        gross_premium_cents=2_000_000, death_benefit_type="ACCOUNT_VALUE",
        beneficiary_shares=(10000,))
    verified = validate_success(api.verify_identity(claim["id"], COMPLIANCE), 200)
    assert verified["status"] == "VERIFYING"
    assert verified["identity_verified"] is True
    valued = validate_success(api.value_benefit(claim["id"], COMPLIANCE), 200)
    assert valued["status"] == "VALUED"
    assert valued["benefit_valued"] is True


# ─── boundary_precision_check / beneficiary_shares_must_sum_exactly_10000_to_fund ─
def test_fund_blocked_when_shares_sum_below_10000(api):
    """PRD §3.9: "it moves the claim from `VALUED` to `FUNDED` only when both
    `identity_verified` and `benefit_valued` are true and the `ACTIVE`
    beneficiary shares sum to exactly 10000 (otherwise
    `ERR_BENEFICIARY_SHARES_INCOMPLETE`)."

    Design: Difficulty/boundary_precision_check/beneficiary_shares_must_sum_exactly_10000_to_fund
    """
    product, contract, claim, _ = setup_death_claim_valued(
        gross_premium_cents=2_000_000, death_benefit_type="ACCOUNT_VALUE",
        beneficiary_shares=((6000, "One"), (3999, "Two")))
    res = api.fund_death_claim(claim["id"], COMPLIANCE)
    validate_error(res, "ERR_BENEFICIARY_SHARES_INCOMPLETE", expected_status=409)
    claim_after = validate_success(api.get_death_claim(claim["id"], ADMIN), 200)
    assert claim_after["status"] == "VALUED"


def test_fund_succeeds_when_shares_sum_exactly_10000(api):
    """PRD §3.9: "it moves the claim from `VALUED` to `FUNDED` only when both
    `identity_verified` and `benefit_valued` are true and the `ACTIVE`
    beneficiary shares sum to exactly 10000".

    Design: Difficulty/boundary_precision_check/beneficiary_shares_must_sum_exactly_10000_to_fund
    """
    product, contract, claim, _ = setup_death_claim_valued(
        gross_premium_cents=2_000_000, death_benefit_type="ACCOUNT_VALUE",
        beneficiary_shares=((6000, "One"), (4000, "Two")))
    funded = validate_success(api.fund_death_claim(claim["id"], COMPLIANCE), 200)
    assert funded["status"] == "FUNDED"


# ─── compensating_invariant / death_claim_file_then_deny_conserves_accumulation ─
def test_file_then_deny_conserves_accumulation(api):
    """PRD §3.9: "Filing a claim cascades the contract from `ACTIVE` to
    `DEATH_CLAIM`, which **freezes** the contract".
    PRD §3.9: "a `ComplianceOfficer` may deny it, moving it to `DENIED` and
    cascading the contract from `DEATH_CLAIM` back to `ACTIVE` — un-freezing
    it".

    Design: Difficulty/compensating_invariant/death_claim_file_then_deny_conserves_accumulation
    """
    product, contract, claim, _ = setup_death_claim_filed(
        gross_premium_cents=2_000_000, death_benefit_type="ACCOUNT_VALUE",
        beneficiary_shares=(10000,))
    denied = validate_success(api.deny_death_claim(claim["id"], COMPLIANCE), 200)
    assert denied["status"] == "DENIED"
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 2000000
    assert contract_after["status"] == "ACTIVE"


def test_deny_unfreezes_contract_back_to_active(api):
    """PRD §3.9: "a `ComplianceOfficer` may deny it, moving it to `DENIED` and
    cascading the contract from `DEATH_CLAIM` back to `ACTIVE` — un-freezing
    it".

    Design: Difficulty/compensating_invariant/death_claim_file_then_deny_conserves_accumulation
    """
    product, contract, claim, _ = setup_death_claim_filed(
        gross_premium_cents=2_000_000, death_benefit_type="ACCOUNT_VALUE",
        beneficiary_shares=(10000,))
    frozen = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert frozen["status"] == "DEATH_CLAIM"
    validate_success(api.deny_death_claim(claim["id"], COMPLIANCE), 200)
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["status"] == "ACTIVE"


# ─── validations / future_date_of_death_rejected (corner) ─────────────────
def test_future_date_of_death_rejected(api):
    """PRD §3.9: "the `date_of_death`, which must not be after the current
    server clock; a future date of death is rejected with
    `ERR_FUTURE_DATE_OF_DEATH`."

    Design: Corner/validations/future_date_of_death_rejected
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, death_benefit_type="ACCOUNT_VALUE",
        clock="2026-01-01T00:00:00Z")
    res = api.create_death_claim(
        create_death_claim_payload(contract["id"], "2027-06-01T00:00:00Z"), ADMIN)
    validate_error(res, "ERR_FUTURE_DATE_OF_DEATH", expected_status=422)
