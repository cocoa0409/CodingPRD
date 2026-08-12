"""Partner and RoutingAssignment endpoints."""
from flask import Blueprint

from db import store, new_record, touch, now_dt
from errors import fail
from middleware import endpoint
from response import success
from services import calc, domain
from util import check_fields, get_body, paginate

bp = Blueprint("partners", __name__)

GRADES = ("RESALE", "RECYCLE", "FIBER")


@bp.route("/partners", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_partner(user_id, role):
    body = get_body()
    check_fields(body, {
        "name": ("str", True),
        "partner_type": (("enum", ("BRAND", "THRIFT")), True),
        "accepted_grades": ("list", True),
        "capacity_kg": ("int", True),
    })
    grades = body["accepted_grades"]
    if not grades or any(not isinstance(g, str) or g not in GRADES for g in grades):
        fail("ERR_INVALID_REQUEST", "accepted_grades must be a non-empty subset of RESALE/RECYCLE/FIBER")
    if body["capacity_kg"] <= 0:
        fail("ERR_INVALID_REQUEST", "capacity_kg must be > 0")
    rec = new_record()
    rec.update({
        "name": body["name"],
        "partner_type": body["partner_type"],
        "accepted_grades": list(grades),
        "capacity_kg": body["capacity_kg"],
        "status": "ELIGIBLE",
    })
    store.partners[rec["id"]] = rec
    return success(domain.partner_view(rec), code=201)


@bp.route("/partners/<pid>", methods=["GET"])
@endpoint(["ZoneOperator", "PartnerManager"])
def get_partner(user_id, role, pid):
    if role == "PartnerManager" and user_id != pid:
        fail("ERR_UNAUTHORIZED", "PartnerManagers may only read their own partner")
    partner = domain.get_or_404(store.partners, pid, "Partner")
    # read trigger: recompute scores with current clock, never fire status transitions
    return success(domain.partner_view(partner, recompute=True))


@bp.route("/partners/<pid>/remediate", methods=["POST"])
@endpoint(["ZoneOperator"])
def remediate_partner(user_id, role, pid):
    get_body()
    partner = domain.get_or_404(store.partners, pid, "Partner")
    if partner["status"] != "QUARANTINED":
        fail("ERR_INVALID_STATE", "Partner must be QUARANTINED to remediate")
    partner["status"] = "SUSPENDED"
    touch(partner)
    routing, _ = calc.partner_scores(partner["id"], now_dt())
    if routing >= calc.SCORE_FLOOR:
        partner["status"] = "ELIGIBLE"
        touch(partner)
    return success(domain.partner_view(partner))


@bp.route("/partners/<pid>/routing-assignments", methods=["GET"])
@endpoint(["ZoneOperator", "PartnerManager"])
def list_partner_assignments(user_id, role, pid):
    if role == "PartnerManager" and user_id != pid:
        fail("ERR_UNAUTHORIZED", "PartnerManagers may only list their own assignments")
    domain.get_or_404(store.partners, pid, "Partner")
    items = [a for a in store.assignments.values() if a["partner_id"] == pid]
    page, meta = paginate(items)
    return success([domain.assignment_view(a) for a in page], response_type="array",
                   pagination=meta)


@bp.route("/weight-tickets/<tid>/routing-assignments", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_assignment(user_id, role, tid):
    ticket = store.tickets.get(tid)
    get_body()
    if ticket is None:
        fail("ERR_NOT_FOUND", "WeightTicket not found: %s" % tid)
    # p5: ticket must be CERTIFIED or QUARANTINED
    if ticket["status"] not in ("CERTIFIED", "QUARANTINED"):
        fail("ERR_TICKET_NOT_CERTIFIED", "Ticket must be CERTIFIED")
    # p7: quarantine safety gate
    if ticket["status"] == "QUARANTINED":
        fail("ERR_TICKET_QUARANTINED", "Ticket is QUARANTINED")
    # p9i: no PENDING/ACCEPTED assignment for this ticket
    for a in store.assignments.values():
        if a["ticket_id"] == tid and a["status"] in ("PENDING", "ACCEPTED"):
            fail("ERR_ASSIGNMENT_PENDING_EXISTS", "An in-flight assignment exists for this ticket")
    # p9j: selector (fails with ERR_NO_ELIGIBLE_PARTNER when the pool is empty)
    partner = domain.routing_selector(ticket)
    rec = new_record()
    rec.update({
        "ticket_id": tid,
        "partner_id": partner["id"],
        "assigned_weight_kg": ticket["certified_weight_kg"],
        "status": "PENDING",
        "decline_reason": None,
    })
    store.assignments[rec["id"]] = rec
    return success(domain.assignment_view(rec), code=201)


@bp.route("/weight-tickets/<tid>/routing-assignments", methods=["GET"])
@endpoint(["ZoneOperator", "PartnerManager"])
def list_ticket_assignments(user_id, role, tid):
    domain.get_or_404(store.tickets, tid, "WeightTicket")
    items = [a for a in store.assignments.values() if a["ticket_id"] == tid]
    if role == "PartnerManager":
        items = [a for a in items if a["partner_id"] == user_id]
    page, meta = paginate(items)
    return success([domain.assignment_view(a) for a in page], response_type="array",
                   pagination=meta)


def _own_assignment_or_403(user_id, assignment):
    if assignment is not None and assignment["partner_id"] != user_id:
        fail("ERR_UNAUTHORIZED", "PartnerManagers may only act on their own assignments")


@bp.route("/routing-assignments/<aid>/accept", methods=["POST"])
@endpoint(["PartnerManager"])
def accept_assignment(user_id, role, aid):
    assignment = store.assignments.get(aid)
    _own_assignment_or_403(user_id, assignment)
    get_body()
    if assignment is None:
        fail("ERR_NOT_FOUND", "RoutingAssignment not found: %s" % aid)
    if assignment["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Assignment must be PENDING to accept")
    # p11: capacity re-check (equality allowed)
    partner = store.partners.get(assignment["partner_id"])
    committed, _ = domain.partner_amounts(partner["id"])
    if committed + calc.dec(assignment["assigned_weight_kg"]) > calc.dec(partner["capacity_kg"]):
        fail("ERR_PARTNER_CAPACITY_EXCEEDED", "Accept would exceed partner capacity")
    assignment["status"] = "ACCEPTED"
    touch(assignment)
    return success(domain.assignment_view(assignment))


@bp.route("/routing-assignments/<aid>/decline", methods=["POST"])
@endpoint(["PartnerManager"])
def decline_assignment(user_id, role, aid):
    assignment = store.assignments.get(aid)
    _own_assignment_or_403(user_id, assignment)
    body = get_body()
    check_fields(body, {"reason": ("str", False)})
    if assignment is None:
        fail("ERR_NOT_FOUND", "RoutingAssignment not found: %s" % aid)
    if assignment["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Assignment must be PENDING to decline")
    assignment["status"] = "DECLINED"
    assignment["decline_reason"] = body.get("reason")
    touch(assignment)
    return success(domain.assignment_view(assignment))


@bp.route("/routing-assignments/<aid>/complete", methods=["POST"])
@endpoint(["PartnerManager"])
def complete_assignment(user_id, role, aid):
    assignment = store.assignments.get(aid)
    _own_assignment_or_403(user_id, assignment)
    get_body()
    if assignment is None:
        fail("ERR_NOT_FOUND", "RoutingAssignment not found: %s" % aid)
    if assignment["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "Assignment must be ACCEPTED to complete")
    assignment["status"] = "COMPLETED"
    touch(assignment)
    return success(domain.assignment_view(assignment))
