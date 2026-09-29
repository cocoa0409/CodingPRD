"""Two resources, two geometries: a buffered unit and an unbuffered worker."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_created_at_ascending
from test_helpers.factories import reservation_payload
from test_helpers.fixtures import assign, reserve
from test_helpers.test_users import STAFF_OPS_HEADERS, make_club_headers
from test_helpers.types import AssignmentRole


# ---------------------------------------------------------------------------
# 29 minutes clear of a HELD unit is a clash; 30 minutes clear is not
# ---------------------------------------------------------------------------
def test_reservation_twenty_nine_minutes_clear_of_the_unit_is_refused(
    api, equipment_buffer_setup
):
    """PRD §3.5: "The new hold clashes with an existing one when the new
    `window_start_utc` falls strictly before the existing `window_end_utc` plus 30
    minutes and the existing `window_start_utc` falls strictly before the new
    `window_end_utc` plus 30 minutes; a clash is refused with
    `ERR_EQUIPMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/equipment_buffer_rejects_29_minute_gap_and_admits_exactly_30
    """
    held = equipment_buffer_setup["held_reservation"]
    assert held["buffer_minutes"] == 30
    assert held["reservation_status"] == "HELD"

    club_headers = make_club_headers(equipment_buffer_setup["club"]["id"])
    validate_error(
        api.create_reservation(
            reservation_payload(
                equipment_buffer_setup["unit"]["id"],
                equipment_buffer_setup["afternoon_event_id"],
                "2026-09-14T13:59:00Z",
                "2026-09-14T19:30:00Z",
            ),
            club_headers,
        ),
        ApiErrorId.EQUIPMENT_WINDOW_CONFLICT,
        409,
    )

    rows, meta = validate_paginated(
        api.list_reservations(
            club_headers, {"equipment_unit_id": equipment_buffer_setup["unit"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == held["id"]


def test_reservation_exactly_thirty_minutes_clear_of_the_unit_is_accepted(
    api, equipment_buffer_setup
):
    """PRD §3.5: "Because both comparisons are strict, a reservation that begins
    exactly 30 minutes after another one ends is accepted, while one that begins
    29 minutes after is refused. That is the crux of the disagreement between the
    two resource types: an equivalent 30-minute separation is fine for a unit and
    fatal for a worker."

    Design: Difficulty/resource_temporal_overlap/equipment_buffer_rejects_29_minute_gap_and_admits_exactly_30
    """
    club_id = equipment_buffer_setup["club"]["id"]
    club_headers = make_club_headers(club_id)
    unit_id = equipment_buffer_setup["unit"]["id"]

    validate_error(
        api.create_reservation(
            reservation_payload(
                unit_id,
                equipment_buffer_setup["afternoon_event_id"],
                "2026-09-14T13:59:00Z",
                "2026-09-14T19:30:00Z",
            ),
            club_headers,
        ),
        ApiErrorId.EQUIPMENT_WINDOW_CONFLICT,
        409,
    )
    accepted = reserve(
        api,
        club_id,
        unit_id,
        equipment_buffer_setup["afternoon_event_id"],
        "2026-09-14T14:00:00Z",
        "2026-09-14T19:30:00Z",
    )

    assert accepted["reservation_status"] == "HELD"
    assert accepted["window_start_utc"].startswith("2026-09-14T14:00:00")
    assert accepted["buffer_minutes"] == 30

    rows, meta = validate_paginated(
        api.list_reservations(club_headers, {"equipment_unit_id": unit_id})
    )
    assert meta["total_count"] == 2
    assert_created_at_ascending(rows)
    assert rows[1]["window_start_utc"].startswith("2026-09-14T14:00:00")

    unit = validate_success(api.get_equipment_unit(unit_id, club_headers))
    still_held = validate_success(
        api.get_reservation(
            equipment_buffer_setup["held_reservation"]["id"], club_headers
        )
    )
    assert unit["sanitation_status"] == "SANITIZED"
    assert still_held["reservation_status"] == "HELD"


# ---------------------------------------------------------------------------
# Shifts that meet at a single instant still clash for a worker
# ---------------------------------------------------------------------------
def test_shifts_meeting_at_one_instant_double_book_the_same_worker(
    api, touching_shift_setup
):
    """PRD §3.4: "Because both comparisons are inclusive, two shifts that merely
    touch at a single instant still clash, and the refusal is
    `ERR_DEMONSTRATOR_DOUBLE_BOOKED`." The consequence is concrete and matters: a
    `MORNING` shift and an `AFTERNOON` shift on the same date merely meet at
    14:15Z, where one shift's `scheduled_end_utc` equals the other's
    `scheduled_start_utc`, and under this closed geometry that still counts as a
    clash.

    Design: Difficulty/resource_temporal_overlap/demonstrator_closed_geometry_rejects_touching_shift_endpoints
    """
    morning_assignment = touching_shift_setup["morning_assignment"]
    assert morning_assignment["scheduled_start_utc"].startswith("2026-09-14T08:15:00")
    assert morning_assignment["scheduled_end_utc"].startswith("2026-09-14T14:15:00")

    error = validate_error(
        api.create_assignment(
            touching_shift_setup["afternoon_event_id"],
            {
                "demonstrator_id": touching_shift_setup["first_demonstrator"]["id"],
                "role": AssignmentRole.LEAD,
            },
            STAFF_OPS_HEADERS,
        ),
        ApiErrorId.DEMONSTRATOR_DOUBLE_BOOKED,
        409,
    )
    assert error["error_id"] != ApiErrorId.DEMONSTRATOR_DAILY_CAP_EXCEEDED.value


def test_a_second_worker_takes_the_touching_afternoon_shift(api, touching_shift_setup):
    """PRD §3.4: "The shift the assignment occupies is derived, not supplied:
    `scheduled_start_utc` is the event's `event_window_start_utc` less 45 minutes
    of setup lead, and `scheduled_end_utc` is the event's `event_window_end_utc`
    plus 75 minutes of teardown." Those asymmetric pads are what make the
    afternoon shift begin at the very instant the morning shift ends.

    Design: Difficulty/resource_temporal_overlap/demonstrator_closed_geometry_rejects_touching_shift_endpoints
    """
    afternoon_event_id = touching_shift_setup["afternoon_event_id"]
    first_id = touching_shift_setup["first_demonstrator"]["id"]

    validate_error(
        api.create_assignment(
            afternoon_event_id,
            {"demonstrator_id": first_id, "role": AssignmentRole.LEAD},
            STAFF_OPS_HEADERS,
        ),
        ApiErrorId.DEMONSTRATOR_DOUBLE_BOOKED,
        409,
    )
    second = assign(
        api,
        afternoon_event_id,
        touching_shift_setup["second_demonstrator"]["id"],
        AssignmentRole.LEAD,
    )

    assert second["scheduled_start_utc"].startswith("2026-09-14T14:15:00")
    assert second["scheduled_end_utc"].startswith("2026-09-14T20:15:00")
    assert (
        second["scheduled_start_utc"][:19]
        == touching_shift_setup["morning_assignment"]["scheduled_end_utc"][:19]
    )

    morning = validate_success(
        api.get_assignment(
            touching_shift_setup["morning_assignment"]["id"], STAFF_OPS_HEADERS
        )
    )
    afternoon_event = validate_success(
        api.get_demo_event(afternoon_event_id, STAFF_OPS_HEADERS)
    )
    assert morning["assignment_status"] == "ASSIGNED"
    assert afternoon_event["staffing_status"] == "FULLY_STAFFED"

    rows, meta = validate_paginated(
        api.list_assignments(STAFF_OPS_HEADERS, {"demonstrator_id": first_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == touching_shift_setup["morning_assignment"]["id"]
