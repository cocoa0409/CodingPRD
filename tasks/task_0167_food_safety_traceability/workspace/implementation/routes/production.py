"""Production-run and consumed-lot endpoints (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth
from response import ok_object, ok_array
from services.common import (
    get_json_body, require_fields, require_str, require_number, require_int,
    parse_pagination, created_sort_key, paginate, fmt_dt, parse_dt,
)
from services.entities import (
    base_fields, touch, get_facility_or_404, get_ingredient_or_404,
    get_run_or_404, get_consumed_lot_or_404, get_lot_or_404,
)
from services.serialize import public
from services.production import finalize_run

bp = Blueprint("production", __name__)


@bp.post("/traceability/production-runs")
def open_run():
    require_auth(["ProductionOperator"])
    body = get_json_body()
    require_fields(body, ["facility_id", "ingredient_id", "planned_output_qty"])
    facility_id = require_str(body, "facility_id")
    ingredient_id = require_str(body, "ingredient_id")
    planned_output_qty = require_number(body, "planned_output_qty", positive=True)

    facility = db.facilities.get(facility_id)
    if facility is None:
        raise err("ERR_FACILITY_NOT_FOUND", "Facility not found")
    ingredient = db.ingredients.get(ingredient_id)
    if ingredient is None:
        raise err("ERR_INGREDIENT_NOT_FOUND", "Ingredient not found")
    if ingredient["facility_id"] != facility_id:
        raise err("ERR_CROSS_FACILITY_REFERENCE", "Ingredient belongs to a different facility")

    rec = base_fields(common=True)
    rec.update({
        "facility_id": facility_id,
        "ingredient_id": ingredient_id,
        "planned_output_qty": planned_output_qty,
        "output_lot_id": None,
        "started_at": facility["current_utc"],
        "status": "OPEN",
    })
    db.production_runs[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/traceability/production-runs/<rid>")
def get_run(rid):
    require_auth(["QualityManager", "ProductionOperator", "SafetyAuditor"])
    rec = get_run_or_404(rid)
    return ok_object(public(rec), 200)


@bp.get("/traceability/production-runs")
def list_runs():
    require_auth(["QualityManager", "ProductionOperator", "SafetyAuditor"])
    items = list(db.production_runs.values())
    facility_id = request.args.get("facility_id")
    ingredient_id = request.args.get("ingredient_id")
    output_lot_id = request.args.get("output_lot_id")
    if facility_id is not None:
        items = [x for x in items if x["facility_id"] == facility_id]
    if ingredient_id is not None:
        items = [x for x in items if x["ingredient_id"] == ingredient_id]
    if output_lot_id is not None:
        items = [x for x in items if x.get("output_lot_id") == output_lot_id]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.post("/traceability/production-runs/<rid>/consumed-lots")
def add_consumed_lot(rid):
    require_auth(["ProductionOperator"])
    run = get_run_or_404(rid)
    body = get_json_body()
    require_fields(body, ["source_lot_id", "quantity"])
    source_lot_id = require_str(body, "source_lot_id")
    quantity = require_number(body, "quantity", positive=True)

    # FK resolution + same-facility ownership (priority 5).
    source_lot = db.lots.get(source_lot_id)
    if source_lot is None:
        raise err("ERR_LOT_NOT_FOUND", "Source lot not found")
    if source_lot["facility_id"] != run["facility_id"]:
        raise err("ERR_CROSS_FACILITY_REFERENCE", "Source lot belongs to a different facility")

    # state (priority 8): a line may be added only while the run is OPEN.
    if run["status"] != "OPEN":
        raise err("ERR_RUN_NOT_OPEN", "Run is not OPEN")

    rec = base_fields(common=True)
    rec.update({
        "production_run_id": rid,
        "source_lot_id": source_lot_id,
        "quantity": quantity,
    })
    db.consumed_lots[rec["id"]] = rec

    # Each added line increments the run's version by 1.
    touch(run)

    return ok_object(public(rec), 201)


@bp.get("/traceability/consumed-lots/<clid>")
def get_consumed_lot(clid):
    require_auth(["QualityManager", "ProductionOperator", "SafetyAuditor"])
    rec = get_consumed_lot_or_404(clid)
    return ok_object(public(rec), 200)


@bp.get("/traceability/consumed-lots")
def list_consumed_lots():
    require_auth(["QualityManager", "ProductionOperator", "SafetyAuditor"])
    items = list(db.consumed_lots.values())
    production_run_id = request.args.get("production_run_id")
    source_lot_id = request.args.get("source_lot_id")
    if production_run_id is not None:
        items = [x for x in items if x["production_run_id"] == production_run_id]
    if source_lot_id is not None:
        items = [x for x in items if x["source_lot_id"] == source_lot_id]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.post("/traceability/production-runs/<rid>/finalize")
def finalize(rid):
    require_auth(["ProductionOperator"])
    run = get_run_or_404(rid)
    body = get_json_body()
    require_fields(body, ["expected_production_run_version"])
    expected = require_int(body, "expected_production_run_version")

    # priority 7: OCC version check — before all other finalize preconditions.
    if expected != run["version"]:
        raise err("ERR_STALE_VERSION", "expected_production_run_version does not match")

    # priority 8: run must be OPEN.
    if run["status"] != "OPEN":
        raise err("ERR_RUN_NOT_OPEN", "Run is not OPEN")

    facility = db.facilities[run["facility_id"]]
    finalize_run(run, facility)
    return ok_object(public(run), 200)


@bp.post("/traceability/production-runs/<rid>/abort")
def abort(rid):
    require_auth(["ProductionOperator"])
    run = get_run_or_404(rid)
    if run["status"] != "OPEN":
        raise err("ERR_RUN_NOT_OPEN", "Run is not OPEN")
    run["status"] = "ABORTED"
    touch(run)
    return ok_object(public(run), 200)
