"""Cart assignment (PRD §3.2). is_extra is derived per stream: the first ACTIVE
TRASH and first ACTIVE RECYCLING cart a plan provisions are non-extra; any
further ACTIVE cart of that stream is an extra."""
from flask import Blueprint, request

import db
from response import ok, ok_list
from routes.helpers import gate, require_ownership
from services import validate as V
from services.common import new_record, touch, sort_by_created
from services.lookup import get_or_404
from services.serialize import cart_out

bp = Blueprint("carts", __name__)

CART_TYPES = {"TRASH", "RECYCLING"}
CART_SIZES = {35, 65, 96}


def recompute_is_extra(account_id):
    """For each stream, the earliest-created ACTIVE cart is provisioned
    (is_extra=False); subsequent ACTIVE carts of that stream are is_extra=True.
    REMOVED carts retain their last is_extra value and do not count."""
    for stream in CART_TYPES:
        carts = [
            c for c in db.cart_assignments.values()
            if c["account_id"] == account_id and c["status"] == "ACTIVE" and c["cart_type"] == stream
        ]
        carts.sort(key=lambda c: (c["created_at"], c["_seq"]))
        for idx, c in enumerate(carts):
            new_val = idx > 0
            if c["is_extra"] != new_val:
                c["is_extra"] = new_val
                touch(c)


@bp.route("/accounts/<aid>/carts", methods=["POST"])
def assign_cart(aid):
    gate({"Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    body = V.get_body(request)
    cart_type = V.require_enum(body, "cart_type", CART_TYPES)
    size = V.require_int(body, "size_gallons", allowed=CART_SIZES)

    rec = new_record({
        "account_id": a["id"],
        "cart_type": cart_type,
        "size_gallons": size,
        "is_extra": False,
        "status": "ACTIVE",
    })
    db.cart_assignments[rec["id"]] = rec
    recompute_is_extra(a["id"])
    return ok(cart_out(rec), 201)


@bp.route("/accounts/<aid>/carts", methods=["GET"])
def list_carts(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    limit, offset = V.parse_pagination(request.args)
    items = [c for c in db.cart_assignments.values() if c["account_id"] == a["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([cart_out(c) for c in page], limit, offset, total)


@bp.route("/carts/<cid>/remove", methods=["POST"])
def remove_cart(cid):
    gate({"Dispatcher"})
    c = get_or_404(db.cart_assignments, cid)
    c["status"] = "REMOVED"
    touch(c)
    recompute_is_extra(c["account_id"])
    return ok(cart_out(c))
