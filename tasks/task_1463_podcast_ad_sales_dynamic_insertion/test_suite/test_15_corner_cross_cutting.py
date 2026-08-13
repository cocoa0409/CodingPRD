"""Corner queue B — cross_cutting_layers section (3 non-stub instances)."""

from test_helpers import (
    ADOPS,
    ApiErrorId,
    add_line_item,
    create_advertiser,
    create_and_approve_copy,
    create_campaign,
    create_episode,
    create_show,
    get_campaign,
    get_line_item,
    get_show,
    make_advertiser_headers,
    review_ad_copy,
    setup_selling_scenario,
    transition_campaign,
    validate_error,
    validate_success,
)


def test_campaign_patch_occ_stale_after_increment(api):
    """PRD §2.7: "Editing a campaign's flight or booking terms requires `expected_campaign_version` in the request body, carrying the client's last observed `version` of that campaign. If the stored `version` no longer matches — because any mutation, including cascaded `delivered_impressions` recomputes, has advanced it since the client last read the campaign — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting flight dates, `booked_impressions`, or `cpm_cents` it has not observed."
    PRD §2.5: "`version` is an integer starting at its initial value on creation and incrementing by one on every mutation of the resource, including mutations caused by cascaded recomputes originating elsewhere (for example, when a campaign's delivery counters are recomputed as a side effect of measurement finalization, the campaign's `version` advances and its `updated_at` refreshes)."

    Design: Corner/cross_cutting_layers/campaign_patch_occ_stale_after_increment
    """
    advertiser = create_advertiser(name="OccCo", category="FINTECH")
    campaign = create_campaign(advertiser["id"], name="CO",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=10, cpm_cents=1000)
    stale_version = campaign["version"]
    first = validate_success(api.patch_campaign(
        campaign["id"],
        {"cpm_cents": 1500, "expected_campaign_version": stale_version},
        ADOPS,
    ))
    assert first["version"] == stale_version + 1, (
        f"A successful edit increments version by one: {stale_version} -> "
        f"{first['version']}"
    )
    resp = api.patch_campaign(
        campaign["id"],
        {"cpm_cents": 2500, "expected_campaign_version": stale_version},
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    campaign = get_campaign(campaign["id"])
    assert campaign["cpm_cents"] == 1500, "The stale write must change nothing"


def test_copy_revocation_cascades_pause_line_items(api):
    """PRD §3.3: "Requesting changes moves `SUBMITTED → CHANGES_REQUESTED`, and may also be applied to an already-`APPROVED` copy — a **revocation** that moves `APPROVED → CHANGES_REQUESTED` and immediately pauses every `ACTIVE` line item referencing that copy, releasing their reservations and episode slots."

    Design: Corner/cross_cutting_layers/copy_revocation_cascades_pause_line_items
    """
    ctx = setup_selling_scenario(
        advertiser_name="RevCo", category="FINTECH", booked_impressions=100,
        cpm_cents=1000, episode_publish_at="2026-08-05T00:00:00Z",
    )
    line_item = add_line_item(ctx, target="show", position="MID_ROLL",
                              reserved_impressions=100, priority=1)
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 100
    assert show["forecast_impressions"] == 9500
    # PRODUCED_AUDIO is reviewed (and revoked) by AdOps.
    revoked = review_ad_copy(ctx["copy"]["id"], "REQUEST_CHANGES", ADOPS,
                             note="legal flag")
    assert revoked["status"] == "CHANGES_REQUESTED"
    line_item = get_line_item(line_item["id"])
    assert line_item["status"] == "PAUSED", (
        f"Revocation must pause the ACTIVE line item, got {line_item['status']}"
    )
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 0, (
        f"Revocation releases the reservation, got {show['reserved_impressions']}"
    )
    assert show["available_impressions"] == 9500


def test_same_advertiser_overlap_not_exclusive(api):
    """PRD §3.4: "**Category exclusivity**: no other `ACTIVE` line item belonging to a *different* advertiser of the *same* category may target the same show with a flight overlapping the candidate's flight, else `ERR_CATEGORY_EXCLUSIVE_CONFLICT`."

    Design: Corner/cross_cutting_layers/same_advertiser_overlap_not_exclusive
    """
    show = create_show(title="Same FM", content_category="TECHNOLOGY",
                       avg_downloads_30d=10000)
    create_episode(show["id"], title="POOL", publish_at="2026-08-05T00:00:00Z",
                   measurement_window_days=30, slot_capacity=2)
    advertiser = create_advertiser(name="SameCo", category="TECHNOLOGY")
    owner = make_advertiser_headers(advertiser["id"])
    ctxs = []
    for name, start, end, priority in (
        ("C1", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", 1),
        ("C2", "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z", 2),
    ):
        campaign = create_campaign(advertiser["id"], name=name,
                                   flight_start=start, flight_end=end,
                                   booked_impressions=10, cpm_cents=1000)
        copy = create_and_approve_copy(campaign["id"], owner)
        campaign = transition_campaign(campaign["id"], "ACTIVATE")
        ctx = {
            "show": show, "advertiser": advertiser, "owner_headers": owner,
            "campaign": campaign, "copy": copy,
        }
        ctx["line_item"] = add_line_item(
            ctx, target="show", position="MID_ROLL", reserved_impressions=10,
            priority=priority, activate=False,
        )
        ctxs.append(ctx)
    for ctx in ctxs:
        resp = api.transition_line_item(ctx["line_item"]["id"],
                                        {"action": "ACTIVATE"}, ADOPS)
        line_item = validate_success(resp)
        assert line_item["status"] == "ACTIVE", (
            "Same-advertiser overlapping flights must not trip exclusivity"
        )
