"""Readiness scoring, dual-variant percentages, and the deadline sweep.

PRD §3.2 (alignment, readiness), §3.4 (milestone percentage variants), §3.6
(work-based-learning percentage), §3.8 (ops runs), §2.5 (logical clock).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId, add_completed_enrollment, add_enrollment,
    assert_ops_run, assert_pct, assert_plan, complete_milestone,
    complete_placement, confirm_placement, create_active_plan,
    create_advisor, create_application, create_application_with_milestones,
    create_pathway, create_placement, create_site, create_student,
    get_plan, make_advisor_headers, make_student_headers,
    pass_certification, set_clock, setup_student_with_active_plan,
    transition_application, validate_success, waive_milestone,
)

ADMIN = TEST_USERS["district_admin_headers"]
DEADLINE = "2026-06-15T00:00:00Z"


class TestAlignmentVariants:
    """Difficulty instance: PROVISIONAL includes PLANNED/ENROLLED, OFFICIAL
    counts COMPLETED only."""

    def _setup_alignment(self):
        advisor = create_advisor(full_name="A One", max_caseload=50)
        pathway = create_pathway(pathway_code="STEM",
                                 required_course_codes=["MATH101", "ENG101"])
        student = create_student(student_ref="S001", full_name="Stu One",
                                 grade_level=12, advisor_id=advisor["id"])
        plan = create_active_plan(student, pathway["id"], advisor["id"])
        add_completed_enrollment(student["id"], plan["id"], advisor["id"],
                                 "MATH101", 4, "A")
        add_enrollment(student["id"], plan["id"], advisor["id"], "ENG101", 4,
                       term="2026-FALL")
        return advisor, plan

    def test_alignment_provisional_vs_official(self, api):
        """PRD §3.2: "The provisional variant — stored as
        `alignment_provisional_pct` and used by the forward-looking advising
        view — counts `PLANNED`, `ENROLLED`, and `COMPLETED` enrollments as
        covering; the official variant — `alignment_official_pct`, the audit
        and graduation view — counts `COMPLETED` enrollments only."

        Design: Difficulty/dual_variant_calc/plan_alignment_provisional_vs_official
        """
        advisor, plan = self._setup_alignment()
        data = get_plan(plan["id"])
        assert_plan(data)
        assert_pct(data["alignment_provisional_pct"], 100.0)
        assert_pct(data["alignment_official_pct"], 50.0)

    def test_readiness_variants_follow_alignment(self, api):
        """PRD §3.2: "`readiness_provisional` uses
        `alignment_provisional_pct`, and `readiness_official` uses
        `alignment_official_pct`, while both share the strict
        `milestone_pct`, the `wbl_hours_pct`, and the `certification_points`."
        PRD §3.2: "for a twelfth-grader the alignment, milestone,
        work-based-learning, and certification weights are 0.30, 0.40, 0.20,
        and 0.10 respectively". PRD §3.4: "An empty denominator yields 100 by
        convention".

        Design: Difficulty/dual_variant_calc/plan_alignment_provisional_vs_official
        """
        advisor, plan = self._setup_alignment()
        data = get_plan(plan["id"])
        # No applications -> milestone_pct 100; pathway needs no hours or
        # certification -> both 100 by convention.
        assert_pct(data["readiness_provisional"], 100.0)
        assert_pct(data["readiness_official"], 85.0)  # 50*.30+100*.40+100*.20+100*.10


class TestMilestonePctVariants:
    """Difficulty instance: STRICT removes WAIVED from the denominator,
    LENIENT counts WAIVED as completed."""

    def _setup_milestone_pool(self, api):
        ctx = setup_student_with_active_plan(
            pathway_overrides={"pathway_code": "TRADE", "name": "Trades"})
        student = ctx["student"]
        advisor_id = ctx["advisor"]["id"]
        app, seeded = create_application_with_milestones(student)
        complete_milestone(seeded[0]["id"], student)
        complete_milestone(seeded[1]["id"], student)
        waive_milestone(seeded[2]["id"], advisor_id)
        api.create_milestone(
            app["id"],
            {"kind": "INTERVIEW", "due_at": "2026-06-01T00:00:00Z"},
            make_student_headers(student["id"]),
        )
        return ctx, app

    def test_milestone_pct_strict_excludes_waived(self, api):
        """PRD §3.4: "The strict variant — the one stored as `milestone_pct`
        and fed into both readiness scores — removes `WAIVED` milestones from
        the denominator and counts only `COMPLETED` milestones in the
        numerator".

        Design: Difficulty/dual_variant_calc/milestone_pct_strict_vs_lenient
        """
        ctx, app = self._setup_milestone_pool(api)
        data = get_plan(ctx["plan"]["id"])
        assert_pct(data["milestone_pct"], 66.67)  # 2 COMPLETED / (4 - 1 WAIVED)

    def test_milestone_pct_lenient_counts_waived(self, api):
        """PRD §3.4: "the lenient variant divides by the full pool and counts
        `COMPLETED` and `WAIVED` together." PRD §3.4: "The lenient figure is
        exposed only on the single-plan read as `milestone_pct_lenient`, a
        display-only number for advising dashboards that never feeds
        readiness."

        Design: Difficulty/dual_variant_calc/milestone_pct_strict_vs_lenient
        """
        ctx, app = self._setup_milestone_pool(api)
        data = get_plan(ctx["plan"]["id"])
        assert_pct(data["milestone_pct_lenient"], 75.0)  # 3 / 4
        assert data["milestone_pct"] != data["milestone_pct_lenient"], (
            "STRICT and LENIENT must diverge for this milestone data"
        )


class TestReadinessBandFormula:
    """Difficulty instance: 4-input weighted formula with grade-12 band and
    post-rounding cap."""

    def _setup_readiness(self, api):
        advisor = create_advisor(full_name="A Four", max_caseload=50)
        pathway = create_pathway(pathway_code="HEALTH", name="Health Sciences",
                                 required_course_codes=["BIO201"],
                                 required_certification_code="CNA",
                                 required_work_hours=40)
        student = create_student(student_ref="S201", full_name="Stu Health",
                                 grade_level=12, advisor_id=advisor["id"])
        plan = create_active_plan(student, pathway["id"], advisor["id"])
        add_enrollment(student["id"], plan["id"], advisor["id"], "BIO201", 4)
        app, seeded = create_application_with_milestones(student)
        complete_milestone(seeded[0]["id"], student)
        complete_milestone(seeded[1]["id"], student)
        api.create_milestone(
            app["id"],
            {"kind": "INTERVIEW", "due_at": "2026-06-01T00:00:00Z"},
            make_student_headers(student["id"]),
        )
        site = create_site(site_code="HOSP1", name="General Hospital")
        placement = create_placement(student["id"], site["id"],
                                     "2026-04-01T00:00:00Z",
                                     "2026-06-01T00:00:00Z", 10)
        confirm_placement(placement["id"])
        complete_placement(placement["id"], 20)
        pass_certification(student["id"], "OSHA",
                           exam_at="2026-05-10T09:00:00Z")
        return advisor, plan

    def test_readiness_components(self, api):
        """PRD §3.2: "Second, the four component percentages are computed."
        PRD §3.6: "a `PASSED` certification in any other code earns partial
        credit of 50". PRD §3.6: "otherwise it is 100 times the earned hours
        divided by the required hours, rounded half-up to 2 decimal places and
        capped at 100 after rounding."

        Design: Difficulty/combinatorial_formula/readiness_weighted_band_formula
        """
        advisor, plan = self._setup_readiness(api)
        data = get_plan(plan["id"])
        assert_plan(data)
        assert_pct(data["alignment_provisional_pct"], 100.0)  # BIO201 PLANNED
        assert_pct(data["alignment_official_pct"], 0.0)       # none COMPLETED
        assert_pct(data["milestone_pct"], 50.0)               # 2 of 4
        assert_pct(data["wbl_hours_pct"], 50.0)               # 20 / 40
        assert data["certification_points"] == 50             # OSHA, not CNA

    def test_readiness_weighted_sum(self, api):
        """PRD §3.2: "First the grade band resolves the weights: for a
        twelfth-grader the alignment, milestone, work-based-learning, and
        certification weights are 0.30, 0.40, 0.20, and 0.10 respectively ...
        Third, the weighted sum is formed — each component multiplied by its
        weight and the products added. Fourth, the sum is rounded half-up to 2
        decimal places. Fifth and finally, the score is capped at 100, the cap
        landing after rounding."

        Design: Difficulty/combinatorial_formula/readiness_weighted_band_formula
        """
        advisor, plan = self._setup_readiness(api)
        data = get_plan(plan["id"])
        # 100*.30 + 50*.40 + 50*.20 + 50*.10
        assert_pct(data["readiness_provisional"], 65.0)
        # 0*.30 + 50*.40 + 50*.20 + 50*.10
        assert_pct(data["readiness_official"], 35.0)


class TestWblCap:
    def test_wbl_hours_capped_at_100(self, api):
        """PRD §3.6: "when the pathway requires no hours the percentage is 100
        by convention, and otherwise it is 100 times the earned hours divided
        by the required hours, rounded half-up to 2 decimal places and capped
        at 100 after rounding." PRD §2.10: "Where a cap applies (readiness and
        work-based-learning progress are capped at 100), the cap is applied
        after rounding, never before."

        Design: Corner/calculations/wbl_hours_capped_at_100
        """
        advisor = create_advisor(max_caseload=10)
        pathway = create_pathway(pathway_code="WBL40", required_work_hours=40)
        student = create_student(student_ref="WH1", advisor_id=advisor["id"])
        plan = create_active_plan(student, pathway["id"], advisor["id"])
        site = create_site(site_code="WHS", max_concurrent_placements=5)
        placement = create_placement(student["id"], site["id"],
                                     "2026-04-01T00:00:00Z",
                                     "2026-05-01T00:00:00Z", 12)
        confirm_placement(placement["id"])
        complete_placement(placement["id"], 45)

        data = get_plan(plan["id"])
        assert_pct(data["wbl_hours_pct"], 100.0)
        assert data["wbl_hours_pct"] <= 100.0, "raw 112.5 must not leak"


class TestOpsRunRegression:
    """Difficulty instance: depth-3 chain — sweep flips milestone MISSED,
    which regresses the READY application, which recomputes the plan."""

    def _setup_regression(self, api):
        ctx = setup_student_with_active_plan(
            pathway_overrides={"pathway_code": "GENO"})
        student = ctx["student"]
        app, seeded = create_application_with_milestones(student)
        for m in seeded:
            complete_milestone(m["id"], student)
        transition_application(app["id"], student, "READY")
        interview = validate_success(
            api.create_milestone(
                app["id"],
                {"kind": "INTERVIEW", "due_at": "2026-05-10T00:00:00Z"},
                make_student_headers(student["id"]),
            ),
            expected_status=201,
        )
        set_clock("2026-05-11T00:00:00Z")
        return ctx, app, interview

    def test_ops_run_marks_missed_and_regresses_application(self, api):
        """PRD §3.8: "The sweep walks every overdue milestone — those in
        `PENDING` or `READY` whose `due_at` falls strictly before
        `executed_at` — in `due_at` ascending, `created_at` ascending order,
        flipping each to `MISSED` and counting it in
        `milestones_marked_missed`. Regression follows: when a newly missed
        milestone is required and its application stands `READY`, the
        application drops back to `DRAFT`, each such regression counted in
        `applications_regressed`".

        Design: Difficulty/transitive_cascade/ops_run_missed_milestone_regresses_application
        """
        ctx, app, interview = self._setup_regression(api)
        run = validate_success(api.create_ops_run(ADMIN), expected_status=201)
        assert_ops_run(run)
        assert run["milestones_marked_missed"] == 1
        assert run["applications_regressed"] == 1

        m_after = validate_success(api.get_milestone(interview["id"], ADMIN))
        assert m_after["status"] == "MISSED"
        app_after = validate_success(api.get_application(app["id"], ADMIN))
        assert app_after["submission_status"] == "DRAFT"

    def test_regression_recomputes_plan(self, api):
        """PRD §3.4: "when an ops run flips a required milestone of a `READY`
        application to `MISSED`, the application regresses from `READY` to
        `DRAFT`, its `version` increments, and the plan's milestone percentage
        and readiness recompute."

        Design: Difficulty/transitive_cascade/ops_run_missed_milestone_regresses_application
        """
        ctx, app, interview = self._setup_regression(api)
        api.create_ops_run(ADMIN)
        data = get_plan(ctx["plan"]["id"])
        assert_pct(data["milestone_pct"], 75.0)  # 3 COMPLETED / 4 pool
        # align 100 (empty pathway) + wbl 100 (no hours) + cert 100 (no cert)
        # -> 100*.30 + 75*.40 + 100*.20 + 100*.10
        assert_pct(data["readiness_official"], 90.0)


class TestOpsRunCounters:
    def test_ops_run_reminder_window_and_restamp_rule(self, api):
        """PRD §3.8: "milestones whose `due_at` falls in the seven-day window
        opening at the clock — on or after now and strictly before now plus
        seven days — and whose `last_reminder_sent_at` is unset or lies more
        than 24 hours in the past are reminder-stamped, refreshing
        `last_reminder_sent_at`, and counted in `reminders_queued`."

        Design: Corner/calculations/ops_run_reminder_window_and_restamp_rule
        """
        ctx = setup_student_with_active_plan(
            pathway_overrides={"pathway_code": "GOR"})
        student = ctx["student"]
        app = create_application(student)
        fafsa = validate_success(
            api.create_milestone(
                app["id"],
                {"kind": "FAFSA", "due_at": "2026-05-05T00:00:00Z"},
                make_student_headers(student["id"]),
            ),
            expected_status=201,
        )

        run1 = validate_success(api.create_ops_run(ADMIN),
                                expected_status=201)
        assert run1["reminders_queued"] == 1, (
            "only the FAFSA milestone due 2026-05-05 is inside "
            "[2026-05-01, 2026-05-08)"
        )
        assert run1["milestones_marked_missed"] == 0

        run2 = validate_success(api.create_ops_run(ADMIN),
                                expected_status=201)
        assert run2["reminders_queued"] == 0, (
            "the 24h restamp rule blocks re-stamping at an unchanged clock"
        )

        m_after = validate_success(api.get_milestone(fafsa["id"], ADMIN))
        assert m_after["last_reminder_sent_at"] is not None
        assert m_after["last_reminder_sent_at"].startswith(
            "2026-05-01T00:00:00")

    def test_ops_run_monotonic_index_and_counters(self, api):
        """PRD §3.8: "Each run takes the next `run_index` — a monotonic
        counter starting at 1 — and stamps `executed_at` with the clock value
        at execution." PRD §3.8: "every plan in `ACTIVE` or `REVISING` status
        has its derived fields recomputed, counted in `plans_recomputed`."

        Design: Corner/endpoints/ops_run_monotonic_index_and_counters
        """
        ctx = setup_student_with_active_plan(
            pathway_overrides={"pathway_code": "GOP"})
        create_application(ctx["student"])

        run1 = validate_success(api.create_ops_run(ADMIN),
                                expected_status=201)
        run2 = validate_success(api.create_ops_run(ADMIN),
                                expected_status=201)
        assert_ops_run(run1)
        assert_ops_run(run2)
        assert run1["run_index"] == 1
        assert run2["run_index"] == 2
        assert run1["milestones_marked_missed"] == 0
        assert run1["applications_regressed"] == 0
        assert run1["reminders_queued"] == 0, (
            "seeded milestones due 2026-06-15 are outside "
            "[2026-05-01, 2026-05-08)"
        )
        assert run1["plans_recomputed"] >= 1

    def test_clock_default_is_fixed_epoch(self, api):
        """PRD §2.5: "At server startup, before any operator intervention, the
        clock reads exactly 2026-05-01T00:00:00Z." PRD §3.8: "The sweep walks
        every overdue milestone — those in `PENDING` or `READY` whose `due_at`
        falls strictly before `executed_at`".

        Design: Corner/cross_cutting_complexity_layers/clock_default_is_fixed_epoch
        """
        ctx = setup_student_with_active_plan(
            pathway_overrides={"pathway_code": "GCK"})
        student = ctx["student"]
        app = create_application(student)
        api.create_milestone(
            app["id"],
            {"kind": "FAFSA", "due_at": "2026-05-02T00:00:00Z"},
            make_student_headers(student["id"]),
        )

        run = validate_success(api.create_ops_run(ADMIN), expected_status=201)
        assert run["executed_at"].startswith("2026-05-01T00:00:00"), (
            "no clock-set call was made, so the sweep reads the startup epoch"
        )
        assert run["milestones_marked_missed"] == 0, (
            "2026-05-02 is not strictly before 2026-05-01"
        )
        assert run["reminders_queued"] == 1, (
            "2026-05-02 is inside [2026-05-01, 2026-05-08)"
        )
