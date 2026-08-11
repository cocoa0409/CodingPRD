"""Compensating invariants: wallet conserved across charge and refund; fleet
checked-out count conserved across checkout and return (PRD §2.9, §3.8).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, deposit, get_holder,
    setup_station, setup_reservation, setup_fleet_scenario, setup_dispatch,
    set_clock,
    COMMUNITY_ADMIN,
)


def _setup_ci1():
    """ONLINE station rate 10 c/min; holder wallet exactly 100000 after deposit;
    clock 2026-05-01 (reservation window is in the future)."""
    community = create_community(name="C-CI1")
    holder = create_eligible_holder(community["id"], full_name="H CI1",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 100000, holder["version"])
    station = setup_station(community["id"], name="S-CI1", slot_count=2,
                            rate_cents_per_min=10)
    return community, holder, station


class TestWalletConservedAcrossChargeAndRefund:
    def test_booking_debits_fee_from_wallet(self):
        """PRD §3.8: "The fee charged at booking is the reservation's duration in
        minutes — any fractional minute rounded up — multiplied by the station's
        `rate_cents_per_min`, subject to a minimum charge of 200 cents; the
        computed `fee_cents` is debited from the holder's wallet immediately, and a
        balance below the fee (equality is sufficient) is rejected with
        `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/compensating_invariant/wallet_conserved_across_charge_and_refund
        """
        _, holder, station = _setup_ci1()
        reservation = setup_reservation(
            station["id"], holder["id"], slot_index=0,
            start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
        assert reservation["fee_cents"] == 600  # 60 min * 10 c/min
        wallet = get_holder(holder["id"])["wallet_balance_cents"]
        assert wallet == 99400, f"forward action: wallet {wallet} != 99400"

    def test_cancel_before_start_restores_wallet_exactly(self):
        """PRD §2.9: "The wallet is credited by holder deposits and by refunds — a
        cancelled charging reservation returns its fee in full, as does each
        reservation cancelled by a station outage cascade."
        PRD §3.8: "The holder may cancel a `BOOKED` reservation before its
        `start_at` for a full refund of `fee_cents` to the wallet; once the clock
        moves past `end_at` the reservation completes (`BOOKED` → `COMPLETED`)."

        Design: Difficulty/compensating_invariant/wallet_conserved_across_charge_and_refund
        """
        _, holder, station = _setup_ci1()
        reservation = setup_reservation(
            station["id"], holder["id"], slot_index=0,
            start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
        hh = make_permit_holder_headers(holder["id"])
        cancelled = validate_success(
            api_client.cancel_charging_reservation(reservation["id"], hh), 200)
        assert cancelled["status"] == "CANCELLED"
        wallet = get_holder(holder["id"])["wallet_balance_cents"]
        assert wallet == 100000, (
            f"compensating action must restore the conserved quantity exactly: "
            f"wallet {wallet} != 100000")


def _setup_ci2():
    """AVAILABLE fleet vehicle in a community with checked_out_count 0; ELIGIBLE
    holder; dispatch booked for 2026-05-01T09:00-17:00; clock 2026-05-01T10:00
    (inside the shift)."""
    ctx = setup_fleet_scenario(community_name="C-CI2", slot_count=1, rate=10)
    dispatch = setup_dispatch(ctx["fleet_vehicle"]["id"], ctx["holder"]["id"],
                              shift_start="2026-05-01T09:00:00Z",
                              shift_end="2026-05-01T17:00:00Z")
    set_clock("2026-05-01T10:00:00Z")
    ctx["dispatch"] = dispatch
    return ctx


class TestFleetCheckedOutCountConservedAcrossCheckoutReturn:
    def test_checkout_bumps_count_and_flips_vehicle(self):
        """PRD §3.8: "A successful checkout moves the dispatch `BOOKED` →
        `CHECKED_OUT`, flips the vehicle `AVAILABLE` → `CHECKED_OUT`, and raises
        the community's `checked_out_count` by 1."
        PRD §3.1: "A freshly created community also carries a computed
        `checked_out_count` starting at zero, tracking how many of its fleet
        vehicles are currently checked out."

        Design: Difficulty/compensating_invariant/fleet_checked_out_count_conserved_across_checkout_return
        """
        ctx = _setup_ci2()
        assert ctx["community"]["checked_out_count"] == 0  # pre-checkout baseline
        holder = ctx["holder"]
        hh = make_permit_holder_headers(holder["id"])
        validate_success(
            api_client.checkout_fleet_dispatch(ctx["dispatch"]["id"], hh), 200)
        community = get_success_data(
            api_client.get_community(ctx["community"]["id"], COMMUNITY_ADMIN))
        assert community["checked_out_count"] == 1
        vehicle = get_success_data(
            api_client.get_fleet_vehicle(ctx["fleet_vehicle"]["id"], COMMUNITY_ADMIN))
        assert vehicle["status"] == "CHECKED_OUT"

    def test_return_restores_count_and_vehicle(self):
        """PRD §3.8: "The holder returns the vehicle from either `CHECKED_OUT` or
        `OVERDUE`: the dispatch records `returned_at` at the return instant and
        moves to `RETURNED` (terminal), the vehicle flips back to `AVAILABLE`, the
        community's `checked_out_count` drops by 1, and when the return is later
        than `shift_end` a late fine is computed — the number of days late with any
        partial day rounded up, multiplied by 500 cents — and recorded in
        `late_fine_cents` and debited from the holder's wallet."

        Design: Difficulty/compensating_invariant/fleet_checked_out_count_conserved_across_checkout_return
        """
        ctx = _setup_ci2()
        holder = ctx["holder"]
        hh = make_permit_holder_headers(holder["id"])
        validate_success(
            api_client.checkout_fleet_dispatch(ctx["dispatch"]["id"], hh), 200)
        returned = validate_success(
            api_client.return_fleet_dispatch(ctx["dispatch"]["id"], hh), 200)
        assert returned["status"] == "RETURNED"
        # Returned at 10:00, before shift_end 17:00 -> no late fine.
        assert returned["late_fine_cents"] == 0
        community = get_success_data(
            api_client.get_community(ctx["community"]["id"], COMMUNITY_ADMIN))
        assert community["checked_out_count"] == 0, (
            "checkout + return conserves the count")
        vehicle = get_success_data(
            api_client.get_fleet_vehicle(ctx["fleet_vehicle"]["id"], COMMUNITY_ADMIN))
        assert vehicle["status"] == "AVAILABLE"
