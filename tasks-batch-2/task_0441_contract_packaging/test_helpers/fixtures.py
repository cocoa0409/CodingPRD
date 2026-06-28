"""Composite setup helpers.

These encapsulate the multi-step preambles the test claims share so test
functions can focus on assertions. All setup uses get_success_data() (the
lenient validator) so a setup failure produces a clear "Setup failed" error.

Each test runs against a freshly restarted, empty server, so every helper
builds its preconditions from scratch using only PRD-declared endpoints.

Naming uses PRD domain language (customers, recipes, lots, runs); field names
match the PRD exactly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS

RECEIVER = TEST_USERS["receiver_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
QA = TEST_USERS["qa_inspector_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the server logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, SCHEDULER))


# ---------------------------------------------------------------------------
# Tier 1: primitive create helpers
# ---------------------------------------------------------------------------

def create_customer(name="Acme Foods", code="ACME", owns_components=None):
    payload = {"name": name, "code": code}
    if owns_components is not None:
        payload["owns_components"] = owns_components
    return get_success_data(api_client.create_customer(payload, RECEIVER))


def create_component(customer_id, sku, name, kind="INGREDIENT", allergens=None):
    payload = {"customer_id": customer_id, "sku": sku, "name": name, "kind": kind}
    if allergens is not None:
        payload["allergens"] = allergens
    return get_success_data(api_client.create_component(payload, RECEIVER))


def receive_lot(component_id, supplier_lot_code, received_qty, expiration_date):
    payload = {
        "supplier_lot_code": supplier_lot_code,
        "received_qty": received_qty,
        "expiration_date": expiration_date,
    }
    return get_success_data(api_client.receive_lot(component_id, payload, RECEIVER))


def create_recipe(customer_id, name="Granola",
                  target_fill_weight_g=200, fill_tolerance_pct=5, shelf_life_days=90):
    payload = {
        "customer_id": customer_id,
        "name": name,
        "target_fill_weight_g": target_fill_weight_g,
        "fill_tolerance_pct": fill_tolerance_pct,
        "shelf_life_days": shelf_life_days,
    }
    return get_success_data(api_client.create_recipe(payload, SCHEDULER))


def add_bom_line(recipe_id, component_id, expected_recipe_version,
                 qty_per_unit=2, scrap_factor_pct=None):
    payload = {
        "component_id": component_id,
        "qty_per_unit": qty_per_unit,
        "expected_recipe_version": expected_recipe_version,
    }
    if scrap_factor_pct is not None:
        payload["scrap_factor_pct"] = scrap_factor_pct
    return get_success_data(api_client.add_bom_line(recipe_id, payload, SCHEDULER))


def create_production_line(name="Line A", rated_units_per_hour=50, changeover_minutes=None):
    payload = {"name": name, "rated_units_per_hour": rated_units_per_hour}
    if changeover_minutes is not None:
        payload["changeover_minutes"] = changeover_minutes
    return get_success_data(api_client.create_production_line(payload, SCHEDULER))


def create_crew(name="Day Crew", rest_buffer_minutes=None):
    payload = {"name": name}
    if rest_buffer_minutes is not None:
        payload["rest_buffer_minutes"] = rest_buffer_minutes
    return get_success_data(api_client.create_crew(payload, SCHEDULER))


def schedule_run(recipe_id, line_id, crew_id, planned_units=100,
                 scheduled_start="2026-06-01T08:00:00Z"):
    payload = {
        "recipe_id": recipe_id,
        "line_id": line_id,
        "crew_id": crew_id,
        "planned_units": planned_units,
        "scheduled_start": scheduled_start,
    }
    return get_success_data(api_client.schedule_run(payload, SCHEDULER))


# ---------------------------------------------------------------------------
# Tier 2: approved-recipe builders
# ---------------------------------------------------------------------------

def build_approved_recipe(customer_id, ingredient_component_id, packaging_component_id,
                          name="Granola", ingredient_qty=2, ingredient_scrap=None,
                          packaging_qty=1,
                          target_fill_weight_g=200, fill_tolerance_pct=5,
                          shelf_life_days=90):
    """Create a DRAFT recipe with one INGREDIENT + one PACKAGING bom line, then
    submit and approve it. Returns the approved recipe dict (after approve)."""
    recipe = create_recipe(
        customer_id, name=name,
        target_fill_weight_g=target_fill_weight_g,
        fill_tolerance_pct=fill_tolerance_pct,
        shelf_life_days=shelf_life_days,
    )
    add_bom_line(recipe["id"], ingredient_component_id, recipe["version"],
                 qty_per_unit=ingredient_qty, scrap_factor_pct=ingredient_scrap)
    # Adding a BOM line bumps the recipe's version (PRD 3.2), so the second add
    # must carry the recipe's CURRENT version, not the first BOM line's version.
    recipe_now = get_success_data(api_client.get_recipe(recipe["id"], SCHEDULER))
    add_bom_line(recipe["id"], packaging_component_id, recipe_now["version"],
                 qty_per_unit=packaging_qty)
    get_success_data(api_client.submit_recipe(recipe["id"], SCHEDULER))
    return get_success_data(api_client.approve_recipe(recipe["id"], QA))


# ---------------------------------------------------------------------------
# Tier 3: standard single-ingredient scenario (the most common preamble)
# ---------------------------------------------------------------------------

def setup_basic_scenario(owns_components=None, almond_qty=2, almond_scrap=None,
                         almond_received=1000, almond_exp="2026-12-31T00:00:00Z",
                         recipe_name="Granola", target_fill_weight_g=200,
                         fill_tolerance_pct=5, shelf_life_days=90,
                         rest_buffer_minutes=None, changeover_minutes=None,
                         pouch_qty=1):
    """Build a complete schedule-ready scenario: customer, an ALMOND INGREDIENT
    component with one lot, a POUCH PACKAGING component with one lot, an APPROVED
    recipe (ALMOND + POUCH), one line, and one crew.

    Returns a dict of all created entities and useful versions.
    """
    customer = create_customer(owns_components=owns_components)
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    almond_lot = receive_lot(almond["id"], "ALM-1", almond_received, almond_exp)
    pouch_lot = receive_lot(pouch["id"], "POU-1", 1000, "2027-12-31T00:00:00Z")
    recipe = build_approved_recipe(
        customer["id"], almond["id"], pouch["id"],
        name=recipe_name, ingredient_qty=almond_qty, ingredient_scrap=almond_scrap,
        packaging_qty=pouch_qty,
        target_fill_weight_g=target_fill_weight_g,
        fill_tolerance_pct=fill_tolerance_pct, shelf_life_days=shelf_life_days,
    )
    line = create_production_line(changeover_minutes=changeover_minutes)
    crew = create_crew(rest_buffer_minutes=rest_buffer_minutes)
    return {
        "customer": customer,
        "almond": almond,
        "pouch": pouch,
        "almond_lot": almond_lot,
        "pouch_lot": pouch_lot,
        "recipe": recipe,
        "line": line,
        "crew": crew,
    }


def setup_scheduled_run(planned_units=100, scheduled_start="2026-06-01T08:00:00Z",
                        **scenario_overrides):
    """setup_basic_scenario + one SCHEDULED run. Returns (scenario, run)."""
    scenario = setup_basic_scenario(**scenario_overrides)
    run = schedule_run(
        scenario["recipe"]["id"], scenario["line"]["id"], scenario["crew"]["id"],
        planned_units=planned_units, scheduled_start=scheduled_start,
    )
    return scenario, run


def setup_running_run(planned_units=100, scheduled_start="2026-06-01T08:00:00Z",
                      start_clock="2026-06-01T08:00:00Z", **scenario_overrides):
    """A run advanced to RUNNING. Sets the clock to start_clock, then starts.
    Returns (scenario, started_run)."""
    scenario, run = setup_scheduled_run(
        planned_units=planned_units, scheduled_start=scheduled_start,
        **scenario_overrides,
    )
    set_clock(start_clock)
    started = get_success_data(api_client.start_run(
        run["id"], {"expected_line_version": scenario["line"]["version"]}, SCHEDULER,
    ))
    return scenario, started


def setup_pending_qa_run(planned_units=100, scheduled_start="2026-06-01T08:00:00Z",
                         start_clock="2026-06-01T08:00:00Z",
                         complete_clock="2026-06-01T10:00:00Z",
                         actual_units_good=100, actual_units_scrapped=0,
                         **scenario_overrides):
    """A run advanced to PENDING_QA (started + completed). Returns
    (scenario, run). No checkweigh samples are added by default."""
    scenario, started = setup_running_run(
        planned_units=planned_units, scheduled_start=scheduled_start,
        start_clock=start_clock, **scenario_overrides,
    )
    set_clock(complete_clock)
    run = get_success_data(api_client.complete_run(
        started["id"],
        {"actual_units_good": actual_units_good,
         "actual_units_scrapped": actual_units_scrapped},
        SCHEDULER,
    ))
    return scenario, run


def add_passing_sample(run_id, measured_weight_g=200):
    """Record one checkweigh sample that PASSES (target 200, default band)."""
    return get_success_data(api_client.add_checkweigh_sample(
        run_id, {"measured_weight_g": measured_weight_g}, QA,
    ))


def setup_released_run(**overrides):
    """Drive a run all the way to RELEASED (PENDING_QA + one passing sample +
    release). Returns (scenario, released_run)."""
    scenario, run = setup_pending_qa_run(**overrides)
    add_passing_sample(run["id"])
    released = get_success_data(api_client.release_run(run["id"], QA))
    return scenario, released


# ---------------------------------------------------------------------------
# Tier 4: multi-line / dirty-line scenarios for allergen + overlap tests
# ---------------------------------------------------------------------------

def setup_dirty_line_with_clean_recipe(almond_received=1000, buffer=0):
    """Build a line dirtied with PEANUT residue (a started peanut run) plus a
    SCHEDULED allergen-free almond run on the same line whose almond lot holds
    `almond_received`. Returns a dict with line, the two runs, versions, ids.

    Sequence:
      - customer
      - PNUT INGREDIENT(PEANUT) + ALMOND INGREDIENT + POUCH PACKAGING, each w/ a lot
      - approved peanut recipe + approved almond-plain recipe
      - line, two buffer-free crews
      - schedule peanut run @08:00, set clock 08:00, start it (line now PEANUT-dirty)
      - advance clock to 11:00
      - schedule almond run @12:00 (no overlap)
    """
    customer = create_customer()
    pnut = create_component(customer["id"], "PNUT", "Peanuts", "INGREDIENT",
                            allergens=["PEANUT"])
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    receive_lot(pnut["id"], "PNUT-1", 1000, "2026-12-31T00:00:00Z")
    receive_lot(almond["id"], "ALM-1", almond_received, "2026-12-31T00:00:00Z")
    receive_lot(pouch["id"], "POU-1", 1000, "2027-12-31T00:00:00Z")

    recipe_pnut = build_approved_recipe(customer["id"], pnut["id"], pouch["id"],
                                        name="Peanut Mix")
    recipe_alm = build_approved_recipe(customer["id"], almond["id"], pouch["id"],
                                       name="Almond Plain", ingredient_scrap=5)

    line = create_production_line()
    crew1 = create_crew(name="Crew 1", rest_buffer_minutes=buffer)
    crew2 = create_crew(name="Crew 2", rest_buffer_minutes=buffer)

    run_pnut = schedule_run(recipe_pnut["id"], line["id"], crew1["id"],
                            scheduled_start="2026-06-01T08:00:00Z")
    set_clock("2026-06-01T08:00:00Z")
    started_pnut = get_success_data(api_client.start_run(
        run_pnut["id"], {"expected_line_version": line["version"]}, SCHEDULER,
    ))
    line_v_after_start = started_pnut["version"]  # run version, not line
    # Read the line to get its post-start version.
    line_after = get_success_data(api_client.get_production_line(line["id"], SCHEDULER))
    set_clock("2026-06-01T11:00:00Z")
    run_alm = schedule_run(recipe_alm["id"], line["id"], crew2["id"],
                           scheduled_start="2026-06-01T12:00:00Z")
    return {
        "customer": customer,
        "line": line,
        "line_after": line_after,
        "line_version_dirty": line_after["version"],
        "recipe_pnut": recipe_pnut,
        "recipe_alm": recipe_alm,
        "run_pnut": run_pnut,
        "run_alm": run_alm,
        "almond": almond,
        "pouch": pouch,
    }
