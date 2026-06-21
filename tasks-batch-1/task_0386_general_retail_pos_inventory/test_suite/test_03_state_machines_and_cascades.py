"""Parallel sale dimensions, the layaway payment cycle, cross-entity state
dependencies, transitive cascades (force-close, layaway fulfillment), and
compensating-void invariants.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_store, create_product, open_cash_session,
    create_loyalty_account, grant_points, create_sale, add_tender,
    create_tendering_sale, get_sale, get_inventory_item, get_loyalty_account,
    get_layaway, advance_clock, layaway_payment, settle_sale_cash,
    setup_store_product_stock, setup_layaway,
    create_inventory_item_with_stock,
)

SM = TEST_USERS["store_manager_headers"]
CA = TEST_USERS["cashier_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Parallel state machine: settlement_status vs stock_status evolve independently
# ─────────────────────────────────────────────────────────────────────────────

def test_sale_stock_axis_stays_pending_during_partial_tender(api):
    """PRD §3.6: "The stock axis (`stock_status`) of a sale evolves independently of its
    payment axis and only ever moves at settlement."
    PRD §1: "A single sale carries two independent fates — how it is paid for and how it
    touches stock — and the platform tracks those two dimensions separately so that the
    money side and the goods side can never be confused for one another."

    Design: Difficulty/non_linear_state_machine/sale_parallel_settlement_and_stock_dimensions_evolve_independently
    """
    s = setup_store_product_stock("PAR1", "PP-PAR", "BP-PAR", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 2}])
    validate_success(add_tender(sale["id"], "CARD", 1200, sale["version"]),
                     expected_status=201)
    mid = get_sale(sale["id"])
    assert mid["settlement_status"] == "TENDERING"
    assert mid["stock_status"] == "PENDING", "stock axis unchanged while TENDERING"

    inv = get_inventory_item(s["inventory_item_id"])
    assert inv["on_hand_qty"] == 5, "on_hand not decremented while TENDERING"


def test_sale_stock_commits_only_at_settlement(api):
    """PRD §3.6: "When a `SALE` settles, it transitions `PENDING → COMMITTED`: for each
    line, the system first requires that the line's `InventoryItem` has `available_qty`
    at least the line `quantity`; if any line falls short, settlement is rejected with
    `ERR_INSUFFICIENT_STOCK`."
    PRD §3.6: "The stock axis (`stock_status`) of a sale evolves independently of its
    payment axis and only ever moves at settlement."

    Design: Difficulty/non_linear_state_machine/sale_parallel_settlement_and_stock_dimensions_evolve_independently
    """
    s = setup_store_product_stock("PAR2", "PP-PR2", "BP-PR2", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 2}])
    validate_success(add_tender(sale["id"], "CASH", 2000, sale["version"]),
                     expected_status=201)
    settled = get_sale(sale["id"])
    assert settled["settlement_status"] == "SETTLED"
    assert settled["stock_status"] == "COMMITTED"
    inv = get_inventory_item(s["inventory_item_id"])
    assert inv["on_hand_qty"] == 3, "on_hand decremented at settlement"


# ─────────────────────────────────────────────────────────────────────────────
# Layaway cyclic ACTIVE -> DELINQUENT -> ACTIVE payment loop
# ─────────────────────────────────────────────────────────────────────────────

def test_layaway_cycles_active_delinquent_active(api):
    """PRD §3.9: "While `ACTIVE`, if the clock advances past the `due_date` while
    `balance_cents` is still above zero, the layaway moves `ACTIVE → DELINQUENT`
    (reservation retained, further deposits still accepted)."
    PRD §3.9: "A deposit recorded while `DELINQUENT` that leaves `balance_cents` still
    above zero moves it back `DELINQUENT → ACTIVE`."

    Design: Difficulty/non_linear_state_machine/layaway_cyclic_active_delinquent_active_payment_loop
    """
    advance_clock("2026-06-01T00:00:00Z")
    store = create_store("LAY1", tax_rate_bps=0)
    product = create_product("PL-LAY", "BL-LAY", list_price_cents=10000)
    create_inventory_item_with_stock(store["id"], product["id"], 5)
    account = create_loyalty_account(phone="555-0003")
    lay = get_success_data(api.create_layaway(
        {"store_id": store["id"], "product_id": product["id"],
         "customer_id": account["id"], "quantity": 1,
         "due_date": "2026-06-10T00:00:00Z", "initial_deposit_cents": 2000}, CA))
    advance_clock("2026-06-11T00:00:00Z")

    delinquent = get_layaway(lay["id"])
    assert delinquent["status"] == "DELINQUENT", "clock past due_date, balance 8000"

    validate_success(layaway_payment(lay["id"], 3000, delinquent["version"]))
    cycled = get_layaway(lay["id"])
    assert cycled["status"] == "ACTIVE", "deposit while balance>0 cycles back to ACTIVE"
    assert cycled["balance_cents"] == 5000


def test_layaway_becomes_delinquent_when_clock_passes_due(api):
    """PRD §3.9: "While `ACTIVE`, if the clock advances past the `due_date` while
    `balance_cents` is still above zero, the layaway moves `ACTIVE → DELINQUENT`
    (reservation retained, further deposits still accepted)."
    PRD §3.12: "Advancing the clock sets the current UTC and runs the layaway due-date
    sweep: every `ACTIVE` layaway whose `due_date` is now in the past and whose
    `balance_cents` remains above zero is moved `ACTIVE → DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/layaway_cyclic_active_delinquent_active_payment_loop
    """
    advance_clock("2026-07-01T00:00:00Z")
    store = create_store("LAY2", tax_rate_bps=0)
    product = create_product("PL-LAY2", "BL-LAY2", list_price_cents=10000)
    create_inventory_item_with_stock(store["id"], product["id"], 5)
    account = create_loyalty_account(phone="555-0033")
    lay = get_success_data(api.create_layaway(
        {"store_id": store["id"], "product_id": product["id"],
         "customer_id": account["id"], "quantity": 1,
         "due_date": "2026-07-10T00:00:00Z", "initial_deposit_cents": 2000}, CA))
    assert get_layaway(lay["id"])["status"] == "ACTIVE"
    advance_clock("2026-07-11T00:00:00Z")
    assert get_layaway(lay["id"])["status"] == "DELINQUENT", "clock past due_date, balance>0"


# ─────────────────────────────────────────────────────────────────────────────
# Cross-entity state dependency
# ─────────────────────────────────────────────────────────────────────────────

def test_tender_requires_store_drawer_open(api):
    """PRD §2.8: "The practical force of `posture` is that it gates payment: tender
    capture on a sale is permitted only while the selling store is `DRAWER_OPEN`, and is
    blocked while the store is `LOCKED`."
    PRD §3.5: "Tender capture is permitted only while the selling store is
    `DRAWER_OPEN`; a tender attempted while the store has no open drawer is rejected with
    `ERR_DRAWER_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/tender_requires_store_posture_drawer_open
    """
    store = create_store("DO1", tax_rate_bps=0)
    product = create_product("PDO", "BDO", list_price_cents=1000)
    create_inventory_item_with_stock(store["id"], product["id"], 10)
    session = open_cash_session(store["id"])
    sale = create_sale(store["id"], [{"product_id": product["id"], "quantity": 1}])
    get_success_data(api.request_close_cash_session(session["id"], SM))

    resp = add_tender(sale["id"], "CASH", 1000, sale["version"])
    validate_error(resp, ApiErrorId.ERR_DRAWER_NOT_OPEN.value)


def test_tender_permitted_again_after_drawer_reopened(api):
    """PRD §2.8: "The practical force of `posture` is that it gates payment: tender
    capture on a sale is permitted only while the selling store is `DRAWER_OPEN`, and is
    blocked while the store is `LOCKED`."
    PRD §3.2: "A manager may instead reopen a frozen session, moving it `CLOSE_REQUESTED
    → OPEN`; this clears `counted_cash_cents` and `variance_cents`, recomputes the
    store's `posture` back to `DRAWER_OPEN`, and increments the session's `version`."

    Design: Difficulty/cross_entity_state_dependency/tender_requires_store_posture_drawer_open
    """
    store = create_store("DO2", tax_rate_bps=0)
    product = create_product("PDO2", "BDO2", list_price_cents=1000)
    create_inventory_item_with_stock(store["id"], product["id"], 10)
    session = open_cash_session(store["id"])
    sale = create_sale(store["id"], [{"product_id": product["id"], "quantity": 1}])
    get_success_data(api.request_close_cash_session(session["id"], SM))
    validate_error(add_tender(sale["id"], "CASH", 1000, sale["version"]),
                   ApiErrorId.ERR_DRAWER_NOT_OPEN.value)
    get_success_data(api.reopen_cash_session(session["id"], SM))
    sale_now = get_sale(sale["id"])
    validate_success(add_tender(sale["id"], "CASH", 1000, sale_now["version"]),
                     expected_status=201)
    assert get_sale(sale["id"])["settlement_status"] == "SETTLED"


def test_return_against_voided_original_rejected(api):
    """PRD §3.7: "The reference itself is validated up front: the `original_sale_id` must
    be present, must point to a sale that is `SETTLED` and of `kind` `SALE`, and each
    `return_of_line_no` must map to an original line that has not already been fully
    returned."

    Design: Difficulty/cross_entity_state_dependency/return_requires_original_sale_settled
    """
    store = create_store("RS1", tax_rate_bps=0)
    product = create_product("PRS", "BRS", list_price_cents=1000)
    create_inventory_item_with_stock(store["id"], product["id"], 10)
    open_cash_session(store["id"])
    orig = create_sale(store["id"], [{"product_id": product["id"], "quantity": 1}])
    get_success_data(api.void_sale(orig["id"], CA))

    resp = api.create_sale(
        {"store_id": store["id"], "kind": "RETURN", "original_sale_id": orig["id"],
         "lines": [{"product_id": product["id"], "quantity": 1,
                    "return_of_line_no": 1}]}, CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_RETURN_REFERENCE.value)


def test_return_against_settled_original_is_accepted(api):
    """PRD §3.7: "The reference itself is validated up front: the `original_sale_id` must
    be present, must point to a sale that is `SETTLED` and of `kind` `SALE`, and each
    `return_of_line_no` must map to an original line that has not already been fully
    returned."

    Design: Difficulty/cross_entity_state_dependency/return_requires_original_sale_settled
    """
    s = setup_store_product_stock("RS2", "PRS2", "BRS2", on_hand=10,
                                  list_price_cents=1000)
    orig = settle_sale_cash(s["store"]["id"],
                            [{"product_id": s["product"]["id"], "quantity": 1}])
    assert orig["settlement_status"] == "SETTLED"
    ret = create_sale(
        s["store"]["id"], [{"product_id": s["product"]["id"], "quantity": 1,
                            "return_of_line_no": 1}],
        kind="RETURN", original_sale_id=orig["id"])
    assert ret["settlement_status"] == "DRAFT"
    assert ret["kind"] == "RETURN"


# ─────────────────────────────────────────────────────────────────────────────
# Transitive cascade: force-close
# ─────────────────────────────────────────────────────────────────────────────

def test_force_close_cascades_void_reverse_tender_keep_stock(api):
    """PRD §3.2: "A force-close is the most consequential drawer action: every sale
    bound to the session still in `DRAFT` is voided to `VOIDED` and any reservation it
    held is released; every bound sale in `TENDERING` is voided as well, with its
    captured tenders reversed through compensating refund tender lines and its inventory
    and loyalty effects unwound; the store's `posture` is recomputed to `LOCKED`; and
    the session's `version` increments by one."

    Design: Difficulty/transitive_cascade/force_close_cascades_void_then_reverse_tender_then_restock_depth3
    """
    s = setup_store_product_stock("FC1", "PF-FC", "BF-FC", on_hand=5,
                                  list_price_cents=1000)
    sale = create_tendering_sale(
        s["store"]["id"], [{"product_id": s["product"]["id"], "quantity": 2}],
        partial_amount=1200, method="CARD")
    assert sale["settlement_status"] == "TENDERING"

    session = validate_success(
        api.force_close_cash_session(s["session"]["id"], SM))
    assert session["status"] == "FORCE_CLOSED"

    voided = get_sale(sale["id"])
    assert voided["settlement_status"] == "VOIDED", "link 1: bound sale voided"
    assert voided["tendered_cents"] == 0, "link 2: CARD tender reversed by the void"

    inv = get_inventory_item(s["inventory_item_id"])
    assert inv["on_hand_qty"] == 5, "link 3: never committed; stock intact"


def test_force_close_locks_store_and_voids_draft_sale(api):
    """PRD §3.2: "A force-close is the most consequential drawer action: every sale
    bound to the session still in `DRAFT` is voided to `VOIDED` and any reservation it
    held is released; every bound sale in `TENDERING` is voided as well, with its
    captured tenders reversed through compensating refund tender lines and its inventory
    and loyalty effects unwound; the store's `posture` is recomputed to `LOCKED`; and
    the session's `version` increments by one."

    Design: Difficulty/transitive_cascade/force_close_cascades_void_then_reverse_tender_then_restock_depth3
    """
    s = setup_store_product_stock("FC2", "PF-FC2", "BF-FC2", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 2}])
    assert sale["settlement_status"] == "DRAFT"
    validate_success(api.force_close_cash_session(s["session"]["id"], SM))

    assert get_sale(sale["id"])["settlement_status"] == "VOIDED", "bound DRAFT sale voided"
    store = get_success_data(api.get_store(s["store"]["id"], SM))
    assert store["posture"] == "LOCKED", "posture recomputed to LOCKED"


def test_layaway_fulfill_cascades_drawdown_and_below_reorder(api):
    """PRD §3.9: "From either `ACTIVE` or `DELINQUENT`, a deposit that brings
    `balance_cents` to exactly zero fulfills the layaway, moving it to `FULFILLED`: the
    reserved units leave with the customer, so the item's `reserved_qty` is decremented
    by the `quantity` and its `on_hand_qty` is also decremented by the `quantity`, with
    `available_qty` and `below_reorder` recomputed."
    PRD §2.9: "the `below_reorder` flag is recomputed as true exactly when
    `available_qty` is at or below the item's `reorder_point` (the comparison is
    inclusive at the threshold)."

    Design: Difficulty/transitive_cascade/layaway_fulfill_cascades_inventory_drawdown_then_below_reorder_depth2
    """
    s = setup_layaway("LF1", "PLF", "BLF", quantity=1, on_hand=3,
                      list_price_cents=1000, due_date="2026-12-31T00:00:00Z",
                      initial_deposit_cents=0, reorder_point=2, reorder_qty=5)
    lay = s["layaway"]
    validate_success(layaway_payment(lay["id"], 1000, lay["version"]))

    fulfilled = get_layaway(lay["id"])
    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["balance_cents"] == 0

    inv = get_inventory_item(s["inventory_item_id"])
    assert inv["on_hand_qty"] == 2, "link 1: on_hand drawn down"
    assert inv["reserved_qty"] == 0, "link 1: reservation released"
    assert inv["available_qty"] == 2
    assert inv["below_reorder"] is True, "link 2: 2 <= reorder_point 2 inclusive"


def test_layaway_fulfillment_decrements_on_hand_and_reserved(api):
    """PRD §3.9: "From either `ACTIVE` or `DELINQUENT`, a deposit that brings
    `balance_cents` to exactly zero fulfills the layaway, moving it to `FULFILLED`: the
    reserved units leave with the customer, so the item's `reserved_qty` is decremented
    by the `quantity` and its `on_hand_qty` is also decremented by the `quantity`, with
    `available_qty` and `below_reorder` recomputed."

    Design: Difficulty/transitive_cascade/layaway_fulfill_cascades_inventory_drawdown_then_below_reorder_depth2
    """
    s = setup_layaway("LF2", "PLF2", "BLF2", quantity=1, on_hand=5,
                      list_price_cents=1000, due_date="2026-12-31T00:00:00Z",
                      initial_deposit_cents=0, reorder_point=0, reorder_qty=0)
    lay = s["layaway"]
    before = get_inventory_item(s["inventory_item_id"])
    assert before["reserved_qty"] == 1, "reservation placed at layaway create"
    validate_success(layaway_payment(lay["id"], 1000, lay["version"]))
    after = get_inventory_item(s["inventory_item_id"])
    assert after["on_hand_qty"] == 4, "on_hand drawn down by quantity"
    assert after["reserved_qty"] == 0, "reservation cleared"
    assert after["available_qty"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# Compensating invariants: void conserves inventory units / loyalty points
# ─────────────────────────────────────────────────────────────────────────────

def test_void_conserves_on_hand_inventory_units(api):
    """PRD §3.5: "A sale that has not yet settled may be voided by a `Cashier`, which is
    allowed from `DRAFT` or `TENDERING` (anything but `SETTLED`); a void reverses any
    captured tenders through compensating tender lines, releases any inventory
    reservation or commitment so there is no net stock change, restores any
    provisionally debited loyalty redemption, and sets `settlement_status` to `VOIDED`."

    Design: Difficulty/compensating_invariant/void_conserves_total_on_hand_inventory_units
    """
    s = setup_store_product_stock("VI1", "PVI", "BVI", on_hand=5,
                                  list_price_cents=1000)
    sale = create_tendering_sale(
        s["store"]["id"], [{"product_id": s["product"]["id"], "quantity": 2}],
        partial_amount=1000, method="CARD")

    voided = validate_success(api.void_sale(sale["id"], CA))
    assert voided["settlement_status"] == "VOIDED"

    inv = get_inventory_item(s["inventory_item_id"])
    assert inv["on_hand_qty"] == 5, "conserved; equals pre-sale level"
    assert inv["available_qty"] == 5
    assert inv["reserved_qty"] == 0


def test_void_keeps_stock_status_off_committed(api):
    """PRD §3.5: "A sale that has not yet settled may be voided by a `Cashier`, which is
    allowed from `DRAFT` or `TENDERING` (anything but `SETTLED`); a void reverses any
    captured tenders through compensating tender lines, releases any inventory
    reservation or commitment so there is no net stock change, restores any
    provisionally debited loyalty redemption, and sets `settlement_status` to `VOIDED`."

    Design: Difficulty/compensating_invariant/void_conserves_total_on_hand_inventory_units
    """
    s = setup_store_product_stock("VI2", "PVI2", "BVI2", on_hand=5,
                                  list_price_cents=1000)
    sale = create_tendering_sale(
        s["store"]["id"], [{"product_id": s["product"]["id"], "quantity": 2}],
        partial_amount=1000, method="CARD")
    assert sale["stock_status"] == "PENDING"
    validate_success(api.void_sale(sale["id"], CA))
    inv = get_inventory_item(s["inventory_item_id"])
    assert inv["on_hand_qty"] == 5, "no net stock change from a voided tendering sale"


def test_void_conserves_loyalty_points_balance(api):
    """PRD §3.5: "A sale that has not yet settled may be voided by a `Cashier`, which is
    allowed from `DRAFT` or `TENDERING` (anything but `SETTLED`); a void reverses any
    captured tenders through compensating tender lines, releases any inventory
    reservation or commitment so there is no net stock change, restores any
    provisionally debited loyalty redemption, and sets `settlement_status` to `VOIDED`."

    Design: Difficulty/compensating_invariant/void_conserves_loyalty_points_balance
    """
    store = create_store("VL1", tax_rate_bps=0)
    product = create_product("PVL", "BVL", list_price_cents=1000)
    create_inventory_item_with_stock(store["id"], product["id"], 10)
    account = create_loyalty_account(phone="555-0008")
    grant_points(account["id"], 500)
    open_cash_session(store["id"])

    sale = create_sale(
        store["id"], [{"product_id": product["id"], "quantity": 2}],
        loyalty_account_id=account["id"], redeem_points=300)
    validate_success(add_tender(sale["id"], "CARD", 500, sale["version"]),
                     expected_status=201)
    voided = validate_success(api.void_sale(sale["id"], CA))
    assert voided["settlement_status"] == "VOIDED"

    after = get_loyalty_account(account["id"])
    assert after["points_balance"] == 500, "redeemed points restored; no leak"
    assert after["lifetime_points"] == 500


def test_void_before_settlement_earns_no_points(api):
    """PRD §3.8: "Earning runs at the settlement of a `SALE`."
    PRD §3.5: "a void reverses any captured tenders through compensating tender lines,
    releases any inventory reservation or commitment so there is no net stock change,
    restores any provisionally debited loyalty redemption, and sets `settlement_status`
    to `VOIDED`."

    Design: Difficulty/compensating_invariant/void_conserves_loyalty_points_balance
    """
    store = create_store("VL2", tax_rate_bps=0)
    product = create_product("PVL2", "BVL2", list_price_cents=1000)
    create_inventory_item_with_stock(store["id"], product["id"], 10)
    account = create_loyalty_account(phone="555-0088")
    grant_points(account["id"], 500)
    open_cash_session(store["id"])
    sale = create_sale(store["id"],
                       [{"product_id": product["id"], "quantity": 2}],
                       loyalty_account_id=account["id"], redeem_points=300)
    validate_success(add_tender(sale["id"], "CARD", 500, sale["version"]),
                     expected_status=201)
    validate_success(api.void_sale(sale["id"], CA))
    acct = get_loyalty_account(account["id"])
    assert acct["points_balance"] == 500
    assert acct["lifetime_points"] == 500, "no earn accrued (sale never settled)"
