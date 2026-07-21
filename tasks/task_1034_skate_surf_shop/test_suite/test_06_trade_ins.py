"""Trade-ins and consignment: offers, payouts, and RBAC.

Difficulty instance: tradein_cash_vs_store_credit_offers. Corner instances:
tradein_accept_store_credit_payout, consignor_credit_on_consignment_sale,
customer_cannot_appraise_tradein_forbidden.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer_headers,
)
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: dual-variant trade-in offers (cash 50% vs store credit 70%)
# --------------------------------------------------------------------------- #
def test_appraise_computes_both_cash_and_store_credit_offers(api):
    """PRD §3.7: "Appraisal moves the record to `APPRAISED`, stores the appraised value, and computes both standing offers from it: the `cash_offer_cents` is the appraised value multiplied by 0.50 and rounded half up to whole cents, and the `store_credit_offer_cents` is the appraised value multiplied by 0.70 and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/tradein_cash_vs_store_credit_offers
    """
    customer = th.create_customer(api, email="ti1@x.com", full_name="Trade One")
    ti = th.create_trade_in(api, customer["id"], mode="TRADE_IN", item_description="Used deck")
    resp = api.appraise_trade_in(ti["id"], {"appraised_value_cents": 20000}, SM)
    data = validate_success(resp, expected_status=200)
    assert data["cash_offer_cents"] == 10000
    assert data["store_credit_offer_cents"] == 14000
    assert data["status"] == "APPRAISED"


def test_store_credit_offer_exceeds_cash_offer_for_same_appraisal(api):
    """PRD §3.7: "The store-credit offer is deliberately the more generous of the two for identical appraised input."

    Design: Difficulty/dual_variant_calc/tradein_cash_vs_store_credit_offers
    """
    customer, ti = th.setup_appraised_trade_in(api, 20000, mode="TRADE_IN")
    assert ti["store_credit_offer_cents"] != ti["cash_offer_cents"]
    assert ti["store_credit_offer_cents"] > ti["cash_offer_cents"]


# --------------------------------------------------------------------------- #
# Corner: accept TRADE_IN with STORE_CREDIT payout
# --------------------------------------------------------------------------- #
def test_accept_trade_in_store_credit_credits_customer(api):
    """PRD §3.7: "For a `TRADE_IN`, acceptance requires a `payout_choice` of either `CASH` or `STORE_CREDIT` and moves the record to `ACCEPTED`; if the choice is `STORE_CREDIT`, the member's `store_credit_cents` is increased by the `store_credit_offer_cents`, whereas a `CASH` choice pays out externally and adds no store credit."

    Design: Corner/calculations/tradein_accept_store_credit_payout
    """
    customer, ti = th.setup_appraised_trade_in(api, 20000, mode="TRADE_IN")
    assert ti["store_credit_offer_cents"] == 14000
    resp = api.accept_trade_in(ti["id"], {"payout_choice": "STORE_CREDIT"},
                               make_customer_headers(customer["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "ACCEPTED"
    customer_read = validate_success(api.get_customer(customer["id"], SA))
    assert customer_read["store_credit_cents"] == 14000


# --------------------------------------------------------------------------- #
# Corner: consignment sale grants consignor credit
# --------------------------------------------------------------------------- #
def test_consignment_sale_grants_consignor_credit(api):
    """PRD §3.7: "The record moves to `SOLD`, the consignor credit is computed as the `sold_price_cents` multiplied by 0.60 and rounded half up to whole cents, and that `consignor_credit_cents` is added to the member's `store_credit_cents`."

    Design: Corner/calculations/consignor_credit_on_consignment_sale
    """
    customer, ti = th.setup_listed_consignment(api, appraised_value_cents=12000, list_price_cents=15000)
    resp = api.sell_trade_in(ti["id"], {"sold_price_cents": 10000}, SM)
    data = validate_success(resp, expected_status=200)
    assert data["consignor_credit_cents"] == 6000  # round(10000 * 0.60)
    assert data["status"] == "SOLD"
    customer_read = validate_success(api.get_customer(customer["id"], SA))
    assert customer_read["store_credit_cents"] == 6000


# --------------------------------------------------------------------------- #
# Corner: RBAC — Customer cannot appraise
# --------------------------------------------------------------------------- #
def test_customer_cannot_appraise_trade_in(api):
    """PRD §3.7: "A `ShopManager` appraises a received item by supplying its `appraised_value_cents`, which requires the record to be `RECEIVED`, else `ERR_TRADE_IN_INVALID_STATE`."
    PRD §2.1: "If the headers are present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_appraise_tradein_forbidden
    """
    customer = th.create_customer(api, email="rd@x.com", full_name="Role Denied")
    ti = th.create_trade_in(api, customer["id"], mode="TRADE_IN", item_description="Old wetsuit")
    resp = api.appraise_trade_in(ti["id"], {"appraised_value_cents": 5000},
                                 make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    reread = validate_success(api.get_trade_in(ti["id"], SA))
    assert reread["status"] == "RECEIVED"
