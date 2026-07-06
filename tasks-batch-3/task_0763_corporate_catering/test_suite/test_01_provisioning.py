"""Provisioning: site/employee creation, FK & uniqueness guards, listing, and immediate
read-after-write consistency (PRD §2.3, §2.5, §2.8, §3.1, §3.6).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    is_valid_uuid, assert_client_site, assert_employee, assert_vendor,
    create_client_site_payload, create_vendor_payload,
    create_site, create_employee, setup_catering_order,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["site_admin_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def test_create_client_site_returns_201_with_defaults(api):
    """PRD §3.1: "A new site opens `ACTIVE` with `cost_status` of `ON_TARGET`, its ledger
    counters `period_food_cost_cents`, `period_revenue_cents`, and `inventory_value_cents`
    at 0, and `version` 1."

    Design: Corner/entities/create_client_site_returns_201_with_defaults
    """
    res = api.create_client_site(create_client_site_payload(), ADMIN)
    site = validate_success(res, 201)
    assert_client_site(site)
    assert site["status"] == "ACTIVE"
    assert site["cost_status"] == "ON_TARGET"
    assert site["version"] == 1
    assert site["period_food_cost_cents"] == 0
    assert site["period_revenue_cents"] == 0
    assert site["inventory_value_cents"] == 0


def test_get_client_site_not_found_returns_404(api):
    """PRD §2.8: "the first identifier that does not resolve to an existing resource causes
    an `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_client_site_not_found_returns_404
    """
    res = api.get_client_site(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_employee_missing_badge_id_returns_validation(api):
    """PRD §3.1: "Employees are registered at a site by a site admin, who provides the
    owning `client_site_id`, a `badge_id` unique among employees at that site, and the
    employee's `full_name`."
    PRD §2.8: "Body validation — required fields present ... else `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_employee_missing_badge_id_returns_validation
    """
    site = create_site()
    res = api.create_employee({"client_site_id": site["id"], "full_name": "No Badge"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_create_employee_bad_site_fk_returns_not_found(api):
    """PRD §2.8: "the first identifier that does not resolve to an existing resource causes
    an `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_employee_bad_site_fk_returns_not_found
    """
    res = api.create_employee(
        {"client_site_id": NON_EXISTENT_UUID, "badge_id": "B1", "full_name": "Ghost"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_duplicate_badge_at_site_rejected(api):
    """PRD §3.1: "Each `badge_id` must be unique within its site; a collision is rejected
    with `ERR_DUPLICATE_BADGE`."

    Design: Corner/entities/duplicate_badge_at_site_rejected
    """
    site = create_site()
    create_employee(site["id"], badge_id="B1", full_name="First")
    res = api.create_employee(
        {"client_site_id": site["id"], "badge_id": "B1", "full_name": "Second"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_BADGE.value, expected_status=409)


def test_system_fields_server_minted_on_create(api):
    """PRD §2.5: "The `id` is a server-minted UUID with no type prefix."
    PRD §2.5: "The `version` is an integer that begins at 1 when the resource is created
    and increases by 1 on every mutation of that resource."

    Design: Corner/entities/system_fields_server_minted_on_create
    """
    res = api.create_vendor(create_vendor_payload(category="PRODUCE"), ADMIN)
    vendor = validate_success(res, 201)
    assert_vendor(vendor)
    assert vendor["version"] == 1
    assert is_valid_uuid(vendor["id"]), "id must be a bare UUID with no type prefix"
    assert ":" not in vendor["id"] and "_" not in vendor["id"], "id carries no type prefix"


def test_list_employees_by_site_paginated(api):
    """PRD §2.3: "Each list response reports pagination state in `meta` through four fields:
    `limit`, `offset`, `total_count` (the total number of records matching the query before
    pagination), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/endpoints/list_employees_by_site_fk_reverse
    """
    site = create_site()
    create_employee(site["id"], badge_id="B1", full_name="One")
    create_employee(site["id"], badge_id="B2", full_name="Two")

    data, meta = validate_paginated(
        api.list_employees(ADMIN, params={"client_site_id": site["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(emp["client_site_id"] == site["id"] for emp in data)


def test_created_catering_order_immediately_visible(api):
    """PRD §3.6: "The order opens in `DRAFT` with `requires_finance_review` initially false."

    Design: Corner/consistency_model/immediate_visibility_of_created_order
    """
    ctx = setup_catering_order(target="DRAFT")
    res = api.get_catering_order(ctx["order"]["id"], FINANCE)
    order = validate_success(res, 200)
    assert order["status"] == "DRAFT"
