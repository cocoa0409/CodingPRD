"""Repair tickets for customer-owned machines, including the re-quote loop."""
from flask import Blueprint, g

from db import store, new_common, new_id, touch, is_int
from errors import ApiError
from middleware import require_roles, body
from response import ok, created, list_response, filter_param

bp = Blueprint("repairs", __name__)

_ROLES = ("ServiceTech", "BranchManager")
_READ_ROLES = ("ServiceTech", "BranchManager", "CounterRep")

# Legal (from, to) pairs of the repair state machine.
_TRANSITIONS = {
    ("INTAKE", "DIAGNOSING"),
    ("DIAGNOSING", "QUOTED"),
    ("QUOTED", "APPROVED"),
    ("QUOTED", "REJECTED"),
    ("REJECTED", "DIAGNOSING"),
    ("APPROVED", "IN_REPAIR"),
    ("IN_REPAIR", "READY_FOR_PICKUP"),
    ("READY_FOR_PICKUP", "CLOSED"),
    ("REJECTED", "CLOSED"),
}
_VALID_TARGETS = ("DIAGNOSING", "QUOTED", "APPROVED", "REJECTED", "IN_REPAIR",
                  "READY_FOR_PICKUP", "CLOSED")


def get_ticket(tid):
    ticket = store.repair_tickets.get(tid)
    if ticket is None:
        raise ApiError("ERR_NOT_FOUND", 404, "RepairTicket not found")
    return ticket


@bp.route("/repair-tickets", methods=["POST"])
@require_roles(*_ROLES)
def create_ticket():
    b = body()
    cust_id = b.get("customer_id")
    # Priority 3: referenced customer exists.
    if cust_id is not None and cust_id not in store.customers:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer not found")
    # Priority 4: shape.
    if not isinstance(cust_id, str) or not cust_id:
        raise ApiError("ERR_VALIDATION", 400, "customer_id is required")
    machine_desc = b.get("machine_desc")
    issue_desc = b.get("issue_desc")
    if not isinstance(machine_desc, str) or not machine_desc:
        raise ApiError("ERR_VALIDATION", 400, "machine_desc is required")
    if not isinstance(issue_desc, str) or not issue_desc:
        raise ApiError("ERR_VALIDATION", 400, "issue_desc is required")
    ticket = {
        "id": new_id(),
        "customer_id": cust_id,
        "machine_desc": machine_desc,
        "issue_desc": issue_desc,
        "status": "INTAKE",
        "quote_cents": None,
        "revision_no": 0,
        "charged_cents": None,
    }
    new_common(ticket)
    store.repair_tickets[ticket["id"]] = ticket
    return created(ticket)


@bp.route("/repair-tickets", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_tickets():
    rows = list(store.repair_tickets.values())
    rows = filter_param(rows, "customer_id")
    rows = filter_param(rows, "status")
    return list_response(rows)


@bp.route("/repair-tickets/<tid>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_one_ticket(tid):
    return ok(get_ticket(tid))


@bp.route("/repair-tickets/<tid>/advance", methods=["POST"])
@require_roles(*_ROLES)
def advance_ticket(tid):
    role = g.user_role
    b = body()
    to = b.get("to")
    # Priority 2 (per-target): quote approval and rejection are manager-only.
    if to in ("APPROVED", "REJECTED") and role != "BranchManager":
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Target %s requires BranchManager" % to)
    ticket = get_ticket(tid)
    # Priority 4: valid target; QUOTED requires a positive quote_cents.
    if to not in _VALID_TARGETS:
        raise ApiError("ERR_VALIDATION", 400,
                       "to must be one of %s" % ", ".join(_VALID_TARGETS))
    quote = b.get("quote_cents")
    if to == "QUOTED" and (not is_int(quote) or quote <= 0):
        raise ApiError("ERR_VALIDATION", 400,
                       "quote_cents must be supplied as an integer > 0 for QUOTED")
    # Priority 6: the from/to pair must be a declared transition.
    if (ticket["status"], to) not in _TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot advance from %s to %s" % (ticket["status"], to))
    # Side effects.
    if to == "DIAGNOSING" and ticket["status"] == "REJECTED":
        # Re-quote loop: bump the revision counter, clear the old quote.
        ticket["revision_no"] += 1
        ticket["quote_cents"] = None
    if to == "QUOTED":
        ticket["quote_cents"] = quote
    if to == "CLOSED":
        if ticket["status"] == "READY_FOR_PICKUP":
            ticket["charged_cents"] = ticket["quote_cents"]
        else:  # closed from REJECTED — declined work bills nothing
            ticket["charged_cents"] = 0
    ticket["status"] = to
    touch(ticket)
    return ok(ticket)
