"""Pricing, dual-variant cost/payout calculations, and revenue settlement.

Covers difficulty rules dual_variant_calc, combinatorial_formula, plus corner
calculations and the reconcile derived-field reconciliation.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_advertiser_headers,
    TEST_USERS,
    setup_monetized_published_episode,
    create_publisher,
    create_active_show,
    create_published_ready_episode,
    create_advertiser_and_active_campaign,
    create_inserted_placement,
    deliver_placement,
    add_counted_downloads,
    set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ============================================================================
# Difficulty: dual_variant_calc / placement_estimated_vs_final_cost_diverge
# ============================================================================
class TestEstimatedVsFinalCost:
    def test_estimate_uses_forecast_impressions(self, api):
        """PRD §3.5: "The base is the campaign's bid_cpm_cents multiplied by forecast_impressions
        and divided by one thousand." with low fill band 1.00 and no premium:
        50000 * 5 / 1000 = 250.

        Design: Difficulty/dual_variant_calc/placement_estimated_vs_final_cost_diverge
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 2, "offered_positions": ["PRE_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100000, "bid_cpm_cents": 50000})
        placement = create_inserted_placement(
            advertiser, campaign, episode, forecast_impressions=5)
        assert placement["estimated_cost_cents"] == 250, (
            f"estimate should be 250, got {placement['estimated_cost_cents']}")

    def test_final_uses_delivered_impressions_and_diverges(self, api):
        """PRD §3.7: "The base is the campaign's bid_cpm_cents multiplied by delivered_impressions
        and divided by one thousand." with delivered 3 => 50000*3/1000 = 150, capped at the
        reserved estimate of 250: final 150 != estimate 250.

        Design: Difficulty/dual_variant_calc/placement_estimated_vs_final_cost_diverge
        """
        publisher, show, episode = setup_monetized_published_episode(
            episode_overrides={"total_ad_slots": 2, "offered_positions": ["PRE_ROLL"]})
        advertiser, campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100000, "bid_cpm_cents": 50000})
        placement = deliver_placement(
            advertiser, campaign, episode, forecast_impressions=5, delivered=3)
        assert placement["delivered_impressions"] == 3
        assert placement["estimated_cost_cents"] == 250
        assert placement["final_cost_cents"] == 150
        assert placement["final_cost_cents"] != placement["estimated_cost_cents"]


# ============================================================================
# Difficulty: dual_variant_calc / payout_accrued_vs_settled_diverge
# ============================================================================
class TestAccruedVsSettledPayout:
    def _build_two_publisher_placements(self):
        """Two DELIVERED placements (final 250 + 150) for one publisher in window
        [2026-03-01, 2026-04-01); campaign cA COMPLETED, campaign cB still ACTIVE."""
        set_clock("2026-03-10T00:00:00Z")
        publisher = create_publisher(revenue_share_pct=0.70)
        show = create_active_show(publisher, category="TECH", monetization_enabled=True)
        ep1 = create_published_ready_episode(
            publisher, show, total_ad_slots=1, offered_positions=["PRE_ROLL"])
        ep2 = create_published_ready_episode(
            publisher, show, total_ad_slots=1, offered_positions=["PRE_ROLL"])

        advertiser, campaign_a = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 100000, "bid_cpm_cents": 50000})
        adv_headers = make_advertiser_headers(advertiser["id"])
        # cA: delivered == forecast == 5 => final 250; then complete the campaign
        deliver_placement(advertiser, campaign_a, ep1, forecast_impressions=5, delivered=5,
                          event_at="2026-03-10T01:00:00Z", ip_prefix="a")
        get_success_data(api_client.complete_ad_campaign(campaign_a["id"], adv_headers))

        # cB: same advertiser, second ACTIVE (not completed) campaign; delivered 3 => final 150
        campaign_b = get_success_data(api_client.create_ad_campaign(
            {"advertiser_id": advertiser["id"], "name": "cB", "budget_cents": 100000,
             "bid_cpm_cents": 50000, "targeting_category": "TECH",
             "flight_start": "2026-01-01T00:00:00Z", "flight_end": "2026-12-31T00:00:00Z"},
            adv_headers))
        campaign_b = get_success_data(api_client.activate_ad_campaign(campaign_b["id"], adv_headers))
        deliver_placement(advertiser, campaign_b, ep2, forecast_impressions=5, delivered=3,
                          event_at="2026-03-10T02:00:00Z", ip_prefix="b")
        return publisher

    def test_accrued_net_counts_all_delivered(self, api):
        """PRD §3.8: "The accrued figure (net_payable_cents) counts every DELIVERED placement in
        the window regardless of campaign status". Gross 250+150=400, net=round(400*0.70)=280.

        Design: Difficulty/dual_variant_calc/payout_accrued_vs_settled_diverge
        """
        publisher = self._build_two_publisher_placements()
        statement = validate_success(api.create_payout_statement(
            {"publisher_id": publisher["id"], "period_start": "2026-03-01T00:00:00Z",
             "period_end": "2026-04-01T00:00:00Z"}, ADMIN), 201)
        assert statement["gross_revenue_cents"] == 400
        assert statement["net_payable_cents"] == 280

    def test_settled_counts_only_completed_campaign(self, api):
        """PRD §3.8: "a settled variant, settled_revenue_cents, which restricts the selection to
        only those selected placements whose funding campaign has reached COMPLETED": only the
        250-cent placement settles => round(250*0.70)=175 != accrued 280.

        Design: Difficulty/dual_variant_calc/payout_accrued_vs_settled_diverge
        """
        publisher = self._build_two_publisher_placements()
        statement = validate_success(api.create_payout_statement(
            {"publisher_id": publisher["id"], "period_start": "2026-03-01T00:00:00Z",
             "period_end": "2026-04-01T00:00:00Z"}, ADMIN), 201)
        assert statement["settled_revenue_cents"] == 175
        assert statement["net_payable_cents"] != statement["settled_revenue_cents"]


# ============================================================================
# Difficulty: combinatorial_formula / estimated_cost_tiered_premium_fillband_mode_a
# ============================================================================
class TestTieredPremiumFillBandCost:
    def _setup_episode_at_half_fill(self):
        """Episode total 2 offering PRE_ROLL+POST_ROLL, with one INSERTED placement so the
        episode fill_rate is 0.5000 (1 of 2 slots filled) before the trigger placement."""
        publisher = create_publisher()
        show = create_active_show(publisher, category="TECH", monetization_enabled=True)
        episode = create_published_ready_episode(
            publisher, show, total_ad_slots=2, offered_positions=["PRE_ROLL", "POST_ROLL"])
        advertiser, fill_campaign = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        create_inserted_placement(advertiser, fill_campaign, episode,
                                  position="PRE_ROLL", forecast_impressions=5)
        return publisher, show, episode, advertiser

    def test_episode_at_mid_fill_band(self, api):
        """PRD §3.2: "fill_rate is the ratio of filled slots to total slots, carried to four
        decimal places" — one INSERTED placement on a 2-slot episode yields fill_rate 0.5.

        Design: Difficulty/combinatorial_formula/estimated_cost_tiered_premium_fillband_mode_a
        """
        publisher, show, episode, advertiser = self._setup_episode_at_half_fill()
        ep = validate_success(api.get_episode(episode["id"], TEST_USERS["publisher_headers"]), 200)
        assert ep["fill_rate"] == 0.5

    def test_estimate_combines_premium_and_mid_fill_tier(self, api):
        """PRD §3.5: "A premium multiplier of 1.25 applies when the campaign's premium_targeting
        is true" and "a fill rate of at least 0.50 but below 0.80 selects the mid band of 1.10":
        base 40000*4/1000=160, *1.25 premium, *1.10 mid tier => round(220.0)=220.

        Design: Difficulty/combinatorial_formula/estimated_cost_tiered_premium_fillband_mode_a
        """
        publisher, show, episode, advertiser = self._setup_episode_at_half_fill()
        adv_headers = make_advertiser_headers(advertiser["id"])
        trigger_campaign = get_success_data(api.create_ad_campaign(
            {"advertiser_id": advertiser["id"], "name": "cT", "budget_cents": 1_000_000,
             "bid_cpm_cents": 40000, "targeting_category": "TECH", "premium_targeting": True,
             "flight_start": "2026-01-01T00:00:00Z", "flight_end": "2026-12-31T00:00:00Z"},
            adv_headers))
        trigger_campaign = get_success_data(api.activate_ad_campaign(trigger_campaign["id"], adv_headers))
        version = get_success_data(api.get_ad_campaign(trigger_campaign["id"], adv_headers))["version"]
        placement = validate_success(api.create_ad_placement(
            {"campaign_id": trigger_campaign["id"], "episode_id": episode["id"],
             "position": "POST_ROLL", "ad_duration_ms": 30000, "forecast_impressions": 4,
             "expected_campaign_version": version}, adv_headers), 201)
        assert placement["estimated_cost_cents"] == 220


# ============================================================================
# Difficulty: combinatorial_formula / payout_rounding_order_per_placement_then_sum_mode_b
# ============================================================================
class TestPayoutRoundingOrder:
    def _build_two_low_tier_deliveries(self):
        """Two DELIVERED placements final 250 and 150 for one publisher in window
        [2026-05-01, 2026-06-01) at clock 2026-05-15."""
        set_clock("2026-05-15T00:00:00Z")
        publisher = create_publisher(revenue_share_pct=0.70)
        show = create_active_show(publisher, category="TECH", monetization_enabled=True)
        ep1 = create_published_ready_episode(
            publisher, show, total_ad_slots=1, offered_positions=["PRE_ROLL"])
        ep2 = create_published_ready_episode(
            publisher, show, total_ad_slots=1, offered_positions=["PRE_ROLL"])
        advertiser, c1 = create_advertiser_and_active_campaign(
            campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
        deliver_placement(advertiser, c1, ep1, forecast_impressions=5, delivered=5,
                          event_at="2026-05-15T01:00:00Z", ip_prefix="r1")
        adv_headers = make_advertiser_headers(advertiser["id"])
        c2 = get_success_data(api_client.create_ad_campaign(
            {"advertiser_id": advertiser["id"], "name": "cR2", "budget_cents": 1_000_000,
             "bid_cpm_cents": 50000, "targeting_category": "TECH",
             "flight_start": "2026-01-01T00:00:00Z", "flight_end": "2026-12-31T00:00:00Z"},
            adv_headers))
        c2 = get_success_data(api_client.activate_ad_campaign(c2["id"], adv_headers))
        deliver_placement(advertiser, c2, ep2, forecast_impressions=5, delivered=3,
                          event_at="2026-05-15T02:00:00Z", ip_prefix="r2")
        return publisher

    def test_gross_is_sum_of_per_placement_integers(self, api):
        """PRD §3.8: "Because each placement's final_cost_cents is already an integer rounded at
        reconcile time, the gross is a straight sum of those per-placement integers": 250+150=400.

        Design: Difficulty/combinatorial_formula/payout_rounding_order_per_placement_then_sum_mode_b
        """
        publisher = self._build_two_low_tier_deliveries()
        statement = validate_success(api.create_payout_statement(
            {"publisher_id": publisher["id"], "period_start": "2026-05-01T00:00:00Z",
             "period_end": "2026-06-01T00:00:00Z"}, ADMIN), 201)
        assert statement["gross_revenue_cents"] == 400

    def test_net_rounded_once_and_fee_is_residual(self, api):
        """PRD §3.8: "net_payable_cents is the gross multiplied by the publisher's
        revenue_share_pct, rounded half up once after the product. The platform_fee_cents is gross
        minus net, computed as a residual so that net and fee always sum exactly to gross":
        net=round(400*0.70)=280, fee=400-280=120, and gross == net + fee.

        Design: Difficulty/combinatorial_formula/payout_rounding_order_per_placement_then_sum_mode_b
        """
        publisher = self._build_two_low_tier_deliveries()
        statement = validate_success(api.create_payout_statement(
            {"publisher_id": publisher["id"], "period_start": "2026-05-01T00:00:00Z",
             "period_end": "2026-06-01T00:00:00Z"}, ADMIN), 201)
        assert statement["net_payable_cents"] == 280
        assert statement["platform_fee_cents"] == 120
        assert statement["gross_revenue_cents"] == (
            statement["net_payable_cents"] + statement["platform_fee_cents"])


# ============================================================================
# Corner: calculations / download_below_iab_min_bytes_not_counted
# ============================================================================
def test_download_below_iab_min_not_counted(api):
    """PRD §3.7: "the system sets the computed counted flag to true exactly when bytes_served is
    at least the IAB minimum of 1,048,576 bytes (one mebibyte); the comparison is inclusive at
    that threshold." 1048575 bytes is one below => counted false, no delivered increment.

    Design: Corner/calculations/download_below_iab_min_bytes_not_counted
    """
    publisher, show, episode = setup_monetized_published_episode()
    # PUBLIC feed so there is no private-access gate on the download.
    from test_helpers import create_feed
    create_feed(publisher, show, visibility="PUBLIC")
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    placement = create_inserted_placement(advertiser, campaign, episode, forecast_impressions=5)
    event = validate_success(api.create_download_event(
        {"episode_id": episode["id"], "placement_id": placement["id"],
         "client_ip_hash": "iab1", "user_agent": "ua", "bytes_served": 1048575,
         "event_at": "2026-01-01T05:00:00Z"}, ADMIN), 201)
    assert event["counted"] is False
    adv_headers = make_advertiser_headers(advertiser["id"])
    refreshed = validate_success(api.get_ad_placement(placement["id"], adv_headers), 200)
    assert refreshed["delivered_impressions"] == 0


# ============================================================================
# Corner: calculations / estimated_cost_floors_at_min_placement_cents
# ============================================================================
def test_estimated_cost_floors_at_min_placement_cents(api):
    """PRD §3.5: "estimated_cost_cents is the larger of the placement floor of 100 cents and that
    raw cost rounded half up to whole cents." bid_cpm 1000 * forecast 1 / 1000 = 1 (raw) floors
    at 100.

    Design: Corner/calculations/estimated_cost_floors_at_min_placement_cents
    """
    publisher, show, episode = setup_monetized_published_episode()
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 1000})
    adv_headers = make_advertiser_headers(advertiser["id"])
    version = get_success_data(api.get_ad_campaign(campaign["id"], adv_headers))["version"]
    placement = validate_success(api.create_ad_placement(
        {"campaign_id": campaign["id"], "episode_id": episode["id"], "position": "PRE_ROLL",
         "ad_duration_ms": 30000, "forecast_impressions": 1,
         "expected_campaign_version": version}, adv_headers), 201)
    assert placement["estimated_cost_cents"] == 100


# ============================================================================
# Corner: cross_cutting_complexity_layers / reconcile_moves_reserve_to_spent_derived_reconciliation
# ============================================================================
def test_reconcile_moves_reserve_to_spent(api):
    """PRD §3.7: "On reconciliation the campaign's reserved_budget_cents decreases by
    estimated_cost_cents, its spent_budget_cents increases by final_cost_cents, and
    available_budget_cents is recomputed". budget 1000000, est 250, final 150 (delivered 3) =>
    reserved 0, spent 150, available 999850.

    Design: Corner/cross_cutting_complexity_layers/reconcile_moves_reserve_to_spent_derived_reconciliation
    """
    publisher, show, episode = setup_monetized_published_episode()
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    adv_headers = make_advertiser_headers(advertiser["id"])
    placement = deliver_placement(advertiser, campaign, episode,
                                  forecast_impressions=5, delivered=3, ip_prefix="rec")
    assert placement["final_cost_cents"] == 150
    refreshed = validate_success(api.get_ad_campaign(campaign["id"], adv_headers), 200)
    assert refreshed["reserved_budget_cents"] == 0
    assert refreshed["spent_budget_cents"] == 150
    assert refreshed["available_budget_cents"] == 999850
