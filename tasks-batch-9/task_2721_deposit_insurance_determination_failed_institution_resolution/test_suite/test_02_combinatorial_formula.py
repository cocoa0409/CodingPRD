"""Two computations whose answer depends on the order the arithmetic is resolved in.

A dividend round is the sum of individually rounded per-certificate entitlements,
never the rounding of a summed entitlement; and a loss-share administration fee is
tiered from the pre-fee cost that precedes it, never from the total that contains
it.  Both orders are pinned, and taking the other order produces a different and
wrong number that these tests name explicitly.
"""
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_bid_costs,
    assert_certificate,
    assert_conservation_identities_hold,
    assert_fields_equal,
)


def _single_loss_share_bid_book(client):
    """A closed 29000001-cent estate with one qualified bidder's loss-share bid.

    The retention pool of 2000000 cents sits well under the cap of half the book
    asset value, and no determination is certified, so the bid is screened purely
    on its own terms.
    """
    estate = X.pooled_estate(
        client, cert_number="40003", legal_name="Salish Community Bank"
    )
    institution_id = estate["institution"]["id"]
    X.open_marketing(client, institution_id)
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Cascade Union Bank",
        cert_number="51001",
        tier1_capital_ratio_bps=1400,
        camels_composite=2,
    )
    estate["bid"] = X.new_bid(
        client,
        institution_id,
        bidder["id"],
        structure="LOSS_SHARE_PA",
        deposit_premium_bps=1379,
        asset_discount_bps=1000,
        loss_share_pct_bps=6000,
        asset_retention_pool_cents=2000000,
        data_room_window_start="2026-09-01T09:00:00Z",
        data_room_window_end="2026-09-01T12:00:00Z",
    )
    return estate


# ---------------------------------------------------------------------------
# Round each certificate first, then sum
# ---------------------------------------------------------------------------
def test_general_unsecured_round_rounds_each_certificate_before_summing(client):
    """A round at 3333 basis points against faces of 4000001 and 2000001 cents
    distributes 1333200 plus 666600, a total of 1999800 cents and never 1999801.

    PRD: "rounding per certificate first yields 1333200 plus 666600, a total of 1999800 cents, whereas summing first and rounding once would yield 1999801 cents"

    Design: Difficulty/combinatorial_formula/dividend_rounds_per_certificate_before_summation_mode_b
    """
    estate = X.estate_with_settled_general_unsecured_round(
        client, cert_number="34568", legal_name="Sound Federal Bank"
    )
    settled = estate["round"]

    assert_fields_equal(
        settled,
        {
            "status": "SETTLED",
            "distribution_round": 1,
            "certificate_count": 2,
            "total_distributed_cents": C.DIVIDEND_TOTAL_ROUND_PER_PART_CENTS,
        },
    )
    # The forbidden sum-then-round order would have produced one cent more.
    assert settled["total_distributed_cents"] != C.DIVIDEND_TOTAL_IF_SUMMED_FIRST_CENTS

    assert_certificate(
        estate["alice_certificate"],
        "PARTIALLY_PAID",
        C.CERT_FACE_LARGE_CENTS,
        cumulative_dividends_cents=C.DIVIDEND_LARGE_CENTS,
        last_dividend_amount_cents=C.DIVIDEND_LARGE_CENTS,
        last_dividend_round=1,
    )
    assert_certificate(
        estate["bob_certificate"],
        "PARTIALLY_PAID",
        C.CERT_FACE_SMALL_CENTS,
        cumulative_dividends_cents=C.DIVIDEND_SMALL_CENTS,
        last_dividend_amount_cents=C.DIVIDEND_SMALL_CENTS,
        last_dividend_round=1,
    )
    # The two rounded parts account for the whole distributed total exactly.
    assert (
        estate["alice_certificate"]["last_dividend_amount_cents"]
        + estate["bob_certificate"]["last_dividend_amount_cents"]
        == settled["total_distributed_cents"]
    )


def test_settled_round_reduces_receivership_cash_by_the_distributed_total(client):
    """Settling that round leaves 2000200 cents of receivership cash out of the
    4000000 realized, and both conservation deltas stay at zero.

    PRD: "The round then stores its `total_distributed_cents` and `certificate_count`, stamps `settled_at` from the logical clock, moves `status` `DECLARED` → `SETTLED`, and the institution's `receivership_cash_cents` is recomputed and falls by the distributed total."

    Design: Difficulty/combinatorial_formula/dividend_rounds_per_certificate_before_summation_mode_b
    """
    estate = X.estate_with_settled_general_unsecured_round(
        client, cert_number="34568", legal_name="Sound Federal Bank"
    )
    institution_id = estate["institution"]["id"]

    institution = X.get_institution(client, institution_id)
    assert_fields_equal(
        institution,
        {
            "gross_disposition_proceeds_cents": 5000000,
            "disposition_expense_total_cents": 1000000,
            "receivership_cash_cents": 2000200,
        },
    )

    summary = X.insurance_summary(client, institution_id)
    assert_fields_equal(
        summary,
        {
            "receivership_cash_cents": 2000200,
            "dividends_paid_cents": C.DIVIDEND_TOTAL_ROUND_PER_PART_CENTS,
        },
    )
    assert_conservation_identities_hold(summary)


# ---------------------------------------------------------------------------
# Key the fee tier on the pre-fee cost, not on the total that contains the fee
# ---------------------------------------------------------------------------
def test_loss_share_fee_tier_is_keyed_on_the_pre_fee_cost(client):
    """A pre-fee cost of 4900901 cents sits in the 25 basis point tier, so the fee is
    12252 cents — not the 19604 that keying the tier on the 7397153 total would give.

    PRD: "The **fee tier** is selected from the pre-fee cost: a pre-fee cost of 5000000 cents or less takes 25 basis points; a pre-fee cost above that but no greater than 20000000 cents takes 40 basis points; anything above 20000000 cents takes 60 basis points."

    Design: Difficulty/combinatorial_formula/loss_share_fee_tier_keyed_on_pre_fee_cost_mode_c
    """
    estate = _single_loss_share_bid_book(client)
    X.evaluate_least_cost(client, estate["institution"]["id"], "EXPECTED_LOSS_SHARE")

    bid = X.get_bid(client, estate["bid"]["id"])
    assert bid["status"] == "CONFORMING"
    assert_bid_costs(
        bid,
        assumed_deposit_base_cents=C.POOLED_ATTRIBUTED_CENTS,
        pre_fee_cost_cents=4900901,
        loss_share_fee_cents=12252,
        expected_loss_share_reimbursement_cents=2484000,
        evaluated_cost_cents=7397153,
    )
    # The pre-fee cost clears the first tier ceiling, and the total does not.
    assert bid["pre_fee_cost_cents"] <= C.LSF_TIER_A_CEILING_CENTS
    assert bid["evaluated_cost_cents"] > C.LSF_TIER_A_CEILING_CENTS
    # Keying the tier on that total would have charged 40 basis points instead.
    assert bid["loss_share_fee_cents"] != 19604


def test_liquidation_baseline_is_administrative_cost_only_when_nothing_is_certified(client):
    """With no certified determination the insured share is zero, so the baseline for
    one depositor is the bare administrative cost of 150000 cents.

    PRD: "The baseline is then `aggregate_insured_cents`, plus an administrative cost of 150000 cents — 1500 dollars — for each depositor counted in `depositor_record_count`, minus that subrogated recovery."

    Design: Difficulty/combinatorial_formula/loss_share_fee_tier_keyed_on_pre_fee_cost_mode_c
    """
    estate = _single_loss_share_bid_book(client)
    X.evaluate_least_cost(client, estate["institution"]["id"], "EXPECTED_LOSS_SHARE")

    institution = X.get_institution(client, estate["institution"]["id"])
    assert_fields_equal(
        institution,
        {
            "aggregate_insured_cents": 0,
            "depositor_record_count": 1,
            "liquidation_baseline_cents": C.ADMIN_COST_PER_DEPOSITOR_CENTS,
            "conforming_bid_count": 1,
            "least_cost_status": "EVALUATED",
        },
    )
