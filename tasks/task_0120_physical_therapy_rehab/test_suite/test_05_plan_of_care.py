"""Plan of Care: drafting, certification, capped projection,
cert-window enforcement, and the KX flip on certify.

PRD §3.3 / §2.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    EVAL_HIGH_CENTS,
    EVAL_LOW_CENTS,
    EVAL_MODERATE_CENTS,
    KX_THRESHOLD_CENTS,
    RATE_PT_DPT_CENTS,
    TEST_USERS,
    anchor_clock,
    assert_plan_of_care,
    certify_plan_of_care,
    create_authorization,
    create_dpt_therapist,
    create_episode,
    create_evaluation,
    create_patient,
    create_plan_of_care,
    finalize_evaluation,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    re_get_patient,
    setup_capped_episode_with_ytd,
    setup_evaluated_episode,
    validate_error,
    validate_success,
)
from test_helpers import create_plan_of_care_payload


# ===========================================================================
# Cert window — PRD §3.3.
# ===========================================================================
class TestCertPeriodValidation:

    def test_cert_window_exactly_90_days_accepted(self, api):
        """PRD §3.3: "The window must not exceed 90 days from start to
        end."

        Claim: cert_period_end - cert_period_start == 90 days is
        accepted (boundary at the maximum).
        """
        setup = setup_evaluated_episode()
        therapist = setup["therapist"]
        episode = setup["episode"]
        evaluation = setup["evaluation"]
        plan = create_plan_of_care(
            episode_id=episode["id"],
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=90),
        )
        assert_plan_of_care(plan)

    def test_cert_window_91_days_rejected(self, api):
        """PRD §3.3: "The window must not exceed 90 days from start to
        end and cert_period_end must be strictly later than
        cert_period_start; violation is rejected with
        ERR_CERT_PERIOD_TOO_LONG."

        Claim: cert window of 91 days → ERR_CERT_PERIOD_TOO_LONG.
        """
        setup = setup_evaluated_episode()
        therapist = setup["therapist"]
        episode = setup["episode"]
        evaluation = setup["evaluation"]
        res = api.create_plan_of_care(
            episode["id"],
            create_plan_of_care_payload(
                evaluation_id=evaluation["id"],
                planned_visit_count=20,
                planned_units_per_visit=3,
                cert_period_start=iso_date_anchor_offset(days=0),
                cert_period_end=iso_date_anchor_offset(days=91),
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_CERT_PERIOD_TOO_LONG")

    def test_cert_window_end_equals_start_rejected(self, api):
        """PRD §3.3: "cert_period_end must be strictly later than
        cert_period_start; violation is rejected with
        ERR_CERT_PERIOD_TOO_LONG."

        Claim: cert_period_end == cert_period_start →
        ERR_CERT_PERIOD_TOO_LONG.
        """
        setup = setup_evaluated_episode()
        therapist = setup["therapist"]
        episode = setup["episode"]
        evaluation = setup["evaluation"]
        same = iso_date_anchor_offset(days=5)
        res = api.create_plan_of_care(
            episode["id"],
            create_plan_of_care_payload(
                evaluation_id=evaluation["id"],
                planned_visit_count=20,
                planned_units_per_visit=3,
                cert_period_start=same,
                cert_period_end=same,
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_CERT_PERIOD_TOO_LONG")


# ===========================================================================
# Capped projection — PRD §3.3.
# ===========================================================================
class TestCappedProjection:

    @pytest.mark.parametrize(
        "complexity,surcharge", [
            ("LOW", 5_000),
            ("MODERATE", 7_500),
            ("HIGH", 10_500),
        ],
    )
    def test_capped_projection_formula(self, api, complexity, surcharge):
        """PRD §3.3: "the projection in integer cents equals
        (planned_visit_count multiplied by planned_units_per_visit,
        then multiplied by 4,200) added to the surcharge dollars
        corresponding to the evaluation's complexity, with the result
        stored as capped_projection_cents on the plan."
        PRD §3.3: "5,000 cents when LOW, 7,500 cents when MODERATE,
        10,500 cents when HIGH."

        Claim: capped_projection_cents == 20*3*4200 + surcharge.
        """
        from test_helpers import setup_active_episode
        setup = setup_active_episode(
            insurance_type="COMMERCIAL",
            complexity=complexity,
            planned_visit_count=20,
            planned_units_per_visit=3,
        )
        plan_of_care = setup["plan_of_care"]
        expected = 20 * 3 * 4_200 + surcharge
        assert plan_of_care["capped_projection_cents"] == expected, (
            f"Projection should be 20*3*4200 + {surcharge} = "
            f"{expected}, got {plan_of_care['capped_projection_cents']}"
        )


# ===========================================================================
# Certify cascade — PRD §3.3.
# ===========================================================================
class TestCertifyCascade:

    def test_certify_moves_plan_from_draft_to_active(self, api):
        """PRD §3.3: "Certifying a plan moves it from DRAFT through
        CERTIFIED to ACTIVE in the same request."

        Claim: after certify, PlanOfCare.status == ACTIVE.
        """
        from test_helpers import setup_active_episode
        setup = setup_active_episode()
        assert setup["plan_of_care"]["status"] == "ACTIVE"

    def test_first_plan_certify_moves_episode_to_active(self, api):
        """PRD §3.3: "Certifying the first plan on an episode also
        cascades the episode from EVALUATED to ACTIVE."

        Claim: post-certify, Episode.status == ACTIVE.
        """
        from test_helpers import setup_active_episode
        setup = setup_active_episode()
        assert setup["episode"]["status"] == "ACTIVE"

    def test_certify_with_kx_crossing_projection_flips_episode_flag(
            self, api):
        """PRD §3.3: "If Episode.cap_policy is CAPPED and the
        just-computed capped_projection_cents added to
        Patient.ytd_capped_amount_cents would push the patient past
        241,000 cents, Episode.kx_modifier_required is set to true at
        certify time."

        Claim: starting with ytd=200000 (multiple of 4200? 200000 % 4200
        != 0 — use fixture-defined 197400 = 47*4200 + ...
        Actually 200000 isn't multiple of 4200. Use 201600 = 48 * 4200.
        201600 + 259500 (=20*3*4200 + 7500) = 461100 > 241000; →
        kx_modifier_required becomes true on certify.
        """
        # 201_600 is divisible by 4200 (48 units exactly).
        # 201_600 < 241_000 → KX not yet crossed by ytd alone.
        # 201_600 + 259_500 = 461_100 > 241_000 → certify flips KX.
        # The fixture pre-signs visits to drive ytd; that means the
        # Plan-of-Care + Authorization used at fixture time already
        # exists. We need a SECOND, fresh PoC to test the certify-flip.
        setup = setup_capped_episode_with_ytd(ytd_cents=201_600)
        therapist = setup["therapist"]
        episode = setup["episode"]
        evaluation = setup["evaluation"]
        # Create a NEW plan of care anchored to the same evaluation.
        plan2 = create_plan_of_care(
            episode_id=episode["id"],
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=20, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        # Authorization covering the cert window.
        create_authorization(
            episode_id=episode["id"],
            plan_of_care_id=plan2["id"],
            source="COMMERCIAL_PAYER", unit_quota=60,
            valid_from=iso_date_anchor_offset(days=-1),
            valid_through=iso_date_anchor_offset(days=61),
        )
        # Refresh patient + episode pre-certify.
        pat_pre = re_get_patient(setup["patient"]["id"])
        ep_pre = re_get_episode(episode["id"])
        assert pat_pre["ytd_capped_amount_cents"] == 201_600
        # PRD §2.8: KX flips on STRICTLY greater than threshold; ytd
        # alone (201_600) has not crossed 241_000.
        # Certify; the projection (259_500) added to 201_600 = 461_100
        # > 241_000 → flag flips.
        plan2_active = certify_plan_of_care(
            poc_id=plan2["id"], acting_therapist_id=therapist["id"],
        )
        ep_post = re_get_episode(episode["id"])
        assert plan2_active["status"] == "ACTIVE"
        assert plan2_active["capped_projection_cents"] == 259_500
        assert ep_post["kx_modifier_required"] is True, (
            "After certify, Episode.kx_modifier_required must flip to "
            "true because ytd + projection > KX_THRESHOLD_CENTS"
        )


# ===========================================================================
# §2.1.A Difficulty-design coverage — Rule 2 mode_c and Rule 1.
# ===========================================================================
class TestDifficultyDesignCappedProjection:
    """Difficulty design covers the order-sensitive certify behavior and
    the static-projection vs live-cap distinction. Each test cites the
    underlying PRD rule, not the difficulty-design entry."""

    def test_capped_poc_certify_evaluation_order_mode_c(self, api):
        """# difficulty: combinatorial_formula/capped_poc_certify_evaluation_order_mode_c
        PRD §3.3: "If Episode.cap_policy is CAPPED and the
        just-computed capped_projection_cents added to
        Patient.ytd_capped_amount_cents would push the patient past
        241,000 cents, Episode.kx_modifier_required is set to true at
        certify time. Certifying the first plan on an episode also
        cascades the episode from EVALUATED to ACTIVE."
        PRD §2.8: "the KX threshold is 241,000 cents."

        Claim: under one /plan-of-cares/{id}/certify call, all four
        post-conditions hold in the implementation's serialized state:
        PlanOfCare.status=ACTIVE, capped_projection_cents=259500,
        Episode.kx_modifier_required=true (because 201600 + 259500 >
        241000), Episode.status=ACTIVE.
        """
        # 201600 is the closest multiple of 4200 below the spec's
        # suggested 200000; the difficulty design's exact value is
        # informational — PRD-faithful behavior is determined by
        # whether ytd + projection > KX_THRESHOLD_CENTS, which holds
        # here.
        setup = setup_capped_episode_with_ytd(ytd_cents=201_600)
        therapist = setup["therapist"]
        episode = setup["episode"]
        evaluation = setup["evaluation"]
        # Build a fresh plan & auth to exercise the certify operation
        # cleanly.
        plan2 = create_plan_of_care(
            episode_id=episode["id"],
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=20, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        create_authorization(
            episode_id=episode["id"],
            plan_of_care_id=plan2["id"],
            source="COMMERCIAL_PAYER", unit_quota=60,
            valid_from=iso_date_anchor_offset(days=-1),
            valid_through=iso_date_anchor_offset(days=61),
        )
        plan2_active = certify_plan_of_care(
            poc_id=plan2["id"], acting_therapist_id=therapist["id"],
        )
        ep = re_get_episode(episode["id"])
        pat = re_get_patient(setup["patient"]["id"])

        assert plan2_active["status"] == "ACTIVE"
        assert plan2_active["capped_projection_cents"] == 259_500
        assert ep["kx_modifier_required"] is True
        # Episode was already ACTIVE from the first plan in the
        # fixture, so this confirms it remains ACTIVE through the
        # second-plan certification (not regressed).
        assert ep["status"] == "ACTIVE"
        # PRD §3.3 / §2.8: projection does NOT increment YTD.
        assert pat["ytd_capped_amount_cents"] == 201_600

    def test_forward_projection_vs_kx_threshold_check(self, api):
        """# difficulty: dual_variant_calc/forward_projection_vs_kx_threshold_check
        PRD §3.3: "the projection in integer cents equals
        (planned_visit_count multiplied by planned_units_per_visit,
        then multiplied by 4,200) added to the surcharge dollars
        corresponding to the evaluation's complexity, with the result
        stored as capped_projection_cents on the plan."
        PRD §2.8: "kx_required is true when the year-to-date amount is
        strictly greater than 241,000 cents."

        Claim: certifying a plan whose forward projection alone exceeds
        the KX threshold does NOT increment Patient.ytd_capped_amount_cents
        nor flip kx_required derived from ytd in the cap-status read —
        kx_required is computed against live ytd, not against the
        plan projection.
        """
        from test_helpers import setup_active_episode, get_cap_status
        setup = setup_active_episode(
            insurance_type="MEDICARE_PART_B",
            complexity="MODERATE",
            planned_visit_count=20,
            planned_units_per_visit=3,
        )
        # PRD §3.3: projection = 259500; KX = 241000. Projection alone
        # would exceed KX, BUT ytd was 0 going in and projection is not
        # added to ytd.
        plan = setup["plan_of_care"]
        assert plan["capped_projection_cents"] == 259_500
        # PRD §2.8: cap-status reflects ytd, not projection.
        cs = get_cap_status(setup["patient"]["id"])
        assert cs["ytd_capped_amount_cents"] == 0
        assert cs["kx_required"] is False
        assert cs["remaining_to_threshold_cents"] == 241_000


# ===========================================================================
# Revoke — PRD §3.3.
# ===========================================================================
class TestRevokePlan:

    def test_revoke_active_plan_moves_to_revoked(self, api):
        """PRD §3.3: "An ACTIVE plan can later be revoked by a
        clinician whose can_evaluate is true; revocation moves the
        plan to terminal REVOKED."

        Claim: POST /plan-of-cares/{id}/revoke → status=REVOKED.
        """
        from test_helpers import setup_active_episode
        setup = setup_active_episode()
        therapist = setup["therapist"]
        plan = setup["plan_of_care"]
        res = api.revoke_plan_of_care(
            plan["id"], make_therapist_headers(therapist["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REVOKED"
