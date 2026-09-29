"""
Operations that are gated on the state of a different entity: a sale gated on
its owning service, a waitlist claim gated on its ticket class, a goodwill
credit gated on its refund exception, and a seating gated on a child dietary
note.

Every scenario below is built twice over: once with the other entity in the
wrong state, where the exact rejection is asserted, and once with that entity
moved into the state the rule demands, where the identical call goes through.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CARE_DECIDER_HEADERS,
    CARE_ISSUER_HEADERS,
    GUEST_SERVICES_DECIDER_ID,
    GUEST_SERVICES_ISSUER_ID,
    make_guest_headers,
    make_restaurant_headers,
)

# The instant every scenario pins its clock to before anything else happens.
SETUP_CLOCK = "2026-09-01T00:00:00Z"

# A Saturday seating, which carries the 12500-basis-point day-of-week factor.
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"

# Exactly 48 hours before the seating start.
CANCEL_AT_48H = "2026-09-10T22:00:00Z"
# The offer minted at CANCEL_AT_48H under offer_ttl_minutes of 15.
OFFER_EXPIRES_AT = "2026-09-10T22:15:00Z"
# Exactly 12 hours before the seating start.
CANCEL_AT_12H = "2026-09-12T10:00:00Z"

# A seating instant half an hour into the service window, so a kitchen
# acknowledgement can still land while the clock is before the seating start.
SEAT_FROM = "2026-09-12T22:30:00Z"
# That instant plus the service's turn_time_minutes of 150.
SEAT_TO = "2026-09-13T01:00:00Z"

# A Saturday HIGH cover off a 12000-cent base price: 12500 bp combined with
# 12000 bp clamps to 15000 bp, and 12000 cents carried through step three and a
# zero scarcity step is 18000 cents per cover.
LIST_PRICE_PER_COVER = 18000

CREDIT_EXPIRES_AT = "2027-01-01T00:00:00Z"


def _draft_service_world(api):
    """A Saturday HIGH service left in DRAFT, carrying one 20-seat OPEN class
    and a guest who has read that class's version.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725)
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        min_party_size=1,
        max_party_size=8,
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
    guest = FX.create_guest(api, display_name="Draft Guest")
    return {
        "restaurant_id": restaurant["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "service": service,
        "service_id": service["id"],
        "ticket_class_id": ticket_class["id"],
        "guest_id": guest["id"],
        "guest_headers": make_guest_headers(guest["id"]),
    }


class TestReservationCreateRequiresPublishedService:
    """A sale is refused two hops up the graph, at the owning service."""

    def test_draft_service_refuses_the_sale_although_the_class_is_open(self, api):
        """The class is OPEN with every seat free, and the sale still fails.

        "Before publication they cannot: a create against a `DRAFT`, `CLOSED` or
        `CANCELLED` service is refused with `ERR_SERVICE_NOT_PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/reservation_create_requires_published_service
        """
        world = _draft_service_world(api)
        assert world["service"]["status"] == "DRAFT"

        before = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        # Nothing about the class itself explains the refusal.
        A.assert_seat_pool(
            before, sold=0, held=0, released=0, available=20, status="OPEN"
        )

        response = api.create_reservation(
            F.reservation_payload(
                world["ticket_class_id"],
                world["guest_id"],
                before["version"],
                party_size=2,
                primary_guest_name="Draft Guest",
            ),
            world["guest_headers"],
        )
        validate_error(response, E.ERR_SERVICE_NOT_PUBLISHED, 409)

        after = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            after, sold=0, held=0, released=0, available=20, status="OPEN"
        )
        assert after["version"] == before["version"]

        rows, meta = validate_paginated(
            api.list_reservations(
                ADMIN_HEADERS, {"ticket_class_id": world["ticket_class_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_publishing_the_service_lets_the_same_sale_through(self, api):
        """The identical request succeeds once the owning service is PUBLISHED.

        "Publication re-evaluates every ticket class of the service against the
        seat-pool precedence ladder — a freshly allocated class with availability
        lands on `OPEN` — and from that instant reservations may be created
        against the service."

        Design: Difficulty/cross_entity_state_dependency/reservation_create_requires_published_service
        """
        world = _draft_service_world(api)
        stale_version = FX.ticket_class_version(
            api, world["ticket_class_id"], world["guest_headers"]
        )
        validate_error(
            api.create_reservation(
                F.reservation_payload(
                    world["ticket_class_id"],
                    world["guest_id"],
                    stale_version,
                    party_size=2,
                    primary_guest_name="Draft Guest",
                ),
                world["guest_headers"],
            ),
            E.ERR_SERVICE_NOT_PUBLISHED,
            409,
        )

        published = FX.publish_service(
            api, world["restaurant_id"], world["service_id"]
        )
        assert published["status"] == "PUBLISHED"

        version = FX.ticket_class_version(
            api, world["ticket_class_id"], world["guest_headers"]
        )
        reservation = validate_success(
            api.create_reservation(
                F.reservation_payload(
                    world["ticket_class_id"],
                    world["guest_id"],
                    version,
                    party_size=2,
                    primary_guest_name="Draft Guest",
                ),
                world["guest_headers"],
            ),
            201,
        )
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")
        assert reservation["service_id"] == world["service_id"]
        assert reservation["price_locked_per_cover_cents"] == LIST_PRICE_PER_COVER
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=36000,
            add_on_total=0,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=0,
        )

        after = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            after, sold=0, held=2, released=0, available=18, status="OPEN"
        )


def _offered_entry_world(api, *, seats_allocated, holder_party_size):
    """A published Saturday HIGH service whose single class was exhausted by one
    confirmed booking and then freed by that booking's cancellation, promoting
    the one waiting entry to OFFERED with a live offer.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        offer_ttl_minutes=15,
        hold_ttl_minutes=20,
        max_offer_rounds=2,
    )
    manager = make_restaurant_headers(restaurant["id"])
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        min_party_size=1,
        max_party_size=8,
    )
    table = FX.create_table(api, restaurant["id"], seats_min=1, seats_max=8)
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=seats_allocated,
        demand_tier="HIGH",
        waitlist_policy="YIELD_WEIGHTED",
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=seats_allocated,
        min_party_size=1,
        max_party_size=holder_party_size,
    )
    FX.publish_service(api, restaurant["id"], service["id"])

    holder = FX.create_guest(api, display_name="Offer Holder")
    waiter = FX.create_guest(api, display_name="Offer Waiter")
    held = FX.confirmed_reservation(
        api, ticket_class["id"], holder["id"], party_size=holder_party_size
    )
    # A seating instant is pinned so the cancellation window comparison is
    # unambiguous when the booking is dropped 48 hours out.
    FX.assign_table(api, restaurant["id"], held["id"], table["id"], SEATING_START)
    entry = FX.join_waitlist(api, service["id"], waiter["id"], party_size=2)

    FX.set_clock(api, CANCEL_AT_48H)
    FX.cancel(api, held["id"], holder["id"])

    waiter_headers = make_guest_headers(waiter["id"])
    offered = FX.read_waitlist_entry(api, entry["id"], waiter_headers)
    return {
        "restaurant_id": restaurant["id"],
        "manager": manager,
        "ticket_class_id": ticket_class["id"],
        "waiter_id": waiter["id"],
        "waiter_headers": waiter_headers,
        "entry_id": entry["id"],
        "offered": offered,
    }


class TestWaitlistClaimRequiresSellableTicketClass:
    """A live, unexpired offer is still worthless if its class stops selling."""

    def test_paused_class_refuses_the_claim_on_a_live_offer(self, api):
        """The offer has not lapsed; the class alone blocks the claim.

        "A `PAUSED` class refuses the claim with `ERR_TICKET_CLASS_NOT_SELLABLE`;
        `SOLD_OUT` is deliberately claimable, because the offer's own hold is
        what exhausted the pool in the first place and refusing it would make the
        offer worthless."

        Design: Difficulty/cross_entity_state_dependency/waitlist_claim_requires_sellable_ticket_class
        """
        world = _offered_entry_world(api, seats_allocated=4, holder_party_size=4)
        offered = world["offered"]
        assert offered["status"] == "OFFERED"
        assert offered["offered_reservation_id"] is not None
        # The offer is still live: the clock sits 15 minutes before it lapses.
        A.assert_instant_equals(offered["offer_expires_at_utc"], OFFER_EXPIRES_AT, "offer_expires_at_utc")

        paused = validate_success(
            api.pause_ticket_class(world["ticket_class_id"], world["manager"]), 200
        )
        A.assert_seat_pool(
            paused, sold=0, held=2, released=0, available=2, status="PAUSED"
        )

        response = api.claim_waitlist_entry(
            world["entry_id"], world["waiter_headers"]
        )
        validate_error(response, E.ERR_TICKET_CLASS_NOT_SELLABLE, 409)

        after = FX.read_waitlist_entry(
            api, world["entry_id"], world["waiter_headers"]
        )
        assert after["status"] == "OFFERED"
        A.assert_instant_equals(after["offer_expires_at_utc"], OFFER_EXPIRES_AT, "offer_expires_at_utc")
        assert after["offered_reservation_id"] == offered["offered_reservation_id"]

        reservation = FX.read_reservation(
            api, offered["offered_reservation_id"], world["waiter_headers"]
        )
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")

        unchanged = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            unchanged, sold=0, held=2, released=0, available=2, status="PAUSED"
        )

    def test_resuming_the_class_lets_the_same_claim_through(self, api):
        """The class returns to OPEN and the previously refused claim lands.

        "Resuming writes no seat counter of its own; it simply lets the ladder run
        again, and the class lands on exactly one of three states according to the
        pools as they stand at that moment." "When `seats_released` is 0 and
        `seats_available` is above 0 it takes `PAUSED → OPEN`."

        Design: Difficulty/cross_entity_state_dependency/waitlist_claim_requires_sellable_ticket_class
        """
        world = _offered_entry_world(api, seats_allocated=4, holder_party_size=4)
        offered_reservation_id = world["offered"]["offered_reservation_id"]

        validate_success(
            api.pause_ticket_class(world["ticket_class_id"], world["manager"]), 200
        )
        validate_error(
            api.claim_waitlist_entry(world["entry_id"], world["waiter_headers"]),
            E.ERR_TICKET_CLASS_NOT_SELLABLE,
            409,
        )

        resumed = validate_success(
            api.resume_ticket_class(world["ticket_class_id"], world["manager"]), 200
        )
        A.assert_seat_pool(
            resumed, sold=0, held=2, released=0, available=2, status="OPEN"
        )

        claimed = validate_success(
            api.claim_waitlist_entry(world["entry_id"], world["waiter_headers"]), 200
        )
        assert claimed["status"] == "CLAIMED"
        assert claimed["offer_expires_at_utc"] is None
        assert claimed["offered_reservation_id"] == offered_reservation_id

        # Claiming secures the offer without paying for it.
        reservation = FX.read_reservation(
            api, offered_reservation_id, world["waiter_headers"]
        )
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")
        assert reservation["is_release_priced"] is False
        assert reservation["price_locked_per_cover_cents"] == LIST_PRICE_PER_COVER

        after = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            after, sold=0, held=2, released=0, available=2, status="OPEN"
        )

    def test_sold_out_class_still_permits_the_claim_it_caused(self, api):
        """The state that blocks a direct sale does not block this claim.

        "It requires the entry to be `OFFERED`, the logical clock to be strictly
        before `offer_expires_at_utc` — otherwise `ERR_OFFER_EXPIRED` — the
        offered reservation to still be `PENDING`, and the offered reservation's
        ticket class to be in `OPEN`, `RELEASED` or `SOLD_OUT`."

        Design: Difficulty/cross_entity_state_dependency/waitlist_claim_requires_sellable_ticket_class
        """
        world = _offered_entry_world(api, seats_allocated=2, holder_party_size=2)
        offered_reservation_id = world["offered"]["offered_reservation_id"]

        # The promotion's own hold is what emptied the pool.
        before = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            before, sold=0, held=2, released=0, available=0, status="SOLD_OUT"
        )

        claimed = validate_success(
            api.claim_waitlist_entry(world["entry_id"], world["waiter_headers"]), 200
        )
        assert claimed["status"] == "CLAIMED"
        assert claimed["offer_expires_at_utc"] is None

        reservation = FX.read_reservation(
            api, offered_reservation_id, world["waiter_headers"]
        )
        A.assert_fulfillment_status(reservation, "PENDING")

        after = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            after, sold=0, held=2, released=0, available=0, status="SOLD_OUT"
        )


def _filed_exception_world(api):
    """A party of two whose deposit was wholly forfeited 12 hours out, carrying a
    freshly filed refund exception that nobody has adjudicated yet.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        goodwill_credit_cap_cents=20000,
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
    table = FX.create_table(api, restaurant["id"], seats_min=1, seats_max=8)
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
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest = FX.create_guest(api, display_name="Contesting Guest")
    guest_headers = make_guest_headers(guest["id"])

    reservation = FX.confirmed_reservation(
        api, ticket_class["id"], guest["id"], party_size=2
    )
    FX.assign_table(
        api, restaurant["id"], reservation["id"], table["id"], SEATING_START
    )
    FX.set_clock(api, CANCEL_AT_12H)
    FX.cancel(api, reservation["id"], guest["id"])
    settled = FX.read_reservation(api, reservation["id"], guest_headers)

    # The guest files for 6000 of the 11583 the restaurant retained.
    exception = FX.file_refund_exception(
        api,
        reservation["id"],
        6000,
        headers=guest_headers,
        reason_code="KITCHEN_ERROR",
    )
    return {
        "restaurant_id": restaurant["id"],
        "guest_id": guest["id"],
        "guest_headers": guest_headers,
        "reservation_id": reservation["id"],
        "settled": settled,
        "exception": exception,
    }


class TestGoodwillCreditRequiresApprovedException:
    """The credit's right to exist, and its ceiling, both live on the exception."""

    def test_credit_is_refused_while_the_exception_is_still_requested(self, api):
        """An undecided exception blocks issuance outright.

        "The refund exception is `APPROVED` before a compensating credit may be
        issued — otherwise `ERR_REFUND_EXCEPTION_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/goodwill_credit_requires_approved_exception
        """
        world = _filed_exception_world(api)
        exception = world["exception"]
        assert exception["status"] == "REQUESTED"
        assert exception["requested_cents"] == 6000
        assert exception["approved_cents"] == 0
        assert exception["shortfall_cents"] == 0
        assert exception["decided_by_user_id"] is None

        # The settlement it contests forfeited the whole deposit.
        A.assert_money_breakdown(
            world["settled"], amount_paid=11583, refunded=0, forfeited=11583
        )
        A.assert_payment_status(world["settled"], "FORFEITED")

        response = api.create_goodwill_credit(
            F.goodwill_credit_payload(exception["id"], 3000, CREDIT_EXPIRES_AT),
            CARE_ISSUER_HEADERS,
        )
        validate_error(response, E.ERR_REFUND_EXCEPTION_NOT_APPROVED, 409)

        rows, meta = validate_paginated(
            api.list_goodwill_credits(
                ADMIN_HEADERS, {"refund_exception_id": exception["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        # Nothing about the contested settlement moved either.
        unchanged = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_money_breakdown(unchanged, refunded=0, forfeited=11583)
        A.assert_payment_status(unchanged, "FORFEITED")

    def test_approving_the_exception_lets_the_same_credit_be_issued(self, api):
        """Approval opens the shortfall the credit is allowed to fill.

        "On approval, `approved_cents` and `decision_note_code` are stored and
        `shortfall_cents` is derived as `requested_cents` less `approved_cents`."

        Design: Difficulty/cross_entity_state_dependency/goodwill_credit_requires_approved_exception
        """
        world = _filed_exception_world(api)
        exception_id = world["exception"]["id"]
        validate_error(
            api.create_goodwill_credit(
                F.goodwill_credit_payload(exception_id, 3000, CREDIT_EXPIRES_AT),
                CARE_ISSUER_HEADERS,
            ),
            E.ERR_REFUND_EXCEPTION_NOT_APPROVED,
            409,
        )

        decided = FX.decide_refund_exception(
            api,
            exception_id,
            decision="APPROVED",
            approved_cents=3000,
            decision_note_code="PARTIAL_GOODWILL",
            headers=CARE_DECIDER_HEADERS,
        )
        assert decided["status"] == "APPROVED"
        assert decided["approved_cents"] == 3000
        assert decided["shortfall_cents"] == 3000
        assert decided["decided_by_user_id"] == GUEST_SERVICES_DECIDER_ID

        # The approval reopened the terminal money state on the reservation.
        reopened = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_money_breakdown(
            reopened, amount_paid=11583, refunded=3000, forfeited=8583
        )
        A.assert_payment_status(reopened, "PARTIALLY_REFUNDED")
        A.assert_settled_ledger_identity(reopened)

        credit = validate_success(
            api.create_goodwill_credit(
                F.goodwill_credit_payload(exception_id, 3000, CREDIT_EXPIRES_AT),
                CARE_ISSUER_HEADERS,
            ),
            201,
        )
        A.assert_common_fields(credit)
        assert credit["refund_exception_id"] == exception_id
        assert credit["issued_cents"] == 3000
        assert credit["remaining_cents"] == 3000
        assert credit["redeemed_cents"] == 0
        assert credit["revoked_cents"] == 0
        A.assert_credit_status(credit)
        assert credit["status"] == "ISSUED"
        # The credit is scoped by copying down from the exception's reservation.
        assert credit["guest_id"] == world["guest_id"]
        assert credit["restaurant_id"] == world["restaurant_id"]
        assert credit["issued_by_user_id"] == GUEST_SERVICES_ISSUER_ID
        assert credit["issued_by_user_id"] != decided["decided_by_user_id"]

    def test_the_exception_shortfall_and_not_the_house_cap_bounds_the_credit(
        self, api
    ):
        """One cent above the approved shortfall fails; the shortfall itself passes.

        "The `issued_cents` must be at least 1 and may not exceed the **smaller**
        of the restaurant's `goodwill_credit_cap_cents` and the exception's
        `shortfall_cents`; exceeding either is refused with
        `ERR_GOODWILL_EXCEEDS_CAP`."

        Design: Difficulty/cross_entity_state_dependency/goodwill_credit_requires_approved_exception
        """
        world = _filed_exception_world(api)
        exception_id = world["exception"]["id"]
        decided = FX.decide_refund_exception(
            api,
            exception_id,
            decision="APPROVED",
            approved_cents=3000,
            decision_note_code="PARTIAL_GOODWILL",
            headers=CARE_DECIDER_HEADERS,
        )
        assert decided["shortfall_cents"] == 3000

        # 3001 sits far below the restaurant's 20000-cent cap, so only the
        # exception's shortfall can be refusing it.
        validate_error(
            api.create_goodwill_credit(
                F.goodwill_credit_payload(exception_id, 3001, CREDIT_EXPIRES_AT),
                CARE_ISSUER_HEADERS,
            ),
            E.ERR_GOODWILL_EXCEEDS_CAP,
            402,
        )
        rows, meta = validate_paginated(
            api.list_goodwill_credits(
                ADMIN_HEADERS, {"refund_exception_id": exception_id}
            )
        )
        assert meta["total_count"] == 0

        credit = validate_success(
            api.create_goodwill_credit(
                F.goodwill_credit_payload(exception_id, 3000, CREDIT_EXPIRES_AT),
                CARE_ISSUER_HEADERS,
            ),
            201,
        )
        assert credit["issued_cents"] == 3000
        A.assert_instant_equals(credit["expires_at_utc"], CREDIT_EXPIRES_AT, "expires_at_utc")
        A.assert_credit_status(credit)


def _pending_anaphylaxis_world(api):
    """A CONFIRMED party of two with a table and a seating instant already
    pinned, carrying one still-pending ANAPHYLAXIS note for cover 1.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api, service_charge_bp=725, prep_lead_minutes=45, no_show_grace_minutes=30
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        kitchen_prep_minutes_per_cover=12,
    )
    table = FX.create_table(
        api, restaurant["id"], seats_min=1, seats_max=8, turn_buffer_minutes=15
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
        kitchen_prep_capacity_minutes=600,
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest = FX.create_guest(api, display_name="Allergy Guest")
    reservation = FX.confirmed_reservation(
        api, ticket_class["id"], guest["id"], party_size=2
    )
    # The table is assigned while the party carries no note at all, so the
    # safety gate has nothing to catch yet.
    FX.assign_table(api, restaurant["id"], reservation["id"], table["id"], SEAT_FROM)
    note = FX.add_dietary_note(
        api,
        reservation["id"],
        guest["id"],
        guest_index=1,
        severity="ANAPHYLAXIS",
        restriction_code="SHELLFISH",
        note_text="Airborne shellfish risk.",
    )
    return {
        "restaurant_id": restaurant["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "guest_id": guest["id"],
        "guest_headers": make_guest_headers(guest["id"]),
        "table_id": table["id"],
        "reservation_id": reservation["id"],
        "note_id": note["id"],
        "note": note,
    }


class TestSeatingRequiresAckedAnaphylaxisNote:
    """The party may not sit down until the kitchen has answered for it."""

    def test_pending_anaphylaxis_note_refuses_the_seating(self, api):
        """Everything else about the seating is in order, and it still fails.

        "First, every note on the reservation whose `severity` is `ANAPHYLAXIS`
        must have reached `ack_status` `ACKED`; a single still-pending anaphylaxis
        note refuses both operations with `ERR_DIETARY_ACK_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/seating_requires_acked_anaphylaxis_note
        """
        world = _pending_anaphylaxis_world(api)
        assert world["note"]["ack_status"] == "PENDING"
        assert world["note"]["severity"] == "ANAPHYLAXIS"

        before = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(before, "CONFIRMED")
        assert before["assigned_table_id"] == world["table_id"]
        A.assert_instant_equals(before["seat_from_utc"], SEAT_FROM, "seat_from_utc")
        # The pending note already costs the kitchen its severity minutes.
        assert before["prep_minutes_total"] == 39

        # The clock has reached the pinned seating instant, so nothing about the
        # schedule can be the reason for the refusal.
        FX.set_clock(api, SEAT_FROM)
        response = api.seat_reservation(world["reservation_id"], world["manager"])
        validate_error(response, E.ERR_DIETARY_ACK_REQUIRED, 422)

        after = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(after, "CONFIRMED")
        A.assert_payment_status(after, "DEPOSIT_PAID")
        assert after["seat_to_utc"] is None
        assert after["version"] == before["version"]

        note = FX.read_note(api, world["note_id"], world["guest_headers"])
        assert note["ack_status"] == "PENDING"
        assert note["acked_by_user_id"] is None

    def test_acknowledging_the_note_lets_the_seating_through(self, api):
        """Once the kitchen accepts the note the same seating call succeeds.

        "Accepting moves the note `PENDING → ACKED` and requires three things: the
        note is still `PENDING`, the owning reservation's seating dimension reads
        `CONFIRMED`, and the logical clock is strictly before the service's
        `seating_start_utc`." "Seating pins `seat_to_utc` to `seat_from_utc` plus
        the service's `turn_time_minutes`; until the party is seated, `seat_to_utc`
        is null."

        Design: Difficulty/cross_entity_state_dependency/seating_requires_acked_anaphylaxis_note
        """
        world = _pending_anaphylaxis_world(api)

        # The clock is still 2026-09-01, strictly before the seating start.
        acked = FX.ack_note(api, world["restaurant_id"], world["note_id"])
        assert acked["ack_status"] == "ACKED"
        assert acked["acked_by_user_id"] == world["restaurant_id"]

        before = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        assert before["seat_to_utc"] is None
        assert before["prep_minutes_total"] == 39

        FX.set_clock(api, SEAT_FROM)
        seated = validate_success(
            api.seat_reservation(world["reservation_id"], world["manager"]), 200
        )
        A.assert_fulfillment_status(seated, "SEATED")
        A.assert_instant_equals(seated["seat_from_utc"], SEAT_FROM, "seat_from_utc")
        A.assert_instant_equals(seated["seat_to_utc"], SEAT_TO, "seat_to_utc")
        A.assert_version_advanced_by(seated["version"], before["version"], 1)

        # Seating moves the seating dimension only.
        A.assert_payment_status(seated, "DEPOSIT_PAID")
        A.assert_money_breakdown(
            seated,
            ticket_subtotal=36000,
            add_on_total=0,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=11583,
        )
        assert seated["prep_minutes_total"] == 39
