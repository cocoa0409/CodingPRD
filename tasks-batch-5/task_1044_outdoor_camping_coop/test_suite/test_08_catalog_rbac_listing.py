"""Catalog validation, role-based access control, and list pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, fixtures,
)

ADMIN = fixtures.ADMIN
STAFF = fixtures.STAFF
ANON = fixtures.ANON


# ---------------------------------------------------------------------------
# Queue B — entities / product_missing_required_field_returns_validation
# ---------------------------------------------------------------------------

def test_create_product_missing_sku_rejected(api):
    """PRD §2.9: "A body that is structurally malformed — a missing required
    field, a value of the wrong type, or an unknown enum value — is rejected with
    `ERR_VALIDATION` (HTTP 400) before business rules run."

    Design: Corner/entities/product_missing_required_field_returns_validation
    """
    validate_error(api.create_product({
        "name": "No SKU", "category": "TENT", "retail_price_cents": 1000,
        "tax_rate": 0.05, "replacement_value_cents": 2000,
    }, ADMIN), ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Queue B — rbac / member_cannot_create_product_forbidden
# ---------------------------------------------------------------------------

def test_member_cannot_create_product(api):
    """PRD §2.1: "A syntactically authenticated caller whose role is not permitted
    to perform the requested operation — or an entity-backed caller reaching for a
    resource it does not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_product_forbidden
    """
    member, member_headers = fixtures.create_active_member(api)
    validate_error(api.create_product({
        "sku": "RB-TENT", "name": "RB Tent", "category": "TENT",
        "retail_price_cents": 1000, "tax_rate": 0.05, "replacement_value_cents": 2000,
    }, member_headers), ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Queue B — rbac / staff_cannot_finalize_dividend_forbidden
# ---------------------------------------------------------------------------

def test_store_staff_cannot_finalize_dividend(api):
    """PRD §2.1: "A syntactically authenticated caller whose role is not permitted
    to perform the requested operation — or an entity-backed caller reaching for a
    resource it does not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/staff_cannot_finalize_dividend_forbidden
    """
    decl = fixtures.create_draft_declaration(api, year=2026, declared_rate=0.08)
    validate_error(api.finalize_declaration(decl["id"], STAFF),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Queue B — endpoints / members_list_pagination_has_more
# ---------------------------------------------------------------------------

def test_members_list_pagination_reports_has_more(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit`, `offset`,
    `total_count` (the total number of records matching the filter, ignoring
    pagination), and `has_more` (true when records remain beyond the current
    page)."

    Design: Corner/endpoints/members_list_pagination_has_more
    """
    validate_success(api.register_member({"email": "pg1@x.com", "full_name": "PG One"}, ANON), 201)
    validate_success(api.register_member({"email": "pg2@x.com", "full_name": "PG Two"}, ANON), 201)
    data, meta = validate_paginated(api.list_members(ADMIN, params={"limit": 1}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
