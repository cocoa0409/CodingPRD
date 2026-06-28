"""Business-rule validations, deterministic error precedence, cross-entity
state guards, and boundary-precision checks.

Covers Difficulty queue rules priority_pair_validation_conflict,
boundary_precision_check, and cross_entity_state_dependency, plus the Corner
queue validations section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_vendor, create_product, create_account,
    create_order_with_line, setup_placed_order, create_station, book_ticket,
    create_special_order, create_rental_asset, create_reservation,
    setup_invoiced_order, create_draft_po, setup_submitted_po, set_clock,
    api_client, SALES, INVENTORY, ACCOUNTS, RENTAL,
    make_contractor_headers,
)


# ─── Difficulty: priority_pair_validation_conflict ──────────────────────────

def test_cancel_invoiced_order_reports_already_billed(api):
    """PRD 3.5: "The billing guard comes first: an order may only be cancelled
    while its `payment_status` is `UNBILLED`; a cancel attempt on an order that
    has been invoiced, paid, or voided is rejected with
    `ERR_ORDER_ALREADY_BILLED`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_already_billed_beats_credit_check
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    invoiced = setup_invoiced_order(product["id"], qty=10,
                                    contractor_account_id=account["id"])
    res = api.cancel_order(invoiced["id"], SALES)
    validate_error(res, "ERR_ORDER_ALREADY_BILLED")


def test_cancel_paid_order_reports_already_billed(api):
    """PRD 3.5: "an order may only be cancelled while its payment_status is
    UNBILLED; a cancel attempt on an order that has been invoiced, paid, or
    voided is rejected with ERR_ORDER_ALREADY_BILLED."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_already_billed_beats_credit_check
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    invoiced = setup_invoiced_order(product["id"], qty=10,
                                    contractor_account_id=account["id"])
    validate_success(api.pay_order(invoiced["id"], ACCOUNTS), 200)
    res = api.cancel_order(invoiced["id"], SALES)
    validate_error(res, "ERR_ORDER_ALREADY_BILLED")


def test_offline_station_beats_uncertified_cylinder(api):
    """PRD 3.8: "Starting a ticket advances it from BOOKED to IN_PROGRESS. The
    station must be ACTIVE, or the start is rejected with ERR_STATION_OFFLINE."
    PRD 3.11: "Where a single operation could trip more than one of these, the
    earlier-listed condition surfaces first."

    Design: Difficulty/priority_pair_validation_conflict/state_offline_station_beats_safety_uncertified_cylinder
    """
    station = create_station(buffer_minutes=0)
    ticket = book_ticket(station["id"], "PROPANE_EXCHANGE",
                         "2026-02-01T09:00:00Z", "2026-02-01T09:30:00Z",
                         cylinder_certified=False)
    validate_success(api.set_offline(station["id"], {"offline": True}, INVENTORY), 200)
    res = api.start_ticket(ticket["id"], SALES)
    # Station-offline (state) precedes propane safety; ERR_STATION_OFFLINE wins.
    validate_error(res, "ERR_STATION_OFFLINE")

    tk = validate_success(api.get_service_ticket(ticket["id"], SALES), 200)
    assert tk["status"] == "BOOKED", "start rejected, ticket unchanged"
    assert tk["fee_cents"] == 0, "no fee computed"


def test_uncertified_cylinder_surfaces_once_station_active(api):
    """PRD 3.8: "a ticket whose service_type is PROPANE_EXCHANGE may only start
    when its cylinder_certified is true; otherwise the start is rejected with
    ERR_CYLINDER_NOT_CERTIFIED."
    PRD 3.8: "The station must be ACTIVE, or the start is rejected with
    ERR_STATION_OFFLINE."

    Design: Difficulty/priority_pair_validation_conflict/state_offline_station_beats_safety_uncertified_cylinder
    """
    station = create_station(buffer_minutes=0)
    ticket = book_ticket(station["id"], "PROPANE_EXCHANGE",
                         "2026-02-01T09:00:00Z", "2026-02-01T09:30:00Z",
                         cylinder_certified=False)
    validate_success(api.set_offline(station["id"], {"offline": True}, INVENTORY), 200)
    # While OFFLINE the station check pre-empts the safety check.
    validate_error(api.start_ticket(ticket["id"], SALES), "ERR_STATION_OFFLINE")
    # Bring the station back ACTIVE; now only the propane safety check can fail.
    validate_success(api.set_offline(station["id"], {"offline": False}, INVENTORY), 200)
    res = api.start_ticket(ticket["id"], SALES)
    validate_error(res, "ERR_CYLINDER_NOT_CERTIFIED")


# ─── Difficulty: boundary_precision_check ───────────────────────────────────

def test_reorder_flag_inclusive_at_reorder_point(api):
    """PRD 2.8: "it is set true exactly when on_hand is at or below the
    product's reorder_point (the comparison is inclusive — equal to the reorder
    point counts as needing reorder), and false otherwise."

    Design: Difficulty/boundary_precision_check/reorder_flag_at_exact_reorder_point_inclusive
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=500, reorder_point=5,
                             reorder_qty=20, on_hand=6)
    at6 = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert at6["on_hand"] == 6
    assert at6["reorder_needed"] is False, "6 > reorder_point 5"

    at5 = validate_success(api.adjust_stock(product["id"], {"delta": -1}, INVENTORY), 200)
    assert at5["on_hand"] == 5
    assert at5["reorder_needed"] is True, "5 == reorder_point 5 (inclusive)"


def test_reorder_flag_false_above_reorder_point(api):
    """PRD 2.8: "A restock that lifts stock back above the reorder point
    therefore clears the flag."
    PRD 2.8: "it is set true exactly when on_hand is at or below the product's
    reorder_point ... and false otherwise."

    Design: Difficulty/boundary_precision_check/reorder_flag_at_exact_reorder_point_inclusive
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=500, reorder_point=5,
                             reorder_qty=20, on_hand=6)
    prod = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert prod["reorder_needed"] is False, "reorder_point+1 (6) keeps it false"


def test_place_empty_order_rejected(api):
    """PRD 3.3: "The order must hold at least one line in PENDING status; an
    order with no pending lines is rejected as ERR_EMPTY_ORDER."

    Design: Difficulty/boundary_precision_check/empty_order_place_zero_lines_rejected
    """
    order = validate_success(api.create_sales_order({}, SALES), 201)
    res = api.place_order(
        order["id"], {"expected_sales_order_version": order["version"]}, SALES)
    validate_error(res, "ERR_EMPTY_ORDER")


def test_place_order_with_one_line_succeeds_boundary(api):
    """PRD 3.3: "The order must hold at least one line in PENDING status."
    PRD 3.3: "A SalesAssociate triggers the placement, which advances
    fulfillment_status from DRAFT to PLACED while pricing_mode remains
    PROVISIONAL."

    Design: Difficulty/boundary_precision_check/empty_order_place_zero_lines_rejected
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    order, _ = create_order_with_line(product["id"], qty=1)
    placed = validate_success(api.place_order(
        order["id"], {"expected_sales_order_version": order["version"]}, SALES), 200)
    assert placed["fulfillment_status"] == "PLACED", "1 PENDING line clears the boundary"


# ─── Difficulty: cross_entity_state_dependency ──────────────────────────────

def test_fulfill_blocked_by_discontinued_product(api):
    """PRD 3.4: "Every line's product must still be ACTIVE, or the transition
    fails with ERR_PRODUCT_DISCONTINUED."

    Design: Difficulty/cross_entity_state_dependency/order_fulfill_blocked_by_discontinued_product
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    placed = setup_placed_order(product["id"], qty=10)
    validate_success(api.discontinue_product(product["id"], INVENTORY), 200)
    res = api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES)
    validate_error(res, "ERR_PRODUCT_DISCONTINUED")


def test_fulfill_succeeds_while_product_active(api):
    """PRD 3.4: "Every line's product must still be ACTIVE, or the transition
    fails with ERR_PRODUCT_DISCONTINUED."
    PRD 3.4: "A SalesAssociate triggers it, advancing fulfillment_status from
    PLACED to FULFILLED."

    Design: Difficulty/cross_entity_state_dependency/order_fulfill_blocked_by_discontinued_product
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    placed = setup_placed_order(product["id"], qty=10)
    # Product is left ACTIVE; the cross-entity guard passes and fulfill proceeds.
    fulfilled = validate_success(api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES), 200)
    assert fulfilled["fulfillment_status"] == "FULFILLED"


def test_checkout_blocked_by_maintenance_asset(api):
    """PRD 3.7: "The asset must be AVAILABLE at checkout, or the request is
    rejected with ERR_ASSET_UNAVAILABLE."
    PRD 3.7: "a true value moves status to MAINTENANCE (a state from which the
    asset cannot be reserved)."

    Design: Difficulty/cross_entity_state_dependency/rental_checkout_blocked_by_maintenance_asset
    """
    asset = create_rental_asset(daily_rate_cents=4500, deposit_cents=10000)
    agreement = create_reservation(
        asset["id"], "2026-02-01T08:00:00Z", "2026-02-03T08:00:00Z")
    validate_success(api.set_maintenance(asset["id"], {"maintenance": True}, RENTAL), 200)
    set_clock("2026-02-01T09:00:00Z")
    res = api.check_out_rental(agreement["id"], RENTAL)
    validate_error(res, "ERR_ASSET_UNAVAILABLE")


def test_checkout_succeeds_when_asset_available(api):
    """PRD 3.7: "The asset must be AVAILABLE at checkout, or the request is
    rejected with ERR_ASSET_UNAVAILABLE."
    PRD 3.7: "Checking out a reserved agreement advances it from RESERVED to
    CHECKED_OUT. ... On checkout the asset's status moves to RENTED."

    Design: Difficulty/cross_entity_state_dependency/rental_checkout_blocked_by_maintenance_asset
    """
    asset = create_rental_asset(daily_rate_cents=4500, deposit_cents=10000)
    agreement = create_reservation(
        asset["id"], "2026-02-01T08:00:00Z", "2026-02-03T08:00:00Z")
    # Asset stays AVAILABLE; once the clock reaches start_at, checkout proceeds.
    set_clock("2026-02-01T09:00:00Z")
    checked_out = validate_success(api.check_out_rental(agreement["id"], RENTAL), 200)
    assert checked_out["status"] == "CHECKED_OUT"


# ─── Corner: validations ────────────────────────────────────────────────────

def test_insufficient_stock_blocks_fulfill(api):
    """PRD 3.4: "For each PENDING line, the line's product must have on_hand at
    least equal to the line's qty; if any line cannot be covered, the
    fulfillment is rejected with ERR_INSUFFICIENT_STOCK."

    Design: Corner/validations/insufficient_stock_blocks_fulfill
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=5)
    placed = setup_placed_order(product["id"], qty=10)  # qty 10 > on_hand 5
    res = api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")

    prod = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert prod["on_hand"] == 5, "unchanged after rejected fulfill"


def test_suspended_account_blocks_place(api):
    """PRD 3.3: "If the order names a contractor account, that account's status
    must be ACTIVE; placing against a SUSPENDED account is rejected with
    ERR_ACCOUNT_SUSPENDED."

    Design: Corner/validations/suspended_account_blocks_place
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    validate_success(api.suspend_account(account["id"], ACCOUNTS), 200)
    order, _ = create_order_with_line(product["id"], qty=5,
                                      contractor_account_id=account["id"])
    res = api.place_order(
        order["id"], {"expected_sales_order_version": order["version"]}, SALES)
    validate_error(res, "ERR_ACCOUNT_SUSPENDED")


def test_offline_station_blocks_ticket_start(api):
    """PRD 3.8: "Starting a ticket advances it from BOOKED to IN_PROGRESS. The
    station must be ACTIVE, or the start is rejected with ERR_STATION_OFFLINE."

    Design: Corner/validations/offline_station_blocks_ticket_start
    """
    station = create_station(buffer_minutes=0)
    ticket = book_ticket(station["id"], "KEY_CUT",
                         "2026-07-02T09:00:00Z", "2026-07-02T09:10:00Z")
    validate_success(api.set_offline(station["id"], {"offline": True}, INVENTORY), 200)
    res = api.start_ticket(ticket["id"], SALES)
    validate_error(res, "ERR_STATION_OFFLINE")


def test_purchase_order_inactive_vendor_blocks_submit(api):
    """PRD 3.10: "The vendor must be ACTIVE, or the submit is rejected with
    ERR_VENDOR_INACTIVE; that same error also rejects a submit whose lines
    reference a product not supplied by the vendor."

    Design: Corner/validations/purchase_order_inactive_vendor_blocks_submit
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000)
    po = create_draft_po(vendor["id"],
                        [{"product_id": product["id"], "qty": 10,
                          "unit_cost_cents": 500}])
    validate_success(api.deactivate_vendor(vendor["id"], INVENTORY), 200)
    res = api.submit_purchase_order(po["id"], INVENTORY)
    validate_error(res, "ERR_VENDOR_INACTIVE")


def test_empty_purchase_order_submit_rejected(api):
    """PRD 3.10: "The lines array must be non-empty, or the submit is rejected
    with ERR_EMPTY_PURCHASE_ORDER."

    Design: Corner/validations/empty_purchase_order_submit_rejected
    """
    vendor = create_vendor()
    po = create_draft_po(vendor["id"], [])
    res = api.submit_purchase_order(po["id"], INVENTORY)
    validate_error(res, "ERR_EMPTY_PURCHASE_ORDER")


def test_special_order_quote_non_drop_ship_vendor_rejected(api):
    """PRD 3.9: "in both cases the vendor must be ACTIVE and have
    drop_ship_capable true, or the quote is rejected with
    ERR_VENDOR_NOT_DROP_SHIP."

    Design: Corner/validations/special_order_quote_non_drop_ship_vendor_rejected
    """
    vendor = create_vendor(drop_ship_capable=False)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    so = create_special_order(vendor["id"], account["id"], qty=1)
    res = api.quote_special_order(so["id"], {"quoted_unit_cents": 5000}, SALES)
    validate_error(res, "ERR_VENDOR_NOT_DROP_SHIP")
