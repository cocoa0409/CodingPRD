"""Remaining breadth coverage: hotshot-fee and core-refund calculations, rollup
filtering, channel/state/qty validations, fitment/cross-reference lookups, duplicate
bay code, run-order-not-ready, RBAC denials, OCC version checks, warranty
replace+restock netting, and immediate-consistency totals.

Queue B: calculations, validations, endpoints, errors, rbac,
cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    build_user_headers,
    create_price_tier, create_part, create_stocked_part, create_account, create_open_order,
    add_line, allocate, ship, invoice, current_version, create_vehicle, create_fitment,
    create_cross_reference, create_driver, create_bay, schedule_run,
    setup_open_wholesale_order_with_line, setup_allocated_hotshot_order,
    setup_shipped_caliper_order, setup_warranty_claim,
    allocate_payload, ship_payload, create_part_payload, create_order_line_payload,
    create_sales_order_payload, create_bay_payload, create_warranty_claim_payload,
    create_core_return_payload,
    ApiErrorId, NONEXISTENT_UUID, TEST_USERS,
)

REP = TEST_USERS["wholesale_rep_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
ADMIN = TEST_USERS["warranty_admin_headers"]


# ═══ calculations ════════════════════════════════════════════════════════════

def test_hotshot_fee_two_special_units(api):
    """PRD §3.4: "Otherwise the fee is a flat base charge of twenty-five dollars plus
    seven dollars and fifty cents for each special-order unit, where the special-order
    unit count is the sum of qty over all non-cancelled special-order lines."

    One special line qty 2 -> hotshot_fee_cents == 2500 + 750*2 == 4000 at allocation.

    Design: Corner/calculations/calc_hotshot_fee_two_special_units
    """
    part, account, order, line = setup_allocated_hotshot_order(qty=2, special=True)
    assert order["hotshot_fee_cents"] == 4000, (
        f"hotshot_fee expected 4000 for two special units, got {order['hotshot_fee_cents']}"
    )


def test_hotshot_fee_zero_without_special_line(api):
    """PRD §3.4: "an order that requested hotshot but has exactly zero special-order
    lines still gets a fee of zero".

    Hotshot-requested order with only an in-stock line -> hotshot_fee_cents == 0.

    Design: Corner/calculations/calc_hotshot_fee_zero_when_no_special_line
    """
    part, account, order, line = setup_allocated_hotshot_order(qty=1, special=False)
    assert order["hotshot_fee_cents"] == 0, (
        f"hotshot_fee expected 0 with no special-order line, got {order['hotshot_fee_cents']}"
    )


def test_core_refund_amount_at_creation(api):
    """PRD §3.6: "the refund amount refund_cents is computed as the return qty
    multiplied by the line's net per-unit core price unit_core_price_cents".
    PRD §3.4: "For every shipped line whose part is rebuildable, the line's
    cores_outstanding is set to the line's qty, opening the core-deposit obligations."

    Caliper line unit_core 5400; a qty-1 core return computes refund_cents == 5400 and
    the shipped line has cores_outstanding 1.

    Design: Corner/calculations/calc_core_refund_amount_on_accept
    """
    part, account, order, line = setup_shipped_caliper_order(qty=1, stock_qty=3)
    cr = validate_success(api.create_core_return(
        create_core_return_payload(line["id"], 1), REP), 201)
    assert cr["refund_cents"] == 5400, f"refund_cents expected 5400, got {cr['refund_cents']}"
    final_line = get_success_data(api_client.get_order_line(line["id"], REP))
    assert final_line["cores_outstanding"] == 1


def test_order_rollup_excludes_cancelled_line(api):
    """PRD §3.3: "The merchandise_subtotal_cents is the sum of line_merch_total_cents
    over all lines whose status is not CANCELLED".
    PRD §3.3: "the order_total_cents is the merchandise subtotal plus the core subtotal
    plus the order's hotshot_fee_cents."

    A wholesale order cancelled while OPEN has merchandise_subtotal_cents 0 and
    order_total_cents 0.

    Design: Corner/calculations/calc_order_rollup_excludes_cancelled_line
    """
    part, account, order, line = setup_open_wholesale_order_with_line(
        qty=1, stock_qty=5,
        part_overrides=dict(description="Rollup", list_price_cents=5000, cost_cents=2000,
                            stockable=True, reorder_point=0, reorder_qty=0))
    cancelled = get_success_data(api_client.cancel_order(order["id"], REP))
    assert cancelled["merchandise_subtotal_cents"] == 0
    assert cancelled["order_total_cents"] == 0


# ═══ validations ═════════════════════════════════════════════════════════════

def test_channel_account_mismatch_rejected(api):
    """PRD §3.3: "The channel must agree with the account's type: a RETAIL account
    must be sold on the COUNTER channel and a WHOLESALE account on the WHOLESALE
    channel; a mismatch is rejected with ERR_CHANNEL_ACCOUNT_MISMATCH."

    Opening a COUNTER order for a WHOLESALE account is rejected.

    Design: Corner/validations/val_channel_account_mismatch_on_order_create
    """
    tier = create_price_tier()
    acct = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
    resp = api.create_sales_order(create_sales_order_payload(acct["id"], channel="COUNTER"), REP)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_ACCOUNT_MISMATCH.value)


def test_order_line_create_requires_open_order(api):
    """PRD §3.3: "Adding a line requires the parent order's fulfillment_status to be
    OPEN; adding a line to any other state is rejected with ERR_ORDER_NOT_OPEN."

    Adding a line to an ALLOCATED order (with a valid ACTIVE part) is rejected.

    Design: Corner/validations/val_order_line_create_requires_open_order
    """
    tier = create_price_tier()
    p1 = create_stocked_part(qty=5, description="Part1", list_price_cents=5000, cost_cents=2000,
                             stockable=True, reorder_point=0, reorder_qty=0)
    p2 = create_stocked_part(qty=5, description="Part2", list_price_cents=6000, cost_cents=2500,
                             stockable=True, reorder_point=0, reorder_qty=0)
    acct = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
    order = create_open_order(acct["id"], channel="WHOLESALE")
    add_line(order["id"], p1["id"], 1)
    allocate(order["id"])
    resp = api.create_order_line(create_order_line_payload(order["id"], p2["id"], 1), REP)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_OPEN.value)


def test_core_qty_exceeds_outstanding_rejected(api):
    """PRD §3.6: "Accepting a return - moving it from PENDING_INSPECTION to ACCEPTED -
    requires ... the return's qty to not exceed the line's current cores_outstanding
    (otherwise ERR_CORE_EXCEEDS_OUTSTANDING)".

    A line with qty 2 opens cores_outstanding 2, so two qty-2 returns are both
    openable (creation only requires qty <= cores_outstanding, per PRD §3.6, and
    creation does not decrement it). Accepting the first decrements
    cores_outstanding 2 -> 0; accepting the second (qty 2 > 0) is then rejected
    with ERR_CORE_EXCEEDS_OUTSTANDING and leaves cores_outstanding at 0.

    Design: Corner/validations/val_core_qty_exceeds_outstanding_rejected
    """
    part, account, order, line = setup_shipped_caliper_order(qty=2, stock_qty=3)
    cr1 = validate_success(api.create_core_return(create_core_return_payload(line["id"], 2), REP), 201)
    cr2 = validate_success(api.create_core_return(create_core_return_payload(line["id"], 2), REP), 201)
    get_success_data(api_client.accept_core_return(cr1["id"], ADMIN))
    resp = api.accept_core_return(cr2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CORE_EXCEEDS_OUTSTANDING.value)
    final_line = get_success_data(api_client.get_order_line(line["id"], REP))
    assert final_line["cores_outstanding"] == 0, "only the first accept decremented cores_outstanding"


def test_warranty_qty_exceeds_line_rejected(api):
    """PRD §3.7: "a qty claimed defective that is at least one and does not exceed the
    line's qty (a claim quantity over the line quantity is rejected with
    ERR_CLAIM_QTY_EXCEEDS_LINE)".

    Filing a qty-5 claim against a qty-1 line is rejected.

    Design: Corner/validations/val_warranty_qty_exceeds_line_rejected
    """
    part, account, order, line = setup_shipped_caliper_order(qty=1, stock_qty=5)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(line["id"], qty=5, reason="all bad", resolution="REFUND"), REP)
    validate_error(resp, ApiErrorId.ERR_CLAIM_QTY_EXCEEDS_LINE.value)


# ═══ endpoints ═══════════════════════════════════════════════════════════════

def test_fitment_reverse_lookup_by_vehicle(api):
    """PRD §3.1: "the listing of fitments can be filtered by part_id to find every
    vehicle a part fits, or by vehicle_id to find every part that fits a vehicle."

    Design: Corner/endpoints/ep_fitment_reverse_lookup_by_vehicle
    """
    part = create_part(description="Part", list_price_cents=1000, cost_cents=400)
    vehicle = create_vehicle(year=2018, make="HONDA", model="CIVIC")
    fitment = create_fitment(part["id"], vehicle["id"])
    data, _ = validate_paginated(api.list_fitments(CLERK, params={"vehicle_id": vehicle["id"]}))
    ids = [f["id"] for f in data]
    assert ids == [fitment["id"]], f"expected exactly the one fitment, got {ids}"


def test_cross_reference_self_referential_lookup(api):
    """PRD §3.1: "Cross-references can be listed and filtered by part_id or by
    interchange_part_id."

    Design: Corner/endpoints/ep_cross_reference_self_referential_lookup
    """
    oe = create_part(description="OE part", list_price_cents=5000, cost_cents=2000)
    am = create_part(description="Aftermarket", list_price_cents=4000, cost_cents=1500)
    xr = create_cross_reference(oe["id"], am["id"], relation="OE_TO_AFTERMARKET")
    data, _ = validate_paginated(api.list_cross_references(CLERK, params={"part_id": oe["id"]}))
    match = [x for x in data if x["id"] == xr["id"]]
    assert len(match) == 1, "the cross-reference must be listed under its part_id"
    assert match[0]["interchange_part_id"] == am["id"]


def test_fitment_part_not_found_on_create(api):
    """PRD §2.7: "the server validates their existence in order, path identifiers
    before body identifiers, and rejects the request at the first identifier that does
    not resolve. Each resource type has its own not-found error: ERR_PART_NOT_FOUND".

    POST /fitments with a non-existent part_id is rejected ERR_PART_NOT_FOUND.

    Design: Corner/endpoints/ep_fitment_part_not_found_on_create
    """
    vehicle = create_vehicle(year=2021, make="MAZDA", model="MX5")
    resp = api.create_fitment(
        {"part_id": NONEXISTENT_UUID, "vehicle_id": vehicle["id"]}, INV)
    validate_error(resp, ApiErrorId.ERR_PART_NOT_FOUND.value)


# ═══ errors ══════════════════════════════════════════════════════════════════

def test_duplicate_bay_code_rejected(api):
    """PRD §3.9: "can register a Bay with a code that must be unique across all bays
    (a repeat is rejected with ERR_DUPLICATE_BAY_CODE)."

    Design: Corner/errors/err_duplicate_bay_code_conflict
    """
    validate_success(api.create_bay(create_bay_payload(code="BAY-Z"), REP), 201)
    resp = api.create_bay(create_bay_payload(code="BAY-Z"), REP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BAY_CODE.value)


def test_dispatch_run_order_not_ready(api):
    """PRD §3.9: "Dispatching a run advances it from SCHEDULED to DISPATCHED, and
    requires the run to be SCHEDULED (otherwise ERR_RUN_NOT_SCHEDULED) and the
    referenced order to be in ALLOCATED or SHIPPED fulfillment (otherwise
    ERR_RUN_ORDER_NOT_READY)."

    A run whose order has since been cancelled (no longer ALLOCATED/SHIPPED) cannot be
    dispatched.

    Design: Corner/errors/err_run_order_not_ready_on_dispatch
    """
    part, account, order, line = setup_allocated_hotshot_order(qty=1, special=True)
    driver = create_driver(name="Drv", turnaround_min=0)
    bay = create_bay()
    run = schedule_run(order["id"], driver["id"], bay["id"], 10, 50)
    get_success_data(api_client.cancel_order(order["id"], REP))
    resp = api.dispatch_delivery_run(run["id"], REP)
    validate_error(resp, ApiErrorId.ERR_RUN_ORDER_NOT_READY.value)


# ═══ rbac ════════════════════════════════════════════════════════════════════

def test_counter_clerk_cannot_create_part(api):
    """PRD §3.1: "The catalog is the foundation, and an InventoryManager is its sole
    author."
    PRD §2.1: "When the headers are present and well-formed but the declared role is
    not permitted to perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Design: Corner/rbac/rbac_counter_clerk_cannot_create_part
    """
    resp = api.create_part(create_part_payload(
        sku="RB-1", description="Nope", list_price_cents=1000, cost_cents=400), CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_counter_clerk_cannot_approve_warranty(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared role is
    not permitted to perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."
    PRD §2.1: "A WarrantyAdmin adjudicates core returns and warranty/defective claims."

    A CounterClerk calling approve (WarrantyAdmin-only) is rejected.

    Design: Corner/rbac/rbac_counter_clerk_cannot_approve_warranty
    """
    part, account, order, line, claim = setup_warranty_claim(
        resolution="REFUND", qty=1, line_qty=1, warranty_days=365, escalate=True, invoiced=False)
    resp = api.approve_claim(claim["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_missing_user_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    A request bearing an unrecognized role context is rejected before any business
    logic.

    Design: Corner/rbac/rbac_missing_user_headers_unauthenticated
    """
    anon = build_user_headers("anon-1", "Anonymous")
    resp = api.list_parts(anon)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ═══ cross_cutting_complexity_layers ═════════════════════════════════════════

def test_occ_allocate_correct_version_succeeds(api):
    """PRD §2.9: "When allocating an order, if expected_sales_order_version does not
    equal the target SalesOrder's current version, the allocation is rejected with
    ERR_STALE_VERSION (HTTP 412)."
    PRD §3.4: "the order's version is incremented by one, and the order moves to
    ALLOCATED."

    Allocating with the current version succeeds and bumps version by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_allocate_correct_version_succeeds
    """
    part, account, order, line = setup_open_wholesale_order_with_line(
        qty=1, stock_qty=5,
        part_overrides=dict(description="Part", list_price_cents=5000, cost_cents=2000,
                            stockable=True, reorder_point=0, reorder_qty=0))
    v1 = current_version(order["id"])
    allocated = get_success_data(api_client.allocate_order(order["id"], allocate_payload(v1), REP))
    assert allocated["fulfillment_status"] == "ALLOCATED"
    assert allocated["version"] == v1 + 1, f"version should advance to {v1 + 1}, got {allocated['version']}"


def test_occ_allocate_stale_version_rejected(api):
    """PRD §2.9: "When allocating an order, if expected_sales_order_version does not
    equal the target SalesOrder's current version, the allocation is rejected with
    ERR_STALE_VERSION (HTTP 412)."
    PRD §3.3: "Adding a line is a mutation of the parent order: it recomputes the
    rollup and increments the order's version by one".

    A version captured before a second line was added is stale; allocate is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_allocate_stale_version_rejected
    """
    part, account, order, line = setup_open_wholesale_order_with_line(
        qty=1, stock_qty=10,
        part_overrides=dict(description="Part", list_price_cents=5000, cost_cents=2000,
                            stockable=True, reorder_point=0, reorder_qty=0))
    v_stale = current_version(order["id"])
    add_line(order["id"], part["id"], 1)  # bumps version
    resp = api.allocate_order(order["id"], allocate_payload(v_stale), REP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_success_data(api_client.get_sales_order(order["id"], REP))
    assert after["fulfillment_status"] == "OPEN", "rejected allocate must leave order OPEN"


def test_occ_ship_stale_version_rejected(api):
    """PRD §2.9: "when shipping an order, if expected_sales_order_version does not
    equal the order's current version, the shipment is rejected with ERR_STALE_VERSION
    (HTTP 412); the allocation step itself advances the order's version, so a ship
    request carrying the pre-allocation version is stale and refused."

    Shipping with the pre-allocate version (stale after allocate bumped it) is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_ship_stale_version_rejected
    """
    part, account, order, line = setup_open_wholesale_order_with_line(
        qty=1, stock_qty=10,
        part_overrides=dict(description="Part", list_price_cents=5000, cost_cents=2000,
                            stockable=True, reorder_point=0, reorder_qty=0))
    v_pre_alloc = current_version(order["id"])
    get_success_data(api_client.allocate_order(order["id"], allocate_payload(v_pre_alloc), REP))
    resp = api.ship_order(order["id"], ship_payload(v_pre_alloc), REP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = get_success_data(api_client.get_sales_order(order["id"], REP))
    assert after["fulfillment_status"] == "ALLOCATED", "rejected ship must leave order ALLOCATED"


def test_warranty_replace_restock_nets_zero_inventory(api):
    """PRD §3.7: "instead a replacement unit is issued by decreasing the part's
    on_hand_qty by the claim qty and recomputing available_qty".
    PRD §3.7: "Independently of the resolution, if restock_defective is true the
    defective unit is returned to inventory by increasing the part's on_hand_qty by the
    claim qty and recomputing available_qty".

    APPROVED REPLACE with restock_defective true nets zero: ship took 1 of 5 (on_hand 4),
    REPLACE -1 and restock +1 leave on_hand 4; credit_cents 0.

    Design: Corner/cross_cutting_complexity_layers/ccl_warranty_replace_restock_derived_inventory
    """
    part, account, order, line, claim = setup_warranty_claim(
        resolution="REPLACE", qty=1, line_qty=1, warranty_days=365,
        restock_defective=True, escalate=True, invoiced=False, stock_qty=5)
    approved = get_success_data(api_client.approve_claim(claim["id"], ADMIN))
    assert approved["credit_cents"] == 0
    final_part = get_success_data(api_client.get_part(part["id"], INV))
    assert final_part["on_hand_qty"] == 4, (
        f"REPLACE -1 and restock +1 should net to 4 (post-ship), got {final_part['on_hand_qty']}"
    )


# ═══ consistency_model ═══════════════════════════════════════════════════════

def test_allocate_totals_visible_in_same_response(api):
    """PRD §3.4: "The hotshot fee is computed at this point, the order totals are
    recomputed to include it".
    PRD §3.3: "the order_total_cents is the merchandise subtotal plus the core subtotal
    plus the order's hotshot_fee_cents."
    PRD §3.4: "while a single special-order unit yields the base plus the per-unit
    charge."

    Special line list 10000 on JOBBER -> merch 7000; hotshot fee for 1 unit 3250;
    the allocate response already reflects order_total 10250.

    Design: Corner/consistency_model/cm_allocate_totals_visible_same_response
    """
    tier = create_price_tier()
    part = create_part(description="Special", list_price_cents=10000, cost_cents=4000,
                       stockable=False, reorder_point=0, reorder_qty=0)
    acct = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
    order = create_open_order(acct["id"], channel="WHOLESALE", hotshot_requested=True)
    add_line(order["id"], part["id"], 1)
    v = current_version(order["id"])
    allocated = get_success_data(api_client.allocate_order(order["id"], allocate_payload(v), REP))
    assert allocated["hotshot_fee_cents"] == 3250
    assert allocated["order_total_cents"] == 10250, (
        f"order_total expected 10250 (merch 7000 + hotshot 3250), got {allocated['order_total_cents']}"
    )
