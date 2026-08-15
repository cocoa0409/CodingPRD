"""Corner queue B — calculations section (4 non-stub instances)."""

from test_helpers import (
    ADOPS,
    add_line_item,
    create_advertiser,
    create_campaign,
    create_episode,
    create_show,
    deliver_downloads,
    end_campaign,
    finalize_episode_measurement,
    get_campaign,
    get_make_good,
    get_show,
    ingest_attribution_event,
    ingest_downloads,
    publish_episode,
    set_clock,
    setup_measured_delivery,
    setup_selling_scenario,
    transition_episode,
    transition_line_item,
    transition_make_good,
    validate_paginated,
)


def test_attribution_window_inclusive_end_boundary(api):
    """PRD §3.6: "At ingest the server computes the event's `attributed` flag: the event is attributed when its `occurred_at` falls on or after the campaign's `flight_start` and on or before the campaign's **current** `flight_end` plus thirty days — both bounds inclusive, and evaluated against whatever `flight_end` the campaign holds at ingest time, which matters when a make-good acceptance has extended the flight."

    Design: Corner/calculations/attribution_window_inclusive_end_boundary
    """
    advertiser = create_advertiser(name="AttrCo", category="FINTECH")
    campaign = create_campaign(advertiser["id"], name="CA",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    # flight_end + 30 days == 2026-10-01T00:00:00Z exactly: inclusive -> true.
    ev_in = ingest_attribution_event(campaign["id"], "PROMO_CODE",
                                     "2026-10-01T00:00:00Z", promo_code="IN30")
    assert ev_in["attributed"] is True, (
        "Event at exactly flight_end + 30 days must be attributed (inclusive)"
    )
    # One second past the window: not attributed.
    ev_out = ingest_attribution_event(campaign["id"], "PROMO_CODE",
                                      "2026-10-01T00:00:01Z", promo_code="OUT30")
    assert ev_out["attributed"] is False
    # One second before flight_start: not attributed.
    ev_pre = ingest_attribution_event(campaign["id"], "PIXEL",
                                      "2026-07-31T23:59:59Z")
    assert ev_pre["attributed"] is False


def _setup_selector_scenario():
    """Show + PUBLISHED episode with slot_capacity 1; one ACTIVE campaign with
    APPROVED copy; LI_A priority 5 ACTIVE (created first), LI_B priority 10
    ACTIVE (created second)."""
    ctx = setup_selling_scenario(
        advertiser_name="SelCo", category="FINTECH", booked_impressions=10,
        cpm_cents=1000, episode_publish_at="2026-08-01T00:00:00Z",
        episode_overrides={"slot_capacity": 1},
    )
    ctx["li_a"] = add_line_item(ctx, target="show", position="MID_ROLL",
                                reserved_impressions=10, priority=5)
    ctx["li_b"] = add_line_item(ctx, target="show", position="MID_ROLL",
                                reserved_impressions=10, priority=10)
    publish_episode(ctx)
    return ctx


def test_insertion_selector_priority_then_created_at(api):
    """PRD §3.5: "Eligible items are ranked by `priority` descending, ties broken by `created_at` ascending, and the top `slot_capacity` of them each receive an Impression on that download."

    Design: Corner/calculations/insertion_selector_priority_then_created_at
    """
    ctx = _setup_selector_scenario()
    # slot_capacity 1: the priority-10 line item wins the only slot.
    d1 = ingest_downloads(ctx["episode"]["id"], "S1", 1,
                          occurred_at="2026-08-05T00:00:00Z")
    impressions, meta = validate_paginated(
        api.list_impressions(ADOPS, params={"download_id": d1[0]["id"]})
    )
    assert meta["total_count"] == 1
    assert impressions[0]["line_item_id"] == ctx["li_b"]["id"], (
        "priority 10 must beat priority 5 for the single slot"
    )
    # Tie-break on equal priority: the earlier created_at wins.
    transition_line_item(ctx["li_b"]["id"], "END")
    li_c = add_line_item(ctx, target="show", position="MID_ROLL",
                         reserved_impressions=10, priority=5)
    d2 = ingest_downloads(ctx["episode"]["id"], "S2", 1,
                          occurred_at="2026-08-06T00:00:00Z")
    impressions, meta = validate_paginated(
        api.list_impressions(ADOPS, params={"download_id": d2[0]["id"]})
    )
    assert meta["total_count"] == 1
    assert impressions[0]["line_item_id"] == ctx["li_a"]["id"], (
        "On a priority tie the earlier-created line item wins"
    )
    _imps, meta = validate_paginated(
        api.list_impressions(ADOPS, params={"line_item_id": li_c["id"]})
    )
    assert meta["total_count"] == 0


def test_forecast_horizon_inclusive_upper_bound(api):
    """PRD §3.1: "Eligible episodes are those of the show whose `status` is `SCHEDULED` or `PUBLISHED` and whose `publish_at` falls inside the inclusive window from the current logical-clock instant to thirty days after it."
    PRD §3.1: "The forecast equals the floor of `avg_downloads_30d` multiplied by the count of eligible episodes multiplied by the tier's sell-through cap: 0.95 while `CLEAR`, 0.70 while `FLAGGED`, and 0.00 while `SUSPENDED`."

    Design: Corner/calculations/forecast_horizon_inclusive_upper_bound
    """
    s1 = create_show(title="H1", content_category="NEWS", avg_downloads_30d=10000)
    s2 = create_show(title="H2", content_category="NEWS", avg_downloads_30d=10000)
    # Startup clock is exactly 2026-08-01T00:00:00Z; +30 days is 2026-08-31.
    create_episode(s1["id"], title="E1", publish_at="2026-08-31T00:00:00Z")
    create_episode(s2["id"], title="E2", publish_at="2026-09-01T00:00:00Z")
    s1 = get_show(s1["id"])
    s2 = get_show(s2["id"])
    assert s1["forecast_impressions"] == 9500, (
        f"publish_at == clock + 30d is inside the inclusive horizon: "
        f"floor(10000 * 1 * 0.95) == 9500, got {s1['forecast_impressions']}"
    )
    assert s2["forecast_impressions"] == 0, (
        f"publish_at one day past the horizon is excluded, got "
        f"{s2['forecast_impressions']}"
    )


def _setup_expiring_makegood():
    """Reopen chain: 800 measured deliveries against 1000 booked, END, invoice,
    MakeGood OFFERED (200), ACCEPT (+14 days), then only 100 bonus downloads
    delivered on the reopened flight and measured."""
    ctx = setup_measured_delivery(
        booked_impressions=1000, cpm_cents=5000, downloads=800,
        reserved_impressions=1000, category="AUTOMOTIVE",
        end_campaign_too=True, create_invoice_too=True,
    )
    ep2 = create_episode(ctx["show"]["id"], title="E2",
                         publish_at="2026-08-25T00:00:00Z",
                         measurement_window_days=30, slot_capacity=2)
    transition_make_good(
        ctx["make_good"]["id"], "ACCEPT", ctx["owner_headers"], extension_days=14,
    )
    set_clock("2026-08-25T00:00:00Z")
    transition_episode(ep2["id"], "PUBLISH")
    ctx["episode"] = ep2
    ctx["campaign"] = get_campaign(ctx["campaign"]["id"])
    add_line_item(ctx, target="show", position="MID_ROLL",
                  reserved_impressions=100, priority=10)
    deliver_downloads(ctx, 100, prefix="Q", occurred_at="2026-08-26T00:00:00Z")
    finalize_episode_measurement(ctx, clock="2026-09-25T00:00:00Z")
    return ctx


def test_make_good_expires_when_bonus_short(api):
    """PRD §3.7: "Fulfillment is then judged when the campaign next ends: the bonus delivered is the campaign's `delivered_impressions` minus `baseline_delivered_impressions`, and if that bonus is greater than or equal to `granted_impressions` — an exact tie fulfills — the make-good moves `ACCEPTED → FULFILLED`, otherwise `ACCEPTED → EXPIRED`."

    Design: Corner/calculations/make_good_expires_when_bonus_short
    """
    ctx = _setup_expiring_makegood()
    end_campaign(ctx)
    campaign = get_campaign(ctx["campaign"]["id"])
    assert campaign["delivered_impressions"] == 900, (
        f"800 baseline + 100 bonus == 900, got {campaign['delivered_impressions']}"
    )
    make_good = get_make_good(ctx["make_good"]["id"])
    assert make_good["status"] == "EXPIRED", (
        f"bonus 100 < granted 200 must expire the make-good, got "
        f"{make_good['status']}"
    )
    # Invoice was never marked PAID, so the campaign rests in ENDED.
    assert campaign["status"] == "ENDED"
