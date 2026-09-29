"""The two computations whose answer turns on a declared variant.

A depositor's insured position depends on where the standard maximum bites — once
on a pooled ownership-category bucket, or independently on each account's own
share — and a resolution's cost depends on which least-cost test variant was
pinned at evaluation time.  Both pairs run against byte-identical stored data, so
any divergence in the answers is attributable to the variant alone.
"""
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_bid_costs,
    assert_category_breakdown,
    assert_determination_amounts,
    assert_fields_equal,
)


# ---------------------------------------------------------------------------
# Shared setup: the two-bid book on a closed, marketed estate
# ---------------------------------------------------------------------------
BID_A_PREMIUM_BPS = 300
BID_C_PREMIUM_BPS = 1379
BID_C_LOSS_SHARE_BPS = 6000
BID_C_RETENTION_CENTS = 2000000

# Bid A: a whole-bank purchase and assumption leaving nothing behind.
BID_A_EVALUATED_CENTS = 5630001

# Bid C priced under EXPECTED_LOSS_SHARE.
BID_C_ELS_PRE_FEE_CENTS = 4900901
BID_C_ELS_FEE_CENTS = 12252
BID_C_ELS_REIMBURSEMENT_CENTS = 2484000
BID_C_ELS_EVALUATED_CENTS = 7397153

# Bid C priced under RETENTION_ADJUSTED.
BID_C_RA_PRE_FEE_CENTS = 5140901
BID_C_RA_FEE_CENTS = 20564
BID_C_RA_EVALUATED_CENTS = 5161465


def _two_bid_book(client, cert_number, legal_name):
    """A closed 29000001-cent estate carrying one whole-bank and one loss-share bid.

    Neither depositor position is certified, so `aggregate_insured_cents` is zero
    and the whole deposit base drives every priced step.
    """
    estate = X.pooled_estate(client, cert_number=cert_number, legal_name=legal_name)
    institution_id = estate["institution"]["id"]
    X.open_marketing(client, institution_id)
    whole_bank_bidder = X.new_qualified_bidder(
        client,
        legal_name="Cascade Union Bank",
        cert_number="51001",
        tier1_capital_ratio_bps=1400,
        camels_composite=2,
    )
    loss_share_bidder = X.new_qualified_bidder(
        client,
        legal_name="Puget Federal Bank",
        cert_number="51002",
        tier1_capital_ratio_bps=1600,
        camels_composite=1,
    )
    bid_a = X.new_bid(
        client,
        institution_id,
        whole_bank_bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=BID_A_PREMIUM_BPS,
        asset_discount_bps=1000,
        loss_share_pct_bps=0,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-09-01T09:00:00Z",
        data_room_window_end="2026-09-01T12:00:00Z",
    )
    bid_c = X.new_bid(
        client,
        institution_id,
        loss_share_bidder["id"],
        structure="LOSS_SHARE_PA",
        deposit_premium_bps=BID_C_PREMIUM_BPS,
        asset_discount_bps=1000,
        loss_share_pct_bps=BID_C_LOSS_SHARE_BPS,
        asset_retention_pool_cents=BID_C_RETENTION_CENTS,
        data_room_window_start="2026-09-01T16:00:00Z",
        data_room_window_end="2026-09-01T18:00:00Z",
    )
    estate["bid_a"] = bid_a
    estate["bid_c"] = bid_c
    return estate


# ---------------------------------------------------------------------------
# Where the standard maximum bites: pooled bucket versus per-account share
# ---------------------------------------------------------------------------
def test_aggregate_by_category_pools_both_single_accounts_against_one_maximum(client):
    """Two single-ownership accounts of 20000000 and 9000001 cents pool into one
    category bucket, so the statutory method insures 25000000 and leaves 4000001
    uninsured.

    PRD: "Aggregated by category the pooled bucket is 29000001 cents against a limit of 25000000, so the determination reads 25000000 insured and 4000001 uninsured."

    Design: Difficulty/dual_variant_calc/alice_category_pooled_vs_per_account_insured_divergence
    """
    estate = X.pooled_estate(client, cert_number="34567", legal_name="First Cascade Savings Bank")
    determination = X.determination_under_review(client, estate["depositor"]["id"])

    assert_fields_equal(
        determination,
        {"method_variant": "AGGREGATE_BY_CATEGORY", "status": "UNDER_REVIEW"},
    )
    assert_determination_amounts(
        determination,
        C.POOLED_INSURED_CENTS,
        C.POOLED_UNINSURED_CENTS,
        C.POOLED_ATTRIBUTED_CENTS,
    )
    assert_category_breakdown(
        determination,
        "SINGLE",
        attributed=C.POOLED_ATTRIBUTED_CENTS,
        limit=C.SMDIA_CENTS,
        insured=C.POOLED_INSURED_CENTS,
        uninsured=C.POOLED_UNINSURED_CENTS,
    )

    # Each contributing account records its own share of the pooled total.
    account_a = X.get_account(client, estate["account_a"]["id"])
    account_b = X.get_account(client, estate["account_b"]["id"])
    assert account_a["attributed_amount_cents"] == C.ACCOUNT_A_BALANCE_CENTS
    assert account_b["attributed_amount_cents"] == C.ACCOUNT_B_BALANCE_CENTS


def test_per_account_provisional_re_prepare_insures_both_accounts_in_full(client):
    """Sent back for revision and re-prepared per account, the same two accounts
    read 29000001 insured and nothing uninsured, because neither exceeds the limit
    on its own.

    PRD: "Taken per account, neither account exceeds the limit on its own, so the same data reads 29000001 insured and 0 uninsured."

    Design: Difficulty/dual_variant_calc/alice_category_pooled_vs_per_account_insured_divergence
    """
    estate = X.pooled_estate(client, cert_number="34567", legal_name="First Cascade Savings Bank")
    determination = X.determination_under_review(client, estate["depositor"]["id"])
    determination_id = determination["id"]
    aggregated_insured = determination["insured_amount_cents"]

    X.request_revision(
        client,
        determination_id,
        revision_reason="Re-run under the provisional per-account method for comparison",
    )
    reprepared = X.prepare(client, determination_id, "PER_ACCOUNT_PROVISIONAL")

    assert_fields_equal(
        reprepared,
        {
            "method_variant": "PER_ACCOUNT_PROVISIONAL",
            "status": "PREPARED",
            "revision_round": 1,
        },
    )
    assert_determination_amounts(
        reprepared, C.POOLED_ATTRIBUTED_CENTS, 0, C.POOLED_ATTRIBUTED_CENTS
    )
    # The two variants diverge by exactly the pooled overage on identical data.
    assert reprepared["insured_amount_cents"] - aggregated_insured == C.POOLED_UNINSURED_CENTS

    # Attribution is a property of the accounts, not of the variant.
    account_a = X.get_account(client, estate["account_a"]["id"])
    account_b = X.get_account(client, estate["account_b"]["id"])
    assert account_a["attributed_amount_cents"] == C.ACCOUNT_A_BALANCE_CENTS
    assert account_b["attributed_amount_cents"] == C.ACCOUNT_B_BALANCE_CENTS


# ---------------------------------------------------------------------------
# Which resolution is cheapest: the pinned least-cost test variant decides
# ---------------------------------------------------------------------------
def test_expected_loss_share_variant_makes_the_whole_bank_bid_cheapest(client):
    """Under `EXPECTED_LOSS_SHARE` the loss-share bid carries a reimbursement the
    whole-bank bid does not, so it evaluates at 7397153 against 5630001 and the
    whole-bank bid is the cheaper of the two.

    PRD: "Under `EXPECTED_LOSS_SHARE` the retained pool is marked at thirty percent and the insurer books a probability-weighted reimbursement on the transferred pool, which makes loss-share bids look expensive."

    Design: Difficulty/dual_variant_calc/bid_evaluation_variant_flips_least_cost_winner
    """
    estate = _two_bid_book(client, "40001", "Elliott Bay Trust")
    institution_id = estate["institution"]["id"]

    X.evaluate_least_cost(client, institution_id, "EXPECTED_LOSS_SHARE")

    bid_a = X.get_bid(client, estate["bid_a"]["id"])
    bid_c = X.get_bid(client, estate["bid_c"]["id"])
    assert_bid_costs(
        bid_a,
        assumed_deposit_base_cents=C.POOLED_ATTRIBUTED_CENTS,
        pre_fee_cost_cents=BID_A_EVALUATED_CENTS,
        loss_share_fee_cents=0,
        expected_loss_share_reimbursement_cents=0,
        evaluated_cost_cents=BID_A_EVALUATED_CENTS,
    )
    assert_bid_costs(
        bid_c,
        assumed_deposit_base_cents=C.POOLED_ATTRIBUTED_CENTS,
        pre_fee_cost_cents=BID_C_ELS_PRE_FEE_CENTS,
        loss_share_fee_cents=BID_C_ELS_FEE_CENTS,
        expected_loss_share_reimbursement_cents=BID_C_ELS_REIMBURSEMENT_CENTS,
        evaluated_cost_cents=BID_C_ELS_EVALUATED_CENTS,
    )
    assert bid_a["evaluated_cost_cents"] < bid_c["evaluated_cost_cents"]

    institution = X.get_institution(client, institution_id)
    assert_fields_equal(
        institution,
        {
            "least_cost_test_variant": "EXPECTED_LOSS_SHARE",
            "least_cost_status": "EVALUATED",
            "conforming_bid_count": 2,
        },
    )


def test_retention_adjusted_variant_makes_the_loss_share_bid_cheapest(client):
    """Under `RETENTION_ADJUSTED` the same loss-share bid books no reimbursement and
    evaluates at 5161465, so it undercuts the unchanged 5630001 whole-bank bid and
    the cheapest bid flips.

    PRD: "Under `RETENTION_ADJUSTED` no reimbursement is booked at all and the retained pool is instead stressed at forty-two percent, which raises the pre-fee cost and can push it across a fee-tier boundary."

    Design: Difficulty/dual_variant_calc/bid_evaluation_variant_flips_least_cost_winner
    """
    estate = _two_bid_book(client, "40002", "Rainier Mutual")
    institution_id = estate["institution"]["id"]

    X.evaluate_least_cost(client, institution_id, "RETENTION_ADJUSTED")

    bid_a = X.get_bid(client, estate["bid_a"]["id"])
    bid_c = X.get_bid(client, estate["bid_c"]["id"])
    # The whole-bank bid prices identically under either variant.
    assert bid_a["evaluated_cost_cents"] == BID_A_EVALUATED_CENTS
    assert_bid_costs(
        bid_c,
        assumed_deposit_base_cents=C.POOLED_ATTRIBUTED_CENTS,
        pre_fee_cost_cents=BID_C_RA_PRE_FEE_CENTS,
        loss_share_fee_cents=BID_C_RA_FEE_CENTS,
        expected_loss_share_reimbursement_cents=0,
        evaluated_cost_cents=BID_C_RA_EVALUATED_CENTS,
    )
    assert bid_c["evaluated_cost_cents"] < bid_a["evaluated_cost_cents"]

    institution = X.get_institution(client, institution_id)
    assert_fields_equal(
        institution,
        {
            "least_cost_test_variant": "RETENTION_ADJUSTED",
            "least_cost_status": "EVALUATED",
            "conforming_bid_count": 2,
        },
    )
