"""Edge cases of the convention-center pricing, ranking and counter formulas."""

from test_helpers import (
    ANALYST_ONE,
    BALLROOM_B,
    BALLROOM_C,
    EVENT_SERVICES,
    HALL_A,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SETTLEMENT_ANALYST,
    ApiErrorId,
    UserRole,
    approve_catering,
    assert_crew_hours,
    assert_fields,
    assert_money_cents,
    booking_payload,
    confirm_definite,
    confirm_first_option,
    create_booking,
    execute_license,
    labor_call_payload,
    make_headers,
    open_show,
    order_service,
    place_hold,
    propose_catering,
    publish_window,
    read_booking,
    read_catering_arrangement,
    read_client,
    read_hold,
    read_labor_call,
    read_service_order,
    read_settlement,
    read_space,
    read_union_jurisdiction,
    register_client,
    register_space,
    register_union_local,
    register_vendor,
    set_clock,
    setup_event_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_citywide_discount_applies_to_the_gross_rental_not_the_daily_rate(api):
    """PRD §3.2: "`contracted_rental_cents` is `gross_rental_cents` multiplied by one minus the class's `rental_discount_pct`, rounded half up to whole cents."

    Hall A at 4,800,000 cents per day over four show days plus six shoulder days
    is 7 billable units, so the 0.25 citywide discount must bite on the
    33,600,000 gross rather than on the daily rate.

    Design: Corner/calculations/contracted_rental_charge_applies_the_citywide_discount_to_the_gross
    """
    publish_window(api, "CITYWIDE_CONVENTION")
    space = register_space(api, **HALL_A)
    client = register_client(api, **NATIONAL_WIDGET_ASSOCIATION)

    resp = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="National Widget Convention",
            event_class="CITYWIDE_CONVENTION",
            move_in_start_date="2028-05-10",
            show_start_date="2028-05-14",
            show_end_date="2028-05-17",
            move_out_end_date="2028-05-19",
            projected_room_nights=3000,
        ),
        headers=SALES_MANAGER,
    )
    booking = validate_success(resp, 201)

    stored = read_booking(api, booking["id"])
    assert_money_cents(stored["gross_rental_cents"], 33_600_000, "gross_rental_cents")
    assert_money_cents(stored["contracted_rental_cents"], 25_200_000, "contracted_rental_cents")
    assert_money_cents(stored["deposit_required_cents"], 6_300_000, "deposit_required_cents")
    assert stored["space_days_committed"] == 10, stored["space_days_committed"]
    assert read_space(api, space["id"])["committed_space_days"] == 10


def test_client_standing_ignores_a_settlement_that_is_only_issued(api):
    """PRD §3.1: "`outstanding_balance_cents` is the sum of `grand_total_cents` over every settlement reachable from this client through its bookings whose `status` is `FINAL`; settlements sitting in `DRAFT`, `ISSUED`, `DISPUTED` or `ARBITRATION` contribute nothing."

    An ISSUED settlement carrying a 5,350,000 grand total must leave the
    licensee's outstanding balance at 0 and its standing at GOOD.

    Design: Corner/calculations/client_standing_ignores_a_settlement_that_is_only_issued
    """
    world = setup_event_lifecycle(
        api,
        stage="settlement_issued",
        event_class="CONSUMER_SHOW",
        space=dict(BALLROOM_C),
        deposit_cents=1_300_000,
        booking={
            "event_name": "Sunbelt Boat Show",
            "move_in_start_date": "2027-06-09",
            "show_start_date": "2027-06-10",
            "show_end_date": "2027-06-12",
            "move_out_end_date": "2027-06-13",
        },
        settlement_basis="CONTRACTED",
        rental_line_cents=5_000_000,
        analyst_id=ANALYST_ONE,
        open_show_at="2027-06-09T08:00:00Z",
        close_at="2027-06-14T09:00:00Z",
    )
    client_id = world["client"]["id"]
    booking_id = world["booking"]["id"]
    settlement_id = world["settlement"]["id"]

    validate_success(api.get_client(client_id, headers=SETTLEMENT_ANALYST), 200)

    settlement = read_settlement(api, settlement_id)
    assert_fields(settlement, status="ISSUED")
    assert_money_cents(settlement["grand_total_cents"], 5_350_000, "grand_total_cents")

    client = read_client(api, client_id)
    assert_money_cents(client["outstanding_balance_cents"], 0, "outstanding_balance_cents")
    assert_fields(client, booking_standing="GOOD")

    assert_fields(read_booking(api, booking_id), status="CLOSED", order_posture="RESTRICTED")


def test_move_period_factor_and_deposit_pct_applied_as_separate_multipliers(api):
    """PRD §3.2: "The billable units are the show days plus one half of the sum of the move-in and move-out days."

    Ballroom B at 1,200,000 cents per day separates the three multipliers: six
    shoulder days become three billable units for a gross of 8,400,000, the
    local-event 0.10 discount gives 7,560,000, and the one-quarter deposit gives
    1,890,000.

    Design: Corner/calculations/move_period_factor_and_deposit_pct_constants_applied_as_declared
    """
    publish_window(api, "LOCAL_EVENT")
    space = register_space(api, **BALLROOM_B)
    client = register_client(api, **RIVERBEND_ROTARY)

    resp = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Riverbend Spring Banquet",
            event_class="LOCAL_EVENT",
            move_in_start_date="2028-05-10",
            show_start_date="2028-05-14",
            show_end_date="2028-05-17",
            move_out_end_date="2028-05-19",
        ),
        headers=SALES_MANAGER,
    )
    booking = validate_success(resp, 201)

    stored = read_booking(api, booking["id"])
    assert_money_cents(stored["gross_rental_cents"], 8_400_000, "gross_rental_cents")
    assert_money_cents(stored["contracted_rental_cents"], 7_560_000, "contracted_rental_cents")
    assert_money_cents(stored["deposit_required_cents"], 1_890_000, "deposit_required_cents")


def test_contracted_rental_rounds_half_up_on_a_half_cent_result(api):
    """PRD §2.6: "Wherever a formula multiplies a cent amount by a fraction, the product is rounded to a whole number of cents using the **round half up** method: a residue of exactly half a cent rounds away from zero."

    A daily rate of 90,901 cents against 4.5 billable units lands the gross
    exactly on 409,054.5, and the quarter deposit then lands on 102,263.75, so a
    single wrong rounding mode is caught at either scale.

    Design: Corner/calculations/contracted_rental_rounds_half_up_on_a_half_cent_result
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(
        api,
        name="Meeting Room 305",
        space_class="MEETING_ROOM",
        rentable_sqft=2600,
        daily_base_rate_cents=90_901,
    )
    client = register_client(api)

    resp = api.create_booking(
        payload=booking_payload(
            client["id"],
            space["id"],
            event_name="Regional Coin Show",
            event_class="CONSUMER_SHOW",
            move_in_start_date="2027-03-01",
            show_start_date="2027-03-02",
            show_end_date="2027-03-04",
            move_out_end_date="2027-03-06",
        ),
        headers=SALES_MANAGER,
    )
    booking = validate_success(resp, 201)

    stored = read_booking(api, booking["id"])
    assert_money_cents(stored["gross_rental_cents"], 409_055, "gross_rental_cents")
    assert stored["gross_rental_cents"] != 409_054
    assert_money_cents(stored["contracted_rental_cents"], 409_055, "contracted_rental_cents")
    assert_money_cents(stored["deposit_required_cents"], 102_264, "deposit_required_cents")
    assert stored["space_days_committed"] == 6, stored["space_days_committed"]


def test_hold_rank_assignment_orders_by_creation_time_not_by_identifier(api):
    """PRD §3.3: "The new hold's `hold_rank` is one greater than the number of holds in that set, so a hold with no competitors ranks 1 and the third overlapping hold on a hall ranks 3."

    Three bookings claim the identical Ballroom B interval, so the three holds
    must come out ranked 1, 2 and 3 in call order.

    Design: Corner/calculations/hold_rank_assignment_orders_by_creation_time_not_by_identifier
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **BALLROOM_B)
    sunbelt = register_client(api)
    rotary = register_client(api, **RIVERBEND_ROTARY)
    widget = register_client(api, **NATIONAL_WIDGET_ASSOCIATION)

    interval = {
        "move_in_start_date": "2027-06-08",
        "show_start_date": "2027-06-10",
        "show_end_date": "2027-06-12",
        "move_out_end_date": "2027-06-13",
    }
    booking_one = create_booking(
        api, sunbelt["id"], space["id"], event_name="Sunbelt Home Show", **interval
    )
    booking_two = create_booking(
        api, rotary["id"], space["id"], event_name="Rotary Antiques Fair", **interval
    )
    booking_three = create_booking(
        api, widget["id"], space["id"], event_name="Widget Regional Expo", **interval
    )

    holds = []
    for booking in (booking_one, booking_two, booking_three):
        current = read_booking(api, booking["id"])
        resp = api.create_hold(
            booking["id"],
            expected_booking_version=current["version"],
            headers=SALES_MANAGER,
        )
        holds.append(validate_success(resp, 201))

    assert read_hold(api, holds[0]["id"])["hold_rank"] == 1
    assert read_hold(api, holds[1]["id"])["hold_rank"] == 2
    assert read_hold(api, holds[2]["id"])["hold_rank"] == 3
    for hold in holds:
        assert_fields(
            read_hold(api, hold["id"]),
            interval_start_date="2027-06-08",
            interval_end_date="2027-06-13",
        )
    assert read_booking(api, booking_three["id"])["hold_count"] == 1


def test_utilities_marginal_tier_breaks_at_exactly_one_hundred_units(api):
    """PRD §3.5: "Utilities alone are marginally tiered: the first 100 amps bill at 1,200 cents each, amps from the 101st through the 400th bill at 900 cents each, and every amp beyond the 400th bills at 700 cents each; an order for 250 amps therefore bills 100 amps at the first rate plus 150 amps at the second, and an order for 80 amps bills all 80 at the first rate with the higher tiers contributing nothing."

    Two orders one amp apart straddle the first tier edge: 100 amps price at
    132,000 cents and 101 amps at 132,990 after the preferred multiplier, so an
    average-rate model diverges immediately.

    Design: Corner/calculations/utilities_marginal_tier_breaks_at_exactly_one_hundred_units
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    vendor = register_vendor(
        api,
        legal_name="Metro Preferred Power",
        service_category="UTILITIES",
        vendor_tier="PREFERRED",
        coi_expiry_date="2030-01-01",
    )
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"])

    order_100 = order_service(api, booking["id"], vendor["id"], "UTILITIES", 100)
    order_101 = order_service(api, booking["id"], vendor["id"], "UTILITIES", 101)

    validate_success(api.approve_service_order(order_100["id"], headers=EVENT_SERVICES), 200)
    validate_success(api.approve_service_order(order_101["id"], headers=EVENT_SERVICES), 200)

    priced_100 = read_service_order(api, order_100["id"])
    priced_101 = read_service_order(api, order_101["id"])
    assert_fields(priced_100, order_timing="ADVANCE")
    assert_money_cents(priced_100["estimated_charge_cents"], 132_000, "estimated_charge_cents")
    assert_money_cents(priced_101["estimated_charge_cents"], 132_990, "estimated_charge_cents")
    assert (
        priced_101["estimated_charge_cents"] - priced_100["estimated_charge_cents"] == 990
    ), "one marginal amp at 900 cents times the preferred multiplier is 990 cents"
    assert priced_101["estimated_charge_cents"] != 133_320


def test_duplicate_usage_day_attestation_rejected(api):
    """PRD §3.8: "A booking may carry at most one attestation per calendar day, and a second attempt on the same `usage_date` is refused with `ERR_USAGE_RECORD_DUPLICATE`."

    A second attestation of 2027-03-01 under a different usage_kind must be
    refused outright rather than merged or overwritten.

    Design: Corner/calculations/duplicate_usage_day_attestation_rejected
    """
    esm_one = make_headers("esm-1", UserRole.EVENT_SERVICES_MANAGER.value)
    esm_two = make_headers("esm-2", UserRole.EVENT_SERVICES_MANAGER.value)

    world = setup_event_lifecycle(
        api,
        stage="in_house",
        event_class="CONSUMER_SHOW",
        deposit_cents=200_000,
        open_show_at="2027-03-01T08:00:00Z",
    )
    booking_id = world["booking"]["id"]

    validate_success(
        api.create_usage_record(
            booking_id, usage_date="2027-03-01", usage_kind="MOVE_IN", headers=esm_one
        ),
        201,
    )

    resp = api.create_usage_record(
        booking_id, usage_date="2027-03-01", usage_kind="DARK", headers=esm_two
    )
    validate_error(resp, ApiErrorId.USAGE_RECORD_DUPLICATE.value)

    records, meta = validate_paginated(
        api.list_usage_records(headers=EVENT_SERVICES, booking_id=booking_id)
    )
    assert meta["total_count"] == 1, meta
    assert_fields(records[0], usage_kind="MOVE_IN", recorded_by_user_id="esm-1")


def test_fnb_buyout_floor_binds_for_the_estimate_but_not_for_the_actual(api):
    """PRD §3.7: "For an `OUTSIDE_EXCEPTION`, take the basis food and beverage spend, multiply it by 22 hundredths, round half up to whole cents, and then take the greater of that figure and a floor of 250,000 cents."

    22 percent of the 1,000,000 forecast is only 220,000 so the approved fee is
    floored to 250,000, while 22 percent of the 1,800,000 settled spend is
    396,000 and the floor is inert once the booking closes.

    Design: Corner/calculations/fnb_buyout_floor_binds_for_the_estimate_but_not_for_the_actual
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    vendor = register_vendor(
        api,
        legal_name="Cousin's Kitchen Catering",
        service_category="CATERING",
        vendor_tier="PREFERRED",
        coi_expiry_date="2030-01-01",
        is_in_house_caterer=False,
    )
    client = register_client(api, deposit_cents=200_000)
    booking = create_booking(api, client["id"], space["id"])

    arrangement = propose_catering(
        api,
        booking["id"],
        vendor["id"],
        "OUTSIDE_EXCEPTION",
        1_000_000,
        exception_reason="ETHNIC_CUISINE",
    )
    approve_catering(api, arrangement["id"])
    validate_success(
        api.update_catering_arrangement(
            arrangement["id"], actual_fnb_cents=1_800_000, headers=EVENT_SERVICES
        ),
        200,
    )

    hold = place_hold(api, booking["id"])
    confirm_first_option(api, hold["id"])
    execute_license(api, booking["id"], client["id"])
    confirm_definite(api, booking["id"])
    open_show(api, booking["id"], at_utc="2027-03-01T08:00:00Z")
    set_clock(api, "2027-03-06T09:00:00Z")

    approved = validate_success(
        api.get_catering_arrangement(arrangement["id"], headers=EVENT_SERVICES), 200
    )
    assert_fields(approved, status="APPROVED")
    assert_money_cents(approved["buyout_fee_cents"], 250_000, "buyout_fee_cents")

    validate_success(api.close_booking(booking["id"], headers=EVENT_SERVICES), 200)

    closed = read_catering_arrangement(api, arrangement["id"])
    assert_fields(closed, status="CLOSED")
    assert_money_cents(closed["buyout_fee_cents"], 396_000, "buyout_fee_cents")
    assert closed["buyout_fee_cents"] != 250_000
    assert_fields(read_booking(api, booking["id"]), status="CLOSED", order_posture="RESTRICTED")


def test_labor_call_creation_selects_the_scheduled_estimate_variant(api):
    """PRD §3.6: "The estimate, written at creation into `estimated_charge_cents`, is generous to the licensee: take the hours per crew member as the greater of the local's `min_call_hours` and the scheduled span, multiply by `crew_size` and by the local's `straight_time_rate_cents`, and round half up to whole cents."

    A crew of three scheduled from hour 6.0 to hour 10.5 sits two hours outside
    the straight-time window, yet creation must price all 4.5 hours at straight
    time: 3 x 4.5 x 9,533 rounds to 128,696 cents.

    Design: Corner/calculations/labor_call_creation_selects_the_scheduled_estimate_variant
    """
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **MEETING_ROOM_301)
    local = register_union_local(
        api,
        craft_name="SEIU Local 3",
        covered_category="CLEANING",
        straight_time_rate_cents=9533,
        max_crew_hours_per_day=40,
        overtime_multiplier=1.5,
        min_call_hours=4,
        st_window_start_hour=8,
        st_window_end_hour=17,
        lockout_active=False,
    )
    client = register_client(api)
    booking = create_booking(api, client["id"], space["id"])

    resp = api.create_labor_call(
        booking["id"],
        payload=labor_call_payload(local["id"], "CLEANING", "2027-03-01", 6.0, 10.5, 3),
        headers=EVENT_SERVICES,
    )
    call = validate_success(resp, 201)

    stored = read_labor_call(api, call["id"])
    assert_fields(stored, status="SCHEDULED")
    assert_crew_hours(stored["billed_hours"], 13.5, "billed_hours")
    assert_money_cents(stored["estimated_charge_cents"], 128_696, "estimated_charge_cents")
    assert stored["actual_charge_cents"] is None, stored["actual_charge_cents"]
    assert_crew_hours(
        read_union_jurisdiction(api, local["id"])["committed_crew_hours"],
        13.5,
        "committed_crew_hours",
    )
