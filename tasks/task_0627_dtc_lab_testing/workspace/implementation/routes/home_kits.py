"""Home kits (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str, paginate,
)
from services.orders import order_lines_for

bp = Blueprint("home_kits", __name__)

HOME_KIT_BANNED_STATES = {"NY", "NJ", "RI"}


@bp.route("/catalog/home-kits", methods=["POST"])
def create_home_kit():
    user_id, role = require_role(["CatalogAdmin", "Patient"])
    body = get_json()
    order_id = require_str(body, "order_id")
    shipping_state = require_str(body, "shipping_state_code")
    order = require_found("orders", order_id)
    if role == "Patient" and user_id != order["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")

    patient = db.get("patients", order["patient_id"])
    # Shipping state must equal patient state and not be banned.
    if patient is None or shipping_state != patient["state_code"]:
        raise err("ERR_HOME_KIT_STATE_BANNED", "Shipping state must match patient state")
    if shipping_state in HOME_KIT_BANNED_STATES:
        raise err("ERR_HOME_KIT_STATE_BANNED", "Home kit cannot ship to this state")
    # Every order line offering must be home_kit_eligible.
    for ol in order_lines_for(order_id):
        offering = db.get("test_offerings", ol["test_offering_id"])
        if offering is None or not offering.get("home_kit_eligible"):
            raise err("ERR_HOME_KIT_STATE_BANNED", "Offering not home_kit_eligible")

    rec = db.new_record({
        "order_id": order_id,
        "shipping_state_code": shipping_state,
        "tracking_code": "TRK" + format(db.next_seq(), "08d"),
        "status": "SHIPPED",
    })
    db.insert("home_kits", rec)
    return success(serialize(rec), status=201)


@bp.route("/catalog/home-kits", methods=["GET"])
def list_home_kits():
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rows = db.sorted_rows(db.all_rows("home_kits"))
    order_id = request.args.get("order_id")
    if order_id:
        rows = [r for r in rows if r["order_id"] == order_id]
    if role == "Patient":
        owned = {o["id"] for o in db.all_rows("orders") if o["patient_id"] == user_id}
        rows = [r for r in rows if r["order_id"] in owned]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/home-kits/<rid>", methods=["GET"])
def get_home_kit(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rec = require_found("home_kits", rid)
    if role == "Patient":
        order = db.get("orders", rec["order_id"])
        if order and user_id != order["patient_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(rec))
