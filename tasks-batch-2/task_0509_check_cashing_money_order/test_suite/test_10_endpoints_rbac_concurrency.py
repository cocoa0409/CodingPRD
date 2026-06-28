"""Breadth tests on read endpoints, auth/RBAC, drawer-close OCC, version cascade,
and immediate consistency (PRD §2.1, §2.2, §2.4, §2.5, §2.10, §3.1, §3.5, §3.7)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    create_money_order_payload, create_check_cash_payload, create_cash_drawer_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    setup_returned_check, setup_risk_held_check, setup_reconciling_drawer,
    create_customer, open_drawer, reconcile_drawer, current_drawer_version,
    close_payload, return_payload,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


# ===== endpoints (reverse-reachability reads) =====

def test_list_transactions_filtered_by_customer(api):
    """PRD §3.4: "The creator supplies the acting `customer_id`".
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    A posting for a customer is returned when the transactions list is filtered by that
    customer_id.

    Design: Corner/endpoints/list_transactions_filtered_by_customer
    """
    cust, drawer = setup_verified_customer_and_drawer("C26", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "T"), TELLER), 201)
    res = api.list_transactions(TELLER, params={"customer_id": cust["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert data[0]["id"] == txn["id"]


def test_drawer_transactions_reverse_reachability(api):
    """PRD §2.5: "Several read endpoints expose a resource's children by walking a foreign
    key in reverse".
    PRD §3.3: "Transactions posted to a drawer can be listed back, optionally filtered by
    `lifecycle_state`."

    Design: Corner/endpoints/drawer_transactions_reverse_reachability
    """
    cust, drawer = setup_verified_customer_and_drawer("C27", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "U"), TELLER), 201)
    res = api.list_drawer_transactions(drawer["id"], MANAGER)
    data, meta = validate_paginated(res)
    assert txn["id"] in [t["id"] for t in data]


def test_returned_items_filtered_by_transaction(api):
    """PRD §3.9: "Returned items can be fetched individually and listed, optionally filtered
    by `transaction_id`, `customer_id`, or `status`."

    Design: Corner/endpoints/returned_items_filtered_by_transaction
    """
    cust, drawer, sched, txn, ri = setup_returned_check(
        store_code="C28", face_amount_cents=100000, teller_id="teller-1")
    res = api.list_returned_items(TELLER, params={"transaction_id": txn["id"]})
    data, meta = validate_paginated(res)
    assert ri["id"] in [r["id"] for r in data]


# ===== errors / auth =====

def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "Every request must carry two HTTP headers identifying the operator:
    `X-User-ID` ... and `X-User-Role` .... If either header is missing or invalid, the
    request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    res = api._request("GET", "/customers", headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_transaction_not_found_on_void(api):
    """PRD §2.5: "A reference to a resource that does not exist is rejected with
    `ERR_NOT_FOUND`. Existence is checked after authentication and authorization but before
    any state or business rule is evaluated."

    Design: Corner/errors/transaction_not_found_on_void
    """
    res = api.void_transaction("00000000-0000-0000-0000-000000000000", MANAGER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


# ===== rbac =====

def test_teller_cannot_open_drawer(api):
    """PRD §2.1: "When a request is authenticated but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.3: "Before any cash can move, a `StoreManager` opens a cash drawer for a branch
    and a business day".

    Opening a drawer is StoreManager-exclusive; a Teller attempt is forbidden.

    Design: Corner/rbac/teller_cannot_open_drawer
    """
    res = api.create_cash_drawer(
        create_cash_drawer_payload(store_code="C29", business_date="2026-05-01",
                                   opening_float_cents=500000), TELLER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_teller_cannot_run_compliance_screen(api):
    """PRD §2.1: "When a request is authenticated but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.1: "Clearing compliance is a `StoreManager`-only act."

    Running a compliance screen is StoreManager-exclusive; a Teller attempt is forbidden.

    Design: Corner/rbac/teller_cannot_run_compliance_screen
    """
    cust = create_customer(full_name="Screen Deny", id_type="STATE_ID",
                           id_number="SID-132", date_of_birth="1984-04-14")
    res = api.create_compliance_screen(
        {"customer_id": cust["id"], "ofac_list_hit": False, "kyc_documents_valid": True},
        TELLER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_teller_can_post_transaction_shared_op(api):
    """PRD §3.4: "A transaction is the unit of business activity, and any `Teller` or
    `StoreManager` may create one."

    Design: Corner/rbac/teller_can_post_transaction_shared_op
    """
    cust, drawer = setup_verified_customer_and_drawer("C30", opening_float_cents=1000000)
    res = api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "V"), TELLER)
    txn = validate_success(res, 201)
    assert txn["lifecycle_state"] == "POSTED"


def test_sod_distinct_manager_can_release(api):
    """PRD §3.7: "Both resolution paths enforce segregation of duties: the resolving
    manager's `X-User-ID` must differ from the creating Teller's, or the request is rejected
    with `ERR_SEGREGATION_OF_DUTIES`. **Releasing** a held check moves the check item
    `RISK_HELD → CLEARED`".

    Manager-9 (distinct from creating teller-1) releases a RISK_HELD check -> CLEARED, txn
    POSTED.

    Design: Corner/rbac/sod_distinct_manager_can_release
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="C31", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    released = validate_success(
        api.release_check_item(check["id"], make_store_manager_headers("manager-9")), 200)
    assert released["verification_state"] == "CLEARED"
    txn_after = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert txn_after["lifecycle_state"] == "POSTED"


# ===== cross-cutting complexity layers =====

def test_drawer_close_correct_version_succeeds(api):
    """PRD §2.10: "The close request must carry `expected_drawer_version`, a non-optional
    field whose value is the `version` of the `CashDrawer` the closing manager last observed
    when counting cash. If that value does not match the drawer's current `version` at the
    moment the close is processed, the request is rejected with `ERR_STALE_DRAWER_VERSION`".
    PRD §3.7: "If the variance is exactly 0 the drawer moves `RECONCILING → CLOSED` ...
    Either way the drawer's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/drawer_close_correct_version_succeeds
    """
    drawer, version = setup_reconciling_drawer(store_code="C32", opening_float_cents=400000)
    res = api.close_drawer(drawer["id"], close_payload(400000, version), MANAGER)
    closed = validate_success(res, 200)
    assert closed["status"] == "CLOSED"
    assert closed["variance_cents"] == 0
    assert closed["version"] == version + 1


def test_drawer_close_stale_version_rejected(api):
    """PRD §2.10: "If that value does not match the drawer's current `version` at the moment
    the close is processed, the request is rejected with `ERR_STALE_DRAWER_VERSION`
    (HTTP 412)."
    PRD §2.9: "Whenever a posting, void, or release cascade touches a drawer, its expected
    cash is recomputed from scratch and its `version` is bumped".

    A version captured at open is stale after begin-reconcile bumps the drawer; closing
    against it -> ERR_STALE_DRAWER_VERSION.

    Design: Corner/cross_cutting_complexity_layers/drawer_close_stale_version_rejected
    """
    drawer = open_drawer(store_code="C33", opening_float_cents=400000)
    stale_version = drawer["version"]
    reconcile_drawer(drawer["id"])
    res = api.close_drawer(drawer["id"], close_payload(400000, stale_version), MANAGER)
    validate_error(res, ApiErrorId.ERR_STALE_DRAWER_VERSION, expected_status=412)


def test_customer_version_increments_on_screen_cascade(api):
    """PRD §3.1: "The screen's `outcome` is computed deterministically and written back to
    the customer's `kyc_status` ... otherwise the outcome is `VERIFIED`."
    PRD §2.4: "Whenever the server mutates a resource — whether in direct response to a
    client request or as a downstream cascade from another operation — that resource's
    `updated_at` is refreshed and its `version` is incremented."

    A registered customer (version 1, PENDING) screened to VERIFIED -> version 2.

    Design: Corner/cross_cutting_complexity_layers/customer_version_increments_on_screen_cascade
    """
    cust = create_customer(full_name="Ver Bump", id_type="STATE_ID",
                           id_number="SID-135", date_of_birth="1985-05-05")
    assert cust["version"] == 1
    validate_success(api.create_compliance_screen(
        {"customer_id": cust["id"], "ofac_list_hit": False, "kyc_documents_valid": True},
        MANAGER), 201)
    after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert after["kyc_status"] == "VERIFIED"
    assert after["version"] == 2


# ===== consistency model =====

def test_immediate_visibility_of_post_cascade(api):
    """PRD §2.9: "Whenever a posting, void, or release cascade touches a drawer, its
    expected cash is recomputed from scratch".
    PRD §3.5: "Expected cash equals the opening float, minus the total of (face minus fee)
    across all posted check-cash transactions".

    Immediately after a CHECK_CASH face=100000 fee=1099, GET on the drawer shows expected
    1000000 - 98901 = 901099 in the same request cycle.

    Design: Corner/consistency_model/immediate_visibility_of_post_cascade
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="C34", opening_float_cents=1000000)
    validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    after = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert after["expected_cash_cents"] == 901099
