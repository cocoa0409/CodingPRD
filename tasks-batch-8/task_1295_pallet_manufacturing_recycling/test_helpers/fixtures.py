"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_core_batch_payload,
    create_core_unit_payload,
    create_customer_payload,
    create_grinding_batch_payload,
    create_ht_run_payload,
    create_inventory_lot_payload,
    create_lumber_index_payload,
    create_order_line_payload,
    create_order_payload,
    create_pool_return_payload,
    create_repair_order_payload,
    create_route_payload,
    create_route_stop_payload,
    create_seasonal_index_payload,
    create_spec_payload,
)
from .test_users import TEST_USERS

PRO = TEST_USERS["procurement_manager_headers"]
YARD = TEST_USERS["yard_supervisor_headers"]
HT = TEST_USERS["heat_treat_operator_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FLEET = TEST_USERS["fleet_planner_headers"]
PLANT = TEST_USERS["plant_manager_headers"]
ANY = TEST_USERS["any_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    if expected_status is not None and resp.status_code != expected_status:
        _fail(step, resp)
    data = get_success_data(resp)
    if not (200 <= resp.status_code < 300):
        _fail(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1 — clock, market data, specs, lots, customers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=C.CLOCK_DEFAULT):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, PLANT)
    return _ok("set_clock", resp)


def publish_lumber_index(species="PINE",
                         price_per_mbf_cents=C.PINE_PRICE_PER_MBF_CENTS,
                         effective_from=C.INDEX_WINDOW_START,
                         effective_to=C.INDEX_WINDOW_END, source_note=None):
    resp = api_client.create_lumber_index(
        create_lumber_index_payload(
            species=species, price_per_mbf_cents=price_per_mbf_cents,
            effective_from=effective_from, effective_to=effective_to,
            source_note=source_note),
        PRO,
    )
    return _ok("publish_lumber_index", resp, expected_status=201)


def publish_seasonal_index(season_code="PEAK-2026-Q3", multiplier_bp=11_000,
                           effective_from=C.CLOCK_DEFAULT,
                           effective_to=C.INDEX_WINDOW_END):
    resp = api_client.create_seasonal_index(
        create_seasonal_index_payload(
            season_code=season_code, multiplier_bp=multiplier_bp,
            effective_from=effective_from, effective_to=effective_to),
        PLANT,
    )
    return _ok("publish_seasonal_index", resp, expected_status=201)


def create_spec(**overrides):
    resp = api_client.create_spec(create_spec_payload(**overrides), PLANT)
    return _ok("create_spec", resp, expected_status=201)


def activate_spec(spec_id):
    resp = api_client.activate_spec(spec_id, PLANT)
    return _ok("activate_spec", resp)


def create_active_spec(**overrides):
    """Create a spec and activate it. Returns the ACTIVE spec."""
    spec = create_spec(**overrides)
    return activate_spec(spec["id"])


def create_new_build_lot(spec_id, quantity_total, quality_grade="NEW"):
    resp = api_client.create_inventory_lot(
        create_inventory_lot_payload(
            spec_id=spec_id, origin_type="NEW_BUILD",
            quantity_total=quantity_total, quality_grade=quality_grade),
        PLANT,
    )
    return _ok("create_new_build_lot", resp, expected_status=201)


def create_customer(company_name="CustomerCo"):
    resp = api_client.create_customer(
        create_customer_payload(company_name=company_name), SALES)
    return _ok("create_customer", resp, expected_status=201)


def setup_pricing_world(set_default_clock=True, **spec_overrides):
    """Clock + PINE lumber index + ACTIVE PINE spec. Returns the spec."""
    if set_default_clock:
        set_clock()
    publish_lumber_index()
    return create_active_spec(**spec_overrides)


def setup_sellable_world(company_name="CustomerCo", lot_quantity=500,
                         lot_grade="NEW", **spec_overrides):
    """Pricing world + one NEW_BUILD lot + one customer.

    Returns (spec, lot, customer).
    """
    spec = setup_pricing_world(**spec_overrides)
    lot = create_new_build_lot(spec["id"], lot_quantity, lot_grade)
    customer = create_customer(company_name)
    return spec, lot, customer


# ---------------------------------------------------------------------------
# Tier 2 — orders: create / confirm / allocate / cancel / pay
# ---------------------------------------------------------------------------

def create_order(customer_id, spec_id, quantity=1,
                 quality_grade_requested="NEW",
                 requested_delivery_date=C.DEFAULT_DELIVERY_DATE,
                 heat_treatment_required=None):
    resp = api_client.create_order(
        create_order_payload(
            customer_id=customer_id, spec_id=spec_id, quantity=quantity,
            quality_grade_requested=quality_grade_requested,
            requested_delivery_date=requested_delivery_date,
            heat_treatment_required=heat_treatment_required),
        SALES,
    )
    return _ok("create_order", resp, expected_status=201)


def add_order_line(order_id, spec_id, quantity=1,
                   quality_grade_requested="NEW",
                   heat_treatment_required=None):
    resp = api_client.add_order_line(
        order_id,
        create_order_line_payload(
            spec_id=spec_id, quantity=quantity,
            quality_grade_requested=quality_grade_requested,
            heat_treatment_required=heat_treatment_required),
        SALES,
    )
    return _ok("add_order_line", resp, expected_status=201)


def confirm_order(order_id, expected_order_version):
    resp = api_client.confirm_order(
        order_id, {"expected_order_version": expected_order_version}, SALES)
    return _ok("confirm_order", resp)


def allocate_order(order_id, expected_order_version):
    resp = api_client.allocate_order(
        order_id, {"expected_order_version": expected_order_version}, SALES)
    return _ok("allocate_order", resp)


def create_confirmed_order(customer_id, spec_id, quantity=1,
                           quality_grade_requested="NEW", **kw):
    order = create_order(customer_id, spec_id, quantity,
                         quality_grade_requested, **kw)
    return confirm_order(order["id"], order["version"])


def create_allocated_order(customer_id, spec_id, quantity=1,
                           quality_grade_requested="NEW", **kw):
    order = create_confirmed_order(customer_id, spec_id, quantity,
                                   quality_grade_requested, **kw)
    return allocate_order(order["id"], order["version"])


def list_order_lines(order_id):
    resp = api_client.list_order_lines(SALES, params={"order_id": order_id})
    return _ok("list_order_lines", resp)


def get_order(order_id):
    resp = api_client.get_order(order_id, SALES)
    return _ok("get_order", resp)


def get_customer(customer_id):
    resp = api_client.get_customer(customer_id, SALES)
    return _ok("get_customer", resp)


def get_lot(lot_id):
    resp = api_client.get_inventory_lot(lot_id, PLANT)
    return _ok("get_lot", resp)


# ---------------------------------------------------------------------------
# Tier 3 — routes, stops, dispatch, delivery
# ---------------------------------------------------------------------------

def create_route(route_date=C.DEFAULT_ROUTE_DATE,
                 trailer_cube_capacity_cuft=5000, planned_miles=40):
    resp = api_client.create_route(
        create_route_payload(
            route_date=route_date,
            trailer_cube_capacity_cuft=trailer_cube_capacity_cuft,
            planned_miles=planned_miles),
        FLEET,
    )
    return _ok("create_route", resp, expected_status=201)


def add_route_stop(route_id, stop_sequence, stop_type="DELIVERY",
                   order_id=None, pickup_customer_id=None):
    resp = api_client.add_route_stop(
        route_id,
        create_route_stop_payload(
            stop_sequence=stop_sequence, stop_type=stop_type,
            order_id=order_id, pickup_customer_id=pickup_customer_id),
        FLEET,
    )
    return _ok("add_route_stop", resp, expected_status=201)


def get_route(route_id):
    resp = api_client.get_route(route_id, FLEET)
    return _ok("get_route", resp)


def dispatch_route_current_version(route_id):
    """Dispatch using the route's current version (read-then-write OCC)."""
    route = get_route(route_id)
    resp = api_client.dispatch_route(
        route_id, {"expected_route_version": route["version"]}, FLEET)
    return _ok("dispatch_route", resp)


def arrive_stop(stop_id):
    resp = api_client.arrive_stop(stop_id, FLEET)
    return _ok("arrive_stop", resp)


def complete_stop(stop_id):
    resp = api_client.complete_stop(stop_id, FLEET)
    return _ok("complete_stop", resp)


def deliver_order_via_new_route(order_id, route_date=C.DEFAULT_ROUTE_DATE,
                                planned_miles=40):
    """Route + one DELIVERY stop for the order + dispatch + arrive + complete.

    Returns (route, stop). The order must already be ALLOCATED.
    """
    route = create_route(route_date=route_date, planned_miles=planned_miles)
    stop = add_route_stop(route["id"], 1, "DELIVERY", order_id=order_id)
    dispatch_route_current_version(route["id"])
    arrive_stop(stop["id"])
    complete_stop(stop["id"])
    return get_route(route["id"]), stop


def setup_delivered_customer(company_name, spec_id, quantity,
                             customer_id=None):
    """Customer with `quantity` pallets delivered (pool_units_outstanding).

    Returns (customer, order). When `customer_id` is given, that existing
    customer is used and `company_name` is ignored — PRD §3.6 requires
    `company_name` to be unique, so callers that already created their
    customer (e.g. via setup_sellable_world) must pass it through rather
    than re-registering the same name.
    """
    if customer_id is None:
        customer_id = create_customer(company_name)["id"]
    order = create_allocated_order(customer_id, spec_id, quantity)
    deliver_order_via_new_route(order["id"],
                                route_date=order["requested_delivery_date"])
    return get_customer(customer_id), order


# ---------------------------------------------------------------------------
# Tier 4 — core procurement, sorting, settlement
# ---------------------------------------------------------------------------

def create_core_batch(supplier_name="CoreCo", agreed_unit_price_cents=500,
                      manifest_count=1, estimated_grade_mix=None):
    resp = api_client.create_core_batch(
        create_core_batch_payload(
            supplier_name=supplier_name,
            agreed_unit_price_cents=agreed_unit_price_cents,
            manifest_count=manifest_count,
            estimated_grade_mix=estimated_grade_mix),
        PRO,
    )
    return _ok("create_core_batch", resp, expected_status=201)


def begin_sorting(batch_id):
    resp = api_client.begin_sorting(batch_id, YARD)
    return _ok("begin_sorting", resp)


def finish_sorting(batch_id):
    resp = api_client.finish_sorting(batch_id, YARD)
    return _ok("finish_sorting", resp)


def close_batch(batch_id):
    resp = api_client.close_batch(batch_id, PRO)
    return _ok("close_batch", resp)


def get_batch(batch_id):
    resp = api_client.get_core_batch(batch_id, PRO)
    return _ok("get_batch", resp)


def receive_core(batch_id, species="PINE", condition_notes=None):
    resp = api_client.create_core_unit(
        create_core_unit_payload(batch_id=batch_id, species=species,
                                 condition_notes=condition_notes),
        YARD,
    )
    return _ok("receive_core", resp, expected_status=201)


def sort_core(core_id, grade, condition_notes=None):
    payload = {"grade": grade}
    if condition_notes is not None:
        payload["condition_notes"] = condition_notes
    resp = api_client.sort_core(core_id, payload, YARD)
    return _ok("sort_core", resp)


def get_core(core_id):
    resp = api_client.get_core_unit(core_id, YARD)
    return _ok("get_core", resp)


def create_sorting_batch_with_cores(supplier_name="CoreCo",
                                    agreed_unit_price_cents=500,
                                    manifest_count=1,
                                    estimated_grade_mix=None, num_cores=1):
    """Batch in SORTING with `num_cores` UNSORTED cores. Returns (batch, cores)."""
    batch = create_core_batch(supplier_name, agreed_unit_price_cents,
                              manifest_count, estimated_grade_mix)
    begin_sorting(batch["id"])
    cores = [receive_core(batch["id"]) for _ in range(num_cores)]
    return batch, cores


def create_graded_core(grade, spec_ready=True, supplier_name="GradedCo",
                       sort_note=None, **batch_kw):
    """Batch SORTING + one core sorted to `grade`. Returns (batch, core)."""
    batch, cores = create_sorting_batch_with_cores(
        supplier_name=supplier_name, **batch_kw)
    core = sort_core(cores[0]["id"], grade, condition_notes=sort_note)
    return batch, core


def setup_batch_in_audit(supplier_name="AuditCo", agreed_unit_price_cents=500,
                         manifest_count=1,
                         estimated_grade_mix=None, grades=("A",)):
    """Fully sorted batch in AUDIT. Returns (batch, cores)."""
    batch, cores = create_sorting_batch_with_cores(
        supplier_name=supplier_name,
        agreed_unit_price_cents=agreed_unit_price_cents,
        manifest_count=manifest_count,
        estimated_grade_mix=estimated_grade_mix,
        num_cores=len(grades))
    for core, grade in zip(cores, grades):
        note = "condemned" if grade == "SCRAP" else None
        sort_core(core["id"], grade, condition_notes=note)
    finish_sorting(batch["id"])
    return get_batch(batch["id"]), cores


# ---------------------------------------------------------------------------
# Tier 5 — repair work orders and recycled lots
# ---------------------------------------------------------------------------

def create_repair_order(core_id, target_spec_id, target_grade="A",
                        labor_minutes_estimate=30, parts_cost_cents=None):
    resp = api_client.create_repair_order(
        create_repair_order_payload(
            core_unit_id=core_id, target_spec_id=target_spec_id,
            target_grade=target_grade,
            labor_minutes_estimate=labor_minutes_estimate,
            parts_cost_cents=parts_cost_cents),
        YARD,
    )
    return _ok("create_repair_order", resp, expected_status=201)


def start_repair_order(wo_id):
    resp = api_client.start_repair_order(wo_id, YARD)
    return _ok("start_repair_order", resp)


def complete_repair_order(wo_id, outcome_grade, actual_labor_minutes):
    resp = api_client.complete_repair_order(
        wo_id, {"outcome_grade": outcome_grade,
                "actual_labor_minutes": actual_labor_minutes}, YARD)
    return _ok("complete_repair_order", resp)


def abort_repair_order(wo_id):
    resp = api_client.abort_repair_order(wo_id, YARD)
    return _ok("abort_repair_order", resp)


def create_completed_repair(target_spec_id, outcome_grade="A",
                            actual_labor_minutes=28, sort_grade="B",
                            target_grade="A", supplier_name="FixUp",
                            agreed_unit_price_cents=500):
    """Core sorted to `sort_grade`, repaired to `outcome_grade` (A or B).

    On success the core is REPAIRED and a 1-unit RECYCLED_REPAIR lot exists
    for `target_spec_id`. Returns (core, work_order).
    """
    batch, core = create_graded_core(
        sort_grade, supplier_name=supplier_name,
        agreed_unit_price_cents=agreed_unit_price_cents,
        estimated_grade_mix={"A": 0.0, "B": 1.0, "SCRAP": 0.0})
    wo = create_repair_order(core["id"], target_spec_id,
                             target_grade=target_grade)
    start_repair_order(wo["id"])
    complete_repair_order(wo["id"], outcome_grade, actual_labor_minutes)
    return get_core(core["id"]), wo


def find_lots(spec_id=None, status=None, origin_type=None):
    params = {}
    if spec_id:
        params["spec_id"] = spec_id
    if status:
        params["status"] = status
    resp = api_client.list_inventory_lots(PLANT, params=params)
    lots = _ok("find_lots", resp)
    if origin_type:
        lots = [l for l in lots if l["origin_type"] == origin_type]
    return lots


# ---------------------------------------------------------------------------
# Tier 6 — heat treatment
# ---------------------------------------------------------------------------

def create_ht_run(chamber_code="CH-1", species_profile="PINE",
                  capacity_pallets=100):
    resp = api_client.create_ht_run(
        create_ht_run_payload(chamber_code=chamber_code,
                              species_profile=species_profile,
                              capacity_pallets=capacity_pallets),
        HT,
    )
    return _ok("create_ht_run", resp, expected_status=201)


def assign_lot_to_run(run_id, lot_id):
    resp = api_client.assign_lot_to_run(run_id, {"lot_id": lot_id}, HT)
    return _ok("assign_lot_to_run", resp)


def start_ht_run(run_id):
    resp = api_client.start_ht_run(run_id, HT)
    return _ok("start_ht_run", resp)


def get_ht_run(run_id):
    resp = api_client.get_ht_run(run_id, HT)
    return _ok("get_ht_run", resp)


def setup_pending_ht_lot(quantity_total=10, quality_grade="NEW",
                         **spec_overrides):
    """ACTIVE spec with requires_heat_treatment_default=true + one lot.

    The lot is born with heat_treat_status PENDING_HT.
    Returns (spec, lot).
    """
    spec_overrides.setdefault("requires_heat_treatment_default", True)
    spec = setup_pricing_world(**spec_overrides)
    lot = create_new_build_lot(spec["id"], quantity_total, quality_grade)
    assert lot["heat_treat_status"] == "PENDING_HT", (
        f"Setup failed: lot must be PENDING_HT, got {lot['heat_treat_status']}"
    )
    return spec, lot


# ---------------------------------------------------------------------------
# Tier 7 — pool returns and grinding
# ---------------------------------------------------------------------------

def log_pool_return(customer_id, returned_count, grade_on_return,
                    route_stop_id=None, as_headers=None):
    resp = api_client.create_pool_return(
        create_pool_return_payload(
            customer_id=customer_id, returned_count=returned_count,
            grade_on_return=grade_on_return, route_stop_id=route_stop_id),
        as_headers or SALES,
    )
    return _ok("log_pool_return", resp, expected_status=201)


def grade_pool_return(return_id, grade_on_return):
    resp = api_client.grade_pool_return(
        return_id, {"grade_on_return": grade_on_return}, YARD)
    return _ok("grade_pool_return", resp)


def credit_pool_return(return_id):
    resp = api_client.credit_pool_return(return_id, SALES)
    return _ok("credit_pool_return", resp)


def setup_customer_with_credit(spec_id, company_name="CreditCust",
                               delivered_qty=5, return_count=4,
                               return_grade="A"):
    """Deliver `delivered_qty` pallets, return `return_count`, credit them.

    Returns (customer, pool_return). Customer.pool_credit_balance_cents ==
    return_count * tier(return_grade); pool_units_outstanding ==
    delivered_qty - return_count.
    """
    customer, _order = setup_delivered_customer(company_name, spec_id,
                                                delivered_qty)
    ret = log_pool_return(customer["id"], return_count, return_grade)
    grade_pool_return(ret["id"], return_grade)
    ret = credit_pool_return(ret["id"])
    return get_customer(customer["id"]), ret


def create_grinding_batch(input_core_ids):
    resp = api_client.create_grinding_batch(
        create_grinding_batch_payload(input_core_ids), YARD)
    return _ok("create_grinding_batch", resp, expected_status=201)


def start_grinding_batch(batch_id):
    resp = api_client.start_grinding_batch(batch_id, YARD)
    return _ok("start_grinding_batch", resp)


def complete_grinding_batch(batch_id, output_fiber_cuyd, revenue_cents=0):
    resp = api_client.complete_grinding_batch(
        batch_id, {"output_fiber_cuyd": output_fiber_cuyd,
                   "revenue_cents": revenue_cents}, YARD)
    return _ok("complete_grinding_batch", resp)


def create_scrap_cores(num_cores, supplier_name="GrindCo",
                       agreed_unit_price_cents=100):
    """`num_cores` sorted to SCRAP (processing_status GRINDING_QUEUED).

    Returns (batch, cores).
    """
    batch, cores = create_sorting_batch_with_cores(
        supplier_name=supplier_name,
        agreed_unit_price_cents=agreed_unit_price_cents,
        manifest_count=num_cores,
        estimated_grade_mix={"A": 0.0, "B": 0.0, "SCRAP": 1.0},
        num_cores=num_cores)
    sorted_cores = [
        sort_core(c["id"], "SCRAP", condition_notes="broken") for c in cores
    ]
    return batch, sorted_cores
