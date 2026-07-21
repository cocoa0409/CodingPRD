"""Sale order totals, confirmation cascade, confirm-time validations and priority."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_sale_order_payload, line_item, TEST_USERS,
)
from test_helpers.fixtures import (
    new_patron, make_appraised_book, make_listed_book, setup_consigned_shelved,
    setup_confirmed_consigned_sale, draft_shop_order, make_empty_sale_order,
    create_consignment_agreement_payload,
)
from test_helpers.api_client import api_client

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["storeclerk_headers"]


def _listing_for_book(api, book_id):
    data = validate_success(api.get_listing(book_id, MANAGER), 200)
    assert isinstance(data, list) and len(data) == 1
    return data[0]


# ── order_total (round per line then sum) ───────────────────────────────────

def test_order_subtotal_rounds_each_line_before_sum(api):
    """PRD §3.8: "The `subtotal_cents` is the sum of these already-rounded per-line
    amounts — the amounts are rounded before they are summed, never after."

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_mode_b
    """
    b1 = make_listed_book(condition_grade="GOOD", list_price_cents=505, comp_median_cents=1000, title="Line One")
    b2 = make_listed_book(condition_grade="GOOD", list_price_cents=515, comp_median_cents=1000, title="Line Two")
    payload = create_sale_order_payload("SHOP", [
        line_item(b1["book"]["id"], 505, discount_pct=0),
        line_item(b2["book"]["id"], 515, discount_pct=0),
    ], tax_pct=0.08)
    order = validate_success(api.create_sale_order(payload, CLERK), 201)
    assert order["subtotal_cents"] == 1101


def test_order_total_equals_subtotal_without_credit(api):
    """PRD §3.8: "The `total_cents` is the `subtotal_cents` less the
    `store_credit_applied_cents`, floored at 0 so it is never negative."

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_mode_b
    """
    b1 = make_listed_book(condition_grade="GOOD", list_price_cents=505, comp_median_cents=1000, title="Line One")
    b2 = make_listed_book(condition_grade="GOOD", list_price_cents=515, comp_median_cents=1000, title="Line Two")
    payload = create_sale_order_payload("SHOP", [
        line_item(b1["book"]["id"], 505, discount_pct=0),
        line_item(b2["book"]["id"], 515, discount_pct=0),
    ], tax_pct=0.08)
    order = validate_success(api.create_sale_order(payload, CLERK), 201)
    assert order["total_cents"] == 1101


# ── depth-3 confirmation cascade ─────────────────────────────────────────────

def test_confirm_cascades_book_and_listing_to_sold(api):
    """PRD §3.8: "each line's book transitions from `LISTED` to `SOLD`; each newly
    sold book pulls its catalog listing's sold axis to `SOLD` according to the order
    channel (settling the other axis to `PULLED` or `DELISTED` as described in §3.4)".
    PRD §3.4: "a confirmed shop sale sets `shop_status` to `SOLD`, records
    `sold_channel` as `SHOP`, and sets `online_status` to `DELISTED` so the online
    copy is withdrawn."

    Design: Difficulty/transitive_cascade/sale_confirm_depth3_book_listing_agreement_payable
    """
    ctx = setup_confirmed_consigned_sale(sale_price_cents=30000, comp_median_cents=20000)
    book = validate_success(api.get_book_item(ctx["book"]["id"], MANAGER), 200)
    assert book["status"] == "SOLD"
    listing = _listing_for_book(api, ctx["book"]["id"])
    assert listing["shop_status"] == "SOLD"
    assert listing["online_status"] == "DELISTED"
    assert listing["sold_channel"] == "SHOP"


def test_confirm_settles_agreement_and_accrues_payable(api):
    """PRD §3.8: "each consigned book's agreement moves from `ACTIVE` to `SETTLED`,
    accruing its consignor payout into the consignor's `consignor_payable_cents`."

    Design: Difficulty/transitive_cascade/sale_confirm_depth3_book_listing_agreement_payable
    """
    ctx = setup_confirmed_consigned_sale(commission_pct=0.30, sale_price_cents=30000, comp_median_cents=20000)
    agreement = validate_success(api.get_consignment_agreement(ctx["agreement"]["id"], MANAGER), 200)
    assert agreement["status"] == "SETTLED"
    patron = validate_success(api.get_patron(ctx["patron"]["id"], MANAGER), 200)
    assert patron["consignor_payable_cents"] == 21000


# ── priority: state (item not listed) outranks referential (consignment) ─────

def _confirm_both_fail(api, title, comp, price):
    """Consigned book APPRAISED (not listed) with a PROPOSED (not active) agreement;
    a draft order selling it. Confirm should surface the state error."""
    patron = new_patron(display_name="Ada Dealer")
    ctx = make_appraised_book(condition_grade="GOOD", comp_median_cents=comp,
                              acquisition_channel="CONSIGNMENT", consignor_id=patron["id"], title=title)
    get_success_data(api_client.create_consignment_agreement(
        create_consignment_agreement_payload(patron["id"], ctx["book"]["id"], commission_pct=0.30), MANAGER))
    order = draft_shop_order(ctx["book"]["id"], price, channel="SHOP")
    return order


def test_confirm_state_outranks_referential_v1(api):
    """PRD §2.8: "On sale-order confirmation, the state check that every line item's
    book is `LISTED` (yielding `ERR_ITEM_NOT_LISTED`) outranks the referential check
    that a consigned line's agreement is `ACTIVE` (yielding `ERR_CONSIGNMENT_NOT_ACTIVE`).
    If both fail, the item-not-listed error is reported."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_outranks_referential
    """
    order = _confirm_both_fail(api, "Giacomo Joyce", 7000, 7000)
    res = api.confirm_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_ITEM_NOT_LISTED", expected_status=409)


def test_confirm_state_outranks_referential_v2(api):
    """PRD §2.8: "On sale-order confirmation, the state check that every line item's
    book is `LISTED` (yielding `ERR_ITEM_NOT_LISTED`) outranks the referential check
    that a consigned line's agreement is `ACTIVE` (yielding `ERR_CONSIGNMENT_NOT_ACTIVE`).
    If both fail, the item-not-listed error is reported."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_outranks_referential
    """
    order = _confirm_both_fail(api, "Pomes Penyeach", 9000, 9000)
    res = api.confirm_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_ITEM_NOT_LISTED", expected_status=409)


# ── cross-entity: confirm requires the consignment ACTIVE ────────────────────

def test_confirm_requires_active_agreement_proposed(api):
    """PRD §3.8: "for any consigned line, that book's `ConsignmentAgreement` must be
    `ACTIVE` (otherwise `ERR_CONSIGNMENT_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_consignment_active
    """
    ctx = setup_consigned_shelved(commission_pct=0.30, comp_median_cents=15000,
                                  list_price_cents=25000, grade="FINE", activate=False)
    order = draft_shop_order(ctx["book"]["id"], 25000, channel="SHOP")
    res = api.confirm_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_CONSIGNMENT_NOT_ACTIVE", expected_status=409)


def test_confirm_requires_active_agreement_variant(api):
    """PRD §3.8: "for any consigned line, that book's `ConsignmentAgreement` must be
    `ACTIVE` (otherwise `ERR_CONSIGNMENT_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_consignment_active
    """
    ctx = setup_consigned_shelved(commission_pct=0.25, comp_median_cents=12000,
                                  list_price_cents=18000, grade="VERY_GOOD", activate=False)
    order = draft_shop_order(ctx["book"]["id"], 18000, channel="SHOP")
    res = api.confirm_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_CONSIGNMENT_NOT_ACTIVE", expected_status=409)


# ── empty-order boundary ─────────────────────────────────────────────────────

def test_confirm_empty_order_shop_channel(api):
    """PRD §3.8: "the `line_items` array must be non-empty (otherwise
    `ERR_EMPTY_ORDER`)".

    Design: Difficulty/boundary_precision_check/confirm_empty_line_items_rejected
    """
    order = make_empty_sale_order(channel="SHOP")
    res = api.confirm_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_EMPTY_ORDER", expected_status=409)


def test_confirm_empty_order_online_channel(api):
    """PRD §3.8: "the `line_items` array must be non-empty (otherwise
    `ERR_EMPTY_ORDER`)".

    Design: Difficulty/boundary_precision_check/confirm_empty_line_items_rejected
    """
    order = make_empty_sale_order(channel="ONLINE")
    res = api.confirm_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_EMPTY_ORDER", expected_status=409)


# ── fiscal: insufficient store credit ────────────────────────────────────────

def test_confirm_insufficient_store_credit(api):
    """PRD §3.8: "the `store_credit_applied_cents` must not exceed the buyer's current
    `store_credit_cents` (otherwise `ERR_INSUFFICIENT_STORE_CREDIT`, HTTP 402)."

    Design: Corner/validations/confirm_insufficient_store_credit_returns_402
    """
    buyer = new_patron(display_name="Buyer Zero")
    ctx = make_listed_book(condition_grade="GOOD", list_price_cents=6000, comp_median_cents=4000,
                           on_shelf=True, title="Counterparts")
    order = draft_shop_order(ctx["book"]["id"], 6000, buyer_patron_id=buyer["id"],
                             store_credit_applied_cents=500, channel="SHOP")
    res = api.confirm_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_INSUFFICIENT_STORE_CREDIT", expected_status=402)


# ── refund guard ─────────────────────────────────────────────────────────────

def test_refund_non_confirmed_order_rejected(api):
    """PRD §3.8: "Refunding is a `Manager` action permitted only on a `CONFIRMED`
    order (otherwise `ERR_ORDER_NOT_CONFIRMED`)".

    Design: Corner/state_machines/refund_non_confirmed_order_returns_409
    """
    order = make_empty_sale_order(channel="SHOP")
    res = api.refund_sale_order(order["id"], MANAGER)
    validate_error(res, "ERR_ORDER_NOT_CONFIRMED", expected_status=409)
