"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data
validator so a failed precondition raises a clear "Setup step failed" error.

Lookup helpers for child resources (drying session, packaging job, goods lot of
a run) list the collection and match on the recorded foreign key when present,
falling back to the singleton row — fixtures create children in a controlled
order so this is deterministic.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    NEXT_DAY_CLOCK,
    RUN_END_ISO,
    RUN_START_ISO,
    STANDARD_FINISH_CLOCK,
)
from .factories import (
    create_contract_payload,
    create_die_payload,
    create_gluten_test_payload,
    create_line_payload,
    create_lot_payload,
    create_pest_inspection_payload,
    create_recipe_payload,
    create_run_payload,
    create_zone_payload,
    index_reading_payload,
    lot_lab_results_payload,
)
from .test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
TECH = TEST_USERS["qa_technician_headers"]
QAM = TEST_USERS["qa_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
CLERK = TEST_USERS["warehouse_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock. Returns the reported current_utc payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PM)
    )


# ---------------------------------------------------------------------------
# Tier 1: contracts, readings, lots
# ---------------------------------------------------------------------------

def create_contract_draft(**overrides):
    """Create a contract (born DRAFT, cumulative 0). Returns the contract."""
    return get_success_data(api_client.create_contract(create_contract_payload(**overrides), PROC))


def create_active_contract(**overrides):
    """Create + activate a contract. Returns the ACTIVE contract."""
    contract = create_contract_draft(**overrides)
    return get_success_data(api_client.activate_contract(contract["id"], PM))


def add_index_reading(contract_id, effective_date, index_value):
    return get_success_data(api_client.create_index_reading(
        contract_id, index_reading_payload(effective_date, index_value), PROC))


def receive_lot(contract_id, received_weight_kg=100.0, delivery_date="2026-08-01",
                as_headers=None, **overrides):
    """Receive a semolina lot (born QUARANTINED). Returns the lot."""
    return get_success_data(api_client.create_semolina_lot(
        create_lot_payload(contract_id, received_weight_kg, delivery_date, **overrides),
        as_headers or PROC,
    ))


def submit_lot_labs(lot_id, as_headers=None, **lab_overrides):
    """Record lab values on a lot; recomputes the LAB grade. Returns the lot."""
    return get_success_data(api_client.submit_lot_lab_results(
        lot_id, lot_lab_results_payload(**lab_overrides), as_headers or TECH))


def accept_lot(lot_id, as_headers=None):
    return get_success_data(api_client.accept_lot(lot_id, as_headers or QAM))


def reject_lot(lot_id, as_headers=None):
    return get_success_data(api_client.reject_lot(lot_id, as_headers or QAM))


def create_accepted_lot(contract_id, received_weight_kg=1000.0, **lab_overrides):
    """Receive a lot, submit passing lab values, accept it. Returns ACCEPTED lot."""
    lot = receive_lot(contract_id, received_weight_kg)
    submit_lot_labs(lot["id"], **lab_overrides)
    return accept_lot(lot["id"])


# ---------------------------------------------------------------------------
# Tier 1: recipes
# ---------------------------------------------------------------------------

def create_recipe_draft(as_headers=None, **overrides):
    """Create a recipe (born DRAFT, version 1). Returns the recipe."""
    return get_success_data(
        api_client.create_recipe(create_recipe_payload(**overrides), as_headers or PM))


def approve_recipe(recipe_id, as_headers=None):
    return get_success_data(api_client.approve_recipe(recipe_id, as_headers or QAM))


def get_recipe(recipe_id):
    return get_success_data(api_client.get_recipe(recipe_id, PM))


def create_approved_recipe(**overrides):
    """Create + approve a recipe (version 2 after approval). Returns it."""
    recipe = create_recipe_draft(**overrides)
    return approve_recipe(recipe["id"])


# ---------------------------------------------------------------------------
# Tier 1: lines and dies
# ---------------------------------------------------------------------------

def create_line(line_name="L-1"):
    return get_success_data(api_client.create_production_line(create_line_payload(line_name), PM))


def get_line(line_id):
    return get_success_data(api_client.get_production_line(line_id, OP))


def start_line_cleaning(line_id):
    return get_success_data(api_client.start_line_cleaning(line_id, OP))


def complete_line_cleaning(line_id):
    return get_success_data(api_client.complete_line_cleaning(line_id, OP))


def create_gf_validated_line(line_name="L-GF"):
    """Run the full cleaning + verified PASS swab cycle. Returns GF_VALIDATED line."""
    line = create_line(line_name)
    start_line_cleaning(line["id"])
    complete_line_cleaning(line["id"])
    record_and_verify_line_swab(line["id"], "PASS")
    return get_line(line["id"])


def create_die(die_code="D-1", shape_family="LONG_CUT", rated_capacity_kg=100000.0):
    return get_success_data(api_client.create_extrusion_die(
        create_die_payload(die_code, shape_family, rated_capacity_kg), PM))


def mount_die(die_id, line_id):
    return get_success_data(api_client.mount_die(die_id, {"line_id": line_id}, OP))


def create_mounted_die(line_id, die_code="D-1", shape_family="LONG_CUT",
                       rated_capacity_kg=100000.0):
    die = create_die(die_code, shape_family, rated_capacity_kg)
    return mount_die(die["id"], line_id)


# ---------------------------------------------------------------------------
# Tier 1: gluten tests / pest inspections
# ---------------------------------------------------------------------------

def record_gluten_test(result="PASS", line_id=None, run_id=None, as_headers=None):
    test_type = "LINE_SWAB" if line_id is not None else "PRODUCT_TEST"
    payload = create_gluten_test_payload(test_type, result)
    if line_id is not None:
        payload["line_id"] = line_id
    if run_id is not None:
        payload["run_id"] = run_id
    return get_success_data(api_client.create_gluten_test(payload, as_headers or TECH))


def verify_gluten_test(test_id, as_headers=None):
    return get_success_data(api_client.verify_gluten_test(test_id, as_headers or QAM))


def record_and_verify_line_swab(line_id, result):
    swab = record_gluten_test(result=result, line_id=line_id)
    return verify_gluten_test(swab["id"])


def record_and_verify_product_test(run_id, result):
    test = record_gluten_test(result=result, run_id=run_id)
    return verify_gluten_test(test["id"])


def record_pest_inspection(zone_id, severity, notes=None, as_headers=None):
    payload = create_pest_inspection_payload(zone_id, severity)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_pest_inspection(payload, as_headers or TECH))


def verify_pest_inspection(inspection_id, as_headers=None):
    return get_success_data(api_client.verify_pest_inspection(inspection_id, as_headers or QAM))


def record_and_verify_pest_inspection(zone_id, severity, notes=None):
    insp = record_pest_inspection(zone_id, severity, notes)
    return verify_pest_inspection(insp["id"])


# ---------------------------------------------------------------------------
# Tier 1: zones / goods lots
# ---------------------------------------------------------------------------

def create_zone(zone_name="Z-1", zone_type="CONVENTIONAL", capacity_pallets=10):
    return get_success_data(api_client.create_warehouse_zone(
        create_zone_payload(zone_name, zone_type, capacity_pallets), PM))


def get_zone(zone_id):
    return get_success_data(api_client.get_warehouse_zone(zone_id, CLERK))


def put_away(goods_lot_id, zone_id):
    return get_success_data(api_client.put_away_lot(goods_lot_id, {"zone_id": zone_id}, CLERK))


def release_goods_lot(goods_lot_id):
    return get_success_data(api_client.release_goods_lot(goods_lot_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 2: run scheduling and advancement
# ---------------------------------------------------------------------------

def schedule_run(recipe_id, line_id, lot_id, planned_input_kg=500.0,
                 scheduled_start=RUN_START_ISO, scheduled_end=RUN_END_ISO):
    """Schedule a run, threading the line's current version (OCC). Returns the run."""
    line = get_line(line_id)
    return get_success_data(api_client.create_production_run(
        create_run_payload(recipe_id, line_id, lot_id, line["version"],
                           planned_input_kg=planned_input_kg,
                           scheduled_start=scheduled_start,
                           scheduled_end=scheduled_end),
        OP,
    ), 201)


def get_run(run_id):
    return get_success_data(api_client.get_production_run(run_id, OP))


def advance_run(run_id, payload=None):
    """Advance one hop; setup-lenient. Returns the updated run."""
    return get_success_data(api_client.advance_run(run_id, payload or {}, OP))


def abort_run(run_id):
    return get_success_data(api_client.abort_run(run_id, OP))


# --- child-resource lookups (list + match recorded FK, else singleton) ------

def _find_child(rows, fk_field, fk_value, what):
    matches = [r for r in rows if r.get(fk_field) == fk_value]
    if matches:
        return matches[0]
    assert len(rows) == 1, (
        f"Could not identify {what} for {fk_field}={fk_value}: "
        f"{len(rows)} rows and none carries the FK"
    )
    return rows[0]


def row_ids(rows):
    return {r["id"] for r in rows}


def capture_new_row(list_fn, before_ids, what="row"):
    """Return the single row present now but absent from before_ids.

    Deterministic regardless of whether the serializer echoes foreign keys:
    the caller controls creation order and diffs the collection."""
    after = list_fn()
    new = [r for r in after if r["id"] not in before_ids]
    assert len(new) == 1, f"expected exactly one new {what}, got {len(new)}"
    return new[0]


def list_drying_sessions():
    return get_success_data(api_client.list_drying_sessions(OP, params={"limit": 100}))


def drying_session_for_run(run_id):
    return _find_child(list_drying_sessions(), "run_id", run_id, "drying session")


def list_packaging_jobs():
    return get_success_data(api_client.list_packaging_jobs(OP, params={"limit": 100}))


def packaging_job_for_run(run_id):
    return _find_child(list_packaging_jobs(), "run_id", run_id, "packaging job")


def list_goods_lots():
    return get_success_data(api_client.list_finished_goods_lots(CLERK, params={"limit": 100}))


def goods_lot_for_run(run_id):
    return _find_child(list_goods_lots(), "run_id", run_id, "finished goods lot")


def get_goods_lot(lot_id):
    return get_success_data(api_client.get_finished_goods_lot(lot_id, CLERK))


def get_lot(lot_id):
    return get_success_data(api_client.get_semolina_lot(lot_id, PROC))


def get_die(die_id):
    return get_success_data(api_client.get_extrusion_die(die_id, OP))


def get_packaging_job(job_id):
    return get_success_data(api_client.get_packaging_job(job_id, OP))


def get_drying_session(session_id):
    return get_success_data(api_client.get_drying_session(session_id, OP))


# ---------------------------------------------------------------------------
# Tier 3: run lifecycle drivers
# ---------------------------------------------------------------------------

def drive_run_to_drying(run, initial_moisture_pct=28.0, mix_clock=RUN_START_ISO):
    """clock -> mix_clock; advance SCHEDULED->MIXING->EXTRUDING->DRYING.
    Returns the created DryingSession (captured by collection diff)."""
    before = row_ids(list_drying_sessions())
    set_clock(mix_clock)
    advance_run(run["id"])
    advance_run(run["id"])
    advance_run(run["id"], {"initial_moisture_pct": initial_moisture_pct})
    return capture_new_row(list_drying_sessions, before, "drying session")


def finish_and_confirm_session(session_id, finish_clock=STANDARD_FINISH_CLOCK,
                               lab_moisture_pct=12.0):
    """clock -> finish_clock; finish; lab result at/below target. Returns CONFIRMED session."""
    set_clock(finish_clock)
    get_success_data(api_client.finish_drying_session(session_id, OP))
    return get_success_data(api_client.submit_drying_lab_results(
        session_id, {"lab_moisture_pct": lab_moisture_pct}, TECH))


def drive_run_to_packaging(run, actual_yield_kg=400.0, initial_moisture_pct=28.0,
                           finish_clock=STANDARD_FINISH_CLOCK, lab_moisture_pct=12.0,
                           mix_clock=RUN_START_ISO):
    """Drive a SCHEDULED run through a CONFIRMED drying session into PACKAGING.
    Returns the created PackagingJob (status CREATED), captured by diff."""
    before = row_ids(list_packaging_jobs())
    session = drive_run_to_drying(run, initial_moisture_pct, mix_clock)
    finish_and_confirm_session(session["id"], finish_clock, lab_moisture_pct)
    advance_run(run["id"], {"actual_yield_kg": actual_yield_kg})
    return capture_new_row(list_packaging_jobs, before, "packaging job")


def complete_packaging(job_id, private_label=False):
    """Complete a packaging job (verifying labels first for private label).
    Returns the COMPLETED job."""
    if private_label:
        get_success_data(api_client.verify_labels(job_id, QAM))
    return get_success_data(api_client.complete_packaging_job(job_id, OP))


def drive_run_to_completed(run, actual_yield_kg=400.0, private_label=False, **drive_kw):
    """Drive a SCHEDULED run to COMPLETED. Returns the created FinishedGoodsLot
    (status CREATED, no zone yet), captured by collection diff."""
    before = row_ids(list_goods_lots())
    job = drive_run_to_packaging(run, actual_yield_kg, **drive_kw)
    complete_packaging(job["id"], private_label=private_label)
    advance_run(run["id"])
    return capture_new_row(list_goods_lots, before, "finished goods lot")


# ---------------------------------------------------------------------------
# Tier 4: composite worlds
# ---------------------------------------------------------------------------

def setup_run_world(contract_code="C-1", contract_overrides=None, readings=(),
                    lot_weight_kg=1000.0, lab_overrides=None,
                    recipe_overrides=None, line_name="L-1",
                    gf_validated_line=False, with_die=True, die_code="D-1",
                    die_rated_kg=100000.0, die_shape_family=None):
    """ACTIVE contract + ACCEPTED lot + APPROVED recipe + line (+ mounted die).

    Returns dict(contract, lot, recipe, line, die). The die shape defaults to
    the recipe's shape_family so the EXTRUDING hop is unblocked.
    """
    contract = create_contract_draft(contract_code=contract_code,
                                     **(contract_overrides or {}))
    for effective_date, index_value in readings:
        add_index_reading(contract["id"], effective_date, index_value)
    contract = get_success_data(api_client.activate_contract(contract["id"], PM))
    lot = create_accepted_lot(contract["id"], lot_weight_kg, **(lab_overrides or {}))
    recipe = create_approved_recipe(**(recipe_overrides or {}))
    if gf_validated_line:
        line = create_gf_validated_line(line_name)
    else:
        line = create_line(line_name)
    die = None
    if with_die:
        die = create_mounted_die(
            line["id"], die_code=die_code,
            shape_family=die_shape_family or recipe["shape_family"],
            rated_capacity_kg=die_rated_kg,
        )
    return {"contract": contract, "lot": lot, "recipe": recipe,
            "line": line, "die": die}


def setup_scheduled_run(planned_input_kg=500.0, scheduled_start=RUN_START_ISO,
                        scheduled_end=RUN_END_ISO, **world_kw):
    """World + one SCHEDULED run. Returns dict with the world plus 'run'."""
    world = setup_run_world(**world_kw)
    run = schedule_run(world["recipe"]["id"], world["line"]["id"],
                       world["lot"]["id"], planned_input_kg,
                       scheduled_start, scheduled_end)
    return {**world, "run": run}


def setup_run_in_drying(initial_moisture_pct=28.0, mix_clock=RUN_START_ISO, **kw):
    """World + run advanced into DRYING. Returns dict plus 'session' and the
    refreshed 'run'."""
    sc = setup_scheduled_run(**kw)
    session = drive_run_to_drying(sc["run"], initial_moisture_pct, mix_clock)
    return {**sc, "session": session, "run": get_run(sc["run"]["id"])}


def setup_run_in_packaging(actual_yield_kg=400.0, finish_clock=STANDARD_FINISH_CLOCK,
                           lab_moisture_pct=12.0, **kw):
    """World + run in PACKAGING with a CREATED PackagingJob ('job').

    The run is already in DRYING after setup_run_in_drying, so this finishes
    and confirms THAT session, then hops DRYING -> PACKAGING. (It must not
    re-drive the run from SCHEDULED via drive_run_to_packaging.)"""
    sc = setup_run_in_drying(**kw)
    before = row_ids(list_packaging_jobs())
    finish_and_confirm_session(sc["session"]["id"], finish_clock, lab_moisture_pct)
    advance_run(sc["run"]["id"], {"actual_yield_kg": actual_yield_kg})
    job = capture_new_row(list_packaging_jobs, before, "packaging job")
    return {**sc, "job": job, "run": get_run(sc["run"]["id"])}


def setup_completed_run_with_goods_lot(actual_yield_kg=400.0, private_label=False, **kw):
    """World + COMPLETED run + CREATED FinishedGoodsLot ('goods_lot')."""
    recipe_overrides = dict(kw.pop("recipe_overrides", {}) or {})
    if private_label:
        recipe_overrides.setdefault("brand_type", "PRIVATE_LABEL")
        recipe_overrides.setdefault("customer_name", "Acme Retail")
        recipe_overrides.setdefault("min_remaining_shelf_life_pct", 0.5)
    sc = setup_run_in_packaging(actual_yield_kg=actual_yield_kg,
                                recipe_overrides=recipe_overrides, **kw)
    before = row_ids(list_goods_lots())
    complete_packaging(sc["job"]["id"], private_label=private_label)
    advance_run(sc["run"]["id"])
    goods = capture_new_row(list_goods_lots, before, "finished goods lot")
    return {**sc, "goods_lot": goods, "run": get_run(sc["run"]["id"])}


def setup_stored_goods_lot(zone_name="Z-1", zone_type=None, capacity_pallets=10,
                           quality_release=False, **kw):
    """COMPLETED run + goods lot put away into a fresh zone (STORED).

    zone_type defaults to GLUTEN_FREE for gluten-free runs, else CONVENTIONAL.
    When quality_release=True the run's disposition is moved to RELEASED first
    (recording + verifying a PASS product test when the run is gluten-free).
    """
    sc = setup_completed_run_with_goods_lot(**kw)
    run = sc["run"]
    if quality_release:
        if run["gluten_free"]:
            record_and_verify_product_test(run["id"], "PASS")
        get_success_data(api_client.quality_release_run(run["id"], QAM))
        run = get_run(run["id"])
    z_type = zone_type or ("GLUTEN_FREE" if run["gluten_free"] else "CONVENTIONAL")
    zone = create_zone(zone_name, z_type, capacity_pallets)
    stored = put_away(sc["goods_lot"]["id"], zone["id"])
    return {**sc, "run": run, "zone": zone, "goods_lot": stored}
