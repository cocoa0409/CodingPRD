"""The three deliberately divergent occupancy conventions of a booked cycle.

PRD.md section 2.9 opens with the warning that drives this module: "A moulding
cycle books three resources over time, and the three use deliberately different
boundary conventions. Implementers must not unify them."

Each convention is asserted on its own terms and never borrowed from a
neighbour: the oven arm is exclusive, half-open and buffered symmetrically on
the *stored* span; the cooling bay is an aggregate count over a closed span
with no buffer at all; and the mould is exclusive and half-open over the union
of the oven and cooling phases, again with no buffer.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    assert_cycle_window_projection,
    assert_instant_equals,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    get_success_data,
    mold_payload,
    molding_cycle_payload,
    production_order_version,
    unique_code,
    validate_error,
)


def _p2_interval_plant(
    *,
    mold_count: int = 3,
    arm_count: int = 4,
    changeover_buffer_min: int = 15,
    slot_capacity: int = 4,
    ordered_qty: int = 3,
) -> dict:
    """A plant whose mould pool ranks deterministically by ``mold_code``.

    The tools are created with codes that sort MZA before MZB before MZC, which
    is the total order PRD.md section 3.4 selects on once every candidate ties
    on ``cycles_since_service``. Every tool is single-cavity, so one cycle books
    one hull and the overbuild ceiling of PRD.md section 3.3 leaves room for
    ``ordered_qty`` cycles.
    """
    codes = [unique_code(prefix) for prefix in ("MZA", "MZB", "MZC")][:mold_count]
    ctx = create_plant_baseline(
        model_overrides={"nominal_charge_kg": 24.0},
        mold_overrides={"cavity_count": 1, "mold_code": codes[0]},
        station_overrides={
            "arm_count": arm_count,
            "changeover_buffer_min": changeover_buffer_min,
        },
        bay_overrides={"concurrent_slot_capacity": slot_capacity},
    )
    molds = [ctx["mold"]]
    for code in codes[1:]:
        molds.append(
            get_success_data(
                api_client.create_mold(
                    mold_payload(
                        ctx["product_model_id"], cavity_count=1, mold_code=code
                    ),
                    ADMIN_HEADERS,
                )
            )
        )
    ctx["molds"] = molds
    ctx["resin_lot"] = create_resin_lot()
    order = create_production_order(ctx, ordered_qty=ordered_qty)
    ctx["production_order"] = order
    ctx["production_order_id"] = order["id"]
    return ctx


def _p2_book(ctx: dict, *, arm_index: int, oven_start_at: str):
    """Attempt one booking on ``arm_index`` opening its oven leg at the instant."""
    payload = molding_cycle_payload(
        ctx["production_order_id"],
        ctx["oven_station_id"],
        ctx["cooling_bay_id"],
        production_order_version(ctx["production_order_id"]),
        arm_index=arm_index,
        oven_start_at=oven_start_at,
    )
    return api_client.create_molding_cycle(payload, ctx["operator_headers"])


def _p2_cycle_count(ctx: dict) -> int:
    """How many cycle rows the order owns right now."""
    rows = api_client.list_molding_cycles(
        {"production_order_id": ctx["production_order_id"], "limit": 100},
        ctx["operator_headers"],
    ).json()["data"]
    return len(rows)


def test_oven_arm_booking_one_second_inside_the_buffered_span_is_refused():
    """A start one second before end-plus-buffer overlaps the stored arm span.

    PRD.md section 2.9: "Occupancy is the half-open span from `oven_start_at` up
    to but not including `oven_end_at`. The station's `changeover_buffer_min` is
    applied symmetrically to both ends of each *already-stored* cycle's span -
    never to the candidate's - so the buffer is counted exactly once per
    comparison." And: "Because the span is half-open, a new cycle whose
    `oven_start_at` equals an existing cycle's `oven_end_at` plus the buffer, to
    the second, is accepted, while one starting a second earlier is refused."

    PRD.md section 3.4 names the refusal and the write-nothing guarantee: "a
    single overlap refuses the booking with `ERR_OVEN_WINDOW_CONFLICT`" and "A
    refused booking writes nothing at all - no cycle row, no order version bump."

    Design: Difficulty/resource_temporal_overlap/oven_arm_half_open_span_with_symmetric_changeover_buffer
    """
    ctx = _p2_interval_plant(arm_count=2, changeover_buffer_min=15, slot_capacity=4)

    first = get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    assert_instant_equals(first["oven_end_at"], "2026-08-01T10:00:00Z", "oven_end_at")
    assert_instant_equals(
        first["cooling_window_start_at"],
        "2026-08-01T10:00:00Z",
        "cooling_window_start_at",
    )
    assert_instant_equals(
        first["cooling_window_end_at"],
        "2026-08-01T10:30:00Z",
        "cooling_window_end_at",
    )
    assert_cycle_window_projection(first)
    assert first["status"] == "SCHEDULED"
    assert first["mold_id"] == ctx["molds"][0]["id"]

    order_version = production_order_version(ctx["production_order_id"])

    # The stored span [09:00:00, 10:00:00) inflates to [08:45:00, 10:15:00), and
    # the candidate's half-open span opens one second inside it.
    validate_error(
        _p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T10:14:59Z"),
        ApiErrorId.OVEN_WINDOW_CONFLICT,
        409,
    )

    assert production_order_version(ctx["production_order_id"]) == order_version
    assert _p2_cycle_count(ctx) == 1


def test_oven_arm_booking_exactly_at_the_buffered_end_instant_is_accepted():
    """Touching the buffered upper edge is not overlapping it.

    PRD.md section 2.9: "Because the span is half-open, a new cycle whose
    `oven_start_at` equals an existing cycle's `oven_end_at` plus the buffer, to
    the second, is accepted, while one starting a second earlier is refused."

    The mould answer diverges in the same breath. PRD.md section 2.9: "The
    **mould** is exclusive over the union of both phases: the half-open span from
    `oven_start_at` up to but not including `cooling_window_end_at`" - so at
    10:15:00 the arm is free while the first tool is still busy until 10:30:00,
    and PRD.md section 3.4's ranking, "ascending `cycles_since_service`, then
    ascending `mold_code`", hands over the second tool.

    Design: Difficulty/resource_temporal_overlap/oven_arm_half_open_span_with_symmetric_changeover_buffer
    """
    ctx = _p2_interval_plant(arm_count=2, changeover_buffer_min=15, slot_capacity=4)
    first = get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    assert first["mold_id"] == ctx["molds"][0]["id"]

    second = get_success_data(
        _p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T10:15:00Z")
    )

    assert second["status"] == "SCHEDULED"
    assert second["arm_index"] == 1
    assert second["mold_id"] == ctx["molds"][1]["id"], (
        "the arm is free at 10:15:00 but the first tool is occupied until 10:30:00"
    )
    assert_instant_equals(
        second["oven_start_at"], "2026-08-01T10:15:00Z", "oven_start_at"
    )
    assert _p2_cycle_count(ctx) == 2


def test_two_arms_of_one_station_hold_fully_coincident_oven_windows():
    """The exclusive unit is the arm, not the station.

    PRD.md section 2.9: "The **oven arm** is an exclusive resource, and the
    resource is the arm rather than the station: cycles sharing an
    `oven_station_id` but holding different `arm_index` values never conflict, so
    a station whose `arm_count` is 4 can hold four fully coincident windows."

    PRD.md section 3.4 repeats it for the booking check - "Cycles on a different
    `arm_index` of the same station never conflict" - and fixes the order edge:
    "the order moves `READY_TO_SCHEDULE` to `IN_PRODUCTION` on the first accepted
    cycle."

    Design: Difficulty/resource_temporal_overlap/oven_arm_half_open_span_with_symmetric_changeover_buffer
    """
    ctx = _p2_interval_plant(arm_count=2, changeover_buffer_min=15, slot_capacity=4)
    first = get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T10:15:00Z"))

    coincident = get_success_data(
        _p2_book(ctx, arm_index=2, oven_start_at="2026-08-01T09:00:00Z")
    )

    assert coincident["arm_index"] == 2
    assert_instant_equals(
        coincident["oven_start_at"], first["oven_start_at"], "oven_start_at"
    )
    assert coincident["mold_id"] == ctx["molds"][2]["id"], (
        "the first two tools are occupied across 09:00-10:30, so the third is taken"
    )
    assert _p2_cycle_count(ctx) == 3

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["status"] == "IN_PRODUCTION"


def test_cooling_windows_touching_at_one_instant_both_hold_slots_of_a_two_slot_bay():
    """A window opening exactly where another closes still intersects it.

    PRD.md section 2.9: "the interval tested is the closed span from
    `cooling_window_start_at` through `cooling_window_end_at` inclusive. Because
    the interval is closed, a new window whose start equals an existing window's
    end to the second *does* intersect and consumes a slot, which is the exact
    opposite of the arm rule."

    The same sentence fixes what a capacity of two admits: "When the count of
    intersecting cycles has already reached the bay's `concurrent_slot_capacity`,
    the booking is refused ...; a bay whose capacity is 2 therefore accepts a
    second overlapping cycle and refuses the third."

    Design: Difficulty/resource_temporal_overlap/cooling_bay_closed_interval_aggregate_slot_capacity
    """
    ctx = _p2_interval_plant(arm_count=4, changeover_buffer_min=15, slot_capacity=2)

    first = get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    assert_instant_equals(
        first["cooling_window_start_at"],
        "2026-08-01T10:00:00Z",
        "cooling_window_start_at",
    )
    assert_instant_equals(
        first["cooling_window_end_at"],
        "2026-08-01T10:30:00Z",
        "cooling_window_end_at",
    )

    second = get_success_data(
        _p2_book(ctx, arm_index=2, oven_start_at="2026-08-01T09:30:00Z")
    )

    assert_instant_equals(
        second["cooling_window_start_at"],
        "2026-08-01T10:30:00Z",
        "cooling_window_start_at",
    )
    assert_instant_equals(
        second["cooling_window_end_at"],
        "2026-08-01T11:00:00Z",
        "cooling_window_end_at",
    )
    assert second["status"] == "SCHEDULED"
    assert second["mold_id"] == ctx["molds"][1]["id"], (
        "the first tool's half-open span [09:00, 10:30) overlaps [09:30, 11:00)"
    )


def test_third_cycle_intersecting_two_closed_cooling_windows_is_refused():
    """The bay constraint is collective, so two legal windows still bar a third.

    PRD.md section 2.9: "When the count of intersecting cycles has already
    reached the bay's `concurrent_slot_capacity`, the booking is refused with
    `ERR_COOLING_BAY_CAPACITY_EXCEEDED` (HTTP 409) ... The constraint is
    collective, so every individual window can be legal and the booking still
    fail."

    PRD.md section 3.4 pins the cause to the bay alone by ordering the checks -
    "Then the oven arm window, then the bay slot count, then the mould pool" -
    and guarantees "A refused booking writes nothing at all - no cycle row, no
    order version bump."

    Design: Difficulty/resource_temporal_overlap/cooling_bay_closed_interval_aggregate_slot_capacity
    """
    ctx = _p2_interval_plant(arm_count=4, changeover_buffer_min=15, slot_capacity=2)
    get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    get_success_data(_p2_book(ctx, arm_index=2, oven_start_at="2026-08-01T09:30:00Z"))
    order_version = production_order_version(ctx["production_order_id"])

    # The candidate's closed span [10:30:00, 11:00:00] touches the first window
    # at the single instant 10:30:00 and covers the second entirely, so the
    # intersecting count is already 2. Arm 3 is empty and the third tool is
    # free, so neither the arm rule nor the mould pool can be the cause.
    validate_error(
        _p2_book(ctx, arm_index=3, oven_start_at="2026-08-01T09:30:00Z"),
        ApiErrorId.COOLING_BAY_CAPACITY_EXCEEDED,
        409,
    )

    assert production_order_version(ctx["production_order_id"]) == order_version
    assert _p2_cycle_count(ctx) == 2


def test_shifting_one_second_past_the_touching_instant_frees_a_cooling_slot():
    """One second of separation drops the intersecting count back below capacity.

    PRD.md section 2.9: "the interval tested is the closed span from
    `cooling_window_start_at` through `cooling_window_end_at` inclusive. Because
    the interval is closed, a new window whose start equals an existing window's
    end to the second *does* intersect and consumes a slot" - so a start one
    second later no longer touches the earlier window and only the fully
    overlapping cycle is counted, which is below the bay's capacity of 2.

    Design: Difficulty/resource_temporal_overlap/cooling_bay_closed_interval_aggregate_slot_capacity
    """
    ctx = _p2_interval_plant(arm_count=4, changeover_buffer_min=15, slot_capacity=2)
    get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    get_success_data(_p2_book(ctx, arm_index=2, oven_start_at="2026-08-01T09:30:00Z"))

    third = get_success_data(
        _p2_book(ctx, arm_index=3, oven_start_at="2026-08-01T09:30:01Z")
    )

    assert_instant_equals(
        third["cooling_window_start_at"],
        "2026-08-01T10:30:01Z",
        "cooling_window_start_at",
    )
    assert third["status"] == "SCHEDULED"
    assert third["mold_id"] == ctx["molds"][2]["id"]
    assert _p2_cycle_count(ctx) == 3

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["status"] == "IN_PRODUCTION"


def test_mold_span_covers_cooling_so_an_overlap_reports_a_window_conflict():
    """The mould is busy past its oven leg, and the refusal names the overlap.

    PRD.md section 2.9: "The **mould** is exclusive over the union of both
    phases: the half-open span from `oven_start_at` up to but not including
    `cooling_window_end_at`, evaluated against cycles in `SCHEDULED`,
    `OVEN_RUNNING` or `COOLING`."

    PRD.md section 3.4 keeps the two 409s apart: "if at least one tool for this
    hull model is in `status` `AVAILABLE` but every such tool was removed by the
    occupancy clause, the request fails with `ERR_MOLD_WINDOW_CONFLICT`
    (HTTP 409)". No buffer appears anywhere in the mould rule, so 10:29:59 is
    still inside the span even though the arm has been free since 10:15:00.

    Design: Difficulty/resource_temporal_overlap/mold_half_open_oven_plus_cooling_span_occupancy_vs_capability
    """
    ctx = _p2_interval_plant(
        mold_count=1, arm_count=4, changeover_buffer_min=15, slot_capacity=4
    )
    only_mold = ctx["molds"][0]

    first = get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    assert first["mold_id"] == only_mold["id"]
    assert_instant_equals(
        first["cooling_window_end_at"],
        "2026-08-01T10:30:00Z",
        "cooling_window_end_at",
    )

    order_version = production_order_version(ctx["production_order_id"])

    # Arm 2 is empty and the bay holds four slots, so only the mould rule can
    # refuse this booking.
    validate_error(
        _p2_book(ctx, arm_index=2, oven_start_at="2026-08-01T10:29:59Z"),
        ApiErrorId.MOLD_WINDOW_CONFLICT,
        409,
    )

    assert production_order_version(ctx["production_order_id"]) == order_version
    assert _p2_cycle_count(ctx) == 1
    still_available = api_client.read_entity(
        "get_mold", only_mold["id"], ctx["admin_headers"]
    )
    assert still_available["status"] == "AVAILABLE"


def test_mold_is_reselected_at_the_exact_end_of_its_half_open_span():
    """One second later the same tool is free again, with no buffer applied.

    PRD.md section 2.9: "A new cycle whose `oven_start_at` equals an existing
    cycle's `cooling_window_end_at` to the second is accepted."

    PRD.md section 3.5 explains why the tool is still selectable at all: the
    mould only leaves `AVAILABLE` when the oven starts, and no oven has started
    here - PRD.md section 3.4 requires the candidate pool to hold tools "whose
    `status` is exactly `AVAILABLE`".

    Design: Difficulty/resource_temporal_overlap/mold_half_open_oven_plus_cooling_span_occupancy_vs_capability
    """
    ctx = _p2_interval_plant(
        mold_count=1, arm_count=4, changeover_buffer_min=15, slot_capacity=4
    )
    only_mold = ctx["molds"][0]
    get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))

    second = get_success_data(
        _p2_book(ctx, arm_index=2, oven_start_at="2026-08-01T10:30:00Z")
    )

    assert second["mold_id"] == only_mold["id"]
    assert second["status"] == "SCHEDULED"
    assert _p2_cycle_count(ctx) == 2
    refreshed = api_client.read_entity(
        "get_mold", only_mold["id"], ctx["admin_headers"]
    )
    assert refreshed["status"] == "AVAILABLE"


def test_empty_available_mold_pool_reports_a_capability_failure_not_a_window_conflict():
    """With no AVAILABLE tool left, an unoccupied window still fails.

    PRD.md section 3.1 makes the service hold a cascade head: "From `AVAILABLE`,
    a service hold moves the tool to `MAINTENANCE` ... every cycle on that tool
    still in `SCHEDULED` becomes `ABORTED` with `abort_reason`
    `MOLD_SERVICE_DUE`".

    PRD.md section 3.4 then chooses the other 409: "otherwise - no available tool
    at all, or an `exclude_mold_ids` list that emptied the pool - it fails with
    `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)", the pool having been filtered on tools
    "whose `status` is exactly `AVAILABLE` - `MAINTENANCE`, `IN_CYCLE` and
    `RETIRED` tools are excluded before ranking".

    Design: Difficulty/resource_temporal_overlap/mold_half_open_oven_plus_cooling_span_occupancy_vs_capability
    """
    ctx = _p2_interval_plant(
        mold_count=1, arm_count=4, changeover_buffer_min=15, slot_capacity=4
    )
    only_mold = ctx["molds"][0]
    first = get_success_data(_p2_book(ctx, arm_index=1, oven_start_at="2026-08-01T09:00:00Z"))
    second = get_success_data(_p2_book(ctx, arm_index=2, oven_start_at="2026-08-01T10:30:00Z"))

    held = get_success_data(
        api_client.service_hold_mold(
            only_mold["id"],
            {"hold_note": "Interval pulled forward for a cavity re-polish"},
            ADMIN_HEADERS,
        )
    )
    assert held["status"] == "MAINTENANCE"

    for cycle_id in (first["id"], second["id"]):
        aborted = api_client.read_entity(
            "get_molding_cycle", cycle_id, ctx["operator_headers"]
        )
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "MOLD_SERVICE_DUE"

    # 14:00:00 is a wholly unoccupied window, so the refusal cannot be an
    # occupancy failure; the pool simply holds no AVAILABLE tool any more.
    validate_error(
        _p2_book(ctx, arm_index=4, oven_start_at="2026-08-01T14:00:00Z"),
        ApiErrorId.NO_ELIGIBLE_MOLD,
        409,
    )
