"""ObligationTicket endpoints."""

from flask import Blueprint, request

from db import store, touch
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_OBLIGATION_TICKET_NOT_FOUND,
    ERR_TICKET_NOT_OPEN, ERR_TICKET_NOT_IN_PROGRESS, ERR_TICKET_NOT_WAIVABLE,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine

bp = Blueprint("tickets", __name__)


def ticket_view(t):
    return {k: v for k, v in t.items() if not k.startswith("_")}


def _resolve(productId, ticketId=None):
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    t = None
    if ticketId is not None:
        t = store.tickets.get(ticketId)
        if not t or t["product_id"] != productId:
            raise err(ERR_OBLIGATION_TICKET_NOT_FOUND, "ObligationTicket not found")
    return p, t


@bp.route("/oss-products/<productId>/obligation-tickets", methods=["GET"])
def list_tickets(productId):
    get_auth()
    _resolve(productId)
    limit, offset = parse_pagination(request.args)
    items = [t for t in store.tickets.values() if t["product_id"] == productId]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    otype = request.args.get("obligation_type")
    if otype:
        items = [t for t in items if t["obligation_type"] == otype]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ticket_view(t) for t in page], limit, offset, total)


@bp.route("/oss-products/<productId>/obligation-tickets/<ticketId>", methods=["GET"])
def get_ticket(productId, ticketId):
    get_auth()
    _, t = _resolve(productId, ticketId)
    return success_obj(ticket_view(t))


@bp.route("/oss-products/<productId>/obligation-tickets/<ticketId>/start", methods=["POST"])
def start_ticket(productId, ticketId):
    require_roles("ComplianceAnalyst")
    _, t = _resolve(productId, ticketId)
    if t["status"] != "OPEN":
        raise err(ERR_TICKET_NOT_OPEN, "ObligationTicket must be OPEN")
    t["status"] = "IN_PROGRESS"
    touch(t)
    return success_obj(ticket_view(t))


@bp.route("/oss-products/<productId>/obligation-tickets/<ticketId>/fulfill", methods=["POST"])
def fulfill_ticket(productId, ticketId):
    require_roles("ComplianceAnalyst")
    p, t = _resolve(productId, ticketId)
    body = get_json_body()
    evidence = body.get("fulfillment_evidence_uri")
    if not evidence:
        raise err(ERR_INVALID_REQUEST, "fulfillment_evidence_uri must be provided")
    if t["status"] != "IN_PROGRESS":
        raise err(ERR_TICKET_NOT_IN_PROGRESS, "ObligationTicket must be IN_PROGRESS")
    t["status"] = "FULFILLED"
    t["fulfillment_evidence_uri"] = evidence
    touch(t)
    entry = store.bom_entries.get(t["bom_entry_id"])
    if entry:
        engine.update_entry_obligation_fulfilled(entry)
    engine.reevaluate_product_posture(p)
    return success_obj(ticket_view(t))


@bp.route("/oss-products/<productId>/obligation-tickets/<ticketId>/waive", methods=["POST"])
def waive_ticket(productId, ticketId):
    user_id, _ = require_roles("LegalCounsel")
    p, t = _resolve(productId, ticketId)
    body = get_json_body()
    reason = body.get("waiver_reason")
    if not reason:
        raise err(ERR_INVALID_REQUEST, "waiver_reason must be provided")
    if t["status"] not in ("OPEN", "IN_PROGRESS"):
        raise err(ERR_TICKET_NOT_WAIVABLE, "ObligationTicket must be OPEN or IN_PROGRESS to waive")
    t["status"] = "WAIVED"
    t["waiver_reason"] = reason
    t["waived_by"] = user_id
    touch(t)
    entry = store.bom_entries.get(t["bom_entry_id"])
    if entry:
        engine.update_entry_obligation_fulfilled(entry)
    engine.reevaluate_product_posture(p)
    return success_obj(ticket_view(t))
