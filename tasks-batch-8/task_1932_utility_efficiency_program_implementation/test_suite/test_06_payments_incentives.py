"""Incentive calculation (provisional vs final variants, tier structure, cap)
and the disburse/reconcile ledger invariant."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    complete_work_order,
    create_approved_project,
    create_completed_project,
    create_inspector,
    create_proposed_project,
    create_work_order,
    get_program,
    make_inspector_headers,
    record_inspection,
    schedule_inspection,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestProvisionalVsFinalOnProject:
    """PROVISIONAL (floor, raw savings) at approval vs FINAL (cost-overrun
    adjusted, round-half-up) at completion, for measure_cost_cents = 1,000,000
    (above the 500,000-cent baseline) and 4,000 kWh savings."""

    def _setup(self, api):
        set_clock()
        return create_approved_project(
            program_overrides={"budget_cents": 200000},
            lead_overrides={"estimated_annual_kwh_savings": 4000},
            project_overrides={"measure_cost_cents": 1000000,
                               "estimated_annual_kwh_savings": 4000},
        )

    def test_provisional_incentive_uses_raw_savings_and_floor(self, api, pm_headers):
        """PRD 3.4: "The provisional incentive is a two-tier marginal rate
        applied to the project's `estimated_annual_kwh_savings`: the first
        2,000 kWh of annual savings earns 25 cents per kWh, and any savings
        above 2,000 kWh earns 12 cents per kWh; the two portions are summed,
        the total is clamped so it never exceeds 80,000 cents, and the
        provisional figure is floored to whole cents. A successful approval
        stores this result in the project's
        `incentive_amount_provisional_cents`, copies it into
        `incentive_amount_cents`".
        2000*25 + 2000*12 = 74,000 (under the cap), floored: 74,000.

        Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_on_project
        """
        ctx = self._setup(api)
        project = ctx["project"]
        assert project["incentive_amount_provisional_cents"] == 74000
        assert project["incentive_amount_cents"] == 74000
        payment = ctx["payment"]
        assert payment is not None and payment["status"] == "DRAFT"
        assert payment["amount_provisional_cents"] == 74000

    def test_final_incentive_applies_cost_overrun_adjustment(self, api, pm_headers):
        """PRD 3.7: "when the project's `measure_cost_cents` exceeds the
        measure-cost baseline of 500,000 cents, the eligible savings are scaled
        down by the ratio of that baseline to the actual installed cost — a
        factor strictly below one that shrinks the eligible savings in
        proportion to the overrun — while an installed cost at or below the
        baseline leaves the savings figure untouched."
        PRD 3.7: "The computed final amount is written to the payment's
        `amount_cents` and replaces the provisional figure in the project's
        `incentive_amount_cents`, and the difference between final and
        provisional is journaled on the payment as `reconciliation_delta_cents`".
        Adjusted savings = 4000 * (500000/1000000) = 2000 kWh -> 2000*25 =
        50,000; delta = 50,000 - 74,000 = -24,000.

        Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_on_project
        """
        ctx = self._setup(api)
        # Drive the same project to COMPLETED via the inspection path.
        ctr_id = ctx["contractor"]["id"]
        wo = create_work_order(ctx["project"]["id"], ctr_id,
                               scheduled_on="2026-08-02T00:00:00Z", duration_hours=4)
        create_inspector()
        wo = complete_work_order(wo["id"], ctr_id)
        inspection = schedule_inspection(
            wo["id"], ctx["project"]["id"], wo["assigned_inspector_id"],
            scheduled_on="2026-08-03T00:00:00Z")
        record_inspection(inspection["id"], wo["assigned_inspector_id"],
                          outcome="PASS", score_bps=9000)
        project = validate_success(api.get_project(ctx["project"]["id"], pm_headers))
        assert project["status"] == "COMPLETED"
        assert project["incentive_amount_cents"] == 50000
        payments = validate_success(
            api.list_incentive_payments(pm_headers,
                                        params={"project_id": ctx["project"]["id"]}))
        payment = payments[0]
        assert payment["status"] == "AUTHORIZED"
        assert payment["amount_cents"] == 50000
        assert payment["amount_provisional_cents"] == 74000
        assert payment["reconciliation_delta_cents"] == 50000 - 74000
        assert payment["amount_cents"] != payment["amount_provisional_cents"]


class TestTieredIncentiveWithCapAndCostAdjustment:
    def test_cap_binds_at_80000_cents(self, api, pm_headers):
        """PRD 3.4: "the first 2,000 kWh of annual savings earns 25 cents per
        kWh, and any savings above 2,000 kWh earns 12 cents per kWh; the two
        portions are summed, the total is clamped so it never exceeds 80,000
        cents, and the provisional figure is floored to whole cents."
        2000*25 + 3000*12 = 86,000 -> clamped to 80,000.

        Design: Difficulty/combinatorial_formula/tiered_incentive_with_cap_and_cost_adjustment
        """
        set_clock()
        ctx = create_approved_project(
            program_overrides={"budget_cents": 500000},
            lead_overrides={"estimated_annual_kwh_savings": 5000},
            project_overrides={"measure_cost_cents": 400000,
                               "estimated_annual_kwh_savings": 5000,
                               "incentive_recipient": "CUSTOMER"},
        )
        assert ctx["project"]["incentive_amount_provisional_cents"] == 80000
        assert ctx["project"]["incentive_amount_cents"] == 80000

    def test_tier_arithmetic_below_cap(self, api, pm_headers):
        """PRD 3.4: "the first 2,000 kWh of annual savings earns 25 cents per
        kWh, and any savings above 2,000 kWh earns 12 cents per kWh; the two
        portions are summed, the total is clamped so it never exceeds 80,000
        cents, and the provisional figure is floored to whole cents."
        2000*25 + 1000*12 = 62,000 (under the cap, no clamp).

        Design: Difficulty/combinatorial_formula/tiered_incentive_with_cap_and_cost_adjustment
        """
        set_clock()
        ctx = create_approved_project(
            program_overrides={"budget_cents": 500000},
            lead_overrides={"estimated_annual_kwh_savings": 3000},
            project_overrides={"measure_cost_cents": 400000,
                               "estimated_annual_kwh_savings": 3000,
                               "incentive_recipient": "CUSTOMER"},
        )
        assert ctx["project"]["incentive_amount_provisional_cents"] == 62000
        assert ctx["project"]["incentive_amount_cents"] == 62000


class TestDisburseReconcileConservesPaid:
    """Payment ledger invariant: disburse pays the provisional up front;
    reconcile trues paid_cents up to exactly the final amount."""

    def _setup_authorized_payment(self, api):
        """Completed project with prov 74,000 / final 50,000 / delta -24,000."""
        set_clock()
        return create_completed_project(
            pass_score_bps=9000,
            program_overrides={"budget_cents": 500000},
            lead_overrides={"estimated_annual_kwh_savings": 4000},
            project_overrides={"measure_cost_cents": 1000000,
                               "estimated_annual_kwh_savings": 4000},
        )

    def test_disburse_pays_provisional_up_front(self, api, pm_headers):
        """PRD 3.7: "Disbursement by a `ProgramManager` moves a payment
        `AUTHORIZED` → `PAID` and adds the provisional amount,
        `amount_provisional_cents`, to the program's `paid_cents` — the
        provisional is paid up front, with the delta settled afterward."

        Design: Difficulty/compensating_invariant/payment_disburse_reconcile_conserves_paid_plus_delta
        """
        ctx = self._setup_authorized_payment(api)
        payment = ctx["payment"]
        assert payment["status"] == "AUTHORIZED"
        assert payment["amount_provisional_cents"] == 74000
        assert payment["amount_cents"] == 50000
        assert payment["reconciliation_delta_cents"] == -24000
        validate_success(api.disburse_payment(payment["id"], pm_headers), 200)
        program = get_program(ctx["program"]["id"])
        assert program["paid_cents"] == 74000

    def test_reconcile_brings_paid_to_final_amount(self, api, pm_headers):
        """PRD 3.7: "A positive delta is added to the program's `paid_cents`
        as a top-up payment bringing the total to the final amount; a negative
        delta is subtracted in absolute terms as a clawback, again bringing the
        total to the final amount. Either way, a reconciled payment has
        contributed exactly its final `amount_cents` to the program".
        74,000 + (-24,000) = 50,000 == final amount_cents.

        Design: Difficulty/compensating_invariant/payment_disburse_reconcile_conserves_paid_plus_delta
        """
        ctx = self._setup_authorized_payment(api)
        payment = ctx["payment"]
        validate_success(api.disburse_payment(payment["id"], pm_headers), 200)
        reconciled = validate_success(api.reconcile_payment(payment["id"], pm_headers), 200)
        assert reconciled["status"] == "RECONCILED"
        program = get_program(ctx["program"]["id"])
        assert program["paid_cents"] == 74000 - 24000
        assert program["paid_cents"] == reconciled["amount_cents"]


class TestBudgetCommitCancelConservesCommitted:
    def test_approve_commits_incentive_amount(self, api, pm_headers):
        """PRD 2.9: "it grows by a project's incentive amount at approval, and
        it is released when an in-flight project is cancelled."
        PRD 3.4: "The program's `committed_cents` grows by the incentive
        amount and the program's `version` increments. In the same atomic
        step, an incentive payment shell is created in `DRAFT`".
        100 kWh * 25 cents = 2,500 committed.

        Design: Difficulty/compensating_invariant/budget_commit_cancel_conserves_committed
        """
        set_clock()
        ctx = create_proposed_project(
            program_overrides={"budget_cents": 100000},
            lead_overrides={"estimated_annual_kwh_savings": 100},
            project_overrides={"estimated_annual_kwh_savings": 100},
        )
        before = get_program(ctx["program"]["id"])
        assert before["committed_cents"] == 0
        approved = validate_success(
            api.approve_project(ctx["project"]["id"], before["version"], PM), 200)
        assert approved["incentive_amount_cents"] == 2500
        after = get_program(ctx["program"]["id"])
        assert after["committed_cents"] == 2500
        assert after["version"] == before["version"] + 1
        payments = validate_success(
            api.list_incentive_payments(PM, params={"project_id": ctx["project"]["id"]}))
        assert len(payments) == 1
        assert payments[0]["status"] == "DRAFT"
        assert payments[0]["amount_provisional_cents"] == 2500

    def test_cancel_releases_committed_amount(self, api, pm_headers):
        """PRD 3.4: "From `APPROVED`, the draft payment is voided (`DRAFT` →
        `VOID`) and the program's `committed_cents` is decremented by the
        project's incentive amount."
        After approve (2,500) then cancel, committed_cents returns to 0.

        Design: Difficulty/compensating_invariant/budget_commit_cancel_conserves_committed
        """
        set_clock()
        ctx = create_approved_project(
            program_overrides={"budget_cents": 100000},
            lead_overrides={"estimated_annual_kwh_savings": 100},
            project_overrides={"estimated_annual_kwh_savings": 100},
        )
        assert get_program(ctx["program"]["id"])["committed_cents"] == 2500
        validate_success(api.cancel_project(ctx["project"]["id"], PM), 200)
        program = get_program(ctx["program"]["id"])
        assert program["committed_cents"] == 0
        payment = validate_success(api.get_incentive_payment(ctx["payment"]["id"], PM))
        assert payment["status"] == "VOID"


class TestReconcileZeroDeltaRejected:
    def test_reconcile_with_zero_delta_rejected(self, api, pm_headers):
        """PRD 3.7: "Reconciliation moves a payment `PAID` → `RECONCILED` and
        exists only when there is something to settle: a reconcile requested
        on a payment whose `reconciliation_delta_cents` is zero is refused
        with `ERR_NOTHING_TO_RECONCILE`."
        With measure_cost_cents at or below the 500,000-cent baseline the
        final equals the provisional, so the delta is zero.

        Design: Corner/validations/reconcile_with_zero_delta_rejected
        """
        set_clock()
        ctx = create_completed_project(
            pass_score_bps=9000,
            program_overrides={"budget_cents": 500000},
            lead_overrides={"estimated_annual_kwh_savings": 100},
            project_overrides={"measure_cost_cents": 100000,
                               "estimated_annual_kwh_savings": 100},
        )
        payment = ctx["payment"]
        assert payment["reconciliation_delta_cents"] == 0
        validate_success(api.disburse_payment(payment["id"], pm_headers), 200)
        resp = api.reconcile_payment(payment["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_RECONCILE)


class TestPaymentRbac:
    def test_inspector_cannot_disburse_payment(self, api, pm_headers):
        """PRD 2.6: "Authentication and role authorization come first (§2.1).
        Path-existence resolution follows" — so an unauthorized role is
        rejected before any resource lookup.
        PRD 2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the per-endpoint role
        assignments appear in §4." (§4: disburse is ProgramManager-only.)

        Design: Corner/roles/inspector_cannot_disburse_payment
        """
        inspector = validate_success(
            api.create_inspector(
                {"full_name": "IRD", "license_number": "I-IRD",
                 "excluded_contractor_ids": []},
                pm_headers),
            expected_status=201,
        )
        resp = api.disburse_payment(
            NON_EXISTENT_UUID, make_inspector_headers(inspector["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
