"""Transitive cascades: violation-upheld depth-3 chain to route-pass revocation,
and station-offline depth-2 chain to wallet refund (PRD §2.11, §3.8, §3.9).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, create_violation_payload,
    deposit, get_holder, set_clock,
    setup_active_registration, setup_route, setup_route_pass,
    setup_station, setup_reservation,
    COMMUNITY_ADMIN, OFFICER,
)


def _setup_tc1():
    """ACTIVE LSV registration with an ACTIVE route pass on
    2026-07-01T10:00-12:00 and three FILED 4-point violations; clock 2026-06-15
    so the pass window is still upcoming."""
    ctx = setup_active_registration(
        community_name="C-TC1", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-TC1"})
    holder = ctx["holder"]
    reg = ctx["registration"]
    route = setup_route(ctx["community"]["id"], name="Main St",
                        route_type="STREET", allowed_vehicle_class="LSV_ALLOWED")
    rp = setup_route_pass(route["id"], reg["id"], holder["id"],
                          start_at="2026-07-01T10:00:00Z",
                          end_at="2026-07-01T12:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    violations = []
    for code in ["OFF_ROUTE", "PARKING_VIOLATION", "UNINSURED_OPERATION"]:
        vio = get_success_data(api_client.create_violation(
            create_violation_payload(holder["id"], registration_id=reg["id"],
                                     violation_code=code, points_assessed=4,
                                     fine_cents=5000,
                                     occurred_at="2026-06-10T00:00:00Z"), OFFICER))
        violations.append(vio)
    return ctx, route, rp, violations


class TestViolationUpholdCascadeToRoutePassRevocation:
    def test_points_accumulate_below_bar_threshold_without_cascade(self):
        """PRD §3.9: "Upholding moves a `FILED` violation to `UPHELD` and triggers
        the standing recomputation: the holder's `points_balance` becomes the sum
        of `points_assessed` over all of the holder's violations currently in
        `UPHELD` status whose `occurred_at` lies within the trailing 730 days of
        now, the boundary included."
        PRD §3.9: "Standing follows fixed thresholds — `BARRED` at 12 points or
        more (exactly 12 is `BARRED`), `PROBATION` at 4 through 11 points, and
        `GOOD_STANDING` at 3 or fewer"

        Design: Difficulty/transitive_cascade/violation_uphold_cascade_to_route_pass_revocation
        """
        ctx, _, rp, violations = _setup_tc1()
        validate_success(api_client.uphold_violation(violations[0]["id"], OFFICER), 200)
        validate_success(api_client.uphold_violation(violations[1]["id"], OFFICER), 200)
        holder = get_holder(ctx["holder"]["id"])
        assert holder["points_balance"] == 8
        assert holder["compliance_status"] == "PROBATION"
        reg = get_success_data(
            api_client.get_registration(ctx["registration"]["id"], COMMUNITY_ADMIN))
        assert reg["status"] == "ACTIVE", (
            "no BARRED flip yet -> registration must stay ACTIVE")

    def test_barred_flip_suspends_registration_and_revokes_pass(self):
        """PRD §3.9: "When this recomputation flips a holder into `BARRED`, the
        cascade of §2.11 fires: every `ACTIVE` registration belonging to the holder
        flips to `SUSPENDED`, and each such suspension revokes its `ACTIVE` route
        passes."
        PRD §2.11: "A holder whose standing flips into `BARRED` has every `ACTIVE`
        registration suspended, with the same route-pass revocations following each
        suspension."

        Design: Difficulty/transitive_cascade/violation_uphold_cascade_to_route_pass_revocation
        """
        ctx, _, rp, violations = _setup_tc1()
        for vio in violations:
            validate_success(api_client.uphold_violation(vio["id"], OFFICER), 200)
        holder = get_holder(ctx["holder"]["id"])
        assert holder["points_balance"] == 12
        assert holder["compliance_status"] == "BARRED"  # 12 >= 12 inclusive
        reg = get_success_data(
            api_client.get_registration(ctx["registration"]["id"], COMMUNITY_ADMIN))
        assert reg["status"] == "SUSPENDED", (
            "hop 2 fires on the BARRED flip, not on the uphold itself")
        rp_after = get_success_data(api_client.get_route_pass(rp["id"], COMMUNITY_ADMIN))
        assert rp_after["status"] == "REVOKED", (
            "hop 3 fires from the registration suspension")


def _setup_tc2():
    """ONLINE station (rate 10 c/min, 2 slots); holder wallet 100000; BOOKED
    reservation 2026-06-01T10:00-11:00 slot 0 (fee 600 debited -> wallet 99400)."""
    community = create_community(name="C-TC2")
    holder = create_eligible_holder(community["id"], full_name="H TC2",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 100000, holder["version"])
    station = setup_station(community["id"], name="S-TC2", slot_count=2,
                            rate_cents_per_min=10)
    reservation = setup_reservation(
        station["id"], holder["id"], slot_index=0,
        start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    return community, holder, station, reservation


class TestStationOfflineCascadeWalletRefund:
    def test_set_offline_cancels_future_booked_reservation(self):
        """PRD §3.8: "Taking a station offline — permitted from `ONLINE` — cancels
        every `BOOKED` reservation whose `start_at` lies in the future and credits
        each such reservation's `fee_cents` back to its holder's wallet, conserving
        the wallet across the book-and-refund pair."

        Design: Difficulty/transitive_cascade/station_offline_cascade_wallet_refund
        """
        _, holder, station, reservation = _setup_tc2()
        assert reservation["fee_cents"] == 600
        assert get_holder(holder["id"])["wallet_balance_cents"] == 99400
        validate_success(api_client.set_station_offline(station["id"], COMMUNITY_ADMIN), 200)
        res_after = get_success_data(
            api_client.get_charging_reservation(reservation["id"], COMMUNITY_ADMIN))
        assert res_after["status"] == "CANCELLED", (
            "hop 1: station -> reservation; start 2026-06-01 > now 2026-05-01")

    def test_cancellation_refunds_exactly_fee_cents(self):
        """PRD §2.9: "The wallet is credited by holder deposits and by refunds — a
        cancelled charging reservation returns its fee in full, as does each
        reservation cancelled by a station outage cascade."
        PRD §3.8: "The fee charged at booking is the reservation's duration in
        minutes — any fractional minute rounded up — multiplied by the station's
        `rate_cents_per_min`, subject to a minimum charge of 200 cents; the
        computed `fee_cents` is debited from the holder's wallet immediately"

        Design: Difficulty/transitive_cascade/station_offline_cascade_wallet_refund
        """
        _, holder, station, reservation = _setup_tc2()
        validate_success(api_client.set_station_offline(station["id"], COMMUNITY_ADMIN), 200)
        wallet_after = get_holder(holder["id"])["wallet_balance_cents"]
        assert wallet_after == 100000, (
            f"hop 2 must refund exactly fee_cents: wallet {wallet_after} != 100000")
