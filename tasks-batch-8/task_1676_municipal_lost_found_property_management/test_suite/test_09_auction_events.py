"""Auction events: windows, venue calendars, settle gates, cancel cascade
(PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_auction_event_payload,
    create_event,
    create_lot,
    create_venue,
    create_program,
    get_event,
    get_item,
    get_lot,
    make_auction_coordinator_headers,
    set_clock,
    setup_auction_eligible_item,
    setup_event_with_lot,
    setup_lot_with_eligible_item,
    publish_lot,
    add_lot_item,
    validate_error,
    validate_success,
)

COORD_1 = make_auction_coordinator_headers("coord-1")


def test_venue_adjacent_windows_book_successfully(api):
    """PRD §3.8: "adjacency is allowed, so an event may begin exactly when
    another ends or end exactly when another begins."

    Design: Difficulty/resource_temporal_overlap/venue_half_open_interval_adjacency
    """
    program = create_program("TRANSIT")
    venue = create_venue(program["id"])
    e1 = create_event(program["id"], venue["id"], name="E1",
                      starts_at="2026-09-01T10:00:00Z",
                      ends_at="2026-09-01T12:00:00Z")
    e2 = create_event(program["id"], venue["id"], name="E2",
                      starts_at="2026-09-01T12:00:00Z",
                      ends_at="2026-09-01T14:00:00Z")
    assert e1["status"] == "SCHEDULED" and e2["status"] == "SCHEDULED", (
        "half-open windows [10:00, 12:00) and [12:00, 14:00) touch but do not overlap")


def test_venue_one_second_overlap_rejected(api):
    """PRD §3.8: "the new event's half-open window — from `starts_at` inclusive
    up to but not including `ends_at` — may not overlap any other `SCHEDULED` or
    `COMPLETED` event at the same venue, else `ERR_VENUE_DOUBLE_BOOKED`".

    Design: Difficulty/resource_temporal_overlap/venue_half_open_interval_adjacency
    """
    program = create_program("TRANSIT")
    venue = create_venue(program["id"])
    create_event(program["id"], venue["id"], name="E1",
                 starts_at="2026-09-01T10:00:00Z", ends_at="2026-09-01T12:00:00Z")

    res = api.create_auction_event(
        create_auction_event_payload(
            venue["id"], program["id"], name="E3",
            starts_at="2026-09-01T11:59:59Z", ends_at="2026-09-01T13:00:00Z"),
        COORD_1)
    validate_error(res, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED, expected_status=409)


def test_event_equal_window_rejected(api):
    """PRD §3.8: "The window must be well-formed: `ends_at` strictly after
    `starts_at`, else `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/errors/err_invalid_time_window_rejected
    """
    program = create_program("TRANSIT")
    venue = create_venue(program["id"])
    res = api.create_auction_event(
        create_auction_event_payload(
            venue["id"], program["id"], name="Bad Window",
            starts_at="2026-09-01T10:00:00Z", ends_at="2026-09-01T10:00:00Z"),
        COORD_1)
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW, expected_status=422)


def test_event_settle_before_end_rejected(api):
    """PRD §3.8: "the logical clock must have reached the event's `ends_at`
    (`ERR_EVENT_STILL_OPEN`)".

    Design: Corner/errors/err_event_still_open_rejected
    """
    program = create_program("TRANSIT")
    venue = create_venue(program["id"])
    event = create_event(program["id"], venue["id"])
    set_clock("2026-08-20T11:00:00Z")  # one hour before ends_at 12:00

    res = api.settle_auction_event(event["id"], COORD_1)
    validate_error(res, ApiErrorId.ERR_EVENT_STILL_OPEN, expected_status=409)
    assert get_event(event["id"])["status"] == "SCHEDULED"


def test_event_settle_with_published_lot_rejected(api):
    """PRD §3.8: "every lot of the event must be in `SOLD`, `CLOSED_UNSOLD`, or
    `CANCELLED` (`ERR_LOTS_NOT_FINAL`)".

    Design: Corner/state_machines/event_settle_with_open_lots_rejected
    """
    ctx = setup_lot_with_eligible_item(declared_value_cents=9000)
    publish_lot(ctx.lot["id"])
    set_clock("2026-08-21T00:00:00Z")  # past ends_at, so only the lots gate fires

    res = api.settle_auction_event(ctx.event["id"], COORD_1)
    validate_error(res, ApiErrorId.ERR_LOTS_NOT_FINAL, expected_status=409)
    assert get_event(ctx.event["id"])["status"] == "SCHEDULED"


def test_event_cancel_returns_items_and_empties_lot(api):
    """PRD §3.8: "Cancelling a `SCHEDULED` event cascades: every one of its lots
    in `DRAFT` or `PUBLISHED` becomes `CANCELLED`, every item lotted in those
    lots returns from `LOTTED` to `AUCTION_ELIGIBLE` with no change to
    `unsold_count`, their membership rows are deleted, each affected lot's
    `minimum_bid_cents` is recomputed to zero".

    Design: Corner/cross_cutting_layers/cascading_event_cancel_returns_items
    """
    ctx = setup_lot_with_eligible_item(declared_value_cents=5005)
    publish_lot(ctx.lot["id"])
    assert get_item(ctx.item["id"])["status"] == "LOTTED"

    cancelled = validate_success(api.cancel_auction_event(ctx.event["id"], COORD_1), 200)
    assert cancelled["status"] == "CANCELLED"

    lot = get_lot(ctx.lot["id"])
    assert lot["status"] == "CANCELLED"
    assert lot["minimum_bid_cents"] == 0, (
        "the cancelled lot's membership rows are deleted and the minimum recomputed")

    item = get_item(ctx.item["id"])
    assert item["status"] == "AUCTION_ELIGIBLE"
    assert item["unsold_count"] == 0, (
        "event cancellation never increments unsold_count")
