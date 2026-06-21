"""Role-based access control, optimistic-concurrency version checks, the
finish-supersede derived field, FK reverse-reachability, and immediate
consistency.

Breadth coverage of the Corner-design `rbac`, `cross_cutting_complexity_layers`,
`endpoints`, and `consistency_model` sections.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    make_unknown_role_headers,
    setup_base_shop,
    setup_quoted_project,
    setup_contracted_project,
    create_shop,
    create_material,
    create_customer,
    create_project,
    add_spec,
)

ADMIN = TEST_USERS["shop_admin_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]
INSTALLER = TEST_USERS["installer_headers"]


# ===========================================================================
# Corner / rbac
# ===========================================================================
def test_designer_cannot_issue_draw_forbidden(api):
    """PRD §2.1: "If the headers are valid but the named role is not authorized for
    the requested operation (see the endpoint table in §4 for each operation's
    permitted roles), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
    403)."

    Design: Corner/rbac/designer_cannot_issue_draw_forbidden
    """
    # Draw issue is a ShopManager/ShopAdmin operation; a Designer is forbidden.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]

    resp = api.issue_draw(shop_id, proj_id, dep_id, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_customer_cannot_pay_another_customers_draw_not_owner(api):
    """PRD §2.1: "A customer may only act on projects, draws, and change orders that
    belong to their own customer record"
    PRD §2.1: "When an entity-backed customer attempts to contract a project, pay a
    draw, or approve, reject, or request revision on a change order that they do
    not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_pay_another_customers_draw_not_owner
    """
    # Customer A's contracted project with an ISSUED deposit draw; Customer B tries to pay.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))

    customer_b = create_customer(shop_id)
    cust_b = make_customer_headers(customer_b["id"])
    resp = api.pay_draw(shop_id, proj_id, dep_id, cust_b)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_user_context_unknown_role_rejected(api):
    """PRD §2.1: "The system recognizes exactly five roles: `ShopAdmin`,
    `ShopManager`, `Designer`, `Customer`, and `Installer`. If either header is
    missing, or `X-User-Role` is not one of these five names, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    shop = create_shop()
    resp = api.get_shop(shop["id"], make_unknown_role_headers())
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)


def test_installer_cannot_create_change_order_forbidden(api):
    """PRD §2.1: "If the headers are valid but the named role is not authorized for
    the requested operation (see the endpoint table in §4 for each operation's
    permitted roles), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
    403)."

    Design: Corner/rbac/installer_cannot_create_change_order_forbidden
    """
    # Change-order create is a ShopManager/ShopAdmin operation; an Installer is forbidden.
    shop = create_shop()
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], title="P")

    resp = api.create_change_order(shop["id"], project["id"], {"description": "x", "spec_price_delta_cents": 1000}, INSTALLER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers
# ===========================================================================
def test_occ_stale_project_version_on_change_order_submit(api):
    """PRD §2.7: "If another change order has already been approved and has thereby
    advanced the project's `version` (and its contract total) since the submitter
    last read it, the submitter's view is stale and the recomputed delta would be
    keyed off an out-of-date base. The version check on `expected_project_version`
    converts this into a deterministic stale-version rejection carrying
    `ERR_STALE_VERSION` and HTTP 412"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_change_order_submit
    """
    # CO1 submitted+approved advances project.version; CO2 submit carries the stale version.
    ctx = setup_in_production_two_change_orders(api)
    shop_id, proj_id, co2_id, stale_version, cust = ctx

    resp = api.submit_change_order(shop_id, proj_id, co2_id, {"expected_project_version": stale_version}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def setup_in_production_two_change_orders(api):
    """Helper local to this file: drive a project to IN_PRODUCTION, create two
    DRAFT change orders, capture the project version, then submit+approve CO1
    (advancing the project version). Returns
    (shop_id, proj_id, co2_id, stale_version, customer_headers)."""
    from test_helpers import setup_in_production_project
    base = setup_in_production_project(
        specs=[{"quantity": 4}], finish_code="PAINT",
        build_start="2026-07-26T09:00:00Z", build_end="2026-07-26T12:00:00Z",
    )
    shop_id = base["shop"]["id"]
    proj_id = base["project"]["id"]
    cust = make_customer_headers(base["customer"]["id"])

    co1 = get_success_data(api.create_change_order(shop_id, proj_id, {"description": "co1", "spec_price_delta_cents": 50000}, MANAGER))
    co2 = get_success_data(api.create_change_order(shop_id, proj_id, {"description": "co2", "spec_price_delta_cents": 20000}, MANAGER))

    stale_version = get_success_data(api.get_project(shop_id, proj_id, MANAGER))["version"]
    get_success_data(api.submit_change_order(shop_id, proj_id, co1["id"], {"expected_project_version": stale_version}, MANAGER))
    pending_version = get_success_data(api.get_project(shop_id, proj_id, MANAGER))["version"]
    get_success_data(api.approve_change_order(shop_id, proj_id, co1["id"], {"expected_project_version": pending_version}, cust))
    return shop_id, proj_id, co2["id"], stale_version, cust


def test_project_version_increments_on_contract(api):
    """PRD §3.5: "it creates one `DEPOSIT` draw in `PENDING` status as the first hop
    of the contract-lock chain; and it increments the project's `version` by one,
    moving the project from `QUOTED` to `CONTRACTED`."

    Design: Corner/cross_cutting_complexity_layers/project_version_increments_on_contract
    """
    ctx = setup_quoted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    v0 = ctx["quote_version"]
    cust = make_customer_headers(ctx["customer"]["id"])

    contracted = validate_success(api.contract_project(shop_id, proj_id, {"expected_project_version": v0}, cust))
    assert contracted["version"] == v0 + 1, (
        f"project version after contract expected {v0 + 1} (quote version + 1), got {contracted['version']}"
    )


def test_occ_wrong_version_on_contract_rejected(api):
    """PRD §2.7: "Before the operation proceeds, the server compares
    `expected_project_version` against the project's current `version`. If they do
    not match — meaning another writer has advanced the project since the client
    read it — the operation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no
    state change or ledger movement occurs."

    Design: Corner/cross_cutting_complexity_layers/occ_wrong_version_on_contract_rejected
    """
    ctx = setup_quoted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])

    # Deliberately stale: one behind the actual version.
    resp = api.contract_project(shop_id, proj_id, {"expected_project_version": ctx["quote_version"] - 1}, cust)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_finish_selection_supersede_deactivates_prior(api):
    """PRD §3.5: "Exactly one finish selection per project is active at a time:
    selecting a new finish sets the previously active selection's `is_active` to
    false and the new one's `is_active` to true, and recomputes
    `estimate_total_cents`."

    Design: Corner/cross_cutting_complexity_layers/finish_selection_supersede_deactivates_prior
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], title="P")
    f1 = get_success_data(api.create_finish_selection(shop["id"], project["id"], {"finish_code": "STAIN"}, DESIGNER))

    f2 = validate_success(api.create_finish_selection(shop["id"], project["id"], {"finish_code": "PAINT"}, DESIGNER), 201)
    assert f2["is_active"] is True, f"newly selected finish expected is_active True, got {f2['is_active']}"

    f1_after = get_success_data(api.get_finish_selection(shop["id"], project["id"], f1["id"], DESIGNER))
    assert f1_after["is_active"] is False, f"superseded finish expected is_active False, got {f1_after['is_active']}"


# ===========================================================================
# Corner / endpoints
# ===========================================================================
def test_fk_reverse_specs_by_material_filtered_list(api):
    """PRD §2.5: "the API also exposes flat single-resource reads ... and flat
    foreign-key-filtered list reads for each entity, so that every entity is
    reachable both through its ownership tree and by reverse lookup from its
    foreign keys."

    Design: Corner/endpoints/fk_reverse_specs_by_material_filtered_list
    """
    shop, material, customer = setup_base_shop()
    project = create_project(shop["id"], customer["id"], title="P")
    add_spec(shop["id"], project["id"], material["id"], label="B1", width_mm=600, height_mm=720, depth_mm=560, quantity=1, base_unit_price_cents=100000)
    add_spec(shop["id"], project["id"], material["id"], label="B2", width_mm=700, height_mm=720, depth_mm=560, quantity=1, base_unit_price_cents=110000)

    resp = api.list_specs_by_material(shop["id"], project["id"], DESIGNER, params={"material_id": material["id"]})
    data = resp.json()["data"]
    assert len(data) == 2, f"specs-by-material expected 2 specs of the material, got {len(data)}"
    assert all(s["material_id"] == material["id"] for s in data), (
        "every returned spec must carry the filtered material_id"
    )


# ===========================================================================
# Corner / consistency_model
# ===========================================================================
def test_contract_lock_changes_visible_in_same_response(api):
    """PRD §3.5: "On success it performs a cascade: it sets `lock_state` to
    `LOCKED` on every cabinet spec; it computes `contract_total_cents` using the
    final variant of the contract-total calculation, including the rush surcharge
    when `is_rush` is true; it computes `deposit_required_cents` as the contract
    total multiplied by the shop's `deposit_pct_bps`, divided by 10000 and rounded
    half up"

    Design: Corner/consistency_model/contract_lock_changes_visible_in_same_response
    """
    # tax0 STAIN qty2 -> contract_total 291600, deposit 87480.
    ctx = setup_quoted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])

    contracted = validate_success(
        api.contract_project(shop_id, proj_id, {"expected_project_version": ctx["quote_version"]}, cust)
    )
    assert contracted["status"] == "CONTRACTED", f"contract response status expected CONTRACTED, got {contracted['status']}"
    assert contracted["contract_total_cents"] == 291600, (
        f"contract_total_cents expected 291600 in the same response, got {contracted['contract_total_cents']}"
    )
    assert contracted["deposit_required_cents"] == 87480, (
        f"deposit_required_cents expected 87480 in the same response, got {contracted['deposit_required_cents']}"
    )
