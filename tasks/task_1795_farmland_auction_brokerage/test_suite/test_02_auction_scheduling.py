"""Auction scheduling: window well-formedness, per-listing half-open overlap,
and the cross-listing auctioneer buffer (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_auction,
    assert_instant_equal,
    create_auction_payload,
    make_agent_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

AUCTION_START = fx.AUCTION_START  # "2026-08-10T17:00:00Z"
AUCTION_END = fx.AUCTION_END  # "2026-08-10T19:00:00Z"


def test_auction_created_with_soft_close_defaults(api):
    """PRD §3.5: "Creation accepts a `listing_id`, a `method` of `LIVE`,
    `ONLINE`, or `SEALED_BID`, a `scheduled_start`, a `scheduled_end`, and
    optionally `soft_close_window_minutes` and `extension_minutes`, each
    defaulting to 5 and meaningful only for `ONLINE` auctions."
    PRD §3.5: "A new auction begins `SCHEDULED` with `effective_end` equal to
    `scheduled_end`, `extension_count` at zero, and `awarded_total` null until
    an award is made."

    Design: Corner/entities/auction_create_defaults_applied
    """
    env = fx.setup_marketed_listing()
    res = api.create_auction(
        create_auction_payload(env["listing"]["id"], method="ONLINE"),
        make_agent_headers(env["agent"]["id"]),
    )
    auction = validate_success(res, 201)
    assert_auction(auction)
    assert auction["soft_close_window_minutes"] == 5
    assert auction["extension_minutes"] == 5
    assert_instant_equal(auction["effective_end"], AUCTION_END, "effective_end")
    assert auction["extension_count"] == 0
    assert auction["awarded_total"] is None
    assert auction["status"] == "SCHEDULED"


def test_auction_window_violations_rejected(api):
    """PRD §3.5: "First, window well-formedness: `scheduled_end` must be
    strictly after `scheduled_start`, the window must last at least sixty
    minutes, and `scheduled_start` must be no earlier than twenty-four hours
    after the current logical instant — any violation is
    `ERR_AUCTION_WINDOW_INVALID`."
    PRD §3.5: "The caller must be the listing's agent, and the logical clock
    must have reached `scheduled_start` without yet reaching `scheduled_end` —
    opening outside the window is `ERR_AUCTION_WINDOW_INVALID`, and opening from
    any state other than `SCHEDULED` is `ERR_INVALID_AUCTION_STATE`."

    Design: Corner/validations/auction_window_malformed_and_early_open_rejected
    """
    env = fx.setup_marketed_listing()
    headers = make_agent_headers(env["agent"]["id"])

    short = api.create_auction(
        create_auction_payload(
            env["listing"]["id"],
            method="LIVE",
            scheduled_start=AUCTION_START,
            scheduled_end="2026-08-10T17:30:00Z",
        ),
        headers,
    )
    validate_error(short, ApiErrorId.ERR_AUCTION_WINDOW_INVALID)  # 30-minute window

    early = api.create_auction(
        create_auction_payload(
            env["listing"]["id"],
            method="LIVE",
            scheduled_start="2026-08-01T12:00:00Z",
            scheduled_end="2026-08-01T14:00:00Z",
        ),
        headers,
    )
    # start precedes clock 2026-08-01T00:00:00Z + 24h
    validate_error(early, ApiErrorId.ERR_AUCTION_WINDOW_INVALID)

    auction = fx.schedule_auction(env["agent"], env["listing"]["id"], method="LIVE")
    opened = api.open_auction(auction["id"], headers)
    # clock is still 2026-08-01T00:00:00Z, before scheduled_start
    validate_error(opened, ApiErrorId.ERR_AUCTION_WINDOW_INVALID)


def test_listing_windows_adjacent_accepted(api):
    """PRD §3.5: "Second, per-listing overlap: the windows of this listing's
    auctions in `SCHEDULED`, `OPEN`, `EXTENDED`, or `CLOSED_PENDING_AWARD` must
    be disjoint half-open intervals, so a new window that starts exactly when an
    existing window ends is permitted adjacency, while true overlap is rejected
    with `ERR_LISTING_AUCTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/listing_windows_half_open_adjacency_permitted
    """
    env = fx.setup_marketed_listing(
        title="L4", total_gross_acres=80, reserve_price_total=460000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 80, "tillable_acres": 40,
            "soil_productivity_index": 60, "min_price": 200000,
        }],
    )
    first = fx.schedule_auction(
        env["agent"], env["listing"]["id"], method="LIVE",
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T12:00:00Z",
    )
    assert first["status"] == "SCHEDULED"
    # Adjacent half-open window: starts exactly when the first ends.
    second = fx.schedule_auction(
        env["agent"], env["listing"]["id"], method="LIVE",
        scheduled_start="2026-08-12T12:00:00Z", scheduled_end="2026-08-12T14:00:00Z",
    )
    assert second["status"] == "SCHEDULED", (
        "adjacency [10:00,12:00) then [12:00,14:00) must be permitted"
    )


def test_listing_windows_true_overlap_rejected(api):
    """PRD §3.5: "Second, per-listing overlap: the windows of this listing's
    auctions in `SCHEDULED`, `OPEN`, `EXTENDED`, or `CLOSED_PENDING_AWARD` must
    be disjoint half-open intervals, so a new window that starts exactly when an
    existing window ends is permitted adjacency, while true overlap is rejected
    with `ERR_LISTING_AUCTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/listing_windows_half_open_adjacency_permitted
    """
    env = fx.setup_marketed_listing(
        title="L4", total_gross_acres=80, reserve_price_total=460000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 80, "tillable_acres": 40,
            "soil_productivity_index": 60, "min_price": 200000,
        }],
    )
    fx.schedule_auction(
        env["agent"], env["listing"]["id"], method="LIVE",
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T12:00:00Z",
    )
    fx.schedule_auction(
        env["agent"], env["listing"]["id"], method="LIVE",
        scheduled_start="2026-08-12T12:00:00Z", scheduled_end="2026-08-12T14:00:00Z",
    )
    res = api.create_auction(
        create_auction_payload(
            env["listing"]["id"], method="LIVE",
            scheduled_start="2026-08-12T11:00:00Z",
            scheduled_end="2026-08-12T13:00:00Z",
        ),
        make_agent_headers(env["agent"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LISTING_AUCTION_OVERLAP)


def test_auctioneer_buffer_below_two_hours_rejected(api):
    """PRD §3.5: "against any such auction in `SCHEDULED`, `OPEN`, `EXTENDED`,
    or `CLOSED_PENDING_AWARD`, the new window is rejected with
    `ERR_AUCTIONEER_SCHEDULE_CONFLICT` when it begins before the moment two
    hours after the existing window's end and simultaneously ends after the
    moment two hours before the existing window's start; because both
    comparisons are strict, a gap of exactly two hours on either side passes."

    Design: Difficulty/resource_temporal_overlap/auctioneer_two_hour_buffer_across_listings
    """
    seller, agent = fx.make_parties()
    l4 = fx.setup_marketed_listing(
        agent=agent, seller=seller, title="L4", total_gross_acres=80,
        reserve_price_total=460000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 80, "tillable_acres": 40,
            "soil_productivity_index": 60, "min_price": 200000,
        }],
    )
    l5 = fx.setup_marketed_listing(
        agent=agent, seller=seller, title="L5", total_gross_acres=40,
        reserve_price_total=310000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 40, "tillable_acres": 40,
            "soil_productivity_index": 80, "min_price": 100000,
        }],
        comparables="none",
    )
    fx.schedule_auction(
        agent, l4["listing"]["id"], method="LIVE",
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T12:00:00Z",
    )
    # Different listing, same agent: 13:30 begins before 12:00 + 2h.
    res = api.create_auction(
        create_auction_payload(
            l5["listing"]["id"], method="LIVE",
            scheduled_start="2026-08-12T13:30:00Z",
            scheduled_end="2026-08-12T15:00:00Z",
        ),
        make_agent_headers(agent["id"]),
    )
    validate_error(res, ApiErrorId.ERR_AUCTIONEER_SCHEDULE_CONFLICT)


def test_auctioneer_buffer_exactly_two_hours_accepted(api):
    """PRD §3.5: "against any such auction in `SCHEDULED`, `OPEN`, `EXTENDED`,
    or `CLOSED_PENDING_AWARD`, the new window is rejected with
    `ERR_AUCTIONEER_SCHEDULE_CONFLICT` when it begins before the moment two
    hours after the existing window's end and simultaneously ends after the
    moment two hours before the existing window's start; because both
    comparisons are strict, a gap of exactly two hours on either side passes."

    Design: Difficulty/resource_temporal_overlap/auctioneer_two_hour_buffer_across_listings
    """
    seller, agent = fx.make_parties()
    l4 = fx.setup_marketed_listing(
        agent=agent, seller=seller, title="L4", total_gross_acres=80,
        reserve_price_total=460000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 80, "tillable_acres": 40,
            "soil_productivity_index": 60, "min_price": 200000,
        }],
    )
    l5 = fx.setup_marketed_listing(
        agent=agent, seller=seller, title="L5", total_gross_acres=40,
        reserve_price_total=310000,
        tract_specs=[{
            "tract_number": 1, "gross_acres": 40, "tillable_acres": 40,
            "soil_productivity_index": 80, "min_price": 100000,
        }],
        comparables="none",
    )
    fx.schedule_auction(
        agent, l4["listing"]["id"], method="LIVE",
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T12:00:00Z",
    )
    # Exactly a two-hour gap (14:00 == 12:00 + 2h) passes the buffer.
    auction = fx.schedule_auction(
        agent, l5["listing"]["id"], method="LIVE",
        scheduled_start="2026-08-12T14:00:00Z", scheduled_end="2026-08-12T16:00:00Z",
    )
    assert auction["status"] == "SCHEDULED"
