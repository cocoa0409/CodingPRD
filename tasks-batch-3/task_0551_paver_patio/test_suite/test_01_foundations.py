"""Foundational records, creation/validation surfaces, listing, and access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_project, assert_product, assert_line_item,
    customer_payload, product_payload, project_payload, line_item_payload,
    TEST_USERS, make_client_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["platform_admin_headers"]
DESIGN = TEST_USERS["design_consultant_headers"]
PM = TEST_USERS["project_manager_headers"]


def test_create_project_returns_201_draft_version_1(api):
    """PRD §4: "Operations that create a new, stand-alone resource return `201 Created`."
    PRD §3.2: "A new project starts in `DRAFT`."
    PRD §2.4: "an integer `version` that starts at 1 and increments by one on each mutation."

    Design: Corner/entities/project_creation_returns_201_with_draft_status
    """
    customer = fx.make_customer(api, email="no@example.com", name="New Owner")
    resp = api.create_project(project_payload(customer["id"], site_address="20 Yard Ln"), DESIGN)
    data = validate_success(resp, 201)
    assert_project(data)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_get_unknown_project_returns_not_found(api):
    """PRD §2.5: "the first identifier that resolves to nothing yields that entity's own
    not-found code — `ERR_PROJECT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`,
    `ERR_SITE_MEASUREMENT_NOT_FOUND`, ... — all 404."

    Design: Corner/entities/get_nonexistent_project_returns_not_found
    """
    resp = api.get_project(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)


def test_get_unknown_design_revision_returns_not_found(api):
    """PRD §2.5: "the first identifier that resolves to nothing yields that entity's own
    not-found code — `ERR_PROJECT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`,
    `ERR_SITE_MEASUREMENT_NOT_FOUND`, ... — all 404."

    Design: Corner/entities/get_nonexistent_design_revision_returns_not_found
    """
    resp = api.get_design_revision(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DESIGN_REVISION_NOT_FOUND)


def test_create_line_item_without_product_id_invalid(api):
    """PRD §2.5: "Required fields must be present, types valid, enum members recognized,
    quantities strictly positive, and dates parseable; otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_line_item_missing_product_id_returns_invalid_request
    """
    customer = fx.make_customer(api, email="or@example.com")
    project = fx.make_project(api, customer["id"], site_address="21 Yard Ln")
    resp = api.create_line_item({"project_id": project["id"], "measured_quantity": 100}, DESIGN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_product_invalid_category_invalid(api):
    """PRD §2.5: "Required fields must be present, types valid, enum members recognized,
    quantities strictly positive, and dates parseable; otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_product_invalid_category_enum_returns_invalid_request
    """
    resp = api.create_product(product_payload(sku="BOGUS-1", name="Bogus", category="GAZEBO",
                                              unit="EACH", unit_price_cents=100,
                                              waste_factor=0, coverage_per_pallet_sqft=0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_is_feature_computed_from_category(api):
    """PRD §3.1: "At creation the system also derives the read-only `is_feature` flag, which
    is true exactly when the product's `category` is `FIRE_PIT` or `OUTDOOR_KITCHEN`; this flag
    feeds per-feature labor pricing."

    Design: Corner/entities/product_is_feature_is_computed_from_category
    """
    resp = api.create_product(product_payload(sku="FIRE-KIT", name="Fire Pit Kit",
                                              category="FIRE_PIT", unit="EACH",
                                              unit_price_cents=180000), ADMIN)
    data = validate_success(resp, 201)
    assert_product(data)
    assert data["is_feature"] is True, f"expected is_feature True for FIRE_PIT, got {data.get('is_feature')}"


def test_line_item_category_denormalized(api):
    """PRD §3.2: "At creation the line's `category` is denormalized from the product's category,
    its `origin` is set to `ORIGINAL`, and its `pinned_unit_price_cents` and `installed_quantity`
    remain null until, respectively, the contract is signed and a covering phase completes."

    Design: Corner/entities/line_item_category_denormalized_from_product
    """
    customer = fx.make_customer(api, email="oc@example.com")
    wall = fx.make_wall_product(api)
    project = fx.make_project(api, customer["id"], site_address="22 Yard Ln")
    resp = api.create_line_item(line_item_payload(project["id"], wall["id"], 30), DESIGN)
    data = validate_success(resp, 201)
    assert_line_item(data)
    assert data["category"] == "WALL_BLOCK", f"expected WALL_BLOCK, got {data['category']}"


def test_project_in_hoa_defaults_false(api):
    """PRD §3.2: "...and an optional `in_hoa` flag (default false) declaring whether the site
    sits inside a homeowners association."

    Design: Corner/entities/project_in_hoa_defaults_false
    """
    customer = fx.make_customer(api, email="od@example.com")
    resp = api.create_project(project_payload(customer["id"], site_address="23 Yard Ln"), DESIGN)
    data = validate_success(resp, 201)
    assert data["in_hoa"] is False, f"expected in_hoa False by default, got {data.get('in_hoa')}"


def test_create_project_unknown_customer_not_found(api):
    """PRD §2.5: "Identifiers carried in the body — `customer_id`, `product_id`, `add_product_id`,
    `crew_id`, `work_phase_id`, and every entry of `line_item_ids` or `covered_line_item_ids` —
    must resolve and belong where required, surfacing `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, or `ERR_LINE_ITEM_NOT_FOUND` (all 404)."

    Design: Corner/entities/create_project_unknown_customer_returns_not_found
    """
    resp = api.create_project(project_payload(NON_EXISTENT_UUID, site_address="24 Yard Ln"), DESIGN)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


def test_create_line_item_unknown_product_not_found(api):
    """PRD §2.5: "Identifiers carried in the body — `customer_id`, `product_id`, `add_product_id`,
    `crew_id`, `work_phase_id`, and every entry of `line_item_ids` or `covered_line_item_ids` —
    must resolve and belong where required, surfacing `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, or `ERR_LINE_ITEM_NOT_FOUND` (all 404)."

    Design: Corner/entities/create_line_item_unknown_product_returns_not_found
    """
    customer = fx.make_customer(api, email="op@example.com")
    project = fx.make_project(api, customer["id"], site_address="25 Yard Ln")
    resp = api.create_line_item(line_item_payload(project["id"], NON_EXISTENT_UUID, 100), DESIGN)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)


def test_new_project_starts_in_draft(api):
    """PRD §3.2: "A new project starts in `DRAFT`."

    Design: Corner/state_machines/new_project_starts_in_draft
    """
    customer = fx.make_customer(api, email="oi@example.com")
    resp = api.create_project(project_payload(customer["id"], site_address="26 Yard Ln"), DESIGN)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"


def test_list_project_line_items_returns_array(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/endpoints/list_project_line_items_returns_array
    """
    customer = fx.make_customer(api, email="ol@example.com")
    product = fx.make_paver(api)
    project = fx.make_project(api, customer["id"], site_address="42 Yard Ln")
    fx.add_line(api, project["id"], product["id"], 100)
    fx.add_line(api, project["id"], product["id"], 60)
    resp = api.list_project_line_items(project["id"], DESIGN)
    data, _meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 line items, got {len(data)}"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    customer = fx.make_customer(api, email="oau@example.com")
    project = fx.make_project(api, customer["id"], site_address="43 Yard Ln")
    resp = api.get_project(project["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_client_cannot_create_line_item_unauthorized(api):
    """PRD §2.1: "When both headers are present but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/client_cannot_create_line_item_returns_unauthorized
    """
    customer = fx.make_customer(api, email="ouz@example.com")
    product = fx.make_paver(api)
    project = fx.make_project(api, customer["id"], site_address="44 Yard Ln")
    resp = api.create_line_item(line_item_payload(project["id"], product["id"], 100),
                                make_client_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
