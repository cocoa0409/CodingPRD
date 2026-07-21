"""RBAC enforcement, base CRUD echoes, not-found links, and list pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, NO_AUTH_HEADERS,
    create_tour_product, create_departure,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ---------------------------------------------------------------------------
# Base creation + computed defaults
# ---------------------------------------------------------------------------

def test_create_tour_product_returns_201_and_echoes_fields(api, ops_headers):
    """PRD §4: "Operations that create a new, stand-alone resource return a 201 Created status."
    PRD §3.1: "A tour product is a reusable catalog template created with a name, a
    duration_days count (which must be at least 1), and a base_price_per_person_cents list
    price (which must be zero or greater, expressed in cents before any occupancy adjustment)."

    Design: Corner/entities/corner_create_tour_product_returns_201_with_fields
    """
    resp = api.create_tour_product(
        {"name": "Sampler", "duration_days": 2, "base_price_per_person_cents": 100000},
        ops_headers,
    )
    data = validate_success(resp, 201)
    assert data["duration_days"] == 2, f"expected duration_days 2, got {data['duration_days']}"
    assert data["base_price_per_person_cents"] == 100000, \
        f"expected base_price 100000, got {data['base_price_per_person_cents']}"


def test_new_coach_status_initialized_available(api, ops_headers):
    """PRD §3.1: "A coach is created with a fleet code, a seat_capacity (at least 1 seat),
    and a day_rate_cents operating cost; its status begins at AVAILABLE."

    Design: Corner/entities/corner_coach_status_initialized_available
    """
    resp = api.create_coach({"code": "CX", "seat_capacity": 40, "day_rate_cents": 50000}, ops_headers)
    data = validate_success(resp, 201)
    assert data["status"] == "AVAILABLE", f"expected AVAILABLE, got {data['status']}"


# ---------------------------------------------------------------------------
# Validation / not-found
# ---------------------------------------------------------------------------

def test_get_nonexistent_departure_returns_404(api, auditor_headers):
    """PRD §2.8: "the first identifier that does not correspond to an existing resource
    causes the request to be rejected with ERR_NOT_FOUND before any inner identifier or
    referenced foreign key is examined."

    Design: Corner/entities/corner_get_departure_nonexistent_returns_404
    """
    resp = api.get_departure(NON_EXISTENT_UUID, auditor_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_booking_without_pax_count_returns_400(api, sales_headers):
    """PRD §2.8: "then request-body well-formedness — required fields present, enum values
    valid, amounts positive (ERR_VALIDATION)"
    PRD §3.5: "a pax_count of passengers (at least 1)"

    Design: Corner/entities/corner_create_booking_missing_pax_count_returns_400
    """
    tp = create_tour_product()
    dep = create_departure(tp["id"])
    fx.publish_departure(dep["id"])
    resp = api.create_booking(
        {"departure_id": dep["id"], "lead_name": "NoPax", "rooms_requested": 0},
        sales_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_booking_nonexistent_departure_returns_404(api, sales_headers):
    """PRD §2.8: "Referenced foreign-key identifiers carried in a request body are likewise
    checked for existence, and a reference to a nonexistent resource yields ERR_NOT_FOUND."

    Design: Corner/endpoints/corner_create_booking_nonexistent_departure_returns_404
    """
    resp = api.create_booking(
        {"departure_id": NON_EXISTENT_UUID, "lead_name": "Ghost", "pax_count": 2, "rooms_requested": 0},
        sales_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_add_passenger_with_nonexistent_roommate_returns_404(api, sales_headers):
    """PRD §2.8: "Referenced foreign-key identifiers carried in a request body are likewise
    checked for existence, and a reference to a nonexistent resource yields ERR_NOT_FOUND."

    Design: Corner/endpoints/corner_passenger_roommate_nonexistent_returns_404
    """
    tp = create_tour_product()
    dep = create_departure(tp["id"])
    fx.publish_departure(dep["id"])
    bk = fx.create_booking(dep["id"], pax_count=2, rooms_requested=0)
    resp = api.create_passenger(
        {"booking_id": bk["id"], "full_name": "Rm1", "roommate_passenger_id": NON_EXISTENT_UUID},
        sales_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_salesagent_cannot_create_coach(api, sales_headers):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    PRD §2.1: "An OpsManager owns the catalog, the fleet, the departure lifecycle, resource
    assignment, hotel blocks, and the logical clock."

    Design: Corner/rbac/corner_salesagent_cannot_create_coach
    """
    resp = api.create_coach({"code": "Nope", "seat_capacity": 10, "day_rate_cents": 50000}, sales_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_opsmanager_cannot_create_booking(api, ops_headers):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    PRD §2.1: "A SalesAgent owns reservations — bookings, passengers, payments, the booking
    lifecycle, and voucher redemption."

    Design: Corner/rbac/corner_opsmanager_cannot_create_booking
    """
    tp = create_tour_product()
    dep = create_departure(tp["id"])
    fx.publish_departure(dep["id"])
    resp = api.create_booking(
        {"departure_id": dep["id"], "lead_name": "Rb Party", "pax_count": 2, "rooms_requested": 0},
        ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_salesagent_cannot_settle_departure(api, sales_headers):
    """PRD §2.1: "A Finance operator holds the segregated authority to settle a departure."
    PRD §2.1: "When a caller is authenticated but their role is not permitted to perform the
    requested operation, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/corner_salesagent_cannot_settle_departure
    """
    tp = create_tour_product()
    dep = create_departure(tp["id"])
    resp = api.settle_departure(dep["id"], sales_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized role, is
    rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/corner_missing_auth_header_returns_401
    """
    resp = api.get_departure(NON_EXISTENT_UUID, NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Listing pagination envelope
# ---------------------------------------------------------------------------

def test_list_bookings_pagination_envelope(api, ops_headers):
    """PRD §2.3: "The limit parameter caps the number of items returned"
    PRD §2.3: "Every list response carries limit, offset, total_count, and has_more inside
    the meta object of the envelope."

    Design: Corner/endpoints/corner_list_bookings_pagination_envelope
    """
    tp = create_tour_product()
    dep = create_departure(tp["id"])
    fx.publish_departure(dep["id"])
    fx.create_booking(dep["id"], lead_name="Pg P1", pax_count=2, rooms_requested=0)
    fx.create_booking(dep["id"], lead_name="Pg P2", pax_count=2, rooms_requested=0)
    resp = api.list_bookings(ops_headers, params={"departure_id": dep["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more true, got {meta['has_more']}"
    assert len(data) == 1, f"expected page length 1, got {len(data)}"
