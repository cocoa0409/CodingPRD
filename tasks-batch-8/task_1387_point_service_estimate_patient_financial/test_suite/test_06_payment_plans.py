"""Payment plan schedule math, activation gating, and the default/reinstate cycle."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_estimate,
    assert_plan_amounts_conserve_principal,
    create_active_plan,
    create_case,
    create_draft_plan,
    create_patient,
    set_clock,
    setup_accepted_insured_estimate,
    setup_defaulted_plan,
    setup_presented_insured_estimate,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNSELOR = TEST_USERS["counselor_headers"]


class TestInstallmentSchedule:
    def test_floor_division_with_remainder_on_last_installment(self, api):
        """PRD §3.8: "`installment_amount_cents` is the principal divided by
        the number of installments, truncated; installments 1 through N−1 each
        carry that amount; and the final installment N carries the remainder —
        the principal minus N−1 times the base amount — so that the schedule
        always sums exactly to `principal_cents`."

        Design: Difficulty/combinatorial_formula/installment_schedule_floor_last_remainder
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-P-1")
        case = create_case(patient["id"])
        plan = create_draft_plan(case["id"], principal_cents=100001,
                                 num_installments=3)
        assert plan["installment_amount_cents"] == 33333, "floor(100001/3)"
        amounts = [inst["amount_cents"] for inst in plan["installments"]]
        assert amounts == [33333, 33333, 33335], (
            "the remainder lands on the LAST installment")
        assert_plan_amounts_conserve_principal(plan)

    def test_amounts_fixed_at_create_and_outstanding_equals_principal(self, api):
        """PRD §3.8: "Rounding each installment half-up instead is a documented
        trap that can push the total above the principal and is not canonical."
        PRD §3.8: "amounts are fixed at creation while due dates are fixed
        later, at activation."

        Design: Difficulty/combinatorial_formula/installment_schedule_floor_last_remainder
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-P-2")
        case = create_case(patient["id"])
        plan = create_draft_plan(case["id"], principal_cents=100001,
                                 num_installments=3)
        assert plan["status"] == "DRAFT"
        assert plan["principal_outstanding_cents"] == 100001
        assert sum(i["amount_cents"] for i in plan["installments"]) == 100001, (
            "never above principal (the round-each-installment trap yields "
            "100002)")
        for inst in plan["installments"]:
            assert inst["paid_cents"] == 0
            assert inst["status"] == "PENDING"


class TestActivateRequiresAcceptedEstimate:
    def _setup(self):
        ctx = setup_presented_insured_estimate(mrn="MRN-X-1")
        plan = create_draft_plan(ctx["case"]["id"], principal_cents=100000,
                                 num_installments=4)
        return ctx, plan

    def test_activate_while_estimate_presented_is_rejected(self, api):
        """PRD §3.8: "Activation moves `DRAFT` → `ACTIVE` and is only possible
        once the case holds an estimate in `ACCEPTED` or `FINALIZED` status —
        otherwise `ERR_NO_ACCEPTED_ESTIMATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/payment_plan_activate_requires_accepted_estimate
        """
        ctx, plan = self._setup()
        assert ctx["estimate"]["status"] == "PRESENTED"
        res = api.activate_payment_plan(plan["id"], COUNSELOR)
        validate_error(res, ApiErrorId.ERR_NO_ACCEPTED_ESTIMATE)
        plans, _m = validate_paginated(
            api.list_case_payment_plans(ctx["case"]["id"], COUNSELOR))
        assert plans[0]["status"] == "DRAFT"

    def test_activate_after_acceptance_fixes_due_dates(self, api):
        """PRD §3.8: "the first `due_date` falls thirty days after the
        activation date, and each subsequent installment falls one calendar
        month after its predecessor, with the day clamped to the end of the
        month when the target month is shorter."

        Design: Difficulty/cross_entity_state_dependency/payment_plan_activate_requires_accepted_estimate
        """
        ctx, plan = self._setup()
        accept_estimate(ctx["estimate"]["id"])
        activated = validate_success(
            api.activate_payment_plan(plan["id"], COUNSELOR), 200)
        assert activated["status"] == "ACTIVE"
        due_dates = [inst["due_date"] for inst in activated["installments"]]
        assert due_dates[0] == "2026-09-02", "activation 2026-08-03 + 30 days"
        assert due_dates == ["2026-09-02", "2026-10-02", "2026-11-02",
                             "2026-12-02"]


class TestDefaultReinstateCycle:
    """ACTIVE -> DEFAULTED -> ACTIVE -> COMPLETED on the same plan."""

    def test_sweep_defaults_plan_past_grace_and_counts_missed(self, api):
        """PRD §3.8: "The sweep moves `ACTIVE` → `DEFAULTED` when any
        installment remains `PENDING` more than fourteen days past its due
        date — that is, when the due date plus fourteen days falls strictly
        before the current logical date — and recomputes the missed count."
        PRD §3.8: "The plan's `missed_payment_count` is the number of
        installments still `PENDING` whose `due_date` is strictly before the
        current logical date."

        Design: Difficulty/non_linear_state_machine/payment_plan_default_reinstate_cycle
        """
        ctx = setup_defaulted_plan(mrn="MRN-CY-1")
        assert ctx["sweep"]["defaulted_plans"] == 1, (
            "due1 2026-09-02 + 14-day grace = 2026-09-16, strictly before "
            "2026-09-17")
        assert ctx["plan"]["status"] == "DEFAULTED"
        assert ctx["plan"]["missed_payment_count"] == 1

    def test_reinstate_then_payoff_completes_cycle(self, api):
        """PRD §3.8: "a sufficient one is applied through the same payment
        waterfall, the missed count is recomputed, and the plan returns
        `DEFAULTED` → `ACTIVE`."
        PRD §3.8: "when it reaches zero the plan completes itself, moving
        `ACTIVE` → `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/payment_plan_default_reinstate_cycle
        """
        ctx = setup_defaulted_plan(mrn="MRN-CY-2")
        plan_id = ctx["plan"]["id"]
        reinstated = validate_success(api.reinstate_payment_plan(
            plan_id, {"cure_amount_cents": 33333}, COUNSELOR), 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["principal_outstanding_cents"] == 66668
        assert reinstated["missed_payment_count"] == 0
        completed = validate_success(api.record_plan_payment(
            plan_id, {"amount_cents": 66668}, COUNSELOR), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["principal_outstanding_cents"] == 0


class TestReinstateCureThreshold:
    def test_reinstate_with_insufficient_cure_returns_409(self, api):
        """PRD §3.8: "a counselor reinstates the plan with a
        `cure_amount_cents` that must at least cover the sum of the unpaid
        balances — `amount_cents` minus `paid_cents` — over all installments
        whose due date is strictly past. A short cure is rejected with
        `ERR_CURE_INSUFFICIENT` (HTTP 409); a sufficient one is applied through
        the same payment waterfall, the missed count is recomputed, and the
        plan returns `DEFAULTED` → `ACTIVE`."

        Design: Corner/validations/reinstate_with_insufficient_cure_returns_409
        """
        ctx = setup_defaulted_plan(mrn="MRN-V-10")
        plan_id = ctx["plan"]["id"]
        res = api.reinstate_payment_plan(plan_id, {"cure_amount_cents": 33332},
                                         COUNSELOR)
        validate_error(res, ApiErrorId.ERR_CURE_INSUFFICIENT)
        plans, _m = validate_paginated(
            api.list_case_payment_plans(ctx["case"]["id"], COUNSELOR))
        assert plans[0]["status"] == "DEFAULTED", "short cure leaves the plan defaulted"
        reinstated = validate_success(api.reinstate_payment_plan(
            plan_id, {"cure_amount_cents": 33333}, COUNSELOR), 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["principal_outstanding_cents"] == 66668


class TestPaymentExceedsOutstanding:
    def test_payment_above_outstanding_returns_422(self, api):
        """PRD §3.8: "A payment supplies `amount_cents`; an amount exceeding
        the plan's `principal_outstanding_cents` is rejected outright with
        `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (HTTP 422)."

        Design: Corner/validations/payment_above_outstanding_returns_422
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-V-11")
        plan = create_active_plan(ctx["case"]["id"], principal_cents=100001,
                                  num_installments=3)
        res = api.record_plan_payment(plan["id"], {"amount_cents": 100002},
                                      COUNSELOR)
        validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)
        plans, _m = validate_paginated(
            api.list_case_payment_plans(ctx["case"]["id"], COUNSELOR))
        assert plans[0]["principal_outstanding_cents"] == 100001, (
            "no partial application")
