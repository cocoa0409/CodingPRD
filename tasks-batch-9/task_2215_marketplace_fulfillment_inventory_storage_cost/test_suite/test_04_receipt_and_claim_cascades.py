"""Four-link cascades from a single write: the short-receipt cascade that erodes the
restock limit, and the claim-approval cascade that restores it."""
from test_helpers import (
    api_client,
    decide_claim,
    file_claim,
    newest_quota,
    read_fulfillment_center,
    read_listing,
    read_lot,
    read_plan,
    read_seller,
    setup_partially_received_plan,
    validate_paginated,
)

# A quota whose four performance inputs score exactly 545 before any penalty.
MID_SCORING_QUOTA = {
    "sell_through_rate": 1.2500,
    "excess_units_ratio": 0.1500,
    "stranded_ratio": 0.0500,
    "in_stock_rate": 0.8000,
}


def _nothing_arrived() -> dict:
    """A 600-unit shipment received with zero units, opening the whole shortfall."""
    return setup_partially_received_plan(600, 0, quota=dict(MID_SCORING_QUOTA))


def _lost_inbound_claim_for_the_whole_shortfall() -> dict:
    ctx = _nothing_arrived()
    ctx["claim"] = file_claim(
        ctx["lot_id"], ctx["seller_id"], "LOST_INBOUND", 600, 2,
        evidence_reference="LOST-77",
    )
    return ctx


class TestPartialReceiptCascade:
    """One receive call writes the shortfall, opens the discrepancy, suppresses the
    listing and re-scores the quota."""

    def test_link_one_writes_the_plan_and_line_shortfall(self):
        """A receipt crediting zero units lands the plan in PARTIALLY_RECEIVED carrying its
        full 600-unit shortfall on both the plan and its line.

        PRD 3.5: "The first link is the crediting itself, together with shortfall
        arithmetic: the plan's `missing_units` becomes its `declared_units` minus its
        `received_units`, and each line's `shortfall_units` becomes that line's declared
        `units` minus its accumulated `received_units`."

        Design: Difficulty/transitive_cascade/partial_receipt_cascade_depth_four_shortfall_to_quota_downgrade
        """
        ctx = _nothing_arrived()
        assert ctx["receipt"]["status"] == "PARTIALLY_RECEIVED"
        assert ctx["receipt"]["missing_units"] == 600

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["received_units"] == 0
        assert plan["declared_units"] == 600

        lines, _meta = validate_paginated(
            api_client.list_plan_line_items(plan["id"], ctx["seller_headers"])
        )
        assert lines[0]["shortfall_units"] == 600

    def test_links_two_and_three_open_the_discrepancy_and_suppress_the_listing(self):
        """The shortfall moves onto the lot as `missing_units` with a stamped
        `discrepancy_opened_at`, and the listing goes dark for MISSING_INVENTORY.

        PRD 3.5: "The second link, caused by the first, is discrepancy opening: every lot
        that absorbed a short line has that line's `shortfall_units` added to the lot's
        `missing_units`, its `reconciliation_status` moved from `RECONCILED` to
        `DISCREPANCY_OPEN`, and its `discrepancy_opened_at` stamped with the logical clock's
        current instant — this instant is the anchor of the `LOST_INBOUND` filing deadline —
        while the seller's `open_discrepancy_units` increases by the total shortfall."
        PRD 3.5: "The third link, caused by the second, is listing health: each affected
        listing is recomputed and may become `SUPPRESSED` with `suppression_reason` of
        `MISSING_INVENTORY` and `inventory_health` of `OUT_OF_STOCK` or `STRANDED`, updating
        the seller's `suppressed_listing_count`."

        Design: Difficulty/transitive_cascade/partial_receipt_cascade_depth_four_shortfall_to_quota_downgrade
        """
        ctx = _nothing_arrived()
        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["missing_units"] == 600
        assert lot["units_received_total"] == 0
        assert lot["fulfillable_units"] == 0
        assert lot["reconciliation_status"] == "DISCREPANCY_OPEN"
        assert lot["discrepancy_opened_at"].startswith("2026-08-01T00:00:00")

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["listing_status"] == "SUPPRESSED"
        assert listing["suppression_reason"] == "MISSING_INVENTORY"
        assert listing["inventory_health"] == "OUT_OF_STOCK"

        seller = read_seller(ctx["seller_id"])
        assert seller["open_discrepancy_units"] == 600
        assert seller["suppressed_listing_count"] == 1

    def test_link_four_re_scores_the_quota_from_545_down_to_495(self):
        """Crossing the 500-unit discrepancy threshold costs 50 points, which drops the
        tier to TIER_RESTRICTED and the restock limit from 1500 to 500.

        PRD 3.5: "The fourth link, caused by the second link's change to the seller's
        `open_discrepancy_units`, is quota re-scoring: the inventory performance score is
        re-run on the seller's active quota period, which may lower `iprs_score`,
        `base_capacity_tier`, `capacity_tier` and `restock_limit_units`, and may set
        `seller_status` to `SUSPENDED`."
        PRD 3.1: "A discrepancy penalty of 50 points applies when the owning seller's
        `open_discrepancy_units` is strictly greater than 500 units."

        Design: Difficulty/transitive_cascade/partial_receipt_cascade_depth_four_shortfall_to_quota_downgrade
        """
        ctx = _nothing_arrived()
        assert ctx["quota"]["iprs_score"] == 545
        assert ctx["quota"]["restock_limit_units"] == 1500

        quota = newest_quota(ctx["seller_id"])
        assert quota["iprs_score"] == 495
        assert quota["base_capacity_tier"] == "TIER_RESTRICTED"
        assert quota["capacity_tier"] == "TIER_RESTRICTED"
        assert quota["restock_limit_units"] == 500
        assert quota["utilized_units"] == 600

        # A partially received plan stays inside the reserving set.
        assert read_seller(ctx["seller_id"])["seller_status"] == "ACTIVE"
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 600
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 600


class TestClaimApprovalCascade:
    """One decide call credits the seller, closes the lot discrepancy, recomputes the
    listing and restores the restock limit."""

    def test_approval_credits_the_seller_with_the_settled_amount(self):
        """600 eligible units at the listing's 1250-cent unit cost and the LOST_INBOUND
        factor of 1.00 settle at 750000 cents.

        PRD 3.8: "The first link writes `eligible_units`, sets `approved_units` equal to
        `eligible_units`, writes `reimbursement_amount_cents`, stamps `decided_at` with the
        logical clock's current instant, and increases the seller's
        `reimbursement_credit_cents` by the reimbursed amount."
        PRD 3.8: "`reimbursement_amount_cents` is the product of `eligible_units`, the
        per-unit value and the type factor, with round half up applied once to that whole
        product."

        Design: Difficulty/transitive_cascade/claim_approval_cascade_depth_four_credit_to_quota_restoration
        """
        ctx = _lost_inbound_claim_for_the_whole_shortfall()
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["reconciliation_status"] == (
            "DISCREPANCY_CLAIMED"
        )

        decided = decide_claim(
            ctx["claim"]["id"], "APPROVED", decision_note="carrier confirmed loss"
        )
        assert decided["status"] == "APPROVED"
        assert decided["eligible_units"] == 600
        assert decided["approved_units"] == 600
        assert decided["reimbursement_amount_cents"] == 750000
        assert decided["decided_at"].startswith("2026-08-01T00:00:00")
        assert read_seller(ctx["seller_id"])["reimbursement_credit_cents"] == 750000

    def test_approval_clears_the_lot_shortfall_and_re_derives_the_listing(self):
        """The approved units leave the lot's `missing_units`, which resolves the
        reconciliation dimension and re-pins the suppression reason to ZERO_FULFILLABLE.

        PRD 3.8: "The second link, caused by the first, decrements the claimed pool on the
        lot: `approved_units` is subtracted from the lot's `missing_units` for a
        `LOST_INBOUND` claim, from its `unfulfillable_units` for a `DAMAGED_WAREHOUSE`
        claim, or from its `units_removed` for a `LOST_REMOVAL` claim; when the lot's
        `missing_units` reaches 0 the reconciliation dimension moves `DISCREPANCY_CLAIMED →
        DISCREPANCY_RESOLVED`, and the seller's `open_discrepancy_units` drops by the same
        amount."
        PRD 3.8: "The third link, caused by the second, recomputes the listing:
        `fulfillable_units`, `unfulfillable_units`, `missing_units`, `inventory_health` and
        `suppression_reason` are all re-derived."

        Design: Difficulty/transitive_cascade/claim_approval_cascade_depth_four_credit_to_quota_restoration
        """
        ctx = _lost_inbound_claim_for_the_whole_shortfall()
        decide_claim(
            ctx["claim"]["id"], "APPROVED", decision_note="carrier confirmed loss"
        )

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["missing_units"] == 0
        assert lot["reconciliation_status"] == "DISCREPANCY_RESOLVED"
        assert lot["lot_status"] == "ACTIVE"
        assert read_seller(ctx["seller_id"])["open_discrepancy_units"] == 0

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["missing_units"] == 0
        assert listing["listing_status"] == "SUPPRESSED"
        assert listing["suppression_reason"] == "ZERO_FULFILLABLE"
        assert listing["inventory_health"] == "OUT_OF_STOCK"

    def test_approval_restores_the_quota_score_and_restock_limit(self):
        """With the discrepancy back below the 500-unit threshold the penalty lifts, so the
        score returns to 545 and the limit to 1500.

        PRD 3.8: "The fourth link, caused by the second link's change to the seller's
        `open_discrepancy_units`, re-runs the inventory performance score on the seller's
        quota period whose `status` is `ACTIVE`, refreshing `iprs_score`, `capacity_tier`
        and `restock_limit_units`."
        PRD 3.1: "The effective tier selects a multiplier — 3.0 for `TIER_ELEVATED`, 1.5 for
        `TIER_STANDARD`, 0.5 for `TIER_RESTRICTED` — and `restock_limit_units` is the floor
        of `base_capacity_units` multiplied by that multiplier."

        Design: Difficulty/transitive_cascade/claim_approval_cascade_depth_four_credit_to_quota_restoration
        """
        ctx = _lost_inbound_claim_for_the_whole_shortfall()
        assert newest_quota(ctx["seller_id"])["restock_limit_units"] == 500

        decide_claim(
            ctx["claim"]["id"], "APPROVED", decision_note="carrier confirmed loss"
        )
        quota = newest_quota(ctx["seller_id"])
        assert quota["iprs_score"] == 545
        assert quota["capacity_tier"] == "TIER_STANDARD"
        assert quota["restock_limit_units"] == 1500
