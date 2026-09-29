"""Two shared resources booked over time under opposite interval conventions.

Bench windows are closed and padded by the rig's cooldown on both sides, so
touching endpoints collide. Loaner windows are half-open, so back-to-back
bookings are legal.
"""
from test_helpers import (
    ApiErrorId,
    INTAKE_CLERK,
    TECHNICIAN_1,
    api_client,
    book_loaner,
    create_loaner_assignment_payload,
    create_shell_test_payload,
    get_success_data,
    read_loaner_unit,
    read_unit,
    schedule_shell_test,
    setup_inspected_units,
    setup_loaner_assignment,
    validate_error,
)


def _bench_sessions(bench_id):
    """Every session booked on one rig, newest page first."""
    return get_success_data(
        api_client.list_shell_tests(TECHNICIAN_1, params={"test_bench_id": bench_id})
    )


def _loaner_assignments(loaner_unit_id):
    """Every assignment recorded against one loaner."""
    return get_success_data(
        api_client.list_loaner_assignments(
            INTAKE_CLERK, params={"loaner_unit_id": loaner_unit_id}
        )
    )


def test_bench_windows_inside_the_cooldown_padding_collide_even_when_they_only_touch():
    """Against a 09:00-10:00 session on a rig with a 45-minute cooldown, a
    10:30 start collides outright and a 10:45 start collides because its padded
    start touches the existing end.

    PRD §3.5: "The first is a cooldown envelope: the requested window is expanded
    by the bench's `cooldown_minutes` on *both* sides, and if that expanded
    interval intersects the window of any existing session on the same bench, the
    booking is rejected with `ERR_BENCH_WINDOW_CONFLICT` (HTTP 409). Both
    intervals are treated as closed, so windows that merely touch at an endpoint
    do collide."

    Design: Difficulty/resource_temporal_overlap/bench_sessions_collide_across_closed_cooldown_padded_windows
    """
    ctx = setup_inspected_units(unit_count=2)
    bench = ctx["bench"]
    assert bench["cooldown_minutes"] == 45
    schedule_shell_test(
        ctx["units"][0]["id"], bench["id"], "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z"
    )

    for window_start, window_end in (
        ("2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z"),
        ("2026-08-01T10:45:00Z", "2026-08-01T11:45:00Z"),
    ):
        response = api_client.create_shell_test(
            create_shell_test_payload(
                ctx["units"][1]["id"],
                bench["id"],
                window_start=window_start,
                window_end=window_end,
            ),
            TECHNICIAN_1,
        )
        validate_error(response, ApiErrorId.ERR_BENCH_WINDOW_CONFLICT, 409)

    assert len(_bench_sessions(bench["id"])) == 1


def test_a_window_clear_of_the_padding_on_both_sides_is_booked():
    """An 11:00 start pads back only to 10:15, a clear hour after the existing
    session ended, so the rig accepts it as the second unit's first attempt.

    PRD §3.5: "With the default cooldown of 45 minutes — three quarters of an hour
    of rig recovery on each side — two sessions on the same rig must therefore be
    separated by more than an hour and a half of clear time."

    Design: Difficulty/resource_temporal_overlap/bench_sessions_collide_across_closed_cooldown_padded_windows
    """
    ctx = setup_inspected_units(unit_count=2)
    bench = ctx["bench"]
    schedule_shell_test(
        ctx["units"][0]["id"], bench["id"], "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z"
    )

    session = schedule_shell_test(
        ctx["units"][1]["id"], bench["id"], "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z"
    )

    assert session["status"] == "SCHEDULED"
    assert session["window_start"][:19] == "2026-08-01T11:00:00"
    assert session["attempt_index"] == 1
    assert len(_bench_sessions(bench["id"])) == 2
    assert read_unit(ctx["units"][1]["id"])["retest_count"] == 0


def test_a_loaner_booking_that_starts_where_another_ends_is_not_an_overlap():
    """A loan running 12 to 19 August butts up against one running 5 to 12 August,
    and half-open windows make that a legal back-to-back booking.

    PRD §3.9: "If that loaner already carries an assignment in `RESERVED` or
    `OUT_ON_LOAN` status whose window intersects the requested window — treating
    both windows as half-open, so a booking that ends exactly when another begins
    is not an overlap — the request is refused with `ERR_LOANER_DOUBLE_BOOKED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/loaner_windows_allow_adjacency_but_reject_overlap
    """
    ctx = setup_loaner_assignment(explicit=True)
    loaner_id = ctx["loaner"]["id"]

    adjacent = book_loaner(
        ctx["account"]["id"],
        ctx["model"]["id"],
        loaner_unit_id=loaner_id,
        window_start="2026-08-12T00:00:00Z",
        window_end="2026-08-19T00:00:00Z",
    )

    assert adjacent["status"] == "RESERVED"
    assert adjacent["selected_by"] == "EXPLICIT"
    assert adjacent["loaner_unit_id"] == loaner_id

    loaner = read_loaner_unit(loaner_id)
    assert loaner["assignment_count"] == 2
    assert loaner["status"] == "RESERVED"
    assert len(_loaner_assignments(loaner_id)) == 2


def test_a_loaner_booking_that_overlaps_an_existing_window_by_a_day_is_refused():
    """A loan running 11 to 18 August covers a day already promised, so the plant
    refuses it with ERR_LOANER_DOUBLE_BOOKED and books nothing.

    PRD §3.9: "If that loaner already carries an assignment in `RESERVED` or
    `OUT_ON_LOAN` status whose window intersects the requested window — treating
    both windows as half-open, so a booking that ends exactly when another begins
    is not an overlap — the request is refused with `ERR_LOANER_DOUBLE_BOOKED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/loaner_windows_allow_adjacency_but_reject_overlap
    """
    ctx = setup_loaner_assignment(explicit=True)
    loaner_id = ctx["loaner"]["id"]

    response = api_client.create_loaner_assignment(
        create_loaner_assignment_payload(
            ctx["account"]["id"],
            ctx["model"]["id"],
            loaner_unit_id=loaner_id,
            window_start="2026-08-11T00:00:00Z",
            window_end="2026-08-18T00:00:00Z",
        ),
        INTAKE_CLERK,
    )

    validate_error(response, ApiErrorId.ERR_LOANER_DOUBLE_BOOKED, 409)
    assert read_loaner_unit(loaner_id)["assignment_count"] == 1
    assert len(_loaner_assignments(loaner_id)) == 1
