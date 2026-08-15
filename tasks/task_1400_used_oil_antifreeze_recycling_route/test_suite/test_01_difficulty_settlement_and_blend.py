"""Difficulty queue A — rules 1 (dual_variant_calc) and 2 (combinatorial_formula)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_blend_batch_payload,
    create_adjust_payload,
    create_settle_payload,
    create_market_price_payload,
    create_route_payload,
    create_route_stop_payload,
    create_sample_screening_payload,
    create_pickup_ticket_payload,
    create_customer_payload,
    create_tank_site_payload,
    create_tank_payload,
    create_driver_payload,
    create_spill_incident_payload,
    create_active_customer_with_installed_tank,
    create_driver,
    create_route,
    add_stop_to_route,
    publish_price,
    drive_halogen_violations,
    setup_completed_pickup,
    setup_settled_ticket,
    setup_spill_remediated,
)


# =========================================================================
# RULE 1 — dual_variant_calc / settlement_provisional_vs_adjusted
# =========================================================================

def test_settlement_provisional_variant_prices_snapshot_at_scheduled_date(api):
    """PRD §3.5: "The provisional variant runs at creation, uses the price as of the route's `scheduled_date`, and leaves `payment_status` `PROVISIONAL` until settlement."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_adjusted
    """
    ctx = setup_completed_pickup(
        credit_terms="PREPAY", price_cents_per_gal=50, metered_volume_gallons=100,
        intake_gallons=200, route_code="PROV-1",
    )
    ticket = ctx["ticket"]
    assert ticket["payment_status"] == "PROVISIONAL"
    assert ticket["commodity_price_cents_per_gal"] == 50
    assert ticket["gross_amount_cents"] == 5000  # 50 * 100
    assert ticket["net_amount_cents"] == 5000
    assert ticket["settlement_direction"] == "PAY_CUSTOMER"


def test_settlement_adjusted_variant_posts_full_net_when_never_settled(api):
    """PRD §3.6: "the customer is posted only the delta between the new and the old net when the ticket had previously settled, or the full new net when it never settled."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_adjusted
    """
    ctx = setup_completed_pickup(
        credit_terms="PREPAY", price_cents_per_gal=50, metered_volume_gallons=100,
        intake_gallons=200, route_code="PROV-2",
    )
    ticket = ctx["ticket"]
    # Dispute then adjust down to 80 gal
    api_client.dispute_pickup_ticket(ticket["id"], TEST_USERS["settlement_clerk_headers"])
    adjusted = get_success_data(api_client.adjust_pickup_ticket(
        ticket["id"],
        create_adjust_payload(corrected_metered_volume_gallons=80),
        TEST_USERS["settlement_clerk_headers"],
    ))
    assert adjusted["payment_status"] == "ADJUSTED"
    assert adjusted["gross_amount_cents"] == 4000  # 50 * 80
    assert adjusted["net_amount_cents"] == 4000
    # Never settled: full new net posted to prepaid
    cust = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    assert cust["prepaid_balance_cents"] == 4000


# =========================================================================
# RULE 1 — dual_variant_calc / blend_yield_planned_vs_actual
# =========================================================================

def test_blend_batch_planned_estimate_ignores_halogen_and_mix(api):
    """PRD §3.8: "creation computes an optimistic what-if projection stored as `planned_output_gallons` — computed with zero halogen history and no mix penalty, informational only and never posted to inventory."

    Design: Difficulty/dual_variant_calc/blend_yield_planned_vs_actual
    """
    # Build customer with halogen_violation_count = 5 to make frozen_halogen_count = 5
    base = create_active_customer_with_installed_tank(
        credit_terms="NET30", tank_kind="USED_OIL", capacity_gallons=1000,
        route_eligibility_override=True, intake_gallons=900,
    )
    driver = create_driver()
    publish_price(market_zone="NORTH", tank_kind="USED_OIL", effective_date="2026-08-01",
                  price_cents_per_gal=40)
    drive_halogen_violations(base["customer"], base["site"], base["tank"], driver, 5, route_code_prefix="HVB")

    # Two PASS pickups → two SETTLED tickets, each with frozen_halogen_count=5
    ticket_ids = []
    for i in range(2):
        route = create_route(driver["id"], scheduled_date=f"2026-08-0{7 + i}",
                             route_code=f"BLEND-{i}", vehicle_capacity_gallons=2000, density_zone="URBAN")
        stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
        route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
        drv = make_driver_headers(driver["id"])
        stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
        stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
        get_success_data(api_client.create_sample_screening(
            stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
        ))
        ticket = get_success_data(api_client.create_pickup_ticket(
            stop["id"], create_pickup_ticket_payload(client_request_id=f"PT-BLEND-{i}", metered_volume_gallons=100), drv,
        ))
        cust_now = get_success_data(api_client.get_customer(base["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
        ticket = get_success_data(api_client.settle_pickup_ticket(
            ticket["id"], create_settle_payload(cust_now["version"]), TEST_USERS["settlement_clerk_headers"],
        ))
        ticket_ids.append(ticket["id"])

    # Create blend batch — planned_output_gallons should be optimistic
    batch = get_success_data(api_client.create_blend_batch(
        create_blend_batch_payload(ticket_ids, batch_code="BB-DUAL-1", target_product="RE_REFINED_BASE_OIL",
                                    resale_price_cents_per_gal=120),
        TEST_USERS["route_planner_headers"],
    ))
    assert batch["planned_output_gallons"] == 144  # round_half_up(200 * 72 / 100)


def test_blend_batch_actual_applies_halogen_penalty(api):
    """PRD §3.8: "Starting the blend computes the actual figures, overwriting the projection" and "the halogen penalty subtracts two percentage points for each average violation above four".

    Design: Difficulty/dual_variant_calc/blend_yield_planned_vs_actual
    """
    base = create_active_customer_with_installed_tank(
        credit_terms="NET30", tank_kind="USED_OIL", capacity_gallons=1000,
        route_eligibility_override=True, intake_gallons=900,
    )
    driver = create_driver()
    publish_price(market_zone="NORTH", tank_kind="USED_OIL", effective_date="2026-08-01",
                  price_cents_per_gal=40)
    drive_halogen_violations(base["customer"], base["site"], base["tank"], driver, 5, route_code_prefix="HVB2")

    ticket_ids = []
    for i in range(2):
        route = create_route(driver["id"], scheduled_date=f"2026-08-0{7 + i}",
                             route_code=f"BLEND2-{i}", vehicle_capacity_gallons=2000, density_zone="URBAN")
        stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
        route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
        drv = make_driver_headers(driver["id"])
        stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
        stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
        get_success_data(api_client.create_sample_screening(
            stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
        ))
        ticket = get_success_data(api_client.create_pickup_ticket(
            stop["id"], create_pickup_ticket_payload(client_request_id=f"PT-B2-{i}", metered_volume_gallons=100), drv,
        ))
        cust_now = get_success_data(api_client.get_customer(base["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
        ticket = get_success_data(api_client.settle_pickup_ticket(
            ticket["id"], create_settle_payload(cust_now["version"]), TEST_USERS["settlement_clerk_headers"],
        ))
        ticket_ids.append(ticket["id"])

    batch = get_success_data(api_client.create_blend_batch(
        create_blend_batch_payload(ticket_ids, batch_code="BB-DUAL-2", target_product="RE_REFINED_BASE_OIL",
                                    resale_price_cents_per_gal=120),
        TEST_USERS["route_planner_headers"],
    ))
    assert batch["planned_output_gallons"] == 144
    batch = get_success_data(api_client.start_blending_batch(batch["id"], TEST_USERS["route_planner_headers"]))
    # avg_H = 5; penalty = min(20, 2*(5-4)) = 2; mix_penalty=0; yield = 72 - 2 - 0 = 70; out = 200*70/100 = 140
    assert batch["yield_pct"] == 70
    assert batch["output_gallons"] == 140
    assert batch["planned_output_gallons"] != batch["output_gallons"]


# =========================================================================
# RULE 2 — combinatorial_formula / settlement_amount_tiered_surcharge_and_zone_fee
# =========================================================================

def test_settlement_tiered_surcharge_tier_3_charges_customer(api):
    """PRD §3.5: "beyond four, the surcharge is 1,500 cents plus 250 cents multiplied by the number of violations beyond the fourth" and "When the price is negative, the net is the negation of the sum of gross, surcharge, and density fee."

    Design: Difficulty/combinatorial_formula/settlement_amount_tiered_surcharge_and_zone_fee
    """
    base = create_active_customer_with_installed_tank(
        market_zone="SOUTH", credit_terms="CHARGE_ONLY", density_zone="RURAL",
        tank_kind="ANTIFREEZE", capacity_gallons=500, route_eligibility_override=False,
        intake_gallons=400,
    )
    driver = create_driver()
    publish_price(market_zone="SOUTH", tank_kind="ANTIFREEZE", effective_date="2026-08-01",
                  price_cents_per_gal=-20)
    drive_halogen_violations(base["customer"], base["site"], base["tank"], driver, 5, route_code_prefix="T3H")

    # Real pickup: RURAL zone_min=150, metered=100 (below min); fee=(150-100)*10=500
    route = create_route(driver["id"], scheduled_date="2026-08-08", route_code="T3REAL",
                         vehicle_capacity_gallons=500, density_zone="RURAL")
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    ticket = get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="PT-T3", metered_volume_gallons=100), drv,
    ))
    assert ticket["commodity_price_cents_per_gal"] == -20
    assert ticket["gross_amount_cents"] == 2000  # 20 * 100
    assert ticket["surcharge_cents"] == 1750  # 1500 + 250*(5-4)
    assert ticket["density_fee_cents"] == 500  # (150-100)*10
    assert ticket["net_amount_cents"] == -4250  # -(2000+1750+500)
    assert ticket["settlement_direction"] == "CHARGE_CUSTOMER"


def test_settlement_tiered_surcharge_gross_uses_absolute_price(api):
    """PRD §3.5: "`gross_amount_cents` is the absolute value of the signed price multiplied by the metered volume, computed in exact integer cents."

    Design: Difficulty/combinatorial_formula/settlement_amount_tiered_surcharge_and_zone_fee
    """
    base = create_active_customer_with_installed_tank(
        market_zone="SOUTH", credit_terms="NET30", density_zone="RURAL",
        tank_kind="ANTIFREEZE", capacity_gallons=500, route_eligibility_override=True,
        intake_gallons=200,
    )
    driver = create_driver()
    publish_price(market_zone="SOUTH", tank_kind="ANTIFREEZE", effective_date="2026-08-01",
                  price_cents_per_gal=-20)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="T3ABS",
                         vehicle_capacity_gallons=500, density_zone="RURAL")
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    ticket = get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="PT-ABS", metered_volume_gallons=100), drv,
    ))
    # gross uses abs(P) * V, so even with P=-20 gross is positive 2000
    assert ticket["gross_amount_cents"] == 2000


# =========================================================================
# RULE 2 — combinatorial_formula / spill_liability_shared_party_rounding
# =========================================================================

def test_spill_liability_shared_party_base_and_share(api):
    """PRD §3.9: "The base rate is 850 cents per gallon spilled" and "for a `SHARED` outcome the customer's share is half of it, rounded half up".

    Design: Difficulty/combinatorial_formula/spill_liability_shared_party_rounding
    """
    ctx = setup_spill_remediated(gallons_spilled=7, cause_code="UNKNOWN")
    spill = ctx["spill"]
    # base = 850 * 7 = 5950; UNKNOWN multiplier = 1.0; raw = 5950; SHARED
    assert spill["responsible_party"] == "SHARED"
    assert spill["liability_cents"] == 5950
    assert spill["reportable_quantity_exceeded"] is False
    # Close: CUSTOMER share = round_half_up(5950/2) = 2975
    spill = get_success_data(api_client.close_spill(spill["id"], TEST_USERS["ehs_officer_headers"]))
    assert spill["status"] == "CLOSED_WITH_LIABILITY"
    cust = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert cust["outstanding_charge_cents"] == 2975


def test_spill_liability_company_party_no_customer_debit(api):
    """PRD §3.9: "a `COMPANY` outcome assigns the customer nothing" and "when it is `COMPANY` no customer debit occurs".

    Design: Difficulty/combinatorial_formula/spill_liability_shared_party_rounding
    """
    ctx = setup_spill_remediated(gallons_spilled=5, cause_code="DRIVER_ERROR")
    spill = ctx["spill"]
    # base = 850 * 5 = 4250; DRIVER_ERROR multiplier = 2.0; raw = 8500; party = COMPANY
    assert spill["responsible_party"] == "COMPANY"
    assert spill["liability_cents"] == 8500
    spill = get_success_data(api_client.close_spill(spill["id"], TEST_USERS["ehs_officer_headers"]))
    assert spill["status"] == "CLOSED_WITH_LIABILITY"
    cust = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert cust["outstanding_charge_cents"] == 0
