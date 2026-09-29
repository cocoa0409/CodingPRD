"""The two interval arithmetics that guard scarce inspection capacity.

An inspector's calendar is exclusive over half-open intervals, so a slot that
starts exactly where the previous one ends is bookable. A station's bays are
counted over closed intervals, so the same touching slot consumes a bay and is
turned away when the station has only one.
"""

from datetime import datetime

from test_helpers import (
    api_client,
    make_state_title_clerk_headers,
    read_application,
    read_inspector,
    read_station,
    schedule_inspection_payload,
    setup_docs_accepted_application,
    setup_program_actors,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import commission_inspector, schedule_inspection

SLOT_0900 = "2026-08-10T09:00:00Z"
SLOT_1000 = "2026-08-10T10:00:00Z"
SLOT_1100 = "2026-08-10T11:00:00Z"
SLOT_1200 = "2026-08-10T12:00:00Z"
SLOT_1300 = "2026-08-10T13:00:00Z"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of the same moment compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _schedule(
    application_id: str,
    inspector_id: str,
    station_id: str,
    expected_application_version: int,
    scheduled_start_at: str,
    scheduled_end_at: str,
):
    """Raw scheduling call, so both the refusal and the booking can be inspected."""
    return api_client.schedule_inspection(
        application_id,
        schedule_inspection_payload(
            inspector_id,
            station_id,
            expected_application_version,
            scheduled_start_at,
            scheduled_end_at,
        ),
        make_state_title_clerk_headers(),
    )


def _two_accepted_applications(bay_count: int) -> tuple:
    """Two trailer applications of one rebuilder, both accepted and ready to schedule.

    The station's `bay_count` is supplied by the caller so that whichever capacity
    rule is not under test can never be the binding constraint.
    """
    actors = setup_program_actors(station_overrides={"bay_count": bay_count})
    env_a = setup_docs_accepted_application(body_class="TRAILER", actors=actors)
    env_b = setup_docs_accepted_application(body_class="TRAILER", actors=actors)
    return actors, env_a, env_b


# ===========================================================================
# the inspector's half-open calendar
# ===========================================================================
def test_inspector_calendar_rejects_the_overlap_but_admits_the_touching_slot():
    """A booking that runs into an existing attempt is refused; one that starts at its end is not.

    PRD: "Because the intervals are half-open, exactly touching endpoints do not collide: an existing attempt whose widened end equals the requested `scheduled_start_at` is not a conflict."

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_interval_rejects_overlap_but_admits_touching_slot
    """
    actors, env_a, env_b = _two_accepted_applications(bay_count=3)
    first = schedule_inspection(
        env_a["application_id"],
        actors["inspector_id"],
        actors["station_id"],
        env_a["app_version"],
        SLOT_0900,
        SLOT_1100,
    )
    assert _instant(first["effective_end_at"]) == _instant(SLOT_1100), (
        "a collision-damaged trailer earns no flood buffer, so effective_end_at must equal "
        f"{SLOT_1100}, got {first['effective_end_at']}"
    )

    validate_error(
        _schedule(
            env_b["application_id"],
            actors["inspector_id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1000,
            SLOT_1200,
        ),
        "ERR_INSPECTOR_INTERVAL_CONFLICT",
    )

    second = validate_success(
        _schedule(
            env_b["application_id"],
            actors["inspector_id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1100,
            SLOT_1300,
        ),
        expected_status=201,
    )
    assert second["status"] == "SCHEDULED", (
        f"expected status SCHEDULED, got {second['status']} for the touching slot"
    )
    assert _instant(second["scheduled_start_at"]) == _instant(first["effective_end_at"]), (
        f"expected the touching slot to start at {first['effective_end_at']}, "
        f"got {second['scheduled_start_at']}"
    )


def test_touching_bookings_leave_the_inspector_holding_two_attempts():
    """Both the original and the touching attempt sit on the inspector's calendar.

    PRD: "An inspector's `scheduled_inspection_count` is the number of that inspector's attempts whose status is `SCHEDULED` or `IN_PROGRESS`, and starts at 0."

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_interval_rejects_overlap_but_admits_touching_slot
    """
    actors, env_a, env_b = _two_accepted_applications(bay_count=3)
    schedule_inspection(
        env_a["application_id"],
        actors["inspector_id"],
        actors["station_id"],
        env_a["app_version"],
        SLOT_0900,
        SLOT_1100,
    )
    validate_success(
        _schedule(
            env_b["application_id"],
            actors["inspector_id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1100,
            SLOT_1300,
        ),
        expected_status=201,
    )

    inspector = read_inspector(actors["inspector_id"])
    assert inspector["scheduled_inspection_count"] == 2, (
        f"expected scheduled_inspection_count 2, got {inspector['scheduled_inspection_count']} "
        "after two touching bookings"
    )

    attempts, meta = validate_paginated(
        api_client.list_inspections(
            make_state_title_clerk_headers(), params={"inspector_id": actors["inspector_id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected total_count 2 attempts for the inspector, got {meta['total_count']}"
    )
    assert [attempt["status"] for attempt in attempts] == ["SCHEDULED", "SCHEDULED"], (
        f"expected both attempts SCHEDULED, got {[a['status'] for a in attempts]}"
    )


def test_rejected_overlap_books_nothing_on_the_inspector_calendar():
    """The refused overlapping booking leaves the calendar and the application untouched.

    PRD: "Any true intersection is refused with `ERR_INSPECTOR_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_interval_rejects_overlap_but_admits_touching_slot
    """
    actors, env_a, env_b = _two_accepted_applications(bay_count=3)
    schedule_inspection(
        env_a["application_id"],
        actors["inspector_id"],
        actors["station_id"],
        env_a["app_version"],
        SLOT_0900,
        SLOT_1100,
    )

    validate_error(
        _schedule(
            env_b["application_id"],
            actors["inspector_id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1000,
            SLOT_1200,
        ),
        "ERR_INSPECTOR_INTERVAL_CONFLICT",
    )

    inspector = read_inspector(actors["inspector_id"])
    assert inspector["scheduled_inspection_count"] == 1, (
        f"expected scheduled_inspection_count 1, got {inspector['scheduled_inspection_count']} "
        "after the refused overlap"
    )
    attempts, meta = validate_paginated(
        api_client.list_inspections(
            make_state_title_clerk_headers(), params={"application_id": env_b["application_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected total_count 0 attempts on the second application, got {meta['total_count']}"
    )
    assert attempts == [], f"expected no attempt rows, got {len(attempts)}"

    application = read_application(env_b["application_id"])
    assert application["status"] == "DOCS_ACCEPTED", (
        f"expected status DOCS_ACCEPTED, got {application['status']} after the refused overlap"
    )
    assert application["version"] == env_b["app_version"], (
        f"expected version {env_b['app_version']} to stand, got {application['version']} "
        "after the refused overlap"
    )

# ===========================================================================
# the station's closed-interval bay count
# ===========================================================================
def test_single_bay_station_rejects_the_touching_slot_but_admits_a_clear_one():
    """A touching slot consumes the last bay of a one-bay station and is turned away.

    PRD: "The station capacity rule instead counts, and it uses closed intervals with the raw `scheduled_end_at` rather than the widened end: the program counts the station's attempts whose `status` is `SCHEDULED` or `IN_PROGRESS` and whose closed interval from `scheduled_start_at` through `scheduled_end_at` intersects the requested closed interval — and here touching endpoints *do* count as intersecting — and that count must be strictly less than the station's `bay_count`."

    Design: Difficulty/resource_temporal_overlap/station_closed_interval_capacity_rejects_touching_slot_on_last_bay
    """
    actors, env_a, env_b = _two_accepted_applications(bay_count=1)
    second_inspector = commission_inspector()
    schedule_inspection(
        env_a["application_id"],
        actors["inspector_id"],
        actors["station_id"],
        env_a["app_version"],
        SLOT_0900,
        SLOT_1100,
    )

    # A different inspector, so the calendar rule cannot be the one that speaks:
    # 11:00 only clashes under the station's closed-interval arithmetic.
    validate_error(
        _schedule(
            env_b["application_id"],
            second_inspector["id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1100,
            SLOT_1300,
        ),
        "ERR_STATION_CAPACITY_EXCEEDED",
    )

    clear = validate_success(
        _schedule(
            env_b["application_id"],
            second_inspector["id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1200,
            SLOT_1300,
        ),
        expected_status=201,
    )
    assert clear["status"] == "SCHEDULED", (
        f"expected status SCHEDULED, got {clear['status']} for the non-touching slot"
    )
    assert clear["station_id"] == actors["station_id"], (
        f"expected station_id {actors['station_id']}, got {clear['station_id']}"
    )


def test_two_disjoint_slots_both_hold_the_one_bay_in_turn():
    """The station carries both bookings once their closed intervals no longer meet.

    PRD: "A successful scheduling creates an attempt in `SCHEDULED`, computes its `effective_end_at`, assigns its `attempt_no`, moves the application's `status` to `SCHEDULED`, increments the application's `version` by 1, and increments both the inspector's `scheduled_inspection_count` and the station's `scheduled_occupancy_count`."

    Design: Difficulty/resource_temporal_overlap/station_closed_interval_capacity_rejects_touching_slot_on_last_bay
    """
    actors, env_a, env_b = _two_accepted_applications(bay_count=1)
    second_inspector = commission_inspector()
    schedule_inspection(
        env_a["application_id"],
        actors["inspector_id"],
        actors["station_id"],
        env_a["app_version"],
        SLOT_0900,
        SLOT_1100,
    )
    validate_success(
        _schedule(
            env_b["application_id"],
            second_inspector["id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1200,
            SLOT_1300,
        ),
        expected_status=201,
    )

    station = read_station(actors["station_id"])
    assert station["scheduled_occupancy_count"] == 2, (
        f"expected scheduled_occupancy_count 2, got {station['scheduled_occupancy_count']} "
        "after two disjoint bookings"
    )
    attempts, meta = validate_paginated(
        api_client.list_inspections(
            make_state_title_clerk_headers(), params={"station_id": actors["station_id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected total_count 2 attempts at the station, got {meta['total_count']}"
    )
    assert {attempt["inspector_id"] for attempt in attempts} == {
        actors["inspector_id"],
        second_inspector["id"],
    }, (
        "expected one attempt per inspector, got "
        f"{[a['inspector_id'] for a in attempts]}"
    )

    first_application = read_application(env_a["application_id"])
    assert first_application["status"] == "SCHEDULED", (
        f"expected the earlier application to stay SCHEDULED, got {first_application['status']}"
    )


def test_rejected_touching_slot_claims_no_bay_and_no_calendar():
    """The refused booking leaves the single bay held by one attempt only.

    PRD: "A count that has already reached `bay_count` is refused with `ERR_STATION_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/station_closed_interval_capacity_rejects_touching_slot_on_last_bay
    """
    actors, env_a, env_b = _two_accepted_applications(bay_count=1)
    second_inspector = commission_inspector()
    schedule_inspection(
        env_a["application_id"],
        actors["inspector_id"],
        actors["station_id"],
        env_a["app_version"],
        SLOT_0900,
        SLOT_1100,
    )

    validate_error(
        _schedule(
            env_b["application_id"],
            second_inspector["id"],
            actors["station_id"],
            env_b["app_version"],
            SLOT_1100,
            SLOT_1300,
        ),
        "ERR_STATION_CAPACITY_EXCEEDED",
    )

    station = read_station(actors["station_id"])
    assert station["scheduled_occupancy_count"] == 1, (
        f"expected scheduled_occupancy_count 1, got {station['scheduled_occupancy_count']} "
        "after the refused touching slot"
    )
    assert read_inspector(second_inspector["id"])["scheduled_inspection_count"] == 0, (
        "expected the refused inspector to hold no attempt, got "
        f"{read_inspector(second_inspector['id'])['scheduled_inspection_count']}"
    )

    application = read_application(env_b["application_id"])
    assert application["status"] == "DOCS_ACCEPTED", (
        f"expected status DOCS_ACCEPTED, got {application['status']} after the refused booking"
    )
    assert application["version"] == env_b["app_version"], (
        f"expected version {env_b['app_version']} to stand, got {application['version']} "
        "after the refused booking"
    )
