"""Corner queue B — endpoints section (3 non-stub instances)."""

from test_helpers import (
    ADOPS,
    FINANCE,
    add_line_item,
    assert_invoice,
    end_campaign,
    get_campaign,
    ingest_attribution_event,
    ingest_downloads,
    invoice_campaign,
    list_make_goods_for_campaign,
    publish_episode,
    setup_measured_delivery,
    setup_selling_scenario,
    transition_episode,
    validate_paginated,
    validate_success,
)
from test_helpers import create_episode, create_show, set_clock


def test_downloads_list_paginates_with_envelope(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/downloads_list_paginates_with_envelope
    """
    show = create_show(title="Page FM", content_category="NEWS",
                       avg_downloads_30d=100)
    episode = create_episode(show["id"], title="E1",
                             publish_at="2026-08-01T00:00:00Z")
    transition_episode(episode["id"], "PUBLISH")
    ingest_downloads(episode["id"], "PG", 15,
                     occurred_at="2026-08-05T00:00:00Z")
    page1, meta1 = validate_paginated(
        api.list_episode_downloads(episode["id"], ADOPS,
                                   params={"limit": 10, "offset": 0})
    )
    assert len(page1) == 10
    assert meta1["total_count"] == 15
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api.list_episode_downloads(episode["id"], ADOPS,
                                   params={"limit": 10, "offset": 10})
    )
    assert len(page2) == 5
    assert meta2["total_count"] == 15
    assert meta2["has_more"] is False


def test_campaign_report_computed_read(api):
    """PRD §3.2: "A live **campaign report**, readable in any campaign status by all roles, returns the campaign's `campaign_id`, `status`, `booked_impressions`, final `delivered_impressions`, a report-only `provisional_delivered_impressions` (the count of its impressions with `billable_provisional` true — this over-counts relative to final since it skips dedupe and includes unknown agents), `shortfall_impressions` computed as `booked_impressions` minus `delivered_impressions` floored at zero, `attributed_promo_code_count` and `attributed_pixel_count` split from the campaign's attributed events, a `gross_cents_estimate`, and an `effective_cpm_cents`."
    PRD §3.2: "`effective_cpm_cents` is zero when `delivered_impressions` is zero, and otherwise the half-up-rounded value of the gross estimate times one thousand divided by `delivered_impressions`."

    Design: Corner/endpoints/campaign_report_computed_read
    """
    ctx = setup_selling_scenario(
        advertiser_name="RepCo", category="FINTECH", booked_impressions=10,
        cpm_cents=1000, episode_publish_at="2026-08-01T00:00:00Z",
    )
    add_line_item(ctx, target="show", position="MID_ROLL", reserved_impressions=10,
                  priority=1)
    publish_episode(ctx)
    # Ten distinct HUMAN listeners -> all qualify at finalization.
    ingest_downloads(ctx["episode"]["id"], "R", 10,
                     occurred_at="2026-08-05T00:00:00Z")
    campaign_id = ctx["campaign"]["id"]
    # Promo in flight; promo at the inclusive window edge; pixel one second out.
    ingest_attribution_event(campaign_id, "PROMO_CODE", "2026-08-10T00:00:00Z",
                             promo_code="IN")
    ingest_attribution_event(campaign_id, "PROMO_CODE", "2026-10-01T00:00:00Z",
                             promo_code="EDGE")
    ingest_attribution_event(campaign_id, "PIXEL", "2026-10-01T00:00:01Z")
    set_clock("2026-09-01T00:00:01Z")
    transition_episode(ctx["episode"]["id"], "FINALIZE_MEASUREMENT")
    report = validate_success(api.get_campaign_report(campaign_id, ADOPS))
    assert report["campaign_id"] == campaign_id
    assert report["delivered_impressions"] == 10
    assert report["provisional_delivered_impressions"] == 10
    assert report["shortfall_impressions"] == 0
    assert report["attributed_promo_code_count"] == 2
    assert report["attributed_pixel_count"] == 0
    # round_half_up(10 * 1000 * 1000 / 1000000) == 10; round_half_up(10*1000/10) == 1000.
    assert report["gross_cents_estimate"] == 10
    assert report["effective_cpm_cents"] == 1000


def test_zero_delivery_invoice_zero_guard(api):
    """PRD §3.2: "`effective_cpm_cents` is zero when `delivered_impressions` is zero, and otherwise the half-up-rounded value of the gross estimate times one thousand divided by `delivered_impressions`."
    PRD §3.7: "`shortfall_impressions` is `booked_impressions` minus `delivered_impressions_billed`, floored at zero."
    PRD §3.7: "If `shortfall_impressions` is greater than zero at creation, the system automatically creates exactly one **MakeGood** for the campaign in `OFFERED` status, recording the `campaign_id`, the `invoice_id` that documented the shortfall, and `granted_impressions` equal to the invoice's `shortfall_impressions`."

    Design: Corner/endpoints/zero_delivery_invoice_zero_guard
    """
    ctx = setup_selling_scenario(
        advertiser_name="ZeroDel", category="FINTECH", booked_impressions=100,
        cpm_cents=1000, episode_publish_at="2026-08-01T00:00:00Z",
    )
    add_line_item(ctx, target="show", position="MID_ROLL", reserved_impressions=100,
                  priority=1)
    publish_episode(ctx)
    # No downloads at all: the campaign ends with zero impression-producing
    # episodes, so the measurement gate passes vacuously.
    end_campaign(ctx)
    invoice_campaign(ctx)
    invoice = ctx["invoice"]
    assert_invoice(invoice)
    assert invoice["gross_cents"] == 0
    assert invoice["delivered_impressions_billed"] == 0
    assert invoice["shortfall_impressions"] == 100
    make_goods = list_make_goods_for_campaign(ctx["campaign"]["id"])
    assert len(make_goods) == 1
    assert make_goods[0]["status"] == "OFFERED"
    assert make_goods[0]["granted_impressions"] == 100
    report = validate_success(
        api.get_campaign_report(ctx["campaign"]["id"], ADOPS)
    )
    assert report["delivered_impressions"] == 0
    assert report["effective_cpm_cents"] == 0, (
        "Zero delivery must hit the zero-guard, not a divide-by-zero"
    )
