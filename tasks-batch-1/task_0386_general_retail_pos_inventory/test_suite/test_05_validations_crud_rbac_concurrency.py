"""CRUD basics, validation-priority conflicts, invalid-state transitions, RBAC,
optimistic concurrency, reference resolution, and atomic settlement.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    build_user_headers,
    create_store, create_product, create_promotion, open_cash_session,
    create_loyalty_account, grant_points, create_sale, add_tender,
    get_sale, get_loyalty_account,
    create_inventory_item, create_inventory_item_with_stock,
    setup_store_product_stock, setup_transfer_pair,
    create_transfer,
)

SM = TEST_USERS["store_manager_headers"]
CA = TEST_USERS["cashier_headers"]
IC = TEST_USERS["inventory_clerk_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Entity CRUD corners
# ─────────────────────────────────────────────────────────────────────────────

def test_create_store_returns_locked_posture_version_1(api):
    """PRD §3.1: "A newly created store starts `LOCKED`: with no open drawer, no payment
    can yet be captured."
    PRD §2.4: "`version` is an integer that starts at 1 and increments by one on every
    mutation that changes the resource; it underpins the optimistic concurrency control
    described in §2.7."
    PRD §3.1: "The manager may also supply `loyalty_earn_rate_bps`, the points earned per
    currency unit of net merchandise expressed in basis points (a value of 100 earns one
    point per dollar of net), which defaults to 100 and may not be negative."

    Design: Corner/entities/create_store_returns_201_with_locked_posture_and_version_1
    """
    resp = api.create_store(
        {"name": "Flagship", "code": "FLAG1", "tax_rate_bps": 875}, SM)
    store = validate_success(resp, expected_status=201)
    assert store["posture"] == "LOCKED"
    assert store["version"] == 1
    assert store["tax_rate_bps"] == 875
    assert store["loyalty_earn_rate_bps"] == 100
    assert is_valid_uuid(store["id"])


def test_get_nonexistent_store_returns_not_found(api):
    """PRD §2.5: "For any path that names a resource by identifier, the system validates
    each identifier left-to-right and rejects the first one that does not resolve with
    `ERR_NOT_FOUND` (404) before any deeper work begins."

    Design: Corner/entities/get_store_nonexistent_returns_not_found
    """
    resp = api.get_store(NON_EXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_product_missing_sku_rejected(api):
    """PRD §3.1: "Either a `StoreManager` or an `InventoryClerk` catalogues a `Product`
    by supplying its `sku`, its `barcode`, a `name`, and a `list_price_cents` (the
    catalogue unit price in cents, which may not be negative)."
    PRD §3.13: "After those come body well-formedness — required fields present and
    well-typed, enums valid, quantities meeting their constraints (`ERR_INVALID_REQUEST`)
    — and then uniqueness collisions (`ERR_DUPLICATE_RESOURCE`)."

    Design: Corner/entities/create_product_missing_required_sku_returns_invalid_request
    """
    resp = api.create_product(
        {"barcode": "B-NOSKU", "name": "X", "list_price_cents": 100}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_product_applies_defaults(api):
    """PRD §3.1: "Two booleans tune behaviour: `tax_exempt`, defaulting to false,
    excludes the line from the tax base when true; and `loyalty_eligible`, defaulting to
    true, governs whether the line's net accrues loyalty points."
    PRD §3.1: "A product is born `ACTIVE`; a `StoreManager` may later move it to
    `DISCONTINUED`."

    Design: Corner/entities/create_product_defaults_tax_exempt_false_loyalty_eligible_true
    """
    product = validate_success(
        api.create_product(
            {"sku": "DEF1", "barcode": "BDEF1", "name": "X",
             "list_price_cents": 500}, SM),
        expected_status=201)
    assert product["tax_exempt"] is False
    assert product["loyalty_eligible"] is True
    assert product["status"] == "ACTIVE"


def test_inventory_item_created_with_zero_quantities(api):
    """PRD §2.9: "A fresh inventory item is created with both `on_hand_qty` and
    `reserved_qty` at zero."
    PRD §2.9: "`available_qty`, the sellable count, is on-hand minus reserved."
    PRD §2.9: "the `below_reorder` flag is recomputed as true exactly when
    `available_qty` is at or below the item's `reorder_point` (the comparison is
    inclusive at the threshold)."

    Design: Corner/entities/inventory_item_computed_available_qty_ignores_client_input
    """
    store = create_store("CMP1", tax_rate_bps=0)
    product = create_product("PCMP", "BCMP", list_price_cents=100)
    item = validate_success(
        api.create_inventory_item(
            {"store_id": store["id"], "product_id": product["id"],
             "reorder_point": 4, "reorder_qty": 10}, IC),
        expected_status=201)
    assert item["on_hand_qty"] == 0
    assert item["reserved_qty"] == 0
    assert item["available_qty"] == 0
    assert item["below_reorder"] is True, "0 <= reorder_point 4"


def test_duplicate_product_sku_rejected(api):
    """PRD §3.1: "Both `sku` and `barcode` are unique across the catalogue, and a
    collision on either is an `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_product_sku_returns_duplicate_resource
    """
    get_success_data(api.create_product(
        {"sku": "DUP1", "barcode": "BD1", "name": "A", "list_price_cents": 100}, SM))
    resp = api.create_product(
        {"sku": "DUP1", "barcode": "BD2", "name": "B", "list_price_cents": 200}, SM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_tender_line_has_no_version_field(api):
    """PRD §2.4: "A tender line carries only `id` and `created_at` — it has no
    `updated_at` and no `version` — because tenders are immutable once recorded: a tender
    line is never edited, only appended, and any reversal is expressed as a new
    compensating tender line rather than a mutation of an existing one."

    Design: Corner/entities/tenderline_immutable_no_version_field
    """
    s = setup_store_product_stock("IMM1", "PIM", "BIM", on_hand=10,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 1}])
    validate_success(add_tender(sale["id"], "CASH", 1000, sale["version"]),
                     expected_status=201)
    resp = api.list_tenders(sale["id"], CA)
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    tender = data[0]
    assert "id" in tender and "created_at" in tender
    assert "version" not in tender, "TenderLine carries no version"
    assert "updated_at" not in tender, "TenderLine carries no updated_at"


def test_discontinue_product_flips_status(api):
    """PRD §3.1: "A product is born `ACTIVE`; a `StoreManager` may later move it to
    `DISCONTINUED`."

    Design: Corner/errors/discontinue_product_then_get_shows_status
    """
    product = create_product("PDC", "BDC", list_price_cents=100)
    validate_success(api.discontinue_product(product["id"], SM))
    fetched = get_success_data(api.get_product(product["id"], SM))
    assert fetched["status"] == "DISCONTINUED"


# ─────────────────────────────────────────────────────────────────────────────
# Invalid state transitions
# ─────────────────────────────────────────────────────────────────────────────

def test_void_settled_sale_rejected(api):
    """PRD §3.5: "Tender capture against a transition the sale cannot make — for instance
    tendering a sale that is already `SETTLED` or `VOIDED` — is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/void_already_settled_sale_returns_invalid_state
    """
    s = setup_store_product_stock("VS1", "PVS", "BVS", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 1}])
    validate_success(add_tender(sale["id"], "CASH", 1000, sale["version"]),
                     expected_status=201)
    resp = api.void_sale(sale["id"], CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reconcile_open_session_rejected(api):
    """PRD §3.2: "To reconcile, the manager submits the physically counted till as
    `counted_cash_cents`, moving the session `CLOSE_REQUESTED → RECONCILED`."
    PRD §2.5 / §3.13 state check: a transition the resource cannot make yields
    `ERR_INVALID_STATE`.

    Design: Corner/state_machines/reconcile_open_session_without_request_close_returns_invalid_state
    """
    store = create_store("RC1", tax_rate_bps=0)
    session = open_cash_session(store["id"], opening_float_cents=5000)
    resp = api.reconcile_cash_session(
        session["id"], {"counted_cash_cents": 5000}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_dispatch_received_transfer_rejected(api):
    """PRD §3.10: "To receive it, an `InventoryClerk` supplies `received_qty` between
    zero and the original `quantity` inclusive, and the destination inventory item at
    (`to_store_id`, `product_id`) must exist; the transfer moves `DISPATCHED →
    RECEIVED`."
    PRD §3.10: "A transfer action requested against a transition the transfer cannot make
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dispatch_already_received_transfer_returns_invalid_state
    """
    s = setup_transfer_pair("TRA", "TRB", "PTR", "BTR", source_on_hand=10,
                            dest_on_hand=0, quantity=2, list_price_cents=100)
    validate_success(
        api.dispatch_transfer(s["transfer"]["id"],
                              {"expected_transfer_version": s["transfer"]["version"]},
                              IC))
    received = validate_success(
        api.receive_transfer(s["transfer"]["id"], {"received_qty": 2}, IC))
    # Re-dispatch the RECEIVED transfer with its CURRENT version so the OCC guard
    # passes (PRD §3.13: ERR_STALE_VERSION is checked ahead of ERR_INVALID_STATE);
    # the request must then surface the out-of-state transition (PRD §3.10).
    resp = api.dispatch_transfer(
        s["transfer"]["id"], {"expected_transfer_version": received["version"]}, IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_count_post_after_movement_is_stale(api):
    """PRD §3.11: "A draft sheet may be posted only when the item has not moved since the
    sheet was opened — its current `on_hand_qty` must still equal `snapshot_on_hand_qty`;
    if stock has shifted in the meantime, the post is rejected with `ERR_COUNT_STALE`."

    Design: Corner/state_machines/count_post_stale_after_movement_returns_count_stale
    """
    store = create_store("CST1", tax_rate_bps=0)
    product = create_product("PCST", "BCST", list_price_cents=100)
    inv = create_inventory_item(store["id"], product["id"])
    seed = get_success_data(api.create_count_sheet(
        {"inventory_item_id": inv["id"], "counted_qty": 10}, IC))
    validate_success(api.post_count_sheet(seed["id"], IC))
    cs1 = get_success_data(api.create_count_sheet(
        {"inventory_item_id": inv["id"], "counted_qty": 9}, IC))
    cs2 = get_success_data(api.create_count_sheet(
        {"inventory_item_id": inv["id"], "counted_qty": 7}, IC))
    validate_success(api.post_count_sheet(cs2["id"], IC))
    resp = api.post_count_sheet(cs1["id"], IC)
    validate_error(resp, ApiErrorId.ERR_COUNT_STALE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Validation-priority conflicts
# ─────────────────────────────────────────────────────────────────────────────

def test_invalid_state_outranks_promo_not_stackable(api):
    """PRD §3.13: "The optimistic-concurrency check (`ERR_STALE_VERSION`) is evaluated
    next, ahead of the general state-transition check (`ERR_INVALID_STATE`); a stale
    version is reported before an out-of-state transition."
    PRD §3.13: "The domain-specific guards then apply in order: the return-reference
    check (`ERR_INVALID_RETURN_REFERENCE`), promo applicability
    (`ERR_PROMO_NOT_APPLICABLE`), stacking (`ERR_PROMO_NOT_STACKABLE`), loyalty
    sufficiency (`ERR_INSUFFICIENT_POINTS`), stock availability
    (`ERR_INSUFFICIENT_STOCK`), over-tender (`ERR_OVERTENDER`), and the count-staleness
    check (`ERR_COUNT_STALE`)."
    PRD §3.3: "A `Cashier` may replace the `lines` of a `DRAFT` sale — and re-supply
    `promo_code` and `redeem_points` — to reprice it; each such edit recomputes the
    pricing and increments the sale's `version` by one."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_promo_not_stackable_on_tendering_sale
    """
    store = create_store("PC1", tax_rate_bps=0)
    product = create_product("PPR", "BPR", list_price_cents=1000)
    create_inventory_item_with_stock(store["id"], product["id"], 10)
    create_promotion("NS10", "PERCENT_OFF", 10, min_subtotal_cents=0, stackable=False)
    account = create_loyalty_account(phone="555-0005")
    grant_points(account["id"], 500)
    open_cash_session(store["id"])
    sale = create_sale(store["id"], [{"product_id": product["id"], "quantity": 2}])
    validate_success(add_tender(sale["id"], "CARD", 1000, sale["version"]),
                     expected_status=201)
    # Sale is now TENDERING; editing lines is an out-of-state transition.
    resp = api.replace_sale_lines(
        sale["id"],
        {"lines": [{"product_id": product["id"], "quantity": 2}],
         "promo_code": "NS10", "redeem_points": 300}, CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_edit_lines_on_settled_sale_returns_invalid_state(api):
    """PRD §3.3: "A `Cashier` may replace the `lines` of a `DRAFT` sale — and re-supply
    `promo_code` and `redeem_points` — to reprice it; each such edit recomputes the
    pricing and increments the sale's `version` by one."
    PRD §3.13: "The domain-specific guards then apply in order: the return-reference
    check (`ERR_INVALID_RETURN_REFERENCE`), promo applicability
    (`ERR_PROMO_NOT_APPLICABLE`), stacking (`ERR_PROMO_NOT_STACKABLE`), loyalty
    sufficiency (`ERR_INSUFFICIENT_POINTS`), stock availability
    (`ERR_INSUFFICIENT_STOCK`), over-tender (`ERR_OVERTENDER`), and the count-staleness
    check (`ERR_COUNT_STALE`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_promo_not_stackable_on_tendering_sale
    """
    s = setup_store_product_stock("PC2", "PPR2", "BPR2", on_hand=10,
                                  list_price_cents=1000)
    create_promotion("NS11", "PERCENT_OFF", 10, min_subtotal_cents=0, stackable=False)
    account = create_loyalty_account(phone="555-0055")
    grant_points(account["id"], 500)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 2}])
    validate_success(add_tender(sale["id"], "CASH", 2000, sale["version"]),
                     expected_status=201)  # now SETTLED
    resp = api.replace_sale_lines(
        sale["id"],
        {"lines": [{"product_id": s["product"]["id"], "quantity": 2}],
         "promo_code": "NS11", "redeem_points": 300}, CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_return_reference_outranks_insufficient_stock(api):
    """PRD §3.13: "The domain-specific guards then apply in order: the return-reference
    check (`ERR_INVALID_RETURN_REFERENCE`), promo applicability
    (`ERR_PROMO_NOT_APPLICABLE`), stacking (`ERR_PROMO_NOT_STACKABLE`), loyalty
    sufficiency (`ERR_INSUFFICIENT_POINTS`), stock availability
    (`ERR_INSUFFICIENT_STOCK`), over-tender (`ERR_OVERTENDER`), and the count-staleness
    check (`ERR_COUNT_STALE`)."
    PRD §3.7: "A missing, non-settled, wrong-kind, or over-returning reference is rejected
    with `ERR_INVALID_RETURN_REFERENCE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_return_reference_outranks_insufficient_stock_on_exchange_create
    """
    store = create_store("RR1", tax_rate_bps=0)
    product = create_product("PRR", "BRR", list_price_cents=1000)
    create_inventory_item(store["id"], product["id"])  # on_hand 0
    open_cash_session(store["id"])
    draft = create_sale(store["id"], [{"product_id": product["id"], "quantity": 1}])
    # EXCHANGE naming an un-settled (DRAFT) original; outbound line also lacks stock.
    resp = api.create_sale(
        {"store_id": store["id"], "kind": "EXCHANGE", "original_sale_id": draft["id"],
         "lines": [{"product_id": product["id"], "quantity": 1,
                    "return_of_line_no": 1}]}, CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_RETURN_REFERENCE.value)


def test_return_reference_check_fires_on_tendering_original_no_stock(api):
    """PRD §3.7: "A missing, non-settled, wrong-kind, or over-returning reference is
    rejected with `ERR_INVALID_RETURN_REFERENCE`."
    PRD §3.13: "The domain-specific guards then apply in order: the return-reference
    check (`ERR_INVALID_RETURN_REFERENCE`), promo applicability
    (`ERR_PROMO_NOT_APPLICABLE`), stacking (`ERR_PROMO_NOT_STACKABLE`), loyalty
    sufficiency (`ERR_INSUFFICIENT_POINTS`), stock availability
    (`ERR_INSUFFICIENT_STOCK`), over-tender (`ERR_OVERTENDER`), and the count-staleness
    check (`ERR_COUNT_STALE`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_return_reference_outranks_insufficient_stock_on_exchange_create
    """
    store = create_store("RR2", tax_rate_bps=0)
    product = create_product("PRR2", "BRR2", list_price_cents=1000)
    create_inventory_item(store["id"], product["id"])  # on_hand 0
    open_cash_session(store["id"])
    orig = create_sale(store["id"], [{"product_id": product["id"], "quantity": 1}])
    # No stock so it can't settle; a partial CARD tender leaves it TENDERING.
    add_tender(orig["id"], "CARD", 500, orig["version"])
    resp = api.create_sale(
        {"store_id": store["id"], "kind": "EXCHANGE", "original_sale_id": orig["id"],
         "lines": [{"product_id": product["id"], "quantity": 1,
                    "return_of_line_no": 1}]}, CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_RETURN_REFERENCE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Reference resolution & pagination
# ─────────────────────────────────────────────────────────────────────────────

def test_inventory_item_unknown_store_reference_not_found(api):
    """PRD §2.5: "When a request body carries a foreign key — `store_id`, `product_id`,
    `loyalty_account_id`, `original_sale_id`, `inventory_item_id`, `customer_id`,
    `from_store_id`, or `to_store_id` — and that key names a row that does not exist, the
    request is rejected with `ERR_REFERENCE_NOT_FOUND` (422)."

    Design: Corner/validations/reference_not_found_unknown_store_on_inventory_item_create
    """
    product = create_product("PREF", "BREF", list_price_cents=100)
    resp = api.create_inventory_item(
        {"store_id": NON_EXISTENT_UUID, "product_id": product["id"],
         "reorder_point": 0, "reorder_qty": 0}, IC)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` outside the permitted range is rejected as a generic
    validation failure with `ERR_VALIDATION`."

    Design: Corner/validations/pagination_limit_out_of_range_returns_validation
    """
    resp = api.list_products(SM, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ─────────────────────────────────────────────────────────────────────────────
# RBAC
# ─────────────────────────────────────────────────────────────────────────────

def test_cashier_cannot_open_cash_session(api):
    """PRD §2.1: "A `StoreManager` owns store setup, promotions, cash-drawer lifecycle
    and reconciliation, product discontinuation, and the layaway overrides (forfeit and
    cancel); the manager also holds the two test-driving capabilities (granting loyalty
    points and advancing the clock)."
    PRD §2.1: "A request that is authenticated but whose role is not permitted to perform
    the requested operation is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/cashier_cannot_open_cash_session
    """
    store = create_store("RB1", tax_rate_bps=0)
    resp = api.create_cash_session(
        {"store_id": store["id"], "opening_float_cents": 1000}, CA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_inventory_clerk_cannot_create_sale(api):
    """PRD §2.1: "A `Cashier` owns the sale, return, and exchange register: creating and
    editing draft sales, appending tenders, and voiding."
    PRD §2.1: "A request that is authenticated but whose role is not permitted to perform
    the requested operation is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/inventory_clerk_cannot_create_sale
    """
    store = create_store("RB2", tax_rate_bps=0)
    product = create_product("PRB", "BRB", list_price_cents=100)
    open_cash_session(store["id"])
    resp = api.create_sale(
        {"store_id": store["id"], "kind": "SALE",
         "lines": [{"product_id": product["id"], "quantity": 1}]}, IC)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_unrecognized_role_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role` or presents a value that is not one
    of these four recognized roles is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unrecognized_role_returns_unauthenticated
    """
    ghost = build_user_headers("ghost-1", "Ghost")
    resp = api.create_store({"name": "S", "code": "RB3", "tax_rate_bps": 0}, ghost)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─────────────────────────────────────────────────────────────────────────────
# Optimistic concurrency
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_sale_version_on_second_tender_rejected(api):
    """PRD §2.7: "Appending a tender to a sale must carry `expected_sale_version` equal
    to the target sale's current `version`."
    PRD §2.7: "Because a prior split-payment tender or a line recompute legitimately
    advances the sale's `version`, a client holding an older view of `total_due_cents`
    and `tendered_cents` would otherwise risk over-collecting or settling against an
    outdated total; if another writer has advanced the sale's `version` since the client
    last read it, the tender is rejected with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_sale_version_on_second_tender
    """
    s = setup_store_product_stock("OC1", "POC", "BOC", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 3}])
    v0 = sale["version"]
    validate_success(add_tender(sale["id"], "CARD", 1000, v0), expected_status=201)
    resp = add_tender(sale["id"], "CARD", 1000, v0)  # stale v0
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_transfer_version_on_dispatch_rejected(api):
    """PRD §2.7: "Dispatching a transfer must carry `expected_transfer_version` equal to
    the transfer's current `version`; if a concurrent cancel or edit has advanced the
    transfer's `version` since the client last read it, the dispatch is rejected with
    `ERR_STALE_VERSION` (412), preventing source stock from being reserved against a
    transfer that is no longer `REQUESTED`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_transfer_version_on_dispatch
    """
    store_a = create_store("OTA", tax_rate_bps=0, name="A")
    store_b = create_store("OTB", tax_rate_bps=0, name="B")
    product = create_product("POT2", "BOT2", list_price_cents=100)
    create_inventory_item_with_stock(store_a["id"], product["id"], 5)
    create_inventory_item_with_stock(store_b["id"], product["id"], 0)
    transfer = create_transfer(store_a["id"], store_b["id"], product["id"], 1)
    resp = api.dispatch_transfer(
        transfer["id"], {"expected_transfer_version": transfer["version"] - 1}, IC)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ─────────────────────────────────────────────────────────────────────────────
# Consistency model: atomic settlement
# ─────────────────────────────────────────────────────────────────────────────

def test_sale_settlement_atomic_in_single_response(api):
    """PRD §3.5: "Settlement is the moment the sale's two dimensions advance together."
    PRD §3.5: "On the ledger side, loyalty `points_earned` are credited to any attached
    account, redeemed points are debited, the drawer's `expected_cash_cents` is updated
    by the net cash movement, and a return reverses both the points and the redemption."
    PRD §3.8: "Base points are that eligible net multiplied by the store's
    `loyalty_earn_rate_bps`, divided by ten thousand, floored."

    Design: Corner/consistency_model/sale_settlement_atomic_in_single_response
    """
    store = create_store("IM1", tax_rate_bps=0, loyalty_earn_rate_bps=100)
    product = create_product("PIM2", "BIM2", list_price_cents=1000)
    create_inventory_item_with_stock(store["id"], product["id"], 5)
    account = create_loyalty_account(phone="555-1004")
    open_cash_session(store["id"])
    sale = create_sale(store["id"],
                       [{"product_id": product["id"], "quantity": 2}],
                       loyalty_account_id=account["id"])
    validate_success(add_tender(sale["id"], "CASH", 2000, sale["version"]),
                     expected_status=201)
    fetched = get_sale(sale["id"])
    assert fetched["settlement_status"] == "SETTLED"
    assert fetched["stock_status"] == "COMMITTED"
    assert fetched["points_earned"] == 20, "floor(2000*100/10000)"
    acct = get_loyalty_account(account["id"])
    assert acct["points_balance"] == 20
