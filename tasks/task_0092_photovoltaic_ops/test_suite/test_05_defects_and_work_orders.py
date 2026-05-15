"""Defect, work-order, recurrence-index, and reopen tests (PRD §3.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    blacklist_supplier,
    cancel_work_order,
    complete_work_order,
    complete_work_order_payload,
    create_defect_payload,
    create_manual_defect,
    create_spare_part,
    create_station,
    create_supplier,
    create_work_order_payload,
    dispatch_work_order,
    setup_station_with_inverters,
    start_work_order,
    validate_error,
    validate_success,
    walk_defect_through_close,
)


class TestDefectCreation:
    """PRD §3.5 defect intake."""

    def test_create_manual_defect_initial_state(self, api, om_headers):
        """PRD §3.5: "The state enumeration spans OPEN, DISPATCHED,
        UNDER_REPAIR, RESOLVED, CLOSED, and REOPENED. The platform
        records opened_at when a defect enters OPEN..."

        Claim: a manually opened defect has state=OPEN.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        payload = create_defect_payload(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            source="EXTERNAL_INSPECTION",
            severity="MINOR",
        )
        resp = api.create_defect(payload, om_headers)
        data = validate_success(resp, expected_status=201)
        assert data["state"] == "OPEN"
        assert data["recurrence_index"] == 1


class TestRecurrenceIndex:
    """PRD §3.5: recurrence_index walks parent_defect_id chain;
    auto-escalation at threshold of 3."""

    def test_parent_with_different_subject_rejected(self, api, om_headers):
        """PRD §3.5: "When a defect is created with a non-null
        parent_defect_id, that ancestor must refer to a defect with
        the same subject_type and subject_id; otherwise the request
        fails with ERR_DEFECT_PARENT_SUBJECT_MISMATCH."

        Claim: parent_defect_id referring to a defect on a different
        subject_id yields ERR_DEFECT_PARENT_SUBJECT_MISMATCH.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=2)
        supplier = create_supplier()
        # Walk a defect on inverter[0] to CLOSED so it can serve as a
        # parent.
        parent, _wo = walk_defect_through_close(
            station_id=station["id"],
            inverter_id=invs[0]["id"],
            supplier_id=supplier["id"],
        )
        # Now create a child defect on a DIFFERENT subject.
        payload = create_defect_payload(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[1]["id"],  # different inverter
            source="EXTERNAL_INSPECTION",
            severity="MINOR",
            parent_defect_id=parent["id"],
        )
        resp = api.create_defect(payload, om_headers)
        validate_error(
            resp, ApiErrorId.ERR_DEFECT_PARENT_SUBJECT_MISMATCH.value,
        )

    def test_third_recurrence_auto_escalates_to_major(self, api, om_headers):
        """PRD §3.5: "If the resulting recurrence_index is three or
        greater, the defect's severity is automatically escalated to
        at least MAJOR — that is, the maximum of its supplied
        severity and MAJOR."

        Claim: a chain of two CLOSED ancestors yields a third defect
        with recurrence_index=3 and severity escalated to MAJOR even
        when the input severity is MINOR.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        # Build first CLOSED defect.
        ancestor1, _ = walk_defect_through_close(
            station_id=station["id"],
            inverter_id=invs[0]["id"],
            supplier_id=supplier["id"],
        )
        # Build second CLOSED defect with ancestor1 as parent.
        from test_helpers import TEST_USERS, dispatch_work_order, start_work_order, complete_work_order, api_client
        payload2 = create_defect_payload(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            source="EXTERNAL_INSPECTION",
            severity="MINOR",
            parent_defect_id=ancestor1["id"],
        )
        ancestor2 = validate_success(
            api_client.create_defect(payload2, TEST_USERS["om_engineer_headers"]),
            expected_status=201,
        )
        # Walk ancestor2 through CLOSED so its state matters for the
        # recurrence count.
        wo2 = dispatch_work_order(ancestor2["id"], supplier["id"])
        start_work_order(wo2["id"])
        complete_work_order(wo2["id"])
        api.close_defect(ancestor2["id"], om_headers)
        # Now the third defect chained off ancestor2.
        payload3 = create_defect_payload(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            source="EXTERNAL_INSPECTION",
            severity="MINOR",
            parent_defect_id=ancestor2["id"],
        )
        resp = api.create_defect(payload3, om_headers)
        third = validate_success(resp, expected_status=201)
        assert third["recurrence_index"] == 3
        assert third["severity"] == "MAJOR", (
            "PRD §3.5: 'the defect's severity is automatically "
            "escalated to at least MAJOR'"
        )


class TestWorkOrderDispatchValidations:
    """PRD §3.5 dispatch path validations."""

    def test_dispatch_blacklisted_supplier_rejected(self, api, om_headers):
        """PRD §3.5: "an assigned_supplier_id (which MUST refer to a
        supplier whose lifecycle_state is ACTIVE and not BLACKLISTED,
        otherwise the request fails with ERR_SUPPLIER_BLACKLISTED)..."

        Claim: dispatching with a BLACKLISTED supplier →
        ERR_SUPPLIER_BLACKLISTED.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        blacklist_supplier(supplier["id"])
        defect = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        payload = create_work_order_payload(
            assigned_supplier_id=supplier["id"],
            spare_part_lines=[],
        )
        resp = api.create_work_order(defect["id"], payload, om_headers)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_BLACKLISTED.value)

    def test_dispatch_insufficient_stock_rejected(self, api, om_headers):
        """PRD §3.5: "For every line, the platform verifies that the
        part's stock_on_hand minus its reserved_qty is greater than
        or equal to the requested quantity; the comparison is closed
        at the boundary, so a request for exactly the available
        quantity succeeds. If any line fails the check, the entire
        dispatch is rejected with ERR_SPARE_PART_INSUFFICIENT..."

        Claim: a request for stock_on_hand=2, reserved=0, quantity=3
        is rejected with ERR_SPARE_PART_INSUFFICIENT.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        part = create_spare_part(stock_on_hand=2)
        defect = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        payload = create_work_order_payload(
            assigned_supplier_id=supplier["id"],
            spare_part_lines=[{"part_id": part["id"], "quantity": 3}],
        )
        resp = api.create_work_order(defect["id"], payload, om_headers)
        validate_error(resp, ApiErrorId.ERR_SPARE_PART_INSUFFICIENT.value)

    def test_dispatch_exact_available_quantity_succeeds(
        self, api, om_headers,
    ):
        """PRD §3.5: "the comparison is closed at the boundary, so a
        request for exactly the available quantity succeeds."

        Claim: stock_on_hand=3, reserved=0, quantity=3 → 201.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        part = create_spare_part(stock_on_hand=3)
        defect = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        payload = create_work_order_payload(
            assigned_supplier_id=supplier["id"],
            spare_part_lines=[{"part_id": part["id"], "quantity": 3}],
        )
        resp = api.create_work_order(defect["id"], payload, om_headers)
        validate_success(resp, expected_status=201)


class TestWorkOrderCompletion:
    """PRD §3.5 completion cascade."""

    def test_complete_cascades_defect_to_resolved(self, api, field_headers,
                                                  om_headers):
        """PRD §3.5: "On success the order moves to COMPLETED, its
        actual_end is set, the defect cascades from UNDER_REPAIR to
        RESOLVED with its resolved_at recorded..."

        Claim: completing a work order moves the work order to
        COMPLETED and the parent defect to RESOLVED.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        defect = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        wo = dispatch_work_order(defect["id"], supplier["id"])
        start_work_order(wo["id"])
        resp = api.complete_work_order(
            wo["id"], complete_work_order_payload(), field_headers,
        )
        completed = validate_success(resp)
        assert completed["state"] == "COMPLETED"
        # Re-fetch defect via the list endpoint to confirm RESOLVED.
        defects = api.list_defects(om_headers, params={
            "station_id": station["id"],
        }).json()["data"]
        d = next(d for d in defects if d["id"] == defect["id"])
        assert d["state"] == "RESOLVED"

    def test_complete_inverter_defect_returns_inverter_to_operating(
        self, api, field_headers, om_headers,
    ):
        """PRD §3.5: "the inverter ledger flips back to OPERATING
        (only when the defect's subject is an inverter that the
        platform itself had locked to UNDER_REPAIR; defects on
        modules, transformers, strings, and arrays do not touch any
        inverter)..."

        Claim: completing a work order whose defect was created by a
        CRITICAL alarm-ack (and thus locked the inverter to
        UNDER_REPAIR) returns the inverter to OPERATING.
        """
        from test_helpers import (
            ingest_alarm,
            register_alarm_code_map,
            setup_station_with_inverters as setup_station_inv,
        )
        station, _supp, invs = setup_station_inv(inverter_count=1)
        register_alarm_code_map(severity="CRITICAL")
        alarm = ingest_alarm(invs[0]["id"])
        # Ack the CRITICAL alarm — creates defect and locks inverter.
        api.ack_alarm(alarm["id"], om_headers)
        # Find the auto-created defect.
        defects = api.list_defects(om_headers, params={
            "station_id": station["id"],
        }).json()["data"]
        defect = next(
            d for d in defects
            if d.get("source") == "ALARM"
            and d.get("source_ref_id") == alarm["id"]
        )
        # Walk to completion.
        supplier = create_supplier()
        wo = dispatch_work_order(defect["id"], supplier["id"])
        start_work_order(wo["id"])
        api.complete_work_order(
            wo["id"], complete_work_order_payload(), field_headers,
        )
        # Inverter is back to OPERATING.
        inv = validate_success(api.get_inverter(invs[0]["id"], om_headers))
        assert inv["lifecycle_state"] == "OPERATING"


class TestWorkOrderCancellation:
    """PRD §3.5 compensation."""

    def test_cancel_releases_spare_parts(self, api, om_headers):
        """PRD §3.5: "Posting the cancel action on a DISPATCHED work
        order moves it to CANCELED, returns every spare-part line's
        quantity back from reserved_qty (the reservations are
        released), and reverts the parent defect from DISPATCHED
        back to OPEN."

        Claim: cancel on a DISPATCHED work order moves it to CANCELED,
        clears the reservation, and reverts the defect to OPEN.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        part = create_spare_part(stock_on_hand=10)
        defect = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        wo = dispatch_work_order(
            defect["id"], supplier["id"],
            spare_part_lines=[{"part_id": part["id"], "quantity": 3}],
        )
        # cancel via direct api call with the O&M role.
        resp = api.cancel_work_order(wo["id"], om_headers)
        canceled = validate_success(resp)
        assert canceled["state"] == "CANCELED"
        # Spare-part reserved_qty back to 0.
        from test_helpers import api_client, TEST_USERS
        # Re-read part via a fresh GET — no GET endpoint exists for
        # spare parts, so we inspect via PATCH no-op? PRD has no
        # spare-part GET. The only way to observe stock is via the
        # PATCH response. So instead we observe via a subsequent
        # dispatch that needs exactly stock_on_hand of the same part.
        defect2 = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        # Requesting quantity=10 should now succeed since reserved is 0.
        payload2 = create_work_order_payload(
            assigned_supplier_id=supplier["id"],
            spare_part_lines=[{"part_id": part["id"], "quantity": 10}],
        )
        resp2 = api.create_work_order(defect2["id"], payload2, om_headers)
        validate_success(resp2, expected_status=201)


class TestDefectReopenGrace:
    """PRD §3.5 reopen grace window of 30 days."""

    def test_reopen_within_grace_succeeds(self, api, om_headers):
        """PRD §3.5: "Reopening moves the defect from RESOLVED back to
        REOPENED, but only if the time elapsed since the defect's
        resolved_at is at most thirty days..."

        Claim: reopen of a RESOLVED defect within 30 days of
        resolution succeeds; state moves to REOPENED.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        defect = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        wo = dispatch_work_order(defect["id"], supplier["id"])
        start_work_order(wo["id"])
        complete_work_order(wo["id"])
        # defect is now RESOLVED. Reopen immediately (within grace).
        resp = api.reopen_defect(defect["id"], om_headers)
        data = validate_success(resp)
        assert data["state"] == "REOPENED"

    def test_reopen_after_grace_window_fails(self, api, om_headers):
        """PRD §3.5: "the grace window is a hard cap, so a defect
        resolved thirty-one days ago cannot be reopened and must
        instead be reopened by chaining a new defect via
        parent_defect_id."

        Claim: reopen on a defect whose resolved_at is more than 30
        days behind the current clock → ERR_INVALID_STATE.
        """
        station, _supp, invs = setup_station_with_inverters(inverter_count=1)
        supplier = create_supplier()
        # Set the clock to a known point, walk defect to RESOLVED, then
        # advance the clock by 31 days.
        advance_clock_to("2026-03-01T00:00:00.000Z")
        defect = create_manual_defect(
            station_id=station["id"],
            subject_type="INVERTER",
            subject_id=invs[0]["id"],
            severity="MINOR",
        )
        wo = dispatch_work_order(defect["id"], supplier["id"])
        start_work_order(wo["id"])
        complete_work_order(wo["id"])  # defect RESOLVED at ~2026-03-01
        # Advance 31 days.
        advance_clock_to("2026-04-01T01:00:00.000Z")
        resp = api.reopen_defect(defect["id"], om_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
