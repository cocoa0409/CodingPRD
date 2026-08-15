"""Pricing engine: pick fee, min-drop, promo rounding, tax stamp, fuel surcharge."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    CREDIT,
    DRIVER,
    SALES,
    api_client,
    begin_loading,
    close_manifest,
    create_new_item_request_payload,
    create_order_guide_payload,
    create_promo_event_payload,
    create_purchase_order_payload,
    create_retailer_payload,
    create_tax_stamp_supply_payload,
    get_success_data,
    make_store_manager_headers,
    order_line,
    publish_fuel_rate,
    assign_order_to_manifest,
    setup_draft_order,
    setup_guide,
    setup_manifest,
    setup_product,
    setup_retailer,
    setup_stamp_supply,
    setup_submitted_order,
    validate_error,
    validate_success,
)


def test_pick_fee_constants_exact(api):
    """PRD §3.4: "The `pick_fee_cents` charges a flat 12 cents for every full
    case picked and 45 cents for every split-case each, summed over the order."
    PRD §3.4: "when that net merchandise figure is strictly below 50,000 cents
    a minimum-drop fee of 2,500 cents applies".

    Design: Corner/calculations/pick_fee_constants_exact
    """
    base = setup_draft_order([
        {"sku": "P1", "cases_qty": 1, "split_units_qty": 0},
        {"sku": "Q1", "cases_qty": 0, "split_units_qty": 1, "case_pack_units": 24,
         "case_cost_cents": 2400, "unit_cost_cents": 150, "weight_lbs_per_case": 8},
    ])
    resp = api_client.submit_order(
        base["order"]["id"],
        {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    data = validate_success(resp)
    assert data["pick_fee_cents"] == 57
    assert data["min_drop_fee_cents"] == 2500
    assert data["provisional_total_cents"] == 3907


def test_scan_back_promo_never_reduces_invoice(api):
    """PRD §3.2: "Only `OFF_INVOICE` promos reduce what the store is billed;
    `SCAN_BACK` events are recorded for manufacturer settlement and never
    reduce the invoice."

    Design: Corner/calculations/scan_back_promo_never_reduces_invoice
    """
    base = setup_draft_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        promo={"product_sku": "P1", "promo_type": "SCAN_BACK", "discount_pct_bps": 1000,
               "start_date": "2026-05-01", "end_date": "2026-05-31"},
    )
    resp = api_client.submit_order(
        base["order"]["id"],
        {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    data = validate_success(resp)
    assert data["promo_allowance_cents"] == 0
    assert data["provisional_total_cents"] == 60600


def test_slotting_fee_cap_applied(api, admin_headers, sales_rep_headers):
    """PRD §3.8: "a base of 50,000 cents plus 250 cents for each unit in the
    product's `case_pack_units`, capped at 150,000 cents — the fee is the
    lesser of the raw figure and the cap."

    Design: Corner/calculations/slotting_fee_cap_applied
    """
    retailer, _ = setup_retailer()
    product = setup_product(sku="PBIG", case_pack_units=500, case_cost_cents=9000,
                            unit_cost_cents=50, weight_lbs_per_case=40)
    setup_guide(retailer_id=retailer["id"], lines=[])
    nir = get_success_data(api_client.create_new_item_request(
        create_new_item_request_payload(
            retailer_id=retailer["id"],
            product_id=product["id"],
            proposed_shelf_price_cents=199,
        ),
        sales_rep_headers,
    ))
    resp = api_client.start_review(nir["id"], admin_headers)
    data = validate_success(resp)
    assert data["slotting_fee_cents"] == 150000


def test_promo_per_line_rounding_order(api):
    """PRD §3.4: "the line's `line_promo_cents` is the line merchandise cost
    multiplied by the promo's basis points divided by ten thousand, rounded
    half-up to integer cents per line, and the order allowance is the sum of
    those rounded per-line amounts. Rounding each line first and then summing
    is mandatory; summing across lines and rounding once is not used and
    yields different cents."

    Design: Difficulty/combinatorial_formula/promo_per_line_rounding_order
    """
    retailer, sm = setup_retailer()
    p2 = setup_product(sku="P2", case_pack_units=12, case_cost_cents=1005,
                       unit_cost_cents=100, split_case_allowed=False,
                       weight_lbs_per_case=5)
    p3 = setup_product(sku="P3", case_pack_units=12, case_cost_cents=1005,
                       unit_cost_cents=100, split_case_allowed=False,
                       weight_lbs_per_case=5)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": p2["id"], "par_cases": 0},
                               {"product_id": p3["id"], "par_cases": 0}])
    for p in (p2, p3):
        get_success_data(api_client.create_promo_event(create_promo_event_payload(
            product_id=p["id"], promo_type="OFF_INVOICE", discount_pct_bps=1000,
            start_date="2026-05-01", end_date="2026-05-31",
        ), SALES))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(p2["id"], cases_qty=1, split_units_qty=0),
                   order_line(p3["id"], cases_qty=1, split_units_qty=0)],
        ),
        sm,
    ))
    resp = api_client.submit_order(
        order["id"], {"expected_order_version": order["version"]}, sm,
    )
    data = validate_success(resp)
    assert data["promo_allowance_cents"] == 202
    assert data["provisional_total_cents"] == 4332


def test_promo_per_line_rounding_order_line_level(api):
    """PRD §3.4: "rounded half-up to integer cents per line". Two 1005-cent
    lines at 1000 bps each round to 101 cents, not the 100.5-sum once-rounded
    value of 201.

    Design: Difficulty/combinatorial_formula/promo_per_line_rounding_order
    """
    retailer, sm = setup_retailer()
    p2 = setup_product(sku="P2", case_pack_units=12, case_cost_cents=1005,
                       unit_cost_cents=100, split_case_allowed=False,
                       weight_lbs_per_case=5)
    p3 = setup_product(sku="P3", case_pack_units=12, case_cost_cents=1005,
                       unit_cost_cents=100, split_case_allowed=False,
                       weight_lbs_per_case=5)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": p2["id"], "par_cases": 0},
                               {"product_id": p3["id"], "par_cases": 0}])
    for p in (p2, p3):
        get_success_data(api_client.create_promo_event(create_promo_event_payload(
            product_id=p["id"], promo_type="OFF_INVOICE", discount_pct_bps=1000,
            start_date="2026-05-01", end_date="2026-05-31",
        ), SALES))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(p2["id"], cases_qty=1, split_units_qty=0),
                   order_line(p3["id"], cases_qty=1, split_units_qty=0)],
        ),
        sm,
    ))
    submit_resp = api_client.submit_order(
        order["id"], {"expected_order_version": order["version"]}, sm,
    )
    validate_success(submit_resp)
    # Per-line rounding visible on line rows
    resp = api_client.list_order_lines(order["id"], ADMIN)
    lines = get_success_data(resp)
    assert len(lines) == 2
    for line in lines:
        assert line["line_promo_cents"] == 101


def test_tax_stamp_nested_max_ceil(api):
    """PRD §3.4: "the stamp charge is the greater of the pack count times the
    jurisdiction's `stamp_rate_cents_per_pack` and the jurisdiction's
    `min_charge_cents`; the rolls needed are the pack count divided by
    `packs_per_roll` rounded up to a whole number; and the total stamp cost is
    the stamp charge plus the rolls needed times the `handling_fee_per_roll_cents`."

    Design: Difficulty/combinatorial_formula/tax_stamp_nested_max_ceil
    """
    retailer, sm = setup_retailer(jurisdiction_code="CA_NORTH")
    setup_stamp_supply(jurisdiction="CA_NORTH", stamp_rate_cents_per_pack=200,
                       handling_fee_per_roll_cents=1500, packs_per_roll=6000,
                       min_charge_cents=5000)
    t1 = setup_product(sku="T1", case_pack_units=60, case_cost_cents=33000,
                       unit_cost_cents=550, split_case_allowed=True,
                       is_tobacco=True, weight_lbs_per_case=15)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": t1["id"], "par_cases": 0}])
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(t1["id"], cases_qty=0, split_units_qty=20)],
        ),
        sm,
    ))
    resp = api_client.submit_order(
        order["id"], {"expected_order_version": order["version"]}, sm,
    )
    data = validate_success(resp)
    assert data["tax_stamp_cost_cents"] == 6500
    assert data["provisional_total_cents"] == 20900


def test_tax_stamp_full_case_pack_count(api):
    """PRD §3.4: "the pack count is the split units summed over tobacco lines
    plus, for tobacco full cases, `cases_qty` multiplied by the product's
    `case_pack_units`". One full case of 60 packs at 200 cents/pack exceeds the
    5000-cent floor so the max does NOT bind.

    Design: Difficulty/combinatorial_formula/tax_stamp_nested_max_ceil
    """
    retailer, sm = setup_retailer(jurisdiction_code="CA_NORTH")
    setup_stamp_supply(jurisdiction="CA_NORTH", stamp_rate_cents_per_pack=200,
                       handling_fee_per_roll_cents=1500, packs_per_roll=6000,
                       min_charge_cents=5000)
    t1 = setup_product(sku="T1", case_pack_units=60, case_cost_cents=33000,
                       unit_cost_cents=550, split_case_allowed=True,
                       is_tobacco=True, weight_lbs_per_case=15)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": t1["id"], "par_cases": 0}])
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(t1["id"], cases_qty=1, split_units_qty=0)],
        ),
        sm,
    ))
    resp = api_client.submit_order(
        order["id"], {"expected_order_version": order["version"]}, sm,
    )
    data = validate_success(resp)
    # packs = 60; stamp_charge = max(60*200, 5000) = 12000; rolls = ceil(60/6000) = 1
    # total = 12000 + 1*1500 = 13500
    assert data["tax_stamp_cost_cents"] == 13500


def test_fuel_surcharge_base_excludes_min_drop_fee(api):
    """PRD §3.5: "The surcharge base is computed in a pinned order: start from
    the order's merchandise subtotal, subtract the promo allowance, then add
    the pick fee; the minimum-drop fee is evaluated separately and is never
    part of the surcharge base."

    Design: Difficulty/combinatorial_formula/fuel_surcharge_base_excludes_min_drop_fee
    """
    base = setup_submitted_order([{"sku": "P1", "cases_qty": 40, "split_units_qty": 0}])
    manifest = setup_manifest()
    publish_fuel_rate(week_start_date="2026-05-25", doe_index_usd=3.75)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    order = get_success_data(api_client.get_purchase_order(base["order"]["id"], ADMIN))
    assert order["min_drop_fee_cents"] == 2500
    assert order["provisional_total_cents"] == 50980
    assert order["fuel_surcharge_cents"] == 1212


def test_fuel_surcharge_base_excludes_min_drop_fee_in_invoice(api):
    """PRD §3.5: "the minimum-drop fee is evaluated separately and is never
    part of the surcharge base" — so the stamped surcharge at 2.5% on a
    48480 base is 1212, not 1275 (which would include the 2500 fee).
    PRD §3.6: "plus the fuel surcharge stamped at manifest close".

    Design: Difficulty/combinatorial_formula/fuel_surcharge_base_excludes_min_drop_fee
    """
    base = setup_submitted_order([{"sku": "P1", "cases_qty": 40, "split_units_qty": 0}])
    manifest = setup_manifest()
    publish_fuel_rate(week_start_date="2026-05-25", doe_index_usd=3.75)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    invoice = get_success_data(api_client.confirm_delivery(base["order"]["id"], DRIVER))
    # PRD §3.6 final total: delivered merch 48000 + pick 480 + stamp 0 + fuel 1212
    # = 49692 — the minimum-drop fee is a submission-time term and is not part
    # of the final-total composition ("plus delivered pick fees, plus the
    # tax-stamp cost carried unchanged from submission, plus the fuel
    # surcharge stamped at manifest close").
    assert invoice["invoiced_total_cents"] == 49692


def test_fuel_tier_inclusive_at_350(api):
    """PRD §3.5: "an index of at least $3.50 but below $4.00 selects the
    2.5 percent tier — an index of exactly $3.50 included".

    Design: Difficulty/boundary_precision_check/fuel_tier_inclusive_at_350
    """
    base = setup_submitted_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        promo={"product_sku": "P1", "promo_type": "OFF_INVOICE", "discount_pct_bps": 1000,
               "start_date": "2026-05-01", "end_date": "2026-05-31"},
    )
    manifest = setup_manifest()
    publish_fuel_rate(week_start_date="2026-05-25", doe_index_usd=3.50)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    order = get_success_data(api_client.get_purchase_order(base["order"]["id"], ADMIN))
    # base = merch 60000 - promo 6000 + pick 600 = 54600; 54600 * 2.5% = 1365
    assert order["fuel_surcharge_cents"] == 1365


def test_fuel_tier_just_below_350_selects_zero(api):
    """PRD §3.5: "an index below $3.50 per gallon means no surcharge at all".
    At 3.4999 the order pays no fuel surcharge; the 2.5% tier lower bound is
    exclusive from below.

    Design: Difficulty/boundary_precision_check/fuel_tier_inclusive_at_350
    """
    base = setup_submitted_order(
        [{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}],
        promo={"product_sku": "P1", "promo_type": "OFF_INVOICE", "discount_pct_bps": 1000,
               "start_date": "2026-05-01", "end_date": "2026-05-31"},
    )
    manifest = setup_manifest()
    publish_fuel_rate(week_start_date="2026-05-25", doe_index_usd=3.49)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    order = get_success_data(api_client.get_purchase_order(base["order"]["id"], ADMIN))
    assert order["fuel_surcharge_cents"] == 0


def test_min_drop_exact_threshold_no_fee(api):
    """PRD §3.4: "when that net merchandise figure is strictly below 50,000
    cents a minimum-drop fee of 2,500 cents applies — an order netting exactly
    50,000 cents pays no fee."

    Design: Difficulty/boundary_precision_check/min_drop_exact_threshold_no_fee
    """
    base = setup_draft_order([
        {"sku": "P1", "cases_qty": 41, "split_units_qty": 0},
        {"sku": "Q2", "cases_qty": 0, "split_units_qty": 8, "case_pack_units": 24,
         "case_cost_cents": 2400, "unit_cost_cents": 100, "weight_lbs_per_case": 8},
    ])
    resp = api_client.submit_order(
        base["order"]["id"],
        {"expected_order_version": base["order_version"]},
        base["sm_headers"],
    )
    data = validate_success(resp)
    assert data["min_drop_fee_cents"] == 0
    assert data["provisional_total_cents"] == 50852


def test_min_drop_one_cent_below_threshold_incurs_fee(api):
    """PRD §3.4: "when that net merchandise figure is strictly below 50,000
    cents a minimum-drop fee of 2,500 cents applies". Net 49999 < 50000 is
    strictly below.

    Design: Difficulty/boundary_precision_check/min_drop_exact_threshold_no_fee
    """
    retailer, sm = setup_retailer()
    p1 = setup_product(sku="P1", case_pack_units=12, case_cost_cents=1200,
                       unit_cost_cents=110, split_case_allowed=True,
                       weight_lbs_per_case=10)
    q2 = setup_product(sku="Q2", case_pack_units=24, case_cost_cents=2400,
                       unit_cost_cents=799, split_case_allowed=True,
                       weight_lbs_per_case=8)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": p1["id"], "par_cases": 0},
                               {"product_id": q2["id"], "par_cases": 0}])
    get_success_data(api_client.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(p1["id"], cases_qty=41, split_units_qty=0),
                   order_line(q2["id"], cases_qty=0, split_units_qty=1)],
        ),
        sm,
    ))
    resp = api_client.submit_order(
        order["id"], {"expected_order_version": order["version"]}, sm,
    )
    data = validate_success(resp)
    # net = 49200 + 799 = 49999 < 50000 -> fee 2500
    assert data["merch_subtotal_cents"] == 49999
    assert data["min_drop_fee_cents"] == 2500
