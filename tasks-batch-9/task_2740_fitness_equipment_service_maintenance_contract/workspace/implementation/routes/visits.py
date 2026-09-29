"""Preventive visits: scheduling, checklist execution, disposal, safety doc."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import calc, domain, validate

bp = Blueprint("visits", __name__)


def _window_checks(club, window_start, window_end):
    if window_end <= window_start:
        raise ApiError("ERR_VISIT_WINDOW_INVALID")
    span_seconds = (window_end - window_start).total_seconds()
    if span_seconds > calc.VISIT_MAX_SPAN_MINUTES * 60:
        raise ApiError("ERR_VISIT_WINDOW_INVALID")
    midnight = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    start_offset = (window_start - midnight).total_seconds()
    end_offset = start_offset + span_seconds
    if start_offset < club["operating_open_minute"] * 60:
        raise ApiError("ERR_VISIT_WINDOW_INVALID")
    if end_offset > club["operating_close_minute"] * 60:
        raise ApiError("ERR_VISIT_WINDOW_INVALID")


def _club_capacity_check(club, window_start, window_end):
    """Visit windows are CLOSED intervals: touching endpoints do collide."""
    fleet_ids = {e["id"] for e in domain.club_equipment(club["id"])}
    overlapping = 0
    for visit in db.visits.values():
        if visit["equipment_id"] not in fleet_ids:
            continue
        if visit["visit_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        existing_start = db.parse_iso(visit["window_start"])
        existing_end = db.parse_iso(visit["window_end"])
        if window_start <= existing_end and existing_start <= window_end:
            overlapping += 1
    if overlapping + 1 > club["max_concurrent_visits"]:
        raise ApiError("ERR_CLUB_VISIT_CAPACITY")


@bp.post("/fleetcare/preventive-visits")
def create_visit():
    middleware.auth(middleware.SERVICE_COORDINATOR)
    body = middleware.body()
    contract_id = validate.identifier(body, "contract_id")
    equipment_id = validate.identifier(body, "equipment_id")
    window_start = validate.instant(body, "window_start")
    window_end = validate.instant(body, "window_end")
    technician_id = validate.identifier(body, "technician_id", required=False)

    contract = domain.need_contract(contract_id)
    equipment_row = domain.need_equipment(equipment_id)
    named = domain.need_technician(technician_id) if technician_id is not None else None

    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    if equipment_row["club_id"] != contract["club_id"]:
        raise ApiError("ERR_EQUIPMENT_CLUB_MISMATCH")

    club = db.clubs[contract["club_id"]]
    category = domain.model_category_of(equipment_row)
    if named is not None:
        if named["region_code"] != club["region_code"]:
            raise ApiError("ERR_TECHNICIAN_REGION_MISMATCH")
        if category not in named["skill_categories"]:
            raise ApiError("ERR_TECHNICIAN_SKILL_MISMATCH")
        if named["duty_status"] != "ON_DUTY":
            raise ApiError("ERR_TECHNICIAN_OFF_DUTY")

    _window_checks(club, window_start, window_end)
    _club_capacity_check(club, window_start, window_end)

    planned_minutes = calc.minutes_between(window_start, window_end)
    if named is not None:
        if domain.has_window_conflict(named["id"], window_start, window_end):
            raise ApiError("ERR_TECHNICIAN_WINDOW_CONFLICT")
        if not domain.has_capacity(named, planned_minutes):
            raise ApiError("ERR_TECHNICIAN_CAPACITY_EXCEEDED")
        technician = named
    else:
        technician = domain.route_technician(
            club, category, equipment_row, window_start, window_end, planned_minutes
        )

    model = db.equipment_models.get(equipment_row["model_id"])
    checklist = []
    for element in (model["checklist_template"] if model else []):
        checklist.append({
            "code": element["code"],
            "is_safety_critical": element["is_safety_critical"],
            "consumable": element["consumable"],
            "result": "PENDING",
            "note": None,
            "consumable_replaced": False,
        })

    row = db.base_row()
    row.update({
        "contract_id": contract_id,
        "equipment_id": equipment_id,
        "assigned_technician_id": technician["id"],
        "window_start": db.iso(window_start),
        "window_end": db.iso(window_end),
        "planned_minutes": planned_minutes,
        "visit_status": "SCHEDULED",
        "safety_doc_status": "PENDING",
        "started_at": None,
        "completed_at": None,
        "usage_hours_at_visit": None,
        "checklist": checklist,
        "checklist_total_count": len(checklist),
        "checklist_resolved_count": 0,
        "checklist_failed_count": 0,
        "safety_critical_failed_count": 0,
        "consumables_replaced_count": 0,
        "inspection_summary": None,
        "safety_doc_certified_by_id": None,
        "safety_doc_rejection_reason": None,
        "cancellation_reason": None,
        "pm_credit_earned": False,
    })
    db.visits[row["id"]] = row
    domain.create_assignment(technician, window_start, window_end,
                             preventive_visit_id=row["id"])
    return response.created_response(row)


@bp.get("/fleetcare/preventive-visits")
def list_visits():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.visits, {
        "contract_id": response.arg("contract_id"),
        "equipment_id": response.arg("equipment_id"),
        "assigned_technician_id": response.arg("assigned_technician_id"),
        "visit_status": response.arg("visit_status"),
        "safety_doc_status": response.arg("safety_doc_status"),
    })


@bp.get("/fleetcare/preventive-visits/<visit_id>")
def read_visit(visit_id):
    ctx = middleware.auth(*middleware.ALL_ROLES)
    visit = domain.need_visit(visit_id)
    middleware.require_club_scope(ctx, domain.club_id_of_contract(visit["contract_id"]))
    return response.object_response(visit)


def _recount_checklist(visit):
    checklist = visit["checklist"]
    resolved = len([e for e in checklist if e["result"] != "PENDING"])
    failed = len([e for e in checklist if e["result"] == "FAIL"])
    critical_failed = len([
        e for e in checklist if e["is_safety_critical"] and e["result"] == "FAIL"
    ])
    replaced = len([e for e in checklist if e["consumable_replaced"]])
    return {
        "checklist_resolved_count": resolved,
        "checklist_failed_count": failed,
        "safety_critical_failed_count": critical_failed,
        "consumables_replaced_count": replaced,
    }


def _pm_credit(visit_status, safety_doc_status):
    return visit_status == "COMPLETED" and safety_doc_status == "CERTIFIED"


@bp.post("/fleetcare/preventive-visits/<visit_id>/start")
def start_visit(visit_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    visit = domain.need_visit(visit_id)
    middleware.require_assigned(ctx, visit["assigned_technician_id"])
    if visit["visit_status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_INVALID_STATE")
    equipment_row = db.equipment.get(visit["equipment_id"])
    if equipment_row is not None and equipment_row["lifecycle_status"] == "TAGGED_OUT":
        raise ApiError("ERR_SAFETY_LOCKOUT_OPEN")

    db.apply_changes(visit, {
        "visit_status": "IN_PROGRESS",
        "started_at": db.now_iso(),
    })
    domain.confirm_assignment(
        domain.find_assignment(preventive_visit_id=visit["id"], statuses=("RESERVED",))
    )
    return response.object_response(visit)


@bp.post("/fleetcare/preventive-visits/<visit_id>/checklist-results")
def record_checklist_result(visit_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    visit = domain.need_visit(visit_id)
    middleware.require_assigned(ctx, visit["assigned_technician_id"])
    body = middleware.body()
    item_code = validate.string(body, "item_code", min_len=1, max_len=40)
    result = validate.enum(body, "result", calc.CHECKLIST_RESULTS)
    consumable_replaced = validate.boolean(body, "consumable_replaced", default=False)
    note = validate.string(body, "note", min_len=0, required=False, default=None)

    if visit["visit_status"] != "IN_PROGRESS":
        raise ApiError("ERR_VISIT_INVALID_STATE")
    element = None
    for candidate in visit["checklist"]:
        if candidate["code"] == item_code:
            element = candidate
            break
    if element is None:
        raise ApiError("ERR_CHECKLIST_ITEM_UNKNOWN")

    # Recording is idempotent-by-overwrite rather than append-only.
    element["result"] = result
    element["note"] = note
    element["consumable_replaced"] = consumable_replaced
    for field, value in _recount_checklist(visit).items():
        visit[field] = value
    db.touch(visit)

    # A safety-critical FAIL locks the machine out immediately. Correcting the
    # entry back to PASS lowers the counter but never clears the lockout: that
    # is a safety state and only the documented clearance path clears it.
    if element["is_safety_critical"] and result == "FAIL":
        equipment_row = db.equipment.get(visit["equipment_id"])
        if equipment_row is not None:
            domain.tag_out_equipment(equipment_row, "SAFETY_CRITICAL_FAIL")
    return response.object_response(visit)


@bp.post("/fleetcare/preventive-visits/<visit_id>/complete")
def complete_visit(visit_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    visit = domain.need_visit(visit_id)
    middleware.require_assigned(ctx, visit["assigned_technician_id"])
    if visit["visit_status"] != "IN_PROGRESS":
        raise ApiError("ERR_VISIT_INVALID_STATE")
    if visit["safety_critical_failed_count"] != 0:
        raise ApiError("ERR_SAFETY_CRITICAL_FAIL_BLOCKS_COMPLETION")
    if visit["checklist_resolved_count"] != visit["checklist_total_count"]:
        raise ApiError("ERR_CHECKLIST_INCOMPLETE")

    equipment_row = db.equipment.get(visit["equipment_id"])
    usage_hours = equipment_row["usage_hours"] if equipment_row is not None else None
    db.apply_changes(visit, {
        "visit_status": "COMPLETED",
        "completed_at": db.now_iso(),
        "usage_hours_at_visit": usage_hours,
        "pm_credit_earned": _pm_credit("COMPLETED", visit["safety_doc_status"]),
    })
    if equipment_row is not None:
        changes = {"usage_hours_at_last_pm": usage_hours}
        changes.update(domain.pm_status_fields(equipment_row, changes))
        db.apply_changes(equipment_row, changes)
    domain.complete_assignment(
        domain.find_assignment(preventive_visit_id=visit["id"], statuses=("CONFIRMED",))
    )
    contract = db.contracts.get(visit["contract_id"])
    if contract is not None:
        completed = contract["pm_visits_completed_count"] + 1
        db.apply_changes(contract, {
            "pm_visits_completed_count": completed,
            "pm_compliance_pct": calc.pm_compliance_pct(
                completed, contract["pm_visits_missed_count"]
            ),
        })
    return response.object_response(visit)


@bp.post("/fleetcare/preventive-visits/<visit_id>/cancel")
def cancel_visit(visit_id):
    middleware.auth(middleware.SERVICE_COORDINATOR)
    visit = domain.need_visit(visit_id)
    body = middleware.body()
    reason = validate.string(body, "reason", min_len=1)
    if visit["visit_status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_INVALID_STATE")

    db.apply_changes(visit, {
        "visit_status": "CANCELLED",
        "cancellation_reason": reason,
    })
    domain.release_assignment(
        domain.find_assignment(preventive_visit_id=visit["id"], statuses=("RESERVED",)),
        "VISIT_CANCELLED",
    )
    return response.object_response(visit)


@bp.post("/fleetcare/preventive-visits/<visit_id>/mark-missed")
def mark_visit_missed(visit_id):
    middleware.auth(middleware.SERVICE_COORDINATOR)
    visit = domain.need_visit(visit_id)
    if visit["visit_status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_INVALID_STATE")
    if db.now() < db.parse_iso(visit["window_end"]):
        raise ApiError("ERR_VISIT_INVALID_STATE")

    db.apply_changes(visit, {"visit_status": "MISSED"})
    domain.release_assignment(
        domain.find_assignment(preventive_visit_id=visit["id"], statuses=("RESERVED",)),
        "VISIT_MISSED",
    )
    contract = db.contracts.get(visit["contract_id"])
    if contract is not None:
        missed = contract["pm_visits_missed_count"] + 1
        db.apply_changes(contract, {
            "pm_visits_missed_count": missed,
            "pm_compliance_pct": calc.pm_compliance_pct(
                contract["pm_visits_completed_count"], missed
            ),
        })
    return response.object_response(visit)


@bp.post("/fleetcare/preventive-visits/<visit_id>/safety-doc/submit")
def submit_safety_doc(visit_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    visit = domain.need_visit(visit_id)
    middleware.require_assigned(ctx, visit["assigned_technician_id"])
    body = middleware.body()
    summary = validate.string(body, "inspection_summary", min_len=1)
    if visit["safety_doc_status"] not in ("PENDING", "REJECTED"):
        raise ApiError("ERR_SAFETY_DOC_INVALID_STATE")
    if visit["visit_status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise ApiError("ERR_SAFETY_DOC_INVALID_STATE")

    db.apply_changes(visit, {
        "safety_doc_status": "SUBMITTED",
        "inspection_summary": summary,
        "safety_doc_rejection_reason": None,
    })
    return response.object_response(visit)


@bp.post("/fleetcare/preventive-visits/<visit_id>/safety-doc/certify")
def certify_safety_doc(visit_id):
    ctx = middleware.auth(middleware.SAFETY_INSPECTOR)
    middleware.require_inspector(ctx)
    visit = domain.need_visit(visit_id)
    if visit["safety_doc_status"] != "SUBMITTED":
        raise ApiError("ERR_SAFETY_DOC_INVALID_STATE")
    if ctx["user_id"] == visit["assigned_technician_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    db.apply_changes(visit, {
        "safety_doc_status": "CERTIFIED",
        "safety_doc_certified_by_id": ctx["user_id"],
        "pm_credit_earned": _pm_credit(visit["visit_status"], "CERTIFIED"),
    })
    return response.object_response(visit)


@bp.post("/fleetcare/preventive-visits/<visit_id>/safety-doc/reject")
def reject_safety_doc(visit_id):
    ctx = middleware.auth(middleware.SAFETY_INSPECTOR)
    middleware.require_inspector(ctx)
    visit = domain.need_visit(visit_id)
    body = middleware.body()
    reason = validate.string(body, "rejection_reason", min_len=1)
    if visit["safety_doc_status"] != "SUBMITTED":
        raise ApiError("ERR_SAFETY_DOC_INVALID_STATE")
    if ctx["user_id"] == visit["assigned_technician_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    db.apply_changes(visit, {
        "safety_doc_status": "REJECTED",
        "safety_doc_rejection_reason": reason,
        "pm_credit_earned": False,
    })
    equipment_row = db.equipment.get(visit["equipment_id"])
    if equipment_row is not None:
        domain.tag_out_equipment(equipment_row, "SAFETY_DOC_REJECTED")
    return response.object_response(visit)
