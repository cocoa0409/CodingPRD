"""QualityInspection endpoints (schedule, record-result, rework loop)."""
from flask import Blueprint, request

from db import STORE
from domain import (new_entity, bump, bump_program, get_or_404, by_created,
                    serialize_inspection)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_FINAL_INSPECTION_PREREQUISITE)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("PREP", "PAINT", "INTERIOR", "FINAL")
RESULTS = ("PASS", "FAIL")
MAJOR_DEFECT_THRESHOLD = 2


def _program_inspections(program_id):
    return [i for i in STORE.quality_inspections.values()
            if i["program_id"] == program_id]


def _rework_of(program_id, inspection_type):
    """The latest FAILED inspection of this type not yet answered by a later
    PASSED inspection of the same type; None otherwise."""
    same_type = [i for i in _program_inspections(program_id)
                 if i["inspection_type"] == inspection_type]
    failed = [i for i in same_type if i["status"] == "FAILED"]
    if not failed:
        return None
    latest_fail = max(failed, key=lambda i: i["_seq"])
    answered = any(j["status"] == "PASSED" and j["_seq"] > latest_fail["_seq"]
                   for j in same_type)
    return None if answered else latest_fail["id"]


@bp.post("/quality-inspections")
def create_inspection():
    auth("QualityInspector")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    inspection_type = field(data, "inspection_type", "str", enum=INSPECTION_TYPES)
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] not in ("IN_WORK", "IN_INSPECTION"):
        raise invalid_state(
            "Inspections may be scheduled only while IN_WORK or IN_INSPECTION")
    insp = new_entity()
    insp.update({
        "program_id": program_id,
        "inspection_type": inspection_type,
        "status": "SCHEDULED",
        "major_defects": None,
        "minor_defects": None,
        "rework_of_id": _rework_of(program_id, inspection_type),
    })
    STORE.quality_inspections[insp["id"]] = insp
    return success(serialize_inspection(insp), status=201)


@bp.get("/quality-inspections/<iid>")
def get_inspection(iid):
    auth()
    insp = get_or_404(STORE.quality_inspections, iid, "QualityInspection")
    return success(serialize_inspection(insp))


@bp.get("/quality-inspections")
def list_inspections():
    auth()
    items = by_created(list(STORE.quality_inspections.values()))
    for key in ("program_id", "inspection_type", "status", "rework_of_id"):
        value = request.args.get(key)
        if value is not None:
            items = [i for i in items if i[key] == value]
    return paginate(items, serialize_inspection)


@bp.post("/quality-inspections/<iid>/record-result")
def record_result(iid):
    auth("QualityInspector")
    data = get_body(required=True)
    result = field(data, "result", "str", enum=RESULTS)
    major_defects = field(data, "major_defects", "int")
    minor_defects = field(data, "minor_defects", "int")
    insp = get_or_404(STORE.quality_inspections, iid, "QualityInspection")
    if insp["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED inspection can record a result")
    prog = STORE.programs[insp["program_id"]]
    if prog["status"] != "IN_INSPECTION":
        raise invalid_state("Recording a result requires the program IN_INSPECTION")
    if insp["inspection_type"] == "FINAL":
        existing = _program_inspections(prog["id"])
        paint_ok = any(i["inspection_type"] == "PAINT" and i["status"] == "PASSED"
                       for i in existing)
        interior_ok = any(i["inspection_type"] == "INTERIOR" and i["status"] == "PASSED"
                          for i in existing)
        if not (paint_ok and interior_ok):
            raise ApiError(ERR_FINAL_INSPECTION_PREREQUISITE, 409,
                           "FINAL requires prior PASSED PAINT and INTERIOR inspections")
    insp["major_defects"] = major_defects
    insp["minor_defects"] = minor_defects
    if result == "PASS":
        insp["status"] = "PASSED"
        bump(insp)
    else:
        insp["status"] = "FAILED"
        bump(insp)
        # Revert loop: IN_INSPECTION -> IN_WORK, rework_cycles += 1.
        prog["status"] = "IN_WORK"
        prog["rework_cycles"] += 1
        bump_program(prog)
        # major_defect_discovery_trigger: >= 2 majors -> auto safety item.
        if major_defects >= MAJOR_DEFECT_THRESHOLD:
            item = new_entity()
            item.update({
                "program_id": prog["id"],
                "assessment_id": None,
                "source": "INSPECTION_AUTO",
                "description": (f"Auto-created from FAILED "
                                f"{insp['inspection_type']} inspection with "
                                f"{major_defects} major defects"),
                "safety_linked": True,
                "status": "OPEN",
                "est_cost_cents": None,
                "est_hours": None,
                "actual_cost_cents": None,
                "defer_reason": None,
            })
            STORE.discovery_items[item["id"]] = item
    return success(serialize_inspection(insp))
