from flask import Blueprint, request

import db
import response
from middleware import get_user_context, require_role, require_ownership
from services import lookup, serialize, paginate, transfer_ops

bp = Blueprint("transfers", __name__)

READ_ROLES = ("PlatformAdmin", "Seller", "Buyer", "TrustSafety")


def _seller_of_order(order):
    listing = db.listings.get(order["listing_id"])
    return listing["seller_id"] if listing else None


@bp.post("/orders/<order_id>/transfers")
def initiate_transfer(order_id):
    user_id, role = get_user_context()
    require_role(role, ("Seller",))
    order = lookup.get_order(order_id)
    listing = db.listings.get(order["listing_id"])
    require_ownership(role, user_id, listing["seller_id"])
    event = db.events.get(listing["event_id"])
    transfer = transfer_ops.initiate(order, listing, event)
    return response.object_response(serialize.public(transfer), 201)


@bp.get("/transfers/<transfer_id>")
def get_transfer(transfer_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    transfer = lookup.get_transfer(transfer_id)
    return response.object_response(serialize.public(transfer), 200)


@bp.get("/transfers")
def list_transfers():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    order_id = request.args.get("order_id")
    records = list(db.transfers.values())
    if order_id is not None:
        records = [t for t in records if t["order_id"] == order_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


@bp.post("/transfers/<transfer_id>/send")
def send(transfer_id):
    user_id, role = get_user_context()
    require_role(role, ("Seller",))
    transfer = lookup.get_transfer(transfer_id)
    order = db.orders.get(transfer["order_id"])
    listing = db.listings.get(order["listing_id"])
    require_ownership(role, user_id, listing["seller_id"])
    event = db.events.get(listing["event_id"])
    transfer_ops.send(transfer, order, event)
    return response.object_response(serialize.public(transfer), 200)


@bp.post("/transfers/<transfer_id>/accept")
def accept(transfer_id):
    user_id, role = get_user_context()
    require_role(role, ("Buyer",))
    transfer = lookup.get_transfer(transfer_id)
    order = db.orders.get(transfer["order_id"])
    require_ownership(role, user_id, order["buyer_id"])
    transfer_ops.accept(transfer, order)
    return response.object_response(serialize.public(transfer), 200)


@bp.post("/transfers/<transfer_id>/fail")
def fail(transfer_id):
    user_id, role = get_user_context()
    require_role(role, ("Seller",))
    transfer = lookup.get_transfer(transfer_id)
    order = db.orders.get(transfer["order_id"])
    listing = db.listings.get(order["listing_id"])
    require_ownership(role, user_id, listing["seller_id"])
    transfer_ops.fail(transfer, order)
    return response.object_response(serialize.public(transfer), 200)


@bp.post("/transfers/<transfer_id>/recall")
def recall(transfer_id):
    user_id, role = get_user_context()
    require_role(role, ("Seller",))
    transfer = lookup.get_transfer(transfer_id)
    order = db.orders.get(transfer["order_id"])
    listing = db.listings.get(order["listing_id"])
    require_ownership(role, user_id, listing["seller_id"])
    transfer_ops.recall(transfer, order)
    return response.object_response(serialize.public(transfer), 200)
