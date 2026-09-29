"""The two interval conventions, tested on their exact endpoints.

Supplier slot windows are half-open, inflated by a changeover buffer on both
sides, and collide pairwise; inspection-bay windows are closed and collide only
when the summed committee size passes the bay's capacity.
"""

from test_helpers import (
    BuildStatus,
    ErrorCode,
    ReservationStatus,
    TripStatus,
    assert_slot_occupancy,
    assert_unit_dimensions,
    create_active_program,
    create_plant_bay,
    create_slot_line,
    make_program_admin_headers,
    read_slot_line,
    read_trip,
    read_unit,
    reserve_slot,
    setup_awarded_unit,
    validate_error,
    validate_success,
)


PUMP_CLAUSE = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
]

# The occupying hold, and the inflated window the buffer gives it.
OCCUPYING_START = "2026-09-01T00:00:00Z"
OCCUPYING_END = "2026-09-15T00:00:00Z"


def _line_with_one_occupying_window(api):
    """One four-slot line carrying a single RESERVED hold over 09-01 .. 09-15.

    With the default seven-day changeover buffer that hold's inflated window
    runs 2026-08-25 to 2026-09-22.
    """
    program = create_active_program(api, name="Slot geometry program",
                                    agency_name="Cedar Fire",
                                    max_option_units=1)
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=4)
    first = reserve_slot(api, program["id"], line["id"],
                         slot_start_date=OCCUPYING_START,
                         slot_end_date=OCCUPYING_END)
    return {"program_id": program["id"], "line_id": line["id"],
            "first_id": first["id"],
            "version": read_slot_line(api, line["id"])["version"]}


def _booking(program_id, line_id, version, start, end):
    return {"program_id": program_id, "slot_line_id": line_id,
            "slot_start_date": start, "slot_end_date": end,
            "reserved_price_cents": 30_000_000,
            "expiry_at": "2026-12-01T00:00:00Z",
            "expected_slot_line_version": version}


def _unit_and_bay(api):
    """One SPEC_LOCKED pumper and one bay rated for ten concurrent visitors."""
    ctx = setup_awarded_unit(
        api,
        program_overrides={"name": "Bay capacity program",
                           "agency_name": "Ridgeway Fire",
                           "max_option_units": 1},
        clauses=PUMP_CLAUSE,
    )
    bay = create_plant_bay(api, name="Bay C", max_concurrent_visitors=10)
    ctx["bay_id"] = bay["id"]
    return ctx


def _trip(unit_id, bay_id, start, end, committee_size):
    return {"unit_order_id": unit_id, "plant_bay_id": bay_id,
            "trip_type": "PRE_CONSTRUCTION", "scheduled_start": start,
            "scheduled_end": end, "committee_size": committee_size}


def test_the_changeover_buffer_pushes_the_first_admissible_start_seven_days_out(
        api, admin_headers):
    """Back-to-back is a collision, and so is one day short of the buffer.

    PRD 3.6: "Each existing reservation on the same line whose `status` is
    `RESERVED`, `CONFIRMED` or `CONSUMED` is considered in turn, and its window is
    *inflated on both sides* by the line's `changeover_buffer_days`... The
    comparison against the inflated window is half-open: a conflict exists when the
    new `slot_start_date` is strictly earlier than the inflated end *and* the
    inflated start is strictly earlier than the new `slot_end_date`."
    PRD 3.6: "With the default seven-day buffer, back-to-back windows do conflict —
    a new window starting exactly on an existing window's `slot_end_date` collides,
    and the earliest admissible start is seven days after that existing end."

    Design: Difficulty/resource_temporal_overlap/slot_window_half_open_comparison_with_seven_day_changeover_buffer
    """
    ctx = _line_with_one_occupying_window(api)
    admin = make_program_admin_headers()

    for start, end in (
        ("2026-09-15T00:00:00Z", "2026-09-29T00:00:00Z"),
        ("2026-09-21T00:00:00Z", "2026-10-05T00:00:00Z"),
        ("2026-08-01T00:00:00Z", "2026-08-26T00:00:00Z"),
    ):
        validate_error(
            api.create_chassis_reservation(
                _booking(ctx["program_id"], ctx["line_id"], ctx["version"],
                         start, end),
                admin,
            ),
            ErrorCode.ERR_SLOT_WINDOW_CONFLICT,
            409,
        )

    line = read_slot_line(api, ctx["line_id"])
    assert_slot_occupancy(line, reserved=1, available=3, total=4)
    assert line["version"] == ctx["version"], line
    assert line["changeover_buffer_days"] == 7, line


def test_a_window_ending_on_the_inflated_start_and_one_starting_on_the_buffer_pass(
        api, admin_headers):
    """Two windows land exactly on the geometry and are both admitted.

    PRD 3.6: "a conflict exists when the new `slot_start_date` is strictly earlier
    than the inflated end *and* the inflated start is strictly earlier than the new
    `slot_end_date`."
    PRD 3.6: "`reserved_slot_count` is the number of that line's reservations whose
    `status` is `RESERVED`, `CONFIRMED` or `CONSUMED`; `available_slot_count` is
    `total_slot_count` minus `reserved_slot_count`."
    PRD 3.6: "A reservation with no `unit_order_id` is an unassigned speculative
    hold."

    Design: Difficulty/resource_temporal_overlap/slot_window_half_open_comparison_with_seven_day_changeover_buffer
    """
    ctx = _line_with_one_occupying_window(api)
    admin = make_program_admin_headers()

    trailing = validate_success(
        api.create_chassis_reservation(
            _booking(ctx["program_id"], ctx["line_id"], ctx["version"],
                     "2026-08-01T00:00:00Z", "2026-08-25T00:00:00Z"),
            admin,
        ),
        201,
    )
    assert trailing["status"] == ReservationStatus.RESERVED.value, trailing
    second_version = read_slot_line(api, ctx["line_id"])["version"]
    assert second_version == ctx["version"] + 1, second_version

    leading = validate_success(
        api.create_chassis_reservation(
            _booking(ctx["program_id"], ctx["line_id"], second_version,
                     "2026-09-22T00:00:00Z", "2026-10-06T00:00:00Z"),
            admin,
        ),
        201,
    )
    assert leading["status"] == ReservationStatus.RESERVED.value, leading
    assert leading["unit_order_id"] is None, leading
    assert trailing["unit_order_id"] is None, trailing

    line = read_slot_line(api, ctx["line_id"])
    assert_slot_occupancy(line, reserved=3, available=1, total=4)
    assert line["version"] == ctx["version"] + 2, line


def test_the_bay_admits_a_summed_committee_that_lands_exactly_on_capacity(
        api, admin_headers):
    """Six plus six is refused, six plus four is admitted on the same window.

    PRD 3.7: "The server sums the `committee_size` of every trip in the same bay
    whose `status` is `SCHEDULED` or `HELD` and whose window intersects the
    requested window, adds the new `committee_size`, and admits the trip only if
    that sum is at most the bay's `max_concurrent_visitors`. A sum exactly equal to
    the capacity is admitted; anything above it is refused with
    `ERR_BAY_CAPACITY_EXCEEDED`."
    PRD 3.7: "A pairwise overlap on its own is not a conflict — two overlapping
    trips of six visitors each are perfectly fine in a bay rated for twelve."

    Design: Difficulty/resource_temporal_overlap/bay_aggregate_capacity_over_closed_touching_windows
    """
    ctx = _unit_and_bay(api)
    window = ("2026-08-10T08:00:00Z", "2026-08-10T16:00:00Z")

    first = validate_success(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], *window, committee_size=6),
            admin_headers,
        ),
        201,
    )
    assert first["status"] == TripStatus.SCHEDULED.value, first

    validate_error(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], *window, committee_size=6),
            admin_headers,
        ),
        ErrorCode.ERR_BAY_CAPACITY_EXCEEDED,
        409,
    )

    on_the_line = validate_success(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], *window, committee_size=4),
            admin_headers,
        ),
        201,
    )
    assert on_the_line["status"] == TripStatus.SCHEDULED.value, on_the_line
    assert on_the_line["committee_size"] == 4, on_the_line
    assert on_the_line["held_at"] is None, on_the_line


def test_touching_bay_windows_intersect_and_a_cancellation_returns_the_visitors(
        api, admin_headers):
    """One second decides an intersection, and a cancellation refills the pool.

    PRD 3.7: "Two trips collide when their closed windows intersect, and touching
    endpoints do intersect: an existing trip whose `scheduled_end` falls exactly on
    the new trip's `scheduled_start` is a collision."
    PRD 3.7: "`CANCELLED` trips are excluded from the sum, which is precisely why
    cancelling a trip frees capacity for a later booking. Datetimes in this
    comparison are evaluated at second resolution in UTC."

    Design: Difficulty/resource_temporal_overlap/bay_aggregate_capacity_over_closed_touching_windows
    """
    ctx = _unit_and_bay(api)
    window = ("2026-08-10T08:00:00Z", "2026-08-10T16:00:00Z")
    filled = validate_success(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], *window, committee_size=6),
            admin_headers,
        ),
        201,
    )
    remainder = validate_success(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], *window, committee_size=4),
            admin_headers,
        ),
        201,
    )

    validate_error(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], "2026-08-10T16:00:00Z",
                  "2026-08-10T17:00:00Z", committee_size=1),
            admin_headers,
        ),
        ErrorCode.ERR_BAY_CAPACITY_EXCEEDED,
        409,
    )

    one_second_clear = validate_success(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], "2026-08-10T16:00:01Z",
                  "2026-08-10T18:00:00Z", committee_size=1),
            admin_headers,
        ),
        201,
    )

    cancelled = validate_success(
        api.cancel_inspection_trip(filled["id"], admin_headers)
    )
    assert cancelled["status"] == TripStatus.CANCELLED.value, cancelled

    retried = validate_success(
        api.create_inspection_trip(
            _trip(ctx["unit_id"], ctx["bay_id"], "2026-08-10T16:00:00Z",
                  "2026-08-10T17:00:00Z", committee_size=1),
            admin_headers,
        ),
        201,
    )

    for trip in (remainder, one_second_clear, retried):
        assert read_trip(api, trip["id"])["status"] == TripStatus.SCHEDULED.value
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.SPEC_LOCKED.value)
