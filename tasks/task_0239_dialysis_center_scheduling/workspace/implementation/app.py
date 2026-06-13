"""Dialysis Center Scheduling API — Flask entry point.

All endpoints mounted under root (flat topology). In-memory store, empty on boot.
Validation order strictly follows PRD §2.9.
"""
import os

from flask import Flask, request

import helpers as H
from cascades import (
    cancel_booked_session,
    cancel_session_transport,
    release_slot_cascade,
    revoke_order_cascade,
)
from db import db
from errors import ApiError
from middleware import require_auth, require_role
from response import error as err_response
from response import success
from serializers import serialize, serialize_list

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_INVALID_REQUEST", "Resource not found.", 400)


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_INVALID_REQUEST", "Method not allowed.", 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 400)


# ===========================================================================
# Lookup helpers (priority 3: path-resource existence)
# ===========================================================================
def _lookup(collection, rid, not_found_error):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError(not_found_error, "Resource '%s' not found." % rid)
    return rec


def get_clinic(cid):
    return _lookup(db.clinics, cid, "ERR_CLINIC_NOT_FOUND")


def get_patient(pid):
    return _lookup(db.patients, pid, "ERR_PATIENT_NOT_FOUND")


def get_shift(sid):
    return _lookup(db.shifts, sid, "ERR_SHIFT_NOT_FOUND")


def get_machine(mid):
    return _lookup(db.machines, mid, "ERR_MACHINE_NOT_FOUND")


def get_station(sid):
    return _lookup(db.stations, sid, "ERR_STATION_NOT_FOUND")


def get_order(oid):
    return _lookup(db.orders, oid, "ERR_ORDER_NOT_FOUND")


def get_slot(sid):
    return _lookup(db.standing_slots, sid, "ERR_SLOT_NOT_FOUND")


def get_session(sid):
    return _lookup(db.sessions, sid, "ERR_SESSION_NOT_FOUND")


def get_trip(tid):
    return _lookup(db.transport_trips, tid, "ERR_TRIP_NOT_FOUND")


def get_lab(lid):
    return _lookup(db.lab_orders, lid, "ERR_LAB_NOT_FOUND")


def get_statement(sid):
    return _lookup(db.statements, sid, "ERR_STATEMENT_NOT_FOUND")


def list_response(records, extra_filters=None):
    page, pagination = H.paginate(records)
    return success(serialize_list(page), status=200, pagination=pagination)


def filter_by(records, field, value):
    if value is None:
        return records
    return [r for r in records if r.get(field) == value]


# ===========================================================================
# CLINIC
# ===========================================================================
@app.route("/clinics", methods=["POST"])
def create_clinic():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    body = H.get_body()
    name = H.check_string(body, "name", required=True)
    time_zone = body.get("time_zone", "UTC")
    if time_zone is None:
        time_zone = "UTC"
    if not isinstance(time_zone, str) or time_zone == "":
        raise ApiError("ERR_INVALID_REQUEST", "time_zone must be a non-empty string.")
    reuse_limit = H.check_int(body, "dialyzer_reuse_limit", required=False, default=12, minimum=1)
    rec = {
        "name": name,
        "time_zone": time_zone,
        "dialyzer_reuse_limit": reuse_limit,
        "status": "OPEN",
    }
    db.stamp_create(rec)
    db.clinics[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/clinics", methods=["GET"])
def list_clinics():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return list_response(list(db.clinics.values()))


@app.route("/clinics/<clinic_id>", methods=["GET"])
def get_clinic_ep(clinic_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_clinic(clinic_id)), status=200)


def _clinic_occ(body, clinic):
    # expected_clinic_version is OPTIONAL on clinic transitions; not a patient OCC.
    if body and body.get("expected_clinic_version") is not None:
        ev = body.get("expected_clinic_version")
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise ApiError("ERR_INVALID_REQUEST", "expected_clinic_version must be an integer.")
        if ev != clinic["version"]:
            raise ApiError("ERR_STALE_PATIENT_VERSION", "Clinic version mismatch.")


@app.route("/clinics/<clinic_id>/suspend", methods=["POST"])
def suspend_clinic(clinic_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    clinic = get_clinic(clinic_id)
    body = H.get_body()
    if clinic["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Clinic must be OPEN to suspend.")
    _clinic_occ(body, clinic)
    clinic["status"] = "SUSPENDED"
    db.touch(clinic)
    return success(serialize(clinic), status=200)


@app.route("/clinics/<clinic_id>/resume", methods=["POST"])
def resume_clinic(clinic_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    clinic = get_clinic(clinic_id)
    body = H.get_body()
    if clinic["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Clinic must be SUSPENDED to resume.")
    _clinic_occ(body, clinic)
    clinic["status"] = "OPEN"
    db.touch(clinic)
    return success(serialize(clinic), status=200)


@app.route("/clinics/<clinic_id>/close", methods=["POST"])
def close_clinic(clinic_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    clinic = get_clinic(clinic_id)
    body = H.get_body()
    if clinic["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Clinic must be OPEN to close.")
    # precondition: no BOOKED/CHECKED_IN sessions in the clinic
    for s in db.sessions.values():
        if s["clinic_id"] == clinic_id and s["clinical_status"] in ("BOOKED", "CHECKED_IN"):
            raise ApiError("ERR_CLINIC_HAS_ACTIVE_SESSIONS",
                           "Clinic has active sessions and cannot be closed.")
    _clinic_occ(body, clinic)
    clinic["status"] = "CLOSED"
    db.touch(clinic)
    # Cascade L1: RESERVED slots -> RELEASED ; L2: their BOOKED sessions -> CANCELLED
    for slot in db.standing_slots.values():
        if slot["clinic_id"] == clinic_id and slot["status"] == "RESERVED":
            slot["status"] = "RELEASED"
            db.touch(slot)
            release_slot_cascade(slot)
    # Cascade L3: ACTIVE shifts -> RETIRED
    for shift in db.shifts.values():
        if shift["clinic_id"] == clinic_id and shift["status"] == "ACTIVE":
            shift["status"] = "RETIRED"
            db.touch(shift)
    return success(serialize(clinic), status=200)


# ===========================================================================
# SHIFT
# ===========================================================================
@app.route("/shifts", methods=["POST"])
def create_shift():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    body = H.get_body()
    clinic_id = H.check_string(body, "clinic_id", required=True)
    code = H.check_string(body, "code", required=True)
    day_pattern = H.check_enum(body, "day_pattern", H.DAY_PATTERNS, required=True)
    start_minute = H.check_int(body, "start_minute", required=True, minimum=0, maximum=1439)
    end_minute = H.check_int(body, "end_minute", required=True, minimum=1, maximum=1440)
    if end_minute <= start_minute:
        raise ApiError("ERR_INVALID_REQUEST", "end_minute must be > start_minute.")
    turnover = H.check_int(body, "turnover_buffer_minutes", required=False, default=45, minimum=0)
    # priority 4: FK existence + same-clinic (clinic itself is the referenced clinic)
    if clinic_id not in db.clinics:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "clinic_id does not exist.")
    rec = {
        "clinic_id": clinic_id,
        "code": code,
        "day_pattern": day_pattern,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "turnover_buffer_minutes": turnover,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.shifts[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/shifts", methods=["GET"])
def list_shifts():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = filter_by(list(db.shifts.values()), "clinic_id", request.args.get("clinic_id"))
    return list_response(recs)


@app.route("/shifts/<shift_id>", methods=["GET"])
def get_shift_ep(shift_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_shift(shift_id)), status=200)


@app.route("/shifts/<shift_id>/retire", methods=["POST"])
def retire_shift(shift_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    shift = get_shift(shift_id)
    if shift["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Shift must be ACTIVE to retire.")
    shift["status"] = "RETIRED"
    db.touch(shift)
    return success(serialize(shift), status=200)


# ===========================================================================
# MACHINE
# ===========================================================================
@app.route("/machines", methods=["POST"])
def create_machine():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    body = H.get_body()
    clinic_id = H.check_string(body, "clinic_id", required=True)
    asset_tag = H.check_string(body, "asset_tag", required=True)
    model = H.check_string(body, "model", required=True)
    supports_hdf = H.check_bool(body, "supports_hdf", default=False)
    if clinic_id not in db.clinics:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "clinic_id does not exist.")
    rec = {
        "clinic_id": clinic_id,
        "asset_tag": asset_tag,
        "model": model,
        "supports_hdf": supports_hdf,
        "dialyzer_reuse_count": 0,
        "status": "AVAILABLE",
    }
    db.stamp_create(rec)
    db.machines[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/machines", methods=["GET"])
def list_machines():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = filter_by(list(db.machines.values()), "clinic_id", request.args.get("clinic_id"))
    return list_response(recs)


@app.route("/machines/<machine_id>", methods=["GET"])
def get_machine_ep(machine_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_machine(machine_id)), status=200)


def _machine_has_active_session(machine_id, statuses):
    """True if any station bound to machine has a session in the given statuses."""
    station_ids = {st["id"] for st in db.stations.values() if st["machine_id"] == machine_id}
    for s in db.sessions.values():
        if s["station_id"] in station_ids and s["clinical_status"] in statuses:
            return True
    return False


@app.route("/machines/<machine_id>/start-maintenance", methods=["POST"])
def start_maintenance(machine_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    machine = get_machine(machine_id)
    if machine["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "Machine must be AVAILABLE to start maintenance.")
    if _machine_has_active_session(machine_id, ("CHECKED_IN",)):
        raise ApiError("ERR_MACHINE_IN_USE", "Machine has a CHECKED_IN session running.")
    machine["status"] = "IN_MAINTENANCE"
    db.touch(machine)
    return success(serialize(machine), status=200)


@app.route("/machines/<machine_id>/complete-maintenance", methods=["POST"])
def complete_maintenance(machine_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    machine = get_machine(machine_id)
    body = H.get_body()
    if machine["status"] != "IN_MAINTENANCE":
        raise ApiError("ERR_INVALID_STATE", "Machine must be IN_MAINTENANCE to complete maintenance.")
    disinfect = H.check_bool(body, "disinfect", default=False)
    machine["status"] = "AVAILABLE"
    if disinfect:
        machine["dialyzer_reuse_count"] = 0
    db.touch(machine)
    return success(serialize(machine), status=200)


@app.route("/machines/<machine_id>/retire", methods=["POST"])
def retire_machine(machine_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    machine = get_machine(machine_id)
    if machine["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "Machine must be AVAILABLE to retire.")
    if _machine_has_active_session(machine_id, ("BOOKED", "CHECKED_IN")):
        raise ApiError("ERR_MACHINE_IN_USE", "Machine has BOOKED/CHECKED_IN sessions on a bound station.")
    machine["status"] = "RETIRED"
    db.touch(machine)
    return success(serialize(machine), status=200)


# ===========================================================================
# STATION
# ===========================================================================
@app.route("/stations", methods=["POST"])
def create_station():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    body = H.get_body()
    clinic_id = H.check_string(body, "clinic_id", required=True)
    chair_label = H.check_string(body, "chair_label", required=True)
    machine_id = H.check_string(body, "machine_id", required=True)
    isolation_capable = H.check_bool(body, "isolation_capable", default=False)
    # priority 4: FK existence + same-clinic
    if clinic_id not in db.clinics:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "clinic_id does not exist.")
    machine = db.machines.get(machine_id)
    if machine is None or machine["clinic_id"] != clinic_id:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE",
                       "machine_id missing or belongs to a different clinic.")
    rec = {
        "clinic_id": clinic_id,
        "chair_label": chair_label,
        "machine_id": machine_id,
        "isolation_capable": isolation_capable,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.stations[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/stations", methods=["GET"])
def list_stations():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = list(db.stations.values())
    recs = filter_by(recs, "clinic_id", request.args.get("clinic_id"))
    recs = filter_by(recs, "machine_id", request.args.get("machine_id"))
    return list_response(recs)


@app.route("/stations/<station_id>", methods=["GET"])
def get_station_ep(station_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_station(station_id)), status=200)


@app.route("/stations/<station_id>/take-offline", methods=["POST"])
def take_station_offline(station_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    station = get_station(station_id)
    if station["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Station must be ACTIVE to take offline.")
    for s in db.sessions.values():
        if s["station_id"] == station_id and s["clinical_status"] in ("BOOKED", "CHECKED_IN"):
            raise ApiError("ERR_STATION_OCCUPIED", "Station has a BOOKED/CHECKED_IN session.")
    station["status"] = "OUT_OF_SERVICE"
    db.touch(station)
    return success(serialize(station), status=200)


@app.route("/stations/<station_id>/bring-online", methods=["POST"])
def bring_station_online(station_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    station = get_station(station_id)
    if station["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_STATE", "Station must be OUT_OF_SERVICE to bring online.")
    station["status"] = "ACTIVE"
    db.touch(station)
    return success(serialize(station), status=200)


# ===========================================================================
# PATIENT
# ===========================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler"})
    body = H.get_body()
    clinic_id = H.check_string(body, "clinic_id", required=True)
    mrn = H.check_string(body, "mrn", required=True)
    full_name = H.check_string(body, "full_name", required=True)
    patient_kind = H.check_enum(body, "patient_kind", H.PATIENT_KINDS, required=False, default="RESIDENT")
    payer_class = H.check_enum(body, "payer_class", H.PAYER_CLASSES, required=False, default="STANDARD")
    requires_isolation = H.check_bool(body, "requires_isolation", default=False)
    coinsurance_pct = H.check_number(body, "coinsurance_pct", required=False, default=0.0,
                                     minimum=0, maximum=1)
    if clinic_id not in db.clinics:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "clinic_id does not exist.")
    rec = {
        "clinic_id": clinic_id,
        "mrn": mrn,
        "full_name": full_name,
        "patient_kind": patient_kind,
        "payer_class": payer_class,
        "requires_isolation": requires_isolation,
        "coinsurance_pct": coinsurance_pct,
        "no_show_count_window": 0,
        "adherence_status": "GOOD_STANDING",
        "account_balance_cents": 0,
    }
    db.stamp_create(rec)
    db.patients[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/patients", methods=["GET"])
def list_patients():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = filter_by(list(db.patients.values()), "clinic_id", request.args.get("clinic_id"))
    return list_response(recs)


@app.route("/patients/<patient_id>", methods=["GET"])
def get_patient_ep(patient_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_patient(patient_id)), status=200)


@app.route("/patients/<patient_id>/adherence", methods=["GET"])
def get_adherence(patient_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    patient = get_patient(patient_id)
    return success(H.adherence_scores(patient), status=200)


@app.route("/patients/<patient_id>/reactivate", methods=["POST"])
def reactivate_patient(patient_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    patient = get_patient(patient_id)
    if patient["adherence_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Patient must be SUSPENDED to reactivate.")
    # Override adherence_status only; do NOT clear no_show_count_window.
    patient["adherence_status"] = "GOOD_STANDING"
    db.touch(patient)
    return success(serialize(patient), status=200)


# ===========================================================================
# NEPHROLOGIST ORDER
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    _, role = require_auth()
    require_role(role, {"Nephrologist"})
    body = H.get_body()
    patient_id = H.check_string(body, "patient_id", required=True)
    modality = H.check_enum(body, "modality", H.MODALITIES, required=True)
    sessions_per_week = H.check_int(body, "sessions_per_week", required=False, default=3,
                                    minimum=1, maximum=3)
    epo_units = H.check_int(body, "epo_units", required=False, default=0, minimum=0)
    iron_ordered = H.check_bool(body, "iron_ordered", default=False)
    effective_from_date = H.check_iso_date(body, "effective_from_date", required=True)
    # priority 4: FK existence (patient)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "patient_id does not exist.")
    rec = {
        "patient_id": patient_id,
        "clinic_id": patient["clinic_id"],
        "modality": modality,
        "sessions_per_week": sessions_per_week,
        "epo_units": epo_units,
        "iron_ordered": iron_ordered,
        "effective_from_date": effective_from_date,
        "revision_no": 0,
        "status": "DRAFT",
    }
    db.stamp_create(rec)
    db.orders[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/orders", methods=["GET"])
def list_orders():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = list(db.orders.values())
    recs = filter_by(recs, "patient_id", request.args.get("patient_id"))
    recs = filter_by(recs, "clinic_id", request.args.get("clinic_id"))
    return list_response(recs)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order_ep(order_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_order(order_id)), status=200)


@app.route("/orders/<order_id>/activate", methods=["POST"])
def activate_order(order_id):
    _, role = require_auth()
    require_role(role, {"Nephrologist"})
    order = get_order(order_id)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Order must be DRAFT to activate.")
    # precondition: patient has no other ACTIVE order
    for o in db.orders.values():
        if o["patient_id"] == order["patient_id"] and o["id"] != order_id and o["status"] == "ACTIVE":
            raise ApiError("ERR_ACTIVE_ORDER_EXISTS", "Patient already has an ACTIVE order.")
    order["status"] = "ACTIVE"
    order["revision_no"] = 1
    db.touch(order)
    return success(serialize(order), status=200)


@app.route("/orders/<order_id>/open-revision", methods=["POST"])
def open_revision(order_id):
    _, role = require_auth()
    require_role(role, {"Nephrologist"})
    order = get_order(order_id)
    if order["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Order must be ACTIVE to open a revision.")
    order["status"] = "UNDER_REVISION"
    db.touch(order)
    return success(serialize(order), status=200)


@app.route("/orders/<order_id>/commit-revision", methods=["POST"])
def commit_revision(order_id):
    _, role = require_auth()
    require_role(role, {"Nephrologist"})
    order = get_order(order_id)
    body = H.get_body()
    if order["status"] != "UNDER_REVISION":
        raise ApiError("ERR_INVALID_STATE", "Order must be UNDER_REVISION to commit a revision.")
    # Apply submitted changes (all optional)
    if "modality" in body and body["modality"] is not None:
        order["modality"] = H.check_enum(body, "modality", H.MODALITIES, required=True)
    if "sessions_per_week" in body and body["sessions_per_week"] is not None:
        order["sessions_per_week"] = H.check_int(body, "sessions_per_week", required=True,
                                                 minimum=1, maximum=3)
    if "epo_units" in body and body["epo_units"] is not None:
        order["epo_units"] = H.check_int(body, "epo_units", required=True, minimum=0)
    if "iron_ordered" in body and body["iron_ordered"] is not None:
        order["iron_ordered"] = H.check_bool(body, "iron_ordered", default=False)
    order["status"] = "ACTIVE"
    order["revision_no"] = order["revision_no"] + 1
    db.touch(order)
    return success(serialize(order), status=200)


@app.route("/orders/<order_id>/revoke", methods=["POST"])
def revoke_order(order_id):
    _, role = require_auth()
    require_role(role, {"Nephrologist"})
    order = get_order(order_id)
    if order["status"] not in ("ACTIVE", "UNDER_REVISION"):
        raise ApiError("ERR_INVALID_STATE", "Order must be ACTIVE or UNDER_REVISION to revoke.")
    order["status"] = "REVOKED"
    db.touch(order)
    revoke_order_cascade(order)
    return success(serialize(order), status=200)


# ===========================================================================
# STANDING SLOT
# ===========================================================================
def _active_order_for_patient(patient_id):
    for o in db.orders.values():
        if o["patient_id"] == patient_id and o["status"] == "ACTIVE":
            return o
    return None


@app.route("/standing-slots", methods=["POST"])
def create_standing_slot():
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    body = H.get_body()
    # Field presence first for the references we will resolve at priority 4.
    patient_id = H.check_string(body, "patient_id", required=True)
    shift_id = H.check_string(body, "shift_id", required=True)
    station_id = H.check_string(body, "station_id", required=True)
    if "expected_patient_version" not in body or body["expected_patient_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field 'expected_patient_version'.")

    # priority 4: FK existence + same-clinic
    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "patient_id does not exist.")
    clinic_id = patient["clinic_id"]
    shift = db.shifts.get(shift_id)
    if shift is None or shift["clinic_id"] != clinic_id:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "shift_id missing or cross-clinic.")
    station = db.stations.get(station_id)
    if station is None or station["clinic_id"] != clinic_id:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "station_id missing or cross-clinic.")

    clinic = db.clinics.get(clinic_id)
    # priority 5: clinic OPEN
    if clinic is None or clinic["status"] != "OPEN":
        raise ApiError("ERR_CLINIC_SUSPENDED", "Clinic is not OPEN.")

    # priority 7: authorizing order ACTIVE and governs the date
    order = _active_order_for_patient(patient_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_ACTIVE", "No ACTIVE order for the patient.")

    # priority 9: isolation suitability
    if patient["requires_isolation"] and not station["isolation_capable"]:
        raise ApiError("ERR_ISOLATION_STATION_REQUIRED", "Station is not isolation-capable.")

    # priority 12: station-cell double-booking (slot reserves the cell on each occurrence)
    _check_slot_double_booking(station_id, shift_id, patient_id)

    # priority 15: standing slot only for RESIDENT
    if patient["patient_kind"] != "RESIDENT":
        raise ApiError("ERR_TRANSIENT_NO_STANDING_SLOT", "Standing slots require a RESIDENT patient.")

    # priority 16: field-level (validated above)

    # priority 17: OCC
    ev = body["expected_patient_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expected_patient_version must be an integer.")
    if ev != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION", "expected_patient_version does not match.")

    rec = {
        "patient_id": patient_id,
        "clinic_id": clinic_id,
        "shift_id": shift_id,
        "station_id": station_id,
        "status": "RESERVED",
    }
    db.stamp_create(rec)
    db.standing_slots[rec["id"]] = rec
    # successful reservation bumps patient.version
    db.touch(patient)
    return success(serialize(rec), status=201)


def _check_slot_double_booking(station_id, shift_id, patient_id):
    """A RESERVED standing slot occupies (station, shift) on every day_pattern
    occurrence. Reject if another RESERVED slot already holds the same cell.
    """
    for slot in db.standing_slots.values():
        if slot["status"] != "RESERVED":
            continue
        if slot["station_id"] == station_id and slot["shift_id"] == shift_id:
            raise ApiError("ERR_STATION_DOUBLE_BOOKED",
                           "Station/shift cell already reserved by a standing slot.")


@app.route("/standing-slots", methods=["GET"])
def list_standing_slots():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = list(db.standing_slots.values())
    recs = filter_by(recs, "patient_id", request.args.get("patient_id"))
    recs = filter_by(recs, "clinic_id", request.args.get("clinic_id"))
    recs = filter_by(recs, "shift_id", request.args.get("shift_id"))
    recs = filter_by(recs, "station_id", request.args.get("station_id"))
    return list_response(recs)


@app.route("/standing-slots/<slot_id>", methods=["GET"])
def get_slot_ep(slot_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_slot(slot_id)), status=200)


@app.route("/standing-slots/<slot_id>/release", methods=["POST"])
def release_slot(slot_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    slot = get_slot(slot_id)
    if slot["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", "Slot must be RESERVED to release.")
    slot["status"] = "RELEASED"
    db.touch(slot)
    release_slot_cascade(slot)
    return success(serialize(slot), status=200)


# ===========================================================================
# TREATMENT SESSION
# ===========================================================================
def _session_occupies_cell(station_id, shift_id, service_date, exclude_id=None):
    """Any non-CANCELLED/non-MISSED session occupying the exact (station, shift, date) cell."""
    for s in db.sessions.values():
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["clinical_status"] in ("CANCELLED", "MISSED"):
            continue
        if (s["station_id"] == station_id and s["shift_id"] == shift_id
                and s["service_date"] == service_date):
            return True
    return False


def _turnover_violation(station, shift, service_date):
    """Two non-terminal sessions sharing the SAME machine on the same date must
    respect the earlier shift's turnover buffer (buffered half-open adjacency).
    Returns True if the proposed booking violates the buffer against any existing
    non-terminal session on a station bound to the same machine.
    """
    machine_id = station["machine_id"]
    new_start = shift["start_minute"]
    new_end = shift["end_minute"]
    new_buf = shift["turnover_buffer_minutes"]
    for s in db.sessions.values():
        if s["clinical_status"] in ("CANCELLED", "MISSED", "COMPLETED"):
            # non-terminal only: BOOKED, CHECKED_IN
            continue
        if s["service_date"] != service_date:
            continue
        other_station = db.stations.get(s["station_id"])
        if other_station is None or other_station["machine_id"] != machine_id:
            continue
        other_shift = db.shifts.get(s["shift_id"])
        if other_shift is None:
            continue
        o_start = other_shift["start_minute"]
        o_end = other_shift["end_minute"]
        o_buf = other_shift["turnover_buffer_minutes"]
        # Determine ordering by start_minute; earlier must finish + buffer before later starts.
        if new_start >= o_start:
            earlier_end, earlier_buf, later_start = o_end, o_buf, new_start
        else:
            earlier_end, earlier_buf, later_start = new_end, new_buf, o_start
        if not (earlier_end + earlier_buf <= later_start):
            return True
    return False


@app.route("/sessions", methods=["POST"])
def create_session():
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    body = H.get_body()
    patient_id = H.check_string(body, "patient_id", required=True)
    order_id = H.check_string(body, "order_id", required=True)
    station_id = H.check_string(body, "station_id", required=True)
    shift_id = H.check_string(body, "shift_id", required=True)
    service_date = H.check_iso_date(body, "service_date", required=True)
    standing_slot_id = H.check_string(body, "standing_slot_id", required=False)
    rescheduled_from_id = H.check_string(body, "rescheduled_from_id", required=False)
    if "expected_patient_version" not in body or body["expected_patient_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field 'expected_patient_version'.")

    # priority 4: FK existence + same-clinic for all body FKs
    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "patient_id does not exist.")
    clinic_id = patient["clinic_id"]
    order = db.orders.get(order_id)
    if order is None or order["clinic_id"] != clinic_id:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "order_id missing or cross-clinic.")
    station = db.stations.get(station_id)
    if station is None or station["clinic_id"] != clinic_id:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "station_id missing or cross-clinic.")
    shift = db.shifts.get(shift_id)
    if shift is None or shift["clinic_id"] != clinic_id:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "shift_id missing or cross-clinic.")
    if standing_slot_id is not None:
        slot = db.standing_slots.get(standing_slot_id)
        if slot is None or slot["clinic_id"] != clinic_id:
            raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "standing_slot_id missing or cross-clinic.")
    if rescheduled_from_id is not None:
        prior = db.sessions.get(rescheduled_from_id)
        if prior is None or prior["clinic_id"] != clinic_id:
            raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "rescheduled_from_id missing or cross-clinic.")

    clinic = db.clinics.get(clinic_id)
    # priority 5: clinic OPEN
    if clinic is None or clinic["status"] != "OPEN":
        raise ApiError("ERR_CLINIC_SUSPENDED", "Clinic is not OPEN.")

    # priority 7: authorizing order ACTIVE + governs date (effective_from_date <= service_date)
    if order["status"] != "ACTIVE":
        raise ApiError("ERR_ORDER_NOT_ACTIVE", "Authorizing order is not ACTIVE.")
    if H.parse_service_date(service_date) < H.parse_service_date(order["effective_from_date"]):
        raise ApiError("ERR_ORDER_NOT_ACTIVE", "Order does not govern the service_date.")

    # priority 8: service_date weekday on shift day_pattern
    weekday = H.parse_service_date(service_date).weekday()
    if weekday not in H.PATTERN_WEEKDAYS[shift["day_pattern"]]:
        raise ApiError("ERR_DATE_NOT_ON_PATTERN", "service_date is not on the shift day pattern.")

    # priority 9: isolation suitability
    if patient["requires_isolation"] and not station["isolation_capable"]:
        raise ApiError("ERR_ISOLATION_STATION_REQUIRED", "Station is not isolation-capable.")

    # priority 10: HDF support
    if order["modality"] == "HEMODIAFILTRATION":
        machine = db.machines.get(station["machine_id"])
        if machine is None or not machine.get("supports_hdf", False):
            raise ApiError("ERR_MODALITY_NOT_SUPPORTED", "Station machine does not support HDF.")

    # priority 12: station-cell double-booking
    if _session_occupies_cell(station_id, shift_id, service_date):
        raise ApiError("ERR_STATION_DOUBLE_BOOKED", "Station/shift/date cell already occupied.")
    # standing slots reserve the cell on every day_pattern occurrence
    for slot in db.standing_slots.values():
        if (slot["status"] == "RESERVED" and slot["station_id"] == station_id
                and slot["shift_id"] == shift_id):
            # the standing slot blocks any other patient's session on this cell
            if slot["patient_id"] != patient_id:
                raise ApiError("ERR_STATION_DOUBLE_BOOKED",
                               "Cell reserved by a standing slot for another patient.")

    # priority 13: machine turnover buffer overlap
    if _turnover_violation(station, shift, service_date):
        raise ApiError("ERR_TURNOVER_BUFFER_VIOLATION", "Machine turnover buffer violated.")

    # priority 14: ad-hoc/transient booking blocked if patient SUSPENDED
    if standing_slot_id is None and patient["adherence_status"] == "SUSPENDED":
        raise ApiError("ERR_PATIENT_SUSPENDED", "Patient is adherence-suspended for ad-hoc booking.")

    # priority 17: OCC
    ev = body["expected_patient_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expected_patient_version must be an integer.")
    if ev != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION", "expected_patient_version does not match.")

    rec = {
        "patient_id": patient_id,
        "clinic_id": clinic_id,
        "order_id": order_id,
        "station_id": station_id,
        "shift_id": shift_id,
        "standing_slot_id": standing_slot_id,
        "rescheduled_from_id": rescheduled_from_id,
        "service_date": service_date,
        "billed_amount_cents": 0,
        "missed_fee_cents": 0,
        "clinical_status": "BOOKED",
        "billing_status": "UNBILLED",
    }
    db.stamp_create(rec)
    db.sessions[rec["id"]] = rec
    db.touch(patient)
    return success(serialize(rec), status=201)


@app.route("/sessions", methods=["GET"])
def list_sessions():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = list(db.sessions.values())
    for field in ("patient_id", "order_id", "station_id", "shift_id",
                  "standing_slot_id", "rescheduled_from_id", "clinic_id"):
        recs = filter_by(recs, field, request.args.get(field))
    return list_response(recs)


@app.route("/sessions/<session_id>", methods=["GET"])
def get_session_ep(session_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_session(session_id)), status=200)


@app.route("/sessions/<session_id>/check-in", methods=["POST"])
def check_in_session(session_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    session = get_session(session_id)
    if session["clinical_status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", "Session must be BOOKED to check in.")
    station = db.stations.get(session["station_id"])
    machine = db.machines.get(station["machine_id"]) if station else None
    if machine is None or machine["status"] != "AVAILABLE":
        raise ApiError("ERR_MACHINE_UNAVAILABLE", "Station machine is not AVAILABLE.")
    if station["status"] != "ACTIVE":
        raise ApiError("ERR_STATION_OFFLINE", "Station is not ACTIVE.")
    session["clinical_status"] = "CHECKED_IN"
    db.touch(session)
    return success(serialize(session), status=200)


@app.route("/sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    session = get_session(session_id)
    if session["clinical_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", "Session must be CHECKED_IN to complete.")
    order = db.orders.get(session["order_id"])
    patient = db.patients.get(session["patient_id"])
    station = db.stations.get(session["station_id"])
    machine = db.machines.get(station["machine_id"]) if station else None
    modality = order["modality"]
    # priority 11: dialyzer reuse headroom for HD/HDF
    if modality in ("HEMODIALYSIS", "HEMODIAFILTRATION"):
        clinic = db.clinics.get(session["clinic_id"])
        if machine is None or machine["dialyzer_reuse_count"] >= clinic["dialyzer_reuse_limit"]:
            raise ApiError("ERR_DIALYZER_REUSE_EXCEEDED", "Dialyzer reuse limit reached.")
    # compute charge
    billed = H.session_charge(order, patient)
    session["billed_amount_cents"] = billed
    session["clinical_status"] = "COMPLETED"
    db.touch(session)
    # ledger: += coinsurance share (per-session rounding)
    patient["account_balance_cents"] += H.coinsurance_cents(billed, patient)
    db.touch(patient)
    # dialyzer reuse increment for HD/HDF
    if modality in ("HEMODIALYSIS", "HEMODIAFILTRATION") and machine is not None:
        machine["dialyzer_reuse_count"] += 1
        db.touch(machine)
    return success(serialize(session), status=200)


@app.route("/sessions/<session_id>/mark-missed", methods=["POST"])
def mark_missed_session(session_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    session = get_session(session_id)
    if session["clinical_status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", "Session must be BOOKED to mark missed.")
    patient = db.patients.get(session["patient_id"])
    session["missed_fee_cents"] = H.MISSED_FEE_CENTS
    session["clinical_status"] = "MISSED"
    db.touch(session)
    patient["account_balance_cents"] += H.MISSED_FEE_CENTS
    # recompute no-show window + adherence escalation
    H.recompute_adherence(patient)
    db.touch(patient)
    # cancel transport on this session (reverse confirmed fares)
    cancel_session_transport(session)
    return success(serialize(session), status=200)


@app.route("/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    session = get_session(session_id)
    if session["clinical_status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", "Session must be BOOKED to cancel.")
    session["clinical_status"] = "CANCELLED"
    db.touch(session)
    cancel_session_transport(session)
    return success(serialize(session), status=200)


@app.route("/sessions/<session_id>/bill", methods=["POST"])
def bill_session(session_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    session = get_session(session_id)
    if session["billing_status"] != "UNBILLED":
        raise ApiError("ERR_INVALID_STATE", "Session billing must be UNBILLED to bill.")
    if session["clinical_status"] != "COMPLETED":
        raise ApiError("ERR_SESSION_NOT_COMPLETED", "Session must be COMPLETED to bill.")
    session["billing_status"] = "BILLED"
    db.touch(session)
    return success(serialize(session), status=200)


@app.route("/sessions/<session_id>/settle", methods=["POST"])
def settle_session(session_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    session = get_session(session_id)
    if session["billing_status"] != "BILLED":
        raise ApiError("ERR_INVALID_STATE", "Session billing must be BILLED to settle.")
    patient = db.patients.get(session["patient_id"])
    session["billing_status"] = "SETTLED"
    db.touch(session)
    patient["account_balance_cents"] -= H.coinsurance_cents(session["billed_amount_cents"], patient)
    db.touch(patient)
    return success(serialize(session), status=200)


@app.route("/sessions/<session_id>/void-billing", methods=["POST"])
def void_billing(session_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    session = get_session(session_id)
    if session["billing_status"] != "UNBILLED":
        raise ApiError("ERR_INVALID_STATE", "Session billing must be UNBILLED to void.")
    if session["clinical_status"] not in ("CANCELLED", "MISSED"):
        raise ApiError("ERR_SESSION_NOT_VOIDABLE", "Session must be CANCELLED or MISSED to void billing.")
    session["billing_status"] = "VOID"
    db.touch(session)
    return success(serialize(session), status=200)


# ===========================================================================
# TRANSPORT TRIP
# ===========================================================================
@app.route("/transport-trips", methods=["POST"])
def create_trip():
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    body = H.get_body()
    session_id = H.check_string(body, "session_id", required=True)
    direction = H.check_enum(body, "direction", H.DIRECTIONS, required=True)
    miles = H.check_number(body, "miles", required=True, minimum=0)
    cross_county = H.check_bool(body, "cross_county", default=False)
    wheelchair = H.check_bool(body, "wheelchair", default=False)
    shared_ride = H.check_bool(body, "shared_ride", default=False)
    # priority 4: FK existence (session)
    session = db.sessions.get(session_id)
    if session is None:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "session_id does not exist.")
    fare = H.transport_fare(miles, cross_county, wheelchair, shared_ride)
    rec = {
        "session_id": session_id,
        "patient_id": session["patient_id"],
        "direction": direction,
        "miles": miles,
        "cross_county": cross_county,
        "wheelchair": wheelchair,
        "shared_ride": shared_ride,
        "fare_cents": fare,
        "status": "REQUESTED",
    }
    db.stamp_create(rec)
    db.transport_trips[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/transport-trips", methods=["GET"])
def list_trips():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = list(db.transport_trips.values())
    recs = filter_by(recs, "session_id", request.args.get("session_id"))
    recs = filter_by(recs, "patient_id", request.args.get("patient_id"))
    return list_response(recs)


@app.route("/transport-trips/<trip_id>", methods=["GET"])
def get_trip_ep(trip_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_trip(trip_id)), status=200)


@app.route("/transport-trips/<trip_id>/confirm", methods=["POST"])
def confirm_trip(trip_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    trip = get_trip(trip_id)
    if trip["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Trip must be REQUESTED to confirm.")
    session = db.sessions.get(trip["session_id"])
    if session is None or session["clinical_status"] not in ("BOOKED", "CHECKED_IN"):
        raise ApiError("ERR_SESSION_NOT_SCHEDULABLE", "Owning session is not schedulable.")
    trip["status"] = "CONFIRMED"
    db.touch(trip)
    patient = db.patients.get(trip["patient_id"])
    if patient is not None:
        patient["account_balance_cents"] += trip["fare_cents"]
        db.touch(patient)
    return success(serialize(trip), status=200)


@app.route("/transport-trips/<trip_id>/complete", methods=["POST"])
def complete_trip(trip_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    trip = get_trip(trip_id)
    if trip["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Trip must be CONFIRMED to complete.")
    session = db.sessions.get(trip["session_id"])
    if session is None or session["clinical_status"] != "COMPLETED":
        raise ApiError("ERR_SESSION_NOT_COMPLETED", "Owning session is not COMPLETED.")
    trip["status"] = "COMPLETED"
    db.touch(trip)
    return success(serialize(trip), status=200)


@app.route("/transport-trips/<trip_id>/cancel", methods=["POST"])
def cancel_trip(trip_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    trip = get_trip(trip_id)
    if trip["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Trip must be REQUESTED or CONFIRMED to cancel.")
    was_confirmed = trip["status"] == "CONFIRMED"
    trip["status"] = "CANCELLED"
    db.touch(trip)
    if was_confirmed:
        patient = db.patients.get(trip["patient_id"])
        if patient is not None:
            patient["account_balance_cents"] -= trip["fare_cents"]
            db.touch(patient)
    return success(serialize(trip), status=200)


# ===========================================================================
# LAB ORDER
# ===========================================================================
@app.route("/lab-orders", methods=["POST"])
def create_lab():
    _, role = require_auth()
    require_role(role, {"Nephrologist", "Scheduler"})
    body = H.get_body()
    patient_id = H.check_string(body, "patient_id", required=True)
    panel = H.check_enum(body, "panel", H.PANELS, required=True)
    scheduled_date = H.check_iso_date(body, "scheduled_date", required=True)
    # priority 4: FK existence (patient)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "patient_id does not exist.")
    clinic = db.clinics.get(patient["clinic_id"])
    # priority 5: clinic OPEN
    if clinic is None or clinic["status"] != "OPEN":
        raise ApiError("ERR_CLINIC_SUSPENDED", "Clinic is not OPEN.")
    rec = {
        "patient_id": patient_id,
        "clinic_id": patient["clinic_id"],
        "panel": panel,
        "scheduled_date": scheduled_date,
        "status": "SCHEDULED",
    }
    db.stamp_create(rec)
    db.lab_orders[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/lab-orders", methods=["GET"])
def list_labs():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = list(db.lab_orders.values())
    recs = filter_by(recs, "patient_id", request.args.get("patient_id"))
    recs = filter_by(recs, "clinic_id", request.args.get("clinic_id"))
    return list_response(recs)


@app.route("/lab-orders/<lab_id>", methods=["GET"])
def get_lab_ep(lab_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_lab(lab_id)), status=200)


@app.route("/lab-orders/<lab_id>/collect", methods=["POST"])
def collect_lab(lab_id):
    _, role = require_auth()
    require_role(role, {"Scheduler"})
    lab = get_lab(lab_id)
    if lab["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Lab must be SCHEDULED to collect.")
    lab["status"] = "COLLECTED"
    db.touch(lab)
    return success(serialize(lab), status=200)


@app.route("/lab-orders/<lab_id>/cancel", methods=["POST"])
def cancel_lab(lab_id):
    _, role = require_auth()
    require_role(role, {"Scheduler", "Nephrologist"})
    lab = get_lab(lab_id)
    if lab["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Lab must be SCHEDULED to cancel.")
    lab["status"] = "CANCELLED"
    db.touch(lab)
    return success(serialize(lab), status=200)


# ===========================================================================
# MONTHLY STATEMENT
# ===========================================================================
def _service_date_in_month(service_date, period_month):
    return isinstance(service_date, str) and service_date[:7] == period_month


@app.route("/statements", methods=["POST"])
def create_statement():
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    body = H.get_body()
    patient_id = H.check_string(body, "patient_id", required=True)
    period_month = H.check_iso_month(body, "period_month", required=True)
    # priority 4: FK existence (patient)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_CROSS_CLINIC_REFERENCE", "patient_id does not exist.")
    # rollup (statement_rollup)
    coinsurance_due = 0
    session_count = 0
    missed_fee_total = 0
    for s in db.sessions.values():
        if s["patient_id"] != patient_id:
            continue
        if not _service_date_in_month(s["service_date"], period_month):
            continue
        if s["clinical_status"] == "COMPLETED" and s["billing_status"] == "BILLED":
            session_count += 1
            coinsurance_due += H.coinsurance_cents(s["billed_amount_cents"], patient)
        if s["clinical_status"] == "MISSED":
            missed_fee_total += s["missed_fee_cents"]
    total_due = coinsurance_due + missed_fee_total
    rec = {
        "patient_id": patient_id,
        "clinic_id": patient["clinic_id"],
        "period_month": period_month,
        "session_count": session_count,
        "coinsurance_due_cents": coinsurance_due,
        "missed_fee_total_cents": missed_fee_total,
        "total_due_cents": total_due,
        "status": "ISSUED",
    }
    db.stamp_create(rec)
    db.statements[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/statements", methods=["GET"])
def list_statements():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    recs = list(db.statements.values())
    recs = filter_by(recs, "patient_id", request.args.get("patient_id"))
    recs = filter_by(recs, "clinic_id", request.args.get("clinic_id"))
    return list_response(recs)


@app.route("/statements/<statement_id>", methods=["GET"])
def get_statement_ep(statement_id):
    _, role = require_auth()
    require_role(role, {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"})
    return success(serialize(get_statement(statement_id)), status=200)


@app.route("/statements/<statement_id>/pay", methods=["POST"])
def pay_statement(statement_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    statement = get_statement(statement_id)
    if statement["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Statement must be ISSUED to pay.")
    statement["status"] = "PAID"
    db.touch(statement)
    patient = db.patients.get(statement["patient_id"])
    if patient is not None:
        patient["account_balance_cents"] -= statement["total_due_cents"]
        db.touch(patient)
    return success(serialize(statement), status=200)


@app.route("/statements/<statement_id>/cancel", methods=["POST"])
def cancel_statement(statement_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    statement = get_statement(statement_id)
    if statement["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Statement must be ISSUED to cancel.")
    statement["status"] = "CANCELLED"
    db.touch(statement)
    return success(serialize(statement), status=200)


# ===========================================================================
# CLOCK (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, {"ClinicAdmin"})
    body = H.get_body()
    to_iso = H.check_string(body, "to_iso8601", required=True)
    # validate parseable instant
    try:
        H._parse_instant(to_iso)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    db.clock_now = to_iso
    # recompute every patient's no-show window + adherence
    for patient in db.patients.values():
        before = patient["adherence_status"]
        H.recompute_adherence(patient)
        if patient["adherence_status"] != before:
            db.touch(patient)
    return success({"now": db.clock_now}, status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
