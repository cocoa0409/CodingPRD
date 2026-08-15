"""Kit endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, touch, paginate, sort_by_created, serialize,
)

bp = Blueprint("kits", __name__)

GET_KIT_ROLES = ("PlatformAdmin", "ProgramManager", "WarehouseOperator", "LogisticsCoordinator", "ClaimsAdjuster")
LIST_KIT_BY_RUN_ROLES = ("PlatformAdmin", "ProgramManager", "WarehouseOperator", "ProductionPlanner")
LIST_KIT_BY_STORE_ROLES = ("PlatformAdmin", "ProgramManager", "WarehouseOperator", "LogisticsCoordinator")


def _get_kit_or_404(kit_id):
    k = db.kits.get(kit_id)
    if not k:
        raise errors.err_not_found("Kit not found")
    return k


@bp.route("/pop/kits", methods=["POST"])
@require_roles("WarehouseOperator")
def create_kit():
    body = request.get_json(silent=True) or {}
    production_run_id = require_string(body, "production_run_id")
    store_id = require_string(body, "store_id")

    if not db.production_runs.get(production_run_id):
        raise errors.err_not_found("Production run not found")
    if not db.stores.get(store_id):
        raise errors.err_not_found("Store not found")

    for k in db.kits.values():
        if k["production_run_id"] == production_run_id and k["store_id"] == store_id:
            raise errors.err_duplicate("A kit already exists for this run and store")

    kit = new_common_fields()
    kit.update({
        "production_run_id": production_run_id,
        "store_id": store_id,
        "status": "PENDING",
    })
    db.kits[kit["id"]] = kit
    return response.success_object(serialize(kit), 201)


@bp.route("/pop/kits/<kit_id>", methods=["GET"])
def get_kit(kit_id):
    _, role = get_auth()
    if role not in GET_KIT_ROLES:
        raise errors.err_unauthorized()
    kit = _get_kit_or_404(kit_id)
    return response.success_object(serialize(kit), 200)


@bp.route("/pop/production-runs/<run_id>/kits", methods=["GET"])
def list_run_kits(run_id):
    _, role = get_auth()
    if role not in LIST_KIT_BY_RUN_ROLES:
        raise errors.err_unauthorized()
    if not db.production_runs.get(run_id):
        raise errors.err_not_found("Production run not found")
    items = sort_by_created([k for k in db.kits.values() if k["production_run_id"] == run_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(k) for k in page], limit, offset, total)


@bp.route("/pop/stores/<store_id>/kits", methods=["GET"])
def list_store_kits(store_id):
    _, role = get_auth()
    if role not in LIST_KIT_BY_STORE_ROLES:
        raise errors.err_unauthorized()
    if not db.stores.get(store_id):
        raise errors.err_not_found("Store not found")
    items = sort_by_created([k for k in db.kits.values() if k["store_id"] == store_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(k) for k in page], limit, offset, total)


@bp.route("/pop/kits/<kit_id>/mark-kitted", methods=["POST"])
@require_roles("WarehouseOperator")
def mark_kitted(kit_id):
    kit = _get_kit_or_404(kit_id)
    if kit["status"] != "PENDING":
        raise errors.err_invalid_state("Kit is not in PENDING")
    run = db.production_runs.get(kit["production_run_id"])
    if not run or run["status"] != "PRODUCED":
        raise errors.err_invalid_state("Parent run is not in PRODUCED")
    kit["status"] = "KITTED"
    touch(kit)
    return response.success_object(serialize(kit), 200)
