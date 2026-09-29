"""Stale-version guards, strict telemetry thresholds and read-after-write currency."""
from test_helpers import (
    AM_HEADERS,
    CM_HEADERS,
    WH_HEADERS,
    add_malt_line,
    add_reading,
    add_spot_hop_line,
    approve_credit,
    confirm_order,
    create_brewer,
    create_contract,
    create_malt_product,
    create_order,
    create_program,
    create_released_lot,
    create_variety,
    create_zone,
    depart_shipment,
    get_brewer,
    get_order,
    get_zone,
    make_brewer_headers,
    order_version,
    pick_order,
    pin_clock,
    report_harvest,
    validate_error,
    validate_paginated,
    validate_success,
)


def _stage_payload(order_id, zone_id, expected_version):
    return {
        "sales_order_id": order_id,
        "cold_storage_zone_id": zone_id,
        "expected_sales_order_version": expected_version,
        "pallet_count": 1,
        "stage_from": "2026-08-01T00:00:00Z",
        "stage_until": "2026-08-01T18:00:00Z",
        "reefer_setpoint_c": 2.0,
        "reefer_tolerance_c": 2.0,
    }


def test_an_offer_written_against_the_pre_harvest_contract_is_refused(api):
    """The harvest report already moved the version the desk would have cached.

    PRD §2.7: "Creating a substitution offer against a hop contract requires
    `expected_hop_contract_version` matching that `HopContract`'s current `version`. A
    mismatch is rejected with `ERR_STALE_HOP_CONTRACT_VERSION` (HTTP 412)."

    PRD §2.7: "When the supplied value does not equal the parent's current `version`,
    the write is rejected and nothing is mutated."

    Design: Corner/cross_cutting_complexity_layers/substitution_offer_create_rejects_a_stale_contract_version
    """
    pin_clock()
    brewer = create_brewer(name="Stale Contract Brewing",
                          brewery_license_no="BR-1056",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    citra = create_variety()
    mosaic = create_variety(variety_code="MOSAIC", name="Mosaic",
                          alpha_acid_target_pct=12.00,
                          spot_price_cents_per_lb=450.00,
                          available_spot_lbs=5000)
    program = create_program(crop_year=2026)
    contract = create_contract(brewer["id"], citra["id"], program["id"],
                              contracted_lbs=5000, price_per_lb_cents=250.00)
    assert contract["version"] == 1, (
        f"a fresh contract is at version 1, got {contract['version']}")

    report_harvest(program["id"], harvest_yield_pct=60.00)
    adjusted = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert adjusted["version"] == 2, (
        f"the harvest report is one write on the contract, got "
        f"{adjusted['version']}")
    assert adjusted["allocated_lbs"] == 3000, (
        f"60.00 percent of 5000 lb is 3000, got {adjusted['allocated_lbs']}")
    assert adjusted["status"] == "SHORTFALL_ADJUSTED", (
        f"a short crop adjusts the contract, got {adjusted['status']}")

    stale = api.create_substitution_offer(
        contract["id"],
        {"expected_hop_contract_version": 1, "selection_mode": "AUTO_RANKED",
         "offered_lbs": 2000}, AM_HEADERS)
    validate_error(stale, "ERR_STALE_HOP_CONTRACT_VERSION", expected_status=412)

    _, offer_meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": contract["id"]}))
    assert offer_meta["total_count"] == 0, (
        f"the refused create wrote no offer, got {offer_meta['total_count']}")
    assert validate_success(api.get_hop_contract(
        contract["id"], AM_HEADERS))["version"] == 2, (
        "the refused create left the contract's version alone")

    offer = validate_success(api.create_substitution_offer(
        contract["id"],
        {"expected_hop_contract_version": 2, "selection_mode": "AUTO_RANKED",
         "offered_lbs": 2000}, AM_HEADERS), expected_status=201)
    assert offer["status"] == "OPEN", (
        f"the correctly versioned offer lands open, got {offer['status']}")
    assert offer["substitute_variety_id"] == mosaic["id"], (
        "Mosaic is the only other member of the aroma group holding 2000 lb of "
        f"spot, got {offer['substitute_variety_id']}")
    assert validate_success(api.get_hop_contract(
        contract["id"], AM_HEADERS))["version"] == 3, (
        "the accepted offer bumped the contract's version")

    replay = api.create_substitution_offer(
        contract["id"],
        {"expected_hop_contract_version": 2, "selection_mode": "AUTO_RANKED",
         "offered_lbs": 2000}, AM_HEADERS)
    validate_error(replay, "ERR_STALE_HOP_CONTRACT_VERSION", expected_status=412)

    _, after_meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": contract["id"]}))
    assert after_meta["total_count"] == 1, (
        "the accepted write is not idempotently repeatable, got "
        f"{after_meta['total_count']} offers")
    assert validate_success(api.get_substitution_offer(
        offer["id"], AM_HEADERS))["status"] == "OPEN", (
        "the refused replay did not supersede the live offer")


def test_staging_on_a_stale_order_snapshot_never_reaches_the_zone_test(api):
    """The concurrency guard sits on the order and fires before zone admission.

    PRD §2.7: "Staging a reefer load requires `expected_sales_order_version` matching
    the target `SalesOrder`'s current `version`. A mismatch is rejected with
    `ERR_STALE_SALES_ORDER_VERSION` (HTTP 412)."

    PRD §2.8: "**Optimistic concurrency** (priority 19): the stale-version guards of
    §2.7."

    Design: Corner/cross_cutting_complexity_layers/shipment_staging_rejects_a_stale_order_version
    """
    pin_clock()
    brewer = create_brewer(name="Stale Order Brewing",
                          brewery_license_no="BR-1057",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety(spot_price_cents_per_lb=51.00,
                            available_spot_lbs=20000)
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                      tolerance_c=2.0)

    order = create_order(brewer["id"])
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    confirmed = confirm_order(order["id"], brewer["id"])
    assert confirmed["total_cents"] == 95380, (
        f"a single full pallet of spot Citra costs 95380, got "
        f"{confirmed['total_cents']}")
    assert confirmed["version"] == 3, (
        "create, line add and confirm are three writes, got version "
        f"{confirmed['version']}")

    stale = api.stage_shipment(_stage_payload(order["id"], zone["id"], 2),
                               WH_HEADERS)
    validate_error(stale, "ERR_STALE_SALES_ORDER_VERSION", expected_status=412)

    assert get_zone(zone["id"])["occupied_pallets"] == 0, (
        "the refusal came before the admission sweep, so no pallets were taken")
    _, load_meta = validate_paginated(api.list_shipments(
        WH_HEADERS, params={"sales_order_id": order["id"]}))
    assert load_meta["total_count"] == 0, (
        f"the refused staging wrote no load, got {load_meta['total_count']}")

    load = validate_success(api.stage_shipment(
        _stage_payload(order["id"], zone["id"], 3), WH_HEADERS),
        expected_status=201)
    assert load["status"] == "STAGED", (
        f"the correctly versioned staging lands, got {load['status']}")
    assert order_version(order["id"]) == 4, (
        "staging is one further write on the order")
    assert get_zone(zone["id"])["occupied_pallets"] == 1, (
        "the clock sits inside the half-open window, so the pallet is occupying")

    replay = api.stage_shipment(_stage_payload(order["id"], zone["id"], 3),
                               WH_HEADERS)
    validate_error(replay, "ERR_STALE_SALES_ORDER_VERSION", expected_status=412)

    assert validate_success(api.get_shipment(
        load["id"], WH_HEADERS))["status"] == "STAGED", (
        "the refused replay did not supersede the live load")
    assert get_zone(zone["id"])["occupied_pallets"] == 1, (
        "occupancy never dropped and re-rose")


def test_a_credit_reprice_from_a_superseded_snapshot_changes_nothing(api):
    """Two desks reprice the same brewery; only the one holding the live version wins.

    PRD §2.7: "Updating a brewery's credit profile requires `expected_brewer_version`
    matching that `Brewer`'s current `version`. A mismatch is rejected with
    `ERR_STALE_BREWER_VERSION` (HTTP 412)."

    PRD §3.1: "the request carries `expected_brewer_version` and may adjust any of
    `credit_limit_cents`, `credit_terms_days` or `cold_chain_certified`."

    Design: Corner/cross_cutting_complexity_layers/credit_profile_update_rejects_a_stale_brewer_version
    """
    pin_clock()
    brewer = create_brewer(name="Stale Brewer Brewing",
                          brewery_license_no="BR-1058",
                          credit_terms_days=30, credit_limit_cents=5000000,
                          cold_chain_certified=False, legacy_trailing_lbs=0)
    assert brewer["version"] == 1, (
        f"a freshly registered brewery is at version 1, got {brewer['version']}")

    first = validate_success(api.update_credit_profile(
        brewer["id"],
        {"expected_brewer_version": 1, "credit_limit_cents": 4000000,
         "cold_chain_certified": True}, CM_HEADERS))
    assert first["version"] == 2, (
        f"the accepted reprice is one write, got version {first['version']}")
    assert first["credit_limit_cents"] == 4000000, (
        f"the new ceiling is 4000000, got {first['credit_limit_cents']}")
    assert first["cold_chain_certified"] is True, (
        "the same request also certified the dock")

    stale = api.update_credit_profile(
        brewer["id"],
        {"expected_brewer_version": 1, "credit_limit_cents": 9000000},
        CM_HEADERS)
    validate_error(stale, "ERR_STALE_BREWER_VERSION", expected_status=412)

    unchanged = get_brewer(brewer["id"])
    assert unchanged["credit_limit_cents"] == 4000000, (
        "the second desk did not overwrite the first desk's ceiling, got "
        f"{unchanged['credit_limit_cents']}")
    assert unchanged["version"] == 2, (
        f"a refused write does not bump the version, got {unchanged['version']}")
    assert unchanged["credit_exposure_cents"] == 0, (
        "nothing was ordered, so exposure is still 0")
    assert unchanged["credit_utilization_pct"] == 0.00, (
        f"zero exposure is 0.00 percent, got {unchanged['credit_utilization_pct']}")
    assert unchanged["credit_status"] == "GOOD_STANDING", (
        f"an unused line is in good standing, got {unchanged['credit_status']}")

    second = validate_success(api.update_credit_profile(
        brewer["id"], {"expected_brewer_version": 2, "credit_terms_days": 45},
        CM_HEADERS))
    assert second["version"] == 3, (
        f"re-reading the version lets the write land, got {second['version']}")
    assert second["credit_terms_days"] == 45, (
        f"the terms moved to 45 days, got {second['credit_terms_days']}")
    assert second["credit_limit_cents"] == 4000000, (
        "an omitted setting is left alone rather than reset, got "
        f"{second['credit_limit_cents']}")


def test_the_accumulator_charges_the_closing_gap_and_never_rewinds(api):
    """Thirty minutes does not flag; thirty-one does, and cooling back never undoes it.

    PRD §3.9: "Its `cumulative_excursion_minutes` is the previous reading's
    `cumulative_excursion_minutes`, plus its own `interval_minutes` when and only when
    **this** reading is `in_violation`."

    PRD §3.9: "When a load's `excursion_minutes` after applying a reading is **strictly
    greater** than 30 minutes, the load is flagged, moving `IN_TRANSIT →
    EXCURSION_FLAGGED` — exactly 30 accumulated minutes does not flag."

    PRD §3.9: "Once flagged, the load stops accumulating and further readings are
    refused with `ERR_INVALID_SHIPMENT_STATE`"

    Design: Corner/cross_cutting_complexity_layers/excursion_thresholds_are_strict_and_the_accumulator_never_resets
    """
    pin_clock()
    brewer = create_brewer(name="Strict Threshold Brewing",
                          brewery_license_no="BR-1059",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety(spot_price_cents_per_lb=51.00,
                            available_spot_lbs=20000)
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                      tolerance_c=2.0)

    order = create_order(brewer["id"])
    line = add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    assert line["cold_chain_required"] is True, (
        "Citra needs cold storage, so the line rides the reefer")
    confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"])
    pick_order(order["id"])
    assert order_version(order["id"]) == 5, (
        "create, line, confirm, credit decision and pick are five writes")

    load = validate_success(api.stage_shipment(
        _stage_payload(order["id"], zone["id"], 5), WH_HEADERS),
        expected_status=201)
    assert load["excursion_minutes"] == 0, (
        f"a staged load starts clean, got {load['excursion_minutes']}")
    assert depart_shipment(load["id"])["status"] == "IN_TRANSIT", (
        "the load is on the road before any probe reports")

    first = add_reading(load["id"], 4.00, "2026-08-01T06:00:00Z")
    assert first["in_violation"] is False, (
        "4.00 sits exactly on the upper band edge, which is in tolerance")
    assert first["interval_minutes"] == 0, (
        f"the first reading has no predecessor, got {first['interval_minutes']}")
    assert first["cumulative_excursion_minutes"] == 0, (
        f"nothing to charge yet, got {first['cumulative_excursion_minutes']}")

    second = add_reading(load["id"], 4.01, "2026-08-01T06:30:00Z")
    assert second["in_violation"] is True, (
        "one hundredth above the edge is strictly above the band")
    assert second["interval_minutes"] == 30, (
        f"half an hour separates the samples, got {second['interval_minutes']}")
    assert second["cumulative_excursion_minutes"] == 30, (
        "the whole gap leading up to the violating sample is charged in full, got "
        f"{second['cumulative_excursion_minutes']}")

    at_thirty = validate_success(api.get_shipment(load["id"], WH_HEADERS))
    assert at_thirty["status"] == "IN_TRANSIT", (
        f"exactly thirty minutes does not flag, got {at_thirty['status']}")
    assert at_thirty["excursion_minutes"] == 30, (
        f"the load carries the latest total, got {at_thirty['excursion_minutes']}")

    third = add_reading(load["id"], 0.00, "2026-08-01T06:31:00Z")
    assert third["in_violation"] is False, (
        "0.00 sits exactly on the lower band edge, which is in tolerance")
    assert third["interval_minutes"] == 1, (
        f"one minute separates the samples, got {third['interval_minutes']}")
    assert third["cumulative_excursion_minutes"] == 30, (
        "cooling back into tolerance neither charges nor refunds, got "
        f"{third['cumulative_excursion_minutes']}")

    fourth = add_reading(load["id"], -0.01, "2026-08-01T06:32:00Z")
    assert fourth["in_violation"] is True, (
        "one hundredth below the edge is strictly below the band")
    assert fourth["cumulative_excursion_minutes"] == 31, (
        "the accumulator resumes from 30 rather than from zero, got "
        f"{fourth['cumulative_excursion_minutes']}")

    flagged = validate_success(api.get_shipment(load["id"], WH_HEADERS))
    assert flagged["status"] == "EXCURSION_FLAGGED", (
        f"thirty-one minutes is a strict excess, got {flagged['status']}")
    assert flagged["excursion_minutes"] == 31, (
        f"the flagged total is 31, got {flagged['excursion_minutes']}")
    assert flagged["reading_count"] == 4, (
        f"four samples were accepted, got {flagged['reading_count']}")

    assert validate_success(api.get_order_line(
        line["id"], AM_HEADERS))["status"] == "QUARANTINED", (
        "cascade C quarantined the cold-chain hop line the load carried")
    _, job_meta = validate_paginated(api.list_propagation_jobs(
        WH_HEADERS, params={"brewer_id": brewer["id"]}))
    assert job_meta["total_count"] == 0, (
        "this order carried no yeast, so link 3 minted no replacement job, got "
        f"{job_meta['total_count']}")

    refused = api.add_reading(load["id"], {"temp_c": 2.00,
                                          "recorded_at": "2026-08-01T06:33:00Z"},
                             WH_HEADERS)
    validate_error(refused, "ERR_INVALID_SHIPMENT_STATE", expected_status=409)
    assert validate_success(api.get_shipment(
        load["id"], WH_HEADERS))["reading_count"] == 4, (
        "the refused sample was not appended to the series")


def test_one_confirm_settles_the_order_the_brewer_and_the_lot_at_once(api):
    """Every figure the confirm moved is already true on the very next read.

    PRD §2.12: "The system performs those propagations immediately and synchronously
    within the triggering request — there is no deferred or eventual reconciliation —
    and each affected resource independently refreshes its `updated_at` and increments
    its `version`, including resources the client never named."

    PRD §3.1: "Three figures drive the brewery's credit standing and they are
    recomputed on every write that changes the receivable balance or any order total."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_response_that_caused_it
    """
    pin_clock()
    brewer = create_brewer(name="Read After Write Brewing",
                          brewery_license_no="BR-1060",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-RAW-1")
    assert lot["available_lbs"] == 5000, (
        f"the whole released lot is on offer, got {lot['available_lbs']}")
    assert lot["committed_lbs"] == 0, (
        f"nothing is drawn against it yet, got {lot['committed_lbs']}")

    brewer_headers = make_brewer_headers(brewer["id"])
    order = create_order(brewer["id"])
    assert order["fulfillment_status"] == "DRAFT", (
        f"the order opens in draft, got {order['fulfillment_status']}")

    line = add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    assert line["extended_cents"] == 68500, (
        f"1000 lb at 68.50 cents is 68500 cents, got {line['extended_cents']}")
    assert line["pallet_break"] is True, (
        "1000 lb is not a whole multiple of the 2200 lb pallet")

    after_line = get_order(order["id"], brewer_headers)
    assert after_line["subtotal_cents"] == 68500, (
        f"the parent roll-up already sees the line, got "
        f"{after_line['subtotal_cents']}")
    assert after_line["line_count"] == 1, (
        f"one line is on the order, got {after_line['line_count']}")
    assert after_line["total_cents"] == 0, (
        "a draft carries no total until its first fee assessment, got "
        f"{after_line['total_cents']}")

    confirmed = confirm_order(order["id"], brewer["id"])
    assert confirmed["total_cents"] == 105500, (
        f"68500 plus 25000 freight, 4500 pallet break and 7500 small order is "
        f"105500, got {confirmed['total_cents']}")
    assert confirmed["freight_cents"] == 25000, (
        f"the rated 12000 cents floors to the tier's 25000 minimum, got "
        f"{confirmed['freight_cents']}")
    assert confirmed["pallet_break_fee_cents"] == 4500, (
        f"one breaking line costs 4500, got {confirmed['pallet_break_fee_cents']}")
    assert confirmed["small_order_surcharge_cents"] == 7500, (
        f"1000 chargeable lb is under 2000, got "
        f"{confirmed['small_order_surcharge_cents']}")
    assert confirmed["fee_variant"] == "PROVISIONAL", (
        f"confirmation assesses the provisional variant, got "
        f"{confirmed['fee_variant']}")
    assert confirmed["freight_tier_applied"] == "TIER_1", (
        f"an unrated brewery ships on TIER_1, got "
        f"{confirmed['freight_tier_applied']}")

    reread = get_order(order["id"], brewer_headers)
    assert reread["total_cents"] == 105500, (
        f"re-reading the order changes nothing, got {reread['total_cents']}")
    assert reread["fee_variant"] == "PROVISIONAL", (
        f"nor does it re-assess the variant, got {reread['fee_variant']}")

    repriced = get_brewer(brewer["id"])
    assert repriced["credit_exposure_cents"] == 105500, (
        "the brewery the client never named is already repriced, got "
        f"{repriced['credit_exposure_cents']}")
    assert repriced["credit_utilization_pct"] == 2.11, (
        f"105500 of 5000000 is 2.11 percent, got "
        f"{repriced['credit_utilization_pct']}")
    assert repriced["credit_status"] == "GOOD_STANDING", (
        f"two percent is nowhere near a watch, got {repriced['credit_status']}")

    drawn = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert drawn["committed_lbs"] == 1000, (
        f"the confirmed line committed 1000 lb, got {drawn['committed_lbs']}")
    assert drawn["available_lbs"] == 4000, (
        f"5000 less the 1000 committed is 4000, got {drawn['available_lbs']}")
