"""Event creation: system-minted fields, request-shape and range validations,
OrgRequester scoping, pagination, and the response envelope."""

from test_helpers import (
    assert_same_instant,
    FACILITIES_MANAGER,
    NON_EXISTENT_UUID,
    SCHEDULER,
    ApiErrorId,
    assert_event,
    create_event,
    create_org,
    create_room,
    get_room,
    make_org_requester_headers,
    setup_org_room,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_event_create_mints_deadline_tier_and_bumps_room_version(api):
    """PRD §3.4: "sets `status` to `REQUESTED`, computes `decision_deadline` as 72
    hours after creation, derives `precedence_tier` from the organization's type,
    and increments the room's `version` by one."
    PRD §3.1: "It determines the `precedence_tier` stamped onto each event at
    creation — 200 for `INTERNAL_DEPARTMENT`, 100 for `STUDENT_GROUP`, and 50
    for `EXTERNAL`"
    PRD §2.4: "Before any adjustment, the server clock starts at exactly
    2026-08-01T00:00:00Z, and it must never fall back to wall-clock time."

    Design: Corner/entities/event_create_mints_system_fields_and_decision_deadline
    """
    scn = setup_org_room(room_overrides={"capacity": 10})
    room_before = scn.room
    event = create_event(
        scn.org,
        scn.room["id"],
        title="Sys",
        expected_attendance=5,
        start_at="2026-09-14T14:00:00Z",
        end_at="2026-09-14T15:00:00Z",
    )
    assert_event(event)
    assert event["status"] == "REQUESTED"
    # Created at the untouched logical clock 2026-08-01T00:00:00Z, +72h.
    assert_same_instant(event["decision_deadline"], "2026-08-04T00:00:00Z")
    assert event["precedence_tier"] == 200, "INTERNAL_DEPARTMENT requester"
    assert event["requester_org_id"] == scn.org["id"]

    room_after = get_room(scn.room["id"])
    assert room_after["version"] == room_before["version"] + 1, (
        "event creation increments the room's version by one"
    )


def test_attendance_equal_to_capacity_allowed_exceeding_rejected(api):
    """PRD §3.4: "attendance must be at least one (`ERR_INVALID_REQUEST`) and no
    more than the room's `capacity` (`ERR_CAPACITY_EXCEEDED`)"

    Design: Corner/validations/attendance_equals_capacity_allowed_exceeds_rejected
    """
    scn = setup_org_room(room_overrides={"capacity": 30})
    at_cap = create_event(
        scn.org, scn.room["id"],
        title="At cap", expected_attendance=30,
        start_at="2026-09-14T14:00:00Z", end_at="2026-09-14T15:00:00Z",
    )
    assert at_cap["status"] == "REQUESTED"

    response = api.create_event_reservation(
        {
            "room_id": scn.room["id"],
            "title": "Over cap",
            "expected_attendance": 31,
            "start_at": "2026-09-15T14:00:00Z",
            "end_at": "2026-09-15T15:00:00Z",
            "expected_room_version": get_room(scn.room["id"])["version"],
        },
        make_org_requester_headers(scn.org["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    _, meta = validate_paginated(api.list_event_reservations(SCHEDULER))
    assert meta["total_count"] == 1, "the over-capacity request was not persisted"


def test_required_features_must_be_subset_of_room_features(api):
    """PRD §3.4: "`required_features` must be a subset of the room's `features`
    (`ERR_FEATURE_MISMATCH`)"
    PRD §3.2: "Room edits follow the same role and cover any of `capacity`,
    `features`, `turnaround_buffer_minutes`, the three rate fields,
    `peak_multiplier_bps`, or `key_count`, incrementing the room's `version` by
    one."

    Design: Corner/validations/required_features_not_subset_rejected
    """
    scn = setup_org_room(room_overrides={"capacity": 30, "features": ["PROJECTOR"]})
    response = api.create_event_reservation(
        {
            "room_id": scn.room["id"],
            "title": "Recital",
            "expected_attendance": 10,
            "required_features": ["PIANO"],
            "start_at": "2026-09-14T14:00:00Z",
            "end_at": "2026-09-14T15:00:00Z",
            "expected_room_version": scn.room["version"],
        },
        make_org_requester_headers(scn.org["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FEATURE_MISMATCH)

    updated = validate_success(
        api.update_room(
            scn.room["id"], {"features": ["PROJECTOR", "PIANO"]}, FACILITIES_MANAGER
        ),
        200,
    )
    retry = api.create_event_reservation(
        {
            "room_id": scn.room["id"],
            "title": "Recital",
            "expected_attendance": 10,
            "required_features": ["PIANO"],
            "start_at": "2026-09-14T14:00:00Z",
            "end_at": "2026-09-14T15:00:00Z",
            "expected_room_version": updated["version"],
        },
        make_org_requester_headers(scn.org["id"]),
    )
    event = validate_success(retry, 201)
    assert event["status"] == "REQUESTED"


def test_end_not_after_start_returns_invalid_time_range(api):
    """PRD §3.4: "`end_at` must be later than `start_at` (`ERR_INVALID_TIME_RANGE`)"

    Design: Corner/validations/end_not_after_start_returns_invalid_time_range
    """
    scn = setup_org_room(room_overrides={"capacity": 30})
    response = api.create_event_reservation(
        {
            "room_id": scn.room["id"],
            "title": "Zero",
            "expected_attendance": 5,
            "start_at": "2026-09-14T14:00:00Z",
            "end_at": "2026-09-14T14:00:00Z",
            "expected_room_version": scn.room["version"],
        },
        make_org_requester_headers(scn.org["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TIME_RANGE)
    _, meta = validate_paginated(api.list_event_reservations(SCHEDULER))
    assert meta["total_count"] == 0


def test_duration_bounds_thirty_minutes_and_eight_hours_inclusive(api):
    """PRD §3.4: "the event must run at least 30 minutes and at most 8 hours
    (`ERR_DURATION_OUT_OF_RANGE`)"
    PRD §2.9: "a failure in an earlier tier surfaces its error and masks any
    failures in later tiers."

    Design: Corner/validations/duration_bounds_thirty_minutes_eight_hours
    """
    scn = setup_org_room(
        room_overrides={"capacity": 30, "turnaround_buffer_minutes": 0}
    )
    requester = make_org_requester_headers(scn.org["id"])
    room_v = scn.room["version"]

    def attempt(title, start, end, version):
        return api.create_event_reservation(
            {
                "room_id": scn.room["id"],
                "title": title,
                "expected_attendance": 5,
                "start_at": start,
                "end_at": end,
                "expected_room_version": version,
            },
            requester,
        )

    err29 = attempt(
        "29min", "2026-09-14T14:00:00Z", "2026-09-14T14:29:00Z", room_v
    )
    validate_error(err29, ApiErrorId.ERR_DURATION_OUT_OF_RANGE)

    ok30 = attempt(
        "30min", "2026-09-14T14:00:00Z", "2026-09-14T14:30:00Z", room_v
    )
    assert validate_success(ok30, 201)["status"] == "REQUESTED"

    # Shape-tier failure masks the now-stale room version carried by this call.
    err481 = attempt(
        "8h01m", "2026-09-15T08:00:00Z", "2026-09-15T16:01:00Z", room_v
    )
    validate_error(err481, ApiErrorId.ERR_DURATION_OUT_OF_RANGE)

    fresh_v = get_room(scn.room["id"])["version"]
    ok480 = attempt(
        "8h", "2026-09-16T08:00:00Z", "2026-09-16T16:00:00Z", fresh_v
    )
    assert validate_success(ok480, 201)["status"] == "REQUESTED"


def test_event_create_missing_required_start_at_returns_400(api):
    """PRD §2.9: "Request shape: required fields, enum membership, and types
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/validations/event_create_missing_required_field_returns_400
    """
    scn = setup_org_room(room_overrides={"capacity": 30})
    response = api.create_event_reservation(
        {
            "room_id": scn.room["id"],
            "title": "No start",
            "expected_attendance": 5,
            "end_at": "2026-09-14T15:00:00Z",
            "expected_room_version": scn.room["version"],
        },
        make_org_requester_headers(scn.org["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api.list_event_reservations(SCHEDULER))
    assert meta["total_count"] == 0


def test_org_requester_reads_scoped_to_own_org(api):
    """PRD §2.10: "when an `OrgRequester` addresses a resource owned by a
    different organization — an event, a service order, an invoice, or an access
    grant — the system responds with `ERR_NOT_FOUND` exactly as if the resource
    did not exist, and list endpoints silently scope an `OrgRequester`'s results
    to their own organization."

    Design: Corner/entities/org_requester_reads_scoped_to_own_org
    """
    org_a = create_org(name="Org A", contact_email="a@univ.edu")
    org_b = create_org(
        name="Org B", org_type="STUDENT_GROUP", contact_email="b@univ.edu"
    )
    room = create_room(name="SCO-1", building_code="SCO", capacity=10)
    event = create_event(
        org_a, room["id"],
        title="A's event", expected_attendance=5,
        start_at="2026-09-14T14:00:00Z", end_at="2026-09-14T15:00:00Z",
    )

    response = api.get_event_reservation(
        event["id"], make_org_requester_headers(org_b["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)

    _, meta_b = validate_paginated(
        api.list_event_reservations(make_org_requester_headers(org_b["id"]))
    )
    assert meta_b["total_count"] == 0

    _, meta_a = validate_paginated(
        api.list_event_reservations(make_org_requester_headers(org_a["id"]))
    )
    assert meta_a["total_count"] == 1


def test_event_list_paginates_with_limit_and_offset(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."
    PRD §2.3: "Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp in ascending order."

    Design: Corner/entities/event_list_pagination_limit_offset
    """
    scn = setup_org_room(room_overrides={"capacity": 10})
    for day, title in (("14", "P1"), ("15", "P2"), ("16", "P3")):
        create_event(
            scn.org, scn.room["id"],
            title=title, expected_attendance=5,
            start_at=f"2026-09-{day}T14:00:00Z",
            end_at=f"2026-09-{day}T15:00:00Z",
        )

    page1, meta1 = validate_paginated(
        api.list_event_reservations(SCHEDULER, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_event_reservations(SCHEDULER, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_response_envelope_success_and_error_shapes(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body"
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format:"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    room = create_room(name="ENV-1", building_code="ENV", capacity=10)

    ok = api.get_room(room["id"], SCHEDULER)
    assert ok.status_code == 200
    body = ok.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["id"] == room["id"]

    missing = api.get_room(NON_EXISTENT_UUID, SCHEDULER)
    err_body = missing.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)
    assert isinstance(err_body["meta"]["api_request_id"], str)
    assert isinstance(err_body["meta"]["api_request_timestamp"], str)
