"""Optimistic concurrency on parent versions, all-or-nothing cascades and rate thresholds.

Every test drives real HTTP against a live server whose database is empty and whose
logical clock reads 2026-08-01T00:00:00Z; the clock only ever moves forward.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId


def test_occ_stale_resident_version_on_plan_create_returns_4xx(api, director, therapist):
    """A plan draft that echoes a superseded resident version is rejected with 412.

    The therapist reads the resident at version 2, the director then renumbers the room
    and takes the resident to version 3, and the draft that echoes 2 is refused; the
    refusal writes no plan and advances no version. Re-reading the resident and echoing
    the fresh version makes the identical body succeed, and that success advances the
    resident's own version in turn.

    PRD: "If it does not match the resident's current `version` at the moment the create
    is processed, the request is rejected with `ERR_STALE_RESIDENT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_resident_version_on_plan_create_returns_4XX
    """
    resident = fx.create_resident(api, full_name="Stale View Stan", room_number="712A")
    assert resident["version"] == 1
    assessment = fx.file_assessment(api, resident["id"], effective_date="2026-07-31")

    stale_version = fx.resident_version(api, resident["id"])
    assert stale_version == 2, (
        f"The assessment mirror write is a version bump, saw version {stale_version}"
    )
    bumped = validate_success(
        api.update_resident(resident["id"], {"room_number": "712B"}, director), 200
    )
    assert bumped["version"] == 3

    targets = f.domain_targets(social=2)
    refused = api.create_activity_plan(
        f.plan_payload(resident["id"], assessment["id"], stale_version, targets=targets),
        therapist,
    )
    validate_error(refused, ApiErrorId.STALE_RESIDENT_VERSION.value, 412)

    _rows, meta = validate_paginated(
        api.list_activity_plans(therapist, {"resident_id": resident["id"]})
    )
    assert meta["total_count"] == 0, (
        f"The refused draft must have written no plan, saw {meta['total_count']}"
    )
    assert fx.resident_version(api, resident["id"]) == 3, (
        "The refused draft must not advance the resident's version"
    )

    fresh_version = fx.resident_version(api, resident["id"])
    created = validate_success(
        api.create_activity_plan(
            f.plan_payload(resident["id"], assessment["id"], fresh_version, targets=targets),
            therapist,
        ),
        201,
    )
    assert created["status"] == "DRAFT"
    assert fx.resident_version(api, resident["id"]) == fresh_version + 1, (
        "PRD §3.2: creating the plan also advances the resident's version"
    )


def test_occ_stale_vehicle_version_on_transport_booking_returns_4xx(api, director):
    """A second booking that echoes the pre-booking vehicle version is rejected with 412.

    Two disjoint outings share one vehicle whose turnaround is 30 minutes, so the fleet
    interval of the 09:00-11:00 trip closes at 11:30 and the 13:00 departure is not a
    time conflict; only the seat-pool version tells the caller that the free pool they
    sized their manifest against has already been consumed.

    PRD: "A mismatch with the vehicle's current `version` is rejected with
    `ERR_STALE_VEHICLE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_vehicle_version_on_transport_booking_returns_4XX
    """
    program = fx.create_program(api, name="Stale Fleet Program", domain="SOCIAL")
    vehicle = fx.create_vehicle(
        api, label="Van 23", ambulatory_seats=8, wheelchair_stations=2, turnaround_minutes=30
    )
    outing_one = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Morning Market",
        departure_at="2026-09-28T09:00:00Z",
        return_at="2026-09-28T11:00:00Z",
        escort_count=1,
    )
    outing_two = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Afternoon Museum",
        departure_at="2026-09-28T13:00:00Z",
        return_at="2026-09-28T15:00:00Z",
        escort_count=1,
    )

    stale_version = fx.vehicle_version(api, vehicle["id"])
    assert stale_version == 1
    first = validate_success(
        api.book_transport(
            outing_one["id"], {"expected_vehicle_version": stale_version}, director
        ),
        200,
    )
    assert first["logistics_status"] == "TRANSPORT_BOOKED"

    refused = api.book_transport(
        outing_two["id"], {"expected_vehicle_version": stale_version}, director
    )
    validate_error(refused, ApiErrorId.STALE_VEHICLE_VERSION.value, 412)

    assert fx.read_outing(api, outing_two["id"], director)["logistics_status"] == "PLANNING"
    after_refusal = fx.read_vehicle(api, vehicle["id"], director)
    assert after_refusal["reserved_ambulatory_seats"] == 1, (
        "Only the first trip's escort seat may be reserved after the refusal"
    )
    assert after_refusal["version"] == 2, "The refused booking must advance nothing"

    fresh_version = fx.vehicle_version(api, vehicle["id"])
    assert fresh_version == 2
    retried = validate_success(
        api.book_transport(
            outing_two["id"], {"expected_vehicle_version": fresh_version}, director
        ),
        200,
    )
    assert retried["logistics_status"] == "TRANSPORT_BOOKED"
    final_vehicle = fx.read_vehicle(api, vehicle["id"], director)
    assert final_vehicle["version"] == 3
    assert final_vehicle["reserved_ambulatory_seats"] == 2


def test_version_increments_on_every_write_including_side_effect_writes(api, director):
    """The vehicle's version counter advances on side-effect writes as well as direct edits.

    Two fleet-metadata edits take the vehicle from version 1 to 3, and the booking that
    echoes version 3 advances it again to 4 through its seat recompute, so a client that
    only re-reads after its own direct edits is already holding a stale token.

    PRD: "any fleet-metadata edit advances the vehicle's `version` and therefore
    invalidates whatever `expected_vehicle_version` a client is still holding"

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_including_side_effect_writes
    """
    program = fx.create_program(api, name="Version Walk Program", domain="PHYSICAL")
    vehicle = fx.create_vehicle(
        api, label="Van 24", ambulatory_seats=8, wheelchair_stations=2, turnaround_minutes=15
    )
    assert vehicle["version"] == 1
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Version Walk Park",
        departure_at="2026-09-29T09:00:00Z",
        return_at="2026-09-29T11:00:00Z",
        escort_count=2,
    )

    after_label = validate_success(
        api.update_vehicle(vehicle["id"], {"label": "Van 24 (relabelled)"}, director), 200
    )
    assert after_label["version"] == 2
    after_turnaround = validate_success(
        api.update_vehicle(vehicle["id"], {"turnaround_minutes": 20}, director), 200
    )
    assert after_turnaround["version"] == 3

    booked = validate_success(
        api.book_transport(
            outing["id"], {"expected_vehicle_version": after_turnaround["version"]}, director
        ),
        200,
    )
    assert booked["logistics_status"] == "TRANSPORT_BOOKED"

    after_booking = fx.read_vehicle(api, vehicle["id"], director)
    assert after_booking["version"] == 4, (
        "The booking's seat recompute is a versioned write of its own, "
        f"saw version {after_booking['version']}"
    )
    assert after_booking["turnaround_minutes"] == 20
    assert after_booking["reserved_ambulatory_seats"] == 2


def test_cascade_partial_failure_leaves_no_drift(api, director, aide, coordinator):
    """A refused documentation close applies none of its fan-out.

    One session carries two enrolled residents and one confirmed volunteer assignment;
    only the first resident is documented, so the close is refused. The session stays
    IN_PROGRESS with no documentation stamp, the assignment never reaches COMPLETED, the
    volunteer's lifetime credited hours stay at zero and their forward commitment still
    holds the two hours.

    PRD: "every enrolled resident must carry a documented outcome first, and any straggler
    reports `ERR_DOCUMENTATION_INCOMPLETE`"

    Design: Corner/cross_cutting_complexity_layers/cascade_partial_failure_leaves_no_drift
    """
    fx.advance_clock(api, "2026-08-03T00:00:00Z")
    resident_a, _asmt_a = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "No Drift Nora", "room_number": "713A"},
        interest_domains=["CREATIVE"],
        effective_date="2026-08-01",
    )
    resident_b, _asmt_b = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "No Drift Ned", "room_number": "713B"},
        interest_domains=["CREATIVE"],
        effective_date="2026-08-01",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "No Drift Program",
            "domain": "CREATIVE",
            "max_supervision_tier": "TIER_3",
            "volunteer_eligible": True,
        },
        room_kwargs={"name": "No Drift Room", "capacity": 10},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T11:00:00Z",
        assigned_staff_count=4,
    )
    record_a = fx.enroll(api, session["id"], resident_a["id"])
    record_b = fx.enroll(api, session["id"], resident_b["id"])
    volunteer = fx.cleared_volunteer(api, full_name="No Drift Val")
    assignment = fx.assign_volunteer(
        api, volunteer["id"], session["id"], role_type="GROUP_ASSISTANT"
    )
    fx.confirm_assignment(api, assignment["id"])

    fx.advance_clock(api, "2026-08-05T09:00:00Z")
    fx.start_session(api, session["id"])
    fx.document_attendance(api, record_a["id"], engagement_level="ACTIVE")

    refused = api.session_status(session["id"], {"action": "CLOSE_DOCUMENTATION"}, aide)
    validate_error(refused, ApiErrorId.DOCUMENTATION_INCOMPLETE.value, 409)

    after = fx.read_session(api, session["id"], director)
    assert after["status"] == "IN_PROGRESS"
    assert after["documented_at"] is None
    assert fx.read_assignment(api, assignment["id"], coordinator)["status"] == "CONFIRMED", (
        "The CONFIRMED to COMPLETED hop must never have run"
    )
    volunteer_after = fx.read_volunteer(api, volunteer["id"], coordinator)
    assert volunteer_after["credited_service_hours"] == 0.0, (
        "An unclosed session credits no lifetime service hours"
    )
    assert volunteer_after["scheduled_hours_week"] == 2.0, (
        "The forward-looking commitment still holds the two-hour session"
    )
    assert fx.read_record(api, record_a["id"], aide)["status"] == "ATTENDED"
    assert fx.read_record(api, record_b["id"], aide)["status"] == "PLANNED"


def test_refusal_review_threshold_boundary_two_versus_three(api, therapist):
    """The refusal review threshold fires at exactly three consecutive refusals, not two.

    The same resident on the same active plan refuses three consecutive sessions. After
    the second refusal the streak reads 2, the plan is still ACTIVE and the resident is
    ungated; the third refusal takes the streak to 3 and is what pushes the plan into
    revision and gates the resident. Refusals score no engagement points and are not
    absences.

    PRD: "the moment the streak reaches three or more, the refusal cascade fires, so a
    streak of exactly three is enough"

    Design: Corner/cross_cutting_complexity_layers/refusal_review_threshold_boundary_two_versus_three
    """
    resident = fx.create_resident(api, full_name="Boundary Streak Bea", room_number="714A")
    assessment = fx.file_assessment(api, resident["id"], effective_date="2026-07-31")
    plan = fx.active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=3),
        cycle_start_at="2026-09-01T00:00:00Z",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Boundary Streak Program",
            "domain": "SOCIAL",
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Boundary Streak Room", "capacity": 10},
    )
    starts = ["2026-09-25T09:00:00Z", "2026-09-26T09:00:00Z", "2026-09-27T09:00:00Z"]
    sessions = [
        fx.create_session(
            api,
            program["id"],
            room["id"],
            starts_at=starts_at,
            ends_at=starts_at.replace("T09:", "T10:"),
            assigned_staff_count=4,
        )
        for starts_at in starts
    ]
    records = [fx.enroll(api, session["id"], resident["id"]) for session in sessions]

    for index in (0, 1):
        fx.advance_clock(api, starts[index])
        fx.start_session(api, sessions[index]["id"])
        fx.document_refusal(api, records[index]["id"], refusal_reason="FATIGUE")

    at_two = fx.read_resident(api, resident["id"], therapist)
    assert at_two["refusal_streak"] == 2, (
        f"Two refusals are one short of the threshold, saw {at_two['refusal_streak']}"
    )
    assert at_two["enrollment_gate"] == "NONE"
    assert fx.read_plan(api, plan["id"], therapist)["status"] == "ACTIVE"

    fx.advance_clock(api, starts[2])
    fx.start_session(api, sessions[2]["id"])
    fx.document_refusal(api, records[2]["id"], refusal_reason="MOOD")

    at_three = fx.read_resident(api, resident["id"], therapist)
    assert at_three["refusal_streak"] == 3
    assert at_three["enrollment_gate"] == "THERAPIST_REVIEW"
    assert at_three["care_plan_review_due"] is True
    assert at_three["engagement_index"] == 0.0, (
        "A refusal enters the engagement window worth zero points"
    )
    assert at_three["absence_count"] == 0, "A refusal is not an absence"
    revised_plan = fx.read_plan(api, plan["id"], therapist)
    assert revised_plan["status"] == "UNDER_REVISION"
    assert revised_plan["review_reason"] == "REFUSAL_PATTERN"


def test_volunteer_weekly_cap_rearms_in_the_next_iso_week(api, coordinator):
    """The 8-hour volunteer cap is scoped to the ISO week holding the logical clock.

    A cleared volunteer is booked to a full 8.00 hours inside one ISO week, so a further
    one-hour booking in that same week is refused. Moving the clock into the following
    Monday-to-Monday window re-arms the allowance: the earlier commitment drops out of
    the forward-looking figure, four plus four hours are accepted, and only the ninth
    hour of the new week is refused. Nothing has been completed, so lifetime credited
    service is still zero.

    PRD: "so a volunteer may be scheduled to exactly 8.00 hours but not to 8.01, and an
    excess reports `ERR_VOLUNTEER_HOUR_CAP_EXCEEDED`" over the week "from Monday at
    `00:00:00Z` inclusive to the same instant seven days later, exclusive"

    Design: Corner/cross_cutting_complexity_layers/volunteer_weekly_cap_rearms_in_the_next_iso_week
    """
    fx.advance_clock(api, "2026-08-03T00:00:00Z")
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Weekly Cap Craft Circle",
            "domain": "CREATIVE",
            "volunteer_eligible": True,
        },
        room_kwargs={"name": "Weekly Cap Studio", "capacity": 12},
    )
    week_a_full = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T08:00:00Z",
        ends_at="2026-08-03T16:00:00Z",
    )
    week_a_extra = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-04T10:00:00Z",
        ends_at="2026-08-04T11:00:00Z",
    )
    week_b_first = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-10T09:00:00Z",
        ends_at="2026-08-10T13:00:00Z",
    )
    week_b_second = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-11T09:00:00Z",
        ends_at="2026-08-11T13:00:00Z",
    )
    week_b_overflow = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-12T09:00:00Z",
        ends_at="2026-08-12T10:00:00Z",
    )
    volunteer = fx.cleared_volunteer(
        api, full_name="Weekly Cap Wanda", volunteer_type="ADULT_COMMUNITY"
    )

    first = fx.assign_volunteer(api, volunteer["id"], week_a_full["id"])
    assert first["hours"] == 8.0, "An 08:00 to 16:00 slot is eight hours of commitment"
    assert fx.read_volunteer(api, volunteer["id"], coordinator)["scheduled_hours_week"] == 8.0

    refused_in_week_a = api.create_volunteer_assignment(
        f.assignment_payload(volunteer["id"], week_a_extra["id"]), coordinator
    )
    validate_error(
        refused_in_week_a, ApiErrorId.VOLUNTEER_HOUR_CAP_EXCEEDED.value, 409
    )
    assert fx.read_volunteer(api, volunteer["id"], coordinator)["scheduled_hours_week"] == 8.0

    fx.advance_clock(api, "2026-08-10T00:00:00Z")
    rearmed = fx.read_volunteer(api, volunteer["id"], coordinator)
    assert rearmed["scheduled_hours_week"] == 0.0, (
        "Last week's commitment is outside the new Monday-to-Monday window"
    )

    fx.assign_volunteer(api, volunteer["id"], week_b_first["id"])
    assert fx.read_volunteer(api, volunteer["id"], coordinator)["scheduled_hours_week"] == 4.0
    fx.assign_volunteer(api, volunteer["id"], week_b_second["id"])
    at_cap = fx.read_volunteer(api, volunteer["id"], coordinator)
    assert at_cap["scheduled_hours_week"] == 8.0, "Exactly 8.00 hours is still allowed"

    refused_in_week_b = api.create_volunteer_assignment(
        f.assignment_payload(volunteer["id"], week_b_overflow["id"]), coordinator
    )
    validate_error(
        refused_in_week_b, ApiErrorId.VOLUNTEER_HOUR_CAP_EXCEEDED.value, 409
    )
    final = fx.read_volunteer(api, volunteer["id"], coordinator)
    assert final["scheduled_hours_week"] == 8.0
    assert final["credited_service_hours"] == 0.0, (
        "Nothing has been documented, so no service has been earned"
    )
    rows, meta = validate_paginated(
        api.list_volunteer_assignments(coordinator, {"volunteer_id": volunteer["id"]})
    )
    assert meta["total_count"] == 3, (
        "Only the three accepted assignments exist; the refused ones wrote nothing"
    )
    assert all(row["status"] == "PROPOSED" for row in rows)
