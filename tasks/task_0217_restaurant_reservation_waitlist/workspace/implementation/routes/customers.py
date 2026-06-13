"""Customer routes (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err, ERR_DUPLICATE_PHONE
from middleware import require_roles
from response import object_response
from services import calc
from services.lookup import get_or_404
from services.cascades import block_customer
from validators import get_body, require_str, require_phone, opt_str

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def register_customer():
    # Self-registration: no authentication required (PRD §2.1).
    body = get_body()
    full_name = require_str(body, "full_name")
    phone = require_phone(body, "phone")
    email = opt_str(body, "email", None)
    # phone unique across customers
    for c in db.customers.values():
        if c["phone"] == phone:
            raise err(ERR_DUPLICATE_PHONE, "phone already in use")

    rec = db.base_fields()
    rec.update({
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "no_show_strikes": 0,
        "lifetime_reservations": 0,
        "lifetime_failures": 0,
        "settled_reliability_pct": 100.0,
        "status": "ACTIVE",
    })
    db.customers[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


@bp.get("/customers/<cid>")
def read_customer(cid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.customers, cid)
    return object_response(db.serialize(rec), 200)


@bp.get("/customers/<cid>/reliability")
def customer_reliability(cid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.customers, cid)
    mode = request.args.get("mode", "settled")
    open_confirmed = sum(
        1 for r in db.reservations.values()
        if r["customer_id"] == cid and r["status"] == "CONFIRMED"
    )
    if mode == "provisional":
        reliability = calc.provisional_reliability(
            rec["lifetime_reservations"], rec["lifetime_failures"], open_confirmed)
        open_count = open_confirmed
    else:
        mode = "settled"
        reliability = calc.settled_reliability(
            rec["lifetime_reservations"], rec["lifetime_failures"])
        open_count = 0
    out = {
        "customer_id": cid,
        "mode": mode,
        "reliability_pct": reliability,
        "lifetime_reservations": rec["lifetime_reservations"],
        "lifetime_failures": rec["lifetime_failures"],
        "open_confirmed_count": open_count,
    }
    return object_response(out, 200)


@bp.post("/customers/<cid>/block")
def block(cid):
    require_roles({"Manager"})
    rec = get_or_404(db.customers, cid)
    # Find a restaurant context is not needed; block + mass-cancel use no
    # restaurant threshold (manual block). Pass any restaurant of the customer's
    # reservations for fee context (block-cancel is early -> fee 0 regardless).
    block_customer(rec, restaurant=None)
    return object_response(db.serialize(rec), 200)


@bp.post("/customers/<cid>/unblock")
def unblock(cid):
    require_roles({"Manager"})
    rec = get_or_404(db.customers, cid)
    rec["status"] = "ACTIVE"
    rec["no_show_strikes"] = 0
    db.touch(rec)
    return object_response(db.serialize(rec), 200)
