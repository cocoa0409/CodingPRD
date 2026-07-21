"""Batch lifecycle transitions, recall cascade, order-cancel cascade, unit conservation."""
import test_helpers as H


# ==========================================================================
# Queue B — batch state machine
# ==========================================================================
def test_batch_label_then_release_valid(api, merchops_headers):
    """PRD §3.2: "From `CREATED`, a labeling action stamps the batch as safety-labeled, moving
    it `CREATED → LABELED` and setting `is_safety_labeled` to true. A release action makes the
    batch sellable inventory: it can be released either from `CREATED` directly or from
    `LABELED`, moving it to `RELEASED`."

    Design: Corner/state_machines/batch_label_then_release_valid
    """
    cat_sku = H.new_sku(H.new_product(product_type="SOAP")["id"], list_price_cents=1000)
    batch = H.new_batch(cat_sku["id"], quantity_produced=10)
    labeled = H.validate_success(api.label_batch(batch["id"], merchops_headers), 200)
    assert labeled["is_safety_labeled"] is True
    assert labeled["status"] == "LABELED"
    released = H.validate_success(api.release_batch(batch["id"], merchops_headers), 200)
    assert released["status"] == "RELEASED"


def test_release_recalled_batch_invalid(api, merchops_headers):
    """PRD §3.10: "A batch can be recalled only from `RELEASED` or `DEPLETED`; the recall moves
    it to the terminal `RECALLED` status, sets `quantity_recalled` equal to `quantity_produced`,
    and drives `quantity_available` to zero."
    PRD §2.11: "Then whether the target resource is in a valid state for the requested transition
    (`ERR_INVALID_STATE` and its specific siblings `ERR_BATCH_NOT_RELEASED`, `ERR_ORDER_NOT_EDITABLE`,
    `ERR_ORDER_NOT_DELIVERED`, `ERR_SUBSCRIPTION_NOT_DUE`)."

    Design: Corner/state_machines/release_recalled_batch_invalid
    """
    cat = H.released_catalog(product_type="SOAP", list_price_cents=1000, quantity=10)
    recalled = H.validate_success(api.recall_batch(cat["batch"]["id"], merchops_headers), 200)
    assert recalled["status"] == "RECALLED"
    H.validate_error(api.release_batch(cat["batch"]["id"], merchops_headers),
                     H.ApiErrorId.ERR_INVALID_STATE)
    assert H.fetch_batch(cat["batch"]["id"])["status"] == "RECALLED"


def test_label_already_labeled_batch_rejected(api, merchops_headers):
    """PRD §3.2: "From `CREATED`, a labeling action stamps the batch as safety-labeled, moving
    it `CREATED → LABELED` and setting `is_safety_labeled` to true."
    PRD §2.11: "Then whether the target resource is in a valid state for the requested transition
    (`ERR_INVALID_STATE` and its specific siblings `ERR_BATCH_NOT_RELEASED`, `ERR_ORDER_NOT_EDITABLE`,
    `ERR_ORDER_NOT_DELIVERED`, `ERR_SUBSCRIPTION_NOT_DUE`)."

    Design: Corner/state_machines/label_already_labeled_batch_idempotency
    """
    sku = H.new_sku(H.new_product(product_type="CANDLE")["id"], list_price_cents=2000)
    batch = H.new_batch(sku["id"], quantity_produced=10)
    H.label_batch(batch["id"])
    H.validate_error(api.label_batch(batch["id"], merchops_headers),
                     H.ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Queue A — transitive_cascade / batch_recall_depth4_cascade
# ==========================================================================
def test_recall_voids_line_and_cancels_order(api, merchops_headers):
    """PRD §3.10: "every order line whose `batch_id` is the recalled batch and whose status is
    `RESERVED` or `SHIPPED`, and whose parent order's `fulfillment_status` is neither `CANCELLED`
    nor `RETURNED`, is voided to `VOIDED_RECALL`, and its reserved or shipped units are released
    from the batch."
    PRD §3.10: "Then, for each affected order, if all of its lines are now `VOIDED_RECALL`, the
    order's `fulfillment_status` becomes `CANCELLED`, and if its `payment_status` was `PAID` it
    becomes `REFUNDED`."

    Design: Difficulty/transitive_cascade/batch_recall_depth4_cascade
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=500, quantity=10, batch_quantity=100)
    H.validate_success(api.recall_batch(ctx["batch"]["id"], merchops_headers), 200)
    assert H.fetch_batch(ctx["batch"]["id"])["status"] == "RECALLED"
    assert H.fetch_order_line(ctx["line"]["id"])["status"] == "VOIDED_RECALL"
    order = H.fetch_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "CANCELLED"


def test_recall_refunds_and_reverses_provisional_loyalty(api, merchops_headers):
    """PRD §3.10: "Finally, posted loyalty for the voided lines is reversed: for an order that
    had posted provisional points (it was `ALLOCATED`) or awarded points (it was `DELIVERED`),
    the customer's `loyalty_points_balance` is reduced by the sum, over the voided lines, of the
    floor of each voided line's `line_subtotal_cents` divided by 100. When a recall voids every
    line of an order, that reversal equals the order's original `provisional_points`."

    Design: Difficulty/transitive_cascade/batch_recall_depth4_cascade
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=500, quantity=10, batch_quantity=100)
    # After checkout: provisional_points = floor(5000/100) = 50, balance = 50.
    assert H.fetch_customer(ctx["customer"]["id"])["loyalty_points_balance"] == 50
    H.validate_success(api.recall_batch(ctx["batch"]["id"], merchops_headers), 200)
    order = H.fetch_order(ctx["order"]["id"])
    assert order["payment_status"] == "REFUNDED"
    assert H.fetch_customer(ctx["customer"]["id"])["loyalty_points_balance"] == 0


# ==========================================================================
# Queue A — transitive_cascade / order_cancel_depth3_cascade
# ==========================================================================
def test_cancel_releases_inventory_and_undepletes_batch(api):
    """PRD §3.7: "Cancellation releases inventory and unwinds loyalty: each `RESERVED` line
    becomes `RELEASED`; per released line, the batch's `quantity_reserved` decreases by the line
    `quantity` and its `quantity_available` increases by the same amount; and any batch that was
    `DEPLETED` and now has availability above zero transitions back to `RELEASED`."

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=100, quantity=100, batch_quantity=100)
    # Reserving all 100 depletes the batch.
    assert H.fetch_batch(ctx["batch"]["id"])["status"] == "DEPLETED"
    H.cancel_order(ctx["order"]["id"], ctx["customer"]["id"])
    batch = H.fetch_batch(ctx["batch"]["id"])
    assert batch["quantity_reserved"] == 0
    assert batch["quantity_available"] == 100
    assert batch["status"] == "RELEASED"
    H.assert_batch_invariant(batch)


def test_cancel_paid_order_refunds_and_cancels(api):
    """PRD §3.7: "A `PENDING` or `ALLOCATED` order may be cancelled — by the owning shopper, or by
    a `MerchOps` or `PlatformAdmin` operator — moving its fulfillment to `CANCELLED`."
    PRD §3.7: "If the order's `payment_status` was `PAID`, it becomes `REFUNDED` and the customer's
    `loyalty_points_balance` is reduced by the order's `provisional_points`, reversing the
    provisional credit."

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=100, quantity=100, batch_quantity=100)
    cancelled = H.cancel_order(ctx["order"]["id"], ctx["customer"]["id"])
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"


# ==========================================================================
# Queue A — compensating_invariant / batch_unit_conservation_reserve_cancel
# ==========================================================================
def test_reservation_holds_availability_invariant(api):
    """PRD §2.6: "Availability is always the produced quantity minus reserved, minus shipped,
    minus recalled. The following invariant holds at all times: the produced quantity equals
    available plus reserved plus shipped plus recalled."

    Design: Difficulty/compensating_invariant/batch_unit_conservation_reserve_cancel
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=200, quantity=30, batch_quantity=100)
    batch = H.fetch_batch(ctx["batch"]["id"])
    assert batch["quantity_reserved"] == 30
    assert batch["quantity_available"] == 70
    H.assert_batch_invariant(batch)


def test_reserve_then_cancel_conserves_all_units(api):
    """PRD §2.6: "The following invariant holds at all times: the produced quantity equals
    available plus reserved plus shipped plus recalled."
    PRD §3.7: "per released line, the batch's `quantity_reserved` decreases by the line
    `quantity` and its `quantity_available` increases by the same amount".

    Design: Difficulty/compensating_invariant/batch_unit_conservation_reserve_cancel
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=200, quantity=30, batch_quantity=100)
    H.cancel_order(ctx["order"]["id"], ctx["customer"]["id"])
    batch = H.fetch_batch(ctx["batch"]["id"])
    assert batch["quantity_produced"] == 100
    assert batch["quantity_reserved"] == 0
    assert batch["quantity_shipped"] == 0
    assert batch["quantity_recalled"] == 0
    assert batch["quantity_available"] == 100
    H.assert_batch_invariant(batch)
