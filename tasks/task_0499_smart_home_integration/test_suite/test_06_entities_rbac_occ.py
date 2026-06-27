"""Entity CRUD facts, RBAC, listing/pagination, and optimistic concurrency.

Covers corner claims under entities (creation/defaults/computed/type/required/
not-found/referential), endpoints (filtered listing, sub-resource), rbac
(unauthorized, not-owner, unauthenticated), and the OCC complexity layer.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    factories as f, fixtures as fx,
)
from test_helpers.fixtures import (
    ADMIN, DESIGNER, PM, TECH,
    create_client, create_project, create_rack, setup_sent_proposal,
    create_crew_member, create_visit, assign_crew, project_version,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Corner / entities / create_project_returns_201_with_computed_counters_zeroed
# ===========================================================================

def test_create_project_returns_zeroed_counters_and_draft():
    """PRD §3.1: "A Project ... is created in DRAFT state".
    PRD §3.1: "Three of its fields — provisioned_device_count,
    open_change_order_count, and contract_balance_cents — are computed counters
    initialized to 0 at creation".
    PRD §2.4: "version begins at the value assigned on creation".

    Design: Corner/entities/create_project_returns_201_with_computed_counters_zeroed
    """
    client = create_client()
    data = validate_success(api_client.create_project(
        f.create_project_payload(client["id"], region_code="NORTH"), PM),
        expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["provisioned_device_count"] == 0
    assert data["open_change_order_count"] == 0
    assert data["contract_balance_cents"] == 0
    assert data["version"] == 1


# ===========================================================================
# Corner / entities / get_project_nonexistent_returns_not_found
# ===========================================================================

def test_get_nonexistent_project_returns_not_found():
    """PRD §2.5: "the system validates the existence of each path identifier in
    strict left-to-right order and rejects the request with ERR_NOT_FOUND at the
    first identifier that does not resolve to an existing in-scope resource."

    Design: Corner/entities/get_project_nonexistent_returns_not_found
    """
    resp = api_client.get_project(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Corner / entities / create_project_missing_region_code_returns_invalid_request
# ===========================================================================

def test_create_project_missing_region_code_rejected():
    """PRD §2.9: "Body well-formedness — required fields present and well-typed,
    enums in range, and the numeric bounds described throughout Section 3 — is
    checked fifth, yielding ERR_INVALID_REQUEST."
    PRD §3.1: "a region_code that is one of NORTH, SOUTH, EAST, or WEST."

    Design: Corner/entities/create_project_missing_region_code_returns_invalid_request
    """
    client = create_client()
    resp = api_client.create_project({"client_id": client["id"],
                                      "site_address": "1 St"}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Corner / entities / create_client_default_billing_tier_residential
# ===========================================================================

def test_create_client_defaults_billing_tier_residential():
    """PRD §3.1: "an optional billing_tier that is one of RESIDENTIAL or COMMERCIAL
    and defaults to RESIDENTIAL."

    Design: Corner/entities/create_client_default_billing_tier_residential
    """
    data = validate_success(api_client.create_client(
        f.create_client_payload(), ADMIN), expected_status=201)
    assert data["billing_tier"] == "RESIDENTIAL"


# ===========================================================================
# Corner / entities / device_is_controller_computed_from_category
# ===========================================================================

def test_device_is_controller_computed_from_category():
    """PRD §3.5: "a computed is_controller flag that is true exactly when the
    device's category is CONTROLLER".

    Design: Corner/entities/device_is_controller_computed_from_category
    """
    ctx = fx.setup_provisioning_project(region_code="WEST")
    rack_id = ctx["rack"]["id"]
    ctrl = validate_success(api_client.create_device(
        f.create_device_payload(rack_id, sku="C4-CTRL", category="CONTROLLER", rack_units=2),
        TECH), expected_status=201)
    spk = validate_success(api_client.create_device(
        f.create_device_payload(rack_id, sku="C4-SPK", category="AUDIO", rack_units=1),
        TECH), expected_status=201)
    assert ctrl["is_controller"] is True
    assert spk["is_controller"] is False


# ===========================================================================
# Corner / entities / create_device_invalid_category_enum_returns_invalid_request
# ===========================================================================

def test_create_device_invalid_category_rejected():
    """PRD §2.9: "Body well-formedness — required fields present and well-typed,
    enums in range, and the numeric bounds described throughout Section 3 — is
    checked fifth, yielding ERR_INVALID_REQUEST."
    PRD §3.5: "a category from the same enumeration used by line items (CONTROLLER,
    AUDIO, VIDEO, NETWORK, LIGHTING, ACCESSORY)".

    Design: Corner/entities/create_device_invalid_category_enum_returns_invalid_request
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    rack = create_rack(project["id"])
    resp = api_client.create_device(
        {"rack_id": rack["id"], "sku": "X", "category": "GADGET", "rack_units": 1}, TECH)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Corner / entities / list_projects_pagination_envelope
# ===========================================================================

def test_list_projects_pagination_meta():
    """PRD §2.3: "Paginated list-based responses include the following fields in the
    meta object of the response envelope: limit, offset, total_count, and has_more."
    PRD §2.2: "The response_type is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    client = create_client()
    create_project(client["id"], region_code="WEST")
    create_project(client["id"], region_code="WEST")
    resp = api_client.list_projects(PM, params={"client_id": client["id"], "limit": 1, "offset": 0})
    assert resp.json()["response_type"] == "array"
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ===========================================================================
# Corner / entities / device_create_nonexistent_rack_returns_referential_integrity
# ===========================================================================

def test_create_device_nonexistent_rack_returns_referential_integrity():
    """PRD §2.9: "Foreign-key referential integrity is checked sixth, yielding
    ERR_REFERENTIAL_INTEGRITY."
    PRD §3.5: "A Device is registered against a rack by a LowVoltageTech or
    ProjectManager with a rack_id".

    Design: Corner/entities/device_create_nonexistent_rack_returns_referential_integrity
    """
    resp = api_client.create_device(
        {"rack_id": NON_EXISTENT_UUID, "sku": "X", "category": "AUDIO", "rack_units": 1}, TECH)
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


# ===========================================================================
# Corner / endpoints / list_devices_filtered_by_rack_id
# ===========================================================================

def test_list_devices_filtered_by_rack_id():
    """PRD §3.5: "Devices are listable filtered by rack_id and by status."

    Design: Corner/endpoints/list_devices_filtered_by_rack_id
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    rack = create_rack(project["id"])
    get_success_data(api_client.create_device(
        f.create_device_payload(rack["id"], sku="A", category="AUDIO", rack_units=1), TECH))
    get_success_data(api_client.create_device(
        f.create_device_payload(rack["id"], sku="B", category="VIDEO", rack_units=1), TECH))
    resp = api_client.list_devices(TECH, params={"rack_id": rack["id"]})
    assert resp.json()["response_type"] == "array"
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


# ===========================================================================
# Corner / endpoints / get_rack_subresource_returns_array_of_one
# ===========================================================================

def test_get_rack_returns_array_of_one():
    """PRD §3.4: "The rack is retrievable as the project's rack collection, which
    returns an array of zero or one rack."

    Design: Corner/endpoints/get_rack_subresource_returns_array_of_one
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    rack = create_rack(project["id"], rack_units_total=8)
    resp = api_client.get_rack(project["id"], PM)
    assert resp.json()["response_type"] == "array"
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == rack["id"]


# ===========================================================================
# Corner / rbac / client_cannot_start_provisioning_returns_unauthorized
# ===========================================================================

def test_client_cannot_start_provisioning_unauthorized():
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."
    PRD §4 endpoint table: POST /projects/{id}/start-provisioning is authorized for
    ProjectManager only.

    Design: Corner/rbac/client_cannot_start_provisioning_returns_unauthorized
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    create_rack(project["id"])
    proposal = setup_sent_proposal(project["id"])
    fx.accept_proposal(project["id"], proposal["id"], client["id"])
    resp = api_client.start_provisioning(project["id"], fx.make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ===========================================================================
# Corner / rbac / non_owner_client_cannot_accept_proposal_returns_not_owner
# ===========================================================================

def test_non_owner_client_cannot_accept_proposal():
    """PRD §2.1: "A Client may accept or reject proposals and approve or reject
    change orders only on projects they own; an ownership failure on those
    operations is reported as ERR_NOT_OWNER."

    Design: Corner/rbac/non_owner_client_cannot_accept_proposal_returns_not_owner
    """
    owner = create_client(email=f.unique_email("owner"))
    other = create_client(email=f.unique_email("other"))
    project = create_project(owner["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    resp = api_client.accept_proposal(
        project["id"], proposal["id"], fx.make_client_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)


# ===========================================================================
# Corner / rbac / missing_auth_headers_returns_unauthenticated
# ===========================================================================

def test_unknown_role_returns_unauthenticated():
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized role names, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    ghost = build_user_headers("z", "Ghost")
    resp = api_client.create_client(f.create_client_payload(), ghost)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_proposal_create_stale_project_version_returns_stale_version
# ===========================================================================

def test_occ_proposal_create_stale_project_version_rejected():
    """PRD §2.8: "First, creating a new proposal carries expected_project_version,
    which must match the current version of the project named in the path".
    PRD §2.8: "if that value does not equal the parent's current version the write
    is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_proposal_create_stale_project_version_returns_stale_version
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    v0 = project["version"]
    # First create bumps the project version from v0.
    get_success_data(api_client.create_proposal(
        project["id"], f.create_proposal_payload(v0, labor_hours_estimate=1.0), DESIGNER))
    # Second create still carrying the old v0 is stale.
    resp = api_client.create_proposal(
        project["id"], f.create_proposal_payload(v0, labor_hours_estimate=2.0), DESIGNER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_assignment_create_correct_visit_version_succeeds_and_bumps
# ===========================================================================

def test_occ_assignment_create_correct_version_succeeds_and_bumps_visit():
    """PRD §2.8: "Second, creating a visit assignment carries expected_visit_version,
    which must match the current version of the visit being staffed".
    PRD §3.7: "A successful assignment recomputes the visit's assigned_crew_count
    and increments the visit's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_assignment_create_correct_visit_version_succeeds_and_bumps
    """
    client = create_client()
    project = create_project(client["id"], region_code="WEST")
    proposal = setup_sent_proposal(project["id"])
    fx.accept_proposal(project["id"], proposal["id"], client["id"])
    crew = create_crew_member(region_code="WEST", cert_level="JOURNEYMAN")
    visit = create_visit(project["id"], "2026-10-01T09:00:00Z", "2026-10-01T12:00:00Z",
                         visit_kind="INSTALL", crew_size_required=1)
    v0 = visit["version"]
    asg = validate_success(api_client.create_assignment(
        project["id"], visit["id"], f.create_assignment_payload(crew["id"], v0), PM),
        expected_status=201)
    assert asg["status"] == "ACTIVE"
    after = validate_success(api_client.get_visit_nested(project["id"], visit["id"], PM))
    assert after["version"] == v0 + 1
    assert after["assigned_crew_count"] == 1
