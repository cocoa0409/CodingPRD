"""CctvInspection + DefectObservation endpoints."""
import re
from flask import Blueprint, request

import db
from db import _parse_iso, _format_iso
from middleware import get_actor, require_roles, technician_capability_check
from response import success_object, success_list
from errors import (
    err_invalid_request, err_invalid_state, err_not_found, err_conflict, err_unauthorized,
)
from services.common import (
    body, require_string, require_number, require_int, require_enum,
    parse_datetime_field, parse_pagination, paginate,
    get_segment, get_cycle, get_inspection, sweep_notice_expiry,
    compute_pacp_scores,
)

bp = Blueprint("inspections", __name__)

READ_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead"]
PURPOSES = {"BASELINE", "PRE_REHAB", "POST_CIPP", "WARRANTY_RE"}
FAMILIES = {"STRUCTURAL", "OM"}
PACP_CODE_RE = re.compile(r"^[A-Z]{1,6}$")


def inspection_view(i):
    return {
        "id": i["id"],
        "segment_id": i["segment_id"],
        "cycle_id": i["cycle_id"],
        "scheduled_at": i["scheduled_at"],
        "coder_id": i["coder_id"],
        "qa_reviewer_id": i["qa_reviewer_id"],
        "purpose": i["purpose"],
        "status": i["status"],
        "reject_count": i["reject_count"],
        "certified_at": i["certified_at"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def defect_view(d):
    return {
        "id": d["id"],
        "inspection_id": d["inspection_id"],
        "pacp_code": d["pacp_code"],
        "family": d["family"],
        "grade": d["grade"],
        "distance_m": d["distance_m"],
        "clock_position": d["clock_position"],
        "extent_m": d["extent_m"],
        "created_at": d["created_at"],
    }


def _get_technician(tech_id):
    t = db.technicians.get(tech_id)
    if t is None:
        raise err_not_found("technician not found")
    return t


def _cert_valid(tech):
    exp = _parse_iso(tech["nassco_cert_expires_at"])
    return exp > db.now_dt()


# ---------------------------------------------------------------------------
# Schedule / read / list
# ---------------------------------------------------------------------------

@bp.post("/sewer/segments/<id>/cctv-inspections")
def schedule_inspection(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    segment = get_segment(id)
    payload = body()
    cycle_id = require_string(payload, "cycle_id")
    cycle = db.cycles.get(cycle_id)
    if cycle is None:
        raise err_not_found("cycle not found")
    if cycle["district_id"] != segment["district_id"]:
        raise err_not_found("cycle not in same district as segment")
    scheduled = parse_datetime_field(payload, "scheduled_at", required=True)
    coder_id = require_string(payload, "coder_id")
    coder = _get_technician(coder_id)
    purpose = payload.get("purpose", "BASELINE")
    if purpose not in PURPOSES:
        raise err_invalid_request("invalid purpose")
    # coder must be active and hold CODER capability
    if not coder.get("active", True):
        raise err_invalid_request("coder technician is inactive")
    if "CODER" not in (coder.get("capabilities") or []):
        raise err_invalid_request("coder lacks CODER capability")
    # cycle window membership
    ws = _parse_iso(cycle["window_start"])
    we = _parse_iso(cycle["window_end"])
    if not (ws <= scheduled <= we):
        raise err_conflict("ERR_OUTSIDE_CYCLE_WINDOW", "scheduled_at outside cycle window")
    ent = {
        "id": db.new_id(),
        "segment_id": segment["id"],
        "cycle_id": cycle["id"],
        "scheduled_at": _format_iso(scheduled),
        "coder_id": coder_id,
        "qa_reviewer_id": None,
        "purpose": purpose,
        "status": "SCHEDULED",
        "reject_count": 0,
        "certified_at": None,
    }
    db.stamp_new(ent)
    db.inspections[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(inspection_view(ent), status=201)


@bp.get("/sewer/cctv-inspections/<id>")
def get_inspection_route(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    insp = get_inspection(id)
    return success_object(inspection_view(insp))


@bp.get("/sewer/segments/<id>/cctv-inspections")
def list_segment_inspections(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    segment = get_segment(id)
    limit, offset = parse_pagination()
    items = [i for i in db.inspections.values() if i["segment_id"] == segment["id"]]
    st = request.args.get("status")
    if st:
        items = [i for i in items if i["status"] == st]
    pu = request.args.get("purpose")
    if pu:
        items = [i for i in items if i["purpose"] == pu]
    page, total = paginate(items, limit, offset)
    return success_list([inspection_view(i) for i in page], limit, offset, total)


@bp.get("/sewer/cctv-inspections")
def list_inspections_xseg():
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.inspections.values())
    cy = request.args.get("cycle_id")
    if cy:
        items = [i for i in items if i["cycle_id"] == cy]
    co = request.args.get("coder_id")
    if co:
        items = [i for i in items if i["coder_id"] == co]
    qa = request.args.get("qa_reviewer_id")
    if qa:
        items = [i for i in items if i.get("qa_reviewer_id") == qa]
    st = request.args.get("status")
    if st:
        items = [i for i in items if i["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([inspection_view(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def _coder_gate(actor, insp):
    """Assert acting Coder is the assigned coder with valid cert + capability."""
    tech = technician_capability_check(actor, "CODER")
    if tech["id"] != insp["coder_id"]:
        raise err_conflict("ERR_NOT_ASSIGNED_CODER", "acting Coder is not the assigned coder")
    if not tech.get("active", True):
        raise err_unauthorized("technician inactive")
    if not _cert_valid(tech):
        raise err_conflict("ERR_CERT_EXPIRED", "coder certification expired")
    return tech


def _qa_gate(actor, insp):
    """Assert acting QaReviewer differs from coder and holds valid cert + capability."""
    tech = technician_capability_check(actor, "QA_REVIEWER")
    if tech["id"] == insp["coder_id"]:
        raise err_conflict("ERR_SOD_VIOLATION", "QA reviewer must differ from coder")
    if not tech.get("active", True):
        raise err_unauthorized("technician inactive")
    if not _cert_valid(tech):
        raise err_conflict("ERR_CERT_EXPIRED", "QA certification expired")
    return tech


def _auto_void_warranty_cases(inspection_id):
    for case in db.warranty_cases.values():
        if case.get("re_inspection_id") == inspection_id and case["status"] == "RE_INSPECTION":
            case["status"] = "OPENED"
            db.touch(case)


def _apply_certify_side_effects(insp, actor):
    segment = db.segments[insp["segment_id"]]
    observations = [d for d in db.defects.values() if d["inspection_id"] == insp["id"]]
    sg, og, idx, qr = compute_pacp_scores(observations)
    segment["structural_grade"] = sg
    segment["om_grade"] = og
    segment["structural_index"] = idx
    segment["quick_rating"] = qr
    db.touch(segment)
    insp["qa_reviewer_id"] = actor.user_id
    insp["certified_at"] = db.now_iso()
    # POST_CIPP acceptance rule
    if insp["purpose"] == "POST_CIPP":
        has_completed_wo = False
        for wo in db.work_orders.values():
            plan = db.plans.get(wo["plan_id"])
            if plan is None:
                continue
            if plan["segment_id"] == segment["id"] and wo["execution_status"] == "COMPLETED":
                has_completed_wo = True
                break
        if has_completed_wo:
            actives = [l for l in db.laterals.values() if l["segment_id"] == segment["id"] and l["active"]]
            all_reinstated = all(l["reinstated"] for l in actives)
            if all_reinstated:
                if segment["rehab_status"] != "WARRANTY":
                    segment["rehab_status"] = "WARRANTY"
                    db.touch(segment)


@bp.post("/sewer/cctv-inspections/<id>/start")
def start_inspection(id):
    actor = get_actor()
    require_roles(actor, ["Coder"])
    insp = get_inspection(id)
    if insp["status"] != "SCHEDULED":
        raise err_invalid_state("inspection not SCHEDULED")
    tech = _coder_gate(actor, insp)
    cycle = db.cycles[insp["cycle_id"]]
    if cycle["status"] != "OPEN":
        raise err_conflict("ERR_CYCLE_NOT_OPEN", "cycle not OPEN")
    insp["status"] = "IN_PROGRESS"
    db.touch(insp)
    # Warranty case linkage: OPENED -> RE_INSPECTION
    for case in db.warranty_cases.values():
        if case.get("re_inspection_id") == insp["id"] and case["status"] == "OPENED":
            case["status"] = "RE_INSPECTION"
            db.touch(case)
    sweep_notice_expiry()
    return success_object(inspection_view(insp))


@bp.post("/sewer/cctv-inspections/<id>/begin-coding")
def begin_coding(id):
    actor = get_actor()
    require_roles(actor, ["Coder"])
    insp = get_inspection(id)
    if insp["status"] != "IN_PROGRESS":
        raise err_invalid_state("inspection not IN_PROGRESS")
    _coder_gate(actor, insp)
    insp["status"] = "CODING"
    db.touch(insp)
    sweep_notice_expiry()
    return success_object(inspection_view(insp))


@bp.post("/sewer/cctv-inspections/<id>/submit-qa")
def submit_qa(id):
    actor = get_actor()
    require_roles(actor, ["Coder"])
    insp = get_inspection(id)
    if insp["status"] != "CODING":
        raise err_invalid_state("inspection not CODING")
    _coder_gate(actor, insp)
    obs = [d for d in db.defects.values() if d["inspection_id"] == insp["id"]]
    if len(obs) < 1:
        raise err_conflict("ERR_NO_DEFECTS_CODED", "at least one DefectObservation required")
    insp["status"] = "QA_REVIEW"
    db.touch(insp)
    sweep_notice_expiry()
    return success_object(inspection_view(insp))


@bp.post("/sewer/cctv-inspections/<id>/certify")
def certify(id):
    actor = get_actor()
    require_roles(actor, ["QaReviewer"])
    insp = get_inspection(id)
    if insp["status"] != "QA_REVIEW":
        raise err_invalid_state("inspection not QA_REVIEW")
    _qa_gate(actor, insp)
    insp["status"] = "CERTIFIED"
    _apply_certify_side_effects(insp, actor)
    db.touch(insp)
    sweep_notice_expiry()
    return success_object(inspection_view(insp))


@bp.post("/sewer/cctv-inspections/<id>/reject")
def reject(id):
    actor = get_actor()
    require_roles(actor, ["QaReviewer"])
    insp = get_inspection(id)
    if insp["status"] != "QA_REVIEW":
        raise err_invalid_state("inspection not QA_REVIEW")
    _qa_gate(actor, insp)
    # reject_count semantics: if currently 2, this third reject auto-voids
    if insp["reject_count"] >= 2:
        insp["reject_count"] = 3
        insp["status"] = "VOIDED"
        db.touch(insp)
        _auto_void_warranty_cases(insp["id"])
    else:
        insp["reject_count"] += 1
        insp["status"] = "CODING"
        db.touch(insp)
    sweep_notice_expiry()
    return success_object(inspection_view(insp))


@bp.post("/sewer/cctv-inspections/<id>/void")
def void_inspection(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    insp = get_inspection(id)
    if insp["status"] not in ("SCHEDULED", "CODING"):
        raise err_invalid_state("inspection not SCHEDULED/CODING")
    insp["status"] = "VOIDED"
    db.touch(insp)
    _auto_void_warranty_cases(insp["id"])
    sweep_notice_expiry()
    return success_object(inspection_view(insp))


# ---------------------------------------------------------------------------
# Defects
# ---------------------------------------------------------------------------

@bp.post("/sewer/cctv-inspections/<id>/defects")
def create_defect(id):
    actor = get_actor()
    require_roles(actor, ["Coder"])
    insp = get_inspection(id)
    if insp["status"] != "CODING":
        raise err_invalid_state("defects only writable while inspection is CODING")
    _coder_gate(actor, insp)
    segment = db.segments[insp["segment_id"]]
    payload = body()
    pacp_code = require_string(payload, "pacp_code")
    if not PACP_CODE_RE.match(pacp_code):
        raise err_invalid_request("pacp_code must be uppercase 1-6 chars")
    family = require_enum(payload, "family", FAMILIES)
    grade = require_int(payload, "grade")
    distance = require_number(payload, "distance_m")
    clock_pos = require_int(payload, "clock_position")
    extent = payload.get("extent_m", 0)
    if isinstance(extent, bool) or not isinstance(extent, (int, float)):
        raise err_invalid_request("extent_m must be a number")
    # ERR_DEFECT_OUT_OF_RANGE for grade/distance/clock violations
    if grade < 1 or grade > 5:
        raise err_conflict("ERR_DEFECT_OUT_OF_RANGE", "grade must be 1-5")
    if distance < 0 or distance > segment["length_m"]:
        raise err_conflict("ERR_DEFECT_OUT_OF_RANGE", "distance_m out of segment bounds")
    if clock_pos < 0 or clock_pos > 12:
        raise err_conflict("ERR_DEFECT_OUT_OF_RANGE", "clock_position must be 0-12")
    if extent < 0:
        raise err_invalid_request("extent_m must be >= 0")
    ent = {
        "id": db.new_id(),
        "inspection_id": insp["id"],
        "pacp_code": pacp_code,
        "family": family,
        "grade": grade,
        "distance_m": distance,
        "clock_position": clock_pos,
        "extent_m": extent,
        "created_at": db.now_iso(),
    }
    db.defects[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(defect_view(ent), status=201)


@bp.get("/sewer/cctv-inspections/<id>/defects")
def list_defects(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    insp = get_inspection(id)
    limit, offset = parse_pagination()
    items = [d for d in db.defects.values() if d["inspection_id"] == insp["id"]]
    fam = request.args.get("family")
    if fam:
        items = [d for d in items if d["family"] == fam]
    page, total = paginate(items, limit, offset)
    return success_list([defect_view(d) for d in page], limit, offset, total)


@bp.delete("/sewer/cctv-inspections/<id>/defects/<defectId>")
def delete_defect(id, defectId):
    actor = get_actor()
    require_roles(actor, ["Coder"])
    insp = get_inspection(id)
    d = db.defects.get(defectId)
    if d is None or d["inspection_id"] != insp["id"]:
        raise err_not_found("defect not found on inspection")
    if insp["status"] != "CODING":
        raise err_invalid_state("defects only removable while inspection is CODING")
    _coder_gate(actor, insp)
    del db.defects[defectId]
    sweep_notice_expiry()
    return ("", 204)
