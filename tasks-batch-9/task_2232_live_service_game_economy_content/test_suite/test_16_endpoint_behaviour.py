"""Endpoint behaviour: CRUD round-trips, action endpoints, bulk fan-out, cross-references,
computed reads and conditional actions."""

from test_helpers import (
    DESIGNER,
    LIVEOPS,
    PRODUCER,
    ApiErrorId,
    api_client,
    append_adjustment,
    certify_monitoring_run,
    compute_monitoring_run,
    create_approved_offer,
    create_cluster,
    create_live_season,
    create_offer_payload,
    create_planned_event,
    create_player,
    create_scheduled_episode,
    read_cluster,
    read_live_event,
    read_offer,
    read_season,
    lock_player,
    make_player_headers,
    offer_line_item,
    open_account,
    open_monitoring_run,
    publish_offer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# An identifier that no Player and no Offer in these fixtures ever carries.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_offer_create_read_and_filtered_list_round_trip():
    """Creating an offer returns the computed fairness index, and the same row comes back
    through the single read and the filtered list.

    PRD §4: "Operations that mint a new resource — a season, an episode, a capacity cluster, a live event, a player, a currency account, an offer, a probability disclosure, a purchase, a refund request, a tuning change, a community notice, a monitoring run, or a ledger adjustment — answer with `201 Created`."
    PRD §3.5: "A newly created offer is `DRAFT` on the first dimension and `OFFLINE` on the second, and neither dimension ever moves the other implicitly: an offer can be re-reviewed while it sits live on the storefront, and it can be suspended and resumed without its approval ever being revisited."
    PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."
    PRD §3.5: "The index is the value ratio minus all three penalties, then clamped into the range 0 through 15000 — negative results become 0 and results above 15000 become 15000."
    PRD §2.4: "Seasons, episodes, capacity clusters, live events, players, currency accounts, offers, probability disclosures, purchases, refund requests, balance changes, community notices and monitoring runs each expose `created_at` (an ISO 8601 UTC timestamp with three fractional digits, recording when the record was first stored), `updated_at` (the same format, refreshed on every mutation of the record), and `version` (an integer that starts at 1 on creation and increases by exactly 1 on every accepted mutation of that record, including mutations caused indirectly by a cascade from another resource)."
    PRD §2.5: "The offer list accepts `season_id`, `offer_type`, `approval_status`, and `availability_status`."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` counts the records matching the filter before pagination is applied and `has_more` is true when records remain beyond the current page."

    Design: Corner/endpoints/corner_ep_standard_crud_offer_create_read_list
    """
    season = create_live_season()

    payload = create_offer_payload(
        season["id"],
        offer_type="BUNDLE",
        sku="READ_PACK",
        price_tier="T1",
        list_price_minor=1000,
        line_items=[offer_line_item("READ_COINS", 1000, 1400, "SOFT_COIN", 1400)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    created = validate_success(api_client.create_offer(payload, DESIGNER), 201)
    assert created["fairness_index_bp"] == 14000
    assert created["approval_status"] == "DRAFT"
    assert created["availability_status"] == "OFFLINE"
    assert created["version"] == 1

    read = validate_success(api_client.get_offer(created["id"], DESIGNER))
    assert read["sku"] == "READ_PACK"
    assert read["fairness_index_bp"] == 14000

    listed, meta = validate_paginated(
        api_client.list_offers(
            DESIGNER,
            params={"season_id": season["id"], "offer_type": "BUNDLE", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert listed[0]["id"] == created["id"]


def test_cluster_drain_blocks_event_approval_then_reactivation_allows_it():
    """Draining a cluster refuses new approvals with ERR_CLUSTER_NOT_ACTIVE; bringing it back
    to ACTIVE lets the very same approval reserve its forecast concurrency.

    PRD §3.3: "Draining an `ACTIVE` cluster leaves existing approved and running events holding their reservations but refuses new approvals; a `DRAINING` cluster may be brought back to `ACTIVE`; and a `DRAINING` cluster may be retired only once its `reserved_ccu` has fallen to exactly 0, an attempt to retire a cluster that still holds reservations being refused with `ERR_CLUSTER_INVALID_STATE`, the same code used for any transition that does not exist from the current status."
    PRD §3.3: "It requires the event to be `PLANNED`, the season to be `LIVE` (otherwise `ERR_SEASON_NOT_LIVE`), the cluster to be `ACTIVE` (a `DRAINING` or `RETIRED` cluster yielding `ERR_CLUSTER_NOT_ACTIVE`), and the logical clock to be strictly before the event's `window_end` — an approval attempted at or after the window has closed is refused with `ERR_EVENT_INVALID_STATE`."
    PRD §3.3: "A new cluster is `ACTIVE` with `reserved_ccu` at 0, that field being the sum of the reservations held by events on the cluster that are `APPROVED` or `RUNNING`."
    PRD §3.3: "On success the event's `forecast_ccu` is snapshotted into `reserved_ccu_at_approval`, the cluster's `reserved_ccu` grows by that same figure, and the cluster's `version` moves by 1."

    Design: Corner/endpoints/corner_ep_action_endpoint_cluster_drain_gate
    """
    season = create_live_season()
    cluster = create_cluster(
        name="NA-1", region_code="NA", ccu_capacity=10000, maintenance_buffer_minutes=30
    )
    event = create_planned_event(
        season["id"],
        cluster["id"],
        code="EVT_DRAIN",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-05T02:00:00Z",
        forecast_ccu=6000,
    )

    drained = validate_success(
        api_client.set_cluster_status(cluster["id"], {"to_status": "DRAINING"}, LIVEOPS)
    )
    assert drained["status"] == "DRAINING"

    blocked = api_client.approve_live_event(event["id"], LIVEOPS)
    validate_error(blocked, ApiErrorId.ERR_CLUSTER_NOT_ACTIVE)
    assert read_live_event(event["id"])["status"] == "PLANNED"
    assert read_cluster(cluster["id"])["reserved_ccu"] == 0

    resumed = validate_success(
        api_client.set_cluster_status(cluster["id"], {"to_status": "ACTIVE"}, LIVEOPS)
    )
    assert resumed["status"] == "ACTIVE"

    approved = validate_success(api_client.approve_live_event(event["id"], LIVEOPS))
    assert approved["status"] == "APPROVED"
    assert read_live_event(event["id"])["status"] == "APPROVED"
    assert read_cluster(cluster["id"])["reserved_ccu"] == 6000


def test_episode_release_grants_only_eligible_accounts_and_skips_frozen_one():
    """With three SOFT_COIN holders of which one is frozen by a compliance lock, the release
    succeeds, credits exactly two accounts and records grant_batch_size 2.

    PRD §3.2: "At the first level, the recipient set is selected: every currency account whose `currency_code` is `SOFT_COIN`, whose `status` is `ACTIVE`, whose owning player's `active_season_id` is the episode's season, and whose owning player's `spend_state` is anything other than `LOCKED`."
    PRD §3.2: "For each recipient in that order a ledger entry is appended with `direction` `FAUCET`, `source_kind` `EPISODE_GRANT`, an `amount_minor` equal to the episode's `soft_currency_grant_minor` — every recipient receives exactly that amount, with no proration — and the episode's season as `season_id`; the episode's `grant_batch_size` records how many entries were appended."
    PRD §3.2: "At the third level, because those account totals changed, the season's `gross_faucet_minor` grows by `grant_batch_size` multiplied by `soft_currency_grant_minor`."
    PRD §3.7: "Locking is a cascade: every currency account of the player is moved to `FROZEN` with each account's `version` moving by 1, every purchase of the player still in `PENDING` is denied with the `deny_reason` `SPEND_LOCKED` while the season's `pending_revenue_minor` and the player's `pending_spend_minor` are each lowered by that purchase's `quoted_price_minor`, and the player's own `version` moves by 1."
    PRD §2.5: "Ledger reads accept `currency_account_id`, `season_id`, `purchase_id`, `reversal_of_entry_id`, `direction`, and `source_kind`."

    Design: Corner/endpoints/corner_ep_bulk_action_release_skips_frozen_accounts
    """
    season = create_live_season()

    pb1 = create_player(season["id"], handle="tide_pb1", region_code="NA")
    pb1_soft = open_account(pb1["id"], "SOFT_COIN")
    pb2 = create_player(season["id"], handle="tide_pb2", region_code="EU")
    pb2_soft = open_account(pb2["id"], "SOFT_COIN")
    pb3 = create_player(season["id"], handle="tide_pb3", region_code="NA")
    pb3_soft = open_account(pb3["id"], "SOFT_COIN")
    lock_player(pb3["id"], note="Compliance hold")

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

    assert validate_success(api_client.get_currency_account(pb1_soft["id"], LIVEOPS))[
        "balance_minor"
    ] == 1200
    assert validate_success(api_client.get_currency_account(pb2_soft["id"], LIVEOPS))[
        "balance_minor"
    ] == 1200
    frozen = validate_success(api_client.get_currency_account(pb3_soft["id"], LIVEOPS))
    assert frozen["balance_minor"] == 0
    assert frozen["status"] == "FROZEN"

    assert read_season(season["id"])["gross_faucet_minor"] == 2400

    _, meta = validate_paginated(
        api_client.list_ledger_entries(LIVEOPS, params={"season_id": season["id"]})
    )
    assert meta["total_count"] == 2


def test_purchase_requires_both_referenced_rows_then_links_them_both_ways():
    """A purchase resolves both foreign keys before any link is made, and the fully resolved
    pair is reachable from the player filter and the offer filter alike.

    PRD §2.5: "Identifiers supplied in a request body are resolved after the path identifiers and produce the same not-found codes: `ERR_SEASON_NOT_FOUND`, `ERR_CLUSTER_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`."
    PRD §3.6: "First, the region multiplier is selected from the buyer's `region_code`: North America is the reference at 10000 basis points, Europe is 11000, Latin America is 6500, and Asia-Pacific is 8500."
    PRD §3.6: "On success the purchase is stored in `PENDING` with `quoted_price_minor` and `applied_personalization_bp` pinned from the quote just computed, `price_paid_minor` and `granted_total_minor` and `granted_consumed_minor` at 0, `settled_at` and `deny_reason` null, and `is_minor_purchase` snapshotted from the buyer's `is_minor` flag at this moment so that a later change to the account's minor status cannot rewrite history."
    PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."
    PRD §2.5: "The purchase list accepts `player_id`, `offer_id`, and `status`."

    Design: Corner/endpoints/corner_ep_cross_reference_purchase_binds_player_and_offer
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pl", region_code="NA")
    open_account(player["id"], "HARD_GEM")

    offer = create_approved_offer(
        season["id"],
        offer_type="LIMITED_TIME",
        sku="LINK_PACK",
        price_tier="T1",
        list_price_minor=900,
        line_items=[offer_line_item("LINK_COINS", 900, 1200, "HARD_GEM", 900)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    published = publish_offer(offer["id"], season["id"])
    offer_v = published["version"]

    unknown_offer = api_client.create_purchase(
        {"player_id": player["id"], "offer_id": UNKNOWN_ID, "expected_offer_version": offer_v},
        make_player_headers(player["id"]),
    )
    validate_error(unknown_offer, ApiErrorId.ERR_OFFER_NOT_FOUND)

    unknown_player = api_client.create_purchase(
        {"player_id": UNKNOWN_ID, "offer_id": offer["id"], "expected_offer_version": offer_v},
        make_player_headers(UNKNOWN_ID),
    )
    validate_error(unknown_player, ApiErrorId.ERR_PLAYER_NOT_FOUND)

    purchase = validate_success(
        api_client.create_purchase(
            {
                "player_id": player["id"],
                "offer_id": offer["id"],
                "expected_offer_version": offer_v,
            },
            make_player_headers(player["id"]),
        ),
        201,
    )
    assert purchase["player_id"] == player["id"]
    assert purchase["offer_id"] == offer["id"]
    assert purchase["quoted_price_minor"] == 900
    assert purchase["status"] == "PENDING"

    _, by_player = validate_paginated(
        api_client.list_purchases(LIVEOPS, params={"player_id": player["id"]})
    )
    assert by_player["total_count"] == 1
    _, by_offer = validate_paginated(
        api_client.list_purchases(LIVEOPS, params={"offer_id": offer["id"]})
    )
    assert by_offer["total_count"] == 1

    assert read_offer(offer["id"])["pending_purchase_count"] == 1
    assert read_season(season["id"])["pending_revenue_minor"] == 900


def test_economy_summary_epoch_filter_selects_the_window_it_aggregates():
    """The epoch_no parameter picks which monitoring window the computed read aggregates, and
    the lifetime reading sees every row, so one unchanged ledger yields three answers.

    PRD §3.1: "Alongside the plain season read, an on-demand economy summary is available to all four operator roles. It takes a required `variant` and an optional `epoch_no`, computes the sink-to-faucet ratio fresh without persisting anything, and answers with the `season_id`, the `variant` that was evaluated, the `window_start` and `window_end` of the window it used, the `gross_faucet_minor` and `gross_sink_minor` it summed inside that window, the resulting `sink_faucet_ratio_bp`, the `health_band` that ratio maps to, and — for context, read straight from the stored season — its current `economy_health`, `cadence_debt_days`, `content_posture` and `effective_sink_rate_bp`."
    PRD §3.9: "This is the reading maintained continuously in the season's `lifetime_ratio_bp`, refreshed on every ledger append."
    PRD §3.9: "The on-demand economy summary introduced in §3.1 evaluates either reading on request without persisting anything. For the lifetime-cumulative reading the window covers the whole season. For the epoch-windowed reading the window is selected in one of three ways: when an `epoch_no` is supplied it is the window of that specific run of the season; otherwise it is the window of the run of that season with the highest `epoch_no` whose `status` is `COMPUTED` or `CERTIFIED`; and when the season has no such run, it is the interval from the season's `starts_at` to the current clock."
    PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."
    PRD §3.9: "The health band follows from the ratio: `HEALTHY` when the ratio is at least 6000 basis points, `WATCH` when it is at least 4000 but below 6000, and `INFLATED` when it is below 4000."
    PRD §3.9: "Only the rows whose `occurred_at` falls at or after the window start and strictly before the window end are considered, and on top of that every compensating pair is removed entirely — a row whose `reversal_of_entry_id` is set is dropped, and so is the row it points at."
    PRD §3.9: "The **lifetime-cumulative** reading uses gross semantics: every row of the season counts regardless of `occurred_at`, including compensating rows and the rows they reverse."
    PRD §3.9: "At the first level, the season's `economy_health` is overwritten with the run's `resulting_health`, the season's `cadence_debt_days` and `content_posture` are recomputed, and the season's `version` moves by 1."

    Design: Corner/endpoints/corner_ep_computed_read_economy_summary_epoch_filter
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pc", region_code="NA")
    account = open_account(player["id"], "SOFT_COIN")

    set_clock("2026-08-02T00:00:00Z")
    append_adjustment(account["id"], "FAUCET", 2000, "ADMIN_ADJUSTMENT")
    append_adjustment(account["id"], "SINK", 1000, "OFFER_SPEND")

    set_clock("2026-08-10T00:00:00Z")
    append_adjustment(account["id"], "FAUCET", 1000, "ADMIN_ADJUSTMENT")
    append_adjustment(account["id"], "SINK", 800, "OFFER_SPEND")

    set_clock("2026-08-15T00:00:00Z")
    run1 = open_monitoring_run(
        season["id"],
        epoch_no=1,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
    )
    compute_monitoring_run(run1["id"])
    certify_monitoring_run(run1["id"])
    run2 = open_monitoring_run(
        season["id"],
        epoch_no=2,
        window_start="2026-08-08T00:00:00Z",
        window_end="2026-08-15T00:00:00Z",
    )
    compute_monitoring_run(run2["id"])
    certify_monitoring_run(run2["id"])

    epoch1 = validate_success(
        api_client.get_economy_summary(
            season["id"], DESIGNER, params={"variant": "EPOCH_WINDOWED", "epoch_no": 1}
        )
    )
    assert epoch1["window_start"].startswith("2026-08-01T00:00:00")
    assert epoch1["window_end"].startswith("2026-08-08T00:00:00")
    assert epoch1["gross_faucet_minor"] == 2000
    assert epoch1["gross_sink_minor"] == 1000
    assert epoch1["sink_faucet_ratio_bp"] == 5000
    assert epoch1["health_band"] == "WATCH"

    epoch2 = validate_success(
        api_client.get_economy_summary(
            season["id"], DESIGNER, params={"variant": "EPOCH_WINDOWED", "epoch_no": 2}
        )
    )
    assert epoch2["gross_faucet_minor"] == 1000
    assert epoch2["gross_sink_minor"] == 800
    assert epoch2["sink_faucet_ratio_bp"] == 8000
    assert epoch2["health_band"] == "HEALTHY"

    lifetime = validate_success(
        api_client.get_economy_summary(
            season["id"], DESIGNER, params={"variant": "LIFETIME_CUMULATIVE"}
        )
    )
    assert lifetime["gross_faucet_minor"] == 3000
    assert lifetime["gross_sink_minor"] == 1800
    assert lifetime["sink_faucet_ratio_bp"] == 6000
    assert lifetime["health_band"] == "HEALTHY"
    assert lifetime["effective_sink_rate_bp"] == 10000
    assert lifetime["cadence_debt_days"] == 0
    assert lifetime["content_posture"] == "ON_TRACK"

    assert validate_success(api_client.get_monitoring_run(run1["id"], LIVEOPS))[
        "resulting_health"
    ] == "WATCH"
    assert validate_success(api_client.get_monitoring_run(run2["id"], LIVEOPS))[
        "resulting_health"
    ] == "HEALTHY"

    stored_season = read_season(season["id"])
    assert stored_season["economy_health"] == "HEALTHY"
    assert stored_season["lifetime_ratio_bp"] == 6000


def test_suspended_offer_resumes_only_while_its_window_is_still_open():
    """Resuming a SUSPENDED offer is conditional on the sales window: the offer whose window
    has closed is refused and stays SUSPENDED, while its twin resumes in the same instant.

    PRD §3.5: "Suspending a `LIVE` offer carries it `LIVE → SUSPENDED`, lowers the season's `live_offer_count` by 1, and moves both the season's and the offer's `version` by 1; the same transition also occurs as a system cascade from a monitoring run, as §3.9 describes."
    PRD §3.5: "Resuming carries `SUSPENDED → LIVE` and requires that the clock still be at or before the offer's `window_end` (otherwise `ERR_OFFER_WINDOW_CLOSED`), that the season's `economy_health` not be `INFLATED` (otherwise `ERR_ECONOMY_INFLATED_BLOCK`), and — for a randomized offer — that its `disclosure_state` be `PUBLISHED` rather than `REQUIRED_MISSING` (otherwise `ERR_DISCLOSURE_NOT_PUBLISHED`); it raises `live_offer_count` by 1 and moves both versions by 1."

    Design: Corner/endpoints/corner_ep_conditional_action_resume_only_inside_window
    """
    season = create_live_season()

    short_offer = create_approved_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="SHORT_PACK",
        price_tier="T1",
        list_price_minor=900,
        line_items=[offer_line_item("SHORT_COINS", 900, 1200, "SOFT_COIN", 1200)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
    )
    publish_offer(short_offer["id"], season["id"])

    long_offer = create_approved_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="LONG_PACK",
        price_tier="T1",
        list_price_minor=900,
        line_items=[offer_line_item("LONG_COINS", 900, 1200, "SOFT_COIN", 1200)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    publish_offer(long_offer["id"], season["id"])

    set_clock("2026-08-05T00:00:00Z")
    validate_success(
        api_client.set_offer_availability(
            short_offer["id"], {"to_status": "SUSPENDED", "reason": "Balance review"}, LIVEOPS
        )
    )
    validate_success(
        api_client.set_offer_availability(
            long_offer["id"], {"to_status": "SUSPENDED", "reason": "Balance review"}, LIVEOPS
        )
    )
    set_clock("2026-08-15T00:00:00Z")

    expired = api_client.set_offer_availability(
        short_offer["id"], {"to_status": "LIVE", "reason": "Review cleared"}, LIVEOPS
    )
    validate_error(expired, ApiErrorId.ERR_OFFER_WINDOW_CLOSED)
    assert read_offer(short_offer["id"])["availability_status"] == "SUSPENDED"

    resumed = validate_success(
        api_client.set_offer_availability(long_offer["id"], {"to_status": "LIVE"}, LIVEOPS)
    )
    assert resumed["availability_status"] == "LIVE"
    assert read_offer(long_offer["id"])["availability_status"] == "LIVE"
    assert read_season(season["id"])["live_offer_count"] == 1
