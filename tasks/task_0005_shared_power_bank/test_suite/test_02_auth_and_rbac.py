"""
Authentication and role-based-access-control tests (PRD §2.1 + §2.7 priorities 1-2).

PRD §2.1.1 carves out four endpoints (payment-events, _clock/advance, _sweep/run,
_events/emit) as exempt from authentication.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    USER_HEADERS_PLACEHOLDER,
    assert_user,
    create_cabinet_payload,
    create_device_payload,
    create_location_partner,
    create_pricing_plan,
    create_user_payload,
    setup_borrow_environment,
    setup_funded_user,
    validate_error,
    validate_success,
    make_user_headers,
)


# ---------------------------------------------------------------------------
# ERR_UNAUTHENTICATED — priority 1 (PRD §2.7 / §2.1)
# ---------------------------------------------------------------------------


def test_missing_both_headers_unauthenticated(api):
    """PRD §2.1: "Every API request except those explicitly noted in §2.1.1
    must include both X-User-ID and X-User-Role headers. If either is
    missing, the request is rejected with HTTP 401 and error_id
    ERR_UNAUTHENTICATED."
    """
    res = api.create_user(create_user_payload(), NO_AUTH_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_missing_user_id_only_unauthenticated(api):
    """PRD §2.1: missing X-User-ID alone → ERR_UNAUTHENTICATED."""
    res = api.create_user(create_user_payload(), {"X-User-Role": "Admin"})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_missing_user_role_only_unauthenticated(api):
    """PRD §2.1: missing X-User-Role alone → ERR_UNAUTHENTICATED."""
    res = api.create_user(create_user_payload(), {"X-User-ID": "anything"})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ---------------------------------------------------------------------------
# ERR_FORBIDDEN — priority 2 (RBAC role-not-permitted)
# ---------------------------------------------------------------------------


def test_user_cannot_create_cabinet(api):
    """PRD §4 endpoint table: POST /cabinets is Admin-only.
    PRD §2.1: "If the role is well-formed but is not permitted to call the
    endpoint, the request is rejected with HTTP 403 and error_id ERR_FORBIDDEN."
    """
    create_pricing_plan(city_code="BJ")
    partner = create_location_partner()
    res = api.create_cabinet(
        create_cabinet_payload(partner["id"]), USER_HEADERS_PLACEHOLDER
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_user_cannot_create_pricing_plan(api):
    """PRD §4 endpoint table: POST /pricing-plans is Admin-only."""
    res = api.create_pricing_plan(
        {
            "city_code": "BJ",
            "hourly_rate": 3.00,
            "daily_cap": 30.00,
            "free_minutes": 5,
            "cross_city_surcharge": 10.00,
        },
        USER_HEADERS_PLACEHOLDER,
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_operator_cannot_register_user(api):
    """PRD §4 endpoint table: POST /users is Admin-only."""
    res = api.create_user(create_user_payload(), OPERATOR_HEADERS)
    validate_error(res, "ERR_FORBIDDEN")


def test_user_cannot_assign_repair_ticket(api):
    """PRD §4 endpoint table: POST /repair-tickets/{id}/assign is Operator-only."""
    res = api.assign_ticket(NON_EXISTENT_UUID, USER_HEADERS_PLACEHOLDER)
    validate_error(res, "ERR_FORBIDDEN")


def test_admin_cannot_borrow(api):
    """PRD §4 endpoint table: POST /rentals is User-only."""
    env = setup_borrow_environment()
    res = api.create_rental(
        {"cabinet_id": env["cabinet"]["id"]}, ADMIN_HEADERS
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_admin_cannot_eject_slot(api):
    """PRD §4 endpoint table: POST /cabinets/{id}/slots/{slot_index}/eject
    is Operator-only."""
    env = setup_borrow_environment()
    res = api.eject_slot(env["cabinet"]["id"], 0, ADMIN_HEADERS)
    validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Ownership checks (PRD §2.1 + §2.7 priority 7)
# ---------------------------------------------------------------------------


def test_user_cannot_read_other_users_rental(api):
    """PRD §2.7 priority 7: "the acting User's id equals the Rental.user_id
    (rejection: ERR_FORBIDDEN, HTTP 403)" applies to GET /rentals/{id}.
    PRD §2.1 also: "A User may read or act on their own Rental records and
    their own User record only."
    """
    from test_helpers import borrow_for, create_user

    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    other = create_user()
    # Other user attempts to read someone else's rental
    res = api.get_rental(rental["id"], make_user_headers(other["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_user_cannot_return_other_users_rental(api):
    """PRD §2.7 priority 7: ownership check applies to POST /rentals/{id}/return."""
    from test_helpers import borrow_for, create_user

    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    other = create_user()
    res = api.return_rental(
        rental["id"],
        {"return_cabinet_id": env["cabinet"]["id"]},
        make_user_headers(other["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Exempt endpoints (PRD §2.1.1)
# ---------------------------------------------------------------------------


def test_clock_advance_no_auth_accepted(api):
    """PRD §2.1.1: "advancing the logical clock (POST /_clock/advance)" is
    deliberately unauthenticated."""
    res = api.advance_clock({"to": "2026-01-01T10:00:00Z"})
    assert res.status_code == 200, res.json()


def test_sweep_run_no_auth_accepted(api):
    """PRD §2.1.1: "running scheduled sweeps (POST /_sweep/run)" is exempt."""
    res = api.run_sweep({"sweep_type": "overdue"})
    assert res.status_code == 200, res.json()


def test_payment_events_no_auth_accepted(api):
    """PRD §2.1.1: "receiving payment events from the upstream payment system
    (POST /payment-events)" is exempt."""
    env = setup_borrow_environment()
    from test_helpers import borrow_for

    rental = borrow_for(env["user"], env["cabinet"]["id"])
    res = api.post_payment_event(
        {
            "idempotency_key": "auth-exempt-1",
            "event_type": "PAYMENT_CONFIRMED",
            "rental_id": rental["id"],
            "amount": 1.00,
            "occurred_at": "2026-01-01T10:00:00Z",
        }
    )
    assert res.status_code == 200, res.json()


def test_events_emit_no_auth_accepted(api):
    """PRD §2.1.1: "emitting external events (POST /_events/emit)" is exempt."""
    res = api.emit_event({"event_type": "SOMETHING", "payload": {}})
    assert res.status_code == 200, res.json()


# ---------------------------------------------------------------------------
# User reads own user record (PRD §2.1)
# ---------------------------------------------------------------------------


def test_user_can_read_own_user_record(api):
    """PRD §2.1: "A User may read ... their own User record only."""
    user = setup_funded_user()
    res = api.get_user(user["id"], make_user_headers(user["id"]))
    fetched = validate_success(res, 200)
    assert_user(fetched)
    assert fetched["id"] == user["id"]


def test_user_cannot_read_other_user_record(api):
    """PRD §2.1: ownership-scoped read."""
    from test_helpers import create_user

    user_a = setup_funded_user()
    user_b = create_user()
    res = api.get_user(user_b["id"], make_user_headers(user_a["id"]))
    validate_error(res, "ERR_FORBIDDEN")
