"""Error precedence at sale completion: the recall safety block is evaluated
before the trade-in band check, so a completion that violates both returns the
recall error.
"""
from test_helpers import TEST_USERS, recall_product, setup_reserved_sales_order, validate_error, validate_success

SA = TEST_USERS["sales_associate_headers"]


def test_recalled_product_error_returned_over_trade_in_band(api):
    """PRD §3.3: "It is blocked when the reserved unit's product is `RECALLED`, in
    which case it fails with `ERR_PRODUCT_RECALLED`."
    PRD §3.3: "the final figure must fall within 15,000 cents of the provisional
    estimate — that is, the absolute difference between `trade_in_final_cents` and
    `trade_in_estimate_cents` must be at most 15,000 cents — otherwise completion is
    rejected with `ERR_TRADE_IN_OUT_OF_BAND`."

    Design: Difficulty/priority_pair_validation_conflict/sale_recall_safety_beats_tradein_band
    """
    _cust, prod, _item, so = setup_reserved_sales_order(
        credit=0, sale_price_cents=100000,
        trade_in_model="Old Kenmore", trade_in_condition="GOOD",
    )
    recall_product(prod["id"], "Fire hazard")
    # trade_in_final 99000 vs estimate 40000 -> |delta| 59000 > 15000 (also out of band).
    res = api.complete_sales_order(so["id"], {"trade_in_final_cents": 99000}, SA)
    validate_error(res, "ERR_PRODUCT_RECALLED", expected_status=409)


def test_recall_and_band_conflict_leaves_order_reserved(api):
    """PRD §3.3: "Completion requires the order to be `RESERVED`, else
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/sale_recall_safety_beats_tradein_band
    """
    _cust, prod, _item, so = setup_reserved_sales_order(
        credit=0, sale_price_cents=100000,
        trade_in_model="Old Kenmore", trade_in_condition="GOOD",
    )
    recall_product(prod["id"], "Fire hazard")
    api.complete_sales_order(so["id"], {"trade_in_final_cents": 99000}, SA)
    after = validate_success(api.get_sales_order(so["id"], SA), 200)
    assert after["status"] == "RESERVED"
