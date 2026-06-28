"""Validation precedence pairs, hardiness gate, RBAC, and auth header.

Difficulty: charge_account_state_beats_fiscal, add_line_referential_beats_safety.
Corner: hardiness_mismatch_blocks_line_without_ack, hardiness_mismatch_allowed_with_ack,
salesclerk_cannot_allocate, inventory_manager_cannot_create_account,
missing_user_context_header_rejected.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, build_user_headers,
    validate_success, validate_error,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Difficulty: charge_account_state_beats_fiscal
# ---------------------------------------------------------------------------
def test_charge_account_draft_over_limit_reports_state_error(api):
    """PRD §3.6: "This is permitted only when the order's fulfillment status is
    `CONFIRMED` or `ALLOCATED` (otherwise `ERR_ORDER_NOT_CONFIRMED`)".
    PRD §2.10: "the server evaluate state preconditions, cross-entity state checks,
    domain safety gates, capacity and feasibility checks, fiscal checks, and finally
    the optimistic-concurrency version check."

    Design: Difficulty/priority_pair_validation_conflict/charge_account_state_beats_fiscal
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], account_type="LANDSCAPER_B2B",
                               display_name="Acme Land", credit_limit_cents=100)
    product = X.create_product(nursery["id"], sku="DG-5", name="Mulch Bag", unit_price_cents=5000)
    order = X.create_order(account["id"])  # left in DRAFT (never confirmed)
    X.add_line(order["id"], product["id"], qty=1)  # net would be 5000, over limit 100
    resp = api.charge_account(order["id"], F.version_payload(order["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CONFIRMED.value)


def test_charge_account_confirmed_over_limit_reports_fiscal_error(api):
    """PRD §3.6: "the account's current outstanding balance plus this order's net
    total would not exceed the account's credit limit (otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/charge_account_state_beats_fiscal
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], account_type="LANDSCAPER_B2B",
                               display_name="Acme Land", credit_limit_cents=100)
    product = X.create_product(nursery["id"], sku="DG-5b", name="Mulch Bag", unit_price_cents=5000)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=1)
    c = X.confirm(order["id"], order["version"])  # state now satisfied
    resp = api.charge_account(order["id"], F.version_payload(c["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Difficulty: add_line_referential_beats_safety
# ---------------------------------------------------------------------------
def test_add_line_bogus_product_reports_referential_error(api):
    """PRD §2.8: "A body-referenced product that does not resolve within the nursery
    yields `ERR_PRODUCT_NOT_FOUND`".
    PRD §2.10: "afterward verifies that body-referenced foreign keys exist within the
    nursery. Field-shape validation follows ... Only once a request is well-formed
    and its references are sound does the server evaluate state preconditions,
    cross-entity state checks, domain safety gates".

    Design: Difficulty/priority_pair_validation_conflict/add_line_referential_beats_safety
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], display_name="Walk-in", ship_to_hardiness_zone=12)
    order = X.create_order(account["id"])
    resp = api.add_line(order["id"],
                        F.add_line_payload(NON_EXISTENT, qty=1, acknowledge_hardiness_risk=False), CLERK)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_add_line_real_out_of_zone_product_reports_safety_error(api):
    """PRD §3.3: "When the line's product is a `LIVE_PLANT` and the account's
    `ship_to_hardiness_zone` falls outside the product's tolerated band — that is,
    below `hardiness_min_zone` or above `hardiness_max_zone` — the line is rejected
    with `ERR_HARDINESS_ZONE_MISMATCH` unless the request explicitly carries
    `acknowledge_hardiness_risk` set to true."

    Design: Difficulty/priority_pair_validation_conflict/add_line_referential_beats_safety
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], display_name="Cold Customer", ship_to_hardiness_zone=10)
    product = X.create_live_plant(nursery["id"], sku="PL-H", name="Tulip",
                                  hardiness_min_zone=3, hardiness_max_zone=7,
                                  unit_price_cents=500, warranty_days=30, warranty_pct=50)
    order = X.create_order(account["id"])
    resp = api.add_line(order["id"], F.add_line_payload(product["id"], qty=1), CLERK)
    validate_error(resp, ApiErrorId.ERR_HARDINESS_ZONE_MISMATCH.value)


# ---------------------------------------------------------------------------
# Corner: hardiness gate
# ---------------------------------------------------------------------------
def test_hardiness_mismatch_blocks_line_without_ack(api):
    """PRD §3.3: "the line is rejected with `ERR_HARDINESS_ZONE_MISMATCH` unless the
    request explicitly carries `acknowledge_hardiness_risk` set to true."

    Design: Corner/validations/hardiness_mismatch_blocks_line_without_ack
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], display_name="Cold Customer", ship_to_hardiness_zone=10)
    product = X.create_live_plant(nursery["id"], sku="PL-H", name="Tulip",
                                  hardiness_min_zone=3, hardiness_max_zone=7,
                                  unit_price_cents=500, warranty_days=30, warranty_pct=50)
    order = X.create_order(account["id"])
    resp = api.add_line(order["id"], F.add_line_payload(product["id"], qty=1), CLERK)
    validate_error(resp, ApiErrorId.ERR_HARDINESS_ZONE_MISMATCH.value)


def test_hardiness_mismatch_allowed_with_ack(api):
    """PRD §3.3: "Supplying `acknowledge_hardiness_risk` as true records the buyer's
    informed acceptance and lets the line through despite the mismatch".

    Design: Corner/validations/hardiness_mismatch_allowed_with_ack
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], display_name="Cold Customer", ship_to_hardiness_zone=10)
    product = X.create_live_plant(nursery["id"], sku="PL-H2", name="Tulip2",
                                  hardiness_min_zone=3, hardiness_max_zone=7,
                                  unit_price_cents=500, warranty_days=30, warranty_pct=50)
    order = X.create_order(account["id"])
    resp = api.add_line(order["id"],
                        F.add_line_payload(product["id"], qty=1, acknowledge_hardiness_risk=True), CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: RBAC
# ---------------------------------------------------------------------------
def test_salesclerk_cannot_allocate(api):
    """PRD §2.1: "When an authenticated operator attempts an operation their role is
    not permitted to perform, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/salesclerk_cannot_allocate
    """
    ctx = X.setup_confirmed_order(unit_price_cents=400, qty=2)
    resp = api.allocate_order(ctx["order"]["id"], F.version_payload(ctx["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_inventory_manager_cannot_create_account(api):
    """PRD §2.1: "When an authenticated operator attempts an operation their role is
    not permitted to perform, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/inventory_manager_cannot_create_account
    """
    nursery = X.create_nursery()
    resp = api.create_account(
        nursery["id"],
        F.create_account_payload(account_type="RETAIL", display_name="X", ship_to_hardiness_zone=6),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a header the server
    cannot validate, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    nursery = X.create_nursery()
    bad_headers = build_user_headers("ghost-1", "Anonymous")  # unrecognized role
    resp = api.get_nursery(nursery["id"], bad_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
