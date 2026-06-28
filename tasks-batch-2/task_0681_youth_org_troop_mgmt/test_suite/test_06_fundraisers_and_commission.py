"""Fundraisers: tiered commission, inventory, fill ledgers, order cancel/close, OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_council,
    create_council_and_troop,
    create_member,
    create_live_fundraiser,
    setup_live_fundraiser_with_seller,
    place_order,
    create_fundraiser_payload,
    create_fundraiser_order_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


def test_commission_marginal_tier_straddle_600_units(api):
    """PRD §3.7: "The first 100 units (units one through one hundred) each earn
    fifteen percent of the unit price; units one hundred one through five hundred
    each earn twenty percent; and every unit beyond five hundred earns twenty-five
    percent ... Each tier's unit count is multiplied by the unit price and by its
    rate, the three tier contributions are summed, and that single sum is rounded
    half-up to whole cents exactly once after summing."

    Design: Difficulty/combinatorial_formula/commission_marginal_tier_straddle_three_inputs
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "Tier Council"},
        fundraiser_overrides={"product": "POPCORN", "unit_price_cents": 500,
                              "unit_cost_cents": 200, "total_inventory_units": 2000},
    )
    order = validate_success(
        api.create_fundraiser_order(
            create_fundraiser_order_payload(fr["id"], troop["id"], seller["id"], 600, fr["version"]), LEAD
        ),
        201,
    )
    # t1=100*500*.15=7500 ; t2=400*500*.20=40000 ; t3=100*500*.25=12500 ; sum=60000
    assert order["troop_commission_cents"] == 60000, f"got {order['troop_commission_cents']}"
    assert order["gross_cents"] == 300000, f"got {order['gross_cents']}"


def test_commission_gross_for_600_units(api):
    """PRD §3.7: "records its gross_cents as units multiplied by the fundraiser's
    unit_price_cents at placement."

    Design: Difficulty/combinatorial_formula/commission_marginal_tier_straddle_three_inputs
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "Tier2"},
        fundraiser_overrides={"product": "POPCORN", "unit_price_cents": 500,
                              "unit_cost_cents": 200, "total_inventory_units": 2000},
    )
    order = validate_success(
        api.create_fundraiser_order(
            create_fundraiser_order_payload(fr["id"], troop["id"], seller["id"], 600, fr["version"]), LEAD
        ),
        201,
    )
    assert order["gross_cents"] == 300000


def test_commission_tier1_boundary_exactly_100_units(api):
    """PRD §3.7: "the number of first-tier units is the smaller of the order's units
    and one hundred ... Each tier's unit count is multiplied by the unit price and by
    its rate, the three tier contributions are summed, and that single sum is rounded
    half-up to whole cents exactly once after summing."

    Design: Corner/calculations/commission_tier_boundary_exactly_100_units
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "K1"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 1000},
    )
    order = validate_success(
        api.create_fundraiser_order(
            create_fundraiser_order_payload(fr["id"], troop["id"], seller["id"], 100, fr["version"]), LEAD
        ),
        201,
    )
    assert order["troop_commission_cents"] == 7500, f"got {order['troop_commission_cents']}"
    assert order["gross_cents"] == 50000


def test_inventory_exact_available_units_allowed(api):
    """PRD §3.7: "The order may not oversell inventory: if units exceeds the
    fundraiser's current available_units, the placement is rejected with
    ERR_INSUFFICIENT_INVENTORY."

    Design: Difficulty/boundary_precision_check/inventory_exact_available_units_boundary
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "Inv Council"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 100},
    )
    # Exactly available_units (100) -> allowed.
    order = validate_success(
        api.create_fundraiser_order(
            create_fundraiser_order_payload(fr["id"], troop["id"], seller["id"], 100, fr["version"]), LEAD
        ),
        201,
    )
    assert order["units"] == 100
    assert order["troop_commission_cents"] == 7500  # 100u@500 all tier1 *.15


def test_inventory_over_available_units_rejected(api):
    """PRD §3.7: "The order may not oversell inventory: if units exceeds the
    fundraiser's current available_units, the placement is rejected with
    ERR_INSUFFICIENT_INVENTORY."

    Design: Difficulty/boundary_precision_check/inventory_exact_available_units_boundary
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "Inv2"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 100},
    )
    validate_success(
        api.create_fundraiser_order(
            create_fundraiser_order_payload(fr["id"], troop["id"], seller["id"], 100, fr["version"]), LEAD
        ),
        201,
    )
    # available_units now 0; +1 oversells. Placing the first order bumped the
    # fundraiser's version (PRD §2.6), so re-read its current version for the
    # second placement — otherwise the OCC check (ERR_STALE_VERSION) would fire
    # first per the §3.9 ordering and mask the inventory check.
    fr_now = validate_success(api.get_fundraiser(fr["id"], REG), 200)
    resp = api.create_fundraiser_order(
        create_fundraiser_order_payload(fr["id"], troop["id"], seller["id"], 1, fr_now["version"]), LEAD
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_fill_order_posts_cash_and_liability_ledger(api):
    """PRD §3.7: "a FundLedgerEntry credits the order's gross_cents into COUNCIL_CASH
    and another credits units multiplied by the fundraiser's unit_cost_cents into
    PRODUCT_LIABILITY, both with a source_kind of FUNDRAISER_ORDER."

    Design: Corner/calculations/fill_order_posts_cash_and_liability_ledger
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "K2"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 1000},
    )
    order = place_order(fr["id"], troop["id"], seller["id"], 150, fr["version"])
    get_success_data(api.fill_order(order["id"], LEAD))

    council_after = validate_success(api.get_council(council["id"], REG), 200)
    assert council_after["fund_cash_cents"] == 75000      # 150*500
    assert council_after["fund_liability_cents"] == 30000  # 150*200


def test_order_cancel_conserves_troop_dues(api):
    """PRD §3.7: "Cancelling a placed order moves it to the terminal CANCELLED,
    decreases the fundraiser's allocated_units by that order's units and recomputes
    available_units, reverses the order's troop_commission_cents out of TROOP_DUES
    via a reversal ledger entry, and recomputes the troop's dues_account_cents."

    Design: Difficulty/compensating_invariant/order_cancel_conserves_troop_dues
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "Inv9 Council"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 1000},
    )
    order = place_order(fr["id"], troop["id"], seller["id"], 150, fr["version"])

    cancelled = validate_success(api.cancel_order(order["id"], LEAD), 200)
    assert cancelled["status"] == "CANCELLED"

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    fr_after = validate_success(api.get_fundraiser(fr["id"], REG), 200)
    assert troop_after["dues_account_cents"] == 0, "12500 credited then reversed -> 0"
    assert fr_after["available_units"] == 1000, "1000-150 then +150 back"


def test_order_cancel_releases_inventory(api):
    """PRD §3.7: "Cancelling a placed order moves it to the terminal CANCELLED,
    decreases the fundraiser's allocated_units by that order's units and recomputes
    available_units."

    Design: Difficulty/compensating_invariant/order_cancel_conserves_troop_dues
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "Inv9b"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 1000},
    )
    order = place_order(fr["id"], troop["id"], seller["id"], 150, fr["version"])
    validate_success(api.cancel_order(order["id"], LEAD), 200)
    fr_after = validate_success(api.get_fundraiser(fr["id"], REG), 200)
    assert fr_after["available_units"] == 1000


def test_fundraiser_close_cancels_placed_and_reverses_commission(api):
    """PRD §3.7: "Closing a fundraiser is permitted only from LIVE; it moves the
    status to CLOSED, auto-cancels every order still in PLACED (filled orders are
    never touched), and for each auto-cancelled order recomputes allocated_units and
    available_units and reverses its troop_commission_cents from TROOP_DUES with a
    reversal entry."

    Design: Corner/state_machines/fundraiser_close_cancels_placed_and_reverses_commission
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "S5"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 1000},
    )
    order = place_order(fr["id"], troop["id"], seller["id"], 150, fr["version"])

    closed = validate_success(api.close_fundraiser(fr["id"], REG), 200)
    assert closed["status"] == "CLOSED"

    order_after = validate_success(api.get_fundraiser_order(order["id"], REG), 200)
    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    assert order_after["status"] == "CANCELLED"
    assert troop_after["dues_account_cents"] == 0


def test_go_live_on_closed_fundraiser_invalid_state(api):
    """PRD §3.7: "Any fundraiser or order transition attempted from a state where it
    is not defined is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/fundraiser_terminal_closed_no_further_go_live
    """
    council = create_council(name="S4")
    fr = get_success_data(
        api.create_fundraiser(council["id"], create_fundraiser_payload(total_inventory_units=100), REG)
    )
    get_success_data(api.go_live_fundraiser(fr["id"], REG))
    get_success_data(api.close_fundraiser(fr["id"], REG))

    resp = api.go_live_fundraiser(fr["id"], REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_order_seller_in_wrong_troop_invalid_reference(api):
    """PRD §2.7: "every body-level reference ... must name an existing row, and
    additionally the seller_member_id on an order must belong to the same troop named
    by the order's troop_id. A violation of either condition is rejected with
    ERR_INVALID_REFERENCE (HTTP 422)."

    Design: Corner/validations/order_seller_in_wrong_troop_invalid_reference
    """
    council = create_council(name="V2")
    troop_a = get_success_data(api.create_troop(council["id"], {"unit_number": "V-2A", "program_type": "SCOUTS"}, REG))
    troop_b = get_success_data(api.create_troop(council["id"], {"unit_number": "V-2B", "program_type": "SCOUTS"}, REG))
    seller_b = create_member(troop_b["id"], member_type="YOUTH", full_name="B Seller")
    fr = create_live_fundraiser(council["id"], total_inventory_units=1000)

    resp = api.create_fundraiser_order(
        create_fundraiser_order_payload(fr["id"], troop_a["id"], seller_b["id"], 10, fr["version"]), LEAD
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE.value)


def test_fundraiser_version_increments_on_go_live(api):
    """PRD §2.4: "Most resources also expose a version, a system-managed integer that
    begins at 1 on creation and increases by one on every mutation."
    PRD §3.7: "Taking the fundraiser live requires it to be in DRAFT and to have at
    least one unit of total inventory; it moves the status to LIVE and increments
    version."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_write
    """
    council = create_council(name="OCC3")
    fr = get_success_data(
        api.create_fundraiser(council["id"], create_fundraiser_payload(total_inventory_units=100), REG)
    )
    assert fr["version"] == 1
    live = validate_success(api.go_live_fundraiser(fr["id"], REG), 200)
    assert live["version"] == 2


def test_order_place_stale_fundraiser_version_rejected(api):
    """PRD §2.6: "placing a fundraiser order requires the request body to carry
    expected_fundraiser_version, which must equal the target fundraiser's current
    version ... a placement request whose expected_fundraiser_version no longer
    matches the fundraiser's current version is rejected with ERR_STALE_VERSION
    (HTTP 412), so a seller must re-read available inventory before committing an
    allocation."

    Design: Corner/cross_cutting_complexity_layers/occ_order_place_stale_fundraiser
    """
    council, troop, seller, fr = setup_live_fundraiser_with_seller(
        council_overrides={"name": "OCC2"},
        fundraiser_overrides={"unit_price_cents": 500, "unit_cost_cents": 200, "total_inventory_units": 1000},
    )
    stale_v = fr["version"]
    # First order with stale_v succeeds and bumps the fundraiser version.
    place_order(fr["id"], troop["id"], seller["id"], 10, stale_v)
    # Second order reusing the now-stale version is rejected.
    resp = api.create_fundraiser_order(
        create_fundraiser_order_payload(fr["id"], troop["id"], seller["id"], 10, stale_v), LEAD
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
