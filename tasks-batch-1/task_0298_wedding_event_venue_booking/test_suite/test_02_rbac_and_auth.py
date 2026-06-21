"""Authentication, role permission, and resource-ownership enforcement.

Translates Corner-design `rbac` instances. Each cites the verbatim PRD rule.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    build_user_headers,
    ApiErrorId,
    TEST_USERS,
    create_payment_payload,
    create_inventory,
    create_inquiry_booking,
    make_client_headers,
)

VA = TEST_USERS["venue_admin_headers"]


def test_client_cannot_post_payment(api):
    """PRD §2.1: "When a recognized role attempts an operation that its role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §2.1: "A `FinanceOfficer` owns payment posting and refunds".

    Design: Corner/rbac/client_cannot_post_payment
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    res = api.post_payment(
        booking["id"], create_payment_payload("INBOUND", 100_000, "CARD"),
        inv["client_headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_client_cannot_confirm_booking(api):
    """PRD §2.1: "When a recognized role attempts an operation that its role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §2.1: "A `Coordinator` is venue-side staff who drives the booking lifecycle,
    manages holds, vendors, walkthroughs, and reschedule counters."

    Design: Corner/rbac/client_cannot_confirm_booking
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    res = api.confirm_booking(booking["id"], inv["client_headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_client_cannot_act_on_other_clients_booking(api):
    """PRD §2.1: "For client-owned operations, the acting `X-User-ID` must equal the
    target booking's `client_id` ... A violation of either ownership rule is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/client_cannot_act_on_other_clients_booking
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    # A second, distinct client.
    client_b = get_success_data(api.create_client(
        {"full_name": "Client B", "email": "other-client-b@example.com"}, VA))
    res = api.cancel_booking(booking["id"], make_client_headers(client_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    # The booking is untouched.
    fetched = get_success_data(api.get_booking(booking["id"], inv["client_headers"]))
    assert fetched["booking_status"] == "INQUIRY"


def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    bogus = build_user_headers("nobody-1", "Nobody")
    res = api.create_venue({"name": "V"}, bogus)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
