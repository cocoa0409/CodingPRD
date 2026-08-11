"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh server
(the harness restarts the API before each test and the logical clock resets
to 2026-05-01T00:00:00Z). All setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BIN_CAPACITY_KG
from .factories import (
    create_bin_payload,
    create_commercial_plan_payload,
    create_contamination_tag_payload,
    create_credit_adjustment_payload,
    create_pause_payload,
    create_redemption_payload,
    create_route_payload,
    create_service_plan_payload,
    create_subscriber_payload,
    create_subscription_payload,
    create_weigh_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_ops_headers,
    make_subscriber_headers,
)

OPS = TEST_USERS["ops_headers"]
ANON = TEST_USERS["anonymous_headers"]
DRIVER = TEST_USERS["driver_headers"]


# --- Tier 1/2: single-entity creation and small hierarchies ------------------

def create_plan_res(**overrides) -> dict:
    """Create the canonical residential plan (weekly 1200, rate 10, allowance 2)."""
    return get_success_data(
        api_client.create_service_plan(create_service_plan_payload(**overrides), OPS)
    )


def create_plan_com(**overrides) -> dict:
    """Create the canonical commercial plan (base 3000, per-kg 7, included 40)."""
    return get_success_data(
        api_client.create_service_plan(create_commercial_plan_payload(**overrides), OPS)
    )


def create_route(code="R1", weekday="MON", max_stops=5) -> dict:
    return get_success_data(
        api_client.create_route(
            create_route_payload(code=code, weekday=weekday, max_stops=max_stops), OPS
        )
    )


def create_bins(count, bin_type="BIN_35L", nominal_capacity_kg=None) -> list:
    """Register `count` clean depot bins; returns them in creation order."""
    if nominal_capacity_kg is None:
        nominal_capacity_kg = BIN_CAPACITY_KG[bin_type]
    bins = []
    for _ in range(count):
        bins.append(
            get_success_data(
                api_client.create_bin(
                    create_bin_payload(
                        bin_type=bin_type, nominal_capacity_kg=nominal_capacity_kg
                    ),
                    OPS,
                )
            )
        )
    return bins


def create_subscriber(subscriber_type="RESIDENTIAL", email="a@x.com", **overrides) -> dict:
    return get_success_data(
        api_client.create_subscriber(
            create_subscriber_payload(
                subscriber_type=subscriber_type, email=email, **overrides
            ),
            ANON,
        )
    )


def create_subscription(subscriber_id, plan_id, route_id, start_date="2026-05-01") -> dict:
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(subscriber_id, plan_id, route_id, start_date),
            OPS,
        )
    )


def setup_active_subscription(
    subscriber_type="RESIDENTIAL",
    bin_count=2,
    route_code="R1",
    max_stops=5,
    start_date="2026-05-01",
    subscriber_email="a@x.com",
    plan_overrides=None,
) -> dict:
    """Plan + route + clean depot bins + subscriber + ACTIVE subscription.

    Residential setups use BIN_35L (20 kg nominal); commercial use BIN_240L
    (60 kg nominal). Returns every created entity.
    """
    if subscriber_type == "COMMERCIAL":
        plan = create_plan_com(**(plan_overrides or {}))
        bin_type = plan["bin_type"]
    else:
        plan = create_plan_res(**(plan_overrides or {}))
        bin_type = plan["bin_type"]
    route = create_route(code=route_code, max_stops=max_stops)
    bins = create_bins(bin_count, bin_type=bin_type)
    subscriber = create_subscriber(subscriber_type, email=subscriber_email)
    subscription = create_subscription(
        subscriber["id"], plan["id"], route["id"], start_date
    )
    return {
        "plan": plan,
        "route": route,
        "bins": bins,
        "subscriber": subscriber,
        "subscription": subscription,
    }


# --- Reads -------------------------------------------------------------------

def get_subscriber(subscriber_id) -> dict:
    return get_success_data(api_client.get_subscriber(subscriber_id, OPS))


def get_subscription(subscription_id) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, OPS))


def get_pickup(pickup_id) -> dict:
    return get_success_data(api_client.get_pickup(pickup_id, OPS))


def get_bin(bin_id) -> dict:
    return get_success_data(api_client.get_bin(bin_id, OPS))


def get_tag(tag_id) -> dict:
    return get_success_data(api_client.get_contamination_tag(tag_id, OPS))


def get_route(route_id) -> dict:
    return get_success_data(api_client.get_route(route_id, OPS))


def get_invoice(invoice_id) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, OPS))


def get_redemption(redemption_id) -> dict:
    return get_success_data(api_client.get_redemption(redemption_id, OPS))


def get_stock() -> dict:
    return get_success_data(api_client.get_compost_stock(OPS))


def list_pickups_for_subscription(subscription_id) -> list:
    return get_success_data(
        api_client.list_pickups(OPS, params={"subscription_id": subscription_id})
    )


def list_invoices_for_subscriber(subscriber_id) -> list:
    return get_success_data(
        api_client.list_invoices(OPS, params={"subscriber_id": subscriber_id})
    )


def list_credit_entries(subscriber_id=None, pickup_id=None, entry_type=None) -> list:
    params = {}
    if subscriber_id is not None:
        params["subscriber_id"] = subscriber_id
    if pickup_id is not None:
        params["pickup_id"] = pickup_id
    if entry_type is not None:
        params["entry_type"] = entry_type
    return get_success_data(api_client.list_credit_entries(OPS, params=params))


def list_bins(params=None) -> list:
    return get_success_data(api_client.list_bins(OPS, params=params or {}))


# --- Tier 3: lifecycle shortcuts ----------------------------------------------

def generate_stops(route_id, service_date) -> dict:
    """Returns the generation payload {created_count, pickup_ids}."""
    return get_success_data(
        api_client.generate_stops(route_id, {"service_date": service_date}, OPS)
    )


def generate_and_get_pickups(route_id, subscription_id, service_dates) -> list:
    """Generate stops for each date (in order) and return the subscription's
    pickups in created_at ascending order."""
    for service_date in service_dates:
        generate_stops(route_id, service_date)
    return list_pickups_for_subscription(subscription_id)


def complete_pickup(pickup_id, fullness_pct=0.5, driver_id="drv-1") -> dict:
    return get_success_data(
        api_client.complete_pickup(
            pickup_id, {"fullness_pct": fullness_pct}, make_driver_headers(driver_id)
        )
    )


def miss_pickup(pickup_id, driver_id="drv-1") -> dict:
    return get_success_data(api_client.miss_pickup(pickup_id, make_driver_headers(driver_id)))


def skip_pickup(pickup_id, subscriber_id) -> dict:
    """Skip is Subscriber-only and ownership-gated: caller is the owner."""
    return get_success_data(
        api_client.skip_pickup(pickup_id, make_subscriber_headers(subscriber_id))
    )


def void_pickup(pickup_id) -> dict:
    return get_success_data(api_client.void_pickup(pickup_id, OPS))


def tag_pickup(pickup_id, severity="LOW", category="PLASTIC", driver_id="drv-1") -> dict:
    return get_success_data(
        api_client.create_contamination_tag(
            pickup_id,
            create_contamination_tag_payload(severity=severity, category=category),
            make_driver_headers(driver_id),
        )
    )


def confirm_tag(tag_id, ops_id="ops-1") -> dict:
    return get_success_data(api_client.confirm_tag(tag_id, make_ops_headers(ops_id)))


def waive_tag(tag_id, ops_id="ops-1") -> dict:
    return get_success_data(api_client.waive_tag(tag_id, make_ops_headers(ops_id)))


def dispute_tag(tag_id, subscriber_id) -> dict:
    return get_success_data(
        api_client.dispute_tag(tag_id, make_subscriber_headers(subscriber_id))
    )


def post_weigh_ticket(route_id, service_date, gross_kg, tare_kg, driver_id="drv-1") -> dict:
    return get_success_data(
        api_client.post_weigh_ticket(
            route_id,
            create_weigh_ticket_payload(service_date, gross_kg, tare_kg),
            make_driver_headers(driver_id),
        )
    )


def pause_subscription(subscription_id, pause_start, pause_end) -> dict:
    return get_success_data(
        api_client.pause_subscription(
            subscription_id, create_pause_payload(pause_start, pause_end), OPS
        )
    )


def resume_subscription(subscription_id) -> dict:
    return get_success_data(api_client.resume_subscription(subscription_id, OPS))


def cancel_subscription(subscription_id) -> dict:
    return get_success_data(api_client.cancel_subscription(subscription_id, OPS))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def run_billing(week_start_date) -> dict:
    return get_success_data(
        api_client.run_billing({"week_start_date": week_start_date}, OPS)
    )


def post_credit_adjustment(subscriber_id, amount_cents, reason="promo") -> dict:
    return get_success_data(
        api_client.create_credit_adjustment(
            subscriber_id, create_credit_adjustment_payload(amount_cents, reason), OPS
        )
    )


def create_redemption(subscriber_id, bags) -> dict:
    return get_success_data(
        api_client.create_redemption(
            create_redemption_payload(subscriber_id, bags),
            make_subscriber_headers(subscriber_id),
        )
    )


# --- Tier 4: threshold / accumulation targeting --------------------------------

def setup_completed_pickup(
    service_date="2026-06-01",
    fullness_pct=0.5,
    subscriber_type="RESIDENTIAL",
    bin_count=2,
    plan_overrides=None,
    subscriber_email="a@x.com",
) -> dict:
    """ACTIVE subscription with one generated pickup, completed by the driver.

    Residential default: BIN_35L (20 kg) at fullness 0.5 -> estimated 10.00 kg.
    """
    env = setup_active_subscription(
        subscriber_type=subscriber_type,
        bin_count=bin_count,
        plan_overrides=plan_overrides,
        subscriber_email=subscriber_email,
    )
    pickups = generate_and_get_pickups(
        env["route"]["id"], env["subscription"]["id"], [service_date]
    )
    env["pickup"] = pickups[0]
    env["completed"] = complete_pickup(pickups[0]["id"], fullness_pct)
    return env


def setup_weighed_pickup(
    service_date="2026-06-01",
    fullness_pct=0.5,
    gross_kg=45.0,
    tare_kg=5.0,
    subscriber_type="RESIDENTIAL",
    bin_count=2,
) -> dict:
    """Completed pickup plus a posted weigh ticket for its route+date."""
    env = setup_completed_pickup(
        service_date=service_date,
        fullness_pct=fullness_pct,
        subscriber_type=subscriber_type,
        bin_count=bin_count,
    )
    env["ticket"] = post_weigh_ticket(
        env["route"]["id"], service_date, gross_kg, tare_kg
    )
    env["pickup"] = get_pickup(env["pickup"]["id"])
    return env


def setup_issued_invoice(
    week_start="2026-05-04",
    fullness_pct=0.5,
    subscriber_type="RESIDENTIAL",
    bin_count=2,
    credit_adjustment_cents=None,
    weigh=False,
) -> dict:
    """Full chain to an ISSUED invoice for one subscriber.

    Residential default: one COMPLETED pickup at 0.5 in the billing week
    (credit 100 SPRING), then the billing run. With weigh=True a weigh ticket
    netting exactly the estimated kilograms is posted first (required before
    billing any week containing a COMPLETED commercial pickup).
    """
    env = setup_completed_pickup(
        service_date=week_start,
        fullness_pct=fullness_pct,
        subscriber_type=subscriber_type,
        bin_count=bin_count,
    )
    if weigh:
        est_kg = env["completed"]["estimated_kg"]
        env["ticket"] = post_weigh_ticket(
            env["route"]["id"], week_start, est_kg + 5.0, 5.0
        )
    if credit_adjustment_cents is not None:
        post_credit_adjustment(env["subscriber"]["id"], credit_adjustment_cents)
    env["billing"] = run_billing(week_start)
    invoices = list_invoices_for_subscriber(env["subscriber"]["id"])
    env["invoice"] = invoices[0] if invoices else None
    return env


def setup_delinquent_subscriber(week_start="2026-05-04", overdue_date="2026-05-20T00:00:00Z") -> dict:
    """ISSUED invoice left unpaid past its due date: the subscriber reads back
    DELINQUENT once the logical clock passes the due date (2026-05-18 for the
    2026-05-04 week)."""
    env = setup_issued_invoice(week_start=week_start)
    set_clock(overdue_date)
    return env
