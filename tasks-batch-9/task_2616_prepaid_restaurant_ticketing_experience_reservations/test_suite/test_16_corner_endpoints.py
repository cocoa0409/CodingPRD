"""
Endpoint-shape corner cases: the create/read/child-list contract on a table,
the pure computed read behind a price quote, the full side-effect set of the
table-assignment action, the cross-restaurant foreign-key refusals, the bulk
hold sweep, the money gates on confirmation and completion, and the filtered
listings that make a flat write model navigable.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_guest_headers,
    make_kitchen_headers,
    make_restaurant_headers,
)

# The recurring service is the Thursday of 2026-09-10, whose day-of-week factor
# is 10000 basis points, seating 22:00Z to 02:00Z the next day with a
# 150-minute turn.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
SEATING_START = "2026-09-10T22:00:00Z"
SEATING_END = "2026-09-11T02:00:00Z"
TURN_END = "2026-09-11T00:30:00Z"

# A 150-minute turn plus a 15-minute table reset frees the table at 00:45.
OCCUPANCY_END = "2026-09-11T00:45:00Z"
INSIDE_OCCUPANCY = "2026-09-11T00:00:00Z"

# A 12000-cent base on a Thursday STANDARD service, with a 1500-basis-point
# release discount and a 725-basis-point service charge, for a party of two.
STANDARD_LIST_PRICE = 12000
STANDARD_RELEASE_PRICE = 10200
TICKET_SUBTOTAL = 24000
TICKET_SERVICE_CHARGE = 1740
GRAND_TOTAL = 25740
DEPOSIT_DUE = 7722
BALANCE_DUE = 18018

# The same class re-tiered to PEAK, whose tier factor is 14500 basis points.
PEAK_LIST_PRICE = 17400
PEAK_RELEASE_PRICE = 14790
PEAK_GRAND_TOTAL = 37323
PEAK_DEPOSIT_DUE = 11197


class TestTableCreateReadAndPaginatedChildList:
    """A table is created, read back unchanged, and found by its parent."""

    def test_a_created_table_round_trips_with_its_declared_default(self, api):
        """The omitted reset interval defaults to 15 and an explicit 0 survives.

        "Each **Table** is created against its `restaurant_id` with a
        `table_code` floor-plan label that is non-empty and unique within that
        restaurant, a seat band given by `seats_min` and `seats_max` where the
        minimum is at least 1 and never above the maximum and the maximum never
        exceeds 20 seats, and a `turn_buffer_minutes` reset interval that
        defaults to 15 minutes and may run from 0 to 120." "Endpoints that
        bring a new resource into existence answer with HTTP 201; endpoints
        that read or modify an existing resource answer with HTTP 200."

        Design: Corner/endpoints/standard_crud_table_create_read_and_paginated_child_list
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api)
        manager = make_restaurant_headers(restaurant["id"])
        kitchen = make_kitchen_headers(restaurant["id"])

        payload = F.table_payload(
            restaurant["id"], table_code="A1", seats_min=2, seats_max=6
        )
        del payload["turn_buffer_minutes"]
        created = get_success_data(api.create_table(payload, manager), 201)

        A.assert_common_fields(created)
        assert created["restaurant_id"] == restaurant["id"]
        assert created["table_code"] == "A1"
        assert created["seats_min"] == 2
        assert created["seats_max"] == 6
        assert created["turn_buffer_minutes"] == C.TABLE_DEFAULTS["turn_buffer_minutes"]
        assert created["version"] == 1

        # A supplied 0 is a real value, not a missing one.
        explicit_zero = get_success_data(
            api.create_table(
                F.table_payload(
                    restaurant["id"], table_code="A2", turn_buffer_minutes=0
                ),
                manager,
            ),
            201,
        )
        assert explicit_zero["turn_buffer_minutes"] == 0

        # The read answers 200 with exactly the row that was written.
        fetched = get_success_data(api.get_table(created["id"], manager), 200)
        assert fetched == created
        # The kitchen lead of the same restaurant reads the identical row.
        assert get_success_data(api.get_table(created["id"], kitchen), 200) == created

    def test_the_parent_child_list_windows_its_own_tables_in_creation_order(
        self, api
    ):
        """The reverse index paginates and never leaks a rival's floor plan.

        "Unless a specific endpoint says otherwise, list results are ordered by
        the row's own `created_at` timestamp, ascending — oldest first." "Every
        list response carries `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope." "`total_count` is the number
        of rows matching the filter before the window is applied, and
        `has_more` is true when rows remain beyond the returned window."

        Design: Corner/endpoints/standard_crud_table_create_read_and_paginated_child_list
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api)
        rival = FX.create_restaurant(api)
        manager = make_restaurant_headers(restaurant["id"])

        tables = [FX.create_table(api, restaurant["id"]) for _ in range(3)]
        # A table of another restaurant must never appear in this index.
        FX.create_table(api, rival["id"])

        first_page, first_meta = validate_paginated(
            api.list_restaurant_tables(
                restaurant["id"], manager, {"limit": 2, "offset": 0}
            )
        )
        A.assert_pagination_meta(
            first_meta, limit=2, offset=0, total_count=3, has_more=True
        )
        assert [row["id"] for row in first_page] == [t["id"] for t in tables[:2]]
        A.assert_created_at_ascending(first_page)

        second_page, second_meta = validate_paginated(
            api.list_restaurant_tables(
                restaurant["id"], manager, {"limit": 2, "offset": 2}
            )
        )
        A.assert_pagination_meta(
            second_meta, limit=2, offset=2, total_count=3, has_more=False
        )
        assert [row["id"] for row in second_page] == [tables[2]["id"]]

        # "when it is omitted it defaults to 10"
        whole, whole_meta = validate_paginated(
            api.list_restaurant_tables(restaurant["id"], manager)
        )
        A.assert_pagination_meta(
            whole_meta,
            limit=C.DEFAULT_LIMIT,
            offset=C.DEFAULT_OFFSET,
            total_count=3,
            has_more=False,
        )
        assert [row["id"] for row in whole] == [t["id"] for t in tables]


def _pool_snapshot(ticket_class):
    """The persisted figures a read must leave exactly where it found them."""
    return {
        key: ticket_class[key]
        for key in (
            "version",
            "status",
            "seats_allocated",
            "seats_sold",
            "seats_held",
            "seats_released",
            "seats_available",
            "sell_through_bp",
            "list_price_per_cover_cents",
            "release_price_per_cover_cents",
        )
    }


def _two_class_world(api):
    """One published Thursday service carrying two classes of different bases,
    12 seats on a 12000-cent package and 8 on a 20000-cent one.
    """
    world = FX.build_world(
        api,
        clock=SETUP_CLOCK,
        publish=False,
        ticket_class={"seats_allocated": 12},
        guests=1,
    )
    dearer_package = FX.create_package(
        api, world["restaurant_id"], base_price_cents=20000
    )
    dearer_class = FX.create_ticket_class(
        api,
        world["restaurant_id"],
        world["service_id"],
        dearer_package["id"],
        seats_allocated=8,
    )
    FX.publish_service(api, world["restaurant_id"], world["service_id"])
    world["dearer_class_id"] = dearer_class["id"]
    return world


class TestPriceQuoteComputedRead:
    """The quote recomputes prices without touching a single stored figure."""

    def test_the_quote_repeats_itself_and_moves_nothing(self, api):
        """Two quotes in a row agree, and the stored class is untouched.

        "A quote request re-derives `sell_through_bp`,
        `list_price_per_cover_cents` and `release_price_per_cover_cents` from
        the current seat pool and returns the refreshed class; it persists no
        other change and moves no seat."

        Design: Corner/endpoints/computed_read_price_quote_reflects_tier_without_mutating_state
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        manager = world["manager_headers"]
        guest = make_guest_headers(world["guest_id"])

        before = _pool_snapshot(
            FX.read_ticket_class(api, world["ticket_class_id"], manager)
        )

        first = get_success_data(
            api.price_quote(world["ticket_class_id"], manager), 200
        )
        assert first["list_price_per_cover_cents"] == STANDARD_LIST_PRICE
        assert first["release_price_per_cover_cents"] == STANDARD_RELEASE_PRICE
        assert first["sell_through_bp"] == 0
        A.assert_seat_pool(first, sold=0, held=0, released=0, available=20, status="OPEN")

        # The same computed read, asked for by the guest who might buy it.
        second = get_success_data(api.price_quote(world["ticket_class_id"], guest), 200)
        assert _pool_snapshot(second) == _pool_snapshot(first)

        after = _pool_snapshot(
            FX.read_ticket_class(api, world["ticket_class_id"], manager)
        )
        assert after == before

    def test_a_new_demand_tier_re_prices_every_class_of_the_service(self, api):
        """Re-tiering moves both classes, each off its own base price.

        "Supplying a new `demand_tier` for a published service re-runs the
        per-cover pricing calculation for every one of its ticket classes,
        refreshing `list_price_per_cover_cents` and
        `release_price_per_cover_cents` across the board."

        Design: Corner/endpoints/computed_read_price_quote_reflects_tier_without_mutating_state
        """
        world = _two_class_world(api)
        manager = world["manager_headers"]

        cheaper = get_success_data(
            api.price_quote(world["ticket_class_id"], manager), 200
        )
        dearer = get_success_data(
            api.price_quote(world["dearer_class_id"], manager), 200
        )
        assert cheaper["list_price_per_cover_cents"] == STANDARD_LIST_PRICE
        assert cheaper["release_price_per_cover_cents"] == STANDARD_RELEASE_PRICE
        assert dearer["list_price_per_cover_cents"] == 20000
        assert dearer["release_price_per_cover_cents"] == 17000

        get_success_data(
            api.set_demand_tier(
                world["service_id"], F.demand_tier_payload("PEAK"), manager
            ),
            200,
        )

        cheaper = get_success_data(
            api.price_quote(world["ticket_class_id"], manager), 200
        )
        dearer = get_success_data(
            api.price_quote(world["dearer_class_id"], manager), 200
        )
        assert cheaper["list_price_per_cover_cents"] == PEAK_LIST_PRICE
        assert cheaper["release_price_per_cover_cents"] == PEAK_RELEASE_PRICE
        assert dearer["list_price_per_cover_cents"] == 29000
        assert dearer["release_price_per_cover_cents"] == 24650

        # The refreshed figures are what the stored classes now carry.
        stored = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        assert stored["list_price_per_cover_cents"] == PEAK_LIST_PRICE
        assert stored["release_price_per_cover_cents"] == PEAK_RELEASE_PRICE

    def test_a_locked_price_ignores_every_later_tier_move(self, api):
        """The booking freezes the tier it was quoted, and later moves miss it.

        "It is re-derived from five ordered steps every time a client asks a
        ticket class for a quote, and derived once more — from exactly the same
        steps — inside reservation creation, where the result is frozen onto the
        reservation as `price_locked_per_cover_cents` and never revisited."
        "Reservations that have already locked a price are untouched — a locked
        `price_locked_per_cover_cents` is never re-priced, no matter how the
        tier subsequently moves."

        Design: Corner/endpoints/computed_read_price_quote_reflects_tier_without_mutating_state
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        manager = world["manager_headers"]
        guest = make_guest_headers(world["guest_id"])

        get_success_data(
            api.set_demand_tier(
                world["service_id"], F.demand_tier_payload("PEAK"), manager
            ),
            200,
        )
        quoted = get_success_data(api.price_quote(world["ticket_class_id"], guest), 200)
        assert quoted["list_price_per_cover_cents"] == PEAK_LIST_PRICE

        reservation = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        assert reservation["price_locked_per_cover_cents"] == PEAK_LIST_PRICE
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=34800,
            add_on_total=0,
            service_charge=2523,
            grand_total=PEAK_GRAND_TOTAL,
            deposit_due=PEAK_DEPOSIT_DUE,
            amount_paid=0,
        )

        # The hold shows up in the sell-through, which is still too low to add a
        # scarcity step: "Below 5000 there is no step at all."
        held = get_success_data(api.price_quote(world["ticket_class_id"], guest), 200)
        assert held["sell_through_bp"] == 1000
        assert held["list_price_per_cover_cents"] == PEAK_LIST_PRICE

        get_success_data(
            api.set_demand_tier(
                world["service_id"], F.demand_tier_payload("STANDARD"), manager
            ),
            200,
        )
        re_quoted = get_success_data(
            api.price_quote(world["ticket_class_id"], guest), 200
        )
        assert re_quoted["list_price_per_cover_cents"] == STANDARD_LIST_PRICE
        assert re_quoted["release_price_per_cover_cents"] == STANDARD_RELEASE_PRICE

        unchanged = FX.read_reservation(api, reservation["id"], guest)
        assert unchanged["price_locked_per_cover_cents"] == PEAK_LIST_PRICE
        assert unchanged["grand_total_cents"] == PEAK_GRAND_TOTAL
        assert unchanged["deposit_due_cents"] == PEAK_DEPOSIT_DUE


class TestAssignTableAppliesEveryDeclaredSideEffect:
    """One assignment, every declared write — and nothing that is not declared."""

    def test_the_assignment_writes_its_fields_and_leaves_the_turn_end_open(self, api):
        """Assigning writes the table and the instant but not the turn's end.

        "It writes `assigned_table_id` and `seat_from_utc` onto the
        reservation, advances the reservation's `version` by one, and re-runs
        the kitchen prep aggregation." "Seating pins `seat_to_utc` to
        `seat_from_utc` plus the service's `turn_time_minutes`; until the party
        is seated, `seat_to_utc` is null."

        Design: Corner/endpoints/action_endpoint_assign_table_applies_every_declared_side_effect
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        manager = world["manager_headers"]
        table = FX.create_table(api, world["restaurant_id"], seats_min=2, seats_max=6)
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )

        assigned = get_success_data(
            api.assign_table(
                reservation["id"],
                F.assign_table_payload(table["id"], SEATING_START),
                manager,
            ),
            200,
        )
        assert assigned["assigned_table_id"] == table["id"]
        A.assert_instant_equals(assigned["seat_from_utc"], SEATING_START, "seat_from_utc")
        assert assigned["seat_to_utc"] is None
        A.assert_version_advanced_by(assigned["version"], reservation["version"], 1)
        # "a baseline of the reservation's `party_size` multiplied by the
        # package's `kitchen_prep_minutes_per_cover`"
        assert assigned["prep_minutes_total"] == C.prep_minutes_total(
            2, world["package"]["kitchen_prep_minutes_per_cover"]
        )
        A.assert_fulfillment_status(assigned, "CONFIRMED")
        A.assert_payment_status(assigned, "DEPOSIT_PAID")
        assert FX.read_reservation(api, reservation["id"], manager) == assigned

        # Only seating pins the end of the turn, 150 minutes on.
        FX.set_clock(api, SEATING_START)
        seated = FX.seat(api, world["restaurant_id"], reservation["id"])
        A.assert_fulfillment_status(seated, "SEATED")
        A.assert_instant_equals(seated["seat_to_utc"], TURN_END, "seat_to_utc")

    def test_a_rival_table_and_a_wrong_seat_band_are_both_refused(self, api):
        """Provenance is tested before the seat band, and neither writes a thing.

        "The table must also belong to the same restaurant as the reservation's
        service, failing which the assignment is rejected with
        `ERR_TABLE_RESTAURANT_MISMATCH`, and the reservation's `party_size` must
        fall within the table's `seats_min` and `seats_max` inclusive, failing
        which the rejection is `ERR_TABLE_PARTY_SIZE_MISMATCH`."

        Design: Corner/endpoints/action_endpoint_assign_table_applies_every_declared_side_effect
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        manager = world["manager_headers"]
        rival = FX.create_restaurant(api)
        rival_table = FX.create_table(api, rival["id"], seats_min=1, seats_max=8)
        narrow_table = FX.create_table(
            api, world["restaurant_id"], seats_min=4, seats_max=6
        )
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )

        validate_error(
            api.assign_table(
                reservation["id"],
                F.assign_table_payload(rival_table["id"], SEATING_START),
                manager,
            ),
            "ERR_TABLE_RESTAURANT_MISMATCH",
        )
        validate_error(
            api.assign_table(
                reservation["id"],
                F.assign_table_payload(narrow_table["id"], SEATING_START),
                manager,
            ),
            "ERR_TABLE_PARTY_SIZE_MISMATCH",
        )

        untouched = FX.read_reservation(api, reservation["id"], manager)
        assert untouched["assigned_table_id"] is None
        assert untouched["seat_from_utc"] is None
        assert untouched["version"] == reservation["version"]

    def test_the_next_party_may_take_the_table_at_the_instant_it_is_freed(self, api):
        """00:00 collides with the first turn; 00:45, its excluded end, does not.

        "Because both comparisons are strict, a party starting at exactly the
        instant another party's occupancy ends does not collide — a table freed
        at 00:45 may be re-seated at 00:45, but not at 00:44."

        Design: Corner/endpoints/action_endpoint_assign_table_applies_every_declared_side_effect
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=2)
        manager = world["manager_headers"]
        table = FX.create_table(api, world["restaurant_id"], seats_min=1, seats_max=8)
        first = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guests"][0]["id"], party_size=2
        )
        second = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guests"][1]["id"], party_size=2
        )
        FX.assign_table(
            api, world["restaurant_id"], first["id"], table["id"], SEATING_START
        )

        validate_error(
            api.assign_table(
                second["id"],
                F.assign_table_payload(table["id"], INSIDE_OCCUPANCY),
                manager,
            ),
            "ERR_TABLE_TURN_CONFLICT",
        )

        adjacent = get_success_data(
            api.assign_table(
                second["id"],
                F.assign_table_payload(table["id"], OCCUPANCY_END),
                manager,
            ),
            200,
        )
        assert adjacent["assigned_table_id"] == table["id"]
        A.assert_instant_equals(adjacent["seat_from_utc"], OCCUPANCY_END, "seat_from_utc")


class TestCrossReferenceMustShareTheRestaurant:
    """A link is only legal when both ends belong to the same restaurant."""

    def test_a_package_of_another_restaurant_cannot_be_allocated_seats(self, api):
        """A missing package is a 404; a rival's package is a 422 mismatch.

        "Every foreign key in the request body references an existing row, on
        every create carrying foreign keys — otherwise the matching not-found
        code from §2.9." "The package must belong to the same restaurant as the
        service, or the allocation fails with
        `ERR_PACKAGE_RESTAURANT_MISMATCH`."

        Design: Corner/endpoints/cross_reference_link_package_and_add_on_must_share_the_restaurant
        """
        world = FX.build_world(
            api,
            clock=SETUP_CLOCK,
            publish=False,
            ticket_class={"seats_allocated": 4},
            guests=0,
        )
        manager = world["manager_headers"]
        rival = FX.create_restaurant(api)
        rival_package = FX.create_package(api, rival["id"])

        validate_error(
            api.create_ticket_class(
                F.ticket_class_payload(
                    world["service_id"], NON_EXISTENT_UUID, seats_allocated=4
                ),
                manager,
            ),
            "ERR_PACKAGE_NOT_FOUND",
        )
        validate_error(
            api.create_ticket_class(
                F.ticket_class_payload(
                    world["service_id"], rival_package["id"], seats_allocated=4
                ),
                manager,
            ),
            "ERR_PACKAGE_RESTAURANT_MISMATCH",
        )

        # Neither refusal left a half-allocated class behind.
        classes, meta = validate_paginated(
            api.list_ticket_classes(manager, {"service_id": world["service_id"]})
        )
        A.assert_pagination_meta(
            meta,
            limit=C.DEFAULT_LIMIT,
            offset=C.DEFAULT_OFFSET,
            total_count=1,
            has_more=False,
        )
        assert classes[0]["id"] == world["ticket_class_id"]
        assert classes[0]["package_id"] == world["package_id"]

    def test_an_add_on_of_another_restaurant_cannot_be_appended(self, api):
        """The missing add-on fails first; the rival's add-on fails next.

        "The add-on must belong to the same restaurant as the reservation's
        service, failing which the append is rejected with
        `ERR_ADDON_RESTAURANT_MISMATCH`."

        Design: Corner/endpoints/cross_reference_link_package_and_add_on_must_share_the_restaurant
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        guest = make_guest_headers(world["guest_id"])
        rival = FX.create_restaurant(api)
        rival_add_on = FX.create_add_on(api, rival["id"], price_cents=100)
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        version = reservation["version"]

        validate_error(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(NON_EXISTENT_UUID, version),
                guest,
            ),
            "ERR_ADDON_NOT_FOUND",
        )
        validate_error(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(rival_add_on["id"], version),
                guest,
            ),
            "ERR_ADDON_RESTAURANT_MISMATCH",
        )

        untouched = FX.read_reservation(api, reservation["id"], guest)
        assert untouched["version"] == version
        assert untouched["add_on_total_cents"] == 0
        assert untouched["grand_total_cents"] == GRAND_TOTAL
        lines, meta = validate_paginated(
            api.list_reservation_add_ons(guest, {"reservation_id": reservation["id"]})
        )
        assert lines == []
        assert meta["total_count"] == 0

    def test_the_add_on_of_the_same_restaurant_links_and_re_prices_the_booking(
        self, api
    ):
        """The legal link freezes its own figures and moves the booking exactly once.

        "On success the line freezes `unit_price_cents_locked` from the add-on's
        current `price_cents`, so that later catalogue price edits never disturb
        an existing booking; copies `requires_kitchen_ack` onto the line as
        `ack_required`; derives `line_subtotal_cents`,
        `line_service_charge_cents` and `line_prep_minutes` — the last being the
        add-on's `prep_minutes_per_unit` multiplied by `qty`; re-runs the whole
        charge breakdown with per-line rounding; re-runs the kitchen prep
        aggregation of §3.4; and advances the reservation's `version` by one."

        Design: Corner/endpoints/cross_reference_link_package_and_add_on_must_share_the_restaurant
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        guest = make_guest_headers(world["guest_id"])
        add_on = FX.create_add_on(
            api,
            world["restaurant_id"],
            price_cents=100,
            prep_minutes_per_unit=5,
            requires_kitchen_ack=True,
        )
        reservation = FX.confirmed_reservation(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        version = reservation["version"]

        line = get_success_data(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(add_on["id"], version, qty=1),
                guest,
            ),
            201,
        )
        assert line["reservation_id"] == reservation["id"]
        assert line["add_on_id"] == add_on["id"]
        assert line["unit_price_cents_locked"] == 100
        assert line["ack_required"] is True
        assert line["line_subtotal_cents"] == 100
        # 100 cents at 725 basis points is 7.25, rounded half up on this line
        # alone.
        assert line["line_service_charge_cents"] == 7
        assert line["line_prep_minutes"] == 5

        moved = FX.read_reservation(api, reservation["id"], guest)
        A.assert_version_advanced_by(moved["version"], version, 1)
        A.assert_money_breakdown(
            moved,
            ticket_subtotal=TICKET_SUBTOTAL,
            add_on_total=100,
            service_charge=TICKET_SERVICE_CHARGE + 7,
            grand_total=TICKET_SUBTOTAL + 100 + TICKET_SERVICE_CHARGE + 7,
            deposit_due=DEPOSIT_DUE,
            amount_paid=DEPOSIT_DUE,
        )
        assert moved["prep_minutes_total"] == C.prep_minutes_total(
            2,
            world["package"]["kitchen_prep_minutes_per_cover"],
            add_on_lines=((5, 1),),
        )

        # Both ends of the link are readable from the flat write model.
        assert get_success_data(api.get_reservation_add_on(line["id"], guest), 200) == line
        lines, meta = validate_paginated(
            api.list_reservation_add_ons(guest, {"reservation_id": reservation["id"]})
        )
        A.assert_pagination_meta(
            meta,
            limit=C.DEFAULT_LIMIT,
            offset=C.DEFAULT_OFFSET,
            total_count=1,
            has_more=False,
        )
        assert lines[0]["id"] == line["id"]


# The sweep world's timeline: holds are taken at 00:00 against a 20-minute
# hold TTL, one more is taken at 00:20, and the sweep runs at 00:25.
HOLD_TAKEN_AT = "2026-09-10T00:00:00Z"
LATER_HOLD_TAKEN_AT = "2026-09-10T00:20:00Z"
SWEEP_AT = "2026-09-10T00:25:00Z"


def _sweep_world(api):
    """Four bookings on one 20-seat class: a paid hold and an unpaid hold that
    have both lapsed, a confirmed booking, and a hold taken late enough to
    still be live when the sweep runs.
    """
    world = FX.build_world(api, clock=SETUP_CLOCK, guests=4)
    lapsed_guest, booked_guest, unpaid_guest, live_guest = world["guests"]

    FX.set_clock(api, HOLD_TAKEN_AT)
    lapsed_paid = FX.deposit_paid_reservation(
        api, world["ticket_class_id"], lapsed_guest["id"], party_size=2
    )
    lapsed_unpaid = FX.hold_seats(
        api, world["ticket_class_id"], unpaid_guest["id"], party_size=3
    )
    booked = FX.confirmed_reservation(
        api, world["ticket_class_id"], booked_guest["id"], party_size=2
    )

    # "`hold_expires_at_utc` is set to the logical clock plus the restaurant's
    # `hold_ttl_minutes`", so a hold taken at 00:20 still has five minutes left
    # when the sweep fires at 00:25.
    FX.set_clock(api, LATER_HOLD_TAKEN_AT)
    live_hold = FX.hold_seats(
        api, world["ticket_class_id"], live_guest["id"], party_size=2
    )
    FX.set_clock(api, SWEEP_AT)

    world["lapsed_paid"] = lapsed_paid
    world["lapsed_unpaid"] = lapsed_unpaid
    world["booked"] = booked
    world["live_hold"] = live_hold
    world["lapsed_guest"] = lapsed_guest
    world["unpaid_guest"] = unpaid_guest
    return world


class TestHoldSweepExpiresOnlyTheLapsedHolds:
    """The sweep is surgical: lapsed holds die, everything else is untouched."""

    def test_the_sweep_moves_the_lapsed_rows_and_nothing_else(self, api):
        """Both lapsed holds expire; the booking and the live hold stay identical.

        "The sweep advances every `PENDING` reservation whose
        `hold_expires_at_utc` the logical clock has reached along `PENDING →
        EXPIRED`." "For each swept reservation it debits `party_size` from
        `seats_held` and returns those seats **to the pool they came from** — to
        `seats_released` when the reservation's `is_release_priced` is true, and
        to `seats_available` otherwise, which is the whole reason that flag is
        persisted on the reservation."

        Design: Corner/endpoints/bulk_action_hold_sweep_expires_only_the_lapsed_holds
        """
        world = _sweep_world(api)
        manager = world["manager_headers"]

        before_class = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            before_class, sold=2, held=7, released=0, available=11, status="OPEN"
        )
        booked_before = FX.read_reservation(api, world["booked"]["id"], manager)
        live_before = FX.read_reservation(api, world["live_hold"]["id"], manager)

        FX.sweep_holds(api, world["service_id"])

        # The lapsed side moved.
        A.assert_fulfillment_status(
            FX.read_reservation(api, world["lapsed_paid"]["id"], manager), "EXPIRED"
        )
        A.assert_fulfillment_status(
            FX.read_reservation(api, world["lapsed_unpaid"]["id"], manager), "EXPIRED"
        )

        # The untouched side did not move by so much as a version.
        assert FX.read_reservation(api, world["booked"]["id"], manager) == booked_before
        assert (
            FX.read_reservation(api, world["live_hold"]["id"], manager) == live_before
        )
        A.assert_fulfillment_status(live_before, "PENDING")
        A.assert_fulfillment_status(booked_before, "CONFIRMED")

        # Five held seats came back to ordinary availability, not to the release
        # pool, because neither lapsed hold was release-priced.
        assert world["lapsed_paid"]["is_release_priced"] is False
        assert world["lapsed_unpaid"]["is_release_priced"] is False
        after_class = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            after_class, sold=2, held=2, released=0, available=16, status="OPEN"
        )

    def test_the_lapsed_hold_is_refunded_in_full_and_the_unpaid_one_is_not(self, api):
        """A refund row appears for the paid hold only, and nothing is mutated.

        "Anything the guest had paid is refunded in full with `memo_code`
        `HOLD_LAPSE`." "When the settlement yields a retention of exactly zero —
        a 0-basis-point cancellation, a service cancellation, or a lapsed hold —
        the reservation moves to `REFUNDED`, a single `REFUND` row for the whole
        of `amount_paid_cents` is written, and `forfeited_cents` stays at 0."

        Design: Corner/endpoints/bulk_action_hold_sweep_expires_only_the_lapsed_holds
        """
        world = _sweep_world(api)
        paid_guest = make_guest_headers(world["lapsed_guest"]["id"])
        unpaid_guest = make_guest_headers(world["unpaid_guest"]["id"])

        FX.sweep_holds(api, world["service_id"])

        refunded = FX.read_reservation(api, world["lapsed_paid"]["id"], paid_guest)
        A.assert_payment_status(refunded, "REFUNDED")
        A.assert_money_breakdown(
            refunded, amount_paid=DEPOSIT_DUE, refunded=DEPOSIT_DUE, forfeited=0
        )
        A.assert_settled_ledger_identity(refunded)

        rows = FX.ledger_rows(api, world["lapsed_paid"]["id"], paid_guest)
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE", "REFUND"]
        assert [row["memo_code"] for row in rows] == ["GUEST_PREPAY", "HOLD_LAPSE"]
        assert rows[1]["amount_cents"] == DEPOSIT_DUE
        assert rows[1]["signed_amount_cents"] == -DEPOSIT_DUE
        A.assert_created_at_ascending(rows)
        for row in rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)
        A.assert_signed_sum_matches(refunded, rows)

        # The hold that never paid gets no ledger row at all.
        never_paid = FX.read_reservation(api, world["lapsed_unpaid"]["id"], unpaid_guest)
        A.assert_payment_status(never_paid, "UNPAID")
        A.assert_money_breakdown(never_paid, amount_paid=0, refunded=0, forfeited=0)
        assert FX.ledger_rows(api, world["lapsed_unpaid"]["id"], unpaid_guest) == []

    def test_closing_waits_for_the_sweep_and_is_refused_a_second_time(self, api):
        """close_service is honoured once the last hold is swept, and never twice.

        "Passing `close_service` as true additionally moves the service
        `PUBLISHED → CLOSED`." "That requires the service to be `PUBLISHED`, the
        logical clock to be at or after the service's `seating_end_utc`, and no
        reservation of the service to remain in `PENDING` — which is why the
        sweep runs first, in the same call." "Closing moves every `TicketClass`
        of the service to `CLOSED` and recomputes the service's
        `net_settled_cents` as `gross_charged_cents` less `refunded_cents`."

        Design: Corner/endpoints/bulk_action_hold_sweep_expires_only_the_lapsed_holds
        """
        world = _sweep_world(api)
        manager = world["manager_headers"]

        FX.sweep_holds(api, world["service_id"])
        assert FX.read_service(api, world["service_id"], manager)["status"] == "PUBLISHED"

        # At the seating end the last live hold has lapsed too, so the same call
        # sweeps it and then closes.
        FX.set_clock(api, SEATING_END)
        FX.sweep_holds(api, world["service_id"], close_service=True)

        A.assert_fulfillment_status(
            FX.read_reservation(api, world["live_hold"]["id"], manager), "EXPIRED"
        )
        service = FX.read_service(api, world["service_id"], manager)
        assert service["status"] == "CLOSED"
        assert service["net_settled_cents"] == (
            service["gross_charged_cents"] - service["refunded_cents"]
        )
        closed_class = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            closed_class, sold=2, held=0, released=0, available=18, status="CLOSED"
        )

        validate_error(
            api.hold_sweep(
                world["service_id"], ADMIN_HEADERS, {"close_service": True}
            ),
            "ERR_SERVICE_INVALID_STATE",
        )


class TestConfirmAndCompleteGateOnTheMoneyDimension:
    """Two conditional actions, each refused until the money says otherwise."""

    def test_confirmation_waits_for_a_deposit_that_is_large_enough(self, api):
        """An unpaid hold cannot confirm, and a cent short is not a deposit.

        "It requires the reservation to still be `PENDING`, the logical clock to
        be strictly before `hold_expires_at_utc`, the money dimension to read
        `DEPOSIT_PAID` or `FULLY_PAID` — a still-`UNPAID` reservation is refused
        with `ERR_DEPOSIT_NOT_SETTLED` — and the owning ticket class not to be
        `CLOSED`." "A payment may never exceed the reservation's
        `balance_due_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`), and the very first
        payment on a reservation must be at least `deposit_due_cents`
        (`ERR_PAYMENT_BELOW_DEPOSIT`)."

        Design: Corner/endpoints/conditional_action_confirm_and_complete_gate_on_the_money_dimension
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        manager = world["manager_headers"]
        guest = make_guest_headers(world["guest_id"])
        reservation = FX.hold_seats(
            api, world["ticket_class_id"], world["guest_id"], party_size=2
        )
        A.assert_payment_status(reservation, "UNPAID")
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=TICKET_SUBTOTAL,
            add_on_total=0,
            service_charge=TICKET_SERVICE_CHARGE,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
            amount_paid=0,
        )

        validate_error(
            api.confirm_reservation(reservation["id"], guest),
            "ERR_DEPOSIT_NOT_SETTLED",
        )
        validate_error(
            api.take_payment(
                reservation["id"], F.payment_payload(GRAND_TOTAL + 1), guest
            ),
            "ERR_PAYMENT_EXCEEDS_BALANCE",
        )
        validate_error(
            api.take_payment(
                reservation["id"], F.payment_payload(DEPOSIT_DUE - 1), guest
            ),
            "ERR_PAYMENT_BELOW_DEPOSIT",
        )

        # Exactly the deposit settles it, and confirmation is then available.
        FX.pay(api, reservation["id"], world["guest_id"], DEPOSIT_DUE)
        settled = FX.read_reservation(api, reservation["id"], guest)
        A.assert_payment_status(settled, "DEPOSIT_PAID")
        assert settled["deposit_frozen"] is True
        assert settled["balance_due_cents"] == BALANCE_DUE
        assert [
            (row["kind"], row["memo_code"], row["amount_cents"])
            for row in FX.ledger_rows(api, reservation["id"], guest)
        ] == [("DEPOSIT_CHARGE", "GUEST_PREPAY", DEPOSIT_DUE)]

        confirmed = FX.confirm(api, reservation["id"], world["guest_id"])
        A.assert_fulfillment_status(confirmed, "CONFIRMED")
        A.assert_payment_status(confirmed, "DEPOSIT_PAID")
        assert confirmed["hold_expires_at_utc"] is None
        A.assert_version_advanced_by(confirmed["version"], settled["version"], 1)
        A.assert_seat_pool(
            FX.read_ticket_class(api, world["ticket_class_id"], manager),
            sold=2,
            held=0,
            released=0,
            available=18,
            status="OPEN",
        )

    def test_completion_waits_for_the_balance_but_seating_does_not(self, api):
        """A deposit-paid party may be seated, but never completed.

        "It requires the reservation to be `CONFIRMED`, `assigned_table_id` to be
        non-null, every `ANAPHYLAXIS` note to be `ACKED`, no note to be in
        `PREP_REJECTED`, and the logical clock to have reached `seat_from_utc` —
        an attempt before that instant is refused with `ERR_SEATING_TOO_EARLY`."
        "Completion advances the reservation `SEATED → COMPLETED` and is the
        point at which the money dimension gates the seating dimension: the
        reservation must read `FULLY_PAID`, and any outstanding balance refuses
        the operation with `ERR_BALANCE_OUTSTANDING`." "A later payment that
        clears the remainder of a deposit-paid reservation moves it
        `DEPOSIT_PAID → FULLY_PAID`, writing a `BALANCE_CHARGE` row with
        `memo_code` `GUEST_BALANCE`, driving `balance_due_cents` to 0 and thereby
        unblocking both completion and transfer."

        Design: Corner/endpoints/conditional_action_confirm_and_complete_gate_on_the_money_dimension
        """
        world = FX.build_world(api, clock=SETUP_CLOCK, guests=1)
        manager = world["manager_headers"]
        guest = make_guest_headers(world["guest_id"])
        table = FX.create_table(api, world["restaurant_id"], seats_min=1, seats_max=8)
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

        # The seating dimension advances with a balance still outstanding.
        FX.set_clock(api, SEATING_START)
        seated = FX.seat(api, world["restaurant_id"], reservation["id"])
        A.assert_fulfillment_status(seated, "SEATED")
        A.assert_payment_status(seated, "DEPOSIT_PAID")
        A.assert_instant_equals(seated["seat_to_utc"], TURN_END, "seat_to_utc")
        assert seated["balance_due_cents"] == BALANCE_DUE

        validate_error(
            api.complete_reservation(reservation["id"], manager),
            "ERR_BALANCE_OUTSTANDING",
        )

        FX.pay(api, reservation["id"], world["guest_id"], BALANCE_DUE)
        cleared = FX.read_reservation(api, reservation["id"], guest)
        A.assert_payment_status(cleared, "FULLY_PAID")
        assert cleared["balance_due_cents"] == 0
        rows = FX.ledger_rows(api, reservation["id"], guest)
        assert [
            (row["kind"], row["memo_code"], row["amount_cents"]) for row in rows
        ] == [
            ("DEPOSIT_CHARGE", "GUEST_PREPAY", DEPOSIT_DUE),
            ("BALANCE_CHARGE", "GUEST_BALANCE", BALANCE_DUE),
        ]
        A.assert_created_at_ascending(rows)
        A.assert_signed_sum_matches(cleared, rows)
        assert sum(row["signed_amount_cents"] for row in rows) == GRAND_TOTAL

        completed = FX.complete(api, world["restaurant_id"], reservation["id"])
        A.assert_fulfillment_status(completed, "COMPLETED")
        A.assert_payment_status(completed, "FULLY_PAID")
        A.assert_version_advanced_by(completed["version"], cleared["version"], 1)


def _flat_world(api):
    """One service carrying a transferred pair and a third hold, a table
    assigned to the successor, and one waiting guest — every child of the
    topology reachable only by filtering a collection.
    """
    world = FX.build_world(api, clock=SETUP_CLOCK, guests=4)
    holder, recipient, third_guest, waiter = world["guests"]

    predecessor = FX.hold_seats(
        api, world["ticket_class_id"], holder["id"], party_size=2
    )
    FX.pay(api, predecessor["id"], holder["id"], DEPOSIT_DUE)
    FX.pay(api, predecessor["id"], holder["id"], BALANCE_DUE)
    FX.confirm(api, predecessor["id"], holder["id"])
    successor = get_success_data(
        api.transfer_reservation(
            predecessor["id"],
            F.transfer_payload(recipient["id"]),
            make_guest_headers(holder["id"]),
        )
    )
    third = FX.hold_seats(
        api, world["ticket_class_id"], third_guest["id"], party_size=2
    )

    table = FX.create_table(api, world["restaurant_id"], seats_min=1, seats_max=8)
    FX.assign_table(
        api, world["restaurant_id"], successor["id"], table["id"], SEATING_START
    )
    entry = FX.join_waitlist(
        api,
        world["service_id"],
        waiter["id"],
        party_size=2,
        requested_package_id=world["package_id"],
    )

    world["holder"] = holder
    world["recipient"] = recipient
    world["waiter"] = waiter
    world["predecessor"] = predecessor
    world["successor"] = successor
    world["third"] = third
    world["table"] = table
    world["entry"] = entry
    return world


class TestFilteredListsReachEveryChild:
    """Nothing is nested, so every child is found by filtering its collection."""

    def test_the_reservation_listing_windows_and_indexes_every_declared_filter(
        self, api
    ):
        """Two pages of three rows, then each declared foreign key as an index.

        "Because writes are flat, every foreign key in the model is nonetheless
        discoverable by reading." "All list endpoints accept the `limit` and
        `offset` query parameters of §2.3, and every filter listed in a list
        endpoint's description is an optional query parameter that narrows the
        result set; combining several filters narrows it further, and each filter
        also serves as the reverse index by which children of a parent are
        discovered."

        Design: Corner/endpoints/standard_crud_filtered_lists_reach_every_child_across_the_flat_topology
        """
        world = _flat_world(api)
        manager = world["manager_headers"]
        expected_order = [
            world["predecessor"]["id"],
            world["successor"]["id"],
            world["third"]["id"],
        ]

        first_page, first_meta = validate_paginated(
            api.list_reservations(manager, {"limit": 2, "offset": 0})
        )
        A.assert_pagination_meta(
            first_meta, limit=2, offset=0, total_count=3, has_more=True
        )
        assert [row["id"] for row in first_page] == expected_order[:2]
        A.assert_created_at_ascending(first_page)

        second_page, second_meta = validate_paginated(
            api.list_reservations(manager, {"limit": 2, "offset": 2})
        )
        A.assert_pagination_meta(
            second_meta, limit=2, offset=2, total_count=3, has_more=False
        )
        assert [row["id"] for row in second_page] == expected_order[2:]

        by_guest, _ = validate_paginated(
            api.list_reservations(manager, {"guest_id": world["recipient"]["id"]})
        )
        assert [row["id"] for row in by_guest] == [world["successor"]["id"]]

        by_predecessor, _ = validate_paginated(
            api.list_reservations(
                manager,
                {"transferred_from_reservation_id": world["predecessor"]["id"]},
            )
        )
        assert [row["id"] for row in by_predecessor] == [world["successor"]["id"]]

        by_table, _ = validate_paginated(
            api.list_reservations(
                manager, {"assigned_table_id": world["table"]["id"]}
            )
        )
        assert [row["id"] for row in by_table] == [world["successor"]["id"]]

        by_class, class_meta = validate_paginated(
            api.list_reservations(
                manager, {"ticket_class_id": world["ticket_class_id"]}
            )
        )
        A.assert_pagination_meta(
            class_meta,
            limit=C.DEFAULT_LIMIT,
            offset=C.DEFAULT_OFFSET,
            total_count=3,
            has_more=False,
        )
        assert [row["id"] for row in by_class] == expected_order

        by_service, _ = validate_paginated(
            api.list_reservations(manager, {"service_id": world["service_id"]})
        )
        assert [row["id"] for row in by_service] == expected_order

        # Combining two filters narrows it further.
        combined, combined_meta = validate_paginated(
            api.list_reservations(
                manager,
                {
                    "service_id": world["service_id"],
                    "guest_id": world["holder"]["id"],
                },
            )
        )
        assert [row["id"] for row in combined] == [world["predecessor"]["id"]]
        assert combined_meta["total_count"] == 1

    def test_the_ledger_and_the_other_child_listings_reach_both_sides(self, api):
        """Each reservation's ledger replays in creation order, and the reverse
        indexes over waitlist entries and dietary notes answer too.

        "A restaurant exposes reverse indexes over its tables, experience
        packages, add-ons and services; a reservation exposes a reverse index
        over its dietary notes; and the collection listings for ticket classes,
        reservations, add-on lines, ledger rows, waitlist entries, refund
        exceptions and goodwill credits all accept filters on the foreign keys
        that point at them." "This applies to the payment ledger listing as
        well, whose deterministic replay order is exactly that ascending
        creation order." "A `TRANSFER_OUT` `PaymentTransaction` for the full
        `amount_paid_cents` is written against the predecessor and a matching
        `TRANSFER_IN` row against the successor, both carrying `memo_code`
        `TRANSFER_MOVE`, so that cash is conserved exactly across the pair and
        neither the restaurant nor the platform gains or loses a cent."

        Design: Corner/endpoints/standard_crud_filtered_lists_reach_every_child_across_the_flat_topology
        """
        world = _flat_world(api)
        manager = world["manager_headers"]
        holder = make_guest_headers(world["holder"]["id"])
        recipient = make_guest_headers(world["recipient"]["id"])

        predecessor_rows = FX.ledger_rows(api, world["predecessor"]["id"], holder)
        assert [
            (row["kind"], row["memo_code"], row["amount_cents"])
            for row in predecessor_rows
        ] == [
            ("DEPOSIT_CHARGE", "GUEST_PREPAY", DEPOSIT_DUE),
            ("BALANCE_CHARGE", "GUEST_BALANCE", BALANCE_DUE),
            ("TRANSFER_OUT", "TRANSFER_MOVE", GRAND_TOTAL),
        ]
        A.assert_created_at_ascending(predecessor_rows)

        successor_rows = FX.ledger_rows(api, world["successor"]["id"], recipient)
        assert [
            (row["kind"], row["memo_code"], row["amount_cents"])
            for row in successor_rows
        ] == [("TRANSFER_IN", "TRANSFER_MOVE", GRAND_TOTAL)]

        for row in predecessor_rows + successor_rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)
        # Cash is conserved exactly across the pair.
        assert predecessor_rows[2]["signed_amount_cents"] == -GRAND_TOTAL
        assert successor_rows[0]["signed_amount_cents"] == GRAND_TOTAL
        assert (
            predecessor_rows[2]["signed_amount_cents"]
            + successor_rows[0]["signed_amount_cents"]
        ) == 0

        entries, entry_meta = validate_paginated(
            api.list_waitlist_entries(manager, {"service_id": world["service_id"]})
        )
        A.assert_pagination_meta(
            entry_meta,
            limit=C.DEFAULT_LIMIT,
            offset=C.DEFAULT_OFFSET,
            total_count=1,
            has_more=False,
        )
        assert entries[0]["id"] == world["entry"]["id"]
        by_waiter, _ = validate_paginated(
            api.list_waitlist_entries(manager, {"guest_id": world["waiter"]["id"]})
        )
        assert [row["id"] for row in by_waiter] == [world["entry"]["id"]]
        by_package, _ = validate_paginated(
            api.list_waitlist_entries(
                manager, {"requested_package_id": world["package_id"]}
            )
        )
        assert [row["id"] for row in by_package] == [world["entry"]["id"]]

        # A child listing with no children still answers with the full envelope.
        notes, notes_meta = validate_paginated(
            api.list_reservation_dietary_notes(world["predecessor"]["id"], manager)
        )
        assert notes == []
        A.assert_pagination_meta(
            notes_meta,
            limit=C.DEFAULT_LIMIT,
            offset=C.DEFAULT_OFFSET,
            total_count=0,
            has_more=False,
        )
