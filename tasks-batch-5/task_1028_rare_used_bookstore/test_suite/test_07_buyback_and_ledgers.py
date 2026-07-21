"""Buyback auto-approval boundary, void guards, and compensating ledgers."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_buyback_offer_payload, TEST_USERS,
)
from test_helpers.fixtures import (
    new_patron, make_buyback_offer, make_accepted_buyback,
    make_listed_book, draft_shop_order, setup_confirmed_consigned_sale,
)
from test_helpers.api_client import api_client

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["storeclerk_headers"]


def test_buyback_auto_approves_at_exact_limit_status(api):
    """PRD §3.6: "an offer whose `offer_value_cents` is at most 5000 auto-approves on
    creation — its `auto_approved` flag is set true and its status becomes
    `AUTO_APPROVED`. The boundary is inclusive on the lower side: an offer of exactly
    5000 cents auto-approves, while 5001 cents remains `PENDING`."

    Design: Difficulty/boundary_precision_check/buyback_auto_approve_at_exact_limit
    """
    patron = new_patron(display_name="Seller One", headers=CLERK)
    offer = validate_success(api.create_buyback_offer(
        create_buyback_offer_payload(patron["id"], 5000), CLERK), 201)
    assert offer["status"] == "AUTO_APPROVED"


def test_buyback_auto_approves_at_exact_limit_flag(api):
    """PRD §3.6: "an offer whose `offer_value_cents` is at most 5000 auto-approves on
    creation — its `auto_approved` flag is set true and its status becomes
    `AUTO_APPROVED`. The boundary is inclusive on the lower side: an offer of exactly
    5000 cents auto-approves, while 5001 cents remains `PENDING`."

    Design: Difficulty/boundary_precision_check/buyback_auto_approve_at_exact_limit
    """
    patron = new_patron(display_name="Seller One", headers=CLERK)
    offer = validate_success(api.create_buyback_offer(
        create_buyback_offer_payload(patron["id"], 5000), CLERK), 201)
    assert offer["auto_approved"] is True


def test_buyback_just_over_limit_stays_pending(api):
    """PRD §3.6: "The boundary is inclusive on the lower side: an offer of exactly
    5000 cents auto-approves, while 5001 cents remains `PENDING`."

    Design: Corner/calculations/buyback_just_over_limit_stays_pending
    """
    patron = new_patron(display_name="Buck", headers=CLERK)
    offer = validate_success(api.create_buyback_offer(
        create_buyback_offer_payload(patron["id"], 5001), CLERK), 201)
    assert offer["status"] == "PENDING"
    assert offer["auto_approved"] is False


def test_void_pending_offer_rejected(api):
    """PRD §3.6: "A `Manager` may later void an `ACCEPTED` offer (otherwise
    `ERR_OFFER_NOT_VOIDABLE`); voiding moves it to `VOIDED` and reverses the credit".

    Design: Corner/state_machines/void_pending_offer_returns_409
    """
    ctx = make_buyback_offer(9000)  # above auto-approve limit, so PENDING
    assert ctx["offer"]["status"] == "PENDING"
    res = api.void_buyback_offer(ctx["offer"]["id"], MANAGER)
    validate_error(res, "ERR_OFFER_NOT_VOIDABLE", expected_status=409)


def test_store_credit_conserved_void_status(api):
    """PRD §3.6: "A `Manager` may later void an `ACCEPTED` offer (otherwise
    `ERR_OFFER_NOT_VOIDABLE`); voiding moves it to `VOIDED` and reverses the credit,
    subtracting the offer's `credit_amount_cents` from the seller's
    `store_credit_cents`."

    Design: Difficulty/compensating_invariant/store_credit_conserved_across_buyback_void
    """
    ctx = make_accepted_buyback(3000)
    voided = validate_success(api.void_buyback_offer(ctx["offer"]["id"], MANAGER), 200)
    assert voided["status"] == "VOIDED"


def test_store_credit_conserved_balance_zero(api):
    """PRD §2.9: "any buyback acceptance immediately undone by its void returns
    `store_credit_cents` to its exact prior value".

    Design: Difficulty/compensating_invariant/store_credit_conserved_across_buyback_void
    """
    ctx = make_accepted_buyback(3000)
    patron_id = ctx["patron_id"]
    before = validate_success(api.get_patron(patron_id, MANAGER), 200)
    assert before["store_credit_cents"] == 3000
    validate_success(api.void_buyback_offer(ctx["offer"]["id"], MANAGER), 200)
    after = validate_success(api.get_patron(patron_id, MANAGER), 200)
    assert after["store_credit_cents"] == 0


def test_consignor_payable_conserved_refund_states(api):
    """PRD §3.8: "Each line's book returns from `SOLD` to `LISTED`, each listing's
    sold axis is restored to its pre-sale live value with `sold_channel` cleared, and
    each consigned agreement returns from `SETTLED` to `ACTIVE`."

    Design: Difficulty/compensating_invariant/consignor_payable_conserved_across_sale_refund
    """
    ctx = setup_confirmed_consigned_sale(commission_pct=0.30, sale_price_cents=30000, comp_median_cents=20000)
    order = validate_success(api.refund_sale_order(ctx["order"]["id"], MANAGER), 200)
    assert order["status"] == "REFUNDED"
    agreement = validate_success(api.get_consignment_agreement(ctx["agreement"]["id"], MANAGER), 200)
    assert agreement["status"] == "ACTIVE"


def test_consignor_payable_conserved_balance_zero(api):
    """PRD §2.9: "any sale confirmation immediately undone by its refund returns both
    `store_credit_cents` and `consignor_payable_cents` to their exact prior values."

    Design: Difficulty/compensating_invariant/consignor_payable_conserved_across_sale_refund
    """
    ctx = setup_confirmed_consigned_sale(commission_pct=0.30, sale_price_cents=30000, comp_median_cents=20000)
    before = validate_success(api.get_patron(ctx["patron"]["id"], MANAGER), 200)
    assert before["consignor_payable_cents"] == 21000
    validate_success(api.refund_sale_order(ctx["order"]["id"], MANAGER), 200)
    after = validate_success(api.get_patron(ctx["patron"]["id"], MANAGER), 200)
    assert after["consignor_payable_cents"] == 0


def test_void_after_credit_spent_rejected(api):
    """PRD §3.6: "a void is refused with `ERR_CREDIT_ALREADY_SPENT` when the seller's
    current `store_credit_cents` is below the offer's `credit_amount_cents` — the
    credit has already been spent and cannot be clawed back."

    Design: Corner/errors/credit_already_spent_void_returns_402
    """
    patron = new_patron(display_name="Bloom")
    ctx = make_accepted_buyback(3000, patron_id=patron["id"])
    book_ctx = make_listed_book(condition_grade="FINE", list_price_cents=10000,
                                comp_median_cents=5000, on_shelf=True, title="Wandering Rocks")
    order = draft_shop_order(book_ctx["book"]["id"], 10000, buyer_patron_id=patron["id"],
                             store_credit_applied_cents=3000, channel="SHOP")
    validate_success(api.confirm_sale_order(order["id"], MANAGER), 200)
    res = api.void_buyback_offer(ctx["offer"]["id"], MANAGER)
    validate_error(res, "ERR_CREDIT_ALREADY_SPENT", expected_status=402)
