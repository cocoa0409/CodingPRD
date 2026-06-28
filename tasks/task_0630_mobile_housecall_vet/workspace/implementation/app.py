"""Mobile & House-Call Veterinary Service API — entry point and all routes."""
import os

from flask import Flask, request

import clock
import db
import models
import services
import calculations as calc
from errors import ApiError, err
from middleware import authenticate, require_role
from response import success_object, success_array, error_response, iso_ts
from util import (
    get_json_body,
    require_fields,
    parse_dt,
    check_enum,
    is_number,
    is_int,
    pagination_params,
    paginate,
)

app = Flask(__name__)

ALL_ROLES = ["Dispatcher", "Clinician", "ComplianceOfficer"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 400, f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch(collection, entity_id):
    rec = collection.get(entity_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist")
    return rec


def list_response(collection, predicate=None, sort_key=None):
    limit, offset = pagination_params()
    items = list(collection.values())
    if predicate:
        items = [r for r in items if predicate(r)]
    items.sort(key=sort_key or models.sort_key_created)
    page, total = paginate(items, limit, offset)
    return success_array([models.public(r) for r in page], limit, offset, total)


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, ["Dispatcher", "ComplianceOfficer"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    clock.set_now(dt)
    return success_object({"current_utc": iso_ts(clock.now())}, status=200)


# ===========================================================================
# ServiceArea
# ===========================================================================
@app.route("/service-areas", methods=["POST"])
def create_service_area():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_json_body()
    require_fields(body, ["zip_code", "name", "travel_surcharge_cents"])
    zip_code = body["zip_code"]
    name = body["name"]
    surcharge = body["travel_surcharge_cents"]
    euth = body.get("euthanasia_allowed", True)
    if not isinstance(zip_code, str) or not zip_code:
        raise err("ERR_INVALID_REQUEST", "zip_code must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise err("ERR_INVALID_REQUEST", "name must be a non-empty string")
    if not is_int(surcharge) or surcharge < 0:
        raise err("ERR_INVALID_REQUEST", "travel_surcharge_cents must be an integer >= 0")
    if not isinstance(euth, bool):
        raise err("ERR_INVALID_REQUEST", "euthanasia_allowed must be a boolean")

    rec = models.stamp_new({
        "zip_code": zip_code,
        "name": name,
        "travel_surcharge_cents": surcharge,
        "euthanasia_allowed": euth,
        "status": "ACTIVE",
    })
    db.service_areas[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/service-areas", methods=["GET"])
def list_service_areas():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    zip_filter = request.args.get("zip_code")
    pred = (lambda r: r["zip_code"] == zip_filter) if zip_filter is not None else None
    return list_response(db.service_areas, pred)


@app.route("/service-areas/<entity_id>", methods=["GET"])
def get_service_area(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.service_areas, entity_id)
    return success_object(models.public(rec))


@app.route("/service-areas/<entity_id>/suspend", methods=["POST"])
def suspend_service_area(entity_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    rec = fetch(db.service_areas, entity_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "ServiceArea is not ACTIVE")
    rec["status"] = "SUSPENDED"
    models.touch(rec)
    return success_object(models.public(rec))


# ===========================================================================
# Clinician
# ===========================================================================
@app.route("/clinicians", methods=["POST"])
def create_clinician():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_json_body()
    require_fields(body, ["full_name", "clinician_role"])
    full_name = body["full_name"]
    crole = body["clinician_role"]
    if not isinstance(full_name, str) or not full_name:
        raise err("ERR_INVALID_REQUEST", "full_name must be a non-empty string")
    check_enum(crole, {"VET", "TECH"}, "clinician_role")
    dea_number = body.get("dea_number")
    dea_expires_on = body.get("dea_expires_on")
    if crole == "VET":
        if not dea_number or not isinstance(dea_number, str):
            raise err("ERR_INVALID_REQUEST", "dea_number required for VET")
        if dea_expires_on is None:
            raise err("ERR_INVALID_REQUEST", "dea_expires_on required for VET")
        dea_dt = parse_dt(dea_expires_on, "dea_expires_on")
        stored_expiry = iso_ts(dea_dt)
    else:
        if dea_number is not None:
            raise err("ERR_INVALID_REQUEST", "dea_number must be null for TECH")
        if dea_expires_on is not None:
            raise err("ERR_INVALID_REQUEST", "dea_expires_on must be null for TECH")
        dea_number = None
        stored_expiry = None

    rec = models.stamp_new({
        "full_name": full_name,
        "clinician_role": crole,
        "dea_number": dea_number,
        "dea_expires_on": stored_expiry,
        "status": "AVAILABLE",
    })
    db.clinicians[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/clinicians", methods=["GET"])
def list_clinicians():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    crole = request.args.get("clinician_role")
    pred = (lambda r: r["clinician_role"] == crole) if crole is not None else None
    return list_response(db.clinicians, pred)


@app.route("/clinicians/<entity_id>", methods=["GET"])
def get_clinician(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.clinicians, entity_id)
    return success_object(models.public(rec))


@app.route("/clinicians/<entity_id>/controlled-logs", methods=["GET"])
def clinician_controlled_logs(entity_id):
    _, role = authenticate()
    require_role(role, ["ComplianceOfficer", "Dispatcher"])
    fetch(db.clinicians, entity_id)
    pred = lambda l: (
        l["administering_vet_id"] == entity_id or l.get("witness_vet_id") == entity_id
    )
    return list_response(db.controlled_med_logs, pred)


# ===========================================================================
# RollingClinic
# ===========================================================================
@app.route("/rolling-clinics", methods=["POST"])
def create_rolling_clinic():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_json_body()
    require_fields(body, ["plate", "controlled_stock_ml", "vaccine_stock_count"])
    plate = body["plate"]
    controlled = body["controlled_stock_ml"]
    vaccine = body["vaccine_stock_count"]
    if not isinstance(plate, str) or not plate:
        raise err("ERR_INVALID_REQUEST", "plate must be a non-empty string")
    if not is_number(controlled) or controlled < 0:
        raise err("ERR_INVALID_REQUEST", "controlled_stock_ml must be a number >= 0")
    if not is_int(vaccine) or vaccine < 0:
        raise err("ERR_INVALID_REQUEST", "vaccine_stock_count must be an integer >= 0")

    rec = models.stamp_new({
        "plate": plate,
        "controlled_stock_ml": controlled,
        "controlled_reconciled_ml": None,
        "vaccine_stock_count": vaccine,
        "status": "IN_DEPOT",
    })
    db.rolling_clinics[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/rolling-clinics", methods=["GET"])
def list_rolling_clinics():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return list_response(db.rolling_clinics)


@app.route("/rolling-clinics/<entity_id>", methods=["GET"])
def get_rolling_clinic(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.rolling_clinics, entity_id)
    return success_object(models.public(rec))


@app.route("/rolling-clinics/<entity_id>", methods=["PATCH"])
def patch_rolling_clinic(entity_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    rec = fetch(db.rolling_clinics, entity_id)
    body = get_json_body()
    require_fields(body, ["status", "expected_rolling_clinic_version"])
    new_status = body["status"]
    expected = body["expected_rolling_clinic_version"]
    check_enum(new_status, {"MAINTENANCE", "IN_DEPOT"}, "status")
    if not is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_rolling_clinic_version must be an integer")
    if expected != rec["version"]:
        raise err("ERR_STALE_ROUTE_DAY_VERSION", "Stale rolling clinic version")
    rec["status"] = new_status
    models.touch(rec)
    return success_object(models.public(rec))


@app.route("/rolling-clinics/<entity_id>/controlled-logs", methods=["GET"])
def rolling_clinic_controlled_logs(entity_id):
    _, role = authenticate()
    require_role(role, ["ComplianceOfficer", "Dispatcher"])
    fetch(db.rolling_clinics, entity_id)
    pred = lambda l: l["rolling_clinic_id"] == entity_id
    return list_response(db.controlled_med_logs, pred)


# ===========================================================================
# Patient
# ===========================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_json_body()
    require_fields(body, ["owner_name", "species", "weight_kg", "home_zip"])
    owner_name = body["owner_name"]
    species = body["species"]
    weight = body["weight_kg"]
    home_zip = body["home_zip"]
    if not isinstance(owner_name, str) or not owner_name:
        raise err("ERR_INVALID_REQUEST", "owner_name must be a non-empty string")
    check_enum(species, {"DOG", "CAT", "OTHER"}, "species")
    if not is_number(weight) or weight <= 0:
        raise err("ERR_INVALID_REQUEST", "weight_kg must be a number > 0")
    if not isinstance(home_zip, str) or not home_zip:
        raise err("ERR_INVALID_REQUEST", "home_zip must be a non-empty string")

    rec = models.stamp_new({
        "owner_name": owner_name,
        "species": species,
        "weight_kg": weight,
        "home_zip": home_zip,
    })
    db.patients[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/patients/<entity_id>", methods=["GET"])
def get_patient(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.patients, entity_id)
    return success_object(models.public(rec))


# ===========================================================================
# Appointment
# ===========================================================================
@app.route("/appointments", methods=["POST"])
def create_appointment():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_json_body()
    require_fields(body, ["patient_id", "visit_type", "requested_start", "requested_end"])
    patient = fetch(db.patients, body["patient_id"])
    visit_type = body["visit_type"]
    check_enum(visit_type, {"EXAM", "VACCINE", "EUTHANASIA"}, "visit_type")
    rstart = parse_dt(body["requested_start"], "requested_start")
    rend = parse_dt(body["requested_end"], "requested_end")
    if rend <= rstart:
        raise err("ERR_INVALID_REQUEST", "requested_end must be after requested_start")
    vaccine_doses = body.get("vaccine_doses", 0)
    if not is_int(vaccine_doses) or vaccine_doses < 0:
        raise err("ERR_INVALID_REQUEST", "vaccine_doses must be an integer >= 0")

    # service_area_id resolved by matching patient.home_zip to an ACTIVE area.
    area = services.resolve_active_service_area(patient["home_zip"])
    area_id = area["id"] if area else None

    rec = models.stamp_new({
        "patient_id": patient["id"],
        "service_area_id": area_id,
        "visit_type": visit_type,
        "requested_start": iso_ts(rstart),
        "requested_end": iso_ts(rend),
        "vaccine_doses": vaccine_doses,
        "status": "REQUESTED",
    })
    db.appointments[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/appointments", methods=["GET"])
def list_appointments():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    patient_id = request.args.get("patient_id")
    area_id = request.args.get("service_area_id")

    def pred(r):
        if patient_id is not None and r["patient_id"] != patient_id:
            return False
        if area_id is not None and r["service_area_id"] != area_id:
            return False
        return True

    return list_response(db.appointments, pred)


@app.route("/appointments/<entity_id>", methods=["GET"])
def get_appointment(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.appointments, entity_id)
    return success_object(models.public(rec))


@app.route("/appointments/<entity_id>/arrive", methods=["POST"])
def appointment_arrive(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    appt = fetch(db.appointments, entity_id)
    if appt["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Appointment is not SCHEDULED")
    stop = services.linked_route_stop(appt["id"])
    if stop is None or stop["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Linked RouteStop is not PLANNED")
    route_day = db.route_days[stop["route_day_id"]]
    if route_day["posture"] not in ("OPEN", "LOCKED"):
        raise err("ERR_ROUTE_NOT_OPEN", "RouteDay posture does not permit arrival")

    appt["status"] = "IN_VISIT"
    models.touch(appt)
    stop["status"] = "ARRIVED"
    models.touch(stop)
    clinician = db.clinicians[route_day["clinician_id"]]
    clinician["status"] = "ON_ROUTE"
    models.touch(clinician)
    return success_object(models.public(appt))


@app.route("/appointments/<entity_id>/complete-visit", methods=["POST"])
def appointment_complete_visit(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    appt = fetch(db.appointments, entity_id)
    if appt["status"] != "IN_VISIT":
        raise err("ERR_INVALID_STATE", "Appointment is not IN_VISIT")

    # An APPROVED estimate must exist.
    approved = [
        e for e in services.estimates_for_appointment(appt["id"])
        if e["status"] == "APPROVED"
    ]
    if not approved:
        raise err("ERR_NO_APPROVED_ESTIMATE", "No APPROVED estimate for this appointment")
    estimate = approved[0]

    stop = services.linked_route_stop(appt["id"])
    route_day = db.route_days[stop["route_day_id"]] if stop else None
    clinic = db.rolling_clinics[route_day["rolling_clinic_id"]] if route_day else None

    if appt["visit_type"] == "EUTHANASIA":
        logs = services.logs_for_appointment(appt["id"])
        has_dispense = any(l["entry_type"] == "DISPENSE" for l in logs)
        has_waste = any(l["entry_type"] == "WASTE" for l in logs)
        if not (has_dispense and has_waste):
            raise err(
                "ERR_EUTHANASIA_LOG_INCOMPLETE",
                "Euthanasia visit requires both a DISPENSE and a WASTE log entry",
            )

    if appt["visit_type"] == "VACCINE" and appt["vaccine_doses"] > 0:
        if clinic is None or clinic["vaccine_stock_count"] < appt["vaccine_doses"]:
            raise err("ERR_INSUFFICIENT_STOCK", "Insufficient vaccine stock")

    # Finalize estimate: APPROVED -> INVOICED, compute invoice_total_cents.
    invoice_cents = calc.invoice_total(
        estimate["line_items"],
        estimate["travel_surcharge_cents"],
        appt["vaccine_doses"],
    )
    estimate["invoice_total_cents"] = invoice_cents
    estimate["status"] = "INVOICED"
    models.touch(estimate)

    # Vaccine inventory cascade.
    if appt["visit_type"] == "VACCINE" and appt["vaccine_doses"] > 0 and clinic is not None:
        clinic["vaccine_stock_count"] = clinic["vaccine_stock_count"] - appt["vaccine_doses"]
        models.touch(clinic)

    # RouteStop ARRIVED -> SERVICED; recompute stop_count.
    if stop is not None:
        stop["status"] = "SERVICED"
        models.touch(stop)
    appt["status"] = "AWAITING_PAYMENT"
    models.touch(appt)
    if route_day is not None:
        services.recompute_stop_count(route_day)

    return success_object(models.public(appt))


@app.route("/appointments/<entity_id>/refer", methods=["POST"])
def appointment_refer(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    appt = fetch(db.appointments, entity_id)
    body = get_json_body()
    require_fields(body, ["hospital_name", "reason"])
    if appt["status"] not in ("REQUESTED", "SCHEDULED", "IN_VISIT"):
        raise err("ERR_INVALID_STATE", "Appointment cannot be referred from its state")
    if appt["visit_type"] == "EUTHANASIA":
        raise err("ERR_EUTHANASIA_NOT_REFERABLE", "Euthanasia appointment cannot be referred")
    hospital = body["hospital_name"]
    reason = body["reason"]
    if not isinstance(hospital, str) or not hospital:
        raise err("ERR_INVALID_REQUEST", "hospital_name must be a non-empty string")
    if not isinstance(reason, str) or not reason:
        raise err("ERR_INVALID_REQUEST", "reason must be a non-empty string")

    referral = models.stamp_new({
        "appointment_id": appt["id"],
        "hospital_name": hospital,
        "reason": reason,
        "status": "OPEN",
    })
    db.referrals[referral["id"]] = referral

    # Cascades.
    stop = services.linked_route_stop(appt["id"])
    route_day = None
    if stop is not None and stop["status"] not in ("SERVICED", "SKIPPED"):
        route_day = db.route_days[stop["route_day_id"]]
        stop["status"] = "SKIPPED"
        models.touch(stop)

    for est in services.estimates_for_appointment(appt["id"]):
        if est["status"] in ("DRAFT", "APPROVED"):
            est["status"] = "VOID"
            models.touch(est)

    # Clinician -> AVAILABLE only if it was ON_ROUTE for this appointment.
    if stop is not None:
        rd = db.route_days[stop["route_day_id"]]
        clinician = db.clinicians[rd["clinician_id"]]
        if clinician["status"] == "ON_ROUTE":
            clinician["status"] = "AVAILABLE"
            models.touch(clinician)

    appt["status"] = "REFERRED"
    models.touch(appt)

    if route_day is not None:
        services.recompute_stop_count(route_day)
        services.assign_sequence(route_day["id"])

    return success_object(models.public(referral), status=201)


@app.route("/appointments/<entity_id>/cancel", methods=["POST"])
def appointment_cancel(entity_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    appt = fetch(db.appointments, entity_id)
    if appt["status"] not in ("REQUESTED", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Appointment cannot be cancelled from its state")

    stop = services.linked_route_stop(appt["id"])
    route_day = None
    if stop is not None and stop["status"] == "PLANNED":
        route_day = db.route_days[stop["route_day_id"]]
        stop["status"] = "SKIPPED"
        models.touch(stop)

    for est in services.estimates_for_appointment(appt["id"]):
        if est["status"] in ("DRAFT", "APPROVED"):
            est["status"] = "VOID"
            models.touch(est)

    appt["status"] = "CANCELLED"
    models.touch(appt)

    if route_day is not None:
        services.recompute_stop_count(route_day)
        services.assign_sequence(route_day["id"])

    return success_object(models.public(appt))


@app.route("/appointments/<entity_id>/euthanasia-log", methods=["POST"])
def euthanasia_log_create(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    appt = fetch(db.appointments, entity_id)
    body = get_json_body()
    require_fields(body, ["rolling_clinic_id", "administering_vet_id", "entry_type", "amount_ml"])
    clinic = fetch(db.rolling_clinics, body["rolling_clinic_id"])
    admin_vet = fetch(db.clinicians, body["administering_vet_id"])
    entry_type = body["entry_type"]
    witness_id = body.get("witness_vet_id")
    witness_vet = None
    if witness_id is not None:
        witness_vet = fetch(db.clinicians, witness_id)

    check_enum(entry_type, {"DISPENSE", "WASTE"}, "entry_type")
    amount_ml = body["amount_ml"]
    if not is_number(amount_ml) or amount_ml <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_ml must be a number > 0")
    if entry_type == "WASTE" and witness_id is None:
        raise err("ERR_INVALID_REQUEST", "witness_vet_id required for WASTE entry")

    # DEA validity: administering party must be a VET with present, unexpired DEA.
    _require_valid_vet(admin_vet)
    if entry_type == "WASTE":
        _require_valid_vet(witness_vet)
        if witness_id == body["administering_vet_id"]:
            raise err("ERR_WITNESS_CONFLICT", "Witness must differ from administering vet")

    # Dose floor check for DISPENSE.
    if entry_type == "DISPENSE":
        patient = db.patients[appt["patient_id"]]
        required = calc.euthanasia_required_ml(patient["weight_kg"])
        if float(amount_ml) < required:
            raise err("ERR_DOSE_BELOW_MINIMUM", "DISPENSE amount_ml below required minimum")

    # Stock check.
    if clinic["controlled_stock_ml"] < amount_ml:
        raise err("ERR_INSUFFICIENT_STOCK", "Insufficient controlled stock")

    # Append immutable log entry (id + created_at only).
    ts = db.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "rolling_clinic_id": clinic["id"],
        "appointment_id": appt["id"],
        "administering_vet_id": admin_vet["id"],
        "witness_vet_id": witness_id,
        "entry_type": entry_type,
        "amount_ml": amount_ml,
        "_seq": db.seq(),
    }
    db.controlled_med_logs[rec["id"]] = rec

    # Decrement vehicle controlled stock.
    clinic["controlled_stock_ml"] = clinic["controlled_stock_ml"] - amount_ml
    models.touch(clinic)

    return success_object(models.public(rec), status=201)


def _require_valid_vet(clinician):
    if clinician["clinician_role"] != "VET":
        raise err("ERR_DEA_INVALID", "Controlled-med entry requires a VET")
    if not clinician.get("dea_number"):
        raise err("ERR_DEA_INVALID", "VET has no DEA number")
    expiry = clinician.get("dea_expires_on")
    if expiry is None:
        raise err("ERR_DEA_INVALID", "VET DEA expiry is unknown")
    expiry_dt = parse_dt(expiry, "dea_expires_on")
    if expiry_dt < clock.now():
        raise err("ERR_DEA_INVALID", "VET DEA registration is expired")


@app.route("/appointments/<entity_id>/euthanasia-log", methods=["GET"])
def euthanasia_log_list(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician", "ComplianceOfficer", "Dispatcher"])
    fetch(db.appointments, entity_id)
    pred = lambda l: l["appointment_id"] == entity_id
    return list_response(db.controlled_med_logs, pred)


# ===========================================================================
# RouteDay / RouteStop
# ===========================================================================
@app.route("/route-days", methods=["POST"])
def create_route_day():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_json_body()
    require_fields(body, ["clinician_id", "rolling_clinic_id", "service_date"])
    clinician = fetch(db.clinicians, body["clinician_id"])
    clinic = fetch(db.rolling_clinics, body["rolling_clinic_id"])
    service_date = parse_dt(body["service_date"], "service_date")

    rec = models.stamp_new({
        "clinician_id": clinician["id"],
        "rolling_clinic_id": clinic["id"],
        "service_date": iso_ts(service_date),
        "stop_count": 0,
        "posture": "OPEN",
    })
    rec["_controlled_stock_at_lock"] = None
    db.route_days[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/route-days", methods=["GET"])
def list_route_days():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    clinician_id = request.args.get("clinician_id")
    clinic_id = request.args.get("rolling_clinic_id")

    def pred(r):
        if clinician_id is not None and r["clinician_id"] != clinician_id:
            return False
        if clinic_id is not None and r["rolling_clinic_id"] != clinic_id:
            return False
        return True

    return list_response(db.route_days, pred)


@app.route("/route-days/<entity_id>", methods=["GET"])
def get_route_day(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.route_days, entity_id)
    return success_object(models.public(rec))


@app.route("/route-days/<route_day_id>/stops", methods=["POST"])
def create_route_stop(route_day_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    route_day = fetch(db.route_days, route_day_id)
    body = get_json_body()
    require_fields(body, ["appointment_id", "window_start", "window_end", "expected_route_day_version"])
    appt = fetch(db.appointments, body["appointment_id"])

    window_start = parse_dt(body["window_start"], "window_start")
    window_end = parse_dt(body["window_end"], "window_end")
    expected = body["expected_route_day_version"]

    # ----- State / posture / business-rule precedence (PRD §2.6, §3.3) -----
    # Appointment must be REQUESTED.
    if appt["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Appointment is not REQUESTED")
    # RouteDay must be OPEN.
    if route_day["posture"] != "OPEN":
        raise err("ERR_ROUTE_NOT_OPEN", "RouteDay is not OPEN")
    # Resolved ServiceArea for patient.home_zip must be ACTIVE.
    patient = db.patients[appt["patient_id"]]
    area = services.resolve_active_service_area(patient["home_zip"])
    if area is None:
        raise err("ERR_AREA_NOT_COVERED", "No ACTIVE ServiceArea covers the patient ZIP")
    # Euthanasia gates.
    if appt["visit_type"] == "EUTHANASIA":
        if not area["euthanasia_allowed"]:
            raise err("ERR_EUTHANASIA_NOT_PERMITTED", "Euthanasia not permitted in this area")
        clinician = db.clinicians[route_day["clinician_id"]]
        if clinician["clinician_role"] != "VET":
            raise err("ERR_VET_REQUIRED", "Euthanasia route requires a VET clinician")

    # Body well-formedness for the windows.
    if window_end <= window_start:
        raise err("ERR_INVALID_REQUEST", "window_end must be after window_start")
    if not is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_route_day_version must be an integer")

    # ----- Scheduling geometry -----
    _check_clinician_conflict(route_day, window_start, window_end)
    _check_vehicle_double_book(route_day, window_start, window_end)

    # ----- OCC -----
    if expected != route_day["version"]:
        raise err("ERR_STALE_ROUTE_DAY_VERSION", "Stale route day version")

    # ----- Commit -----
    stop = models.stamp_new({
        "route_day_id": route_day["id"],
        "appointment_id": appt["id"],
        "window_start": iso_ts(window_start),
        "window_end": iso_ts(window_end),
        "sequence": 0,
        "status": "PLANNED",
    })
    # internal raw datetimes for stable sequencing comparisons
    stop["_window_start_dt"] = window_start
    db.route_stops[stop["id"]] = stop

    appt["status"] = "SCHEDULED"
    models.touch(appt)

    # PRD §3.3: a successful booking recomputes stop_count, recomputes the
    # sequence of every stop, and "increments the route day's `version` by 1".
    # The whole booking bundle advances the route day version by exactly 1, so
    # the single recompute_stop_count touch below IS that increment; we do not
    # add a second redundant touch (which would advance version by 2).
    services.recompute_stop_count(route_day)
    services.assign_sequence(route_day["id"])

    return success_object(models.public(stop), status=201)


def _stop_window_dt(stop):
    from util import parse_dt as _p
    return (_p(stop["window_start"], "window_start"), _p(stop["window_end"], "window_end"))


def _check_clinician_conflict(route_day, new_start, new_end):
    """SAME RouteDay, buffered: touching conflicts (buffer 30 min)."""
    from datetime import timedelta
    buf = timedelta(minutes=calc.TRAVEL_BUFFER_MIN)
    for stop in services.stops_for_route(route_day["id"]):
        if stop["status"] == "SKIPPED":
            continue
        o_start, o_end = _stop_window_dt(stop)
        if new_start < (o_end + buf) and o_start < (new_end + buf):
            raise err("ERR_STOP_WINDOW_CONFLICT", "Stop window conflicts on the route")


def _check_vehicle_double_book(route_day, new_start, new_end):
    """ANY RouteDay sharing the vehicle on the same service_date, zero-buffer
    half-open overlap: touching at endpoints allowed.
    """
    vehicle_id = route_day["rolling_clinic_id"]
    service_date = route_day["service_date"]
    for other_rd in db.route_days.values():
        if other_rd["rolling_clinic_id"] != vehicle_id:
            continue
        if other_rd["service_date"] != service_date:
            continue
        for stop in services.stops_for_route(other_rd["id"]):
            if stop["status"] == "SKIPPED":
                continue
            o_start, o_end = _stop_window_dt(stop)
            if new_start < o_end and o_start < new_end:
                raise err("ERR_VEHICLE_DOUBLE_BOOKED", "Vehicle double-booked")


@app.route("/route-days/<route_day_id>/stops", methods=["GET"])
def list_route_day_stops(route_day_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    fetch(db.route_days, route_day_id)
    pred = lambda s: s["route_day_id"] == route_day_id
    return list_response(db.route_stops, pred)


@app.route("/route-stops", methods=["GET"])
def list_route_stops():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    appt_id = request.args.get("appointment_id")
    rd_id = request.args.get("route_day_id")

    def pred(s):
        if appt_id is not None and s["appointment_id"] != appt_id:
            return False
        if rd_id is not None and s["route_day_id"] != rd_id:
            return False
        return True

    return list_response(db.route_stops, pred)


@app.route("/route-stops/<entity_id>", methods=["GET"])
def get_route_stop(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.route_stops, entity_id)
    return success_object(models.public(rec))


@app.route("/route-days/<entity_id>/lock", methods=["POST"])
def lock_route_day(entity_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    route_day = fetch(db.route_days, entity_id)
    if route_day["posture"] != "OPEN":
        raise err("ERR_ROUTE_NOT_OPEN", "RouteDay is not OPEN")
    if route_day["stop_count"] < 1:
        raise err("ERR_ROUTE_EMPTY", "Cannot lock a RouteDay with no counted stops")
    clinic = db.rolling_clinics[route_day["rolling_clinic_id"]]
    if clinic["status"] == "MAINTENANCE":
        raise err("ERR_VEHICLE_UNAVAILABLE", "Assigned vehicle is in MAINTENANCE")

    # Snapshot the controlled stock at lock for later independent recount.
    route_day["_controlled_stock_at_lock"] = clinic["controlled_stock_ml"]
    route_day["posture"] = "LOCKED"
    models.touch(route_day)

    if clinic["status"] == "IN_DEPOT":
        clinic["status"] = "DEPLOYED"
        models.touch(clinic)

    clinician = db.clinicians[route_day["clinician_id"]]
    clinician["status"] = "ON_ROUTE"
    models.touch(clinician)

    return success_object(models.public(route_day))


@app.route("/route-days/<entity_id>/reconcile", methods=["POST"])
def reconcile_route_day(entity_id):
    _, role = authenticate()
    require_role(role, ["ComplianceOfficer"])
    route_day = fetch(db.route_days, entity_id)
    if route_day["posture"] != "LOCKED":
        raise err("ERR_ROUTE_NOT_OPEN", "RouteDay is not LOCKED")

    stops = services.stops_for_route(route_day["id"])
    for s in stops:
        if s["status"] not in ("SERVICED", "SKIPPED"):
            raise err("ERR_STOPS_OPEN", "Not all stops are in a terminal state")

    clinic = db.rolling_clinics[route_day["rolling_clinic_id"]]
    recount = services.reconcile_controlled_balance(route_day)
    running = round(float(clinic["controlled_stock_ml"]), 1)
    if abs(recount - running) > 1e-9:
        raise err("ERR_CONTROLLED_COUNT_MISMATCH", "Reconcile recount disagrees with running balance")

    clinic["controlled_reconciled_ml"] = recount
    models.touch(clinic)

    route_day["posture"] = "RECONCILED"
    models.touch(route_day)

    if clinic["status"] == "DEPLOYED":
        clinic["status"] = "IN_DEPOT"
        models.touch(clinic)

    clinician = db.clinicians[route_day["clinician_id"]]
    if clinician["status"] == "ON_ROUTE":
        clinician["status"] = "AVAILABLE"
        models.touch(clinician)

    return success_object(models.public(route_day))


# ===========================================================================
# Estimate
# ===========================================================================
def _validate_line_items(line_items):
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise err("ERR_INVALID_REQUEST", "line_items must be a non-empty array")
    for li in line_items:
        if not isinstance(li, dict):
            raise err("ERR_INVALID_REQUEST", "each line item must be an object")
        for f in ("code", "label", "unit_cents", "qty"):
            if f not in li or li[f] is None:
                raise err("ERR_INVALID_REQUEST", f"line item missing field: {f}")
        if not isinstance(li["code"], str) or not li["code"]:
            raise err("ERR_INVALID_REQUEST", "line item code must be a non-empty string")
        if not isinstance(li["label"], str):
            raise err("ERR_INVALID_REQUEST", "line item label must be a string")
        if not is_int(li["unit_cents"]):
            raise err("ERR_INVALID_REQUEST", "line item unit_cents must be an integer")
        if not is_number(li["qty"]) or li["qty"] < 0:
            raise err("ERR_INVALID_REQUEST", "line item qty must be a number >= 0")


@app.route("/estimates", methods=["POST"])
def create_estimate():
    _, role = authenticate()
    require_role(role, ["Clinician"])
    body = get_json_body()
    require_fields(body, ["appointment_id", "line_items"])
    appt = fetch(db.appointments, body["appointment_id"])
    line_items = body["line_items"]
    _validate_line_items(line_items)

    # Resolve service area for travel surcharge (must be ACTIVE for coverage).
    patient = db.patients[appt["patient_id"]]
    area = services.resolve_active_service_area(patient["home_zip"])
    if area is None:
        raise err("ERR_AREA_NOT_COVERED", "No ACTIVE ServiceArea covers the patient ZIP")
    surcharge = area["travel_surcharge_cents"]

    subtotal, total = calc.estimate_total(line_items, surcharge)
    rec = models.stamp_new({
        "appointment_id": appt["id"],
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "travel_surcharge_cents": surcharge,
        "estimate_total_cents": total,
        "invoice_total_cents": None,
        "status": "DRAFT",
    })
    db.estimates[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/estimates", methods=["GET"])
def list_estimates():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    appt_id = request.args.get("appointment_id")
    pred = (lambda r: r["appointment_id"] == appt_id) if appt_id is not None else None
    return list_response(db.estimates, pred)


@app.route("/estimates/<entity_id>", methods=["GET"])
def get_estimate(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.estimates, entity_id)
    return success_object(models.public(rec))


@app.route("/estimates/<entity_id>", methods=["PUT"])
def revise_estimate(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    est = fetch(db.estimates, entity_id)
    body = get_json_body()
    require_fields(body, ["line_items"])
    if est["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Estimate is not DRAFT")
    line_items = body["line_items"]
    _validate_line_items(line_items)

    subtotal, total = calc.estimate_total(line_items, est["travel_surcharge_cents"])
    est["line_items"] = line_items
    est["subtotal_cents"] = subtotal
    est["estimate_total_cents"] = total
    models.touch(est)
    return success_object(models.public(est))


@app.route("/estimates/<entity_id>/approve", methods=["POST"])
def approve_estimate(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    est = fetch(db.estimates, entity_id)
    if est["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Estimate is not DRAFT")
    appt = db.appointments[est["appointment_id"]]
    if appt["status"] not in ("SCHEDULED", "IN_VISIT"):
        raise err("ERR_APPT_NOT_IN_VISIT_PHASE", "Appointment is not in SCHEDULED or IN_VISIT")
    est["status"] = "APPROVED"
    models.touch(est)
    return success_object(models.public(est))


# ===========================================================================
# Payment
# ===========================================================================
@app.route("/payments", methods=["POST"])
def create_payment():
    _, role = authenticate()
    require_role(role, ["Clinician"])
    body = get_json_body()
    require_fields(body, ["estimate_id", "amount_cents", "method"])
    est = fetch(db.estimates, body["estimate_id"])
    amount = body["amount_cents"]
    method = body["method"]
    check_enum(method, {"CARD", "CASH", "CHECK"}, "method")
    if not is_int(amount) or amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be an integer > 0")

    appt = db.appointments[est["appointment_id"]]
    if appt["status"] != "AWAITING_PAYMENT":
        raise err("ERR_INVALID_STATE", "Appointment is not AWAITING_PAYMENT")
    if est["status"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "Estimate is not INVOICED")
    if amount != est["invoice_total_cents"]:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Payment amount must equal invoice total exactly")

    rec = models.stamp_new({
        "estimate_id": est["id"],
        "amount_cents": amount,
        "method": method,
        "status": "CAPTURED",
    })
    db.payments[rec["id"]] = rec

    appt["status"] = "COMPLETED"
    models.touch(appt)

    # Return clinician to AVAILABLE.
    stop = services.linked_route_stop(appt["id"])
    if stop is not None:
        rd = db.route_days[stop["route_day_id"]]
        clinician = db.clinicians[rd["clinician_id"]]
        clinician["status"] = "AVAILABLE"
        models.touch(clinician)

    return success_object(models.public(rec), status=201)


@app.route("/payments", methods=["GET"])
def list_payments():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    est_id = request.args.get("estimate_id")
    pred = (lambda r: r["estimate_id"] == est_id) if est_id is not None else None
    return list_response(db.payments, pred)


@app.route("/payments/<entity_id>", methods=["GET"])
def get_payment(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.payments, entity_id)
    return success_object(models.public(rec))


# ===========================================================================
# SpecimenPickup
# ===========================================================================
@app.route("/specimen-pickups", methods=["POST"])
def create_specimen_pickup():
    _, role = authenticate()
    require_role(role, ["Clinician"])
    body = get_json_body()
    require_fields(body, ["appointment_id", "specimen_type"])
    appt = fetch(db.appointments, body["appointment_id"])
    specimen_type = body["specimen_type"]
    check_enum(specimen_type, {"BLOOD", "URINE", "TISSUE"}, "specimen_type")

    rec = models.stamp_new({
        "appointment_id": appt["id"],
        "specimen_type": specimen_type,
        "status": "COLLECTED",
    })
    db.specimen_pickups[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/specimen-pickups", methods=["GET"])
def list_specimen_pickups():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    appt_id = request.args.get("appointment_id")
    pred = (lambda r: r["appointment_id"] == appt_id) if appt_id is not None else None
    return list_response(db.specimen_pickups, pred)


@app.route("/specimen-pickups/<entity_id>", methods=["GET"])
def get_specimen_pickup(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.specimen_pickups, entity_id)
    return success_object(models.public(rec))


@app.route("/specimen-pickups/<entity_id>/transit", methods=["POST"])
def specimen_transit(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    rec = fetch(db.specimen_pickups, entity_id)
    if rec["status"] != "COLLECTED":
        raise err("ERR_INVALID_STATE", "Specimen is not COLLECTED")
    rec["status"] = "IN_TRANSIT"
    models.touch(rec)
    return success_object(models.public(rec))


@app.route("/specimen-pickups/<entity_id>/deliver", methods=["POST"])
def specimen_deliver(entity_id):
    _, role = authenticate()
    require_role(role, ["Clinician"])
    rec = fetch(db.specimen_pickups, entity_id)
    if rec["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "Specimen is not IN_TRANSIT")
    rec["status"] = "DELIVERED"
    models.touch(rec)
    return success_object(models.public(rec))


# ===========================================================================
# WellnessPlan
# ===========================================================================
@app.route("/wellness-plans", methods=["POST"])
def create_wellness_plan():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_json_body()
    require_fields(body, ["patient_id", "interval_days", "anchor_date"])
    patient = fetch(db.patients, body["patient_id"])
    interval_days = body["interval_days"]
    if not is_int(interval_days) or interval_days < 1:
        raise err("ERR_INVALID_REQUEST", "interval_days must be an integer >= 1")
    anchor = parse_dt(body["anchor_date"], "anchor_date")

    nxt = calc.next_reminder(anchor, interval_days, clock.now())
    rec = models.stamp_new({
        "patient_id": patient["id"],
        "interval_days": interval_days,
        "anchor_date": iso_ts(anchor),
        "next_reminder_date": iso_ts(nxt),
        "status": "ACTIVE",
    })
    rec["_anchor_dt"] = anchor
    db.wellness_plans[rec["id"]] = rec
    return success_object(models.public(rec), status=201)


@app.route("/wellness-plans", methods=["GET"])
def list_wellness_plans():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    patient_id = request.args.get("patient_id")
    pred = (lambda r: r["patient_id"] == patient_id) if patient_id is not None else None
    return list_response(db.wellness_plans, pred)


@app.route("/wellness-plans/<entity_id>", methods=["GET"])
def get_wellness_plan(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.wellness_plans, entity_id)
    return success_object(models.public(rec))


@app.route("/wellness-plans/<entity_id>/pause", methods=["POST"])
def pause_wellness_plan(entity_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    rec = fetch(db.wellness_plans, entity_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "WellnessPlan is not ACTIVE")
    rec["status"] = "PAUSED"
    models.touch(rec)
    return success_object(models.public(rec))


@app.route("/wellness-plans/<entity_id>/resume", methods=["POST"])
def resume_wellness_plan(entity_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    rec = fetch(db.wellness_plans, entity_id)
    if rec["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "WellnessPlan is not PAUSED")
    anchor = rec.get("_anchor_dt") or parse_dt(rec["anchor_date"], "anchor_date")
    nxt = calc.next_reminder(anchor, rec["interval_days"], clock.now())
    rec["status"] = "ACTIVE"
    rec["next_reminder_date"] = iso_ts(nxt)
    models.touch(rec)
    return success_object(models.public(rec))


@app.route("/wellness-plans/<entity_id>/end", methods=["POST"])
def end_wellness_plan(entity_id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    rec = fetch(db.wellness_plans, entity_id)
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "WellnessPlan cannot be ended from its state")
    rec["status"] = "ENDED"
    models.touch(rec)
    return success_object(models.public(rec))


# ===========================================================================
# Referral
# ===========================================================================
@app.route("/referrals", methods=["GET"])
def list_referrals():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    appt_id = request.args.get("appointment_id")
    pred = (lambda r: r["appointment_id"] == appt_id) if appt_id is not None else None
    return list_response(db.referrals, pred)


@app.route("/referrals/<entity_id>", methods=["GET"])
def get_referral(entity_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch(db.referrals, entity_id)
    return success_object(models.public(rec))


@app.route("/referrals/<entity_id>/acknowledge", methods=["POST"])
def acknowledge_referral(entity_id):
    _, role = authenticate()
    require_role(role, ["ComplianceOfficer"])
    rec = fetch(db.referrals, entity_id)
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Referral is not OPEN")
    rec["status"] = "ACKNOWLEDGED"
    models.touch(rec)
    return success_object(models.public(rec))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
