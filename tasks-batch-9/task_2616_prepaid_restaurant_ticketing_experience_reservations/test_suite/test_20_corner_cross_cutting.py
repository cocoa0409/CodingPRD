"""
Three cross-cutting layers probed call by call on one Thursday service: which
row a write is allowed to version, whether a rejected adjudication leaves any
part of its cascade behind, and whether the seat pool and its derived
sell-through follow every single source change.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import (
    CARE_DECIDER_HEADERS,
    CARE_FILER_HEADERS,
    GUEST_SERVICES_DECIDER_ID,
    make_guest_headers,
    make_restaurant_headers,
)

# The Thursday every scenario below trades on. Thursday is neutral at 10000
# basis points and the STANDARD tier is neutral too, so a 12000-cent base price
# stays at 12000 cents per cover and every figure below is a clean literal.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
SEATING_START = "2026-09-10T22:00:00Z"
SEATING_END = "2026-09-11T02:00:00Z"


def _assert_unchanged(label, before, after):
    """Assert a re-read resource is identical to its earlier snapshot."""
    assert after == before, (
        f"{label} was expected to be untouched but changed:\n"
        f"  before: {before}\n"
        f"  after:  {after}"
    )


def _version_world(api):
    """A published Thursday service carrying two ticket classes and one add-on.

    The second class shares the service and the package but sells none of the
    seats the guest below buys, so it is the foreign parent no write may touch.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name="Corner Version House",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        goodwill_credit_cap_cents=20000,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Tasting Menu",
        course_count=8,
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        release_discount_bp=1500,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    add_on = FX.create_add_on(
        api,
        restaurant["id"],
        name="Caviar Supplement",
        price_cents=4500,
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=1440,
        requires_kitchen_ack=False,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=28,
        demand_tier="STANDARD",
        unsold_release_bp=5000,
        release_lead_minutes=180,
        waitlist_policy="FAIR_QUEUE",
        kitchen_prep_capacity_minutes=600,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=20,
        min_party_size=1,
        max_party_size=8,
    )
    other_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=8,
        min_party_size=1,
        max_party_size=8,
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest = FX.create_guest(
        api, email="version@corner.test", display_name="Version Guest"
    )
    return {
        "restaurant": restaurant,
        "package": package,
        "add_on": add_on,
        "service": service,
        "ticket_class_id": ticket_class["id"],
        "other_class_id": other_class["id"],
        "guest_id": guest["id"],
        "guest_headers": make_guest_headers(guest["id"]),
        "manager_headers": make_restaurant_headers(restaurant["id"]),
    }


class TestVersionMovesOnlyOnTheRowThatChanged:
    """Every declared write versions its own row, once, and nothing else."""

    def test_reads_never_version_and_the_create_versions_only_its_own_class(
        self, api
    ):
        """Two reads agree, then the create moves one class and not the other.

        "`version` is an integer that starts at 1 on creation and increments by
        exactly 1 on every mutation of that resource." The create's own effect
        is pinned: "`party_size` seats move out of `seats_available` and into
        `seats_held`, after which the class's status is re-derived against the
        precedence ladder and the class's `version` advances by one."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_version_increments_once_per_write_and_only_on_its_own_parent
        """
        world = _version_world(api)
        guest_headers = world["guest_headers"]

        first_read = FX.read_ticket_class(api, world["ticket_class_id"], guest_headers)
        second_read = FX.read_ticket_class(api, world["ticket_class_id"], guest_headers)
        _assert_unchanged("ticket class across two reads", first_read, second_read)

        foreign_before = FX.read_ticket_class(
            api, world["other_class_id"], guest_headers
        )

        reservation = get_success_data(
            api.create_reservation(
                F.reservation_payload(
                    world["ticket_class_id"],
                    world["guest_id"],
                    second_read["version"],
                    party_size=2,
                    primary_guest_name="Version Guest",
                ),
                guest_headers,
            )
        )
        A.assert_common_fields(reservation)
        assert reservation["version"] == 1, (
            "a freshly created reservation starts at version 1, got "
            f"{reservation['version']}"
        )

        # Half one: the OCC parent the create committed against moved once.
        sold_class = FX.read_ticket_class(api, world["ticket_class_id"], guest_headers)
        A.assert_version_advanced_by(sold_class["version"], second_read["version"])
        A.assert_seat_pool(
            sold_class, sold=0, held=2, released=0, available=18, status="OPEN"
        )

        # Half two: the sibling class of the same service is byte-identical.
        foreign_after = FX.read_ticket_class(api, world["other_class_id"], guest_headers)
        _assert_unchanged("foreign ticket class", foreign_before, foreign_after)

    def test_each_add_on_append_versions_the_reservation_once_and_the_class_never(
        self, api
    ):
        """Two appends, two increments on the reservation, none on the class.

        "Add-on lines are additive and the same add-on may legitimately appear
        on several lines, so no state rule refuses a second append; the hazard
        is that the client's picture of `grand_total_cents` and
        `balance_due_cents` predates another line or a credit redemption, and
        the per-cover quantity ceiling would then be evaluated against stale
        totals." The totals the second append lands on are pinned too:
        "`grand_total_cents` is `ticket_subtotal_cents` plus
        `add_on_total_cents` plus `service_charge_cents`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_version_increments_once_per_write_and_only_on_its_own_parent
        """
        world = _version_world(api)
        guest_headers = world["guest_headers"]
        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Version Guest",
        )
        class_before = FX.read_ticket_class(
            api, world["ticket_class_id"], guest_headers
        )

        get_success_data(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(
                    world["add_on"]["id"], reservation["version"], qty=1
                ),
                guest_headers,
            )
        )
        after_first = FX.read_reservation(api, reservation["id"], guest_headers)
        A.assert_version_advanced_by(after_first["version"], reservation["version"])

        # The client refreshed the version before appending again, which is the
        # whole point of the echoed field, so the second append is accepted.
        get_success_data(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(
                    world["add_on"]["id"], after_first["version"], qty=1
                ),
                guest_headers,
            )
        )
        after_second = FX.read_reservation(api, reservation["id"], guest_headers)
        A.assert_version_advanced_by(after_second["version"], after_first["version"])

        # 4500 * 725 / 10000 rounds half up to 326 on each line of its own.
        A.assert_money_breakdown(
            after_second,
            ticket_subtotal=24000,
            add_on_total=9000,
            service_charge=2392,
            grand_total=35392,
            deposit_due=10618,
        )
        assert after_second["prep_minutes_total"] == 32, (
            "prep_minutes_total should be 2 * 12 + 4 + 4 = 32, got "
            f"{after_second['prep_minutes_total']}"
        )

        # Neither append moved a seat, so the class is byte-identical.
        class_after = FX.read_ticket_class(api, world["ticket_class_id"], guest_headers)
        _assert_unchanged("ticket class across two appends", class_before, class_after)

    def test_payment_and_confirm_each_version_the_reservation_exactly_once(
        self, api
    ):
        """The money write and the confirm write take one increment each.

        "Confirming clears `hold_expires_at_utc` to null, sets `deposit_frozen`
        to true and so freezes `deposit_due_cents` against every later add-on
        or price change, debits `party_size` from the class's `seats_held` and
        credits the same count to `seats_sold` so that the pool total is
        unchanged, credits `party_size` to the service's `covers_confirmed`,
        and advances the reservation's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_version_increments_once_per_write_and_only_on_its_own_parent
        """
        world = _version_world(api)
        guest_headers = world["guest_headers"]
        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Version Guest",
        )
        for _ in range(2):
            FX.append_add_on_line(
                api, reservation["id"], world["guest_id"], world["add_on"]["id"], qty=1
            )
        before_payment = FX.read_reservation(api, reservation["id"], guest_headers)
        assert before_payment["deposit_due_cents"] == 10618
        class_before_payment = FX.read_ticket_class(
            api, world["ticket_class_id"], guest_headers
        )

        paid = get_success_data(
            api.take_payment(
                reservation["id"], F.payment_payload(10618), guest_headers
            )
        )
        A.assert_version_advanced_by(paid["version"], before_payment["version"])
        A.assert_payment_status(paid, "DEPOSIT_PAID")
        assert paid["deposit_frozen"] is True

        # The payment moved no seat, so its parent class is byte-identical.
        class_after_payment = FX.read_ticket_class(
            api, world["ticket_class_id"], guest_headers
        )
        _assert_unchanged(
            "ticket class across the payment", class_before_payment, class_after_payment
        )

        confirmed = get_success_data(
            api.confirm_reservation(reservation["id"], guest_headers)
        )
        A.assert_version_advanced_by(confirmed["version"], paid["version"])
        A.assert_fulfillment_status(confirmed, "CONFIRMED")
        assert confirmed["deposit_frozen"] is True
        A.assert_money_breakdown(
            confirmed,
            grand_total=35392,
            deposit_due=10618,
            amount_paid=10618,
        )
        assert confirmed["balance_due_cents"] == 24774


def _atomic_world(api):
    """A COMPLETED, fully paid party of 2 with a filed exception it cannot win.

    The reservation ran the whole floor cycle without ever settling, so its
    `forfeited_cents` stands at 0 and any approval at all breaks the forfeiture
    ceiling while staying inside the requested and paid ceilings. The same guest
    also holds a WAITING entry on a second service of the same restaurant, which
    is the far end of the approval cascade.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name="Corner Atomic House",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        goodwill_credit_cap_cents=20000,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    manager_headers = make_restaurant_headers(restaurant["id"])
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Tasting Menu",
        course_count=8,
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        release_discount_bp=1500,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="STANDARD",
        kitchen_prep_capacity_minutes=600,
    )
    second_service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-20",
        meal_period="DINNER",
        seating_start_utc="2026-09-20T22:00:00Z",
        seating_end_utc="2026-09-21T02:00:00Z",
        turn_time_minutes=150,
        seats_capacity=4,
        demand_tier="STANDARD",
        kitchen_prep_capacity_minutes=600,
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.create_ticket_class(
        api, restaurant["id"], second_service["id"], package["id"], seats_allocated=4
    )
    table = FX.create_table(
        api, restaurant["id"], table_code="T1", seats_min=2, seats_max=4
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    FX.publish_service(api, restaurant["id"], second_service["id"])
    guest = FX.create_guest(
        api, email="atomic@corner.test", display_name="Atomic Guest"
    )
    guest_headers = make_guest_headers(guest["id"])

    reservation = FX.hold_seats(
        api,
        ticket_class["id"],
        guest["id"],
        party_size=2,
        primary_guest_name="Atomic Guest",
    )
    # The deposit first, then the balance, so the ledger carries two inbound
    # rows in ascending created_at order.
    FX.pay(api, reservation["id"], guest["id"], 7722)
    FX.pay(api, reservation["id"], guest["id"], 18018)
    FX.confirm(api, reservation["id"], guest["id"])
    entry = FX.join_waitlist(
        api,
        second_service["id"],
        guest["id"],
        party_size=2,
        requested_package_id=package["id"],
    )
    FX.assign_table(
        api, restaurant["id"], reservation["id"], table["id"], SEATING_START
    )
    FX.set_clock(api, SEATING_START)
    FX.seat(api, restaurant["id"], reservation["id"])
    FX.complete(api, restaurant["id"], reservation["id"])
    exception = FX.file_refund_exception(
        api,
        reservation["id"],
        1000,
        reason_code="KITCHEN_ERROR",
        headers=CARE_FILER_HEADERS,
    )
    return {
        "restaurant": restaurant,
        "manager_headers": manager_headers,
        "service_id": service["id"],
        "second_service_id": second_service["id"],
        "guest_id": guest["id"],
        "guest_headers": guest_headers,
        "reservation_id": reservation["id"],
        "entry_id": entry["id"],
        "exception_id": exception["id"],
    }


def _rejected_approval(api, exception_id):
    """Attempt the approval that breaks the forfeiture ceiling."""
    return api.decide_refund_exception(
        exception_id,
        F.decide_payload(
            decision="APPROVED",
            approved_cents=1000,
            decision_note_code="POLICY_EXCEPTION",
        ),
        CARE_DECIDER_HEADERS,
    )


class TestRejectedApprovalAppliesNoPartOfItsCascade:
    """The widest cascade in the domain, refused before any of it is written."""

    def test_the_refused_approval_leaves_the_exception_row_byte_identical(self, api):
        """Nothing on the exception moves when the approval is refused.

        "`approved_cents` does not exceed the reservation's current
        `forfeited_cents`, on decision, so that a reversal can never manufacture
        cash — otherwise `ERR_APPROVED_EXCEEDS_FORFEITED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_rejected_decide_leaves_no_half_applied_cascade
        """
        world = _atomic_world(api)
        completed = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(completed, "COMPLETED")
        A.assert_payment_status(completed, "FULLY_PAID")
        A.assert_money_breakdown(
            completed, amount_paid=25740, refunded=0, forfeited=0
        )

        before = get_success_data(
            api.get_refund_exception(world["exception_id"], CARE_DECIDER_HEADERS)
        )
        assert before["status"] == "REQUESTED"
        assert before["requested_cents"] == 1000

        refused = _rejected_approval(api, world["exception_id"])
        validate_error(refused, E.ERR_APPROVED_EXCEEDS_FORFEITED, 402)

        after = get_success_data(
            api.get_refund_exception(world["exception_id"], CARE_DECIDER_HEADERS)
        )
        _assert_unchanged("refund exception", before, after)
        assert after["status"] == "REQUESTED"
        assert after["approved_cents"] == 0
        assert after["shortfall_cents"] == 0
        assert after["decided_by_user_id"] is None
        assert after["decision_note_code"] is None

    def test_the_refused_approval_writes_no_ledger_row_and_moves_no_dependant(
        self, api
    ):
        """The ledger, the reservation, the guest and the entry all stand still.

        "The two arms then diverge completely, and the asymmetry is intentional:
        approval touches three entities, denial touches none." The furthest
        consequence is the guest's own record: "After **every** `REFUND` row is
        written — from any trigger, at any restaurant — the refunded amount is
        credited to that guest's `lifetime_refunded_cents`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_rejected_decide_leaves_no_half_applied_cascade
        """
        world = _atomic_world(api)
        rows_before = FX.ledger_rows(
            api, world["reservation_id"], CARE_DECIDER_HEADERS
        )
        assert [row["kind"] for row in rows_before] == [
            "DEPOSIT_CHARGE",
            "BALANCE_CHARGE",
        ]
        assert [row["amount_cents"] for row in rows_before] == [7722, 18018]
        reservation_before = FX.read_reservation(
            api, world["reservation_id"], CARE_DECIDER_HEADERS
        )
        guest_before = FX.read_guest(api, world["guest_id"], CARE_DECIDER_HEADERS)
        assert guest_before["lifetime_refunded_cents"] == 0
        assert guest_before["refund_scrutiny_flag"] is False
        entry_before = FX.read_waitlist_entry(
            api, world["entry_id"], CARE_DECIDER_HEADERS
        )
        assert entry_before["status"] == "WAITING"
        assert entry_before["priority_penalty_applied"] is False

        refused = _rejected_approval(api, world["exception_id"])
        validate_error(refused, E.ERR_APPROVED_EXCEEDS_FORFEITED, 402)

        rows_after = FX.ledger_rows(api, world["reservation_id"], CARE_DECIDER_HEADERS)
        _assert_unchanged("payment ledger", rows_before, rows_after)

        reservation_after = FX.read_reservation(
            api, world["reservation_id"], CARE_DECIDER_HEADERS
        )
        _assert_unchanged("reservation", reservation_before, reservation_after)
        A.assert_payment_status(reservation_after, "FULLY_PAID")
        A.assert_money_breakdown(
            reservation_after, amount_paid=25740, refunded=0, forfeited=0
        )

        guest_after = FX.read_guest(api, world["guest_id"], CARE_DECIDER_HEADERS)
        _assert_unchanged("guest", guest_before, guest_after)
        assert guest_after["lifetime_refunded_cents"] == 0
        assert guest_after["refund_scrutiny_flag"] is False

        entry_after = FX.read_waitlist_entry(
            api, world["entry_id"], CARE_DECIDER_HEADERS
        )
        _assert_unchanged("waitlist entry", entry_before, entry_after)
        assert entry_after["priority_penalty_applied"] is False
        assert entry_after["priority_score"] == entry_before["priority_score"]

    def test_the_exception_is_still_deniable_after_the_refused_approval(self, api):
        """The refusal left the row usable, and the denial writes only itself.

        "On denial, `approved_cents` stays at 0 and `shortfall_cents` becomes
        the whole of `requested_cents`." "No `PaymentTransaction` row of any
        kind is written, no reservation field moves, no guest counter moves, and
        — despite the non-zero `shortfall_cents` — no goodwill credit may be
        issued at all, because issuance requires an `APPROVED` exception and a
        `DENIED` one is refused with `ERR_REFUND_EXCEPTION_NOT_APPROVED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_rejected_decide_leaves_no_half_applied_cascade
        """
        world = _atomic_world(api)
        refused = _rejected_approval(api, world["exception_id"])
        validate_error(refused, E.ERR_APPROVED_EXCEEDS_FORFEITED, 402)

        rows_before = FX.ledger_rows(api, world["reservation_id"], CARE_DECIDER_HEADERS)
        guest_before = FX.read_guest(api, world["guest_id"], CARE_DECIDER_HEADERS)
        entry_before = FX.read_waitlist_entry(
            api, world["entry_id"], CARE_DECIDER_HEADERS
        )

        denied = get_success_data(
            api.decide_refund_exception(
                world["exception_id"],
                F.decide_payload(
                    decision="DENIED", decision_note_code="OUT_OF_POLICY"
                ),
                CARE_DECIDER_HEADERS,
            )
        )
        assert denied["status"] == "DENIED"
        assert denied["approved_cents"] == 0
        assert denied["shortfall_cents"] == 1000
        assert denied["decision_note_code"] == "OUT_OF_POLICY"
        assert denied["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID

        rows_after = FX.ledger_rows(api, world["reservation_id"], CARE_DECIDER_HEADERS)
        _assert_unchanged("payment ledger", rows_before, rows_after)
        guest_after = FX.read_guest(api, world["guest_id"], CARE_DECIDER_HEADERS)
        _assert_unchanged("guest", guest_before, guest_after)
        entry_after = FX.read_waitlist_entry(
            api, world["entry_id"], CARE_DECIDER_HEADERS
        )
        _assert_unchanged("waitlist entry", entry_before, entry_after)


def _derived_world(api):
    """A published Thursday service carrying one 20-seat class and two guests.

    One guest buys and confirms a party of 2; the other mints a party-of-3 hold
    and lets it lapse, so the class's counters are driven up and back down by
    two different kinds of source change.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name="Corner Derived House",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        goodwill_credit_cap_cents=20000,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Tasting Menu",
        course_count=8,
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        release_discount_bp=1500,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="STANDARD",
        unsold_release_bp=5000,
        release_lead_minutes=180,
        waitlist_policy="FAIR_QUEUE",
        kitchen_prep_capacity_minutes=600,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=20,
        min_party_size=1,
        max_party_size=8,
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    buyer = FX.create_guest(
        api, email="derived1@corner.test", display_name="Derived One"
    )
    lapser = FX.create_guest(
        api, email="derived2@corner.test", display_name="Derived Two"
    )
    return {
        "restaurant_id": restaurant["id"],
        "manager_headers": make_restaurant_headers(restaurant["id"]),
        "service_id": service["id"],
        "ticket_class_id": ticket_class["id"],
        "buyer_id": buyer["id"],
        "buyer_headers": make_guest_headers(buyer["id"]),
        "lapser_id": lapser["id"],
        "lapser_headers": make_guest_headers(lapser["id"]),
    }


def _reread_pool(
    api,
    world,
    headers,
    *,
    sold,
    held,
    released,
    available,
    status,
    sell_through,
):
    """Re-read the class and check its four counters against its derived pair.

    Every caller runs this immediately after a source change, so the counters,
    the summing invariant and the derived sell-through are re-checked at each
    step rather than only once at the end.
    """
    ticket_class = FX.read_ticket_class(api, world["ticket_class_id"], headers)
    A.assert_seat_pool(
        ticket_class,
        sold=sold,
        held=held,
        released=released,
        available=available,
        status=status,
    )
    assert ticket_class["sell_through_bp"] == sell_through, (
        f"sell_through_bp should read {sell_through} at sold={sold} held={held} "
        f"of 20, got {ticket_class['sell_through_bp']}"
    )
    return ticket_class


class TestSeatPoolAndSellThroughFollowEverySourceChange:
    """One class, five readings, one derived figure that must never drift."""

    def test_a_hold_lifts_sell_through_and_the_confirm_does_not_lift_it_again(
        self, api
    ):
        """The hold moves the derived figure; converting it to a sale does not.

        "Alongside those counters the class publishes `sell_through_bp`, the
        floor of ten thousand times the sum of `seats_sold` and `seats_held`
        divided by `seats_allocated`." "Note that a mere hold moves it: a
        `PENDING` reservation counts against sell-through exactly as a confirmed
        one does, so an unpaid hold can already push the class into a higher
        scarcity price step."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_seat_pool_and_sell_through_track_every_source_change
        """
        world = _derived_world(api)
        _reread_pool(
            api,
            world,
            world["buyer_headers"],
            sold=0,
            held=0,
            released=0,
            available=20,
            status="OPEN",
            sell_through=0,
        )

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["buyer_id"],
            party_size=2,
            primary_guest_name="Derived One",
        )
        assert reservation["deposit_due_cents"] == 7722
        _reread_pool(
            api,
            world,
            world["buyer_headers"],
            sold=0,
            held=2,
            released=0,
            available=18,
            status="OPEN",
            sell_through=1000,
        )

        FX.pay(api, reservation["id"], world["buyer_id"], 7722)
        _reread_pool(
            api,
            world,
            world["buyer_headers"],
            sold=0,
            held=2,
            released=0,
            available=18,
            status="OPEN",
            sell_through=1000,
        )

        confirmed = FX.confirm(api, reservation["id"], world["buyer_id"])
        A.assert_fulfillment_status(confirmed, "CONFIRMED")
        _reread_pool(
            api,
            world,
            world["buyer_headers"],
            sold=2,
            held=0,
            released=0,
            available=18,
            status="OPEN",
            sell_through=1000,
        )

    def test_the_second_hold_lifts_the_figure_and_the_sweep_re_derives_it_down(
        self, api
    ):
        """A lapsed hold hands its seats back and the derived pair follows.

        "For each swept reservation it debits `party_size` from `seats_held` and
        returns those seats **to the pool they came from** — to `seats_released`
        when the reservation's `is_release_priced` is true, and to
        `seats_available` otherwise, which is the whole reason that flag is
        persisted on the reservation." "The invariant is absolute:
        `seats_allocated` always equals `seats_sold` plus `seats_held` plus
        `seats_released` plus `seats_available`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_seat_pool_and_sell_through_track_every_source_change
        """
        world = _derived_world(api)
        sale = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["buyer_id"],
            party_size=2,
            primary_guest_name="Derived One",
        )
        FX.pay(api, sale["id"], world["buyer_id"], 7722)
        FX.confirm(api, sale["id"], world["buyer_id"])
        _reread_pool(
            api,
            world,
            world["buyer_headers"],
            sold=2,
            held=0,
            released=0,
            available=18,
            status="OPEN",
            sell_through=1000,
        )

        lapsing = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["lapser_id"],
            party_size=3,
            primary_guest_name="Derived Two",
        )
        assert lapsing["is_release_priced"] is False
        _reread_pool(
            api,
            world,
            world["lapser_headers"],
            sold=2,
            held=3,
            released=0,
            available=15,
            status="OPEN",
            sell_through=2500,
        )

        FX.set_clock(api, "2026-09-01T00:25:00Z")
        FX.sweep_holds(api, world["service_id"])
        swept = FX.read_reservation(api, lapsing["id"], world["lapser_headers"])
        A.assert_fulfillment_status(swept, "EXPIRED")
        _reread_pool(
            api,
            world,
            world["lapser_headers"],
            sold=2,
            held=0,
            released=0,
            available=18,
            status="OPEN",
            sell_through=1000,
        )

    def test_the_cancelled_sale_empties_the_numerator_and_the_service_rollups(
        self, api
    ):
        """The last source row leaves and every roll-up re-derives with it.

        "A service's `covers_confirmed` tracks the sum of party sizes over its
        reservations in `CONFIRMED`, `SEATED` or `COMPLETED`; its
        `gross_charged_cents` is the sum of inbound ledger magnitudes across its
        reservations; its `refunded_cents` and `forfeited_cents` are the
        corresponding outbound sums; and its `net_settled_cents` is
        `gross_charged_cents` minus `refunded_cents`." "It debits `party_size`
        from `seats_sold`, returns the seats to `seats_available`, re-evaluates
        the precedence ladder and promotes the highest-ranked eligible waitlist
        entry on a `SOLD_OUT → OPEN` transition, debits the service's
        `covers_confirmed`, credits the service's `refunded_cents` and
        `forfeited_cents`, recomputes `net_settled_cents`, and advances the
        reservation's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_seat_pool_and_sell_through_track_every_source_change
        """
        world = _derived_world(api)
        sale = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["buyer_id"],
            party_size=2,
            primary_guest_name="Derived One",
        )
        FX.pay(api, sale["id"], world["buyer_id"], 7722)
        FX.confirm(api, sale["id"], world["buyer_id"])
        _reread_pool(
            api,
            world,
            world["buyer_headers"],
            sold=2,
            held=0,
            released=0,
            available=18,
            status="OPEN",
            sell_through=1000,
        )
        after_sale = FX.read_service(
            api, world["service_id"], world["manager_headers"]
        )
        assert after_sale["covers_confirmed"] == 2
        assert after_sale["gross_charged_cents"] == 7722
        assert after_sale["refunded_cents"] == 0
        assert after_sale["forfeited_cents"] == 0
        assert after_sale["net_settled_cents"] == 7722

        FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["lapser_id"],
            party_size=3,
            primary_guest_name="Derived Two",
        )
        _reread_pool(
            api,
            world,
            world["lapser_headers"],
            sold=2,
            held=3,
            released=0,
            available=15,
            status="OPEN",
            sell_through=2500,
        )
        FX.set_clock(api, "2026-09-01T00:25:00Z")
        FX.sweep_holds(api, world["service_id"])
        _reread_pool(
            api,
            world,
            world["lapser_headers"],
            sold=2,
            held=0,
            released=0,
            available=18,
            status="OPEN",
            sell_through=1000,
        )
        # The lapsed hold never paid, so the service's cash roll-ups stand.
        after_sweep = FX.read_service(
            api, world["service_id"], world["manager_headers"]
        )
        assert after_sweep["covers_confirmed"] == 2
        assert after_sweep["gross_charged_cents"] == 7722
        assert after_sweep["net_settled_cents"] == 7722

        # Exactly 48.0 hours before seating.
        FX.set_clock(api, "2026-09-08T22:00:00Z")
        cancelled = FX.cancel(api, sale["id"], world["buyer_id"])
        A.assert_fulfillment_status(cancelled, "CANCELLED")
        assert cancelled["forfeited_cents"] == 4361
        assert cancelled["refunded_cents"] == 3361
        _reread_pool(
            api,
            world,
            world["buyer_headers"],
            sold=0,
            held=0,
            released=0,
            available=20,
            status="OPEN",
            sell_through=0,
        )
        after_cancel = FX.read_service(
            api, world["service_id"], world["manager_headers"]
        )
        assert after_cancel["covers_confirmed"] == 0
        assert after_cancel["gross_charged_cents"] == 7722
        assert after_cancel["refunded_cents"] == 3361
        assert after_cancel["forfeited_cents"] == 4361
        assert after_cancel["net_settled_cents"] == 4361
