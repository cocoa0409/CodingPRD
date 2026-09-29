"""
State-machine edges on the later half of the lifecycle: the restaurant-initiated
service unwind, the kitchen acknowledgement cycle, the waitlist offer deadline
and its withdrawal, the exhausted goodwill credit, the two reservation
dimensions moving on their own triggers, and the closing hold sweep.

Every scenario is built from an empty database through declared endpoints only,
and every identity is threaded from the entity it acts for: a Guest's
`X-User-ID` is that guest's own id, while a RestaurantManager's and a
KitchenLead's are the owning restaurant's id.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import (
    ERR_BALANCE_OUTSTANDING,
    ERR_DIETARY_NOTE_INVALID_STATE,
    ERR_GOODWILL_CREDIT_EXHAUSTED,
    ERR_GOODWILL_CREDIT_INVALID_STATE,
    ERR_OFFER_EXPIRED,
    ERR_SERVICE_INVALID_STATE,
    ERR_WAITLIST_ENTRY_INVALID_STATE,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CARE_DECIDER_HEADERS,
    CARE_ISSUER_HEADERS,
    CARE_REVOKER_HEADERS,
    make_guest_headers,
)

# ─── the pinned calendar every scenario trades on ─────────────────────────
#
# 2026-09-10 is a Thursday, whose day-of-week factor is neutral at 10000 basis
# points, and the STANDARD demand tier is likewise 10000, so a 12000-cent base
# price yields a 12000-cent cover before any scarcity step.

SETUP_CLOCK = "2026-09-01T00:00:00Z"
SEATING_START = "2026-09-10T22:00:00Z"
SEATING_END = "2026-09-11T02:00:00Z"
# seat_from 22:00 plus the service's turn_time_minutes of 150.
SEAT_TO = "2026-09-11T00:30:00Z"
# Exactly 48.0 hours before seating, mid-ladder on the STANDARD schedule.
CANCEL_AT_48H = "2026-09-08T22:00:00Z"
# seating_start less the service's release_lead_minutes of 180.
RELEASE_WINDOW_OPEN = "2026-09-10T19:00:00Z"
# The release-window instant plus offer_ttl_minutes 15 and hold_ttl_minutes 20.
OFFER_EXPIRES_AT = "2026-09-10T19:15:00Z"
HOLD_EXPIRES_AT = "2026-09-10T19:20:00Z"
ONE_MINUTE_PAST_THE_OFFER = "2026-09-10T19:16:00Z"
CREDIT_EXPIRES_AT = "2027-01-01T00:00:00Z"

# The money picture of a party of two on the recurring 12000-cent package:
# 12000 * 2 = 24000 subtotal, 24000 * 725 / 10000 = 1740 service charge,
# 25740 grand total, 25740 * 3000 / 10000 = 7722 deposit.
TICKET_SUBTOTAL = 24000
SERVICE_CHARGE = 1740
GRAND_TOTAL = 25740
DEPOSIT = 7722
BALANCE_AFTER_DEPOSIT = 18018


def _same_instant(actual: str, expected: str) -> bool:
    """Compare two ISO 8601 UTC instants without pinning their rendering."""
    return F.parse_iso(actual) == F.parse_iso(expected)


def _rows_of_kind(rows, kind):
    return [row for row in rows if row["kind"] == kind]


# ─── the restaurant-initiated unwind ──────────────────────────────────────


def _cascade_world(api):
    """A PUBLISHED Thursday service with a 20-seat class, one CONFIRMED
    deposit-paid party of two, and a second guest waiting in line, with the
    clock parked exactly 48 hours before seating.
    """
    world = FX.build_world(api, clock=SETUP_CLOCK, guests=2)
    guest_a, guest_b = world["guests"][0], world["guests"][1]
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_a["id"], party_size=2
    )
    entry = FX.join_waitlist(api, world["service_id"], guest_b["id"], party_size=2)
    FX.set_clock(api, CANCEL_AT_48H)
    world["guest_a"] = guest_a
    world["guest_b"] = guest_b
    world["reservation"] = reservation
    world["entry"] = entry
    return world


class TestServiceCancelUnwind:
    """One manager request refunds the room and empties the queue."""

    def test_service_cancel_refunds_in_full_and_bypasses_the_ladder(self, api):
        """The restaurant-initiated basis keeps nothing the ladder would have kept.

        "A restaurant-initiated cancellation therefore never forfeits a cent no
        matter what the package's `forfeiture_schedule_code` says or how close
        to service it happens; and a still-`PENDING` hold is always settled at
        zero forfeiture regardless of hours to service, because its seats were
        never sold."

        Design: Corner/state_machines/cascade_down_service_cancel_refunds_reservations_and_withdraws_waitlist
        """
        world = _cascade_world(api)
        guest_headers = make_guest_headers(world["guest_a"]["id"])

        # What the guest-initiated ladder would have retained at this instant.
        counterfactual = C.settle_cancellation(
            DEPOSIT, DEPOSIT, GRAND_TOTAL, "STANDARD", "DEPOSIT_BASIS", 48.0
        )
        assert counterfactual["forfeited_cents"] == 4361

        get_success_data(
            api.cancel_service(world["service_id"], world["manager_headers"])
        )

        settled = FX.read_reservation(
            api, world["reservation"]["id"], guest_headers
        )
        A.assert_fulfillment_status(settled, "CANCELLED")
        assert settled["cancel_settlement_basis"] == "RESTAURANT_INITIATED"
        A.assert_payment_status(settled, "REFUNDED")
        A.assert_money_breakdown(
            settled,
            grand_total=GRAND_TOTAL,
            amount_paid=DEPOSIT,
            refunded=DEPOSIT,
            forfeited=0,
        )
        assert settled["refunded_cents"] != counterfactual["forfeited_cents"]

        rows = FX.ledger_rows(api, world["reservation"]["id"], guest_headers)
        refunds = _rows_of_kind(rows, "REFUND")
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == DEPOSIT
        assert refunds[0]["memo_code"] == "SERVICE_CANCEL"
        assert _rows_of_kind(rows, "FORFEITURE") == []
        for row in rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)
        A.assert_signed_sum_matches(settled, rows)
        assert sum(row["signed_amount_cents"] for row in rows) == 0

        # "After **every** `REFUND` row is written — from any trigger, at any
        # restaurant — the refunded amount is credited to that guest's
        # `lifetime_refunded_cents`."
        guest = FX.read_guest(api, world["guest_a"]["id"], guest_headers)
        assert guest["lifetime_refunded_cents"] == DEPOSIT
        assert guest["refund_scrutiny_flag"] is False

    def test_service_cancel_closes_the_class_withdraws_the_queue_and_reconciles(
        self, api
    ):
        """The same request cascades to the class, the waitlist and the roll-ups.

        "From `PUBLISHED` — the `PUBLISHED → CANCELLED` edge — it unwinds
        everything: every reservation in `PENDING` or `CONFIRMED` moves to
        `CANCELLED` with `cancel_settlement_basis` set to
        `RESTAURANT_INITIATED`; each such reservation is refunded in full by a
        `REFUND` row for `amount_paid_cents` less any `refunded_cents` already
        recorded, with `memo_code` `SERVICE_CANCEL`, and its `forfeited_cents`
        stays at 0; every `WaitlistEntry` in `WAITING` or `OFFERED` moves to
        `WITHDRAWN`; every `TicketClass` moves to `CLOSED`; and the service's
        `refunded_cents` and `net_settled_cents` are recomputed."

        Design: Corner/state_machines/cascade_down_service_cancel_refunds_reservations_and_withdraws_waitlist
        """
        world = _cascade_world(api)
        guest_b_headers = make_guest_headers(world["guest_b"]["id"])

        cancelled = get_success_data(
            api.cancel_service(world["service_id"], world["manager_headers"])
        )
        assert cancelled["status"] == "CANCELLED"

        service = FX.read_service(
            api, world["service_id"], world["manager_headers"]
        )
        assert service["status"] == "CANCELLED"
        assert service["covers_confirmed"] == 0
        assert service["gross_charged_cents"] == DEPOSIT
        assert service["refunded_cents"] == DEPOSIT
        assert service["forfeited_cents"] == 0
        assert service["net_settled_cents"] == 0

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        assert ticket_class["status"] == "CLOSED"

        entry = FX.read_waitlist_entry(
            api, world["entry"]["id"], guest_b_headers
        )
        assert entry["status"] == "WITHDRAWN"
        assert entry["offered_reservation_id"] is None


# ─── the kitchen acknowledgement cycle ────────────────────────────────────


def _dietary_world(api):
    """A CONFIRMED party of two carrying two fresh notes: one ALLERGY and one
    ANAPHYLAXIS, both `PENDING`, well before seating.
    """
    world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    allergy = FX.add_dietary_note(
        api,
        reservation["id"],
        world["guest_id"],
        guest_index=1,
        severity="ALLERGY",
        restriction_code="NUT",
        note_text="No nuts of any kind.",
    )
    anaphylaxis = FX.add_dietary_note(
        api,
        reservation["id"],
        world["guest_id"],
        guest_index=2,
        severity="ANAPHYLAXIS",
        restriction_code="SHELLFISH",
        note_text="Carries an epinephrine pen.",
    )
    world["reservation"] = reservation
    world["allergy_note"] = allergy
    world["anaphylaxis_note"] = anaphylaxis
    return world


class TestDietaryAckCycle:
    """ACKED is terminal; PREP_REJECTED is not."""

    def test_accepting_reaches_a_terminal_state_that_refuses_both_edges(self, api):
        """An ACKED note can be neither acknowledged again nor amended.

        "Accepting moves the note `PENDING → ACKED` and requires three things:
        the note is still `PENDING`, the owning reservation's seating dimension
        reads `CONFIRMED`, and the logical clock is strictly before the
        service's `seating_start_utc`." "Acknowledging a note that is not
        `PENDING` is refused with `ERR_DIETARY_NOTE_INVALID_STATE`."

        Design: Corner/state_machines/valid_transition_dietary_ack_accept_reject_and_amend_cycle
        """
        world = _dietary_world(api)
        note_id = world["allergy_note"]["id"]
        assert world["allergy_note"]["ack_status"] == "PENDING"
        assert world["allergy_note"]["amend_count"] == 0
        assert world["allergy_note"]["acked_by_user_id"] is None

        acked = get_success_data(
            api.ack_dietary_note(
                note_id, F.ack_payload("ACCEPT"), world["kitchen_headers"]
            )
        )
        assert acked["ack_status"] == "ACKED"
        # "Acceptance records the acting lead's `X-User-ID` as
        # `acked_by_user_id`": the lead acts for the owning restaurant.
        assert acked["acked_by_user_id"] == world["restaurant_id"]
        assert acked["reject_reason_code"] is None

        second_ack = api.ack_dietary_note(
            note_id, F.ack_payload("ACCEPT"), world["kitchen_headers"]
        )
        validate_error(second_ack, ERR_DIETARY_NOTE_INVALID_STATE, 409)

        amend_the_acked = api.amend_dietary_note(
            note_id,
            F.amend_payload(severity="INFO", restriction_code="NUT"),
            make_guest_headers(world["guest_id"]),
        )
        validate_error(amend_the_acked, ERR_DIETARY_NOTE_INVALID_STATE, 409)

        unchanged = FX.read_note(api, note_id, world["kitchen_headers"])
        assert unchanged["ack_status"] == "ACKED"
        assert unchanged["severity"] == "ALLERGY"
        assert unchanged["amend_count"] == 0

    def test_rejecting_then_amending_returns_the_note_to_pending(self, api):
        """The rejection loop is a genuine cycle back to PENDING.

        "Rejecting moves the note `PENDING → PREP_REJECTED` and requires the
        note to be `PENDING` and a `reject_reason_code` to be supplied — one of
        `CROSS_CONTAMINATION_RISK`, `INGREDIENT_UNAVAILABLE` or
        `DETAIL_INSUFFICIENT`." "A successful amendment credits `amend_count`
        by 1, clears both `reject_reason_code` and `acked_by_user_id` back to
        null, and re-derives `prep_minutes` from the amended severity."

        Design: Corner/state_machines/valid_transition_dietary_ack_accept_reject_and_amend_cycle
        """
        world = _dietary_world(api)
        note_id = world["anaphylaxis_note"]["id"]
        guest_headers = make_guest_headers(world["guest_id"])

        rejected = get_success_data(
            api.ack_dietary_note(
                note_id,
                F.reject_payload("CROSS_CONTAMINATION_RISK"),
                world["kitchen_headers"],
            )
        )
        assert rejected["ack_status"] == "PREP_REJECTED"
        assert rejected["reject_reason_code"] == "CROSS_CONTAMINATION_RISK"
        assert rejected["amend_count"] == 0

        amended = get_success_data(
            api.amend_dietary_note(
                note_id,
                F.amend_payload(
                    severity="ALLERGY",
                    restriction_code="SHELLFISH",
                    note_text="Shellfish avoided, no airborne risk.",
                ),
                guest_headers,
            )
        )
        assert amended["ack_status"] == "PENDING"
        assert amended["amend_count"] == 1
        assert amended["reject_reason_code"] is None
        assert amended["acked_by_user_id"] is None
        assert amended["severity"] == "ALLERGY"
        assert amended["prep_minutes"] == 6

        # The note is back at PENDING, so the amend edge is closed again.
        second_amend = api.amend_dietary_note(
            note_id, F.amend_payload(severity="INFO"), guest_headers
        )
        validate_error(second_amend, ERR_DIETARY_NOTE_INVALID_STATE, 409)
        still_pending = FX.read_note(api, note_id, world["kitchen_headers"])
        assert still_pending["ack_status"] == "PENDING"
        assert still_pending["amend_count"] == 1

    def test_the_cycle_re_derives_the_reservation_prep_total(self, api):
        """Kitchen minutes track the notes through the cycle, whatever their state.

        "It is the sum of three terms: a baseline of the reservation's
        `party_size` multiplied by the package's
        `kitchen_prep_minutes_per_cover`; plus the severity minutes of every one
        of the reservation's dietary notes, counted **regardless of
        `ack_status`**, because a still-pending allergy consumes kitchen time
        exactly as an acknowledged one does; plus, over every add-on line on the
        reservation, the add-on's `prep_minutes_per_unit` multiplied by that
        line's `qty`." "It is recomputed whenever a note is created,
        acknowledged or amended, whenever an add-on line is appended, and again
        whenever a table is assigned."

        Design: Corner/state_machines/valid_transition_dietary_ack_accept_reject_and_amend_cycle
        """
        world = _dietary_world(api)
        guest_headers = make_guest_headers(world["guest_id"])
        per_cover = world["package"]["kitchen_prep_minutes_per_cover"]

        before = C.prep_minutes_total(2, per_cover, severities=("ALLERGY", "ANAPHYLAXIS"))
        assert before == 45
        booking = FX.read_reservation(api, world["reservation"]["id"], guest_headers)
        assert booking["prep_minutes_total"] == before

        # A rejected note still costs the kitchen its severity minutes.
        FX.reject_note(
            api, world["restaurant_id"], world["anaphylaxis_note"]["id"]
        )
        after_reject = FX.read_reservation(
            api, world["reservation"]["id"], guest_headers
        )
        assert after_reject["prep_minutes_total"] == before

        FX.amend_note(
            api,
            world["anaphylaxis_note"]["id"],
            world["guest_id"],
            severity="ALLERGY",
            restriction_code="SHELLFISH",
        )
        expected_after = C.prep_minutes_total(
            2, per_cover, severities=("ALLERGY", "ALLERGY")
        )
        assert expected_after == 36
        after_amend = FX.read_reservation(
            api, world["reservation"]["id"], guest_headers
        )
        assert after_amend["prep_minutes_total"] == expected_after


# ─── the release run's offer, its deadline and its withdrawal ─────────────


def _release_ready_world(api):
    """A four-seat Thursday class with two seats sold and two idle, one guest
    waiting for a single seat, and the clock exactly at the release window.

    The window opens at `seating_start_utc` less the service's
    `release_lead_minutes` of 180, i.e. 19:00Z.
    """
    world = FX.build_world(
        api, clock=SETUP_CLOCK, ticket_class={"seats_allocated": 4}, guests=2
    )
    holder, waiter = world["guests"][0], world["guests"][1]
    holder_reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], holder["id"], party_size=2
    )
    entry = FX.join_waitlist(api, world["service_id"], waiter["id"], party_size=1)
    FX.set_clock(api, RELEASE_WINDOW_OPEN)
    world["holder"] = holder
    world["waiter"] = waiter
    world["holder_reservation"] = holder_reservation
    world["entry"] = entry
    return world


def _offered_world(api):
    """The release-ready world after one release run, so the waiting guest
    holds a live release-priced offer that lapses at 19:15Z."""
    world = _release_ready_world(api)
    FX.run_release(api, world["restaurant_id"], world["service_id"])
    waiter_headers = make_guest_headers(world["waiter"]["id"])
    entry = FX.read_waitlist_entry(api, world["entry"]["id"], waiter_headers)
    offered = FX.read_reservation(
        api, entry["offered_reservation_id"], waiter_headers
    )
    world["entry"] = entry
    world["offered"] = offered
    world["waiter_headers"] = waiter_headers
    return world


class TestReleaseOfferDeadline:
    """The offer lapses fifteen minutes in; the hold it minted lives twenty."""

    def test_the_promotion_mints_a_release_priced_hold_with_both_deadlines(self, api):
        """One run releases a seat, promotes the waiter and prices the offer down.

        "It mints a `PENDING` `Reservation` for the entry's guest, stores its id
        on `offered_reservation_id`, credits `party_size` to the class's
        `seats_held`, debits the same count from the drawing pool, and sets
        `offer_expires_at_utc` to the logical clock plus the restaurant's
        `offer_ttl_minutes`." "When the seats being priced are drawn from the
        released pool rather than from ordinary availability, the figure
        produced by step four is multiplied by 10000 minus the package's
        `release_discount_bp`, divided by 10000, and rounded half up."

        Design: Corner/state_machines/precondition_waitlist_claim_after_offer_ttl_returns_offer_expired
        """
        world = _release_ready_world(api)
        waiter_headers = make_guest_headers(world["waiter"]["id"])

        # Half of the two idle seats is one whole seat: a partial seat is never
        # released.
        assert C.release_seat_count(2, world["service"]["unsold_release_bp"]) == 1

        FX.run_release(api, world["restaurant_id"], world["service_id"])

        service = FX.read_service(
            api, world["service_id"], world["manager_headers"]
        )
        assert service["release_run_count"] == 1
        assert service["seats_released_total"] == 1
        assert service["last_release_released_count"] == 1
        assert service["last_release_promoted_count"] == 1

        entry = FX.read_waitlist_entry(api, world["entry"]["id"], waiter_headers)
        assert entry["status"] == "OFFERED"
        assert entry["offered_reservation_id"] is not None
        assert _same_instant(entry["offer_expires_at_utc"], OFFER_EXPIRES_AT)

        offered = FX.read_reservation(
            api, entry["offered_reservation_id"], waiter_headers
        )
        A.assert_fulfillment_status(offered, "PENDING")
        A.assert_payment_status(offered, "UNPAID")
        assert offered["guest_id"] == world["waiter"]["id"]
        assert offered["party_size"] == 1
        assert offered["is_release_priced"] is True
        assert _same_instant(offered["hold_expires_at_utc"], HOLD_EXPIRES_AT)

        # Thursday and STANDARD are both neutral, the class has sold through
        # 5000 basis points, and the released pool takes 1500 off the
        # scarcity-adjusted figure.
        list_price = C.list_price_per_cover(
            world["package"]["base_price_cents"], "THU", "STANDARD", sell_through=5000
        )
        assert list_price == 12960
        expected = C.release_price_per_cover(
            list_price, world["package"]["release_discount_bp"]
        )
        assert expected == 11016
        assert offered["price_locked_per_cover_cents"] == expected

        # The released seat moved into the hold pool, not out of availability.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=2, held=1, released=0, available=1, status="OPEN"
        )

    def test_claiming_one_minute_after_the_offer_lapses_is_refused(self, api):
        """The offer deadline bites while the hold it minted is still alive.

        "It requires the entry to be `OFFERED`, the logical clock to be strictly
        before `offer_expires_at_utc` — otherwise `ERR_OFFER_EXPIRED` — the
        offered reservation to still be `PENDING`, and the offered
        reservation's ticket class to be in `OPEN`, `RELEASED` or `SOLD_OUT`."
        "Because `offer_ttl_minutes` is constrained to be at or below
        `hold_ttl_minutes`, the offer always lapses before the hold reservation
        it minted."

        Design: Corner/state_machines/precondition_waitlist_claim_after_offer_ttl_returns_offer_expired
        """
        world = _offered_world(api)
        FX.set_clock(api, ONE_MINUTE_PAST_THE_OFFER)

        response = api.claim_waitlist_entry(
            world["entry"]["id"], world["waiter_headers"]
        )
        validate_error(response, ERR_OFFER_EXPIRED, 409)

        # The hold outlives the offer, so nothing about the hold caused this.
        assert F.parse_iso(world["offered"]["hold_expires_at_utc"]) > F.parse_iso(
            ONE_MINUTE_PAST_THE_OFFER
        )
        assert F.parse_iso(world["entry"]["offer_expires_at_utc"]) < F.parse_iso(
            ONE_MINUTE_PAST_THE_OFFER
        )

        # The refusal changed nothing: the entry is still OFFERED, the hold is
        # still PENDING and the seats are still held.
        entry = FX.read_waitlist_entry(api, world["entry"]["id"], world["waiter_headers"])
        assert entry["status"] == "OFFERED"
        assert entry["offered_reservation_id"] == world["offered"]["id"]
        still_held = FX.read_reservation(
            api, world["offered"]["id"], world["waiter_headers"]
        )
        A.assert_fulfillment_status(still_held, "PENDING")
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=2, held=1, released=0, available=1, status="OPEN"
        )


class TestOfferedWithdrawal:
    """Leaving the queue reaches across to the reservation the offer minted."""

    def test_withdrawing_an_offer_cancels_the_hold_and_returns_the_released_seat(
        self, api
    ):
        """The withdrawal unwinds a second entity and a third counter.

        "The `OFFERED → WITHDRAWN` edge additionally cancels the offered
        `PENDING` reservation and returns its held seats to their originating
        pool." "`RELEASED` therefore outranks `OPEN` whenever both pools hold
        seats."

        Design: Corner/state_machines/cross_entity_waitlist_withdraw_cancels_the_offered_hold
        """
        world = _offered_world(api)

        withdrawn = get_success_data(
            api.withdraw_waitlist_entry(
                world["entry"]["id"], world["waiter_headers"]
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        cancelled = FX.read_reservation(
            api, world["offered"]["id"], world["waiter_headers"]
        )
        A.assert_fulfillment_status(cancelled, "CANCELLED")
        # Nothing was ever paid on the hold, so nothing is refunded or kept.
        A.assert_money_breakdown(cancelled, amount_paid=0, refunded=0, forfeited=0)

        # The seat goes back where it came from: the released pool, which
        # outranks ordinary availability on the ladder.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=2, held=0, released=1, available=1, status="RELEASED"
        )

    def test_a_withdrawn_entry_accepts_neither_withdrawal_nor_claim(self, api):
        """WITHDRAWN is terminal on both of the entry's outbound edges.

        "The waitlist entry is in the status the operation requires — `OFFERED`
        to claim, `WAITING` or `OFFERED` to withdraw — otherwise
        `ERR_WAITLIST_ENTRY_INVALID_STATE`." "`WAITING` and `OFFERED` are the
        live states; `CLAIMED`, `EXPIRED` and `WITHDRAWN` are terminal."

        Design: Corner/state_machines/cross_entity_waitlist_withdraw_cancels_the_offered_hold
        """
        world = _offered_world(api)
        FX.withdraw_entry(api, world["entry"]["id"], world["waiter"]["id"])

        second_withdraw = api.withdraw_waitlist_entry(
            world["entry"]["id"], world["waiter_headers"]
        )
        validate_error(second_withdraw, ERR_WAITLIST_ENTRY_INVALID_STATE, 409)

        late_claim = api.claim_waitlist_entry(
            world["entry"]["id"], world["waiter_headers"]
        )
        validate_error(late_claim, ERR_WAITLIST_ENTRY_INVALID_STATE, 409)

        entry = FX.read_waitlist_entry(
            api, world["entry"]["id"], world["waiter_headers"]
        )
        assert entry["status"] == "WITHDRAWN"
        # The holder's two covers were never in question.
        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["covers_confirmed"] == 2


# ─── the exhausted goodwill credit ────────────────────────────────────────


def _exhausted_credit_world(api):
    """A credit whose whole face value has been spent on a second booking.

    A party of two pays its 7722-cent deposit and cancels 48 hours out, keeping
    4361 cents with the restaurant. The guest contests that retention, the
    decider releases 1000 of the 4361 asked for, and the 3361-cent shortfall is
    issued as goodwill — which is then redeemed in full against a fresh hold.
    """
    world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
    guest_id = world["guest_id"]
    guest_headers = make_guest_headers(guest_id)

    first = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_id, party_size=2
    )
    FX.set_clock(api, CANCEL_AT_48H)
    FX.cancel(api, first["id"], guest_id)

    exception = FX.file_refund_exception(
        api, first["id"], 4361, headers=guest_headers
    )
    decided = FX.decide_refund_exception(
        api,
        exception["id"],
        decision="APPROVED",
        approved_cents=1000,
        decision_note_code="PARTIAL_GOODWILL",
        headers=CARE_DECIDER_HEADERS,
    )
    assert decided["shortfall_cents"] == 3361
    credit = FX.issue_goodwill_credit(
        api,
        decided["id"],
        3361,
        CREDIT_EXPIRES_AT,
        headers=CARE_ISSUER_HEADERS,
    )

    target = FX.hold_seats(
        api,
        world["ticket_class_id"],
        guest_id,
        party_size=2,
        primary_guest_name="Second Attempt",
    )
    row = FX.redeem_goodwill_credit(
        api, credit["id"], target["id"], 3361, guest_id=guest_id
    )

    world["first_reservation"] = first
    world["exception"] = decided
    world["credit"] = credit
    world["target"] = target
    world["redemption_row"] = row
    world["guest_headers"] = guest_headers
    return world


class TestExhaustedCreditLockdown:
    """Spending the last cent of a credit closes both of its remaining edges."""

    def test_redeeming_the_whole_remainder_exhausts_the_credit(self, api):
        """The exhausting redemption writes one row and moves four figures.

        "A successful redemption writes a `GOODWILL_REDEMPTION`
        `PaymentTransaction` of `amount_cents` on the target reservation with
        `memo_code` `CREDIT_APPLIED` and `goodwill_credit_id` set, credits
        `redeemed_cents` and debits `remaining_cents`, raises the reservation's
        `amount_paid_cents` — possibly advancing its `payment_status` all the way
        to `FULLY_PAID` — and advances the credit's `version` by one."
        "Redeeming strictly less than `remaining_cents` moves the credit
        `ISSUED → PARTIALLY_REDEEMED`; redeeming exactly `remaining_cents` moves
        it `ISSUED → EXHAUSTED` or `PARTIALLY_REDEEMED → EXHAUSTED`."

        Design: Corner/state_machines/terminal_state_lockdown_exhausted_credit_refuses_redeem_and_revoke
        """
        world = _exhausted_credit_world(api)
        row = world["redemption_row"]

        assert row["kind"] == "GOODWILL_REDEMPTION"
        assert row["amount_cents"] == 3361
        assert row["memo_code"] == "CREDIT_APPLIED"
        assert row["goodwill_credit_id"] == world["credit"]["id"]
        assert row["reservation_id"] == world["target"]["id"]
        A.assert_ledger_row_shape(row)
        A.assert_signed_amount(row)

        credit = FX.read_credit(
            api, world["credit"]["id"], world["guest_headers"]
        )
        assert credit["redeemed_cents"] == 3361
        assert credit["remaining_cents"] == 0
        assert credit["revoked_cents"] == 0
        assert credit["status"] == "EXHAUSTED"
        A.assert_credit_status(credit)
        A.assert_version_advanced_by(
            credit["version"], world["credit"]["version"], 1
        )

        # The credit lands in amount_paid_cents like cash, but 3361 cents is
        # short of both the grand total and the deposit due, so rule 3 of the
        # money derivation still reads UNPAID.
        target = FX.read_reservation(
            api, world["target"]["id"], world["guest_headers"]
        )
        A.assert_money_breakdown(
            target,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT,
            amount_paid=3361,
            goodwill_applied=3361,
        )
        assert target["balance_due_cents"] == GRAND_TOTAL - 3361
        A.assert_payment_status(target, "UNPAID")

    def test_an_exhausted_credit_refuses_a_further_redemption_and_a_revocation(
        self, api
    ):
        """Each door has its own error, and neither leaves a trace.

        "The credit must not be `REVOKED` — a redemption against a revoked credit
        is refused with `ERR_GOODWILL_CREDIT_INVALID_STATE`, while an exhausted
        credit instead falls through to the dedicated
        `ERR_GOODWILL_CREDIT_EXHAUSTED`, which fires whenever `remaining_cents`
        is not strictly above 0." "It is a `GuestServices` action that may
        optionally record a `reason_code`, and it requires the credit to be in
        `ISSUED` or `PARTIALLY_REDEEMED` — attempting it on an already
        `EXHAUSTED` or `REVOKED` credit is refused with
        `ERR_GOODWILL_CREDIT_INVALID_STATE` — and requires the acting
        `X-User-ID` to differ from `issued_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/terminal_state_lockdown_exhausted_credit_refuses_redeem_and_revoke
        """
        world = _exhausted_credit_world(api)
        credit_id = world["credit"]["id"]
        guest_headers = world["guest_headers"]

        exhausted = FX.read_credit(api, credit_id, guest_headers)
        assert exhausted["status"] == "EXHAUSTED"
        live_version = exhausted["version"]

        # A single further cent, quoting the credit's live version so that no
        # stale-view rejection can pre-empt the state check.
        again = api.redeem_goodwill_credit(
            credit_id,
            F.redemption_payload(world["target"]["id"], 1, live_version),
            guest_headers,
        )
        validate_error(again, ERR_GOODWILL_CREDIT_EXHAUSTED, 409)

        # The revoker is a different operator from the issuer, so segregation of
        # duties is satisfied and the state check is what refuses.
        revoke = api.revoke_goodwill_credit(credit_id, CARE_REVOKER_HEADERS)
        validate_error(revoke, ERR_GOODWILL_CREDIT_INVALID_STATE, 409)

        unchanged = FX.read_credit(api, credit_id, guest_headers)
        assert unchanged["status"] == "EXHAUSTED"
        assert unchanged["redeemed_cents"] == 3361
        assert unchanged["remaining_cents"] == 0
        assert unchanged["revoked_cents"] == 0
        assert unchanged["version"] == live_version
        A.assert_credit_identity(unchanged)

        # Nothing was appended: the one redemption row is still the only row
        # carrying this credit's id.
        rows = get_success_data(
            api.list_payment_transactions(
                guest_headers, {"goodwill_credit_id": credit_id, "limit": 100}
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == world["redemption_row"]["id"]


# ─── the two dimensions advancing on their own triggers ───────────────────


def _parallel_world(api):
    """A deposit-paid party of two, table-assigned for 22:00Z, with the clock
    standing exactly at the seating instant and 18018 cents still owed."""
    world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
    table = FX.create_table(
        api, world["restaurant_id"], table_code="T1", seats_min=2, seats_max=4
    )
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    FX.assign_table(
        api,
        world["restaurant_id"],
        reservation["id"],
        table["id"],
        SEATING_START,
    )
    FX.set_clock(api, SEATING_START)
    world["table"] = table
    world["reservation"] = reservation
    world["guest_headers"] = make_guest_headers(world["guest_id"])
    return world


class TestParallelStateDimensions:
    """The seating side reaches SEATED while the money side is still short."""

    def test_seating_advances_with_the_money_dimension_left_at_deposit_paid(
        self, api
    ):
        """A party sits down owing the balance, and the money side does not move.

        "A reservation carries **two independent state dimensions on the same
        row**, and they advance on different triggers." "Seating pins
        `seat_to_utc` to `seat_from_utc` plus the service's `turn_time_minutes`;
        until the party is seated, `seat_to_utc` is null."

        Design: Corner/state_machines/parallel_dimensions_payment_advances_independently_of_fulfillment
        """
        world = _parallel_world(api)

        before = FX.read_reservation(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(before, "CONFIRMED")
        A.assert_payment_status(before, "DEPOSIT_PAID")
        assert before["seat_to_utc"] is None
        assert before["assigned_table_id"] == world["table"]["id"]

        seated = get_success_data(
            api.seat_reservation(
                world["reservation"]["id"], world["manager_headers"]
            )
        )
        A.assert_fulfillment_status(seated, "SEATED")
        # The seating trigger moved one dimension and left the other alone.
        A.assert_payment_status(seated, "DEPOSIT_PAID")
        assert _same_instant(seated["seat_from_utc"], SEATING_START)
        assert _same_instant(seated["seat_to_utc"], SEAT_TO)
        assert seated["amount_paid_cents"] == DEPOSIT
        assert seated["balance_due_cents"] == BALANCE_AFTER_DEPOSIT
        A.assert_balance_due(seated)

    def test_the_balance_payment_moves_only_the_money_dimension(self, api):
        """Completion is blocked by the money side, then unblocked by it alone.

        "Completion advances the reservation `SEATED → COMPLETED` and is the
        point at which the money dimension gates the seating dimension: the
        reservation must read `FULLY_PAID`, and any outstanding balance refuses
        the operation with `ERR_BALANCE_OUTSTANDING`." "A later payment that
        clears the remainder of a deposit-paid reservation moves it
        `DEPOSIT_PAID → FULLY_PAID`, writing a `BALANCE_CHARGE` row with
        `memo_code` `GUEST_BALANCE`, driving `balance_due_cents` to 0 and thereby
        unblocking both completion and transfer."

        Design: Corner/state_machines/parallel_dimensions_payment_advances_independently_of_fulfillment
        """
        world = _parallel_world(api)
        reservation_id = world["reservation"]["id"]
        FX.seat(api, world["restaurant_id"], reservation_id)

        too_early = api.complete_reservation(
            reservation_id, world["manager_headers"]
        )
        validate_error(too_early, ERR_BALANCE_OUTSTANDING, 409)
        blocked = FX.read_reservation(api, reservation_id, world["guest_headers"])
        A.assert_fulfillment_status(blocked, "SEATED")
        A.assert_payment_status(blocked, "DEPOSIT_PAID")

        paid = FX.pay(
            api, reservation_id, world["guest_id"], BALANCE_AFTER_DEPOSIT
        )
        A.assert_payment_status(paid, "FULLY_PAID")
        assert paid["amount_paid_cents"] == GRAND_TOTAL
        assert paid["balance_due_cents"] == 0
        # The payment trigger left the seating dimension exactly where it was.
        A.assert_fulfillment_status(paid, "SEATED")

        rows = FX.ledger_rows(api, reservation_id, world["guest_headers"])
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE", "BALANCE_CHARGE"]
        assert rows[1]["amount_cents"] == BALANCE_AFTER_DEPOSIT
        assert rows[1]["memo_code"] == "GUEST_BALANCE"
        A.assert_created_at_ascending(rows)
        A.assert_derived_ledger_figures(paid, rows)

    def test_completion_needs_both_dimensions_and_credits_the_guest(self, api):
        """Only once both dimensions are ready does the last edge open.

        "Completing credits the guest's `completed_reservations_count` by 1 —
        which lifts that guest's waitlist standing everywhere, as §3.8 explains —
        reconciles the service's `gross_charged_cents` against the reservation's
        ledger, and advances the reservation's `version` by one."

        Design: Corner/state_machines/parallel_dimensions_payment_advances_independently_of_fulfillment
        """
        world = _parallel_world(api)
        reservation_id = world["reservation"]["id"]
        FX.seat(api, world["restaurant_id"], reservation_id)
        FX.pay(api, reservation_id, world["guest_id"], BALANCE_AFTER_DEPOSIT)

        before = FX.read_reservation(api, reservation_id, world["guest_headers"])
        completed = get_success_data(
            api.complete_reservation(reservation_id, world["manager_headers"])
        )
        A.assert_fulfillment_status(completed, "COMPLETED")
        A.assert_payment_status(completed, "FULLY_PAID")
        A.assert_version_advanced_by(completed["version"], before["version"], 1)

        guest = FX.read_guest(api, world["guest_id"], world["guest_headers"])
        assert guest["completed_reservations_count"] == 1

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["covers_confirmed"] == 2
        assert service["gross_charged_cents"] == GRAND_TOTAL
        assert service["refunded_cents"] == 0
        assert service["net_settled_cents"] == GRAND_TOTAL


# ─── the closing sweep ────────────────────────────────────────────────────


def _closing_world(api):
    """A finished service: one fully prepaid party of two seated and completed,
    no hold left outstanding, and the clock at `seating_end_utc`."""
    world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
    table = FX.create_table(
        api, world["restaurant_id"], table_code="T1", seats_min=2, seats_max=4
    )
    reservation = FX.hold_seats(
        api, world["ticket_class_id"], world["guest_id"], party_size=2
    )
    paid = FX.pay(api, reservation["id"], world["guest_id"], GRAND_TOTAL)
    FX.confirm(api, reservation["id"], world["guest_id"])
    FX.assign_table(
        api, world["restaurant_id"], reservation["id"], table["id"], SEATING_START
    )
    FX.set_clock(api, SEATING_START)
    FX.seat(api, world["restaurant_id"], reservation["id"])
    FX.complete(api, world["restaurant_id"], reservation["id"])
    FX.set_clock(api, SEATING_END)
    world["table"] = table
    world["reservation"] = reservation
    world["paid"] = paid
    world["guest_headers"] = make_guest_headers(world["guest_id"])
    return world


class TestHoldSweepClose:
    """The sweep that closes the night takes the ticket classes with it."""

    def test_closing_the_service_closes_every_ticket_class(self, api):
        """One sweep call ends the service and every class beneath it.

        "Passing `close_service` as true additionally moves the service
        `PUBLISHED → CLOSED`." "Closing moves every `TicketClass` of the service
        to `CLOSED` and recomputes the service's `net_settled_cents` as
        `gross_charged_cents` less `refunded_cents`."

        Design: Corner/state_machines/valid_transition_hold_sweep_close_service_closes_classes_and_settles
        """
        world = _closing_world(api)

        before = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert before["status"] == "PUBLISHED"

        FX.sweep_holds(api, world["service_id"], close_service=True)

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["status"] == "CLOSED"

        classes = get_success_data(
            api.list_ticket_classes(
                world["manager_headers"],
                {"service_id": world["service_id"], "limit": 100},
            )
        )
        assert len(classes) == 1
        for ticket_class in classes:
            assert ticket_class["status"] == "CLOSED"
            A.assert_seat_pool_identity(ticket_class)
            # CLOSED is sticky: the ladder no longer speaks for the counters.
            assert ticket_class["seats_sold"] == 2
            assert ticket_class["seats_available"] == 18

    def test_the_close_settles_the_service_money_and_leaves_the_booking_alone(
        self, api
    ):
        """The roll-ups settle while the completed reservation is untouched.

        "A service's `covers_confirmed` tracks the sum of party sizes over its
        reservations in `CONFIRMED`, `SEATED` or `COMPLETED`; its
        `gross_charged_cents` is the sum of inbound ledger magnitudes across its
        reservations; its `refunded_cents` and `forfeited_cents` are the
        corresponding outbound sums; and its `net_settled_cents` is
        `gross_charged_cents` minus `refunded_cents`."

        Design: Corner/state_machines/valid_transition_hold_sweep_close_service_closes_classes_and_settles
        """
        world = _closing_world(api)

        # The whole ticket was taken in one payment, before anything was paid.
        A.assert_payment_status(world["paid"], "FULLY_PAID")
        assert world["paid"]["balance_due_cents"] == 0

        FX.sweep_holds(api, world["service_id"], close_service=True)

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["covers_confirmed"] == 2
        assert service["gross_charged_cents"] == GRAND_TOTAL
        assert service["refunded_cents"] == 0
        assert service["forfeited_cents"] == 0
        assert service["net_settled_cents"] == GRAND_TOTAL - 0

        booking = FX.read_reservation(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(booking, "COMPLETED")
        A.assert_payment_status(booking, "FULLY_PAID")
        rows = FX.ledger_rows(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE"]
        assert rows[0]["amount_cents"] == GRAND_TOTAL
        A.assert_signed_sum_matches(booking, rows)

    def test_a_closed_service_refuses_a_second_close(self, api):
        """CLOSED is terminal, so the sweep's own state gate refuses it.

        "The service is in the status the operation itself requires — `DRAFT` to
        publish, `DRAFT` or `PUBLISHED` to cancel, `PUBLISHED` to close — on
        service publish, service cancel, hold sweep and ticket-class creation —
        otherwise `ERR_SERVICE_INVALID_STATE`." "The four legal service states
        are `DRAFT`, `PUBLISHED`, `CLOSED` and `CANCELLED`, with `CLOSED` and
        `CANCELLED` both terminal."

        Design: Corner/state_machines/valid_transition_hold_sweep_close_service_closes_classes_and_settles
        """
        world = _closing_world(api)
        FX.sweep_holds(api, world["service_id"], close_service=True)

        again = api.hold_sweep(
            world["service_id"], ADMIN_HEADERS, {"close_service": True}
        )
        validate_error(again, ERR_SERVICE_INVALID_STATE, 409)

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["status"] == "CLOSED"
        assert service["net_settled_cents"] == GRAND_TOTAL
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        assert ticket_class["status"] == "CLOSED"
