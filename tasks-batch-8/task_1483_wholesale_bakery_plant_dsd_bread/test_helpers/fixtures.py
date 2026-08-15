"""Composite setup helpers for the bakery DSD domain.

Every test starts against an empty database (the harness restarts the server
before each test). These helpers build multi-step preconditions from scratch
using only PRD-declared endpoints. Internal setup calls go through
get_success_data() so failures surface as "Setup failed at <step>" instead of
a downstream assertion.

Identity threading: Driver and StoreReceiver are entity-backed (PRD §2.1);
every ownership- or segregation-gated call uses make_driver_headers(driver.id)
or make_store_receiver_headers(store.id). Opaque roles (LineOperator, QALead)
are threaded as distinct user_id strings wherever §2.10 segregation applies.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_batch_payload,
    create_driver_payload,
    create_ingredient_index_payload,
    create_line_payload,
    create_plant_payload,
    create_product_payload,
    create_production_plan_payload,
    create_route_payload,
    create_route_stop_payload,
    create_sanitation_cycle_payload,
    create_stale_return_payload,
    create_store_order_payload,
    create_store_payload,
    create_surcharge_schedule_payload,
    create_thrift_sale_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_operator_headers,
    make_qa_headers,
    make_store_receiver_headers,
)


def _fail(step: str, response):
    raise AssertionError(
        f"Setup failed at {step}: {response.status_code} {response.text}"
    )


def _ok(step: str, response):
    if response.status_code >= 400:
        _fail(step, response)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["admin_headers"])
    return _ok("set_clock", resp)


def create_plant(**overrides) -> dict:
    resp = api_client.create_plant(create_plant_payload(**overrides), TEST_USERS["admin_headers"])
    return _ok("create_plant", resp)


def create_product(plant_id: str, **overrides) -> dict:
    resp = api_client.create_product(
        create_product_payload(plant_id, **overrides), TEST_USERS["admin_headers"]
    )
    return _ok("create_product", resp)


def create_store(plant_id: str, **overrides) -> dict:
    resp = api_client.create_store(
        create_store_payload(plant_id, **overrides), TEST_USERS["admin_headers"]
    )
    return _ok("create_store", resp)


def create_driver(plant_id: str, **overrides) -> dict:
    resp = api_client.create_driver(
        create_driver_payload(plant_id, **overrides), TEST_USERS["admin_headers"]
    )
    return _ok("create_driver", resp)


def create_line(plant_id: str, **overrides) -> dict:
    resp = api_client.create_line(
        create_line_payload(plant_id, **overrides), TEST_USERS["admin_headers"]
    )
    return _ok("create_line", resp)


def create_order(store_id: str, product_id: str, qty: int = 100, **overrides) -> dict:
    resp = api_client.create_store_order(
        create_store_order_payload(store_id, product_id, qty=qty, **overrides),
        TEST_USERS["planner_headers"],
    )
    return _ok("create_store_order", resp)


def confirm_order(order_id: str) -> dict:
    resp = api_client.confirm_store_order(order_id, TEST_USERS["planner_headers"])
    return _ok("confirm_store_order", resp)


def lock_order(order_id: str) -> dict:
    resp = api_client.lock_store_order(order_id, TEST_USERS["planner_headers"])
    return _ok("lock_store_order", resp)


def create_plan(plant_id: str, expected_plant_version: int, **overrides) -> dict:
    resp = api_client.create_production_plan(
        create_production_plan_payload(plant_id, expected_plant_version, **overrides),
        TEST_USERS["planner_headers"],
    )
    return _ok("create_production_plan", resp)


def lock_plan(plan_id: str) -> dict:
    resp = api_client.lock_production_plan(plan_id, TEST_USERS["planner_headers"])
    return _ok("lock_production_plan", resp)


def release_plan(plan_id: str) -> dict:
    resp = api_client.release_production_plan(plan_id, TEST_USERS["planner_headers"])
    return _ok("release_production_plan", resp)


def get_plan(plan_id: str) -> dict:
    resp = api_client.get_production_plan(plan_id, TEST_USERS["planner_headers"])
    return _ok("get_production_plan", resp)


def create_batch(plan_id: str, line_id: str, product_id: str, plan_version: int, **overrides) -> dict:
    resp = api_client.create_batch(
        create_batch_payload(
            plan_id, line_id, product_id, plan_version, **overrides
        ),
        TEST_USERS["planner_headers"],
    )
    return _ok("create_batch", resp)


def create_route(plant_id: str, driver_id: str, **overrides) -> dict:
    resp = api_client.create_route(
        create_route_payload(plant_id, driver_id, **overrides),
        TEST_USERS["planner_headers"],
    )
    return _ok("create_route", resp)


def create_stop(route_id: str, order_id: str, planned_units: int, batch_ids: list) -> dict:
    resp = api_client.create_route_stop(
        create_route_stop_payload(route_id, order_id, planned_units, batch_ids),
        TEST_USERS["planner_headers"],
    )
    return _ok("create_route_stop", resp)


def create_cycle(line_id: str, to_allergen_class: str = "NONE", operator_id: str = "op-1") -> dict:
    resp = api_client.create_sanitation_cycle(
        create_sanitation_cycle_payload(line_id, to_allergen_class=to_allergen_class),
        make_operator_headers(operator_id),
    )
    return _ok("create_sanitation_cycle", resp)


def create_stale_return(store_id: str, stop_id: str, lines: list, driver_id: str) -> dict:
    resp = api_client.create_stale_return(
        create_stale_return_payload(store_id, stop_id, lines),
        make_driver_headers(driver_id),
    )
    return _ok("create_stale_return", resp)


def create_ingredient_index(plant_id: str, ingredient: str, period: str, forecast_value) -> dict:
    resp = api_client.create_ingredient_index(
        create_ingredient_index_payload(
            plant_id, ingredient=ingredient, period=period, forecast_value=forecast_value
        ),
        TEST_USERS["pricing_headers"],
    )
    return _ok("create_ingredient_index", resp)


def create_surcharge_schedule(product_id: str, period: str = "2026-08") -> dict:
    resp = api_client.create_surcharge_schedule(
        create_surcharge_schedule_payload(product_id, period=period),
        TEST_USERS["pricing_headers"],
    )
    return _ok("create_surcharge_schedule", resp)


def create_thrift_sale(product_id: str, units: int, unit_price_cents: int) -> dict:
    resp = api_client.create_thrift_sale(
        create_thrift_sale_payload(product_id, units=units, unit_price_cents=unit_price_cents),
        TEST_USERS["thrift_headers"],
    )
    return _ok("create_thrift_sale", resp)


# ---------------------------------------------------------------------------
# Tier 1: state progression — walk entities to specific states
# ---------------------------------------------------------------------------

def walk_batch_to_released(
    batch_id: str,
    operator_id: str = "op-1",
    qa_id: str = "qa-1",
    bake_complete_clock: str = "2026-08-09T09:00:00Z",
) -> dict:
    """Walk a SCHEDULED batch through MIXING -> PROOFING -> BAKING -> COOLING
    -> RELEASED. Assumes the plan is RELEASED and the clock is before
    proof start. Returns the RELEASED batch."""
    op = make_operator_headers(operator_id)
    qa = make_qa_headers(qa_id)
    _ok("start_mix", api_client.start_mix(batch_id, op))
    _ok("start_proof", api_client.start_proof(batch_id, op))
    set_clock(bake_complete_clock)
    _ok("start_bake", api_client.start_bake(batch_id, op))
    _ok("complete_bake", api_client.complete_bake(batch_id, op))
    return _ok("release_batch", api_client.release_batch(batch_id, qa))


def walk_route_to_dispatched(route_id: str, driver_id: str) -> dict:
    """PLANNED -> LOADING -> DISPATCHED. Caller must have created >=1 stop whose
    order is LOCKED or SHORTED, and loaded_units must fit the truck."""
    hdrs = make_driver_headers(driver_id)
    _ok("start_loading", api_client.start_loading(route_id, hdrs))
    return _ok("dispatch_route", api_client.dispatch_route(route_id, hdrs))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — the canonical plant with master data
# ---------------------------------------------------------------------------

def setup_plant_with_master_data(
    plant_name: str = "Plant",
    product_overrides: dict = None,
    store_overrides: dict = None,
    line_overrides: dict = None,
    second_product_overrides: dict = None,
) -> dict:
    """Plant + product A (+ optional product D/B) + store + driver + line.

    Returns a dict of the created entities with keys:
      plant, product_a, store, driver, line, [product_b]
    """
    plant = create_plant(name=plant_name)
    product_a = create_product(plant["id"], **(product_overrides or {}))
    result = {
        "plant": plant,
        "product_a": product_a,
        "store": create_store(plant["id"], **(store_overrides or {})),
        "driver": create_driver(plant["id"]),
        "line": create_line(plant["id"], **(line_overrides or {})),
    }
    if second_product_overrides is not None:
        result["product_b"] = create_product(plant["id"], **second_product_overrides)
    return result


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — distribution chain
# ---------------------------------------------------------------------------

def setup_released_batch_scenario(
    plant_name: str = "Plant",
    order_qty: int = 100,
    batch_qty: int = None,
    product_overrides: dict = None,
    store_overrides: dict = None,
    bake_complete_clock: str = "2026-08-09T09:00:00Z",
    second_product: bool = False,
) -> dict:
    """Plant + product A (+ optional product D) + store + driver + line +
    order (LOCKED) + plan (RELEASED) + batch A (RELEASED).

    The order delivery_date is 2026-08-10 (cutoff 2026-08-08T08:00:00Z with the
    default 48h lead time). The plan bakes for 2026-08-09. Batch A is walked
    through to RELEASED by operator op-1 / qa-1, with bake_completed_at pinned
    to `bake_complete_clock`.

    Returns dict: plant, product_a, [product_b], store, driver, line, order,
    plan, batch.
    """
    second_overrides = None
    if second_product:
        second_overrides = {
            "sku": "SKU-D",
            "name": "Bun 200",
            "allergen_class": "NONE",
            "unit_weight_g": 200,
            "shelf_life_hours": 48,
            "base_price_cents": 99,
            "flour_share_pct": 0.20,
            "butter_share_pct": 0.05,
            "batch_capacity_units": 200,
        }
    ctx = setup_plant_with_master_data(
        plant_name=plant_name,
        product_overrides=product_overrides,
        store_overrides=store_overrides,
        second_product_overrides=second_overrides,
    )
    plant = ctx["plant"]
    product_a = ctx["product_a"]
    store = ctx["store"]
    line = ctx["line"]

    # Start clock before the order cutoff (2026-08-08T08:00:00Z for the
    # default 48h lead-time store with delivery 2026-08-10).
    set_clock("2026-08-06T00:00:00Z")

    order = create_order(store["id"], product_a["id"], qty=order_qty)
    confirm_order(order["id"])
    lock_order(order["id"])

    plan = create_plan(plant["id"], expected_plant_version=plant["version"])
    locked_plan = lock_plan(plan["id"])
    batch = create_batch(
        plan["id"],
        line["id"],
        product_a["id"],
        plan_version=locked_plan["version"],
        qty_units=batch_qty if batch_qty is not None else order_qty,
    )
    release_plan(plan["id"])

    # Walk batch A through to RELEASED; set clock to a valid proof start.
    set_clock("2026-08-09T07:50:00Z")
    batch = walk_batch_to_released(
        batch["id"], operator_id="op-1", qa_id="qa-1", bake_complete_clock=bake_complete_clock
    )

    ctx.update({"order": order, "plan": plan, "batch": batch})
    return ctx


def setup_dispatched_route_scenario(
    plant_name: str = "Plant",
    order_qty: int = 100,
    deliver_clock: str = "2026-08-10T09:00:00Z",
    **kwargs,
) -> dict:
    """Extends setup_released_batch_scenario: adds a route on 2026-08-10 with
    one stop covering the order, walks the route to DISPATCHED, and sets the
    clock to `deliver_clock` ready for a deliver call.

    Returns dict with additional keys: route, stop.
    """
    ctx = setup_released_batch_scenario(plant_name=plant_name, order_qty=order_qty, **kwargs)
    plant = ctx["plant"]
    driver = ctx["driver"]
    order = ctx["order"]
    batch = ctx["batch"]

    route = create_route(plant["id"], driver["id"])
    stop = create_stop(route["id"], order["id"], order_qty, [batch["id"]])
    walk_route_to_dispatched(route["id"], driver["id"])
    set_clock(deliver_clock)

    ctx.update({"route": route, "stop": stop})
    return ctx


def setup_delivered_stop_scenario(
    plant_name: str = "Plant",
    order_qty: int = 100,
    delivered_units: int = None,
    on_shelf_units_observed: int = 0,
    deliver_clock: str = "2026-08-10T09:00:00Z",
    **kwargs,
) -> dict:
    """Extends setup_dispatched_route_scenario: driver delivers the stop at
    `deliver_clock`. Returns dict with the re-fetched stop (status DELIVERED).
    """
    ctx = setup_dispatched_route_scenario(
        plant_name=plant_name,
        order_qty=order_qty,
        deliver_clock=deliver_clock,
        **kwargs,
    )
    driver = ctx["driver"]
    stop = ctx["stop"]
    qty = delivered_units if delivered_units is not None else order_qty
    delivered_stop = _ok(
        "deliver_route_stop",
        api_client.deliver_route_stop(
            stop["id"],
            {"delivered_units": qty, "on_shelf_units_observed": on_shelf_units_observed},
            make_driver_headers(driver["id"]),
        ),
    )
    ctx["stop"] = delivered_stop
    return ctx


def setup_verified_stale_return_scenario(
    plant_name: str = "Plant",
    stale_lines_qty: int = 3,
    pickup_clock: str = "2026-08-10T15:00:00Z",
    verify_qty: int = None,
    **kwargs,
) -> dict:
    """Extends setup_delivered_stop_scenario: at `pickup_clock` the driver
    records a stale return of `stale_lines_qty` units against the batch, then
    QA verifies with `verify_qty` (defaults to the same). Returns dict with
    stale_return (VERIFIED)."""
    ctx = setup_delivered_stop_scenario(plant_name=plant_name, **kwargs)
    store = ctx["store"]
    driver = ctx["driver"]
    stop = ctx["stop"]
    batch = ctx["batch"]

    set_clock(pickup_clock)
    sre = create_stale_return(
        store["id"], stop["id"], [{"batch_id": batch["id"], "qty": stale_lines_qty}], driver["id"]
    )
    v_qty = verify_qty if verify_qty is not None else stale_lines_qty
    verified = _ok(
        "verify_stale_return",
        api_client.verify_stale_return(
            sre["id"],
            {"verified_lines": [{"batch_id": batch["id"], "qty": v_qty}]},
            make_qa_headers("qa-1"),
        ),
    )
    ctx["stale_return"] = verified
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_locked_plan_with_gross(gross_units: int, plant_name: str = "Plant") -> dict:
    """Plant + product A + store + one LOCKED order of `gross_units` for
    2026-08-10, and a DRAFT plan for the same bake_date. Returns dict; the
    caller can then call lock_plan(plan_id) and read the computed fields."""
    ctx = setup_plant_with_master_data(plant_name=plant_name)
    plant = ctx["plant"]
    product_a = ctx["product_a"]
    store = ctx["store"]

    set_clock("2026-08-06T00:00:00Z")
    order = create_order(store["id"], product_a["id"], qty=gross_units)
    confirm_order(order["id"])
    lock_order(order["id"])

    # PRD §3.3: gross is summed over LOCKED orders whose delivery_date equals
    # the plan's bake_date — the plan must bake for the order's delivery date.
    plan = create_plan(
        plant["id"], expected_plant_version=plant["version"], bake_date="2026-08-10"
    )
    ctx.update({"order": order, "plan": plan})
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: terminal / settlement scenarios
# ---------------------------------------------------------------------------

def setup_settled_route_scenario(
    plant_name: str = "Plant",
    order_qty: int = 100,
    delivered_units: int = 100,
    store_shelf_capacity: int = 500,
    **kwargs,
) -> dict:
    """Delivers the stop, completes the route, settles it. Returns dict with
    the SETTLED route under ctx['route']."""
    store_overrides = kwargs.pop("store_overrides", {}) or {}
    store_overrides.setdefault("shelf_capacity_units", store_shelf_capacity)
    ctx = setup_delivered_stop_scenario(
        plant_name=plant_name,
        order_qty=order_qty,
        delivered_units=delivered_units,
        store_overrides=store_overrides,
        **kwargs,
    )
    route = ctx["route"]
    driver = ctx["driver"]
    hdrs = make_driver_headers(driver["id"])
    _ok("complete_route", api_client.complete_route(route["id"], hdrs))
    settled = _ok(
        "settle_route",
        api_client.settle_route(route["id"], {}, TEST_USERS["planner_headers"]),
    )
    ctx["route"] = settled
    return ctx


def setup_line_dirty_with_sesame(plant_name: str = "Plant") -> dict:
    """Plant + product B (SESAME) + line. A SESAME batch runs to COOLING at
    2026-08-09T08:10:00Z, leaving the line DIRTY with SESAME residue.

    Returns dict: plant, product_b, line, plan (RELEASED), batch (COOLING).
    """
    plant = create_plant(name=plant_name)
    product_b = create_product(
        plant["id"],
        sku="SKU-B",
        name="Sesame 300",
        allergen_class="SESAME",
        unit_weight_g=300,
        shelf_life_hours=48,
        base_price_cents=299,
        flour_share_pct=0.25,
        butter_share_pct=0.05,
        batch_capacity_units=400,
    )
    line = create_line(plant["id"])

    set_clock("2026-08-09T07:00:00Z")
    plan = create_plan(plant["id"], expected_plant_version=plant["version"])
    locked_plan = lock_plan(plan["id"])
    batch = create_batch(
        plan["id"],
        line["id"],
        product_b["id"],
        plan_version=locked_plan["version"],
        qty_units=100,
    )
    release_plan(plan["id"])

    op = make_operator_headers("op-1")
    _ok("start_mix", api_client.start_mix(batch["id"], op))
    _ok("start_proof", api_client.start_proof(batch["id"], op))
    set_clock("2026-08-09T08:10:00Z")
    _ok("start_bake", api_client.start_bake(batch["id"], op))
    _ok("complete_bake", api_client.complete_bake(batch["id"], op))

    return {
        "plant": plant,
        "product_b": product_b,
        "line": line,
        "plan": plan,
        "batch": batch,
    }


def setup_two_product_delivered_scenario(
    plant_name: str = "Plant Alpha",
    deliver_clock: str = "2026-08-10T09:00:00Z",
    after_delivery_clock: str = "2026-08-10T15:00:00Z",
) -> dict:
    """Two products: A (500g, 199c) baked 2026-08-09T09:00:00Z, D (200g, 99c)
    baked 2026-08-09T10:10:00Z. Route on 2026-08-10 with the order stop
    DELIVERED 100/100 at `deliver_clock`, then clock advanced to
    `after_delivery_clock` so batch A age is 30h and batch D age is ~28h50m —
    both lines in the 25..48h rate tier (0.50).

    Returns dict: plant, product_a, product_b, store, driver, line, order,
    plan, batch (A), batch_d, route, stop.
    """
    ctx = setup_released_batch_scenario(
        plant_name=plant_name,
        order_qty=100,
        second_product=True,
        bake_complete_clock="2026-08-09T09:00:00Z",
    )
    plant = ctx["plant"]
    driver = ctx["driver"]
    order = ctx["order"]
    batch_a = ctx["batch"]
    product_b = ctx["product_b"]
    line = ctx["line"]
    plan = ctx["plan"]

    # Schedule the D batch on the same line for the 09:00-10:00 slot.
    plan_now = get_plan(plan["id"])
    batch_d = create_batch(
        plan["id"],
        line["id"],
        product_b["id"],
        plan_version=plan_now["version"],
        qty_units=50,
        scheduled_start_at="2026-08-09T09:00:00Z",
        scheduled_end_at="2026-08-09T10:00:00Z",
    )
    # Plan is already RELEASED so we can run D immediately.
    op = make_operator_headers("op-1")
    qa = make_qa_headers("qa-1")
    _ok("start_mix_d", api_client.start_mix(batch_d["id"], op))
    _ok("start_proof_d", api_client.start_proof(batch_d["id"], op))
    set_clock("2026-08-09T10:10:00Z")
    _ok("start_bake_d", api_client.start_bake(batch_d["id"], op))
    _ok("complete_bake_d", api_client.complete_bake(batch_d["id"], op))
    _ok("release_batch_d", api_client.release_batch(batch_d["id"], qa))

    route = create_route(plant["id"], driver["id"])
    stop = create_stop(route["id"], order["id"], 100, [batch_a["id"]])
    walk_route_to_dispatched(route["id"], driver["id"])
    set_clock(deliver_clock)
    delivered_stop = _ok(
        "deliver_route_stop",
        api_client.deliver_route_stop(
            stop["id"],
            {"delivered_units": 100, "on_shelf_units_observed": 0},
            make_driver_headers(driver["id"]),
        ),
    )
    set_clock(after_delivery_clock)
    ctx.update({"batch_d": batch_d, "route": route, "stop": delivered_stop})
    return ctx


def setup_surcharge_scenario(
    plant_name: str = "Plant",
    flour_forecast=440,
    butter_forecast=600,
    period: str = "2026-08",
) -> dict:
    """Plant + product C + FLOUR/BUTTER FORECAST indices + PROVISIONAL
    surcharge schedule for the period. Returns dict: plant, product_c,
    index_flour, index_butter, schedule."""
    plant = create_plant(name=plant_name)
    product_c = create_product(
        plant["id"],
        sku="SKU-C",
        name="Brioche 250",
        allergen_class="NONE",
        unit_weight_g=250,
        shelf_life_hours=48,
        base_price_cents=249,
        flour_share_pct=0.30,
        butter_share_pct=0.10,
        batch_capacity_units=200,
    )
    idx_flour = create_ingredient_index(plant["id"], "FLOUR", period, flour_forecast)
    idx_butter = create_ingredient_index(plant["id"], "BUTTER", period, butter_forecast)
    schedule = create_surcharge_schedule(product_c["id"], period)
    return {
        "plant": plant,
        "product_c": product_c,
        "index_flour": idx_flour,
        "index_butter": idx_butter,
        "schedule": schedule,
    }
