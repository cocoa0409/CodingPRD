"""School compliance posture: composite weighted scoring, the overdue-review
cap, training-coverage rounding, and the clock-advance cascade
(PRD §2.4, §2.5, §2.8, §2.10, §3.1)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_plan,
    add_accommodation,
    assert_audit_event,
    create_draft_plan,
    create_school,
    create_staff,
    create_student_for,
    file_grievance,
    get_school_posture_snapshot,
    get_success_data,
    make_coordinator_headers,
    make_teacher_headers,
    pipeline_to_determination,
    schedule_review,
    set_clock,
    setup_active_plan,
    setup_school_with_staff,
    submit_referral,
    train_staff,
    validate_error,
    validate_success,
)


class TestPostureGrievanceWeightBoundary:
    def test_posture_derivation_grievance_weight_boundary(self, api):
        """PRD §2.10: "Each open grievance at the school — one whose status is
        `FILED`, `INFORMAL_RESOLUTION`, or `FORMAL_INVESTIGATION` — contributes
        20 points." and "A composite score of 60 or more, or any nonzero
        OCR-escalation contribution, yields `AUDIT_HOLD`. Otherwise, a composite
        score of 30 or more yields `PROBATION`. Below that, the school is
        `OPERATIONAL`. The score itself is an integer. A computed snapshot is
        available per school, reporting `posture`, `training_coverage_pct`,
        `open_grievance_count`, `overdue_review_count`, and `composite_score`."

        Design: Corner/calculations/posture_derivation_grievance_weight_boundary
        """
        ctx = setup_school_with_staff()
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        school_id = ctx["school"]["id"]
        file_grievance(student["id"], parent_ref="p", description="G1")
        s1 = get_school_posture_snapshot(school_id)
        assert s1["composite_score"] == 20, f"one open grievance contributes 20, got {s1['composite_score']}"
        assert s1["posture"] == "OPERATIONAL", "20 is below the PROBATION threshold of 30"
        file_grievance(student["id"], parent_ref="p", description="G2")
        s2 = get_school_posture_snapshot(school_id)
        assert s2["composite_score"] == 40, f"two open grievances contribute 40, got {s2['composite_score']}"
        assert s2["posture"] == "PROBATION", "40 >= 30 yields PROBATION"


class TestPostureOverdueReviewCap:
    def test_posture_overdue_review_cap_at_30(self, api):
        """PRD §2.10: "Each review event at the school in `OVERDUE` status
        contributes 15 points, with the total overdue-review contribution capped
        at 30 points."
        PRD §2.10: "A composite score of 60 or more, or any nonzero
        OCR-escalation contribution, yields `AUDIT_HOLD`. Otherwise, a composite
        score of 30 or more yields `PROBATION`. Below that, the school is
        `OPERATIONAL`."

        Design: Corner/calculations/posture_overdue_review_cap_at_30
        """
        # Three plans (three students), each with an ANNUAL review scheduled for
        # 2026-08-01; clock advance to 2026-08-20 flips all three OVERDUE.
        ctx1 = setup_active_plan(school_name="Cap School", activate_at="2025-08-01T00:00:00Z")
        co = ctx1["coordinator"]
        school_id = ctx1["school"]["id"]
        teacher = ctx1["teacher"]
        ctxs = [ctx1]
        for i in (2, 3):
            student = create_student_for(school_id, co["id"], student_external_ref=f"STU-C{i}")
            referral = submit_referral(student["id"], teacher["id"], role="Teacher")
            evaluation = pipeline_to_determination(student["id"], referral, co["id"])
            plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
            add_accommodation(plan["id"], co["id"], applies_to_testing=False)
            plan = activate_plan(plan["id"], co["id"])
            ctxs.append({"plan": plan, "student": student})
        for c in ctxs:
            schedule_review(c["plan"]["id"], co["id"], "2026-08-01T00:00:00Z", review_type="ANNUAL")
        set_clock("2026-08-20T00:00:00Z")  # 19 days past scheduled_for — beyond the 14-day grace
        summary = get_school_posture_snapshot(school_id)
        assert summary["overdue_review_count"] == 3, (
            f"three reviews must be OVERDUE, got {summary['overdue_review_count']}"
        )
        assert summary["composite_score"] == 30, (
            f"the overdue-review contribution is capped at 30 (3 * 15 = 45 -> 30), "
            f"got {summary['composite_score']}"
        )
        assert summary["posture"] == "PROBATION", "composite 30 (>= 30, < 60) yields PROBATION"


class TestPostureCompositeWeightedScoring:
    def test_school_posture_composite_weighted_scoring_mode_a(self, api):
        """PRD §2.10: "Each open grievance at the school — one whose status is
        `FILED`, `INFORMAL_RESOLUTION`, or `FORMAL_INVESTIGATION` — contributes
        20 points." and "Each review event at the school in `OVERDUE` status
        contributes 15 points, with the total overdue-review contribution capped
        at 30 points." and "A composite score of 60 or more, or any nonzero
        OCR-escalation contribution, yields `AUDIT_HOLD`. Otherwise, a composite
        score of 30 or more yields `PROBATION`."
        PRD §2.10: "A computed snapshot is available per school, reporting
        `posture`, `training_coverage_pct`, `open_grievance_count`,
        `overdue_review_count`, and `composite_score`."

        Design: Difficulty/combinatorial_formula/school_posture_composite_weighted_scoring_mode_a
        """
        # Plan effective 2025-08-01; ANNUAL review scheduled 2026-08-01; one
        # open grievance (FILED). Clock advance to 2026-08-20 flips the review
        # OVERDUE: composite = 20 + min(1 * 15, 30) = 35 -> PROBATION.
        ctx = setup_active_plan(school_name="Posture School",
                                activate_at="2025-08-01T00:00:00Z")
        co = ctx["coordinator"]
        grievance = file_grievance(ctx["student"]["id"], parent_ref="parent-P",
                                   description="Accommodation not delivered")
        review = schedule_review(ctx["plan"]["id"], co["id"], "2026-08-01T00:00:00Z",
                                 review_type="ANNUAL")
        set_clock("2026-08-20T00:00:00Z")
        summary = get_school_posture_snapshot(ctx["school"]["id"], co["id"])
        assert summary["composite_score"] == 35, (
            f"20 (grievance) + 15 (overdue, under the 30 cap) = 35, got {summary['composite_score']}"
        )
        assert summary["posture"] == "PROBATION", "35 (>= 30, < 60) yields PROBATION"
        grievance_after = validate_success(api.get_grievance(
            grievance["id"], make_coordinator_headers(co["id"])
        ))
        assert grievance_after["grievance_status"] == "FILED"
        review_after = validate_success(api.get_review(review["id"], make_coordinator_headers(co["id"])))
        assert review_after["review_status"] == "OVERDUE"

    def test_school_posture_snapshot_reports_all_fields(self, api):
        """PRD §2.10: "A computed snapshot is available per school, reporting
        `posture`, `training_coverage_pct`, `open_grievance_count`,
        `overdue_review_count`, and `composite_score`."

        Design: Difficulty/combinatorial_formula/school_posture_composite_weighted_scoring_mode_a
        """
        ctx = setup_active_plan(school_name="Posture School",
                                activate_at="2025-08-01T00:00:00Z")
        co = ctx["coordinator"]
        file_grievance(ctx["student"]["id"], parent_ref="parent-P")
        schedule_review(ctx["plan"]["id"], co["id"], "2026-08-01T00:00:00Z", review_type="ANNUAL")
        set_clock("2026-08-20T00:00:00Z")
        summary = get_school_posture_snapshot(ctx["school"]["id"], co["id"])
        assert summary["open_grievance_count"] == 1
        assert summary["overdue_review_count"] == 1
        assert summary["posture"] == "PROBATION"
        assert summary["composite_score"] == 35
        assert summary["training_coverage_pct"] == 100.0, (
            "all active staff are trained in this fixture — coverage must be 100.0"
        )


class TestTrainingCoverageRounding:
    def test_training_coverage_rounding_then_threshold_mode_b(self, api):
        """PRD §3.1: "From these records the system computes each school's
        training coverage: among active staff (`is_active` true) at the school,
        the fraction whose `current_training_status` is `TRAINED_CURRENT`,
        multiplied by 100 and rounded half-up to 2 decimal places; a school with
        no active staff is treated as fully covered (a ratio of 1.0)."
        PRD §2.10: "If the school's staff training coverage ratio (§3.1) falls
        below 0.95 — strictly less than ninety-five percent — a further 25
        points are contributed."

        Design: Difficulty/combinatorial_formula/training_coverage_rounding_then_threshold_mode_b
        """
        set_clock("2026-01-01T00:00:00Z")
        school = create_school(school_name="Rounding School", district_code="D03")
        staff = []
        for i in range(1, 21):
            staff.append(create_staff(school["id"], "TEACHER",
                                      staff_external_ref=f"S-{i:02d}", full_name=f"Staff {i:02d}"))
        for s in staff:
            train_staff(s["id"], "2026-01-01T00:00:00Z")
        summary0 = get_school_posture_snapshot(school["id"])
        assert summary0["training_coverage_pct"] == 100.0, (
            f"20/20 trained must report 100.0, got {summary0['training_coverage_pct']}"
        )
        # 20/21 = 0.952380... -> 95.24 (>= 95: no training gap).
        create_staff(school["id"], "TEACHER", staff_external_ref="S-21", full_name="Staff 21")
        summary21 = get_school_posture_snapshot(school["id"])
        assert summary21["training_coverage_pct"] == 95.24, (
            f"20/21 rounded half-up to 2dp must be 95.24, got {summary21['training_coverage_pct']}"
        )
        # 20/22 = 0.909090... -> 90.91 (< 95: training gap engages).
        create_staff(school["id"], "TEACHER", staff_external_ref="S-22", full_name="Staff 22")
        summary22 = get_school_posture_snapshot(school["id"])
        assert summary22["training_coverage_pct"] == 90.91, (
            f"20/22 rounded half-up to 2dp must be 90.91, got {summary22['training_coverage_pct']}"
        )

    def test_training_gap_threshold_flips_composite_not_posture(self, api):
        """PRD §2.10: "If the school's staff training coverage ratio (§3.1)
        falls below 0.95 — strictly less than ninety-five percent — a further 25
        points are contributed." and "A composite score of 60 or more, or any
        nonzero OCR-escalation contribution, yields `AUDIT_HOLD`. Otherwise, a
        composite score of 30 or more yields `PROBATION`. Below that, the school
        is `OPERATIONAL`."

        Design: Difficulty/combinatorial_formula/training_coverage_rounding_then_threshold_mode_b
        """
        set_clock("2026-01-01T00:00:00Z")
        school = create_school(school_name="Rounding School", district_code="D03")
        staff = []
        for i in range(1, 21):
            staff.append(create_staff(school["id"], "TEACHER",
                                      staff_external_ref=f"S-{i:02d}", full_name=f"Staff {i:02d}"))
        for s in staff:
            train_staff(s["id"], "2026-01-01T00:00:00Z")
        create_staff(school["id"], "TEACHER", staff_external_ref="S-21", full_name="Staff 21")
        summary21 = get_school_posture_snapshot(school["id"])
        assert summary21["composite_score"] == 0, (
            "95.24 is not strictly below ninety-five percent — no training-gap contribution"
        )
        assert summary21["posture"] == "OPERATIONAL"
        create_staff(school["id"], "TEACHER", staff_external_ref="S-22", full_name="Staff 22")
        summary22 = get_school_posture_snapshot(school["id"])
        assert summary22["composite_score"] == 25, (
            f"90.91 is strictly below ninety-five percent — a further 25 points, got {summary22['composite_score']}"
        )
        assert summary22["posture"] == "OPERATIONAL", "composite 25 is below the PROBATION threshold of 30"


class TestClockAdvanceCascade:
    def _setup_two_overdue_reviews_and_grievances(self, api):
        """School with two ACTIVE plans, each carrying an ANNUAL review
        scheduled for 2026-08-01, plus two open grievances. Clock not yet
        advanced past the grace window."""
        ctx1 = setup_active_plan(school_name="Cascade School",
                                 activate_at="2025-08-01T00:00:00Z")
        co = ctx1["coordinator"]
        school_id = ctx1["school"]["id"]
        teacher = ctx1["teacher"]
        review1 = schedule_review(ctx1["plan"]["id"], co["id"], "2026-08-01T00:00:00Z",
                                  review_type="ANNUAL")
        student2 = create_student_for(school_id, co["id"], student_external_ref="STU-K2")
        referral2 = submit_referral(student2["id"], teacher["id"], role="Teacher")
        evaluation2 = pipeline_to_determination(student2["id"], referral2, co["id"])
        plan2 = create_draft_plan(student2["id"], evaluation2["id"], co["id"])
        add_accommodation(plan2["id"], co["id"], applies_to_testing=False)
        plan2 = activate_plan(plan2["id"], co["id"])
        review2 = schedule_review(plan2["id"], co["id"], "2026-08-01T00:00:00Z",
                                  review_type="ANNUAL")
        griev1 = file_grievance(ctx1["student"]["id"], parent_ref="parent-1", description="G1")
        griev2 = file_grievance(student2["id"], parent_ref="parent-2", description="G2")
        return ctx1, review1, review2, griev1, griev2, student2

    def test_clock_advance_cascade_review_overdue_posture_flip_mutation_blocked(self, api):
        """PRD §2.5: "Advancing the clock is itself a trigger: after each
        advance the server flips any review still sitting in `SCHEDULED` past
        its grace window to `OVERDUE` (emitting a `REVIEW_OVERDUE` event),
        expires any `TRAINED_CURRENT` training status whose validity has passed
        (emitting `TRAINING_LAPSED`), and recomputes every affected school's
        compliance posture (emitting `POSTURE_CHANGED` where the posture
        moved)."
        PRD §2.8: "4. The school posture gate — a mutation scoped under a school
        whose `school_posture` is `AUDIT_HOLD` is rejected with
        `ERR_SCHOOL_UNDER_AUDIT_HOLD` (HTTP 409) before any deeper rule runs."

        Design: Difficulty/transitive_cascade/clock_advance_cascade_review_overdue_posture_flip_mutation_blocked
        """
        (ctx, review1, review2, _g1, _g2, student2) = (
            self._setup_two_overdue_reviews_and_grievances(api)
        )
        co = ctx["coordinator"]
        school_id = ctx["school"]["id"]
        # 2 open grievances (40) + 2 reviews flipping OVERDUE (min(2*15,30)=30) = 70.
        set_clock("2026-08-20T00:00:00Z")
        co_headers = make_coordinator_headers(co["id"])
        for review in (review1, review2):
            after = validate_success(api.get_review(review["id"], co_headers))
            assert after["review_status"] == "OVERDUE", (
                f"review {review['id']} must flip SCHEDULED -> OVERDUE past the grace window"
            )
        summary = get_school_posture_snapshot(school_id)
        assert summary["composite_score"] == 70, (
            f"40 grievance + 30 overdue (at the cap) = 70, got {summary['composite_score']}"
        )
        assert summary["posture"] == "AUDIT_HOLD", "composite 70 (>= 60) yields AUDIT_HOLD"
        # Level 3: the posture gate blocks a school-scoped mutation.
        resp = api.create_referral(
            {"student_id": ctx["student"]["id"], "referral_reason": "r-after-hold",
             "suspected_disability_category": "OTHER"},
            make_teacher_headers(ctx["teacher"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_UNDER_AUDIT_HOLD)

    def test_clock_advance_emits_review_overdue_and_posture_changed_events(self, api):
        """PRD §2.5: "Advancing the clock is itself a trigger: after each
        advance the server flips any review still sitting in `SCHEDULED` past
        its grace window to `OVERDUE` (emitting a `REVIEW_OVERDUE` event),
        expires any `TRAINED_CURRENT` training status whose validity has passed
        (emitting `TRAINING_LAPSED`), and recomputes every affected school's
        compliance posture (emitting `POSTURE_CHANGED` where the posture
        moved)."
        PRD §2.4: "The audit listing is filterable by `school_id`,
        `event_type`, and `entity_ref`."

        Design: Difficulty/transitive_cascade/clock_advance_cascade_review_overdue_posture_flip_mutation_blocked
        """
        (ctx, review1, review2, _g1, _g2, _s2) = (
            self._setup_two_overdue_reviews_and_grievances(api)
        )
        school_id = ctx["school"]["id"]
        set_clock("2026-08-20T00:00:00Z")
        director_headers = TEST_USERS["director_headers"]
        for review in (review1, review2):
            events = get_success_data(api.list_audit_events(
                director_headers,
                params={"school_id": school_id, "event_type": "REVIEW_OVERDUE",
                        "entity_ref": review["id"]},
            ))
            assert len(events) == 1, (
                f"exactly one REVIEW_OVERDUE event must be recorded per flipped review, "
                f"got {len(events)} for {review['id']}"
            )
            assert_audit_event(events[0])
        posture_events = get_success_data(api.list_audit_events(
            director_headers,
            params={"school_id": school_id, "event_type": "POSTURE_CHANGED"},
        ))
        assert len(posture_events) >= 1, (
            "the posture move to AUDIT_HOLD must be recorded as POSTURE_CHANGED"
        )


class TestAuditTrail:
    def test_audit_event_immutable_no_update_endpoint(self, api):
        """PRD §2.4: "The one exception is the `ComplianceAuditEvent`, the
        system's append-only compliance ledger. Audit events are created by the
        server as side effects of workflow actions and are never modified
        afterward; consequently an audit event carries only `id` and
        `created_at` — both `updated_at` and `version` are absent. Each event
        records the `school_id` of the school it belongs to, an `event_type`
        drawn from a fixed vocabulary, an `entity_ref` holding the `id` of the
        entity the event pertains to, an `actor_staff_id` identifying the acting
        `StaffMember` (null when the system itself acted), and an
        `event_payload` object with event-specific structured details."

        Design: Corner/entities/audit_event_immutable_no_update_endpoint
        """
        ctx = setup_school_with_staff()
        student = create_student_for(ctx["school"]["id"], ctx["coordinator"]["id"])
        file_grievance(student["id"], parent_ref="p")  # emits GRIEVANCE_FILED
        events = get_success_data(api.list_audit_events(
            TEST_USERS["director_headers"],
            params={"school_id": ctx["school"]["id"]},
        ))
        assert isinstance(events, list) and len(events) >= 1, (
            "filing a grievance must append at least one audit event"
        )
        for event in events:
            assert_audit_event(event)
