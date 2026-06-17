"""Role-based access control, ownership isolation, authentication, and pagination
bounds (PRD §2.1, §2.3, §2.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_guest_headers, TEST_USERS,
    create_park, create_policy, create_guest, create_order,
)

PM = TEST_USERS["park_manager_headers"]
GA = TEST_USERS["gate_agent_headers"]
FC = TEST_USERS["finance_clerk_headers"]


# ───────────────── Queue B: rbac ─────────────────

def test_gate_agent_cannot_create_park(api):
    """PRD §2.1: "When a syntactically valid request names a role that is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/rbac_gate_agent_cannot_create_park
    """
    res = api_client.create_park({"name": "X", "total_gate_capacity": 10}, GA)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_guest_cannot_refund_order(api):
    """PRD §2.1: "When a syntactically valid request names a role that is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/rbac_guest_cannot_refund_order
    """
    park = create_park()
    create_policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    guest = create_guest()
    gh = make_guest_headers(guest["id"])
    order = create_order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    get_success_data(api_client.pay_order(order["id"], gh))
    res = api_client.refund_order(order["id"], gh)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_guest_cannot_act_on_other_guests_order(api):
    """PRD §2.1: "A guest who attempts a state-changing operation against an order or
    admission whose guest_id is not their own X-User-ID is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/rbac_guest_cannot_act_on_other_guests_order
    """
    park = create_park()
    create_policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    guest_a = create_guest(email="ga@x.com")
    guest_b = create_guest(email="gb@x.com")
    order = create_order(park["id"], guest_a["id"], product_type="DAY_TICKET", party_size=1)
    # Guest B tries to pay Guest A's order.
    res = api_client.pay_order(order["id"], make_guest_headers(guest_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "A request that omits either header, or that carries a malformed value,
    is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/rbac_unauthenticated_missing_headers
    """
    res = api_client.list_parks({})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ───────────────── Queue B: errors ─────────────────

def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A limit below 1 or above 100, or an offset below 0, is rejected with
    ERR_PAGINATION_INVALID."

    Design: Corner/errors/error_pagination_invalid_limit_over_max
    """
    res = api_client.list_parks(PM, params={"limit": 101})
    validate_error(res, "ERR_PAGINATION_INVALID")
