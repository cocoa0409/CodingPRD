"""The liquidation baseline, the conformance screens and bid pricing.

PRD section 3.8.  Every priced step rounds half up independently from its own
exact rational value -- the products are never chained together and rounded once
-- and the fee tier is keyed on the pre-fee cost of step five, never on the
final total.
"""

import lookup
from db import db
from services import aggregates
from util import floor_div, round_half_up

ADMIN_COST_PER_DEPOSITOR_CENTS = 150000

RETAINED_SHORTFALL_BPS = {
    "EXPECTED_LOSS_SHARE": 3000,
    "RETENTION_ADJUSTED": 4200,
}

EXPECTED_LOSS_RATE_BPS = 1800

# (inclusive pre-fee cost ceiling, fee rate in basis points)
FEE_TIERS = ((5000000, 25), (20000000, 40))
FEE_TIER_TOP_BPS = 60

MAX_RETENTION_BPS = 5000

TEST_VARIANTS = ("EXPECTED_LOSS_SHARE", "RETENTION_ADJUSTED")

BID_STRUCTURES = ("WHOLE_BANK_PA", "INSURED_DEPOSITS_ONLY_PA", "LOSS_SHARE_PA")


def liquidation_baseline_cents(institution):
    """The benchmark every bid must beat.

    The insured share is truncated downward *before* the subrogated recovery is
    rounded half up, in that order.
    """
    insured = aggregates.aggregate_insured_cents(institution["id"])
    total = aggregates.total_deposit_balance_cents(institution["id"])
    insured_share_bps = 0 if total == 0 else floor_div(insured * 10000, total)
    subrogated = round_half_up(
        institution["estimated_liquidation_recovery_cents"] * insured_share_bps, 10000
    )
    admin = ADMIN_COST_PER_DEPOSITOR_CENTS * aggregates.depositor_record_count(
        institution["id"]
    )
    return insured + admin - subrogated


def retention_cap_cents(institution):
    """Half the book asset value, truncated downward."""
    return floor_div(institution["book_asset_value_cents"] * MAX_RETENTION_BPS, 10000)


def non_conformance_reason(institution, bid):
    """The three screens in their pinned order, so the stored reason is
    deterministic when a bid fails more than one."""
    if bid["asset_retention_pool_cents"] > retention_cap_cents(institution):
        return "RETENTION_POOL_ABOVE_CAP"
    bidder = db.bidders.get(bid["bidder_id"])
    if bidder is None or bidder["qualification_status"] != "QUALIFIED":
        return "BIDDER_NOT_QUALIFIED_AT_EVALUATION"
    if bid["structure"] == "INSURED_DEPOSITS_ONLY_PA":
        if aggregates.aggregate_insured_cents(institution["id"]) <= 0:
            return "INSURED_ONLY_WITHOUT_CERTIFIED_DETERMINATIONS"
    return None


def fee_tier_bps(pre_fee_cost_cents):
    for ceiling, rate in FEE_TIERS:
        if pre_fee_cost_cents <= ceiling:
            return rate
    return FEE_TIER_TOP_BPS


def evaluated_cost(institution, bid, test_variant):
    """The nine pinned pricing steps of PRD section 3.8."""
    structure = bid["structure"]

    # 1. assumed deposit base
    if structure == "INSURED_DEPOSITS_ONLY_PA":
        assumed_deposit_base = aggregates.aggregate_insured_cents(institution["id"])
    else:
        assumed_deposit_base = aggregates.total_deposit_balance_cents(institution["id"])

    # 2. deposit premium paid to the receivership
    deposit_premium = round_half_up(
        assumed_deposit_base * bid["deposit_premium_bps"], 10000
    )

    # 3. transferred asset value and the discounted asset bid value
    transferred_asset_value = (
        institution["book_asset_value_cents"] - bid["asset_retention_pool_cents"]
    )
    asset_bid_value = round_half_up(
        transferred_asset_value * (10000 - bid["asset_discount_bps"]), 10000
    )

    # 4. retained shortfall on the pool the bidder leaves behind
    retained_shortfall = round_half_up(
        bid["asset_retention_pool_cents"] * RETAINED_SHORTFALL_BPS[test_variant], 10000
    )

    # 5. pre-fee cost -- it alone keys the fee tier
    pre_fee_cost = (
        assumed_deposit_base - asset_bid_value - deposit_premium + retained_shortfall
    )

    # 6 + 7. loss-share administration fee, only for LOSS_SHARE_PA
    if structure == "LOSS_SHARE_PA":
        loss_share_fee = round_half_up(
            pre_fee_cost * fee_tier_bps(pre_fee_cost), 10000
        )
    else:
        loss_share_fee = 0

    # 8. expected loss-share reimbursement
    if test_variant == "EXPECTED_LOSS_SHARE" and structure == "LOSS_SHARE_PA":
        expected_reimbursement = round_half_up(
            transferred_asset_value * EXPECTED_LOSS_RATE_BPS * bid["loss_share_pct_bps"],
            100000000,
        )
    else:
        expected_reimbursement = 0

    # 9. evaluated cost
    return {
        "assumed_deposit_base_cents": assumed_deposit_base,
        "pre_fee_cost_cents": pre_fee_cost,
        "loss_share_fee_cents": loss_share_fee,
        "expected_loss_share_reimbursement_cents": expected_reimbursement,
        "evaluated_cost_cents": pre_fee_cost + loss_share_fee + expected_reimbursement,
    }


def award_candidate(institution):
    """The least-cost eligible bid, or ``None`` when every bid fails the test.

    A bid is eligible only at ``CONFORMING`` and only when its evaluated cost is
    *strictly* less than the liquidation baseline; equality is not least-costly.
    Ties break on the highest deposit premium, then the earliest ``created_at``.
    """
    baseline = institution["liquidation_baseline_cents"]
    eligible = [
        b
        for b in lookup.bids_of_institution(institution["id"])
        if b["status"] == "CONFORMING"
        and b["evaluated_cost_cents"] is not None
        and baseline is not None
        and b["evaluated_cost_cents"] < baseline
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda b: (
            b["evaluated_cost_cents"],
            -b["deposit_premium_bps"],
            b["created_at"],
            b["_seq"],
        )
    )
    return eligible[0]
