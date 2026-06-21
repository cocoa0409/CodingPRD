"""CRUD/defaults, RBAC, ownership, auth, pagination, and FK reverse-reachability."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_customer_headers, make_pro_headers, TEST_USERS, NON_EXISTENT_UUID,
    create_category, create_customer, create_cleared_pro, create_pro, create_window,
    create_job, in_progress_job, completed_paid_job, dispute_under_review,
    assert_service_category, assert_pro,
    create_background_check_payload, create_part_line_payload,
    resolve_dispute_payload,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# =====================================================================
# Corner: entities
# =====================================================================

def test_create_service_category_returns_201_with_fields(api):
    """PRD §3.1: "A `PlatformAdmin` defines each **service category** by supplying a `code` (a
    stable, unique identifier ...), a human-readable `name`, and a `pricing_model` that is either
    `HOURLY` or `FLAT`." PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID
    with no type prefix."

    Design: Corner/entities/create_service_category_returns_201_with_fields
    """
    res = api.create_service_category(
        {"code": "CAT_CREATE", "name": "Create Cat", "pricing_model": "HOURLY", "hourly_rate_cents": 9000},
        ADMIN)
    cat = validate_success(res, 201)
    assert_service_category(cat)
    assert cat["code"] == "CAT_CREATE"
    assert cat["pricing_model"] == "HOURLY"


def test_get_job_not_found_returns_404(api):
    """PRD §2.7: "If the parent identifier in the path does not resolve to an existing resource,
    the request fails with `ERR_NOT_FOUND` for that parent before any child or body reference is
    examined."

    Design: Corner/entities/get_job_not_found_returns_404
    """
    res = api.get_job("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_job_missing_category_id_returns_invalid_request(api):
    """PRD §3.3: "A `Customer` files a **job** by naming the `customer_id` placing the request, the
    `category_id` of the service wanted, and the five-digit `address_zip_code` where the work will
    happen." PRD §2.9: "(1) request-body well-formedness, surfacing `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_job_missing_required_category_id_returns_invalid_request
    """
    cust = create_customer(email="cf1@x.com", full_name="CF One", zip_code="30301")
    res = api.create_job(
        {"customer_id": cust["id"], "address_zip_code": "30301"},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_service_category_defaults_applied(api):
    """PRD §3.1: "The category also declares whether it `requires_license`, defaulting to false ...
    and a `callback_warranty_days` window, defaulting to 30". PRD §3.1: "Independently, a category
    may be flagged `instant_quote_eligible` (defaulting to false)."

    Design: Corner/entities/service_category_default_requires_license_false_applied
    """
    res = api.create_service_category(
        {"code": "CAT_DEF", "name": "Default Cat", "pricing_model": "FLAT", "flat_task_fee_cents": 9000},
        ADMIN)
    cat = validate_success(res, 201)
    assert cat["requires_license"] is False
    assert cat["instant_quote_eligible"] is False
    assert cat["callback_warranty_days"] == 30


def test_pro_defaults_applied(api):
    """PRD §3.2: "That markup fraction defaults to 0.25 and must lie between 0 and 1 inclusive ...
    On registration a professional's `background_check_status` is `PENDING` and their
    `license_status` is `NONE` ... their `completed_job_count`, `callback_job_count`, and
    `callback_rate` all start at zero."

    Design: Corner/entities/pro_default_truck_markup_pct_applied
    """
    res = api.create_pro({"email": "pdef@x.com", "full_name": "P Def", "home_zip_code": "30301"}, ANON)
    pro = validate_success(res, 201)
    assert pro["truck_stock_markup_pct"] == 0.25
    assert pro["background_check_status"] == "PENDING"
    assert pro["license_status"] == "NONE"
    assert pro["callback_rate"] == 0


def test_service_category_invalid_pricing_model_enum_rejected(api):
    """PRD §3.1: "a `pricing_model` that is either `HOURLY` or `FLAT`." PRD §2.9: "(1) request-body
    well-formedness, surfacing `ERR_INVALID_REQUEST`".

    Design: Corner/entities/service_category_invalid_pricing_model_enum_rejected
    """
    res = api.create_service_category(
        {"code": "CAT_BAD", "name": "Bad Cat", "pricing_model": "SUBSCRIPTION"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_service_category_flat_without_fee_semantic_invalid(api):
    """PRD §3.1: "A `FLAT` category must carry a non-negative `flat_task_fee_cents` and must leave
    `hourly_rate_cents` null ... The pricing fields must be coherent with the chosen
    `pricing_model`, and incoherence is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/service_category_flat_without_fee_semantic_invalid
    """
    res = api.create_service_category(
        {"code": "CAT_FLATNULL", "name": "Flat Null", "pricing_model": "FLAT"}, ADMIN)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_service_category_immutable_no_version_field(api):
    """PRD §2.4: "`ServiceCategory` is the one exception: it is configuration data that, once
    created, is treated as immutable. A `ServiceCategory` therefore carries only `id` and
    `created_at`; it has neither an `updated_at` nor a `version` field."

    Design: Corner/entities/service_category_immutable_no_version_field
    """
    cat = create_category(code="CAT_IMMUT", name="Immut Cat", pricing_model="HOURLY", hourly_rate_cents=9000)
    res = api.get_service_category(cat["id"], ADMIN)
    fetched = validate_success(res, 200)
    assert "created_at" in fetched
    assert "version" not in fetched
    assert "updated_at" not in fetched


# =====================================================================
# Corner: endpoints / list_jobs_pagination_envelope
# =====================================================================

def test_list_jobs_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "If not provided, it defaults to 10".

    Design: Corner/endpoints/list_jobs_pagination_envelope
    """
    cat = create_category(code="EP_LIST", name="EP List", pricing_model="HOURLY", hourly_rate_cents=9000)
    cust = create_customer(email="cep1@x.com", full_name="C EP1", zip_code="30301")
    create_job(cust["id"], cat["id"], "30301")
    create_job(cust["id"], cat["id"], "30301")
    data, meta = validate_paginated(api.list_jobs(ADMIN, params={"customer_id": cust["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10


# =====================================================================
# Corner: rbac
# =====================================================================

def test_customer_cannot_issue_invoice_unauthorized(api):
    """PRD §2.1: "If the headers are well-formed but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`." (POST
    /invoices/{id}/issue is Pro-only per §4.)

    Design: Corner/rbac/customer_cannot_issue_invoice_unauthorized
    """
    cat = create_category(code="RB_ISS", name="RB Issue", pricing_model="FLAT",
                          flat_task_fee_cents=12000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["plumb"])
    cust = create_customer(email="crb1@x.com", full_name="C RB1", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="prb1@x.com", full_name="P RB1")
    job, window = in_progress_job(cust["id"], cat["id"], pro,
                                  "2026-06-22T10:00:00.000Z", "2026-06-22T12:00:00.000Z",
                                  "2026-06-22T10:30:00.000Z")
    invoice = get_success_data(api.create_invoice(job["id"], make_pro_headers(pro["id"])))
    res = api.issue_invoice(invoice["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_pro_cannot_resolve_dispute_unauthorized(api):
    """PRD §2.1: "If the headers are well-formed but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`." (POST
    /disputes/{id}/resolve is PlatformAdmin-only per §4.)

    Design: Corner/rbac/pro_cannot_resolve_dispute_unauthorized
    """
    from test_helpers import set_clock
    set_clock("2026-06-01T08:00:00.000Z")
    cat = create_category(code="RB_RES", name="RB Resolve", pricing_model="FLAT",
                          flat_task_fee_cents=12000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["plumb"])
    cust = create_customer(email="crb2@x.com", full_name="C RB2", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="prb2@x.com", full_name="P RB2")
    job, window, invoice = completed_paid_job(
        cust["id"], cat["id"], pro,
        "2026-06-23T10:00:00.000Z", "2026-06-23T12:00:00.000Z", "2026-06-23T10:30:00.000Z",
        pay_amount=14500)
    disp = dispute_under_review(cust["id"], invoice["id"], job["id"], "OVERCHARGED", 5000)
    res = api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=5000),
                              make_pro_headers(pro["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_unauthenticated_create_job_returns_401(api):
    """PRD §2.1: "Every request that is not an open self-registration must be authenticated through
    two mandatory HTTP headers ... If either header is missing, or `X-User-Role` is not one of the
    known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_create_job_returns_401
    """
    cat = create_category(code="RB_AUTH", name="RB Auth", pricing_model="HOURLY", hourly_rate_cents=9000)
    cust = create_customer(email="crb3@x.com", full_name="C RB3", zip_code="30301")
    res = api.create_job(
        {"customer_id": cust["id"], "category_id": cat["id"], "address_zip_code": "30301"},
        headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_customer_cannot_cancel_other_customers_job_not_owner(api):
    """PRD §2.1: "when a `Customer` or `Pro` acts on a resource they do not own, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER` even though their role would in principle be allowed to
    perform the operation."

    Design: Corner/rbac/customer_cannot_cancel_other_customers_job_not_owner
    """
    cat = create_category(code="RB_OWN", name="RB Owner", pricing_model="HOURLY", hourly_rate_cents=9000)
    cust_a = create_customer(email="crbA@x.com", full_name="C RB A", zip_code="30301")
    cust_b = create_customer(email="crbB@x.com", full_name="C RB B", zip_code="30301")
    job = create_job(cust_a["id"], cat["id"], "30301")
    res = api.cancel_job(job["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


# =====================================================================
# Corner: entities (FK reverse-reachability)
# =====================================================================

def test_list_part_lines_for_job_fk_reverse(api):
    """PRD §2.7: "the visits, labor lines, part lines, quotes, and invoices that hang off a
    particular job". PRD §3.6: "If the part came `from_truck_stock`, the system computes a markup
    equal to the base multiplied by the professional's `truck_stock_markup_pct`, rounded half-up to
    whole cents; that markup is then capped so it never exceeds 5,000 cents, and floored so it is
    never less than 300 cents; the line total is the base plus this capped-and-floored markup".

    Design: Corner/entities/list_part_lines_for_job_fk_reverse
    """
    cat = create_category(code="FK_PL", name="FK PartLine", pricing_model="HOURLY",
                          hourly_rate_cents=9000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["appliance"])
    cust = create_customer(email="cfk1@x.com", full_name="C FK1", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["appliance"], home_zip_code="30301",
                             email="pfk1@x.com", full_name="P FK1", truck_stock_markup_pct=0.35)
    job, window = in_progress_job(cust["id"], cat["id"], pro,
                                  "2026-06-27T10:00:00.000Z", "2026-06-27T12:00:00.000Z",
                                  "2026-06-27T10:30:00.000Z")
    pro_h = make_pro_headers(pro["id"])
    pl = get_success_data(api.create_part_line(
        job["id"], create_part_line_payload("Belt", 4000, 2, from_truck_stock=True), pro_h))
    data, meta = validate_paginated(api.list_part_lines(job["id"], pro_h))
    match = [p for p in data if p["id"] == pl["id"]]
    assert len(match) == 1
    assert match[0]["line_total_cents"] == 10800


def test_list_pro_background_checks_fk_reverse(api):
    """PRD §3.2: "vetting is administered by a `PlatformAdmin` who submits **background checks**
    against the professional. Each check declares a `check_type` of `CRIMINAL`, `IDENTITY`, or
    `LICENSE` ... A submitted check is created with a `decision` of `PENDING`."

    Design: Corner/entities/list_pro_background_checks_fk_reverse
    """
    pro = create_pro(email="pfk2@x.com", full_name="P FK2", home_zip_code="30301")
    bc = get_success_data(api.create_background_check(
        pro["id"], create_background_check_payload(check_type="CRIMINAL"), ADMIN))
    data, meta = validate_paginated(api.list_background_checks(pro["id"], ADMIN))
    match = [c for c in data if c["id"] == bc["id"]]
    assert len(match) == 1
    assert match[0]["decision"] == "PENDING"
