"""Role-based access control (peer isolation, role-exclusive operations),
authentication errors, and a filtered billing-cycle read.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
    create_plan_payload, pause_payload, retry_charge_payload,
    set_clock, create_plan, create_subscriber, create_subscription,
    setup_subscription,
)

ADMIN = TEST_USERS["curation_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]


def test_subscriber_cannot_act_on_another_subscribers_subscription(api):
    """PRD §2.1: "a `Subscriber` may act only on subscriptions, box selections,
    gifts, and wallet lines whose `subscriber_id` (or, for gifts,
    `gifter_subscriber_id`) equals their own `X-User-ID`; acting on another
    subscriber's resource is denied with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/subscriber_cannot_act_on_another_subscribers_subscription
    """
    ctx = setup_subscription(plan_overrides={"name": "OW"})
    b_subscription = ctx["subscription"]
    a_account = create_subscriber(email="owa@x.com", full_name="OW A")
    a_headers = make_subscriber_headers(a_account["id"])
    res = api.pause_subscription(b_subscription["id"], pause_payload("2026-08-01T00:00:00Z"), a_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_subscriber_cannot_retry_charge_billing_operator_only(api):
    """PRD §2.1: "A `BillingOperator` owns billing settlement: charge retries,
    refunds, manual wallet adjustments, and gift revocation."
    PRD §2.1: "When a request is authenticated but the acting role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/subscriber_cannot_retry_charge_billing_operator_only
    """
    ctx = setup_subscription(plan_overrides={"name": "RC"})
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.retry_charge(sub["id"], retry_charge_payload("PAID"), headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.list_plans(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_subscriber_creating_plan_returns_unauthorized(api):
    """PRD §2.1: "A `CurationAdmin` owns the catalog and fulfillment machinery:
    plans, products, shipping waves, allocations, and shipments".
    PRD §2.1: "When a request is authenticated but the acting role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/errors/subscriber_creating_plan_returns_unauthorized
    """
    set_clock("2026-06-01T00:00:00Z")
    account = create_subscriber(email="ua@x.com", full_name="UA S")
    headers = make_subscriber_headers(account["id"])
    res = api.create_plan(
        create_plan_payload(name="Sneaky", cadence="MONTHLY",
                            period_price_cents=6000, box_item_count=1),
        headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_list_billing_cycles_filtered_by_subscription(api):
    """PRD §2.10: "A subscription's billing cycles, box selections, allocations,
    invoices, and shipments are each discoverable by filtering the corresponding
    collection on a `subscription_id`."
    PRD §3.2: "The first period is billed immediately: the system creates a
    `BillingCycle` for `period_index` 1 with `funding_source` `CHARGE`, settles it
    `PAID`".

    Design: Corner/endpoints/list_billing_cycles_filtered_by_subscription
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="BC", period_price_cents=6000)
    subscriber = create_subscriber(email="bc@x.com", full_name="BC S")
    sub = create_subscription(subscriber, plan)
    data, _meta = validate_paginated(
        api.list_billing_cycles(BILLING, params={"subscription_id": sub["id"]}))
    assert len(data) == 1, f"expected exactly one period-1 billing cycle, got {len(data)}"
    assert data[0]["period_index"] == 1
    assert data[0]["status"] == "PAID"
