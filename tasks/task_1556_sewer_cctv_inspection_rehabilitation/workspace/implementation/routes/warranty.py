"""WarrantyCase endpoints."""
from flask import Blueprint, request

import db
from db import _parse_iso, _format_iso
from middleware import get_actor, require_roles
from response import success_object, success_list
from errors import err_invalid_request, err_invalid_state, err_not_found, err_conflict
from services.common import (
    body, require_string, parse_datetime_field, parse_pagination, paginate,
    get_segment, get_warranty_case, sweep_notice_expiry,
)

bp = Blueprint("warranty", __name__)

READ_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead"]


def case_view(c):
    return {
        "id": c["id"],
        "segment_id": c["segment_id"],
        "work_order_id": c["work_order_id"],
        "opened_at": c["opened_at"],
        "defect_summary": c["defect_summary"],
        "re_inspection_id": c["re_inspection_id"],
        "status": c["status"],
        "resolution_note": c.get("resolution_note"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/sewer/segments/<id>/warranty-cases")
def create_case(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    segment = get_segment(id)
    payload = body()
    work_order_id = require_string(payload, "work_order_id")
    defect_summary = require_string(payload, "defect_summary")
    cycle_id = require_string(payload, "cycle_id")
    scheduled = parse_datetime_field(payload, "scheduled_at", required=True)
    coder_id = require_string(payload, "coder_id")
    wo = db.work_orders.get(work_order_id)
    if wo is None:
        raise err_not_found("work order not found")
    plan = db.plans.get(wo["plan_id"])
    if plan is None or plan["segment_id"] != segment["id"]:
        raise err_not_found("work order not on this segment")
    if wo["execution_status"] != "COMPLETED":
        raise err_invalid_request("work order must be COMPLETED")
    cycle = db.cycles.get(cycle_id)
    if cycle is None:
        raise err_not_found("cycle not found")
    if cycle["district_id"] != segment["district_id"]:
        raise err_not_found("cycle not in same district")
    coder = db.technicians.get(coder_id)
    if coder is None:
        raise err_not_found("coder not found")
    if not coder.get("active", True) or "CODER" not in (coder.get("capabilities") or []):
        raise err_invalid_request("coder must be active and hold CODER capability")
    # scheduled_at inside cycle window
    ws = _parse_iso(cycle["window_start"])
    we = _parse_iso(cycle["window_end"])
    if not (ws <= scheduled <= we):
        raise err_conflict("ERR_OUTSIDE_CYCLE_WINDOW", "scheduled_at outside cycle window")
    # warranty expiry gate
    now = db.now_dt()
    if wo.get("warranty_expires_at") is None:
        raise err_invalid_request("referenced work order has no warranty window")
    if now > _parse_iso(wo["warranty_expires_at"]):
        raise err_conflict("ERR_WARRANTY_EXPIRED", "warranty window has closed")
    # create the linked WARRANTY_RE inspection in SCHEDULED
    insp = {
        "id": db.new_id(),
        "segment_id": segment["id"],
        "cycle_id": cycle["id"],
        "scheduled_at": _format_iso(scheduled),
        "coder_id": coder_id,
        "qa_reviewer_id": None,
        "purpose": "WARRANTY_RE",
        "status": "SCHEDULED",
        "reject_count": 0,
        "certified_at": None,
    }
    db.stamp_new(insp)
    db.inspections[insp["id"]] = insp
    ent = {
        "id": db.new_id(),
        "segment_id": segment["id"],
        "work_order_id": work_order_id,
        "opened_at": db.now_iso(),
        "defect_summary": defect_summary,
        "re_inspection_id": insp["id"],
        "status": "OPENED",
        "resolution_note": None,
    }
    db.stamp_new(ent)
    db.warranty_cases[ent["id"]] = ent
    if segment["rehab_status"] == "REHABILITATED":
        segment["rehab_status"] = "WARRANTY"
        db.touch(segment)
    sweep_notice_expiry()
    return success_object(case_view(ent), status=201)


@bp.get("/sewer/warranty-cases/<id>")
def get_case(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    c = get_warranty_case(id)
    return success_object(case_view(c))


@bp.get("/sewer/segments/<id>/warranty-cases")
def list_cases_for_segment(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    segment = get_segment(id)
    limit, offset = parse_pagination()
    items = [c for c in db.warranty_cases.values() if c["segment_id"] == segment["id"]]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([case_view(c) for c in page], limit, offset, total)


@bp.get("/sewer/warranty-cases")
def list_cases_xseg():
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.warranty_cases.values())
    wo = request.args.get("work_order_id")
    if wo:
        items = [c for c in items if c["work_order_id"] == wo]
    ri = request.args.get("re_inspection_id")
    if ri:
        items = [c for c in items if c.get("re_inspection_id") == ri]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([case_view(c) for c in page], limit, offset, total)


def _linked_inspection(case):
    if not case.get("re_inspection_id"):
        return None
    return db.inspections.get(case["re_inspection_id"])


@bp.post("/sewer/warranty-cases/<id>/authorize-repair")
def authorize_repair(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    case = get_warranty_case(id)
    if case["status"] != "RE_INSPECTION":
        raise err_invalid_state("case not RE_INSPECTION")
    insp = _linked_inspection(case)
    segment = db.segments[case["segment_id"]]
    if insp is None or insp["status"] != "CERTIFIED" or segment["structural_grade"] < 4:
        raise err_conflict("ERR_DEFECT_UNCONFIRMED", "requires certified re-inspection with structural_grade >= 4")
    case["status"] = "UNDER_REPAIR"
    db.touch(case)
    sweep_notice_expiry()
    return success_object(case_view(case))


@bp.post("/sewer/warranty-cases/<id>/deny")
def deny(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    case = get_warranty_case(id)
    if case["status"] != "RE_INSPECTION":
        raise err_invalid_state("case not RE_INSPECTION")
    payload = body()
    note = payload.get("resolution_note")
    if not note or not isinstance(note, str):
        raise err_invalid_request("resolution_note required")
    insp = _linked_inspection(case)
    if insp is None or insp["status"] != "CERTIFIED":
        raise err_conflict("ERR_BASIS_NOT_CERTIFIED", "re-inspection not CERTIFIED")
    case["resolution_note"] = note
    case["status"] = "DENIED"
    db.touch(case)
    sweep_notice_expiry()
    return success_object(case_view(case))


@bp.post("/sewer/warranty-cases/<id>/resolve")
def resolve(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    case = get_warranty_case(id)
    if case["status"] != "UNDER_REPAIR":
        raise err_invalid_state("case not UNDER_REPAIR")
    payload = body()
    note = payload.get("resolution_note")
    if not note or not isinstance(note, str):
        raise err_invalid_request("resolution_note required")
    case["resolution_note"] = note
    case["status"] = "RESOLVED"
    db.touch(case)
    sweep_notice_expiry()
    return success_object(case_view(case))


@bp.post("/sewer/warranty-cases/<id>/reopen")
def reopen(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    case = get_warranty_case(id)
    if case["status"] != "RESOLVED":
        raise err_invalid_state("case not RESOLVED")
    wo = db.work_orders.get(case["work_order_id"])
    if wo is None or wo.get("warranty_expires_at") is None:
        raise err_invalid_request("referenced work order has no warranty window")
    now = db.now_dt()
    if now > _parse_iso(wo["warranty_expires_at"]):
        raise err_conflict("ERR_WARRANTY_EXPIRED", "warranty window has closed")
    case["status"] = "OPENED"
    db.touch(case)
    sweep_notice_expiry()
    return success_object(case_view(case))


@bp.post("/sewer/warranty-cases/<id>/withdraw")
def withdraw(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    case = get_warranty_case(id)
    if case["status"] not in ("OPENED", "RE_INSPECTION"):
        raise err_invalid_state("case not OPENED/RE_INSPECTION")
    from_re_inspection = case["status"] == "RE_INSPECTION"
    case["status"] = "WITHDRAWN"
    db.touch(case)
    if from_re_inspection:
        insp = _linked_inspection(case)
        if insp is not None and insp["status"] in ("SCHEDULED", "CODING"):
            insp["status"] = "VOIDED"
            db.touch(insp)
    sweep_notice_expiry()
    return success_object(case_view(case))
