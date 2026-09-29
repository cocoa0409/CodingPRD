"""
Requests that break several rules at once, and the single rejection each one is
required to answer with.

The order in which a request is refused is pinned, so every scenario below
stages a later violation alongside an earlier one and asserts the earlier code
and its exact HTTP status. Where a losing rule can be isolated by clearing the
winner, the control request is asserted too, and every refusal is followed by a
read proving that nothing was committed.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import (
    ERR_FORBIDDEN_RESOURCE_OWNER,
    ERR_GOODWILL_CREDIT_EXPIRED,
    ERR_GOODWILL_EXCEEDS_BALANCE_DUE,
    ERR_GOODWILL_REDEMPTION_EXCEEDS_REMAINING,
    ERR_GOODWILL_TARGET_MISMATCH,
    ERR_MISSING_AUTH_HEADERS,
    ERR_ONWARD_TRANSFER_FORBIDDEN,
    ERR_RESALE_SUSPECTED,
    ERR_STALE_GOODWILL_CREDIT_VERSION,
    ERR_STALE_RESERVATION_VERSION,
    ERR_STALE_TICKET_CLASS_VERSION,
    ERR_TICKET_CLASS_NOT_SELLABLE,
    ERR_TRANSFER_CUTOFF_PASSED,
    ERR_TRANSFER_LIMIT_REACHED,
    ERR_TRANSFER_REQUIRES_FULL_PAYMENT,
    ERR_TRANSFER_TO_SELF,
    ERR_UNAUTHORIZED,
    ERR_UNKNOWN_ROLE,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    headers_with_blank,
    headers_without,
    make_care_headers,
    make_guest_headers,
    make_headers,
    make_kitchen_headers,
    make_restaurant_headers,
)

# The instant every scenario pins its clock to before anything else happens.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
# The Thursday every service below seats. Thursday carries the 10000
# basis-point day-of-week factor and STANDARD carries 10000, so a 12000-cent
# cover prices at 12000 cents: two covers are 24000, the 7.25 percent service
# charge is 1740, the grand total 25740 and thirty percent down is 7722.
SEATING_START = "2026-09-10T22:00:00Z"
SEATING_END = "2026-09-11T02:00:00Z"
GRAND_TOTAL = 25740
DEPOSIT_DUE = 7722

# A well-formed identifier that no row in an empty database was ever minted
# with, used where a request must be refused before existence is consulted.
_ABSENT_ID = "00000000-0000-0000-0000-000000000000"


def _catalogue_world(api):
    """One restaurant carrying exactly one experience package.

    A legitimate caller would have something real to act on here, which is what
    makes the refusals below attributable to the caller rather than to an empty
    database.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725)
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Corner Tasting Menu",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
    )
    return {
        "restaurant": restaurant,
        "restaurant_id": restaurant["id"],
        "package": package,
        "manager": make_restaurant_headers(restaurant["id"]),
        "kitchen": make_kitchen_headers(restaurant["id"]),
    }


class TestAuthenticationAndAuthorizationAnswerFirst:
    """The first three rungs, each staged against a later violation."""

    def test_absent_or_empty_identity_beats_the_not_found_row(self, api):
        """A caller the server cannot identify never learns the id was bogus.

        "If either header is absent or present but empty, the request is
        rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else
        about the request is inspected." And "If both headers are present but
        `X-User-Role` is not one of the five recognised role names, the
        rejection is `ERR_UNKNOWN_ROLE`, also HTTP 401."

        Design: Corner/validations/auth_ladder_missing_auth_headers_unknown_role_then_unauthorized
        """
        _catalogue_world(api)

        # Nothing identifies the caller, and the path id names no row either.
        validate_error(
            api.get_restaurant(_ABSENT_ID, {}), ERR_MISSING_AUTH_HEADERS, 401
        )
        # One header alone is not identity.
        validate_error(
            api.get_restaurant(
                _ABSENT_ID, headers_without(ADMIN_HEADERS, "X-User-Role")
            ),
            ERR_MISSING_AUTH_HEADERS,
            401,
        )
        # Present but empty counts as absent.
        validate_error(
            api.get_restaurant(
                _ABSENT_ID, headers_with_blank(ADMIN_HEADERS, "X-User-ID")
            ),
            ERR_MISSING_AUTH_HEADERS,
            401,
        )
        # Both headers present, but the capacity is not one of the five.
        validate_error(
            api.get_restaurant(_ABSENT_ID, make_headers("someone-else", "Sommelier")),
            ERR_UNKNOWN_ROLE,
            401,
        )

    def test_a_role_outside_the_endpoints_list_beats_the_body_shape_row(self, api):
        """A wrong capacity is refused before the payload is ever read.

        "If the acting role is not among the roles listed for the endpoint being
        called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)." And "A
        `KitchenLead` is the back-of-house lead whose only write authority is
        acknowledging or prep-rejecting dietary notes."

        Design: Corner/validations/auth_ladder_missing_auth_headers_unknown_role_then_unauthorized
        """
        world = _catalogue_world(api)
        diner = FX.create_guest(api, display_name="Curious Diner")

        # Creating a service belongs to the RestaurantManager alone, and this
        # body would not survive shape validation either: the date is not a
        # date and BRUNCH is not a meal period.
        rejected_service = api.create_service(
            F.service_payload(
                world["restaurant_id"],
                service_date="not-a-date",
                meal_period="BRUNCH",
            ),
            make_guest_headers(diner["id"]),
        )
        validate_error(rejected_service, ERR_UNAUTHORIZED, 403)

        # The back-of-house lead cannot price anything, catalogue included.
        rejected_package = api.create_package(
            F.package_payload(world["restaurant_id"], name="Sneaky Menu"),
            world["kitchen"],
        )
        validate_error(rejected_package, ERR_UNAUTHORIZED, 403)

        # Neither refusal wrote a row.
        services, _meta = validate_paginated(
            api.list_restaurant_services(
                world["restaurant_id"], world["manager"], {"limit": 100}
            )
        )
        assert services == []
        packages, _meta = validate_paginated(
            api.list_restaurant_packages(
                world["restaurant_id"], world["manager"], {"limit": 100}
            )
        )
        assert [row["id"] for row in packages] == [world["package"]["id"]]


def _two_house_world(api):
    """Two restaurants, a published service and a 20-seat class at the first,
    and two guests of whom only the first holds a ticket carrying a note.

    Everything the second restaurant and the second guest would need to act
    legitimately exists — their own package, their own headers — so the only
    thing wrong with the requests below is who is making them.
    """
    FX.set_clock(api, SETUP_CLOCK)
    house_one = FX.create_restaurant(api, service_charge_bp=725)
    house_two = FX.create_restaurant(api, service_charge_bp=725)
    package_one = FX.create_package(
        api,
        house_one["id"],
        name="House One Tasting",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
    )
    package_two = FX.create_package(
        api,
        house_two["id"],
        name="House Two Tasting",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
    )
    service = FX.create_service(
        api,
        house_one["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        seats_capacity=20,
        demand_tier="STANDARD",
    )
    ticket_class = FX.create_ticket_class(
        api, house_one["id"], service["id"], package_one["id"], seats_allocated=20
    )
    FX.publish_service(api, house_one["id"], service["id"])
    holder = FX.create_guest(api, display_name="Holder Guest A")
    stranger = FX.create_guest(api, display_name="Stranger Guest B")
    reservation = FX.hold_seats(
        api,
        ticket_class["id"],
        holder["id"],
        party_size=2,
        primary_guest_name="Holder Guest A",
    )
    note = FX.add_dietary_note(
        api,
        reservation["id"],
        holder["id"],
        guest_index=1,
        severity="ALLERGY",
        restriction_code="NUT",
    )
    return {
        "house_one": house_one,
        "house_two": house_two,
        "package_two": package_two,
        "service": service,
        "ticket_class": ticket_class,
        "holder": holder,
        "stranger": stranger,
        "reservation": reservation,
        "note": note,
        "manager_one": make_restaurant_headers(house_one["id"]),
        "kitchen_one": make_kitchen_headers(house_one["id"]),
        "manager_two": make_restaurant_headers(house_two["id"]),
        "kitchen_two": make_kitchen_headers(house_two["id"]),
    }


class TestOwnershipIsComparedAgainstTheTarget:
    """Ownership answers before existence, shape, state or capacity do."""

    def test_a_second_guest_can_neither_read_nor_confirm_another_guests_ticket(
        self, api
    ):
        """The wrong guest is turned away; the right one still gets the row.

        "An entity-backed role acting on a resource it does not own is rejected
        with `ERR_FORBIDDEN_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/forbidden_resource_owner_guest_cannot_read_another_guests_reservation
        """
        world = _two_house_world(api)
        stranger = make_guest_headers(world["stranger"]["id"])
        holder = make_guest_headers(world["holder"]["id"])
        reservation_id = world["reservation"]["id"]

        # A plain read of someone else's booking.
        validate_error(
            api.get_reservation(reservation_id, stranger),
            ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )
        # A write the real holder could not make either — nothing is paid yet —
        # but ownership is compared long before the deposit is looked at.
        validate_error(
            api.confirm_reservation(reservation_id, stranger),
            ERR_FORBIDDEN_RESOURCE_OWNER,
            403,
        )

        # The booking is untouched, and its own holder reads it perfectly well.
        mine = get_success_data(api.get_reservation(reservation_id, holder), 200)
        assert mine["id"] == reservation_id
        assert mine["guest_id"] == world["holder"]["id"]
        A.assert_fulfillment_status(mine, "PENDING")
        A.assert_payment_status(mine, "UNPAID")

    def test_a_rival_house_can_neither_allocate_seats_nor_acknowledge_notes(self, api):
        """The restaurant-scoped comparison covers classes and notes alike.

        "When `X-User-Role` is `KitchenLead`, `X-User-ID` is likewise the `id`
        of the acting `Restaurant`, and the same restaurant-ownership comparison
        applies to the dietary notes and reservations the lead may read or
        acknowledge."

        Design: Corner/validations/forbidden_resource_owner_guest_cannot_read_another_guests_reservation
        """
        world = _two_house_world(api)

        # The rival offers its own package against a service it does not own:
        # the package would also be out of scope for that service.
        rejected_class = api.create_ticket_class(
            F.ticket_class_payload(
                world["service"]["id"], world["package_two"]["id"], seats_allocated=1
            ),
            world["manager_two"],
        )
        validate_error(rejected_class, ERR_FORBIDDEN_RESOURCE_OWNER, 403)

        # The rival's kitchen tries to clear a note it has never been shown.
        rejected_ack = api.ack_dietary_note(
            world["note"]["id"], F.ack_payload("ACCEPT"), world["kitchen_two"]
        )
        validate_error(rejected_ack, ERR_FORBIDDEN_RESOURCE_OWNER, 403)

        # Neither refusal left a trace.
        note = FX.read_note(api, world["note"]["id"], world["kitchen_one"])
        assert note["ack_status"] == "PENDING"
        classes, _meta = validate_paginated(
            api.list_ticket_classes(
                world["manager_one"],
                {"service_id": world["service"]["id"], "limit": 100},
            )
        )
        assert [row["id"] for row in classes] == [world["ticket_class"]["id"]]


def _version_race_world(api):
    """A published class two guests both hold a view of, plus a cheap add-on.

    The add-on is priced at 100 cents and costs 4 kitchen minutes a unit, small
    enough that the reservation totals stay easy to read after a line lands.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725)
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Version Race Tasting",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        kitchen_prep_minutes_per_cover=12,
    )
    add_on = FX.create_add_on(
        api,
        restaurant["id"],
        name="Corkage",
        price_cents=100,
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=1440,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        seats_capacity=20,
        demand_tier="STANDARD",
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest_a = FX.create_guest(api, display_name="Racing Guest A")
    guest_b = FX.create_guest(api, display_name="Racing Guest B")
    return {
        "restaurant": restaurant,
        "add_on": add_on,
        "service": service,
        "ticket_class": ticket_class,
        "guest_a": guest_a,
        "guest_b": guest_b,
        "manager": make_restaurant_headers(restaurant["id"]),
    }


def _reserve_echoing(api, ticket_class_id, guest_id, echoed_version, party_size=2):
    """Attempt a reservation echoing a caller-chosen class version."""
    headers = make_guest_headers(guest_id)
    payload = F.reservation_payload(
        ticket_class_id,
        guest_id,
        echoed_version,
        party_size=party_size,
        primary_guest_name="Racing Party",
    )
    return api.create_reservation(payload, headers)


class TestStaleViewsAnswerBeforeBusinessState:
    """A refreshed view is demanded before the state of the parent matters."""

    def test_a_stale_class_version_beats_the_paused_class(self, api):
        """The version check fires even though the class is also unsellable.

        "`expected_ticket_class_version` equals the ticket class's current
        `version`, on reservation creation — otherwise
        `ERR_STALE_TICKET_CLASS_VERSION`." Only later does the ladder ask that
        "The ticket class is sellable: `OPEN` or `RELEASED` for a direct
        reservation, and `OPEN`, `RELEASED` or `SOLD_OUT` for a waitlist claim,
        with `PAUSED` and `CLOSED` always failing — on reservation creation and
        waitlist claim — otherwise `ERR_TICKET_CLASS_NOT_SELLABLE`."

        Design: Corner/validations/priority_ordering_stale_versions_returns_412_before_business_state
        """
        world = _version_race_world(api)
        class_id = world["ticket_class"]["id"]
        observed = FX.ticket_class_version(api, class_id, world["manager"])

        # The other guest gets in first, which advances the class version.
        first = _reserve_echoing(api, class_id, world["guest_b"]["id"], observed)
        get_success_data(first, 201)
        after_sale = FX.ticket_class_version(api, class_id, world["manager"])
        A.assert_version_advanced_by(after_sale, observed, 1)

        # And then the house suspends sales altogether.
        get_success_data(api.pause_ticket_class(class_id, world["manager"]), 200)
        paused = FX.read_ticket_class(api, class_id, world["manager"])
        assert paused["status"] == "PAUSED"
        assert paused["version"] != observed

        # Two rules are now broken at once, and the earlier one answers.
        stale = _reserve_echoing(api, class_id, world["guest_a"]["id"], observed)
        validate_error(stale, ERR_STALE_TICKET_CLASS_VERSION, 412)

        # Refreshing the view isolates the rule that lost.
        unsellable = _reserve_echoing(
            api, class_id, world["guest_a"]["id"], paused["version"]
        )
        validate_error(unsellable, ERR_TICKET_CLASS_NOT_SELLABLE, 409)

        # Neither refusal moved a seat: only the first sale's two are held, and
        # suspending sales released nothing of its own.
        after_refusals = FX.read_ticket_class(api, class_id, world["manager"])
        A.assert_seat_pool(
            after_refusals, sold=0, held=2, released=0, available=18, status="PAUSED"
        )

        # With sales resumed and the current version echoed, the same request
        # that failed twice succeeds.
        get_success_data(api.resume_ticket_class(class_id, world["manager"]), 200)
        live = FX.ticket_class_version(api, class_id, world["manager"])
        accepted = get_success_data(
            _reserve_echoing(api, class_id, world["guest_a"]["id"], live), 201
        )
        assert accepted["guest_id"] == world["guest_a"]["id"]
        reread = FX.read_ticket_class(api, class_id, world["manager"])
        A.assert_seat_pool(
            reread, sold=0, held=4, released=0, available=16, status="OPEN"
        )

    def test_a_replayed_reservation_version_appends_no_second_line(self, api):
        """The first append advances the version, so replaying it is refused.

        "A mismatch with the reservation's current `version` is rejected with
        `ERR_STALE_RESERVATION_VERSION` (HTTP 412)."

        Design: Corner/validations/priority_ordering_stale_versions_returns_412_before_business_state
        """
        world = _version_race_world(api)
        guest_id = world["guest_a"]["id"]
        headers = make_guest_headers(guest_id)
        reservation = FX.confirmed_reservation(
            api, world["ticket_class"]["id"], guest_id, party_size=2
        )
        observed = FX.reservation_version(api, reservation["id"], headers)

        # The first append is legitimate and advances the version by one.
        first = get_success_data(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(world["add_on"]["id"], observed, qty=1),
                headers,
            ),
            201,
        )
        assert first["qty"] == 1
        assert first["unit_price_cents_locked"] == 100
        assert first["line_prep_minutes"] == 4
        after = FX.reservation_version(api, reservation["id"], headers)
        A.assert_version_advanced_by(after, observed, 1)

        # Replaying the same body is not a second legitimate append: nothing in
        # the quantity ceiling would have stopped it, only the stale view does.
        replay = api.append_add_on_line(
            reservation["id"],
            F.add_on_line_payload(world["add_on"]["id"], observed, qty=1),
            headers,
        )
        validate_error(replay, ERR_STALE_RESERVATION_VERSION, 412)

        lines, _meta = validate_paginated(
            api.list_reservation_add_ons(
                headers, {"reservation_id": reservation["id"], "limit": 100}
            )
        )
        assert [row["id"] for row in lines] == [first["id"]]

        # One line's worth of money and minutes, not two: 24 baseline minutes
        # for two covers plus the single unit's 4.
        settled = FX.read_reservation(api, reservation["id"], headers)
        assert settled["add_on_total_cents"] == 100
        assert settled["prep_minutes_total"] == 28
        assert settled["version"] == after


# The cancellation instant for the settled booking the credit compensates:
# exactly 48 hours before seating, which the STANDARD ladder retains half of.
CANCEL_AT_48H = "2026-09-08T22:00:00Z"
# Two hours after that cancellation, and therefore a valid expiry at issue time.
CREDIT_EXPIRES_AT = "2026-09-09T00:00:00Z"
CREDIT_FACE_VALUE = 3361


def _goodwill_world(api):
    """A live goodwill credit, the booking it may be spent on, and a stranger's
    booking it may not.

    The chain is the whole compensation channel: a deposit-paid Thursday
    booking cancelled at 48 hours retains 4361 cents and refunds 3361, the
    guest asks for the retention back, one operator approves 1000 of it and a
    second issues the 3361-cent shortfall as credit.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api, service_charge_bp=725, goodwill_credit_cap_cents=20000
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Goodwill Tasting",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        seats_capacity=20,
        demand_tier="STANDARD",
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest = FX.create_guest(api, display_name="Compensated Guest")
    stranger = FX.create_guest(api, display_name="Unrelated Guest")

    settled = FX.confirmed_reservation(
        api, ticket_class["id"], guest["id"], party_size=2
    )
    FX.set_clock(api, CANCEL_AT_48H)
    FX.cancel(api, settled["id"], guest["id"])
    exception = FX.approved_exception_with_shortfall(api, settled["id"], 4361, 1000)
    credit = FX.issue_goodwill_credit(
        api, exception["id"], CREDIT_FACE_VALUE, CREDIT_EXPIRES_AT
    )

    # A fresh booking of the same guest, which the credit may settle, and one
    # belonging to nobody the credit knows.
    target = FX.hold_seats(
        api,
        ticket_class["id"],
        guest["id"],
        party_size=2,
        primary_guest_name="Compensated Guest",
    )
    outsider = FX.hold_seats(
        api,
        ticket_class["id"],
        stranger["id"],
        party_size=2,
        primary_guest_name="Unrelated Guest",
    )
    return {
        "restaurant": restaurant,
        "guest": guest,
        "stranger": stranger,
        "settled": settled,
        "exception": exception,
        "credit": credit,
        "target": target,
        "outsider": outsider,
        "guest_headers": make_guest_headers(guest["id"]),
    }


def _redeem(api, credit_id, reservation_id, amount_cents, headers, version):
    """Attempt a redemption echoing a caller-chosen credit version."""
    return api.redeem_goodwill_credit(
        credit_id,
        F.redemption_payload(reservation_id, amount_cents, version),
        headers,
    )


def _rows_for_credit(api, credit_id, headers):
    """Every ledger row written against one credit."""
    rows, _meta = validate_paginated(
        api.list_payment_transactions(
            headers, {"goodwill_credit_id": credit_id, "limit": 100}
        )
    )
    return rows


class TestGoodwillRedemptionGuards:
    """One credit, six attempts, and each refusal at its pinned rung."""

    def test_a_one_cent_redemption_lands_and_its_replay_is_stale(self, api):
        """The credit's version moves, so the same body cannot be sent twice.

        "A successful redemption writes a `GOODWILL_REDEMPTION`
        `PaymentTransaction` of `amount_cents` on the target reservation with
        `memo_code` `CREDIT_APPLIED` and `goodwill_credit_id` set, credits
        `redeemed_cents` and debits `remaining_cents`, raises the reservation's
        `amount_paid_cents` — possibly advancing its `payment_status` all the
        way to `FULLY_PAID` — and advances the credit's `version` by one."

        Design: Corner/validations/goodwill_redemption_guard_ladder_returns_412_422_and_402
        """
        world = _goodwill_world(api)
        headers = world["guest_headers"]
        credit_id = world["credit"]["id"]
        observed = FX.credit_version(api, credit_id, headers)

        row = get_success_data(
            _redeem(api, credit_id, world["target"]["id"], 1, headers, observed)
        )
        assert row["kind"] == "GOODWILL_REDEMPTION"
        assert row["memo_code"] == "CREDIT_APPLIED"
        assert row["goodwill_credit_id"] == credit_id
        assert row["reservation_id"] == world["target"]["id"]
        assert row["amount_cents"] == 1
        A.assert_ledger_row_shape(row)
        A.assert_signed_amount(row)

        spent = FX.read_credit(api, credit_id, headers)
        assert spent["issued_cents"] == CREDIT_FACE_VALUE
        assert spent["redeemed_cents"] == 1
        assert spent["remaining_cents"] == CREDIT_FACE_VALUE - 1
        A.assert_credit_status(spent)
        assert spent["status"] == "PARTIALLY_REDEEMED"
        A.assert_version_advanced_by(spent["version"], observed, 1)

        # The identical request a second time is a stale view, not a second
        # legitimate partial redemption.
        replay = _redeem(api, credit_id, world["target"]["id"], 1, headers, observed)
        validate_error(replay, ERR_STALE_GOODWILL_CREDIT_VERSION, 412)

        unchanged = FX.read_credit(api, credit_id, headers)
        assert unchanged["redeemed_cents"] == 1
        assert len(_rows_for_credit(api, credit_id, headers)) == 1

    def test_the_wrong_guests_booking_and_an_overdraw_are_refused_apart(self, api):
        """Scope is checked before the remainder is.

        "The target reservation must belong to the credit's `guest_id` and its
        service must belong to the credit's `restaurant_id`, otherwise
        `ERR_GOODWILL_TARGET_MISMATCH` — credit does not travel between guests
        or between restaurants."

        Design: Corner/validations/goodwill_redemption_guard_ladder_returns_412_422_and_402
        """
        world = _goodwill_world(api)
        headers = world["guest_headers"]
        credit_id = world["credit"]["id"]
        FX.redeem_goodwill_credit(
            api, credit_id, world["target"]["id"], 1, guest_id=world["guest"]["id"]
        )
        live = FX.credit_version(api, credit_id, headers)

        # An operator acting on the guest's behalf still cannot spend the credit
        # on a booking that is not the credit guest's.
        operator = make_care_headers("care-operator-probe")
        mismatched = _redeem(
            api, credit_id, world["outsider"]["id"], 100, operator, live
        )
        validate_error(mismatched, ERR_GOODWILL_TARGET_MISMATCH, 422)

        # And on the right booking, one cent more than the remainder overdraws.
        overdraw = _redeem(
            api, credit_id, world["target"]["id"], CREDIT_FACE_VALUE, headers, live
        )
        validate_error(overdraw, ERR_GOODWILL_REDEMPTION_EXCEEDS_REMAINING, 402)

        intact = FX.read_credit(api, credit_id, headers)
        assert intact["redeemed_cents"] == 1
        assert intact["remaining_cents"] == CREDIT_FACE_VALUE - 1
        A.assert_credit_status(intact)
        assert len(_rows_for_credit(api, credit_id, headers)) == 1

    def test_expiry_answers_before_the_settled_balance_does(self, api):
        """With the bill already at zero and the credit lapsed, expiry wins.

        "The logical clock is strictly before the credit's `expires_at_utc`, on
        redemption — otherwise `ERR_GOODWILL_CREDIT_EXPIRED`." Only afterwards
        does the ladder ask that "`amount_cents` does not exceed the target
        reservation's `balance_due_cents`, on redemption — otherwise
        `ERR_GOODWILL_EXCEEDS_BALANCE_DUE`."

        Design: Corner/validations/goodwill_redemption_guard_ladder_returns_412_422_and_402
        """
        world = _goodwill_world(api)
        headers = world["guest_headers"]
        credit_id = world["credit"]["id"]
        target_id = world["target"]["id"]
        FX.redeem_goodwill_credit(
            api, credit_id, target_id, 1, guest_id=world["guest"]["id"]
        )

        # The guest settles the rest in cash, leaving nothing for credit to pay.
        FX.pay_in_full(api, target_id, world["guest"]["id"])
        settled = FX.read_reservation(api, target_id, headers)
        A.assert_payment_status(settled, "FULLY_PAID")
        assert settled["balance_due_cents"] == 0
        assert settled["amount_paid_cents"] == GRAND_TOTAL
        assert settled["goodwill_applied_cents"] == 1

        live = FX.credit_version(api, credit_id, headers)
        no_room = _redeem(api, credit_id, target_id, 100, headers, live)
        validate_error(no_room, ERR_GOODWILL_EXCEEDS_BALANCE_DUE, 402)

        # At exactly the expiry instant the credit is no longer live, and that
        # refusal outranks the settled balance.
        FX.set_clock(api, CREDIT_EXPIRES_AT)
        lapsed = _redeem(api, credit_id, target_id, 100, headers, live)
        validate_error(lapsed, ERR_GOODWILL_CREDIT_EXPIRED, 409)

        final = FX.read_credit(api, credit_id, headers)
        assert final["redeemed_cents"] == 1
        assert final["revoked_cents"] == 0
        assert final["remaining_cents"] == CREDIT_FACE_VALUE - 1
        A.assert_credit_identity(final)
        A.assert_credit_status(final)
        assert len(_rows_for_credit(api, credit_id, headers)) == 1


def _transfer_world(api):
    """A confirmed, deposit-paid Thursday ticket and four candidate recipients.

    The house permits two transfers per guest and closes transfers a day out,
    so nothing in this world is near either bound; the recipients differ only in
    whether the platform has flagged them for resale.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        max_transfers_per_guest=2,
        transfer_cutoff_minutes=1440,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Transfer Tasting",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        seats_capacity=20,
        demand_tier="STANDARD",
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    holder = FX.create_guest(api, display_name="Transfer Holder A")
    clean = FX.create_guest(api, display_name="Transfer Guest B")
    broker = FX.create_guest(
        api, display_name="Flagged Broker C", is_broker_flagged=True
    )
    onward = FX.create_guest(api, display_name="Onward Guest D")
    reservation = FX.confirmed_reservation(
        api,
        ticket_class["id"],
        holder["id"],
        party_size=2,
        primary_guest_name="Transfer Holder A",
    )
    return {
        "restaurant": restaurant,
        "ticket_class": ticket_class,
        "holder": holder,
        "clean": clean,
        "broker": broker,
        "onward": onward,
        "reservation": reservation,
        "holder_headers": make_guest_headers(holder["id"]),
        "manager": make_restaurant_headers(restaurant["id"]),
    }


def _successors_of(api, reservation_id):
    """Every reservation minted by transferring the given one."""
    rows, _meta = validate_paginated(
        api.list_reservations(
            ADMIN_HEADERS,
            {"transferred_from_reservation_id": reservation_id, "limit": 100},
        )
    )
    return rows


class TestTransferGuards:
    """Six preconditions, one refusal each, in the order the ladder pins."""

    def test_a_deposit_only_ticket_then_oneself_then_a_flagged_recipient(self, api):
        """Three rungs of the transfer guard, each isolated from the next.

        "The reservation's money dimension must read `FULLY_PAID` — a
        deposit-only ticket cannot be handed on — otherwise
        `ERR_TRANSFER_REQUIRES_FULL_PAYMENT`." And "The recipient guest's
        `is_broker_flagged` must be false, otherwise `ERR_RESALE_SUSPECTED`.
        This is the resale brake, and it is applied to the **recipient**, not
        the initiator."

        Design: Corner/validations/transfer_guard_ladder_rejects_deposit_only_self_and_broker
        """
        world = _transfer_world(api)
        headers = world["holder_headers"]
        reservation_id = world["reservation"]["id"]

        # Only the deposit is down, so the ticket cannot be handed on at all.
        A.assert_payment_status(world["reservation"], "DEPOSIT_PAID")
        deposit_only = api.transfer_reservation(
            reservation_id, F.transfer_payload(world["clean"]["id"]), headers
        )
        validate_error(deposit_only, ERR_TRANSFER_REQUIRES_FULL_PAYMENT, 409)

        FX.pay_in_full(api, reservation_id, world["holder"]["id"])
        paid = FX.read_reservation(api, reservation_id, headers)
        A.assert_payment_status(paid, "FULLY_PAID")
        assert paid["amount_paid_cents"] == GRAND_TOTAL

        # Handing the ticket to oneself is not a transfer.
        to_self = api.transfer_reservation(
            reservation_id, F.transfer_payload(world["holder"]["id"]), headers
        )
        validate_error(to_self, ERR_TRANSFER_TO_SELF, 422)

        # The resale brake is read off the recipient, and it outranks the
        # self-naming check.
        to_broker = api.transfer_reservation(
            reservation_id, F.transfer_payload(world["broker"]["id"]), headers
        )
        validate_error(to_broker, ERR_RESALE_SUSPECTED, 422)

        # Nothing moved: no successor, no counter, no state change.
        assert _successors_of(api, reservation_id) == []
        intact = FX.read_reservation(api, reservation_id, headers)
        A.assert_fulfillment_status(intact, "CONFIRMED")
        A.assert_payment_status(intact, "FULLY_PAID")
        initiator = FX.read_guest(api, world["holder"]["id"], headers)
        assert initiator["transfers_initiated_count"] == 0

    def test_the_permitted_transfer_conserves_the_cash_and_the_seats(self, api):
        """The successor pays what the predecessor paid and the pool is untouched.

        "A `TRANSFER_OUT` `PaymentTransaction` for the full `amount_paid_cents`
        is written against the predecessor and a matching `TRANSFER_IN` row
        against the successor, both carrying `memo_code` `TRANSFER_MOVE`, so
        that cash is conserved exactly across the pair and neither the
        restaurant nor the platform gains or loses a cent."

        Design: Corner/validations/transfer_guard_ladder_rejects_deposit_only_self_and_broker
        """
        world = _transfer_world(api)
        headers = world["holder_headers"]
        reservation_id = world["reservation"]["id"]
        FX.pay_in_full(api, reservation_id, world["holder"]["id"])

        successor = get_success_data(
            api.transfer_reservation(
                reservation_id,
                F.transfer_payload(
                    world["clean"]["id"], recipient_guest_name="Transfer Guest B"
                ),
                headers,
            ),
            201,
        )
        recipient_headers = make_guest_headers(world["clean"]["id"])

        # The body is the successor, and it is the only way to learn its id.
        assert successor["id"] != reservation_id
        assert successor["guest_id"] == world["clean"]["id"]
        assert successor["transferred_from_reservation_id"] == reservation_id
        assert successor["primary_guest_name"] == "Transfer Guest B"
        assert successor["party_size"] == 2
        assert successor["price_locked_per_cover_cents"] == 12000
        assert successor["grand_total_cents"] == GRAND_TOTAL
        assert successor["name_change_count"] == 0
        A.assert_fulfillment_status(successor, "CONFIRMED")
        A.assert_payment_status(successor, "FULLY_PAID")

        predecessor = FX.read_reservation(api, reservation_id, headers)
        A.assert_fulfillment_status(predecessor, "TRANSFERRED_OUT")
        A.assert_payment_status(predecessor, "TRANSFERRED")

        out_rows = [
            row
            for row in FX.ledger_rows(api, reservation_id, headers)
            if row["kind"] == "TRANSFER_OUT"
        ]
        in_rows = [
            row
            for row in FX.ledger_rows(api, successor["id"], recipient_headers)
            if row["kind"] == "TRANSFER_IN"
        ]
        assert len(out_rows) == 1
        assert len(in_rows) == 1
        assert out_rows[0]["amount_cents"] == GRAND_TOTAL
        assert in_rows[0]["amount_cents"] == GRAND_TOTAL
        assert out_rows[0]["memo_code"] == "TRANSFER_MOVE"
        assert in_rows[0]["memo_code"] == "TRANSFER_MOVE"
        A.assert_signed_amount(out_rows[0])
        A.assert_signed_amount(in_rows[0])

        initiator = FX.read_guest(api, world["holder"]["id"], headers)
        assert initiator["transfers_initiated_count"] == 1

        # The seats travelled with the successor rather than returning.
        pool = FX.read_ticket_class(api, world["ticket_class"]["id"], world["manager"])
        A.assert_seat_pool(
            pool, sold=2, held=0, released=0, available=18, status="OPEN"
        )

    def test_a_transferred_ticket_is_a_terminus(self, api):
        """The successor cannot itself be handed on to a third guest.

        "The reservation's own `transferred_from_reservation_id` must be null,
        otherwise `ERR_ONWARD_TRANSFER_FORBIDDEN`. A ticket that arrived by
        transfer is a terminus; chains of length greater than one are
        structurally impossible, which is what stops a broker from laundering a
        ticket through intermediaries."

        Design: Corner/validations/transfer_guard_ladder_rejects_deposit_only_self_and_broker
        """
        world = _transfer_world(api)
        reservation_id = world["reservation"]["id"]
        FX.pay_in_full(api, reservation_id, world["holder"]["id"])
        successor = get_success_data(
            api.transfer_reservation(
                reservation_id,
                F.transfer_payload(world["clean"]["id"]),
                world["holder_headers"],
            ),
            201,
        )

        # The recipient is fully paid, confirmed, unflagged and well inside both
        # the cutoff and their own transfer budget; only the chain rule bites.
        recipient_headers = make_guest_headers(world["clean"]["id"])
        onward = api.transfer_reservation(
            successor["id"],
            F.transfer_payload(world["onward"]["id"]),
            recipient_headers,
        )
        validate_error(onward, ERR_ONWARD_TRANSFER_FORBIDDEN, 422)

        assert _successors_of(api, successor["id"]) == []
        intact = FX.read_reservation(api, successor["id"], recipient_headers)
        A.assert_fulfillment_status(intact, "CONFIRMED")
        A.assert_payment_status(intact, "FULLY_PAID")
        recipient = FX.read_guest(api, world["clean"]["id"], recipient_headers)
        assert recipient["transfers_initiated_count"] == 0


# The second seating, a day after the first.
SECOND_SEATING_START = "2026-09-11T22:00:00Z"
SECOND_SEATING_END = "2026-09-12T02:00:00Z"
# The first seating less a full day of cutoff, and the minute past it.
CUTOFF_LAST_ALLOWED = "2026-09-09T22:00:00Z"
CUTOFF_ONE_MINUTE_LATE = "2026-09-09T22:01:00Z"


def _bounded_transfer_world(api):
    """A house allowing exactly one transfer per guest and closing transfers a
    full day before seating, with fully paid tickets on two consecutive nights.

    One guest holds a ticket on each night, so their single allowance can be
    spent on the first and then tested against the second; two further guests
    hold tickets on the first night, one to transfer at the last permitted
    instant and one to transfer a minute afterwards.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        max_transfers_per_guest=1,
        transfer_cutoff_minutes=1440,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Bounded Transfer Tasting",
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
    )
    first_night = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        seats_capacity=20,
        demand_tier="STANDARD",
    )
    second_night = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-11",
        meal_period="DINNER",
        seating_start_utc=SECOND_SEATING_START,
        seating_end_utc=SECOND_SEATING_END,
        seats_capacity=20,
        demand_tier="STANDARD",
    )
    first_class = FX.create_ticket_class(
        api, restaurant["id"], first_night["id"], package["id"], seats_allocated=20
    )
    second_class = FX.create_ticket_class(
        api, restaurant["id"], second_night["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], first_night["id"])
    FX.publish_service(api, restaurant["id"], second_night["id"])

    twice_booked = FX.create_guest(api, display_name="Twice Booked Guest A")
    punctual = FX.create_guest(api, display_name="Punctual Guest P")
    late = FX.create_guest(api, display_name="Late Guest Q")
    first_recipient = FX.create_guest(api, display_name="Recipient B")
    second_recipient = FX.create_guest(api, display_name="Recipient D")
    punctual_recipient = FX.create_guest(api, display_name="Recipient X")
    late_recipient = FX.create_guest(api, display_name="Recipient Y")

    return {
        "restaurant": restaurant,
        "first_night": first_night,
        "second_night": second_night,
        "twice_booked": twice_booked,
        "punctual": punctual,
        "late": late,
        "first_recipient": first_recipient,
        "second_recipient": second_recipient,
        "punctual_recipient": punctual_recipient,
        "late_recipient": late_recipient,
        "reservation_first_night": FX.fully_paid_reservation(
            api, first_class["id"], twice_booked["id"], party_size=2
        ),
        "reservation_second_night": FX.fully_paid_reservation(
            api, second_class["id"], twice_booked["id"], party_size=2
        ),
        "reservation_punctual": FX.fully_paid_reservation(
            api, first_class["id"], punctual["id"], party_size=2
        ),
        "reservation_late": FX.fully_paid_reservation(
            api, first_class["id"], late["id"], party_size=2
        ),
    }


class TestTransferBoundsAreExactlyWhereDeclared:
    """The lifetime allowance and the cutoff instant, tested at their edges."""

    def test_the_second_transfer_of_a_one_transfer_guest_is_refused(self, api):
        """The allowance is spent on the first night and gone on the second.

        "The initiating guest's `transfers_initiated_count` must be strictly
        below the restaurant's `max_transfers_per_guest`, otherwise
        `ERR_TRANSFER_LIMIT_REACHED`. This counter is lifetime and per guest,
        not per service."

        Design: Corner/validations/transfer_limit_and_cutoff_rejected_at_the_declared_bounds
        """
        world = _bounded_transfer_world(api)
        initiator_id = world["twice_booked"]["id"]
        headers = make_guest_headers(initiator_id)

        # The one permitted transfer.
        successor = get_success_data(
            api.transfer_reservation(
                world["reservation_first_night"]["id"],
                F.transfer_payload(world["first_recipient"]["id"]),
                headers,
            ),
            201,
        )
        assert successor["guest_id"] == world["first_recipient"]["id"]
        spent = FX.read_guest(api, initiator_id, headers)
        assert spent["transfers_initiated_count"] == 1

        # The counter is not per service, so the other night's ticket is stuck.
        refused = api.transfer_reservation(
            world["reservation_second_night"]["id"],
            F.transfer_payload(world["second_recipient"]["id"]),
            headers,
        )
        validate_error(refused, ERR_TRANSFER_LIMIT_REACHED, 422)

        stuck = FX.read_reservation(
            api, world["reservation_second_night"]["id"], headers
        )
        A.assert_fulfillment_status(stuck, "CONFIRMED")
        A.assert_payment_status(stuck, "FULLY_PAID")
        assert _successors_of(api, stuck["id"]) == []
        unchanged = FX.read_guest(api, initiator_id, headers)
        assert unchanged["transfers_initiated_count"] == 1

    def test_the_cutoff_instant_itself_is_still_open(self, api):
        """At the cutoff the transfer lands; a minute later the same one is refused.

        "The logical clock must be at or before the service's
        `seating_start_utc` less the restaurant's `transfer_cutoff_minutes`,
        otherwise `ERR_TRANSFER_CUTOFF_PASSED`."

        Design: Corner/validations/transfer_limit_and_cutoff_rejected_at_the_declared_bounds
        """
        world = _bounded_transfer_world(api)
        punctual_headers = make_guest_headers(world["punctual"]["id"])
        late_headers = make_guest_headers(world["late"]["id"])
        punctual_id = world["reservation_punctual"]["id"]
        late_id = world["reservation_late"]["id"]

        # Exactly 1440 minutes before the seating: the bound is inclusive.
        FX.set_clock(api, CUTOFF_LAST_ALLOWED)
        successor = get_success_data(
            api.transfer_reservation(
                punctual_id,
                F.transfer_payload(world["punctual_recipient"]["id"]),
                punctual_headers,
            ),
            201,
        )
        assert successor["transferred_from_reservation_id"] == punctual_id
        assert successor["guest_id"] == world["punctual_recipient"]["id"]

        # One minute later, an otherwise identical request is closed out.
        FX.set_clock(api, CUTOFF_ONE_MINUTE_LATE)
        refused = api.transfer_reservation(
            late_id,
            F.transfer_payload(world["late_recipient"]["id"]),
            late_headers,
        )
        validate_error(refused, ERR_TRANSFER_CUTOFF_PASSED, 422)

        stuck = FX.read_reservation(api, late_id, late_headers)
        A.assert_fulfillment_status(stuck, "CONFIRMED")
        A.assert_payment_status(stuck, "FULLY_PAID")
        initiator = FX.read_guest(api, world["late"]["id"], late_headers)
        assert initiator["transfers_initiated_count"] == 0

        # The reverse index confirms one successor exists and the other does not.
        assert [row["id"] for row in _successors_of(api, punctual_id)] == [
            successor["id"]
        ]
        assert _successors_of(api, late_id) == []
