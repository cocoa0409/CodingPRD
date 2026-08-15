"""Composite setup helpers (PRD §3 workflows).

Every test runs against a freshly restarted server with an empty database, so
each helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator so a setup
failure surfaces as a clear "Setup failed" error rather than an assertion
failure inside the rule under test.

Composite preambles:
  setup_kitted_batch            — approved recipe + order + batch in KITTED
  setup_cooked_batch            — ... batch in COOKED
  setup_frozen_batch            — ... + cell + VERIFIED cycle, batch FROZEN
  setup_qa_pending_lot          — ... + line + film + COMPLETED run, lot QA_PENDING
  setup_releasable_lot          — ... + both CCP types PASS + batch COMPLETED
  setup_released_lot            — ... + lot RELEASED
  setup_stored_released_lot     — ... + slot + put-away
  setup_contagion_scenario      — two released lots of one recipe with shipped
                                  volume and two VALID complaints on lot 1
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import CLOCK_START
from .factories import (
    DEFAULTS,
    ccp_check_payload,
    complete_cycle_payload,
    complete_run_payload,
    cook_batch_payload,
    create_batch_payload,
    create_component_payload,
    create_complaint_payload,
    create_copack_customer_payload,
    create_cycle_payload,
    create_film_lot_payload,
    create_freezer_cell_payload,
    create_line_run_payload,
    create_order_payload,
    create_packaging_line_payload,
    create_recipe_payload,
    create_storage_slot_payload,
    put_away_payload,
    withdraw_payload,
)
from .test_users import (
    TEST_USERS,
    make_qa_manager_headers,
    make_qa_technician_headers,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
QA_TECH = TEST_USERS["qa_technician_headers"]
QA_MGR = TEST_USERS["qa_manager_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


def _setup_failed(step: str, resp):
    raise AssertionError(
        f"Setup failed at step '{step}': HTTP {resp.status_code}: {resp.text}"
    )


def _ok(resp, step: str):
    data = get_success_data(resp)
    if not isinstance(data, dict) or resp.status_code >= 300:
        _setup_failed(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def pin_clock(to_iso8601: str = CLOCK_START):
    """Pin the logical clock (PRD §2.6). Startup default is already CLOCK_START;
    call explicitly when a test needs a later instant."""
    resp = _api.set_clock({"to_iso8601": to_iso8601}, PM)
    return _ok(resp, "set_clock")


def create_recipe(**overrides):
    resp = _api.create_recipe(create_recipe_payload(**overrides), PM)
    return _ok(resp, "create_recipe")


def add_component(recipe_id, **overrides):
    resp = _api.add_component(recipe_id, create_component_payload(**overrides), PM)
    return _ok(resp, "add_component")


def create_approved_recipe(**overrides):
    """Recipe + one default component + approve. Returns the APPROVED recipe."""
    recipe = create_recipe(**overrides)
    add_component(recipe["id"])
    resp = _api.approve_recipe(recipe["id"], PM)
    return _ok(resp, "approve_recipe")


def create_copack_customer(**overrides):
    resp = _api.create_copack_customer(create_copack_customer_payload(**overrides), PM)
    return _ok(resp, "create_copack_customer")


def create_order(recipe_id, **overrides):
    resp = _api.create_production_order(create_order_payload(recipe_id, **overrides), PLANNER)
    return _ok(resp, "create_production_order")


def get_order(order_id):
    return _ok(_api.get_production_order(order_id, PLANNER), "get_production_order")


def create_batch(order_id, units_planned=DEFAULTS["BATCH_UNITS"]):
    """Create a batch under an order, reading the order's current version first
    (optimistic-concurrency guard, PRD §2.8)."""
    order = get_order(order_id)
    payload = create_batch_payload(order["version"], units_planned=units_planned)
    resp = _api.create_batch(order_id, payload, PLANNER)
    return _ok(resp, "create_batch")


def get_batch(batch_id):
    return _ok(_api.get_batch(batch_id, PLANNER), "get_batch")


def kit_batch(batch_id):
    return _ok(_api.kit_batch(batch_id, OPERATOR), "kit_batch")


def cook_batch(batch_id, cooked_mass_kg=DEFAULTS["COOKED_MASS_KG"]):
    resp = _api.cook_batch(batch_id, cook_batch_payload(cooked_mass_kg=cooked_mass_kg), OPERATOR)
    return _ok(resp, "cook_batch")


def complete_batch(batch_id):
    return _ok(_api.complete_batch(batch_id, OPERATOR), "complete_batch")


def create_freezer_cell(**overrides):
    resp = _api.create_freezer_cell(create_freezer_cell_payload(**overrides), PM)
    return _ok(resp, "create_freezer_cell")


def create_packaging_line(**overrides):
    resp = _api.create_packaging_line(create_packaging_line_payload(**overrides), PM)
    return _ok(resp, "create_packaging_line")


def create_film_lot(**overrides):
    resp = _api.create_film_lot(create_film_lot_payload(**overrides), PM)
    return _ok(resp, "create_film_lot")


def create_storage_slot(**overrides):
    resp = _api.create_storage_slot(create_storage_slot_payload(**overrides), PM)
    return _ok(resp, "create_storage_slot")


def book_cycle(batch_id, cell_id=None, **overrides):
    """Book a freezing cycle, reading the batch's current version first (PRD §2.8)."""
    batch = get_batch(batch_id)
    payload = create_cycle_payload(batch["version"], **overrides)
    if cell_id is not None:
        payload["cell_id"] = cell_id
    resp = _api.create_freezing_cycle(batch_id, payload, PLANNER)
    return _ok(resp, "create_freezing_cycle")


def start_cycle(cycle_id):
    return _ok(_api.start_freezing_cycle(cycle_id, OPERATOR), "start_freezing_cycle")


def complete_cycle(cycle_id, **overrides):
    resp = _api.complete_freezing_cycle(cycle_id, complete_cycle_payload(**overrides), OPERATOR)
    return _ok(resp, "complete_freezing_cycle")


def start_and_verify_cycle(cycle_id, **overrides):
    start_cycle(cycle_id)
    return complete_cycle(cycle_id, **overrides)


def schedule_run(line_id, batch_id, film_lot_id, **overrides):
    payload = create_line_run_payload(batch_id, film_lot_id, **overrides)
    resp = _api.create_line_run(line_id, payload, PLANNER)
    return _ok(resp, "create_line_run")


def start_run(run_id):
    return _ok(_api.start_line_run(run_id, OPERATOR), "start_line_run")


def complete_run(run_id, **overrides):
    resp = _api.complete_line_run(run_id, complete_run_payload(**overrides), OPERATOR)
    return _ok(resp, "complete_line_run")


def get_film_lot(lot_id):
    return _ok(_api.get_film_lot(lot_id, PLANNER), "get_film_lot")


def get_lot(lot_id):
    return _ok(_api.get_lot(lot_id, QA_MGR), "get_lot")


def get_slot(slot_id):
    return _ok(_api.get_storage_slot(slot_id, WAREHOUSE), "get_storage_slot")


def get_lot_of_batch(batch_id):
    """The finished-goods lot created by the batch's completed run (PRD §3.5)."""
    resp = _api.list_lots(QA_MGR, params={"batch_id": batch_id})
    body = resp.json()
    lots = body.get("data", [])
    if not lots:
        _setup_failed("get_lot_of_batch (no lot for batch)", resp)
    return lots[0]


def record_ccp(batch_id, check_type, detected, user_id="qa-tech-1"):
    """Record a critical-control-point check as a QATechnician with a specific
    X-User-ID (the segregation-of-duties reference, PRD §2.1/§3.6)."""
    resp = _api.create_ccp_check(
        batch_id,
        ccp_check_payload(check_type=check_type, test_piece_detected=detected),
        make_qa_technician_headers(user_id),
    )
    return _ok(resp, "create_ccp_check")


def record_both_ccp_passes(batch_id, user_id="qa-tech-1"):
    record_ccp(batch_id, "METAL_DETECTOR", True, user_id)
    record_ccp(batch_id, "XRAY", True, user_id)


def release_lot(lot_id, user_id="qa-mgr-1"):
    resp = _api.release_lot(lot_id, make_qa_manager_headers(user_id))
    return _ok(resp, "release_lot")


def put_away(lot_id, slot_id, cases):
    resp = _api.put_away_lot(lot_id, put_away_payload(slot_id, cases), WAREHOUSE)
    return _ok(resp, "put_away_lot")


def withdraw(lot_id, cases, purpose="SHIPMENT"):
    resp = _api.withdraw_lot(lot_id, withdraw_payload(cases, purpose), WAREHOUSE)
    return _ok(resp, "withdraw_lot")


def file_complaint(lot_id, units_affected=1, complaint_type="FREEZER_BURN", reporter="qa-tech-9"):
    resp = _api.create_complaint(
        create_complaint_payload(lot_id, complaint_type=complaint_type, units_affected=units_affected),
        make_qa_technician_headers(reporter),
    )
    return _ok(resp, "create_complaint")


def investigate_complaint(complaint_id, user_id="qa-tech-2"):
    resp = _api.investigate_complaint(complaint_id, make_qa_technician_headers(user_id))
    return _ok(resp, "investigate_complaint")


def resolve_complaint(complaint_id, verdict="VALID", resolver="qa-mgr-9"):
    resp = _api.resolve_complaint(
        complaint_id, {"verdict": verdict}, make_qa_manager_headers(resolver)
    )
    return _ok(resp, "resolve_complaint")


def file_and_resolve_valid_complaint(lot_id, units_affected=1, complaint_type="FREEZER_BURN",
                                     reporter="qa-tech-9", resolver="qa-mgr-9"):
    """File -> investigate -> resolve VALID (resolver differs from reporter, PRD §3.8)."""
    complaint = file_complaint(lot_id, units_affected, complaint_type, reporter)
    investigate_complaint(complaint["id"])
    return resolve_complaint(complaint["id"], "VALID", resolver)


# ---------------------------------------------------------------------------
# Tier 2/3: state-progression composites
# ---------------------------------------------------------------------------

def setup_kitted_batch(recipe_over=None, order_over=None, batch_units=None):
    """APPROVED recipe + order + batch walked to KITTED."""
    recipe = create_approved_recipe(**(recipe_over or {}))
    order = create_order(recipe["id"], **(order_over or {}))
    batch = create_batch(order["id"], units_planned=batch_units or DEFAULTS["BATCH_UNITS"])
    batch = kit_batch(batch["id"])
    return {"recipe": recipe, "order": order, "batch": batch}


def setup_cooked_batch(cooked_mass_kg=DEFAULTS["COOKED_MASS_KG"], **kwargs):
    """Kitted batch + cook. Returns dict with batch in COOKED."""
    env = setup_kitted_batch(**kwargs)
    env["batch"] = cook_batch(env["batch"]["id"], cooked_mass_kg)
    return env


def setup_frozen_batch(cell_over=None, cycle_over=None, complete_over=None, **kwargs):
    """Cooked batch + freezer cell + cycle booked, started, and VERIFIED.
    Returns dict including cell and cycle; batch is FROZEN."""
    env = setup_cooked_batch(**kwargs)
    env["cell"] = create_freezer_cell(**(cell_over or {}))
    env["cycle"] = book_cycle(env["batch"]["id"], cell_id=env["cell"]["id"], **(cycle_over or {}))
    env["cycle"] = start_and_verify_cycle(env["cycle"]["id"], **(complete_over or {}))
    env["batch"] = get_batch(env["batch"]["id"])
    return env


def setup_qa_pending_lot(line_over=None, film_over=None, run_over=None,
                         complete_run_over=None, **kwargs):
    """Frozen batch + packaging line + film lot + run completed.
    Returns dict including line, film lot, run, and the QA_PENDING lot;
    batch is PACKED."""
    env = setup_frozen_batch(**kwargs)
    env["line"] = create_packaging_line(**(line_over or {}))
    env["film"] = create_film_lot(**(film_over or {}))
    run_units = (run_over or {}).get("units_planned", env["batch"]["units_planned"])
    env["run"] = schedule_run(
        env["line"]["id"], env["batch"]["id"], env["film"]["id"], **(run_over or {})
    )
    start_run(env["run"]["id"])
    packed = (complete_run_over or {}).get("units_packed", run_units)
    consumed = (complete_run_over or {}).get(
        "film_meters_consumed", env["run"]["reserved_film_m"]
    )
    env["run"] = complete_run(
        env["run"]["id"], units_packed=packed, film_meters_consumed=consumed
    )
    env["lot"] = get_lot_of_batch(env["batch"]["id"])
    env["batch"] = get_batch(env["batch"]["id"])
    return env


def setup_releasable_lot(ccp_user_id="qa-tech-1", **kwargs):
    """QA_PENDING lot whose batch is COMPLETED with both CCP types PASS.
    Ready for the release gates of PRD §3.7."""
    env = setup_qa_pending_lot(**kwargs)
    record_both_ccp_passes(env["batch"]["id"], ccp_user_id)
    env["batch"] = complete_batch(env["batch"]["id"])
    env["lot"] = get_lot(env["lot"]["id"])
    return env


def setup_released_lot(release_user_id="qa-mgr-1", **kwargs):
    """Releasable lot released by a QAManager segregated from the CCP performer."""
    env = setup_releasable_lot(**kwargs)
    env["lot"] = release_lot(env["lot"]["id"], release_user_id)
    env["order"] = get_order(env["order"]["id"])
    return env


def setup_stored_released_lot(slot_over=None, put_away_cases=None, **kwargs):
    """Released lot with cases put away into a storage slot."""
    env = setup_released_lot(**kwargs)
    env["slot"] = create_storage_slot(**(slot_over or {}))
    cases = put_away_cases if put_away_cases is not None else env["lot"]["cases_produced"]
    env["lot"] = put_away(env["lot"]["id"], env["slot"]["id"], cases)
    env["slot"] = get_slot(env["slot"]["id"])
    return env


# ---------------------------------------------------------------------------
# Tier 4/5: accumulation and terminal-state composites
# ---------------------------------------------------------------------------

def setup_released_lot_with_shipments(ship_cases, put_away_cases=None, **kwargs):
    """Released lot, put away, then partially shipped (purpose SHIPMENT)."""
    env = setup_stored_released_lot(put_away_cases=put_away_cases, **kwargs)
    env["lot"] = withdraw(env["lot"]["id"], ship_cases, "SHIPMENT")
    return env


def setup_contagion_scenario():
    """One recipe, one order, two batches fully produced and RELEASED.

    Each lot: 600 cases produced (7200 RETAIL units), 600 put away, 500 shipped,
    so 100 cases remain on hand per lot and recipe-level shipped volume is 1000.
    Two VALID-resolved complaints already sit on lot 1. Returns the environment
    for the third complaint to trigger the contagion cascade (PRD §3.8).
    """
    pin_clock()
    recipe = create_approved_recipe(name="R-Contagion")
    cell1 = create_freezer_cell(cell_code="FC-1", capacity_kg=2500)
    cell2 = create_freezer_cell(cell_code="FC-2", capacity_kg=2500)
    line1 = create_packaging_line(line_code="L-1")
    line2 = create_packaging_line(line_code="L-2")
    film = create_film_lot(rolls_received=20)
    slot = create_storage_slot(capacity_cases=2000)
    order = create_order(recipe["id"], units_planned=14400)
    # Both batches are created up front: PRD §3.2 auto-completes the order the
    # moment every batch has resolved, so creating batch 2 after batch 1
    # completes would hit ERR_ORDER_NOT_OPEN on a PRD-faithful server.
    batch1 = create_batch(order["id"], units_planned=7200)
    batch2 = create_batch(order["id"], units_planned=7200)

    def produce_batch(batch, cell, line):
        kit_batch(batch["id"])
        cook_batch(batch["id"], cooked_mass_kg=1900)
        cycle = book_cycle(batch["id"], cell_id=cell["id"], load_kg=1900)
        start_and_verify_cycle(cycle["id"])
        run = schedule_run(line["id"], batch["id"], film["id"], units_planned=7200)
        start_run(run["id"])
        complete_run(run["id"], units_packed=7200, film_meters_consumed=3205)
        lot = get_lot_of_batch(batch["id"])
        record_both_ccp_passes(batch["id"], "qa-tech-1")
        complete_batch(batch["id"])
        return lot

    lot1 = produce_batch(batch1, cell1, line1)
    lot2 = produce_batch(batch2, cell2, line2)
    put_away(lot1["id"], slot["id"], 600)
    put_away(lot2["id"], slot["id"], 600)
    release_lot(lot1["id"], "qa-mgr-1")
    release_lot(lot2["id"], "qa-mgr-1")
    withdraw(lot1["id"], 500, "SHIPMENT")
    withdraw(lot2["id"], 500, "SHIPMENT")
    file_and_resolve_valid_complaint(lot1["id"], units_affected=2)
    file_and_resolve_valid_complaint(lot1["id"], units_affected=2)
    return {
        "recipe": recipe, "order": order, "film": film, "slot": slot,
        "lot1": get_lot(lot1["id"]), "lot2": get_lot(lot2["id"]),
    }
