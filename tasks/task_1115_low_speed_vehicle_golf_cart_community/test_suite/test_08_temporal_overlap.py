"""Temporal overlap semantics: half-open route passes, buffered closed charging
intervals, and closed dispatch windows where adjacency conflicts (PRD §2.10).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_permit_holder_headers,
    create_community, create_eligible_holder, deposit,
    setup_active_registration, setup_route, setup_route_pass,
    setup_station, setup_reservation, setup_fleet_scenario, setup_dispatch,
    create_route_pass_payload, create_charging_reservation_payload,
    create_fleet_dispatch_payload,
    ApiErrorId,
)


def _setup_to1():
    """ACTIVE LSV registration; DESIGNATED LSV_ALLOWED route."""
    ctx = setup_active_registration(
        community_name="C-TO1", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-TO1"})
    route = setup_route(ctx["community"]["id"], name="R-TO1",
                        route_type="STREET", allowed_vehicle_class="LSV_ALLOWED")
    return ctx, route


class TestRoutePassHalfOpenAdjacency:
    def test_back_to_back_windows_are_legal(self):
        """PRD §2.10: "**Route passes** occupy a half-open window: the pass holds
        from its `start_at` inclusive up to but not including its `end_at`. Two
        passes on the same registration may therefore touch — one beginning at the
        exact instant the other ends — but any true overlap between the new window
        and another `ACTIVE` pass on the same registration is rejected with
        `ERR_ROUTE_PASS_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/route_pass_half_open_adjacency
        """
        ctx, route = _setup_to1()
        holder = ctx["holder"]
        reg = ctx["registration"]
        p1 = setup_route_pass(route["id"], reg["id"], holder["id"],
                              start_at="2026-06-01T10:00:00Z",
                              end_at="2026-06-01T12:00:00Z")
        p2 = setup_route_pass(route["id"], reg["id"], holder["id"],
                              start_at="2026-06-01T12:00:00Z",
                              end_at="2026-06-01T14:00:00Z")
        assert p1["status"] == "ACTIVE" and p2["status"] == "ACTIVE", (
            "end == next start is adjacency, not overlap, under half-open semantics")

    def test_interior_overlap_rejected(self):
        """PRD §2.10: "Two passes on the same registration may therefore touch —
        one beginning at the exact instant the other ends — but any true overlap
        between the new window and another `ACTIVE` pass on the same registration
        is rejected with `ERR_ROUTE_PASS_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/route_pass_half_open_adjacency
        """
        ctx, route = _setup_to1()
        holder = ctx["holder"]
        reg = ctx["registration"]
        setup_route_pass(route["id"], reg["id"], holder["id"],
                         start_at="2026-06-01T10:00:00Z",
                         end_at="2026-06-01T12:00:00Z")
        setup_route_pass(route["id"], reg["id"], holder["id"],
                         start_at="2026-06-01T12:00:00Z",
                         end_at="2026-06-01T14:00:00Z")
        res = api_client.create_route_pass(
            create_route_pass_payload(route["id"], reg["id"], holder["id"],
                                      start_at="2026-06-01T11:00:00Z",
                                      end_at="2026-06-01T13:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        # [11:00,13:00) overlaps both windows in their interiors.
        validate_error(res, ApiErrorId.ERR_ROUTE_PASS_OVERLAP, expected_status=409)


def _setup_to2():
    """ONLINE station (2 slots, rate 10 c/min); holder wallet 100000; R1
    [10:00,11:00] on slot 0."""
    community = create_community(name="C-TO2")
    holder = create_eligible_holder(community["id"], full_name="H TO2",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 100000, holder["version"])
    station = setup_station(community["id"], name="S-TO2", slot_count=2,
                            rate_cents_per_min=10)
    setup_reservation(station["id"], holder["id"], slot_index=0,
                      start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    return community, holder, station


class TestChargingClosedIntervalWithBuffer:
    def test_start_inside_buffer_rejected(self):
        """PRD §2.10: "**Charging reservations** occupy a closed interval — both
        `start_at` and `end_at` inclusive — padded with a 15-minute turnaround
        buffer on both sides. A new reservation on a given station and bay collides
        with any other `BOOKED` reservation on the same station and `slot_index`
        whose buffered interval touches it; such a collision is rejected with
        `ERR_CHARGING_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/charging_closed_interval_with_buffer
        """
        _, holder, station = _setup_to2()
        res = api_client.create_charging_reservation(
            create_charging_reservation_payload(
                station["id"], holder["id"], slot_index=0,
                start_at="2026-06-01T11:14:00Z", end_at="2026-06-01T12:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        # 11:14 < 11:00 + 15min -> buffered intervals touch.
        validate_error(res, ApiErrorId.ERR_CHARGING_OVERLAP, expected_status=409)

    def test_start_exactly_at_buffer_boundary_rejected(self):
        """PRD §2.10: "**Charging reservations** occupy a closed interval — both
        `start_at` and `end_at` inclusive — padded with a 15-minute turnaround
        buffer on both sides. A new reservation on a given station and bay collides
        with any other `BOOKED` reservation on the same station and `slot_index`
        whose buffered interval touches it; such a collision is rejected with
        `ERR_CHARGING_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/charging_closed_interval_with_buffer
        """
        _, holder, station = _setup_to2()
        res = api_client.create_charging_reservation(
            create_charging_reservation_payload(
                station["id"], holder["id"], slot_index=0,
                start_at="2026-06-01T11:15:00Z", end_at="2026-06-01T12:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        # R1 [10:00,11:00] buffered to [09:45,11:15]; the new window starts
        # exactly at 11:15 — closed intervals touch at the endpoint, and §2.10
        # rejects any buffered interval that "touches" the new reservation.
        validate_error(res, ApiErrorId.ERR_CHARGING_OVERLAP, expected_status=409)


def _setup_to3():
    """AVAILABLE fleet vehicle; ELIGIBLE holder."""
    ctx = setup_fleet_scenario(community_name="C-TO3", slot_count=1, rate=10)
    return ctx


class TestDispatchWindowClosedAdjacencyConflicts:
    def test_touching_endpoints_conflict(self):
        """PRD §2.10: "**Fleet dispatch shifts** occupy a closed interval from
        `shift_start` through `shift_end` with no buffer, and per vehicle adjacency
        itself counts as a conflict: a new dispatch whose closed window so much as
        touches another non-terminal dispatch on the same vehicle is rejected with
        `ERR_DISPATCH_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_closed_adjacency_conflicts
        """
        ctx = _setup_to3()
        holder = ctx["holder"]
        fv = ctx["fleet_vehicle"]
        d1 = setup_dispatch(fv["id"], holder["id"],
                            shift_start="2026-06-01T10:00:00Z",
                            shift_end="2026-06-01T12:00:00Z")
        assert d1["status"] == "BOOKED"
        res = api_client.create_fleet_dispatch(
            create_fleet_dispatch_payload(fv["id"], holder["id"],
                                          shift_start="2026-06-01T12:00:00Z",
                                          shift_end="2026-06-01T14:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        # Closed semantics: 12:00 <= 12:00 collides.
        validate_error(res, ApiErrorId.ERR_DISPATCH_WINDOW_OVERLAP, expected_status=409)

    def test_one_second_later_clears_closed_interval(self):
        """PRD §2.10: "**Fleet dispatch shifts** occupy a closed interval from
        `shift_start` through `shift_end` with no buffer, and per vehicle adjacency
        itself counts as a conflict: a new dispatch whose closed window so much as
        touches another non-terminal dispatch on the same vehicle is rejected with
        `ERR_DISPATCH_WINDOW_OVERLAP` (HTTP 409)."
        PRD §2.10: "Two passes on the same registration may therefore touch — one
        beginning at the exact instant the other ends — but any true overlap
        between the new window and another `ACTIVE` pass on the same registration
        is rejected with `ERR_ROUTE_PASS_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_closed_adjacency_conflicts
        """
        ctx = _setup_to3()
        holder = ctx["holder"]
        fv = ctx["fleet_vehicle"]
        setup_dispatch(fv["id"], holder["id"],
                       shift_start="2026-06-01T10:00:00Z",
                       shift_end="2026-06-01T12:00:00Z")
        d2 = setup_dispatch(fv["id"], holder["id"],
                            shift_start="2026-06-01T12:00:01Z",
                            shift_end="2026-06-01T14:00:00Z")
        # One second later clears the closed interval — direct contrast with the
        # half-open route-pass adjacency rule.
        assert d2["status"] == "BOOKED"
