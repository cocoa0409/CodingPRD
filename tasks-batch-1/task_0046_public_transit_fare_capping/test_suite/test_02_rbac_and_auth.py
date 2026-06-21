"""Role-based access control and authentication (PRD §2.1).

Covers Corner queue (B) instances from the rbac section.
"""
import pytest
from test_helpers import (
    validate_error,
    create_tap_payload,
    TEST_USERS, make_rider_headers,
    set_clock, make_fare_product, register_rider, add_funding_source, open_week,
    record_tap,
    ApiErrorId,
)


def test_rider_cannot_settle_tap_forbidden_role(api):
    """PRD §2.1: "If the headers are well-formed and the role is known but that role
    is not permitted to invoke the requested endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: settle (`POST /taps/{id}/settle`) is authorized for `PaymentGateway`.

    Design: Corner/rbac/rider_cannot_settle_tap_forbidden_role
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="rn@x.com")
    fs = add_funding_source(rider["id"])
    week = open_week(rider["id"], zone_code="ZONEX")
    tap = record_tap(rider["id"], week["id"], fs["id"], "2026-06-01T09:00:00Z")
    # Rider tries to settle its own tap — settle is PaymentGateway-exclusive.
    res = api.settle_tap(tap["id"], make_rider_headers(rider["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_rider_cannot_act_on_other_riders_tap_not_owner(api):
    """PRD §2.1: "when a `Rider` records a tap, fetches a tap, attaches a funding
    source, applies for a reduced-fare card, or requests a fare quote, the
    `rider_id` carried by (or implied by) the targeted resource must equal the
    caller's `X-User-ID`; if it does not, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/rider_cannot_act_on_other_riders_tap_not_owner
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-01T12:00:00Z")
    rider_a = register_rider(home_zone_code="ZONEX", email="ra@x.com")
    rider_b = register_rider(home_zone_code="ZONEX", email="rbb@x.com")
    fs_b = add_funding_source(rider_b["id"])
    week_b = open_week(rider_b["id"], zone_code="ZONEX")
    # Rider A acts as itself but supplies Rider B's rider_id/week/funding source.
    res = api.create_tap(
        create_tap_payload(rider_b["id"], week_b["id"], fs_b["id"],
                           "2026-06-01T09:00:00Z"),
        make_rider_headers(rider_a["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "If a protected endpoint is called without both headers, or with an
    `X-User-Role` that is not one of these five, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="ru@x.com")
    fs = add_funding_source(rider["id"])
    week = open_week(rider["id"], zone_code="ZONEX")
    # No X-User-Role / X-User-ID headers at all (Content-Type only).
    res = api.create_tap(
        create_tap_payload(rider["id"], week["id"], fs["id"], "2026-06-01T09:00:00Z"),
        {"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
