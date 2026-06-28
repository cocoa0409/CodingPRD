"""Specimens: process (mint LabResult), reject (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_number, paginate,
)
from services.orders import line_terminal_cascade
from services.results import provisional_flag

bp = Blueprint("specimens", __name__)


@bp.route("/catalog/specimens", methods=["GET"])
def list_specimens():
    user_id, role = require_role(["LabTech", "PhlebotomyTech", "CatalogAdmin", "Patient"])
    rows = db.sorted_rows(db.all_rows("specimens"))
    order_line_id = request.args.get("order_line_id")
    if order_line_id:
        rows = [r for r in rows if r["order_line_id"] == order_line_id]
    if role == "Patient":
        owned_lines = _patient_order_line_ids(user_id)
        rows = [r for r in rows if r["order_line_id"] in owned_lines]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/specimens/<rid>", methods=["GET"])
def get_specimen(rid):
    user_id, role = require_role(["LabTech", "PhlebotomyTech", "CatalogAdmin", "Patient"])
    rec = require_found("specimens", rid)
    if role == "Patient" and rec["order_line_id"] not in _patient_order_line_ids(user_id):
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(rec))


@bp.route("/catalog/specimens/<rid>/process", methods=["POST"])
def process_specimen(rid):
    require_role(["LabTech"])
    specimen = require_found("specimens", rid)
    body = get_json()
    analyzer_value = require_number(body, "analyzer_value")

    # Process only from COLLECTED.
    if specimen["status"] != "COLLECTED":
        raise err("ERR_RESULT_NOT_PROCESSABLE", "Specimen not in COLLECTED")

    line = db.get("order_lines", specimen["order_line_id"])
    order = db.get("orders", line["order_id"]) if line else None
    offering = db.get("test_offerings", line["test_offering_id"]) if line else None

    flag = provisional_flag(analyzer_value, offering or {})

    result = db.new_record({
        "specimen_id": specimen["id"],
        "order_line_id": specimen["order_line_id"],
        "patient_id": order["patient_id"] if order else None,
        "test_code": line["test_code"] if line else None,
        "analyzer_value": analyzer_value,
        "provisional_flag": flag,
        "final_flag": None,
        "critical_acknowledged": False,
        # CRITICAL provisional parks in PENDING_CRITICAL_CALLBACK; else PROCESSING.
        "status": "PENDING_CRITICAL_CALLBACK" if flag == "CRITICAL" else "PROCESSING",
    })
    db.insert("lab_results", result)

    specimen["status"] = "IN_ANALYSIS"
    db.touch(specimen)
    return success(serialize(result), status=201)


@bp.route("/catalog/specimens/<rid>/reject", methods=["POST"])
def reject_specimen(rid):
    require_role(["LabTech"])
    specimen = require_found("specimens", rid)
    line = db.get("order_lines", specimen["order_line_id"])

    # Rejectable only when line is COLLECTED and specimen in {COLLECTED, IN_ANALYSIS}.
    if (line is None or line["status"] != "COLLECTED"
            or specimen["status"] not in ("COLLECTED", "IN_ANALYSIS")):
        raise err("ERR_SPECIMEN_NOT_REJECTABLE", "Specimen not rejectable")

    specimen["status"] = "REJECTED"
    db.touch(specimen)
    line["status"] = "REJECTED"
    db.touch(line)

    order = db.get("orders", line["order_id"])
    if order is not None:
        line_terminal_cascade(order)
    return success(serialize(specimen))


def _patient_order_line_ids(patient_id):
    orders = {o["id"] for o in db.all_rows("orders") if o["patient_id"] == patient_id}
    return {ol["id"] for ol in db.all_rows("order_lines") if ol["order_id"] in orders}
