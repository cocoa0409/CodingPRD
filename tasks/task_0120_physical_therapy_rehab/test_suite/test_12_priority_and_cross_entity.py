"""Validation-priority pairs and cross-entity state dependencies
required by the difficulty-design index.

PRD §2.6 (validation ordering), §3.5, §3.6, §3.3.
"""
from __future__ import annotations

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    anchor_clock,
    certify_plan_of_care,
    create_authorization,
    create_dpt_therapist,
    create_episode,
    create_evaluation,
    create_patient,
    create_plan_of_care,
    create_pta_therapist,
    create_visit,
    iso_anchor_offset,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    setup_active_episode,
    setup_reeval_due_episode,
    setup_reeval_due_with_full_units,
    setup_scheduled_visit,
    start_visit,
    validate_error,
    validate_success,
)
from test_helpers import (
    create_evaluation_payload,
    create_plan_of_care_payload,
    create_visit_payload,
)


# ===========================================================================
# Priority pair: state vs business_fiscal — Difficulty design Rule 5.
# ===========================================================================
class TestPriorityStateVsBusinessFiscal:

    def test_state_vs_business_fiscal_pair(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pair
        PRD §2.6: "Once existence is established, state checks fire
        next: ERR_INVALID_STATE for any target resource not in the
        required status, followed by ERR_EPISODE_NOT_ACTIVE for
        operations that require the parent episode to be active,
        followed by ERR_REEVAL_DUE for visit-scheduling specifically.
        Clinical-capability checks come next ..., then VA-referential
        checks ..., then temporal checks ..., then quota-and-cap
        checks (ERR_POC_VISIT_LIMIT, then ERR_INSUFFICIENT_UNITS, then
        ERR_CAP_EXCEEDED)."

        Claim: POST /episodes/{id}/visits on a REEVAL_DUE episode
        where the new visit would also fail unit-coverage — PRD
        precedence says state (ERR_REEVAL_DUE) wins over fiscal
        (ERR_INSUFFICIENT_UNITS).
        """
        setup = setup_reeval_due_with_full_units()
        therapist = setup["therapist"]
        # Attempt: units_planned=4 exceeds available, AND episode is
        # in REEVAL_DUE. Both rules fire; state precedence wins.
        res = api.create_visit(
            setup["episode"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care"]["id"],
                authorization_id=setup["authorization"]["id"],
                clinician_id=therapist["id"],
                scheduled_start=iso_anchor_offset(days=40, hours=10),
                scheduled_end=iso_anchor_offset(days=40, hours=11),
                units_planned=4,
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_REEVAL_DUE")


# ===========================================================================
# Priority pair: business_safety vs business_referential — Rule 5.
# ===========================================================================
class TestPriorityBusinessSafetyVsReferential:

    def test_business_safety_vs_business_referential_pair(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_pair
        PRD §3.2: "a therapist whose credential is PTA is rejected
        with ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE."
        PRD §2.6: "Clinical-capability checks come next
        (ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE, then
        ERR_SEGREGATION_OF_DUTIES), then VA-referential checks
        (ERR_VETERAN_REFERRAL_REQUIRED, then
        ERR_VA_REFERENCE_MISMATCH)."

        Claim: a PTA-credential therapist on a VA patient calling
        /evaluations/{id}/finalize — the licensing check fires (the
        VA-referral rule does not apply to /finalize anyway) →
        ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE.
        """
        anchor_clock()
        pta = create_pta_therapist()
        patient = create_patient(insurance_type="VA")
        # No VeteranReferral registered (per difficulty recipe).
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=pta["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=pta["id"], complexity="LOW",
            functional_baseline_score=40,
            acting_therapist_id=pta["id"],
        )
        res = api.finalize_evaluation(
            evaluation["id"], make_therapist_headers(pta["id"]),
        )
        validate_error(res, "ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE")


# ===========================================================================
# Cross-entity state dependency — Difficulty design Rule 7.
# ===========================================================================
class TestVisitStartRequiresEpisodeActive:

    def test_visit_start_blocked_when_episode_in_reeval_due(self, api):
        """# difficulty: cross_entity_state_dependency/visit_start_requires_episode_active
        PRD §3.5: "Starting requires the episode to be in ACTIVE (not
        REEVAL_DUE), the bound plan to be in ACTIVE, the bound
        authorization to be in APPROVED ..."
        PRD §3.6: "Scheduling a visit while the episode is in
        REEVAL_DUE is rejected with ERR_REEVAL_DUE; visit operations
        targeted at episodes not in ACTIVE are rejected with
        ERR_EPISODE_NOT_ACTIVE."

        Claim: a SCHEDULED visit cannot be started while the parent
        episode is in REEVAL_DUE → ERR_EPISODE_NOT_ACTIVE; visit
        remains SCHEDULED.
        """
        # Build an ACTIVE episode + SCHEDULED visit, then advance the
        # clock past 30 days so the episode transitions to REEVAL_DUE.
        setup = setup_scheduled_visit(
            unit_quota=10, planned_visit_count=5,
            planned_units_per_visit=3,
            visit_offset_hours=1, visit_duration_minutes=60,
        )
        therapist = setup["therapist"]
        from test_helpers import advance_clock_days
        from test_helpers import REEVAL_DUE_DAYS
        advance_clock_days(REEVAL_DUE_DAYS + 1)
        ep = re_get_episode(setup["episode"]["id"])
        assert ep["status"] == "REEVAL_DUE"
        # Attempt /start.
        res = api.start_visit(
            setup["visit"]["id"], make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_EPISODE_NOT_ACTIVE")
        # Visit must remain SCHEDULED.
        v_after = api.get_visit(
            setup["visit"]["id"],
            TEST_USERS["clinic_admin_headers"],
        )
        v_data = validate_success(v_after, expected_status=200)
        assert v_data["status"] == "SCHEDULED"


# ===========================================================================
# Cross-entity state dependency: POC certify requires evaluation
# finalized — Difficulty design Rule 7.
# ===========================================================================
class TestPocCertifyRequiresEvaluationFinalized:

    def test_poc_certify_blocked_when_evaluation_is_draft(self, api):
        """# difficulty: cross_entity_state_dependency/poc_certify_requires_evaluation_finalized
        PRD §3.3: "Certifying a plan moves it from DRAFT through
        CERTIFIED to ACTIVE in the same request. Certification
        requires the anchoring evaluation to be in FINALIZED or
        AMENDED."

        Claim: anchoring Evaluation in DRAFT → POST
        /plan-of-cares/{id}/certify rejected with ERR_INVALID_STATE,
        and PlanOfCare.status remains DRAFT.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="COMMERCIAL")
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        # Evaluation in DRAFT (not finalized).
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
            acting_therapist_id=therapist["id"],
        )
        # PRD §3.3: A DRAFT plan can be drafted even with a DRAFT
        # evaluation — the FINALIZED/AMENDED check fires at certify.
        # (The PRD says "an evaluation_id that must be in FINALIZED
        # or AMENDED status at certification time", explicitly
        # at-certification.)
        plan = create_plan_of_care(
            episode_id=episode["id"], evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=10, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        # Authorization to cover units.
        create_authorization(
            episode_id=episode["id"], plan_of_care_id=plan["id"],
            source="COMMERCIAL_PAYER", unit_quota=60,
            valid_from=iso_date_anchor_offset(days=-1),
            valid_through=iso_date_anchor_offset(days=61),
        )
        # Attempt /certify.
        res = api.certify_plan_of_care(
            plan["id"], make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")
        # Plan remains in DRAFT.
        plan_res = api.get_plan_of_care(
            plan["id"], TEST_USERS["clinic_admin_headers"],
        )
        plan_after = validate_success(plan_res, expected_status=200)
        assert plan_after["status"] == "DRAFT"
