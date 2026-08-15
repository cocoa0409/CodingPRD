"""Difficulty queue: validation priority pairs and boundary precision checks."""
import pytest
from datetime import date

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan_payload, create_dose_constraint_payload,
    create_fraction_session_payload, create_chart_review_payload,
    setup_patient, setup_machine, setup_course,
    setup_treatment_ready_linac, setup_on_treatment, setup_planning_with_draft_plan,
    book_session, deliver_session, weekday_slot,
)

SCHED = TEST_USERS["scheduler_headers"]
ONC_A = TEST_USERS["oncologist_headers"]
ONC_B = TEST_USERS["oncologist_b_headers"]
DOS_A = TEST_USERS["dosimetrist_headers"]
PHYS_A = TEST_USERS["physicist_headers"]
PHYS_B = TEST_USERS["physicist_b_headers"]
RTT_A = TEST_USERS["therapist_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _arm_chart_gate(ctx, n=5, start=date(2026, 8, 3)):
    """Book n sessions on consecutive weekdays and deliver them all, arming the
    chart gate at exactly n==5 deliveries since the last PASS."""
    sessions = []
    d = start
    for _ in range(n):
        while d.weekday() >= 5:
            from datetime import timedelta
            d += timedelta(days=1)
        s_t, e_t = weekday_slot(d)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"],
                            ctx["linac"]["id"], s_t, e_t)
        sessions.append(deliver_session(sess["id"]))
        from datetime import timedelta
        d += timedelta(days=1)
    return sessions


class TestPriorityPairs:
    def test_deliver_state_error_precedes_chart_gate(self):
        """PRD §2.5: category 6 "State gates" (the operation-specific 409 such
        as `ERR_SESSION_NOT_SCHEDULED`) is evaluated before category 8
        "Chart-review gate ... `ERR_CHART_REVIEW_OVERDUE` (HTTP 409)".
        PRD §3.7: "the session must be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`,
        HTTP 409 ...)". A re-delivery attempt on an already-DELIVERED session
        with the chart gate armed must therefore report ERR_SESSION_NOT_SCHEDULED.

        Design: Difficulty/priority_pair_validation_conflict/deliver_session_state_error_precedes_chart_gate_safety
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-PRI-1", technique="IMRT",
                                          total_dose=2000, fractions=10)
        sessions = _arm_chart_gate(ctx, n=5)
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["fractions_since_chart_review"] == 5, "gate armed"
        resp = api_client.deliver_fraction(sessions[0]["id"], RTT_A)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED, expected_status=409)

    def test_deliver_state_error_leaves_counters_untouched(self):
        """PRD §3.7: "A successful delivery writes the session's
        `dose_delivered_cGy` ... and advances the course: `delivered_fractions`
        increments by one". A rejected delivery performs none of these
        mutations: the session stays DELIVERED and the gate counter stays at 5.

        Design: Difficulty/priority_pair_validation_conflict/deliver_session_state_error_precedes_chart_gate_safety
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-PRI-1", technique="IMRT",
                                          total_dose=2000, fractions=10)
        sessions = _arm_chart_gate(ctx, n=5)
        api_client.deliver_fraction(sessions[0]["id"], RTT_A)  # rejected
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["fractions_since_chart_review"] == 5
        assert course["delivered_fractions"] == 5
        lst = validate_paginated(
            api_client.list_fraction_sessions(ctx["course"]["id"], SCHED))[0]
        first = [s for s in lst if s["id"] == sessions[0]["id"]][0]
        assert first["status"] == "DELIVERED"

    def test_schedule_referential_error_precedes_temporal_conflict(self):
        """PRD §2.5: "Every request that survives transport is validated in a
        fixed, system-wide priority order; when several checks could reject the
        same request, the earliest category in this cascade wins and produces
        the error" — category 10 cross-reference integrity precedes category 12
        interval occupation. PRD §3.6: "The plan must belong to the course in
        the path — `ERR_PLAN_COURSE_MISMATCH` (HTTP 422) otherwise". Booking
        course B's session with course A's plan on a slot that collides with an
        existing session must report ERR_PLAN_COURSE_MISMATCH.

        Design: Difficulty/priority_pair_validation_conflict/schedule_referential_error_precedes_temporal_conflict
        """
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-P2", room="SIM1")
        lin_m = setup_machine("LINAC", name="Linac-P2", room="TX2")
        ctx_a = setup_treatment_ready_linac(mrn="MRN-PRI-A", technique="IMRT",
                                            total_dose=2000, fractions=10,
                                            sim_machine=sim_m)
        ctx_b = setup_treatment_ready_linac(mrn="MRN-PRI-B", technique="IMRT",
                                            total_dose=2000, fractions=10,
                                            diagnosis_code="C50",
                                            sim_machine=sim_m)
        # occupy 2026-08-03 09:00-09:20 on the shared linac with course A's plan
        book_session(ctx_a["course"]["id"], ctx_a["plan"]["id"], lin_m["id"],
                     "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        resp = api_client.create_fraction_session(
            ctx_b["course"]["id"],
            create_fraction_session_payload(plan_id=ctx_a["plan"]["id"],  # wrong course
                                            machine_id=lin_m["id"],
                                            start_time="2026-08-03T09:00:00Z",
                                            end_time="2026-08-03T09:20:00Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_PLAN_COURSE_MISMATCH, expected_status=422)

    def test_referential_rejection_creates_no_session(self):
        """PRD §3.6: "The plan must belong to the course in the path —
        `ERR_PLAN_COURSE_MISMATCH` (HTTP 422) otherwise". A rejected booking
        persists nothing: the target course's session list stays empty.

        Design: Difficulty/priority_pair_validation_conflict/schedule_referential_error_precedes_temporal_conflict
        """
        sim_m = setup_machine("CT_SIMULATOR", name="CT-Sim-P2", room="SIM1")
        lin_m = setup_machine("LINAC", name="Linac-P2", room="TX2")
        ctx_a = setup_treatment_ready_linac(mrn="MRN-PRI-A", technique="IMRT",
                                            total_dose=2000, fractions=10,
                                            sim_machine=sim_m)
        ctx_b = setup_treatment_ready_linac(mrn="MRN-PRI-B", technique="IMRT",
                                            total_dose=2000, fractions=10,
                                            diagnosis_code="C50",
                                            sim_machine=sim_m)
        book_session(ctx_a["course"]["id"], ctx_a["plan"]["id"], lin_m["id"],
                     "2026-08-03T09:00:00Z", "2026-08-03T09:20:00Z")
        api_client.create_fraction_session(
            ctx_b["course"]["id"],
            create_fraction_session_payload(plan_id=ctx_a["plan"]["id"],
                                            machine_id=lin_m["id"],
                                            start_time="2026-08-03T09:00:00Z",
                                            end_time="2026-08-03T09:20:00Z"),
            SCHED)
        sessions_b = validate_paginated(
            api_client.list_fraction_sessions(ctx_b["course"]["id"], SCHED))[0]
        assert sessions_b == [], "no FractionSession may be created for course B"


class TestBoundaryPrecision:
    def test_weight_loss_below_threshold_does_not_trigger(self):
        """PRD §3.8: "Adaptation is required when the loss is at least 10.0
        percent (a loss of exactly 10.00 percent triggers) or when
        `physician_override` is true; a current weight at or above baseline
        yields a loss at or below zero and never triggers." A 72.8 kg reading
        against an 80.0 kg baseline is a 9.0% loss: the course stays
        ON_TREATMENT.

        Design: Difficulty/boundary_precision_check/weight_loss_exactly_10pct_triggers_adaptation
        """
        ctx = setup_on_treatment(num_delivered=2, technique="IMRT", total_dose=2000,
                                 fractions=10, mrn="MRN-BND-1", patient_weight=80.0)
        resp = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 72.8}, ONC_A))
        assert resp["status"] == "ON_TREATMENT", "9.0% loss must not trigger"

    def test_weight_loss_exactly_10pct_triggers(self):
        """PRD §3.8: "The percentage weight loss is the baseline minus the
        current weight, divided by the baseline, multiplied by one hundred —
        computed at full floating-point precision with no rounding before
        comparison. Adaptation is required when the loss is at least 10.0
        percent (a loss of exactly 10.00 percent triggers)". 72.0 kg against
        80.0 kg is exactly 10.0%: the course flips to ADAPTATION_REQUIRED.

        Design: Difficulty/boundary_precision_check/weight_loss_exactly_10pct_triggers_adaptation
        """
        ctx = setup_on_treatment(num_delivered=2, technique="IMRT", total_dose=2000,
                                 fractions=10, mrn="MRN-BND-1", patient_weight=80.0)
        resp = get_success_data(api_client.adaptation_check(
            ctx["course"]["id"], {"current_weight_kg": 72.0}, ONC_A))
        assert resp["status"] == "ADAPTATION_REQUIRED"

    def test_chart_gate_sixth_delivery_blocked_then_reopened_by_pass(self):
        """PRD §3.7: "Delivery is permitted only while the course's
        `fractions_since_chart_review` is strictly less than five: the fifth
        delivery since the last passing review still succeeds and arms the gate,
        and the sixth is rejected with `ERR_CHART_REVIEW_OVERDUE` (HTTP 409)
        until a physicist records a review. ... A `PASS` resets
        `fractions_since_chart_review` to zero."

        Design: Difficulty/boundary_precision_check/chart_gate_fifth_delivery_passes_sixth_blocked
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-BND-2", technique="IMRT",
                                          total_dose=2000, fractions=10)
        _arm_chart_gate(ctx, n=5)  # 5 deliveries; gate now armed
        f6 = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"],
                          "2026-08-10T09:00:00Z", "2026-08-10T09:20:00Z")
        resp = api_client.deliver_fraction(f6["id"], RTT_A)
        validate_error(resp, ApiErrorId.ERR_CHART_REVIEW_OVERDUE, expected_status=409)
        get_success_data(api_client.create_chart_review(
            ctx["course"]["id"], create_chart_review_payload(outcome="PASS"), PHYS_A))
        delivered = validate_success(api_client.deliver_fraction(f6["id"], RTT_A))
        assert delivered["status"] == "DELIVERED"
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["fractions_since_chart_review"] == 1, \
            "PASS reset to 0, then this delivery incremented to 1"

    def test_chart_gate_allows_exactly_five_consecutive_deliveries(self):
        """PRD §3.7: "the fifth delivery since the last passing review still
        succeeds and arms the gate". Deliveries 1 through 5 all succeed; the
        counter then reads exactly 5.

        Design: Difficulty/boundary_precision_check/chart_gate_fifth_delivery_passes_sixth_blocked
        """
        ctx = setup_treatment_ready_linac(mrn="MRN-BND-2", technique="IMRT",
                                          total_dose=2000, fractions=10)
        sessions = _arm_chart_gate(ctx, n=5)
        assert all(s["status"] == "DELIVERED" for s in sessions)
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["fractions_since_chart_review"] == 5

    def test_dose_constraint_equality_satisfies_submission(self):
        """PRD §3.4: "The system derives `satisfied` as true exactly when the
        evaluated value is no greater than the limit — equality satisfies."
        PRD §3.5: "A successful submission moves the plan `DRAFT →
        PENDING_PRIMARY_CHECK`". A MAX_DOSE constraint evaluated at exactly its
        4500 limit is satisfied and the plan submits.

        Design: Difficulty/boundary_precision_check/dose_constraint_equality_satisfies_submission
        """
        ctx = setup_planning_with_draft_plan(mrn="MRN-BND-3", total_dose=4000,
                                             fractions=8, diagnosis_code="C73")
        dc = get_success_data(api_client.create_dose_constraint(
            ctx["plan"]["id"],
            create_dose_constraint_payload(limit_cGy=4500, evaluated_value_cGy=4500),
            DOS_A))
        assert dc["satisfied"] is True, "equality satisfies"
        plan = validate_success(api_client.submit_plan_for_check(ctx["plan"]["id"], DOS_A))
        assert plan["status"] == "PENDING_PRIMARY_CHECK"

    def test_dose_constraint_equality_boundary_recorded_on_constraint(self):
        """PRD §3.4: "`satisfied` [is] true exactly when the evaluated value is
        no greater than the limit — equality satisfies." The created constraint
        itself reports satisfied true at the exact boundary.

        Design: Difficulty/boundary_precision_check/dose_constraint_equality_satisfies_submission
        """
        ctx = setup_planning_with_draft_plan(mrn="MRN-BND-3", total_dose=4000,
                                             fractions=8, diagnosis_code="C73")
        dc = get_success_data(api_client.create_dose_constraint(
            ctx["plan"]["id"],
            create_dose_constraint_payload(limit_cGy=4500, evaluated_value_cGy=4500),
            DOS_A))
        assert dc["evaluated_value_cGy"] == 4500
        assert dc["limit_cGy"] == 4500
        assert dc["satisfied"] is True
