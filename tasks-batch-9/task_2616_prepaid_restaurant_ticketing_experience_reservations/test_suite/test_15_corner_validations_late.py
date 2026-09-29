"""
Guard rails at their exact bounds: the rename cap and its cutoff, the aggregate
add-on quantity ceiling and its order cutoff, the party-band, capacity and
uniqueness guards, the two seating-floor instants, the money ceilings on
payment and adjudication, the dietary amendment cap, one ticket that satisfies
every temporal guard at its inclusive bound, and the rejection order that
decides which of two live violations answers the request.

Every rejection below is asserted with its exact error identifier and its exact
HTTP status, because the order in which a request is rejected is pinned and not
a matter of implementation taste.
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
    ERR_ADDON_ORDER_CUTOFF_PASSED,
    ERR_ADDON_QTY_INVALID,
    ERR_APPROVED_EXCEEDS_FORFEITED,
    ERR_APPROVED_EXCEEDS_REQUESTED,
    ERR_DIETARY_AMEND_LIMIT,
    ERR_DUPLICATE_ACTIVE_RESERVATION,
    ERR_DUPLICATE_WAITLIST_ENTRY,
    ERR_INVALID_PAGINATION,
    ERR_NAME_CHANGE_CUTOFF_PASSED,
    ERR_NAME_CHANGE_LIMIT_REACHED,
    ERR_NO_SHOW_TOO_EARLY,
    ERR_PARTY_SIZE_OUT_OF_BAND,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_REFUND_REQUEST_EXCEEDS_PAID,
    ERR_RESTAURANT_NOT_FOUND,
    ERR_SEATING_TOO_EARLY,
    ERR_SERVICE_CAPACITY_EXCEEDED,
    ERR_UNAUTHORIZED,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CARE_DECIDER_HEADERS,
    CARE_FILER_HEADERS,
    make_guest_headers,
    make_restaurant_headers,
)

# Every scenario below trades on the same Thursday evening. Thursday is neutral
# at 10000 basis points and the STANDARD tier is neutral too, so a 12000-cent
# cover prices at exactly 12000 cents and a party of two owes 24000 + 1740 =
# 25740 cents with a 7722-cent deposit.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
SEATING_START = "2026-09-10T22:00:00Z"
SEATING_END = "2026-09-11T02:00:00Z"
TURN_TIME_MINUTES = 150

GRAND_TOTAL = 25740
DEPOSIT_DUE = 7722

# seating_start_utc less the 240-minute name-change cutoff, and one minute past
# it.
RENAME_CUTOFF_INSTANT = "2026-09-10T18:00:00Z"
RENAME_CUTOFF_PASSED = "2026-09-10T18:01:00Z"
# seating_start_utc less the 1440-minute add-on and transfer cutoffs, and one
# minute past it.
DAY_OUT_CUTOFF_INSTANT = "2026-09-09T22:00:00Z"
DAY_OUT_CUTOFF_PASSED = "2026-09-09T22:01:00Z"
# One minute before the seating instant, the seating instant itself, one minute
# before the no-show grace expires and the instant it expires.
ONE_MINUTE_EARLY = "2026-09-10T21:59:00Z"
NO_SHOW_TOO_EARLY = "2026-09-10T22:29:00Z"
NO_SHOW_INSTANT = "2026-09-10T22:30:00Z"
# seat_from_utc plus the service's turn_time_minutes.
SEAT_TO = "2026-09-11T00:30:00Z"


def _standard_chain(api, **restaurant_overrides):
    """The restaurant, package and published Thursday service every scenario
    starts from, with one 20-seat class spanning the package's whole band."""
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        refund_scrutiny_threshold_cents=300000,
        **restaurant_overrides,
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
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=TURN_TIME_MINUTES,
        seats_capacity=20,
        demand_tier="STANDARD",
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
    return {
        "restaurant": restaurant,
        "restaurant_id": restaurant["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "package": package,
        "package_id": package["id"],
        "service": service,
        "service_id": service["id"],
        "ticket_class": ticket_class,
        "ticket_class_id": ticket_class["id"],
    }


def _rename_world(api):
    """Three confirmed parties of two on one class, under a restaurant that
    permits a single rename and closes renames 240 minutes out."""
    world = _standard_chain(
        api, max_name_changes=1, name_change_cutoff_minutes=240
    )
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    letters = ("A", "B", "C")
    for letter in letters:
        guest = FX.create_guest(api, display_name=f"Rename Guest {letter}")
        reservation = FX.confirmed_reservation(
            api,
            world["ticket_class_id"],
            guest["id"],
            party_size=2,
            primary_guest_name=f"Rename Guest {letter}",
        )
        world[f"guest_{letter}"] = guest
        world[f"reservation_{letter}"] = reservation
    return world


def _rename(api, reservation_id, guest_id, new_name):
    """Attempt one rename as the guest who holds the ticket."""
    return api.change_name(
        reservation_id,
        F.name_change_payload(new_name),
        make_guest_headers(guest_id),
    )


class TestNameChangeLimitAndCutoff:
    """The per-reservation rename cap and the inclusive rename cutoff."""

    def test_the_second_rename_is_refused_once_the_cap_is_reached(self, api):
        """One permitted rename lands; the next is refused on the cap.

        "It is further allowed only while the reservation's `name_change_count`
        is strictly below the restaurant's `max_name_changes`, so a restaurant
        configured with `max_name_changes` of 2 permits exactly two renames and
        refuses the third with `ERR_NAME_CHANGE_LIMIT_REACHED`."

        Design: Corner/validations/name_change_limit_and_cutoff_rejected
        """
        world = _rename_world(api)
        guest_id = world["guest_A"]["id"]
        headers = make_guest_headers(guest_id)
        reservation_id = world["reservation_A"]["id"]

        renamed = get_success_data(
            _rename(api, reservation_id, guest_id, "Rename Guest A Prime"), 200
        )
        assert renamed["primary_guest_name"] == "Rename Guest A Prime"
        assert renamed["name_change_count"] == 1
        A.assert_version_advanced_by(
            renamed["version"], world["reservation_A"]["version"]
        )

        refused = _rename(api, reservation_id, guest_id, "Rename Guest A Double")
        validate_error(refused, ERR_NAME_CHANGE_LIMIT_REACHED, 422)

        after = FX.read_reservation(api, reservation_id, headers)
        assert after["primary_guest_name"] == "Rename Guest A Prime"
        assert after["name_change_count"] == 1
        assert after["version"] == renamed["version"]

    def test_the_cutoff_instant_itself_is_still_open_and_one_minute_later_is_not(
        self, api
    ):
        """Seating minus 240 minutes is the last instant a rename is accepted.

        "A name change takes a single `primary_guest_name` and is allowed only
        while the logical clock is at or before the service's
        `seating_start_utc` less the restaurant's `name_change_cutoff_minutes`;
        inside that window the request is refused with
        `ERR_NAME_CHANGE_CUTOFF_PASSED`."

        Design: Corner/validations/name_change_limit_and_cutoff_rejected
        """
        world = _rename_world(api)
        guest_b = world["guest_B"]["id"]
        guest_c = world["guest_C"]["id"]

        FX.set_clock(api, RENAME_CUTOFF_INSTANT)
        on_the_bound = get_success_data(
            _rename(
                api, world["reservation_B"]["id"], guest_b, "Rename Guest B Prime"
            ),
            200,
        )
        assert on_the_bound["primary_guest_name"] == "Rename Guest B Prime"
        assert on_the_bound["name_change_count"] == 1

        FX.set_clock(api, RENAME_CUTOFF_PASSED)
        refused = _rename(
            api, world["reservation_C"]["id"], guest_c, "Rename Guest C Prime"
        )
        validate_error(refused, ERR_NAME_CHANGE_CUTOFF_PASSED, 422)

        untouched = FX.read_reservation(
            api, world["reservation_C"]["id"], make_guest_headers(guest_c)
        )
        assert untouched["name_change_count"] == 0
        assert untouched["primary_guest_name"] == "Rename Guest C"

    def test_a_rename_moves_neither_the_owner_nor_a_single_seat(self, api):
        """A rename edits the printed name and nothing else at all.

        "Nothing else moves: no ledger row is written, no seat counter changes,
        no roll-up is touched."

        Design: Corner/validations/name_change_limit_and_cutoff_rejected
        """
        world = _rename_world(api)
        guest_b = world["guest_B"]["id"]
        headers = make_guest_headers(guest_b)
        reservation_id = world["reservation_B"]["id"]

        before_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            before_class, sold=6, held=0, released=0, available=14, status="OPEN"
        )
        before_rows = FX.ledger_rows(api, reservation_id, headers)

        renamed = get_success_data(
            _rename(api, reservation_id, guest_b, "Rename Guest B Prime"), 200
        )
        # The ticket changed its printed name, not its owner: that is exactly
        # what separates a rename from a transfer.
        assert renamed["guest_id"] == guest_b
        assert renamed["fulfillment_status"] == "CONFIRMED"

        after_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            after_class, sold=6, held=0, released=0, available=14, status="OPEN"
        )
        after_rows = FX.ledger_rows(api, reservation_id, headers)
        assert len(after_rows) == len(before_rows)
        A.assert_money_breakdown(
            renamed,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
            amount_paid=DEPOSIT_DUE,
            refunded=0,
            forfeited=0,
        )


def _add_on_world(api):
    """A confirmed party of two plus a 100-cent bread service whose orders
    close a full day before seating."""
    world = _standard_chain(api)
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    add_on = FX.create_add_on(
        api,
        world["restaurant_id"],
        name="Bread Service",
        price_cents=100,
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=1440,
    )
    guest = FX.create_guest(api, display_name="Add On Guest")
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest["id"], party_size=2
    )
    world["add_on"] = add_on
    world["add_on_id"] = add_on["id"]
    world["guest"] = guest
    world["guest_id"] = guest["id"]
    world["guest_headers"] = make_guest_headers(guest["id"])
    world["reservation"] = reservation
    world["reservation_id"] = reservation["id"]
    return world


def _append_attempt(api, world, qty):
    """Attempt one add-on line, echoing the reservation's live version so the
    stale-view check can never be what answers the request."""
    headers = world["guest_headers"]
    version = FX.reservation_version(api, world["reservation_id"], headers)
    return api.append_add_on_line(
        world["reservation_id"],
        F.add_on_line_payload(world["add_on_id"], version, qty=qty),
        headers,
    )


class TestAddOnQuantityAggregateAndOrderCutoff:
    """The quantity ceiling is an aggregate across lines, and the cutoff is
    tested before the quantity is."""

    def test_the_ceiling_counts_quantities_already_ordered_on_other_lines(self, api):
        """Three of four covers' worth lands; a further two breaches the ceiling.

        "The quantity must be at least 1 and, counting quantities already
        ordered on other lines for the same add-on, at most `max_qty_per_cover`
        multiplied by the reservation's `party_size`; a breach yields
        `ERR_ADDON_QTY_INVALID`."

        Design: Corner/validations/addon_qty_aggregate_and_order_cutoff_rejected
        """
        world = _add_on_world(api)

        # 3 is inside the ceiling of 2 per cover times a party of 2.
        line = get_success_data(_append_attempt(api, world, 3), 201)
        assert line["qty"] == 3
        assert line["unit_price_cents_locked"] == 100
        assert line["line_subtotal_cents"] == 300
        # 300 * 725 / 10000 is 21.75, rounded half up on this line alone.
        assert line["line_service_charge_cents"] == 22
        assert line["line_prep_minutes"] == 12
        assert line["ack_required"] is False

        # 3 already ordered plus 2 more is 5, one past the aggregate ceiling.
        refused = _append_attempt(api, world, 2)
        validate_error(refused, ERR_ADDON_QTY_INVALID, 422)

        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        assert reservation["add_on_total_cents"] == 300
        assert reservation["prep_minutes_total"] == 36

    def test_the_cutoff_instant_is_inclusive_and_is_tested_before_the_quantity(
        self, api
    ):
        """The last legal instant still accepts an order; one minute later the
        cutoff answers even though the quantity is also out of range.

        "The order must arrive at or before the add-on's own cutoff — the
        service's `seating_start_utc` less the add-on's `order_cutoff_minutes` —
        or it is refused with `ERR_ADDON_ORDER_CUTOFF_PASSED`."

        Design: Corner/validations/addon_qty_aggregate_and_order_cutoff_rejected
        """
        world = _add_on_world(api)
        FX.append_add_on_line(
            api,
            world["reservation_id"],
            world["guest_id"],
            world["add_on_id"],
            qty=3,
        )

        FX.set_clock(api, DAY_OUT_CUTOFF_INSTANT)
        on_the_bound = get_success_data(_append_attempt(api, world, 1), 201)
        assert on_the_bound["qty"] == 1
        assert on_the_bound["line_subtotal_cents"] == 100
        # 100 * 725 / 10000 is 7.25, rounded half up to 7 on this line alone.
        assert on_the_bound["line_service_charge_cents"] == 7

        FX.set_clock(api, DAY_OUT_CUTOFF_PASSED)
        # This request breaches the cutoff and the aggregate quantity ceiling at
        # once; the cutoff is the earlier check and is the one that answers.
        refused = _append_attempt(api, world, 2)
        validate_error(refused, ERR_ADDON_ORDER_CUTOFF_PASSED, 422)

    def test_the_accepted_lines_re_roll_the_charge_without_moving_the_deposit(
        self, api
    ):
        """Two lines raise the grand total and the balance, never the deposit.

        "`deposit_frozen` becomes true as soon as the first `DEPOSIT_CHARGE` row
        lands on the reservation, and confirmation likewise guarantees it is
        true; from that point on, appending further add-on lines raises
        `grand_total_cents` and `balance_due_cents` but leaves
        `deposit_due_cents` exactly where it was."

        Design: Corner/validations/addon_qty_aggregate_and_order_cutoff_rejected
        """
        world = _add_on_world(api)
        FX.append_add_on_line(
            api,
            world["reservation_id"],
            world["guest_id"],
            world["add_on_id"],
            qty=3,
        )
        FX.set_clock(api, DAY_OUT_CUTOFF_INSTANT)
        FX.append_add_on_line(
            api,
            world["reservation_id"],
            world["guest_id"],
            world["add_on_id"],
            qty=1,
        )

        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        assert reservation["deposit_frozen"] is True
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=24000,
            add_on_total=400,
            # 1740 on the ticket plus 22 and 7 rounded per line.
            service_charge=1769,
            grand_total=26169,
            deposit_due=DEPOSIT_DUE,
            amount_paid=DEPOSIT_DUE,
        )
        assert reservation["balance_due_cents"] == 18447
        # 2 covers at 12 minutes, plus 4 minutes a unit over 4 units.
        assert reservation["prep_minutes_total"] == 40
        A.assert_payment_status(reservation, "DEPOSIT_PAID")


def _band_world(api):
    """A 20-seat service whose whole capacity is already allocated to one class
    that admits parties of 1 to 4, under a package that admits 1 to 8. The
    service is left `DRAFT` so that allocation attempts are legal to make."""
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725)
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
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
        turn_time_minutes=TURN_TIME_MINUTES,
        seats_capacity=20,
        demand_tier="STANDARD",
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=20,
        min_party_size=1,
        max_party_size=4,
    )
    return {
        "restaurant_id": restaurant["id"],
        "manager": make_restaurant_headers(restaurant["id"]),
        "package_id": package["id"],
        "service_id": service["id"],
        "ticket_class_id": ticket_class["id"],
        "guest_a": FX.create_guest(api, display_name="Band Guest A"),
        "guest_b": FX.create_guest(api, display_name="Band Guest B"),
        "guest_c": FX.create_guest(api, display_name="Band Guest C"),
    }


def _reservation_attempt(api, world, guest_id, party_size):
    """Attempt one direct sale, echoing the class's live version."""
    version = FX.ticket_class_version(api, world["ticket_class_id"], world["manager"])
    return api.create_reservation(
        F.reservation_payload(
            world["ticket_class_id"],
            guest_id,
            version,
            party_size=party_size,
            primary_guest_name="Band Party",
        ),
        make_guest_headers(guest_id),
    )


class TestPartyBandCapacityAndDuplicateGuards:
    """The band, the capacity sum and the two uniqueness guards, each answered
    by its own error and in the order the ladder pins."""

    def test_a_class_band_outside_its_package_band_answers_before_the_capacity_sum(
        self, api
    ):
        """One allocation attempt breaches both the band and the capacity; the
        band is the earlier check.

        "The party size sits inside the ticket class's own band, and a new
        class's band lies inside its package's band, on reservation creation,
        ticket-class creation and waitlist-entry creation — otherwise
        `ERR_PARTY_SIZE_OUT_OF_BAND`."

        Design: Corner/validations/violation_to_error_party_band_capacity_and_duplicate_guards
        """
        world = _band_world(api)

        out_of_band = api.create_ticket_class(
            F.ticket_class_payload(
                world["service_id"],
                world["package_id"],
                seats_allocated=1,
                min_party_size=1,
                max_party_size=9,
            ),
            world["manager"],
        )
        validate_error(out_of_band, ERR_PARTY_SIZE_OUT_OF_BAND, 422)

        rows, _meta = validate_paginated(
            api.list_ticket_classes(
                world["manager"], {"service_id": world["service_id"], "limit": 100}
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == world["ticket_class_id"]

    def test_a_band_legal_allocation_still_fails_on_the_capacity_sum(self, api):
        """With the band satisfied, one more seat than capacity is refused.

        "The sum of `seats_allocated` across the service's ticket classes does
        not exceed the service's `seats_capacity`, on ticket-class creation
        **and** on service publication — otherwise
        `ERR_SERVICE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/violation_to_error_party_band_capacity_and_duplicate_guards
        """
        world = _band_world(api)

        over_capacity = api.create_ticket_class(
            F.ticket_class_payload(
                world["service_id"],
                world["package_id"],
                seats_allocated=1,
                min_party_size=1,
                max_party_size=4,
            ),
            world["manager"],
        )
        validate_error(over_capacity, ERR_SERVICE_CAPACITY_EXCEEDED, 422)

        rows, meta = validate_paginated(
            api.list_ticket_classes(
                world["manager"], {"service_id": world["service_id"], "limit": 100}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1

    def test_the_band_is_enforced_on_a_sale_and_on_a_waitlist_entry_alike(self, api):
        """A party of five and a party of nine are both outside every band in
        force on this service.

        "The party size sits inside the ticket class's own band, and a new
        class's band lies inside its package's band, on reservation creation,
        ticket-class creation and waitlist-entry creation — otherwise
        `ERR_PARTY_SIZE_OUT_OF_BAND`."

        Design: Corner/validations/violation_to_error_party_band_capacity_and_duplicate_guards
        """
        world = _band_world(api)
        FX.publish_service(api, world["restaurant_id"], world["service_id"])
        guest_c = world["guest_c"]["id"]

        too_big_to_sell = _reservation_attempt(api, world, guest_c, 5)
        validate_error(too_big_to_sell, ERR_PARTY_SIZE_OUT_OF_BAND, 422)

        too_big_to_wait = api.create_waitlist_entry(
            F.waitlist_entry_payload(
                world["service_id"],
                guest_c,
                party_size=9,
                requested_package_id=world["package_id"],
            ),
            make_guest_headers(guest_c),
        )
        validate_error(too_big_to_wait, ERR_PARTY_SIZE_OUT_OF_BAND, 422)

        # Neither refusal touched a seat.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=0, available=20, status="OPEN"
        )

    def test_one_live_booking_and_one_live_waitlist_entry_per_guest_per_service(
        self, api
    ):
        """The second attempt by the same guest on the same service is refused
        on each of the two surfaces.

        "The guest holds no other reservation on the same service in `PENDING`,
        `CONFIRMED` or `SEATED`, on reservation creation — otherwise
        `ERR_DUPLICATE_ACTIVE_RESERVATION`."

        "The guest has no other waitlist entry on the same service in `WAITING`
        or `OFFERED`, on waitlist-entry creation — otherwise
        `ERR_DUPLICATE_WAITLIST_ENTRY`."

        Design: Corner/validations/violation_to_error_party_band_capacity_and_duplicate_guards
        """
        world = _band_world(api)
        FX.publish_service(api, world["restaurant_id"], world["service_id"])
        guest_a = world["guest_a"]["id"]
        guest_b = world["guest_b"]["id"]

        first = get_success_data(_reservation_attempt(api, world, guest_a, 2), 201)
        A.assert_fulfillment_status(first, "PENDING")
        held = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(held, sold=0, held=2, released=0, available=18)

        # The echoed class version is deliberately re-read, so the stale-view
        # check cannot be what answers this request.
        duplicate = _reservation_attempt(api, world, guest_a, 2)
        validate_error(duplicate, ERR_DUPLICATE_ACTIVE_RESERVATION, 422)

        entry = FX.join_waitlist(api, world["service_id"], guest_b, party_size=2)
        assert entry["status"] == "WAITING"
        duplicate_entry = api.create_waitlist_entry(
            F.waitlist_entry_payload(world["service_id"], guest_b, party_size=3),
            make_guest_headers(guest_b),
        )
        validate_error(duplicate_entry, ERR_DUPLICATE_WAITLIST_ENTRY, 422)

        rows, meta = validate_paginated(
            api.list_waitlist_entries(
                make_guest_headers(guest_b),
                {"service_id": world["service_id"], "guest_id": guest_b, "limit": 100},
            )
        )
        assert [row["id"] for row in rows] == [entry["id"]]
        assert meta["total_count"] == 1


def _floor_world(api):
    """Two confirmed parties of two, each on its own table, both due to sit at
    the seating instant, under a 30-minute no-show grace."""
    world = _standard_chain(api, no_show_grace_minutes=30, prep_lead_minutes=45)
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    table_a = FX.create_table(api, world["restaurant_id"], seats_min=1, seats_max=8)
    table_b = FX.create_table(api, world["restaurant_id"], seats_min=1, seats_max=8)
    guest_a = FX.create_guest(api, display_name="Floor Guest A")
    guest_b = FX.create_guest(api, display_name="Floor Guest B")
    reservation_a = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_a["id"], party_size=2, pay_full=True
    )
    reservation_b = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_b["id"], party_size=2
    )
    FX.assign_table(
        api,
        world["restaurant_id"],
        reservation_a["id"],
        table_a["id"],
        SEATING_START,
    )
    FX.assign_table(
        api,
        world["restaurant_id"],
        reservation_b["id"],
        table_b["id"],
        SEATING_START,
    )
    world["guest_a"] = guest_a
    world["guest_b"] = guest_b
    world["reservation_a_id"] = reservation_a["id"]
    world["reservation_b_id"] = reservation_b["id"]
    return world


class TestSeatingAndNoShowEarliestLegalInstant:
    """Two floors, one minute apart in effect: the seating instant and the
    seating instant plus the grace."""

    def test_one_minute_before_the_seating_instant_both_floors_refuse(self, api):
        """At 21:59 neither the seating floor nor the no-show floor is reached.

        "It requires the reservation to be `CONFIRMED`, `assigned_table_id` to be
        non-null, every `ANAPHYLAXIS` note to be `ACKED`, no note to be in
        `PREP_REJECTED`, and the logical clock to have reached `seat_from_utc` —
        an attempt before that instant is refused with `ERR_SEATING_TOO_EARLY`."

        Design: Corner/validations/temporal_validation_seating_and_no_show_at_their_earliest_legal_instant
        """
        world = _floor_world(api)
        FX.set_clock(api, ONE_MINUTE_EARLY)

        too_early_to_seat = api.seat_reservation(
            world["reservation_a_id"], world["manager"]
        )
        validate_error(too_early_to_seat, ERR_SEATING_TOO_EARLY, 422)

        too_early_to_write_off = api.declare_no_show(
            world["reservation_b_id"], world["manager"]
        )
        validate_error(too_early_to_write_off, ERR_NO_SHOW_TOO_EARLY, 422)

        for reservation_id, guest in (
            (world["reservation_a_id"], world["guest_a"]),
            (world["reservation_b_id"], world["guest_b"]),
        ):
            reservation = FX.read_reservation(
                api, reservation_id, make_guest_headers(guest["id"])
            )
            A.assert_fulfillment_status(reservation, "CONFIRMED")
            assert reservation["seat_to_utc"] is None

    def test_seating_lands_on_the_instant_itself_and_pins_the_turn(self, api):
        """The seating floor is inclusive, and seating pins the end of the turn.

        "Seating pins `seat_to_utc` to `seat_from_utc` plus the service's
        `turn_time_minutes`; until the party is seated, `seat_to_utc` is null."

        Design: Corner/validations/temporal_validation_seating_and_no_show_at_their_earliest_legal_instant
        """
        world = _floor_world(api)
        FX.set_clock(api, SEATING_START)

        seated = get_success_data(
            api.seat_reservation(world["reservation_a_id"], world["manager"]), 200
        )
        A.assert_fulfillment_status(seated, "SEATED")
        A.assert_instant_equals(seated["seat_from_utc"], SEATING_START, "seat_from_utc")
        A.assert_instant_equals(seated["seat_to_utc"], SEAT_TO, "seat_to_utc")
        # Seating is a floor event only: it moves no money and no seat.
        A.assert_payment_status(seated, "FULLY_PAID")
        A.assert_money_breakdown(
            seated,
            grand_total=GRAND_TOTAL,
            amount_paid=GRAND_TOTAL,
            refunded=0,
            forfeited=0,
        )
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=4, held=0, released=0, available=16, status="OPEN"
        )

    def test_the_no_show_floor_is_the_grace_expiry_and_forfeits_everything_paid(
        self, api
    ):
        """22:29 is one minute too early; 22:30 writes the whole deposit off.

        "It is a `RestaurantManager` action and may not be declared until the
        logical clock has reached `seat_from_utc` plus the restaurant's
        `no_show_grace_minutes`; declaring earlier is refused with
        `ERR_NO_SHOW_TOO_EARLY`."

        "`cancel_settlement_basis` is set to `NO_SHOW_FULL` and the whole of
        `amount_paid_cents` is forfeited by writing a single `FORFEITURE` row
        with `memo_code` `NO_SHOW`, which drives the money dimension to
        `FORFEITED`."

        Design: Corner/validations/temporal_validation_seating_and_no_show_at_their_earliest_legal_instant
        """
        world = _floor_world(api)
        guest_headers = make_guest_headers(world["guest_b"]["id"])

        FX.set_clock(api, NO_SHOW_TOO_EARLY)
        refused = api.declare_no_show(world["reservation_b_id"], world["manager"])
        validate_error(refused, ERR_NO_SHOW_TOO_EARLY, 422)

        FX.set_clock(api, NO_SHOW_INSTANT)
        declared = get_success_data(
            api.declare_no_show(world["reservation_b_id"], world["manager"]), 200
        )
        A.assert_fulfillment_status(declared, "NO_SHOW")
        A.assert_payment_status(declared, "FORFEITED")
        assert declared["cancel_settlement_basis"] == "NO_SHOW_FULL"
        A.assert_money_breakdown(
            declared,
            amount_paid=DEPOSIT_DUE,
            forfeited=DEPOSIT_DUE,
            refunded=0,
        )
        A.assert_settled_ledger_identity(declared)

        rows = FX.ledger_rows(api, world["reservation_b_id"], guest_headers)
        forfeitures = [row for row in rows if row["kind"] == "FORFEITURE"]
        assert len(forfeitures) == 1
        assert forfeitures[0]["memo_code"] == "NO_SHOW"
        assert forfeitures[0]["amount_cents"] == DEPOSIT_DUE
        A.assert_derived_ledger_figures(declared, rows)

        # The write-off returns the party's seats to the pool; the other
        # reservation's two seats stay sold.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=2, held=0, released=0, available=18, status="OPEN"
        )


# Exactly 48.0 hours before the seating instant, which is the inclusive top of
# the STANDARD ladder's 5000-basis-point band.
CANCEL_AT_48H = "2026-09-08T22:00:00Z"


def _money_world(api):
    """One deposit-paid party of two carrying an 18018-cent balance, and one
    fully paid party of two that will be walked all the way to completion."""
    world = _standard_chain(api)
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    world["table"] = FX.create_table(
        api, world["restaurant_id"], seats_min=1, seats_max=8
    )
    guest_a = FX.create_guest(api, display_name="Ceiling Guest A")
    guest_b = FX.create_guest(api, display_name="Ceiling Guest B")
    world["guest_a"] = guest_a
    world["guest_b"] = guest_b
    world["headers_a"] = make_guest_headers(guest_a["id"])
    world["headers_b"] = make_guest_headers(guest_b["id"])
    world["reservation_a"] = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_a["id"], party_size=2
    )
    world["reservation_b"] = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest_b["id"], party_size=2, pay_full=True
    )
    return world


class TestPaymentAndRefundAmountCeilings:
    """Each money ceiling refuses the cent that would breach it, and refuses it
    with the payment-required status the catalogue pins."""

    def test_one_cent_past_the_balance_is_refused_and_takes_no_money(self, api):
        """A payment of 18019 against a balance of 18018 is refused outright.

        "A payment may never exceed the reservation's `balance_due_cents`
        (`ERR_PAYMENT_EXCEEDS_BALANCE`), and the very first payment on a
        reservation must be at least `deposit_due_cents`
        (`ERR_PAYMENT_BELOW_DEPOSIT`)."

        Design: Corner/validations/violation_to_error_payment_and_refund_amount_ceilings
        """
        world = _money_world(api)
        reservation_id = world["reservation_a"]["id"]
        assert world["reservation_a"]["balance_due_cents"] == 18018

        refused = api.take_payment(
            reservation_id, F.payment_payload(18019), world["headers_a"]
        )
        validate_error(refused, ERR_PAYMENT_EXCEEDS_BALANCE, 402)

        reservation = FX.read_reservation(api, reservation_id, world["headers_a"])
        A.assert_money_breakdown(
            reservation,
            grand_total=GRAND_TOTAL,
            amount_paid=DEPOSIT_DUE,
            refunded=0,
            forfeited=0,
        )
        assert reservation["balance_due_cents"] == 18018
        A.assert_payment_status(reservation, "DEPOSIT_PAID")
        rows = FX.ledger_rows(api, reservation_id, world["headers_a"])
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE"]

    def test_the_request_ceiling_is_the_money_still_held_and_approval_cannot_exceed_it(
        self, api
    ):
        """After a settlement retains 4361 cents, 4361 may be asked for and 4362
        may not, and an approval may not exceed what was asked.

        "The request must be at least 1 cent and may not exceed the
        reservation's `amount_paid_cents` less its `refunded_cents`, which is the
        money still sitting with the restaurant; asking for more is refused with
        `ERR_REFUND_REQUEST_EXCEEDS_PAID`."

        Design: Corner/validations/violation_to_error_payment_and_refund_amount_ceilings
        """
        world = _money_world(api)
        reservation_id = world["reservation_a"]["id"]

        FX.set_clock(api, CANCEL_AT_48H)
        FX.cancel(api, reservation_id, world["guest_a"]["id"])
        settled = FX.read_reservation(api, reservation_id, world["headers_a"])
        A.assert_money_breakdown(
            settled, amount_paid=DEPOSIT_DUE, forfeited=4361, refunded=3361
        )
        A.assert_payment_status(settled, "PARTIALLY_REFUNDED")

        # 7722 paid less 3361 already returned leaves 4361 with the restaurant.
        over_the_ceiling = api.create_refund_exception(
            F.refund_exception_payload(reservation_id, 4362), CARE_FILER_HEADERS
        )
        validate_error(over_the_ceiling, ERR_REFUND_REQUEST_EXCEEDS_PAID, 402)

        exception = get_success_data(
            api.create_refund_exception(
                F.refund_exception_payload(reservation_id, 4361), CARE_FILER_HEADERS
            ),
            201,
        )
        assert exception["status"] == "REQUESTED"
        assert exception["requested_cents"] == 4361
        assert exception["approved_cents"] == 0

        over_the_request = api.decide_refund_exception(
            exception["id"],
            F.decide_payload(decision="APPROVED", approved_cents=4362),
            CARE_DECIDER_HEADERS,
        )
        validate_error(over_the_request, ERR_APPROVED_EXCEEDS_REQUESTED, 402)

        undecided = get_success_data(
            api.get_refund_exception(exception["id"], CARE_DECIDER_HEADERS), 200
        )
        assert undecided["status"] == "REQUESTED"
        assert undecided["approved_cents"] == 0
        assert undecided["decided_by_user_id"] is None
        unchanged = FX.read_reservation(api, reservation_id, world["headers_a"])
        A.assert_money_breakdown(unchanged, forfeited=4361, refunded=3361)

    def test_an_approval_cannot_manufacture_cash_that_was_never_retained(self, api):
        """On a completed reservation nothing is forfeited, so not even one cent
        may be approved.

        "The `REQUESTED → APPROVED` arm additionally requires `approved_cents` to
        be strictly above 0 and at most `requested_cents` — more is refused with
        `ERR_APPROVED_EXCEEDS_REQUESTED` — and at most the reservation's current
        `forfeited_cents`, so that a reversal can never manufacture cash that was
        never retained; more is refused with `ERR_APPROVED_EXCEEDS_FORFEITED`."

        Design: Corner/validations/violation_to_error_payment_and_refund_amount_ceilings
        """
        world = _money_world(api)
        reservation_id = world["reservation_b"]["id"]
        FX.assign_table(
            api,
            world["restaurant_id"],
            reservation_id,
            world["table"]["id"],
            SEATING_START,
        )
        FX.set_clock(api, SEATING_START)
        FX.seat(api, world["restaurant_id"], reservation_id)
        completed = FX.complete(api, world["restaurant_id"], reservation_id)
        A.assert_fulfillment_status(completed, "COMPLETED")
        A.assert_money_breakdown(
            completed, amount_paid=GRAND_TOTAL, forfeited=0, refunded=0
        )

        exception = FX.file_refund_exception(api, reservation_id, 5000)
        assert exception["status"] == "REQUESTED"

        refused = api.decide_refund_exception(
            exception["id"],
            F.decide_payload(decision="APPROVED", approved_cents=1),
            CARE_DECIDER_HEADERS,
        )
        validate_error(refused, ERR_APPROVED_EXCEEDS_FORFEITED, 402)

        still_requested = get_success_data(
            api.get_refund_exception(exception["id"], CARE_DECIDER_HEADERS), 200
        )
        assert still_requested["status"] == "REQUESTED"
        assert still_requested["approved_cents"] == 0
        rows = FX.ledger_rows(api, reservation_id, world["headers_b"])
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE"]
        assert not [row for row in rows if row["kind"] == "REFUND"]


AMENDMENT_TEXTS = (
    "First amendment: peanuts and tree nuts, prepared on a clean pass.",
    "Second amendment: peanuts and tree nuts, no shared fryer.",
    "Third amendment: peanuts and tree nuts, sealed mise en place.",
)


def _note_world(api):
    """A confirmed party of two carrying one ALLERGY note on cover 1."""
    world = _standard_chain(api)
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    guest = FX.create_guest(api, display_name="Amend Guest")
    reservation = FX.confirmed_reservation(
        api, world["ticket_class_id"], guest["id"], party_size=2
    )
    note = FX.add_dietary_note(
        api,
        reservation["id"],
        guest["id"],
        guest_index=1,
        severity="ALLERGY",
        restriction_code="NUT",
        note_text="No nuts of any kind.",
    )
    world["guest_id"] = guest["id"]
    world["guest_headers"] = make_guest_headers(guest["id"])
    world["reservation_id"] = reservation["id"]
    world["note"] = note
    world["note_id"] = note["id"]
    return world


def _amend_attempt(api, world, note_text):
    """Attempt one amendment that keeps the severity and restriction as they
    are, so the kitchen's prep minutes cannot move."""
    return api.amend_dietary_note(
        world["note_id"],
        F.amend_payload(
            restriction_code="NUT", severity="ALLERGY", note_text=note_text
        ),
        world["guest_headers"],
    )


def _exhaust_the_amend_budget(api, world):
    """Walk the reject-and-amend cycle three times, which is the cap."""
    for index, text in enumerate(AMENDMENT_TEXTS, start=1):
        FX.reject_note(api, world["restaurant_id"], world["note_id"])
        amended = get_success_data(_amend_attempt(api, world, text), 200)
        assert amended["amend_count"] == index
    return world


class TestDietaryAmendLimitAfterThreeAmendments:
    """The reject-and-amend cycle is a real loop, and it is capped at three."""

    def test_each_of_the_three_amendments_reopens_the_note_and_credits_the_count(
        self, api
    ):
        """Three cycles run, each clearing the rejection and crediting the count.

        "A successful amendment credits `amend_count` by 1, clears both
        `reject_reason_code` and `acked_by_user_id` back to null, and re-derives
        `prep_minutes` from the amended severity."

        Design: Corner/validations/violation_to_error_dietary_amend_limit_after_three_amendments
        """
        world = _note_world(api)
        assert world["note"]["ack_status"] == "PENDING"
        assert world["note"]["amend_count"] == 0

        for index, text in enumerate(AMENDMENT_TEXTS, start=1):
            rejected = FX.reject_note(api, world["restaurant_id"], world["note_id"])
            assert rejected["ack_status"] == "PREP_REJECTED"
            assert rejected["reject_reason_code"] == "CROSS_CONTAMINATION_RISK"

            amended = get_success_data(_amend_attempt(api, world, text), 200)
            assert amended["ack_status"] == "PENDING"
            assert amended["reject_reason_code"] is None
            assert amended["acked_by_user_id"] is None
            assert amended["amend_count"] == index
            assert amended["note_text"] == text
            # An ALLERGY note costs the kitchen 6 minutes on top of the 24 the
            # two covers cost, and an amendment that keeps the severity keeps it.
            assert amended["prep_minutes"] == 6
            reservation = FX.read_reservation(
                api, world["reservation_id"], world["guest_headers"]
            )
            assert reservation["prep_minutes_total"] == 30

    def test_the_fourth_amendment_is_refused_and_the_note_stays_rejected(self, api):
        """With three amendments spent, a fourth is refused on the cap.

        "It is permitted only while the note is `PREP_REJECTED` and only while
        `amend_count` is strictly below 3 — a fourth attempt is refused with
        `ERR_DIETARY_AMEND_LIMIT`."

        Design: Corner/validations/violation_to_error_dietary_amend_limit_after_three_amendments
        """
        world = _note_world(api)
        _exhaust_the_amend_budget(api, world)

        # A fourth rejection is still legal — only the guest's answer to it is
        # out of budget.
        FX.reject_note(api, world["restaurant_id"], world["note_id"])
        refused = _amend_attempt(api, world, "Fourth amendment: nothing left to say.")
        validate_error(refused, ERR_DIETARY_AMEND_LIMIT, 422)

        note = FX.read_note(api, world["note_id"], world["guest_headers"])
        assert note["ack_status"] == "PREP_REJECTED"
        assert note["amend_count"] == 3
        assert note["note_text"] == AMENDMENT_TEXTS[-1]
        assert note["reject_reason_code"] == "CROSS_CONTAMINATION_RISK"
        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        assert reservation["prep_minutes_total"] == 30


class TestUnauthorizedBeatsPaginationAndNotFoundBeatsState:
    """Two requests carrying two violations each, answered by whichever check
    the ladder reaches first."""

    def test_a_role_that_may_not_list_is_refused_before_its_pagination_is_read(
        self, api
    ):
        """A Guest asking for an illegal page size is told about the role.

        "If the acting role is not among the roles listed for the endpoint being
        called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/priority_ordering_unauthorized_beats_pagination_and_not_found_beats_state
        """
        FX.set_clock(api, SETUP_CLOCK)
        guest = FX.create_guest(api, display_name="Listing Guest")

        refused = api.list_guests(make_guest_headers(guest["id"]), {"limit": 0})
        validate_error(refused, ERR_UNAUTHORIZED, 403)

    def test_the_pagination_bounds_answer_once_the_role_is_allowed(self, api):
        """Each bound is refused one step outside and accepted at its extreme.

        "A `limit` below 1 or above 100, or an `offset` below 0, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/priority_ordering_unauthorized_beats_pagination_and_not_found_beats_state
        """
        FX.set_clock(api, SETUP_CLOCK)
        guest = FX.create_guest(api, display_name="Listing Guest")

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(
                api.list_guests(ADMIN_HEADERS, params), ERR_INVALID_PAGINATION, 400
            )

        rows, meta = validate_paginated(
            api.list_guests(ADMIN_HEADERS, {"limit": 100, "offset": 0})
        )
        A.assert_pagination_meta(
            meta, limit=100, offset=0, total_count=1, has_more=False
        )
        assert [row["id"] for row in rows] == [guest["id"]]

    def test_a_missing_body_foreign_key_answers_before_the_body_shape(self, api):
        """A create naming a restaurant that does not exist is a not-found, even
        though its seating window is also inverted.

        "Where a path contains an identifier, and where the body contains foreign
        keys, identifiers are validated **left to right in the order they appear
        in the path, and then in the order the body declares them**, and the
        first identifier that resolves to nothing determines the error."

        Design: Corner/validations/priority_ordering_unauthorized_beats_pagination_and_not_found_beats_state
        """
        FX.set_clock(api, SETUP_CLOCK)
        missing_restaurant_id = "rst-00000000-0000-4000-8000-000000000000"

        refused = api.create_service(
            F.service_payload(
                missing_restaurant_id,
                # The window is inverted as well: the end falls before the start.
                seating_start_utc=SEATING_END,
                seating_end_utc=SEATING_START,
            ),
            make_restaurant_headers(missing_restaurant_id),
        )
        validate_error(refused, ERR_RESTAURANT_NOT_FOUND, 404)


def _bound_world(api):
    """A fully paid party of two held by one guest, a recipient guest, a table,
    and a bread service whose orders close when transfers do."""
    world = _standard_chain(
        api,
        max_name_changes=1,
        name_change_cutoff_minutes=240,
        transfer_cutoff_minutes=1440,
        max_transfers_per_guest=2,
        prep_lead_minutes=45,
    )
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    world["add_on"] = FX.create_add_on(
        api,
        world["restaurant_id"],
        name="Bread Service",
        price_cents=100,
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=1440,
    )
    world["table"] = FX.create_table(
        api, world["restaurant_id"], seats_min=1, seats_max=8
    )
    holder = FX.create_guest(api, display_name="Bound Holder")
    recipient = FX.create_guest(api, display_name="Bound Recipient")
    world["holder"] = holder
    world["recipient"] = recipient
    world["holder_headers"] = make_guest_headers(holder["id"])
    world["recipient_headers"] = make_guest_headers(recipient["id"])
    world["reservation"] = FX.fully_paid_reservation(
        api, world["ticket_class_id"], holder["id"], party_size=2
    )
    return world


def _transfer_at_the_cutoff(api, world):
    """Hand the ticket on at the last legal instant and return the successor."""
    FX.set_clock(api, DAY_OUT_CUTOFF_INSTANT)
    return get_success_data(
        api.transfer_reservation(
            world["reservation"]["id"],
            F.transfer_payload(world["recipient"]["id"]),
            world["holder_headers"],
        ),
        201,
    )


def _order_the_add_on_at_the_cutoff(api, world, successor_id):
    """Order two units at the add-on's own last legal instant."""
    version = FX.reservation_version(api, successor_id, world["recipient_headers"])
    return api.append_add_on_line(
        successor_id,
        F.add_on_line_payload(world["add_on"]["id"], version, qty=2),
        world["recipient_headers"],
    )


class TestEveryGuardSatisfiedAtItsExactBound:
    """One ticket walked from transfer to completion, meeting each temporal guard
    on the exact instant that guard admits."""

    def test_the_transfer_and_the_add_on_both_land_on_the_shared_cutoff_instant(
        self, api
    ):
        """Seating minus 1440 minutes is legal for the transfer and for the order.

        "A `TRANSFER_OUT` `PaymentTransaction` for the full `amount_paid_cents` is
        written against the predecessor and a matching `TRANSFER_IN` row against
        the successor, both carrying `memo_code` `TRANSFER_MOVE`, so that cash is
        conserved exactly across the pair and neither the restaurant nor the
        platform gains or loses a cent."

        Design: Corner/validations/satisfaction_to_pass_every_guard_satisfied_at_its_exact_bound
        """
        world = _bound_world(api)
        successor = _transfer_at_the_cutoff(api, world)

        A.assert_fulfillment_status(successor, "CONFIRMED")
        A.assert_payment_status(successor, "FULLY_PAID")
        assert successor["guest_id"] == world["recipient"]["id"]
        assert (
            successor["transferred_from_reservation_id"]
            == world["reservation"]["id"]
        )
        assert successor["name_change_count"] == 0
        A.assert_money_breakdown(
            successor,
            ticket_subtotal=24000,
            grand_total=GRAND_TOTAL,
            amount_paid=GRAND_TOTAL,
            refunded=0,
            forfeited=0,
        )

        predecessor = FX.read_reservation(
            api, world["reservation"]["id"], world["holder_headers"]
        )
        A.assert_fulfillment_status(predecessor, "TRANSFERRED_OUT")
        A.assert_payment_status(predecessor, "TRANSFERRED")
        out_rows = FX.ledger_rows(
            api, predecessor["id"], world["holder_headers"]
        )
        moved_out = [row for row in out_rows if row["kind"] == "TRANSFER_OUT"]
        assert len(moved_out) == 1
        assert moved_out[0]["amount_cents"] == GRAND_TOTAL
        assert moved_out[0]["memo_code"] == "TRANSFER_MOVE"

        line = get_success_data(
            _order_the_add_on_at_the_cutoff(api, world, successor["id"]), 201
        )
        assert line["qty"] == 2
        assert line["line_subtotal_cents"] == 200
        # 200 * 725 / 10000 is 14.5, rounded half up on this line alone.
        assert line["line_service_charge_cents"] == 15
        assert line["line_prep_minutes"] == 8

        extended = FX.read_reservation(
            api, successor["id"], world["recipient_headers"]
        )
        A.assert_money_breakdown(
            extended,
            ticket_subtotal=24000,
            add_on_total=200,
            service_charge=1755,
            grand_total=25955,
            amount_paid=GRAND_TOTAL,
        )
        assert extended["balance_due_cents"] == 215
        # The cash that travelled is still short of the new grand total, so the
        # money dimension reads deposit-paid rather than fully paid.
        A.assert_payment_status(extended, "DEPOSIT_PAID")

    def test_the_balance_clears_and_the_rename_lands_on_its_own_cutoff_instant(
        self, api
    ):
        """215 cents closes the gap the add-on opened, and the rename is accepted
        at seating minus 240 minutes.

        "A later payment that clears the remainder of a deposit-paid reservation
        moves it `DEPOSIT_PAID → FULLY_PAID`, writing a `BALANCE_CHARGE` row with
        `memo_code` `GUEST_BALANCE`, driving `balance_due_cents` to 0 and thereby
        unblocking both completion and transfer."

        Design: Corner/validations/satisfaction_to_pass_every_guard_satisfied_at_its_exact_bound
        """
        world = _bound_world(api)
        successor = _transfer_at_the_cutoff(api, world)
        get_success_data(
            _order_the_add_on_at_the_cutoff(api, world, successor["id"]), 201
        )

        FX.pay(api, successor["id"], world["recipient"]["id"], 215)
        paid = FX.read_reservation(
            api, successor["id"], world["recipient_headers"]
        )
        A.assert_payment_status(paid, "FULLY_PAID")
        assert paid["balance_due_cents"] == 0
        A.assert_money_breakdown(paid, grand_total=25955, amount_paid=25955)

        rows = FX.ledger_rows(api, successor["id"], world["recipient_headers"])
        balance_rows = [row for row in rows if row["kind"] == "BALANCE_CHARGE"]
        assert len(balance_rows) == 1
        assert balance_rows[0]["amount_cents"] == 215
        assert balance_rows[0]["memo_code"] == "GUEST_BALANCE"

        FX.set_clock(api, RENAME_CUTOFF_INSTANT)
        renamed = get_success_data(
            _rename(
                api,
                successor["id"],
                world["recipient"]["id"],
                "Bound Recipient Party",
            ),
            200,
        )
        assert renamed["primary_guest_name"] == "Bound Recipient Party"
        assert renamed["name_change_count"] == 1
        # A rename is not a transfer: the successor's owner is untouched.
        assert renamed["guest_id"] == world["recipient"]["id"]

    def test_seating_on_the_instant_completes_the_ticket_with_cash_conserved(
        self, api
    ):
        """The ticket seats at exactly seat_from_utc and completes fully paid.

        "Completion advances the reservation `SEATED → COMPLETED` and is the point
        at which the money dimension gates the seating dimension: the reservation
        must read `FULLY_PAID`, and any outstanding balance refuses the operation
        with `ERR_BALANCE_OUTSTANDING`."

        "Transferring a ticket therefore leaves every seat counter on the class
        untouched."

        Design: Corner/validations/satisfaction_to_pass_every_guard_satisfied_at_its_exact_bound
        """
        world = _bound_world(api)
        successor = _transfer_at_the_cutoff(api, world)
        get_success_data(
            _order_the_add_on_at_the_cutoff(api, world, successor["id"]), 201
        )
        FX.pay(api, successor["id"], world["recipient"]["id"], 215)
        FX.set_clock(api, RENAME_CUTOFF_INSTANT)
        _rename(api, successor["id"], world["recipient"]["id"], "Bound Party")

        FX.assign_table(
            api,
            world["restaurant_id"],
            successor["id"],
            world["table"]["id"],
            SEATING_START,
        )
        FX.set_clock(api, SEATING_START)
        seated = FX.seat(api, world["restaurant_id"], successor["id"])
        A.assert_fulfillment_status(seated, "SEATED")
        A.assert_instant_equals(seated["seat_to_utc"], SEAT_TO, "seat_to_utc")

        completed = FX.complete(api, world["restaurant_id"], successor["id"])
        A.assert_fulfillment_status(completed, "COMPLETED")
        A.assert_payment_status(completed, "FULLY_PAID")
        assert completed["balance_due_cents"] == 0
        # 2 covers at 12 minutes plus 4 minutes a unit over 2 units.
        assert completed["prep_minutes_total"] == 32
        assert completed["version"] > successor["version"]

        rows = FX.ledger_rows(api, successor["id"], world["recipient_headers"])
        assert sorted(row["kind"] for row in rows) == [
            "BALANCE_CHARGE",
            "TRANSFER_IN",
        ]
        assert sum(row["amount_cents"] for row in rows) == 25955
        assert not [
            row for row in rows if row["kind"] in ("FORFEITURE", "REFUND")
        ]
        A.assert_derived_ledger_figures(completed, rows)

        # The seats travelled with the successor rather than returning to the
        # pool, and nothing since has moved them.
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=2, held=0, released=0, available=18, status="OPEN"
        )
