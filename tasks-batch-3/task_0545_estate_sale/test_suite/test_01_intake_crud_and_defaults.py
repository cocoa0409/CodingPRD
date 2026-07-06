"""CRUD, creation defaults, listing, versioning, and read-after-write for the Estate Sale API.

Each test translates exactly one corner-design (breadth) instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_client, assert_project, assert_lot,
    new_client, new_project, contracted_project,
)

ADMIN = TEST_USERS["platform_admin_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


def test_client_create_echoes_all_supplied_fields(api):
    """PRD §3.1: "Every engagement begins with a `Client` — the estate owner or downsizing
    senior — registered by a `PlatformAdmin` with a `name`, a `phone` number, and an optional
    `email` (absent by default)."

    Design: Corner/entities/client_create_returns_all_fields
    """
    resp = api.create_client(
        {"name": "Test Owner", "phone": "555-9000", "email": "t@x.com"}, ADMIN
    )
    data = validate_success(resp, 201)
    assert_client(data)
    assert data["name"] == "Test Owner"
    assert data["phone"] == "555-9000"
    assert data["email"] == "t@x.com"


def test_project_computed_counters_zero_on_create(api):
    """PRD §3.1: "A new project opens in the `LEAD` state with all of its derived counters —
    `gross_sales_cents`, `buyout_advances_cents`, `unsold_lot_count`, and the three estimate
    fields — initialized to zero."

    Design: Corner/entities/project_computed_counters_zero_on_create
    """
    client = new_client(api)
    resp = api.create_project(
        {"client_id": client["id"], "address": "1 A St", "estimated_total_value_cents": 1000},
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_project(data)
    assert data["gross_sales_cents"] == 0
    assert data["buyout_advances_cents"] == 0
    assert data["unsold_lot_count"] == 0
    assert data["status"] == "LEAD"
    assert data["version"] == 1


def test_lot_defaults_applied_on_create(api):
    """PRD §3.2: "A lot defaults to `CONSIGNMENT` handling and to a fixed-price sale
    (`is_bid_lot` false); an appraiser may instead mark it a bid lot".
    PRD §3.2: "A new lot opens in the `NEW` state."

    Design: Corner/entities/lot_defaults_applied_on_create
    """
    _, project = contracted_project(api)
    resp = api.create_lot({"project_id": project["id"], "title": "Box of books"}, APPRAISER)
    data = validate_success(resp, 201)
    assert_lot(data)
    assert data["handling_type"] == "CONSIGNMENT"
    assert data["is_bid_lot"] is False
    assert data["status"] == "NEW"


def test_get_nonexistent_project_returns_not_found(api):
    """PRD §2.9: "The first reference that fails to resolve determines the error: an unresolved
    client yields `ERR_CLIENT_NOT_FOUND`, an unresolved project `ERR_PROJECT_NOT_FOUND`".

    Design: Corner/entities/project_get_nonexistent_returns_not_found
    """
    resp = api.get_project("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)


def test_lot_create_missing_title_returns_validation(api):
    """PRD §3.2: "Each item becomes a `Lot`, created against the project's `project_id` with a
    `title`."
    PRD §2.11: "Body well-formedness — required fields present, enum values in range, numeric
    fields at least 0, and a bid lot supplies its `bid_mode`, else `ERR_VALIDATION` (400)."

    Design: Corner/entities/lot_create_missing_title_returns_validation
    """
    _, project = contracted_project(api)
    resp = api.create_lot({"project_id": project["id"]}, APPRAISER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_projects_list_pagination_and_filter(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/endpoints/projects_list_pagination_and_filter
    """
    client = new_client(api)
    for addr in ("P1", "P2", "P3"):
        new_project(client["id"], api, address=addr, estimated_total_value_cents=1000)
    resp = api.list_projects(ADMIN, params={"client_id": client["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2


def test_project_immediately_readable_after_create(api):
    """PRD §3.1: "A new project opens in the `LEAD` state with all of its derived counters —
    `gross_sales_cents`, `buyout_advances_cents`, `unsold_lot_count`, and the three estimate
    fields — initialized to zero."

    Design: Corner/consistency_model/immediate_read_after_write_visible
    """
    client = new_client(api)
    created = new_project(client["id"], api, address="17 Q St", estimated_total_value_cents=1000)
    resp = api.get_project(created["id"], ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "LEAD"
    assert data["address"] == "17 Q St"


def test_project_version_increments_on_each_write(api):
    """PRD §2.4: "`version`: an integer that starts at 1 and increments by one on every
    mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/project_version_increments_on_each_write
    """
    client = new_client(api)
    project = new_project(client["id"], api, estimated_total_value_cents=1000)
    assert project["version"] == 1
    resp = api.patch_project(project["id"], {"status": "ASSESSED"}, TEST_USERS["sale_manager_headers"])
    data = validate_success(resp, 200)
    assert data["version"] == 2
