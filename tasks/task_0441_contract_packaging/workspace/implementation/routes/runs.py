"""ProductionRun endpoints: schedule, start, complete, checkweigh, release,
quarantine, cancel, summary, plus LotConsumption/CMR reads (PRD §3.3-§3.7)."""
from flask import Blueprint, request

import clock
import db
import errors
import response
import serializers
import util
from middleware import require_role, ALL_ROLES
from services import calc, run_svc

bp = Blueprint("runs", __name__)


# ---------------------------------------------------------------------------
# Schedule a run
# ---------------------------------------------------------------------------
@bp.route("/copack/production-runs", methods=["POST"])
@require_role("Scheduler")
def schedule_run():
    body = util.get_json_body()
    util.require_fields(body, "recipe_id", "line_id", "crew_id", "planned_units", "scheduled_start")
    recipe_id = body["recipe_id"]
    line_id = body["line_id"]
    crew_id = body["crew_id"]
    planned_units = body["planned_units"]
    scheduled_start = body["scheduled_start"]

    if not all(isinstance(v, str) for v in (recipe_id, line_id, crew_id, scheduled_start)):
        raise errors.invalid_request("recipe_id, line_id, crew_id, scheduled_start must be strings")
    if not util.is_int(planned_units):
        raise errors.invalid_request("planned_units must be an integer")

    # priority 7: body FK existence.
    recipe = db.recipes.get(recipe_id)
    if recipe is None:
        raise errors.not_found("Recipe not found")
    line = db.production_lines.get(line_id)
    if line is None:
        raise errors.not_found("Production line not found")
    crew = db.crews.get(crew_id)
    if crew is None:
        raise errors.not_found("Crew not found")

    # priority 8: planned_units > 0.
    if planned_units <= 0:
        raise errors.invalid_quantity("planned_units must be > 0")

    # scheduled_start must be a valid instant (well-formedness).
    start_dt = clock.parse_iso8601(scheduled_start)
    if start_dt is None:
        raise errors.invalid_request("scheduled_start must be a valid ISO 8601 instant")

    # priority 29: recipe must be APPROVED.
    if recipe["status"] != "APPROVED":
        raise errors.recipe_not_approved("Recipe must be APPROVED to schedule a run")

    # compute scheduled_end via project_run_window.
    end_dt = calc.project_run_window(start_dt, line, recipe, planned_units)

    # priority 25: line overlap (half-open).
    run_svc.check_line_overlap(line_id, start_dt, end_dt)
    # priority 26: crew overlap (closed, buffer-padded).
    run_svc.check_crew_overlap(crew, start_dt, end_dt)

    rec = db.new_full_record({
        "recipe_id": recipe_id,
        "line_id": line_id,
        "crew_id": crew_id,
        "planned_units": planned_units,
        "scheduled_start": clock.to_iso_millis(start_dt),
        "scheduled_end": clock.to_iso_millis(end_dt),
        "_scheduled_start_dt": start_dt,
        "_scheduled_end_dt": end_dt,
        "actual_units_good": 0,
        "actual_units_scrapped": 0,
        "lot_code": None,
        "pack_date": None,
        "_pack_date_dt": None,
        "fg_expiration_date": None,
        "run_rate_units_per_hour": None,
        "status": "SCHEDULED",
    })
    db.production_runs[rec["id"]] = rec

    # reserve material.
    run_svc.reserve_material(rec, recipe)

    return response.success(serializers.production_run(rec), status=201)


@bp.route("/copack/production-runs/<rid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_run(rid):
    rec = db.production_runs.get(rid)
    if rec is None:
        raise errors.not_found("Production run not found")
    return response.success(serializers.production_run(rec), status=200)


@bp.route("/copack/production-runs", methods=["GET"])
@require_role(*ALL_ROLES)
def list_runs():
    limit, offset = util.parse_pagination()
    recipe_id = request.args.get("recipe_id")
    line_id = request.args.get("line_id")
    crew_id = request.args.get("crew_id")
    status = request.args.get("status")
    items = list(db.production_runs.values())
    if recipe_id is not None:
        items = [r for r in items if r["recipe_id"] == recipe_id]
    if line_id is not None:
        items = [r for r in items if r["line_id"] == line_id]
    if crew_id is not None:
        items = [r for r in items if r["crew_id"] == crew_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.production_run(r) for r in window], status=200, pagination=meta)


@bp.route("/copack/production-runs/<rid>/summary", methods=["GET"])
@require_role(*ALL_ROLES)
def run_summary(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")
    recipe = db.recipes.get(run["recipe_id"])
    return response.success(run_svc.compute_summary(run, recipe), status=200)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
@bp.route("/copack/production-runs/<rid>/start", methods=["POST"])
@require_role("Scheduler")
def start_run(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")

    body = util.get_json_body()
    util.require_fields(body, "expected_line_version")
    expected_line_version = body["expected_line_version"]
    if not util.is_int(expected_line_version):
        raise errors.invalid_request("expected_line_version must be an integer")

    recipe = db.recipes.get(run["recipe_id"])
    line = db.production_lines.get(run["line_id"])
    customer = db.customers.get(recipe["customer_id"]) if recipe else None

    # priority 20: state precondition (run SCHEDULED).
    if run["status"] != "SCHEDULED":
        raise errors.invalid_state("start requires run SCHEDULED")

    # referenced recipe must still be APPROVED (priority 29 family).
    if recipe is None or recipe["status"] != "APPROVED":
        raise errors.recipe_not_approved("Recipe must be APPROVED to start a run")

    # priority 21: allergen changeover.
    run_svc.check_allergen_changeover(line, recipe)

    # priority 22 then 23: expiry, then material sufficiency (build plan).
    plan = run_svc.check_expiry_and_material(run, recipe)

    # priority 28: OCC on line version.
    if expected_line_version != line["version"]:
        raise errors.stale_version("expected_line_version does not match line version")

    # all preconditions passed -> apply atomic start cascade.
    run_svc.apply_start(run, recipe, line, customer, plan)
    return response.success(serializers.production_run(run), status=200)


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------
@bp.route("/copack/production-runs/<rid>/complete", methods=["POST"])
@require_role("Scheduler")
def complete_run(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")

    body = util.get_json_body()
    actual_good = body.get("actual_units_good", 0)
    actual_scrapped = body.get("actual_units_scrapped", 0)
    if actual_good is None:
        actual_good = 0
    if actual_scrapped is None:
        actual_scrapped = 0
    if not util.is_int(actual_good) or not util.is_int(actual_scrapped):
        raise errors.invalid_request("actual_units_good and actual_units_scrapped must be integers")
    if actual_good < 0 or actual_scrapped < 0:
        raise errors.invalid_quantity("actual unit counts must be >= 0")

    # priority 20: state precondition (run RUNNING).
    if run["status"] != "RUNNING":
        raise errors.invalid_state("complete requires run RUNNING")

    # priority 24: over-run ceiling = planned_units * (1 + 10/100).
    ceiling = run["planned_units"] * (1 + calc.OVERRUN_ALLOWANCE_PCT / 100.0)
    if (actual_good + actual_scrapped) > ceiling:
        raise errors.overrun_exceeded()

    recipe = db.recipes.get(run["recipe_id"])
    run_svc.apply_complete(run, recipe, actual_good, actual_scrapped)
    return response.success(serializers.production_run(run), status=200)


# ---------------------------------------------------------------------------
# Checkweigh samples
# ---------------------------------------------------------------------------
@bp.route("/copack/production-runs/<rid>/checkweigh-samples", methods=["POST"])
@require_role("QAInspector")
def add_checkweigh_sample(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")

    body = util.get_json_body()
    util.require_fields(body, "measured_weight_g")
    measured = body["measured_weight_g"]
    if not util.is_number(measured):
        raise errors.invalid_request("measured_weight_g must be a number")

    # priority 8: measured_weight_g > 0.
    if measured <= 0:
        raise errors.invalid_quantity("measured_weight_g must be > 0")

    # priority 29: sampling only while RUNNING or PENDING_QA.
    if run["status"] not in ("RUNNING", "PENDING_QA"):
        raise errors.recipe_not_approved("Samples may only be added while RUNNING or PENDING_QA")

    recipe = db.recipes.get(run["recipe_id"])
    verdict = calc.checkweigh_verdict(
        measured, recipe["target_fill_weight_g"], recipe["fill_tolerance_pct"])

    rec = db.new_append_record({
        "production_run_id": rid,
        "measured_weight_g": measured,
        "verdict": verdict,
    })
    db.checkweigh_samples[rec["id"]] = rec
    return response.success(serializers.checkweigh_sample(rec), status=201)


@bp.route("/copack/production-runs/<rid>/checkweigh-samples", methods=["GET"])
@require_role(*ALL_ROLES)
def list_checkweigh_samples(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")
    limit, offset = util.parse_pagination()
    items = [s for s in db.checkweigh_samples.values() if s["production_run_id"] == rid]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.checkweigh_sample(r) for r in window], status=200, pagination=meta)


# ---------------------------------------------------------------------------
# Release / Quarantine
# ---------------------------------------------------------------------------
@bp.route("/copack/production-runs/<rid>/release", methods=["POST"])
@require_role("QAInspector")
def release_run(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")

    # priority 20: state precondition (run PENDING_QA).
    if run["status"] != "PENDING_QA":
        raise errors.invalid_state("release requires run PENDING_QA")

    # priority 27: QA reject-rate gate (>=1 sample, reject_rate <= MAX).
    samples = [s for s in db.checkweigh_samples.values() if s["production_run_id"] == rid]
    if not samples:
        raise errors.qa_reject_rate_exceeded("Release requires at least one checkweigh sample")
    reject_rate = calc.checkweigh_reject_rate(samples)
    if reject_rate > calc.MAX_REJECT_RATE:
        raise errors.qa_reject_rate_exceeded()

    recipe = db.recipes.get(run["recipe_id"])
    run_svc.apply_release(run, recipe)
    return response.success(serializers.production_run(run), status=200)


@bp.route("/copack/production-runs/<rid>/quarantine", methods=["POST"])
@require_role("QAInspector")
def quarantine_run(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")
    if run["status"] != "PENDING_QA":
        raise errors.invalid_state("quarantine requires run PENDING_QA")
    run_svc.apply_quarantine(run)
    return response.success(serializers.production_run(run), status=200)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.route("/copack/production-runs/<rid>/cancel", methods=["POST"])
@require_role("Scheduler")
def cancel_run(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")
    recipe = db.recipes.get(run["recipe_id"])
    if run["status"] == "SCHEDULED":
        run_svc.apply_cancel_scheduled(run, recipe)
    elif run["status"] == "RUNNING":
        run_svc.apply_cancel_running(run, recipe)
    else:
        raise errors.invalid_state("cancel requires run SCHEDULED or RUNNING")
    return response.success(serializers.production_run(run), status=200)


# ---------------------------------------------------------------------------
# LotConsumption reads
# ---------------------------------------------------------------------------
@bp.route("/copack/production-runs/<rid>/lot-consumptions", methods=["GET"])
@require_role(*ALL_ROLES)
def list_run_lot_consumptions(rid):
    run = db.production_runs.get(rid)
    if run is None:
        raise errors.not_found("Production run not found")
    limit, offset = util.parse_pagination()
    items = [lc for lc in db.lot_consumptions.values() if lc["production_run_id"] == rid]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.lot_consumption(r) for r in window], status=200, pagination=meta)


@bp.route("/copack/lot-consumptions/<lcid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_lot_consumption(lcid):
    rec = db.lot_consumptions.get(lcid)
    if rec is None:
        raise errors.not_found("Lot consumption not found")
    return response.success(serializers.lot_consumption(rec), status=200)


@bp.route("/copack/lot-consumptions", methods=["GET"])
@require_role(*ALL_ROLES)
def list_lot_consumptions():
    limit, offset = util.parse_pagination()
    component_lot_id = request.args.get("component_lot_id")
    bom_line_id = request.args.get("bom_line_id")
    items = list(db.lot_consumptions.values())
    if component_lot_id is not None:
        items = [lc for lc in items if lc["component_lot_id"] == component_lot_id]
    if bom_line_id is not None:
        items = [lc for lc in items if lc["bom_line_id"] == bom_line_id]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.lot_consumption(r) for r in window], status=200, pagination=meta)


# ---------------------------------------------------------------------------
# CMR ledger reads
# ---------------------------------------------------------------------------
@bp.route("/copack/cmr-ledger-entries/<eid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_cmr_entry(eid):
    rec = db.cmr_ledger_entries.get(eid)
    if rec is None:
        raise errors.not_found("CMR ledger entry not found")
    return response.success(serializers.cmr_ledger_entry(rec), status=200)


@bp.route("/copack/cmr-ledger-entries", methods=["GET"])
@require_role(*ALL_ROLES)
def list_cmr_entries():
    limit, offset = util.parse_pagination()
    customer_id = request.args.get("customer_id")
    component_id = request.args.get("component_id")
    production_run_id = request.args.get("production_run_id")
    items = list(db.cmr_ledger_entries.values())
    if customer_id is not None:
        items = [e for e in items if e["customer_id"] == customer_id]
    if component_id is not None:
        items = [e for e in items if e["component_id"] == component_id]
    if production_run_id is not None:
        items = [e for e in items if e["production_run_id"] == production_run_id]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.cmr_ledger_entry(r) for r in window], status=200, pagination=meta)
