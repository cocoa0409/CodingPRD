"""Difficulty queue A — dual_variant_calc (2 instances, 4 tests)."""

from test_helpers import (
    ADOPS,
    add_line_item,
    create_advertiser,
    create_and_approve_copy,
    create_campaign,
    create_episode,
    create_invoice,
    create_show,
    end_campaign,
    get_episode,
    ingest_downloads,
    list_make_goods_for_campaign,
    make_advertiser_headers,
    set_clock,
    transition_campaign,
    transition_episode,
    validate_success,
)


def _setup_mixed_downloads_episode():
    """PUBLISHED episode (publish 2026-08-01, window 30) with 4 downloads:
    L1-0 HUMAN twice on the same UTC day, L2-0 UNKNOWN, L3-0 BOT."""
    show = create_show(title="Tech Talk", content_category="TECHNOLOGY",
                       avg_downloads_30d=10000)
    episode = create_episode(show["id"], title="E1", publish_at="2026-08-01T00:00:00Z",
                             measurement_window_days=30, slot_capacity=2)
    transition_episode(episode["id"], "PUBLISH")
    ingest_downloads(episode["id"], "L1", 1, occurred_at="2026-08-02T00:00:00Z",
                     user_agent_class="HUMAN")
    ingest_downloads(episode["id"], "L1", 1, occurred_at="2026-08-02T12:00:00Z",
                     user_agent_class="HUMAN")
    ingest_downloads(episode["id"], "L2", 1, occurred_at="2026-08-03T00:00:00Z",
                     user_agent_class="UNKNOWN")
    ingest_downloads(episode["id"], "L3", 1, occurred_at="2026-08-04T00:00:00Z",
                     user_agent_class="BOT")
    return {"show": show, "episode": episode}


def _setup_dual_billing_variants():
    """Two campaigns (ACTUAL_DELIVERY + BOOKED_GROSS), identical flights/rates,
    each with an ACTIVE run-of-show line item serving the same 800 downloads;
    episode MEASURED, both campaigns ENDED."""
    show = create_show(title="Daily Tech", content_category="TECHNOLOGY",
                       avg_downloads_30d=10000)
    episode = create_episode(show["id"], title="E1", publish_at="2026-08-01T00:00:00Z",
                             measurement_window_days=30, slot_capacity=2)
    advertiser = create_advertiser(name="Acme", category="TECHNOLOGY")
    owner = make_advertiser_headers(advertiser["id"])

    ctxs = {}
    for key, model, priority in (
        ("actual", "ACTUAL_DELIVERY", 10),
        ("booked", "BOOKED_GROSS", 9),
    ):
        campaign = create_campaign(
            advertiser["id"], name=f"C-{key}", flight_start="2026-08-01T00:00:00Z",
            flight_end="2026-09-01T00:00:00Z", booked_impressions=1000,
            cpm_cents=5000, billing_model=model,
        )
        copy = create_and_approve_copy(campaign["id"], owner, script_text=f"spot {key}")
        campaign = transition_campaign(campaign["id"], "ACTIVATE")
        ctx = {
            "show": show, "episode": episode, "advertiser": advertiser,
            "owner_headers": owner, "campaign": campaign, "copy": copy,
        }
        ctx["line_item"] = add_line_item(
            ctx, target="show", position="MID_ROLL", reserved_impressions=1000,
            priority=priority,
        )
        ctxs[key] = ctx

    transition_episode(episode["id"], "PUBLISH")
    ingest_downloads(episode["id"], "P", 800, occurred_at="2026-08-05T00:00:00Z",
                     user_agent_class="HUMAN")
    set_clock("2026-09-01T00:00:01Z")
    transition_episode(episode["id"], "FINALIZE_MEASUREMENT")
    for key in ("actual", "booked"):
        end_campaign(ctxs[key])
    return ctxs


# =========================================================================
# download_qualification_provisional_vs_final
# =========================================================================

def test_provisional_lens_counts_unknown_and_same_day_repeats(api):
    """PRD §2.9: "The **provisional** lens applies at download ingest: it excludes only bot-classified traffic, counts unknown agents and same-day repeat listens, and drives live counters such as an episode's `provisional_download_count` and report-only provisional delivery figures."

    Design: Difficulty/dual_variant_calc/download_qualification_provisional_vs_final
    """
    ctx = _setup_mixed_downloads_episode()
    episode = get_episode(ctx["episode"]["id"])
    # L1-0 x2 (HUMAN, same listener same UTC day) + L2-0 (UNKNOWN) qualify
    # provisionally; only L3-0 (BOT) is excluded.
    assert episode["provisional_download_count"] == 3, (
        f"provisional_download_count must be 3, got {episode['provisional_download_count']}"
    )
    assert episode["status"] == "PUBLISHED"


def test_final_lens_dedupes_and_filters_after_finalize(api):
    """PRD §2.9: "The **final** lens applies exactly once, when an episode's measurement is finalized: it keeps only human-classified downloads inside the measurement window and deduplicates to one download per listener per UTC calendar day."

    Design: Difficulty/dual_variant_calc/download_qualification_provisional_vs_final
    """
    ctx = _setup_mixed_downloads_episode()
    set_clock("2026-09-01T00:00:01Z")
    measured = validate_success(
        api.transition_episode(ctx["episode"]["id"], {"action": "FINALIZE_MEASUREMENT"}, ADOPS)
    )
    assert measured["status"] == "MEASURED"
    # Only the first L1-0 HUMAN download survives the HUMAN-only + window +
    # per-listener-per-day dedupe: measured == 1.
    assert measured["measured_download_count"] == 1, (
        f"measured_download_count must be 1, got {measured['measured_download_count']}"
    )
    # Provisional lens is untouched by finalization.
    assert measured["provisional_download_count"] == 3


# =========================================================================
# invoice_billing_actual_vs_booked_gross
# =========================================================================

def test_actual_delivery_bills_only_qualified_delivered(api):
    """PRD §3.7: "The gross depends on the billing variant: under `ACTUAL_DELIVERY`, `gross_cents` is the sum of the per-line amounts; under `BOOKED_GROSS`, `gross_cents` is the half-up-rounded value of `booked_impressions` times `cpm_cents` divided by one thousand, billed in full regardless of delivery or position."

    Design: Difficulty/dual_variant_calc/invoice_billing_actual_vs_booked_gross
    """
    ctxs = _setup_dual_billing_variants()
    invoice = create_invoice(ctxs["actual"]["campaign"]["id"])
    # round_half_up(800 * 5000 * 1000 / 1000000) == 4000
    assert invoice["billing_model"] == "ACTUAL_DELIVERY"
    assert invoice["gross_cents"] == 4000, (
        f"ACTUAL_DELIVERY gross_cents must be 4000, got {invoice['gross_cents']}"
    )
    assert invoice["delivered_impressions_billed"] == 800
    assert invoice["shortfall_impressions"] == 200


def test_booked_gross_bills_booked_despite_identical_delivery(api):
    """PRD §3.7: "under `BOOKED_GROSS`, `gross_cents` is the half-up-rounded value of `booked_impressions` times `cpm_cents` divided by one thousand, billed in full regardless of delivery or position."
    PRD §3.7: "If `shortfall_impressions` is greater than zero at creation, the system automatically creates exactly one **MakeGood** for the campaign in `OFFERED` status, recording the `campaign_id`, the `invoice_id` that documented the shortfall, and `granted_impressions` equal to the invoice's `shortfall_impressions`."

    Design: Difficulty/dual_variant_calc/invoice_billing_actual_vs_booked_gross
    """
    ctxs = _setup_dual_billing_variants()
    invoice = create_invoice(ctxs["booked"]["campaign"]["id"])
    # round_half_up(1000 * 5000 / 1000) == 5000 even though only 800 delivered.
    assert invoice["billing_model"] == "BOOKED_GROSS"
    assert invoice["gross_cents"] == 5000, (
        f"BOOKED_GROSS gross_cents must be 5000, got {invoice['gross_cents']}"
    )
    assert invoice["delivered_impressions_billed"] == 800
    assert invoice["shortfall_impressions"] == 200
    make_goods = list_make_goods_for_campaign(ctxs["booked"]["campaign"]["id"])
    assert len(make_goods) == 1, "shortfall 200 must auto-create exactly one MakeGood"
    assert make_goods[0]["granted_impressions"] == 200
    assert make_goods[0]["status"] == "OFFERED"
    assert make_goods[0]["invoice_id"] == invoice["id"]
