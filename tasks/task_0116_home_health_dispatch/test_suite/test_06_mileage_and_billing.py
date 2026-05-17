"""Mileage capture, tier formula, PDGM claim provisional vs. final.

PRD §3.6 (Mileage Capture), §3.7 (PDGM Claim Computation), §2.6
(Precision).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    LUPA_PER_VISIT_RATE,
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_mileage_log,
    assert_money_2dp,
    assert_pdgm_claim,
    close_episode_at_end_date,
    create_mileage_payload,
    make_field_clinician_headers,
    re_get_claim,
    record_mileage,
    setup_episode_with_one_completed_visit,
    setup_episode_with_three_completed_visits,
    setup_episode_with_two_completed_sn_visits_for_mileage,
    validate_error,
    validate_success,
)


# ===========================================================================
# Mileage capture — preconditions
# ===========================================================================
class TestMileagePreconditions:

    def test_zero_miles_rejected(self, api):
        """PRD §3.6: "it must be strictly greater than zero, and a value
        of zero or negative is rejected with ERR_MILEAGE_NOT_POSITIVE."

        Claim: miles_driven == 0 is rejected with
        ERR_MILEAGE_NOT_POSITIVE.
        # difficulty: boundary_precision_check/mileage_zero_miles_rejection_boundary
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        res = api.create_mileage(
            visit["id"],
            create_mileage_payload(miles_driven=0),
            make_field_clinician_headers(clinician["id"]),
        )
        validate_error(res, "ERR_MILEAGE_NOT_POSITIVE")

    def test_negative_miles_rejected(self, api):
        """PRD §3.6: "a value of zero or negative is rejected with
        ERR_MILEAGE_NOT_POSITIVE."

        Claim: a negative miles_driven is rejected.
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        res = api.create_mileage(
            visit["id"],
            create_mileage_payload(miles_driven=-5),
            make_field_clinician_headers(clinician["id"]),
        )
        validate_error(res, "ERR_MILEAGE_NOT_POSITIVE")

    def test_mileage_against_scheduled_visit_rejected(self, api):
        """PRD §3.6: "The parent visit must be in COMPLETED status; a
        mileage record attempted against a SCHEDULED or CANCELLED visit
        is rejected with ERR_MILEAGE_VISIT_NOT_COMPLETED."

        Claim: recording mileage on a SCHEDULED (not COMPLETED) visit
        is rejected.
        """
        from test_helpers import (
            create_clinician,
            schedule_visit,
            setup_open_episode,
        )
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        visit = schedule_visit(episode=episode, clinician=clinician)
        # Visit is still SCHEDULED (we did not complete it).
        res = api.create_mileage(
            visit["id"],
            create_mileage_payload(miles_driven=10),
            make_field_clinician_headers(clinician["id"]),
        )
        validate_error(res, "ERR_MILEAGE_VISIT_NOT_COMPLETED")


# ===========================================================================
# Mileage tier formula
# ===========================================================================
class TestMileageTiers:

    def test_within_tier1_30_miles(self, api):
        """PRD §3.6: "The first tier covers the first 30 miles;
        specifically, take whichever is smaller — miles_driven or 30 —
        and multiply by 0.70 USD per mile."

        Claim: 30 miles → 30 * 0.70 = 21.00.
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=30,
        )
        assert_mileage_log(ml)
        assert ml["reimbursement_amount"] == pytest.approx(21.00, abs=0.001)

    def test_within_tier2_50_miles(self, api):
        """PRD §3.6: "The second tier covers miles in the range above
        30 up to and including 100 … multiply by 0.55 USD per mile."

        Claim: 50 miles → 30*0.70 + 20*0.55 = 21.00 + 11.00 = 32.00.
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=50,
        )
        assert ml["reimbursement_amount"] == pytest.approx(32.00, abs=0.001)

    def test_at_tier2_boundary_100_miles(self, api):
        """PRD §3.6: "Tier 1 is inclusive of mile 30; tier 2 covers the
        interval from mile 30 (exclusive) through mile 100 (inclusive);
        tier 3 covers everything strictly above mile 100."

        Claim: exactly 100 miles uses only tier 1 + tier 2:
        30*0.70 + 70*0.55 = 21.00 + 38.50 = 59.50.
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=100,
        )
        assert ml["reimbursement_amount"] == pytest.approx(59.50, abs=0.001)

    def test_into_tier3_150_miles(self, api):
        """PRD §3.6: "The third tier covers every mile beyond 100;
        specifically, subtract 100 from miles_driven (floored at zero)
        and multiply by 0.40 USD per mile."

        Claim: 150 miles → 30*0.70 + 70*0.55 + 50*0.40 = 79.50.
        # difficulty: combinatorial_formula/mileage_three_tier_breakpoint_formula
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=150,
        )
        assert ml["reimbursement_amount"] == pytest.approx(79.50, abs=0.001)


# ===========================================================================
# Claim aggregation — round-then-sum
# ===========================================================================
class TestMileageRoundThenSum:

    def test_total_mileage_reimbursement_is_sum_of_rounded_rows(self, api):
        """PRD §2.6: "Mileage uses a round-then-sum convention that is
        load-bearing: each MileageLog's reimbursement_amount is rounded
        to two decimals at insertion time, and the claim's
        total_mileage_reimbursement is the sum of those already-rounded
        values with no further rounding."

        Claim: with two MileageLogs of 31.7 and 32.3 miles, per-log
        amounts are 21.94 and 22.27 (round-then-sum), and the claim's
        total_mileage_reimbursement equals 44.21 — not 44.20 that
        sum-then-round would produce.

        # difficulty: dual_variant_calc/mileage_round_then_sum_vs_sum_then_round_divergence
        """
        # Per PRD §3.6 tier formula:
        # m = 31.7 → 30*0.70 + 1.7*0.55 = 21.00 + 0.935 = 21.935
        #            round_half_up to 2dp → 21.94
        # m = 32.3 → 30*0.70 + 2.3*0.55 = 21.00 + 1.265 = 22.265
        #            round_half_up to 2dp → 22.27 (half-up; .5 rounds up)
        # round-then-sum:   21.94 + 22.27 = 44.21
        # sum-then-round:   21.935 + 22.265 = 44.20 (round_half_up)
        _, _, episode, clinicians, visits = (
            setup_episode_with_two_completed_sn_visits_for_mileage()
        )
        ml1 = record_mileage(
            visit=visits[0], clinician=clinicians[0], miles_driven=31.7,
        )
        ml2 = record_mileage(
            visit=visits[1], clinician=clinicians[1], miles_driven=32.3,
        )
        assert ml1["reimbursement_amount"] == pytest.approx(21.94, abs=0.001)
        assert ml2["reimbursement_amount"] == pytest.approx(22.27, abs=0.001)
        # Now close the episode and read total_mileage_reimbursement.
        close_episode_at_end_date(episode)
        claim = re_get_claim(episode["id"])
        assert claim["total_mileage_reimbursement"] == pytest.approx(
            44.21, abs=0.001,
        ), (
            "PRD §2.6: round-then-sum aggregation must yield 44.21, "
            "not 44.20 (sum-then-round)"
        )


# ===========================================================================
# PDGM final payment — LUPA branch
# ===========================================================================
class TestPDGMLupaBranch:

    def test_lupa_applied_when_completed_count_below_threshold(self, api):
        """PRD §3.7: "If the count is strictly less than the LUPA
        threshold of 5, the claim is paid per visit instead of by case
        mix. … Sum the already-rounded per-visit payments to produce
        final_payment (round-then-sum is required), and set
        lupa_applied to true."

        Claim: with 3 COMPLETED visits (3 < 5) the claim closes with
        lupa_applied=true and final_payment computed per-visit.

        # difficulty: dual_variant_calc/pdgm_payment_provisional_vs_final_lupa_divergence
        """
        _, _, episode, _, visits = (
            setup_episode_with_three_completed_visits()
        )
        # Read claim BEFORE close to capture provisional_payment.
        before_close = re_get_claim(episode["id"])
        prov = before_close["provisional_payment"]
        close_episode_at_end_date(episode)
        claim = re_get_claim(episode["id"])
        assert_pdgm_claim(claim)
        assert claim["status"] == "FINALIZED"
        assert claim["lupa_applied"] is True
        # final_payment should differ from provisional_payment under
        # the LUPA path (the divergence point of the dual-variant
        # calculation).
        assert claim["final_payment"] != pytest.approx(prov, abs=0.001), (
            "PRD §3.7: LUPA path replaces case-mix formula with per-"
            "visit rates → final_payment must differ from "
            "provisional_payment (the dual-variant divergence)"
        )
        # PRD §2.6: 2dp precision.
        assert_money_2dp(claim["final_payment"])


# ===========================================================================
# PDGM final payment — case-mix branch at boundary
# ===========================================================================
class TestPDGMCaseMixBranchAtBoundary:

    def test_lupa_not_applied_at_exactly_five_completed_visits(self, api):
        """PRD §3.7: "the LUPA visit-count threshold is 5 (strictly: a
        completed-visit count of fewer than 5 triggers LUPA)."

        Claim: with EXACTLY 5 COMPLETED visits (count == 5, not strictly
        less than 5), lupa_applied is false and the case-mix formula
        applies.

        # difficulty: boundary_precision_check/lupa_threshold_strict_less_than_boundary
        """
        from test_helpers import setup_episode_with_five_completed_visits
        _, _, episode, _, _ = (
            setup_episode_with_five_completed_visits()
        )
        close_episode_at_end_date(episode)
        claim = re_get_claim(episode["id"])
        assert claim["lupa_applied"] is False, (
            "PRD §3.7: 5 visits is NOT strictly less than 5 → LUPA must "
            "NOT apply"
        )
        assert_money_2dp(claim["final_payment"])


# ===========================================================================
# Mileage immutability — append-only (no version, no updated_at)
# ===========================================================================
class TestMileageImmutable:

    def test_mileage_log_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "MileageLog is immutable once recorded; the row
        carries id and created_at but does not carry updated_at and
        does not carry version — both fields are absent from the JSON
        response."

        Claim: a MileageLog response does NOT carry updated_at or
        version.
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        ml = record_mileage(
            visit=visit, clinician=clinician, miles_driven=10,
        )
        assert "updated_at" not in ml, (
            "PRD §2.4: MileageLog must omit updated_at"
        )
        assert "version" not in ml, (
            "PRD §2.4: MileageLog must omit version"
        )
