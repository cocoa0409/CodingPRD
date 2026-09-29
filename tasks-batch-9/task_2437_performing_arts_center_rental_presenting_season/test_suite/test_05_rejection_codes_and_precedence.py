"""Rejections: entity-specific lookup failures, body-reference resolution,
booking guards, engagement-type guards, inventory and gap coverage, the pinned
tier-before-engagement ticketing precedence and repeat attempts on
already-advanced rows.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    book_rental_engagement,
    call_crew,
    clear_presented_rider,
    confirm,
    create_presented_engagement_payload,
    create_rental_engagement_payload,
    make_artist_representative_headers,
    make_rental_client_contact_headers,
    negotiate_and_accept_fee,
    put_on_sale,
    read_engagement,
    read_price_tier,
    record_deposit,
    register_artist,
    register_equipment_item,
    register_hall,
    register_rental_client,
    register_union_department,
    report_hours,
    reserve_equipment_line,
    review_rider,
    set_clock,
    submit_rider,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]
AGENCY = TEST_USERS["artist_representative_headers"]


class TestNotFoundFamily:

    def test_each_absent_path_resource_reports_its_own_not_found_code(self):
        """Every kind of path-referenced row has its own lookup code, so an
        absent identifier names the resource that could not be found rather than
        a generic failure.

        PRD: "Path-referenced resources of other kinds yield
        `ERR_NEGOTIATION_NOT_FOUND`, `ERR_TECH_RIDER_NOT_FOUND`,
        `ERR_LABOR_CALL_NOT_FOUND`, `ERR_PRICE_TIER_NOT_FOUND`,
        `ERR_SETTLEMENT_NOT_FOUND` or `ERR_SUBSCRIPTION_PACKAGE_NOT_FOUND` as
        appropriate, all with HTTP 404."

        Design: Corner/errors/nonexistent_path_resources_return_entity_specific_not_found_codes
        """
        attempts = [
            (api_client.counter_fee_negotiation(
                NON_EXISTENT_UUID,
                {"counter_fee_cents": 250_000, "counter_artist_share_pct": 0.15},
                AGENCY), "ERR_NEGOTIATION_NOT_FOUND"),
            (api_client.get_tech_rider(NON_EXISTENT_UUID, TECH_DIRECTOR),
             "ERR_TECH_RIDER_NOT_FOUND"),
            (api_client.report_labor_hours(
                NON_EXISTENT_UUID,
                {"actual_hours": 4.0, "meal_break_taken": True},
                TECH_DIRECTOR), "ERR_LABOR_CALL_NOT_FOUND"),
            (api_client.get_price_tier(NON_EXISTENT_UUID, BOX_OFFICE),
             "ERR_PRICE_TIER_NOT_FOUND"),
            (api_client.sell_subscription_orders(
                NON_EXISTENT_UUID, {"order_qty": 1}, BOX_OFFICE),
             "ERR_SUBSCRIPTION_PACKAGE_NOT_FOUND"),
            (api_client.reconcile_settlement_expenses(
                NON_EXISTENT_UUID, {"actual_marketing_cents": 0}, FINANCE),
             "ERR_SETTLEMENT_NOT_FOUND"),
            (api_client.get_artist(NON_EXISTENT_UUID, DIRECTOR),
             "ERR_PARTY_NOT_FOUND"),
            (api_client.get_union_department(NON_EXISTENT_UUID, ADMIN),
             "ERR_DEPARTMENT_NOT_FOUND"),
        ]

        for response, expected_error_id in attempts:
            body = validate_error(response, expected_error_id)
            assert body["message"]

    def test_body_references_are_resolved_before_the_payload_is_applied(self):
        """A dangling identifier inside the request body is reported as its own
        lookup failure, and no row is written for the request that carried it.

        PRD: "Body-referenced identifiers are resolved after path identifiers:
        `space_id` yields `ERR_SPACE_NOT_FOUND`, `artist_id` and
        `rental_client_id` yield `ERR_PARTY_NOT_FOUND`"

        Design: Corner/errors/body_referenced_resources_are_resolved_before_the_payload_is_applied
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])

        validate_error(api_client.create_engagement(
            create_presented_engagement_payload(NON_EXISTENT_UUID, artist["id"],
                                                title="Ghost Hall Recital"),
            DIRECTOR), "ERR_SPACE_NOT_FOUND")

        validate_error(api_client.create_engagement(
            create_presented_engagement_payload(space["id"], NON_EXISTENT_UUID,
                                                title="Ghost Artist Recital"),
            DIRECTOR), "ERR_PARTY_NOT_FOUND")

        rider = submit_rider(engagement["id"],
                             make_artist_representative_headers(artist["id"]),
                             requested_power_amps=500)
        reviewed = review_rider(rider["id"])
        assert reviewed["review_status"] == "GAP_IDENTIFIED"

        validate_error(api_client.create_equipment_line(
            rider["id"],
            {"equipment_item_id": NON_EXISTENT_UUID,
             "covers_gap": "POWER_SHORTFALL", "qty": 1, "rental_days": 1},
            TECH_DIRECTOR), "ERR_EQUIPMENT_ITEM_NOT_FOUND")

        _, meta = validate_paginated(api_client.list_engagements(DIRECTOR))
        assert meta["total_count"] == 1


class TestBookingGuards:

    def test_offline_hall_and_out_of_window_performance_are_both_refused(self):
        """A hall registered `OFFLINE` refuses a booking outright, and a
        presented performance outside the artist's routing window is refused
        even on an active hall; the same artist inside the window books
        normally.

        PRD: "the closed performance interval running from
        `performance_start_utc` to `performance_end_utc` must lie inside the
        artist's routing window"

        Design: Corner/errors/offline_hall_and_out_of_routing_window_bookings_are_refused
        """
        offline_space = register_hall(name="Studio Theater", status="OFFLINE")
        client = register_rental_client()
        validate_error(api_client.create_engagement(
            create_rental_engagement_payload(offline_space["id"], client["id"],
                                             title="Dark House Rental"),
            RENTAL_MANAGER), "ERR_SPACE_OFFLINE")

        space = register_hall(name="Grand Hall")
        artist = register_artist(
            routing_window_start_utc="2026-09-01T00:00:00Z",
            routing_window_end_utc="2026-09-30T23:59:59Z")

        validate_error(api_client.create_engagement(
            create_presented_engagement_payload(
                space["id"], artist["id"], title="October Out Of Window",
                load_in_start_utc="2026-10-10T08:00:00Z",
                performance_start_utc="2026-10-11T19:00:00Z",
                performance_end_utc="2026-10-11T22:00:00Z",
                load_out_end_utc="2026-10-12T02:00:00Z"),
            DIRECTOR), "ERR_ROUTING_WINDOW_VIOLATION")

        booked = validate_success(api_client.create_engagement(
            create_presented_engagement_payload(
                space["id"], artist["id"], title="September In Window",
                load_in_start_utc="2026-09-14T08:00:00Z",
                performance_start_utc="2026-09-15T19:00:00Z",
                performance_end_utc="2026-09-15T22:00:00Z",
                load_out_end_utc="2026-09-16T02:00:00Z"),
            DIRECTOR), expected_status=201)
        assert booked["lifecycle_status"] == "DRAFT"
        assert booked["financial_clearance"] == "UNASSESSED"
        assert booked["facility_fee_cents"] == 0
        assert booked["deposit_required_cents"] == 0

    def test_operations_of_the_other_engagement_type_are_refused(self):
        """Deposits belong to rentals, fee negotiations and price tiers to
        presented engagements. Each act aimed at the wrong type is refused, and
        neither engagement is touched.

        PRD: "Deposits are meaningless on a presented engagement and the attempt
        is refused with `ERR_ENGAGEMENT_TYPE_MISMATCH`."

        Design: Corner/errors/type_specific_operations_on_the_wrong_engagement_type_return_422
        """
        space = register_hall()
        artist = register_artist()
        client = register_rental_client()
        presented = book_presented_engagement(space["id"], artist["id"])
        rental = book_rental_engagement(space["id"], client["id"])

        validate_error(api_client.record_deposit(
            presented["id"], {"amount_cents": 100_000}, RENTAL_MANAGER),
            "ERR_ENGAGEMENT_TYPE_MISMATCH")

        validate_error(api_client.open_fee_negotiation(
            rental["id"],
            {"offered_fee_cents": 300_000, "offered_artist_share_pct": 0.10,
             "expected_engagement_version": rental["version"]},
            DIRECTOR), "ERR_ENGAGEMENT_TYPE_MISMATCH")

        validate_error(api_client.create_price_tier(
            rental["id"],
            {"tier_name": "ORCH", "seats_allocated": 100,
             "base_price_cents": 10_000, "price_ceiling_cents": 15_000,
             "dynamic_pricing_enabled": False, "subscription_eligible": False},
            BOX_OFFICE), "ERR_ENGAGEMENT_TYPE_MISMATCH")

        presented_after = read_engagement(presented["id"])
        assert presented_after["version"] == presented["version"]
        assert presented_after["deposit_paid_cents"] == 0

        rental_after = read_engagement(rental["id"])
        assert rental_after["version"] == rental["version"]
        assert rental_after["negotiation_round_count"] == 0
        assert rental_after["ticketing_status"] == "TICKETING_UNSET"


class TestInventoryAndGapCoverage:

    def test_reservations_beyond_the_free_stock_are_refused(self):
        """Two units on hand admit a line of two and nothing more, and the
        refused attempts leave the item's reserved counter untouched.

        PRD: "the requested `qty` may not exceed the item's `on_hand_qty` less
        its current `reserved_qty`, and an over-reservation is refused with
        `ERR_EQUIPMENT_STOCK_UNAVAILABLE`."

        Design: Corner/errors/equipment_lines_beyond_available_stock_are_refused
        """
        space = register_hall(house_power_amps=400)
        client = register_rental_client()
        owner = make_rental_client_contact_headers(client["id"])
        item = register_equipment_item(category="POWER_DISTRO",
                                       model_name="Scarce Distro",
                                       on_hand_qty=2, daily_rate_cents=25_000)

        first = book_rental_engagement(space["id"], client["id"],
                                       title="First Claim On The Distro")
        first_rider = submit_rider(first["id"], owner, requested_power_amps=500)
        review_rider(first_rider["id"])

        validate_error(api_client.create_equipment_line(
            first_rider["id"],
            {"equipment_item_id": item["id"], "covers_gap": "POWER_SHORTFALL",
             "qty": 3, "rental_days": 1}, TECH_DIRECTOR),
            "ERR_EQUIPMENT_STOCK_UNAVAILABLE")
        assert validate_success(api_client.get_equipment_item(
            item["id"], ADMIN))["reserved_qty"] == 0

        line = validate_success(api_client.create_equipment_line(
            first_rider["id"],
            {"equipment_item_id": item["id"], "covers_gap": "POWER_SHORTFALL",
             "qty": 2, "rental_days": 1}, TECH_DIRECTOR), expected_status=201)
        assert line["line_cost_cents"] == 50_000
        assert line["status"] == "RESERVED"

        second = book_rental_engagement(
            space["id"], client["id"], title="Second Claim On The Distro",
            load_in_start_utc="2026-10-10T08:00:00Z",
            performance_start_utc="2026-10-11T19:00:00Z",
            performance_end_utc="2026-10-11T22:00:00Z",
            load_out_end_utc="2026-10-12T02:00:00Z")
        second_rider = submit_rider(second["id"], owner,
                                    requested_power_amps=500)
        review_rider(second_rider["id"])
        validate_error(api_client.create_equipment_line(
            second_rider["id"],
            {"equipment_item_id": item["id"], "covers_gap": "POWER_SHORTFALL",
             "qty": 1, "rental_days": 1}, TECH_DIRECTOR),
            "ERR_EQUIPMENT_STOCK_UNAVAILABLE")

        item_after = validate_success(
            api_client.get_equipment_item(item["id"], ADMIN))
        assert item_after["reserved_qty"] == 2

        lines, meta = validate_paginated(
            api_client.list_equipment_item_rental_lines(item["id"], ADMIN))
        assert meta["total_count"] == 1

    def test_a_gap_clears_only_once_a_line_covers_that_very_gap(self):
        """A power shortfall is not cleared by an empty rider, and not cleared
        by a comfort item that covers nothing; only a line whose `covers_gap`
        names the shortfall lets the rider join at CLEARED, and the cleared
        rider then carries every reserved line's cost.

        PRD: "every element of `capability_gaps` other than
        `RIGGING_NEAR_LIMIT` must be matched by at least one `RESERVED` line of
        this rider whose `covers_gap` equals that element."

        Design: Corner/errors/clearing_an_uncovered_gap_requires_a_line_that_matches_the_gap
        """
        space = register_hall(house_power_amps=400)
        client = register_rental_client()
        distro = register_equipment_item(category="POWER_DISTRO",
                                         model_name="Company Switch Distro",
                                         on_hand_qty=4,
                                         daily_rate_cents=25_000)
        comfort = register_equipment_item(category="AUDIO_PACKAGE",
                                          model_name="Wardrobe Steamer Package",
                                          on_hand_qty=4,
                                          daily_rate_cents=5_000)
        engagement = book_rental_engagement(space["id"], client["id"])
        rider = submit_rider(engagement["id"],
                             make_rental_client_contact_headers(client["id"]),
                             requested_power_amps=500)
        reviewed = review_rider(rider["id"])
        assert reviewed["capability_gaps"] == ["POWER_SHORTFALL"]

        validate_error(api_client.clear_tech_rider(rider["id"], TECH_DIRECTOR),
                       "ERR_GAP_NOT_COVERED")

        reserve_equipment_line(rider["id"], comfort["id"], covers_gap="NONE",
                               qty=1, rental_days=2)
        validate_error(api_client.clear_tech_rider(rider["id"], TECH_DIRECTOR),
                       "ERR_GAP_NOT_COVERED")

        reserve_equipment_line(rider["id"], distro["id"],
                               covers_gap="POWER_SHORTFALL", qty=1,
                               rental_days=2)
        cleared = validate_success(
            api_client.clear_tech_rider(rider["id"], TECH_DIRECTOR))
        assert cleared["review_status"] == "CLEARED"
        assert cleared["additional_equipment_cost_cents"] == 60_000

        after = read_engagement(engagement["id"])
        assert after["additional_equipment_cost_cents"] == 60_000
        assert after["deposit_required_cents"] == 175_000


class TestTicketingPrecedence:

    def test_tier_state_is_reported_before_engagement_state(self):
        """Before the box office opens a sale reports the engagement's ticketing
        dimension; once open, an oversized order reports the tier's seats; and
        after settlement has closed both the engagement and its tiers, the tier
        code wins over the engagement code.

        PRD: "A sale against a `CLOSED` price tier therefore reports
        `ERR_TIER_CLOSED` even when the engagement's `ticketing_status` is also
        `CLOSED`"

        Design: Corner/errors/ticketing_errors_follow_the_pinned_tier_before_engagement_precedence
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        negotiate_and_accept_fee(engagement["id"], artist["id"], 300_000, 0.10)
        clear_presented_rider(engagement["id"], artist["id"])
        tier = add_price_tier(engagement["id"], tier_name="ORCH",
                              seats_allocated=100, base_price_cents=10_000,
                              price_ceiling_cents=15_000)
        assess_risk(engagement["id"])
        confirm(engagement["id"])

        validate_error(api_client.create_ticket_sale(
            tier["id"], {"qty": 1, "channel": "WEB"}, BOX_OFFICE),
            "ERR_TICKETING_NOT_ON_SALE")

        put_on_sale(engagement["id"])
        validate_error(api_client.create_ticket_sale(
            tier["id"], {"qty": 101, "channel": "WEB"}, BOX_OFFICE),
            "ERR_TIER_SOLD_OUT")
        assert read_price_tier(tier["id"])["sold_qty"] == 0

        sale = validate_success(api_client.create_ticket_sale(
            tier["id"], {"qty": 10, "channel": "WEB"}, BOX_OFFICE),
            expected_status=201)
        assert sale["unit_price_cents"] == 10_000

        set_clock("2026-10-12T00:00:00Z")
        validate_success(api_client.open_settlement(engagement["id"], FINANCE),
                         expected_status=201)
        assert read_engagement(engagement["id"])["ticketing_status"] == "CLOSED"
        assert read_price_tier(tier["id"])["status"] == "CLOSED"

        validate_error(api_client.create_ticket_sale(
            tier["id"], {"qty": 1, "channel": "WEB"}, BOX_OFFICE),
            "ERR_TIER_CLOSED")

        final_tier = read_price_tier(tier["id"])
        assert final_tier["sold_qty"] == 10
        assert final_tier["gross_cents"] == 100_000
        assert final_tier["available_qty"] == 90
        assert final_tier["status"] == "CLOSED"


class TestRepeatedActs:

    def test_singleton_children_and_out_of_state_repeats_report_their_own_codes(self):
        """A second rider, a second hours report, a second settlement and a
        finalization attempted from DRAFT each report the code that names what
        actually blocked them, and none of them alters the row it targeted.

        PRD: "An engagement admits at most one settlement, and a second attempt
        is refused with `ERR_DUPLICATE_SETTLEMENT`."

        Design: Corner/errors/duplicate_child_rows_and_out_of_state_repeats_return_state_specific_codes
        """
        space = register_hall()
        client = register_rental_client(credit_rating="A")
        owner = make_rental_client_contact_headers(client["id"])
        department = register_union_department(department="STAGEHANDS",
                                              roster_size=10,
                                              straight_hourly_rate_cents=5_000)
        engagement = book_rental_engagement(space["id"], client["id"])
        crew_call = call_crew(engagement["id"], department["id"], crew_size=2,
                              call_start_utc="2026-10-01T08:00:00Z",
                              call_end_utc="2026-10-01T12:00:00Z")

        rider = submit_rider(engagement["id"], owner)
        review_rider(rider["id"])
        validate_success(api_client.clear_tech_rider(rider["id"], TECH_DIRECTOR))

        validate_error(api_client.submit_tech_rider(
            engagement["id"],
            {"submitted_rigging_kg": 2_000, "requested_power_amps": 300,
             "requested_dmx_universes": 3, "requires_orchestra_pit": True},
            owner), "ERR_DUPLICATE_TECH_RIDER")

        riders, riders_meta = validate_paginated(
            api_client.list_engagement_tech_riders(engagement["id"],
                                                   TECH_DIRECTOR))
        assert riders_meta["total_count"] == 1
        assert riders[0]["submitted_rigging_kg"] == 1_000
        assert riders[0]["requested_power_amps"] == 200
        assert riders[0]["requested_dmx_universes"] == 2

        assess_risk(engagement["id"])
        record_deposit(engagement["id"], 185_000)
        confirm(engagement["id"], RENTAL_MANAGER)
        report_hours(crew_call["id"], 4.0, True)

        validate_error(api_client.report_labor_hours(
            crew_call["id"], {"actual_hours": 6.0, "meal_break_taken": False},
            TECH_DIRECTOR), "ERR_LABOR_CALL_INVALID_STATE")

        set_clock("2026-10-03T00:00:00Z")
        settlement = validate_success(
            api_client.open_settlement(engagement["id"], FINANCE),
            expected_status=201)
        validate_error(api_client.open_settlement(engagement["id"], FINANCE),
                       "ERR_DUPLICATE_SETTLEMENT")

        validate_error(api_client.finalize_settlement(settlement["id"], FINANCE),
                       "ERR_SETTLEMENT_INVALID_STATE")

        settlements, _ = validate_paginated(
            api_client.list_engagement_settlements(engagement["id"], FINANCE))
        assert settlements[0]["status"] == "DRAFT"
        assert settlements[0]["finalized_by_user_id"] is None

        assert read_engagement(engagement["id"])["lifecycle_status"] == "PERFORMED"
        calls, _ = validate_paginated(
            api_client.list_engagement_labor_calls(engagement["id"],
                                                   TECH_DIRECTOR))
        assert calls[0]["status"] == "WORKED"
        assert calls[0]["actual_cost_cents"] == 40_000

        entries, _ = validate_paginated(
            api_client.list_reserve_ledger_entries(ADMIN, {"limit": 100}))
        assert all(entry["entry_type"] != "SETTLEMENT_CONTRIBUTION"
                   for entry in entries)
