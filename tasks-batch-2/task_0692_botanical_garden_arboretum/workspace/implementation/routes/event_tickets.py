"""EventTicket routes + refund (PRD §3.4)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize, calc
from services.common import (
    new_record, get_body, get_or_404, paginate, touch,
    req_str, opt_str, req_int,
)

bp = Blueprint("event_tickets", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


@bp.route("/v1/event-tickets", methods=["POST"])
def create_event_ticket():
    _, role = get_identity()
    require_role(role, {"Visitor", "GardenStaff"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    exhibit_name = req_str(body, "exhibit_name")
    list_price_cents = req_int(body, "list_price_cents", min_value=0)
    quantity = req_int(body, "quantity", min_value=1)
    membership_id = opt_str(body, "membership_id", "")

    garden = get_or_404(db.gardens, garden_id)
    membership = None
    if membership_id:
        membership = get_or_404(db.memberships, membership_id)
        if membership["garden_id"] != garden_id:
            raise errors.cross_garden_reference()

    # Member discount applies only if membership attached AND ACTIVE (PRD §3.4).
    applies = False
    discount_pct = 0
    if membership is not None and membership["status"] == "ACTIVE":
        plan = db.membership_plans.get(membership["plan_id"])
        if plan is not None:
            applies = True
            discount_pct = plan["event_discount_pct"]
    charged_cents = calc.event_ticket_charge(
        list_price_cents, quantity, applies, discount_pct)

    rec = new_record({
        "garden_id": garden_id,
        "membership_id": membership_id,
        "exhibit_name": exhibit_name,
        "list_price_cents": list_price_cents,
        "quantity": quantity,
        "charged_cents": charged_cents,
        "status": "PURCHASED",
    })
    db.event_tickets[rec["id"]] = rec
    return success(serialize.event_ticket(rec), status=201)


@bp.route("/v1/event-tickets/<ticket_id>", methods=["GET"])
def read_event_ticket(ticket_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.event_tickets, ticket_id)
    return success(serialize.event_ticket(rec), status=200)


@bp.route("/v1/event-tickets", methods=["GET"])
def list_event_tickets():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    records = list(db.event_tickets.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.event_ticket(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/event-tickets/<ticket_id>/refund", methods=["POST"])
def refund_event_ticket(ticket_id):
    _, role = get_identity()
    require_role(role, {"GardenStaff", "GardenAdmin"})
    rec = get_or_404(db.event_tickets, ticket_id)
    # Refund permitted only on a PURCHASED ticket (PRD §3.4).
    if rec["status"] != "PURCHASED":
        raise errors.refund_not_allowed()
    rec["status"] = "REFUNDED"
    touch(rec)
    return success(serialize.event_ticket(rec), status=200)
