"""State-machine depth and breadth: the cyclic re-roast loop, the parallel Order
fulfillment/billing dimensions, plus queue-B state transitions (initial states,
invalid transitions, terminal lockdown, ship bubble-up, sample branching, invoice
payment progression).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_catalog, produce_roasted_lot, create_green_lot, create_planned_batch,
    cooling_batch, place_order, reserve_fulfillment, ship_fulfillment, setup_shipped_order,
    issue_invoice, setup_issued_invoice,
    start_roast_batch_payload, complete_roast_batch_payload,
    create_order_payload, order_line, create_payment_payload,
    create_sample_request_payload, review_sample_request_payload,
    convert_sample_request_payload, create_fulfillment_payload,
    TEST_USERS,
)

ROASTER = TEST_USERS["roaster_headers"]
SALES = TEST_USERS["sales_headers"]


# ─── non_linear_state_machine / roast_batch_cyclic_reroast_loop ─────────────

def test_reroast_loops_cooling_back_to_roasting(api):
    """PRD §3.3: "a cooling batch can be sent back to `ROASTING` for a bounded development
    re-pass, which increments an internal re-roast counter and the batch's `version`."

    Design: Difficulty/non_linear_state_machine/roast_batch_cyclic_reroast_loop
    """
    product = setup_catalog()["product"]
    batch = cooling_batch(product["id"], actual_green_kg=20, planned_green_kg=20)
    assert batch["status"] == "COOLING"
    rerolled = validate_success(api.reroast_roast_batch(batch["id"], ROASTER), 200)
    assert rerolled["status"] == "ROASTING", \
        f"reroast must loop COOLING back to ROASTING, got {rerolled['status']}"


def test_reroast_then_drop_re_enters_cooling(api):
    """PRD §3.3: "Dropping a batch advances it from `ROASTING` to `COOLING`".
    PRD §3.3: "a cooling batch can be sent back to `ROASTING` for a bounded development
    re-pass, which increments an internal re-roast counter and the batch's `version`."

    Design: Difficulty/non_linear_state_machine/roast_batch_cyclic_reroast_loop
    """
    product = setup_catalog()["product"]
    batch = cooling_batch(product["id"], actual_green_kg=20, planned_green_kg=20)
    api.reroast_roast_batch(batch["id"], ROASTER)  # COOLING -> ROASTING
    back = validate_success(api.drop_roast_batch(batch["id"], ROASTER), 200)  # ROASTING -> COOLING
    assert back["status"] == "COOLING", \
        f"the A->B->A cycle must re-enter COOLING after the second drop, got {back['status']}"


# ─── non_linear_state_machine / order_parallel_fulfillment_and_billing_dimensions ─

def test_order_partially_fulfilled_while_unbilled(api):
    """PRD §3.5: "If at least one line has some but not all of its ordered kilograms
    shipped, with no line over-shipped, and the order is not yet fully covered, the order
    is `PARTIALLY_FULFILLED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_billing_dimensions
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 10)])
    ful = reserve_fulfillment(order["id"], prod["id"], lot["id"], 6)
    ship_fulfillment(ful["id"])
    order_read = validate_success(api.get_order(order["id"], SALES), 200)
    assert order_read["fulfillment_status"] == "PARTIALLY_FULFILLED", \
        f"6 of 10 kg shipped -> PARTIALLY_FULFILLED, got {order_read['fulfillment_status']}"
    assert order_read["billing_status"] == "UNBILLED"


def test_order_billing_advances_independently_of_partial_fulfillment(api):
    """PRD §3.4: "An order's two status dimensions move independently."
    PRD §3.6: "Issuing an **invoice** is a `SalesRep` action that drives the order's
    `billing_status` from `UNBILLED` to the terminal `INVOICED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_billing_dimensions
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 10)])
    ful = reserve_fulfillment(order["id"], prod["id"], lot["id"], 6)
    ship_fulfillment(ful["id"])
    issue_invoice(order["id"])
    order_read = validate_success(api.get_order(order["id"], SALES), 200)
    # Billing advanced to INVOICED while fulfillment stays PARTIALLY_FULFILLED.
    assert order_read["fulfillment_status"] == "PARTIALLY_FULFILLED"
    assert order_read["billing_status"] == "INVOICED", \
        f"billing must reach INVOICED independently, got {order_read['billing_status']}"


# ─── state_machines / new_batch_starts_in_planned (queue B) ─────────────────

def test_new_batch_initial_state_and_planned_yield(api):
    """PRD §3.3: "the batch starts in `PLANNED`".
    PRD §3.3: "its `planned_roasted_kg` is `planned_green_kg` multiplied by one minus the
    profile's `expected_shrink_bps` divided by ten thousand, rounded half-up to three
    decimals."

    Design: Corner/state_machines/new_batch_starts_in_planned
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "INI", "roast_level": "DARK", "expected_shrink_bps": 1800,
         "charge_temp_c": 210}, ROASTER))
    product = get_success_data(api.create_product(
        {"sku": "SKU-INI", "name": "INI", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 2000, "freshness_window_days": 14}, ROASTER))
    gl = get_success_data(api.create_green_lot(
        {"origin": "Sumatra", "lot_ref": "INI-GL", "received_kg": 50, "par_level_kg": 5},
        ROASTER))
    batch = validate_success(api.create_roast_batch(
        {"green_lot_id": gl["id"], "product_id": product["id"],
         "planned_green_kg": 12.5, "expected_green_lot_version": gl["version"]}, ROASTER), 201)
    assert batch["status"] == "PLANNED"
    # 12.5 * (1 - 1800/10000) = 12.5 * 0.82 = 10.250
    assert batch["planned_roasted_kg"] == 10.250, \
        f"expected planned_roasted_kg 10.250, got {batch['planned_roasted_kg']}"


# ─── state_machines / complete_batch_from_planned_returns_invalid_state ─────

def test_complete_planned_batch_invalid_state(api):
    """PRD §3.3: "Completing from any state other than `COOLING` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_batch_from_planned_returns_invalid_state
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=50, par_level_kg=5)
    batch = create_planned_batch(gl["id"], product["id"], planned_green_kg=20)
    res = api.complete_roast_batch(batch["id"], complete_roast_batch_payload(17), ROASTER)
    validate_error(res, "ERR_INVALID_STATE")
    batch_read = validate_success(api.get_roast_batch(batch["id"], ROASTER), 200)
    assert batch_read["status"] == "PLANNED"


# ─── state_machines / cancel_completed_batch_terminal_lockdown ──────────────

def test_cancel_completed_batch_terminal_lockdown(api):
    """PRD §3.3: "Cancelling is only allowed from `PLANNED`; cancelling from any other
    state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_completed_batch_terminal_lockdown
    """
    product = setup_catalog()["product"]
    batch, _ = produce_roasted_lot(product["id"], actual_green_kg=20, actual_roasted_kg=17)
    assert batch["status"] == "COMPLETED"
    res = api.cancel_roast_batch(batch["id"], ROASTER)
    validate_error(res, "ERR_INVALID_STATE")
    batch_read = validate_success(api.get_roast_batch(batch["id"], ROASTER), 200)
    assert batch_read["status"] == "COMPLETED"


# ─── state_machines / reroast_beyond_max_returns_invalid_state ──────────────

def test_third_reroast_exceeds_cap_invalid_state(api):
    """PRD §3.3: "Re-roasting is only allowed while the batch is in `COOLING` and while the
    re-roast count is below the cap of two; a re-roast attempt from a non-`COOLING` state or
    once the cap has been reached is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reroast_beyond_max_returns_invalid_state
    """
    product = setup_catalog()["product"]
    batch = cooling_batch(product["id"], actual_green_kg=20, planned_green_kg=20)
    # reroast 1
    api.reroast_roast_batch(batch["id"], ROASTER)
    api.drop_roast_batch(batch["id"], ROASTER)
    # reroast 2
    api.reroast_roast_batch(batch["id"], ROASTER)
    api.drop_roast_batch(batch["id"], ROASTER)
    # reroast 3 -> exceeds cap of two
    res = api.reroast_roast_batch(batch["id"], ROASTER)
    validate_error(res, "ERR_INVALID_STATE")


# ─── state_machines / ship_then_bubble_up_fulfilled ─────────────────────────

def test_ship_covering_whole_order_bubbles_up_fulfilled(api):
    """PRD §3.5: "If, after this shipment, every order line has its full ordered `qty_kg`
    covered by `SHIPPED` allocations of that product, the order becomes `FULFILLED` —
    whether it reaches that state in a single covering shipment straight from `OPEN` or as
    the final shipment from `PARTIALLY_FULFILLED`."

    Design: Corner/state_machines/ship_then_bubble_up_fulfilled
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order, ful = setup_shipped_order(cat["account"]["id"], prod["id"], lot["id"],
                                     qty_kg=10, allocated_kg=10)
    order_read = validate_success(api.get_order(order["id"], SALES), 200)
    assert order_read["fulfillment_status"] == "FULFILLED"
    lot_read = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    assert lot_read["on_hand_kg"] == 15.000, \
        f"on_hand should fall to 15.000 (25 - 10 shipped), got {lot_read['on_hand_kg']}"


# ─── state_machines / sample_decline_branch_terminal ────────────────────────

def test_sample_decline_terminal_blocks_convert(api):
    """PRD §3.7: "On a DECLINE decision the request moves from `REQUESTED` to the terminal
    `DECLINED`".
    PRD §3.7: "Conversion is only allowed while the request is `APPROVED`, or it is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sample_decline_branch_terminal
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    sr = get_success_data(api.create_sample_request(
        cat["account"]["id"], create_sample_request_payload(cat["product"]["id"]), SALES))
    reviewed = get_success_data(api.review_sample_request(
        sr["id"], review_sample_request_payload("DECLINE", 60), ROASTER))
    assert reviewed["status"] == "DECLINED"
    res = api.convert_sample_request(sr["id"], convert_sample_request_payload(5), SALES)
    validate_error(res, "ERR_INVALID_STATE")


# ─── state_machines / sample_convert_below_score_rejected ───────────────────

def test_convert_below_min_score_rejected(api):
    """PRD §3.7: "The recorded `cupping_score` must be at least 80 — the minimum conversion
    score — and the sampled product must not be archived".

    Design: Corner/state_machines/sample_convert_below_score_rejected
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    sr = get_success_data(api.create_sample_request(
        cat["account"]["id"], create_sample_request_payload(cat["product"]["id"]), SALES))
    api.review_sample_request(sr["id"], review_sample_request_payload("APPROVE", 75), ROASTER)
    res = api.convert_sample_request(sr["id"], convert_sample_request_payload(5), SALES)
    validate_error(res, "ERR_INVALID_STATE")


# ─── state_machines / invoice_payment_partial_then_paid ─────────────────────

def test_invoice_partial_then_full_payment(api):
    """PRD §3.6: "A partial payment (strictly less than the amount due) on an `ISSUED`
    invoice moves it to `PARTIALLY_PAID`; a payment that exactly equals the amount due moves
    an `ISSUED`, `OVERDUE`, or `PARTIALLY_PAID` invoice to the terminal `PAID` with
    `amount_due_cents` of zero."

    Design: Corner/state_machines/invoice_payment_partial_then_paid
    """
    ctx = setup_issued_invoice(qty_kg=10, base_price_cents_per_kg=2000, discount_bps=0)
    inv = ctx["invoice"]
    assert inv["amount_cents"] == 20000
    api.create_payment(inv["id"], create_payment_payload(8000), SALES)
    mid = validate_success(api.get_invoice(inv["id"], SALES), 200)
    assert mid["status"] == "PARTIALLY_PAID"
    assert mid["amount_due_cents"] == 12000
    api.create_payment(inv["id"], create_payment_payload(12000), SALES)
    end = validate_success(api.get_invoice(inv["id"], SALES), 200)
    assert end["status"] == "PAID"
    assert end["amount_due_cents"] == 0


# ─── calculations / invoice_due_at_uses_net_terms (queue B) ─────────────────

def test_invoice_due_at_uses_net_terms(api):
    """PRD §3.6: "stamps `issued_at` to the current clock, pins `due_at` to `issued_at` plus
    the account's `net_terms_days` days, and starts the invoice in `ISSUED`."

    Design: Corner/calculations/invoice_due_at_uses_net_terms
    """
    from test_helpers import clock_set
    clock_set("2026-06-01T00:00:00Z")
    ctx = setup_issued_invoice(qty_kg=10, base_price_cents_per_kg=2000, discount_bps=0,
                               net_terms_days=30)
    inv = ctx["invoice"]
    assert inv["issued_at"] == "2026-06-01T00:00:00.000Z", \
        f"issued_at must equal the clock at issue, got {inv['issued_at']}"
    assert inv["due_at"] == "2026-07-01T00:00:00.000Z", \
        f"due_at must be issued_at + 30 days, got {inv['due_at']}"
