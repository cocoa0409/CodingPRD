"""Validation gates: cross-entity preconditions, temporal overlap, enrollment
safety gates, storm closure, capacity, makeup credit, and the one PRD-stated
completion precedence (payment before attendance).

Queue A: cross_entity_state_dependency, resource_temporal_overlap, and the
state-vs-age priority pair. Queue B: section=validations, section=endpoints.

NOTE on a skipped design instance: the "storm-closed outranks waiver on
check-in" precedence is NOT translated into a test. PRD §2.10 makes the
per-workflow §3 ordering authoritative, and §3.7 lists the check-in gates with
the waiver requirement BEFORE the storm-closure requirement. A faithful PRD-only
implementer could therefore legitimately return ERR_WAIVER_REQUIRED first, so a
test asserting ERR_SCHOOL_STORM_CLOSED is not uniquely derivable from the PRD
(error-precedence silence pattern) and is omitted.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, TEST_USERS,
    setup_catalog, create_student_with_waiver, create_school, create_student,
    create_equipment, create_paid_enrollment, create_enrollment,
    create_session, book, attend_session, set_clock, create_membership,
    set_storm_advisory, set_maintenance, equipment_version,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]


# ============================================================================
# rule_id=cross_entity_state_dependency
# ============================================================================
class TestCheckInRequiresWaiverSigned:

    def test_checkin_blocked_when_waiver_revoked(self, api):
        """PRD §3.7: "that the student (reached through the booking's enrollment)
        have a `waiver_status` of `SIGNED` — otherwise `ERR_WAIVER_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_student_waiver_signed
        """
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student(school["id"])
        waiver = get_success_data(api.create_waiver(
            {"student_id": student["id"], "signed_by": "Mia",
             "expires_at": "2026-12-31T00:00:00Z"}, ADMIN))
        enr = create_enrollment(school["id"], student["id"], level["id"],
                                planned_sessions=1, party_size=1)
        sess = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                            tide_window_start="2026-03-05T08:00:00Z",
                            tide_window_end="2026-03-05T12:00:00Z", capacity=4)
        bk = book(sess["id"], enr["id"], sess["version"])
        set_clock("2026-03-05T08:30:00Z")
        get_success_data(api.start_session(sess["id"], ADMIN))
        get_success_data(api.revoke_waiver(waiver["id"], ADMIN))
        validate_error(api.check_in_booking(bk["id"], ADMIN),
                       ApiErrorId.ERR_WAIVER_REQUIRED.value)

    def test_checkin_succeeds_with_signed_waiver(self, api):
        """PRD §3.7: "Checking a student in, permitted to an administrator or the
        session's lead instructor, moves a `BOOKED` booking to `CHECKED_IN`."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_student_waiver_signed
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
        get_success_data(api.start_session(sess["id"], ADMIN))
        data = validate_success(api.check_in_booking(bk["id"], ADMIN), 200)
        assert data["status"] == "CHECKED_IN"


class TestCheckoutBlockedByMaintenance:

    def _reserved_rental_then_maintenance(self, api):
        set_clock("2026-03-03T00:00:00Z")
        school = create_school(name="Mt School")
        student = create_student(school["id"], full_name="Leo")
        equipment = create_equipment(school["id"], equipment_type="BOARD",
                                     asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
        rental = get_success_data(api.create_rental(
            {"school_id": school["id"], "student_id": student["id"],
             "equipment_item_id": equipment["id"],
             "starts_at": "2026-03-02T09:00:00Z", "ends_at": "2026-03-02T12:00:00Z",
             "expected_equipment_version": equipment["version"]}, ADMIN))
        v1 = equipment_version(equipment["id"])
        set_maintenance(equipment["id"], True, v1)
        return rental["id"]

    def test_checkout_blocked_when_item_in_maintenance(self, api):
        """PRD §3.9: "It requires the agreement to be `RESERVED`, the equipment
        item not to be in `MAINTENANCE` — a checkout against a maintenance item
        is rejected with `ERR_EQUIPMENT_IN_MAINTENANCE`."

        Design: Difficulty/cross_entity_state_dependency/rental_checkout_blocked_by_equipment_maintenance
        """
        rental_id = self._reserved_rental_then_maintenance(api)
        validate_error(api.checkout_rental(rental_id, ADMIN),
                       ApiErrorId.ERR_EQUIPMENT_IN_MAINTENANCE.value)

    def test_checkout_succeeds_when_item_available(self, api):
        """PRD §3.9: "Checking out a rental, permitted to an administrator or the
        owning student, moves it from `RESERVED` to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/rental_checkout_blocked_by_equipment_maintenance
        """
        set_clock("2026-03-03T00:00:00Z")
        school = create_school(name="Mt School")
        student = create_student(school["id"], full_name="Leo")
        equipment = create_equipment(school["id"], equipment_type="BOARD",
                                     asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
        rental = get_success_data(api.create_rental(
            {"school_id": school["id"], "student_id": student["id"],
             "equipment_item_id": equipment["id"],
             "starts_at": "2026-03-02T09:00:00Z", "ends_at": "2026-03-02T12:00:00Z",
             "expected_equipment_version": equipment["version"]}, ADMIN))
        data = validate_success(api.checkout_rental(rental["id"], ADMIN), 200)
        assert data["status"] == "ACTIVE"


# ============================================================================
# rule_id=resource_temporal_overlap
# ============================================================================
class TestTemporalOverlap:

    def test_instructor_double_booking_overlap_rejected(self, api):
        """PRD §3.6: "the new session interval must not overlap any other
        non-terminal session of the same instructor: the interval runs from
        `starts_at` up to but not including `ends_at` (half-open), so two
        sessions that merely touch at an endpoint do not conflict and no buffer
        is added, but any genuine overlap is rejected with
        `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/instructor_double_booking_half_open_touching_allowed
        """
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        create_session(school["id"], level["id"], inst["id"],
                      starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:30:00Z",
                      tide_window_start="2026-03-10T08:00:00Z",
                      tide_window_end="2026-03-10T12:00:00Z", capacity=4)
        res = api.create_session(
            {"school_id": school["id"], "course_level_id": level["id"],
             "instructor_id": inst["id"],
             "starts_at": "2026-03-10T10:00:00Z", "ends_at": "2026-03-10T11:00:00Z",
             "tide_window_start": "2026-03-10T08:00:00Z",
             "tide_window_end": "2026-03-10T12:00:00Z", "capacity": 4}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED.value)

    def test_instructor_touching_endpoint_allowed(self, api):
        """PRD §3.6: "two sessions that merely touch at an endpoint do not
        conflict and no buffer is added."

        Design: Difficulty/resource_temporal_overlap/instructor_double_booking_half_open_touching_allowed
        """
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        create_session(school["id"], level["id"], inst["id"],
                      starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:30:00Z",
                      tide_window_start="2026-03-10T08:00:00Z",
                      tide_window_end="2026-03-10T12:00:00Z", capacity=4)
        # A second session starting exactly at 10:30 only touches the first's end.
        res = api.create_session(
            {"school_id": school["id"], "course_level_id": level["id"],
             "instructor_id": inst["id"],
             "starts_at": "2026-03-10T10:30:00Z", "ends_at": "2026-03-10T11:30:00Z",
             "tide_window_start": "2026-03-10T08:00:00Z",
             "tide_window_end": "2026-03-10T12:00:00Z", "capacity": 4}, ADMIN)
        data = validate_success(res, 201)
        assert data["status"] == "SCHEDULED"

    def test_equipment_overlap_within_buffer_rejected(self, api):
        """PRD §3.9: "The window must not collide with any non-terminal agreement
        on the same item, where each existing agreement reserves a closed
        interval running from its `starts_at` through its `ends_at` plus a
        one-hour turnaround buffer; a collision against that buffered, closed
        interval is rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/equipment_rental_overlap_within_one_hour_buffer
        """
        school = create_school(name="Eq School")
        student = create_student(school["id"], full_name="Leo")
        equipment = create_equipment(school["id"], equipment_type="BOARD",
                                     asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
        get_success_data(api.create_rental(
            {"school_id": school["id"], "student_id": student["id"],
             "equipment_item_id": equipment["id"],
             "starts_at": "2026-03-02T09:00:00Z", "ends_at": "2026-03-02T12:00:00Z",
             "expected_equipment_version": equipment["version"]}, ADMIN))
        v1 = equipment_version(equipment["id"])
        # Existing ends 12:00 -> buffered through 13:00; 12:30-14:00 falls inside.
        res = api.create_rental(
            {"school_id": school["id"], "student_id": student["id"],
             "equipment_item_id": equipment["id"],
             "starts_at": "2026-03-02T12:30:00Z", "ends_at": "2026-03-02T14:00:00Z",
             "expected_equipment_version": v1}, ADMIN)
        validate_error(res, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value)

    def test_equipment_rental_clear_of_buffer_allowed(self, api):
        """PRD §3.9: "The window must not collide with any non-terminal agreement
        on the same item, where each existing agreement reserves a closed
        interval running from its `starts_at` through its `ends_at` plus a
        one-hour turnaround buffer; a collision against that buffered, closed
        interval is rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/equipment_rental_overlap_within_one_hour_buffer
        """
        school = create_school(name="Eq School")
        student = create_student(school["id"], full_name="Leo")
        equipment = create_equipment(school["id"], equipment_type="BOARD",
                                     asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
        get_success_data(api.create_rental(
            {"school_id": school["id"], "student_id": student["id"],
             "equipment_item_id": equipment["id"],
             "starts_at": "2026-03-02T09:00:00Z", "ends_at": "2026-03-02T12:00:00Z",
             "expected_equipment_version": equipment["version"]}, ADMIN))
        v1 = equipment_version(equipment["id"])
        # Existing ends 12:00 -> buffered through 13:00; a window starting 15:00 is
        # well clear of the buffered, closed interval and must be accepted.
        res = api.create_rental(
            {"school_id": school["id"], "student_id": student["id"],
             "equipment_item_id": equipment["id"],
             "starts_at": "2026-03-02T15:00:00Z", "ends_at": "2026-03-02T16:00:00Z",
             "expected_equipment_version": v1}, ADMIN)
        data = validate_success(res, 201)
        assert data["status"] == "RESERVED"


# ============================================================================
# rule_id=priority_pair_validation_conflict (state outranks age via re-complete)
# ============================================================================
class TestInvalidStateOutranksAge:

    def _completed_enrollment(self, api):
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student_with_waiver(school["id"])
        enr = create_paid_enrollment(school["id"], student["id"], level["id"],
                                     planned_sessions=1, party_size=1)
        sess = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                            tide_window_start="2026-03-05T08:00:00Z",
                            tide_window_end="2026-03-05T12:00:00Z", capacity=4)
        bk = book(sess["id"], enr["id"], sess["version"])
        attend_session(sess["id"], [bk["id"]], "2026-03-05T08:30:00Z")
        get_success_data(api.complete_enrollment(enr["id"], ADMIN))
        return enr["id"]

    def test_recomplete_completed_enrollment_invalid_state(self, api):
        """PRD §2.10: "Only after these do state-transition legality
        (`ERR_INVALID_STATE`) and the domain-specific business rules — storm
        closure, waivers, age, swim test, certification, prerequisites, tide
        windows, scheduling overlaps, capacity, makeup credits, maintenance,
        payment, and attendance — apply."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_age_on_enroll_completion_vs_creation
        """
        enr_id = self._completed_enrollment(api)
        validate_error(api.complete_enrollment(enr_id, ADMIN),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_first_completion_succeeds(self, api):
        """PRD §3.5: "Completing an enrollment is restricted to an administrator.
        It requires that `progress_status` be `ACTIVE`, that `payment_status`
        already be `PAID` (a cross-dimension gate — an unpaid enrollment cannot
        complete), and that the enrollment's `attended_count` be at least its
        `planned_sessions`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_age_on_enroll_completion_vs_creation
        """
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student_with_waiver(school["id"])
        enr = create_paid_enrollment(school["id"], student["id"], level["id"],
                                     planned_sessions=1, party_size=1)
        sess = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                            tide_window_start="2026-03-05T08:00:00Z",
                            tide_window_end="2026-03-05T12:00:00Z", capacity=4)
        bk = book(sess["id"], enr["id"], sess["version"])
        attend_session(sess["id"], [bk["id"]], "2026-03-05T08:30:00Z")
        data = validate_success(api.complete_enrollment(enr["id"], ADMIN), 200)
        assert data["progress_status"] == "COMPLETED"


# ============================================================================
# Queue B (Corner) — section: validations
# ============================================================================
def test_enroll_below_min_age_rejected(api):
    """PRD §3.4: "The student's `age_years` must be at least the level's
    `min_age`, or the enrollment is rejected with
    `ERR_AGE_REQUIREMENT_NOT_MET`."

    Design: Corner/validations/enroll_below_min_age_returns_age_error
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = setup_catalog(level_overrides={
        "max_students_per_instructor": 4, "min_age": 12,
        "requires_swim_test": False, "required_equipment_type": "NONE"})
    school, level = cat["school"], cat["level"]
    student = create_student(school["id"], full_name="Kid", birthdate="2015-01-01")
    get_success_data(api.create_waiver(
        {"student_id": student["id"], "signed_by": "Guardian", "is_guardian": True,
         "expires_at": "2026-12-31T00:00:00Z"}, ADMIN))
    res = api.create_enrollment(
        {"school_id": school["id"], "student_id": student["id"],
         "course_level_id": level["id"], "planned_sessions": 1, "party_size": 1}, ADMIN)
    validate_error(res, ApiErrorId.ERR_AGE_REQUIREMENT_NOT_MET.value)


def test_enroll_without_swim_test_rejected(api):
    """PRD §3.4: "If the level's `requires_swim_test` is true, the student's
    `swim_test_status` must be `PASSED`, or the enrollment is rejected with
    `ERR_SWIM_TEST_REQUIRED`."

    Design: Corner/validations/enroll_without_swim_test_returns_swim_error
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = setup_catalog(level_overrides={
        "max_students_per_instructor": 4, "min_age": 0,
        "requires_swim_test": True, "required_equipment_type": "NONE"})
    school, level = cat["school"], cat["level"]
    student = create_student_with_waiver(school["id"])  # swim_test_status UNTESTED
    res = api.create_enrollment(
        {"school_id": school["id"], "student_id": student["id"],
         "course_level_id": level["id"], "planned_sessions": 1, "party_size": 1}, ADMIN)
    validate_error(res, ApiErrorId.ERR_SWIM_TEST_REQUIRED.value)


def test_prerequisite_not_met_on_rank_two(api):
    """PRD §3.4: "if the target level's `rank` is greater than 1, the student
    must already hold a `COMPLETED` enrollment at the rank-1 level of the same
    course, or the enrollment is rejected with `ERR_PREREQUISITE_NOT_MET`."

    Design: Corner/validations/prerequisite_not_met_on_rank_two_enroll
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = setup_catalog(level_overrides={
        "max_students_per_instructor": 4, "rank": 1, "min_age": 0,
        "requires_swim_test": False, "required_equipment_type": "NONE"})
    school, course, level1 = cat["school"], cat["course"], cat["level"]
    level2 = get_success_data(api.create_level(
        {"course_id": course["id"], "rank": 2, "name": "L2",
         "max_students_per_instructor": 4, "base_price_cents": 6000, "min_age": 0,
         "requires_swim_test": False, "required_equipment_type": "NONE"}, ADMIN))
    student = create_student_with_waiver(school["id"])
    res = api.create_enrollment(
        {"school_id": school["id"], "student_id": student["id"],
         "course_level_id": level2["id"], "planned_sessions": 1, "party_size": 1}, ADMIN)
    validate_error(res, ApiErrorId.ERR_PREREQUISITE_NOT_MET.value)


def test_tide_window_invalid_on_session_create(api):
    """PRD §3.6: "The tide window must fully contain the session interval,
    meaning `tide_window_start` is at or before `starts_at` and `ends_at` is at
    or before `tide_window_end`; otherwise the request is rejected with
    `ERR_TIDE_WINDOW_INVALID`."

    Design: Corner/validations/tide_window_invalid_on_session_create
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    res = api.create_session(
        {"school_id": school["id"], "course_level_id": level["id"],
         "instructor_id": inst["id"],
         "starts_at": "2026-03-10T09:00:00Z", "ends_at": "2026-03-10T13:00:00Z",
         "tide_window_start": "2026-03-10T08:00:00Z",
         "tide_window_end": "2026-03-10T12:00:00Z", "capacity": 4}, ADMIN)
    validate_error(res, ApiErrorId.ERR_TIDE_WINDOW_INVALID.value)


def test_instructor_not_certified_for_discipline(api):
    """PRD §3.6: "The lead instructor must be certified for the discipline of
    the level's course — that discipline must appear in the instructor's
    `certified_disciplines` — or the request is rejected with
    `ERR_INSTRUCTOR_NOT_CERTIFIED`."

    Design: Corner/validations/instructor_not_certified_for_discipline
    """
    cat = setup_catalog(
        course_overrides={"discipline": "SURF", "title": "C", "kind": "LESSON"},
        level_overrides={"max_students_per_instructor": 4},
        instructor_overrides={"certified_disciplines": ["KAYAK"]})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    res = api.create_session(
        {"school_id": school["id"], "course_level_id": level["id"],
         "instructor_id": inst["id"],
         "starts_at": "2026-03-10T09:00:00Z", "ends_at": "2026-03-10T10:00:00Z",
         "tide_window_start": "2026-03-10T08:00:00Z",
         "tide_window_end": "2026-03-10T12:00:00Z", "capacity": 4}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INSTRUCTOR_NOT_CERTIFIED.value)


def test_session_full_on_booking_over_capacity(api):
    """PRD §3.7: "The session must have room: its `enrolled_count` (the number
    of its bookings in `BOOKED`, `CHECKED_IN`, or `ATTENDED`) must be strictly
    less than its `capacity`, or the booking is rejected with
    `ERR_SESSION_FULL`."

    Design: Corner/validations/session_full_on_booking_over_capacity
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
                        tide_window_end="2026-03-10T12:00:00Z", capacity=1)
    book(sess["id"], eA["id"], sess["version"])
    v1 = get_success_data(api.get_session(sess["id"], ADMIN))["version"]
    res = api.create_booking(
        {"session_id": sess["id"], "enrollment_id": eB["id"],
         "expected_session_version": v1}, ADMIN)
    validate_error(res, ApiErrorId.ERR_SESSION_FULL.value)


def test_equipment_type_mismatch_on_session_linked_rental(api):
    """PRD §3.9: "when a `session_id` is supplied, the equipment item's
    `equipment_type` must equal the linked level's `required_equipment_type`, or
    the create is rejected with `ERR_EQUIPMENT_TYPE_MISMATCH`."

    Design: Corner/validations/equipment_type_mismatch_on_session_linked_rental
    """
    cat = setup_catalog(level_overrides={
        "max_students_per_instructor": 4, "required_equipment_type": "BOARD"})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    student = create_student(school["id"], full_name="Leo")
    equipment = create_equipment(school["id"], equipment_type="KAYAK",
                                 asset_tag="K-1", hourly_rate_cents=1000, deposit_cents=0)
    sess = create_session(school["id"], level["id"], inst["id"],
                        starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                        tide_window_start="2026-03-10T08:00:00Z",
                        tide_window_end="2026-03-10T12:00:00Z", capacity=4)
    res = api.create_rental(
        {"school_id": school["id"], "student_id": student["id"],
         "equipment_item_id": equipment["id"],
         "starts_at": "2026-03-10T08:00:00Z", "ends_at": "2026-03-10T11:00:00Z",
         "expected_equipment_version": equipment["version"], "session_id": sess["id"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_EQUIPMENT_TYPE_MISMATCH.value)


def test_complete_unpaid_returns_payment_required_before_attendance(api):
    """PRD §3.5: "The payment gate, when unmet, is reported as
    `ERR_PAYMENT_REQUIRED`; the attendance gate, when unmet, is reported as
    `ERR_ATTENDANCE_INCOMPLETE`; the payment requirement is evaluated before the
    attendance requirement."

    Design: Corner/validations/complete_enrollment_unpaid_returns_payment_required
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level = cat["school"], cat["level"]
    student = create_student_with_waiver(school["id"])
    # ACTIVE, UNPAID, attended_count 0 < planned 1 -> both gates would fail.
    enr = create_enrollment(school["id"], student["id"], level["id"],
                            planned_sessions=1, party_size=1)
    validate_error(api.complete_enrollment(enr["id"], ADMIN),
                   ApiErrorId.ERR_PAYMENT_REQUIRED.value)


# ============================================================================
# Queue B (Corner) — section: endpoints
# ============================================================================
def test_storm_advisory_sets_operating_status_closed(api):
    """PRD §3.1: "The supplied `active` boolean is written to
    `storm_advisory_active`; `operating_status` becomes `STORM_CLOSED` when
    `active` is true and `OPEN` when it is false; and the school's `version` is
    incremented by 1."

    Design: Corner/endpoints/storm_advisory_sets_operating_status_closed
    """
    school = create_school(name="Sa School")
    data = validate_success(api.set_storm_advisory(
        school["id"], {"active": True, "expected_school_version": school["version"]}, ADMIN), 200)
    assert data["operating_status"] == "STORM_CLOSED"
    assert data["version"] == 2, f"version bumps 1->2: got {data['version']}"


def test_session_create_blocked_while_storm_closed(api):
    """PRD §3.6: "The school must not be storm-closed: if `operating_status` is
    `STORM_CLOSED`, scheduling is rejected with `ERR_SCHOOL_STORM_CLOSED`."

    Design: Corner/endpoints/session_create_blocked_while_storm_closed
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    set_storm_advisory(school["id"], True, school["version"])
    res = api.create_session(
        {"school_id": school["id"], "course_level_id": level["id"],
         "instructor_id": inst["id"],
         "starts_at": "2026-03-10T09:00:00Z", "ends_at": "2026-03-10T10:00:00Z",
         "tide_window_start": "2026-03-10T08:00:00Z",
         "tide_window_end": "2026-03-10T12:00:00Z", "capacity": 4}, ADMIN)
    validate_error(res, ApiErrorId.ERR_SCHOOL_STORM_CLOSED.value)


def test_booking_no_makeup_credit_rejected(api):
    """PRD §3.7: "When `use_makeup_credit` is true, the owning enrollment's
    membership must have a `makeup_credit_balance` of at least 1, or the booking
    is rejected with `ERR_NO_MAKEUP_CREDIT`."

    Design: Corner/endpoints/booking_no_makeup_credit_returns_error
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    student = create_student_with_waiver(school["id"])
    mem = create_membership(student["id"], tier="BASIC")  # makeup_credit_balance 0
    enr = create_enrollment(school["id"], student["id"], level["id"],
                            membership_id=mem["id"], planned_sessions=1, party_size=1)
    sess = create_session(school["id"], level["id"], inst["id"],
                        starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                        tide_window_start="2026-03-10T08:00:00Z",
                        tide_window_end="2026-03-10T12:00:00Z", capacity=4)
    res = api.create_booking(
        {"session_id": sess["id"], "enrollment_id": enr["id"],
         "expected_session_version": sess["version"], "use_makeup_credit": True}, ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_MAKEUP_CREDIT.value)
