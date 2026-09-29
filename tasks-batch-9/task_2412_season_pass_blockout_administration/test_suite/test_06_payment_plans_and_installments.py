"""Payment plan enrolment, amortisation and the installment schedule."""

from test_helpers import (
    BRONZE,
    GOLD,
    ApiErrorId,
    BillingStatus,
    InstallmentStatus,
    PassStatus,
    PaymentMode,
    PlanStatus,
    ProgramStatus,
    assert_installment_schedule,
    assert_installment_statuses,
    assert_installments_sum_to_financed,
    assert_instant_equals,
    assert_ledger,
    assert_pass_dimensions,
    assert_plan_amortization,
    build_active_pass,
    build_plan,
    build_program,
    clerk_headers,
    get_pass,
    get_plan,
    plan_installments,
    settle_installment,
    settle_payload,
    validate_error,
    validate_success,
)


class TestPlanAmortisationResidual:
    """A financed principal that does not divide evenly lands on the last row."""

    def test_seven_installments_split_25500_into_six_of_3643_and_a_final_3642(self, api, default_clock):
        """The level payment and the residual match the PRD's own worked example.

        PRD: "Worked through: a pass with 30000 cents outstanding, a 6000-cent down
        payment and seven installments finances 30000 less 6000 plus 1500, which is
        25500; dividing by seven and rounding half up gives a level payment of 3643
        cents for sequences one through six, totalling 21858, leaving 25500 less
        21858, which is 3642 cents, for sequence seven."

        Design: Difficulty/combinatorial_formula/plan_amortization_residual_on_final_installment
        """
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="GOLD", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )

        plan_ctx = build_plan(api, pass_ctx.id, 6000, 7, "2026-09-01")

        assert plan_ctx.plan["setup_fee_cents"] == 1500, (
            "the enrolment fee charged onto the pass should be 1500 cents, "
            f"got {plan_ctx.plan['setup_fee_cents']!r}"
        )
        assert_plan_amortization(
            plan_ctx.plan, financed=25500, monthly=3643, final=3642, installment_count=7
        )
        assert_installment_schedule(
            plan_ctx.installments,
            [
                (1, 3643, "2026-09-01"),
                (2, 3643, "2026-10-01"),
                (3, 3643, "2026-11-01"),
                (4, 3643, "2026-12-01"),
                (5, 3643, "2027-01-01"),
                (6, 3643, "2027-02-01"),
                (7, 3642, "2027-03-01"),
            ],
        )

    def test_enrolment_bills_the_setup_fee_and_credits_the_down_payment(self, api, default_clock):
        """The pass ledger after enrolment matches the schedule invariant.

        PRD: "the sum of `amount_cents` across all installments of the plan equals
        `financed_amount_cents`, and equals the pass's `outstanding_balance_cents`
        immediately after the plan is created, once the setup fee has been billed and
        the down payment credited."

        Design: Difficulty/combinatorial_formula/plan_amortization_residual_on_final_installment
        """
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="GOLD", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )

        plan_ctx = build_plan(api, pass_ctx.id, 6000, 7, "2026-09-01")

        assert_installments_sum_to_financed(plan_ctx.installments, 25500)
        assert plan_ctx.plan["plan_status"] == PlanStatus.ACTIVE.value, (
            f"a new plan should open ACTIVE, got {plan_ctx.plan['plan_status']!r}"
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert_ledger(pass_row, contract=30000, billed=31500, paid=6000, credited=0, outstanding=25500)
        assert_pass_dimensions(pass_row, billing_status=BillingStatus.PLAN_CURRENT.value)


class TestPlanInstallmentHalfCentRounding:
    """A principal whose sixth is exactly x.5 cents rounds the level payment up."""

    def test_10503_over_six_rounds_half_up_to_1751(self, api, default_clock):
        """10503 divided by six is exactly 1750.5, which rounds half up to 1751.

        PRD: "`monthly_amount_cents` is `financed_amount_cents` divided by
        `installment_count`, rounded half up to a whole number of cents. Every
        installment from `sequence_no` 1 through `installment_count` minus 1 carries
        that figure as its `amount_cents`."

        Design: Difficulty/boundary_precision_check/plan_installment_rounds_half_up_at_exact_half_cent
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )

        plan_ctx = build_plan(api, pass_ctx.id, 2997, 6, "2026-09-01")

        assert plan_ctx.plan["financed_amount_cents"] == 10503, (
            "12000 outstanding less a 2997 down payment plus the 1500 fee is 10503, "
            f"got {plan_ctx.plan['financed_amount_cents']!r}"
        )
        assert plan_ctx.plan["monthly_amount_cents"] == 1751, (
            "10503 / 6 is exactly 1750.5 and must round half up to 1751, "
            f"got {plan_ctx.plan['monthly_amount_cents']!r}"
        )
        assert [row["amount_cents"] for row in plan_ctx.installments[:5]] == [1751] * 5, (
            "sequences one through five should each carry the level payment, got "
            f"{[row['amount_cents'] for row in plan_ctx.installments[:5]]}"
        )

    def test_the_final_installment_absorbs_the_rounding_up(self, api, default_clock):
        """Rounding the level payment up leaves the last row three cents short.

        PRD: "Rounding is introduced at stage two and nowhere else; the final
        installment takes whatever remainder that rounding produced, which means it
        may be a cent or two below — or above — the level payment."

        Design: Difficulty/boundary_precision_check/plan_installment_rounds_half_up_at_exact_half_cent
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )

        plan_ctx = build_plan(api, pass_ctx.id, 2997, 6, "2026-09-01")

        assert_plan_amortization(
            plan_ctx.plan, financed=10503, monthly=1751, final=1748, installment_count=6
        )
        assert plan_ctx.installment(6)["amount_cents"] == 1748, (
            "10503 less five payments of 1751 leaves 1748 for the last installment, "
            f"got {plan_ctx.installment(6)['amount_cents']!r}"
        )
        assert_installments_sum_to_financed(plan_ctx.installments, 10503)
        pass_row = get_pass(api, pass_ctx.id)
        assert_ledger(pass_row, billed=13500, paid=2997, credited=0, outstanding=10503)
        assert_pass_dimensions(pass_row, billing_status=BillingStatus.PLAN_CURRENT.value)


class TestFinalSettlementCompletesThePlan:
    """The last payment closes the plan and pays the pass in full."""

    def _plan_of_four(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        return program, pass_ctx, plan_ctx

    def test_settling_the_last_installment_completes_the_plan_and_pays_the_pass(
        self, api, default_clock
    ):
        """With nothing scheduled or missed left, both records move up together.

        PRD: "If after the write the active plan holds no installment at all in
        `SCHEDULED` or in `MISSED`, the plan moves `ACTIVE → COMPLETED` with its `version`
        incremented by 1, and the pass's `billing_status` moves `PLAN_CURRENT →
        PAID_IN_FULL` with `outstanding_balance_cents` recomputed — which lands at 0 when no
        upgrade balance remains outstanding — and the pass's `version` increments by 1."

        Design: Corner/state_machines/final_installment_settlement_completes_plan_and_pays_pass_in_full
        """
        _, pass_ctx, plan_ctx = self._plan_of_four(api)

        for sequence_no in (1, 2, 3):
            settle_installment(api, plan_ctx.installment(sequence_no)["id"], 2625)
        final = settle_installment(api, plan_ctx.installment(4)["id"], 2625)

        assert final["status"] == InstallmentStatus.SETTLED.value, (
            f"the final installment should be SETTLED, got {final['status']!r}"
        )
        assert_instant_equals(final["settled_at"], "2026-08-01T00:00:00Z", "settled_at")
        plan_row = get_plan(api, plan_ctx.id)
        assert plan_row["plan_status"] == PlanStatus.COMPLETED.value, (
            f"the plan should be COMPLETED, got {plan_row['plan_status']!r}"
        )
        assert plan_row["settled_count"] == 4, (
            f"all four installments are settled, got {plan_row['settled_count']!r}"
        )
        assert plan_row["missed_count"] == 0, (
            f"nothing was missed on this plan, got {plan_row['missed_count']!r}"
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id), [InstallmentStatus.SETTLED.value] * 4
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert_pass_dimensions(
            pass_row,
            pass_status=PassStatus.ACTIVE.value,
            billing_status=BillingStatus.PAID_IN_FULL.value,
        )
        assert_ledger(pass_row, billed=13500, paid=13500, credited=0, outstanding=0)

    def test_a_settled_installment_cannot_be_settled_again(self, api, default_clock):
        """Only a scheduled or missed installment on an active plan is payable.

        PRD: "Three preconditions guard the write, and their errors are ordered: an
        installment whose `status` is neither `SCHEDULED` nor `MISSED`, or whose owning
        plan's `plan_status` is not `ACTIVE`, is refused with
        `ERR_INSTALLMENT_NOT_PAYABLE` (HTTP 409); a tendered `amount_cents` that does not
        exactly equal the installment's own `amount_cents` is refused with
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422) — the park takes the scheduled amount or
        nothing, neither part payment nor overpayment; and an installment on a pass whose
        `pass_status` is `REVOKED` is not payable either."

        Design: Corner/state_machines/final_installment_settlement_completes_plan_and_pays_pass_in_full
        """
        _, pass_ctx, plan_ctx = self._plan_of_four(api)
        for sequence_no in (1, 2, 3, 4):
            settle_installment(api, plan_ctx.installment(sequence_no)["id"], 2625)

        response = api.settle_installment(
            plan_ctx.installment(4)["id"], settle_payload(2625), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value, 409)
        assert_ledger(get_pass(api, pass_ctx.id), paid=13500, outstanding=0)


class TestSettlementAmountMustMatchExactly:
    """The park takes the scheduled figure or nothing at all."""

    def _plan_of_four(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        return pass_ctx, plan_ctx

    def test_neither_underpayment_nor_overpayment_is_accepted(self, api, default_clock):
        """2624 and 2626 are both refused against a 2625-cent row.

        PRD: "a tendered `amount_cents` that does not exactly equal the installment's own
        `amount_cents` is refused with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422) — the park
        takes the scheduled amount or nothing, neither part payment nor overpayment"

        Design: Corner/validations/installment_settlement_amount_must_match_exactly
        """
        pass_ctx, plan_ctx = self._plan_of_four(api)
        first = plan_ctx.installment(1)

        under = api.settle_installment(
            first["id"], settle_payload(2624), headers=clerk_headers()
        )
        over = api.settle_installment(first["id"], settle_payload(2626), headers=clerk_headers())

        validate_error(under, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 422)
        validate_error(over, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 422)
        untouched = validate_success(api.get_installment(first["id"], headers=clerk_headers()))
        assert untouched["status"] == InstallmentStatus.SCHEDULED.value, (
            f"a refused tender leaves the row SCHEDULED, got {untouched['status']!r}"
        )
        assert untouched["settled_at"] is None, (
            f"a refused tender records no settlement instant, got {untouched['settled_at']!r}"
        )
        assert_ledger(get_pass(api, pass_ctx.id), paid=3000)

    def test_the_supplied_paid_at_wins_over_the_logical_clock(self, api, default_clock):
        """An exact tender with its own instant settles at that instant.

        PRD: "The settlement payload states the `amount_cents` tendered and may optionally
        state `paid_at`, the instant the money was taken; when `paid_at` is omitted the
        logical clock's current instant is used."

        Design: Corner/validations/installment_settlement_amount_must_match_exactly
        """
        pass_ctx, plan_ctx = self._plan_of_four(api)
        first = plan_ctx.installment(1)

        settled = validate_success(
            api.settle_installment(
                first["id"],
                settle_payload(2625, paid_at="2026-09-01T09:30:00Z"),
                headers=clerk_headers(),
            )
        )

        assert settled["status"] == InstallmentStatus.SETTLED.value, (
            f"an exact tender should settle the row, got {settled['status']!r}"
        )
        assert_instant_equals(settled["settled_at"], "2026-09-01T09:30:00Z", "settled_at")
        pass_row = get_pass(api, pass_ctx.id)
        assert_ledger(pass_row, paid=5625)
        assert_pass_dimensions(pass_row, billing_status=BillingStatus.PLAN_CURRENT.value)
