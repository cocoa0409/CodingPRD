"""RBAC (role authorization, ownership, hierarchical override) and checkout OCC."""
import test_helpers as H


# ==========================================================================
# Queue B — rbac
# ==========================================================================
def test_customer_cannot_create_product(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to invoke
    the target operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_create_product
    """
    customer = H.new_customer()
    resp = api.create_product(H.create_product_payload(product_type="SOAP", title="Rb"),
                              H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_UNAUTHORIZED)


def test_customer_cannot_checkout_another_customers_order(api):
    """PRD §2.1: "Ownership is enforced on every self-service operation: for any order, return, or
    subscription the customer acts on, the resource's owning `customer_id` (directly on an `Order`
    or `Subscription`, or reached through the `order_id` on a `Return`) must equal `X-User-ID`. A
    `Customer` acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/customer_cannot_checkout_others_order
    """
    cat = H.released_catalog(product_type="SOAP", list_price_cents=1000, quantity=20)
    c1 = H.new_customer()
    c2 = H.new_customer()
    order = H.new_order(c1["id"])
    H.add_line(order["id"], c1["id"], cat["sku"]["id"], cat["batch"]["id"], 1)
    version = H.get_order_version(order["id"], c1["id"])
    resp = api.checkout_order(order["id"], version, H.make_customer_headers(c2["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_platform_admin_can_fulfill_order(api, admin_headers):
    """PRD §2.1: "a superset operator who can perform every `MerchOps` operation, every `Customer`
    write operation (acting on behalf of shoppers), all reads, and additionally the
    customer-lifecycle, loyalty-grant, and logical-clock operations reserved to this role."

    Design: Corner/rbac/platform_admin_can_fulfill_order
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=1000, quantity=1, batch_quantity=20)
    delivered = H.validate_success(api.fulfill_order(ctx["order"]["id"], admin_headers), 200)
    assert delivered["fulfillment_status"] == "DELIVERED"


# ==========================================================================
# Queue B — cross_cutting: optimistic concurrency at checkout
# ==========================================================================
def test_checkout_with_stale_version_rejected(api):
    """PRD §2.7: "if another writer has advanced the order's version since the client last read
    it — for example by adding or repricing a line, which legitimately mutates the cart and bumps
    the order version — the totals the client is paying against are stale, and the checkout is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/checkout_stale_version_returns_412
    """
    cat = H.released_catalog(product_type="SOAP", list_price_cents=1000, quantity=50)
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    H.add_line(order["id"], customer["id"], cat["sku"]["id"], cat["batch"]["id"], 1)
    stale_version = H.get_order_version(order["id"], customer["id"])
    H.add_line(order["id"], customer["id"], cat["sku"]["id"], cat["batch"]["id"], 1)  # bumps version
    resp = api.checkout_order(order["id"], stale_version, H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_STALE_VERSION)
    assert H.fetch_order(order["id"])["payment_status"] == "UNPAID"


def test_checkout_with_current_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "Only when `expected_order_version` equals the order's current `version` does
    checkout proceed."
    PRD §3.7: "Checkout increments the order's `version` by one."

    Design: Corner/cross_cutting/checkout_correct_version_succeeds
    """
    cat = H.released_catalog(product_type="SOAP", list_price_cents=1000, quantity=50)
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    H.add_line(order["id"], customer["id"], cat["sku"]["id"], cat["batch"]["id"], 1)
    version = H.get_order_version(order["id"], customer["id"])
    result = H.validate_success(
        api.checkout_order(order["id"], version, H.make_customer_headers(customer["id"])), 200)
    assert result["payment_status"] == "PAID"
    assert result["fulfillment_status"] == "ALLOCATED"
    assert result["version"] == version + 1
