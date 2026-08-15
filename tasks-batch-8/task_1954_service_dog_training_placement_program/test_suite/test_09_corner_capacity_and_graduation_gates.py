"""Corner queue: raiser capacity, class size/window/capacity gates, refund
guard while matched, graduation gates, attendance recompute, enrollment
withdraw branch (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    PAT_PERFECT_SCORES,
    TEST_USERS,
    ApiErrorId,
    create_approved_raiser,
    create_certified_trainer,
    create_class_enrolling,
    create_cleared_dog,
    create_eligible_entry,
    create_match_ready_dog,
    enroll_match,
    propose_and_accept_match,
    setup_enrolled_pair,
    setup_in_session_enrollment,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]


class TestRaiserCapacityEnforcedOnExplicitPick:
    """Corner/validations/raiser_capacity_enforced_on_explicit_pick."""

    def test_full_raiser_rejected(self, api):
        """PRD §3.6: "When the request supplies `puppy_raiser_id`, that
        explicit pick bypasses ranking but not eligibility: the raiser must be
        `APPROVED` or `ACTIVE` with `current_dog_count` below
        `foster_capacity` (violations are `ERR_RAISER_CAPACITY`, HTTP 409)."

        Raiser with capacity 1 already fostering one dog.

        Design: Corner/validations/raiser_capacity_enforced_on_explicit_pick
        """
        raiser = create_approved_raiser(foster_capacity=1)
        dog1 = create_cleared_dog()
        validate_success(
            api.create_raiser_placement(
                dog1["id"], {"puppy_raiser_id": raiser["id"]}, TD
            ),
            expected_status=201,
        )
        dog2 = create_cleared_dog()
        resp = api.create_raiser_placement(
            dog2["id"], {"puppy_raiser_id": raiser["id"]}, TD
        )
        validate_error(resp, ApiErrorId.ERR_RAISER_CAPACITY)
        dog2_now = validate_success(api.get_dog(dog2["id"], TD))
        assert dog2_now["status"] == "CLEARED"


class TestClassStartBelowMinimumSize:
    """Corner/validations/class_start_below_minimum_size_rejected."""

    def test_start_with_zero_enrolled_rejected(self, api):
        """PRD §3.7: "Starting the class moves `ENROLLING` to `IN_SESSION` and
        enforces two checks: `enrolled_count` must be at least 1 (otherwise
        `ERR_CLASS_TOO_SMALL` — the minimum class size is one enrolled pair)
        and the logical date must be at least `starts_on` (otherwise
        `ERR_ENROLLMENT_WINDOW`)."

        Clock is past starts_on; only the size check can fail.

        Design: Corner/validations/class_start_below_minimum_size_rejected
        """
        trainer = create_certified_trainer()
        clazz = create_class_enrolling(
            trainer["id"], capacity=4, total_sessions=20
        )
        validate_success(
            api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN)
        )
        resp = api.start_class(clazz["id"], TD)
        validate_error(resp, ApiErrorId.ERR_CLASS_TOO_SMALL)
        now = validate_success(api.get_class(clazz["id"], TD))
        assert now["status"] == "ENROLLING"


class TestClassStartBeforeStartsOn:
    """Corner/validations/class_start_before_starts_on_rejected."""

    def test_start_before_starts_on_rejected(self, api):
        """PRD §3.7: "the logical date must be at least `starts_on` (otherwise
        `ERR_ENROLLMENT_WINDOW`)."

        Clock remains at the 2026-08-01 startup default while starts_on is
        2026-09-01; one pair is enrolled, so only the temporal gate can fail.

        Design: Corner/validations/class_start_before_starts_on_rejected
        """
        ctx = setup_enrolled_pair()
        resp = api.start_class(ctx["clazz"]["id"], TD)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW)
        now = validate_success(api.get_class(ctx["clazz"]["id"], TD))
        assert now["status"] == "ENROLLING"
        assert now["enrolled_count"] == 1


class TestClassCapacityFullBoundary:
    """Corner/validations/class_capacity_full_boundary."""

    def _three_pairs_and_class(self):
        trainer = create_certified_trainer()
        pairs = []
        for _ in range(3):
            dog, _r, _t = create_match_ready_dog()
            _applicant, entry, _c = create_eligible_entry()
            match = propose_and_accept_match(dog, entry)
            pairs.append((dog, match))
        clazz = create_class_enrolling(trainer["id"], capacity=2)
        return clazz, pairs

    def test_second_enrollment_at_capacity_succeeds(self, api):
        """PRD §3.7: "Seat capacity is enforced at creation: enrolling
        succeeds while `enrolled_count` is below `capacity` — the enrollment
        that brings the count exactly to capacity succeeds — and is rejected
        with `ERR_CLASS_FULL` beyond that."

        Capacity 2: the 2nd enrollment succeeds.

        Design: Corner/validations/class_capacity_full_boundary
        """
        clazz, pairs = self._three_pairs_and_class()
        enroll_match(clazz, pairs[0][1])
        enrollment_b = enroll_match(clazz, pairs[1][1])
        assert enrollment_b["status"] == "ENROLLED"
        now = validate_success(api.get_class(clazz["id"], TD))
        assert now["enrolled_count"] == 2

    def test_third_enrollment_rejected_class_full(self, api):
        """PRD §3.7: "rejected with `ERR_CLASS_FULL` beyond that."

        The third enrollment against a capacity-2 class fails, and its match
        stays ACCEPTED.

        Design: Corner/validations/class_capacity_full_boundary
        """
        clazz, pairs = self._three_pairs_and_class()
        enroll_match(clazz, pairs[0][1])
        enroll_match(clazz, pairs[1][1])
        fresh = validate_success(api.get_class(clazz["id"], TD))
        assert fresh["enrolled_count"] == 2
        resp = api.create_enrollment(
            clazz["id"],
            {
                "match_id": pairs[2][1]["id"],
                "expected_class_version": fresh["version"],
            },
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_CLASS_FULL)
        match_c = validate_success(api.get_match(pairs[2][1]["id"], COORD))
        assert match_c["status"] == "ACCEPTED"
        dog_c = validate_success(api.get_dog(pairs[2][0]["id"], TD))
        assert dog_c["status"] == "MATCHED"


class TestRefundBlockedWhileEntryMatched:
    """Corner/validations/refund_blocked_while_entry_matched."""

    def test_refund_rejected_while_matched(self, api):
        """PRD §3.3: "Refunding a `RECEIVED` contribution is blocked once the
        money is locked into a placement pipeline: when the linked entry is
        `MATCHED` or the applicant is `PLACED`, the refund is rejected with
        `ERR_REFUND_NOT_ALLOWED`."

        Design: Corner/validations/refund_blocked_while_entry_matched
        """
        dog, _r, _t = create_match_ready_dog()
        _applicant, entry, contribution = create_eligible_entry()
        propose_and_accept_match(dog, entry)
        entry_now = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert entry_now["status"] == "MATCHED"
        resp = api.refund_contribution(contribution["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_REFUND_NOT_ALLOWED)
        contribution_now = validate_success(
            api.get_contribution(contribution["id"], COORD)
        )
        assert contribution_now["status"] == "RECEIVED"
        entry_after = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert entry_after["raised_cents"] == 1_350_000


class TestGraduationWithoutPatPass:
    """Corner/validations/graduation_without_pat_pass_rejected."""

    def test_no_scored_pass_pat_rejected(self, api):
        """PRD §3.7: "a public access test for the enrollment exists with
        status `SCORED_PASS` (otherwise `ERR_GRADUATION_REQUIREMENTS`)."

        Class in GRADUATION_REVIEW with 20/20 attendance but no PAT at all.

        Design: Corner/validations/graduation_without_pat_pass_rejected
        """
        ctx = setup_in_session_enrollment(attendance=20)
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN)
        )
        validate_success(api.begin_graduation_review(ctx["clazz"]["id"], TD))
        resp = api.graduate_enrollment(ctx["enrollment"]["id"], TD)
        validate_error(resp, ApiErrorId.ERR_GRADUATION_REQUIREMENTS)
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "ENROLLED"
        partnerships = validate_success(
            api.list_enrollment_partnerships(ctx["enrollment"]["id"], TD)
        )
        assert len(partnerships) == 0


class TestGraduationAttendanceBelowThreshold:
    """Corner/validations/graduation_attendance_below_threshold_rejected."""

    def test_attendance_80_0_rejected(self, api):
        """PRD §3.7: "the enrollment is `ENROLLED`; its class is in
        `GRADUATION_REVIEW`; `attendance_pct` is at least 85.0 inclusive
        (otherwise `ERR_ATTENDANCE_BELOW_THRESHOLD`); and a public access test
        for the enrollment exists with status `SCORED_PASS` (otherwise
        `ERR_GRADUATION_REQUIREMENTS`)."

        16/20 sessions = 80.0 < 85.0 blocks graduation even with a
        SCORED_PASS PAT.

        Design: Corner/validations/graduation_attendance_below_threshold_rejected
        """
        ctx = setup_in_session_enrollment(
            attendance=16, pat_scores=PAT_PERFECT_SCORES
        )
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["attendance_pct"] == pytest.approx(80.0, abs=0.01)
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN)
        )
        validate_success(api.begin_graduation_review(ctx["clazz"]["id"], TD))
        resp = api.graduate_enrollment(ctx["enrollment"]["id"], TD)
        validate_error(resp, ApiErrorId.ERR_ATTENDANCE_BELOW_THRESHOLD)
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "ENROLLED"


class TestRecordAttendanceRecomputesPercentage:
    """Corner/endpoints/record_attendance_recomputes_percentage."""

    def test_absolute_set_recomputes_from_total_sessions(self, api):
        """PRD §3.7: "Attendance is recorded as an absolute count: a
        `TrainingDirector` or `Trainer` sets `sessions_attended` while the
        class is `IN_SESSION`, and `attendance_pct` is recomputed as sessions
        attended divided by the class's `total_sessions`, multiplied by 100,
        rounded half-up to 1 decimal place."

        10/20 -> 50.0, then an update to 17/20 -> 85.0 (recompute, not
        accumulation).

        Design: Corner/endpoints/record_attendance_recomputes_percentage
        """
        ctx = setup_enrolled_pair()
        from test_helpers import start_class_in_session
        start_class_in_session(ctx["clazz"])
        first = validate_success(
            api.record_attendance(
                ctx["enrollment"]["id"], {"sessions_attended": 10}, TD
            )
        )
        assert first["attendance_pct"] == pytest.approx(50.0, abs=0.01)
        second = validate_success(
            api.record_attendance(
                ctx["enrollment"]["id"], {"sessions_attended": 17}, TD
            )
        )
        assert second["sessions_attended"] == 17
        assert second["attendance_pct"] == pytest.approx(85.0, abs=0.01)


class TestEnrollmentWithdrawMidClass:
    """Corner/endpoints/enrollment_withdraw_mid_class_dissolves_match."""

    def test_actor_initiated_withdraw_dissolves_match(self, api):
        """PRD §3.7: "Withdrawing an `ENROLLED` enrollment — directly by a
        `TrainingDirector`, or through the class-cancel, applicant-withdraw,
        and career-change cascades — decrements `enrolled_count`. When the
        withdrawal is actor-initiated, the accepted match dissolves (with all
        of the dissolve side effects), the dog reverts from `TEAM_TRAINING` to
        `MATCH_READY`, and the applicant from `TEAM_TRAINING` to
        `MATCH_ELIGIBLE`."

        Design: Corner/endpoints/enrollment_withdraw_mid_class_dissolves_match
        """
        ctx = setup_enrolled_pair()
        from test_helpers import start_class_in_session
        start_class_in_session(ctx["clazz"])
        withdrawn = validate_success(
            api.withdraw_enrollment(ctx["enrollment"]["id"], TD)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        match = validate_success(api.get_match(ctx["match"]["id"], COORD))
        assert match["status"] == "DISSOLVED"
        dog = validate_success(api.get_dog(ctx["dog"]["id"], TD))
        assert dog["status"] == "MATCH_READY"
        applicant = validate_success(api.get_applicant(ctx["applicant"]["id"], COORD))
        assert applicant["application_status"] == "MATCH_ELIGIBLE"
        entry = validate_success(api.get_waitlist_entry(ctx["entry"]["id"], COORD))
        assert entry["status"] == "ELIGIBLE"
        assert entry["dissolved_match_count"] == 1
        clazz = validate_success(api.get_class(ctx["clazz"]["id"], TD))
        assert clazz["enrolled_count"] == 0
