"""Catalog defaults, existence and envelope shape, listing/pagination,
season close deadline, role gates, and OCC on session patch."""
from test_helpers import (
    FO,
    NON_EXISTENT_UUID,
    PC,
    ApiErrorId,
    accept_contract,
    add_meeting,
    assert_season,
    create_class_session,
    create_contract,
    create_household,
    create_instructor,
    create_participant_payload,
    create_program,
    create_published_season,
    create_room,
    create_season,
    get_session,
    household_headers,
    is_iso8601_timestamp,
    is_valid_uuid,
    publish_session,
    register_participant,
    set_clock,
    setup_household_with_participants,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api


def test_season_creation_applies_defaults(api):
    """PRD §3.1: "Three policy knobs complete the season:
    `family_discount_threshold` (the household enrollment count in the season
    at which the family discount applies; it defaults to 3 and must be at
    least 2), `family_discount_pct` (the percent taken off after the
    scholarship step; it defaults to 10 and must lie between 0 and 100
    inclusive), and `scholarship_budget_cents` (the season's total scholarship
    commitment budget; it defaults to 0 and cannot be negative). The server
    maintains `scholarship_committed_cents` — the sum of commitments across
    the season's approved applications — starting from zero. A season is born
    `DRAFT`, moves to `PUBLISHED` when the coordinator publishes it, and
    finally to `CLOSED`, which is terminal."

    Design: Corner/entities/season_creation_applies_defaults
    """
    season = create_season(
        name="Winter 2027",
        start_date="2027-01-05T00:00:00Z",
        end_date="2027-03-30T00:00:00Z",
        resident_opens_at="2026-12-01T00:00:00Z",
        general_opens_at="2026-12-08T00:00:00Z",
        registration_closes_at="2027-01-02T00:00:00Z",
    )
    assert_season(season)
    assert season["family_discount_threshold"] == 3
    assert season["family_discount_pct"] == 10
    assert season["scholarship_budget_cents"] == 0
    assert season["scholarship_committed_cents"] == 0
    assert season["status"] == "DRAFT"
    assert is_valid_uuid(season["id"])
    assert is_iso8601_timestamp(season["created_at"])


def test_household_created_pending_with_zero_credit(api):
    """PRD §3.4: "The household's `residency_status` begins `PENDING`, and its
    `account_credit_cents` balance begins at zero."

    Design: Corner/entities/household_created_with_zero_credit_pending_residency
    """
    household = create_household("New Fam")
    assert household["residency_status"] == "PENDING"
    assert household["account_credit_cents"] == 0


def test_participant_missing_birth_date_rejected(api):
    """PRD §3.4: "A `HouseholdManager` adds one with the owning `household_id`,
    a `full_name`, and a `birth_date`; the `household_id` must be the caller's
    own household, else the request is rejected with
    `ERR_NOT_HOUSEHOLD_MEMBER`."
    PRD §2.8: "Request well-formedness — required fields present, types
    correct, enum members valid, and numeric ranges honored: `capacity`
    greater than zero, `min_enrollment` at least one and no greater than
    `capacity`, amounts greater than zero, `approved_pct` one of 25, 50, 75,
    or 100, `revenue_share_bp` between 0 and 10000 inclusive, `ends_at` later
    than `starts_at`, `max_age` at least `min_age`, the season window ordering
    (`resident_opens_at` no later than `general_opens_at`, in turn no later
    than `registration_closes_at`), and `end_date` later than `start_date`.
    Violations are `ERR_INVALID_REQUEST`."

    Design: Corner/entities/participant_missing_required_birth_date
    """
    household = create_household("HX")
    payload = create_participant_payload(household["id"], full_name="No Dob")
    del payload["birth_date"]
    resp = _api.create_participant(payload, household_headers(household))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_class_session_not_found_returns_404(api):
    """PRD §2.8: "Existence — path parameters such as `season_id`,
    `program_id`, `room_id`, `instructor_id`, `session_id`, `meeting_id`,
    `contract_id`, `household_id`, `participant_id`, `form_id`,
    `application_id`, `registration_id`, `payment_id`, and `attendance_id`
    resolve strictly left to right, and the request is rejected with
    `ERR_NOT_FOUND` naming the first identifier that does not correspond to an
    existing resource; body-referenced identifiers must likewise reference
    existing resources before any business rule is evaluated."

    Design: Corner/entities/class_session_not_found_returns_404
    """
    resp = _api.get_class_session(NON_EXISTENT_UUID, PC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format"; "The `meta` object for error responses contains
    only `api_request_id` and `api_request_timestamp`."; "The `error_id` is a
    unique, machine-readable string that identifies the specific error.";
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape
    """
    resp = _api.get_household(NON_EXISTENT_UUID, FO)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_pagination_filter_interaction(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return. If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0." and "Paginated and non-paginated list-based
    responses include the following fields in the `meta` object of the
    response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.2: "Sessions can be listed with optional `program_id`,
    `instructor_id`, and `status` filters."

    Design: Corner/endpoints/pagination_filter_interaction
    """
    season = create_season()
    program_a = create_program(season["id"], name="Cluster A", category="Arts")
    program_b = create_program(season["id"], name="Cluster B", category="Sports")
    instructor = create_instructor()
    for title in ("A1", "A2", "A3"):
        create_class_session(program_a["id"], instructor["id"], title=title)
    create_class_session(program_b["id"], instructor["id"], title="B1")

    page1, meta1 = validate_paginated(
        _api.list_class_sessions(PC, params={"program_id": program_a["id"],
                                             "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert all(item["program_id"] == program_a["id"] for item in page1)

    page2, meta2 = validate_paginated(
        _api.list_class_sessions(PC, params={"program_id": program_a["id"],
                                             "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert all(item["program_id"] == program_a["id"] for item in page2)
    leaked = [i for i in page1 + page2 if i["program_id"] == program_b["id"]]
    assert leaked == [], "sessions of other programs must not leak into filtered pages"


def test_reverse_fk_filtered_listing(api):
    """PRD §3.6: "Registrations can be listed with optional `session_id`,
    `participant_id`, `household_id`, and `enrollment_status` filters."

    Design: Corner/endpoints/reverse_fk_filtered_listing
    """
    season = create_published_season()
    program = create_program(season["id"], name="Climbing", category="Sports")
    room_a = create_room(name="Wall 1")
    room_b = create_room(name="Wall 2")
    instructor_a = create_instructor(full_name="Climb A", email="ca@x.com")
    instructor_b = create_instructor(full_name="Climb B", email="cb@x.com")
    session_a = create_class_session(program["id"], instructor_a["id"], title="SA",
                                     fee_resident_cents=1000,
                                     fee_nonresident_cents=1000)
    session_b = create_class_session(program["id"], instructor_b["id"], title="SB",
                                     fee_resident_cents=1000,
                                     fee_nonresident_cents=1000)
    contract_a = create_contract(session_a["id"], instructor_a["id"])
    contract_b = create_contract(session_b["id"], instructor_b["id"])
    add_meeting(session_a["id"], room_a["id"])
    add_meeting(session_b["id"], room_b["id"])
    accept_contract(contract_a["id"], instructor_a["id"])
    accept_contract(contract_b["id"], instructor_b["id"])
    publish_session(session_a["id"])
    publish_session(session_b["id"])
    household, participants = setup_household_with_participants(count=3,
                                                                account_name="HC")
    set_clock("2026-08-17T00:00:00Z")
    register_participant(session_a["id"], participants[0]["id"], household["id"])
    register_participant(session_a["id"], participants[1]["id"], household["id"])
    other = register_participant(session_b["id"], participants[2]["id"], household["id"])

    data, meta = validate_paginated(
        _api.list_registrations(PC, params={"session_id": session_a["id"]})
    )
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert all(item["session_id"] == session_a["id"] for item in data)
    assert other["id"] not in {item["id"] for item in data}


def test_season_close_before_deadline_rejected(api):
    """PRD §3.1: "Closing a season is allowed only once now has reached
    `registration_closes_at`; an early close is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/season_close_before_deadline_rejected
    """
    season = create_published_season()
    set_clock("2026-09-01T00:00:00Z")
    resp = _api.close_season(season["id"], PC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    set_clock("2026-09-15T00:00:00Z")
    closed = validate_success(_api.close_season(season["id"], PC))
    assert closed["status"] == "CLOSED"


def test_household_cannot_publish_session(api):
    """PRD §2.1: "Access to each operation is further restricted by role; an
    attempt to perform an action outside the caller's designated role is
    rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/household_cannot_publish_session
    """
    season = create_published_season()
    program = create_program(season["id"], name="Coding", category="Education")
    room = create_room(name="Lab C")
    instructor = create_instructor()
    session = create_class_session(program["id"], instructor["id"], title="SD")
    contract = create_contract(session["id"], instructor["id"])
    add_meeting(session["id"], room["id"])
    accept_contract(contract["id"], instructor["id"])
    household = create_household("HQ")

    resp = _api.publish_class_session(session["id"], household_headers(household))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
    assert get_session(session["id"])["status"] == "DRAFT"


def test_occ_stale_version_on_session_patch(api):
    """PRD §2.7: "Updating a session's `capacity`, `min_enrollment`, or
    `enrollment_check_at` is likewise guarded: the request must carry
    `expected_class_session_version` matching the session's current `version`.
    Enrollments and waitlist movements change the session's counters and
    version, so a client reasoning about capacity-versus-enrollment from an
    older read is acting on stale data; a mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_session_patch
    """
    season = create_season()
    program = create_program(season["id"], name="Cycling", category="Sports")
    instructor = create_instructor()
    session = create_class_session(program["id"], instructor["id"], title="SX")
    observed_version = session["version"]

    patched = validate_success(
        _api.patch_class_session(
            session["id"],
            {"capacity": 8, "expected_class_session_version": observed_version},
            PC,
        )
    )
    assert patched["capacity"] == 8
    assert patched["version"] == observed_version + 1

    resp = _api.patch_class_session(
        session["id"],
        {"min_enrollment": 2, "expected_class_session_version": observed_version},
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_session(session["id"])["min_enrollment"] == 1
