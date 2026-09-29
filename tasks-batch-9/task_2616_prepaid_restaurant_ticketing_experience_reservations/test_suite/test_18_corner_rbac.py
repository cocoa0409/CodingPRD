"""
Role reach, endpoint by endpoint: what an entity-backed principal may write on
rows it owns, and what it may not write at all.

Every request below carries the two mandatory identity headers, and the two
entity-backed roles exercised here are always built from the real id created
during setup — a Guest's X-User-ID is that Guest's own id and a
RestaurantManager's is the id of the Restaurant it acts for. Each permitted
write is asserted through its declared side effect rather than through its
status code alone, and each refused write is asserted through the exact
identifier and status the rejection order pins to it.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ERR_UNAUTHORIZED
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_guest_headers,
    make_restaurant_headers,
)

# The instant every scenario pins the logical clock to before anything else
# happens: far enough from the seating start that the 20-minute hold, the
# 240-minute rename cutoff and the 1440-minute add-on cutoff are all wide open.
SETUP_CLOCK = "2026-09-01T00:00:00Z"

# One Thursday dinner service. Thursday carries the neutral 10000-basis-point
# day-of-week factor, so a STANDARD-tier 12000-cent cover prices at 12000.
SERVICE_DATE = "2026-09-10"
SEATING_START = "2026-09-10T22:00:00Z"
SEATING_END = "2026-09-11T02:00:00Z"
TURN_TIME_MINUTES = 150

# seat_from_utc plus the service's turn_time_minutes.
SEAT_TO_UTC = "2026-09-11T00:30:00Z"
# seat_from_utc plus the restaurant's 30-minute no-show grace.
NO_SHOW_AT = "2026-09-10T22:30:00Z"

# A second service, created and cancelled inside the manager's own reach.
SECOND_SERVICE_DATE = "2026-09-12"
SECOND_SEATING_START = "2026-09-12T16:00:00Z"
SECOND_SEATING_END = "2026-09-12T19:00:00Z"

# Identifiers that were never allocated to any row. They are used on purpose:
# a request whose role is wrong must be refused before any lookup runs.
UNALLOCATED_TABLE_ID = "00000000-0000-4000-8000-0000000000a1"
UNALLOCATED_EXCEPTION_ID = "00000000-0000-4000-8000-0000000000a2"
OTHER_UNALLOCATED_EXCEPTION_ID = "00000000-0000-4000-8000-0000000000a3"
CREDIT_EXPIRY = "2027-01-01T00:00:00Z"


def _refused_for_role(attempts):
    """Assert every attempt in the mapping was refused for the acting role."""
    for label, response in attempts.items():
        assert response.status_code == 403, (
            f"{label} should have been refused with HTTP 403, got "
            f"{response.status_code}: {response.text}"
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)


def _guest_world(api):
    """A published Thursday service carrying one 20-seat class, one add-on and
    one guest who owns nothing yet.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name="Corner Guest Rights House",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        goodwill_credit_cap_cents=20000,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    manager = make_restaurant_headers(restaurant["id"])
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
        service_date=SERVICE_DATE,
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=TURN_TIME_MINUTES,
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
    guest = FX.create_guest(api, display_name="Rights Guest")
    return {
        "restaurant": restaurant,
        "restaurant_id": restaurant["id"],
        "manager_headers": manager,
        "package": package,
        "package_id": package["id"],
        "add_on": add_on,
        "add_on_id": add_on["id"],
        "service": service,
        "service_id": service["id"],
        "ticket_class_id": ticket_class["id"],
        "guest": guest,
        "guest_id": guest["id"],
        "guest_headers": make_guest_headers(guest["id"]),
    }


class TestGuestWritesOnItsOwnTicket:
    """Every write reserved to the buying role, driven by the owning guest."""

    def test_guest_holds_seats_notes_a_restriction_and_renames_the_ticket(self, api):
        """Buying, annotating and renaming all land for the owning guest.

        "A `Guest` is a diner who buys tickets, prepays them, appends add-ons,
        records dietary notes, changes the name on a ticket, transfers it,
        cancels it, joins waitlists and redeems goodwill credit." The three
        writes exercised here are asserted through their own declared effects:
        "`ticket_subtotal_cents` is `price_locked_per_cover_cents` multiplied by
        `party_size`.", "A new note begins with `ack_status` `PENDING`,
        `reject_reason_code` null, `amend_count` at 0 and `acked_by_user_id`
        null." and, for the rename, "Nothing else moves: no ledger row is
        written, no seat counter changes, no roll-up is touched."

        Design: Corner/rbac/rbac_guest_exclusive_writes_all_succeed_for_the_owning_guest
        """
        world = _guest_world(api)
        guest_headers = world["guest_headers"]
        class_version = FX.ticket_class_version(
            api, world["ticket_class_id"], guest_headers
        )

        reservation = validate_success(
            api.create_reservation(
                F.reservation_payload(
                    world["ticket_class_id"],
                    world["guest_id"],
                    class_version,
                    party_size=2,
                    primary_guest_name="Rights Guest",
                ),
                guest_headers,
            ),
            201,
        )
        assert reservation["price_locked_per_cover_cents"] == 12000
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=24000,
            add_on_total=0,
            service_charge=1740,
            grand_total=25740,
            deposit_due=7722,
            amount_paid=0,
        )
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")
        assert reservation["name_change_count"] == 0

        note = validate_success(
            api.create_dietary_note(
                reservation["id"],
                F.dietary_note_payload(
                    guest_index=1,
                    restriction_code="GLUTEN",
                    severity="INFO",
                    note_text="Coeliac, no bread service",
                ),
                guest_headers,
            ),
            201,
        )
        assert note["prep_minutes"] == 0
        assert note["ack_status"] == "PENDING"
        assert note["guest_index"] == 1
        assert note["amend_count"] == 0
        assert note["reject_reason_code"] is None
        assert note["acked_by_user_id"] is None

        renamed = validate_success(
            api.change_name(
                reservation["id"],
                F.name_change_payload("Rights Guest Renamed"),
                guest_headers,
            ),
            200,
        )
        assert renamed["primary_guest_name"] == "Rights Guest Renamed"
        assert renamed["name_change_count"] == 1
        # The rename re-prices nothing and re-holds nothing.
        assert renamed["price_locked_per_cover_cents"] == 12000
        assert renamed["grand_total_cents"] == 25740
        assert FX.ledger_rows(api, reservation["id"], guest_headers) == []
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=2, released=0, available=18, status="OPEN"
        )

    def test_guest_appends_an_add_on_line_rounded_on_that_line_alone(self, api):
        """The guest's add-on line re-prices the reservation it belongs to.

        "The ticket line and each add-on line are charged independently, each
        rounded half up on its own, and the rounded per-line figures are then
        summed." The unfrozen deposit follows the new total, because "When the
        mode is `DEPOSIT` and the deposit has not yet been frozen, it is
        `grand_total_cents` multiplied by the package's `deposit_bp`, divided by
        10000, rounded half up."

        Design: Corner/rbac/rbac_guest_exclusive_writes_all_succeed_for_the_owning_guest
        """
        world = _guest_world(api)
        guest_headers = world["guest_headers"]
        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Rights Guest",
        )
        FX.add_dietary_note(
            api,
            reservation["id"],
            world["guest_id"],
            guest_index=1,
            restriction_code="GLUTEN",
            severity="INFO",
            note_text="Coeliac, no bread service",
        )

        version = FX.reservation_version(api, reservation["id"], guest_headers)
        line = validate_success(
            api.append_add_on_line(
                reservation["id"],
                F.add_on_line_payload(world["add_on_id"], version, qty=1),
                guest_headers,
            ),
            201,
        )
        assert line["qty"] == 1
        assert line["unit_price_cents_locked"] == 4500
        assert line["line_subtotal_cents"] == 4500
        # 4500 * 725 / 10000 is 326.25, rounded half up on this line alone.
        assert line["line_service_charge_cents"] == 326
        assert line["line_prep_minutes"] == 4
        assert line["ack_required"] is False

        updated = FX.read_reservation(api, reservation["id"], guest_headers)
        A.assert_money_breakdown(
            updated,
            ticket_subtotal=24000,
            add_on_total=4500,
            service_charge=2066,
            grand_total=30566,
            deposit_due=9170,
            amount_paid=0,
        )
        assert updated["deposit_frozen"] is False
        # 2 covers * 12 minutes, plus 0 for the INFO note, plus 1 unit * 4.
        assert updated["prep_minutes_total"] == 28

    def test_guest_pays_confirms_and_works_the_waitlist_of_the_same_service(self, api):
        """Prepayment, confirmation and both waitlist writes land for the owner.

        "A payment on a still-unpaid reservation that brings the cumulative
        `amount_paid_cents` to at least `deposit_due_cents` but leaves it
        strictly below `grand_total_cents` writes a `DEPOSIT_CHARGE` row with
        `memo_code` `GUEST_PREPAY` and moves the money dimension `UNPAID →
        DEPOSIT_PAID`, with `balance_due_cents` recomputed as
        `grand_total_cents` less `amount_paid_cents`." Afterwards "A new entry
        starts `WAITING` with `offer_round` at 0, `offered_reservation_id` and
        `offer_expires_at_utc` null, and its `priority_score` computed
        immediately." and "The `WAITING → WITHDRAWN` edge simply moves the entry
        to `WITHDRAWN` with no other effect."

        Design: Corner/rbac/rbac_guest_exclusive_writes_all_succeed_for_the_owning_guest
        """
        world = _guest_world(api)
        guest_headers = world["guest_headers"]
        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Rights Guest",
        )
        FX.append_add_on_line(
            api, reservation["id"], world["guest_id"], world["add_on_id"], qty=1
        )

        paid = get_success_data(
            api.take_payment(reservation["id"], F.payment_payload(9170), guest_headers)
        )
        A.assert_payment_status(paid, "DEPOSIT_PAID")
        assert paid["amount_paid_cents"] == 9170
        assert paid["balance_due_cents"] == 21396
        A.assert_fulfillment_status(paid, "PENDING")
        rows = FX.ledger_rows(api, reservation["id"], guest_headers)
        assert [row["kind"] for row in rows] == ["DEPOSIT_CHARGE"]
        assert rows[0]["memo_code"] == "GUEST_PREPAY"
        assert rows[0]["amount_cents"] == 9170

        confirmed = validate_success(
            api.confirm_reservation(reservation["id"], guest_headers), 200
        )
        A.assert_fulfillment_status(confirmed, "CONFIRMED")
        assert confirmed["hold_expires_at_utc"] is None
        assert confirmed["deposit_frozen"] is True
        assert confirmed["deposit_due_cents"] == 9170
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=2, held=0, released=0, available=18, status="OPEN"
        )

        # A CONFIRMED ticket on this service is not a waitlist row, so joining
        # the queue for a larger party is still open to the same guest.
        entry = validate_success(
            api.create_waitlist_entry(
                F.waitlist_entry_payload(
                    world["service_id"],
                    world["guest_id"],
                    party_size=4,
                    requested_package_id=world["package_id"],
                ),
                guest_headers,
            ),
            201,
        )
        assert entry["status"] == "WAITING"
        assert entry["offer_round"] == 0
        assert entry["offered_reservation_id"] is None
        assert entry["offer_expires_at_utc"] is None
        # A base of 1000 plus 50 per cover of a party of four.
        assert entry["priority_score"] == 1200

        withdrawn = validate_success(
            api.withdraw_waitlist_entry(entry["id"], guest_headers), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        still_confirmed = FX.read_reservation(api, reservation["id"], guest_headers)
        A.assert_fulfillment_status(still_confirmed, "CONFIRMED")
        A.assert_payment_status(still_confirmed, "DEPOSIT_PAID")


def _guest_denial_world(api):
    """The same published Thursday service, with the guest already holding a
    PENDING party of two carrying one ALLERGY note. No table, refund exception
    or goodwill credit has ever been created.
    """
    world = _guest_world(api)
    reservation = FX.hold_seats(
        api,
        world["ticket_class_id"],
        world["guest_id"],
        party_size=2,
        primary_guest_name="Denial Guest",
    )
    note = FX.add_dietary_note(
        api,
        reservation["id"],
        world["guest_id"],
        guest_index=1,
        restriction_code="NUT",
        severity="ALLERGY",
        note_text="Severe nut allergy",
    )
    world["reservation"] = reservation
    world["reservation_id"] = reservation["id"]
    world["note_id"] = note["id"]
    return world


class TestGuestCannotReachOtherRolesWrites:
    """The buying role stops at the edge of its own endpoint list."""

    def test_guest_cannot_drive_catalogue_or_inventory_writes(self, api):
        """Six manager-only catalogue and inventory writes are all refused.

        "A `RestaurantManager` is the front-of-house operator who registers
        tables, publishes the experience catalogue, creates and publishes
        services, allocates ticket classes, re-tiers demand, runs release runs,
        and works the floor by assigning tables, seating parties, completing
        them and declaring no-shows." For a caller outside that list, "If the
        acting role is not among the roles listed for the endpoint being called,
        the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_guest_cannot_perform_manager_kitchen_care_or_admin_exclusive_ops
        """
        world = _guest_denial_world(api)
        guest_headers = world["guest_headers"]

        attempts = {
            "create_table": api.create_table(
                F.table_payload(
                    world["restaurant_id"], table_code="T1", seats_min=2, seats_max=4
                ),
                guest_headers,
            ),
            "create_service": api.create_service(
                F.service_payload(
                    world["restaurant_id"],
                    service_date="2026-09-11",
                    meal_period="LUNCH",
                    seating_start_utc="2026-09-11T16:00:00Z",
                    seating_end_utc="2026-09-11T19:00:00Z",
                    turn_time_minutes=90,
                    seats_capacity=10,
                ),
                guest_headers,
            ),
            "publish_service": api.publish_service(world["service_id"], guest_headers),
            "set_demand_tier": api.set_demand_tier(
                world["service_id"], F.demand_tier_payload("PEAK"), guest_headers
            ),
            "release_run": api.release_run(world["service_id"], guest_headers),
            "pause_ticket_class": api.pause_ticket_class(
                world["ticket_class_id"], guest_headers
            ),
        }
        _refused_for_role(attempts)

        # Publishing an already-published service and releasing before the lead
        # window would both be state failures; the role check ran first, so the
        # service and its class are exactly as setup left them.
        service = FX.read_service(api, world["service_id"], world["manager_headers"])
        assert service["status"] == "PUBLISHED"
        assert service["demand_tier"] == "STANDARD"
        assert service["release_run_count"] == 0
        assert service["seats_released_total"] == 0
        ticket_class = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager_headers"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=2, released=0, available=18, status="OPEN"
        )
        tables, _meta = validate_paginated(
            api.list_restaurant_tables(world["restaurant_id"], world["manager_headers"])
        )
        assert tables == []

    def test_guest_cannot_drive_floor_or_kitchen_writes(self, api):
        """Table assignment, seating, no-show and the kitchen ack are refused.

        "A `KitchenLead` is the back-of-house lead whose only write authority is
        acknowledging or prep-rejecting dietary notes." The role check is
        settled before any identifier in the path is looked up, since "The
        acting role appears in the endpoint's authorized role list, on every
        endpoint — otherwise `ERR_UNAUTHORIZED`." precedes "Every identifier in
        the request path exists, validated left to right, on every endpoint that
        has a path identifier — otherwise the matching not-found code from §2.9."

        Design: Corner/rbac/rbac_guest_cannot_perform_manager_kitchen_care_or_admin_exclusive_ops
        """
        world = _guest_denial_world(api)
        guest_headers = world["guest_headers"]

        attempts = {
            # The table id was never allocated, and the reservation is PENDING
            # rather than CONFIRMED or SEATED: neither failure is reached.
            "assign_table": api.assign_table(
                world["reservation_id"],
                F.assign_table_payload(UNALLOCATED_TABLE_ID, SEATING_START),
                guest_headers,
            ),
            "seat_reservation": api.seat_reservation(
                world["reservation_id"], guest_headers
            ),
            "declare_no_show": api.declare_no_show(
                world["reservation_id"], guest_headers
            ),
            "ack_dietary_note": api.ack_dietary_note(
                world["note_id"], F.ack_payload("ACCEPT"), guest_headers
            ),
        }
        _refused_for_role(attempts)

        reservation = FX.read_reservation(api, world["reservation_id"], guest_headers)
        A.assert_fulfillment_status(reservation, "PENDING")
        assert reservation["assigned_table_id"] is None
        assert reservation["seat_from_utc"] is None
        assert reservation["seat_to_utc"] is None
        note = FX.read_note(api, world["note_id"], guest_headers)
        assert note["ack_status"] == "PENDING"
        assert note["acked_by_user_id"] is None
        assert note["amend_count"] == 0

    def test_guest_cannot_drive_care_or_platform_writes(self, api):
        """Adjudication, credit issue, onboarding, the sweep and the clock all fail.

        "A `PlatformAdmin` onboards restaurants and guests, drives the hold
        sweep, and sets the server's logical clock." Because the refusal lands
        before anything is applied, the clock never moves, and a first payment
        is still inside the hold: "For a `PENDING` reservation, the logical
        clock is strictly before `hold_expires_at_utc`, on confirm, payment and
        waitlist claim — otherwise `ERR_HOLD_EXPIRED`."

        Design: Corner/rbac/rbac_guest_cannot_perform_manager_kitchen_care_or_admin_exclusive_ops
        """
        world = _guest_denial_world(api)
        guest_headers = world["guest_headers"]

        attempts = {
            "decide_refund_exception": api.decide_refund_exception(
                UNALLOCATED_EXCEPTION_ID,
                F.decide_payload(decision="DENIED", decision_note_code="OUT_OF_POLICY"),
                guest_headers,
            ),
            "create_goodwill_credit": api.create_goodwill_credit(
                F.goodwill_credit_payload(
                    OTHER_UNALLOCATED_EXCEPTION_ID, 1000, CREDIT_EXPIRY
                ),
                guest_headers,
            ),
            "create_guest": api.create_guest(
                F.guest_payload(
                    email="shadow-onboard@corner.test", display_name="Shadow Guest"
                ),
                guest_headers,
            ),
            "hold_sweep": api.hold_sweep(
                world["service_id"], guest_headers, {"close_service": False}
            ),
            "set_clock": api.set_clock("2026-09-11T03:00:00Z", guest_headers),
        }
        _refused_for_role(attempts)

        guests, _meta = validate_paginated(api.list_guests(ADMIN_HEADERS, {"limit": 100}))
        assert all(
            row["email"] != "shadow-onboard@corner.test" for row in guests
        ), "the refused onboarding must not have created a guest"

        # The clock still reads the setup instant, so the hold placed at
        # 2026-09-01T00:00:00Z has not lapsed and the deposit is payable.
        paid = get_success_data(
            api.take_payment(
                world["reservation_id"], F.payment_payload(7722), guest_headers
            )
        )
        A.assert_payment_status(paid, "DEPOSIT_PAID")
        assert paid["amount_paid_cents"] == 7722
        assert paid["balance_due_cents"] == 18018


def _manager_world(api):
    """Everything the front-of-house role builds for itself: the catalogue, one
    service published and re-tiered twice, one class paused and resumed, and two
    tables. Each raw response is kept so the declared status codes can be read
    back.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name="Corner Manager Reach House",
        service_charge_bp=725,
        hold_ttl_minutes=20,
        offer_ttl_minutes=15,
        max_offer_rounds=2,
        no_show_grace_minutes=30,
        goodwill_credit_cap_cents=20000,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    manager = make_restaurant_headers(restaurant["id"])
    guest_a = FX.create_guest(api, display_name="Reach Guest A")
    guest_b = FX.create_guest(api, display_name="Reach Guest B")

    responses = {}
    responses["package"] = api.create_package(
        F.package_payload(
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
        ),
        manager,
    )
    package = validate_success(responses["package"], 201)

    responses["add_on"] = api.create_add_on(
        F.add_on_payload(
            restaurant["id"],
            name="Wine Pairing",
            price_cents=8500,
            prep_minutes_per_unit=2,
            max_qty_per_cover=2,
            order_cutoff_minutes=1440,
            requires_kitchen_ack=False,
        ),
        manager,
    )
    add_on = validate_success(responses["add_on"], 201)

    responses["service"] = api.create_service(
        F.service_payload(
            restaurant["id"],
            service_date=SERVICE_DATE,
            meal_period="DINNER",
            seating_start_utc=SEATING_START,
            seating_end_utc=SEATING_END,
            turn_time_minutes=TURN_TIME_MINUTES,
            seats_capacity=20,
            demand_tier="STANDARD",
            unsold_release_bp=5000,
            release_lead_minutes=180,
            waitlist_policy="FAIR_QUEUE",
            kitchen_prep_capacity_minutes=600,
        ),
        manager,
    )
    draft_service = validate_success(responses["service"], 201)

    responses["ticket_class"] = api.create_ticket_class(
        F.ticket_class_payload(
            draft_service["id"],
            package["id"],
            seats_allocated=20,
            min_party_size=1,
            max_party_size=8,
        ),
        manager,
    )
    ticket_class = validate_success(responses["ticket_class"], 201)

    responses["publish"] = api.publish_service(draft_service["id"], manager)
    published_service = validate_success(responses["publish"], 200)

    responses["tier_peak"] = api.set_demand_tier(
        draft_service["id"], F.demand_tier_payload("PEAK"), manager
    )
    peak_service = validate_success(responses["tier_peak"], 200)
    class_at_peak = FX.read_ticket_class(api, ticket_class["id"], manager)

    responses["tier_standard"] = api.set_demand_tier(
        draft_service["id"], F.demand_tier_payload("STANDARD"), manager
    )
    standard_service = validate_success(responses["tier_standard"], 200)
    class_at_standard = FX.read_ticket_class(api, ticket_class["id"], manager)

    responses["pause"] = api.pause_ticket_class(ticket_class["id"], manager)
    paused_class = validate_success(responses["pause"], 200)
    responses["resume"] = api.resume_ticket_class(ticket_class["id"], manager)
    resumed_class = validate_success(responses["resume"], 200)

    responses["table_one"] = api.create_table(
        F.table_payload(
            restaurant["id"],
            table_code="T1",
            seats_min=2,
            seats_max=4,
            turn_buffer_minutes=15,
        ),
        manager,
    )
    table_one = validate_success(responses["table_one"], 201)
    responses["table_two"] = api.create_table(
        F.table_payload(
            restaurant["id"],
            table_code="T2",
            seats_min=2,
            seats_max=4,
            turn_buffer_minutes=15,
        ),
        manager,
    )
    table_two = validate_success(responses["table_two"], 201)

    return {
        "restaurant_id": restaurant["id"],
        "manager_headers": manager,
        "guest_a": guest_a,
        "guest_b": guest_b,
        "package": package,
        "package_id": package["id"],
        "add_on": add_on,
        "service_id": draft_service["id"],
        "draft_service": draft_service,
        "published_service": published_service,
        "peak_service": peak_service,
        "standard_service": standard_service,
        "class_at_peak": class_at_peak,
        "class_at_standard": class_at_standard,
        "paused_class": paused_class,
        "resumed_class": resumed_class,
        "ticket_class_id": ticket_class["id"],
        "ticket_class": ticket_class,
        "table_one": table_one,
        "table_two": table_two,
        "responses": responses,
    }


def _two_confirmed_parties(api, world):
    """One fully paid party of two and one deposit-paid party of two, both
    CONFIRMED on the manager's own class.
    """
    paid_in_full = FX.confirmed_reservation(
        api,
        world["ticket_class_id"],
        world["guest_a"]["id"],
        party_size=2,
        pay_full=True,
        primary_guest_name="Reach Guest A",
    )
    on_deposit = FX.confirmed_reservation(
        api,
        world["ticket_class_id"],
        world["guest_b"]["id"],
        party_size=2,
        pay_full=False,
        primary_guest_name="Reach Guest B",
    )
    return paid_in_full, on_deposit


class TestRestaurantManagerOwnedWrites:
    """The fifteen writes the front-of-house role holds exclusively."""

    def test_manager_builds_the_catalogue_and_tunes_its_own_inventory(self, api):
        """Ten catalogue and inventory writes land for the owning restaurant.

        "A service is born in `status` `DRAFT`, and its nine
        money-and-inventory roll-ups — `release_run_count`,
        `seats_released_total`, `last_release_released_count`,
        `last_release_promoted_count`, `covers_confirmed`,
        `gross_charged_cents`, `refunded_cents`, `forfeited_cents` and
        `net_settled_cents` — all begin at 0." Re-tiering reaches the class,
        because "Supplying a new `demand_tier` for a published service re-runs
        the per-cover pricing calculation for every one of its ticket classes,
        refreshing `list_price_per_cover_cents` and
        `release_price_per_cover_cents` across the board." Pausing keeps the
        pool intact: "Crucially, pausing **releases nothing**: `seats_available`,
        `seats_held`, `seats_sold` and `seats_released` all stand exactly as they
        were, which is what makes `PAUSED` sticky at the top of the ladder rather
        than a state the arithmetic can fall out of."

        Design: Corner/rbac/rbac_restaurant_manager_drives_all_fifteen_exclusive_operations
        """
        world = _manager_world(api)
        responses = world["responses"]

        # Endpoints that mint a resource answer 201; endpoints that modify one
        # answer 200.
        for label in ("package", "add_on", "service", "ticket_class", "table_one",
                      "table_two"):
            assert responses[label].status_code == 201, label
        for label in ("publish", "tier_peak", "tier_standard", "pause", "resume"):
            assert responses[label].status_code == 200, label

        assert world["draft_service"]["status"] == "DRAFT"
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
            assert world["draft_service"][rollup] == 0, rollup
        assert world["published_service"]["status"] == "PUBLISHED"

        # PEAK on a Thursday is 14500 basis points against a 12000-cent cover;
        # STANDARD returns it to 10000 basis points.
        assert world["peak_service"]["demand_tier"] == "PEAK"
        assert world["class_at_peak"]["list_price_per_cover_cents"] == 17400
        assert world["class_at_peak"]["release_price_per_cover_cents"] == 14790
        assert world["standard_service"]["demand_tier"] == "STANDARD"
        assert world["class_at_standard"]["list_price_per_cover_cents"] == 12000
        assert world["class_at_standard"]["release_price_per_cover_cents"] == 10200

        assert world["paused_class"]["status"] == "PAUSED"
        A.assert_seat_pool(
            world["paused_class"],
            sold=0,
            held=0,
            released=0,
            available=20,
            status="PAUSED",
        )
        assert world["resumed_class"]["status"] == "OPEN"

        for table in (world["table_one"], world["table_two"]):
            assert table["restaurant_id"] == world["restaurant_id"]
            assert table["seats_min"] == 2
            assert table["seats_max"] == 4
            assert table["turn_buffer_minutes"] == 15

    def test_manager_works_the_floor_from_assignment_to_no_show(self, api):
        """Assigning, seating, completing and no-showing all land for the owner.

        "Seating pins `seat_to_utc` to `seat_from_utc` plus the service's
        `turn_time_minutes`; until the party is seated, `seat_to_utc` is null."
        "Completing credits the guest's `completed_reservations_count` by 1 —
        which lifts that guest's waitlist standing everywhere, as §3.8 explains
        — reconciles the service's `gross_charged_cents` against the
        reservation's ledger, and advances the reservation's `version` by one."
        For the party that never arrives, "`cancel_settlement_basis` is set to
        `NO_SHOW_FULL` and the whole of `amount_paid_cents` is forfeited by
        writing a single `FORFEITURE` row with `memo_code` `NO_SHOW`, which
        drives the money dimension to `FORFEITED`."

        Design: Corner/rbac/rbac_restaurant_manager_drives_all_fifteen_exclusive_operations
        """
        world = _manager_world(api)
        manager = world["manager_headers"]
        paid_in_full, on_deposit = _two_confirmed_parties(api, world)

        # Both tier flips preceded every sale, so the locked price is the
        # STANDARD one.
        assert paid_in_full["price_locked_per_cover_cents"] == 12000
        assert paid_in_full["grand_total_cents"] == 25740
        assert paid_in_full["amount_paid_cents"] == 25740
        assert on_deposit["amount_paid_cents"] == 7722

        assigned_one = validate_success(
            api.assign_table(
                paid_in_full["id"],
                F.assign_table_payload(world["table_one"]["id"], SEATING_START),
                manager,
            ),
            200,
        )
        assert assigned_one["assigned_table_id"] == world["table_one"]["id"]
        assert F.parse_iso(assigned_one["seat_from_utc"]) == F.parse_iso(SEATING_START)
        assert assigned_one["seat_to_utc"] is None
        assigned_two = validate_success(
            api.assign_table(
                on_deposit["id"],
                F.assign_table_payload(world["table_two"]["id"], SEATING_START),
                manager,
            ),
            200,
        )
        assert assigned_two["assigned_table_id"] == world["table_two"]["id"]

        FX.set_clock(api, SEATING_START)
        seated = validate_success(api.seat_reservation(paid_in_full["id"], manager), 200)
        A.assert_fulfillment_status(seated, "SEATED")
        assert F.parse_iso(seated["seat_to_utc"]) == F.parse_iso(SEAT_TO_UTC)

        completed = validate_success(
            api.complete_reservation(paid_in_full["id"], manager), 200
        )
        A.assert_fulfillment_status(completed, "COMPLETED")
        A.assert_payment_status(completed, "FULLY_PAID")
        guest_a = FX.read_guest(api, world["guest_a"]["id"], ADMIN_HEADERS)
        assert guest_a["completed_reservations_count"] == 1

        FX.set_clock(api, NO_SHOW_AT)
        no_show = validate_success(api.declare_no_show(on_deposit["id"], manager), 200)
        A.assert_fulfillment_status(no_show, "NO_SHOW")
        A.assert_payment_status(no_show, "FORFEITED")
        assert no_show["cancel_settlement_basis"] == "NO_SHOW_FULL"
        assert no_show["forfeited_cents"] == 7722
        assert no_show["refunded_cents"] == 0
        rows = FX.ledger_rows(api, on_deposit["id"], ADMIN_HEADERS)
        forfeitures = [row for row in rows if row["kind"] == "FORFEITURE"]
        assert len(forfeitures) == 1
        assert forfeitures[0]["amount_cents"] == 7722
        assert forfeitures[0]["memo_code"] == "NO_SHOW"
        guest_b = FX.read_guest(api, world["guest_b"]["id"], ADMIN_HEADERS)
        assert guest_b["no_show_strikes"] == 1

        service = FX.read_service(api, world["service_id"], manager)
        assert service["covers_confirmed"] == 2
        assert service["forfeited_cents"] == 7722
        assert service["gross_charged_cents"] == 33462
        assert service["net_settled_cents"] == 33462
        ticket_class = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            ticket_class, sold=2, held=0, released=0, available=18, status="OPEN"
        )

    def test_manager_releases_unsold_seats_and_cancels_a_service_it_owns(self, api):
        """The release run and the service cancellation both land for the owner.

        "For each, it computes the number of seats to release as the floor of
        that class's `seats_available` multiplied by the service's
        `unsold_release_bp`, divided by 10000 — a partial seat is never released
        — debits that count from `seats_available`, credits it to
        `seats_released`, adds it to the run's release total, and re-evaluates
        the class against the precedence ladder." "At the end of the run the
        service's `release_run_count` is credited by 1, its
        `seats_released_total` is credited by the run's release total, its
        `last_release_released_count` is set to that total, and its
        `last_release_promoted_count` is set to the number of entries promoted."
        Cancelling a different service of the same restaurant reaches only that
        service: "Both `CLOSED` and `CANCELLED` are terminal for a service."

        Design: Corner/rbac/rbac_restaurant_manager_drives_all_fifteen_exclusive_operations
        """
        world = _manager_world(api)
        manager = world["manager_headers"]
        _paid_in_full, on_deposit = _two_confirmed_parties(api, world)
        FX.assign_table(
            api,
            world["restaurant_id"],
            on_deposit["id"],
            world["table_two"]["id"],
            SEATING_START,
        )
        FX.set_clock(api, NO_SHOW_AT)
        FX.declare_no_show(api, world["restaurant_id"], on_deposit["id"])

        # 18 unsold seats, half of them released: floor(18 * 5000 / 10000).
        released_service = validate_success(
            api.release_run(world["service_id"], manager), 200
        )
        assert released_service["last_release_released_count"] == 9
        assert released_service["last_release_promoted_count"] == 0
        assert released_service["release_run_count"] == 1
        assert released_service["seats_released_total"] == 9
        ticket_class = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            ticket_class, sold=2, held=0, released=9, available=9, status="RELEASED"
        )
        A.assert_seat_pool_identity(ticket_class)

        second_service = validate_success(
            api.create_service(
                F.service_payload(
                    world["restaurant_id"],
                    service_date=SECOND_SERVICE_DATE,
                    meal_period="LUNCH",
                    seating_start_utc=SECOND_SEATING_START,
                    seating_end_utc=SECOND_SEATING_END,
                    turn_time_minutes=90,
                    seats_capacity=10,
                ),
                manager,
            ),
            201,
        )
        second_class = validate_success(
            api.create_ticket_class(
                F.ticket_class_payload(
                    second_service["id"], world["package_id"], seats_allocated=10
                ),
                manager,
            ),
            201,
        )
        validate_success(api.publish_service(second_service["id"], manager), 200)
        cancelled = validate_success(
            api.cancel_service(second_service["id"], manager, {"reason_code": "STAFFING"}),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert (
            FX.read_ticket_class(api, second_class["id"], manager)["status"] == "CLOSED"
        )

        # The service that was released is untouched by the other's cancellation.
        assert FX.read_service(api, world["service_id"], manager)["status"] == "PUBLISHED"
        assert (
            FX.read_ticket_class(api, world["ticket_class_id"], manager)["status"]
            == "RELEASED"
        )


def _manager_denial_world(api):
    """The manager's own published service, one table, and a guest-owned PENDING
    party of two carrying one ALLERGY note, plus a second guest to transfer to.
    """
    world = _guest_world(api)
    table = FX.create_table(
        api,
        world["restaurant_id"],
        table_code="T1",
        seats_min=2,
        seats_max=4,
        turn_buffer_minutes=15,
    )
    recipient = FX.create_guest(api, display_name="Denial Recipient")
    reservation = FX.hold_seats(
        api,
        world["ticket_class_id"],
        world["guest_id"],
        party_size=2,
        primary_guest_name="Owner Guest",
    )
    note = FX.add_dietary_note(
        api,
        reservation["id"],
        world["guest_id"],
        guest_index=1,
        restriction_code="SHELLFISH",
        severity="ALLERGY",
        note_text="Severe shellfish allergy",
    )
    world["table"] = table
    world["recipient"] = recipient
    world["recipient_id"] = recipient["id"]
    world["reservation"] = reservation
    world["reservation_id"] = reservation["id"]
    world["note_id"] = note["id"]
    return world


class TestRestaurantManagerCannotReachGuestOrCareWrites:
    """Owning the restaurant is not owning the ticket."""

    def test_manager_cannot_book_pay_confirm_cancel_rename_or_transfer(self, api):
        """The six writes that move a guest's own ticket are all refused.

        "A `Guest` is a diner who buys tickets, prepays them, appends add-ons,
        records dietary notes, changes the name on a ticket, transfers it,
        cancels it, joins waitlists and redeems goodwill credit." The same six
        writes are shared with care, not with the floor: "A `GuestServices`
        operator is the customer-care agent who files, adjudicates and
        compensates refund exceptions, and who may also take payments, cancel
        bookings and apply credit on a guest's behalf."

        Design: Corner/rbac/rbac_restaurant_manager_cannot_book_pay_ack_or_adjudicate
        """
        world = _manager_denial_world(api)
        manager = world["manager_headers"]
        class_version = FX.ticket_class_version(
            api, world["ticket_class_id"], manager
        )

        attempts = {
            "create_reservation": api.create_reservation(
                F.reservation_payload(
                    world["ticket_class_id"],
                    world["recipient_id"],
                    class_version,
                    party_size=2,
                    primary_guest_name="Denial Recipient",
                ),
                manager,
            ),
            "take_payment": api.take_payment(
                world["reservation_id"], F.payment_payload(7722), manager
            ),
            "confirm_reservation": api.confirm_reservation(
                world["reservation_id"], manager
            ),
            "cancel_reservation": api.cancel_reservation(
                world["reservation_id"], manager
            ),
            "change_name": api.change_name(
                world["reservation_id"],
                F.name_change_payload("Manager Renamed"),
                manager,
            ),
            "transfer_reservation": api.transfer_reservation(
                world["reservation_id"],
                F.transfer_payload(world["recipient_id"]),
                manager,
            ),
        }
        _refused_for_role(attempts)

        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")
        assert reservation["primary_guest_name"] == "Owner Guest"
        assert reservation["name_change_count"] == 0
        assert reservation["guest_id"] == world["guest_id"]
        assert reservation["amount_paid_cents"] == 0
        assert FX.ledger_rows(api, world["reservation_id"], ADMIN_HEADERS) == []
        ticket_class = FX.read_ticket_class(api, world["ticket_class_id"], manager)
        A.assert_seat_pool(
            ticket_class, sold=0, held=2, released=0, available=18, status="OPEN"
        )

    def test_manager_cannot_annotate_a_ticket_or_acknowledge_the_kitchen(self, api):
        """Notes, add-on lines, both kitchen verbs and the waitlist are refused.

        "A `KitchenLead` is the back-of-house lead whose only write authority is
        acknowledging or prep-rejecting dietary notes." The add-on attempt
        echoes the reservation's live version, so nothing but the role can
        explain the refusal — the version guard sits far downstream of it, since
        "The acting role appears in the endpoint's authorized role list, on every
        endpoint — otherwise `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_restaurant_manager_cannot_book_pay_ack_or_adjudicate
        """
        world = _manager_denial_world(api)
        manager = world["manager_headers"]
        live_version = FX.reservation_version(
            api, world["reservation_id"], world["guest_headers"]
        )

        attempts = {
            "create_dietary_note": api.create_dietary_note(
                world["reservation_id"],
                F.dietary_note_payload(
                    guest_index=2,
                    restriction_code="DAIRY",
                    severity="INFO",
                    note_text="No cream",
                ),
                manager,
            ),
            "append_add_on_line": api.append_add_on_line(
                world["reservation_id"],
                F.add_on_line_payload(world["add_on_id"], live_version, qty=1),
                manager,
            ),
            "ack_dietary_note": api.ack_dietary_note(
                world["note_id"], F.ack_payload("ACCEPT"), manager
            ),
            "amend_dietary_note": api.amend_dietary_note(
                world["note_id"],
                F.amend_payload(restriction_code="GLUTEN", severity="INFO"),
                manager,
            ),
            "create_waitlist_entry": api.create_waitlist_entry(
                F.waitlist_entry_payload(
                    world["service_id"], world["recipient_id"], party_size=2
                ),
                manager,
            ),
        }
        _refused_for_role(attempts)

        note = FX.read_note(api, world["note_id"], world["guest_headers"])
        assert note["ack_status"] == "PENDING"
        assert note["acked_by_user_id"] is None
        assert note["amend_count"] == 0
        assert note["restriction_code"] == "SHELLFISH"
        notes, _notes_meta = validate_paginated(
            api.list_reservation_dietary_notes(
                world["reservation_id"], world["guest_headers"], {"limit": 100}
            )
        )
        assert [row["id"] for row in notes] == [world["note_id"]]

        reservation = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        assert reservation["version"] == live_version
        assert reservation["add_on_total_cents"] == 0
        # 2 covers * 12 minutes plus the 6 minutes of the ALLERGY note.
        assert reservation["prep_minutes_total"] == 30
        entries, _entries_meta = validate_paginated(
            api.list_waitlist_entries(
                ADMIN_HEADERS, {"service_id": world["service_id"], "limit": 100}
            )
        )
        assert entries == []

    def test_manager_cannot_adjudicate_compensate_onboard_or_sweep(self, api):
        """Care and platform writes are refused while the manager's reads stand.

        "A `GuestServices` operator is the customer-care agent who files,
        adjudicates and compensates refund exceptions, and who may also take
        payments, cancel bookings and apply credit on a guest's behalf." "A
        `PlatformAdmin` onboards restaurants and guests, drives the hold sweep,
        and sets the server's logical clock." The refusals are per endpoint
        rather than a blanket lockout, since "Endpoints that bring a new resource
        into existence answer with HTTP 201; endpoints that read or modify an
        existing resource answer with HTTP 200."

        Design: Corner/rbac/rbac_restaurant_manager_cannot_book_pay_ack_or_adjudicate
        """
        world = _manager_denial_world(api)
        manager = world["manager_headers"]
        version_before = FX.reservation_version(
            api, world["reservation_id"], world["guest_headers"]
        )

        attempts = {
            "create_refund_exception": api.create_refund_exception(
                F.refund_exception_payload(world["reservation_id"], 1000), manager
            ),
            # Neither adjudication target was ever allocated; the role check
            # settles the request before the lookup.
            "decide_refund_exception": api.decide_refund_exception(
                UNALLOCATED_EXCEPTION_ID,
                F.decide_payload(
                    decision="APPROVED",
                    approved_cents=1000,
                    decision_note_code="POLICY_EXCEPTION",
                ),
                manager,
            ),
            "create_goodwill_credit": api.create_goodwill_credit(
                F.goodwill_credit_payload(
                    OTHER_UNALLOCATED_EXCEPTION_ID, 1000, CREDIT_EXPIRY
                ),
                manager,
            ),
            "create_guest": api.create_guest(
                F.guest_payload(
                    email="manager-onboard@corner.test", display_name="Onboard Attempt"
                ),
                manager,
            ),
            "hold_sweep": api.hold_sweep(
                world["service_id"], manager, {"close_service": False}
            ),
        }
        _refused_for_role(attempts)

        exceptions, _exception_meta = validate_paginated(
            api.list_refund_exceptions(
                ADMIN_HEADERS,
                {"reservation_id": world["reservation_id"], "limit": 100},
            )
        )
        assert exceptions == []
        guests, _guest_meta = validate_paginated(
            api.list_guests(ADMIN_HEADERS, {"limit": 100})
        )
        assert all(row["email"] != "manager-onboard@corner.test" for row in guests)

        # The same manager still reads the reservation of its own service.
        read_back = validate_success(
            api.get_reservation(world["reservation_id"], manager), 200
        )
        A.assert_fulfillment_status(read_back, "PENDING")
        A.assert_payment_status(read_back, "UNPAID")
        assert read_back["version"] == version_before
        assert read_back["hold_expires_at_utc"] is not None
