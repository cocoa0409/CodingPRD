"""Contribution posting, annual cap, and catch-up eligibility.

Coverage targets (PRD §3.3):
- REGULAR cap = 7,000 dollars (700,000 cents); CATCHUP +1,000 dollars
  (+100,000 cents) when age on Dec 31 of clock year >= 50.
- ERR_CONTRIBUTION_CAP_EXCEEDED when ytd + amount > applicable cap.
- ERR_CATCHUP_AGE_INELIGIBLE when CATCHUP and age < 50.
- Boundary at exactly age 50 on Dec 31.
- Reversal decrements ytd and balance, marks event REVERSED, creates
  EXCESS_REMOVAL distribution.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_contribution_event,
    create_contribution_payload,
    create_participant,
    create_participant_born,
    get_account,
    open_account,
    post_contribution,
    setup_owner_rmd_eligible,
    validate_error,
    validate_success,
)


# ===========================================================================
# Successful posting — PRD §3.3
# ===========================================================================
class TestPostContribution:

    def test_regular_contribution_increments_ytd_and_balance(
        self, api, custodian_headers,
    ):
        """PRD §3.3: "Posting captures the current clock year as the
        event's tax_year, sets the event's initial status to POSTED,
        leaves reversed_at as null, increments
        Account.ytd_contribution_cents by the contribution amount, and
        increments Account.balance_cents by the same amount — all
        atomically."

        Claim: successful contribution returns POSTED event and bumps
        ytd + balance.
        """
        p = create_participant_born(1990)
        a = open_account(p["id"])
        payload = create_contribution_payload(
            amount_cents=500_000, contribution_type="REGULAR",
        )
        resp = api.create_contribution(a["id"], payload,
                                       custodian_headers)
        ev = validate_success(resp, expected_status=201)
        assert_contribution_event(ev)
        assert ev["status"] == "POSTED"
        assert ev["amount_cents"] == 500_000
        assert ev["contribution_type"] == "REGULAR"
        assert ev.get("reversed_at") is None
        # Re-read account.
        a2 = get_account(p["id"], a["id"])
        assert a2["balance_cents"] == 500_000
        assert a2["ytd_contribution_cents"] == 500_000


# ===========================================================================
# Cap — PRD §3.3 boundary X-1, X, X+1
# ===========================================================================
class TestContributionCap:

    def test_cap_at_exact_regular_limit_succeeds(self, api,
                                                 custodian_headers):
        """PRD §3.3: "The cap check rejects the contribution with
        ERR_CONTRIBUTION_CAP_EXCEEDED whenever the new posting's
        amount_cents added to the account's current
        ytd_contribution_cents would exceed this applicable cap.
        (Equality with the cap is permitted; strict over-cap is
        rejected.)"

        Claim: posting exactly 700_000 to an under-50 participant's
        empty account succeeds.
        """
        p = create_participant_born(1990)
        a = open_account(p["id"])
        resp = api.create_contribution(
            a["id"],
            create_contribution_payload(
                amount_cents=700_000, contribution_type="REGULAR",
            ),
            custodian_headers,
        )
        validate_success(resp, expected_status=201)

    def test_one_cent_over_cap_rejected(self, api, custodian_headers):
        """PRD §3.3: "Equality with the cap is permitted; strict
        over-cap is rejected."

        Claim: posting 700_001 to an under-50 empty account ->
        ERR_CONTRIBUTION_CAP_EXCEEDED.
        """
        p = create_participant_born(1990)
        a = open_account(p["id"])
        # Limit single-call to MAX_SINGLE_CONTRIBUTION_CENTS = 1_000_000
        # so the cap is the gating rule, not the per-call ceiling.
        resp = api.create_contribution(
            a["id"],
            create_contribution_payload(
                amount_cents=700_001, contribution_type="REGULAR",
            ),
            custodian_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value,
        )

    def test_catchup_eligible_extends_cap_to_800k(
        self, api, custodian_headers,
    ):
        """PRD §3.3: "The applicable cap for the posting decision is
        therefore the base cap plus the catch-up addition — 700,000
        cents for participants younger than 50 on December 31 of the
        clock year, and 800,000 cents for participants who reach 50
        or older by that date."

        Claim: participant age 50+ may post 800_000 CATCHUP to empty
        account.
        """
        # Born 1970 — definitely age 50+ on Dec 31 of any clock year
        # >= 2026 (the default seeded clock).
        p = create_participant_born(1970)
        a = open_account(p["id"])
        resp = api.create_contribution(
            a["id"],
            create_contribution_payload(
                amount_cents=800_000, contribution_type="CATCHUP",
            ),
            custodian_headers,
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Catch-up age eligibility — PRD §3.3
# ===========================================================================
class TestCatchupAgeEligibility:

    def test_catchup_under_50_rejected(self, api, custodian_headers):
        """PRD §3.3: "A catch-up contribution submitted by a
        participant who is too young is rejected with
        ERR_CATCHUP_AGE_INELIGIBLE, even if the cap arithmetic would
        have permitted it."

        Claim: CATCHUP by participant age < 50 ->
        ERR_CATCHUP_AGE_INELIGIBLE.
        """
        p = create_participant_born(1985)  # well under 50
        a = open_account(p["id"])
        resp = api.create_contribution(
            a["id"],
            create_contribution_payload(
                amount_cents=100_000, contribution_type="CATCHUP",
            ),
            custodian_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_CATCHUP_AGE_INELIGIBLE.value,
        )


# ===========================================================================
# Reversal — PRD §3.3
# ===========================================================================
class TestContributionReversal:

    def test_reversal_decrements_balance_and_marks_event(
        self, api, custodian_headers,
    ):
        """PRD §3.3: "Reversal sets the event's status to REVERSED,
        stamps its reversed_at with the current timestamp, decrements
        both Account.ytd_contribution_cents and Account.balance_cents
        by the original amount_cents, and creates a matching
        DistributionEvent with distribution_reason equal to
        EXCESS_REMOVAL, gross_amount_cents equal to the original
        contribution amount, and federal_withholding_cents equal to 0."

        Claim: reversal flips status -> REVERSED, sets reversed_at,
        and zeros balance/ytd.
        """
        p = create_participant_born(1985)
        a = open_account(p["id"])
        ev = post_contribution(a["id"], amount_cents=400_000)
        resp = api.reverse_contribution(ev["id"], custodian_headers)
        rev_ev = validate_success(resp, expected_status=200)
        assert rev_ev["status"] == "REVERSED"
        assert rev_ev.get("reversed_at") is not None
        a2 = get_account(p["id"], a["id"])
        assert a2["balance_cents"] == 0
        assert a2["ytd_contribution_cents"] == 0
