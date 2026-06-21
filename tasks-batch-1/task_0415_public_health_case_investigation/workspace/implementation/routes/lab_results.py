"""Lab result intake, listing, supersede."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (base_entity, touch, parse_pagination, sorted_by_creation,
                     get_or_404, get_in_program_or_404, require_string,
                     require_enum, parse_dt)
from middleware import get_user_context, require_role
from response import success, success_list
from serializers import ser_lab_result
from calculations import recompute_linked_positive, compute_completeness
from routes.config import ALL_ROLES

bp = Blueprint("lab_results", __name__)

RESULT_VALUES = {"POSITIVE", "NEGATIVE", "INDETERMINATE"}


@bp.route("/surveillance/lab-results", methods=["POST"])
def create_lab_result():
    _, role = get_user_context()
    require_role(role, {"IntakeProcessor"})
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    jurisdiction_id = require_string(body, "jurisdiction_id")
    condition_code = require_string(body, "condition_code")

    with db.lock:
        get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        get_in_program_or_404(db.jurisdictions, jurisdiction_id, program_id, "ERR_JURISDICTION_NOT_FOUND")
        # condition_code FK in program
        cond = next((c for c in db.conditions.values()
                     if c["program_id"] == program_id and c["condition_code"] == condition_code), None)
        if cond is None:
            raise err("ERR_CONDITION_NOT_FOUND", "condition_code unknown in program")

        # field-level validation after existence
        patient_reference = require_string(body, "patient_reference")
        result_value = require_enum(body, "result_value", RESULT_VALUES)
        specimen_collection_date = require_string(body, "specimen_collection_date")
        parse_dt(specimen_collection_date)

        ent = base_entity(common_fields=True)
        ent.update({
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "condition_code": condition_code,
            "patient_reference": patient_reference,
            "result_value": result_value,
            "specimen_collection_date": specimen_collection_date,
            "linked_case_id": None,
            "status": "RECEIVED",
        })

        # auto-linkage: exactly one OPEN/UNDER_INVESTIGATION case in program with matching ref+condition
        matches = [c for c in db.cases.values()
                   if c["program_id"] == program_id
                   and c["patient_reference"] == patient_reference
                   and c["condition_code"] == condition_code
                   and c["status"] in ("OPEN", "UNDER_INVESTIGATION")]
        if len(matches) == 1:
            case = matches[0]
            ent["status"] = "LINKED"
            ent["linked_case_id"] = case["id"]
            db.lab_results[ent["id"]] = ent
            recompute_linked_positive(case)
            case["completeness_score"] = compute_completeness(case)
            touch(case)
        else:
            ent["status"] = "UNLINKED"
            db.lab_results[ent["id"]] = ent

        return success(ser_lab_result(ent), 201)


@bp.route("/surveillance/lab-results", methods=["GET"])
def list_lab_results():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        program_id = request.args.get("program_id")
        linked_case_id = request.args.get("linked_case_id")
        jurisdiction_id = request.args.get("jurisdiction_id")
        items = []
        for l in db.lab_results.values():
            if program_id is not None and l["program_id"] != program_id:
                continue
            if linked_case_id is not None and l.get("linked_case_id") != linked_case_id:
                continue
            if jurisdiction_id is not None and l["jurisdiction_id"] != jurisdiction_id:
                continue
            items.append(l)
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_lab_result(l) for l in page], limit, offset, total)


@bp.route("/surveillance/lab-results/<lab_result_id>", methods=["GET"])
def get_lab_result(lab_result_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        l = get_or_404(db.lab_results, lab_result_id, "ERR_LAB_RESULT_NOT_FOUND")
        return success(ser_lab_result(l), 200)


@bp.route("/surveillance/lab-results/<lab_result_id>/supersede", methods=["POST"])
def supersede_lab_result(lab_result_id):
    _, role = get_user_context()
    require_role(role, {"IntakeProcessor"})
    with db.lock:
        l = get_or_404(db.lab_results, lab_result_id, "ERR_LAB_RESULT_NOT_FOUND")
        if l["status"] != "LINKED":
            raise err("ERR_LAB_NOT_SUPERSEDABLE", "Lab result not in LINKED for supersede")
        prior_case_id = l.get("linked_case_id")
        l["status"] = "SUPERSEDED"
        l["linked_case_id"] = None
        touch(l)
        if prior_case_id and prior_case_id in db.cases:
            case = db.cases[prior_case_id]
            recompute_linked_positive(case)
            case["completeness_score"] = compute_completeness(case)
            touch(case)
        return success(ser_lab_result(l), 200)
