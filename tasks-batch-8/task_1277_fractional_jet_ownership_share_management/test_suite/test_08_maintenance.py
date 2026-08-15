"""Maintenance windows: start cascade, singleton in-progress rule, cost allocation,
temporal validation."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_booking_ok,
    complete_maintenance_ok,
    create_activated_share,
    create_aircraft,
    create_confirmed_booking,
    create_invoice_ok,
    create_maintenance_event_ok,
    create_owner,
    create_program,
    create_aircraft_class,
    get_aircraft,
    get_booking,
    issue_invoice_ok,
    set_clock,
    setup_program_with_share,
    start_maintenance_ok,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
FLEET = TEST_USERS["fleet_ops_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def _program_with_tail(program_code="FJX-TC1"):
    """Program + MID class + one tail, no owners needed for pure maintenance tests."""
    program = create_program(program_code=program_code)
    cls = create_aircraft_class(program["id"], class_code="MID")
    tail = create_aircraft(program["id"], cls["id"], tail_number="N300TC")
    return program, cls, tail


class TestMaintenanceStartCascade:
    def test_start_unassigns_overlapping_confirmed_booking(self, api):
        """PRD §3.7: "The tail moves from `IN_SERVICE` to `IN_MAINTENANCE`, and any
        `CONFIRMED` booking assigned to it whose window overlaps the maintenance window
        is unassigned — its `assigned_aircraft_id` is cleared"

        Design: Difficulty/transitive_cascade/maintenance_start_cascade_depth3
        """
        sc = setup_program_with_share(program_code="FJX-TC1", class_code="MID")
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N300TC")
        # Booking window [2026-09-10T15:00, 17:00) overlaps the maintenance window
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 2.00,
        )
        assign_booking_ok(booking["id"], tail["id"])
        mx = create_maintenance_event_ok(
            tail["id"], "2026-09-10T00:00:00Z", "2026-09-11T00:00:00Z",
        )
        resp = api.start_maintenance(mx["id"], FLEET)
        event = validate_success(resp, 200)
        assert event["event_status"] == "IN_PROGRESS"

        # Hop 1: the tail's status changed because the event started
        assert get_aircraft(tail["id"])["aircraft_status"] == "IN_MAINTENANCE"
        # Hop 2: the overlapping booking is unassigned by the status change
        after = get_booking(booking["id"])
        assert after["assigned_aircraft_id"] is None, (
            "the overlapping CONFIRMED booking must lose its assignment"
        )
        assert after["interchange_direction"] == "NONE"
        # The cascade does not cancel the booking
        assert after["booking_status"] == "CONFIRMED"

    def test_start_leaves_non_overlapping_booking_assigned(self, api):
        """PRD §3.7: "any `CONFIRMED` booking assigned to it whose window overlaps the
        maintenance window is unassigned — its `assigned_aircraft_id` is cleared"

        Design: Difficulty/transitive_cascade/maintenance_start_cascade_depth3
        """
        sc = setup_program_with_share(program_code="FJX-TC1B", class_code="MID")
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N301TC")
        # Booking window [2026-09-15T15:00, 17:00) does NOT overlap [09-10, 09-11)
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-15T15:00:00Z", 2.00,
        )
        assign_booking_ok(booking["id"], tail["id"])
        mx = create_maintenance_event_ok(
            tail["id"], "2026-09-10T00:00:00Z", "2026-09-11T00:00:00Z",
        )
        start_maintenance_ok(mx["id"])
        after = get_booking(booking["id"])
        assert after["assigned_aircraft_id"] == tail["id"], (
            "only overlapping bookings are unassigned; disjoint windows keep theirs"
        )
        assert after["booking_status"] == "CONFIRMED"


class TestInProgressSingleton:
    def test_second_in_progress_event_rejected_despite_disjoint_windows(self, api):
        """PRD §3.7: "Starting the event requires that no other maintenance event is
        already `IN_PROGRESS` on the same tail; a second in-progress event is rejected
        with `ERR_MAINTENANCE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/maintenance_in_progress_singleton_per_aircraft
        """
        _program, _cls, tail = _program_with_tail("FJX-TO2")
        mx1 = create_maintenance_event_ok(
            tail["id"], "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z",
        )
        mx2 = create_maintenance_event_ok(
            tail["id"], "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z",
        )
        first = validate_success(api.start_maintenance(mx1["id"], FLEET), 200)
        assert first["event_status"] == "IN_PROGRESS"
        # Disjoint windows still collide: the rule is a capacity-1 singleton per tail
        resp = api.start_maintenance(mx2["id"], FLEET)
        validate_error(resp, ApiErrorId.ERR_MAINTENANCE_OVERLAP)
        assert resp.status_code == 409

    def test_in_progress_slot_frees_after_completion(self, api):
        """PRD §3.7: "Completing the event requires the clock to have reached
        `window_end_utc`, unless `FleetOps` explicitly passes the `override_early` flag;
        completion returns the tail to `IN_SERVICE` and triggers cost allocation."

        Design: Difficulty/resource_temporal_overlap/maintenance_in_progress_singleton_per_aircraft
        """
        _program, _cls, tail = _program_with_tail("FJX-TO2B")
        mx1 = create_maintenance_event_ok(
            tail["id"], "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z",
        )
        mx2 = create_maintenance_event_ok(
            tail["id"], "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z",
        )
        start_maintenance_ok(mx1["id"])
        set_clock("2026-09-05T00:00:00Z")  # reach mx1's window_end
        completed = complete_maintenance_ok(mx1["id"])
        assert completed["event_status"] == "COMPLETED"
        assert get_aircraft(tail["id"])["aircraft_status"] == "IN_SERVICE"
        # With no event IN_PROGRESS on the tail, the second start now succeeds
        second = validate_success(api.start_maintenance(mx2["id"], FLEET), 200)
        assert second["event_status"] == "IN_PROGRESS"


class TestMaintenanceTemporalValidation:
    def test_window_end_not_after_start_rejected(self, api):
        """PRD §3.7: "a `window_end_utc` strictly after the start — anything else is
        rejected with `ERR_TEMPORAL_INVALID`"

        Design: Difficulty/priority_pair_validation_conflict/exit_value_temporal_vs_referential_priority
        """
        _program, _cls, tail = _program_with_tail("FJX-PP2")
        resp = api.create_maintenance_event(
            {
                "aircraft_id": tail["id"],
                "window_start_utc": "2026-09-10T10:00:00Z",
                "window_end_utc": "2026-09-10T09:00:00Z",
                "cost_cents": 1000,
                "unscheduled_flag": False,
            },
            FLEET,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID)
        assert resp.status_code == 422


class TestMaintenanceCostAllocation:
    def test_remainder_cents_distributed_by_weight_then_seniority(self, api):
        """PRD §3.7: "For scheduled events, an owner's weight is the sum of the ownership
        fractions of their `ACTIVE` shares in the class."
        PRD §3.7: "Each owner's raw allotment is the pool scaled by their weight over the
        total weight; raw allotments are floored to whole cents, and the remainder cents
        are then distributed one at a time in order of decreasing weight, ties broken by
        the owner's earlier `created_at`, until the remainder is exhausted."

        Design: Corner/calculations/maintenance_allocation_remainder_distribution
        """
        program = create_program(program_code="FJX-CA4")
        cls = create_aircraft_class(program["id"], class_code="MID")
        owner_a = create_owner(program["id"], legal_name="CA4 OwnerA")
        owner_b = create_owner(program["id"], legal_name="CA4 OwnerB")
        owner_c = create_owner(program["id"], legal_name="CA4 OwnerC")
        create_activated_share(owner_a["id"], cls["id"], fraction_numerator=1,
                               fraction_denominator=4, purchase_price_cents=24000000)
        create_activated_share(owner_b["id"], cls["id"], fraction_numerator=1,
                               fraction_denominator=8, purchase_price_cents=12000000)
        create_activated_share(owner_c["id"], cls["id"], fraction_numerator=1,
                               fraction_denominator=16, purchase_price_cents=6000000)
        tail = create_aircraft(program["id"], cls["id"], tail_number="N333CA")
        mx = create_maintenance_event_ok(
            tail["id"], "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z",
            cost_cents=100001,
        )
        start_maintenance_ok(mx["id"])
        set_clock("2026-08-12T00:00:00Z")
        complete_maintenance_ok(mx["id"])

        inv_a = create_invoice_ok(owner_a["id"], "2026-08")
        inv_b = create_invoice_ok(owner_b["id"], "2026-08")
        inv_c = create_invoice_ok(owner_c["id"], "2026-08")
        set_clock("2026-09-01T00:00:00Z")
        issue_invoice_ok(inv_a["id"])
        issue_invoice_ok(inv_b["id"])
        issue_invoice_ok(inv_c["id"])

        def allocation(invoice_id):
            lines, _meta = validate_paginated(api.list_invoice_lines(invoice_id, FIN))
            amounts = [ln["amount_cents"] for ln in lines
                       if ln["line_kind"] == "MAINTENANCE_ALLOCATION"]
            assert len(amounts) == 1, f"expected one allocation line, got {amounts}"
            return amounts[0]

        # weights 1/4 : 1/8 : 1/16 over a 100001-cent pool: floors 57143/28571/14285
        # leave a remainder of 2 cents, distributed by decreasing weight.
        a = allocation(inv_a["id"])
        b = allocation(inv_b["id"])
        c = allocation(inv_c["id"])
        assert a == 57144, f"heaviest weight takes the first remainder cent, got {a}"
        assert b == 28572, f"second weight takes the second remainder cent, got {b}"
        assert c == 14285, f"lightest weight receives no remainder, got {c}"
        assert a + b + c == 100001, "the allocation conserves the pool exactly"
