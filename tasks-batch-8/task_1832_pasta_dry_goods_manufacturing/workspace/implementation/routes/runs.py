"""ProductionRun endpoints: scheduling (OCC + changeover + overlap), hop-by-hop
advancement, abort compensation, and the independent quality dimension."""
from datetime import timedelta

from flask import Blueprint

import db
from db import new_common, new_id, num_out, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok, paginate
from services import calc
from services.cascades import (run_quality_reject_cascade,
                               run_quality_release_cascade)
from validation import fk_exists, parse_body, raw_body, require_path_entity, validate_schema

bp = Blueprint("runs", __name__)

_RUN_SCHEMA = {
    "recipe_id": ("string", True, None),
    "line_id": ("string", True, None),
    "semolina_lot_id": ("string", True, None),
    "planned_input_kg": ("number", True, None),
    "scheduled_start": ("datetime", True, None),
    "scheduled_end": ("datetime", True, None),
    "expected_line_version": ("integer", True, None),
}

_PATCH_SCHEMA = {
    "scheduled_start": ("datetime", False, None),
    "scheduled_end": ("datetime", False, None),
    "expected_run_version": ("integer", True, None),
}

_ADVANCE_SCHEMA = {
    "initial_moisture_pct": ("number", False, None),
    "actual_yield_kg": ("number", False, None),
}


@bp.post("/production-runs")
def create_run():
    get_context()
    require_roles(["ProductionOperator"])
    body = raw_body()
    # Existence (priority 4): body FKs in declared input order.
    recipe = fk_exists(store.recipes, body, "recipe_id", "ERR_RECIPE_NOT_FOUND")
    line = fk_exists(store.production_lines, body, "line_id", "ERR_LINE_NOT_FOUND")
    lot = fk_exists(store.semolina_lots, body, "semolina_lot_id", "ERR_LOT_NOT_FOUND")
    validate_schema(body, _RUN_SCHEMA)
    if db.dec(body["planned_input_kg"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "planned_input_kg must be > 0")
    scheduled_start = db.parse_datetime(body["scheduled_start"])
    scheduled_end = db.parse_datetime(body["scheduled_end"])
    # Optimistic concurrency (priority 7) precedes temporal rules (priority 9).
    if body["expected_line_version"] != line["version"]:
        raise ApiError("ERR_STALE_LINE_VERSION", 412,
                       "expected_line_version does not match the line's current version")
    if scheduled_end <= scheduled_start or scheduled_start < db.clock_now():
        raise ApiError("ERR_INVALID_SCHEDULE", 422,
                       "scheduled_end must be after scheduled_start and start must not be in the past")
    changeover = calc.compute_changeover(line["id"], recipe, scheduled_start)
    if calc.line_window_overlaps(line["id"], scheduled_start, scheduled_end, changeover):
        raise ApiError("ERR_LINE_WINDOW_OVERLAP", 409,
                       "Buffered occupancy intersects another non-ABORTED run on the line")
    # Referenced-entity state (priority 10).
    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_NOT_APPROVED", 409,
                       "Runs may only be scheduled against an APPROVED recipe")
    run = {
        "id": new_id(),
        "recipe_id": recipe["id"],
        "line_id": line["id"],
        "semolina_lot_id": lot["id"],
        "pinned_recipe_version": recipe["version"],
        "planned_input_kg": body["planned_input_kg"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "changeover_minutes": changeover,
        "gluten_free": recipe["gluten_free"],
        "brand_type": recipe["brand_type"],
        "actual_yield_kg": None,
        "actual_started_at": None,
        "completed_at": None,
        "production_status": "SCHEDULED",
        "quality_disposition": "PENDING_QA",
    }
    new_common(run)
    store.production_runs[run["id"]] = run
    touch(line)  # scheduling consumes line capacity: line.version += 1
    return created(run)


@bp.get("/production-runs")
def list_runs():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.production_runs.values())
    for field in ("recipe_id", "line_id", "semolina_lot_id",
                  "production_status", "quality_disposition"):
        rows = paginate.filter(rows, field)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/production-runs/<run_id>")
def get_run(run_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.production_runs, run_id, "ERR_RUN_NOT_FOUND"))


@bp.patch("/production-runs/<run_id>")
def reschedule_run(run_id):
    get_context()
    require_roles(["ProductionOperator"])
    run = require_path_entity(store.production_runs, run_id, "ERR_RUN_NOT_FOUND")
    body = parse_body(_PATCH_SCHEMA, allow_empty=False)
    if run["production_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SCHEDULED run can be rescheduled")
    if body["expected_run_version"] != run["version"]:
        raise ApiError("ERR_STALE_RUN_VERSION", 412,
                       "expected_run_version does not match the run's current version")
    new_start = (db.parse_datetime(body["scheduled_start"])
                 if "scheduled_start" in body else run["scheduled_start"])
    new_end = (db.parse_datetime(body["scheduled_end"])
               if "scheduled_end" in body else run["scheduled_end"])
    if new_end <= new_start or new_start < db.clock_now():
        raise ApiError("ERR_INVALID_SCHEDULE", 422,
                       "scheduled_end must be after scheduled_start and start must not be in the past")
    recipe = store.recipes[run["recipe_id"]]
    changeover = calc.compute_changeover(run["line_id"], recipe, new_start,
                                         exclude_run_id=run["id"])
    if calc.line_window_overlaps(run["line_id"], new_start, new_end, changeover,
                                 exclude_run_id=run["id"]):
        raise ApiError("ERR_LINE_WINDOW_OVERLAP", 409,
                       "Buffered occupancy intersects another non-ABORTED run on the line")
    run["scheduled_start"] = new_start
    run["scheduled_end"] = new_end
    run["changeover_minutes"] = changeover
    touch(run)
    return ok(run)


# ------------------------------------------------------------------ advance --
def _hop_mixing(run, recipe, lot, line):
    # Safety (priority 8) -> temporal (9) -> referential (10) -> fiscal (12).
    if run["gluten_free"] and line["gluten_posture"] != "GF_VALIDATED":
        raise ApiError("ERR_GF_SEGREGATION_VIOLATION", 409,
                       "Gluten-free run requires a GF_VALIDATED line")
    earliest = run["scheduled_start"] - timedelta(minutes=run["changeover_minutes"])
    if db.clock_now() < earliest:
        raise ApiError("ERR_INVALID_SCHEDULE", 422,
                       "Cannot advance to MIXING before scheduled_start - changeover_minutes")
    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_NOT_APPROVED", 409,
                       "Recipe is no longer APPROVED")
    if recipe["version"] != run["pinned_recipe_version"]:
        raise ApiError("ERR_RECIPE_REVISION_STALE", 409,
                       "Recipe version has advanced beyond the run's pinned_recipe_version")
    if lot["status"] != "ACCEPTED":
        raise ApiError("ERR_LOT_NOT_ACCEPTED", 409,
                       "Semolina lot is not ACCEPTED")
    for ingredient in store.recipe_ingredients.values():
        if (ingredient["recipe_id"] == recipe["id"]
                and ingredient["ingredient_type"] == "SEMOLINA"
                and ingredient["min_protein_pct"] is not None
                and db.dec(lot["lab_protein_pct"]) < db.dec(ingredient["min_protein_pct"])):
            raise ApiError("ERR_LOT_QUALITY_INSUFFICIENT", 422,
                           "Lot lab protein below the recipe's min_protein_pct")
    if db.dec(lot["remaining_weight_kg"]) < db.dec(run["planned_input_kg"]):
        raise ApiError("ERR_INSUFFICIENT_LOT_WEIGHT", 402,
                       "Lot remaining_weight_kg does not cover planned_input_kg")
    run["production_status"] = "MIXING"
    run["actual_started_at"] = db.clock_now()
    remaining = db.dec(lot["remaining_weight_kg"]) - db.dec(run["planned_input_kg"])
    lot["remaining_weight_kg"] = num_out(remaining)
    lot["consumed_kg"] = num_out(db.dec(lot["consumed_kg"]) + db.dec(run["planned_input_kg"]))
    if remaining == 0:
        lot["status"] = "DEPLETED"
    touch(lot)
    touch(run)


def _hop_extruding(run, recipe, line):
    die = calc._mounted_die(run["line_id"])
    if die is None:
        raise ApiError("ERR_DIE_NOT_MOUNTED", 409,
                       "No MOUNTED die on the run's line")
    if die["shape_family"] != recipe["shape_family"]:
        raise ApiError("ERR_DIE_SHAPE_MISMATCH", 409,
                       "Mounted die shape_family does not match the recipe")
    die["extruded_kg"] = num_out(db.dec(die["extruded_kg"]) + db.dec(run["planned_input_kg"]))
    touch(die)
    if not run["gluten_free"] and line["gluten_posture"] != "GLUTEN_EXPOSED":
        line["gluten_posture"] = "GLUTEN_EXPOSED"
        touch(line)
    run["production_status"] = "EXTRUDING"
    touch(run)


def _hop_drying(run, recipe, body):
    if "initial_moisture_pct" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "initial_moisture_pct is required on the EXTRUDING -> DRYING hop")
    initial = body["initial_moisture_pct"]
    if (recipe["drying_curve"] == "HIGH_TEMP"
            and db.dec(initial) > calc.CRACK_RISK_MOISTURE):
        raise ApiError("ERR_CRACK_RISK", 422,
                       "HIGH_TEMP curve rejects initial_moisture_pct above 32.0")
    run["production_status"] = "DRYING"
    touch(run)
    session = {
        "id": new_id(),
        "run_id": run["id"],
        "drying_curve": recipe["drying_curve"],
        "initial_moisture_pct": initial,
        "target_moisture_pct": recipe["target_moisture_pct"],
        "redry_count": 0,
        "required_hours": calc.CURVE_TOTAL_HOURS[recipe["drying_curve"]],
        "drying_started_at": db.clock_now(),
        "latest_inline_moisture_pct": None,
        "latest_lab_moisture_pct": None,
        "status": "IN_PROGRESS",
    }
    new_common(session)
    store.drying_sessions[session["id"]] = session


def _hop_packaging(run, recipe, body):
    if "actual_yield_kg" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "actual_yield_kg is required on the DRYING -> PACKAGING hop")
    actual = body["actual_yield_kg"]
    if db.dec(actual) <= 0 or db.dec(actual) > db.dec(run["planned_input_kg"]):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "actual_yield_kg must be > 0 and <= planned_input_kg")
    session = drying_session_for(run["id"])
    if session is None or session["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Drying session must be CONFIRMED before packaging")
    run["production_status"] = "PACKAGING"
    run["actual_yield_kg"] = actual
    touch(run)
    plan = calc.case_plan(actual, recipe, run["brand_type"])
    job = {
        "id": new_id(),
        "run_id": run["id"],
        "status": "CREATED",
        "actual_yield_kg": actual,
        "total_units": plan["total_units"],
        "units_per_case": plan["units_per_case"],
        "full_case_count": plan["full_case_count"],
        "partial_case_count": plan["partial_case_count"],
        "scrapped_units": plan["scrapped_units"],
        "case_count": plan["case_count"],
        "pallet_count": plan["pallet_count"],
        "labels_verified_by_user_id": None,
    }
    new_common(job)
    store.packaging_jobs[job["id"]] = job


def _hop_completed(run, recipe):
    job = packaging_job_for(run["id"])
    if job is None or job["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Packaging job must be COMPLETED before the run completes")
    run["production_status"] = "COMPLETED"
    run["completed_at"] = db.clock_now()
    touch(run)
    production_date = db.clock_today()
    expiry_date = production_date + timedelta(days=recipe["shelf_life_days"])
    for lot in store.finished_goods_lots.values():
        if lot["run_id"] == run["id"]:
            lot["production_date"] = production_date
            lot["expiry_date"] = expiry_date
            touch(lot)


def drying_session_for(run_id):
    for session in store.drying_sessions.values():
        if session["run_id"] == run_id:
            return session
    return None


def packaging_job_for(run_id):
    for job in store.packaging_jobs.values():
        if job["run_id"] == run_id:
            return job
    return None


@bp.post("/production-runs/<run_id>/advance")
def advance_run(run_id):
    get_context()
    require_roles(["ProductionOperator"])
    run = require_path_entity(store.production_runs, run_id, "ERR_RUN_NOT_FOUND")
    body = parse_body(_ADVANCE_SCHEMA)
    status = run["production_status"]
    if status not in ("SCHEDULED", "MIXING", "EXTRUDING", "DRYING", "PACKAGING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No advance transition exists from %s" % status)
    recipe = store.recipes[run["recipe_id"]]
    lot = store.semolina_lots[run["semolina_lot_id"]]
    line = store.production_lines[run["line_id"]]
    if status == "SCHEDULED":
        _hop_mixing(run, recipe, lot, line)
    elif status == "MIXING":
        _hop_extruding(run, recipe, line)
    elif status == "EXTRUDING":
        _hop_drying(run, recipe, body)
    elif status == "DRYING":
        _hop_packaging(run, recipe, body)
    else:  # PACKAGING
        _hop_completed(run, recipe)
    return ok(run)


@bp.post("/production-runs/<run_id>/abort")
def abort_run(run_id):
    get_context()
    require_roles(["ProductionOperator"])
    run = require_path_entity(store.production_runs, run_id, "ERR_RUN_NOT_FOUND")
    source = run["production_status"]
    if source in ("COMPLETED", "ABORTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Terminal runs cannot be aborted")
    if source == "PACKAGING":
        job = packaging_job_for(run["id"])
        if job is not None and job["status"] == "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Packaging job already COMPLETED; complete the run instead")
    run["production_status"] = "ABORTED"
    touch(run)
    if source == "SCHEDULED":
        line = store.production_lines[run["line_id"]]
        touch(line)  # schedule released
    elif source == "MIXING":
        lot = store.semolina_lots[run["semolina_lot_id"]]
        lot["remaining_weight_kg"] = num_out(
            db.dec(lot["remaining_weight_kg"]) + db.dec(run["planned_input_kg"]))
        lot["consumed_kg"] = num_out(
            db.dec(lot["consumed_kg"]) - db.dec(run["planned_input_kg"]))
        if lot["status"] == "DEPLETED":
            lot["status"] = "ACCEPTED"
        touch(lot)
    elif source == "PACKAGING":
        job = packaging_job_for(run["id"])
        if job is not None and job["status"] in ("CREATED", "LABEL_VERIFIED", "BLOCKED"):
            job["status"] = "CANCELLED"
            touch(job)
    # EXTRUDING: no refund (material already extruded).
    # DRYING: the session is orphaned in place and is not reusable.
    return ok(run)


# ------------------------------------------------------ quality dimension ----
@bp.post("/production-runs/<run_id>/quality-hold")
def quality_hold(run_id):
    get_context()
    require_roles(["QAManager"])
    run = require_path_entity(store.production_runs, run_id, "ERR_RUN_NOT_FOUND")
    if run["quality_disposition"] != "PENDING_QA":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PENDING_QA run can be held")
    run["quality_disposition"] = "HELD"
    touch(run)
    return ok(run)


@bp.post("/production-runs/<run_id>/quality-release")
def quality_release(run_id):
    get_context()
    require_roles(["QAManager"])
    run = require_path_entity(store.production_runs, run_id, "ERR_RUN_NOT_FOUND")
    if run["quality_disposition"] not in ("PENDING_QA", "HELD"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PENDING_QA or HELD run can be quality-released")
    if run["production_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Quality release requires production_status COMPLETED")
    if run["gluten_free"]:
        verified_pass = any(
            t for t in store.gluten_tests.values()
            if t["test_type"] == "PRODUCT_TEST" and t["run_id"] == run["id"]
            and t["status"] == "VERIFIED" and t["result"] == "PASS")
        if not verified_pass:
            raise ApiError("ERR_GLUTEN_TEST_REQUIRED", 409,
                           "Gluten-free run requires a VERIFIED PASS product test")
    run["quality_disposition"] = "RELEASED"
    touch(run)
    run_quality_release_cascade(run)
    return ok(run)


@bp.post("/production-runs/<run_id>/quality-reject")
def quality_reject(run_id):
    get_context()
    require_roles(["QAManager"])
    run = require_path_entity(store.production_runs, run_id, "ERR_RUN_NOT_FOUND")
    if run["quality_disposition"] not in ("PENDING_QA", "HELD"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PENDING_QA or HELD run can be quality-rejected")
    run["quality_disposition"] = "REJECTED"
    touch(run)
    run_quality_reject_cascade(run)
    return ok(run)
