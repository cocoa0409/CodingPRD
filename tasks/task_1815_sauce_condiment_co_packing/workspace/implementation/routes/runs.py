"""ProductionRun endpoints: planning (revision pinning), confirmation
(changeover fee, estimate, reservations, consignment draw, credit gate),
completion (final charge, billing delta, packaging consumption, auto-hold on
pH/aw deviation), release, and cancellation."""
from flask import Blueprint, g, request

from db import STORE
from errors import (
    err,
    ERR_BATCH_EXCEEDS_CAPACITY,
    ERR_COMPONENT_NOT_FOUND,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_FORMULA_NOT_APPROVED,
    ERR_FORMULA_NOT_FOUND,
    ERR_HOLD_BLOCKS_RELEASE,
    ERR_INGREDIENT_SHORTAGE,
    ERR_INVALID_REQUEST,
    ERR_KETTLE_LINE_CONFLICT,
    ERR_KETTLE_LINE_NOT_FOUND,
    ERR_LABEL_NOT_APPROVED,
    ERR_PACKAGING_SHORTAGE,
    ERR_RUN_NOT_CANCELLABLE,
    ERR_RUN_NOT_COMPLETABLE,
    ERR_RUN_NOT_COMPLETED,
    ERR_RUN_NOT_FOUND,
    ERR_RUN_NOT_PLANNED,
)
from middleware import check_customer_scope, require_roles
from response import paginate, success
from services.calc import (
    active_letter_for,
    changeover_fee,
    compute_estimate,
    compute_final,
    hold_deviation_metrics,
    kettle_line_conflict,
    supplies_of,
)
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from services.run_ops import adjust_outstanding, cancel_run
from util import as_dt, as_int, as_num, as_str, body_json, req

bp = Blueprint("runs", __name__)


def _customer_of(run):
    formula = STORE.formulas.get(run["formula_id"])
    return STORE.customers.get(formula["customer_id"]) if formula else None


def _validate_packaging_requirements(body):
    """packaging_requirements: required array (may be empty) of
    {component_id, quantity_per_unit > 0}."""
    raw = req(body, "packaging_requirements")
    if not isinstance(raw, list):
        raise err(ERR_INVALID_REQUEST, 400, "packaging_requirements must be an array")
    lines = []
    for line in raw:
        if not isinstance(line, dict):
            raise err(ERR_INVALID_REQUEST, 400, "each packaging requirement must be an object")
        component_id = as_str(req(line, "component_id"), "component_id")
        quantity_per_unit = as_num(req(line, "quantity_per_unit"), "quantity_per_unit")
        if quantity_per_unit <= 0:
            raise err(ERR_INVALID_REQUEST, 400, "quantity_per_unit must be > 0")
        lines.append({"component_id": component_id, "quantity_per_unit": quantity_per_unit})
    return lines


@bp.post("/copack/production-runs")
def create_run():
    require_roles("OpsAdmin")
    body = body_json()
    # Body FK existence (stage 4) precedes request shape (stage 5).
    raw_formula_id = body.get("formula_id")
    if isinstance(raw_formula_id, str):
        find_or_404(STORE.formulas, raw_formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    raw_line_id = body.get("kettle_line_id")
    if isinstance(raw_line_id, str):
        find_or_404(STORE.kettle_lines, raw_line_id, ERR_KETTLE_LINE_NOT_FOUND, "kettle line")
    raw_reqs = body.get("packaging_requirements")
    if isinstance(raw_reqs, list):
        for line in raw_reqs:
            if isinstance(line, dict) and isinstance(line.get("component_id"), str):
                find_or_404(STORE.components, line["component_id"], ERR_COMPONENT_NOT_FOUND, "packaging component")
    formula_id = as_str(req(body, "formula_id"), "formula_id")
    formula = find_or_404(STORE.formulas, formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    kettle_line_id = as_str(req(body, "kettle_line_id"), "kettle_line_id")
    line = find_or_404(STORE.kettle_lines, kettle_line_id, ERR_KETTLE_LINE_NOT_FOUND, "kettle line")
    planned_units = as_int(req(body, "planned_units"), "planned_units")
    if planned_units < 1:
        raise err(ERR_INVALID_REQUEST, 400, "planned_units must be >= 1")
    scheduled_start = as_dt(req(body, "scheduled_start"), "scheduled_start")
    scheduled_end = as_dt(req(body, "scheduled_end"), "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise err(ERR_INVALID_REQUEST, 400, "scheduled_end must be strictly after scheduled_start")
    packaging_requirements = _validate_packaging_requirements(body)
    for req_line in packaging_requirements:
        find_or_404(STORE.components, req_line["component_id"], ERR_COMPONENT_NOT_FOUND, "packaging component")
    # Stage 6: the formula must be TRIAL_PASSED or APPROVED (the catalogue maps
    # run creation from DRAFT/IN_TRIAL onto ERR_FORMULA_NOT_APPROVED).
    if formula["status"] not in ("TRIAL_PASSED", "APPROVED"):
        raise err(ERR_FORMULA_NOT_APPROVED, 409, "formula must be TRIAL_PASSED or APPROVED to plan a run")
    if planned_units > line["capacity_units"]:
        raise err(ERR_BATCH_EXCEEDS_CAPACITY, 409, "planned_units exceeds the kettle line capacity")
    rec = new_record({
        "formula_id": formula_id,
        "kettle_line_id": kettle_line_id,
        "planned_units": planned_units,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "packaging_requirements": packaging_requirements,
        "formula_revision": formula["revision"],
        "actual_units_produced": None,
        "measured_ph": None,
        "measured_water_activity": None,
        "changeover_fee_cents": None,
        "estimated_charge_cents": None,
        "final_charge_cents": None,
        "status": "PLANNED",
    })
    STORE.runs[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/production-runs")
def list_runs():
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    formula_id = request.args.get("formula_id")
    kettle_line_id = request.args.get("kettle_line_id")
    status = request.args.get("status")
    items = []
    for r in sorted_created(STORE.runs.values()):
        if g.user_role == "Customer":
            f = STORE.formulas.get(r["formula_id"])
            if f is None or f["customer_id"] != g.user_id:
                continue
        if formula_id is not None and r["formula_id"] != formula_id:
            continue
        if kettle_line_id is not None and r["kettle_line_id"] != kettle_line_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(serialize(r))
    return paginate(items)


@bp.get("/copack/production-runs/<rid>")
def get_run(rid):
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    rec = find_or_404(STORE.runs, rid, ERR_RUN_NOT_FOUND, "production run")
    f = STORE.formulas.get(rec["formula_id"])
    if f is not None:
        check_customer_scope(f["customer_id"])
    return success(serialize(rec))


@bp.post("/copack/production-runs/<rid>/confirm")
def confirm_run(rid):
    require_roles("OpsAdmin")
    run = find_or_404(STORE.runs, rid, ERR_RUN_NOT_FOUND, "production run")
    # Stage 6 state gates: run PLANNED, then formula APPROVED.
    if run["status"] != "PLANNED":
        raise err(ERR_RUN_NOT_PLANNED, 409, "only a PLANNED run can be confirmed")
    formula = STORE.formulas.get(run["formula_id"])
    if formula is None or formula["status"] != "APPROVED":
        raise err(ERR_FORMULA_NOT_APPROVED, 409, "formula must be APPROVED to confirm a run")
    customer = STORE.customers.get(formula["customer_id"])
    # Stage 8 domain constraints, in workflow order (PRD §3.5): the kettle-line
    # interval rule, packaging availability, consigned-ingredient availability.
    if kettle_line_conflict(run):
        raise err(ERR_KETTLE_LINE_CONFLICT, 409, "run window conflicts with an occupying run on this kettle line")
    for req_line in run["packaging_requirements"]:
        comp = STORE.components[req_line["component_id"]]
        required = req_line["quantity_per_unit"] * run["planned_units"]
        available = comp["on_hand_units"] - comp["reserved_units"]
        if required > available:
            raise err(ERR_PACKAGING_SHORTAGE, 409, "packaging requirement exceeds available stock")
    for s in supplies_of(run["formula_id"]):
        if s["sourcing_mode"] == "CUSTOMER_SUPPLIED":
            required = s["quantity_per_unit"] * run["planned_units"]
            if s["consigned_units_on_hand"] < required:
                raise err(ERR_INGREDIENT_SHORTAGE, 409, "consigned ingredient stock is insufficient")
    # Charge math: the changeover fee is computed once and locked here; the
    # estimate is the planned-units variant of the run charge.
    run["changeover_fee_cents"] = changeover_fee(run)
    estimate = compute_estimate(run, formula)
    # Stage 10: credit is always the final gate; equality with the limit passes.
    if customer["outstanding_billed_cents"] + estimate > customer["credit_limit_cents"]:
        raise err(ERR_CREDIT_LIMIT_EXCEEDED, 402, "estimated charge would exceed the customer's credit limit")
    # Effects: bill the estimate, reserve packaging, draw consignments.
    run["estimated_charge_cents"] = estimate
    run["status"] = "CONFIRMED"
    touch(run)
    adjust_outstanding(customer, estimate)
    for req_line in run["packaging_requirements"]:
        comp = STORE.components[req_line["component_id"]]
        comp["reserved_units"] += req_line["quantity_per_unit"] * run["planned_units"]
        touch(comp)
    for s in supplies_of(run["formula_id"]):
        if s["sourcing_mode"] == "CUSTOMER_SUPPLIED":
            s["consigned_units_on_hand"] -= s["quantity_per_unit"] * run["planned_units"]
            touch(s)
    return success(serialize(run))


@bp.post("/copack/production-runs/<rid>/complete")
def complete_run(rid):
    require_roles("OpsAdmin")
    run = find_or_404(STORE.runs, rid, ERR_RUN_NOT_FOUND, "production run")
    body = body_json()
    actual_units_produced = as_int(req(body, "actual_units_produced"), "actual_units_produced")
    if actual_units_produced < 0:
        raise err(ERR_INVALID_REQUEST, 400, "actual_units_produced must be >= 0")
    measured_ph = as_num(req(body, "measured_ph"), "measured_ph")
    measured_water_activity = as_num(req(body, "measured_water_activity"), "measured_water_activity")
    # Stage 6: only CONFIRMED or REWORK runs are completable.
    if run["status"] not in ("CONFIRMED", "REWORK"):
        raise err(ERR_RUN_NOT_COMPLETABLE, 409, "only a CONFIRMED or REWORK run can be completed")
    formula = STORE.formulas.get(run["formula_id"])
    customer = STORE.customers.get(formula["customer_id"])
    # Packaging feasibility is rechecked against actuals before anything books.
    for req_line in run["packaging_requirements"]:
        comp = STORE.components[req_line["component_id"]]
        required = req_line["quantity_per_unit"] * actual_units_produced
        if comp["on_hand_units"] < required:
            raise err(ERR_PACKAGING_SHORTAGE, 409, "packaging consumption exceeds on-hand stock")
    first_complete = run["status"] == "CONFIRMED"
    # Final charge: actuals drive units_billed and packaging lines; the
    # changeover fee stays locked from confirmation.
    final_charge = compute_final(run, formula, actual_units_produced)
    previously_applied = run["estimated_charge_cents"] if first_complete else run["final_charge_cents"]
    run["actual_units_produced"] = actual_units_produced
    run["measured_ph"] = measured_ph
    run["measured_water_activity"] = measured_water_activity
    run["final_charge_cents"] = final_charge
    # Billing moves by the delta against the previously applied charge.
    adjust_outstanding(customer, final_charge - previously_applied)
    # Physical stock: on_hand falls on every completion; the reservation
    # release happens on the first completion only.
    for req_line in run["packaging_requirements"]:
        comp = STORE.components[req_line["component_id"]]
        if first_complete:
            comp["reserved_units"] -= req_line["quantity_per_unit"] * run["planned_units"]
        comp["on_hand_units"] -= req_line["quantity_per_unit"] * actual_units_produced
        touch(comp)
    # Food-safety automation: an ACTIVE letter plus a deviation (pH strictly
    # over max_ph, or aw reaching max_water_activity; pH wins when both
    # deviate) routes the run to ON_HOLD behind an automatic QualityHold.
    letter = active_letter_for(run["formula_id"])
    auto_reason = None
    if letter is not None:
        ph_deviates = measured_ph > letter["max_ph"]
        aw_deviates = measured_water_activity >= letter["max_water_activity"]
        if ph_deviates:
            auto_reason = "PH_DEVIATION"
        elif aw_deviates:
            auto_reason = "AW_DEVIATION"
    if auto_reason is not None:
        letter_deviation, statutory_margin = hold_deviation_metrics(
            auto_reason, measured_ph, measured_water_activity, letter
        )
        hold = new_record({
            "production_run_id": run["id"],
            "reason_category": auto_reason,
            "measured_ph": measured_ph,
            "measured_water_activity": measured_water_activity,
            "letter_deviation": letter_deviation,
            "statutory_margin": statutory_margin,
            "disposition_owner": customer["default_disposition_owner"],
            "created_by_user_id": "system",
            "disposition": None,
            "disposition_note": None,
            "status": "OPEN",
        })
        STORE.holds[hold["id"]] = hold
        run["status"] = "ON_HOLD"
    else:
        run["status"] = "COMPLETED"
    touch(run)
    return success(serialize(run))


@bp.post("/copack/production-runs/<rid>/release")
def release_run(rid):
    require_roles("QAReviewer")
    run = find_or_404(STORE.runs, rid, ERR_RUN_NOT_FOUND, "production run")
    if run["status"] != "COMPLETED":
        raise err(ERR_RUN_NOT_COMPLETED, 409, "only a COMPLETED run can be released")
    for hold in STORE.holds.values():
        if hold["production_run_id"] == rid and hold["status"] == "OPEN":
            raise err(ERR_HOLD_BLOCKS_RELEASE, 409, "an OPEN quality hold still references this run")
    has_approved_label = any(
        label["formula_id"] == run["formula_id"] and label["status"] == "APPROVED"
        for label in STORE.labels.values()
    )
    if not has_approved_label:
        raise err(ERR_LABEL_NOT_APPROVED, 409, "no APPROVED label exists for the run's formula")
    run["status"] = "RELEASED"
    touch(run)
    return success(serialize(run))


@bp.post("/copack/production-runs/<rid>/cancel")
def cancel_run_endpoint(rid):
    require_roles("OpsAdmin")
    run = find_or_404(STORE.runs, rid, ERR_RUN_NOT_FOUND, "production run")
    if run["status"] not in ("PLANNED", "CONFIRMED"):
        raise err(ERR_RUN_NOT_CANCELLABLE, 409, "only a PLANNED or CONFIRMED run can be cancelled")
    customer = _customer_of(run)
    cancel_run(run, customer)
    return success(serialize(run))
