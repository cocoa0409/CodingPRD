"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup steps use the lenient success validator so
a broken precondition surfaces as a clear "Setup step failed" error instead of
a confusing assertion failure deep in a test.

OCC threading: the run-create and changeover-create helpers re-read the parent
aggregate's current version by default (the client re-reads and retries per
PRD §2.8); pass an explicit expected_*_version to exercise the stale path.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_BUILD_END,
    DEFAULT_BUILD_START,
    DEFAULT_SHIP_END,
    DEFAULT_SHIP_START,
    SETUP_CLOCK,
)
from .factories import (
    complete_run_payload,
    create_changeover_payload,
    create_gift_component_payload,
    create_mold_payload,
    create_packaging_component_payload,
    create_product_payload,
    create_production_line_payload,
    create_production_run_payload,
    create_quality_hold_payload,
    create_recipe_payload,
    create_seasonal_window_payload,
    disposition_payload,
)
from .test_users import (
    TEST_USERS,
    make_quality_manager_headers,
    make_sanitation_lead_headers,
)

PLANNER = TEST_USERS["production_planner_headers"]
MANAGER = TEST_USERS["plant_manager_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
SANITATION = TEST_USERS["sanitation_lead_headers"]
QA = TEST_USERS["quality_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and plain readers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server logical clock. Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def get_window(window_id):
    return get_success_data(api_client.get_seasonal_window(window_id, PLANNER))


def get_line(line_id):
    return get_success_data(api_client.get_production_line(line_id, PLANNER))


def get_run(run_id):
    return get_success_data(api_client.get_production_run(run_id, PLANNER))


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, PLANNER))


def get_hold(hold_id):
    return get_success_data(api_client.get_quality_hold(hold_id, PLANNER))


def get_changeover(changeover_id):
    return get_success_data(api_client.get_changeover(changeover_id, PLANNER))


def list_components():
    data, _meta = validate_paginated(api_client.list_packaging_components(PLANNER))
    return data


def get_component(component_id):
    for row in list_components():
        if row["id"] == component_id:
            return row
    raise AssertionError(f"Setup failed: component {component_id} not listed")


def list_lots_for_run(run_id):
    data, _meta = validate_paginated(
        api_client.list_lots(PLANNER, params={"run_id": run_id}))
    return data


def list_holds_for_lot(lot_id):
    data, _meta = validate_paginated(
        api_client.list_quality_holds(PLANNER, params={"lot_id": lot_id}))
    return data


# ---------------------------------------------------------------------------
# Tier 1: master data creation
# ---------------------------------------------------------------------------

def create_packaging_component(sku_code="BOX-24", name="24pc box",
                               units_per_component=10, lead_time_days=14,
                               qty_on_hand=100000):
    payload = create_packaging_component_payload(
        sku_code=sku_code, name=name, units_per_component=units_per_component,
        lead_time_days=lead_time_days, qty_on_hand=qty_on_hand)
    return get_success_data(api_client.create_packaging_component(payload, PLANNER))


def create_product(packaging_component_id, sku_code="NOVELTY", name="Novelty",
                   product_type="STANDARD", brand="OWN", base_price_cents=800,
                   unit_weight_grams=100, shelf_life_days=200,
                   customer_name=None):
    overrides = {}
    if customer_name is not None:
        overrides["customer_name"] = customer_name
    payload = create_product_payload(
        packaging_component_id, sku_code=sku_code, name=name,
        product_type=product_type, brand=brand, base_price_cents=base_price_cents,
        unit_weight_grams=unit_weight_grams, shelf_life_days=shelf_life_days,
        **overrides)
    return get_success_data(api_client.create_product(payload, PLANNER))


def create_recipe(product_id, name="Mass", shape_code="STAR",
                  cook_temp_min_c=80, cook_temp_max_c=90,
                  temper_exit_min_c=28, temper_exit_max_c=30,
                  allergens=(), standard_yield_pct=0.95):
    payload = create_recipe_payload(
        product_id, name=name, shape_code=shape_code,
        cook_temp_min_c=cook_temp_min_c, cook_temp_max_c=cook_temp_max_c,
        temper_exit_min_c=temper_exit_min_c, temper_exit_max_c=temper_exit_max_c,
        allergens=list(allergens), standard_yield_pct=standard_yield_pct)
    return get_success_data(api_client.create_recipe(payload, PLANNER))


def add_gift_component(gift_product_id, component_product_id, qty_per_set):
    payload = create_gift_component_payload(
        gift_product_id, component_product_id, qty_per_set)
    return get_success_data(api_client.create_gift_component(payload, PLANNER))


def create_mold(shape_code="STAR", cavity_count=60):
    payload = create_mold_payload(shape_code=shape_code, cavity_count=cavity_count)
    return get_success_data(api_client.create_mold(payload, PLANNER))


def create_line(name="LINE-1"):
    payload = create_production_line_payload(name=name)
    return get_success_data(api_client.create_production_line(payload, PLANNER))


# ---------------------------------------------------------------------------
# Tier 1: seasonal windows
# ---------------------------------------------------------------------------

def create_window(season_code="BASE", build_start=DEFAULT_BUILD_START,
                  build_end=DEFAULT_BUILD_END, ship_start=DEFAULT_SHIP_START,
                  ship_end=DEFAULT_SHIP_END, target_units=5000,
                  markdown_tiers=()):
    payload = create_seasonal_window_payload(
        season_code=season_code, build_start=build_start, build_end=build_end,
        ship_start=ship_start, ship_end=ship_end, target_units=target_units,
        markdown_tiers=list(markdown_tiers))
    return get_success_data(api_client.create_seasonal_window(payload, PLANNER))


def publish_window(window_id):
    return get_success_data(api_client.publish_window(window_id, MANAGER))


def close_window(window_id):
    return get_success_data(api_client.close_window(window_id, MANAGER))


def create_published_window(**kwargs):
    """Create a window and publish it. Returns the PUBLISHED window."""
    return publish_window(create_window(**kwargs)["id"])


# ---------------------------------------------------------------------------
# Tier 2: changeover protocol (open -> swab -> release)
# ---------------------------------------------------------------------------

def open_changeover(line_id, changeover_type, to_mold_id=None,
                    target_allergens=None, expected_line_version=None):
    """Open a changeover on a line. The line's current version is re-read when
    no explicit expected_line_version is given (OCC). Returns the changeover."""
    if expected_line_version is None:
        expected_line_version = get_line(line_id)["version"]
    payload = create_changeover_payload(
        changeover_type, expected_line_version, to_mold_id=to_mold_id,
        target_allergens=target_allergens)
    return get_success_data(api_client.create_changeover(line_id, payload, OPERATOR))


def swab_changeover(changeover_id, user_id="san-1"):
    """Sanitation lead records a passing swab. Returns the changeover."""
    headers = make_sanitation_lead_headers(user_id)
    return get_success_data(
        api_client.record_swab(changeover_id, {"swab_passed": True}, headers))


def release_changeover(changeover_id, user_id="qm-1"):
    """Quality manager releases the changeover. Returns the changeover."""
    headers = make_quality_manager_headers(user_id)
    return get_success_data(api_client.release_changeover(changeover_id, headers))


def run_changeover_cycle(line_id, changeover_type, to_mold_id=None,
                         target_allergens=None, swab_user="san-1",
                         qa_user="qm-1"):
    """Full open -> swab(pass) -> release cycle. Returns the RELEASED changeover."""
    changeover = open_changeover(line_id, changeover_type, to_mold_id=to_mold_id,
                                 target_allergens=target_allergens)
    swab_changeover(changeover["id"], user_id=swab_user)
    return release_changeover(changeover["id"], user_id=qa_user)


def prepare_line(shape_code="STAR", cleared_allergens=(), name="LINE-1",
                 cavity_count=60):
    """Create a line and a mold, then run a changeover cycle that installs the
    mold and leaves the line cleared for exactly `cleared_allergens` (an empty
    set uses a mold-swap changeover, which resets clearance to empty).
    Returns (line, mold) with the line re-read after release."""
    mold = create_mold(shape_code=shape_code, cavity_count=cavity_count)
    line = create_line(name)
    if cleared_allergens:
        run_changeover_cycle(line["id"], "ALLERGEN_WASH", to_mold_id=mold["id"],
                             target_allergens=list(cleared_allergens))
    else:
        run_changeover_cycle(line["id"], "SHAPE_ONLY", to_mold_id=mold["id"])
    return get_line(line["id"]), mold


# ---------------------------------------------------------------------------
# Tier 3: production runs and lots
# ---------------------------------------------------------------------------

def create_run(window_id, product_id, recipe_id, line_id, run_type="STANDARD",
               planned_units=500, scheduled_start="2026-09-05T08:00:00Z",
               scheduled_end="2026-09-05T16:00:00Z", expected_window_version=None,
               source_lot_id=None, rework_qty=None):
    """Schedule a run. The window's current version is re-read when no explicit
    expected_window_version is given (OCC). Returns the PLANNED run."""
    if expected_window_version is None:
        expected_window_version = get_window(window_id)["version"]
    overrides = {}
    if source_lot_id is not None:
        overrides["source_lot_id"] = source_lot_id
    if rework_qty is not None:
        overrides["rework_qty"] = rework_qty
    payload = create_production_run_payload(
        window_id, product_id, recipe_id, line_id, expected_window_version,
        run_type=run_type, planned_units=planned_units,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end, **overrides)
    return get_success_data(api_client.create_production_run(payload, PLANNER))


def start_run(run_id):
    return get_success_data(api_client.start_run(run_id, OPERATOR))


def hold_run(run_id):
    return get_success_data(api_client.hold_run(run_id, OPERATOR))


def resume_run(run_id):
    return get_success_data(api_client.resume_run(run_id, OPERATOR))


def complete_run(run_id, output_units, actual_cook_temp_c=85,
                 actual_temper_exit_c=29):
    payload = complete_run_payload(
        output_units, actual_cook_temp_c=actual_cook_temp_c,
        actual_temper_exit_c=actual_temper_exit_c)
    return get_success_data(api_client.complete_run(run_id, payload, OPERATOR))


def cancel_run(run_id):
    return get_success_data(api_client.cancel_run(run_id, PLANNER))


def produce_lot(window_id, product_id, recipe_id, line_id, planned_units,
                output_units=None, scheduled_start="2026-09-05T08:00:00Z",
                scheduled_end="2026-09-05T16:00:00Z", actual_cook_temp_c=85,
                actual_temper_exit_c=29, run_type="STANDARD", source_lot_id=None,
                rework_qty=None):
    """Create -> start -> complete a run. Returns (completed_run, lot)."""
    run = create_run(window_id, product_id, recipe_id, line_id,
                     run_type=run_type, planned_units=planned_units,
                     scheduled_start=scheduled_start, scheduled_end=scheduled_end,
                     source_lot_id=source_lot_id, rework_qty=rework_qty)
    start_run(run["id"])
    done = complete_run(run["id"], output_units=output_units or planned_units,
                        actual_cook_temp_c=actual_cook_temp_c,
                        actual_temper_exit_c=actual_temper_exit_c)
    return done, get_lot(done["created_lot_id"])


# ---------------------------------------------------------------------------
# Tier 4: quality holds
# ---------------------------------------------------------------------------

def create_quality_hold(lot_id, defect_type="BLOOM", affected_units=1,
                        headers=None):
    """Open a hold on an ACTIVE lot. Returns the OPEN hold."""
    payload = create_quality_hold_payload(lot_id, defect_type=defect_type,
                                          affected_units=affected_units)
    return get_success_data(
        api_client.create_quality_hold(payload, headers or QA))


def disposition_hold(hold_id, action, user_id="qm-1"):
    """Disposition an OPEN hold (RELEASE/SCRAP/REWORK). Returns the hold."""
    headers = make_quality_manager_headers(user_id)
    return get_success_data(
        api_client.disposition_quality_hold(hold_id, disposition_payload(action),
                                            headers))


# ---------------------------------------------------------------------------
# Tier 5: composite plant setups
# ---------------------------------------------------------------------------

def setup_runnable_plant(product_type="STANDARD", sku_code="NOVELTY",
                         base_price_cents=800, shelf_life_days=200,
                         standard_yield_pct=0.95, allergens=(), shape_code="STAR",
                         cleared_allergens=(), season_code="BASE",
                         target_units=5000, markdown_tiers=(), qty_on_hand=100000,
                         units_per_component=10, lead_time_days=14,
                         line_name="LINE-1", clock=SETUP_CLOCK,
                         build_start=DEFAULT_BUILD_START,
                         build_end=DEFAULT_BUILD_END,
                         ship_start=DEFAULT_SHIP_START,
                         ship_end=DEFAULT_SHIP_END):
    """Full preamble: clock set, packaging component, product + recipe, line
    with the mold installed and the requested allergen clearance, and a
    published window. Returns a dict with every created resource."""
    set_clock(clock)
    component = create_packaging_component(
        qty_on_hand=qty_on_hand, units_per_component=units_per_component,
        lead_time_days=lead_time_days)
    product = create_product(
        component["id"], sku_code=sku_code, product_type=product_type,
        base_price_cents=base_price_cents, shelf_life_days=shelf_life_days)
    recipe = create_recipe(
        product["id"], shape_code=shape_code, allergens=allergens,
        standard_yield_pct=standard_yield_pct)
    line, mold = prepare_line(shape_code=shape_code,
                              cleared_allergens=cleared_allergens,
                              name=line_name)
    window = create_published_window(
        season_code=season_code, target_units=target_units,
        markdown_tiers=list(markdown_tiers), build_start=build_start,
        build_end=build_end, ship_start=ship_start, ship_end=ship_end)
    return {
        "component": component, "product": product, "recipe": recipe,
        "line": line, "mold": mold, "window": window,
    }


def setup_active_lot(output_units=1000, planned_units=None, clock=SETUP_CLOCK,
                     complete_clock=None, scheduled_start="2026-09-05T08:00:00Z",
                     scheduled_end="2026-09-05T16:00:00Z", actual_cook_temp_c=85,
                     actual_temper_exit_c=29, **plant_kwargs):
    """Runnable plant plus one completed STANDARD run. Returns the plant dict
    extended with "run" (completed) and "lot" (the produced lot)."""
    plant = setup_runnable_plant(clock=clock, **plant_kwargs)
    if complete_clock is not None:
        set_clock(complete_clock)
    run, lot = produce_lot(
        plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
        plant["line"]["id"], planned_units=planned_units or output_units,
        output_units=output_units, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end, actual_cook_temp_c=actual_cook_temp_c,
        actual_temper_exit_c=actual_temper_exit_c)
    plant["run"] = run
    plant["lot"] = lot
    return plant


def setup_gift_bom(gift_product_id, components):
    """Add bill-of-material rows. `components` is a list of
    (component_product_id, qty_per_set) tuples."""
    rows = []
    for component_product_id, qty_per_set in components:
        rows.append(add_gift_component(gift_product_id, component_product_id,
                                       qty_per_set))
    return rows


def setup_closed_window_with_seasonal_lots(lot_specs, markdown_tiers,
                                           target_units=5000,
                                           season_code="HOLIDAY",
                                           ship_end=DEFAULT_SHIP_END,
                                           close_clock="2027-01-02T00:00:00Z"):
    """A window carrying one ACTIVE lot of a SEASONAL product per spec, with the
    clock advanced strictly past ship_end and the window CLOSED.

    lot_specs: list of dicts {sku, base_price_cents, units, day} where day is a
    YYYY-MM-DD string inside the build corridor (one distinct day per lot).
    Returns {"window", "component", "line", "mold", "lots", "runs", "products"}.
    """
    set_clock(SETUP_CLOCK)
    component = create_packaging_component()
    line, mold = prepare_line()
    window = create_published_window(season_code=season_code,
                                     target_units=target_units,
                                     markdown_tiers=list(markdown_tiers),
                                     ship_end=ship_end)
    lots, runs, products = [], [], []
    for spec in lot_specs:
        product = create_product(component["id"], sku_code=spec["sku"],
                                 product_type="SEASONAL",
                                 base_price_cents=spec["base_price_cents"])
        recipe = create_recipe(product["id"])
        run, lot = produce_lot(
            window["id"], product["id"], recipe["id"], line["id"],
            planned_units=spec["units"], output_units=spec["units"],
            scheduled_start=f"{spec['day']}T08:00:00Z",
            scheduled_end=f"{spec['day']}T16:00:00Z")
        lots.append(lot)
        runs.append(run)
        products.append(product)
    set_clock(close_clock)
    window = close_window(window["id"])
    return {
        "window": window, "component": component, "line": line, "mold": mold,
        "lots": lots, "runs": runs, "products": products,
    }
