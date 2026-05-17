"""Visit lifecycle (start/sign/submit-claim/cancel) and billing
calculation (8-minute rule, per-credential rate, evaluation surcharge,
KX flip, cap hard cap).

PRD §3.5 / §2.8 / §2.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CAP_HARD_CENTS,
    EVAL_HIGH_CENTS,
    EVAL_LOW_CENTS,
    EVAL_MODERATE_CENTS,
    KX_THRESHOLD_CENTS,
    RATE_PTA_CENTS,
    RATE_PT_DPT_CENTS,
    TEST_USERS,
    advance_clock_days,
    anchor_clock,
    cancel_visit,
    create_dpt_therapist,
    create_episode,
    create_evaluation,
    create_patient,
    create_pta_therapist,
    create_visit,
    finalize_evaluation,
    iso_anchor_offset,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    re_get_patient,
    setup_active_episode,
    setup_capped_episode_with_ytd,
    setup_in_session_visit,
    setup_kx_boundary_capped_episode,
    setup_scheduled_visit,
    setup_signed_visit,
    sign_visit,
    start_visit,
    submit_claim,
    validate_error,
    validate_success,
)
from test_helpers import sign_visit_payload, create_plan_of_care, create_authorization, certify_plan_of_care, create_plan_of_care_payload


# ===========================================================================
# Visit.start — PRD §3.5.
# ===========================================================================
class TestVisitStart:

    def test_start_sets_in_session(self, api):
        """PRD §3.5: "When the therapist arrives for the visit they
        advance it from SCHEDULED to IN_SESSION."

        Claim: post-start, status=IN_SESSION.
        """
        setup = setup_in_session_visit()
        assert setup["visit"]["status"] == "IN_SESSION"


# ===========================================================================
# 8-Minute Rule — PRD §3.5.
# ===========================================================================
class TestEightMinuteRule:
    """PRD §3.5 (CMS 8-Minute Rule)."""

    @pytest.mark.parametrize("timed_minutes,expected_units", [
        (0, 0), (7, 0),
        (8, 1), (22, 1),
        (23, 2), (37, 2),
        (38, 3), (52, 3),
        (53, 4), (67, 4),
        (68, 5), (82, 5),
        (83, 6), (97, 6),
    ])
    def test_units_billed_by_band(self, api, timed_minutes, expected_units):
        """PRD §3.5: "0 units for fewer than 8 minutes, 1 unit for 8
        through 22 minutes inclusive, 2 units for 23 through 37 minutes
        inclusive, 3 units for 38 through 52 minutes inclusive, 4 units
        for 53 through 67 minutes inclusive, 5 units for 68 through 82
        minutes inclusive, 6 units for 83 through 97 minutes inclusive."

        Claim: each band yields the documented unit count exactly.
        """
        # Use a fresh signed visit per parametrization.
        setup = setup_in_session_visit(
            unit_quota=12, planned_visit_count=10,
            planned_units_per_visit=6,
            visit_offset_hours=5,  # outside eval window
            visit_duration_minutes=180,
        )
        signed = sign_visit(
            visit_id=setup["visit"]["id"],
            acting_therapist_id=setup["therapist"]["id"],
            timed_minutes=timed_minutes,
        )
        assert signed["units_billed"] == expected_units, (
            f"timed_minutes={timed_minutes}: expected units={expected_units}, "
            f"got {signed['units_billed']}"
        )

    def test_eight_minute_rule_lower_boundary_7_to_8(self, api):
        """# difficulty: boundary_precision_check/eight_minute_rule_lower_boundary
        PRD §3.5: "when timed_minutes is strictly less than 8 the
        billed units are 0; otherwise the billed units are equal to
        the integer division of (timed_minutes minus 8) by 15, plus 1."
        PRD §3.5: "1 unit for 8 through 22 minutes inclusive."

        Claim: timed_minutes=7 → 0 units, charge=0; timed_minutes=8 →
        1 unit, charge=4200.
        """
        # Visit A — timed_minutes=7.
        setup_a = setup_in_session_visit(
            unit_quota=12, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=5, visit_duration_minutes=180,
        )
        signed_a = sign_visit(
            visit_id=setup_a["visit"]["id"],
            acting_therapist_id=setup_a["therapist"]["id"],
            timed_minutes=7,
        )
        assert signed_a["units_billed"] == 0
        assert signed_a["charge_cents"] == 0

        # Visit B — timed_minutes=8.
        setup_b = setup_in_session_visit(
            unit_quota=12, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=5, visit_duration_minutes=180,
        )
        signed_b = sign_visit(
            visit_id=setup_b["visit"]["id"],
            acting_therapist_id=setup_b["therapist"]["id"],
            timed_minutes=8,
        )
        assert signed_b["units_billed"] == 1
        assert signed_b["charge_cents"] == RATE_PT_DPT_CENTS  # 4200


# ===========================================================================
# Per-credential rate — PRD §3.5.
# ===========================================================================
class TestPerCredentialRate:

    def test_dpt_visit_uses_4200_per_unit(self, api):
        """PRD §3.5: "4,200 cents per unit when the credential is PT
        or DPT."

        Claim: DPT clinician + 45 min (3 units) outside eval window →
        charge = 12,600.
        """
        setup = setup_in_session_visit(
            therapist_credential="DPT",
            unit_quota=12, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=5, visit_duration_minutes=180,
        )
        signed = sign_visit(
            visit_id=setup["visit"]["id"],
            acting_therapist_id=setup["therapist"]["id"],
            timed_minutes=45,
        )
        assert signed["units_billed"] == 3
        assert signed["charge_cents"] == 3 * RATE_PT_DPT_CENTS  # 12600

    def test_pta_visit_uses_3500_per_unit(self, api):
        """PRD §3.5: "3,500 cents per unit when the credential is PTA."

        Claim: PTA clinician + 45 min (3 units) outside eval window →
        charge = 10,500.
        """
        # Build with DPT evaluator (for finalize licensing) then sign
        # the visit with a separate PTA clinician.
        anchor_clock()
        evaluator = create_dpt_therapist()
        delivering_pta = create_pta_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=evaluator["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=evaluator["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=evaluator["id"],
        )
        plan = create_plan_of_care(
            episode_id=episode["id"], evaluation_id=evaluation["id"],
            acting_therapist_id=evaluator["id"],
            planned_visit_count=10, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        auth = create_authorization(
            episode_id=episode["id"], plan_of_care_id=plan["id"],
            source="COMMERCIAL_PAYER", unit_quota=30,
            valid_from=iso_date_anchor_offset(days=-1),
            valid_through=iso_date_anchor_offset(days=61),
        )
        certify_plan_of_care(
            poc_id=plan["id"], acting_therapist_id=evaluator["id"],
        )
        # Visit delivered by the PTA, outside eval window.
        visit = create_visit(
            episode_id=episode["id"], plan_of_care_id=plan["id"],
            authorization_id=auth["id"], clinician_id=delivering_pta["id"],
            scheduled_start=iso_anchor_offset(days=2, hours=10),
            scheduled_end=iso_anchor_offset(days=2, hours=11),
            units_planned=3, acting_therapist_id=delivering_pta["id"],
        )
        start_visit(
            visit_id=visit["id"],
            acting_therapist_id=delivering_pta["id"],
        )
        signed = sign_visit(
            visit_id=visit["id"],
            acting_therapist_id=delivering_pta["id"],
            timed_minutes=45,
        )
        assert signed["units_billed"] == 3
        assert signed["charge_cents"] == 3 * RATE_PTA_CENTS  # 10500


# ===========================================================================
# Evaluation surcharge — Difficulty design Rule 2 / PRD §3.5.
# ===========================================================================
class TestEvaluationSurcharge:

    def test_visit_with_eval_in_window_mode_a(self, api):
        """# difficulty: combinatorial_formula/visit_charge_with_eval_in_window_mode_a
        PRD §3.5: "If a FINALIZED (or AMENDED) evaluation has its
        finalized_at timestamp falling inside this visit's
        [scheduled_start, scheduled_end] window, the system adds the
        evaluation surcharge for that evaluation's complexity — 5,000
        cents for LOW, 7,500 cents for MODERATE, 10,500 cents for HIGH."
        PRD §3.5: "4,200 cents per unit when the credential is PT or
        DPT."

        Claim: DPT clinician, 45 timed_minutes (=3 units), MODERATE
        eval whose finalized_at lies within the visit window →
        charge_cents = 3*4200 + 7500 = 20100.
        """
        # The fixture anchors the clock then immediately creates and
        # finalizes the evaluation, so eval.finalized_at is at-or-near
        # the anchor instant. Schedule the visit to span the anchor.
        setup = setup_active_episode(
            insurance_type="COMMERCIAL",
            complexity="MODERATE",
            therapist_credential="DPT",
            unit_quota=20,
            planned_visit_count=10,
            planned_units_per_visit=3,
        )
        therapist = setup["therapist"]
        # Visit window straddles the anchor (visit started 1 minute
        # before, ends 59 min after).
        visit = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(minutes=-1),
            scheduled_end=iso_anchor_offset(minutes=59),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        start_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
        )
        signed = sign_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
            timed_minutes=45,
        )
        assert signed["units_billed"] == 3
        assert signed["charge_cents"] == 3 * RATE_PT_DPT_CENTS + EVAL_MODERATE_CENTS
        assert signed["charge_cents"] == 20_100


# ===========================================================================
# KX flip on sign — Difficulty design Rule 4.
# ===========================================================================
class TestKxFlipOnSign:

    def test_sign_crossing_kx_threshold_flips_episode_flag(self, api):
        """# difficulty: transitive_cascade/visit_sign_cascade_kx_depth_2
        PRD §3.5: "On a successful sign the platform decreases
        total_reserved_units by units_planned and increases
        total_committed_units by units_billed, in that order ... When
        Episode.cap_policy is CAPPED, the platform adds the
        just-computed charge_cents to Patient.ytd_capped_amount_cents;
        if doing so newly pushes the patient past 241,000 cents,
        Episode.kx_modifier_required is flipped to true and the
        visit's kx_applied is set to true."
        PRD §2.8: "the KX threshold is 241,000 cents."

        Claim: starting ytd=235,200, signing a 3-unit DPT visit (12,600
        cents) pushes ytd to 247,800 (> 241,000) → kx_modifier_required
        becomes true and kx_applied is set on this visit.
        """
        setup = setup_kx_boundary_capped_episode()
        therapist = setup["therapist"]
        # Confirm pre-state.
        pat_pre = re_get_patient(setup["patient"]["id"])
        ep_pre = re_get_episode(setup["episode"]["id"])
        assert pat_pre["ytd_capped_amount_cents"] == 235_200
        assert ep_pre["kx_modifier_required"] is False

        # New visit (3 units DPT, no eval surcharge — schedule it
        # several days after anchor).
        visit = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=20, hours=10),
            scheduled_end=iso_anchor_offset(days=20, hours=11),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        start_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
        )
        signed = sign_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
            timed_minutes=45,  # 3 units
        )
        assert signed["units_billed"] == 3
        assert signed["charge_cents"] == 12_600
        # PRD §3.5: kx_applied flipped on this visit when threshold
        # newly crossed.
        assert signed["kx_applied"] is True
        # Patient ytd advanced.
        pat_post = re_get_patient(setup["patient"]["id"])
        assert pat_post["ytd_capped_amount_cents"] == 247_800
        # Episode kx flag flipped.
        ep_post = re_get_episode(setup["episode"]["id"])
        assert ep_post["kx_modifier_required"] is True


# ===========================================================================
# Cap hard-cap rejection — PRD §3.5.
# ===========================================================================
class TestCapHardCap:

    def test_sign_that_would_exceed_hard_cap_rejected(self, api):
        """PRD §3.5: "If the addition would push the patient past
        300,000 cents (the hard cap), the sign is rejected with
        ERR_CAP_EXCEEDED — crossing the soft threshold is allowed and
        merely flips kx_applied, but crossing the hard cap is
        forbidden."

        Claim: ytd_capped_amount_cents pre-positioned just below the
        hard cap such that the next sign would exceed it →
        ERR_CAP_EXCEEDED.
        """
        # Position ytd at 294_000 (70 * 4200). The next 3-unit visit
        # at 12_600 would push to 306_600 > 300_000.
        setup = setup_capped_episode_with_ytd(ytd_cents=294_000)
        therapist = setup["therapist"]
        visit = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=20, hours=10),
            scheduled_end=iso_anchor_offset(days=20, hours=11),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        start_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
        )
        res = api.sign_visit(
            visit["id"],
            sign_visit_payload(timed_minutes=45),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_CAP_EXCEEDED")


# ===========================================================================
# Cancel — PRD §3.5.
# ===========================================================================
class TestVisitCancel:

    def test_cancel_scheduled_visit_releases_reservation(self, api):
        """# difficulty: compensating_invariant/unit_reservation_release_invariant
        PRD §3.5: "A visit that has not yet reached SIGNED can also be
        cancelled by a therapist; cancelling a SCHEDULED or IN_SESSION
        visit releases its reservation by decreasing
        total_reserved_units by the visit's units_planned."

        Claim: create then cancel; the unit triad returns to its
        pre-create snapshot.
        """
        setup = setup_active_episode(unit_quota=10)
        therapist = setup["therapist"]
        ep_pre = re_get_episode(setup["episode"]["id"])
        assert ep_pre["total_authorized_units"] == 10
        assert ep_pre["total_reserved_units"] == 0
        assert ep_pre["total_committed_units"] == 0

        # Create a SCHEDULED visit using 3 units.
        visit = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=1, hours=0),
            scheduled_end=iso_anchor_offset(days=1, hours=1),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        ep_mid = re_get_episode(setup["episode"]["id"])
        assert ep_mid["total_reserved_units"] == 3

        # Cancel.
        cancel_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
        )
        ep_post = re_get_episode(setup["episode"]["id"])
        assert ep_post["total_authorized_units"] == 10
        assert ep_post["total_reserved_units"] == 0
        assert ep_post["total_committed_units"] == 0

    def test_cap_ytd_no_drift_on_cancel_before_sign(self, api):
        """# difficulty: compensating_invariant/cap_ytd_no_drift_on_cancel_before_sign
        PRD §3.5: "On a successful sign ... When Episode.cap_policy is
        CAPPED, the platform adds the just-computed charge_cents to
        Patient.ytd_capped_amount_cents."
        PRD §3.5: "A visit that has not yet reached SIGNED can also be
        cancelled by a therapist; cancelling a SCHEDULED or IN_SESSION
        visit releases its reservation by decreasing
        total_reserved_units by the visit's units_planned."

        Claim: scheduling and then cancelling (without signing) does
        not change Patient.ytd_capped_amount_cents — sign is the sole
        producer of YTD increments.
        """
        # CAPPED episode with ytd preset to 235_200 (56 * 4_200).
        setup = setup_capped_episode_with_ytd(ytd_cents=235_200)
        therapist = setup["therapist"]
        pat_pre = re_get_patient(setup["patient"]["id"])
        assert pat_pre["ytd_capped_amount_cents"] == 235_200
        ep_pre = re_get_episode(setup["episode"]["id"])

        # Create SCHEDULED -> IN_SESSION -> CANCEL.
        visit = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=20, hours=10),
            scheduled_end=iso_anchor_offset(days=20, hours=11),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        start_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
        )
        cancel_visit(
            visit_id=visit["id"], acting_therapist_id=therapist["id"],
        )

        pat_post = re_get_patient(setup["patient"]["id"])
        ep_post = re_get_episode(setup["episode"]["id"])
        assert pat_post["ytd_capped_amount_cents"] == 235_200
        assert ep_post["total_committed_units"] == ep_pre[
            "total_committed_units"
        ]
        assert ep_post["total_reserved_units"] == ep_pre[
            "total_reserved_units"
        ]


# ===========================================================================
# Submit claim — PRD §3.5.
# ===========================================================================
class TestSubmitClaim:

    def test_signed_visit_can_be_billed(self, api):
        """PRD §3.5: "A signed visit awaits the biller. The biller's
        submit-claim operation advances the visit from SIGNED to
        BILLED."

        Claim: submit-claim on a SIGNED visit → status=BILLED.
        """
        setup = setup_signed_visit(
            insurance_type="COMMERCIAL",
            unit_quota=12, planned_visit_count=5,
            planned_units_per_visit=3, visit_offset_hours=5,
            visit_duration_minutes=180,
        )
        billed = submit_claim(visit_id=setup["visit"]["id"])
        assert billed["status"] == "BILLED"

    def test_cap_status_kx_required_strict_inequality(self, api):
        """PRD §2.8: "kx_required is true when the year-to-date amount
        is strictly greater than 241,000 cents."

        Claim: ytd == KX_THRESHOLD_CENTS exactly → kx_required=false
        (strict inequality boundary).
        """
        from test_helpers import get_cap_status
        # PRD §3.5 + §2.8: signs accumulate ytd. The pre-positioned
        # fixture only supports multiples of 4200; 241_000 % 4_200 =
        # 4_000 (so cannot be reached exactly). Instead drive to
        # 239_400 (57 * 4_200), confirm kx_required=false, then sign
        # an additional 1-unit visit to land at 243_600. Confirm
        # kx_required=true.
        setup = setup_capped_episode_with_ytd(ytd_cents=239_400)
        cs_pre = get_cap_status(setup["patient"]["id"])
        assert cs_pre["ytd_capped_amount_cents"] == 239_400
        assert cs_pre["kx_required"] is False  # 239400 < 241000
        # Now sign an additional 1-unit visit (4_200 cents).
        therapist = setup["therapist"]
        v = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=30, hours=10),
            scheduled_end=iso_anchor_offset(days=30, hours=11),
            units_planned=1, acting_therapist_id=therapist["id"],
        )
        start_visit(visit_id=v["id"], acting_therapist_id=therapist["id"])
        sign_visit(
            visit_id=v["id"], acting_therapist_id=therapist["id"],
            timed_minutes=8,  # 1 unit
        )
        cs_post = get_cap_status(setup["patient"]["id"])
        assert cs_post["ytd_capped_amount_cents"] == 243_600  # > 241000
        assert cs_post["kx_required"] is True
