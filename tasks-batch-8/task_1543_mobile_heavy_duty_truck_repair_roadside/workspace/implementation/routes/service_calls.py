"""ServiceCall endpoints: intake, triage, diagnose, repair, cancel, selector,
per-call event trail."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state,
                    err_call_terminal, err_validation)
from middleware import auth, require_fleet_ownership
from response import success
from serializers import serialize, serialize_call_event
from services.cascades import (append_event, free_technician, wall_now,
                               call_dispatches)
from services.pricing import active_dispatch
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("service_calls", __name__)

SYMPTOMS = {"ENGINE_NO_START", "OVERHEAT", "BRAKE_FAULT", "AIR_LEAK",
            "ELECTRICAL", "LIGHTING", "TIRE_BLOWOUT", "HVAC_ISSUE", "OTHER"}
SEVERITIES = {"BLOCKING", "DRIVABLE", "DEFERRED"}
RESOLUTION_PATHS = {"ON_SITE_REPAIR", "TOW_REQUIRED"}

PRIORITY_BY_SEVERITY = {
    "BLOCKING": "P1_EMERGENCY",
    "DRIVABLE": "P2_URGENT",
    "DEFERRED": "P3_STANDARD",
}
CERT_BY_SYMPTOM = {
    "ENGINE_NO_START": "ENGINE", "OVERHEAT": "ENGINE",
    "BRAKE_FAULT": "BRAKES", "AIR_LEAK": "BRAKES",
    "ELECTRICAL": "ELECTRICAL", "LIGHTING": "ELECTRICAL",
    "TIRE_BLOWOUT": "TIRES", "HVAC_ISSUE": "HVAC", "OTHER": "ANY",
}
PART_CLASS_BY_SYMPTOM = {
    "ENGINE_NO_START": "ENGINE", "OVERHEAT": "COOLING",
    "BRAKE_FAULT": "BRAKE", "AIR_LEAK": "AIR_SYSTEM",
    "ELECTRICAL": "ELECTRICAL", "LIGHTING": "LIGHTING",
    "TIRE_BLOWOUT": "TIRE", "HVAC_ISSUE": "HVAC", "OTHER": "NONE",
}

READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician", "FleetManager",
              "BillingClerk", "WarrantyAdministrator", "SafetyOfficer"]
LIST_ROLES = ["OpsAdmin", "Dispatcher", "FleetManager", "BillingClerk"]
EVENT_READ_ROLES = ["OpsAdmin", "Dispatcher", "FleetManager", "BillingClerk"]


def get_call_or_404(call_id):
    call = store.service_calls.get(call_id)
    if call is None:
        raise err_not_found("ServiceCall not found")
    return call


def ensure_not_cancelled(call):
    if call["status"] == "CANCELLED":
        raise err_call_terminal()


def fleet_gate_active(call):
    """Fleet-scoped writes require the fleet to be ACTIVE."""
    fleet_id = call.get("fleet_account_id")
    if not fleet_id:
        return
    fleet = store.fleets.get(fleet_id)
    if fleet is None:
        return
    if fleet["status"] == "SUSPENDED":
        raise ApiError("ERR_FLEET_SUSPENDED",
                       "Gated write attempted for a SUSPENDED fleet", 409)
    if fleet["status"] == "CLOSED":
        raise ApiError("ERR_FLEET_CLOSED",
                       "Gated write attempted for a CLOSED fleet", 409)


def onsite_dispatch_for(call):
    for d in call_dispatches(call["id"]):
        if d["status"] == "ON_SITE":
            return d
    return None


def _check_actor_is_onsite_tech(call, uid):
    disp = onsite_dispatch_for(call)
    if disp is None or disp["technician_id"] != uid:
        from errors import err_forbidden_ownership
        raise err_forbidden_ownership(
            "Actor is not the technician of the call's ON_SITE dispatch")


@bp.route("/roadside/service-calls", methods=["POST"])
def intake():
    uid, role = auth(["Dispatcher", "OpsAdmin"])
    vals = validate_body(request.get_json(silent=True), [
        Field("vehicle_id", "string", required=True),
        Field("caller_name", "string", required=True),
        Field("caller_phone", "string", required=True),
        Field("breakdown_location_text", "string", required=True),
        Field("distance_miles_from_depot", "int", required=True, min_val=0),
        Field("symptom_category", "enum", required=True, enum=SYMPTOMS),
        Field("symptom_description", "string", required=True),
    ])
    vehicle = store.vehicles.get(vals["vehicle_id"])
    if vehicle is None:
        raise err_not_found("Vehicle not found")
    fleet_id = vehicle.get("fleet_account_id")
    if fleet_id:
        fleet = store.fleets.get(fleet_id)
        if fleet is not None:
            if fleet["status"] == "SUSPENDED":
                raise ApiError("ERR_FLEET_SUSPENDED",
                               "Intake attempted for a SUSPENDED fleet", 409)
            if fleet["status"] == "CLOSED":
                raise ApiError("ERR_FLEET_CLOSED",
                               "Intake attempted for a CLOSED fleet", 409)
    received = store.clock
    hour = received.hour  # logical clock is UTC
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "vehicle_id": vehicle["id"],
        "fleet_account_id": fleet_id,
        "caller_name": vals["caller_name"],
        "caller_phone": vals["caller_phone"],
        "breakdown_location_text": vals["breakdown_location_text"],
        "distance_miles_from_depot": vals["distance_miles_from_depot"],
        "symptom_category": vals["symptom_category"],
        "symptom_description": vals["symptom_description"],
        "severity": None,
        "received_at": received,
        "after_hours": bool(hour >= 18 or hour < 6),
        "priority": None,
        "required_certification": None,
        "required_part_class": None,
        "status": "RECEIVED",
        "diagnosis_summary": None,
        "resolution_path": "PENDING",
        "labor_hours_actual": None,
        "completion_odometer_miles": None,
        "completed_at": None,
        "is_comeback": False,
        "repeat_of_call_id": None,
        "linked_defect_id": None,
        "hold_reason": "NONE",
        "status_before_invoice": None,
        "reopened_count": 0,
        "cancel_reason": None,
    })
    store.service_calls[rec["id"]] = rec
    append_event(rec["id"], "CALL_RECEIVED", role, uid)
    return success(serialize("service_call", rec), status=201)


@bp.route("/roadside/service-calls/<serviceCallId>", methods=["GET"])
def get_call(serviceCallId):
    uid, role = auth(READ_ROLES)
    call = get_call_or_404(serviceCallId)
    if role == "FleetManager":
        require_fleet_ownership(uid, call.get("fleet_account_id"))
    return success(serialize("service_call", call))


@bp.route("/roadside/service-calls", methods=["GET"])
def list_calls():
    uid, role = auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(store.service_calls.values(), key=lambda r: r["_seq"])
    if role == "FleetManager":
        items = [c for c in items if c.get("fleet_account_id") == uid]
    fleet_f = request.args.get("fleet_account_id")
    vehicle_f = request.args.get("vehicle_id")
    status_f = request.args.get("status")
    defect_f = request.args.get("linked_defect_id")
    repeat_f = request.args.get("repeat_of_call_id")
    if fleet_f is not None:
        items = [c for c in items if c.get("fleet_account_id") == fleet_f]
    if vehicle_f is not None:
        items = [c for c in items if c["vehicle_id"] == vehicle_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    if defect_f is not None:
        items = [c for c in items if c.get("linked_defect_id") == defect_f]
    if repeat_f is not None:
        items = [c for c in items if c.get("repeat_of_call_id") == repeat_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("service_call", c) for c in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/service-calls/<serviceCallId>/triage", methods=["POST"])
def triage(serviceCallId):
    uid, role = auth(["Dispatcher", "OpsAdmin"])
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("severity", "enum", required=True, enum=SEVERITIES),
        Field("symptom_category", "enum", enum=SYMPTOMS),
    ])
    ensure_not_cancelled(call)
    if call["status"] != "RECEIVED":
        raise err_invalid_state("Triage requires status RECEIVED")
    if "symptom_category" in vals:
        call["symptom_category"] = vals["symptom_category"]
    symptom = call["symptom_category"]
    call["severity"] = vals["severity"]
    call["priority"] = PRIORITY_BY_SEVERITY[vals["severity"]]
    call["required_certification"] = CERT_BY_SYMPTOM[symptom]
    call["required_part_class"] = PART_CLASS_BY_SYMPTOM[symptom]
    call["status"] = "TRIAGED"
    touch(call, wall_now())
    append_event(call["id"], "TRIAGED", role, uid)
    return success(serialize("service_call", call))


@bp.route("/roadside/service-calls/<serviceCallId>/diagnose", methods=["POST"])
def diagnose(serviceCallId):
    uid, role = auth(["Technician"])
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("diagnosis_summary", "string", required=True),
        Field("resolution_path", "enum", required=True, enum=RESOLUTION_PATHS),
    ])
    ensure_not_cancelled(call)
    if call["status"] != "ON_SITE":
        raise err_invalid_state("Diagnose requires status ON_SITE")
    _check_actor_is_onsite_tech(call, uid)
    call["diagnosis_summary"] = vals["diagnosis_summary"]
    call["resolution_path"] = vals["resolution_path"]
    call["status"] = "DIAGNOSED"
    touch(call, wall_now())
    append_event(call["id"], "DIAGNOSED", role, uid)
    return success(serialize("service_call", call))


@bp.route("/roadside/service-calls/<serviceCallId>/start-repair", methods=["POST"])
def start_repair(serviceCallId):
    uid, role = auth(["Technician"])
    call = get_call_or_404(serviceCallId)
    validate_body(request.get_json(silent=True), [])
    ensure_not_cancelled(call)
    if call["status"] != "DIAGNOSED":
        raise err_invalid_state("Start-repair requires status DIAGNOSED")
    _check_actor_is_onsite_tech(call, uid)
    # PRD 3.5 gate order: resolution path first, then the estimate gate
    if call["resolution_path"] != "ON_SITE_REPAIR":
        raise ApiError("ERR_RESOLUTION_PATH_CONFLICT",
                       "Start-repair requires resolution_path ON_SITE_REPAIR",
                       409)
    for est in store.estimates.values():
        if (est["service_call_id"] == call["id"]
                and est["status"] in ("DRAFT", "SUBMITTED")):
            raise ApiError("ERR_ESTIMATE_NOT_APPROVED",
                           "An estimate of the call is DRAFT or SUBMITTED", 409)
    call["status"] = "REPAIR_IN_PROGRESS"
    touch(call, wall_now())
    append_event(call["id"], "REPAIR_STARTED", role, uid)
    return success(serialize("service_call", call))


@bp.route("/roadside/service-calls/<serviceCallId>/complete-repair",
          methods=["POST"])
def complete_repair(serviceCallId):
    uid, role = auth(["Technician"])
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("labor_hours_actual", "number", required=True, min_val=0,
              quarter_hour=True),
        Field("completion_odometer_miles", "int", required=True, min_val=0),
    ])
    ensure_not_cancelled(call)
    if call["status"] != "REPAIR_IN_PROGRESS":
        raise err_invalid_state("Complete-repair requires REPAIR_IN_PROGRESS")
    _check_actor_is_onsite_tech(call, uid)
    vehicle = store.vehicles.get(call["vehicle_id"])
    if (vehicle is not None
            and vals["completion_odometer_miles"] < vehicle["odometer_miles"]):
        raise ApiError("ERR_ODOMETER_REGRESSION",
                       "completion_odometer_miles below vehicle.odometer_miles",
                       422)
    call["labor_hours_actual"] = vals["labor_hours_actual"]
    call["completion_odometer_miles"] = vals["completion_odometer_miles"]
    call["completed_at"] = store.clock
    call["status"] = "REPAIR_COMPLETED"
    touch(call, wall_now())
    if vehicle is not None:
        vehicle["odometer_miles"] = vals["completion_odometer_miles"]
        touch(vehicle, wall_now())
    append_event(call["id"], "REPAIR_COMPLETED", role, uid)
    return success(serialize("service_call", call))


@bp.route("/roadside/service-calls/<serviceCallId>/cancel", methods=["POST"])
def cancel(serviceCallId):
    uid, role = auth(["Dispatcher", "OpsAdmin", "FleetManager"])
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string", required=True),
    ])
    if role == "FleetManager":
        require_fleet_ownership(uid, call.get("fleet_account_id"))
    if call["status"] == "CANCELLED":
        raise err_call_terminal("Call is already CANCELLED")
    if call["status"] not in ("RECEIVED", "TRIAGED", "DISPATCHED", "EN_ROUTE"):
        raise err_invalid_state(
            "Cancel is allowed only from RECEIVED, TRIAGED, DISPATCHED, EN_ROUTE")
    if call["status"] in ("DISPATCHED", "EN_ROUTE"):
        for disp in call_dispatches(call["id"]):
            if disp["status"] in ("PROPOSED", "ACCEPTED", "EN_ROUTE"):
                disp["status"] = "RELEASED"
                touch(disp, wall_now())
                free_technician(disp["technician_id"])
    call["status"] = "CANCELLED"
    call["cancel_reason"] = vals["reason"]
    touch(call, wall_now())
    append_event(call["id"], "CALL_CANCELLED", role, uid)
    return success(serialize("service_call", call))


@bp.route("/roadside/service-calls/<serviceCallId>/dispatch-suggestion",
          methods=["GET"])
def dispatch_suggestion(serviceCallId):
    auth(["Dispatcher", "OpsAdmin"])
    call = get_call_or_404(serviceCallId)
    if call["status"] != "TRIAGED":
        raise err_invalid_state("Dispatch suggestion requires status TRIAGED")
    req_cert = call.get("required_certification")
    req_part = call.get("required_part_class")
    eligible = []
    for tech in store.technicians.values():
        if tech["status"] != "AVAILABLE":
            continue
        if req_cert and req_cert != "ANY" and req_cert not in tech["certifications"]:
            continue
        if req_part and req_part != "NONE":
            has_part = any(
                i["technician_id"] == tech["id"]
                and i["part_class"] == req_part and i["qty_on_hand"] >= 1
                for i in store.van_stock.values())
            if not has_part:
                continue
        eligible.append(tech)

    def sort_key(tech):
        active = sum(
            1 for d in store.dispatches.values()
            if d["technician_id"] == tech["id"]
            and d["status"] in ("PROPOSED", "ACCEPTED", "EN_ROUTE", "ON_SITE"))
        completed = [d["completed_at"] for d in store.dispatches.values()
                     if d["technician_id"] == tech["id"]
                     and d["status"] == "COMPLETED"
                     and d.get("completed_at") is not None]
        # never-completed sorts first
        last_completed = max(completed) if completed else None
        completed_key = (1, last_completed) if last_completed else (0, None)
        return (active, completed_key, tech["_seq"])

    eligible.sort(key=sort_key)
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_TECHNICIAN",
                       "Eligible technician pool is empty", 409)
    ranked = [t["id"] for t in eligible]
    return success({"candidate_technician_id": ranked[0],
                    "ranked_technician_ids": ranked})


@bp.route("/roadside/service-calls/<serviceCallId>/events", methods=["GET"])
def call_events(serviceCallId):
    uid, role = auth(EVENT_READ_ROLES)
    call = get_call_or_404(serviceCallId)
    if role == "FleetManager":
        require_fleet_ownership(uid, call.get("fleet_account_id"))
    limit, offset = parse_pagination(request.args)
    etype = request.args.get("event_type")
    items = sorted(
        (e for e in store.call_events.values()
         if e["service_call_id"] == call["id"]),
        key=lambda r: r["_seq"])
    if etype is not None:
        items = [e for e in items if e["event_type"] == etype]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize_call_event(e) for e in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})
