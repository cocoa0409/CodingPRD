"""Catalog creation, booking creation guards, listing envelope, and the
authentication / role-permission perimeter.

Queue B (Corner): entities, state_machines, validations, endpoints, rbac.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    validate_success, validate_error, validate_paginated,
    assert_client, assert_booking,
    make_client_headers,
    ApiErrorId, NON_EXISTENT_UUID,
)

ERR = ApiErrorId


# ─── Corner/entities: client creation ─────────────────────────────────────

def test_client_creation_returns_active_client(api, ops_headers):
    """PRD §3.1: "Each customer is registered as a Client with a `company_name` and
    a `contact_email`, the latter unique per client. A Client's `status` starts at
    `ACTIVE` and may later move to `SUSPENDED` or `CLOSED`."
    PRD §4: "Operations that create a new resource — whether a stand-alone catalog
    entry or a new child resource within a booking — return a `201 Created` status
    code."

    POST /clients with both required fields returns 201, a server-minted UUID id,
    and status ACTIVE.

    Design: Corner/entities/client_creation_required_fields
    """
    res = api.create_client(
        f.create_client_payload(company_name="Acme", contact_email="acme@x.com"),
        ops_headers)
    client = validate_success(res, 201)
    assert_client(client)
    assert client["status"] == "ACTIVE", client
    assert client["company_name"] == "Acme", client
    assert client["contact_email"] == "acme@x.com", client


def test_client_creation_missing_contact_email_rejected(api, ops_headers):
    """PRD §2.10: "A request body that is structurally malformed — a missing required
    field or a wrongly typed value — is rejected with the generic `ERR_VALIDATION`
    (HTTP 400)."
    PRD §3.1: "Each customer is registered as a Client with a `company_name` and a
    `contact_email`, the latter unique per client."

    Omitting the required contact_email fails with ERR_VALIDATION.

    Design: Corner/entities/client_missing_contact_email_rejected
    """
    res = api.create_client({"company_name": "Acme"}, ops_headers)
    validate_error(res, ERR.ERR_VALIDATION, expected_status=400)


# ─── Corner/state_machines: booking initial state ─────────────────────────

def test_booking_created_in_quote_status(api):
    """PRD §3.2: "The new booking lands in `QUOTE` status, and its financial fields —
    `quoted_subtotal_cents`, `quoted_travel_fee_cents`, `quoted_total_cents`, and
    `deposit_due_cents` — stay at zero until the quote is submitted."

    A newly created EventBooking starts in QUOTE.

    Design: Corner/state_machines/booking_initial_state_quote
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    booking = fx.create_quote_booking(ctx)
    assert_booking(booking)
    assert booking["status"] == "QUOTE", booking


# ─── Corner/entities: unknown identifier ──────────────────────────────────

def test_get_booking_with_unknown_id_returns_not_found(api, ops_headers):
    """PRD §2.8: "When a path contains multiple identifiers — for example a booking
    followed by one of its collections — the server confirms each identifier in
    sequence, and the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)
    at the first identifier that does not resolve to an existing resource within
    its declared parent."

    GET /bookings/{random-uuid} is rejected with ERR_RESOURCE_NOT_FOUND.

    Design: Corner/entities/not_found_on_random_uuid
    """
    res = api.get_booking(NON_EXISTENT_UUID, ops_headers)
    validate_error(res, ERR.ERR_RESOURCE_NOT_FOUND, expected_status=404)


# ─── Corner/validations: creation-time business guards ────────────────────

def test_venue_hookup_mismatch_when_power_required_but_not_provided(api):
    """PRD §3.2: "Venue compatibility follows: if the cart's `requires_power_hookup`
    is true then `venue_provides_power` must be true, and if the cart's
    `requires_water_hookup` is true then `venue_provides_water` must be true, with
    mismatches rejected as `ERR_VENUE_HOOKUP_MISMATCH` (HTTP 422)."

    A cart that must plug into venue power cannot be booked at a venue that does
    not provide power.

    Design: Corner/validations/venue_hookup_mismatch_power_required_but_not_provided
    """
    ctx = fx.setup_base_catalog(
        package_kind="FLAT", cart_overrides={"requires_power_hookup": True})
    res = api.create_booking(
        f.create_booking_payload(
            ctx["client"]["id"], ctx["package"]["id"], ctx["cart"]["id"],
            ctx["zone"]["id"], venue_provides_power=False,
            venue_provides_water=True),
        ctx["client_headers"])
    validate_error(res, ERR.ERR_VENUE_HOOKUP_MISMATCH, expected_status=422)


def test_guest_count_above_package_max_rejected(api):
    """PRD §3.2: "Guest count is checked last: `guest_count` must be at least one and
    at most the package's `max_guests`, otherwise the request fails with
    `ERR_GUEST_COUNT_OUT_OF_RANGE` (HTTP 422). The package's `max_guests` is a hard
    validation boundary, never a clamp."

    guest_count=81 against a package with max_guests=80 is rejected.

    Design: Corner/validations/guest_count_above_package_max_rejected
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT",
                                package_overrides={"max_guests": 80})
    res = api.create_booking(
        f.create_booking_payload(
            ctx["client"]["id"], ctx["package"]["id"], ctx["cart"]["id"],
            ctx["zone"]["id"], guest_count=81),
        ctx["client_headers"])
    validate_error(res, ERR.ERR_GUEST_COUNT_OUT_OF_RANGE, expected_status=422)


# ─── Corner/endpoints: filtered listing envelope ──────────────────────────

def test_list_bookings_filtered_by_status_returns_paginated_array(api, ops_headers):
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.3: "Beyond pagination, several list endpoints accept domain filters — for
    example `status` on most catalog and lifecycle lists, `skill_level` on the
    barista roster, `pricing_model` on the package catalog, and `kind` on a
    booking's payment history; the bookings list itself may be narrowed by
    `client_id`, `cart_id`, `package_id`, or `travel_zone_id`."

    With two bookings in QUOTE, GET /bookings?status=QUOTE returns an array
    envelope whose total_count is 2.

    Design: Corner/endpoints/list_bookings_filtered_by_status
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    fx.create_quote_booking(
        ctx, event_start="2026-05-10T10:00:00Z", event_end="2026-05-10T12:00:00Z")
    fx.create_quote_booking(
        ctx, event_start="2026-05-11T10:00:00Z", event_end="2026-05-11T12:00:00Z")

    res = api.list_bookings(ops_headers, params={"status": "QUOTE"})
    data, meta = validate_paginated(res)
    assert res.json().get("response_type") == "array", res.text
    assert meta["total_count"] == 2, meta
    assert len(data) == 2, data
    assert all(row["status"] == "QUOTE" for row in data), data


# ─── Corner/rbac: authentication and role perimeter ───────────────────────

def test_missing_user_context_headers_rejected(api):
    """PRD §2.1: "Failure to provide both headers, or supplying a role outside this
    declared set, results in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error
    (HTTP 400)."

    A request with no X-User-ID / X-User-Role headers is rejected.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    res = api.list_clients(headers={})
    validate_error(res, ERR.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   expected_status=400)


def test_client_role_cannot_create_cart(api):
    """PRD §2.1: "Access to individual operations is further restricted by role; an
    attempt to perform an action outside the caller's designated role is rejected
    with an `ERR_UNAUTHORIZED` error (HTTP 403)."
    PRD §4: POST /coffee-cart/carts — "Register a new coffee cart" — is authorized
    for OperationsManager only.

    A Client attempting to register a cart is denied.

    Design: Corner/rbac/client_cannot_create_cart
    """
    fx.set_clock()
    client = fx.create_client()
    res = api.create_cart(f.create_cart_payload(cart_code="CART-X"),
                          make_client_headers(client["id"]))
    validate_error(res, ERR.ERR_UNAUTHORIZED, expected_status=403)
