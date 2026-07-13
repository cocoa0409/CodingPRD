"""Inspection scheduling, conduct, and completion routes."""
from datetime import timedelta
from flask import Blueprint, request
from store import store, new_entity, touch
from auth import require_role, body, as_int, check_enum
from errors import err
from lookups import (
    get_property, get_inspector, get_complaint, get_inspection, sorted_by_creation,
)
from pagination import paginate
from envelope import success, list_response
from serializers import inspection_dict, checklist_item_dict
from domain import complete_inspection
from timeutil import parse_iso
from calc import COOLDOWN_HOURS, REINSPECTION_MIN_HOURS

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = {"PERIODIC", "COMPLAINT", "REINSPECTION"}
CHECKLIST_CATEGORIES = {"LIFE_SAFETY", "HABITABILITY", "LEAD_PAINT", "STRUCTURAL"}
CHECKLIST_RESULTS = {"PASS", "FAIL", "NOT_APPLICABLE"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
NON_TERMINAL_INSPECTION = {"SCHEDULED", "IN_PROGRESS"}


def _end(insp):
    return insp["scheduled_date"] + timedelta(minutes=insp["duration_minutes"])


@bp.post("/inspections")
def schedule_inspection():
    require_role({"Inspector", "Registrar"})
    data = body()

    # Existence of referenced FKs (priority 5), for those provided.
    if data.get("property_id") is not None:
        prop = get_property(data["property_id"])
    if data.get("inspector_id") is not None:
        get_inspector(data["inspector_id"])
    complaint = None
    if data.get("complaint_id") is not None:
        complaint = get_complaint(data["complaint_id"])
    prior = None
    if data.get("prior_inspection_id") is not None:
        prior = get_inspection(data["prior_inspection_id"])

    # Structural validation (priority 6).
    for f in ("property_id", "inspector_id", "inspection_type", "scheduled_date"):
        if data.get(f) is None:
            raise err("ERR_VALIDATION", f"Missing required field: {f}")
    itype = check_enum(data["inspection_type"], "inspection_type", INSPECTION_TYPES)
    scheduled_date = parse_iso(data["scheduled_date"])
    if scheduled_date is None:
        raise err("ERR_VALIDATION", "scheduled_date must be a valid ISO-8601 timestamp")
    duration = data.get("duration_minutes", 60)
    if duration is None:
        duration = 60
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise err("ERR_VALIDATION", "duration_minutes must be a positive integer")
    if itype == "COMPLAINT" and data.get("complaint_id") is None:
        raise err("ERR_VALIDATION", "COMPLAINT inspection requires complaint_id")
    if itype == "REINSPECTION" and data.get("prior_inspection_id") is None:
        raise err("ERR_VALIDATION", "REINSPECTION inspection requires prior_inspection_id")

    prop = store.properties[data["property_id"]]

    # State preconditions (priority 7).
    if itype == "COMPLAINT" and complaint["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Complaint is not in FILED state")
    if itype == "REINSPECTION" and prior["status"] != "FAILED":
        raise err("ERR_INVALID_STATE", "Prior inspection is not FAILED")

    new_insp = {
        "property_id": data["property_id"],
        "inspector_id": data["inspector_id"],
        "inspection_type": itype,
        "complaint_id": data.get("complaint_id") if itype == "COMPLAINT" else None,
        "prior_inspection_id": data.get("prior_inspection_id") if itype == "REINSPECTION" else None,
        "scheduled_date": scheduled_date,
        "duration_minutes": duration,
        "status": "SCHEDULED",
        "conducted_at": None,
        "result_score": None,
    }
    new_end = scheduled_date + timedelta(minutes=duration)

    # Guardrail: inspector double-booking (priority 13, half-open overlap).
    for other in store.inspections.values():
        if other["inspector_id"] != new_insp["inspector_id"]:
            continue
        if scheduled_date < _end(other) and other["scheduled_date"] < new_end:
            raise err("ERR_INSPECTOR_DOUBLE_BOOKED", "Inspector has an overlapping inspection")

    # Guardrail: property cooldown (priority 14, closed 24h buffer, non-terminal).
    window = timedelta(hours=COOLDOWN_HOURS)
    for other in store.inspections.values():
        if other["property_id"] != new_insp["property_id"]:
            continue
        if other["status"] not in NON_TERMINAL_INSPECTION:
            continue
        if abs(scheduled_date - other["scheduled_date"]) <= window:
            raise err("ERR_INSPECTION_COOLDOWN", "Another inspection is within the cooldown window")

    # Guardrail: reinspection minimum delay (priority 15).
    if itype == "REINSPECTION":
        earliest = prior["conducted_at"] + timedelta(hours=REINSPECTION_MIN_HOURS)
        if scheduled_date < earliest:
            raise err("ERR_REINSPECTION_TOO_EARLY", "Reinspection scheduled too early")

    insp = new_entity(store.inspections, new_insp)

    if itype == "COMPLAINT":
        complaint["status"] = "INSPECTION_SCHEDULED"
        touch(complaint)

    return success(inspection_dict(insp), status=201)


@bp.get("/inspections/<iid>")
def get_inspection_route(iid):
    require_role({"Inspector", "Registrar", "Landlord"})
    insp = get_inspection(iid)
    return success(inspection_dict(insp), status=200)


@bp.get("/inspections")
def list_inspections():
    require_role({"Inspector", "Registrar", "Landlord"})
    items = list(store.inspections.values())
    for key in ("property_id", "inspector_id", "complaint_id", "prior_inspection_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return list_response([inspection_dict(i) for i in page], limit, offset, total)


@bp.post("/inspections/<iid>/begin")
def begin_inspection(iid):
    uid, role = require_role({"Inspector"})
    insp = get_inspection(iid)
    if uid != insp["inspector_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Only the assigned inspector may begin")
    if insp["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Inspection is not SCHEDULED")
    prop = store.properties[insp["property_id"]]
    # Begin requires a REGISTERED property. A REINSPECTION is the mechanism that
    # lifts a suspension, so it is permitted on a SUSPENDED property as well;
    # a CONDEMNED (terminal) property is never inspectable.
    registered = prop["registration_status"] == "REGISTERED"
    reinspect_suspended = (
        insp["inspection_type"] == "REINSPECTION"
        and prop["registration_status"] == "SUSPENDED"
    )
    if not (registered or reinspect_suspended):
        raise err("ERR_PROPERTY_NOT_REGISTERED", "Property is not REGISTERED")
    insp["status"] = "IN_PROGRESS"
    touch(insp)
    return success(inspection_dict(insp), status=200)


@bp.post("/inspections/<iid>/checklist-items")
def record_checklist_item(iid):
    uid, role = require_role({"Inspector"})
    insp = get_inspection(iid)
    if uid != insp["inspector_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Only the assigned inspector may record items")
    data = body()
    for f in ("category", "code", "result"):
        if data.get(f) is None:
            raise err("ERR_VALIDATION", f"Missing required field: {f}")
    check_enum(data["category"], "category", CHECKLIST_CATEGORIES)
    check_enum(data["result"], "result", CHECKLIST_RESULTS)
    severity = data.get("severity", "MINOR")
    if severity is None:
        severity = "MINOR"
    check_enum(severity, "severity", SEVERITIES)
    if insp["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Inspection is not IN_PROGRESS")
    item = new_entity(store.checklist_items, {
        "inspection_id": insp["id"],
        "category": data["category"],
        "code": data["code"],
        "result": data["result"],
        "severity": severity,
        "notes": data.get("notes"),
    }, common=False)
    return success(checklist_item_dict(item), status=201)


@bp.get("/inspections/<iid>/checklist-items")
def list_checklist_items(iid):
    require_role({"Inspector", "Registrar", "Landlord"})
    get_inspection(iid)
    items = sorted_by_creation(
        [c for c in store.checklist_items.values() if c["inspection_id"] == iid]
    )
    page, limit, offset, total = paginate(items)
    return list_response([checklist_item_dict(c) for c in page], limit, offset, total)


@bp.post("/inspections/<iid>/complete")
def complete_inspection_route(iid):
    uid, role = require_role({"Inspector"})
    insp = get_inspection(iid)
    if uid != insp["inspector_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Only the assigned inspector may complete")
    if insp["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Inspection is not IN_PROGRESS")
    complete_inspection(insp)
    return success(inspection_dict(insp), status=200)
