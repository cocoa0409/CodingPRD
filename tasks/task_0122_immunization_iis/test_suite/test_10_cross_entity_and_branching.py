"""Cross-entity state dependencies, branching certificate transitions,
parallel-dimension cascades, and VAERS webhook.

PRD §3.5 (lot status -> dose admin gate), §3.8 (cert branching with
revert), §3.9 (parallel AE dimensions), §2.10 (vaers-ack webhook).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    REVIEWING_CLINICIAN_ID,
    TEST_USERS,
    administer_dose_payload,
    advance_clock_to,
    anchor_clock,
    conclude_review,
    conclude_review_payload,
    create_antigen_schedule_rule,
    create_certificate,
    create_patient,
    create_provider_organization,
    create_vaccine_lot,
    create_vaccine_product,
    iso_anchor_offset,
    iso_utc,
    issue_certificate,
    parse_iso,
    re_get_adverse_event,
    re_get_certificate,
    re_get_dose,
    re_get_lot,
    recall_lot,
    schedule_and_administer_dose,
    schedule_dose,
    setup_administered_dose,
    setup_basic_scenario,
    setup_issued_certificate_full_coverage,
    setup_serious_ae,
    start_review,
    submit_vaers,
    submit_vaers_payload,
    vaers_ack_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Cross-entity state dependency: dose admin <- VaccineLot.status
# Difficulty design: dose_admin_depends_on_lot_status
# ===========================================================================
class TestDoseAdminDependsOnLot:
    """Difficulty design: dose_admin_depends_on_lot_status.
    PRD §3.3: "The lot must be selectable for new administration -
    its status must equal AVAILABLE."
    """

    # difficulty: cross_entity_state_dependency/dose_admin_depends_on_lot_status
    def test_administer_against_exhausted_lot_rejected(self, api):
        """PRD §3.3: "The lot must still hold inventory - doses_on_hand
        must be at least 1 (ERR_LOT_EXHAUSTED)."

        Claim: scheduling on an AVAILABLE-but-zero-stock lot (which
        becomes EXHAUSTED after the first admin) yields
        ERR_LOT_EXHAUSTED on the second admin attempt.

        # difficulty: cross_entity_state_dependency/dose_admin_depends_on_lot_status
        """
        ctx = setup_basic_scenario(doses_on_hand=1)
        # Schedule and administer the first dose - lot becomes EXHAUSTED.
        d1 = schedule_dose(
            ctx["patient"]["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        from test_helpers import administer_dose as _adm
        _adm(ctx["patient"]["id"], d1["id"], iso_anchor_offset())
        # Lot is now EXHAUSTED.
        # Schedule second dose (PRD §3.3 doesn't gate schedule on
        # doses_on_hand; only the administer step does).
        other_patient = create_patient()
        d2 = schedule_dose(
            other_patient["id"], ctx["product"]["id"], ctx["lot"]["id"],
            ctx["provider_org"]["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Now try administer; lot.doses_on_hand == 0 -> ERR_LOT_EXHAUSTED.
        res = api.administer_dose(
            other_patient["id"], d2["id"],
            administer_dose_payload(administered_at=iso_anchor_offset(seconds=60)),
            TEST_USERS["provider_clinician_headers"],
        )
        validate_error(res, "ERR_LOT_EXHAUSTED")


# ===========================================================================
# Cross-entity intra-row dependency:
# vaers_submission_status <- clinical_review_status
# Difficulty design: vaers_submission_depends_on_adverse_event_review_state
# ===========================================================================
class TestVaersSubmissionDependsOnReviewState:
    """Difficulty design:
    vaers_submission_depends_on_adverse_event_review_state.
    PRD §3.9: "the clinical review must already be at least
    UNDER_REVIEW (specifically, clinical_review_status must be one of
    UNDER_REVIEW, CAUSALLY_RELATED, or NOT_RELATED)."
    """

    # difficulty: cross_entity_state_dependency/vaers_submission_depends_on_adverse_event_review_state
    def test_submit_when_pending_review_rejected(self, api):
        """PRD §3.9: precondition for submission.

        Claim: /submit-vaers while clinical_review_status =
        PENDING_REVIEW yields ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/vaers_submission_depends_on_adverse_event_review_state
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Do NOT start review.
        res = api.submit_vaers(
            ctx["adverse_event"]["id"],
            TEST_USERS["reviewing_clinician_headers"],
            submit_vaers_payload(),
        )
        validate_error(res, "ERR_INVALID_STATE")

    # difficulty: cross_entity_state_dependency/vaers_submission_depends_on_adverse_event_review_state
    def test_submit_after_start_review_succeeds(self, api):
        """PRD §3.9: "the clinical review must already be at least
        UNDER_REVIEW (specifically, clinical_review_status must be one
        of UNDER_REVIEW, CAUSALLY_RELATED, or NOT_RELATED)."

        Claim: /submit-vaers with clinical_review_status=UNDER_REVIEW
        succeeds (transitions vaers_submission_status to SUBMITTED).

        # difficulty: cross_entity_state_dependency/vaers_submission_depends_on_adverse_event_review_state
        """
        ctx = setup_serious_ae(
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        start_review(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        data = submit_vaers(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        assert data["vaers_submission_status"] == "SUBMITTED"


# ===========================================================================
# Branching certificate state machine with revert (difficulty design)
# ===========================================================================
class TestCertificateBranchingWithRevert:
    """Difficulty design: school_certificate_branching_with_revert.
    PRD §3.5: ISSUED -> DEFICIENT on recall.
    PRD §3.3: DEFICIENT -> ISSUED on subsequent administer that
    completes coverage.
    """

    # difficulty: non_linear_state_machine/school_certificate_branching_with_revert
    def test_recall_then_revaccinate_demote_then_promote(self, api):
        """PRD §3.5 + §3.3: ISSUED -> DEFICIENT (revert via recall) ->
        ISSUED (re-advance via fresh dose).

        Claim: full branching path lands DEFICIENT after recall and
        ISSUED again after a replacement dose from a different lot.

        # difficulty: non_linear_state_machine/school_certificate_branching_with_revert
        """
        ctx = setup_issued_certificate_full_coverage()
        # Verify initial ISSUED.
        cert0 = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert0["certificate_status"] == "ISSUED"
        # Recall MMR lot.
        recall_lot(ctx["lot_mmr"]["id"], reason="CONTAMINATION")
        cert_def = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert_def["certificate_status"] == "DEFICIENT"
        assert "MMR_MEASLES" in cert_def["missing_antigens"]
        # Create a fresh MMR lot and administer a replacement.
        new_mmr_lot = create_vaccine_lot(
            ctx["product_mmr"]["id"], ctx["provider_org"]["id"],
            doses_on_hand=3,
        )
        schedule_and_administer_dose(
            ctx["patient"]["id"], ctx["product_mmr"]["id"],
            new_mmr_lot["id"], ctx["provider_org"]["id"],
            administered_at=iso_anchor_offset(seconds=60),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        cert_after = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert_after["certificate_status"] == "ISSUED", (
            "PRD §3.3 / §3.8: after revaccination, DEFICIENT cert must "
            "auto-promote back to ISSUED"
        )
        assert cert_after["missing_antigens"] == []


# ===========================================================================
# §2.10 / §4 VAERS ack webhook
# ===========================================================================
class TestVaersAckWebhook:
    """PRD §2.10 / §3.9: "The downstream acknowledgement - SUBMITTED ->
    ACK_RECEIVED or SUBMITTED -> REJECTED - is delivered by the
    test-only VAERS acknowledgement webhook, whose body carries an
    outcome of ACK or REJECT."
    """

    def test_ack_transitions_submitted_to_ack_received(self, api):
        """PRD §3.9 + §2.10: ACK outcome -> ACK_RECEIVED.

        Claim: /_events/vaers-ack with outcome=ACK transitions
        vaers_submission_status SUBMITTED -> ACK_RECEIVED.
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
        submit_vaers(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        res = api.vaers_ack(
            vaers_ack_payload(
                adverse_event_id=ctx["adverse_event"]["id"],
                outcome="ACK",
            ),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res)
        assert data["vaers_submission_status"] == "ACK_RECEIVED"

    def test_reject_transitions_submitted_to_rejected(self, api):
        """PRD §3.9 + §2.10: REJECT outcome -> REJECTED.

        Claim: /_events/vaers-ack with outcome=REJECT transitions
        vaers_submission_status SUBMITTED -> REJECTED.
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
        submit_vaers(
            ctx["adverse_event"]["id"],
            reviewer_id=REVIEWING_CLINICIAN_ID,
        )
        res = api.vaers_ack(
            vaers_ack_payload(
                adverse_event_id=ctx["adverse_event"]["id"],
                outcome="REJECT",
            ),
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res)
        assert data["vaers_submission_status"] == "REJECTED"


# ===========================================================================
# §3.7 catch-up input_set: only ADMINISTERED doses count
# ===========================================================================
class TestCatchupInputSet:
    """PRD §3.7: "Both variants run over prior AdministeredDose rows
    for the patient in the same antigen series ... only doses currently
    in ADMINISTERED state count toward 'prior doses'. SCHEDULED,
    INVALIDATED, and CANCELLED rows are explicitly excluded."
    """

    def test_invalidated_dose_not_counted_for_min_interval(self, api):
        """PRD §3.7 + §3.3: an INVALIDATED prior dose must not satisfy
        the dose 2 prerequisite (since only ADMINISTERED counts as
        prior).

        Claim: after invalidating dose 1, a second dose 1 attempt
        succeeds without ERR_MIN_INTERVAL_VIOLATION (because the
        invalidated row is excluded -- so this is really a "dose 1"
        attempt with no prior, not a "dose 2" attempt).
        """
        anchor_clock()
        provider_org = create_provider_organization()
        create_antigen_schedule_rule(
            antigen="HEPB", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product = create_vaccine_product(
            antigens=["HEPB"], min_age_days=0, max_age_days=None,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=5,
        )
        patient = create_patient(date_of_birth="2020-01-01")
        d1 = schedule_and_administer_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administered_at=iso_anchor_offset(),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Invalidate via data-error.
        from test_helpers import invalidate_dose
        invalidate_dose(patient["id"], d1["id"], "DATA_ERROR")
        # Re-administer.
        d2 = schedule_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        res = api.administer_dose(
            patient["id"], d2["id"],
            administer_dose_payload(
                administered_at=iso_anchor_offset(seconds=60),
            ),
            TEST_USERS["provider_clinician_headers"],
        )
        data = validate_success(res)
        assert data["dose_state"] == "ADMINISTERED", (
            "PRD §3.7: INVALIDATED prior dose must not count toward "
            "min-interval/prerequisite check"
        )
