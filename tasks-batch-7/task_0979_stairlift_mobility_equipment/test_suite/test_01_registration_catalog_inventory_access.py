"""Customer registration, catalog, inventory, listing envelope, and access control."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, MODEL_STRAIGHT,
    assert_customer, assert_product_model, assert_equipment_unit,
    create_customer_payload, create_product_model_payload,
    create_equipment_unit_payload, create_home_assessment_payload,
    create_measure_payload,
    set_clock, create_catalog_model, create_customer, schedule_assessment,
    measure_assessment, create_unit, fresh_serial,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
FUNDING = TEST_USERS["funding_officer_headers"]
COORD = TEST_USERS["install_coordinator_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]


# ---------------------------------------------------------------------------
# Customer creation
# ---------------------------------------------------------------------------

def test_customer_creation_with_defaults(api):
    """PRD §3.1: "A newly registered customer starts in `PROSPECT` status with
    `lifetime_outstanding_cents` at zero; the customer list supports an
    optional `status` filter."
    PRD §2.5: "Resources with standard lifecycle metadata additionally carry
    `created_at` and `updated_at` — ISO 8601 UTC timestamps with three
    fractional digits — and a `version` integer that starts low and increments
    by one on every mutation of that resource."

    Design: Corner/entities/customer_creation_with_defaults
    """
    set_clock()
    res = api.create_customer(
        create_customer_payload(full_name="Default Dan", date_of_birth="1960-01-01",
                                home_region_code="NORTH"),
        SALES)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["status"] == "PROSPECT"
    assert customer["lifetime_outstanding_cents"] == 0
    assert isinstance(customer["version"], int)


def test_customer_creation_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "Independently of this ordering, any request body that is
    missing a required input field or supplies a value of the wrong type is
    rejected with `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "Registration by a `PlatformAdmin` or `SalesRep` captures the
    customer's `full_name`, `date_of_birth` (an ISO 8601 date used later for
    age-based funding eligibility), and `home_region_code` (a region code such
    as `NORTH` or `SOUTH` that funding and buyback rules consult)."

    Design: Corner/entities/customer_creation_missing_required_field_returns_invalid_request
    """
    set_clock()
    payload = {"date_of_birth": "1960-01-01", "home_region_code": "NORTH"}
    res = api.create_customer(payload, SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_customer_get_not_found_returns_404(api):
    """PRD §2.8: "3. Reference resolution — path-templated identifiers resolve
    left-to-right, and each foreign key in the payload resolves — failure
    yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/customer_get_not_found_returns_404
    """
    set_clock()
    res = api.get_customer(NON_EXISTENT_UUID, SALES)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Catalog reference data
# ---------------------------------------------------------------------------

def test_product_model_immutable_no_version_field(api):
    """PRD §2.5: "Two resource kinds are deliberately leaner: a `ProductModel`
    catalog entry and an `AuditEvent` row carry only `id` and `created_at`;
    both `updated_at` and `version` are absent from them."

    Design: Corner/entities/product_model_immutable_no_version_field
    """
    set_clock()
    create_catalog_model(model_code="SL-X", base_purchase_price_cents=300000,
                         monthly_rental_rate_cents=7000)
    res = api.get_product_model("SL-X", ADMIN)
    model = validate_success(res, 200)
    assert_product_model(model)
    assert "version" not in model, "ProductModel must not carry a version field"
    assert "updated_at" not in model, "ProductModel must not carry updated_at"


# ---------------------------------------------------------------------------
# Equipment inventory
# ---------------------------------------------------------------------------

def test_equipment_unit_default_grade_and_status(api):
    """PRD §3.2: "Receiving by an `InventoryManager` or `PlatformAdmin` records
    the unit's `model_code` and globally unique `serial_number`; the unit
    arrives `IN_STOCK` in `condition_grade` `NEW` with `acquired_at` stamped
    from the logical clock and `lifetime_rental_months` at zero."

    Design: Corner/entities/equipment_unit_default_grade_and_status
    """
    set_clock()
    create_catalog_model(model_code="SL-D", base_purchase_price_cents=300000,
                         monthly_rental_rate_cents=7000)
    unit = create_unit("SL-D", serial="SN-D-001")
    assert_equipment_unit(unit)
    assert unit["condition_grade"] == "NEW"
    assert unit["status"] == "IN_STOCK"
    assert unit["lifetime_rental_months"] == 0


# ---------------------------------------------------------------------------
# List envelope and filters
# ---------------------------------------------------------------------------

def test_list_customers_pagination_envelope(api):
    """PRD §2.3: "Every list response sorts by `created_at` ascending unless
    otherwise noted, and its `meta` object carries the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/list_customers_pagination_envelope
    """
    set_clock()
    for name in ("P1", "P2", "P3"):
        create_customer(full_name=name)
    res = api.list_customers(SALES, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in meta
    assert res.json()["response_type"] == "array"
    assert len(data) == 2
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"meta missing pagination field {field}"
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_list_equipment_units_filtered_by_model_code(api):
    """PRD §3.2: "The inventory list supports optional `model_code`, `status`,
    and `condition_grade` filters."

    Design: Corner/endpoints/list_equipment_units_filtered_by_model_code
    """
    set_clock()
    create_catalog_model(model_code="SL-FA", base_purchase_price_cents=300000,
                         monthly_rental_rate_cents=7000)
    create_catalog_model(model_code="SL-FB", kind="SCOOTER", supports_outdoor=True,
                         min_stair_width_mm=0, base_purchase_price_cents=150000,
                         monthly_rental_rate_cents=5000, install_labor_hours=0)
    create_unit("SL-FA", serial="SN-FA-1")
    create_unit("SL-FA", serial="SN-FA-2")
    create_unit("SL-FB", serial="SN-FB-1")
    res = api.list_equipment_units(INVENTORY, params={"model_code": "SL-FA"})
    data, meta = validate_paginated(res)
    assert len(data) == 2
    assert all(u["model_code"] == "SL-FA" for u in data)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing or malformed, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    set_clock()
    res = api.create_customer(
        create_customer_payload(full_name="No Auth"), headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_wrong_role_returns_unauthorized(api):
    """PRD §2.1: "If the named role is not permitted to invoke the endpoint,
    the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /stairlift-ops/equipment-units/{id}/restock is authorized for
    InventoryManager only.

    Design: Corner/validations/wrong_role_returns_unauthorized
    """
    set_clock()
    create_catalog_model(model_code="SL-UR", base_purchase_price_cents=300000,
                         monthly_rental_rate_cents=7000)
    unit = create_unit("SL-UR", serial="SN-UR-001")
    res = api.restock_equipment_unit(unit["id"], SALES)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_assessor_cannot_approve_own_assessment(api):
    """PRD §3.1: "Approval is segregated from measurement. An
    `AssessmentReviewer` approves a `MEASURED` assessment against a target
    catalog model pinned as `model_code` in the request."
    PRD §2.1: "If the named role is not permitted to invoke the endpoint, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /stairlift-ops/home-assessments/{id}/approve is authorized for
    AssessmentReviewer only.

    Design: Corner/roles/assessor_cannot_approve_own_assessment
    """
    set_clock()
    create_catalog_model(model_code="SL-SD")
    customer = create_customer(full_name="SD Sarah")
    assessment = schedule_assessment(customer["id"])
    measure_assessment(assessment["id"])
    res = api.approve_home_assessment(assessment["id"], {"model_code": "SL-SD"},
                                      ASSESSOR)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_customer_cannot_issue_quote(api):
    """PRD §3.3: "A `SalesRep` may issue only a `DRAFT` quote — anything else
    is `ERR_INVALID_STATE`."
    PRD §2.1: "If the named role is not permitted to invoke the endpoint, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /stairlift-ops/quotes/{id}/issue is authorized for SalesRep
    only.

    Design: Corner/roles/customer_cannot_issue_quote
    """
    from test_helpers import (setup_approved_assessment, create_draft_quote,
                              make_customer_headers)
    set_clock()
    create_catalog_model(model_code="SL-CI")
    base = setup_approved_assessment("SL-CI")
    quote = create_draft_quote(base["customer"]["id"], base["assessment"]["id"],
                               "SL-CI")
    res = api.issue_quote(quote["id"], make_customer_headers(base["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
