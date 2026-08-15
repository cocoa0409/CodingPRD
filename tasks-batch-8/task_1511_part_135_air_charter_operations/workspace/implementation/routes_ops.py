"""Operations endpoints: MaintenanceWindow, Passenger, OverflightPermit,
ComplianceFinding, WeatherAdvisory, and the logical clock."""

from flask import Blueprint, g, request

from httpkit import (
    ALL_ROLES, authenticate, ensure_empty_body, err, err_forbidden,
    err_invalid_request, err_invalid_time_range, get_body, paginate,
    require_positive, require_roles, respond_object, sorted_items,
)
from serializers import (
    advisory_json, finding_json, flight_log_json, maintenance_window_json,
    passenger_json, payment_json, permit_json, statement_json,
)
from services import (
    closed_intersects, complete_trip, confirmed_assignment_for,
    create_payment, get_aircraft_or_404, get_crew_member_or_404,
    get_flight_log_or_404, get_finding_or_404, get_leg_or_404,
    get_owner_or_404, get_passenger_or_404, get_permit_or_404,
    get_statement_or_404, get_trip_or_404, get_window_or_404, new_common,
    new_ledger, raw_flight_interval, recompute_payment_posture,
    run_expiry_sweep, touch, trip_legs,
)
from store import db

bp = Blueprint("ops", __name__)

WINDOW_TYPES = ["INSPECTION_100H", "ANNUAL", "AOG_REPAIR"]
SEVERITIES = ["SIGMET", "CONVECTIVE", "WINTER", "OTHER"]
SUBJECT_TYPES = ["AIRCRAFT", "CREW_MEMBER", "TRIP_REQUEST"]


# ---------------------------------------------------------------------------
# MaintenanceWindow
# ---------------------------------------------------------------------------

@bp.post("/charter/maintenance-windows")
def create_maintenance_window():
    authenticate()
    require_roles("MaintenanceController")
    data = get_body([
        {"name": "aircraft_id", "type": "string", "required": True},
        {"name": "window_type", "type": "enum", "values": WINDOW_TYPES,
         "required": True},
        {"name": "starts_at", "type": "datetime", "required": True},
        {"name": "ends_at", "type": "datetime", "required": True},
    ])
    # Priority 4 (time-range coherence) is evaluated before priority 5
    # (existence), per PRD section 2.11.
    if data["ends_at"] <= data["starts_at"]:
        raise err_invalid_time_range("ends_at must be after starts_at")
    aircraft = get_aircraft_or_404(data["aircraft_id"])

    # Closed-interval, touching-counts conflict checks in both directions:
    # first vs CONFIRMED assignments' raw flight intervals, then vs other
    # PLANNED/ACTIVE windows on the same tail.
    for a in db.aircraft_assignments.values():
        if a["aircraft_id"] != aircraft["id"] or a["status"] != "CONFIRMED":
            continue
        trip = db.trips.get(a["trip_request_id"])
        if trip is None:
            continue
        fs, fe = raw_flight_interval(trip)
        if closed_intersects(data["starts_at"], data["ends_at"], fs, fe):
            raise err("ERR_MAINTENANCE_CONFLICT", 409,
                      "The window intersects the flight interval of a "
                      "CONFIRMED assignment on this aircraft")
    for w in db.maintenance_windows.values():
        if w["aircraft_id"] != aircraft["id"]:
            continue
        if w["status"] not in ("PLANNED", "ACTIVE"):
            continue
        if closed_intersects(data["starts_at"], data["ends_at"],
                             w["starts_at"], w["ends_at"]):
            raise err("ERR_WINDOW_OVERLAP", 409,
                      "The window intersects another PLANNED or ACTIVE window "
                      "on this aircraft")

    w = new_common()
    w.update({
        "aircraft_id": aircraft["id"],
        "window_type": data["window_type"],
        "starts_at": data["starts_at"],
        "ends_at": data["ends_at"],
        "status": "PLANNED",
    })
    db.maintenance_windows[w["id"]] = w
    return respond_object(maintenance_window_json(w), 201)


@bp.get("/charter/aircraft/<aircraft_id>/maintenance-windows")
def list_aircraft_windows(aircraft_id):
    authenticate()
    require_roles(*ALL_ROLES)
    get_aircraft_or_404(aircraft_id)
    items = sorted_items(w for w in db.maintenance_windows.values()
                         if w["aircraft_id"] == aircraft_id)
    return paginate([maintenance_window_json(w) for w in items])


@bp.get("/charter/maintenance-windows/<window_id>")
def get_maintenance_window(window_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(maintenance_window_json(get_window_or_404(window_id)))


@bp.post("/charter/maintenance-windows/<window_id>/complete")
def complete_maintenance_window(window_id):
    authenticate()
    require_roles("MaintenanceController")
    ensure_empty_body()
    w = get_window_or_404(window_id)
    if w["status"] != "ACTIVE":
        raise err("ERR_WINDOW_NOT_COMPLETABLE", 409,
                  "Completing a window requires it to be ACTIVE")
    w["status"] = "COMPLETED"
    touch(w)
    aircraft = db.aircraft.get(w["aircraft_id"])
    if aircraft is not None:
        mutated = False
        if w["window_type"] == "INSPECTION_100H":
            aircraft["next_check_due_minutes"] = \
                aircraft["total_airframe_minutes"] + 6000
            mutated = True
        other_active = any(
            x["aircraft_id"] == aircraft["id"] and x["status"] == "ACTIVE"
            for x in db.maintenance_windows.values())
        if not other_active and aircraft["status"] == "MAINTENANCE_HOLD" \
                and aircraft["total_airframe_minutes"] < aircraft["next_check_due_minutes"]:
            aircraft["status"] = "AVAILABLE"
            mutated = True
        if mutated:
            touch(aircraft)
    return respond_object(maintenance_window_json(w))


@bp.post("/charter/maintenance-windows/<window_id>/cancel")
def cancel_maintenance_window(window_id):
    authenticate()
    require_roles("MaintenanceController")
    ensure_empty_body()
    w = get_window_or_404(window_id)
    if w["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", 409,
                  "Only a PLANNED window may be cancelled")
    w["status"] = "CANCELLED"
    touch(w)
    return respond_object(maintenance_window_json(w))


# ---------------------------------------------------------------------------
# Passenger
# ---------------------------------------------------------------------------

@bp.post("/charter/passengers")
def create_passenger():
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "full_name", "type": "string", "required": True},
        {"name": "date_of_birth", "type": "string", "required": True},
    ])
    t = get_trip_or_404(data["trip_request_id"])
    if t["status"] not in ("QUOTED", "BOOKED"):
        raise err("ERR_INVALID_STATE", 409,
                  "Passengers may only be added to QUOTED or BOOKED trips")
    p = new_common()
    p.update({
        "trip_request_id": t["id"],
        "full_name": data["full_name"],
        "date_of_birth": data["date_of_birth"],
        "tsa_status": "PENDING",
        "screened_at": None,
    })
    db.passengers[p["id"]] = p
    return respond_object(passenger_json(p), 201)


@bp.get("/charter/trip-requests/<trip_id>/passengers")
def list_trip_passengers(trip_id):
    authenticate()
    require_roles(*ALL_ROLES)
    get_trip_or_404(trip_id)
    items = sorted_items(p for p in db.passengers.values()
                         if p["trip_request_id"] == trip_id)
    return paginate([passenger_json(p) for p in items])


@bp.get("/charter/passengers/<passenger_id>")
def get_passenger(passenger_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(passenger_json(get_passenger_or_404(passenger_id)))


@bp.post("/charter/passengers/<passenger_id>/screen")
def screen_passenger(passenger_id):
    authenticate()
    require_roles("ComplianceOfficer")
    data = get_body([
        {"name": "outcome", "type": "enum", "values": ["CLEARED", "DENIED"],
         "required": True},
    ])
    p = get_passenger_or_404(passenger_id)
    if p["tsa_status"] not in ("PENDING", "EXPIRED"):
        raise err("ERR_PASSENGER_NOT_SCREENABLE", 409,
                  "Only a PENDING or EXPIRED passenger may be screened")
    p["tsa_status"] = data["outcome"]
    p["screened_at"] = db.now()
    touch(p)
    return respond_object(passenger_json(p))


# ---------------------------------------------------------------------------
# OverflightPermit
# ---------------------------------------------------------------------------

@bp.post("/charter/overflight-permits")
def create_permit():
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "country_code", "type": "string", "required": True},
        {"name": "permit_type", "type": "enum",
         "values": ["OVERFLIGHT", "LANDING"], "required": True},
        {"name": "required", "type": "boolean", "required": False},
    ])
    t = get_trip_or_404(data["trip_request_id"])
    required = data["required"] if data["required"] is not None else True
    for p in db.permits.values():
        if p["trip_request_id"] == t["id"] \
                and p["country_code"] == data["country_code"] \
                and p["permit_type"] == data["permit_type"] \
                and p["status"] in ("REQUESTED", "GRANTED"):
            raise err("ERR_DUPLICATE_PERMIT", 422,
                      "A permit for this trip, country, and type is already "
                      "REQUESTED or GRANTED")
    p = new_common()
    p.update({
        "trip_request_id": t["id"],
        "country_code": data["country_code"],
        "permit_type": data["permit_type"],
        "required": required,
        "status": "REQUESTED",
        "decided_at": None,
    })
    db.permits[p["id"]] = p
    return respond_object(permit_json(p), 201)


@bp.get("/charter/trip-requests/<trip_id>/overflight-permits")
def list_trip_permits(trip_id):
    authenticate()
    require_roles(*ALL_ROLES)
    get_trip_or_404(trip_id)
    items = sorted_items(p for p in db.permits.values()
                         if p["trip_request_id"] == trip_id)
    return paginate([permit_json(p) for p in items])


@bp.get("/charter/overflight-permits/<permit_id>")
def get_permit(permit_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(permit_json(get_permit_or_404(permit_id)))


@bp.post("/charter/overflight-permits/<permit_id>/decide")
def decide_permit(permit_id):
    authenticate()
    require_roles("ComplianceOfficer")
    data = get_body([
        {"name": "decision", "type": "enum", "values": ["GRANTED", "DENIED"],
         "required": True},
    ])
    p = get_permit_or_404(permit_id)
    if p["status"] != "REQUESTED":
        raise err("ERR_PERMIT_NOT_DECIDABLE", 409,
                  "Only a REQUESTED permit may be decided")
    p["status"] = data["decision"]
    p["decided_at"] = db.now()
    touch(p)
    return respond_object(permit_json(p))


# ---------------------------------------------------------------------------
# Payment (manual BALANCE only; DEPOSIT via book, REFUND via cancel)
# ---------------------------------------------------------------------------

@bp.post("/charter/payments")
def create_payment_endpoint():
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "payment_type", "type": "enum",
         "values": ["DEPOSIT", "BALANCE", "REFUND"], "required": True},
        {"name": "amount_cents", "type": "integer", "required": True},
    ])
    require_positive(data["amount_cents"], "amount_cents")
    t = get_trip_or_404(data["trip_request_id"])
    if data["payment_type"] != "BALANCE" or t["status"] not in ("BOOKED", "DISPATCHED"):
        raise err("ERR_PAYMENT_STATE_INVALID", 402,
                  "Manual payments must be BALANCE on a BOOKED or DISPATCHED "
                  "trip")
    outstanding = t["quoted_total_cents"] - t["collected_cents"]
    if data["amount_cents"] > outstanding:
        raise err("ERR_OVERPAYMENT", 402,
                  "A BALANCE payment may not exceed the outstanding balance")
    p = create_payment(t["id"], "BALANCE", data["amount_cents"])
    recompute_payment_posture(t)
    touch(t)
    return respond_object(payment_json(p), 201)


@bp.get("/charter/trip-requests/<trip_id>/payments")
def list_trip_payments(trip_id):
    authenticate()
    require_roles(*ALL_ROLES)
    get_trip_or_404(trip_id)
    items = sorted_items(p for p in db.payments.values()
                         if p["trip_request_id"] == trip_id)
    return paginate([payment_json(p) for p in items])


# ---------------------------------------------------------------------------
# FlightLog
# ---------------------------------------------------------------------------

@bp.post("/charter/flight-logs")
def create_flight_log():
    authenticate()
    require_roles("CrewMember")
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "quote_leg_id", "type": "string", "required": True},
        {"name": "actual_block_minutes", "type": "integer", "required": True},
        {"name": "departed_at", "type": "datetime", "required": True},
        {"name": "arrived_at", "type": "datetime", "required": True},
    ])
    require_positive(data["actual_block_minutes"], "actual_block_minutes")
    if data["arrived_at"] <= data["departed_at"]:
        raise err_invalid_time_range("arrived_at must be after departed_at")
    t = get_trip_or_404(data["trip_request_id"])
    leg = get_leg_or_404(data["quote_leg_id"])

    # Entity-backed ownership: the acting CrewMember must be the trip's
    # VETTED PIC (PRD section 2.1).
    is_vetted_pic = any(
        c["trip_request_id"] == t["id"] and c["crew_member_id"] == g.user_id
        and c["duty_role"] == "PIC" and c["status"] == "VETTED"
        for c in db.crew_assignments.values())
    if not is_vetted_pic:
        raise err_forbidden(
            "Only the trip's VETTED PIC may record a flight log")

    if t["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", 409,
                  "Flight logs may only be recorded on a DISPATCHED trip")
    if leg["trip_request_id"] != t["id"]:
        raise err("ERR_LEG_TRIP_MISMATCH", 422,
                  "The quote leg does not belong to the given trip")
    if any(f["quote_leg_id"] == leg["id"] for f in db.flight_logs.values()):
        raise err("ERR_DUPLICATE_FLIGHT_LOG", 422,
                  "The leg already has a FlightLog")

    fl = new_ledger()
    fl.update({
        "trip_request_id": t["id"],
        "quote_leg_id": leg["id"],
        "actual_block_minutes": data["actual_block_minutes"],
        "departed_at": data["departed_at"],
        "arrived_at": data["arrived_at"],
        "recorded_by_crew_id": g.user_id,
    })
    db.flight_logs[fl["id"]] = fl

    # The confirmed tail accumulates actual block minutes immediately.
    assignment = confirmed_assignment_for(t["id"])
    aircraft = db.aircraft[assignment["aircraft_id"]] if assignment else None
    if aircraft is not None:
        aircraft["total_airframe_minutes"] += data["actual_block_minutes"]
        touch(aircraft)

    # Completion is automatic once every leg has exactly one log.
    legs = trip_legs(t["id"])
    logged_leg_ids = {f["quote_leg_id"] for f in db.flight_logs.values()
                      if f["trip_request_id"] == t["id"]}
    if legs and all(lg["id"] in logged_leg_ids for lg in legs):
        complete_trip(t)

    return respond_object(flight_log_json(fl), 201)


@bp.get("/charter/flight-logs")
def list_flight_logs():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.flight_logs.values())
    flt_trip = request.args.get("trip_request_id")
    if flt_trip is not None:
        items = [f for f in items if f["trip_request_id"] == flt_trip]
    flt_leg = request.args.get("quote_leg_id")
    if flt_leg is not None:
        items = [f for f in items if f["quote_leg_id"] == flt_leg]
    return paginate([flight_log_json(f) for f in items])


@bp.get("/charter/flight-logs/<flight_log_id>")
def get_flight_log(flight_log_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(flight_log_json(get_flight_log_or_404(flight_log_id)))


# ---------------------------------------------------------------------------
# OwnerStatement
# ---------------------------------------------------------------------------

@bp.get("/charter/trip-requests/<trip_id>/owner-statements")
def list_trip_statements(trip_id):
    authenticate()
    require_roles(*ALL_ROLES)
    get_trip_or_404(trip_id)
    items = sorted_items(s for s in db.statements.values()
                         if s["trip_request_id"] == trip_id)
    return paginate([statement_json(s) for s in items])


@bp.post("/charter/owner-statements/<statement_id>/issue")
def issue_statement(statement_id):
    authenticate()
    require_roles("OpsAdmin")
    ensure_empty_body()
    s = get_statement_or_404(statement_id)
    if s["status"] != "DRAFT":
        raise err("ERR_STATEMENT_NOT_DRAFT", 409,
                  "Issuing a statement requires it to be DRAFT")
    s["status"] = "ISSUED"
    s["issued_at"] = db.now()
    touch(s)
    return respond_object(statement_json(s))


# ---------------------------------------------------------------------------
# ComplianceFinding
# ---------------------------------------------------------------------------

@bp.post("/charter/compliance-findings")
def create_finding():
    authenticate()
    require_roles("ComplianceOfficer")
    data = get_body([
        {"name": "subject_type", "type": "enum", "values": SUBJECT_TYPES,
         "required": True},
        {"name": "subject_id", "type": "string", "required": True},
        {"name": "finding_code", "type": "string", "required": True},
        {"name": "grounding", "type": "boolean", "required": True},
        {"name": "notes", "type": "string", "required": False},
    ])
    # The polymorphic subject_id must exist in the collection named by
    # subject_type; the resource-specific 404 applies.
    if data["subject_type"] == "AIRCRAFT":
        get_aircraft_or_404(data["subject_id"])
    elif data["subject_type"] == "CREW_MEMBER":
        get_crew_member_or_404(data["subject_id"])
    else:
        get_trip_or_404(data["subject_id"])
    f = new_common()
    f.update({
        "subject_type": data["subject_type"],
        "subject_id": data["subject_id"],
        "finding_code": data["finding_code"],
        "grounding": data["grounding"],
        "notes": data["notes"],
        "status": "OPEN",
        "resolved_at": None,
    })
    db.findings[f["id"]] = f
    return respond_object(finding_json(f), 201)


@bp.get("/charter/compliance-findings")
def list_findings():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.findings.values())
    flt_type = request.args.get("subject_type")
    if flt_type is not None:
        items = [f for f in items if f["subject_type"] == flt_type]
    flt_subject = request.args.get("subject_id")
    if flt_subject is not None:
        items = [f for f in items if f["subject_id"] == flt_subject]
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [f for f in items if f["status"] == flt_status]
    return paginate([finding_json(f) for f in items])


@bp.get("/charter/compliance-findings/<finding_id>")
def get_finding(finding_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(finding_json(get_finding_or_404(finding_id)))


@bp.post("/charter/compliance-findings/<finding_id>/resolve")
def resolve_finding(finding_id):
    authenticate()
    require_roles("ComplianceOfficer")
    ensure_empty_body()
    f = get_finding_or_404(finding_id)
    if f["status"] != "OPEN":
        raise err("ERR_FINDING_ALREADY_RESOLVED", 409,
                  "Resolving a finding requires it to be OPEN")
    f["status"] = "RESOLVED"
    f["resolved_at"] = db.now()
    touch(f)
    return respond_object(finding_json(f))


# ---------------------------------------------------------------------------
# WeatherAdvisory
# ---------------------------------------------------------------------------

@bp.post("/charter/weather-advisories")
def create_advisory():
    authenticate()
    require_roles("DispatchManager")
    data = get_body([
        {"name": "station_icao", "type": "string", "required": True},
        {"name": "severity", "type": "enum", "values": SEVERITIES,
         "required": True},
        {"name": "starts_at", "type": "datetime", "required": True},
        {"name": "ends_at", "type": "datetime", "required": True},
    ])
    if data["ends_at"] <= data["starts_at"]:
        raise err_invalid_time_range("ends_at must be after starts_at")
    w = new_ledger()
    w.update({
        "station_icao": data["station_icao"],
        "severity": data["severity"],
        "starts_at": data["starts_at"],
        "ends_at": data["ends_at"],
    })
    db.advisories[w["id"]] = w
    return respond_object(advisory_json(w), 201)


@bp.get("/charter/weather-advisories")
def list_advisories():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.advisories.values())
    flt_station = request.args.get("station_icao")
    if flt_station is not None:
        items = [w for w in items if w["station_icao"] == flt_station]
    return paginate([advisory_json(w) for w in items])


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/charter/_clock/set_current_utc")
def set_clock():
    authenticate()
    require_roles("OpsAdmin")
    data = get_body([
        {"name": "to_iso8601", "type": "datetime", "required": True},
    ])
    target = data["to_iso8601"]
    if target < db.now():
        raise err_invalid_request("The logical clock only moves forward")
    db.clock = target
    run_expiry_sweep()
    return respond_object({})
