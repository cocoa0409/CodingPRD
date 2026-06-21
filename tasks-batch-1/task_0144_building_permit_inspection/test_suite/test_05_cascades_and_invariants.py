"""Cascades and conserved quantities: the stop-work depth-3 cascade
(work_status -> inspection cancel -> slot capacity freed), the FINAL-pass
depth-2 cascade (inspection PASSED -> CofO created), the schedule/cancel slot
occupancy invariant, the issue/revoke certificate-count invariant, and the
stop-work CofO-revocation compensation.

PRD §2.7 (cascades), §3.7-§3.9 (inspections, stop-work, revocation).
"""
from test_helpers import (
    api_client,
    validate_success,
    create_issued_permit_with_scheduled_rough,
    create_issued_permit_with_passed_rough,
    create_permit_with_certificate,
    schedule_inspection,
    issue_stop_work,
    make_applicant_headers,
    make_inspector_headers,
    make_official_headers,
)


class TestStopWorkCascade:
    def test_stop_work_cancels_inspection_and_frees_slot(self, api):
        """PRD §3.9: "Posting the order creates a `StopWorkOrder` with
        `order_status` `ACTIVE`, drives the permit's `work_status` from `ACTIVE`
        to `STOPPED`, cancels every inspection for the permit still in `SCHEDULED`
        status — each cancellation freeing its slot's capacity".

        Design: Difficulty/transitive_cascade/stop_work_cancels_inspection_frees_slot_depth3
        """
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=2, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        issue_stop_work(issued["id"])
        permit_read = validate_success(api.get_permit(issued["id"], make_official_headers()))
        assert permit_read["work_status"] == "STOPPED"
        insp_read = validate_success(api.get_inspection(rough["id"], make_applicant_headers()))
        assert insp_read["inspection_status"] == "CANCELLED"
        slot_read = validate_success(api.get_slot(slot["id"], make_official_headers()))
        assert slot_read["booked_count"] == 0

    def test_stop_work_cancellation_frees_slot_to_zero(self, api):
        """PRD §2.7: "When a permit expires or a stop-work order is posted, every
        still-scheduled inspection for that permit is cancelled, and each
        cancellation frees the capacity it had consumed on its inspection slot."

        Design: Difficulty/transitive_cascade/stop_work_cancels_inspection_frees_slot_depth3
        """
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=2, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        slot_before = validate_success(api.get_slot(slot["id"], make_official_headers()))
        assert slot_before["booked_count"] == 1
        issue_stop_work(issued["id"])
        slot_after = validate_success(api.get_slot(slot["id"], make_official_headers()))
        assert slot_after["booked_count"] == 0


class TestFinalPassCreatesCertificate:
    def test_final_pass_sets_passed(self, api):
        """PRD §3.8: "On a `PASS` outcome, the inspection's `inspection_status`
        becomes `PASSED` and an `INSPECTION_PASSED` audit event is appended."

        Design: Difficulty/transitive_cascade/final_pass_creates_certificate_depth2
        """
        issued, reviewer, inspector, slot, rough_passed = (
            create_issued_permit_with_passed_rough(
                max_inspections=5, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        final = schedule_inspection(issued["id"], slot["id"], "FINAL",
                                    "2026-07-01T11:00:00Z", "2026-07-01T12:00:00Z")
        resp = api.record_inspection_result(
            final["id"], {"outcome": "PASS"}, make_inspector_headers(inspector["id"]))
        data = validate_success(resp)
        assert data["inspection_status"] == "PASSED"

    def test_final_pass_cascades_issued_certificate(self, api):
        """PRD §3.8: "When a `FINAL` inspection passes, the system cascades the
        creation of a `CertificateOfOccupancy`: the new certificate records the
        `permit_id`, sets its `final_inspection_id` to the passing inspection,
        takes `co_type` `FINAL` and `co_status` `ISSUED`".

        Design: Difficulty/transitive_cascade/final_pass_creates_certificate_depth2
        """
        issued, reviewer, inspector, slot, rough_passed = (
            create_issued_permit_with_passed_rough(
                max_inspections=5, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        final = schedule_inspection(issued["id"], slot["id"], "FINAL",
                                    "2026-07-01T11:00:00Z", "2026-07-01T12:00:00Z")
        validate_success(api.record_inspection_result(
            final["id"], {"outcome": "PASS"}, make_inspector_headers(inspector["id"])))
        certs, _meta = _certs_for_permit(api, issued["id"])
        issued_certs = [c for c in certs
                        if c["co_status"] == "ISSUED" and c["final_inspection_id"] == final["id"]]
        assert len(issued_certs) == 1, f"expected exactly one ISSUED CofO, got {len(issued_certs)}"


class TestSlotOccupancyInvariant:
    def test_schedule_then_cancel_returns_booked_count(self, api):
        """PRD §3.7: "Cancellation sets `inspection_status` to `CANCELLED` and
        decrements the slot's `booked_count`, returning the slot to the capacity
        it had before the booking".

        Design: Difficulty/compensating_invariant/slot_booked_count_conserved_schedule_then_cancel
        """
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=3, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        resp = api.cancel_inspection(rough["id"], make_applicant_headers())
        data = validate_success(resp)
        assert data["inspection_status"] == "CANCELLED"
        slot_read = validate_success(api.get_slot(slot["id"], make_official_headers()))
        assert slot_read["booked_count"] == 0

    def test_cancelled_inspection_not_counted_in_booked(self, api):
        """PRD §3.7: "A `CANCELLED` inspection does not count toward the booked
        count, which is how a cancellation frees capacity."

        Design: Difficulty/compensating_invariant/slot_booked_count_conserved_schedule_then_cancel
        """
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=3, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        validate_success(api.cancel_inspection(rough["id"], make_applicant_headers()))
        slot_read = validate_success(api.get_slot(slot["id"], make_official_headers()))
        assert slot_read["booked_count"] == 0


class TestCertificateCountInvariant:
    def test_revoke_certificate_sets_revoked(self, api):
        """PRD §3.9: "revocation is permitted only while the certificate's
        `co_status` is `ISSUED`, sets it to `REVOKED`, and appends a `CO_REVOKED`
        audit event."

        Design: Difficulty/compensating_invariant/active_certificate_count_conserved_issue_then_revoke
        """
        issued, reviewer, inspector, slot, final_passed, cert = create_permit_with_certificate(
            max_inspections=5, work_class="REPAIR",
            fee_method="VALUATION", declared_valuation=2000)
        assert cert is not None and cert["co_status"] == "ISSUED"
        resp = api.revoke_certificate(cert["id"], make_official_headers())
        data = validate_success(resp)
        assert data["co_status"] == "REVOKED"

    def test_issued_certificate_count_returns_to_zero_after_revoke(self, api):
        """PRD §3.8: "the new certificate records the `permit_id`, sets its
        `final_inspection_id` to the passing inspection, takes `co_type` `FINAL`
        and `co_status` `ISSUED`, and its creation appends a `CO_ISSUED` audit event."
        PRD §3.9: "revocation is permitted only while the certificate's `co_status`
        is `ISSUED`, sets it to `REVOKED`, and appends a `CO_REVOKED` audit event."

        Design: Difficulty/compensating_invariant/active_certificate_count_conserved_issue_then_revoke
        """
        issued, reviewer, inspector, slot, final_passed, cert = create_permit_with_certificate(
            max_inspections=5, work_class="REPAIR",
            fee_method="VALUATION", declared_valuation=2000)
        certs_before, _ = _certs_for_permit(api, issued["id"])
        assert len([c for c in certs_before if c["co_status"] == "ISSUED"]) == 1
        validate_success(api.revoke_certificate(cert["id"], make_official_headers()))
        certs_after, _ = _certs_for_permit(api, issued["id"])
        assert len([c for c in certs_after if c["co_status"] == "ISSUED"]) == 0


class TestStopWorkRevokesCertificate:
    def test_stop_work_revokes_issued_certificate_and_stops_work(self, api):
        """PRD §3.9: "Posting the order creates a `StopWorkOrder` with
        `order_status` `ACTIVE`, drives the permit's `work_status` from `ACTIVE`
        to `STOPPED`, cancels every inspection for the permit still in `SCHEDULED`
        status — each cancellation freeing its slot's capacity — revokes any
        standing certificate of occupancy for the permit (its `co_status` moving
        from `ISSUED` to `REVOKED`, with a `CO_REVOKED` audit event), and appends
        a `STOP_WORK_ISSUED` audit event."

        Design: Corner/state_machines/stop_work_revokes_issued_certificate_cascade
        """
        issued, reviewer, inspector, slot, final_passed, cert = create_permit_with_certificate(
            max_inspections=5, work_class="REPAIR",
            fee_method="VALUATION", declared_valuation=2000)
        issue_stop_work(issued["id"], reason="Post-CO violation found")
        cert_read = validate_success(api.get_certificate(cert["id"], make_official_headers()))
        assert cert_read["co_status"] == "REVOKED"
        permit_read = validate_success(api.get_permit(issued["id"], make_official_headers()))
        assert permit_read["work_status"] == "STOPPED"


# ─── local helpers ─────────────────────────────────────
def _certs_for_permit(api, permit_id):
    resp = api.list_certificates(make_official_headers(), params={"permit_id": permit_id})
    body = resp.json()
    return body.get("data", []), body.get("meta", {})
