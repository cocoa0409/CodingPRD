"""RetestRequest lifecycle and compliance audit conservation.

PRD §3.7 fixes retest behavior; PRD §3.8 fixes the audit log; the
difficulty design includes the cancel-cascade conservation invariant
on active orders per patient.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    LAB_LOCATION_CODE,
    anchor_clock,
    attempt_cancel_retest,
    collect_specimen,
    create_catalog_bundle,
    iso_anchor_offset,
    list_audit_for_order,
    list_orders_for_patient,
    list_retests_for_order,
    make_lab_tech_headers,
    make_ordering_provider_headers,
    open_transport_leg,
    place_lab_order,
    reget_lab_order,
    reget_retest,
    setup_in_transit_for_break,
    setup_patient_with_three_ordered,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 Retest cancellation
# ===========================================================================
class TestRetestCancellation:

    def test_cancel_issued_retest_with_ordered_replacement_cascades(
        self, api,
    ):
        """PRD §3.7: "Before that happens, an `OrderingProvider` may
        cancel an `ISSUED` retest provided the actor's id equals the
        original order's `ordering_provider_id` and the replacement
        order is either absent or still in `ORDERED`; the retest's
        `status` transitions to `CANCELED`, and when the replacement
        order is present and still in `ORDERED`, that replacement
        order is itself transitioned to `CANCELED` as part of the
        same operation."

        Claim: POST /retest-requests/{id}/cancel after a report-break
        cascade sets the RetestRequest to CANCELED AND its replacement
        LabOrder to CANCELED.

        # difficulty: compensating_invariant/cancel_retest_invariant_total_active_orders_per_patient
        """
        ctx = setup_in_transit_for_break()
        bundle = ctx["bundle"]
        leg = ctx["leg"]
        order = ctx["order"]
        tech = bundle["lab_tech"]
        api.report_break_transport_leg(
            leg["id"], make_lab_tech_headers(tech["id"]),
        )
        retests = list_retests_for_order(bundle, order["id"])
        rr = next(r for r in retests
                  if r["reason"] == "SPECIMEN_REJECTED")
        new_order_id = rr["new_lab_order_id"]
        assert rr["status"] == "ISSUED"
        res = attempt_cancel_retest(bundle, rr)
        validate_success(res, 200)
        rr_after = reget_retest(bundle, rr["id"])
        assert rr_after["status"] == "CANCELED"
        new_order = reget_lab_order(bundle, new_order_id)
        assert new_order["status"] == "CANCELED"

    def test_cancel_retest_active_order_conservation(self, api):
        """PRD §3.2: "Cancellation is permitted only while the order
        remains in `ORDERED`; any later state — `COLLECTED`,
        `IN_TRANSIT`, `RECEIVED`, `RESULTED`, `RELEASED`, `CANCELED`,
        or `REJECTED` — yields the standard state-violation
        rejection."
        PRD §3.7: "when the replacement order is present and still
        in `ORDERED`, that replacement order is itself transitioned
        to `CANCELED` as part of the same operation."

        Claim: starting from a patient with 3 ORDERED LabOrders,
        report-breaking the first cascades to REJECTED + replacement
        ORDERED, leaving the count of non-terminal orders at 3;
        cancelling the retest then cancels the replacement, dropping
        the count to 2. Conservation: active_count_after_cancel ==
        active_count_before_cascade - 1.

        # difficulty: compensating_invariant/cancel_retest_invariant_total_active_orders_per_patient
        """
        ctx = setup_patient_with_three_ordered()
        bundle = ctx["bundle"]
        o1, o2, o3 = ctx["orders"]
        patient_id = bundle["patient"]["id"]
        spec1 = collect_specimen(bundle, o1)
        leg1 = open_transport_leg(
            bundle, spec1,
            from_location="CLINIC_A", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=0),
        )
        tech = bundle["lab_tech"]
        api.report_break_transport_leg(
            leg1["id"], make_lab_tech_headers(tech["id"]),
        )
        retests = list_retests_for_order(bundle, o1["id"])
        rr1 = next(r for r in retests
                   if r["reason"] == "SPECIMEN_REJECTED")
        all_orders = list_orders_for_patient(bundle, patient_id)
        non_terminal = [
            o for o in all_orders
            if o["status"] not in
            ("CANCELED", "RELEASED", "REJECTED")
        ]
        assert len(non_terminal) == 3
        attempt_cancel_retest(bundle, rr1)
        all_orders_after = list_orders_for_patient(bundle, patient_id)
        non_terminal_after = [
            o for o in all_orders_after
            if o["status"] not in
            ("CANCELED", "RELEASED", "REJECTED")
        ]
        assert len(non_terminal_after) == 2


# ===========================================================================
# §3.8 Compliance audit reads
# ===========================================================================
class TestComplianceAuditAccess:

    def test_audit_events_listable_by_lab_order_id(self, api):
        """PRD §3.8: "A `LabDirector` may list audit events with
        optional `lab_order_id` and `event_type` filters."

        Claim: GET /audit-events?lab_order_id={id} returns events
        scoped to that order.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        events = list_audit_for_order(bundle, order["id"])
        assert any(
            e["event_type"] == "ORDER_PLACED"
            and e.get("lab_order_id") == order["id"]
            for e in events
        )

    def test_audit_event_actor_id_is_clinician_or_system(self, api):
        """PRD §2.11: "When the sweep performs a state transition,
        the `actor_id` recorded on the resulting
        `ComplianceAuditEvent` is the literal string `\"system\"`
        rather than a `Clinician.id`."

        Claim: ORDER_PLACED (human-triggered) carries actor_id =
        Clinician.id of the placing OrderingProvider, not 'system'.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        events = list_audit_for_order(
            bundle, order["id"], event_type="ORDER_PLACED",
        )
        assert events
        e = events[0]
        assert e["actor_id"] != "system"
        assert e["actor_id"] == bundle["ordering_provider"]["id"]

    def test_ordering_provider_cannot_read_audit_log(self, api):
        """PRD §2.1: "When the headers are present but the declared
        role is not permitted to invoke the requested endpoint, the
        request is rejected with `ERR_FORBIDDEN`."

        Claim: OrderingProvider GET /audit-events -> ERR_FORBIDDEN
        (PRD §4 restricts the endpoint to LabDirector).
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op = bundle["ordering_provider"]
        res = api.list_audit_events(
            make_ordering_provider_headers(op["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")
