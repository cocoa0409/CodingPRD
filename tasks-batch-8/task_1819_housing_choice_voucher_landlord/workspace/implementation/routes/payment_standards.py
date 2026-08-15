"""PaymentStandard endpoints."""

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import parse_pagination, sorted_page

bp = Blueprint("payment_standards", __name__)


def serialize_payment_standard(p):
    return {
        "id": p["id"],
        "zip_code": p["zip_code"],
        "bedroom_count": p["bedroom_count"],
        "amount_cents": p["amount_cents"],
        "effective_from": p["effective_from"],
        "effective_to": p.get("effective_to"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/hcv/payment-standards", methods=["POST"])
def create_payment_standard():
    require_roles("HousingAuthorityAdmin")
    body = request.get_json(force=True, silent=True) or {}
    rec = db.make_record({
        "zip_code": body.get("zip_code"),
        "bedroom_count": body.get("bedroom_count"),
        "amount_cents": body.get("amount_cents"),
        "effective_from": body.get("effective_from"),
        "effective_to": body.get("effective_to"),
    })
    db.payment_standards[rec["id"]] = rec
    return success_object(serialize_payment_standard(rec), 201)


@bp.route("/hcv/payment-standards", methods=["GET"])
def list_payment_standards():
    require_roles("HousingAuthorityAdmin", "Landlord")
    limit, offset = parse_pagination()
    zip_code = request.args.get("zip_code")
    bedroom_count = request.args.get("bedroom_count")
    rows = list(db.payment_standards.values())
    if zip_code is not None:
        rows = [r for r in rows if r["zip_code"] == zip_code]
    if bedroom_count is not None:
        try:
            bc = int(bedroom_count)
            rows = [r for r in rows if r["bedroom_count"] == bc]
        except ValueError:
            rows = []
    page, total = sorted_page(rows, limit, offset)
    return success_list([serialize_payment_standard(p) for p in page], total, limit, offset)
