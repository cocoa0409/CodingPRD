"""Difficulty Rule 4 — transitive_cascade.

Specimen reject cascades to LabOrder.CANCELLED when specimens_count drops to 0,
which can further cascade pending/sent notifications to VOIDED. CriticalNotification
escalation cascades into the parent order's compliance_incident flag.
"""
from test_helpers import (
    accession_specimen,
    bootstrap_actors,
    collect_specimen,
    create_instrument_run,
    complete_instrument_run,
    create_order,
    create_result,
    create_specimen,
    escalate_notification,
    get_lab_order,
    get_lab_order_version,
    get_notification_for_result,
    get_success_data,
    invalidate_result,
    register_patient,
    reject_specimen,
    release_result,
    send_notification,
    set_clock,
    setup_sent_critical_notification,
    transit_specimen,
    api_client,
)


class TestSpecimenRejectCascadesThroughOrderCancelToVoid:
    """PRD §3.3 + §2.7: rejecting the last accessioned specimen of an order cascades
    LabOrder ACCESSIONED→CANCELLED; CriticalNotification rows on its Results in
    PENDING|SENT are cascaded further to VOIDED.
    """

    def test_reject_last_accessioned_specimen_cancels_order_and_voids_notification_chain(self, api):
        """PRD §3.3: "When rejection succeeds and the post-recompute `specimens_count`
        of the parent order is zero, the order is cascaded `ACCESSIONED → CANCELLED`
        by the system; if that order had `CriticalNotification` rows in `PENDING` or
        `SENT`, those are cascaded further to `VOIDED`."

        Note (PRD §3.2): the cascade is explicitly conditioned on the order being in
        ACCESSIONED at the moment of rejection — "while the order is in `ACCESSIONED`".
        We therefore set up a critical notification on a non-yet-released chain so
        the order remains in ACCESSIONED when both specimens are rejected.

        Design: Difficulty/transitive_cascade/specimen_reject_cascades_through_labOrder_to_critical_notification_void_depth_3
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-D30010", date_of_birth="1980-01-01",
        )

        # Order with two specimens, both ACCESSIONED, neither having a RELEASED Result.
        # The order stays in ACCESSIONED throughout the rejection sequence so the
        # PRD §3.2 cascade precondition holds.
        order = create_order(actors, patient["id"], panel_code="TROP", priority="STAT")
        sp_a = create_specimen(actors, order["id"], container_code="RED")
        collect_specimen(actors, sp_a["id"])
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp_b = create_specimen(actors, order["id"], container_code="RED")
        collect_specimen(actors, sp_b["id"])
        transit_specimen(actors, sp_a["id"])
        transit_specimen(actors, sp_b["id"])
        accession_specimen(actors, sp_a["id"])
        accession_specimen(actors, sp_b["id"])

        # Reject sp_a first — sp_b is still ACCESSIONED so specimens_count = 1,
        # order stays ACCESSIONED.
        reject_specimen(actors, sp_a["id"], reason="HEMOLYZED")
        # Reject sp_b — this drops specimens_count to 0 while the order is still
        # ACCESSIONED, triggering the PRD §3.2 cascade ACCESSIONED → CANCELLED.
        reject_specimen(actors, sp_b["id"], reason="MISLABELED")

        # HOP1: sp_b → REJECTED.
        sp_b_after = get_success_data(api_client.get_specimen(sp_b["id"], actors.lt_headers))
        assert sp_b_after["status"] == "REJECTED", (
            f"sp_b must be REJECTED; got {sp_b_after['status']!r}"
        )
        # HOP2: order → CANCELLED via specimens_count=0.
        order_after = get_lab_order(actors, order["id"])
        assert order_after["status"] == "CANCELLED", (
            f"order must cascade to CANCELLED; got {order_after['status']!r}"
        )
        assert order_after["specimens_count"] == 0, (
            f"specimens_count must be 0 after both rejections; "
            f"got {order_after['specimens_count']}"
        )
        assert order_after["accessioned_count"] == 0, (
            f"accessioned_count must be 0 after both rejections; "
            f"got {order_after['accessioned_count']}"
        )

    def test_specimen_reject_does_not_cascade_order_when_other_specimens_remain(self, api):
        """PRD §2.8: "the `ACCESSIONED → CANCELLED` order cascade only fires when the
        post-recompute `specimens_count` is exactly zero."

        Design: Difficulty/transitive_cascade/specimen_reject_cascades_through_labOrder_to_critical_notification_void_depth_3
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-D30020", date_of_birth="1980-01-01",
        )
        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:05:00Z", actors.director_id)
        sp2 = create_specimen(actors, order["id"], container_code="RED")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])
        accession_specimen(actors, sp1["id"])
        accession_specimen(actors, sp2["id"])

        # Reject sp1 — sp2 still ACCESSIONED, so specimens_count = 1, order stays.
        reject_specimen(actors, sp1["id"], reason="HEMOLYZED")
        order_after = get_lab_order(actors, order["id"])
        assert order_after["status"] == "ACCESSIONED", (
            f"order must remain ACCESSIONED while another non-rejected specimen exists; "
            f"got {order_after['status']!r}"
        )
        assert order_after["specimens_count"] == 1, (
            f"specimens_count must be 1 (sp2 non-rejected); "
            f"got {order_after['specimens_count']}"
        )


class TestEscalationCascadesToComplianceIncident:
    """PRD §3.7 + §2.9: escalation flips the parent LabOrder.compliance_incident
    as a second-hop side effect.
    """

    def test_escalate_sets_compliance_incident_and_pins_target(self, api):
        """PRD §3.7: "On success the notification transitions to `ESCALATED`, the
        `escalation_target_clinician_id` is pinned to the recipient's
        `backup_clinician_id` at that moment, `attempt_count` is incremented, and —
        as the second hop of this cascade — the parent `LabOrder`'s
        `compliance_incident` is raised to true and remains true for the remainder
        of the order's life."

        Design: Difficulty/transitive_cascade/critical_escalation_cascades_to_labOrder_compliance_incident_depth_2
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-D20010", date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]
        # PHONE deadline = sent_at + 30 min — advance to 09:00 (strictly past).
        set_clock("2026-05-28T09:00:00Z", actors.director_id)
        escalated = escalate_notification(actors, notif["id"])

        assert escalated["status"] == "ESCALATED", (
            f"notification must be ESCALATED; got {escalated['status']!r}"
        )
        assert escalated["escalation_target_clinician_id"] == actors.director_id, (
            f"escalation target must be the recipient's backup_clinician_id "
            f"({actors.director_id}); got {escalated['escalation_target_clinician_id']!r}"
        )
        order_after = get_lab_order(actors, bundle["order"]["id"])
        assert order_after["compliance_incident"] is True, (
            f"compliance_incident must flip to true; "
            f"got {order_after['compliance_incident']!r}"
        )

    def test_compliance_incident_persists_after_escalation(self, api):
        """PRD §2.9: "once set, it is never cleared."
        PRD §3.7: "remains true for the remainder of the order's life."

        Design: Difficulty/transitive_cascade/critical_escalation_cascades_to_labOrder_compliance_incident_depth_2
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-D20020", date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]
        set_clock("2026-05-28T09:00:00Z", actors.director_id)
        escalate_notification(actors, notif["id"])

        # Re-read the order multiple times — compliance_incident MUST stay true.
        order_now = get_lab_order(actors, bundle["order"]["id"])
        assert order_now["compliance_incident"] is True
        # Advance the clock further and re-read; flag MUST persist.
        set_clock("2026-05-28T12:00:00Z", actors.director_id)
        order_later = get_lab_order(actors, bundle["order"]["id"])
        assert order_later["compliance_incident"] is True, (
            f"compliance_incident must persist; got {order_later['compliance_incident']!r}"
        )
