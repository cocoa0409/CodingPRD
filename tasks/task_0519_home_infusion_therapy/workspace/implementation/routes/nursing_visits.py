"""NursingVisit routes (PRD §3.6/§3.7)."""
from flask import Blueprint, request

import errors
import helpers
from clock import clock
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response
from services import calculations as calc
from services import workflow

bp = Blueprint("nursing_visits", __name__)

VISIT_TYPES = {"TEACH", "ADMINISTER"}
READ_ROLES = ["VisitingNurse", "MedicalDirector", "Pharmacist", "IntakeCoordinator"]


def _recompute_sequence_indices(order_id):
    """1-based ordinal within the order, ordered by start_at asc then created_at asc."""
    visits = [v for v in db.nursing_visits.values() if v["order_id"] == order_id]
    visits.sort(key=lambda v: (helpers.parse_iso(v["start_at"]), v["created_at"], v["_seq"]))
    for idx, v in enumerate(visits, start=1):
        v["sequence_index"] = idx


@bp.route("/nursing-visits", methods=["POST"])
def create_visit():
    require(["IntakeCoordinator", "VisitingNurse"])
    body = helpers.get_body()
    # existence (priority 3) before other body validity (priority 4) per PRD §2.8
    order_id = helpers.as_str(body, "order_id")
    nurse_id = helpers.as_str(body, "nurse_id")
    compound_id = helpers.as_str(body, "compound_id", required=False, default=None)
    if order_id not in db.infusion_orders:
        raise errors.not_found("Infusion order not found")
    if nurse_id not in db.nurses:
        raise errors.not_found("Nurse not found")
    if compound_id is not None and compound_id not in db.compounds:
        raise errors.not_found("Compound not found")

    # body validity (priority 4)
    visit_type = helpers.as_enum(body, "visit_type", VISIT_TYPES)
    start_at = helpers.as_datetime(body, "start_at")
    duration_min = helpers.as_int(body, "duration_min")
    if duration_min <= 0:
        raise errors.invalid_request("duration_min must be > 0")

    order = db.infusion_orders[order_id]
    nurse = db.nurses[nurse_id]
    patient = db.patients.get(order["patient_id"])

    # (8) nurse licensure: license_state == patient.service_state and nurse ACTIVE
    if (patient is None or nurse["license_state"] != patient["service_state"]
            or nurse["status"] != "ACTIVE"):
        raise errors.ApiError(errors.ERR_NURSE_NOT_LICENSED, 422,
                              "Nurse not licensed for the patient's service state")

    # (11) nurse schedule overlap (SCHEDULED or COMPLETED visits of same nurse)
    new_start = start_at
    for other in db.nursing_visits.values():
        if other["nurse_id"] != nurse_id:
            continue
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        ex_start = helpers.parse_iso(other["start_at"])
        if calc.nurse_conflict(new_start, duration_min, ex_start, other["duration_min"]):
            raise errors.ApiError(errors.ERR_NURSE_DOUBLE_BOOKED, 409,
                                  "Nurse schedule conflict")

    visit = stamp_create({
        "order_id": order_id,
        "nurse_id": nurse_id,
        "compound_id": compound_id,
        "visit_type": visit_type,
        "start_at": body["start_at"],
        "duration_min": duration_min,
        "sequence_index": 0,
        "status": "SCHEDULED",
    })
    db.nursing_visits[visit["id"]] = visit
    _recompute_sequence_indices(order_id)
    return object_response(visit, 201)


@bp.route("/nursing-visits/<id>", methods=["GET"])
def get_visit(id):
    require(READ_ROLES)
    visit = db.nursing_visits.get(id)
    if visit is None:
        raise errors.not_found("Nursing visit not found")
    return object_response(visit, 200)


@bp.route("/nursing-visits", methods=["GET"])
def list_visits():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.nursing_visits.values())
    order_id = request.args.get("order_id")
    nurse_id = request.args.get("nurse_id")
    compound_id = request.args.get("compound_id")
    if order_id is not None:
        items = [v for v in items if v["order_id"] == order_id]
    if nurse_id is not None:
        items = [v for v in items if v["nurse_id"] == nurse_id]
    if compound_id is not None:
        items = [v for v in items if v["compound_id"] == compound_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/nursing-visits/<id>/complete", methods=["POST"])
def complete_visit(id):
    require(["VisitingNurse"])
    visit = db.nursing_visits.get(id)
    if visit is None:
        raise errors.not_found("Nursing visit not found")
    # (5) state legality
    if visit["status"] != "SCHEDULED":
        raise errors.invalid_state("Visit is not in SCHEDULED state")
    order = db.infusion_orders.get(visit["order_id"])
    if order is None or order["status"] not in ("RELEASED", "ACTIVE"):
        raise errors.invalid_state("Order is not in RELEASED or ACTIVE state")

    # (7) lab-monitoring gate: 4th+ visit on a trough-monitored order needs a
    # TROUGH lab in [start_date, start_date + LAB_DUE_DAYS].
    _recompute_sequence_indices(order["id"])
    drug = db.drug_catalog.get(order["drug_id"])
    if visit["sequence_index"] >= 4 and drug["requires_trough_lab"]:
        if not _has_trough_in_window(order):
            # Block completion AND place the order on hold (LAB_OVERDUE).
            if order["status"] in ("RELEASED", "ACTIVE"):
                workflow.hold_order(order, "LAB_OVERDUE")
            raise errors.ApiError(errors.ERR_LAB_OVERDUE, 409,
                                  "Trough lab overdue for 4th+ visit")

    # commit completion
    is_first = not any(
        v["order_id"] == order["id"] and v["status"] == "COMPLETED"
        for v in db.nursing_visits.values()
    )
    visit["status"] = "COMPLETED"
    touch(visit)

    if is_first and order["status"] == "RELEASED":
        order["status"] = "ACTIVE"
        workflow.recompute_administered_days(order)
        touch(order)
    else:
        before = order["administered_days"]
        workflow.recompute_administered_days(order)
        if order["administered_days"] != before:
            touch(order)

    return object_response(visit, 200)


@bp.route("/nursing-visits/<id>/miss", methods=["POST"])
def miss_visit(id):
    require(["VisitingNurse"])
    visit = db.nursing_visits.get(id)
    if visit is None:
        raise errors.not_found("Nursing visit not found")
    if visit["status"] != "SCHEDULED":
        raise errors.invalid_state("Visit is not in SCHEDULED state")
    visit["status"] = "MISSED"
    touch(visit)
    return object_response(visit, 200)


def _has_trough_in_window(order):
    start = helpers.parse_iso(order["start_date"])
    lo, hi = calc.lab_window(start)
    for lab in db.lab_results.values():
        if lab["order_id"] != order["id"]:
            continue
        if lab["lab_type"] != "TROUGH":
            continue
        collected = helpers.parse_iso(lab["collected_at"])
        if lo <= collected <= hi:
            return True
    return False
