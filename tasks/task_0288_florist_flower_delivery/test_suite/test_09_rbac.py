"""Role-based access control and authentication.

Translates queue-B Corner rbac instances: role-forbidden, resource ownership,
and missing authentication headers.
"""
import pytest
import requests
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers,
    set_clock, create_zone, create_arrangement, create_customer, create_florist,
    create_draft_order, setup_delivered_order, file_claim, TEST_USERS,
)

CATALOG_ADMIN = TEST_USERS["catalog_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_customer_cannot_approve_claim_forbidden(api):
    """PRD §2.1: "When an authenticated principal invokes an endpoint its role is
    not permitted to call, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.7: "A `Dispatcher` adjudicates an open claim. **Approving** advances the
    claim from `OPEN` to `APPROVED`".

    Design: Corner/rbac/customer_cannot_approve_claim
    """
    ctx, order, _wf = setup_delivered_order(
        "2027-07-01T08:00:00Z",
        zone_overrides={"zone_code": "ZB1", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CB1", "display_name": "CB1", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2027-07-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    claim = file_claim(order, ctx["customer"], "LATE", "REFUND")
    res = api.approve_claim(claim["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
    after = validate_success(api.get_claim(claim["id"], DISPATCHER), 200)
    assert after["status"] == "OPEN"


def test_customer_cannot_act_on_other_customers_order(api):
    """PRD §2.1: "ownership checks on any resource that references a `Customer` (an
    `Order` through its `customer_id`, a `QualityClaim` through its `customer_id`, a
    `RecurringSchedule` through its `customer_id`) compare the resource's owner
    foreign key to `X-User-ID`."
    PRD §2.1: "An entity-backed principal that attempts to mutate a resource it does
    not own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order
    """
    set_clock("2027-07-08T08:00:00Z")
    zone = create_zone(zone_code="ZB2", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CB2", display_name="CB2", base_price_cents=5000)
    cust_a = create_customer(email="owna@x.com", full_name="Owner A")
    cust_b = create_customer(email="ownb@x.com", full_name="Owner B")
    order = create_draft_order(cust_a, arr, zone, delivery_date="2027-07-12",
                               window_start_minute=540, window_end_minute=720)
    # Customer B (X-User-ID != order.customer_id) tries to quote A's order.
    res = api.quote_order(order["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "DRAFT"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    zone = create_zone(zone_code="ZB3", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    # POST /floral/florists with no X-User-Role / X-User-ID headers.
    resp = requests.post(
        f"{api.base_url}/floral/florists",
        json={"shop_name": "NoAuth", "covered_zone_id": zone["id"], "daily_capacity": 5},
        headers={"Content-Type": "application/json"},
    )
    validate_error(resp, "ERR_UNAUTHENTICATED", expected_status=401)
