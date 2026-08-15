"""Difficulty queue A — transitive_cascade (2 instances, 4 tests)."""

from test_helpers import (
    ADOPS,
    add_line_item,
    deliver_downloads,
    get_campaign,
    get_episode,
    get_line_item,
    get_show,
    publish_episode,
    set_clock,
    setup_selling_scenario,
    transition_advertiser,
    transition_episode,
    validate_paginated,
)


def _setup_suspension_cascade():
    """Show (avg 10000, one episode in horizon -> forecast 9500) with an ACTIVE
    campaign and an ACTIVE run-of-show line item reserving 1000."""
    ctx = setup_selling_scenario(
        advertiser_name="CascadeCo", category="FINTECH", booked_impressions=1000,
        cpm_cents=1000, content_category="NEWS", show_avg=10000,
        episode_publish_at="2026-08-05T00:00:00Z",
    )
    ctx["line_item"] = add_line_item(ctx, target="show", position="MID_ROLL",
                                     reserved_impressions=1000, priority=10)
    return ctx


def _setup_finalize_cascade():
    """ACTIVE campaign (booked 10) with ACTIVE run-of-show line item; PUBLISHED
    episode carrying 5 HUMAN downloads; clock advanced past the window close.
    Captures the campaign's delivered_impressions before finalization."""
    ctx = setup_selling_scenario(
        advertiser_name="FinCo", category="HEALTH_PHARMA", booked_impressions=10,
        cpm_cents=1000, content_category="HEALTH", show_avg=10000,
        episode_publish_at="2026-08-01T00:00:00Z",
    )
    ctx["line_item"] = add_line_item(ctx, target="show", position="MID_ROLL",
                                     reserved_impressions=10, priority=10)
    publish_episode(ctx)
    deliver_downloads(ctx, 5, prefix="D")
    ctx["pre_delivered"] = get_campaign(ctx["campaign"]["id"])["delivered_impressions"]
    set_clock("2026-09-01T00:00:01Z")
    return ctx


# =========================================================================
# advertiser_suspension_three_level_cascade
# =========================================================================

def test_suspend_cascades_campaign_line_item_and_show_pool(api):
    """PRD §3.2: "Suspension cascades: every campaign of the advertiser in `ACTIVE` moves to `PAUSED`, every `ACTIVE` line item of each such campaign moves to `PAUSED` with its show-pool reservation released, and each affected show's `reserved_impressions` and `available_impressions` are recomputed."

    Design: Difficulty/transitive_cascade/advertiser_suspension_three_level_cascade
    """
    ctx = _setup_suspension_cascade()
    transition_advertiser(ctx["advertiser"]["id"], "SUSPEND")
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["status"] == "PAUSED", (
        f"Campaign must be PAUSED after advertiser suspension, got {campaign['status']}"
    )
    line_item = get_line_item(ctx["line_item"]["id"])
    assert line_item["status"] == "PAUSED", (
        f"Line item must be PAUSED by the cascade, got {line_item['status']}"
    )
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 0, (
        f"Reservation must be released, got {show['reserved_impressions']}"
    )
    assert show["forecast_impressions"] == 9500
    assert show["available_impressions"] == 9500


def test_reinstate_does_not_unwind_the_cascade(api):
    """PRD §3.2: "Reinstatement moves the advertiser `SUSPENDED → ACTIVE` but resumes nothing — paused campaigns and line items stay paused until individually reactivated."

    Design: Difficulty/transitive_cascade/advertiser_suspension_three_level_cascade
    """
    ctx = _setup_suspension_cascade()
    transition_advertiser(ctx["advertiser"]["id"], "SUSPEND")
    reinstated = transition_advertiser(ctx["advertiser"]["id"], "REINSTATE")
    assert reinstated["status"] == "ACTIVE"
    campaign = get_campaign(ctx["campaign"]["id"])
    line_item = get_line_item(ctx["line_item"]["id"])
    assert campaign["status"] == "PAUSED", (
        f"Reinstatement must not resume the campaign, got {campaign['status']}"
    )
    assert line_item["status"] == "PAUSED", (
        f"Reinstatement must not resume the line item, got {line_item['status']}"
    )


# =========================================================================
# finalize_measurement_delivery_cascade
# =========================================================================

def test_delivered_counter_is_zero_until_finalize_then_counts_final(api):
    """PRD §3.2: "A campaign's `delivered_impressions` is always the count of its impressions whose `billable_final` is true; an impression is only ever created when its download's `occurred_at` lies inside the campaign's half-open flight, so the delivered count never includes out-of-flight serves."
    PRD §3.1: "it sets `qualified_final` on every download of the episode, stores the count of qualifying downloads in `measured_download_count`, cascades `billable_final` onto every impression those downloads carried, recomputes `delivered_impressions` on every campaign that served into the episode, and recomputes the show's forecast since `MEASURED` episodes leave the eligible set."

    Design: Difficulty/transitive_cascade/finalize_measurement_delivery_cascade
    """
    ctx = _setup_finalize_cascade()
    # Five impressions already exist, but billable_final is still null
    # everywhere, so the stored counter is 0.
    assert ctx["pre_delivered"] == 0, (
        f"Before finalize delivered_impressions must be 0, got {ctx['pre_delivered']}"
    )
    transition_episode(ctx["episode"]["id"], "FINALIZE_MEASUREMENT")
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["delivered_impressions"] == 5, (
        f"After finalize delivered_impressions must be 5, "
        f"got {campaign['delivered_impressions']}"
    )


def test_finalize_sets_qualified_final_and_billable_final(api):
    """PRD §2.9: "Per-download `qualified_final` and per-impression `billable_final` stay null until that moment."
    PRD §3.1: "it sets `qualified_final` on every download of the episode, stores the count of qualifying downloads in `measured_download_count`, cascades `billable_final` onto every impression those downloads carried, recomputes `delivered_impressions` on every campaign that served into the episode, and recomputes the show's forecast since `MEASURED` episodes leave the eligible set."

    Design: Difficulty/transitive_cascade/finalize_measurement_delivery_cascade
    """
    ctx = _setup_finalize_cascade()
    transition_episode(ctx["episode"]["id"], "FINALIZE_MEASUREMENT")
    downloads, dmeta = validate_paginated(
        api.list_episode_downloads(ctx["episode"]["id"], ADOPS, params={"limit": 100})
    )
    assert dmeta["total_count"] == 5
    assert all(d["qualified_final"] is True for d in downloads), (
        "Every HUMAN in-window download must end with qualified_final == true"
    )
    impressions, imeta = validate_paginated(
        api.list_impressions(ADOPS, params={"campaign_id": ctx["campaign"]["id"],
                                            "limit": 100})
    )
    assert imeta["total_count"] == 5
    assert all(i["billable_final"] is True for i in impressions), (
        "The finalize cascade must write billable_final == true on each impression"
    )
    episode = get_episode(ctx["episode"]["id"])
    assert episode["measured_download_count"] == 5
