"""Routes for facilities, ORs, recovery bays, anesthesiologists, surgeons,
procedures, supply items, patients (PRD §3.1, §3.2)."""
from flask import Blueprint

from db import db, stamp_common, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_response
from services.helpers import (
    lookup, get_body, require_str, require_int, require_positive_int,
    require_nonneg_int, require_enum, optional_bool, optional_int, optional_number,
    paginate, sorted_by_created, ser_default,
)
from services.calculations import coverage_load

bp = Blueprint("resources", __name__)

ALL_ROLES = {"Scheduler", "PreOpNurse", "ORManager", "BillingAnalyst"}
ANES_CLASSES = {"LOCAL", "MAC", "REGIONAL", "GENERAL"}
CMS_INDICATORS = {"COVERED_ASC", "DEVICE_INTENSIVE", "OFFICE_BASED", "EXCLUDED"}
CREDENTIALS = {"MD", "DO", "CRNA"}


def _unique_in_facility(collection, facility_id, field, value):
    coll = getattr(db, collection)
    for rec in coll.values():
        if rec.get("facility_id") == facility_id and rec.get(field) == value:
            raise err("ERR_DUPLICATE_KEY",
                      "%s '%s' already exists in this facility." % (field, value))


# ------------------------------------------------------------------ Facilities
@bp.route("/asc/facilities", methods=["POST"])
def create_facility():
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    body = get_body()
    name = require_str(body, "name")

    turnover = optional_int(body, "turnover_minutes", 25)
    if turnover < 0:
        raise err("ERR_INVALID_REQUEST", "turnover_minutes must be non-negative.")
    hp_validity = optional_int(body, "hp_validity_days", 30)
    if hp_validity < 0:
        raise err("ERR_INVALID_REQUEST", "hp_validity_days must be non-negative.")
    util_target = optional_number(body, "utilization_target_pct", 75)
    if util_target < 0 or util_target > 100:
        raise err("ERR_INVALID_REQUEST", "utilization_target_pct must be 0..100.")

    rec = stamp_common({
        "name": name,
        "turnover_minutes": turnover,
        "hp_validity_days": hp_validity,
        "utilization_target_pct": util_target,
        "current_utc": "1970-01-01T00:00:00.000Z",
    })
    db.facilities[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/facilities/<facility_id>", methods=["GET"])
def get_facility(facility_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = lookup("facilities", facility_id)
    return success(ser_default(rec))


@bp.route("/asc/facilities/<facility_id>/clock", methods=["POST"])
def advance_clock(facility_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler", "ORManager"})
    fac = lookup("facilities", facility_id)
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    # Must be >= prior current_utc (string ISO compare is monotonic for fixed format,
    # but compare as time to be safe).
    from services.timeutil import parse_iso
    try:
        new_t = parse_iso(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    prior_t = parse_iso(fac["current_utc"])
    if new_t < prior_t:
        raise err("ERR_INVALID_REQUEST", "Clock cannot move backward.")
    fac["current_utc"] = to_iso
    touch(fac)
    return success(ser_default(fac))


# -------------------------------------------------------------- Operating Rooms
@bp.route("/asc/operating-rooms", methods=["POST"])
def create_or():
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    room_label = require_str(body, "room_label")
    start = optional_int(body, "prime_time_start_min", 420)
    end = optional_int(body, "prime_time_end_min", 960)
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "prime_time_end_min must be > prime_time_start_min.")

    rec = stamp_common({
        "facility_id": facility_id,
        "room_label": room_label,
        "prime_time_start_min": start,
        "prime_time_end_min": end,
        "status": "AVAILABLE",
    })
    db.operating_rooms[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/operating-rooms", methods=["GET"])
def list_ors():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.operating_rooms.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    status = _arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/operating-rooms/<or_id>", methods=["GET"])
def get_or(or_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("operating_rooms", or_id)))


@bp.route("/asc/operating-rooms/<or_id>/status", methods=["POST"])
def or_status(or_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    rec = lookup("operating_rooms", or_id)
    body = get_body()
    status = require_enum(body, "status", {"AVAILABLE", "OFFLINE"})
    rec["status"] = status
    touch(rec)
    return success(ser_default(rec))


# ---------------------------------------------------------------- Recovery Bays
@bp.route("/asc/recovery-bays", methods=["POST"])
def create_bay():
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    bay_label = require_str(body, "bay_label")
    phase2 = optional_bool(body, "phase2_capable", True)

    rec = stamp_common({
        "facility_id": facility_id,
        "bay_label": bay_label,
        "phase2_capable": phase2,
        "status": "AVAILABLE",
    })
    db.recovery_bays[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/recovery-bays", methods=["GET"])
def list_bays():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.recovery_bays.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    status = _arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/recovery-bays/<bay_id>", methods=["GET"])
def get_bay(bay_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("recovery_bays", bay_id)))


@bp.route("/asc/recovery-bays/<bay_id>/status", methods=["POST"])
def bay_status(bay_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    rec = lookup("recovery_bays", bay_id)
    body = get_body()
    status = require_enum(body, "status", {"AVAILABLE", "OFFLINE"})
    rec["status"] = status
    touch(rec)
    return success(ser_default(rec))


# ------------------------------------------------------------ Anesthesiologists
@bp.route("/asc/anesthesiologists", methods=["POST"])
def create_anesth():
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    full_name = require_str(body, "full_name")
    credential = body.get("credential", "MD")
    if credential not in CREDENTIALS:
        raise err("ERR_INVALID_REQUEST", "credential must be MD, DO, or CRNA.")
    active = optional_bool(body, "active", True)

    rec = stamp_common({
        "facility_id": facility_id,
        "full_name": full_name,
        "credential": credential,
        "active": active,
    })
    db.anesthesiologists[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/anesthesiologists", methods=["GET"])
def list_anesth():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.anesthesiologists.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/anesthesiologists/<anesth_id>", methods=["GET"])
def get_anesth(anesth_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("anesthesiologists", anesth_id)))


@bp.route("/asc/anesthesiologists/<anesth_id>/coverage-load", methods=["GET"])
def coverage_load_report(anesth_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler", "ORManager", "BillingAnalyst"})
    lookup("anesthesiologists", anesth_id)
    service_date = _arg("service_date")
    if service_date is None:
        raise err("ERR_INVALID_REQUEST", "service_date query param is required.")
    basis = _arg("basis") or "PROJECTED"
    if basis not in ("PROJECTED", "ACTUAL"):
        raise err("ERR_INVALID_REQUEST", "basis must be PROJECTED or ACTUAL.")
    minutes, pct = coverage_load(anesth_id, service_date, basis)
    return success({
        "anesthesiologist_id": anesth_id,
        "service_date": service_date,
        "basis": basis,
        "minutes": minutes,
        "coverage_load_pct": pct,
    })


# --------------------------------------------------------------------- Surgeons
@bp.route("/asc/surgeons", methods=["POST"])
def create_surgeon():
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    full_name = require_str(body, "full_name")
    npi = require_str(body, "npi")
    if not (npi.isdigit() and len(npi) == 10):
        raise err("ERR_INVALID_REQUEST", "npi must be exactly 10 digits.")
    active = optional_bool(body, "active", True)
    _unique_in_facility("surgeons", facility_id, "npi", npi)

    rec = stamp_common({
        "facility_id": facility_id,
        "full_name": full_name,
        "npi": npi,
        "active": active,
    })
    db.surgeons[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/surgeons", methods=["GET"])
def list_surgeons():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.surgeons.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/surgeons/<surgeon_id>", methods=["GET"])
def get_surgeon(surgeon_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("surgeons", surgeon_id)))


@bp.route("/asc/surgeons/<surgeon_id>", methods=["PATCH"])
def update_surgeon(surgeon_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    rec = lookup("surgeons", surgeon_id)
    body = get_body()
    if body.get("active") is not None:
        rec["active"] = require_bool_val(body, "active")
    touch(rec)
    return success(ser_default(rec))


# ------------------------------------------------------------------- Procedures
@bp.route("/asc/procedures", methods=["POST"])
def create_procedure():
    _, role = get_user_context()
    require_role(role, {"BillingAnalyst"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    cpt = require_str(body, "cpt_code")
    if len(cpt) != 5:
        raise err("ERR_INVALID_REQUEST", "cpt_code must be exactly 5 characters.")
    description = require_str(body, "description")
    scheduled_minutes = require_positive_int(body, "scheduled_minutes")
    cms_indicator = require_enum(body, "cms_payment_indicator", CMS_INDICATORS)
    cms_base = require_nonneg_int(body, "cms_base_rate_cents")
    requires_phase2 = optional_bool(body, "requires_phase2", False)
    anesthesia_class = body.get("anesthesia_class", "MAC")
    if anesthesia_class not in ANES_CLASSES:
        raise err("ERR_INVALID_REQUEST", "anesthesia_class out of range.")
    device_offset = optional_number(body, "device_offset_pct", 0)
    if device_offset < 0 or device_offset > 100:
        raise err("ERR_INVALID_REQUEST", "device_offset_pct must be 0..100.")
    _unique_in_facility("procedures", facility_id, "cpt_code", cpt)

    rec = stamp_common({
        "facility_id": facility_id,
        "cpt_code": cpt,
        "description": description,
        "scheduled_minutes": scheduled_minutes,
        "requires_phase2": requires_phase2,
        "anesthesia_class": anesthesia_class,
        "cms_payment_indicator": cms_indicator,
        "cms_base_rate_cents": cms_base,
        "device_offset_pct": device_offset,
    })
    db.procedures[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/procedures", methods=["GET"])
def list_procedures():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.procedures.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/procedures/<procedure_id>", methods=["GET"])
def get_procedure(procedure_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("procedures", procedure_id)))


# ----------------------------------------------------------------- Supply Items
@bp.route("/asc/supply-items", methods=["POST"])
def create_supply():
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    sku = require_str(body, "sku")
    description = require_str(body, "description")
    unit_cost = require_nonneg_int(body, "unit_cost_cents")
    is_device = optional_bool(body, "is_device", False)
    on_hand = optional_int(body, "on_hand_qty", 0)
    if on_hand < 0:
        raise err("ERR_INVALID_REQUEST", "on_hand_qty must be non-negative.")
    _unique_in_facility("supply_items", facility_id, "sku", sku)

    rec = stamp_common({
        "facility_id": facility_id,
        "sku": sku,
        "description": description,
        "is_device": is_device,
        "unit_cost_cents": unit_cost,
        "on_hand_qty": on_hand,
        "reserved_qty": 0,
    })
    db.supply_items[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/supply-items", methods=["GET"])
def list_supply():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.supply_items.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/supply-items/<item_id>", methods=["GET"])
def get_supply(item_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("supply_items", item_id)))


@bp.route("/asc/supply-items/<item_id>/restock", methods=["POST"])
def restock(item_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    rec = lookup("supply_items", item_id)
    body = get_body()
    delta = require_positive_int(body, "delta_qty")
    rec["on_hand_qty"] += delta
    touch(rec)
    return success(ser_default(rec))


# --------------------------------------------------------------------- Patients
@bp.route("/asc/patients", methods=["POST"])
def create_patient():
    _, role = get_user_context()
    require_role(role, {"Scheduler", "PreOpNurse"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    mrn = require_str(body, "mrn")
    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    _unique_in_facility("patients", facility_id, "mrn", mrn)

    rec = stamp_common({
        "facility_id": facility_id,
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": dob,
    })
    db.patients[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/patients", methods=["GET"])
def list_patients():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.patients.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("patients", patient_id)))


# ---- small local helpers ----
def _arg(name):
    from flask import request
    return request.args.get(name)


def require_bool_val(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v
