"""Payment plans: default sweep boundary, cure cycle, completion, and the
balance-plus-recoveries conservation invariant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    assert_payment_plan,
    create_account,
    create_plan,
    make_counselor_headers,
    post_recovery,
    read_account,
    validate_error,
    validate_success,
)

COLLECTOR = TEST_USERS["collector_headers"]


def _plan(api, plan_id):
    return validate_success(api.get_payment_plan(plan_id, COLLECTOR), 200)


class TestDefaultSweepBoundary:
    def test_two_missed_installments_default_one_missed_stays_active(self, api):
        """PRD §3.7: "When the missed count reaches two or more missed
        installments while the plan is still `ACTIVE`, the plan transitions to
        `IN_DEFAULT` and `default_flagged_at` is stamped from the logical
        clock"
        PRD §3.7: "The missed count is the number due minus
        `installments_paid_count`, floored at zero"

        Plan A (first due 2026-01-01, 30-day cadence) has two installments due
        by 2026-02-15; plan B (first due 2026-02-01) has one.

        Design: Difficulty/boundary_precision_check/payment_plan_default_threshold_at_exactly_two_missed
        """
        acct_a = create_account(
            balance_cents=200000, guarantor_liability_date="2025-12-01",
            patient_mrn="MRN-G3", patient_name="G3")
        plan_a = create_plan(
            acct_a["id"], installment_amount_cents=50000, installment_count=4,
            first_installment_due="2026-01-01")
        acct_b = create_account(
            balance_cents=200000, guarantor_liability_date="2025-12-01",
            patient_mrn="MRN-G4", patient_name="G4")
        plan_b = create_plan(
            acct_b["id"], installment_amount_cents=50000, installment_count=4,
            first_installment_due="2026-02-01")

        advance_clock("2026-02-15T00:00:00Z")

        plan_a_after = _plan(api, plan_a["id"])
        assert plan_a_after["status"] == "IN_DEFAULT"
        assert plan_a_after["missed_installment_count"] == 2
        assert plan_a_after["default_flagged_at"] is not None

        plan_b_after = _plan(api, plan_b["id"])
        assert plan_b_after["status"] == "ACTIVE"
        assert plan_b_after["missed_installment_count"] == 1

    def test_installment_due_today_counts_toward_default(self, api):
        """PRD §3.7: "the count of installment due dates falling on or between
        `first_installment_due` and the new logical date, with an installment
        due exactly on the logical date counting as due."
        PRD §3.7: "`default_flagged_at` is stamped from the logical clock"

        Installments due 2026-02-01 and 2026-03-03; advancing the clock to
        exactly 2026-03-03 makes both due.

        The default_flagged_at stamp equals the logical clock instant; the PRD
        pins the instant (§3.7) but not the serialization's fractional-second
        precision, so the comparison normalizes a whole-second rendering.

        Design: Difficulty/boundary_precision_check/payment_plan_default_threshold_at_exactly_two_missed
        """
        account = create_account(
            balance_cents=200000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-DT", patient_name="Due Today")
        plan = create_plan(
            account["id"], installment_amount_cents=50000, installment_count=2,
            first_installment_due="2026-02-01")

        advance_clock("2026-03-03T00:00:00Z")

        plan_after = _plan(api, plan["id"])
        assert plan_after["status"] == "IN_DEFAULT"
        assert plan_after["missed_installment_count"] == 2
        assert plan_after["default_flagged_at"].replace(
            ".000Z", "Z") == "2026-03-03T00:00:00Z"


class TestDefaultCureCycle:
    def test_plan_defaults_then_cure_returns_to_active(self, api):
        """PRD §3.7: "A defaulted plan can be cured by a `Collector`, but only
        after a qualifying catch-up payment has posted: an installment recovery
        attributed to this plan, posted after `default_flagged_at`, whose amount
        is at least the missed installment count multiplied by the
        `installment_amount_cents`."
        PRD §3.7: "A successful cure resets `missed_installment_count` to zero,
        clears `default_flagged_at`, and returns the plan to `ACTIVE`; although
        the transition is labelled `CURED` in audit prose, the persisted
        post-cure state is `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/payment_plan_active_default_cured_cycle
        """
        account = create_account(
            balance_cents=300000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-D1", patient_name="Dan D")
        plan = create_plan(
            account["id"], installment_amount_cents=50000, installment_count=6,
            first_installment_due="2026-02-01")
        # 2026-05-01: installments due 02-01, 03-03, 04-02 -> missed = 3.
        advance_clock("2026-05-01T00:00:00Z")
        defaulted = _plan(api, plan["id"])
        assert defaulted["status"] == "IN_DEFAULT"
        assert defaulted["missed_installment_count"] == 3
        flagged_at = defaulted["default_flagged_at"]

        # Advance one more day so the catch-up posts strictly after
        # default_flagged_at; the sweep only walks ACTIVE plans, so the missed
        # count stays at 3 and 150000 = 3 * 50000 qualifies.
        advance_clock("2026-05-02T00:00:00Z")
        post_recovery(
            account["id"], payment_kind="INSTALLMENT", amount_cents=150000,
            payment_plan_id=plan["id"])
        resp = api.cure_payment_plan(plan["id"], COLLECTOR)
        cured = validate_success(resp, 200)
        assert_payment_plan(cured)
        assert cured["status"] == "ACTIVE"
        assert cured["missed_installment_count"] == 0
        assert cured["default_flagged_at"] is None
        assert cured["installments_paid_count"] == 1
        assert flagged_at is not None

    def test_plan_redefaults_after_cure_completing_cycle(self, api):
        """PRD §3.7: "When the missed count reaches two or more missed
        installments while the plan is still `ACTIVE`, the plan transitions to
        `IN_DEFAULT` and `default_flagged_at` is stamped from the logical clock"

        The ACTIVE -> IN_DEFAULT -> ACTIVE cycle is repeatable: after the cure,
        a later clock advance with all six due installments and one paid flags
        the plan a second time.

        Design: Difficulty/non_linear_state_machine/payment_plan_active_default_cured_cycle
        """
        account = create_account(
            balance_cents=300000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-D1R", patient_name="Dan Redefault")
        plan = create_plan(
            account["id"], installment_amount_cents=50000, installment_count=6,
            first_installment_due="2026-02-01")
        advance_clock("2026-05-01T00:00:00Z")
        advance_clock("2026-05-02T00:00:00Z")
        post_recovery(
            account["id"], payment_kind="INSTALLMENT", amount_cents=150000,
            payment_plan_id=plan["id"])
        validate_success(api.cure_payment_plan(plan["id"], COLLECTOR), 200)
        assert _plan(api, plan["id"])["status"] == "ACTIVE"

        # Due dates 02-01, 03-03, 04-02, 05-02, 06-01, 07-01 are all <=
        # 2026-07-01 (an installment due exactly on the logical date counts as
        # due): due = 6, paid = 1 -> missed = 5 >= 2 -> IN_DEFAULT again.
        advance_clock("2026-07-01T00:00:00Z")
        redefaulted = _plan(api, plan["id"])
        assert redefaulted["status"] == "IN_DEFAULT"
        assert redefaulted["missed_installment_count"] == 5
        assert redefaulted["default_flagged_at"].replace(
            ".000Z", "Z") == "2026-07-01T00:00:00Z"


class TestPlanCompletionAndInvariant:
    def test_installments_to_completion_conserve_balance_sum(self, api):
        """PRD §3.7: "A plan also completes automatically: when
        `installments_paid_count` reaches the `installment_count`, the plan
        moves to `COMPLETED`."
        PRD §3.8: "A posted transaction reduces the account's
        `current_balance_cents` by the gross `amount_cents`"
        PRD §3.8: "adds the gross amount to the account's
        `recovery_total_cents`"

        current_balance_cents + recovery_total_cents is invariant across the
        plan lifecycle: 20000 + 80000 == original 100000.

        Design: Difficulty/compensating_invariant/payment_plan_installment_then_plan_completion_conserves_balance_sum
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-J2", patient_name="J2")
        plan = create_plan(
            account["id"], installment_amount_cents=40000, installment_count=2,
            first_installment_due="2026-01-15")

        post_recovery(account["id"], payment_kind="INSTALLMENT",
                      amount_cents=40000, payment_plan_id=plan["id"])
        post_recovery(account["id"], payment_kind="INSTALLMENT",
                      amount_cents=40000, payment_plan_id=plan["id"])

        plan_after = _plan(api, plan["id"])
        assert plan_after["status"] == "COMPLETED"
        assert plan_after["installments_paid_count"] == 2

        acct_after = read_account(account["id"])
        assert acct_after["current_balance_cents"] == 20000
        assert acct_after["recovery_total_cents"] == 80000
        assert (acct_after["current_balance_cents"]
                + acct_after["recovery_total_cents"]) == 100000

    def test_single_installment_mid_plan_invariant_holds(self, api):
        """PRD §3.8: "An installment payment additionally increments the plan's
        `installments_paid_count`, completing the plan when the count reaches
        `installment_count` as described in §3.7."
        PRD §3.8: "A posted transaction reduces the account's
        `current_balance_cents` by the gross `amount_cents`"

        Mid-plan, before completion: one paid installment leaves the plan ACTIVE
        and conserves current_balance_cents + recovery_total_cents.

        Design: Difficulty/compensating_invariant/payment_plan_installment_then_plan_completion_conserves_balance_sum
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-J2B", patient_name="J2 Mid")
        plan = create_plan(
            account["id"], installment_amount_cents=40000, installment_count=2,
            first_installment_due="2026-01-15")

        post_recovery(account["id"], payment_kind="INSTALLMENT",
                      amount_cents=40000, payment_plan_id=plan["id"])

        plan_after = _plan(api, plan["id"])
        assert plan_after["status"] == "ACTIVE"
        assert plan_after["installments_paid_count"] == 1

        acct_after = read_account(account["id"])
        assert acct_after["current_balance_cents"] == 60000
        assert acct_after["recovery_total_cents"] == 40000
        assert (acct_after["current_balance_cents"]
                + acct_after["recovery_total_cents"]) == 100000


class TestCureGuardAndClockReport:
    def test_cure_active_plan_rejected(self, api):
        """PRD §3.7: "attempting to cure a plan that is not `IN_DEFAULT` is
        rejected with `ERR_PLAN_NOT_IN_DEFAULT` (a 409 conflict in the same
        family as `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/payment_plan_cure_from_active_returns_invalid_state
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-L3", patient_name="L3")
        plan = create_plan(
            account["id"], installment_amount_cents=50000, installment_count=2,
            first_installment_due="2026-02-01")
        assert _plan(api, plan["id"])["status"] == "ACTIVE"

        resp = api.cure_payment_plan(plan["id"], COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_IN_DEFAULT)

    def test_clock_advance_reports_sweep_counts(self, api):
        """PRD §2.4: "the response reports the new time as `now_iso8601`
        together with how many plans were flagged into default
        (`plans_flagged_in_default`) and how many disputes expired
        (`disputes_expired`)."

        Design: Corner/endpoints/clock_endpoint_reports_sweep_results
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-P3", patient_name="P3")
        plan = create_plan(
            account["id"], installment_amount_cents=50000, installment_count=2,
            first_installment_due="2026-02-01")

        # Due 2026-02-01 and 2026-03-03 by 2026-04-15 -> missed = 2 -> default.
        result = advance_clock("2026-04-15T00:00:00Z")
        assert result["now_iso8601"] == "2026-04-15T00:00:00Z"
        assert result["plans_flagged_in_default"] == 1
        assert result["disputes_expired"] == 0
        assert _plan(api, plan["id"])["status"] == "IN_DEFAULT"

    def test_financial_counselor_cannot_terminate_plan(self, api):
        """PRD §2.1: "A `FinancialCounselor` creates and evaluates presumptive
        charity screenings, and shares dispute-filing and payment-plan setup
        with the `Collector`."
        PRD §2.9: "The role must appear in the endpoint's authorized role list,
        else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Termination of a defaulted plan is an officer-only operation.

        Design: Corner/rbac/financial_counselor_cannot_terminate_plan
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-R2", patient_name="R2")
        plan = create_plan(
            account["id"], installment_amount_cents=50000, installment_count=2,
            first_installment_due="2026-01-01")
        advance_clock("2026-04-15T00:00:00Z")
        assert _plan(api, plan["id"])["status"] == "IN_DEFAULT"

        resp = api.terminate_payment_plan(plan["id"], make_counselor_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
