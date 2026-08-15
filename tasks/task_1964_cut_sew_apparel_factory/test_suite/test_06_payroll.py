"""Piece-rate payroll: sweeps, guarantees, and bonuses (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_open_payroll_run,
    calculate_payroll_run,
    get_success_data,
    setup_calculated_payroll_run,
    setup_verified_entry_for_payroll,
    validate_error,
)

CLERK = TEST_USERS["payroll_clerk_headers"]
CLERK2 = TEST_USERS["payroll_clerk2_headers"]
PM = TEST_USERS["plant_manager_headers"]
PM_AS_PC1 = TEST_USERS["pm_as_u_pc1_headers"]
ANY = TEST_USERS["any_headers"]


class TestStraightVsGuaranteedMinimum:
    def test_piece_rate_straight_vs_guaranteed_minimum(self):
        """PRD §3.7: "The day's payable is the greater of the piece total and
        the floor; the `day_topup` is the difference, positive exactly when
        the floor wins." and "the run then records ... `total_piece_cents` as
        the sum of straight piece earnings, `total_topup_cents` as the sum of
        day top-ups ... `total_payable_cents` as the sum of those three
        totals".

        Design: Difficulty/dual_variant_calc/piece_rate_straight_vs_guaranteed_minimum
        """
        ctx = setup_verified_entry_for_payroll(
            order_qty=100, sam_seconds=54, piece_rate_cents=12,
            work_date="2026-08-03", assign_minutes=100,
        )
        run = create_open_payroll_run(CLERK)
        run = calculate_payroll_run(run["id"], run["version"], CLERK)
        # straight: 100 x 12 = 1200
        assert run["total_piece_cents"] == 1200
        # guarantee floor: round(100 * 1500 / 60) = 2500; topup = 2500 - 1200
        assert run["total_topup_cents"] == 1300
        # efficiency 90.0 -> 5% tier: round(1200 * 0.05) = 60
        assert run["total_bonus_cents"] == 60
        assert run["total_payable_cents"] == 2560
        entry = get_success_data(
            api_client.get_piece_work_entry(ctx["entry"]["id"], ANY)
        )
        assert entry["piece_earnings_cents"] == 1200
        assert entry["payable_cents"] == 2560

    def test_guarantee_floor_computed_from_assigned_minutes(self):
        """PRD §3.7: "the day's straight piece total is compared against a
        floor of the operator's assigned minutes that day ... multiplied by a
        guaranteed rate of 1,500 cents per hour and divided by 60, the result
        rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/piece_rate_straight_vs_guaranteed_minimum
        """
        ctx = setup_verified_entry_for_payroll(
            order_qty=100, sam_seconds=54, piece_rate_cents=12,
            work_date="2026-08-03", assign_minutes=100,
        )
        run = create_open_payroll_run(CLERK)
        run = calculate_payroll_run(run["id"], run["version"], CLERK)
        assert run["entry_count"] == 1
        assert run["status"] == "CALCULATED"
        assert run["total_payable_cents"] == (
            run["total_piece_cents"]
            + run["total_topup_cents"]
            + run["total_bonus_cents"]
        )


class TestPinnedEvaluationOrder:
    def test_payroll_totals_pinned_evaluation_order(self):
        """PRD §3.7: "Each operator's `efficiency_pct` is then computed over
        entries in `VERIFIED` or `PAID` status — which deliberately includes
        this run's just-swept `VERIFIED` entries, a pre-pay snapshot, so the
        bonus does not feed back into the efficiency that sizes it."

        Design: Difficulty/combinatorial_formula/payroll_totals_pinned_evaluation_order
        """
        ctx = setup_verified_entry_for_payroll(
            order_qty=100, sam_seconds=54, piece_rate_cents=12,
            work_date="2026-08-03", assign_minutes=100,
        )
        run = create_open_payroll_run(CLERK)
        run = calculate_payroll_run(run["id"], run["version"], CLERK)
        # earned = 100 * 54 / 60 = 90.0 min; attended = 100 -> 90.0 -> 5% tier.
        assert run["total_bonus_cents"] == 60
        assert run["total_piece_cents"] == 1200
        assert run["total_topup_cents"] == 1300
        assert run["total_payable_cents"] == 2560

    def test_sweep_count_and_status_after_calculate(self):
        """PRD §3.7: "The run then records `entry_count` as the size of the
        sweep ... the run moves to `CALCULATED`". PRD §3.7: "The sweep set is
        every `VERIFIED` piece-work entry whose `payroll_run_id` is null and
        whose `work_date` falls within the inclusive period bounds."

        Design: Difficulty/combinatorial_formula/payroll_totals_pinned_evaluation_order
        """
        ctx = setup_verified_entry_for_payroll(
            order_qty=100, sam_seconds=54, piece_rate_cents=12,
            work_date="2026-08-03", assign_minutes=100,
        )
        run = create_open_payroll_run(CLERK)
        run = calculate_payroll_run(run["id"], run["version"], CLERK)
        assert run["entry_count"] == 1
        assert run["status"] == "CALCULATED"
        entry = get_success_data(
            api_client.get_piece_work_entry(ctx["entry"]["id"], ANY)
        )
        assert entry["payroll_run_id"] == run["id"]


class TestPayCascade:
    def test_payroll_pay_cascade_to_operator_metrics(self):
        """PRD §3.7: "Paying moves every swept entry from `VERIFIED` to the
        terminal `PAID` status, finalizing the `payable_cents` the calculate
        stamped; per entry, the operator's `ytd_earnings_cents` increases by
        the entry's `payable_cents`, the operator's `efficiency_pct` is
        recomputed".

        Design: Difficulty/transitive_cascade/payroll_pay_cascade_to_operator_metrics
        """
        ctx = setup_verified_entry_for_payroll(
            order_qty=100, sam_seconds=54, piece_rate_cents=12,
            work_date="2026-08-03", assign_minutes=100,
        )
        run = create_open_payroll_run(CLERK)
        run = calculate_payroll_run(run["id"], run["version"], CLERK)
        get_success_data(
            api_client.decide_payroll_run(run["id"], {"decision": "APPROVE"}, PM)
        )
        run = get_success_data(api_client.pay_payroll_run(run["id"], CLERK))
        assert run["status"] == "PAID"
        entry = get_success_data(
            api_client.get_piece_work_entry(ctx["entry"]["id"], ANY)
        )
        assert entry["status"] == "PAID"
        assert entry["payable_cents"] == 2560
        operator = get_success_data(api_client.get_operator(ctx["operator"]["id"], ANY))
        assert operator["ytd_earnings_cents"] == 2560

    def test_pay_cascade_recomputes_efficiency(self):
        """PRD §3.7: "per entry, the operator's `ytd_earnings_cents` increases
        by the entry's `payable_cents`, the operator's `efficiency_pct` is
        recomputed, and both the operator's and the entry's `version`
        increment".

        Design: Difficulty/transitive_cascade/payroll_pay_cascade_to_operator_metrics
        """
        ctx = setup_verified_entry_for_payroll(
            order_qty=100, sam_seconds=54, piece_rate_cents=12,
            work_date="2026-08-03", assign_minutes=100,
        )
        run = create_open_payroll_run(CLERK)
        run = calculate_payroll_run(run["id"], run["version"], CLERK)
        get_success_data(
            api_client.decide_payroll_run(run["id"], {"decision": "APPROVE"}, PM)
        )
        get_success_data(api_client.pay_payroll_run(run["id"], CLERK))
        operator = get_success_data(api_client.get_operator(ctx["operator"]["id"], ANY))
        # earned 90.0 min over attended 100 min -> 90.0
        assert operator["efficiency_pct"] == pytest.approx(90.0, abs=1e-9)


class TestOccPayrollCalculate:
    def test_occ_payroll_calculate_stale_run_version(self):
        """PRD §2.7: "a calculate carrying the pre-calculation version is
        acting on a stale baseline and is refused with `ERR_STALE_VERSION`
        (HTTP 412), even when the run has since been rejected back to `OPEN`."

        Design: Corner/cross_cutting_layers/occ_payroll_calculate_stale_run_version
        """
        run = create_open_payroll_run(CLERK)
        original_version = run["version"]
        run = calculate_payroll_run(run["id"], original_version, CLERK)
        get_success_data(
            api_client.decide_payroll_run(run["id"], {"decision": "REJECT"}, PM)
        )
        # Run is OPEN again but the original version is stale.
        resp = api_client.calculate_payroll_run(
            run["id"], {"expected_payroll_run_version": original_version}, CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_payroll_calculate_retry_with_fresh_version(self):
        """PRD §2.7: "Calculating a payroll run requires
        `expected_payroll_run_version`, carrying the `version` of the
        `PayrollRun` as the clerk last observed it."

        Design: Corner/cross_cutting_layers/occ_payroll_calculate_stale_run_version
        """
        run = create_open_payroll_run(CLERK)
        original_version = run["version"]
        run = calculate_payroll_run(run["id"], original_version, CLERK)
        get_success_data(
            api_client.decide_payroll_run(run["id"], {"decision": "REJECT"}, PM)
        )
        resp = api_client.calculate_payroll_run(
            run["id"], {"expected_payroll_run_version": original_version}, CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_success_data(api_client.get_payroll_run(run["id"], ANY))
        assert fresh["status"] == "OPEN"
        run = calculate_payroll_run(run["id"], fresh["version"], CLERK)
        assert run["status"] == "CALCULATED"

    def test_occ_stale_version_beats_state_on_recalculate(self):
        """PRD §2.6: "Reviewing a tech pack runs the stale-version check
        (step 5) before the pack's from-state check (step 6)" — and §2.6
        step 5: "Where an endpoint participates in OCC (§2.7), the supplied
        expected version must match the parent's current `version` —
        otherwise `ERR_STALE_VERSION`. This check runs after existence and
        before any state or business rule."

        Design: Corner/validations/occ_stale_version_beats_state_on_recalculate
        """
        run = setup_calculated_payroll_run(CLERK)
        # Run is CALCULATED; replay the stale pre-calculate version: OCC (step
        # 5) fires before the from-state check (step 6), so 412 wins.
        stale_version = run["version"] - 1
        resp = api_client.calculate_payroll_run(
            run["id"], {"expected_payroll_run_version": stale_version}, CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestPayrollStateMachine:
    def test_pay_open_run_returns_payroll_not_approved(self):
        """PRD §3.7: "The run must be `APPROVED`, or the pay request is
        rejected with `ERR_PAYROLL_NOT_APPROVED` (HTTP 409)."

        Design: Corner/state_machines/pay_open_run_returns_payroll_not_approved
        """
        run = create_open_payroll_run(CLERK)
        resp = api_client.pay_payroll_run(run["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PAYROLL_NOT_APPROVED)

    def test_decide_open_run_and_calculate_calculated_run_rejected(self):
        """PRD §3.7: "the run must be `OPEN`, otherwise `ERR_PAYROLL_NOT_OPEN`
        (HTTP 409)" and "the run must be `CALCULATED`, otherwise
        `ERR_PAYROLL_NOT_CALCULATED` (HTTP 409)".

        Design: Corner/errors/decide_open_run_and_calculate_calculated_run_rejected
        """
        run1 = create_open_payroll_run(CLERK)
        resp1 = api_client.decide_payroll_run(run1["id"], {"decision": "APPROVE"}, PM)
        validate_error(resp1, ApiErrorId.ERR_PAYROLL_NOT_CALCULATED)
        run2 = setup_calculated_payroll_run(CLERK)
        # OCC passes with the fresh version; the state check fires.
        resp2 = api_client.calculate_payroll_run(
            run2["id"], {"expected_payroll_run_version": run2["version"]}, CLERK,
        )
        validate_error(resp2, ApiErrorId.ERR_PAYROLL_NOT_OPEN)

    def test_decide_reject_unwinds_calculation(self):
        """PRD §3.7: "Rejection unwinds the calculation: every swept entry's
        `payroll_run_id` is cleared to null and its `payable_cents` to null,
        `calculated_by_user_id` is cleared, `entry_count` and all four totals
        reset to zero, and the run returns to `OPEN`".

        Design: Corner/errors/decide_open_run_and_calculate_calculated_run_rejected
        """
        ctx = setup_verified_entry_for_payroll(
            order_qty=100, sam_seconds=54, piece_rate_cents=12,
            work_date="2026-08-03", assign_minutes=100,
        )
        run = create_open_payroll_run(CLERK)
        run = calculate_payroll_run(run["id"], run["version"], CLERK)
        run = get_success_data(
            api_client.decide_payroll_run(run["id"], {"decision": "REJECT"}, PM)
        )
        assert run["status"] == "OPEN"
        assert run["entry_count"] == 0
        assert run["total_piece_cents"] == 0
        assert run["total_topup_cents"] == 0
        assert run["total_bonus_cents"] == 0
        assert run["total_payable_cents"] == 0
        assert run["calculated_by_user_id"] is None
        entry = get_success_data(
            api_client.get_piece_work_entry(ctx["entry"]["id"], ANY)
        )
        assert entry["payroll_run_id"] is None
        assert entry["payable_cents"] is None


class TestPayrollSod:
    def test_payroll_self_approve_rejected(self):
        """PRD §2.10: "A payroll run may not be decided by the `PayrollClerk`
        who calculated it: the decider's `X-User-ID` must differ from the
        run's `calculated_by_user_id`, or the decision — whether approve or
        reject — is rejected with `ERR_SOD_PAYROLL_SELF_APPROVE` (HTTP 403)."

        Design: Corner/validations/payroll_self_approve_rejected
        """
        run = setup_calculated_payroll_run(CLERK)  # calculated by u-pc1
        resp = api_client.decide_payroll_run(
            run["id"], {"decision": "APPROVE"}, PM_AS_PC1,
        )
        validate_error(resp, ApiErrorId.ERR_SOD_PAYROLL_SELF_APPROVE)
        run_after = get_success_data(api_client.get_payroll_run(run["id"], ANY))
        assert run_after["status"] == "CALCULATED"

    def test_payroll_clerk_cannot_decide_and_plant_manager_cannot_calculate(self):
        """PRD §4: `POST /payroll-runs/{id}/decide` is authorized for
        PlantManager and `POST /payroll-runs/{id}/calculate` for PayrollClerk.
        PRD §2.1: "A request whose authenticated role is not in the endpoint's
        authorized role list is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/payroll_clerk_cannot_decide_and_plant_manager_cannot_calculate
        """
        run1 = create_open_payroll_run(CLERK)
        resp1 = api_client.calculate_payroll_run(
            run1["id"], {"expected_payroll_run_version": run1["version"]}, PM,
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_ROLE)
        run2 = setup_calculated_payroll_run(CLERK)
        resp2 = api_client.decide_payroll_run(
            run2["id"], {"decision": "APPROVE"}, CLERK2,
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_ROLE)
