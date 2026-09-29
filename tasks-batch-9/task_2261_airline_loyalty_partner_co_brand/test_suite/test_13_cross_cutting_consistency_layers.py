"""Cross-cutting layers: stale-version protection on every anchored write, the
demand ladder's threshold step, and the immediacy of derived-counter recomputes.
"""
from test_helpers import (
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    active_agreement,
    assert_award_booking,
    assert_deferred_revenue_posting,
    assert_mile_purchase_order,
    award_booking_payload,
    create_issuer,
    create_member,
    create_order,
    create_program,
    create_window,
    deferred_revenue_posting_payload,
    get_success_data,
    hold_seats,
    mile_purchase_order_payload,
    read_agreement,
    read_program,
    read_window,
    tier_schedule,
    transition_recognition,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Optimistic concurrency: all three anchored creates reject a stale parent
# --------------------------------------------------------------------------- #
def test_all_three_anchored_creates_reject_a_stale_parent_version(api):
    """PRD §2.8: "In each case, if the supplied value does not equal the parent's current `version`, the write is rejected with `ERR_STALE_VERSION` (412) and nothing is mutated."
    PRD §2.8: "Creating a mile purchase order requires `expected_agreement_version`, carrying the client's last observed `version` of the target `MileSaleAgreement`."
    PRD §2.8: "Creating an award booking hold requires `expected_window_version`, carrying the client's last observed `version` of the target `AwardInventoryWindow`."
    PRD §2.8: "Creating a deferred revenue posting requires `expected_program_version`, carrying the client's last observed `version` of the target `LoyaltyProgram`."
    PRD §2.8: "A second order on the same agreement, a second hold on the same window, and a posting for a different period are all perfectly legitimate acts in themselves."
    PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."
    PRD §3.5: "`quoted_miles` is then the gross per-seat figure multiplied by the quantity (10000 minus `elite_discount_bps_applied`), divided by 10000, rounded half up **per seat**, and only then multiplied by `seats`."

    Design: Corner/cross_cutting_complexity_layers/all_three_declared_occ_rules_reject_a_stale_parent_version
    """
    program = create_program(name="SkyMiles OCC", current_period="2026-08")
    program_version_stale = program["version"]
    member = create_member(
        program["id"], external_member_ref="MBR-OCC", home_region="AMER"
    )
    issuer = create_issuer(
        program["id"],
        name="Northbank Card Services",
        annual_mile_purchase_cap_miles=5000000,
    )
    agreement = active_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=1000000,
        tier_schedule=tier_schedule((0, 200)),
    )
    agreement_version_stale = agreement["version"]
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )
    window_version_stale = window["version"]

    # Each of the three legitimate first writes bumps its parent's version.
    create_order(agreement["id"], 100000, agreement_version_stale)
    hold_seats(
        member["id"],
        window["id"],
        window_version_stale,
        travel_date="2026-09-10",
        seats=1,
        fare_class="FLEX",
    )
    transition_recognition(program["id"], "CLOSING")

    stale_order = api.create_mile_purchase_order(
        mile_purchase_order_payload(
            agreement["id"], 100000, agreement_version_stale
        ),
        PARTNER_MANAGER,
    )
    validate_error(stale_order, "ERR_STALE_VERSION", 412)

    stale_hold = api.create_award_booking(
        award_booking_payload(
            member["id"],
            window["id"],
            window_version_stale,
            travel_date="2026-09-10",
            seats=1,
            fare_class="FLEX",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(stale_hold, "ERR_STALE_VERSION", 412)

    stale_posting = api.create_deferred_revenue_posting(
        deferred_revenue_posting_payload(
            program["id"], "2026-08", program_version_stale
        ),
        REVENUE_ACCOUNTANT,
    )
    validate_error(stale_posting, "ERR_STALE_VERSION", 412)

    # Retrying each write against the refreshed parent version succeeds.
    agreement_fresh = read_agreement(agreement["id"])
    second_order = validate_success(
        api.create_mile_purchase_order(
            mile_purchase_order_payload(
                agreement["id"], 100000, agreement_fresh["version"]
            ),
            PARTNER_MANAGER,
        ),
        expected_status=201,
    )
    assert_mile_purchase_order(second_order)
    assert second_order["gross_amount_cents"] == 200000, (
        "100000 miles at 200 centicents is 200000 cents"
    )

    window_fresh = read_window(window["id"])
    second_hold = validate_success(
        api.create_award_booking(
            award_booking_payload(
                member["id"],
                window["id"],
                window_fresh["version"],
                travel_date="2026-09-10",
                seats=1,
                fare_class="FLEX",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert_award_booking(second_hold)
    assert second_hold["quoted_miles"] == 22500, (
        "an ECONOMY FLEX seat at the 9000 bps rung quotes 22500 miles"
    )

    program_fresh = read_program(program["id"], REVENUE_ACCOUNTANT)
    posting = validate_success(
        api.create_deferred_revenue_posting(
            deferred_revenue_posting_payload(
                program["id"], "2026-08", program_fresh["version"]
            ),
            REVENUE_ACCOUNTANT,
        ),
        expected_status=201,
    )
    assert_deferred_revenue_posting(posting)

    assert read_agreement(agreement["id"])["drawn_miles"] == 0, (
        "no order was issued, so the agreement has drawn nothing"
    )
    assert read_window(window["id"])["seats_held"] == 2, (
        "exactly the two accepted holds are seated; the refused one seated nothing"
    )

    _, order_meta = validate_paginated(
        api.list_mile_purchase_orders(
            PARTNER_MANAGER, params={"agreement_id": agreement["id"]}
        )
    )
    assert order_meta["total_count"] == 2, (
        "the rejected order write mutated nothing, so only two orders exist"
    )
    _, booking_meta = validate_paginated(
        api.list_award_bookings(PROGRAM_ADMIN, params={"window_id": window["id"]})
    )
    assert booking_meta["total_count"] == 2, (
        "the rejected hold mutated nothing, so only two bookings exist"
    )
    _, posting_meta = validate_paginated(
        api.list_deferred_revenue_postings(
            REVENUE_ACCOUNTANT, params={"program_id": program["id"]}
        )
    )
    assert posting_meta["total_count"] == 1, (
        "the rejected posting wrote no row, so only one posting exists"
    )


# --------------------------------------------------------------------------- #
# Rate threshold: crossing 9000 bps of load lifts the demand multiplier
# --------------------------------------------------------------------------- #
def test_load_factor_crossing_nine_thousand_bps_lifts_the_demand_multiplier(api):
    """PRD §3.5: "**Pre-booking load factor.** The window's occupancy is measured *before* the requested seats are added: `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up — and zero when `authorized_seats` is zero, which short-circuits rather than dividing by zero."
    PRD §3.5: "**Demand multiplier.** That pre-booking load factor selects `demand_multiplier_bps_applied` from a four-rung ladder whose lower bounds are inclusive: 9000 basis points below 5000, 10000 from 5000 through 7499, 12500 from 7500 through 8999, and 16000 at 9000 and above."
    PRD §3.5: "A load factor of exactly 5000, 7500 or 9000 therefore takes the higher rung."
    PRD §3.5: "**Chart miles.** `chart_miles_per_seat` is read from the award chart by the window's `cabin` and the requested `fare_class`: `ECONOMY` charges 12500 at `SAVER` and 25000 at `FLEX`; `PREMIUM` charges 25000 and 45000; `BUSINESS` charges 50000 and 85000; `FIRST` charges 90000 and 140000."
    PRD §3.5: "The gross award miles per seat are `chart_miles_per_seat` multiplied by `demand_multiplier_bps_applied` and by `partner_uplift_bps_applied`, divided by 100000000 (that is, both basis-point factors converted to plain multipliers), rounded half up."
    PRD §3.5: "**Surcharge band.** `surcharge_band` is keyed by that gross per-seat figure, pre-discount, against inclusive lower bounds: `SURCHARGE_LOW` below 25000 gross miles, `SURCHARGE_MID` from 25000 through 74999, and `SURCHARGE_HIGH` at 75000 and above, so a gross of exactly 25000 or exactly 75000 takes the higher band."
    PRD §3.5: "The band also fixes the cash side: `cash_surcharge_cents` is 560 cents per seat at `SURCHARGE_LOW`, 1120 at `SURCHARGE_MID` and 2240 at `SURCHARGE_HIGH`, multiplied by `seats`."
    PRD §3.5: "A `BASE` member receives no discount in any band."
    PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."
    PRD §3.5: "While a window is `CLOSED`, new holds are refused with `ERR_AWARD_WINDOW_CLOSED`."

    Design: Corner/cross_cutting_complexity_layers/load_factor_crossing_nine_thousand_bps_lifts_the_demand_multiplier_to_sixteen_thousand
    """
    program = create_program(name="SkyMiles Ladder", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-LADDER", home_region="AMER"
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    nine_seats = hold_seats(
        member["id"],
        window["id"],
        window["version"],
        travel_date="2026-09-10",
        seats=9,
        fare_class="FLEX",
    )
    assert_award_booking(nine_seats)
    assert nine_seats["demand_multiplier_bps_applied"] == 9000, (
        "an empty window's pre-booking load of 0 sits on the 9000 bps floor rung"
    )
    assert nine_seats["quoted_miles"] == 202500, (
        "25000 chart miles at 9000 bps is 22500 per seat, times nine seats"
    )
    assert nine_seats["surcharge_band"] == "SURCHARGE_LOW", (
        "a gross of 22500 per seat is below the 25000 band boundary"
    )
    assert nine_seats["cash_surcharge_cents"] == 5040, (
        "560 cents per seat at SURCHARGE_LOW times nine seats"
    )

    after_nine = read_window(window["id"])
    assert after_nine["load_factor_bps"] == 9000, (
        "nine held seats of ten authorised is 9000 basis points"
    )
    assert after_nine["capacity_control_state"] == "CONSTRAINED", (
        "9000 bps falls inside the 7500-through-9999 CONSTRAINED band"
    )
    assert after_nine["demand_multiplier_bps"] == 16000, (
        "a load factor of exactly 9000 takes the top rung of the ladder"
    )

    tenth_seat = hold_seats(
        member["id"],
        window["id"],
        after_nine["version"],
        travel_date="2026-09-11",
        seats=1,
        fare_class="FLEX",
    )
    assert tenth_seat["demand_multiplier_bps_applied"] == 16000, (
        "the tenth seat is quoted at a pre-booking load of exactly 9000"
    )
    assert tenth_seat["quoted_miles"] == 40000, (
        "25000 chart miles at 16000 bps is 40000 for the single seat"
    )
    assert tenth_seat["surcharge_band"] == "SURCHARGE_MID", (
        "a gross of 40000 sits in the 25000-through-74999 band"
    )
    assert tenth_seat["cash_surcharge_cents"] == 1120, (
        "1120 cents per seat at SURCHARGE_MID times one seat"
    )

    after_ten = read_window(window["id"])
    assert after_ten["load_factor_bps"] == 10000, (
        "ten held seats of ten authorised is a full 10000 basis points"
    )
    assert after_ten["capacity_control_state"] == "CLOSED", (
        "a load factor of 10000 or more is CLOSED"
    )
    assert after_ten["seats_held"] == 10, "both accepted holds seated their seats"

    eleventh = api.create_award_booking(
        award_booking_payload(
            member["id"],
            window["id"],
            after_ten["version"],
            travel_date="2026-09-12",
            seats=1,
            fare_class="FLEX",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(eleventh, "ERR_AWARD_WINDOW_CLOSED", 409)

    assert read_window(window["id"])["seats_held"] == 10, (
        "the refused hold seated nothing"
    )


# --------------------------------------------------------------------------- #
# Immediate consistency: the issue response and a re-read agree everywhere
# --------------------------------------------------------------------------- #
def test_issue_response_and_an_immediate_reread_agree_on_every_ledger(api):
    """PRD §2.10: "Aggregates are recomputed synchronously, inside the request that caused them to change, and every entity whose row is touched has its `updated_at` refreshed and its `version` incremented by one."
    PRD §3.3: "Its effects reach three rows: the agreement's `drawn_miles` increases by `order_miles`, the agreement's `prepayment_balance_miles` increases by the same `order_miles` (these are miles bought but not yet distributed to members), and the programme's `deferred_revenue_cents` increases by `gross_amount_cents`."
    PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."
    PRD §3.3: "The order lands with `fulfillment_status` at `PENDING` and `settlement_status` at `PENDING`, with `final_amount_cents`, `net_amount_cents`, `posted_period` and `reversal_reason` all null and `volume_true_up_cents` at zero."

    Design: Corner/consistency_model/issue_response_and_an_immediate_reread_agree_on_every_ledger
    """
    program = create_program(name="SkyMiles Immediate", current_period="2026-08")
    assert program["deferred_revenue_cents"] == 0, (
        "a fresh programme carries no deferred revenue"
    )
    issuer = create_issuer(
        program["id"],
        name="Northbank Card Services",
        annual_mile_purchase_cap_miles=5000000,
    )
    agreement = active_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=1000000,
        tier_schedule=tier_schedule((0, 150)),
    )
    order = create_order(agreement["id"], 300000, agreement["version"])
    assert order["gross_amount_cents"] == 450000, (
        "300000 miles at 150 centicents is 450000 cents"
    )

    issued = validate_success(api.issue_order(order["id"], PARTNER_MANAGER))
    assert issued["fulfillment_status"] == "ISSUED", (
        "the issue call itself reports the ISSUED fulfilment dimension"
    )

    agreement_reread = get_success_data(
        api.get_mile_sale_agreement(agreement["id"], PARTNER_MANAGER)
    )
    assert agreement_reread["drawn_miles"] == 300000, (
        "the agreement re-read already shows the drawn miles, with no epoch run"
    )
    assert agreement_reread["prepayment_balance_miles"] == 300000, (
        "prepayment_balance_miles moved in the same request"
    )

    program_reread = get_success_data(
        api.get_loyalty_program(program["id"], REVENUE_ACCOUNTANT)
    )
    assert program_reread["deferred_revenue_cents"] == 450000, (
        "the programme re-read already carries the order's gross_amount_cents"
    )

    order_reread = get_success_data(
        api.get_mile_purchase_order(order["id"], REVENUE_ACCOUNTANT)
    )
    assert order_reread["fulfillment_status"] == "ISSUED", (
        "the order re-read agrees with the issue response"
    )
    assert order_reread["settlement_status"] == "PENDING", (
        "issuance leaves the settlement dimension at PENDING"
    )
    assert order_reread["final_amount_cents"] is None, (
        "final_amount_cents stays null until the order is invoiced"
    )

    _, meta = validate_paginated(
        api.list_mile_purchase_orders(
            REVENUE_ACCOUNTANT,
            params={
                "agreement_id": agreement["id"],
                "fulfillment_status": "ISSUED",
            },
        )
    )
    assert meta["total_count"] == 1, (
        "the filtered listing immediately reflects the one issued order"
    )
