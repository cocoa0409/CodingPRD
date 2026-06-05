from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_roles
from response import success, list_success
from services import validate as V
from services.common import new_common, touch, paginate, page_slice
from services.cascade import recompute_buddy_remaining
from services.serialize import buddy_ticket_out, compute_buddy_remaining

bp = Blueprint("buddy_tickets", __name__)

READ_ROLES = {"NetworkAdmin", "ResortOps", "RefundAdmin"}


@bp.post("/buddy-tickets")
def reserve_buddy_ticket():
    _, role = authenticate()
    require_roles(role, {"ResortOps"})
    body = V.get_body(request)
    # Reference order Pass -> Resort (PRD §2.5). Referenced-resource existence
    # (priority 3) precedes other body-field validity (priority 4): validate
    # each reference identifier, resolve it, then validate remaining fields.
    pass_id = V.require_str(body, "pass_id")
    pass_rec = db.passes.get(pass_id)
    if pass_rec is None:
        raise errors.not_found("Pass not found")
    resort_id = V.require_str(body, "resort_id")
    resort = db.resorts.get(resort_id)
    if resort is None:
        raise errors.not_found("Resort not found")
    guest_name = V.require_str(body, "guest_name")
    valid_date = V.require_date(body, "valid_date")

    # State guard (priority 6): a pass cannot grant buddy-ticket benefits until
    # it is ACTIVE (PRD §3.2). Wins over the fiscal allotment check (priority 12).
    if pass_rec["status"] != "ACTIVE":
        raise errors.invalid_state("Host pass is not ACTIVE")

    # Allotment guard (ERR_BUDDY_ALLOTMENT_EXHAUSTED, priority 12).
    remaining = compute_buddy_remaining(pass_rec)
    if remaining < 1:
        raise errors.ApiError(errors.ERR_BUDDY_ALLOTMENT_EXHAUSTED, 409,
                              "Pass buddy-ticket allotment is exhausted")

    # Same-day double-book guard (ERR_BUDDY_DATE_CONFLICT, priority 13).
    for b in db.buddy_tickets.values():
        if (b["guest_name"] == guest_name and b["valid_date"] == valid_date
                and b["resort_id"] == resort_id and b["status"] != "CANCELLED"):
            raise errors.ApiError(errors.ERR_BUDDY_DATE_CONFLICT, 409,
                                  "Guest already holds a buddy ticket for this date at this resort")

    product = db.pass_products.get(pass_rec["pass_product_id"])
    price = product["buddy_ticket_price_cents"] if product else 0

    rec = new_common({
        "pass_id": pass_id,
        "resort_id": resort_id,
        "guest_name": guest_name,
        "valid_date": valid_date,
        "price_charged_cents": price,
        "status": "RESERVED",
    })
    db.buddy_tickets[rec["id"]] = rec
    recompute_buddy_remaining(pass_rec)
    return success(buddy_ticket_out(rec), status=201)


@bp.get("/buddy-tickets")
def list_buddy_tickets():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = paginate(request.args)
    pass_id = request.args.get("pass_id")
    records = list(db.buddy_tickets.values())
    if pass_id is not None:
        records = [b for b in records if b["pass_id"] == pass_id]
    window, total = page_slice(records, limit, offset)
    return list_success([buddy_ticket_out(b) for b in window], limit, offset, total)


@bp.get("/buddy-tickets/<bid>")
def get_buddy_ticket(bid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.buddy_tickets.get(bid)
    if rec is None:
        raise errors.not_found("Buddy ticket not found")
    return success(buddy_ticket_out(rec))


@bp.post("/buddy-tickets/<bid>/redeem")
def redeem_buddy_ticket(bid):
    _, role = authenticate()
    require_roles(role, {"ResortOps"})
    rec = db.buddy_tickets.get(bid)
    if rec is None:
        raise errors.not_found("Buddy ticket not found")
    if rec["status"] != "RESERVED":
        raise errors.invalid_state("Buddy ticket is not RESERVED")
    pass_rec = db.passes.get(rec["pass_id"])
    if pass_rec is None or pass_rec["status"] != "ACTIVE":
        raise errors.invalid_state("Host pass is not ACTIVE")
    rec["status"] = "REDEEMED"
    touch(rec)
    return success(buddy_ticket_out(rec))


@bp.post("/buddy-tickets/<bid>/cancel")
def cancel_buddy_ticket(bid):
    _, role = authenticate()
    require_roles(role, {"ResortOps"})
    rec = db.buddy_tickets.get(bid)
    if rec is None:
        raise errors.not_found("Buddy ticket not found")
    if rec["status"] != "RESERVED":
        raise errors.invalid_state("Buddy ticket is not RESERVED")
    rec["status"] = "CANCELLED"
    touch(rec)
    pass_rec = db.passes.get(rec["pass_id"])
    if pass_rec is not None:
        recompute_buddy_remaining(pass_rec)
    return success(buddy_ticket_out(rec))
