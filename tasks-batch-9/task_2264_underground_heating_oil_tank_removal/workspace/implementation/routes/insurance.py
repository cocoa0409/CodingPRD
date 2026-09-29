"""Insurance notifications and the reserve waterfall."""

from flask import Blueprint

import calculations as calc
from db import create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, opt_id, pagination, req_enum,
                        resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("insurance", __name__)

READ_ROLES = ("ProjectCoordinator", "LicensedSiteProfessional", "ComplianceOfficer")


@bp.post("/insurance-notifications")
def create_notification():
    authenticate(("ComplianceOfficer",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")
    kind = req_enum(payload, "notification_kind", calc.NOTIFICATION_KINDS)

    prop = svc.property_of(project)
    notification = create("insurance_notifications", {
        "tank_project_id": project["id"],
        "notification_kind": kind,
        "carrier_code": prop["insurance_carrier_code"] if prop else None,
        "notified_at": db.now(),
        "first_party_allocated_cents": 0,
        "third_party_allocated_cents": 0,
        "homeowner_out_of_pocket_cents": 0,
        "reserve_amount_cents": 0,
        "status": "OPEN",
    })
    svc.run_waterfall(project)
    return entity_response(notification, 201)


@bp.get("/insurance-notifications")
def list_notifications():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    project_id = filter_arg("tank_project_id")
    kind = filter_arg("notification_kind")
    status = filter_arg("status")
    rows = list(db.insurance_notifications.values())
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if kind is not None:
        rows = [r for r in rows if r["notification_kind"] == kind]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/insurance-notifications/<notification_id>")
def read_notification(notification_id):
    authenticate(READ_ROLES)
    return entity_response(resolve("insurance_notifications", notification_id))
