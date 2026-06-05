"""Corner — validations section: business rules not exercised by difficulty
(released-result protection, specimen/order mismatch, invalid range, role
mismatch).
"""
from test_helpers import (
    accession_specimen,
    api_client,
    ApiErrorId,
    bootstrap_actors,
    collect_specimen,
    complete_instrument_run,
    create_instrument_run,
    create_order,
    create_result_payload,
    create_specimen,
    create_specimen_payload,
    get_success_data,
    register_patient,
    reject_specimen_payload,
    setup_released_result,
    transit_specimen,
    validate_error,
)


class TestReleasedResultBlocksSpecimenReject:
    def test_reject_specimen_with_released_result_returns_blocks_reject_error(self, api):
        """PRD §3.3: "Rejection of an `ACCESSIONED` specimen that has a `RELEASED`
        `Result` is forbidden, since that would orphan a clinically released finding;
        such an attempt is rejected with `ERR_RELEASED_RESULT_BLOCKS_REJECT` and the
        caller is directed to invalidate the result first (only a `LabDirector` may
        do so)."

        Design: Corner/validations/released_result_blocks_specimen_reject
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(actors.lt_id, mrn="MRN-RB0100")
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        # sp is ACCESSIONED + has a RELEASED Result. Reject MUST be blocked.
        res = api_client.reject_specimen(
            bundle["specimen"]["id"],
            reject_specimen_payload("HEMOLYZED"),
            actors.lt_headers,
        )
        validate_error(res, ApiErrorId.ERR_RELEASED_RESULT_BLOCKS_REJECT)
        sp_after = get_success_data(
            api_client.get_specimen(bundle["specimen"]["id"], actors.lt_headers)
        )
        assert sp_after["status"] == "ACCESSIONED", (
            f"specimen MUST remain ACCESSIONED after rejected reject; "
            f"got {sp_after['status']!r}"
        )


class TestResultSpecimenOrderMismatch:
    def test_create_result_with_specimen_on_different_order_returns_mismatch(self, api):
        """PRD §3.5: "The `specimen_id` and `lab_order_id` MUST agree on the parent
        order — that is, the named specimen's own `lab_order_id` MUST equal the supplied
        `lab_order_id` — or the create is rejected with `ERR_SPECIMEN_ORDER_MISMATCH`."

        Design: Corner/validations/result_specimen_order_mismatch_rejected
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(actors.lt_id, mrn="MRN-SM0100")

        ord_a = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        ord_b = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp_a = create_specimen(actors, ord_a["id"], container_code="GREEN")
        collect_specimen(actors, sp_a["id"])
        transit_specimen(actors, sp_a["id"])
        accession_specimen(actors, sp_a["id"])
        run = create_instrument_run(
            actors, sp_a["id"], "2026-05-28T08:30:00Z", "2026-05-28T08:40:00Z"
        )
        complete_instrument_run(actors, run["id"])

        # Try to create Result with lab_order_id=ord_b but specimen_id=sp_a (which
        # belongs to ord_a). MUST be rejected.
        res = api_client.create_result(
            create_result_payload(
                lab_order_id=ord_b["id"],
                specimen_id=sp_a["id"],
                run_id=run["id"],
                analyte_code="K", numeric_value=4.20, unit="mmol/L",
                reference_low=3.50, reference_high=5.10,
                critical_low=2.50, critical_high=6.00,
            ),
            actors.lt_headers,
        )
        validate_error(res, ApiErrorId.ERR_SPECIMEN_ORDER_MISMATCH)


class TestResultInvalidRange:
    def test_create_result_with_inverted_critical_range_returns_invalid_range(self, api):
        """PRD §3.5: "The references MUST satisfy `reference_high > reference_low` AND
        `critical_high > critical_low`; a violation is rejected with `ERR_INVALID_RANGE`."

        Design: Corner/validations/result_invalid_range_critical_le_reference
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(actors.lt_id, mrn="MRN-IR0100")
        ord_ = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp = create_specimen(actors, ord_["id"], container_code="GREEN")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])
        accession_specimen(actors, sp["id"])
        run = create_instrument_run(
            actors, sp["id"], "2026-05-28T08:30:00Z", "2026-05-28T08:40:00Z"
        )
        complete_instrument_run(actors, run["id"])

        # Send inverted critical range: critical_high (2.50) < critical_low (6.00).
        res = api_client.create_result(
            create_result_payload(
                lab_order_id=ord_["id"],
                specimen_id=sp["id"],
                run_id=run["id"],
                analyte_code="K", numeric_value=4.20, unit="mmol/L",
                reference_low=3.50, reference_high=5.10,
                critical_low=6.00, critical_high=2.50,
            ),
            actors.lt_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_RANGE)


class TestClinicianRoleMismatchOnSpecimenCollector:
    def test_create_specimen_with_lab_tech_as_collector_returns_role_mismatch(self, api):
        """PRD §3.1: "the same error is returned when a `Specimen` is created with a
        `collector_clinician_id` whose underlying clinician has a `role_type` other
        than `PHLEBOTOMIST`."

        Design: Corner/validations/clinician_role_mismatch_on_specimen_collector
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", with_instrument=False)
        patient = register_patient(actors.lt_id, mrn="MRN-RM0100")
        ord_ = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")

        # collector_clinician_id is the LAB_TECH (role_type != PHLEBOTOMIST).
        res = api_client.create_specimen(
            ord_["id"],
            create_specimen_payload(
                collector_clinician_id=actors.lt_id,
                container_code="GREEN",
            ),
            actors.lt_headers,
        )
        validate_error(res, ApiErrorId.ERR_CLINICIAN_ROLE_MISMATCH)
