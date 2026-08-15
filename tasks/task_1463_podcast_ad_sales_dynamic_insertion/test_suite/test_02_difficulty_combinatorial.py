"""Difficulty queue A — combinatorial_formula (3 instances, 6 tests)."""

from test_helpers import (
    add_line_item,
    assert_invoice_invariants,
    create_agency,
    create_episode,
    create_invoice,
    create_show,
    end_campaign,
    get_invoice,
    get_show,
    ingest_downloads,
    list_make_goods_for_campaign,
    make_advertiser_headers,
    set_clock,
    setup_measured_delivery,
    setup_selling_scenario,
    transition_episode,
    transition_make_good,
    transition_show,
)


def _setup_forecast_tiers_show():
    """Show avg 10000; E1/E2 SCHEDULED inside the horizon, E3 outside, E4 walked
    to MEASURED via a clock detour so it is excluded by status."""
    show = create_show(title="Forecast FM", content_category="BUSINESS",
                       avg_downloads_30d=10000)
    create_episode(show["id"], title="E1", publish_at="2026-08-05T00:00:00Z",
                   measurement_window_days=30, slot_capacity=2)
    create_episode(show["id"], title="E2", publish_at="2026-08-20T00:00:00Z",
                   measurement_window_days=30, slot_capacity=2)
    create_episode(show["id"], title="E3", publish_at="2026-10-01T00:00:00Z",
                   measurement_window_days=30, slot_capacity=2)
    ep4 = create_episode(show["id"], title="E4", publish_at="2026-08-10T00:00:00Z",
                         measurement_window_days=1, slot_capacity=2)
    set_clock("2026-08-10T00:00:00Z")
    transition_episode(ep4["id"], "PUBLISH")
    set_clock("2026-08-12T00:00:00Z")
    transition_episode(ep4["id"], "FINALIZE_MEASUREMENT")
    set_clock("2026-08-01T00:00:00Z")
    return show


def _setup_rounding_campaign():
    """ACTUAL_DELIVERY campaign (booked 15, cpm 1000) with three
    episode-targeted line items: 7xPRE_ROLL on EPA, 7xPRE_ROLL on EPB,
    1xPOST_ROLL on EPC; all episodes MEASURED; campaign ENDED."""
    show = create_show(title="Rounding Radio", content_category="COMEDY",
                       avg_downloads_30d=10000)
    episodes = {}
    for name in ("EPA", "EPB", "EPC"):
        episodes[name] = create_episode(
            show["id"], title=name, publish_at="2026-08-01T00:00:00Z",
            measurement_window_days=30, slot_capacity=2,
        )
    ctx = setup_selling_scenario(
        with_episode=False, advertiser_name="RoundCo", category="CPG_FOOD",
        booked_impressions=15, cpm_cents=1000,
    )
    ctx["show"] = show
    line_items = {}
    for name, position, priority in (
        ("EPA", "PRE_ROLL", 10),
        ("EPB", "PRE_ROLL", 9),
        ("EPC", "POST_ROLL", 8),
    ):
        ctx["episode"] = episodes[name]
        line_items[name] = add_line_item(
            ctx, target="episode", position=position,
            reserved_impressions=100, priority=priority,
        )
    for name, count, prefix in (("EPA", 7, "PA"), ("EPB", 7, "PB"), ("EPC", 1, "PC")):
        transition_episode(episodes[name]["id"], "PUBLISH")
        ingest_downloads(episodes[name]["id"], prefix, count,
                         occurred_at="2026-08-05T00:00:00Z", user_agent_class="HUMAN")
    set_clock("2026-09-01T00:00:01Z")
    for name in ("EPA", "EPB", "EPC"):
        transition_episode(episodes[name]["id"], "FINALIZE_MEASUREMENT")
    end_campaign(ctx)
    ctx["line_items"] = line_items
    return ctx


def _setup_commission_chain():
    """Agency-represented advertiser (1500 bps); ACTUAL_DELIVERY campaign
    booked 1000 cpm 2000 with 800 measured deliveries; ENDED; invoice DRAFT
    with shortfall 200 and MakeGood OFFERED."""
    agency = create_agency(name="MediaBuy LLC", commission_bps=1500)
    ctx = setup_measured_delivery(
        booked_impressions=1000, cpm_cents=2000, billing_model="ACTUAL_DELIVERY",
        downloads=800, reserved_impressions=500, category="FINTECH",
        agency=agency, end_campaign_too=True, create_invoice_too=True,
    )
    assert ctx["make_good"] is not None, "Setup failed: expected an OFFERED MakeGood"
    return ctx


# =========================================================================
# inventory_forecast_tiered_conditional_inputs
# =========================================================================

def test_forecast_combines_baseline_eligible_count_and_clear_cap(api):
    """PRD §3.1: "Eligible episodes are those of the show whose `status` is `SCHEDULED` or `PUBLISHED` and whose `publish_at` falls inside the inclusive window from the current logical-clock instant to thirty days after it."
    PRD §3.1: "The forecast equals the floor of `avg_downloads_30d` multiplied by the count of eligible episodes multiplied by the tier's sell-through cap: 0.95 while `CLEAR`, 0.70 while `FLAGGED`, and 0.00 while `SUSPENDED`."

    Design: Difficulty/combinatorial_formula/inventory_forecast_tiered_conditional_inputs
    """
    show = _setup_forecast_tiers_show()
    show = get_show(show["id"])
    # E1 + E2 eligible; E3 outside the horizon; E4 MEASURED (status filter).
    assert show["brand_safety_tier"] == "CLEAR"
    assert show["forecast_impressions"] == 19000, (
        f"floor(10000 * 2 * 0.95) == 19000, got {show['forecast_impressions']}"
    )


def test_forecast_recomputed_with_flagged_cap_on_tier_transition(api):
    """PRD §3.1: "Every tier change recomputes the forecast with the new cap."
    PRD §3.1: "The forecast equals the floor of `avg_downloads_30d` multiplied by the count of eligible episodes multiplied by the tier's sell-through cap: 0.95 while `CLEAR`, 0.70 while `FLAGGED`, and 0.00 while `SUSPENDED`."

    Design: Difficulty/combinatorial_formula/inventory_forecast_tiered_conditional_inputs
    """
    show = _setup_forecast_tiers_show()
    flagged = transition_show(show["id"], "FLAGGED")
    assert flagged["brand_safety_tier"] == "FLAGGED"
    assert flagged["forecast_impressions"] == 14000, (
        f"floor(10000 * 2 * 0.70) == 14000, got {flagged['forecast_impressions']}"
    )
    # The same recomputation is visible on a follow-up read.
    reread = get_show(show["id"])
    assert reread["forecast_impressions"] == 14000


# =========================================================================
# invoice_per_line_rounding_then_sum
# =========================================================================

def test_invoice_rounds_each_line_half_up_then_sums(api):
    """PRD §3.7: "For each line item that produced at least one impression with `billable_final` true, the line's `billable_impressions` is that count, and its `line_cents` is computed by multiplying the line's billable impressions by the campaign's `cpm_cents` and by the position's per-mille multiplier (800 for `PRE_ROLL`, 1000 for `MID_ROLL`, 600 for `POST_ROLL`), dividing by one million, and rounding half-up to integer cents."
    PRD §3.7: "Rounding order is pinned: each line is rounded first, then the lines are summed."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
    """
    ctx = _setup_rounding_campaign()
    invoice = create_invoice(ctx["campaign"]["id"])
    by_line = {line["line_item_id"]: line for line in invoice["lines"]}
    assert len(by_line) == 3, f"Expected 3 frozen lines, got {len(by_line)}"
    li = ctx["line_items"]
    # 7 * 1000 * 800 / 1e6 = 5.6 -> 6 (each PRE_ROLL line)
    assert by_line[li["EPA"]["id"]]["line_cents"] == 6
    assert by_line[li["EPA"]["id"]]["billable_impressions"] == 7
    assert by_line[li["EPB"]["id"]]["line_cents"] == 6
    assert by_line[li["EPB"]["id"]]["billable_impressions"] == 7
    # 1 * 1000 * 600 / 1e6 = 0.6 -> 1 (POST_ROLL line)
    assert by_line[li["EPC"]["id"]]["line_cents"] == 1
    assert by_line[li["EPC"]["id"]]["billable_impressions"] == 1
    # Per-line-then-sum: 6 + 6 + 1 = 13 (sum-then-round would give 12).
    assert invoice["gross_cents"] == 13, (
        f"gross_cents must be 13 under per-line rounding, got {invoice['gross_cents']}"
    )


def test_invoice_full_delivery_has_zero_shortfall_and_no_makegood(api):
    """PRD §3.7: "`delivered_impressions_billed` is the sum of the per-line billable counts. `shortfall_impressions` is `booked_impressions` minus `delivered_impressions_billed`, floored at zero."
    PRD §3.7: "If `shortfall_impressions` is greater than zero at creation, the system automatically creates exactly one **MakeGood** for the campaign in `OFFERED` status"

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
    """
    ctx = _setup_rounding_campaign()
    invoice = create_invoice(ctx["campaign"]["id"])
    assert invoice["delivered_impressions_billed"] == 15
    assert invoice["shortfall_impressions"] == 0
    make_goods = list_make_goods_for_campaign(ctx["campaign"]["id"])
    assert make_goods == [], (
        f"No shortfall means no MakeGood, got {len(make_goods)}"
    )


# =========================================================================
# invoice_commission_pinned_evaluation_order
# =========================================================================

def test_decline_grants_credit_before_commission(api):
    """PRD §3.7: "Commission and credit follow a pinned evaluation order, each step using only earlier steps: first the delivered and shortfall figures, then `gross_cents`, then `make_good_credit_cents` — the half-up-rounded value of `shortfall_impressions` times `cpm_cents` divided by one thousand when a make-good of the campaign has been `DECLINED`, and zero otherwise"

    Design: Difficulty/combinatorial_formula/invoice_commission_pinned_evaluation_order
    """
    ctx = _setup_commission_chain()
    invoice = ctx["invoice"]
    assert invoice["gross_cents"] == 1600  # round_half_up(800 * 2000 * 1000 / 1000000)
    assert invoice["make_good_credit_cents"] == 0  # offer still OFFERED at creation
    transition_make_good(
        ctx["make_good"]["id"], "DECLINE",
        make_advertiser_headers(ctx["advertiser"]["id"]),
    )
    invoice = get_invoice(invoice["id"])
    # round_half_up(200 * 2000 / 1000) == 400
    assert invoice["make_good_credit_cents"] == 400, (
        f"Decline credit must be 400, got {invoice['make_good_credit_cents']}"
    )
    assert invoice["gross_cents"] == 1600


def test_commission_computed_on_post_credit_gross(api):
    """PRD §3.7: "then `agency_commission_cents`, the half-up-rounded value of `gross_cents` minus `make_good_credit_cents`, multiplied by the agency's `commission_bps` and divided by ten thousand, applied only when the advertiser has an `agency_id` (direct advertisers pay zero commission), and finally `net_cents` as `gross_cents` minus `agency_commission_cents` minus `make_good_credit_cents`."
    PRD §3.7: "The invariant `net_cents` plus `agency_commission_cents` plus `make_good_credit_cents` equals `gross_cents` always holds."

    Design: Difficulty/combinatorial_formula/invoice_commission_pinned_evaluation_order
    """
    ctx = _setup_commission_chain()
    transition_make_good(
        ctx["make_good"]["id"], "DECLINE",
        make_advertiser_headers(ctx["advertiser"]["id"]),
    )
    invoice = get_invoice(ctx["invoice"]["id"])
    # Commission on post-credit gross: round_half_up((1600 - 400) * 1500 / 10000)
    # == 180 (on gross alone it would be 240).
    assert invoice["agency_commission_cents"] == 180, (
        f"Commission must be 180 (post-credit), got {invoice['agency_commission_cents']}"
    )
    assert invoice["net_cents"] == 1020
    assert_invoice_invariants(invoice)
