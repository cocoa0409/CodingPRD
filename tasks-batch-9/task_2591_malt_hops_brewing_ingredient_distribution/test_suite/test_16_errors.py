"""One violation, one code: the refusals each rule is allowed to report."""
from test_helpers import (
    ALLOC_1_HEADERS,
    AM_HEADERS,
    CM_HEADERS,
    NON_EXISTENT_UUID,
    WH_HEADERS,
    add_contract_hop_line,
    add_malt_line,
    add_spot_hop_line,
    add_yeast_line,
    approve_credit,
    complete_propagation,
    confirm_order,
    create_brewer,
    create_contract,
    create_job,
    create_malt_product,
    create_order,
    create_program,
    create_recipe,
    create_released_lot,
    create_strain,
    create_variety,
    create_zone,
    get_brewer,
    get_order,
    make_brewer_headers,
    pin_clock,
    report_harvest,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_three_identity_failures_are_distinct_and_outrank_the_payload(
        api, invalid_role_headers):
    """A malformed body is never reported to a role that cannot use the endpoint.

    PRD §2.1: "If either header is absent or empty the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.1: "A value of `X-User-Role` that is not one of those five is rejected
    with `ERR_INVALID_ROLE` (HTTP 403). A syntactically valid role that is not among
    the roles authorised for the requested operation — see the authorised-role column
    in §4 — is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.8: "When one request violates several rules, the response carries the
    error belonging to the **lowest** priority number, and only that error."

    Design: Corner/errors/identity_headers_are_the_outermost_gate
    """
    pin_clock()
    product = create_malt_product()
    good_body = {"malt_product_id": product["id"], "lot_code": "LOT-HG-1",
                 "quantity_lbs": 4000}

    naked = api.create_malt_lot(good_body, {})
    validate_error(naked, "ERR_UNAUTHENTICATED", expected_status=401)

    unknown_role = api.create_malt_lot(good_body, invalid_role_headers)
    validate_error(unknown_role, "ERR_INVALID_ROLE", expected_status=403)

    wrong_desk = api.create_malt_lot(good_body, CM_HEADERS)
    validate_error(wrong_desk, "ERR_ROLE_NOT_PERMITTED", expected_status=403)

    wrong_desk_bad_body = api.create_malt_lot({"lot_code": "LOT-HG-2"}, CM_HEADERS)
    validate_error(wrong_desk_bad_body, "ERR_ROLE_NOT_PERMITTED",
                   expected_status=403)

    accepted = validate_success(api.create_malt_lot(good_body, WH_HEADERS),
                               expected_status=201)
    assert accepted["status"] == "RECEIVED", (
        "the same body from the floor is admitted, got "
        f"{accepted['status']}")

    naked_read = api.list_malt_lots({})
    validate_error(naked_read, "ERR_UNAUTHENTICATED", expected_status=401)


def test_each_unresolved_identifier_blames_the_entity_it_names(api):
    """A phantom program is reported as a missing program, not a missing contract.

    PRD §2.8: "Identifiers supplied in a request body or query string are checked at
    priority 7, after the `Brewer` scope check at priority 6, and each reports the
    not-found code for the entity it names"

    PRD §2.8: "All of these carry HTTP 404."

    Design: Corner/errors/every_unresolved_reference_names_its_own_entity
    """
    pin_clock()
    brewer = create_brewer(name="Dangling Reference Brewing",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    strain = create_strain()

    phantom_program = api.create_hop_contract(
        {"brewer_id": brewer["id"], "variety_id": variety["id"],
         "crop_year_program_id": NON_EXISTENT_UUID,
         "contract_type": "FIXED_CROP_YEAR", "contracted_lbs": 5000,
         "price_per_lb_cents": 250.00,
         "delivery_window_start": "2026-09-01T00:00:00Z",
         "delivery_window_end": "2026-12-31T00:00:00Z"}, AM_HEADERS)
    validate_error(phantom_program, "ERR_CROP_YEAR_PROGRAM_NOT_FOUND",
                   expected_status=404)

    validate_error(api.get_hop_contract(NON_EXISTENT_UUID, AM_HEADERS),
                   "ERR_HOP_CONTRACT_NOT_FOUND", expected_status=404)
    validate_error(api.get_substitution_offer(NON_EXISTENT_UUID, AM_HEADERS),
                   "ERR_SUBSTITUTION_OFFER_NOT_FOUND", expected_status=404)
    validate_error(api.get_propagation_job(NON_EXISTENT_UUID, WH_HEADERS),
                   "ERR_YEAST_JOB_NOT_FOUND", expected_status=404)
    validate_error(api.get_cold_storage_zone(NON_EXISTENT_UUID, WH_HEADERS),
                   "ERR_COLD_STORAGE_ZONE_NOT_FOUND", expected_status=404)
    validate_error(api.get_shipment(NON_EXISTENT_UUID, WH_HEADERS),
                   "ERR_COLD_CHAIN_SHIPMENT_NOT_FOUND", expected_status=404)

    phantom_recipe = api.create_propagation_job(
        {"brewer_id": brewer["id"], "recipe_id": NON_EXISTENT_UUID,
         "yeast_strain_id": strain["id"],
         "pitch_date": "2026-08-20T00:00:00Z"},
        make_brewer_headers(brewer["id"]))
    validate_error(phantom_recipe, "ERR_BREWER_RECIPE_NOT_FOUND",
                   expected_status=404)

    _, meta = validate_paginated(api.list_hop_contracts(AM_HEADERS))
    assert meta["total_count"] == 0, (
        f"none of the refusals wrote a row, got {meta['total_count']}")


def test_a_line_that_belongs_to_a_sibling_order_is_simply_not_found(api):
    """Cross-order deletion is impossible, even between two orders of one brewery.

    PRD §2.8: "Deleting a line from an order, for instance, resolves the order first
    and reports `ERR_SALES_ORDER_NOT_FOUND` before it ever looks for the line; only
    once the order resolves does an unresolvable line segment — or a line that
    resolves but belongs to a different order — report `ERR_ORDER_LINE_NOT_FOUND`."

    Design: Corner/errors/a_line_id_from_another_order_is_not_found
    """
    pin_clock()
    brewer = create_brewer(name="Cross Order Brewing",
                          brewery_license_no="BR-1047",
                          credit_limit_cents=5000000,
                          cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000)

    order_a = create_order(brewer["id"])
    line_a = add_malt_line(order_a["id"], brewer["id"], lot["id"], 1000)
    order_b = create_order(brewer["id"])
    line_b = add_malt_line(order_b["id"], brewer["id"], lot["id"], 1000)

    stolen = api.remove_order_line(order_a["id"], line_b["id"],
                                   make_brewer_headers(brewer["id"]))
    validate_error(stolen, "ERR_ORDER_LINE_NOT_FOUND", expected_status=404)

    surviving = validate_success(api.get_order_line(
        line_b["id"], make_brewer_headers(brewer["id"])))
    assert surviving["status"] == "OPEN", (
        f"B's line is untouched by A's delete, got {surviving['status']}")
    assert get_order(order_b["id"])["line_count"] == 1, (
        "order B still holds its one line")

    phantom = api.remove_order_line(order_a["id"], NON_EXISTENT_UUID,
                                    make_brewer_headers(brewer["id"]))
    validate_error(phantom, "ERR_ORDER_LINE_NOT_FOUND", expected_status=404)

    emptied = validate_success(api.remove_order_line(
        order_a["id"], line_a["id"], make_brewer_headers(brewer["id"])))
    assert emptied["line_count"] == 0, (
        f"A's own line comes off cleanly, got line_count {emptied['line_count']}")
    assert emptied["subtotal_cents"] == 0, (
        f"the roll-up drops to zero, got {emptied['subtotal_cents']}")
    assert emptied["requires_cold_chain"] is False, (
        "an ambient malt order never demanded cold chain")
    removed = validate_success(api.get_order_line(
        line_a["id"], make_brewer_headers(brewer["id"])))
    assert removed["status"] == "REMOVED", (
        f"the deleted line is tombstoned, got {removed['status']}")


def test_a_colliding_crop_year_and_four_colliding_codes_report_differently(api):
    """One dedicated collision code, and one shared code for the four catalogues.

    PRD §2.10: "A duplicate `crop_year` on a crop-year program reports
    `ERR_DUPLICATE_CROP_YEAR`; a duplicate `lot_code` on a malt lot reports
    `ERR_DUPLICATE_LOT_CODE`; a duplicate `brewery_license_no` on a brewery reports
    `ERR_DUPLICATE_BREWERY_LICENSE`; and a duplicate `zone_code` on a cold storage
    zone, `variety_code` on a hop variety, `sku` on a malt product or `strain_code`
    on a yeast strain all report `ERR_DUPLICATE_RESOURCE_CODE`."

    Design: Corner/errors/each_unique_key_reports_its_own_collision_code
    """
    pin_clock()
    program = create_program(crop_year=2026)
    create_zone()
    create_variety()
    create_malt_product()
    create_strain()

    same_year = api.create_crop_year_program(
        {"crop_year": 2026, "contract_open_date": "2026-02-01T00:00:00Z",
         "harvest_report_due_date": "2026-09-15T00:00:00Z"}, AM_HEADERS)
    validate_error(same_year, "ERR_DUPLICATE_CROP_YEAR", expected_status=409)

    same_zone = api.create_cold_storage_zone(
        {"zone_code": "Z1", "temp_setpoint_c": 4.0, "capacity_pallets": 6,
         "tolerance_c": 1.5}, WH_HEADERS)
    validate_error(same_zone, "ERR_DUPLICATE_RESOURCE_CODE", expected_status=409)

    same_variety = api.create_hop_variety(
        {"variety_code": "CITRA", "name": "Citra Reprise",
         "substitution_group": "AROMA_HIGH_ALPHA", "alpha_acid_target_pct": 11.00,
         "spot_price_cents_per_lb": 60.00, "available_spot_lbs": 1000,
         "cold_storage_required": True, "pallet_quantity_lbs": 880,
         "min_order_lbs": 44}, AM_HEADERS)
    validate_error(same_variety, "ERR_DUPLICATE_RESOURCE_CODE",
                   expected_status=409)

    same_sku = api.create_malt_product(
        {"sku": "PALE-ALE", "name": "Pale Ale Malt Redux", "malt_class": "BASE",
         "list_price_cents_per_lb": 70.00, "max_moisture_pct": 5.0,
         "min_diastatic_power": 60.0, "pallet_quantity_lbs": 2200,
         "min_order_lbs": 55}, WH_HEADERS)
    validate_error(same_sku, "ERR_DUPLICATE_RESOURCE_CODE", expected_status=409)

    same_strain = api.create_yeast_strain(
        {"strain_code": "WLP001", "name": "California Ale Again",
         "fermentation_type": "ALE", "propagation_lead_time_days": 5,
         "list_price_cents_per_l": 1100.00, "viability_pct_at_ship": 90.0,
         "cells_per_ml_slurry_billion": 1.1, "min_batch_l": 20.0,
         "vessel_max_l": 1000.0}, WH_HEADERS)
    validate_error(same_strain, "ERR_DUPLICATE_RESOURCE_CODE",
                   expected_status=409)

    fresh_year = validate_success(api.create_crop_year_program(
        {"crop_year": 2027, "contract_open_date": "2027-01-15T00:00:00Z",
         "harvest_report_due_date": "2027-10-01T00:00:00Z"}, AM_HEADERS),
        expected_status=201)
    assert fresh_year["id"] != program["id"], (
        "a distinct crop year is a distinct program")

    _, program_meta = validate_paginated(api.list_crop_year_programs(AM_HEADERS))
    assert program_meta["total_count"] == 2, (
        f"only the two accepted programs exist, got {program_meta['total_count']}")

    surviving = validate_success(api.get_crop_year_program(program["id"],
                                                          AM_HEADERS))
    assert surviving["contract_open_date"].startswith("2026-01-15T00:00:00"), (
        "the refused duplicate left the original program's dates alone, got "
        f"{surviving['contract_open_date']}")


def test_three_different_bad_targets_share_one_carry_forward_target_code(api):
    """The source itself, a skipped crop year and a settled next year all refuse alike.

    PRD §3.5: "The named target program must exist, must carry a `crop_year` exactly
    one greater than the source program's `crop_year`, must itself be `OPEN`, and must
    not be the source program; any of those failing is refused with
    `ERR_INVALID_CARRY_FORWARD_TARGET`."

    PRD §3.5: "The accepted request writes `carry_forward_requested_lbs` equal to the
    requested poundage and `carry_forward_fee_cents` equal to the requested poundage
    multiplied by `price_per_lb_cents`, multiplied by 8 and divided by 100, rounded
    half up to whole cents."

    Design: Corner/errors/carry_forward_target_must_be_the_next_open_crop_year
    """
    pin_clock()
    brewer = create_brewer(name="Next Year Brewing", credit_limit_cents=9000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    programs = {year: create_program(crop_year=year)
                for year in (2026, 2027, 2028, 2029, 2030)}

    contract_a = create_contract(
        brewer["id"], variety["id"], programs[2026]["id"],
        contracted_lbs=5000, price_per_lb_cents=250.00,
        delivery_window_start="2026-09-01T00:00:00Z",
        delivery_window_end="2026-12-31T00:00:00Z")
    contract_b = create_contract(
        brewer["id"], variety["id"], programs[2028]["id"],
        contracted_lbs=4000, price_per_lb_cents=250.00,
        delivery_window_start="2028-09-01T00:00:00Z",
        delivery_window_end="2028-12-31T00:00:00Z")

    report_harvest(programs[2026]["id"], harvest_yield_pct=100.00)
    report_harvest(programs[2028]["id"], harvest_yield_pct=100.00)
    reported_29 = report_harvest(programs[2029]["id"], harvest_yield_pct=100.00)
    assert reported_29["allocatable_pool_lbs"] == 0, (
        "a program carrying no contracts still reports a pool, got "
        f"{reported_29['allocatable_pool_lbs']}")
    settled_29 = validate_success(api.settle_program(
        programs[2029]["id"], {"settlement_note": "empty crop year"}, AM_HEADERS))
    assert settled_29["status"] == "SETTLED", (
        f"the 2029 program is closed, got {settled_29['status']}")

    brewer_headers = make_brewer_headers(brewer["id"])
    version_before = validate_success(
        api.get_hop_contract(contract_a["id"], AM_HEADERS))["version"]

    onto_itself = api.request_carry_forward(
        contract_a["id"],
        {"carry_forward_target_program_id": programs[2026]["id"],
         "requested_lbs": 1000, "justification": "roll into myself"},
        brewer_headers)
    validate_error(onto_itself, "ERR_INVALID_CARRY_FORWARD_TARGET",
                   expected_status=422)

    skipping_a_year = api.request_carry_forward(
        contract_a["id"],
        {"carry_forward_target_program_id": programs[2030]["id"],
         "requested_lbs": 1000, "justification": "skip ahead four years"},
        brewer_headers)
    validate_error(skipping_a_year, "ERR_INVALID_CARRY_FORWARD_TARGET",
                   expected_status=422)

    onto_a_settled_year = api.request_carry_forward(
        contract_b["id"],
        {"carry_forward_target_program_id": programs[2029]["id"],
         "requested_lbs": 800, "justification": "right year, wrong status"},
        brewer_headers)
    validate_error(onto_a_settled_year, "ERR_INVALID_CARRY_FORWARD_TARGET",
                   expected_status=422)

    untouched = validate_success(api.get_hop_contract(contract_a["id"],
                                                     AM_HEADERS))
    assert untouched["status"] == "ACTIVE", (
        f"three refusals left contract A active, got {untouched['status']}")
    assert untouched["carry_forward_target_program_id"] is None, (
        "no target was stamped by a refused request, got "
        f"{untouched['carry_forward_target_program_id']}")
    assert untouched["version"] == version_before, (
        f"a refusal is not a write, expected version {version_before}, got "
        f"{untouched['version']}")

    rolled = validate_success(api.request_carry_forward(
        contract_a["id"],
        {"carry_forward_target_program_id": programs[2027]["id"],
         "requested_lbs": 1250, "justification": "tank space"}, brewer_headers))
    assert rolled["status"] == "CARRY_FORWARD_PENDING", (
        f"the next open crop year is accepted, got {rolled['status']}")
    assert rolled["carry_forward_requested_lbs"] == 1250, (
        "1250 is exactly 25 percent of the original 5000, got "
        f"{rolled['carry_forward_requested_lbs']}")
    assert rolled["carry_forward_fee_cents"] == 25000, (
        "1250 * 250.00 * 8 / 100 is 25000 cents, got "
        f"{rolled['carry_forward_fee_cents']}")

    b_after = validate_success(api.get_hop_contract(contract_b["id"], AM_HEADERS))
    assert b_after["status"] == "ACTIVE", (
        f"contract B was never mutated, got {b_after['status']}")
    assert b_after["remaining_lbs"] == 4000, (
        f"contract B is still wholly undrawn, got {b_after['remaining_lbs']}")


def test_a_fully_drawn_contract_reports_the_cap_on_one_route_and_the_volume_on_the_other(api):
    """Zero remaining poundage surfaces as the cap error where the cap is judged first.

    PRD §3.5: "And finally the contract's `remaining_lbs` must be greater than zero —
    a fully drawn contract can be neither carried forward nor defaulted — with a
    violation refused as `ERR_NO_UNCOMMITTED_VOLUME`. Those last two are evaluated in
    that order, the cap test before the uncommitted-volume test, which is why a
    request against a fully drawn contract normally surfaces as the cap error."

    PRD §3.5: "The contract must be in `ACTIVE` or `SHORTFALL_ADJUSTED` and must have
    `remaining_lbs` greater than zero, refused respectively with
    `ERR_INVALID_CONTRACT_STATE` and `ERR_NO_UNCOMMITTED_VOLUME`."

    PRD §2.11: "The invariant that must hold after every write to a contract is that
    `allocated_lbs` equals the sum of those five figures"

    Design: Corner/errors/a_fully_drawn_contract_can_be_neither_defaulted_nor_rolled
    """
    pin_clock()
    brewer = create_brewer(name="Fully Drawn Brewing", credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety(spot_price_cents_per_lb=51.00)
    program_26 = create_program(crop_year=2026)
    program_27 = create_program(crop_year=2027)
    contract = create_contract(brewer["id"], variety["id"], program_26["id"],
                              contracted_lbs=5000, price_per_lb_cents=250.00)

    order = create_order(brewer["id"])
    line = add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                                contract["id"], 5000)
    assert line["extended_cents"] == 1250000, (
        f"5000 lb at 250.00 contract price is 1250000, got {line['extended_cents']}")
    assert line["pallet_break"] is True, (
        "5000 modulo 880 leaves 600 lb, so the line breaks a pallet")

    confirmed = confirm_order(order["id"], brewer["id"])
    assert confirmed["volume_discount_cents"] == 18750, (
        "1.5 percent of a 1250000 subtotal is 18750, got "
        f"{confirmed['volume_discount_cents']}")
    assert confirmed["freight_cents"] == 78000, (
        "5000 lb at the TIER_1 rate is 60000 plus the 18000 reefer surcharge, got "
        f"{confirmed['freight_cents']}")
    assert confirmed["total_cents"] == 1313750, (
        "1250000 - 18750 + 78000 + 4500 is 1313750, got "
        f"{confirmed['total_cents']}")

    report_harvest(program_26["id"], harvest_yield_pct=100.00)
    drawn = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert drawn["status"] == "ACTIVE", (
        f"a full crop leaves the contract active, got {drawn['status']}")
    assert drawn["committed_lbs"] == 5000, (
        f"the confirmed order took the whole commitment, got {drawn['committed_lbs']}")
    assert drawn["remaining_lbs"] == 0, (
        f"nothing is left undrawn, got {drawn['remaining_lbs']}")

    one_pound = api.request_carry_forward(
        contract["id"],
        {"carry_forward_target_program_id": program_27["id"],
         "requested_lbs": 1, "justification": "one pound"},
        make_brewer_headers(brewer["id"]))
    validate_error(one_pound, "ERR_CARRY_FORWARD_EXCEEDS_CAP",
                   expected_status=422)

    walk_away = api.declare_default(
        contract["id"], {"default_reason": "nothing left to walk away from"},
        ALLOC_1_HEADERS)
    validate_error(walk_away, "ERR_NO_UNCOMMITTED_VOLUME", expected_status=422)

    after = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert after["status"] == "ACTIVE", (
        f"neither refusal moved the contract, got {after['status']}")
    assert after["defaulted_lbs"] == 0, (
        f"no poundage was defaulted, got {after['defaulted_lbs']}")
    assert after["settlement_total_cents"] is None, (
        f"no settlement was priced, got {after['settlement_total_cents']}")
    assert after["defaulted_by_user_id"] is None, (
        f"no defaulting operator was recorded, got {after['defaulted_by_user_id']}")
    assert get_brewer(brewer["id"])["ar_balance_cents"] == 0, (
        "the refused default booked nothing, so cascade B never started")

    assert after["allocated_lbs"] == (
        after["remaining_lbs"] + after["committed_lbs"]
        + after["carried_forward_out_lbs"] + after["defaulted_lbs"]
        + after["resold_lbs"]), (
        f"the five buckets must still partition {after['allocated_lbs']}")


def test_the_limit_breach_fires_from_a_watch_posture_not_from_a_hold(api):
    """WATCH is a warning that lets priority 44 pass and priority 45 do the refusing.

    PRD §3.8: "Finally the owning brewery's `credit_status` must not be `HOLD`,
    otherwise `ERR_BREWER_CREDIT_HOLD`, and the brewery's `credit_exposure_cents` plus
    this order's freshly computed `total_cents` must not exceed its
    `credit_limit_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED`; exposure landing
    exactly on the limit is accepted."

    PRD §3.1: "`credit_status` is `HOLD` when `credit_exposure_cents` is **strictly
    greater** than `credit_limit_cents`; otherwise `WATCH` when
    `credit_utilization_pct` is at least 85.00; otherwise `GOOD_STANDING`."

    Design: Corner/errors/credit_limit_breach_is_reported_while_the_posture_is_only_watch
    """
    pin_clock()
    brewer = create_brewer(name="Thin Limit Brewing", credit_limit_cents=100000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety(spot_price_cents_per_lb=51.00,
                            available_spot_lbs=20000)

    order_a = create_order(brewer["id"])
    add_spot_hop_line(order_a["id"], brewer["id"], variety["id"], 880)
    order_b = create_order(brewer["id"])
    add_spot_hop_line(order_b["id"], brewer["id"], variety["id"], 880)

    pre = get_brewer(brewer["id"])
    assert pre["credit_exposure_cents"] == 0, (
        "a DRAFT order carries total_cents 0, so exposure is nil, got "
        f"{pre['credit_exposure_cents']}")
    assert pre["credit_status"] == "GOOD_STANDING", (
        f"nothing is owed yet, got {pre['credit_status']}")

    confirmed = confirm_order(order_a["id"], brewer["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        f"order A is admitted, got {confirmed['fulfillment_status']}")
    assert confirmed["total_cents"] == 95380, (
        "44880 subtotal, 25000 freight minimum plus 18000 reefer, plus the 7500 "
        f"small-order surcharge is 95380, got {confirmed['total_cents']}")

    mid = get_brewer(brewer["id"])
    assert mid["credit_exposure_cents"] == 95380, (
        f"the confirmed total is the whole exposure, got "
        f"{mid['credit_exposure_cents']}")
    assert float(mid["credit_utilization_pct"]) == 95.38, (
        "95380 of a 100000 limit is 95.38 percent, got "
        f"{mid['credit_utilization_pct']}")
    assert mid["credit_status"] == "WATCH", (
        f"95.38 percent is a warning, not a hold, got {mid['credit_status']}")

    second = api.confirm_order(order_b["id"], make_brewer_headers(brewer["id"]))
    validate_error(second, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=402)

    still_draft = get_order(order_b["id"])
    assert still_draft["fulfillment_status"] == "DRAFT", (
        f"the refused order never left DRAFT, got "
        f"{still_draft['fulfillment_status']}")
    assert still_draft["total_cents"] == 0, (
        f"a DRAFT order has no total, got {still_draft['total_cents']}")
    assert get_brewer(brewer["id"])["credit_exposure_cents"] == 95380, (
        "the refused confirm added nothing to the exposure")
    assert validate_success(api.get_hop_variety(
        variety["id"], AM_HEADERS))["available_spot_lbs"] == 19120, (
        "only order A reserved its pallet out of the 20000 lb spot pool")


def test_all_three_bench_verbs_share_one_code_from_the_wrong_state(api):
    """Each verb has one legal from-state, and a refusal never bumps the version.

    PRD §3.7: "Both increment the job's `version`, and a close attempted from any
    status other than `PROPAGATING` — like a start attempted from any status other
    than `REQUESTED` — is refused with `ERR_INVALID_JOB_STATE`."

    PRD §3.7: "The warehouse starts a propagation, moving the job `REQUESTED →
    PROPAGATING` and stamping `ready_at` as the current logical clock plus the
    strain's `propagation_lead_time_days` days"

    PRD §3.7: "A requeue supplies a `new_pitch_date` and moves the job `FAILED →
    REQUESTED`, setting `pitch_date` to the new date and clearing both
    `failure_reason` and `ready_at` back to null."

    Design: Corner/errors/propagation_transitions_are_refused_from_the_wrong_state
    """
    pin_clock()
    brewer = create_brewer(name="Wrong State Brewing", credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain(propagation_lead_time_days=7)
    recipe = create_recipe(brewer["id"], product["id"], strain["id"])
    job = create_job(brewer["id"], recipe["id"], strain["id"],
                    pitch_date="2026-08-20T00:00:00Z")
    assert job["status"] == "REQUESTED", (
        f"a fresh booking sits in REQUESTED, got {job['status']}")
    assert job["version"] == 1, (
        f"a fresh booking is at version 1, got {job['version']}")

    early_close = api.complete_propagation(job["id"], {"outcome": "READY"},
                                           WH_HEADERS)
    validate_error(early_close, "ERR_INVALID_JOB_STATE", expected_status=409)

    early_requeue = api.requeue_propagation(
        job["id"], {"new_pitch_date": "2026-08-25T00:00:00Z"}, WH_HEADERS)
    validate_error(early_requeue, "ERR_INVALID_JOB_STATE", expected_status=409)

    untouched = validate_success(api.get_propagation_job(job["id"], WH_HEADERS))
    assert untouched["version"] == 1, (
        f"two refusals left the version alone, got {untouched['version']}")

    started = validate_success(api.start_propagation(job["id"], WH_HEADERS))
    assert started["status"] == "PROPAGATING", (
        f"the bench is running, got {started['status']}")
    assert started["version"] == 2, (
        f"the start is the first real write, got version {started['version']}")
    assert started["ready_at"].startswith("2026-08-08T00:00:00"), (
        "2026-08-01 plus a seven-day lead time is 2026-08-08, got "
        f"{started['ready_at']}")

    double_start = api.start_propagation(job["id"], WH_HEADERS)
    validate_error(double_start, "ERR_INVALID_JOB_STATE", expected_status=409)

    requeue_running = api.requeue_propagation(
        job["id"], {"new_pitch_date": "2026-08-25T00:00:00Z"}, WH_HEADERS)
    validate_error(requeue_running, "ERR_INVALID_JOB_STATE", expected_status=409)

    failed = validate_success(api.complete_propagation(
        job["id"], {"outcome": "FAILED",
                    "failure_reason": "vessel contamination"}, WH_HEADERS))
    assert failed["status"] == "FAILED", (
        f"the bench lost the batch, got {failed['status']}")
    assert failed["version"] == 3, (
        f"the close is the second real write, got version {failed['version']}")
    assert failed["failure_reason"] == "vessel contamination", (
        f"the reason is recorded verbatim, got {failed['failure_reason']}")

    double_close = api.complete_propagation(job["id"], {"outcome": "READY"},
                                            WH_HEADERS)
    validate_error(double_close, "ERR_INVALID_JOB_STATE", expected_status=409)

    rebooked = validate_success(api.requeue_propagation(
        job["id"], {"new_pitch_date": "2026-08-25T00:00:00Z"}, WH_HEADERS))
    assert rebooked["status"] == "REQUESTED", (
        f"only FAILED admits a requeue, got {rebooked['status']}")
    assert rebooked["version"] == 4, (
        f"the requeue is the third real write, got version {rebooked['version']}")
    assert rebooked["pitch_date"].startswith("2026-08-25T00:00:00"), (
        f"the new pitch date is adopted, got {rebooked['pitch_date']}")
    assert rebooked["failure_reason"] is None, (
        f"the requeue clears the reason, got {rebooked['failure_reason']}")
    assert rebooked["ready_at"] is None, (
        f"the requeue clears the readiness stamp, got {rebooked['ready_at']}")


def test_readiness_gates_the_pick_and_never_the_confirm(api):
    """A yeast-only order prices and confirms against a job that has not begun.

    PRD §3.8: "every `YEAST` line's propagation job must be in `READY`, otherwise
    `ERR_YEAST_NOT_READY`; and the order's own `credit_status` must be `APPROVED`,
    otherwise `ERR_ORDER_CREDIT_NOT_APPROVED`. The malt and yeast gates are checked
    before the credit gate."

    PRD §3.8: "`chargeable_lbs` is the sum of `quantity` over lines whose `uom` is
    `LB`"

    PRD §3.8: "Eighth, `freight_cents` is the greater of the applied tier's freight
    minimum — 25,000 cents for `TIER_1`, 15,000 for `TIER_2`, 0 for `TIER_3` — and
    that rated freight."

    Design: Corner/errors/pick_is_blocked_until_the_yeast_job_reaches_ready
    """
    pin_clock()
    brewer = create_brewer(name="Not Ready Brewing", credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain(list_price_cents_per_l=1200.00)
    recipe = create_recipe(brewer["id"], product["id"], strain["id"])
    job = create_job(brewer["id"], recipe["id"], strain["id"],
                    pitch_date="2026-08-20T00:00:00Z")
    assert job["status"] == "REQUESTED", (
        f"the bench has not been started, got {job['status']}")

    order = create_order(brewer["id"])
    line = add_yeast_line(order["id"], brewer["id"], job["id"], 60.0)
    assert line["extended_cents"] == 72000, (
        f"60.0 L at 1200.00 cents per litre is 72000, got {line['extended_cents']}")
    assert line["cold_chain_required"] is True, (
        "a strain's cold_storage_required defaults to true, so slurry travels cold")
    assert line["pallet_break"] is False, (
        "a yeast line has no applicable pallet quantity, so it cannot break one")

    confirmed = confirm_order(order["id"], brewer["id"])
    assert confirmed["chargeable_lbs"] == 0, (
        "the only line is measured in litres, got "
        f"{confirmed['chargeable_lbs']}")
    assert confirmed["freight_cents"] == 43000, (
        "the 25000 TIER_1 minimum plus the 18000 reefer surcharge is 43000, got "
        f"{confirmed['freight_cents']}")
    assert confirmed["small_order_surcharge_cents"] == 7500, (
        "zero chargeable pounds is below the 2000 lb order minimum, got "
        f"{confirmed['small_order_surcharge_cents']}")
    assert confirmed["total_cents"] == 122500, (
        f"72000 + 43000 + 7500 is 122500, got {confirmed['total_cents']}")
    assert approve_credit(order["id"])["credit_status"] == "APPROVED", (
        "the confirm and the credit decision never consult job readiness")

    too_early = api.pick_order(order["id"], WH_HEADERS)
    validate_error(too_early, "ERR_YEAST_NOT_READY", expected_status=409)

    running = validate_success(api.start_propagation(job["id"], WH_HEADERS))
    assert running["status"] == "PROPAGATING", (
        f"the bench is now running, got {running['status']}")
    still_too_early = api.pick_order(order["id"], WH_HEADERS)
    validate_error(still_too_early, "ERR_YEAST_NOT_READY", expected_status=409)

    assert get_order(order["id"])["fulfillment_status"] == "CONFIRMED", (
        "two refused picks left the order where it was")

    ready = complete_propagation(job["id"], outcome="READY")
    assert ready["status"] == "READY", (
        f"the slurry is on hand, got {ready['status']}")
    picked = validate_success(api.pick_order(order["id"], WH_HEADERS))
    assert picked["fulfillment_status"] == "PICKED", (
        f"only READY satisfies the gate, got {picked['fulfillment_status']}")
