"""Voucher endpoints."""
from flask import Blueprint, request

import services
from store import db
from web import authenticate, ok, ok_list, parse_pagination

bp = Blueprint("vouchers", __name__)


@bp.get("/api/vouchers/<voucher_id>")
def get_voucher(voucher_id):
    authenticate("ALL")
    v = services.get_or_404(db.vouchers, voucher_id)
    return ok(services.serialize(v))


@bp.get("/api/vouchers")
def list_vouchers():
    authenticate("ALL")
    limit, offset = parse_pagination()
    args = request.args
    items = list(db.vouchers.values())
    if args.get("booking_id") is not None:
        items = [v for v in items if v["booking_id"] == args.get("booking_id")]
    if args.get("passenger_id") is not None:
        items = [v for v in items if v["passenger_id"] == args.get("passenger_id")]
    page, total = services.paginate(items, limit, offset)
    return ok_list([services.serialize(v) for v in page], total, limit, offset)


@bp.post("/api/vouchers/<voucher_id>/redeem")
def redeem_voucher(voucher_id):
    authenticate({"SalesAgent"})
    v = services.get_or_404(db.vouchers, voucher_id)
    services.redeem_voucher(v)
    return ok(services.serialize(v))
