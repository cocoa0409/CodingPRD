"""ServiceTicket endpoints (scaffold §1.5; lifecycle per PRD §3.8)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role, require_operator_ownership
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_array, req_enum, stamp_new, touch
from errors import (
    ApiError, ERR_LOCATION_NOT_FOUND, ERR_SERVICE_TICKET_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INVALID_QUANTITY, ERR_TICKET_NOT_OPEN,
    ERR_TICKET_NOT_SCHEDULED, ERR_OPERATOR_NOT_ACTIVE, ERR_DATE_NOT_FUTURE,
)
import clock

bp = Blueprint("service_tickets", __name__)

ISSUE_TYPES = {"PART_REPLACEMENT", "REPAIR", "PREVENTIVE"}


def view(t):
    return {k: v for k, v in t.items()}


@bp.post("/wholesale/service-tickets")
def create_ticket():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["OperatorManager"])
    location_id = req_string(body, "location_id")
    equipment_model = req_string(body, "equipment_model")
    issue_type = req_enum(body, "issue_type", ISSUE_TYPES)
    parts = req_array(body, "parts")
    clean_parts = []
    parts_total = 0
    for row in parts:
        if not isinstance(row, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "parts rows must be objects")
        part_sku = row.get("part_sku")
        if not isinstance(part_sku, str) or not part_sku:
            raise ApiError(ERR_INVALID_REQUEST, 400, "parts[].part_sku required")
        part_name = row.get("part_name")
        if not isinstance(part_name, str) or not part_name:
            raise ApiError(ERR_INVALID_REQUEST, 400, "parts[].part_name required")
        qty = row.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError(ERR_INVALID_QUANTITY, 400, "parts[].quantity must be a positive integer")
        unit_price = row.get("unit_price_cents")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "parts[].unit_price_cents must be a non-negative integer")
        clean_parts.append({
            "part_sku": part_sku,
            "part_name": part_name,
            "quantity": qty,
            "unit_price_cents": unit_price,
        })
        parts_total += qty * unit_price
    location = db.locations.get(location_id)
    if location is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, 404, "Location id does not exist")
    require_operator_ownership(role, user_id, location["operator_id"])
    ticket = stamp_new({
        "location_id": location_id,
        "equipment_model": equipment_model,
        "issue_type": issue_type,
        "parts": clean_parts,
        "parts_total_cents": parts_total,
        "service_date": None,
        "status": "OPEN",
    })
    db.service_tickets[ticket["id"]] = ticket
    return success_object(view(ticket), 201)


@bp.get("/wholesale/service-tickets")
def list_tickets():
    get_auth()
    limit, offset = parse_pagination(request.args)
    loc_f = request.args.get("location_id")
    items = list(db.service_tickets.values())
    if loc_f is not None:
        items = [t for t in items if t["location_id"] == loc_f]
    items.sort(key=lambda t: t["created_at"])
    total = len(items)
    return success_list([view(t) for t in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/service-tickets/<ticketId>")
def get_ticket(ticketId):
    get_auth()
    t = db.service_tickets.get(ticketId)
    if t is None:
        raise ApiError(ERR_SERVICE_TICKET_NOT_FOUND, 404, "ServiceTicket id does not exist")
    return success_object(view(t))


@bp.post("/wholesale/service-tickets/<ticketId>/schedule")
def schedule_ticket(ticketId):
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["RoutePlanner"])
    service_date = req_string(body, "service_date")
    try:
        sd = clock.parse_date(service_date)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "service_date must be YYYY-MM-DD")
    t = db.service_tickets.get(ticketId)
    if t is None:
        raise ApiError(ERR_SERVICE_TICKET_NOT_FOUND, 404, "ServiceTicket id does not exist")
    if t["status"] != "OPEN":
        raise ApiError(ERR_TICKET_NOT_OPEN, 409, "schedule requires ticket OPEN")
    location = db.locations[t["location_id"]]
    operator = db.operators[location["operator_id"]]
    if operator["status"] != "ACTIVE":
        raise ApiError(ERR_OPERATOR_NOT_ACTIVE, 409, "Operator must be ACTIVE")
    if not (sd > clock.now().date()):
        raise ApiError(ERR_DATE_NOT_FUTURE, 422, "service_date must be strictly after the current logical date")
    t["service_date"] = service_date
    t["status"] = "SCHEDULED"
    touch(t)
    return success_object(view(t))


@bp.post("/wholesale/service-tickets/<ticketId>/complete")
def complete_ticket(ticketId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["WarehouseOps"])
    t = db.service_tickets.get(ticketId)
    if t is None:
        raise ApiError(ERR_SERVICE_TICKET_NOT_FOUND, 404, "ServiceTicket id does not exist")
    if t["status"] != "SCHEDULED":
        raise ApiError(ERR_TICKET_NOT_SCHEDULED, 409, "complete requires ticket SCHEDULED")
    t["status"] = "COMPLETED"
    touch(t)
    return success_object(view(t))
