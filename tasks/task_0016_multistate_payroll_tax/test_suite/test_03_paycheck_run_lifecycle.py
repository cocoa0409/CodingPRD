"""PaycheckRun state machine, approve/reject/pay/void, SoD, cascades.

Drives queue (A) instances on rules 3 (non_linear_state_machine),
4 (transitive_cascade), 5 (priority_pair_validation_conflict),
6 (boundary_precision_check pay_period_overlap),
7 (cross_entity_state_dependency), 8 (resource_temporal_overlap),
9 (compensating_invariant). Plus corner state_machines + entities.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    set_clock,
    seed_federal_and_california_2025,
    setup_employee_with_filed_w4,
    setup_approved_regular_run,
    setup_paid_regular_run,
    create_employee,
    terminate_employee,
    create_and_file_w4,
    create_draft_paycheck_run,
    attach_regular_paycheck,
    approve_run,
    pay_run,
    void_run,
    seed_employee_ytd,
    create_garnishment_order,
    get_employee,
    get_paycheck,
    get_paycheck_run,
    get_garnishment_order,
    find_remittance,
    create_paycheck_run_payload,
    pay_paycheck_run_payload,
    create_paycheck_payload,
    regular_paycheck_payload,
    update_employee_status_payload,
    create_garnishment_order_payload,
    TEST_USERS,
    make_preparer_headers,
    make_approver_headers,
)


# =========================================================================
# Queue (A) Difficulty — rule 3 non_linear_state_machine (instance 1)
# =========================================================================

class TestPaycheckRunBranchingRevert:
    """APPROVED → DRAFT revert via /reject per PRD §3.6."""

    def test_reject_returns_approved_run_to_draft_and_clears_approver(self, api):
        """PRD §3.6: "Rejecting an `APPROVED` run reverts `PaycheckRun.status`
        to `DRAFT` and clears `approved_by_user_id` to null"

        Design: Difficulty/non_linear_state_machine/paycheckrun_branching_revert_approved_to_draft
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, approved, paycheck = setup_approved_regular_run()
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] is not None

        rejected_res = api_client.reject_paycheck_run(
            approved["id"], TEST_USERS["payroll_approver_headers"]
        )
        rejected = validate_success(rejected_res, expected_status=200)
        assert rejected["status"] == "DRAFT"
        assert rejected.get("approved_by_user_id") is None
        # child paycheck stays PENDING since the run never reached PAID
        pay_check = get_paycheck(paycheck["id"])
        assert pay_check["status"] == "PENDING"


# =========================================================================
# Queue (A) Difficulty — rule 4 transitive_cascade (instance 1, depth-4)
# =========================================================================

class TestPayCascadeDepth4:
    """POST /paycheck-runs/{id}/pay cascades 4 hops per PRD §3.6."""

    def test_pay_cascade_propagates_to_paycheck_garnishment_remittance_and_ytd(self, api):
        """PRD §3.6: "Each child `Paycheck` then transitions from `PENDING` to
        `PAID`."
        PRD §3.6: "For each child paycheck, the employee's accumulators advance:
        `ytd_wages_cents` increases by that paycheck's `gross_wages_cents`;
        `ytd_fed_withheld_cents` increases by the paycheck's post-reconciliation
        `fed_withheld_cents`"
        PRD §3.6: "For each `GarnishmentDeduction` on each child paycheck, the
        corresponding `GarnishmentOrder` has its `balance_remaining_cents`
        reduced by the deduction's `amount_cents`; if that balance reaches zero,
        the order transitions from `ACTIVE` to `SATISFIED`."

        One $2000 REGULAR paycheck + one CHILD_SUPPORT order with original_balance=30000;
        the single deduction satisfies the order on /pay.

        Design: Difficulty/transitive_cascade/paycheck_run_pay_cascade_depth_4
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        g = create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=30000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])
        approve_run(run["id"])
        paid = pay_run(run["id"])

        assert paid["status"] == "PAID"
        # hop 1: child Paycheck PENDING -> PAID
        pay_after = get_paycheck(pay["id"])
        assert pay_after["status"] == "PAID"
        # hop 3: GarnishmentOrder balance debited; reaches 0 -> SATISFIED
        g_after = get_garnishment_order(g["id"])
        assert g_after["balance_remaining_cents"] == 0
        assert g_after["status"] == "SATISFIED"
        # hop 2: Employee YTD accumulators advance
        emp_after = get_employee(emp["id"])
        assert emp_after["ytd_wages_cents"] == 200000
        assert emp_after["ytd_fed_withheld_cents"] == 16357


# =========================================================================
# Queue (A) Difficulty — rule 5 priority_pair_validation_conflict (instance 1)
# =========================================================================

class TestPriorityPairStateBeatsEmployeeNotActive:
    """State guard (priority 5) fires before EMPLOYEE_NOT_ACTIVE (priority 6) per PRD §2.6."""

    def test_approve_already_paid_run_with_terminated_employee_returns_invalid_state(self, api):
        """PRD §2.6: "the response always reflects the **first** failing rule in
        priority order"
        PRD §2.6: "state-machine guards (`ERR_INVALID_STATE`), then
        employee-not-active blocking (`ERR_EMPLOYEE_NOT_ACTIVE`)"

        Setup: PaycheckRun is already PAID (state guard violated). After the
        pay run, Employee is TERMINATED. Re-attempting /approve must fail with
        ERR_INVALID_STATE (priority 5) — not ERR_EMPLOYEE_NOT_ACTIVE.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_pay_with_terminated_employee
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, paid_run, _ = setup_paid_regular_run()
        terminate_employee(emp["id"])
        # The PaycheckRun is currently PAID; /approve must be rejected with ERR_INVALID_STATE.
        # Use a non-SoD approver to ensure the priority-5 state guard fires (not priority-7 SoD).
        res = api_client.approve_paycheck_run(
            paid_run["id"], make_approver_headers("U_APPR_NEW")
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =========================================================================
# Queue (A) Difficulty — rule 5 priority_pair_validation_conflict (instance 2)
# =========================================================================

class TestPriorityPairSodVsBusinessFiscal:
    """SoD (priority 7) per PRD §3.6 segregation-of-duties."""

    def test_self_approval_triggers_sod_violation(self, api):
        """PRD §3.6: "A preparer who attempts to approve their own run is
        rejected with `ERR_SOD_VIOLATION` and HTTP 403."
        PRD §3.6: "the approver's `X-User-ID` must differ from the run's
        `prepared_by_user_id` (segregation of duties)"

        Setup: U_PREP creates DRAFT run with a paycheck; the same U_PREP id
        attempts to call /approve (as PayrollApprover). The role is sufficient
        but the X-User-ID match violates SoD.

        Design: Difficulty/priority_pair_validation_conflict/sod_business_safety_beats_fiscal_open_run_blocks
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        prep_headers = make_preparer_headers("U_PREP")
        run = create_draft_paycheck_run(preparer_headers=prep_headers)
        attach_regular_paycheck(run["id"], emp["id"], preparer_headers=prep_headers)

        # Self-approval: approver X-User-ID == preparer X-User-ID
        self_approve_headers = make_approver_headers("U_PREP")
        res = api_client.approve_paycheck_run(run["id"], self_approve_headers)
        validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)


# =========================================================================
# Queue (A) Difficulty — rule 6 boundary_precision_check (instance 2)
# =========================================================================

class TestPayPeriodOverlapBoundary:
    """Closed-closed interval overlap per PRD §3.3."""

    def test_new_run_starting_at_prior_runs_end_is_rejected(self, api):
        """PRD §3.3: "If the proposed interval `[pay_period_start,
        pay_period_end]` (closed on both ends — a point overlap at the boundary
        counts as a conflict, so `start == prior.end` is a conflict) collides
        with any non-`VOID` `PaycheckRun` already holding a `Paycheck` for one
        of the to-be-added employees, the create is rejected with
        `ERR_PAY_PERIOD_OVERLAP`."

        Run A: 2025-11-01..2025-11-15T23:59:59.999Z with a paycheck for emp.
        Run B: starts at exactly 2025-11-15T23:59:59.999Z (touch point) →
        rejected on the second POST /paycheck-runs that would attach the
        same employee. (The scaffold encodes attempting the second create
        directly; both formulations are PRD-valid because the closed-closed
        check applies to runs already holding paychecks for the employee.)

        Design: Difficulty/boundary_precision_check/pay_period_overlap_closed_closed_point_touch
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run_a = create_draft_paycheck_run(
            pay_period_start="2025-11-01T00:00:00.000Z",
            pay_period_end="2025-11-15T23:59:59.999Z",
            pay_date="2025-11-15T00:00:00.000Z",
        )
        attach_regular_paycheck(run_a["id"], emp["id"])
        # Second run touches A at the start instant; create a run plus attempt
        # to attach a paycheck for the same employee, which must be rejected.
        run_b = create_draft_paycheck_run(
            pay_period_start="2025-11-15T23:59:59.999Z",
            pay_period_end="2025-11-30T23:59:59.999Z",
            pay_date="2025-11-30T00:00:00.000Z",
        )
        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=run_b["id"],
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        validate_error(res, "ERR_PAY_PERIOD_OVERLAP", expected_status=422)


# =========================================================================
# Queue (A) Difficulty — rule 7 cross_entity_state_dependency (instance 1)
# =========================================================================

class TestPaycheckCreateRequiresActiveEmployee:
    """Cross-entity state guard — POST /paychecks needs ACTIVE/ON_LEAVE Employee."""

    def test_paycheck_create_against_terminated_employee_is_rejected(self, api):
        """PRD §2.6 / §3.3: "the employee must currently be in `ACTIVE` or
        `ON_LEAVE` status (a `TERMINATED` employee yields
        `ERR_EMPLOYEE_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/paycheck_create_requires_employee_active_pair_paycheck_employee
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        terminate_employee(emp["id"])

        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=run["id"],
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        validate_error(res, "ERR_EMPLOYEE_NOT_ACTIVE", expected_status=409)


# =========================================================================
# Queue (A) Difficulty — rule 8 resource_temporal_overlap (instance 1)
# =========================================================================

class TestPayPeriodOverlapPointTouch:
    """Closed-closed point-touch interval semantics scoped to employee."""

    def test_two_runs_touching_at_boundary_with_shared_employee_overlap(self, api):
        """PRD §3.3: "If the proposed interval `[pay_period_start,
        pay_period_end]` (closed on both ends — a point overlap at the boundary
        counts as a conflict, so `start == prior.end` is a conflict) collides
        with any non-`VOID` `PaycheckRun` already holding a `Paycheck` for one
        of the to-be-added employees, the create is rejected with
        `ERR_PAY_PERIOD_OVERLAP`."

        Run A spans 2025-11-01..2025-11-15 with a paycheck for emp.
        Run B spans 2025-11-15..2025-11-30 (touches A at 2025-11-15). Attaching
        a paycheck for the same employee to run B must be rejected.

        Design: Difficulty/resource_temporal_overlap/pay_period_closed_closed_overlap_on_employee
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run_a = create_draft_paycheck_run(
            pay_period_start="2025-11-01T00:00:00.000Z",
            pay_period_end="2025-11-15T00:00:00.000Z",
            pay_date="2025-11-15T00:00:00.000Z",
        )
        attach_regular_paycheck(run_a["id"], emp["id"])
        run_b = create_draft_paycheck_run(
            pay_period_start="2025-11-15T00:00:00.000Z",
            pay_period_end="2025-11-30T00:00:00.000Z",
            pay_date="2025-11-30T00:00:00.000Z",
        )
        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=run_b["id"],
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        validate_error(res, "ERR_PAY_PERIOD_OVERLAP", expected_status=422)


# =========================================================================
# Queue (A) Difficulty — rule 9 compensating_invariant (instances 1 + 2)
# =========================================================================

class TestVoidPreservesEmployeeYtdInvariant:
    """PAID→VOID reverses YTD increments exactly per PRD §3.6."""

    def test_void_run_restores_employee_ytd_to_pre_pay_baseline(self, api):
        """PRD §3.6: "For each child paycheck, the employee's year-to-date
        accumulators are reversed by the same amounts they were incremented by."
        PRD §2.9: "The reverse cascade fires when a `PaycheckRun` is voided:
        children flip to `VOID`, year-to-date accumulators reverse"

        Seed Employee YTD to a non-zero baseline; run the PAID cascade; void
        the run; YTD fields must return to the seeded baseline.

        Design: Difficulty/compensating_invariant/void_run_preserves_employee_ytd_quantities
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        seed_employee_ytd(
            emp["id"],
            ytd_wages_cents=500000,
            ytd_fed_withheld_cents=40000,
            ytd_ss_wages_cents=500000,
            ytd_medicare_wages_cents=500000,
        )
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        attach_regular_paycheck(run["id"], emp["id"])
        approve_run(run["id"])
        pay_run(run["id"])
        void_run(run["id"])

        emp_after = get_employee(emp["id"])
        assert emp_after["ytd_wages_cents"] == 500000, \
            f"ytd_wages_cents must reverse to baseline 500000, got {emp_after['ytd_wages_cents']}"
        assert emp_after["ytd_fed_withheld_cents"] == 40000
        assert emp_after["ytd_ss_wages_cents"] == 500000
        assert emp_after["ytd_medicare_wages_cents"] == 500000
        run_after = get_paycheck_run(run["id"])
        assert run_after["status"] == "VOID"


class TestVoidPreservesGarnishmentBalanceInvariant:
    """PAID→VOID restores garnishment balance and reverts SATISFIED → ACTIVE."""

    def test_void_run_restores_garnishment_balance_and_status(self, api):
        """PRD §3.6: "For each `GarnishmentDeduction`, `balance_remaining_cents`
        on the corresponding order is increased back by `amount_cents`; if the
        order was previously `SATISFIED` and is now above zero again, it
        reverts to `ACTIVE`."

        Garnishment with original_balance=30000 fully satisfied by one $2000
        paycheck. Void → balance returns to 30000, status returns to ACTIVE.

        Design: Difficulty/compensating_invariant/void_run_preserves_garnishment_balance_remaining
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        g = create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=30000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        run = create_draft_paycheck_run()
        attach_regular_paycheck(run["id"], emp["id"])
        approve_run(run["id"])
        pay_run(run["id"])

        # Pre-void: order SATISFIED with balance=0
        g_paid = get_garnishment_order(g["id"])
        assert g_paid["status"] == "SATISFIED"
        assert g_paid["balance_remaining_cents"] == 0

        void_run(run["id"])
        g_voided = get_garnishment_order(g["id"])
        assert g_voided["balance_remaining_cents"] == 30000, \
            f"balance must restore to 30000, got {g_voided['balance_remaining_cents']}"
        assert g_voided["status"] == "ACTIVE", \
            f"SATISFIED must revert to ACTIVE after void, got {g_voided['status']}"


# =========================================================================
# Queue (B) Corner — state_machines section
# =========================================================================

class TestPaycheckRunInitialState:
    def test_post_paycheck_run_creates_draft(self, api):
        """PRD §3.3: "The new run is created in `DRAFT`"

        Design: Corner/state_machines/paycheckrun_initial_state_is_draft
        """
        run = create_draft_paycheck_run()
        assert run["status"] == "DRAFT"


class TestPaycheckRunInvalidTransitionDraftToPay:
    def test_pay_against_draft_run_rejected_invalid_state(self, api):
        """PRD §3.6: "Paying a run that is not currently `APPROVED`, or a run
        whose child paychecks are not all in `PENDING`, is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/paycheckrun_invalid_transition_from_draft_to_pay
        """
        run = create_draft_paycheck_run()
        res = api_client.pay_paycheck_run(
            run["id"], pay_paycheck_run_payload(), TEST_USERS["payroll_approver_headers"]
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestPaycheckRunTerminalVoidLockdown:
    def test_void_run_rejects_subsequent_approve(self, api):
        """PRD §3.6 (run is VOID) plus §1.2 PaycheckRun terminal_states=[VOID]
        and PRD §2.6 §1.4 priority-5 state guard: "the response always reflects
        the **first** failing rule in priority order, so test fixtures can
        construct exactly one failing condition at a time. The priority sequence
        is fixed: ... then state-machine guards (`ERR_INVALID_STATE`)"

        After VOID, /approve fires the priority-5 ERR_INVALID_STATE state guard.

        Design: Corner/state_machines/paycheckrun_terminal_void_no_transition
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, paid_run, _ = setup_paid_regular_run()
        # Void it
        void_run(paid_run["id"])
        # Attempt to approve a VOID run with a fresh approver id (avoid SoD)
        res = api_client.approve_paycheck_run(
            paid_run["id"], make_approver_headers("U_APPR_OTHER")
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
