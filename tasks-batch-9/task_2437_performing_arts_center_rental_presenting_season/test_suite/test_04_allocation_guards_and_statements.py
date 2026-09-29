"""Input guards that fire exactly at their limit, the fixed precedence between
an authorization check and a lookup, the conditional equipment add-on in the
deposit rule, and the computed box-office statement.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    book_rental_engagement,
    clear_presented_rider,
    confirm,
    engagement_version,
    make_rental_client_contact_headers,
    negotiate_and_accept_fee,
    put_on_sale,
    read_engagement,
    register_artist,
    register_equipment_item,
    register_hall,
    register_rental_client,
    reserve_equipment_line,
    review_rider,
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

ABSENT_ENGAGEMENT_ID = "11111111-1111-4111-8111-111111111111"


class TestSeatAllocationLimit:

    def test_allocation_reaching_capacity_exactly_is_admitted(self):
        """Tiers of 800 and 400 seats fill a 1,200-seat house exactly and are
        both admitted; one more seat exceeds the house and is refused. The
        refusal leaves the engagement with two tiers and its ticketing dimension
        where the first tier put it.

        PRD: "the sum of `seats_allocated` across the engagement's `ACTIVE`
        tiers, counting the tier being added, may not exceed the hall's
        `seat_capacity`"

        Design: Corner/validations/seat_allocation_exactly_equal_to_capacity_passes
        """
        space = register_hall(seat_capacity=1_200)
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])

        orchestra = validate_success(api_client.create_price_tier(
            engagement["id"],
            {"tier_name": "ORCH", "seats_allocated": 800,
             "base_price_cents": 10_000, "price_ceiling_cents": 15_000,
             "dynamic_pricing_enabled": False, "subscription_eligible": False},
            BOX_OFFICE), expected_status=201)
        assert orchestra["available_qty"] == 800

        mezzanine = validate_success(api_client.create_price_tier(
            engagement["id"],
            {"tier_name": "MEZZ", "seats_allocated": 400,
             "base_price_cents": 6_000, "price_ceiling_cents": 9_000,
             "dynamic_pricing_enabled": False, "subscription_eligible": False},
            BOX_OFFICE), expected_status=201)
        assert mezzanine["available_qty"] == 400

        validate_error(api_client.create_price_tier(
            engagement["id"],
            {"tier_name": "BALCONY", "seats_allocated": 1,
             "base_price_cents": 3_000, "price_ceiling_cents": 3_000,
             "dynamic_pricing_enabled": False, "subscription_eligible": False},
            BOX_OFFICE), "ERR_SEAT_ALLOCATION_EXCEEDS_CAPACITY")

        tiers, meta = validate_paginated(
            api_client.list_engagement_price_tiers(engagement["id"], BOX_OFFICE))
        assert meta["total_count"] == 2
        assert read_engagement(engagement["id"])["ticketing_status"] == "TIERS_DRAFT"


class TestCheckPrecedence:

    def test_unauthorized_role_is_reported_before_the_missing_engagement(self):
        """The same request against the same absent engagement reports two
        different failures depending on the acting role: a role that may never
        open a negotiation round is refused before the path is resolved, while
        the authorized role gets the lookup failure.

        PRD: "when several checks could all reject the same request, only the
        highest-priority one is reported."

        Design: Corner/validations/role_check_outranks_engagement_existence_check
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        version_before = engagement["version"]

        payload = {"offered_fee_cents": 300_000,
                   "offered_artist_share_pct": 0.10,
                   "expected_engagement_version": 1}

        validate_error(api_client.open_fee_negotiation(
            ABSENT_ENGAGEMENT_ID, payload, BOX_OFFICE),
            "ERR_ROLE_NOT_PERMITTED")

        validate_error(api_client.open_fee_negotiation(
            ABSENT_ENGAGEMENT_ID, payload, DIRECTOR),
            "ERR_ENGAGEMENT_NOT_FOUND")

        after = read_engagement(engagement["id"])
        assert after["negotiation_round_count"] == 0
        assert after["version"] == version_before


class TestDepositEquipmentAddOn:

    def test_equipment_cost_is_added_only_for_a_client_already_in_arrears(self):
        """Two identical rentals differ only in the client's outstanding
        balance. Both clear a rider carrying 100,000 of additional equipment.
        The client with nothing outstanding owes 25 percent of the facility fee
        alone; the client owing 5,000 has the whole equipment cost added on top,
        undiscounted.

        PRD: "Then, and only when the client's `outstanding_balance_cents` is
        strictly greater than zero — a balance of exactly zero adds nothing —
        the engagement's `additional_equipment_cost_cents` is added on top of
        that rounded amount in full, undiscounted by the percentage."

        Design: Corner/validations/deposit_equipment_add_on_applies_only_when_client_is_in_arrears
        """
        space = register_hall(house_power_amps=400)
        item = register_equipment_item(category="POWER_DISTRO",
                                       model_name="200A Distro Rack",
                                       on_hand_qty=5, daily_rate_cents=25_000)
        settled_client = register_rental_client(org_name="Clear Account Dance",
                                                credit_rating="A")
        arrears_client = register_rental_client(org_name="Behind On Invoices Co",
                                                credit_rating="A",
                                                outstanding_balance_cents=5_000)

        settled_engagement = book_rental_engagement(
            space["id"], settled_client["id"], title="Clear Account Gala",
            load_in_day_count=0)
        arrears_engagement = book_rental_engagement(
            space["id"], arrears_client["id"], title="Arrears Gala",
            load_in_start_utc="2026-10-10T08:00:00Z",
            performance_start_utc="2026-10-11T19:00:00Z",
            performance_end_utc="2026-10-11T22:00:00Z",
            load_out_end_utc="2026-10-12T02:00:00Z",
            load_in_day_count=0)
        assert settled_engagement["facility_fee_cents"] == 500_000
        assert arrears_engagement["facility_fee_cents"] == 500_000

        for engagement, client in ((settled_engagement, settled_client),
                                   (arrears_engagement, arrears_client)):
            rider = submit_rider(engagement["id"],
                                 make_rental_client_contact_headers(client["id"]),
                                 requested_power_amps=500)
            reviewed = review_rider(rider["id"])
            assert reviewed["capability_gaps"] == ["POWER_SHORTFALL"]
            reserve_equipment_line(rider["id"], item["id"],
                                   covers_gap="POWER_SHORTFALL", qty=2,
                                   rental_days=2)
            cleared = validate_success(
                api_client.clear_tech_rider(rider["id"], TECH_DIRECTOR))
            assert cleared["review_status"] == "CLEARED"
            assert cleared["additional_equipment_cost_cents"] == 100_000

        settled_after = read_engagement(settled_engagement["id"])
        assert settled_after["additional_equipment_cost_cents"] == 100_000
        assert settled_after["deposit_required_cents"] == 125_000

        arrears_after = read_engagement(arrears_engagement["id"])
        assert arrears_after["additional_equipment_cost_cents"] == 100_000
        assert arrears_after["deposit_required_cents"] == 225_000

        item_after = validate_success(
            api_client.get_equipment_item(item["id"], ADMIN))
        assert item_after["reserved_qty"] == 4
        assert item_after["on_hand_qty"] == 5


class TestBoxOfficeStatement:

    def test_statement_aggregates_the_engagement_tiers_and_stores_nothing(self):
        """The statement is a live aggregate over the engagement's tiers: two
        tiers of 100 and 50 seats, ten tickets sold at 10,000, and the patron's
        capital contribution of 200 a seat taken back out of the adjusted
        gross.

        PRD: "`adjusted_gross_cents` as `box_office_gross_cents` less
        `restoration_fees_cents`. The statement is computed live from current
        counters and stores nothing."

        Design: Corner/endpoints/box_office_statement_matches_tier_aggregates
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        negotiate_and_accept_fee(engagement["id"], artist["id"], 300_000, 0.10)
        clear_presented_rider(engagement["id"], artist["id"])
        orchestra = add_price_tier(engagement["id"], tier_name="ORCH",
                                   seats_allocated=100,
                                   base_price_cents=10_000,
                                   price_ceiling_cents=15_000)
        add_price_tier(engagement["id"], tier_name="MEZZ", seats_allocated=50,
                       base_price_cents=5_000, price_ceiling_cents=7_500)
        assess_risk(engagement["id"])
        confirm(engagement["id"])
        put_on_sale(engagement["id"])
        version_on_sale = engagement_version(engagement["id"])

        validate_success(api_client.create_ticket_sale(
            orchestra["id"], {"qty": 10, "channel": "WEB"}, BOX_OFFICE),
            expected_status=201)

        statement = validate_success(
            api_client.get_box_office_statement(engagement["id"], BOX_OFFICE))
        assert statement["engagement_id"] == engagement["id"]
        assert statement["tier_count"] == 2
        assert statement["seats_allocated_total"] == 150
        assert statement["sold_qty_total"] == 10
        assert statement["subscription_held_qty_total"] == 0
        assert statement["single_ticket_gross_cents"] == 100_000
        assert statement["subscription_revenue_cents"] == 0
        assert statement["box_office_gross_cents"] == 100_000
        assert statement["restoration_fees_cents"] == 2_000
        assert statement["adjusted_gross_cents"] == 98_000

        settlements, meta = validate_paginated(
            api_client.list_engagement_settlements(engagement["id"], FINANCE))
        assert meta["total_count"] == 0
        assert settlements == []
        assert engagement_version(engagement["id"]) == version_on_sale
