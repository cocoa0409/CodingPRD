"""Parallel state dimensions on Order and special-order re-quote self-cycle."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_customer_headers,
    create_active_product, create_store, create_inventory, create_customer,
    create_open_order, add_line,
    create_special_order_draft,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


def test_partial_payment_advances_payment_status_only(api):
    """PRD §3.7: "While the cumulative `amount_paid_cents` remains below `total_cents`,
    `payment_status` becomes `PARTIALLY_PAID`; once it reaches or exceeds `total_cents`,
    `payment_status` becomes `PAID`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    product = create_active_product(msrp_cents=1000)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=50)
    customer = create_customer()
    cid = customer["id"]

    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=5, recipient_age_months=120)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))

    data = validate_success(api.pay_order(order["id"], {"amount_cents": 2000}, ASSOCIATE))
    assert data["payment_status"] == "PARTIALLY_PAID"
    assert data["fulfillment_status"] == "SUBMITTED"
    assert data["amount_paid_cents"] == 2000


def test_payment_dimension_independent_of_fulfillment_dimension(api):
    """PRD §2.7: "An `Order` has a `fulfillment_status` (`OPEN`, `SUBMITTED`, `READY`,
    `FULFILLED`, `CANCELLED`) and an independent `payment_status` (`UNPAID`,
    `PARTIALLY_PAID`, `PAID`)."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    product = create_active_product(msrp_cents=1000)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=50)
    customer = create_customer()
    cid = customer["id"]

    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=5, recipient_age_months=120)
    submitted = validate_success(api.submit_order(order["id"], make_customer_headers(cid)))
    assert submitted["payment_status"] == "UNPAID"
    assert submitted["fulfillment_status"] == "SUBMITTED"


def test_requote_from_quoted_increments_revision(api):
    """PRD §3.10: "re-quoting from `QUOTED` is a deliberate self-cycle that supersedes the
    prior quote. A successful quote sets `quoted_unit_price_cents` and `deposit_cents`,
    increments `quote_revision`, increments `version`, and leaves the special order in
    `QUOTED`."

    Design: Difficulty/non_linear_state_machine/special_order_requote_self_cycle
    """
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    customer = create_customer()
    so = create_special_order_draft(customer["id"], product["id"], requested_qty=2)

    q1 = validate_success(api.quote_special_order(
        so["id"], {"unit_price_cents": 5200, "deposit_cents": 2000,
                   "expected_special_order_version": so["version"]}, MANAGER))
    q2 = validate_success(api.quote_special_order(
        so["id"], {"unit_price_cents": 5400, "deposit_cents": 2200,
                   "expected_special_order_version": q1["version"]}, MANAGER))
    assert q2["quote_revision"] == 2
    assert q2["status"] == "QUOTED"
    assert q2["quoted_unit_price_cents"] == 5400


def test_requote_supersedes_prior_quote_price(api):
    """PRD §2.6: "Because a new quote legitimately supersedes the prior one — replacing
    `quoted_unit_price_cents` and `deposit_cents` and advancing `quote_revision` — a
    manager working from a stale view would otherwise silently overwrite a newer quote."

    Design: Difficulty/non_linear_state_machine/special_order_requote_self_cycle
    """
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    customer = create_customer()
    so = create_special_order_draft(customer["id"], product["id"], requested_qty=2)

    q1 = validate_success(api.quote_special_order(
        so["id"], {"unit_price_cents": 5200, "deposit_cents": 2000,
                   "expected_special_order_version": so["version"]}, MANAGER))
    validate_success(api.quote_special_order(
        so["id"], {"unit_price_cents": 5400, "deposit_cents": 2200,
                   "expected_special_order_version": q1["version"]}, MANAGER))
    fetched = validate_success(api.get_special_order(so["id"], ANY))
    assert fetched["quoted_unit_price_cents"] == 5400
    assert fetched["deposit_cents"] == 2200


def test_stale_expected_version_on_requote_rejected(api):
    """PRD §2.6: "If `expected_special_order_version` does not equal the special order's
    current `version`, the quote is rejected with `ERR_STALE_SPECIAL_ORDER_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/special_order_requote_stale_version_conflict
    """
    from test_helpers import validate_error, ApiErrorId
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    customer = create_customer()
    so = create_special_order_draft(customer["id"], product["id"], requested_qty=1)
    v0 = so["version"]

    validate_success(api.quote_special_order(
        so["id"], {"unit_price_cents": 5100, "deposit_cents": 2000,
                   "expected_special_order_version": v0}, MANAGER))
    # Second quote reuses the now-stale v0.
    validate_error(
        api.quote_special_order(
            so["id"], {"unit_price_cents": 5300, "deposit_cents": 2100,
                       "expected_special_order_version": v0}, MANAGER),
        ApiErrorId.ERR_STALE_SPECIAL_ORDER_VERSION.value,
    )
