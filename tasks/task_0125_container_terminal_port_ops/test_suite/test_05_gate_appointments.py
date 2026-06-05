"""Gate appointments: booking, the buffered slot clash, check-in window,
no-show/reschedule cycle, the no-show cap, cancel, and listing-by-container.

Difficulty instances: non_linear_state_machine (no-show/reschedule cycle),
resource_temporal_overlap (gate buffered adjacency conflicts). Corner instances:
check-in outside window, no-show before window_end, reschedule cap, cancel,
list-by-container.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["terminal_admin_headers"]
GATE = TEST_USERS["gate_operator_headers"]


# --------------------------------------------------------------------------- #
# No-show / reschedule cycle — non_linear_state_machine
# --------------------------------------------------------------------------- #
def test_no_show_reschedule_cycle_increments_count(api):
    """PRD §3.4: "A no-show increments the appointment's `no_show_count` by one and
    increments its `version`."
    PRD §3.4: "On success the appointment adopts the new `window_start` and
    `window_end`, returns to `BOOKED`, and increments `version`."

    Design: Difficulty/non_linear_state_machine/gate_appointment_noshow_reschedule_cycle
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    appt = fx.book_appointment(
        container["id"], window_start="2026-03-01T10:00:00.000Z", window_end="2026-03-01T11:00:00.000Z"
    )
    fx.set_clock("2026-03-01T11:30:00.000Z")  # slot fully elapsed
    fx.get_success_data(api.mark_no_show(appt["id"], GATE))
    rescheduled = validate_success(
        api.reschedule_gate_appointment(
            appt["id"],
            {"window_start": "2026-03-02T10:00:00.000Z", "window_end": "2026-03-02T11:00:00.000Z"},
            GATE,
        ),
        200,
    )
    assert rescheduled["status"] == "BOOKED"
    assert rescheduled["no_show_count"] == 1
    assert rescheduled["window_start"] == "2026-03-02T10:00:00.000Z"


def test_mark_no_show_sets_no_show_state_and_count(api):
    """PRD §3.4: "If the slot fully elapses with no arrival, the operator **marks a
    no-show**, moving a `BOOKED` appointment to `NO_SHOW` ... A no-show increments
    the appointment's `no_show_count` by one".

    Design: Difficulty/non_linear_state_machine/gate_appointment_noshow_reschedule_cycle
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    appt = fx.book_appointment(
        container["id"], window_start="2026-03-01T10:00:00.000Z", window_end="2026-03-01T11:00:00.000Z"
    )
    fx.set_clock("2026-03-01T11:30:00.000Z")
    data = validate_success(api.mark_no_show(appt["id"], GATE), 200)
    assert data["status"] == "NO_SHOW"
    assert data["no_show_count"] == 1


# --------------------------------------------------------------------------- #
# Buffered slot clash — resource_temporal_overlap
# --------------------------------------------------------------------------- #
def test_gate_slot_buffered_adjacency_conflicts(api):
    """PRD §3.4: "Two appointments for the same `container_id` clash when their
    slots, each extended by thirty minutes on its trailing edge, intersect ...
    Unlike berths, adjacency here **does** clash, because the trailing buffer makes
    back-to-back slots collide." A clash is rejected with `ERR_GATE_SLOT_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/gate_slot_buffered_overlap_adjacency_conflicts
    """
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    fx.book_appointment(
        container["id"], window_start="2026-03-01T10:00:00.000Z", window_end="2026-03-01T11:00:00.000Z"
    )
    # Second slot starts exactly at the first's window_end (adjacent) -> conflicts.
    resp = api.create_gate_appointment(
        {
            "container_id": container["id"],
            "truck_plate": "TRK-171",
            "window_start": "2026-03-01T11:00:00.000Z",
            "window_end": "2026-03-01T12:00:00.000Z",
        },
        GATE,
    )
    validate_error(resp, ApiErrorId.ERR_GATE_SLOT_CONFLICT.value)


def test_gate_slot_beyond_buffer_accepted(api):
    """PRD §3.4: "consecutive slots must leave a turnaround buffer of thirty minutes
    between them. Two appointments for the same `container_id` clash when their
    slots, each extended by thirty minutes on its trailing edge, intersect".

    Design: Difficulty/resource_temporal_overlap/gate_slot_buffered_overlap_adjacency_conflicts
    """
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    fx.book_appointment(
        container["id"], window_start="2026-03-01T10:00:00.000Z", window_end="2026-03-01T11:00:00.000Z"
    )
    # Second slot starts 31 minutes after the first ends -> clears the 30-min buffer.
    data = validate_success(
        api.create_gate_appointment(
            {
                "container_id": container["id"],
                "truck_plate": "TRK-172",
                "window_start": "2026-03-01T11:31:00.000Z",
                "window_end": "2026-03-01T12:31:00.000Z",
            },
            GATE,
        ),
        201,
    )
    assert data["status"] == "BOOKED"


# --------------------------------------------------------------------------- #
# Check-in / no-show window guards
# --------------------------------------------------------------------------- #
def test_check_in_before_window_start_outside_window(api):
    """PRD §3.4: "the current clock instant must fall within the half-open slot — at
    or after `window_start` and strictly before `window_end`. A check-in attempted
    outside that interval is rejected with `ERR_OUTSIDE_WINDOW`."

    Design: Corner/state_machines/checkin_outside_window_returns_outside_window
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    appt = fx.book_appointment(
        container["id"], window_start="2026-03-01T10:00:00.000Z", window_end="2026-03-01T11:00:00.000Z"
    )
    # clock is still 2026-02-01, well before window_start
    resp = api.check_in_gate_appointment(appt["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW.value)


def test_no_show_before_window_end_outside_window(api):
    """PRD §3.4: "This requires that the slot has fully elapsed — the current clock
    instant must be at or after `window_end` — otherwise the attempt is rejected
    with `ERR_OUTSIDE_WINDOW`."

    Design: Corner/state_machines/no_show_before_window_end_returns_outside_window
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    appt = fx.book_appointment(
        container["id"], window_start="2026-03-01T10:00:00.000Z", window_end="2026-03-01T11:00:00.000Z"
    )
    fx.set_clock("2026-03-01T10:30:00.000Z")  # inside the slot, before window_end
    resp = api.mark_no_show(appt["id"], GATE)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW.value)


def test_reschedule_blocked_after_no_show_cap(api):
    """PRD §3.4: "Rescheduling is capped: an appointment whose `no_show_count`
    exceeds three may not be rescheduled, so a fourth no-show is barred from
    rescheduling, and an over-cap attempt is rejected with `ERR_NO_SHOW_CAP`."

    Design: Corner/state_machines/reschedule_blocked_after_no_show_cap
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=365)
    appt = fx.book_appointment(
        container["id"], window_start="2026-03-01T10:00:00.000Z", window_end="2026-03-01T11:00:00.000Z"
    )
    # Cycle no-show/reschedule until no_show_count reaches 4, ending in NO_SHOW.
    slots = [
        ("2026-03-01T11:30:00.000Z", "2026-03-02T10:00:00.000Z", "2026-03-02T11:00:00.000Z"),
        ("2026-03-02T11:30:00.000Z", "2026-03-03T10:00:00.000Z", "2026-03-03T11:00:00.000Z"),
        ("2026-03-03T11:30:00.000Z", "2026-03-04T10:00:00.000Z", "2026-03-04T11:00:00.000Z"),
    ]
    for elapsed_clock, next_start, next_end in slots:
        fx.set_clock(elapsed_clock)
        fx.get_success_data(api.mark_no_show(appt["id"], GATE))
        fx.get_success_data(
            api.reschedule_gate_appointment(
                appt["id"], {"window_start": next_start, "window_end": next_end}, GATE
            )
        )
    # Fourth no-show (no_show_count -> 4), then attempt reschedule (over cap).
    fx.set_clock("2026-03-04T11:30:00.000Z")
    fx.get_success_data(api.mark_no_show(appt["id"], GATE))
    resp = api.reschedule_gate_appointment(
        appt["id"],
        {"window_start": "2026-03-05T10:00:00.000Z", "window_end": "2026-03-05T11:00:00.000Z"},
        GATE,
    )
    validate_error(resp, ApiErrorId.ERR_NO_SHOW_CAP.value)
    after = validate_success(api.get_gate_appointment(appt["id"], GATE), 200)
    assert after["no_show_count"] == 4


# --------------------------------------------------------------------------- #
# Cancel + listing
# --------------------------------------------------------------------------- #
def test_gate_appointment_cancel_from_booked(api):
    """PRD §3.4: "A booked appointment may also be **cancelled** to the terminal
    `CANCELLED` state (the appointment must be `BOOKED`, otherwise
    `ERR_INVALID_STATE`), which increments `version`."

    Design: Corner/endpoints/gate_appointment_cancel_from_booked
    """
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    appt = fx.book_appointment(container["id"])
    data = validate_success(api.cancel_gate_appointment(appt["id"], GATE), 200)
    assert data["status"] == "CANCELLED"


def test_list_gate_appointments_filtered_by_container(api):
    """PRD §4: "GET /gate-appointments | List gate appointments, optionally filtered
    by container".
    PRD §3.4: "A `GateOperator` **books a gate appointment** against a specific
    container by naming the `container_id` to be collected".

    Design: Corner/endpoints/list_gate_appointments_filtered_by_container
    """
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    fx.book_appointment(container["id"])
    data, _meta = validate_paginated(
        api.list_gate_appointments(GATE, params={"container_id": container["id"]})
    )
    assert len(data) == 1
    assert data[0]["container_id"] == container["id"]
