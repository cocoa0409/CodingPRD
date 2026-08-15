"""Cross-cutting validation and security: auth headers, RBAC, OCC on accounts,
upfit rules, spec freeze, uniqueness (PRD §2.1, §2.7, §2.10, §3.2, §3.9)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, get_success_data,
    create_account, create_fleet_account, create_slot_pool, create_order,
    commit_order, create_shipped_order, receive_unit_from_order,
    create_ready_unit, create_part, build_user_headers,
)

MGR = TEST_USERS["sales_manager_headers"]
CONSULTANT = TEST_USERS["sales_consultant_headers"]
ADVISOR = TEST_USERS["service_advisor_headers"]
PARTS_REP = TEST_USERS["parts_counter_rep_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
OEM_ADJUDICATOR = TEST_USERS["oem_adjudicator_headers"]

STD_SPEC = dict(chassis_model="M2_106", engine_option="DD13", axle_config="A4X2")


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    not among the declared roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.10: "1. Header presence and declared role —
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400)." precedes "5. Existence
    of path and body identifiers".

    Design: Corner/validations/missing_auth_headers_rejected
    """
    # No X-User-ID / X-User-Role at all: auth beats the 404 the path yields.
    resp = api_client.get_unit(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)
    # Undeclared role string.
    resp = api_client.get_unit(NON_EXISTENT_UUID,
                               headers=build_user_headers("x", "NotARole"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


def test_role_denied_on_exclusive_endpoint(api):
    """PRD §2.1: "Once headers are well-formed, the role must be permitted on
    the target endpoint per the authorization table in §4; otherwise the
    request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /dealership/factory-orders is authorized for SalesConsultant.

    Design: Corner/validations/role_denied_on_exclusive_endpoint
    """
    slot = create_slot_pool(build_month="2026-10", capacity=2)
    resp = api_client.create_factory_order(
        {"factory_build_slot_id": slot["id"], **STD_SPEC}, PARTS_REP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_each_exclusive_endpoint_rejects_foreign_roles(api):
    """PRD §2.1: "the role must be permitted on the target endpoint per the
    authorization table in §4; otherwise the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.10: "2. Role permitted on the endpoint — `ERR_INSUFFICIENT_PERMISSIONS`
    (403)" precedes "5. Existence of path and body identifiers".

    Design: Corner/rbac/each_exclusive_endpoint_rejects_foreign_roles
    """
    acct = create_fleet_account(credit_limit_cents=50000000, name="RbacCo")
    unit = create_ready_unit(vin="1FUJGBDV1CLW88335")
    # PATCH account is SalesManager-only.
    validate_error(api_client.patch_customer_account(
        acct["id"], {"fleet_tier": "GOLD",
                     "expected_customer_account_version": acct["version"]}, CONSULTANT),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    # Sell is SalesConsultant-only.
    validate_error(api_client.sell_unit(
        unit["id"], {"customer_account_id": acct["id"], "sale_price_cents": 12000000},
        CONTROLLER), ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    # Draft claim is WarrantyAdministrator-only; role check precedes the 404.
    validate_error(api_client.create_warranty_claim(
        {"repair_order_id": NON_EXISTENT_UUID, "claimed_labor_cents": 1,
         "claimed_parts_cents": 0}, OEM_ADJUDICATOR),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_occ_stale_version_rejected_on_account_patch(api):
    """PRD §2.7: "Updating an account — the SalesManager's patch of
    `fleet_tier`, `credit_limit_cents`, or `status` — requires the request to
    carry `expected_customer_account_version` holding the version of the
    `CustomerAccount` the client last observed. If the account's current
    `version` no longer matches ... the patch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_on_account_patch
    """
    acct = create_fleet_account(credit_limit_cents=500000, name="OccCo")
    v1 = acct["version"]
    data = validate_success(api_client.patch_customer_account(
        acct["id"], {"fleet_tier": "GOLD", "expected_customer_account_version": v1},
        MGR), 200)
    assert data["fleet_tier"] == "GOLD"
    assert data["version"] == v1 + 1
    # Replaying the now-stale version is rejected; nothing changes.
    validate_error(api_client.patch_customer_account(
        acct["id"], {"credit_limit_cents": 600000,
                     "expected_customer_account_version": v1}, MGR),
        ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_success_data(
        api_client.get_customer_account(acct["id"], MGR))["credit_limit_cents"] == 500000


def test_upfit_compatibility_and_dependency_rules(api):
    """PRD §3.2: "a `CRANE_PTO` requires the order's vocation group to be
    `SEVERE`; `REEFER_BOX` and `DUMP_BODY` are mutually exclusive on one order;
    and a `LIFTGATE` requires a `VAN_BODY` or `REEFER_BOX` on the same order.
    Violations are rejected with `ERR_UPFIT_INCOMPATIBLE` (422) for the first
    two rules and `ERR_UPFIT_DEPENDENCY_MISSING` (422) for the missing-body
    rule."

    Design: Corner/validations/upfit_compatibility_and_dependency_rules
    """
    slot_std = create_slot_pool(build_month="2026-10", vocation_group="STANDARD")
    slot_sev = create_slot_pool(build_month="2026-10", vocation_group="SEVERE")
    o_std = create_order(slot_std["id"], **STD_SPEC)
    o_sev = create_order(slot_sev["id"], chassis_model="SD_114", engine_option="DD15",
                         axle_config="A6X4")

    validate_error(api_client.add_upfit_line(
        o_std["id"], {"component_code": "CRANE_PTO", "price_cents": 950000}, CONSULTANT),
        ApiErrorId.ERR_UPFIT_INCOMPATIBLE)
    validate_error(api_client.add_upfit_line(
        o_sev["id"], {"component_code": "LIFTGATE", "price_cents": 120000}, CONSULTANT),
        ApiErrorId.ERR_UPFIT_DEPENDENCY_MISSING)
    validate_success(api_client.add_upfit_line(
        o_sev["id"], {"component_code": "VAN_BODY", "price_cents": 900000}, CONSULTANT), 201)
    data = validate_success(api_client.add_upfit_line(
        o_sev["id"], {"component_code": "LIFTGATE", "price_cents": 120000}, CONSULTANT), 201)
    assert len(data["upfit_lines"]) == 2


def test_spec_freeze_blocks_upfit_after_commit(api):
    """PRD §3.2: "Additional upfit lines may be appended only while the order
    remains `SLOT_HELD`; once committed the specification is frozen and a
    further append is rejected with `ERR_SPEC_FROZEN`."

    Design: Corner/validations/spec_freeze_blocks_upfit_after_commit
    """
    slot = create_slot_pool(build_month="2026-10", capacity=5)
    order = commit_order(create_order(slot["id"], **STD_SPEC)["id"])
    validate_error(api_client.add_upfit_line(
        order["id"], {"component_code": "VAN_BODY", "price_cents": 900000}, CONSULTANT),
        ApiErrorId.ERR_SPEC_FROZEN)
    assert get_success_data(
        api_client.get_factory_order(order["id"], MGR))["upfit_lines"] == []


def test_duplicate_vin_and_sku_rejected(api):
    """PRD §3.9: "creating a `Part` with a unique `sku` (duplicates rejected
    `ERR_DUPLICATE_SKU`)".
    PRD §3.2: "a `SHIPPED` order is received with a `vin` (rejected with
    `ERR_ORDER_STATE` if the order is not `SHIPPED`, and with
    `ERR_DUPLICATE_VIN` if any unit already carries that VIN)".

    Design: Corner/validations/duplicate_vin_and_sku_rejected
    """
    create_part(sku="DUP-1", list_price_cents=100, cost_cents=50)
    validate_error(api_client.create_part(
        {"sku": "DUP-1", "part_name": "P2", "list_price_cents": 200, "cost_cents": 60},
        PARTS_REP), ApiErrorId.ERR_DUPLICATE_SKU)

    slot = create_slot_pool(build_month="2026-08", capacity=5)
    o1 = create_shipped_order(slot_id=slot["id"], receive_date="2026-08-15T00:00:00Z")
    o2 = create_shipped_order(slot_id=slot["id"], receive_date="2026-08-16T00:00:00Z")
    receive_unit_from_order(o1["id"], vin="1FUJGBDV1CLW88333")
    validate_error(api_client.receive_factory_order(
        o2["id"], {"vin": "1FUJGBDV1CLW88333"}, MGR), ApiErrorId.ERR_DUPLICATE_VIN)
    assert get_success_data(
        api_client.get_factory_order(o2["id"], MGR))["status"] == "SHIPPED"
