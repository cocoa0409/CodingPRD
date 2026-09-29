"""Collection projections: filter composition, computed-status pages and the one
endpoint whose response is not an entity at all.

Every filter here narrows an independently declared axis, so the interesting
question is never "does the filter work" but "do the filters intersect, does
total_count describe the filtered set rather than the page, and does a status
nobody wrote still move a row from one page to another".
"""

import pytest

from test_helpers import (
    ADMIN,
    BILLING,
    BUYER,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    QE_TESTER,
    create_customer,
    create_draft_product,
    create_lot,
    create_order,
    create_reel,
    create_rod_lot,
    get_success_data,
    read_customer,
    read_product,
    setup_baseline,
    setup_invoiced_shipment,
    setup_lv_catalog,
    setup_staged_shipment,
    validate_paginated,
    validate_success,
)

ALUMINUM_SKU = {
    "product_code": "XHHW-10-AL",
    "awg_size": "10",
    "conductor_metal": "ALUMINUM",
    "application_rating": "XHHW_2",
    "insulation_thickness_mils": 45.0,
    "conductor_lbs_per_kft": 30.0,
    "base_target_kft": 40.0,
    "demand_index": 0.70,
}


def _codes(rows, key):
    return [row[key] for row in rows]


def test_the_lot_list_intersects_six_filters_and_counts_the_filtered_set(api):
    """Six independent filters compose on one collection, an offset page still
    reports the whole filtered count, and an empty result is a 200 with no rows.

    PRD 3.6: "Lots may be listed and narrowed by `product_id`, by `rod_lot_id`,
    by `order_id`, by `line_code`, by `process_state` and by `quality_state`."

    PRD 2.3: "`total_count` reports the number of records matching the filters
    before the page window is applied, and `has_more` is true whenever records
    remain beyond the current window."

    Design: Corner/endpoints/production_lot_list_composes_filters_and_pages_in_created_at_order
    """
    world = setup_baseline(api)
    lot_1 = create_lot(api, world, lot_code="LOT-1", planned_length_ft=1000)
    create_lot(
        api, dict(world, order=None), lot_code="LOT-2", planned_length_ft=1000,
        line_code="EXT-2",
    )
    lot_3 = create_lot(
        api, world, lot_code="LOT-3", planned_length_ft=1000,
        scheduled_start_at="2026-08-02T13:00:00Z",
        scheduled_end_at="2026-08-02T17:00:00Z",
    )
    for lot_id in (lot_1["id"], lot_3["id"]):
        get_success_data(api.create_process_step(lot_id, {"step": "DRAWING"}, ENGINEER))

    rows, meta = validate_paginated(api.list_production_lots(ENGINEER))
    assert _codes(rows, "lot_code") == ["LOT-1", "LOT-2", "LOT-3"], (
        "the collection reads in created_at ascending order"
    )
    assert meta["total_count"] == 3
    assert meta["limit"] == 10, "ten is the declared default page size"
    assert meta["offset"] == 0
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_production_lots(QE_TESTER, params={"line_code": "EXT-1"})
    )
    assert _codes(rows, "lot_code") == ["LOT-1", "LOT-3"]
    assert meta["total_count"] == 2, "the lot on EXT-2 is excluded"

    rows, meta = validate_paginated(
        api.list_production_lots(CLERK, params={"process_state": "QUEUED"})
    )
    assert _codes(rows, "lot_code") == ["LOT-2"]
    assert meta["total_count"] == 1, "the two drawn lots are excluded"

    rows, meta = validate_paginated(
        api.list_production_lots(
            CERT_OFFICER, params={"line_code": "EXT-1", "process_state": "DRAWN"}
        )
    )
    assert _codes(rows, "lot_code") == ["LOT-1", "LOT-3"]
    assert meta["total_count"] == 2, "two filters intersect, they do not union"

    rows, meta = validate_paginated(
        api.list_production_lots(ENGINEER, params={"order_id": world["order"]["id"]})
    )
    assert _codes(rows, "lot_code") == ["LOT-1", "LOT-3"]
    assert meta["total_count"] == 2, "the lot with no order is excluded"

    rows, meta = validate_paginated(
        api.list_production_lots(
            ENGINEER,
            params={"rod_lot_id": world["rod_lot"]["id"], "limit": 1, "offset": 1},
        )
    )
    assert _codes(rows, "lot_code") == ["LOT-2"], "the second row of the filtered set"
    assert meta["total_count"] == 3, "the count describes the filtered set, not the page"
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api.list_production_lots(QE_TESTER, params={"quality_state": "NONCONFORMING"})
    )
    assert rows == []
    assert meta["total_count"] == 0, "an empty filtered result is not a not-found"
    assert meta["has_more"] is False


def test_rod_and_sku_pages_move_on_their_own_when_a_computed_status_changes(api):
    """Both lists filter a status nobody ever writes directly, so exhausting a heat
    and releasing a SKU each move a row to a different page as a side effect.

    PRD 3.1: "Rod lots may be listed and narrowed by `metal` and by `status`."

    PRD 3.4: "SKUs may be listed and narrowed by `insulation_compound_id`, by
    `jacket_compound_id`, by `listing_certification_id`, by `status` and by
    `application_rating`."

    Design: Corner/endpoints/rod_lot_and_sku_lists_filter_on_status_metal_and_dependency
    """
    world = setup_lv_catalog(api)
    create_draft_product(
        api, world["insulation"]["id"], world["certification"]["id"], **ALUMINUM_SKU
    )
    copper_rod = create_rod_lot(api, purchase_weight_lbs=138.60)
    create_rod_lot(
        api, metal="ALUMINUM", heat_number="H-AL1", purchase_weight_lbs=5000.00,
        purchase_price_usd_per_lb=1.20,
    )
    create_lot(
        api, dict(world, rod_lot=copper_rod, order=None), lot_code="LOT-A",
        planned_length_ft=7000,
    )

    rows, meta = validate_paginated(api.list_rod_purchase_lots(BUYER))
    assert _codes(rows, "heat_number") == ["H-77Q", "H-AL1"]
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_rod_purchase_lots(QE_TESTER, params={"status": "RECEIVED"})
    )
    assert _codes(rows, "heat_number") == ["H-AL1"], (
        "the copper heat left this page with nobody writing to its status, because the "
        "7000 foot allocation drove remaining_lbs to zero"
    )
    rows, meta = validate_paginated(
        api.list_rod_purchase_lots(QE_TESTER, params={"status": "CONSUMED"})
    )
    assert _codes(rows, "heat_number") == ["H-77Q"]
    assert meta["total_count"] == 1
    assert rows[0]["remaining_lbs"] == pytest.approx(0.00, abs=0.01)

    rows, meta = validate_paginated(
        api.list_rod_purchase_lots(ENGINEER, params={"metal": "ALUMINUM"})
    )
    assert meta["total_count"] == 1
    rows, meta = validate_paginated(
        api.list_rod_purchase_lots(
            ENGINEER, params={"metal": "ALUMINUM", "status": "CONSUMED"}
        )
    )
    assert meta["total_count"] == 0, "the metal and status filters intersect"

    rows, meta = validate_paginated(
        api.list_catalog_products(BILLING, params={"status": "RELEASED"})
    )
    assert _codes(rows, "product_code") == ["THHN-12-CU"]
    rows, meta = validate_paginated(
        api.list_catalog_products(BILLING, params={"status": "DRAFT"})
    )
    assert _codes(rows, "product_code") == ["XHHW-10-AL"]

    rows, meta = validate_paginated(
        api.list_catalog_products(
            CLERK,
            params={"insulation_compound_id": world["insulation"]["id"],
                    "listing_certification_id": world["certification"]["id"]},
        )
    )
    assert _codes(rows, "product_code") == ["THHN-12-CU", "XHHW-10-AL"]
    assert meta["total_count"] == 2, "both SKUs hang off the same compound and file"

    rows, meta = validate_paginated(
        api.list_catalog_products(CLERK, params={"application_rating": "XHHW_2"})
    )
    assert _codes(rows, "product_code") == ["XHHW-10-AL"]
    rows, meta = validate_paginated(
        api.list_catalog_products(
            CLERK, params={"jacket_compound_id": world["insulation"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "neither SKU has a jacket, and the jacket filter is not confused by the "
        "insulation reference"
    )


def test_the_order_list_exposes_both_status_dimensions_as_separate_filters(api):
    """One order answers both a pricing filter and a fulfillment filter that a
    single-status model would make mutually exclusive.

    PRD 3.5: "Orders may be listed and narrowed by `customer_id`, by `product_id`,
    by `pricing_status` and by `fulfillment_status`."

    PRD 3.5: "The two dimensions are genuinely independent: `pricing_status` moves
    among `QUOTED`, `LOCKED`, `HELD` and `INVOICED`, while `fulfillment_status`
    moves among `OPEN`, `PARTIALLY_SHIPPED`, `FULFILLED` and the terminal
    `CANCELLED`, and neither dimension constrains the other except where a rule
    says so explicitly."

    Design: Corner/endpoints/order_list_filters_on_both_parallel_status_dimensions
    """
    world = setup_lv_catalog(api)
    acme = create_customer(api)
    beta = create_customer(api, account_code="BETA", name="Beta Contractors")
    product_id = world["product"]["id"]
    order_a = create_order(api, acme["id"], product_id, order_number="SO-A")
    create_order(api, acme["id"], product_id, order_number="SO-B")
    order_c = create_order(api, acme["id"], product_id, order_number="SO-C")
    create_order(api, beta["id"], product_id, order_number="SO-D")
    get_success_data(api.price_lock_customer_order(order_a["id"], BILLING))
    get_success_data(api.cancel_customer_order(order_c["id"], BILLING))

    rows, meta = validate_paginated(api.list_customer_orders(BILLING))
    assert _codes(rows, "order_number") == ["SO-A", "SO-B", "SO-C", "SO-D"]
    assert meta["total_count"] == 4

    rows, meta = validate_paginated(
        api.list_customer_orders(CLERK, params={"customer_id": acme["id"]})
    )
    assert _codes(rows, "order_number") == ["SO-A", "SO-B", "SO-C"]
    assert meta["total_count"] == 3

    rows, meta = validate_paginated(
        api.list_customer_orders(ENGINEER, params={"pricing_status": "LOCKED"})
    )
    assert _codes(rows, "order_number") == ["SO-A"]
    assert rows[0]["fulfillment_status"] == "OPEN", (
        "confirming the price basis moved the pricing dimension only"
    )

    rows, meta = validate_paginated(
        api.list_customer_orders(BILLING, params={"pricing_status": "QUOTED"})
    )
    assert _codes(rows, "order_number") == ["SO-B", "SO-C", "SO-D"], (
        "the cancelled order keeps its QUOTED pricing status"
    )
    assert meta["total_count"] == 3

    rows, meta = validate_paginated(
        api.list_customer_orders(BILLING, params={"fulfillment_status": "CANCELLED"})
    )
    assert _codes(rows, "order_number") == ["SO-C"]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_customer_orders(
            BILLING, params={"customer_id": acme["id"], "fulfillment_status": "OPEN"}
        )
    )
    assert _codes(rows, "order_number") == ["SO-A", "SO-B"]
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_customer_orders(
            BILLING, params={"product_id": product_id, "limit": 2, "offset": 2}
        )
    )
    assert _codes(rows, "order_number") == ["SO-C", "SO-D"]
    assert meta["total_count"] == 4
    assert meta["has_more"] is False, "offset two of four is the last page"

    rows, meta = validate_paginated(
        api.list_customer_orders(
            BILLING,
            params={"customer_id": beta["id"], "fulfillment_status": "FULFILLED"},
        )
    )
    assert meta["total_count"] == 0


def test_reel_and_shipment_pages_follow_pointers_no_request_body_ever_named(api):
    """Loading and staging set two denormalised pointers, and invoicing moves a
    shipment from one status page to another without any field being submitted.

    PRD 3.8: "Reels may be listed and narrowed by `status`, by `reel_type`, by
    `current_lot_id` and by `held_by_customer_id`."

    PRD 3.8: "Shipments may be listed and narrowed by `order_id`, by `lot_id`, by
    `reel_id` and by `status`."

    Design: Corner/endpoints/reel_and_shipment_lists_track_computed_status_and_references
    """
    world, lot, reel, shipment = setup_staged_shipment(
        api, reel_overrides={"reel_serial": "R-A", "reel_type": "WOOD_RETURNABLE"}
    )
    spare = create_reel(api, reel_serial="R-B", reel_type="STEEL_RETURNABLE")

    rows, meta = validate_paginated(api.list_reels(CLERK))
    assert _codes(rows, "reel_serial") == ["R-A", "R-B"]
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_reels(BILLING, params={"status": "AVAILABLE"})
    )
    assert _codes(rows, "reel_serial") == ["R-B"]
    rows, meta = validate_paginated(
        api.list_reels(
            ENGINEER, params={"status": "SHIPPED", "reel_type": "WOOD_RETURNABLE"}
        )
    )
    assert _codes(rows, "reel_serial") == ["R-A"]

    rows, meta = validate_paginated(
        api.list_reels(BILLING, params={"held_by_customer_id": world["customer"]["id"]})
    )
    assert _codes(rows, "reel_serial") == ["R-A"], (
        "the holder pointer was set by the staging side effect, never by a body"
    )
    rows, meta = validate_paginated(
        api.list_reels(CLERK, params={"current_lot_id": lot["id"]})
    )
    assert _codes(rows, "reel_serial") == ["R-A"], "the lot pointer was set by the load"

    rows, meta = validate_paginated(
        api.list_shipments(CLERK, params={"status": "STAGED"})
    )
    assert _codes(rows, "id") == [shipment["id"]]
    assert meta["total_count"] == 1

    get_success_data(api.invoice_shipment(shipment["id"], BILLING))

    rows, meta = validate_paginated(
        api.list_shipments(CLERK, params={"status": "STAGED"})
    )
    assert meta["total_count"] == 0, "invoicing emptied the staged page"
    rows, meta = validate_paginated(
        api.list_shipments(
            BILLING, params={"status": "INVOICED", "order_id": world["order"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["invoice_amount_usd"] == pytest.approx(544.58, abs=0.01)

    rows, meta = validate_paginated(
        api.list_shipments(BILLING, params={"reel_id": spare["id"]})
    )
    assert meta["total_count"] == 0, "no shipment ever referenced the spare reel"
    rows, meta = validate_paginated(
        api.list_shipments(CLERK, params={"lot_id": lot["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_one_return_row_is_projected_by_both_the_reel_and_the_shipment(api):
    """A single append-only return row is addressable through two parents, and both
    projections must be the same row rather than a copy each.

    PRD 3.9: "They may be listed against the reel they belong to, narrowed by
    `condition`, and they may also be listed against the shipment they settled,
    which is how a billing analyst reconciles a single delivery's deposits."

    PRD 3.9: "Each row records the `reel_id` returned, the `shipment_id` that
    sent it out, the `returned_date`, the reported `condition`, and the computed
    `days_out`, `refund_usd`, `forfeited_usd` and `refund_variant_applied`."

    Design: Corner/endpoints/reel_return_is_readable_from_both_the_reel_and_the_shipment
    """
    world, lot, reel, shipment = setup_invoiced_shipment(api)
    spare = create_reel(api, reel_serial="R-B", reel_type="STEEL_RETURNABLE")
    row = validate_success(
        api.create_reel_return(
            reel["id"],
            {"shipment_id": shipment["id"], "returned_date": "2026-08-10",
             "condition": "GOOD"},
            CLERK,
        ),
        201,
    )
    assert row["days_out"] == 9, "the reel went out on 2026-08-01 and came back the 10th"

    from_reel, reel_meta = validate_paginated(api.list_reel_returns(reel["id"], CLERK))
    from_shipment, ship_meta = validate_paginated(
        api.list_shipment_reel_returns(shipment["id"], BILLING)
    )
    assert _codes(from_reel, "id") == [row["id"]]
    assert _codes(from_shipment, "id") == [row["id"]], (
        "both parents project the identical row, they do not each own a copy"
    )
    assert from_reel[0]["shipment_id"] == shipment["id"]
    assert from_shipment[0]["reel_id"] == reel["id"]
    for meta in (reel_meta, ship_meta):
        assert meta["total_count"] == 1
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_reel_returns(reel["id"], BILLING, params={"condition": "DAMAGED"})
    )
    assert meta["total_count"] == 0, (
        "the condition filter narrows this parent's children only"
    )
    rows, meta = validate_paginated(api.list_reel_returns(spare["id"], CLERK))
    assert meta["total_count"] == 0, (
        "the never-loaded reel exists, so its empty child collection is a 200"
    )


def test_repositioning_answers_a_summary_and_skips_every_unreleased_sku(api):
    """The only response in the service that is not an entity: a run summary with no
    identifier and no version, whose scope is decided by SKU status, not by the
    caller's explicit list.

    PRD 3.4: "Only SKUs whose status is `RELEASED` are evaluated, in ascending
    `created_at` order. SKUs at `DRAFT`, `SUSPENDED` or `OBSOLETE` are skipped and
    keep their previous `volatility_index` and `target_inventory_kft` untouched."

    PRD 3.4: "The run reports back the `as_of_date` it used, an `evaluated_count`,
    a `skipped_count`, and the `product_ids` it actually evaluated."

    PRD 3.4: "If the window holds fewer than three quotes there is not enough
    history to characterise volatility and `volatility_index` is set to 0.0000."

    Design: Corner/endpoints/inventory_reposition_returns_a_non_entity_summary_and_skips_unreleased_skus
    """
    world = setup_lv_catalog(api)
    copper_sku = world["product"]
    aluminum_sku = create_draft_product(
        api, world["insulation"]["id"], world["certification"]["id"], **ALUMINUM_SKU
    )

    first = validate_success(
        api.reposition_inventory({"as_of_date": "2026-08-01"}, ENGINEER), 200
    )
    assert first["as_of_date"] == "2026-08-01"
    assert first["evaluated_count"] == 1
    assert first["skipped_count"] == 1
    assert first["product_ids"] == [copper_sku["id"]]
    for absent in ("id", "created_at", "version"):
        assert absent not in first, f"a run summary is not an entity and carries no {absent}"

    copper = read_product(api, copper_sku["id"])
    assert copper["volatility_index"] == pytest.approx(0.0000, abs=0.00005), (
        "one copper quote is fewer than the three the window needs"
    )
    assert copper["target_inventory_kft"] == pytest.approx(100.0, abs=0.05), (
        "a demand index of 1.0 takes the mid multiplier and an undamped target"
    )
    assert read_product(api, aluminum_sku["id"])[
        "target_inventory_kft"
    ] == pytest.approx(40.0, abs=0.05), (
        "the skipped SKU still carries the target it was initialised with"
    )

    second = validate_success(
        api.reposition_inventory(
            {"as_of_date": "2026-08-01", "product_ids": [aluminum_sku["id"]]}, ENGINEER
        ),
        200,
    )
    assert second["evaluated_count"] == 0
    assert second["skipped_count"] == 1
    assert second["product_ids"] == [], (
        "naming a draft SKU narrows the scope, it does not override the status rule"
    )

    get_success_data(api.release_catalog_product(aluminum_sku["id"], ENGINEER))
    third = validate_success(
        api.reposition_inventory(
            {"as_of_date": "2026-08-01", "product_ids": [aluminum_sku["id"]]}, ENGINEER
        ),
        200,
    )
    assert third["evaluated_count"] == 1
    assert third["skipped_count"] == 0

    aluminum = read_product(api, aluminum_sku["id"])
    assert aluminum["volatility_index"] == pytest.approx(0.0000, abs=0.00005), (
        "no aluminium settlement exists at all"
    )
    assert aluminum["target_inventory_kft"] == pytest.approx(12.0, abs=0.05), (
        "40.0 base at the 0.30 low-demand multiplier is 12.0, clear of the 10.0 floor"
    )
    assert read_product(api, copper_sku["id"])[
        "target_inventory_kft"
    ] == pytest.approx(100.0, abs=0.05), "the third run touched only the SKU it named"


def test_a_partial_account_update_writes_only_what_it_names_yet_re_reads_the_ledger(api):
    """Lowering a limit puts the account on hold with no money moving, and the next
    partial update must neither resurrect the old limit nor clear the hold.

    PRD 3.5: "Accounts may be adjusted later, and an adjustment may carry any
    combination of a revised `credit_limit_usd`, a revised `pass_through_enabled`
    election and a revised `reel_program`."

    PRD 3.5: "The account moves to `CREDIT_HOLD` when `credit_exposure_usd` is
    strictly greater than `credit_limit_usd` and returns to `ACTIVE` when it is at
    or below the limit, so an exposure landing exactly on the limit keeps the
    account in good standing."

    Design: Corner/endpoints/patch_customer_applies_only_supplied_fields_and_reevaluates_credit
    """
    world, lot, reel, shipment = setup_invoiced_shipment(api)
    before = read_customer(api, world["customer"]["id"])
    assert before["credit_exposure_usd"] == pytest.approx(994.58, abs=0.01), (
        "544.58 of invoiced receivable plus a 450.00 deposit still outstanding"
    )
    assert before["status"] == "ACTIVE"

    first = validate_success(
        api.patch_customer(
            world["customer"]["id"], {"credit_limit_usd": 500.00}, BILLING
        ),
        200,
    )
    assert first["credit_limit_usd"] == pytest.approx(500.00, abs=0.01)
    assert first["credit_exposure_usd"] == pytest.approx(994.58, abs=0.01), (
        "the ledger did not move, only the comparison flipped"
    )
    assert first["status"] == "CREDIT_HOLD"
    assert first["version"] == before["version"] + 1, "a partial update is still a write"
    assert first["pass_through_enabled"] is True, "an unnamed election is untouched"
    assert first["reel_program"] == "RETURNABLE"
    assert first["account_code"] == before["account_code"]
    assert first["name"] == before["name"]
    assert first["market_region"] == before["market_region"]

    second = validate_success(
        api.patch_customer(
            world["customer"]["id"], {"pass_through_enabled": False}, BILLING
        ),
        200,
    )
    assert second["pass_through_enabled"] is False
    assert second["credit_limit_usd"] == pytest.approx(500.00, abs=0.01), (
        "naming one field must not resurrect the previous limit"
    )
    assert second["status"] == "CREDIT_HOLD", "and it must not clear the hold"

    third = validate_success(
        api.patch_customer(
            world["customer"]["id"],
            {"credit_limit_usd": 100000.00, "reel_program": "NON_RETURNABLE"},
            ADMIN,
        ),
        200,
    )
    assert third["credit_limit_usd"] == pytest.approx(100000.00, abs=0.01)
    assert third["reel_program"] == "NON_RETURNABLE"
    assert third["status"] == "ACTIVE", "994.58 is comfortably under the restored limit"
    assert third["pass_through_enabled"] is False, (
        "the flag stays where the previous adjustment left it"
    )
