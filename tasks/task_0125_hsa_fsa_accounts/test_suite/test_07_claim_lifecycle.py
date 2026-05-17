"""Claim lifecycle — PRD §3.5.

Coverage targets:
- create -> submit -> approve -> pay happy path produces correct
  state transitions and updated paid_amount_cents.
- submit pins plan_year_id correctly using calc plan_year_resolution.
- approve/deny on SUBMITTED enforce SoD; deny on APPROVED does NOT.
- pay enforces balance precondition; reverse PAID claim restores
  counters and creates twin row.
- denial requires denial_reason; future-dated service rejected.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_claim,
    available_balance,
    create_claim_payload,
    deny_claim_payload,
    get_claim,
    get_plan_year,
    iso_datetime_utc,
    make_account_holder_headers,
    make_adjudicator_headers,
    pay_claim,
    seed_qualified_expense,
    setup_approved_claim,
    setup_funded_plan_year,
    setup_paid_claim,
    setup_submitted_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create / Submit — PRD §3.5
# ===========================================================================
class TestClaimCreateSubmit:

    def test_create_claim_starts_in_draft(self, api):
        """PRD §3.5: "The new claim starts in DRAFT status; no balance
        impact and no audit event are produced at creation."

        Claim: a freshly created claim has status DRAFT and
        plan_year_id null (pinned only at submit time).
        """
        holder, acct, _ = setup_funded_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE", calendar_year=2025,
            contribution_cents=100_000,
        )
        qe = seed_qualified_expense(
            category="MEDICAL",
            eligible_account_types=["HSA"],
            requires_dependent=False,
        )
        payload = create_claim_payload(
            service_date=iso_datetime_utc(2025, 6, 15),
            expense_code=qe["code"], amount_cents=10_000,
        )
        resp = api.create_claim(
            acct["id"], payload,
            make_account_holder_headers(holder["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_claim(data)
        assert data["status"] == "DRAFT"
        assert data["plan_year_id"] is None

    def test_submit_pins_plan_year_id(self, api):
        """PRD §3.5: "Submitting a DRAFT claim transitions it to
        SUBMITTED and is the moment at which plan_year_id is pinned."

        Claim: after /submit, plan_year_id == resolved plan year id
        and status == SUBMITTED.
        """
        holder, acct, py, _, claim = setup_submitted_claim()
        fetched = get_claim(claim["id"])
        assert fetched["status"] == "SUBMITTED"
        assert fetched["plan_year_id"] == py["id"]

    def test_future_service_date_rejected(self, api):
        """PRD §3.5: "The service_date itself must be on or before the
        current clock value — a future-dated service is rejected with
        the same ERR_NO_ELIGIBLE_PLAN_YEAR."

        Claim: a claim with service_date in the future has its submit
        rejected with ERR_NO_ELIGIBLE_PLAN_YEAR.
        """
        # Anchor clock at mid-2025; service_date = 2030 is in the future.
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder, acct, py = setup_funded_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE", calendar_year=2025,
            contribution_cents=10_000,
            clock_anchor=iso_datetime_utc(2025, 6, 1),
        )
        qe = seed_qualified_expense(
            category="MEDICAL", eligible_account_types=["HSA"],
        )
        # The submit-time check raises; submitter is the holder.
        future_date = iso_datetime_utc(2030, 6, 15)
        payload = create_claim_payload(
            service_date=future_date,
            expense_code=qe["code"], amount_cents=1_000,
        )
        resp_create = api.create_claim(
            acct["id"], payload,
            make_account_holder_headers(holder["id"]),
        )
        # PRD §3.5: create-time check also raises ERR_NO_ELIGIBLE_PLAN_YEAR
        # ("The same expense-eligibility ... checks also run at claim
        # creation time" doesn't cover service_date, but PRD §3.5
        # explicitly groups future-dated services under
        # ERR_NO_ELIGIBLE_PLAN_YEAR at submit). Accept either point of
        # rejection.
        if resp_create.status_code >= 400:
            validate_error(
                resp_create, ApiErrorId.ERR_NO_ELIGIBLE_PLAN_YEAR.value,
            )
            return
        draft = resp_create.json()["data"]
        resp_submit = api.submit_claim(
            draft["id"], make_account_holder_headers(holder["id"]),
        )
        validate_error(
            resp_submit, ApiErrorId.ERR_NO_ELIGIBLE_PLAN_YEAR.value,
        )


# ===========================================================================
# Approve and Pay — PRD §3.5
# ===========================================================================
class TestApproveAndPay:

    def test_approve_then_pay_transitions(self, api):
        """PRD §3.5: "Approval of a SUBMITTED claim by a
        ClaimAdjudicator ... the claim advances to APPROVED".
        PRD §3.5: "Payment of an APPROVED claim moves it to PAID."

        Claim: approve sets status APPROVED; pay sets PAID and
        paid_amount_cents == amount_cents.
        """
        holder, acct, py, qe, claim = setup_approved_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000,
            claim_cents=20_000,
        )
        assert claim["status"] == "APPROVED"
        pay_claim(claim["id"])
        final = get_claim(claim["id"])
        assert final["status"] == "PAID"
        assert final["paid_amount_cents"] == claim["amount_cents"]

    def test_pay_updates_plan_year_claims_paid_ytd(
        self, api,
    ):
        """PRD §3.5: "claims_paid_ytd_cents increases by the paid
        amount".

        Claim: post-pay, PlanYear.claims_paid_ytd_cents == amount.
        """
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000,
            claim_cents=15_000,
        )
        # py here is the post-pay snapshot returned by setup_paid_claim.
        assert py["claims_paid_ytd_cents"] == 15_000

    def test_pay_with_insufficient_balance_rejected(self, api):
        """PRD §3.5: "the claim's amount_cents no greater than the
        plan year's currently available balance (else
        ERR_INSUFFICIENT_BALANCE)."

        Claim: pay a claim whose amount exceeds the plan year's
        available balance -> ERR_INSUFFICIENT_BALANCE.
        """
        # Fund the plan year with only $100 but make a $5_000 claim.
        holder, acct, py, qe, claim = setup_approved_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100,
            claim_cents=5_000,
        )
        # Sanity: available balance must be < claim_cents.
        assert available_balance(py) < claim["amount_cents"]
        # Use a non-submitter adjudicator so SoD does not pre-empt
        # this check. SoD only applies to approve/deny per PRD §2.9.
        resp = api.pay_claim(
            claim["id"], make_adjudicator_headers("adjudicator-pay-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


# ===========================================================================
# Segregation of Duties — PRD §2.9, §3.5
# ===========================================================================
class TestSegregationOfDuties:

    def test_approve_by_submitter_id_rejected(self, api):
        """PRD §2.9: "the actor_user_id recorded on the
        CLAIM_SUBMITTED event for a given claim is compared to the
        current X-User-ID whenever that claim is approved or denied;
        if they match, the operation is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Claim: ClaimAdjudicator whose X-User-ID equals the submitting
        AccountHolder.id is rejected on /approve with
        ERR_SEGREGATION_OF_DUTIES.
        """
        holder, acct, py, qe, claim = setup_submitted_claim()
        # Build adjudicator headers whose X-User-ID equals the
        # holder's id — same as the actor on the CLAIM_SUBMITTED event.
        same_id_headers = make_adjudicator_headers(holder["id"])
        resp = api.approve_claim(claim["id"], same_id_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_deny_from_submitted_by_submitter_id_rejected(self, api):
        """PRD §3.5: "Denial from SUBMITTED is subject to
        segregation-of-duties (same rule as approval;
        ERR_SEGREGATION_OF_DUTIES on a same-user violation)."

        Claim: denying a SUBMITTED claim with X-User-ID equal to the
        submitting actor -> ERR_SEGREGATION_OF_DUTIES.
        """
        holder, acct, py, qe, claim = setup_submitted_claim()
        same_id_headers = make_adjudicator_headers(holder["id"])
        resp = api.deny_claim(
            claim["id"], deny_claim_payload(denial_reason="r"),
            same_id_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_deny_from_approved_not_subject_to_sod(self, api):
        """PRD §3.5: "Denial from APPROVED is not subject to
        segregation-of-duties, because the approval step has already
        required a second adjudicator."

        Claim: denying an APPROVED claim by an adjudicator whose
        X-User-ID equals the submitting AccountHolder.id is NOT
        rejected with ERR_SEGREGATION_OF_DUTIES (it succeeds).
        """
        holder, acct, py, qe, claim = setup_approved_claim()
        # Use an adjudicator whose id equals the submitter's; PRD
        # explicitly carves out APPROVED -> DENIED from SoD.
        same_id_headers = make_adjudicator_headers(holder["id"])
        resp = api.deny_claim(
            claim["id"],
            deny_claim_payload(denial_reason="approved-then-denied"),
            same_id_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DENIED"


# ===========================================================================
# Denial body — PRD §3.5
# ===========================================================================
class TestDenialReason:

    def test_deny_without_reason_rejected(
        self, api, adjudicator_headers_alt,
    ):
        """PRD §3.5: "The request body must include a denial_reason;
        absence of a denial reason returns ERR_DENIAL_REASON_REQUIRED."

        Claim: POST /claims/{id}/deny with empty body ->
        ERR_DENIAL_REASON_REQUIRED.
        """
        holder, acct, py, qe, claim = setup_submitted_claim()
        # Use an adjudicator who is NOT the submitter so SoD does not
        # pre-empt.
        resp = api._request(
            "POST", f"/claims/{claim['id']}/deny", {},
            adjudicator_headers_alt,
        )
        validate_error(resp, ApiErrorId.ERR_DENIAL_REASON_REQUIRED.value)


# ===========================================================================
# Reversal — PRD §3.5
# ===========================================================================
class TestClaimReverse:

    def test_reverse_paid_claim_changes_status_and_counters(
        self, api,
    ):
        """PRD §3.5: "On success, the original Claim row is mutated
        in place: status becomes REVERSED. The plan-year counters are
        restored: claims_paid_ytd_cents decreases by the original
        paid_amount_cents".

        Claim: reverse a PAID claim -> claim.status == REVERSED and
        PlanYear.claims_paid_ytd_cents drops back to 0.
        """
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000, claim_cents=20_000,
        )
        from test_helpers import reverse_claim
        reverse_claim(claim["id"])
        final_claim = get_claim(claim["id"])
        assert final_claim["status"] == "REVERSED"
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["claims_paid_ytd_cents"] == 0

    def test_reverse_paid_claim_inserts_twin(self, api):
        """PRD §3.5: "A twin Claim row is inserted whose
        reversed_from_id is the original's id, whose amount_cents
        equals the original amount_cents, whose status is REVERSED,
        and whose plan_year_id equals the original".

        Claim: after reversal, the account's claim list contains a
        twin row whose reversed_from_id == original.id.
        """
        from test_helpers import reverse_claim
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000, claim_cents=20_000,
        )
        reverse_claim(claim["id"])
        # Locate the twin.
        resp = api.list_claims(
            acct["id"],
            make_account_holder_headers(holder["id"]),
        )
        body = resp.json()
        rows = body.get("data", [])
        twins = [
            r for r in rows
            if r.get("reversed_from_id") == claim["id"]
        ]
        assert len(twins) == 1, (
            f"expected exactly one twin row, found {len(twins)}: {twins}"
        )
        twin = twins[0]
        assert twin["status"] == "REVERSED"
        assert twin["amount_cents"] == claim["amount_cents"]
        assert twin["plan_year_id"] == claim["plan_year_id"]
