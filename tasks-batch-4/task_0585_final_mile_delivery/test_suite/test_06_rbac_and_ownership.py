"""Role-based access control: authentication, authorization, and resource
ownership on the window-confirm path."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_depot_payload, create_order_payload, record_attempt_payload,
    make_customer,
    make_customer_headers,
    setup_out_for_delivery, setup_scheduled_order,
    TEST_USERS, NO_AUTH_HEADERS,
)

PLANNER = TEST_USERS["dispatch_planner_headers"]


def test_create_depot_without_auth_headers_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: X-User-ID, identifying the acting principal, and X-User-Role,
    declaring the operational capacity under which the request is made. If either
    header is absent, or the role is not one the system recognizes, the request
    is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/create_depot_missing_auth_header_returns_unauthenticated
    """
    validate_error(api.create_depot(create_depot_payload(), NO_AUTH_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_dispatch_planner_cannot_create_depot(api):
    """PRD §2.1: "Each write operation is restricted to specific roles; an
    authenticated principal attempting an operation outside its authority is
    rejected with ERR_UNAUTHORIZED."
    PRD §4: the POST /depots row lists PlatformAdmin as the only authorized role.

    Design: Corner/rbac/dispatch_planner_cannot_create_depot
    """
    validate_error(api.create_depot(create_depot_payload(), PLANNER),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


def test_dispatch_planner_cannot_record_attempt(api):
    """PRD §2.1: "an authenticated principal attempting an operation outside its
    authority is rejected with ERR_UNAUTHORIZED."
    PRD §4: the POST /delivery-orders/{orderId}/attempts row lists DeliveryLead as
    the only authorized role.

    Design: Corner/rbac/planner_cannot_record_attempt
    """
    ns = setup_out_for_delivery(api)
    payload = record_attempt_payload("DELIVERED", placement="THRESHOLD", signature_captured=True, photo_count=1)
    validate_error(api.record_attempt(ns["order"]["id"], payload, PLANNER),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_confirming_others_window_rejected(api):
    """PRD §2.1: "a Customer confirming a window that does not belong to their own
    order is rejected with ERR_NOT_RESOURCE_OWNER."
    PRD §3.3: "Confirmation requires ... that the acting Customer be the order's
    own customer (otherwise ERR_NOT_RESOURCE_OWNER)."

    Design: Corner/rbac/customer_confirm_window_not_owner
    """
    ns = setup_scheduled_order(api)  # window owned by customer A
    other = make_customer(api, full_name="Bob", address_line="2 Ave", geo_lat=34.1, geo_lng=-118.1)
    headers = make_customer_headers(other["id"])
    validate_error(api.confirm_window(ns["window"]["id"], headers),
                   ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
