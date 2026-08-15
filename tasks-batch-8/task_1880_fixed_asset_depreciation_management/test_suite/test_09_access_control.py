"""RBAC, authentication, segregation of duties, and validation-order claims."""
from test_helpers import (
    ACCT,
    CLERK,
    CTRL,
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    TAX,
    ApiErrorId,
    create_class,
    create_disposal_request,
    create_in_service_asset,
    make_controller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting operator, and `X-User-Role`, identifying the role under which the
    operator acts. A request missing either header, or presenting a role outside
    the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    resp = api.get_fixed_asset(NON_EXISTENT_UUID, headers=NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_clerk_create_project_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`InventoryClerk` — performs physical inventory. Creates inventory
    runs, records count lines, and drives recount cycles."

    Design: Corner/validations/clerk_create_project_forbidden
    """
    cls = create_class()
    resp = api.create_capital_project(
        {"project_code": "PROJ-F", "name": "Forbidden",
         "asset_class_id": cls["id"]},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    rows, meta = validate_paginated(api.list_capital_projects(CLERK))
    assert meta["total_count"] == 0 and rows == [], "no project persisted"


def test_sod_self_approve_disposal_rejected(api):
    """PRD §2.9: "**Disposal approval** — the `Controller` approving a disposal
    must present an `X-User-ID` different from the disposal's recorded
    `requested_by_user_id`."
    PRD §2.9: "A violation of any of these three rules is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/sod_self_approve_disposal_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-040", description="SoD asset",
        acquisition_cost_cents=500000,
    )
    disposal = create_disposal_request(
        asset["id"], disposal_type="SALE", proceeds_cents=400000,
        effective_date="2026-03-01",
    )
    assert disposal["requested_by_user_id"] == "u_acct_1"

    # A Controller wearing the requester's X-User-ID cannot approve it.
    resp = api.approve_disposal(
        disposal["id"], make_controller_headers("u_acct_1")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    after = validate_success(api.get_disposal(disposal["id"], ACCT), 200)
    assert after["status"] == "REQUESTED"

    # The same call under a different Controller id succeeds.
    approved = validate_success(
        api.approve_disposal(disposal["id"], make_controller_headers("u_ctrl_1")),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "u_ctrl_1"


def test_authorization_precedes_existence(api):
    """PRD §2.10: "When multiple validation rules could reject the same request,
    the server evaluates them in a fixed priority order so the returned error is
    deterministic."
    PRD §2.10: "**(2) authorization and segregation of duties** — role permission
    for the endpoint (`ERR_FORBIDDEN`) and the SoD comparisons
    (`ERR_SEGREGATION_OF_DUTIES`); **(3) existence** — every path id and every
    body foreign-key reference must resolve (`ERR_NOT_FOUND`, or
    `ERR_ASSET_NOT_IN_SCOPE` for a count line whose asset was not seeded into the
    run)"

    Design: Corner/validations/authorization_precedes_existence
    """
    payload = {"asset_tag": "A-041", "description": "ghost"}
    forbidden = api.capitalize_project(NON_EXISTENT_UUID, payload, ACCT)
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN, 403)

    missing = api.capitalize_project(NON_EXISTENT_UUID, payload, CTRL)
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND, 404)


def test_role_exclusive_operation_denials(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "All four roles may call every read (GET) endpoint. Write endpoints
    are restricted as enumerated in §4."

    Design: Corner/rbac/role_exclusive_operation_denials
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-070", description="RBAC asset",
        acquisition_cost_cents=500000,
    )
    disposal = create_disposal_request(
        asset["id"], disposal_type="SALE", proceeds_cents=100000,
        effective_date="2026-03-01",
    )
    run = validate_success(
        api.create_depreciation_run({"period": "2026-01"}, ACCT), 201
    )

    clerk_project = api.create_capital_project(
        {"project_code": "PROJ-R", "name": "Nope", "asset_class_id": cls["id"]},
        CLERK,
    )
    validate_error(clerk_project, ApiErrorId.ERR_FORBIDDEN, 403)

    accountant_approve = api.approve_disposal(disposal["id"], ACCT)
    validate_error(accountant_approve, ApiErrorId.ERR_FORBIDDEN, 403)

    analyst_post = api.post_depreciation_run(run["id"], TAX)
    validate_error(analyst_post, ApiErrorId.ERR_FORBIDDEN, 403)

    controller_count_run = api.create_inventory_run(
        {"name": "Nope", "scope_type": "ALL"}, CTRL
    )
    validate_error(controller_count_run, ApiErrorId.ERR_FORBIDDEN, 403)

    d_after = validate_success(api.get_disposal(disposal["id"], ACCT), 200)
    assert d_after["status"] == "REQUESTED"
    r_after = validate_success(api.get_depreciation_run(run["id"], ACCT), 200)
    assert r_after["status"] == "OPEN"
    projects, pmeta = validate_paginated(api.list_capital_projects(ACCT))
    assert pmeta["total_count"] == 0 and projects == [], (
        "no project or inventory run persisted (no state changed)"
    )


def test_all_roles_can_read(api):
    """PRD §2.1: "All four roles may call every read (GET) endpoint."

    Design: Corner/rbac/all_roles_can_read
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-071", description="Read me",
        acquisition_cost_cents=500000,
    )

    bodies = []
    for headers in (ACCT, CTRL, CLERK, TAX):
        data = validate_success(api.get_fixed_asset(asset["id"], headers), 200)
        bodies.append(data)
    first = bodies[0]
    for body in bodies[1:]:
        assert body == first, "all four roles read the identical asset body"
