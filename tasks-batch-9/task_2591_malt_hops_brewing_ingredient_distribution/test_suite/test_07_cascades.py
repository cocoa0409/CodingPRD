"""The three cascades: harvest shortfall, default settlement and cold-chain excursion."""
import pytest

from test_helpers import (
    ALLOC_1_HEADERS,
    ALLOC_1_USER_ID,
    AM_HEADERS,
    WH_HEADERS,
    add_contract_hop_line,
    add_malt_line,
    add_reading,
    add_spot_hop_line,
    add_yeast_line,
    approve_credit,
    confirm_order,
    create_brewer,
    create_contract,
    create_malt_product,
    create_order,
    create_program,
    create_ready_job,
    create_recipe,
    create_released_lot,
    create_strain,
    create_variety,
    create_zone,
    depart_shipment,
    get_brewer,
    get_shipment,
    get_zone,
    pick_order,
    pin_clock,
    report_harvest,
    stage_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)


# ── Cascade A: a halved crop travels program -> contract -> line -> order ──
@pytest.fixture
def shortfall_world():
    """A CONFIRMED 4,000 lb contract line, priced before any harvest is reported."""
    pin_clock()
    brewer = create_brewer(name="Shortfall Brewing", credit_limit_cents=3000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                               contracted_lbs=4000, price_per_lb_cents=250.00)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-10-15T00:00:00Z",
                         purchase_order_ref="PO-4001")
    line = add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                                 contract["id"], 4000)
    order = confirm_order(order["id"], brewer["id"])
    return {"brewer": brewer, "program": program, "variety": variety,
            "contract": contract, "order": order, "line": line}


def test_cascade_a_links_one_and_two_cut_the_allocation_and_move_the_contract(
        api, shortfall_world):
    """A 50 percent crop halves the pool and shorts the only contract in it.

    PRD §3.3: "any contract whose newly written `allocated_lbs` is less than its
    `contracted_lbs` transitions `ACTIVE → SHORTFALL_ADJUSTED`, has its
    `shortfall_lbs` set to the difference between `contracted_lbs` and
    `allocated_lbs`, has `remaining_lbs` recomputed, and has its `version`
    incremented."

    Design: Difficulty/transitive_cascade/report_harvest_shortfall_trims_lines_reprices_order_and_moves_credit
    """
    world = shortfall_world
    assert world["order"]["total_cents"] == 1055500, (
        "1000000 - 15000 discount + 66000 freight + 4500 pallet break = 1055500, "
        f"got {world['order']['total_cents']}")
    assert world["order"]["subtotal_cents"] == 1000000, (
        f"4000 lbs at 250.00 cents, got {world['order']['subtotal_cents']}")
    assert world["order"]["volume_discount_cents"] == 15000, (
        f"1.5 percent of a 1,000,000-cent subtotal, got "
        f"{world['order']['volume_discount_cents']}")
    assert world["order"]["freight_cents"] == 66000, (
        f"4000 lbs at 12 cents plus the 18000 reefer surcharge, got "
        f"{world['order']['freight_cents']}")

    before = get_brewer(world["brewer"]["id"])
    assert before["credit_utilization_pct"] == pytest.approx(35.18, abs=0.005), (
        f"1055500 of a 3,000,000-cent limit, got {before['credit_utilization_pct']}")
    assert before["credit_status"] == "GOOD_STANDING", (
        f"the brewer starts in good standing, got {before['credit_status']}")

    program = report_harvest(world["program"]["id"], harvest_yield_pct=50.00,
                            reported_note="drought halved the crop")
    assert program["status"] == "HARVEST_REPORTED", (
        f"the report moves the program, got {program['status']}")
    assert program["harvest_yield_pct"] == pytest.approx(50.00, abs=0.005), (
        f"the yield is recorded, got {program['harvest_yield_pct']}")
    assert program["total_contracted_lbs"] == 4000, (
        f"one 4000 lb contract books against the program, got "
        f"{program['total_contracted_lbs']}")
    assert program["allocatable_pool_lbs"] == 2000, (
        f"floor(4000 * 50 / 100) = 2000, got {program['allocatable_pool_lbs']}")
    assert program["unallocated_pool_lbs"] == 0, (
        f"the sole contract absorbs the whole pool, got "
        f"{program['unallocated_pool_lbs']}")

    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     AM_HEADERS))
    assert contract["allocated_lbs"] == 2000 and contract["shortfall_lbs"] == 2000, (
        "the waterfall writes 2000 allocated and 2000 short, got allocated "
        f"{contract['allocated_lbs']} shortfall {contract['shortfall_lbs']}")
    assert contract["status"] == "SHORTFALL_ADJUSTED", (
        f"2000 allocated against 4000 contracted, got {contract['status']}")


def test_cascade_a_link_three_trims_the_line_that_lost_its_poundage(
        api, shortfall_world):
    """The 2,000 lb gap is taken out of the line and returned to the contract.

    PRD §3.3: "Each line's `quantity` is reduced by the smallest amount that
    closes the gap; the reduction accumulates into `trimmed_lbs`; `extended_cents`
    and `pallet_break` are recomputed from the new quantity; and the line moves
    `OPEN → TRIMMED`."

    Design: Difficulty/transitive_cascade/report_harvest_shortfall_trims_lines_reprices_order_and_moves_credit
    """
    world = shortfall_world
    report_harvest(world["program"]["id"], harvest_yield_pct=50.00,
                   reported_note="drought halved the crop")

    line = validate_success(api.get_order_line(world["line"]["id"], AM_HEADERS))
    assert line["status"] == "TRIMMED", (
        f"the line is trimmed rather than cancelled, got {line['status']}")
    assert line["quantity"] == pytest.approx(2000, abs=0.005), (
        f"4000 less the 2000 lb gap, got {line['quantity']}")
    assert line["trimmed_lbs"] == 2000, (
        f"the removed poundage is recorded, got {line['trimmed_lbs']}")
    assert line["extended_cents"] == 500000, (
        f"2000 lbs at 250.00 cents, got {line['extended_cents']}")
    assert line["pallet_break"] is True, (
        f"2000 lbs is not a whole number of 880 lb pallets, got "
        f"{line['pallet_break']}")

    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     AM_HEADERS))
    assert contract["committed_lbs"] == 2000, (
        f"the trim gives 2000 lbs back, got {contract['committed_lbs']}")
    assert contract["remaining_lbs"] == 0, (
        "allocated 2000 less committed 2000 leaves nothing undrawn, got "
        f"{contract['remaining_lbs']}")


def test_cascade_a_links_four_and_five_reprice_the_order_and_relax_the_credit(
        api, shortfall_world):
    """Repricing loses the discount tier outright and drops the freight to the floor.

    PRD §3.3: "*Link 5*, caused by the `total_cents` rewrite in link 4, re-runs the
    owning brewery's credit posture, rewriting `open_order_exposure_cents`,
    `credit_exposure_cents`, `credit_utilization_pct` and `credit_status`."

    Design: Difficulty/transitive_cascade/report_harvest_shortfall_trims_lines_reprices_order_and_moves_credit
    """
    world = shortfall_world
    report_harvest(world["program"]["id"], harvest_yield_pct=50.00,
                   reported_note="drought halved the crop")

    order = validate_success(api.get_sales_order(world["order"]["id"], AM_HEADERS))
    assert order["subtotal_cents"] == 500000, (
        f"the trimmed line halves the subtotal, got {order['subtotal_cents']}")
    assert order["volume_discount_cents"] == 0, (
        "the discount tier is lost outright, not merely reduced, got "
        f"{order['volume_discount_cents']}")
    assert order["chargeable_lbs"] == 2000, (
        f"only 2000 lbs still ship, got {order['chargeable_lbs']}")
    assert order["freight_tier_applied"] == "TIER_1", (
        f"2000 lbs stays in the first tier, got {order['freight_tier_applied']}")
    assert order["freight_cents"] == 43000, (
        "2000 lbs at 12 cents is below the 25000 minimum, so 25000 plus the "
        f"18000 reefer surcharge, got {order['freight_cents']}")
    assert order["pallet_break_fee_cents"] == 4500, (
        f"one breaking line, got {order['pallet_break_fee_cents']}")
    assert order["small_order_surcharge_cents"] == 0, (
        f"2000 lbs is not below the minimum, got "
        f"{order['small_order_surcharge_cents']}")
    assert order["total_cents"] == 547500, (
        f"500000 + 43000 + 4500 = 547500, got {order['total_cents']}")
    assert order["fee_variant"] == "PROVISIONAL", (
        f"the reprice re-runs the provisional variant, got {order['fee_variant']}")
    assert order["fulfillment_status"] == "CONFIRMED", (
        f"repricing does not move the order, got {order['fulfillment_status']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["open_order_exposure_cents"] == 547500, (
        f"the open order is the whole exposure, got "
        f"{brewer['open_order_exposure_cents']}")
    assert brewer["credit_exposure_cents"] == 547500, (
        f"nothing is invoiced, got {brewer['credit_exposure_cents']}")
    assert brewer["credit_utilization_pct"] == pytest.approx(18.25, abs=0.005), (
        f"547500 of a 3,000,000-cent limit, got {brewer['credit_utilization_pct']}")
    assert brewer["credit_status"] == "GOOD_STANDING", (
        f"the brewer relaxes further into good standing, got "
        f"{brewer['credit_status']}")
    assert brewer["ar_balance_cents"] == 0, (
        f"nothing was invoiced anywhere in this cascade, got "
        f"{brewer['ar_balance_cents']}")


# ── Cascade B: a default travels contract -> AR -> posture -> order -> zone ──
@pytest.fixture
def default_world():
    """A thin-limit brewer with one approved order, one staged load and one contract."""
    pin_clock()
    brewer = create_brewer(name="Thin Margin Brewing", credit_limit_cents=1000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=20000,
                             lot_code="LOT-2602")
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00)
    report_harvest(program["id"], harvest_yield_pct=100.00)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-5001")
    malt_line = add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    hop_line = add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    order = confirm_order(order["id"], brewer["id"])
    order = approve_credit(order["id"])
    shipment = stage_shipment(order["id"], zone["id"], pallet_count=3,
                              stage_from="2026-08-01T00:00:00Z",
                              stage_until="2026-08-02T00:00:00Z",
                              reefer_setpoint_c=2.0, reefer_tolerance_c=2.0)
    return {"brewer": brewer, "program": program, "variety": variety,
            "lot": lot, "zone": zone, "contract": contract, "order": order,
            "malt_line": malt_line, "hop_line": hop_line, "shipment": shipment}


def test_cascade_b_link_one_posts_the_settlement_onto_the_receivable_ledger(
        api, default_world):
    """The default prices a MARKET_SETTLED settlement and bills it immediately.

    PRD §3.5: "*Link 1* adds `settlement_total_cents` to the brewery's
    `ar_balance_cents`."

    Design: Difficulty/transitive_cascade/declare_default_posts_settlement_holds_brewer_freezes_order_and_releases_pallets
    """
    world = default_world
    assert world["order"]["total_cents"] == 168380, (
        f"the pre-existing order totals 168380, got {world['order']['total_cents']}")
    assert world["order"]["credit_status"] == "APPROVED", (
        f"its credit dimension starts APPROVED, got {world['order']['credit_status']}")

    before = get_brewer(world["brewer"]["id"])
    assert before["credit_utilization_pct"] == pytest.approx(16.84, abs=0.005), (
        f"168380 of a 1,000,000-cent limit, got {before['credit_utilization_pct']}")
    assert before["credit_status"] == "GOOD_STANDING", (
        f"the brewer starts in good standing, got {before['credit_status']}")

    contract = validate_success(api.declare_default(
        world["contract"]["id"],
        {"default_reason": "brewer repudiated the crop-year commitment"},
        ALLOC_1_HEADERS))
    assert contract["status"] == "DEFAULTED", (
        f"the contract moves to DEFAULTED, got {contract['status']}")
    assert contract["settlement_variant"] == "MARKET_SETTLED", (
        f"the parent program has reported harvest, got "
        f"{contract['settlement_variant']}")
    assert contract["settlement_damages_cents"] == 995000, (
        f"5000 * (250.00 - 51.00) = 995000, got "
        f"{contract['settlement_damages_cents']}")
    assert contract["settlement_admin_fee_cents"] == 19900, (
        f"2.0 percent of 995000, got {contract['settlement_admin_fee_cents']}")
    assert contract["settlement_total_cents"] == 1014900, (
        f"995000 + 19900 = 1014900, got {contract['settlement_total_cents']}")
    assert contract["defaulted_lbs"] == 5000 and contract["remaining_lbs"] == 0, (
        "the undrawn balance is the defaulted poundage, got defaulted "
        f"{contract['defaulted_lbs']} remaining {contract['remaining_lbs']}")
    assert contract["defaulted_by_user_id"] == ALLOC_1_USER_ID, (
        f"the declaring operator is recorded, got "
        f"{contract['defaulted_by_user_id']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["ar_balance_cents"] == 1014900, (
        f"the settlement total is billed, got {brewer['ar_balance_cents']}")


def test_cascade_b_links_two_and_three_flip_the_posture_and_freeze_the_order(
        api, default_world):
    """The AR posting alone drives the brewer over its limit and holds the order.

    PRD §3.5: "*Link 3*, caused by `credit_status` becoming `HOLD`, moves every
    order of that brewery whose `fulfillment_status` is `DRAFT` or `CONFIRMED` and
    whose own `credit_status` is `APPROVED` along the credit dimension
    `APPROVED → ON_HOLD`."

    Design: Difficulty/transitive_cascade/declare_default_posts_settlement_holds_brewer_freezes_order_and_releases_pallets
    """
    world = default_world
    validate_success(api.declare_default(
        world["contract"]["id"],
        {"default_reason": "brewer repudiated the crop-year commitment"},
        ALLOC_1_HEADERS))

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["open_order_exposure_cents"] == 168380, (
        f"the open order is unchanged, got {brewer['open_order_exposure_cents']}")
    assert brewer["credit_exposure_cents"] == 1183280, (
        f"1014900 + 168380 = 1183280, got {brewer['credit_exposure_cents']}")
    assert brewer["credit_utilization_pct"] == pytest.approx(118.33, abs=0.005), (
        f"1183280 of a 1,000,000-cent limit, got {brewer['credit_utilization_pct']}")
    assert brewer["credit_status"] == "HOLD", (
        f"over the limit is a hold, got {brewer['credit_status']}")

    order = validate_success(api.get_sales_order(world["order"]["id"], WH_HEADERS))
    assert order["credit_status"] == "ON_HOLD", (
        f"the order's credit dimension is frozen, got {order['credit_status']}")
    assert order["fulfillment_status"] == "CONFIRMED", (
        f"the fulfillment dimension is untouched, got {order['fulfillment_status']}")
    assert order["total_cents"] == 168380, (
        f"no repricing happens in this cascade, got {order['total_cents']}")
    assert order["fee_variant"] == "PROVISIONAL", (
        f"the fee variant is not re-run, got {order['fee_variant']}")


def test_cascade_b_links_four_and_five_hold_the_load_and_free_the_pallets(
        api, default_world):
    """The frozen order releases its three pallets back to the zone.

    PRD §3.5: "*Link 4*, caused by each of those orders going on hold, moves every
    reefer load of those orders whose `status` is `STAGED` along `STAGED → HELD`,
    which releases that load's `pallet_count` from its zone's `occupied_pallets`."

    Design: Difficulty/transitive_cascade/declare_default_posts_settlement_holds_brewer_freezes_order_and_releases_pallets
    """
    world = default_world
    assert world["shipment"]["status"] == "STAGED", (
        f"the load starts STAGED, got {world['shipment']['status']}")
    assert get_zone(world["zone"]["id"])["occupied_pallets"] == 3, (
        "three pallets are staged before the trigger, got "
        f"{get_zone(world['zone']['id'])['occupied_pallets']}")

    validate_success(api.declare_default(
        world["contract"]["id"],
        {"default_reason": "brewer repudiated the crop-year commitment"},
        ALLOC_1_HEADERS))

    shipment = get_shipment(world["shipment"]["id"])
    assert shipment["status"] == "HELD", (
        f"the staged load is held, got {shipment['status']}")
    assert get_zone(world["zone"]["id"])["occupied_pallets"] == 0, (
        "the held load releases its pallets, got "
        f"{get_zone(world['zone']['id'])['occupied_pallets']}")

    malt_line = validate_success(api.get_order_line(world["malt_line"]["id"],
                                                    WH_HEADERS))
    hop_line = validate_success(api.get_order_line(world["hop_line"]["id"],
                                                   WH_HEADERS))
    assert malt_line["status"] == "OPEN" and hop_line["status"] == "OPEN", (
        "no line is trimmed by a credit cascade, got "
        f"{malt_line['status']} and {hop_line['status']}")

    lot = validate_success(api.get_malt_lot(world["lot"]["id"], WH_HEADERS))
    assert lot["committed_lbs"] == 1000, (
        "committed poundage is not released by a credit hold, got "
        f"{lot['committed_lbs']}")


# ── Cascade C: a telemetry reading travels load -> job -> replacement job ──
@pytest.fixture
def excursion_world():
    """An IN_TRANSIT 2-pallet load over a PICKED order with a READY yeast job."""
    pin_clock()
    brewer = create_brewer(name="Reefer Run Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    strain = create_strain()
    product = create_malt_product()
    variety = create_variety()
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    recipe = create_recipe(brewer["id"], product["id"], strain["id"],
                           name="Flagship Ale", batch_volume_bbl=30.0,
                           original_gravity_plato=12.50,
                           target_color_lovibond=2.50, target_extract_pct=80.00,
                           target_protein_pct=11.00,
                           requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
                           adjunct_pct=0.0)
    job = create_ready_job(brewer["id"], recipe["id"], strain["id"],
                           pitch_date="2026-08-15T00:00:00Z")
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-6001")
    yeast_line = add_yeast_line(order["id"], brewer["id"], job["id"], 20.0)
    hop_line = add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    order = confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"])
    order = pick_order(order["id"])
    shipment = stage_shipment(order["id"], zone["id"], pallet_count=2,
                              stage_from="2026-08-01T00:00:00Z",
                              stage_until="2026-08-02T00:00:00Z",
                              reefer_setpoint_c=2.0, reefer_tolerance_c=2.0)
    shipment = depart_shipment(shipment["id"])
    return {"brewer": brewer, "strain": strain, "variety": variety,
            "zone": zone, "recipe": recipe, "job": job, "order": order,
            "yeast_line": yeast_line, "hop_line": hop_line,
            "shipment": shipment}


def test_cascade_c_charges_each_interval_to_the_reading_that_closes_it(
        api, excursion_world):
    """20 minutes of clean transit is free; the gap up to the hot sample is charged.

    PRD §3.9: "the interval is charged to the reading that *closes* it, so the time
    elapsed before the first out-of-tolerance sample is not penalised, but the whole
    gap leading up to a violating sample is charged in full"

    Design: Difficulty/transitive_cascade/temperature_excursion_fails_yeast_quarantines_hops_and_mints_replacement_job
    """
    world = excursion_world
    assert world["order"]["total_cents"] == 119380, (
        "24000 yeast + 44880 hops + 43000 freight + 7500 surcharge = 119380, got "
        f"{world['order']['total_cents']}")
    assert world["order"]["fulfillment_status"] == "PICKED", (
        f"the order is picked before departure, got "
        f"{world['order']['fulfillment_status']}")
    assert world["order"]["chargeable_lbs"] == 880, (
        f"only the hop line is charged by weight, got {world['order']['chargeable_lbs']}")
    assert world["shipment"]["status"] == "IN_TRANSIT", (
        f"the load has departed, got {world['shipment']['status']}")
    assert get_zone(world["zone"]["id"])["occupied_pallets"] == 0, (
        "departure frees the staged pallets, got "
        f"{get_zone(world['zone']['id'])['occupied_pallets']}")

    first = add_reading(world["shipment"]["id"], 2.0, "2026-08-01T10:00:00Z")
    assert first["interval_minutes"] == 0, (
        f"the first reading on a load spans nothing, got {first['interval_minutes']}")
    assert first["in_violation"] is False, (
        f"2.0 is the setpoint itself, got {first['in_violation']}")
    assert first["cumulative_excursion_minutes"] == 0, (
        f"nothing has accumulated, got {first['cumulative_excursion_minutes']}")

    second = add_reading(world["shipment"]["id"], 9.5, "2026-08-01T10:20:00Z")
    assert second["interval_minutes"] == 20, (
        f"10:00 to 10:20 is twenty whole minutes, got {second['interval_minutes']}")
    assert second["in_violation"] is True, (
        f"9.5 is above the 4.0 upper band, got {second['in_violation']}")
    assert second["cumulative_excursion_minutes"] == 20, (
        "the whole gap up to the violating sample is charged, got "
        f"{second['cumulative_excursion_minutes']}")

    shipment = get_shipment(world["shipment"]["id"])
    assert shipment["status"] == "IN_TRANSIT", (
        f"20 accumulated minutes does not flag, got {shipment['status']}")
    assert shipment["excursion_minutes"] == 20, (
        f"the load tracks the latest cumulative figure, got "
        f"{shipment['excursion_minutes']}")


def test_cascade_c_links_one_and_two_flag_the_load_and_fail_the_yeast(
        api, excursion_world):
    """35 minutes is strictly above 30, so the flag fires and the job fails.

    PRD §3.9: "every propagation job referenced by a `YEAST` line of the owning
    order whose `status` is `READY` moves `READY → FAILED` with `failure_reason`
    set to `COLD_CHAIN_EXCURSION`, and every line of the order with
    `cold_chain_required` true and `item_type` `HOP` moves `OPEN → QUARANTINED`"

    Design: Difficulty/transitive_cascade/temperature_excursion_fails_yeast_quarantines_hops_and_mints_replacement_job
    """
    world = excursion_world
    add_reading(world["shipment"]["id"], 2.0, "2026-08-01T10:00:00Z")
    add_reading(world["shipment"]["id"], 9.5, "2026-08-01T10:20:00Z")
    third = add_reading(world["shipment"]["id"], 9.0, "2026-08-01T10:35:00Z")

    assert third["interval_minutes"] == 15, (
        f"10:20 to 10:35 is fifteen minutes, got {third['interval_minutes']}")
    assert third["in_violation"] is True, (
        f"9.0 is still above the band, got {third['in_violation']}")
    assert third["cumulative_excursion_minutes"] == 35, (
        f"20 + 15 = 35, got {third['cumulative_excursion_minutes']}")

    shipment = get_shipment(world["shipment"]["id"])
    assert shipment["excursion_minutes"] == 35, (
        f"the load carries the latest figure, got {shipment['excursion_minutes']}")
    assert shipment["status"] == "EXCURSION_FLAGGED", (
        f"35 is strictly greater than 30, got {shipment['status']}")
    assert shipment["reading_count"] == 3, (
        f"three samples are on file, got {shipment['reading_count']}")
    assert shipment["last_reading_at"].startswith("2026-08-01T10:35"), (
        f"the series ends at 10:35, got {shipment['last_reading_at']}")

    job = validate_success(api.get_propagation_job(world["job"]["id"], WH_HEADERS))
    assert job["status"] == "FAILED", (
        f"the READY job behind the yeast line fails, got {job['status']}")
    assert job["failure_reason"] == "COLD_CHAIN_EXCURSION", (
        f"the flag is the stated reason, got {job['failure_reason']}")

    hop_line = validate_success(api.get_order_line(world["hop_line"]["id"],
                                                   WH_HEADERS))
    assert hop_line["status"] == "QUARANTINED", (
        f"the cold-chain hop line is quarantined, got {hop_line['status']}")
    yeast_line = validate_success(api.get_order_line(world["yeast_line"]["id"],
                                                     WH_HEADERS))
    assert yeast_line["status"] == "OPEN", (
        f"only cold-chain HOP lines are quarantined, got {yeast_line['status']}")


def test_cascade_c_link_three_mints_a_replacement_job_pushed_out_by_the_lead_time(
        api, excursion_world):
    """The only cascade that creates a row: a fresh job seven days later.

    PRD §3.9: "a replacement propagation job is created in `REQUESTED` with its
    `replaces_job_id` pointing at the failed job and its `pitch_date` pushed out by
    the strain's `propagation_lead_time_days`"

    Design: Difficulty/transitive_cascade/temperature_excursion_fails_yeast_quarantines_hops_and_mints_replacement_job
    """
    world = excursion_world
    add_reading(world["shipment"]["id"], 2.0, "2026-08-01T10:00:00Z")
    add_reading(world["shipment"]["id"], 9.5, "2026-08-01T10:20:00Z")
    add_reading(world["shipment"]["id"], 9.0, "2026-08-01T10:35:00Z")

    rows, meta = validate_paginated(api.list_propagation_jobs(
        WH_HEADERS, params={"replaces_job_id": world["job"]["id"]}))
    assert meta["total_count"] == 1, (
        f"exactly one replacement is minted, got {meta['total_count']}")
    replacement = rows[0]
    assert replacement["status"] == "REQUESTED", (
        f"the replacement opens in REQUESTED, got {replacement['status']}")
    assert replacement["replaces_job_id"] == world["job"]["id"], (
        f"it points back at the failed job, got {replacement['replaces_job_id']}")
    assert replacement["pitch_date"].startswith("2026-08-22"), (
        f"2026-08-15 pushed out by 7 days, got {replacement['pitch_date']}")
    assert replacement["brewer_id"] == world["brewer"]["id"], (
        f"the owner carries over, got {replacement['brewer_id']}")
    assert replacement["recipe_id"] == world["recipe"]["id"], (
        f"the recipe carries over, got {replacement['recipe_id']}")
    assert replacement["yeast_strain_id"] == world["strain"]["id"], (
        f"the strain carries over, got {replacement['yeast_strain_id']}")
    assert replacement["required_cells_billion"] == pytest.approx(33004.13, abs=0.005), (
        f"the recipe is unchanged, got {replacement['required_cells_billion']}")
    assert replacement["recommended_slurry_l"] == pytest.approx(55.007, abs=0.0005), (
        "a 21-day wait is clamped at the 0.50 viability floor, got "
        f"{replacement['recommended_slurry_l']}")
    assert replacement["propagation_volume_l"] == pytest.approx(63.258, abs=0.0005), (
        f"55.007 * 1.15 = 63.258, got {replacement['propagation_volume_l']}")

    failed = validate_success(api.get_propagation_job(world["job"]["id"],
                                                     WH_HEADERS))
    assert failed["recommended_slurry_l"] == pytest.approx(42.974, abs=0.0005), (
        "the failed job's own 14-day advisory is untouched, got "
        f"{failed['recommended_slurry_l']}")
    assert failed["propagation_volume_l"] == pytest.approx(49.420, abs=0.0005), (
        f"42.974 * 1.15 = 49.420, got {failed['propagation_volume_l']}")

    blocked = api.ship_order(world["order"]["id"], WH_HEADERS)
    validate_error(blocked, "ERR_COLD_CHAIN_EXCURSION", expected_status=409)
    order = validate_success(api.get_sales_order(world["order"]["id"], WH_HEADERS))
    assert order["fulfillment_status"] == "PICKED", (
        f"the flagged load blocks the shipment, got {order['fulfillment_status']}")
    assert order["invoiced_at"] is None, (
        f"nothing is invoiced, got {order['invoiced_at']}")
    assert get_brewer(world["brewer"]["id"])["ar_balance_cents"] == 0, (
        "no money moves in this cascade, got "
        f"{get_brewer(world['brewer']['id'])['ar_balance_cents']}")
