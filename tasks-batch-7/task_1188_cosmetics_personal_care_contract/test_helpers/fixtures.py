"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the public API,
because the test harness restarts the server (empty database) before each test.
Setup calls use the lenient get_success_data() so failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: CustomerRep is entity-backed, so every ownership-gated call
(order placement, confirm, cancel, PATCH, waive-variant, shortfall commit) uses
make_customer_rep_headers(customer["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOT_EXPIRES_AT, RUN_DAY
from .factories import (
    allocation_item,
    complete_run_payload,
    create_allocations_payload,
    create_batch_payload,
    create_chamber_payload,
    create_component_payload,
    create_customer_payload,
    create_formula_payload,
    create_line_payload,
    create_lot_payload,
    create_order_payload,
    create_review_payload,
    create_run_payload,
    declare_shortfall_payload,
    escalate_shortfall_payload,
    ipc_check_payload,
    patch_order_payload,
    record_reading_payload,
    single_ingredient,
    waive_variant_payload,
    create_revision_payload,
    create_study_payload,
)
from .test_users import TEST_USERS, make_customer_rep_headers, make_qa_manager_headers

PD = TEST_USERS["plant_director_headers"]
PP = TEST_USERS["production_planner_headers"]
QA1 = TEST_USERS["qa_manager_1_headers"]
QA2 = TEST_USERS["qa_manager_2_headers"]
FC = TEST_USERS["formulation_chemist_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]

PASSING_VISCOSITY = 4000   # exactly the default target -> PASS
PASSING_PH = 5.5           # exactly the default target -> PASS


# ---------------------------------------------------------------------------
# Tier 1/2: single-resource creators and state progression
# ---------------------------------------------------------------------------

def create_customer(**overrides):
    """Register a brand-owner customer. Returns the customer dict."""
    resp = api_client.create_customer(create_customer_payload(**overrides), PD)
    return get_success_data(resp)


def create_component(**overrides):
    """Register a component. Returns the component dict."""
    resp = api_client.create_component(create_component_payload(**overrides), PP)
    return get_success_data(resp)


def create_customer_supplied_component(customer_id, **overrides):
    """Register a CUSTOMER_SUPPLIED component owned by the given customer."""
    overrides.setdefault("supply_mode", "CUSTOMER_SUPPLIED")
    overrides.setdefault("customer_id", customer_id)
    overrides.setdefault("standard_cost_per_kg_cents", 0)
    return create_component(**overrides)


def create_lot(component_id, **overrides):
    """Receive a lot against a component. Returns the lot dict."""
    resp = api_client.create_lot(component_id, create_lot_payload(**overrides), PP)
    return get_success_data(resp)


def create_formula(customer_id, ingredients=None, component_id=None, **overrides):
    """Create a formula in DRAFT. Pass either a full ingredients list or a single
    component_id for a 100%-ingredient formula. Returns the formula dict."""
    if ingredients is None:
        ingredients = single_ingredient(component_id)
    resp = api_client.create_formula(create_formula_payload(customer_id, ingredients, **overrides), FC)
    return get_success_data(resp)


def submit_formula(formula_id):
    return get_success_data(api_client.submit_formula(formula_id, FC))


def open_review(formula_id, review_scope="INCI_LIST"):
    """Open a regulatory review; returns the SUBMITTED review dict."""
    return get_success_data(api_client.create_review(formula_id, create_review_payload(review_scope), FC))


def claim_review(review_id):
    return get_success_data(api_client.claim_review(review_id, RA))


def approve_review(review_id):
    return get_success_data(api_client.approve_review(review_id, RA))


def request_changes(review_id, comment="changes requested"):
    return get_success_data(api_client.request_changes(review_id, {"comment": comment}, RA))


def resubmit_review(review_id):
    return get_success_data(api_client.resubmit_review(review_id, FC))


def activate_formula(formula_id):
    return get_success_data(api_client.activate_formula(formula_id, FC))


def create_active_formula(customer_id, ingredients=None, component_id=None, **overrides):
    """Full regulatory walk: DRAFT -> IN_REVIEW -> INCI_LIST approved ->
    APPROVED -> ACTIVE. Returns the ACTIVE formula dict."""
    formula = create_formula(customer_id, ingredients=ingredients, component_id=component_id, **overrides)
    submit_formula(formula["id"])
    review = open_review(formula["id"], "INCI_LIST")
    claim_review(review["id"])
    approve_review(review["id"])
    return activate_formula(formula["id"])


def create_approved_formula(customer_id, ingredients=None, component_id=None, **overrides):
    """Walk to APPROVED (INCI_LIST review approved) but do NOT activate."""
    formula = create_formula(customer_id, ingredients=ingredients, component_id=component_id, **overrides)
    submit_formula(formula["id"])
    review = open_review(formula["id"], "INCI_LIST")
    claim_review(review["id"])
    approve_review(review["id"])
    return get_success_data(api_client.get_formula(formula["id"], FC))


def approve_label_artwork(formula_id):
    """Open + claim + approve a LABEL_ARTWORK review on an ACTIVE formula."""
    review = open_review(formula_id, "LABEL_ARTWORK")
    claim_review(review["id"])
    return approve_review(review["id"])


def create_revision(formula_id, expected_formula_version, **overrides):
    return get_success_data(api_client.create_revision(
        formula_id, create_revision_payload(expected_formula_version, **overrides), FC))


# --- Orders ---

def create_order(customer_id, formula_id, requested_units):
    """Place a DRAFT order as the owning CustomerRep. Returns the order dict."""
    resp = api_client.create_order(
        create_order_payload(formula_id, requested_units),
        make_customer_rep_headers(customer_id),
    )
    return get_success_data(resp)


def confirm_order(order_id, customer_id):
    return get_success_data(api_client.confirm_order(order_id, make_customer_rep_headers(customer_id)))


def create_confirmed_order(customer_id, formula_id, requested_units):
    order = create_order(customer_id, formula_id, requested_units)
    return confirm_order(order["id"], customer_id)


def cancel_order(order_id, customer_id):
    return get_success_data(api_client.cancel_order(order_id, make_customer_rep_headers(customer_id)))


def resume_order(order_id):
    """ProductionPlanner resumes an ON_HOLD order (PRD §3.3)."""
    return get_success_data(api_client.resume_order(order_id, PP))


def patch_order_units(order_id, customer_id, requested_units, expected_version):
    return get_success_data(api_client.patch_order(
        order_id, patch_order_payload(requested_units, expected_version),
        make_customer_rep_headers(customer_id)))


# --- Batches, allocations, IPC ---

def create_batch(order_id, batch_size_kg):
    return get_success_data(api_client.create_batch(order_id, create_batch_payload(batch_size_kg), PP))


def allocate_lots(order_id, items):
    """Reserve lots for an order. Returns the list of allocation dicts."""
    resp = api_client.create_allocations(order_id, create_allocations_payload(items), PP)
    return get_success_data(resp)


def start_mixing(batch_id):
    return get_success_data(api_client.start_mixing(batch_id, PP))


def record_ipc_check(batch_id, check_type, measured_value, headers=None):
    headers = headers or QA1
    return get_success_data(api_client.record_ipc_check(
        batch_id, ipc_check_payload(check_type, measured_value), headers))


def adjust_batch(batch_id, headers=None):
    headers = headers or QA1
    return get_success_data(api_client.adjust_batch(batch_id, {"adjustment_note": "adjust"}, headers))


def release_batch(batch_id, headers=None):
    headers = headers or QA2
    return get_success_data(api_client.release_batch(batch_id, headers))


def reject_batch(batch_id, reason="off-spec", headers=None):
    headers = headers or QA1
    return get_success_data(api_client.reject_batch(batch_id, {"reason": reason}, headers))


# --- Filling lines & runs ---

def create_line(**overrides):
    return get_success_data(api_client.create_line(create_line_payload(**overrides), PP))


def schedule_run(order_id, line_id, batch_id, planned_units,
                 scheduled_start=f"{RUN_DAY}T08:00:00Z",
                 scheduled_end=f"{RUN_DAY}T09:00:00Z"):
    resp = api_client.create_run(
        order_id,
        create_run_payload(line_id, batch_id, planned_units, scheduled_start, scheduled_end),
        PP,
    )
    return get_success_data(resp)


def start_run(run_id):
    return get_success_data(api_client.start_run(run_id, PP))


def complete_run(run_id, filled_units, **overrides):
    return get_success_data(api_client.complete_run(run_id, complete_run_payload(filled_units, **overrides), PP))


def abort_run(run_id):
    return get_success_data(api_client.abort_run(run_id, PP))


def finish_cleaning(line_id):
    return get_success_data(api_client.finish_cleaning(line_id, PP))


# --- Stability ---

def create_chamber(**overrides):
    return get_success_data(api_client.create_chamber(create_chamber_payload(**overrides), QA1))


def create_study(formula_id, chamber_id, study_type):
    return get_success_data(api_client.create_study(
        formula_id, create_study_payload(chamber_id, study_type), QA1))


def record_reading(study_id, interval_index, result, headers=None):
    headers = headers or QA1
    return get_success_data(api_client.record_reading(
        study_id, record_reading_payload(interval_index, result), headers))


# --- Shortfalls & waivers ---

def declare_shortfall(order_id, component_id, required_quantity):
    return get_success_data(api_client.declare_shortfall(
        order_id, declare_shortfall_payload(component_id, required_quantity), PP))


def commit_shortfall(shortfall_id, customer_id, committed_by_date="2026-06-01T00:00:00Z"):
    return get_success_data(api_client.commit_shortfall(
        shortfall_id, {"committed_by_date": committed_by_date},
        make_customer_rep_headers(customer_id)))


def escalate_shortfall(shortfall_id, resolution):
    return get_success_data(api_client.escalate_shortfall(
        shortfall_id, escalate_shortfall_payload(resolution), PP))


def waive_variant(lot_id, customer_id, decision):
    return get_success_data(api_client.waive_variant(
        lot_id, waive_variant_payload(decision), make_customer_rep_headers(customer_id)))


# ---------------------------------------------------------------------------
# Tier 3: composite lifecycle contexts
# ---------------------------------------------------------------------------

def confirmed_order_ctx(requested_units=2000, required_components=None,
                        component_cost=1000, formula_overrides=None,
                        customer_overrides=None):
    """Customer + raw component + ACTIVE 100%-AQUA formula + CONFIRMED order.

    Returns a ctx dict with keys: customer, component, formula, order.
    """
    customer = create_customer(**(customer_overrides or {}))
    component = create_component(standard_cost_per_kg_cents=component_cost)
    formula = create_active_formula(
        customer["id"], component_id=component["id"],
        required_components=required_components or [],
        **(formula_overrides or {}),
    )
    order = create_confirmed_order(customer["id"], formula["id"], requested_units)
    return {"customer": customer, "component": component, "formula": formula, "order": order}


def mixing_batch_ctx(batch_size_kg=100, lot_quantity=200, alloc_quantity=100,
                     requested_units=2000, **ctx_overrides):
    """confirmed_order_ctx + PLANNED batch + lot + full batch allocation + MIXING.

    The order has moved CONFIRMED -> IN_PRODUCTION (first MIXING batch).
    Keys: customer, component, formula, order, batch, lot, allocations.
    """
    ctx = confirmed_order_ctx(requested_units=requested_units, **ctx_overrides)
    batch = create_batch(ctx["order"]["id"], batch_size_kg)
    lot = create_lot(ctx["component"]["id"], quantity_received=lot_quantity)
    allocations = allocate_lots(ctx["order"]["id"], [
        allocation_item(lot["id"], alloc_quantity, batch_id=batch["id"]),
    ])
    started = start_mixing(batch["id"])
    ctx.update({"batch": started, "lot": lot, "allocations": allocations})
    return ctx


def ipc_passed_batch_ctx(**kwargs):
    """mixing_batch_ctx + both round checks PASS (recorded by qa-1)."""
    ctx = mixing_batch_ctx(**kwargs)
    record_ipc_check(ctx["batch"]["id"], "VISCOSITY", PASSING_VISCOSITY, QA1)
    record_ipc_check(ctx["batch"]["id"], "PH", PASSING_PH, QA1)
    ctx["batch"] = get_success_data(api_client.get_batch(ctx["batch"]["id"], QA1))
    return ctx


def released_batch_ctx(**kwargs):
    """ipc_passed_batch_ctx + release by qa-2 (segregation of duties honored).
    Keys add: line."""
    ctx = ipc_passed_batch_ctx(**kwargs)
    ctx["batch"] = release_batch(ctx["batch"]["id"], QA2)
    ctx["line"] = create_line()
    return ctx


def in_progress_run_ctx(requested_units=1000, batch_size_kg=50, lot_quantity=100,
                        alloc_quantity=50, planned_units=1000, **ctx_overrides):
    """released_batch_ctx + scheduled run + started run.

    The order has moved IN_PRODUCTION -> FILLING; the line is RUNNING.
    Keys add: run.
    """
    ctx = released_batch_ctx(
        requested_units=requested_units, batch_size_kg=batch_size_kg,
        lot_quantity=lot_quantity, alloc_quantity=alloc_quantity, **ctx_overrides)
    run = schedule_run(ctx["order"]["id"], ctx["line"]["id"], ctx["batch"]["id"], planned_units)
    ctx["run"] = start_run(run["id"])
    return ctx


def scheduled_run_ctx(requested_units=2000, batch_size_kg=100, planned_units=2000,
                      scheduled_start=f"{RUN_DAY}T08:00:00Z",
                      scheduled_end=f"{RUN_DAY}T10:00:00Z",
                      **ctx_overrides):
    """confirmed_order_ctx + PLANNED batch + line + SCHEDULED run (no mixing).

    The order remains CONFIRMED. Keys add: batch, line, run.
    """
    ctx = confirmed_order_ctx(requested_units=requested_units, **ctx_overrides)
    ctx["batch"] = create_batch(ctx["order"]["id"], batch_size_kg)
    ctx["line"] = create_line()
    ctx["run"] = schedule_run(ctx["order"]["id"], ctx["line"]["id"], ctx["batch"]["id"],
                              planned_units, scheduled_start, scheduled_end)
    return ctx
