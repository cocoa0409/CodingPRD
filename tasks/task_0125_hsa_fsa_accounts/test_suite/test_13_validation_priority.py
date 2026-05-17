"""Validation priority — PRD §2.10.

PRD §2.10 fixes a deterministic precedence order so error responses
are predictable when multiple rules apply. Only orderings that PRD
prose explicitly pins are tested here. Tests where PRD does not
commit to a precedence use validate_error_is_one_of so that either
faithful interpretation passes.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock_to,
    create_account_holder,
    create_contribution_payload,
    iso_datetime_utc,
    make_adjudicator_headers,
    setup_funded_plan_year,
    setup_holder_and_account,
    seed_qualified_expense,
    validate_error,
)


# ===========================================================================
# Auth precedes everything — PRD §2.10
# ===========================================================================
class TestAuthBeforeState:

    def test_missing_auth_beats_frozen_account(self, api):
        """PRD §2.10: "first, auth headers must be present
        (ERR_MISSING_AUTH); next, the role must be permitted for the
        endpoint (ERR_FORBIDDEN); next, every path-segment identifier
        must resolve left-to-right to an existing in-scope row
        (ERR_NOT_FOUND); next, account-state preconditions are
        evaluated — operations that require an open account check
        Account.status and reject with ERR_ACCOUNT_NOT_OPEN".
        PRD §2.10: "This ordering ensures that, for example, a request
        from an unauthenticated principal against a frozen account
        always surfaces the missing-auth error rather than the
        account-not-open error."

        Claim: missing auth headers on POST /plan-years/{id}/contributions
        against a frozen account -> ERR_MISSING_AUTH, NOT
        ERR_ACCOUNT_NOT_OPEN.
        """
        from test_helpers import freeze_account, setup_active_plan_year
        _, acct, py = setup_active_plan_year()
        freeze_account(acct["id"])
        resp = api._request(
            "POST", f"/plan-years/{py['id']}/contributions",
            create_contribution_payload(amount_cents=10_000),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# ===========================================================================
# Role precedes existence — PRD §2.10
# ===========================================================================
class TestForbiddenBeforeNotFound:

    def test_role_check_beats_not_found(self, api, auditor_headers):
        """PRD §2.10: "next, the role must be permitted for the
        endpoint (ERR_FORBIDDEN); next, every path-segment identifier
        must resolve left-to-right to an existing in-scope row
        (ERR_NOT_FOUND)".

        Claim: Auditor (forbidden) calls POST /accounts/{nonexistent}/freeze
        -> ERR_FORBIDDEN, not ERR_NOT_FOUND.
        """
        resp = api.freeze_account(NON_EXISTENT_UUID, auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# SoD precedes business_referential — PRD §2.10
# ===========================================================================
class TestSegregationBeforeDependentInactive:
    """PRD §2.10 pins SoD (priority 7) before dependent-active
    (priority 9.5). On /approve, both can fire if the dependent is
    deactivated AFTER submit (PRD §3.1: 'deactivation does not
    retroactively affect claims already in flight that cite the
    dependent'). The precondition list for /approve in PRD §3.5
    explicitly names SoD; PRD §2.10 names dep-inactive in the same
    business-referential block. Because §2.10 fixes the order, the
    expected error_id when both conditions hold is
    ERR_SEGREGATION_OF_DUTIES.

    Note: PRD §3.5's /approve precondition list names SoD but not
    dep-inactive — an implementation may legitimately not re-check
    dependent status at /approve. The test claim therefore only
    asserts the precedence outcome for cases where both checks
    run: SoD wins. If an implementation faithfully omits the
    dep-inactive recheck at /approve, the SoD assertion still
    succeeds because SoD is mandatory at /approve.
    """

    def test_sod_priority_over_dependent_inactive_on_approve(self, api):
        """PRD §2.9: "the actor_user_id recorded on the
        CLAIM_SUBMITTED event for a given claim is compared to the
        current X-User-ID whenever that claim is approved or denied;
        if they match, the operation is rejected with
        ERR_SEGREGATION_OF_DUTIES."
        PRD §3.1: "deactivation does not retroactively affect claims
        already in flight that cite the dependent, but blocks new
        claim submissions from citing the inactive dependent."

        Claim: build a SUBMITTED DCFSA claim citing a dependent, then
        deactivate the dependent, then /approve with X-User-ID equal
        to the submitter -> ERR_SEGREGATION_OF_DUTIES (priority 7
        wins over priority 9.5).
        """
        from test_helpers import (
            approve_claim,
            create_claim,
            create_dependent,
            deactivate_dependent,
            submit_claim,
            validate_error_is_one_of,
        )

        # Build a DCFSA + active dependent + submit a claim.
        holder, acct, py = setup_funded_plan_year(
            account_type="DEPENDENT_CARE_FSA",
            coverage_tier=None, year_end_policy="NONE",
            calendar_year=2025, contribution_cents=100_000,
        )
        dep = create_dependent(account_holder=holder)
        qe = seed_qualified_expense(
            category="DEPENDENT_CARE",
            eligible_account_types=["DEPENDENT_CARE_FSA"],
            requires_dependent=True,
        )
        claim = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2025, 6, 15),
            expense_code=qe["code"], amount_cents=10_000,
            dependent_id=dep["id"],
        )
        submit_claim(claim["id"], account_holder=holder)
        # Now deactivate the dependent post-submit.
        deactivate_dependent(dep["id"])
        # /approve with X-User-ID equal to the submitter's holder id.
        same_id_headers = make_adjudicator_headers(holder["id"])
        resp = api.approve_claim(claim["id"], same_id_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# State precedence over fiscal — PRD §2.10
# ===========================================================================
class TestPlanYearStateBeforeBalance:
    """Mirrors difficulty instance
    state_vs_business_fiscal_pay_on_closed_with_insufficient.

    PRD §2.10: "Resolved PlanYear must be in a claimable status
    (ACTIVE, GRACE_PERIOD, or CARRYOVER_PENDING) for /submit,
    /approve, /pay; CLOSED PlanYears reject" with priority 6 (state),
    versus "Claim.amount_cents <= available_balance (calc
    available_balance) at the moment of /pay" with priority 13
    (business_fiscal).
    """

    def test_plan_year_closed_beats_insufficient_balance_on_pay(self, api):
        """PRD §2.10: "the resolved PlanYear must be in a claimable
        status ... (ERR_PLAN_YEAR_NOT_CLAIMABLE); next ... fiscal
        balance checks (ERR_INSUFFICIENT_BALANCE, then
        ERR_REVERSAL_WOULD_OVERDRAW)".

        Claim: a /pay request where the resolved PlanYear is CLOSED
        AND the claim amount exceeds available balance returns
        ERR_PLAN_YEAR_NOT_CLAIMABLE (priority 6, state) — not
        ERR_INSUFFICIENT_BALANCE (priority 13, business_fiscal).
        """
        from test_helpers import (
            approve_claim,
            create_claim,
            create_dependent as _cd,  # unused
            iso_datetime_utc as _iso,
            post_ops_run,
            submit_claim,
        )

        # HEALTH_FSA NONE so YEAR_END_CLOSE moves directly to CLOSED.
        # Anchor late in 2025 so the 6/15 service_date below is past.
        advance_clock_to(iso_datetime_utc(2025, 12, 1))
        _, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="NONE", birth_date="1980-01-01",
        )
        from test_helpers import open_plan_year, post_contribution
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=10_000, source="PAYROLL")
        qe = seed_qualified_expense(
            category="MEDICAL",
            eligible_account_types=["HEALTH_FSA"],
            requires_dependent=False,
        )
        holder = create_account_holder()
        # We need a claim with amount > available balance against a
        # CLOSED plan year. The cleanest construction is to make the
        # claim under the account whose plan year is being closed.
        # We already created acct; we just need a holder reference
        # to acct's owner. Re-derive.
        from test_helpers import api_client as _ac
        # Build a $500 (50_000 cents) claim against acct so amount
        # exceeds available balance ($100).
        # The account's holder is the one we minted in setup_holder...
        # The fixture returned (_, acct) — let's recreate so we have
        # the holder.
        # Replace with a fresh full-setup that exposes the holder.
        holder2, acct2 = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="NONE", birth_date="1980-01-01",
        )
        py2 = open_plan_year(acct2["id"], calendar_year=2025)
        post_contribution(py2["id"], amount_cents=10_000, source="PAYROLL")
        c = create_claim(
            account_holder=holder2, account=acct2,
            service_date=_iso(2025, 6, 15),
            expense_code=qe["code"], amount_cents=50_000,
        )
        submit_claim(c["id"], account_holder=holder2)
        approve_claim(c["id"])
        # YEAR_END_CLOSE -> py2 (HEALTH_FSA NONE) goes to CLOSED.
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        # Pay attempt: state (CLOSED) and fiscal (insufficient) both
        # fail. PRD §2.10 pins state first.
        from test_helpers import make_adjudicator_headers as _mah
        resp = api.pay_claim(
            c["id"], _mah("priority-test-pay-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_YEAR_NOT_CLAIMABLE.value)
