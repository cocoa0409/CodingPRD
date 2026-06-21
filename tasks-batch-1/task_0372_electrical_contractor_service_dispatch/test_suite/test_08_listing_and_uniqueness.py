"""Filtered list reads (FK reverse-reachability) and uniqueness constraints.

Queue B (Corner): endpoints (filtered reads), validations (uniqueness).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer, make_technician, make_job, current_job_version,
    quote_and_accept, dispatch_tech, depart_and_arrive, complete_job, invoice_job,
)

DISP = TEST_USERS["dispatcher_headers"]


def test_fk_reverse_estimates_by_job(api):
    """PRD §4 routing for GET /v1/estimates (filter by job).
    PRD §3.3: "Pricing is captured as one or more `Estimate` records against the job. An
    estimate names its `job_id`."

    Design: Corner/endpoints/fk_reverse_estimates_by_job
    """
    cust = make_customer(email="fr@x.com", service_zip="43001")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    est1 = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 10000},
        DISP), 201)
    v1 = current_job_version(job["id"])  # estimate-create bumped the job version (PRD §2.5)
    est2 = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v1, "flat_rate_cents": 11000},
        DISP), 201)
    data = validate_success(api.list_estimates(DISP, params={"job_id": job["id"]}), 200)
    ids = {e["id"] for e in data}
    assert {est1["id"], est2["id"]} <= ids
    assert len(data) == 2


def test_get_invoice_by_job_filter(api):
    """PRD §4 routing for GET /v1/invoices (filter by job).
    PRD §3.7: "Invoicing creates an `Invoice` (one per job)."

    Design: Corner/endpoints/get_invoice_by_job_filter
    """
    cust = make_customer(email="gi@x.com", service_zip="44001")
    tech = make_technician(service_zone="440", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-16T09:00:00Z", "2026-08-16T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    data = validate_success(api.list_invoices(DISP, params={"job_id": job["id"]}), 200)
    assert len(data) == 1
    assert data[0]["job_id"] == job["id"]


def test_duplicate_customer_email_rejected(api):
    """PRD §3.1: "The `email` must be unique across all customers; an attempt to create a
    second customer with an `email` already in use is rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_customer_email_rejected
    """
    api.create_customer({"full_name": "First", "email": "dup@x.com", "service_zip": "37001", "phone": "1"}, DISP)
    resp = api.create_customer({"full_name": "Second", "email": "dup@x.com", "service_zip": "37002", "phone": "2"}, DISP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_duplicate_sku_code_rejected(api):
    """PRD §3.1: "The `sku_code` must be unique across all SKUs; a duplicate `sku_code` is
    rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_sku_code_rejected
    """
    api.create_material_sku({"sku_code": "DUP-1", "description": "A", "unit_price_cents": 100, "taxable": True}, DISP)
    resp = api.create_material_sku(
        {"sku_code": "DUP-1", "description": "B", "unit_price_cents": 200, "taxable": False}, DISP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)
