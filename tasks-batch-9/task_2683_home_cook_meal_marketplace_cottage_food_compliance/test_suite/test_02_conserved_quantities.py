"""The two conserved counters of this platform, exercised across a reversal.

A production window's `committed_meals` must survive a placement followed by its
cancellation, and a cook's `ytd_cottage_revenue_cents` must survive a capture
followed by a full cook-fault refund. Both quantities are asserted through the
derived fields that hang off them, because a naive compensation leaves residue
there rather than in the counter itself.
"""

from test_helpers import fixtures as fx
from test_helpers import (
    DINER_ONE_HEADERS,
    assert_capacity_triple,
    assert_charge_breakdown,
    assert_cook,
    assert_order,
    assert_refund_event,
    assert_refund_three_bucket_identity,
    is_iso8601_timestamp,
    order_payload,
    validate_success,
)

_UNIT_PRICE_CENTS = 1200
_CAPACITY_MEALS = 10
_ORDER_QUANTITY = 4

#: The captured order of the second instance: 1200 x 2 = 2400 subtotal, a
#: 216-cent diner service fee, a 2616-cent total, 540 of commission and
#: 1860 of cook earnings.
_CAPTURED_SUBTOTAL_CENTS = 2400
_CAPTURED_TOTAL_CENTS = 2616
_CAPTURED_COMMISSION_CENTS = 540
_CAPTURED_EARNINGS_CENTS = 1860
_DINER_FEE_CENTS = 216


def _open_window_of_ten(api):
    """An ACTIVE, CLEAR cook with one APPROVED dish and an empty capacity-10 window."""
    return fx.selling_cook(
        api,
        cook_overrides={"weekly_capacity_meals": _CAPACITY_MEALS},
        item_overrides={
            "name": "Pastel de Nata Box",
            "food_category": "BAKED_NON_TCS",
            "allergens": ["WHEAT", "EGG", "MILK"],
            "shelf_life_days": 3,
            "unit_price_cents": _UNIT_PRICE_CENTS,
        },
        window_overrides={"capacity_meals": _CAPACITY_MEALS},
    )


def _place_four(api, setup):
    """Place the quantity-4 order that moves the capacity triple off its zero point."""
    return fx.order_in_scenario(
        api, setup, quantity=_ORDER_QUANTITY, diner_headers=DINER_ONE_HEADERS
    )


def _captured_order(api):
    """A quantity-2 order walked all the way to DELIVERED, so its payment captured."""
    setup = fx.selling_cook(
        api,
        cook_overrides={"weekly_capacity_meals": 8},
        item_overrides={
            "name": "Idli Steamer Pack",
            "food_category": "NON_TCS",
            "allergens": ["SOY"],
            "shelf_life_days": 4,
            "unit_price_cents": _UNIT_PRICE_CENTS,
        },
        window_overrides={"capacity_meals": 8},
    )
    order = fx.routed_order(api, setup, quantity=2, diner_headers=DINER_ONE_HEADERS)
    fx.open_window_into_production(api, setup)
    order = fx.hand_off_order(api, setup, order)
    fx.set_clock(api, "2026-08-08T17:00:00Z")
    setup["order"] = fx.deliver_order(api, order)
    return setup


# --------------------------------------------------------------------------
# Conserved quantity 1: meal capacity held on a production window
# --------------------------------------------------------------------------
def test_01_cancellation_restores_the_committed_meals_and_its_derived_pair(api):
    """Placing 4 meals on a capacity-10 window and cancelling restores (0, 0, 10) exactly.

    PRD: "After a placement and its cancellation, `committed_meals` must equal its exact pre-placement value, and `spoilage_reserve_meals` and `effective_capacity_meals` must be re-derived from that restored count."
    Design: Difficulty/compensating_invariant/capacity_units_conserved_place_then_cancel
    """
    setup = _open_window_of_ten(api)
    assert_capacity_triple(fx.read_window(api, setup.window["id"]), 0, _CAPACITY_MEALS)

    order = _place_four(api, setup)
    assert_capacity_triple(fx.read_window(api, setup.window["id"]), 4, _CAPACITY_MEALS)

    fx.cancel_order(api, order, reason="diner changed plans")

    window = fx.read_window(api, setup.window["id"])
    assert_capacity_triple(window, 0, _CAPACITY_MEALS)
    assert window["committed_meals"] == 0
    assert window["spoilage_reserve_meals"] == 0
    assert window["effective_capacity_meals"] == _CAPACITY_MEALS


def test_02_the_identical_order_is_admitted_again_after_the_cancellation(api):
    """The byte-identical quantity-4 placement is re-admitted with HTTP 201.

    PRD: "The reserve must leave no residue: a window that admitted an order and then saw it cancelled must still admit the identical order again."
    Design: Difficulty/compensating_invariant/capacity_units_conserved_place_then_cancel
    """
    setup = _open_window_of_ten(api)
    order = _place_four(api, setup)
    fx.cancel_order(api, order, reason="diner changed plans")

    payload = order_payload(
        setup.menu_item["id"],
        setup.window["id"],
        setup.zone["id"],
        quantity=_ORDER_QUANTITY,
        diner_contact_email="t1@example.com",
    )
    replacement = validate_success(api.create_order(payload, DINER_ONE_HEADERS), 201)

    assert_order(
        replacement,
        quantity=_ORDER_QUANTITY,
        fulfillment_status="PLACED",
        payment_status="AUTHORIZED",
    )
    assert_capacity_triple(fx.read_window(api, setup.window["id"]), 4, _CAPACITY_MEALS)


def test_03_a_cancelled_order_recognises_no_revenue_at_all(api):
    """The cancelled order voids its authorisation and leaves every cook counter at zero.

    PRD: "Cancellation moves `PLACED → CANCELLED` or `ROUTED → CANCELLED`, sets `cancelled_reason` to `DINER_REQUEST`, moves `payment_status` `AUTHORIZED → VOIDED` so that no revenue is ever recognised, and decrements the owning window's `committed_meals` by the order's `quantity`, restoring the conserved capacity counter to its exact pre-placement value."
    Design: Difficulty/compensating_invariant/capacity_units_conserved_place_then_cancel
    """
    setup = _open_window_of_ten(api)
    order = _place_four(api, setup)

    cancelled = fx.cancel_order(api, order, reason="diner changed plans")

    assert_order(
        cancelled,
        fulfillment_status="CANCELLED",
        payment_status="VOIDED",
        cancelled_reason="DINER_REQUEST",
    )
    assert fx.read_window(api, setup.window["id"])["committed_meals"] == 0
    assert_cook(
        fx.read_cook(api, setup.cook_id),
        ytd_cottage_revenue_cents=0,
        ytd_gross_sales_cents=0,
        pending_payout_cents=0,
        cap_status="UNDER_CAP",
    )


# --------------------------------------------------------------------------
# Conserved quantity 2: recognised cottage-food revenue in cents
# --------------------------------------------------------------------------
def test_04_full_cook_fault_refund_returns_cottage_revenue_to_its_pre_capture_value(api):
    """Refunding the whole 2616-cent charge at COOK fault drives recognised revenue back to 0.

    PRD: "Taken together these two facts mean that capturing an order and then refunding its full `total_charge_cents` with `fault_party` of `COOK` returns `ytd_cottage_revenue_cents` to exactly its pre-capture value: the cook-side chargeback plus the reversed commission together equal the recognised subtotal, and the diner service fee — which was never part of `subtotal_cents` — lands entirely in `platform_absorbed_cents`."
    Design: Difficulty/compensating_invariant/cottage_revenue_cents_conserved_capture_then_full_cook_fault_refund
    """
    setup = _captured_order(api)
    order = setup.order
    assert_charge_breakdown(order)
    assert_order(
        order,
        payment_status="CAPTURED",
        subtotal_cents=_CAPTURED_SUBTOTAL_CENTS,
        diner_service_fee_cents=_DINER_FEE_CENTS,
        total_charge_cents=_CAPTURED_TOTAL_CENTS,
        platform_commission_cents=_CAPTURED_COMMISSION_CENTS,
        cook_earnings_cents=_CAPTURED_EARNINGS_CENTS,
    )
    assert_cook(
        fx.read_cook(api, setup.cook_id),
        ytd_cottage_revenue_cents=_CAPTURED_SUBTOTAL_CENTS,
        pending_payout_cents=_CAPTURED_EARNINGS_CENTS,
    )

    refund = fx.record_refund(
        api,
        order["id"],
        reason="QUALITY",
        fault_party="COOK",
        refund_amount_cents=_CAPTURED_TOTAL_CENTS,
        settle_immediately=True,
    )

    assert_refund_event(
        refund,
        refund_amount_cents=_CAPTURED_TOTAL_CENTS,
        cook_chargeback_cents=_CAPTURED_EARNINGS_CENTS,
        commission_reversed_cents=_CAPTURED_COMMISSION_CENTS,
        platform_absorbed_cents=_DINER_FEE_CENTS,
    )
    assert_cook(fx.read_cook(api, setup.cook_id), ytd_cottage_revenue_cents=0)


def test_05_the_three_bucket_split_neither_creates_nor_destroys_a_cent(api):
    """1860 + 540 + 216 lands exactly on the 2616-cent refund amount.

    PRD: "Independently, every refund event satisfies the identity that its `refund_amount_cents` equals the sum of its `cook_chargeback_cents`, its `commission_reversed_cents` and its `platform_absorbed_cents` — the three-bucket split neither creates nor destroys a cent."
    Design: Difficulty/compensating_invariant/cottage_revenue_cents_conserved_capture_then_full_cook_fault_refund
    """
    setup = _captured_order(api)

    refund = fx.record_refund(
        api,
        setup.order["id"],
        reason="QUALITY",
        fault_party="COOK",
        refund_amount_cents=_CAPTURED_TOTAL_CENTS,
        settle_immediately=True,
    )

    assert_refund_three_bucket_identity(refund)
    assert (
        refund["cook_chargeback_cents"]
        + refund["commission_reversed_cents"]
        + refund["platform_absorbed_cents"]
        == _CAPTURED_TOTAL_CENTS
    )
    assert_refund_event(refund, status="SETTLED")
    assert is_iso8601_timestamp(refund["settled_at"])
    order = fx.read_order(api, setup.order["id"])
    assert_order(
        order,
        payment_status="REFUNDED",
        refunded_cents=_CAPTURED_TOTAL_CENTS,
        cook_chargeback_cents=_CAPTURED_EARNINGS_CENTS,
        commission_reversed_cents=_CAPTURED_COMMISSION_CENTS,
        platform_absorbed_cents=_DINER_FEE_CENTS,
    )


def test_06_the_refund_lowers_cottage_revenue_but_never_gross_sales(api):
    """Recognised gross stays at 2400 while the cap-metered figure returns to zero.

    PRD: "`ytd_cottage_revenue_cents` is the recognised amount less the reversed amount, while `ytd_gross_sales_cents` is the recognised amount alone — which is why a refund lowers the cap-metered figure but does not lower the commission-tier selector."
    Design: Difficulty/compensating_invariant/cottage_revenue_cents_conserved_capture_then_full_cook_fault_refund
    """
    setup = _captured_order(api)
    before = fx.read_cook(api, setup.cook_id)
    assert_cook(
        before,
        ytd_gross_sales_cents=_CAPTURED_SUBTOTAL_CENTS,
        ytd_cottage_revenue_cents=_CAPTURED_SUBTOTAL_CENTS,
    )

    fx.record_refund(
        api,
        setup.order["id"],
        reason="QUALITY",
        fault_party="COOK",
        refund_amount_cents=_CAPTURED_TOTAL_CENTS,
        settle_immediately=True,
    )

    after = fx.read_cook(api, setup.cook_id)
    assert_cook(
        after,
        ytd_gross_sales_cents=_CAPTURED_SUBTOTAL_CENTS,
        ytd_cottage_revenue_cents=0,
        pending_payout_cents=0,
        cap_status="UNDER_CAP",
    )
