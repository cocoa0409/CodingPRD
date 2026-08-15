"""Tail assignment windows, interchange direction/economics, suggestion selector."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_booking_ok,
    create_aircraft,
    create_aircraft_class,
    create_booking_ok,
    create_completed_booking,
    create_confirmed_booking,
    create_invoice_ok,
    create_maintenance_event_ok,
    create_owner,
    get_booking,
    issue_invoice_ok,
    make_owner_headers,
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


def _two_share_scenario(program_code="FJX-TO1"):
    """Program + MID class + two owners each with an ACTIVE 1/8 share + one tail."""
    sc = setup_program_with_share(program_code=program_code, class_code="MID")
    owner_b = create_owner(sc["program"]["id"], legal_name=f"{program_code} OwnerB")
    from test_helpers import create_activated_share
    share_b = create_activated_share(owner_b["id"], sc["cls"]["id"])
    tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N600HL")
    sc.update({"owner_b": owner_b, "share_b": share_b, "tail": tail})
    return sc


class TestHalfOpenWindowAdjacency:
    def test_adjacent_windows_assign_succeeds(self, api):
        """PRD §3.4: "no other `CONFIRMED` booking window and no in-progress maintenance
        window may overlap the booking's window, where windows are treated as half-open
        intervals — one window ending at the exact instant another begins is not a
        conflict."

        Design: Difficulty/resource_temporal_overlap/aircraft_booking_half_open_adjacency
        """
        sc = _two_share_scenario("FJX-TO1A")
        # Booking A occupies [13:00, 15:00)
        create_assigned = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T13:00:00Z", 2.00,
        )
        assign_booking_ok(create_assigned["id"], sc["tail"]["id"])
        # Booking B begins exactly when A ends: [15:00, 17:30)
        booking_b = create_confirmed_booking(
            sc["share_b"]["id"], sc["owner_b"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 2.50,
        )
        resp = api.assign_booking(booking_b["id"], {"aircraft_id": sc["tail"]["id"]}, FLEET)
        data = validate_success(resp, 200)
        assert data["assigned_aircraft_id"] == sc["tail"]["id"], (
            "a window starting exactly when the other ends is adjacency, not overlap"
        )

    def test_one_minute_overlap_assign_rejected(self, api):
        """PRD §3.4: "A conflicting assignment is rejected with
        `ERR_AIRCRAFT_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/aircraft_booking_half_open_adjacency
        """
        sc = _two_share_scenario("FJX-TO1B")
        booking_a = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T13:00:00Z", 2.00,
        )
        assign_booking_ok(booking_a["id"], sc["tail"]["id"])
        # Booking C starts one minute before A's window ends: [14:59, 16:59)
        booking_c = create_confirmed_booking(
            sc["share_b"]["id"], sc["owner_b"]["id"], sc["cls"]["id"],
            "2026-09-10T14:59:00Z", 2.00,
        )
        resp = api.assign_booking(booking_c["id"], {"aircraft_id": sc["tail"]["id"]}, FLEET)
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_WINDOW_CONFLICT)
        assert resp.status_code == 409
        assert get_booking(booking_c["id"])["assigned_aircraft_id"] is None


class TestSuggestAircraftSelector:
    def test_empty_candidate_pool_is_an_error(self, api):
        """PRD §3.4: "An empty candidate pool is reported as `ERR_NO_AIRCRAFT_AVAILABLE`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/empty_candidate_pool_suggest_aircraft
        """
        sc = setup_program_with_share(program_code="FJX-BP2", class_code="MID")
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N500BP")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-12-10T15:00:00Z", 2.00,
        )
        # Put the only tail into IN_PROGRESS maintenance -> IN_MAINTENANCE
        mx = create_maintenance_event_ok(
            tail["id"], "2026-08-01T00:00:00Z", "2027-01-01T00:00:00Z",
        )
        start_maintenance_ok(mx["id"])
        resp = api.suggest_aircraft(booking["id"], FLEET)
        validate_error(resp, ApiErrorId.ERR_NO_AIRCRAFT_AVAILABLE)
        assert resp.status_code == 409

    def test_suggest_aircraft_ranks_by_seat_proximity(self, api):
        """PRD §3.4: "They are ranked first by ascending absolute difference between the
        candidate class's `seats` and the requested class's seats, then by ascending
        `total_hours_flown` to spread wear across the fleet, then by ascending
        `created_at`."

        Design: Difficulty/boundary_precision_check/empty_candidate_pool_suggest_aircraft
        """
        sc = setup_program_with_share(program_code="FJX-BP2B", class_code="MID")
        heavy = create_aircraft_class(sc["program"]["id"], class_code="HEAVY")
        tail_mid = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N501BP")
        tail_heavy = create_aircraft(sc["program"]["id"], heavy["id"], tail_number="N502BP")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-12-10T15:00:00Z", 2.00,
        )
        resp = api.suggest_aircraft(booking["id"], FLEET)
        data = validate_success(resp, 200)
        candidates = data if isinstance(data, list) else data.get("data", [])
        ids = [c["id"] for c in candidates]
        assert ids[:2] == [tail_mid["id"], tail_heavy["id"]], (
            f"MID tail (seat diff 0) must outrank HEAVY tail (seat diff 6); got {ids}"
        )


class TestAssignRbac:
    def test_owner_cannot_assign_aircraft(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "`POST /bookings/{id}/assign` | Assign an aircraft; computes interchange
        direction | FleetOps"

        Design: Corner/rbac/owner_cannot_assign_aircraft
        """
        sc = setup_program_with_share(program_code="FJX-RB1", class_code="MID")
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N666RB")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 1.00,
        )
        resp = api.assign_booking(
            booking["id"], {"aircraft_id": tail["id"]},
            make_owner_headers(sc["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403
        assert get_booking(booking["id"])["assigned_aircraft_id"] is None


class TestInterchangeUpgradeCap:
    def test_upgrade_billing_capped_below_rack_rate(self, api):
        """PRD §3.4: "On an upgrade, the effective hourly rate billed is the lesser of
        the flying class's rack rate and the requested class's rate scaled by the
        assigned class's `interchange_upgrade_multiplier_bp` divided by 10000 — that
        scaled figure rounded half-up to whole cents before the comparison."
        PRD §3.4: "`UPGRADE` when the assigned class's hourly rate exceeds the requested
        class's rate"

        Design: Corner/calculations/interchange_upgrade_capped_billing
        """
        sc = setup_program_with_share(
            program_code="FJX-CA2", class_code="MID", fraction=(1, 4),
            purchase_price_cents=24000000,
        )
        heavy = create_aircraft_class(sc["program"]["id"], class_code="HEAVY")
        tail_h = create_aircraft(sc["program"]["id"], heavy["id"], tail_number="N111CA")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 2.00,
        )
        assigned = assign_booking_ok(booking["id"], tail_h["id"])
        assert assigned["interchange_direction"] == "UPGRADE", (
            f"HEAVY rate 900000 > MID rate 450000, got {assigned['interchange_direction']}"
        )
        from test_helpers import complete_booking_ok
        # Completion stamps completed_at from the clock (PRD §3.5); advance into the
        # September billing month so the leg aggregates into the 2026-09 invoice.
        set_clock("2026-09-11T00:00:00Z")
        complete_booking_ok(booking["id"], 2.00)

        invoice = create_invoice_ok(sc["owner"]["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        issued = issue_invoice_ok(invoice["id"])
        # effective rate = min(900000, 450000 * 12500/10000 = 562500) = 562500
        # occupied fee = 2.00 * 450000 base + 2.00 * (562500 - 450000) adjustment
        #              = 900000 + 225000 = 1125000 — never the 1800000 rack-rate figure
        assert issued["occupied_hours_fee_cents"] == 1125000, (
            f"upgrade must bill at the capped 562500 rate, got {issued['occupied_hours_fee_cents']}"
        )


class TestInterchangeDowngradeCredit:
    def test_downgrade_produces_negative_adjustment_line(self, api):
        """PRD §3.4: "On a downgrade the owner simply pays the flying class's lower rate,
        and the adjustment line carries the difference between the flying and requested
        rates, multiplied by the billed hours and rounded half-up, as a negative amount —
        a credit."

        Design: Corner/calculations/interchange_downgrade_credit
        """
        sc = setup_program_with_share(
            program_code="FJX-CA3", class_code="SUPER_MID", fraction=(1, 4),
            purchase_price_cents=32000000,
        )
        mid = create_aircraft_class(sc["program"]["id"], class_code="MID")
        tail_m = create_aircraft(sc["program"]["id"], mid["id"], tail_number="N222CA")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 3.00,
        )
        assigned = assign_booking_ok(booking["id"], tail_m["id"])
        assert assigned["interchange_direction"] == "DOWNGRADE"
        from test_helpers import complete_booking_ok
        # Completion stamps completed_at from the clock (PRD §3.5); advance into the
        # September billing month so the leg aggregates into the 2026-09 invoice.
        set_clock("2026-09-11T00:00:00Z")
        complete_booking_ok(booking["id"], 3.00)

        invoice = create_invoice_ok(sc["owner"]["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        issued = issue_invoice_ok(invoice["id"])
        # base 3.00 * 600000 = 1800000; adjustment 3.00 * (450000 - 600000) = -450000
        assert issued["occupied_hours_fee_cents"] == 1350000, (
            f"downgrade must credit the rate difference, got {issued['occupied_hours_fee_cents']}"
        )
        lines, _meta = validate_paginated(api.list_invoice_lines(invoice["id"], FIN))
        adj = [ln for ln in lines if ln["line_kind"] == "INTERCHANGE_ADJUSTMENT"]
        assert any(ln["amount_cents"] == -450000 for ln in adj), (
            f"expected an INTERCHANGE_ADJUSTMENT credit of -450000, got {adj}"
        )
