"""Composite setup helpers for the MES API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Fixtures use get_success_data() (lenient 2xx validator) so setup failures
surface as clear "Setup step failed" errors rather than confusing assertions.

All roles use opaque identities (PRD §2.1), so calls use the shared role-header
constants from TEST_USERS.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["machine_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


def _u(prefix=""):
    """Short unique suffix so SKUs / codes never collide within a test."""
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


# ─── Tier: primitive entity creators ──────────────────

def create_product(sku=None, name="Prod", product_type="FINISHED_GOOD",
                   unit_cost_cents=None, lot_controlled=None, headers=ENG):
    payload = {"sku": sku or _u("SKU"), "name": name, "product_type": product_type}
    if unit_cost_cents is not None:
        payload["unit_cost_cents"] = unit_cost_cents
    if lot_controlled is not None:
        payload["lot_controlled"] = lot_controlled
    return get_success_data(api_client.create_product(payload, headers))


def create_machine(machine_code=None, work_center="WC1",
                   planned_production_secs=28800, headers=ENG):
    payload = {
        "machine_code": machine_code or _u("M-"),
        "work_center": work_center,
        "planned_production_secs": planned_production_secs,
    }
    return get_success_data(api_client.create_machine(payload, headers))


def create_bom_line(parent_product_id, component_product_id, quantity_per=1,
                    scrap_factor_pct=None, headers=ENG):
    payload = {
        "parent_product_id": parent_product_id,
        "component_product_id": component_product_id,
        "quantity_per": quantity_per,
    }
    if scrap_factor_pct is not None:
        payload["scrap_factor_pct"] = scrap_factor_pct
    return get_success_data(api_client.create_bom_line(payload, headers))


def create_lot(product_id, lot_code=None, received_qty=5, headers=OPERATOR):
    payload = {
        "product_id": product_id,
        "lot_code": lot_code or _u("L-"),
        "received_qty": received_qty,
    }
    return get_success_data(api_client.create_lot(payload, headers))


# ─── Tier 1: routing state progression ────────────────

def create_draft_routing_with_ops(product_id, machine_id, ops, routing_code=None,
                                  headers=ENG):
    """Create a DRAFT routing and attach the given operations.

    `ops` is a list of dicts each with sequence_no, ideal_cycle_time_secs, and
    optional setup_buffer_secs. Returns (routing, [operation, ...]).
    """
    routing = get_success_data(api_client.create_routing(
        {"product_id": product_id, "routing_code": routing_code or _u("RT-")}, headers))
    operations = []
    for op in ops:
        payload = {
            "machine_id": machine_id,
            "sequence_no": op["sequence_no"],
            "ideal_cycle_time_secs": op["ideal_cycle_time_secs"],
        }
        if "setup_buffer_secs" in op:
            payload["setup_buffer_secs"] = op["setup_buffer_secs"]
        operations.append(get_success_data(
            api_client.create_operation(routing["id"], payload, headers)))
    return routing, operations


def create_released_routing(product_id, machine_id, ops=None, routing_code=None,
                            headers=ENG):
    """Create a routing, attach ops, and release it. Returns (routing, [operation]).

    Defaults to a single seq-10 op with ideal_cycle_time_secs=100.
    """
    if ops is None:
        ops = [{"sequence_no": 10, "ideal_cycle_time_secs": 100}]
    routing, operations = create_draft_routing_with_ops(
        product_id, machine_id, ops, routing_code, headers)
    routing = get_success_data(api_client.release_routing(routing["id"], headers))
    return routing, operations


# ─── Tier 2: entity hierarchy (product + machine + released routing) ──

def setup_released_routing_for_fg(ops=None, unit_cost_cents=None):
    """Finished-good product + machine + released routing.

    Returns dict {fg, machine, routing, operations}.
    """
    fg = create_product(product_type="FINISHED_GOOD", unit_cost_cents=unit_cost_cents)
    machine = create_machine()
    routing, operations = create_released_routing(fg["id"], machine["id"], ops=ops)
    return {"fg": fg, "machine": machine, "routing": routing, "operations": operations}


# ─── Tier 3: work-order lifecycle shortcuts ───────────

def create_planned_work_order(product_id, routing_id, order_qty=1, headers=PLANNER):
    """Create a PLANNED work order. Returns the work order dict."""
    return get_success_data(api_client.create_work_order(
        {"product_id": product_id, "routing_id": routing_id, "order_qty": order_qty},
        headers))


def setup_released_work_order(order_qty=1, ops=None, unit_cost_cents=None):
    """FG + machine + released routing + PLANNED WO + release.

    Returns dict {fg, machine, routing, operations, work_order, woops}
    where woops is the list of WorkOrderOperation rows ordered by sequence_no.
    """
    base = setup_released_routing_for_fg(ops=ops, unit_cost_cents=unit_cost_cents)
    wo = create_planned_work_order(base["fg"]["id"], base["routing"]["id"], order_qty)
    wo = get_success_data(api_client.release_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
    woops = get_success_data(api_client.list_work_order_operations(wo["id"], PLANNER))
    base["work_order"] = wo
    base["woops"] = woops
    return base


def setup_planned_work_order_released_routing(order_qty=1):
    """FG + machine + RELEASED routing + a PLANNED (not yet released) WO.

    Returns dict {fg, machine, routing, operations, work_order}.
    """
    base = setup_released_routing_for_fg()
    wo = create_planned_work_order(base["fg"]["id"], base["routing"]["id"], order_qty)
    base["work_order"] = wo
    return base


# ─── Tier: WIP node progression ───────────────────────

def sign_off_operation(woop_id, result="PASS", headers=INSPECTOR):
    """Append a traveler sign-off to a WIP node."""
    return get_success_data(api_client.create_signoff(woop_id, {"result": result}, headers))


def start_operation(woop_id, units_in=None, scheduled_start=None, scheduled_end=None,
                    headers=OPERATOR):
    payload = {}
    if units_in is not None:
        payload["units_in"] = units_in
    if scheduled_start is not None:
        payload["scheduled_start"] = scheduled_start
    if scheduled_end is not None:
        payload["scheduled_end"] = scheduled_end
    return get_success_data(api_client.start_operation(woop_id, payload, headers))


def complete_operation(woop_id, good_qty, headers=OPERATOR):
    return get_success_data(api_client.complete_operation(woop_id, {"good_qty": good_qty}, headers))


def signoff_start_complete_op(woop_id, units_in, good_qty):
    """Full single-op execution: PASS sign-off -> start -> complete. Returns the node."""
    sign_off_operation(woop_id, "PASS")
    start_operation(woop_id, units_in=units_in)
    return complete_operation(woop_id, good_qty)


def setup_started_single_op_wo(order_qty=10, units_in=None, unit_cost_cents=None):
    """Released single-op WO with its op started (IN_PROGRESS).

    Returns dict {fg, machine, routing, operations, work_order, woops, woop}
    with woop = the single started WIP node. started_qty bubbles to order_qty.
    """
    base = setup_released_work_order(order_qty=order_qty, unit_cost_cents=unit_cost_cents)
    woop = base["woops"][0]
    if units_in is None:
        units_in = order_qty
    woop = start_operation(woop["id"], units_in=units_in)
    base["woop"] = woop
    return base


def setup_completed_single_op_wo(order_qty=1, unit_cost_cents=None):
    """Released single-op WO walked through to WO COMPLETED (no BOM).

    Sign PASS -> start -> complete op -> complete work order.
    Returns dict {..., work_order (COMPLETED), woop (COMPLETED)}.
    """
    base = setup_released_work_order(order_qty=order_qty, unit_cost_cents=unit_cost_cents)
    woop = base["woops"][0]
    signoff_start_complete_op(woop["id"], units_in=order_qty, good_qty=order_qty)
    wo = get_success_data(api_client.complete_work_order(base["work_order"]["id"], PLANNER))
    base["work_order"] = wo
    base["woop"] = get_success_data(api_client.get_work_order_operation(woop["id"], PLANNER))
    return base


# ─── Tier: scrap disposition setup ────────────────────

def raise_scrap_disposition(woop_id, quantity, defect_code="DEF", headers=OPERATOR):
    """Raise a PENDING scrap disposition at a started op. Returns the disposition."""
    return get_success_data(api_client.create_scrap_disposition(
        woop_id, {"quantity": quantity, "defect_code": defect_code}, headers))


def setup_pending_scrap_on_started_op(order_qty=10, scrap_qty=3, unit_cost_cents=500):
    """Released single-op WO, op started, with a PENDING scrap disposition raised.

    Returns dict {..., woop (IN_PROGRESS), disposition (PENDING)}.
    """
    base = setup_started_single_op_wo(order_qty=order_qty, units_in=order_qty,
                                      unit_cost_cents=unit_cost_cents)
    disp = raise_scrap_disposition(base["woop"]["id"], scrap_qty)
    base["disposition"] = disp
    return base


def setup_completed_op_then_pending_scrap(order_qty=5, scrap_qty=2, unit_cost_cents=700):
    """Single-op WO with the op signed PASS, started, completed (final op ->
    completed_qty=order_qty), then a PENDING scrap disposition raised at the op.

    Returns dict {..., woop (COMPLETED), disposition (PENDING)}.
    """
    base = setup_released_work_order(order_qty=order_qty, unit_cost_cents=unit_cost_cents)
    woop = base["woops"][0]
    signoff_start_complete_op(woop["id"], units_in=order_qty, good_qty=order_qty)
    woop = get_success_data(api_client.get_work_order_operation(woop["id"], PLANNER))
    disp = raise_scrap_disposition(woop["id"], scrap_qty, headers=INSPECTOR)
    base["woop"] = woop
    base["disposition"] = disp
    return base


# ─── Tier 4: OEE machine setup ────────────────────────

def setup_machine_with_run_logs(planned_production_secs=28800, run_logs=None,
                                primary_ideal_cycle_time_secs=None):
    """Machine + optional primary op (for performance basis) + run logs.

    `run_logs` is a list of dicts each with window_start, window_end,
    run_time_secs, total_units, good_units. If primary_ideal_cycle_time_secs is
    given, an FG product + DRAFT routing + one seq-10 op on the machine is created
    and the routing released so OEE performance has a primary operation.
    Returns dict {machine, fg?, routing?, operations?, run_logs}.
    """
    machine = create_machine(planned_production_secs=planned_production_secs)
    out = {"machine": machine}
    if primary_ideal_cycle_time_secs is not None:
        fg = create_product(product_type="FINISHED_GOOD")
        routing, operations = create_released_routing(
            fg["id"], machine["id"],
            ops=[{"sequence_no": 10, "ideal_cycle_time_secs": primary_ideal_cycle_time_secs}])
        out["fg"] = fg
        out["routing"] = routing
        out["operations"] = operations
    created_logs = []
    for log in (run_logs or []):
        created_logs.append(get_success_data(
            api_client.create_run_log(machine["id"], log, OPERATOR)))
    out["run_logs"] = created_logs
    return out


# ─── Tier: material-variance scenario (multi-level BOM + lot issues) ──

def setup_material_variance_scenario():
    """Build the dual-variant material-variance scenario.

    Products: FG (finished), SA (subassembly, unit_cost 0), R1 (raw 82c,
    lot_controlled), R2 (raw 88c, lot_controlled).
    BOM: FG->SA q1 s20, FG->R1 q1 s20, SA->R2 q1 s20.
    RELEASED routing for FG with one op; WO order_qty=1 released so demands
    explode; lots L1 of R1 (recv 5) and L2 of R2 (recv 5); issue R1=2, R2=2 to
    the demands through the single WIP op; op signed PASS, started, completed.
    The work order is left IN_PROCESS (NOT yet completed) so the caller can
    trigger completion and observe material_variance_cents.

    Returns dict with fg, sa, r1, r2, work_order, woop, demands{r1,r2}, lots{l1,l2}.
    """
    fg = create_product(sku=_u("FG"), name="FG", product_type="FINISHED_GOOD")
    sa = create_product(sku=_u("SA"), name="SA", product_type="SUBASSEMBLY", unit_cost_cents=0)
    r1 = create_product(sku=_u("R1"), name="R1", product_type="RAW_MATERIAL",
                        unit_cost_cents=82, lot_controlled=True)
    r2 = create_product(sku=_u("R2"), name="R2", product_type="RAW_MATERIAL",
                        unit_cost_cents=88, lot_controlled=True)
    create_bom_line(fg["id"], sa["id"], quantity_per=1, scrap_factor_pct=20)
    create_bom_line(fg["id"], r1["id"], quantity_per=1, scrap_factor_pct=20)
    create_bom_line(sa["id"], r2["id"], quantity_per=1, scrap_factor_pct=20)
    machine = create_machine()
    routing, operations = create_released_routing(fg["id"], machine["id"])
    wo = create_planned_work_order(fg["id"], routing["id"], order_qty=1)
    wo = get_success_data(api_client.release_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
    cd_r1 = get_success_data(api_client.list_component_demands(
        PLANNER, params={"work_order_id": wo["id"], "component_product_id": r1["id"]}))[0]
    cd_r2 = get_success_data(api_client.list_component_demands(
        PLANNER, params={"work_order_id": wo["id"], "component_product_id": r2["id"]}))[0]
    woop = get_success_data(api_client.list_work_order_operations(wo["id"], PLANNER))[0]
    l1 = create_lot(r1["id"], received_qty=5)
    l2 = create_lot(r2["id"], received_qty=5)
    get_success_data(api_client.create_lot_issue(
        {"component_demand_id": cd_r1["id"], "lot_id": l1["id"],
         "work_order_operation_id": woop["id"], "issued_qty": 2}, OPERATOR))
    get_success_data(api_client.create_lot_issue(
        {"component_demand_id": cd_r2["id"], "lot_id": l2["id"],
         "work_order_operation_id": woop["id"], "issued_qty": 2}, OPERATOR))
    signoff_start_complete_op(woop["id"], units_in=1, good_qty=1)
    return {
        "fg": fg, "sa": sa, "r1": r1, "r2": r2,
        "machine": machine, "routing": routing,
        "work_order": wo, "woop": woop,
        "demands": {"r1": cd_r1, "r2": cd_r2},
        "lots": {"l1": l1, "l2": l2},
    }


# ─── Tier: BOM standard-cost scenario (no execution) ──

def setup_bom_standard_cost_scenario():
    """FG/SA/R1(82c)/R2(88c); BOM FG->SA q1 s20, FG->R1 q1 s20, SA->R2 q1 s20;
    RELEASED routing; WO order_qty=1 created PLANNED (NOT yet released).

    Returns dict {fg, sa, r1, r2, machine, routing, work_order}. The caller
    releases to trigger the explosion and reads the cost summary.
    """
    fg = create_product(sku=_u("FG"), name="FG", product_type="FINISHED_GOOD")
    sa = create_product(sku=_u("SA"), name="SA", product_type="SUBASSEMBLY", unit_cost_cents=0)
    r1 = create_product(sku=_u("R1"), name="R1", product_type="RAW_MATERIAL",
                        unit_cost_cents=82, lot_controlled=True)
    r2 = create_product(sku=_u("R2"), name="R2", product_type="RAW_MATERIAL",
                        unit_cost_cents=88, lot_controlled=True)
    create_bom_line(fg["id"], sa["id"], quantity_per=1, scrap_factor_pct=20)
    create_bom_line(fg["id"], r1["id"], quantity_per=1, scrap_factor_pct=20)
    create_bom_line(sa["id"], r2["id"], quantity_per=1, scrap_factor_pct=20)
    machine = create_machine()
    routing, operations = create_released_routing(fg["id"], machine["id"])
    wo = create_planned_work_order(fg["id"], routing["id"], order_qty=1)
    return {"fg": fg, "sa": sa, "r1": r1, "r2": r2,
            "machine": machine, "routing": routing, "work_order": wo}


# ─── Tier: lot-issue scenario (single raw, released WO) ──

def setup_released_wo_with_demand_and_lot(quantity_per=2, scrap_factor_pct=0,
                                          raw_unit_cost=100, received_qty=5,
                                          order_qty=1, raw_lot_controlled=True):
    """FG + one lot-controlled raw R1 (BOM FG->R1) + RELEASED routing + released
    WO so a ComponentDemand for R1 exists; one lot of R1 received; one WIP op.

    Returns dict {fg, r1, machine, routing, work_order, woop, demand, lot}.
    The lot is NOT yet issued — the caller drives the issue under test.
    """
    fg = create_product(sku=_u("FG"), name="FG", product_type="FINISHED_GOOD")
    r1 = create_product(sku=_u("R1"), name="R1", product_type="RAW_MATERIAL",
                        unit_cost_cents=raw_unit_cost, lot_controlled=raw_lot_controlled)
    create_bom_line(fg["id"], r1["id"], quantity_per=quantity_per,
                    scrap_factor_pct=scrap_factor_pct)
    machine = create_machine()
    routing, operations = create_released_routing(fg["id"], machine["id"])
    wo = create_planned_work_order(fg["id"], routing["id"], order_qty=order_qty)
    wo = get_success_data(api_client.release_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
    demand = get_success_data(api_client.list_component_demands(
        PLANNER, params={"work_order_id": wo["id"], "component_product_id": r1["id"]}))[0]
    woop = get_success_data(api_client.list_work_order_operations(wo["id"], PLANNER))[0]
    lot = create_lot(r1["id"], received_qty=received_qty)
    return {"fg": fg, "r1": r1, "machine": machine, "routing": routing,
            "work_order": wo, "woop": woop, "demand": demand, "lot": lot}
