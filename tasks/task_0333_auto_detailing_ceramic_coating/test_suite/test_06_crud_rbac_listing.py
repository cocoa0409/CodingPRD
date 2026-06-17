"""CRUD basics, input validation, system/computed-field generation, FK and
path existence, pagination, immutability of catalog rows, RBAC and ownership.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_customer_headers, NON_EXISTENT_UUID,
    set_clock, seed_package, seed_vehicle_size_rate,
    create_customer, create_mobile_unit,
    book_mobile_appointment,
)
from test_helpers.factories import (
    create_customer_payload, create_appointment_payload, create_package_payload,
)
from test_helpers.test_users import TEST_USERS

SCHEDULER = TEST_USERS["scheduler_headers"]
DETAILER = TEST_USERS["detailer_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / create_customer_returns_201_with_defaults
# ──────────────────────────────────────────────────────────────────────

def test_create_customer_returns_201_with_defaults():
    """PRD §3.1: "a newly registered customer starts in the `BRONZE` loyalty tier with both spend totals at zero."
    PRD §2.4: "The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation"

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    res = api_client.create_customer(
        create_customer_payload(email="new@x.com", full_name="New Cust"), SCHEDULER
    )
    cust = validate_success(res, 201)
    assert cust["loyalty_tier"] == "BRONZE"
    assert cust["chronological_lifetime_spend_cents"] == 0
    assert cust["projected_lifetime_spend_cents"] == 0
    assert cust["version"] == 1


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / get_customer_not_found_returns_404
# ──────────────────────────────────────────────────────────────────────

def test_get_customer_not_found_returns_404():
    """PRD §2.5: "the first identifier in the path that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any later identifier is examined. This applies to every path that targets a resource by its `id`."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api_client.get_customer(NON_EXISTENT_UUID, SCHEDULER)
    validate_error(res, "ERR_NOT_FOUND", 404)


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / create_customer_missing_required_field_returns_invalid_request
# ──────────────────────────────────────────────────────────────────────

def test_create_customer_missing_full_name_returns_invalid_request():
    """PRD §3.1: "Registering a customer captures the customer's `email` — which must be unique across customers, non-empty, and contain an at-sign — and a non-empty `full_name`; a newly registered customer starts in the `BRONZE` loyalty tier with both spend totals at zero."
    PRD §2.9: "the request body checked for well-formedness — required fields present, enum values legal, numbers in range, and an email containing an at-sign (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_customer_missing_required_field_returns_invalid_request
    """
    res = api_client.create_customer({"email": "x@x.com"}, SCHEDULER)
    validate_error(res, "ERR_INVALID_REQUEST", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / create_customer_email_without_at_returns_invalid_request
# ──────────────────────────────────────────────────────────────────────

def test_create_customer_email_without_at_returns_invalid_request():
    """PRD §2.9: "an email containing an at-sign (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "Registering a customer captures the customer's `email` — which must be unique across customers, non-empty, and contain an at-sign"

    Design: Corner/entities/create_customer_email_without_at_returns_invalid_request
    """
    res = api_client.create_customer(
        {"email": "noatsign", "full_name": "Bad Email"}, SCHEDULER
    )
    validate_error(res, "ERR_INVALID_REQUEST", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / appointment_invalid_enum_tier_returns_invalid_request
# ──────────────────────────────────────────────────────────────────────

def test_appointment_invalid_enum_tier_returns_invalid_request():
    """PRD §2.9: "the request body checked for well-formedness — required fields present, enum values legal, numbers in range, and an email containing an at-sign (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/appointment_invalid_enum_tier_returns_invalid_request
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="enum@x.com", full_name="Enum Test")
    unit = create_mobile_unit(unit_code="ME1", travel_buffer_minutes=30)
    payload = create_appointment_payload(
        cust["id"], tier="PLATINUM", vehicle_size="SEDAN", location_mode="MOBILE",
        scheduled_start_utc="2026-06-15T10:00:00Z", mobile_unit_id=unit["id"],
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / appointment_system_fields_generated_not_accepted_from_input
# ──────────────────────────────────────────────────────────────────────

def test_appointment_system_fields_generated_by_server():
    """PRD §3.2: "A new appointment begins with `work_status` of `BOOKED` and `payment_status` of `UNPAID`, with `amount_charged_cents` and `amount_refunded_cents` at zero."
    PRD §2.4: "The `version` field is an integer that begins at its initial value on creation"

    Design: Corner/entities/appointment_system_fields_generated_not_accepted_from_input
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="sys@x.com", full_name="Sys F")
    unit = create_mobile_unit(unit_code="ME2", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T10:00:00Z",
    )
    assert appt["work_status"] == "BOOKED"
    assert appt["payment_status"] == "UNPAID"
    assert appt["version"] == 1


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / appointment_default_use_membership_credit_false
#   (default-value silence pattern: PRD does not name the server-side default of
#   the optional input field, so we assert only the PRD-derivable outcome that,
#   with no active membership, credit_applied_cents is zero.)
# ──────────────────────────────────────────────────────────────────────

def test_no_credit_applied_without_membership():
    """PRD §3.2: "When no credit applies, `credit_applied_cents` is zero."

    Design: Corner/entities/appointment_default_use_membership_credit_false
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="def@x.com", full_name="Def G")
    unit = create_mobile_unit(unit_code="ME3", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T10:00:00Z",
    )
    assert appt["credit_applied_cents"] == 0


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / appointment_fk_customer_not_found_returns_fk_not_found
# ──────────────────────────────────────────────────────────────────────

def test_appointment_fk_customer_not_found():
    """PRD §2.5: "When a create endpoint accepts a foreign key — a `customer_id`, a `service_bay_id`, a `mobile_unit_id`, an `appointment_id`, or an `original_appointment_id` — and that key does not point at an existing resource, the request is rejected with `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/appointment_fk_customer_not_found_returns_fk_not_found
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    unit = create_mobile_unit(unit_code="ME4", travel_buffer_minutes=30)
    payload = create_appointment_payload(
        NON_EXISTENT_UUID, tier="FULL", vehicle_size="SEDAN", location_mode="MOBILE",
        scheduled_start_utc="2026-06-15T10:00:00Z", mobile_unit_id=unit["id"],
    )
    res = api_client.create_appointment(payload, SCHEDULER)
    validate_error(res, "ERR_FK_NOT_FOUND", 404)


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / list_customers_pagination_envelope
# ──────────────────────────────────────────────────────────────────────

def test_list_customers_pagination_envelope():
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_customers_pagination_envelope
    """
    create_customer(email="p1@x.com", full_name="P One")
    create_customer(email="p2@x.com", full_name="P Two")
    data, meta = validate_paginated(
        api_client.list_customers(SCHEDULER, params={"limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / pagination_limit_out_of_range_returns_validation
# ──────────────────────────────────────────────────────────────────────

def test_pagination_limit_zero_returns_validation():
    """PRD §2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/pagination_limit_out_of_range_returns_validation
    """
    res = api_client.list_customers(SCHEDULER, params={"limit": 0})
    validate_error(res, "ERR_VALIDATION", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / entities / immutable_packagecatalog_has_no_version_field
# ──────────────────────────────────────────────────────────────────────

def test_package_catalog_has_no_version_field():
    """PRD §2.4: "The three flat catalog resources — `PackageCatalog`, `VehicleSizeRate`, and `AddOn` — are configuration records that are not versioned. Each of these carries only an `id` (a server-minted UUID) and a `created_at` timestamp; they have no `updated_at` field and no `version` field."

    Design: Corner/entities/immutable_packagecatalog_has_no_version_field
    """
    res = api_client.create_package(create_package_payload(tier="WASH"), SCHEDULER)
    pkg = validate_success(res, 201)
    assert pkg["base_price_cents"] == 4000
    assert "version" not in pkg
    assert "updated_at" not in pkg


# ──────────────────────────────────────────────────────────────────────
# Corner / endpoints / get_appointment_returns_all_computed_fields
# ──────────────────────────────────────────────────────────────────────

def test_get_appointment_returns_computed_fields():
    """PRD §3.2: "The `provisional_total_cents` reported at booking is the net package price plus the add-on total"
    PRD §3.2: "for a `MOBILE` job the crew leaves before the cure, so `occupancy_end_utc` equals `scheduled_start_utc` plus busy minutes only."

    Design: Corner/endpoints/get_appointment_returns_all_computed_fields
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="gc1@x.com", full_name="Gc One")
    unit = create_mobile_unit(unit_code="GC1", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    fetched = validate_success(
        api_client.get_appointment(appt["id"], make_customer_headers(cust["id"])), 200
    )
    # Non-member FULL/SEDAN = 12000; busy = prep20+service120 = 140 min -> 11:20.
    assert fetched["provisional_total_cents"] == 12000
    assert fetched["outstanding_balance_cents"] == 12000
    assert fetched["occupancy_end_utc"] == "2026-06-15T11:20:00.000Z"


# ──────────────────────────────────────────────────────────────────────
# Corner / endpoints / list_appointments_filtered_by_mobile_unit_fk
# ──────────────────────────────────────────────────────────────────────

def test_list_appointments_filtered_by_mobile_unit():
    """PRD §4: "The appointment list endpoint accepts the optional filters `customer_id`, `service_bay_id`, `mobile_unit_id`, and `spawned_from_rework_claim_id` in addition to `limit` and `offset`."

    Design: Corner/endpoints/list_appointments_filtered_by_mobile_unit_fk
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="lf1@x.com", full_name="Lf One")
    unit = create_mobile_unit(unit_code="LF1", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    data, meta = validate_paginated(
        api_client.list_appointments(SCHEDULER, params={"mobile_unit_id": unit["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == appt["id"]


# ──────────────────────────────────────────────────────────────────────
# Corner / rbac / customer_cannot_create_package_catalog
# ──────────────────────────────────────────────────────────────────────

def test_customer_cannot_create_package():
    """PRD §2.1: "When an authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4 (endpoint table): POST /detailing/packages is authorized for
    Scheduler, ShopManager only.

    Design: Corner/rbac/customer_cannot_create_package_catalog
    """
    cust = create_customer(email="rb1@x.com", full_name="Rb One")
    res = api_client.create_package(
        create_package_payload(tier="WASH"), make_customer_headers(cust["id"])
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)


# ──────────────────────────────────────────────────────────────────────
# Corner / rbac / customer_cannot_act_on_another_customers_appointment
# ──────────────────────────────────────────────────────────────────────

def test_customer_cannot_cancel_anothers_appointment():
    """PRD §2.1: "When a `Customer` acts on an appointment or membership whose `customer_id` does not equal `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_act_on_another_customers_appointment
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust_a = create_customer(email="owna@x.com", full_name="Own A")
    cust_b = create_customer(email="ownb@x.com", full_name="Own B")
    unit = create_mobile_unit(unit_code="OWN1", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust_a["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    res = api_client.cancel_appointment(appt["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", 403)


# ──────────────────────────────────────────────────────────────────────
# Corner / rbac / missing_auth_headers_returns_unauthenticated
# ──────────────────────────────────────────────────────────────────────

def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api_client.list_customers({"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED", 401)


# ──────────────────────────────────────────────────────────────────────
# Corner / rbac / detailer_cannot_refund_only_shopmanager
# ──────────────────────────────────────────────────────────────────────

def test_detailer_cannot_refund():
    """PRD §3.7: "Refunding is exclusive to a `ShopManager` and may be applied to a `PAID` appointment."
    PRD §2.1: "When an authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/detailer_cannot_refund_only_shopmanager
    """
    from test_helpers.fixtures import complete_non_ceramic_to_released
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="df1@x.com", full_name="Df One")
    unit = create_mobile_unit(unit_code="DF1", travel_buffer_minutes=30)
    appt = complete_non_ceramic_to_released(cust["id"], unit["id"], amount_cents=12000)
    res = api_client.refund(appt["id"], DETAILER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)
