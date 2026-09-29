"""The permission matrix: five desks, their own verbs, and the reads they share."""
from test_helpers import (
    AM_HEADERS,
    ANALYST_HEADERS,
    CM_HEADERS,
    PA_HEADERS,
    RELEASER_HEADERS,
    WH_HEADERS,
    add_malt_line,
    analyse_lot,
    confirm_order,
    create_brewer,
    create_contract,
    create_lot,
    create_malt_product,
    create_order,
    create_program,
    create_recipe,
    create_strain,
    create_variety,
    get_brewer,
    get_order,
    make_brewer_headers,
    pin_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_each_of_the_five_desks_reaches_the_verb_it_alone_owns(api):
    """One happy call per desk, so the matrix cannot be collapsed onto a super-role.

    PRD §2.1: "A `Brewer` is a brewery customer: it draws on its own crop-year
    commitments, builds and confirms its own orders, responds to substitution offers,
    asks for carry-forward, and requests yeast propagation."

    PRD §2.1: "A `CreditManager` is the credit desk: it onboards breweries, sets
    limits and payment terms, posts cash receipts, decides each order's credit
    standing and releases credit-held reefer loads — but it cannot write contracts,
    declare defaults or move fulfilment."

    PRD §2.1: "A `WarehouseOperator` runs the floor and the cold chain: receiving and
    analysing malt lots, releasing them, propagating yeast, picking, shipping and
    delivering orders, staging reefer loads and logging temperature readings — but it
    cannot approve credit or write contracts."

    Design: Corner/rbac/every_desk_can_run_its_own_exclusive_operation
    """
    clock = pin_clock()
    assert clock["current_utc"].startswith("2026-08-01T00:00:00"), (
        f"only the admin drives the clock, got {clock['current_utc']}")

    brewer = create_brewer(name="Five Desks Brewing", credit_limit_cents=5000000,
                          cold_chain_certified=False, legacy_trailing_lbs=0)
    variety = create_variety()
    program = create_program(crop_year=2026)
    product = create_malt_product()

    lot = create_lot(product["id"], quantity_lbs=20000)
    assert lot["status"] == "RECEIVED", (
        f"the floor receives malt, got {lot['status']}")

    contract = create_contract(brewer["id"], variety["id"], program["id"],
                              contracted_lbs=5000, price_per_lb_cents=250.00)
    assert contract["status"] == "ACTIVE", (
        f"the hop desk writes contracts, got {contract['status']}")
    assert contract["remaining_lbs"] == 5000, (
        f"the whole commitment is undrawn, got {contract['remaining_lbs']}")

    order = create_order(brewer["id"])
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    confirmed = confirm_order(order["id"], brewer["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        f"the brewery confirms its own order, got {confirmed['fulfillment_status']}")
    assert confirmed["total_cents"] == 105500, (
        "68500 subtotal, the 25000 freight minimum with no reefer surcharge, 4500 "
        f"pallet break and 7500 small-order surcharge is 105500, got "
        f"{confirmed['total_cents']}")

    before = get_brewer(brewer["id"])
    repriced = validate_success(api.update_credit_profile(
        brewer["id"],
        {"expected_brewer_version": before["version"], "credit_terms_days": 45},
        CM_HEADERS))
    assert repriced["credit_terms_days"] == 45, (
        f"the credit desk sets payment terms, got {repriced['credit_terms_days']}")
    assert repriced["version"] == before["version"] + 1, (
        f"the reprice is one write, got version {repriced['version']}")


def test_no_desk_including_the_admin_reaches_another_desks_verb(api):
    """Six denials across six pairs of desks, the platform admin among them.

    PRD §2.1: "A `PlatformAdmin` seeds reference data and drives the logical clock,
    and deliberately holds **no** business decision rights: it cannot confirm an
    order, approve credit, report a harvest, declare a default, analyse or release a
    lot, or move fulfilment."

    PRD §2.8: "**Authentication and authorisation** (priorities 1–3): header presence,
    then role validity, then endpoint role permission."

    Design: Corner/rbac/no_desk_can_reach_another_desks_exclusive_operation
    """
    pin_clock()
    brewer = create_brewer(name="Wrong Desk Brewing", credit_limit_cents=5000000,
                          cold_chain_certified=False, legacy_trailing_lbs=0)
    variety = create_variety()
    program = create_program(crop_year=2026)
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                              contracted_lbs=5000, price_per_lb_cents=250.00)
    product = create_malt_product()
    lot = create_lot(product["id"], quantity_lbs=20000)
    order = create_order(brewer["id"])
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)

    brewer_headers = make_brewer_headers(brewer["id"])
    version_before = get_brewer(brewer["id"])["version"]

    brewer_opens_a_program = api.create_crop_year_program(
        {"crop_year": 2027, "contract_open_date": "2027-01-15T00:00:00Z",
         "harvest_report_due_date": "2027-10-01T00:00:00Z"}, brewer_headers)
    validate_error(brewer_opens_a_program, "ERR_ROLE_NOT_PERMITTED",
                   expected_status=403)

    hop_desk_reprices_credit = api.update_credit_profile(
        brewer["id"],
        {"expected_brewer_version": version_before, "credit_limit_cents": 1},
        AM_HEADERS)
    validate_error(hop_desk_reprices_credit, "ERR_ROLE_NOT_PERMITTED",
                   expected_status=403)

    credit_desk_writes_a_contract = api.create_hop_contract(
        {"brewer_id": brewer["id"], "variety_id": variety["id"],
         "crop_year_program_id": program["id"],
         "contract_type": "FIXED_CROP_YEAR", "contracted_lbs": 1000,
         "price_per_lb_cents": 250.00,
         "delivery_window_start": "2027-01-01T00:00:00Z",
         "delivery_window_end": "2027-06-30T00:00:00Z"}, CM_HEADERS)
    validate_error(credit_desk_writes_a_contract, "ERR_ROLE_NOT_PERMITTED",
                   expected_status=403)

    floor_confirms_the_order = api.confirm_order(order["id"], WH_HEADERS)
    validate_error(floor_confirms_the_order, "ERR_ROLE_NOT_PERMITTED",
                   expected_status=403)

    admin_declares_a_default = api.declare_default(
        contract["id"], {"default_reason": "admin overreach"}, PA_HEADERS)
    validate_error(admin_declares_a_default, "ERR_ROLE_NOT_PERMITTED",
                   expected_status=403)

    brewer_picks_its_own_order = api.pick_order(order["id"], brewer_headers)
    validate_error(brewer_picks_its_own_order, "ERR_ROLE_NOT_PERMITTED",
                   expected_status=403)

    _, program_meta = validate_paginated(api.list_crop_year_programs(AM_HEADERS))
    assert program_meta["total_count"] == 1, (
        f"the refused program was never opened, got {program_meta['total_count']}")

    contract_after = validate_success(api.get_hop_contract(contract["id"],
                                                          AM_HEADERS))
    assert contract_after["status"] == "ACTIVE", (
        f"the refused default moved nothing, got {contract_after['status']}")
    assert contract_after["defaulted_lbs"] == 0, (
        f"no poundage was defaulted, got {contract_after['defaulted_lbs']}")

    brewer_after = get_brewer(brewer["id"])
    assert brewer_after["credit_limit_cents"] == 5000000, (
        f"the refused reprice wrote nothing, got "
        f"{brewer_after['credit_limit_cents']}")
    assert brewer_after["version"] == version_before, (
        "priority 3 fires ahead of the version guard, so there is no write, got "
        f"version {brewer_after['version']}")
    assert get_order(order["id"])["fulfillment_status"] == "DRAFT", (
        "neither the refused confirm nor the refused pick moved the order")


def test_the_credit_desk_may_read_a_lot_but_not_score_it(api):
    """The one declared carve-out from an otherwise universal read surface.

    PRD §3.6: "A brewery, the hop desk, the warehouse or platform operations may score
    a lot's analysis sheet against a recipe's targets by naming a `recipe_id`; the
    credit desk is the one role excluded from this capability."

    PRD §3.6: "`match_score` is 100 multiplied by one minus that weighted penalty,
    rounded half up to two decimal places once at the end. `match_grade` is then
    `EXACT` when the score is at least 95.00, `ACCEPTABLE` when it is at least 80.00,
    `SUBSTITUTE_REQUIRED` when it is at least 60.00, and `REJECTED` otherwise."

    Design: Corner/rbac/shared_reads_are_open_to_all_five_desks_except_the_spec_match_read
    """
    pin_clock()
    brewer = create_brewer(name="Open Book Brewing",
                          brewery_license_no="BR-1055",
                          credit_limit_cents=5000000,
                          cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain()
    recipe = create_recipe(brewer["id"], product["id"], strain["id"],
                         name="House Pale", batch_volume_bbl=30.0,
                         original_gravity_plato=12.50,
                         target_color_lovibond=2.50, target_extract_pct=80.00,
                         target_protein_pct=11.00,
                         requested_pitch_rate_million_cells_per_ml_per_plato=0.75)
    lot = create_lot(product["id"], quantity_lbs=5000, lot_code="LOT-OB-1")
    analysed = analyse_lot(lot["id"], color_lovibond=2.60, extract_pct=79.90,
                          moisture_pct=4.20, protein_pct=11.10,
                          diastatic_power=95.0)
    assert analysed["status"] == "PASSED", (
        "4.20 moisture is under the 5.0 ceiling and 95.0 diastatic power over the "
        f"60.0 floor, got {analysed['status']}")

    for desk, headers in (("credit desk", CM_HEADERS),
                          ("platform admin", PA_HEADERS)):
        read = validate_success(api.get_malt_lot(lot["id"], headers))
        assert read["lot_code"] == "LOT-OB-1", (
            f"the plain lot read is open to the {desk}, got {read['lot_code']}")

    params = {"recipe_id": recipe["id"]}
    brewer_score = validate_success(api.spec_match(
        lot["id"], make_brewer_headers(brewer["id"]), params=params))
    assert float(brewer_score["match_score"]) == 90.71, (
        "0.0667 colour, 0.1000 extract and 0.1250 protein deviations weight to a "
        f"0.09293 penalty, so the score is 90.71, got {brewer_score['match_score']}")
    assert brewer_score["match_grade"] == "ACCEPTABLE", (
        "90.71 is at or above 80.00 and below 95.00, got "
        f"{brewer_score['match_grade']}")

    for desk, headers in (("hop desk", AM_HEADERS), ("warehouse", WH_HEADERS),
                          ("platform admin", PA_HEADERS)):
        scored = validate_success(api.spec_match(lot["id"], headers,
                                                params=params))
        assert float(scored["match_score"]) == 90.71, (
            f"the {desk} sees the same score, got {scored['match_score']}")

    refused = api.spec_match(lot["id"], CM_HEADERS, params=params)
    validate_error(refused, "ERR_ROLE_NOT_PERMITTED", expected_status=403)


def test_the_analyst_of_a_lot_may_not_be_the_one_who_releases_it(api):
    """Two identical roles, two different user ids, two different outcomes.

    PRD §2.9: "A malt lot may not be released by the user recorded in its
    `analyzed_by_user_id`, and a defaulted hop contract's poundage may not be resold
    by the user recorded in its `defaulted_by_user_id`. Either violation is refused
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), evaluated at priority 20"

    PRD §3.6: "A passed lot is released for picking by a `WarehouseOperator` with an
    optional `release_note`, moving `PASSED → RELEASED`, which is also terminal, and
    recording `released_by_user_id` as the releasing `X-User-ID`."

    Design: Corner/rbac/the_same_user_cannot_analyse_and_release_one_malt_lot
    """
    pin_clock()
    product = create_malt_product()
    lot = create_lot(product["id"], quantity_lbs=5000)
    analysed = analyse_lot(lot["id"], headers=ANALYST_HEADERS)
    assert analysed["status"] == "PASSED", (
        f"the sheet clears both specifications, got {analysed['status']}")
    assert analysed["analyzed_by_user_id"] == "qa-analyst-1", (
        f"the analyst is recorded, got {analysed['analyzed_by_user_id']}")
    version_after_analysis = analysed["version"]

    self_release = api.release_malt_lot(
        lot["id"], {"release_note": "signing off on my own sheet"},
        ANALYST_HEADERS)
    validate_error(self_release, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    untouched = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert untouched["status"] == "PASSED", (
        f"the refused release moved nothing, got {untouched['status']}")
    assert untouched["released_by_user_id"] is None, (
        f"no releaser was recorded, got {untouched['released_by_user_id']}")
    assert untouched["version"] == version_after_analysis, (
        f"a refusal is not a write, expected version {version_after_analysis}, got "
        f"{untouched['version']}")

    released = validate_success(api.release_malt_lot(
        lot["id"], {"release_note": "second pair of eyes"}, RELEASER_HEADERS))
    assert released["status"] == "RELEASED", (
        f"a different warehouse user may release it, got {released['status']}")
    assert released["released_by_user_id"] == "qa-analyst-2", (
        f"the releasing identity is recorded, got "
        f"{released['released_by_user_id']}")
    assert released["version"] == version_after_analysis + 1, (
        f"the release is one write, got version {released['version']}")
