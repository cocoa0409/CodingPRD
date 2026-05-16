"""Drug claims and the four-phase donut hole calculation.

Covers PRD §3.8 — submission guards, segregation of duties on
adjudication, donut-hole phase walk with per-phase rounding, and the
reverse compensating-invariant.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_enrollment,
    adjudicate_drug_claim,
    advance_clock_to,
    assert_drug_claim,
    assert_drug_cost_estimate,
    assert_drug_phase_ledger,
    assert_ledger_sums_equal_adjudicated,
    create_beneficiary,
    create_drug_claim_payload,
    create_enrollment,
    create_enrollment_period,
    create_part_d_plan,
    create_plan,
    get_drug_cost_estimate,
    get_drug_phase_ledger,
    get_iep_period,
    re_get_beneficiary,
    re_get_drug_claim,
    reverse_drug_claim,
    setup_active_part_d_enrollment,
    setup_clock_at,
    setup_part_d_with_empty_ledger,
    setup_part_d_with_one_adjudicated_claim,
    submit_drug_claim,
    validate_error,
    validate_success,
    TEST_USERS,
)


class TestDrugClaimSubmission:
    """PRD §3.8 submission guards."""

    def test_submit_against_non_part_d_enrollment_rejected(
        self, api, counselor_headers,
    ):
        """PRD §3.8: "If the referenced enrollment is not Part D, the
        submission is rejected with ERR_NON_PART_D_CLAIM."

        Claim: submitting a claim against a PART_B enrollment ->
        ERR_NON_PART_D_CLAIM.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        iep = get_iep_period(b["id"])
        part_b_plan = create_plan(
            plan_type="PART_B", plan_year=2026,
            monthly_premium_cents=18_000,
        )
        pending = create_enrollment(
            beneficiary=re_b, plan=part_b_plan, enrollment_period=iep,
            effective_date="2026-04-01",
        )
        active = activate_enrollment(pending["id"])
        resp = api.create_drug_claim(
            create_drug_claim_payload(
                beneficiary_id=re_b["id"],
                enrollment_id=active["id"],
                tier="TIER_3", fill_date="2026-05-10",
                gross_cost_cents=10_000,
            ),
            counselor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NON_PART_D_CLAIM.value)

    def test_submit_fill_date_before_effective_rejected(
        self, api, counselor_headers,
    ):
        """PRD §3.8: "If fill_date is earlier than
        Enrollment.effective_date or later than the coalesce of
        Enrollment.termination_date and the last day of the plan's
        plan_year, the submission is rejected with
        ERR_FILL_DATE_OUT_OF_COVERAGE."

        Claim: fill_date < effective_date -> ERR_FILL_DATE_OUT_OF_COVERAGE.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        # effective_date in this fixture is 2026-04-01.
        resp = api.create_drug_claim(
            create_drug_claim_payload(
                beneficiary_id=b["id"], enrollment_id=active["id"],
                tier="TIER_3", fill_date="2026-03-01",
                gross_cost_cents=5_000,
            ),
            counselor_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_FILL_DATE_OUT_OF_COVERAGE.value,
        )


class TestSegregationOfDuties:
    """PRD §3.8 segregation of duties on adjudication."""

    def test_same_actor_submit_and_adjudicate_rejected(
        self, api, counselor_headers,
    ):
        """PRD §3.8: "The admin who performs adjudication cannot be the
        same operator who submitted the claim — if X-User-ID of the
        adjudication call equals the X-User-ID recorded at submission,
        the request is rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: when adjudicate X-User-ID equals submit X-User-ID,
        ERR_SEGREGATION_OF_DUTIES is returned. RBAC also permits only
        PlanAdmin to adjudicate (PRD §4); so we mint a PlanAdmin header
        whose X-User-ID matches the BenefitsCounselor's at submission.
        """
        b, plan, iep, active = setup_active_part_d_enrollment(
            dob_iso="1961-04-15", plan_year=2026,
        )
        # Submit with a specific counselor X-User-ID.
        from test_helpers import make_counselor_headers, make_admin_headers
        same_id = "shared-operator-1"
        submit_hdr = make_counselor_headers(same_id)
        adj_hdr = make_admin_headers(same_id)  # SAME X-User-ID
        claim_resp = api.create_drug_claim(
            create_drug_claim_payload(
                beneficiary_id=b["id"], enrollment_id=active["id"],
                tier="TIER_3", fill_date="2026-05-10",
                gross_cost_cents=10_000,
            ),
            submit_hdr,
        )
        claim = validate_success(claim_resp, expected_status=201)
        resp = api.adjudicate_drug_claim(claim["id"], {}, adj_hdr)
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )


class TestDonutHolePhaseWalkSingleClaim:
    """PRD §3.8 donut hole walk."""

    def test_deductible_only_no_rounding(self, api, counselor_headers):
        """PRD §3.8: "In this phase, the entire covered amount is
        charged to the beneficiary — there is no rounding in the
        deductible phase because the beneficiary pays one hundred
        percent."

        Claim: a claim entirely inside the deductible phase has
        beneficiary_cost_cents == gross_cost_cents and plan_cost_cents
        == 0; phase_at_adjudication == DEDUCTIBLE.

        Setup: empty ledger (deductible_paid_cents=0), claim gross
        20000 below D=40000.
        """
        b, plan, iep, active = setup_part_d_with_empty_ledger(
            dob_iso="1961-04-15", plan_year=2026,
            annual_deductible_cents=40_000,
            initial_coverage_limit_cents=400_000,
            catastrophic_threshold_cents=150_000,
        )
        submitted = submit_drug_claim(
            beneficiary=b, enrollment=active, tier="TIER_3",
            fill_date="2026-05-10", gross_cost_cents=20_000,
        )
        adj = adjudicate_drug_claim(submitted["id"])
        assert_drug_claim(adj)
        assert adj["status"] == "ADJUDICATED"
        assert adj["phase_at_adjudication"] == "DEDUCTIBLE"
        assert adj["beneficiary_cost_cents"] == 20_000, (
            f"deductible phase pays 100% to beneficiary, got "
            f"{adj['beneficiary_cost_cents']}"
        )
        assert adj["plan_cost_cents"] == 0

    def test_initial_coverage_tier_three_rounding(self, api,
                                                 counselor_headers):
        """PRD §3.8: "The beneficiary's share of the covered amount
        equals the covered amount multiplied by the tier-specific
        initial-coverage copay rate, rounded half up to integer cents.
        The five copay rates are 5% for TIER_1, 15% for TIER_2, 25%
        for TIER_3, 40% for TIER_4, and 50% for TIER_5."

        Claim: claim entirely inside initial coverage at TIER_3 ->
        beneficiary = round_half_up(gross * 0.25); plan = gross - bene.
        Setup: ledger already past deductible.
        """
        b, plan, iep, active = setup_part_d_with_empty_ledger(
            dob_iso="1961-04-15", plan_year=2026,
            annual_deductible_cents=40_000,
            initial_coverage_limit_cents=400_000,
            catastrophic_threshold_cents=150_000,
        )
        # First fill of 40000 covers exactly the deductible.
        c1_sub = submit_drug_claim(
            beneficiary=b, enrollment=active, tier="TIER_3",
            fill_date="2026-05-01", gross_cost_cents=40_000,
        )
        adjudicate_drug_claim(c1_sub["id"])
        # Now ledger: deductible_paid=40000, spend=40000, troop=40000.
        # Next fill 10000 entirely INITIAL_COVERAGE @ tier3 25%.
        c2_sub = submit_drug_claim(
            beneficiary=b, enrollment=active, tier="TIER_3",
            fill_date="2026-05-05", gross_cost_cents=10_000,
        )
        c2_adj = adjudicate_drug_claim(c2_sub["id"])
        assert c2_adj["phase_at_adjudication"] == "INITIAL_COVERAGE"
        # round_half_up(10000 * 0.25) = 2500.
        assert c2_adj["beneficiary_cost_cents"] == 2500, (
            f"expected beneficiary share 2500 (10000 * 0.25), got "
            f"{c2_adj['beneficiary_cost_cents']}"
        )
        assert c2_adj["plan_cost_cents"] == 7500

    def test_claim_spanning_deductible_to_initial_per_phase_rounding(
        self, api, counselor_headers,
    ):
        """PRD §3.8: "Rounding is applied once per phase share, not
        once at the end of the claim — this means the four rounded
        shares are summed to produce the claim totals."

        Claim: a single claim of 50001 cents at TIER_3 with empty
        ledger (D=40000) — Phase 1 covers 40000 unrounded; Phase 2
        covers remaining 10001 with round_half_up(10001 * 0.25) =
        round_half_up(2500.25) = 2500. Total bene = 40000 + 2500 =
        42500; plan = 10001 - 2500 = 7501. Naive "sum then round"
        would yield round_half_up(50001 * 0.25) = 12500 for the
        non-deductible portion — wrong.
        """
        b, plan, iep, active = setup_part_d_with_empty_ledger(
            dob_iso="1961-04-15", plan_year=2026,
            annual_deductible_cents=40_000,
            initial_coverage_limit_cents=400_000,
            catastrophic_threshold_cents=150_000,
        )
        sub = submit_drug_claim(
            beneficiary=b, enrollment=active, tier="TIER_3",
            fill_date="2026-05-01", gross_cost_cents=50_001,
        )
        adj = adjudicate_drug_claim(sub["id"])
        assert adj["phase_at_adjudication"] == "INITIAL_COVERAGE"
        assert adj["beneficiary_cost_cents"] == 42_500, (
            f"per-phase rounding: 40000 (deductible) + 2500 (initial) "
            f"= 42500; got {adj['beneficiary_cost_cents']}"
        )
        assert adj["plan_cost_cents"] == 7_501
        assert (
            adj["beneficiary_cost_cents"] + adj["plan_cost_cents"]
            == 50_001
        )


class TestForwardEstimateVariant:
    """PRD §3.8 forward-estimate variant."""

    def test_forward_estimate_does_not_mutate_ledger(self, api):
        """PRD §3.8: "The forward variant returns
        beneficiary_cost_cents, plan_cost_cents, and
        phase_at_adjudication (a projection — it does not write back to
        the claim row)."

        Claim: GET /beneficiaries/{id}/drug-cost-estimate returns the
        projection but does NOT change the ledger counters.
        """
        b, plan, iep, active = setup_part_d_with_empty_ledger(
            dob_iso="1961-04-15", plan_year=2026,
            annual_deductible_cents=40_000,
            initial_coverage_limit_cents=400_000,
            catastrophic_threshold_cents=150_000,
        )
        before = get_drug_phase_ledger(b["id"], plan_year=2026)
        estimate = get_drug_cost_estimate(
            b["id"], gross_cost_cents=20_000, tier="TIER_3",
        )
        assert_drug_cost_estimate(estimate)
        after = get_drug_phase_ledger(b["id"], plan_year=2026)
        assert (
            after["deductible_paid_cents"]
            == before["deductible_paid_cents"]
        )
        assert (
            after["total_drug_spend_cents"]
            == before["total_drug_spend_cents"]
        )
        assert after["troop_cents"] == before["troop_cents"]


class TestReverseClaim:
    """PRD §3.8 reverse a claim."""

    def test_reverse_submitted_no_ledger_impact(self, api,
                                                counselor_headers):
        """PRD §3.8: "From SUBMITTED, reversal simply moves the claim
        to REVERSED with no ledger impact."

        Claim: reverse a SUBMITTED claim -> status REVERSED, ledger
        unchanged.
        """
        b, plan, iep, active = setup_part_d_with_empty_ledger(
            dob_iso="1961-04-15", plan_year=2026,
            annual_deductible_cents=40_000,
            initial_coverage_limit_cents=400_000,
            catastrophic_threshold_cents=150_000,
        )
        before = get_drug_phase_ledger(b["id"], plan_year=2026)
        submitted = submit_drug_claim(
            beneficiary=b, enrollment=active, tier="TIER_3",
            fill_date="2026-05-10", gross_cost_cents=20_000,
        )
        reversed_claim = reverse_drug_claim(submitted["id"])
        assert reversed_claim["status"] == "REVERSED"
        after = get_drug_phase_ledger(b["id"], plan_year=2026)
        assert (
            after["deductible_paid_cents"]
            == before["deductible_paid_cents"]
        )
        assert after["troop_cents"] == before["troop_cents"]

    def test_reverse_last_adjudicated_rolls_back_ledger(
        self, api, counselor_headers,
    ):
        """PRD §3.8: "From ADJUDICATED, reversal first verifies that
        this claim is still the most recent adjudication against the
        ledger ... When permitted, the four ledger counters are
        decreased by exactly this claim's contribution and current_phase
        is recomputed from the updated counters".

        Claim: reverse the most-recently-adjudicated claim -> ledger
        counters roll back to pre-claim values.
        """
        b, plan, iep, active, claim_adj = (
            setup_part_d_with_one_adjudicated_claim(
                dob_iso="1961-04-15", plan_year=2026,
                fill_date_iso="2026-05-10", tier="TIER_3",
                gross_cost_cents=50_000,
            )
        )
        ledger_before = get_drug_phase_ledger(b["id"], plan_year=2026)
        assert ledger_before["total_drug_spend_cents"] == 50_000
        reverse_drug_claim(claim_adj["id"])
        ledger_after = get_drug_phase_ledger(b["id"], plan_year=2026)
        assert ledger_after["total_drug_spend_cents"] == 0
        assert ledger_after["deductible_paid_cents"] == 0
        assert ledger_after["troop_cents"] == 0
        assert ledger_after["current_phase"] == "DEDUCTIBLE", (
            f"after rollback, current_phase recomputed from zero "
            f"counters -> DEDUCTIBLE, got {ledger_after['current_phase']}"
        )
