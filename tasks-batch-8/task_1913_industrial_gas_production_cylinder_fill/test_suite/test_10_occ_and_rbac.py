"""Optimistic concurrency control and role-based access rules (PRD §2.1, §2.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_test_customer,
    create_test_plant,
    create_test_tank,
    get_customer,
    get_tank,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# --- Corner: complexity_layers / occ_tank_patch_fresh_then_stale ---

def test_tank_patch_fresh_version_succeeds(api):
    """PRD §2.7: "Updating a storage tank's configuration via
    `PATCH /api/tanks/{tankId}` requires a non-optional `expected_tank_version`
    carrying the caller's last observed `version` of the tank."
    PRD §3.1: "Updating a tank's `reorder_point_liters` is an OCC-protected
    configuration write (see §2.7) that recomputes `low_level_flag` and
    increments `version`."

    Design: Corner/complexity_layers/occ_tank_patch_fresh_then_stale
    """
    plant = create_test_plant(plant_name="P-CL1")
    tank = create_test_tank(plant["id"], reorder_point_liters=500)
    assert tank["version"] == 1

    patched = validate_success(
        api.patch_tank(tank["id"],
                       {"reorder_point_liters": 600, "expected_tank_version": 1},
                       PM),
        200,
    )
    assert patched["reorder_point_liters"] == 600
    assert patched["version"] == 2


def test_tank_patch_stale_version_rejected(api):
    """PRD §2.7: "If the tank's current `version` has advanced past the supplied
    value, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), because
    the caller's view of thresholds such as the reorder point is stale and the
    lost update is refused rather than silently overwriting another writer's
    configuration."

    Design: Corner/complexity_layers/occ_tank_patch_fresh_then_stale
    """
    plant = create_test_plant(plant_name="P-CL1B")
    tank = create_test_tank(plant["id"], reorder_point_liters=500)
    validate_success(
        api.patch_tank(tank["id"],
                       {"reorder_point_liters": 600, "expected_tank_version": 1},
                       PM),
        200,
    )
    res = api.patch_tank(
        tank["id"], {"reorder_point_liters": 700, "expected_tank_version": 1}, PM
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_tank(tank["id"])
    assert after["reorder_point_liters"] == 600, "the stale write is refused"
    assert after["version"] == 2


# --- Corner: complexity_layers / occ_customer_patch_fresh_then_stale ---

def test_customer_patch_fresh_version_succeeds(api):
    """PRD §2.7: "Updating a customer account's credit terms via
    `PATCH /api/customers/{customerId}` requires a non-optional
    `expected_customer_version` carrying the caller's last observed `version` of
    the account."
    PRD §3.5: "Credit terms may later be updated — optionally a new
    `credit_limit_cents`, `free_days`, or `billing_variant` — through the
    OCC-protected account write described in §2.7, which increments the account's
    `version`."

    Design: Corner/complexity_layers/occ_customer_patch_fresh_then_stale
    """
    customer = create_test_customer(account_name="C-CL2", credit_limit_cents=100000)
    assert customer["version"] == 1
    patched = validate_success(
        api.patch_customer(
            customer["id"],
            {"credit_limit_cents": 200000, "expected_customer_version": 1},
            BC,
        ),
        200,
    )
    assert patched["credit_limit_cents"] == 200000
    assert patched["version"] == 2


def test_customer_patch_stale_version_rejected(api):
    """PRD §2.7: "A mismatch with the account's current `version` is rejected
    with `ERR_STALE_VERSION` (HTTP 412), because the credit terms the caller
    observed no longer describe the account."

    Design: Corner/complexity_layers/occ_customer_patch_fresh_then_stale
    """
    customer = create_test_customer(account_name="C-CL2B", credit_limit_cents=100000)
    validate_success(
        api.patch_customer(
            customer["id"],
            {"credit_limit_cents": 200000, "expected_customer_version": 1},
            BC,
        ),
        200,
    )
    res = api.patch_customer(
        customer["id"],
        {"credit_limit_cents": 300000, "expected_customer_version": 1},
        BC,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_customer(customer["id"])
    assert after["credit_limit_cents"] == 200000
    assert after["version"] == 2


# --- Corner: rbac / billing_clerk_cannot_create_tank ---

def test_billing_clerk_cannot_create_tank(api):
    """PRD §2.1: "Each endpoint declares the roles permitted to call it; a caller
    whose role is not listed, or who violates a role-scoped restriction on an
    otherwise permitted endpoint, is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: POST `/api/tanks` — "Register a cryogenic storage tank; seeds an
    INITIAL_LOAD reading" — authorized role: PlantManager.

    Design: Corner/rbac/billing_clerk_cannot_create_tank
    """
    plant = create_test_plant(plant_name="P-RB1")
    res = api.create_tank(
        {
            "plant_id": plant["id"],
            "product_code": "O2",
            "capacity_liters": 10000,
            "initial_level_liters": 5000,
            "reorder_point_liters": 500,
        },
        BC,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)


# --- Corner: validations / auth_missing_header_rejected ---

def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request with either header missing, or with a role value
    outside this declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/auth_missing_header_rejected
    """
    res = api.list_plants(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_undeclared_role_rejected(api):
    """PRD §2.1: "The system recognizes exactly seven roles, spelled precisely as
    follows: `PlantManager`, `ProductionOperator`, `LabAnalyst`,
    `QualityManager`, `LogisticsCoordinator`, `BillingClerk`, and `Driver`. A
    request with either header missing, or with a role value outside this
    declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/auth_missing_header_rejected
    """
    res = api.list_plants(
        headers={"X-User-ID": "intruder-1", "X-User-Role": "SuperAdmin",
                 "Content-Type": "application/json"}
    )
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
