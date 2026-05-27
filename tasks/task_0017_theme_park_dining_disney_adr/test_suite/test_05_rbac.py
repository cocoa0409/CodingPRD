"""Role-based access control — Queue B (Corner)."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    set_clock,
    setup_confirmed_reservation,
    create_guest,
    create_restaurant,
    create_dining_plan_payload,
    make_guest_headers,
    make_restaurant_headers,
    TEST_USERS,
    ApiErrorId,
)


def test_guest_cannot_seat_reservation_returns_forbidden(api):
    """PRD §4 (endpoint table): "POST /v1/reservations/{id}/seat | ... | Restaurant"
    PRD §2.1: "A request that carries valid headers but whose role is not
    authorised for the called endpoint is rejected with ERR_FORBIDDEN (HTTP 403)"

    Design: Corner/rbac/guest_cannot_seat_reservation_returns_forbidden
    """
    guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(party_size=1)
    # Advance clock into check-in grace, activate session, then check in.
    set_clock("2026-02-15T17:55:00Z")
    api.activate_park_session(ps["id"], make_guest_headers(guest["id"]))
    api.check_in_reservation(reservation["id"], make_guest_headers(guest["id"]))
    # Guest attempts the Restaurant-only `seat` action.
    res = api.seat_reservation(reservation["id"], make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_restaurant_cannot_create_dining_plan_returns_forbidden(api):
    """PRD §4 (endpoint table): "POST /v1/dining-plans ... PlatformAdmin"
    PRD §2.1: a role not authorised for an endpoint receives ERR_FORBIDDEN.

    Design: Corner/rbac/restaurant_cannot_create_dining_plan_returns_forbidden
    """
    set_clock("2026-01-15T12:00:00Z")
    restaurant = create_restaurant(name="RbacR", park_code="EPCOT")
    guest = create_guest(email="rbac_target@x.com")
    payload = create_dining_plan_payload(
        guest_id=guest["id"],
        tier="STANDARD",
        table_service_credits_initial=5,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-12-31T00:00:00Z",
    )
    res = api.create_dining_plan(payload, make_restaurant_headers(restaurant["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_unauthenticated_request_without_user_role_returns_401(api):
    """PRD §2.1: "Every API request MUST carry two headers: X-User-ID, identifying
    the calling principal, and X-User-Role, identifying the role the caller is
    acting under. ... A request that omits either header — or carries a header that
    the server cannot parse — is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/unauthenticated_request_without_user_role_returns_401
    """
    set_clock("2026-01-15T12:00:00Z")
    # No X-User-ID / X-User-Role headers at all.
    res = api.list_restaurants({})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
