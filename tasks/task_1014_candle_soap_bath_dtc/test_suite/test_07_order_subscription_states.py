"""Parallel order dimensions, cyclic subscription renewal, bulk-min & empty-bundle boundaries."""
import test_helpers as H


# ==========================================================================
# Queue A — non_linear_state_machine / order_parallel_payment_fulfillment_dimensions
# ==========================================================================
def test_checkout_sets_paid_and_allocated(api):
    """PRD §3.7: "A shopper pays for a `PENDING` order, transitioning it
    `fulfillment=PENDING → fulfillment=ALLOCATED` and `payment=UNPAID → payment=PAID` in one
    step."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=3000, quantity=1, batch_quantity=20)
    assert ctx["order"]["payment_status"] == "PAID"
    assert ctx["order"]["fulfillment_status"] == "ALLOCATED"


def test_fulfill_advances_fulfillment_keeping_payment_paid(api):
    """PRD §3.7: "A `MerchOps` or `PlatformAdmin` operator ships and delivers an `ALLOCATED`,
    `PAID` order, moving it `fulfillment=ALLOCATED → fulfillment=DELIVERED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=3000, quantity=1, batch_quantity=20)
    delivered = H.fulfill(ctx["order"]["id"])
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["payment_status"] == "PAID"


# ==========================================================================
# Queue A — non_linear_state_machine / subscription_renew_cycle
# ==========================================================================
def test_two_renewals_keep_active_and_increment_count(api, merchops_headers):
    """PRD §3.9: "Renewal is an operator-driven cyclic transition (`ACTIVE → ACTIVE`) invoked by
    `MerchOps` or `PlatformAdmin`."
    PRD §3.9: "advances `next_renewal_at` by `cadence_days`; and increments `renewal_count` by
    one."

    Design: Difficulty/non_linear_state_machine/subscription_renew_cycle
    """
    ctx = H.subscription_ctx(list_price_cents=1000, batch_quantity=100, quantity=5, cadence_days=30)
    H.set_clock("2026-08-01T00:00:00Z")
    H.validate_success(api.renew_subscription(ctx["subscription"]["id"], merchops_headers), 200)
    H.set_clock("2026-09-01T00:00:00Z")
    H.validate_success(api.renew_subscription(ctx["subscription"]["id"], merchops_headers), 200)
    sub = H.fetch_subscription(ctx["subscription"]["id"])
    assert sub["status"] == "ACTIVE"
    assert sub["renewal_count"] == 2


def test_each_renewal_reserves_stock_from_batch(api, merchops_headers):
    """PRD §3.9: "reserves the stock (the selected batch's `quantity_reserved` increases by the
    quantity and its `quantity_available` decreases by it, depleting the batch if it reaches
    zero)".

    Design: Difficulty/non_linear_state_machine/subscription_renew_cycle
    """
    ctx = H.subscription_ctx(list_price_cents=1000, batch_quantity=100, quantity=5, cadence_days=30)
    batch_id = ctx["batches"][0]["id"]
    H.set_clock("2026-08-01T00:00:00Z")
    H.validate_success(api.renew_subscription(ctx["subscription"]["id"], merchops_headers), 200)
    H.set_clock("2026-09-01T00:00:00Z")
    H.validate_success(api.renew_subscription(ctx["subscription"]["id"], merchops_headers), 200)
    batch = H.fetch_batch(batch_id)
    assert batch["quantity_reserved"] == 10  # two renewals x qty 5
    H.assert_batch_invariant(batch)


# ==========================================================================
# Queue B — renewal batch selector
# ==========================================================================
def test_renewal_selects_earliest_created_batch(api, merchops_headers):
    """PRD §3.9: "Candidates are ranked by `created_at` ascending — the earliest-produced batch
    first — with `created_at` as the sole ranking key; the resource `id` is never used as a
    tiebreaker. The first candidate after ranking is selected."

    Design: Corner/calculations/renewal_selector_picks_earliest_batch
    """
    ctx = H.subscription_ctx(list_price_cents=1000, batch_quantity=100, quantity=5,
                             cadence_days=30, num_released_batches=2)
    H.set_clock("2026-08-01T00:00:00Z")
    H.validate_success(api.renew_subscription(ctx["subscription"]["id"], merchops_headers), 200)
    assert H.fetch_batch(ctx["batches"][0]["id"])["quantity_reserved"] == 5
    assert H.fetch_batch(ctx["batches"][1]["id"])["quantity_reserved"] == 0


def test_renew_no_eligible_batch_fails_without_advancing(api, merchops_headers):
    """PRD §3.9: "If the candidate set is empty, the renewal fails with `ERR_NO_ELIGIBLE_BATCH`
    and neither `next_renewal_at` nor `renewal_count` is advanced."

    Design: Corner/calculations/renew_no_eligible_batch_fallback
    """
    ctx = H.subscription_ctx(list_price_cents=1000, batch_quantity=3, quantity=5, cadence_days=30)
    H.set_clock("2026-08-01T00:00:00Z")
    H.validate_error(api.renew_subscription(ctx["subscription"]["id"], merchops_headers),
                     H.ApiErrorId.ERR_NO_ELIGIBLE_BATCH)
    assert H.fetch_subscription(ctx["subscription"]["id"])["renewal_count"] == 0


# ==========================================================================
# Queue B — subscription terminal lockdown
# ==========================================================================
def test_cancel_already_cancelled_subscription_rejected(api):
    """PRD §3.9: "cancelling moves it to `CANCELLED` from either `ACTIVE` or `PAUSED`.
    Cancellation is terminal."
    PRD §2.11: "Then whether the target resource is in a valid state for the requested transition
    (`ERR_INVALID_STATE` and its specific siblings `ERR_BATCH_NOT_RELEASED`, `ERR_ORDER_NOT_EDITABLE`,
    `ERR_ORDER_NOT_DELIVERED`, `ERR_SUBSCRIPTION_NOT_DUE`)."

    Design: Corner/state_machines/cancel_cancelled_subscription_terminal_lockdown
    """
    sku = H.new_sku(H.new_product(product_type="SOAP")["id"], list_price_cents=900)
    customer = H.new_customer()
    ch = H.make_customer_headers(customer["id"])
    sub = H.validate_success(
        api.create_subscription(customer["id"], H.create_subscription_payload(sku["id"], quantity=2), ch), 201)
    H.validate_success(api.cancel_subscription(sub["id"], ch), 200)
    H.validate_error(api.cancel_subscription(sub["id"], ch), H.ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Queue A — boundary_precision_check / bulk_min_quantity_at_checkout
# ==========================================================================
def test_bulk_order_below_minimum_rejected_at_checkout(api):
    """PRD §3.7: "If the `order_type` is `BULK`, the order's `total_quantity` must be at least 50
    units; a bulk order below that floor is rejected with `ERR_BULK_MIN_NOT_MET`."

    Design: Difficulty/boundary_precision_check/bulk_min_quantity_at_checkout
    """
    ctx = H.reserved_order(product_type="SOAP", list_price_cents=100, quantity=49,
                           batch_quantity=100, order_type="BULK")
    version = H.get_order_version(ctx["order"]["id"], ctx["customer"]["id"])
    resp = api.checkout_order(ctx["order"]["id"], version, H.make_customer_headers(ctx["customer"]["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_BULK_MIN_NOT_MET)
    assert H.fetch_order(ctx["order"]["id"])["payment_status"] == "UNPAID"


def test_bulk_order_at_minimum_checks_out(api):
    """PRD §3.7: "If the `order_type` is `BULK`, the order's `total_quantity` must be at least 50
    units; a bulk order below that floor is rejected with `ERR_BULK_MIN_NOT_MET`."

    Design: Difficulty/boundary_precision_check/bulk_min_quantity_at_checkout
    """
    ctx = H.reserved_order(product_type="SOAP", list_price_cents=100, quantity=50,
                           batch_quantity=100, order_type="BULK")
    order = H.checkout(ctx["order"]["id"], ctx["customer"]["id"])
    assert order["payment_status"] == "PAID"
    assert order["fulfillment_status"] == "ALLOCATED"


# ==========================================================================
# Queue A — boundary_precision_check / empty_bundle_activate_zero_items
# ==========================================================================
def test_empty_bundle_activation_rejected(api, merchops_headers):
    """PRD §3.4: "activation requires the bundle to contain at least one item, and activating an
    empty bundle is rejected with `ERR_EMPTY_BUNDLE`."

    Design: Difficulty/boundary_precision_check/empty_bundle_activate_zero_items
    """
    bundle = H.new_bundle(items=[], bundle_price_cents=5000, title="Empty Gift")
    H.validate_error(api.activate_bundle(bundle["id"], merchops_headers), H.ApiErrorId.ERR_EMPTY_BUNDLE)


def test_empty_bundle_stays_draft_after_rejected_activation(api, merchops_headers):
    """PRD §3.4: "A newly created bundle starts in `DRAFT`. Activating a bundle moves it
    `DRAFT → ACTIVE`, after which it is publicly purchasable; activation requires the bundle to
    contain at least one item, and activating an empty bundle is rejected with
    `ERR_EMPTY_BUNDLE`."

    Design: Difficulty/boundary_precision_check/empty_bundle_activate_zero_items
    """
    bundle = H.new_bundle(items=[], bundle_price_cents=5000, title="Empty Gift")
    api.activate_bundle(bundle["id"], merchops_headers)
    assert H.validate_success(api.get_bundle(bundle["id"], merchops_headers), 200)["status"] == "DRAFT"
