"""Authentication, driver leg-ownership, and list endpoints (pagination + FK reads).

Covers Corner sections: validations, rbac, endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    mk_terminal, mk_driver, mk_booking,
    create_terminal_payload, create_leg_payload,
    setup_dispatched_pickup,
    make_driver_headers, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]

_OUT_KW = dict(
    clock="2026-05-06T00:00:00Z", appt_start="2026-05-06T06:00:00Z",
    appt_end="2026-05-20T23:59:59Z", leg_start="2026-05-06T08:00:00Z",
    leg_end="2026-05-06T12:00:00Z",
)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    headers_without_role = {"X-User-ID": "someone"}
    resp = api.create_terminal(
        create_terminal_payload(name="NoAuth", code="NA"), headers_without_role)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_driver_completes_own_leg(api):
    """PRD §2.1: "Specifically, when a driver completes a leg, the leg's `driver_id`
    must equal `X-User-ID`; otherwise the request is rejected with `ERR_LEG_NOT_OWNED`
    (HTTP 403)."
    PRD §3.7: "**Pickup completion** captures proof of delivery. It requires the leg
    to be `DISPATCHED` and of `leg_type` `PICKUP`, and it advances the owning booking
    from `DISPATCHED` to `DELIVERED`, incrementing the booking's `version`."

    Design: Corner/rbac/driver_completes_own_leg_success
    """
    ctx = setup_dispatched_pickup(api, container_number="MSCU24", **_OUT_KW)
    owner_headers = make_driver_headers(ctx["driver_id"])
    get_success_data(api.complete_leg(ctx["leg_id"], owner_headers))
    leg = validate_success(api.get_leg(ctx["leg_id"], DISPATCHER))
    assert leg["status"] == "COMPLETED"
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["status"] == "DELIVERED"


def test_driver_cannot_complete_another_drivers_leg(api):
    """PRD §2.1: "Specifically, when a driver completes a leg, the leg's `driver_id`
    must equal `X-User-ID`; otherwise the request is rejected with `ERR_LEG_NOT_OWNED`
    (HTTP 403)."

    Design: Corner/rbac/driver_cannot_complete_others_leg
    """
    ctx = setup_dispatched_pickup(api, container_number="MSCU25", **_OUT_KW)
    other_driver = mk_driver(api, name="Drv B", license_number="LB")
    resp = api.complete_leg(ctx["leg_id"], make_driver_headers(other_driver["id"]))
    validate_error(resp, ApiErrorId.ERR_LEG_NOT_OWNED, expected_status=403)
    leg = validate_success(api.get_leg(ctx["leg_id"], DISPATCHER))
    assert leg["status"] == "DISPATCHED"


def test_list_bookings_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter bounds the number of items returned; when
    omitted it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_bookings_pagination_envelope
    """
    terminal = mk_terminal(api, name="Berth 67", code="B67")
    mk_booking(api, terminal["id"], container_number="MSCU17")
    mk_booking(api, terminal["id"], container_number="MSCU18")
    data, meta = validate_paginated(api.list_bookings(DISPATCHER, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_list_legs_filtered_by_booking(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, all list endpoints
    return resources sorted by their `created_at` timestamp in ascending order."

    Design: Corner/endpoints/filtered_list_legs_by_booking_fk
    """
    terminal = mk_terminal(api, name="Berth 68", code="B68")
    driver = mk_driver(api, name="Del FL", license_number="LFL")
    booking = mk_booking(api, terminal["id"], container_number="MSCU19")
    leg = get_success_data(api.create_leg(
        create_leg_payload(booking["id"], driver["id"], "RETURN",
                           "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z"), DISPATCHER))
    data, _meta = validate_paginated(api.list_legs(DISPATCHER, params={"booking_id": booking["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == leg["id"]
