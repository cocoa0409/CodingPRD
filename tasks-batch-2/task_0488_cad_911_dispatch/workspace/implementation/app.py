"""CAD / NG911 Computer-Aided Dispatch API (PRD task 0488).

Entry point: registers all routes, error handling, and wires the in-memory
store. No entities are seeded at startup — the store is empty on every boot.
"""
import os

from flask import Flask, request

from clock import clock, DEFAULT_CLOCK
from db import db, stamp_create, touch, iso_ts
from errors import ApiError, err
import errors as E
import constants as C
import calc
import serializers as S
import validate as V
from auth import authenticate, require_role
from response import success, list_response, error_response
from pagination import paginate, sort_by_created

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response(E.ERR_NOT_FOUND, 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response(E.ERR_NOT_FOUND, 404, "Method not allowed.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response(E.ERR_INVALID_REQUEST, 422, f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Lookup helpers (path existence -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_or_404(store, _id):
    ent = store.get(_id)
    if ent is None:
        raise err(E.ERR_NOT_FOUND, "Resource not found.")
    return ent


# ===========================================================================
# Test-driving logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"SystemClock"})
    body = V.get_body()
    to_iso = V.require(body, "to_iso8601")
    dt = calc.parse_iso(to_iso) if isinstance(to_iso, str) else None
    if dt is None:
        raise err(E.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant.")
    clock.set(dt)
    return success({"current_utc": iso_ts(clock.now())}, status=200)


# ===========================================================================
# Agencies
# ===========================================================================
@app.route("/agencies", methods=["POST"])
def create_agency():
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    body = V.get_body()
    name = V.require_string(body, "name")
    discipline = V.require_enum(body, "discipline", C.DISCIPLINES)
    sla = V.require_int(body, "response_sla_seconds", lo=1)
    agency = {
        "name": name,
        "discipline": discipline,
        "response_sla_seconds": sla,
        "status": "ONLINE",
    }
    stamp_create(agency)
    db.agencies[agency["id"]] = agency
    return success(S.agency(agency), status=201)


@app.route("/agencies/<aid>", methods=["GET"])
def get_agency(aid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    return success(S.agency(get_or_404(db.agencies, aid)), status=200)


@app.route("/agencies", methods=["GET"])
def list_agencies():
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    items = list(db.agencies.values())
    disc = request.args.get("discipline")
    if disc is not None:
        items = [a for a in items if a["discipline"] == disc]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.agency(a) for a in page], limit, offset, total)


@app.route("/agencies/<aid>/status", methods=["PATCH"])
def patch_agency_status(aid):
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    agency = get_or_404(db.agencies, aid)
    body = V.get_body()
    new_status = V.require_enum(body, "status", C.AGENCY_STATUSES)
    cur = agency["status"]
    allowed = {
        ("ONLINE", "MUTUAL_AID_ONLY"),
        ("MUTUAL_AID_ONLY", "OFFLINE"),
        ("MUTUAL_AID_ONLY", "ONLINE"),
    }
    if (cur, new_status) not in allowed:
        raise err(E.ERR_INVALID_STATE, f"Cannot move agency from {cur} to {new_status}.")
    agency["status"] = new_status
    touch(agency)
    return success(S.agency(agency), status=200)


# ===========================================================================
# Stations
# ===========================================================================
@app.route("/stations", methods=["POST"])
def create_station():
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    body = V.get_body()
    # FK existence (priority 4) checked before body well-formedness (priority 5)
    agency_id = body.get("agency_id")
    if agency_id is not None and agency_id not in db.agencies:
        raise err(E.ERR_REFERENCE_NOT_FOUND, "agency_id does not reference an existing agency.")
    agency_id = V.require_string(body, "agency_id")
    if agency_id not in db.agencies:
        raise err(E.ERR_REFERENCE_NOT_FOUND, "agency_id does not reference an existing agency.")
    name = V.require_string(body, "name")
    grid_x = V.require_grid(body, "grid_x")
    grid_y = V.require_grid(body, "grid_y")
    station = {
        "agency_id": agency_id,
        "name": name,
        "grid_x": grid_x,
        "grid_y": grid_y,
    }
    stamp_create(station)
    db.stations[station["id"]] = station
    return success(S.station(station), status=201)


@app.route("/stations/<sid>", methods=["GET"])
def get_station(sid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    return success(S.station(get_or_404(db.stations, sid)), status=200)


@app.route("/stations", methods=["GET"])
def list_stations():
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    items = list(db.stations.values())
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        items = [s for s in items if s["agency_id"] == agency_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.station(s) for s in page], limit, offset, total)


# ===========================================================================
# Units
# ===========================================================================
@app.route("/units", methods=["POST"])
def create_unit():
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    body = V.get_body()
    # FK existence (priority 4): agency_id and station_id
    agency_id = body.get("agency_id")
    station_id = body.get("station_id")
    if agency_id is not None and agency_id not in db.agencies:
        raise err(E.ERR_REFERENCE_NOT_FOUND, "agency_id does not reference an existing agency.")
    if station_id is not None and station_id not in db.stations:
        raise err(E.ERR_REFERENCE_NOT_FOUND, "station_id does not reference an existing station.")
    agency_id = V.require_string(body, "agency_id")
    station_id = V.require_string(body, "station_id")
    if agency_id not in db.agencies:
        raise err(E.ERR_REFERENCE_NOT_FOUND, "agency_id does not reference an existing agency.")
    if station_id not in db.stations:
        raise err(E.ERR_REFERENCE_NOT_FOUND, "station_id does not reference an existing station.")
    call_sign = V.require_string(body, "call_sign")
    capability = V.require_enum(body, "capability", C.UNIT_CAPABILITIES)
    grid_x = V.optional_grid(body, "grid_x", default=None)
    grid_y = V.optional_grid(body, "grid_y", default=None)

    station = db.stations[station_id]
    # business: station must belong to same agency (priority 18)
    if station["agency_id"] != agency_id:
        raise err(E.ERR_STATION_AGENCY_MISMATCH, "Station does not belong to the unit's agency.")
    # business: call_sign unique within agency (priority 17)
    for u in db.units.values():
        if u["agency_id"] == agency_id and u["call_sign"] == call_sign:
            raise err(E.ERR_DUPLICATE_CALL_SIGN, "call_sign already used in this agency.")

    if grid_x is None:
        grid_x = station["grid_x"]
    if grid_y is None:
        grid_y = station["grid_y"]

    unit = {
        "agency_id": agency_id,
        "station_id": station_id,
        "call_sign": call_sign,
        "capability": capability,
        "status": "AVAILABLE",
        "grid_x": grid_x,
        "grid_y": grid_y,
        "active_incident_id": None,
    }
    stamp_create(unit)
    db.units[unit["id"]] = unit
    return success(S.unit(unit), status=201)


@app.route("/units/<uid>", methods=["GET"])
def get_unit(uid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    return success(S.unit(get_or_404(db.units, uid)), status=200)


@app.route("/units", methods=["GET"])
def list_units():
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    items = list(db.units.values())
    for field in ("agency_id", "station_id", "status", "active_incident_id"):
        val = request.args.get(field)
        if val is not None:
            items = [u for u in items if u.get(field) == val]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.unit(u) for u in page], limit, offset, total)


@app.route("/units/<uid>/status", methods=["PATCH"])
def patch_unit_status(uid):
    _, role = authenticate()
    require_role(role, {"FieldUnit", "Supervisor"})
    unit = get_or_404(db.units, uid)
    body = V.get_body()
    new_status = V.require_enum(body, "status", C.UNIT_STATUSES)
    cur = unit["status"]
    allowed = {("AVAILABLE", "OUT_OF_SERVICE"), ("OUT_OF_SERVICE", "AVAILABLE")}
    if (cur, new_status) not in allowed:
        raise err(E.ERR_INVALID_STATE, f"Manual readiness toggle cannot move unit from {cur} to {new_status}.")
    unit["status"] = new_status
    touch(unit)
    return success(S.unit(unit), status=200)


# ===========================================================================
# Premise alerts
# ===========================================================================
@app.route("/premise-alerts", methods=["POST"])
def create_premise_alert():
    _, role = authenticate()
    require_role(role, {"Supervisor", "Records"})
    body = V.get_body()
    grid_x = V.require_grid(body, "grid_x")
    grid_y = V.require_grid(body, "grid_y")
    hazard_class = V.require_enum(body, "hazard_class", C.HAZARD_CLASSES)
    floor = V.require_int(body, "min_priority_floor", lo=1, hi=5)
    alert = {
        "grid_x": grid_x,
        "grid_y": grid_y,
        "hazard_class": hazard_class,
        "min_priority_floor": floor,
        "active": True,
    }
    stamp_create(alert)
    db.premise_alerts[alert["id"]] = alert
    return success(S.premise_alert(alert), status=201)


@app.route("/premise-alerts/<pid>", methods=["GET"])
def get_premise_alert(pid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    return success(S.premise_alert(get_or_404(db.premise_alerts, pid)), status=200)


@app.route("/premise-alerts", methods=["GET"])
def list_premise_alerts():
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    items = list(db.premise_alerts.values())
    for field in ("grid_x", "grid_y"):
        val = request.args.get(field)
        if val is not None:
            try:
                ival = int(val)
            except ValueError:
                items = []
                break
            items = [a for a in items if a[field] == ival]
    active = request.args.get("active")
    if active is not None:
        want = active.lower() in ("true", "1")
        items = [a for a in items if a["active"] == want]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.premise_alert(a) for a in page], limit, offset, total)


@app.route("/premise-alerts/<pid>", methods=["PATCH"])
def patch_premise_alert(pid):
    _, role = authenticate()
    require_role(role, {"Supervisor", "Records"})
    alert = get_or_404(db.premise_alerts, pid)
    body = V.get_body()
    active = V.require_bool(body, "active")
    alert["active"] = active
    touch(alert)
    return success(S.premise_alert(alert), status=200)


# ===========================================================================
# Incidents — intake & lifecycle
# ===========================================================================
@app.route("/incidents", methods=["POST"])
def create_incident():
    _, role = authenticate()
    require_role(role, {"Calltaker", "Supervisor"})
    body = V.get_body()
    ani = V.require_ani(body, "ani")
    ali_grid_x = V.require_grid(body, "ali_grid_x")
    ali_grid_y = V.require_grid(body, "ali_grid_y")
    incident_type = V.require_enum(body, "incident_type", C.INCIDENT_TYPES)
    ali_confidence = V.optional_enum(body, "ali_confidence", C.ALI_CONFIDENCES, default="HIGH")

    now = clock.now()
    year = now.year
    incident_number = db.next_cfs_number(year)

    active_alerts = [a for a in db.premise_alerts.values() if a.get("active")]
    base, priority, premise_alert_id = calc.effective_priority_at_intake(
        incident_type, ali_grid_x, ali_grid_y, ali_confidence, active_alerts)

    incident = {
        "incident_number": incident_number,
        "ani": ani,
        "ali_grid_x": ali_grid_x,
        "ali_grid_y": ali_grid_y,
        "ali_confidence": ali_confidence,
        "incident_type": incident_type,
        "priority_level": priority,
        "base_priority_level": base,
        "required_disciplines": calc.required_disciplines_for(incident_type),
        "lifecycle_status": "PENDING",
        "premise_alert_id": premise_alert_id,
        "received_at": iso_ts(now),
        "first_dispatch_at": None,
        "first_onscene_at": None,
        "closed_at": None,
        "escalation_count": 0,
        "disposition_code": None,
        "response_time_seconds": None,
        "total_handle_seconds": None,
        "sla_breached": False,
    }
    stamp_create(incident)
    db.incidents[incident["id"]] = incident
    return success(S.incident(incident), status=201)


@app.route("/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    return success(S.incident(get_or_404(db.incidents, iid)), status=200)


@app.route("/incidents", methods=["GET"])
def list_incidents():
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    items = list(db.incidents.values())
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        items = [i for i in items if i["lifecycle_status"] == lifecycle]
    priority = request.args.get("priority_level")
    if priority is not None:
        try:
            pv = int(priority)
            items = [i for i in items if i["priority_level"] == pv]
        except ValueError:
            items = []
    palert = request.args.get("premise_alert_id")
    if palert is not None:
        items = [i for i in items if i.get("premise_alert_id") == palert]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.incident(i) for i in page], limit, offset, total)


# --- recommendation helpers ---
def _non_cancelled_assignments(incident_id):
    return [a for a in db.assignments.values()
            if a["incident_id"] == incident_id and a["status"] != "CANCELLED"]


def _covered_disciplines(incident_id):
    covered = set()
    for a in _non_cancelled_assignments(incident_id):
        u = db.units.get(a["unit_id"])
        if u:
            ag = db.agencies.get(u["agency_id"])
            if ag:
                covered.add(ag["discipline"])
    return covered


def _resolve_discipline(incident, requested):
    """Resolve the discipline to recommend for. If none requested, pick the next
    required discipline not yet covered by a non-cancelled assignment."""
    if requested is not None:
        return requested
    covered = _covered_disciplines(incident["id"])
    for d in incident["required_disciplines"]:
        if d not in covered:
            return d
    return None


def _candidate_pool(incident, discipline, mutual_aid):
    """Build the candidate pool for a discipline.

    mutual_aid False -> agency status must be ONLINE.
    mutual_aid True  -> agency status in {ONLINE, MUTUAL_AID_ONLY}.
    Excludes units already on this incident via a non-cancelled assignment.
    """
    assigned_unit_ids = {a["unit_id"] for a in _non_cancelled_assignments(incident["id"])}
    allowed_agency_status = {"ONLINE"} if not mutual_aid else {"ONLINE", "MUTUAL_AID_ONLY"}
    pool = []
    for u in db.units.values():
        if u["status"] != "AVAILABLE":
            continue
        ag = db.agencies.get(u["agency_id"])
        if not ag:
            continue
        if ag["status"] not in allowed_agency_status:
            continue
        if ag["discipline"] != discipline:
            continue
        if u["id"] in assigned_unit_ids:
            continue
        pool.append(u)
    return pool


def _recommend(incident, discipline):
    """Run primary then mutual-aid waterfall.
    Returns (best_unit or None, candidate_count). candidate_count is the size of
    the winning pass's pool (the one that produced the recommendation, or the
    mutual-aid pool if both empty -> 0)."""
    if discipline is None:
        return None, 0
    primary = _candidate_pool(incident, discipline, mutual_aid=False)
    if primary:
        ranked = calc.rank_candidates(incident, primary)
        return ranked[0], len(primary)
    mutual = _candidate_pool(incident, discipline, mutual_aid=True)
    if mutual:
        ranked = calc.rank_candidates(incident, mutual)
        return ranked[0], len(mutual)
    return None, 0


@app.route("/incidents/<iid>/recommendation", methods=["GET"])
def get_recommendation(iid):
    _, role = authenticate()
    require_role(role, {"Dispatcher", "Supervisor"})
    incident = get_or_404(db.incidents, iid)
    requested = request.args.get("discipline")
    discipline = _resolve_discipline(incident, requested)
    best, count = _recommend(incident, discipline)
    if best is None:
        data = {
            "recommended_unit_id": None,
            "discipline": discipline,
            "travel_distance": None,
            "candidate_count": count,
        }
    else:
        dist = calc.manhattan(best["grid_x"], best["grid_y"],
                              incident["ali_grid_x"], incident["ali_grid_y"])
        data = {
            "recommended_unit_id": best["id"],
            "discipline": discipline,
            "travel_distance": dist,
            "candidate_count": count,
        }
    return success(data, status=200)


# ===========================================================================
# Assignments — dispatch (create) and field pipeline (PATCH)
# ===========================================================================
@app.route("/incidents/<iid>/assignments", methods=["POST"])
def create_assignment(iid):
    _, role = authenticate()
    require_role(role, {"Dispatcher", "Supervisor"})
    incident = get_or_404(db.incidents, iid)
    body = V.get_body()

    # FK existence (priority 4): explicit unit_id must reference an existing unit
    unit_id = body.get("unit_id")
    auto_select = body.get("auto_select")
    if unit_id is not None and unit_id not in db.units:
        raise err(E.ERR_REFERENCE_NOT_FOUND, "unit_id does not reference an existing unit.")

    # body well-formedness (priority 5)
    expected_version = V.require_int(body, "expected_incident_version")
    if auto_select is not None and not isinstance(auto_select, bool):
        raise err(E.ERR_INVALID_REQUEST, "auto_select must be a boolean.")
    requested_discipline = body.get("discipline")
    if requested_discipline is not None and requested_discipline not in C.DISCIPLINES:
        raise err(E.ERR_INVALID_REQUEST, "discipline must be a valid discipline.")
    if unit_id is None and not auto_select:
        raise err(E.ERR_INVALID_REQUEST, "Provide unit_id or set auto_select=true.")

    # OCC (priority 6)
    if expected_version != incident["version"]:
        raise err(E.ERR_STALE_INCIDENT_VERSION, "expected_incident_version does not match current incident version.")

    # state validity (priority 7): incident must be in a state that accepts new
    # assignments (PENDING, DISPATCHED, ACTIVE). HELD is handled separately at
    # priority 8; terminal states are invalid.
    if incident["lifecycle_status"] in ("CLOSED", "CANCELLED"):
        raise err(E.ERR_INVALID_STATE, "Incident is not in a state that accepts assignments.")

    # held guard (priority 8)
    if incident["lifecycle_status"] == "HELD":
        raise err(E.ERR_INCIDENT_HELD, "Incident is HELD; no new assignments until resumed.")

    # Resolve discipline for auto-select / recommended flag computation
    discipline = _resolve_discipline(incident, requested_discipline)

    if unit_id is None:
        # auto_select path: compute recommendation
        best, _count = _recommend(incident, discipline)
        if best is None:
            raise err(E.ERR_NO_UNIT_AVAILABLE, "No eligible unit in primary or mutual-aid pass.")
        unit = best
        unit_id = unit["id"]
        recommended = True
    else:
        unit = db.units[unit_id]
        ag = db.agencies.get(unit["agency_id"])

        # discipline match (priority 9)
        if not ag or ag["discipline"] not in incident["required_disciplines"]:
            raise err(E.ERR_DISCIPLINE_MISMATCH, "Unit's agency discipline is not required by this incident.")

        # agency availability (priority 10)
        if ag["status"] == "OFFLINE":
            raise err(E.ERR_AGENCY_UNAVAILABLE, "Unit's agency is OFFLINE.")
        if ag["status"] == "MUTUAL_AID_ONLY":
            # allowed only if no ONLINE unit of that discipline exists
            online_exists = any(
                a2["status"] == "ONLINE" and a2["discipline"] == ag["discipline"]
                for a2 in db.agencies.values()
            )
            if online_exists:
                raise err(E.ERR_AGENCY_UNAVAILABLE,
                          "Agency is MUTUAL_AID_ONLY while an ONLINE unit of that discipline exists.")

        # unit availability (priority 11)
        if unit["status"] != "AVAILABLE":
            raise err(E.ERR_UNIT_NOT_AVAILABLE, "Unit is not AVAILABLE.")

        # duplicate assignment (priority 12)
        for a in _non_cancelled_assignments(incident["id"]):
            if a["unit_id"] == unit_id:
                raise err(E.ERR_DUPLICATE_ASSIGNMENT, "Unit already has a non-cancelled assignment on this incident.")

        # compute recommended flag: true iff this unit is what the recommendation
        # would choose right now for the unit's discipline.
        rec_discipline = ag["discipline"]
        rec_unit, _c = _recommend(incident, rec_discipline)
        recommended = bool(rec_unit and rec_unit["id"] == unit_id)

    now = clock.now()
    travel_distance = calc.manhattan(unit["grid_x"], unit["grid_y"],
                                     incident["ali_grid_x"], incident["ali_grid_y"])

    assignment = {
        "incident_id": incident["id"],
        "unit_id": unit_id,
        "recommended": recommended,
        "travel_distance": travel_distance,
        "status": "DISPATCHED",
        "dispatched_at": iso_ts(now),
        "enroute_at": None,
        "onscene_at": None,
        "cleared_at": None,
    }
    stamp_create(assignment)
    db.assignments[assignment["id"]] = assignment

    # drive the unit
    unit["status"] = "DISPATCHED"
    unit["active_incident_id"] = incident["id"]
    touch(unit)

    # first accepted assignment flips incident PENDING -> DISPATCHED
    if incident["lifecycle_status"] == "PENDING":
        incident["lifecycle_status"] = "DISPATCHED"
        incident["first_dispatch_at"] = iso_ts(now)
        touch(incident)  # bump version on first dispatch
    else:
        # subsequent assignments do not bump version (only first dispatch does)
        touch(incident, bump_version=False)

    return success(S.assignment(assignment), status=201)


@app.route("/incidents/<iid>/assignments", methods=["GET"])
def list_incident_assignments(iid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    get_or_404(db.incidents, iid)
    items = [a for a in db.assignments.values() if a["incident_id"] == iid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.assignment(a) for a in page], limit, offset, total)


@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    return success(S.assignment(get_or_404(db.assignments, aid)), status=200)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records"})
    items = list(db.assignments.values())
    for field in ("incident_id", "unit_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.assignment(a) for a in page], limit, offset, total)


def _recompute_incident_metrics(incident):
    """Recompute response/handle/sla on the incident (PRD §3.6)."""
    incident["response_time_seconds"] = calc.response_time_seconds(
        incident["first_dispatch_at"], incident["first_onscene_at"])
    incident["total_handle_seconds"] = calc.total_handle_seconds(
        incident["received_at"], incident["first_onscene_at"])
    gov = calc.governing_sla(incident, list(db.assignments.values()),
                             db.agencies, db.units)
    incident["sla_breached"] = calc.sla_breached(
        incident["total_handle_seconds"], gov)


@app.route("/assignments/<aid>/status", methods=["PATCH"])
def patch_assignment_status(aid):
    user_id, role = authenticate()
    require_role(role, {"FieldUnit", "Dispatcher", "Supervisor"})
    assignment = get_or_404(db.assignments, aid)
    body = V.get_body()
    target = V.require_enum(body, "status", {"ENROUTE", "ONSCENE", "CLEAR", "CANCEL", "CLEARED", "CANCELLED"})
    # normalise CLEAR/CANCEL aliases
    if target == "CLEAR":
        target = "CLEARED"
    if target == "CANCEL":
        target = "CANCELLED"

    incident = db.incidents.get(assignment["incident_id"])
    unit = db.units.get(assignment["unit_id"])
    cur = assignment["status"]

    # FieldUnit ownership: a field unit acts only on its own assignment
    # (assignment's unit == X-User-ID). Dispatcher/Supervisor are not constrained.
    if role == "FieldUnit" and assignment["unit_id"] != user_id:
        raise err(E.ERR_FORBIDDEN_ROLE, "FieldUnit may act only on its own assignment.")

    now = clock.now()

    if target == "ENROUTE":
        if cur == "DISPATCHED":
            assignment["status"] = "ENROUTE"
            assignment["enroute_at"] = iso_ts(now)
            if unit:
                unit["status"] = "ENROUTE"
                touch(unit)
        elif cur == "ONSCENE":
            # re-stage; permitted only while incident not HELD
            if incident and incident["lifecycle_status"] == "HELD":
                raise err(E.ERR_INVALID_STATE, "Cannot re-stage while incident is HELD.")
            assignment["status"] = "ENROUTE"
            assignment["onscene_at"] = None
            if unit:
                unit["status"] = "ENROUTE"
                touch(unit)
        else:
            raise err(E.ERR_INVALID_STATE, f"Cannot go ENROUTE from {cur}.")

    elif target == "ONSCENE":
        if cur != "ENROUTE":
            raise err(E.ERR_INVALID_STATE, f"Cannot go ONSCENE from {cur}.")
        assignment["status"] = "ONSCENE"
        assignment["onscene_at"] = iso_ts(now)
        if unit:
            unit["status"] = "ONSCENE"
            unit["grid_x"] = incident["ali_grid_x"]
            unit["grid_y"] = incident["ali_grid_y"]
            touch(unit)
        # bubble-up: first onscene flips incident DISPATCHED -> ACTIVE
        if incident and incident["first_onscene_at"] is None:
            incident["first_onscene_at"] = iso_ts(now)
            if incident["lifecycle_status"] == "DISPATCHED":
                incident["lifecycle_status"] = "ACTIVE"
            _recompute_incident_metrics(incident)
            touch(incident, bump_version=False)

    elif target == "CLEARED":
        if cur == "ONSCENE":
            assignment["status"] = "CLEARED"
            assignment["cleared_at"] = iso_ts(now)
            if unit:
                # walk through CLEARING then AVAILABLE
                unit["status"] = "AVAILABLE"
                unit["active_incident_id"] = None
                touch(unit)
        elif cur == "ENROUTE":
            assignment["status"] = "CLEARED"
            assignment["cleared_at"] = iso_ts(now)
            if unit:
                unit["status"] = "AVAILABLE"
                unit["active_incident_id"] = None
                touch(unit)
        else:
            raise err(E.ERR_INVALID_STATE, f"Cannot CLEAR from {cur}.")

    elif target == "CANCELLED":
        if cur == "DISPATCHED":
            assignment["status"] = "CANCELLED"
            if unit:
                unit["status"] = "AVAILABLE"
                unit["active_incident_id"] = None
                touch(unit)
            _maybe_revert_to_pending(incident)
        elif cur == "ENROUTE":
            assignment["status"] = "CANCELLED"
            if unit:
                unit["status"] = "AVAILABLE"
                unit["active_incident_id"] = None
                touch(unit)
        else:
            raise err(E.ERR_INVALID_STATE, f"Cannot CANCEL from {cur}.")

    touch(assignment, bump_version=True)
    return success(S.assignment(assignment), status=200)


def _maybe_revert_to_pending(incident):
    """Cancel-from-DISPATCHED cascade (PRD §3.5): if the cancelled assignment was
    the only non-terminal assignment AND it carried first_dispatch with no ONSCENE
    ever occurring, revert incident DISPATCHED -> PENDING and clear
    first_dispatch_at."""
    if incident is None:
        return
    if incident["lifecycle_status"] != "DISPATCHED":
        return
    if incident["first_onscene_at"] is not None:
        return
    # are there any remaining non-terminal assignments?
    remaining = [a for a in db.assignments.values()
                 if a["incident_id"] == incident["id"]
                 and a["status"] in ("DISPATCHED", "ENROUTE", "ONSCENE")]
    if remaining:
        return
    incident["lifecycle_status"] = "PENDING"
    incident["first_dispatch_at"] = None
    touch(incident, bump_version=False)


# ===========================================================================
# Incident actions: escalate / hold / resume / cancel
# ===========================================================================
@app.route("/incidents/<iid>/escalate", methods=["POST"])
def escalate_incident(iid):
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    incident = get_or_404(db.incidents, iid)
    V.get_body()  # reason optional; ignore content
    if incident["lifecycle_status"] in ("CLOSED", "CANCELLED"):
        raise err(E.ERR_INVALID_STATE, "Cannot escalate a terminal incident.")
    if incident["priority_level"] <= 1:
        raise err(E.ERR_INVALID_STATE, "Incident already at top urgency.")
    incident["priority_level"] -= 1
    incident["escalation_count"] += 1
    touch(incident)  # bump version on escalation
    return success(S.incident(incident), status=200)


@app.route("/incidents/<iid>/hold", methods=["POST"])
def hold_incident(iid):
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    incident = get_or_404(db.incidents, iid)
    V.get_body()
    if incident["lifecycle_status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Only an ACTIVE incident can be held.")
    onscene_exists = any(
        a["incident_id"] == iid and a["status"] == "ONSCENE"
        for a in db.assignments.values()
    )
    if not onscene_exists:
        raise err(E.ERR_INVALID_STATE, "Hold requires at least one ONSCENE assignment.")
    incident["lifecycle_status"] = "HELD"
    touch(incident, bump_version=False)
    return success(S.incident(incident), status=200)


@app.route("/incidents/<iid>/resume", methods=["POST"])
def resume_incident(iid):
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    incident = get_or_404(db.incidents, iid)
    if incident["lifecycle_status"] != "HELD":
        raise err(E.ERR_INVALID_STATE, "Only a HELD incident can be resumed.")
    incident["lifecycle_status"] = "ACTIVE"
    touch(incident, bump_version=False)
    return success(S.incident(incident), status=200)


@app.route("/incidents/<iid>/cancel", methods=["POST"])
def cancel_incident(iid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Supervisor"})
    incident = get_or_404(db.incidents, iid)
    V.get_body()
    if incident["lifecycle_status"] != "PENDING":
        raise err(E.ERR_INVALID_STATE, "Only a PENDING incident can be cancelled.")
    any_assignment = any(a["incident_id"] == iid for a in db.assignments.values())
    if any_assignment:
        raise err(E.ERR_INVALID_STATE, "Cannot cancel: an assignment exists for this incident.")
    incident["lifecycle_status"] = "CANCELLED"
    incident["closed_at"] = iso_ts(clock.now())
    incident["disposition_code"] = "CANCELLED"
    touch(incident, bump_version=False)
    return success(S.incident(incident), status=200)


# ===========================================================================
# Dispositions — close
# ===========================================================================
@app.route("/incidents/<iid>/dispositions", methods=["POST"])
def create_disposition(iid):
    _, role = authenticate()
    require_role(role, {"Supervisor"})
    incident = get_or_404(db.incidents, iid)
    body = V.get_body()
    disposition_code = V.require_enum(body, "disposition_code", C.DISPOSITION_CODES)
    narrative = V.require_string(body, "narrative")

    # state validity: must be DISPATCHED, ACTIVE, or HELD
    if incident["lifecycle_status"] not in ("DISPATCHED", "ACTIVE", "HELD"):
        raise err(E.ERR_INVALID_STATE, "Incident is not in a closable lifecycle state.")

    # every assignment must be CLEARED or CANCELLED (priority 14)
    open_exists = any(
        a["incident_id"] == iid and a["status"] in ("DISPATCHED", "ENROUTE", "ONSCENE")
        for a in db.assignments.values()
    )
    started_from = incident["lifecycle_status"]
    if open_exists:
        raise err(E.ERR_OPEN_ASSIGNMENTS, "Cannot close: an assignment is still open.")

    requires_nfirs = "FIRE" in incident["required_disciplines"]
    disposition = {
        "incident_id": iid,
        "disposition_code": disposition_code,
        "narrative": narrative,
        "requires_nfirs": requires_nfirs,
    }
    stamp_create(disposition)
    db.dispositions[disposition["id"]] = disposition

    # close the incident
    incident["lifecycle_status"] = "CLOSED"
    incident["closed_at"] = iso_ts(clock.now())
    incident["disposition_code"] = disposition_code

    # CASCADE: when starting from DISPATCHED or ACTIVE, force non-terminal
    # assignments to CLEARED and free their units. (Per state machine: HELD close
    # has no cascade clause, but by precondition all assignments are already
    # terminal there, so the loop is a no-op anyway.)
    if started_from in ("DISPATCHED", "ACTIVE"):
        for a in db.assignments.values():
            if a["incident_id"] == iid and a["status"] in ("DISPATCHED", "ENROUTE", "ONSCENE"):
                a["status"] = "CLEARED"
                a["cleared_at"] = iso_ts(clock.now())
                touch(a)
                u = db.units.get(a["unit_id"])
                if u:
                    u["status"] = "AVAILABLE"
                    u["active_incident_id"] = None
                    touch(u)

    touch(incident)  # bump version on close
    return success(S.disposition(disposition), status=201)


@app.route("/incidents/<iid>/dispositions", methods=["GET"])
def list_dispositions(iid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "Supervisor", "Records"})
    get_or_404(db.incidents, iid)
    items = [d for d in db.dispositions.values() if d["incident_id"] == iid]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.disposition(d) for d in page], limit, offset, total)


# ===========================================================================
# Reports
# ===========================================================================
@app.route("/incidents/<iid>/reports", methods=["POST"])
def create_report(iid):
    _, role = authenticate()
    require_role(role, {"Records", "Supervisor"})
    incident = get_or_404(db.incidents, iid)
    body = V.get_body()
    report_standard = V.require_enum(body, "report_standard", C.REPORT_STANDARDS)

    # report standard / discipline compatibility (priority 15)
    is_fire = "FIRE" in incident["required_disciplines"]
    if report_standard == "NFIRS" and not is_fire:
        raise err(E.ERR_REPORT_STANDARD_MISMATCH, "NFIRS report requires a FIRE-discipline incident.")

    # must be CLOSED (priority 16)
    if incident["lifecycle_status"] != "CLOSED":
        raise err(E.ERR_INCIDENT_NOT_CLOSED, "Reports may only be generated for a CLOSED incident.")

    unit_count = calc.incident_unit_count(iid, list(db.assignments.values()))
    report = {
        "incident_id": iid,
        "report_standard": report_standard,
        "response_time_seconds": incident["response_time_seconds"],
        "total_handle_seconds": incident["total_handle_seconds"],
        "sla_breached": incident["sla_breached"],
        "unit_count": unit_count,
        "disposition_code": incident["disposition_code"],
    }
    stamp_create(report, with_version=False)  # immutable: only id + created_at
    db.reports[report["id"]] = report
    return success(S.report(report), status=201)


@app.route("/incidents/<iid>/reports", methods=["GET"])
def list_reports(iid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "Supervisor", "Records"})
    get_or_404(db.incidents, iid)
    items = [r for r in db.reports.values() if r["incident_id"] == iid]
    standard = request.args.get("report_standard")
    if standard is not None:
        items = [r for r in items if r["report_standard"] == standard]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([S.report(r) for r in page], limit, offset, total)


@app.route("/reports/<rid>", methods=["GET"])
def get_report(rid):
    _, role = authenticate()
    require_role(role, {"Calltaker", "Dispatcher", "Supervisor", "Records"})
    return success(S.report(get_or_404(db.reports, rid)), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
