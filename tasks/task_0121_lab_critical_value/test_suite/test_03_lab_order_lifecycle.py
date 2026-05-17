"""Lab order placement, default priority, cancellation, state guards.

PRD §3.2 fixes order placement and cancellation; PRD §3.8 / §3.2
specify the ORDER_PLACED audit event side effect; PRD §2.13 fixes
validation order.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    anchor_clock,
    assert_lab_order,
    attempt_cancel_order,
    collect_specimen,
    create_catalog_bundle,
    create_lab_order_payload,
    list_audit_for_order,
    make_lab_director_headers,
    make_ordering_provider_headers,
    patch_clinician_payload,
    place_lab_order,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 Placement
# ===========================================================================
class TestLabOrderPlacement:

    def test_place_order_returns_201_with_default_state_and_priority(
        self, api,
    ):
        """PRD §3.2: "On success the new `LabOrder` is persisted with
        `status` set to `ORDERED` (the initial state for every order),
        `retest_count` set to 0, `parent_order_id` set to absent, and
        `ordered_at` set to a snapshot of the server clock at the
        moment of acceptance."

        PRD §3.2: "An `OrderingProvider` places an order by supplying
        a `patient_id`, an `ordering_provider_id`, a `panel_id`, and
        an optional `priority` of `ROUTINE` (default) or `STAT`."

        Claim: a placement returns a LabOrder with status=ORDERED,
        retest_count=0, parent_order_id null, priority default
        ROUTINE.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        op = bundle["ordering_provider"]
        payload = create_lab_order_payload(
            patient_id=bundle["patient"]["id"],
            ordering_provider_id=op["id"],
            panel_id=bundle["panel"]["id"],
        )
        res = api.create_lab_order(
            payload, make_ordering_provider_headers(op["id"]),
        )
        order = validate_success(res, 201)
        assert_lab_order(order)
        assert order["status"] == "ORDERED"
        assert order["retest_count"] == 0
        assert order.get("parent_order_id") is None
        assert order["priority"] == "ROUTINE"

    def test_order_placement_writes_order_placed_audit_event(self, api):
        """PRD §3.2: "A `ComplianceAuditEvent` with `event_type` of
        `ORDER_PLACED` is appended on creation; its `lab_order_id` is
        the new order's id, `actor_id` is the placing provider's id,
        and `payload` carries an event-specific JSON snapshot."

        Claim: an ORDER_PLACED audit event with the order's id is
        listable after placement.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        events = list_audit_for_order(
            bundle, order["id"], event_type="ORDER_PLACED",
        )
        assert any(
            e.get("lab_order_id") == order["id"]
            and e.get("event_type") == "ORDER_PLACED"
            for e in events
        )


# ===========================================================================
# §3.2 Placement preconditions
# ===========================================================================
class TestLabOrderPreconditions:

    def test_inactive_ordering_provider_rejected(self, api):
        """PRD §3.2: "The supplied `ordering_provider_id` must
        reference a `Clinician` whose `role_kind` is
        `ORDERING_PROVIDER` and whose `active` flag is `true`."

        PRD §2.6: "Every clinician participating in a write — the
        `ordering_provider_id` on order placement, the
        `collected_by_id` on specimen collection, the `resulted_by_id`
        on resulting, and the `released_by_id` on release — must have
        `active` equal to `true` on the underlying `Clinician` row. A
        reference to an inactive clinician is rejected with
        `ERR_CLINICIAN_INACTIVE`."

        Claim: POST /lab-orders with INACTIVE ordering provider ->
        ERR_CLINICIAN_INACTIVE.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        op = bundle["ordering_provider"]
        api.patch_clinician(
            op["id"], patch_clinician_payload(active=False),
            make_lab_director_headers(bundle["director"]["id"]),
        )
        payload = create_lab_order_payload(
            patient_id=bundle["patient"]["id"],
            ordering_provider_id=op["id"],
            panel_id=bundle["panel"]["id"],
        )
        res = api.create_lab_order(
            payload, make_ordering_provider_headers(op["id"]),
        )
        validate_error(res, "ERR_CLINICIAN_INACTIVE")


# ===========================================================================
# §3.2 Cancellation
# ===========================================================================
class TestLabOrderCancellation:

    def test_cancel_ordered_succeeds_and_transitions(self, api):
        """PRD §3.2: "An `OrderingProvider` may cancel their own
        `ORDERED` order, optionally supplying `version` for OCC."

        Claim: POST /lab-orders/{id}/cancel on an ORDERED order
        returns 200 and the order's status becomes CANCELED.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        op = bundle["ordering_provider"]
        res = api.cancel_lab_order(
            order["id"], make_ordering_provider_headers(op["id"]),
        )
        canceled = validate_success(res, 200)
        assert canceled["status"] == "CANCELED"

    def test_cancel_after_collection_rejected(self, api):
        """PRD §3.2: "Cancellation is permitted only while the order
        remains in `ORDERED`; any later state — `COLLECTED`,
        `IN_TRANSIT`, `RECEIVED`, `RESULTED`, `RELEASED`, `CANCELED`,
        or `REJECTED` — yields the standard state-violation
        rejection."

        Claim: cancel after collection -> ERR_INVALID_STATE.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        collect_specimen(bundle, order)
        res = attempt_cancel_order(bundle, order)
        validate_error(res, "ERR_INVALID_STATE")

    def test_cancel_nonexistent_order_returns_not_found(self, api):
        """PRD §2.5: "the first segment that fails to resolve to a
        live row terminates the request with `ERR_NOT_FOUND`."

        Claim: POST /lab-orders/{unknown}/cancel -> ERR_NOT_FOUND.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op = bundle["ordering_provider"]
        res = api.cancel_lab_order(
            NON_EXISTENT_UUID,
            make_ordering_provider_headers(op["id"]),
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_cancel_by_other_provider_rejected(self, api):
        """PRD §3.2: "The actor's id (the value of `X-User-ID`) must
        equal the order's `ordering_provider_id`; otherwise the
        request is rejected on the role-permission rule."

        Claim: cancel by a different OrderingProvider returns
        ERR_FORBIDDEN.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_ordering_provider=True,
        )
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        other_op = bundle["ordering_provider2"]
        res = api.cancel_lab_order(
            order["id"],
            make_ordering_provider_headers(other_op["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")
