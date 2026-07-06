"""Layaway lifecycle (cyclic deposit loop, completion, default, cancel) and the
transitive inventory cascades and compensating-action invariants they drive.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_paginated,
    setup_layaway,
    deposit_on_layaway,
    set_spot_rate,
    create_product,
    create_customer,
    create_placed_buy_order,
    make_customer_headers,
    TEST_USERS,
)

SALES = TEST_USERS["sales_agent_headers"]


# ─── Rule 3a: cyclic ACTIVE→ACTIVE deposit self-loop ───────────────────────

def test_layaway_two_deposits_stay_active_and_accumulate(api):
    """PRD §3.5: "While a layaway is ACTIVE it accepts deposits in a repeating
    self-loop that keeps it ACTIVE." PRD §3.5: "A successful deposit increases
    amount_paid_cents by amount_cents and increments the layaway's version".

    Design: Difficulty/non_linear_state_machine/layaway_cyclic_deposit_loop
    """
    ctx = setup_layaway(quantity=2, customer_name="Layaway Holder")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    after1 = deposit_on_layaway(lay["id"], 100_000, lay["version"], cust_id)
    assert after1["status"] == "ACTIVE"
    after2 = deposit_on_layaway(lay["id"], 100_000, after1["version"], cust_id)
    assert after2["status"] == "ACTIVE"
    assert after2["amount_paid_cents"] == 200_000


def test_layaway_deposit_locks_price_at_creation(api):
    """PRD §3.5: "locks the locked_unit_price_cents from the unit sell price of
    §3.1 (this price is immune to any later spot-rate change, which is the
    price-lock guarantee), sets total_price_cents to the locked unit price
    multiplied by the quantity".

    Design: Difficulty/non_linear_state_machine/layaway_cyclic_deposit_loop
    """
    ctx = setup_layaway(quantity=2, customer_name="Price Lock")
    lay = ctx["layaway"]
    # GOLD spot 200000, 1oz bullion, spread 0.05 → unit sell 210000; qty 2 → 420000
    assert lay["total_price_cents"] == 420_000
    assert lay["amount_paid_cents"] == 0
    assert lay["status"] == "ACTIVE"


# ─── Rule 4a: complete cascades lot to DEPLETED (depth ≥3) ────────────────

def test_layaway_complete_converts_reservation_to_sale(api):
    """PRD §3.5: "completion converts the reservation to a delivered sale by
    decrementing the lot's reserved_qty by the quantity and incrementing its
    sold_qty by the same quantity ... the layaway status becomes COMPLETED."

    Design: Difficulty/transitive_cascade/layaway_complete_cascades_to_lot_depletion
    """
    ctx = setup_layaway(total_qty=2, quantity=2, customer_name="Full Payer")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    deposit_on_layaway(lay["id"], 420_000, lay["version"], cust_id)
    completed = validate_success(api.complete_layaway(lay["id"], SALES), 200)
    assert completed["status"] == "COMPLETED"

    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], SALES), 200)
    assert lot["reserved_qty"] == 0
    assert lot["sold_qty"] == 2


def test_layaway_complete_cascades_lot_to_depleted(api):
    """PRD §3.5: "any such lot whose available_qty is 0 with sold_qty equal to
    total_qty transitions to DEPLETED". PRD §3.2: "transitions to DEPLETED once
    available_qty reaches 0 and sold_qty equals total_qty."

    Design: Difficulty/transitive_cascade/layaway_complete_cascades_to_lot_depletion
    """
    ctx = setup_layaway(total_qty=2, quantity=2, customer_name="Full Payer Two")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    deposit_on_layaway(lay["id"], 420_000, lay["version"], cust_id)
    validate_success(api.complete_layaway(lay["id"], SALES), 200)

    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], SALES), 200)
    assert lot["available_qty"] == 0
    assert lot["status"] == "DEPLETED"


# ─── Rule 4b: buy settle cascades to new inventory + lifetime payout ──────

def test_buy_settle_creates_inventory_and_bumps_lifetime(api):
    """PRD §3.4: "the system creates (or augments) an inventory lot for the product
    with total_qty equal to the buy order quantity and acquisition_unit_cost_cents
    equal to the order's quoted_unit_payout_cents ... increments the selling
    customer's lifetime_buy_payout_cents by the order's total_payout_cents; and
    sets the order status to SETTLED."

    Design: Difficulty/transitive_cascade/buy_settle_cascades_to_inventory_and_lifetime
    """
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-1OZ-B4", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    customer = create_customer("Seller", id_document_on_file=True)
    order = create_placed_buy_order(product["id"], customer["id"], quantity=3)

    settled = validate_success(api.settle_buy_order(order["id"], SALES), 200)
    assert settled["status"] == "SETTLED"
    assert settled["total_payout_cents"] == 576_000

    cust = validate_success(api.get_customer(customer["id"], SALES), 200)
    assert cust["lifetime_buy_payout_cents"] == 576_000


def test_buy_settle_new_lot_carries_payout_as_cost(api):
    """PRD §3.4: "the system creates (or augments) an inventory lot for the product
    with total_qty equal to the buy order quantity and acquisition_unit_cost_cents
    equal to the order's quoted_unit_payout_cents, making that stock immediately
    available for sale".

    Design: Difficulty/transitive_cascade/buy_settle_cascades_to_inventory_and_lifetime
    """
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-1OZ-B4B", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    customer = create_customer("Seller Two", id_document_on_file=True)
    order = create_placed_buy_order(product["id"], customer["id"], quantity=3)
    validate_success(api.settle_buy_order(order["id"], SALES), 200)

    data, meta = validate_paginated(
        api.list_inventory_lots(SALES, params={"product_id": product["id"]}))
    lots = [l for l in data if l["product_id"] == product["id"]]
    assert any(l["total_qty"] == 3 and l["available_qty"] == 3
               and l["acquisition_unit_cost_cents"] == 192_000 for l in lots)


# ─── Rule 9a: cancel conserves lot total_qty ──────────────────────────────

def test_layaway_cancel_sets_status_cancelled(api):
    """PRD §3.5: "the owning Customer may cancel an active layaway, which likewise
    releases the reservation back to available_qty and refunds the accumulated
    amount_paid_cents into the customer's store_credit_cents, setting the status
    to CANCELLED."

    Design: Difficulty/compensating_invariant/layaway_cancel_conserves_lot_total_qty
    """
    ctx = setup_layaway(total_qty=10, quantity=2, customer_name="Canceller")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    cancelled = validate_success(
        api.cancel_layaway(lay["id"], make_customer_headers(cust_id)), 200)
    assert cancelled["status"] == "CANCELLED"


def test_layaway_cancel_conserves_lot_units(api):
    """PRD §3.5: "the owning Customer may cancel an active layaway, which likewise
    releases the reservation back to available_qty ... setting the status to
    CANCELLED." PRD §3.2: "available_qty plus reserved_qty plus sold_qty always
    equals total_qty."

    Design: Difficulty/compensating_invariant/layaway_cancel_conserves_lot_total_qty
    """
    ctx = setup_layaway(total_qty=10, quantity=2, customer_name="Canceller Two")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    validate_success(api.cancel_layaway(lay["id"], make_customer_headers(cust_id)), 200)

    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], SALES), 200)
    assert lot["available_qty"] == 10
    assert lot["reserved_qty"] == 0
    assert lot["sold_qty"] == 0


# ─── Rule 9b: default conserves customer value ────────────────────────────

def test_layaway_default_credits_deposits_to_store_credit(api):
    """PRD §3.5: "a SalesAgent may default an active layaway: this releases the
    reservation ... credits the customer's store_credit_cents by the layaway's
    amount_paid_cents so the deposits become refundable store credit, and sets the
    status to DEFAULTED."

    Design: Difficulty/compensating_invariant/layaway_default_conserves_customer_value
    """
    ctx = setup_layaway(total_qty=5, quantity=2, customer_name="Defaulter")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    after = deposit_on_layaway(lay["id"], 150_000, lay["version"], cust_id)
    assert after["amount_paid_cents"] == 150_000

    defaulted = validate_success(api.default_layaway(lay["id"], SALES), 200)
    assert defaulted["status"] == "DEFAULTED"
    assert defaulted["amount_paid_cents"] == 150_000

    cust = validate_success(api.get_customer(cust_id, SALES), 200)
    assert cust["store_credit_cents"] == 150_000


def test_layaway_default_releases_reservation_to_available(api):
    """PRD §3.5: "a SalesAgent may default an active layaway: this releases the
    reservation by decrementing the lot's reserved_qty and incrementing its
    available_qty by the quantity (a compensating move that conserves total_qty)
    ... and sets the status to DEFAULTED."

    Design: Difficulty/compensating_invariant/layaway_default_conserves_customer_value
    """
    ctx = setup_layaway(total_qty=5, quantity=2, customer_name="Defaulter Two")
    lay = ctx["layaway"]
    cust_id = ctx["customer"]["id"]

    deposit_on_layaway(lay["id"], 150_000, lay["version"], cust_id)
    validate_success(api.default_layaway(lay["id"], SALES), 200)

    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], SALES), 200)
    assert lot["available_qty"] == 5
    assert lot["reserved_qty"] == 0
