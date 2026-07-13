"""Traffic Signal & Streetlight Maintenance API (Task 0841).

Python + Flask, in-memory storage only. Boots empty on every process start.
"""
import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from flask import Flask, request, jsonify

from errors import ApiError
from store import (
    store, parse_dt, fmt_dt, now_real,
    new_request_id,
    intersection_posture, pole_committed_load, crew_committed_hours,
)

app = Flask(__name__)

ROLES = {"Admin", "Dispatcher", "FieldTech", "TrafficEngineer", "UtilityCoordinator"}
ALL_ROLES = list(ROLES)

# Enum vocabularies
DEVICE_TYPES = {"SIGNAL_CONTROLLER", "SIGNAL_HEAD", "PED_SIGNAL", "DETECTOR", "STREETLIGHT"}
CRITICALITIES = {"CRITICAL", "STANDARD", "LOW"}
TICKET_SOURCES = {"SRC_311", "DETECTOR", "KNOCKDOWN"}
MOUNT_ZONES = {"LOW", "MID", "HIGH"}
WORK_TYPES = {"REPAIR", "PM_LAMP", "LED_REPLACEMENT", "EXCAVATION", "EMERGENCY"}
SPECIALTIES = {"SIGNAL", "LIGHTING", "LOCATE", "GENERAL"}

# Calculation constants
LABOR_RATE = Decimal("95.00")
OVERHEAD_PCT = Decimal("0.15")
SEVERITY_MULT = 8
HAZARD_BONUS = 25
SCORE_CAP = 100
P1_MIN, P2_MIN, P3_MIN = 80, 60, 35
SOURCE_WEIGHT = {"SRC_311": 10, "DETECTOR": 15, "KNOCKDOWN": 30}
CRIT_WEIGHT = {"CRITICAL": 40, "STANDARD": 20, "LOW": 10}
RESPONSE_SLA = {"P1": 60, "P2": 240, "P3": 1440, "P4": 4320}
RESOLUTION_SLA = {"P1": 240, "P2": 1440, "P3": 4320, "P4": 10080}
REOPEN_WINDOW_HOURS = 72
ATTACHMENT_BUFFER_DAYS = 7
WARRANTY_TERM_MONTHS = 60
FULL_COVERAGE_MONTHS = 12


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now_real()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", code=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_STATE", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    return uid, role


def require(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def body():
    return request.get_json(silent=True) or {}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def verr(msg="Invalid request body"):
    raise ApiError("ERR_VALIDATION", 422, msg)


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        verr("Field '%s' must be a non-empty string" % field)
    return v


def req_number(b, field):
    v = b.get(field)
    if not _is_number(v):
        verr("Field '%s' must be a number" % field)
    return v


def req_int(b, field):
    v = b.get(field)
    if not _is_int(v):
        verr("Field '%s' must be an integer" % field)
    return v


def req_enum(b, field, allowed):
    v = req_str(b, field)
    if v not in allowed:
        verr("Field '%s' has an invalid value" % field)
    return v


def opt_bool(b, field, default=False):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if not isinstance(v, bool):
        verr("Field '%s' must be a boolean" % field)
    return v


def req_datetime(b, field):
    v = b.get(field)
    if not isinstance(v, str):
        verr("Field '%s' must be an ISO-8601 datetime string" % field)
    try:
        return parse_dt(v)
    except Exception:
        verr("Field '%s' is not a valid datetime" % field)


def parts_list(b, field):
    """Validate and normalise an optional array of {qty, unit_price} line items."""
    v = b.get(field)
    if v is None:
        return []
    if not isinstance(v, list):
        verr("Field '%s' must be an array" % field)
    out = []
    for line in v:
        if not isinstance(line, dict):
            verr("Each %s line must be an object" % field)
        if not _is_number(line.get("qty")):
            verr("Each %s line requires a numeric 'qty'" % field)
        if not _is_number(line.get("unit_price")):
            verr("Each %s line requires a numeric 'unit_price'" % field)
        out.append({"qty": line["qty"], "unit_price": line["unit_price"]})
    return out


# ---------------------------------------------------------------------------
# Existence resolution (raises the resource-specific 404)
# ---------------------------------------------------------------------------
def resolve(value, table, err_id):
    """If value is a present string, resolve it or raise 404. None -> None."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in table:
        raise ApiError(err_id, 404, "Referenced resource not found")
    return table[value]


def get_or_404(table, rid, err_id):
    obj = table.get(rid)
    if obj is None:
        raise ApiError(err_id, 404, "Resource not found")
    return obj


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            verr("limit must be an integer")
        if limit < 1 or limit > 100:
            verr("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            verr("offset must be an integer")
        if offset < 0:
            verr("offset must not be negative")
    return limit, offset


def paginate(items, serializer):
    limit, offset = get_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [serializer(e) for e in page], pag


def clock():
    return store.clock


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def money(d):
    return float(d)


def compute_cost(hours, parts):
    h = Decimal(str(hours))
    labor = (h * LABOR_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    parts_total = Decimal("0")
    for line in parts:
        qty = Decimal(str(line["qty"]))
        up = Decimal(str(line["unit_price"]))
        parts_total += (qty * up).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    subtotal = labor + parts_total
    overhead = (subtotal * OVERHEAD_PCT).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return money(subtotal + overhead)


def whole_calendar_months(start, end):
    months = (end.year - start.year) * 12 + (end.month - start.month)
    start_key = (start.day, start.hour, start.minute, start.second, start.microsecond)
    end_key = (end.day, end.hour, end.minute, end.second, end.microsecond)
    if end_key < start_key:
        months -= 1
    return months


def compute_priority(ticket, device):
    src = SOURCE_WEIGHT[ticket["source"]]
    crit = CRIT_WEIGHT[device["criticality"]]
    sev = ticket["reported_severity"] * SEVERITY_MULT
    hazard = HAZARD_BONUS if ticket["hazard_flag"] else 0
    score = min(SCORE_CAP, src + crit + sev + hazard)
    if score >= P1_MIN or (ticket["hazard_flag"] and device["criticality"] == "CRITICAL"):
        band = "P1"
    elif score >= P2_MIN:
        band = "P2"
    elif score >= P3_MIN:
        band = "P3"
    else:
        band = "P4"
    return score, band


def ticket_sla_status(ticket):
    triaged = ticket.get("triaged_at")
    if triaged is None:
        return "PENDING"
    response_due = ticket.get("response_due")
    if ticket["status"] in ("RESOLVED", "CLOSED"):
        resolved = ticket.get("resolved_at")
        if resolved is not None and response_due is not None and resolved < response_due:
            return "ON_TRACK"
        return "BREACHED"
    if response_due is not None and clock() >= response_due:
        return "BREACHED"
    return "ON_TRACK"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_intersection(e):
    d = _base(e)
    d.update({
        "name": e["name"],
        "district": e["district"],
        "latitude": e["latitude"],
        "longitude": e["longitude"],
        "active_cycle_length_sec": e["active_cycle_length_sec"],
        "active_offset_sec": e["active_offset_sec"],
        "active_plan_revision": e["active_plan_revision"],
        "operational_posture": intersection_posture(e["id"]),
    })
    return d


def ser_pole(e):
    committed = pole_committed_load(e["id"])
    d = _base(e)
    d.update({
        "intersection_id": e["intersection_id"],
        "label": e["label"],
        "latitude": e["latitude"],
        "longitude": e["longitude"],
        "load_capacity_units": e["load_capacity_units"],
        "committed_load_units": committed,
        "available_load_units": e["load_capacity_units"] - committed,
        "status": e["status"],
    })
    return d


def ser_device(e):
    d = _base(e)
    d.update({
        "intersection_id": e["intersection_id"],
        "pole_id": e["pole_id"],
        "device_type": e["device_type"],
        "criticality": e["criticality"],
        "model": e["model"],
        "installed_at": fmt_dt(e["installed_at"]),
        "replacement_cost": e["replacement_cost"],
        "warranty_provider": e["warranty_provider"],
        "last_pm_at": fmt_dt(e["last_pm_at"]),
        "status": e["status"],
    })
    return d


def ser_attachment(e):
    d = _base(e)
    d.update({
        "pole_id": e["pole_id"],
        "attacher_name": e["attacher_name"],
        "mount_zone": e["mount_zone"],
        "load_units": e["load_units"],
        "effective_from": fmt_dt(e["effective_from"]),
        "effective_to": fmt_dt(e["effective_to"]),
        "status": e["status"],
    })
    return d


def ser_crew(e):
    committed = crew_committed_hours(e["id"])
    d = _base(e)
    d.update({
        "name": e["name"],
        "specialty": e["specialty"],
        "labor_capacity_hours": e["labor_capacity_hours"],
        "committed_labor_hours": committed,
        "available_labor_hours": e["labor_capacity_hours"] - committed,
    })
    return d


def ser_ticket(e):
    d = _base(e)
    d.update({
        "device_id": e["device_id"],
        "source": e["source"],
        "reported_severity": e["reported_severity"],
        "hazard_flag": e["hazard_flag"],
        "struck_pole": e["struck_pole"],
        "description": e["description"],
        "priority_score": e["priority_score"],
        "priority_band": e["priority_band"],
        "triaged_at": fmt_dt(e["triaged_at"]),
        "response_due": fmt_dt(e["response_due"]),
        "resolution_due": fmt_dt(e["resolution_due"]),
        "sla_response_status": ticket_sla_status(e),
        "resolved_at": fmt_dt(e["resolved_at"]),
        "reopen_count": e["reopen_count"],
        "status": e["status"],
    })
    return d


def ser_work_order(e):
    d = _base(e)
    d.update({
        "ticket_id": e["ticket_id"],
        "device_id": e["device_id"],
        "crew_id": e["crew_id"],
        "locate_request_id": e["locate_request_id"],
        "work_type": e["work_type"],
        "estimated_labor_hours": e["estimated_labor_hours"],
        "estimated_parts": e["estimated_parts"],
        "actual_labor_hours": e["actual_labor_hours"],
        "actual_parts": e["actual_parts"],
        "scheduled_start": fmt_dt(e["scheduled_start"]),
        "scheduled_end": fmt_dt(e["scheduled_end"]),
        "provisional_cost": e["provisional_cost"],
        "final_cost": e["final_cost"],
        "status": e["status"],
    })
    return d


def ser_tcr(e):
    d = _base(e)
    d.update({
        "intersection_id": e["intersection_id"],
        "proposed_cycle_length_sec": e["proposed_cycle_length_sec"],
        "proposed_offset_sec": e["proposed_offset_sec"],
        "rationale": e["rationale"],
        "revision_count": e["revision_count"],
        "decided_at": fmt_dt(e["decided_at"]),
        "status": e["status"],
    })
    return d


def ser_locate(e):
    d = _base(e)
    d.update({
        "intersection_id": e["intersection_id"],
        "requested_by": e["requested_by"],
        "valid_days": e["valid_days"],
        "valid_until": fmt_dt(e["valid_until"]),
        "status": e["status"],
    })
    return d


def ser_warranty(e):
    d = _base(e)
    d.update({
        "device_id": e["device_id"],
        "work_order_id": e["work_order_id"],
        "defect_description": e["defect_description"],
        "coverage_variant": e["coverage_variant"],
        "payout_amount": e["payout_amount"],
        "status": e["status"],
    })
    return d


# ---------------------------------------------------------------------------
# Filtering helper for list endpoints
# ---------------------------------------------------------------------------
def filter_by(items, fields):
    result = list(items)
    for qparam, entity_field in fields:
        val = request.args.get(qparam)
        if val is not None:
            result = [e for e in result if e.get(entity_field) == val]
    return result


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require(role, {"Admin"})
    b = body()
    dt = req_datetime(b, "to_iso8601")
    store.clock = dt
    return ok({"current_utc": fmt_dt(dt)})


# ===========================================================================
# Intersections
# ===========================================================================
@app.route("/intersections", methods=["POST"])
def create_intersection():
    _uid, role = authenticate()
    require(role, {"Admin"})
    b = body()
    name = req_str(b, "name")
    district = req_str(b, "district")
    latitude = req_number(b, "latitude")
    longitude = req_number(b, "longitude")
    e = store.new_entity()
    e.update({
        "name": name, "district": district,
        "latitude": latitude, "longitude": longitude,
        "active_cycle_length_sec": 0, "active_offset_sec": 0,
        "active_plan_revision": 0,
    })
    store.intersections[e["id"]] = e
    return ok(ser_intersection(e), code=201)


@app.route("/intersections/<rid>", methods=["GET"])
def get_intersection(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.intersections, rid, "ERR_INTERSECTION_NOT_FOUND")
    return ok(ser_intersection(e))


@app.route("/intersections/<rid>/summary", methods=["GET"])
def intersection_summary(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.intersections, rid, "ERR_INTERSECTION_NOT_FOUND")
    devs = [d for d in store.devices.values() if d["intersection_id"] == rid]
    dev_ids = {d["id"] for d in devs}
    out_of_service = sum(1 for d in devs if d["status"] == "OUT_OF_SERVICE")
    open_tickets = sum(
        1 for t in store.tickets.values()
        if t["device_id"] in dev_ids and t["status"] in ("OPEN", "TRIAGED", "IN_PROGRESS")
    )
    return ok({
        "intersection_id": rid,
        "operational_posture": intersection_posture(rid),
        "device_count": len(devs),
        "out_of_service_count": out_of_service,
        "open_ticket_count": open_tickets,
    })


# ===========================================================================
# Poles
# ===========================================================================
@app.route("/poles", methods=["POST"])
def create_pole():
    _uid, role = authenticate()
    require(role, {"Admin"})
    b = body()
    resolve(b.get("intersection_id"), store.intersections, "ERR_INTERSECTION_NOT_FOUND")
    label = req_str(b, "label")
    latitude = req_number(b, "latitude")
    longitude = req_number(b, "longitude")
    capacity = req_int(b, "load_capacity_units")
    intersection_id = b.get("intersection_id")
    if intersection_id is not None and not isinstance(intersection_id, str):
        verr("intersection_id must be a string")
    e = store.new_entity()
    e.update({
        "intersection_id": intersection_id,
        "label": label, "latitude": latitude, "longitude": longitude,
        "load_capacity_units": capacity,
        "status": "STANDING",
    })
    store.poles[e["id"]] = e
    return ok(ser_pole(e), code=201)


@app.route("/poles/<rid>", methods=["GET"])
def get_pole(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.poles, rid, "ERR_POLE_NOT_FOUND")
    return ok(ser_pole(e))


@app.route("/poles", methods=["GET"])
def list_poles():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.poles.values(), [("intersection_id", "intersection_id"), ("status", "status")])
    data, pag = paginate(items, ser_pole)
    return ok(data, response_type="array", pagination=pag)


# ===========================================================================
# Devices
# ===========================================================================
@app.route("/devices", methods=["POST"])
def create_device():
    _uid, role = authenticate()
    require(role, {"Admin"})
    b = body()
    resolve(b.get("intersection_id"), store.intersections, "ERR_INTERSECTION_NOT_FOUND")
    resolve(b.get("pole_id"), store.poles, "ERR_POLE_NOT_FOUND")
    intersection_id = req_str(b, "intersection_id")
    device_type = req_enum(b, "device_type", DEVICE_TYPES)
    criticality = req_enum(b, "criticality", CRITICALITIES)
    model = req_str(b, "model")
    installed_at = req_datetime(b, "installed_at")
    replacement_cost = req_number(b, "replacement_cost")
    warranty_provider = req_str(b, "warranty_provider")
    pole_id = b.get("pole_id")
    if pole_id is not None and not isinstance(pole_id, str):
        verr("pole_id must be a string")
    e = store.new_entity()
    e.update({
        "intersection_id": intersection_id,
        "pole_id": pole_id,
        "device_type": device_type,
        "criticality": criticality,
        "model": model,
        "installed_at": installed_at,
        "replacement_cost": replacement_cost,
        "warranty_provider": warranty_provider,
        "last_pm_at": None,
        "status": "IN_SERVICE",
    })
    store.devices[e["id"]] = e
    return ok(ser_device(e), code=201)


@app.route("/devices/<rid>", methods=["GET"])
def get_device(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.devices, rid, "ERR_DEVICE_NOT_FOUND")
    return ok(ser_device(e))


@app.route("/devices", methods=["GET"])
def list_devices():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.devices.values(),
                      [("intersection_id", "intersection_id"), ("pole_id", "pole_id"), ("status", "status")])
    data, pag = paginate(items, ser_device)
    return ok(data, response_type="array", pagination=pag)


@app.route("/devices/<rid>/decommission", methods=["POST"])
def decommission_device(rid):
    _uid, role = authenticate()
    require(role, {"Admin"})
    e = get_or_404(store.devices, rid, "ERR_DEVICE_NOT_FOUND")
    if e["status"] not in ("IN_SERVICE", "OUT_OF_SERVICE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Device cannot be decommissioned from its current state")
    blocking = any(
        w["device_id"] == rid and w["status"] in ("DRAFT", "SCHEDULED", "DISPATCHED")
        for w in store.work_orders.values()
    )
    if blocking:
        raise ApiError("ERR_INVALID_STATE", 409, "Device has open work orders")
    e["status"] = "DECOMMISSIONED"
    store.touch(e)
    return ok(ser_device(e))


# ===========================================================================
# Crews
# ===========================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    _uid, role = authenticate()
    require(role, {"Admin"})
    b = body()
    name = req_str(b, "name")
    specialty = req_enum(b, "specialty", SPECIALTIES)
    capacity = req_number(b, "labor_capacity_hours")
    e = store.new_entity()
    e.update({"name": name, "specialty": specialty, "labor_capacity_hours": capacity})
    store.crews[e["id"]] = e
    return ok(ser_crew(e), code=201)


@app.route("/crews/<rid>", methods=["GET"])
def get_crew(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.crews, rid, "ERR_CREW_NOT_FOUND")
    return ok(ser_crew(e))


# ===========================================================================
# Pole Attachments
# ===========================================================================
@app.route("/pole-attachments", methods=["POST"])
def create_attachment():
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    b = body()
    pole = resolve(b.get("pole_id"), store.poles, "ERR_POLE_NOT_FOUND")
    pole_id = req_str(b, "pole_id")
    attacher = req_str(b, "attacher_name")
    mount_zone = req_enum(b, "mount_zone", MOUNT_ZONES)
    load_units = req_int(b, "load_units")
    effective_from = req_datetime(b, "effective_from")
    effective_to = req_datetime(b, "effective_to")
    expected_version = req_int(b, "expected_pole_version")
    # OCC check (priority 14)
    if pole is None:
        pole = store.poles[pole_id]
    if expected_version != pole["version"]:
        raise ApiError("ERR_STALE_POLE_VERSION", 412, "Pole version has advanced since last observed")
    e = store.new_entity()
    e.update({
        "pole_id": pole_id,
        "attacher_name": attacher,
        "mount_zone": mount_zone,
        "load_units": load_units,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "REQUESTED",
    })
    store.pole_attachments[e["id"]] = e
    # Creating the attachment advances the pole's version.
    store.touch(pole)
    return ok(ser_attachment(e), code=201)


@app.route("/pole-attachments/<rid>", methods=["GET"])
def get_attachment(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.pole_attachments, rid, "ERR_ATTACHMENT_NOT_FOUND")
    return ok(ser_attachment(e))


@app.route("/pole-attachments", methods=["GET"])
def list_attachments():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.pole_attachments.values(), [("pole_id", "pole_id"), ("status", "status")])
    data, pag = paginate(items, ser_attachment)
    return ok(data, response_type="array", pagination=pag)


def _windows_conflict(a_from, a_to, b_from, b_to):
    buf = timedelta(days=ATTACHMENT_BUFFER_DAYS)
    # OK (no conflict) only if disjoint AND separated by at least the buffer.
    if b_from >= a_to + buf or a_from >= b_to + buf:
        return False
    return True


@app.route("/pole-attachments/<rid>/approve", methods=["POST"])
def approve_attachment(rid):
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    e = get_or_404(store.pole_attachments, rid, "ERR_ATTACHMENT_NOT_FOUND")
    if e["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Attachment is not in REQUESTED state")
    pole = store.poles[e["pole_id"]]
    # priority 7: pole must be STANDING
    if pole["status"] != "STANDING":
        raise ApiError("ERR_POLE_NOT_STANDING", 409, "Pole is not STANDING")
    # priority 8: window conflict against other APPROVED attachments same (pole, zone)
    for other in store.pole_attachments.values():
        if (other["id"] != e["id"] and other["pole_id"] == e["pole_id"]
                and other["status"] == "APPROVED" and other["mount_zone"] == e["mount_zone"]):
            if _windows_conflict(e["effective_from"], e["effective_to"],
                                 other["effective_from"], other["effective_to"]):
                raise ApiError("ERR_ATTACHMENT_WINDOW_CONFLICT", 409, "Attachment window conflict")
    # priority 9: load capacity
    committed = pole_committed_load(pole["id"])
    if committed + e["load_units"] > pole["load_capacity_units"]:
        raise ApiError("ERR_POLE_LOAD_EXCEEDED", 409, "Pole load capacity exceeded")
    e["status"] = "APPROVED"
    store.touch(e)
    store.touch(pole)  # committed_load_units recomputes; pole version += 1
    return ok(ser_attachment(e))


@app.route("/pole-attachments/<rid>/deny", methods=["POST"])
def deny_attachment(rid):
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    e = get_or_404(store.pole_attachments, rid, "ERR_ATTACHMENT_NOT_FOUND")
    if e["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Attachment is not in REQUESTED state")
    e["status"] = "DENIED"
    store.touch(e)
    return ok(ser_attachment(e))


@app.route("/pole-attachments/<rid>/revoke", methods=["POST"])
def revoke_attachment(rid):
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    e = get_or_404(store.pole_attachments, rid, "ERR_ATTACHMENT_NOT_FOUND")
    if e["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Attachment is not in APPROVED state")
    pole = store.poles[e["pole_id"]]
    e["status"] = "REVOKED"
    store.touch(e)
    store.touch(pole)  # compensating release; pole version += 1
    return ok(ser_attachment(e))


# ===========================================================================
# Tickets
# ===========================================================================
@app.route("/tickets", methods=["POST"])
def create_ticket():
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    b = body()
    resolve(b.get("device_id"), store.devices, "ERR_DEVICE_NOT_FOUND")
    device_id = req_str(b, "device_id")
    source = req_enum(b, "source", TICKET_SOURCES)
    severity = req_int(b, "reported_severity")
    if severity < 1 or severity > 5:
        verr("reported_severity must be between 1 and 5")
    description = req_str(b, "description")
    hazard_flag = opt_bool(b, "hazard_flag", False)
    struck_pole = opt_bool(b, "struck_pole", False)
    e = store.new_entity()
    e.update({
        "device_id": device_id, "source": source,
        "reported_severity": severity, "hazard_flag": hazard_flag,
        "struck_pole": struck_pole, "description": description,
        "priority_score": None, "priority_band": None,
        "triaged_at": None, "response_due": None, "resolution_due": None,
        "resolved_at": None, "reopen_count": 0,
        "status": "OPEN",
    })
    store.tickets[e["id"]] = e
    return ok(ser_ticket(e), code=201)


@app.route("/tickets/<rid>", methods=["GET"])
def get_ticket(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.tickets, rid, "ERR_TICKET_NOT_FOUND")
    return ok(ser_ticket(e))


@app.route("/tickets", methods=["GET"])
def list_tickets():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.tickets.values(), [("device_id", "device_id"), ("status", "status")])
    data, pag = paginate(items, ser_ticket)
    return ok(data, response_type="array", pagination=pag)


@app.route("/tickets/<rid>/triage", methods=["POST"])
def triage_ticket(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    e = get_or_404(store.tickets, rid, "ERR_TICKET_NOT_FOUND")
    if e["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not OPEN")
    device = store.devices.get(e["device_id"])
    if device is None or device["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_INVALID_STATE", 409, "Device is missing or decommissioned")
    # Calculations
    score, band = compute_priority(e, device)
    now = clock()
    e["priority_score"] = score
    e["priority_band"] = band
    e["triaged_at"] = now
    e["response_due"] = now + timedelta(minutes=RESPONSE_SLA[band])
    e["resolution_due"] = now + timedelta(minutes=RESOLUTION_SLA[band])
    e["status"] = "TRIAGED"
    store.touch(e)
    # Source-specific cascade
    if e["source"] != "KNOCKDOWN":
        if device["status"] == "IN_SERVICE":
            device["status"] = "OUT_OF_SERVICE"
            store.touch(device)
    else:
        device["status"] = "KNOCKED_DOWN"
        store.touch(device)
        if e["struck_pole"] and device.get("pole_id"):
            pole = store.poles.get(device["pole_id"])
            if pole is not None and pole["status"] != "DOWN":
                pole["status"] = "DOWN"
                store.touch(pole)
        # Suspend timing change requests of the intersection in SUBMITTED/UNDER_REVIEW
        for tcr in store.tcrs.values():
            if tcr["intersection_id"] == device["intersection_id"] and tcr["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                tcr["status"] = "SUSPENDED"
                store.touch(tcr)
        # Auto-create emergency work order (DRAFT)
        wo = store.new_entity()
        wo.update({
            "ticket_id": e["id"], "device_id": device["id"], "crew_id": None,
            "locate_request_id": None, "work_type": "EMERGENCY",
            "estimated_labor_hours": 0, "estimated_parts": [],
            "actual_labor_hours": None, "actual_parts": [],
            "scheduled_start": None, "scheduled_end": None,
            "provisional_cost": compute_cost(0, []), "final_cost": None,
            "status": "DRAFT",
        })
        store.work_orders[wo["id"]] = wo
    return ok(ser_ticket(e))


@app.route("/tickets/<rid>/resolve", methods=["POST"])
def resolve_ticket(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    e = get_or_404(store.tickets, rid, "ERR_TICKET_NOT_FOUND")
    if e["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not IN_PROGRESS")
    has_completed = any(
        w["ticket_id"] == rid and w["status"] == "COMPLETED" for w in store.work_orders.values()
    )
    if not has_completed:
        raise ApiError("ERR_INVALID_STATE", 409, "No completed work order for this ticket")
    e["resolved_at"] = clock()
    e["status"] = "RESOLVED"
    store.touch(e)
    return ok(ser_ticket(e))


@app.route("/tickets/<rid>/reopen", methods=["POST"])
def reopen_ticket(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    e = get_or_404(store.tickets, rid, "ERR_TICKET_NOT_FOUND")
    if e["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not RESOLVED")
    resolved = e["resolved_at"]
    if resolved is not None and (clock() - resolved) > timedelta(hours=REOPEN_WINDOW_HOURS):
        raise ApiError("ERR_REOPEN_WINDOW_EXPIRED", 409, "Reopen window expired")
    e["reopen_count"] += 1
    e["resolved_at"] = None
    e["status"] = "TRIAGED"
    store.touch(e)
    return ok(ser_ticket(e))


@app.route("/tickets/<rid>/close", methods=["POST"])
def close_ticket(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    e = get_or_404(store.tickets, rid, "ERR_TICKET_NOT_FOUND")
    if e["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not RESOLVED")
    open_work = any(
        w["ticket_id"] == rid and w["status"] in ("DRAFT", "SCHEDULED", "DISPATCHED")
        for w in store.work_orders.values()
    )
    if open_work:
        raise ApiError("ERR_TICKET_HAS_OPEN_WORK", 409, "Ticket has open work orders")
    e["status"] = "CLOSED"
    store.touch(e)
    return ok(ser_ticket(e))


# ===========================================================================
# Work Orders
# ===========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    b = body()
    resolve(b.get("device_id"), store.devices, "ERR_DEVICE_NOT_FOUND")
    resolve(b.get("ticket_id"), store.tickets, "ERR_TICKET_NOT_FOUND")
    resolve(b.get("locate_request_id"), store.locate_requests, "ERR_LOCATE_NOT_FOUND")
    device_id = req_str(b, "device_id")
    work_type = req_enum(b, "work_type", WORK_TYPES)
    est_hours = req_number(b, "estimated_labor_hours")
    est_parts = parts_list(b, "estimated_parts")
    ticket_id = b.get("ticket_id")
    if ticket_id is not None and not isinstance(ticket_id, str):
        verr("ticket_id must be a string")
    locate_id = b.get("locate_request_id")
    if locate_id is not None and not isinstance(locate_id, str):
        verr("locate_request_id must be a string")
    e = store.new_entity()
    e.update({
        "ticket_id": ticket_id, "device_id": device_id, "crew_id": None,
        "locate_request_id": locate_id, "work_type": work_type,
        "estimated_labor_hours": est_hours, "estimated_parts": est_parts,
        "actual_labor_hours": None, "actual_parts": [],
        "scheduled_start": None, "scheduled_end": None,
        "provisional_cost": compute_cost(est_hours, est_parts), "final_cost": None,
        "status": "DRAFT",
    })
    store.work_orders[e["id"]] = e
    return ok(ser_work_order(e), code=201)


@app.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.work_orders, rid, "ERR_WORK_ORDER_NOT_FOUND")
    return ok(ser_work_order(e))


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.work_orders.values(), [
        ("ticket_id", "ticket_id"), ("device_id", "device_id"),
        ("crew_id", "crew_id"), ("locate_request_id", "locate_request_id"),
        ("status", "status"),
    ])
    data, pag = paginate(items, ser_work_order)
    return ok(data, response_type="array", pagination=pag)


@app.route("/work-orders/<rid>/schedule", methods=["POST"])
def schedule_work_order(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    e = get_or_404(store.work_orders, rid, "ERR_WORK_ORDER_NOT_FOUND")
    b = body()
    crew = resolve(b.get("crew_id"), store.crews, "ERR_CREW_NOT_FOUND")
    crew_id = req_str(b, "crew_id")
    scheduled_start = req_datetime(b, "scheduled_start")
    scheduled_end = req_datetime(b, "scheduled_end")
    if crew is None:
        crew = store.crews[crew_id]
    # priority 5: state
    if e["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not DRAFT")
    # priority 6: excavation locate safety
    if e["work_type"] == "EXCAVATION":
        if not e["locate_request_id"]:
            raise ApiError("ERR_LOCATE_REQUIRED", 409, "Excavation requires a locate request")
        locate = store.locate_requests.get(e["locate_request_id"])
        if locate is None or locate["status"] != "CLEARED":
            raise ApiError("ERR_LOCATE_NOT_CLEARED", 409, "Locate request is not CLEARED")
        if locate["valid_until"] is not None and clock() > locate["valid_until"]:
            raise ApiError("ERR_LOCATE_EXPIRED", 409, "Locate request has expired")
    # priority 8: crew schedule conflict
    for other in store.work_orders.values():
        if (other["id"] != e["id"] and other.get("crew_id") == crew_id
                and other["status"] in ("SCHEDULED", "DISPATCHED")):
            os_, oe_ = other["scheduled_start"], other["scheduled_end"]
            if os_ is not None and oe_ is not None:
                if scheduled_start < oe_ and os_ < scheduled_end:
                    raise ApiError("ERR_CREW_SCHEDULE_CONFLICT", 409, "Crew schedule conflict")
    # priority 10: crew capacity
    available = crew["labor_capacity_hours"] - crew_committed_hours(crew_id)
    if e["estimated_labor_hours"] > available:
        raise ApiError("ERR_CREW_CAPACITY_EXCEEDED", 409, "Crew capacity exceeded")
    e["crew_id"] = crew_id
    e["scheduled_start"] = scheduled_start
    e["scheduled_end"] = scheduled_end
    e["status"] = "SCHEDULED"
    store.touch(e)
    return ok(ser_work_order(e))


@app.route("/work-orders/<rid>/dispatch", methods=["POST"])
def dispatch_work_order(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    e = get_or_404(store.work_orders, rid, "ERR_WORK_ORDER_NOT_FOUND")
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not SCHEDULED")
    device = store.devices.get(e["device_id"])
    if device is not None and device["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_DEVICE_DECOMMISSIONED", 409, "Device is decommissioned")
    e["status"] = "DISPATCHED"
    store.touch(e)
    if device is not None and device["status"] != "KNOCKED_DOWN":
        device["status"] = "UNDER_MAINTENANCE"
        store.touch(device)
    if e["ticket_id"]:
        ticket = store.tickets.get(e["ticket_id"])
        if ticket is not None and ticket["status"] == "TRIAGED":
            ticket["status"] = "IN_PROGRESS"
            store.touch(ticket)
    return ok(ser_work_order(e))


@app.route("/work-orders/<rid>/complete", methods=["POST"])
def complete_work_order(rid):
    uid, role = authenticate()
    require(role, {"FieldTech"})
    e = get_or_404(store.work_orders, rid, "ERR_WORK_ORDER_NOT_FOUND")
    # ownership: FieldTech's X-User-ID must equal the WO crew_id
    if e.get("crew_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "FieldTech does not own this work order")
    if e["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not DISPATCHED")
    b = body()
    actual_hours = req_number(b, "actual_labor_hours")
    actual_parts = parts_list(b, "actual_parts")
    e["actual_labor_hours"] = actual_hours
    e["actual_parts"] = actual_parts
    e["final_cost"] = compute_cost(actual_hours, actual_parts)
    e["status"] = "COMPLETED"  # releases crew commitment (computed ledger)
    store.touch(e)
    device = store.devices.get(e["device_id"])
    if device is not None:
        was_knocked = device["status"] == "KNOCKED_DOWN"
        device["status"] = "IN_SERVICE"
        if e["work_type"] in ("PM_LAMP", "LED_REPLACEMENT"):
            device["last_pm_at"] = clock()
        store.touch(device)
        if was_knocked and device.get("pole_id"):
            pole = store.poles.get(device["pole_id"])
            if pole is not None and pole["status"] == "DOWN":
                pole["status"] = "STANDING"
                store.touch(pole)
    return ok(ser_work_order(e))


@app.route("/work-orders/<rid>/cancel", methods=["POST"])
def cancel_work_order(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher"})
    e = get_or_404(store.work_orders, rid, "ERR_WORK_ORDER_NOT_FOUND")
    if e["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Work order cannot be cancelled from its current state")
    e["status"] = "CANCELLED"  # compensating release is implicit via computed ledger
    store.touch(e)
    return ok(ser_work_order(e))


# ===========================================================================
# Timing Plan Change Requests
# ===========================================================================
@app.route("/timing-change-requests", methods=["POST"])
def create_tcr():
    _uid, role = authenticate()
    require(role, {"Dispatcher", "TrafficEngineer"})
    b = body()
    resolve(b.get("intersection_id"), store.intersections, "ERR_INTERSECTION_NOT_FOUND")
    intersection_id = req_str(b, "intersection_id")
    cycle = req_int(b, "proposed_cycle_length_sec")
    offset = req_int(b, "proposed_offset_sec")
    rationale = req_str(b, "rationale")
    e = store.new_entity()
    e.update({
        "intersection_id": intersection_id,
        "proposed_cycle_length_sec": cycle,
        "proposed_offset_sec": offset,
        "rationale": rationale,
        "revision_count": 0,
        "decided_at": None,
        "status": "SUBMITTED",
    })
    store.tcrs[e["id"]] = e
    return ok(ser_tcr(e), code=201)


@app.route("/timing-change-requests/<rid>", methods=["GET"])
def get_tcr(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.tcrs, rid, "ERR_TCR_NOT_FOUND")
    return ok(ser_tcr(e))


@app.route("/timing-change-requests", methods=["GET"])
def list_tcrs():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.tcrs.values(), [("intersection_id", "intersection_id"), ("status", "status")])
    data, pag = paginate(items, ser_tcr)
    return ok(data, response_type="array", pagination=pag)


@app.route("/timing-change-requests/<rid>/start-review", methods=["POST"])
def start_review_tcr(rid):
    _uid, role = authenticate()
    require(role, {"TrafficEngineer"})
    e = get_or_404(store.tcrs, rid, "ERR_TCR_NOT_FOUND")
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not SUBMITTED")
    if intersection_posture(e["intersection_id"]) == "EMERGENCY":
        raise ApiError("ERR_INTERSECTION_EMERGENCY", 409, "Intersection is in EMERGENCY posture")
    e["status"] = "UNDER_REVIEW"
    store.touch(e)
    return ok(ser_tcr(e))


@app.route("/timing-change-requests/<rid>/approve", methods=["POST"])
def approve_tcr(rid):
    _uid, role = authenticate()
    require(role, {"TrafficEngineer"})
    e = get_or_404(store.tcrs, rid, "ERR_TCR_NOT_FOUND")
    if e["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not UNDER_REVIEW")
    if intersection_posture(e["intersection_id"]) == "EMERGENCY":
        raise ApiError("ERR_INTERSECTION_EMERGENCY", 409, "Intersection is in EMERGENCY posture")
    intersection = store.intersections[e["intersection_id"]]
    intersection["active_cycle_length_sec"] = e["proposed_cycle_length_sec"]
    intersection["active_offset_sec"] = e["proposed_offset_sec"]
    intersection["active_plan_revision"] += 1
    store.touch(intersection)  # version += 1
    e["decided_at"] = clock()
    e["status"] = "APPROVED"
    store.touch(e)
    return ok(ser_tcr(e))


@app.route("/timing-change-requests/<rid>/reject", methods=["POST"])
def reject_tcr(rid):
    _uid, role = authenticate()
    require(role, {"TrafficEngineer"})
    e = get_or_404(store.tcrs, rid, "ERR_TCR_NOT_FOUND")
    if e["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not UNDER_REVIEW")
    e["decided_at"] = clock()
    e["status"] = "REJECTED"
    store.touch(e)
    return ok(ser_tcr(e))


@app.route("/timing-change-requests/<rid>/request-changes", methods=["POST"])
def request_changes_tcr(rid):
    _uid, role = authenticate()
    require(role, {"TrafficEngineer"})
    e = get_or_404(store.tcrs, rid, "ERR_TCR_NOT_FOUND")
    if e["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not UNDER_REVIEW")
    e["status"] = "CHANGES_REQUESTED"
    store.touch(e)
    return ok(ser_tcr(e))


@app.route("/timing-change-requests/<rid>/resubmit", methods=["POST"])
def resubmit_tcr(rid):
    _uid, role = authenticate()
    require(role, {"Dispatcher", "TrafficEngineer"})
    e = get_or_404(store.tcrs, rid, "ERR_TCR_NOT_FOUND")
    if e["status"] not in ("CHANGES_REQUESTED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Request cannot be resubmitted from its current state")
    if e["status"] == "SUSPENDED" and intersection_posture(e["intersection_id"]) == "EMERGENCY":
        raise ApiError("ERR_INTERSECTION_EMERGENCY", 409, "Intersection is in EMERGENCY posture")
    b = body()
    if "proposed_cycle_length_sec" in b and b["proposed_cycle_length_sec"] is not None:
        e["proposed_cycle_length_sec"] = req_int(b, "proposed_cycle_length_sec")
    if "proposed_offset_sec" in b and b["proposed_offset_sec"] is not None:
        e["proposed_offset_sec"] = req_int(b, "proposed_offset_sec")
    if "rationale" in b and b["rationale"] is not None:
        e["rationale"] = req_str(b, "rationale")
    e["revision_count"] += 1
    e["status"] = "SUBMITTED"
    store.touch(e)
    return ok(ser_tcr(e))


# ===========================================================================
# Locate Requests
# ===========================================================================
@app.route("/locate-requests", methods=["POST"])
def create_locate():
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    b = body()
    resolve(b.get("intersection_id"), store.intersections, "ERR_INTERSECTION_NOT_FOUND")
    intersection_id = req_str(b, "intersection_id")
    requested_by = req_str(b, "requested_by")
    if "valid_days" in b and b["valid_days"] is not None:
        valid_days = req_int(b, "valid_days")
    else:
        valid_days = 21
    e = store.new_entity()
    e.update({
        "intersection_id": intersection_id,
        "requested_by": requested_by,
        "valid_days": valid_days,
        "valid_until": clock() + timedelta(days=valid_days),
        "status": "OPEN",
    })
    store.locate_requests[e["id"]] = e
    return ok(ser_locate(e), code=201)


@app.route("/locate-requests/<rid>", methods=["GET"])
def get_locate(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.locate_requests, rid, "ERR_LOCATE_NOT_FOUND")
    return ok(ser_locate(e))


@app.route("/locate-requests", methods=["GET"])
def list_locates():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.locate_requests.values(), [("intersection_id", "intersection_id"), ("status", "status")])
    data, pag = paginate(items, ser_locate)
    return ok(data, response_type="array", pagination=pag)


@app.route("/locate-requests/<rid>/mark", methods=["POST"])
def mark_locate(rid):
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    e = get_or_404(store.locate_requests, rid, "ERR_LOCATE_NOT_FOUND")
    if e["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Locate request is not OPEN")
    e["status"] = "MARKED"
    store.touch(e)
    return ok(ser_locate(e))


@app.route("/locate-requests/<rid>/clear", methods=["POST"])
def clear_locate(rid):
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    e = get_or_404(store.locate_requests, rid, "ERR_LOCATE_NOT_FOUND")
    if e["status"] != "MARKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Locate request is not MARKED")
    e["status"] = "CLEARED"
    store.touch(e)
    return ok(ser_locate(e))


# ===========================================================================
# Warranty Claims
# ===========================================================================
@app.route("/warranty-claims", methods=["POST"])
def create_warranty():
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    b = body()
    device = resolve(b.get("device_id"), store.devices, "ERR_DEVICE_NOT_FOUND")
    resolve(b.get("work_order_id"), store.work_orders, "ERR_WORK_ORDER_NOT_FOUND")
    device_id = req_str(b, "device_id")
    defect = req_str(b, "defect_description")
    work_order_id = b.get("work_order_id")
    if work_order_id is not None and not isinstance(work_order_id, str):
        verr("work_order_id must be a string")
    if device is None:
        device = store.devices[device_id]
    # priority 13: warranty age
    age = whole_calendar_months(device["installed_at"], clock())
    if age > WARRANTY_TERM_MONTHS:
        raise ApiError("ERR_WARRANTY_EXPIRED", 409, "Device is past its warranty term")
    rc = Decimal(str(device["replacement_cost"]))
    if age <= FULL_COVERAGE_MONTHS:
        coverage = "FULL"
        payout = money(rc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        coverage = "PRORATED"
        remaining = Decimal(WARRANTY_TERM_MONTHS - age)
        payout = money((rc * remaining / Decimal(WARRANTY_TERM_MONTHS)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    e = store.new_entity()
    e.update({
        "device_id": device_id, "work_order_id": work_order_id,
        "defect_description": defect,
        "coverage_variant": coverage, "payout_amount": payout,
        "status": "SUBMITTED",
    })
    store.warranty_claims[e["id"]] = e
    return ok(ser_warranty(e), code=201)


@app.route("/warranty-claims/<rid>", methods=["GET"])
def get_warranty(rid):
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    e = get_or_404(store.warranty_claims, rid, "ERR_WARRANTY_NOT_FOUND")
    return ok(ser_warranty(e))


@app.route("/warranty-claims", methods=["GET"])
def list_warranties():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    items = filter_by(store.warranty_claims.values(), [("device_id", "device_id"), ("work_order_id", "work_order_id")])
    data, pag = paginate(items, ser_warranty)
    return ok(data, response_type="array", pagination=pag)


@app.route("/warranty-claims/<rid>/approve", methods=["POST"])
def approve_warranty(rid):
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    e = get_or_404(store.warranty_claims, rid, "ERR_WARRANTY_NOT_FOUND")
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED")
    e["status"] = "APPROVED"
    store.touch(e)
    return ok(ser_warranty(e))


@app.route("/warranty-claims/<rid>/deny", methods=["POST"])
def deny_warranty(rid):
    _uid, role = authenticate()
    require(role, {"UtilityCoordinator"})
    e = get_or_404(store.warranty_claims, rid, "ERR_WARRANTY_NOT_FOUND")
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED")
    e["status"] = "DENIED"
    store.touch(e)
    return ok(ser_warranty(e))


# ===========================================================================
# Reports
# ===========================================================================
@app.route("/reports/device-availability", methods=["GET"])
def report_device_availability():
    _uid, role = authenticate()
    require(role, ALL_ROLES)
    intersection_id = request.args.get("intersection_id")
    devs = [
        d for d in store.devices.values()
        if d["status"] != "DECOMMISSIONED"
        and (intersection_id is None or d["intersection_id"] == intersection_id)
    ]
    total = len(devs)
    in_service = sum(1 for d in devs if d["status"] == "IN_SERVICE")
    out_of_service = sum(1 for d in devs if d["status"] == "OUT_OF_SERVICE")
    knocked_down = sum(1 for d in devs if d["status"] == "KNOCKED_DOWN")
    if total == 0:
        availability = 0.0
    else:
        availability = money((Decimal(in_service) / Decimal(total) * Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    return ok({
        "total_devices": total,
        "in_service": in_service,
        "out_of_service": out_of_service,
        "knocked_down": knocked_down,
        "availability_pct": availability,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
