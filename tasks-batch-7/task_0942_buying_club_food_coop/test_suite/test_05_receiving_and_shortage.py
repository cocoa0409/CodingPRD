"""Receiving: the receipt cascade, largest-remainder shortage allocation and
the aggregate capacity rule."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_receipt_line,
    assert_units_conserved,
    canonical_world,
    capture_aggregates,
    create_receipt_line_payload,
    publish_item,
    record_receipt,
    route_run_version,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


def test_receipt_line_cascades_from_receipt_through_route_run_totals(api):
    """PRD §3.6: "The server derives `units_received` on the receipt line as
    `cases_received` multiplied by the `case_pack_units` of the item actually
    received, which is the substitute when one is named and the ordered item
    otherwise, and records the acting `X-User-ID` as `recorded_by_user_id`."
    PRD §3.6: "When supply falls short, each line's exact share is its
    `confirmed_units` multiplied by supply and divided by total demand, treated as
    an exact rational; each line first receives the whole-unit floor of that share;
    the leftover is supply less the sum of those floors; the lines are ranked in
    descending order of the fractional part discarded by the floor, with ties broken
    by ascending `created_at`; and the first however-many lines in that ranking, one
    for each leftover unit, each receive one extra unit."
    PRD §3.6: "Every one of these transitions recomputes the order's `gross_cents`,
    `split_fee_cents`, `tier_discount_cents` and `pre_credit_total_cents`, and the
    affected drop runs and route run recompute their `received_subtotal_cents` — the
    pre-discount value of what was actually allocated, summed as `allocated_units`
    multiplied by `unit_price_cents`."

    Design: Difficulty/transitive_cascade/receipt_line_cascades_from_receipt_through_route_run_totals
    """
    w = canonical_world(api, "aggregates")

    version = route_run_version(api, w, w.route_run_id)
    receipt = validate_success(
        api.create_receipt_line(
            create_receipt_line_payload(
                w.route_run_id, w.aggregates["oat"], 2, version
            ),
            WAREHOUSE,
        ),
        201,
    )
    assert_receipt_line(receipt)
    assert receipt["units_received"] == 8

    aggregate = validate_success(api.get_case_aggregate(w.aggregates["oat"], ADMIN))
    assert aggregate["units_received"] == 8

    mara_oat = validate_success(api.get_order_line(w.lines["mara_oat"], ADMIN))
    assert mara_oat["allocated_units"] == 4
    assert mara_oat["short_units"] == 1
    assert mara_oat["allocation_remainder_rank"] == 1
    assert mara_oat["status"] == "SHORT_FILLED"

    ben_oat = validate_success(api.get_order_line(w.lines["ben_oat"], ADMIN))
    assert ben_oat["allocated_units"] == 4
    assert ben_oat["short_units"] == 2
    assert ben_oat["allocation_remainder_rank"] == 2

    assert_units_conserved([mara_oat, ben_oat], aggregate["units_received"])

    mara_order = validate_success(api.get_member_order(w.order_mara, ADMIN))
    assert mara_order["status"] == "SHORT_FILLED"
    assert mara_order["gross_cents"] == 14784
    ben_order = validate_success(api.get_member_order(w.order_ben, ADMIN))
    assert ben_order["gross_cents"] == 14784

    assert (
        validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["received_subtotal_cents"]
        == 29568
    )
    assert (
        validate_success(api.get_route_run(w.route_run_id, ADMIN))["received_subtotal_cents"]
        == 29568
    )


def test_a_later_receipt_tops_a_short_filled_line_back_up_to_filled(api):
    """PRD §3.6: "A later receipt line topping the aggregate up can move a line
    back `SHORT_FILLED → FILLED`, setting `short_units` to 0."
    PRD §3.6: "When supply is at least total demand, every line receives
    `allocated_units` equal to its `confirmed_units` and an
    `allocation_remainder_rank` of 0."
    PRD §3.6: "In every case `short_units` is `confirmed_units` less
    `allocated_units`, and the sum of `allocated_units` across the aggregate equals
    the smaller of supply and total demand exactly — no unit is invented and none is
    lost."

    Design: Difficulty/transitive_cascade/receipt_line_cascades_from_receipt_through_route_run_totals
    """
    w = canonical_world(api, "aggregates")

    record_receipt(api, w, "berry", 1)
    mara_berry = validate_success(api.get_order_line(w.lines["mara_berry"], ADMIN))
    ben_berry = validate_success(api.get_order_line(w.lines["ben_berry"], ADMIN))
    assert mara_berry["allocated_units"] == 5
    assert mara_berry["short_units"] == 4
    assert mara_berry["allocation_remainder_rank"] == 1
    assert mara_berry["status"] == "SHORT_FILLED"
    assert ben_berry["allocated_units"] == 1
    assert ben_berry["short_units"] == 2
    assert ben_berry["allocation_remainder_rank"] == 2
    assert_units_conserved([mara_berry, ben_berry], 6)

    record_receipt(api, w, "berry", 1)
    mara_berry = validate_success(api.get_order_line(w.lines["mara_berry"], ADMIN))
    ben_berry = validate_success(api.get_order_line(w.lines["ben_berry"], ADMIN))
    assert mara_berry["allocated_units"] == 9
    assert mara_berry["short_units"] == 0
    assert mara_berry["allocation_remainder_rank"] == 0
    assert mara_berry["status"] == "FILLED"
    assert ben_berry["allocated_units"] == 3
    assert ben_berry["status"] == "FILLED"
    assert_units_conserved([mara_berry, ben_berry], 12)


def test_input_set_filtering_excludes_unallocated_lines_from_the_order_gross(api):
    """PRD §3.8: "`gross_cents` is the sum, over the order's lines with status
    `FILLED`, `SHORT_FILLED` or `SUBSTITUTED`, of `allocated_units` multiplied by
    `unit_price_cents`. Lines in `REQUESTED`, `CONFIRMED`, `DROPPED`,
    `ROLLED_FORWARD` or `CANCELLED` contribute 0."
    PRD §3.8: "`tier_discount_cents` is `gross_cents` multiplied by the member's
    `discount_pct`, rounded half up to the whole cent."

    Design: Corner/calculations/input_set_filtering_excludes_unallocated_lines_from_the_order_gross
    """
    w = canonical_world(api, "aggregates")
    record_receipt(api, w, "oat", 2)

    order = validate_success(api.get_member_order(w.order_mara, ADMIN))
    assert order["gross_cents"] == 14784
    assert order["tier_discount_cents"] == 739
    assert order["status"] == "SHORT_FILLED"

    berry = validate_success(api.get_order_line(w.lines["mara_berry"], ADMIN))
    assert berry["status"] == "CONFIRMED"
    assert berry["allocated_units"] == 0

    cheese = validate_success(api.get_order_line(w.lines["mara_cheese"], ADMIN))
    assert cheese["status"] == "CONFIRMED"


def test_receiving_more_than_was_ordered_returns_receipt_exceeds_ordered(api):
    """PRD §3.6: "The aggregate's own `units_received` is the running sum of
    `units_received` over the receipt lines against it, and no receipt may push that
    running total above the aggregate's `covered_units`; an over-receipt is refused
    with `ERR_RECEIPT_EXCEEDS_ORDERED`."

    Design: Corner/validations/receiving_more_than_was_ordered_returns_receipt_exceeds_ordered
    """
    w = canonical_world(api, "aggregates")
    version = route_run_version(api, w, w.route_run_id)

    validate_error(
        api.create_receipt_line(
            create_receipt_line_payload(w.route_run_id, w.aggregates["oat"], 3, version),
            WAREHOUSE,
        ),
        ApiErrorId.ERR_RECEIPT_EXCEEDS_ORDERED.value,
    )

    aggregate = validate_success(api.get_case_aggregate(w.aggregates["oat"], ADMIN))
    assert aggregate["units_received"] == 0
    assert (
        validate_success(api.get_order_line(w.lines["mara_oat"], ADMIN))["status"]
        == "CONFIRMED"
    )
    _, meta = validate_paginated(
        api.list_receipt_lines(ADMIN, params={"route_run_id": w.route_run_id})
    )
    assert meta["total_count"] == 0


def test_recording_a_receipt_before_the_run_is_received_returns_invalid_route_run_state(api):
    """PRD §3.6: "Receipt lines, the supplier invoice and pallet building all
    become available on a run only once it is `RECEIVED`; attempting any of them
    earlier or later fails with `ERR_INVALID_ROUTE_RUN_STATE`."

    Design: Corner/state_machines/recording_a_receipt_before_the_run_is_received_returns_invalid_route_run_state
    """
    w = canonical_world(api, "locked")
    capture_aggregates(api, w)
    version = route_run_version(api, w, w.route_run_id)

    validate_error(
        api.create_receipt_line(
            create_receipt_line_payload(w.route_run_id, w.aggregates["oat"], 2, version),
            WAREHOUSE,
        ),
        ApiErrorId.ERR_INVALID_ROUTE_RUN_STATE.value,
    )

    assert validate_success(api.get_route_run(w.route_run_id, ADMIN))["status"] == "QUALIFIED"
    assert (
        validate_success(api.get_case_aggregate(w.aggregates["oat"], ADMIN))["units_received"]
        == 0
    )


def test_a_substitute_receipt_without_a_substitute_price_returns_validation_error(api):
    """PRD §3.6: "it may also carry a `substitute_item_id` when the supplier
    shipped something else, in which case a `substitute_case_price_cents` of at
    least 1 must accompany it — the pairing is strict in both directions, and a
    substitute price supplied without a substitute item, or a substitute item
    supplied without its price, is refused with `ERR_VALIDATION`."

    Design: Corner/validations/a_substitute_receipt_without_a_substitute_price_returns_validation_error
    """
    w = canonical_world(api, "volunteer_verified", extra_items=("cheddar_sub",))
    capture_aggregates(api, w)
    version = route_run_version(api, w, w.route_run_id)

    validate_error(
        api.create_receipt_line(
            create_receipt_line_payload(
                w.route_run_id,
                w.aggregates["cheese"],
                2,
                version,
                substitute_item_id=w.items["cheddar_sub"],
            ),
            WAREHOUSE,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    _, meta = validate_paginated(
        api.list_receipt_lines(ADMIN, params={"route_run_id": w.route_run_id})
    )
    assert meta["total_count"] == 0
    _, offer_meta = validate_paginated(
        api.list_substitution_offers(
            ADMIN, params={"order_line_id": w.lines["mara_cheese"]}
        )
    )
    assert offer_meta["total_count"] == 0
