"""Role-based access control: authentication, authorization, and resource ownership.

Corner instances: rbac section (peer_roles) + the ownership-violation validation.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    make_admin_headers, make_farm_headers, make_customer_headers, ANONYMOUS_HEADERS,
    ABSENT_UUID,
    set_clock, new_farm, new_hub, new_customer, new_cycle, open_cycle, new_order,
)


def _order(api, order_id):
    return api.get_order(order_id, make_admin_headers()).json()["data"]


def test_customer_cannot_pack_line_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.10: "**Authorization** — the acting role is permitted for the endpoint, else
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_pack_line_unauthorized
    """
    set_clock(api)
    # pack is a Farm/PlatformAdmin operation; a Customer is rejected at authorization,
    # before path existence is even checked (so a bogus line id is fine).
    resp = api.pack_line(ABSENT_UUID, {"fulfilled_qty": 1},
                         make_customer_headers("00000000-0000-4000-8000-0000000000c1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_farm_cannot_open_cycle_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/farm_cannot_open_cycle_unauthorized
    """
    set_clock(api)
    # opening a cycle is PlatformAdmin-exclusive; a Farm is rejected with ERR_UNAUTHORIZED.
    resp = api.open_cycle(ABSENT_UUID, make_farm_headers("00000000-0000-4000-8000-0000000000f1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_customer_b_cannot_cancel_other_customers_order(api):
    """PRD §2.1: "When an entity-backed actor (a `Farm` or a `Customer`) is authenticated and
    authorized for the endpoint but is not the owner of the specific targeted resource, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_b_cannot_cancel_others_order
    """
    set_clock(api)
    hub = new_hub(api)
    cust_a = new_customer(api, name="Ada", snap_balance_cents=0)
    cust_b = new_customer(api, name="Ben", snap_balance_cents=0)
    cycle = new_cycle(api)
    open_cycle(api, cycle["id"])
    order = new_order(api, cust_a["id"], cycle["id"], hub["id"])

    resp = api.cancel_order(order["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert _order(api, order["id"])["order_status"] == "CART"


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    farm = new_farm(api)
    resp = api.get_farm(farm["id"], ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
