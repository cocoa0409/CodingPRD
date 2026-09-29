"""
The state machines of the Service, the TicketClass and the Reservation: where
each entity starts, which edges are real, which repeats are refused, and how
completely a terminal state locks a row down.

Every scenario below builds its own world from the declared endpoints only —
a restaurant, a Thursday DINNER service, one twenty-seat ticket class and the
guests it needs — and pins the logical clock explicitly, because every deadline
and cutoff in the system reads that clock rather than the host's wall clock.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import (
    ERR_DEPOSIT_NOT_SETTLED,
    ERR_HOLD_EXPIRED,
    ERR_PAYMENT_BELOW_DEPOSIT,
    ERR_RESERVATION_INVALID_STATE,
    ERR_SERVICE_INVALID_STATE,
    ERR_SERVICE_NOT_PUBLISHED,
    ERR_TICKET_CLASS_INVALID_STATE,
    ERR_TICKET_CLASS_NOT_SELLABLE,
)
from test_helpers.test_users import ADMIN_HEADERS, make_guest_headers

# The instant every scenario pins its clock to before anything else happens. It
# is strictly before the seating start, so no hold, cutoff or release window has
# lapsed at setup time.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
# The Thursday seating the standard world trades on. Thursday is neutral at
# 10000 basis points and the STANDARD tier is neutral too, so a 12000-cent cover
# prices at exactly 12000 before any scarcity step.
SEATING_START = "2026-09-10T22:00:00Z"
# One minute past the 20-minute hold minted at SETUP_CLOCK.
PAST_HOLD_EXPIRY = "2026-09-01T00:21:00Z"
# Inside the release window, which opens 180 minutes before the seating start.
INSIDE_RELEASE_WINDOW = "2026-09-10T21:00:00Z"

PRICE_PER_COVER = 12000
TICKET_SUBTOTAL = 24000
SERVICE_CHARGE = 1740
GRAND_TOTAL = 25740
DEPOSIT_DUE = 7722
BALANCE_AFTER_DEPOSIT = 18018


def _draft_world(api, *, guests=1):
    """A DRAFT service carrying one twenty-seat class, plus its guests."""
    return FX.build_world(api, clock=SETUP_CLOCK, publish=False, guests=guests)


def _published_world(api, *, guests=1):
    """The same world with the service already PUBLISHED and trading."""
    return FX.build_world(api, clock=SETUP_CLOCK, guests=guests)


def _fresh_class_version(api, ticket_class_id, headers):
    """The class version read immediately before a create, so that the
    stale-view rejection can never be what answers the request."""
    return FX.read_ticket_class(api, ticket_class_id, headers)["version"]


def _request_reservation(api, ticket_class_id, guest_id, *, party_size=2, name="Corner Guest"):
    """POST one reservation for a guest, echoing the class's live version."""
    headers = make_guest_headers(guest_id)
    payload = F.reservation_payload(
        ticket_class_id,
        guest_id,
        _fresh_class_version(api, ticket_class_id, headers),
        party_size=party_size,
        primary_guest_name=name,
    )
    return api.create_reservation(payload, headers)


def _row_count(api, endpoint_params, lister):
    """The total_count a filtered list endpoint reports."""
    _, meta = validate_paginated(lister(ADMIN_HEADERS, endpoint_params))
    return meta["total_count"]


class TestInitialStates:
    """Where each entity starts when nothing but a create has happened."""

    def test_service_is_born_draft_and_its_class_lands_open(self, api):
        """A create leaves the service in DRAFT and its class in OPEN.

        "On creation the class's `seats_available` is initialised to the whole of
        `seats_allocated`, `seats_sold`, `seats_held` and `seats_released` all
        start at 0, `status` starts at `OPEN`, and both
        `list_price_per_cover_cents` and `release_price_per_cover_cents` are
        computed immediately from the pricing rules of §3.2."

        Design: Corner/state_machines/initial_state_core_entities_start_in_declared_initial_states
        """
        world = _draft_world(api)

        service = world["service"]
        assert service["status"] == "DRAFT"
        assert service["day_of_week"] == "THU"
        for rollup in (
            "release_run_count",
            "seats_released_total",
            "last_release_released_count",
            "last_release_promoted_count",
            "covers_confirmed",
            "gross_charged_cents",
            "refunded_cents",
            "forfeited_cents",
            "net_settled_cents",
        ):
            assert service[rollup] == 0, f"{rollup} should begin at 0"

        ticket_class = world["ticket_class"]
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=0, available=20, status="OPEN"
        )
        assert ticket_class["list_price_per_cover_cents"] == PRICE_PER_COVER
        A.assert_common_fields(service)
        A.assert_common_fields(ticket_class)

    def test_a_fresh_hold_starts_pending_on_seating_and_unpaid_on_money(self, api):
        """The two dimensions of one reservation row start independently.

        "The reservation lands in `fulfillment_status` `PENDING` and
        `payment_status` `UNPAID`, with `assigned_table_id`,
        `transferred_from_reservation_id`, `seat_from_utc`, `seat_to_utc` and
        `cancel_settlement_basis` all null, `is_release_priced` and
        `deposit_frozen` both false, `name_change_count` at 0, and every money
        roll-up other than the ones just named at 0."

        Design: Corner/state_machines/initial_state_core_entities_start_in_declared_initial_states
        """
        world = _published_world(api)
        reservation = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )

        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")
        for field in (
            "assigned_table_id",
            "transferred_from_reservation_id",
            "seat_from_utc",
            "seat_to_utc",
            "cancel_settlement_basis",
        ):
            assert reservation[field] is None, f"{field} should start null"
        assert reservation["is_release_priced"] is False
        assert reservation["deposit_frozen"] is False
        assert reservation["name_change_count"] == 0
        A.assert_money_breakdown(
            reservation,
            amount_paid=0,
            refunded=0,
            forfeited=0,
            goodwill_applied=0,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
        )

    def test_note_waitlist_and_guest_counters_start_at_their_declared_values(
        self, api
    ):
        """A dietary note, a waitlist entry and a guest all start clean.

        "A new note begins with `ack_status` `PENDING`, `reject_reason_code`
        null, `amend_count` at 0 and `acked_by_user_id` null." "A new entry
        starts `WAITING` with `offer_round` at 0, `offered_reservation_id` and
        `offer_expires_at_utc` null, and its `priority_score` computed
        immediately."

        Design: Corner/state_machines/initial_state_core_entities_start_in_declared_initial_states
        """
        world = _published_world(api, guests=2)
        booking_guest, waiting_guest = world["guests"][0], world["guests"][1]
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], booking_guest["id"], party_size=2
        )
        note = FX.add_dietary_note(
            api, reservation["id"], booking_guest["id"], severity="ALLERGY"
        )
        entry = FX.join_waitlist(
            api, world["service_id"], waiting_guest["id"], party_size=2
        )

        assert note["ack_status"] == "PENDING"
        assert note["reject_reason_code"] is None
        assert note["amend_count"] == 0
        assert note["acked_by_user_id"] is None

        assert entry["status"] == "WAITING"
        assert entry["offer_round"] == 0
        assert entry["offered_reservation_id"] is None
        assert entry["offer_expires_at_utc"] is None
        assert entry["priority_score"] == 1100

        fresh_guest = FX.read_guest(
            api, waiting_guest["id"], make_guest_headers(waiting_guest["id"])
        )
        assert fresh_guest["no_show_strikes"] == 0
        assert fresh_guest["completed_reservations_count"] == 0
        assert fresh_guest["transfers_initiated_count"] == 0
        assert fresh_guest["lifetime_refunded_cents"] == 0
        assert fresh_guest["refund_scrutiny_flag"] is False


class TestPublicationOpensTheServiceForSales:
    """DRAFT → PUBLISHED is the edge that turns configuration into trade."""

    def test_a_draft_service_refuses_the_sale_and_publish_flips_both_rows(self, api):
        """The identical create is refused before publication and the edge lands.

        "Before publication they cannot: a create against a `DRAFT`, `CLOSED` or
        `CANCELLED` service is refused with `ERR_SERVICE_NOT_PUBLISHED`."
        "Publication re-evaluates every ticket class of the service against the
        seat-pool precedence ladder — a freshly allocated class with availability
        lands on `OPEN` — and from that instant reservations may be created
        against the service."

        Design: Corner/state_machines/valid_transition_publish_opens_the_service_for_sales
        """
        world = _draft_world(api)
        guest_id = world["guest_id"]
        # The class was created moments ago and nothing has touched it since, so
        # the version echoed here is the live one.
        payload = F.reservation_payload(
            world["ticket_class_id"],
            guest_id,
            world["ticket_class"]["version"],
            party_size=2,
        )
        refused = api.create_reservation(payload, make_guest_headers(guest_id))
        validate_error(refused, ERR_SERVICE_NOT_PUBLISHED, 409)

        # Nothing was reserved by the refusal.
        assert (
            _row_count(api, {"service_id": world["service_id"]}, api.list_reservations)
            == 0
        )

        published = FX.publish_service(api, world["restaurant_id"], world["service_id"])
        assert published["status"] == "PUBLISHED"
        opened = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            opened, sold=0, held=0, released=0, available=20, status="OPEN"
        )

    def test_the_same_create_succeeds_once_the_service_is_published(self, api):
        """After the edge the create takes seats and locks the quoted price.

        "The per-cover price is locked into `price_locked_per_cover_cents`."
        "`party_size` seats move out of `seats_available` and into `seats_held`,
        after which the class's status is re-derived against the precedence
        ladder and the class's `version` advances by one."

        Design: Corner/state_machines/valid_transition_publish_opens_the_service_for_sales
        """
        world = _draft_world(api)
        FX.publish_service(api, world["restaurant_id"], world["service_id"])

        created = validate_success(
            _request_reservation(api, world["ticket_class_id"], world["guest_id"]), 201
        )
        A.assert_fulfillment_status(created, "PENDING")
        assert created["price_locked_per_cover_cents"] == PRICE_PER_COVER
        A.assert_money_breakdown(
            created,
            ticket_subtotal=TICKET_SUBTOTAL,
            service_charge=SERVICE_CHARGE,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
        )

        sold_from = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            sold_from, sold=0, held=2, released=0, available=18, status="OPEN"
        )


class TestRepeatedServiceMovesAreRefused:
    """A completed service move is not repeatable, in either direction."""

    def test_publishing_an_already_published_service_is_refused(self, api):
        """The second publish finds the wrong precondition state.

        "The service is in the status the operation itself requires — `DRAFT` to
        publish, `DRAFT` or `PUBLISHED` to cancel, `PUBLISHED` to close — on
        service publish, service cancel, hold sweep and ticket-class creation —
        otherwise `ERR_SERVICE_INVALID_STATE`."

        Design: Corner/state_machines/idempotency_second_publish_and_publish_after_cancel_rejected
        """
        world = _published_world(api)

        again = api.publish_service(world["service_id"], world["manager_headers"])
        validate_error(again, ERR_SERVICE_INVALID_STATE, 409)

        still_trading = FX.read_service(
            api, world["service_id"], world["manager_headers"]
        )
        assert still_trading["status"] == "PUBLISHED"
        unchanged = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            unchanged, sold=0, held=0, released=0, available=20, status="OPEN"
        )

    def test_a_cancelled_service_refuses_both_a_second_cancel_and_a_publish(self, api):
        """CANCELLED is terminal, so neither move is available afterwards.

        "From `DRAFT` the cancellation is quiet: the service moves `DRAFT →
        CANCELLED` and every one of its ticket classes moves to `CLOSED`, and
        nothing else happens because nothing has been sold." "Both `CLOSED` and
        `CANCELLED` are terminal for a service."

        Design: Corner/state_machines/idempotency_second_publish_and_publish_after_cancel_rejected
        """
        world = _draft_world(api)
        manager = world["manager_headers"]
        # A second, published service of the same restaurant proves the quiet
        # cancellation touches only the classes of the service it names.
        sibling = FX.create_service(
            api,
            world["restaurant_id"],
            service_date="2026-09-10",
            meal_period="LUNCH",
            seating_start_utc="2026-09-10T16:00:00Z",
            seating_end_utc="2026-09-10T18:00:00Z",
            seats_capacity=20,
        )
        sibling_class = FX.create_ticket_class(
            api,
            world["restaurant_id"],
            sibling["id"],
            world["package_id"],
            seats_allocated=20,
        )
        FX.publish_service(api, world["restaurant_id"], sibling["id"])

        cancelled = validate_success(
            api.cancel_service(
                world["service_id"], manager, {"reason_code": "KITCHEN_CLOSURE"}
            )
        )
        assert cancelled["status"] == "CANCELLED"
        closed_class = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        assert closed_class["status"] == "CLOSED"

        second_cancel = api.cancel_service(world["service_id"], manager)
        validate_error(second_cancel, ERR_SERVICE_INVALID_STATE, 409)
        publish_after_cancel = api.publish_service(world["service_id"], manager)
        validate_error(publish_after_cancel, ERR_SERVICE_INVALID_STATE, 409)

        # The terminal service and its class are exactly where the first cancel
        # left them, and the sibling never noticed.
        after = FX.read_service(api, world["service_id"], manager)
        assert after["status"] == "CANCELLED"
        assert FX.read_ticket_class(api, world["ticket_class_id"], manager)["status"] == "CLOSED"
        assert FX.read_ticket_class(api, sibling_class["id"], manager)["status"] == "OPEN"
        assert FX.read_service(api, sibling["id"], manager)["status"] == "PUBLISHED"


class TestDraftServiceRefusesTheTradingMoves:
    """A service that never opened cannot release, be joined, or be closed."""

    def test_a_release_run_and_a_waitlist_join_are_both_refused_on_draft(self, api):
        """Both moves demand a service that is trading, not one still configuring.

        "The owning service is `PUBLISHED`, on reservation creation,
        waitlist-entry creation, release runs and ticket-class resume — otherwise
        `ERR_SERVICE_NOT_PUBLISHED`." "It is legal only while the service is
        `PUBLISHED` and only once the logical clock has reached the service's
        `seating_start_utc` less its `release_lead_minutes`; firing earlier is
        refused with `ERR_RELEASE_WINDOW_NOT_OPEN`."

        Design: Corner/state_machines/invalid_transitions_draft_service_refuses_release_run_and_close
        """
        world = _draft_world(api)
        guest_id = world["guest_id"]
        # 180 minutes before the 22:00 seating start, so the release window is
        # wide open and only the service's own status can be at fault.
        FX.set_clock(api, INSIDE_RELEASE_WINDOW)

        refused_run = api.release_run(world["service_id"], world["manager_headers"])
        validate_error(refused_run, ERR_SERVICE_NOT_PUBLISHED, 409)

        refused_join = api.create_waitlist_entry(
            F.waitlist_entry_payload(world["service_id"], guest_id, party_size=2),
            make_guest_headers(guest_id),
        )
        validate_error(refused_join, ERR_SERVICE_NOT_PUBLISHED, 409)

        after = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert after["status"] == "DRAFT"
        assert after["release_run_count"] == 0
        assert after["seats_released_total"] == 0
        assert after["last_release_released_count"] == 0
        assert after["last_release_promoted_count"] == 0
        assert (
            _row_count(
                api, {"service_id": world["service_id"]}, api.list_waitlist_entries
            )
            == 0
        )
        untouched = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            untouched, sold=0, held=0, released=0, available=20, status="OPEN"
        )

    def test_closing_a_draft_service_and_resuming_its_paused_class_both_fail(self, api):
        """Closure wants a published service, and so does a resume.

        "The service is in the status the operation itself requires — `DRAFT` to
        publish, `DRAFT` or `PUBLISHED` to cancel, `PUBLISHED` to close — on
        service publish, service cancel, hold sweep and ticket-class creation —
        otherwise `ERR_SERVICE_INVALID_STATE`." "Resuming requires the class to
        be `PAUSED` and the owning service to be `PUBLISHED` — a class of a
        service that has since left `PUBLISHED` cannot be resumed, and the
        attempt is refused with `ERR_SERVICE_NOT_PUBLISHED`."

        Design: Corner/state_machines/invalid_transitions_draft_service_refuses_release_run_and_close
        """
        world = _draft_world(api)
        manager = world["manager_headers"]

        # Pausing needs only an OPEN class, so it is available on a DRAFT
        # service and gives the resume a legitimate starting status.
        paused = validate_success(
            api.pause_ticket_class(world["ticket_class_id"], manager)
        )
        assert paused["status"] == "PAUSED"

        # Past the seating end, so the closure's timing precondition is met and
        # only the service's status stands in the way.
        FX.set_clock(api, "2026-09-11T03:00:00Z")
        refused_close = api.hold_sweep(
            world["service_id"], ADMIN_HEADERS, {"close_service": True}
        )
        validate_error(refused_close, ERR_SERVICE_INVALID_STATE, 409)

        refused_resume = api.resume_ticket_class(world["ticket_class_id"], manager)
        validate_error(refused_resume, ERR_SERVICE_NOT_PUBLISHED, 409)

        assert FX.read_service(api, world["service_id"], manager)["status"] == "DRAFT"
        still_paused = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            still_paused, sold=0, held=0, released=0, available=20, status="PAUSED"
        )


class TestPauseResumeRoundTrip:
    """OPEN → PAUSED → OPEN, and neither leg repeats."""

    def test_pause_suspends_the_class_and_a_second_pause_is_refused(self, api):
        """The suspension lands once and moves no seat while doing it.

        "Pausing is the requested suspension. It advances the class `OPEN →
        PAUSED`, requires the class to be `OPEN` — any other status is refused
        with `ERR_TICKET_CLASS_INVALID_STATE` — and takes no payload."
        "Crucially, pausing **releases nothing**: `seats_available`,
        `seats_held`, `seats_sold` and `seats_released` all stand exactly as they
        were, which is what makes `PAUSED` sticky at the top of the ladder rather
        than a state the arithmetic can fall out of."

        Design: Corner/state_machines/pause_resume_round_trip_and_second_pause_rejected
        """
        world = _published_world(api)
        manager = world["manager_headers"]

        paused = validate_success(
            api.pause_ticket_class(world["ticket_class_id"], manager)
        )
        A.assert_seat_pool(
            paused, sold=0, held=0, released=0, available=20, status="PAUSED"
        )

        again = api.pause_ticket_class(world["ticket_class_id"], manager)
        validate_error(again, ERR_TICKET_CLASS_INVALID_STATE, 409)

        still_paused = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            still_paused, sold=0, held=0, released=0, available=20, status="PAUSED"
        )

    def test_a_paused_class_refuses_a_direct_sale_and_writes_no_row(self, api):
        """PAUSED is never sellable, however many seats are still free.

        "The ticket class is sellable: `OPEN` or `RELEASED` for a direct
        reservation, and `OPEN`, `RELEASED` or `SOLD_OUT` for a waitlist claim,
        with `PAUSED` and `CLOSED` always failing — on reservation creation and
        waitlist claim — otherwise `ERR_TICKET_CLASS_NOT_SELLABLE`."

        Design: Corner/state_machines/pause_resume_round_trip_and_second_pause_rejected
        """
        world = _published_world(api)
        manager = world["manager_headers"]
        validate_success(api.pause_ticket_class(world["ticket_class_id"], manager))

        refused = _request_reservation(api, world["ticket_class_id"], world["guest_id"])
        validate_error(refused, ERR_TICKET_CLASS_NOT_SELLABLE, 409)

        assert (
            _row_count(
                api,
                {"ticket_class_id": world["ticket_class_id"]},
                api.list_reservations,
            )
            == 0
        )
        untouched = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            untouched, sold=0, held=0, released=0, available=20, status="PAUSED"
        )

    def test_resume_returns_the_class_to_open_and_a_second_resume_is_refused(self, api):
        """The return leg re-derives OPEN from the pools and then closes behind it.

        "When `seats_released` is 0 and `seats_available` is above 0 it takes
        `PAUSED → OPEN`." "The ticket class is in the status the operation
        requires — `OPEN` to pause, `PAUSED` to resume — otherwise
        `ERR_TICKET_CLASS_INVALID_STATE`."

        Design: Corner/state_machines/pause_resume_round_trip_and_second_pause_rejected
        """
        world = _published_world(api)
        manager = world["manager_headers"]
        validate_success(api.pause_ticket_class(world["ticket_class_id"], manager))

        resumed = validate_success(
            api.resume_ticket_class(world["ticket_class_id"], manager)
        )
        A.assert_seat_pool(
            resumed, sold=0, held=0, released=0, available=20, status="OPEN"
        )

        again = api.resume_ticket_class(world["ticket_class_id"], manager)
        validate_error(again, ERR_TICKET_CLASS_INVALID_STATE, 409)

        # Sales work again on exactly the pool the pause preserved.
        created = validate_success(
            _request_reservation(api, world["ticket_class_id"], world["guest_id"]), 201
        )
        A.assert_fulfillment_status(created, "PENDING")
        selling_again = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            selling_again, sold=0, held=2, released=0, available=18, status="OPEN"
        )


class TestConfirmationPreconditions:
    """PENDING → CONFIRMED is gated on the money dimension, not on the guest's word."""

    def test_confirming_an_unpaid_hold_is_refused(self, api):
        """The seating edge will not fire while the money dimension reads UNPAID.

        "It requires the reservation to still be `PENDING`, the logical clock to
        be strictly before `hold_expires_at_utc`, the money dimension to read
        `DEPOSIT_PAID` or `FULLY_PAID` — a still-`UNPAID` reservation is refused
        with `ERR_DEPOSIT_NOT_SETTLED` — and the owning ticket class not to be
        `CLOSED`."

        Design: Corner/state_machines/precondition_confirm_requires_settled_deposit_and_live_hold
        """
        world = _published_world(api)
        guest_id = world["guest_id"]
        reservation = FX.hold_seats(
            api, world["ticket_class_id"], guest_id, party_size=2
        )

        refused = api.confirm_reservation(
            reservation["id"], make_guest_headers(guest_id)
        )
        validate_error(refused, ERR_DEPOSIT_NOT_SETTLED, 409)

        after = FX.read_reservation(api, reservation["id"], make_guest_headers(guest_id))
        A.assert_fulfillment_status(after, "PENDING")
        A.assert_payment_status(after, "UNPAID")
        assert after["hold_expires_at_utc"] is not None
        assert after["deposit_frozen"] is False
        held_still = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            held_still, sold=0, held=2, released=0, available=18, status="OPEN"
        )
        assert (
            FX.read_service(api, world["service_id"], world["manager_headers"])[
                "covers_confirmed"
            ]
            == 0
        )

    def test_the_first_payment_must_reach_the_deposit_to_the_cent(self, api):
        """One cent short writes nothing; the exact deposit settles the money side.

        "A payment may never exceed the reservation's `balance_due_cents`
        (`ERR_PAYMENT_EXCEEDS_BALANCE`), and the very first payment on a
        reservation must be at least `deposit_due_cents`
        (`ERR_PAYMENT_BELOW_DEPOSIT`)." "A payment on a still-unpaid reservation
        that brings the cumulative `amount_paid_cents` to at least
        `deposit_due_cents` but leaves it strictly below `grand_total_cents`
        writes a `DEPOSIT_CHARGE` row with `memo_code` `GUEST_PREPAY` and moves
        the money dimension `UNPAID → DEPOSIT_PAID`, with `balance_due_cents`
        recomputed as `grand_total_cents` less `amount_paid_cents`."

        Design: Corner/state_machines/precondition_confirm_requires_settled_deposit_and_live_hold
        """
        world = _published_world(api)
        guest_id = world["guest_id"]
        guest = make_guest_headers(guest_id)
        reservation = FX.hold_seats(
            api, world["ticket_class_id"], guest_id, party_size=2
        )
        assert reservation["deposit_due_cents"] == DEPOSIT_DUE

        one_cent_short = api.take_payment(
            reservation["id"], F.payment_payload(DEPOSIT_DUE - 1), guest
        )
        validate_error(one_cent_short, ERR_PAYMENT_BELOW_DEPOSIT, 402)
        assert FX.ledger_rows(api, reservation["id"], guest) == []
        unmoved = FX.read_reservation(api, reservation["id"], guest)
        A.assert_payment_status(unmoved, "UNPAID")
        assert unmoved["amount_paid_cents"] == 0
        assert unmoved["deposit_frozen"] is False

        settled = FX.pay(api, reservation["id"], guest_id, DEPOSIT_DUE)
        A.assert_payment_status(settled, "DEPOSIT_PAID")
        assert settled["amount_paid_cents"] == DEPOSIT_DUE
        assert settled["balance_due_cents"] == BALANCE_AFTER_DEPOSIT
        A.assert_balance_due(settled)
        assert settled["deposit_frozen"] is True

        rows = FX.ledger_rows(api, reservation["id"], guest)
        assert len(rows) == 1
        assert rows[0]["kind"] == "DEPOSIT_CHARGE"
        assert rows[0]["memo_code"] == "GUEST_PREPAY"
        assert rows[0]["amount_cents"] == DEPOSIT_DUE
        A.assert_ledger_row_shape(rows[0])
        A.assert_signed_amount(rows[0])

    def test_a_settled_deposit_and_a_live_hold_let_the_confirmation_through(self, api):
        """The edge fires, moves the seats across the pool and books the covers.

        "Confirming clears `hold_expires_at_utc` to null, sets `deposit_frozen`
        to true and so freezes `deposit_due_cents` against every later add-on or
        price change, debits `party_size` from the class's `seats_held` and
        credits the same count to `seats_sold` so that the pool total is
        unchanged, credits `party_size` to the service's `covers_confirmed`, and
        advances the reservation's `version` by one."

        Design: Corner/state_machines/precondition_confirm_requires_settled_deposit_and_live_hold
        """
        world = _published_world(api)
        guest_id = world["guest_id"]
        guest = make_guest_headers(guest_id)
        reservation = FX.deposit_paid_reservation(
            api, world["ticket_class_id"], guest_id, party_size=2
        )
        before_version = reservation["version"]

        confirmed = validate_success(api.confirm_reservation(reservation["id"], guest))
        A.assert_fulfillment_status(confirmed, "CONFIRMED")
        A.assert_payment_status(confirmed, "DEPOSIT_PAID")
        assert confirmed["hold_expires_at_utc"] is None
        assert confirmed["deposit_frozen"] is True
        assert confirmed["deposit_due_cents"] == DEPOSIT_DUE
        A.assert_version_advanced_by(confirmed["version"], before_version, 1)

        pool = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            pool, sold=2, held=0, released=0, available=18, status="OPEN"
        )

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["covers_confirmed"] == 2
        assert service["gross_charged_cents"] == DEPOSIT_DUE
        assert service["refunded_cents"] == 0
        assert service["forfeited_cents"] == 0
        assert service["net_settled_cents"] == DEPOSIT_DUE


def _lapsed_hold_world(api):
    """A deposit-paid PENDING hold whose 20-minute hold has just lapsed, with
    another guest waiting on the same service."""
    world = _published_world(api, guests=2)
    holder, waiter = world["guests"][0], world["guests"][1]
    reservation = FX.deposit_paid_reservation(
        api, world["ticket_class_id"], holder["id"], party_size=2
    )
    entry = FX.join_waitlist(api, world["service_id"], waiter["id"], party_size=2)
    # One minute past hold_expires_at_utc, which the 20-minute default put at
    # 2026-09-01T00:20:00Z.
    FX.set_clock(api, PAST_HOLD_EXPIRY)
    world["holder"] = holder
    world["waiter"] = waiter
    world["reservation"] = reservation
    world["entry"] = entry
    return world


class TestHoldSweepExpiresAndRefunds:
    """A lapsed hold cannot be rescued, and the sweep unwinds it in full."""

    def test_confirming_after_the_hold_lapsed_is_refused(self, api):
        """The lapsed hold blocks the confirmation even though the deposit is paid.

        "For a `PENDING` reservation, the logical clock is strictly before
        `hold_expires_at_utc`, on confirm, payment and waitlist claim — otherwise
        `ERR_HOLD_EXPIRED`."

        Design: Corner/state_machines/side_effect_hold_sweep_expires_reservation_and_refunds_hold_lapse
        """
        world = _lapsed_hold_world(api)
        holder = make_guest_headers(world["holder"]["id"])

        refused = api.confirm_reservation(world["reservation"]["id"], holder)
        validate_error(refused, ERR_HOLD_EXPIRED, 409)

        untouched = FX.read_reservation(api, world["reservation"]["id"], holder)
        A.assert_fulfillment_status(untouched, "PENDING")
        A.assert_payment_status(untouched, "DEPOSIT_PAID")
        assert untouched["deposit_frozen"] is True
        assert untouched["refunded_cents"] == 0
        still_held = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            still_held, sold=0, held=2, released=0, available=18, status="OPEN"
        )

    def test_the_sweep_expires_the_hold_and_refunds_what_was_paid(self, api):
        """PENDING → EXPIRED, a HOLD_LAPSE refund, and the seats go back.

        "The sweep advances every `PENDING` reservation whose
        `hold_expires_at_utc` the logical clock has reached along `PENDING →
        EXPIRED`." "Anything the guest had paid is refunded in full with
        `memo_code` `HOLD_LAPSE`." "Otherwise, if `refunded_cents` equals
        `amount_paid_cents`, it is `REFUNDED`."

        Design: Corner/state_machines/side_effect_hold_sweep_expires_reservation_and_refunds_hold_lapse
        """
        world = _lapsed_hold_world(api)
        holder = make_guest_headers(world["holder"]["id"])

        FX.sweep_holds(api, world["service_id"])

        swept = FX.read_reservation(api, world["reservation"]["id"], holder)
        A.assert_fulfillment_status(swept, "EXPIRED")
        A.assert_payment_status(swept, "REFUNDED")
        assert swept["amount_paid_cents"] == DEPOSIT_DUE
        assert swept["refunded_cents"] == DEPOSIT_DUE
        assert swept["forfeited_cents"] == 0
        A.assert_settled_ledger_identity(swept)

        rows = FX.ledger_rows(api, world["reservation"]["id"], holder)
        # The charge row is untouched and the reversal is a new row beside it.
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE", "REFUND"]
        refund = rows[1]
        assert refund["memo_code"] == "HOLD_LAPSE"
        assert refund["amount_cents"] == DEPOSIT_DUE
        assert refund["signed_amount_cents"] == -DEPOSIT_DUE
        A.assert_ledger_row_shape(refund)
        A.assert_signed_amount(refund)
        A.assert_signed_sum_matches(swept, rows)

        recycled = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            recycled, sold=0, held=0, released=0, available=20, status="OPEN"
        )

    def test_the_sweep_promotes_nobody_and_reconciles_the_parents(self, api):
        """Seats recovered by a sweep sit in the pool, and the money is booked.

        "It re-evaluates the precedence ladder, but — unlike a cancellation or a
        no-show — it triggers **no waitlist promotion whatsoever**, so seats
        recovered by a sweep sit in the pool until someone buys them or a release
        run offers them." "After **every** `REFUND` row is written — from any
        trigger, at any restaurant — the refunded amount is credited to that
        guest's `lifetime_refunded_cents`."

        Design: Corner/state_machines/side_effect_hold_sweep_expires_reservation_and_refunds_hold_lapse
        """
        world = _lapsed_hold_world(api)
        waiter_headers = make_guest_headers(world["waiter"]["id"])

        FX.sweep_holds(api, world["service_id"])

        passed_over = FX.read_waitlist_entry(api, world["entry"]["id"], waiter_headers)
        assert passed_over["status"] == "WAITING"
        assert passed_over["offer_round"] == 0
        assert passed_over["offered_reservation_id"] is None
        assert passed_over["offer_expires_at_utc"] is None

        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["covers_confirmed"] == 0
        assert service["gross_charged_cents"] == DEPOSIT_DUE
        assert service["refunded_cents"] == DEPOSIT_DUE
        assert service["forfeited_cents"] == 0
        assert service["net_settled_cents"] == 0

        # 7722 cents refunded is far short of the 300000-cent scrutiny threshold.
        holder = FX.read_guest(
            api, world["holder"]["id"], make_guest_headers(world["holder"]["id"])
        )
        assert holder["lifetime_refunded_cents"] == DEPOSIT_DUE
        assert holder["refund_scrutiny_flag"] is False


def _cancelled_hold_world(api):
    """A cancelled party-of-two hold, with a table, an add-on and a second guest
    standing by so that every refused write is refused for one reason only."""
    world = _published_world(api, guests=2)
    holder, other = world["guests"][0], world["guests"][1]
    reservation = FX.hold_seats(
        api, world["ticket_class_id"], holder["id"], party_size=2
    )
    FX.cancel(api, reservation["id"], holder["id"])
    world["holder"] = holder
    world["other"] = other
    world["holder_headers"] = make_guest_headers(holder["id"])
    world["reservation_id"] = reservation["id"]
    world["table"] = FX.create_table(api, world["restaurant_id"])
    world["add_on"] = FX.create_add_on(api, world["restaurant_id"])
    return world


class TestCancelledReservationLockdown:
    """CANCELLED is terminal on the seating side, and nothing writes to it again."""

    def test_every_guest_side_write_is_refused_on_a_cancelled_reservation(self, api):
        """Confirm, pay, order, annotate, rename, transfer and re-cancel all fail.

        "The reservation's `fulfillment_status` permits the operation per the
        seating state machine, on confirm, payment, add-on append, dietary-note
        capture, table assignment, seating, completion, no-show declaration,
        cancellation, name change and transfer — otherwise
        `ERR_RESERVATION_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_cancelled_reservation_refuses_every_write
        """
        world = _cancelled_hold_world(api)
        reservation_id = world["reservation_id"]
        holder = world["holder_headers"]
        assert (
            FX.read_reservation(api, reservation_id, holder)["fulfillment_status"]
            == "CANCELLED"
        )
        # Read the version after the cancellation, so the add-on append carries
        # the live one and cannot be answered by the stale-view rejection.
        live_version = FX.reservation_version(api, reservation_id, holder)

        validate_error(
            api.confirm_reservation(reservation_id, holder),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.take_payment(reservation_id, F.payment_payload(5000), holder),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.append_add_on_line(
                reservation_id,
                F.add_on_line_payload(world["add_on"]["id"], live_version, qty=1),
                holder,
            ),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.create_dietary_note(
                reservation_id, F.dietary_note_payload(guest_index=1), holder
            ),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.change_name(reservation_id, F.name_change_payload("Someone Else"), holder),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.transfer_reservation(
                reservation_id, F.transfer_payload(world["other"]["id"]), holder
            ),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.cancel_reservation(reservation_id, holder),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )

    def test_every_floor_operation_is_refused_on_a_cancelled_reservation(self, api):
        """The state check answers before any timing or money check gets a turn.

        "The checks below are evaluated **in the order given**, and the first
        check that fails is the error the client sees." "`fulfillment_status` is
        the seating side, whose legal values are `PENDING`, `CONFIRMED`, `SEATED`,
        `COMPLETED`, `CANCELLED`, `NO_SHOW`, `TRANSFERRED_OUT` and `EXPIRED`,
        starting at `PENDING` and terminating at `COMPLETED`, `CANCELLED`,
        `NO_SHOW`, `TRANSFERRED_OUT` or `EXPIRED`."

        Design: Corner/state_machines/terminal_state_lockdown_cancelled_reservation_refuses_every_write
        """
        world = _cancelled_hold_world(api)
        reservation_id = world["reservation_id"]
        manager = world["manager_headers"]

        # The table assignment would otherwise be too early, the seating would be
        # ERR_SEATING_TOO_EARLY, the no-show ERR_NO_SHOW_TOO_EARLY and the
        # completion ERR_BALANCE_OUTSTANDING; the terminal state outranks all four.
        validate_error(
            api.assign_table(
                reservation_id,
                F.assign_table_payload(world["table"]["id"], SEATING_START),
                manager,
            ),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.seat_reservation(reservation_id, manager),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.declare_no_show(reservation_id, manager),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.complete_reservation(reservation_id, manager),
            ERR_RESERVATION_INVALID_STATE,
            409,
        )

    def test_none_of_the_refused_writes_left_a_trace(self, api):
        """The cancelled row, its ledger, its class and its successors all stand still.

        "`PENDING → CANCELLED` requires only that the reservation still be
        `PENDING`; it runs the settlement (which short-circuits to zero
        forfeiture), debits `party_size` from the class's `seats_held` and returns
        those seats to whichever pool they came from, and moves any linked
        `WaitlistEntry` to `WITHDRAWN`."

        Design: Corner/state_machines/terminal_state_lockdown_cancelled_reservation_refuses_every_write
        """
        world = _cancelled_hold_world(api)
        reservation_id = world["reservation_id"]
        holder = world["holder_headers"]
        manager = world["manager_headers"]

        # Fire the whole battery once more, then prove nothing at all moved.
        live_version = FX.reservation_version(api, reservation_id, holder)
        api.confirm_reservation(reservation_id, holder)
        api.take_payment(reservation_id, F.payment_payload(5000), holder)
        api.append_add_on_line(
            reservation_id,
            F.add_on_line_payload(world["add_on"]["id"], live_version, qty=1),
            holder,
        )
        api.create_dietary_note(
            reservation_id, F.dietary_note_payload(guest_index=1), holder
        )
        api.assign_table(
            reservation_id,
            F.assign_table_payload(world["table"]["id"], SEATING_START),
            manager,
        )
        api.transfer_reservation(
            reservation_id, F.transfer_payload(world["other"]["id"]), holder
        )

        frozen = FX.read_reservation(api, reservation_id, holder)
        A.assert_fulfillment_status(frozen, "CANCELLED")
        assert frozen["version"] == live_version
        assert frozen["assigned_table_id"] is None
        assert frozen["seat_from_utc"] is None
        assert frozen["name_change_count"] == 0
        assert frozen["add_on_total_cents"] == 0
        A.assert_money_breakdown(
            frozen, amount_paid=0, refunded=0, forfeited=0, goodwill_applied=0
        )

        assert FX.ledger_rows(api, reservation_id, holder) == []
        assert _row_count(api, {"reservation_id": reservation_id}, api.list_reservation_add_ons) == 0
        assert (
            _row_count(
                api,
                {"transferred_from_reservation_id": reservation_id},
                api.list_reservations,
            )
            == 0
        )

        restored = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            restored, sold=0, held=0, released=0, available=20, status="OPEN"
        )
