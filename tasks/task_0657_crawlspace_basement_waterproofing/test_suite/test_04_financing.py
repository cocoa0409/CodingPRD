"""Financing: 2-D APR tier + amortization, the per-band finance ceiling, the
state-vs-fiscal precedence on decide, declined->withdrawn reset, and the FinancePartner
exclusivity of decide.

Covers Difficulty queue: combinatorial_formula (2-D tier amortization),
priority_pair_validation_conflict (state before finance-limit on decide).
Covers Corner queue: subprime APR tier, finance-limit-exceeded, declined->withdrawn,
homeowner-cannot-decide RBAC.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_financing_application_payload,
    setup_sold_job, setup_submitted_financing,
    TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
FIN = TEST_USERS["finance_partner_headers"]


class TestFinancingAmortization:
    def test_prime_term36_apr_and_monthly_payment(self, api):
        """PRD §3.6: "For a `PRIME` band the APR is 599 basis points short and 799 long".
        PRD §3.6: "the term bucket is "short" when `term_months` is 24 or fewer and "long"
        when `term_months` is greater than 24."
        PRD §3.6: "the payment is the principal times the monthly rate times the quantity
        one-plus-the-monthly-rate raised to the number of months, divided by the quantity
        one-plus-the-monthly-rate raised to the number of months minus one. The result is
        rounded half up to whole cents."
        PRD §3.6: "At submission the financed amount is locked: `amount_financed_cents` is
        pinned to the accepted quote's `total_cents`."

        Design: Difficulty/combinatorial_formula/financing_amortization_2d_tier_nonlinear
        """
        # 600 sqft sump-only no discount: base 250000 + sump 120000 = 370000;
        # tax round(370000*0.07)=25900; total 395900. PRIME term36 -> long -> 799 bps.
        # monthly_payment over 36 months = 12404 cents.
        ctx = setup_sold_job(credit_band="PRIME", footprint_sqft=600,
                            quote_overrides={"includes_sump": True})
        res = api.create_financing_application(
            create_financing_application_payload(ctx["job"]["id"], ctx["quote"]["id"], 36),
            ctx["ho_headers"])
        app = validate_success(res, 201)
        assert app["amount_financed_cents"] == 395900
        assert app["apr_bps"] == 799
        assert app["monthly_payment_cents"] == 12404

    def test_subprime_term12_apr_tier_selection(self, api):
        """PRD §3.6: "for `SUBPRIME` it is 1999 short and 2399 long."
        PRD §3.6: "the term bucket is "short" when `term_months` is 24 or fewer".
        PRD §3.6: "the payment is the principal times the monthly rate times the quantity
        one-plus-the-monthly-rate raised to the number of months, divided by the quantity
        one-plus-the-monthly-rate raised to the number of months minus one. The result is
        rounded half up to whole cents."

        Design: Corner/calculations/financing_subprime_apr_tier_selection
        """
        # 600 sqft sump-only -> total 395900 (< 1.5M subprime ceiling). SUBPRIME term12 ->
        # short -> 1999 bps. monthly over 12 months = 36672 cents.
        ctx = setup_sold_job(credit_band="SUBPRIME", footprint_sqft=600,
                            quote_overrides={"includes_sump": True})
        res = api.create_financing_application(
            create_financing_application_payload(ctx["job"]["id"], ctx["quote"]["id"], 12),
            ctx["ho_headers"])
        app = validate_success(res, 201)
        assert app["apr_bps"] == 1999
        assert app["monthly_payment_cents"] == 36672


class TestFinanceLimit:
    def test_subprime_approve_over_ceiling_rejected(self, api):
        """PRD §3.6: "Approval additionally enforces a per-band ceiling: the
        `amount_financed_cents` must not exceed the maximum the credit band allows —
        5,000,000 cents for `PRIME`, 3,000,000 cents for `NEAR_PRIME`, and 1,500,000
        cents for `SUBPRIME`. An approval whose financed amount exceeds the band's ceiling
        is rejected with `ERR_FINANCE_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/finance_limit_exceeded_subprime_approve
        """
        # full scope 2000 sqft -> total 1813650 (> 1.5M subprime ceiling), clean SUBMITTED.
        ctx = setup_submitted_financing(
            credit_band="SUBPRIME", footprint_sqft=2000, term_months=60,
            quote_overrides={"includes_vapor_barrier": True, "includes_sump": True,
                             "includes_dehumidifier": True, "includes_drain": True,
                             "includes_battery_backup": True, "drain_linear_ft": 100,
                             "discount_code": "NONE"})
        assert ctx["app"]["amount_financed_cents"] == 1813650
        res = api.decide_financing(ctx["app"]["id"], {"decision": "APPROVE"}, FIN)
        validate_error(res, "ERR_FINANCE_LIMIT_EXCEEDED", expected_status=422)


class TestDecidePrecedence:
    def test_state_check_precedes_finance_limit_on_redecide(self, api):
        """PRD §2.7: "Only after all of those does the system evaluate whether the target
        resource is in a legal state for the requested transition, yielding
        `ERR_INVALID_STATE` (HTTP 409); the optimistic-concurrency version check ...; and
        finally the domain-specific business rules described throughout §2 and §3."
        PRD §3.6: "Approving requires the application to be `SUBMITTED` and the Job's
        `financing_status` to be `APPLIED`".

        Design: Difficulty/priority_pair_validation_conflict/state_before_finance_limit_on_decide
        """
        # SUBPRIME full-scope 2000 sqft -> total 1813650 (> ceiling). DECLINE first so a
        # re-decide is an invalid-state transition; the finance-limit business rule would
        # also fail, but state legality (P6) outranks the business ceiling (P13).
        ctx = setup_submitted_financing(
            credit_band="SUBPRIME", footprint_sqft=2000, term_months=12,
            quote_overrides={"includes_vapor_barrier": True, "includes_sump": True,
                             "includes_dehumidifier": True, "includes_drain": True,
                             "includes_battery_backup": True, "drain_linear_ft": 100,
                             "discount_code": "NONE"})
        validate_success(api.decide_financing(ctx["app"]["id"], {"decision": "DECLINE"}, FIN), 200)

        res = api.decide_financing(ctx["app"]["id"], {"decision": "APPROVE"}, FIN)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        app_after = validate_success(api.get_financing_application(ctx["app"]["id"], FIN), 200)
        assert app_after["status"] == "DECLINED"


class TestWithdrawReset:
    def test_declined_to_withdrawn_resets_job_financing(self, api):
        """PRD §3.6: "A homeowner whose application was declined may withdraw it:
        withdrawing requires the application to be `DECLINED` and the Job's
        `financing_status` to be `DECLINED`, moves the application from `DECLINED` to
        `WITHDRAWN`, and resets the Job's `financing_status` from `DECLINED` back to
        `NONE`".

        Design: Corner/state_machines/financing_declined_to_withdrawn_resets_job_financing
        """
        ctx = setup_submitted_financing(credit_band="PRIME", footprint_sqft=600,
                                       term_months=24,
                                       quote_overrides={"includes_sump": True})
        validate_success(api.decide_financing(ctx["app"]["id"], {"decision": "DECLINE"}, FIN), 200)

        withdrawn = validate_success(
            api.withdraw_financing(ctx["app"]["id"], ctx["ho_headers"]), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        job_after = validate_success(api.get_job(ctx["job"]["id"], EST), 200)
        assert job_after["financing_status"] == "NONE"


class TestFinancingRbac:
    def test_homeowner_cannot_decide_financing(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not permitted
        to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §3.6: "The `FinancePartner` then decides the application, supplying a
        `decision` of approve or decline."

        Design: Corner/rbac/homeowner_cannot_decide_financing
        """
        ctx = setup_submitted_financing(credit_band="PRIME", footprint_sqft=600,
                                       term_months=24,
                                       quote_overrides={"includes_sump": True})
        res = api.decide_financing(ctx["app"]["id"], {"decision": "APPROVE"}, ctx["ho_headers"])
        validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
