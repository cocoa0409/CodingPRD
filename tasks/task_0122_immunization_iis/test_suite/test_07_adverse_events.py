"""Adverse-event reporting, parallel state dimensions, VAERS
reportability and submission, segregation of duties.

PRD §3.9 (AE lifecycle and SOD), §2.6 priorities 52, 61, 90, 110.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    PROVIDER_CLINICIAN_ID_ALT,
    REVIEWING_CLINICIAN_ID,
    REVIEWING_CLINICIAN_ID_ALT,
    TEST_USERS,
    administer_dose_payload,
    advance_clock_to,
    anchor_clock,
    assert_adverse_event,
    conclude_review,
    conclude_review_payload,
    create_adverse_event,
    create_adverse_event_payload,
    create_allergy,
    create_antigen_schedule_rule,
    create_patient,
    create_provider_organization,
    create_vaccine_lot,
    create_vaccine_product,
    iso_anchor_offset,
    iso_utc,
    make_reviewing_clinician_headers,
    parse_iso,
    re_get_adverse_event,
    schedule_and_administer_dose,
    setup_administered_dose,
    setup_basic_scenario,
    setup_dose_for_ae_onset_window,
    setup_serious_ae,
    start_review,
    submit_vaers,
    submit_vaers_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §3.9 Create AE
# ===========================================================================
class TestCreateAdverseEvent:

    def test_create_ae_with_valid_dose_succeeds(self, api):
        """PRD §3.9 input shape; PRD §3.9: "A report of a suspected
        vaccine-induced adverse event is opened by either a
        ProviderClinician or a ReviewingClinician posting an
        AdverseEvent."

        Claim: a valid AE create returns 201 with default
        clinical_review_status='PENDING_REVIEW' and
        vaers_submission_status='NOT_SUBMITTED'.
        """
        administered_at = iso_anchor_offset()
        ctx = setup_administered_dose(administered_at=administered_at)
        onset_at = iso_utc(parse_iso(administered_at) + timedelta(hours=1))
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=onset_at,
                seriousness="NON_SERIOUS",
                symptom_codes=["RASH"],
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["clinical_review_status"] == "PENDING_REVIEW"
        assert data["vaers_submission_status"] == "NOT_SUBMITTED"
        assert_adverse_event(data)

    def test_create_ae_dose_patient_mismatch_rejected(self, api):
        """PRD §3.9: "patient_id, dose_id (the suspected trigger
        dose, which must belong to patient_id - mismatch yields
        ERR_DOSE_PATIENT_MISMATCH)."

        Claim: an AE create with dose_id belonging to a different
        patient yields ERR_DOSE_PATIENT_MISMATCH.
        """
        administered_at = iso_anchor_offset()
        ctx_a = setup_administered_dose(administered_at=administered_at)
        # Create another patient, not the owner of the dose.
        other_patient = create_patient()
        onset_at = iso_utc(parse_iso(administered_at) + timedelta(hours=1))
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=other_patient["id"],
                dose_id=ctx_a["dose"]["id"],
                onset_at=onset_at,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_DOSE_PATIENT_MISMATCH")


# ===========================================================================
# §3.9 onset window (difficulty design)
# ===========================================================================
class TestOnsetWindow:
    """Difficulty design: adverse_event_onset_window_open_upper_bound.
    PRD §3.9: "onset_at (the instant symptoms began, which must be at
    or after the dose's administered_at and within 42 days of it;
    outside that window yields ERR_ONSET_OUT_OF_WINDOW)."
    """

    # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
    def test_onset_exactly_at_administered_at_accepted(self, api):
        """PRD §3.9: "must be at or after the dose's administered_at."

        Claim: onset_at == administered_at -> 201 accepted.

        # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=administered_at,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_success(res, expected_status=201)

    # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
    def test_onset_exactly_42_days_after_accepted(self, api):
        """PRD §3.9: "and within 42 days of it." Inclusive 42-day
        upper bound.

        Claim: onset_at == administered_at + 42 days exactly -> 201.

        # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        onset = "2026-02-12T00:00:00.000Z"  # +42 days exactly.
        # Advance the clock so onset is <= now.
        advance_clock_to(onset)
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=onset,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_success(res, expected_status=201)

    # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
    def test_onset_past_42_days_rejected(self, api):
        """PRD §3.9: "outside that window yields ERR_ONSET_OUT_OF_WINDOW."

        Claim: onset_at == administered_at + 42 days + 1 second ->
        ERR_ONSET_OUT_OF_WINDOW.

        # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        onset = "2026-02-12T00:00:01.000Z"  # 1s past 42d.
        advance_clock_to(onset)
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=onset,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_ONSET_OUT_OF_WINDOW")

    # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
    def test_onset_before_administered_at_rejected(self, api):
        """PRD §3.9: "must be at or after the dose's administered_at...
        outside that window yields ERR_ONSET_OUT_OF_WINDOW."

        Claim: onset_at = administered_at - 1 second ->
        ERR_ONSET_OUT_OF_WINDOW.

        # difficulty: resource_temporal_overlap/adverse_event_onset_window_open_upper_bound
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        onset = "2025-12-31T23:59:59.000Z"  # 1s before admin.
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=onset,
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_ONSET_OUT_OF_WINDOW")


# ===========================================================================
# §3.9 vaers_required boundary at 24.0 hours
# Difficulty design: vaers_reportable_vs_provider_compliance_dual_perspective
# ===========================================================================
class TestVaersRequiredBoundary:
    """PRD §3.9: "The persisted vaers_required field is true if and
    only if either seriousness is SERIOUS or DEATH, or the lag in
    hours is at most 24.0. The boundary is exact and inclusive: a
    lag of exactly 24.0 hours qualifies, 24.0001 hours does not, and
    a lag of zero qualifies."
    """

    # difficulty: dual_variant_calc/vaers_reportable_vs_provider_compliance_dual_perspective
    def test_lag_exactly_24h_with_non_serious_yields_vaers_required(self, api):
        """PRD §3.9: "a lag of exactly 24.0 hours qualifies."

        Claim: NON_SERIOUS AE with lag=24.0h has vaers_required=true.

        # difficulty: dual_variant_calc/vaers_reportable_vs_provider_compliance_dual_perspective
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        onset = "2026-01-02T00:00:00.000Z"  # +24h exactly.
        advance_clock_to(onset)
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=onset,
                seriousness="NON_SERIOUS",
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["vaers_required"] is True, (
            "PRD §3.9: lag == 24.0 hours exactly must yield vaers_required=true"
        )

    # difficulty: dual_variant_calc/vaers_reportable_vs_provider_compliance_dual_perspective
    def test_lag_24_hours_plus_epsilon_yields_vaers_not_required(self, api):
        """PRD §3.9 / §2.8: "exactly 24.0 hours qualifies, 24.0001
        hours does not."

        Claim: NON_SERIOUS AE with lag slightly above 24.0h has
        vaers_required=false.

        # difficulty: dual_variant_calc/vaers_reportable_vs_provider_compliance_dual_perspective
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        # 24h + 1 second = 86401 seconds = 24.000277... hours.
        onset = "2026-01-02T00:00:01.000Z"
        advance_clock_to(onset)
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=onset,
                seriousness="NON_SERIOUS",
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["vaers_required"] is False, (
            "PRD §3.9: lag > 24.0 hours with NON_SERIOUS must yield "
            "vaers_required=false"
        )

    def test_serious_seriousness_always_yields_vaers_required(self, api):
        """PRD §3.9: "either seriousness is SERIOUS or DEATH."

        Claim: SERIOUS seriousness yields vaers_required=true even
        with a large lag.
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        onset = "2026-02-12T00:00:00.000Z"  # +42d (inclusive upper).
        advance_clock_to(onset)
        res = api.create_adverse_event(
            create_adverse_event_payload(
                patient_id=ctx["patient"]["id"],
                dose_id=ctx["dose"]["id"],
                onset_at=onset,
                seriousness="SERIOUS",
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["vaers_required"] is True


# ===========================================================================
# §3.9 Parallel dimensions (difficulty design)
# ===========================================================================
class TestParallelDimensions:
    """Difficulty design: adverse_event_parallel_dimensions.
    PRD §3.9: "An AdverseEvent carries two state dimensions that
    evolve independently on the same row."
    """

    # difficulty: non_linear_state_machine/adverse_event_parallel_dimensions
    def test_conclude_review_does_not_touch_submission_dimension(self, api):
        """PRD §3.9: "An AdverseEvent carries two state dimensions
        that evolve independently on the same row:
        clinical_review_status runs PENDING_REVIEW -> UNDER_REVIEW ->
        (CAUSALLY_RELATED | NOT_RELATED). vaers_submission_status
        runs NOT_SUBMITTED -> SUBMITTED -> (ACK_RECEIVED | REJECTED)."

        Claim: after start-review + conclude-review (NOT_RELATED), the
        vaers_submission_status is still NOT_SUBMITTED.

        # difficulty: non_linear_state_machine/adverse_event_parallel_dimensions
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Reviewer must differ from administering clinician.
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        conclude_review(
            ctx["adverse_event"]["id"],
            conclusion="NOT_RELATED",
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        ae = re_get_adverse_event(ctx["adverse_event"]["id"])
        assert ae["clinical_review_status"] == "NOT_RELATED"
        assert ae["vaers_submission_status"] == "NOT_SUBMITTED", (
            "PRD §3.9: conclude-review must NOT touch the submission "
            "axis"
        )

    # difficulty: non_linear_state_machine/adverse_event_parallel_dimensions
    def test_submit_vaers_does_not_touch_review_dimension(self, api):
        """PRD §3.9: dimensions evolve independently.

        Claim: after submit-vaers, clinical_review_status is unchanged
        at the value it had pre-submit.

        # difficulty: non_linear_state_machine/adverse_event_parallel_dimensions
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        conclude_review(
            ctx["adverse_event"]["id"],
            conclusion="NOT_RELATED",
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        # Submit to VAERS.
        submit_vaers(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        ae = re_get_adverse_event(ctx["adverse_event"]["id"])
        assert ae["clinical_review_status"] == "NOT_RELATED", (
            "PRD §3.9: submit-vaers must not touch clinical_review_status"
        )
        assert ae["vaers_submission_status"] == "SUBMITTED"


# ===========================================================================
# §3.9 SoD enforcement
# ===========================================================================
class TestSegregationOfDuties:
    """PRD §3.9: "Segregation of duties is enforced on both the
    conclude step and the VAERS submission step: the acting X-User-ID
    must not equal the administering_clinician_id recorded on the
    referenced dose. A self-review or self-submission yields
    ERR_SOD_VIOLATION."
    """

    def test_self_conclude_review_rejected(self, api):
        """PRD §3.9: "A self-review or self-submission yields
        ERR_SOD_VIOLATION."

        Claim: a reviewing clinician whose X-User-ID matches the
        dose's administering_clinician_id sees ERR_SOD_VIOLATION on
        /conclude-review.
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Start review by an independent reviewer (allowed).
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        # Now attempt to conclude using a header whose X-User-ID matches
        # the administering_clinician_id. (PRD §2.1 / §3.9 - SoD is by
        # X-User-ID, not role.)
        res = api.conclude_review(
            ctx["adverse_event"]["id"],
            conclude_review_payload(conclusion="NOT_RELATED"),
            make_reviewing_clinician_headers(PROVIDER_CLINICIAN_ID),
        )
        validate_error(res, "ERR_SOD_VIOLATION")

    def test_self_submit_vaers_rejected(self, api):
        """PRD §3.9: same SOD rule on /submit-vaers.

        Claim: /submit-vaers with X-User-ID matching the dose's
        administering_clinician_id yields ERR_SOD_VIOLATION.
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        conclude_review(
            ctx["adverse_event"]["id"],
            conclusion="NOT_RELATED",
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        res = api.submit_vaers(
            ctx["adverse_event"]["id"],
            make_reviewing_clinician_headers(PROVIDER_CLINICIAN_ID),
            submit_vaers_payload(),
        )
        validate_error(res, "ERR_SOD_VIOLATION")


# ===========================================================================
# §3.9 VAERS submission preconditions and gating
# Difficulty design: vaers_submission_depends_on_adverse_event_review_state
# ===========================================================================
class TestVaersSubmission:

    def test_submit_vaers_before_start_review_rejected(self, api):
        """PRD §3.9: "the clinical review must already be at least
        UNDER_REVIEW (specifically, clinical_review_status must be one
        of UNDER_REVIEW, CAUSALLY_RELATED, or NOT_RELATED)."

        Claim: /submit-vaers while clinical_review_status =
        PENDING_REVIEW yields ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/vaers_submission_depends_on_adverse_event_review_state
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Do NOT start review. Try to submit.
        res = api.submit_vaers(
            ctx["adverse_event"]["id"],
            TEST_USERS["reviewing_clinician_headers"],
            submit_vaers_payload(),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_submit_vaers_when_not_reportable_no_elective_rejected(self, api):
        """PRD §3.9: "either vaers_required must be true or the request
        body must carry elective set to true. Otherwise the submission
        is rejected with ERR_VAERS_NOT_REPORTABLE."

        Claim: a NON_SERIOUS AE with lag > 24h has vaers_required=false;
        /submit-vaers without elective -> ERR_VAERS_NOT_REPORTABLE.
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        onset = "2026-01-02T01:00:00.000Z"  # +25h (>24h boundary).
        advance_clock_to(onset)
        ae = create_adverse_event(
            ctx["patient"]["id"], ctx["dose"]["id"],
            onset_at=onset, seriousness="NON_SERIOUS",
            actor_role="ReviewingClinician",
        )
        assert ae["vaers_required"] is False
        start_review(ae["id"], reviewer_id=REVIEWING_CLINICIAN_ID)
        conclude_review(
            ae["id"], conclusion="NOT_RELATED",
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        res = api.submit_vaers(
            ae["id"],
            TEST_USERS["reviewing_clinician_headers"],
            submit_vaers_payload(),
        )
        validate_error(res, "ERR_VAERS_NOT_REPORTABLE")

    def test_submit_vaers_with_elective_succeeds(self, api):
        """PRD §3.9: "either vaers_required must be true or the request
        body must carry elective set to true."

        Claim: even when vaers_required=false, submit with
        elective=true succeeds (and mints vaers_submission_id).
        """
        administered_at = "2026-01-01T00:00:00.000Z"
        ctx = setup_dose_for_ae_onset_window(administered_at=administered_at)
        onset = "2026-01-02T01:00:00.000Z"  # +25h.
        advance_clock_to(onset)
        ae = create_adverse_event(
            ctx["patient"]["id"], ctx["dose"]["id"],
            onset_at=onset, seriousness="NON_SERIOUS",
            actor_role="ReviewingClinician",
        )
        assert ae["vaers_required"] is False
        start_review(ae["id"], reviewer_id=REVIEWING_CLINICIAN_ID)
        conclude_review(
            ae["id"], conclusion="NOT_RELATED",
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        res = api.submit_vaers(
            ae["id"],
            TEST_USERS["reviewing_clinician_headers"],
            submit_vaers_payload(elective=True),
        )
        data = validate_success(res)
        assert data["vaers_submission_status"] == "SUBMITTED"
        assert data["vaers_submission_id"], (
            "PRD §3.9: vaers_submission_id must be minted on submit"
        )

    def test_conclude_causally_related_does_not_auto_submit(self, api):
        """PRD §3.9: "A conclusion of CAUSALLY_RELATED does not
        automatically submit the case to VAERS. The system logs an
        audit note when vaers_required is true and submission has not
        yet occurred, but it does not auto-fire submission - submission
        is always a separate, deliberate action."

        Claim: after concluding CAUSALLY_RELATED on a vaers_required=true
        AE, vaers_submission_status stays NOT_SUBMITTED.
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        conclude_review(
            ctx["adverse_event"]["id"],
            conclusion="CAUSALLY_RELATED",
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        ae = re_get_adverse_event(ctx["adverse_event"]["id"])
        assert ae["clinical_review_status"] == "CAUSALLY_RELATED"
        assert ae["vaers_submission_status"] == "NOT_SUBMITTED", (
            "PRD §3.9: CAUSALLY_RELATED must not auto-submit"
        )
