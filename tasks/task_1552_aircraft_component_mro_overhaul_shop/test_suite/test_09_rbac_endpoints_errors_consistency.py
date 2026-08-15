"""RBAC denials, response-envelope shapes, 404 sweep, version visibility,
and immediate consistency of the release response (queue B)."""
import pytest

from test_helpers import (
    ApiErrorId,
    INSPECTOR,
    NON_EXISTENT_UUID,
    PARTS_BUYER,
    SHOP_MANAGER,
    TECHNICIAN,
    api_client,
    approve_quote,
    create_customer,
    create_part,
    create_unit,
    create_work_order,
    customer_payload,
    get_work_order,
    make_customer_headers,
    make_inspector_headers,
    parse_instant,
    setup_work_order_test_passed,
    submit_quote,
    validate_error,
    validate_success,
    work_order_payload,
)


# ---------------------------------------------------------------------------
# Queue B — rbac
# ---------------------------------------------------------------------------

def test_technician_cannot_create_customer(api):
    """PRD §2.1: "Access to each operation is restricted by role per §4; an
    attempt to perform an action outside the caller's role is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." The §4 address map lists POST
    /mro/customers under ShopManager only.

    Design: Corner/rbac/technician_cannot_create_customer
    """
    res = api.create_customer(customer_payload(), TECHNICIAN)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_inspector_cannot_create_work_order(api):
    """PRD §2.1: "Access to each operation is restricted by role per §4; an
    attempt to perform an action outside the caller's role is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.9: "2. Role authorization for
    the endpoint (`ERR_FORBIDDEN_ROLE`). 3. Resource existence, paths
    validated left to right (§2.8)." — the role check fires before the
    nonexistent customer/unit ids are ever examined.

    Design: Corner/rbac/inspector_cannot_create_work_order
    """
    res = api.create_work_order(
        work_order_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                           work_scope="OVERHAUL"),
        INSPECTOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_customer_cannot_review_claim(api):
    """PRD §2.1: "Access to each operation is restricted by role per §4; an
    attempt to perform an action outside the caller's role is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.9: "2. Role authorization for
    the endpoint (`ERR_FORBIDDEN_ROLE`). 3. Resource existence, paths
    validated left to right (§2.8)." — warranty review is ShopManager-only,
    so a Customer caller is denied before the unknown claim id matters.

    Design: Corner/rbac/customer_cannot_review_claim
    """
    res = api.review_warranty_claim(
        NON_EXISTENT_UUID, {"decision": "ACCEPT"},
        make_customer_headers(NON_EXISTENT_UUID))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


# ---------------------------------------------------------------------------
# Queue B — endpoints (envelope shapes, version visibility)
# ---------------------------------------------------------------------------

def test_response_envelope_object_and_error_shapes(api):
    """PRD §2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources." and "The `api_request_id`
    is a server-generated unique identifier for the request that starts with
    `req_`." Error path: "All error API responses (4xx status codes) follow
    this standard envelope format" with `"response_type": "error",` and "The
    `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/endpoints/response_envelope_object_and_error_shapes
    """
    customer = create_customer()

    res = api.get_customer(customer["id"], SHOP_MANAGER)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["response_type"] == "object"
    assert body["data"]["id"] == customer["id"]

    res_err = api.get_work_order(NON_EXISTENT_UUID, SHOP_MANAGER)
    assert res_err.status_code == 404
    err_body = res_err.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value
    assert isinstance(err_body["data"]["message"], str)


def test_work_order_version_increments_visible_via_get(api):
    """PRD §2.4: "`version` (integer): a system-managed integer that
    increments by exactly 1 on every mutation of the resource." PRD §3.3: a
    successful quote "computes `promised_return_at` as `received_at` plus
    the customer's `contract_tat_hours`". PRD §2.5: "At server startup the
    logical clock is exactly `2026-08-01T00:00:00Z`"; PRD §3.2: induction
    "stamps `received_at` with the logical clock (this is the TAT start)".

    Design: Corner/endpoints/work_order_version_increments_visible_via_get
    """
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], owner_customer_id=customer["id"])

    created = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    assert created["version"] == 1

    torn_down = validate_success(
        api.teardown_complete(created["id"], TECHNICIAN), 200)
    assert torn_down["version"] == 2

    quoted = submit_quote(created["id"], scrap_option_ack=False)
    assert quoted["version"] == 3

    approved = approve_quote(created["id"], customer["id"], quoted["version"])
    assert approved["version"] == 4

    fetched = get_work_order(created["id"])
    assert fetched["version"] == 4
    assert fetched["status"] == "REPAIR_IN_PROGRESS"
    # Instant comparison: PRD pins the instant (clock default per §2.5) but not
    # the fractional-digit serialization of received_at / promised_return_at.
    assert parse_instant(fetched["received_at"]) == parse_instant("2026-08-01T00:00:00Z")
    # received 2026-08-01T00:00:00Z + 100h contract TAT = 2026-08-05T04:00:00Z.
    assert parse_instant(fetched["promised_return_at"]) == parse_instant("2026-08-05T04:00:00Z")


# ---------------------------------------------------------------------------
# Queue B — errors
# ---------------------------------------------------------------------------

def test_not_found_sweep_returns_404s(api):
    """PRD §2.8: "Each resource family has its own 404 code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`,
    `ERR_TEST_CELL_NOT_FOUND`, `ERR_EXCHANGE_NOT_FOUND`, and
    `ERR_LEASE_NOT_FOUND`." and "References with no family-specific code
    fall back to the generic `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/not_found_sweep_returns_404s
    """
    cases = [
        (api.get_customer(NON_EXISTENT_UUID, SHOP_MANAGER),
         ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value),
        (api.get_part(NON_EXISTENT_UUID, SHOP_MANAGER),
         ApiErrorId.ERR_PART_NOT_FOUND.value),
        (api.get_unit(NON_EXISTENT_UUID, SHOP_MANAGER),
         ApiErrorId.ERR_UNIT_NOT_FOUND.value),
        (api.source_approval(NON_EXISTENT_UUID, {"approved": True}, PARTS_BUYER),
         ApiErrorId.ERR_REQUISITION_NOT_FOUND.value),
        (api.get_test_cell(NON_EXISTENT_UUID, SHOP_MANAGER),
         ApiErrorId.ERR_TEST_CELL_NOT_FOUND.value),
        (api.get_exchange_agreement(NON_EXISTENT_UUID, SHOP_MANAGER),
         ApiErrorId.ERR_EXCHANGE_NOT_FOUND.value),
        (api.get_lease_agreement(NON_EXISTENT_UUID, SHOP_MANAGER),
         ApiErrorId.ERR_LEASE_NOT_FOUND.value),
        # Invoices have no family-specific code -> generic ERR_NOT_FOUND.
        (api.get_invoice(NON_EXISTENT_UUID, SHOP_MANAGER),
         ApiErrorId.ERR_NOT_FOUND.value),
    ]
    for res, expected_error_id in cases:
        validate_error(res, expected_error_id, expected_status=404)


# ---------------------------------------------------------------------------
# Queue B — consistency
# ---------------------------------------------------------------------------

def test_immediate_consistency_release_response(api):
    """PRD §3.5: on release the system "stamps `released_at` with the clock
    (the TAT stop) and captures `inspector_user_id` from the caller" ...
    "leaving the work order `RELEASED`". PRD §2.2: "Unless otherwise noted,
    operations that create or modify a resource will return the created or
    updated resource object in the data field." — the mutation response
    already carries the post-release state, and the follow-up read agrees.

    Design: Corner/consistency/immediate_consistency_release_response
    """
    # Test clock is 2026-08-02T02:00:00Z inside the booked window.
    customer, part, unit, wo, cell, booking = setup_work_order_test_passed()

    res = api.release_work_order(wo["id"], make_inspector_headers("insp-9"))
    released = validate_success(res, 200)
    assert released["status"] == "RELEASED"
    assert released["inspector_user_id"] == "insp-9"
    assert parse_instant(released["released_at"]) == parse_instant("2026-08-02T02:00:00Z")

    fetched = get_work_order(wo["id"])
    assert fetched["status"] == released["status"]
    assert fetched["released_at"] == released["released_at"]
    assert fetched["inspector_user_id"] == released["inspector_user_id"]
