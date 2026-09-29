"""Two shared resources with deliberately opposite interval conventions.

An extrusion line is a closed interval widened by a thirty-minute changeover
buffer at both ends, so two windows that merely touch still collide and the
boundary value is refused. A reel is half-open with no buffer at all, so a load
starting exactly at the instant the reel came back is accepted. The value that
is rejected on the line is precisely the value that is accepted on the reel.
"""

from test_helpers import (
    BILLING,
    CLERK,
    ENGINEER,
    advance_lot_to_extruded,
    advance_lot_to_tested,
    assert_lot_dimensions,
    assert_money,
    assert_reel_return,
    create_lot,
    create_production_lot_payload,
    create_reel,
    create_reel_return_payload,
    create_shipment_payload,
    current_order_version,
    current_rod_lot_version,
    get_success_data,
    load_reel_payload,
    read_lot,
    read_reel,
    read_rod_lot,
    release_lot,
    scrap_lot,
    set_clock,
    setup_baseline,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULING_WORLD = {
    "order_overrides": {"order_number": "SO-SCH", "ordered_kft": 20.000},
    "rod_overrides": {"heat_number": "H-77Q", "purchase_weight_lbs": 20000.00},
}
# The incumbent occupies EXT-1 from 08:00 to 12:00 on 2026-08-02, so the
# forbidden zone for that line runs from 07:30 to 12:30 exclusive at both ends.
INCUMBENT_WINDOW = {
    "line_code": "EXT-1",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T12:00:00Z",
}
OFF_CENTRE_EXTRUSION = {"measured_min_wall_mils": 23.0}
OCCUPANCY_WORLD = {
    "order_overrides": {"order_number": "SO-OCC", "ordered_kft": 10.000},
    "rod_overrides": {"purchase_weight_lbs": 20000.00},
}
SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T12:00:00Z",
}


def _scheduling_world(api):
    """A plant with one 2000 ft lot already holding EXT-1 from 08:00 to 12:00."""
    world = setup_baseline(api, **SCHEDULING_WORLD)
    incumbent = create_lot(
        api, world, lot_code="LOT-SCH-1", planned_length_ft=2000, **INCUMBENT_WINDOW
    )
    assert_money(incumbent["consumed_rod_lbs"], 39.60, "2.0 kft at 19.8 lbs per kft")
    return world, incumbent


def _schedule(api, world, rod_version, **overrides):
    """Attempt one scheduling request and hand back the raw response."""
    payload = create_production_lot_payload(
        world["product"]["id"], world["rod_lot"]["id"], rod_version,
        order_id=world["order"]["id"], planned_length_ft=2000, **overrides,
    )
    return api.create_production_lot(payload, ENGINEER)


def _lots_on_line(api, line_code):
    rows, _ = validate_paginated(
        api.list_production_lots(ENGINEER, {"line_code": line_code})
    )
    return rows


def _returned_reel_world(api):
    """A reel back in the fleet at exactly 2026-08-10T09:00:00Z, plus a second
    CONFORMING lot waiting to take it.

    Returns ``(reel, second_lot, reel_return)``.
    """
    world = setup_baseline(api, **OCCUPANCY_WORLD)
    order = world["order"]
    get_success_data(api.price_lock_customer_order(order["id"], BILLING))

    lots = []
    for lot_code, overrides in (
        ("LOT-OCC-A", INCUMBENT_WINDOW), ("LOT-OCC-B", SECOND_LINE_WINDOW),
    ):
        lot = create_lot(
            api, world, lot_code=lot_code, planned_length_ft=5000, **overrides
        )
        advance_lot_to_tested(api, lot["id"])
        release_lot(api, lot["id"], 5000)
        lots.append(read_lot(api, lot["id"]))

    reel = create_reel(api, reel_serial="R-OCC")
    get_success_data(
        api.load_reel(
            reel["id"],
            load_reel_payload(lots[0]["id"], 5000,
                              occupancy_start_at="2026-08-03T00:00:00Z"),
            CLERK,
        )
    )

    set_clock(api, "2026-08-05T10:00:00Z")
    shipment = validate_success(
        api.create_shipment(
            create_shipment_payload(
                order["id"], lots[0]["id"], reel["id"], 5000,
                current_order_version(api, order["id"]), ship_date="2026-08-05",
            ),
            CLERK,
        ),
        201,
    )
    get_success_data(api.invoice_shipment(shipment["id"], BILLING))

    set_clock(api, "2026-08-10T09:00:00Z")
    reel_return = get_success_data(
        api.create_reel_return(
            reel["id"],
            create_reel_return_payload(shipment["id"], "2026-08-10", "GOOD"),
            CLERK,
        )
    )
    return read_reel(api, reel["id"]), lots[1], reel_return


def test_a_window_inside_the_late_changeover_buffer_collides_and_the_boundary_clears(
    api,
):
    """Twenty minutes after the incumbent ends is a collision, one second short of
    the thirty-minute buffer is still a collision, and 12:30:00 exactly is
    accepted — and neither refusal spent a pound of rod or a version.

    PRD 3.6: "The requested window must clear every *other* production lot on the
    same `line_code` whose process dimension is neither `SHIPPED` nor
    `SCRAP_CLOSED` by at least a thirty-minute changeover buffer at both ends."

    PRD 3.6: "Concretely, the request is refused when the new lot's start is
    earlier than the other lot's end advanced by thirty minutes *and* the other
    lot's start is earlier than the new lot's end advanced by thirty minutes; when
    either of those two conditions fails, the windows are far enough apart and the
    schedule is accepted."

    PRD 2.6: "If the supplied value does not equal that rod lot's current
    `version`, the request is rejected with `ERR_STALE_ROD_LOT_VERSION` (HTTP 412)
    and nothing is created."

    Design: Difficulty/resource_temporal_overlap/extrusion_line_buffered_closed_interval
    """
    world, _ = _scheduling_world(api)
    rod_version = current_rod_lot_version(api, world["rod_lot"]["id"])

    validate_error(
        _schedule(
            api, world, rod_version, lot_code="LOT-SCH-LATE-BAD", line_code="EXT-1",
            scheduled_start_at="2026-08-02T12:20:00Z",
            scheduled_end_at="2026-08-02T14:20:00Z",
        ),
        "ERR_LINE_SCHEDULE_CONFLICT", 409,
    )
    validate_error(
        _schedule(
            api, world, rod_version, lot_code="LOT-SCH-LATE-EDGE", line_code="EXT-1",
            scheduled_start_at="2026-08-02T12:29:59Z",
            scheduled_end_at="2026-08-02T14:29:59Z",
        ),
        "ERR_LINE_SCHEDULE_CONFLICT", 409,
    )

    after_refusals = read_rod_lot(api, world["rod_lot"]["id"])
    assert after_refusals["version"] == rod_version, (
        "two refused schedules mutated nothing, so the version the client holds is "
        "still the current one"
    )
    assert_money(after_refusals["committed_lbs"], 39.60, "only the incumbent's mass")

    accepted = validate_success(
        _schedule(
            api, world, rod_version, lot_code="LOT-SCH-LATE-OK", line_code="EXT-1",
            scheduled_start_at="2026-08-02T12:30:00Z",
            scheduled_end_at="2026-08-02T14:30:00Z",
        ),
        201,
    )
    assert accepted["scheduled_start_at"] == "2026-08-02T12:30:00Z", (
        "a start exactly on the buffer is not earlier than the buffer, so the "
        "windows are far enough apart"
    )
    assert_lot_dimensions(accepted, "QUEUED", "PENDING")
    assert_money(
        read_rod_lot(api, world["rod_lot"]["id"])["committed_lbs"], 79.20,
        "two lots of 39.60 each",
    )


def test_a_window_inside_the_early_changeover_buffer_collides_the_same_way(api):
    """The buffer is symmetric: a lot that ends at 07:31, one minute inside the
    zone in front of the incumbent, is refused, and the same lot ending at 07:30
    exactly is scheduled.

    PRD 3.6: "Concretely, the request is refused when the new lot's start is
    earlier than the other lot's end advanced by thirty minutes *and* the other
    lot's start is earlier than the new lot's end advanced by thirty minutes; when
    either of those two conditions fails, the windows are far enough apart and the
    schedule is accepted."

    PRD 3.6: "A collision is reported as `ERR_LINE_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/extrusion_line_buffered_closed_interval
    """
    world, incumbent = _scheduling_world(api)
    rod_version = current_rod_lot_version(api, world["rod_lot"]["id"])

    validate_error(
        _schedule(
            api, world, rod_version, lot_code="LOT-SCH-EARLY-BAD", line_code="EXT-1",
            scheduled_start_at="2026-08-02T04:00:00Z",
            scheduled_end_at="2026-08-02T07:31:00Z",
        ),
        "ERR_LINE_SCHEDULE_CONFLICT", 409,
    )
    assert len(_lots_on_line(api, "EXT-1")) == 1, (
        "the refused lot was never written, so the line still holds one lot"
    )

    accepted = validate_success(
        _schedule(
            api, world, rod_version, lot_code="LOT-SCH-EARLY-OK", line_code="EXT-1",
            scheduled_start_at="2026-08-02T04:00:00Z",
            scheduled_end_at="2026-08-02T07:30:00Z",
        ),
        201,
    )
    assert accepted["scheduled_end_at"] == "2026-08-02T07:30:00Z", (
        "the incumbent's 08:00 start is not earlier than 07:30 advanced by thirty "
        "minutes, so one of the two conditions fails and the schedule is accepted"
    )
    assert accepted["traceability_code"] == "H-77Q-LOT-SCH-EARLY-OK", (
        "a scheduled lot can always be walked back to the heat it draws from"
    )
    assert incumbent["traceability_code"] == "H-77Q-LOT-SCH-1"


def test_the_line_is_the_resource_and_not_the_plant(api):
    """The identical 08:00 to 12:00 window is taken on EXT-2 with no complaint at
    all, and the line filter then reports three lots on the crowded line against
    one on the quiet one.

    PRD 3.6: "`line_code` names the extrusion line the lot will occupy and is the
    resource key for occupancy conflicts, while `scheduled_start_at` and
    `scheduled_end_at` bound that occupancy as ISO 8601 UTC instants;
    `scheduled_end_at` must be strictly after `scheduled_start_at`, and a window
    that is not is rejected with `ERR_INVALID_REQUEST`."

    PRD 3.6: "Lots may be listed and narrowed by `product_id`, by `rod_lot_id`, by
    `order_id`, by `line_code`, by `process_state` and by `quality_state`."

    Design: Difficulty/resource_temporal_overlap/extrusion_line_buffered_closed_interval
    """
    world, _ = _scheduling_world(api)

    for lot_code, start, end in (
        ("LOT-SCH-EARLY-OK", "2026-08-02T04:00:00Z", "2026-08-02T07:30:00Z"),
        ("LOT-SCH-LATE-OK", "2026-08-02T12:30:00Z", "2026-08-02T14:30:00Z"),
    ):
        validate_success(
            _schedule(
                api, world, current_rod_lot_version(api, world["rod_lot"]["id"]),
                lot_code=lot_code, line_code="EXT-1",
                scheduled_start_at=start, scheduled_end_at=end,
            ),
            201,
        )

    other_line = validate_success(
        _schedule(
            api, world, current_rod_lot_version(api, world["rod_lot"]["id"]),
            lot_code="LOT-SCH-OTHERLINE", **SECOND_LINE_WINDOW,
        ),
        201,
    )
    assert other_line["line_code"] == "EXT-2"
    assert other_line["scheduled_start_at"] == "2026-08-02T08:00:00Z", (
        "the window the incumbent holds on EXT-1 is free on EXT-2"
    )

    crowded = _lots_on_line(api, "EXT-1")
    assert sorted(row["lot_code"] for row in crowded) == [
        "LOT-SCH-1", "LOT-SCH-EARLY-OK", "LOT-SCH-LATE-OK",
    ], "exactly the three lots the buffer left room for"
    quiet = _lots_on_line(api, "EXT-2")
    assert [row["lot_code"] for row in quiet] == ["LOT-SCH-OTHERLINE"]


def test_a_scrapped_lot_stops_holding_the_slot_it_was_booked_into(api):
    """Scrapping the incumbent takes it off the line, and the window it used to
    occupy — start for start and end for end — is then scheduled to a fresh lot.

    PRD 3.7: "A `SCRAPPED` disposition is available from process states `DRAWN`,
    `STRANDED`, `EXTRUDED` and `TESTED`. It sets the process dimension to
    `SCRAP_CLOSED` and the quality dimension to `SCRAPPED`, incrementing `version`
    by one, and then runs three cascade hops."

    PRD 3.6: "Lots already at `SHIPPED` or `SCRAP_CLOSED` are off the line and are
    ignored by this check entirely."

    Design: Difficulty/resource_temporal_overlap/extrusion_line_buffered_closed_interval
    """
    world, incumbent = _scheduling_world(api)
    advance_lot_to_extruded(
        api, incumbent["id"], extrusion_overrides=OFF_CENTRE_EXTRUSION
    )
    assert_lot_dimensions(read_lot(api, incumbent["id"]), "EXTRUDED", "NONCONFORMING")

    scrap_lot(api, incumbent["id"], reason="off centre beyond recovery")
    closed = read_lot(api, incumbent["id"])
    assert_lot_dimensions(closed, "SCRAP_CLOSED", "SCRAPPED")

    replacement = validate_success(
        _schedule(
            api, world, current_rod_lot_version(api, world["rod_lot"]["id"]),
            lot_code="LOT-SCH-REPLACEMENT", **INCUMBENT_WINDOW,
        ),
        201,
    )
    assert replacement["scheduled_start_at"] == closed["scheduled_start_at"], (
        "the replacement takes the scrapped lot's exact start"
    )
    assert replacement["scheduled_end_at"] == closed["scheduled_end_at"], (
        "and its exact end, because a closed lot is no longer on the line"
    )
    assert len(_lots_on_line(api, "EXT-1")) == 2, (
        "the scrapped lot stays on the line's history even though it no longer "
        "blocks the window"
    )


def test_a_load_one_second_before_the_return_instant_is_refused(api):
    """The return stamps the reel's lower bound from the logical clock, and a load
    claiming the reel one second earlier than that instant is refused while the
    waiting lot stays exactly at `TESTED`.

    PRD 3.8: "Reel occupancy is **half-open with no buffer**: when the reel has a
    `returned_at` instant recorded, the requested `occupancy_start_at` must be at
    or after that instant, so a load starting exactly at the previous return
    instant is accepted and a load starting even a moment earlier is refused with
    `ERR_REEL_OCCUPANCY_OVERLAP`."

    PRD 3.9: "`returned_at` is stamped with the logical-clock instant and becomes
    the exclusive lower bound for the reel's next occupancy; `last_return_condition`
    records the reported `condition`; `cycle_count` is incremented by one; and
    `current_lot_id`, `held_by_customer_id` and `loaded_length_ft` are cleared to
    null, null and 0 respectively."

    PRD 3.9: "A `WOOD_RETURNABLE` reel returned in `GOOD` condition follows a flat
    step schedule recorded as `FLAT_STEP`: the whole `deposit_usd` is refunded when
    `days_out` is at most 90; half the deposit, rounded half up to two decimals, is
    refunded when `days_out` is greater than 90 and at most 180; and nothing is
    refunded once `days_out` exceeds 180."

    Design: Difficulty/resource_temporal_overlap/reel_occupancy_half_open_at_return_instant
    """
    reel, waiting_lot, reel_return = _returned_reel_world(api)

    assert reel["returned_at"].startswith("2026-08-10T09:00:00"), (
        "the boundary is the clock's instant, not anything the client supplied, "
        f"got {reel['returned_at']!r}"
    )
    assert reel["status"] == "AVAILABLE"
    assert reel["cycle_count"] == 1
    assert reel["loaded_length_ft"] == 0

    assert_reel_return(reel_return)
    assert reel_return["days_out"] == 5, "2026-08-05 out to 2026-08-10 back"
    assert reel_return["refund_variant_applied"] == "FLAT_STEP"
    assert_money(reel_return["refund_usd"], 450.00, "5 days is at most 90")
    assert_money(reel_return["forfeited_usd"], 0.00, "nothing is kept back")

    validate_error(
        api.load_reel(
            reel["id"],
            load_reel_payload(waiting_lot["id"], 5000,
                              occupancy_start_at="2026-08-10T08:59:59Z"),
            CLERK,
        ),
        "ERR_REEL_OCCUPANCY_OVERLAP", 409,
    )

    assert_lot_dimensions(read_lot(api, waiting_lot["id"]), "TESTED", "CONFORMING")
    untouched = read_reel(api, reel["id"])
    assert untouched["status"] == "AVAILABLE", "the refused load left the reel free"
    assert untouched["current_lot_id"] is None
    assert untouched["version"] == reel["version"]


def test_a_load_exactly_at_the_return_instant_is_accepted(api):
    """One second later the same request is a valid claim on the reel: the
    half-open boundary belongs to the new occupancy, and no changeover buffer
    stands in front of it.

    PRD 3.8: "Reel occupancy is **half-open with no buffer**: when the reel has a
    `returned_at` instant recorded, the requested `occupancy_start_at` must be at
    or after that instant, so a load starting exactly at the previous return
    instant is accepted and a load starting even a moment earlier is refused with
    `ERR_REEL_OCCUPANCY_OVERLAP`."

    PRD 3.8: "A successful load sets `current_lot_id` to the loaded lot,
    increases `loaded_length_ft` by `load_length_ft`, records `occupancy_start_at`
    verbatim from the request, and clears `occupancy_end_at`, `shipped_at` and
    `returned_at` back to null so the reel's new occupancy starts clean."

    PRD 3.8: "The loaded lot simultaneously advances its process dimension
    `TESTED` → `PACKAGED` with its own `version` incremented by one; its
    `packaged_length_ft` is *not* re-derived here, because that figure was fixed by
    the quality engineer at release."

    Design: Difficulty/resource_temporal_overlap/reel_occupancy_half_open_at_return_instant
    """
    reel, waiting_lot, _ = _returned_reel_world(api)
    validate_error(
        api.load_reel(
            reel["id"],
            load_reel_payload(waiting_lot["id"], 5000,
                              occupancy_start_at="2026-08-10T08:59:59Z"),
            CLERK,
        ),
        "ERR_REEL_OCCUPANCY_OVERLAP", 409,
    )

    loaded = validate_success(
        api.load_reel(
            reel["id"],
            load_reel_payload(waiting_lot["id"], 5000,
                              occupancy_start_at="2026-08-10T09:00:00Z"),
            CLERK,
        ),
        200,
    )

    assert loaded["status"] == "LOADED"
    assert loaded["current_lot_id"] == waiting_lot["id"]
    assert loaded["loaded_length_ft"] == 5000
    assert loaded["occupancy_start_at"] == "2026-08-10T09:00:00Z", (
        "zero minutes after the reel came back is close enough, because this "
        "resource carries no changeover buffer"
    )
    assert loaded["returned_at"] is None, "the new occupancy starts clean"
    assert loaded["shipped_at"] is None
    assert loaded["cycle_count"] == 1, "loading is not a cycle"

    packaged = read_lot(api, waiting_lot["id"])
    assert_lot_dimensions(packaged, "PACKAGED", "CONFORMING")
    assert packaged["packaged_length_ft"] == 5000, (
        "the figure the quality engineer certified is not re-derived at loading"
    )
    assert packaged["version"] > waiting_lot["version"]


def test_a_reel_that_has_never_been_returned_has_no_lower_bound_at_all(api):
    """The occupancy check is skipped outright on a fresh reel rather than
    defaulting its boundary to some epoch, so an occupancy claimed months before
    the logical clock is accepted.

    PRD 3.8: "A reel that has never been returned has no lower bound."

    PRD 3.8: "A registered reel begins at `AVAILABLE` with `loaded_length_ft` at 0,
    `cycle_count` at 0, and `current_lot_id`, `held_by_customer_id`,
    `occupancy_start_at`, `occupancy_end_at`, `shipped_at`, `returned_at` and
    `last_return_condition` all null or zero as applicable."

    Design: Difficulty/resource_temporal_overlap/reel_occupancy_half_open_at_return_instant
    """
    _, waiting_lot, _ = _returned_reel_world(api)

    fresh = create_reel(api, reel_serial="R-FRESH")
    assert fresh["returned_at"] is None, "a brand-new reel has never come back"
    assert fresh["status"] == "AVAILABLE"
    assert fresh["cycle_count"] == 0

    loaded = validate_success(
        api.load_reel(
            fresh["id"],
            load_reel_payload(waiting_lot["id"], 5000,
                              occupancy_start_at="2026-01-01T00:00:00Z"),
            CLERK,
        ),
        200,
    )
    assert loaded["occupancy_start_at"] == "2026-01-01T00:00:00Z", (
        "with no returned_at there is nothing to compare against, so the instant "
        "is recorded verbatim"
    )
    assert loaded["status"] == "LOADED"
    assert loaded["current_lot_id"] == waiting_lot["id"]
    assert_lot_dimensions(read_lot(api, waiting_lot["id"]), "PACKAGED", "CONFORMING")
