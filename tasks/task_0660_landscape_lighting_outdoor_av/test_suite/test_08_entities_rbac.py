"""Entity creation surface, defaults, pagination, the unzoned-fixture lock guard,
and RBAC: role-exclusive denials and authentication.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_project_with_transformer_and_zone,
    assign_fixtures_to_zone,
    submit_warranty_claim,
    setup_installed_project,
    create_customer,
    create_project,
    create_fixture,
    build_user_headers,
    make_customer_headers,
    set_clock,
    GHOST_UUID,
    api_client,
    TEST_USERS,
)
import test_helpers.factories as F

DESIGNER = TEST_USERS["lighting_designer_headers"]
TECH = TEST_USERS["install_tech_headers"]
PROGRAMMER = TEST_USERS["control_programmer_headers"]
ADMIN = TEST_USERS["operations_admin_headers"]


# ---------------------------------------------------------------------------
# Entities (corner: entities)
# ---------------------------------------------------------------------------
def test_create_project_initial_states(api):
    """PRD §3.1: "A fresh project starts with `design_status` of `DRAFT` and
    `commercial_status` of `PRE_QUOTE`." PRD §2.4: "a `version`, an integer that
    begins at its initial value on creation".

    Design: Corner/entities/create_project_returns_201_with_initial_states
    """
    cust = create_customer()
    project = validate_success(
        api.create_project(F.create_project_payload(cust["id"], property_address="1 Main"), ADMIN),
        expected_status=201,
    )
    assert project["design_status"] == "DRAFT", project["design_status"]
    assert project["commercial_status"] == "PRE_QUOTE", project["commercial_status"]
    assert project["version"] == 1, project["version"]


def test_get_nonexistent_transformer_returns_not_found(api):
    """PRD §2.9: "an identifier in a path or body that does not resolve to an
    existing resource yields `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/get_transformer_not_found_returns_404
    """
    validate_error(
        api.get_transformer("00000000-0000-4000-8000-000000000001", ADMIN),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
    )


def test_create_fixture_missing_wattage_invalid_request(api):
    """PRD §2.10: "Request-shape validation comes fourth — required fields present,
    correct types, valid enum membership ... all surfaced as `ERR_INVALID_REQUEST`."
    PRD §3.2: "its continuous `wattage_w` draw (a non-negative integer)".

    Omitting the required wattage_w on fixture create is rejected.

    Design: Corner/entities/create_fixture_missing_required_field_returns_invalid_request
    """
    cust = create_customer()
    project = create_project(cust["id"])
    resp = api.create_fixture(
        {"project_id": project["id"], "model_code": "X", "category": "PATH", "purchase_price_cents": 1000},
        DESIGNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_fixture_default_warranty_months(api):
    """PRD §3.2: "an optional `warranty_months` term that defaults to 60 months
    and must be at least one." and "A `Fixture` is created on a project in
    `PLANNED` status and, by default, unassigned — its `zone_id` is null".

    Omitting warranty_months applies the default 60; the fixture is PLANNED and
    unassigned.

    Design: Corner/entities/create_fixture_default_warranty_months_applied
    """
    cust = create_customer()
    project = create_project(cust["id"])
    fx = validate_success(
        api.create_fixture(F.create_fixture_payload(project["id"], model_code="X", category="PATH",
                                                    wattage_w=3, purchase_price_cents=1000), DESIGNER),
        expected_status=201,
    )
    assert fx["warranty_months"] == 60, fx["warranty_months"]
    assert fx["status"] == "PLANNED", fx["status"]
    assert fx["zone_id"] is None, fx["zone_id"]


def test_duplicate_customer_email_rejected_case_insensitive(api):
    """PRD §3.1: "Email is unique across customers without regard to case;
    registering an address that already exists (ignoring case) is rejected with
    `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_customer_email_returns_409
    """
    validate_success(api.create_customer({"full_name": "C1", "email": "dup_rbac@x.com"}, ADMIN),
                     expected_status=201)
    validate_error(
        api.create_customer({"full_name": "C2", "email": "DUP_RBAC@x.com"}, ADMIN),
        ApiErrorId.ERR_DUPLICATE_EMAIL.value,
    )


def test_list_projects_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    cust = create_customer()
    create_project(cust["id"])
    data, meta = validate_paginated(api.list_projects(ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] >= 1, meta
    assert isinstance(meta["has_more"], bool), meta


def test_list_projects_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100 is rejected as
    an invalid request."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    validate_error(api.list_projects(ADMIN, params={"limit": 101, "offset": 0}),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Unzoned-fixture lock guard (corner: state_machines)
# ---------------------------------------------------------------------------
def test_lock_design_with_unzoned_planned_fixture_rejected(api):
    """PRD §3.4: "every fixture on the project that is still `PLANNED` must have a
    non-null `zone_id`. If any planned fixture remains unzoned, the lock is
    rejected with `ERR_UNZONED_FIXTURE`."

    Design: Corner/state_machines/lock_design_with_unzoned_fixture_returns_unzoned_fixture
    """
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "A", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4000}])
    # A second fixture left unassigned (PLANNED, null zone_id).
    create_fixture(ctx["project_id"], model_code="B", category="PATH",
                   wattage_w=3, purchase_price_cents=4000)
    validate_error(api.lock_design(ctx["project_id"], DESIGNER), ApiErrorId.ERR_UNZONED_FIXTURE.value)
    project = validate_success(api.get_project(ctx["project_id"], DESIGNER))
    assert project["design_status"] == "ZONED", project["design_status"]


# ---------------------------------------------------------------------------
# RBAC (corner: rbac)
# ---------------------------------------------------------------------------
def test_control_programmer_cannot_create_transformer(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted
    to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`." PRD §4 endpoint
    table: POST /transformers is authorized for LightingDesigner only.

    Design: Corner/rbac/control_programmer_cannot_create_transformer
    """
    cust = create_customer()
    project = create_project(cust["id"])
    validate_error(
        api.create_transformer(F.create_transformer_payload(project["id"], rated_capacity_va=300), PROGRAMMER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


def test_customer_cannot_approve_warranty_claim(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted
    to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`." PRD §4 endpoint
    table: POST /warranty-claims/{id}/approve is authorized for OperationsAdmin only.

    Design: Corner/rbac/customer_cannot_approve_warranty_claim
    """
    ctx = setup_installed_project(
        fixture_specs=[{"model_code": "SPOT-9W", "category": "SPOT", "wattage_w": 9,
                        "purchase_price_cents": 9000}],
        quote_lines=[{"model_code": "SPOT-9W", "quantity": 1, "unit_price_cents": 9000}],
    )
    set_clock("2026-04-15T00:00:00Z")
    claim = submit_warranty_claim(ctx, ctx["fixtures"][0]["id"], reason="x")
    validate_error(
        api.approve_warranty_claim(claim["id"], make_customer_headers(ctx["cust_id"])),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    claim_now = validate_success(api.get_warranty_claim(claim["id"], ADMIN))
    assert claim_now["status"] == "SUBMITTED", claim_now["status"]


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or `X-User-Role` is not one of these
    five role names, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    nobody = build_user_headers("nobody-1", "NobodyRole")
    validate_error(
        api.create_customer({"full_name": "X", "email": "noauth@x.com"}, nobody),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
