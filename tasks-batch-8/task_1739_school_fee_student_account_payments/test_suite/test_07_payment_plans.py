"""Payment plans and installments: schedule math, cancel rules, recovery cycle,
plan OCC guard, aging default cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    setup_account_with_assessment, setup_account_with_plan,
    pay_and_settle, set_clock, current_account_version,
    make_bookkeeper_headers,
)

BK = make_bookkeeper_headers()


class TestInstallmentSchedule:
    def test_installment_schedule_remainder_on_last_installment(self):
        """PRD §2.6: "The per-installment base is the covered total divided by the
        installment count, rounded down to a whole cent; the shortfall left by
        that floor division is added in full to the final installment, never the
        first."
        PRD §3.6: "each installment's due_date is first_due_date advanced by
        interval_days once for every preceding installment"

        Design: Corner/calculations/installment_schedule_remainder_on_last_installment
        """
        env = setup_account_with_assessment(assessed_amount_cents=10001)
        account_id = env["account"]["id"]
        a_v = current_account_version(account_id)
        plan = get_success_data(api_client.create_payment_plan(
            account_id, {"installment_count": 3, "first_due_date": "2026-09-05",
                         "interval_days": 30, "expected_account_version": a_v}, BK))
        assert plan["covered_amount_cents"] == 10001
        installments = get_success_data(api_client.list_plan_installments(
            account_id, plan["id"], BK))
        assert len(installments) == 3
        assert installments[0]["amount_cents"] == 3333
        assert installments[1]["amount_cents"] == 3333
        assert installments[2]["amount_cents"] == 3335, (
            f"Remainder 2 pinned to the LAST installment; got {installments[2]['amount_cents']}")
        assert installments[0]["due_date"] == "2026-09-05"
        assert installments[1]["due_date"] == "2026-10-05"
        assert installments[2]["due_date"] == "2026-11-04"
        assert all(i["status"] == "SCHEDULED" for i in installments)

    def test_plan_terms_floor_violation(self):
        """PRD §3.6: "The terms must hold or creation fails with
        `ERR_PLAN_TERMS_VIOLATION` (HTTP 422): the covered total must be at least
        the year's payment_plan_min_cents, the installment_count must lie between
        2 and the year's payment_plan_max_installments inclusive, and there must
        be outstanding to cover at all."

        Design: Corner/validations/plan_terms_floor_violation
        """
        env = setup_account_with_assessment(
            assessed_amount_cents=3000,
            year_overrides={"payment_plan_min_cents": 5000})
        a_v = current_account_version(env["account"]["id"])
        resp = api_client.create_payment_plan(
            env["account"]["id"],
            {"installment_count": 2, "first_due_date": "2026-09-05",
             "interval_days": 30, "expected_account_version": a_v}, BK)
        validate_error(resp, ApiErrorId.ERR_PLAN_TERMS_VIOLATION)

    def test_plan_covers_full_outstanding_and_moves_assessments(self):
        """PRD §3.6: "The covered set is not negotiable: all of the account's
        assessments in `ASSESSED` or `PARTIALLY_PAID` status with
        `outstanding_cents` above zero, ordered by `created_at` ascending — the
        plan covers the account's full outstanding and there is no cherry-picking."
        and "Creation moves every covered assessment `ASSESSED` or
        `PARTIALLY_PAID` → `PAYMENT_PLAN` and sets each one's payment_plan_id."

        Design: Corner/calculations/installment_schedule_remainder_on_last_installment
        """
        env = setup_account_with_assessment(assessed_amount_cents=6000)
        a_v = current_account_version(env["account"]["id"])
        plan = get_success_data(api_client.create_payment_plan(
            env["account"]["id"], {"installment_count": 2,
                                   "first_due_date": "2026-09-05",
                                   "interval_days": 30,
                                   "expected_account_version": a_v}, BK))
        assert plan["status"] == "ACTIVE"
        fa = get_success_data(api_client.get_fee_assessment(
            env["account"]["id"], env["assessment"]["id"], BK))
        assert fa["status"] == "PAYMENT_PLAN"
        assert fa["payment_plan_id"] == plan["id"]


class TestPlanCancel:
    def test_plan_cancel_returns_assessments_and_waives_installments(self):
        """PRD §3.6: "cancellation moves the plan to `CANCELLED`, waives its unpaid
        installments to `WAIVED_BY_DEFAULT`, and returns the covered assessments
        from `PAYMENT_PLAN` to `ASSESSED` so the obligation flows back through
        the normal waterfall."

        Design: Corner/cross_cutting_layers/plan_cancel_returns_assessments_and_waives_installments
        """
        env = setup_account_with_plan(assessed_amount_cents=4000)
        account_id, plan_id = env["account"]["id"], env["plan"]["id"]
        resp = api_client.cancel_payment_plan(account_id, plan_id, BK)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"
        installments = get_success_data(api_client.list_plan_installments(
            account_id, plan_id, BK))
        assert all(i["status"] == "WAIVED_BY_DEFAULT" for i in installments)
        fa = get_success_data(api_client.list_fee_assessments(account_id, BK))[0]
        assert fa["status"] == "ASSESSED"
        assert fa["outstanding_cents"] == 4000, (
            f"Obligation fully restored to the waterfall; got {fa['outstanding_cents']}")

    def test_plan_cancel_with_paid_installment_rejected(self):
        """PRD §3.6: "A `Bookkeeper` may cancel an `ACTIVE` plan only while no
        installment is `PAID` — a plan with any paid installment refuses with
        `ERR_PLAN_HAS_PAYMENTS` (HTTP 409)"

        Design: Corner/validations/plan_cancel_with_paid_installment_rejected
        """
        env = setup_account_with_plan(assessed_amount_cents=4000,
                                      first_due_date="2026-09-05")
        account_id, plan_id = env["account"]["id"], env["plan"]["id"]
        # Early payment is allowed from SCHEDULED: settle exactly one installment
        pay_and_settle(account_id, 2000, idempotency_key="k1")
        resp = api_client.cancel_payment_plan(account_id, plan_id, BK)
        validate_error(resp, ApiErrorId.ERR_PLAN_HAS_PAYMENTS)
        plan = get_success_data(api_client.get_payment_plan(account_id, plan_id, BK))
        assert plan["status"] == "ACTIVE"


class TestInstallmentRecoveryCycle:
    def test_installment_past_due_recovery_cycle(self):
        """PRD §3.6: "The waterfall can pay an installment from `SCHEDULED` (early
        payment is allowed), from `DUE`, or from `PAST_DUE` (the recovery loop);
        a fully covered installment becomes `PAID`"
        PRD §3.8: "First, every `DUE` installment whose logical date has passed
        its due_date becomes `PAST_DUE`."

        Design: Difficulty/non_linear_state_machine/installment_past_due_recovery_cycle
        """
        env = setup_account_with_plan(assessed_amount_cents=4000,
                                      first_due_date="2026-08-05", interval_days=30,
                                      year_overrides={"payment_plan_min_cents": 1000,
                                                      "aging_interval_days": 10})
        account_id, plan_id = env["account"]["id"], env["plan"]["id"]
        # Advance past the first due date and sweep: installment 1 -> PAST_DUE
        set_clock("2026-08-06T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        installments = get_success_data(api_client.list_plan_installments(
            account_id, plan_id, BK))
        assert installments[0]["status"] == "PAST_DUE", (
            f"Installment 1 past its 2026-08-05 due date must be PAST_DUE; "
            f"got {installments[0]['status']}")
        # Recovery: settling 2000 covers installment 1 via Stage 1
        pay_and_settle(account_id, 2000, idempotency_key="k1", method="CASH")
        installments = get_success_data(api_client.list_plan_installments(
            account_id, plan_id, BK))
        assert installments[0]["status"] == "PAID", (
            f"PAST_DUE -> PAID recovery loop must close; got {installments[0]['status']}")
        assert installments[1]["status"] == "SCHEDULED"
        plan = get_success_data(api_client.get_payment_plan(account_id, plan_id, BK))
        assert plan["status"] == "ACTIVE"

    def test_installment_paid_completes_plan(self):
        """PRD §3.6: "A plan completes `ACTIVE` → `COMPLETED` when every
        installment is `PAID`; its covered assessments move `PAYMENT_PLAN` →
        `PAID` with their payment_plan_id cleared, and the account recomputes."

        Design: Difficulty/non_linear_state_machine/installment_past_due_recovery_cycle
        """
        env = setup_account_with_plan(assessed_amount_cents=4000,
                                      first_due_date="2026-08-05", interval_days=30)
        account_id, plan_id = env["account"]["id"], env["plan"]["id"]
        pay_and_settle(account_id, 4000, idempotency_key="k-full")
        plan = get_success_data(api_client.get_payment_plan(account_id, plan_id, BK))
        assert plan["status"] == "COMPLETED"
        installments = get_success_data(api_client.list_plan_installments(
            account_id, plan_id, BK))
        assert all(i["status"] == "PAID" for i in installments)
        fa = get_success_data(api_client.list_fee_assessments(account_id, BK))[0]
        assert fa["status"] == "PAID"
        assert fa.get("payment_plan_id") in (None,), (
            f"payment_plan_id cleared on completion; got {fa.get('payment_plan_id')}")


class TestPlanDefaultCascade:
    def test_ops_run_plan_default_cascade_to_collections(self):
        """PRD §3.8: "Second, any `ACTIVE` plan with an installment `PAST_DUE` for
        more than k days past its due date defaults, cascading per §3.6."
        PRD §3.6: "the plan moves `ACTIVE` → `DEFAULTED`, its unpaid installments
        become `WAIVED_BY_DEFAULT`, every covered assessment becomes
        `DELINQUENT`, a collections case opens for the account (or the existing
        case's bucket advances), and posture recomputes."
        PRD §3.2: "Otherwise, if the account has a case `OPEN` or
        `PAYMENT_PROMISED`, posture is `COLLECTIONS`."

        Design: Difficulty/transitive_cascade/ops_run_plan_default_cascade_to_collections
        """
        env = setup_account_with_plan(assessed_amount_cents=4000,
                                      first_due_date="2026-08-05", interval_days=30,
                                      year_overrides={"payment_plan_min_cents": 1000,
                                                      "aging_interval_days": 10})
        account_id, plan_id = env["account"]["id"], env["plan"]["id"]
        # Installment 1 due 2026-08-05; at 2026-08-20 it is 15 days past due (> k=10)
        set_clock("2026-08-20T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        plan = get_success_data(api_client.get_payment_plan(account_id, plan_id, BK))
        assert plan["status"] == "DEFAULTED", (
            f"15 days past due > k=10 must default the plan; got {plan['status']}")
        installments = get_success_data(api_client.list_plan_installments(
            account_id, plan_id, BK))
        assert all(i["status"] == "WAIVED_BY_DEFAULT" for i in installments)
        fa = get_success_data(api_client.list_fee_assessments(account_id, BK))[0]
        assert fa["status"] == "DELINQUENT"
        cases = get_success_data(api_client.list_collections_cases(account_id, BK))
        assert len(cases) == 1
        assert cases[0]["status"] == "OPEN"
        assert cases[0]["principal_cents"] == 4000, (
            f"principal snapshots the balance owed at open; got {cases[0]['principal_cents']}")
        account = get_success_data(api_client.get_student_account(account_id, BK))
        assert account["posture"] == "COLLECTIONS"

    def test_ops_run_counts_reported(self):
        """PRD §3.8: "The **collections aging** machinery runs as the year-scoped
        operations sweep, which a `Bookkeeper` triggers; the run reports back
        swept_cases, defaulted_plans, advanced_installments, and opened_cases."

        Design: Difficulty/transitive_cascade/ops_run_plan_default_cascade_to_collections
        """
        env = setup_account_with_plan(assessed_amount_cents=4000,
                                      first_due_date="2026-08-05", interval_days=30,
                                      year_overrides={"payment_plan_min_cents": 1000,
                                                      "aging_interval_days": 10})
        set_clock("2026-08-20T00:00:00Z")
        report = get_success_data(api_client.run_ops(env["year"]["id"], BK))
        assert report["defaulted_plans"] == 1
        assert report["opened_cases"] == 1
        assert isinstance(report["swept_cases"], int)
        assert isinstance(report["advanced_installments"], int)
