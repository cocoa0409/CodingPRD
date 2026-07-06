"""Onboarding and creation-path breadth tests (customers, chimneys, service jobs)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    assert_customer, assert_chimney, assert_service_job,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_customer_returns_201_with_minted_id():
    """PRD §3.1: "A `Dispatcher` records a homeowner as a `Customer`, capturing
    their `name`, `service_address` (the street address where the chimney lives),
    and `phone`; an `email` is optional and, if not supplied, is stored as null."
    PRD §4: "Creation endpoints that mint a new stand-alone resource return `201
    Created`; this includes creating customers, chimneys, technicians, route days,
    service jobs, appointments, sweep logs, safety checks, repair orders,
    warranties, and reminder schedules."

    Design: Corner/entities/creation_success_customer
    """
    resp = api_client.create_customer(
        F.create_customer_payload(name="Cora Coal", service_address="20 Hearth Ln",
                                  phone="555-0200", email="cora@x.com"),
        DISPATCHER,
    )
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["name"] == "Cora Coal"
    assert data["service_address"] == "20 Hearth Ln"


def test_create_customer_missing_service_address_rejected():
    """PRD §3.1: "A `Dispatcher` records a homeowner as a `Customer`, capturing
    their `name`, `service_address` (the street address where the chimney lives),
    and `phone`; an `email` is optional and, if not supplied, is stored as null."
    PRD §2.11: "**Shape and enum domains** — required fields present and
    enum/numeric domains valid, else `ERR_VALIDATION`,
    `ERR_INVALID_INSPECTION_LEVEL`, or `ERR_INVALID_CREOSOTE_CLASS` (400)."

    Design: Corner/entities/error_missing_required_field_on_create_customer
    """
    resp = api_client.create_customer({"name": "No Address", "phone": "555-0201"}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_missing_auth_headers_rejected():
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming their operational
    capacity. If either header is missing or empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS`."

    Design: Corner/validations/error_missing_auth_headers_on_create_customer
    """
    resp = api_client.create_customer(
        F.create_customer_payload(name="No Auth", service_address="34 Hearth Ln", phone="555-0215"),
        {},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS)


def test_get_service_job_not_found():
    """PRD §2.9: "The same left-to-right rule governs foreign keys supplied in a
    request body: each referenced resource must exist, and the corresponding
    not-found error is raised for the first that does not. The catalogue of
    not-found errors is `ERR_CUSTOMER_NOT_FOUND`, `ERR_CHIMNEY_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_ROUTE_DAY_NOT_FOUND`,
    `ERR_SERVICE_JOB_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_WARRANTY_NOT_FOUND`, and
    `ERR_REMINDER_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/entities/error_service_job_not_found_on_get
    """
    resp = api_client.get_service_job("00000000-0000-0000-0000-000000000000", DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_SERVICE_JOB_NOT_FOUND)


def test_chimney_defaults_applied():
    """PRD §3.1: "Three descriptors are optional and take defaults when omitted:
    `cap_installed` records whether a rain cap is currently fitted and defaults to
    false; `liner_type` is one of `NONE`, `CLAY`, `STAINLESS`, or `ALUMINUM` and
    defaults to `NONE`; and `damper_type` is one of `THROAT`, `TOP_MOUNT`, or
    `NONE` and defaults to `THROAT`."

    Design: Corner/entities/default_liner_type_applied_none
    """
    customer = fx.make_customer(name="Deb Damper", service_address="21 Hearth Ln", phone="555-0202")
    resp = api_client.create_chimney(
        F.create_chimney_payload(customer_id=customer["id"], chimney_type="MASONRY",
                                 appliance_type="OPEN_FIREPLACE", flue_count=1),
        DISPATCHER,
    )
    data = validate_success(resp, 201)
    assert_chimney(data)
    assert data["liner_type"] == "NONE"
    assert data["damper_type"] == "THROAT"
    assert data["cap_installed"] is False


def test_service_job_provisional_and_committed_at_creation():
    """PRD §3.2: "The base charge is set by inspection level: 15000 cents for level
    1, 24000 cents for level 2, and 40000 cents for level 3."
    PRD §3.2: "A creosote surcharge is added by class: nothing for class 1, 6000
    cents for class 2, and 18000 cents for class 3 — and the provisional quote uses
    `expected_creosote_class` for this term while treating the glaze condition as
    absent (a zero glaze surcharge)."
    PRD §3.2: "Immediately after, `committed_cost_cents` is initialized to equal
    `sweep_provisional_cost_cents`, since no repairs exist yet."

    Design: Corner/entities/computed_sweep_provisional_at_job_creation
    """
    customer = fx.make_customer(name="Ed Ember", service_address="22 Hearth Ln", phone="555-0203")
    chimney = fx.make_chimney(customer["id"], appliance_type="WOOD_STOVE")
    resp = api_client.create_service_job(
        F.create_service_job_payload(customer_id=customer["id"], chimney_id=chimney["id"],
                                     inspection_level=2, expected_creosote_class=2, trip_zone="A"),
        DISPATCHER,
    )
    data = validate_success(resp, 201)
    assert_service_job(data)
    # 24000 (level 2) + 6000 (class 2) + 0 (no glaze) + 0 (zone A) = 30000
    assert data["sweep_provisional_cost_cents"] == 30000
    assert data["committed_cost_cents"] == 30000


def test_invalid_inspection_level_rejected():
    """PRD §3.2: "the CSIA `inspection_level`, which must be 1, 2, or 3 — any other
    value is `ERR_INVALID_INSPECTION_LEVEL`."

    Design: Corner/entities/error_invalid_inspection_level_enum
    """
    customer = fx.make_customer(name="Fi Flint", service_address="23 Hearth Ln", phone="555-0204")
    chimney = fx.make_chimney(customer["id"])
    resp = api_client.create_service_job(
        F.create_service_job_payload(customer_id=customer["id"], chimney_id=chimney["id"], inspection_level=4),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INSPECTION_LEVEL)


def test_service_jobs_pagination():
    """PRD §2.3: "The `limit` parameter caps how many items are returned; when
    omitted it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/pagination_service_jobs_list
    """
    customer = fx.make_customer(name="Hy Hob", service_address="25 Hearth Ln", phone="555-0206")
    chimney = fx.make_chimney(customer["id"])
    fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    fx.make_service_job(customer["id"], chimney["id"], inspection_level=2)
    resp = api_client.list_service_jobs(DISPATCHER, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_service_job_create_chimney_not_found():
    """PRD §2.9: "The same left-to-right rule governs foreign keys supplied in a
    request body: each referenced resource must exist, and the corresponding
    not-found error is raised for the first that does not."

    Design: Corner/errors/error_chimney_not_found_on_service_job_create
    """
    customer = fx.make_customer(name="Jo Jamb", service_address="46 Hearth Ln", phone="555-0227")
    resp = api_client.create_service_job(
        F.create_service_job_payload(customer_id=customer["id"],
                                     chimney_id="00000000-0000-0000-0000-000000000000", inspection_level=1),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CHIMNEY_NOT_FOUND)
