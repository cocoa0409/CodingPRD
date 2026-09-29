"""Optimistic concurrency on the three pinned writes, version accounting on every write, and the
immediate visibility of a cascade in the responses that follow it."""

from test_helpers import (
    COMPLIANCE,
    DESIGNER,
    LIVEOPS,
    PRODUCER,
    ApiErrorId,
    api_client,
    create_approved_offer,
    create_draft_balance_change,
    create_live_season,
    create_player,
    create_scheduled_episode,
    make_player_headers,
    offer_line_item,
    open_account,
    read_balance_change,
    read_offer,
    read_season,
    season_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_offer_publish_with_stale_season_version_is_rejected():
    """A season version captured before an episode release no longer matches, so the publish is
    refused and the storefront is untouched until the pin is refreshed.

    PRD §2.7: "`POST /offers/{offer_id}/publish` requires `expected_season_version` in its request body, carrying the `version` of the offer's season as the client last observed it. If that number does not equal the season's current `version`, the publish is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412)."
    PRD §3.2: "On success the episode's `actual_release_at` is stamped with the clock, the season's `scheduled_episode_count` falls by 1 and its `released_episode_count` rises by 1, and any episode of the same season that is currently `LIVE` with a lower `sequence_no` is automatically carried from `LIVE` to `CONCLUDED` — the previous drop closing out as the new one opens, with `released_episode_count` unaffected by that automatic closure."
    PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."

    Design: Corner/cross-cutting complexity layers/corner_layer_occ_offer_publish_stale_season_version
    """
    season = create_live_season()
    episode = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    offer = create_approved_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="OCC_PACK",
        price_tier="T1",
        list_price_minor=900,
        line_items=[offer_line_item("OCC_COINS", 900, 1200, "SOFT_COIN", 1200)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )

    stale_v = season_version(season["id"])
    set_clock("2026-08-02T00:00:00Z")
    validate_success(api_client.release_episode(episode["id"], PRODUCER))

    stale_publish = api_client.publish_offer(
        offer["id"], {"expected_season_version": stale_v}, DESIGNER
    )
    validate_error(stale_publish, ApiErrorId.ERR_STALE_SEASON_VERSION)
    assert read_offer(offer["id"])["availability_status"] == "OFFLINE"
    assert read_season(season["id"])["live_offer_count"] == 0

    fresh_v = season_version(season["id"])
    published = validate_success(
        api_client.publish_offer(offer["id"], {"expected_season_version": fresh_v}, DESIGNER)
    )
    assert published["availability_status"] == "LIVE"
    assert read_offer(offer["id"])["availability_status"] == "LIVE"

    final_season = read_season(season["id"])
    assert final_season["live_offer_count"] == 1
    assert final_season["version"] == fresh_v + 1


def test_purchase_with_stale_offer_version_is_rejected():
    """A buyer holding the offer version from before a suspend and resume cycle is turned away,
    and only the refreshed pin creates the purchase.

    PRD §2.7: "`POST /purchases` requires `expected_offer_version` in its request body, carrying the `version` of the offer as the buyer last observed it. If that number does not equal the offer's current `version`, the purchase creation is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412)."
    PRD §3.5: "Suspending a `LIVE` offer carries it `LIVE → SUSPENDED`, lowers the season's `live_offer_count` by 1, and moves both the season's and the offer's `version` by 1; the same transition also occurs as a system cascade from a monitoring run, as §3.9 describes."
    PRD §3.5: "Resuming carries `SUSPENDED → LIVE` and requires that the clock still be at or before the offer's `window_end` (otherwise `ERR_OFFER_WINDOW_CLOSED`), that the season's `economy_health` not be `INFLATED` (otherwise `ERR_ECONOMY_INFLATED_BLOCK`), and — for a randomized offer — that its `disclosure_state` be `PUBLISHED` rather than `REQUIRED_MISSING` (otherwise `ERR_DISCLOSURE_NOT_PUBLISHED`); it raises `live_offer_count` by 1 and moves both versions by 1."
    PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."
    PRD §2.5: "The purchase list accepts `player_id`, `offer_id`, and `status`."

    Design: Corner/cross-cutting complexity layers/corner_layer_occ_purchase_create_stale_offer_version
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pv", region_code="NA")
    open_account(player["id"], "HARD_GEM")

    offer = create_approved_offer(
        season["id"],
        offer_type="LIMITED_TIME",
        sku="PV_PACK",
        price_tier="T1",
        list_price_minor=300,
        line_items=[offer_line_item("PV_COINS", 300, 400, "HARD_GEM", 300)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    published = validate_success(
        api_client.publish_offer(
            offer["id"], {"expected_season_version": season_version(season["id"])}, DESIGNER
        )
    )
    stale_offer_v = published["version"]

    validate_success(
        api_client.set_offer_availability(
            offer["id"], {"to_status": "SUSPENDED", "reason": "Copy fix"}, LIVEOPS
        )
    )
    validate_success(
        api_client.set_offer_availability(
            offer["id"], {"to_status": "LIVE", "reason": "Copy fixed"}, LIVEOPS
        )
    )

    player_headers = make_player_headers(player["id"])

    stale_purchase = api_client.create_purchase(
        {
            "player_id": player["id"],
            "offer_id": offer["id"],
            "expected_offer_version": stale_offer_v,
        },
        player_headers,
    )
    validate_error(stale_purchase, ApiErrorId.ERR_STALE_OFFER_VERSION)
    _, meta = validate_paginated(
        api_client.list_purchases(LIVEOPS, params={"offer_id": offer["id"]})
    )
    assert meta["total_count"] == 0

    fresh_offer_v = validate_success(api_client.get_offer(offer["id"], player_headers))["version"]
    purchase = validate_success(
        api_client.create_purchase(
            {
                "player_id": player["id"],
                "offer_id": offer["id"],
                "expected_offer_version": fresh_offer_v,
            },
            player_headers,
        ),
        201,
    )
    assert purchase["status"] == "PENDING"

    final_offer = read_offer(offer["id"])
    assert final_offer["pending_purchase_count"] == 1
    assert final_offer["version"] == fresh_offer_v + 1
    assert read_season(season["id"])["pending_revenue_minor"] == 300


def test_balance_change_advance_with_stale_season_version_is_rejected():
    """A tuning advance pinned to the season version from before an offer publish is refused and
    the change stays in DRAFT until the operator re-reads the season.

    PRD §2.7: "`POST /balance-changes/{change_id}/advance` likewise requires `expected_season_version` matching the season's current `version`, and a mismatch is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412)."
    PRD §3.8: "Entering `SHADOW` from `DRAFT` requires the season to be `LIVE`; it records the promoting operator as `promoted_by_user_id`, raises the season's `active_tuning_count` by 1, raises the season's `tuning_stage_epoch` by 1, and moves the season's `version` by 1."
    PRD §3.8: "On success the season's current `effective_sink_rate_bp` is snapshotted into the change's `pre_live_sink_rate_bp`, and then — only when the change's `target_kind` is `SINK_RATE` — the season's `effective_sink_rate_bp` is adjusted by the change's `delta_bp`, a positive delta raising it and a negative delta lowering it."
    PRD §3.1: "The season is stored in `PLANNED`, with `economy_health` at `HEALTHY`, `content_posture` at `ON_TRACK`, `version` at 1, and every derived counter at its opening value: `scheduled_episode_count`, `released_episode_count`, `cadence_debt_days`, `gross_faucet_minor`, `gross_sink_minor`, `pending_revenue_minor`, `settled_revenue_minor`, `live_offer_count`, `active_tuning_count` and `tuning_stage_epoch` all at 0, and `lifetime_ratio_bp` and `effective_sink_rate_bp` both at 10000."

    Design: Corner/cross-cutting complexity layers/corner_layer_occ_balance_change_advance_stale_season_version
    """
    season = create_live_season()
    change = create_draft_balance_change(
        season["id"], target_kind="SINK_RATE", delta_bp=500, rationale="Crafting sink up"
    )
    offer = create_approved_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="BC_PACK",
        price_tier="T1",
        list_price_minor=900,
        line_items=[offer_line_item("BC_COINS", 900, 1200, "SOFT_COIN", 1200)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )

    stale_v = season_version(season["id"])
    validate_success(
        api_client.publish_offer(offer["id"], {"expected_season_version": stale_v}, DESIGNER)
    )

    stale_advance = api_client.advance_balance_change(
        change["id"], {"to_stage": "SHADOW", "expected_season_version": stale_v}, LIVEOPS
    )
    validate_error(stale_advance, ApiErrorId.ERR_STALE_SEASON_VERSION)
    assert read_balance_change(change["id"])["stage"] == "DRAFT"

    fresh_v = season_version(season["id"])
    advanced = validate_success(
        api_client.advance_balance_change(
            change["id"], {"to_stage": "SHADOW", "expected_season_version": fresh_v}, LIVEOPS
        )
    )
    assert advanced["stage"] == "SHADOW"
    assert read_balance_change(change["id"])["stage"] == "SHADOW"
    assert read_season(season["id"])["effective_sink_rate_bp"] == 10000


def test_version_advances_by_one_on_every_write_and_ledger_rows_carry_none():
    """Each accepted mutation moves the record's version by exactly one, while the append-only
    ledger row carries no version at all.

    PRD §2.4: "Seasons, episodes, capacity clusters, live events, players, currency accounts, offers, probability disclosures, purchases, refund requests, balance changes, community notices and monitoring runs each expose `created_at` (an ISO 8601 UTC timestamp with three fractional digits, recording when the record was first stored), `updated_at` (the same format, refreshed on every mutation of the record), and `version` (an integer that starts at 1 on creation and increases by exactly 1 on every accepted mutation of that record, including mutations caused indirectly by a cascade from another resource)."
    PRD §2.4: "Economy ledger entries are the exception. A ledger entry is immutable once appended, so it exposes only `id` and `created_at`; it has no `updated_at` and no `version` field at all."
    PRD §3.5: "An `EconomyDesigner` first submits a `DRAFT` offer into review, which requires the offer's `approval_status` to be `DRAFT`, its `availability_status` to be `OFFLINE`, and its season to be `LIVE` (otherwise `ERR_SEASON_NOT_LIVE`); the submission recomputes `fairness_index_bp` and moves the offer's `version` by 1, touching the storefront dimension not at all."
    PRD §3.5: "Approving carries the offer `IN_REVIEW → APPROVED`, records the reviewer as `reviewed_by_user_id`, and moves the offer's `version` by 1."
    PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."
    PRD §2.8: "Because balances are derived from the ledger rather than stored independently, every append fans out. The credited or debited account's `lifetime_faucet_minor` or `lifetime_sink_minor` grows by the entry's `amount_minor`, and its `balance_minor` is then recomputed as lifetime faucet total minus lifetime sink total — a quantity that is never allowed to go negative."

    Design: Corner/cross-cutting complexity layers/corner_layer_version_increments_on_every_write
    """
    set_clock("2026-08-01T00:00:00Z")

    season = validate_success(
        api_client.create_season(
            {
                "code": "S7",
                "title": "Season 7 Tidebreak",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-10-30T00:00:00Z",
                "planned_episode_count": 6,
                "target_xp_total": 9000,
                "pass_price_minor": 1000,
            },
            PRODUCER,
        ),
        201,
    )
    s_v1 = season["version"]
    s_v2 = validate_success(
        api_client.set_season_status(season["id"], {"to_status": "LIVE"}, PRODUCER)
    )["version"]

    offer = validate_success(
        api_client.create_offer(
            {
                "season_id": season["id"],
                "offer_type": "BUNDLE",
                "sku": "VER_PACK",
                "price_tier": "T1",
                "list_price_minor": 900,
                "line_items": [offer_line_item("VER_COINS", 900, 1200, "SOFT_COIN", 1200)],
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-20T00:00:00Z",
            },
            DESIGNER,
        ),
        201,
    )
    o_v1 = offer["version"]
    o_v2 = validate_success(api_client.submit_offer(offer["id"], DESIGNER))["version"]
    o_v3 = validate_success(
        api_client.review_offer(offer["id"], {"decision": "APPROVE"}, COMPLIANCE)
    )["version"]
    o_v4 = validate_success(
        api_client.publish_offer(offer["id"], {"expected_season_version": s_v2}, DESIGNER)
    )["version"]

    assert (s_v1, s_v2) == (1, 2)
    assert read_season(season["id"])["version"] == 3
    assert (o_v1, o_v2, o_v3, o_v4) == (1, 2, 3, 4)

    player = validate_success(
        api_client.create_player(
            {"handle": "tide_pver", "region_code": "NA", "active_season_id": season["id"]}, LIVEOPS
        ),
        201,
    )
    account = validate_success(
        api_client.create_currency_account(player["id"], {"currency_code": "SOFT_COIN"}, LIVEOPS),
        201,
    )
    entry = validate_success(
        api_client.create_adjustment(
            account["id"],
            {"direction": "FAUCET", "amount_minor": 500, "source_kind": "ADMIN_ADJUSTMENT"},
            LIVEOPS,
        ),
        201,
    )
    assert "version" not in entry

    rows, _ = validate_paginated(
        api_client.list_ledger_entries(LIVEOPS, params={"currency_account_id": account["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["direction"] == "FAUCET"
    assert "version" not in rows[0]
    assert validate_success(api_client.get_currency_account(account["id"], LIVEOPS))[
        "balance_minor"
    ] == 500


def test_release_cascade_is_visible_in_the_same_and_following_responses():
    """The release response already reports its own fan-out, and reads taken straight afterwards
    show the season totals and the recomputed ratio with no settling delay.

    PRD §3.2: "For each recipient in that order a ledger entry is appended with `direction` `FAUCET`, `source_kind` `EPISODE_GRANT`, an `amount_minor` equal to the episode's `soft_currency_grant_minor` — every recipient receives exactly that amount, with no proration — and the episode's season as `season_id`; the episode's `grant_batch_size` records how many entries were appended."
    PRD §3.2: "At the second level, because those entries now exist, each recipient account's `lifetime_faucet_minor` grows by the granted amount, its `balance_minor` is recomputed as lifetime faucet minus lifetime sink, and its `version` moves by 1."
    PRD §3.2: "At the third level, because those account totals changed, the season's `gross_faucet_minor` grows by `grant_batch_size` multiplied by `soft_currency_grant_minor`."
    PRD §3.2: "At the fourth level, because the season's gross faucet total changed, the season's `lifetime_ratio_bp` is recomputed under the lifetime-cumulative reading described in §3.9."
    PRD §3.2: "On success the episode's `actual_release_at` is stamped with the clock, the season's `scheduled_episode_count` falls by 1 and its `released_episode_count` rises by 1, and any episode of the same season that is currently `LIVE` with a lower `sequence_no` is automatically carried from `LIVE` to `CONCLUDED` — the previous drop closing out as the new one opens, with `released_episode_count` unaffected by that automatic closure."
    PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."
    PRD §3.9: "The **lifetime-cumulative** reading uses gross semantics: every row of the season counts regardless of `occurred_at`, including compensating rows and the rows they reverse."
    PRD §3.9: "The health band follows from the ratio: `HEALTHY` when the ratio is at least 6000 basis points, `WATCH` when it is at least 4000 but below 6000, and `INFLATED` when it is below 4000."

    Design: Corner/consistency model/corner_consistency_immediate_cascade_visible_in_same_response
    """
    season = create_live_season()
    pi1 = create_player(season["id"], handle="tide_pi1", region_code="NA")
    pi1_soft = open_account(pi1["id"], "SOFT_COIN")
    pi2 = create_player(season["id"], handle="tide_pi2", region_code="EU")
    pi2_soft = open_account(pi2["id"], "SOFT_COIN")

    validate_success(
        api_client.create_adjustment(
            pi1_soft["id"],
            {"direction": "FAUCET", "amount_minor": 400, "source_kind": "ADMIN_ADJUSTMENT"},
            LIVEOPS,
        ),
        201,
    )
    validate_success(
        api_client.create_adjustment(
            pi1_soft["id"],
            {"direction": "SINK", "amount_minor": 400, "source_kind": "OFFER_SPEND"},
            LIVEOPS,
        ),
        201,
    )

    episode = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=1200,
    )
    set_clock("2026-08-02T00:00:00Z")

    released = validate_success(api_client.release_episode(episode["id"], PRODUCER))
    assert released["status"] == "LIVE"
    assert released["grant_batch_size"] == 2
    assert released["actual_release_at"].startswith("2026-08-02T00:00:00")

    summary = validate_success(
        api_client.get_economy_summary(
            season["id"], DESIGNER, params={"variant": "LIFETIME_CUMULATIVE"}
        )
    )
    assert summary["gross_faucet_minor"] == 2800
    assert summary["gross_sink_minor"] == 400
    assert summary["sink_faucet_ratio_bp"] == 1429
    assert summary["health_band"] == "INFLATED"

    stored_season = validate_success(api_client.get_season(season["id"], LIVEOPS))
    assert stored_season["gross_faucet_minor"] == 2800
    assert stored_season["lifetime_ratio_bp"] == 1429
    assert stored_season["released_episode_count"] == 1

    assert validate_success(api_client.get_currency_account(pi1_soft["id"], LIVEOPS))[
        "balance_minor"
    ] == 1200
    assert validate_success(api_client.get_currency_account(pi2_soft["id"], LIVEOPS))[
        "balance_minor"
    ] == 1200
