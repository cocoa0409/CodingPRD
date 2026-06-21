"""Composite setup helpers for the Laundry & Dry-Cleaning Delivery API.

Every test runs against a freshly-restarted, empty server, so each fixture
builds all of its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup step failed" rather than a confusing assertion error.

Identity threading: a Customer is entity_backed, so every customer-owned call
uses make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_customer_headers,
    admin_headers, dispatch_headers, plant_headers, adjuster_headers,
)
from . import factories as f
from .constants import TEST_CLOCK_UTC


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601=TEST_CLOCK_UTC):
    """Pin the server's logical clock (PRD §3.11)."""
    return get_success_data(api_client.set_clock(to_iso8601, admin_headers()))


# --------------------------------------------------------------------------
# Tier 1 / Tier 2: catalogue + base entities
# --------------------------------------------------------------------------
def create_customer(zone_code="Z1", **overrides):
    payload = f.create_customer_payload(zone_code=zone_code, **overrides)
    return get_success_data(api_client.create_customer(payload, admin_headers()))


def create_plan(**overrides):
    payload = f.create_subscription_plan_payload(**overrides)
    return get_success_data(api_client.create_subscription_plan(payload, admin_headers()))


def create_subscription(customer_id, plan_id):
    payload = f.create_subscription_payload(customer_id, plan_id)
    return get_success_data(api_client.create_subscription(payload, make_customer_headers(customer_id)))


def create_pickup_window(zone_code="Z1", stop_capacity=5,
                         start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T11:00:00Z"):
    payload = f.create_route_window_payload(
        zone_code=zone_code, window_kind="PICKUP",
        start_utc=start_utc, end_utc=end_utc, stop_capacity=stop_capacity,
    )
    return get_success_data(api_client.create_route_window(payload, dispatch_headers()))


def create_delivery_window(zone_code="Z1", stop_capacity=5,
                           start_utc="2026-06-03T09:00:00Z", end_utc="2026-06-03T11:00:00Z"):
    payload = f.create_route_window_payload(
        zone_code=zone_code, window_kind="DELIVERY",
        start_utc=start_utc, end_utc=end_utc, stop_capacity=stop_capacity,
    )
    return get_success_data(api_client.create_route_window(payload, dispatch_headers()))


def create_locker(zone_code="Z1", compartment_count=4, **overrides):
    payload = f.create_locker_payload(zone_code=zone_code, compartment_count=compartment_count, **overrides)
    return get_success_data(api_client.create_locker(payload, dispatch_headers()))


def create_zone_setup(zone_code="Z1", pickup_capacity=5, delivery_capacity=5,
                      pickup_start="2026-06-01T09:00:00Z", pickup_end="2026-06-01T11:00:00Z",
                      delivery_start="2026-06-03T09:00:00Z", delivery_end="2026-06-03T11:00:00Z"):
    """Create one customer + a PICKUP and DELIVERY window in the same zone.

    Returns (customer, pickup_window, delivery_window).

    Pin the server clock to TEST_CLOCK_UTC (2026-06-01T08:00:00Z) first so SLA
    math is deterministic: pickup sets ready_by_utc = clock + standard SLA
    (PRD §3.4), which must land at or before the default delivery window's
    start_utc (2026-06-03T09:00:00Z) for dispatch (PRD §3.6) to pass. Without a
    pinned clock the real wall-clock pushes ready_by_utc past the delivery
    window and dispatch is correctly rejected with ERR_DELIVERY_BEFORE_READY.
    """
    set_clock(TEST_CLOCK_UTC)
    customer = create_customer(zone_code=zone_code)
    pickup = create_pickup_window(zone_code=zone_code, stop_capacity=pickup_capacity,
                                  start_utc=pickup_start, end_utc=pickup_end)
    delivery = create_delivery_window(zone_code=zone_code, stop_capacity=delivery_capacity,
                                      start_utc=delivery_start, end_utc=delivery_end)
    return customer, pickup, delivery


def add_garment(order_id, customer_id, **garment_overrides):
    payload = f.create_garment_payload(**garment_overrides)
    return get_success_data(api_client.add_garment(order_id, payload, make_customer_headers(customer_id)))


def create_order(customer, pickup, delivery, **order_overrides):
    payload = f.create_order_payload(customer["id"], pickup["id"], delivery["id"], **order_overrides)
    return get_success_data(api_client.create_order(payload, make_customer_headers(customer["id"])))


# --------------------------------------------------------------------------
# Tier 3: full-lifecycle order shortcuts
# --------------------------------------------------------------------------
def create_order_with_garments(customer=None, pickup=None, delivery=None,
                               garments=None, order_overrides=None, zone_code="Z1"):
    """Create (customer/windows if absent) + a CREATED order + its garment lines.

    garments: list of dicts of garment-payload overrides (each becomes one line).
              Defaults to a single 2000g WASH_FOLD line.
    Returns (customer, pickup, delivery, order, [garment, ...]).
    """
    if customer is None or pickup is None or delivery is None:
        customer, pickup, delivery = create_zone_setup(zone_code=zone_code)
    if garments is None:
        garments = [{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}]
    order = create_order(customer, pickup, delivery, **(order_overrides or {}))
    created = [add_garment(order["id"], customer["id"], **g) for g in garments]
    return customer, pickup, delivery, order, created


def schedule_order(order, customer):
    return get_success_data(api_client.schedule_order(order["id"], make_customer_headers(customer["id"])))


def pickup_order(order):
    return get_success_data(api_client.pickup_order(order["id"], dispatch_headers()))


def log_intake(order, garment, **measurement):
    """Record plant-measured values. measurement keys: actual_weight_grams / actual_piece_count."""
    return get_success_data(api_client.log_intake(order["id"], garment["id"], measurement, plant_headers()))


def start_processing(order):
    return get_success_data(api_client.start_processing(order["id"], plant_headers()))


def finish_clean(order, garment):
    return get_success_data(api_client.finish_clean(order["id"], garment["id"], plant_headers()))


def mark_lost(order, garment):
    return get_success_data(api_client.mark_lost(order["id"], garment["id"], plant_headers()))


def qc_hold(order):
    return get_success_data(api_client.qc_hold(order["id"], plant_headers()))


def qc_pass(order):
    return get_success_data(api_client.qc_pass(order["id"], plant_headers()))


def get_order(order_id, customer_id):
    return get_success_data(api_client.get_order(order_id, make_customer_headers(customer_id)))


def _default_actuals(garment_payload):
    """Pick the plant-measured value matching the garment's service type."""
    st = garment_payload.get("service_type", "WASH_FOLD")
    if st == "WASH_FOLD":
        return {"actual_weight_grams": garment_payload.get("declared_weight_grams", 2000)}
    return {"actual_piece_count": garment_payload.get("declared_piece_count", 1)}


def order_in_processing(customer=None, pickup=None, delivery=None,
                        garments=None, actuals=None, order_overrides=None, zone_code="Z1"):
    """Drive an order all the way to IN_PROCESSING with every garment logged + processing started.

    garments: list of garment-payload override dicts.
    actuals:  optional parallel list of measurement dicts (defaults derived from declared).
    Returns (customer, pickup, delivery, order, [garment, ...]).
    """
    if garments is None:
        garments = [{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}]
    customer, pickup, delivery, order, created = create_order_with_garments(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=garments, order_overrides=order_overrides, zone_code=zone_code,
    )
    schedule_order(order, customer)
    pickup_order(order)
    for idx, garment in enumerate(created):
        meas = (actuals[idx] if actuals else None) or _default_actuals(garments[idx])
        log_intake(order, garment, **meas)
    start_processing(order)
    return customer, pickup, delivery, order, created


def order_at_qc_hold(customer=None, pickup=None, delivery=None,
                     garments=None, actuals=None, order_overrides=None, zone_code="Z1",
                     finish_all=True):
    """Drive an order to QC_HOLD: in-processing → finish-clean each garment → qc-hold.

    Returns (customer, pickup, delivery, order, [garment, ...]).
    """
    customer, pickup, delivery, order, created = order_in_processing(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=garments, actuals=actuals, order_overrides=order_overrides, zone_code=zone_code,
    )
    if finish_all:
        for garment in created:
            finish_clean(order, garment)
    qc_hold(order)
    return customer, pickup, delivery, order, created


def order_at_ready(customer=None, pickup=None, delivery=None,
                   garments=None, actuals=None, order_overrides=None, zone_code="Z1"):
    """Drive an order to READY (qc-pass creates the DRAFT invoice).

    Returns (customer, pickup, delivery, order, [garment, ...]).
    """
    customer, pickup, delivery, order, created = order_at_qc_hold(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=garments, actuals=actuals, order_overrides=order_overrides, zone_code=zone_code,
    )
    qc_pass(order)
    return customer, pickup, delivery, order, created


def order_delivered(customer=None, pickup=None, delivery=None,
                    garments=None, actuals=None, order_overrides=None, zone_code="Z1"):
    """Drive a DOORSTEP order all the way to DELIVERED.

    Returns (customer, pickup, delivery, order, [garment, ...]).
    """
    customer, pickup, delivery, order, created = order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=garments, actuals=actuals, order_overrides=order_overrides, zone_code=zone_code,
    )
    get_success_data(api_client.dispatch_delivery(order["id"], dispatch_headers()))
    get_success_data(api_client.confirm_delivery(order["id"], dispatch_headers()))
    return customer, pickup, delivery, order, created


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def file_claim(order, customer, subject_kind="ORDER", declared_value_cents=5000,
               garment=None, expected_order_version=None):
    """File a claim against an order; reads the current order version when not supplied."""
    if expected_order_version is None:
        expected_order_version = get_order(order["id"], customer["id"])["version"]
    overrides = {}
    if garment is not None:
        overrides["garment_id"] = garment["id"]
    payload = f.create_claim_payload(
        order["id"], subject_kind, declared_value_cents, expected_order_version, **overrides
    )
    return get_success_data(api_client.create_claim(payload, make_customer_headers(customer["id"])))


def investigate(claim):
    return get_success_data(api_client.investigate_claim(claim["id"], adjuster_headers()))


def approve(claim):
    return get_success_data(api_client.approve_claim(claim["id"], adjuster_headers()))


def reject(claim):
    return get_success_data(api_client.reject_claim(claim["id"], adjuster_headers()))


def appeal(claim, customer):
    return get_success_data(api_client.appeal_claim(claim["id"], make_customer_headers(customer["id"])))


def settle(claim):
    return get_success_data(api_client.settle_claim(claim["id"], adjuster_headers()))


def settle_garment_claim(order, customer, garment, declared_value_cents):
    """File → investigate → approve → settle a GARMENT claim on a LOST garment.

    Returns the settled claim. Used to seed customer wallet_credit_cents.
    """
    claim = file_claim(order, customer, subject_kind="GARMENT",
                       declared_value_cents=declared_value_cents, garment=garment)
    investigate(claim)
    approve(claim)
    return settle(claim)


def seed_wallet_via_settled_claim(customer, pickup, delivery, declared_value_cents):
    """Drive a throwaway order to a LOST garment, settle a GARMENT claim, and
    thereby credit the customer's wallet. Returns the settled claim.

    Settlement = round_half_up(min(declared, 20000) * 0.80), ceiling-bounded by
    30000 per order (PRD §3.10).
    """
    _, _, _, order, garments = order_in_processing(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
    )
    mark_lost(order, garments[0])
    return settle_garment_claim(order, customer, garments[0], declared_value_cents)


# --------------------------------------------------------------------------
# Locker assignments
# --------------------------------------------------------------------------
def create_locker_assignment(order, locker, compartment_index=1,
                             hold_start_utc="2026-06-03T09:00:00Z",
                             hold_end_utc="2026-06-03T18:00:00Z"):
    payload = f.create_locker_assignment_payload(
        order["id"], locker["id"], compartment_index=compartment_index,
        hold_start_utc=hold_start_utc, hold_end_utc=hold_end_utc,
    )
    return get_success_data(api_client.create_locker_assignment(payload, dispatch_headers()))


def ready_locker_order_with_assignment(zone_code="Z1", compartment_index=1,
                                       hold_start_utc="2026-06-03T09:00:00Z",
                                       hold_end_utc="2026-06-03T18:00:00Z",
                                       locker=None):
    """Drive a LOCKER-handoff order to READY and create one RESERVED assignment.

    Returns (customer, pickup, delivery, order, garments, locker, assignment).
    """
    customer, pickup, delivery = create_zone_setup(zone_code=zone_code)
    if locker is None:
        locker = create_locker(zone_code=zone_code)
    _, _, _, order, garments = order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        order_overrides={"handoff_method": "LOCKER"},
    )
    assignment = create_locker_assignment(
        order, locker, compartment_index=compartment_index,
        hold_start_utc=hold_start_utc, hold_end_utc=hold_end_utc,
    )
    return customer, pickup, delivery, order, garments, locker, assignment


# --------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------
def cancelled_subscription(plan_overrides=None):
    """Create a subscription and cancel it once; return (customer, subscription, version_after_cancel)."""
    customer = create_customer()
    plan = create_plan(**(plan_overrides or {"tier": "LITE", "monthly_fee_cents": 3000,
                                             "included_wash_fold_grams": 2000,
                                             "overage_rate_cents_per_kg": 350,
                                             "dryclean_discount_pct": 0.10}))
    sub = create_subscription(customer["id"], plan["id"])
    get_success_data(api_client.cancel_subscription(
        sub["id"], {"expected_subscription_version": sub["version"]},
        make_customer_headers(customer["id"]),
    ))
    refreshed = get_success_data(api_client.get_subscription(sub["id"], make_customer_headers(customer["id"])))
    return customer, refreshed, refreshed["version"]
