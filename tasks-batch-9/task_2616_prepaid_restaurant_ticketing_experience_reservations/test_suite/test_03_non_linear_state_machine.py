"""
State machines that do not walk a single line: a reservation whose seating and
money dimensions advance on different triggers, a waitlist entry that loops
through OFFERED until a counter stops it, a dietary note that re-enters PENDING
through PREP_REJECTED, and a refund exception whose two terminal arms have
disjoint side effects.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import (
    CARE_DECIDER_HEADERS,
    CARE_ISSUER_HEADERS,
    GUEST_SERVICES_DECIDER_ID,
    make_guest_headers,
    make_kitchen_headers,
    make_restaurant_headers,
)

# 2026-09-12 is a Saturday, "the strongest day at 12500" basis points, and the
# demand tier below is HIGH at 12000, so a 12000-cent cover lists at 18000.
SERVICE_DATE = "2026-09-12"
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"
SETUP_CLOCK = "2026-09-01T00:00:00Z"

# The party-of-2 money picture every scenario below starts from.
LIST_PRICE_PER_COVER = 18000
TICKET_SUBTOTAL = 36000
SERVICE_CHARGE = 2610
GRAND_TOTAL = 38610
DEPOSIT_DUE = 11583
BALANCE_AFTER_DEPOSIT = 27027


def _floor_world(api):
    """A published Saturday HIGH service with one 20-seat class, one table
    seating 2 to 4, and one guest.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        no_show_grace_minutes=30,
        prep_lead_minutes=45,
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
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    table = FX.create_table(
        api, restaurant["id"], seats_min=2, seats_max=4, turn_buffer_minutes=15
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date=SERVICE_DATE,
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
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
    guest = FX.create_guest(api, display_name="Floor Guest")
    return {
        "restaurant_id": restaurant["id"],
        "package_id": package["id"],
        "table_id": table["id"],
        "service_id": service["id"],
        "ticket_class_id": ticket_class["id"],
        "guest_id": guest["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "kitchen": make_kitchen_headers(restaurant["id"]),
        "guest_headers": make_guest_headers(guest["id"]),
    }


def _seated_on_a_deposit(api, world):
    """A SEATED party whose money dimension has only reached DEPOSIT_PAID."""
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    FX.assign_table(
        api,
        world["restaurant_id"],
        reservation["id"],
        world["table_id"],
        SEATING_START,
    )
    FX.set_clock(api, SEATING_START)
    FX.seat(api, world["restaurant_id"], reservation["id"])
    return FX.read_reservation(api, reservation["id"], world["guest_headers"])


class TestParallelPaymentAndFulfillmentDimensions:
    """The seating side and the money side of one reservation row move apart."""

    def test_completion_is_refused_while_the_balance_is_outstanding(self, api):
        """A SEATED party cannot be completed on a deposit alone.

        "A reservation carries **two independent state dimensions on the same
        row**, and they advance on different triggers."

        "Completion advances the reservation `SEATED → COMPLETED` and is the
        point at which the money dimension gates the seating dimension: the
        reservation must read `FULLY_PAID`, and any outstanding balance refuses
        the operation with `ERR_BALANCE_OUTSTANDING`."

        Design: Difficulty/non_linear_state_machine/parallel_payment_and_fulfillment_dimension_gate
        """
        world = _floor_world(api)
        reservation = _seated_on_a_deposit(api, world)

        A.assert_fulfillment_status(reservation, "SEATED")
        A.assert_payment_status(reservation, "DEPOSIT_PAID")
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=TICKET_SUBTOTAL,
            service_charge=SERVICE_CHARGE,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
            amount_paid=DEPOSIT_DUE,
        )
        assert reservation["balance_due_cents"] == BALANCE_AFTER_DEPOSIT

        refused = api.complete_reservation(reservation["id"], world["manager"])
        validate_error(refused, E.ERR_BALANCE_OUTSTANDING, 409)

        # The refusal moved neither dimension of the row it was called on.
        after = FX.read_reservation(api, reservation["id"], world["guest_headers"])
        A.assert_fulfillment_status(after, "SEATED")
        A.assert_payment_status(after, "DEPOSIT_PAID")
        assert after["balance_due_cents"] == BALANCE_AFTER_DEPOSIT
        A.assert_instant_equals(after["seat_from_utc"], SEATING_START, "seat_from_utc")

    def test_paying_the_balance_moves_only_the_money_dimension(self, api):
        """The balance payment advances payment_status and leaves SEATED alone.

        "A later payment that clears the remainder of a deposit-paid
        reservation moves it `DEPOSIT_PAID → FULLY_PAID`, writing a
        `BALANCE_CHARGE` row with `memo_code` `GUEST_BALANCE`, driving
        `balance_due_cents` to 0 and thereby unblocking both completion and
        transfer."

        Design: Difficulty/non_linear_state_machine/parallel_payment_and_fulfillment_dimension_gate
        """
        world = _floor_world(api)
        reservation = _seated_on_a_deposit(api, world)

        FX.pay(api, reservation["id"], world["guest_id"], BALANCE_AFTER_DEPOSIT)

        paid = FX.read_reservation(api, reservation["id"], world["guest_headers"])
        A.assert_payment_status(paid, "FULLY_PAID")
        A.assert_fulfillment_status(paid, "SEATED")
        A.assert_money_breakdown(
            paid,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
            amount_paid=GRAND_TOTAL,
            refunded=0,
            forfeited=0,
        )
        assert paid["balance_due_cents"] == 0

        rows = FX.ledger_rows(api, reservation["id"], world["guest_headers"])
        assert [(row["kind"], row["memo_code"], row["amount_cents"]) for row in rows] == [
            ("DEPOSIT_CHARGE", "GUEST_PREPAY", DEPOSIT_DUE),
            ("BALANCE_CHARGE", "GUEST_BALANCE", BALANCE_AFTER_DEPOSIT),
        ]
        for row in rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)
        A.assert_derived_ledger_figures(paid, rows)

    def test_completion_succeeds_once_the_money_dimension_reads_fully_paid(self, api):
        """The identical completion request now advances the seating side.

        "Completing credits the guest's `completed_reservations_count` by 1 —
        which lifts that guest's waitlist standing everywhere, as §3.8 explains
        — reconciles the service's `gross_charged_cents` against the
        reservation's ledger, and advances the reservation's `version` by one."

        "Seating pins `seat_to_utc` to `seat_from_utc` plus the service's
        `turn_time_minutes`; until the party is seated, `seat_to_utc` is null."

        Design: Difficulty/non_linear_state_machine/parallel_payment_and_fulfillment_dimension_gate
        """
        world = _floor_world(api)
        reservation = _seated_on_a_deposit(api, world)

        refused = api.complete_reservation(reservation["id"], world["manager"])
        validate_error(refused, E.ERR_BALANCE_OUTSTANDING, 409)

        FX.pay(api, reservation["id"], world["guest_id"], BALANCE_AFTER_DEPOSIT)
        accepted = validate_success(
            api.complete_reservation(reservation["id"], world["manager"]), 200
        )

        A.assert_fulfillment_status(accepted, "COMPLETED")
        A.assert_payment_status(accepted, "FULLY_PAID")
        # The turn end was pinned by the seating, not by the completion, and
        # carries the service's turn time with no table buffer added.
        A.assert_instant_equals(accepted["seat_from_utc"], SEATING_START, "seat_from_utc")
        A.assert_instant_equals(accepted["seat_to_utc"], F.minutes_after(SEATING_START, 150), "seat_to_utc")

        guest = FX.read_guest(api, world["guest_id"], world["guest_headers"])
        assert guest["completed_reservations_count"] == 1


# ─── the capped offer cycle ───────────────────────────────────────────────
#
# The release window opens at the seating start less the service's
# release_lead_minutes of 180, that is at 2026-09-12T19:00:00Z.
CANCEL_AT = "2026-09-12T19:30:00Z"
OFFER_ONE_EXPIRES = "2026-09-12T19:45:00Z"
HOLD_ONE_EXPIRES = "2026-09-12T19:50:00Z"
FIRST_SWEEP_AT = "2026-09-12T19:51:00Z"
OFFER_TWO_EXPIRES = "2026-09-12T20:06:00Z"
HOLD_TWO_EXPIRES = "2026-09-12T20:11:00Z"
SECOND_SWEEP_AT = "2026-09-12T20:12:00Z"
RELEASE_PRICE_PER_COVER = 15300


def _cycle_world(api):
    """A sold-out 2-seat Saturday class with one party-of-2 entry waiting.

    The service releases the whole of an open class's availability, so a single
    release run can re-offer the same seats to the same entry.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        prep_lead_minutes=45,
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
        release_discount_bp=1500,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    table = FX.create_table(
        api, restaurant["id"], seats_min=2, seats_max=4, turn_buffer_minutes=15
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date=SERVICE_DATE,
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=2,
        demand_tier="HIGH",
        unsold_release_bp=10000,
        release_lead_minutes=180,
        waitlist_policy="YIELD_WEIGHTED",
        kitchen_prep_capacity_minutes=600,
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
    holder = FX.create_guest(api, display_name="Holder Two")
    cycler = FX.create_guest(api, display_name="Cycler")
    holder_reservation = FX.confirmed_reservation(
        api, ticket_class["id"], holder["id"], party_size=2
    )
    # The seating instant is pinned on the booking, so the cancellation below
    # is unambiguously inside the window that closes at seat_from_utc.
    FX.assign_table(
        api,
        restaurant["id"],
        holder_reservation["id"],
        table["id"],
        SEATING_START,
    )
    entry = FX.join_waitlist(api, service["id"], cycler["id"], party_size=2)
    return {
        "restaurant_id": restaurant["id"],
        "service_id": service["id"],
        "ticket_class_id": ticket_class["id"],
        "holder_id": holder["id"],
        "holder_reservation_id": holder_reservation["id"],
        "cycler_id": cycler["id"],
        "entry_id": entry["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "cycler_headers": make_guest_headers(cycler["id"]),
        "holder_headers": make_guest_headers(holder["id"]),
    }


def _first_offer(api, world):
    """The cancellation frees the seats and offers them to the waiting entry."""
    FX.set_clock(api, CANCEL_AT)
    FX.cancel(api, world["holder_reservation_id"], world["holder_id"])
    return FX.read_waitlist_entry(api, world["entry_id"], world["cycler_headers"])


def _first_lapse(api, world):
    """The offer and its hold both lapse, and the sweep reaps the hold."""
    FX.set_clock(api, FIRST_SWEEP_AT)
    FX.sweep_holds(api, world["service_id"])
    return FX.read_waitlist_entry(api, world["entry_id"], world["cycler_headers"])


def _release_reoffer(api, world):
    """The release run dumps the recovered seats into the released pool and
    promotes the same entry onto them a second time."""
    FX.run_release(api, world["restaurant_id"], world["service_id"])
    return FX.read_waitlist_entry(api, world["entry_id"], world["cycler_headers"])


class TestWaitlistOfferCycleCappedAtMaxOfferRounds:
    """One entry visits OFFERED twice and WAITING twice before a counter ends
    it."""

    def test_cancellation_offers_the_freed_seats_at_the_undiscounted_price(self, api):
        """The first promotion is cancel-driven, so it draws ordinary
        availability.

        "A cancel-driven or no-show-driven promotion draws **only** from
        `seats_available` and mints a hold with `is_release_priced` false, so
        the guest is quoted the full `list_price_per_cover_cents`."

        "It mints a `PENDING` `Reservation` for the entry's guest, stores its id
        on `offered_reservation_id`, credits `party_size` to the class's
        `seats_held`, debits the same count from the drawing pool, and sets
        `offer_expires_at_utc` to the logical clock plus the restaurant's
        `offer_ttl_minutes`."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_cycle_capped_at_max_offer_rounds
        """
        world = _cycle_world(api)
        entry = _first_offer(api, world)

        # Cancelling 2.5 hours out takes the 10000-basis-point band of the
        # STANDARD ladder, so the whole deposit is retained.
        holder = FX.read_reservation(
            api, world["holder_reservation_id"], world["holder_headers"]
        )
        A.assert_money_breakdown(
            holder, amount_paid=DEPOSIT_DUE, forfeited=DEPOSIT_DUE, refunded=0
        )
        A.assert_payment_status(holder, "FORFEITED")

        assert entry["status"] == "OFFERED"
        assert entry["offer_round"] == 0
        A.assert_instant_equals(entry["offer_expires_at_utc"], OFFER_ONE_EXPIRES, "offer_expires_at_utc")
        assert entry["priority_score"] == C.priority_score(2)
        assert entry["priority_score"] == 1100
        assert entry["offered_reservation_id"] is not None

        offered = FX.read_reservation(
            api, entry["offered_reservation_id"], world["cycler_headers"]
        )
        A.assert_fulfillment_status(offered, "PENDING")
        A.assert_payment_status(offered, "UNPAID")
        assert offered["party_size"] == 2
        assert offered["is_release_priced"] is False
        assert offered["price_locked_per_cover_cents"] == LIST_PRICE_PER_COVER
        A.assert_instant_equals(offered["hold_expires_at_utc"], HOLD_ONE_EXPIRES, "hold_expires_at_utc")

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=2, released=0, available=0, status="SOLD_OUT"
        )

    def test_the_first_lapse_cycles_the_entry_back_to_waiting_without_promoting(
        self, api
    ):
        """The sweep burns a round and puts the seats back untouched by anyone.

        "An offer that lapses does not necessarily end the entry's chances." The
        round below is the first of two, so the entry survives it: "This is the
        cycle edge, and an entry may loop `WAITING → OFFERED → WAITING`
        repeatedly."

        "It re-evaluates the precedence ladder, but — unlike a cancellation or a
        no-show — it triggers **no waitlist promotion whatsoever**, so seats
        recovered by a sweep sit in the pool until someone buys them or a
        release run offers them."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_cycle_capped_at_max_offer_rounds
        """
        world = _cycle_world(api)
        offered_entry = _first_offer(api, world)
        first_hold_id = offered_entry["offered_reservation_id"]

        entry = _first_lapse(api, world)

        assert entry["status"] == "WAITING"
        assert entry["offer_round"] == 1
        assert entry["offer_expires_at_utc"] is None
        assert entry["offered_reservation_id"] is None
        assert entry["priority_score"] == C.priority_score(2, offer_round=1)
        assert entry["priority_score"] == 1000

        lapsed = FX.read_reservation(api, first_hold_id, world["cycler_headers"])
        A.assert_fulfillment_status(lapsed, "EXPIRED")

        # The seats came back to ordinary availability and nobody was promoted
        # onto them, so the class is merely OPEN again.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=0, available=2, status="OPEN"
        )

    def test_the_release_run_re_offers_the_same_entry_at_the_discounted_price(
        self, api
    ):
        """The second offer comes from a different source and a different pool.

        "A release-run promotion draws **only** from `seats_released` and mints
        a hold with `is_release_priced` true, so the guest is quoted the
        discounted `release_price_per_cover_cents`."

        "At the end of the run the service's `release_run_count` is credited by
        1, its `seats_released_total` is credited by the run's release total,
        its `last_release_released_count` is set to that total, and its
        `last_release_promoted_count` is set to the number of entries promoted."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_cycle_capped_at_max_offer_rounds
        """
        world = _cycle_world(api)
        _first_offer(api, world)
        _first_lapse(api, world)

        entry = _release_reoffer(api, world)

        service = FX.read_service(api, world["service_id"], world["manager"])
        assert service["release_run_count"] == 1
        assert service["last_release_released_count"] == 2
        assert service["last_release_promoted_count"] == 1
        assert service["seats_released_total"] == 2

        assert entry["status"] == "OFFERED"
        assert entry["offer_round"] == 1
        A.assert_instant_equals(entry["offer_expires_at_utc"], OFFER_TWO_EXPIRES, "offer_expires_at_utc")
        assert entry["offered_reservation_id"] is not None

        second_hold = FX.read_reservation(
            api, entry["offered_reservation_id"], world["cycler_headers"]
        )
        A.assert_fulfillment_status(second_hold, "PENDING")
        assert second_hold["is_release_priced"] is True
        assert second_hold["price_locked_per_cover_cents"] == RELEASE_PRICE_PER_COVER
        assert second_hold["price_locked_per_cover_cents"] == C.release_price_per_cover(
            LIST_PRICE_PER_COVER, 1500
        )
        A.assert_instant_equals(second_hold["hold_expires_at_utc"], HOLD_TWO_EXPIRES, "hold_expires_at_utc")

        # The promotion pass drained the pool the release pass had just filled.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=2, released=0, available=0, status="SOLD_OUT"
        )

    def test_the_second_lapse_terminates_the_entry_and_refuses_the_claim(self, api):
        """The loop ends on the counter, not on a state, and EXPIRED is terminal.

        "When instead `offer_round` plus one **equals** `max_offer_rounds`, the
        entry terminates `OFFERED → EXPIRED`: `offer_round` is credited by 1 and
        the entry permanently stops being an eligible promotion target."

        "The waitlist entry is in the status the operation requires — `OFFERED`
        to claim, `WAITING` or `OFFERED` to withdraw — otherwise
        `ERR_WAITLIST_ENTRY_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_cycle_capped_at_max_offer_rounds
        """
        world = _cycle_world(api)
        _first_offer(api, world)
        _first_lapse(api, world)
        second_offer = _release_reoffer(api, world)
        second_hold_id = second_offer["offered_reservation_id"]

        FX.set_clock(api, SECOND_SWEEP_AT)
        FX.sweep_holds(api, world["service_id"])

        entry = FX.read_waitlist_entry(
            api, world["entry_id"], world["cycler_headers"]
        )
        assert entry["status"] == "EXPIRED"
        assert entry["offer_round"] == 2
        # The PRD clears `offer_expires_at_utc` on the OFFERED -> WAITING cycle
        # edge and on a claim, but the OFFERED -> EXPIRED termination edge names
        # only that "`offer_round` is credited by 1 and the entry permanently
        # stops being an eligible promotion target", so nothing is asserted of
        # that field here.
        assert entry["priority_score"] == C.priority_score(2, offer_round=2)
        assert entry["priority_score"] == 900

        lapsed = FX.read_reservation(api, second_hold_id, world["cycler_headers"])
        A.assert_fulfillment_status(lapsed, "EXPIRED")

        # The release-priced hold returned its seats to the released pool.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=2, available=0, status="RELEASED"
        )

        refused = api.claim_waitlist_entry(
            world["entry_id"], world["cycler_headers"]
        )
        validate_error(refused, E.ERR_WAITLIST_ENTRY_INVALID_STATE, 409)


# ─── the prep-rejection amendment cycle ───────────────────────────────────
#
# A party of 2 on a 12-minute-per-cover package carries a 24-minute baseline,
# an ANAPHYLAXIS note adds 15 and an ALLERGY note adds 6.
BASELINE_PREP_MINUTES = 24
PREP_WITH_ANAPHYLAXIS = 39
PREP_WITH_ANAPHYLAXIS_AND_ALLERGY = 45


def _booked_with_note(api, world, *, severity="ANAPHYLAXIS", restriction_code="NUT"):
    """A CONFIRMED party of 2 carrying one PENDING note on the first cover."""
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    note = FX.add_dietary_note(
        api,
        reservation["id"],
        world["guest_id"],
        guest_index=1,
        severity=severity,
        restriction_code=restriction_code,
    )
    return reservation, note


class TestDietaryNotePrepRejectionAmendLoop:
    """A note leaves PENDING, comes back to it, and only then reaches ACKED."""

    def test_the_note_re_enters_pending_through_prep_rejected(self, api):
        """Rejection and amendment form a cycle, and ACKED alone is terminal.

        "Rejecting moves the note `PENDING → PREP_REJECTED` and requires the
        note to be `PENDING` and a `reject_reason_code` to be supplied — one of
        `CROSS_CONTAMINATION_RISK`, `INGREDIENT_UNAVAILABLE` or
        `DETAIL_INSUFFICIENT`."

        "A successful amendment credits `amend_count` by 1, clears both
        `reject_reason_code` and `acked_by_user_id` back to null, and re-derives
        `prep_minutes` from the amended severity."

        "The `PENDING → PREP_REJECTED → PENDING` loop is therefore a genuine
        cycle, capped at three amendments per note."

        "Acknowledging a note that is not `PENDING` is refused with
        `ERR_DIETARY_NOTE_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/dietary_note_prep_rejection_amend_loop
        """
        world = _floor_world(api)
        reservation, note = _booked_with_note(api, world)

        assert note["ack_status"] == "PENDING"
        assert note["amend_count"] == 0
        assert note["reject_reason_code"] is None
        assert note["acked_by_user_id"] is None
        assert note["prep_minutes"] == C.SEVERITY_PREP_MINUTES["ANAPHYLAXIS"]
        assert note["prep_minutes"] == 15

        rejected = FX.reject_note(
            api,
            world["restaurant_id"],
            note["id"],
            reject_reason_code="CROSS_CONTAMINATION_RISK",
        )
        assert rejected["ack_status"] == "PREP_REJECTED"
        assert rejected["reject_reason_code"] == "CROSS_CONTAMINATION_RISK"
        assert rejected["amend_count"] == 0

        # The severity is preserved on the amendment, so the minutes do not move.
        amended = FX.amend_note(
            api,
            note["id"],
            world["guest_id"],
            severity="ANAPHYLAXIS",
            restriction_code="NUT",
            note_text="Severe nut anaphylaxis, separate preparation surface.",
        )
        assert amended["ack_status"] == "PENDING"
        assert amended["amend_count"] == 1
        assert amended["reject_reason_code"] is None
        assert amended["acked_by_user_id"] is None
        assert amended["prep_minutes"] == 15

        # A still-pending note consumes kitchen minutes throughout the cycle.
        after_loop = FX.read_reservation(
            api, reservation["id"], world["guest_headers"]
        )
        assert after_loop["prep_minutes_total"] == PREP_WITH_ANAPHYLAXIS
        assert after_loop["prep_minutes_total"] == C.prep_minutes_total(
            2, 12, ["ANAPHYLAXIS"]
        )

        acked = FX.ack_note(api, world["restaurant_id"], note["id"])
        assert acked["ack_status"] == "ACKED"
        assert acked["acked_by_user_id"] == world["restaurant_id"]
        assert acked["amend_count"] == 1

        # ACKED is terminal, so the kitchen cannot decide the note again.
        refused = api.ack_dietary_note(
            note["id"], F.ack_payload("ACCEPT"), world["kitchen"]
        )
        validate_error(refused, E.ERR_DIETARY_NOTE_INVALID_STATE, 409)

    def test_an_unacknowledged_anaphylaxis_note_blocks_table_assignment(self, api):
        """The ack gate outranks the rejection gate on the same note.

        "First, every note on the reservation whose `severity` is `ANAPHYLAXIS`
        must have reached `ack_status` `ACKED`; a single still-pending
        anaphylaxis note refuses both operations with
        `ERR_DIETARY_ACK_REQUIRED`."

        "Seating pins `seat_to_utc` to `seat_from_utc` plus the service's
        `turn_time_minutes`; until the party is seated, `seat_to_utc` is null."

        Design: Difficulty/non_linear_state_machine/dietary_note_prep_rejection_amend_loop
        """
        world = _floor_world(api)
        reservation, note = _booked_with_note(api, world)
        payload = F.assign_table_payload(world["table_id"], SEATING_START)

        # Pending: the note has never reached ACKED.
        validate_error(
            api.assign_table(reservation["id"], payload, world["manager"]),
            E.ERR_DIETARY_ACK_REQUIRED,
            422,
        )

        # Prep-rejected: still not ACKED, so the same gate speaks first.
        FX.reject_note(api, world["restaurant_id"], note["id"])
        validate_error(
            api.assign_table(reservation["id"], payload, world["manager"]),
            E.ERR_DIETARY_ACK_REQUIRED,
            422,
        )

        # Amended back to PENDING: the note is still short of ACKED.
        FX.amend_note(
            api,
            note["id"],
            world["guest_id"],
            severity="ANAPHYLAXIS",
            restriction_code="NUT",
        )
        validate_error(
            api.assign_table(reservation["id"], payload, world["manager"]),
            E.ERR_DIETARY_ACK_REQUIRED,
            422,
        )

        FX.ack_note(api, world["restaurant_id"], note["id"])
        assigned = get_success_data(
            api.assign_table(reservation["id"], payload, world["manager"])
        )
        assert assigned["assigned_table_id"] == world["table_id"]
        A.assert_instant_equals(assigned["seat_from_utc"], SEATING_START, "seat_from_utc")
        assert assigned["seat_to_utc"] is None
        assert assigned["prep_minutes_total"] == PREP_WITH_ANAPHYLAXIS
        A.assert_fulfillment_status(assigned, "CONFIRMED")

    def test_a_prep_rejected_note_blocks_assignment_until_it_is_amended(self, api):
        """With the anaphylaxis note ACKED, the rejection gate becomes visible.

        "Second, no note on the reservation may be sitting in `PREP_REJECTED`;
        if one is, both operations are refused with
        `ERR_DIETARY_NOTE_PREP_REJECTED`."

        "Notes at `INFO` or `ALLERGY` severity do not require acknowledgement to
        seat — they simply cost minutes."

        Design: Difficulty/non_linear_state_machine/dietary_note_prep_rejection_amend_loop
        """
        world = _floor_world(api)
        reservation, anaphylaxis = _booked_with_note(api, world)
        FX.ack_note(api, world["restaurant_id"], anaphylaxis["id"])

        allergy = FX.add_dietary_note(
            api,
            reservation["id"],
            world["guest_id"],
            guest_index=2,
            severity="ALLERGY",
            restriction_code="SHELLFISH",
        )
        assert allergy["prep_minutes"] == C.SEVERITY_PREP_MINUTES["ALLERGY"]

        payload = F.assign_table_payload(world["table_id"], SEATING_START)
        FX.reject_note(
            api,
            world["restaurant_id"],
            allergy["id"],
            reject_reason_code="DETAIL_INSUFFICIENT",
        )
        validate_error(
            api.assign_table(reservation["id"], payload, world["manager"]),
            E.ERR_DIETARY_NOTE_PREP_REJECTED,
            422,
        )

        amended = FX.amend_note(
            api,
            allergy["id"],
            world["guest_id"],
            severity="ALLERGY",
            restriction_code="SHELLFISH",
            note_text="Shellfish allergy, no shared fryer.",
        )
        assert amended["ack_status"] == "PENDING"
        assert amended["amend_count"] == 1
        assert amended["prep_minutes"] == 6

        # The amended note is PENDING again, and a pending ALLERGY note is no
        # obstacle to assignment — it only costs minutes.
        assigned = get_success_data(
            api.assign_table(reservation["id"], payload, world["manager"])
        )
        assert assigned["assigned_table_id"] == world["table_id"]
        assert assigned["prep_minutes_total"] == PREP_WITH_ANAPHYLAXIS_AND_ALLERGY
        assert assigned["prep_minutes_total"] == C.prep_minutes_total(
            2, 12, ["ANAPHYLAXIS", "ALLERGY"]
        )


# ─── the two disjoint adjudication arms ───────────────────────────────────
#
# Cancelling 2.5 hours out retains the whole 11583-cent deposit, which is the
# pool an approval may reverse against.
FORFEITED_DEPOSIT = 11583
REQUESTED_CENTS = 3000
APPROVED_CENTS = 3000
CREDIT_EXPIRES_AT = "2026-10-01T00:00:00Z"


def _forfeited_reservation(api, world):
    """A CANCELLED reservation whose money dimension settled to FORFEITED."""
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    # The seating instant is pinned so the cancellation is unambiguously before
    # it, which fixes which forfeiture band applies.
    FX.assign_table(
        api,
        world["restaurant_id"],
        reservation["id"],
        world["table_id"],
        SEATING_START,
    )
    FX.set_clock(api, CANCEL_AT)
    FX.cancel(api, reservation["id"], world["guest_id"])
    return FX.read_reservation(api, reservation["id"], world["guest_headers"])


class TestRefundExceptionForkWithDisjointArms:
    """One state, two terminal successors, and almost nothing in common."""

    def test_the_denial_arm_records_a_decision_and_touches_nothing_else(self, api):
        """DENIED moves the exception and leaves the reservation and guest alone.

        "The `REQUESTED → DENIED` arm requires nothing beyond the state check
        and the segregation check."

        "On denial, `approved_cents` stays at 0 and `shortfall_cents` becomes
        the whole of `requested_cents`."

        Design: Difficulty/non_linear_state_machine/refund_exception_fork_with_disjoint_arms
        """
        world = _floor_world(api)
        settled = _forfeited_reservation(api, world)
        A.assert_payment_status(settled, "FORFEITED")
        assert settled["forfeited_cents"] == FORFEITED_DEPOSIT
        assert settled["refunded_cents"] == 0
        rows_before = FX.ledger_rows(api, settled["id"], world["guest_headers"])
        version_before = settled["version"]

        exception = FX.file_refund_exception(api, settled["id"], REQUESTED_CENTS)
        assert exception["status"] == "REQUESTED"
        assert exception["approved_cents"] == 0
        assert exception["shortfall_cents"] == 0
        assert exception["decided_by_user_id"] is None
        assert exception["decision_note_code"] is None

        denied = FX.decide_refund_exception(
            api,
            exception["id"],
            decision="DENIED",
            decision_note_code="EVIDENCE_INSUFFICIENT",
        )
        assert denied["status"] == "DENIED"
        assert denied["approved_cents"] == 0
        assert denied["shortfall_cents"] == REQUESTED_CENTS
        assert denied["decision_note_code"] == "EVIDENCE_INSUFFICIENT"
        assert denied["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID

        # No ledger row, no reservation field and no guest counter moved.
        rows_after = FX.ledger_rows(api, settled["id"], world["guest_headers"])
        assert len(rows_after) == len(rows_before)
        assert sorted(row["kind"] for row in rows_after) == [
            "DEPOSIT_CHARGE",
            "FORFEITURE",
        ]
        after = FX.read_reservation(api, settled["id"], world["guest_headers"])
        A.assert_payment_status(after, "FORFEITED")
        assert after["forfeited_cents"] == FORFEITED_DEPOSIT
        assert after["refunded_cents"] == 0
        assert after["version"] == version_before
        A.assert_settled_ledger_identity(after)

        guest = FX.read_guest(api, world["guest_id"], world["guest_headers"])
        assert guest["lifetime_refunded_cents"] == 0
        assert guest["refund_scrutiny_flag"] is False

    def test_the_denied_arm_is_terminal_and_cannot_be_re_decided(self, api):
        """Neither arm may be revisited once the fork has been taken.

        "Both arms require the exception to still be `REQUESTED`, otherwise
        `ERR_REFUND_EXCEPTION_ALREADY_DECIDED`, and both require the acting
        `X-User-ID` to differ from `requested_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        "`APPROVED` and `DENIED` are both terminal."

        Design: Difficulty/non_linear_state_machine/refund_exception_fork_with_disjoint_arms
        """
        world = _floor_world(api)
        settled = _forfeited_reservation(api, world)
        exception = FX.file_refund_exception(api, settled["id"], REQUESTED_CENTS)
        FX.decide_refund_exception(
            api,
            exception["id"],
            decision="DENIED",
            decision_note_code="OUT_OF_POLICY",
        )

        # A third operator, so the segregation comparison passes and the state
        # check is what speaks.
        refused = api.decide_refund_exception(
            exception["id"],
            F.decide_payload(
                decision="APPROVED",
                approved_cents=APPROVED_CENTS,
                decision_note_code="POLICY_EXCEPTION",
            ),
            CARE_ISSUER_HEADERS,
        )
        validate_error(refused, E.ERR_REFUND_EXCEPTION_ALREADY_DECIDED, 409)

        unchanged = get_success_data(
            api.get_refund_exception(exception["id"], CARE_DECIDER_HEADERS)
        )
        assert unchanged["status"] == "DENIED"
        assert unchanged["approved_cents"] == 0
        assert unchanged["decision_note_code"] == "OUT_OF_POLICY"

    def test_the_denied_shortfall_cannot_be_spent_on_a_goodwill_credit(self, api):
        """The denial arm's shortfall is a record, not an entitlement.

        "No `PaymentTransaction` row of any kind is written, no reservation
        field moves, no guest counter moves, and — despite the non-zero
        `shortfall_cents` — no goodwill credit may be issued at all, because
        issuance requires an `APPROVED` exception and a `DENIED` one is refused
        with `ERR_REFUND_EXCEPTION_NOT_APPROVED`."

        "The denial arm's `shortfall_cents` is a record of what was asked and
        refused, not a spendable balance."

        Design: Difficulty/non_linear_state_machine/refund_exception_fork_with_disjoint_arms
        """
        world = _floor_world(api)
        settled = _forfeited_reservation(api, world)
        exception = FX.file_refund_exception(api, settled["id"], REQUESTED_CENTS)
        denied = FX.decide_refund_exception(
            api,
            exception["id"],
            decision="DENIED",
            decision_note_code="EVIDENCE_INSUFFICIENT",
        )
        assert denied["shortfall_cents"] == REQUESTED_CENTS

        # The face value sits inside both the shortfall and the restaurant's cap,
        # so only the exception's state can refuse this.
        refused = api.create_goodwill_credit(
            F.goodwill_credit_payload(
                exception["id"], REQUESTED_CENTS, CREDIT_EXPIRES_AT
            ),
            CARE_ISSUER_HEADERS,
        )
        validate_error(refused, E.ERR_REFUND_EXCEPTION_NOT_APPROVED, 409)

        rows = FX.ledger_rows(api, settled["id"], world["guest_headers"])
        assert sorted(row["kind"] for row in rows) == ["DEPOSIT_CHARGE", "FORFEITURE"]

    def test_the_approval_arm_writes_a_row_pair_and_reopens_the_money_state(
        self, api
    ):
        """APPROVED touches the exception, the reservation's ledger and the guest.

        "The two arms then diverge completely, and the asymmetry is intentional:
        approval touches three entities, denial touches none."

        "The reservation is credited a `FORFEITURE_REVERSAL` row of
        `approved_cents` and debited a `REFUND` row of the same
        `approved_cents`, both with `memo_code` `REFUND_EXCEPTION`, which keeps
        the signed ledger sum aligned with `amount_paid_cents` less
        `refunded_cents` less `forfeited_cents`; the reservation's
        `forfeited_cents` is debited and its `refunded_cents` credited by
        `approved_cents`."

        "`FORFEITED → PARTIALLY_REFUNDED` fires when the approval covers only
        part of what was forfeited, that is when `approved_cents` sits strictly
        between 0 and `forfeited_cents`."

        Design: Difficulty/non_linear_state_machine/refund_exception_fork_with_disjoint_arms
        """
        world = _floor_world(api)
        settled = _forfeited_reservation(api, world)
        exception = FX.file_refund_exception(api, settled["id"], REQUESTED_CENTS)

        approved = FX.decide_refund_exception(
            api,
            exception["id"],
            decision="APPROVED",
            approved_cents=APPROVED_CENTS,
            decision_note_code="POLICY_EXCEPTION",
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_cents"] == APPROVED_CENTS
        assert approved["shortfall_cents"] == REQUESTED_CENTS - APPROVED_CENTS
        assert approved["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID

        after = FX.read_reservation(api, settled["id"], world["guest_headers"])
        A.assert_payment_status(after, "PARTIALLY_REFUNDED")
        assert after["refunded_cents"] == APPROVED_CENTS
        assert after["forfeited_cents"] == FORFEITED_DEPOSIT - APPROVED_CENTS
        assert after["amount_paid_cents"] == FORFEITED_DEPOSIT
        A.assert_settled_ledger_identity(after)
        # The seating dimension stayed where the cancellation left it.
        A.assert_fulfillment_status(after, "CANCELLED")

        rows = FX.ledger_rows(api, settled["id"], world["guest_headers"])
        exception_rows = [
            row for row in rows if row["memo_code"] == "REFUND_EXCEPTION"
        ]
        assert sorted(row["kind"] for row in exception_rows) == [
            "FORFEITURE_REVERSAL",
            "REFUND",
        ]
        by_kind = {row["kind"]: row for row in exception_rows}
        assert by_kind["FORFEITURE_REVERSAL"]["amount_cents"] == APPROVED_CENTS
        assert by_kind["FORFEITURE_REVERSAL"]["signed_amount_cents"] == APPROVED_CENTS
        assert by_kind["REFUND"]["amount_cents"] == APPROVED_CENTS
        assert by_kind["REFUND"]["signed_amount_cents"] == -APPROVED_CENTS
        for row in rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)
        A.assert_signed_sum_matches(after, rows)
        A.assert_derived_ledger_figures(after, rows)

        # The third entity: the refund is written onto the guest's lifetime
        # total, which stays under the restaurant's scrutiny threshold here.
        guest = FX.read_guest(api, world["guest_id"], world["guest_headers"])
        assert guest["lifetime_refunded_cents"] == APPROVED_CENTS
        assert guest["refund_scrutiny_flag"] is False
