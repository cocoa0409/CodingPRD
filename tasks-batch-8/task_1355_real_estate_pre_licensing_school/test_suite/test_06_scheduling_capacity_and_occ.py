"""Schedule-conflict rules, capacity boundaries, seat conservation, and OCC.

Covers the three distinct overlap semantics (student half-open, instructor
rest-gap buffer, proctor day-granularity), the capacity full boundary, the seat
conservation invariant across enroll/withdraw, and the optimistic-concurrency
guards on offering update, grant creation, and report amendments.
"""
from test_helpers import (
    ApiErrorId,
    assert_seat_invariant,
    create_active_course,
    create_credentialed_instructor,
    create_grant,
    create_licensed_school,
    create_offering,
    create_published_offering,
    create_proctor,
    create_report,
    create_student,
    enroll,
    enroll_with_seat_time,
    get_offering,
    get_refund_for_enrollment,
    get_success_data,
    schedule_attempt,
    setup_publishable_school,
    validate_error,
    validate_paginated,
    withdraw_payload,
)
from test_helpers.fixtures import COMPLIANCE, COMMISSION, DIRECTOR, REGISTRAR
from test_helpers import api_client


def _version_of_course(api, course_id):
    return get_success_data(api.get_course(course_id, COMPLIANCE))["version"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/student_overlap_half_open_adjacency_allowed
# ---------------------------------------------------------------------------

class TestStudentOverlapHalfOpenAdjacency:
    def _three_offerings(self, api):
        """A 09-01..09-10, B 09-10..09-20, C 09-09..09-15; distinct instructors
        so the rest-gap rule does not interfere."""
        school = create_licensed_school()
        course = create_active_course(school["id"])
        ins_a = create_credentialed_instructor(school["id"])
        ins_b = create_credentialed_instructor(school["id"])
        ins_c = create_credentialed_instructor(school["id"])
        off_a = create_published_offering(course["id"], ins_a["id"],
                                          start_date="2026-09-01",
                                          end_date="2026-09-10", capacity=5)
        off_b = create_published_offering(course["id"], ins_b["id"],
                                          start_date="2026-09-10",
                                          end_date="2026-09-20", capacity=5)
        off_c = create_published_offering(course["id"], ins_c["id"],
                                          start_date="2026-09-09",
                                          end_date="2026-09-15", capacity=5,
                                          delivery_mode="DISTANCE")
        student = create_student(school["id"])
        return student, off_a, off_b, off_c

    def test_adjacent_windows_allowed(self, api):
        """PRD §3.5: "Windows that merely touch are allowed — a new offering
        starting the day an existing one ends, or ending the day the existing
        one starts, is adjacent rather than overlapping".

        Design: Difficulty/resource_temporal_overlap/student_overlap_half_open_adjacency_allowed
        """
        student, off_a, off_b, _off_c = self._three_offerings(api)
        ea = get_success_data(api.create_enrollment(
            {"offering_id": off_a["id"], "student_id": student["id"]}, REGISTRAR))
        eb = get_success_data(api.create_enrollment(
            {"offering_id": off_b["id"], "student_id": student["id"]}, REGISTRAR))
        assert ea["academic_status"] == "ENROLLED"
        assert eb["academic_status"] == "ENROLLED", \
            "B.start == A.end is adjacency under half-open semantics"

    def test_strict_overlap_rejected(self, api):
        """PRD §3.5: "any strict overlap is rejected with
        `ERR_STUDENT_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/student_overlap_half_open_adjacency_allowed
        """
        student, off_a, off_b, off_c = self._three_offerings(api)
        get_success_data(api.create_enrollment(
            {"offering_id": off_a["id"], "student_id": student["id"]}, REGISTRAR))
        get_success_data(api.create_enrollment(
            {"offering_id": off_b["id"], "student_id": student["id"]}, REGISTRAR))
        resp = api.create_enrollment(
            {"offering_id": off_c["id"], "student_id": student["id"]}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_STUDENT_SCHEDULE_CONFLICT)
        data, _meta = validate_paginated(api.list_enrollments(REGISTRAR))
        mine = [e for e in data if e["student_id"] == student["id"]]
        assert len(mine) == 2, "student holds exactly 2 enrollments"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/instructor_rest_gap_buffer
# ---------------------------------------------------------------------------

class TestInstructorRestGapBuffer:
    def _instructor_with_offering(self, api):
        school = create_licensed_school()
        course = create_active_course(school["id"])
        ins = create_credentialed_instructor(school["id"])
        off_a = create_offering(course["id"], ins["id"],
                                start_date="2026-09-01", end_date="2026-09-10")
        return school, course, ins, off_a

    def test_zero_rest_days_conflicts(self, api):
        """PRD §3.4: "Concretely, an existing offering ending 2026-09-10 blocks
        a new start on 2026-09-11 but permits 2026-09-12."

        Design: Difficulty/resource_temporal_overlap/instructor_rest_gap_buffer
        """
        _school, course, ins, _off_a = self._instructor_with_offering(api)
        resp = api.create_offering(
            {"course_id": course["id"], "instructor_id": ins["id"],
             "state_code": "TX", "start_date": "2026-09-11", "end_date": "2026-09-15",
             "capacity": 2, "delivery_mode": "IN_PERSON"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_SCHEDULE_CONFLICT)

    def test_one_full_rest_day_allowed(self, api):
        """PRD §3.4: "A conflict exists unless the new `start_date` is at least
        two days after the existing offering's `end_date`... otherwise the create
        is rejected with `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`. Concretely, an
        existing offering ending 2026-09-10 blocks a new start on 2026-09-11 but
        permits 2026-09-12."

        Design: Difficulty/resource_temporal_overlap/instructor_rest_gap_buffer
        """
        _school, course, ins, _off_a = self._instructor_with_offering(api)
        created = get_success_data(api.create_offering(
            {"course_id": course["id"], "instructor_id": ins["id"],
             "state_code": "TX", "start_date": "2026-09-12", "end_date": "2026-09-20",
             "capacity": 2, "delivery_mode": "IN_PERSON"}, DIRECTOR))
        assert created["status"] == "DRAFT", "2026-09-11 is the rest day"
        data, _meta = validate_paginated(api.list_offerings(REGISTRAR))
        mine = [o for o in data if o["instructor_id"] == ins["id"]]
        assert len(mine) == 2


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/proctor_same_day_conflict
# ---------------------------------------------------------------------------

class TestProctorSameDayConflict:
    def _two_seat_time_met(self, api):
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60},
                                       offering_overrides={"capacity": 3})
        proctor = create_proctor(env["school"]["id"])
        _sa, ea = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        _sb, eb = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        return env, proctor, ea, eb

    def test_same_calendar_date_conflicts_regardless_of_clock_time(self, api):
        """PRD §3.7: "the proctor must not already hold another attempt in
        `SCHEDULED` or `PROCTORED` on the same calendar date
        (`ERR_PROCTOR_SCHEDULE_CONFLICT`)".

        Design: Difficulty/resource_temporal_overlap/proctor_same_day_conflict
        """
        _env, proctor, ea, eb = self._two_seat_time_met(api)
        schedule_attempt(ea["id"], proctor["id"], scheduled_at="2026-09-15T10:00:00Z")
        resp = api.create_exam_attempt(
            eb["id"], {"scheduled_at": "2026-09-15T18:00:00Z",
                       "proctor_instructor_id": proctor["id"]}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_PROCTOR_SCHEDULE_CONFLICT)

    def test_next_calendar_date_is_free(self, api):
        """PRD §3.7: "the proctor must not already hold another attempt in
        `SCHEDULED` or `PROCTORED` on the same calendar date
        (`ERR_PROCTOR_SCHEDULE_CONFLICT`)" — day granularity means the next
        date is free.

        Design: Difficulty/resource_temporal_overlap/proctor_same_day_conflict
        """
        _env, proctor, ea, eb = self._two_seat_time_met(api)
        schedule_attempt(ea["id"], proctor["id"], scheduled_at="2026-09-15T10:00:00Z")
        resp = api.create_exam_attempt(
            eb["id"], {"scheduled_at": "2026-09-15T18:00:00Z",
                       "proctor_instructor_id": proctor["id"]}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_PROCTOR_SCHEDULE_CONFLICT)
        ok = get_success_data(api.create_exam_attempt(
            eb["id"], {"scheduled_at": "2026-09-16T10:00:00Z",
                       "proctor_instructor_id": proctor["id"]}, REGISTRAR))
        assert ok["attempt_number"] == 1
        assert ok["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/capacity_full_boundary
# ---------------------------------------------------------------------------

class TestCapacityFullBoundary:
    def test_first_enrollment_consumes_last_seat(self, api):
        """PRD §3.5: "Enrollment requires the offering to be `PUBLISHED`
        (`ERR_OFFERING_NOT_OPEN`) with at least one seat free —
        `seats_available` at least 1, else `ERR_OFFERING_FULL`".

        Design: Difficulty/boundary_precision_check/capacity_full_boundary
        """
        env = setup_publishable_school(capacity=1)
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        assert enr["academic_status"] == "ENROLLED"
        offering = get_offering(env["offering"]["id"])
        assert offering["seats_available"] == 0
        assert offering["enrolled_count"] == 1

    def test_enrollment_at_zero_seats_rejected(self, api):
        """PRD §3.5: "with at least one seat free — `seats_available` at least 1,
        else `ERR_OFFERING_FULL`".

        Design: Difficulty/boundary_precision_check/capacity_full_boundary
        """
        env = setup_publishable_school(capacity=1)
        enroll(env["offering"]["id"], env["school"]["id"])
        sb = create_student(env["school"]["id"])
        resp = api.create_enrollment(
            {"offering_id": env["offering"]["id"], "student_id": sb["id"]}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_OFFERING_FULL)
        offering = get_offering(env["offering"]["id"])
        assert offering["enrolled_count"] == 1
        assert offering["seats_available"] == 0


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/seat_conservation_cycle
# ---------------------------------------------------------------------------

class TestSeatConservationCycle:
    def test_seat_invariant_holds_across_enroll_and_withdraw(self, api):
        """PRD §3.5: "`enrolled_count` is the count of the offering's enrollments
        whose `academic_status` is not one of `WITHDRAWN`, `FAILED`, or
        `EXPIRED`, and `seats_available` is `capacity` minus `enrolled_count`, so
        capacity always equals enrolled seats plus available seats."

        Design: Difficulty/compensating_invariant/seat_conservation_cycle
        """
        env = setup_publishable_school(capacity=2)
        _sa, ea = enroll(env["offering"]["id"], env["school"]["id"])
        offering = get_offering(env["offering"]["id"])
        assert (offering["enrolled_count"], offering["seats_available"]) == (1, 1)
        assert_seat_invariant(offering)
        _sb, eb = enroll(env["offering"]["id"], env["school"]["id"])
        offering = get_offering(env["offering"]["id"])
        assert (offering["enrolled_count"], offering["seats_available"]) == (2, 0)
        assert_seat_invariant(offering)
        get_success_data(api.withdraw_enrollment(ea["id"], withdraw_payload("VOLUNTARY"),
                                                 REGISTRAR))
        offering = get_offering(env["offering"]["id"])
        assert (offering["enrolled_count"], offering["seats_available"]) == (1, 1)
        assert_seat_invariant(offering)

    def test_unpaid_withdrawal_voids_payment_without_refund_artifact(self, api):
        """PRD §3.5: "If `payment_status` is still `PENDING`, it flips to
        `VOIDED` and no refund request is created."

        Design: Difficulty/compensating_invariant/seat_conservation_cycle
        """
        env = setup_publishable_school(capacity=2)
        _sa, ea = enroll(env["offering"]["id"], env["school"]["id"])
        enroll(env["offering"]["id"], env["school"]["id"])
        withdrawn = get_success_data(api.withdraw_enrollment(
            ea["id"], withdraw_payload("VOLUNTARY"), REGISTRAR))
        assert withdrawn["payment_status"] == "VOIDED", "PENDING never captured money"
        assert get_refund_for_enrollment(ea["id"]) is None, "no refund artifact"
        offering = get_offering(env["offering"]["id"])
        assert_seat_invariant(offering)


# ---------------------------------------------------------------------------
# Corner/cross_cutting/cn_occ_offering_stale_version
# ---------------------------------------------------------------------------

class TestOccOfferingStaleVersion:
    def _draft_offering(self, api):
        school = create_licensed_school()
        course = create_active_course(school["id"])
        ins = create_credentialed_instructor(school["id"])
        offering = create_offering(course["id"], ins["id"])
        return offering

    def test_current_version_update_succeeds_and_increments(self, api):
        """PRD §2.5: "The offering update capability (`PUT /offerings/{id}`)
        requires a non-optional `expected_offering_version` field carrying the
        client's last observed `version` of the offering... A successful update
        or amendment-creation under these guards increments the guarded parent's
        `version` by 1."

        Design: Corner/cross_cutting/cn_occ_offering_stale_version
        """
        offering = self._draft_offering(api)
        updated = get_success_data(api.update_offering(
            offering["id"],
            {"capacity": 3, "expected_offering_version": offering["version"]},
            DIRECTOR))
        assert updated["version"] == offering["version"] + 1
        assert updated["capacity"] == 3

    def test_stale_version_rejected_and_changes_nothing(self, api):
        """PRD §2.5: "if another writer has advanced the offering's version since
        the client last read it, the update is rejected with
        `ERR_STALE_OFFERING_VERSION` (HTTP 412) rather than silently overwriting
        that change."

        Design: Corner/cross_cutting/cn_occ_offering_stale_version
        """
        offering = self._draft_offering(api)
        get_success_data(api.update_offering(
            offering["id"],
            {"capacity": 3, "expected_offering_version": offering["version"]},
            DIRECTOR))
        resp = api.update_offering(
            offering["id"],
            {"capacity": 4, "expected_offering_version": offering["version"]},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_OFFERING_VERSION)
        assert get_offering(offering["id"])["capacity"] == 3


# ---------------------------------------------------------------------------
# Corner/cross_cutting/cn_occ_grant_supersede_and_stale
# ---------------------------------------------------------------------------

class TestOccGrantSupersedeAndStale:
    def _course_with_grant(self, api):
        school = create_licensed_school()
        course = create_active_course(school["id"])
        grant = create_grant(course["id"], "TX", "NM", course["version"])
        return course, grant

    def test_stale_course_version_rejected(self, api):
        """PRD §2.5: "Creating an equivalency grant requires
        `expected_course_version` matching the course's current `version`,
        because grant creation supersedes existing grants and the client must
        have observed the latest grant state; a mismatch is rejected with
        `ERR_STALE_COURSE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/cn_occ_grant_supersede_and_stale
        """
        course, _g1 = self._course_with_grant(api)
        resp = api.create_equivalency_grant(
            {"course_id": course["id"], "home_state_code": "TX",
             "recognized_state_code": "NM",
             "expected_course_version": course["version"]},
            COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_STALE_COURSE_VERSION)

    def test_fresh_version_supersedes_existing_grant(self, api):
        """PRD §3.2: "Creating a grant for a course-home-recognized triple that
        already has a grant in `ACTIVE` or `SUSPENDED` supersedes it — the older
        grant moves to `SUPERSEDED`. New grants stand `ACTIVE`." and §2.5: "a
        successful creation increments the course's `version` by 1."

        Design: Corner/cross_cutting/cn_occ_grant_supersede_and_stale
        """
        course, g1 = self._course_with_grant(api)
        fresh_version = _version_of_course(api, course["id"])
        g2 = get_success_data(api.create_equivalency_grant(
            {"course_id": course["id"], "home_state_code": "TX",
             "recognized_state_code": "NM",
             "expected_course_version": fresh_version},
            COMPLIANCE))
        assert g2["status"] == "ACTIVE"
        assert get_success_data(api.get_equivalency_grant(g1["id"], COMPLIANCE))["status"] \
            == "SUPERSEDED"
        assert _version_of_course(api, course["id"]) == fresh_version + 1


# ---------------------------------------------------------------------------
# Corner/cross_cutting/cn_occ_report_amendment_stale_version
# ---------------------------------------------------------------------------

class TestOccReportAmendmentStaleVersion:
    def _acknowledged_report(self, api):
        school = create_licensed_school()
        report = create_report(school["id"], "2026-09-01", "2026-09-30")
        get_success_data(api.submit_credit_report(report["id"], COMPLIANCE))
        return get_success_data(api.acknowledge_credit_report(report["id"], COMMISSION))

    def test_amendment_with_current_version_succeeds(self, api):
        """PRD §3.8: "The new report is a `DRAFT` whose `amendment_of_id` points
        at the parent".

        Design: Corner/cross_cutting/cn_occ_report_amendment_stale_version
        """
        report = self._acknowledged_report(api)
        amendment = get_success_data(api.create_credit_report_amendment(
            report["id"],
            {"reason": "correction batch 1",
             "expected_credit_report_version": report["version"]},
            COMPLIANCE))
        assert amendment["status"] == "DRAFT"
        assert amendment["amendment_of_id"] == report["id"]

    def test_amendment_with_stale_version_rejected(self, api):
        """PRD §2.5: "Creating an amendment against an acknowledged credit report
        requires `expected_credit_report_version` matching that report's current
        `version`; a mismatch is rejected with `ERR_STALE_CREDIT_REPORT_VERSION`
        (HTTP 412)." and §3.8: "a successful amendment increments the parent
        report's `version` by 1."

        Design: Corner/cross_cutting/cn_occ_report_amendment_stale_version
        """
        report = self._acknowledged_report(api)
        get_success_data(api.create_credit_report_amendment(
            report["id"],
            {"reason": "correction batch 1",
             "expected_credit_report_version": report["version"]},
            COMPLIANCE))
        resp = api.create_credit_report_amendment(
            report["id"],
            {"reason": "correction batch 2",
             "expected_credit_report_version": report["version"]},
            COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_STALE_CREDIT_REPORT_VERSION)
