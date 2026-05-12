"""Composite setup helpers for the Restaurant Supply Chain test suite.

The PRD's lifecycle has many interlocking phases — Store, Recipe,
Ingredient (with BOM), StoreOrder (DRAFT → SUBMITTED → CONSOLIDATED →
DELIVERED), ProductionBatch (PLANNED → SCHEDULED → IN_PRODUCTION →
COMPLETED), DeliveryRoute (PLANNED → DISPATCHED → IN_TRANSIT →
COMPLETED), InventoryBatch (ON_HAND → ...), LossRecord, ReplenishmentRule
— and most interesting tests need the system in a non-initial state.
This module captures the common multi-call setup sequences once.

Identity threading (PRD §2.1): StoreManager is the only entity-backed
role (X-User-ID == Store.id). Whenever a fixture creates a Store and
the downstream call is store-scoped (POST /store-orders, lines, submit,
adjust inventory, transfer, dispose, replenishment-rules, loss-records),
the helper must thread the actual Store.id through
make_storemanager_headers; never fall back to the shared
TEST_USERS["store_manager_headers"] for ownership-gated flows.

For Driver: identity is opaque but compared to DeliveryRoute.driver_user_id
on depart/complete/raise-exception. Pass the same opaque id used at
plan time through make_driver_headers().

Setup calls use get_success_data (lenient validator) so that broken
preconditions surface as obvious "Setup failed" mismatches rather than
confusing assertion errors.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjust_inventory_payload,
    append_order_line_payload,
    attach_recipe_ingredient_payload,
    consolidate_payload,
    create_ingredient_payload,
    create_loss_record_payload,
    create_recipe_payload,
    create_replenishment_rule_payload,
    create_route_payload,
    create_store_order_payload,
    create_store_payload,
    create_vehicle_payload,
    planned_stop,
    raise_exception_payload,
    reroute_payload,
    run_cost_allocation_payload,
    schedule_batch_payload,
    transfer_inventory_payload,
    unique_user_id,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_planner_headers,
    make_platform_admin_headers,
    make_finance_headers,
    make_storemanager_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 — ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: float) -> str:
    """Add n hours to ISO timestamp s."""
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


def date_str(s: str) -> str:
    """Return YYYY-MM-DD portion of an ISO timestamp (UTC)."""
    return parse_iso(s).date().isoformat()


# Default base instant used unless a test pins something else.
DEFAULT_NOW_ISO = "2026-05-11T00:00:00.000Z"


# ===========================================================================
# Test-driving wrappers (PRD §2.11)
# ===========================================================================
# Module-level mirror of the most-recent clock_advance target so that
# helpers can pick safely-forward target dates without an endpoint to
# query the clock.
_last_known_clock_iso: Optional[str] = None


def advance_clock(to_iso: str) -> Dict[str, Any]:
    """POST /supply-chain/_clock/advance with PlatformAdmin headers.
    PRD §2.11: 'A clock-advance capability moves the simulated clock
    forward to a supplied to_iso8601 instant.' This is forward-only;
    if the requested time is earlier than the last known clock, the
    helper silently NO-OPS (the simulated clock is shared across all
    tests in a session, so we can't go backward).
    """
    global _last_known_clock_iso
    if (_last_known_clock_iso is not None
            and parse_iso(to_iso) <= parse_iso(_last_known_clock_iso)):
        # Clock already at or past requested time; nothing to do.
        return {}
    res = api_client.advance_clock(
        to_iso, TEST_USERS["platform_admin_headers"]
    )
    data = get_success_data(res)
    _last_known_clock_iso = to_iso
    return data


# Alias retained for callers that want to be explicit.
advance_clock_safe = advance_clock


def current_clock_iso() -> str:
    """Return the most recent clock instant we've advanced to (or a sane
    floor if nothing has been advanced yet). The simulated clock is
    shared across tests, so this mirror is the best we have without an
    endpoint to query it (PRD §2.11 only specifies advance/sweep/event)."""
    return _last_known_clock_iso or "2026-01-01T00:00:00.000Z"


def advance_clock_relative(*, minutes: int = 0, hours: int = 0,
                           days: int = 0) -> str:
    """Advance the simulated clock to (last_known + delta). Returns the
    new clock instant. Always moves forward — useful for tests that
    need to reach a specific clock instant without colliding with
    prior tests' clock state."""
    cur = parse_iso(current_clock_iso())
    new_iso = iso_z(cur + timedelta(minutes=minutes, hours=hours, days=days))
    advance_clock(new_iso)
    return new_iso


def current_clock_minute_of_day() -> int:
    """Return the current clock as minute-of-day (0..1439, UTC)."""
    cur = parse_iso(current_clock_iso())
    return cur.hour * 60 + cur.minute


def run_expiry_sweep() -> Dict[str, Any]:
    """POST /supply-chain/_sweep/expiry-alerts with PlatformAdmin headers."""
    return get_success_data(
        api_client.run_expiry_sweep(TEST_USERS["platform_admin_headers"])
    )


def run_replenish_sweep() -> Dict[str, Any]:
    """POST /supply-chain/_sweep/replenish with PlatformAdmin headers."""
    return get_success_data(
        api_client.run_replenish_sweep(TEST_USERS["platform_admin_headers"])
    )


def emit_event(system: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /supply-chain/_events/emit (PlatformAdmin)."""
    return get_success_data(
        api_client.emit_event(
            system, payload, TEST_USERS["platform_admin_headers"]
        )
    )


# ===========================================================================
# Tier 1 — single-entity creation
# ===========================================================================
def create_store(
    *,
    store_code: Optional[str] = None,
    name: Optional[str] = None,
    temperature_zone: str = "MIXED",
    catalog_permission: Optional[List[str]] = None,
    order_window_open_minute: int = 0,
    order_window_close_minute: int = 1439,
    cutoff_minutes_before_close: Optional[int] = None,
    low_amount_bypass_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a Store (PlatformAdmin per PRD §4)."""
    payload = create_store_payload(
        store_code=store_code,
        name=name,
        temperature_zone=temperature_zone,
        catalog_permission=catalog_permission,
        order_window_open_minute=order_window_open_minute,
        order_window_close_minute=order_window_close_minute,
        cutoff_minutes_before_close=cutoff_minutes_before_close,
        low_amount_bypass_cents=low_amount_bypass_cents,
    )
    res = api_client.create_store(
        payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def get_store(store_id: str) -> Dict[str, Any]:
    res = api_client.get_store(
        store_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def patch_store_admin(
    store_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """PATCH /stores/{id} as PlatformAdmin (PRD §4)."""
    res = api_client.patch_store(
        store_id, payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def create_recipe(
    *,
    recipe_code: Optional[str] = None,
    name: Optional[str] = None,
    temperature_zone: str = "AMBIENT",
    shelf_life_hours: int = 72,
    production_minutes_per_unit: float = 1.0,
    equipment_class: str = "OVEN",
    unit_price_cents: int = 500,
) -> Dict[str, Any]:
    """Create a Recipe (CentralKitchenPlanner per PRD §4)."""
    payload = create_recipe_payload(
        recipe_code=recipe_code,
        name=name,
        temperature_zone=temperature_zone,
        shelf_life_hours=shelf_life_hours,
        production_minutes_per_unit=production_minutes_per_unit,
        equipment_class=equipment_class,
        unit_price_cents=unit_price_cents,
    )
    res = api_client.create_recipe(payload, TEST_USERS["planner_headers"])
    return get_success_data(res)


def create_ingredient(
    *,
    sku: Optional[str] = None,
    name: Optional[str] = None,
    unit: str = "kg",
    shelf_life_hours: int = 240,
    unit_cost_cents: int = 10,
) -> Dict[str, Any]:
    """Create an Ingredient (CentralKitchenPlanner per PRD §4)."""
    payload = create_ingredient_payload(
        sku=sku, name=name, unit=unit,
        shelf_life_hours=shelf_life_hours,
        unit_cost_cents=unit_cost_cents,
    )
    res = api_client.create_ingredient(
        payload, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def attach_recipe_ingredient(
    *,
    recipe_id: str,
    ingredient_id: str,
    quantity_per_unit: float,
) -> Dict[str, Any]:
    """Attach a RecipeIngredient junction row (CentralKitchenPlanner)."""
    payload = attach_recipe_ingredient_payload(
        ingredient_id=ingredient_id,
        quantity_per_unit=quantity_per_unit,
    )
    res = api_client.attach_recipe_ingredient(
        recipe_id, payload, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def create_vehicle(
    *,
    vehicle_code: Optional[str] = None,
    capacity_units: int = 100,
    temperature_zones: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a Vehicle (PlatformAdmin per PRD §4)."""
    payload = create_vehicle_payload(
        vehicle_code=vehicle_code,
        capacity_units=capacity_units,
        temperature_zones=temperature_zones,
    )
    res = api_client.create_vehicle(
        payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2 — Recipe + ingredient bundle, Store with catalog
# ===========================================================================
def setup_recipe_with_one_ingredient(
    *,
    recipe_overrides: Optional[Dict[str, Any]] = None,
    ingredient_overrides: Optional[Dict[str, Any]] = None,
    quantity_per_unit: float = 1.0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create Recipe + Ingredient + RecipeIngredient. Returns
    (recipe, ingredient, recipe_ingredient)."""
    recipe = create_recipe(**(recipe_overrides or {}))
    ingredient = create_ingredient(**(ingredient_overrides or {}))
    ri = attach_recipe_ingredient(
        recipe_id=recipe["id"],
        ingredient_id=ingredient["id"],
        quantity_per_unit=quantity_per_unit,
    )
    return recipe, ingredient, ri


def setup_store_with_recipe(
    *,
    recipe_overrides: Optional[Dict[str, Any]] = None,
    store_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Recipe and a Store whose catalog_permission contains it.
    Returns (store, recipe)."""
    recipe = create_recipe(**(recipe_overrides or {}))
    store_kwargs: Dict[str, Any] = {
        "catalog_permission": [recipe["id"]],
    }
    store_kwargs.update(store_overrides or {})
    store = create_store(**store_kwargs)
    return store, recipe


def setup_store_recipe_ingredient(
    *,
    recipe_overrides: Optional[Dict[str, Any]] = None,
    ingredient_overrides: Optional[Dict[str, Any]] = None,
    quantity_per_unit: float = 1.0,
    store_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create Recipe + Ingredient + RecipeIngredient + Store with the recipe
    in its catalog_permission. Returns (store, recipe, ingredient)."""
    recipe, ingredient, _ = setup_recipe_with_one_ingredient(
        recipe_overrides=recipe_overrides,
        ingredient_overrides=ingredient_overrides,
        quantity_per_unit=quantity_per_unit,
    )
    store_kwargs: Dict[str, Any] = {"catalog_permission": [recipe["id"]]}
    store_kwargs.update(store_overrides or {})
    store = create_store(**store_kwargs)
    return store, recipe, ingredient


# ===========================================================================
# Tier 3 — StoreOrder lifecycle (DRAFT → SUBMITTED → CONSOLIDATED → DELIVERED)
# ===========================================================================
def create_draft_order(
    *,
    store_id: str,
    target_delivery_date: str,
) -> Dict[str, Any]:
    """POST /store-orders as the StoreManager owning the store."""
    payload = create_store_order_payload(
        target_delivery_date=target_delivery_date
    )
    headers = make_storemanager_headers(store_id)
    res = api_client.create_store_order(payload, headers)
    return get_success_data(res)


def append_line(
    *,
    order_id: str,
    store_id: str,
    recipe_id: str,
    quantity: int,
) -> Dict[str, Any]:
    """POST /store-orders/{id}/lines as the owning StoreManager."""
    payload = append_order_line_payload(
        recipe_id=recipe_id, quantity=quantity
    )
    headers = make_storemanager_headers(store_id)
    res = api_client.append_order_line(order_id, payload, headers)
    return get_success_data(res)


def submit_order(*, order_id: str, store_id: str) -> Dict[str, Any]:
    headers = make_storemanager_headers(store_id)
    res = api_client.submit_store_order(order_id, headers)
    return get_success_data(res)


def cancel_order(*, order_id: str, store_id: str) -> Dict[str, Any]:
    headers = make_storemanager_headers(store_id)
    res = api_client.cancel_store_order(order_id, headers)
    return get_success_data(res)


def get_order(order_id: str) -> Dict[str, Any]:
    res = api_client.get_store_order(
        order_id, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def setup_submitted_order(
    *,
    store_id: str,
    recipe_id: str,
    target_delivery_date: str,
    quantity: int = 1,
) -> Dict[str, Any]:
    """Create DRAFT order → append one line → submit. Returns the
    submitted StoreOrder."""
    order = create_draft_order(
        store_id=store_id, target_delivery_date=target_delivery_date
    )
    append_line(
        order_id=order["id"],
        store_id=store_id,
        recipe_id=recipe_id,
        quantity=quantity,
    )
    return submit_order(order_id=order["id"], store_id=store_id)


def setup_submitted_order_multiple_lines(
    *,
    store_id: str,
    target_delivery_date: str,
    lines: List[Tuple[str, int]],
) -> Dict[str, Any]:
    """Create DRAFT, append (recipe_id, quantity) lines, submit. Returns order."""
    order = create_draft_order(
        store_id=store_id, target_delivery_date=target_delivery_date
    )
    for recipe_id, qty in lines:
        append_line(
            order_id=order["id"],
            store_id=store_id,
            recipe_id=recipe_id,
            quantity=qty,
        )
    return submit_order(order_id=order["id"], store_id=store_id)


# ===========================================================================
# Tier 3b — ProductionBatch lifecycle
# ===========================================================================
def consolidate_batches(
    *, target_delivery_date: str
) -> List[Dict[str, Any]]:
    """POST /production-batches/consolidate as CentralKitchenPlanner.
    Returns the list of created/updated ProductionBatch rows."""
    payload = consolidate_payload(target_delivery_date=target_delivery_date)
    res = api_client.consolidate_production_batches(
        payload, TEST_USERS["planner_headers"]
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return [data] if data else []


def get_batch(batch_id: str) -> Dict[str, Any]:
    res = api_client.get_production_batch(
        batch_id, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def get_batch_forecast(batch_id: str) -> Dict[str, Any]:
    res = api_client.get_production_batch_forecast(
        batch_id, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def schedule_batch(
    *,
    batch_id: str,
    preferred_start_at: Optional[str] = None,
) -> Dict[str, Any]:
    payload = schedule_batch_payload(preferred_start_at=preferred_start_at)
    res = api_client.schedule_production_batch(
        batch_id, TEST_USERS["planner_headers"], payload
    )
    return get_success_data(res)


def start_batch(batch_id: str) -> Dict[str, Any]:
    res = api_client.start_production_batch(
        batch_id, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def complete_batch(batch_id: str) -> Dict[str, Any]:
    res = api_client.complete_production_batch(
        batch_id, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def fail_batch(batch_id: str) -> Dict[str, Any]:
    res = api_client.fail_production_batch(
        batch_id, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def setup_consolidated_batch(
    *,
    store_id: str,
    recipe_id: str,
    target_delivery_date: str,
    quantity: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Submit one order → consolidate. Returns (order, batch_for_that_recipe)."""
    order = setup_submitted_order(
        store_id=store_id,
        recipe_id=recipe_id,
        target_delivery_date=target_delivery_date,
        quantity=quantity,
    )
    batches = consolidate_batches(
        target_delivery_date=target_delivery_date
    )
    target_batch: Optional[Dict[str, Any]] = None
    for b in batches:
        if b.get("recipe_id") == recipe_id:
            target_batch = b
            break
    assert target_batch is not None, (
        f"Setup failed: no ProductionBatch returned for recipe {recipe_id}"
    )
    return order, target_batch


def setup_completed_batch(
    *,
    store_id: str,
    recipe_id: str,
    target_delivery_date: str,
    quantity: int = 1,
    schedule_start_at: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full pipeline: submitted order → consolidate → schedule → start →
    complete. Advances the simulated clock to schedule_start_at (or to
    a server-assigned scheduled_start_at) before start. Returns
    (order, completed_batch)."""
    order, batch = setup_consolidated_batch(
        store_id=store_id,
        recipe_id=recipe_id,
        target_delivery_date=target_delivery_date,
        quantity=quantity,
    )
    scheduled = schedule_batch(
        batch_id=batch["id"],
        preferred_start_at=schedule_start_at,
    )
    # Advance the simulated clock to the scheduled_start_at so that
    # /start passes the now() >= scheduled_start_at precondition.
    sched_start = scheduled.get("scheduled_start_at")
    if sched_start:
        advance_clock(sched_start)
    started = start_batch(batch["id"])
    completed = complete_batch(started["id"])
    return order, completed


# ===========================================================================
# Tier 4 — Vehicle / DeliveryRoute helpers
# ===========================================================================
def plan_route(
    *,
    vehicle_id: str,
    driver_user_id: str,
    target_delivery_date: str,
    planned_stops: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """POST /delivery-routes as CentralKitchenPlanner."""
    payload = create_route_payload(
        vehicle_id=vehicle_id,
        driver_user_id=driver_user_id,
        target_delivery_date=target_delivery_date,
        planned_stops=planned_stops,
    )
    res = api_client.create_delivery_route(
        payload, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def dispatch_route(route_id: str) -> Dict[str, Any]:
    res = api_client.dispatch_route(
        route_id, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def depart_route(*, route_id: str, driver_user_id: str) -> Dict[str, Any]:
    """Driver departs. driver_user_id MUST match
    DeliveryRoute.driver_user_id (PRD §2.1)."""
    headers = make_driver_headers(driver_user_id)
    res = api_client.depart_route(route_id, headers)
    return get_success_data(res)


def complete_route(
    *, route_id: str, driver_user_id: str
) -> Dict[str, Any]:
    headers = make_driver_headers(driver_user_id)
    res = api_client.complete_route(route_id, headers)
    return get_success_data(res)


def raise_route_exception(
    *, route_id: str, driver_user_id: str, exception_reason: str
) -> Dict[str, Any]:
    headers = make_driver_headers(driver_user_id)
    payload = raise_exception_payload(exception_reason=exception_reason)
    res = api_client.raise_exception(route_id, payload, headers)
    return get_success_data(res)


def reroute_to_replacement(
    *, route_id: str, replacement_vehicle_id: str
) -> Dict[str, Any]:
    payload = reroute_payload(replacement_vehicle_id=replacement_vehicle_id)
    res = api_client.reroute_route(
        route_id, payload, TEST_USERS["planner_headers"]
    )
    return get_success_data(res)


def setup_delivered_inventory(
    *,
    store_id: str,
    recipe_id: str,
    target_delivery_date: str,
    quantity: int,
    vehicle_temp_zones: Optional[List[str]] = None,
    schedule_start_at: Optional[str] = None,
    stop_window_start: Optional[str] = None,
    stop_window_end: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Full pipeline: submitted order → consolidate → schedule → start →
    complete batch → plan route loading the batch → dispatch → depart
    → complete (creates InventoryBatch at store, transitions order
    CONSOLIDATED→DELIVERED). Returns (order, batch, route, inventory_batch)."""
    order, batch = setup_completed_batch(
        store_id=store_id,
        recipe_id=recipe_id,
        target_delivery_date=target_delivery_date,
        quantity=quantity,
        schedule_start_at=schedule_start_at,
    )
    if vehicle_temp_zones is None:
        # PRD §2.10: must be subset of {AMBIENT, CHILLED, FROZEN}
        vehicle_temp_zones = ["AMBIENT", "CHILLED", "FROZEN"]
    vehicle = create_vehicle(
        capacity_units=max(quantity, 1),
        temperature_zones=vehicle_temp_zones,
    )
    driver_id = unique_user_id("driver")
    # Anchor stop window relative to current simulated clock so it is
    # in the future and well-formed (start < end).
    if stop_window_start is None:
        # Use the batch's expires_at - 1h as a comfortable mid-window
        produced_at = batch.get("produced_at")
        anchor = produced_at or DEFAULT_NOW_ISO
        stop_window_start = add_hours(anchor, 0)
    if stop_window_end is None:
        stop_window_end = add_hours(stop_window_start, 1)
    stops = [planned_stop(
        store_id=store_id,
        time_window_start=stop_window_start,
        time_window_end=stop_window_end,
        batch_ids=[batch["id"]],
    )]
    route = plan_route(
        vehicle_id=vehicle["id"],
        driver_user_id=driver_id,
        target_delivery_date=target_delivery_date,
        planned_stops=stops,
    )
    dispatched = dispatch_route(route["id"])
    departed = depart_route(
        route_id=dispatched["id"], driver_user_id=driver_id
    )
    completed_route = complete_route(
        route_id=departed["id"], driver_user_id=driver_id
    )
    # Find the resulting InventoryBatch for this store + recipe.
    inv = list_inventory_batches(store_id=store_id)
    inventory_batch: Optional[Dict[str, Any]] = None
    for ib in inv:
        if (ib.get("store_id") == store_id
                and ib.get("recipe_id") == recipe_id
                and ib.get("status") == "ON_HAND"):
            inventory_batch = ib
            break
    assert inventory_batch is not None, (
        "Setup failed: route completion did not create an "
        "ON_HAND InventoryBatch for the target store."
    )
    return order, batch, completed_route, inventory_batch


# ===========================================================================
# Tier 4b — Inventory & loss helpers
# ===========================================================================
def list_inventory_batches(
    *,
    store_id: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """List inventory batches optionally filtered by store_id.
    PRD §4: GET /inventory-batches is authorized for StoreManager,
    CentralKitchenPlanner, FinanceController. We default to a
    CentralKitchenPlanner for cross-store visibility unless a specific
    actor is supplied (StoreManager would be filtered to own store
    server-side)."""
    headers = actor_headers or TEST_USERS["planner_headers"]
    params = {"store_id": store_id} if store_id is not None else None
    res = api_client.list_inventory_batches(headers, params=params)
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def adjust_inventory(
    *,
    inventory_batch_id: str,
    store_id: str,
    delta: int,
    reason: str = "test adjust",
) -> Dict[str, Any]:
    payload = adjust_inventory_payload(delta=delta, reason=reason)
    headers = make_storemanager_headers(store_id)
    res = api_client.adjust_inventory_batch(
        inventory_batch_id, payload, headers
    )
    return get_success_data(res)


def transfer_inventory(
    *,
    inventory_batch_id: str,
    source_store_id: str,
    destination_store_id: str,
) -> Dict[str, Any]:
    payload = transfer_inventory_payload(
        destination_store_id=destination_store_id
    )
    headers = make_storemanager_headers(source_store_id)
    res = api_client.transfer_inventory_batch(
        inventory_batch_id, payload, headers
    )
    return get_success_data(res)


def dispose_inventory(
    *, inventory_batch_id: str, store_id: str
) -> Dict[str, Any]:
    headers = make_storemanager_headers(store_id)
    res = api_client.dispose_inventory_batch(inventory_batch_id, headers)
    return get_success_data(res)


def record_loss(
    *,
    store_id: str,
    inventory_batch_id: str,
    quantity_lost: int,
    cause: str,
    responsibility_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /loss-records as the owning StoreManager."""
    payload = create_loss_record_payload(
        inventory_batch_id=inventory_batch_id,
        quantity_lost=quantity_lost,
        cause=cause,
        responsibility_user_id=responsibility_user_id,
    )
    headers = make_storemanager_headers(store_id)
    res = api_client.create_loss_record(payload, headers)
    return get_success_data(res)


def reverse_loss(loss_id: str) -> Dict[str, Any]:
    res = api_client.reverse_loss_record(
        loss_id, TEST_USERS["finance_headers"]
    )
    return get_success_data(res)


def approve_loss(loss_id: str) -> Dict[str, Any]:
    res = api_client.approve_loss_record(
        loss_id, TEST_USERS["finance_headers"]
    )
    return get_success_data(res)


def resolve_investigation(loss_id: str) -> Dict[str, Any]:
    res = api_client.resolve_investigation(
        loss_id, TEST_USERS["finance_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4c — Replenishment helpers
# ===========================================================================
def create_replenishment_rule(
    *,
    store_id: str,
    recipe_id: str,
    safety_stock_units: int,
    replenish_to_units: int,
    cycle_hours: int,
) -> Dict[str, Any]:
    payload = create_replenishment_rule_payload(
        recipe_id=recipe_id,
        safety_stock_units=safety_stock_units,
        replenish_to_units=replenish_to_units,
        cycle_hours=cycle_hours,
    )
    headers = make_storemanager_headers(store_id)
    res = api_client.create_replenishment_rule(payload, headers)
    return get_success_data(res)


def suspend_replenishment_rule(
    *, rule_id: str, store_id: str
) -> Dict[str, Any]:
    headers = make_storemanager_headers(store_id)
    res = api_client.suspend_replenishment_rule(rule_id, headers)
    return get_success_data(res)


def activate_replenishment_rule(
    *, rule_id: str, store_id: str
) -> Dict[str, Any]:
    headers = make_storemanager_headers(store_id)
    res = api_client.activate_replenishment_rule(rule_id, headers)
    return get_success_data(res)


def manual_replenish(*, rule_id: str, store_id: str) -> Dict[str, Any]:
    headers = make_storemanager_headers(store_id)
    res = api_client.manual_replenish(rule_id, headers)
    return get_success_data(res)


def list_audit_log_entries(
    *,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if target_type is not None:
        params["target_type"] = target_type
    if target_id is not None:
        params["target_id"] = target_id
    if action is not None:
        params["action"] = action
    res = api_client.list_audit_log(
        TEST_USERS["platform_admin_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def list_loss_records(
    *,
    store_id: Optional[str] = None,
    inventory_batch_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if store_id is not None:
        params["store_id"] = store_id
    if inventory_batch_id is not None:
        params["inventory_batch_id"] = inventory_batch_id
    res = api_client.list_loss_records(
        TEST_USERS["finance_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def list_store_orders(
    *,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    target_delivery_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if store_id is not None:
        params["store_id"] = store_id
    if status is not None:
        params["status"] = status
    if target_delivery_date is not None:
        params["target_delivery_date"] = target_delivery_date
    res = api_client.list_store_orders(
        TEST_USERS["planner_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


# ===========================================================================
# Tier 5 — Difficulty-design specific composites
# ===========================================================================
def setup_dual_variant_planned_vs_forecast(
    *,
    target_delivery_date: str,
    avg_daily_sales_cents: int = 10000,
    unit_price_cents: int = 500,
    order_quantity: int = 15,
    quantity_per_unit: float = 2.0,
    velocity_multiplier_hint: float = 1.0,  # informational; server-computed
) -> Dict[str, Any]:
    """Build the scaffold-difficulty 'ingredient_demand_planned_vs_forecast'
    fixture: one Recipe (unit_price_cents=500), one Ingredient,
    RecipeIngredient(qpu=2), one Store with avg_daily_sales_cents=10000
    and an ACTIVE ReplenishmentRule for the recipe, then a SUBMITTED
    StoreOrder with one OrderLine (quantity=order_quantity).

    The store's avg_daily_sales_cents is read-only / computed per PRD,
    so the rate at which the implementation populates it is implementation
    defined; tests asserting the forecast number additionally use
    /_events/emit (POS sale) where required.

    Returns dict with keys: store, recipe, ingredient, recipe_ingredient,
    submitted_order.
    """
    recipe = create_recipe(
        unit_price_cents=unit_price_cents,
        shelf_life_hours=72,
        production_minutes_per_unit=1.0,
        equipment_class="OVEN",
    )
    ingredient = create_ingredient(unit_cost_cents=10)
    ri = attach_recipe_ingredient(
        recipe_id=recipe["id"],
        ingredient_id=ingredient["id"],
        quantity_per_unit=quantity_per_unit,
    )
    store = create_store(
        catalog_permission=[recipe["id"]],
        order_window_open_minute=0,
        order_window_close_minute=1439,
    )
    rule = create_replenishment_rule(
        store_id=store["id"],
        recipe_id=recipe["id"],
        safety_stock_units=1,
        replenish_to_units=2,
        cycle_hours=1,
    )
    order = setup_submitted_order(
        store_id=store["id"],
        recipe_id=recipe["id"],
        target_delivery_date=target_delivery_date,
        quantity=order_quantity,
    )
    return {
        "store": store,
        "recipe": recipe,
        "ingredient": ingredient,
        "recipe_ingredient": ri,
        "replenishment_rule": rule,
        "submitted_order": order,
    }


def setup_three_stores_for_provisional_alloc(
    *,
    target_delivery_date: str,
) -> Dict[str, Any]:
    """Three stores with codes S-001/S-002/S-003 (so lowest-store_code
    tie-break is deterministic), each contributing one OrderLine
    (quantity=1) of a single Recipe (unit_price=200, ingredient cost
    structure ingredient_cost = 1 × 10 × 3 = 30), used by the
    provisional_cost_allocation_pinned_rounding_order difficulty test.

    Returns dict: stores (list ordered S-001, S-002, S-003), recipe,
    orders (parallel list), batch (after consolidate)."""
    recipe = create_recipe(
        unit_price_cents=200,
        shelf_life_hours=72,
        production_minutes_per_unit=1.0,
        equipment_class="OVEN",
    )
    ingredient = create_ingredient(unit_cost_cents=10)
    attach_recipe_ingredient(
        recipe_id=recipe["id"],
        ingredient_id=ingredient["id"],
        quantity_per_unit=1.0,
    )
    stores: List[Dict[str, Any]] = []
    for code_suffix in ("001", "002", "003"):
        store = create_store(
            store_code=f"S-{code_suffix}-{__import__('uuid').uuid4().hex[:4]}",
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        stores.append(store)
    orders: List[Dict[str, Any]] = []
    for store in stores:
        order = setup_submitted_order(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date=target_delivery_date,
            quantity=1,
        )
        orders.append(order)
    batches = consolidate_batches(target_delivery_date=target_delivery_date)
    target_batch: Optional[Dict[str, Any]] = None
    for b in batches:
        if b.get("recipe_id") == recipe["id"]:
            target_batch = b
            break
    assert target_batch is not None, (
        "Setup failed: consolidation produced no batch for the target recipe."
    )
    return {
        "stores": stores,
        "recipe": recipe,
        "ingredient": ingredient,
        "orders": orders,
        "batch": target_batch,
    }


def setup_two_recipes_same_target_date_oven(
    *,
    target_delivery_date: str,
    short_shelf_life_hours: int = 12,
    long_shelf_life_hours: int = 48,
    short_recipe_code: Optional[str] = None,
    long_recipe_code: Optional[str] = None,
    production_minutes_per_unit: float = 60.0,
    units_each: int = 1,
) -> Dict[str, Any]:
    """Two OVEN recipes (one short shelf life, one long), both ordered by
    a single Store with one quantity=1 OrderLine each, then consolidated.
    Underpins the shelf_life_sequencing topological difficulty test.

    Returns dict: store, r_short, r_long, batch_short, batch_long, orders.
    """
    r_short = create_recipe(
        recipe_code=short_recipe_code,
        shelf_life_hours=short_shelf_life_hours,
        production_minutes_per_unit=production_minutes_per_unit,
        equipment_class="OVEN",
        unit_price_cents=500,
    )
    r_long = create_recipe(
        recipe_code=long_recipe_code,
        shelf_life_hours=long_shelf_life_hours,
        production_minutes_per_unit=production_minutes_per_unit,
        equipment_class="OVEN",
        unit_price_cents=500,
    )
    ingredient = create_ingredient(unit_cost_cents=10)
    attach_recipe_ingredient(
        recipe_id=r_short["id"],
        ingredient_id=ingredient["id"],
        quantity_per_unit=1.0,
    )
    attach_recipe_ingredient(
        recipe_id=r_long["id"],
        ingredient_id=ingredient["id"],
        quantity_per_unit=1.0,
    )
    store = create_store(
        catalog_permission=[r_short["id"], r_long["id"]],
        order_window_open_minute=0,
        order_window_close_minute=1439,
    )
    o_short = setup_submitted_order(
        store_id=store["id"],
        recipe_id=r_short["id"],
        target_delivery_date=target_delivery_date,
        quantity=units_each,
    )
    o_long = setup_submitted_order(
        store_id=store["id"],
        recipe_id=r_long["id"],
        target_delivery_date=target_delivery_date,
        quantity=units_each,
    )
    batches = consolidate_batches(target_delivery_date=target_delivery_date)
    batch_by_recipe: Dict[str, Dict[str, Any]] = {}
    for b in batches:
        batch_by_recipe[b.get("recipe_id")] = b
    return {
        "store": store,
        "r_short": r_short,
        "r_long": r_long,
        "batch_short": batch_by_recipe.get(r_short["id"]),
        "batch_long": batch_by_recipe.get(r_long["id"]),
        "orders": [o_short, o_long],
    }


def setup_two_oven_batches_capacity(
    *,
    target_delivery_date: str,
    units_each: int = 30,
    production_minutes_per_unit: float = 10.0,
) -> Dict[str, Any]:
    """Two OVEN recipes, each in its own ProductionBatch (planned_units
    = units_each), so that two batches each consume
    units_each * production_minutes_per_unit equipment_minutes. With
    units=30 and pmu=10, each batch is 300 OVEN minutes; two batches sum
    to 600 > 480 (the per-day OVEN cap). Used for capacity-exceed tests.

    Returns dict: store, r_a, r_b, batch_a, batch_b.
    """
    return setup_two_recipes_same_target_date_oven(
        target_delivery_date=target_delivery_date,
        short_shelf_life_hours=72,
        long_shelf_life_hours=72,
        production_minutes_per_unit=production_minutes_per_unit,
        units_each=units_each,
    )


def setup_inventory_with_target_expiry(
    *,
    expires_at_iso: str,
    quantity_on_hand: int = 10,
    recipe_temperature_zone: str = "AMBIENT",
    store_temperature_zone: str = "MIXED",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an InventoryBatch and pin the simulated clock so that the
    distance-to-expiry equals (expires_at_iso - 2026-05-11T00:00:00Z).

    Implementation detail: the production pipeline determines the actual
    InventoryBatch.expires_at (= produced_at + Recipe.shelf_life_hours).
    To get a deterministic distance-to-expiry without controlling the
    implementation's chosen scheduled_start_at, we drive the pipeline
    to create a real ON_HAND batch, then advance the clock to
    (actual_expires_at - desired_distance) where desired_distance is
    (expires_at_iso - 2026-05-11T00:00:00Z).

    The 2026-05-11T00:00:00Z anchor is just a convention — tests pin
    clock to that anchor before computing thresholds.

    Returns (store, inventory_batch).
    """
    # advance_clock is forward-only. Pick a target_delivery_date that is
    # safely AFTER the current clock so the production pipeline is
    # feasible. We use a clock-relative anchor: 1 day after the latest
    # known clock instant (or 2026-01-02 as the floor for the very first
    # call in a session).
    if _last_known_clock_iso is None:
        anchor = "2026-01-01T00:00:00.000Z"
        advance_clock(anchor)
    base_clock = parse_iso(_last_known_clock_iso or "2026-01-01T00:00:00.000Z")
    # target date = base_clock + 1 day, formatted YYYY-MM-DD.
    target_dt = base_clock + timedelta(days=1)
    target_date = target_dt.date().isoformat()
    shelf_life_hours = 24 * 365  # 1 year of headroom — recipe shelf life
    store, recipe, _ = setup_store_recipe_ingredient(
        recipe_overrides={
            "temperature_zone": recipe_temperature_zone,
            "shelf_life_hours": shelf_life_hours,
            "production_minutes_per_unit": 1.0,
            "equipment_class": "OVEN",
        },
        store_overrides={
            "temperature_zone": store_temperature_zone,
        },
    )
    veh_zones = (
        [recipe_temperature_zone]
        if recipe_temperature_zone in {"AMBIENT", "CHILLED", "FROZEN"}
        else ["AMBIENT"]
    )
    _order, _batch, _route, inv = setup_delivered_inventory(
        store_id=store["id"],
        recipe_id=recipe["id"],
        target_delivery_date=target_date,
        quantity=quantity_on_hand,
        vehicle_temp_zones=veh_zones,
    )
    # Compute the clock placement needed to make
    # (actual_expires_at - now()) == (expires_at_iso - anchor_now).
    actual_expires_at = inv.get("expires_at")
    if actual_expires_at:
        anchor_now = parse_iso("2026-05-11T00:00:00.000Z")
        desired_distance = parse_iso(expires_at_iso) - anchor_now
        new_clock = parse_iso(actual_expires_at) - desired_distance
        advance_clock_safe(iso_z(new_clock))
    return store, inv


def setup_replenishment_with_on_hand(
    *,
    safety_stock_units: int,
    on_hand: int,
    replenish_to_units: int,
    cycle_hours: int = 1,
    target_delivery_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Full setup: store + recipe with delivered inventory whose
    quantity_on_hand equals `on_hand`; ACTIVE replenishment rule with
    given safety_stock_units / replenish_to_units / cycle_hours; then
    last_evaluated_at is shifted backwards (by advancing the clock far
    enough forward AFTER rule creation) so that cycle_hours has elapsed.

    Returns dict: store, recipe, inventory_batch, rule.
    """
    # target_delivery_date defaults to (current_clock + 1 day) so the
    # production pipeline schedule is feasible regardless of where prior
    # tests have moved the clock.
    if target_delivery_date is None:
        base_clock = parse_iso(current_clock_iso())
        target_delivery_date = (base_clock + timedelta(days=1)).date().isoformat()

    # Build recipe + ingredient + store.
    store, recipe, _ = setup_store_recipe_ingredient(
        recipe_overrides={
            "shelf_life_hours": 24 * 365,
            "production_minutes_per_unit": 1.0,
            "equipment_class": "OVEN",
            "unit_price_cents": 500,
        },
    )
    # Drive a delivered InventoryBatch whose quantity_on_hand == on_hand.
    _order, _batch, _route, inv = setup_delivered_inventory(
        store_id=store["id"],
        recipe_id=recipe["id"],
        target_delivery_date=target_delivery_date,
        quantity=on_hand,
        vehicle_temp_zones=["AMBIENT", "CHILLED", "FROZEN"],
    )
    # Create the rule AFTER inventory exists.
    rule = create_replenishment_rule(
        store_id=store["id"],
        recipe_id=recipe["id"],
        safety_stock_units=safety_stock_units,
        replenish_to_units=replenish_to_units,
        cycle_hours=cycle_hours,
    )
    # Advance clock past cycle_hours so that the next sweep / manual
    # trigger sees the cycle as elapsed. Clock-relative is robust to
    # whatever instant the rule was created at.
    advance_clock(add_hours(current_clock_iso(), cycle_hours + 1))
    return {
        "store": store,
        "recipe": recipe,
        "inventory_batch": inv,
        "rule": rule,
    }


def cost_allocation_run(
    *,
    period_start: str,
    period_end: str,
    indirect_basis: str,
) -> Dict[str, Any]:
    payload = run_cost_allocation_payload(
        period_start=period_start,
        period_end=period_end,
        indirect_basis=indirect_basis,
    )
    res = api_client.run_cost_allocation(
        payload, TEST_USERS["finance_headers"]
    )
    return get_success_data(res)


__all__ = [
    # time
    "iso_z", "parse_iso", "add_seconds", "add_minutes",
    "add_hours", "add_days", "date_str", "DEFAULT_NOW_ISO",
    # admin / sweeps
    "advance_clock", "run_expiry_sweep", "run_replenish_sweep", "emit_event",
    # tier 1
    "create_store", "get_store", "patch_store_admin",
    "create_recipe", "create_ingredient", "attach_recipe_ingredient",
    "create_vehicle",
    # tier 2
    "setup_recipe_with_one_ingredient",
    "setup_store_with_recipe",
    "setup_store_recipe_ingredient",
    # tier 3 - orders
    "create_draft_order", "append_line", "submit_order", "cancel_order",
    "get_order",
    "setup_submitted_order", "setup_submitted_order_multiple_lines",
    # tier 3 - production
    "consolidate_batches", "get_batch", "get_batch_forecast",
    "schedule_batch", "start_batch", "complete_batch", "fail_batch",
    "setup_consolidated_batch", "setup_completed_batch",
    # tier 4 - delivery
    "plan_route", "dispatch_route", "depart_route", "complete_route",
    "raise_route_exception", "reroute_to_replacement",
    "setup_delivered_inventory",
    # tier 4 - inventory & loss
    "list_inventory_batches", "adjust_inventory", "transfer_inventory",
    "dispose_inventory", "record_loss", "reverse_loss", "approve_loss",
    "resolve_investigation",
    # tier 4 - replenishment
    "create_replenishment_rule", "suspend_replenishment_rule",
    "activate_replenishment_rule", "manual_replenish",
    # readers
    "list_audit_log_entries", "list_loss_records", "list_store_orders",
    # tier 5 - difficulty composites
    "setup_dual_variant_planned_vs_forecast",
    "setup_three_stores_for_provisional_alloc",
    "setup_two_recipes_same_target_date_oven",
    "setup_two_oven_batches_capacity",
    "setup_inventory_with_target_expiry",
    "setup_replenishment_with_on_hand",
    "cost_allocation_run",
]
