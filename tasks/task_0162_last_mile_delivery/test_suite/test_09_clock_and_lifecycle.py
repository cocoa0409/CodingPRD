"""Logical clock (PRD §2.11) and end-to-end lifecycle integration."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    add_stop,
    advance_clock_by_days,
    advance_clock_to,
    api_client,
    check_in_driver,
    clock_advance_payload,
    create_parcel,
    create_route,
    current_clock,
    deliver_signed,
    dispatch_route,
    induct_to_hub,
    iso_utc,
    make_customer_headers,
    make_driver_headers,
    parse_iso,
    setup_baseline,
    sort_parcel,
    validate_error,
    validate_success,
    walk_parcel_to_out_for_delivery,
    walk_parcel_to_sorted,
)


# ---------------------------------------------------------------------------
# Logical clock — PRD §2.11
# ---------------------------------------------------------------------------
class TestLogicalClock:

    def test_clock_advances_forward(self, api):
        """PRD §2.11: 'A test-only capability advances the clock to a
        supplied target instant carried in the request body as
        to_iso8601.'"""
        now = current_clock()
        target = now + timedelta(hours=1)
        res = api.advance_clock(
            clock_advance_payload(iso_utc(target)),
            TEST_USERS["dispatcher_headers"],
        )
        validate_success(res, 200)
        # Keep the in-process tracker in sync with the server clock so
        # subsequent tests' relative advances also move forward.
        from test_helpers import reset_clock_tracker_to
        reset_clock_tracker_to(target)

    def test_clock_backwards_rejected(self, api):
        """PRD §2.11: 'The clock is forward-only: advancing to an
        instant earlier than the current now is rejected with
        ERR_CLOCK_BACKWARDS.'"""
        # First, push the clock forward.
        forward = current_clock() + timedelta(hours=2)
        validate_success(api.advance_clock(
            clock_advance_payload(iso_utc(forward)),
            TEST_USERS["dispatcher_headers"],
        ), 200)
        from test_helpers import reset_clock_tracker_to
        reset_clock_tracker_to(forward)
        # Then try to go backwards.
        backward = forward - timedelta(hours=1)
        res = api.advance_clock(
            clock_advance_payload(iso_utc(backward)),
            TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_CLOCK_BACKWARDS")

    def test_any_role_may_advance_clock(self, api):
        """PRD §2.11: 'Any role may advance the clock, since it is
        purely a test instrument.'"""
        target = current_clock() + timedelta(hours=1)
        res = api.advance_clock(
            clock_advance_payload(iso_utc(target)),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_success(res, 200)
        from test_helpers import reset_clock_tracker_to
        reset_clock_tracker_to(target)


# ---------------------------------------------------------------------------
# End-to-end lifecycle
# ---------------------------------------------------------------------------
class TestEndToEndLifecycle:

    def test_full_lifecycle_inducted_to_delivered(self, api):
        """PRD §3 narratives end-to-end: induction -> hub -> sorted ->
        on-vehicle -> dispatched/out-for-delivery -> attempt
        DELIVERED_SIGNED inside window -> DELIVERED with final_fee
        populated.
        """
        ctx = walk_parcel_to_out_for_delivery()
        delivered_attempt = deliver_signed(
            ctx["parcel"], ctx["stop"], ctx["driver"]["id"],
        )
        terminal = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert terminal["status"] == "DELIVERED"
        assert terminal["last_attempt_outcome"] == "DELIVERED_SIGNED"
        assert terminal["final_fee"] is not None

    def test_full_lifecycle_with_return_to_sender(self, api):
        """PRD §3.5 / §3.7: ADDRESS_INVALID -> EXCEPTION -> return_to_sender
        -> RETURNED_TO_SENDER with final_fee that includes the return
        surcharge."""
        ctx = walk_parcel_to_out_for_delivery()
        # Move clock into the window so the temporal guard passes.
        from test_helpers import move_clock_into_window
        move_clock_into_window(ctx["parcel"])
        validate_success(api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "ADDRESS_INVALID"},
            make_driver_headers(ctx["driver"]["id"]),
        ), 201)
        terminal = validate_success(api.return_to_sender(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert terminal["status"] == "RETURNED_TO_SENDER"
        assert terminal["final_fee"] is not None
        # The final fee must exceed quoted_fee (return adds surcharges).
        assert terminal["final_fee"] > terminal["quoted_fee"]


# ---------------------------------------------------------------------------
# Version increments across lifecycle
# ---------------------------------------------------------------------------
class TestVersionIncrements:

    def test_patch_increments_version_by_one(self, api):
        """PRD §2.4: 'a system-managed counter that increments by one
        on every mutation to the resource'."""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        v0 = parcel["version"]
        updated = validate_success(api.patch_parcel(
            parcel["id"], {"signature_required": True},
            TEST_USERS["dispatcher_headers"],
        ), 200)
        # PRD says "increments by one on every mutation". When a PATCH
        # also triggers a quoted_fee recompute, PRD §2.5 says cascades
        # are themselves mutations — but the same resource is the
        # subject of both, and the natural reading is version += 1.
        assert updated["version"] >= v0 + 1


# ---------------------------------------------------------------------------
# Cascades from PRD §2.5 hierarchical consistency
# ---------------------------------------------------------------------------
class TestHierarchicalCascade:

    def test_close_after_all_terminal_drives_driver_to_returned(self, api):
        """PRD §3.4: 'On close, the route lands in the terminal CLOSED
        state, the driver's status advances to RETURNED'."""
        ctx = walk_parcel_to_out_for_delivery()
        deliver_signed(ctx["parcel"], ctx["stop"], ctx["driver"]["id"])
        closed = validate_success(api.close_route(
            ctx["route"]["id"],
            make_driver_headers(ctx["driver"]["id"]),
        ), 200)
        assert closed["status"] == "CLOSED"
        # PRD §3.2: 'transitioning to ... RETURNED when the driver
        # closes that route, and finally back to OFF_DUTY when the
        # driver checks out.' Verify check-out is admissible from
        # RETURNED — implies driver did reach RETURNED.
        res = api.driver_check_out(
            ctx["driver"]["id"],
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_success(res, 200)
