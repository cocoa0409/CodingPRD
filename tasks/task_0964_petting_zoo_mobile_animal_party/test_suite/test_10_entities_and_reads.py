"""Entity creation defaults, schema validation, not-found errors, pagination
envelope, computed read-back, filtered listing, and immediate read-after-write
consistency (PRD §2.2, §2.3, §2.4, §2.7, §2.9, §3.1, §3.4).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    assert_customer,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Corner/entities/customer_creation_applies_defaults
# =====================================================================
def test_customer_creation_applies_defaults(api):
    """PRD §3.1: "An `Anonymous` caller registers a customer by supplying an
    `email` — unique across all customers — a `full_name`, and a
    `customer_type` of `PRIVATE`, `SCHOOL`, or `LIBRARY`."
    PRD §2.4: "`version`, an integer that starts at 1 and increments by
    exactly 1 on every mutation of that resource."

    Design: Corner/entities/customer_creation_applies_defaults
    """
    resp = api.create_customer(
        {"email": "new@x.com", "full_name": "New Cust", "customer_type": "LIBRARY"},
        TEST_USERS["anonymous_headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["response_type"] == "object"
    data = resp.json()["data"]
    assert_customer(data)
    assert data["version"] == 1, data["version"]
    assert data["email"] == "new@x.com"
    assert data["customer_type"] == "LIBRARY"


# =====================================================================
# Corner/entities/customer_create_missing_required_email
# =====================================================================
def test_customer_create_missing_required_email(api):
    """PRD §3.1: "An `Anonymous` caller registers a customer by supplying an
    `email` — unique across all customers — a `full_name`, and a
    `customer_type` of `PRIVATE`, `SCHOOL`, or `LIBRARY`."
    PRD §2.9: "**Request shape** — required body fields are present, enum
    values are valid, types are correct, an event's `end_time` falls strictly
    after its `start_time`, and ranged inputs (such as a temperament tier
    between 1 and 3, or a precipitation probability between 0 and 100) are in
    range; failures are `ERR_INVALID_REQUEST`."

    Design: Corner/entities/customer_create_missing_required_email
    """
    resp = api.create_customer(
        {"full_name": "No Email", "customer_type": "PRIVATE"},
        TEST_USERS["anonymous_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# =====================================================================
# Corner/entities/animal_create_with_invalid_enum_rejected
# =====================================================================
def test_animal_create_with_invalid_species_rejected(api):
    """PRD §3.2: "supplying the animal's `name`, its `species` (`GOAT`,
    `SHEEP`, `PONY`, `RABBIT`, `CHICKEN`, or `REPTILE`)"
    PRD §2.9: "**Request shape** — required body fields are present, enum
    values are valid, types are correct, an event's `end_time` falls strictly
    after its `start_time`, and ranged inputs (such as a temperament tier
    between 1 and 3, or a precipitation probability between 0 and 100) are in
    range; failures are `ERR_INVALID_REQUEST`."

    Design: Corner/entities/animal_create_with_invalid_enum_rejected
    """
    resp = api.create_animal(
        {"name": "Draco", "species": "DRAGON", "weight_class": "LARGE",
         "temperament_tier": 1, "base_event_fee_cents": 9999},
        TEST_USERS["operator_headers"],
    )
    # DRAGON is outside the declared species enum.
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# =====================================================================
# Corner/entities/get_booking_not_found_returns_404
# =====================================================================
def test_get_booking_not_found_returns_404(api):
    """PRD §2.7: "Each resource type has its own not-found error:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`,
    `ERR_HANDLER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and
    `ERR_ASSIGNMENT_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/get_booking_not_found_returns_404
    """
    resp = api.get_booking(NON_EXISTENT_UUID, TEST_USERS["coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND, expected_status=404)


# =====================================================================
# Corner/entities/list_animals_pagination_envelope
# =====================================================================
def test_list_animals_pagination_envelope(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. Results are sorted by `created_at` ascending.
    The `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, so a client can always tell whether
    additional pages exist."

    Design: Corner/entities/list_animals_pagination_envelope
    """
    for i in range(1, 13):
        fx.create_animal(name=f"P{i:02d}", species="CHICKEN",
                         weight_class="SMALL", temperament_tier=2,
                         base_event_fee_cents=3000)
    resp = api.list_animals(TEST_USERS["operator_headers"], params={"limit": 10})
    assert resp.json()["response_type"] == "array"
    assert isinstance(resp.json()["meta"]["api_request_id"], str)

    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 12, meta
    assert meta["has_more"] is True
    assert len(data) == 10
    assert meta["limit"] == 10
    assert meta["offset"] == 0


# =====================================================================
# Corner/endpoints/get_booking_returns_computed_quote_fields
# =====================================================================
def test_get_booking_returns_computed_quote_fields(api):
    """PRD §3.4: "it stamps every computed quote field on the booking:
    `animal_subtotal_cents`, `addon_subtotal_cents`, `discount_cents`,
    `surcharge_cents`, `travel_fee_cents`, `guest_surcharge_cents`,
    `quoted_total_cents`, `deposit_amount_cents`,
    `required_handwash_stations`, `required_staff_count`, and
    `compliance_screening_score`."
    PRD §3.4: "Customers, coordinators, operators, and compliance officers can
    list bookings — with optional `customer_id`, `venue_id`, `status`, and
    `payment_status` filters plus pagination — and fetch a single booking with
    all of its computed quote fields."

    Design: Corner/endpoints/get_booking_returns_computed_quote_fields
    """
    ctx = fx.setup_quoted_goat_booking()
    resp = api.get_booking(ctx["booking"]["id"],
                           make_customer_headers(ctx["customer"]["id"]))
    assert isinstance(resp.json()["meta"]["api_request_id"], str)
    assert resp.json()["response_type"] == "object"

    data = validate_success(resp)
    # Standard goat fixture: 8000 animal + 240 surcharge + 8000 travel.
    assert data["quoted_total_cents"] == 16240, data["quoted_total_cents"]
    assert data["travel_fee_cents"] == 8000, data["travel_fee_cents"]
    assert data["required_handwash_stations"] == 1   # ceil(20/20)
    assert data["required_staff_count"] == 1         # max(ceil(1/4), ceil(0/8))


# =====================================================================
# Corner/endpoints/list_bookings_filtered_by_customer
# =====================================================================
def test_list_bookings_filtered_by_customer(api):
    """PRD §3.4: "Customers, coordinators, operators, and compliance officers
    can list bookings — with optional `customer_id`, `venue_id`, `status`, and
    `payment_status` filters plus pagination — and fetch a single booking with
    all of its computed quote fields."

    Design: Corner/endpoints/list_bookings_filtered_by_customer
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer_a = fx.create_customer()
    customer_b = fx.create_customer()
    venue_a = fx.create_venue(customer_a["id"], name="Venue A")
    venue_b = fx.create_venue(customer_b["id"], name="Venue B",
                              address="2 Meadow Ln", distance_miles=12)
    booking_a = fx.create_booking(customer_a["id"], venue_a["id"], guest_count=10)
    fx.create_booking(customer_b["id"], venue_b["id"], guest_count=10,
                      start_time="2026-06-18T14:00:00Z",
                      end_time="2026-06-18T16:00:00Z")

    resp = api.list_bookings(TEST_USERS["coordinator_headers"],
                             params={"customer_id": customer_a["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta
    assert len(data) == 1
    assert data[0]["id"] == booking_a["id"]
    assert data[0]["customer_id"] == customer_a["id"]


# =====================================================================
# Corner/consistency_model/immediate_read_after_write_consistency
# =====================================================================
def test_immediate_read_after_write_consistency(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "it stamps every computed quote field on the booking:
    `animal_subtotal_cents`, `addon_subtotal_cents`, `discount_cents`,
    `surcharge_cents`, `travel_fee_cents`, `guest_surcharge_cents`,
    `quoted_total_cents`, `deposit_amount_cents`,
    `required_handwash_stations`, `required_staff_count`, and
    `compliance_screening_score`."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    ctx = fx.setup_quoted_goat_booking()
    q_write = ctx["quote"]["quoted_total_cents"]
    assert q_write == 16240

    q_read = fx.get_booking(ctx["booking"]["id"])["quoted_total_cents"]
    # The write response and the immediate next read agree — no lag.
    assert q_read == q_write
