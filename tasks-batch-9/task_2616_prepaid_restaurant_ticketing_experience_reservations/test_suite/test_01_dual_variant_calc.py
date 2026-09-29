"""
Two calculations whose variant selector changes the outcome from identical
inputs: the cancellation settlement's forfeiture basis, and the waitlist's
promotion-ranking policy.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import make_guest_headers, make_restaurant_headers

# The Saturday the two settlement arms are cancelled against. Saturday is the
# strongest day-of-week factor at 12500 basis points.
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"
# "Subtract the logical clock from the service's seating_start_utc and divide
# by 3600 seconds": exactly 48.0 hours before seating.
CANCEL_AT_48H = "2026-09-10T22:00:00Z"


def _two_basis_world(api):
    """A published Saturday HIGH service carrying one 20-seat class per
    forfeiture basis, with a party-of-2 deposit-paid CONFIRMED booking on each.
    """
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    restaurant = FX.create_restaurant(
        api, service_charge_bp=725, refund_scrutiny_threshold_cents=30000
    )
    manager = make_restaurant_headers(restaurant["id"])
    package_deposit = FX.create_package(
        api,
        restaurant["id"],
        name="Tasting Deposit Basis",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
    )
    package_full = FX.create_package(
        api,
        restaurant["id"],
        name="Tasting Full Ticket Basis",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="FULL_TICKET_BASIS",
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=40,
        demand_tier="HIGH",
        waitlist_policy="YIELD_WEIGHTED",
    )
    tc_deposit = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package_deposit["id"], seats_allocated=20
    )
    tc_full = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package_full["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest_one = FX.create_guest(api, display_name="Guest One")
    guest_two = FX.create_guest(api, display_name="Guest Two")
    reservation_deposit = FX.confirmed_reservation(
        api, tc_deposit["id"], guest_one["id"], party_size=2
    )
    reservation_full = FX.confirmed_reservation(
        api, tc_full["id"], guest_two["id"], party_size=2
    )
    return {
        "manager": manager,
        "service": service,
        "guest_one": guest_one,
        "guest_two": guest_two,
        "reservation_deposit": reservation_deposit,
        "reservation_full": reservation_full,
    }


class TestCancellationSettlementBasisDivergence:
    """The forfeiture basis is the only difference between the two packages."""

    def test_same_money_inputs_settle_to_different_refunds(self, api):
        """Two reservations with byte-identical money settle differently.

        "Under `DEPOSIT_BASIS` the raw forfeiture is 5792 cents, the fee 500
        cents, the retention 6292 cents and the refund 5291 cents, leaving the
        money dimension `PARTIALLY_REFUNDED`." Against the same figures, "Under
        `FULL_TICKET_BASIS` the raw forfeiture is 19305 cents, the fee 1500
        cents, the retention caps at 11583 cents and the refund is 0, leaving
        the money dimension `FORFEITED`."

        Design: Difficulty/dual_variant_calc/cancellation_settlement_deposit_basis_vs_full_ticket_basis
        """
        world = _two_basis_world(api)
        deposit_headers = make_guest_headers(world["guest_one"]["id"])
        full_headers = make_guest_headers(world["guest_two"]["id"])

        # Both bookings start from exactly the same money picture.
        A.assert_money_breakdown(
            world["reservation_deposit"],
            ticket_subtotal=36000,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=11583,
        )
        A.assert_money_breakdown(
            world["reservation_full"],
            ticket_subtotal=36000,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=11583,
        )

        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, world["reservation_deposit"]["id"], world["guest_one"]["id"])
        FX.cancel(api, world["reservation_full"]["id"], world["guest_two"]["id"])

        settled_deposit = FX.read_reservation(
            api, world["reservation_deposit"]["id"], deposit_headers
        )
        settled_full = FX.read_reservation(
            api, world["reservation_full"]["id"], full_headers
        )

        assert settled_deposit["forfeited_cents"] == 6292
        assert settled_deposit["refunded_cents"] == 5291
        A.assert_payment_status(settled_deposit, "PARTIALLY_REFUNDED")
        assert settled_deposit["cancel_settlement_basis"] == "DEPOSIT_BASIS"

        assert settled_full["forfeited_cents"] == 11583
        assert settled_full["refunded_cents"] == 0
        A.assert_payment_status(settled_full, "FORFEITED")
        assert settled_full["cancel_settlement_basis"] == "FULL_TICKET_BASIS"

        # The variant is the only thing that moved.
        assert settled_deposit["refunded_cents"] != settled_full["refunded_cents"]
        A.assert_fulfillment_status(settled_deposit, "CANCELLED")
        A.assert_fulfillment_status(settled_full, "CANCELLED")
        A.assert_settled_ledger_identity(settled_deposit)
        A.assert_settled_ledger_identity(settled_full)

    def test_each_basis_writes_the_row_pair_its_outcome_demands(self, api):
        """The two arms write different ledger rows, not merely different totals.

        "When the settlement yields a refund strictly above zero **and** a
        retention strictly above zero, the reservation moves to
        `PARTIALLY_REFUNDED` and exactly one `FORFEITURE` row and one `REFUND`
        row are written, with `refunded_cents` plus `forfeited_cents` equal to
        `amount_paid_cents`." Whereas "When the settlement yields a refund of
        exactly zero, so that retention has consumed everything paid, the
        reservation moves to `FORFEITED`, a single `FORFEITURE` row for the
        whole of `amount_paid_cents` is written, and `refunded_cents` stays at
        0."

        Design: Difficulty/dual_variant_calc/cancellation_settlement_deposit_basis_vs_full_ticket_basis
        """
        world = _two_basis_world(api)
        deposit_headers = make_guest_headers(world["guest_one"]["id"])
        full_headers = make_guest_headers(world["guest_two"]["id"])

        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, world["reservation_deposit"]["id"], world["guest_one"]["id"])
        FX.cancel(api, world["reservation_full"]["id"], world["guest_two"]["id"])

        deposit_rows = FX.ledger_rows(
            api, world["reservation_deposit"]["id"], deposit_headers
        )
        full_rows = FX.ledger_rows(api, world["reservation_full"]["id"], full_headers)

        deposit_cancel_rows = [
            row for row in deposit_rows if row["memo_code"] == "GUEST_CANCEL"
        ]
        assert sorted(row["kind"] for row in deposit_cancel_rows) == [
            "FORFEITURE",
            "REFUND",
        ]
        by_kind = {row["kind"]: row for row in deposit_cancel_rows}
        assert by_kind["FORFEITURE"]["amount_cents"] == 6292
        assert by_kind["REFUND"]["amount_cents"] == 5291

        full_cancel_rows = [
            row for row in full_rows if row["memo_code"] == "GUEST_CANCEL"
        ]
        assert [row["kind"] for row in full_cancel_rows] == ["FORFEITURE"]
        assert full_cancel_rows[0]["amount_cents"] == 11583

        for row in deposit_rows + full_rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)

        settled_deposit = FX.read_reservation(
            api, world["reservation_deposit"]["id"], deposit_headers
        )
        settled_full = FX.read_reservation(
            api, world["reservation_full"]["id"], full_headers
        )
        A.assert_signed_sum_matches(settled_deposit, deposit_rows)
        A.assert_signed_sum_matches(settled_full, full_rows)


def _two_policy_world(api):
    """One restaurant, two same-day services differing only in waitlist policy,
    each sold out by a party-of-3 holder, each carrying the same two waiting
    guests in the same arrival order.
    """
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    restaurant = FX.create_restaurant(api, service_charge_bp=725)
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
    )
    service_fair = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=10,
        demand_tier="HIGH",
        waitlist_policy="FAIR_QUEUE",
    )
    service_yield = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="LUNCH",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=10,
        demand_tier="HIGH",
        waitlist_policy="YIELD_WEIGHTED",
    )
    tc_fair = FX.create_ticket_class(
        api, restaurant["id"], service_fair["id"], package["id"], seats_allocated=3
    )
    tc_yield = FX.create_ticket_class(
        api, restaurant["id"], service_yield["id"], package["id"], seats_allocated=3
    )
    FX.publish_service(api, restaurant["id"], service_fair["id"])
    FX.publish_service(api, restaurant["id"], service_yield["id"])

    holder = FX.create_guest(api, display_name="Holder")
    # Party of 2 scores 1100; party of 3 scores 1150. The lower-scoring guest
    # joins first on both services.
    waiter_early = FX.create_guest(api, display_name="Early Small Party")
    waiter_late = FX.create_guest(api, display_name="Late Large Party")

    holder_fair = FX.confirmed_reservation(
        api, tc_fair["id"], holder["id"], party_size=3
    )
    holder_yield = FX.confirmed_reservation(
        api, tc_yield["id"], holder["id"], party_size=3
    )

    entries = {}
    for key, service in (("fair", service_fair), ("yield", service_yield)):
        entries[(key, "early")] = FX.join_waitlist(
            api, service["id"], waiter_early["id"], party_size=2
        )
        entries[(key, "late")] = FX.join_waitlist(
            api, service["id"], waiter_late["id"], party_size=3
        )

    return {
        "restaurant": restaurant,
        "tc_fair": tc_fair,
        "tc_yield": tc_yield,
        "holder": holder,
        "holder_fair": holder_fair,
        "holder_yield": holder_yield,
        "waiter_early": waiter_early,
        "waiter_late": waiter_late,
        "entries": entries,
        "manager": make_restaurant_headers(restaurant["id"]),
    }


class TestWaitlistPolicyRankingDivergence:
    """The same two entries, the same two scores, two different winners."""

    def test_fair_queue_promotes_the_earlier_entry_and_ignores_the_score(self, api):
        """FAIR_QUEUE orders by arrival even though the later entry scores higher.

        "Under `FAIR_QUEUE` the `priority_score` is still computed and still
        persisted on the entry, but it is **entirely ignored for ordering**:
        candidates are ranked by the entry's `created_at` ascending, and ties
        broken by the guest's `email` ascending."

        Design: Difficulty/dual_variant_calc/waitlist_priority_score_fair_queue_vs_yield_weighted
        """
        world = _two_policy_world(api)
        early_headers = make_guest_headers(world["waiter_early"]["id"])
        late_headers = make_guest_headers(world["waiter_late"]["id"])

        # The score is computed and stored regardless of the policy in force.
        early_entry = FX.read_waitlist_entry(
            api, world["entries"][("fair", "early")]["id"], early_headers
        )
        late_entry = FX.read_waitlist_entry(
            api, world["entries"][("fair", "late")]["id"], late_headers
        )
        assert early_entry["priority_score"] == 1100
        assert late_entry["priority_score"] == 1150

        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, world["holder_fair"]["id"], world["holder"]["id"])

        promoted = FX.read_waitlist_entry(
            api, world["entries"][("fair", "early")]["id"], early_headers
        )
        passed_over = FX.read_waitlist_entry(
            api, world["entries"][("fair", "late")]["id"], late_headers
        )
        assert promoted["status"] == "OFFERED"
        assert promoted["offered_reservation_id"] is not None
        # Promotion does not burn a round; only a lapsed offer credits one.
        assert promoted["offer_round"] == 0
        assert passed_over["status"] == "WAITING"
        assert passed_over["offer_round"] == 0
        assert passed_over["offered_reservation_id"] is None

        # Two of the three freed seats are now held for the promoted party.
        tc_fair = FX.read_ticket_class(api, world["tc_fair"]["id"], world["manager"])
        A.assert_seat_pool(
            tc_fair, sold=0, held=2, released=0, available=1, status="OPEN"
        )

    def test_yield_weighted_promotes_the_higher_score_over_the_earlier_arrival(
        self, api
    ):
        """YIELD_WEIGHTED reverses the winner on identical inputs.

        "Under `YIELD_WEIGHTED` candidates are ranked by `priority_score`
        descending, then by the entry's `created_at` ascending, then by the
        guest's `email` ascending."

        Design: Difficulty/dual_variant_calc/waitlist_priority_score_fair_queue_vs_yield_weighted
        """
        world = _two_policy_world(api)
        early_headers = make_guest_headers(world["waiter_early"]["id"])
        late_headers = make_guest_headers(world["waiter_late"]["id"])

        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, world["holder_yield"]["id"], world["holder"]["id"])

        promoted = FX.read_waitlist_entry(
            api, world["entries"][("yield", "late")]["id"], late_headers
        )
        passed_over = FX.read_waitlist_entry(
            api, world["entries"][("yield", "early")]["id"], early_headers
        )
        assert promoted["priority_score"] == 1150
        assert promoted["status"] == "OFFERED"
        assert promoted["offered_reservation_id"] is not None
        assert promoted["offer_round"] == 0
        assert passed_over["priority_score"] == 1100
        assert passed_over["status"] == "WAITING"

        # The party of three swallows all three freed seats.
        tc_yield = FX.read_ticket_class(api, world["tc_yield"]["id"], world["manager"])
        A.assert_seat_pool(
            tc_yield, sold=0, held=3, released=0, available=0, status="SOLD_OUT"
        )
