"""Means-test variants (SSI vs Medicaid), the $100k SSI boundary, the management fee
round-then-sum, and the Medicaid payback waterfall at death.

Difficulty (queue A) instances appear with >=2 tests each; corner (queue B)
instances appear once. Each docstring ends with its Design tag.
"""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    make_program_admin_headers,
    setup_open_account,
    setup_frozen_account,
    post_contribution,
    credit_earnings,
    record_death,
    file_medicaid_claim,
    get_account,
    get_medicaid_claim,
)

ADMIN = make_program_admin_headers()


# ===========================================================================
# Difficulty: dual_variant_calc / ssi_vs_medicaid_disregard_same_balance
# ===========================================================================
def _setup_101_500_balance(api):
    """Balance 10_150_000 ($101,500): REGULAR 1_900_000 + earnings 8_250_000."""
    _, _, beneficiary, account = setup_open_account(
        beneficiary_overrides={"other_countable_resources_cents": 0}
    )
    post_contribution(account["id"], 1_900_000, account["version"])
    credit_earnings(account["id"], 8_250_000)
    return beneficiary, account


def test_means_test_ssi_counts_balance_above_threshold(api):
    """PRD 3.7: "the portion of the ABLE balance that counts against SSI is the amount by which
    `balance_cents` exceeds the program's `ssi_suspension_threshold_cents`, floored at zero — so
    a balance at or below one hundred thousand dollars contributes nothing."
    PRD 3.7: "if that total is strictly greater than the program's `ssi_resource_limit_cents`
    (two thousand dollars), the account's `ssi_posture` is `SSI_SUSPENDED`, and otherwise it is
    `SSI_OK`."

    Design: Difficulty/dual_variant_calc/ssi_vs_medicaid_disregard_same_balance
    """
    beneficiary, account = _setup_101_500_balance(api)
    resp = api.means_test(account["id"], "SSI", ADMIN)
    data = validate_success(resp)
    # 10_150_000 - 10_000_000 = 150_000 above the threshold.
    assert data["able_countable_for_ssi_cents"] == 150_000
    assert data["total_countable_cents"] == 150_000
    # PRD 3.7: posture is SSI_SUSPENDED only when total_countable is STRICTLY GREATER
    # than ssi_resource_limit_cents (200_000). 150_000 is not > 200_000, so SSI_OK.
    assert data["ssi_posture"] == "SSI_OK"


def test_means_test_medicaid_disregards_entire_balance(api):
    """PRD 3.7: "The Medicaid variant is deliberately different: the entire ABLE balance is
    disregarded for Medicaid regardless of the hundred-thousand-dollar threshold, so only the
    beneficiary's `other_countable_resources_cents` is countable and the same balance that can
    suspend SSI never affects Medicaid the same way."

    Design: Difficulty/dual_variant_calc/ssi_vs_medicaid_disregard_same_balance
    """
    beneficiary, account = _setup_101_500_balance(api)
    resp = api.means_test(account["id"], "MEDICAID", ADMIN)
    data = validate_success(resp)
    assert data["able_countable_for_ssi_cents"] == 0
    assert data["affects_benefit"] is False


# ===========================================================================
# Difficulty: boundary_precision_check / ssi_threshold_strict_gt_at_100k_boundary
# ===========================================================================
def _setup_at_100k(api):
    """other_countable 200_000 (= $2,000 limit); balance set to exactly 10_000_000
    via REGULAR 1_900_000 + earnings 8_100_000."""
    _, _, beneficiary, account = setup_open_account(
        beneficiary_overrides={"other_countable_resources_cents": 200_000}
    )
    post_contribution(account["id"], 1_900_000, account["version"])
    credit_earnings(account["id"], 8_100_000)
    return beneficiary, account


def test_ssi_posture_ok_at_exact_threshold(api):
    """PRD 2.7: "the SSI tests at the hundred-thousand-dollar disregard ceiling and the
    two-thousand-dollar resource limit are strict greater-than comparisons, so a balance
    exactly at a boundary does not trip it."

    Design: Difficulty/boundary_precision_check/ssi_threshold_strict_gt_at_100k_boundary
    """
    beneficiary, account = _setup_at_100k(api)
    # balance exactly 10_000_000 -> able countable 0 -> total_countable 200_000, NOT > 200_000.
    data = validate_success(api.means_test(account["id"], "SSI", ADMIN))
    assert data["ssi_posture"] == "SSI_OK", "total_countable 200000 is not strictly greater than the limit"


def test_ssi_posture_suspended_one_cent_over_threshold(api):
    """PRD 3.7: "if that total is strictly greater than the program's `ssi_resource_limit_cents`
    (two thousand dollars), the account's `ssi_posture` is `SSI_SUSPENDED`, and otherwise it is
    `SSI_OK`."

    Design: Difficulty/boundary_precision_check/ssi_threshold_strict_gt_at_100k_boundary
    """
    beneficiary, account = _setup_at_100k(api)
    credit_earnings(account["id"], 1)  # balance now 10_000_001
    # able countable 1 -> total_countable 200_001 > 200_000.
    data = validate_success(api.means_test(account["id"], "SSI", ADMIN))
    assert data["ssi_posture"] == "SSI_SUSPENDED"


# ===========================================================================
# Difficulty: combinatorial_formula / management_fee_round_per_month_then_sum
# ===========================================================================
def test_management_fee_round_per_month_then_sum(api):
    """PRD 3.11: "The monthly fee is `period_end_balance_cents` multiplied by that monthly rate,
    rounded half up to whole cents. The fee for the period is that rounded monthly fee
    multiplied by the number of `months`."

    Design: Difficulty/combinatorial_formula/management_fee_round_per_month_then_sum
    """
    _, _, _, account = setup_open_account()
    post_contribution(account["id"], 1_900_000, account["version"])
    credit_earnings(account["id"], 1_433_333)
    account = get_account(account["id"])  # balance 3_333_333
    # monthly rate = (30/10000)/12; 3_333_333 * rate = 833.333... -> 833; 833 * 12 = 9_996.
    resp = api.assess_fee(account["id"], {"period_end_balance_cents": 3_333_333, "months": 12}, ADMIN)
    data = validate_success(resp)
    assert data["balance_cents"] == 3_333_333 - 9_996, (
        f"fee must be 9996 (833 x 12), leaving balance {3_333_333 - 9_996}, got {data['balance_cents']}"
    )


def test_management_fee_not_round_of_annual_figure(api):
    """PRD 3.11: "rounding per period and then summing, never rounding a single annual figure,
    because the two can differ by a few cents and the per-period rounding is authoritative."

    Design: Difficulty/combinatorial_formula/management_fee_round_per_month_then_sum
    """
    _, _, _, account = setup_open_account()
    post_contribution(account["id"], 1_900_000, account["version"])
    credit_earnings(account["id"], 1_433_333)
    account = get_account(account["id"])
    resp = api.assess_fee(account["id"], {"period_end_balance_cents": 3_333_333, "months": 12}, ADMIN)
    data = validate_success(resp)
    fee = 3_333_333 - data["balance_cents"]
    assert fee == 9_996, f"round-per-month-then-sum gives 9996, not the 10000 of an annual rounding; got {fee}"


# ===========================================================================
# Difficulty: compensating_invariant / medicaid_settle_conserves_balance_partition
# ===========================================================================
def _setup_filed_claim_for_settle(api):
    """FROZEN_DEATH account, balance 8_000_000, premiums 800_000; claim 3_000_000 FILED."""
    _, _, beneficiary, account = setup_frozen_account(
        basis_cents=1_900_000, earnings_delta_cents=6_100_000,
        account_overrides={"premiums_paid_by_beneficiary_cents": 800_000},
    )
    claim = file_medicaid_claim(account["id"], 3_000_000)
    return account, claim


def test_medicaid_payback_partition_at_filing(api):
    """PRD 3.12: "the claimable amount is `claimed_amount_cents` minus
    `premiums_paid_by_beneficiary_cents`, floored at zero. The `allowed_payback_cents` is then the
    smaller of the post-bucket balance and that claimable amount, and the `residual_to_estate_cents`
    is the post-bucket balance minus the allowed payback."

    Design: Difficulty/compensating_invariant/medicaid_settle_conserves_balance_partition
    """
    account, claim = _setup_filed_claim_for_settle(api)
    # claimable = 3_000_000 - 800_000 = 2_200_000; allowed = min(8_000_000, 2_200_000) = 2_200_000;
    # residual = 8_000_000 - 2_200_000 = 5_800_000.
    assert claim["allowed_payback_cents"] == 2_200_000
    assert claim["residual_to_estate_cents"] == 5_800_000
    assert claim["allowed_payback_cents"] + claim["residual_to_estate_cents"] == 8_000_000


def test_medicaid_settle_closes_account_and_debits_balance(api):
    """PRD 3.12: "Settling moves the claim from `FILED` to `SETTLED`, decrements the account's
    `balance_cents` by the claim's `allowed_payback_cents`, records the `residual_to_estate_cents`
    left for the estate, and moves the account from `FROZEN_DEATH` to `CLOSED`."

    Design: Difficulty/compensating_invariant/medicaid_settle_conserves_balance_partition
    """
    account, claim = _setup_filed_claim_for_settle(api)
    resp = api.settle_medicaid_claim(account["id"], claim["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "SETTLED"
    after_account = get_account(account["id"])
    assert after_account["status"] == "CLOSED"
    assert after_account["balance_cents"] == 8_000_000 - 2_200_000, (
        f"balance must be debited by the allowed payback, got {after_account['balance_cents']}"
    )


# ===========================================================================
# Corner: calculations / medicaid_payback_claim_below_balance_uncapped
# ===========================================================================
def test_medicaid_payback_claim_below_balance_uncapped(api):
    """PRD 3.12: "The `allowed_payback_cents` is then the smaller of the post-bucket balance and
    that claimable amount, and the `residual_to_estate_cents` is the post-bucket balance minus the
    allowed payback."

    Design: Corner/calculations/medicaid_payback_claim_below_balance_uncapped
    """
    _, _, beneficiary, account = setup_frozen_account(
        basis_cents=1_900_000, earnings_delta_cents=6_100_000,
        account_overrides={"premiums_paid_by_beneficiary_cents": 0},
    )
    # balance 8_000_000, premiums 0, claim 3_000_000 (< balance) -> claim binds.
    claim = file_medicaid_claim(account["id"], 3_000_000)
    assert claim["allowed_payback_cents"] == 3_000_000
    assert claim["residual_to_estate_cents"] == 5_000_000
