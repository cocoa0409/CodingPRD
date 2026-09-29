"""
The stored shape of each entity: defaults, derived fields, listing, and 404s.

PRD 2.5 owns the common-field block every entity but PaymentEvent carries, and
PRD 2.10 owns the order in which a malformed or dangling payload is refused.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_BOOKING_NOT_FOUND,
    ERR_CABIN_CATEGORY_NOT_FOUND,
    ERR_GROUP_BLOCK_MISMATCH,
    ERR_GUEST_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_NO_FARE_RULE_FOR_WINDOW,
    ERR_SAILING_NOT_FOUND,
    GROUP_SALES_AGENT,
    PORT_OPS_COORDINATOR,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_common_fields,
    assert_payment_event_shape,
    factories as f,
    fixtures as fx,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def test_a_new_sailing_comes_back_with_every_derived_field_initialised(api):
    """A brand-new voyage is flagged from the start, because zero RALBD is below the floor.

    PRD 3.1: "A newly created sailing lands in PLANNED with suspension_count at 0
    and suspension_reason null. Its derived block is initialised immediately:
    available_lower_berth_days_gross and available_lower_berth_days_net are both
    total_lower_berths multiplied by nights ..., occupancy_pct is 0.00,
    inventory_posture is OPEN, lower_berths_sold, third_berths_sold,
    fourth_berths_sold, gross_ticket_revenue_cents, projected_onboard_revenue_cents,
    compensation_liability_cents, confirmed_bookings_count, and
    paid_in_full_bookings_count are all 0, final_payment_risk_flag is false,
    ralbd_gross_cents and ralbd_net_cents are both 0 - and because zero revenue per
    available lower berth day sits below the alert floor described in 3.9,
    revenue_alert is true on a brand-new sailing."

    Design: Corner/entities/sailing_creation_initializes_derived_revenue_fields
    """
    fx.set_clock(api)

    sailing = validate_success(
        api.create_sailing(f.sailing_payload(voyage_code="AUR-2701"), REVENUE_MANAGER),
        201,
    )

    assert_common_fields(sailing)
    assert sailing["status"] == "PLANNED"
    assert sailing["version"] == 1
    # 200 lower berths across 7 nights.
    assert sailing["available_lower_berth_days_gross"] == 1400
    assert sailing["available_lower_berth_days_net"] == 1400
    assert float(sailing["occupancy_pct"]) == 0.0
    assert sailing["inventory_posture"] == "OPEN"
    assert sailing["lower_berths_sold"] == 0
    assert sailing["third_berths_sold"] == 0
    assert sailing["fourth_berths_sold"] == 0
    assert sailing["gross_ticket_revenue_cents"] == 0
    assert sailing["projected_onboard_revenue_cents"] == 0
    assert sailing["compensation_liability_cents"] == 0
    assert sailing["confirmed_bookings_count"] == 0
    assert sailing["paid_in_full_bookings_count"] == 0
    assert sailing["final_payment_risk_flag"] is False
    assert sailing["ralbd_gross_cents"] == 0
    assert sailing["ralbd_net_cents"] == 0
    assert sailing["revenue_alert"] is True
    assert sailing["suspension_count"] == 0
    assert sailing["suspension_reason"] is None


def test_one_allotment_read_returns_stored_and_derived_counters_together(api):
    """The read shows the requested allowance and the capped effective figure side by side.

    PRD 3.1: "On creation the availability derivation of 2.7 runs immediately, so a
    fresh allotment is returned with effective_oversell_cabins, group_held_cabins
    (0), booked_cabins (0), waitlisted_bookings_count (0), released_cabins_total
    (0), and available_cabins already populated." PRD 2.7 caps the appetite: the
    oversell ceiling is "ten percent of physical_cabins, rounded up".

    Design: Corner/entities/sailing_inventory_read_returns_stored_and_derived_counters
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)
    fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest["id"], occupancy_adults=2
    )

    inventory = validate_success(
        api.get_sailing_inventory(world.inventory["id"], REVENUE_MANAGER)
    )

    assert_common_fields(inventory)
    assert inventory["sailing_id"] == world.sailing["id"]
    assert inventory["cabin_category_id"] == world.category["id"]
    assert inventory["physical_cabins"] == 60
    assert inventory["oversell_allowance"] == 4
    # ceil(60 x 0.10) is 6, so the requested 4 is the binding arm.
    assert inventory["effective_oversell_cabins"] == 4
    assert inventory["booked_cabins"] == 1
    assert inventory["group_held_cabins"] == 0
    assert inventory["waitlisted_bookings_count"] == 0
    assert inventory["released_cabins_total"] == 0
    assert inventory["available_cabins"] == 63
    assert_capacity_identity(inventory)


def test_booking_list_pages_a_filtered_set_and_counts_the_whole_of_it(api):
    """total_count describes the filtered set; has_more describes the page.

    PRD 2.3: "Every list response carries limit, offset, total_count, and has_more
    inside the envelope's meta object, where total_count is the number of rows
    matching the filters before pagination is applied and has_more indicates whether
    rows remain beyond the current page." PRD 4 fixes the filters: the booking list
    is one where "every foreign key is a filter, so children are reachable from any
    parent id."

    Design: Corner/entities/booking_list_filters_by_sailing_and_guest_with_pagination
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    bookings = []
    for _ in range(3):
        guest = fx.make_guest(api, prior_sailings_count=0)
        bookings.append(
            fx.make_booking(
                api,
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=2,
            )
        )

    page_one, meta_one = validate_paginated(
        api.list_bookings(
            REVENUE_MANAGER,
            params={"sailing_id": world.sailing["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_bookings(
            REVENUE_MANAGER,
            params={"sailing_id": world.sailing["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2

    seen = [row["id"] for row in page_one + page_two]
    assert len(set(seen)) == 3
    assert set(seen) == {row["id"] for row in bookings}

    narrowed, meta_three = validate_paginated(
        api.list_bookings(
            REVENUE_MANAGER,
            params={
                "sailing_id": world.sailing["id"],
                "guest_id": bookings[1]["guest_id"],
            },
        )
    )
    assert meta_three["total_count"] == 1
    assert meta_three["has_more"] is False
    assert [row["id"] for row in narrowed] == [bookings[1]["id"]]

    for row in page_one + page_two:
        assert row["net_ticket_cents"] == 379990
        assert row["booking_status"] == "OPTION"


def test_unknown_ids_return_the_entity_specific_not_found(api):
    """A well-formed UUID that is simply not stored is a 404, never a 400.

    PRD 2.10 separates path existence at priority 5 - "each path id is resolved left
    to right, and the first unresolvable one determines the code:
    ERR_SAILING_NOT_FOUND, ... ERR_BOOKING_NOT_FOUND ... All carry HTTP 404" - from
    body reference existence at priority 6, whose "Codes are ERR_SAILING_NOT_FOUND,
    ERR_CABIN_CATEGORY_NOT_FOUND, ERR_GUEST_NOT_FOUND, ERR_GROUP_BLOCK_NOT_FOUND,
    ERR_PROMOTION_NOT_FOUND, at HTTP 404."

    Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found
    """
    fx.set_clock(api)
    sailing = fx.make_sailing(api, voyage_code="AUR-2701")

    validate_error(
        api.get_sailing(NON_EXISTENT_UUID, REVENUE_MANAGER), ERR_SAILING_NOT_FOUND, 404
    )
    validate_error(
        api.get_booking(NON_EXISTENT_UUID, RESERVATION_AGENT), ERR_BOOKING_NOT_FOUND, 404
    )
    validate_error(
        api.create_sailing_inventory(
            {
                "sailing_id": sailing["id"],
                "cabin_category_id": NON_EXISTENT_UUID,
                "physical_cabins": 10,
                "oversell_allowance": 0,
            },
            REVENUE_MANAGER,
        ),
        ERR_CABIN_CATEGORY_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_sailing_inventories(
            REVENUE_MANAGER, params={"sailing_id": sailing["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_payload_missing_a_required_field_is_a_shape_error_first(api):
    """Priority 4 runs before priority 6, so a doubly-broken payload reports the shape.

    PRD 2.10 puts request shape at priority 4 - "every required input field present
    ... Failures here are ERR_INVALID_REQUEST" - and body reference existence at
    priority 6. PRD 3.4 makes occupancy_adults required: the agent "supplies the
    sailing_id, the cabin_category_id being sold, the guest_id of the lead guest, and
    occupancy_adults". PRD 3.1 makes voyage_code required on a sailing.

    Design: Corner/entities/booking_without_required_fields_is_rejected
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)

    validate_error(
        api.create_booking(
            {
                "sailing_id": world.sailing["id"],
                "cabin_category_id": world.category["id"],
                "guest_id": guest["id"],
            },
            RESERVATION_AGENT,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_sailing(
            {
                "ship_code": "AURORA",
                "embark_date": "2027-05-01T17:00:00Z",
                "nights": 7,
                "total_lower_berths": 100,
            },
            REVENUE_MANAGER,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    # Missing occupancy_adults *and* an unstored sailing_id: shape wins.
    validate_error(
        api.create_booking(
            {
                "sailing_id": NON_EXISTENT_UUID,
                "cabin_category_id": world.category["id"],
                "guest_id": guest["id"],
            },
            RESERVATION_AGENT,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert fx.read_inventory(api, world.inventory["id"])["booked_cabins"] == 0
    assert fx.read_guest(api, guest["id"])["bookings_count"] == 0
    _, meta = validate_paginated(api.list_sailings(REVENUE_MANAGER))
    assert meta["total_count"] == 1


def test_optional_inputs_fall_back_to_their_declared_defaults(api):
    """Every default is load-bearing: berths, deadlines, oversell appetite, loyalty.

    PRD 3.1: "is_guarantee defaults to false ...; lower_berths defaults to 2 and must
    be either 1 or 2 ...; and upgrade_to_category_id defaults to null", "A category
    with no upgrade target has an upgrade_chain_length of 0", "final_payment_days_before
    ... defaults to 75, and deposit_due_days_after_booking ... defaults to 7", and
    "an optional oversell_allowance defaulting to 0". PRD 3.4: "An optional
    prior_sailings_count, defaulting to 0 ... fewer than 1 gives NONE and 0.00", with
    "bookings_count ... starts at 0."

    Design: Corner/entities/optional_fields_take_their_declared_defaults
    """
    fx.set_clock(api)

    category = validate_success(
        api.create_cabin_category(
            {
                "code": "OV",
                "tier_rank": 2,
                "max_occupancy": 4,
                "onboard_spend_lower_per_night_cents": 11000,
                "onboard_spend_upper_per_night_cents": 7000,
            },
            REVENUE_MANAGER,
        ),
        201,
    )
    assert category["lower_berths"] == 2
    assert category["is_guarantee"] is False
    assert category["upgrade_to_category_id"] is None
    assert category["upgrade_chain_length"] == 0

    sailing = validate_success(
        api.create_sailing(
            {
                "ship_code": "AURORA",
                "voyage_code": "DEF-2701",
                "embark_date": "2027-01-10T17:00:00Z",
                "nights": 7,
                "total_lower_berths": 200,
            },
            REVENUE_MANAGER,
        ),
        201,
    )
    assert sailing["final_payment_days_before"] == 75
    assert sailing["deposit_due_days_after_booking"] == 7

    inventory = validate_success(
        api.create_sailing_inventory(
            {
                "sailing_id": sailing["id"],
                "cabin_category_id": category["id"],
                "physical_cabins": 10,
            },
            REVENUE_MANAGER,
        ),
        201,
    )
    assert inventory["oversell_allowance"] == 0
    assert inventory["effective_oversell_cabins"] == 0
    assert inventory["available_cabins"] == 10

    guest = validate_success(
        api.create_guest(
            {"full_name": "Bo Chen", "email": "bo.defaults@example.com"},
            RESERVATION_AGENT,
        ),
        201,
    )
    assert guest["prior_sailings_count"] == 0
    assert guest["loyalty_tier"] == "NONE"
    assert float(guest["repeat_guest_offer_pct"]) == 0.0
    assert guest["bookings_count"] == 0


def test_allotment_counters_move_only_through_other_entities_writes(api):
    """A 10-cabin allotment with an appetite of 5 sells 11 cabins, not 15.

    PRD 2.7: "effective_oversell_cabins is the smaller of the allotment's requested
    oversell_allowance and ten percent of physical_cabins rounded up ... sellable
    capacity is physical_cabins plus effective_oversell_cabins", and
    "available_cabins is sellable capacity minus booked_cabins minus
    group_held_cabins, floored at zero." PRD 3.1 keeps the counters out of the client's
    hands: an allotment is created "with a payload naming the sailing_id, the
    cabin_category_id, and the physical_cabins count ..., plus an optional
    oversell_allowance."

    Design: Corner/entities/allotment_counters_are_computed_and_never_taken_from_input
    """
    world = fx.simple_world(
        api,
        voyage_code="CMP-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=5,
        fare_overrides=FLAT_FARE_50K,
    )
    fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        cabins_held=2,
        review_date="2026-09-01T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest["id"], occupancy_adults=1
    )

    inventory = validate_success(
        api.get_sailing_inventory(world.inventory["id"], REVENUE_MANAGER)
    )
    assert inventory["oversell_allowance"] == 5
    # ceil(10 x 0.10) is 1, so capacity is 11 however large the appetite.
    assert inventory["effective_oversell_cabins"] == 1
    assert inventory["booked_cabins"] == 1
    assert inventory["group_held_cabins"] == 2
    assert inventory["waitlisted_bookings_count"] == 0
    assert inventory["available_cabins"] == 8
    assert inventory["released_cabins_total"] == 0
    assert_capacity_identity(inventory)

    # A solo traveller pays 175 percent of 50,000; the 25,000 floor beats 20 percent.
    assert booking["net_ticket_cents"] == 87500
    assert booking["deposit_due_cents"] == 25000


def test_common_fields_are_server_minted_and_version_moves_once_per_write(api):
    """One mutation, one increment, and created_at is untouched by it.

    PRD 2.5: "Every resource the API stores is addressed by an id, which is a
    server-minted UUID with no type prefix, and carries a created_at timestamp - an
    ISO 8601 UTC instant with three fractional digits ... additionally carry
    updated_at, refreshed on every mutation of the row, and version, an integer that
    starts at 1 on creation and increments by exactly 1 on every mutation of that
    row."

    Design: Corner/entities/common_fields_are_server_minted_and_version_increments_per_write
    """
    fx.set_clock(api)
    category = fx.make_guarantee_category(api)
    sailing = fx.make_sailing(api, voyage_code="SYS-2701")
    created = fx.make_inventory(
        api, sailing["id"], category["id"], physical_cabins=60, oversell_allowance=4
    )

    assert_common_fields(created)
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert "_" not in created["id"], "the id carries no type prefix"
    assert is_iso8601_timestamp(created["created_at"])

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    patched = validate_success(
        api.patch_sailing_inventory(
            created["id"],
            {"oversell_allowance": 2, "expected_inventory_version": created["version"]},
            REVENUE_MANAGER,
        )
    )

    assert patched["version"] == 2
    assert patched["created_at"] == created["created_at"]
    assert patched["updated_at"] > patched["created_at"]
    assert is_iso8601_timestamp(patched["updated_at"])
    assert patched["oversell_allowance"] == 2
    assert patched["effective_oversell_cabins"] == 2
    assert patched["available_cabins"] == 62


def test_enum_and_range_violations_are_four_hundred_shape_errors(api):
    """Five different constraints, one tier, one code - and never a domain code.

    PRD 2.10, priority 4: "every enum value inside its declared set; every integer
    inside its declared range; discount_pct greater than 0 and at most 0.5;
    occupancy_adults either 1 or 2; ...
    window_open_days_to_sail strictly greater than window_close_days_to_sail; ...
    max_occupancy between 2 and 4 inclusive. Failures here are ERR_INVALID_REQUEST."
    PRD 3.8 fixes the disruption enum: the kind is "PORT_CANCELLED,
    PORT_SUBSTITUTED, or ITINERARY_SHORTENED".

    Design: Corner/entities/enum_and_range_constraints_are_rejected_on_create
    """
    world = fx.simple_world(
        api,
        voyage_code="RNG-2701",
        fare_overrides={
            "window_open_days_to_sail": 730,
            "window_close_days_to_sail": 0,
        },
    )
    guest = fx.make_guest(api, prior_sailings_count=0)
    sailing_version = world.sailing["version"]

    # max_occupancy above the [2, 4] range.
    validate_error(
        api.create_cabin_category(
            {
                "code": "SUITE",
                "tier_rank": 3,
                "max_occupancy": 5,
                "onboard_spend_lower_per_night_cents": 15000,
                "onboard_spend_upper_per_night_cents": 9000,
            },
            REVENUE_MANAGER,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    # discount_pct above the 0.5 ceiling.
    validate_error(
        api.create_promotion(
            f.promotion_payload(
                world.sailing["id"],
                sailing_version,
                code="TOOBIG",
                discount_pct=0.6,
                starts_on="2026-08-05T00:00:00Z",
                ends_on="2026-08-10T00:00:00Z",
                max_redemptions=10,
            ),
            REVENUE_MANAGER,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    # An inverted fare window: the open bound must exceed the close bound.
    validate_error(
        api.create_fare_rule(
            f.fare_rule_payload(
                world.sailing["id"],
                world.category["id"],
                window_open_days_to_sail=60,
                window_close_days_to_sail=120,
            ),
            REVENUE_MANAGER,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    # occupancy_adults outside {1, 2}.
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=3,
            ),
            RESERVATION_AGENT,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    # A disruption kind outside the declared set.
    validate_error(
        api.create_itinerary_change(
            f.itinerary_change_payload(
                world.sailing["id"],
                kind="PORT_DELAYED",
                affected_port_code="GRC",
                compensation_policy="OBC_ONLY",
            ),
            PORT_OPS_COORDINATOR,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    _, category_meta = validate_paginated(api.list_cabin_categories(REVENUE_MANAGER))
    assert category_meta["total_count"] == 1
    _, promotion_meta = validate_paginated(
        api.list_promotions(REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]})
    )
    assert promotion_meta["total_count"] == 0
    _, rule_meta = validate_paginated(
        api.list_fare_rules(REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]})
    )
    assert rule_meta["total_count"] == 1
    _, change_meta = validate_paginated(
        api.list_itinerary_changes(
            PORT_OPS_COORDINATOR, params={"sailing_id": world.sailing["id"]}
        )
    )
    assert change_meta["total_count"] == 0

    # PRD 3.2: only a created campaign "increments the parent sailing's version by 1".
    assert fx.read_sailing(api, world.sailing["id"])["version"] == sailing_version


def test_the_payment_ledger_appends_and_never_rewrites(api):
    """A second payment adds a row; the first keeps the status it was posted under.

    PRD 2.8: "Posting a payment ... appends one PaymentEvent carrying booking_id, that
    kind and amount_cents, a posted_at stamped from the current instant, and a
    resulting_payment_status recording the booking's payment_status immediately after
    the event was applied", and "every row it returns is immutable - this is the one
    entity in the system with neither updated_at nor version."

    Design: Corner/entities/payment_event_is_append_only_with_no_version_field
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest["id"], occupancy_adults=2
    )
    first = validate_success(
        api.post_payment(
            booking["id"], f.payment_payload("DEPOSIT", 75998), RESERVATION_AGENT
        ),
        201,
    )

    second = validate_success(
        api.post_payment(
            booking["id"], f.payment_payload("PARTIAL", 1000), RESERVATION_AGENT
        ),
        201,
    )

    events, meta = validate_paginated(
        api.list_payment_events(booking["id"], RESERVATION_AGENT)
    )
    assert meta["total_count"] == 2
    assert [event["id"] for event in events] == [first["id"], second["id"]]

    assert events[0]["kind"] == "DEPOSIT"
    assert events[0]["amount_cents"] == 75998
    assert events[0]["resulting_payment_status"] == "DEPOSIT_PAID"
    assert events[1]["kind"] == "PARTIAL"
    assert events[1]["amount_cents"] == 1000
    assert events[1]["resulting_payment_status"] == "DEPOSIT_PAID"

    for event in events:
        assert_payment_event_shape(event)
        assert event["booking_id"] == booking["id"]
        assert "posted_at" in event
        assert "note" in event

    after = fx.read_booking(api, booking["id"])
    assert after["amount_paid_cents"] == 76998
    assert after["balance_due_cents"] == 302992
    assert after["payment_status"] == "DEPOSIT_PAID"


def test_payment_events_are_scoped_to_their_parent_booking(api):
    """The ledger is addressed only through its parent, and a missing parent is a 404.

    PRD 2.8: "The ledger of one booking is readable by a RevenueManager, a
    ReservationAgent, or the owning Guest, optionally filtered by kind, ordered by
    posted_at ascending and then created_at ascending." PRD 2.10 makes the unstored
    parent a path-existence failure at priority 5, code ERR_BOOKING_NOT_FOUND.

    Design: Corner/entities/payment_events_are_scoped_to_their_parent_booking
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest_a = fx.make_guest(api, prior_sailings_count=0)
    guest_b = fx.make_guest(api, prior_sailings_count=0)
    booking_a = fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest_a["id"], occupancy_adults=2
    )
    booking_b = fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest_b["id"], occupancy_adults=2
    )
    fx.pay(api, booking_a["id"], "DEPOSIT", 75998)
    fx.pay(api, booking_a["id"], "PARTIAL", 1000)
    fx.pay(api, booking_b["id"], "DEPOSIT", 75998)

    rows_a, meta_a = validate_paginated(
        api.list_payment_events(booking_a["id"], RESERVATION_AGENT)
    )
    assert meta_a["total_count"] == 2
    for row in rows_a:
        assert row["booking_id"] == booking_a["id"]

    rows_b, meta_b = validate_paginated(
        api.list_payment_events(
            booking_b["id"], RESERVATION_AGENT, params={"kind": "PARTIAL"}
        )
    )
    assert meta_b["total_count"] == 0
    assert rows_b == []

    validate_error(
        api.list_payment_events(NON_EXISTENT_UUID, RESERVATION_AGENT),
        ERR_BOOKING_NOT_FOUND,
        404,
    )

    assert fx.read_booking(api, booking_a["id"])["amount_paid_cents"] == 76998
    assert fx.read_booking(api, booking_b["id"])["amount_paid_cents"] == 75998


def test_booking_foreign_keys_resolve_in_the_declared_order(api):
    """Two dangling ids report the first in the declared order, and existence beats integrity.

    PRD 2.10, priority 6: "every foreign key in the body resolves to a stored row,
    checked in this declared field order: sailing_id first, then cabin_category_id or
    target_cabin_category_id, then guest_id, then group_block_id, then promotion_id."
    Priority 17 then adds integrity for rows that do exist: "a booking's group_block_id
    must reference a block whose sailing_id and cabin_category_id both equal the
    booking's (ERR_GROUP_BLOCK_MISMATCH); and a fare rule, group block, or booking may
    not reference a cabin_category_id that has no allotment row on that sailing ...
    (ERR_CATEGORY_NOT_ON_SAILING)." The category-presence code is tier 17, so it only
    surfaces where no earlier tier can fire - not on booking creation.

    Design: Corner/entities/booking_foreign_keys_are_validated_in_the_declared_order
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    other = fx.simple_world(
        api,
        voyage_code="OTH-2701",
        embark_date="2027-02-10T17:00:00Z",
        total_lower_berths=100,
        category=world.category,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    foreign_block = fx.make_group_block(
        api,
        other.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        agency_name="Other Voyage Agency",
        cabins_held=2,
        review_date="2026-09-01T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    unlisted = fx.make_category(api, code="OV", tier_rank=2, max_occupancy=4)
    guest = fx.make_guest(api, prior_sailings_count=0)

    validate_error(
        api.create_booking(
            f.booking_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID, occupancy_adults=2
            ),
            RESERVATION_AGENT,
        ),
        ERR_SAILING_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                NON_EXISTENT_UUID,
                occupancy_adults=2,
            ),
            RESERVATION_AGENT,
        ),
        ERR_GUEST_NOT_FOUND,
        404,
    )
    # The category is stored, so its absence from this voyage is a 422, not a 404.
    # Which 422 is fixed by PRD 2.10: fare-window coverage is tier 15 and the
    # category-presence integrity check is tier 17, and "the first failure
    # encountered is the response". A category with no allotment on the voyage can
    # never carry a fare rule there either - tier 17 forbids creating one - so the
    # tier-15 window failure is always what a booking on an unlisted category sees.
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"], unlisted["id"], guest["id"], occupancy_adults=2
            ),
            RESERVATION_AGENT,
        ),
        ERR_NO_FARE_RULE_FOR_WINDOW,
        422,
    )
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=2,
                group_block_id=foreign_block["id"],
            ),
            RESERVATION_AGENT,
        ),
        ERR_GROUP_BLOCK_MISMATCH,
        422,
    )

    _, meta = validate_paginated(
        api.list_bookings(REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.read_guest(api, guest["id"])["bookings_count"] == 0
