"""Access control, authentication, existence, range validation, and filtered listings."""
import test_helpers as H


# ==========================================================================
# Queue B — rbac
# ==========================================================================
def test_associate_cannot_publish_recall(api, associate_headers, manager_headers):
    """PRD §2.1: "A `Manager` is a supervisor whose permissions are a superset of the `Associate`'s
    (a hierarchical override — anything an `Associate` may do, a `Manager` may do) plus fiscal and
    compliance exclusives: publishing and closing recall notices, discontinuing products, resolving
    warranty claims, voiding registrations, accepting and voiding trade-ins, refunding sales orders,
    and setting the logical clock."

    Design: Corner/rbac/associate_cannot_publish_recall_returns_forbidden
    """
    product = H.new_product(api)
    notice = H.new_recall_notice(product["id"], api, reason="x", remedy="REPAIR")
    H.validate_error(api.publish_recall_notice(notice["id"], associate_headers), H.ApiErrorId.ERR_FORBIDDEN)


def test_customer_cannot_resolve_claim(api):
    """PRD §2.1: "A `Manager` is a supervisor whose permissions are a superset of the `Associate`'s
    (a hierarchical override — anything an `Associate` may do, a `Manager` may do) plus fiscal and
    compliance exclusives: publishing and closing recall notices, discontinuing products, resolving
    warranty claims, voiding registrations, accepting and voiding trade-ins, refunding sales orders,
    and setting the logical clock."

    Design: Corner/rbac/customer_cannot_resolve_claim_returns_forbidden
    """
    _p, customer, _reg, claim = H.reviewed_claim(api)
    resp = api.resolve_claim(claim["id"], "REPAIR", H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_FORBIDDEN)


def test_customer_cannot_approve_other_customers_repair(api, associate_headers):
    """PRD §2.1: "Any attempt by a `Customer` to read or act on another customer's resource is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_approve_other_customers_repair_returns_forbidden
    """
    cust_a = H.new_customer(api)
    cust_b = H.new_customer(api)
    product = H.new_product(api)
    ro, _ = H.quoted_repair(cust_a["id"], product["id"],
                            [{"repair_type": "WHEEL", "labor_hours": 1, "parts_cost_cents": 1000}], api=api)
    resp = api.approve_repair_order(ro["id"], H.make_customer_headers(cust_b["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_FORBIDDEN)


# ==========================================================================
# Queue B — errors: authentication and existence
# ==========================================================================
def test_missing_auth_headers_rejected(api, anon_headers):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` that is not one
    of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    H.validate_error(api.list_products(anon_headers), H.ApiErrorId.ERR_UNAUTHENTICATED)


def test_get_nonexistent_product_returns_not_found(api, associate_headers):
    """PRD §2.8: "3. **Existence** — every path `id` and every body foreign key resolves to an
    existing resource, validated left to right in the order they appear; the first unresolved
    identifier yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/get_product_nonexistent_returns_not_found
    """
    H.validate_error(api.get_product(H.NON_EXISTENT_UUID, associate_headers), H.ApiErrorId.ERR_NOT_FOUND)


def test_sales_order_line_qty_zero_returns_range_error(api, associate_headers):
    """PRD §3.5: "Quantities below one, negative money, or a discount outside the zero-to-one range
    are rejected with `ERR_VALIDATION_RANGE`."

    Design: Corner/entities/create_sales_order_line_qty_zero_returns_validation_range
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=8000)
    order = H.new_sales_order(customer["id"], api)
    resp = api.create_sales_order_line(
        H.create_sales_order_line_payload(order["id"], product["id"], unit_price_cents=8000, qty=0),
        associate_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_VALIDATION_RANGE)


# ==========================================================================
# Queue B — endpoints: filtered child listings
# ==========================================================================
def test_list_repair_lines_by_repair_order(api, associate_headers):
    """PRD §4: "| GET | `/store/repair-lines` | List/filter repair lines | Manager, Associate,
    Customer |"

    Design: Corner/endpoints/list_repair_lines_by_repair_order_returns_children
    """
    customer = H.new_customer(api)
    product = H.new_product(api)
    ro = H.new_repair_order(customer["id"], product["id"], api)
    l1 = H.new_repair_line(ro["id"], api, repair_type="WHEEL", parts_cost_cents=1000)
    l2 = H.new_repair_line(ro["id"], api, repair_type="HANDLE", parts_cost_cents=1000)
    data, _meta = H.validate_paginated(api.list_repair_lines(associate_headers, params={"repair_order_id": ro["id"]}))
    returned_ids = {row["id"] for row in data}
    assert {l1["id"], l2["id"]} <= returned_ids
    assert all(row["repair_order_id"] == ro["id"] for row in data)


def test_list_registrations_by_customer(api, associate_headers):
    """PRD §4: "| GET | `/store/warranty-registrations` | List/filter registrations | Manager,
    Associate, Customer |"

    Design: Corner/endpoints/list_registrations_by_customer_returns_children
    """
    customer = H.new_customer(api)
    product = H.new_product(api)
    reg = H.new_registration(product["id"], customer["id"], api)
    data, _meta = H.validate_paginated(api.list_registrations(associate_headers, params={"customer_id": customer["id"]}))
    assert reg["id"] in {row["id"] for row in data}
