"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All setup calls use the lenient validator so a
failure surfaces as a clear "Setup step failed" error.

Identity threading: the Distributor role is entity-backed, so every
Distributor-role call is made with make_distributor_headers(entity["id"]).
Segregation-of-duties scenarios thread explicit operator ids through the
make_*_headers builders.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    adjudicate_claim_payload,
    advance_work_order_payload,
    consume_component_payload,
    create_build_spec_payload,
    create_core_return_payload,
    create_distributor_payload,
    create_warranty_claim_payload,
    create_work_order_payload,
    declare_operation_payload,
    grade_return_payload,
    inspect_component_payload,
    patch_distributor_payload,
    perform_operation_payload,
    record_dyno_test_payload,
    respond_grading_payload,
    salvage_component_payload,
    sell_engine_payload,
    teardown_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_distributor_headers,
    make_quality_inspector_headers,
    make_shop_technician_headers,
    make_warranty_adjuster_headers,
)

ADMIN = TEST_USERS["plant_admin_headers"]
INSPECTOR = TEST_USERS["core_inspector_headers"]
TECH = TEST_USERS["shop_technician_headers"]          # X-User-ID: tech-1
QUALITY = TEST_USERS["quality_inspector_headers"]     # X-User-ID: qi-1
ADJUSTER = TEST_USERS["warranty_adjuster_headers"]    # X-User-ID: adj-1


def _hour(h: int) -> str:
    return f"{h:02d}:00:00Z"


def station_window(slot: int = 0, offset_hours: int = 0):
    """Occupation window on 2026-08-02 for machining operations.

    Slots are spaced two hours apart so multiple engines in one test never
    collide on a shared station.
    """
    base = 8 + 2 * slot + offset_hours
    return (f"2026-08-02T{_hour(base)}", f"2026-08-02T{_hour(base + 1)}")


def dyno_window(slot: int = 0):
    """Dyno window on 2026-08-03; slots spaced two hours apart so the
    thirty-minute cooldown buffer never collides within a test."""
    base = 8 + 2 * slot
    return (f"2026-08-03T{_hour(base)}", f"2026-08-03T{_hour(base + 1)}")


# ---------------------------------------------------------------------------
# Clock, distributors, build specs
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Drive the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_distributor(**overrides):
    """Register a distributor (born ACTIVE, ledgers zeroed, version 1)."""
    return get_success_data(
        api_client.create_distributor(create_distributor_payload(**overrides),
                                      ADMIN))


def get_distributor(distributor_id):
    return get_success_data(api_client.get_distributor(distributor_id, ADMIN))


def patch_distributor(distributor_id, **fields):
    return get_success_data(api_client.patch_distributor(
        distributor_id, patch_distributor_payload(**fields), ADMIN))


def create_build_spec(**overrides):
    """Create a build spec (born DRAFT)."""
    return get_success_data(
        api_client.create_build_spec(create_build_spec_payload(**overrides),
                                     ADMIN))


def activate_build_spec(spec_id):
    return get_success_data(api_client.activate_build_spec(spec_id, ADMIN))


def create_active_spec(**overrides):
    """Create a build spec and activate it. Returns the ACTIVE spec."""
    spec = create_build_spec(**overrides)
    return activate_build_spec(spec["id"])


def get_build_spec(spec_id):
    return get_success_data(api_client.get_build_spec(spec_id, ADMIN))


# ---------------------------------------------------------------------------
# Core returns and grading
# ---------------------------------------------------------------------------

def create_received_return(distributor, spec, core_deposit_id=None):
    """Register a core return as the owning distributor (RECEIVED)."""
    payload = create_core_return_payload(distributor["id"], spec["id"],
                                         core_deposit_id=core_deposit_id)
    return get_success_data(api_client.create_core_return(
        payload, make_distributor_headers(distributor["id"])))


def grade_core_return(return_id, grade="GRADE_A", missing_components=None):
    """Grade a return as CoreInspector (RECEIVED/DISPUTED -> GRADED)."""
    return get_success_data(api_client.grade_core_return(
        return_id, grade_return_payload(grade, missing_components), INSPECTOR))


def create_graded_return(distributor, spec, grade="GRADE_A",
                         missing_components=None, core_deposit_id=None):
    """Receive + grade a core return. Returns the GRADED CoreReturn."""
    ret = create_received_return(distributor, spec, core_deposit_id=core_deposit_id)
    return grade_core_return(ret["id"], grade, missing_components)


def respond_to_grading(core_return, distributor, action):
    """Distributor responds ACCEPT or DISPUTE to its own graded return."""
    return get_success_data(api_client.respond_core_return(
        core_return["id"], respond_grading_payload(action),
        make_distributor_headers(distributor["id"])))


def get_core_return(return_id):
    return get_success_data(api_client.get_core_return(return_id, ADMIN))


# ---------------------------------------------------------------------------
# Core deposits
# ---------------------------------------------------------------------------

def list_all_deposits():
    data, _meta = validate_paginated(api_client.list_core_deposits(
        ADMIN, params={"limit": 100}))
    return data


def find_deposit_for_engine(engine_id):
    """Locate the deposit created by a sale (or replacement) of an engine.

    Matches client-side so the helper stays correct no matter which list
    filters a given build supports.
    """
    for row in list_all_deposits():
        if row.get("reman_engine_id") == engine_id:
            return row
    raise AssertionError(f"Setup failed: no deposit found for engine {engine_id}")


def get_deposit(deposit_id):
    return get_success_data(api_client.get_core_deposit(deposit_id, ADMIN))


# ---------------------------------------------------------------------------
# Work orders and the machining route
# ---------------------------------------------------------------------------

def open_work_order(core_return):
    """Open a work order from a graded, rebuildable return (QUEUED)."""
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(core_return["id"]), ADMIN))


def get_work_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, ADMIN))


def advance_work_order(work_order_id, target):
    return get_success_data(api_client.advance_work_order(
        work_order_id, advance_work_order_payload(target), TECH))


def cancel_work_order(work_order_id):
    return get_success_data(api_client.cancel_work_order(work_order_id, ADMIN))


def declare_operation(work_order_id, op_type, sequence):
    """Declare one route operation, threading the OCC version read fresh."""
    wo = get_work_order(work_order_id)
    return get_success_data(api_client.declare_operation(
        work_order_id,
        declare_operation_payload(op_type, sequence, wo["version"]),
        TECH))


def declare_route(work_order, spec):
    """Declare every operation of the spec's required_op_sequence, in order.

    Returns the list of created PENDING MachineOperations.
    """
    ops = []
    for position, op_type in enumerate(spec["required_op_sequence"], start=1):
        ops.append(declare_operation(work_order["id"], op_type, position))
    return ops


def list_operations(work_order_id):
    data, _meta = validate_paginated(api_client.list_operations(
        work_order_id, ADMIN, params={"limit": 100}))
    return data


def perform_operation(operation_id, station_code, scheduled_start,
                      scheduled_end, result="PASS"):
    return get_success_data(api_client.perform_operation(
        operation_id,
        perform_operation_payload(station_code, scheduled_start,
                                  scheduled_end, result),
        TECH))


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def salvage_component(work_order_id, part_type="CRANKSHAFT",
                      interchange_group="CRANK-SBC-3.48"):
    return get_success_data(api_client.salvage_component(
        work_order_id,
        salvage_component_payload(part_type, interchange_group),
        TECH))


def inspect_component(component_id, reuse_grade="REUSE_OK", quarantine=False):
    return get_success_data(api_client.inspect_component(
        component_id, inspect_component_payload(reuse_grade, quarantine),
        QUALITY))


def consume_component(work_order_id, component_id):
    return get_success_data(api_client.consume_component(
        work_order_id, consume_component_payload(component_id), TECH))


def get_component(component_id):
    return get_success_data(api_client.get_component(component_id, ADMIN))


# ---------------------------------------------------------------------------
# Engine production chain (core -> work order -> route -> machining ->
# assembly -> dyno test). `slot` staggers station/dyno windows so several
# engines can be produced inside one test without scheduling collisions.
# ---------------------------------------------------------------------------

def build_engine_in_dyno_test(spec, core_distributor, slot=0,
                              station_code=None, dyno_cell_code=None):
    """Drive a graded GRADE_A core through the pipeline until the engine is
    BUILT and the work order stands in DYNO_TEST.

    Returns a context dict: core_return, work_order, operations, engine.
    """
    station_code = station_code or f"STN-CRANK-S{slot}"
    core_return = create_graded_return(core_distributor, spec)
    wo = open_work_order(core_return)
    wo = advance_work_order(wo["id"], "TEARDOWN")
    ops = declare_route(wo, spec)
    wo = advance_work_order(wo["id"], "MACHINING")
    for idx, op in enumerate(ops):
        start, end = station_window(slot, offset_hours=idx)
        perform_operation(op["id"], station_code, start, end, "PASS")
    wo = advance_work_order(wo["id"], "ASSEMBLY")
    engine_id = wo["reman_engine_id"]
    wo = advance_work_order(wo["id"], "DYNO_TEST")
    engine = get_success_data(api_client.get_reman_engine(engine_id, ADMIN))
    return {
        "spec": spec,
        "core_distributor": core_distributor,
        "core_return": core_return,
        "work_order": wo,
        "operations": ops,
        "engine": engine,
        "station_code": station_code,
        "dyno_cell_code": dyno_cell_code or f"CELL-S{slot}",
    }


def record_dyno_test(engine_id, dyno_cell_code, started_at=None,
                     ended_at=None, slot=0, horsepower=None,
                     oil_pressure_psi=None, coolant_temp_f=None,
                     tech_user_id="tech-1"):
    """Record a dyno test as a ShopTechnician with an explicit operator id
    (recorded_by is stamped from X-User-ID)."""
    if started_at is None or ended_at is None:
        started_at, ended_at = dyno_window(slot)
    payload = record_dyno_test_payload(
        dyno_cell_code, started_at, ended_at,
        horsepower=horsepower, oil_pressure_psi=oil_pressure_psi,
        coolant_temp_f=coolant_temp_f)
    return get_success_data(api_client.record_dyno_test(
        engine_id, payload, make_shop_technician_headers(tech_user_id)))


def seal_engine(engine_id, qi_user_id="qi-1"):
    """Seal a DYNO_PASSED engine as a QualityInspector whose id differs from
    the dyno recorder's (segregation of duties)."""
    return get_success_data(api_client.seal_reman_engine(
        engine_id, make_quality_inspector_headers(qi_user_id)))


def get_reman_engine(engine_id):
    return get_success_data(api_client.get_reman_engine(engine_id, ADMIN))


def produce_sealed_engine(spec, core_distributor, slot=0,
                          station_code=None, dyno_cell_code=None,
                          tech_user_id="tech-1", qi_user_id="qi-1"):
    """Full production chain ending with the engine SEALED and the work
    order CLOSED. Returns the context dict with refreshed engine/work_order.
    """
    ctx = build_engine_in_dyno_test(spec, core_distributor, slot=slot,
                                    station_code=station_code,
                                    dyno_cell_code=dyno_cell_code)
    record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"], slot=slot,
                     tech_user_id=tech_user_id)
    engine = seal_engine(ctx["engine"]["id"], qi_user_id=qi_user_id)
    ctx["engine"] = engine
    ctx["work_order"] = get_work_order(ctx["work_order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Engine sale (server-side allocation) and the deposit it creates
# ---------------------------------------------------------------------------

def sell_engine_to(buyer, spec):
    """Sell the oldest-sealed engine of the spec to the buyer distributor.

    Threads the OCC guard: re-reads the buyer's version right before the
    call. Returns {engine, deposit, distributor} post-sale.
    """
    fresh = get_distributor(buyer["id"])
    engine = get_success_data(api_client.sell_reman_engine(
        sell_engine_payload(spec["id"], fresh["version"]),
        make_distributor_headers(buyer["id"])))
    return {
        "engine": engine,
        "deposit": find_deposit_for_engine(engine["id"]),
        "distributor": get_distributor(buyer["id"]),
    }


def setup_sold_engine(buyer, spec, core_distributor, slot=0):
    """Produce a sealed engine and sell it to the buyer. Returns the merged
    context: production ctx + engine (SOLD), deposit, distributor."""
    ctx = produce_sealed_engine(spec, core_distributor, slot=slot)
    sale = sell_engine_to(buyer, spec)
    ctx.update(sale)
    return ctx


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------

def file_warranty_claim(engine_id, distributor,
                        failure_description="rod knock under load"):
    """File a claim as the owning distributor."""
    return get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(engine_id, distributor["id"],
                                      failure_description),
        make_distributor_headers(distributor["id"])))


def teardown_warranty_claim(claim_id, teardown_findings="spun rod bearing",
                            tech_user_id="tech-9"):
    """Teardown an OPEN claim as a ShopTechnician with explicit operator id
    (teardown_by is stamped from X-User-ID)."""
    return get_success_data(api_client.teardown_warranty_claim(
        claim_id, teardown_claim_payload(teardown_findings),
        make_shop_technician_headers(tech_user_id)))


def adjudicate_warranty_claim(claim_id, outcome, teardown_fee_cents=0,
                              adjuster_user_id="adj-1"):
    """Adjudicate a torn-down claim as a WarrantyAdjuster with explicit
    operator id (must differ from teardown_by)."""
    return get_success_data(api_client.adjudicate_warranty_claim(
        claim_id, adjudicate_claim_payload(outcome, teardown_fee_cents),
        make_warranty_adjuster_headers(adjuster_user_id)))


def get_warranty_claim(claim_id):
    return get_success_data(api_client.get_warranty_claim(claim_id, ADMIN))


def setup_torn_down_claim(buyer, spec, core_distributor, slot=0,
                          failure_description="rod knock under load",
                          tech_user_id="tech-9"):
    """Sold engine + OPEN claim + teardown. Returns ctx with claim."""
    ctx = setup_sold_engine(buyer, spec, core_distributor, slot=slot)
    claim = file_warranty_claim(ctx["engine"]["id"], buyer,
                                failure_description)
    claim = teardown_warranty_claim(claim["id"], tech_user_id=tech_user_id)
    ctx["claim"] = claim
    return ctx


# ---------------------------------------------------------------------------
# Aging sweep
# ---------------------------------------------------------------------------

def run_aging_sweep():
    return get_success_data(api_client.run_aging(ADMIN))
