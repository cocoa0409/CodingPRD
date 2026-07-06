"""CRUD, defaults, computed fields, listing, RBAC, OCC concurrency, and derived
field reconciliation.

Queue B: section=entities, section=errors, section=rbac,
section=cross_cutting_complexity_layers.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS, make_instructor_headers,
    setup_catalog, create_student_with_waiver, create_school, create_student,
    create_equipment, create_enrollment, create_session, book, set_clock,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]


# ============================================================================
# Queue B (Corner) — section: entities
# ============================================================================
def test_create_school_returns_system_fields(api):
    """PRD §3.1: "A new school opens with `storm_advisory_active` false, an
    `operating_status` of `OPEN`, an `open_session_count` of 0, and `version`
    1."

    Design: Corner/entities/create_school_returns_201_with_system_fields
    """
    res = api.create_school({"name": "New School"}, ADMIN)
    data = validate_success(res, 201)
    assert data["operating_status"] == "OPEN"
    assert data["storm_advisory_active"] is False
    assert data["version"] == 1
    assert data["open_session_count"] == 0


def test_get_nonexistent_school_returns_not_found(api):
    """PRD §2.8: "When a request targets a resource by its `{id}` in the path and
    no such resource exists, the response is `ERR_NOT_FOUND`."

    Design: Corner/entities/get_school_nonexistent_returns_not_found
    """
    validate_error(api.get_school("00000000-0000-4000-8000-000000000000", ADMIN),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_enrollment_missing_planned_sessions_validation(api):
    """PRD §3.4: "The request supplies the `school_id`, the `student_id`, the
    `course_level_id`, an optional `membership_id` (null for non-members), a
    `planned_sessions` count of at least 1, and a `party_size` of at least 1."
    PRD §3.1: "a malformed body ... [is] rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_enrollment_missing_required_field_returns_validation
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level = cat["school"], cat["level"]
    student = create_student_with_waiver(school["id"])
    res = api.create_enrollment(
        {"school_id": school["id"], "student_id": student["id"],
         "course_level_id": level["id"], "party_size": 1}, ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_level_requires_swim_test_defaults_true(api):
    """PRD §3.1: "a `requires_swim_test` flag that defaults to true."

    Design: Corner/entities/level_requires_swim_test_default_true
    """
    school = create_school(name="D School")
    course = get_success_data(api.create_course(
        {"school_id": school["id"], "discipline": "SURF", "title": "C", "kind": "LESSON"}, ADMIN))
    res = api.create_level(
        {"course_id": course["id"], "rank": 1, "name": "L1",
         "max_students_per_instructor": 4, "base_price_cents": 5000, "min_age": 0,
         "required_equipment_type": "NONE"}, ADMIN)
    data = validate_success(res, 201)
    assert data["requires_swim_test"] is True


def test_student_age_years_computed_from_clock(api):
    """PRD §3.3: "The student's `age_years` is not stored as a fixed value but
    computed as the number of whole years from `birthdate` to the current
    logical-clock date."

    Design: Corner/entities/student_age_years_computed_from_clock
    """
    set_clock("2026-03-01T00:00:00Z")
    school = create_school(name="Age School")
    res = api.create_student(
        {"school_id": school["id"], "full_name": "Kid", "birthdate": "2014-03-01"}, ADMIN)
    data = validate_success(res, 201)
    assert data["age_years"] == 12, \
        f"clock 2026-03-01 minus birthdate 2014-03-01 -> 12: got {data['age_years']}"


def test_list_schools_pagination_envelope(api):
    """PRD §2.3: "List responses surface `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_schools_pagination_envelope
    """
    create_school(name="S1")
    create_school(name="S2")
    data, meta = validate_paginated(api.list_schools(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["has_more"] is True
    assert meta["total_count"] >= 2


# ============================================================================
# Queue B (Corner) — section: errors
# ============================================================================
def test_rental_ends_before_starts_returns_validation(api):
    """PRD §3.1: "Simple shape violations on these inputs — a `rank` below 1, a
    negative price, a malformed body, a bad enum — are rejected with
    `ERR_VALIDATION`."

    Design: Corner/errors/booking_ends_before_start_returns_validation
    """
    school = create_school(name="Ev School")
    student = create_student(school["id"], full_name="Leo")
    equipment = create_equipment(school["id"], equipment_type="BOARD",
                                 asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
    res = api.create_rental(
        {"school_id": school["id"], "student_id": student["id"],
         "equipment_item_id": equipment["id"],
         "starts_at": "2026-03-02T12:00:00Z", "ends_at": "2026-03-02T09:00:00Z",
         "expected_equipment_version": equipment["version"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ============================================================================
# Queue B (Corner) — section: rbac
# ============================================================================
def test_student_cannot_schedule_session_forbidden(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to
    perform the requested operation (per the authorization column of the
    endpoint table in §4) is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/student_cannot_schedule_session_forbidden
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    student = create_student(school["id"], full_name="Mia")
    student_headers = {"X-User-ID": student["id"], "X-User-Role": "Student",
                       "Content-Type": "application/json"}
    res = api.create_session(
        {"school_id": school["id"], "course_level_id": level["id"],
         "instructor_id": inst["id"],
         "starts_at": "2026-03-10T09:00:00Z", "ends_at": "2026-03-10T10:00:00Z",
         "tide_window_start": "2026-03-10T08:00:00Z",
         "tide_window_end": "2026-03-10T12:00:00Z", "capacity": 4}, student_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request missing the `X-User-Role` header, or carrying a role
    string the system does not recognize, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    res = api.list_schools(TEST_USERS["unknown_role_headers"])
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_instructor_can_check_in_shared_op(api):
    """PRD §2.1: "an instructor may only start, complete, or check students into
    a session whose `instructor_id` equals their own `X-User-ID`."
    PRD §3.7: "Checking a student in, permitted to an administrator or the
    session's lead instructor, moves a `BOOKED` booking to `CHECKED_IN`."

    Design: Corner/rbac/instructor_can_check_in_shared_op
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    student = create_student_with_waiver(school["id"])
    enr = create_enrollment(school["id"], student["id"], level["id"],
                            planned_sessions=1, party_size=1)
    sess = create_session(school["id"], level["id"], inst["id"],
                        starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                        tide_window_start="2026-03-05T08:00:00Z",
                        tide_window_end="2026-03-05T12:00:00Z", capacity=4)
    bk = book(sess["id"], enr["id"], sess["version"])
    set_clock("2026-03-05T08:30:00Z")
    # Identity threading: the instructor must be the session's lead instructor.
    inst_headers = make_instructor_headers(inst["id"])
    get_success_data(api.start_session(sess["id"], inst_headers))
    data = validate_success(api.check_in_booking(bk["id"], inst_headers), 200)
    assert data["status"] == "CHECKED_IN"


# ============================================================================
# Queue B (Corner) — section: cross_cutting_complexity_layers
# ============================================================================
def test_stale_equipment_version_on_rental_create(api):
    """PRD §2.6: "When creating a rental agreement, the request must include
    `expected_equipment_version` carrying the client's last observed `version`
    of the target `EquipmentItem`. If the equipment item's current `version` no
    longer matches — because another rental create on the same item has advanced
    its version since the client last read it — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_equipment_version_on_rental_create
    """
    school = create_school(name="Oc School")
    student = create_student(school["id"], full_name="Leo")
    equipment = create_equipment(school["id"], equipment_type="BOARD",
                                 asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
    stale_version = equipment["version"]
    # First rental bumps the item version, making stale_version stale.
    get_success_data(api.create_rental(
        {"school_id": school["id"], "student_id": student["id"],
         "equipment_item_id": equipment["id"],
         "starts_at": "2026-03-02T09:00:00Z", "ends_at": "2026-03-02T11:00:00Z",
         "expected_equipment_version": stale_version}, ADMIN))
    res = api.create_rental(
        {"school_id": school["id"], "student_id": student["id"],
         "equipment_item_id": equipment["id"],
         "starts_at": "2026-03-03T09:00:00Z", "ends_at": "2026-03-03T11:00:00Z",
         "expected_equipment_version": stale_version}, ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_session_version_on_booking_create(api):
    """PRD §2.6: "When booking an enrollment into a session, the request must
    include `expected_session_version` carrying the client's last observed
    `version` of the target `Session`. If the session's current `version` no
    longer matches — because some other writer has booked a seat and advanced
    the session's version since the client last read it — the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_on_booking_create
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    sA = create_student_with_waiver(school["id"], full_name="A")
    sB = create_student_with_waiver(school["id"], full_name="B")
    eA = create_enrollment(school["id"], sA["id"], level["id"], planned_sessions=1, party_size=1)
    eB = create_enrollment(school["id"], sB["id"], level["id"], planned_sessions=1, party_size=1)
    sess = create_session(school["id"], level["id"], inst["id"],
                        starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                        tide_window_start="2026-03-10T08:00:00Z",
                        tide_window_end="2026-03-10T12:00:00Z", capacity=4)
    stale_version = sess["version"]
    # First booking advances the session version, making stale_version stale.
    book(sess["id"], eA["id"], stale_version)
    res = api.create_booking(
        {"session_id": sess["id"], "enrollment_id": eB["id"],
         "expected_session_version": stale_version}, ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_derived_equipment_status_rented_during_active_rental(api):
    """PRD §3.2: "An item's `status` is derived and starts at `AVAILABLE`; it
    reads `RENTED` while a rental agreement on it is in its active state."
    PRD §3.9: "On checkout the equipment item moves to `RENTED` and its
    `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/derived_equipment_status_rented_during_active_rental
    """
    set_clock("2026-03-03T00:00:00Z")
    school = create_school(name="Dr School")
    student = create_student(school["id"], full_name="Leo")
    equipment = create_equipment(school["id"], equipment_type="BOARD",
                                 asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
    rental = get_success_data(api.create_rental(
        {"school_id": school["id"], "student_id": student["id"],
         "equipment_item_id": equipment["id"],
         "starts_at": "2026-03-02T09:00:00Z", "ends_at": "2026-03-02T12:00:00Z",
         "expected_equipment_version": equipment["version"]}, ADMIN))
    get_success_data(api.checkout_rental(rental["id"], ADMIN))
    data = validate_success(api.get_equipment(equipment["id"], ADMIN), 200)
    assert data["status"] == "RENTED", \
        f"derived status reads RENTED during ACTIVE rental: got {data['status']}"
