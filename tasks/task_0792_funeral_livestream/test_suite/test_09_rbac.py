"""Role-based access control and tenant isolation.

Queue-B corner instances under the rbac section.
"""
from test_helpers import (
    TEST_USERS,
    validate_error, ApiErrorId,
    setup_home_and_venue, create_home, create_venue, create_order,
    create_service_order_payload, make_funeral_home_headers,
)

ADMIN = TEST_USERS["admin_headers"]
GUEST = TEST_USERS["guest_headers"]


def test_guest_cannot_create_service_order(api):
    """PRD §2.1: "When the headers are present and valid but the declared role is
    not permitted to invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/guest_cannot_create_service_order_returns_unauthorized
    """
    base = setup_home_and_venue()
    payload = create_service_order_payload(base["home"]["id"], base["venue"]["id"],
                                           decedent_name="G Zee")
    validate_error(api.create_service_order(payload, GUEST), ApiErrorId.ERR_UNAUTHORIZED)


def test_funeral_home_cannot_read_other_homes_order(api):
    """PRD §2.1: "Any cross-tenant access — a `FuneralHome` or `Operator` acting
    on a resource whose `home_id` is not their own — is rejected with
    `ERR_CROSS_TENANT_FORBIDDEN`."

    Design: Corner/rbac/cross_tenant_get_order_returns_forbidden
    """
    home_a = create_home(initial_credits=0, name="Home A", contact_email="a@x.com")
    home_b = create_home(initial_credits=0, name="Home B", contact_email="b@x.com")
    venue_b = create_venue(home_b["id"], name="B Hall")
    order_b = create_order(home_b["id"], venue_b["id"], decedent_name="B Own")
    # Funeral home A (X-User-ID = home_a.id) reaching an order owned by home B.
    headers_a = make_funeral_home_headers(home_a["id"])
    validate_error(api.get_service_order(order_b["id"], headers_a),
                   ApiErrorId.ERR_CROSS_TENANT_FORBIDDEN)
