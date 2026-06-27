"""Clients, no-show strikes, deposit regime (PRD §3.4)."""
from flask import Blueprint, request

from common import (json_body, make_record, get_str, parse_pagination, paginate)
from db import db
from errors import err, ERR_DUPLICATE_RESOURCE, ERR_FORBIDDEN
from middleware import authorize
from lookup import get_client
from response import success_object, success_list
from serialize import client_out, appointment_out, gift_card_out

bp = Blueprint("clients", __name__)


@bp.route("/clients", methods=["POST"])
def create_client():
    authorize({"FrontDesk", "SalonManager"})
    body = json_body(optional=False)
    full_name = get_str(body, "full_name", required=True)
    email = get_str(body, "email", required=True)

    for c in db.clients.values():
        if c["email"] == email:
            raise err(ERR_DUPLICATE_RESOURCE, "Client email already exists")

    rec = make_record({
        "full_name": full_name,
        "email": email,
        "loyalty_points_balance": 0,
        "_raw_strikes": 0,            # stored raw strike count; decayed on read
        "last_no_show_at": None,
    })
    db.clients[rec["id"]] = rec
    return success_object(client_out(rec), status=201)


@bp.route("/clients", methods=["GET"])
def list_clients():
    authorize({"FrontDesk", "SalonManager"})
    items = list(db.clients.values())
    email = request.args.get("email")
    if email is not None:
        items = [c for c in items if c["email"] == email]
    dr = request.args.get("deposit_required")
    if dr is not None:
        from derive import client_effective_strikes
        want = dr.lower() == "true"
        items = [c for c in items if client_effective_strikes(c)[1] == want]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([client_out(c) for c in page], limit, offset, total)


@bp.route("/clients/<cid>", methods=["GET"])
def get_one_client(cid):
    user_id, role = authorize({"FrontDesk", "SalonManager", "Client"})
    rec = get_client(cid)
    if role == "Client" and user_id != rec["id"]:
        raise err(ERR_FORBIDDEN, "Client may only read their own record")
    # active_no_show_strikes and deposit_required are recomputed on read in
    # client_out via the logical clock (PRD §3.4).
    return success_object(client_out(rec), status=200)


@bp.route("/clients/<cid>/appointments", methods=["GET"])
def client_appointments(cid):
    user_id, role = authorize({"FrontDesk", "SalonManager", "Client"})
    rec = get_client(cid)
    if role == "Client" and user_id != rec["id"]:
        raise err(ERR_FORBIDDEN, "Client may only read their own appointments")
    items = [a for a in db.appointments.values() if a["client_id"] == cid]
    bs = request.args.get("booking_status")
    if bs is not None:
        items = [a for a in items if a["booking_status"] == bs]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([appointment_out(a) for a in page], limit, offset, total)


@bp.route("/clients/<cid>/gift-cards", methods=["GET"])
def client_gift_cards(cid):
    user_id, role = authorize({"FrontDesk", "SalonManager", "Client"})
    rec = get_client(cid)
    if role == "Client" and user_id != rec["id"]:
        raise err(ERR_FORBIDDEN, "Client may only read their own gift cards")
    items = [g for g in db.gift_cards.values() if g["purchaser_client_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [g for g in items if g["status"] == st]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([gift_card_out(g) for g in page], limit, offset, total)
