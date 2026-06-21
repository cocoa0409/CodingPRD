"""Uniqueness, temporal, and concurrency validations; RBAC authentication,
authorization, and ownership; and the discontinue action endpoint.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_product_payload, create_customer_payload, create_estimate_payload,
    issue_payload, measure_payload,
    create_draft_job, create_measured_estimate, create_issued_estimate,
    register_customer, register_sales_rep, create_product,
    make_sales_rep_headers, make_customer_headers, set_clock,
    TEST_USERS, ANONYMOUS_HEADERS,
)


# ─── Uniqueness ───────────────────────────────────────────────────────

def test_duplicate_product_sku_rejected(api, admin_headers):
    """PRD §3.1: "A product's `sku` must be unique among products that are not
    discontinued; the codes are case-sensitive, and a create whose `sku` collides
    with an existing active product is rejected with `ERR_DUPLICATE_KEY`
    (HTTP 409)."

    Design: Corner/validations/duplicate_product_sku_rejected
    """
    api.create_product(create_product_payload(sku="DUP-1", category="LVP"), admin_headers)
    res = api.create_product(
        create_product_payload(sku="DUP-1", category="TILE",
                               requires_underlayment=False,
                               underlayment_cost_per_sqft_cents=0),
        admin_headers)
    validate_error(res, "ERR_DUPLICATE_KEY", expected_status=409)


def test_duplicate_customer_email_rejected(api):
    """PRD §3.2: "the email is unique among customers, compared case-insensitively,
    and a duplicate is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_customer_email_rejected
    """
    api.create_customer({"full_name": "First", "address": "1 St", "email": "dup-key@x.com"},
                        ANONYMOUS_HEADERS)
    res = api.create_customer({"full_name": "Second", "address": "2 St", "email": "dup-key@x.com"},
                              ANONYMOUS_HEADERS)
    validate_error(res, "ERR_DUPLICATE_KEY", expected_status=409)


def test_job_create_on_discontinued_product_rejected(api, admin_headers):
    """PRD §3.2: "The referenced product must be `ACTIVE` at the moment the job is
    created; if it has been discontinued, the create is rejected with
    `ERR_PRODUCT_DISCONTINUED` (HTTP 409)."

    Design: Corner/validations/job_create_on_discontinued_product_rejected
    """
    customer = register_customer()
    sales_rep = register_sales_rep()
    product = create_product(sku="DISC-2", category="TILE",
                             requires_underlayment=False, underlayment_cost_per_sqft_cents=0,
                             material_cost_per_sqft_cents=500, labor_rate_per_sqft_cents=400,
                             warranty_years=25)
    get_success_data(api.discontinue_product(product["id"], admin_headers))
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    from test_helpers import create_job_payload
    res = api.create_job(
        create_job_payload(customer["id"], sales_rep["id"], product["id"], declared_sqft=200),
        rep_headers)
    validate_error(res, "ERR_PRODUCT_DISCONTINUED", expected_status=409)


# ─── Temporal validations ─────────────────────────────────────────────

def test_issue_estimate_valid_until_in_past_rejected(api):
    """PRD §3.5: "its `valid_until` must be strictly after the current clock — a
    `valid_until` at or before now is rejected with `ERR_VALID_UNTIL_IN_PAST`
    (HTTP 422)."

    Design: Corner/validations/estimate_issue_valid_until_in_past_rejected
    """
    # clock 2026-06-01; estimate valid_until 2026-05-01 (past).
    customer, sales_rep, product, job, est = create_measured_estimate(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        valid_until="2026-05-01T00:00:00.000Z",
        product_overrides={"sku": "PAST-1", "category": "LVP", "lead_time_days": 0})
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    res = api.issue_estimate(est["id"], issue_payload(job["version"]), rep_headers)
    validate_error(res, "ERR_VALID_UNTIL_IN_PAST", expected_status=422)


def test_accept_estimate_after_expiry_rejected(api):
    """PRD §3.6: "the current clock must be strictly before its `valid_until`; an
    acceptance at or after `valid_until` is rejected with `ERR_ESTIMATE_EXPIRED`
    (HTTP 409)".

    Design: Corner/validations/estimate_accept_after_expiry_rejected
    """
    # ISSUED estimate valid_until 2026-06-10; clock advanced to 2026-06-11.
    customer, sales_rep, product, job, est = create_issued_estimate(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        valid_until="2026-06-10T00:00:00.000Z",
        product_overrides={"sku": "EXPACC-1", "category": "LVP", "lead_time_days": 0})
    set_clock("2026-06-11T00:00:00.000Z")
    cust_headers = make_customer_headers(customer["id"])
    res = api.accept_estimate(est["id"], cust_headers)
    validate_error(res, "ERR_ESTIMATE_EXPIRED", expected_status=409)


# ─── Optimistic concurrency ───────────────────────────────────────────

def test_issue_with_stale_job_version_rejected(api):
    """PRD §2.7: "If that value does not equal the job's current `version` —
    because another writer has advanced the job since the client read it, for
    instance by issuing a competing estimate — the issue is rejected with
    `ERR_STALE_JOB_VERSION` (HTTP 412), so the client cannot supersede an estimate
    it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_job_version_explicit_412
    """
    # Measure (capture stale version); issue est1 (bumps job.version);
    # create est2; issue est2 with the stale version -> 412.
    customer = register_customer()
    sales_rep = register_sales_rep()
    set_clock("2026-06-01T00:00:00.000Z")
    product = create_product(sku="OCC-1", category="LVP", lead_time_days=0)
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    from test_helpers import create_job_payload
    job = get_success_data(api.create_job(
        create_job_payload(customer["id"], sales_rep["id"], product["id"], declared_sqft=200),
        rep_headers))
    job = get_success_data(api.measure_job(
        job["id"], measure_payload(measured_sqft=200, tear_out_sqft=0, room_count=1),
        TEST_USERS["estimator_headers"]))
    stale_version = job["version"]
    est1 = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED"), rep_headers))
    get_success_data(api.issue_estimate(est1["id"], issue_payload(stale_version), rep_headers))
    est2 = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED"), rep_headers))
    res = api.issue_estimate(est2["id"], issue_payload(stale_version), rep_headers)
    validate_error(res, "ERR_STALE_JOB_VERSION", expected_status=412)
    est2_after = get_success_data(api.get_estimate(est2["id"], rep_headers))
    assert est2_after["status"] == "DRAFT"


# ─── RBAC ─────────────────────────────────────────────────────────────

def test_missing_auth_headers_unauthenticated(api, admin_headers):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    product = create_product(sku="AUTH-1", category="LVP", lead_time_days=0)
    res = api.get_product(product["id"], ANONYMOUS_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_estimator_cannot_create_product_forbidden(api, estimator_headers):
    """PRD §2.1: "When a recognized user invokes an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/estimator_cannot_create_product_forbidden
    """
    res = api.create_product(create_product_payload(sku="FORB-1", category="LVP"),
                             estimator_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_scheduler_cannot_create_job_forbidden(api, scheduler_headers):
    """PRD §2.1: "When a recognized user invokes an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/scheduler_cannot_create_job_forbidden
    """
    customer = register_customer()
    sales_rep = register_sales_rep()
    product = create_product(sku="SCH-1", category="LVP", lead_time_days=0)
    from test_helpers import create_job_payload
    res = api.create_job(
        create_job_payload(customer["id"], sales_rep["id"], product["id"], declared_sqft=200),
        scheduler_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_customer_cannot_accept_other_customers_estimate(api):
    """PRD §2.1: "Ownership is enforced specifically when a `Customer` accepts an
    estimate or files a warranty claim: the acting `X-User-ID` must equal the
    `customer_id` of the job in question, and a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_accept_other_customers_estimate
    """
    # Customer A owns the job's ISSUED estimate; Customer B attempts to accept.
    customer_a, sales_rep, product, job, est = create_issued_estimate(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "OWN-1", "category": "LVP", "lead_time_days": 0})
    customer_b = register_customer()
    intruder_headers = make_customer_headers(customer_b["id"])
    res = api.accept_estimate(est["id"], intruder_headers)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


# ─── Discontinue action endpoint ──────────────────────────────────────

def test_discontinue_product_succeeds_when_no_live_jobs(api, admin_headers):
    """PRD §3.1: "An `Admin` may later retire a product, transitioning its
    `status` from `ACTIVE` to `DISCONTINUED`, which bumps the product's `version`."

    Design: Corner/endpoints/discontinue_product_action_succeeds_when_no_live_jobs
    """
    product = create_product(sku="DACT-1", category="TILE",
                             requires_underlayment=False, underlayment_cost_per_sqft_cents=0,
                             material_cost_per_sqft_cents=500, labor_rate_per_sqft_cents=400,
                             warranty_years=25)
    res = api.discontinue_product(product["id"], admin_headers)
    updated = validate_success(res, 200)
    assert updated["status"] == "DISCONTINUED"
    assert updated["version"] == 2
