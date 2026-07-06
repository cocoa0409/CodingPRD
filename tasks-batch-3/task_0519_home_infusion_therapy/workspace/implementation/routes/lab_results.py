"""LabResult routes (PRD §3.7)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create
from middleware import require
from response import object_response, array_response

bp = Blueprint("lab_results", __name__)

LAB_TYPES = {"TROUGH", "PEAK", "CMP", "CBC"}
READ_ROLES = ["VisitingNurse", "MedicalDirector", "Pharmacist"]


@bp.route("/lab-results", methods=["POST"])
def create_lab():
    require(["VisitingNurse", "MedicalDirector"])
    body = helpers.get_body()
    # existence (3) before other body validity (4) per PRD §2.8
    order_id = helpers.as_str(body, "order_id")
    if order_id not in db.infusion_orders:
        raise errors.not_found("Infusion order not found")
    lab_type = helpers.as_enum(body, "lab_type", LAB_TYPES)
    value_num = helpers.as_number(body, "value_num")
    collected_at = helpers.as_datetime(body, "collected_at")
    is_critical = helpers.as_bool(body, "is_critical", default=False)

    lab = stamp_create({
        "order_id": order_id,
        "lab_type": lab_type,
        "value_num": value_num,
        "collected_at": body["collected_at"],
        "is_critical": is_critical,
    })
    db.lab_results[lab["id"]] = lab
    return object_response(lab, 201)


@bp.route("/lab-results/<id>", methods=["GET"])
def get_lab(id):
    require(READ_ROLES)
    lab = db.lab_results.get(id)
    if lab is None:
        raise errors.not_found("Lab result not found")
    return object_response(lab, 200)


@bp.route("/lab-results", methods=["GET"])
def list_labs():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.lab_results.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)
