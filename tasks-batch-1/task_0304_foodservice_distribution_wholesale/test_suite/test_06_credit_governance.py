"""Credit governance and approve-credit guards: validation precedence, OCC stale version,
lot freshness, return-approve gating, over-credit-limit release block, customer closure,
and the compensating cancel invariants.

Covers difficulty priority_pair_validation_conflict (auth vs state), cross_entity
(return approve), resource_temporal_overlap (lot freshness), compensating_invariant,
plus corner validations / state_machines / cross_cutting (OCC).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_catalog, setup_base, create_product, add_price_tier, receive_lot, create_customer,
    create_draft_order_with_line, create_submitted_order, create_approved_order,
    create_delivered_order, set_clock, get_customer_version, approve_credit_payload,
    TEST_USERS,
)

CREDIT = TEST_USERS["credit_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_op_headers"]
ADMIN = TEST_USERS["distributor_admin_headers"]


# ─── Validation precedence: auth beats state ───────────────────────────────

def test_forbidden_role_beats_invalid_state(api):
    """PRD §3.3: "Authentication comes first ... then role authorization
    (`ERR_FORBIDDEN_FOR_ROLE`) ... Only after those four foundational checks does the
    system apply the state check that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."
    PRD §4 endpoint table: approve-credit is authorized for CreditManager only.

    A SalesRep (not permitted) calls approve-credit on a DRAFT (state-ineligible) order;
    auth precedence means ERR_FORBIDDEN_FOR_ROLE is returned, not ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_auth_vs_state
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1)
    cust_v = get_customer_version(cat["customer"]["id"])

    res = api.approve_credit(order["id"], approve_credit_payload(cust_v), SALES)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


def test_forbidden_role_beats_state_second_role(api):
    """PRD §3.3: "then role authorization (`ERR_FORBIDDEN_FOR_ROLE`) ... Only after those
    four foundational checks does the system apply the state check that the target resource
    is in a state from which the requested transition is defined (`ERR_INVALID_STATE`)."
    PRD §4 endpoint table: approve-credit is authorized for CreditManager only.

    Second test of auth-over-state precedence with a different unauthorized role: a
    WarehouseOp calling approve-credit on a DRAFT order is rejected ERR_FORBIDDEN_FOR_ROLE.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_auth_vs_state
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1)
    cust_v = get_customer_version(cat["customer"]["id"])

    res = api.approve_credit(order["id"], approve_credit_payload(cust_v), WAREHOUSE)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


# ─── OCC stale customer version ────────────────────────────────────────────

def test_stale_customer_version_after_sibling_approval_rejected(api):
    """PRD §2.7: "At approval time the server compares `expected_customer_version` against
    the customer's current `version`. If they do not match ... the approval is rejected
    with `ERR_STALE_CUSTOMER_VERSION` and HTTP status 412."
    PRD §2.7: "Approving a different order for the same customer debits that customer's
    balance and advances the customer's `version`; a later approval still carrying the
    pre-debit `expected_customer_version` is therefore working from a balance that has
    since moved."

    Read customer at version V; approving sibling O1 with V advances version to V+1;
    approving O2 still carrying the stale V is rejected ERR_STALE_CUSTOMER_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_customer_version_after_sibling_approval
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    o1, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                   lines=[(cat["product"]["id"], "CASE", 1)],
                                   delivery_date="2026-06-17T00:00:00Z")
    o2, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                   lines=[(cat["product"]["id"], "CASE", 1)],
                                   delivery_date="2026-06-24T00:00:00Z")

    stale_v = get_customer_version(cat["customer"]["id"])
    validate_success(
        api.approve_credit(o1["id"], approve_credit_payload(stale_v), CREDIT), 200)

    res = api.approve_credit(o2["id"], approve_credit_payload(stale_v), CREDIT)
    validate_error(res, "ERR_STALE_CUSTOMER_VERSION")


def test_stale_customer_version_minus_one_rejected(api):
    """PRD §2.7: "At approval time the server compares `expected_customer_version` against
    the customer's current `version`. If they do not match ... the approval is rejected
    with `ERR_STALE_CUSTOMER_VERSION` and HTTP status 412."

    A deliberate stale approve-credit carrying expected_customer_version one below the
    customer's current version is rejected ERR_STALE_CUSTOMER_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_customer_version_negative_minus_one
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                      lines=[(cat["product"]["id"], "CASE", 1)])
    cust_v = get_customer_version(cat["customer"]["id"])

    res = api.approve_credit(order["id"], approve_credit_payload(cust_v - 1), CREDIT)
    validate_error(res, "ERR_STALE_CUSTOMER_VERSION")


# ─── Lot freshness containment ─────────────────────────────────────────────

def test_perishable_lot_expiring_before_delivery_blocks_approval(api):
    """PRD §3.4: "for every perishable line, that at least one eligible lot exists whose
    freshness window still contains the delivery instant — that is, whose `expires_on` is
    strictly after `requested_delivery_date`. If for some perishable line every candidate
    lot, across both the primary product and any substitute, has an `expires_on` at or
    before `requested_delivery_date`, the approval is rejected with
    `ERR_LOT_EXPIRES_BEFORE_DELIVERY`."

    A perishable product's only lot expires 2026-06-16 while delivery is 2026-06-17, so the
    delivery instant is not within the freshness window: approve-credit is rejected
    ERR_LOT_EXPIRES_BEFORE_DELIVERY (409).

    Design: Difficulty/resource_temporal_overlap/lot_freshness_window_containment_conflict
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True, perishable=True,
                        tiers=((1, 2400),), on_hand_splits=24,
                        lot_expires_on="2026-06-16T00:00:00Z", credit_limit_cents=100000)
    order, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                      lines=[(cat["product"]["id"], "CASE", 1)])
    cust_v = get_customer_version(cat["customer"]["id"])

    res = api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT)
    validate_error(res, "ERR_LOT_EXPIRES_BEFORE_DELIVERY")


def test_perishable_lot_expiring_on_delivery_blocks_approval(api):
    """PRD §3.4: "whose `expires_on` is strictly after `requested_delivery_date`. If for
    some perishable line every candidate lot ... has an `expires_on` at or before
    `requested_delivery_date`, the approval is rejected with
    `ERR_LOT_EXPIRES_BEFORE_DELIVERY`."

    Second test of the freshness-window containment: a lot expiring exactly on the delivery
    date 2026-06-17 (the "at" side of "at or before") also fails, since eligibility requires
    expires_on strictly after the delivery date.

    Design: Difficulty/resource_temporal_overlap/lot_freshness_window_containment_conflict
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True, perishable=True,
                        tiers=((1, 2400),), on_hand_splits=24,
                        lot_expires_on="2026-06-17T00:00:00Z", credit_limit_cents=100000)
    order, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                      lines=[(cat["product"]["id"], "CASE", 1)])
    cust_v = get_customer_version(cat["customer"]["id"])

    res = api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT)
    validate_error(res, "ERR_LOT_EXPIRES_BEFORE_DELIVERY")


# ─── Return approve gated on order delivered ───────────────────────────────

def test_return_approve_blocked_until_order_delivered(api):
    """PRD §3.7: "Approval requires that the return is in `REQUESTED`, or `ERR_INVALID_STATE`;
    that the referenced order's `fulfillment_status` is `DELIVERED`, or
    `ERR_ORDER_NOT_DELIVERED`."

    A return is requested against a line of an order that is only SUBMITTED+APPROVED (not
    delivered); approving the return fails ERR_ORDER_NOT_DELIVERED.

    Design: Difficulty/cross_entity_state_dependency/return_approve_blocked_until_order_delivered
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, lines = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                         lines=[(cat["product"]["id"], "CASE", 1)])
    line = lines[0]
    ret = validate_success(api.create_return(
        {"customer_id": cat["customer"]["id"], "order_id": order["id"],
         "order_line_id": line["id"], "reason": "DAMAGED", "return_splits": 1}, CREDIT), 201)

    res = api.approve_return(ret["id"], CREDIT)
    validate_error(res, "ERR_ORDER_NOT_DELIVERED")


def test_return_approve_blocked_when_order_still_picking(api):
    """PRD §3.7: "that the referenced order's `fulfillment_status` is `DELIVERED`, or
    `ERR_ORDER_NOT_DELIVERED`."

    Second test of the Return->Order delivered dependency: with the order advanced only to
    PICKING (start-pick run, not yet loaded/POD'd), approving a return still fails
    ERR_ORDER_NOT_DELIVERED.

    Design: Difficulty/cross_entity_state_dependency/return_approve_blocked_until_order_delivered
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, lines = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                         lines=[(cat["product"]["id"], "CASE", 1)])
    line = lines[0]
    validate_success(api.start_pick(order["id"], WAREHOUSE), 200)

    ret = validate_success(api.create_return(
        {"customer_id": cat["customer"]["id"], "order_id": order["id"],
         "order_line_id": line["id"], "reason": "DAMAGED", "return_splits": 1}, CREDIT), 201)
    res = api.approve_return(ret["id"], CREDIT)
    validate_error(res, "ERR_ORDER_NOT_DELIVERED")


# ─── Over-credit-limit blocks release ──────────────────────────────────────

def test_over_credit_limit_blocks_release_after_tightening(api):
    """PRD §3.5: "Release is only permitted while the customer's `ar_balance_cents` is at
    most its `credit_limit_cents`; a release attempted while the balance still exceeds the
    limit is rejected with `ERR_OVER_CREDIT_LIMIT`."
    PRD §3.5: "any customer currently `ACTIVE` whose `ar_balance_cents` exceeds its
    `credit_limit_cents` is moved to `CREDIT_HOLD`."

    Deliver a 2-case order (ar 4800, limit 5000); tighten limit to 3000; advancing the
    clock sweeps the customer to CREDIT_HOLD; credit-release while 4800 > 3000 is rejected
    ERR_OVER_CREDIT_LIMIT (409).

    Design: Corner/validations/over_credit_limit_blocks_release_after_limit_tightened
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=5000)
    order, lines, ship = create_delivered_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 2)], pod_signature="Sig")

    validate_success(api.adjust_credit_limit(
        cat["customer"]["id"], {"credit_limit_cents": 3000}, CREDIT), 200)
    set_clock(cat["distributor"]["id"], "2026-06-15T13:00:00Z")

    cust = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust["ar_status"] == "CREDIT_HOLD"

    res = api.credit_release(cat["customer"]["id"], CREDIT)
    validate_error(res, "ERR_OVER_CREDIT_LIMIT")


# ─── Customer closure preconditions ────────────────────────────────────────

def test_close_customer_with_open_order_rejected(api):
    """PRD §3.5: "no order for the customer is in `fulfillment_status` `SUBMITTED`,
    `PICKING`, or `LOADED`, or it is rejected with `ERR_CUSTOMER_HAS_OPEN_ORDERS`."

    Closing a customer with a SUBMITTED (unapproved, ar_balance 0) order is rejected
    ERR_CUSTOMER_HAS_OPEN_ORDERS (409).

    Design: Corner/state_machines/close_customer_with_open_order_returns_has_open_orders
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                           lines=[(cat["product"]["id"], "CASE", 1)])

    res = api.close_customer(cat["customer"]["id"], ADMIN)
    validate_error(res, "ERR_CUSTOMER_HAS_OPEN_ORDERS")


def test_close_customer_with_outstanding_ar_rejected(api):
    """PRD §3.5: "Closure requires that the customer's `ar_balance_cents` is exactly zero,
    or it is rejected with `ERR_CUSTOMER_NOT_SETTLED`."

    A customer whose delivered order left ar_balance 4800 (>0, order settled so no open
    orders) is rejected ERR_CUSTOMER_NOT_SETTLED (409) on close.

    Design: Corner/state_machines/close_customer_with_outstanding_ar_returns_not_settled
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    create_delivered_order(cat["customer"]["id"], cat["product"]["id"],
                           lines=[(cat["product"]["id"], "CASE", 2)], pod_signature="Sig")

    res = api.close_customer(cat["customer"]["id"], ADMIN)
    validate_error(res, "ERR_CUSTOMER_NOT_SETTLED")


# ─── Compensating invariants: cancel restores AR and lot reservation ───────

def test_cancel_approved_order_restores_ar_balance(api):
    """PRD §3.6: "If the order's `credit_status` was `APPROVED`, cancellation releases
    every reservation ... and decreases the customer's `ar_balance_cents` by the order's
    `order_total_cents`, then resets `credit_status` to `PENDING`; accounts-receivable and
    reservations must net back to zero."

    Approve a CASE-2 order (total 4800) -> ar_balance 4800; cancel while SUBMITTED+APPROVED
    restores ar_balance to its pre-approval value (0).

    Design: Difficulty/compensating_invariant/cancel_approved_order_restores_ar_balance_invariant
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    lot = cat["lot"]
    order, _ = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                     lines=[(cat["product"]["id"], "CASE", 2)])

    cancelled = validate_success(api.cancel_order(order["id"], SALES), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"

    cust_after = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust_after["ar_balance_cents"] == 0

    lot_after = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_after["reserved_splits"] == 0


def test_cancel_approved_order_restores_lot_reservation(api):
    """PRD §3.6: "cancellation releases every reservation (each allocated line's lot has its
    `reserved_splits` decremented by that line's `allocated_splits`)."

    Approve a CASE-2 order reserving 24 splits (lot available 24->0); cancelling releases
    them, returning the lot to reserved 0 / on_hand 24 (available back to 24).

    Design: Difficulty/compensating_invariant/cancel_approved_order_restores_lot_reservation_invariant
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    lot = cat["lot"]
    order, _ = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                     lines=[(cat["product"]["id"], "CASE", 2)])

    lot_reserved = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_reserved["reserved_splits"] == 24

    cancelled = validate_success(api.cancel_order(order["id"], SALES), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"

    lot_after = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_after["reserved_splits"] == 0
    assert lot_after["on_hand_splits"] == 24


def test_cancel_approved_order_restores_ar_second_quantity(api):
    """PRD §3.6: "decreases the customer's `ar_balance_cents` by the order's
    `order_total_cents`, then resets `credit_status` to `PENDING`; accounts-receivable and
    reservations must net back to zero."

    Second test of the AR-conservation invariant with a different total: a CASE-1 order
    (total 2400) debits then on cancel restores ar_balance to 0 and resets credit_status.

    Design: Difficulty/compensating_invariant/cancel_approved_order_restores_ar_balance_invariant
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    order, _ = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                     lines=[(cat["product"]["id"], "CASE", 1)])

    cust_before = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust_before["ar_balance_cents"] == 2400

    cancelled = validate_success(api.cancel_order(order["id"], SALES), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["credit_status"] == "PENDING"

    cust_after = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust_after["ar_balance_cents"] == 0


def test_cancel_approved_order_restores_lot_second_quantity(api):
    """PRD §3.6: "cancellation releases every reservation (each allocated line's lot has its
    `reserved_splits` decremented by that line's `allocated_splits`)."

    Second test of the inventory-capacity invariant: a CASE-1 order reserves 12 splits;
    cancelling releases them (reserved back to 0, on_hand unchanged at 24).

    Design: Difficulty/compensating_invariant/cancel_approved_order_restores_lot_reservation_invariant
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    lot = cat["lot"]
    order, _ = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                     lines=[(cat["product"]["id"], "CASE", 1)])

    lot_reserved = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_reserved["reserved_splits"] == 12

    validate_success(api.cancel_order(order["id"], SALES), 200)
    lot_after = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_after["reserved_splits"] == 0
    assert lot_after["on_hand_splits"] == 24
