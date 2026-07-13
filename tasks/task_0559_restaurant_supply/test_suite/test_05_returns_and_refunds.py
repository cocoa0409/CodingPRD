"""Returns lifecycle: sealed-vs-opened restock/refund, approve→revise revert, receive
restock cascade, return-window and referential guards, and refund crediting the account.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_buyer_headers,
    fixtures,
)

AM = TEST_USERS["account_manager_headers"]
WH = TEST_USERS["warehouse_headers"]


# --------------------------------------------------------------------------- #
# dual_variant_calc / restock_sealed_vs_opened_on_rma
# --------------------------------------------------------------------------- #
def _rma_requested_sealed_plate_opened_cup(api):
    acct = fixtures.create_account(api)
    plate = fixtures.create_product(api, sku="PLATE-1", name="Dinner Plate", unit_price_cents=800,
                                    case_qty=100, case_price_cents=70000, pallet_case_qty=10,
                                    pallet_price_cents=650000, par_level=200, reorder_point=10)
    cup = fixtures.create_product(api, sku="CUP-1", name="Coffee Cup", unit_price_cents=800,
                                  case_qty=100, case_price_cents=70000, pallet_case_qty=10,
                                  pallet_price_cents=650000, par_level=200, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], plate["id"], 4)
    fixtures.add_line(api, order["id"], acct["id"], cup["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = fixtures.create_shipment(api, order["id"])
    fixtures.book_shipment(api, ship["id"])
    fixtures.deliver_shipment(api, ship["id"])
    ret = fixtures.open_return(api, order["id"], acct["id"], reason="Damaged in transit")
    fixtures.add_return_line(api, ret["id"], acct["id"], plate["id"], 4, "SEALED")
    fixtures.add_return_line(api, ret["id"], acct["id"], cup["id"], 4, "OPENED")
    return acct, ret


def test_approve_sums_sealed_and_opened_restock_fees(api):
    """PRD §3.8: "the restock percentage is 15 percent when the `condition` is `SEALED` and 25
    percent when it is `OPENED`; the line's restock fee is that merchandise value multiplied by the
    percentage, rounded half-up to whole cents; and the line's `line_refund_cents` is the
    merchandise value minus that restock fee."

    Design: Difficulty/dual_variant_calc/restock_sealed_vs_opened_on_rma
    """
    _acct, ret = _rma_requested_sealed_plate_opened_cup(api)
    approved = validate_success(api.approve_return(ret["id"], WH))
    # SEALED 4*800=3200 -> fee 480; OPENED 4*800=3200 -> fee 800; sum 1280
    assert approved["restock_fee_cents"] == 1280
    assert approved["status"] == "APPROVED"


def test_approve_sums_sealed_and_opened_refunds(api):
    """PRD §3.8: "The return's `restock_fee_cents` is the sum of the per-line restock fees and its
    `refund_cents` is the sum of the per-line refunds, after which it moves `REQUESTED → APPROVED`."

    Design: Difficulty/dual_variant_calc/restock_sealed_vs_opened_on_rma
    """
    _acct, ret = _rma_requested_sealed_plate_opened_cup(api)
    approved = validate_success(api.approve_return(ret["id"], WH))
    # refunds 2720 (sealed) + 2400 (opened) = 5120
    assert approved["refund_cents"] == 5120


# --------------------------------------------------------------------------- #
# non_linear_state_machine / rma_approved_revert_to_requested
# --------------------------------------------------------------------------- #
def _approved_rma_single_sealed_plate(api):
    acct = fixtures.create_account(api)
    plate = fixtures.create_product(api, sku="PLATE-2", name="Salad Plate", unit_price_cents=800,
                                    case_qty=100, case_price_cents=70000, pallet_case_qty=10,
                                    pallet_price_cents=650000, par_level=200, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], plate["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = fixtures.create_shipment(api, order["id"])
    fixtures.book_shipment(api, ship["id"])
    fixtures.deliver_shipment(api, ship["id"])
    ret = fixtures.open_return(api, order["id"], acct["id"], reason="Wrong item")
    fixtures.add_return_line(api, ret["id"], acct["id"], plate["id"], 4, "SEALED")
    fixtures.approve_return(api, ret["id"])
    return acct, ret


def test_revise_returns_rma_to_requested(api):
    """PRD §3.8: "An approved return can be sent back for revision by `WarehouseOps`, which requires
    it to be `APPROVED` (otherwise `ERR_RETURN_NOT_APPROVED`) and reverts the computed figures".

    Design: Difficulty/non_linear_state_machine/rma_approved_revert_to_requested
    """
    _acct, ret = _approved_rma_single_sealed_plate(api)
    revised = validate_success(api.revise_return(ret["id"], WH))
    assert revised["status"] == "REQUESTED"


def test_revise_zeroes_refund_and_restock_figures(api):
    """PRD §3.8: "reverts the computed figures — the return's `refund_cents` and `restock_fee_cents`
    and each line's `line_refund_cents` are all reset to 0 — as it cycles `APPROVED → REQUESTED`."

    Design: Difficulty/non_linear_state_machine/rma_approved_revert_to_requested
    """
    _acct, ret = _approved_rma_single_sealed_plate(api)
    revised = validate_success(api.revise_return(ret["id"], WH))
    assert revised["refund_cents"] == 0
    assert revised["restock_fee_cents"] == 0


# --------------------------------------------------------------------------- #
# transitive_cascade / rma_receive_restocks_clears_reorder
# --------------------------------------------------------------------------- #
def _received_ready_rma_frypan(api):
    """FRYPAN on_hand 8, reorder_point 5, par 12; order 4 (on_hand -> 4, needs_reorder true);
    RMA APPROVED with a SEALED line of 4."""
    acct = fixtures.create_account(api)
    pan = fixtures.create_product(api, sku="FRYPAN-1", name="Fry Pan", unit_price_cents=1500,
                                  case_qty=100, case_price_cents=130000, pallet_case_qty=10,
                                  pallet_price_cents=1200000, weight_lbs_per_unit=3,
                                  on_hand_qty=8, par_level=12, reorder_point=5)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], pan["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = fixtures.create_shipment(api, order["id"], carrier="FEDEX")
    fixtures.book_shipment(api, ship["id"])
    fixtures.deliver_shipment(api, ship["id"])
    ret = fixtures.open_return(api, order["id"], acct["id"], reason="Overstock")
    rline = fixtures.add_return_line(api, ret["id"], acct["id"], pan["id"], 4, "SEALED")
    fixtures.approve_return(api, ret["id"])
    return acct, pan, ret, rline


def test_receive_restocks_product_and_marks_line_received(api):
    """PRD §3.8: "Receiving an approved return requires the `APPROVED` state (otherwise
    `ERR_RETURN_NOT_APPROVED`) and restocks inventory: each line moves to `RECEIVED` and the
    product's `on_hand_qty` is increased by that line's `quantity`".

    Design: Difficulty/transitive_cascade/rma_receive_restocks_clears_reorder
    """
    _acct, pan, ret, rline = _received_ready_rma_frypan(api)
    validate_success(api.receive_return(ret["id"], WH))
    rline_after = validate_success(api.get_return_line(rline["id"], WH))
    pan_after = validate_success(api.get_product(pan["id"], WH))
    assert rline_after["status"] == "RECEIVED"
    assert pan_after["on_hand_qty"] == 8  # 4 remaining + 4 restocked


def test_receive_restock_clears_reorder_flag(api):
    """PRD §3.3: "The `needs_reorder` flag is true exactly when `on_hand_qty` is less than or equal
    to `reorder_point`."

    Design: Difficulty/transitive_cascade/rma_receive_restocks_clears_reorder
    """
    _acct, pan, ret, _rline = _received_ready_rma_frypan(api)
    validate_success(api.receive_return(ret["id"], WH))
    pan_after = validate_success(api.get_product(pan["id"], WH))
    assert pan_after["needs_reorder"] is False  # 8 > reorder_point 5


# --------------------------------------------------------------------------- #
# validations / return_window_expired_rejected (corner)
# --------------------------------------------------------------------------- #
def test_open_return_after_window_expired_rejected(api):
    """PRD §3.8: "the return may be opened only within 30 days of the order's shipment
    `delivered_at`, and a later attempt is rejected with `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_window_expired_rejected
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="WN-1", name="Spatula", unit_price_cents=400,
                                   case_qty=100, case_price_cents=36000, pallet_case_qty=10,
                                   pallet_price_cents=340000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = fixtures.create_shipment(api, order["id"])
    fixtures.book_shipment(api, ship["id"])
    fixtures.deliver_shipment(api, ship["id"])
    fixtures.set_clock(api, "2026-06-15T00:00:00Z")  # > 30 days after delivery
    resp = api.create_return(order["id"], {"reason": "Too late"}, make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value)


# --------------------------------------------------------------------------- #
# validations / return_line_product_not_in_order_rejected (corner)
# --------------------------------------------------------------------------- #
def test_return_line_for_unordered_product_rejected(api):
    """PRD §3.8: "the product must appear on the original order (otherwise
    `ERR_PRODUCT_NOT_IN_ORDER`)".

    Design: Corner/validations/return_line_product_not_in_order_rejected
    """
    acct = fixtures.create_account(api)
    a = fixtures.create_product(api, sku="A-1", name="Product A", unit_price_cents=500,
                                case_qty=100, case_price_cents=45000, pallet_case_qty=10,
                                pallet_price_cents=420000, par_level=50)
    b = fixtures.create_product(api, sku="B-1", name="Product B", unit_price_cents=500,
                                case_qty=100, case_price_cents=45000, pallet_case_qty=10,
                                pallet_price_cents=420000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], a["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = fixtures.create_shipment(api, order["id"])
    fixtures.book_shipment(api, ship["id"])
    fixtures.deliver_shipment(api, ship["id"])
    ret = fixtures.open_return(api, order["id"], acct["id"], reason="Wrong product")
    resp = api.add_return_line(ret["id"], {"product_id": b["id"], "quantity": 1, "condition": "SEALED"},
                               make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_IN_ORDER.value)


# --------------------------------------------------------------------------- #
# validations / return_qty_exceeds_ordered_rejected (corner)
# --------------------------------------------------------------------------- #
def test_return_quantity_over_ordered_rejected(api):
    """PRD §3.8: "the returned `quantity` must not exceed the quantity that was ordered for that
    product on the original order (otherwise `ERR_RETURN_QTY_EXCEEDS_ORDERED`)".

    Design: Corner/validations/return_qty_exceeds_ordered_rejected
    """
    acct = fixtures.create_account(api)
    a = fixtures.create_product(api, sku="QA-1", name="Colander", unit_price_cents=600,
                                case_qty=100, case_price_cents=55000, pallet_case_qty=10,
                                pallet_price_cents=520000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], a["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = fixtures.create_shipment(api, order["id"])
    fixtures.book_shipment(api, ship["id"])
    fixtures.deliver_shipment(api, ship["id"])
    ret = fixtures.open_return(api, order["id"], acct["id"], reason="Too many")
    resp = api.add_return_line(ret["id"], {"product_id": a["id"], "quantity": 5, "condition": "SEALED"},
                               make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_ORDERED.value)


# --------------------------------------------------------------------------- #
# state_machines / open_return_on_undelivered_order_returns_not_completed (corner)
# --------------------------------------------------------------------------- #
def test_open_return_on_confirmed_order_rejected(api):
    """PRD §3.8: "Opening a return requires the order to be in `COMPLETED` (delivered) state,
    otherwise `ERR_ORDER_NOT_COMPLETED`".

    Design: Corner/state_machines/open_return_on_undelivered_order_returns_not_completed
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="RET-1", name="Tongs", unit_price_cents=400,
                                   case_qty=12, case_price_cents=4200, pallet_case_qty=10,
                                   pallet_price_cents=40000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 3)
    fixtures.confirm_order(api, order["id"], acct["id"])
    resp = api.create_return(order["id"], {"reason": "Change of mind"}, make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_COMPLETED.value)


# --------------------------------------------------------------------------- #
# cross_cutting / rma_refund_credits_account_outstanding (corner)
# --------------------------------------------------------------------------- #
def test_refund_credits_account_outstanding(api):
    """PRD §3.8: "refunding a received return requires the `RECEIVED` state (otherwise
    `ERR_RETURN_NOT_RECEIVED`) and moves it `RECEIVED → REFUNDED`, at which point the owning
    account's outstanding and available credit are recomputed so that the return's `refund_cents`
    is credited against the outstanding balance."

    Design: Corner/cross_cutting_complexity_layers/rma_refund_credits_account_outstanding
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="REF-1", name="Storage Bin", unit_price_cents=1000,
                                   case_qty=100, case_price_cents=90000, pallet_case_qty=10,
                                   pallet_price_cents=850000, weight_lbs_per_unit=1, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = fixtures.create_shipment(api, order["id"])
    fixtures.book_shipment(api, ship["id"])
    fixtures.deliver_shipment(api, ship["id"])
    ret = fixtures.open_return(api, order["id"], acct["id"], reason="One damaged")
    fixtures.add_return_line(api, ret["id"], acct["id"], prod["id"], 1, "SEALED")
    fixtures.approve_return(api, ret["id"])
    fixtures.receive_return(api, ret["id"])
    refunded = validate_success(api.refund_return(ret["id"], WH))
    acct_after = validate_success(api.get_account(acct["id"], WH))
    assert refunded["status"] == "REFUNDED"
    assert refunded["refund_cents"] == 850
    # order total 3460 (2000 + 160 tax + 1300 parcel freight); minus 850 refund = 2610
    assert acct_after["outstanding_cents"] == 2610
