"""CRUD, defaults, validation, RBAC, pagination, and atomic-consistency claims
for the IT Asset & License inventory.

Each test translates exactly one corner-design (queue B) instance.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    set_clock, create_vendor, create_software_product, create_employee,
    setup_employee_and_asset, open_checkout, setup_over_deployed_finding,
)

MGR = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
EMP = TEST_USERS["employee_headers"]


# ─── entities section ─────────────────────────────────

def test_create_hardware_asset_returns_201_with_computed_fields(api):
    """PRD 3.2: "A newly created asset has `status` of `IN_STOCK`, a
    `support_status` of `UNCOVERED`, and `disposal_proceeds_cents` of 0."
    PRD 2.5: "a `version`, an integer that starts at 1 and increments by one
    on every mutation of the resource."

    Design: Corner/entities/create_hardware_asset_returns_201_with_computed_fields
    """
    set_clock("2024-01-01T00:00:00.000Z")
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    resp = api.create_hardware(
        {
            "vendor_id": vendor["id"], "asset_tag": "TAG-NEW", "category": "LAPTOP",
            "purchase_cost_cents": 120000, "in_service_date": "2024-01-01T00:00:00.000Z",
            "useful_life_months": 24, "salvage_value_cents": 0,
        },
        MGR,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "IN_STOCK"
    assert data["support_status"] == "UNCOVERED"
    # 0 whole months elapsed at the in-service date → no depreciation booked.
    assert data["net_book_value_cents"] == 120000
    assert data["version"] == 1


def test_get_hardware_asset_not_found_returns_404(api):
    """PRD 2.8: "every identifier in the URL path and every foreign-key
    identifier in the request body must resolve to an existing entity,
    validated left to right, and the first unresolved identifier yields
    `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/get_hardware_asset_not_found_returns_404
    """
    resp = api.get_hardware("00000000-0000-4000-8000-000000000000", MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_entitlement_missing_required_field_returns_invalid_request(api):
    """PRD 2.8: "Request well-formedness is fourth: required fields must be
    present, enum values must be legal, numeric fields constrained to be
    non-negative must satisfy that constraint, and per-core fields must be
    consistent with the product's license model; a violation yields
    `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_entitlement_missing_required_field_returns_invalid_request
    """
    vendor = create_vendor(vendor_type="SOFTWARE", name="SW Co")
    product = create_software_product(vendor["id"], license_model="PER_SEAT")
    # entitled_units omitted — a required input on POST /assets/entitlements.
    resp = api.create_entitlement(
        {
            "software_product_id": product["id"], "vendor_id": vendor["id"],
            "unit_price_cents": 1000,
            "term_start": "2025-01-01T00:00:00.000Z",
            "term_end": "2025-12-31T00:00:00.000Z",
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_employee_default_max_assigned_assets_applied(api):
    """PRD 3.1: "an optional `max_assigned_assets` cap may be supplied and
    defaults to 3, governing how many hardware checkouts the employee may hold
    open at once". PRD 3.1: "A new employee always begins life with `status` of
    `ACTIVE` and an `open_checkout_count` of 0."

    Design: Corner/entities/create_employee_default_max_assigned_assets_applied
    """
    resp = api.create_employee(
        {"full_name": "Dee", "email": "dee@x.com", "department": "OPS"}, MGR
    )
    data = validate_success(resp, 201)
    assert data["max_assigned_assets"] == 3
    assert data["status"] == "ACTIVE"
    assert data["open_checkout_count"] == 0


def test_create_entitlement_invalid_term_window_returns_error(api):
    """PRD 3.4: "activation requires that it currently be `DRAFT` ... and that
    its term window be well-formed, with `term_start` no later than `term_end`
    — a reversed window is rejected with `ERR_INVALID_TERM_WINDOW`."

    Design: Corner/entities/create_entitlement_invalid_term_window_returns_error
    """
    vendor = create_vendor(vendor_type="SOFTWARE", name="SW Co")
    product = create_software_product(vendor["id"], license_model="PER_SEAT")
    # PRD ties the reversed-window check to *activation*, not creation: the entitlement
    # is created in DRAFT carrying the (reversed) window, and the check fires on activate.
    created = validate_success(api.create_entitlement(
        {
            "software_product_id": product["id"], "vendor_id": vendor["id"],
            "entitled_units": 5, "unit_price_cents": 1000,
            "term_start": "2025-12-31T00:00:00.000Z",
            "term_end": "2025-01-01T00:00:00.000Z",
        },
        MGR,
    ), 201)
    resp = api.activate_entitlement(created["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM_WINDOW.value)


def test_install_id_and_system_fields_server_generated(api):
    """PRD 3.4: "A new install is `PENDING` and consumes nothing yet". PRD 3.4:
    "For a per-seat product this is always exactly 1, regardless of the
    machine's core count."

    Design: Corner/entities/install_id_and_system_fields_server_generated
    """
    from test_helpers import setup_product_with_active_entitlement, create_hardware
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="BOTH", license_model="PER_SEAT", entitled_units=5,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-SYS", category="DESKTOP")
    resp = api.create_installation(
        {
            "software_product_id": product["id"], "hardware_asset_id": asset["id"],
            "license_entitlement_id": entitlement["id"],
            "expected_entitlement_version": entitlement["version"],
        },
        MGR,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING"
    assert data["required_core_units"] == 1


def test_finding_immutable_no_version_field(api):
    """PRD 2.5: "A `ComplianceFinding` is an immutable audit record minted at
    true-up finalization and never subsequently changed; it therefore carries
    only `id` and `created_at`. It has no `updated_at` and no `version` field
    at all."

    Design: Corner/entities/finding_immutable_no_version_field
    """
    product, entitlement, finalized = setup_over_deployed_finding()
    resp = api.list_true_up_findings(finalized["id"], CO)
    findings, _meta = validate_paginated(resp)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["finding_type"] == "OVER_DEPLOYED"
    assert finding["shortfall_units"] == 1
    assert "version" not in finding, "ComplianceFinding must not carry a version field"
    assert "updated_at" not in finding, "ComplianceFinding must not carry updated_at"


# ─── endpoints section: pagination + reverse reachability ─────

def test_list_entitlements_filtered_by_product_paginated(api):
    """PRD 3.4: "Entitlements can be listed and filtered by
    `software_product_id`, `vendor_id`, or `status`." PRD 2.3: "The response
    envelope's `meta` object for any list carries the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_entitlements_filtered_by_product_paginated
    """
    from test_helpers import create_entitlement
    vendor = create_vendor(vendor_type="SOFTWARE", name="SW Co")
    prod_a = create_software_product(vendor["id"], license_model="PER_SEAT", name="ProdA")
    prod_b = create_software_product(vendor["id"], license_model="PER_SEAT", name="ProdB")
    create_entitlement(prod_a["id"], vendor["id"], entitled_units=5)
    create_entitlement(prod_a["id"], vendor["id"], entitled_units=3)
    create_entitlement(prod_b["id"], vendor["id"], entitled_units=9)

    resp = api.list_entitlements(
        CO, params={"software_product_id": prod_a["id"], "limit": 10, "offset": 0}
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert all(e["software_product_id"] == prod_a["id"] for e in data)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_findings_filtered_by_product_reverse_reachability(api):
    """PRD 3.7: "the finalize step mints a `ComplianceFinding` linked to the run
    through `true_up_reconciliation_id` and to the product through
    `software_product_id`". PRD 3.7: "findings overall can be listed and
    filtered by `software_product_id` or `true_up_reconciliation_id`."

    Design: Corner/endpoints/findings_filtered_by_product_reverse_reachability
    """
    product, entitlement, finalized = setup_over_deployed_finding()
    resp = api.list_findings(CO, params={"software_product_id": product["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["finding_type"] == "OVER_DEPLOYED"
    assert data[0]["software_product_id"] == product["id"]


# ─── rbac section ─────────────────────────────────────

def test_asset_manager_cannot_approve_disposal_forbidden(api):
    """PRD 2.1: "A request whose role is well-formed but not permitted to
    perform the requested operation, according to the authorization table in
    Section 4, is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/asset_manager_cannot_approve_disposal_forbidden
    """
    from test_helpers import submit_disposal, create_vendor as cv, create_hardware
    vendor = cv(vendor_type="HARDWARE", name="HW Corp")
    asset = create_hardware(vendor["id"], asset_tag="TAG-RB1", category="LAPTOP")
    request = submit_disposal(asset["id"], reason="END_OF_LIFE", submitter_id="mgr-1")
    # AssetManager is not authorized for the approve operation (ComplianceOfficer only).
    resp = api.approve_disposal(request["id"], TEST_USERS["asset_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_employee_cannot_create_hardware_forbidden(api):
    """PRD 2.1: "The `Employee` role is read-only and may not perform any
    mutating operation."

    Design: Corner/rbac/employee_cannot_create_hardware_forbidden
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    resp = api.create_hardware(
        {
            "vendor_id": vendor["id"], "asset_tag": "TAG-RB2", "category": "LAPTOP",
            "purchase_cost_cents": 100000, "in_service_date": "2025-01-01T00:00:00.000Z",
        },
        EMP,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or whose `X-User-Role` is
    not one of these three values, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_vendor(
        {"name": "Anon", "vendor_type": "HARDWARE", "support_email": "a@x.com"},
        {"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── consistency_model section ────────────────────────

def test_checkout_cascade_visible_in_same_request(api):
    """PRD 3.3: "When all conditions pass, a checkout record is created with
    `status` of `OPEN`, the employee's `open_checkout_count` is increased by
    one, and the asset moves to `ASSIGNED`."

    Design: Corner/consistency_model/checkout_cascade_visible_in_same_request
    """
    vendor, employee, asset = setup_employee_and_asset(
        emp_overrides={"email": "fay@x.com"},
        asset_overrides={"asset_tag": "TAG-IMM", "category": "LAPTOP"},
    )
    checkout = open_checkout(asset["id"], employee["id"])
    assert checkout["status"] == "OPEN"

    emp_after = validate_success(api.get_employee(employee["id"], MGR))
    assert emp_after["open_checkout_count"] == 1

    asset_after = validate_success(api.get_hardware(asset["id"], MGR))
    assert asset_after["status"] == "ASSIGNED"
