"""CRUD, listing/pagination, input validation, system fields, FK existence.

Covers project/surface/payment/line-item creation, retrieval, listing, filtering,
required-field and range validation, server-minted system fields, and not-found
resolution for the House Painting Contractor API.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_project_payload, create_surface_payload, create_paint_product_payload,
    assert_project, assert_surface, assert_payment,
    create_product, create_project, add_surface,
    setup_estimated_project, pay_deposit,
    TEST_DEFAULTS,
)

EST = "estimator_headers"


def test_create_project_returns_201_with_defaults(api, estimator_headers):
    """PRD §3.2: "A freshly created project begins in `DRAFT` on its workflow axis
    and `UNPAID` on its payment axis, with every computed monetary total at 0 and
    `version` at 1."
    PRD §3.2: "`deposit_pct`, the deposit percentage of the estimate total, an integer
    from 0 through 100 that defaults to 30; and `warranty_months`, the touch-up warranty
    length in months counted from completion, defaulting to 12."

    Design: Corner/entities/create_project_returns_201_with_defaults
    """
    res = api.create_project(
        create_project_payload(customer_id="cust-1", site_address="1 Oak St", scope="INTERIOR"),
        estimator_headers,
    )
    project = validate_success(res, 201)
    assert_project(project)
    assert project["workflow_status"] == "DRAFT"
    assert project["payment_status"] == "UNPAID"
    assert project["deposit_pct"] == 30
    assert project["warranty_months"] == 12
    assert project["version"] == 1
    assert project["estimate_total_cents"] == 0


def test_get_project_not_found_returns_404(api, estimator_headers):
    """PRD §2.6: "The first identifier that does not resolve causes immediate rejection
    with the corresponding 404 error — `ERR_PROJECT_NOT_FOUND`, ..."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    res = api.get_project("00000000-0000-4000-8000-000000000000", estimator_headers)
    validate_error(res, "ERR_PROJECT_NOT_FOUND", expected_status=404)


def test_list_projects_paginated_envelope(api, estimator_headers):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_projects_paginated_envelope
    """
    create_project()
    data, meta = validate_paginated(api.list_projects(estimator_headers))
    assert isinstance(data, list)
    assert "total_count" in meta
    assert "has_more" in meta
    assert "limit" in meta
    assert "offset" in meta
    assert meta["total_count"] >= 1


def test_list_projects_filter_by_customer_id(api, estimator_headers):
    """PRD §3.2: "An estimator opens a **project** by supplying the homeowner's
    `customer_id` (the opaque account identifier the customer will authenticate with)..."
    PRD §4: "List projects; optional `customer_id` filter"

    Design: Corner/entities/list_projects_filter_by_customer_id
    """
    create_project(customer_id="cust-1", site_address="1 Oak St", scope="INTERIOR")
    proj2 = create_project(customer_id="cust-2", site_address="2 Elm St", scope="EXTERIOR")
    data, _ = validate_paginated(api.list_projects(estimator_headers, params={"customer_id": "cust-2"}))
    returned_ids = [p["id"] for p in data]
    assert proj2["id"] in returned_ids
    assert all(p["customer_id"] == "cust-2" for p in data)


def test_create_project_missing_scope_returns_invalid_request(api, estimator_headers):
    """PRD §3.2: "An estimator opens a **project** by supplying the homeowner's
    `customer_id` (the opaque account identifier the customer will authenticate with),
    the `site_address` of the job, and the overall `scope` (one of `INTERIOR`, `EXTERIOR`,
    or `BOTH`)."

    Design: Corner/entities/create_project_missing_scope_returns_invalid_request
    """
    res = api.create_project(
        {"customer_id": "cust-1", "site_address": "1 Oak St"}, estimator_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_surface_coats_out_of_range_returns_invalid_request(api, estimator_headers):
    """PRD §3.2: "a `coats` count (from 1 through 4 inclusive)..."
    PRD §3.12: "numeric ranges honored, namely `area_sqft` at least 1, `coats` from
    1 through 4, ... (`ERR_INVALID_REQUEST`, 422)."

    Design: Corner/entities/surface_coats_out_of_range_returns_invalid_request
    """
    product = create_product()
    project = create_project()
    res = api.create_surface(
        create_surface_payload(project["id"], product["id"], label="Bad", coats=5),
        estimator_headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_surface_system_fields_are_server_minted(api, estimator_headers):
    """PRD §3.2: "The surface is created in `PLANNED` status with its `color_locked`
    flag false."
    PRD §2.4: "`version` — a system-managed integer that begins at 1 on creation..."

    Design: Corner/entities/surface_system_fields_are_server_minted
    """
    product = create_product()
    project = create_project()
    res = api.create_surface(
        # Attempt to inject a client-supplied status; the server must force PLANNED.
        create_surface_payload(project["id"], product["id"], status="EXECUTED"),
        estimator_headers,
    )
    surface = validate_success(res, 201)
    assert_surface(surface)
    assert surface["status"] == "PLANNED"
    assert surface["project_id"] == project["id"]
    assert surface["version"] == 1


def test_payment_is_immutable_no_version_field(api, estimator_headers, customer_headers):
    """PRD §2.4: "A `Payment` is an append-only ledger row: it carries only `id` and
    `created_at`. A `Payment` has neither an `updated_at` nor a `version`, because once
    captured a payment row is never mutated in place..."

    Design: Corner/entities/payment_is_immutable_no_version_field
    """
    _, project, _ = setup_estimated_project(project_overrides={"deposit_pct": 30})
    payment = pay_deposit(project["id"], TEST_DEFAULTS["S1_DEPOSIT_30PCT_CENTS"])
    res = api.get_payment(payment["id"], estimator_headers)
    fetched = validate_success(res, 200)
    assert_payment(fetched)
    assert fetched["status"] == "CAPTURED"
    assert "version" not in fetched, "Payment must NOT expose a version field"
    assert "updated_at" not in fetched, "Payment must NOT expose an updated_at field"


def test_surface_list_isolated_by_project_id_filter(api, estimator_headers):
    """PRD §2.5: "Children are discovered through filtered list queries (for instance,
    listing surfaces by `project_id`, or color selections by `surface_id`), never through
    path nesting."
    PRD §2.6: "The first identifier that does not resolve causes immediate rejection with
    the corresponding 404 error — ... `ERR_SURFACE_NOT_FOUND`, ..."

    Design: Corner/validations/surface_list_isolated_by_project_id_filter
    """
    product = create_product()
    proj_a = create_project(site_address="A")
    add_surface(proj_a["id"], product["id"])
    proj_b = create_project(site_address="B")

    data_b, _ = validate_paginated(
        api.list_surfaces(estimator_headers, params={"project_id": proj_b["id"]}))
    assert data_b == [], "projB has no surfaces; filter must isolate by project_id"

    res = api.get_surface("00000000-0000-4000-8000-000000000000", estimator_headers)
    validate_error(res, "ERR_SURFACE_NOT_FOUND", expected_status=404)


def test_line_items_reverse_reachable_by_surface_filter(api, estimator_headers):
    """PRD §3.2: "line items may be filtered by `project_id` or `surface_id`."
    PRD §3.2: "Creating a surface immediately spawns exactly one **line item** for it
    (one line item per non-`REMOVED` surface) and computes that line item's estimate."

    Design: Corner/endpoints/line_items_reverse_reachable_by_surface_filter
    """
    product = create_product()
    project = create_project()
    s1 = add_surface(project["id"], product["id"], label="Bedroom",
                     area_sqft=120, coats=1, prep_level="LIGHT")
    add_surface(project["id"], product["id"], label="Hall",
                area_sqft=100, coats=2, prep_level="LIGHT")

    data, _ = validate_paginated(
        api.list_line_items(estimator_headers, params={"surface_id": s1["id"]}))
    assert len(data) == 1
    assert data[0]["surface_id"] == s1["id"]
    assert data[0]["material_cost_cents"] == TEST_DEFAULTS["S1_MATERIAL_CENTS"]


def test_crew_member_not_found_on_assignment(api, project_manager_headers):
    """PRD §2.6: "The first identifier that does not resolve causes immediate rejection
    with the corresponding 404 error — ... `ERR_CREW_MEMBER_NOT_FOUND`, ..."

    Design: Corner/errors/crew_member_not_found_on_assignment
    """
    project = create_project()
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": "00000000-0000-4000-8000-000000000000",
            "start_date": "2026-03-02",
            "end_date": "2026-03-03",
        },
        project_manager_headers,
    )
    validate_error(res, "ERR_CREW_MEMBER_NOT_FOUND", expected_status=404)
