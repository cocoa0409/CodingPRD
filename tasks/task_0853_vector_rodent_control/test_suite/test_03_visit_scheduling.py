"""Booking field visits: window shape, the parent's state, and the two calendars."""

from test_helpers import (
    ApiErrorId,
    assert_inspection,
    bootstrap_registry,
    file_complaint,
    make_supervisor_headers,
    schedule_visit,
    setup_triaged_complaint,
    TEST_USERS,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

CLERK = TEST_USERS["intake_clerk_headers"]


def test_visit_window_shorter_than_half_an_hour_is_rejected(api):
    """PRD §3.3: "The booked window must be structurally sound before anything
    else about it is considered: `scheduled_end` must be strictly after
    `scheduled_start`, and the duration between them must be at least 30 minutes
    and at most 240 minutes, both bounds inclusive."
    PRD §3.3: "A window that inverts, collapses to zero, runs shorter than half
    an hour or longer than four hours is rejected with `ERR_VALIDATION`."
    PRD §3.3: "Booking one moves the complaint `TRIAGED → INSPECTION_SCHEDULED`."

    Design: Corner/validations/corner_inspection_window_duration_out_of_range_rejected
    """
    env, complaint = setup_triaged_complaint(bootstrap_kwargs={"inspectors": 1})
    sup = make_supervisor_headers(env["sup_id"])

    too_short = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": complaint["id"],
            "officer_id": env["insp1_id"],
            "scheduled_start": "2026-05-05T09:00:00Z",
            "scheduled_end": "2026-05-05T09:20:00Z",
        },
        sup,
    )
    assert too_short.status_code == 400
    validate_error(too_short, ApiErrorId.ERR_VALIDATION.value)
    still_triaged = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert still_triaged["status"] == "TRIAGED"

    exactly_thirty = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": complaint["id"],
            "officer_id": env["insp1_id"],
            "scheduled_start": "2026-05-05T09:00:00Z",
            "scheduled_end": "2026-05-05T09:30:00Z",
        },
        sup,
    )
    visit = validate_success(exactly_thirty, 201)
    assert_inspection(visit)
    assert visit["status"] == "SCHEDULED"
    booked = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert booked["status"] == "INSPECTION_SCHEDULED"


def test_inspection_list_filters_by_officer_and_by_status(api):
    """PRD §3.3: "Inspections can be listed with optional filters on
    `complaint_id`, on `abatement_order_id`, on `property_id`, on `officer_id`,
    on `status` and on `kind`, or read one at a time."
    PRD §2.9: "An inspection whose `kind` is `INITIAL` responds to a complaint
    and carries `complaint_id` populated with `abatement_order_id` null; an
    inspection whose `kind` is `REINSPECTION` verifies an abatement order and
    carries `abatement_order_id` populated with `complaint_id` null."

    Design: Corner/endpoints/corner_inspection_filtered_list_by_officer_and_kind
    """
    env = bootstrap_registry(inspectors=2, parcels=2)
    first = file_complaint(env["prop1_id"], complaint_type="HARBORAGE",
                           reported_severity="HIGH")
    triage(first["id"], env["sup_id"], "HIGH")
    second = file_complaint(
        env["prop2_id"], complaint_type="RODENT_SIGHTING",
        reported_severity="ROUTINE", description="Sighting near the porch",
    )
    triage(second["id"], env["sup_id"], "ROUTINE")

    visit_one = schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=first["id"],
    )
    schedule_visit(
        env["sup_id"], "INITIAL", env["insp2_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=second["id"],
    )

    sup = make_supervisor_headers(env["sup_id"])
    rows, meta = validate_paginated(
        api.list_inspections(sup, params={"officer_id": env["insp1_id"]})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == visit_one["id"]
    assert rows[0]["kind"] == "INITIAL"
    assert rows[0]["property_id"] == env["prop1_id"]
    assert rows[0]["abatement_order_id"] is None

    in_progress, meta2 = validate_paginated(
        api.list_inspections(sup, params={"status": "IN_PROGRESS"})
    )
    assert meta2["total_count"] == 0
    assert in_progress == []


def test_initial_visit_against_an_untriaged_complaint_is_rejected(api):
    """PRD §3.3: "An `INITIAL` visit may only be booked against a complaint
    currently in `TRIAGED`; any other complaint status yields
    `ERR_COMPLAINT_NOT_TRIAGED`."
    PRD §3.2: "Every complaint is born in status `RECEIVED`."

    Design: Difficulty/cross_entity_state_dependency/initial_inspection_requires_triaged_complaint
    """
    env = bootstrap_registry(inspectors=1)
    complaint = file_complaint(
        env["prop_id"], complaint_type="DEAD_ANIMAL",
        reported_severity="ROUTINE", description="Dead rat in the courtyard",
    )

    resp = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": complaint["id"],
            "officer_id": env["insp1_id"],
            "scheduled_start": "2026-05-05T09:00:00Z",
            "scheduled_end": "2026-05-05T10:00:00Z",
        },
        make_supervisor_headers(env["sup_id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_TRIAGED.value)

    after = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert after["status"] == "RECEIVED"


def test_rejected_scheduling_leaves_no_inspection_row(api):
    """PRD §3.3: "An `INITIAL` visit may only be booked against a complaint
    currently in `TRIAGED`; any other complaint status yields
    `ERR_COMPLAINT_NOT_TRIAGED`."
    PRD §3.3: "Inspections can be listed with optional filters on
    `complaint_id`, on `abatement_order_id`, on `property_id`, on `officer_id`,
    on `status` and on `kind`, or read one at a time."

    Design: Difficulty/cross_entity_state_dependency/initial_inspection_requires_triaged_complaint
    """
    env = bootstrap_registry(inspectors=1)
    complaint = file_complaint(
        env["prop_id"], complaint_type="DEAD_ANIMAL",
        reported_severity="ROUTINE", description="Dead rat in the courtyard",
    )
    sup = make_supervisor_headers(env["sup_id"])

    resp = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": complaint["id"],
            "officer_id": env["insp1_id"],
            "scheduled_start": "2026-05-05T09:00:00Z",
            "scheduled_end": "2026-05-05T10:00:00Z",
        },
        sup,
    )
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_TRIAGED.value)

    rows, meta = validate_paginated(
        api.list_inspections(sup, params={"complaint_id": complaint["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def _officer_calendar_env():
    env = bootstrap_registry(inspectors=1, parcels=2)
    first = file_complaint(env["prop1_id"], complaint_type="HARBORAGE",
                           reported_severity="HIGH")
    triage(first["id"], env["sup_id"], "HIGH")
    schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=first["id"],
    )
    second = file_complaint(
        env["prop2_id"], complaint_type="GARBAGE_ACCUMULATION",
        reporter_type="AGENCY", reported_severity="ROUTINE",
        description="Overflowing bins in the side yard",
    )
    triage(second["id"], env["sup_id"], "ROUTINE")
    return env, second


def test_officer_window_inside_the_travel_buffer_collides(api):
    """PRD §3.3: "**Officer availability** is evaluated against every other
    inspection of the same officer that is currently `SCHEDULED` or
    `IN_PROGRESS`, using closed comparison on both ends plus a 30-minute travel
    buffer: the two bookings collide when the new visit's `scheduled_start` is at
    or before the other visit's `scheduled_end` extended by 30 minutes, *and* the
    other visit's `scheduled_start` is at or before the new visit's
    `scheduled_end` extended by 30 minutes."
    PRD §3.3: "Because the comparison is closed, two windows that are exactly
    back-to-back — and indeed two windows separated by exactly the travel buffer
    — do collide, and the booking is rejected with
    `ERR_OFFICER_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/officer_calendar_collides_inside_travel_buffer
    """
    env, second = _officer_calendar_env()
    resp = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": second["id"],
            "officer_id": env["insp1_id"],
            "scheduled_start": "2026-05-05T10:15:00Z",
            "scheduled_end": "2026-05-05T11:00:00Z",
        },
        make_supervisor_headers(env["sup_id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_OFFICER_SCHEDULE_CONFLICT.value)

    after = validate_success(api.get_complaint(second["id"], CLERK))
    assert after["status"] == "TRIAGED"


def test_officer_window_one_minute_past_the_buffer_is_accepted(api):
    """PRD §3.3: "**Officer availability** is evaluated against every other
    inspection of the same officer that is currently `SCHEDULED` or
    `IN_PROGRESS`, using closed comparison on both ends plus a 30-minute travel
    buffer: the two bookings collide when the new visit's `scheduled_start` is at
    or before the other visit's `scheduled_end` extended by 30 minutes, *and* the
    other visit's `scheduled_start` is at or before the new visit's
    `scheduled_end` extended by 30 minutes."
    PRD §3.3: "Booking one moves the complaint `TRIAGED → INSPECTION_SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/officer_calendar_collides_inside_travel_buffer
    """
    env, second = _officer_calendar_env()
    resp = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": second["id"],
            "officer_id": env["insp1_id"],
            "scheduled_start": "2026-05-05T10:31:00Z",
            "scheduled_end": "2026-05-05T11:16:00Z",
        },
        make_supervisor_headers(env["sup_id"]),
    )
    visit = validate_success(resp, 201)
    assert visit["status"] == "SCHEDULED"

    after = validate_success(api.get_complaint(second["id"], CLERK))
    assert after["status"] == "INSPECTION_SCHEDULED"

    rows, meta = validate_paginated(
        api.list_inspections(
            make_supervisor_headers(env["sup_id"]),
            params={"officer_id": env["insp1_id"]},
        )
    )
    assert meta["total_count"] == 2


def _parcel_calendar_env():
    env = bootstrap_registry(inspectors=3, parcels=1)
    first = file_complaint(env["prop_id"], complaint_type="HARBORAGE",
                           reported_severity="HIGH")
    triage(first["id"], env["sup_id"], "HIGH")
    second = file_complaint(
        env["prop_id"], complaint_type="GARBAGE_ACCUMULATION",
        reporter_type="AGENCY", reported_severity="ROUTINE",
        description="Refuse piled behind the building",
    )
    triage(second["id"], env["sup_id"], "ROUTINE")
    third = file_complaint(
        env["prop_id"], complaint_type="RODENT_SIGHTING",
        reported_severity="ROUTINE", description="Rats seen in the stairwell",
    )
    triage(third["id"], env["sup_id"], "ROUTINE")
    schedule_visit(
        env["sup_id"], "INITIAL", env["insp1_id"],
        "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z", complaint_id=first["id"],
    )
    return env, second, third


def test_parcel_windows_that_merely_touch_are_allowed(api):
    """PRD §3.3: "**Site availability** is evaluated against every other
    `SCHEDULED` or `IN_PROGRESS` inspection on the same parcel, with no buffer
    and half-open comparison: the two overlap when the new visit's
    `scheduled_start` is strictly before the other's `scheduled_end` *and* the
    other's `scheduled_start` is strictly before the new visit's
    `scheduled_end`."
    PRD §3.3: "Two windows that merely touch at an endpoint therefore do not
    overlap and are allowed; a genuine overlap yields
    `ERR_PROPERTY_INSPECTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/property_calendar_allows_touching_windows
    """
    env, second, _third = _parcel_calendar_env()
    resp = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": second["id"],
            "officer_id": env["insp2_id"],
            "scheduled_start": "2026-05-05T10:00:00Z",
            "scheduled_end": "2026-05-05T11:00:00Z",
        },
        make_supervisor_headers(env["sup_id"]),
    )
    visit = validate_success(resp, 201)
    assert visit["status"] == "SCHEDULED"
    assert visit["property_id"] == env["prop_id"]


def test_parcel_windows_that_genuinely_overlap_are_rejected(api):
    """PRD §3.3: "**Site availability** is evaluated against every other
    `SCHEDULED` or `IN_PROGRESS` inspection on the same parcel, with no buffer
    and half-open comparison: the two overlap when the new visit's
    `scheduled_start` is strictly before the other's `scheduled_end` *and* the
    other's `scheduled_start` is strictly before the new visit's
    `scheduled_end`."
    PRD §3.3: "Two windows that merely touch at an endpoint therefore do not
    overlap and are allowed; a genuine overlap yields
    `ERR_PROPERTY_INSPECTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/property_calendar_allows_touching_windows
    """
    env, second, third = _parcel_calendar_env()
    sup = make_supervisor_headers(env["sup_id"])
    schedule_visit(
        env["sup_id"], "INITIAL", env["insp2_id"],
        "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z", complaint_id=second["id"],
    )

    resp = api.create_inspection(
        {
            "kind": "INITIAL",
            "complaint_id": third["id"],
            "officer_id": env["insp3_id"],
            "scheduled_start": "2026-05-05T09:30:00Z",
            "scheduled_end": "2026-05-05T10:30:00Z",
        },
        sup,
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_PROPERTY_INSPECTION_OVERLAP.value)

    after = validate_success(api.get_complaint(third["id"], CLERK))
    assert after["status"] == "TRIAGED"

    rows, meta = validate_paginated(
        api.list_inspections(sup, params={"property_id": env["prop_id"]})
    )
    assert meta["total_count"] == 2
