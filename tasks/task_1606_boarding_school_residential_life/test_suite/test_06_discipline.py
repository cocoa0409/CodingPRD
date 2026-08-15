"""Discipline workflow: dual ledgers, standing thresholds, hearings, appeals."""
import pytest

from test_helpers import (
    TEST_USERS, api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_discipline_case, assert_student, assert_standing_matches_points,
    create_discipline_case_payload,
    make_dean_headers, make_student_headers,
    make_parent, make_student, make_dean, get_student,
    report_case, sanction_minor_case, sanction_major_case,
    setup_student_with_sanction, set_clock,
)


class TestDualPointLedgers:
    def _setup_sanctioned_plus_reported(self):
        """Student with one SANCTIONED case at 6 and one REPORTED case at 5."""
        parent = make_parent()
        student = make_student(parent["id"], grade=9, gender="MALE",
                               legal_name="Stu C", sleep_schedule=2, cleanliness=4,
                               noise_tolerance=3, guests_comfort=5)
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case1 = report_case(student["id"], dean1["id"], category="MINOR",
                            description="Tardy to check-in", points_proposed=6)
        sanction_minor_case(case1["id"], dean1["id"], dean2["id"], 6,
                            sanction_type="WARNING")
        case2 = report_case(student["id"], dean1["id"], category="MINOR",
                            description="Candle in room", points_proposed=5)
        return student, dean1, case1, case2

    def test_official_and_provisional_totals_diverge_while_case_pending(self, api):
        """PRD §2.8: "The official `demerit_points` sums three sources: points
        assessed by night checks, points assessed by curfew-late sign-ins and
        late leave returns, and the `points_assessed` of discipline cases in
        `SANCTIONED` or `CLOSED` status. The `demerit_points_provisional` total
        adds, on top of the official figure, the `points_proposed` of cases still
        in `REPORTED`, `UNDER_REVIEW`, `HEARING_SCHEDULED`, or `APPEALED`".

        Design: Difficulty/dual_variant_calc/discipline_points_official_vs_provisional
        """
        student, dean1, case1, case2 = self._setup_sanctioned_plus_reported()
        fetched = get_student(student["id"])
        assert fetched["demerit_points"] == 6
        assert fetched["demerit_points_provisional"] == 11

    def test_pending_case_stays_reported_and_standing_good(self, api, admin_headers):
        """PRD §2.8: "fewer than 10 means `GOOD`".
        PRD §3.7: "the case opens in `REPORTED`. Pending cases feed the
        provisional demerit total (§2.8) without touching the official one."

        Design: Difficulty/dual_variant_calc/discipline_points_official_vs_provisional
        """
        student, dean1, case1, case2 = self._setup_sanctioned_plus_reported()
        fetched_case = validate_success(api.get_discipline_case(
            case2["id"], make_dean_headers(dean1["id"])), 200)
        assert fetched_case["status"] == "REPORTED"

        fetched = get_student(student["id"])
        assert fetched["discipline_standing"] == "GOOD"
        assert_standing_matches_points(fetched)


class TestAppealCycle:
    def _setup_appealed_then_upheld(self):
        """MAJOR case heard and SANCTIONED at 5; appeal; UPHOLD adjusted to 7."""
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="MALE",
                               legal_name="Stu G")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MAJOR",
                           description="Fire extinguisher discharge",
                           points_proposed=5)
        sanction_major_case(case["id"], dean1["id"], dean2["id"], 5,
                            sanction_type="PROBATION")
        get_success_data(api_client.appeal_case(
            case["id"], make_student_headers(student["id"])))
        get_success_data(api_client.appeal_decision(
            case["id"], "UPHOLD", make_dean_headers(dean2["id"]),
            adjusted_points=7))
        return student, dean1, dean2, case

    def test_second_appeal_rejected_at_cap(self, api):
        """PRD §3.7: "The student who is the subject of a `SANCTIONED` case —
        `X-User-ID` must equal the case's `student_id` — may appeal, once only:
        a second appeal is rejected with `ERR_APPEAL_LIMIT_REACHED`".

        Design: Difficulty/non_linear_state_machine/discipline_case_appeal_cycle_with_cap
        """
        student, dean1, dean2, case = self._setup_appealed_then_upheld()
        res = api.appeal_case(case["id"], make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)

        fetched = validate_success(api.get_discipline_case(
            case["id"], make_dean_headers(dean1["id"])), 200)
        assert fetched["status"] == "SANCTIONED"
        assert fetched["appeal_count"] == 1

    def test_uphold_with_adjusted_points_shifts_official_total(self, api):
        """PRD §3.7: "Upholding returns the case to `SANCTIONED` and accepts an
        optional `adjusted_points`: when provided, `points_assessed` is replaced
        with the adjusted figure and the student's official total is shifted by
        the delta between old and new, with standing re-evaluation following."

        Design: Difficulty/non_linear_state_machine/discipline_case_appeal_cycle_with_cap
        """
        student, dean1, dean2, case = self._setup_appealed_then_upheld()
        fetched_case = validate_success(api.get_discipline_case(
            case["id"], make_dean_headers(dean1["id"])), 200)
        assert fetched_case["points_assessed"] == 7

        fetched_student = get_student(student["id"])
        assert fetched_student["demerit_points"] == 7


class TestParallelDimensions:
    def _setup_on_leave_then_sanctioned(self):
        parent = make_parent()
        student = make_student(parent["id"], grade=12, gender="FEMALE",
                               legal_name="Stu H")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        get_success_data(api_client.set_student_enrollment(
            student["id"], "ON_LEAVE", TEST_USERS["admin_headers"]))
        return student, dean1, dean2

    def test_sanction_during_on_leave_moves_only_standing(self, api, admin_headers):
        """PRD §3.2: "Students carry two parallel dimensions on one record." and
        "`ENROLLED` and `ON_LEAVE` toggle freely in both directions".
        PRD §3.2: "The standing axis, `discipline_standing`, is computed rather
        than commanded: it tracks the official point total against the thresholds
        of §2.8."

        Design: Difficulty/non_linear_state_machine/student_parallel_dimensions_independent
        """
        student, dean1, dean2 = self._setup_on_leave_then_sanctioned()
        mid = get_student(student["id"])
        assert mid["enrollment_status"] == "ON_LEAVE"
        assert mid["discipline_standing"] == "GOOD"

        case = report_case(student["id"], dean1["id"], category="MINOR",
                           description="Off campus without leave",
                           points_proposed=10)
        sanction_minor_case(case["id"], dean1["id"], dean2["id"], 10,
                            sanction_type="PROBATION")

        post = get_student(student["id"])
        assert post["enrollment_status"] == "ON_LEAVE"
        assert post["discipline_standing"] == "PROBATION"

    def test_enrollment_returns_while_standing_persists(self, api, admin_headers):
        """PRD §3.2: "`ENROLLED` and `ON_LEAVE` toggle freely in both directions"
        and "The standing axis, `discipline_standing`, is computed rather than
        commanded: it tracks the official point total against the thresholds of
        §2.8."

        Design: Difficulty/non_linear_state_machine/student_parallel_dimensions_independent
        """
        student, dean1, dean2 = self._setup_on_leave_then_sanctioned()
        case = report_case(student["id"], dean1["id"], category="MINOR",
                           description="Off campus without leave",
                           points_proposed=10)
        sanction_minor_case(case["id"], dean1["id"], dean2["id"], 10,
                            sanction_type="PROBATION")

        validate_success(api.set_student_enrollment(student["id"], "ENROLLED",
                                                    admin_headers), 200)
        fin = get_student(student["id"])
        assert fin["enrollment_status"] == "ENROLLED"
        assert fin["discipline_standing"] == "PROBATION"


class TestStandingThresholdBoundary:
    def _setup_student(self):
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="FEMALE",
                               legal_name="Stu N")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        return student, dean1, dean2

    def test_nine_points_leaves_standing_good(self, api):
        """PRD §2.8: "Discipline standing is recomputed after every change to
        `demerit_points`, from two inclusive thresholds: at least 20 points means
        `SUSPENDED`; at least 10 but fewer than 20 means `PROBATION`; fewer than
        10 means `GOOD`."

        Design: Difficulty/boundary_precision_check/standing_threshold_nine_vs_ten
        """
        student, dean1, dean2 = self._setup_student()
        case1 = report_case(student["id"], dean1["id"], category="MINOR",
                            description="Missed study hall x3", points_proposed=9)
        sanction_minor_case(case1["id"], dean1["id"], dean2["id"], 9,
                            sanction_type="WARNING")

        fetched = get_student(student["id"])
        assert fetched["demerit_points"] == 9
        assert fetched["discipline_standing"] == "GOOD"  # 9 < 10 does not trigger

    def test_ten_points_flips_standing_to_probation(self, api):
        """PRD §2.8: "The boundaries are inclusive at the bottom of each band —
        exactly 10 points is `PROBATION`, exactly 20 is `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/standing_threshold_nine_vs_ten
        """
        student, dean1, dean2 = self._setup_student()
        case1 = report_case(student["id"], dean1["id"], category="MINOR",
                            description="Missed study hall x3", points_proposed=9)
        sanction_minor_case(case1["id"], dean1["id"], dean2["id"], 9,
                            sanction_type="WARNING")
        case2 = report_case(student["id"], dean1["id"], category="MINOR",
                            description="Late to bed check", points_proposed=1)
        sanction_minor_case(case2["id"], dean1["id"], dean2["id"], 1,
                            sanction_type="WARNING")

        fetched = get_student(student["id"])
        assert fetched["demerit_points"] == 10
        assert fetched["discipline_standing"] == "PROBATION"  # >= 10 inclusive


class TestOverturnConservation:
    def _setup_sanctioned_and_appealed(self):
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="MALE",
                               legal_name="Stu U")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MAJOR",
                           description="Lab vandalism", points_proposed=6)
        sanction_major_case(case["id"], dean1["id"], dean2["id"], 6,
                            sanction_type="PROBATION")
        get_success_data(api_client.appeal_case(
            case["id"], make_student_headers(student["id"])))
        return student, dean1, dean2, case

    def test_overturn_restores_points_and_standing_exactly(self, api):
        """PRD §3.7: "Overturning moves the case to `DISMISSED`, subtracts the
        case's `points_assessed` from the student's official total exactly as
        they were added, zeroes the case's `points_assessed`, and re-evaluates
        standing — the exact reversal is what can drop a student back below a
        threshold."

        Design: Difficulty/compensating_invariant/sanction_then_overturn_conserves_points
        """
        student, dean1, dean2, case = self._setup_sanctioned_and_appealed()
        mid = get_student(student["id"])
        assert mid["demerit_points"] == 6

        decided = validate_success(api.appeal_decision(
            case["id"], "OVERTURN", make_dean_headers(dean2["id"])), 200)
        assert decided["status"] == "DISMISSED"
        assert decided["points_assessed"] == 0

        end = get_student(student["id"])
        assert end["demerit_points"] == 0  # exact reversal; no drift
        assert end["discipline_standing"] == "GOOD"

    def test_overturn_zeroes_case_points_and_dismisses(self, api, admin_headers):
        """PRD §3.7: "Overturning moves the case to `DISMISSED`, subtracts the
        case's `points_assessed` from the student's official total exactly as
        they were added, zeroes the case's `points_assessed`, and re-evaluates
        standing".

        Design: Difficulty/compensating_invariant/sanction_then_overturn_conserves_points
        """
        student, dean1, dean2, case = self._setup_sanctioned_and_appealed()
        validate_success(api.appeal_decision(case["id"], "OVERTURN",
                                             make_dean_headers(dean2["id"])), 200)

        fetched = validate_success(api.get_discipline_case(
            case["id"], make_dean_headers(dean1["id"])), 200)
        assert_discipline_case(fetched)
        assert fetched["status"] == "DISMISSED"
        assert fetched["points_assessed"] == 0

        end = get_student(student["id"])
        assert end["demerit_points"] == 0


class TestProvisionalLedgerFiltering:
    def test_dismissed_case_leaves_both_ledgers(self, api):
        """PRD §2.8: "The `demerit_points_provisional` total adds, on top of the
        official figure, the `points_proposed` of cases still in `REPORTED`,
        `UNDER_REVIEW`, `HEARING_SCHEDULED`, or `APPEALED`".
        PRD §3.7: "A dismissed outcome stamps `decided_at`, applies no points,
        and removes the case from the provisional input set."

        Design: Corner/calculations/provisional_points_exclude_dismissed
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="FEMALE",
                               legal_name="Stu V")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MINOR",
                           description="Dining hall disruption", points_proposed=5)

        pending = get_student(student["id"])
        assert pending["demerit_points"] == 0
        assert pending["demerit_points_provisional"] == 5

        get_success_data(api_client.begin_review(case["id"],
                                                 make_dean_headers(dean1["id"])))
        dismissed = validate_success(api.record_outcome(
            case["id"], {"outcome": "DISMISSED"}, make_dean_headers(dean2["id"])), 200)
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["decided_at"] is not None
        assert dismissed["points_assessed"] == 0

        after = get_student(student["id"])
        assert after["demerit_points"] == 0
        assert after["demerit_points_provisional"] == 0


class TestHearingRules:
    def test_major_outcome_without_hearing_rejected(self, api):
        """PRD §3.7: "For a `MAJOR` case, the outcome must wait for a hearing:
        recording an outcome on a `MAJOR` case still in `UNDER_REVIEW` is
        rejected with `ERR_HEARING_REQUIRED`."

        Design: Corner/state_machines/major_case_outcome_without_hearing_returns_hearing_required
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="MALE",
                               legal_name="Stu Q")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MAJOR",
                           description="Fire alarm tampering", points_proposed=15)
        get_success_data(api_client.begin_review(case["id"],
                                                 make_dean_headers(dean1["id"])))

        res = api.record_outcome(
            case["id"], {"outcome": "SANCTIONED", "sanction_type": "SUSPENSION",
                         "points_assessed": 15},
            make_dean_headers(dean2["id"]))
        validate_error(res, ApiErrorId.ERR_HEARING_REQUIRED)

    def test_minor_case_dismissed_from_under_review(self, api):
        """PRD §3.7: "For a `MINOR` case, a dean other than the reporter may
        record an outcome directly from `UNDER_REVIEW`." and "A dismissed outcome
        stamps `decided_at`, applies no points, and removes the case from the
        provisional input set."

        Design: Corner/state_machines/minor_case_dismissed_from_under_review
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=9, gender="FEMALE",
                               legal_name="Stu R")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MINOR",
                           description="Unexcused class absence", points_proposed=5)
        get_success_data(api_client.begin_review(case["id"],
                                                 make_dean_headers(dean1["id"])))

        dismissed = validate_success(api.record_outcome(
            case["id"], {"outcome": "DISMISSED"}, make_dean_headers(dean2["id"])), 200)
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["decided_at"] is not None
        assert dismissed["points_assessed"] == 0

        fetched = get_student(student["id"])
        assert fetched["demerit_points"] == 0
        assert fetched["demerit_points_provisional"] == 0

    def test_hearing_officer_equal_to_reporter_rejected(self, api):
        """PRD §3.7: "the dean who adjudicates must not be the reporter, on pain
        of `ERR_REPORTER_CANNOT_ADJUDICATE`" and "Scheduling a hearing names a
        `hearing_officer_id` — an active dean who is not the reporter".

        Design: Corner/validations/segregation_officer_equals_reporter_rejected
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="MALE",
                               legal_name="Stu C")
        dean1 = make_dean("Dean One")
        case = report_case(student["id"], dean1["id"], category="MAJOR",
                           description="Theft", points_proposed=12)
        get_success_data(api_client.begin_review(case["id"],
                                                 make_dean_headers(dean1["id"])))

        res = api.schedule_hearing(case["id"], "2026-09-10T15:00:00Z",
                                   dean1["id"], make_dean_headers(dean1["id"]))
        validate_error(res, ApiErrorId.ERR_REPORTER_CANNOT_ADJUDICATE)

    def test_hearing_in_the_past_rejected(self, api):
        """PRD §3.7: "a `hearing_at` that must lie in the future
        (`ERR_HEARING_IN_PAST`)".

        Design: Corner/validations/hearing_in_past_rejected
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="MALE",
                               legal_name="Stu AC")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MAJOR",
                           description="Theft", points_proposed=12)
        get_success_data(api_client.begin_review(case["id"],
                                                 make_dean_headers(dean1["id"])))

        # Logical clock is at the default 2026-08-01; 2026-07-01 precedes it.
        res = api.schedule_hearing(case["id"], "2026-07-01T15:00:00Z",
                                   dean2["id"], make_dean_headers(dean1["id"]))
        validate_error(res, ApiErrorId.ERR_HEARING_IN_PAST)


class TestAppealWindowAndSegregation:
    def test_appeal_after_window_closed_rejected(self, api):
        """PRD §3.7: "an appeal filed more than 168 hours after `decided_at` is
        rejected with `ERR_APPEAL_WINDOW_CLOSED`".

        Design: Corner/validations/appeal_after_window_closed_rejected
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="MALE",
                               legal_name="Stu S")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MINOR",
                           description="Library disruption", points_proposed=4)
        # decided_at stamps to the default logical clock 2026-08-01T00:00:00Z.
        sanction_minor_case(case["id"], dean1["id"], dean2["id"], 4,
                            sanction_type="WARNING")

        # 2026-08-01T00:00Z + 168h = 2026-08-08T00:00Z; one second past it.
        set_clock("2026-08-09T00:00:01Z")
        res = api.appeal_case(case["id"], make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    def test_appeal_decision_by_reporter_rejected(self, api):
        """PRD §3.7: "A dean other than the reporter then decides the appeal,
        supplying a `decision` of `UPHOLD` or `OVERTURN`." and "the dean who
        adjudicates must not be the reporter, on pain of
        `ERR_REPORTER_CANNOT_ADJUDICATE`".

        Design: Corner/rbac/appeal_decision_by_reporter_rejected
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="MALE",
                               legal_name="Stu AH")
        dean1 = make_dean("Dean One")
        dean2 = make_dean("Dean Two")
        case = report_case(student["id"], dean1["id"], category="MINOR",
                           description="Dorm damage", points_proposed=6)
        sanction_minor_case(case["id"], dean1["id"], dean2["id"], 6,
                            sanction_type="WARNING")
        get_success_data(api_client.appeal_case(
            case["id"], make_student_headers(student["id"])))

        res = api.appeal_decision(case["id"], "UPHOLD",
                                  make_dean_headers(dean1["id"]))
        validate_error(res, ApiErrorId.ERR_REPORTER_CANNOT_ADJUDICATE)

        ok = validate_success(api.appeal_decision(
            case["id"], "UPHOLD", make_dean_headers(dean2["id"])), 200)
        assert ok["status"] == "SANCTIONED"
