"""B2B BulkOrder quote/read/list/confirm/activate/cancel (PRD §3.9)."""

from flask import Blueprint, request

from db import db
from core import (
    get_body, stamp_new, touch,
    paginate, check_str, check_int, round_half_up, post_ledger,
)
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_bulk_order
import serialize

bp = Blueprint("bulk_orders", __name__)


def _buyer_owner_ok(order, uid, role):
    if role == "B2BBuyer" and order["buyer_customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "Not the owner of this bulk order.")


@bp.post("/v1/bulk-orders")
def quote_bulk_order():
    uid, role = get_identity()
    require_role(role, {"B2BBuyer", "ProgramAdmin"})
    body = get_body()
    program_id = check_str(body, "program_id")
    buyer_customer_id = check_str(body, "buyer_customer_id")
    card_count = check_int(body, "card_count")
    face_value = check_int(body, "face_value_cents")
    state_code = check_str(body, "state_code")

    # Body FK existence (priority 5).
    if program_id not in db.programs:
        raise err("ERR_REFERENCE_NOT_FOUND", "program_id does not exist.")
    if buyer_customer_id not in db.customers:
        raise err("ERR_REFERENCE_NOT_FOUND", "buyer_customer_id does not exist.")

    # B2BBuyer ownership: quotes on their own behalf.
    if role == "B2BBuyer" and buyer_customer_id != uid:
        raise err("ERR_FORBIDDEN", "B2BBuyer may only quote own bulk order.")

    # Domain shape (priority 6).
    if card_count < 1 or face_value <= 0:
        raise err("ERR_INVALID_REDEMPTION", "card_count must be >= 1 and face_value_cents > 0.")

    b = {
        "program_id": program_id,
        "buyer_customer_id": buyer_customer_id,
        "card_count": card_count,
        "face_value_cents": face_value,
        "state_code": state_code,
        "net_invoice_cents": None,
        "status": "QUOTED",
    }
    stamp_new(b)
    db.bulk_orders[b["id"]] = b
    return success(serialize.bulk_order(b), status=201)


@bp.get("/v1/bulk-orders/<bulk_order_id>")
def read_bulk_order(bulk_order_id):
    uid, role = get_identity()
    require_role(role, {"B2BBuyer", "ProgramAdmin"})
    b = get_bulk_order(bulk_order_id)
    _buyer_owner_ok(b, uid, role)
    return success(serialize.bulk_order(b))


@bp.get("/v1/bulk-orders")
def list_bulk_orders():
    uid, role = get_identity()
    require_role(role, {"B2BBuyer", "ProgramAdmin"})
    items = list(db.bulk_orders.values())
    for key in ("program_id", "buyer_customer_id"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    # B2BBuyer sees only their own orders.
    if role == "B2BBuyer":
        items = [b for b in items if b["buyer_customer_id"] == uid]
    page, pg = paginate(items)
    return success([serialize.bulk_order(b) for b in page], pagination=pg)


@bp.post("/v1/bulk-orders/<bulk_order_id>/confirm")
def confirm_bulk_order(bulk_order_id):
    uid, role = get_identity()
    require_role(role, {"B2BBuyer"})
    b = get_bulk_order(bulk_order_id)
    _buyer_owner_ok(b, uid, role)
    buyer = db.customers[b["buyer_customer_id"]]
    program = db.programs[b["program_id"]]

    # Corporate-buyer gate (PRD §3.9) then state.
    if not buyer["is_corporate"]:
        raise err("ERR_NOT_CORPORATE_BUYER", "Buyer is not a corporate customer.")
    if b["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Bulk order is not QUOTED.")

    # Pricing: round per card BEFORE multiplying (PRD §3.9, §2.7).
    per_card_net = round_half_up(b["face_value_cents"] * (1 - program["b2b_discount_pct"]))
    b["net_invoice_cents"] = per_card_net * b["card_count"]
    b["status"] = "CONFIRMED"
    touch(b)
    return success(serialize.bulk_order(b))


@bp.post("/v1/bulk-orders/<bulk_order_id>/activate")
def activate_bulk_order(bulk_order_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    b = get_bulk_order(bulk_order_id)
    if b["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Bulk order is not CONFIRMED.")

    # Mint card_count ACTIVE cards, each LOADed face_value_cents (PRD §3.9).
    for _ in range(b["card_count"]):
        c = {
            "program_id": b["program_id"],
            "owner_customer_id": b["buyer_customer_id"],
            "form_factor": "DIGITAL",
            "state_code": b["state_code"],
            "lifecycle_status": "ACTIVE",
            "risk_status": "CLEAR",
            "replaced_by_card_id": None,
            "activated_at": None,
        }
        stamp_new(c)
        db.cards[c["id"]] = c
        entry = post_ledger(c, "LOAD", b["face_value_cents"], source_ref_id=b["id"])
        c["activated_at"] = entry["created_at"]

    b["status"] = "ACTIVATED"
    touch(b)
    return success(serialize.bulk_order(b))


@bp.post("/v1/bulk-orders/<bulk_order_id>/cancel")
def cancel_bulk_order(bulk_order_id):
    uid, role = get_identity()
    require_role(role, {"B2BBuyer"})
    b = get_bulk_order(bulk_order_id)
    _buyer_owner_ok(b, uid, role)
    if b["status"] not in ("QUOTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Only QUOTED/CONFIRMED orders may be cancelled.")
    b["status"] = "CANCELLED"
    touch(b)
    return success(serialize.bulk_order(b))
