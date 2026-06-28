"""Physician orders (PWN review cycle) (PRD §3.5)."""
from flask import Blueprint, request

import db
import clock
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_enum, paginate,
)
from services.orders import line_terminal_cascade

bp = Blueprint("physician_orders", __name__)

DECISIONS = {"APPROVE", "DECLINE", "REQUEST_INFO"}
PWN_LICENSED_STATES = {"CA", "TX", "FL"}
PWN_MIN_AGE_YEARS = 18


@bp.route("/catalog/physician-orders", methods=["GET"])
def list_physician_orders():
    user_id, role = require_role(["OrderingPhysician", "Patient", "CatalogAdmin"])
    rows = db.sorted_rows(db.all_rows("physician_orders"))
    order_line_id = request.args.get("order_line_id")
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    if order_line_id:
        rows = [r for r in rows if r["order_line_id"] == order_line_id]
    if patient_id:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if role == "Patient":
        rows = [r for r in rows if r["patient_id"] == user_id]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/physician-orders/<rid>", methods=["GET"])
def get_physician_order(rid):
    user_id, role = require_role(["OrderingPhysician", "Patient", "CatalogAdmin"])
    po = require_found("physician_orders", rid)
    if role == "Patient" and user_id != po["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(po))


@bp.route("/catalog/physician-orders/<rid>/decision", methods=["POST"])
def decision(rid):
    user_id, role = require_role(["OrderingPhysician"])
    po = require_found("physician_orders", rid)
    body = get_json()
    dec = body.get("decision")
    require_enum(dec, DECISIONS, "decision")

    # Decision allowed only while SUBMITTED.
    if po["status"] != "SUBMITTED":
        raise err("ERR_PHYSICIAN_ORDER_NOT_REVIEWABLE", "Physician order not SUBMITTED")

    patient = db.get("patients", po["patient_id"])

    if dec == "APPROVE":
        # PWN licensure state then age.
        if patient is None or patient["state_code"] not in PWN_LICENSED_STATES:
            raise err("ERR_PWN_STATE_UNLICENSED", "Patient state not network-licensed")
        if clock.derived_age_years(patient["date_of_birth"]) < PWN_MIN_AGE_YEARS:
            raise err("ERR_PWN_AGE_INELIGIBLE", "Patient below minimum age")
        po["reviewing_physician_id"] = user_id
        if body.get("clinical_note") is not None:
            po["clinical_note"] = body.get("clinical_note")
        po["status"] = "APPROVED"
        db.touch(po)
        return success(serialize(po))

    if dec == "REQUEST_INFO":
        po["reviewing_physician_id"] = user_id
        if body.get("clinical_note") is not None:
            po["clinical_note"] = body.get("clinical_note")
        po["status"] = "NEEDS_MORE_INFO"
        db.touch(po)
        return success(serialize(po))

    # DECLINE: records physician, declines, fires decline cascade.
    po["reviewing_physician_id"] = user_id
    if body.get("clinical_note") is not None:
        po["clinical_note"] = body.get("clinical_note")
    po["status"] = "DECLINED"
    db.touch(po)

    # Cascade hop 1: owning OrderLine ORDERED -> REJECTED.
    line = db.get("order_lines", po["order_line_id"])
    if line is not None and line["status"] == "ORDERED":
        line["status"] = "REJECTED"
        db.touch(line)
        # Hops 2-3: invoice recompute + fulfillment bubble on the parent order.
        order = db.get("orders", line["order_id"])
        if order is not None:
            line_terminal_cascade(order)
    return success(serialize(po))


@bp.route("/catalog/physician-orders/<rid>/resubmit", methods=["POST"])
def resubmit(rid):
    user_id, role = require_role(["Patient"])
    po = require_found("physician_orders", rid)
    if user_id != po["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    if po["status"] != "NEEDS_MORE_INFO":
        raise err("ERR_PHYSICIAN_ORDER_NOT_RESUBMITTABLE", "Not in NEEDS_MORE_INFO")
    body = get_json()
    if body.get("clinical_note") is not None:
        po["clinical_note"] = body.get("clinical_note")
    po["status"] = "SUBMITTED"
    db.touch(po)
    return success(serialize(po))
