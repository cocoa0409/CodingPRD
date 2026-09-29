"""Two edges of the money rules: the dynamic-pricing band probed from just below
and exactly at its threshold, and a settlement whose box office sold nothing at
all, driving the waterfall through zero and into negative territory.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    clear_presented_rider,
    confirm,
    finalize_settlement_as,
    negotiate_and_accept_fee,
    open_settlement,
    put_on_sale,
    read_box_office_statement,
    read_engagement,
    read_price_tier,
    reconcile_expenses,
    register_artist,
    register_hall,
    sell_tickets,
    set_clock,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["programming_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

ZERO_HOUSE_CONTROLLER_USER_ID = "user-finance-2"


def _on_sale_tier_of_one_hundred_seats_sixty_of_them_gone() -> dict:
    """A dynamically priced hundred-seat tier with exactly sixty seats sold, so the
    next sale is priced off a sell-through of exactly 0.6000."""
    space = register_hall()
    artist = register_artist(legal_name="Silverpine Songwriters",
                            guarantee_floor_cents=100_000,
                            historical_sell_through_pct=0.80,
                            min_days_between_engagements=0)
    engagement = book_presented_engagement(
        space["id"], artist["id"],
        title="Silverpine Songwriters in the Round",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    clear_presented_rider(engagement["id"], artist["id"],
                          submitted_rigging_kg=1_000, requested_power_amps=200,
                          requested_dmx_universes=1)
    tier = add_price_tier(engagement["id"], tier_name="ORCH",
                          seats_allocated=100, base_price_cents=8_000,
                          price_ceiling_cents=9_500,
                          dynamic_pricing_enabled=True,
                          subscription_eligible=False)
    negotiate_and_accept_fee(engagement["id"], artist["id"], 200_000, 0.10)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 26
    assert assessed["financial_clearance"] == "CLEARED"
    confirm(engagement["id"])
    put_on_sale(engagement["id"])
    bulk_sale = sell_tickets(tier["id"], 59, "WEB")
    below_band = sell_tickets(tier["id"], 1, "WEB")
    return {"engagement": engagement, "tier": tier,
            "bulk_sale": bulk_sale, "below_band": below_band}


def _reconciled_presented_settlement_with_no_sales_and_no_calls() -> dict:
    """A presented engagement taken on sale and settled without a single ticket
    sold and without a single crew call, its marketing reconciled at 50,000."""
    space = register_hall(name="Studio Theatre", seat_capacity=400,
                         base_facility_fee_cents=500_000,
                         load_in_day_fee_cents=200_000,
                         changeover_buffer_minutes=60,
                         rigging_capacity_kg=2_000, house_power_amps=200,
                         dmx_universes=2)
    artist = register_artist(legal_name="Nocturne Solo Piano",
                            agency_name="Southgate Booking",
                            guarantee_floor_cents=100_000,
                            historical_sell_through_pct=0.50,
                            min_days_between_engagements=0)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Nocturne: Late Night Piano",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    clear_presented_rider(engagement["id"], artist["id"],
                          submitted_rigging_kg=200, requested_power_amps=60,
                          requested_dmx_universes=1)
    tier = add_price_tier(engagement["id"], tier_name="GA",
                          seats_allocated=200, base_price_cents=5_000,
                          price_ceiling_cents=6_000,
                          dynamic_pricing_enabled=False,
                          subscription_eligible=False)
    negotiate_and_accept_fee(engagement["id"], artist["id"], 200_000, 0.10)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 33
    assert assessed["financial_clearance"] == "CLEARED"
    confirm(engagement["id"])
    put_on_sale(engagement["id"])
    set_clock("2026-10-03T00:00:00Z")
    settlement = open_settlement(engagement["id"])
    assert settlement["box_office_gross_cents"] == 0
    assert settlement["actual_labor_cents"] == 0
    return {"artist": artist, "engagement": engagement, "tier": tier,
            "settlement": settlement}


class TestDynamicPriceAtTheMidBandThreshold:

    def test_the_multiplier_lifts_at_the_band_edge_and_not_one_seat_earlier(self):
        """The sale made at a sell-through of 0.5900 is still priced at face value;
        the very next sale, made at exactly 0.6000, catches the middle band. The
        lifted price is rounded once and stays under the ceiling, so no clamp
        hides the multiplier.

        PRD: "Otherwise a sell-through of 0.85 or greater selects a multiplier of
        1.30, a sell-through of 0.60 or greater but below 0.85 selects 1.15, and
        anything below 0.60 selects 1.00; the band comparisons are inclusive at
        their lower bounds and are made against the four-decimal ratio."

        Design: Difficulty/boundary_precision_check/dynamic_ticket_price_at_exact_mid_band_ratio
        """
        scenario = _on_sale_tier_of_one_hundred_seats_sixty_of_them_gone()
        below = scenario["below_band"]
        assert below["sell_through_pct_at_sale"] == pytest.approx(0.59,
                                                                 abs=0.0001)
        assert below["dynamic_multiplier_applied"] == pytest.approx(1.00,
                                                                   abs=0.01)
        assert below["unit_price_cents"] == 8_000

        at_band = validate_success(api_client.create_ticket_sale(
            scenario["tier"]["id"], {"qty": 1, "channel": "PHONE"},
            BOX_OFFICE), expected_status=201)
        assert at_band["sell_through_pct_at_sale"] == pytest.approx(0.60,
                                                                   abs=0.0001)
        assert at_band["dynamic_multiplier_applied"] == pytest.approx(1.15,
                                                                     abs=0.01)
        assert at_band["unit_price_cents"] == 9_200
        assert at_band["gross_cents"] == 9_200
        assert at_band["restoration_fee_cents"] == 200
        assert at_band["status"] == "SOLD"

    def test_the_unit_price_is_rounded_once_and_then_multiplied_by_the_quantity(self):
        """The opening sale of fifty-nine seats is priced per seat and multiplied,
        so no rounding drift accumulates across the block. The tier's counters and
        the live statement then agree with the three sales that produced them,
        including the restoration charge the adjusted gross strips back out.

        PRD: "`gross_cents` is `unit_price_cents` multiplied by `qty`; the
        rounding happens once per unit price, never after the quantity
        multiplication."

        Design: Difficulty/boundary_precision_check/dynamic_ticket_price_at_exact_mid_band_ratio
        """
        scenario = _on_sale_tier_of_one_hundred_seats_sixty_of_them_gone()
        bulk = scenario["bulk_sale"]
        assert bulk["sell_through_pct_at_sale"] == pytest.approx(0.0,
                                                                abs=0.0001)
        assert bulk["unit_price_cents"] == 8_000
        assert bulk["gross_cents"] == 472_000
        assert bulk["restoration_fee_cents"] == 11_800

        sell_tickets(scenario["tier"]["id"], 1, "PHONE")

        tier_after = read_price_tier(scenario["tier"]["id"])
        assert tier_after["sold_qty"] == 61
        assert tier_after["gross_cents"] == 489_200
        assert tier_after["subscription_held_qty"] == 0
        assert tier_after["available_qty"] == 39

        assert read_engagement(scenario["engagement"]["id"])[
            "realized_gross_cents"] == 489_200

        statement = read_box_office_statement(scenario["engagement"]["id"])
        assert statement["sold_qty_total"] == 61
        assert statement["single_ticket_gross_cents"] == 489_200
        assert statement["restoration_fees_cents"] == 12_200
        assert statement["adjusted_gross_cents"] == 477_000


class TestSettlementOverAnEmptyHouse:

    def test_an_empty_box_office_clamps_the_overage_and_leaves_the_net_negative(self):
        """Nothing sold, so the box office aggregates to zero rather than to null:
        an adjusted gross of exactly zero selects the lowest expense band, the
        overage the artist would share in goes negative and is clamped away, and
        the center's net is allowed to stand below zero.

        PRD: "Step four computes the overage as the adjusted gross less
        `guarantee_cents` less `reimbursable_expenses_cents`, floored at zero,
        then writes `artist_share_cents` as the engagement's `artist_share_pct`
        multiplied by that overage, rounded half up."

        Design: Difficulty/boundary_precision_check/settlement_with_empty_box_office_and_negative_net_clamps
        """
        scenario = _reconciled_presented_settlement_with_no_sales_and_no_calls()

        reconciled = reconcile_expenses(scenario["settlement"]["id"], 50_000)
        assert reconciled["status"] == "EXPENSES_RECONCILED"
        assert reconciled["box_office_gross_cents"] == 0
        assert reconciled["restoration_fees_cents"] == 0
        assert reconciled["adjusted_gross_cents"] == 0
        assert reconciled["reimbursable_expense_cap_cents"] == 300_000
        assert reconciled["reimbursable_expenses_cents"] == 50_000
        assert reconciled["artist_share_cents"] == 0
        assert reconciled["net_to_center_cents"] == -250_000
        assert reconciled["reserve_contribution_cents"] == 0
        assert reconciled["amount_payable_to_artist_cents"] == 200_000

    def test_the_guarantee_is_paid_and_the_zero_movement_is_still_recorded(self):
        """Finalizing a failed night still pays the guarantee in full and still
        posts its reserve movement, even though that movement is zero, so the
        ledger remains a complete trail. The realized margin is the mirror image of
        the money that left the building.

        PRD: "Because the settlement produced a reserve contribution, a reserve
        entry of type `SETTLEMENT_CONTRIBUTION` is appended with `amount_cents`
        equal to the settlement's `reserve_contribution_cents` and a recomputed
        `balance_after_cents`."

        Design: Difficulty/boundary_precision_check/settlement_with_empty_box_office_and_negative_net_clamps
        """
        scenario = _reconciled_presented_settlement_with_no_sales_and_no_calls()
        engagement_id = scenario["engagement"]["id"]
        reconcile_expenses(scenario["settlement"]["id"], 50_000)

        finalized = finalize_settlement_as(scenario["settlement"]["id"],
                                           ZERO_HOUSE_CONTROLLER_USER_ID)
        assert finalized["status"] == "FINALIZED"
        assert finalized["amount_payable_to_artist_cents"] == 200_000

        entries, entries_meta = validate_paginated(
            api_client.list_engagement_reserve_ledger_entries(engagement_id,
                                                              FINANCE))
        assert entries_meta["total_count"] == 1
        assert entries[0]["entry_type"] == "SETTLEMENT_CONTRIBUTION"
        assert entries[0]["amount_cents"] == 0
        assert entries[0]["balance_after_cents"] == 0

        artist_after = validate_success(
            api_client.get_artist(scenario["artist"]["id"], DIRECTOR))
        assert artist_after["lifetime_guarantee_paid_cents"] == 200_000

        after = read_engagement(engagement_id)
        assert after["lifecycle_status"] == "SETTLED"
        assert after["realized_gross_cents"] == 0
        assert after["realized_margin_cents"] == -250_000

        statement = read_box_office_statement(engagement_id)
        assert statement["tier_count"] == 1
        assert statement["seats_allocated_total"] == 200
        assert statement["sold_qty_total"] == 0
        assert statement["box_office_gross_cents"] == 0
