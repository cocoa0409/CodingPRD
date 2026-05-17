"""Lot recall three-hop cascade and data-error invalidation cascade.

PRD §3.5 (recall cascade hops 1-3), §3.3 (data-error invalidation),
§3.8 (school certificate auto-demote / auto-promote), §3.9 (AE
clinical_review auto-advance).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    TEST_USERS,
    administer_dose,
    advance_clock_to,
    anchor_clock,
    create_adverse_event,
    create_allergy,
    create_antigen_schedule_rule,
    create_certificate,
    create_patient,
    create_provider_organization,
    create_vaccine_lot,
    create_vaccine_product,
    invalidate_dose,
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
    setup_hepb_single_required_and_dose,
    setup_issued_certificate_full_coverage,
    setup_mmr_lot_recall_with_ae_pending,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.5 Hop 1 - recall invalidates ADMINISTERED doses
# ===========================================================================
class TestRecallHop1:

    # difficulty: transitive_cascade/recall_to_dose_to_certificate_to_review_chain
    def test_recall_invalidates_administered_dose_from_that_lot(self, api):
        """PRD §3.5: "Every AdministeredDose whose lot_id matches the
        recalled lot and whose dose_state is ADMINISTERED is
        transitioned to INVALIDATED with invalidation_reason recorded
        as LOT_RECALL."

        Claim: after /recall on a lot with an administered dose, the
        dose advances to INVALIDATED with invalidation_reason ==
        'LOT_RECALL'.

        # difficulty: transitive_cascade/recall_to_dose_to_certificate_to_review_chain
        """
        ctx = setup_administered_dose()
        recall_lot(ctx["lot"]["id"], reason="MANUFACTURER_DEFECT")
        dose_after = re_get_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
        )
        assert dose_after["dose_state"] == "INVALIDATED"
        assert dose_after["invalidation_reason"] == "LOT_RECALL", (
            "PRD §3.5: invalidation_reason must be 'LOT_RECALL' after recall"
        )

    def test_recall_restores_inventory_when_reason_not_expired(self, api):
        """PRD §3.5: "the system then restores doses_on_hand by one
        only if the recall_reason is anything other than EXPIRED and
        the lot's status was AVAILABLE immediately before the recall."

        Claim: recall with reason=MANUFACTURER_DEFECT on an AVAILABLE
        lot with one ADMINISTERED dose restores doses_on_hand by 1.
        """
        # Start with doses_on_hand=2, administer once -> 1; recall ->
        # invalidate dose AND restore by 1 -> 2 again. (Lot becomes
        # RECALLED, but doses_on_hand reflects the restored count.)
        ctx = setup_administered_dose(doses_on_hand=2)
        before = re_get_lot(ctx["lot"]["id"])
        assert before["doses_on_hand"] == 1
        recall_lot(ctx["lot"]["id"], reason="MANUFACTURER_DEFECT")
        after = re_get_lot(ctx["lot"]["id"])
        assert after["status"] == "RECALLED"
        assert after["doses_on_hand"] == 2, (
            "PRD §3.5: non-EXPIRED recall on AVAILABLE lot restores "
            "doses_on_hand by 1 per invalidated dose"
        )

    def test_recall_with_reason_expired_does_not_restore_inventory(self, api):
        """PRD §3.5: "An EXPIRED recall does not restore inventory
        (the doses are physically unusable)."

        Claim: recall with reason=EXPIRED leaves doses_on_hand unchanged.
        """
        ctx = setup_administered_dose(doses_on_hand=2)
        before = re_get_lot(ctx["lot"]["id"])
        assert before["doses_on_hand"] == 1
        recall_lot(ctx["lot"]["id"], reason="EXPIRED")
        after = re_get_lot(ctx["lot"]["id"])
        assert after["status"] == "RECALLED"
        assert after["doses_on_hand"] == 1, (
            "PRD §3.5: EXPIRED recall must NOT restore doses_on_hand"
        )


# ===========================================================================
# §3.5 Hop 2 - certificate auto-demote on recall
# ===========================================================================
class TestRecallHop2:

    # difficulty: non_linear_state_machine/school_certificate_branching_with_revert
    # difficulty: compensating_invariant/school_coverage_set_conservation_under_recall_then_revaccinate
    def test_recall_demotes_issued_certificate_to_deficient(self, api):
        """PRD §3.5: "For every SchoolEnrollmentCertificate whose
        patient_id matches an affected patient and whose
        certificate_status is ISSUED or EXEMPTION_GRANTED, the system
        reruns the school coverage evaluation. If the recompute
        reveals at least one uncovered antigen, the certificate's
        certificate_status is auto-demoted to DEFICIENT and
        missing_antigens is updated with the alphabetically sorted
        list."

        Claim: after recalling the MMR lot, the previously ISSUED
        certificate is auto-demoted to DEFICIENT and
        'MMR_MEASLES' appears in missing_antigens.

        # difficulty: non_linear_state_machine/school_certificate_branching_with_revert
        """
        ctx = setup_issued_certificate_full_coverage()
        cert_before = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert_before["certificate_status"] == "ISSUED"
        recall_lot(ctx["lot_mmr"]["id"], reason="CONTAMINATION")
        cert_after = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert_after["certificate_status"] == "DEFICIENT", (
            f"PRD §3.5: ISSUED certificate must be demoted to DEFICIENT "
            f"after recall, got {cert_after['certificate_status']!r}"
        )
        assert "MMR_MEASLES" in cert_after["missing_antigens"], (
            f"PRD §3.5: missing_antigens must include MMR_MEASLES, "
            f"got {cert_after['missing_antigens']!r}"
        )


# ===========================================================================
# §3.5 Hop 3 - parallel adverse-event clinical_review_status auto-advance
# ===========================================================================
class TestRecallHop3:

    # difficulty: transitive_cascade/recall_to_dose_to_certificate_to_review_chain
    def test_recall_auto_advances_pending_review_to_under_review(self, api):
        """PRD §3.5: "Every AdverseEvent whose dose_id references one
        of the just-invalidated doses and whose clinical_review_status
        is currently PENDING_REVIEW is auto-advanced to UNDER_REVIEW."

        Claim: after recall, an AE in PENDING_REVIEW state tied to an
        invalidated dose is auto-advanced to UNDER_REVIEW.

        # difficulty: transitive_cascade/recall_to_dose_to_certificate_to_review_chain
        """
        ctx = setup_mmr_lot_recall_with_ae_pending()
        ae_before = re_get_adverse_event(ctx["adverse_event"]["id"])
        assert ae_before["clinical_review_status"] == "PENDING_REVIEW"
        recall_lot(ctx["lot_mmr"]["id"], reason="MANUFACTURER_DEFECT")
        ae_after = re_get_adverse_event(ctx["adverse_event"]["id"])
        assert ae_after["clinical_review_status"] == "UNDER_REVIEW", (
            f"PRD §3.5: clinical_review_status must auto-advance to "
            f"UNDER_REVIEW, got {ae_after['clinical_review_status']!r}"
        )

    def test_recall_does_not_touch_vaers_submission_status(self, api):
        """PRD §3.5: "The vaers_submission_status dimension is
        untouched by the cascade."

        Claim: vaers_submission_status remains NOT_SUBMITTED after
        recall, even though clinical_review_status advanced.
        """
        ctx = setup_mmr_lot_recall_with_ae_pending()
        recall_lot(ctx["lot_mmr"]["id"], reason="MANUFACTURER_DEFECT")
        ae_after = re_get_adverse_event(ctx["adverse_event"]["id"])
        assert ae_after["vaers_submission_status"] == "NOT_SUBMITTED", (
            "PRD §3.5: recall must NOT touch vaers_submission_status"
        )


# ===========================================================================
# §3.5 Three-hop combined cascade (difficulty design)
# ===========================================================================
class TestThreeHopCascadeCombined:
    """Difficulty design: recall_to_dose_to_certificate_to_review_chain.
    The end-to-end recall cascade hits 4 entities (lot, dose, cert, AE)
    in one synchronous request.
    """

    # difficulty: transitive_cascade/recall_to_dose_to_certificate_to_review_chain
    def test_full_recall_cascade_synchronous(self, api):
        """PRD §3.5: end-to-end three-hop cascade
        (lot RECALLED -> dose INVALIDATED -> certificate DEFICIENT
        + AE UNDER_REVIEW) inside the single recall request.

        Claim: after a single POST /vaccine-lots/{id}/recall, all four
        target entities have reached their cascaded states
        synchronously.

        # difficulty: transitive_cascade/recall_to_dose_to_certificate_to_review_chain
        """
        ctx = setup_mmr_lot_recall_with_ae_pending()
        # Trigger.
        recall_lot(ctx["lot_mmr"]["id"], reason="MANUFACTURER_DEFECT")
        # Verify lot.
        lot_after = re_get_lot(ctx["lot_mmr"]["id"])
        assert lot_after["status"] == "RECALLED"
        # Verify dose.
        dose_after = re_get_dose(
            ctx["patient"]["id"], ctx["mmr_dose"]["id"],
        )
        assert dose_after["dose_state"] == "INVALIDATED"
        assert dose_after["invalidation_reason"] == "LOT_RECALL"
        # Verify cert.
        cert_after = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert_after["certificate_status"] == "DEFICIENT"
        assert "MMR_MEASLES" in cert_after["missing_antigens"]
        # Verify AE.
        ae_after = re_get_adverse_event(ctx["adverse_event"]["id"])
        assert ae_after["clinical_review_status"] == "UNDER_REVIEW"


# ===========================================================================
# §3.3 Data-error invalidation cascade (difficulty design)
# ===========================================================================
class TestDataErrorInvalidationCascade:
    """Difficulty design: data_error_invalidation_to_certificate_chain.
    PRD §3.3: data-error invalidate triggers school_coverage_evaluation;
    PRD §3.3 / §3.8: ISSUED -> DEFICIENT when recompute uncovers an
    antigen.
    """

    # difficulty: transitive_cascade/data_error_invalidation_to_certificate_chain
    def test_invalidate_demotes_certificate_and_restores_inventory(self, api):
        """PRD §3.3: "An already-administered dose can be invalidated
        due to data error by a PublicHealthOfficer, supplying the
        reason DATA_ERROR. The dose's dose_state advances
        ADMINISTERED -> INVALIDATED, invalidation_reason is recorded
        as DATA_ERROR, the lot's doses_on_hand is incremented by one
        (data-error invalidations always restore stock), and the
        school-coverage recomputation runs for the patient - demoting
        any ISSUED certificate to DEFICIENT if the recompute newly
        uncovers an antigen."

        Claim: data-error invalidate causes (a) dose INVALIDATED with
        reason DATA_ERROR; (b) lot.doses_on_hand restored by 1; (c)
        certificate ISSUED -> DEFICIENT with newly uncovered antigen
        in missing_antigens.

        # difficulty: transitive_cascade/data_error_invalidation_to_certificate_chain
        """
        ctx = setup_hepb_single_required_and_dose(
            patient_dob="2020-01-01",
            lot_doses_on_hand=1,  # 1 dose; admin drops to 0 -> EXHAUSTED.
        )
        cert_before = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert_before["certificate_status"] == "ISSUED"
        # Verify lot exhausted after admin.
        lot_mid = re_get_lot(ctx["lot_hepb"]["id"])
        assert lot_mid["doses_on_hand"] == 0
        assert lot_mid["status"] == "EXHAUSTED"
        # Invalidate the dose.
        invalidate_dose(
            ctx["patient"]["id"], ctx["dose"]["id"], reason="DATA_ERROR",
        )
        # Verify dose.
        dose_after = re_get_dose(
            ctx["patient"]["id"], ctx["dose"]["id"],
        )
        assert dose_after["dose_state"] == "INVALIDATED"
        assert dose_after["invalidation_reason"] == "DATA_ERROR"
        # Verify lot doses_on_hand restored. PRD §3.3: "the lot's
        # doses_on_hand is incremented by one (data-error
        # invalidations always restore stock)".
        lot_after = re_get_lot(ctx["lot_hepb"]["id"])
        assert lot_after["doses_on_hand"] == 1, (
            "PRD §3.3: data-error invalidate must restore doses_on_hand by 1"
        )
        # Verify certificate demoted.
        cert_after = re_get_certificate(
            ctx["patient"]["id"], ctx["certificate"]["id"],
        )
        assert cert_after["certificate_status"] == "DEFICIENT"
        assert "HEPB" in cert_after["missing_antigens"]


# ===========================================================================
# Compensating action - dose inventory conservation
# (difficulty: compensating_invariant/dose_inventory_conservation_under_data_error_invalidation)
# ===========================================================================
class TestInventoryConservationCompensating:
    """Difficulty design:
    dose_inventory_conservation_under_data_error_invalidation.
    PRD §3.3 forward action (admin decrement) + compensating action
    (data-error invalidate increment) -> conserved.
    """

    # difficulty: compensating_invariant/dose_inventory_conservation_under_data_error_invalidation
    # difficulty: transitive_cascade/data_error_invalidation_to_certificate_chain
    def test_administer_then_invalidate_conserves_doses_on_hand(self, api):
        """PRD §3.3: administer decrements doses_on_hand by 1.
        PRD §3.3: data-error invalidate increments doses_on_hand by 1.

        Claim: initial_doses_on_hand == final_doses_on_hand after the
        (administer; data-error invalidate) pair.

        # difficulty: compensating_invariant/dose_inventory_conservation_under_data_error_invalidation
        """
        anchor_clock()
        provider_org = create_provider_organization()
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=7,
        )
        patient = create_patient()
        initial = re_get_lot(lot["id"])
        assert initial["doses_on_hand"] == 7
        dose = schedule_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        administer_dose(
            patient["id"], dose["id"], iso_anchor_offset(),
        )
        mid = re_get_lot(lot["id"])
        assert mid["doses_on_hand"] == 6
        invalidate_dose(patient["id"], dose["id"], "DATA_ERROR")
        final = re_get_lot(lot["id"])
        assert final["doses_on_hand"] == 7, (
            f"PRD §3.3: inventory must be conserved across "
            f"administer-then-invalidate (initial=7, final="
            f"{final['doses_on_hand']})"
        )


# ===========================================================================
# Compensating action - school coverage set conservation under recall +
# revaccinate (difficulty: compensating_invariant/school_coverage_set_conservation_under_recall_then_revaccinate)
# ===========================================================================
class TestSchoolCoverageSetConservation:
    """Difficulty design:
    school_coverage_set_conservation_under_recall_then_revaccinate.

    PRD §3.5: recall demotes ISSUED -> DEFICIENT when a covered
    antigen is uncovered.
    PRD §3.3: subsequent administer auto-bubbles DEFICIENT -> ISSUED
    when missing_antigens becomes empty again.
    """

    # difficulty: compensating_invariant/school_coverage_set_conservation_under_recall_then_revaccinate
    def test_recall_then_revaccinate_restores_issued(self, api):
        """PRD §3.5 + §3.3: forward (recall) + compensating (admin from
        new lot) restores certificate to ISSUED with empty
        missing_antigens.

        # difficulty: compensating_invariant/school_coverage_set_conservation_under_recall_then_revaccinate
        """
        anchor_clock()
        provider_org = create_provider_organization()
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0,
            routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
            school_enrollment_required=True,
        )
        product = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        lot_a = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=1,
        )
        lot_b = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=1,
        )
        patient = create_patient(date_of_birth="2020-01-01")
        schedule_and_administer_dose(
            patient["id"], product["id"], lot_a["id"],
            provider_org["id"],
            administered_at=iso_anchor_offset(),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        cert = create_certificate(patient["id"])
        cert = issue_certificate(patient["id"], cert["id"])
        assert cert["certificate_status"] == "ISSUED"
        assert cert["missing_antigens"] == []
        # Recall lot A -> cert -> DEFICIENT.
        recall_lot(lot_a["id"], reason="CONTAMINATION")
        cert_after_recall = re_get_certificate(patient["id"], cert["id"])
        assert cert_after_recall["certificate_status"] == "DEFICIENT"
        assert "MMR_MEASLES" in cert_after_recall["missing_antigens"]
        # Revaccinate from lot B.
        schedule_and_administer_dose(
            patient["id"], product["id"], lot_b["id"],
            provider_org["id"],
            administered_at=iso_anchor_offset(seconds=60),
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        cert_final = re_get_certificate(patient["id"], cert["id"])
        # PRD §3.3: "if the recompute reveals an empty set, the
        # certificate auto-bubbles up to ISSUED and its issued_at is
        # stamped."
        assert cert_final["certificate_status"] == "ISSUED", (
            f"PRD §3.3: cert must auto-promote DEFICIENT -> ISSUED "
            f"after revaccinate, got {cert_final['certificate_status']!r}"
        )
        assert cert_final["missing_antigens"] == [], (
            "PRD §3.3: missing_antigens must become [] after revaccination"
        )
