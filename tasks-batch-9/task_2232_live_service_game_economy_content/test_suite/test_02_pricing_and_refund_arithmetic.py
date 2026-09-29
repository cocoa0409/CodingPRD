"""Pinned rounding order in the personalized quote and pinned step order in refund settlement."""

from typing import Any, Dict, Tuple

from test_helpers import (
    COMPLIANCE,
    api_client,
    approve_offer,
    assert_offer,
    assert_refund_request,
    create_draft_offer,
    create_live_season,
    create_pending_purchase,
    create_player,
    make_player_headers,
    offer_line_item,
    open_account,
    publish_offer,
    read_offer,
    read_purchase,
    settle_purchase,
    submit_offer,
    submit_refund,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup helpers (state is rebuilt from scratch inside every test)
# ---------------------------------------------------------------------------
def _eu_player_and_two_line_bundle() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """LIVE season with a two-line BUNDLE at tier T3 (list 1798) and a European player whose
    retention band is HEALTHY. Returns (offer, player).
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p2_eu", region_code="EU")
    offer = create_draft_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="AUG_BUNDLE",
        price_tier="T3",
        list_price_minor=1798,
        line_items=[
            offer_line_item("COIN_PACK", 499, 700, "EVENT_TOKEN", 600),
            offer_line_item("SKIN_A", 1299, 1700, "EVENT_TOKEN", 600),
        ],
        personalization_discount_bp=1500,
        minor_purchasable=False,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    return offer, player


def _settled_5000_purchase_with_submitted_refund() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """LIVE season, a LIVE 5000-minor offer granting 5000 HARD_GEM, an adult NA player holding
    both a HARD_GEM and a SOFT_COIN account, one SETTLED purchase that consumed nothing, and a
    refund request in SUBMITTED. Returns (purchase, refund_request).
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p4", region_code="NA")
    open_account(player["id"], "HARD_GEM")
    open_account(player["id"], "SOFT_COIN")

    offer = create_draft_offer(
        season["id"],
        offer_type="LIMITED_TIME",
        sku="STARTER_5K",
        price_tier="T1",
        list_price_minor=5000,
        line_items=[offer_line_item("STARTER_PACK", 5000, 6000, "HARD_GEM", 5000)],
        personalization_discount_bp=0,
        minor_purchasable=True,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    publish_offer(offer["id"], season["id"])

    purchase = create_pending_purchase(player["id"], offer["id"])
    settled = settle_purchase(purchase["id"])
    request = submit_refund(purchase["id"], player["id"], "ACCIDENTAL")
    return settled, request


class TestBundleQuoteRoundsPerLine:
    """A two-line bundle quoted for a European buyer at tier T3."""

    def test_each_line_is_rounded_twice_before_the_net_lines_are_summed(self):
        """PRD §3.6: "Walking the offer's `line_items` in ascending line `sku` order, each line is priced in two rounded steps: the gross line is that line's `base_price_minor` multiplied by the region multiplier, divided by 10000, and rounded half up; the net line is that gross line multiplied by the quantity 10000 minus the tier discount minus the personalization discount, divided by 10000, and rounded half up again."
        PRD §3.6: "The quote is the sum of those net lines."
        PRD §3.6: "Summing the gross lines first and applying the discounts once to the total is forbidden and produces a different figure."
        PRD §3.6: "First, the region multiplier is selected from the buyer's `region_code`: North America is the reference at 10000 basis points, Europe is 11000, Latin America is 6500, and Asia-Pacific is 8500."
        PRD §3.6: "Second, the tier discount is selected from the offer's `price_tier`: `T1` discounts nothing, `T2` discounts 500 basis points, `T3` discounts 1200, and `T4` discounts 2000."
        PRD §3.6: "It takes the `player_id` being quoted and answers with the `offer_id`, that `player_id`, the `region_multiplier_bp` and `tier_discount_bp` that were selected, the `applied_personalization_bp`, the `retention_band` that was read, the resulting `quote_minor`, and a `line_breakdown` array showing the per-line arithmetic."

        Design: Difficulty/combinatorial_formula/bundle_quote_round_per_line_then_sum
        """
        offer, player = _eu_player_and_two_line_bundle()

        quote = validate_success(
            api_client.get_offer_quote(
                offer["id"],
                make_player_headers(player["id"]),
                params={"player_id": player["id"]},
            )
        )

        assert quote["offer_id"] == offer["id"], "The quote must name the offer it priced"
        assert quote["player_id"] == player["id"], "The quote must name the player it priced for"
        assert quote["region_multiplier_bp"] == 11000, (
            f"A European buyer selects 11000 bp, got {quote['region_multiplier_bp']}"
        )
        assert quote["tier_discount_bp"] == 1200, (
            f"Price tier T3 discounts 1200 bp, got {quote['tier_discount_bp']}"
        )
        assert quote["quote_minor"] == 1741, (
            "Per-line double rounding gives 483 + 1258 = 1741 minor units, got "
            f"{quote['quote_minor']}"
        )
        assert quote["quote_minor"] != 1740, (
            "1740 is the figure produced by collapsing both multipliers onto the 1798 summed "
            "base, which the pinned rounding order forbids"
        )

    def test_healthy_band_zeroes_the_personalization_discount_but_not_its_fairness_penalty(self):
        """PRD §3.6: "Third, the personalization discount applies only when the buyer's stored `retention_band` is exactly `AT_RISK`: in that case it is the offer's `personalization_discount_bp` capped at 1500 basis points, and in every other band — `HEALTHY` or `CHURN_RISK` — it is 0."
        PRD §3.6: "The personalization discount actually used is reported and stored as `applied_personalization_bp`."
        PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."
        PRD §3.5: "The personalization penalty is the offer's `personalization_discount_bp` divided by 5, rounded half up, then capped at 600 basis points."
        PRD §3.5: "The index is the value ratio minus all three penalties, then clamped into the range 0 through 15000 — negative results become 0 and results above 15000 become 15000."
        PRD §3.5: "The scarcity penalty looks at the length of the merchandising window in whole hours, taken as the difference between `window_end` and `window_start` divided by 3600 and truncated downward: a window of 72 hours or longer draws no penalty, a window of at least 24 hours but shorter than 72 draws 500 basis points, and anything shorter than 24 hours draws 1200."

        Design: Difficulty/combinatorial_formula/bundle_quote_round_per_line_then_sum
        """
        offer, player = _eu_player_and_two_line_bundle()

        quote = validate_success(
            api_client.get_offer_quote(
                offer["id"],
                make_player_headers(player["id"]),
                params={"player_id": player["id"]},
            )
        )

        assert quote["retention_band"] == "HEALTHY", (
            "A freshly provisioned player sits in the HEALTHY band, got "
            f"{quote['retention_band']}"
        )
        assert quote["applied_personalization_bp"] == 0, (
            "The offer's 1500 bp personalization discount must not apply outside the AT_RISK "
            f"band, got {quote['applied_personalization_bp']}"
        )

        stored_offer = read_offer(offer["id"])
        assert_offer(stored_offer)
        assert stored_offer["fairness_index_bp"] == 13048, (
            "2400 * 10000 / 1798 rounds to 13348 bp, less a 300 bp personalization penalty and "
            f"no window or minor-safety penalty, giving 13048, got {stored_offer['fairness_index_bp']}"
        )


class TestRefundFeeTierKeyedOnBase:
    """A 5000-minor refund whose restocking tier is keyed on the Step-two base."""

    def test_restocking_tier_reads_the_refund_base_and_not_the_final_amount(self):
        """PRD §3.7: "**Step one** computes `consumed_ratio_bp`: the purchase's `granted_consumed_minor` multiplied by 10000, divided by its `granted_total_minor` — or by 1 if that total is 0, so that a purchase which granted nothing does not divide by zero — rounded half up, then capped at 10000."
        PRD §3.7: "**Step two** computes `refund_base_minor`: the purchase's `price_paid_minor` multiplied by the quantity 10000 minus `consumed_ratio_bp`, divided by 10000, rounded half up."
        PRD §3.7: "**Step three** selects the restocking fee tier, and it is keyed on the Step-two figure and on nothing else: the tier is 0 basis points when `refund_base_minor` is strictly below 1000 minor units, 500 basis points when it is at least 1000 but strictly below 5000, and 1000 basis points at 5000 or above."
        PRD §3.7: "The tier must not be re-derived from the Step-five figure even though the fee is subtracted from the base."
        PRD §3.7: "**Step four** computes `restock_fee_minor`: `refund_base_minor` multiplied by that tier, divided by 10000, rounded half up."
        PRD §3.7: "**Step five** computes `refund_amount_minor`: `refund_base_minor` minus `restock_fee_minor`, floored at 0."

        Design: Difficulty/combinatorial_formula/refund_fee_tier_keyed_on_base_not_final
        """
        _purchase, request = _settled_5000_purchase_with_submitted_refund()

        decided = validate_success(
            api_client.decide_refund_request(
                request["id"],
                {
                    "decision": "APPROVE",
                    "decision_note": "Charged within minutes of an accidental tap",
                },
                COMPLIANCE,
            )
        )
        assert_refund_request(decided)

        assert decided["status"] == "APPROVED", (
            f"An approved decision must land the request in APPROVED, got {decided['status']}"
        )
        assert decided["consumed_ratio_bp"] == 0, (
            "Nothing granted has been consumed, so the consumed ratio must be 0 bp, got "
            f"{decided['consumed_ratio_bp']}"
        )
        assert decided["refund_base_minor"] == 5000, (
            "5000 * (10000 - 0) / 10000 must give a refund base of 5000, got "
            f"{decided['refund_base_minor']}"
        )
        assert decided["restock_fee_minor"] == 500, (
            "A base of exactly 5000 selects the 1000 bp tier, so the fee must be 500, got "
            f"{decided['restock_fee_minor']}"
        )
        assert decided["refund_amount_minor"] == 4500, (
            f"5000 minus a 500 fee must return 4500, got {decided['refund_amount_minor']}"
        )
        assert decided["refund_amount_minor"] != 4775, (
            "4775 is the figure produced by re-keying the tier on the Step-five output of 4500, "
            "which the pinned step order forbids"
        )

    def test_goodwill_credit_is_half_the_fee_and_the_purchase_stays_settled(self):
        """PRD §3.7: "**Step six** computes `goodwill_credit_minor`: half of the restocking fee — that is, `restock_fee_minor` multiplied by 5000, divided by 10000, rounded half up — but only when the player holds a currency account whose `currency_code` is `SOFT_COIN` and the player's `spend_state` is not `LOCKED`; when either condition fails the goodwill credit is 0."
        PRD §3.7: "Approving carries `SUBMITTED → APPROVED` and additionally requires the underlying purchase to still be `SETTLED`; it pins the settlement arithmetic as of the decision instant, and those pinned figures are reused verbatim at execution time."

        Design: Difficulty/combinatorial_formula/refund_fee_tier_keyed_on_base_not_final
        """
        purchase, request = _settled_5000_purchase_with_submitted_refund()

        decided = validate_success(
            api_client.decide_refund_request(
                request["id"],
                {
                    "decision": "APPROVE",
                    "decision_note": "Charged within minutes of an accidental tap",
                },
                COMPLIANCE,
            )
        )

        assert decided["goodwill_credit_minor"] == 250, (
            "Half of the 500 restocking fee must be credited to the SOFT_COIN holder, got "
            f"{decided['goodwill_credit_minor']}"
        )

        purchase_after = read_purchase(purchase["id"])
        assert purchase_after["status"] == "SETTLED", (
            "Approving a refund only pins the arithmetic; the purchase must stay SETTLED until "
            f"execution, got {purchase_after['status']}"
        )
