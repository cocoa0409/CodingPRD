"""Alteration tickets (PRD §3.7)."""
from flask import Blueprint, request

import errors
import serializers as S
import validation as V
from db import db, stamp_create, touch
from errors import fail
from lookups import get_order, get_ticket
from middleware import get_user_context, require_role, get_json_body
from response import success, list_response

bp = Blueprint("alterations", __name__)


@bp.post("/orders/<oid>/alterations")
def open_ticket(oid):
    _, role = get_user_context()
    require_role(role, {"SalesAssociate", "FittingSpecialist", "ShopManager", "Customer"})
    o = get_order(oid)
    body = get_json_body()
    description = V.req_str(body, "description")
    billable = V.opt_int(body, "billable_cents", default=0, minimum=0)

    # order must be READY or PICKED_UP
    if o["status"] not in ("READY", "PICKED_UP"):
        fail(errors.ERR_ORDER_INVALID_STATE, "Alterations allowed only on READY or PICKED_UP orders")

    rec = stamp_create()
    rec.update({
        "order_id": oid,
        "description": description,
        "billable_cents": billable,
        "status": "OPEN",
    })
    db.alteration_tickets[rec["id"]] = rec
    return success(S.alteration_ticket(rec), status=201)


@bp.get("/orders/<oid>/alterations")
def list_tickets(oid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    get_order(oid)
    limit, offset = V.parse_pagination()
    status = request.args.get("status")

    def pred(t):
        if t["order_id"] != oid:
            return False
        if status is not None and t["status"] != status:
            return False
        return True

    items = [t for t in db.alteration_tickets.values() if pred(t)]
    items.sort(key=lambda t: t["created_at"])
    page = V.paginate(items, limit, offset)
    return list_response([S.alteration_ticket(t) for t in page], len(items), limit, offset)


@bp.post("/orders/<oid>/alterations/<tid>/complete")
def complete_ticket(oid, tid):
    _, role = get_user_context()
    require_role(role, {"FittingSpecialist", "ShopManager"})
    get_order(oid)
    ticket = get_ticket(oid, tid)

    if ticket["status"] != "OPEN":
        fail(errors.ERR_ALTERATION_INVALID_STATE, "Ticket is not OPEN")

    # billable tickets require a BALANCE payment captured after the ticket opened,
    # summing to at least the billable amount.
    if ticket["billable_cents"] > 0:
        paid_after = sum(
            p["amount_cents"] for p in db.payments.values()
            if p["order_id"] == oid and p["kind"] == "BALANCE"
            and p["status"] == "CAPTURED" and p["created_at"] > ticket["created_at"]
        )
        if paid_after < ticket["billable_cents"]:
            fail(errors.ERR_ALTERATION_UNPAID, "Billable alteration not yet paid")

    ticket["status"] = "COMPLETED"
    touch(ticket)
    return success(S.alteration_ticket(ticket))


@bp.post("/orders/<oid>/alterations/<tid>/void")
def void_ticket(oid, tid):
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    get_order(oid)
    ticket = get_ticket(oid, tid)

    if ticket["status"] != "OPEN":
        fail(errors.ERR_ALTERATION_INVALID_STATE, "Ticket is not OPEN")

    ticket["status"] = "VOIDED"
    touch(ticket)
    return success(S.alteration_ticket(ticket))
