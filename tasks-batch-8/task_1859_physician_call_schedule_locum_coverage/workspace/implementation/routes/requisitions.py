"""Locum requisitions: create/list/get/propose-candidate/begin-credentialing/cancel
(PRD §3.5). Gap phase transitions follow the §1.2 CoverageGap state machine."""
from flask import Blueprint

import db
import validation as V
from db import store
from errors import ApiError
from middleware import require_roles
from response import ok, created, paginate
from services import domain as D
from routes.gaps import get_gap_or_404
from routes.physicians import get_physician_or_404

bp = Blueprint("requisitions", __name__)

ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_requisition_or_404(requisition_id):
    req = store.requisitions.get(requisition_id)
    if req is None:
        raise ApiError("ERR_REQUISITION_NOT_FOUND", 404, "LocumRequisition id does not exist")
    return req


def _gap_slot_program(req_or_gap):
    gap_id = req_or_gap["gap_id"] if "gap_id" in req_or_gap else req_or_gap["id"]
    gap = store.gaps.get(gap_id)
    slot = store.slots.get(gap["slot_id"])
    program = store.programs.get(gap["program_id"])
    return gap, slot, program


def _check_credentialing_feasible(slot, program):
    """now must be strictly earlier than window_start - credentialing_lead_hours."""
    from datetime import timedelta
    deadline = slot["window_start"] - timedelta(hours=int(program["credentialing_lead_hours"]))
    if not (db.now_logical() < deadline):
        raise ApiError("ERR_CREDENTIALING_INFEASIBLE", 409,
                       "Credentialing window is infeasible for this slot")


@bp.route("/api/locum-requisitions", methods=["POST"])
def create_requisition():
    require_roles(["SchedulerAdmin"])
    body = V.json_body()
    gap_id = V.req_str(body, "gap_id")
    gap = get_gap_or_404(gap_id)
    if gap["status"] != "OPEN":
        raise ApiError("ERR_GAP_NOT_OPEN", 409,
                       "Locum requisition creation requires the gap OPEN")
    _gap, slot, program = _gap_slot_program(gap)
    _check_credentialing_feasible(slot, program)
    req = db.new_common({
        "gap_id": gap["id"],
        "program_id": gap["program_id"],
        "candidate_physician_id": None,
        "status": "OPEN",
    })
    store.requisitions[req["id"]] = req
    gap["status"] = "REQUISITIONED"
    db.touch(gap)
    return created(req)


@bp.route("/api/locum-requisitions", methods=["GET"])
def list_requisitions():
    require_roles(ALL)
    rows = list(store.requisitions.values())
    rows = paginate.filter(rows, "gap_id")
    rows = paginate.filter(rows, "program_id")
    rows = paginate.filter(rows, "candidate_physician_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/locum-requisitions/<requisition_id>", methods=["GET"])
def get_requisition(requisition_id):
    require_roles(ALL)
    return ok(get_requisition_or_404(requisition_id))


@bp.route("/api/locum-requisitions/<requisition_id>/propose-candidate", methods=["POST"])
def propose_candidate(requisition_id):
    require_roles(["SchedulerAdmin"])
    body = V.json_body()
    candidate_id = V.req_str(body, "candidate_physician_id")
    # Existence (priority 5): path id, then body id.
    req = get_requisition_or_404(requisition_id)
    candidate = get_physician_or_404(candidate_id)
    if req["status"] != "OPEN":
        raise ApiError("ERR_REQUISITION_NOT_OPEN", 409,
                       "propose-candidate requires the requisition OPEN")
    gap, slot, program = _gap_slot_program(req)
    # Level 8: candidate ACTIVE, then unavailability (moonlight cap: LOCUM exempt).
    if candidate["status"] != "ACTIVE":
        raise ApiError("ERR_PHYSICIAN_INACTIVE", 409, "Candidate physician is INACTIVE")
    if D.has_approved_window_covering(candidate["id"], slot["date"]):
        raise ApiError("ERR_UNAVAILABILITY_CONFLICT", 409,
                       "An APPROVED unavailability window covers the slot date")
    # Level 9: half-open overlap.
    if D.has_overlapping_assignment(candidate["id"], slot):
        raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                       "Candidate holds an assignment whose half-open window overlaps")
    # Level 10 (narrative order): candidate must be LOCUM, then specialty match.
    if candidate["employment_type"] != "LOCUM":
        raise ApiError("ERR_CANDIDATE_NOT_LOCUM", 409,
                       "propose-candidate requires a LOCUM physician")
    if candidate["specialty"] != program["service_line"]:
        raise ApiError("ERR_SPECIALTY_MISMATCH", 409,
                       "Candidate specialty != program.service_line")
    req["candidate_physician_id"] = candidate["id"]
    req["status"] = "SOURCED"
    db.touch(req)
    return ok(req)


@bp.route("/api/locum-requisitions/<requisition_id>/begin-credentialing", methods=["POST"])
def begin_credentialing(requisition_id):
    require_roles(["CredentialingOfficer"])
    V.json_body()
    req = get_requisition_or_404(requisition_id)
    if req["status"] != "SOURCED":
        raise ApiError("ERR_REQUISITION_NOT_SOURCED", 409,
                       "begin-credentialing requires the requisition SOURCED")
    gap, slot, program = _gap_slot_program(req)
    _check_credentialing_feasible(slot, program)
    from datetime import timedelta
    case = db.new_common({
        "requisition_id": req["id"],
        "locum_physician_id": req["candidate_physician_id"],
        "clear_by": slot["window_start"] - timedelta(hours=int(program["credentialing_lead_hours"])),
        "items": {name: {"completed_at": None} for name in D.CREDENTIAL_ITEMS},
        "status": "INITIATED",
    })
    store.cases[case["id"]] = case
    req["status"] = "CREDENTIALING"
    db.touch(req)
    return ok(req)


@bp.route("/api/locum-requisitions/<requisition_id>/cancel", methods=["POST"])
def cancel_requisition(requisition_id):
    require_roles(["SchedulerAdmin"])
    V.json_body()
    req = get_requisition_or_404(requisition_id)
    if req["status"] not in ("OPEN", "SOURCED", "CREDENTIALING"):
        raise ApiError("ERR_REQUISITION_NOT_CANCELLABLE", 409,
                       "cancel requires the requisition OPEN, SOURCED or CREDENTIALING")
    was_credentialing = req["status"] == "CREDENTIALING"
    req["status"] = "CANCELLED"
    req["candidate_physician_id"] = None
    db.touch(req)
    if was_credentialing:
        for case in store.cases.values():
            if case["requisition_id"] == req["id"] \
                    and case["status"] in ("INITIATED", "IN_PROGRESS"):
                case["status"] = "CANCELLED"
                db.touch(case)
    # Gap returns REQUISITIONED -> OPEN on a user-initiated cancel.
    gap = store.gaps.get(req["gap_id"])
    if gap is not None and gap["status"] == "REQUISITIONED":
        gap["status"] = "OPEN"
        db.touch(gap)
    return ok(req)
