"""Consignment corner (shelf guards, capacity overlap, payout math) and outgrown
trade-ins (quoted vs final valuation with the condition cap).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    new_store,
    new_shelf,
    new_customer,
    new_sku,
    new_consignment_item,
    new_trade_in,
    display_item,
    display_payload,
    setup_displayed_consignment_item,
)

STAFF = TEST_USERS["store_staff_headers"]


def test_display_onto_closed_shelf_returns_shelf_closed(api):
    """PRD §3.6: "Display requires the item to currently be `RECEIVED`, else
    `ERR_CONSIGNMENT_NOT_RECEIVED`, and requires the target shelf to be `OPEN`,
    else `ERR_SHELF_CLOSED`."

    Design: Corner/state_machines/display_onto_closed_shelf_returns_shelf_closed
    """
    store = new_store(api)
    shelf = new_shelf(api, store["id"], capacity=5)
    get_success_data(api.close_shelf(shelf["id"], STAFF))
    customer = new_customer(api)
    item = new_consignment_item(api, customer["id"], store["id"], condition="GOOD",
                                season="IN_SEASON", list_price_cents=4000)
    resp = api.display_consignment_item(
        item["id"],
        display_payload(shelf["id"], "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_SHELF_CLOSED.value)


def test_shelf_capacity_overlap_conflict(api):
    """PRD §3.6: "counting on a closed-interval basis, adding this window must
    not raise the number of overlapping `ON_DISPLAY` items on the shelf above
    the shelf's `capacity`, or the request is rejected with
    `ERR_SHELF_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/shelf_capacity_overlap_conflict
    """
    store = new_store(api)
    shelf = new_shelf(api, store["id"], capacity=1)
    customer = new_customer(api)
    ci1 = new_consignment_item(api, customer["id"], store["id"], condition="GOOD",
                               season="IN_SEASON", list_price_cents=4000)
    ci2 = new_consignment_item(api, customer["id"], store["id"], condition="GOOD",
                               season="IN_SEASON", list_price_cents=4000)
    display_item(api, ci1["id"], shelf["id"], "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z")
    resp = api.display_consignment_item(
        ci2["id"],
        display_payload(shelf["id"], "2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_SHELF_CAPACITY_EXCEEDED.value)


def test_shelf_capacity_allows_non_overlapping_windows(api):
    """PRD §3.6: "A shelf enforces its `capacity` as a limit on how many
    displayed items may overlap in time at once: counting on a closed-interval
    basis, adding this window must not raise the number of overlapping
    `ON_DISPLAY` items on the shelf above the shelf's `capacity`, or the request
    is rejected with `ERR_SHELF_CAPACITY_EXCEEDED`." — a non-overlapping window
    on a capacity-1 shelf is accepted.

    Design: Difficulty/resource_temporal_overlap/shelf_capacity_overlap_conflict
    """
    store = new_store(api)
    shelf = new_shelf(api, store["id"], capacity=1)
    customer = new_customer(api)
    ci1 = new_consignment_item(api, customer["id"], store["id"], condition="GOOD",
                               season="IN_SEASON", list_price_cents=4000)
    ci2 = new_consignment_item(api, customer["id"], store["id"], condition="GOOD",
                               season="IN_SEASON", list_price_cents=4000)
    display_item(api, ci1["id"], shelf["id"], "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z")
    resp = api.display_consignment_item(
        ci2["id"],
        display_payload(shelf["id"], "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z"),
        STAFF,
    )
    data = validate_success(resp, 200)
    assert data["status"] == "ON_DISPLAY"


def test_consignor_payout_split_selection_and_fee_cap(api):
    """PRD §3.6: "The split rate starts from the season: an `IN_SEASON` item pays
    a 60 percent base split and an `OFF_SEASON` item pays 50 percent, and if the
    item's `condition` is `LIKE_NEW` a further 5-percentage-point condition bonus
    is added to that split."
    PRD §3.6: "The gross payout is `sale_price_cents` multiplied by that combined
    split rate, rounded half up to whole cents."
    PRD §3.6: "The processing fee is `sale_price_cents` multiplied by 3 percent
    and rounded half up to whole cents, but capped at 200 cents — the fee is the
    lesser of the two."
    PRD §3.6: "The final `payout_cents` is the gross payout minus the processing
    fee, with the gross and the fee each rounded independently before the
    subtraction."

    Design: Difficulty/combinatorial_formula/consignor_payout_split_selection_and_fee_cap
    """
    ctx = setup_displayed_consignment_item(api, condition="LIKE_NEW", item_season="IN_SEASON",
                                           list_price_cents=10000, shelf_capacity=5)
    cust = ctx["customer"]["id"]
    data = validate_success(api.sell_consignment_item(ctx["item"]["id"],
                                                      {"sale_price_cents": 10000}, STAFF), 200)
    # split 0.60+0.05=0.65 -> gross 6500; fee min(round(300),200)=200; payout 6300.
    assert data["status"] == "SOLD"
    assert data["payout_cents"] == 6300
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cust_data["store_credit_balance_cents"] == 6300


def test_consignor_payout_off_season_good_fee_below_cap(api):
    """PRD §3.6: "The split rate starts from the season: an `IN_SEASON` item pays
    a 60 percent base split and an `OFF_SEASON` item pays 50 percent, and if the
    item's `condition` is `LIKE_NEW` a further 5-percentage-point condition bonus
    is added to that split."
    PRD §3.6: "The processing fee is `sale_price_cents` multiplied by 3 percent
    and rounded half up to whole cents, but capped at 200 cents — the fee is the
    lesser of the two."
    PRD §3.6: "The final `payout_cents` is the gross payout minus the processing
    fee, with the gross and the fee each rounded independently before the
    subtraction."

    Design: Difficulty/combinatorial_formula/consignor_payout_split_selection_and_fee_cap
    """
    ctx = setup_displayed_consignment_item(api, condition="GOOD", item_season="OFF_SEASON",
                                           list_price_cents=5000, shelf_capacity=5)
    cust = ctx["customer"]["id"]
    data = validate_success(api.sell_consignment_item(ctx["item"]["id"],
                                                      {"sale_price_cents": 5000}, STAFF), 200)
    # split 0.50 -> gross 2500; fee min(round(150),200)=150; payout 2350.
    assert data["payout_cents"] == 2350
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cust_data["store_credit_balance_cents"] == 2350


def test_trade_in_quoted_value_good_condition_percent_of_retail(api):
    """PRD §3.7: "the SKU's `base_price_cents` multiplied by a condition factor —
    `LIKE_NEW` contributes a factor of 1.00, `GOOD` a factor of 0.70, and `FAIR`
    a factor of 0.40 — multiplied by the trade-in base rate of 30 percent, the
    whole product rounded half up to whole cents. The quoted value uses the
    `submitted_condition` and applies **no** cap."

    Design: Corner/calculations/trade_in_quoted_value_good_condition_percent_of_retail
    """
    store = new_store(api)
    customer = new_customer(api)
    sku = new_sku(api, store["id"], base_price_cents=10000)
    ti = new_trade_in(api, customer["id"], sku["id"], submitted_condition="GOOD")
    # round(10000 * 0.70 * 0.30) = 2100
    assert ti["quoted_value_cents"] == 2100
    assert ti["status"] == "SUBMITTED"


def test_trade_in_reject_issues_no_store_credit(api):
    """PRD §3.7: "Rejection advances `SUBMITTED → REJECTED`, issues no credit,
    and leaves `final_value_cents` at zero."

    Design: Corner/state_machines/trade_in_reject_issues_no_store_credit
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=10000)
    ti = new_trade_in(api, cust, sku["id"], submitted_condition="GOOD")
    data = validate_success(api.reject_trade_in(ti["id"], STAFF), 200)
    assert data["status"] == "REJECTED"
    assert data["final_value_cents"] == 0
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cust_data["store_credit_balance_cents"] == 0


def test_trade_in_final_valuation_applies_condition_cap(api):
    """PRD §3.7: "The **final** value is then computed into `final_value_cents`
    using the same percent-of-retail formula but evaluated with the
    `inspected_condition` and then capped: the final value is the lesser of that
    percent-of-retail figure and the condition's cap, where the caps are 2500
    cents for `LIKE_NEW`, 1500 cents for `GOOD`, and 800 cents for `FAIR`."
    PRD §3.7: "On acceptance the computed `final_value_cents` is credited to the
    customer's `store_credit_balance_cents`."

    Design: Difficulty/dual_variant_calc/trade_in_final_valuation_applies_condition_cap
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=10000)
    ti = new_trade_in(api, cust, sku["id"], submitted_condition="LIKE_NEW")
    assert ti["quoted_value_cents"] == 3000  # round(10000*1.00*0.30), no cap
    data = validate_success(
        api.accept_trade_in(ti["id"], {"inspected_condition": "LIKE_NEW"}, STAFF), 200
    )
    # final = min(round(10000*1.00*0.30)=3000, cap LIKE_NEW 2500) = 2500
    assert data["final_value_cents"] == 2500
    assert data["status"] == "ACCEPTED"
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cust_data["store_credit_balance_cents"] == 2500


def test_trade_in_final_valuation_uses_inspected_condition(api):
    """PRD §3.7: "Acceptance advances `SUBMITTED → ACCEPTED` and may carry an
    `inspected_condition`; when omitted, `inspected_condition` defaults to the
    `submitted_condition`."
    PRD §3.7: "The **final** value is then computed into `final_value_cents`
    using the same percent-of-retail formula but evaluated with the
    `inspected_condition` and then capped: the final value is the lesser of that
    percent-of-retail figure and the condition's cap, where the caps are 2500
    cents for `LIKE_NEW`, 1500 cents for `GOOD`, and 800 cents for `FAIR`."

    Design: Difficulty/dual_variant_calc/trade_in_final_valuation_applies_condition_cap
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=10000)
    ti = new_trade_in(api, cust, sku["id"], submitted_condition="LIKE_NEW")
    assert ti["quoted_value_cents"] == 3000
    data = validate_success(
        api.accept_trade_in(ti["id"], {"inspected_condition": "GOOD"}, STAFF), 200
    )
    # inspected GOOD: percent = round(10000*0.70*0.30)=2100; cap GOOD 1500 -> final 1500
    assert data["final_value_cents"] == 1500
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cust_data["store_credit_balance_cents"] == 1500
