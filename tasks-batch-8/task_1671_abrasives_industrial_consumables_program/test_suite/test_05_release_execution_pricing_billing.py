"""Release execution: FEFO pick, ship, billing totals, cancellation branches."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allocations_shape,
    get_contract,
    get_lot,
    get_order,
    get_release,
    make_blanket_order,
    make_contract,
    make_lot,
    make_picked_release,
    make_product,
    make_release,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def _setup_open_order(committed_qty=100, sku="EX-1", contract_number="C-EX1",
                      base=10000, escalation_pct=0.0,
                      price_hold_end="2026-12-31",
                      escalation_effective_date="2027-01-01",
                      term_end="2027-12-31"):
    product = make_product(sku=sku, name="Exec Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": base}],
        customer_ref="PLANT-EX",
        contract_number=contract_number,
        price_hold_end=price_hold_end,
        escalation_pct=escalation_pct,
        escalation_effective_date=escalation_effective_date,
        term_end=term_end,
    )
    order = make_blanket_order(contract["id"], product["id"],
                               committed_qty=committed_qty)
    return product, contract, order


# ---------------------------------------------------------------------------
# Difficulty / dual_variant_calc / release_price_provisional_vs_final
# ---------------------------------------------------------------------------


def test_release_provisional_price_evaluated_at_ship_date_inside_hold(api):
    """PRD §3.6: "the release's `provisional_unit_price_cents` is stamped by
    evaluating the price at its `scheduled_ship_date`"
    PRD §3.5: "an evaluation date on or before `price_hold_end` yields the
    line's `base_unit_price_cents`"

    Design: Difficulty/dual_variant_calc/release_price_provisional_vs_final
    """
    product, contract, order = _setup_open_order(
        committed_qty=240, sku="CB-240", contract_number="C-1001",
        base=10000, escalation_pct=0.04,
    )
    release = make_release(order["id"], order["version"], qty=240,
                           scheduled_ship_date="2026-09-01")
    assert release["provisional_unit_price_cents"] == 10000, (
        f"scheduled 2026-09-01 <= price_hold_end 2026-12-31 -> base 10000; got "
        f"{release['provisional_unit_price_cents']}"
    )


def test_release_final_price_diverges_from_provisional_after_escalation(api):
    """PRD §3.7: "`final_unit_price_cents` is the price evaluated at the
    **current logical-clock date** for the order's product — the final variant
    of the pricing function, which diverges from the provisional stamp whenever
    a hold or escalation boundary falls between the scheduled and actual ship
    dates."
    PRD §3.5: "an evaluation date on or after `escalation_effective_date` yields
    the base price multiplied by one plus `escalation_pct`, rounded half-up to
    whole cents"
    PRD §3.7: "The tier percentage depends on the order's `committed_qty` with
    inclusive boundaries: at least 2000 committed units earns a discount of 6
    percent (0.06); otherwise at least 500 committed units earns 3 percent
    (0.03); smaller orders earn no discount."

    Design: Difficulty/dual_variant_calc/release_price_provisional_vs_final
    """
    product, contract, order = _setup_open_order(
        committed_qty=240, sku="CB-240B", contract_number="C-1001B",
        base=10000, escalation_pct=0.04,
    )
    release = make_release(order["id"], order["version"], qty=240,
                           scheduled_ship_date="2026-09-01")
    make_lot(product["id"], lot_code="L-300", qty_received=300)
    validate_success(api.pick_release(release["id"], AM), 200)

    # Advance clock past escalation_effective_date; contract term still ACTIVE.
    set_clock("2027-01-15T00:00:00Z")

    shipped = validate_success(api.ship_release(release["id"], AM), 200)
    assert shipped["status"] == "SHIPPED"
    assert shipped["final_unit_price_cents"] == 10400, (
        f"final evaluated at clock 2027-01-15: round_half_up(10000*1.04)=10400; "
        f"got {shipped['final_unit_price_cents']}"
    )
    # committed 240 < 500 -> tier 0; billed = 240 x 10400 = 2,496,000.
    assert shipped["billed_total_cents"] == 2496000

    fetched = get_release(release["id"])
    assert fetched["provisional_unit_price_cents"] == 10000, (
        "provisional stamp (at scheduled_ship_date inside hold) must remain 10000"
    )


# ---------------------------------------------------------------------------
# Difficulty / combinatorial_formula / billing_total_unit_first_rounding
# ---------------------------------------------------------------------------


def test_billing_total_unit_first_rounding_final_price(api):
    """PRD §3.7: "`billed_total_cents` follows a pinned five-step rounding
    order: first, the unit price is rounded at the unit level (this is the
    `final_unit_price_cents` just computed)"
    PRD §3.7: "For example, with a base price of 10013 cents, an escalation of
    0.04 in effect at ship time, a shipped quantity of 2, and no tier, the
    pinned computation yields a unit price of 10414 cents and a total of 20828
    cents — whereas rounding the unrounded unit-price-times-quantity product
    would yield 20827 cents, which is wrong."

    Design: Difficulty/combinatorial_formula/billing_total_unit_first_rounding
    """
    product, contract, order = _setup_open_order(
        committed_qty=100, sku="CB-RND", contract_number="C-1002",
        base=10013, escalation_pct=0.04,
    )
    release = make_release(order["id"], order["version"], qty=2,
                           scheduled_ship_date="2027-02-01")
    make_lot(product["id"], lot_code="L-RND", qty_received=10)
    validate_success(api.pick_release(release["id"], AM), 200)
    set_clock("2027-02-01T00:00:00Z")

    shipped = validate_success(api.ship_release(release["id"], AM), 200)
    assert shipped["final_unit_price_cents"] == 10414, (
        f"unit-first rounding: round_half_up(10013*1.04)=10414; got "
        f"{shipped['final_unit_price_cents']}"
    )


def test_billing_total_unit_first_rounding_total(api):
    """PRD §3.7: "second, each allocation line's gross is extended exactly as
    the unit price multiplied by that line's quantity; third, the line grosses
    are summed into the release gross; fourth, the tier discount percentage for
    the order is applied to the release gross and the result is rounded half-up
    to whole cents exactly once; fifth, the rounded discount is subtracted from
    the release gross."
    PRD §3.7: "the pinned computation yields a unit price of 10414 cents and a
    total of 20828 cents — whereas rounding the unrounded
    unit-price-times-quantity product would yield 20827 cents, which is wrong."

    Design: Difficulty/combinatorial_formula/billing_total_unit_first_rounding
    """
    product, contract, order = _setup_open_order(
        committed_qty=100, sku="CB-RND2", contract_number="C-1002B",
        base=10013, escalation_pct=0.04,
    )
    release = make_release(order["id"], order["version"], qty=2,
                           scheduled_ship_date="2027-02-01")
    make_lot(product["id"], lot_code="L-RND2", qty_received=10)
    validate_success(api.pick_release(release["id"], AM), 200)
    set_clock("2027-02-01T00:00:00Z")

    shipped = validate_success(api.ship_release(release["id"], AM), 200)
    assert shipped["billed_total_cents"] == 20828, (
        f"pinned total 2 x 10414 = 20828 (NOT 20827 from order-level "
        f"rounding); got {shipped['billed_total_cents']}"
    )
    assert shipped["status"] == "SHIPPED"


# ---------------------------------------------------------------------------
# Corner / state_machines / release_ship_before_pick_rejected
# ---------------------------------------------------------------------------


def test_release_ship_before_pick_rejected(api):
    """PRD §2.8 item 6: "release picks only from `SCHEDULED`, ships only from
    `PICKED`, cancels only from a non-terminal state ... violations yield
    `ERR_INVALID_STATE_TRANSITION`, 409"
    PRD §3.7: "Shipment, also by an `AccountManager`, moves a `PICKED` release
    to `SHIPPED`"

    Design: Corner/state_machines/release_ship_before_pick_rejected
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="SP-1",
                                                 contract_number="C-SP")
    release = make_release(order["id"], order["version"], qty=5,
                           scheduled_ship_date="2026-09-01")
    resp = api.ship_release(release["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert get_release(release["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner / state_machines / release_cancel_after_ship_rejected
# ---------------------------------------------------------------------------


def test_release_cancel_after_ship_rejected(api):
    """PRD §3.7: "Cancelling a release that is already `SHIPPED` or `CANCELLED`
    is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/release_cancel_after_ship_rejected
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="CS-1",
                                                 contract_number="C-CS")
    make_lot(product["id"], lot_code="L-CS", qty_received=10)
    release = make_release(order["id"], order["version"], qty=10,
                           scheduled_ship_date="2026-09-01")
    validate_success(api.pick_release(release["id"], AM), 200)
    validate_success(api.ship_release(release["id"], AM), 200)

    resp = api.cancel_release(release["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert get_release(release["id"])["status"] == "SHIPPED"


# ---------------------------------------------------------------------------
# Corner / state_machines / blanket_auto_close_after_final_ship
# ---------------------------------------------------------------------------


def test_blanket_auto_close_after_final_ship(api):
    """PRD §3.6: "the order auto-closes: after any individual release ships or
    is cancelled, if the order's `remaining_qty` has reached zero and no
    release remains in `SCHEDULED`, `ON_HOLD`, or `PICKED`, the order
    transitions from `OPEN` to `CLOSED` on its own."
    PRD §3.3: "Whenever a decrement leaves `qty_on_hand` at exactly zero, the
    lot transitions from `AVAILABLE` to `DEPLETED`"

    Design: Corner/state_machines/blanket_auto_close_after_final_ship
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="AC-1",
                                                 contract_number="C-AC")
    lot = make_lot(product["id"], lot_code="L-AC", qty_received=10)
    release = make_release(order["id"], order["version"], qty=10,
                           scheduled_ship_date="2026-09-01")
    validate_success(api.pick_release(release["id"], AM), 200)
    shipped = validate_success(api.ship_release(release["id"], AM), 200)

    assert shipped["status"] == "SHIPPED"
    assert shipped["final_unit_price_cents"] == 10000
    # committed 10 < 500 -> tier 0; billed = 10 x 10000.
    assert shipped["billed_total_cents"] == 100000

    order_after = get_order(order["id"])
    assert order_after["status"] == "CLOSED"
    assert order_after["remaining_qty"] == 0

    lot_after = get_lot(lot["id"])
    assert lot_after["qty_on_hand"] == 0
    assert lot_after["status"] == "DEPLETED"


# ---------------------------------------------------------------------------
# Difficulty / non_linear_state_machine / release_branching_cancel_side_effects
# ---------------------------------------------------------------------------


def test_release_cancel_from_scheduled_no_lot_touch(api):
    """PRD §3.7: "From `SCHEDULED`, the release moves to `CANCELLED`, its `qty`
    is added back to the order's `remaining_qty`, and the auto-close check
    runs." — the SCHEDULED branch never touches lots (only the PICKED branch
    "restores stock").

    Design: Difficulty/non_linear_state_machine/release_branching_cancel_side_effects
    """
    product, contract, order = _setup_open_order(committed_qty=100, sku="CB-BR",
                                                 contract_number="C-1003")
    lot = make_lot(product["id"], lot_code="L-BR", qty_received=50)
    r1 = make_release(order["id"], order["version"], qty=10,
                      scheduled_ship_date="2026-09-01")

    cancelled = validate_success(api.cancel_release(r1["id"], AM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_lot(lot["id"])["qty_on_hand"] == 50, (
        "cancel from SCHEDULED must not touch lots"
    )


def test_release_cancel_from_picked_restores_lot_and_clears_allocations(api):
    """PRD §3.7: "From `PICKED`, cancellation additionally restores stock: each
    allocation line's `qty` is returned to the **same** lot it was taken from,
    a `DEPLETED` lot lifted back above zero returns to `AVAILABLE`, `BLOCKED`
    and `EXPIRED` lots keep their status (their `qty_on_hand` increases but they
    remain unpickable), the release's `allocations` are cleared to empty, the
    quantity is given back, and the auto-close check runs."

    Design: Difficulty/non_linear_state_machine/release_branching_cancel_side_effects
    """
    product, contract, order = _setup_open_order(committed_qty=100, sku="CB-BR2",
                                                 contract_number="C-1003B")
    lot = make_lot(product["id"], lot_code="L-BR2", qty_received=50)
    r1 = make_release(order["id"], order["version"], qty=10,
                      scheduled_ship_date="2026-09-01")
    mid = get_order(order["id"])
    r2 = make_release(order["id"], mid["version"], qty=10,
                      scheduled_ship_date="2026-09-01")
    validate_success(api.pick_release(r2["id"], AM), 200)
    assert get_lot(lot["id"])["qty_on_hand"] == 40

    cancelled = validate_success(api.cancel_release(r2["id"], AM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["allocations"] == [], "PICKED-cancel must clear allocations"

    lot_after = get_lot(lot["id"])
    assert lot_after["qty_on_hand"] == 50, "restore returned 10 to the same lot"
    assert lot_after["status"] == "AVAILABLE"

    order_after = get_order(order["id"])
    assert order_after["remaining_qty"] == 90, (
        f"PICKED-cancel gives back 10: 80 + 10 = 90 (r1 still SCHEDULED); "
        f"got {order_after['remaining_qty']}"
    )
    assert order_after["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Difficulty / compensating_invariant / lot_stock_conserved_on_pick_cancel
# ---------------------------------------------------------------------------


def test_lot_stock_conserved_mid_pick(api):
    """PRD §3.7: "A successful pick moves the release to `PICKED`, decrements
    each allocated lot's `qty_on_hand` (a lot reaching zero becomes `DEPLETED`),
    and records the waterfall lines — each a `lot_id` with its allocated `qty`,
    in allocation order — on the release's `allocations`."

    Design: Difficulty/compensating_invariant/lot_stock_conserved_on_pick_cancel
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="CB-INV2",
                                                 contract_number="C-1010")
    lot = make_lot(product["id"], lot_code="L-INV2", qty_received=10)
    release = make_release(order["id"], order["version"], qty=6,
                           scheduled_ship_date="2026-09-01")
    picked = validate_success(api.pick_release(release["id"], AM), 200)

    assert_allocations_shape(picked["allocations"])
    assert picked["allocations"] == [{"lot_id": lot["id"], "qty": 6}]
    # Stock identity mid-flight: 4 on hand + 6 allocated == 10 received.
    assert get_lot(lot["id"])["qty_on_hand"] == 4


def test_lot_stock_restored_exactly_on_cancel(api):
    """PRD §3.7: "each allocation line's `qty` is returned to the **same** lot
    it was taken from, a `DEPLETED` lot lifted back above zero returns to
    `AVAILABLE` ... the release's `allocations` are cleared to empty"

    Design: Difficulty/compensating_invariant/lot_stock_conserved_on_pick_cancel
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="CB-INV2B",
                                                 contract_number="C-1010B")
    lot = make_lot(product["id"], lot_code="L-INV2B", qty_received=10)
    release = make_release(order["id"], order["version"], qty=6,
                           scheduled_ship_date="2026-09-01")
    validate_success(api.pick_release(release["id"], AM), 200)
    assert get_lot(lot["id"])["qty_on_hand"] == 4

    cancelled = validate_success(api.cancel_release(release["id"], AM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["allocations"] == []

    lot_after = get_lot(lot["id"])
    assert lot_after["qty_on_hand"] == 10, "stock position restored exactly"
    assert lot_after["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Corner / calculations / fefo_waterfall_split_allocation
# ---------------------------------------------------------------------------


def test_fefo_waterfall_split_allocation(api):
    """PRD §3.7: "Candidates are ranked by `expiry_date` ascending with
    never-expiring lots placed last, ties broken by `manufacture_date`
    ascending and then `created_at` ascending. The allocation walks the ranking
    as a waterfall, taking from each lot the lesser of its on-hand quantity and
    the remaining need, until the release quantity is covered."
    PRD §3.7: "records the waterfall lines — each a `lot_id` with its allocated
    `qty`, in allocation order — on the release's `allocations`"

    Design: Corner/calculations/fefo_waterfall_split_allocation
    """
    product = make_product(sku="FF-1", name="FEFO Wheel", product_form="BONDED",
                           shelf_life_months=6, shelf_life_policy="EXACT_DAY")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-FF", contract_number="C-FF",
    )
    order = make_blanket_order(contract["id"], product["id"], committed_qty=10)
    # L1 expires 2026-09-01; L2 expires 2026-09-10 — L1 ranks first.
    l1 = make_lot(product["id"], lot_code="L-F1", manufacture_date="2026-03-01",
                  qty_received=3)
    l2 = make_lot(product["id"], lot_code="L-F2", manufacture_date="2026-03-10",
                  qty_received=7)
    release = make_release(order["id"], order["version"], qty=6,
                           scheduled_ship_date="2026-08-15")

    picked = validate_success(api.pick_release(release["id"], AM), 200)
    assert picked["status"] == "PICKED"
    assert picked["allocations"] == [
        {"lot_id": l1["id"], "qty": 3},
        {"lot_id": l2["id"], "qty": 3},
    ], f"earlier-expiring lot must be drained first: {picked['allocations']}"

    l1_after = get_lot(l1["id"])
    assert l1_after["qty_on_hand"] == 0 and l1_after["status"] == "DEPLETED"
    l2_after = get_lot(l2["id"])
    assert l2_after["qty_on_hand"] == 4 and l2_after["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Corner / calculations / fefo_excludes_lot_expiring_before_ship
# ---------------------------------------------------------------------------


def test_fefo_excludes_lot_expiring_before_ship(api):
    """PRD §3.7: "The candidate pool is every lot of the order's product that is
    `AVAILABLE`, has `qty_on_hand` greater than zero, and has either no
    `expiry_date` or an `expiry_date` on or after the release's
    `scheduled_ship_date` — shipping on the lot's expiry day itself is allowed."

    Design: Corner/calculations/fefo_excludes_lot_expiring_before_ship
    """
    product = make_product(sku="FX-1", name="FEFO Exclude Wheel",
                           product_form="BONDED", shelf_life_months=6,
                           shelf_life_policy="EXACT_DAY")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-FX", contract_number="C-FX",
    )
    order = make_blanket_order(contract["id"], product["id"], committed_qty=10)
    # LA expires 2026-08-01 (before R1's ship 2026-08-05 -> excluded).
    la = make_lot(product["id"], lot_code="L-FA", manufacture_date="2026-02-01",
                  qty_received=5)
    # LB expires 2026-08-10.
    lb = make_lot(product["id"], lot_code="L-FB", manufacture_date="2026-02-10",
                  qty_received=5)

    r1 = make_release(order["id"], order["version"], qty=3,
                      scheduled_ship_date="2026-08-05")
    mid = get_order(order["id"])
    r2 = make_release(order["id"], mid["version"], qty=2,
                      scheduled_ship_date="2026-08-10")

    p1 = validate_success(api.pick_release(r1["id"], AM), 200)
    assert p1["allocations"] == [{"lot_id": lb["id"], "qty": 3}], (
        f"LA (expiry 2026-08-01 < ship 2026-08-05) must be excluded: "
        f"{p1['allocations']}"
    )

    p2 = validate_success(api.pick_release(r2["id"], AM), 200)
    assert p2["allocations"] == [{"lot_id": lb["id"], "qty": 2}], (
        f"LB expiry 2026-08-10 == ship 2026-08-10 is eligible (inclusive): "
        f"{p2['allocations']}"
    )

    la_after = get_lot(la["id"])
    assert la_after["qty_on_hand"] == 5 and la_after["status"] == "AVAILABLE"
    lb_after = get_lot(lb["id"])
    assert lb_after["qty_on_hand"] == 0 and lb_after["status"] == "DEPLETED"


# ---------------------------------------------------------------------------
# Corner / calculations / tier_discount_boundary_499_vs_500
# ---------------------------------------------------------------------------


def _ship_full_order(committed, sku, contract_number, lot_code):
    product = make_product(sku=sku, name="Tier Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-TD", contract_number=contract_number,
    )
    order = make_blanket_order(contract["id"], product["id"],
                               committed_qty=committed)
    make_lot(product["id"], lot_code=lot_code, qty_received=committed)
    release = make_release(order["id"], order["version"], qty=committed,
                           scheduled_ship_date="2026-09-01")
    validate_success(api_client.pick_release(release["id"], AM), 200)
    return validate_success(api_client.ship_release(release["id"], AM), 200)


def test_tier_discount_499_no_discount(api):
    """PRD §3.7: "The tier percentage depends on the order's `committed_qty`
    with inclusive boundaries: at least 2000 committed units earns a discount
    of 6 percent (0.06); otherwise at least 500 committed units earns 3 percent
    (0.03); smaller orders earn no discount."

    Design: Corner/calculations/tier_discount_boundary_499_vs_500
    """
    shipped = _ship_full_order(499, "TD-1", "C-TD", "L-TA")
    # 499 < 500 -> tier 0: billed = 499 x 10000.
    assert shipped["billed_total_cents"] == 4990000


def test_tier_discount_500_earns_3pct(api):
    """PRD §3.7: "at least 2000 committed units earns a discount of 6 percent
    (0.06); otherwise at least 500 committed units earns 3 percent (0.03);
    smaller orders earn no discount." — and "the tier discount percentage for
    the order is applied to the release gross and the result is rounded half-up
    to whole cents exactly once"

    Design: Corner/calculations/tier_discount_boundary_499_vs_500
    """
    shipped = _ship_full_order(500, "TD-2", "C-TD2", "L-TB")
    # committed 500 >= 500 -> 3%: gross 5,000,000 - round(5,000,000*0.03)=150,000.
    assert shipped["billed_total_cents"] == 4850000


# ---------------------------------------------------------------------------
# Corner / calculations / price_hold_end_and_escalation_boundary
# ---------------------------------------------------------------------------


def test_price_hold_end_inclusive_base_price(api):
    """PRD §3.5: "both boundary dates are **inclusive**: an evaluation date on
    or before `price_hold_end` yields the line's `base_unit_price_cents`"
    PRD §3.6: "the release's `provisional_unit_price_cents` is stamped by
    evaluating the price at its `scheduled_ship_date`"

    Design: Corner/calculations/price_hold_end_and_escalation_boundary
    """
    product, contract, order = _setup_open_order(
        committed_qty=100, sku="HB-1", contract_number="C-HB",
        base=10000, escalation_pct=0.04,
    )
    release = make_release(order["id"], order["version"], qty=10,
                           scheduled_ship_date="2026-12-31")
    assert release["provisional_unit_price_cents"] == 10000, (
        f"scheduled == price_hold_end 2026-12-31 -> hold inclusive -> base; "
        f"got {release['provisional_unit_price_cents']}"
    )


def test_price_escalation_effective_date_inclusive(api):
    """PRD §3.5: "otherwise, an evaluation date on or after
    `escalation_effective_date` yields the base price multiplied by one plus
    `escalation_pct`, rounded half-up to whole cents"

    Design: Corner/calculations/price_hold_end_and_escalation_boundary
    """
    product, contract, order = _setup_open_order(
        committed_qty=100, sku="HB-2", contract_number="C-HB2",
        base=10000, escalation_pct=0.04,
    )
    release = make_release(order["id"], order["version"], qty=10,
                           scheduled_ship_date="2027-01-01")
    assert release["provisional_unit_price_cents"] == 10400, (
        f"scheduled == escalation_effective_date 2027-01-01 -> escalated: "
        f"round_half_up(10000*1.04)=10400; got "
        f"{release['provisional_unit_price_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner / state_machines / pick_empty_pool_rejected
# ---------------------------------------------------------------------------


def test_pick_empty_pool_rejected(api):
    """PRD §3.7: "An empty pool is rejected with `ERR_NO_ELIGIBLE_LOT`."

    Design: Corner/state_machines/pick_empty_pool_rejected
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="EP-1",
                                                 contract_number="C-EP")
    release = make_release(order["id"], order["version"], qty=5,
                           scheduled_ship_date="2026-09-01")
    resp = api.pick_release(release["id"], AM)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_LOT.value)

    after = get_release(release["id"])
    assert after["status"] == "SCHEDULED"
    assert after["allocations"] == []


# ---------------------------------------------------------------------------
# Corner / state_machines / pick_insufficient_stock_rejected
# ---------------------------------------------------------------------------


def test_pick_insufficient_stock_rejected(api):
    """PRD §3.7: "If the pool's total on-hand quantity is less than the
    release's `qty`, picking is rejected with `ERR_INSUFFICIENT_STOCK` and **no
    partial allocation is persisted**."

    Design: Corner/state_machines/pick_insufficient_stock_rejected
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="ISF-1",
                                                 contract_number="C-ISF")
    lot = make_lot(product["id"], lot_code="L-ISF", qty_received=3)
    release = make_release(order["id"], order["version"], qty=10,
                           scheduled_ship_date="2026-09-01")
    resp = api.pick_release(release["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)

    assert get_lot(lot["id"])["qty_on_hand"] == 3, "no partial allocation persisted"
    after = get_release(release["id"])
    assert after["status"] == "SCHEDULED"
    assert after["allocations"] == []


# ---------------------------------------------------------------------------
# Difficulty / cross_entity_state_dependency / release_ship_gated_by_contract_status
# ---------------------------------------------------------------------------


def test_release_ship_blocked_after_contract_expired(api):
    """PRD §3.7: "Shipment, also by an `AccountManager`, moves a `PICKED`
    release to `SHIPPED` and requires the order's contract to be `ACTIVE`
    (`ERR_CONTRACT_NOT_ACTIVE`)."
    PRD §2.4: "every contract still `ACTIVE` whose `term_end` is strictly
    earlier than the new clock date transitions to `EXPIRED`"

    Design: Difficulty/cross_entity_state_dependency/release_ship_gated_by_contract_status
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="CB-G2",
                                                 contract_number="C-1008")
    release = make_release(order["id"], order["version"], qty=4,
                           scheduled_ship_date="2027-06-01")
    make_lot(product["id"], lot_code="L-G2", qty_received=10)
    validate_success(api.pick_release(release["id"], AM), 200)

    sweep = set_clock("2028-01-01T00:00:00Z")
    assert sweep["contracts_expired"] == 1, (
        f"term_end 2027-12-31 < 2028-01-01 -> contract swept: {sweep}"
    )

    resp = api.ship_release(release["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)


def test_release_ship_blocked_release_and_contract_states_unchanged(api):
    """PRD §3.7: "requires the order's contract to be `ACTIVE`
    (`ERR_CONTRACT_NOT_ACTIVE`)"
    PRD §2.4: "Sweeps never reverse: once a lot is `EXPIRED` or a contract is
    `EXPIRED`, moving the clock does not restore it."

    Design: Difficulty/cross_entity_state_dependency/release_ship_gated_by_contract_status
    """
    product, contract, order = _setup_open_order(committed_qty=10, sku="CB-G2B",
                                                 contract_number="C-1008B")
    release = make_release(order["id"], order["version"], qty=4,
                           scheduled_ship_date="2027-06-01")
    make_lot(product["id"], lot_code="L-G2B", qty_received=10)
    validate_success(api.pick_release(release["id"], AM), 200)
    set_clock("2028-01-01T00:00:00Z")

    resp = api.ship_release(release["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    assert get_release(release["id"])["status"] == "PICKED", (
        "release stays PICKED after the rejected ship"
    )
    assert get_contract(contract["id"])["status"] == "EXPIRED"
