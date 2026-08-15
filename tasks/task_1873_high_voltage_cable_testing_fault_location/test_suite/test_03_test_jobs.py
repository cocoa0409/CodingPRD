"""Test job planning, steering, budgeting, invoicing, and OCC (PRD §3.3, §2.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_success,
    validate_error,
    create_circuit,
    create_window,
    approve_window,
    activate_window,
    create_job,
    plan_job,
    set_clock,
    get_job,
    get_unit,
    get_assignment,
    setup_planned_job,
    setup_job_in_progress,
    setup_job_in_evaluation,
    setup_fault_closed_verified,
    create_unit,
    create_assignment,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
SUPERVISOR = TEST_USERS["test_supervisor_headers"]
TECHNICIAN = TEST_USERS["field_technician_headers"]
ENGINEER = TEST_USERS["asset_engineer_headers"]
DISPATCH = TEST_USERS["dispatch_coordinator_headers"]


class TestEstimateAndBudget:
    def test_subtotal_at_threshold_uses_standard_rate(self, api):
        """PRD §3.3: "The complexity surcharge is then keyed strictly on this
        pre-surcharge subtotal: a subtotal strictly greater than 400,000 cents
        makes the job COMPLEX and carries a twelve percent surcharge; anything
        else, including a subtotal of exactly 400,000 cents, is STANDARD with
        a six percent surcharge."

        Design: Difficulty/combinatorial_formula/estimate_tier_keyed_on_pre_surcharge_subtotal
        """
        ctx = setup_planned_job(
            circuit_ref="CKT-CF3", length_m=1000, approved_budget_cents=424000,
        )
        job = ctx["job"]
        # subtotal = 180000 + 125*1000 + 95000 = 400000 (not > 400000)
        # -> STANDARD 6% -> 400000 * 1.06 = 424000, and 424000 <= 424000 passes.
        assert job["estimate_cents"] == 424000
        assert job["status"] == "PLANNED"

    def test_subtotal_above_threshold_uses_complex_rate(self, api):
        """PRD §3.3: "a subtotal strictly greater than 400,000 cents makes the
        job COMPLEX and carries a twelve percent surcharge".

        Design: Difficulty/combinatorial_formula/estimate_tier_keyed_on_pre_surcharge_subtotal
        """
        ctx = setup_planned_job(
            circuit_ref="CKT-CF3B", length_m=1001, approved_budget_cents=500000,
        )
        # subtotal = 180000 + 125*1001 + 95000 = 400125 > 400000
        # -> COMPLEX 12% -> round(400125 * 1.12) = 448140.
        assert ctx["job"]["estimate_cents"] == 448140
        assert ctx["job"]["status"] == "PLANNED"

    def test_plan_rejected_when_budget_one_cent_short(self, api):
        """PRD §3.3: "If that estimate exceeds `approved_budget_cents`,
        planning is rejected with `ERR_BUDGET_EXCEEDED` and the job stays in
        `DRAFT`; otherwise the estimate is stored and the job moves to
        `PLANNED`."

        Design: Corner/validations/budget_exceeded_by_one_cent
        """
        circuit = create_circuit("CKT-V14", length_m=1000)
        window = create_window(circuit["id"])
        approve_window(window["id"])
        job = create_job(circuit["id"], window["id"], approved_budget_cents=423999)
        resp = api.plan_job(job["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        after = get_job(job["id"])
        assert after["status"] == "DRAFT"
        assert after["estimate_cents"] is None, (
            "the estimate is stored only on a successful plan (PRD §3.3)"
        )

    def test_second_job_on_busy_circuit_rejected(self, api):
        """PRD §3.3: "the circuit must not already carry a non-terminal test
        job (else `ERR_CIRCUIT_BUSY`)".

        Design: Corner/validations/circuit_busy_rejected
        """
        circuit = create_circuit("CKT-V10")
        window1 = create_window(circuit["id"])
        window2 = create_window(
            circuit["id"], window_start="2026-09-01T08:00:00Z",
            window_end="2026-09-01T12:00:00Z",
        )
        approve_window(window1["id"])
        approve_window(window2["id"])
        create_job(circuit["id"], window1["id"], approved_budget_cents=800000)
        resp = api.create_test_job(
            {
                "circuit_id": circuit["id"],
                "outage_window_id": window2["id"],
                "requested_methods": ["PD_MAPPING"],
                "approved_budget_cents": 500000,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_CIRCUIT_BUSY)


class TestAbortAndInvoice:
    def test_abort_cancels_open_assignments_and_frees_unit(self, api):
        """PRD §3.3: "abortion lands the job in `ABORTED` and cancels every
        equipment assignment of the job still in `RESERVED` or `CONFIRMED`,
        subtracting each cancelled assignment's `duration_hours` from its
        unit's `committed_hours`."

        Design: Corner/cross_cutting_layers/job_abort_cascades_assignments
        """
        ctx = setup_planned_job(circuit_ref="CKT-X4")
        unit = create_unit()
        assignment = create_assignment(unit["id"], ctx["job"]["id"])

        aborted = validate_success(api.abort_job(ctx["job"]["id"], PLANNER))
        assert aborted["status"] == "ABORTED"

        assert get_assignment(assignment["id"])["status"] == "CANCELLED"
        unit_after = get_unit(unit["id"])
        assert unit_after["status"] == "AVAILABLE"
        assert unit_after["committed_hours"] == 0.0

    def test_invoice_without_work_lines_equals_estimate(self, api):
        """PRD §3.3: "The invoice total is the stored estimate plus the sum of
        the excavation lines plus the sum of the splice lines." With no
        excavations or splices both sums are empty.

        Design: Corner/calculations/invoice_with_no_work_lines
        """
        ctx = setup_planned_job(circuit_ref="CKT-C5", length_m=1000)
        invoice = validate_success(api.get_job_invoice(ctx["job"]["id"], PLANNER))
        assert invoice["estimate_cents"] == 424000
        assert invoice["excavation_total_cents"] == 0
        assert invoice["splice_total_cents"] == 0
        assert invoice["invoice_total_cents"] == 424000

    def test_invoice_total_marks_up_per_line(self, api):
        """PRD §3.3: "The rounding order is pinned per line: markup is applied
        and rounded on each line individually and only then summed — summing
        costs first and marking up afterwards yields different cents, so on
        lines of 100,040 and 200,040 cents the specified order produces
        325,586 cents of marked-up work where the forbidden order would
        produce 325,587."

        Design: Difficulty/combinatorial_formula/invoice_per_line_markup_rounding_beats_sum_rounding
        """
        ctx = setup_fault_closed_verified(circuit_ref="CKT-CF2", length_m=1000)
        invoice = validate_success(api.get_job_invoice(ctx["job"]["id"], ENGINEER))
        assert invoice["estimate_cents"] == 424000
        assert invoice["invoice_total_cents"] == 749586, (
            "424000 + 108543 + 217043 — per-line rounding, not 749587"
        )

    def test_invoice_line_components_rounded_individually(self, api):
        """PRD §3.3: "Each billable excavation line is the excavation's
        `cost_cents` marked up by 8.5 percent and rounded half-up to whole
        cents, summed over the job's non-cancelled excavation orders; each
        billable splice line is computed the same way over all splices of the
        job's faults regardless of splice status."

        Design: Difficulty/combinatorial_formula/invoice_per_line_markup_rounding_beats_sum_rounding
        """
        ctx = setup_fault_closed_verified(circuit_ref="CKT-CF2", length_m=1000)
        invoice = validate_success(api.get_job_invoice(ctx["job"]["id"], ENGINEER))
        # round_half_up(100040 * 1.085) = 108543; round_half_up(200040 * 1.085) = 217043.
        assert invoice["excavation_total_cents"] == 108543
        assert invoice["splice_total_cents"] == 217043
        job = get_job(ctx["job"]["id"])
        assert job["committed_cost_cents"] == 300080, (
            "committed = excavation 100040 + splice 200040 (PRD §2.10)"
        )


class TestStartSuspendResume:
    def test_start_before_window_active_rejected(self, api):
        """PRD §3.3: "Starting a job requires its outage window to be
        `ACTIVE`, else `ERR_WINDOW_NOT_ACTIVE`, and moves the job `PLANNED` →
        `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/job_start_requires_active_window
        """
        ctx = setup_planned_job(circuit_ref="CKT-CE3")
        # Clock untouched: 2026-08-01 default, window merely APPROVED.
        resp = api.start_job(ctx["job"]["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_ACTIVE)
        assert get_job(ctx["job"]["id"])["status"] == "PLANNED"

    def test_start_after_window_activation_succeeds(self, api):
        """PRD §3.3: "Starting a job requires its outage window to be
        `ACTIVE`, else `ERR_WINDOW_NOT_ACTIVE`, and moves the job `PLANNED` →
        `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/job_start_requires_active_window
        """
        ctx = setup_planned_job(circuit_ref="CKT-CE3")
        set_clock("2026-08-10T09:00:00Z")
        activate_window(ctx["window"]["id"])
        started = validate_success(api.start_job(ctx["job"]["id"], SUPERVISOR))
        assert started["status"] == "IN_PROGRESS"

    def test_suspend_resume_loop_ends_in_progress_with_version_drift(self, api):
        """PRD §3.3: "Suspension moves `IN_PROGRESS` → `SUSPENDED` with no
        preconditions, and resumption returns `SUSPENDED` → `IN_PROGRESS`
        under the same active-window requirement."
        PRD §2.5: "`version`, an integer that increments by one on every
        mutation of the resource."

        Design: Difficulty/non_linear_state_machine/job_suspend_resume_revert_loop
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-NL2", with_permit=False, with_equipment=False,
        )
        job_id = ctx["job"]["id"]
        version_in_progress = get_job(job_id)["version"]
        # plan and start already happened before this read; what follows is
        # exactly four further mutations.
        api.suspend_job(job_id, SUPERVISOR)
        api.resume_job(job_id, SUPERVISOR)
        api.suspend_job(job_id, SUPERVISOR)
        final = validate_success(api.resume_job(job_id, SUPERVISOR))
        assert final["status"] == "IN_PROGRESS"
        assert final["version"] == version_in_progress + 4, (
            "two full suspend/resume loops after the read are four mutations, "
            "and version increments by one on every mutation (PRD §2.5)"
        )

    def test_suspend_and_resume_intermediate_states(self, api):
        """PRD §3.3: "Suspension moves `IN_PROGRESS` → `SUSPENDED` with no
        preconditions, and resumption returns `SUSPENDED` → `IN_PROGRESS`
        under the same active-window requirement."

        Design: Difficulty/non_linear_state_machine/job_suspend_resume_revert_loop
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-NL2", with_permit=False, with_equipment=False,
        )
        job_id = ctx["job"]["id"]
        suspended = validate_success(api.suspend_job(job_id, SUPERVISOR))
        assert suspended["status"] == "SUSPENDED"
        resumed = validate_success(api.resume_job(job_id, SUPERVISOR))
        assert resumed["status"] == "IN_PROGRESS"


class TestCompletionGatesAndPrecedence:
    def test_complete_in_progress_job_reports_state_error(self, api):
        """PRD §2.7: "Every request passes through a fixed validation
        pipeline, and a failure at an earlier stage is always reported in
        preference to a failure at any later stage." Stage 6 is state
        legality (`ERR_INVALID_STATE`); the permit-release business rule sits
        in stage 7 — completing an `IN_PROGRESS` job therefore reports the
        state failure, not `ERR_PERMIT_NOT_RELEASED`.

        Design: Difficulty/priority_pair_validation_conflict/state_error_masks_safety_error_on_job_complete
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-PP1", with_equipment=False)
        resp = api.complete_job(ctx["job"]["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_job(ctx["job"]["id"])["status"] == "IN_PROGRESS"

    def test_complete_evaluation_job_without_release_reports_safety_error(self, api):
        """PRD §3.3: "Completion of an `EVALUATION` job is gated on the job's
        isolation permit having reached `RELEASED` — completing earlier is
        rejected with `ERR_PERMIT_NOT_RELEASED` — and lands the job in
        `COMPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_masks_safety_error_on_job_complete
        """
        ctx = setup_job_in_evaluation(circuit_ref="CKT-PP1")
        # Job is EVALUATION; the permit is still GROUNDING_VERIFIED.
        resp = api.complete_job(ctx["job"]["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_RELEASED)
        assert get_job(ctx["job"]["id"])["status"] == "EVALUATION"


class TestExistenceVsAuthorization:
    def test_forbidden_role_beats_not_found(self, api):
        """PRD §2.7: "2. **Authorization** — the role is listed for the
        endpoint, else `ERR_FORBIDDEN`." ahead of "4. **Existence** — path
        identifiers are resolved first, validated left to right along the URL,
        and then body foreign-key references in their declared input order;
        the first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_not_found
        """
        create_circuit("CKT-PP3", "KV_25", 500, 2020)
        resp = api.start_job(NON_EXISTENT_UUID, TEST_USERS["field_technician_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_authorized_role_reaches_existence_check(self, api):
        """PRD §2.7: "4. **Existence** — path identifiers are resolved first,
        validated left to right along the URL, and then body foreign-key
        references in their declared input order; the first missing reference
        yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_not_found
        """
        create_circuit("CKT-PP3", "KV_25", 500, 2020)
        resp = api.start_job(NON_EXISTENT_UUID, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRescheduleOcc:
    def test_reschedule_supersede_then_stale_replay_rejected(self, api):
        """PRD §3.3: "A successful reschedule replaces the job's
        `outage_window_id` outright — supersede semantics, with no history
        kept on the job — and increments the job's `version` by one."
        PRD §2.6: "a mismatch with the job's current `version` is likewise
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/reschedule_supersede_then_stale_rejected
        """
        circuit = create_circuit("CKT-X2")
        window1 = create_window(circuit["id"])
        window2 = create_window(
            circuit["id"], window_start="2026-09-01T08:00:00Z",
            window_end="2026-09-01T12:00:00Z",
        )
        approve_window(window1["id"])
        approve_window(window2["id"])
        job = create_job(circuit["id"], window1["id"], approved_budget_cents=800000)
        plan_job(job["id"])
        observed_version = get_job(job["id"])["version"]

        moved = validate_success(api.reschedule_job(
            job["id"],
            {"outage_window_id": window2["id"],
             "expected_test_job_version": observed_version},
            PLANNER,
        ))
        assert moved["outage_window_id"] == window2["id"]
        assert moved["version"] == observed_version + 1

        replay = api.reschedule_job(
            job["id"],
            {"outage_window_id": window1["id"],
             "expected_test_job_version": observed_version},
            PLANNER,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        assert get_job(job["id"])["outage_window_id"] == window2["id"]
