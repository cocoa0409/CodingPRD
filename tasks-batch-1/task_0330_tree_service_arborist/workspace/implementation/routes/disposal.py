"""DisposalTicket routes (nested under work order) + finalize/void."""
from flask import Blueprint

import calculations
import db
import errors
import lookups
import response
from errors import ApiError
from helpers import as_number, get_json_body, parse_pagination
from middleware import ALL_ROLES, require_roles

bp = Blueprint("disposal", __name__)


@bp.post("/work-orders/<wid>/disposal-tickets")
@require_roles("Dispatcher", "FinanceClerk")
def create_ticket(wid):
    wo = lookups.get_work_order(wid)
    if wo["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(errors.ERR_WORK_ORDER_TERMINAL, 409, "Work order is terminal.")
    body = get_json_body()
    debris_tons = as_number(body, "debris_tons")
    if debris_tons <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "debris_tons must be > 0.")
    obj = db.stamp_new({
        "work_order_id": wid,
        "debris_tons": debris_tons,
        "fee_cents": 0,
        "status": "RECORDED",
    })
    db.disposal_tickets[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/work-orders/<wid>/disposal-tickets")
@require_roles(*ALL_ROLES)
def list_tickets(wid):
    lookups.get_work_order(wid)
    limit, offset = parse_pagination()
    items = db.sort_by_created(
        [t for t in db.disposal_tickets.values() if t["work_order_id"] == wid])
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/work-orders/<wid>/disposal-tickets/<tid>")
@require_roles(*ALL_ROLES)
def get_ticket(wid, tid):
    lookups.get_work_order(wid)
    obj = lookups.get_disposal_ticket_on_wo(wid, tid)
    return response.success(db.public(obj), 200)


@bp.post("/work-orders/<wid>/disposal-tickets/<tid>/finalize")
@require_roles("FinanceClerk")
def finalize_ticket(wid, tid):
    wo = lookups.get_work_order(wid)
    ticket = lookups.get_disposal_ticket_on_wo(wid, tid)
    if wo["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_WORK_ORDER_NOT_SCHEDULED, 409,
                       "Work order is not SCHEDULED.")
    if ticket["status"] != "RECORDED":
        raise ApiError(errors.ERR_TICKET_NOT_RECORDED, 409, "Ticket is not RECORDED.")

    area = db.service_areas.get(wo["service_area_id"])
    fee = calculations.disposal_fee(ticket["debris_tons"],
                                    area["disposal_fee_cents_per_ton"])
    ticket["fee_cents"] = fee
    ticket["status"] = "FINALIZED"
    db.touch(ticket)

    wo["disposal_cost_accrued_cents"] += fee
    db.touch(wo)
    return response.success(db.public(ticket), 200)


@bp.post("/work-orders/<wid>/disposal-tickets/<tid>/void")
@require_roles("FinanceClerk")
def void_ticket(wid, tid):
    lookups.get_work_order(wid)
    ticket = lookups.get_disposal_ticket_on_wo(wid, tid)
    if ticket["status"] != "RECORDED":
        raise ApiError(errors.ERR_TICKET_NOT_RECORDED, 409, "Ticket is not RECORDED.")
    ticket["status"] = "VOIDED"
    db.touch(ticket)
    return response.success(db.public(ticket), 200)
