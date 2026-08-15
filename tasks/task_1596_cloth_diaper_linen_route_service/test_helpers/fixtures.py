"""Composite setup helpers.

Every test runs against an empty database (the runner restarts the server
before each test), so each helper builds its preconditions from scratch using
only endpoints the PRD declares. Setup calls use the lenient get_success_data
validator so a broken precondition surfaces as a clear "Setup step failed"
rather than a confusing assertion failure later.

The standard onboarding chain (PRD 3.2) is: plan -> zone -> pool -> customer ->
subscription (kit RESERVED, deposit charged) -> kit ISSUE -> customer ACTIVATE
-> subscription ACTIVATE. setup_active_subscription() runs the whole chain and
returns a context dict; most fixtures compose on top of it.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, FORMULA_F_SANI, ROUTE_DATE_MON
from .factories import (
    complete_stop_payload,
    create_batch_payload,
    create_case_payload,
    create_customer_payload,
    create_formula_payload,
    create_intake_payload,
    create_pause_payload,
    create_plan_payload,
    create_pool_payload,
    create_route_payload,
    create_subscription_payload,
    create_swap_payload,
    create_zone_payload,
    generate_invoice_payload,
    pool_adjustment_payload,
)
from .test_users import (
    make_billing_admin_headers,
    make_customer_headers,
    make_plant_operator_headers,
    make_platform_admin_headers,
    make_route_driver_headers,
)

ADMIN = make_platform_admin_headers()
DRIVER = make_route_driver_headers()
OPERATOR = make_plant_operator_headers("op-1")
OPERATOR_2 = make_plant_operator_headers("op-2")
BILLING = make_billing_admin_headers()


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> Dict[str, Any]:
    """Advance the logical clock (PlatformAdmin only, PRD 2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_plan(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def create_zone(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_zone(create_zone_payload(**overrides), ADMIN))


def create_pool(size_code: str = "MEDIUM") -> Dict[str, Any]:
    return get_success_data(api_client.create_pool(create_pool_payload(size_code), ADMIN))


def adjust_pool(pool_id: str, adjustment_type: str, units: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.pool_adjustment(
            pool_id, pool_adjustment_payload(adjustment_type, units), ADMIN
        )
    )


def fund_pool(size_code: str = "MEDIUM", units: int = 500) -> Dict[str, Any]:
    """Create a size pool and ACQUIRE stock into it."""
    pool = create_pool(size_code)
    if units:
        pool = adjust_pool(pool["id"], "ACQUIRE", units)
    return pool


def create_customer(zone_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_customer(create_customer_payload(zone_id, **overrides), ADMIN)
    )


def create_subscription(customer: Dict, plan: Dict, zone: Dict, **overrides: Any) -> Dict[str, Any]:
    payload = create_subscription_payload(customer["id"], plan["id"], zone["id"], **overrides)
    return get_success_data(api_client.create_subscription(payload, ADMIN))


def find_kit(subscription_id: str) -> Dict[str, Any]:
    kits = get_success_data(
        api_client.list_kits(ADMIN, params={"subscription_id": subscription_id})
    )
    assert isinstance(kits, list) and len(kits) == 1, (
        f"expected exactly one starter kit for subscription {subscription_id}"
    )
    return kits[0]


def kit_event(kit_id: str, event_type: str, headers: Optional[Dict] = None, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(fields)
    return get_success_data(api_client.kit_event(kit_id, payload, headers or OPERATOR))


def customer_event(customer_id: str, event_type: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.customer_event(customer_id, {"event_type": event_type}, ADMIN)
    )


def subscription_event(subscription_id: str, event_type: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.subscription_event(subscription_id, {"event_type": event_type}, headers or ADMIN)
    )


def read_subscription(subscription_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def read_subscription_version(subscription_id: str) -> int:
    return read_subscription(subscription_id)["version"]


def read_pool(pool_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pool(pool_id, ADMIN))


def read_pool_version(pool_id: str) -> int:
    return read_pool(pool_id)["version"]


def read_route(route_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_route(route_id, ADMIN))


def read_route_version(route_id: str) -> int:
    return read_route(route_id)["version"]


def read_customer(customer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def read_pause(pause_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pause(pause_id, ADMIN))


def read_stop(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_route_stop(stop_id, ADMIN))


def read_batch(batch_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_batch(batch_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 — onboarding chain (PRD 3.2)
# ---------------------------------------------------------------------------


def _activate_member(
    zone: Dict, plan: Dict, customer_overrides: Optional[Dict] = None, sub_overrides: Optional[Dict] = None
) -> Dict[str, Any]:
    """Create a customer + subscription in the zone on the plan, then run the
    onboarding chain: kit ISSUE -> customer ACTIVATE -> subscription ACTIVATE."""
    customer = create_customer(zone["id"], **(customer_overrides or {}))
    subscription = create_subscription(customer, plan, zone, **(sub_overrides or {}))
    kit = find_kit(subscription["id"])
    kit_event(kit["id"], "ISSUE")
    customer_event(customer["id"], "ACTIVATE")
    subscription = subscription_event(subscription["id"], "ACTIVATE")
    return {
        "customer": customer,
        "customer_headers": make_customer_headers(customer["id"]),
        "subscription": subscription,
        "kit": find_kit(subscription["id"]),
        "subscription_version": subscription["version"],
    }


def setup_active_subscription(
    *,
    plan_overrides: Optional[Dict] = None,
    zone_overrides: Optional[Dict] = None,
    sub_overrides: Optional[Dict] = None,
    customer_overrides: Optional[Dict] = None,
    size_code: str = "MEDIUM",
    pool_units: int = 500,
    set_initial_clock: bool = True,
) -> Dict[str, Any]:
    """Full onboarding chain. Returns a context dict with plan, zone, pool,
    customer, customer_headers, subscription, kit, subscription_version."""
    if set_initial_clock:
        set_clock(DEFAULT_CLOCK)
    plan = create_plan(**(plan_overrides or {}))
    zone = create_zone(**(zone_overrides or {}))
    pool = fund_pool(size_code, pool_units)
    ctx: Dict[str, Any] = {"plan": plan, "zone": zone, "pool": pool}
    ctx.update(_activate_member(zone, plan, customer_overrides, sub_overrides))
    return ctx


def add_active_subscription(
    ctx: Dict[str, Any],
    *,
    plan: Optional[Dict] = None,
    sub_overrides: Optional[Dict] = None,
    customer_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Add a second fully-activated customer+subscription to an existing
    context's zone and (by default) plan."""
    return _activate_member(
        ctx["zone"], plan or ctx["plan"], customer_overrides, sub_overrides
    )


# ---------------------------------------------------------------------------
# Tier 2 — routes and stops (PRD 3.3)
# ---------------------------------------------------------------------------


def create_route(zone: Dict, route_date: str = ROUTE_DATE_MON) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_route(create_route_payload(zone["id"], route_date), ADMIN)
    )


def find_stop(route_id: str, subscription_id: str) -> Dict[str, Any]:
    stops = get_success_data(
        api_client.list_route_stops(
            ADMIN, params={"route_id": route_id, "subscription_id": subscription_id}
        )
    )
    assert isinstance(stops, list) and len(stops) == 1, (
        f"expected exactly one stop for subscription {subscription_id} on route {route_id}"
    )
    return stops[0]


def list_stops(route_id: str) -> List[Dict[str, Any]]:
    stops = get_success_data(
        api_client.list_route_stops(ADMIN, params={"route_id": route_id, "limit": 100})
    )
    assert isinstance(stops, list)
    return stops


def sequence_route(route_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.sequence_route(route_id, ADMIN))


def route_event(route_id: str, event_type: str) -> Dict[str, Any]:
    return get_success_data(api_client.route_event(route_id, {"event_type": event_type}, ADMIN))


def drive_route_to_in_progress(route_id: str, route_date: str = ROUTE_DATE_MON) -> int:
    """Sequence -> LOCK -> advance the clock into the route date -> START.
    Returns the route's version after START (the OCC token for completions)."""
    sequence_route(route_id)
    route_event(route_id, "LOCK")
    set_clock(f"{route_date}T08:00:00Z")
    route = route_event(route_id, "START")
    return route["version"]


def complete_stop(
    stop_id: str,
    route_version: int,
    clean_items: int = 80,
    soiled_bags: int = 1,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    payload = complete_stop_payload(clean_items, soiled_bags, route_version)
    return get_success_data(api_client.complete_stop(stop_id, payload, headers or DRIVER))


def stop_event(stop_id: str, event_type: str, headers: Optional[Dict] = None, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(fields)
    return get_success_data(api_client.route_stop_event(stop_id, payload, headers or DRIVER))


def setup_route_in_progress(
    ctx: Dict[str, Any], route_date: str = ROUTE_DATE_MON
) -> Dict[str, Any]:
    """Create a route for the context's zone, drive it to IN_PROGRESS, and
    attach route/stop/route_version to the context (single-subscription ctx)."""
    route = create_route(ctx["zone"], route_date)
    stop = find_stop(route["id"], ctx["subscription"]["id"])
    route_version = drive_route_to_in_progress(route["id"], route_date)
    ctx.update({"route": route, "stop": stop, "route_version": route_version})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — intakes and the wash plant (PRD 3.4, 3.5)
# ---------------------------------------------------------------------------


def record_intake(
    stop_id: str, scale_weight_g: int, soil_level: str = "NORMAL", headers: Optional[Dict] = None
) -> Dict[str, Any]:
    payload = create_intake_payload(stop_id, scale_weight_g, soil_level)
    return get_success_data(api_client.create_intake(payload, headers or OPERATOR))


def intake_event(intake_id: str, event_type: str, headers: Optional[Dict] = None, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(fields)
    return get_success_data(api_client.intake_event(intake_id, payload, headers or OPERATOR))


def create_formula(**overrides: Any) -> Dict[str, Any]:
    payload = create_formula_payload(**overrides)
    if "formula_code" not in overrides:
        payload["formula_code"] = FORMULA_F_SANI["formula_code"]
    return get_success_data(api_client.create_formula(payload, ADMIN))


def create_batch(
    formula_id: str, soil_level: str = "HEAVY", water_hardness: str = "HARD"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_batch(create_batch_payload(formula_id, soil_level, water_hardness), OPERATOR)
    )


def load_batch(batch_id: str, intake_ids: List[str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.load_batch(batch_id, {"soiled_intake_ids": intake_ids}, OPERATOR)
    )


def batch_event(
    batch_id: str, event_type: str, headers: Optional[Dict] = None, **fields: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(fields)
    return get_success_data(api_client.batch_event(batch_id, payload, headers or OPERATOR))


def start_wash(batch_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """LOADED -> WASHING; records the caller's X-User-ID as wash_started_by."""
    return batch_event(batch_id, "START_WASH", headers or OPERATOR)


def record_sanitization(
    batch_id: str,
    peak_temp_celsius: int,
    dwell_seconds: int,
    chlorine_ppm: int,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """WASHING -> VALIDATING; records the caller's X-User-ID as validated_by."""
    return batch_event(
        batch_id,
        "RECORD_SANITIZATION",
        headers or OPERATOR_2,
        peak_temp_celsius=peak_temp_celsius,
        dwell_seconds=dwell_seconds,
        chlorine_ppm=chlorine_ppm,
    )


def setup_completed_stop_with_intake(
    *,
    clean_items: int = 80,
    scale_weight_g: int = 8000,
    intake_soil: str = "NORMAL",
    plan_overrides: Optional[Dict] = None,
    zone_overrides: Optional[Dict] = None,
    route_date: str = ROUTE_DATE_MON,
) -> Dict[str, Any]:
    """Active subscription -> route IN_PROGRESS -> stop COMPLETED at
    clean_items -> intake recorded at scale_weight_g. Returns the full ctx."""
    ctx = setup_active_subscription(
        plan_overrides=plan_overrides, zone_overrides=zone_overrides
    )
    setup_route_in_progress(ctx, route_date)
    complete_stop(ctx["stop"]["id"], ctx["route_version"], clean_items=clean_items)
    intake = record_intake(ctx["stop"]["id"], scale_weight_g, intake_soil)
    ctx["intake"] = intake
    return ctx


def setup_loaded_batch(
    *,
    clean_items: int = 80,
    scale_weight_g: int = 8000,
    intake_soil: str = "NORMAL",
    batch_soil: str = "HEAVY",
    water_hardness: str = "HARD",
    plan_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Everything in setup_completed_stop_with_intake plus a wash batch in
    LOADED holding that intake."""
    ctx = setup_completed_stop_with_intake(
        clean_items=clean_items,
        scale_weight_g=scale_weight_g,
        intake_soil=intake_soil,
        plan_overrides=plan_overrides,
    )
    formula = create_formula()
    batch = create_batch(formula["id"], batch_soil, water_hardness)
    batch = load_batch(batch["id"], [ctx["intake"]["id"]])
    ctx.update({"formula": formula, "batch": batch})
    return ctx


def setup_batch_in_washing(
    starter_headers: Optional[Dict] = None, **kwargs: Any
) -> Dict[str, Any]:
    """setup_loaded_batch plus START_WASH. starter_headers pins wash_started_by."""
    ctx = setup_loaded_batch(**kwargs)
    ctx["batch"] = start_wash(ctx["batch"]["id"], starter_headers or OPERATOR)
    return ctx


def setup_batch_validating(
    *,
    starter_headers: Optional[Dict] = None,
    validator_headers: Optional[Dict] = None,
    peak_temp_celsius: int = 71,
    dwell_seconds: int = 180,
    chlorine_ppm: int = 100,
    **kwargs: Any,
) -> Dict[str, Any]:
    """setup_batch_in_washing plus one RECORD_SANITIZATION reading."""
    ctx = setup_batch_in_washing(starter_headers, **kwargs)
    ctx["batch"] = record_sanitization(
        ctx["batch"]["id"],
        peak_temp_celsius,
        dwell_seconds,
        chlorine_ppm,
        validator_headers or OPERATOR_2,
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — pauses, swaps, cases, invoices
# ---------------------------------------------------------------------------


def create_pause(
    subscription_id: str,
    start_date: str,
    end_date: str,
    expected_subscription_version: int,
    headers: Dict,
) -> Dict[str, Any]:
    payload = create_pause_payload(
        subscription_id, start_date, end_date, expected_subscription_version
    )
    return get_success_data(api_client.create_pause(payload, headers))


def create_swap(subscription_id: str, to_size_code: str, headers: Dict) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_swap(create_swap_payload(subscription_id, to_size_code), headers)
    )


def swap_event(swap_id: str, event_type: str, headers: Optional[Dict] = None, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(fields)
    return get_success_data(api_client.swap_event(swap_id, payload, headers or OPERATOR))


def create_case(
    subscription_id: str,
    pool_id: str,
    case_type: str = "LOST",
    item_count: int = 1,
    first_issued_date: str = "2026-06-01",
    assessed_fee_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload = create_case_payload(
        subscription_id, pool_id, case_type, item_count, first_issued_date, assessed_fee_cents
    )
    return get_success_data(api_client.create_case(payload, BILLING))


def case_event(case_id: str, event_type: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.case_event(case_id, {"event_type": event_type}, headers or BILLING)
    )


def generate_invoice(
    subscription_id: str,
    period_start: str = "2026-08-03",
    period_end: str = "2026-08-10",
) -> Dict[str, Any]:
    payload = generate_invoice_payload(subscription_id, period_start, period_end)
    return get_success_data(api_client.generate_invoice(payload, BILLING))


def invoice_event(invoice_id: str, event_type: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.invoice_event(invoice_id, {"event_type": event_type}, headers or BILLING)
    )


def settle_kit(kit_id: str, items_returned_count: int) -> Dict[str, Any]:
    """Kit RETURN (full or partial count) followed by SETTLE."""
    kit_event(kit_id, "RETURN", items_returned_count=items_returned_count)
    return kit_event(kit_id, "SETTLE")
