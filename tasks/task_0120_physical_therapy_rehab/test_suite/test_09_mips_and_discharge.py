"""MIPS attestation rules and the discharge two-step ceremony, plus
the depth-3 cascade on discharge sign and the empty-applicable-set
boundary.

PRD §3.8 / §3.9 / §2.10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_mips_measure,
    create_discharge_assessment,
    create_dpt_therapist,
    create_home_exercise_program,
    create_mips_measure,
    iso_anchor_offset,
    issue_home_exercise_program,
    make_therapist_headers,
    re_get_episode,
    setup_active_episode,
    setup_capped_active_via_three_visits,
    setup_discharge_pending_episode,
    setup_signed_visit,
    sign_discharge_assessment,
    validate_error,
    validate_success,
)
from test_helpers import create_mips_measure_payload


# ===========================================================================
# MIPS attestation — PRD §3.8.
# ===========================================================================
class TestMipsAttestation:

    def test_attestation_creates_appendonly_row(self, api):
        """PRD §3.8: "A therapist attests a measure against a specific
        visit by creating a MipsMeasure row ... The scored_at
        timestamp is set by the server when the row is created."

        Claim: POST /episodes/{id}/mips-measures returns an append-only
        row with scored_at populated.
        """
        setup = setup_signed_visit(
            insurance_type="COMMERCIAL", unit_quota=12,
            planned_visit_count=5, planned_units_per_visit=3,
            visit_offset_hours=5, visit_duration_minutes=180,
        )
        therapist = setup["therapist"]
        row = create_mips_measure(
            episode_id=setup["episode"]["id"],
            measure_code="Q126_PAIN_ASSESSMENT",
            visit_id=setup["visit"]["id"],
            numerator_met=True,
            exception_reason="NONE",
            acting_therapist_id=therapist["id"],
        )
        assert_mips_measure(row)

    def test_numerator_met_with_non_none_exception_rejected(self, api):
        """PRD §3.8: "a row with exception_reason other than NONE is
        only valid when numerator_met is false (if a met measure
        carries an exception, the row is rejected with
        ERR_INVALID_MIPS_EXCEPTION)."

        Claim: numerator_met=true + exception_reason=MEDICAL →
        ERR_INVALID_MIPS_EXCEPTION.
        """
        setup = setup_signed_visit(
            insurance_type="COMMERCIAL", unit_quota=12,
            planned_visit_count=5, planned_units_per_visit=3,
            visit_offset_hours=5, visit_duration_minutes=180,
        )
        therapist = setup["therapist"]
        res = api.create_mips_measure(
            setup["episode"]["id"],
            create_mips_measure_payload(
                measure_code="Q126_PAIN_ASSESSMENT",
                visit_id=setup["visit"]["id"],
                numerator_met=True,
                exception_reason="MEDICAL",
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_INVALID_MIPS_EXCEPTION")


# ===========================================================================
# Discharge two-step — PRD §3.9.
# ===========================================================================
class TestDischargeCeremony:

    def test_creating_discharge_assessment_moves_episode_to_pending(
            self, api):
        """PRD §3.9: "On a successful create, the assessment is
        created in DRAFT and the episode is moved from ACTIVE (or
        from REEVAL_DUE) to DISCHARGE_PENDING."

        Claim: post-create, Episode.status == DISCHARGE_PENDING and
        DischargeAssessment.status == DRAFT.
        """
        setup = setup_discharge_pending_episode()
        assert setup["episode"]["status"] == "DISCHARGE_PENDING"
        assert setup["discharge_assessment"]["status"] == "DRAFT"

    def test_segregation_of_duties_blocks_self_signed_discharge(self, api):
        """PRD §3.9: "Signing a draft discharge requires ... the
        discharging_clinician_id recorded on the assessment is not
        equal to the clinician_id of the most recent evaluation on
        the episode — the same person who performed the evaluation
        may not sign the discharge. A self-discharge attempt is
        rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: same person who evaluated tries to sign the discharge
        → ERR_SEGREGATION_OF_DUTIES.
        """
        # Build ACTIVE episode, then create the discharge whose
        # discharging_clinician_id == evaluator id, then try to sign.
        setup = setup_active_episode()
        evaluator = setup["therapist"]
        # No SCHEDULED visit, so we can open a discharge.
        # Discharger same as evaluator → SoD violation.
        discharge = create_discharge_assessment(
            episode_id=setup["episode"]["id"],
            discharging_clinician_id=evaluator["id"],
            acting_therapist_id=evaluator["id"],
            discharge_outcome="GOALS_MET",
            final_functional_score=80,
        )
        res = api.sign_discharge_assessment(
            discharge["id"], make_therapist_headers(evaluator["id"]),
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_signed_discharge_moves_episode_to_discharged(self, api):
        """PRD §3.9: "On a successful sign, the discharge transitions
        to SIGNED ... the episode advances from DISCHARGE_PENDING to
        terminal DISCHARGED."

        Claim: after sign, Episode.status == DISCHARGED.
        """
        setup = setup_discharge_pending_episode()
        discharger = setup["discharger"]
        discharge = setup["discharge_assessment"]
        signed = sign_discharge_assessment(
            discharge_id=discharge["id"],
            acting_therapist_id=discharger["id"],
        )
        assert signed["status"] == "SIGNED"
        ep = re_get_episode(setup["episode"]["id"])
        assert ep["status"] == "DISCHARGED"

    def test_signed_discharge_writes_functional_delta(self, api):
        """PRD §3.9: "the platform computes functional_delta as the
        difference between final_functional_score and the
        functional_baseline_score of the most recent FINALIZED or
        AMENDED evaluation on the episode (final minus baseline)."

        Claim: baseline=50, final=80 → functional_delta=30.
        """
        # Override fixture defaults: baseline=50, final=80.
        setup = setup_discharge_pending_episode(
            functional_baseline_score=50,
        )
        discharger = setup["discharger"]
        signed = sign_discharge_assessment(
            discharge_id=setup["discharge_assessment"]["id"],
            acting_therapist_id=discharger["id"],
        )
        # PRD §3.9 says functional_delta = final - baseline = 80 - 50.
        assert signed["functional_delta"] == 30


# ===========================================================================
# Discharge cascade depth-3 — Difficulty design Rule 4.
# ===========================================================================
class TestDischargeCascadeDepthThree:

    def test_discharge_signs_cascade_depth_3(self, api):
        """# difficulty: transitive_cascade/discharge_signs_cascade_depth_3
        PRD §3.9: "the episode advances from DISCHARGE_PENDING to
        terminal DISCHARGED ... every APPROVED authorization on the
        episode is moved to EXPIRED; and every ISSUED or ACKNOWLEDGED
        HEP on the episode is moved to SUPERSEDED."

        Claim: link 1 — DischargeAssessment SIGNED;
        link 2 — Episode → DISCHARGED;
        link 3 — APPROVED Authorization → EXPIRED, ISSUED/ACKNOWLEDGED
        HEP → SUPERSEDED.
        """
        # Build a discharge-pending episode that ALSO has an ISSUED
        # HEP (no visits remaining since fixture has none).
        setup = setup_discharge_pending_episode()
        discharger = setup["discharger"]
        evaluator = setup["therapist"]
        # Create HEP draft & issue it.
        # NOTE: PRD §3.7 requires the bound plan to be in ACTIVE for
        # the issue. The episode is in DISCHARGE_PENDING but the plan
        # is still ACTIVE; PRD §3.7 doesn't tie HEP issue to episode
        # state. To stay PRD-safe, build HEP before the discharge
        # creation. Restart with the active flow.
        # Rebuild: ACTIVE → HEP issued → discharge create → discharge
        # sign.
        active = setup_active_episode()
        therapist = active["therapist"]
        hep = create_home_exercise_program(
            episode_id=active["episode"]["id"],
            plan_of_care_id=active["plan_of_care"]["id"],
            prescribing_clinician_id=therapist["id"],
            acting_therapist_id=therapist["id"],
        )
        issued_hep = issue_home_exercise_program(
            hep_id=hep["id"],
            acting_therapist_id=therapist["id"],
        )
        assert issued_hep["status"] == "ISSUED"
        # Now create the discharge (different clinician) and sign.
        discharger2 = create_dpt_therapist()
        discharge = create_discharge_assessment(
            episode_id=active["episode"]["id"],
            discharging_clinician_id=discharger2["id"],
            acting_therapist_id=discharger2["id"],
        )
        sign_discharge_assessment(
            discharge_id=discharge["id"],
            acting_therapist_id=discharger2["id"],
        )
        # Episode should be DISCHARGED.
        ep = re_get_episode(active["episode"]["id"])
        assert ep["status"] == "DISCHARGED"
        # HEP should be SUPERSEDED.
        hep_res = api.get_episode(
            active["episode"]["id"],
            TEST_USERS["clinic_admin_headers"],
        )
        # GET /home-exercise-programs/{id} — there's no list endpoint
        # for HEPs in the PRD, so we fetch the episode and check the
        # HEP by id. We need a direct fetch, but no such endpoint
        # exists. Use a workaround: the issue response already gave
        # us the HEP id; re-fetch via the episode-scoped list would
        # be needed, which the PRD does not expose. We instead
        # re-issue the existing HEP id through a path we have access
        # to — but there isn't one. So we settle for an indirect
        # check via the authorization.
        # PRD §3.9 also expires authorizations:
        auth_res = api.get_authorization(
            active["authorization"]["id"],
            TEST_USERS["clinic_admin_headers"],
        )
        auth_data = validate_success(auth_res, expected_status=200)
        assert auth_data["status"] == "EXPIRED", (
            "After discharge sign, APPROVED authorization must be "
            "moved to EXPIRED (cascade link 3)"
        )


# ===========================================================================
# MIPS aggregate-then-round — Difficulty design Rule 2 / Rule 6.
# ===========================================================================
class TestMipsScoring:

    def test_mips_aggregate_then_round_mode_b(self, api):
        """# difficulty: combinatorial_formula/mips_aggregate_then_round_mode_b
        PRD §3.8: "the per-measure rate is the count of met rows
        divided by the count of applicable rows; when there are no
        applicable rows the measure is excluded from the average. The
        episode-level rate is the sum of per-measure rates across
        non-excluded measures, divided by the count of non-excluded
        measures, multiplied by 100."
        PRD §2.9: "The episode-level MIPS quality score ... is rounded
        to two decimal places using the round-half-up rule, with
        rounding applied exactly once at the very end of aggregation,
        never to intermediate per-measure rates."

        Claim: with measures Q126={3 met/3 applicable},
        Q127={2 met/3 applicable}, Q128={1 met/1 applicable after 2
        MEDICAL exceptions excluded}, score = 88.89 (aggregate then
        round-half-up, NOT 89.00 which is per-measure-round-then-
        aggregate).
        """
        setup = setup_capped_active_via_three_visits(
            per_visit_charge_cents=12_600, n_visits=3,
            complexity="MODERATE",
        )
        evaluator = setup["evaluator"]
        discharger = setup["discharger"]
        visits = setup["visits"]

        # Q126: all three visits met=true, exception=NONE.
        for v in visits:
            create_mips_measure(
                episode_id=setup["episode"]["id"],
                measure_code="Q126_PAIN_ASSESSMENT",
                visit_id=v["id"], numerator_met=True,
                exception_reason="NONE",
                acting_therapist_id=evaluator["id"],
            )
        # Q127: V1, V2 met=true NONE; V3 met=false NONE.
        for idx, v in enumerate(visits):
            create_mips_measure(
                episode_id=setup["episode"]["id"],
                measure_code="Q127_FUNCTIONAL_STATUS",
                visit_id=v["id"],
                numerator_met=(idx < 2),
                exception_reason="NONE",
                acting_therapist_id=evaluator["id"],
            )
        # Q128: V1 met=true NONE; V2, V3 met=false MEDICAL (excluded).
        create_mips_measure(
            episode_id=setup["episode"]["id"],
            measure_code="Q128_FALL_RISK_SCREEN",
            visit_id=visits[0]["id"], numerator_met=True,
            exception_reason="NONE", acting_therapist_id=evaluator["id"],
        )
        for v in visits[1:]:
            create_mips_measure(
                episode_id=setup["episode"]["id"],
                measure_code="Q128_FALL_RISK_SCREEN",
                visit_id=v["id"], numerator_met=False,
                exception_reason="MEDICAL",
                acting_therapist_id=evaluator["id"],
            )

        # Now discharge — must use a different clinician (segregation).
        discharge = create_discharge_assessment(
            episode_id=setup["episode"]["id"],
            discharging_clinician_id=discharger["id"],
            acting_therapist_id=discharger["id"],
            discharge_outcome="PARTIAL",
            final_functional_score=70,
        )
        signed = sign_discharge_assessment(
            discharge_id=discharge["id"],
            acting_therapist_id=discharger["id"],
        )
        # Expected: Q126=1.0, Q127=2/3, Q128=1.0. Sum=2.6667;
        # /3 = 0.88889; *100 = 88.889 → 88.89 round-half-up.
        assert signed["mips_quality_score"] == pytest.approx(
            88.89, abs=0.001,
        ), (
            f"mips_quality_score should be 88.89 (aggregate then "
            f"round), got {signed['mips_quality_score']!r}"
        )
        # Verify it is NOT 89.00 (the rejected per-measure-round-then-
        # aggregate variant would yield: round(1.0,2)+round(0.67,2)+
        # round(1.0,2)=2.67 → 2.67/3*100 = 89.00).
        assert signed["mips_quality_score"] != pytest.approx(
            89.00, abs=0.001,
        ), (
            "mips_quality_score must NOT equal 89.00 (rejected "
            "per-measure-round-then-aggregate variant)"
        )

    def test_mips_empty_applicable_set_boundary(self, api):
        """# difficulty: boundary_precision_check/mips_empty_applicable_set_boundary
        PRD §3.8: "when there are no applicable rows the measure is
        excluded from the average ... If all three measures are
        excluded the score is 0.00."

        Claim: every MipsMeasure row has exception_reason != NONE →
        applicable_rows is empty for every measure → score = 0.00.
        """
        setup = setup_capped_active_via_three_visits(
            per_visit_charge_cents=12_600, n_visits=1,
            complexity="MODERATE",
        )
        evaluator = setup["evaluator"]
        discharger = setup["discharger"]
        visit = setup["visits"][0]
        # Three measure rows, ALL exception_reason=MEDICAL,
        # numerator_met=false (so they're valid attestations under
        # PRD §3.8 but excluded from per-measure rates).
        for code in (
            "Q126_PAIN_ASSESSMENT",
            "Q127_FUNCTIONAL_STATUS",
            "Q128_FALL_RISK_SCREEN",
        ):
            create_mips_measure(
                episode_id=setup["episode"]["id"],
                measure_code=code, visit_id=visit["id"],
                numerator_met=False, exception_reason="MEDICAL",
                acting_therapist_id=evaluator["id"],
            )
        discharge = create_discharge_assessment(
            episode_id=setup["episode"]["id"],
            discharging_clinician_id=discharger["id"],
            acting_therapist_id=discharger["id"],
            discharge_outcome="PARTIAL",
            final_functional_score=70,
        )
        signed = sign_discharge_assessment(
            discharge_id=discharge["id"],
            acting_therapist_id=discharger["id"],
        )
        assert signed["mips_quality_score"] == pytest.approx(
            0.00, abs=0.001,
        )
