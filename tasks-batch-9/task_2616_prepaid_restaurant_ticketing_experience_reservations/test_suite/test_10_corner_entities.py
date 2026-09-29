"""
Entity-level corner cases: what a create persists, what an omitted field falls
back to, what the server computes for itself, what a read returns, how a
collection pages, and which rejection a bad identifier or a foreign scope earns.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import (
    ERR_ADDON_NOT_FOUND,
    ERR_ADDON_RESTAURANT_MISMATCH,
    ERR_DIETARY_NOTE_NOT_FOUND,
    ERR_GOODWILL_CREDIT_NOT_FOUND,
    ERR_GUEST_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_PACKAGE_NOT_FOUND,
    ERR_PACKAGE_RESTAURANT_MISMATCH,
    ERR_PAYMENT_TRANSACTION_NOT_FOUND,
    ERR_REFUND_EXCEPTION_NOT_FOUND,
    ERR_RESERVATION_ADDON_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_RESTAURANT_NOT_FOUND,
    ERR_SERVICE_NOT_FOUND,
    ERR_TABLE_NOT_FOUND,
    ERR_TABLE_RESTAURANT_MISMATCH,
    ERR_TICKET_CLASS_NOT_FOUND,
    ERR_VALIDATION,
    ERR_WAITLIST_ENTRY_NOT_FOUND,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CARE_HEADERS,
    make_guest_headers,
    make_restaurant_headers,
)

# The recurring setup instant. A hold minted here lapses at 00:20:00Z under the
# default hold_ttl_minutes of 20.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
HOLD_LAPSES_AT = "2026-09-01T00:20:00Z"

# The Thursday the STD chain sells against: day-of-week factor 10000 bp against
# the STANDARD tier's 10000 bp, so a 12000-cent cover stays at 12000.
THURSDAY_DATE = "2026-09-10"
THURSDAY_SEATING_START = "2026-09-10T22:00:00Z"
THURSDAY_SEATING_END = "2026-09-11T02:00:00Z"
# The Saturday used for the stored-field read.
SATURDAY_DATE = "2026-09-12"
SATURDAY_SEATING_START = "2026-09-12T11:00:00Z"
SATURDAY_SEATING_END = "2026-09-12T15:00:00Z"

# A party of 2 at 12000 a cover: 24000 subtotal, 725 bp of that is 1740, so the
# grand total is 25740, of which 3000 bp is a 7722 deposit and 18018 balance.
LIST_PRICE = 12000
RELEASE_PRICE = 10200
TICKET_SUBTOTAL = 24000
SERVICE_CHARGE = 1740
GRAND_TOTAL = 25740
DEPOSIT_DUE = 7722
BALANCE_DUE = 18018

# Unused identifiers. None of these is ever written by the tests below.
GHOST_PACKAGE_ID = "00000000-0000-4000-8000-0000000000b1"
GHOST_GUEST_ID = "00000000-0000-4000-8000-0000000000b2"
GHOST_SERVICE_ID = "00000000-0000-4000-8000-0000000000b3"
GHOST_ADDON_ID = "00000000-0000-4000-8000-0000000000b4"
GHOST_RESERVATION_ID = "00000000-0000-4000-8000-0000000000f1"


def _bare_restaurant(api, name="Corner Defaults House"):
    """Register a restaurant with nothing but its trading name, so every
    policy knob falls back to its documented default."""
    FX.set_clock(api, SETUP_CLOCK)
    return validate_success(api.create_restaurant({"name": name}, ADMIN_HEADERS), 201)


def _three_services(api):
    """One restaurant carrying three DRAFT services, created oldest first."""
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, name="Corner Page House")
    dates = [
        (THURSDAY_DATE, THURSDAY_SEATING_START, THURSDAY_SEATING_END),
        ("2026-09-11", "2026-09-11T22:00:00Z", "2026-09-12T02:00:00Z"),
        (SATURDAY_DATE, "2026-09-12T22:00:00Z", "2026-09-13T02:00:00Z"),
    ]
    services = [
        FX.create_service(
            api,
            restaurant["id"],
            service_date=date,
            seating_start_utc=start,
            seating_end_utc=end,
        )
        for date, start, end in dates
    ]
    return {
        "restaurant": restaurant,
        "manager": make_restaurant_headers(restaurant["id"]),
        "services": services,
        "service_ids": [service["id"] for service in services],
    }


def _held_world(api):
    """The STD chain through a PUBLISHED Thursday service, an OPEN 20-seat
    class and one party-of-2 hold owned by the world's single guest."""
    world = FX.build_world(api, clock=SETUP_CLOCK)
    reservation = FX.hold_seats(
        api,
        world["ticket_class_id"],
        world["guest_id"],
        party_size=2,
        primary_guest_name="Corner Guest",
    )
    world["reservation"] = reservation
    world["reservation_id"] = reservation["id"]
    world["guest_headers"] = make_guest_headers(world["guest_id"])
    return world


def _scope_world(api):
    """Two restaurants that share nothing: A sells a confirmed party of 2 off a
    published Thursday service and also keeps a DRAFT service in reserve, while
    B owns a rival package, a table seating 2 to 4 and an add-on.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant_a = FX.create_restaurant(api, name="Corner Scope House A")
    restaurant_b = FX.create_restaurant(api, name="Corner Scope House B")
    package_a = FX.create_package(api, restaurant_a["id"], name="Tasting Menu")
    package_b = FX.create_package(
        api,
        restaurant_b["id"],
        name="Rival Menu",
        course_count=5,
        base_price_cents=9000,
        kitchen_prep_minutes_per_cover=10,
    )
    table_b = FX.create_table(
        api, restaurant_b["id"], table_code="B1", seats_min=2, seats_max=4
    )
    add_on_b = FX.create_add_on(
        api,
        restaurant_b["id"],
        name="Rival Caviar",
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=1440,
    )
    service_a = FX.create_service(api, restaurant_a["id"])
    ticket_class = FX.create_ticket_class(
        api, restaurant_a["id"], service_a["id"], package_a["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant_a["id"], service_a["id"])
    # A second service of restaurant A, deliberately left in DRAFT, because
    # "Allocating a class requires the owning service to still be DRAFT".
    draft_service_a = FX.create_service(
        api,
        restaurant_a["id"],
        service_date="2026-09-11",
        seating_start_utc="2026-09-11T22:00:00Z",
        seating_end_utc="2026-09-12T02:00:00Z",
    )
    guest = FX.create_guest(api, display_name="Scope Guest")
    reservation = FX.confirmed_reservation(
        api, ticket_class["id"], guest["id"], party_size=2
    )
    return {
        "restaurant_a_id": restaurant_a["id"],
        "restaurant_b_id": restaurant_b["id"],
        "manager_a": make_restaurant_headers(restaurant_a["id"]),
        "package_b": package_b,
        "table_b": table_b,
        "add_on_b": add_on_b,
        "service_a": service_a,
        "draft_service_a": draft_service_a,
        "ticket_class": ticket_class,
        "guest": guest,
        "guest_headers": make_guest_headers(guest["id"]),
        "reservation": reservation,
    }


class TestRestaurantRegistration:
    """Registering a restaurant with every knob supplied."""

    def test_every_supplied_policy_knob_is_persisted_verbatim(self, api):
        """All thirteen inputs come back on the created restaurant.

        "A `PlatformAdmin` brings a restaurant onto the platform by registering
        its trading `name` — non-empty, at most 120 characters, and unique
        across all restaurants — together with the ticketing policy knobs that
        will govern everything the room later does." Among them, "The kitchen
        service charge, `service_charge_bp`, defaults to 725 basis points —
        that is, 7.25 percent applied to each charge line — and may be set
        anywhere from 0 to 3000."

        Design: Corner/entities/creation_restaurant_persists_every_policy_knob
        """
        FX.set_clock(api, SETUP_CLOCK)
        payload = F.restaurant_payload(name="Corner Creation House")
        restaurant = validate_success(
            api.create_restaurant(payload, ADMIN_HEADERS), 201
        )

        assert restaurant["name"] == "Corner Creation House"
        for field, supplied in payload.items():
            assert restaurant[field] == supplied, (
                f"{field} should have been stored as {supplied!r}, got "
                f"{restaurant[field]!r}"
            )
        # The knobs that are not at their defaults prove the values were read
        # from the request rather than from the fallback table.
        assert restaurant["refund_scrutiny_threshold_cents"] == 300000
        assert restaurant["service_charge_bp"] == 725
        assert restaurant["hold_ttl_minutes"] == 20
        assert restaurant["offer_ttl_minutes"] == 15
        assert restaurant["max_offer_rounds"] == 2

    def test_the_server_mints_the_identity_fields_the_client_never_sent(self, api):
        """The response adds an id, both timestamps and version 1.

        "Every persisted resource carries a server-minted `id`: a UUID string
        with no type prefix, generated by the server and never supplied by the
        client." And "Endpoints that bring a new resource into existence answer
        with HTTP 201; endpoints that read or modify an existing resource answer
        with HTTP 200."

        Design: Corner/entities/creation_restaurant_persists_every_policy_knob
        """
        FX.set_clock(api, SETUP_CLOCK)
        payload = F.restaurant_payload(name="Corner Creation House")
        response = api.create_restaurant(payload, ADMIN_HEADERS)
        restaurant = validate_success(response, 201)

        A.assert_common_fields(restaurant)
        assert restaurant["version"] == 1
        for field in ("id", "created_at", "updated_at", "version"):
            assert field not in payload
            assert field in restaurant

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")


class TestRestaurantDefaults:
    """Registering a restaurant with nothing but a name."""

    def test_omitted_policy_knobs_fall_back_to_their_documented_defaults(self, api):
        """All twelve knobs land on the values the contract names.

        "Every knob is optional at registration and falls back to a documented
        default." The last of them: "`refund_scrutiny_threshold_cents` is the
        lifetime-refund figure above which a guest is flagged for scrutiny,
        defaulting to 30000 cents and required only to be non-negative."

        Design: Corner/entities/defaults_restaurant_omitted_policy_knobs_take_declared_defaults
        """
        restaurant = _bare_restaurant(api, name="Corner Defaults House")

        assert restaurant["name"] == "Corner Defaults House"
        assert restaurant["service_charge_bp"] == 725
        assert restaurant["hold_ttl_minutes"] == 20
        assert restaurant["offer_ttl_minutes"] == 15
        assert restaurant["max_offer_rounds"] == 2
        assert restaurant["max_name_changes"] == 1
        assert restaurant["name_change_cutoff_minutes"] == 240
        assert restaurant["transfer_cutoff_minutes"] == 1440
        assert restaurant["max_transfers_per_guest"] == 2
        assert restaurant["no_show_grace_minutes"] == 30
        assert restaurant["goodwill_credit_cap_cents"] == 20000
        assert restaurant["prep_lead_minutes"] == 45
        assert restaurant["refund_scrutiny_threshold_cents"] == 30000
        # Every one of the twelve, cross-checked against the documented table.
        for field, default in C.RESTAURANT_DEFAULTS.items():
            assert restaurant[field] == default, (
                f"{field} should default to {default!r}, got {restaurant[field]!r}"
            )


class TestCatalogueDefaults:
    """Packages, services and add-ons created with only their required inputs."""

    def test_package_optional_fields_take_their_declared_defaults(self, api):
        """A package created without any policy selector picks up all five.

        "When the mode is `DEPOSIT`, the deposit share is `deposit_bp`,
        expressed in basis points of the reservation's grand total, defaulting
        to 3000 — thirty percent — and permitted from 1 up to 10000; when the
        mode is `FULL`, `deposit_bp` is ignored entirely because the deposit
        simply is the grand total." Alongside it, "`release_discount_bp` is the
        discount applied to release-run inventory offered off the waitlist,
        defaulting to 1500 basis points — fifteen percent — over a permitted
        range of 0 to 5000."

        Design: Corner/entities/defaults_package_service_and_addon_omitted_fields_take_declared_defaults
        """
        restaurant = _bare_restaurant(api, name="Corner Minimal House")
        manager = make_restaurant_headers(restaurant["id"])
        package = validate_success(
            api.create_package(
                {
                    "restaurant_id": restaurant["id"],
                    "name": "Bare Menu",
                    "course_count": 6,
                    "base_price_cents": 12000,
                    "prepayment_mode": "DEPOSIT",
                    "min_party_size": 1,
                    "max_party_size": 8,
                },
                manager,
            ),
            201,
        )

        assert package["deposit_bp"] == 3000
        assert package["forfeiture_schedule_code"] == "STANDARD"
        assert package["forfeiture_basis"] == "DEPOSIT_BASIS"
        assert package["release_discount_bp"] == 1500
        assert package["kitchen_prep_minutes_per_cover"] == 10
        for field, default in C.PACKAGE_DEFAULTS.items():
            assert package[field] == default, (
                f"{field} should default to {default!r}, got {package[field]!r}"
            )

    def test_service_optional_fields_default_and_day_of_week_is_derived(self, api):
        """A service created with only its window keeps the five defaults, is
        born DRAFT, and reports the Thursday its date falls on.

        "`demand_tier` is the demand band feeding the tier price multiplier and
        is one of `LOW`, `STANDARD`, `HIGH` or `PEAK`, defaulting to
        `STANDARD`." And "The service's `day_of_week` is never supplied by the
        client: it is derived from `service_date` on the proleptic Gregorian
        calendar and reported as one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`
        or `SUN`."

        Design: Corner/entities/defaults_package_service_and_addon_omitted_fields_take_declared_defaults
        """
        restaurant = _bare_restaurant(api, name="Corner Minimal House")
        manager = make_restaurant_headers(restaurant["id"])
        payload = {
            "restaurant_id": restaurant["id"],
            "service_date": THURSDAY_DATE,
            "meal_period": "DINNER",
            "seating_start_utc": THURSDAY_SEATING_START,
            "seating_end_utc": THURSDAY_SEATING_END,
            "turn_time_minutes": 150,
            "seats_capacity": 20,
        }
        service = validate_success(api.create_service(payload, manager), 201)

        assert service["demand_tier"] == "STANDARD"
        assert service["unsold_release_bp"] == 5000
        assert service["release_lead_minutes"] == 180
        assert service["waitlist_policy"] == "FAIR_QUEUE"
        assert service["kitchen_prep_capacity_minutes"] == 600
        for field, default in C.SERVICE_DEFAULTS.items():
            assert service[field] == default, (
                f"{field} should default to {default!r}, got {service[field]!r}"
            )
        assert "day_of_week" not in payload
        assert service["day_of_week"] == "THU"
        assert service["status"] == "DRAFT"

    def test_add_on_optional_fields_take_their_declared_defaults(self, api):
        """An add-on created with only a name and a price keeps all four.

        "`max_qty_per_cover` is the per-cover quantity ceiling, defaulting to 1
        and ranging from 1 to 20; the effective ceiling on a booking is that
        figure multiplied by the reservation's party size." And
        "`order_cutoff_minutes` refuses add-on orders inside that many minutes
        of the seating start, defaulting to 1440 over a 0-to-20160 range."

        Design: Corner/entities/defaults_package_service_and_addon_omitted_fields_take_declared_defaults
        """
        restaurant = _bare_restaurant(api, name="Corner Minimal House")
        manager = make_restaurant_headers(restaurant["id"])
        add_on = validate_success(
            api.create_add_on(
                {
                    "restaurant_id": restaurant["id"],
                    "name": "Bare Caviar",
                    "price_cents": 4500,
                },
                manager,
            ),
            201,
        )

        assert add_on["prep_minutes_per_unit"] == 0
        assert add_on["max_qty_per_cover"] == 1
        assert add_on["order_cutoff_minutes"] == 1440
        assert add_on["requires_kitchen_ack"] is False
        for field, default in C.ADDON_DEFAULTS.items():
            assert add_on[field] == default, (
                f"{field} should default to {default!r}, got {add_on[field]!r}"
            )


class TestTicketClassComputedFields:
    """Allocating a class against a DRAFT Thursday service."""

    def test_seat_pool_and_status_are_computed_from_the_allocation(self, api):
        """The whole allocation starts as availability, on an OPEN class.

        "On creation the class's `seats_available` is initialised to the whole of
        `seats_allocated`, `seats_sold`, `seats_held` and `seats_released` all
        start at 0, `status` starts at `OPEN`, and both
        `list_price_per_cover_cents` and `release_price_per_cover_cents` are
        computed immediately from the pricing rules of §3.2."

        Design: Corner/entities/computed_fields_ticket_class_seat_pool_and_two_prices_on_create
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Compute House")
        package = FX.create_package(api, restaurant["id"], name="Tasting Menu")
        service = FX.create_service(api, restaurant["id"])
        manager = make_restaurant_headers(restaurant["id"])

        payload = F.ticket_class_payload(
            service["id"], package["id"], seats_allocated=20
        )
        ticket_class = validate_success(
            api.create_ticket_class(payload, manager), 201
        )

        assert ticket_class["seats_allocated"] == 20
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=0, available=20, status="OPEN"
        )
        assert ticket_class["sell_through_bp"] == 0
        for counter in ("seats_sold", "seats_held", "seats_released"):
            assert counter not in payload
        assert ticket_class["service_id"] == service["id"]
        assert ticket_class["package_id"] == package["id"]

    def test_both_per_cover_prices_are_derived_at_allocation_time(self, api):
        """A Thursday STANDARD cover lists at 12000 and releases at 10200.

        "`list_price_per_cover_cents` is the outcome of steps one through four
        with ordinary availability as the drawing pool — that is, without the
        release discount." And "When the seats being priced are drawn from the
        released pool rather than from ordinary availability, the figure produced
        by step four is multiplied by 10000 minus the package's
        `release_discount_bp`, divided by 10000, and rounded half up."

        Design: Corner/entities/computed_fields_ticket_class_seat_pool_and_two_prices_on_create
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Compute House")
        # base_price_cents 12000 and release_discount_bp 1500.
        package = FX.create_package(api, restaurant["id"], name="Tasting Menu")
        # A Thursday at the STANDARD tier: 10000 bp times 10000 bp over 10000 is
        # 10000 bp, which sits inside the 8500..18000 clamp, so the base survives
        # untouched; an empty pool adds no scarcity step.
        service = FX.create_service(api, restaurant["id"])
        manager = make_restaurant_headers(restaurant["id"])

        ticket_class = validate_success(
            api.create_ticket_class(
                F.ticket_class_payload(
                    service["id"], package["id"], seats_allocated=20
                ),
                manager,
            ),
            201,
        )

        assert package["base_price_cents"] == 12000
        assert package["release_discount_bp"] == 1500
        assert service["day_of_week"] == "THU"
        assert service["demand_tier"] == "STANDARD"
        assert ticket_class["list_price_per_cover_cents"] == LIST_PRICE
        assert ticket_class["release_price_per_cover_cents"] == RELEASE_PRICE


class TestReservationSystemFields:
    """Creating a hold declares five inputs and inherits everything else."""

    def test_service_id_price_and_statuses_are_set_by_the_server(self, api):
        """The create body never names them, yet the reservation carries them.

        "The reservation's `service_id` is never supplied: it is copied from the
        ticket class at creation and never changes afterwards." Creation also
        settles the clock-derived deadline: "`hold_expires_at_utc` is set to the
        logical clock plus the restaurant's `hold_ttl_minutes`."

        Design: Corner/entities/system_fields_reservation_ids_and_statuses_input_ignored
        """
        world = FX.build_world(api, clock=SETUP_CLOCK)
        guest_headers = make_guest_headers(world["guest_id"])
        version = FX.ticket_class_version(
            api, world["ticket_class_id"], guest_headers
        )
        payload = F.reservation_payload(
            world["ticket_class_id"],
            world["guest_id"],
            version,
            party_size=2,
            primary_guest_name="System Guest",
        )
        reservation = validate_success(
            api.create_reservation(payload, guest_headers), 201
        )

        assert set(payload) == {
            "ticket_class_id",
            "guest_id",
            "party_size",
            "primary_guest_name",
            "expected_ticket_class_version",
        }
        assert reservation["service_id"] == world["service_id"]
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")
        assert reservation["price_locked_per_cover_cents"] == LIST_PRICE
        assert reservation["amount_paid_cents"] == 0
        # The clock stands at 00:00:00Z and hold_ttl_minutes is 20.
        assert F.parse_iso(reservation["hold_expires_at_utc"]) == F.parse_iso(
            HOLD_LAPSES_AT
        )

    def test_a_fresh_hold_starts_with_every_later_field_empty(self, api):
        """Nothing that a later transition writes is populated at creation.

        "The reservation lands in `fulfillment_status` `PENDING` and
        `payment_status` `UNPAID`, with `assigned_table_id`,
        `transferred_from_reservation_id`, `seat_from_utc`, `seat_to_utc` and
        `cancel_settlement_basis` all null, `is_release_priced` and
        `deposit_frozen` both false, `name_change_count` at 0, and every money
        roll-up other than the ones just named at 0."

        Design: Corner/entities/system_fields_reservation_ids_and_statuses_input_ignored
        """
        world = _held_world(api)
        reservation = world["reservation"]

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
            ticket_subtotal=TICKET_SUBTOTAL,
            add_on_total=0,
            service_charge=SERVICE_CHARGE,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
            amount_paid=0,
            refunded=0,
            forfeited=0,
            goodwill_applied=0,
        )
        A.assert_common_fields(reservation)
        assert reservation["version"] == 1


class TestServiceRetrieval:
    """Reading back a Saturday service that has sold nothing."""

    def test_the_read_echoes_the_stored_window_and_derives_the_day(self, api):
        """Every supplied field comes back, plus the Saturday it falls on.

        "The service's `day_of_week` is never supplied by the client: it is
        derived from `service_date` on the proleptic Gregorian calendar and
        reported as one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT` or `SUN`."

        Design: Corner/entities/retrieval_service_returns_stored_fields_and_derived_day_of_week
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Read House")
        manager = make_restaurant_headers(restaurant["id"])
        created = FX.create_service(
            api,
            restaurant["id"],
            service_date=SATURDAY_DATE,
            meal_period="LUNCH",
            seating_start_utc=SATURDAY_SEATING_START,
            seating_end_utc=SATURDAY_SEATING_END,
            turn_time_minutes=90,
            seats_capacity=12,
            demand_tier="PEAK",
            unsold_release_bp=2500,
            release_lead_minutes=120,
            waitlist_policy="YIELD_WEIGHTED",
            kitchen_prep_capacity_minutes=240,
        )

        service = validate_success(api.get_service(created["id"], manager), 200)

        assert service["id"] == created["id"]
        assert service["restaurant_id"] == restaurant["id"]
        assert service["service_date"] == SATURDAY_DATE
        assert service["meal_period"] == "LUNCH"
        assert F.parse_iso(service["seating_start_utc"]) == F.parse_iso(
            SATURDAY_SEATING_START
        )
        assert F.parse_iso(service["seating_end_utc"]) == F.parse_iso(
            SATURDAY_SEATING_END
        )
        assert service["turn_time_minutes"] == 90
        assert service["seats_capacity"] == 12
        assert service["demand_tier"] == "PEAK"
        assert service["unsold_release_bp"] == 2500
        assert service["release_lead_minutes"] == 120
        assert service["waitlist_policy"] == "YIELD_WEIGHTED"
        assert service["kitchen_prep_capacity_minutes"] == 240
        assert service["day_of_week"] == "SAT"

    def test_a_service_that_has_sold_nothing_reads_back_all_zeroes(self, api):
        """The nine roll-ups and the birth status.

        "A service is born in `status` `DRAFT`, and its nine
        money-and-inventory roll-ups — `release_run_count`,
        `seats_released_total`, `last_release_released_count`,
        `last_release_promoted_count`, `covers_confirmed`,
        `gross_charged_cents`, `refunded_cents`, `forfeited_cents` and
        `net_settled_cents` — all begin at 0."

        Design: Corner/entities/retrieval_service_returns_stored_fields_and_derived_day_of_week
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Read House")
        manager = make_restaurant_headers(restaurant["id"])
        created = FX.create_service(
            api,
            restaurant["id"],
            service_date=SATURDAY_DATE,
            meal_period="LUNCH",
            seating_start_utc=SATURDAY_SEATING_START,
            seating_end_utc=SATURDAY_SEATING_END,
            turn_time_minutes=90,
            seats_capacity=12,
        )

        service = validate_success(api.get_service(created["id"], manager), 200)

        assert service["status"] == "DRAFT"
        for field in C.SERVICE_ROLLUP_FIELDS:
            assert service[field] == 0, f"{field} should begin at 0"
        assert len(C.SERVICE_ROLLUP_FIELDS) == 9
        A.assert_common_fields(service)


class TestServiceListingPagination:
    """Three services and a window of two."""

    def test_the_first_page_reports_the_full_count_and_more_to_come(self, api):
        """Two rows of three, with has_more true.

        "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope." And "`total_count`
        is the number of rows matching the filter before the window is applied,
        and `has_more` is true when rows remain beyond the returned window."

        Design: Corner/entities/listing_services_paginates_with_total_count_and_has_more
        """
        world = _three_services(api)

        response = api.list_services(world["manager"], {"limit": 2, "offset": 0})
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert len(rows) == 2
        A.assert_pagination_meta(
            meta, limit=2, offset=0, total_count=3, has_more=True
        )
        A.assert_created_at_ascending(rows)

    def test_the_last_page_closes_the_window_without_repeating_a_row(self, api):
        """The remaining row, with has_more false and no overlap.

        "Unless a specific endpoint says otherwise, list results are ordered by
        the row's own `created_at` timestamp, ascending — oldest first."

        Design: Corner/entities/listing_services_paginates_with_total_count_and_has_more
        """
        world = _three_services(api)

        first_rows, _ = validate_paginated(
            api.list_services(world["manager"], {"limit": 2, "offset": 0})
        )
        last_rows, last_meta = validate_paginated(
            api.list_services(world["manager"], {"limit": 2, "offset": 2})
        )

        assert len(last_rows) == 1
        A.assert_pagination_meta(
            last_meta, limit=2, offset=2, total_count=3, has_more=False
        )
        paged_ids = [row["id"] for row in first_rows] + [
            row["id"] for row in last_rows
        ]
        assert len(paged_ids) == len(set(paged_ids)) == 3
        assert set(paged_ids) == set(world["service_ids"])
        assert paged_ids == world["service_ids"]


class TestPaginationBounds:
    """The declared window bounds on a service listing."""

    def test_limit_and_offset_outside_their_ranges_are_refused(self, api):
        """Zero, 101 and a negative offset are all rejected the same way.

        "A `limit` below 1 or above 100, or an `offset` below 0, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/entities/listing_pagination_out_of_range_rejected
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Bad Page House")
        manager = make_restaurant_headers(restaurant["id"])
        FX.create_service(api, restaurant["id"])

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(
                api.list_services(manager, params), ERR_INVALID_PAGINATION, 400
            )

    def test_the_boundary_window_is_accepted(self, api):
        """limit 100 with offset 0 is inside the range and returns the row.

        "`limit` caps the number of rows returned; when it is omitted it
        defaults to 10, and a supplied value must be at least 1 and at most
        100."

        Design: Corner/entities/listing_pagination_out_of_range_rejected
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Bad Page House")
        manager = make_restaurant_headers(restaurant["id"])
        service = FX.create_service(api, restaurant["id"])

        response = api.list_services(manager, {"limit": 100, "offset": 0})
        rows, meta = validate_paginated(response)

        assert response.status_code == 200
        assert [row["id"] for row in rows] == [service["id"]]
        A.assert_pagination_meta(
            meta, limit=100, offset=0, total_count=1, has_more=False
        )


class TestEntitySpecificNotFound:
    """Fourteen single-id reads against an empty database."""

    def test_each_read_returns_its_own_entity_not_found_code(self, api):
        """No endpoint falls back to a shared not-found code.

        "Every identifier in the request path exists, validated left to right, on
        every endpoint that has a path identifier — otherwise the matching
        not-found code from §2.9."

        Design: Corner/entities/not_found_reads_return_the_entity_specific_404
        """
        FX.set_clock(api, SETUP_CLOCK)
        probes = [
            (api.get_restaurant, "01", ERR_RESTAURANT_NOT_FOUND),
            (api.get_guest, "02", ERR_GUEST_NOT_FOUND),
            (api.get_table, "03", ERR_TABLE_NOT_FOUND),
            (api.get_package, "04", ERR_PACKAGE_NOT_FOUND),
            (api.get_add_on, "05", ERR_ADDON_NOT_FOUND),
            (api.get_service, "06", ERR_SERVICE_NOT_FOUND),
            (api.get_ticket_class, "07", ERR_TICKET_CLASS_NOT_FOUND),
            (api.get_reservation, "08", ERR_RESERVATION_NOT_FOUND),
            (api.get_reservation_add_on, "09", ERR_RESERVATION_ADDON_NOT_FOUND),
            (api.get_dietary_note, "0a", ERR_DIETARY_NOTE_NOT_FOUND),
            (api.get_waitlist_entry, "0b", ERR_WAITLIST_ENTRY_NOT_FOUND),
            (api.get_payment_transaction, "0c", ERR_PAYMENT_TRANSACTION_NOT_FOUND),
            (api.get_refund_exception, "0d", ERR_REFUND_EXCEPTION_NOT_FOUND),
            (api.get_goodwill_credit, "0e", ERR_GOODWILL_CREDIT_NOT_FOUND),
        ]
        assert len(probes) == 14
        seen = set()

        for read, tail, expected in probes:
            unused_id = f"00000000-0000-4000-8000-0000000000{tail}"
            response = read(unused_id, ADMIN_HEADERS)
            error = validate_error(response, expected, 404)
            assert response.json()["response_type"] == "error"
            assert isinstance(error["message"], str) and error["message"]
            seen.add(error["error_id"])

        # Fourteen entity types, fourteen distinct codes.
        assert len(seen) == 14


class TestRequiredFields:
    """Dropping one non-optional field from an otherwise valid body."""

    def test_a_missing_required_field_is_a_validation_error(self, api):
        """Three creates, each missing exactly one required input.

        "The request body satisfies its declared shape on every endpoint:
        required fields present, types correct, enum values recognised, integers
        inside their declared ranges, datetimes well-formed ISO 8601 UTC —
        otherwise `ERR_VALIDATION`." The echoed parent version is one of them:
        "Each of those three requires the client to echo back the `version` it
        last observed on that parent, as a **non-optional** field in the request
        body, and each rejects the write when the echoed value does not equal the
        parent's current `version`."

        Design: Corner/entities/required_fields_missing_on_create_returns_400
        """
        world = FX.build_world(api, clock=SETUP_CLOCK)
        manager = world["manager_headers"]
        guest_headers = make_guest_headers(world["guest_id"])

        package_payload = F.package_payload(
            world["restaurant_id"], name="No Price Menu", course_count=4
        )
        del package_payload["base_price_cents"]
        validate_error(
            api.create_package(package_payload, manager), ERR_VALIDATION, 400
        )

        service_payload = F.service_payload(
            world["restaurant_id"],
            service_date="2026-09-11",
            seating_start_utc="2026-09-11T22:00:00Z",
            seating_end_utc="2026-09-12T02:00:00Z",
        )
        del service_payload["turn_time_minutes"]
        validate_error(
            api.create_service(service_payload, manager), ERR_VALIDATION, 400
        )

        reservation_payload = {
            "ticket_class_id": world["ticket_class_id"],
            "guest_id": world["guest_id"],
            "party_size": 2,
            "primary_guest_name": "Required Guest",
        }
        validate_error(
            api.create_reservation(reservation_payload, guest_headers),
            ERR_VALIDATION,
            400,
        )

    def test_a_refused_create_writes_no_row(self, api):
        """The three rejections leave the catalogue exactly as it was.

        "The request body satisfies its declared shape on every endpoint:
        required fields present, types correct, enum values recognised, integers
        inside their declared ranges, datetimes well-formed ISO 8601 UTC —
        otherwise `ERR_VALIDATION`."

        Design: Corner/entities/required_fields_missing_on_create_returns_400
        """
        world = FX.build_world(api, clock=SETUP_CLOCK)
        manager = world["manager_headers"]
        guest_headers = make_guest_headers(world["guest_id"])

        package_payload = F.package_payload(
            world["restaurant_id"], name="No Price Menu", course_count=4
        )
        del package_payload["base_price_cents"]
        api.create_package(package_payload, manager)

        service_payload = F.service_payload(
            world["restaurant_id"],
            service_date="2026-09-11",
            seating_start_utc="2026-09-11T22:00:00Z",
            seating_end_utc="2026-09-12T02:00:00Z",
        )
        del service_payload["turn_time_minutes"]
        api.create_service(service_payload, manager)

        api.create_reservation(
            {
                "ticket_class_id": world["ticket_class_id"],
                "guest_id": world["guest_id"],
                "party_size": 2,
                "primary_guest_name": "Required Guest",
            },
            guest_headers,
        )

        packages, _ = validate_paginated(
            api.list_restaurant_packages(world["restaurant_id"], manager)
        )
        services, _ = validate_paginated(
            api.list_restaurant_services(world["restaurant_id"], manager)
        )
        reservations, reservation_meta = validate_paginated(
            api.list_reservations(guest_headers, {"guest_id": world["guest_id"]})
        )

        assert len(packages) == 1
        assert len(services) == 1
        assert reservations == []
        assert reservation_meta["total_count"] == 0


class TestTypeConstraints:
    """Bodies that are well formed apart from one value out of its domain."""

    def test_an_unrecognised_enum_member_and_a_below_range_integer_are_refused(
        self, api
    ):
        """BRUNCH is not a meal period and 10 minutes is too short a turn.

        "`turn_time_minutes` is how long a party occupies its table before the
        table's own buffer is added, and must be at least 15 minutes and at most
        480."

        Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_rejected
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Types House")
        manager = make_restaurant_headers(restaurant["id"])

        validate_error(
            api.create_service(
                F.service_payload(restaurant["id"], meal_period="BRUNCH"), manager
            ),
            ERR_VALIDATION,
            400,
        )
        validate_error(
            api.create_service(
                F.service_payload(restaurant["id"], turn_time_minutes=10), manager
            ),
            ERR_VALIDATION,
            400,
        )

        services, meta = validate_paginated(
            api.list_restaurant_services(restaurant["id"], manager)
        )
        assert services == []
        assert meta["total_count"] == 0

    def test_a_malformed_timestamp_and_a_backwards_seating_window_are_refused(
        self, api
    ):
        """A non-ISO instant, and an end that precedes its start.

        "A `RestaurantManager` creates it against a `restaurant_id` with a
        `service_date` calendar date in ISO 8601 `YYYY-MM-DD` form, a
        `meal_period` that is either `LUNCH` or `DINNER`, a `seating_start_utc`
        that is the earliest legal seating instant, and a `seating_end_utc` that
        is the latest legal seating instant and must fall strictly after the
        start."

        Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_rejected
        """
        FX.set_clock(api, SETUP_CLOCK)
        restaurant = FX.create_restaurant(api, name="Corner Types House")
        manager = make_restaurant_headers(restaurant["id"])

        validate_error(
            api.create_service(
                F.service_payload(
                    restaurant["id"], seating_start_utc="10/09/2026 22:00"
                ),
                manager,
            ),
            ERR_VALIDATION,
            400,
        )
        validate_error(
            api.create_service(
                F.service_payload(
                    restaurant["id"],
                    seating_start_utc=THURSDAY_SEATING_END,
                    seating_end_utc=THURSDAY_SEATING_START,
                ),
                manager,
            ),
            ERR_VALIDATION,
            400,
        )

        services, _ = validate_paginated(
            api.list_restaurant_services(restaurant["id"], manager)
        )
        assert services == []

    def test_a_knob_above_its_ceiling_and_a_broken_cross_field_bound_are_refused(
        self, api
    ):
        """3001 basis points is over the cap, and an offer may not outlive a hold.

        "The kitchen service charge, `service_charge_bp`, defaults to 725 basis
        points — that is, 7.25 percent applied to each charge line — and may be
        set anywhere from 0 to 3000." And "`offer_ttl_minutes` is how long a
        waitlist offer stays claimable; it defaults to 15 minutes, must be at
        least 1 minute, and — critically — must never exceed `hold_ttl_minutes`,
        so that an offer always lapses before the hold reservation it minted."

        Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_rejected
        """
        FX.set_clock(api, SETUP_CLOCK)
        FX.create_restaurant(api, name="Corner Types House")

        validate_error(
            api.create_restaurant(
                {"name": "Corner Over Charge House", "service_charge_bp": 3001},
                ADMIN_HEADERS,
            ),
            ERR_VALIDATION,
            400,
        )
        validate_error(
            api.create_restaurant(
                {
                    "name": "Corner Bad Ttl House",
                    "hold_ttl_minutes": 20,
                    "offer_ttl_minutes": 30,
                },
                ADMIN_HEADERS,
            ),
            ERR_VALIDATION,
            400,
        )

        restaurants, meta = validate_paginated(api.list_restaurants(ADMIN_HEADERS))
        assert len(restaurants) == 1
        assert meta["total_count"] == 1
        assert restaurants[0]["name"] == "Corner Types House"


class TestLedgerRowImmutability:
    """The ledger of a deposit-paid then fully-paid booking."""

    def test_a_ledger_row_carries_no_version_and_no_updated_at(self, api):
        """The deposit row is the one resource shape without the common fields.

        "Ledger rows are immutable once written: a `PaymentTransaction` carries
        only `id` and `created_at`, and both `updated_at` and `version` are
        absent from it entirely."

        Design: Corner/entities/immutability_payment_transaction_carries_no_version_field
        """
        world = _held_world(api)
        FX.pay(api, world["reservation_id"], world["guest_id"], DEPOSIT_DUE)
        FX.confirm(api, world["reservation_id"], world["guest_id"])

        rows = FX.ledger_rows(api, world["reservation_id"], CARE_HEADERS)

        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "DEPOSIT_CHARGE"
        assert row["amount_cents"] == DEPOSIT_DUE
        assert row["signed_amount_cents"] == DEPOSIT_DUE
        assert row["memo_code"] == "GUEST_PREPAY"
        assert row["reservation_id"] == world["reservation_id"]
        assert row["goodwill_credit_id"] is None
        A.assert_ledger_row_shape(row)
        A.assert_signed_amount(row)
        assert "version" not in row
        assert "updated_at" not in row

    def test_clearing_the_balance_appends_a_row_and_edits_nothing(self, api):
        """The second payment leaves the first row exactly as it was.

        "Rows are never edited and never deleted; a correction is always a new
        compensating row." And "A later payment that clears the remainder of a
        deposit-paid reservation moves it `DEPOSIT_PAID → FULLY_PAID`, writing a
        `BALANCE_CHARGE` row with `memo_code` `GUEST_BALANCE`, driving
        `balance_due_cents` to 0 and thereby unblocking both completion and
        transfer."

        Design: Corner/entities/immutability_payment_transaction_carries_no_version_field
        """
        world = _held_world(api)
        FX.pay(api, world["reservation_id"], world["guest_id"], DEPOSIT_DUE)
        FX.confirm(api, world["reservation_id"], world["guest_id"])
        before = FX.ledger_rows(api, world["reservation_id"], CARE_HEADERS)

        FX.pay(api, world["reservation_id"], world["guest_id"], BALANCE_DUE)
        after = FX.ledger_rows(api, world["reservation_id"], CARE_HEADERS)

        assert len(before) == 1
        assert len(after) == 2
        A.assert_created_at_ascending(after)
        assert after[0] == before[0], (
            "the first ledger row must be untouched by the second payment"
        )
        assert [row["kind"] for row in after] == ["DEPOSIT_CHARGE", "BALANCE_CHARGE"]
        assert [row["amount_cents"] for row in after] == [DEPOSIT_DUE, BALANCE_DUE]
        assert after[1]["memo_code"] == "GUEST_BALANCE"
        for row in after:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)

        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        assert reservation["amount_paid_cents"] == GRAND_TOTAL
        A.assert_payment_status(reservation, "FULLY_PAID")


class TestBodyForeignKeys:
    """Creates whose body names a parent that was never written."""

    def test_an_unknown_body_foreign_key_returns_that_entity_s_not_found_code(
        self, api
    ):
        """Four creates, four different 404s, no validation error anywhere.

        "Foreign keys are supplied in request bodies rather than encoded as
        nested write paths, which means that a create request can reference a
        parent that does not exist." And "Every foreign key in the request body
        references an existing row, on every create carrying foreign keys —
        otherwise the matching not-found code from §2.9."

        Design: Corner/entities/fk_reference_validation_unknown_body_foreign_keys_return_not_found
        """
        world = _held_world(api)
        version = FX.ticket_class_version(
            api, world["ticket_class_id"], world["guest_headers"]
        )
        reservation_version = FX.reservation_version(
            api, world["reservation_id"], world["guest_headers"]
        )

        validate_error(
            api.create_ticket_class(
                F.ticket_class_payload(
                    world["service_id"],
                    GHOST_PACKAGE_ID,
                    seats_allocated=4,
                    max_party_size=4,
                ),
                world["manager_headers"],
            ),
            ERR_PACKAGE_NOT_FOUND,
            404,
        )
        # The acting guest is the very guest the body names, so ownership holds
        # and the only thing wrong with the request is that no such guest exists.
        validate_error(
            api.create_reservation(
                F.reservation_payload(
                    world["ticket_class_id"],
                    GHOST_GUEST_ID,
                    version,
                    primary_guest_name="Ghost",
                ),
                make_guest_headers(GHOST_GUEST_ID),
            ),
            ERR_GUEST_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_waitlist_entry(
                F.waitlist_entry_payload(GHOST_SERVICE_ID, world["guest_id"]),
                world["guest_headers"],
            ),
            ERR_SERVICE_NOT_FOUND,
            404,
        )
        validate_error(
            api.append_add_on_line(
                world["reservation_id"],
                F.add_on_line_payload(GHOST_ADDON_ID, reservation_version),
                world["guest_headers"],
            ),
            ERR_ADDON_NOT_FOUND,
            404,
        )

    def test_the_refused_creates_move_no_seat_and_write_no_class(self, api):
        """The class and its seat pool are exactly where the hold left them.

        "Every foreign key in the request body references an existing row, on
        every create carrying foreign keys — otherwise the matching not-found
        code from §2.9."

        Design: Corner/entities/fk_reference_validation_unknown_body_foreign_keys_return_not_found
        """
        world = _held_world(api)
        version = FX.ticket_class_version(
            api, world["ticket_class_id"], world["guest_headers"]
        )
        reservation_version = FX.reservation_version(
            api, world["reservation_id"], world["guest_headers"]
        )

        api.create_ticket_class(
            F.ticket_class_payload(
                world["service_id"],
                GHOST_PACKAGE_ID,
                seats_allocated=4,
                max_party_size=4,
            ),
            world["manager_headers"],
        )
        api.create_reservation(
            F.reservation_payload(
                world["ticket_class_id"],
                GHOST_GUEST_ID,
                version,
                primary_guest_name="Ghost",
            ),
            make_guest_headers(GHOST_GUEST_ID),
        )
        api.append_add_on_line(
            world["reservation_id"],
            F.add_on_line_payload(GHOST_ADDON_ID, reservation_version),
            world["guest_headers"],
        )

        classes, meta = validate_paginated(
            api.list_ticket_classes(
                world["manager_headers"], {"service_id": world["service_id"]}
            )
        )
        assert len(classes) == 1
        assert meta["total_count"] == 1
        assert classes[0]["id"] == world["ticket_class_id"]

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=2, released=0, available=18, status="OPEN"
        )


class TestRestaurantScopeIntegrity:
    """Parents that exist, but under the wrong restaurant."""

    def test_a_package_from_another_restaurant_cannot_be_allocated(self, api):
        """The rival package exists, so the refusal is a mismatch, not a 404.

        "The package must belong to the same restaurant as the service, or the
        allocation fails with `ERR_PACKAGE_RESTAURANT_MISMATCH`." The attempt is
        made against a service that is still open to allocation, because
        "Allocating a class requires the owning service to still be `DRAFT`;
        attempting it against a service that has moved on is rejected with
        `ERR_SERVICE_INVALID_STATE`."

        Design: Corner/entities/cross_reference_integrity_mismatched_restaurant_scopes_rejected
        """
        world = _scope_world(api)
        draft_service_id = world["draft_service_a"]["id"]
        assert world["draft_service_a"]["status"] == "DRAFT"
        assert world["package_b"]["restaurant_id"] == world["restaurant_b_id"]

        validate_error(
            api.create_ticket_class(
                F.ticket_class_payload(
                    draft_service_id,
                    world["package_b"]["id"],
                    seats_allocated=4,
                    max_party_size=4,
                ),
                world["manager_a"],
            ),
            ERR_PACKAGE_RESTAURANT_MISMATCH,
            422,
        )

        draft_classes, _ = validate_paginated(
            api.list_ticket_classes(
                world["manager_a"], {"service_id": draft_service_id}
            )
        )
        traded_classes, _ = validate_paginated(
            api.list_ticket_classes(
                world["manager_a"], {"service_id": world["service_a"]["id"]}
            )
        )
        assert draft_classes == []
        assert len(traded_classes) == 1
        assert traded_classes[0]["id"] == world["ticket_class"]["id"]

    def test_a_table_from_another_restaurant_cannot_be_assigned(self, api):
        """The party of two fits the rival table's band and is still refused.

        "The table must also belong to the same restaurant as the reservation's
        service, failing which the assignment is rejected with
        `ERR_TABLE_RESTAURANT_MISMATCH`, and the reservation's `party_size` must
        fall within the table's `seats_min` and `seats_max` inclusive, failing
        which the rejection is `ERR_TABLE_PARTY_SIZE_MISMATCH`."

        Design: Corner/entities/cross_reference_integrity_mismatched_restaurant_scopes_rejected
        """
        world = _scope_world(api)
        reservation = world["reservation"]
        table_b = world["table_b"]

        # The band is not the problem: a party of 2 sits inside 2..4.
        assert table_b["seats_min"] == 2 and table_b["seats_max"] == 4
        assert reservation["party_size"] == 2
        assert table_b["restaurant_id"] == world["restaurant_b_id"]

        validate_error(
            api.assign_table(
                reservation["id"],
                F.assign_table_payload(table_b["id"], THURSDAY_SEATING_START),
                world["manager_a"],
            ),
            ERR_TABLE_RESTAURANT_MISMATCH,
            422,
        )

        after = FX.read_reservation(api, reservation["id"], world["guest_headers"])
        assert after["assigned_table_id"] is None
        assert after["seat_from_utc"] is None
        assert after["version"] == reservation["version"]

    def test_an_add_on_from_another_restaurant_cannot_be_appended(self, api):
        """The rival add-on leaves the booking's money and version untouched.

        "The add-on must belong to the same restaurant as the reservation's
        service, failing which the append is rejected with
        `ERR_ADDON_RESTAURANT_MISMATCH`."

        Design: Corner/entities/cross_reference_integrity_mismatched_restaurant_scopes_rejected
        """
        world = _scope_world(api)
        reservation = world["reservation"]
        before_version = FX.reservation_version(
            api, reservation["id"], world["guest_headers"]
        )
        assert world["add_on_b"]["restaurant_id"] == world["restaurant_b_id"]

        validate_error(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(world["add_on_b"]["id"], before_version),
                world["guest_headers"],
            ),
            ERR_ADDON_RESTAURANT_MISMATCH,
            422,
        )

        after = FX.read_reservation(api, reservation["id"], world["guest_headers"])
        assert after["add_on_total_cents"] == 0
        assert after["grand_total_cents"] == GRAND_TOTAL
        assert after["version"] == before_version
        A.assert_money_breakdown(
            after,
            ticket_subtotal=TICKET_SUBTOTAL,
            add_on_total=0,
            service_charge=SERVICE_CHARGE,
            grand_total=GRAND_TOTAL,
            deposit_due=DEPOSIT_DUE,
        )
