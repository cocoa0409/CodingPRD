"""Payments (read-only) and the logical clock endpoint (PRD §2.4, §3)."""
from flask import Blueprint, request

import db
import clock
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str, paginate,
)

bp = Blueprint("payments", __name__)


@bp.route("/catalog/payments", methods=["GET"])
def list_payments():
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rows = db.sorted_rows(db.all_rows("payments"))
    order_id = request.args.get("order_id")
    if order_id:
        rows = [r for r in rows if r["order_id"] == order_id]
    if role == "Patient":
        owned = {o["id"] for o in db.all_rows("orders") if o["patient_id"] == user_id}
        rows = [r for r in rows if r["order_id"] in owned]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/payments/<rid>", methods=["GET"])
def get_payment(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rec = require_found("payments", rid)
    if role == "Patient":
        order = db.get("orders", rec["order_id"])
        if order and user_id != order["patient_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(rec))


@bp.route("/catalog/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role(["CatalogAdmin"])
    body = get_json()
    to_iso = require_str(body, "to_iso8601")
    try:
        clock.set_now(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    return success({"now": clock.now_iso()})
