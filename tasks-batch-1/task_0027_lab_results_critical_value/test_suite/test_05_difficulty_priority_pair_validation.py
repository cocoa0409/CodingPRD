"""Difficulty Rule 5 — priority_pair_validation_conflict.

Two requests each violate two stacked validation rules; PRD §2.10 declares the
priority order so the higher-priority error wins.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    acknowledge_notification,
    api_client,
    ApiErrorId,
    bootstrap_actors,
    create_result_payload,
    get_success_data,
    make_ordering_provider_headers,
    register_clinician,
    register_patient,
    setup_provisional_result,
    setup_sent_critical_notification,
    validate_error,
)


class TestStateBeforeBusinessConstraintOnAck:
    """PRD §2.10: state-validity is priority 4, ack-recipient is priority 13.
    When both would fail on the same request, state wins → ERR_INVALID_STATE.
    """

    def test_ack_after_already_acknowledged_returns_invalid_state_even_if_recipient_wrong(self, api):
        """PRD §2.10: "authentication of the caller's headers, role-based authorization for the endpoint, existence of every path-id and foreign-key referent (left-to-right), and only then state-validity of the targeted entity against §3's state machines. After those four, domain-specific rules apply in the following order: the `STAT`-priority channel rule for critical notifications, the released-result protection on specimen rejection, the instrument-slot overlap check with `qc_buffer_minutes`, the per-collector five-minute spacing rule, the cross-reference rule that `Result.specimen_id` and `Result.lab_order_id` must agree on the parent order, the cross-reference rule that `Result.run_id` must reference an `InstrumentRun` whose `specimen_id` matches the result's `specimen_id`, the reference-range and critical-range sanity checks, the acknowledgement-window check, the acknowledgement-recipient check, the OCC stale-version checks, and finally the uniqueness checks on identifiers like `mrn`, `npi`, and `instrument_code`."

        Design: Difficulty/priority_pair_validation_conflict/state_versus_business_safety_send_on_already_acknowledged
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-P5A010", date_of_birth="1980-01-01",
        )
        # Use a ROUTINE order so the auto-create can validly use either channel —
        # but to avoid §3.7 STAT-PHONE forcing PHONE, we keep this on ROUTINE.
        bundle = setup_sent_critical_notification(
            actors, patient,
            panel_code="CMP", priority="ROUTINE", container_code="GREEN",
            analyte_code="K", numeric_value=6.50, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
            run_start="2026-05-28T08:30:00Z", run_end="2026-05-28T08:40:00Z",
        )
        notif = bundle["notification"]
        # First ack (succeeds) by the correct recipient.
        acknowledge_notification(
            actors, notif["id"], recipient_id=notif["recipient_clinician_id"],
            ack_method="WEB_UI", attestation_text="First ack ok.",
        )
        # Register a different ORDERING_PROVIDER to use as the wrong-recipient.
        wrong_op = register_clinician(
            "ORDERING_PROVIDER", actors.director_id,
            full_name="Other Provider",
        )
        # Second ack: wrong recipient AND notification already ACKNOWLEDGED.
        # Per PRD §2.10, state check fires first → ERR_INVALID_STATE.
        from test_helpers import create_acknowledgement_payload
        res = api_client.create_acknowledgement(
            notif["id"],
            create_acknowledgement_payload(
                ack_method="WEB_UI",
                attestation_text="Second ack attempt by wrong provider.",
            ),
            make_ordering_provider_headers(wrong_op["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_send_on_already_sent_notification_returns_invalid_state(self, api):
        """PRD §2.10: "and only then state-validity of the targeted entity against §3's
        state machines."
        PRD §3.7: "A pending notification is delivered by a `LabTech` (acting as the
        integration operator), which transitions it from `PENDING` to `SENT`."

        Design: Difficulty/priority_pair_validation_conflict/state_versus_business_safety_send_on_already_acknowledged
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-P5A020", date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        # Second send — notification already SENT.
        res = api_client.send_critical_notification(
            bundle["notification"]["id"], actors.lt_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestExistenceBeforeBusinessReferentialOnResultCreate:
    """PRD §2.10 + §2.5: existence (priority 3, ERR_NOT_FOUND) is checked before
    business_referential rules like ERR_RUN_SPECIMEN_MISMATCH.
    """

    def test_create_result_with_nonexistent_run_returns_not_found_not_referential(self, api):
        """PRD §2.5: "Path parameters are resolved from left to right; the first id
        that does not resolve to a live row terminates the request with `ERR_NOT_FOUND`
        (HTTP 404), and foreign-key fields in the request body are validated against
        the same rule once the path-level lookups succeed."
        PRD §2.10: "and a request that fails both an existence check and a domain check
        reports the existence failure."

        Design: Difficulty/priority_pair_validation_conflict/existence_versus_business_referential_create_result_on_nonexistent_run
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-P5B010", date_of_birth="1980-01-01",
        )
        from test_helpers import (
            accession_specimen,
            collect_specimen,
            create_order,
            create_specimen,
            transit_specimen,
        )

        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])
        accession_specimen(actors, sp["id"])

        # No InstrumentRun exists. run_id = NON_EXISTENT_UUID — and a
        # vacuous run.specimen_id mismatch would also apply if it existed.
        # Per PRD §2.5/§2.10, existence (ERR_NOT_FOUND) wins.
        res = api_client.create_result(
            create_result_payload(
                lab_order_id=order["id"],
                specimen_id=sp["id"],
                run_id=NON_EXISTENT_UUID,
                analyte_code="K", numeric_value=4.20, unit="mmol/L",
                reference_low=3.50, reference_high=5.10,
                critical_low=2.50, critical_high=6.00,
            ),
            actors.lt_headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_create_result_with_nonexistent_specimen_returns_not_found(self, api):
        """PRD §2.5: "the first id that does not resolve to a live row terminates the
        request with `ERR_NOT_FOUND` (HTTP 404), and foreign-key fields in the request
        body are validated against the same rule once the path-level lookups succeed."

        Design: Difficulty/priority_pair_validation_conflict/existence_versus_business_referential_create_result_on_nonexistent_run
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-P5B020", date_of_birth="1980-01-01",
        )
        from test_helpers import (
            accession_specimen,
            collect_specimen,
            complete_instrument_run,
            create_instrument_run,
            create_order,
            create_specimen,
            transit_specimen,
        )

        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])
        accession_specimen(actors, sp["id"])
        run = create_instrument_run(
            actors, sp["id"], "2026-05-28T08:30:00Z", "2026-05-28T08:40:00Z"
        )
        complete_instrument_run(actors, run["id"])

        res = api_client.create_result(
            create_result_payload(
                lab_order_id=order["id"],
                specimen_id=NON_EXISTENT_UUID,
                run_id=run["id"],
                analyte_code="K", numeric_value=4.20, unit="mmol/L",
                reference_low=3.50, reference_high=5.10,
                critical_low=2.50, critical_high=6.00,
            ),
            actors.lt_headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
