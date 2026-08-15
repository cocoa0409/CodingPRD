"""Treatment work orders, contractor quality scores, and the suspension cascade
(PRD §3.5); validation-ordering pair on schedule (PRD §2.8)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    apply_treatment,
    assert_contractor_crew,
    assert_instant_equals,
    assert_treatment_work_order,
    create_crew,
    create_pole,
    create_treatment_order,
    drive_treatment_to_qa,
    get_crew,
    get_treatment,
    qa_review_treatment,
    schedule_treatment,
    schedule_treatment_payload,
    setup_crew_with_qa_history,
    validate_error,
    validate_success,
)


class TestCrewDefaults:
    def test_crew_read_shows_default_scores(self, api, program_manager_headers):
        """PRD §3.5: "A crew begins `ACTIVE` and carries lifetime counters
        `qa_pass_count` and `qa_fail_count`, both zero, an append-only `qa_event_log`
        whose entries record each QA decision with its `decided_at` instant and the
        `order_id` it concerned, two computed quality scores, and
        `current_cycle_billing_cents`, the production billing from the most recent
        cycle reconcile."
        PRD §3.5: "Both are rounded to two decimal places, half-up, and both read
        exactly 100.00 when the crew has no events at all."

        Design: Corner/entities/crew_read_shows_default_scores
        """
        crew = create_crew(crew_code="CR-DEF", region="SE")
        read = validate_success(
            api.get_contractor_crew(crew["id"], program_manager_headers)
        )
        assert_contractor_crew(read)
        assert read["quality_score_lifetime"] == pytest.approx(100.00, abs=0.005)
        assert read["quality_score_rolling"] == pytest.approx(100.00, abs=0.005)
        assert read["qa_pass_count"] == 0
        assert read["qa_fail_count"] == 0
        assert read["status"] == "ACTIVE"
        assert read["qa_event_log"] == []


class TestRollingVsLifetimeDivergence:
    def _setup_six_event_crew(self, api):
        """Chronological QA events P, P, P, F, P on five orders plus a sixth APPLIED."""
        crew, pole, orders = setup_crew_with_qa_history(
            ["PASS", "PASS", "PASS", "FAIL", "PASS"], crew_code="CR-Q"
        )
        sixth = create_treatment_order(pole["id"], product_code="CCA_WRAP",
                                       cost_cents=17500)
        schedule_treatment(sixth["id"], crew["id"],
                           work_start_date="2026-08-10", work_end_date="2026-08-12")
        apply_treatment(sixth["id"], crew["id"])
        return crew, sixth

    def test_crew_quality_scores_diverge_rolling_vs_lifetime(
            self, api, program_manager_headers):
        """PRD §3.5: "`quality_score_lifetime` is one hundred times the number of
        `PASS` events divided by the total number of events, computed over all events;
        `quality_score_rolling` applies the same ratio over only the five most recent
        events."

        Design: Difficulty/dual_variant_calc/crew_quality_rolling_vs_lifetime_diverge
        """
        crew, sixth = self._setup_six_event_crew(api)
        qa_review_treatment(sixth["id"], "FAIL")
        read = get_crew(crew["id"])
        # All six events P,P,P,F,P,F -> 4/6; last five P,P,F,P,F -> 3/5.
        assert read["quality_score_lifetime"] == pytest.approx(66.67, abs=0.005)
        assert read["quality_score_rolling"] == pytest.approx(60.00, abs=0.005)
        assert read["qa_pass_count"] == 4
        assert read["qa_fail_count"] == 2
        assert len(read["qa_event_log"]) == 6

    def test_crew_suspension_follows_rolling_score_only(
            self, api, program_manager_headers):
        """PRD §3.5: "if the crew's rolling quality score has dropped below 70.00, the
        crew moves from `ACTIVE` to `SUSPENDED`, and every subsequent scheduling attempt
        for that crew fails with `ERR_CREW_SUSPENDED`."
        PRD §3.5: "The suspension cascade consults the rolling score only — a
        pass-heavy recent window can sit far above the lifetime figure".

        Design: Difficulty/dual_variant_calc/crew_quality_rolling_vs_lifetime_diverge
        """
        crew, sixth = self._setup_six_event_crew(api)
        qa_review_treatment(sixth["id"], "FAIL")
        read = get_crew(crew["id"])
        assert read["quality_score_rolling"] == pytest.approx(60.00, abs=0.005)
        assert read["status"] == "SUSPENDED", (
            "rolling 60.00 < 70.00 after the FAIL must suspend the crew"
        )


class TestFailSuspendsCrewCascade:
    def _setup_four_events_plus_applied(self, api):
        """Crew with P,P,P,F history (rolling 75.00) and a fifth order APPLIED."""
        crew, pole, _ = setup_crew_with_qa_history(
            ["PASS", "PASS", "PASS", "FAIL"], crew_code="CR-S"
        )
        fifth = create_treatment_order(pole["id"], product_code="CCA_WRAP",
                                       cost_cents=17500)
        schedule_treatment(fifth["id"], crew["id"],
                           work_start_date="2026-08-10", work_end_date="2026-08-12")
        apply_treatment(fifth["id"], crew["id"])
        return crew, fifth

    def test_treatment_fail_drops_rolling_below_threshold(
            self, api, program_manager_headers):
        """PRD §3.5: "A `FAIL` moves the order to `FAILED_QA`, increments the crew's
        `qa_fail_count` and the order's own `qa_fail_events`, appends the event, and
        recomputes both scores — and then the suspension cascade runs: if the crew's
        rolling quality score has dropped below 70.00, the crew moves from `ACTIVE` to
        `SUSPENDED`".

        Design: Difficulty/transitive_cascade/treatment_fail_suspends_crew_cascade_depth2
        """
        crew, fifth = self._setup_four_events_plus_applied(api)
        qa_review_treatment(fifth["id"], "FAIL")
        read = get_crew(crew["id"])
        # Last five events P,P,P,F,F -> 3/5 = 60.00.
        assert read["quality_score_rolling"] == pytest.approx(60.00, abs=0.005)
        assert read["status"] == "SUSPENDED"

    def test_treatment_fail_increments_order_fail_events(
            self, api, program_manager_headers):
        """PRD §3.5: "A `FAIL` moves the order to `FAILED_QA`, increments the crew's
        `qa_fail_count` and the order's own `qa_fail_events`, appends the event, and
        recomputes both scores".

        Design: Difficulty/transitive_cascade/treatment_fail_suspends_crew_cascade_depth2
        """
        crew, fifth = self._setup_four_events_plus_applied(api)
        reviewed = qa_review_treatment(fifth["id"], "FAIL")
        assert reviewed["status"] == "FAILED_QA"
        assert reviewed["qa_fail_events"] == 1
        assert get_treatment(fifth["id"])["qa_fail_events"] == 1


class TestScheduleWithSuspendedCrew:
    def _setup_suspended_crew(self, api):
        """One FAIL on the crew's only event -> rolling 0.00 -> SUSPENDED (PRD §3.5)."""
        crew = create_crew(crew_code="CR-Z")
        pole = create_pole(pole_number="P-SB")
        drive_treatment_to_qa(pole["id"], crew["id"], "FAIL")
        assert get_crew(crew["id"])["status"] == "SUSPENDED"
        second = create_treatment_order(pole["id"], product_code="CCA_WRAP",
                                        cost_cents=17500)
        return crew, second

    def test_schedule_with_suspended_crew_rejected(self, api, program_manager_headers):
        """PRD §3.5: "the named crew must exist and be `ACTIVE`, since a `SUSPENDED`
        crew cannot take new work (`ERR_CREW_SUSPENDED`)".

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_when_crew_suspended
        """
        crew, second = self._setup_suspended_crew(api)
        resp = api.schedule_treatment_work_order(
            second["id"],
            schedule_treatment_payload(crew["id"], work_start_date="2026-08-20",
                                       work_end_date="2026-08-22"),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_SUSPENDED)

    def test_schedule_with_suspended_crew_leaves_order_created(
            self, api, program_manager_headers):
        """PRD §3.5: "if the crew's rolling quality score has dropped below 70.00, the
        crew moves from `ACTIVE` to `SUSPENDED`, and every subsequent scheduling attempt
        for that crew fails with `ERR_CREW_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_when_crew_suspended
        """
        crew, second = self._setup_suspended_crew(api)
        resp = api.schedule_treatment_work_order(
            second["id"],
            schedule_treatment_payload(crew["id"], work_start_date="2026-08-20",
                                       work_end_date="2026-08-22"),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_SUSPENDED)
        after = get_treatment(second["id"])
        assert after["status"] == "CREATED"
        assert after["crew_id"] is None


class TestCrewHalfOpenWindow:
    def _setup_scheduled_crew(self, api):
        crew = create_crew(crew_code="CR-H")
        p1 = create_pole(pole_number="P-H1")
        p2 = create_pole(pole_number="P-H2")
        p3 = create_pole(pole_number="P-H3")
        o1 = create_treatment_order(p1["id"])
        schedule_treatment(o1["id"], crew["id"],
                           work_start_date="2026-08-10", work_end_date="2026-08-12")
        o2 = create_treatment_order(p2["id"])
        o3 = create_treatment_order(p3["id"])
        return crew, o2, o3

    def test_crew_window_adjacency_allowed(self, api, program_manager_headers):
        """PRD §3.5: "the half-open window must not overlap any other `SCHEDULED` order
        for the same crew, else `ERR_CREW_SCHEDULE_CONFLICT` — adjacency is not overlap,
        so one order's start may equal another's end."

        Design: Difficulty/resource_temporal_overlap/crew_halfopen_window_adjacency
        """
        crew, o2, _ = self._setup_scheduled_crew(api)
        resp = api.schedule_treatment_work_order(
            o2["id"],
            schedule_treatment_payload(crew["id"], work_start_date="2026-08-12",
                                       work_end_date="2026-08-15"),
            program_manager_headers,
        )
        scheduled = validate_success(resp, expected_status=200)
        assert_treatment_work_order(scheduled)
        assert scheduled["status"] == "SCHEDULED", (
            "half-open adjacency [08-12, 08-15) after [08-10, 08-12) must be allowed"
        )
        assert scheduled["crew_id"] == crew["id"]

    def test_crew_window_overlap_rejected(self, api, program_manager_headers):
        """PRD §3.5: "the half-open window must not overlap any other `SCHEDULED` order
        for the same crew, else `ERR_CREW_SCHEDULE_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/crew_halfopen_window_adjacency
        """
        crew, o2, o3 = self._setup_scheduled_crew(api)
        schedule_treatment(o2["id"], crew["id"],
                           work_start_date="2026-08-12", work_end_date="2026-08-15")
        resp = api.schedule_treatment_work_order(
            o3["id"],
            schedule_treatment_payload(crew["id"], work_start_date="2026-08-11",
                                       work_end_date="2026-08-13"),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)
        assert get_treatment(o3["id"])["status"] == "CREATED"


class TestScheduleValidationOrdering:
    def _setup_applied_order(self, api):
        crew = create_crew(crew_code="CR-E")
        pole = create_pole(pole_number="P-PC2")
        order = create_treatment_order(pole["id"])
        schedule_treatment(order["id"], crew["id"],
                           work_start_date="2026-08-10", work_end_date="2026-08-12")
        apply_treatment(order["id"], crew["id"])
        return crew, order

    def test_schedule_unknown_crew_existence_wins_over_state(
            self, api, program_manager_headers):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, and the
        stages are evaluated in a strict order; a failure at an earlier stage is
        reported and masks every later check." — stage 4 (Existence) precedes stage 5
        (State validity).
        PRD §2.9: "Each unresolved identifier maps to its resource-specific error:
        `ERR_POLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`,
        `ERR_TREATMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND`."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_schedule
        """
        _, order = self._setup_applied_order(api)
        resp = api.schedule_treatment_work_order(
            order["id"],
            schedule_treatment_payload(NON_EXISTENT_UUID,
                                       work_start_date="2026-09-01",
                                       work_end_date="2026-09-03"),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_FOUND)

    def test_schedule_unknown_crew_leaves_order_untouched(
            self, api, program_manager_headers):
        """PRD §2.8: "a failure at an earlier stage is reported and masks every later
        check", so the rejected call mutates nothing: the APPLIED order keeps its crew
        and application stamps.

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_schedule
        """
        crew, order = self._setup_applied_order(api)
        resp = api.schedule_treatment_work_order(
            order["id"],
            schedule_treatment_payload(NON_EXISTENT_UUID,
                                       work_start_date="2026-09-01",
                                       work_end_date="2026-09-03"),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_FOUND)
        after = get_treatment(order["id"])
        assert after["status"] == "APPLIED"
        assert after["crew_id"] == crew["id"]
        assert after["applied_at"] is not None


class TestFailedQaRetreatLoop:
    def test_failed_qa_retreat_loop_resets_warranty(self, api, program_manager_headers):
        """PRD §3.5: "Scheduling is valid from `CREATED` and equally from `FAILED_QA` —
        the retreat loop — and sets `crew_id`, `work_start_date`, and `work_end_date`."
        PRD §3.5: "Rescheduling from `FAILED_QA` additionally resets `applied_at`,
        `applied_by_crew_id`, and the warranty fields to null, erasing the failed
        application."
        PRD §3.5: "A warranty retreat order, when itself applied, starts an entirely
        new warranty window from its own `applied_at`."

        Design: Corner/state_machines/failed_qa_retreat_loop_resets_warranty
        """
        # Three PASSes keep the crew ACTIVE after one FAIL (rolling 75.00 >= 70.00).
        crew, pole, _ = setup_crew_with_qa_history(
            ["PASS", "PASS", "PASS"], crew_code="CR-RL",
            work_start_date="2026-08-03", work_end_date="2026-08-04",
        )
        order = create_treatment_order(pole["id"], product_code="COPPER_NAPHTHENATE",
                                       cost_cents=14500)
        schedule_treatment(order["id"], crew["id"],
                           work_start_date="2026-08-10", work_end_date="2026-08-12")
        apply_treatment(order["id"], crew["id"])
        failed = qa_review_treatment(order["id"], "FAIL")
        assert failed["status"] == "FAILED_QA"
        assert get_crew(crew["id"])["status"] == "ACTIVE", (
            "rolling 75.00 stays at or above 70.00, so the retreat loop is available"
        )

        resp = api.schedule_treatment_work_order(
            order["id"],
            schedule_treatment_payload(crew["id"], work_start_date="2026-08-20",
                                       work_end_date="2026-08-22"),
            program_manager_headers,
        )
        rescheduled = validate_success(resp, expected_status=200)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["applied_at"] is None
        assert rescheduled["applied_by_crew_id"] is None
        assert rescheduled["warranty_years"] is None
        assert rescheduled["warranty_end_date"] is None

        reapplied = apply_treatment(order["id"], crew["id"])
        # COPPER_NAPHTHENATE carries five warranty years from the new applied_at.
        assert_instant_equals(reapplied["warranty_end_date"], "2031-08-01T00:00:00Z",
                              "re-baselined warranty_end_date")
        assert reapplied["warranty_years"] == 5
        assert reapplied["qa_fail_events"] == 1, (
            "fail history is retained across the retreat loop"
        )
