"""CRUD / entity-shape claims, gate redemption lifecycle, and RBAC.

Covers the corner-design entities, endpoints (gate redemption), and rbac instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_driver_headers, make_host_headers, TEST_USERS,
    setup_host_driver_spot, setup_reserved_booking, set_clock, create_booking,
    register_host, register_driver, create_spot, log_violation,
    create_host_payload, create_spot_payload, create_booking_payload, redeem_payload,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Corner: entities ────────────────────────────────────────────────────────

def test_create_spot_returns_201_listed_version_1(api):
    """PRD §3.2: "Every new spot begins LISTED; its `listing_status` is one of `LISTED` or
    `UNLISTED`."
    PRD §2.4: "`version` — an integer that starts at its initial value and increments by one
    on every mutation."

    POST /spots with all required fields returns 201 with listing_status LISTED and version 1.

    Design: Corner/entities/create_spot_returns_201_with_all_fields
    """
    host = register_host()
    res = api.create_spot(create_spot_payload(host["id"], zone_code="Z"), make_host_headers(host["id"]))
    spot = validate_success(res, 201)
    assert spot["listing_status"] == "LISTED"
    assert spot["version"] == 1, spot["version"]


def test_get_nonexistent_booking_returns_not_found(api):
    """PRD §2.8: "the server validates referenced resources left to right and rejects the
    first identifier that does not resolve to an existing resource with `ERR_NOT_FOUND`
    (HTTP 404)."

    GET /bookings/{id} with a non-existent UUID returns ERR_NOT_FOUND.

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    driver = register_driver()
    res = api.get_booking(NON_EXISTENT_UUID, make_driver_headers(driver["id"]))
    validate_error(res, "ERR_NOT_FOUND")


def test_create_spot_missing_required_field_rejected(api):
    """PRD §3.2: "the spot's pricing: `base_hourly_cents` (at least 100), `base_daily_cents`
    (at least 500), and `monthly_flat_cents` (at least 5000)."
    PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request".

    POST /spots omitting base_hourly_cents (required, no default) returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_spot_missing_required_field_returns_invalid_request
    """
    host = register_host()
    payload = create_spot_payload(host["id"], zone_code="Z")
    del payload["base_hourly_cents"]
    res = api.create_spot(payload, make_host_headers(host["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_host_default_platform_fee_bps(api):
    """PRD §3.1: "A host may also supply `platform_fee_bps` ... and when omitted it defaults
    to 1500 (15%)."

    Omitting platform_fee_bps on POST /hosts applies the default 1500.

    Design: Corner/entities/create_host_default_platform_fee_bps_applied
    """
    payload = create_host_payload()
    payload.pop("platform_fee_bps", None)
    host = validate_success(api.create_host(payload, TEST_USERS["anonymous_headers"]), 201)
    assert host["platform_fee_bps"] == 1500, host["platform_fee_bps"]


def test_booking_quoted_amount_is_server_computed(api):
    """PRD §3.3: "At creation the server computes and freezes `quoted_amount_cents`".

    A 2h HOURLY booking at base 400 has a server-computed quoted_amount_cents of 800.

    Design: Corner/entities/booking_quoted_amount_is_computed_input_ignored
    """
    host, driver, spot = setup_host_driver_spot(
        spot_overrides={"base_hourly_cents": 400, "zone_code": "Z5C"}, wallet_cents=5000)
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 800, booking["quoted_amount_cents"]


def test_create_booking_invalid_rate_kind_rejected(api):
    """PRD §3.3: "a `rate_kind` of `HOURLY`, `DAILY`, or `MONTHLY`".
    PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request".

    rate_kind not in {HOURLY,DAILY,MONTHLY} returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_booking_invalid_rate_kind_enum_rejected
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000, spot_overrides={"zone_code": "Z6C"})
    res = api.create_booking(
        create_booking_payload(spot["id"], driver["id"], "YEARLY",
                               "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"]),
        make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_spot_nonexistent_host_returns_not_found(api):
    """PRD §2.8: "for any write whose body references other resources, the server validates
    referenced resources left to right and rejects the first identifier that does not resolve
    to an existing resource with `ERR_NOT_FOUND` (HTTP 404)."

    POST /spots with a non-existent host_id in the body returns ERR_NOT_FOUND.

    Design: Corner/entities/spot_requires_existing_host_parent
    """
    host = register_host()
    payload = create_spot_payload("00000000-0000-0000-0000-000000000000", zone_code="Z")
    res = api.create_spot(payload, make_host_headers(host["id"]))
    validate_error(res, "ERR_NOT_FOUND")


def test_list_spots_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object
    of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    GET /spots filtered by host_id returns an array envelope containing the host's one spot,
    with total_count 1 and has_more false.

    Design: Corner/entities/list_spots_pagination_envelope
    """
    host = register_host()
    spot = create_spot(host["id"], zone_code="Z8C")
    data, meta = validate_paginated(
        api.list_spots(make_host_headers(host["id"]), params={"host_id": host["id"], "limit": 10, "offset": 0}))
    ids = [s["id"] for s in data]
    assert spot["id"] in ids
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False


def test_list_spots_invalid_pagination_rejected(api):
    """PRD §2.3: "A `limit` outside the range of 1 to 100 inclusive, or an `offset` below 0,
    is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    GET /spots with limit=0 (below the minimum of 1) returns ERR_INVALID_PAGINATION.

    Design: Corner/entities/list_spots_invalid_pagination_rejected
    """
    host = register_host()
    res = api.list_spots(make_host_headers(host["id"]), params={"limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION")


# ─── Corner: endpoints / gate redemption ─────────────────────────────────────

def test_gate_redeem_decrements_then_blocks_at_zero(api):
    """PRD §3.4: "The minted `AccessPass` references its `booking_id`, carries an opaque
    single-spot `qr_token`, and starts with `gate_opens_remaining` of 2".
    PRD §3.4: "each successful redemption decrements that pass's `gate_opens_remaining` by
    one. Redemption requires a valid access pass with `gate_opens_remaining` greater than 0
    that matches the booking; a redemption against a missing pass, a non-matching pass, or a
    pass whose `gate_opens_remaining` has reached 0 is rejected with `ERR_GATE_PASS_INVALID`
    (HTTP 409)."

    An AccessPass minted at check-in starts at 2; two redeems drive it to 0; a third redeem
    is rejected with ERR_GATE_PASS_INVALID.

    Design: Corner/endpoints/gate_redeem_decrements_remaining_then_blocks_at_zero
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "ZEP1"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    set_clock("2026-04-08T10:00:00Z")
    get_success_data(api.check_in_booking(booking["id"], make_driver_headers(driver["id"])))

    passes = get_success_data(api.get_booking_access_pass(booking["id"], make_driver_headers(driver["id"])))
    token = passes[0]["qr_token"]

    r1 = get_success_data(api.redeem_access_pass(redeem_payload(token), make_driver_headers(driver["id"])))
    assert r1["gate_opens_remaining"] == 1, r1
    r2 = get_success_data(api.redeem_access_pass(redeem_payload(token), make_driver_headers(driver["id"])))
    assert r2["gate_opens_remaining"] == 0, r2
    res3 = api.redeem_access_pass(redeem_payload(token), make_driver_headers(driver["id"]))
    validate_error(res3, "ERR_GATE_PASS_INVALID")


# ─── Corner: rbac ────────────────────────────────────────────────────────────

def test_driver_cannot_create_spot(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: "POST | `/spots` | Create (list) a parking spot | Host".

    A Driver calling POST /spots (Host-only) returns ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/driver_cannot_create_spot_forbidden_role
    """
    driver = register_driver()
    res = api.create_spot(create_spot_payload(driver["id"], zone_code="Z"),
                          make_driver_headers(driver["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_host_cannot_confirm_violation(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/violations/{id}/confirm` | Confirm a violation; assess points; cascade
    | PlatformAdmin".

    A Host calling POST /violations/{id}/confirm (PlatformAdmin-only) returns
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/host_cannot_confirm_violation_forbidden_role
    """
    host, driver, spot, booking = setup_reserved_booking(spot_overrides={"zone_code": "ZRB2"})
    vr = log_violation(host["id"], booking["id"], "OVERSTAY", 3)
    res = api.confirm_violation(vr["id"], make_host_headers(host["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_driver_cannot_check_in_others_booking(api):
    """PRD §2.1: "a driver may check in, check out, cancel, or offer a `Booking` only when
    its `driver_id` equals their own `X-User-ID` ... A request by an authenticated user of
    the correct role who is nonetheless not the owner or holder of the target resource is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    A Driver (D_b) checking in a booking held by another driver (D_a) returns
    ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/driver_cannot_check_in_others_booking_not_owner
    """
    host = register_host()
    da = register_driver()
    db = register_driver()
    from test_helpers import fund_driver
    fund_driver(da["id"], 5000)
    spot = create_spot(host["id"], zone_code="ZRB3", overstay_grace_minutes=15)
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], da["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    set_clock("2026-04-08T10:05:00Z")
    res = api.check_in_booking(booking["id"], make_driver_headers(db["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "When either header is missing or malformed on a protected endpoint, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Calling GET /bookings with no auth headers returns ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.list_bookings(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
