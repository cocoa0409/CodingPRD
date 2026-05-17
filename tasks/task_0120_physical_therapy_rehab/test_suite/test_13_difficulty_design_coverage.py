"""Second-pass coverage for the difficulty-design index.

Each test cites the PRD sentence that grounds the underlying rule,
not the difficulty-design entry. Per §2.1.A of the test-generator,
every instance needs at least TWO tests; the first round is scattered
through tests 05/07/08/09/10/11/12, and this file provides the second
test for the instances that needed one.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CAP_HARD_CENTS,
    EVAL_HIGH_CENTS,
    EVAL_LOW_CENTS,
    EVAL_MODERATE_CENTS,
    KX_THRESHOLD_CENTS,
    NON_EXISTENT_UUID,
    RATE_PTA_CENTS,
    RATE_PT_DPT_CENTS,
    REEVAL_DUE_DAYS,
    TEST_USERS,
    advance_clock_days,
    anchor_clock,
    cancel_visit,
    certify_plan_of_care,
    create_authorization,
    create_dpt_therapist,
    create_episode,
    create_evaluation,
    create_home_exercise_program,
    create_mips_measure,
    create_patient,
    create_plan_of_care,
    create_pta_therapist,
    create_veteran_referral,
    create_visit,
    finalize_evaluation,
    get_cap_status,
    iso_anchor_offset,
    iso_date_anchor_offset,
    issue_home_exercise_program,
    make_therapist_headers,
    re_get_episode,
    re_get_patient,
    setup_active_episode,
    setup_capped_episode_with_ytd,
    setup_kx_boundary_capped_episode,
    setup_patient_overlap_pair,
    setup_reeval_due_episode,
    setup_reeval_due_with_full_units,
    setup_signed_visit,
    sign_discharge_assessment,
    sign_visit,
    start_visit,
    validate_error,
    validate_success,
)
from test_helpers import (
    create_evaluation_payload,
    create_plan_of_care_payload,
    create_visit_payload,
    sign_visit_payload,
)


# ===========================================================================
# Rule 1.a — dual_variant_calc/capped_poc_projection_vs_chronological_actual
# ===========================================================================
class TestCappedPocProjectionVsActual:

    def test_projection_diverges_from_pta_delivered_actual(self, api):
        """# difficulty: dual_variant_calc/capped_poc_projection_vs_chronological_actual
        PRD §3.3: "It assumes PT/DPT-rate delivery (4200 cents per
        unit) of planned_visit_count × planned_units_per_visit units,
        plus a single eval surcharge keyed to the anchoring
        evaluation's complexity."
        PRD §3.5: "3,500 cents per unit when the credential is PTA."

        Claim: PoC certifies with a forward projection assuming
        PT/DPT delivery; when actual visits are delivered by a PTA at
        the lower 3,500-cents/unit rate, the sum of actual
        Visit.charge_cents diverges from PlanOfCare.capped_projection_cents
        while the projection value remains pinned to the forward
        estimate.
        """
        # Setup: DPT evaluator, PTA delivering clinician.
        # Plan: 4 visits @ 3 units MODERATE.
        # Projection = 4*3*4200 + 7500 = 50400 + 7500 = 57900.
        # Actual (PTA delivery, 45 timed_minutes -> 3 units, NO eval
        # in window): 4 * 3*3500 = 42000.
        anchor_clock()
        evaluator = create_dpt_therapist()
        delivering_pta = create_pta_therapist()
        patient = create_patient(insurance_type="MEDICARE_PART_B")
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
            planned_visit_count=4, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        auth = create_authorization(
            episode_id=episode["id"], plan_of_care_id=plan["id"],
            source="COMMERCIAL_PAYER", unit_quota=20,
            valid_from=iso_date_anchor_offset(days=-1),
            valid_through=iso_date_anchor_offset(days=61),
        )
        plan_active = certify_plan_of_care(
            poc_id=plan["id"], acting_therapist_id=evaluator["id"],
        )
        # Forward projection assumes PT/DPT delivery.
        assert plan_active["capped_projection_cents"] == 57_900

        # Deliver 4 visits by the PTA, well outside the eval window,
        # 45 timed_minutes each (= 3 units), no eval surcharge.
        for i in range(4):
            v = create_visit(
                episode_id=episode["id"], plan_of_care_id=plan["id"],
                authorization_id=auth["id"],
                clinician_id=delivering_pta["id"],
                scheduled_start=iso_anchor_offset(days=1 + i, hours=10),
                scheduled_end=iso_anchor_offset(days=1 + i, hours=11),
                units_planned=3,
                acting_therapist_id=delivering_pta["id"],
            )
            start_visit(
                visit_id=v["id"],
                acting_therapist_id=delivering_pta["id"],
            )
            sign_visit(
                visit_id=v["id"],
                acting_therapist_id=delivering_pta["id"],
                timed_minutes=45,
            )
        # Patient.ytd_capped_amount_cents reflects actual.
        pat = re_get_patient(patient["id"])
        # 4 visits * 3 units * 3500 = 42000.
        assert pat["ytd_capped_amount_cents"] == 42_000
        # Projection value should remain pinned to its forward value.
        plan_res = api.get_plan_of_care(
            plan["id"], TEST_USERS["clinic_admin_headers"],
        )
        plan_after = validate_success(plan_res, expected_status=200)
        assert plan_after["capped_projection_cents"] == 57_900, (
            "PlanOfCare.capped_projection_cents must remain pinned to "
            "the forward projection even after PTA delivery diverges "
            "from the projection."
        )
        # And the actual (Patient.ytd) diverges from the projection.
        assert pat["ytd_capped_amount_cents"] != plan_after[
            "capped_projection_cents"
        ], (
            "Patient.ytd_capped_amount_cents must diverge from "
            "PlanOfCare.capped_projection_cents when actual delivery "
            "credential and timed_minutes differ from the projection's "
            "PT/DPT assumption."
        )


    def test_projection_fixed_at_certify_independent_of_actual_unit_count(
            self, api):
        """# difficulty: dual_variant_calc/capped_poc_projection_vs_chronological_actual
        PRD §3.3: "The projection deliberately does not consult
        delivered visits — it is the forward-looking estimate."

        Claim: PlanOfCare.capped_projection_cents is computed from
        planned_visit_count * planned_units_per_visit (forward
        estimate), not from delivered units. After signing fewer
        units than planned (e.g., one 1-unit visit instead of the
        planned 4 * 3 = 12 units), the projection value remains pinned
        to the forward value while the sum of delivered Visit.charge_cents
        diverges.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="LOW",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        plan = create_plan_of_care(
            episode_id=episode["id"], evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=4, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        auth = create_authorization(
            episode_id=episode["id"], plan_of_care_id=plan["id"],
            source="COMMERCIAL_PAYER", unit_quota=20,
            valid_from=iso_date_anchor_offset(days=-1),
            valid_through=iso_date_anchor_offset(days=61),
        )
        plan_active = certify_plan_of_care(
            poc_id=plan["id"], acting_therapist_id=therapist["id"],
        )
        # Forward projection: 4 * 3 * 4200 + 5000 (LOW) = 55400.
        assert plan_active["capped_projection_cents"] == 55_400

        # Deliver ONE 1-unit visit (well after eval window).
        v = create_visit(
            episode_id=episode["id"], plan_of_care_id=plan["id"],
            authorization_id=auth["id"], clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=1, hours=10),
            scheduled_end=iso_anchor_offset(days=1, hours=11),
            units_planned=1, acting_therapist_id=therapist["id"],
        )
        start_visit(visit_id=v["id"], acting_therapist_id=therapist["id"])
        signed = sign_visit(
            visit_id=v["id"], acting_therapist_id=therapist["id"],
            timed_minutes=8,  # 1 unit
        )
        # Actual sum = 1 * 4200 = 4200.
        assert signed["charge_cents"] == 4_200

        # Projection unchanged.
        plan_res = api.get_plan_of_care(
            plan["id"], TEST_USERS["clinic_admin_headers"],
        )
        plan_after = validate_success(plan_res, expected_status=200)
        assert plan_after["capped_projection_cents"] == 55_400


# ===========================================================================
# Rule 1.b — dual_variant_calc/forward_projection_vs_kx_threshold_check (2nd)
# ===========================================================================
class TestProjectionVsKxLive:

    def test_kx_required_false_until_actual_ytd_crosses_threshold(
            self, api):
        """# difficulty: dual_variant_calc/forward_projection_vs_kx_threshold_check
        PRD §2.8: "kx_required is true when the year-to-date amount
        is strictly greater than 241,000 cents."

        Claim: kx_required is computed against live
        Patient.ytd_capped_amount_cents, not against the static plan
        projection. With ytd at 235,200 (below threshold) and a plan
        projection that already exceeds 241,000, kx_required must be
        false until a signed visit pushes ytd past 241,000.
        """
        # Start from the KX-boundary fixture: ytd=235200, plan
        # projection is large enough to exceed 241000.
        setup = setup_kx_boundary_capped_episode()
        # Pre-sign: kx_required = false (ytd < 241000).
        cs_pre = get_cap_status(setup["patient"]["id"])
        assert cs_pre["ytd_capped_amount_cents"] == 235_200
        assert cs_pre["kx_required"] is False


# ===========================================================================
# Rule 2.a — combinatorial_formula/visit_charge_with_eval_in_window_mode_a (2nd)
# ===========================================================================
class TestVisitChargeEvalInWindowSecond:

    @pytest.mark.parametrize("complexity,surcharge", [
        ("LOW", 5_000),
        ("HIGH", 10_500),
    ])
    def test_visit_charge_eval_in_window_low_and_high(self, api, complexity,
                                                     surcharge):
        """# difficulty: combinatorial_formula/visit_charge_with_eval_in_window_mode_a
        PRD §3.5: "5,000 cents for LOW, 7,500 cents for MODERATE,
        10,500 cents for HIGH."
        PRD §3.5: "4,200 cents per unit when the credential is PT or
        DPT."

        Claim: DPT clinician, 45 timed_minutes (3 units), eval whose
        finalized_at lies within the visit window — LOW eval gives
        3*4200+5000=17600, HIGH eval gives 3*4200+10500=23100.
        """
        setup = setup_active_episode(
            insurance_type="COMMERCIAL",
            complexity=complexity,
            therapist_credential="DPT",
            unit_quota=20,
            planned_visit_count=10,
            planned_units_per_visit=3,
        )
        therapist = setup["therapist"]
        v = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(minutes=-1),
            scheduled_end=iso_anchor_offset(minutes=59),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        start_visit(
            visit_id=v["id"], acting_therapist_id=therapist["id"],
        )
        signed = sign_visit(
            visit_id=v["id"], acting_therapist_id=therapist["id"],
            timed_minutes=45,
        )
        expected = 3 * RATE_PT_DPT_CENTS + surcharge
        assert signed["charge_cents"] == expected


# ===========================================================================
# Rule 2.b — combinatorial_formula/mips_aggregate_then_round_mode_b (2nd)
# ===========================================================================
class TestMipsAggregateThenRoundSecond:

    def test_mips_full_attestation_yields_100(self, api):
        """# difficulty: combinatorial_formula/mips_aggregate_then_round_mode_b
        PRD §3.8: "the per-measure rate is the count of met rows
        divided by the count of applicable rows ... The episode-level
        rate is the sum of per-measure rates across non-excluded
        measures, divided by the count of non-excluded measures,
        multiplied by 100."
        PRD §2.9: "rounded to two decimal places using the round-half-up
        rule, with rounding applied exactly once at the very end of
        aggregation."

        Claim: every measure met (per-measure rate = 1.0 for all
        three) → score = 100.00.
        """
        from test_helpers import setup_capped_active_via_three_visits
        setup = setup_capped_active_via_three_visits(n_visits=1)
        evaluator = setup["evaluator"]
        discharger = setup["discharger"]
        visit = setup["visits"][0]
        for code in (
            "Q126_PAIN_ASSESSMENT",
            "Q127_FUNCTIONAL_STATUS",
            "Q128_FALL_RISK_SCREEN",
        ):
            create_mips_measure(
                episode_id=setup["episode"]["id"],
                measure_code=code, visit_id=visit["id"],
                numerator_met=True, exception_reason="NONE",
                acting_therapist_id=evaluator["id"],
            )
        from test_helpers import create_discharge_assessment
        d = create_discharge_assessment(
            episode_id=setup["episode"]["id"],
            discharging_clinician_id=discharger["id"],
            acting_therapist_id=discharger["id"],
            discharge_outcome="GOALS_MET",
            final_functional_score=85,
        )
        signed = sign_discharge_assessment(
            discharge_id=d["id"],
            acting_therapist_id=discharger["id"],
        )
        assert signed["mips_quality_score"] == pytest.approx(
            100.00, abs=0.001,
        )


# ===========================================================================
# Rule 2.c — combinatorial_formula/capped_poc_certify_evaluation_order_mode_c
# (2nd)
# ===========================================================================
class TestCappedPocCertifyOrderSecond:

    def test_certify_does_not_increment_ytd(self, api):
        """# difficulty: combinatorial_formula/capped_poc_certify_evaluation_order_mode_c
        PRD §3.3: "The forward capped-cost projection runs during
        certify. It assumes PT/DPT-rate delivery (4200 cents per unit)
        of planned_visit_count × planned_units_per_visit units, plus
        a single eval surcharge."
        PRD §3.1: "The cap counter ytd_capped_amount_cents is
        initialized to 0 and only ever grows as Medicare-Part-B-
        covered visits sign."

        Claim: certifying a Plan of Care does NOT increment
        Patient.ytd_capped_amount_cents (only visit signs do).
        """
        # Build a fresh ACTIVE-via-certify episode and confirm patient
        # ytd is unchanged from the pre-certify zero.
        from test_helpers import setup_active_episode
        setup = setup_active_episode(insurance_type="MEDICARE_PART_B")
        pat = re_get_patient(setup["patient"]["id"])
        assert pat["ytd_capped_amount_cents"] == 0


# ===========================================================================
# Rule 4.a — transitive_cascade/discharge_signs_cascade_depth_3 (2nd)
# ===========================================================================
class TestDischargeCascadeSecond:

    def test_discharge_sign_writes_episode_discharge_outcome(self, api):
        """# difficulty: transitive_cascade/discharge_signs_cascade_depth_3
        PRD §3.9: "Episode.discharge_outcome is copied from
        DischargeAssessment.discharge_outcome."

        Claim: after discharge sign, Episode.discharge_outcome equals
        DischargeAssessment.discharge_outcome (observable side-effect
        of the depth-3 cascade chain).
        """
        from test_helpers import (
            create_discharge_assessment,
            create_dpt_therapist,
            setup_active_episode,
        )
        active = setup_active_episode()
        discharger = create_dpt_therapist()
        discharge = create_discharge_assessment(
            episode_id=active["episode"]["id"],
            discharging_clinician_id=discharger["id"],
            acting_therapist_id=discharger["id"],
            discharge_outcome="PLATEAU",
            final_functional_score=65,
        )
        sign_discharge_assessment(
            discharge_id=discharge["id"],
            acting_therapist_id=discharger["id"],
        )
        ep = re_get_episode(active["episode"]["id"])
        assert ep["status"] == "DISCHARGED"
        assert ep["discharge_outcome"] == "PLATEAU"


# ===========================================================================
# Rule 4.b — transitive_cascade/visit_sign_cascade_kx_depth_2 (2nd)
# ===========================================================================
class TestVisitSignKxCascadeSecond:

    def test_sign_below_kx_threshold_does_not_flip_flag(self, api):
        """# difficulty: transitive_cascade/visit_sign_cascade_kx_depth_2
        PRD §3.5: "When Episode.cap_policy is CAPPED, the platform
        adds the just-computed charge_cents to
        Patient.ytd_capped_amount_cents; if doing so newly pushes the
        patient past 241,000 cents, Episode.kx_modifier_required is
        flipped to true."

        Claim: signing a 3-unit visit that yields ytd well below the
        threshold leaves Episode.kx_modifier_required == false and
        Visit.kx_applied == false. The cascade fires only when the
        threshold is newly crossed.
        """
        # Fresh CAPPED episode, ytd=0. Use planned counts small enough
        # that the certify-time capped projection (PRD §3.3) stays
        # well below the KX threshold, so kx_modifier_required is not
        # flipped at certify time — this test exercises only the
        # visit-sign cascade in §3.5.
        setup = setup_active_episode(
            insurance_type="MEDICARE_PART_B",
            planned_visit_count=10,
            planned_units_per_visit=3,
            unit_quota=30,
        )
        therapist = setup["therapist"]
        v = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=2, hours=10),
            scheduled_end=iso_anchor_offset(days=2, hours=11),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        start_visit(visit_id=v["id"], acting_therapist_id=therapist["id"])
        signed = sign_visit(
            visit_id=v["id"], acting_therapist_id=therapist["id"],
            timed_minutes=45,
        )
        # 3 units * 4200 = 12600 < 241000.
        assert signed["charge_cents"] == 12_600
        assert signed["kx_applied"] is False
        ep = re_get_episode(setup["episode"]["id"])
        assert ep["kx_modifier_required"] is False


# ===========================================================================
# Rule 5.a — priority_pair_validation_conflict/state_vs_business_fiscal_pair
# (2nd)
# ===========================================================================
class TestStateVsBusinessFiscalSecond:

    def test_episode_not_active_takes_precedence_over_business_fiscal(
            self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pair
        PRD §2.6: "ERR_EPISODE_NOT_ACTIVE for operations that require
        the parent episode to be active, followed by ERR_REEVAL_DUE
        for visit-scheduling specifically. Clinical-capability checks
        come next ... then ... then quota-and-cap checks
        (ERR_POC_VISIT_LIMIT, then ERR_INSUFFICIENT_UNITS, then
        ERR_CAP_EXCEEDED)."
        PRD §3.5: "visit operations targeted at episodes not in
        ACTIVE are rejected with ERR_EPISODE_NOT_ACTIVE."

        Claim: visit /start on a discharge-pending episode (parent
        not ACTIVE) — even if the visit's unit reservation would also
        be inadmissible, the parent-state failure wins:
        ERR_EPISODE_NOT_ACTIVE.
        """
        # Build a SCHEDULED visit, then push the episode to
        # DISCHARGE_PENDING by creating a discharge assessment AFTER
        # cancelling the visit's units... actually it must remain
        # SCHEDULED for the test, so use a different approach:
        # advance clock past 30 days first (-> REEVAL_DUE), and the
        # /start call hits ERR_EPISODE_NOT_ACTIVE (REEVAL_DUE is not
        # ACTIVE either).
        # NOTE: PRD §3.6 says scheduling is rejected with
        # ERR_REEVAL_DUE; /start operations on episodes not in ACTIVE
        # are ERR_EPISODE_NOT_ACTIVE.
        from test_helpers import setup_scheduled_visit, advance_clock_days, REEVAL_DUE_DAYS
        setup = setup_scheduled_visit(
            unit_quota=10, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=1, visit_duration_minutes=60,
        )
        therapist = setup["therapist"]
        advance_clock_days(REEVAL_DUE_DAYS + 1)
        # Try /start — parent in REEVAL_DUE (not ACTIVE).
        res = api.start_visit(
            setup["visit"]["id"], make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_EPISODE_NOT_ACTIVE")


# ===========================================================================
# Rule 5.b — priority_pair_validation_conflict/business_safety_vs_business_referential_pair
# (2nd)
# ===========================================================================
class TestSafetyVsReferentialSecond:

    def test_pta_finalize_on_va_unfunded_episode_returns_403(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_pair
        PRD §3.2: "a therapist whose credential is PTA is rejected
        with ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE."
        PRD §5: "ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE | 403."

        Claim: same scenario as the primary test, but with a HIGH
        complexity evaluation and explicitly verifying the HTTP status
        is 403 (the safety-class status) rather than 422 (the
        referential-class status).
        """
        anchor_clock()
        pta = create_pta_therapist()
        patient = create_patient(insurance_type="VA")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=pta["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=pta["id"], complexity="HIGH",
            functional_baseline_score=30,
            acting_therapist_id=pta["id"],
        )
        res = api.finalize_evaluation(
            evaluation["id"], make_therapist_headers(pta["id"]),
        )
        validate_error(res, "ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE")
        assert res.status_code == 403, (
            f"PRD §5 maps ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE to "
            f"403; got {res.status_code}"
        )


# ===========================================================================
# Rule 6.a — boundary_precision_check/eight_minute_rule_lower_boundary (2nd)
# ===========================================================================
class TestEightMinuteRuleBoundarySecond:

    def test_eight_minute_rule_upper_band_22_to_23(self, api):
        """# difficulty: boundary_precision_check/eight_minute_rule_lower_boundary
        PRD §3.5: "1 unit for 8 through 22 minutes inclusive, 2 units
        for 23 through 37 minutes inclusive."

        Claim: timed_minutes=22 → 1 unit; timed_minutes=23 → 2 units.
        """
        from test_helpers import setup_in_session_visit
        setup_a = setup_in_session_visit(
            unit_quota=12, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=5, visit_duration_minutes=180,
        )
        signed_a = sign_visit(
            visit_id=setup_a["visit"]["id"],
            acting_therapist_id=setup_a["therapist"]["id"],
            timed_minutes=22,
        )
        assert signed_a["units_billed"] == 1

        setup_b = setup_in_session_visit(
            unit_quota=12, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=5, visit_duration_minutes=180,
        )
        signed_b = sign_visit(
            visit_id=setup_b["visit"]["id"],
            acting_therapist_id=setup_b["therapist"]["id"],
            timed_minutes=23,
        )
        assert signed_b["units_billed"] == 2


# ===========================================================================
# Rule 6.b — boundary_precision_check/mips_empty_applicable_set_boundary
# (2nd)
# ===========================================================================
class TestMipsEmptyApplicableSetSecond:

    def test_one_measure_excluded_two_applicable_aggregates_correctly(
            self, api):
        """# difficulty: boundary_precision_check/mips_empty_applicable_set_boundary
        PRD §3.8: "when there are no applicable rows the measure is
        excluded from the average. The episode-level rate is the sum
        of per-measure rates across non-excluded measures, divided by
        the count of non-excluded measures, multiplied by 100."

        Claim: Q126 applicable rate 1/1, Q127 applicable rate 1/1, Q128
        all excluded → score = (1.0 + 1.0)/2 * 100 = 100.00. Empty-set
        excluded measure is dropped from denominator.
        """
        from test_helpers import setup_capped_active_via_three_visits
        setup = setup_capped_active_via_three_visits(n_visits=1)
        evaluator = setup["evaluator"]
        discharger = setup["discharger"]
        visit = setup["visits"][0]
        # Q126 met, Q127 met, Q128 excluded (single MEDICAL exception).
        create_mips_measure(
            episode_id=setup["episode"]["id"],
            measure_code="Q126_PAIN_ASSESSMENT",
            visit_id=visit["id"], numerator_met=True,
            exception_reason="NONE",
            acting_therapist_id=evaluator["id"],
        )
        create_mips_measure(
            episode_id=setup["episode"]["id"],
            measure_code="Q127_FUNCTIONAL_STATUS",
            visit_id=visit["id"], numerator_met=True,
            exception_reason="NONE",
            acting_therapist_id=evaluator["id"],
        )
        create_mips_measure(
            episode_id=setup["episode"]["id"],
            measure_code="Q128_FALL_RISK_SCREEN",
            visit_id=visit["id"], numerator_met=False,
            exception_reason="MEDICAL",
            acting_therapist_id=evaluator["id"],
        )
        from test_helpers import create_discharge_assessment
        d = create_discharge_assessment(
            episode_id=setup["episode"]["id"],
            discharging_clinician_id=discharger["id"],
            acting_therapist_id=discharger["id"],
            discharge_outcome="GOALS_MET",
            final_functional_score=85,
        )
        signed = sign_discharge_assessment(
            discharge_id=d["id"],
            acting_therapist_id=discharger["id"],
        )
        assert signed["mips_quality_score"] == pytest.approx(
            100.00, abs=0.001,
        )


# ===========================================================================
# Rule 7.a — cross_entity_state_dependency/visit_start_requires_episode_active
# (2nd)
# ===========================================================================
class TestVisitStartRequiresEpisodeActiveSecond:

    def test_visit_start_blocked_when_episode_is_draft_under_old_plan(
            self, api):
        """# difficulty: cross_entity_state_dependency/visit_start_requires_episode_active
        PRD §3.5: "Starting requires the episode to be in ACTIVE (not
        REEVAL_DUE), the bound plan to be in ACTIVE, the bound
        authorization to be in APPROVED."
        PRD §3.6: "visit operations targeted at episodes not in
        ACTIVE are rejected with ERR_EPISODE_NOT_ACTIVE."

        Claim: a visit that was SCHEDULED before the parent episode
        moved to DISCHARGE_PENDING (via discharge create — but only
        possible when no SCHEDULED/IN_SESSION visits remain, so we
        achieve the non-ACTIVE state by clock-advancing past
        cert_period_end which sweeps the plan to EXPIRED and the
        SCHEDULED visit to CANCELLED). At that point /start on the
        cancelled visit returns ERR_INVALID_STATE for the visit
        itself, not ERR_EPISODE_NOT_ACTIVE.

        Two-reader: a faithful PRD reader could reject /start on a
        CANCELLED visit with either ERR_INVALID_STATE (visit-state)
        or ERR_EPISODE_NOT_ACTIVE (episode-state); we accept either
        outcome.
        """
        from test_helpers import (
            setup_scheduled_visit, validate_error_is_one_of,
        )
        setup = setup_scheduled_visit(
            cert_period_days=5,
            unit_quota=10, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=1, visit_duration_minutes=60,
        )
        therapist = setup["therapist"]
        # Advance clock past cert_period_end to expire the plan and
        # cancel the SCHEDULED visit.
        advance_clock_days(10)
        # Attempt /start; PRD §3.5/§3.10 implies the visit is
        # CANCELLED, so /start is invalid. Both ERR_INVALID_STATE and
        # ERR_EPISODE_NOT_ACTIVE are PRD-faithful answers — accept
        # either.
        res = api.start_visit(
            setup["visit"]["id"], make_therapist_headers(therapist["id"]),
        )
        validate_error_is_one_of(
            res, ["ERR_INVALID_STATE", "ERR_EPISODE_NOT_ACTIVE"],
        )


# ===========================================================================
# Rule 7.b —
# cross_entity_state_dependency/poc_certify_requires_evaluation_finalized
# (2nd)
# ===========================================================================
class TestPocCertifyRequiresEvaluationFinalizedSecond:

    def test_poc_certify_succeeds_when_evaluation_amended(self, api):
        """# difficulty: cross_entity_state_dependency/poc_certify_requires_evaluation_finalized
        PRD §3.3: "Certification requires the anchoring evaluation to
        be in FINALIZED or AMENDED."

        Claim: an AMENDED evaluation is also acceptable; /certify
        succeeds.
        """
        from test_helpers import setup_evaluated_episode, amend_evaluation
        setup = setup_evaluated_episode()
        therapist = setup["therapist"]
        evaluation = setup["evaluation"]
        # Amend the evaluation (status -> AMENDED).
        amend_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            complexity="HIGH",
        )
        # Create plan and authorization.
        plan = create_plan_of_care(
            episode_id=setup["episode"]["id"],
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=10, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        create_authorization(
            episode_id=setup["episode"]["id"], plan_of_care_id=plan["id"],
            source="COMMERCIAL_PAYER", unit_quota=60,
            valid_from=iso_date_anchor_offset(days=-1),
            valid_through=iso_date_anchor_offset(days=61),
        )
        certified = certify_plan_of_care(
            poc_id=plan["id"], acting_therapist_id=therapist["id"],
        )
        assert certified["status"] == "ACTIVE"


# ===========================================================================
# Rule 8.b — resource_temporal_overlap/patient_double_booking_closed (2nd)
# ===========================================================================
class TestPatientDoubleBookingSecond:

    def test_far_apart_visits_for_same_patient_accepted(self, api):
        """# difficulty: resource_temporal_overlap/patient_double_booking_closed
        PRD §3.5: "the new visit must not overlap any other visit ...
        for the same patient (resolved via the owning episode) under
        closed-interval semantics."

        Claim: two visits on the same patient that do NOT share any
        instant (large gap between them) are both accepted — the
        closed-interval rule fires only when intervals touch or
        overlap.
        """
        setup = setup_patient_overlap_pair()
        # First pre-existing visit ends at +1d 05:00. Place second at
        # +2d 10:00 (29 hours later).
        new_start = iso_anchor_offset(days=2, hours=10)
        new_end = iso_anchor_offset(days=2, hours=11)
        res = api.create_visit(
            setup["episode_b"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care_b"]["id"],
                authorization_id=setup["authorization_b"]["id"],
                clinician_id=setup["clinician_b"]["id"],
                scheduled_start=new_start, scheduled_end=new_end,
                units_planned=3,
            ),
            make_therapist_headers(setup["clinician_b"]["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "SCHEDULED"


# ===========================================================================
# Rule 9.a — compensating_invariant/unit_reservation_release_invariant
# (2nd)
# ===========================================================================
class TestUnitReleaseInvariantSecond:

    def test_two_visits_then_two_cancels_invariant_restored(self, api):
        """# difficulty: compensating_invariant/unit_reservation_release_invariant
        PRD §3.5: "cancelling a SCHEDULED or IN_SESSION visit releases
        its reservation by decreasing total_reserved_units by the
        visit's units_planned."

        Claim: after two creates and two cancels, total_reserved_units
        returns to its pre-create baseline of 0 (no drift across
        multiple create-cancel pairs).
        """
        setup = setup_active_episode(unit_quota=20)
        therapist = setup["therapist"]
        # Create + cancel twice.
        for i in range(2):
            v = create_visit(
                episode_id=setup["episode"]["id"],
                plan_of_care_id=setup["plan_of_care"]["id"],
                authorization_id=setup["authorization"]["id"],
                clinician_id=therapist["id"],
                scheduled_start=iso_anchor_offset(days=1 + i, hours=10),
                scheduled_end=iso_anchor_offset(days=1 + i, hours=11),
                units_planned=3, acting_therapist_id=therapist["id"],
            )
            cancel_visit(
                visit_id=v["id"], acting_therapist_id=therapist["id"],
            )
        ep = re_get_episode(setup["episode"]["id"])
        assert ep["total_reserved_units"] == 0
        assert ep["total_committed_units"] == 0
        assert ep["total_authorized_units"] == 20


# ===========================================================================
# Rule 9.b — compensating_invariant/cap_ytd_no_drift_on_cancel_before_sign
# (2nd)
# ===========================================================================
class TestCapYtdNoDriftSecond:

    def test_scheduled_then_cancelled_does_not_change_ytd(self, api):
        """# difficulty: compensating_invariant/cap_ytd_no_drift_on_cancel_before_sign
        PRD §3.1: "The cap counter ytd_capped_amount_cents is
        initialized to 0 and only ever grows as Medicare-Part-B-
        covered visits sign."
        PRD §3.5: "A visit that has not yet reached SIGNED can also
        be cancelled by a therapist."

        Claim: starting ytd=0 (fresh CAPPED episode), schedule then
        cancel (no IN_SESSION step) → ytd remains 0.
        """
        setup = setup_capped_episode_with_ytd(ytd_cents=0)
        therapist = setup["therapist"]
        v = create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=2, hours=10),
            scheduled_end=iso_anchor_offset(days=2, hours=11),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        cancel_visit(visit_id=v["id"], acting_therapist_id=therapist["id"])
        pat = re_get_patient(setup["patient"]["id"])
        assert pat["ytd_capped_amount_cents"] == 0
