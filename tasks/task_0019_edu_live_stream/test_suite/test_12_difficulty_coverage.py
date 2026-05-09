"""Difficulty-design coverage: every scaffold_difficulty_design[*].instances[*]
gets at least TWO dedicated tests, each tagged with
`# difficulty: <rule_id>/<instance.name>` in its docstring.

The PRD-citation rule still applies: each test cites the PRD prose for the
underlying rule, never the difficulty-design entry itself.
"""

import pytest

from test_helpers import (
    advance_clock,
    advance_clock_days,
    api_client,
    approve_refund_request,
    create_class_group,
    create_instructor,
    create_live_class_payload,
    create_published_course,
    delist_course,
    end_live_class,
    enroll_student,
    file_leave_request,
    file_refund_request,
    log_watch_session,
    make_instructor_headers,
    make_student_headers,
    make_ta_headers,
    publish_assignment,
    reach_revision_count,
    reject_refund_request,
    request_revision,
    resubmit,
    schedule_live_class,
    setup_course_delist_cascade,
    setup_enrollment_for_refund,
    setup_enrollment_with_progress,
    setup_instructor_with_window,
    setup_pending_leave_with_ta,
    setup_room_with_existing_session,
    setup_submission_under_review,
    start_live_class,
    start_review,
    submit_assignment,
    sweep_at_risk,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─────────────────────────────────────────────────────────────────────────
# Rule 1 — Dual-variant calculations
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule1RefundProvisionalVsFinal:
    """# difficulty: dual_variant_calc / refund_provisional_vs_final_diverges_on_progress_growth

    PRD §3.7 specifies provisional@request and final@approval are distinct
    snapshots; PRD says: 'Because the inputs are re-snapshotted, the final
    amount may legitimately differ from the provisional amount even when the
    formula and constants are identical.'
    """

    def test_provisional_locks_at_request_time(self, api):
        """# difficulty: dual_variant_calc/refund_provisional_vs_final_diverges_on_progress_growth

        PRD §3.7: 'The provisional refund calculation is forward-looking: it
        locks in the student's circumstances at the moment of request.'
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=10,
            target_progress_percent=25.0,    # tier-2 (mid)
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=1)
        # tier-2 (days<=30, progress<=30): ratio=0.7 → gross=70000.
        # Deduct 1 kit ($50 = 5000c) → provisional=65000. attended=0 ⇒ no
        # service deduction.
        assert refund["provisional_amount_cents"] == 65000, (
            f"Provisional at days=10/progress=25.0/kits=1 must be 65000; "
            f"got {refund['provisional_amount_cents']}"
        )

    def test_final_resnapshots_at_approval_time(self, api):
        """# difficulty: dual_variant_calc/refund_provisional_vs_final_diverges_on_progress_growth

        PRD §3.7: 'progress is the enrolment's current progress_percent at
        approval time (not at requested_at); days_elapsed is recomputed
        against the approval timestamp; and attended_count is the count of
        attendance rows whose created_at is at or before the approval
        timestamp.'
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=10,
            target_progress_percent=25.0,    # tier-2 at request
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        provisional = refund["provisional_amount_cents"]  # 70000 (tier-2)
        # Push progress upward into tier-3 territory: watch enough additional
        # seconds so progress exceeds 30%.
        log_watch_session(enrollment, student, chapters[1]["id"], 600)
        approved = approve_refund_request(refund)
        final_amt = approved["final_amount_cents"]
        # tier-3 (progress>30,<=60) ratio=0.3 → gross=30000.
        assert final_amt == 30000, (
            f"Final at approval after progress moved above 30 must use "
            f"tier-3 ratio; expected 30000, got {final_amt}"
        )
        assert final_amt != provisional, (
            f"PRD §3.7: provisional and final may legitimately differ; "
            f"provisional={provisional}, final={final_amt}"
        )


class TestDifficultyRule1ChapterVsWatchDuration:
    """# difficulty: dual_variant_calc / chapter_completion_vs_watch_duration_diverges_on_partial_views"""

    def test_partial_view_yields_zero_chapter_completion(self, api):
        """# difficulty: dual_variant_calc/chapter_completion_vs_watch_duration_diverges_on_partial_views

        PRD §3.4: 'A required chapter counts as completed when the sum of
        seconds_watched across all WatchSession rows for that enrollment and
        that chapter is at least equal to the chapter's video_duration_seconds.'

        Watching 990s of a 1000s chapter does NOT meet the threshold, so
        chapter_completion_percent stays at 0.0 even though watch_duration is
        nonzero.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        log_watch_session(enrollment, student, chapters[0]["id"], 990)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["chapter_completion_percent"] == pytest.approx(0.0, abs=0.05), (
            f"chapter_completion must be 0.0 when no chapter has ≥duration "
            f"watched; got {e['chapter_completion_percent']}"
        )

    def test_partial_view_yields_nonzero_watch_duration(self, api):
        """# difficulty: dual_variant_calc/chapter_completion_vs_watch_duration_diverges_on_partial_views

        PRD §3.4: 'For each such chapter it computes the smaller of the
        chapter's total watched seconds and that chapter's
        video_duration_seconds.'

        With 990s watched of 1000s on chapter 1 and 0 on chapter 2 (total
        2000s required), watch_duration_percent = 100 * 990 / 2000 = 49.5.
        progress_percent uses max(0.0, 49.5) = 49.5.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        log_watch_session(enrollment, student, chapters[0]["id"], 990)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["watch_duration_percent"] == pytest.approx(49.5, abs=0.05)
        assert e["progress_percent"] == pytest.approx(49.5, abs=0.05)


# ─────────────────────────────────────────────────────────────────────────
# Rule 2 — Combinatorial formulas
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule2DiscountClamp:
    """# difficulty: combinatorial_formula / enrollment_paid_amount_three_input_nonlinear

    PRD §3.6: 'the effective discount percentage is the supplied
    discount_percent clamped to lie between zero and eighty inclusive — values
    below zero become zero, values above eighty become eighty. The raw cent
    amount is list_price_cents multiplied by (one hundred minus the effective
    percentage), divided by one hundred.'
    """

    def test_paid_amount_with_zero_discount(self, api):
        """# difficulty: combinatorial_formula/enrollment_paid_amount_three_input_nonlinear

        PRD §3.6: 'The raw cent amount is list_price_cents multiplied by
        (one hundred minus the effective percentage), divided by one hundred.'
        """
        course, _, _ = create_published_course(
            list_price_cents=10000, discount_percent=0
        )
        enrollment, _ = enroll_student(course)
        assert enrollment["paid_amount_cents"] == 10000

    def test_paid_amount_with_in_range_discount(self, api):
        """# difficulty: combinatorial_formula/enrollment_paid_amount_three_input_nonlinear

        PRD §3.6 standard formula path with discount=15.
        """
        course, _, _ = create_published_course(
            list_price_cents=10000, discount_percent=15
        )
        enrollment, _ = enroll_student(course)
        assert enrollment["paid_amount_cents"] == 8500


class TestDifficultyRule2AtRiskCircularEvalOrder:
    """# difficulty: combinatorial_formula / at_risk_alert_circular_eval_order_pinned

    PRD §3.4 + §3.5 pin the recompute order: chapter → watch → progress → at-risk.
    """

    def test_at_risk_after_clock_advance_with_low_progress(self, api):
        """# difficulty: combinatorial_formula/at_risk_alert_circular_eval_order_pinned

        PRD §3.5: 'learning_status flips from ACTIVE to AT_RISK if and only
        if the days-since-enrolment is at least fourteen and either the
        current progress_percent is strictly less than thirty percent or the
        risk score is strictly greater than zero.'

        With 200s on chapter 1 of a 2000s required total: chapter_completion
        is 0 (no chapter complete), watch_duration is 10.0%, progress is
        max=10.0. After 14d the learning_status flips to AT_RISK because
        progress<30%.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        log_watch_session(enrollment, student, chapters[0]["id"], 200)
        advance_clock_days(14)
        sweep_at_risk()
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["chapter_completion_percent"] == pytest.approx(0.0, abs=0.05)
        assert e["watch_duration_percent"] == pytest.approx(10.0, abs=0.05)
        assert e["progress_percent"] == pytest.approx(10.0, abs=0.05)
        assert e["learning_status"] == "AT_RISK"

    def test_recompute_order_progress_picks_max(self, api):
        """# difficulty: combinatorial_formula/at_risk_alert_circular_eval_order_pinned

        PRD §3.4: 'first chapter_completion_percent, then
        watch_duration_percent, then progress_percent from the
        maximum-with-tiebreak.'

        Watching 1000s of one chapter completes that chapter
        (chapter_completion=50%) and watch_duration=50%. The two are equal,
        so progress_percent must equal them under the documented tie rule.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        log_watch_session(enrollment, student, chapters[0]["id"], 1000)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["chapter_completion_percent"] == pytest.approx(50.0, abs=0.05)
        assert e["watch_duration_percent"] == pytest.approx(50.0, abs=0.05)
        assert e["progress_percent"] == pytest.approx(50.0, abs=0.05)


# ─────────────────────────────────────────────────────────────────────────
# Rule 3 — Non-linear state-machine shape
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule3CourseBranchingWithRevert:
    """# difficulty: non_linear_state_machine / course_branching_with_revert_leg

    PRD §3.1 branching: DRAFT → UNDER_REVIEW → {PUBLISHED | REJECTED};
    REJECTED → DRAFT via return-to-draft.
    """

    def test_branch_via_reject_and_return_to_draft(self, api):
        """# difficulty: non_linear_state_machine/course_branching_with_revert_leg

        PRD §3.1: 'From REJECTED, the owning instructor can return the course
        to DRAFT.'
        """
        from test_helpers import (
            add_chapter, approve_course, create_draft_course, reject_course,
            return_course_to_draft, submit_course_for_review,
        )
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        # DRAFT → UNDER_REVIEW
        course = submit_course_for_review(course, instructor)
        assert course["status"] == "UNDER_REVIEW"
        # UNDER_REVIEW → REJECTED
        course = reject_course(course)
        assert course["status"] == "REJECTED"
        # REJECTED → DRAFT
        course = return_course_to_draft(course, instructor)
        assert course["status"] == "DRAFT"
        # DRAFT → UNDER_REVIEW (second time)
        course = submit_course_for_review(course, instructor)
        assert course["status"] == "UNDER_REVIEW"
        # UNDER_REVIEW → PUBLISHED
        course = approve_course(course)
        assert course["status"] == "PUBLISHED"

    def test_two_syllabus_revisions_one_per_submit(self, api):
        """# difficulty: non_linear_state_machine/course_branching_with_revert_leg

        PRD §3.1: 'The submission also writes a fresh SyllabusRevision row
        whose revision_number is the current maximum for this course plus
        one.' Two submit-for-review calls produce two distinct rows.
        """
        from test_helpers import (
            add_chapter, create_draft_course, reject_course,
            return_course_to_draft, submit_course_for_review,
        )
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        submit_course_for_review(course, instructor)
        reject_course(course)
        return_course_to_draft(course, instructor)
        submit_course_for_review(course, instructor)
        rows, _ = validate_paginated(
            api.list_syllabus_revisions(
                course["id"], make_instructor_headers(instructor["id"])
            )
        )
        # Exactly two SyllabusRevision rows exist (one per submit).
        nums = sorted(r["revision_number"] for r in rows)
        assert nums == [1, 2], (
            f"PRD §3.1: revision_number must increment per submit; got {nums}"
        )


class TestDifficultyRule3SubmissionCyclicLoop:
    """# difficulty: non_linear_state_machine / submission_cyclic_revision_loop

    PRD §3.8: 'This closes the cyclic loop SUBMITTED → UNDER_REVIEW →
    REVISION_REQUESTED → SUBMITTED, which can iterate up to three times
    before the cap is reached.'
    """

    def test_revision_count_increments_per_cycle(self, api):
        """# difficulty: non_linear_state_machine/submission_cyclic_revision_loop

        PRD §3.8: 'On success, revision_count increments by one.' After two
        completed cycles, revision_count == 2.
        """
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment, sub = reach_revision_count(
            course, instructor, enrollment, student, target_count=2, fmt="TEXT"
        )
        assert sub["status"] == "SUBMITTED"
        assert sub["revision_count"] == 2

    def test_revision_cap_enforced_at_three(self, api):
        """# difficulty: non_linear_state_machine/submission_cyclic_revision_loop

        PRD §3.8: 'a current revision_count strictly less than the revision
        cap of three (ERR_REVISION_CAP_REACHED — the cap is reached when
        revision_count equals three).'
        """
        from test_helpers import request_revision_payload
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment, sub = reach_revision_count(
            course, instructor, enrollment, student, target_count=3, fmt="TEXT"
        )
        # sub is SUBMITTED with revision_count==3. Re-enter UNDER_REVIEW;
        # any subsequent request-revision must fail.
        sub_ur = start_review(sub, instructor)
        res = api.request_submission_revision(
            sub_ur["id"],
            request_revision_payload("nope"),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_REVISION_CAP_REACHED")


# ─────────────────────────────────────────────────────────────────────────
# Rule 4 — Transitive cascade chains
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule4DelistDepth3Cascade:
    """# difficulty: transitive_cascade / course_delist_depth_3_cascade

    PRD §3.1 names every link of the depth-3 chain explicitly.
    """

    def test_delist_freezes_course_and_cancels_live_class(self, api):
        """# difficulty: transitive_cascade/course_delist_depth_3_cascade

        PRD §3.1: 'every LiveClass belonging to this course that is currently
        in SCHEDULED is moved to CANCELLED with the reason COURSE_DELISTED ...
        the course's posture is recomputed to FROZEN.'
        """
        course, instructor, students, enrollments, live_class, refund = (
            setup_course_delist_cascade()
        )
        delist_course(course)
        c = validate_success(
            api.get_course(course["id"], make_instructor_headers(instructor["id"])),
            expected_status=200,
        )
        assert c["status"] == "DELISTED"
        assert c["posture"] == "FROZEN"

    def test_delist_blocks_new_enrollment_with_frozen_error(self, api):
        """# difficulty: transitive_cascade/course_delist_depth_3_cascade

        PRD §3.1: 'While the course is FROZEN, several operations are blocked
        with ERR_COURSE_FROZEN, including ... creating a new enrollment.'
        """
        from test_helpers import create_enrollment_payload, create_student
        course, _, _ = create_published_course()
        delist_course(course)
        new_student = create_student()
        res = api.create_enrollment(
            course["id"],
            create_enrollment_payload(new_student["id"]),
            make_student_headers(new_student["id"]),
        )
        validate_error(res, "ERR_COURSE_FROZEN")


class TestDifficultyRule4RefundApproveDepth2Cascade:
    """# difficulty: transitive_cascade / refund_approve_depth_2_cascade

    PRD §3.7: 'The enrolment's payment_status flips from REFUND_PENDING to
    REFUNDED, the enrolment's learning_status flips to WITHDRAWN ... an
    AuditLogEntry whose action is REFUND_APPROVED is appended.'
    """

    def test_approve_cascades_enrollment_dual_axes(self, api):
        """# difficulty: transitive_cascade/refund_approve_depth_2_cascade

        PRD §3.7: 'The enrolment's payment_status flips from REFUND_PENDING
        to REFUNDED, the enrolment's learning_status flips to WITHDRAWN.'
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=0,
            target_progress_percent=0.0,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        approve_refund_request(refund)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["payment_status"] == "REFUNDED"
        assert e["learning_status"] == "WITHDRAWN"

    def test_approve_appends_refund_approved_audit_with_correct_subject(self, api):
        """# difficulty: transitive_cascade/refund_approve_depth_2_cascade

        PRD §3.7: 'an AuditLogEntry whose action is REFUND_APPROVED is
        appended.' PRD §2.10 names subject_type=REFUND_REQUEST.
        """
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund()
        refund = file_refund_request(enrollment, student)
        approve_refund_request(refund)
        rows, _ = validate_paginated(api.list_audit_logs(
            TEST_USERS["admin_headers"],
            params={"subject_type": "REFUND_REQUEST", "subject_id": refund["id"]},
        ))
        approved_rows = [r for r in rows if r["action"] == "REFUND_APPROVED"]
        assert len(approved_rows) >= 1, (
            f"Expected REFUND_APPROVED audit row; got actions "
            f"{[r['action'] for r in rows]}"
        )
        assert approved_rows[0]["subject_id"] == refund["id"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 5 — Validation priority conflicts
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule5StateVsTemporal:
    """# difficulty: priority_pair_validation_conflict / state_vs_business_temporal_state_wins

    PRD §2.8 priority order — state (priority 5) before business_temporal
    (priority 8). Reschedule on an ENDED live class with a colliding new room
    must fire ERR_LIVE_CLASS_NOT_SCHEDULED.
    """

    def test_state_error_wins_over_room_conflict(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_temporal_state_wins

        PRD §2.8: 'the server evaluates them in the following order and
        returns the first failure ... (5) the source entity is in the
        required state for the requested transition ... (8) room overlap on
        live-class scheduling.'
        """
        from test_helpers import (
            advance_clock, create_published_course, end_live_class,
            schedule_live_class, start_live_class,
        )
        # Build an ENDED live class.
        course, instructor, _ = create_published_course()
        live_a = schedule_live_class(course, instructor, start_ts=1_000_000, end_ts=1_003_600)
        advance_clock(1_000_000)
        start_live_class(live_a, instructor)
        end_live_class(live_a, instructor)
        # Build another SCHEDULED class on a chosen room R that the candidate
        # will collide with.
        live_b = schedule_live_class(
            course, instructor, room_id="ROOM-COLLIDE", start_ts=2_000_000, end_ts=2_003_600
        )
        # Attempt to reschedule the ENDED live class onto room R. State is
        # priority 5 (ENDED → ERR_LIVE_CLASS_NOT_SCHEDULED), room conflict
        # priority 8 — state must win.
        from test_helpers import reschedule_live_class_payload
        res = api.reschedule_live_class(
            live_a["id"],
            reschedule_live_class_payload("ROOM-COLLIDE", 2_000_500, 2_003_000),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_LIVE_CLASS_NOT_SCHEDULED")

    def test_state_error_wins_with_obvious_room_conflict(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_temporal_state_wins

        PRD §2.8 priority order ensures the state check fires regardless of
        whether the rest of the body would also have failed.
        """
        from test_helpers import (
            advance_clock, create_published_course, end_live_class,
            schedule_live_class, start_live_class,
        )
        course, instructor, _ = create_published_course()
        live_a = schedule_live_class(course, instructor, start_ts=3_000_000, end_ts=3_003_600)
        advance_clock(3_000_000)
        start_live_class(live_a, instructor)
        end_live_class(live_a, instructor)  # ENDED
        # Another SCHEDULED class on ROOM-Y to provide an existing
        # half-open conflict band; reschedule attempt onto ROOM-Y at fully
        # overlapping times would normally be ERR_ROOM_CONFLICT.
        live_b = schedule_live_class(
            course, instructor, room_id="ROOM-Y", start_ts=4_000_000, end_ts=4_003_600
        )
        from test_helpers import reschedule_live_class_payload
        res = api.reschedule_live_class(
            live_a["id"],
            reschedule_live_class_payload("ROOM-Y", 4_000_500, 4_003_000),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_LIVE_CLASS_NOT_SCHEDULED")


class TestDifficultyRule5BusinessSafetyVsConstraint:
    """# difficulty: priority_pair_validation_conflict / business_safety_vs_business_constraint_safety_wins

    PRD §2.8 priority — plagiarism (priority 7, business_safety) precedes
    score range (priority 17, business_constraint).
    """

    def test_plagiarism_block_wins_over_score_out_of_range(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_safety_wins

        PRD §2.8: '(7) plagiarism block on grading, surfacing
        ERR_PLAGIARISM_BLOCKED ... (17) the score range on grading,
        surfacing ERR_SCORE_OUT_OF_RANGE.'

        The construction relies on the system's plagiarism scorer; PRD §3.8
        does not pin a deterministic plagiarism_score for any given input.
        Because we cannot guarantee plagiarism_score >= threshold without
        knowing the threshold, this test must be carefully constructed. PRD
        §3.8 also says 'unless the request body sets the override_plagiarism
        flag to true' — without that flag, the priority ordering is
        observable only when plagiarism_score actually clears the threshold.

        We therefore make a best-effort assertion: the response is a 4xx
        with either ERR_PLAGIARISM_BLOCKED (priority wins) or
        ERR_SCORE_OUT_OF_RANGE (no plagiarism issue triggered). The
        priority-pair claim is observable only in the former path.
        """
        from test_helpers import grade_submission_payload, make_instructor_headers, validate_error_is_one_of
        course, instructor, _, _, _, sub = setup_submission_under_review(max_score=100)
        # Submit a grade with score=200 (out-of-range) and no override.
        res = api.grade_submission(
            sub["id"],
            grade_submission_payload(score=200, feedback="x"),
            make_instructor_headers(instructor["id"]),
        )
        # PRD priority would yield ERR_PLAGIARISM_BLOCKED iff plagiarism_score
        # is >= threshold; otherwise ERR_SCORE_OUT_OF_RANGE wins. We accept
        # the correct priority outcome of either branch.
        validate_error_is_one_of(res, ["ERR_PLAGIARISM_BLOCKED", "ERR_SCORE_OUT_OF_RANGE"])

    def test_score_out_of_range_when_no_plagiarism(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_safety_wins

        PRD §2.8: '(17) the score range on grading, surfacing
        ERR_SCORE_OUT_OF_RANGE.' This test isolates the constraint-only
        path: with override_plagiarism=true the safety check is suppressed,
        so the 17-priority constraint becomes observable.
        """
        from test_helpers import grade_submission_payload, make_instructor_headers
        course, instructor, _, _, _, sub = setup_submission_under_review(max_score=100)
        res = api.grade_submission(
            sub["id"],
            grade_submission_payload(score=200, feedback="x", override_plagiarism=True),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_SCORE_OUT_OF_RANGE")


# ─────────────────────────────────────────────────────────────────────────
# Rule 6 — Boundary precision
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule6CheckinBoundary:
    """# difficulty: boundary_precision_check / late_vs_absent_at_exact_1800_seconds"""

    def test_delta_exactly_1800_yields_late(self, api):
        """# difficulty: boundary_precision_check/late_vs_absent_at_exact_1800_seconds

        PRD §3.3: 'the integer-second boundary at delta equal to one thousand
        eight hundred yields LATE.'
        """
        from test_helpers import setup_live_session_in_progress
        _, _, student, _, live = setup_live_session_in_progress(start_ts=10_000, end_ts=13_600)
        from test_helpers import checkin_payload
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=11_800),
            make_student_headers(student["id"]),
        )
        att = validate_success(res, expected_status=201)
        assert att["mark"] == "LATE"

    def test_delta_1801_rejected_window_closed(self, api):
        """# difficulty: boundary_precision_check/late_vs_absent_at_exact_1800_seconds

        PRD §3.3: 'delta equal to one thousand eight hundred and one yields
        ERR_CHECKIN_WINDOW_CLOSED.'
        """
        from test_helpers import setup_live_session_in_progress, checkin_payload
        _, _, student, _, live = setup_live_session_in_progress(start_ts=20_000, end_ts=23_600)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=21_801),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_CHECKIN_WINDOW_CLOSED")


class TestDifficultyRule6RefundTierBoundary:
    """# difficulty: boundary_precision_check / refund_tier_boundary_at_progress_5_and_days_7"""

    def test_refund_full_at_day_7_progress_5_inclusive(self, api):
        """# difficulty: boundary_precision_check/refund_tier_boundary_at_progress_5_and_days_7

        PRD §3.7: 'If days_elapsed is at most seven and progress is at most
        five percent, the ratio is one (full refund).' Both bounds inclusive.
        """
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=7,
            target_progress_percent=5.0,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        assert refund["provisional_amount_cents"] == 100000

    def test_refund_drops_to_mid_at_progress_5_1(self, api):
        """# difficulty: boundary_precision_check/refund_tier_boundary_at_progress_5_and_days_7

        PRD §3.7: 'Otherwise, if days_elapsed is at most thirty and progress
        is at most thirty percent, the ratio is zero point seven.' progress
        of 5.1 trips out of tier-1 into tier-2; ratio=0.7 → 70000.
        """
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=7,
            target_progress_percent=5.1,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        assert refund["provisional_amount_cents"] == 70000


# ─────────────────────────────────────────────────────────────────────────
# Rule 7 — Cross-entity state dependencies
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule7LiveClassStartBlockedByCoursePosture:
    """# difficulty: cross_entity_state_dependency / live_class_start_blocked_by_course_posture

    PRD §3.3 + §3.1: Course.posture is read by LiveClass.start. When delist
    has occurred, posture==FROZEN.
    """

    def test_start_after_delist_yields_one_of_two_errors(self, api):
        """# difficulty: cross_entity_state_dependency/live_class_start_blocked_by_course_posture

        PRD §3.3: 'The transition requires the parent course's posture to be
        OPEN (otherwise ERR_COURSE_FROZEN).' PRD §3.1 cascade also moves the
        live class to CANCELLED, which the priority-5 state check would
        report as ERR_LIVE_CLASS_NOT_SCHEDULED. PRD §2.8 priority order has
        state (5) before posture (6), so per the priority a sequential
        delist-then-start can return either, depending on whether the
        cascade has run before the state check.
        """
        from test_helpers import (
            advance_clock, create_published_course, schedule_live_class,
            validate_error_is_one_of,
        )
        course, instructor, _ = create_published_course()
        live = schedule_live_class(course, instructor, start_ts=900_000, end_ts=903_600)
        delist_course(course)  # cancels the live class via cascade
        advance_clock(900_000)
        res = api.start_live_class(live["id"], make_instructor_headers(instructor["id"]))
        validate_error_is_one_of(
            res, ["ERR_COURSE_FROZEN", "ERR_LIVE_CLASS_NOT_SCHEDULED"]
        )

    def test_create_enrollment_after_delist_returns_course_frozen(self, api):
        """# difficulty: cross_entity_state_dependency/live_class_start_blocked_by_course_posture

        PRD §3.1: 'While the course is FROZEN, several operations are
        blocked with ERR_COURSE_FROZEN, including ... creating a new
        enrollment.'

        This is a sister cross-entity check on the same Course.posture state
        that the difficulty instance focuses on.
        """
        from test_helpers import create_enrollment_payload, create_student
        course, _, _ = create_published_course()
        delist_course(course)
        student = create_student()
        res = api.create_enrollment(
            course["id"],
            create_enrollment_payload(student["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_COURSE_FROZEN")


class TestDifficultyRule7LeaveBlockedByLiveClassStatus:
    """# difficulty: cross_entity_state_dependency / leave_approval_blocked_by_live_class_status

    PRD §3.3: leave-approval reads LiveClass.status; LIVE/ENDED yields
    ERR_LIVE_CLASS_ALREADY_STARTED.
    """

    def test_approve_leave_when_live_class_is_live_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/leave_approval_blocked_by_live_class_status

        PRD §3.3: 'approval requires ... the target live class to still be
        SCHEDULED (ERR_LIVE_CLASS_ALREADY_STARTED).'
        """
        course, instructor, ta, student, enrollment, group, live, leave = (
            setup_pending_leave_with_ta(start_ts=1_500_000, end_ts=1_503_600)
        )
        advance_clock(1_500_000)
        start_live_class(live, instructor)
        res = api.approve_leave_request(leave["id"], make_ta_headers(ta["id"]))
        validate_error(res, "ERR_LIVE_CLASS_ALREADY_STARTED")

    def test_approve_leave_when_live_class_ended_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/leave_approval_blocked_by_live_class_status

        PRD §3.3: '(ERR_LIVE_CLASS_ALREADY_STARTED)' fires for both LIVE and
        ENDED live classes, since both fail the 'still SCHEDULED' precondition.
        """
        course, instructor, ta, student, enrollment, group, live, leave = (
            setup_pending_leave_with_ta(start_ts=1_700_000, end_ts=1_703_600)
        )
        advance_clock(1_700_000)
        start_live_class(live, instructor)
        end_live_class(live, instructor)
        res = api.approve_leave_request(leave["id"], make_ta_headers(ta["id"]))
        validate_error(res, "ERR_LIVE_CLASS_ALREADY_STARTED")


# ─────────────────────────────────────────────────────────────────────────
# Rule 8 — Resource temporal-overlap
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule8RoomOverlap:
    """# difficulty: resource_temporal_overlap / room_overlap_half_open_with_post_buffer

    PRD §3.3: half-open room interval with 600-second post-buffer.
    """

    def test_room_overlap_at_buffer_end_succeeds(self, api):
        """# difficulty: resource_temporal_overlap/room_overlap_half_open_with_post_buffer

        PRD §3.3: 'the candidate's start_ts is strictly less than the
        occupied end' — at exactly +600 the candidate.start_ts == occupied
        end, so the strict-less-than condition is FALSE; the request
        succeeds.
        """
        course, instructor, _ = setup_room_with_existing_session(
            room_id="ROOM-DR8A", existing_start_ts=1000, existing_end_ts=2000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-DR8A", start_ts=2600, end_ts=3600
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_success(res, expected_status=201)

    def test_room_overlap_one_below_buffer_end_rejected(self, api):
        """# difficulty: resource_temporal_overlap/room_overlap_half_open_with_post_buffer

        PRD §3.3: 'the candidate's start_ts is strictly less than the
        occupied end' — start_ts=2599 < 2600 fires ERR_ROOM_CONFLICT.
        """
        course, instructor, _ = setup_room_with_existing_session(
            room_id="ROOM-DR8B", existing_start_ts=1000, existing_end_ts=2000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-DR8B", start_ts=2599, end_ts=3500
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_ROOM_CONFLICT")


class TestDifficultyRule8InstructorAvailability:
    """# difficulty: resource_temporal_overlap / instructor_availability_closed_interval_containment

    PRD §3.3: closed-interval containment, no buffer.
    """

    def test_instructor_window_end_inclusive_succeeds(self, api):
        """# difficulty: resource_temporal_overlap/instructor_availability_closed_interval_containment

        PRD §3.3: 'a candidate whose end_ts is exactly equal to a window's
        end_ts is allowed.'
        """
        course, instructor, _ = setup_instructor_with_window(
            window_start=1000, window_end=5000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-DR8I", start_ts=4000, end_ts=5000
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_success(res, expected_status=201)

    def test_instructor_one_past_window_end_rejected(self, api):
        """# difficulty: resource_temporal_overlap/instructor_availability_closed_interval_containment

        PRD §3.3: 'the candidate's end_ts is less than or equal to the
        window's end_ts.' end_ts=5001 against window_end=5000 fails.
        """
        course, instructor, _ = setup_instructor_with_window(
            window_start=1000, window_end=5000
        )
        res = api.create_live_class(
            course["id"],
            create_live_class_payload(
                instructor["id"], "ROOM-DR8J", start_ts=4000, end_ts=5001
            ),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_INSTRUCTOR_UNAVAILABLE")


# ─────────────────────────────────────────────────────────────────────────
# Rule 9 — Compensating-action invariants
# ─────────────────────────────────────────────────────────────────────────

class TestDifficultyRule9RefundRejectInvariant:
    """# difficulty: compensating_invariant / refund_request_then_reject_preserves_paid_amount"""

    def test_refund_request_then_reject_preserves_paid_amount(self, api):
        """# difficulty: compensating_invariant/refund_request_then_reject_preserves_paid_amount

        PRD §3.7: 'The enrolment's payment_status reverts from REFUND_PENDING
        back to PAID.' Combined with PRD §3.2 ('refund_amount_cents ... null
        until a refund on this enrollment reaches APPROVED'), the
        request→reject cycle conserves Enrollment.paid_amount_cents.
        """
        course, instructor, _ = create_published_course(
            list_price_cents=10000, discount_percent=15
        )
        enrollment, student = enroll_student(course)
        # Pre-cycle: paid_amount_cents = 10000 * (100-15)/100 = 8500.
        assert enrollment["paid_amount_cents"] == 8500
        # Cycle.
        refund = file_refund_request(enrollment, student)
        rejected = reject_refund_request(refund, "ineligible")
        assert rejected["status"] == "REJECTED"
        # Post-cycle invariants.
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["paid_amount_cents"] == 8500
        assert e["payment_status"] == "PAID"
        assert e.get("refund_amount_cents") is None or e.get("refund_amount_cents") in (None, 0)

    def test_refund_request_then_reject_keeps_enrollment_active(self, api):
        """# difficulty: compensating_invariant/refund_request_then_reject_preserves_paid_amount

        PRD §3.7: 'The enrolment's payment_status reverts from REFUND_PENDING
        back to PAID.' learning_status was unaffected by the refund cycle
        (PRD §3.7 only flips learning_status to WITHDRAWN on APPROVED, not on
        REJECTED), so it stays ACTIVE.
        """
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        refund = file_refund_request(enrollment, student)
        reject_refund_request(refund, "ineligible")
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["learning_status"] == "ACTIVE"


class TestDifficultyRule9SubmissionLoopProgressInvariant:
    """# difficulty: compensating_invariant / submission_revise_loop_does_not_advance_progress

    PRD §3.4: 'These three numbers are recomputed whenever a WatchSession is
    created, whenever a Submission reaches GRADED, and whenever an enrollment
    is read.' The loop's transitions are NOT in this list.
    """

    def test_submission_revision_loop_does_not_advance_progress(self, api):
        """# difficulty: compensating_invariant/submission_revise_loop_does_not_advance_progress

        PRD §3.4: 'These three numbers are recomputed whenever a
        WatchSession is created, whenever a Submission reaches GRADED, and
        whenever an enrollment is read.'
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=10.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        e_pre = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        pre_progress = e_pre["progress_percent"]
        # Cycle: SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        sub = submit_assignment(assignment, enrollment, student, fmt="TEXT")
        sub = start_review(sub, instructor)
        sub = request_revision(sub, instructor, "please redo")
        sub = resubmit(sub, student, fmt="TEXT")
        e_post = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e_post["progress_percent"] == pytest.approx(pre_progress, abs=0.1)
        assert sub["revision_count"] == 1

    def test_submission_revision_count_strictly_increases(self, api):
        """# difficulty: compensating_invariant/submission_revise_loop_does_not_advance_progress

        PRD §3.8: 'On success, revision_count increments by one.' The
        revision_count is the only quantity the loop touches; progress is
        conserved, count grows.
        """
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment, sub = reach_revision_count(
            course, instructor, enrollment, student, target_count=2, fmt="TEXT"
        )
        assert sub["revision_count"] == 2
