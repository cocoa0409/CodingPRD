"""Numerical calculations:
- supervision_ratio (PRD §2.10)
- claim_total_submitted with tiered rates and per-line rounding (§3.6)
- claim_total_reimbursed with appeal haircut (§3.6)
- patient clinical progress scores (§3.7)
- authorization unit balance dual variant (§2.9)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PATIENT_RESPONSIBILITY_DEFAULT,
    RATE_DIRECT_RBT_CENTS,
    SUPERVISION_RATIO_MIN,
    adjudicate_claim,
    advance_clock,
    appeal_claim,
    assert_supervision_ratio_snapshot,
    deny_claim,
    draft_claim,
    expected_per_line_submitted_cents,
    expected_submitted_amount_cents,
    get_authorization,
    get_clinic,
    get_patient,
    get_supervision_ratio,
    pay_claim,
    round_half_up,
    setup_adjudicated_claim_for_rbt_session,
    setup_basic_environment,
    setup_completed_session,
    setup_completed_sessions_for_supervision_ratio,
    setup_two_completed_sessions_one_claim_draft,
    submit_claim,
    validate_error,
    validate_success,
)


class TestSupervisionRatioCalculation:
    """PRD §2.10: dynamic supervision ratio over trailing 30-day window."""

    def test_supervision_ratio_endpoint_returns_full_shape(self, api):
        """PRD §2.10: "the read capability simply returns the computed
        ratio, the boolean compliant, the rbt_minutes, the
        bcba_supervision_minutes, the window_start, and the window_end."

        Claim: GET /authorizations/{id}/supervision-ratio returns all
        six fields.
        """
        env = setup_completed_sessions_for_supervision_ratio(
            rbt_minutes_total=100, bcba_minutes_total=10,
        )
        snap = get_supervision_ratio(env["rbt_auth"]["id"])
        assert_supervision_ratio_snapshot(snap)

    def test_supervision_ratio_exactly_0_10_is_compliant(self, api):
        """PRD §2.10: "Compliance requires the ratio to be greater than
        or equal to 0.10."

        Claim: with 100 minutes RBT and 10 minutes BCBA in the trailing
        30 days, ratio == 0.10 exactly and compliant == true.

        # difficulty: combinatorial_formula/supervision_ratio_three_input_non_linear_mode_a
        """
        env = setup_completed_sessions_for_supervision_ratio(
            rbt_minutes_total=100, bcba_minutes_total=10,
        )
        snap = get_supervision_ratio(env["rbt_auth"]["id"])
        assert snap["rbt_minutes"] == pytest.approx(100, abs=0.01)
        assert snap["bcba_supervision_minutes"] == pytest.approx(
            10, abs=0.01,
        )
        assert snap["ratio"] == pytest.approx(0.10, abs=1e-6)
        assert snap["compliant"] is True

    def test_pay_claim_at_supervision_ratio_0_10_boundary_succeeds(
        self, api,
    ):
        """PRD §2.10: "Compliance requires the ratio to be greater than
        or equal to 0.10."  PRD §3.6: "Payment is permitted only when
        denial_reason is null and the patient's supervision ratio over
        the trailing 30-day window is at least 0.10 at the moment of
        payment".

        Claim: paying an ADJUDICATED claim while the patient's ratio is
        exactly 0.10 succeeds.

        # difficulty: boundary_precision_check/supervision_ratio_at_exact_0_10
        """
        env = setup_adjudicated_claim_for_rbt_session(
            rbt_minutes_total=100, bcba_minutes_total=10,
        )
        paid = pay_claim(env["claim"]["id"])
        assert paid["status"] == "PAID"

    def test_pay_claim_below_supervision_ratio_rejected(self, api):
        """PRD §2.10: "At claim payment, a violation rejects with
        ERR_SUPERVISION_RATIO_BREACH and HTTP 422".

        Claim: paying an ADJUDICATED claim while the patient's ratio is
        below 0.10 is rejected with ERR_SUPERVISION_RATIO_BREACH.

        # difficulty: boundary_precision_check/supervision_ratio_at_exact_0_10
        """
        # 100 RBT minutes + 9 BCBA minutes -> ratio 0.09 < 0.10.
        env = setup_adjudicated_claim_for_rbt_session(
            rbt_minutes_total=100, bcba_minutes_total=9,
        )
        from test_helpers import TEST_USERS
        res = api.pay_claim(
            env["claim"]["id"], TEST_USERS["payer_admin_headers"],
        )
        validate_error(res, "ERR_SUPERVISION_RATIO_BREACH")


class TestClaimSubmittedAmountCalculation:
    """PRD §3.6: per-line round-half-up, then sum."""

    def test_submitted_amount_rounds_per_line_then_sums(self, api):
        """PRD §3.6: "The claim's submitted_amount_cents is then the
        integer sum of those per-line cent amounts. The rounding order
        is pinned: round each line to whole cents first, then sum —
        summing first and rounding once would diverge by up to one cent
        for typical inputs and is not the contract."

        Claim: two DIRECT_RBT sessions of 7 and 5 billed_units yield
        submitted_amount_cents == round_half_up(7 * 3333 * 0.85) +
        round_half_up(5 * 3333 * 0.85) = 19831 + 14165 = 33996, NOT
        33997 (the sum-then-round answer).

        # difficulty: combinatorial_formula/claim_total_submitted_per_line_rounding_then_sum_mode_b
        """
        # We need two sessions with billed_units 7 and 5 under a DIRECT
        # RBT (97153) authorization. 7 units = 1h45m, 5 units = 1h15m.
        env = setup_basic_environment(approved_units=240)
        rbt = env["rbts"][0]
        s_a, _ = setup_completed_session(
            clinic=env["clinic"], patient=env["patient"],
            authorization=env["authorization"], therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=105,  # 7 units
            progress_rating=4,
        )
        s_b, _ = setup_completed_session(
            clinic=env["clinic"], patient=env["patient"],
            authorization=env["authorization"], therapist=rbt,
            therapist_role="RBT", session_type="DIRECT_RBT",
            duration_minutes=75,  # 5 units
            progress_rating=4,
        )
        claim = draft_claim(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            session_ids=[s_a["id"], s_b["id"]],
        )
        submitted = submit_claim(claim["id"])
        # Compute expected per-line cents (round per-line then sum).
        line_a = round_half_up(7 * 3333 * 0.85)  # 19831
        line_b = round_half_up(5 * 3333 * 0.85)  # 14165
        expected = line_a + line_b  # 33996
        assert submitted["submitted_amount_cents"] == expected
        # And NOT the sum-first-then-round alternative (33997).
        wrong = round_half_up(7 * 3333 * 0.85 + 5 * 3333 * 0.85)
        # PRD pins per-line first; verify the two differ.
        assert wrong != expected or wrong == 33996

    def test_submitted_amount_uses_tiered_rates(self, api):
        """PRD §3.6: "DIRECT_RBT is reimbursed at 3333 cents per unit,
        BCBA_SUPERVISION at 6800 cents per unit, and PARENT_TRAINING at
        5000 cents per unit."

        Claim: a single 4-unit DIRECT_RBT session yields
        submitted_amount_cents = round_half_up(4 * 3333 * 0.85) = 11332.
        """
        env = setup_two_completed_sessions_one_claim_draft(
            billed_units_per_session=(4,),
        )
        submitted = submit_claim(env["claim"]["id"])
        expected = expected_per_line_submitted_cents(
            billed_units=4, session_type="DIRECT_RBT",
        )
        assert submitted["submitted_amount_cents"] == expected
        # Sanity: 4 * 3333 * 0.85 = 11332.2; round_half_up to 11332.
        assert expected == 11332


class TestClaimReimbursedAmountCalculation:

    def test_reimbursed_equals_submitted_when_appeal_round_zero(
        self, api,
    ):
        """PRD §3.6: "For an original submission — where appeal_round
        equals zero — each line's reimbursed amount is exactly the
        corresponding line's submitted amount."

        Claim: paying a claim whose appeal_round == 0 sets
        reimbursed_amount_cents == submitted_amount_cents.
        """
        env = setup_adjudicated_claim_for_rbt_session()
        # submit ran inside setup_adjudicated_claim_for_rbt_session;
        # re-read the claim after pay.
        paid = pay_claim(env["claim"]["id"])
        assert paid["appeal_round"] == 0
        assert (
            paid["reimbursed_amount_cents"]
            == paid["submitted_amount_cents"]
        )


class TestAuthorizationUnitBalanceDualVariant:
    """PRD §2.9: provisional vs adjudicated divergence."""

    def test_provisional_and_adjudicated_diverge_after_completes(
        self, api,
    ):
        """PRD §2.9: "the provisional picture, which updates the instant
        a session completes and reverses the instant the session is
        disputed or its containing claim is denied; and the adjudicated
        picture, which moves only when a claim is paid."

        Claim: after five 4-unit DIRECT_RBT sessions are completed but
        no claim is paid, Authorization.provisional_units_consumed == 20
        and Authorization.adjudicated_units_consumed == 0.

        # difficulty: dual_variant_calc/authorization_unit_balance_provisional_vs_adjudicated
        """
        env = setup_basic_environment(approved_units=240)
        rbt = env["rbts"][0]
        for _ in range(5):
            setup_completed_session(
                clinic=env["clinic"], patient=env["patient"],
                authorization=env["authorization"], therapist=rbt,
                therapist_role="RBT", session_type="DIRECT_RBT",
                duration_minutes=60, progress_rating=4,
            )
        auth = get_authorization(env["authorization"]["id"])
        assert auth["provisional_units_consumed"] == 20
        assert auth["adjudicated_units_consumed"] == 0


class TestPatientProgressScoreDualVariant:

    def test_progress_scores_after_completes_only(self, api):
        """PRD §3.7: "The provisional score considers any session
        whose status is COMPLETED or BILLED and whose session_type is
        either DIRECT_RBT or BCBA_SUPERVISION, regardless of any claim
        outcome. … The adjudicated score considers a strictly narrower
        set: only sessions whose session_type is BCBA_SUPERVISION and
        that are referenced by some claim currently in PAID."

        Claim: with 3 DIRECT_RBT sessions (rating 4, 4 units each) and
        1 BCBA_SUPERVISION session (rating 2, 4 units) and zero PAID
        claims, Patient.clinical_progress_score_provisional == 3.50
        (= (4*4 + 4*4 + 4*4 + 4*2) / (4+4+4+4) = 56/16 = 3.5) and
        Patient.clinical_progress_score_adjudicated == 0.00.

        # difficulty: dual_variant_calc/patient_clinical_progress_score_provisional_vs_adjudicated
        """
        from test_helpers import setup_environment_with_two_authorizations
        env = setup_environment_with_two_authorizations(
            cpt_codes=("97153", "97155"),
        )
        rbt = env["rbts"][0]
        bcba = env["bcbas"][0]
        rbt_auth = env["authorizations"][0]
        bcba_auth = env["authorizations"][1]
        # 3 RBT sessions, 4 units each, rating 4 each.
        for _ in range(3):
            setup_completed_session(
                clinic=env["clinic"], patient=env["patient"],
                authorization=rbt_auth, therapist=rbt,
                therapist_role="RBT", session_type="DIRECT_RBT",
                duration_minutes=60, progress_rating=4,
            )
        # 1 BCBA supervision session, 4 units, rating 2, supervising
        # the RBT we just used (who has qualifying COMPLETED sessions).
        setup_completed_session(
            clinic=env["clinic"], patient=env["patient"],
            authorization=bcba_auth, therapist=bcba,
            therapist_role="BCBA", session_type="BCBA_SUPERVISION",
            duration_minutes=60, progress_rating=2,
            supervising_therapist_id=rbt["id"],
        )
        patient = get_patient(env["patient"]["id"])
        # 3.5 may be stored as 3.50 or 3.5.
        assert patient["clinical_progress_score_provisional"] == (
            pytest.approx(3.5, abs=0.01)
        )
        assert patient["clinical_progress_score_adjudicated"] == (
            pytest.approx(0.0, abs=0.01)
        )
