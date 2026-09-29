"""The organisational skeleton: districts, schools, windows and lots.

Creation shapes, declared defaults, body validation, not-found vocabulary and
the logical clock that every timestamp is read from.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_LOGICAL_CLOCK_UTC,
    TEST_CALENDAR,
    assert_custody_event,
    assert_district,
    assert_session,
    assert_test_window,
    create_district_payload,
    create_school_payload,
    create_session_payload,
    create_test_window_payload,
    is_valid_uuid,
    make_district_coordinator_headers,
    make_officer_headers,
    make_school_coordinator_headers,
    receipt,
    set_clock,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_district_creation_returns_zeroed_ledger_and_reads_back(api):
    """PRD §3.1: "A newly registered district starts with a clean ledger: its
    `replacement_charge_total_cents`, its `security_assessment_cents`, and its
    `open_discrepancy_count` are all 0."
    PRD §4: "Endpoints that bring a brand-new resource into existence respond
    with **201 Created**; every other successful call — reads, transitions,
    assignments, codings, decisions, attendance and score recordings,
    reconciliations, and the distribution and clock operations — responds with
    **200 OK**."

    Design: Corner/entities/district_creation_returns_201_with_zeroed_ledger_and_readable_afterwards
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    created = validate_success(
        api.create_district(
            create_district_payload(district_code="NG-1001"), make_officer_headers()),
        expected_status=201)
    assert_district(created)
    assert created["district_code"] == "NG-1001"
    assert created["state_code"] == "NG"
    assert created["replacement_charge_total_cents"] == 0
    assert created["security_assessment_cents"] == 0
    assert created["open_discrepancy_count"] == 0

    read_back = validate_success(
        api.get_district(created["id"], make_district_coordinator_headers(created["id"])))
    assert read_back["district_code"] == "NG-1001"
    assert read_back["id"] == created["id"]
    assert read_back["replacement_charge_total_cents"] == 0


def test_school_listing_filters_by_district_with_pagination_meta(api):
    """PRD §2.3: "The `limit` parameter caps how many items come back; it
    defaults to 10, may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    sorted by their creation timestamp in ascending order. List responses carry
    `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of
    the envelope."
    PRD §2.3: "Schools may be narrowed by `district_id`."

    Design: Corner/entities/school_listing_filters_by_district_and_reports_pagination_fields
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])
    district = validate_success(
        api.create_district(create_district_payload(district_code="NG-1002"),
                            make_officer_headers()), expected_status=201)
    school_ids = []
    for name, code in (("Alpha High", "AH-01"), ("Beta High", "BH-01"),
                       ("Gamma High", "GH-01")):
        school = validate_success(
            api.create_school(
                create_school_payload(district["id"], name=name, school_code=code,
                                      max_concurrent_seats=30),
                make_officer_headers()), expected_status=201)
        school_ids.append(school["id"])

    data, meta = validate_paginated(api.list_schools(
        make_officer_headers(),
        params={"district_id": district["id"], "limit": 2, "offset": 0}))

    assert meta["total_count"] == 3, f"Expected 3 schools, meta says {meta}"
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(data) == 2, f"Expected a page of 2 rows, got {len(data)}"
    assert data[0]["id"] == school_ids[0], "list must be ordered by created_at ascending"


def test_test_window_optional_inputs_take_their_declared_defaults(api):
    """PRD §3.2: "The `appeal_window_days` value, between 1 and 45 inclusive,
    sets how long families and staff have to appeal a released score and
    defaults to 10."
    PRD §3.2: "The `min_participation_pct` value, between 0.0 and 100.0
    inclusive, sets the participation floor the window must clear before results
    may be released and defaults to 95.0."
    PRD §3.2: "Fresh windows begin in `PLANNED` with `security_hold` false,
    `open_breach_count` 0, `released_at` and `appeal_window_closes_at` null,
    both participation percentages null, and `registered_distinct_count` and
    `present_distinct_count` at 0."

    Design: Corner/entities/test_window_omitted_optionals_receive_declared_defaults
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    window = validate_success(
        api.create_test_window(
            create_test_window_payload(name="Fall ELA G3-5", grade_band="G3_5"),
            make_officer_headers()), expected_status=201)

    assert_test_window(window)
    assert window["appeal_window_days"] == 10
    assert window["min_participation_pct"] == 95.0
    assert window["status"] == "PLANNED"
    assert window["security_hold"] is False
    assert window["open_breach_count"] == 0
    assert window["participation_rate_provisional_pct"] is None
    assert window["participation_rate_final_pct"] is None
    assert window["released_at"] is None
    assert window["appeal_window_closes_at"] is None
    assert window["registered_distinct_count"] == 0
    assert window["present_distinct_count"] == 0


def test_district_creation_without_state_code_is_rejected(api):
    """PRD §3.1: "A district is registered with a human-readable `name` of
    between 1 and 120 characters, a `district_code` that must be two uppercase
    letters, a hyphen, and four digits, and a `state_code` of exactly two
    uppercase letters naming the state the district reports under."
    PRD §2.7: "**Body well-formedness** — every required field present, every
    enum value a declared member, every number inside its declared range, every
    string matching its declared pattern, every datetime a parseable ISO 8601
    UTC instant, and every cross-field arithmetic rule satisfied. Failure:
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/district_creation_missing_required_field_returns_invalid_request
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    response = api.create_district(
        {"name": "Northgate District", "district_code": "NG-1003"},
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    data, meta = validate_paginated(api.list_schools(make_officer_headers()))
    assert meta["total_count"] == 0, "the rejected request must create nothing"


def test_test_window_rejects_a_subject_outside_the_declared_set(api):
    """PRD §3.2: "A test window is the temporal container for everything else,
    and a `StateAssessmentOfficer` creates one by declaring a `name` of 1 to 120
    characters, a `subject` drawn from `ELA`, `MATH`, `SCIENCE`, and
    `SOCIAL_STUDIES`, a `grade_band` drawn from `G3_5`, `G6_8`, and `G9_12`, and
    four instants: `window_start` and `window_end` bounding the initial testing
    period, and `makeup_start` and `makeup_end` bounding the make-up period."
    PRD §2.7: "**Body well-formedness** — every required field present, every
    enum value a declared member, every number inside its declared range, every
    string matching its declared pattern, every datetime a parseable ISO 8601
    UTC instant, and every cross-field arithmetic rule satisfied. Failure:
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/test_window_unknown_subject_enum_rejected
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    response = api.create_test_window(
        create_test_window_payload(name="Fall HIST G6-8", subject="HISTORY",
                                   grade_band="G6_8"),
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    data, meta = validate_paginated(api.list_test_windows(make_officer_headers()))
    assert meta["total_count"] == 0, "no window row may survive the rejection"


def test_material_lot_seal_range_must_tally_with_quantity_shipped(api):
    """PRD §3.5: "The range and the count must agree exactly: subtracting
    `seal_range_start` from `seal_range_end` and adding one must equal
    `quantity_shipped`, and a range that does not tally is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/material_lot_seal_range_must_match_quantity_shipped
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])
    district = validate_success(
        api.create_district(create_district_payload(district_code="NG-1004"),
                            make_officer_headers()), expected_status=201)
    window = validate_success(
        api.create_test_window(create_test_window_payload(name="Fall ELA G6-8",
                                                          grade_band="G6_8"),
                               make_officer_headers()), expected_status=201)

    response = api.create_material_lot(
        {"window_id": window["id"], "district_id": district["id"],
         "lot_code": "LOT-Z1", "quantity_shipped": 10,
         "seal_range_start": 2000, "seal_range_end": 2008},
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    data, meta = validate_paginated(api.list_material_lots(
        make_officer_headers(), params={"window_id": window["id"]}))
    assert meta["total_count"] == 0, "a mistallied lot must not be shipped"


def test_resource_identifier_is_a_bare_server_minted_uuid(api):
    """PRD §2.4: "**`id`** (string): a server-minted unique identifier formatted
    as a UUID, with no type prefix of any kind."
    PRD §2.5: "Every timestamp the server stamps — `signed_at` on an affidavit,
    `occurred_at` on a custody entry, `opened_at` and `closed_at` on a session,
    `released_at` on a window, `training_completed_at` and `revoked_at` on a
    proctor, `filed_at`, `decided_at`, `adjudicated_at`, `reconciled_at`, and
    `report_delivered_at` — is read from that logical clock, and every
    time-gated precondition compares against the same clock."

    Design: Corner/entities/server_minted_system_fields_are_not_client_settable
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    created = validate_success(
        api.create_district(create_district_payload(district_code="NG-1005"),
                            make_officer_headers()), expected_status=201)

    assert is_valid_uuid(created["id"]), (
        f"id must be a bare UUID with no type prefix, got {created['id']!r}")
    assert created["created_at"] == "2026-09-01T08:00:00.000Z", (
        "created_at is stamped from the logical clock")
    assert created["updated_at"] == "2026-09-01T08:00:00.000Z"


def test_custody_entry_exposes_no_version_and_no_updated_at(api):
    """PRD §2.4: "Custody entries are the single exception. A custody entry is
    an append-only fact about a physical movement of booklets and is never
    edited after it is written, so it carries only `id` and `created_at`. It has
    neither an `updated_at` nor a `version` property, and requests must not
    expect either to be present."
    PRD §3.5: "Everything else on the entry is server-derived and never
    client-supplied: the `sequence_no` as a one-based position within this lot's
    chain, the `previous_event_id` pointing at the immediately preceding entry
    on the same lot (null for the lot's first entry), the `from_holder_type` and
    `to_holder_type` naming which bucket the booklets left and entered, the
    `actor_user_id` and `actor_role` taken from the request headers, the
    `occurred_at` instant taken from the logical clock, and the
    `chain_balance_after` described below."

    Design: Corner/entities/custody_event_is_immutable_and_carries_no_version
    """
    ctx = setup_program(district_code="NG-1006", school_code="AH-01",
                        lot_code="LOT-Z2", seal_start=2300, open_the_window=False)
    event = receipt(ctx["lot"]["id"], ctx["district"]["id"], 10)

    read_back = validate_success(api.get_custody_event(
        event["id"], make_district_coordinator_headers(ctx["district"]["id"])))

    assert_custody_event(read_back)
    assert read_back["sequence_no"] == 1
    assert read_back["previous_event_id"] is None
    assert read_back["from_holder_type"] == "STATE"
    assert read_back["to_holder_type"] == "DISTRICT"
    assert read_back["actor_role"] == "DistrictTestCoordinator"
    assert read_back["occurred_at"] == "2026-09-01T08:00:00.000Z"
    assert read_back["chain_balance_after"] == 10
    assert "version" not in read_back
    assert "updated_at" not in read_back


def test_school_created_under_an_unknown_district_is_not_found(api):
    """PRD §2.6: "The same catalogue governs identifiers supplied inside a
    request body rather than in the path. A `district_id` on a school, a
    `window_id` or `school_id` on a session, a `proctor_id` on an assignment or
    an affidavit, the `window_id` on an affidavit, a `session_id` or
    `makeup_of_registration_id` on a registration, a `window_id` or
    `district_id` on a material lot, a `session_id` on a custody entry, a
    `session_id` or `registration_id` on an irregularity report, and a
    `registration_id` on a score appeal all resolve against the same error
    vocabulary and the same 404 status."
    PRD §2.6: "Each identifier has its own error: `district_id` produces
    `ERR_DISTRICT_NOT_FOUND`, `school_id` produces `ERR_SCHOOL_NOT_FOUND`,
    `window_id` produces `ERR_TEST_WINDOW_NOT_FOUND`, `proctor_id` produces
    `ERR_PROCTOR_NOT_FOUND`, `security_affidavit_id` produces
    `ERR_SECURITY_AFFIDAVIT_NOT_FOUND`, `session_id` produces
    `ERR_SESSION_NOT_FOUND`, `registration_id` produces
    `ERR_REGISTRATION_NOT_FOUND`, `material_lot_id` produces
    `ERR_MATERIAL_LOT_NOT_FOUND`, `custody_event_id` produces
    `ERR_CUSTODY_EVENT_NOT_FOUND`, `irregularity_report_id` produces
    `ERR_IRREGULARITY_REPORT_NOT_FOUND`, and `score_appeal_id` produces
    `ERR_SCORE_APPEAL_NOT_FOUND`."

    Design: Corner/entities/school_creation_with_unknown_district_parent_returns_not_found
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    response = api.create_school(
        create_school_payload(UNKNOWN_ID, name="Orphan High", school_code="OH-99",
                              max_concurrent_seats=20),
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_DISTRICT_NOT_FOUND.value, 404)

    data, meta = validate_paginated(api.list_schools(make_officer_headers()))
    assert meta["total_count"] == 0, "no orphan school may be created"


@pytest.mark.parametrize("reader,expected_error", [
    ("get_district", ApiErrorId.ERR_DISTRICT_NOT_FOUND),
    ("get_school", ApiErrorId.ERR_SCHOOL_NOT_FOUND),
    ("get_test_window", ApiErrorId.ERR_TEST_WINDOW_NOT_FOUND),
    ("get_proctor", ApiErrorId.ERR_PROCTOR_NOT_FOUND),
    ("get_security_affidavit", ApiErrorId.ERR_SECURITY_AFFIDAVIT_NOT_FOUND),
    ("get_session", ApiErrorId.ERR_SESSION_NOT_FOUND),
    ("get_registration", ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
    ("get_material_lot", ApiErrorId.ERR_MATERIAL_LOT_NOT_FOUND),
    ("get_custody_event", ApiErrorId.ERR_CUSTODY_EVENT_NOT_FOUND),
    ("get_irregularity_report", ApiErrorId.ERR_IRREGULARITY_REPORT_NOT_FOUND),
    ("get_score_appeal", ApiErrorId.ERR_SCORE_APPEAL_NOT_FOUND),
])
def test_each_resource_reader_answers_its_own_not_found_error(api, reader,
                                                              expected_error):
    """PRD §2.6: "Each identifier has its own error: `district_id` produces
    `ERR_DISTRICT_NOT_FOUND`, `school_id` produces `ERR_SCHOOL_NOT_FOUND`,
    `window_id` produces `ERR_TEST_WINDOW_NOT_FOUND`, `proctor_id` produces
    `ERR_PROCTOR_NOT_FOUND`, `security_affidavit_id` produces
    `ERR_SECURITY_AFFIDAVIT_NOT_FOUND`, `session_id` produces
    `ERR_SESSION_NOT_FOUND`, `registration_id` produces
    `ERR_REGISTRATION_NOT_FOUND`, `material_lot_id` produces
    `ERR_MATERIAL_LOT_NOT_FOUND`, `custody_event_id` produces
    `ERR_CUSTODY_EVENT_NOT_FOUND`, `irregularity_report_id` produces
    `ERR_IRREGULARITY_REPORT_NOT_FOUND`, and `score_appeal_id` produces
    `ERR_SCORE_APPEAL_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/entities/every_path_scoped_resource_has_its_own_not_found_error
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    response = getattr(api, reader)(UNKNOWN_ID, make_officer_headers())
    validate_error(response, expected_error.value, 404)


def test_new_session_derives_its_seat_fields_rather_than_accepting_them(api):
    """PRD §3.3: "The new session is born in `DRAFT` with a null `proctor_id`,
    null `opened_at` and `closed_at`, `seats_consumed` at 0,
    `separate_setting_count` at 0, `materials_checked_out` and
    `materials_checked_in` at 0, and an `effective_seat_capacity` already
    computed by the seat-pressure rule of §3.4."
    PRD §3.4: "On the supply side, the session begins from the smaller of its
    own `seat_capacity` and the owning school's `max_concurrent_seats`, then
    subtracts a proctor-span penalty for supervising scattered settings."

    Design: Corner/entities/session_computed_seat_fields_are_derived_not_supplied
    """
    ctx = setup_program(district_code="NG-1007", school_code="SH-01",
                        lot_code="LOT-Z3", seal_start=2400,
                        max_concurrent_seats=60)

    session = validate_success(
        api.create_session(
            create_session_payload(ctx["window"]["id"], ctx["school"]["id"],
                                   room_code="R101", seat_capacity=12),
            make_school_coordinator_headers(ctx["school"]["id"])),
        expected_status=201)

    assert_session(session)
    assert session["status"] == "DRAFT"
    assert session["proctor_id"] is None
    assert session["opened_at"] is None
    assert session["closed_at"] is None
    assert session["seats_consumed"] == 0
    assert session["separate_setting_count"] == 0
    assert session["materials_checked_out"] == 0
    assert session["materials_checked_in"] == 0
    assert session["effective_seat_capacity"] == 12, (
        "effective capacity is the smaller of seat_capacity 12 and school max 60")


def test_logical_clock_starts_at_the_fixed_instant_and_is_settable(api):
    """PRD §2.5: "Before any request has moved it, the clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."
    PRD §2.5: "A `StateAssessmentOfficer` may set the clock to a supplied
    instant by naming that instant in the `to_iso8601` field. The response
    reports the new clock as `current_utc`."

    Design: Corner/cross_cutting_complexity_layers/logical_clock_defaults_to_the_fixed_startup_instant
    """
    created = validate_success(
        api.create_district(create_district_payload(district_code="NG-1042"),
                            make_officer_headers()), expected_status=201)
    assert created["created_at"] == DEFAULT_LOGICAL_CLOCK_UTC, (
        "before any clock-set call the server stamps the fixed startup instant")

    read_back = validate_success(
        api.get_district(created["id"], make_officer_headers()))
    assert read_back["created_at"] == DEFAULT_LOGICAL_CLOCK_UTC

    moved = validate_success(
        api.set_clock({"to_iso8601": "2026-12-25T09:30:00Z"}, make_officer_headers()))
    assert moved["current_utc"] == "2026-12-25T09:30:00.000Z"
