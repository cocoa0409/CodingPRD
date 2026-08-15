"""RepairCrew endpoints."""
from flask import Blueprint, request

import db
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import load_crew
from validate import (get_body, opt_bool, pagination_params, paginate, req_int,
                      req_str, sort_by_creation)

bp = Blueprint("crews", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/repair-crews", methods=["POST"])
@require_roles("SystemAdmin")
def create_crew(user_id, role):
    body = get_body()
    territory_id = req_str(body, "territory_id")
    rec = domain.new_record(common_fields=True)
    rec.update({
        "crew_code": req_str(body, "crew_code"),
        "territory_id": territory_id,
        "hourly_rate_cents": req_int(body, "hourly_rate_cents"),
        "is_active": opt_bool(body, "is_active", True),
    })
    if territory_id not in db.territories:
        raise ApiError("ERR_TERRITORY_NOT_FOUND", "Territory not found", 404)
    db.crews[rec["id"]] = rec
    return response.success(domain.ser_crew(rec), 201)


@bp.route("/gas-ops/repair-crews", methods=["GET"])
@require_roles(*ALL)
def list_crews(user_id, role):
    limit, offset = pagination_params()
    items = sort_by_creation(db.crews.values())
    territory_id = request.args.get("territory_id")
    if territory_id is not None:
        items = [c for c in items if c["territory_id"] == territory_id]
    page, total = paginate([domain.ser_crew(c) for c in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/repair-crews/<crewId>", methods=["GET"])
@require_roles(*ALL)
def get_crew(crewId, user_id, role):
    return response.success(domain.ser_crew(load_crew(crewId)), 200)


@bp.route("/gas-ops/repair-crews/<cid>/repair-work-orders", methods=["GET"])
@require_roles(*ALL)
def list_crew_work_orders(cid, user_id, role):
    load_crew(cid)
    limit, offset = pagination_params()
    items = sort_by_creation([w for w in db.work_orders.values() if w["crew_id"] == cid])
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, total = paginate([domain.ser_work_order(w) for w in items], limit, offset)
    return response.success_list(page, limit, offset, total)
