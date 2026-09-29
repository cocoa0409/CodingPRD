"""
Single requests whose consequences propagate across several entities: a release
run that releases seats, promotes two waitlist entries and drains the released
pool again inside one call; a cancellation that settles the ladder, returns
seats to ordinary availability and promotes exactly one entry; and a refund
exception approval that rewrites the ledger, crosses a guest's lifetime-refund
threshold and re-derives that guest's waitlist standing.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import (
    CARE_DECIDER_HEADERS,
    GUEST_SERVICES_DECIDER_ID,
    make_guest_headers,
    make_restaurant_headers,
)

# 2026-09-12 is a Saturday, the strongest day-of-week factor at 12500 basis
# points; combined with the HIGH demand tier's 12000 it clamps to 15000, so a
# 12000-cent cover lists at 18000 cents.
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"
SETUP_AT = "2026-09-01T00:00:00Z"
# The release window opens at seating_start less release_lead_minutes of 180,
# that is at 19:00; 20:00 is inside it.
RELEASE_RUN_AT = "2026-09-12T20:00:00Z"
# Exactly 48.0 hours before the seating instant.
CANCEL_AT_48H = "2026-09-10T22:00:00Z"

LIST_PRICE_PER_COVER = 18000


def _instants_equal(actual, expected):
    """Compare two ISO 8601 UTC instants irrespective of fractional digits."""
    assert actual is not None, f"expected the instant {expected}, got null"
    return F.parse_iso(actual) == F.parse_iso(expected)


def _offered_hold(api, entry, headers):
    """The PENDING hold reservation a promotion minted for a waitlist entry."""
    assert entry["offered_reservation_id"], (
        "a promoted entry must name the hold reservation it was offered"
    )
    return FX.read_reservation(api, entry["offered_reservation_id"], headers)


def _release_world(api):
    """A published Saturday HIGH service whose single 6-seat class carries one
    CONFIRMED party of 2, with two party-of-2 entries waiting behind it.

    The service releases the whole of an open class's remaining availability
    (unsold_release_bp 10000), so the run has 4 seats to hand to the waitlist.
    """
    FX.set_clock(api, SETUP_AT)
    restaurant = FX.create_restaurant(
        api,
        name=f"Aurum Release {F.unique_suffix()}",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        release_discount_bp=1500,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=6,
        demand_tier="HIGH",
        unsold_release_bp=10000,
        release_lead_minutes=180,
        waitlist_policy="YIELD_WEIGHTED",
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=6,
        min_party_size=1,
        max_party_size=6,
    )
    FX.publish_service(api, restaurant["id"], service["id"])

    holder = FX.create_guest(api, display_name="Release Holder")
    waiter_a = FX.create_guest(api, display_name="Release Waiter A")
    waiter_b = FX.create_guest(api, display_name="Release Waiter B")

    holder_reservation = FX.confirmed_reservation(
        api, ticket_class["id"], holder["id"], party_size=2
    )
    entry_a = FX.join_waitlist(api, service["id"], waiter_a["id"], party_size=2)
    entry_b = FX.join_waitlist(api, service["id"], waiter_b["id"], party_size=2)

    FX.set_clock(api, RELEASE_RUN_AT)
    return {
        "restaurant": restaurant,
        "manager": make_restaurant_headers(restaurant["id"]),
        "package": package,
        "service": service,
        "ticket_class": ticket_class,
        "holder": holder,
        "holder_reservation": holder_reservation,
        "waiter_a": waiter_a,
        "waiter_b": waiter_b,
        "entry_a": entry_a,
        "entry_b": entry_b,
        "headers_a": make_guest_headers(waiter_a["id"]),
        "headers_b": make_guest_headers(waiter_b["id"]),
    }


class TestReleaseRunCascade:
    """One release run moves the seat pool, offers two entries and closes the
    class again before the response is written."""

    def test_release_pass_then_promotions_leave_the_class_sold_out(self, api):
        """The released pool is credited and then wholly drawn into holds.

        "A class that released seats moves `OPEN → RELEASED` or `SOLD_OUT →
        RELEASED`, and if the promotion pass then draws the whole released pool
        into holds the same class moves `RELEASED → SOLD_OUT` inside the same
        request."

        Design: Difficulty/transitive_cascade/release_run_cascade_to_double_promotion_and_sold_out
        """
        world = _release_world(api)
        before = FX.read_ticket_class(
            api, world["ticket_class"]["id"], world["manager"]
        )
        A.assert_seat_pool(
            before, sold=2, held=0, released=0, available=4, status="OPEN"
        )
        # The count to release is the floor of seats_available multiplied by
        # unsold_release_bp divided by 10000, so a partial seat never moves.
        assert C.release_seat_count(4, 10000) == 4

        FX.run_release(api, world["restaurant"]["id"], world["service"]["id"])

        after = FX.read_ticket_class(api, world["ticket_class"]["id"], world["manager"])
        A.assert_seat_pool(
            after, sold=2, held=4, released=0, available=0, status="SOLD_OUT"
        )
        # The four seats were credited to the released pool and then drawn out
        # of it by the two promotions of the same request.
        service = FX.read_service(api, world["service"]["id"], world["manager"])
        assert service["last_release_released_count"] == 4
        assert service["last_release_promoted_count"] == 2
        assert service["release_run_count"] == 1
        assert service["seats_released_total"] == 4
        # A promotion mints a hold, so no cover became confirmed.
        assert service["covers_confirmed"] == 2

    def test_both_waiting_entries_are_offered_with_pinned_expiries(self, api):
        """Each promotion mints a PENDING hold and stamps the offer expiry.

        "It mints a `PENDING` `Reservation` for the entry's guest, stores its id
        on `offered_reservation_id`, credits `party_size` to the class's
        `seats_held`, debits the same count from the drawing pool, and sets
        `offer_expires_at_utc` to the logical clock plus the restaurant's
        `offer_ttl_minutes`."

        Design: Difficulty/transitive_cascade/release_run_cascade_to_double_promotion_and_sold_out
        """
        world = _release_world(api)
        FX.run_release(api, world["restaurant"]["id"], world["service"]["id"])

        entry_a = FX.read_waitlist_entry(
            api, world["entry_a"]["id"], world["headers_a"]
        )
        entry_b = FX.read_waitlist_entry(
            api, world["entry_b"]["id"], world["headers_b"]
        )
        for entry in (entry_a, entry_b):
            assert entry["status"] == "OFFERED"
            # An offer_round is credited only when an offer lapses, never when
            # it is made.
            assert entry["offer_round"] == 0
            assert _instants_equal(
                entry["offer_expires_at_utc"], "2026-09-12T20:15:00Z"
            )

        hold_a = _offered_hold(api, entry_a, world["headers_a"])
        hold_b = _offered_hold(api, entry_b, world["headers_b"])
        assert hold_a["guest_id"] == world["waiter_a"]["id"]
        assert hold_b["guest_id"] == world["waiter_b"]["id"]
        for hold in (hold_a, hold_b):
            A.assert_fulfillment_status(hold, "PENDING")
            A.assert_payment_status(hold, "UNPAID")
            assert hold["party_size"] == 2
            assert hold["amount_paid_cents"] == 0
            assert _instants_equal(
                hold["hold_expires_at_utc"], "2026-09-12T20:20:00Z"
            )

    def test_second_promotion_is_priced_past_the_scarcity_step_it_crossed(self, api):
        """Both holds are release-priced, and the second costs more.

        "A release-run promotion draws **only** from `seats_released` and mints
        a hold with `is_release_priced` true, so the guest is quoted the
        discounted `release_price_per_cover_cents`."

        Design: Difficulty/transitive_cascade/release_run_cascade_to_double_promotion_and_sold_out
        """
        world = _release_world(api)
        FX.run_release(api, world["restaurant"]["id"], world["service"]["id"])

        entry_a = FX.read_waitlist_entry(
            api, world["entry_a"]["id"], world["headers_a"]
        )
        entry_b = FX.read_waitlist_entry(
            api, world["entry_b"]["id"], world["headers_b"]
        )
        # The earlier arrival was served first: both entries score 1100, so the
        # tie broke on created_at ascending.
        assert C.priority_score(2) == 1100
        assert entry_a["priority_score"] == 1100
        assert entry_b["priority_score"] == 1100
        assert F.parse_iso(entry_a["created_at"]) <= F.parse_iso(
            entry_b["created_at"]
        )

        hold_a = _offered_hold(api, entry_a, world["headers_a"])
        hold_b = _offered_hold(api, entry_b, world["headers_b"])
        assert hold_a["is_release_priced"] is True
        assert hold_b["is_release_priced"] is True

        # The first promotion saw sold 2 and held 0 out of 6 — a sell-through of
        # 3333 basis points, below the first scarcity step.
        assert C.sell_through_bp(2, 0, 6) == 3333
        assert C.release_price_per_cover(LIST_PRICE_PER_COVER, 1500) == 15300
        assert hold_a["price_locked_per_cover_cents"] == 15300

        # The second promotion saw sold 2 and held 2 out of 6 — 6666 basis
        # points, which has reached the 5000 step of 800 basis points.
        assert C.sell_through_bp(2, 2, 6) == 6666
        assert C.scarcity_step_bp(6666) == 800
        assert C.release_price_per_cover(
            C.list_price_per_cover(12000, "SAT", "HIGH", 6666), 1500
        ) == 16524
        assert hold_b["price_locked_per_cover_cents"] == 16524

        breakdown_a = C.charge_breakdown(15300, 2, 725)
        A.assert_money_breakdown(
            hold_a,
            ticket_subtotal=30600,
            service_charge=2219,
            grand_total=32819,
        )
        assert breakdown_a["grand_total_cents"] == 32819
        breakdown_b = C.charge_breakdown(16524, 2, 725)
        A.assert_money_breakdown(
            hold_b,
            ticket_subtotal=33048,
            service_charge=2396,
            grand_total=35444,
        )
        assert breakdown_b["grand_total_cents"] == 35444


def _cancel_world(api):
    """A published Saturday HIGH service whose single 2-seat class is SOLD_OUT
    behind one CONFIRMED, deposit-paid party of 2, with two party-of-2 entries
    waiting.

    The clock is left at exactly 48.0 hours before the seating instant, the
    figure the settlement procedure is worked out against.
    """
    FX.set_clock(api, SETUP_AT)
    restaurant = FX.create_restaurant(
        api,
        name=f"Aurum Cancel {F.unique_suffix()}",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=2,
        demand_tier="HIGH",
        unsold_release_bp=5000,
        release_lead_minutes=180,
        waitlist_policy="YIELD_WEIGHTED",
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=2,
        min_party_size=1,
        max_party_size=2,
    )
    FX.publish_service(api, restaurant["id"], service["id"])

    holder = FX.create_guest(api, display_name="Cancel Holder")
    waiter_one = FX.create_guest(api, display_name="Cancel Waiter One")
    waiter_two = FX.create_guest(api, display_name="Cancel Waiter Two")

    holder_reservation = FX.confirmed_reservation(
        api, ticket_class["id"], holder["id"], party_size=2
    )
    entry_one = FX.join_waitlist(api, service["id"], waiter_one["id"], party_size=2)
    entry_two = FX.join_waitlist(api, service["id"], waiter_two["id"], party_size=2)

    FX.set_clock(api, CANCEL_AT_48H)
    return {
        "restaurant": restaurant,
        "manager": make_restaurant_headers(restaurant["id"]),
        "service": service,
        "ticket_class": ticket_class,
        "holder": holder,
        "holder_reservation": holder_reservation,
        "holder_headers": make_guest_headers(holder["id"]),
        "waiter_one": waiter_one,
        "waiter_two": waiter_two,
        "entry_one": entry_one,
        "entry_two": entry_two,
        "headers_one": make_guest_headers(waiter_one["id"]),
        "headers_two": make_guest_headers(waiter_two["id"]),
    }


class TestCancelCascade:
    """A cancellation settles the ladder, hands the freed seats back to ordinary
    availability, and offers them on at list price."""

    def test_settlement_and_seat_return_close_the_class_again(self, api):
        """The class ends on the status it started on, with every pool moved.

        "Under `DEPOSIT_BASIS` the raw forfeiture is 5792 cents, the fee 500
        cents, the retention 6292 cents and the refund 5291 cents, leaving the
        money dimension `PARTIALLY_REFUNDED`."

        Design: Difficulty/transitive_cascade/cancel_cascade_returns_class_to_sold_out_via_available_pool
        """
        world = _cancel_world(api)
        before = FX.read_ticket_class(
            api, world["ticket_class"]["id"], world["manager"]
        )
        A.assert_seat_pool(
            before, sold=2, held=0, released=0, available=0, status="SOLD_OUT"
        )
        A.assert_money_breakdown(
            world["holder_reservation"],
            ticket_subtotal=36000,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=11583,
        )

        FX.cancel(api, world["holder_reservation"]["id"], world["holder"]["id"])

        settled = FX.read_reservation(
            api, world["holder_reservation"]["id"], world["holder_headers"]
        )
        A.assert_fulfillment_status(settled, "CANCELLED")
        A.assert_payment_status(settled, "PARTIALLY_REFUNDED")
        assert settled["forfeited_cents"] == 6292
        assert settled["refunded_cents"] == 5291
        assert settled["cancel_settlement_basis"] == "DEPOSIT_BASIS"
        A.assert_settled_ledger_identity(settled)
        expected = C.settle_cancellation(
            11583, 11583, 38610, "STANDARD", "DEPOSIT_BASIS", 48.0
        )
        assert expected["forfeited_cents"] == 6292
        assert expected["refunded_cents"] == 5291

        # Two seats left seats_sold for seats_available and were immediately
        # taken back out of it by the promotion the transition fired.
        after = FX.read_ticket_class(api, world["ticket_class"]["id"], world["manager"])
        A.assert_seat_pool(
            after, sold=0, held=2, released=0, available=0, status="SOLD_OUT"
        )
        service = FX.read_service(api, world["service"]["id"], world["manager"])
        assert service["covers_confirmed"] == 0
        assert service["refunded_cents"] == 5291
        assert service["forfeited_cents"] == 6292

    def test_exactly_one_entry_is_promoted_onto_the_freed_seats(self, api):
        """The transition promotes a single entry, not every entry that fits.

        "It debits `party_size` from `seats_sold`, returns the seats to
        `seats_available`, re-evaluates the precedence ladder and promotes the
        highest-ranked eligible waitlist entry on a `SOLD_OUT → OPEN`
        transition, debits the service's `covers_confirmed`, credits the
        service's `refunded_cents` and `forfeited_cents`, recomputes
        `net_settled_cents`, and advances the reservation's `version` by one."

        Design: Difficulty/transitive_cascade/cancel_cascade_returns_class_to_sold_out_via_available_pool
        """
        world = _cancel_world(api)
        FX.cancel(api, world["holder_reservation"]["id"], world["holder"]["id"])

        entry_one = FX.read_waitlist_entry(
            api, world["entry_one"]["id"], world["headers_one"]
        )
        entry_two = FX.read_waitlist_entry(
            api, world["entry_two"]["id"], world["headers_two"]
        )
        assert entry_one["status"] == "OFFERED"
        assert entry_one["offer_round"] == 0
        assert _instants_equal(
            entry_one["offer_expires_at_utc"], "2026-09-10T22:15:00Z"
        )
        assert entry_two["status"] == "WAITING"
        assert entry_two["offered_reservation_id"] is None
        assert entry_two["offer_expires_at_utc"] is None

        hold = _offered_hold(api, entry_one, world["headers_one"])
        A.assert_fulfillment_status(hold, "PENDING")
        A.assert_payment_status(hold, "UNPAID")
        assert hold["guest_id"] == world["waiter_one"]["id"]
        assert _instants_equal(hold["hold_expires_at_utc"], "2026-09-10T22:20:00Z")

    def test_the_promoted_hold_is_list_priced_from_ordinary_availability(self, api):
        """A cancel-driven offer carries no release discount.

        "A cancel-driven or no-show-driven promotion draws **only** from
        `seats_available` and mints a hold with `is_release_priced` false, so the
        guest is quoted the full `list_price_per_cover_cents`."

        Design: Difficulty/transitive_cascade/cancel_cascade_returns_class_to_sold_out_via_available_pool
        """
        world = _cancel_world(api)
        FX.cancel(api, world["holder_reservation"]["id"], world["holder"]["id"])

        entry_one = FX.read_waitlist_entry(
            api, world["entry_one"]["id"], world["headers_one"]
        )
        hold = _offered_hold(api, entry_one, world["headers_one"])
        assert hold["is_release_priced"] is False
        assert hold["price_locked_per_cover_cents"] == LIST_PRICE_PER_COVER
        assert C.list_price_per_cover(12000, "SAT", "HIGH", 0) == LIST_PRICE_PER_COVER
        A.assert_money_breakdown(
            hold,
            ticket_subtotal=36000,
            service_charge=2610,
            grand_total=38610,
            amount_paid=0,
        )
        # The discounted figure the class also publishes was deliberately not
        # used for this hold.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class"]["id"], world["manager"]
        )
        assert ticket_class["release_price_per_cover_cents"] != (
            hold["price_locked_per_cover_cents"]
        )
        # No release run took place, so the run counters never moved.
        service = FX.read_service(api, world["service"]["id"], world["manager"])
        assert service["release_run_count"] == 0
        assert service["last_release_released_count"] == 0
        assert service["last_release_promoted_count"] == 0


def _scrutiny_world(api):
    """A guest whose 48-hour cancellation refunded 5291 cents against a 6000-cent
    scrutiny threshold, who is now waiting on the same service, and whose
    3000-cent refund exception is still REQUESTED.

    5291 is under the threshold, so nothing is flagged yet: only the exception's
    approval can push the lifetime total over it.
    """
    FX.set_clock(api, SETUP_AT)
    restaurant = FX.create_restaurant(
        api,
        name=f"Aurum Scrutiny {F.unique_suffix()}",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        refund_scrutiny_threshold_cents=6000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
        unsold_release_bp=5000,
        release_lead_minutes=180,
        waitlist_policy="YIELD_WEIGHTED",
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

    guest = FX.create_guest(api, display_name="Scrutiny Guest")
    guest_headers = make_guest_headers(guest["id"])
    reservation = FX.confirmed_reservation(
        api, ticket_class["id"], guest["id"], party_size=2
    )
    FX.set_clock(api, CANCEL_AT_48H)
    FX.cancel(api, reservation["id"], guest["id"])
    entry = FX.join_waitlist(api, service["id"], guest["id"], party_size=2)
    exception = FX.file_refund_exception(
        api,
        reservation["id"],
        3000,
        headers=guest_headers,
        reason_code="KITCHEN_ERROR",
    )
    return {
        "restaurant": restaurant,
        "manager": make_restaurant_headers(restaurant["id"]),
        "service": service,
        "guest": guest,
        "guest_headers": guest_headers,
        "reservation": reservation,
        "entry": entry,
        "exception": exception,
    }


def _approve(api, world):
    """Adjudicate the filed exception in full, with an operator distinct from the
    guest who filed it."""
    return FX.decide_refund_exception(
        api,
        world["exception"]["id"],
        decision="APPROVED",
        approved_cents=3000,
        decision_note_code="PARTIAL_GOODWILL",
        headers=CARE_DECIDER_HEADERS,
    )


class TestRefundApprovalCascade:
    """One approval rewrites the ledger, moves a guest counter across a threshold
    and re-derives that guest's waitlist standing."""

    def test_approval_writes_the_reversal_and_refund_pair(self, api):
        """The compensating pair keeps the settled identity intact.

        "The reservation is credited a `FORFEITURE_REVERSAL` row of
        `approved_cents` and debited a `REFUND` row of the same
        `approved_cents`, both with `memo_code` `REFUND_EXCEPTION`, which keeps
        the signed ledger sum aligned with `amount_paid_cents` less
        `refunded_cents` less `forfeited_cents`; the reservation's
        `forfeited_cents` is debited and its `refunded_cents` credited by
        `approved_cents`."

        Design: Difficulty/transitive_cascade/refund_approval_cascade_flags_guest_and_repriorities_waitlist
        """
        world = _scrutiny_world(api)
        decided = _approve(api, world)

        assert decided["status"] == "APPROVED"
        assert decided["approved_cents"] == 3000
        # shortfall_cents is requested_cents less approved_cents.
        assert decided["shortfall_cents"] == 0
        assert decided["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID

        reservation = FX.read_reservation(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        assert reservation["refunded_cents"] == 8291
        assert reservation["forfeited_cents"] == 3292
        assert reservation["amount_paid_cents"] == 11583
        A.assert_payment_status(reservation, "PARTIALLY_REFUNDED")
        A.assert_settled_ledger_identity(reservation)

        rows = FX.ledger_rows(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        exception_rows = [
            row for row in rows if row["memo_code"] == "REFUND_EXCEPTION"
        ]
        assert sorted(row["kind"] for row in exception_rows) == [
            "FORFEITURE_REVERSAL",
            "REFUND",
        ]
        by_kind = {row["kind"]: row for row in exception_rows}
        assert by_kind["FORFEITURE_REVERSAL"]["amount_cents"] == 3000
        assert by_kind["REFUND"]["amount_cents"] == 3000
        for row in rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)
        A.assert_derived_ledger_figures(reservation, rows)
        A.assert_signed_sum_matches(reservation, rows)

    def test_the_new_refund_row_crosses_the_scrutiny_threshold(self, api):
        """The lifetime total was under the threshold and the approval takes it over.

        "If the running lifetime total then stands **strictly greater than** the
        restaurant's `refund_scrutiny_threshold_cents`, the guest's
        `refund_scrutiny_flag` is raised to true, and every one of that guest's
        waitlist entries **whose status is `WAITING` at that moment** has its
        `priority_penalty_applied` set to true and its `priority_score`
        re-derived."

        Design: Difficulty/transitive_cascade/refund_approval_cascade_flags_guest_and_repriorities_waitlist
        """
        world = _scrutiny_world(api)
        before = FX.read_guest(api, world["guest"]["id"], world["guest_headers"])
        # The cancellation's own refund alone stays under the 6000-cent bar.
        assert before["lifetime_refunded_cents"] == 5291
        assert before["refund_scrutiny_flag"] is False

        _approve(api, world)

        after = FX.read_guest(api, world["guest"]["id"], world["guest_headers"])
        assert after["lifetime_refunded_cents"] == 8291
        assert after["refund_scrutiny_flag"] is True
        assert after["lifetime_refunded_cents"] > world["restaurant"][
            "refund_scrutiny_threshold_cents"
        ]

    def test_the_waiting_entry_is_penalised_without_leaving_waiting(self, api):
        """The penalty reaches the entry's score but not the entry's state.

        "For a party of 2 with a clean record the score is 1100; one no-show
        strike takes it to 800; one burned offer round takes it to 1000; a
        scrutiny penalty takes it to 900."

        Design: Difficulty/transitive_cascade/refund_approval_cascade_flags_guest_and_repriorities_waitlist
        """
        world = _scrutiny_world(api)
        before = FX.read_waitlist_entry(
            api, world["entry"]["id"], world["guest_headers"]
        )
        assert before["status"] == "WAITING"
        assert before["priority_penalty_applied"] is False
        assert before["priority_score"] == 1100

        _approve(api, world)

        after = FX.read_waitlist_entry(
            api, world["entry"]["id"], world["guest_headers"]
        )
        assert after["priority_penalty_applied"] is True
        assert after["priority_score"] == 900
        assert C.priority_score(2, priority_penalty_applied=True) == 900
        assert after["status"] == "WAITING"
        assert after["offer_round"] == 0
