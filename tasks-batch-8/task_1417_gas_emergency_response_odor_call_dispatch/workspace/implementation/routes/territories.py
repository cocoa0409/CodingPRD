"""ServiceTerritory endpoints."""
from flask import Blueprint, request

import db
import domain
import response
from auth import require_roles
from routes.common import incident_visible, load_territory
from validate import (get_body, pagination_params, paginate, req_int, req_str,
                      sort_by_creation)

bp = Blueprint("territories", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/territories", methods=["POST"])
@require_roles("SystemAdmin")
def create_territory(user_id, role):
    body = get_body()
    name = req_str(body, "name")
    rec = domain.new_record(common_fields=True)
    rec.update({
        "name": name,
        "p1_threshold_minutes": req_int(body, "p1_threshold_minutes"),
        "p2_threshold_minutes": req_int(body, "p2_threshold_minutes"),
        "p3_threshold_minutes": req_int(body, "p3_threshold_minutes"),
        "p4_threshold_minutes": req_int(body, "p4_threshold_minutes"),
        "recurrence_window_hours": req_int(body, "recurrence_window_hours"),
        "repair_budget_cap_cents": req_int(body, "repair_budget_cap_cents"),
    })
    db.territories[rec["id"]] = rec
    return response.success(domain.ser_territory(rec), 201)


@bp.route("/gas-ops/territories", methods=["GET"])
@require_roles(*ALL)
def list_territories(user_id, role):
    limit, offset = pagination_params()
    items = sort_by_creation(db.territories.values())
    page, total = paginate([domain.ser_territory(t) for t in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/territories/<territoryId>", methods=["GET"])
@require_roles(*ALL)
def get_territory(territoryId, user_id, role):
    return response.success(domain.ser_territory(load_territory(territoryId)), 200)


@bp.route("/gas-ops/territories/<tid>/incidents", methods=["GET"])
@require_roles(*ALL)
def list_territory_incidents(tid, user_id, role):
    load_territory(tid)
    limit, offset = pagination_params()
    items = [i for i in db.incidents.values() if i["territory_id"] == tid]
    lifecycle = request.args.get("lifecycle_status")
    priority = request.args.get("priority")
    if lifecycle is not None:
        items = [i for i in items if i["lifecycle_status"] == lifecycle]
    if priority is not None:
        items = [i for i in items if i["priority"] == priority]
    items = [i for i in sort_by_creation(items) if incident_visible(i, role, user_id)]
    page, total = paginate([domain.ser_incident(i) for i in items], limit, offset)
    return response.success_list(page, limit, offset, total)
