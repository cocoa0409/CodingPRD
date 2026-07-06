"""Cross-entity cascades from cancel and payment failure; dual-variant cancellation
refund; stem and money conservation invariants.

Covers difficulty rules dual_variant_calc.refund_estimate_vs_actual_on_cancel,
transitive_cascade.cancel_subscription_cascade_to_lot_depth3 and
payment_fail_cascade_to_scheduled_shipments_depth2, compensating_invariant.stem_conservation
and money_conservation.
"""
from test_helpers import (
    api_client,
    make_customer_headers,
    TEST_USERS,
    validate_error,
    validate_success,
    ApiErrorId,
    setup_plan_customer_subscription,
    setup_sourcing_shipment,
    setup_captured_charge_subscription,
    get_subscription_shipments,
    get_subscription_charges,
    get_subscription,
    get_customer,
    get_lot,
    list_customer_wallet_entries,
    source_shipment,
    reserve_allocation,
    capture_current_charge,
    capture_payment_succeed,
    capture_payment_fail,
    cancel,
    pause,
    set_clock,
    create_plan,
    create_customer,
    create_subscription_for,
)
from test_helpers.factories import refund_payload


# =====================================================================
# Difficulty §1.8: dual_variant_calc.refund_estimate_vs_actual_on_cancel
# =====================================================================


def test_cancel_preview_estimate_includes_sourcing_shipment():
    """PRD §3.8: "The cancel preview reports an `estimated_refund_cents` and a `refundable_shipment_count` computed under the estimate variant, which is more optimistic than the actual: it counts every current-cycle shipment that is neither `DELIVERED` nor `CANCELLED` (thereby treating shipments in `SOURCING`, `SOURCED`, `SUBSTITUTED`, and beyond as refundable) and multiplies that count by the per-shipment value."

    WEEKLY / DELUXE / vase (renewal 6000+1500+1200=8700) / per_shipment 2175; 4 shipments,
    move shipment[1] to SOURCING. Estimate counts all 4 as refundable -> 4*2175 = 8700.

    Design: Difficulty/dual_variant_calc/refund_estimate_vs_actual_on_cancel
    """
    plan = create_plan(cadence="WEEKLY", base_fee_cents=6000)
    customer = create_customer()
    subscription = create_subscription_for(
        customer, plan, size="DELUXE", vase_addon=True
    )
    # Capture first charge SUCCEEDED so refund destination is meaningful.
    charge = capture_current_charge(subscription["id"])
    capture_payment_succeed(charge["id"])
    shipments = get_subscription_shipments(subscription["id"])
    # Move shipment[1] to SOURCING.
    source_shipment(shipments[1]["id"])
    res = api_client.cancel_preview_subscription(
        subscription["id"], make_customer_headers(customer["id"])
    )
    preview = validate_success(res)
    # 4 shipments none DELIVERED/CANCELLED -> 4 * 2175 = 8700
    assert preview["estimated_refund_cents"] == 8700
    assert preview["refundable_shipment_count"] == 4


def test_cancel_actual_refund_excludes_sourcing_shipment():
    """PRD §3.8: "it is the per-shipment value (as defined in §3.4) multiplied by the number of current-cycle shipments that were in `SCHEDULED` or `SKIPPED` status. This actual refund deliberately excludes any shipment that had progressed past `SCHEDULED` into sourcing or beyond, because those shipments' stems were already committed or in progress."
    PRD §3.8: "When `refund_destination` is `WALLET`, the system credits that refund by creating a wallet entry with `reason` of `REFUND`".

    Same setup as estimate: 4 shipments, 1 in SOURCING, 3 SCHEDULED. Actual = 3 * 2175 = 6525.

    Design: Difficulty/dual_variant_calc/refund_estimate_vs_actual_on_cancel
    """
    plan = create_plan(cadence="WEEKLY", base_fee_cents=6000)
    customer = create_customer()
    subscription = create_subscription_for(
        customer, plan, size="DELUXE", vase_addon=True
    )
    charge = capture_current_charge(subscription["id"])
    capture_payment_succeed(charge["id"])
    shipments = get_subscription_shipments(subscription["id"])
    source_shipment(shipments[1]["id"])
    cancel(subscription["id"], customer["id"], refund_destination="WALLET")
    fetched_customer = get_customer(customer["id"])
    # actual refund = 3 SCHEDULED * 2175 = 6525
    assert fetched_customer["wallet_credit_cents"] == 6525


# =====================================================================
# Difficulty §1.8: transitive_cascade.cancel_subscription_cascade_to_lot_depth3
# =====================================================================


def test_cancel_cascades_shipment_and_allocation_and_restores_lot_availability():
    """PRD §3.8: "Cancellation triggers a three-level cascade that settles entirely within the request: every non-terminal shipment of the subscription — those in `SCHEDULED`, `SOURCING`, `SOURCED`, or `SUBSTITUTED` status — moves to `CANCELLED`; each cancelled shipment releases its `RESERVED` and `COMMITTED` allocations to `RELEASED`; and each released allocation restores its lot's `quantity_available`."

    24 stems RESERVED on a lot of total 100 -> available 76 before cancel; after cancel
    -> available restored to 100.

    Design: Difficulty/transitive_cascade/cancel_subscription_cascade_to_lot_depth3
    """
    _plan, customer, subscription, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 100,
            "unit_cost_cents": 40,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-04T12:00:00Z",
    )
    allocation = reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=24,
        hold_start="2026-03-04T13:00:00Z",
        hold_end="2026-03-04T14:00:00Z",
    )
    lot_before = get_lot(lot["id"])
    assert lot_before["quantity_available"] == 76
    cancelled_sub = cancel(subscription["id"], customer["id"], refund_destination="WALLET")
    assert cancelled_sub["lifecycle_status"] == "CANCELLED"
    # Shipment cascaded to CANCELLED (hop 1).
    fetched_shipment_res = api_client.get_shipment(
        shipment["id"], TEST_USERS["fulfillment_ops_headers"]
    )
    fetched_shipment = validate_success(fetched_shipment_res)
    assert fetched_shipment["status"] == "CANCELLED"
    # Allocation cascaded to RELEASED (hop 2).
    alloc_res = api_client.list_shipment_allocations(
        shipment["id"], TEST_USERS["fulfillment_ops_headers"]
    )
    alloc_data = validate_success(alloc_res)
    assert alloc_data[0]["status"] == "RELEASED"
    # Lot quantity_available restored (hop 3).
    lot_after = get_lot(lot["id"])
    assert lot_after["quantity_available"] == 100


def test_cancel_cascades_non_terminal_shipments_to_cancelled():
    """PRD §3.8: "every non-terminal shipment of the subscription — those in `SCHEDULED`, `SOURCING`, `SOURCED`, or `SUBSTITUTED` status — moves to `CANCELLED`".

    Fresh subscription has 4 SCHEDULED shipments; cancel drops each to CANCELLED.

    Design: Difficulty/transitive_cascade/cancel_subscription_cascade_to_lot_depth3
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    cancel(subscription["id"], customer["id"])
    for sh in shipments:
        res = api_client.get_shipment(sh["id"], TEST_USERS["fulfillment_ops_headers"])
        fetched = validate_success(res)
        assert fetched["status"] == "CANCELLED", (
            f"Shipment {sh['id']} status must be CANCELLED after cancel cascade; got {fetched['status']}"
        )


# =====================================================================
# Difficulty §1.8: transitive_cascade.payment_fail_cascade_to_scheduled_shipments_depth2
# =====================================================================


def test_payment_fail_flips_billing_to_past_due_and_cancels_scheduled_shipments():
    """PRD §3.7: "A `FAILED` outcome moves the charge to `FAILED` and cascades on the billing axis: the subscription's `billing_status` flips to `PAST_DUE`, and that flip cancels every current-cycle shipment still in `SCHEDULED` status, moving each to `CANCELLED` and releasing any stems those shipments held."

    Design: Difficulty/transitive_cascade/payment_fail_cascade_to_scheduled_shipments_depth2
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    charge = capture_current_charge(subscription["id"])
    failed_charge = capture_payment_fail(charge["id"])
    assert failed_charge["status"] == "FAILED"
    sub_after = get_subscription(subscription["id"])
    assert sub_after["billing_status"] == "PAST_DUE"
    shipments = get_subscription_shipments(subscription["id"])
    for sh in shipments:
        assert sh["status"] == "CANCELLED", (
            f"Every SCHEDULED cycle-1 shipment must be CANCELLED after payment fail cascade; got {sh['status']}"
        )


def test_payment_fail_charge_status_becomes_failed():
    """PRD §3.7: "A `FAILED` outcome moves the charge to `FAILED` and cascades on the billing axis: the subscription's `billing_status` flips to `PAST_DUE`".

    Depth-1 hop before the cascade: the charge itself moves from PENDING to FAILED.

    Design: Difficulty/transitive_cascade/payment_fail_cascade_to_scheduled_shipments_depth2
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    charge = capture_current_charge(subscription["id"])
    failed = capture_payment_fail(charge["id"])
    assert failed["status"] == "FAILED"


# =====================================================================
# Difficulty §1.8: compensating_invariant.stem_conservation_reserve_then_release
# =====================================================================


def test_stem_conservation_holds_while_reserved():
    """PRD §2.5: "Stems are conserved as whole units: for any stem lot, its original `quantity_total` always equals its current `quantity_available` plus the sum of stems currently held by active allocations."

    Reserving 25 stems from a lot total 60 leaves quantity_available = 35, and total = 35 + 25.

    Design: Difficulty/compensating_invariant/stem_conservation_reserve_then_release
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 60,
            "unit_cost_cents": 40,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-05T00:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=25,
        hold_start="2026-03-05T08:00:00Z",
        hold_end="2026-03-05T10:00:00Z",
    )
    lot_now = get_lot(lot["id"])
    assert lot_now["quantity_available"] == 35
    # Conservation: 60 = 35 + 25
    assert lot_now["quantity_total"] == lot_now["quantity_available"] + 25


def test_stem_conservation_restored_after_cancel_release():
    """PRD §2.5: "These two invariants must hold after every request completes."
    PRD §2.7: "When a cascade removes stems that were being held — through a skip, a shipment cancellation, or a subscription cancellation — the released allocations move to `RELEASED` and the affected stem lot's available quantity is restored in the same request, so the stem-conservation invariant of §2.5 always holds on read."

    After cancel releases the 25-stem allocation, quantity_available == quantity_total.

    Design: Difficulty/compensating_invariant/stem_conservation_reserve_then_release
    """
    _plan, customer, subscription, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 60,
            "unit_cost_cents": 40,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-05T00:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=25,
        hold_start="2026-03-05T08:00:00Z",
        hold_end="2026-03-05T10:00:00Z",
    )
    cancel(subscription["id"], customer["id"])
    lot_after = get_lot(lot["id"])
    assert lot_after["quantity_available"] == lot_after["quantity_total"] == 60


# =====================================================================
# Difficulty §1.8: compensating_invariant.money_conservation_capture_then_refund
# =====================================================================


def test_partial_refund_bumps_refunded_cents_status_stays_captured():
    """PRD §3.7: "Otherwise the charge's `refunded_cents` increases by the refunded amount, and once `refunded_cents` reaches the full `amount_cents` the charge's `status` becomes `REFUNDED` (a partial refund leaves the charge `CAPTURED` with a positive `refunded_cents`). Every refund creates a wallet entry with `reason` of `REFUND` and a positive `amount_cents` equal to the refunded amount".

    DELUXE+vase renewal = 8700; refund 6525 (partial) -> refunded_cents=6525, status=CAPTURED.

    Design: Difficulty/compensating_invariant/money_conservation_capture_then_refund
    """
    plan, customer, subscription, charge = setup_captured_charge_subscription(
        size="DELUXE", vase_addon=True
    )
    res = api_client.refund_charge(
        charge["id"], refund_payload(6525), TEST_USERS["billing_admin_headers"]
    )
    refunded = validate_success(res)
    assert refunded["refunded_cents"] == 6525
    assert refunded["status"] == "CAPTURED"


def test_wallet_credit_equals_sum_of_wallet_entries_after_partial_refund():
    """PRD §2.5: "Money is likewise conserved: a customer's wallet balance always equals the sum of that customer's wallet entries."
    PRD §3.7: "Every refund creates a wallet entry with `reason` of `REFUND` and a positive `amount_cents` equal to the refunded amount".

    After a 6525 partial refund, wallet_credit_cents == 6525 == sum(entries).

    Design: Difficulty/compensating_invariant/money_conservation_capture_then_refund
    """
    plan, customer, subscription, charge = setup_captured_charge_subscription(
        size="DELUXE", vase_addon=True
    )
    api_client.refund_charge(
        charge["id"], refund_payload(6525), TEST_USERS["billing_admin_headers"]
    )
    fetched_customer = get_customer(customer["id"])
    wallet_entries = list_customer_wallet_entries(customer)
    assert fetched_customer["wallet_credit_cents"] == 6525
    total_entries = sum(e["amount_cents"] for e in wallet_entries)
    assert total_entries == 6525
