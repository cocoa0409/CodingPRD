"""Breadth coverage: entity creation/defaults, not-found, required-field, duplicate,
soft-delete listing, payment immutability, immediate balance visibility, account-orders
listing, RBAC, and optimistic-concurrency (queue B corner instances).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_catalog, produce_roasted_lot, create_green_lot,
    setup_issued_invoice, place_order,
    create_payment_payload, order_line, create_fulfillment_payload,
    assert_no_version_fields, assert_account,
    make_buyer_headers, TEST_USERS, NON_EXISTENT_UUID,
)

ROASTER = TEST_USERS["roaster_headers"]
SALES = TEST_USERS["sales_headers"]


# ─── entities / create_account_returns_201_with_defaults ────────────────────

def test_create_account_defaults(api):
    """PRD §3.2: "On creation the account's `outstanding_balance_cents` is initialized to
    zero and its `status` is `ACTIVE`."

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    tier = get_success_data(api.create_price_tier(
        {"code": "C-T", "discount_bps": 500, "min_monthly_kg": 50, "freshness_max_days": 21},
        SALES))
    acct = validate_success(api.create_account(
        {"name": "New Cafe", "price_tier_id": tier["id"], "net_terms_days": 30,
         "credit_limit_cents": 500000}, SALES), 201)
    assert_account(acct)
    assert acct["status"] == "ACTIVE"
    assert acct["outstanding_balance_cents"] == 0
    # NOTE: PRD §2.4 states version "begins at its initial value on creation" but does not
    # name that value as 1, so the literal version==1 assertion is not PRD-derivable and is
    # intentionally omitted.


# ─── entities / get_account_not_found_returns_404 ───────────────────────────

def test_get_account_not_found(api):
    """PRD §2.4: "the server validates the identifiers strictly left to right and rejects the
    request with `ERR_NOT_FOUND` at the first identifier that does not resolve."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    res = api.get_account(NON_EXISTENT_UUID, SALES)
    validate_error(res, "ERR_NOT_FOUND")


# ─── entities / create_product_missing_required_field_returns_422 ───────────

def test_create_product_missing_required_field(api):
    """PRD §3.8: "Request well-formedness comes fourth: a missing or malformed body, a bad
    enum member, a non-positive quantity where a positive one is required, or a disallowed
    `net_terms_days`, `cadence_days`, or `roast_level` yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_product_missing_required_field_returns_422
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "RF", "roast_level": "MEDIUM", "expected_shrink_bps": 1500,
         "charge_temp_c": 200}, ROASTER))
    # Omit required base_price_cents_per_kg.
    res = api.create_product(
        {"sku": "SKU-RF", "name": "RF Prod", "roast_profile_id": profile["id"],
         "freshness_window_days": 14}, ROASTER)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entities / product_defaults_archived_false ─────────────────────────────

def test_product_default_archived_false(api):
    """PRD §3.1: "A newly created product has its `archived` flag false."

    Design: Corner/entities/product_defaults_archived_false
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "DF", "roast_level": "LIGHT", "expected_shrink_bps": 1300,
         "charge_temp_c": 195}, ROASTER))
    prod = validate_success(api.create_product(
        {"sku": "SKU-DF", "name": "DF Prod", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 2000, "freshness_window_days": 14}, ROASTER), 201)
    assert prod["archived"] is False


# ─── entities / duplicate_green_lot_ref_returns_409 ─────────────────────────

def test_duplicate_green_lot_ref(api):
    """PRD §3.3: "The `lot_ref` must be unique among green lots that are not yet depleted; a
    collision is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_green_lot_ref_returns_409
    """
    api.create_green_lot(
        {"origin": "Kenya", "lot_ref": "DUP-1", "received_kg": 50, "par_level_kg": 10}, ROASTER)
    res = api.create_green_lot(
        {"origin": "Kenya 2", "lot_ref": "DUP-1", "received_kg": 60, "par_level_kg": 10}, ROASTER)
    validate_error(res, "ERR_DUPLICATE")


# ─── entities / payment_immutable_no_version_field ──────────────────────────

def test_payment_append_only_no_version(api):
    """PRD §2.4: "A `Payment` is an append-only event: once created it is never modified, so a
    `Payment` carries only `id` and `created_at`. It has no `updated_at` and no `version`."

    Design: Corner/entities/payment_immutable_no_version_field
    """
    ctx = setup_issued_invoice(qty_kg=10, base_price_cents_per_kg=2000, discount_bps=0)
    inv = ctx["invoice"]
    pay = validate_success(api.create_payment(inv["id"], create_payment_payload(5000), SALES), 201)
    assert pay["status"] == "CLEARED"
    assert "id" in pay and "created_at" in pay
    assert_no_version_fields(pay)


# ─── consistency_model / immediate_visibility_of_computed_balance ───────────

def test_balance_immediately_reflects_issued_invoice(api):
    """PRD §2.9: "This posted balance is recomputed whenever an invoice is issued, a payment
    clears, an aging sweep runs, or an account is read."

    Design: Corner/consistency_model/immediate_visibility_of_computed_balance
    """
    ctx = setup_issued_invoice(qty_kg=10, base_price_cents_per_kg=2000, discount_bps=0)
    acct = ctx["account"]
    acct_read = validate_success(api.get_account(acct["id"], SALES), 200)
    assert acct_read["outstanding_balance_cents"] == 20000


# ─── endpoints / list_orders_for_account_paginated ──────────────────────────

def test_list_account_orders_paginated(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_orders_for_account_paginated
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    acct = cat["account"]
    prod = cat["product"]
    place_order(acct["id"], [order_line(prod["id"], 5)])
    place_order(acct["id"], [order_line(prod["id"], 3)])
    data, meta = validate_paginated(api.list_account_orders(acct["id"], SALES))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─── cross_cutting_complexity_layers / archived_product_excluded_from_default_list ─

def test_archived_product_excluded_from_default_list(api):
    """PRD §3.1: "Archiving a product sets its `archived` flag true so that it can no longer
    be added to new order lines; this is a modification of the existing product. Products can
    be listed filtered by `roast_profile_id` or by `archived`, and the default product
    listing excludes archived products."

    Design: Corner/cross_cutting_complexity_layers/archived_product_excluded_from_default_list
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "SDX", "roast_level": "MEDIUM", "expected_shrink_bps": 1500,
         "charge_temp_c": 205}, ROASTER))
    prod = get_success_data(api.create_product(
        {"sku": "SKU-SDX", "name": "SDX", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 2000, "freshness_window_days": 60}, ROASTER))
    archived = validate_success(api.archive_product(prod["id"], ROASTER), 200)
    assert archived["archived"] is True
    default_data, _ = validate_paginated(api.list_products(SALES))
    assert prod["id"] not in [p["id"] for p in default_data], \
        "archived product must be excluded from the default product list"
    incl_data, _ = validate_paginated(api.list_products(SALES, params={"archived": "true"}))
    assert prod["id"] in [p["id"] for p in incl_data], \
        "archived=true must include the archived product"


# ─── rbac / roasterstaff_cannot_create_account ──────────────────────────────

def test_roaster_cannot_create_account(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "`SalesRep` operate the commercial side: they manage price tiers and accounts".

    Design: Corner/rbac/roasterstaff_cannot_create_account
    """
    tier = get_success_data(api.create_price_tier(
        {"code": "RB0", "discount_bps": 0, "min_monthly_kg": 0, "freshness_max_days": 60}, SALES))
    res = api.create_account(
        {"name": "Blocked", "price_tier_id": tier["id"], "net_terms_days": 30,
         "credit_limit_cents": 1000}, ROASTER)
    validate_error(res, "ERR_FORBIDDEN")


# ─── rbac / salesrep_cannot_receive_green_lot ───────────────────────────────

def test_salesrep_cannot_receive_green_lot(api):
    """PRD §2.1: "`RoasterStaff` operate the production side: they receive green lots, author
    roast profiles, plan and run roast batches".

    Design: Corner/rbac/salesrep_cannot_receive_green_lot
    """
    res = api.create_green_lot(
        {"origin": "X", "lot_ref": "RB-X", "received_kg": 50, "par_level_kg": 5}, SALES)
    validate_error(res, "ERR_FORBIDDEN")


# ─── rbac / buyer_cannot_order_for_other_account ────────────────────────────

def test_buyer_cannot_order_for_other_account(api):
    """PRD §2.1: "A `WholesaleBuyer` whose `X-User-ID` does not match the targeted account's
    `id` (or the owning account of the targeted child resource) is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/buyer_cannot_order_for_other_account
    """
    tier = get_success_data(api.create_price_tier(
        {"code": "ISO0", "discount_bps": 0, "min_monthly_kg": 0, "freshness_max_days": 60}, SALES))
    acct_a = get_success_data(api.create_account(
        {"name": "Acct A", "price_tier_id": tier["id"], "net_terms_days": 30,
         "credit_limit_cents": 1_000_000}, SALES))
    acct_b = get_success_data(api.create_account(
        {"name": "Acct B", "price_tier_id": tier["id"], "net_terms_days": 30,
         "credit_limit_cents": 1_000_000}, SALES))
    profile = get_success_data(api.create_roast_profile(
        {"name": "ISO", "roast_level": "MEDIUM", "expected_shrink_bps": 1500,
         "charge_temp_c": 205}, ROASTER))
    prod = get_success_data(api.create_product(
        {"sku": "SKU-ISO", "name": "ISO", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 2000, "freshness_window_days": 60}, ROASTER))
    # Buyer of A (X-User-ID == acct_a.id) attempts to order for account B.
    res = api.create_order(
        acct_b["id"], {"lines": [order_line(prod["id"], 5)]}, make_buyer_headers(acct_a["id"]))
    validate_error(res, "ERR_FORBIDDEN")


# ─── rbac / missing_auth_headers_unauthenticated ────────────────────────────

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a recognized
    role, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.get_account(NON_EXISTENT_UUID, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── cross_cutting_complexity_layers / occ_stale_roasted_lot_reserve ────────

def test_occ_stale_roasted_lot_reserve_rejected(api):
    """PRD §2.6: "If that value does not equal the roasted lot's current `version` — because
    a prior reservation has already consumed available kilograms and advanced the lot's
    version — the reservation is refused with `ERR_STALE_VERSION` (HTTP 412) rather than
    overbooking the lot against a stale view of its available kilograms."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_roasted_lot_reserve
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    acct = cat["account"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order_a = place_order(acct["id"], [order_line(prod["id"], 5)])
    order_b = place_order(acct["id"], [order_line(prod["id"], 5)])
    # Client reads lot version once before the first reservation.
    lot_pre = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    stale_version = lot_pre["version"]
    # First reservation advances the lot version.
    api.create_fulfillment(
        order_a["id"],
        create_fulfillment_payload(prod["id"], lot["id"], 5, stale_version), SALES)
    # Second reservation carrying the now-stale pre-first version is rejected.
    res = api.create_fulfillment(
        order_b["id"],
        create_fulfillment_payload(prod["id"], lot["id"], 5, stale_version), SALES)
    validate_error(res, "ERR_STALE_VERSION")


# ─── cross_cutting_complexity_layers / occ_correct_green_lot_version_succeeds ─

def test_occ_correct_green_lot_version_succeeds(api):
    """PRD §2.6: "The batch-creation request must carry `expected_green_lot_version` holding
    the `version` of the target `GreenLot` that the client last observed."
    PRD §3.3: "Planning a batch reserves `planned_green_kg` on the green lot ... and recomputes
    the green lot's `reserved_kg`, `available_kg`, and `reorder_status`, then increments the
    green lot's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_green_lot_version_succeeds
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "OCG", "roast_level": "MEDIUM", "expected_shrink_bps": 1500,
         "charge_temp_c": 205}, ROASTER))
    prod = get_success_data(api.create_product(
        {"sku": "SKU-OCG", "name": "OCG", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 2000, "freshness_window_days": 60}, ROASTER))
    gl = get_success_data(api.create_green_lot(
        {"origin": "Vietnam", "lot_ref": "OCG-GL", "received_kg": 60, "par_level_kg": 5},
        ROASTER))
    before = gl["version"]
    batch = validate_success(api.create_roast_batch(
        {"green_lot_id": gl["id"], "product_id": prod["id"], "planned_green_kg": 20,
         "expected_green_lot_version": before}, ROASTER), 201)
    assert batch["status"] == "PLANNED"
    gl_after = validate_success(api.get_green_lot(gl["id"], ROASTER), 200)
    assert gl_after["version"] > before, \
        "planning a batch must increment the green lot's version"
    assert gl_after["reserved_kg"] == 20.000
    # NOTE: PRD §2.4 does not pin the initial version value, so the literal version 1->2
    # assertion is omitted; the increment (after > before) is what PRD §3.3 uniquely derives.
