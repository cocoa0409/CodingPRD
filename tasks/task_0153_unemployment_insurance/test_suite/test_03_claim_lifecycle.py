"""Claim lifecycle — PRD §3.2.

Tests DRAFT -> PENDING_ADJUDICATION -> {MONETARILY_ELIGIBLE | DENIED}
plus base-period selection, WBA calculation, max-weeks calculation,
and adjudicator-side wage-floor enforcement.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    MAX_REGULAR_WEEKS,
    MAX_WBA_CENTS,
    MIN_BASE_PERIOD_WAGES_CENTS,
    MIN_HIGH_QUARTER_WAGES_CENTS,
    MIN_REGULAR_WEEKS,
    MIN_WBA_CENTS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    adjudicate_claim_payload,
    assert_claim,
    assert_claim_monetary_fields_set,
    create_claim,
    create_claimant,
    create_employer,
    create_eligible_claim,
    make_adjudicator_headers,
    make_claimant_headers,
    next_certifiable_saturday,
    stage_eligible_wages,
    stage_low_wages_below_floors,
    submit_claim,
    validate_error,
    validate_success,
)


class TestClaimDraft:

    def test_create_claim_starts_in_draft(self, api):
        """PRD §3.2: "A claimant opens a new claim by posting under
        their own claimant resource; the returned Claim enters DRAFT."
        """
        claimant = create_claimant()
        claim = create_claim(claimant)
        assert_claim(claim)
        assert claim["status"] == "DRAFT"
        assert claim["claimant_id"] == claimant["id"]

    def test_submit_without_any_wage_records_rejected(self, api):
        """PRD §3.2: "Submission requires that the requesting claimant
        own the claim and that the claimant has at least one WageRecord
        falling within either candidate base period (otherwise the
        submission is rejected with ERR_INVALID_STATE)."
        """
        claimant = create_claimant()
        claim = create_claim(claimant)
        resp = api.submit_claim(
            claim["id"], make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestClaimSubmission:

    def test_submit_runs_calculations(self, api):
        """PRD §3.2: "The act of submission runs three sequenced
        calculations and stamps the claim's filing_date to
        SystemClock.now, sets benefit_year_start to the first Sunday on
        or before filing_date, and sets benefit_year_end to 364 days
        after benefit_year_start."
        """
        claimant = create_claimant()
        employer = create_employer()
        stage_eligible_wages(claimant["id"], employer["id"])
        claim = create_claim(claimant)
        claim = submit_claim(claim, claimant["id"])
        assert claim["status"] == "PENDING_ADJUDICATION"
        assert_claim_monetary_fields_set(claim)
        assert claim.get("filing_date"), "filing_date must be set"
        assert claim.get("benefit_year_start"), (
            "benefit_year_start must be set"
        )
        assert claim.get("benefit_year_end"), (
            "benefit_year_end must be set"
        )

    def test_wba_floor_when_high_quarter_below_minimum(self, api):
        """PRD §3.2: "The weekly benefit amount in cents is computed by
        dividing high_quarter_wages_cents by 26 with floor (truncating)
        division, then clamping the result to the range from 4,000 cents
        ($40.00) at the floor to 60,000 cents ($600.00) at the ceiling."
        """
        claimant = create_claimant()
        employer = create_employer()
        # high_quarter = 26 cents -> raw WBA = 1 -> floor-clamped to 4_000.
        # Use 26 for high quarter, and pad the other quarters so total
        # clears 150_000 floor — though monetary eligibility may still
        # fail at adjudicate.
        from test_helpers import post_wage_record, base_period_quarters_at, current_clock
        now = current_clock()
        qs = base_period_quarters_at(now)["STANDARD"]
        post_wage_record(claimant["id"], employer["id"], qs[0][0], qs[0][1], 26)
        post_wage_record(claimant["id"], employer["id"], qs[1][0], qs[1][1], 50_000)
        post_wage_record(claimant["id"], employer["id"], qs[2][0], qs[2][1], 50_000)
        post_wage_record(claimant["id"], employer["id"], qs[3][0], qs[3][1], 50_000)
        claim = create_claim(claimant)
        claim = submit_claim(claim, claimant["id"])
        # high_quarter is 50_000 (the highest of the four); WBA raw =
        # floor(50_000/26) = 1923; floor-clamped to 4_000.
        assert claim["weekly_benefit_amount_cents"] == MIN_WBA_CENTS, (
            f"WBA must be floor-clamped to {MIN_WBA_CENTS}, "
            f"got {claim['weekly_benefit_amount_cents']}"
        )

    def test_wba_ceiling_when_high_quarter_huge(self, api):
        """PRD §3.2: "clamping the result to the range from 4,000 cents
        ($40.00) at the floor to 60,000 cents ($600.00) at the ceiling."
        """
        claimant = create_claimant()
        employer = create_employer()
        # high_quarter = 10_000_000 cents ($100,000) -> WBA raw =
        # floor(10_000_000/26) = 384_615; ceiling-clamped to 60_000.
        stage_eligible_wages(
            claimant["id"], employer["id"],
            high_quarter_cents=10_000_000,
            other_quarter_cents=500_000,
        )
        claim = create_claim(claimant)
        claim = submit_claim(claim, claimant["id"])
        assert claim["weekly_benefit_amount_cents"] == MAX_WBA_CENTS, (
            f"WBA must be ceiling-clamped to {MAX_WBA_CENTS}, "
            f"got {claim['weekly_benefit_amount_cents']}"
        )

    def test_wba_floor_division_truncates_not_rounds(self, api):
        """PRD §3.2: "Truncation, not rounding, is used at the divide
        step."

        With high_quarter = 26 * 100 + 25 = 2625, floor(2625/26) = 100.
        Round-half-up would give 101.
        Then the result 100 is floor-clamped up to MIN_WBA_CENTS=4_000.
        We pick a different value that lands above the floor:
            high_quarter = 26 * 200 + 25 = 5225 -> floor 200, ceil 201;
            both below MIN_WBA_CENTS so clamped to 4_000 anyway.
        So we use 26 * 5_000 + 25 = 130_025 -> raw 5_001, no clamp.
        """
        claimant = create_claimant()
        employer = create_employer()
        stage_eligible_wages(
            claimant["id"], employer["id"],
            high_quarter_cents=130_025,
            other_quarter_cents=50_000,
        )
        claim = create_claim(claimant)
        claim = submit_claim(claim, claimant["id"])
        # floor(130_025/26) = 5_000 (not 5_001 which is round-half-up).
        assert claim["weekly_benefit_amount_cents"] == 5_000, (
            f"floor division must truncate; got "
            f"{claim['weekly_benefit_amount_cents']}, expected 5_000"
        )

    def test_max_weeks_floor_clamp(self, api):
        """PRD §3.2: "clamping the result to lie between a minimum of
        13 weeks and a maximum of 26 weeks inclusive."

        Wages must clear PRD §3.2 floors (base_period_total >= 150_000
        AND high_quarter >= 90_000) so adjudicate-ELIGIBLE accepts;
        meanwhile the raw max-weeks quotient must fall below 13 so the
        min clamp pins the result at 13.
        """
        # high_quarter = 90_000 (exactly the floor), each other = 20_000:
        # total = 90_000 + 3*20_000 = 150_000 (exactly the floor).
        # WBA = floor(90_000/26) = 3_461 -> min-clamped to 4_000.
        # raw potential = floor(150_000 / (4_000 * 3)) = floor(12.5) = 12;
        # clamped to MIN_REGULAR_WEEKS = 13.
        bundle = create_eligible_claim(
            high_quarter_cents=90_000,
            other_quarter_cents=20_000,
        )
        claim = bundle["claim"]
        assert claim["max_weeks_of_eligibility"] == MIN_REGULAR_WEEKS

    def test_max_weeks_ceiling_clamp(self, api):
        """PRD §3.2: "clamping the result to lie between a minimum of
        13 weeks and a maximum of 26 weeks inclusive."
        """
        bundle = create_eligible_claim(
            high_quarter_cents=2_000_000,
            other_quarter_cents=2_000_000,
        )
        claim = bundle["claim"]
        # WBA = floor(2_000_000/26) = 76_923 -> ceiling-clamped 60_000.
        # total = 8_000_000; potential = floor(8_000_000/(60_000*3))
        #       = floor(44.44) = 44; clamped to MAX_REGULAR_WEEKS = 26.
        assert claim["max_weeks_of_eligibility"] == MAX_REGULAR_WEEKS


class TestAdjudication:

    def test_eligible_when_floors_met(self, api):
        """PRD §3.2: "When accepted, an ELIGIBLE decision transitions
        the claim to MONETARILY_ELIGIBLE."
        """
        bundle = create_eligible_claim()
        assert bundle["claim"]["status"] == "MONETARILY_ELIGIBLE"

    def test_denied_when_floors_unmet(self, api):
        """PRD §3.2: "a DENIED decision (which is the appropriate
        decision precisely when either wage floor is unmet) transitions
        the claim to DENIED."
        """
        from test_helpers import create_denied_claim
        bundle = create_denied_claim()
        assert bundle["claim"]["status"] == "DENIED"

    def test_eligible_rejected_when_base_period_below_floor(self, api):
        """PRD §3.2: "A decision of ELIGIBLE is rejected with
        ERR_INSUFFICIENT_BASE_PERIOD_WAGES unless both wage floors are
        met (base_period_total_wages_cents at least 150,000 cents and
        high_quarter_wages_cents at least 90,000 cents) and
        weekly_benefit_amount_cents is strictly greater than zero."
        """
        claimant = create_claimant()
        employer = create_employer()
        stage_low_wages_below_floors(claimant["id"], employer["id"])
        claim = create_claim(claimant)
        claim = submit_claim(claim, claimant["id"])
        # Attempt ELIGIBLE despite failing floors -> should be rejected.
        resp = api.adjudicate_claim(
            claim["id"], adjudicate_claim_payload("ELIGIBLE"),
            make_adjudicator_headers(),
        )
        validate_error(
            resp,
            ApiErrorId.ERR_INSUFFICIENT_BASE_PERIOD_WAGES.value,
        )

    def test_adjudicator_id_recorded_for_segregation(self, api):
        """PRD §3.2: "Either way, the adjudicator's X-User-ID is
        recorded on the claim's adjudication record as
        assigned_adjudicator_id and the claim's version is incremented."
        """
        bundle = create_eligible_claim(adjudicator_id="adjudicator-9999")
        claim = bundle["claim"]
        # The field is exposed on the Claim record (PRD §2.11).
        assert claim.get("assigned_adjudicator_id") == "adjudicator-9999"

    def test_invalid_decision_value_rejected(self, api):
        """PRD §3.2: "The request body carries a decision of either
        ELIGIBLE or DENIED together with an optional version for the
        OCC check."
        """
        claimant = create_claimant()
        employer = create_employer()
        stage_eligible_wages(claimant["id"], employer["id"])
        claim = create_claim(claimant)
        claim = submit_claim(claim, claimant["id"])
        resp = api.adjudicate_claim(
            claim["id"], {"decision": "MAYBE"},
            make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_adjudicate_nonexistent_claim_not_found(self, api):
        """PRD §2.7: "URL paths are validated left to right. ...
        Only after every path segment resolves does the server proceed
        to ownership, state, and body validation."
        """
        resp = api.adjudicate_claim(
            NON_EXISTENT_UUID, adjudicate_claim_payload("ELIGIBLE"),
            make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_adjudicate_draft_claim_invalid_state(self, api):
        """PRD §3.2: "A PENDING_ADJUDICATION claim is decided by an
        Adjudicator."
        """
        claimant = create_claimant()
        employer = create_employer()
        stage_eligible_wages(claimant["id"], employer["id"])
        claim = create_claim(claimant)  # DRAFT, not yet submitted
        resp = api.adjudicate_claim(
            claim["id"], adjudicate_claim_payload("ELIGIBLE"),
            make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
