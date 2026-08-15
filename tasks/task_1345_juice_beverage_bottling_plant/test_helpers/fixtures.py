"""Composite setup helpers for the bottling plant test suite.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface as clear
"Setup failed" assertion errors. The canonical happy path is:

  customer (ACTIVE) -> formula (label APPROVED) -> tank + batch blended ->
  QA PASS -> process run VALIDATED -> batch RELEASED -> line + QC_PASSED
  container lot + zone -> run QUOTED -> CONFIRMED -> SCHEDULED -> (clock)
  IN_PRODUCTION -> COMPLETED (+ finished-good lot) -> order -> allocate ->
  pick -> ship.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_product_developer_headers,
    make_label_reviewer_headers,
    make_blend_operator_headers,
    make_qa_inspector_headers,
)

PM = TEST_USERS["plant_manager_headers"]
FIN = TEST_USERS["finance_clerk_headers"]
DEV = TEST_USERS["product_developer_headers"]
REV = TEST_USERS["label_reviewer_headers"]
OP = TEST_USERS["blend_operator_headers"]
QA = TEST_USERS["qa_inspector_headers"]
PLAN = TEST_USERS["production_planner_headers"]
WH = TEST_USERS["warehouse_lead_headers"]
CSR = TEST_USERS["customer_service_rep_headers"]

# Canonical line window used by most production-run scenarios
WINDOW_START = "2026-08-11T08:00:00Z"
WINDOW_END = "2026-08-11T12:00:00Z"
CLOCK_IN_WINDOW = "2026-08-11T09:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ---------------------------------------------------------------------------

def create_customer(name=None, credit_limit_cents=1_000_000, minimum_run_units=500,
                    pallet_deposit_cents=1500, approve=True) -> dict:
    """Create a customer; approve credit by default so it is ACTIVE."""
    overrides = {}
    if name is not None:
        overrides["name"] = name
    customer = get_success_data(api_client.create_customer(
        factories.create_customer_payload(
            credit_limit_cents=credit_limit_cents,
            minimum_run_units=minimum_run_units,
            pallet_deposit_cents=pallet_deposit_cents,
            **overrides,
        ), PM))
    if approve:
        customer = get_success_data(api_client.approve_credit(customer["id"], FIN))
    return customer


def submit_label(formula_id: str, developer_headers=None) -> dict:
    """Submit the formula for label review at its current version. Returns the new review."""
    developer_headers = developer_headers or DEV
    formula = get_success_data(api_client.get_formula(formula_id, PM))
    return get_success_data(api_client.submit_label_review(
        formula_id, {"expected_formula_version": formula["version"]}, developer_headers))


def create_formula(customer_id: str, approve=True, developer_headers=None,
                   reviewer_headers=None, **overrides) -> dict:
    """Create a formula; optionally drive DRAFT -> LABEL_REVIEW -> APPROVED.

    Returns the freshly-read formula (current version included).
    """
    developer_headers = developer_headers or DEV
    reviewer_headers = reviewer_headers or REV
    formula = get_success_data(api_client.create_formula(
        factories.create_formula_payload(customer_id, **overrides), developer_headers))
    if approve:
        review = submit_label(formula["id"], developer_headers)
        get_success_data(api_client.approve_label_review(review["id"], reviewer_headers))
        formula = get_success_data(api_client.get_formula(formula["id"], PM))
    return formula


def create_tank(tank_code=None, capacity_liters=5_000) -> dict:
    overrides = {}
    if tank_code is not None:
        overrides["tank_code"] = tank_code
    return get_success_data(api_client.create_tank(
        factories.create_tank_payload(capacity_liters=capacity_liters, **overrides), PM))


def create_line(line_code=None, supported_container_types=("PET_473",), nominal_cpm=200) -> dict:
    overrides = {}
    if line_code is not None:
        overrides["line_code"] = line_code
    return get_success_data(api_client.create_line(
        factories.create_line_payload(
            supported_container_types=list(supported_container_types),
            nominal_cpm=nominal_cpm, **overrides), PM))


def create_container_lot(container_type="PET_473", quantity_received=5_000,
                         supplier_lot_code=None, qc_pass=True) -> dict:
    overrides = {}
    if supplier_lot_code is not None:
        overrides["supplier_lot_code"] = supplier_lot_code
    lot = get_success_data(api_client.create_container_lot(
        factories.create_container_lot_payload(
            container_type=container_type, quantity_received=quantity_received, **overrides), WH))
    if qc_pass:
        lot = get_success_data(api_client.container_qc_verdict(lot["id"], {"verdict": "PASS"}, QA))
    return lot


def create_zone(zone_code=None, temperature_class="AMBIENT", pallet_capacity=50) -> dict:
    overrides = {}
    if zone_code is not None:
        overrides["zone_code"] = zone_code
    return get_success_data(api_client.create_zone(
        factories.create_zone_payload(
            temperature_class=temperature_class, pallet_capacity=pallet_capacity, **overrides), PM))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PM))


# ---------------------------------------------------------------------------
# Tier 2/3: batch lifecycle shortcuts
# ---------------------------------------------------------------------------

def plan_batch(formula_id: str, tank_id: str, quantity_liters=2000,
               planned_start_at="2026-08-10T08:00:00Z",
               planned_end_at="2026-08-10T12:00:00Z") -> dict:
    return get_success_data(api_client.create_batch(
        factories.create_batch_payload(
            formula_id, tank_id, quantity_liters=quantity_liters,
            planned_start_at=planned_start_at, planned_end_at=planned_end_at), OP))


def blend_and_record(batch_id: str, measured_brix: float, operator_headers=None) -> dict:
    """PLANNED -> BLENDING -> AWAITING_QA with the given measured brix."""
    operator_headers = operator_headers or OP
    get_success_data(api_client.start_blend(batch_id, operator_headers))
    return get_success_data(api_client.record_blend(
        batch_id, {"measured_brix": measured_brix}, operator_headers))


def remeasure_blend(batch_id: str, measured_brix: float, operator_headers=None) -> dict:
    """Re-measurement after a brix correction: PRD §3.4 returns the corrected
    batch to BLENDING, so only the record step (BLENDING -> AWAITING_QA, §3.3)
    applies — start-blend is admitted solely from PLANNED."""
    operator_headers = operator_headers or OP
    return get_success_data(api_client.record_blend(
        batch_id, {"measured_brix": measured_brix}, operator_headers))


def qa_verdict(batch_id: str, verdict: str, qa_headers=None) -> dict:
    qa_headers = qa_headers or QA
    return get_success_data(api_client.qa_verdict(batch_id, {"verdict": verdict}, qa_headers))


def create_qa_passed_batch(formula: dict, tank: dict, quantity_liters=2000,
                           measured_brix=None, planned_start_at="2026-08-10T08:00:00Z",
                           planned_end_at="2026-08-10T12:00:00Z") -> dict:
    """PLANNED -> BLENDING -> AWAITING_QA -> QA_PASSED."""
    if measured_brix is None:
        measured_brix = round(formula["target_brix"] + 0.1, 2)
    batch = plan_batch(formula["id"], tank["id"], quantity_liters=quantity_liters,
                       planned_start_at=planned_start_at, planned_end_at=planned_end_at)
    blend_and_record(batch["id"], measured_brix)
    return qa_verdict(batch["id"], "PASS")


def process_batch_validated(batch_id: str, process_type="PASTEURIZATION") -> dict:
    """Create + start + complete a process run with exact readings (VALIDATED)."""
    prun = get_success_data(api_client.create_process_run(
        factories.create_process_run_payload(batch_id, process_type), OP))
    get_success_data(api_client.start_process_run(prun["id"], OP))
    return get_success_data(api_client.complete_process_run(
        prun["id"], factories.complete_process_run_payload(process_type), OP))


def create_released_batch(formula: dict, tank: dict, quantity_liters=2000,
                          measured_brix=None,
                          planned_start_at="2026-08-10T08:00:00Z",
                          planned_end_at="2026-08-10T12:00:00Z") -> dict:
    """Full chain: blend -> QA PASS -> process VALIDATED -> RELEASED."""
    batch = create_qa_passed_batch(
        formula, tank, quantity_liters=quantity_liters, measured_brix=measured_brix,
        planned_start_at=planned_start_at, planned_end_at=planned_end_at)
    process_batch_validated(batch["id"], formula["process_type"])
    return get_success_data(api_client.release_batch(batch["id"], QA))


# ---------------------------------------------------------------------------
# Tier 3: production-run lifecycle shortcuts
# ---------------------------------------------------------------------------

def quote_run(customer_id: str, formula_id: str, planned_units=1000,
              unit_price_cents=150, container_type="PET_473") -> dict:
    return get_success_data(api_client.create_production_run(
        factories.create_production_run_payload(
            customer_id, formula_id, planned_units=planned_units,
            unit_price_cents=unit_price_cents, container_type=container_type), PLAN))


def confirm_run(run_id: str) -> dict:
    return get_success_data(api_client.confirm_run(run_id, PLAN))


def schedule_run(run_id: str, batch_id: str, line_id: str,
                 scheduled_start_at=WINDOW_START, scheduled_end_at=WINDOW_END,
                 expected_version=None) -> dict:
    """CONFIRMED/BLOCKED_SUPPLY -> SCHEDULED. Reads the current version when
    expected_version is not supplied."""
    if expected_version is None:
        expected_version = get_success_data(api_client.get_production_run(run_id, PM))["version"]
    return get_success_data(api_client.schedule_run(
        run_id,
        factories.schedule_run_payload(
            batch_id, line_id, expected_version,
            scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at),
        PLAN))


# ---------------------------------------------------------------------------
# Tier 5: full pipelines
# ---------------------------------------------------------------------------

def setup_pipeline(customer_overrides=None, formula_overrides=None, planned_units=1000,
                   unit_price_cents=150, container_type="PET_473",
                   line_types=("PET_473",), container_qty=5000,
                   zone_temperature="AMBIENT", zone_capacity=50,
                   batch_quantity=2000, approve_customer=True,
                   approve_formula=True,
                   credit_limit_cents=None, shelf_life_days=None) -> dict:
    """ACTIVE customer + formula + tank + RELEASED batch + line + QC_PASSED lot
    + zone + QUOTED run. The workhorse preamble for run/scheduling tests.

    credit_limit_cents / shelf_life_days are convenience routes into
    customer_overrides / formula_overrides for the two most commonly varied
    PRD-declared creation fields."""
    customer_overrides = dict(customer_overrides or {})
    formula_overrides = dict(formula_overrides or {})
    if credit_limit_cents is not None:
        customer_overrides.setdefault("credit_limit_cents", credit_limit_cents)
    if shelf_life_days is not None:
        formula_overrides.setdefault("shelf_life_days", shelf_life_days)
    customer = create_customer(approve=approve_customer, **customer_overrides)
    formula = create_formula(customer["id"], approve=approve_formula, **formula_overrides)
    tank = create_tank()
    batch = create_released_batch(formula, tank, quantity_liters=batch_quantity)
    line = create_line(supported_container_types=line_types)
    clot = create_container_lot(container_type=container_type, quantity_received=container_qty)
    zone = create_zone(temperature_class=zone_temperature, pallet_capacity=zone_capacity)
    run = quote_run(customer["id"], formula["id"], planned_units=planned_units,
                    unit_price_cents=unit_price_cents, container_type=container_type)
    return {
        "customer": customer, "formula": formula, "tank": tank, "batch": batch,
        "line": line, "container_lot": clot, "zone": zone, "run": run,
    }


def setup_scheduled_run(scheduled_start_at=WINDOW_START, scheduled_end_at=WINDOW_END,
                        **pipeline_kwargs) -> dict:
    """Pipeline + confirm + schedule. Returns namespace with the SCHEDULED run."""
    ctx = setup_pipeline(**pipeline_kwargs)
    ctx["run"] = confirm_run(ctx["run"]["id"])
    ctx["run"] = schedule_run(ctx["run"]["id"], ctx["batch"]["id"], ctx["line"]["id"],
                              scheduled_start_at, scheduled_end_at)
    return ctx


def setup_completed_run(actual_units_filled=1000, avg_fill_ml=473,
                        scheduled_start_at=WINDOW_START, scheduled_end_at=WINDOW_END,
                        clock_at_start=CLOCK_IN_WINDOW, **pipeline_kwargs) -> dict:
    """Full pipeline through COMPLETED: clock set inside the window, run started
    and completed. Adds 'lot' (the finished-good lot) to the namespace."""
    ctx = setup_scheduled_run(scheduled_start_at, scheduled_end_at, **pipeline_kwargs)
    set_clock(clock_at_start)
    ctx["run"] = get_success_data(api_client.start_run(ctx["run"]["id"], PLAN))
    ctx["run"] = get_success_data(api_client.complete_run(
        ctx["run"]["id"],
        factories.complete_run_payload(
            ctx["zone"]["id"], actual_units_filled=actual_units_filled,
            avg_fill_ml=avg_fill_ml),
        PLAN))
    ctx["lot"] = get_finished_lot_for_run(ctx["run"]["id"])
    return ctx


def get_finished_lot_for_run(run_id: str) -> dict:
    lots = get_success_data(api_client.list_run_finished_lots(run_id, PM))
    assert isinstance(lots, list) and len(lots) == 1, (
        f"Setup failed: expected exactly one finished lot for run {run_id}, got {lots}")
    return lots[0]


def get_pallet_account(customer_id: str) -> dict:
    accounts = get_success_data(api_client.get_customer_pallet_account(customer_id, PM))
    assert isinstance(accounts, list) and len(accounts) == 1, (
        f"Setup failed: expected exactly one pallet account for customer {customer_id}")
    return accounts[0]


def place_order(customer_id: str, formula_id: str, channel="FOODSERVICE",
                requested_delivery_date="2026-08-20", units_requested=500) -> dict:
    return get_success_data(api_client.create_shipment_order(
        factories.create_shipment_order_payload(
            customer_id, formula_id, channel=channel,
            requested_delivery_date=requested_delivery_date,
            units_requested=units_requested), CSR))


def allocate_order(order_id: str, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = get_success_data(api_client.get_shipment_order(order_id, PM))["version"]
    return get_success_data(api_client.allocate_order(
        order_id, {"expected_shipment_order_version": expected_version}, WH))


def ship_allocated_order(order_id: str) -> dict:
    """allocate -> pick -> ship for an order with enough eligible stock."""
    allocate_order(order_id)
    get_success_data(api_client.pick_order(order_id, WH))
    return get_success_data(api_client.ship_order(order_id, WH))
