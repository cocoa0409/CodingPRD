"""Provisioning, system fields, computed fields, listing, and computed reads.

Translates queue-B corner instances in sections `entities` and `endpoints`.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    fixtures,
)

MGR = TEST_USERS["studio_manager_headers"]


def test_create_studio_returns_201_with_default_policy(api):
    """PRD 3.1: "the operator-tunable penalty policy: `late_cancel_window_minutes`,
    the number of minutes before a session's start inside which a cancellation counts
    as late, defaulting to 720 (twelve hours); `late_cancel_fee_cents`, the flat fee
    for a late cancellation, defaulting to 2000; and `no_show_fee_cents`, the flat fee
    for a no-show, defaulting to 3000."
    PRD 3.1: "A studio's `status` is system-managed and is always `ACTIVE` in this
    version (there is no studio-close flow)."

    Design: Corner/entities/create_studio_returns_201_with_defaults
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    resp = api.create_studio({"name": "Downtown", "city": "NYC"}, MGR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["late_cancel_window_minutes"] == 720
    assert data["late_cancel_fee_cents"] == 2000
    assert data["no_show_fee_cents"] == 3000


def test_get_member_not_found_returns_404(api):
    """PRD 2.5: "The system validates path identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` at the first identifier that does not
    resolve to an existing resource."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    fixtures.create_studio()
    resp = api.get_member("00000000-0000-4000-8000-000000000000", MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_session_missing_required_room_id_returns_400(api):
    """PRD 3.2: "A class session is scheduled by a manager inside a studio and
    references a `room_id`, an `instructor_id`, a `start_utc`, and an `end_utc`".
    PRD 5: ERR_VALIDATION — "Malformed body: bad enum, non-positive integer,
    end_utc <= start_utc, missing required field".

    Design: Corner/entities/create_session_missing_required_room_id_returns_400
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    instr = fixtures.create_instructor()
    resp = api.create_session(
        studio["id"],
        {
            "instructor_id": instr["id"],
            "start_utc": "2026-06-10T18:00:00Z",
            "end_utc": "2026-06-10T19:00:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_create_session_end_before_start_returns_400(api):
    """PRD 3.2: "an `end_utc`, where the end must be strictly later than the start
    (a non-positive interval is rejected as malformed input)."

    Design: Corner/entities/create_session_end_before_start_returns_400
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    room = fixtures.create_room(studio["id"])
    instr = fixtures.create_instructor()
    resp = api.create_session(
        studio["id"],
        {
            "room_id": room["id"],
            "instructor_id": instr["id"],
            "start_utc": "2026-06-10T19:00:00Z",
            "end_utc": "2026-06-10T18:00:00Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_session_capacity_computed_from_active_bikes(api):
    """PRD 3.2: "the session's `capacity` is snapshotted: it is set to the count of
    bikes in the chosen room whose status is `ACTIVE` at that instant, and it must be
    at least one."
    PRD 3.2: "starts in `SCHEDULED` status, and initializes `booked_count` and
    `waitlist_count` to zero."

    Design: Corner/entities/session_capacity_computed_from_active_bikes
    """
    estate = fixtures.setup_studio_estate(n_bikes=3)
    session = fixtures.create_session(
        estate["studio"]["id"], estate["room"]["id"], estate["instructor"]["id"]
    )
    assert session["capacity"] == 3
    assert session["booked_count"] == 0


def test_system_fields_generated_on_create(api):
    """PRD 2.4: "The `id` is a server-minted UUID with no type prefix."
    PRD 2.4: "The `version` field is an integer that begins at the resource's creation
    and increments by one on every mutation."

    Design: Corner/entities/system_fields_generated_on_create
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    resp = api.create_studio({"name": "Downtown", "city": "NYC"}, MGR)
    data = validate_success(resp, expected_status=201)
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "id must be a UUID without a type prefix"
    assert "_" not in data["id"], "id must carry no type prefix"


def test_list_sessions_paginated(api):
    """PRD 2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object, where `total_count` is the number
    of items matching the query before pagination and `has_more` indicates whether
    additional items remain beyond the current page."

    Design: Corner/endpoints/list_sessions_paginated
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-21T18:00:00Z", end_utc="2026-06-21T19:00:00Z",
    )
    resp = api.list_sessions(MGR, params={"studio_id": studio_id, "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_computed_read_member_strike_count_ages_out(api):
    """PRD 2.9: "Charges older than 30 days drop out of the count automatically as the
    clock advances, and waiving a charge removes it from the count immediately."
    PRD 3.11: "Reading a member recomputes the `active_strike_count` against the
    current clock so that aged-out strikes are not counted."

    Design: Corner/endpoints/computed_read_member_strike_count
    """
    # One late cancel at 2026-06-05 (1 strike), clock advanced to 2026-07-10 (35 days).
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=1, final_strike=True)
    member_id = ctx["member"]["id"]
    fixtures.set_clock("2026-07-10T00:00:00Z")
    resp = api.get_member(member_id, make_member_headers(member_id))
    data = validate_success(resp)
    assert data["active_strike_count"] == 0, "strike older than 30 days drops out"
    assert data["account_status"] == "ACTIVE"
