"""Fix curation: the STYLING<->PREVIEW revision loop, item selection/removal with
inventory reservation, stylist capacity, sibling-status gating, and validation
precedence on item add.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_client_headers, make_stylist_headers,
    create_active_client, create_product, create_stylist,
    schedule_fix, assign_fix, add_item,
    setup_styling_fix, setup_preview_fix,
    get_fix, get_product, assert_inventory_conserved,
)

OPS = TEST_USERS["ops_headers"]


# ------------------------------------------------ Difficulty: revision loop cycle
def test_request_changes_moves_preview_back_to_styling(api):
    """PRD §3.4: "The subscriber, on seeing the preview, may send it back for
    restyling, transitioning the fix from PREVIEW back to STYLING and reopening it
    for the stylist to edit — the STYLING and PREVIEW states form a revision loop
    that may repeat."

    Design: Difficulty/non_linear_state_machine/fix_preview_revision_cycle
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000])
    resp = api.request_changes(ctx["fix_id"], headers=make_client_headers(ctx["client_id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "STYLING", f"expected STYLING, got {data['status']}"


def test_preview_styling_preview_cycle_completes(api):
    """PRD §3.4: "Once the box holds a valid number of items, the stylist submits it
    for preview, transitioning the fix from STYLING to PREVIEW."
    PRD §3.4: "the STYLING and PREVIEW states form a revision loop that may repeat."

    Design: Difficulty/non_linear_state_machine/fix_preview_revision_cycle
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000])
    sty = make_stylist_headers(ctx["stylist_id"])
    validate_success(api.request_changes(ctx["fix_id"], headers=make_client_headers(ctx["client_id"])), 200)
    assert get_fix(ctx["fix_id"])["status"] == "STYLING"
    resp = api.submit_preview(ctx["fix_id"], headers=sty)
    data = validate_success(resp, 200)
    assert data["status"] == "PREVIEW", f"cycle should re-advance to PREVIEW, got {data['status']}"


# ------------------------------------- Difficulty: state check beats item-limit
def test_add_item_to_preview_fix_rejected_by_state(api):
    """PRD §3.4: "Item and preview operations that target a fix in the wrong state are
    rejected at the state layer: item add and submit-preview require STYLING
    (ERR_FIX_NOT_STYLING)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_add_item
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000, 3000, 3000])  # 5 items, PREVIEW
    resp = api.add_fix_item(
        ctx["fix_id"], {"product_id": ctx["product_ids"][0]},
        headers=make_stylist_headers(ctx["stylist_id"]))
    validate_error(resp, ApiErrorId.ERR_FIX_NOT_STYLING.value)


def test_state_error_preempts_item_limit(api):
    """PRD §2.10: "structural business constraints (priority 10) are evaluated after
    state and sibling-status checks."
    PRD §3.4: "item add and submit-preview require STYLING (ERR_FIX_NOT_STYLING)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_add_item
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000, 3000, 3000])  # at MAX_ITEMS (5), PREVIEW
    resp = api.add_fix_item(
        ctx["fix_id"], {"product_id": ctx["product_ids"][0]},
        headers=make_stylist_headers(ctx["stylist_id"]))
    # The state error, not ERR_FIX_ITEM_LIMIT, is reported.
    validate_error(resp, ApiErrorId.ERR_FIX_NOT_STYLING.value)
    assert get_fix(ctx["fix_id"])["item_count"] == 5, "no item should have been added"


# ------------------------- Difficulty: FixItem creation depends on Product status
def test_add_discontinued_product_rejected(api):
    """PRD §3.3: "a discontinued product can no longer be selected into fixes or
    purchased, and referencing one where an ACTIVE product is required yields
    ERR_PRODUCT_UNAVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/add_item_requires_product_active
    """
    ctx = setup_styling_fix(prices=[])  # STYLING fix, no items
    prod = create_product(total_stock=5)
    validate_success(api.discontinue_product(prod["id"], headers=OPS), 200)
    resp = api.add_fix_item(
        ctx["fix_id"], {"product_id": prod["id"]},
        headers=make_stylist_headers(ctx["stylist_id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_UNAVAILABLE.value)


def test_discontinued_product_not_reserved_after_rejection(api):
    """PRD §3.4: "Selecting reserves one unit of the product (see §2.7), which requires
    available_count of at least one — an empty shelf yields ERR_OUT_OF_STOCK — and
    requires the product to be ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/add_item_requires_product_active
    """
    ctx = setup_styling_fix(prices=[])
    prod = create_product(total_stock=5)
    validate_success(api.discontinue_product(prod["id"], headers=OPS), 200)
    api.add_fix_item(ctx["fix_id"], {"product_id": prod["id"]},
                     headers=make_stylist_headers(ctx["stylist_id"]))
    after = get_product(prod["id"])
    assert after["available_count"] == 5 and after["reserved_count"] == 0, \
        "a rejected selection must not reserve inventory"


# ---------------------------------------- Difficulty: zero-stock boundary on add
def test_add_item_exhausts_then_rejects_at_zero_stock(api):
    """PRD §3.4: "Selecting reserves one unit of the product (see §2.7), which requires
    available_count of at least one — an empty shelf yields ERR_OUT_OF_STOCK — and
    requires the product to be ACTIVE."

    Design: Difficulty/boundary_precision_check/add_item_when_available_zero_out_of_stock
    """
    prod = create_product(total_stock=1)
    stylist = create_stylist()
    client_a = create_active_client(region_code="CA")
    fix_a = schedule_fix(client_a["id"])
    assign_fix(fix_a["id"], stylist["id"])
    # available_count == 1 → selection succeeds and reserves the last unit.
    add_item(fix_a["id"], prod["id"], stylist["id"])
    assert get_product(prod["id"])["available_count"] == 0

    client_b = create_active_client(region_code="CA")
    fix_b = schedule_fix(client_b["id"])
    assign_fix(fix_b["id"], stylist["id"])
    resp = api.add_fix_item(fix_b["id"], {"product_id": prod["id"]},
                            headers=make_stylist_headers(stylist["id"]))
    validate_error(resp, ApiErrorId.ERR_OUT_OF_STOCK.value)


def test_add_item_zero_available_rejected(api):
    """PRD §3.4: "an empty shelf yields ERR_OUT_OF_STOCK".

    Design: Difficulty/boundary_precision_check/add_item_when_available_zero_out_of_stock
    """
    prod = create_product(total_stock=1)
    stylist = create_stylist()
    client_a = create_active_client(region_code="CA")
    fix_a = schedule_fix(client_a["id"])
    assign_fix(fix_a["id"], stylist["id"])
    add_item(fix_a["id"], prod["id"], stylist["id"])  # drains available to 0

    client_b = create_active_client(region_code="CA")
    fix_b = schedule_fix(client_b["id"])
    assign_fix(fix_b["id"], stylist["id"])
    resp = api.add_fix_item(fix_b["id"], {"product_id": prod["id"]},
                            headers=make_stylist_headers(stylist["id"]))
    validate_error(resp, ApiErrorId.ERR_OUT_OF_STOCK.value)


# ----------------------------------------- Difficulty: stylist aggregate capacity
def test_assign_beyond_stylist_capacity_rejected(api):
    """PRD §3.4: "the stylist to have spare capacity — their active_fix_count must be
    strictly less than their max_concurrent_fixes. When the stylist is already at or
    above capacity, the assignment is rejected with ERR_STYLIST_AT_CAPACITY."

    Design: Difficulty/resource_temporal_overlap/stylist_aggregate_capacity_exceeded
    """
    stylist = create_stylist(max_concurrent_fixes=1)
    client_a = create_active_client(region_code="CA")
    fix_a = schedule_fix(client_a["id"])
    assign_fix(fix_a["id"], stylist["id"])  # active_fix_count -> 1 (at capacity)

    client_b = create_active_client(region_code="CA")
    fix_b = schedule_fix(client_b["id"])
    resp = api.assign_fix(fix_b["id"], {"stylist_id": stylist["id"]}, headers=OPS)
    validate_error(resp, ApiErrorId.ERR_STYLIST_AT_CAPACITY.value)


def test_capacity_rejection_leaves_second_fix_requested(api):
    """PRD §3.4: "On success the stylist's active_fix_count is recomputed (rising by
    one to reflect the newly styling fix)."
    PRD §3.4: "When the stylist is already at or above capacity, the assignment is
    rejected with ERR_STYLIST_AT_CAPACITY."

    Design: Difficulty/resource_temporal_overlap/stylist_aggregate_capacity_exceeded
    """
    stylist = create_stylist(max_concurrent_fixes=1)
    client_a = create_active_client(region_code="CA")
    fix_a = schedule_fix(client_a["id"])
    assign_fix(fix_a["id"], stylist["id"])

    client_b = create_active_client(region_code="CA")
    fix_b = schedule_fix(client_b["id"])
    api.assign_fix(fix_b["id"], {"stylist_id": stylist["id"]}, headers=OPS)
    assert get_fix(fix_b["id"])["status"] == "REQUESTED", "rejected assign must not start styling"


# --------------------------------- Difficulty: reserve/release conserves inventory
def test_remove_selected_item_restocks_product(api):
    """PRD §3.4: "A stylist may remove a still-SELECTED item, transitioning it to
    RELEASED and restocking its product (reserved_count down one, available_count up
    one); removal is permitted only while the fix is in STYLING or PREVIEW"

    Design: Difficulty/compensating_invariant/reserve_then_release_conserves_inventory
    """
    ctx = setup_styling_fix(prices=[3000])  # ts 5 → available 4, reserved 1
    validate_success(
        api.remove_fix_item(ctx["fix_id"], ctx["item_ids"][0],
                            headers=make_stylist_headers(ctx["stylist_id"])),
        200,
    )
    prod = get_product(ctx["product_ids"][0])
    assert prod["available_count"] == 5
    assert prod["reserved_count"] == 0
    assert prod["sold_count"] == 0


def test_reserve_then_release_conserves_total_stock(api):
    """PRD §2.7: "At all times, for every product, the invariant available_count +
    reserved_count + sold_count equals total_stock, and no count is ever negative."

    Design: Difficulty/compensating_invariant/reserve_then_release_conserves_inventory
    """
    ctx = setup_styling_fix(prices=[3000])
    assert_inventory_conserved(get_product(ctx["product_ids"][0]))
    api.remove_fix_item(ctx["fix_id"], ctx["item_ids"][0],
                        headers=make_stylist_headers(ctx["stylist_id"]))
    prod = get_product(ctx["product_ids"][0])
    assert_inventory_conserved(prod)
    assert prod["total_stock"] == 5, "total_stock is conserved across reserve/release"


# ------------------------------------------------------- Corner: state guards
def test_checkout_on_styling_fix_rejected(api):
    """PRD §3.6: "A checkout against a fix not in DELIVERED is rejected with
    ERR_FIX_NOT_DELIVERED."

    Design: Corner/state_machines/checkout_on_non_delivered_fix_returns_not_delivered
    """
    ctx = setup_styling_fix(prices=[])
    resp = api.checkout_fix(ctx["fix_id"], {"kept_item_ids": []},
                            headers=make_client_headers(ctx["client_id"]))
    validate_error(resp, ApiErrorId.ERR_FIX_NOT_DELIVERED.value)


def test_ship_already_shipped_fix_rejected(api):
    """PRD §3.5: "Shipping from any state other than PREVIEW is rejected with
    ERR_FIX_NOT_PREVIEW."

    Design: Corner/state_machines/ship_twice_second_returns_not_preview
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000])
    validate_success(api.ship_fix(ctx["fix_id"], headers=OPS), 200)
    resp = api.ship_fix(ctx["fix_id"], headers=OPS)
    validate_error(resp, ApiErrorId.ERR_FIX_NOT_PREVIEW.value)


def test_request_changes_on_cancelled_fix_rejected(api):
    """PRD §3.7: "CLOSED and CANCELLED are the terminal fix states, and any transition
    attempt on a fix already in one of them is rejected with ERR_FIX_TERMINAL."

    Design: Corner/state_machines/request_changes_on_cancelled_fix_returns_terminal
    """
    client = create_active_client(region_code="CA")
    hdr = make_client_headers(client["id"])
    fix = schedule_fix(client["id"])
    validate_success(api.cancel_client(client["id"], headers=hdr), 200)  # fix -> CANCELLED
    resp = api.request_changes(fix["id"], headers=hdr)
    validate_error(resp, ApiErrorId.ERR_FIX_TERMINAL.value)


def test_submit_preview_with_too_few_items_rejected(api):
    """PRD §3.4: "Submission requires the item count to be at least three and at most
    five; a submission with fewer than three items is rejected with
    ERR_FIX_TOO_FEW_ITEMS."

    Design: Corner/state_machines/submit_preview_too_few_items_returns_too_few
    """
    ctx = setup_styling_fix(prices=[3000, 3000])  # only 2 items
    resp = api.submit_preview(ctx["fix_id"], headers=make_stylist_headers(ctx["stylist_id"]))
    validate_error(resp, ApiErrorId.ERR_FIX_TOO_FEW_ITEMS.value)


def test_assign_inactive_stylist_rejected(api):
    """PRD §3.3: "Deactivating a stylist moves status to INACTIVE; an inactive stylist
    can no longer be assigned new fixes, and an assignment attempt against one is
    rejected with ERR_STYLIST_INACTIVE."

    Design: Corner/errors/assign_inactive_stylist_returns_inactive
    """
    stylist = create_stylist()
    validate_success(api.deactivate_stylist(stylist["id"], headers=OPS), 200)
    client = create_active_client(region_code="CA")
    fix = schedule_fix(client["id"])
    resp = api.assign_fix(fix["id"], {"stylist_id": stylist["id"]}, headers=OPS)
    validate_error(resp, ApiErrorId.ERR_STYLIST_INACTIVE.value)
