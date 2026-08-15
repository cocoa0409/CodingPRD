"""Damage assessments (PRD 3.10): per-line rounded billing schedule."""
from flask import Blueprint, g, request

import domain
from calc import damage_totals
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found, validation
from http_util import (
    DEFECT_CAUSES, SEVERITIES, get_body, parse_pagination, require_roles,
    v_int, v_str,
)
from store import db, new_entity, touch

bp_damage = Blueprint("damage", __name__)

READ_ROLES = (
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController",
    "BillingAnalyst", "ComplianceOfficer", "LesseeRep",
)


def _load_assessment(assessment_id):
    d = db.assessments.get(assessment_id)
    if d is None:
        raise not_found("ERR_ASSESSMENT_NOT_FOUND", f"Damage assessment {assessment_id} not found")
    return d


def _owner_lessee_id(assessment):
    a = db.assignments.get(assessment["lease_assignment_id"])
    return domain.lessee_id_of_assignment(a) if a else None


def _validate_line_items(body):
    items = body.get("line_items")
    if items is None:
        raise validation("Missing required field: line_items")
    if not isinstance(items, list) or len(items) == 0:
        raise validation("line_items must be a non-empty array")
    cleaned = []
    for i, line in enumerate(items):
        if not isinstance(line, dict):
            raise validation(f"line_items[{i}] must be an object")
        component = line.get("component")
        if not isinstance(component, str) or component == "":
            raise validation(f"line_items[{i}].component must be a non-empty string")
        severity = line.get("severity")
        if severity not in SEVERITIES:
            raise validation(f"line_items[{i}].severity must be one of {sorted(SEVERITIES)}")
        cause = line.get("cause")
        if cause not in DEFECT_CAUSES:
            raise validation(f"line_items[{i}].cause must be one of {sorted(DEFECT_CAUSES)}")
        parts = line.get("parts_cents")
        if not isinstance(parts, int) or isinstance(parts, bool) or parts < 0:
            raise validation(f"line_items[{i}].parts_cents must be an integer >= 0")
        hours = line.get("labor_hours")
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours < 0:
            raise validation(f"line_items[{i}].labor_hours must be a number >= 0")
        replaced = line.get("replaced")
        if not isinstance(replaced, bool):
            raise validation(f"line_items[{i}].replaced must be a boolean")
        cleaned.append(
            {
                "component": component,
                "severity": severity,
                "cause": cause,
                "parts_cents": parts,
                "labor_hours": hours,
                "replaced": replaced,
            }
        )
    return cleaned


@bp_damage.route("/damage-assessments", methods=["POST"])
@require_roles("MaintenanceController")
def create_assessment():
    body = get_body()
    assignment_id = v_str(body, "lease_assignment_id")
    railcar_id = v_str(body, "railcar_id")
    if assignment_id not in db.assignments:
        raise not_found("ERR_ASSIGNMENT_NOT_FOUND", f"Lease assignment {assignment_id} not found")
    if railcar_id not in db.railcars:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")
    d = new_entity(
        {
            "lease_assignment_id": assignment_id,
            "railcar_id": railcar_id,
            "line_items": None,
            "total_assessed_cents": None,
            "lessee_liable_cents": None,
            "status": "DRAFT",
        }
    )
    db.assessments[d["id"]] = d
    return ok(domain.serialize_assessment(d), status=201)


@bp_damage.route("/damage-assessments", methods=["GET"])
@require_roles(*READ_ROLES)
def list_assessments():
    limit, offset = parse_pagination()
    items = sorted(db.assessments.values(), key=lambda d: (d["created_at"], d["_created_seq"]))
    if g.user_role == "LesseeRep":
        items = [d for d in items if _owner_lessee_id(d) == g.user_id]
    assignment_id = request.args.get("lease_assignment_id")
    railcar_id = request.args.get("railcar_id")
    status = request.args.get("status")
    if assignment_id is not None:
        items = [d for d in items if d["lease_assignment_id"] == assignment_id]
    if railcar_id is not None:
        items = [d for d in items if d["railcar_id"] == railcar_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_assessment(d) for d in page], limit, offset, total)


@bp_damage.route("/damage-assessments/<assessment_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_assessment(assessment_id):
    d = _load_assessment(assessment_id)
    domain.check_lessee_ownership(_owner_lessee_id(d))
    return ok(domain.serialize_assessment(d))


@bp_damage.route("/damage-assessments/<assessment_id>/submit", methods=["POST"])
@require_roles("MaintenanceController")
def submit_assessment(assessment_id):
    d = _load_assessment(assessment_id)
    body = get_body()
    items = _validate_line_items(body)
    if d["status"] != "DRAFT":
        raise invalid_state(f"Assessment in status {d['status']} cannot be submitted")
    d["line_items"] = items
    d["status"] = "SUBMITTED"
    touch(d)
    return ok(domain.serialize_assessment(d))


@bp_damage.route("/damage-assessments/<assessment_id>/dispute", methods=["POST"])
@require_roles("LesseeRep")
def dispute_assessment(assessment_id):
    d = _load_assessment(assessment_id)
    domain.check_lessee_ownership(_owner_lessee_id(d))
    body = get_body()
    v_str(body, "reason")
    if d["status"] != "SUBMITTED":
        raise invalid_state(f"Assessment in status {d['status']} cannot be disputed")
    d["status"] = "DISPUTED"
    touch(d)
    return ok(domain.serialize_assessment(d))


@bp_damage.route("/damage-assessments/<assessment_id>/resubmit", methods=["POST"])
@require_roles("MaintenanceController")
def resubmit_assessment(assessment_id):
    d = _load_assessment(assessment_id)
    body = get_body()
    items = _validate_line_items(body)
    if d["status"] != "DISPUTED":
        raise invalid_state(f"Assessment in status {d['status']} cannot be resubmitted")
    d["line_items"] = items
    d["status"] = "SUBMITTED"
    touch(d)
    return ok(domain.serialize_assessment(d))


@bp_damage.route("/damage-assessments/<assessment_id>/finalize", methods=["POST"])
@require_roles("MaintenanceController")
def finalize_assessment(assessment_id):
    d = _load_assessment(assessment_id)
    if d["status"] != "SUBMITTED":
        raise invalid_state(f"Assessment in status {d['status']} cannot be finalized")
    car = db.railcars.get(d["railcar_id"])
    age = domain.car_age(car) if car else 0
    total, liable = damage_totals(d["line_items"] or [], age)
    d["total_assessed_cents"] = total
    d["lessee_liable_cents"] = liable
    d["status"] = "FINALIZED"
    touch(d)
    return ok(domain.serialize_assessment(d))


@bp_damage.route("/damage-assessments/<assessment_id>/invoice", methods=["POST"])
@require_roles("BillingAnalyst")
def invoice_assessment(assessment_id):
    d = _load_assessment(assessment_id)
    if d["status"] != "FINALIZED":
        raise invalid_state(f"Assessment in status {d['status']} cannot be invoiced")
    d["status"] = "INVOICED"
    touch(d)
    lessee_id = _owner_lessee_id(d)
    lessee = db.lessees.get(lessee_id) if lessee_id else None
    if lessee is not None:
        domain.balance_add(lessee, d["lessee_liable_cents"])
    return ok(domain.serialize_assessment(d))


@bp_damage.route("/damage-assessments/<assessment_id>/record-payment", methods=["POST"])
@require_roles("BillingAnalyst")
def record_payment(assessment_id):
    d = _load_assessment(assessment_id)
    body = get_body()
    amount = v_int(body, "amount_cents")
    if d["status"] != "INVOICED":
        raise invalid_state(f"Assessment in status {d['status']} cannot record payment")
    if amount != d["lessee_liable_cents"]:
        raise ApiError(
            "ERR_PAYMENT_MISMATCH", 422,
            "amount_cents must equal lessee_liable_cents exactly",
        )
    d["status"] = "PAID"
    touch(d)
    lessee_id = _owner_lessee_id(d)
    lessee = db.lessees.get(lessee_id) if lessee_id else None
    if lessee is not None:
        domain.balance_add(lessee, -amount)
    return ok(domain.serialize_assessment(d))
