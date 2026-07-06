"""Calculation tests: retainer churn proration, boost settlement cost,
collab settlement bonus, engagement rate.

Covers difficulty rules dual_variant_calc and combinatorial_formula plus the
corner calculations section.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_active_client, create_published_content,
    create_draft_boost, reserve_boost,
    setup_collab_with_cleared_assets, create_accepted_collab, add_cleared_assets,
    create_client, create_and_activate_package, create_live_channel,
)
from test_helpers import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


# ===========================================================================
# dual_variant_calc / retainer_churn_quote_forward_vs_chronological
# ===========================================================================
def test_churn_quote_forward_full_owes_whole_retainer(api):
    """PRD §3.7: "The forward-looking figure, `forward_full_cents`, treats the
    whole cycle's retainer as owed once the cycle has opened regardless of when
    churn happens, and so equals the client's `retainer_fee_cents` independent
    of usage."

    Design: Difficulty/dual_variant_calc/retainer_churn_quote_forward_vs_chronological
    """
    client, channel = setup_active_client(
        monthly_retainer_fee_cents=500000, monthly_post_quota=10, included_channels=3)
    cid = client["id"]
    for slot in ("2026-03-01T09:00:00Z", "2026-03-01T10:00:00Z", "2026-03-01T11:00:00Z"):
        create_published_content(cid, channel["id"], slot_start_utc=slot)

    quote = validate_success(api.get_churn_quote(cid, AM))
    assert quote["forward_full_cents"] == 500000, (
        f"forward_full must equal retainer_fee_cents 500000, got {quote['forward_full_cents']}")


def test_churn_quote_chronological_prorates_by_posts(api):
    """PRD §3.7: "The chronological figure, `chronological_prorated_cents`, scales
    the retainer by posts actually published this cycle against quota: it is the
    `retainer_fee_cents` multiplied by `posts_published_this_cycle`, divided by
    `monthly_post_quota`, rounded up to the next whole cent (ceiling)."

    Design: Difficulty/dual_variant_calc/retainer_churn_quote_forward_vs_chronological
    """
    client, channel = setup_active_client(
        monthly_retainer_fee_cents=500000, monthly_post_quota=10, included_channels=3)
    cid = client["id"]
    for slot in ("2026-03-01T09:00:00Z", "2026-03-01T10:00:00Z", "2026-03-01T11:00:00Z"):
        create_published_content(cid, channel["id"], slot_start_utc=slot)

    quote = validate_success(api.get_churn_quote(cid, AM))
    # ceil(500000 * 3 / 10) == 150000
    assert quote["chronological_prorated_cents"] == 150000, (
        f"expected 150000, got {quote['chronological_prorated_cents']}")
    assert quote["forward_full_cents"] != quote["chronological_prorated_cents"], (
        "the two variants must diverge for this client")


# ===========================================================================
# dual_variant_calc / boost_cost_provisional_reserved_vs_final_spent
# ===========================================================================
def test_boost_reserved_cost_is_full_reservation_while_running(api):
    """PRD §3.4: "While a campaign is `RESERVED` or `RUNNING`, its cost for
    budget-gating purposes is the full reservation — the whole locked
    `reserved_budget_cents` — because the committed cost the moment a campaign
    reserves is the entire reservation."

    Design: Difficulty/dual_variant_calc/boost_cost_provisional_reserved_vs_final_spent
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=300000, daily_cap_cents=200000,
                               duration_days=3)
    boost = reserve_boost(client["id"], boost["id"])
    boost = get_success_data(api.launch_boost_campaign(boost["id"], FC))
    get_success_data(api.record_spend_boost_campaign(boost["id"], {"amount_cents": 120000}, FC))

    running = validate_success(api.get_boost_campaign(boost["id"], FC))
    assert running["reserved_budget_cents"] == 300000, (
        f"reserved (while RUNNING) must be 300000, got {running['reserved_budget_cents']}")
    assert running["spent_budget_cents"] == 120000


def test_boost_final_spent_cost_diverges_and_reservation_clears_on_complete(api):
    """PRD §3.4: "At completion, settlement bills only what was actually recorded,
    clamped by both ceilings: the billable cost is the smallest of three figures
    — the recorded `spent_budget_cents`, the pacing ceiling given by
    `daily_cap_cents` multiplied by `days_elapsed`, and the reservation ceiling
    `reserved_budget_cents` — and whichever of the three is smallest is the one
    that binds."
    PRD §3.4: "the campaign's `reserved_budget_cents` is then set to zero and the
    client's `boost_reserved_cents`, `boost_spent_cents`, and
    `boost_available_cents` are recomputed."

    Design: Difficulty/dual_variant_calc/boost_cost_provisional_reserved_vs_final_spent
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=300000, daily_cap_cents=200000,
                               duration_days=3)
    boost = reserve_boost(client["id"], boost["id"])
    boost = get_success_data(api.launch_boost_campaign(boost["id"], FC))
    get_success_data(api.record_spend_boost_campaign(boost["id"], {"amount_cents": 120000}, FC))

    completed = validate_success(api.complete_boost_campaign(boost["id"], FC))
    # final_spent = min(120000, 200000*1, 300000) == 120000; differs from reserved 300000
    assert completed["spent_budget_cents"] == 120000, (
        f"spent must be 120000, got {completed['spent_budget_cents']}")
    assert completed["reserved_budget_cents"] == 0, (
        "reserved_budget_cents must be 0 after COMPLETED")


# ===========================================================================
# combinatorial_formula / collab_settlement_round_per_line_then_sum
# ===========================================================================
def test_collab_settlement_round_per_line_item_then_sum(api):
    """PRD §3.6: "The bonus is the floored five-percent per-unit value multiplied
    by the count of five-percent units, plus the floored ten-percent per-unit
    value multiplied by the count of ten-percent units; each per-unit bonus is
    floored before being multiplied by its unit count, and the two products are
    then summed — rounding is per line item and then summed, never summed and
    then rounded."

    Design: Difficulty/combinatorial_formula/collab_settlement_round_per_line_then_sum
    """
    client, collab, _assets = setup_collab_with_cleared_assets(
        offer_fee_cents=100000, deliverable_count=4, cleared_count=6)
    # per_deliverable_value=floor(100000/4)=25000; tier2_units=3, tier3_units=1
    # bonus = floor(25000*0.05)*3 + floor(25000*0.10)*1 = 1250*3 + 2500*1 = 6250
    # settlement = 100000 + 6250 = 106250
    quote = validate_success(api.get_settlement_quote(collab["id"], AM))
    assert quote["settlement_amount_cents"] == 106250, (
        f"expected 106250, got {quote['settlement_amount_cents']}")

    refreshed = validate_success(api.get_influencer_collab(collab["id"], AM))
    assert refreshed["approved_asset_count"] == 6


def test_collab_settlement_five_percent_tier_only(api):
    """PRD §3.6: "cleared deliverables three through five each earn a bonus of five
    percent of the per-deliverable value, taken as the floor of the per-deliverable
    value multiplied by 0.05".
    PRD §3.6: "the number of deliverables earning the five-percent rate is the
    smaller of the approved-asset count and 5, minus 2, but never below zero".

    Design: Difficulty/combinatorial_formula/collab_settlement_round_per_line_then_sum
    """
    # approved=3 isolates the 5% tier only: tier2_units = min(3,5)-2 = 1, tier3_units = 0.
    client, collab, _assets = setup_collab_with_cleared_assets(
        offer_fee_cents=100000, deliverable_count=4, cleared_count=3)
    # per_deliverable_value=floor(100000/4)=25000; bonus=floor(25000*0.05)*1=1250
    # settlement = 100000 + 1250 = 101250
    quote = validate_success(api.get_settlement_quote(collab["id"], AM))
    assert quote["settlement_amount_cents"] == 101250, (
        f"expected 101250, got {quote['settlement_amount_cents']}")


# ===========================================================================
# combinatorial_formula / boost_final_cost_nested_min_of_three_ceilings
# ===========================================================================
def test_boost_final_cost_spent_ceiling_binds(api):
    """PRD §3.4: "the billable cost is the smallest of three figures — the
    recorded `spent_budget_cents`, the pacing ceiling given by `daily_cap_cents`
    multiplied by `days_elapsed`, and the reservation ceiling
    `reserved_budget_cents` — and whichever of the three is smallest is the one
    that binds."

    Design: Difficulty/combinatorial_formula/boost_final_cost_nested_min_of_three_ceilings
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=300000, daily_cap_cents=100000,
                               duration_days=3)
    boost = reserve_boost(client["id"], boost["id"])
    boost = get_success_data(api.launch_boost_campaign(boost["id"], FC))
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 90000, "spend_day_index": 0}, FC))
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 90000, "spend_day_index": 1}, FC))

    running = validate_success(api.get_boost_campaign(boost["id"], FC))
    # min(spent=180000, daily_cap*days=100000*2=200000, reserved=300000) == 180000
    assert running["spent_budget_cents"] == 180000, (
        f"spent must be 180000, got {running['spent_budget_cents']}")
    assert running["days_elapsed"] == 2, (
        f"days_elapsed must be 2, got {running['days_elapsed']}")


def test_boost_final_cost_billed_spent_survives_completion(api):
    """PRD §3.4: "At completion, settlement bills only what was actually recorded,
    clamped by both ceilings: the billable cost is the smallest of three figures —
    the recorded `spent_budget_cents`, the pacing ceiling given by `daily_cap_cents`
    multiplied by `days_elapsed`, and the reservation ceiling `reserved_budget_cents`".

    Design: Difficulty/combinatorial_formula/boost_final_cost_nested_min_of_three_ceilings
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=300000, daily_cap_cents=100000,
                               duration_days=3)
    boost = reserve_boost(client["id"], boost["id"])
    boost = get_success_data(api.launch_boost_campaign(boost["id"], FC))
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 90000, "spend_day_index": 0}, FC))
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 90000, "spend_day_index": 1}, FC))

    completed = validate_success(api.complete_boost_campaign(boost["id"], FC))
    # min(spent=180000, daily_cap*days=200000, reserved=300000) == 180000; spent survives.
    assert completed["spent_budget_cents"] == 180000, (
        f"recorded spend 180000 must survive completion, got {completed['spent_budget_cents']}")
    assert completed["status"] == "COMPLETED", (
        f"campaign must be COMPLETED, got {completed['status']}")


# ===========================================================================
# corner calculations / engagement_rate correct result
# ===========================================================================
def test_engagement_rate_basis_points_multiply_before_divide(api):
    """PRD §3.7: "otherwise it is the total engagements multiplied by ten thousand
    and then divided by the total impressions, rounded half up to a whole number
    of basis points."

    Design: Corner/calculations/corner_engagement_rate_correct_result
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    snap = validate_success(
        api.create_analytics_snapshot(
            client["id"], {"total_impressions": 20000, "total_engagements": 350}, AM),
        expected_status=201)
    # round_half_up(350 * 10000 / 20000) == 175
    assert snap["engagement_rate_bps"] == 175, (
        f"expected 175, got {snap['engagement_rate_bps']}")


def test_engagement_rate_zero_impressions_defined_as_zero(api):
    """PRD §3.7: "When `total_impressions` is zero the engagement rate is defined
    as zero rather than a division by zero."

    Design: Corner/calculations/corner_engagement_rate_zero_impressions_edge
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    snap = validate_success(
        api.create_analytics_snapshot(
            client["id"], {"total_impressions": 0, "total_engagements": 100}, AM),
        expected_status=201)
    assert snap["engagement_rate_bps"] == 0, (
        f"zero impressions must yield 0 bps, got {snap['engagement_rate_bps']}")


def test_collab_settlement_no_bonus_at_tier2_floor(api):
    """PRD §3.6: "the first two cleared deliverables earn no bonus".
    PRD §3.6: "The settlement amount is the base plus that bonus, in exact integer cents."

    Design: Corner/calculations/corner_settlement_no_bonus_under_tier2_floor
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    collab = create_accepted_collab(
        client["id"], offer_fee_cents=100000, deliverable_count=4)
    add_cleared_assets(collab["id"], 2)  # approved_asset_count == 2, no bonus units
    quote = validate_success(api.get_settlement_quote(collab["id"], AM))
    assert quote["settlement_amount_cents"] == 100000, (
        f"with 2 cleared assets settlement == offer_fee 100000, got {quote['settlement_amount_cents']}")
