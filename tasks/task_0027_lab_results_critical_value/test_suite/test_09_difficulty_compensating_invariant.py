"""Difficulty Rule 9 — compensating_invariant.

LabOrder.accessioned_count is conserved: +1 on accession, −1 on reject of an
ACCESSIONED specimen. Patient.results_release_count is conserved: +1 on release,
−1 on invalidate (amend is net zero).
"""
from test_helpers import (
    accession_specimen,
    api_client,
    bootstrap_actors,
    collect_specimen,
    complete_instrument_run,
    create_instrument_run,
    create_order,
    create_result,
    create_specimen,
    get_lab_order,
    get_lab_order_version,
    get_success_data,
    invalidate_result,
    register_patient,
    reject_specimen,
    release_result,
    setup_released_result,
    transit_specimen,
)


class TestAccessionedCountConservedAcrossAccessionThenReject:
    """PRD §2.8: LabOrder.accessioned_count = count of ACCESSIONED specimens,
    recomputed after every specimen-state transition.
    """

    def test_accession_then_reject_returns_accessioned_count_to_zero(self, api):
        """PRD §2.8: "`LabOrder.accessioned_count` is the number whose `status` is
        `ACCESSIONED`. Both are recomputed after every specimen-state transition,
        before any cascade reads them."

        Design: Difficulty/compensating_invariant/order_accessioned_count_conserved_under_accession_then_reject
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", with_instrument=False)
        patient = register_patient(
            actors.lt_id, mrn="MRN-I10000", date_of_birth="1980-01-01",
        )

        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp1 = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        from test_helpers import set_clock
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp2 = create_specimen(actors, order["id"], container_code="RED")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])

        # Initial state: no accessions yet.
        before = get_lab_order(actors, order["id"])
        assert before["accessioned_count"] == 0, (
            f"accessioned_count must start at 0; got {before['accessioned_count']}"
        )

        # Accession sp1: +1.
        accession_specimen(actors, sp1["id"])
        mid = get_lab_order(actors, order["id"])
        assert mid["accessioned_count"] == 1, (
            f"accessioned_count must be 1 after accessioning sp1; "
            f"got {mid['accessioned_count']}"
        )

        # Reject sp1 (previously ACCESSIONED): -1.
        reject_specimen(actors, sp1["id"], reason="HEMOLYZED")
        after = get_lab_order(actors, order["id"])
        assert after["accessioned_count"] == 0, (
            f"accessioned_count must return to 0 after reject of ACCESSIONED sp1; "
            f"got {after['accessioned_count']}"
        )
        # sp2 never reached ACCESSIONED, so the recomputed value MUST match
        # count(specimens where status == ACCESSIONED) which is 0.

    def test_accessioned_count_matches_current_specimen_states(self, api):
        """PRD §2.8: "`LabOrder.accessioned_count` is the number whose `status` is `ACCESSIONED`. Both are recomputed after every specimen-state transition, before any cascade reads them."

        Design: Difficulty/compensating_invariant/order_accessioned_count_conserved_under_accession_then_reject
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", with_instrument=False)
        patient = register_patient(
            actors.lt_id, mrn="MRN-I1B000", date_of_birth="1980-01-01",
        )
        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        from test_helpers import set_clock
        sp1 = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp1["id"])
        set_clock("2026-05-28T08:10:00Z", actors.director_id)
        sp2 = create_specimen(actors, order["id"], container_code="RED")
        collect_specimen(actors, sp2["id"])
        transit_specimen(actors, sp1["id"])
        transit_specimen(actors, sp2["id"])
        accession_specimen(actors, sp1["id"])
        accession_specimen(actors, sp2["id"])

        # Both ACCESSIONED → accessioned_count == 2.
        snap = get_lab_order(actors, order["id"])
        assert snap["accessioned_count"] == 2, (
            f"accessioned_count must equal current count of ACCESSIONED specimens "
            f"(2); got {snap['accessioned_count']}"
        )


class TestResultsReleaseCountConservedAcrossReleaseThenInvalidate:
    """PRD §2.8: Patient.results_release_count is conserved across release (+1)
    and invalidate (−1).
    """

    def test_release_then_invalidate_returns_count_to_zero(self, api):
        """PRD §2.8: "Across the lifetime of a patient, the sum of all increments
        (`+1` per release) and decrements (`−1` per invalidation) MUST equal the count
        of currently-released rows for that patient."

        Design: Difficulty/compensating_invariant/patient_results_release_count_conserved_under_release_then_invalidate
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-I20000", date_of_birth="1980-01-01",
        )

        # Initial count is 0.
        before = get_success_data(api_client.get_patient(patient["id"], actors.lt_headers))
        assert before["results_release_count"] == 0, (
            f"results_release_count must start at 0; got {before['results_release_count']}"
        )

        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        # After release: +1.
        mid = get_success_data(api_client.get_patient(patient["id"], actors.lt_headers))
        assert mid["results_release_count"] == 1, (
            f"results_release_count must be 1 after first release; "
            f"got {mid['results_release_count']}"
        )

        # Invalidate: -1.
        invalidate_result(actors, bundle["result"]["id"])
        after = get_success_data(api_client.get_patient(patient["id"], actors.lt_headers))
        assert after["results_release_count"] == 0, (
            f"results_release_count must return to 0 after invalidate; "
            f"got {after['results_release_count']}"
        )

    def test_invalidate_voids_pending_or_sent_critical_notification(self, api):
        """PRD §3.8: "On success the patient's `results_release_count` is decremented
        by one, and any `CriticalNotification` on the result in `PENDING` or `SENT`
        is voided."

        Design: Difficulty/compensating_invariant/patient_results_release_count_conserved_under_release_then_invalidate
        """
        from test_helpers import setup_sent_critical_notification
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-I2B000", date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]

        invalidate_result(actors, bundle["result"]["id"])
        # Result count drops back to 0.
        pat_after = get_success_data(api_client.get_patient(patient["id"], actors.lt_headers))
        assert pat_after["results_release_count"] == 0, (
            f"results_release_count must drop by 1 after invalidate; "
            f"got {pat_after['results_release_count']}"
        )
        # Notification (was SENT) MUST cascade to VOIDED.
        notif_after = get_success_data(
            api_client.get_critical_notification(notif["id"], actors.lt_headers)
        )
        assert notif_after["status"] == "VOIDED", (
            f"SENT notification on invalidated result must be VOIDED; "
            f"got {notif_after['status']!r}"
        )
