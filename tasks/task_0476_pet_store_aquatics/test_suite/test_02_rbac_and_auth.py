"""Role-based access control, ownership, and authentication header checks."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_customer_headers, build_user_headers,
    create_recall_payload, create_subscription_payload, run_shipment_payload,
    make_store, make_product, make_customer,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
KEEPER = TEST_USERS["livestock_keeper_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


def test_store_clerk_cannot_issue_recall(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: "POST | `/recalls` | Issue a product recall (3-hop cross-store
    cascade) | InventoryManager".

    Design: Corner/rbac/store_clerk_cannot_issue_recall
    """
    product = make_product()
    res = api.create_recall(
        create_recall_payload(product["id"], severity="ADVISORY"), CLERK
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_customer_cannot_pause_other_customers_subscription(api):
    """PRD §2.1: "When a `Customer` attempts to pause, resume, or cancel a
    subscription, or cancel a special order, that does not belong to them, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_pause_other_customers_subscription
    """
    store = make_store()
    product = make_product()
    c1 = make_customer(store["id"], email="c1@x.com")
    c2 = make_customer(store["id"], email="c2@x.com")
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(c1["id"], product["id"], store["id"]),
            make_customer_headers(c1["id"]),
        ), 201,
    )
    res = api.pause_subscription(sub["id"], make_customer_headers(c2["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_livestock_keeper_cannot_run_shipment(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: "POST | `/subscriptions/{subId}/run-shipment` | Fulfill a due
    auto-ship cycle (OCC-guarded; allocates FEFO; charges) | StoreClerk".

    Design: Corner/rbac/livestock_keeper_cannot_run_shipment
    """
    store = make_store()
    product = make_product()
    customer = make_customer(store["id"])
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(customer["id"], product["id"], store["id"]),
            CLERK,
        ), 201,
    )
    res = api.run_shipment(
        sub["id"], run_shipment_payload(sub["version"]), KEEPER
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_missing_user_context_header_returns_401(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and
    `X-User-Role`, which declares the operational capacity under which they are
    acting. If either header is missing or malformed, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_returns_401
    """
    # An invalid (unrecognized) role value is malformed user context.
    bad_headers = build_user_headers("test-x", "NotARealRole")
    res = api.create_store({"name": "S", "state_code": "CA"}, bad_headers)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
