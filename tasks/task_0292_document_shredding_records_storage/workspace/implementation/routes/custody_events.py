"""CustodyEvent read endpoints (PRD §3.4). Append-only; created by order transitions."""
from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    serialize, paginate, sort_by_created, get_custody_event_or_404,
)

bp = Blueprint("custody_events", __name__)

_ROLES = {"FieldTechnician", "PlantOperator", "DestructionWitness", "ComplianceOfficer"}


@bp.get("/custody-events/<event_id>")
def get_custody_event(event_id):
    _, role = get_auth()
    require_role(role, _ROLES)
    e = get_custody_event_or_404(event_id)
    return object_response(serialize(e), 200)


@bp.get("/custody-events")
def list_custody_events():
    _, role = get_auth()
    require_role(role, _ROLES)
    items = list(db.custody_events.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [e for e in items if e["order_id"] == order_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(e) for e in page], limit, offset, total, 200)
