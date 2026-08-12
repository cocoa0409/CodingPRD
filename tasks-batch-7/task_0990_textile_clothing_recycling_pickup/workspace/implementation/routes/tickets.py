"""WeightTicket endpoints: read, certify, void."""
from flask import Blueprint

from db import store, touch, now_dt, now_iso
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import check_fields, get_body

bp = Blueprint("tickets", __name__)


@bp.route("/weight-tickets/<tid>", methods=["GET"])
@endpoint(["ZoneOperator", "Driver", "Inspector", "Resident"])
def get_ticket(user_id, role, tid):
    ticket = store.tickets.get(tid)
    # Resident binding: only tickets sourced from their own pickups
    if role == "Resident" and ticket is not None:
        if domain.ticket_resident_id(ticket) != user_id:
            fail("ERR_UNAUTHORIZED", "Residents may only read tickets from their own pickups")
    if ticket is None:
        fail("ERR_NOT_FOUND", "WeightTicket not found: %s" % tid)
    return success(domain.ticket_view(ticket))


@bp.route("/weight-tickets/<tid>/certify", methods=["POST"])
@endpoint(["ZoneOperator"])
def certify_ticket(user_id, role, tid):
    ticket = store.tickets.get(tid)
    body = get_body()
    check_fields(body, {
        "certified_weight_kg": ("num", True),
        "grade": (("enum", ("RESALE", "RECYCLE", "FIBER")), True),
    })
    from services import calc
    if calc.dec(body["certified_weight_kg"]) <= 0:
        fail("ERR_INVALID_REQUEST", "certified_weight_kg must be > 0")
    if ticket is None:
        fail("ERR_NOT_FOUND", "WeightTicket not found: %s" % tid)
    if ticket["status"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE", "Ticket must be PROVISIONAL to certify")
    ticket["certified_weight_kg"] = body["certified_weight_kg"]
    ticket["grade"] = body["grade"]
    ticket["status"] = "CERTIFIED"
    ticket["certified_at"] = now_iso()
    ticket["_certified_at"] = now_dt()
    touch(ticket)
    # bubble-up: source pickup COLLECTED -> WEIGHED
    if ticket["source_type"] == "PICKUP_REQUEST":
        pickup = store.pickups.get(ticket["source_id"])
        if pickup is not None and pickup["status"] == "COLLECTED":
            pickup["status"] = "WEIGHED"
            touch(pickup)
    return success(domain.ticket_view(ticket))


@bp.route("/weight-tickets/<tid>/void", methods=["POST"])
@endpoint(["ZoneOperator"])
def void_ticket(user_id, role, tid):
    ticket = store.tickets.get(tid)
    get_body()
    if ticket is None:
        fail("ERR_NOT_FOUND", "WeightTicket not found: %s" % tid)
    if ticket["status"] not in ("CERTIFIED", "QUARANTINED"):
        fail("ERR_INVALID_STATE", "Ticket must be CERTIFIED or QUARANTINED to void")
    if domain.settled_credit_on_ticket(tid) is not None:
        fail("ERR_INVALID_STATE", "A SETTLED credit exists on this ticket")
    ticket["status"] = "VOIDED"
    touch(ticket)
    # cascade: non-settled credits -> VOIDED (hold released); PENDING assignments declined
    for c in store.credits.values():
        if c["ticket_id"] == tid and c["status"] in ("PROVISIONAL", "DISPUTED", "FINALIZED"):
            domain.void_credit_record(c)
    domain.decline_pending_assignments(tid)
    return success(domain.ticket_view(ticket))
