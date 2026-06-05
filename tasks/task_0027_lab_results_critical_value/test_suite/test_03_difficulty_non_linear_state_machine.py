"""Difficulty Rule 3 — non_linear_state_machine.

Result has a cyclic-with-shadow shape (RELEASED → AMENDED creates a fresh
RELEASED descendant with a self-referential FK). CriticalNotification branches
from SENT into two divergent terminals (ACKNOWLEDGED with a receipt, or
ESCALATED with a compliance_incident side-effect).
"""
from test_helpers import (
    acknowledge_notification,
    amend_result,
    bootstrap_actors,
    escalate_notification,
    get_lab_order,
    get_notification_for_result,
    register_patient,
    set_clock,
    setup_released_result,
    setup_sent_critical_notification,
)


class TestResultAmendmentCreatesShadowChain:
    """PRD §3.8: amend marks the old row AMENDED and inserts a new RELEASED row
    pointing back via amended_from_result_id.
    """

    def test_amend_marks_old_row_amended_and_new_row_released_with_back_pointer(self, api):
        """PRD §3.8: "the existing row is marked `AMENDED` (preserved for the audit
        trail) and a new row is inserted in `RELEASED` status, identical to the prior
        row in `lab_order_id`, `specimen_id`, and `run_id`, with `amended_from_result_id`
        pointing back to the prior row"

        Design: Difficulty/non_linear_state_machine/result_amendment_cycle_released_amended_released_chain
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-Y00100", date_of_birth="1980-01-01",
        )
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        old_result = bundle["result"]
        # Amend with a new numeric_value.
        new_result = amend_result(actors, old_result["id"], old_result["version"], 4.80)

        # New row asserts.
        assert new_result["status"] == "RELEASED", (
            f"new amended row must be RELEASED; got {new_result['status']!r}"
        )
        assert new_result["amended_from_result_id"] == old_result["id"], (
            f"amended_from_result_id must point back to {old_result['id']}; "
            f"got {new_result.get('amended_from_result_id')!r}"
        )
        assert new_result["numeric_value"] == 4.80, (
            f"new numeric_value must be 4.80; got {new_result['numeric_value']!r}"
        )
        assert new_result["lab_order_id"] == old_result["lab_order_id"]
        assert new_result["specimen_id"] == old_result["specimen_id"]
        assert new_result["run_id"] == old_result["run_id"]

        # Old row asserts — fetch its current state.
        from test_helpers import api_client, get_success_data
        fetched_old = get_success_data(
            api_client.get_result(old_result["id"], actors.lt_headers)
        )
        assert fetched_old["status"] == "AMENDED", (
            f"old row must transition to AMENDED; got {fetched_old['status']!r}"
        )

    def test_amend_preserves_patient_release_count_net_zero(self, api):
        """PRD §3.8: "The patient's `results_release_count` does not change on amendment
        — the old row leaves `RELEASED` (entering `AMENDED`) at the same time the new
        row enters `RELEASED`, for a net zero."

        Design: Difficulty/non_linear_state_machine/result_amendment_cycle_released_amended_released_chain
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-Y00200", date_of_birth="1980-01-01",
        )
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        # After first release: results_release_count must be 1.
        from test_helpers import api_client, get_success_data
        pat_after_release = get_success_data(
            api_client.get_patient(patient["id"], actors.lt_headers)
        )
        assert pat_after_release["results_release_count"] == 1, (
            f"results_release_count must be 1 after first release; "
            f"got {pat_after_release['results_release_count']}"
        )

        amend_result(actors, bundle["result"]["id"], bundle["result"]["version"], 4.80)
        pat_after_amend = get_success_data(
            api_client.get_patient(patient["id"], actors.lt_headers)
        )
        assert pat_after_amend["results_release_count"] == 1, (
            f"results_release_count must remain 1 after amendment (net zero); "
            f"got {pat_after_amend['results_release_count']}"
        )


class TestCriticalNotificationBranchesFromSentToAcknowledgedOrEscalated:
    """PRD §3.7: from SENT a notification can transition either to ACKNOWLEDGED
    (creating an AcknowledgementReceipt, no compliance flip) or to ESCALATED
    (pinning escalation_target_clinician_id and raising the parent order's
    compliance_incident flag).
    """

    def test_acknowledged_branch_creates_receipt_and_leaves_compliance_false(self, api):
        """PRD §3.7: "Acknowledgement is performed by submitting an attestation,
        which both transitions the notification from `SENT` to `ACKNOWLEDGED` and
        persists an immutable `AcknowledgementReceipt` row."
        PRD §2.9: "when a notification is escalated from `SENT` to `ESCALATED`, the
        parent order's `compliance_incident` flag is raised as a second-hop side
        effect"

        Design: Difficulty/non_linear_state_machine/critical_notification_branching_sent_to_ack_or_escalate_with_different_side_effects
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-BR0010", full_name="Br A",
            date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]
        # PHONE deadline = sent_at + 30 min. Acknowledge well within the window.
        set_clock("2026-05-28T08:20:00Z", actors.director_id)
        receipt = acknowledge_notification(
            actors,
            notif["id"],
            recipient_id=notif["recipient_clinician_id"],
            ack_method="IVR_KEYPRESS",
            attestation_text="Reviewed and acknowledged.",
        )

        # Receipt is created with the expected fields.
        assert receipt["critical_notification_id"] == notif["id"]
        assert receipt["acknowledging_clinician_id"] == notif["recipient_clinician_id"]
        assert receipt["ack_method"] == "IVR_KEYPRESS"

        # Notification → ACKNOWLEDGED.
        from test_helpers import api_client, get_success_data
        notif_after = get_success_data(
            api_client.get_critical_notification(notif["id"], actors.lt_headers)
        )
        assert notif_after["status"] == "ACKNOWLEDGED", (
            f"notification must be ACKNOWLEDGED; got {notif_after['status']!r}"
        )
        # Order compliance_incident must remain FALSE (no escalation occurred).
        order_after = get_lab_order(actors, bundle["order"]["id"])
        assert order_after["compliance_incident"] is False, (
            f"compliance_incident must remain false after ack branch; "
            f"got {order_after['compliance_incident']!r}"
        )

    def test_escalated_branch_pins_target_and_flips_compliance_to_true(self, api):
        """PRD §3.7: "On success the notification transitions to `ESCALATED`, the
        `escalation_target_clinician_id` is pinned to the recipient's
        `backup_clinician_id` at that moment, `attempt_count` is incremented, and —
        as the second hop of this cascade — the parent `LabOrder`'s
        `compliance_incident` is raised to true and remains true for the remainder
        of the order's life."

        Design: Difficulty/non_linear_state_machine/critical_notification_branching_sent_to_ack_or_escalate_with_different_side_effects
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-BR0020", full_name="Br B",
            date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]
        # PHONE deadline = sent_at + 30 min. Advance clock past deadline.
        set_clock("2026-05-28T08:45:00Z", actors.director_id)
        escalated = escalate_notification(actors, notif["id"])

        assert escalated["status"] == "ESCALATED", (
            f"notification must be ESCALATED; got {escalated['status']!r}"
        )
        # The escalation target equals the recipient's backup_clinician_id —
        # which in our bootstrap is the LabDirector's id (PRD §3.1 / §3.7).
        assert escalated["escalation_target_clinician_id"] == actors.director_id, (
            f"escalation_target_clinician_id must equal recipient's "
            f"backup_clinician_id ({actors.director_id}); "
            f"got {escalated['escalation_target_clinician_id']!r}"
        )

        order_after = get_lab_order(actors, bundle["order"]["id"])
        assert order_after["compliance_incident"] is True, (
            f"compliance_incident must flip to true on escalation; "
            f"got {order_after['compliance_incident']!r}"
        )
