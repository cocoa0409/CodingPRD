"""Account creation, retrieval, listing, lifecycle, and role-based access control.

Translates queue B (Corner) instances from the `entities`, `state_machines`, and
`rbac` sections that concern the Account aggregate.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_customer_headers, NON_EXISTENT_UUID,
    assert_account, assert_tank,
    create_account_payload, create_tank_payload, create_order_payload,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]


# ---------------------------------------------------------------------------
# entities section
# ---------------------------------------------------------------------------
def test_create_account_returns_201_with_system_fields(api):
    """PRD §3.1: "On creation the account's `service_status` is `ACTIVE`, its `credit_balance_cents` ledger starts at 0, its `active_price_plan_id` is null until a plan is activated, and its `version` is 1."

    Design: Corner/entities/create_account_returns_201_with_system_fields
    """
    resp = api.create_account(
        create_account_payload(customer_name="New Nora", region_code="NE_01",
                               fuel_type="HEATING_OIL"), AM)
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["service_status"] == "ACTIVE"
    assert data["credit_balance_cents"] == 0
    assert data["version"] == 1
    assert data["active_price_plan_id"] is None


def test_get_account_returns_stored_data(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of resource objects."

    Design: Corner/entities/get_account_returns_stored_data
    """
    created = fx.create_account(region_code="NE_02", fuel_type="PROPANE",
                                customer_name="Read Ray")
    resp = api.get_account(created["id"], DISP)
    data = validate_success(resp, expected_status=200)
    assert data["id"] == created["id"]
    assert data["region_code"] == "NE_02"


def test_list_accounts_paginated_with_total_count(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_accounts_paginated_with_total_count
    """
    fx.create_account(customer_name="A One")
    fx.create_account(customer_name="A Two")
    data, meta = validate_paginated(api.list_accounts(DISP))
    assert isinstance(data, list)
    assert meta["total_count"] >= 2


def test_get_account_not_found(api):
    """PRD §2.6: "the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined and before any business rule is evaluated."

    Design: Corner/entities/get_account_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, DISP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_account_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "Body well-formedness** — on every write, required fields must be present, enums must hold legal values, and quantities that must be positive must be positive, else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_account_missing_required_field_returns_invalid_request
    """
    resp = api.create_account({"customer_name": "No Region", "fuel_type": "PROPANE"}, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_account_invalid_fuel_enum_rejected(api):
    """PRD §3.1: "the `fuel_type`, which is either `PROPANE` or `HEATING_OIL`."
    PRD §2.8: "enums must hold legal values ... else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_tank_invalid_fuel_enum_rejected
    """
    resp = api.create_account(
        {"customer_name": "Bad Fuel", "region_code": "NE_01", "fuel_type": "COAL"}, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_tank_defaults_applied_when_omitted(api):
    """PRD §3.3: "Optional inputs at creation are `reorder_threshold_pct` (the fill fraction, as a whole percent from 1 to 99, at or below which an auto-reorder fires; default 30), `delivery_mode` (`WILL_CALL` or `AUTOMATIC`, default `WILL_CALL`), `monitor_installed` (whether a telemetry monitor is fitted, default false), and an initial `current_gallons` level (default 0)."

    Design: Corner/entities/tank_defaults_applied_when_omitted
    """
    account = fx.create_account(customer_name="Def Dee")
    resp = api.create_tank(account["id"],
                           {"capacity_gallons": 500, "k_factor": 1500}, AM)
    data = validate_success(resp, expected_status=201)
    assert data["reorder_threshold_pct"] == 30
    assert data["delivery_mode"] == "WILL_CALL"
    assert data["monitor_installed"] is False


def test_system_fields_ignored_on_input(api):
    """PRD §3.1: "On creation the account's `service_status` is `ACTIVE`, its `credit_balance_cents` ledger starts at 0"

    Design: Corner/entities/system_fields_ignored_on_input
    """
    resp = api.create_account(
        {"customer_name": "Sneaky Sam", "region_code": "NE_01", "fuel_type": "PROPANE",
         "service_status": "CLOSED", "credit_balance_cents": 99999}, AM)
    data = validate_success(resp, expected_status=201)
    assert data["service_status"] == "ACTIVE"
    assert data["credit_balance_cents"] == 0


def test_monitor_reading_immutable_no_version_field(api):
    """PRD §2.4: "A `TankMonitorReading` and a `DegreeDayReading` are immutable observations: each carries only an `id` and a `created_at`, and neither has an `updated_at` nor a `version`."

    Design: Corner/entities/monitor_reading_immutable_no_version_field
    """
    account = fx.create_account(customer_name="Imm Ida")
    tank = fx.create_tank(account["id"], current_gallons=100)
    resp = api.create_reading(tank["id"],
                              {"reading_gallons": 200, "read_at": "2026-01-01T00:00:00Z"},
                              DRIVER)
    data = validate_success(resp, expected_status=201)
    assert "id" in data and data["id"]
    assert "version" not in data, "immutable reading must not carry version"
    assert "updated_at" not in data, "immutable reading must not carry updated_at"


def test_tank_requires_existing_account_parent(api):
    """PRD §2.6: "The system validates the identifiers in a path strictly left to right, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND"

    Design: Corner/entities/tank_requires_existing_account_parent
    """
    resp = api.create_tank(NON_EXISTENT_UUID,
                           {"capacity_gallons": 500, "k_factor": 1500}, AM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_tank_account_fk_reverse_reachable(api):
    """PRD §3.3: "Tanks can be read individually or listed; the list filters by `account_id`, by `service_status`, and by `reorder_status`."

    Design: Corner/entities/tank_account_fk_reverse_reachable
    """
    account = fx.create_account(customer_name="FK Fred")
    fx.create_tank(account["id"], capacity_gallons=500, k_factor=1500)
    fx.create_tank(account["id"], capacity_gallons=300, k_factor=1200)
    data, meta = validate_paginated(api.list_tanks(DISP, params={"account_id": account["id"]}))
    assert meta["total_count"] == 2
    for t in data:
        assert t["account_id"] == account["id"]


# ---------------------------------------------------------------------------
# state_machines section (Account)
# ---------------------------------------------------------------------------
def test_account_starts_active(api):
    """PRD §3.1: "On creation the account's `service_status` is `ACTIVE"

    Design: Corner/state_machines/account_starts_active
    """
    resp = api.create_account(create_account_payload(customer_name="Init Ivy"), AM)
    data = validate_success(resp, expected_status=201)
    assert data["service_status"] == "ACTIVE"


def test_suspend_then_reactivate_account(api):
    """PRD §3.1: "From `ACTIVE` an account manager may suspend it, transitioning `ACTIVE → SUSPENDED`; this is permitted only when the account is currently `ACTIVE`, otherwise `ERR_INVALID_STATE`, and it increments the account's `version` by one."
    PRD §3.1: "A `SUSPENDED` account may be reactivated, `SUSPENDED → ACTIVE`, permitted only from `SUSPENDED` (else `ERR_INVALID_STATE`) and again incrementing `version`."

    Design: Corner/state_machines/suspend_then_reactivate_account
    """
    account = fx.create_account(customer_name="Susp Sue")
    s1 = validate_success(api.suspend_account(account["id"], AM))
    assert s1["service_status"] == "SUSPENDED"
    s2 = validate_success(api.reactivate_account(account["id"], AM))
    assert s2["service_status"] == "ACTIVE"


def test_reactivate_active_account_invalid_state(api):
    """PRD §3.1: "A `SUSPENDED` account may be reactivated, `SUSPENDED → ACTIVE`, permitted only from `SUSPENDED` (else `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/reactivate_active_account_invalid_state
    """
    account = fx.create_account(customer_name="Active Al")
    resp = api.reactivate_account(account["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_closed_account_is_terminal(api):
    """PRD §3.1: "From `ACTIVE` an account manager may suspend it, transitioning `ACTIVE → SUSPENDED`; this is permitted only when the account is currently `ACTIVE`, otherwise `ERR_INVALID_STATE"

    Design: Corner/state_machines/closed_account_is_terminal
    """
    account = fx.create_account(customer_name="Closed Cleo")
    closed = validate_success(api.close_account(account["id"], AM))
    assert closed["service_status"] == "CLOSED"
    resp = api.suspend_account(account["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_close_account_with_open_order_rejected(api):
    """PRD §3.1: "there must be no `DeliveryOrder` for the account sitting in `CREATED`, `SCHEDULED`, or `HOLD` (otherwise `ERR_ACCOUNT_HAS_OPEN_ORDERS`)"

    Design: Corner/state_machines/close_account_with_open_order_rejected
    """
    account = fx.create_account(customer_name="Open Olga")
    tank = fx.create_tank(account["id"], current_gallons=100)
    fx.create_will_call_order(account["id"], tank["id"], requested_gallons=100)
    resp = api.close_account(account["id"], AM)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_ORDERS.value)


# ---------------------------------------------------------------------------
# rbac section
# ---------------------------------------------------------------------------
def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api.create_account(create_account_payload(customer_name="Anon"), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_driver_cannot_create_account_forbidden(api):
    """PRD §2.1: "When a caller presents a well-formed role that is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/driver_cannot_create_account_forbidden
    """
    resp = api.create_account(create_account_payload(customer_name="Driver Tries"), DRIVER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_customer_cannot_act_on_other_account_not_owner(api):
    """PRD §2.1: "A customer acting on a resource that belongs to a different account is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_act_on_other_account_not_owner
    """
    acct_a = fx.create_account(customer_name="Owner A")
    acct_b = fx.create_account(customer_name="Owner B")
    tank_b = fx.create_tank(acct_b["id"], current_gallons=100)
    resp = api.create_order(acct_b["id"],
                            create_order_payload(tank_b["id"], requested_gallons=100),
                            make_customer_headers(acct_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_customer_creates_own_will_call_order_allowed(api):
    """PRD §3.6: "A will-call order is raised directly by a customer (on their own account) or a dispatcher ... such an order is born with `origin` of `WILL_CALL` and `status` of `CREATED`."

    Design: Corner/rbac/customer_creates_own_will_call_order_allowed
    """
    account = fx.create_account(customer_name="Self Sid")
    tank = fx.create_tank(account["id"], current_gallons=100)
    resp = api.create_order(account["id"],
                            create_order_payload(tank["id"], requested_gallons=150),
                            make_customer_headers(account["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "CREATED"
