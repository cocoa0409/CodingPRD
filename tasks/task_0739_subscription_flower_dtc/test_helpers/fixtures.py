"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors, not confusing assertion failures.

Identity threading (PRD §2.1): every ownership-gated call passes headers built with
make_customer_headers(customer["id"]) — never a shared TEST_USERS fallback for
entity_backed:Customer.

Every test starts against an empty database (harness restarts server between tests),
so every fixture builds its state from scratch using only PRD-declared endpoints.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    change_subscription_payload,
    confirm_sourced_payload,
    create_allocation_payload,
    create_carrier_route_payload,
    create_customer_payload,
    create_plan_payload,
    create_stem_lot_payload,
    create_subscription_payload,
    create_substitution_rule_payload,
    redeem_offer_payload,
    refund_payload,
    set_clock_payload,
    ship_shipment_payload,
    simulate_payment_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)


# --- Tier 0: unique-email helper ---


def _uniq_email(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@x.com"


# --- Tier 1: primitives ---


def create_plan(cadence: str = "WEEKLY", base_fee_cents: int = 6000, name: str = "Weekly Classic", **overrides) -> dict:
    payload = create_plan_payload(
        name=name, cadence=cadence, base_fee_cents=base_fee_cents, **overrides
    )
    res = api_client.create_plan(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def create_customer(email: str = None, full_name: str = "Test Customer", **overrides) -> dict:
    if email is None:
        email = _uniq_email("cust")
    payload = create_customer_payload(email=email, full_name=full_name, **overrides)
    res = api_client.create_customer(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def set_clock(iso_instant: str) -> None:
    """Advance/set the logical clock (PRD §2.6). Returns None (data is empty)."""
    api_client.set_clock(set_clock_payload(iso_instant), TEST_USERS["platform_admin_headers"])


def create_stem_lot(
    variety: str = "ROSE",
    grade: str = "A",
    quantity_total: int = 100,
    unit_cost_cents: int = 40,
    sourced_at: str = "2026-03-04T00:00:00Z",
    shelf_life_hours: int = 240,
) -> dict:
    payload = {
        "variety": variety,
        "grade": grade,
        "quantity_total": quantity_total,
        "unit_cost_cents": unit_cost_cents,
        "sourced_at": sourced_at,
        "shelf_life_hours": shelf_life_hours,
    }
    res = api_client.create_stem_lot(payload, TEST_USERS["fulfillment_ops_headers"])
    return get_success_data(res)


def create_carrier_route(zone: str = "Z1", service_date: str = "2026-03-10T00:00:00Z") -> dict:
    payload = create_carrier_route_payload(zone=zone, service_date=service_date)
    res = api_client.create_carrier_route(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def create_substitution_rule(from_variety: str = "ROSE", to_variety: str = "TULIP", allowed: bool = True) -> dict:
    payload = create_substitution_rule_payload(
        from_variety=from_variety, to_variety=to_variety, allowed=allowed
    )
    res = api_client.create_substitution_rule(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


# --- Tier 2: composite subscription setup ---


def create_subscription_for(
    customer: dict,
    plan: dict,
    size: str = "ORIGINAL",
    vase_addon: bool = False,
    start_date: str = "2026-03-01T00:00:00Z",
    **overrides,
) -> dict:
    """Create a subscription owned by the given customer against the given plan.
    Default start_date matches the server's default clock (PRD §2.6)."""
    payload = create_subscription_payload(
        customer_id=customer["id"],
        plan_id=plan["id"],
        size=size,
        vase_addon=vase_addon,
        start_date=start_date,
        **overrides,
    )
    res = api_client.create_subscription(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def setup_plan_customer_subscription(
    cadence: str = "WEEKLY",
    base_fee_cents: int = 6000,
    size: str = "ORIGINAL",
    vase_addon: bool = False,
    start_date: str = "2026-03-01T00:00:00Z",
    customer_email: str = None,
) -> tuple[dict, dict, dict]:
    """Common preamble: plan + customer + subscription. Returns (plan, customer, subscription)."""
    plan = create_plan(cadence=cadence, base_fee_cents=base_fee_cents)
    customer = create_customer(email=customer_email)
    subscription = create_subscription_for(
        customer, plan, size=size, vase_addon=vase_addon, start_date=start_date
    )
    return plan, customer, subscription


def get_subscription_shipments(subscription_id: str) -> list:
    """List all shipments of a subscription (uses PlatformAdmin — non-ownership read)."""
    res = api_client.list_subscription_shipments(
        subscription_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def get_subscription_charges(subscription_id: str) -> list:
    res = api_client.list_subscription_charges(
        subscription_id, TEST_USERS["billing_admin_headers"]
    )
    return get_success_data(res)


def get_subscription(subscription_id: str) -> dict:
    """Fetch a subscription using PlatformAdmin (non-ownership read)."""
    res = api_client.get_subscription(
        subscription_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def get_customer(customer_id: str) -> dict:
    res = api_client.get_customer(customer_id, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def get_lot(lot_id: str) -> dict:
    res = api_client.get_stem_lot(lot_id, TEST_USERS["fulfillment_ops_headers"])
    return get_success_data(res)


def list_customer_wallet_entries(customer: dict) -> list:
    """Uses the customer's OWN headers (ownership-gated read)."""
    res = api_client.list_customer_wallet_entries(
        customer["id"], make_customer_headers(customer["id"])
    )
    return get_success_data(res)


def list_customer_win_back_offers(customer: dict) -> list:
    """Uses the customer's OWN headers (ownership-gated read)."""
    res = api_client.list_customer_win_back_offers(
        customer["id"], make_customer_headers(customer["id"])
    )
    return get_success_data(res)


# --- Tier 3: subscription lifecycle helpers ---


def capture_current_charge(subscription_id: str) -> dict:
    """Return the earliest cycle-1 charge of the subscription (charges are ordered by (cycle_index, created_at))."""
    charges = get_subscription_charges(subscription_id)
    return charges[0]


def capture_payment_succeed(charge_id: str) -> dict:
    """Simulate SUCCEEDED payment; returns the updated charge."""
    res = api_client.simulate_payment(
        charge_id, simulate_payment_payload("SUCCEEDED"), TEST_USERS["billing_admin_headers"]
    )
    return get_success_data(res)


def capture_payment_fail(charge_id: str) -> dict:
    res = api_client.simulate_payment(
        charge_id, simulate_payment_payload("FAILED"), TEST_USERS["billing_admin_headers"]
    )
    return get_success_data(res)


def source_shipment(shipment_id: str) -> dict:
    res = api_client.source_shipment(
        shipment_id, {}, TEST_USERS["fulfillment_ops_headers"]
    )
    return get_success_data(res)


def reserve_allocation(shipment_id: str, lot_id: str, quantity_reserved: int, hold_start: str, hold_end: str) -> dict:
    payload = create_allocation_payload(
        lot_id=lot_id,
        quantity_reserved=quantity_reserved,
        hold_start=hold_start,
        hold_end=hold_end,
    )
    res = api_client.create_shipment_allocation(
        shipment_id, payload, TEST_USERS["fulfillment_ops_headers"]
    )
    return get_success_data(res)


def confirm_sourced(shipment_id: str, substitution_applied: bool = False, from_variety: str = None, to_variety: str = None) -> dict:
    payload = confirm_sourced_payload(
        substitution_applied=substitution_applied,
        from_variety=from_variety,
        to_variety=to_variety,
    )
    res = api_client.confirm_sourced_shipment(
        shipment_id, payload, TEST_USERS["fulfillment_ops_headers"]
    )
    return get_success_data(res)


def ship(shipment_id: str, route_id: str, delivery_window_start: str, delivery_window_end: str) -> dict:
    payload = ship_shipment_payload(
        route_id=route_id,
        delivery_window_start=delivery_window_start,
        delivery_window_end=delivery_window_end,
    )
    res = api_client.ship_shipment(
        shipment_id, payload, TEST_USERS["fulfillment_ops_headers"]
    )
    return get_success_data(res)


def deliver(shipment_id: str) -> dict:
    res = api_client.deliver_shipment(
        shipment_id, {}, TEST_USERS["fulfillment_ops_headers"]
    )
    return get_success_data(res)


def pause(subscription_id: str, customer_id: str) -> dict:
    res = api_client.pause_subscription(
        subscription_id, {}, make_customer_headers(customer_id)
    )
    return get_success_data(res)


def cancel(subscription_id: str, customer_id: str, refund_destination: str = None, reason: str = None) -> dict:
    payload: dict = {}
    if refund_destination is not None:
        payload["refund_destination"] = refund_destination
    if reason is not None:
        payload["reason"] = reason
    res = api_client.cancel_subscription(
        subscription_id, payload, make_customer_headers(customer_id)
    )
    return get_success_data(res)


# --- Tier 4: composite scenarios matching design-index setup chains ---


def setup_sourcing_shipment(
    plan_cadence: str = "WEEKLY",
    plan_base_fee_cents: int = 6000,
    size: str = "ORIGINAL",
    lot_kwargs: dict = None,
    clock_at_source: str = "2026-03-04T12:00:00Z",
    which_shipment_index: int = 0,
) -> tuple[dict, dict, dict, dict, dict]:
    """Full setup to place shipment[k] in SOURCING with a fresh lot available.

    Returns (plan, customer, subscription, shipment, lot).
    Callers can then reserve/commit as they wish.

    Sequence:
      1. Create plan + customer + subscription (opens cycle-1 shipments).
      2. Create the lot (fresh, per lot_kwargs).
      3. Set clock to `clock_at_source` (so any allocation created next is at that clock).
      4. Source the chosen shipment (SCHEDULED -> SOURCING).
    """
    if lot_kwargs is None:
        lot_kwargs = {}
    plan, customer, subscription = setup_plan_customer_subscription(
        cadence=plan_cadence, base_fee_cents=plan_base_fee_cents, size=size
    )
    shipments = get_subscription_shipments(subscription["id"])
    shipment = shipments[which_shipment_index]
    lot = create_stem_lot(**lot_kwargs)
    set_clock(clock_at_source)
    sourced_shipment = source_shipment(shipment["id"])
    return plan, customer, subscription, sourced_shipment, lot


def setup_sourcing_shipment_with_allocation(
    plan_cadence: str = "WEEKLY",
    plan_base_fee_cents: int = 6000,
    size: str = "ORIGINAL",
    lot_kwargs: dict = None,
    clock_at_source: str = "2026-03-04T12:00:00Z",
    quantity_reserved: int = 20,
    hold_start: str = "2026-03-04T13:00:00Z",
    hold_end: str = "2026-03-04T14:00:00Z",
) -> tuple[dict, dict, dict, dict, dict, dict]:
    """Extends setup_sourcing_shipment with one RESERVED allocation.
    Returns (plan, customer, subscription, shipment, lot, allocation)."""
    plan, customer, subscription, shipment, lot = setup_sourcing_shipment(
        plan_cadence=plan_cadence,
        plan_base_fee_cents=plan_base_fee_cents,
        size=size,
        lot_kwargs=lot_kwargs,
        clock_at_source=clock_at_source,
    )
    allocation = reserve_allocation(
        shipment_id=shipment["id"],
        lot_id=lot["id"],
        quantity_reserved=quantity_reserved,
        hold_start=hold_start,
        hold_end=hold_end,
    )
    return plan, customer, subscription, shipment, lot, allocation


def setup_captured_charge_subscription(
    size: str = "DELUXE",
    vase_addon: bool = True,
) -> tuple[dict, dict, dict, dict]:
    """Plan + customer + subscription + cycle-1 charge simulated SUCCEEDED.
    Returns (plan, customer, subscription, charge)."""
    plan, customer, subscription = setup_plan_customer_subscription(
        size=size, vase_addon=vase_addon
    )
    charge = capture_current_charge(subscription["id"])
    captured = capture_payment_succeed(charge["id"])
    return plan, customer, subscription, captured


def setup_cancelled_with_offer(
    size: str = "ORIGINAL",
    vase_addon: bool = False,
    refund_destination: str = None,
) -> tuple[dict, dict, dict, dict]:
    """Plan + customer + subscription + cancel -> subscription CANCELLED + WinBackOffer OFFERED.

    Returns (plan, customer, subscription_after_cancel, offer).
    Cancel is invoked without advancing the clock, so offer.expires_at == cancel_time + 30 days
    lands on 2026-03-31 (default clock 2026-03-01).
    """
    plan, customer, subscription = setup_plan_customer_subscription(
        size=size, vase_addon=vase_addon
    )
    cancelled_sub = cancel(subscription["id"], customer["id"], refund_destination=refund_destination)
    offers = list_customer_win_back_offers(customer)
    return plan, customer, cancelled_sub, offers[0]


def setup_shipments_sourced(
    num_shipments: int = 3,
    plan_base_fee_cents: int = 6000,
    lot_kwargs: dict = None,
    clock_at_source: str = "2026-03-04T12:00:00Z",
) -> tuple[dict, dict, dict, list, dict]:
    """WEEKLY subscription; source + confirm-sourced (no substitution) the first N shipments.
    Returns (plan, customer, subscription, shipments_after_confirm, lot).

    Each sourced shipment is committed without any allocation (per design-index route-window
    test — commit is legal from SOURCING with zero allocations; result is stem_cost_cents == 0
    if the impl needs a sum-over-zero-set; the design instance only asserts route-window overlap
    on the ship call, not stem_cost). If allocations are needed, callers should reserve
    before invoking this helper.
    """
    if lot_kwargs is None:
        lot_kwargs = {}
    plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    set_clock(clock_at_source)
    lot = create_stem_lot(**lot_kwargs)
    confirmed = []
    for i in range(num_shipments):
        sh = shipments[i]
        source_shipment(sh["id"])
        confirmed_sh = confirm_sourced(sh["id"], substitution_applied=False)
        confirmed.append(confirmed_sh)
    return plan, customer, subscription, confirmed, lot
