"""Evaluation lifecycle: DRAFT → FINALIZED → AMENDED, and the
licensing / score / amend re-projection rules.

PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    EVAL_MODERATE_CENTS,
    RATE_PT_DPT_CENTS,
    TEST_DEFAULTS,
    TEST_USERS,
    amend_evaluation,
    anchor_clock,
    assert_evaluation,
    certify_plan_of_care,
    create_authorization,
    create_dpt_therapist,
    create_episode,
    create_evaluation,
    create_patient,
    create_plan_of_care,
    create_pta_therapist,
    finalize_evaluation,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    setup_evaluated_episode,
    validate_error,
    validate_success,
)
from test_helpers import create_evaluation_payload


# ===========================================================================
# Finalize — PRD §3.2: licensing, score bounds.
# ===========================================================================
class TestFinalizeEvaluation:

    def test_finalize_sets_status_to_finalized_with_timestamp(self, api):
        """PRD §3.2: "On a successful finalize, finalized_at is set to
        the current clock instant."

        Claim: after finalize, Evaluation.status == FINALIZED and
        finalized_at is a non-null ISO timestamp.
        """
        setup = setup_evaluated_episode()
        evaluation = setup["evaluation"]
        assert evaluation["status"] == "FINALIZED"
        assert evaluation.get("finalized_at"), (
            "finalized_at must be set on FINALIZED"
        )

    def test_pta_finalize_rejected_with_licensing_error(self, api):
        """PRD §3.2: "Finalizing a draft evaluation ... requires that
        the acting therapist's can_evaluate flag is true ...; a
        therapist whose credential is PTA is rejected with
        ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE."

        Claim: PTA-credential clinician attempting /finalize →
        ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE.
        """
        anchor_clock()
        # NOTE: PRD §2.1 ownership requires X-User-ID ==
        # Evaluation.clinician_id, so we must register a PTA, open the
        # episode as the PTA, create the eval with clinician_id=PTA,
        # then finalize as the PTA — and observe the licensing failure
        # rather than an auth/ownership failure.
        pta = create_pta_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=pta["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=pta["id"], complexity="MODERATE",
            functional_baseline_score=50,
            acting_therapist_id=pta["id"],
        )
        res = api.finalize_evaluation(
            evaluation["id"], make_therapist_headers(pta["id"]),
        )
        validate_error(res, "ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE")

    @pytest.mark.parametrize("score", [-1, 101, 200])
    def test_score_outside_0_100_rejected_with_validation(self, api, score):
        """PRD §3.2: "the supplied functional_baseline_score is between
        0 and 100 inclusive ... a score outside [0, 100] is rejected
        with ERR_VALIDATION."

        Claim: functional_baseline_score outside [0, 100] →
        ERR_VALIDATION.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        res = api.create_evaluation(
            episode["id"],
            create_evaluation_payload(
                evaluation_type="INITIAL",
                clinician_id=therapist["id"],
                complexity="MODERATE",
                functional_baseline_score=score,
            ),
            make_therapist_headers(therapist["id"]),
        )
        # The PRD does not commit to which side (create vs finalize)
        # surfaces the validation. PRD §3.2 says the failure is at
        # finalize. Two-reader check: A reader could lawfully accept
        # the create and reject at finalize, OR reject at create. We
        # exercise both pathways and accept either route — but assert
        # the eventual outcome is rejection somewhere.
        if 200 <= res.status_code < 300:
            # Create accepted; finalize MUST be rejected.
            evaluation = res.json()["data"]
            res2 = api.finalize_evaluation(
                evaluation["id"], make_therapist_headers(therapist["id"]),
            )
            validate_error(res2, "ERR_VALIDATION")
        else:
            validate_error(res, "ERR_VALIDATION")

    @pytest.mark.parametrize("score", [0, 100])
    def test_score_at_boundaries_accepted(self, api, score):
        """PRD §3.2: "between 0 and 100 inclusive."

        Claim: score=0 and score=100 are both accepted at finalize.
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
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=score,
            acting_therapist_id=therapist["id"],
        )
        finalized = finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        assert finalized["status"] == "FINALIZED"


# ===========================================================================
# Amend — PRD §3.2.
# ===========================================================================
class TestAmendEvaluation:

    def test_amend_by_same_clinician_succeeds(self, api):
        """PRD §3.2: "A FINALIZED evaluation can be amended by the
        same clinician_id that finalized it, provided the episode is
        not in DISCHARGED or CANCELLED; amend transitions the
        evaluation to AMENDED and may revise functional_baseline_score
        and complexity."

        Claim: same clinician calls /amend → status=AMENDED, score
        revised.
        """
        setup = setup_evaluated_episode(functional_baseline_score=50)
        therapist = setup["therapist"]
        evaluation = setup["evaluation"]
        amended = amend_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            functional_baseline_score=60,
        )
        assert amended["status"] == "AMENDED"
        assert amended["functional_baseline_score"] == 60

    def test_amend_reruns_capped_projection_on_active_plan(self, api):
        """PRD §3.2: "If a non-terminal PlanOfCare (in DRAFT, CERTIFIED,
        or ACTIVE) references the amended evaluation, the forward
        capped-cost projection re-runs on that plan, the plan's
        capped_projection_cents is rewritten, and
        Episode.kx_modifier_required is re-derived."

        Claim: with an ACTIVE plan referencing the eval, after amend
        capped_projection_cents is recomputed under the new complexity.
        """
        # Build an ACTIVE episode with eval complexity=MODERATE.
        from test_helpers import setup_active_episode
        setup = setup_active_episode(
            insurance_type="COMMERCIAL",
            complexity="MODERATE",
            planned_visit_count=20,
            planned_units_per_visit=3,
        )
        therapist = setup["therapist"]
        evaluation = setup["evaluation"]
        plan_of_care = setup["plan_of_care"]
        # PRD §3.3: projection = 20*3*4200 + 7500 = 259500.
        initial_projection = plan_of_care["capped_projection_cents"]
        assert initial_projection == 259500, (
            f"Pre-amend projection should be 259500 (MODERATE), got "
            f"{initial_projection}"
        )
        amend_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            complexity="HIGH",  # HIGH surcharge = 10500
        )
        # Re-fetch plan.
        res = api.get_plan_of_care(
            plan_of_care["id"], TEST_USERS["clinic_admin_headers"],
        )
        plan = res.json()["data"]
        # PRD §3.3: 20*3*4200 + 10500 = 262500.
        assert plan["capped_projection_cents"] == 262500, (
            f"After amend to HIGH, projection should be 262500, got "
            f"{plan['capped_projection_cents']}"
        )
