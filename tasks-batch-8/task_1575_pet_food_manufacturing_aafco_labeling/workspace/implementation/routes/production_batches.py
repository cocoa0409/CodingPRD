"""ProductionBatch endpoints."""

from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import errors
from db import store, parse_iso
from middleware import (require_roles, get_json_body, require_string,
                        require_number, require_int, optional_field,
                        optional_bool, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import (stamp_new, touch, serialize, serialize_list,
                                   compute_yield_variance, YIELD_HOLD_THRESHOLD_PCT,
                                   mint_lot_code)

bp = Blueprint("production_batches", __name__)

BATCH_TERMINAL = {"COMPLETED", "REJECTED", "RECALLED"}


@bp.route("/formulas/<formula_id>/production-batches", methods=["POST"])
def create_batch(formula_id):
    require_roles("ProductionPlanner")
    formula = store.formulas.get(formula_id)
    if formula is None:
        raise errors.not_found("Formula not found")
    body = get_json_body()
    planned_kg = require_number(body, "planned_kg")
    if planned_kg <= 0:
        raise errors.invalid_request("planned_kg must be > 0")
    line_id = require_string(body, "line_id")
    scheduled_start_raw = body.get("scheduled_start")
    sched_dt = parse_iso(scheduled_start_raw)
    if sched_dt is None:
        raise errors.invalid_request("scheduled_start must be a valid ISO 8601 timestamp")
    if "expected_formula_version" not in body or body["expected_formula_version"] is None:
        raise errors.invalid_request("expected_formula_version is required")
    efv = body["expected_formula_version"]
    if isinstance(efv, bool) or not isinstance(efv, int):
        raise errors.invalid_request("expected_formula_version must be an integer")

    if formula["status"] != "LOCKED":
        raise errors.invalid_state("Batches may only be created against a LOCKED formula")
    if efv != formula["version"]:
        raise errors.stale_formula_version()

    batch = {
        "formula_id": formula_id,
        "planned_kg": planned_kg,
        "actual_kg": 0,
        "line_id": line_id,
        "scheduled_start": scheduled_start_raw if isinstance(scheduled_start_raw, str) else sched_dt.isoformat(),
        "status": "SCHEDULED",
        "yield_variance_pct": None,
        "expected_formula_version": efv,
        "_scheduled_start_dt": sched_dt,
    }
    stamp_new(batch)
    store.production_batches[batch["id"]] = batch
    # Creating a batch advances the formula's version
    touch(formula)
    return success_object(serialize(batch), 201)


def _get_batch(id):
    b = store.production_batches.get(id)
    if b is None:
        raise errors.not_found("ProductionBatch not found")
    return b


def _check_batch_not_terminal(b):
    if b["status"] in BATCH_TERMINAL:
        raise errors.already_terminal("Batch is in a terminal state")


@bp.route("/production-batches/<id>", methods=["GET"])
def get_batch(id):
    require_roles("PlatformAdmin", "ProductionPlanner", "LineOperator",
                  "QualityAnalyst", "QAApprover")
    batch = _get_batch(id)
    return success_object(serialize(batch), 200)


@bp.route("/formulas/<id>/production-batches", methods=["GET"])
def list_batches(id):
    require_roles("PlatformAdmin", "ProductionPlanner", "QualityAnalyst", "QAApprover")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [b for b in store.production_batches.values() if b["formula_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [b for b in items if b["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/production-batches/<id>/release", methods=["POST"])
def release_batch(id):
    require_roles("ProductionPlanner")
    batch = _get_batch(id)
    _check_batch_not_terminal(batch)
    if batch["status"] != "SCHEDULED":
        raise errors.invalid_state("Only SCHEDULED batches can be released")
    formula = store.formulas.get(batch["formula_id"])
    if formula is None:
        raise errors.not_found("Formula not found")
    if formula["status"] != "LOCKED":
        raise errors.invalid_state("Formula must be LOCKED")

    # Guard order: open-recall, ingredient-active, sourcing coverage, line conflict.
    if formula.get("open_recall_flag"):
        raise errors.open_recall()

    lines = [fi for fi in store.formula_ingredients.values()
             if fi["formula_id"] == formula["id"]]
    for fi in lines:
        ing = store.ingredients.get(fi["ingredient_id"])
        if ing is None or ing["status"] != "ACTIVE":
            raise errors.ingredient_inactive()

    for fi in lines:
        pairings = [a for a in store.supplier_ingredient_approvals.values()
                    if a["ingredient_id"] == fi["ingredient_id"]
                    and a["approval_state"] == "APPROVED"]
        if not pairings:
            raise errors.unapproved_ingredient_source()
        supplier_ok = any(
            (store.suppliers.get(a["supplier_id"]) or {}).get("approval_state") == "APPROVED"
            for a in pairings
        )
        if not supplier_ok:
            raise errors.supplier_suspended()

    # Line-schedule conflict: half-open 8h windows
    my_start = batch["_scheduled_start_dt"]
    my_end = my_start + timedelta(hours=8)
    for other in store.production_batches.values():
        if other["id"] == batch["id"]:
            continue
        if other["line_id"] != batch["line_id"]:
            continue
        if other["status"] not in ("RELEASED_FOR_PRODUCTION", "IN_PROCESS"):
            continue
        o_start = other["_scheduled_start_dt"]
        o_end = o_start + timedelta(hours=8)
        # half-open [start, end) intersection
        if my_start < o_end and o_start < my_end:
            raise errors.line_schedule_conflict()

    batch["status"] = "RELEASED_FOR_PRODUCTION"
    touch(batch, status_changed=True)
    return success_object(serialize(batch), 200)


@bp.route("/production-batches/<id>/start-run", methods=["POST"])
def start_run(id):
    require_roles("LineOperator")
    batch = _get_batch(id)
    _check_batch_not_terminal(batch)
    if batch["status"] != "RELEASED_FOR_PRODUCTION":
        raise errors.invalid_state("Only RELEASED_FOR_PRODUCTION batches can start")
    batch["status"] = "IN_PROCESS"
    touch(batch, status_changed=True)
    return success_object(serialize(batch), 200)


@bp.route("/production-batches/<id>/hold", methods=["POST"])
def hold_batch(id):
    require_roles("QualityAnalyst")
    batch = _get_batch(id)
    _check_batch_not_terminal(batch)
    if batch["status"] != "IN_PROCESS":
        raise errors.invalid_state("Only IN_PROCESS batches can be held")
    batch["status"] = "ON_HOLD"
    touch(batch, status_changed=True)
    return success_object(serialize(batch), 200)


@bp.route("/production-batches/<id>/resume", methods=["POST"])
def resume_batch(id):
    require_roles("QualityAnalyst")
    batch = _get_batch(id)
    _check_batch_not_terminal(batch)
    if batch["status"] != "ON_HOLD":
        raise errors.invalid_state("Only ON_HOLD batches can be resumed")
    batch["status"] = "IN_PROCESS"
    touch(batch, status_changed=True)
    return success_object(serialize(batch), 200)


@bp.route("/production-batches/<id>/complete", methods=["POST"])
def complete_batch(id):
    user_id, role = require_roles("LineOperator", "QualityAnalyst")
    batch = _get_batch(id)
    _check_batch_not_terminal(batch)
    if batch["status"] != "IN_PROCESS":
        raise errors.invalid_state("Only IN_PROCESS batches can be completed")
    body = get_json_body()
    actual_kg = require_number(body, "actual_kg")
    if actual_kg <= 0:
        raise errors.invalid_request("actual_kg must be > 0")
    override = optional_bool(body, "override", False)

    variance = compute_yield_variance(batch["planned_kg"], actual_kg)
    if abs(variance) > YIELD_HOLD_THRESHOLD_PCT:
        if not (override and role == "QualityAnalyst"):
            raise errors.yield_variance_hold()

    batch["actual_kg"] = actual_kg
    batch["yield_variance_pct"] = variance
    batch["status"] = "COMPLETED"
    touch(batch, status_changed=True)

    formula = store.formulas.get(batch["formula_id"])
    if formula is not None:
        formula["total_batch_count"] = int(formula.get("total_batch_count", 0)) + 1

    # Optionally create first lot
    lot_fields = body.get("lot_fields")
    if lot_fields is not None:
        if not isinstance(lot_fields, dict):
            raise errors.invalid_request("lot_fields must be an object")
        _create_lot_for_batch(batch, lot_fields)

    return success_object(serialize(batch), 200)


@bp.route("/production-batches/<id>/reject", methods=["POST"])
def reject_batch(id):
    require_roles("QualityAnalyst")
    batch = _get_batch(id)
    _check_batch_not_terminal(batch)
    if batch["status"] != "ON_HOLD":
        raise errors.invalid_state("Only ON_HOLD batches can be rejected")
    batch["status"] = "REJECTED"
    touch(batch, status_changed=True)
    # Cascade: ACTIVE lots -> QUARANTINED
    for lot in store.batch_lot_codes.values():
        if lot["batch_id"] == id and lot["status"] == "ACTIVE":
            lot["status"] = "QUARANTINED"
            touch(lot, status_changed=True)
    return success_object(serialize(batch), 200)


# ---------------------------------------------------------------------------
# Lot creation helper shared by POST /lots and complete's lot_fields
# ---------------------------------------------------------------------------
def _create_lot_for_batch(batch, fields):
    packaged_units = fields.get("packaged_units")
    if isinstance(packaged_units, bool) or not isinstance(packaged_units, int):
        raise errors.invalid_request("packaged_units must be an integer")
    if packaged_units < 0:
        raise errors.invalid_request("packaged_units must be >= 0")
    best_by_raw = fields.get("best_by_date")
    best_by_dt = parse_iso(best_by_raw)
    if best_by_dt is None:
        raise errors.invalid_request("best_by_date must be a valid ISO 8601 timestamp")
    prod_dt = batch["_scheduled_start_dt"]
    if best_by_dt <= prod_dt:
        raise errors.best_by_invalid()

    lot = {
        "batch_id": batch["id"],
        "packaged_units": packaged_units,
        "best_by_date": best_by_raw if isinstance(best_by_raw, str) else best_by_dt.isoformat(),
        "status": "ACTIVE",
        "_best_by_dt": best_by_dt,
    }
    stamp_new(lot)
    lot["lot_code"] = mint_lot_code(batch)
    store.batch_lot_codes[lot["id"]] = lot
    return lot
