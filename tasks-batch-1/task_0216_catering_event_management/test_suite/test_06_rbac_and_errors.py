"""RBAC and remaining error-path tests: role-forbidden, ownership, unauthenticated, leg
out-of-order, and delivery-leg window validation.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CAPTAIN = TEST_USERS["captain_headers"]


# =====================================================================
# Queue B — RBAC
# =====================================================================
def test_client_cannot_confirm_order(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: confirm is authorized for SalesCoordinator only.

    Design: Corner/rbac/client_cannot_confirm_order
    """
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    validate_error(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]},
                          ctx["client_headers"]),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "DRAFT"


def test_client_cannot_cancel_another_clients_order(api):
    """PRD §2.1: "when a `Client` acts on an order or on a change request, the system resolves
    the order's `client_id` ... and requires it to equal `X-User-ID`; a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/client_cannot_cancel_other_clients_order
    """
    cat = fx.setup_catalog(client_overrides={"company_name": "ClientA", "billing_email": "a@x.com"})
    client_b = fx.create_client(company_name="ClientB", billing_email="b@x.com")
    headers_a = make_client_headers(cat["client"]["id"])
    from test_helpers import create_order_payload
    order = validate_success(
        api.create_order(
            create_order_payload(cat["client"]["id"], cat["package"]["id"], cat["venue"]["id"],
                                 booked_headcount=80),
            headers_a,
        ),
        expected_status=201,
    )
    # Client B attempts to cancel A's order.
    headers_b = make_client_headers(client_b["id"])
    validate_error(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]}, headers_b),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "DRAFT"


def test_eventcaptain_cannot_create_package(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: package creation is authorized for CateringAdmin only.

    Design: Corner/rbac/eventcaptain_cannot_create_package
    """
    validate_error(
        api.create_package(
            {"name": "Sneaky", "per_head_cents": 5000, "min_headcount": 1, "lead_time_hours": 24},
            CAPTAIN,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    # No X-User-ID / X-User-Role headers at all.
    validate_error(
        api.create_venue(
            {"name": "Hall", "tax_rate_bps": 875, "service_fee_bps": 2000, "max_overlapping_events": 5},
            {"Content-Type": "application/json"},
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


# =====================================================================
# Queue B — errors
# =====================================================================
def test_dispatch_leg_out_of_order_rejected(api):
    """PRD §3.11: "the route order is respected, meaning `preceding_leg_id` is null or the
    preceding leg's `stop_status` is `DISPATCHED` or `DELIVERED` ... A dispatch that violates
    route ordering or exceeds vehicle capacity is rejected with `ERR_LEG_OUT_OF_ORDER`".

    Design: Corner/errors/leg_out_of_order_dispatch_returns_error
    """
    ctx = fx.setup_guaranteed_order_with_route_and_leg(
        guaranteed_headcount=80,
        window_start="2026-09-01T15:00:00Z", window_end="2026-09-01T16:00:00Z",
    )
    order, route, leg1 = ctx["order"], ctx["route"], ctx["leg"]  # leg1 still PLANNED
    leg2 = fx.create_leg(order["id"], route["id"],
                         "2026-09-01T18:00:00Z", "2026-09-01T19:00:00Z", preceding_leg_id=leg1["id"])
    validate_error(
        api.dispatch_delivery_leg(leg2["id"], {"expected_route_version": fx.route_version(route["id"])},
                                  CAPTAIN),
        ApiErrorId.ERR_LEG_OUT_OF_ORDER.value,
    )
    leg2_after = validate_success(api.get_delivery_leg(leg2["id"], CAPTAIN))
    assert leg2_after["stop_status"] == "PLANNED"


def test_delivery_leg_window_end_before_start_rejected(api):
    """PRD §3.11: "a `window_start` and a `window_end` (the earliest and latest arrival at the
    stop, with `window_end` required to be strictly after `window_start`, else
    `ERR_VALIDATION_WINDOW`)".

    Design: Corner/errors/leg_window_end_before_start_returns_validation_window
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    route = fx.create_route(vehicle_capacity_legs=3)
    ctx = fx.create_draft_order(booked_headcount=80)
    order = fx.confirm_order(ctx["order"])
    validate_error(
        api.create_delivery_leg(
            {"order_id": order["id"], "route_id": route["id"],
             "window_start": "2026-09-01T16:00:00Z", "window_end": "2026-09-01T15:00:00Z"},
            COORD,
        ),
        ApiErrorId.ERR_VALIDATION_WINDOW.value,
    )
