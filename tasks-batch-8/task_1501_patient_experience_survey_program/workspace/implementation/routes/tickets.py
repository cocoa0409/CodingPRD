"""ServiceRecoveryTicket endpoints (PRD 3.9): comment routing with the
chain-of-custody checks, acknowledge (SLA stamp), resolve."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_UNIT_ACCESS_DENIED,
    ERR_RESPONSE_NOT_FINAL,
    ERR_UNIT_RESPONSE_MISMATCH,
    ERR_NO_COMMENT_TO_ROUTE,
    ERR_TICKET_NOT_ACKNOWLEDGEABLE,
    ERR_TICKET_NOT_RESOLVABLE,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import ticket_view
from services.core import service_recovery_sla
from util import (
    get_json_body, reject_unknown_fields, require_string, require_enum,
    get_or_404, parse_pagination, paginate, sort_created, query_arg,
)

bp = Blueprint("tickets", __name__)

DOMAINS = {"NURSE_COMM", "DOCTOR_COMM", "CLEANLINESS", "OVERALL_RATING"}
PRIORITIES = {"LOW", "MEDIUM", "HIGH"}
CREATE_FIELDS = {"unit_id", "response_id", "domain", "priority"}


@bp.route("/api/service-recovery-tickets", methods=["POST"])
@require_roles("UnitManager")
def create_ticket(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    unit_id = require_string(body, "unit_id")

    # Entity-backed ownership (priority 2.5): the manager's X-User-ID must
    # equal the requested unit_id.
    if _user_id != unit_id:
        raise_err(ERR_UNIT_ACCESS_DENIED,
                  "UnitManager may only route tickets for their own unit")

    response_id = require_string(body, "response_id")
    domain = require_enum(body, "domain", DOMAINS)
    priority = require_enum(body, "priority", PRIORITIES)

    unit = get_or_404(db.units, unit_id, "CareUnit")
    response = get_or_404(db.responses, response_id, "SurveyResponse")

    # State (tier 4): the routed response must be final (ACCEPTED or INCLUDED).
    if response["status"] not in ("ACCEPTED", "INCLUDED"):
        raise_err(ERR_RESPONSE_NOT_FINAL,
                  "Only an ACCEPTED or INCLUDED response can be routed")
    # Referential (tier 6): the response's attributed unit must be the ticket's.
    case = db.sample_cases.get(response["case_id"])
    if case is None or case["unit_id"] != unit_id:
        raise_err(ERR_UNIT_RESPONSE_MISMATCH,
                  "The response's attributed unit does not match the ticket's unit_id")
    # Constraint (tier 8): nothing to route without a comment.
    if not response["comment_text"]:
        raise_err(ERR_NO_COMMENT_TO_ROUTE,
                  "The response carries no comment_text to route")

    ticket = db.stamp_new({
        "unit_id": unit_id,
        "program_id": unit["program_id"],
        "response_id": response_id,
        "domain": domain,
        "priority": priority,
        "status": "OPEN",
        "acknowledged_at": None,
        "acknowledged_within_sla": None,
        "resolution_note": None,
    })
    db.tickets[ticket["id"]] = ticket
    return success_object(ticket_view(ticket), 201)


@bp.route("/api/service-recovery-tickets", methods=["GET"])
@require_roles("Any")
def list_tickets(_user_id: str, _role: str):
    items = list(db.tickets.values())
    for param in ("unit_id", "program_id", "response_id", "status"):
        value = query_arg(param)
        if value is not None:
            items = [t for t in items if t[param] == value]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([ticket_view(t) for t in page], limit, offset, total)


@bp.route("/api/service-recovery-tickets/<ticketId>", methods=["GET"])
@require_roles("Any")
def get_ticket(ticketId: str, _user_id: str, _role: str):
    ticket = get_or_404(db.tickets, ticketId, "ServiceRecoveryTicket")
    return success_object(ticket_view(ticket))


@bp.route("/api/service-recovery-tickets/<ticketId>/acknowledge", methods=["POST"])
@require_roles("UnitManager")
def acknowledge_ticket(ticketId: str, _user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, set())
    ticket = get_or_404(db.tickets, ticketId, "ServiceRecoveryTicket")
    if _user_id != ticket["unit_id"]:
        raise_err(ERR_UNIT_ACCESS_DENIED,
                  "UnitManager may only acknowledge tickets for their own unit")
    if ticket["status"] not in ("OPEN", "ESCALATED"):
        raise_err(ERR_TICKET_NOT_ACKNOWLEDGEABLE,
                  "Only an OPEN or ESCALATED ticket can be acknowledged")

    ticket["acknowledged_at"] = db.clock_now()
    ticket["acknowledged_within_sla"] = service_recovery_sla(
        ticket["created_at"], ticket["acknowledged_at"])
    ticket["status"] = "ACKNOWLEDGED"
    db.touch(ticket)
    return success_object(ticket_view(ticket))


@bp.route("/api/service-recovery-tickets/<ticketId>/resolve", methods=["POST"])
@require_roles("UnitManager")
def resolve_ticket(ticketId: str, _user_id: str, _role: str):
    ticket = get_or_404(db.tickets, ticketId, "ServiceRecoveryTicket")
    if _user_id != ticket["unit_id"]:
        raise_err(ERR_UNIT_ACCESS_DENIED,
                  "UnitManager may only resolve tickets for their own unit")
    body = get_json_body()
    reject_unknown_fields(body, {"resolution_note"})
    note = require_string(body, "resolution_note")
    if ticket["status"] != "ACKNOWLEDGED":
        raise_err(ERR_TICKET_NOT_RESOLVABLE,
                  "Only an ACKNOWLEDGED ticket can be resolved")

    ticket["resolution_note"] = note
    ticket["status"] = "RESOLVED"
    db.touch(ticket)
    return success_object(ticket_view(ticket))
