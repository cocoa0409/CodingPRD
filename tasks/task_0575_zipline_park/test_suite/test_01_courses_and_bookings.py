"""CRUD, computed fields, defaults, and list envelopes (PRD §2, §3.1, §3.4, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_guide_headers, NON_EXISTENT_UUID,
    create_course_payload, create_participant_payload, create_time_slot_payload,
    create_incident_report_payload,
    assert_incident_report,
    setup_course_slot_guide, create_participant, create_booking, create_course,
    create_time_slot, get_time_slot,
    WEEKDAY_SLOT_START,
)

OP = TEST_USERS["operator_headers"]


def test_create_course_returns_201_and_echoes_fields(api):
    """PRD §4: "Operations that create a new, stand-alone resource return `201 Created`."
    PRD §3.1: "Commercially it carries a `base_price_cents` (the per-participant base
    price in cents), a `duration_minutes` (how long the tour runs), a `default_capacity`".

    Design: Corner/entities/create_course_returns_201_and_echoes_fields
    """
    res = api.create_course(create_course_payload(base_price_cents=5000,
                                                   difficulty_level=2), OP)
    course = validate_success(res, 201)
    assert course["base_price_cents"] == 5000
    assert course["difficulty_level"] == 2
    assert course["id"]


def test_participant_age_years_computed_from_clock(api):
    """PRD §2.5: "A participant's `age_years` is the number of whole (fully completed)
    years between their `birthdate` and the current clock instant."

    Design: Corner/entities/participant_age_years_computed_from_clock
    """
    res = api.create_participant(
        create_participant_payload(full_name="Kid", weight_kg=40,
                                   birthdate="2016-05-01T00:00:00Z"), OP)
    p = validate_success(res, 201)
    assert p["age_years"] == 10


def test_timeslot_end_at_computed_from_duration(api):
    """PRD §3.1: "The slot's `end_at` is computed as `start_at` plus the course's
    `duration_minutes`."
    PRD §3.1: "when `capacity` is omitted it defaults to the course's `default_capacity`."

    Design: Corner/entities/timeslot_end_at_computed_from_duration
    """
    course = create_course(api, duration_minutes=90, default_capacity=4)
    res = api.create_time_slot(
        create_time_slot_payload(course["id"], WEEKDAY_SLOT_START), OP)
    ts = validate_success(res, 201)
    assert ts["end_at"] == "2026-06-03T11:30:00.000Z"
    assert ts["capacity"] == 4


def test_get_nonexistent_booking_returns_404(api):
    """PRD §2.9: "every resource named in the path and every foreign key referenced in
    the body must exist, validated left-to-right in path order; the first missing one
    yields `ERR_NOT_FOUND`."

    Design: Corner/entities/booking_not_found_returns_404
    """
    res = api.get_booking(NON_EXISTENT_UUID, OP)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_course_missing_required_field_returns_400(api):
    """PRD §2.9: "on write endpoints, required fields must be present, enums must hold
    legal values, numeric fields must be numeric, and where a season pass is issued the
    window must satisfy `valid_until` strictly after `valid_from`; otherwise
    `ERR_VALIDATION`."

    Design: Corner/entities/course_missing_required_field_returns_400
    """
    payload = create_course_payload()
    del payload["base_price_cents"]
    res = api.create_course(payload, OP)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_booking_use_season_pass_defaults_false(api):
    """PRD §3.4: "The system sets `season_pass_id` to the id of the pass consumed when
    `use_season_pass` is requested and a usable pass exists, and to null otherwise."
    PRD §3.4: "otherwise `price_cents` is the discounted amount rounded half-up to whole
    cents in a single final rounding step."

    Design: Corner/entities/booking_use_season_pass_defaults_false
    """
    course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api)
    res = api.create_booking(
        {"time_slot_id": ts["id"], "participant_id": p["id"]}, OP)
    booking = validate_success(res, 201)
    assert booking["season_pass_id"] is None
    assert booking["price_cents"] == 5000


def test_incident_report_created_append_only(api):
    """PRD §4: "Operations that create a new, stand-alone resource return `201 Created`."
    PRD §3.9: "Incident reports are append-only records — they are never updated after
    creation, and accordingly they carry only an `id` and a `created_at` with no
    `updated_at` or `version`."
    PRD §3.9: "The incident reports attached to a booking can be listed back for review."

    Design: Corner/entities/incident_report_created_append_only
    """
    course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api)
    booking = create_booking(api, ts["id"], p["id"])
    guide_hdr = make_guide_headers(guide["id"])
    res = api.create_incident_report(
        create_incident_report_payload(booking["id"], guide["id"], severity="SEVERE"),
        guide_hdr)
    ir = validate_success(res, 201)
    assert_incident_report(ir)
    assert ir["severity"] == "SEVERE"

    listed, meta = validate_paginated(
        api.list_incident_reports(booking["id"], OP))
    assert any(r["id"] == ir["id"] for r in listed)


def test_list_bookings_filtered_by_time_slot_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."
    PRD §2.3: "Every list-based response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_bookings_filtered_by_time_slot_envelope
    """
    course, ts, guide = setup_course_slot_guide(api)
    p_a = create_participant(api, full_name="P A")
    p_b = create_participant(api, full_name="P B")
    create_booking(api, ts["id"], p_a["id"])
    create_booking(api, ts["id"], p_b["id"])

    data, meta = validate_paginated(
        api.list_bookings(OP, params={"time_slot_id": ts["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_derived_slot_remaining_reconciled_on_create(api):
    """PRD §2.8: "A `TimeSlot` exposes `booked_count` (how many of its bookings are
    currently active) and `remaining_capacity` (its `capacity` minus `booked_count`,
    never allowed to go below zero)."
    PRD §3.4: "A slot's `booked_count` is the count of its bookings in the three active
    states `CONFIRMED`, `CHECKED_IN`, and `BRIEFED`".

    Design: Corner/cross_cutting_complexity_layers/derived_slot_remaining_reconciled_on_create
    """
    course, ts, guide = setup_course_slot_guide(api, capacity=4)
    p = create_participant(api)
    create_booking(api, ts["id"], p["id"])
    slot = get_time_slot(api, ts["id"])
    assert slot["remaining_capacity"] == 3
    assert slot["booked_count"] == 1
