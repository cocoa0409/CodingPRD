"""Accommodations, implementation logging, and the two compliance-measurement
windows (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    add_accommodation,
    create_draft_plan,
    create_student_for,
    create_testing_request,
    log_implementation,
    make_coordinator_headers,
    make_teacher_headers,
    pipeline_to_determination,
    set_clock,
    setup_active_plan,
    setup_school_with_staff,
    submit_referral,
    validate_error,
    validate_success,
)


class TestImplementationLogGuards:
    def test_err_accommodation_not_active_on_log(self, api):
        """PRD §3.5: "Logging against an accommodation that is not `ACTIVE` is
        rejected with `ERR_ACCOMMODATION_NOT_ACTIVE`, and whenever
        `was_implemented_as_planned` is false a `deviation_notes` explanation is
        mandatory — its absence is rejected with `ERR_DEVIATION_NOTES_REQUIRED`
        (HTTP 400)."

        Design: Corner/errors/err_accommodation_not_active_on_log
        """
        ctx = setup_school_with_staff()
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = submit_referral(student["id"], ctx["teacher"]["id"], role="Teacher")
        evaluation = pipeline_to_determination(student["id"], referral, co["id"])
        plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
        accommodation = add_accommodation(plan["id"], co["id"], applies_to_testing=False)
        # Plan never activated: the accommodation is still DRAFT.
        resp = api.create_implementation_log(
            {"plan_id": plan["id"], "accommodation_id": accommodation["id"],
             "log_date": "2025-12-20T00:00:00Z", "was_implemented_as_planned": True},
            make_teacher_headers(ctx["teacher"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_NOT_ACTIVE)

    def test_err_deviation_notes_required(self, api):
        """PRD §3.5: "Logging against an accommodation that is not `ACTIVE` is
        rejected with `ERR_ACCOMMODATION_NOT_ACTIVE`, and whenever
        `was_implemented_as_planned` is false a `deviation_notes` explanation is
        mandatory — its absence is rejected with `ERR_DEVIATION_NOTES_REQUIRED`
        (HTTP 400)."

        Design: Corner/errors/err_deviation_notes_required
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        resp = api.create_implementation_log(
            {"plan_id": ctx["plan"]["id"], "accommodation_id": ctx["accommodation"]["id"],
             "log_date": "2026-01-15T00:00:00Z", "was_implemented_as_planned": False},
            make_teacher_headers(ctx["teacher"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEVIATION_NOTES_REQUIRED)


class TestTestingAccommodationReferentialGuards:
    def test_err_accommodation_not_test_applicable(self, api):
        """PRD §3.7: "The referenced accommodation must belong to the same plan
        and carry `applies_to_testing` true; otherwise the submission is
        rejected with `ERR_ACCOMMODATION_NOT_TEST_APPLICABLE`."

        Design: Corner/errors/err_accommodation_not_test_applicable
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z",
                                applies_to_testing=False,
                                accommodation_type="PREFERENTIAL_SEATING")
        resp = api.create_testing_request(
            {"plan_id": ctx["plan"]["id"], "accommodation_id": ctx["accommodation"]["id"],
             "test_name": "ELA", "test_date": "2027-01-15T00:00:00Z"},
            make_coordinator_headers(ctx["coordinator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_NOT_TEST_APPLICABLE)

    def test_cascade_accommodation_discontinue_denies_pending_testing(self, api):
        """PRD §3.5: "Discontinuing is permitted from either `ACTIVE` or
        `SUSPENDED` (otherwise `ERR_ACCOMMODATION_NOT_DISCONTINUABLE`) and is
        terminal: the accommodation lands in `DISCONTINUED`, and every testing
        request referencing it that is still in `SUBMITTED` or
        `PENDING_DISTRICT_REVIEW` is automatically denied in the same request."

        Design: Corner/cross_cutting_layers/cascade_accommodation_discontinue_denies_pending_testing
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z", applies_to_testing=True)
        co = ctx["coordinator"]
        request = create_testing_request(
            ctx["plan"]["id"], ctx["accommodation"]["id"], co["id"],
            "2027-01-15T00:00:00Z", test_name="ELA",
        )
        assert request["request_status"] == "SUBMITTED"
        discontinued = validate_success(api.discontinue_accommodation(
            ctx["accommodation"]["id"], make_coordinator_headers(co["id"])
        ))
        assert discontinued["accommodation_status"] == "DISCONTINUED"
        request_after = validate_success(api.get_testing_request(
            request["id"], make_coordinator_headers(co["id"])
        ))
        assert request_after["request_status"] == "DENIED", (
            "discontinuing an accommodation must auto-deny its SUBMITTED testing "
            f"requests in the same request, got {request_after['request_status']}"
        )


class TestComplianceWindowVariants:
    def _setup_two_window_logs(self, api):
        """Plan effective 2026-01-01; one old success log (2026-02-01) and one
        recent deviation log (2026-07-25); clock ends at 2026-08-01."""
        ctx = setup_active_plan(
            clock_initial="2025-12-15T00:00:00Z",
            activate_at="2026-01-01T00:00:00Z",
            applies_to_testing=True,
        )
        teacher = ctx["teacher"]
        set_clock("2026-02-01T00:00:00Z")
        log_implementation(ctx["plan"]["id"], ctx["accommodation"]["id"],
                           "2026-02-01T00:00:00Z", teacher["id"],
                           was_implemented_as_planned=True)
        set_clock("2026-07-25T00:00:00Z")
        log_implementation(ctx["plan"]["id"], ctx["accommodation"]["id"],
                           "2026-07-25T00:00:00Z", teacher["id"],
                           was_implemented_as_planned=False,
                           deviation_notes="Sub forgot extended time")
        set_clock("2026-08-01T00:00:00Z")
        return ctx

    def test_implementation_compliance_trailing_vs_cumulative_diverge(self, api):
        """PRD §3.5: "The default trailing variant, recomputed eagerly whenever
        a log is filed and surfaced on plan reads, counts only logs whose
        `log_date` falls within the inclusive window from 30 days before the
        current clock instant through the instant itself. The cumulative
        plan-year variant, produced by the plan's compliance summary, counts all
        logs since the plan-year anchor — the later of the plan's
        `plan_effective_date` and the `completed_at` of its most recently
        completed `ANNUAL` review. The compliance summary reports
        `implementation_compliance_pct_trailing_30`,
        `implementation_compliance_pct_cumulative`, `next_annual_review_due`,
        and `next_re_evaluation_due`."

        Design: Difficulty/dual_variant_calc/implementation_compliance_trailing_vs_cumulative_diverge
        """
        ctx = self._setup_two_window_logs(api)
        summary = validate_success(api.get_plan_compliance_summary(
            ctx["plan"]["id"], make_coordinator_headers(ctx["coordinator"]["id"])
        ))
        trailing = summary["implementation_compliance_pct_trailing_30"]
        cumulative = summary["implementation_compliance_pct_cumulative"]
        assert trailing == 0.0, (
            f"trailing 30-day window holds only the deviation log: 0/1 = 0.0, got {trailing}"
        )
        assert cumulative == 50.0, (
            f"plan-year window holds both logs: 1/2 = 50.0, got {cumulative}"
        )
        assert trailing != cumulative, (
            "the two variants must diverge on identical log history"
        )

    def test_trailing_variant_surfaced_on_plan_reads(self, api):
        """PRD §3.5: "The default trailing variant, recomputed eagerly whenever
        a log is filed and surfaced on plan reads, counts only logs whose
        `log_date` falls within the inclusive window from 30 days before the
        current clock instant through the instant itself."

        Design: Difficulty/dual_variant_calc/implementation_compliance_trailing_vs_cumulative_diverge
        """
        ctx = self._setup_two_window_logs(api)
        plan = validate_success(api.get_plan(
            ctx["plan"]["id"], make_coordinator_headers(ctx["coordinator"]["id"])
        ))
        assert plan["implementation_compliance_pct"] == 0.0, (
            "plan reads must surface the trailing 30-day variant (only the "
            f"recent deviation log is in-window): got {plan['implementation_compliance_pct']}"
        )
