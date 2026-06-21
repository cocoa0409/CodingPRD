"""MaintenanceTicket routes: file, fetch, list, approve, reject, resolve."""

from flask import Blueprint, request

import db
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from routes.helpers import lookup, paginate
from services import domain
from services import calc
import validation as V

bp = Blueprint("maintenance", __name__)


# ---------------------------------------------------------------------------
# File (Tenant)
# ---------------------------------------------------------------------------
@bp.post("/agreements/<aid>/maintenance-tickets")
def create_ticket(aid):
    user_id, role = get_auth()
    require_role(role, {"Tenant"})
    agreement = lookup(db.agreements, aid)
    if agreement["tenant_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Tenant does not own this agreement")

    body = V.get_body()
    summary = V.require_str(body, "summary")
    estimated_cost_cents = V.require_int(body, "estimated_cost_cents", minimum=0)

    rec = {
        "id": db.new_id(),
        "agreement_id": aid,
        "summary": summary,
        "estimated_cost_cents": estimated_cost_cents,
        "actual_cost_cents": None,
        "tenant_share_cents": None,
        "landlord_share_cents": None,
        "status": "OPEN",
    }
    domain._stamp_new(rec)
    db.maintenance_tickets[rec["id"]] = rec
    return object_response(domain.serialize_maintenance_ticket(rec), 201)


# ---------------------------------------------------------------------------
# Fetch / list
# ---------------------------------------------------------------------------
@bp.get("/maintenance-tickets/<rid>")
def get_ticket(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.maintenance_tickets, rid)
    return object_response(domain.serialize_maintenance_ticket(rec), 200)


@bp.get("/maintenance-tickets")
def list_tickets():
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    items = list(db.maintenance_tickets.values())
    for field in ("agreement_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [t for t in items if t.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([domain.serialize_maintenance_ticket(t) for t in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Approve (Landlord): OPEN -> APPROVED, estimate split
# ---------------------------------------------------------------------------
@bp.post("/maintenance-tickets/<rid>/approve")
def approve_ticket(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    ticket = lookup(db.maintenance_tickets, rid)
    agreement = lookup(db.agreements, ticket["agreement_id"])
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this ticket")

    if ticket["status"] != "OPEN":
        raise err("ERR_TICKET_NOT_OPEN", "Ticket is not OPEN")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")

    tenant_share, landlord_share = calc.maintenance_split(
        ticket["estimated_cost_cents"], agreement["maintenance_threshold_cents"])
    ticket["tenant_share_cents"] = tenant_share
    ticket["landlord_share_cents"] = landlord_share
    ticket["status"] = "APPROVED"
    domain.touch(ticket)
    return object_response(domain.serialize_maintenance_ticket(ticket), 200)


# ---------------------------------------------------------------------------
# Reject (Landlord): OPEN -> REJECTED
# ---------------------------------------------------------------------------
@bp.post("/maintenance-tickets/<rid>/reject")
def reject_ticket(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    ticket = lookup(db.maintenance_tickets, rid)
    agreement = lookup(db.agreements, ticket["agreement_id"])
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this ticket")

    if ticket["status"] != "OPEN":
        raise err("ERR_TICKET_NOT_OPEN", "Ticket is not OPEN")

    ticket["status"] = "REJECTED"
    domain.touch(ticket)
    return object_response(domain.serialize_maintenance_ticket(ticket), 200)


# ---------------------------------------------------------------------------
# Resolve (Landlord): APPROVED -> RESOLVED, actual split (overrides estimate)
# ---------------------------------------------------------------------------
@bp.post("/maintenance-tickets/<rid>/resolve")
def resolve_ticket(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    ticket = lookup(db.maintenance_tickets, rid)
    agreement = lookup(db.agreements, ticket["agreement_id"])
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this ticket")

    body = V.get_body()
    actual_cost_cents = V.require_int(body, "actual_cost_cents", minimum=0)

    if ticket["status"] != "APPROVED":
        raise err("ERR_TICKET_NOT_APPROVED", "Ticket is not APPROVED")

    ticket["actual_cost_cents"] = actual_cost_cents
    tenant_share, landlord_share = calc.maintenance_split(
        actual_cost_cents, agreement["maintenance_threshold_cents"])
    ticket["tenant_share_cents"] = tenant_share
    ticket["landlord_share_cents"] = landlord_share
    ticket["status"] = "RESOLVED"
    domain.touch(ticket)
    return object_response(domain.serialize_maintenance_ticket(ticket), 200)
