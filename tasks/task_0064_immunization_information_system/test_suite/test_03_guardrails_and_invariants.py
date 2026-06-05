"""Recording guardrail precedence, numeric boundaries, cross-entity state
dependencies, interval/expiry semantics, and conserved-quantity invariants."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_catalog_and_patient, setup_patient_with_doses, create_allergy,
    issue_recall, reverse_recall, run_evaluation, issue_certificate,
    record_dose, api_client, make_registrar_headers, make_clerk_headers,
    create_product_payload, create_immunization_payload,
)

REG = make_registrar_headers()
CLERK = make_clerk_headers()

DTAP = dict(product_code="DTAP", antigen="DTAP", doses_in_series=5,
            min_age_days=42, recommended_age_days=60, min_interval_days=28,
            grace_period_days=4)
C1 = dict(product_code="C1", antigen="C1", doses_in_series=1, min_age_days=0,
          recommended_age_days=0, min_interval_days=0, grace_period_days=4)


class TestGuardrailPrecedence:
    def test_contraindication_beats_interval(self, api):
        """PRD §3.3: "the recording checks run in this order: First, provider
        authorization ... Next, the safety check: the patient must have no
        CONTRAINDICATED allergy record for the product's antigen, or the dose is
        rejected with ERR_CONTRAINDICATED (HTTP 422). Next, for strict
        directly-recorded doses, the minimum-interval guard described above,
        rejecting with ERR_INTERVAL_TOO_SHORT."

        A dose violating both contraindication and interval reports
        ERR_CONTRAINDICATED (contraindication is checked before interval).

        Design: Difficulty/priority_pair_validation_conflict/contraindication_beats_interval_on_record
        """
        _, provider, lot, patient, _ = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        create_allergy(patient["id"], "DTAP", severity="CONTRAINDICATED")
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-02-20"), REG)
        validate_error(resp, ApiErrorId.ERR_CONTRAINDICATED.value)

    def test_lot_recalled_beats_lot_expired(self, api):
        """PRD §3.3: "Next, the lot must not be recalled: a dose against a lot
        whose status is RECALLED is rejected with ERR_LOT_RECALLED (HTTP 409).
        Next, lot expiry: the administered_date must lie within the lot's window
        ... or the dose is rejected with ERR_LOT_EXPIRED."

        A recalled, expired lot reports ERR_LOT_RECALLED (recall is checked
        before expiry).

        Design: Difficulty/priority_pair_validation_conflict/lot_recalled_state_beats_lot_expired_temporal_on_record
        """
        product, provider, lot, patient = setup_catalog_and_patient(
            product_overrides=create_product_payload(**DTAP),
            lot_overrides={"lot_number": "LJ", "expiration_date": "2025-03-01"},
            patient_overrides={"date_of_birth": "2025-01-01"})
        issue_recall(lot["id"], reason="recalled")
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-12-01"), REG)
        validate_error(resp, ApiErrorId.ERR_LOT_RECALLED.value)

    def test_contraindication_reported_for_safety_before_temporal_status(self, api):
        """PRD §5: the ERR_CONTRAINDICATED error maps to HTTP status 422.
        PRD §3.3: "the safety check: the patient must have no CONTRAINDICATED
        allergy record for the product's antigen, or the dose is rejected with
        ERR_CONTRAINDICATED (HTTP 422). Next, for strict directly-recorded doses,
        the minimum-interval guard described above, rejecting with
        ERR_INTERVAL_TOO_SHORT."

        The doubly-violating dose's response carries the safety error's HTTP 422.

        Design: Difficulty/priority_pair_validation_conflict/contraindication_beats_interval_on_record
        """
        _, provider, lot, patient, _ = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        create_allergy(patient["id"], "DTAP", severity="CONTRAINDICATED")
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-02-20"), REG)
        assert resp.status_code == 422, \
            f"ERR_CONTRAINDICATED maps to 422, got {resp.status_code}"

    def test_recalled_lot_reported_with_409_over_expiry_422(self, api):
        """PRD §5: ERR_LOT_RECALLED maps to HTTP 409 while ERR_LOT_EXPIRED maps
        to HTTP 422.
        PRD §3.3: "the lot must not be recalled: a dose against a lot whose
        status is RECALLED is rejected with ERR_LOT_RECALLED (HTTP 409). Next,
        lot expiry: the administered_date must lie within the lot's window ... or
        the dose is rejected with ERR_LOT_EXPIRED."

        The recalled+expired lot yields the recall path's HTTP 409, not 422.

        Design: Difficulty/priority_pair_validation_conflict/lot_recalled_state_beats_lot_expired_temporal_on_record
        """
        product, provider, lot, patient = setup_catalog_and_patient(
            product_overrides=create_product_payload(**DTAP),
            lot_overrides={"lot_number": "LJ", "expiration_date": "2025-03-01"},
            patient_overrides={"date_of_birth": "2025-01-01"})
        issue_recall(lot["id"], reason="recalled")
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-12-01"), REG)
        assert resp.status_code == 409, \
            f"ERR_LOT_RECALLED maps to 409, got {resp.status_code}"


class TestBoundaryPrecision:
    def test_interval_one_day_below_graced_minimum_rejected(self, api):
        """PRD §3.2: "a dose whose gap from the prior valid same-antigen dose is
        less than min_interval_days reduced by the grace window is refused
        outright with ERR_INTERVAL_TOO_SHORT (HTTP 422)".

        Dose2 at 23 days (graced minimum is 24) is rejected.

        Design: Difficulty/boundary_precision_check/interval_one_day_below_graced_minimum_is_rejected
        """
        _, provider, lot, patient, _ = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-03-03"), REG)
        validate_error(resp, ApiErrorId.ERR_INTERVAL_TOO_SHORT.value)

    def test_interval_exactly_at_graced_minimum_accepted(self, api):
        """PRD §2.7: "if a prior valid date exists and the number of days from
        that prior valid date to this dose's administered_date is strictly less
        than the product's min_interval_days reduced by the grace window, its
        validity is INVALID_INTERVAL and it is not counted; otherwise the dose is
        VALID".

        At exactly the graced minimum (24 days), the gap is not strictly less
        than 24, so the dose is accepted and VALID — the upper side of the
        rejected boundary.

        Design: Difficulty/boundary_precision_check/interval_one_day_below_graced_minimum_is_rejected
        """
        _, provider, lot, patient, _ = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        dose2 = record_dose(patient["id"], lot["id"], provider["id"],
                            "2025-03-04")
        assert dose2["validity"] == "VALID", \
            f"expected VALID at 24-day graced minimum, got {dose2['validity']}"

    def test_recording_dose_at_exact_capacity_allowed(self, api):
        """PRD §2.8: "Recording the dose that brings the count up to exactly
        doses_total is allowed; the next dose, which would push the count past
        doses_total, is rejected with ERR_LOT_DEPLETED (HTTP 422)."

        The single allowed dose on a doses_total=1 lot is accepted and brings
        administered_count to exactly 1.

        Design: Difficulty/boundary_precision_check/lot_depleted_at_exact_capacity_boundary
        """
        product, provider, lot, patient = setup_catalog_and_patient(
            product_overrides=create_product_payload(**C1),
            lot_overrides={"doses_total": 1},
            patient_overrides={"date_of_birth": "2024-01-01"})
        record_dose(patient["id"], lot["id"], provider["id"], "2025-01-01")
        final = get_success_data(api_client.get_lot(lot["id"], REG))
        assert final["administered_count"] == 1, \
            f"expected administered_count 1 at capacity, got {final['administered_count']}"

    def test_lot_depleted_at_exact_capacity_boundary(self, api):
        """PRD §2.8: "Recording the dose that brings the count up to exactly
        doses_total is allowed; the next dose, which would push the count past
        doses_total, is rejected with ERR_LOT_DEPLETED (HTTP 422)."

        A doses_total=1 lot accepts its first dose and rejects the second.

        Design: Difficulty/boundary_precision_check/lot_depleted_at_exact_capacity_boundary
        """
        product, provider, lot, pat_a = setup_catalog_and_patient(
            product_overrides=create_product_payload(**C1),
            lot_overrides={"doses_total": 1},
            patient_overrides={"date_of_birth": "2024-01-01"})
        from test_helpers import create_patient
        pat_b = create_patient(date_of_birth="2024-01-01")
        record_dose(pat_a["id"], lot["id"], provider["id"], "2025-01-01")
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=pat_b["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-01-01"), REG)
        validate_error(resp, ApiErrorId.ERR_LOT_DEPLETED.value)


class TestCrossEntityStateDependency:
    def test_record_blocked_when_lot_recalled(self, api):
        """PRD §3.3: "the lot must not be recalled: a dose against a lot whose
        status is RECALLED is rejected with ERR_LOT_RECALLED (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/immunization_record_blocked_when_lot_recalled
        """
        product, provider, lot, patient = setup_catalog_and_patient(
            product_overrides=create_product_payload(**C1),
            patient_overrides={"date_of_birth": "2024-01-01"})
        issue_recall(lot["id"], reason="recalled")
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-01-01"), REG)
        validate_error(resp, ApiErrorId.ERR_LOT_RECALLED.value)

    def test_recall_sets_lot_status_recalled_before_record_block(self, api):
        """PRD §3.9: "Issuing the recall sets the lot's status to RECALLED".
        PRD §3.3: "a dose against a lot whose status is RECALLED is rejected with
        ERR_LOT_RECALLED (HTTP 409)."

        The blocking state on the other entity (VaccineLot.status == RECALLED) is
        observable on the lot, and recording against it is rejected.

        Design: Difficulty/cross_entity_state_dependency/immunization_record_blocked_when_lot_recalled
        """
        product, provider, lot, patient = setup_catalog_and_patient(
            product_overrides=create_product_payload(**C1),
            patient_overrides={"date_of_birth": "2024-01-01"})
        issue_recall(lot["id"], reason="recalled")
        recalled_lot = get_success_data(api_client.get_lot(lot["id"], REG))
        assert recalled_lot["status"] == "RECALLED", \
            f"expected RECALLED, got {recalled_lot['status']}"
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-01-01"), REG)
        assert resp.status_code == 409, \
            f"ERR_LOT_RECALLED maps to 409, got {resp.status_code}"

    def test_certificate_blocked_when_evaluation_behind(self, api):
        """PRD §3.7: "Issuance is permitted only when the cited evaluation's
        overall_status is UP_TO_DATE or CONDITIONAL; an evaluation that is BEHIND
        or NON_COMPLIANT cannot back a certificate and the issuance is rejected
        with ERR_NOT_COMPLIANT (HTTP 422)."

        A patient with zero doses (BEHIND) cannot back a certificate.

        Design: Difficulty/cross_entity_state_dependency/certificate_blocked_when_evaluation_behind
        """
        from test_helpers import set_clock, create_product, create_patient
        set_clock("2026-06-01T00:00:00Z")
        create_product(**C1)
        patient = create_patient(date_of_birth="2024-01-01")
        ev = run_evaluation(patient["id"], "2026-06-01")
        pat = get_success_data(api_client.get_patient(patient["id"], REG))
        assert ev["overall_status"] == "BEHIND", \
            f"precondition: expected BEHIND, got {ev['overall_status']}"
        resp = issue_certificate(patient["id"], ev["id"], pat["version"])
        validate_error(resp, ApiErrorId.ERR_NOT_COMPLIANT.value)


class TestResourceTemporalOverlap:
    def test_interval_spacing_with_grace_buffer_rejected(self, api):
        """PRD §3.2: "a dose whose gap from the prior valid same-antigen dose is
        less than min_interval_days reduced by the grace window is refused
        outright with ERR_INTERVAL_TOO_SHORT (HTTP 422)".

        A dose 23 days after the prior valid dose (graced minimum 24) collides
        on the patient's antigen series.

        Design: Difficulty/resource_temporal_overlap/interval_spacing_with_grace_buffer_on_patient_series
        """
        _, provider, lot, patient, _ = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-03-03"), REG)
        validate_error(resp, ApiErrorId.ERR_INTERVAL_TOO_SHORT.value)

    def test_lot_window_containment_after_expiry_rejected(self, api):
        """PRD §3.3: "lot expiry: the administered_date must lie within the lot's
        window, not before received_date and not after expiration_date, or the
        dose is rejected with ERR_LOT_EXPIRED."

        A dose dated after the lot's expiration_date is rejected.

        Design: Difficulty/resource_temporal_overlap/lot_validity_window_containment_on_lot_resource
        """
        product, provider, lot, patient = setup_catalog_and_patient(
            product_overrides=create_product_payload(**C1),
            lot_overrides={"expiration_date": "2025-03-01"},
            patient_overrides={"date_of_birth": "2024-01-01"})
        resp = api_client.create_immunization(create_immunization_payload(
            patient_id=patient["id"], lot_id=lot["id"],
            provider_id=provider["id"], administered_date="2025-06-01"), REG)
        validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED.value)


class TestCompensatingInvariants:
    def test_administered_count_conserved_across_recall_and_reverse(self, api):
        """PRD §2.8: "The compensating actions — invalidating a dose by recall,
        deleting a dose, and the inverse of a revalidation — each subtract 1,
        exactly undoing the forward action."

        A lot with one recorded dose returns to administered_count 1 (and status
        AVAILABLE) after recall-then-reverse.

        Design: Difficulty/compensating_invariant/lot_administered_count_conserved_across_recall_and_reverse
        """
        _, _, lot, _, _ = setup_patient_with_doses(
            dose_dates=["2025-01-01"],
            product_overrides=create_product_payload(**C1),
            patient_overrides={"date_of_birth": "2024-01-01"})
        recall = issue_recall(lot["id"], reason="precaution")
        reverse_recall(lot["id"], recall["id"])
        final = get_success_data(api_client.get_lot(lot["id"], REG))
        assert final["administered_count"] == 1, \
            f"expected administered_count 1 after reverse, got {final['administered_count']}"
        assert final["status"] == "AVAILABLE", \
            f"expected AVAILABLE after reverse, got {final['status']}"

    def test_valid_dose_count_conserved_across_amend_and_delete(self, api):
        """PRD §3.2: "A successful retraction decrements the lot's
        administered_count by 1, recomputes dose_number and validity for the
        patient's same-antigen series".

        After amending dose2's date and deleting it, dose1 remains the only VALID
        dose with dose_number 1.

        Design: Difficulty/compensating_invariant/valid_dose_count_conserved_across_amend_and_delete
        """
        _, _, lot, _, doses = setup_patient_with_doses(
            dose_dates=["2025-02-08", "2025-03-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        dose1, dose2 = doses
        validate_success(api_client.amend_immunization(
            dose2["id"], {"administered_date": "2025-03-15"}, CLERK))
        validate_success(api_client.delete_immunization(dose2["id"], REG))
        d1 = get_success_data(api_client.get_immunization(dose1["id"], REG))
        d2 = get_success_data(api_client.get_immunization(dose2["id"], REG))
        assert d1["dose_number"] == 1, f"expected dose1 number 1, got {d1['dose_number']}"
        assert d1["validity"] == "VALID", f"expected dose1 VALID, got {d1['validity']}"
        assert d2["status"] == "DELETED", f"expected dose2 DELETED, got {d2['status']}"
