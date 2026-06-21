"""Catalog CRUD, retrieval, listing, required/optional fields, and FK integrity.

Each test translates exactly one corner-design instance (queue B).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_product, assert_job,
    create_product_payload, create_job_payload, create_estimate_payload,
    register_customer, register_sales_rep, create_product, create_draft_job,
    make_sales_rep_headers,
    TEST_USERS, ANONYMOUS_HEADERS, NON_EXISTENT_UUID,
    get_success_data, api_client,
)


def test_create_product_returns_201_with_active_status(api, admin_headers):
    """PRD §3.1: "A new product comes into the world with `status` of `ACTIVE`."
    PRD §2.4: "every one has a `version`, an integer that begins at 1 when the
    resource is created and increments by exactly one on each mutation."

    Design: Corner/entities/create_product_returns_201_with_all_fields
    """
    payload = create_product_payload(
        sku="HW-CR", name="Create Oak", category="HARDWOOD",
        material_cost_per_sqft_cents=600, labor_rate_per_sqft_cents=350,
        requires_underlayment=False, underlayment_cost_per_sqft_cents=0,
        lead_time_days=5, warranty_years=20,
    )
    res = api.create_product(payload, admin_headers)
    product = validate_success(res, 201)
    assert_product(product)
    assert product["status"] == "ACTIVE"
    assert product["version"] == 1
    assert product["category"] == "HARDWOOD"


def test_get_job_returns_stored_data(api):
    """PRD §3.2: "A new job starts in `DRAFT` status."
    PRD §3.2: "A `SalesRep` opens a `Job` by supplying a `customer_id`, a
    `sales_rep_id`, a `product_id`, and a `declared_sqft` — the rough square
    footage the customer reports before anyone has measured."

    Design: Corner/entities/get_job_returns_stored_data
    """
    customer, sales_rep, product, job = create_draft_job(declared_sqft=250)
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    res = api.get_job(job["id"], rep_headers)
    fetched = validate_success(res, 200)
    assert fetched["status"] == "DRAFT"
    assert fetched["declared_sqft"] == 250


def test_list_products_paginated_envelope(api, admin_headers):
    """PRD §2.3: "The `limit` parameter caps how many items a single page returns;
    it defaults to 10, may be no smaller than 1, and may be no larger than 100."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/entities/list_products_paginated_envelope
    """
    api.create_product(create_product_payload(sku="P1", category="TILE"), admin_headers)
    api.create_product(create_product_payload(sku="P2", category="CARPET",
                                              requires_underlayment=False,
                                              underlayment_cost_per_sqft_cents=0),
                       admin_headers)
    data, meta = validate_paginated(api.list_products(admin_headers, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_nonexistent_job_returns_not_found(api, admin_headers):
    """PRD §2.5: "The first identifier that does not resolve to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404),
    before any business rule is evaluated."

    Design: Corner/entities/get_nonexistent_job_returns_not_found
    """
    res = api.get_job(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_job_missing_declared_sqft_returns_invalid_request(api):
    """PRD §3.2: "The declared figure must be greater than 0."
    PRD §3.1: "Any violation of these numeric, enum, or consistency bounds —
    here and on every create or measure endpoint — is rejected with
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_job_missing_declared_sqft_returns_invalid_request
    """
    customer = register_customer()
    sales_rep = register_sales_rep()
    product = create_product()
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    payload = {
        "customer_id": customer["id"],
        "sales_rep_id": sales_rep["id"],
        "product_id": product["id"],
    }
    res = api.create_job(payload, rep_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_product_default_lead_time_zero(api, admin_headers):
    """PRD §3.1: "`lead_time_days`, the vendor lead time in days for a special
    order (0 meaning the product is stocked), also defaults to 0."

    Design: Corner/entities/create_product_default_lead_time_zero
    """
    payload = {
        "sku": "DEF-1", "name": "Default Tile", "category": "TILE",
        "material_cost_per_sqft_cents": 500, "labor_rate_per_sqft_cents": 400,
        "requires_underlayment": False, "warranty_years": 25,
    }
    res = api.create_product(payload, admin_headers)
    product = validate_success(res, 201)
    assert product["lead_time_days"] == 0


def test_job_waste_factor_null_until_measured(api):
    """PRD §3.3: "It is computed and stored at measure time (and recomputed on
    every re-measure) and is null until the job has been measured."

    Design: Corner/entities/job_computed_waste_factor_null_until_measured
    """
    customer, sales_rep, product, job = create_draft_job(declared_sqft=200)
    assert job["waste_factor_pct"] is None


def test_invalid_category_enum_rejected(api, admin_headers):
    """PRD §3.1: "a `category` that is one of `HARDWOOD`, `LVP`, `TILE`, or
    `CARPET`".
    PRD §3.1: "Any violation of these numeric, enum, or consistency bounds —
    here and on every create or measure endpoint — is rejected with
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/invalid_category_enum_rejected
    """
    payload = create_product_payload(sku="ENUM-1", name="Bad", category="BAMBOO",
                                     requires_underlayment=False,
                                     underlayment_cost_per_sqft_cents=0)
    res = api.create_product(payload, admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_customer_has_no_version_field(api):
    """PRD §2.4: "The `Customer` and the `SalesRep` are registration records that,
    once created, are not mutated through this API: each carries only an `id` (a
    server-minted UUID, with no type prefix) and a `created_at` timestamp. Neither
    carries an `updated_at` field nor a `version` field; both are absent for these
    two resources."

    Design: Corner/entities/customer_immutable_no_version_field
    """
    res = api.create_customer(
        {"full_name": "Imm Guy", "address": "4 St", "email": "imm-novers@x.com"},
        ANONYMOUS_HEADERS,
    )
    customer = validate_success(res, 201)
    assert "version" not in customer
    assert "updated_at" not in customer


def test_product_status_server_set_on_create(api, admin_headers):
    """PRD §3.1: "A new product comes into the world with `status` of `ACTIVE`."

    Design: Corner/entities/system_field_status_server_set_on_product
    """
    payload = create_product_payload(sku="SYS-1", name="Sys LVP", category="LVP")
    res = api.create_product(payload, admin_headers)
    product = validate_success(res, 201)
    assert product["status"] == "ACTIVE"


def test_job_with_nonexistent_product_returns_not_found(api):
    """PRD §2.5: "the path identifier is checked first, and only then are foreign
    keys referenced in the request body resolved. The first identifier that does
    not resolve to an existing resource causes the request to be rejected with
    `ERR_NOT_FOUND` (HTTP 404), before any business rule is evaluated."

    Design: Corner/entities/job_wrong_parent_product_returns_not_found
    """
    customer = register_customer()
    sales_rep = register_sales_rep()
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    payload = create_job_payload(customer["id"], sales_rep["id"], NON_EXISTENT_UUID,
                                 declared_sqft=200)
    res = api.create_job(payload, rep_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_job_estimates_reverse_list(api):
    """PRD §4 (routing): the job's estimates list endpoint exists, and PRD §3.2:
    "Every estimate is created in `DRAFT` status and records the `job_id` it
    prices and a `valid_until` instant supplied by the caller."

    Design: Corner/entities/flat_fk_integrity_estimate_job_reverse_list
    """
    customer, sales_rep, product, job = create_draft_job(declared_sqft=200)
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    est = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="PROVISIONAL"), rep_headers))
    data, _meta = validate_paginated(api.list_job_estimates(job["id"], rep_headers))
    assert len(data) == 1
    assert data[0]["id"] == est["id"]
