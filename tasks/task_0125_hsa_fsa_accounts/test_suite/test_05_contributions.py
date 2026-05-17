"""Contributions — PRD §3.3.

Coverage targets:
- POSTED happy path: amount_cents and source preserved, posted_at set,
  PlanYear.contributions_ytd_cents incremented.
- Cap enforcement at boundary: post-write sum > cap+catch_up -> reject.
- EMPLOYER_MATCH on HSA counts against the cap.
- Reversal: original -> REVERSED, twin row inserted, counter rolls
  back; ERR_REVERSAL_WOULD_OVERDRAW when reversal would push
  contributions_ytd below claims_paid_ytd.
- Account-state preconditions: FROZEN account rejects new contribution.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_contribution,
    create_contribution_payload,
    freeze_account,
    get_plan_year,
    iso_datetime_utc,
    post_contribution,
    reverse_contribution,
    setup_active_plan_year,
    setup_paid_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Contribution post happy path — PRD §3.3
# ===========================================================================
class TestContributionPost:

    def test_post_contribution_returns_posted(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "Contributions are append-only; the row is created
        with status PENDING and immediately advanced to POSTED in the
        same request, so in the happy path callers observe POSTED
        directly."

        Claim: POST /plan-years/{id}/contributions returns status
        POSTED with positive amount_cents.
        """
        _, _, py = setup_active_plan_year()
        payload = create_contribution_payload(
            amount_cents=10_000, source="PAYROLL",
        )
        resp = api.create_contribution(
            py["id"], payload, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_contribution(data)
        assert data["status"] == "POSTED"
        assert data["amount_cents"] == 10_000
        assert data["source"] == "PAYROLL"
        assert data["plan_year_id"] == py["id"]

    def test_contribution_updates_plan_year_counters(
        self, api,
    ):
        """PRD §3.3: "atomically updates the plan year — adding
        amount_cents to contributions_ytd_cents, recomputing
        provisional_balance_cents, refreshing the plan year's
        updated_at, and incrementing PlanYear.version."

        Claim: post-contribution PlanYear has counters incremented and
        version bumped by exactly 1.
        """
        _, acct, py = setup_active_plan_year()
        prev_version = py["version"]
        post_contribution(py["id"], amount_cents=15_000, source="DIRECT")
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["contributions_ytd_cents"] == 15_000
        assert py_after["version"] == prev_version + 1

    @pytest.mark.parametrize(
        "source", ["PAYROLL", "DIRECT", "EMPLOYER_MATCH"],
    )
    def test_contribution_each_source_accepted(
        self, api, plan_admin_headers, source,
    ):
        """PRD §3.3: "a source enumerated as PAYROLL, DIRECT, or
        EMPLOYER_MATCH".

        Claim: each source value is accepted.
        """
        _, _, py = setup_active_plan_year()
        payload = create_contribution_payload(
            amount_cents=10_000, source=source,
        )
        resp = api.create_contribution(
            py["id"], payload, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["source"] == source


# ===========================================================================
# Cap enforcement — PRD §3.3
# ===========================================================================
class TestContributionCap:

    def test_post_at_exact_cap_succeeds(self, api, plan_admin_headers):
        """PRD §3.3: "the sum of the prior contributions_ytd_cents and
        the new amount_cents must be at most contribution_cap_cents
        plus catch_up_cap_cents."

        Claim (boundary): HSA SELF_ONLY cap = 412_500; a single
        contribution of exactly 412_500 succeeds.
        """
        _, _, py = setup_active_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
        )
        resp = api.create_contribution(
            py["id"],
            create_contribution_payload(amount_cents=412_500),
            plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "POSTED"

    def test_post_one_cent_above_cap_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "If posting would push the total above that
        combined ceiling, the contribution is rejected with
        ERR_CONTRIBUTION_CAP_EXCEEDED."

        Claim (boundary): contributing 412_500 + 1 to an HSA
        SELF_ONLY account -> second call ERR_CONTRIBUTION_CAP_EXCEEDED.
        """
        _, _, py = setup_active_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
        )
        post_contribution(py["id"], amount_cents=412_500, source="PAYROLL")
        resp = api.create_contribution(
            py["id"],
            create_contribution_payload(amount_cents=1),
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)

    def test_employer_match_counts_against_hsa_cap(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "The employer-match source is not exempt: when
        source is EMPLOYER_MATCH and account_type is HSA, the matched
        amount counts against the cap exactly as a PAYROLL
        contribution does."

        Claim: PAYROLL 412_500 + EMPLOYER_MATCH 1 on HSA SELF_ONLY ->
        the EMPLOYER_MATCH call is rejected with
        ERR_CONTRIBUTION_CAP_EXCEEDED.
        """
        _, _, py = setup_active_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
        )
        post_contribution(py["id"], amount_cents=412_500, source="PAYROLL")
        resp = api.create_contribution(
            py["id"],
            create_contribution_payload(
                amount_cents=1, source="EMPLOYER_MATCH",
            ),
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)

    def test_hsa_with_catch_up_increases_cap(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "the sum of the prior contributions_ytd_cents and
        the new amount_cents must be at most contribution_cap_cents
        plus catch_up_cap_cents."
        PRD §3.2: "The HSA catch-up cap catch_up_cap_cents is 100,000
        cents ($1,000.00) if, on December 31 of the plan year's
        calendar_year ... the account holder's age ... is at least 55".

        Claim: age-55+ HSA SELF_ONLY accepts contributions up to
        412_500 + 100_000 = 512_500.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, _, py = setup_active_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            birth_date="1969-06-01", calendar_year=2025,
        )
        # A single contribution at 512_500 should succeed.
        resp = api.create_contribution(
            py["id"],
            create_contribution_payload(amount_cents=512_500),
            plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["amount_cents"] == 512_500


# ===========================================================================
# Reversal — PRD §3.3
# ===========================================================================
class TestContributionReverse:

    def test_reverse_contribution_creates_twin(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "On success, the original contribution's status
        transitions to REVERSED; a new Contribution row is appended
        with amount_cents equal to the negative of the original,
        status POSTED, and reversal_of_id set to the original's id."

        Claim: reversal appends a new row whose amount_cents is the
        negative of the original and whose reversal_of_id points back.
        """
        _, _, py = setup_active_plan_year()
        original = post_contribution(
            py["id"], amount_cents=20_000, source="PAYROLL",
        )
        resp = api.reverse_contribution(
            original["id"], plan_admin_headers,
        )
        twin = validate_success(resp, expected_status=200)
        assert_contribution(twin)
        assert twin["amount_cents"] == -20_000
        assert twin["status"] == "POSTED"
        assert twin["reversal_of_id"] == original["id"]

    def test_reverse_contribution_updates_counters(
        self, api,
    ):
        """PRD §3.3: "The plan year's contributions_ytd_cents
        decreases by the original amount, provisional_balance_cents
        is recomputed, and PlanYear.version is incremented."

        Claim: after reversal, contributions_ytd_cents == 0 and
        PlanYear.version increments.
        """
        _, acct, py = setup_active_plan_year()
        original = post_contribution(
            py["id"], amount_cents=20_000, source="PAYROLL",
        )
        py_after_post = get_plan_year(acct["id"], py["id"])
        reverse_contribution(original["id"])
        py_after_reverse = get_plan_year(acct["id"], py["id"])
        assert py_after_reverse["contributions_ytd_cents"] == 0
        assert py_after_reverse["version"] >= py_after_post["version"] + 1

    def test_reverse_would_overdraw_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "It is additionally rejected with
        ERR_REVERSAL_WOULD_OVERDRAW if, after subtracting the original
        amount_cents, the plan year's contributions_ytd_cents would
        drop below its claims_paid_ytd_cents."

        Claim: when a claim has been paid against the contribution,
        reversing that contribution -> ERR_REVERSAL_WOULD_OVERDRAW.
        """
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA",
            coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=20_000,
            claim_cents=20_000,
        )
        # Need the original contribution id. List and pick the first
        # POSTED non-reversal row.
        resp = api.list_contributions(py["id"], plan_admin_headers)
        body = resp.json()
        rows = body.get("data", []) if isinstance(body, dict) else []
        natural = [
            r for r in rows
            if r.get("status") == "POSTED" and r.get("amount_cents", 0) > 0
            and r.get("reversal_of_id") is None
        ]
        assert natural, "expected at least one natural POSTED contribution"
        contrib_id = natural[0]["id"]
        rev_resp = api.reverse_contribution(contrib_id, plan_admin_headers)
        validate_error(
            rev_resp, ApiErrorId.ERR_REVERSAL_WOULD_OVERDRAW.value,
        )


# ===========================================================================
# Account-state preconditions — PRD §3.3
# ===========================================================================
class TestContributionAccountState:

    def test_contribution_on_frozen_account_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "Posting a contribution requires that the linked
        Account.status is OPEN (otherwise ERR_ACCOUNT_NOT_OPEN)".

        Claim: POST /plan-years/{id}/contributions when the account is
        FROZEN -> ERR_ACCOUNT_NOT_OPEN.
        """
        _, acct, py = setup_active_plan_year()
        freeze_account(acct["id"])
        resp = api.create_contribution(
            py["id"],
            create_contribution_payload(amount_cents=10_000),
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN.value)
