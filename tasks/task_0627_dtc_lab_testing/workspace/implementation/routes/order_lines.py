"""Order lines and specimen collection (PRD §3.5)."""
from flask import Blueprint, request

import db
import clock
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import serialize, serialize_list, require_found, paginate

bp = Blueprint("order_lines", __name__)


@bp.route("/catalog/order-lines", methods=["GET"])
def list_order_lines():
    user_id, role = require_role(["Patient", "CatalogAdmin", "LabTech", "PhlebotomyTech"])
    rows = db.sorted_rows(db.all_rows("order_lines"))
    order_id = request.args.get("order_id")
    offering_id = request.args.get("test_offering_id")
    if order_id:
        rows = [r for r in rows if r["order_id"] == order_id]
    if offering_id:
        rows = [r for r in rows if r["test_offering_id"] == offering_id]
    if role == "Patient":
        owned = {o["id"] for o in db.all_rows("orders") if o["patient_id"] == user_id}
        rows = [r for r in rows if r["order_id"] in owned]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/order-lines/<rid>", methods=["GET"])
def get_order_line(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin", "LabTech", "PhlebotomyTech"])
    line = require_found("order_lines", rid)
    if role == "Patient":
        order = db.get("orders", line["order_id"])
        if order and user_id != order["patient_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(line))


@bp.route("/catalog/order-lines/<rid>/collect", methods=["POST"])
def collect(rid):
    user_id, role = require_role(["PhlebotomyTech"])
    line = require_found("order_lines", rid)
    order = db.get("orders", line["order_id"])

    # State preconditions (PRD §3.5).
    if line["status"] != "ORDERED":
        raise err("ERR_ORDER_LINE_NOT_COLLECTIBLE", "Order line not in ORDERED")
    if order["fulfillment_status"] not in ("AWAITING_COLLECTION", "IN_PROCESSING"):
        raise err("ERR_ORDER_NOT_COLLECTABLE_STATE", "Order not in a collectable state")

    # PWN gate: restricted line needs an APPROVED physician order.
    if line.get("requires_physician_order"):
        approved = any(
            po["order_line_id"] == line["id"] and po["status"] == "APPROVED"
            for po in db.all_rows("physician_orders")
        )
        if not approved:
            raise err("ERR_PHYSICIAN_ORDER_REQUIRED", "No APPROVED physician order")

    # PSC orders require a CHECKED_IN appointment for the order.
    if order["fulfillment_mode"] == "PSC":
        checked_in = any(
            ap["order_id"] == order["id"] and ap["status"] == "CHECKED_IN"
            for ap in db.all_rows("appointments")
        )
        if not checked_in:
            raise err("ERR_APPOINTMENT_NOT_CHECKED_IN", "No CHECKED_IN appointment")

    # Mint specimen.
    specimen = db.new_record({
        "order_line_id": line["id"],
        "collected_by_user_id": user_id,
        "accession_code": "ACC" + format(db.next_seq(), "08d"),
        "collected_at": clock.now_iso(),
        "status": "COLLECTED",
    })
    db.insert("specimens", specimen)

    line["status"] = "COLLECTED"
    db.touch(line)

    # First collect advances AWAITING_COLLECTION -> IN_PROCESSING.
    if order["fulfillment_status"] == "AWAITING_COLLECTION":
        order["fulfillment_status"] = "IN_PROCESSING"
    db.touch(order)

    return success(serialize(specimen), status=201)
