"""Validation-priority conflicts and cross-entity state dependencies on add-line / renew."""
import test_helpers as H


# ==========================================================================
# Queue A — priority_pair_validation_conflict / state_beats_safety_on_add_line
# ==========================================================================
def _candle_unreleased_order():
    """CANDLE (safety-required) sku with a CREATED, unlabeled, unreleased batch + PENDING order."""
    product = H.new_product(product_type="CANDLE")
    sku = H.new_sku(product["id"], list_price_cents=4000, size="LARGE", scent="Smoke")
    batch = H.new_batch(sku["id"], quantity_produced=10)  # left CREATED
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    return sku, batch, customer, order


def test_state_error_precedes_safety_error_on_add_line(api):
    """PRD §3.6: "The batch a line reserves against must itself be sellable: if the chosen batch
    is not in `RELEASED` status the line is rejected with `ERR_BATCH_NOT_RELEASED`. Two domain
    guards then apply, in this order. First, safety labeling: if the sku's `requires_safety_label`
    is true, the chosen batch must have `is_safety_labeled` true, otherwise the line is rejected
    with `ERR_SAFETY_LABEL_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_add_line
    """
    sku, batch, customer, order = _candle_unreleased_order()
    resp = api.add_line(order["id"], H.create_line_payload(sku["id"], batch["id"], 1),
                        H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_BATCH_NOT_RELEASED)


def test_rejected_add_line_makes_no_reservation(api):
    """PRD §2.11: "When several checks could reject the same request, they are evaluated in a
    fixed priority order so that the returned error is deterministic."
    PRD §3.2: "On creation the batch starts in `CREATED` status with `is_safety_labeled` false,
    `quantity_available` equal to `quantity_produced`, and its `quantity_reserved`,
    `quantity_shipped`, and `quantity_recalled` counters at zero."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_add_line
    """
    sku, batch, customer, order = _candle_unreleased_order()
    api.add_line(order["id"], H.create_line_payload(sku["id"], batch["id"], 1),
                 H.make_customer_headers(customer["id"]))
    fresh = H.fetch_batch(batch["id"])
    assert fresh["quantity_reserved"] == 0
    assert fresh["quantity_available"] == fresh["quantity_produced"] == 10


# ==========================================================================
# Queue A — priority_pair_validation_conflict / temporal_beats_fiscal_on_add_line
# ==========================================================================
def _ended_drop_low_stock_order():
    """Soap sku exclusive to an ENDED drop, released batch with only 5 available, PENDING order."""
    H.set_clock("2026-07-01T00:00:00Z")
    product = H.new_product(product_type="SOAP")
    sku = H.new_sku(product["id"], list_price_cents=1000, scent="Jasmine")
    batch = H.new_batch(sku["id"], quantity_produced=5)
    H.release_batch(batch["id"])
    H.new_drop(listings=[{"sku_id": sku["id"], "drop_price_cents": 900, "is_exclusive": True}],
               starts_at="2026-07-05T00:00:00Z", ends_at="2026-07-10T00:00:00Z", season="SUMMER_2026", title="Flash")
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    H.set_clock("2026-07-20T00:00:00Z")  # drop now ENDED
    return sku, batch, customer, order


def test_drop_liveness_error_precedes_inventory_error(api):
    """PRD §3.6: "Second, drop exclusivity: if the sku is exclusive to a drop, that drop must be
    `LIVE` at the current logical-clock instant for the line to be added, otherwise it is
    rejected with `ERR_DROP_NOT_LIVE`. Finally, inventory sufficiency: the batch's
    `quantity_available` must be at least the requested `quantity`, otherwise the line is rejected
    with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_add_line
    """
    sku, batch, customer, order = _ended_drop_low_stock_order()
    resp = api.add_line(order["id"], H.create_line_payload(sku["id"], batch["id"], 10),
                        H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_DROP_NOT_LIVE)


def test_temporal_rejection_leaves_inventory_untouched(api):
    """PRD §2.11: "Then domain safety and temporal rules — safety-label enforcement
    (`ERR_SAFETY_LABEL_REQUIRED`), drop-liveness (`ERR_DROP_NOT_LIVE`), and
    customer-active-for-renewal (`ERR_CUSTOMER_SUSPENDED`)."
    PRD §2.11: "Then fiscal and quantity floors — inventory sufficiency and the bulk-order minimum
    (`ERR_INSUFFICIENT_INVENTORY`, `ERR_BULK_MIN_NOT_MET`)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_add_line
    """
    sku, batch, customer, order = _ended_drop_low_stock_order()
    api.add_line(order["id"], H.create_line_payload(sku["id"], batch["id"], 10),
                 H.make_customer_headers(customer["id"]))
    assert H.fetch_batch(batch["id"])["quantity_available"] == 5


# ==========================================================================
# Queue A — cross_entity_state_dependency / add_line_requires_batch_released
# ==========================================================================
def test_add_line_requires_batch_released(api):
    """PRD §3.6: "The batch a line reserves against must itself be sellable: if the chosen batch
    is not in `RELEASED` status the line is rejected with `ERR_BATCH_NOT_RELEASED`."

    Design: Difficulty/cross_entity_state_dependency/add_line_requires_batch_released
    """
    sku = H.new_sku(H.new_product(product_type="SOAP")["id"], list_price_cents=1000, scent="Yuzu")
    batch = H.new_batch(sku["id"], quantity_produced=50)  # left CREATED
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    resp = api.add_line(order["id"], H.create_line_payload(sku["id"], batch["id"], 1),
                        H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_BATCH_NOT_RELEASED)


def test_add_line_succeeds_once_batch_released(api):
    """PRD §3.2: "A release action makes the batch sellable inventory: it can be released either
    from `CREATED` directly or from `LABELED`, moving it to `RELEASED`."
    PRD §3.6: "the line begins in `RESERVED` status."

    Design: Difficulty/cross_entity_state_dependency/add_line_requires_batch_released
    """
    sku = H.new_sku(H.new_product(product_type="SOAP")["id"], list_price_cents=1000, scent="Yuzu")
    batch = H.new_batch(sku["id"], quantity_produced=50)
    H.release_batch(batch["id"])
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    line = H.validate_success(
        api.add_line(order["id"], H.create_line_payload(sku["id"], batch["id"], 1),
                     H.make_customer_headers(customer["id"])), 201)
    assert line["status"] == "RESERVED"


# ==========================================================================
# Queue A — cross_entity_state_dependency / renew_requires_customer_active
# ==========================================================================
def test_renew_blocked_for_suspended_customer(api, merchops_headers):
    """PRD §3.9: "requires the owning customer to be `ACTIVE` rather than `SUSPENDED` (a suspended
    customer's renewal is rejected with `ERR_CUSTOMER_SUSPENDED`)".

    Design: Difficulty/cross_entity_state_dependency/renew_requires_customer_active
    """
    ctx = H.subscription_ctx(list_price_cents=1000, batch_quantity=100, quantity=5, cadence_days=30)
    H.suspend_customer(ctx["customer"]["id"])
    H.set_clock("2026-08-01T00:00:00Z")  # renewal now due
    H.validate_error(api.renew_subscription(ctx["subscription"]["id"], merchops_headers),
                     H.ApiErrorId.ERR_CUSTOMER_SUSPENDED)


def test_blocked_renew_does_not_advance_subscription(api, merchops_headers):
    """PRD §3.9: "On success the renewal creates a `RETAIL` order for the customer containing a
    single `RESERVED` line for the subscription's sku, batch, and quantity"
    PRD §3.9: "advances `next_renewal_at` by `cadence_days`; and increments `renewal_count` by
    one."

    Design: Difficulty/cross_entity_state_dependency/renew_requires_customer_active
    """
    ctx = H.subscription_ctx(list_price_cents=1000, batch_quantity=100, quantity=5, cadence_days=30)
    original_next = ctx["subscription"]["next_renewal_at"]
    H.suspend_customer(ctx["customer"]["id"])
    H.set_clock("2026-08-01T00:00:00Z")
    api.renew_subscription(ctx["subscription"]["id"], merchops_headers)
    sub = H.fetch_subscription(ctx["subscription"]["id"])
    assert sub["renewal_count"] == 0
    assert sub["status"] == "ACTIVE"
    assert sub["next_renewal_at"] == original_next
