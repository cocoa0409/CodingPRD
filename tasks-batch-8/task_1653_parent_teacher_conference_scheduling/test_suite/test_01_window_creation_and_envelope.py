"""Window creation rules, entity field defaults, and response envelope shape."""
from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    add_family,
    assert_booking,
    assert_window,
    create_student_payload,
    create_window_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_family_with_students,
    setup_window_at_stage,
    validate_error,
    validate_success,
)


def test_create_window_with_all_required_fields_returns_draft(api, school_admin_headers):
    """PRD 3.1: "A new window is born in `DRAFT` status with `ops_run_index` at
    0, every counter at 0, and `version` at 1."
    PRD 4: "Operations that create new, stand-alone resources — a window,
    teacher, family, student, student-teacher link, booking, interpreter,
    interpreter request, waitlist entry, or outreach task — return a `201
    Created` status code; the waitlist claim also returns `201 Created` because
    it creates the booking it produces."

    Design: Corner/entities/create_window_with_all_required_fields_returns_201
    """
    response = api.create_window(create_window_payload(), school_admin_headers)
    data = validate_success(response, 201)
    assert_window(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["ops_run_index"] == 0
    assert data["slots_total_count"] == 0
    assert data["slots_open_count"] == 0
    assert data["slots_held_count"] == 0
    assert data["slots_booked_count"] == 0
    assert data["bookings_confirmed_count"] == 0
    assert data["waitlist_waiting_count"] == 0
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_create_window_missing_required_name_rejected(api, school_admin_headers):
    """PRD 2.7: "Required fields present, types valid, enum members valid,
    ranges valid — `grade_level` between 0 and 12 inclusive, positive minute
    and cap values where required; failures yield `ERR_VALIDATION` (422)."
    PRD 3.1: "A `SchoolAdmin` creates one by supplying a human-readable `name`
    such as "Fall Conferences", a `term_label` such as "2026-FALL", and a
    `format` of either `ELEMENTARY` or `SECONDARY` — the format drives the
    booking rules later, since elementary families book a single homeroom
    conference while secondary families book per teacher."

    Design: Corner/entities/create_window_missing_required_name_rejected
    """
    payload = create_window_payload()
    del payload["name"]
    response = api.create_window(payload, school_admin_headers)
    validate_error(response, ApiErrorId.ERR_VALIDATION, 422)


def test_create_window_invalid_format_enum_rejected(api, school_admin_headers):
    """PRD 3.1: "A `SchoolAdmin` creates one by supplying a human-readable
    `name` such as "Fall Conferences", a `term_label` such as "2026-FALL", and
    a `format` of either `ELEMENTARY` or `SECONDARY` — the format drives the
    booking rules later, since elementary families book a single homeroom
    conference while secondary families book per teacher."
    PRD 2.7: "Required fields present, types valid, enum members valid, ranges
    valid — `grade_level` between 0 and 12 inclusive, positive minute and cap
    values where required; failures yield `ERR_VALIDATION` (422)."

    Design: Corner/entities/create_window_invalid_format_enum_rejected
    """
    payload = create_window_payload(format="MIDDLE")
    response = api.create_window(payload, school_admin_headers)
    validate_error(response, ApiErrorId.ERR_VALIDATION, 422)


def test_create_student_grade_out_of_range_rejected(api, front_office_headers):
    """PRD 2.7: "Required fields present, types valid, enum members valid,
    ranges valid — `grade_level` between 0 and 12 inclusive, positive minute
    and cap values where required; failures yield `ERR_VALIDATION` (422)."
    PRD 3.3: "Students are registered under a family by staff or by the
    family's own guardian, supplying a `full_name` and a `grade_level` between
    0 and 12 inclusive, where 0 denotes kindergarten."

    Design: Corner/entities/create_student_grade_out_of_range_rejected
    """
    family = add_family()
    response = api.create_student(
        family["id"], create_student_payload(grade_level=13), front_office_headers
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION, 422)


def test_window_optional_defaults_applied(api, school_admin_headers):
    """PRD 3.1: "Finally, the administrator sets quotas and policy knobs:
    `teacher_daily_conf_cap` (the maximum number of `CONFIRMED` bookings a
    teacher may hold on one day, which must be positive), and the optional
    `family_conf_cap` (default 8), `cancel_cutoff_hours` (default 24),
    `waitlist_offer_ttl_hours` (default 24), `no_show_strike_threshold`
    (default 3), and `auto_no_show_grace_hours` (default 24)."

    Design: Corner/entities/window_optional_defaults_applied
    """
    payload = {
        "name": "Fall",
        "term_label": "2026-FALL",
        "format": "SECONDARY",
        "slot_length_minutes": 15,
        "buffer_minutes": 5,
        "travel_minutes": 25,
        "day_windows": [{
            "date": "2026-10-06",
            "start_at": "2026-10-06T15:00:00Z",
            "end_at": "2026-10-06T18:00:00Z",
        }],
        "booking_open_at": "2026-09-01T00:00:00Z",
        "booking_close_at": "2026-10-01T00:00:00Z",
        "teacher_daily_conf_cap": 5,
    }
    response = api.create_window(payload, school_admin_headers)
    data = validate_success(response, 201)
    assert_window(data)
    assert data["family_conf_cap"] == 8
    assert data["cancel_cutoff_hours"] == 24
    assert data["waitlist_offer_ttl_hours"] == 24
    assert data["no_show_strike_threshold"] == 3
    assert data["auto_no_show_grace_hours"] == 24


def test_get_window_not_found_returns_404(api, school_admin_headers):
    """PRD 2.7: "Path parameters are validated left to right; the first
    identifier that does not resolve to an existing resource rejects the
    request with `ERR_NOT_FOUND` (404) before any later segment is examined."

    Design: Corner/entities/get_window_not_found_returns_404
    """
    response = api.get_window(MISSING_UUID, school_admin_headers)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND, 404)


def test_create_student_unknown_family_returns_404(api, front_office_headers):
    """PRD 2.7: "Path parameters are validated left to right; the first
    identifier that does not resolve to an existing resource rejects the
    request with `ERR_NOT_FOUND` (404) before any later segment is examined."

    Design: Corner/entities/create_student_unknown_family_returns_404
    """
    response = api.create_student(
        MISSING_UUID, create_student_payload(), front_office_headers
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND, 404)


def test_booking_response_envelope_shape(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD 3.4: "The recorded `booked_by_role` is `FAMILY_SELF` for a guardian
    booking and `FRONT_OFFICE` when staff book on behalf."
    PRD 3.4: "The booking's `window_id` and `teacher_id` are derived from the
    slot, and its `family_id` is derived from the student's owning family — a
    guardian may only book for a student of their own family, otherwise
    `ERR_FORBIDDEN`."

    Design: Corner/endpoints/booking_response_envelope_shape
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    slot = ctx["teacher_slots"][teacher_id][0]

    response = api.create_booking(
        {"slot_id": slot["id"], "student_id": party["students"][0]["id"],
         "channel": "IN_PERSON"},
        party["guardian"],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"]["api_request_id"]
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    data = body["data"]
    assert_booking(data)
    assert data["status"] == "CONFIRMED"
    assert data["booked_by_role"] == "FAMILY_SELF"
    assert data["window_id"] == ctx["window"]["id"]
    assert data["teacher_id"] == teacher_id
    assert data["family_id"] == party["family"]["id"]


def test_error_response_envelope_shape(api, school_admin_headers):
    """PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/error_response_envelope_shape
    """
    response = api.get_teacher(MISSING_UUID, school_admin_headers)
    assert response.status_code == 404
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"].get("error_id"), str)
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"].strip()
