"""Flight operations and operators (PRD §3.1, §3.2)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_flight, ser_operator, ser_notification
import services
from services import touch, compute_curfew_flags
from util import now, parse_quarter_label, quarter_key_of
from validate import validate, parse_pagination

bp = Blueprint("flights", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

ENGINE_CLASSES = ["STAGE_3", "STAGE_4", "STAGE_5"]
OPERATION_TYPES = ["ARRIVAL", "DEPARTURE", "RUNUP"]
EXEMPTIONS = ["NONE", "EMERGENCY", "WEATHER_DIVERT", "ATC_DELAY"]


def _get_flight(fid):
    f = db.flights.get(fid)
    if f is None:
        raise err("ERR_NOT_FOUND", f"FlightOperation {fid} not found")
    return f


def _get_operator(oid):
    o = db.operators.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", f"Operator {oid} not found")
    return o


def _flight_quarter(f):
    dt = f.get("actual_at") if f["status"] == "OPERATED" and f.get("actual_at") \
        else f["scheduled_at"]
    return quarter_key_of(dt)


# ------------------------------ flights ------------------------------------

@bp.post("/flight-operations")
def create_flight():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("flight_number", "str", True),
        ("operator_id", "str", True),
        ("aircraft_type", "str", True),
        ("engine_class", "enum", True, {"enum": ENGINE_CLASSES}),
        ("operation_type", "enum", True, {"enum": OPERATION_TYPES}),
        ("runway_code", "str", True),
        ("scheduled_at", "dt", True),
        ("zone_code", "str", True),
    ])
    require_role(caller, ["NoiseOfficeAdmin"])
    if data["operator_id"] not in db.operators:
        raise err("ERR_OPERATOR_NOT_FOUND",
                  f"Operator {data['operator_id']} not found")
    t = now()
    f = {
        "id": new_id(),
        "flight_number": data["flight_number"],
        "operator_id": data["operator_id"],
        "aircraft_type": data["aircraft_type"],
        "engine_class": data["engine_class"],
        "operation_type": data["operation_type"],
        "runway_code": data["runway_code"],
        "scheduled_at": data["scheduled_at"],
        "actual_at": None,
        "status": "SCHEDULED",
        "exemption_code": "NONE",
        "zone_code": data["zone_code"],
        "linked_complaint_count": 0,
        "linked_event_count": 0,
        "curfew_movement": False,
        "curfew_violation": False,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.flights[f["id"]] = f
    return success_object(ser_flight(f), status=201)


@bp.get("/flight-operations")
def list_flights():
    caller = get_caller()
    require_role(caller, STAFF + ["OperatorRep"])
    limit, offset = parse_pagination(request.args)
    f_operator = request.args.get("operator_id")
    f_status = request.args.get("status")
    f_runway = request.args.get("runway_code")
    f_quarter = request.args.get("quarter")
    if caller.role == "OperatorRep":
        f_operator = caller.user_id  # forced to own operator
    items = sorted(db.flights.values(), key=lambda f: f["created_at"])
    if f_operator is not None:
        items = [f for f in items if f["operator_id"] == f_operator]
    if f_status is not None:
        items = [f for f in items if f["status"] == f_status]
    if f_runway is not None:
        items = [f for f in items if f["runway_code"] == f_runway]
    if f_quarter is not None:
        items = [f for f in items if _flight_quarter(f) == f_quarter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_flight(f) for f in page], limit, offset, total)


@bp.get("/flight-operations/<flightId>")
def get_flight(flightId):
    caller = get_caller()
    require_role(caller, STAFF + ["OperatorRep"])
    f = _get_flight(flightId)
    if caller.role == "OperatorRep" and f["operator_id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "An OperatorRep may read only their own operator's flights")
    return success_object(ser_flight(f))


@bp.patch("/flight-operations/<flightId>")
def patch_flight(flightId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("status", "enum", False, {"enum": ["SCHEDULED", "OPERATED", "CANCELLED", "DIVERTED"]}),
        ("actual_at", "dt", False),
        ("exemption_code", "enum", False, {"enum": EXEMPTIONS}),
    ])
    require_role(caller, ["NoiseOfficeAdmin"])
    f = _get_flight(flightId)
    if f["status"] != "SCHEDULED":
        raise err("ERR_INVALID_FLIGHT_STATE",
                  "Outcomes may be recorded only while SCHEDULED")
    changed = False
    if "exemption_code" in data:
        f["exemption_code"] = data["exemption_code"]
        changed = True
    target = data.get("status")
    if target == "OPERATED":
        if "actual_at" not in data:
            raise err("ERR_VALIDATION",
                      "actual_at is required when recording OPERATED")
        f["actual_at"] = data["actual_at"]
        f["status"] = "OPERATED"
        movement, violation = compute_curfew_flags(f)
        f["curfew_movement"] = movement
        f["curfew_violation"] = violation
        changed = True
    elif target in ("CANCELLED", "DIVERTED"):
        f["status"] = target
        changed = True
    elif target == "SCHEDULED":
        raise err("ERR_VALIDATION", "status outcome must be OPERATED, CANCELLED or DIVERTED")
    if changed:
        touch(f)
    return success_object(ser_flight(f))


# ------------------------------ operators ----------------------------------

@bp.post("/operators")
def create_operator():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("name", "str", True),
        ("iata_code", "str", True),
        ("contact_email", "str", True),
    ])
    require_role(caller, ["NoiseOfficeAdmin"])
    if not (2 <= len(data["iata_code"]) <= 3):
        raise err("ERR_VALIDATION", "iata_code must be 2-3 characters")
    for o in db.operators.values():
        if o["iata_code"] == data["iata_code"]:
            raise err("ERR_DUPLICATE_IATA_CODE",
                      f"iata_code {data['iata_code']} is already registered")
    t = now()
    o = {
        "id": new_id(),
        "name": data["name"],
        "iata_code": data["iata_code"],
        "contact_email": data["contact_email"],
        "compliance_standing": "GOOD",
        "curfew_grace_minutes": 15,
        "compliance_score_latest": None,
        "notifications_sent_total": 0,
        "notifications_open": 0,
        "notifications_closed": 0,
        "notifications_draft": 0,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.operators[o["id"]] = o
    return success_object(ser_operator(o), status=201)


@bp.get("/operators")
def list_operators():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    standing = request.args.get("compliance_standing")
    items = sorted(db.operators.values(), key=lambda o: o["created_at"])
    if standing is not None:
        items = [o for o in items if o["compliance_standing"] == standing]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_operator(o) for o in page], limit, offset, total)


@bp.get("/operators/<operatorId>")
def get_operator(operatorId):
    caller = get_caller()
    require_role(caller, STAFF + ["OperatorRep"])
    o = _get_operator(operatorId)
    if caller.role == "OperatorRep" and o["id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "An OperatorRep may read only their own operator record")
    return success_object(ser_operator(o))


@bp.get("/operators/<operatorId>/operator-notifications")
def list_operator_notifications(operatorId):
    caller = get_caller()
    require_role(caller, STAFF + ["OperatorRep"])
    o = _get_operator(operatorId)
    if caller.role == "OperatorRep" and o["id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "An OperatorRep may read only their own notifications")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted((n for n in db.notifications.values()
                    if n["operator_id"] == o["id"]),
                   key=lambda n: n["created_at"])
    if status is not None:
        items = [n for n in items if n["status"] == status]
    for n in items:
        services.sweep_notification_on_read(n)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_notification(n) for n in page], limit, offset, total)


@bp.get("/operators/<operatorId>/compliance-summary")
def compliance_summary(operatorId):
    caller = get_caller()
    require_role(caller, STAFF + ["OperatorRep"])
    o = _get_operator(operatorId)
    if caller.role == "OperatorRep" and o["id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "An OperatorRep may read only their own compliance summary")
    raw = request.args.get("quarter")
    q = parse_quarter_label(raw)
    if q is None:
        raise err("ERR_VALIDATION", "quarter query parameter must match YYYY-Qn")
    year, qn = q
    movements, violations, score, band = services.compliance_score(o, year, qn)
    o["compliance_score_latest"] = score
    if o["compliance_standing"] != band:
        o["compliance_standing"] = band
    touch(o)
    return success_object({
        "quarter": f"{year:04d}-Q{qn}",
        "curfew_movements": movements,
        "curfew_violations": violations,
        "score": score,
        "standing": band,
    })
