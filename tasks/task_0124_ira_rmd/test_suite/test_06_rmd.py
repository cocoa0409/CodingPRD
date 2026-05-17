"""Required Minimum Distributions: divisor tables, age threshold,
RMD amount match, and RMD-already-taken serialization.

Coverage targets (PRD §3.5):
- ROTH (original owner) -> required_amount_cents == 0.
- TRADITIONAL with owner age < 73 -> 0.
- TRADITIONAL with owner age == 73 -> 10_000_000 / 26.5 -> 377_358.
- Inherited IRA with beneficiary age 50 -> 10_000_000 / 36.2 ->
  276_243.
- RMD-coded distribution amount must equal computed RMD exactly ->
  mismatch yields ERR_RMD_AMOUNT_MISMATCH.
- Second RMD for the same (account, tax_year) ->
  ERR_RMD_ALREADY_TAKEN.
- RMD for a tax_year < clock_year -> ERR_RMD_PERIOD_CLOSED.

Arithmetic per PRD §2.8 (half-up rounding):
  10_000_000 / 26.5 = 377_358.49056... -> half-up -> 377_358 cents
  (since .49... rounds DOWN; .5 would round UP).
  10_000_000 / 36.2 = 276_243.09392... -> half-up -> 276_243 cents.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_rmd_quote,
    create_distribution_payload,
    create_participant_born,
    get_account,
    get_clock_state,
    open_account,
    post_contribution,
    setup_inherited_account,
    setup_owner_rmd_eligible,
    take_distribution,
    validate_error,
    validate_success,
)


# ===========================================================================
# Zero RMD cases — PRD §3.5
# ===========================================================================
class TestZeroRmdCases:

    def test_roth_original_owner_has_zero_rmd(self, api, auditor_headers):
        """PRD §3.5: "A ROTH account whose inherited_from_participant_id
        is null (a Roth held by its original owner) has no lifetime RMD,
        and the required amount is 0."

        Claim: GET /rmd on original-owner Roth returns 0.
        """
        # Age the participant well past 73 so the Roth-exception
        # branch is the only path that can produce 0 (an under-73
        # owner would also return 0 via the age-under-73 branch). We
        # want the Roth branch to be load-bearing.
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        p = create_participant_born(ty - 75)
        a = open_account(p["id"], account_type="ROTH")
        resp = api.get_rmd(a["id"], auditor_headers,
                           params={"tax_year": ty})
        data = validate_success(resp, expected_status=200)
        assert_rmd_quote(data)
        assert data["required_amount_cents"] == 0

    def test_traditional_owner_under_73_has_zero_rmd(
        self, api, auditor_headers,
    ):
        """PRD §3.5: "A non-inherited account whose owner is younger
        than 73 in the queried tax_year (computed as the queried
        tax_year minus the year-portion of date_of_birth) also has a
        required amount of 0."

        Claim: TRADITIONAL with owner age < 73 -> required = 0.
        """
        # Read clock and choose dob so participant is age 60 in
        # tax_year=clock_year — robustly under 73.
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        p = create_participant_born(ty - 60)
        a = open_account(p["id"], account_type="TRADITIONAL")
        resp = api.get_rmd(a["id"], auditor_headers,
                           params={"tax_year": ty})
        data = validate_success(resp, expected_status=200)
        assert data["required_amount_cents"] == 0


# ===========================================================================
# Uniform Lifetime Table — PRD §3.5
# ===========================================================================
class TestUniformLifetimeRmd:
    """PRD §3.5: 'For a non-inherited account whose owner is 73 or
    older, the divisor comes from the Uniform Lifetime Table indexed
    by the participant's age on December 31 of the queried tax_year.
    The table covers (at minimum) ages 73 through 78 with the
    following divisors: 26.5 at age 73, 25.5 at age 74, 24.6 at age
    75, 23.7 at age 76, 22.9 at age 77, and 22.0 at age 78.'"""

    def test_age_73_divisor_26_5_yields_expected_amount(
        self, api, auditor_headers,
    ):
        """PRD §3.5: "26.5 at age 73" combined with PRD §2.8:
        "Wherever a calculation step produces a fractional cent ... the
        result is rounded half-up to the nearest whole cent."

        Claim: prior_year_end_balance_cents=10_000_000, owner age 73
        on Dec 31 of queried tax_year -> 10_000_000 / 26.5 =
        377358.49... -> round half-up to 377_358 cents.
        """
        p, a = setup_owner_rmd_eligible(
            target_age_on_dec31=73,
            prior_year_end_balance_cents=10_000_000,
        )
        # Query the RMD at the participant's current "age-73 year" —
        # the fixture targets the live clock_year for that age.
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        resp = api.get_rmd(
            a["id"], auditor_headers, params={"tax_year": ty},
        )
        data = validate_success(resp, expected_status=200)
        assert_rmd_quote(data)
        assert data["required_amount_cents"] == 377_358, (
            f"expected 377358, got {data['required_amount_cents']}"
        )


# ===========================================================================
# Single Life Table (inherited) — PRD §3.5
#
# DELETED per Step 7 STEP 1b (unique-derivability failure):
# The single-life base divisor 36.2 at age 50 is achievable only when
# (a) beneficiary_age_at_claim_year == 50 AND (b) year_offset == 0 AND
# (c) prior_year_end_balance_cents > 0. PRD §3.2 explicitly sets a new
# Inherited IRA's initial prior_year_end_balance_cents to 0, and the
# only way to drive that field positive is to advance the clock past at
# least one year-roll (which forces year_offset >= 1 and decrements the
# divisor). No PRD-faithful setup can produce 10_000_000 / 36.2; a
# faithful implementer would correctly return 10_000_000 / (36.2 - K)
# for K >= 1. The single-life table coverage remains exercised through
# the projection arithmetic tests and the dual-variant divergence test.
# ===========================================================================


# ===========================================================================
# RMD-distribution validation — PRD §3.5
# ===========================================================================
class TestRmdDistribution:

    def test_rmd_amount_mismatch_rejected(self, api, custodian_headers):
        """PRD §3.5: "Posting an RMD-coded distribution requires the
        submitted gross_amount_cents to equal the computed RMD amount
        for that account and tax year exactly. Any mismatch is
        rejected with ERR_RMD_AMOUNT_MISMATCH."

        Claim: RMD-coded distribution with amount != computed
        required_amount_cents -> ERR_RMD_AMOUNT_MISMATCH.
        """
        p, a = setup_owner_rmd_eligible(
            target_age_on_dec31=73,
            prior_year_end_balance_cents=10_000_000,
        )
        # Try to take RMD of 100_000 (wrong amount; correct is 377_358).
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=100_000,
                distribution_reason="RMD",
            ),
            custodian_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RMD_AMOUNT_MISMATCH.value)

    def test_rmd_exact_amount_succeeds(self, api, custodian_headers):
        """PRD §3.5: "Posting an RMD-coded distribution requires the
        submitted gross_amount_cents to equal the computed RMD amount
        for that account and tax year exactly."

        Claim: RMD-coded distribution with exact 377_358 -> 201.
        """
        p, a = setup_owner_rmd_eligible(
            target_age_on_dec31=73,
            prior_year_end_balance_cents=10_000_000,
        )
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=377_358,
                distribution_reason="RMD",
            ),
            custodian_headers,
        )
        d = validate_success(resp, expected_status=201)
        assert d["distribution_reason"] == "RMD"

    def test_second_rmd_same_year_rejected(self, api, custodian_headers):
        """PRD §3.5: "At most one RMD-coded distribution may exist per
        account per tax year; a second simultaneous RMD attempt on the
        same account in the same tax year is rejected with
        ERR_RMD_ALREADY_TAKEN (serialization is on the tuple of
        account id, tax_year, and RMD reason; first writer wins)."

        Claim: second RMD-coded distribution in same tax_year ->
        ERR_RMD_ALREADY_TAKEN.
        """
        p, a = setup_owner_rmd_eligible(
            target_age_on_dec31=73,
            prior_year_end_balance_cents=10_000_000,
        )
        # First succeeds.
        first = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=377_358,
                distribution_reason="RMD",
            ),
            custodian_headers,
        )
        validate_success(first, expected_status=201)
        # Second RMD attempt in same tax_year, same correct amount
        # (377_358 == prior_year_end_balance/26.5; the snapshot does
        # not change mid-year per PRD §2.10, so the quoted RMD remains
        # 377_358). The same-year attempt collides on the
        # (account_id, tax_year, RMD) tuple.
        resp = api.create_distribution(
            a["id"],
            create_distribution_payload(
                gross_amount_cents=377_358,
                distribution_reason="RMD",
            ),
            custodian_headers,
        )
        # PRD §3.5: "a second simultaneous RMD attempt on the same
        # account in the same tax year is rejected with
        # ERR_RMD_ALREADY_TAKEN".
        validate_error(resp, ApiErrorId.ERR_RMD_ALREADY_TAKEN.value)
