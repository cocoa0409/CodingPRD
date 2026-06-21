"""WeightTicket read endpoints (PRD §3.5). Creation is via /service-orders/{id}/weigh-in."""
from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    serialize, paginate, sort_by_created, get_weight_ticket_or_404,
)

bp = Blueprint("weight_tickets", __name__)

_ROLES = {"FieldTechnician", "PlantOperator", "ComplianceOfficer"}


@bp.get("/weight-tickets/<ticket_id>")
def get_weight_ticket(ticket_id):
    _, role = get_auth()
    require_role(role, _ROLES)
    t = get_weight_ticket_or_404(ticket_id)
    return object_response(serialize(t), 200)


@bp.get("/weight-tickets")
def list_weight_tickets():
    _, role = get_auth()
    require_role(role, _ROLES)
    items = list(db.weight_tickets.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [t for t in items if t["order_id"] == order_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(t) for t in page], limit, offset, total, 200)
