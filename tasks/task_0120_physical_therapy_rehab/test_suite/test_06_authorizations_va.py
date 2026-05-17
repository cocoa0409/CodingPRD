"""Authorization create, VA referral tie-down, and VA-referral
exhaustion.

PRD §3.4.
"""
from __future__ import annotations

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    anchor_clock,
    assert_authorization,
    create_authorization,
    create_dpt_therapist,
    create_episode,
    create_evaluation,
    create_patient,
    create_plan_of_care,
    create_veteran_referral,
    create_visit,
    finalize_evaluation,
    iso_anchor_offset,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    setup_active_episode,
    setup_va_active_episode,
    setup_va_referral_partial_consumed,
    validate_error,
    validate_success,
)
from test_helpers import (
    create_authorization_payload,
    create_visit_payload,
)


# ===========================================================================
# Authorization recomputes total_authorized_units — PRD §2.7 / §3.4.
# ===========================================================================
class TestAuthorizationCounters:

    def test_authorization_increments_total_authorized_units(self, api):
        """PRD §2.7: "Episode.total_authorized_units is the sum of
        unit_quota across every Authorization on the episode whose
        status is APPROVED ... These three counters are recomputed by
        the server after every visit lifecycle transition and on every
        authorization create or revoke."

        Claim: post-creation, Episode.total_authorized_units equals
        the sum of authorized quotas.
        """
        setup = setup_active_episode(unit_quota=40)
        # Authorization with unit_quota=40 was created during fixture.
        ep = re_get_episode(setup["episode"]["id"])
        assert ep["total_authorized_units"] == 40


# ===========================================================================
# VA referral tie-down — PRD §3.4.
# ===========================================================================
class TestVeteranReferral:

    def test_first_va_visit_without_referral_authorization_rejected(
            self, api):
        """PRD §3.4: "the very first visit creation on an episode for
        a patient whose insurance_type is VA requires that an
        Authorization with source equal to VA_REFERRAL referencing an
        ACTIVE VeteranReferral already exists on the episode;
        otherwise the create is rejected with
        ERR_VETERAN_REFERRAL_REQUIRED."

        Claim: VA patient, ACTIVE episode with only a
        COMMERCIAL_PAYER-source authorization, first POST /visits →
        ERR_VETERAN_REFERRAL_REQUIRED.
        """
        # Build a VA patient ACTIVE episode but use COMMERCIAL_PAYER
        # source (not VA_REFERRAL).
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="VA")
        # Make a VeteranReferral but don't use it as the authorization
        # source.
        create_veteran_referral(patient_id=patient["id"])
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        plan = create_plan_of_care(
            episode_id=episode["id"], evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=10, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        auth = create_authorization(
            episode_id=episode["id"],
            plan_of_care_id=plan["id"],
            source="COMMERCIAL_PAYER",  # wrong source for VA patient
            unit_quota=60,
        )
        from test_helpers import certify_plan_of_care
        certify_plan_of_care(
            poc_id=plan["id"], acting_therapist_id=therapist["id"],
        )
        # First visit creation — must be rejected.
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                plan_of_care_id=plan["id"],
                authorization_id=auth["id"],
                clinician_id=therapist["id"],
                scheduled_start=iso_anchor_offset(hours=2),
                scheduled_end=iso_anchor_offset(hours=3),
                units_planned=3,
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_VETERAN_REFERRAL_REQUIRED")

    def test_va_authorization_mismatched_external_reference_rejected(
            self, api):
        """PRD §3.4: "when an authorization is created with source
        equal to VA_REFERRAL, its external_reference must equal both
        the id of an active VeteranReferral and the va_referral_id
        recorded on the patient; mismatch yields
        ERR_VA_REFERENCE_MISMATCH."

        Claim: VA_REFERRAL-sourced authorization whose
        external_reference matches neither the VeteranReferral.id nor
        the Patient.va_referral_id → ERR_VA_REFERENCE_MISMATCH.
        """
        anchor_clock()
        therapist = create_dpt_therapist()
        patient = create_patient(insurance_type="VA")
        create_veteran_referral(patient_id=patient["id"])
        episode = create_episode(
            patient_id=patient["id"],
            acting_therapist_id=therapist["id"],
        )
        evaluation = create_evaluation(
            episode_id=episode["id"], evaluation_type="INITIAL",
            clinician_id=therapist["id"], complexity="MODERATE",
            functional_baseline_score=50,
        )
        finalize_evaluation(
            evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
        )
        plan = create_plan_of_care(
            episode_id=episode["id"], evaluation_id=evaluation["id"],
            acting_therapist_id=therapist["id"],
            planned_visit_count=10, planned_units_per_visit=3,
            cert_period_start=iso_date_anchor_offset(days=0),
            cert_period_end=iso_date_anchor_offset(days=60),
        )
        res = api.create_authorization(
            episode["id"],
            create_authorization_payload(
                plan_of_care_id=plan["id"],
                source="VA_REFERRAL",
                external_reference="WRONG-REFERENCE-12345",
                unit_quota=20,
            ),
            TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res, "ERR_VA_REFERENCE_MISMATCH")

    def test_va_referral_exhaustion_blocks_second_authorization(self, api):
        """PRD §3.4: "Multiple authorizations may collectively draw
        against a single VA referral so long as the sum of their
        unit_quota values stays at or below the referral's
        authorized_units. If two concurrent authorization creates
        would jointly push that sum above the cap, exactly one
        succeeds and the other is rejected with
        ERR_VA_REFERRAL_EXHAUSTED."

        Claim: sequential authorization creates whose cumulative
        unit_quota exceeds VeteranReferral.authorized_units → the
        second is rejected with ERR_VA_REFERRAL_EXHAUSTED.
        """
        setup = setup_va_referral_partial_consumed(
            authorized_units=50, first_quota=40,
        )
        # Now attempt a second VA_REFERRAL authorization that would
        # push consumption above 50.
        res = api.create_authorization(
            setup["episode"]["id"],
            create_authorization_payload(
                plan_of_care_id=setup["plan_of_care"]["id"],
                source="VA_REFERRAL",
                external_reference=setup["veteran_referral"]["id"],
                unit_quota=20,  # 40 + 20 = 60 > 50
            ),
            TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res, "ERR_VA_REFERRAL_EXHAUSTED")
