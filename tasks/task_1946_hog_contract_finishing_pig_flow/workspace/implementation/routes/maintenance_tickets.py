"""Maintenance tickets (PRD §3.7): quote/approve segregation and the 50000-cent
FieldTech approval threshold, EMERGENCY fix-first retro path, pinned owner-first
cost split, negligence charge routing at completion."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict, forbidden_role, segregation_of_duties,
    ERR_INVALID_STATE_TRANSITION, ERR_TICKET_UNAPPROVED,
)
from middleware import (
    require_roles, check_grower_ownership, ticket_owner_id,
    ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER,
)
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_maintenance_ticket,
    active_contract_on_site, maintenance_cost_split, charge_negligence_share,
    TICKET_APPROVAL_THRESHOLD_CENTS,
)
from util import get_body, req, as_str, as_int, as_enum, load_or_404

bp = Blueprint("maintenance_tickets", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER]
CATEGORIES = {"STRUCTURAL", "EQUIPMENT", "ROUTINE", "EMERGENCY"}
CAUSES = {"WEAR", "NEGLIGENCE", "ACT_OF_NATURE"}


@bp.route("/maintenance-tickets", methods=["POST"])
def create_ticket():
    role, user_id = require_roles([ROLE_GROWER])
    body = get_body()
    barn_id = as_str(req(body, "barn_id"), "barn_id")
    barn = load_or_404(store.barns, barn_id, "Barn")
    # ownership: the ACTIVE contract on the barn's site must be the caller's
    contract = active_contract_on_site(barn["site_id"])
    check_grower_ownership(role, user_id, contract["grower_id"] if contract else None)
    category = as_enum(req(body, "category"), "category", CATEGORIES)
    description = as_str(req(body, "description"), "description")
    rec = new_record()
    rec.update({
        "barn_id": barn_id,
        "contract_id": contract["id"],
        "grower_id": contract["grower_id"],
        "category": category, "description": description,
        "cause": None, "cost_cents": None, "quoted_by": None,
        "approved_by": None, "approved_flag": False,
        "owner_share_cents": None, "grower_share_cents": None,
        "completed_at": None, "ticket_status": "OPEN",
    })
    store.maintenance_tickets[rec["id"]] = rec
    return success_object(ser_maintenance_ticket(rec), 201)


@bp.route("/maintenance-tickets", methods=["GET"])
def list_tickets():
    require_roles(ROLES_READ)
    barn_id = request.args.get("barn_id")
    contract_id = request.args.get("contract_id")
    grower_id = request.args.get("grower_id")
    status = request.args.get("ticket_status")
    items = list(store.maintenance_tickets.values())
    if barn_id is not None:
        items = [t for t in items if t["barn_id"] == barn_id]
    if contract_id is not None:
        items = [t for t in items if t["contract_id"] == contract_id]
    if grower_id is not None:
        items = [t for t in items if t["grower_id"] == grower_id]
    if status is not None:
        items = [t for t in items if t["ticket_status"] == status]
    return paginate(items, request.args, ser_maintenance_ticket)


@bp.route("/maintenance-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    role, user_id = require_roles(ROLES_READ)
    ticket = load_or_404(store.maintenance_tickets, tid, "MaintenanceTicket")
    check_grower_ownership(role, user_id, ticket_owner_id(ticket))
    return success_object(ser_maintenance_ticket(ticket))


@bp.route("/maintenance-tickets/<tid>/quote", methods=["POST"])
def quote_ticket(tid):
    role, user_id = require_roles([ROLE_FIELD_TECH])
    ticket = load_or_404(store.maintenance_tickets, tid, "MaintenanceTicket")
    body = get_body()
    cost_cents = as_int(req(body, "cost_cents"), "cost_cents", 1)
    cause = as_enum(req(body, "cause"), "cause", CAUSES)
    if ticket["ticket_status"] == "OPEN":
        new_status = "QUOTED"
    elif ticket["ticket_status"] == "IN_PROGRESS" and ticket["category"] == "EMERGENCY":
        new_status = "IN_PROGRESS"  # EMERGENCY retro-quote
    else:
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot quote a ticket in {ticket['ticket_status']}")
    ticket["cost_cents"] = cost_cents
    ticket["cause"] = cause
    ticket["quoted_by"] = user_id
    ticket["ticket_status"] = new_status
    touch(ticket)
    return success_object(ser_maintenance_ticket(ticket))


@bp.route("/maintenance-tickets/<tid>/approve", methods=["POST"])
def approve_ticket(tid):
    role, user_id = require_roles([ROLE_FIELD_TECH, ROLE_INTEGRATOR_ADMIN])
    ticket = load_or_404(store.maintenance_tickets, tid, "MaintenanceTicket")
    # value-dependent role check (priority 2): FieldTech may approve only below
    # the 50000-cent threshold; an attempt at or above it fails here
    if (role == ROLE_FIELD_TECH and ticket["cost_cents"] is not None
            and ticket["cost_cents"] >= TICKET_APPROVAL_THRESHOLD_CENTS):
        raise forbidden_role("FieldTech may approve only below 50000 cents")
    if ticket["ticket_status"] == "QUOTED":
        new_status = "APPROVED"
    elif ticket["ticket_status"] == "IN_PROGRESS" and ticket["category"] == "EMERGENCY":
        new_status = "IN_PROGRESS"  # EMERGENCY retro-approval
    else:
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot approve a ticket in {ticket['ticket_status']}")
    # SoD: the approver's identity must differ from the quoter's (§2.11)
    if user_id == ticket["quoted_by"]:
        raise segregation_of_duties("Approver must differ from the quoter")
    contract = store.contracts.get(ticket["contract_id"])
    owner_share, grower_share = maintenance_cost_split(
        contract, ticket["category"], ticket["cause"], ticket["cost_cents"])
    ticket["owner_share_cents"] = owner_share
    ticket["grower_share_cents"] = grower_share
    ticket["approved_by"] = user_id
    ticket["approved_flag"] = True
    ticket["ticket_status"] = new_status
    touch(ticket)
    return success_object(ser_maintenance_ticket(ticket))


@bp.route("/maintenance-tickets/<tid>/start-work", methods=["POST"])
def start_work_ticket(tid):
    require_roles([ROLE_FIELD_TECH])
    ticket = load_or_404(store.maintenance_tickets, tid, "MaintenanceTicket")
    if ticket["ticket_status"] == "APPROVED":
        pass  # standard path
    elif not (ticket["ticket_status"] == "QUOTED" and ticket["category"] == "EMERGENCY"):
        # EMERGENCY fix-first may start from QUOTED; everything else is illegal
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot start work on a ticket in {ticket['ticket_status']}")
    ticket["ticket_status"] = "IN_PROGRESS"
    touch(ticket)
    return success_object(ser_maintenance_ticket(ticket))


@bp.route("/maintenance-tickets/<tid>/complete", methods=["POST"])
def complete_ticket(tid):
    require_roles([ROLE_FIELD_TECH])
    ticket = load_or_404(store.maintenance_tickets, tid, "MaintenanceTicket")
    if ticket["ticket_status"] != "IN_PROGRESS":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot complete a ticket in {ticket['ticket_status']}")
    if not ticket["approved_flag"]:
        raise conflict(ERR_TICKET_UNAPPROVED,
                       "Ticket has no recorded approval")
    ticket["completed_at"] = store.now()
    ticket["ticket_status"] = "COMPLETED"
    touch(ticket)
    # negligence's second life: the grower's share is charged at completion
    if ticket["cause"] == "NEGLIGENCE":
        charge_negligence_share(ticket, ticket["grower_share_cents"])
    return success_object(ser_maintenance_ticket(ticket))


@bp.route("/maintenance-tickets/<tid>/reject", methods=["POST"])
def reject_ticket(tid):
    require_roles([ROLE_FIELD_TECH])
    ticket = load_or_404(store.maintenance_tickets, tid, "MaintenanceTicket")
    if ticket["ticket_status"] != "QUOTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot reject a ticket in {ticket['ticket_status']}")
    ticket["ticket_status"] = "REJECTED"
    touch(ticket)
    return success_object(ser_maintenance_ticket(ticket))


@bp.route("/maintenance-tickets/<tid>/cancel", methods=["POST"])
def cancel_ticket(tid):
    role, user_id = require_roles([ROLE_GROWER])
    ticket = load_or_404(store.maintenance_tickets, tid, "MaintenanceTicket")
    # the grower cancels only their own ticket
    check_grower_ownership(role, user_id, ticket_owner_id(ticket))
    if ticket["ticket_status"] not in ("OPEN", "QUOTED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot cancel a ticket in {ticket['ticket_status']}")
    ticket["ticket_status"] = "CANCELLED"
    touch(ticket)
    return success_object(ser_maintenance_ticket(ticket))
