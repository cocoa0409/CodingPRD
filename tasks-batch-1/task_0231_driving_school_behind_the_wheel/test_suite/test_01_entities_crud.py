"""CRUD, creation defaults, computed fields, listing, and wallet endpoints.

Corner-design queue B: sections `entities` and `endpoints`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_student_payload, create_vehicle_payload,
    create_guardian_consent_payload, create_wallet_entry_payload,
    assert_student,
    set_clock, create_student,
    setup_classroom_scheduling_context, schedule_lesson,
)

ADMIN = TEST_USERS["admin_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_student_returns_201_with_computed_defaults(api):
    """PRD §3.2: "The student is created at the `PROSPECT` milestone, and the
    system seeds the computed ledgers — `completed_classroom_hours`,
    `completed_online_hours`, `completed_road_hours`, `scheduled_road_hours`,
    `readiness_score`, `no_show_count`, and `wallet_balance_cents` — at zero."
    PRD §2.4: "`version`: a system-managed integer that begins at its initial
    value and increments by one with every modification to the resource."

    Design: Corner/entities/create_student_returns_201_with_computed_defaults
    """
    set_clock("2026-06-01T00:00:00.000Z")
    resp = api.create_student(
        create_student_payload(full_name="New Stu", email="new@x.com",
                               date_of_birth="1995-01-01"),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_student(data)
    assert data["status"] == "PROSPECT"
    assert data["completed_road_hours"] == 0
    assert data["completed_classroom_hours"] == 0
    assert data["completed_online_hours"] == 0
    assert data["scheduled_road_hours"] == 0
    assert data["readiness_score"] == 0
    assert data["no_show_count"] == 0
    assert data["wallet_balance_cents"] == 0
    assert data["version"] == 1
    assert data["is_minor"] is False


def test_get_nonexistent_student_returns_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing
    resource causes the whole request to fail with `ERR_NOT_FOUND` before any
    later reference is examined."

    Design: Corner/entities/get_nonexistent_student_returns_not_found
    """
    resp = api.get_student(NON_EXISTENT, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_student_missing_required_field_rejected(api):
    """PRD §3.2: "A `SchoolAdmin` registers a learner by supplying their
    `full_name`, contact `email`, and `date_of_birth`."
    PRD §2.11: "The well-formedness of the request body (`ERR_INVALID_REQUEST`,
    400) ... round out the catalogue."

    Design: Corner/entities/create_student_missing_required_field_rejected
    """
    resp = api.create_student(
        {"full_name": "No DOB", "email": "nodob@x.com"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_duplicate_vehicle_plate_rejected(api):
    """PRD §3.6: "A colliding instructor `email` or vehicle `plate` is rejected
    with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_vehicle_plate_rejected
    """
    api.create_vehicle(create_vehicle_payload(plate="DUP-1", dual_control=True), ADMIN)
    resp = api.create_vehicle(
        create_vehicle_payload(plate="DUP-1", dual_control=False), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE, expected_status=409)


def test_invalid_enum_relationship_on_guardian_consent_rejected(api):
    """PRD §3.2: "recording the `guardian_name`, the `guardian_email`, and the
    `relationship`, which is either `PARENT` or `LEGAL_GUARDIAN`."
    PRD §2.11: "The well-formedness of the request body (`ERR_INVALID_REQUEST`,
    400)".

    Design: Corner/entities/invalid_enum_relationship_on_guardian_consent_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    stu = create_student(full_name="En Um", email="enum@x.com",
                         date_of_birth="2010-01-01")
    resp = api.create_guardian_consent(
        create_guardian_consent_payload(stu["id"], guardian_name="Un Cle",
                                        guardian_email="uncle@x.com",
                                        relationship="UNCLE"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_computed_duration_hours_ignores_client_input(api):
    """PRD §3.6: "A new lesson is created in `SCHEDULED` status with its
    `duration_hours` derived as the elapsed time from `start_at` to `end_at` in
    hours rounded to two decimals."

    Design: Corner/entities/computed_duration_hours_ignores_client_input
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_classroom_scheduling_context(package_overrides={
        "included_classroom_hours": 30, "included_online_hours": 0,
        "included_road_hours": 0, "enrollment_fee_cents": 0,
        "bundle_discount_cents": 0, "price_cents": 60000,
    })
    lesson = schedule_lesson(
        ctx["student"]["id"], ctx["enrollment"]["id"], "CLASSROOM",
        "2026-06-10T09:00:00.000Z", "2026-06-10T11:00:00.000Z",
        instructor_id=ctx["instructor"]["id"],
    )
    data = validate_success(api.get_lesson(lesson["id"], ADMIN))
    assert data["duration_hours"] == 2.0
    assert data["status"] == "SCHEDULED"


def test_list_students_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps how many items a single page
    returns; when omitted it defaults to 10, and a supplied value must be no
    less than 1 and no greater than 100."
    PRD §2.3: "Each list response carries the pagination bookkeeping inside the
    `meta` object of the envelope, specifically the `limit`, `offset`,
    `total_count`, and `has_more` fields."

    Design: Corner/entities/list_students_pagination_envelope
    """
    set_clock("2026-06-01T00:00:00.000Z")
    create_student(full_name="P One", email="p1@x.com", date_of_birth="1990-01-01")
    create_student(full_name="P Two", email="p2@x.com", date_of_birth="1991-01-01")
    resp = api.list_students(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_admin_wallet_adjustment_updates_balance(api):
    """PRD §3.10: "a `SchoolAdmin` may post a manual wallet adjustment directly,
    supplying a `student_id`, a signed `amount_cents`, a `reason` (here
    `ADMIN_ADJUSTMENT` ...) ...; posting the entry re-derives the student's
    `wallet_balance_cents`."

    Design: Corner/endpoints/admin_wallet_adjustment_updates_balance
    """
    set_clock("2026-06-01T00:00:00.000Z")
    stu = create_student(full_name="Wal Et", email="walet@x.com",
                        date_of_birth="1990-01-01")
    resp = api.create_wallet_entry(
        create_wallet_entry_payload(stu["id"], 2500, "ADMIN_ADJUSTMENT"), ADMIN
    )
    validate_success(resp, expected_status=201)
    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["wallet_balance_cents"] == 2500


def test_list_lessons_filtered_by_student(api):
    """PRD §2.5: "a caller can filter no-show strikes, wallet entries,
    certificates, enrollments, and lessons by the foreign keys that point back
    to a student, an enrollment, a lesson, an instructor, a vehicle, or a course
    package, which is how the portal reconstructs a learner's full history."

    Design: Corner/endpoints/list_lessons_filtered_by_student
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_classroom_scheduling_context(package_overrides={
        "included_classroom_hours": 30, "included_online_hours": 0,
        "included_road_hours": 0, "enrollment_fee_cents": 0,
        "bundle_discount_cents": 0, "price_cents": 60000,
    })
    schedule_lesson(
        ctx["student"]["id"], ctx["enrollment"]["id"], "CLASSROOM",
        "2026-06-10T09:00:00.000Z", "2026-06-10T11:00:00.000Z",
        instructor_id=ctx["instructor"]["id"],
    )
    resp = api.list_lessons(ADMIN, params={"student_id": ctx["student"]["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    for lesson in data:
        assert lesson["student_id"] == ctx["student"]["id"]
