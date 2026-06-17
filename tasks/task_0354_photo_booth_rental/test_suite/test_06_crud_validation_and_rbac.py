"""CRUD basics, input validation, foreign-key existence, defaults, immutability,
filtered listing, pagination, and RBAC."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, ApiErrorId, NON_EXISTENT_UUID,
    make_customer_headers, TEST_USERS,
    seed_model_and_package, create_customer, create_booking, create_booth,
    create_booth_model_payload, create_package_payload, create_booth_payload,
    create_booking_payload, create_payment_payload, pay_deposit,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["operations_manager_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]
ANON = {}  # no auth headers


# ─── Not found / existence (Queue B entities) ──────────────────────────

def test_get_booking_nonexistent_returns_not_found(api):
    """PRD §2.8: "a reference to a resource that does not exist (whether named in the
    path or supplied as a foreign key in the body) is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    res = api.get_booking(NON_EXISTENT_UUID, OPS)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_booking_create_wrong_package_id_not_found(api):
    """PRD §2.8: "a reference to a resource that does not exist (whether named in the
    path or supplied as a foreign key in the body) is rejected with `ERR_NOT_FOUND`. All
    path and body references are validated left-to-right, so the first non-existent
    reference encountered is the one reported."

    Design: Corner/entities/booking_create_wrong_package_id_not_found
    """
    customer = create_customer()
    payload = create_booking_payload(
        customer["id"], NON_EXISTENT_UUID,
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Required fields / type constraints (Queue B entities) ─────────────

def test_create_package_missing_base_price_rejected(api):
    """PRD §3.2: "A malformed payload — a missing required field, an invalid enum, an
    out-of-range number, or an `event_end` that is not strictly after `event_start` — is
    rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "It is created against a `booth_model_id` and carries a marketing `name`, a
    `base_price` (a non-negative dollar amount) that covers the package's
    `included_hours` of live coverage (at least 1) and its `included_prints` (zero or
    more) of printed copies."

    Design: Corner/entities/create_package_missing_required_field_rejected
    """
    model, _ = seed_model_and_package()
    payload = create_package_payload(model["id"], name="No Price")
    del payload["base_price"]
    res = api.create_package(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_booth_model_invalid_enum_rejected(api):
    """PRD §3.1: "A booth **model** describes a form factor and is created with a `name`
    ... a `booth_type` that is one of `OPEN_AIR`, `ENCLOSED`, `MIRROR`, or `ROAMING_360`."
    PRD §3.2: "A malformed payload — a missing required field, an invalid enum, an
    out-of-range number, or an `event_end` that is not strictly after `event_start` — is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_booth_model_invalid_enum_rejected
    """
    payload = create_booth_model_payload(name="Bad", booth_type="HOLOGRAM")
    res = api.create_booth_model(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_booking_event_end_not_after_start_rejected(api):
    """PRD §3.2: "the requested `event_start` and `event_end` (both ISO 8601 UTC instants
    for the live-coverage window, with `event_end` required to be strictly later than
    `event_start`) ... A malformed payload — a missing required field, an invalid enum,
    an out-of-range number, or an `event_end` that is not strictly after `event_start` —
    is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/booking_event_end_not_after_start_rejected
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    payload = create_booking_payload(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T18:00:00Z",
        venue_distance_miles=0)
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_booth_asset_tag_rejected(api):
    """PRD §3.1: "When the administrator creates a booth or a customer self-registers,
    uniqueness is enforced: a duplicate `asset_tag` on a booth, or a duplicate `email` on
    a customer, is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/duplicate_booth_asset_tag_rejected
    """
    model, _ = seed_model_and_package()
    validate_success(api.create_booth(create_booth_payload(model["id"], "BTH-001"), OPS), 201)
    res = api.create_booth(create_booth_payload(model["id"], "BTH-001"), OPS)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_KEY.value)


# ─── Defaults / computed / immutability (Queue B entities) ─────────────

def test_create_booth_default_status_available(api):
    """PRD §3.1: "A **booth** is registered against a `booth_model_id` with an
    `asset_tag` ... and a `status` that is one of `AVAILABLE`, `MAINTENANCE`, or
    `RETIRED`, defaulting to `AVAILABLE`."

    Design: Corner/entities/create_booth_default_status_available
    """
    model, _ = seed_model_and_package()
    booth = validate_success(api.create_booth(create_booth_payload(model["id"], "BTH-001"), OPS), 201)
    assert booth["status"] == "AVAILABLE"


def test_payment_is_append_only_no_version_field(api):
    """PRD §2.4: "The **Payment** resource is an append-only money event and carries only
    `id` and `created_at`; it has neither an `updated_at` field nor a `version` field,
    because a payment record is never mutated after it is written."

    Design: Corner/entities/payment_immutable_no_version_field
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    booking = create_booking(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    pay_deposit(booking["id"])
    payments = get_success_data(api.list_booking_payments(booking["id"], FINANCE))
    assert len(payments) == 1
    payment = payments[0]
    assert payment["kind"] == "DEPOSIT"
    assert "version" not in payment
    assert "updated_at" not in payment


# ─── Flat-topology filtered listing (Queue B entities) ─────────────────

def test_filter_booths_by_model(api):
    """PRD §4: "GET `/booths` — List booths, optionally filtered by booth model —
    OperationsManager, PlatformAdmin." PRD §2.8: "a reference to a resource that does not
    exist (whether named in the path or supplied as a foreign key in the body) is
    rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/flat_topology_filtered_list_booths_by_model
    """
    model1, _ = seed_model_and_package()
    model2 = get_success_data(api.create_booth_model(
        create_booth_model_payload(name="Enclosed", booth_type="ENCLOSED",
                                   footprint_sqft=60, max_prints_per_hour=90), ADMIN))
    create_booth(model1["id"], "BTH-001")
    create_booth(model2["id"], "BTH-002")
    data, meta = validate_paginated(
        api.list_booths(OPS, params={"booth_model_id": model1["id"]}))
    assert len(data) == 1
    assert data[0]["booth_model_id"] == model1["id"]


# ─── Pagination envelope (Queue B endpoints) ───────────────────────────

def test_list_bookings_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted
    it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses carry the following fields inside the `meta` object of the
    envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_bookings_pagination_envelope
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    create_booking(customer["id"], package["id"],
                   event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
                   venue_distance_miles=0)
    create_booking(customer["id"], package["id"],
                   event_start="2026-10-12T18:00:00Z", event_end="2026-10-12T22:00:00Z",
                   venue_distance_miles=0)
    data, meta = validate_paginated(
        api.list_bookings(OPS, params={"customer_id": customer["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── RBAC (Queue B rbac) ───────────────────────────────────────────────

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that is missing either header on a protected endpoint is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    model, _ = seed_model_and_package()
    res = api.create_booth(create_booth_payload(model["id"], "BTH-009"), ANON)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_customer_cannot_confirm_booking(api):
    """PRD §2.1: "A request whose declared role is authenticated but not permitted for
    the requested operation is rejected with `ERR_FORBIDDEN`."
    PRD §3.4: "Confirmation is the pivotal step where the operator commits scarce
    resources to the booking. It is driven by an `OperationsManager` and advances the
    booking from `DRAFT` to `CONFIRMED`."

    Design: Corner/rbac/customer_cannot_confirm_booking
    """
    model, package = seed_model_and_package()
    booth = create_booth(model["id"], "BTH-001")
    customer = create_customer()
    booking = create_booking(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    pay_deposit(booking["id"])
    booth_v = get_success_data(api.get_booth(booth["id"], OPS))["version"]
    res = api.confirm_booking(booking["id"], {"expected_booth_version": booth_v},
                              make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_customer_cannot_read_other_customers_booking(api):
    """PRD §2.1: "for the customer-owned actions — cancelling a booking and reading one's
    own booking — the booking's `customer_id` must equal the caller's `X-User-ID`; if it
    does not, the request is rejected with `ERR_NOT_BOOKING_OWNER`."

    Design: Corner/rbac/customer_cannot_read_other_customers_booking
    """
    model, package = seed_model_and_package()
    cust_a = create_customer(email="a@x.com", full_name="Cust A")
    cust_b = create_customer(email="b@x.com", full_name="Cust B")
    booking = create_booking(
        cust_a["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    res = api.get_booking(booking["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_BOOKING_OWNER.value)
