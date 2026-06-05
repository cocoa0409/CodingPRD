"""Tip routes: create (folds into payout), read, list."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     parse_pagination, paginate, ownership_customer)
from response import success, list_success

bp = Blueprint("tips", __name__)


@bp.route("/cleaning/tips", methods=["POST"])
def create_tip():
    principal = authenticate()
    authorize(principal, {"Customer"})
    body = get_json_body()
    require_fields(body, ["booking_id", "customer_id", "amount_cents"])
    # Existence left-to-right: booking_id then customer_id.
    booking = require_resource(db.bookings, body["booking_id"], "booking")
    customer = require_resource(db.customers, body["customer_id"], "customer")
    ownership_customer(principal, customer["id"])

    # Tip permissibility (priority 14): COMPLETED booking, owned by tipper,
    # at most one tip per booking.
    if booking["status"] != "COMPLETED":
        raise err("ERR_TIP_NOT_ALLOWED", "tip only allowed on a COMPLETED booking")
    if booking["customer_id"] != customer["id"]:
        raise err("ERR_TIP_NOT_ALLOWED", "tipper does not own the booking")
    for t in db.tips.values():
        if t["booking_id"] == booking["id"]:
            raise err("ERR_TIP_NOT_ALLOWED", "booking already tipped")

    amount = body["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be a positive integer")

    rec = {
        "booking_id": booking["id"],
        "customer_id": customer["id"],
        "cleaner_id": booking.get("cleaner_id"),
        "amount_cents": amount,
    }
    db.insert(db.tips, rec, append_only=True)

    # tip_attach: fold into the booking's existing CleanerPayout.
    for payout in db.cleaner_payouts.values():
        if payout["booking_id"] == booking["id"]:
            payout["tip_cents"] = amount
            payout["total_cents"] = payout["base_payout_cents"] + amount
            db.touch(payout)
            break

    return success(S.tip(rec), status=201)


@bp.route("/cleaning/tips/<tid>", methods=["GET"])
def get_tip(tid):
    principal = authenticate()
    authorize(principal, {"Customer", "Cleaner", "PlatformAdmin"})
    rec = require_resource(db.tips, tid, "tip")
    if principal.role == "Customer" and principal.user_id != rec["customer_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "customer does not own this tip")
    if principal.role == "Cleaner" and principal.user_id != rec.get("cleaner_id"):
        raise err("ERR_FORBIDDEN_OWNERSHIP", "tip is not for this cleaner")
    return success(S.tip(rec), status=200)


@bp.route("/cleaning/tips", methods=["GET"])
def list_tips():
    principal = authenticate()
    authorize(principal, {"Customer", "Cleaner", "PlatformAdmin"})
    limit, offset = parse_pagination()
    records = list(db.tips.values())
    for key in ("booking_id", "customer_id", "cleaner_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    if principal.role == "Customer":
        records = [r for r in records if r["customer_id"] == principal.user_id]
    elif principal.role == "Cleaner":
        records = [r for r in records if r.get("cleaner_id") == principal.user_id]
    page, total = paginate(records, limit, offset)
    return list_success([S.tip(r) for r in page], limit, offset, total)
