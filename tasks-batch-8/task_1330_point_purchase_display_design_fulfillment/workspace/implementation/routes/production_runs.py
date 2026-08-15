"""ProductionRun endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, require_number, touch, paginate,
    sort_by_created, serialize, compute_production_quantity, compute_unit_cost_cents,
    capture_provisional_roi,
)

bp = Blueprint("production_runs", __name__)

GET_RUN_ROLES = ("PlatformAdmin", "ProgramManager", "ProductionPlanner", "WarehouseOperator")
LIST_RUN_ROLES = ("PlatformAdmin", "ProgramManager", "ProductionPlanner")


def _get_run_or_404(run_id):
    r = db.production_runs.get(run_id)
    if not r:
        raise errors.err_not_found("Production run not found")
    return r


@bp.route("/pop/production-runs", methods=["POST"])
@require_roles("ProductionPlanner")
def create_run():
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    design_id = require_string(body, "design_id")
    overage_pct = require_number(body, "overage_pct")
    if overage_pct < 0:
        raise errors.err_invalid_request("overage_pct must be >= 0")

    program = db.programs.get(program_id)
    if not program:
        raise errors.err_not_found("Program not found")
    design = db.designs.get(design_id)
    if not design:
        raise errors.err_not_found("Design not found")

    if design["status"] != "APPROVED":
        raise errors.err_referential("Referenced design is not APPROVED")

    # OCC: expected_program_version (checked after state/referential per priority order)
    expected = body.get("expected_program_version")
    if expected is not None:
        if expected != program["version"]:
            raise errors.err_stale_version("expected_program_version does not match current program version")

    run = new_common_fields()
    run.update({
        "program_id": program_id,
        "design_id": design_id,
        "overage_pct": overage_pct,
        "production_quantity": None,
        "unit_cost_cents": None,
        "total_cost_cents": None,
        "status": "PLANNED",
    })
    db.production_runs[run["id"]] = run
    # Creating a run advances the parent program's version
    touch(program)
    return response.success_object(serialize(run), 201)


@bp.route("/pop/production-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    _, role = get_auth()
    if role not in GET_RUN_ROLES:
        raise errors.err_unauthorized()
    run = _get_run_or_404(run_id)
    return response.success_object(serialize(run), 200)


@bp.route("/pop/programs/<program_id>/production-runs", methods=["GET"])
def list_program_runs(program_id):
    _, role = get_auth()
    if role not in LIST_RUN_ROLES:
        raise errors.err_unauthorized()
    if not db.programs.get(program_id):
        raise errors.err_not_found("Program not found")
    items = sort_by_created([r for r in db.production_runs.values() if r["program_id"] == program_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/pop/designs/<design_id>/production-runs", methods=["GET"])
def list_design_runs(design_id):
    _, role = get_auth()
    if role not in LIST_RUN_ROLES:
        raise errors.err_unauthorized()
    if not db.designs.get(design_id):
        raise errors.err_not_found("Design not found")
    items = sort_by_created([r for r in db.production_runs.values() if r["design_id"] == design_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/pop/production-runs/<run_id>/authorize", methods=["POST"])
@require_roles("ProductionPlanner")
def authorize_run(run_id):
    run = _get_run_or_404(run_id)
    if run["status"] != "PLANNED":
        raise errors.err_invalid_state("Run is not in PLANNED")
    program = db.programs.get(run["program_id"])
    if not program or program["status"] != "PRODUCTION":
        raise errors.err_invalid_state("Parent program is not in PRODUCTION")
    design = db.designs.get(run["design_id"])
    if not design or design["status"] != "APPROVED":
        raise errors.err_invalid_state("Referenced design is not APPROVED")

    qty = compute_production_quantity(program["store_count"], run["overage_pct"])
    unit_cost = compute_unit_cost_cents(qty)
    run["production_quantity"] = qty
    run["unit_cost_cents"] = unit_cost
    run["total_cost_cents"] = qty * unit_cost
    run["status"] = "AUTHORIZED"
    touch(run)
    return response.success_object(serialize(run), 200)


@bp.route("/pop/production-runs/<run_id>/mark-produced", methods=["POST"])
@require_roles("ProductionPlanner")
def mark_produced(run_id):
    run = _get_run_or_404(run_id)
    if run["status"] != "AUTHORIZED":
        raise errors.err_invalid_state("Run is not in AUTHORIZED")
    run["status"] = "PRODUCED"
    touch(run)
    # Cascade: one Kit (PENDING) per Store of the parent program
    program_stores = [s for s in db.stores.values() if s["program_id"] == run["program_id"]]
    for store in sort_by_created(program_stores):
        kit = new_common_fields()
        kit.update({
            "production_run_id": run_id,
            "store_id": store["id"],
            "status": "PENDING",
        })
        db.kits[kit["id"]] = kit
    # Capture provisional ROI at first PRODUCED run
    program = db.programs.get(run["program_id"])
    if program:
        capture_provisional_roi(program)
    return response.success_object(serialize(run), 200)


@bp.route("/pop/production-runs/<run_id>/cancel", methods=["POST"])
@require_roles("ProductionPlanner")
def cancel_run(run_id):
    run = _get_run_or_404(run_id)
    if run["status"] != "PLANNED":
        raise errors.err_invalid_state("Run is not in PLANNED")
    run["status"] = "CANCELLED"
    touch(run)
    return response.success_object(serialize(run), 200)
