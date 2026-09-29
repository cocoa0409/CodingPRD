"""Gates, boundaries and the precedence order in which they are allowed to fire."""
import pytest

from test_helpers import (
    AM_HEADERS,
    CM_HEADERS,
    NON_EXISTENT_UUID,
    WH_HEADERS,
    add_contract_hop_line,
    add_malt_line,
    add_spot_hop_line,
    api_client,
    approve_credit,
    cancel_order,
    confirm_order,
    create_brewer,
    create_contract,
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
    get_zone,
    make_brewer_headers,
    order_version,
    pick_order,
    pin_clock,
    set_credit_limit,
    validate_error,
    validate_paginated,
    validate_success,
)

CONFORMING_SHEET = {
    "color_lovibond": 2.60,
    "extract_pct": 79.90,
    "moisture_pct": 4.20,
    "protein_pct": 11.10,
    "diastatic_power": 95.00,
}


def test_a_line_exactly_at_the_products_minimum_is_admitted(api):
    """54 lbs of a 55 lb-minimum malt is refused; exactly 55 rounds 3767.50 to 3768.

    PRD §3.8: "the line's `quantity` must be at least the item's own minimum — the
    variety's `min_order_lbs` for `HOP`, the malt product's `min_order_lbs` for
    `MALT`, the strain's `min_batch_l` for `YEAST` — with exactly the minimum
    accepted and anything below it refused with
    `ERR_BELOW_MINIMUM_ORDER_QUANTITY`."

    Design: Corner/validations/minimum_order_quantity_admits_a_line_exactly_at_the_minimum
    """
    pin_clock()
    brewer = create_brewer(name="Minimum Order Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    assert product["min_order_lbs"] == 55, (
        f"the SKU carries a 55 lb floor, got {product['min_order_lbs']}")
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-MQ-1", **CONFORMING_SHEET)
    order = create_order(brewer["id"],
                        requested_ship_date="2026-09-20T00:00:00Z",
                        purchase_order_ref="PO-MQ")
    brewer_headers = make_brewer_headers(brewer["id"])

    refused = api.add_order_line(order["id"],
                                {"item_type": "MALT", "quantity": 54,
                                 "uom": "LB", "malt_lot_id": lot["id"]},
                                brewer_headers)
    validate_error(refused, "ERR_BELOW_MINIMUM_ORDER_QUANTITY",
                   expected_status=422)
    empty = get_order(order["id"], brewer_headers)
    assert empty["line_count"] == 0, (
        f"the refused line stored no row, got {empty['line_count']}")
    assert empty["subtotal_cents"] == 0, (
        f"and contributed no money, got {empty['subtotal_cents']}")

    line = add_malt_line(order["id"], brewer["id"], lot["id"], 55)
    assert line["extended_cents"] == 3768, (
        "55 lbs at 68.50 cents is 3767.50, which rounds half up to 3768, got "
        f"{line['extended_cents']}")
    assert line["pallet_break"] is True, (
        "55 is not an exact multiple of the 2200 lb pallet, got "
        f"{line['pallet_break']}")
    assert line["status"] == "OPEN", (
        f"the accepted line is open, got {line['status']}")

    priced = get_order(order["id"], brewer_headers)
    assert priced["line_count"] == 1, (
        f"only the accepted line counts, got {priced['line_count']}")
    assert priced["chargeable_lbs"] == 55, (
        f"the poundage is the survivor's own, got {priced['chargeable_lbs']}")
    assert priced["subtotal_cents"] == 3768, (
        "the roll-up sums the already-rounded line, got "
        f"{priced['subtotal_cents']}")


@pytest.fixture
def two_brewers_and_a_contract_owned_by_the_second():
    """Brewer A with an empty order, and a 5000 lb Citra contract owned by brewer B."""
    pin_clock()
    brewer_a = create_brewer(name="Ordering Brewing", credit_limit_cents=5000000,
                             cold_chain_certified=True, legacy_trailing_lbs=0)
    brewer_b = create_brewer(name="Contract Holder Brewing",
                             credit_limit_cents=5000000,
                             cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    contract = create_contract(brewer_b["id"], variety["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00,
                               contract_type="FIXED_CROP_YEAR",
                               delivery_window_start="2026-09-01T00:00:00Z",
                               delivery_window_end="2026-12-31T00:00:00Z")
    desk_order = validate_success(api_client.create_sales_order(
        {"brewer_id": brewer_a["id"],
         "requested_ship_date": "2026-10-01T00:00:00Z",
         "purchase_order_ref": "PO-MM-A"}, AM_HEADERS), expected_status=201)
    return {"brewer_a": brewer_a, "brewer_b": brewer_b, "program": program,
            "variety": variety, "contract": contract, "desk_order": desk_order}


def test_the_desk_cannot_draw_one_brewerys_order_on_anothers_contract(
        api, two_brewers_and_a_contract_owned_by_the_second):
    """The hop desk may touch both breweries, yet the cross-owned line is refused.

    PRD §3.8: "Before that check, the referenced contract must belong to the same
    brewery as the owning order: a line pointing at another brewery's contract is
    refused with `ERR_CONTRACT_BREWER_MISMATCH`, which outranks the reference-shape
    check."

    Design: Corner/validations/a_line_cannot_draw_on_another_brewers_contract
    """
    world = two_brewers_and_a_contract_owned_by_the_second
    payload = {"item_type": "HOP", "quantity": 1000, "uom": "LB",
               "allocation_source": "CONTRACT",
               "hop_variety_id": world["variety"]["id"],
               "hop_contract_id": world["contract"]["id"]}
    refused = api.add_order_line(world["desk_order"]["id"], payload, AM_HEADERS)
    validate_error(refused, "ERR_CONTRACT_BREWER_MISMATCH", expected_status=422)

    order = validate_success(api.get_sales_order(world["desk_order"]["id"],
                                                 AM_HEADERS))
    assert order["line_count"] == 0, (
        f"the refusal stored no line, got {order['line_count']}")
    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     AM_HEADERS))
    assert contract["committed_lbs"] == 0, (
        f"and drew no poundage, got {contract['committed_lbs']}")

    owners_order = create_order(world["brewer_b"]["id"],
                               requested_ship_date="2026-10-01T00:00:00Z",
                               purchase_order_ref="PO-MM-B")
    accepted = add_contract_hop_line(owners_order["id"], world["brewer_b"]["id"],
                                     world["variety"]["id"],
                                     world["contract"]["id"], 1000)
    assert accepted["status"] == "OPEN", (
        "the identical line on the contract's own brewery is accepted, so the "
        f"refusal was about ownership, got {accepted['status']}")
    assert accepted["unit_price_cents"] == pytest.approx(250.00, abs=0.005), (
        f"and prices off the contract, got {accepted['unit_price_cents']}")


def test_the_brewer_scope_check_outranks_the_ownership_coherence_check(
        api, two_brewers_and_a_contract_owned_by_the_second):
    """Brewer A naming brewer B's contract is a 403, not the 422 the desk received.

    PRD §2.1: "a `Brewer` actor may only address contracts, orders, order lines,
    recipes, propagation jobs, substitution offers and payments belonging to the
    brewery whose `id` equals `X-User-ID`; reaching for another brewery's resource
    is refused with `ERR_BREWER_SCOPE_VIOLATION` (HTTP 403)."

    PRD §2.8: "**Existence and ownership scope** (priorities 5–7): path identifiers
    resolved left to right, then the `Brewer` ownership scope, then identifiers
    supplied in the body or query string."

    Design: Corner/validations/a_line_cannot_draw_on_another_brewers_contract
    """
    world = two_brewers_and_a_contract_owned_by_the_second
    own_order = create_order(world["brewer_a"]["id"],
                            requested_ship_date="2026-10-01T00:00:00Z",
                            purchase_order_ref="PO-MM-SCOPE")
    payload = {"item_type": "HOP", "quantity": 1000, "uom": "LB",
               "allocation_source": "CONTRACT",
               "hop_variety_id": world["variety"]["id"],
               "hop_contract_id": world["contract"]["id"]}
    refused = api.add_order_line(own_order["id"], payload,
                                make_brewer_headers(world["brewer_a"]["id"]))
    validate_error(refused, "ERR_BREWER_SCOPE_VIOLATION", expected_status=403)

    order = get_order(own_order["id"], make_brewer_headers(world["brewer_a"]["id"]))
    assert order["line_count"] == 0, (
        f"nothing was stored, got {order['line_count']}")
    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     AM_HEADERS))
    assert contract["committed_lbs"] == 0, (
        f"nor drawn, got {contract['committed_lbs']}")


def test_every_ill_formed_reference_set_is_refused_for_the_same_reason(api):
    """An extra FK, a missing contract and a wrong uom all report the shape error.

    PRD §3.8: "Exactly the reference set matching `item_type` must be populated,
    and the `uom` must agree with it: a `HOP` line requires a `hop_variety_id`
    plus, when its `allocation_source` is `CONTRACT`, a `hop_contract_id`, and must
    be in `LB`; a `MALT` line requires a `malt_lot_id` and must be in `LB`; a
    `YEAST` line requires a `yeast_propagation_job_id` and must be in `L`."

    PRD §3.8: "A `HOP` line naming a `malt_lot_id`, or a `YEAST` line quoted in
    `LB`, is refused with `ERR_ITEM_REFERENCE_MISMATCH` — the `uom` is never
    silently corrected."

    Design: Corner/validations/line_reference_must_match_the_declared_item_type
    """
    pin_clock()
    brewer = create_brewer(name="Reference Shape Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-RM-1", **CONFORMING_SHEET)
    order = create_order(brewer["id"],
                        requested_ship_date="2026-09-20T00:00:00Z",
                        purchase_order_ref="PO-RM")
    brewer_headers = make_brewer_headers(brewer["id"])

    extra_fk = api.add_order_line(order["id"],
                                 {"item_type": "HOP", "quantity": 880,
                                  "uom": "LB", "allocation_source": "SPOT",
                                  "hop_variety_id": variety["id"],
                                  "malt_lot_id": lot["id"]}, brewer_headers)
    validate_error(extra_fk, "ERR_ITEM_REFERENCE_MISMATCH", expected_status=422)

    no_contract = api.add_order_line(order["id"],
                                    {"item_type": "HOP", "quantity": 880,
                                     "uom": "LB",
                                     "allocation_source": "CONTRACT",
                                     "hop_variety_id": variety["id"]},
                                    brewer_headers)
    validate_error(no_contract, "ERR_ITEM_REFERENCE_MISMATCH",
                   expected_status=422)

    wrong_uom = api.add_order_line(order["id"],
                                  {"item_type": "MALT", "quantity": 1000,
                                   "uom": "L", "malt_lot_id": lot["id"]},
                                  brewer_headers)
    validate_error(wrong_uom, "ERR_ITEM_REFERENCE_MISMATCH", expected_status=422)

    good = add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    assert good["unit_price_cents"] == pytest.approx(68.50, abs=0.005), (
        f"the malt line prices off the SKU, got {good['unit_price_cents']}")
    assert good["extended_cents"] == 68500, (
        f"1000 lbs at 68.50 is 68500, got {good['extended_cents']}")

    priced = get_order(order["id"], brewer_headers)
    assert priced["line_count"] == 1, (
        f"only the well-formed line was stored, got {priced['line_count']}")
    assert priced["subtotal_cents"] == 68500, (
        "none of the three refusals contributed money, got "
        f"{priced['subtotal_cents']}")
    assert priced["requires_cold_chain"] is False, (
        "the refused hop lines never made the order a reefer order, got "
        f"{priced['requires_cold_chain']}")


def test_a_program_that_has_reported_or_settled_admits_no_new_contracts(api):
    """Contracting stops at HARVEST_REPORTED, not merely at SETTLED.

    PRD §3.2: "A contract may only be written against a program whose `status` is
    `OPEN`; attempting it against a program that has already reported harvest or
    settled is refused with `ERR_PROGRAM_NOT_OPEN`."

    Design: Corner/validations/contracts_cannot_be_written_once_the_program_leaves_open
    """
    pin_clock()
    brewer = create_brewer(name="Late Contract Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    payload = {"brewer_id": brewer["id"], "variety_id": variety["id"],
               "crop_year_program_id": program["id"],
               "contract_type": "FIXED_CROP_YEAR", "contracted_lbs": 5000,
               "price_per_lb_cents": 250.00,
               "delivery_window_start": "2026-09-01T00:00:00Z",
               "delivery_window_end": "2026-12-31T00:00:00Z"}

    reported = validate_success(api.report_harvest(
        program["id"], {"harvest_yield_pct": 100.00,
                        "reported_note": "an empty book"}, AM_HEADERS))
    assert reported["status"] == "HARVEST_REPORTED", (
        f"the program has reported, got {reported['status']}")
    assert reported["allocatable_pool_lbs"] == 0, (
        "a program with no contracts allocates nothing, got "
        f"{reported['allocatable_pool_lbs']}")
    assert reported["total_contracted_lbs"] == 0, (
        f"its contract base is empty, got {reported['total_contracted_lbs']}")

    after_report = api.create_hop_contract(payload, AM_HEADERS)
    validate_error(after_report, "ERR_PROGRAM_NOT_OPEN", expected_status=409)

    settled = validate_success(api.settle_program(
        program["id"], {"settlement_note": "nothing outstanding"}, AM_HEADERS))
    assert settled["status"] == "SETTLED", (
        "settlement is unobstructed because no contract is CARRY_FORWARD_PENDING, "
        f"got {settled['status']}")


    after_settle = api.create_hop_contract(payload, AM_HEADERS)
    validate_error(after_settle, "ERR_PROGRAM_NOT_OPEN", expected_status=409)

    _, meta = validate_paginated(api.list_hop_contracts(
        AM_HEADERS, params={"crop_year_program_id": program["id"]}))
    assert meta["total_count"] == 0, (
        f"neither refusal wrote a contract row, got {meta['total_count']}")


@pytest.fixture
def contract_with_an_autumn_delivery_window():
    """A 5000 lb Citra contract deliverable from 2026-09-01 to 2026-12-31."""
    pin_clock()
    brewer = create_brewer(name="Delivery Window Brewing",
                           credit_limit_cents=9000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00,
                               contract_type="FIXED_CROP_YEAR",
                               delivery_window_start="2026-09-01T00:00:00Z",
                               delivery_window_end="2026-12-31T00:00:00Z")
    return {"brewer": brewer, "program": program, "variety": variety,
            "contract": contract}


def test_a_ship_date_one_day_before_the_window_is_refused_at_confirm(
        api, contract_with_an_autumn_delivery_window):
    """The line is accepted happily and the confirm is what discovers 2026-08-31.

    PRD §3.8: "For every `CONTRACT`-sourced hop line the order's
    `requested_ship_date` must fall inside the closed inclusive interval running
    from the contract's `delivery_window_start` to its `delivery_window_end`,
    otherwise `ERR_SHIP_DATE_OUTSIDE_DELIVERY_WINDOW`."

    Design: Corner/validations/requested_ship_date_must_sit_inside_the_closed_delivery_window
    """
    world = contract_with_an_autumn_delivery_window
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    order = create_order(world["brewer"]["id"],
                        requested_ship_date="2026-08-31T00:00:00Z",
                        purchase_order_ref="PO-DW-EARLY")
    line = add_contract_hop_line(order["id"], world["brewer"]["id"],
                                 world["variety"]["id"],
                                 world["contract"]["id"], 1000)
    assert line["status"] == "OPEN", (
        f"line creation never consults the window, got {line['status']}")

    refused = api.confirm_order(order["id"], brewer_headers)
    validate_error(refused, "ERR_SHIP_DATE_OUTSIDE_DELIVERY_WINDOW",
                   expected_status=422)

    still = get_order(order["id"], brewer_headers)
    assert still["fulfillment_status"] == "DRAFT", (
        f"the order does not advance, got {still['fulfillment_status']}")
    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     AM_HEADERS))
    assert contract["committed_lbs"] == 0, (
        f"and commits nothing, got {contract['committed_lbs']}")
    survivor = validate_success(api.get_order_line(line["id"], brewer_headers))
    assert survivor["status"] == "OPEN", (
        "the window check refuses the confirm rather than trimming the line, got "
        f"{survivor['status']}")


def test_a_ship_date_exactly_on_the_window_end_confirms(
        api, contract_with_an_autumn_delivery_window):
    """2026-12-31 is the closed upper bound, so the order prices at 305000.

    PRD §3.2: "the inclusive delivery window bounded by `delivery_window_start` and
    `delivery_window_end`, where the end instant must be later than the start"

    Design: Corner/validations/requested_ship_date_must_sit_inside_the_closed_delivery_window
    """
    world = contract_with_an_autumn_delivery_window
    order = create_order(world["brewer"]["id"],
                        requested_ship_date="2026-12-31T00:00:00Z",
                        purchase_order_ref="PO-DW-EDGE")
    add_contract_hop_line(order["id"], world["brewer"]["id"],
                          world["variety"]["id"], world["contract"]["id"], 1000)

    confirmed = confirm_order(order["id"], world["brewer"]["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        "a ship date landing exactly on the window end is inside it, got "
        f"{confirmed['fulfillment_status']}")
    assert confirmed["total_cents"] == 305000, (
        "250000 plus 43000 reefer freight, 4500 pallet break and 7500 surcharge = "
        f"305000, got {confirmed['total_cents']}")
    assert confirmed["volume_discount_cents"] == 0, (
        "250000 is under the first discount tier, got "
        f"{confirmed['volume_discount_cents']}")

    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     AM_HEADERS))
    assert contract["committed_lbs"] == 1000, (
        f"the confirm draws 1000 lbs, got {contract['committed_lbs']}")
    assert contract["remaining_lbs"] == 4000, (
        f"leaving 4000 undrawn, got {contract['remaining_lbs']}")


@pytest.fixture
def recipe_on_a_seven_day_strain():
    """A brewery, a WLP001 strain with a seven-day lead time and a recipe on it."""
    pin_clock()
    brewer = create_brewer(name="Lead Time Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain()
    recipe = create_recipe(brewer["id"], product["id"], strain["id"],
                           name="House Ale", batch_volume_bbl=30.00,
                           original_gravity_plato=12.50,
                           target_color_lovibond=2.50, target_extract_pct=80.00,
                           target_protein_pct=11.00,
                           requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
                           adjunct_pct=0.0)
    assert strain["propagation_lead_time_days"] == 7, (
        "the strain needs seven days, got "
        f"{strain['propagation_lead_time_days']}")
    return {"brewer": brewer, "product": product, "strain": strain,
            "recipe": recipe}


def test_a_pitch_date_six_days_out_misses_a_seven_day_lead_time(
        api, recipe_on_a_seven_day_strain):
    """2026-08-07 is six whole days from the clock and is refused outright.

    PRD §3.7: "The `pitch_date` must fall at least `propagation_lead_time_days`
    whole days after the current logical clock, with exactly the lead time accepted
    and anything shorter refused with `ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME`."

    Design: Corner/validations/propagation_accepts_a_pitch_date_exactly_at_the_lead_time
    """
    world = recipe_on_a_seven_day_strain
    refused = api.create_propagation_job(
        {"brewer_id": world["brewer"]["id"], "recipe_id": world["recipe"]["id"],
         "yeast_strain_id": world["strain"]["id"],
         "pitch_date": "2026-08-07T00:00:00Z"},
        make_brewer_headers(world["brewer"]["id"]))
    validate_error(refused, "ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME",
                   expected_status=422)

    _, meta = validate_paginated(api.list_propagation_jobs(
        WH_HEADERS, params={"brewer_id": world["brewer"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the refusal created no job, got {meta['total_count']}")


def test_a_pitch_date_exactly_at_the_lead_time_is_measured_from_the_live_clock(
        api, recipe_on_a_seven_day_strain):
    """2026-08-08 is accepted at the 08-01 clock and refused once it reads 08-02.

    PRD §3.7: "An accepted request lands in `status` `REQUESTED` with `ready_at`,
    `failure_reason` and `replaces_job_id` all null, and with the advisory figures
    below computed immediately."

    PRD §2.5: "Every delivery window test, propagation lead-time test, viability
    decay, trailing-volume window, staging interval and "current instant" stamp
    reads the logical clock."

    Design: Corner/validations/propagation_accepts_a_pitch_date_exactly_at_the_lead_time
    """
    world = recipe_on_a_seven_day_strain
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    payload = {"brewer_id": world["brewer"]["id"],
               "recipe_id": world["recipe"]["id"],
               "yeast_strain_id": world["strain"]["id"],
               "pitch_date": "2026-08-08T00:00:00Z"}
    job = validate_success(api.create_propagation_job(payload, brewer_headers),
                           expected_status=201)
    assert job["status"] == "REQUESTED", (
        f"exactly seven days out is accepted, got {job['status']}")
    assert job["ready_at"] is None, (
        "readiness is dated when the job starts, not when it is requested, got "
        f"{job['ready_at']}")
    assert job["failure_reason"] is None, (
        f"a fresh request has no failure, got {job['failure_reason']}")
    assert job["replaces_job_id"] is None, (
        f"nor a predecessor, got {job['replaces_job_id']}")

    pin_clock("2026-08-02T00:00:00Z")
    now_short = api.create_propagation_job(payload, brewer_headers)
    validate_error(now_short, "ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME",
                   expected_status=422)


def test_a_zero_length_staging_window_is_refused_like_an_inverted_one(api):
    """06:00 to 06:00 cannot park a pallet for free; only a forward window stages.

    PRD §3.9: "`stage_until` must be strictly after `stage_from`; a zero-length or
    inverted window is refused with `ERR_INVALID_STAGING_WINDOW`."

    Design: Corner/validations/staging_window_must_be_strictly_forward
    """
    pin_clock()
    brewer = create_brewer(name="Staging Window Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    order = create_order(brewer["id"],
                        requested_ship_date="2026-09-12T00:00:00Z",
                        purchase_order_ref="PO-SW")
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"], note="within limit")
    pick_order(order["id"])

    def attempt(stage_from, stage_until):
        return api.stage_shipment(
            {"sales_order_id": order["id"], "cold_storage_zone_id": zone["id"],
             "expected_sales_order_version": order_version(order["id"]),
             "pallet_count": 1, "stage_from": stage_from,
             "stage_until": stage_until, "reefer_setpoint_c": 2.00,
             "reefer_tolerance_c": 2.00}, WH_HEADERS)

    zero_length = attempt("2026-08-01T06:00:00Z", "2026-08-01T06:00:00Z")
    validate_error(zero_length, "ERR_INVALID_STAGING_WINDOW",
                   expected_status=422)
    inverted = attempt("2026-08-01T14:00:00Z", "2026-08-01T06:00:00Z")
    validate_error(inverted, "ERR_INVALID_STAGING_WINDOW", expected_status=422)

    staged = validate_success(attempt("2026-08-01T06:00:00Z",
                                      "2026-08-01T14:00:00Z"),
                              expected_status=201)
    assert staged["status"] == "STAGED", (
        f"a strictly forward window is admitted, got {staged['status']}")
    assert staged["excursion_minutes"] == 0, (
        f"a fresh load has accrued nothing, got {staged['excursion_minutes']}")
    assert staged["reading_count"] == 0, (
        f"nor any telemetry, got {staged['reading_count']}")
    assert staged["last_reading_at"] is None, (
        f"nor a high-water mark, got {staged['last_reading_at']}")

    assert get_zone(zone["id"])["occupied_pallets"] == 0, (
        "the clock sits before 06:00 so the window does not cover it, got "
        f"{get_zone(zone['id'])['occupied_pallets']}")
    _, meta = validate_paginated(api.list_shipments(
        WH_HEADERS, params={"sales_order_id": order["id"]}))
    assert meta["total_count"] == 1, (
        f"the accepted load is the only row, got {meta['total_count']}")


def test_only_a_reefer_order_demands_cold_chain_certification(api):
    """The uncertified brewery confirms its malt order and is refused on its hops.

    PRD §3.8: "When the order's `requires_cold_chain` is true the owning brewery's
    `cold_chain_certified` must be true, otherwise `ERR_COLD_CHAIN_NOT_CERTIFIED`."

    PRD §3.8: "`requires_cold_chain` is true when any line in the set has
    `cold_chain_required` true"

    Design: Corner/validations/cold_chain_certification_is_demanded_only_by_reefer_orders
    """
    pin_clock()
    brewer = create_brewer(name="Uncertified Dock Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    variety = create_variety()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-UC-1", **CONFORMING_SHEET)
    brewer_headers = make_brewer_headers(brewer["id"])

    ambient = create_order(brewer["id"],
                          requested_ship_date="2026-09-20T00:00:00Z",
                          purchase_order_ref="PO-UC-AMB")
    add_malt_line(ambient["id"], brewer["id"], lot["id"], 1000)
    reefer = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-UC-REEF")
    hop_line = add_spot_hop_line(reefer["id"], brewer["id"], variety["id"], 880)
    assert hop_line["cold_chain_required"] is True, (
        "the line copies the variety's refrigeration flag, got "
        f"{hop_line['cold_chain_required']}")
    assert get_order(reefer["id"], brewer_headers)["requires_cold_chain"] is True, (
        "so the order needs reefer freight, got "
        f"{get_order(reefer['id'], brewer_headers)['requires_cold_chain']}")

    confirmed = confirm_order(ambient["id"], brewer["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        "an ambient order is unaffected by the certification gate, got "
        f"{confirmed['fulfillment_status']}")
    assert confirmed["total_cents"] == 105500, (
        "68500 plus 25000 freight with no reefer surcharge, 4500 pallet break and "
        f"7500 surcharge = 105500, got {confirmed['total_cents']}")

    refused = api.confirm_order(reefer["id"], brewer_headers)
    validate_error(refused, "ERR_COLD_CHAIN_NOT_CERTIFIED", expected_status=422)
    held = get_order(reefer["id"], brewer_headers)
    assert held["fulfillment_status"] == "DRAFT", (
        f"the hop order stays a draft, got {held['fulfillment_status']}")
    assert validate_success(api.get_hop_variety(variety["id"],
                                               AM_HEADERS))["available_spot_lbs"] == 20000, (
        "the refused confirm reserved nothing from the spot pool")

    posture = get_brewer(brewer["id"])
    assert posture["credit_exposure_cents"] == 105500, (
        "only the confirmed order carries a total, since a DRAFT order's total is "
        f"0, got {posture['credit_exposure_cents']}")

    certified = set_credit_limit(brewer["id"], 5000000, cold_chain_certified=True)
    assert certified["cold_chain_certified"] is True, (
        f"the dock is now certified, got {certified['cold_chain_certified']}")
    now_ok = confirm_order(reefer["id"], brewer["id"])
    assert now_ok["fulfillment_status"] == "CONFIRMED", (
        f"the same confirm now succeeds, got {now_ok['fulfillment_status']}")
    assert now_ok["total_cents"] == 95380, (
        "44880 plus 43000 reefer freight and 7500 surcharge = 95380, got "
        f"{now_ok['total_cents']}")


def test_an_unknown_brewery_is_a_404_while_a_real_foreign_one_is_a_403(api):
    """Existence is decided before tenancy, so the pair of probes reads differently.

    PRD §2.8: "**Existence and ownership scope** (priorities 5–7): path identifiers
    resolved left to right, then the `Brewer` ownership scope, then identifiers
    supplied in the body or query string."

    PRD §2.1: "reaching for another brewery's resource is refused with
    `ERR_BREWER_SCOPE_VIOLATION` (HTTP 403)"

    Design: Corner/validations/unknown_id_is_reported_before_the_brewer_scope_check
    """
    pin_clock()
    prying = create_brewer(name="Prying Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    other = create_brewer(name="Minding Its Own Brewing",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    prying_headers = make_brewer_headers(prying["id"])

    missing = api.get_brewer(NON_EXISTENT_UUID, prying_headers)
    validate_error(missing, "ERR_BREWER_NOT_FOUND", expected_status=404)

    own = validate_success(api.get_brewer(prying["id"], prying_headers))
    assert own["name"] == "Prying Brewing", (
        f"a brewery may always read itself, got {own['name']}")

    desk_view = validate_success(api.get_brewer(other["id"], CM_HEADERS))
    assert desk_view["id"] == other["id"], (
        "the scope rule binds the Brewer role only, so the credit desk reads any "
        f"brewery, got {desk_view['id']}")


def test_a_malformed_duplicate_reports_the_shape_before_the_collision(api):
    """A request that is both ill-formed and duplicate reports only the shape error.

    PRD §2.8: "When one request violates several rules, the response carries the
    error belonging to the **lowest** priority number, and only that error."

    PRD §2.8: "**Request shape** (priority 4): every required body field present,
    every field of the declared type, every enum field carrying a declared member,
    every quantity, poundage, pallet count and money amount non-negative, no
    decimal exceeding its declared scale, and every version field an integer."

    PRD §2.10: "a duplicate `brewery_license_no` on a brewery reports
    `ERR_DUPLICATE_BREWERY_LICENSE`"

    Design: Corner/validations/payload_shape_is_judged_before_the_duplicate_key
    """
    pin_clock()
    incumbent = create_brewer(name="Incumbent Brewing",
                              brewery_license_no="BR-1033",
                              credit_limit_cents=5000000,
                              cold_chain_certified=False, legacy_trailing_lbs=0)

    both_wrong = api.create_brewer({"brewery_license_no": "BR-1033",
                                   "credit_terms_days": 30}, CM_HEADERS)
    validate_error(both_wrong, "ERR_INVALID_REQUEST", expected_status=400)

    duplicate = api.create_brewer({"name": "Impostor Brewing",
                                   "brewery_license_no": "BR-1033",
                                   "credit_terms_days": 30,
                                   "credit_limit_cents": 5000000,
                                   "cold_chain_certified": False,
                                   "legacy_trailing_lbs": 0}, CM_HEADERS)
    validate_error(duplicate, "ERR_DUPLICATE_BREWERY_LICENSE",
                   expected_status=409)

    fresh = validate_success(api.create_brewer(
        {"name": "Impostor Brewing", "brewery_license_no": "BR-1034",
         "credit_terms_days": 30, "credit_limit_cents": 5000000,
         "cold_chain_certified": False, "legacy_trailing_lbs": 0}, CM_HEADERS),
        expected_status=201)
    assert fresh["id"] != incumbent["id"], (
        f"a fresh licence mints a new brewery, got {fresh['id']}")

    namesake = validate_success(api.create_brewer(
        {"name": "Incumbent Brewing", "brewery_license_no": "BR-1035",
         "credit_terms_days": 30, "credit_limit_cents": 5000000,
         "cold_chain_certified": False, "legacy_trailing_lbs": 0}, CM_HEADERS),
        expected_status=201)
    assert namesake["name"] == incumbent["name"], (
        "two breweries may share a name because only the licence is unique, got "
        f"{namesake['name']} against {incumbent['name']}")
    assert namesake["id"] != incumbent["id"], (
        f"they are nonetheless distinct rows, got {namesake['id']}")


def test_two_affordable_contract_lines_are_refused_collectively(
        api, contract_with_an_autumn_delivery_window):
    """3000 plus 3000 against 5000 remaining pounds is caught at confirm, not at add.

    PRD §3.8: "**All three volume gates are aggregate**, not per line: two
    individually affordable lines on the same contract, lot or variety that jointly
    overdraw it are refused."

    Design: Corner/validations/individually_affordable_lines_jointly_overdraw_the_contract
    """
    world = contract_with_an_autumn_delivery_window
    brewer, variety, contract = world["brewer"], world["variety"], world["contract"]
    brewer_headers = make_brewer_headers(brewer["id"])
    order = create_order(brewer["id"],
                        requested_ship_date="2026-10-01T00:00:00Z",
                        purchase_order_ref="PO-AGG-1")
    line_a = add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                                  contract["id"], 3000)
    line_b = add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                                  contract["id"], 3000)
    assert line_a["status"] == "OPEN" and line_b["status"] == "OPEN", (
        "each line taken alone fits inside 5000 remaining pounds, got "
        f"{line_a['status']} and {line_b['status']}")

    refused = api.confirm_order(order["id"], brewer_headers)
    validate_error(refused, "ERR_CONTRACT_VOLUME_EXHAUSTED", expected_status=422)
    assert get_order(order["id"], brewer_headers)["fulfillment_status"] == "DRAFT", (
        "the refused confirm leaves the order a draft, got "
        f"{get_order(order['id'], brewer_headers)['fulfillment_status']}")
    untouched = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert untouched["committed_lbs"] == 0, (
        f"and commits nothing, got {untouched['committed_lbs']}")

    api.remove_order_line(order["id"], line_b["id"], brewer_headers)
    dropped = validate_success(api.get_order_line(line_b["id"], brewer_headers))
    assert dropped["status"] == "REMOVED", (
        f"the second line is withdrawn, got {dropped['status']}")
    trimmed = get_order(order["id"], brewer_headers)
    assert trimmed["chargeable_lbs"] == 3000, (
        f"only the surviving line is chargeable, got {trimmed['chargeable_lbs']}")

    confirmed = confirm_order(order["id"], brewer["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        f"3000 alone is affordable, got {confirmed['fulfillment_status']}")
    assert confirmed["total_cents"] == 808500, (
        "750000 subtotal plus 36000 rate-based freight, 18000 reefer and 4500 "
        f"pallet break = 808500, got {confirmed['total_cents']}")

    after = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert after["committed_lbs"] == 3000, (
        f"exactly one line's poundage is committed, got {after['committed_lbs']}")
    assert after["remaining_lbs"] == 2000, (
        f"5000 less 3000 leaves 2000, got {after['remaining_lbs']}")
    kept = validate_success(api.get_order_line(line_a["id"], brewer_headers))
    assert kept["unit_price_cents"] == pytest.approx(250.00, abs=0.005), (
        f"the surviving line still carries the contract price, got "
        f"{kept['unit_price_cents']}")


def test_lot_availability_is_aggregated_across_orders_and_within_one(api):
    """A 5000 lb lot with 4000 committed refuses both a 1500 order and a 600+600 one.

    PRD §3.8: "each malt lot must have `available_lbs` at least equal to the
    quantity drawing on it, otherwise `ERR_MALT_LOT_INSUFFICIENT_QUANTITY`"

    Design: Corner/validations/malt_lot_shortage_is_aggregated_across_orders_and_within_one
    """
    pin_clock()
    brewer = create_brewer(name="Single Lot Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                            lot_code="LOT-AGG-1", **CONFORMING_SHEET)
    brewer_headers = make_brewer_headers(brewer["id"])

    order_a = create_order(brewer["id"],
                          requested_ship_date="2026-09-10T00:00:00Z",
                          purchase_order_ref="PO-AGG-A")
    add_malt_line(order_a["id"], brewer["id"], lot["id"], 4000)
    order_b = create_order(brewer["id"],
                          requested_ship_date="2026-09-10T00:00:00Z",
                          purchase_order_ref="PO-AGG-B")
    add_malt_line(order_b["id"], brewer["id"], lot["id"], 1500)
    order_c = create_order(brewer["id"],
                          requested_ship_date="2026-09-10T00:00:00Z",
                          purchase_order_ref="PO-AGG-C")
    add_malt_line(order_c["id"], brewer["id"], lot["id"], 600)
    add_malt_line(order_c["id"], brewer["id"], lot["id"], 600)

    confirmed_a = confirm_order(order_a["id"], brewer["id"])
    assert confirmed_a["total_cents"] == 326500, (
        "274000 subtotal plus 48000 rate-based freight and 4500 pallet break with "
        f"no small-order surcharge = 326500, got {confirmed_a['total_cents']}")
    drawn = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert drawn["committed_lbs"] == 4000, (
        f"order A holds 4000 lbs of the lot, got {drawn['committed_lbs']}")
    assert drawn["available_lbs"] == 1000, (
        f"5000 less 4000 leaves 1000 available, got {drawn['available_lbs']}")

    refused_b = api.confirm_order(order_b["id"], brewer_headers)
    validate_error(refused_b, "ERR_MALT_LOT_INSUFFICIENT_QUANTITY",
                   expected_status=422)
    refused_c = api.confirm_order(order_c["id"], brewer_headers)
    validate_error(refused_c, "ERR_MALT_LOT_INSUFFICIENT_QUANTITY",
                   expected_status=422)

    still = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert still["committed_lbs"] == 4000, (
        "neither refusal moved the commitment, got "
        f"{still['committed_lbs']}")
    assert still["quantity_lbs"] == 5000, (
        f"nor the physical poundage, got {still['quantity_lbs']}")

    cancel_order(order_a["id"], cancel_reason="brew day pushed back")
    freed = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert freed["available_lbs"] == 5000, (
        f"the cancel returns the whole lot, got {freed['available_lbs']}")
    now_ok = confirm_order(order_b["id"], brewer["id"])
    assert now_ok["fulfillment_status"] == "CONFIRMED", (
        f"order B then fits, got {now_ok['fulfillment_status']}")


def test_the_spot_pool_is_drawn_at_confirm_and_not_at_line_creation(api):
    """A 1000 lb pool takes two 880 lb lines but only one confirm.

    PRD §3.8: "each variety must have `available_spot_lbs` at least equal to the
    `SPOT` quantity drawing on it, otherwise `ERR_SPOT_INVENTORY_INSUFFICIENT`"

    Design: Corner/validations/spot_pool_shortage_surfaces_only_at_confirm
    """
    pin_clock()
    brewer = create_brewer(name="Thin Pool Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety(available_spot_lbs=1000)
    brewer_headers = make_brewer_headers(brewer["id"])

    order_a = create_order(brewer["id"],
                          requested_ship_date="2026-09-14T00:00:00Z",
                          purchase_order_ref="PO-POOL-A")
    add_spot_hop_line(order_a["id"], brewer["id"], variety["id"], 880)
    order_b = create_order(brewer["id"],
                          requested_ship_date="2026-09-14T00:00:00Z",
                          purchase_order_ref="PO-POOL-B")
    add_spot_hop_line(order_b["id"], brewer["id"], variety["id"], 880)

    confirmed_a = confirm_order(order_a["id"], brewer["id"])
    assert confirmed_a["total_cents"] == 95380, (
        "44880 subtotal plus 25000 freight minimum, 18000 reefer and the 7500 "
        f"small-order surcharge = 95380, got {confirmed_a['total_cents']}")
    after_a = validate_success(api.get_hop_variety(variety["id"], AM_HEADERS))
    assert after_a["available_spot_lbs"] == 120, (
        f"the confirm drew 880 from the 1000 lb pool, got "
        f"{after_a['available_spot_lbs']}")

    refused_b = api.confirm_order(order_b["id"], brewer_headers)
    validate_error(refused_b, "ERR_SPOT_INVENTORY_INSUFFICIENT",
                   expected_status=422)
    unmoved = validate_success(api.get_hop_variety(variety["id"], AM_HEADERS))
    assert unmoved["available_spot_lbs"] == 120, (
        f"the loser draws nothing, got {unmoved['available_spot_lbs']}")

    cancelled = cancel_order(order_a["id"], cancel_reason="tank not free")
    assert cancelled["fulfillment_status"] == "CANCELLED", (
        f"order A is withdrawn, got {cancelled['fulfillment_status']}")
    restored = validate_success(api.get_hop_variety(variety["id"], AM_HEADERS))
    assert restored["available_spot_lbs"] == 1000, (
        f"the whole pool is returned, got {restored['available_spot_lbs']}")

    confirmed_b = confirm_order(order_b["id"], brewer["id"])
    assert confirmed_b["total_cents"] == 95380, (
        f"order B prices identically, got {confirmed_b['total_cents']}")
    final_pool = validate_success(api.get_hop_variety(variety["id"], AM_HEADERS))
    assert final_pool["available_spot_lbs"] == 120, (
        f"and draws the pool back down to 120, got "
        f"{final_pool['available_spot_lbs']}")
    assert get_brewer(brewer["id"])["credit_exposure_cents"] == 95380, (
        "the cancelled order left no exposure behind, got "
        f"{get_brewer(brewer['id'])['credit_exposure_cents']}")
