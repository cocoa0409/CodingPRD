"""Difficulty Rule 7 — cross_entity_state_dependency.

Result.PROVISIONAL → RELEASED requires Specimen.status == ACCESSIONED.
AcknowledgementReceipt requires CriticalNotification.status == SENT.
Different entity pairs, both gated by ERR_INVALID_STATE.
"""
from test_helpers import (
    accession_specimen,
    api_client,
    ApiErrorId,
    bootstrap_actors,
    collect_specimen,
    complete_instrument_run,
    create_acknowledgement_payload,
    create_instrument_run,
    create_order,
    create_result,
    create_specimen,
    get_lab_order_version,
    get_notification_for_result,
    get_success_data,
    make_ordering_provider_headers,
    register_patient,
    release_result_payload,
    set_clock,
    setup_pending_critical_notification,
    setup_released_result,
    transit_specimen,
    validate_error,
)


class TestResultReleaseRequiresSpecimenAccessioned:
    """PRD §3.5: release requires Specimen.status == ACCESSIONED and InstrumentRun.
    status == COMPLETED, else ERR_INVALID_STATE.
    """

    def test_release_with_specimen_not_accessioned_returns_invalid_state(self, api):
        """PRD §3.5: "The specimen named by the result MUST be in `ACCESSIONED` status
        and the instrument run named by the result MUST be in `COMPLETED` status;
        otherwise the release is rejected with `ERR_INVALID_STATE`."

        Setup: create the Result against a fully-ACCESSIONED specimen, then reject
        that specimen (PRD §3.3 allows ACCESSIONED → REJECTED when no `RELEASED`
        Result exists yet). The specimen is now no longer ACCESSIONED, so the
        subsequent release MUST be rejected with ERR_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/result_release_requires_specimen_accessioned
        """
        from test_helpers import reject_specimen
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-C10000", date_of_birth="1980-01-01",
        )
        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        # Two specimens to keep order ACCESSIONED after rejecting sp1.
        sp1 = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp2 = create_specimen(actors, order["id"], container_code="RED")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])
        accession_specimen(actors, sp1["id"])
        accession_specimen(actors, sp2["id"])
        run = create_instrument_run(
            actors, sp1["id"], "2026-05-28T08:30:00Z", "2026-05-28T08:40:00Z"
        )
        complete_instrument_run(actors, run["id"])

        # Create the Result while sp1 is ACCESSIONED + run is COMPLETED — POST
        # /results succeeds (run.specimen_id == sp1; specimen+order parent match).
        result = create_result(
            actors, order["id"], sp1["id"], run["id"],
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        # No RELEASED Result on sp1 yet → priority 6 (PRD §3.3) does not block.
        reject_specimen(actors, sp1["id"], reason="HEMOLYZED")
        # sp1 is now REJECTED, sp2 is still ACCESSIONED so order stays ACCESSIONED.

        ord_v = get_lab_order_version(actors, order["id"])
        res = api_client.release_result(
            result["id"], release_result_payload(ord_v), actors.lt_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        # Side effects MUST NOT fire — sp1 stays REJECTED, the result row stays
        # un-RELEASED.
        sp_after = get_success_data(api_client.get_specimen(sp1["id"], actors.lt_headers))
        assert sp_after["status"] == "REJECTED", (
            f"specimen state must persist as REJECTED; got {sp_after['status']!r}"
        )
        res_after = get_success_data(api_client.get_result(result["id"], actors.lt_headers))
        assert res_after["status"] != "RELEASED", (
            f"result must NOT have been RELEASED; got status={res_after['status']!r}"
        )

    def test_release_succeeds_when_specimen_is_accessioned(self, api):
        """PRD §3.5: "Releasing a result transitions it from `PROVISIONAL` to `RELEASED`."
        PRD §3.5: "The specimen named by the result MUST be in `ACCESSIONED` status and the instrument run named by the result MUST be in `COMPLETED` status; otherwise the release is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/result_release_requires_specimen_accessioned
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-C1B000", date_of_birth="1980-01-01",
        )
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        assert bundle["result"]["status"] == "RELEASED", (
            f"result must be RELEASED when specimen ACCESSIONED + run COMPLETED; "
            f"got {bundle['result']['status']!r}"
        )


class TestAcknowledgementRequiresNotificationSent:
    """PRD §3.7: acknowledgement transitions notification from SENT to ACKNOWLEDGED.
    PRD §2.10: state-validity check is priority 4 (above ack rules).
    """

    def test_acknowledge_pending_notification_returns_invalid_state(self, api):
        """PRD §3.7: "Acknowledgement is performed by submitting an attestation,
        which both transitions the notification from `SENT` to `ACKNOWLEDGED` and
        persists an immutable `AcknowledgementReceipt` row."
        PRD §2.10: "and only then state-validity of the targeted entity against §3's
        state machines."

        Design: Difficulty/cross_entity_state_dependency/ack_requires_notification_in_sent_or_escalated
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-C20000", date_of_birth="1970-01-01",
        )
        bundle = setup_pending_critical_notification(actors, patient)
        notif = bundle["notification"]
        assert notif["status"] == "PENDING", (
            f"notification must be PENDING in this fixture; got {notif['status']!r}"
        )

        res = api_client.create_acknowledgement(
            notif["id"],
            create_acknowledgement_payload(
                ack_method="WEB_UI",
                attestation_text="Trying to ack before send.",
            ),
            make_ordering_provider_headers(notif["recipient_clinician_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(
            api_client.get_critical_notification(notif["id"], actors.lt_headers)
        )
        assert after["status"] == "PENDING", (
            f"notification must remain PENDING; got {after['status']!r}"
        )

    def test_acknowledge_sent_notification_succeeds(self, api):
        """PRD §3.7: "Acknowledgement is performed by submitting an attestation, which both transitions the notification from `SENT` to `ACKNOWLEDGED` and persists an immutable `AcknowledgementReceipt` row."

        Design: Difficulty/cross_entity_state_dependency/ack_requires_notification_in_sent_or_escalated
        """
        from test_helpers import acknowledge_notification, setup_sent_critical_notification
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-C2B000", date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]
        receipt = acknowledge_notification(
            actors, notif["id"], recipient_id=notif["recipient_clinician_id"],
            ack_method="WEB_UI", attestation_text="Within window.",
        )
        assert receipt["critical_notification_id"] == notif["id"]
        after = get_success_data(
            api_client.get_critical_notification(notif["id"], actors.lt_headers)
        )
        assert after["status"] == "ACKNOWLEDGED", (
            f"notification must be ACKNOWLEDGED; got {after['status']!r}"
        )
