"""Authentication and role-based access control.

Covers corner validations and rbac instances.
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_error,
    ApiErrorId,
    setup_plan_customer_subscription,
    get_subscription_shipments,
    create_customer,
)
from test_helpers.test_users import anonymous_headers, make_customer_headers
from test_helpers.factories import create_plan_payload


# =====================================================================
# Corner: unauthenticated_missing_headers
# =====================================================================


def test_missing_auth_headers_return_unauthenticated():
    """PRD §2.1: "Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/corner_unauthenticated_missing_headers
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    res = api_client.get_subscription(subscription["id"], anonymous_headers())
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =====================================================================
# Corner: RBAC — fulfillmentops_cannot_pause
# =====================================================================


def test_fulfillment_ops_cannot_pause_subscription():
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    PRD §4's endpoint table names Customer as the sole authorized role for
    POST /subscriptions/{id}/pause; FulfillmentOps calling it must be rejected.

    Design: Corner/rbac/corner_rbac_fulfillmentops_cannot_pause
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    res = api_client.pause_subscription(
        subscription["id"], {}, TEST_USERS["fulfillment_ops_headers"]
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


# =====================================================================
# Corner: RBAC — customer_cannot_source
# =====================================================================


def test_customer_cannot_source_shipment():
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    PRD §4's endpoint table names FulfillmentOps as the sole authorized role for
    POST /shipments/{id}/source; Customer calling it must be rejected.

    Design: Corner/rbac/corner_rbac_customer_cannot_source
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    res = api_client.source_shipment(
        shipments[0]["id"], {}, make_customer_headers(customer["id"])
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


# =====================================================================
# Corner: RBAC — customer_cannot_create_plan
# =====================================================================


def test_customer_cannot_create_plan():
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    PRD §4's endpoint table names PlatformAdmin as the sole authorized role for
    POST /plans; Customer calling it must be rejected.

    Design: Corner/rbac/corner_rbac_customer_cannot_create_plan
    """
    customer = create_customer()
    payload = create_plan_payload(name="Sneaky", cadence="WEEKLY", base_fee_cents=5000)
    res = api_client.create_plan(payload, make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)
