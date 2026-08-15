"""Nuclear Medicine & Radiopharmaceutical Management API (Flask, in-memory)."""

import os
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

import db
from calc import (
    Q3, Q6, container_current_activity, decay_exact, decay_tabular, dfrac,
    find_license_for_isotope, get_now, get_order_license, iso_z,
    matching_condition, minutes_between, parse_dt,
    required_activity_at_preparation, stamp_new, system_ts, touch,
)
from errors import (
    ApiError, ERR_ACTIVITY_TOLERANCE_EXCEEDED, ERR_ADMIN_BEFORE_DELIVERY,
    ERR_APPOINTMENT_OVERLAP, ERR_CLEARANCE_ACTIVITY_EXCEEDED,
    ERR_DELIVERY_NOT_RECEIVED, ERR_DOSE_DECAYED_BELOW_MIN,
    ERR_DUPLICATE_LICENSE_NUMBER, ERR_DUPLICATE_RELEASE_INSTRUCTION,
    ERR_FORBIDDEN_ROLE, ERR_HOT_LAB_CAPACITY_EXCEEDED,
    ERR_INSUFFICIENT_DELIVERY_ACTIVITY, ERR_INVALID_STATE,
    ERR_ISOTOPE_NOT_ON_LICENSE, ERR_LICENSE_EXPIRED, ERR_LICENSE_SUSPENDED,
    ERR_NOT_FOUND, ERR_OUTSIDE_ADMIN_WINDOW, ERR_POSSESSION_LIMIT_EXCEEDED,
    ERR_PRESCRIBED_ACTIVITY_EXCEEDS_LIMIT, ERR_RELEASE_CRITERIA_NOT_MET,
    ERR_ROOM_CONTAMINATED, ERR_SCHEDULE_IN_PAST, ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION, ERR_SURVEY_REQUIRED, ERR_USER_NOT_ACTIVE,
    ERR_USER_SCOPE_INSUFFICIENT, ERR_VALIDATION, ERR_WASTE_CLEARANCE_TOO_EARLY,
    raise_error,
)
from middleware import GET_ALL_ROLES, require_auth, require_entity_backed_au, require_role
from response import error_response, success_list, success_object
from serializers import (
    authorized_user_out, dose_administration_out, dose_order_out, dose_vial_out,
    imaging_room_out, isotope_delivery_out, isotope_product_out, license_out,
    patient_out, patient_release_instruction_out, procedure_appointment_out,
    radiation_survey_out, spill_incident_out, waste_container_out,
)

app = Flask(__name__)

PREFIX = "/nuclear-medicine"


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response("ERR_VALIDATION", str(err), 400)


# ---------------------------------------------------------------------------
# Payload / validation helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_error(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def req_field(data, field):
    if field not in data or data[field] is None:
        raise_error(ERR_VALIDATION, f"Missing required field: {field}")
    return data[field]


def req_number(data, field):
    return dfrac(req_field(data, field), )


def req_string(data, field):
    value = req_field(data, field)
    if not isinstance(value, str):
        raise_error(ERR_VALIDATION, f"Field '{field}' must be a string")
    return value


def opt_number(data, field):
    if field not in data or data[field] is None:
        return None
    return dfrac(data[field])


def parse_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except ValueError:
        raise_error(ERR_VALIDATION, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def list_response(store, serializer, filters):
    """Sorted by created_at ascending; apply equality filters; paginate."""
    items = sorted(store.values(), key=lambda e: (e["created_at"], e["id"]))
    for field, value in filters.items():
        if value is not None:
            items = [e for e in items if str(e.get(field)) == value]
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(e) for e in page], limit, offset, total)


def get_or_404(store, entity_id, what):
    entity = store.get(entity_id)
    if entity is None:
        raise_error(ERR_NOT_FOUND, f"{what} not found")
    return entity


# ---------------------------------------------------------------------------
# Clock sweep (PRD §2.4)
# ---------------------------------------------------------------------------

def run_clock_sweep(now):
    for order in db.dose_orders.values():
        if order["status"] in ("ORDERED", "ON_HOLD") and order["expires_at_dt"] < now:
            order["status"] = "EXPIRED"
            touch(order)
    for vial in db.dose_vials.values():
        if vial["status"] != "CALIBRATED":
            continue
        order = db.dose_orders.get(vial["order_id"])
        if order is None:
            continue
        isotope = db.isotope_products.get(order["isotope_product_id"])
        if isotope is None:
            continue
        decayed = decay_exact(vial["measured_activity_mbq"], vial["calibrated_at_dt"], now,
                              isotope["half_life_minutes"])
        if decayed < dfrac(isotope["min_usable_activity_mbq"]):
            vial["status"] = "DECAYED"
            touch(vial)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role(("DepartmentAdmin",))
    data = body()
    to_iso = req_field(data, "to_iso8601")
    if not isinstance(to_iso, str):
        raise_error(ERR_VALIDATION, "to_iso8601 must be a string")
    # Validate
    parse_dt(to_iso, "to_iso8601")
    db.current_utc_iso = to_iso
    run_clock_sweep(get_now())
    return success_object({"current_utc": to_iso}, 200)


# ---------------------------------------------------------------------------
# Isotope products
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/isotope-products", methods=["POST"])
def create_isotope_product():
    require_role(("DepartmentAdmin",))
    data = body()
    name = req_string(data, "name")
    half_life = req_number(data, "half_life_minutes")
    spill_thr = req_number(data, "spill_major_threshold_mbq")
    release_lim = req_number(data, "release_activity_limit_mbq")
    min_usable = req_number(data, "min_usable_activity_mbq")
    if half_life <= 0:
        raise_error(ERR_VALIDATION, "half_life_minutes must be > 0")
    decay_const = (Decimal("0.6931471805599453") / half_life).quantize(Q6, rounding=ROUND_HALF_UP)
    entity = {
        "id": str(uuid.uuid4()),
        "name": name,
        "half_life_minutes": half_life,
        "decay_constant_per_minute": decay_const,
        "spill_major_threshold_mbq": spill_thr,
        "release_activity_limit_mbq": release_lim,
        "min_usable_activity_mbq": min_usable,
    }
    stamp_new(entity)
    db.isotope_products[entity["id"]] = entity
    return success_object(isotope_product_out(entity), 201)


@app.route(f"{PREFIX}/isotope-products", methods=["GET"])
def list_isotope_products():
    require_role(GET_ALL_ROLES)
    return list_response(db.isotope_products, isotope_product_out, {})


@app.route(f"{PREFIX}/isotope-products/<pid>", methods=["GET"])
def get_isotope_product(pid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.isotope_products, pid, "IsotopeProduct")
    return success_object(isotope_product_out(entity), 200)


# ---------------------------------------------------------------------------
# Licenses
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/licenses", methods=["POST"])
def create_license():
    require_role(("DepartmentAdmin",))
    data = body()
    license_number = req_string(data, "license_number")
    max_possession = req_number(data, "max_possession_mbq")
    conditions = req_field(data, "isotope_conditions")
    if not isinstance(conditions, list):
        raise_error(ERR_VALIDATION, "isotope_conditions must be an array")
    expires_at = parse_dt(req_field(data, "expires_at"), "expires_at")
    for cond in conditions:
        if not isinstance(cond, dict):
            raise_error(ERR_VALIDATION, "isotope_conditions entries must be objects")
        iso_id = cond.get("isotope_product_id")
        if not isinstance(iso_id, str) or iso_id not in db.isotope_products:
            raise_error(ERR_NOT_FOUND, "isotope_conditions references an unknown isotope_product_id")
        if "max_possession_mbq" not in cond:
            raise_error(ERR_VALIDATION, "isotope_conditions entry missing max_possession_mbq")
        dfrac(cond["max_possession_mbq"])
        if cond.get("allowed_use") not in ("DIAGNOSTIC", "THERAPEUTIC", "BOTH"):
            raise_error(ERR_VALIDATION, "allowed_use must be DIAGNOSTIC, THERAPEUTIC, or BOTH")
    for other in db.licenses.values():
        if other["license_number"] == license_number:
            raise_error(ERR_DUPLICATE_LICENSE_NUMBER, "license_number already exists")
    entity = {
        "id": str(uuid.uuid4()),
        "license_number": license_number,
        "max_possession_mbq": max_possession,
        "isotope_conditions": conditions,
        "expires_at_dt": expires_at,
        "status": "ACTIVE",
    }
    stamp_new(entity)
    db.licenses[entity["id"]] = entity
    return success_object(license_out(entity), 201)


@app.route(f"{PREFIX}/licenses/<lid>", methods=["GET"])
def get_license(lid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.licenses, lid, "RadiopharmacyLicense")
    return success_object(license_out(entity), 200)


@app.route(f"{PREFIX}/licenses/<lid>/suspend", methods=["POST"])
def suspend_license(lid):
    require_role(("DepartmentAdmin",))
    lic = get_or_404(db.licenses, lid, "RadiopharmacyLicense")
    if lic["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "License must be ACTIVE to suspend")
    lic["status"] = "SUSPENDED"
    touch(lic)
    # Cascade hop 1: suspend ACTIVE authorized users of this license.
    suspended_user_ids = []
    for au in db.authorized_users.values():
        if au["license_id"] == lic["id"] and au["status"] == "ACTIVE":
            au["status"] = "SUSPENDED"
            touch(au)
            suspended_user_ids.append(au["id"])
    # Cascade hop 2: hold open orders of just-suspended users (no vial quarantine).
    for order in db.dose_orders.values():
        if order["authorized_user_id"] in suspended_user_ids and order["status"] in ("ORDERED", "DOSE_PREPARED"):
            order["hold_previous_status"] = order["status"]
            order["status"] = "ON_HOLD"
            order["hold_reason"] = "LICENSE_SUSPENDED"
            touch(order)
    return success_object(license_out(lic), 200)


@app.route(f"{PREFIX}/licenses/<lid>/reinstate", methods=["POST"])
def reinstate_license(lid):
    require_role(("DepartmentAdmin",))
    lic = get_or_404(db.licenses, lid, "RadiopharmacyLicense")
    if lic["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "License must be SUSPENDED to reinstate")
    lic["status"] = "ACTIVE"
    touch(lic)
    for au in db.authorized_users.values():
        if au["license_id"] == lic["id"] and au["status"] == "SUSPENDED":
            au["status"] = "ACTIVE"
            touch(au)
    for order in db.dose_orders.values():
        if order["status"] == "ON_HOLD" and order.get("hold_reason") == "LICENSE_SUSPENDED":
            order["status"] = order["hold_previous_status"]
            order["hold_reason"] = None
            order["hold_previous_status"] = None
            touch(order)
    return success_object(license_out(lic), 200)


# ---------------------------------------------------------------------------
# Authorized users
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/authorized-users", methods=["POST"])
def create_authorized_user():
    require_role(("DepartmentAdmin",))
    data = body()
    full_name = req_string(data, "full_name")
    license_id = req_string(data, "license_id")
    scope = req_string(data, "scope")
    expires_at = parse_dt(req_field(data, "expires_at"), "expires_at")
    get_or_404(db.licenses, license_id, "RadiopharmacyLicense")
    if scope not in ("DIAGNOSTIC", "THERAPEUTIC", "BOTH"):
        raise_error(ERR_VALIDATION, "scope must be DIAGNOSTIC, THERAPEUTIC, or BOTH")
    entity = {
        "id": str(uuid.uuid4()),
        "full_name": full_name,
        "license_id": license_id,
        "scope": scope,
        "expires_at_dt": expires_at,
        "status": "ACTIVE",
    }
    stamp_new(entity)
    db.authorized_users[entity["id"]] = entity
    return success_object(authorized_user_out(entity), 201)


@app.route(f"{PREFIX}/authorized-users", methods=["GET"])
def list_authorized_users():
    require_role(GET_ALL_ROLES)
    return list_response(db.authorized_users, authorized_user_out,
                         {"license_id": request.args.get("license_id")})


@app.route(f"{PREFIX}/authorized-users/<uid>", methods=["GET"])
def get_authorized_user(uid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.authorized_users, uid, "AuthorizedUser")
    return success_object(authorized_user_out(entity), 200)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/patients", methods=["POST"])
def create_patient():
    require_role(("NuclearMedicineTechnologist", "DepartmentAdmin"))
    data = body()
    full_name = req_string(data, "full_name")
    weight = req_number(data, "weight_kg")
    dob = data.get("date_of_birth")
    if weight <= 0:
        raise_error(ERR_VALIDATION, "weight_kg must be > 0")
    entity = {
        "id": str(uuid.uuid4()),
        "full_name": full_name,
        "weight_kg": weight,
        "date_of_birth": dob,
    }
    stamp_new(entity)
    db.patients[entity["id"]] = entity
    return success_object(patient_out(entity), 201)


@app.route(f"{PREFIX}/patients", methods=["GET"])
def list_patients():
    require_role(GET_ALL_ROLES)
    return list_response(db.patients, patient_out, {})


# ---------------------------------------------------------------------------
# Imaging rooms
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/imaging-rooms", methods=["POST"])
def create_imaging_room():
    require_role(("DepartmentAdmin",))
    data = body()
    name = req_string(data, "name")
    buffer_min = data.get("cleanup_buffer_minutes", 15)
    if isinstance(buffer_min, bool) or not isinstance(buffer_min, int):
        raise_error(ERR_VALIDATION, "cleanup_buffer_minutes must be an integer")
    entity = {
        "id": str(uuid.uuid4()),
        "name": name,
        "cleanup_buffer_minutes": buffer_min,
        "status": "OPERATIONAL",
    }
    stamp_new(entity)
    db.imaging_rooms[entity["id"]] = entity
    return success_object(imaging_room_out(entity), 201)


@app.route(f"{PREFIX}/imaging-rooms/<rid>", methods=["GET"])
def get_imaging_room(rid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.imaging_rooms, rid, "ImagingRoom")
    return success_object(imaging_room_out(entity), 200)


# ---------------------------------------------------------------------------
# Isotope deliveries
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/isotope-deliveries", methods=["POST"])
def create_isotope_delivery():
    require_role(("Radiopharmacist",))
    data = body()
    isotope_id = req_string(data, "isotope_product_id")
    arrival = parse_dt(req_field(data, "scheduled_arrival_at"), "scheduled_arrival_at")
    ref_activity = req_number(data, "reference_activity_mbq")
    ref_time = parse_dt(req_field(data, "reference_time_at"), "reference_time_at")
    isotope = get_or_404(db.isotope_products, isotope_id, "IsotopeProduct")

    # Hot-lab aggregate capacity check (SCAFFOLD calc hot_lab_delivery_capacity).
    new_start = arrival - timedelta(minutes=30)
    new_end = arrival + timedelta(minutes=30)
    candidates = []
    for other in db.isotope_deliveries.values():
        if other["status"] not in ("SCHEDULED", "RECEIVED"):
            continue
        o_start = other["scheduled_arrival_at_dt"] - timedelta(minutes=30)
        o_end = other["scheduled_arrival_at_dt"] + timedelta(minutes=30)
        if o_start < new_end and new_start < o_end:
            candidates.append(other)
    t_star = max([arrival] + [c["scheduled_arrival_at_dt"] for c in candidates])
    load = Decimal("0")
    for c in candidates:
        c_iso = db.isotope_products[c["isotope_product_id"]]
        load += decay_exact(c["reference_activity_mbq"], c["reference_time_at_dt"], t_star,
                            c_iso["half_life_minutes"])
    load += decay_exact(ref_activity, ref_time, t_star, isotope["half_life_minutes"])
    load = load.quantize(Q3, rounding=ROUND_HALF_UP)
    if load > Decimal("37000"):
        raise_error(ERR_HOT_LAB_CAPACITY_EXCEEDED, "Hot-lab aggregate capacity exceeded")

    entity = {
        "id": str(uuid.uuid4()),
        "isotope_product_id": isotope_id,
        "scheduled_arrival_at_dt": arrival,
        "reference_activity_mbq": ref_activity,
        "reference_time_at_dt": ref_time,
        "received_at_dt": None,
        "measured_activity_mbq": None,
        "failure_reason": None,
        "status": "SCHEDULED",
    }
    stamp_new(entity)
    db.isotope_deliveries[entity["id"]] = entity
    return success_object(isotope_delivery_out(entity), 201)


@app.route(f"{PREFIX}/isotope-deliveries", methods=["GET"])
def list_isotope_deliveries():
    require_role(GET_ALL_ROLES)
    return list_response(db.isotope_deliveries, isotope_delivery_out, {
        "isotope_product_id": request.args.get("isotope_product_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/isotope-deliveries/<did>", methods=["GET"])
def get_isotope_delivery(did):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.isotope_deliveries, did, "IsotopeDelivery")
    return success_object(isotope_delivery_out(entity), 200)


@app.route(f"{PREFIX}/isotope-deliveries/<did>/receive", methods=["POST"])
def receive_isotope_delivery(did):
    require_role(("Radiopharmacist",))
    delivery = get_or_404(db.isotope_deliveries, did, "IsotopeDelivery")
    data = body()
    measured = req_number(data, "measured_activity_mbq")
    if delivery["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Delivery must be SCHEDULED")
    lic = find_license_for_isotope(delivery["isotope_product_id"])
    now = get_now()
    if lic is not None:
        if lic["status"] != "ACTIVE":
            raise_error(ERR_LICENSE_SUSPENDED, "License is SUSPENDED")
        if now >= lic["expires_at_dt"]:
            raise_error(ERR_LICENSE_EXPIRED, "License is expired")
    isotope = db.isotope_products[delivery["isotope_product_id"]]
    decayed_ref = decay_exact(delivery["reference_activity_mbq"], delivery["reference_time_at_dt"],
                              now, isotope["half_life_minutes"])
    tolerance = (decayed_ref * Decimal("0.1"))
    if abs(measured - decayed_ref) > tolerance:
        raise_error(ERR_ACTIVITY_TOLERANCE_EXCEEDED,
                    "Measured receipt activity deviates > 10% from decayed reference")
    delivery["measured_activity_mbq"] = measured
    delivery["received_at_dt"] = now
    delivery["status"] = "RECEIVED"
    touch(delivery)
    return success_object(isotope_delivery_out(delivery), 200)


@app.route(f"{PREFIX}/isotope-deliveries/<did>/mark-failed", methods=["POST"])
def mark_delivery_failed(did):
    require_role(("Radiopharmacist",))
    delivery = get_or_404(db.isotope_deliveries, did, "IsotopeDelivery")
    data = body()
    reason = req_string(data, "reason")
    if delivery["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Delivery must be SCHEDULED")
    delivery["failure_reason"] = reason
    delivery["status"] = "FAILED"
    touch(delivery)
    return success_object(isotope_delivery_out(delivery), 200)


# ---------------------------------------------------------------------------
# Dose orders
# ---------------------------------------------------------------------------

def _validate_order_clinical(au, isotope, use_type, prescribed, sched_dt, now):
    """Guard chain shared by order creation and substitution (PRD §3.3)."""
    lic = db.licenses.get(au["license_id"])
    if lic is None:
        raise_error(ERR_NOT_FOUND, "License not found for authorized user")
    if lic["status"] != "ACTIVE":
        raise_error(ERR_LICENSE_SUSPENDED, "License is SUSPENDED")
    if now >= lic["expires_at_dt"]:
        raise_error(ERR_LICENSE_EXPIRED, "License is expired")
    if au["status"] != "ACTIVE" or now >= au["expires_at_dt"]:
        raise_error(ERR_USER_NOT_ACTIVE, "AuthorizedUser is not active")
    if au["scope"] != "BOTH" and au["scope"] != use_type:
        raise_error(ERR_USER_SCOPE_INSUFFICIENT, "AuthorizedUser scope does not cover use_type")
    cond = matching_condition(lic, isotope["id"])
    if cond is None or (cond.get("allowed_use") != "BOTH" and cond.get("allowed_use") != use_type):
        raise_error(ERR_ISOTOPE_NOT_ON_LICENSE, "Isotope not on license for this use")
    if prescribed > dfrac(cond["max_possession_mbq"]):
        raise_error(ERR_PRESCRIBED_ACTIVITY_EXCEEDS_LIMIT,
                    "prescribed_activity_mbq exceeds condition max_possession_mbq")
    if sched_dt <= now:
        raise_error(ERR_SCHEDULE_IN_PAST, "administration_scheduled_at must be in the future")
    return lic


def _create_order(au, isotope_id, use_type, prescribed, sched_dt, patient_id, now,
                  replaces_order_id=None):
    isotope = db.isotope_products[isotope_id]
    lic = _validate_order_clinical(au, isotope, use_type, prescribed, sched_dt, now)
    expires_dt = sched_dt + timedelta(minutes=2 * float(isotope["half_life_minutes"]))
    entity = {
        "id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "isotope_product_id": isotope_id,
        "authorized_user_id": au["id"],
        "use_type": use_type,
        "prescribed_activity_mbq": prescribed,
        "administration_scheduled_at_dt": sched_dt,
        "expires_at_dt": expires_dt,
        "hold_reason": None,
        "hold_previous_status": None,
        "replaces_order_id": replaces_order_id,
        "superseded_by_order_id": None,
        "status": "ORDERED",
    }
    stamp_new(entity)
    db.dose_orders[entity["id"]] = entity
    return entity


@app.route(f"{PREFIX}/dose-orders", methods=["POST"])
def create_dose_order():
    user_id, _ = require_role(("AuthorizedUser",))
    au = require_entity_backed_au(user_id)
    data = body()
    patient_id = req_string(data, "patient_id")
    isotope_id = req_string(data, "isotope_product_id")
    use_type = req_string(data, "use_type")
    prescribed = req_number(data, "prescribed_activity_mbq")
    sched_dt = parse_dt(req_field(data, "administration_scheduled_at"), "administration_scheduled_at")
    get_or_404(db.patients, patient_id, "Patient")
    get_or_404(db.isotope_products, isotope_id, "IsotopeProduct")
    if use_type not in ("DIAGNOSTIC", "THERAPEUTIC"):
        raise_error(ERR_VALIDATION, "use_type must be DIAGNOSTIC or THERAPEUTIC")
    now = get_now()
    entity = _create_order(au, isotope_id, use_type, prescribed, sched_dt, patient_id, now)
    return success_object(dose_order_out(entity), 201)


@app.route(f"{PREFIX}/dose-orders", methods=["GET"])
def list_dose_orders():
    require_role(GET_ALL_ROLES)
    return list_response(db.dose_orders, dose_order_out, {
        "patient_id": request.args.get("patient_id"),
        "isotope_product_id": request.args.get("isotope_product_id"),
        "authorized_user_id": request.args.get("authorized_user_id"),
        "replaces_order_id": request.args.get("replaces_order_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/dose-orders/<oid>", methods=["GET"])
def get_dose_order(oid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.dose_orders, oid, "DoseOrder")
    return success_object(dose_order_out(entity), 200)


def _decay_open_vials(order, statuses=("PREPARED", "CALIBRATED", "QUARANTINED")):
    for vial in db.dose_vials.values():
        if vial["order_id"] == order["id"] and vial["status"] in statuses:
            vial["status"] = "DECAYED"
            touch(vial)


@app.route(f"{PREFIX}/dose-orders/<oid>/cancel", methods=["POST"])
def cancel_dose_order(oid):
    user_id, _ = require_role(("AuthorizedUser",))
    order = get_or_404(db.dose_orders, oid, "DoseOrder")
    if user_id != order["authorized_user_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "Only the prescribing AuthorizedUser may cancel")
    au = require_entity_backed_au(user_id)
    if order["status"] not in ("ORDERED", "DOSE_PREPARED", "ON_HOLD"):
        raise_error(ERR_INVALID_STATE, "Order cannot be cancelled from its current state")
    now = get_now()
    if au["status"] != "ACTIVE" or now >= au["expires_at_dt"]:
        raise_error(ERR_USER_NOT_ACTIVE, "AuthorizedUser is not active")
    order["status"] = "CANCELLED"
    touch(order)
    _decay_open_vials(order)
    return success_object(dose_order_out(order), 200)


@app.route(f"{PREFIX}/dose-orders/<oid>/substitute", methods=["POST"])
def substitute_dose_order(oid):
    user_id, _ = require_role(("AuthorizedUser",))
    order = get_or_404(db.dose_orders, oid, "DoseOrder")
    if user_id != order["authorized_user_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "Only the prescribing AuthorizedUser may substitute")
    au = require_entity_backed_au(user_id)
    data = body()
    expected = req_field(data, "expected_order_version")
    isotope_id = req_string(data, "isotope_product_id")
    use_type = req_string(data, "use_type")
    prescribed = req_number(data, "prescribed_activity_mbq")
    sched_dt = parse_dt(req_field(data, "administration_scheduled_at"), "administration_scheduled_at")
    # Body FK existence (priority 3) precedes OCC (priority 4).
    get_or_404(db.isotope_products, isotope_id, "IsotopeProduct")
    # OCC runs before state evaluation (PRD §2.8 / §3.3).
    if expected != order["version"]:
        raise_error(ERR_STALE_VERSION, "expected_order_version does not match current version")
    if order["status"] not in ("ORDERED", "ON_HOLD"):
        raise_error(ERR_INVALID_STATE, "Order cannot be substituted from its current state")
    if use_type not in ("DIAGNOSTIC", "THERAPEUTIC"):
        raise_error(ERR_VALIDATION, "use_type must be DIAGNOSTIC or THERAPEUTIC")
    now = get_now()
    new_order = _create_order(au, isotope_id, use_type, prescribed, sched_dt,
                              order["patient_id"], now, replaces_order_id=order["id"])
    order["status"] = "SUPERSEDED"
    order["superseded_by_order_id"] = new_order["id"]
    touch(order)
    _decay_open_vials(order, statuses=("PREPARED", "CALIBRATED"))
    return success_object(dose_order_out(new_order), 201)


# ---------------------------------------------------------------------------
# Dose vials
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/dose-vials", methods=["POST"])
def create_dose_vial():
    require_role(("Radiopharmacist",))
    data = body()
    order_id = req_string(data, "order_id")
    delivery_id = req_string(data, "delivery_id")
    order = get_or_404(db.dose_orders, order_id, "DoseOrder")
    delivery = get_or_404(db.isotope_deliveries, delivery_id, "IsotopeDelivery")
    if order["status"] != "ORDERED":
        raise_error(ERR_INVALID_STATE, "Order must be ORDERED to prepare a vial")
    if delivery["status"] != "RECEIVED":
        raise_error(ERR_DELIVERY_NOT_RECEIVED, "Delivery must be RECEIVED")
    lic = get_order_license(order)
    now = get_now()
    if lic is not None:
        if lic["status"] != "ACTIVE":
            raise_error(ERR_LICENSE_SUSPENDED, "License is SUSPENDED")
        if now >= lic["expires_at_dt"]:
            raise_error(ERR_LICENSE_EXPIRED, "License is expired")
    isotope = db.isotope_products[order["isotope_product_id"]]
    required = required_activity_at_preparation(order, isotope, now)
    if lic is not None:
        from calc import compute_possession
        current = compute_possession(lic, now)
        projected = (current + required).quantize(Q3, rounding=ROUND_HALF_UP)
        if projected > dfrac(lic["max_possession_mbq"]):
            raise_error(ERR_POSSESSION_LIMIT_EXCEEDED, "License possession limit exceeded")
        cond = matching_condition(lic, order["isotope_product_id"])
        if cond is not None and projected > dfrac(cond["max_possession_mbq"]):
            raise_error(ERR_POSSESSION_LIMIT_EXCEEDED, "Isotope condition possession limit exceeded")
    if order["administration_scheduled_at_dt"] < delivery["scheduled_arrival_at_dt"]:
        raise_error(ERR_ADMIN_BEFORE_DELIVERY,
                    "administration_scheduled_at precedes the delivery's scheduled_arrival_at")
    decayed_delivery = decay_exact(delivery["reference_activity_mbq"],
                                   delivery["reference_time_at_dt"], now,
                                   isotope["half_life_minutes"])
    if decayed_delivery < required:
        raise_error(ERR_INSUFFICIENT_DELIVERY_ACTIVITY,
                    "required activity exceeds the delivery's decayed remaining activity")
    entity = {
        "id": str(uuid.uuid4()),
        "order_id": order_id,
        "delivery_id": delivery_id,
        "waste_container_id": None,
        "prepared_at_dt": now,
        "required_activity_mbq": required,
        "measured_activity_mbq": None,
        "calibrated_at_dt": None,
        "calibrated_by_user_id": None,
        "status": "PREPARED",
        "disposed_at_dt": None,
        "residual_activity_mbq": None,
        "decay_loss_mbq": None,
    }
    stamp_new(entity)
    db.dose_vials[entity["id"]] = entity
    order["status"] = "DOSE_PREPARED"
    touch(order)
    return success_object(dose_vial_out(entity), 201)


@app.route(f"{PREFIX}/dose-vials", methods=["GET"])
def list_dose_vials():
    require_role(GET_ALL_ROLES)
    return list_response(db.dose_vials, dose_vial_out, {
        "order_id": request.args.get("order_id"),
        "delivery_id": request.args.get("delivery_id"),
        "waste_container_id": request.args.get("waste_container_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/dose-vials/<vid>", methods=["GET"])
def get_dose_vial(vid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.dose_vials, vid, "DoseVial")
    return success_object(dose_vial_out(entity), 200)


@app.route(f"{PREFIX}/dose-vials/<vid>/calibrate", methods=["POST"])
def calibrate_dose_vial(vid):
    user_id, _ = require_role(("Radiopharmacist",))
    vial = get_or_404(db.dose_vials, vid, "DoseVial")
    data = body()
    measured = req_number(data, "measured_activity_mbq")
    if vial["status"] != "PREPARED":
        raise_error(ERR_INVALID_STATE, "Vial must be PREPARED to calibrate")
    order = db.dose_orders[vial["order_id"]]
    isotope = db.isotope_products[order["isotope_product_id"]]
    if measured < dfrac(isotope["min_usable_activity_mbq"]):
        raise_error(ERR_DOSE_DECAYED_BELOW_MIN, "Assayed activity below min_usable_activity_mbq")
    vial["measured_activity_mbq"] = measured
    vial["calibrated_at_dt"] = get_now()
    vial["calibrated_by_user_id"] = user_id
    vial["status"] = "CALIBRATED"
    touch(vial)
    return success_object(dose_vial_out(vial), 200)


@app.route(f"{PREFIX}/dose-vials/<vid>/administer", methods=["POST"])
def administer_dose_vial(vid):
    user_id, _ = require_role(("NuclearMedicineTechnologist",))
    vial = get_or_404(db.dose_vials, vid, "DoseVial")
    if vial["status"] != "CALIBRATED":
        raise_error(ERR_INVALID_STATE, "Vial must be CALIBRATED to administer")
    order = db.dose_orders[vial["order_id"]]
    isotope = db.isotope_products[order["isotope_product_id"]]
    lic = get_order_license(order)
    now = get_now()
    if lic is not None:
        if lic["status"] != "ACTIVE":
            raise_error(ERR_LICENSE_SUSPENDED, "License is SUSPENDED")
        if now >= lic["expires_at_dt"]:
            raise_error(ERR_LICENSE_EXPIRED, "License is expired")
    if user_id == vial["calibrated_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "Administrator must differ from calibrator")
    diff_min = abs(minutes_between(order["administration_scheduled_at_dt"], now))
    within_window = diff_min <= 60
    if not within_window:
        raise_error(ERR_OUTSIDE_ADMIN_WINDOW,
                    "administered_at outside +/-60 minutes of administration_scheduled_at")
    assayed_exact = decay_exact(vial["measured_activity_mbq"], vial["calibrated_at_dt"], now,
                                isotope["half_life_minutes"])
    assayed_tabular = decay_tabular(vial["measured_activity_mbq"], vial["calibrated_at_dt"], now,
                                    isotope["half_life_minutes"])
    if assayed_exact < dfrac(isotope["min_usable_activity_mbq"]):
        vial["status"] = "DECAYED"
        touch(vial)
        raise_error(ERR_DOSE_DECAYED_BELOW_MIN, "Assayed activity below min_usable_activity_mbq")
    if order["status"] != "DOSE_PREPARED":
        raise_error(ERR_INVALID_STATE, "Order must be DOSE_PREPARED to administer")
    admin = {
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "vial_id": vial["id"],
        "administered_at_dt": now,
        "administered_by_user_id": user_id,
        "assayed_activity_exact_mbq": assayed_exact,
        "assayed_activity_tabular_mbq": assayed_tabular,
        "within_admin_window": within_window,
    }
    stamp_new(admin, append_only=True)
    db.dose_administrations[admin["id"]] = admin
    vial["status"] = "ADMINISTERED"
    touch(vial)
    order["status"] = "ADMINISTERED"
    touch(order)
    for appt in db.procedure_appointments.values():
        if (appt["order_id"] == order["id"] and appt["status"] == "BOOKED"
                and appt["start_at_dt"] <= now < appt["end_at_dt"]):
            appt["status"] = "COMPLETED"
            touch(appt)
    return success_object(dose_administration_out(admin), 201)


@app.route(f"{PREFIX}/dose-vials/<vid>/dispose", methods=["POST"])
def dispose_dose_vial(vid):
    require_role(("Radiopharmacist",))
    vial = get_or_404(db.dose_vials, vid, "DoseVial")
    data = body()
    container_id = req_string(data, "waste_container_id")
    container = get_or_404(db.waste_containers, container_id, "WasteContainer")
    if vial["status"] not in ("ADMINISTERED", "DECAYED"):
        raise_error(ERR_INVALID_STATE, "Only ADMINISTERED or DECAYED vials can be disposed")
    if container["status"] != "FILLING":
        raise_error(ERR_INVALID_STATE, "Target container must be FILLING")
    order = db.dose_orders[vial["order_id"]]
    if container["isotope_product_id"] != order["isotope_product_id"]:
        raise_error(ERR_VALIDATION, "Container isotope must match the vial's order isotope")
    isotope = db.isotope_products[order["isotope_product_id"]]
    hl = isotope["half_life_minutes"]
    now = get_now()
    measured = dfrac(vial["measured_activity_mbq"])
    if vial["status"] == "ADMINISTERED":
        admin = next((a for a in db.dose_administrations.values() if a["vial_id"] == vial["id"]), None)
        administered = dfrac(admin["assayed_activity_exact_mbq"])
        residual_now = measured - administered
        residual = decay_exact(residual_now, admin["administered_at_dt"], now, hl)
    else:
        administered = Decimal("0")
        residual = decay_exact(measured, vial["calibrated_at_dt"], now, hl)
    # PRD §3.7 balance invariant: measured == administered + residual + decay_loss.
    decay_loss = (measured - administered - residual).quantize(Q3, rounding=ROUND_HALF_UP)
    vial["residual_activity_mbq"] = residual
    vial["decay_loss_mbq"] = decay_loss
    vial["disposed_at_dt"] = now
    vial["waste_container_id"] = container_id
    vial["status"] = "DISPOSED"
    touch(vial)
    container["intake_activity_mbq"] = (dfrac(container["intake_activity_mbq"]) + residual).quantize(
        Q3, rounding=ROUND_HALF_UP)
    touch(container)
    return success_object(dose_vial_out(vial), 200)


# ---------------------------------------------------------------------------
# Dose administrations (append-only read surface)
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/dose-administrations", methods=["GET"])
def list_dose_administrations():
    require_role(GET_ALL_ROLES)
    return list_response(db.dose_administrations, dose_administration_out, {
        "order_id": request.args.get("order_id"),
        "vial_id": request.args.get("vial_id"),
    })


@app.route(f"{PREFIX}/dose-administrations/<aid>", methods=["GET"])
def get_dose_administration(aid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.dose_administrations, aid, "DoseAdministration")
    return success_object(dose_administration_out(entity), 200)


# ---------------------------------------------------------------------------
# Procedure appointments
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/procedure-appointments", methods=["POST"])
def create_procedure_appointment():
    require_role(("NuclearMedicineTechnologist",))
    data = body()
    order_id = req_string(data, "order_id")
    room_id = req_string(data, "room_id")
    start_at = parse_dt(req_field(data, "start_at"), "start_at")
    end_at = parse_dt(req_field(data, "end_at"), "end_at")
    order = get_or_404(db.dose_orders, order_id, "DoseOrder")
    room = get_or_404(db.imaging_rooms, room_id, "ImagingRoom")
    if order["status"] not in ("ORDERED", "DOSE_PREPARED"):
        raise_error(ERR_INVALID_STATE, "Order must be ORDERED or DOSE_PREPARED to book")
    if room["status"] != "OPERATIONAL":
        raise_error(ERR_ROOM_CONTAMINATED, "Room is CONTAMINATED")
    if end_at <= start_at:
        raise_error(ERR_VALIDATION, "end_at must be strictly later than start_at")
    buffer_td = timedelta(minutes=room["cleanup_buffer_minutes"])
    for appt in db.procedure_appointments.values():
        if appt["room_id"] != room_id or appt["status"] != "BOOKED":
            continue
        existing_end = appt["end_at_dt"] + buffer_td
        if start_at < existing_end and appt["start_at_dt"] < end_at:
            raise_error(ERR_APPOINTMENT_OVERLAP, "Booking overlaps an existing appointment")
    entity = {
        "id": str(uuid.uuid4()),
        "order_id": order_id,
        "room_id": room_id,
        "start_at_dt": start_at,
        "end_at_dt": end_at,
        "status": "BOOKED",
        "void_reason": None,
    }
    stamp_new(entity)
    db.procedure_appointments[entity["id"]] = entity
    return success_object(procedure_appointment_out(entity), 201)


@app.route(f"{PREFIX}/procedure-appointments", methods=["GET"])
def list_procedure_appointments():
    require_role(GET_ALL_ROLES)
    return list_response(db.procedure_appointments, procedure_appointment_out, {
        "order_id": request.args.get("order_id"),
        "room_id": request.args.get("room_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/procedure-appointments/<aid>", methods=["GET"])
def get_procedure_appointment(aid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.procedure_appointments, aid, "ProcedureAppointment")
    return success_object(procedure_appointment_out(entity), 200)


@app.route(f"{PREFIX}/procedure-appointments/<aid>/cancel", methods=["POST"])
def cancel_procedure_appointment(aid):
    require_role(("NuclearMedicineTechnologist",))
    appt = get_or_404(db.procedure_appointments, aid, "ProcedureAppointment")
    if appt["status"] != "BOOKED":
        raise_error(ERR_INVALID_STATE, "Appointment must be BOOKED to cancel")
    appt["status"] = "CANCELLED"
    touch(appt)
    return success_object(procedure_appointment_out(appt), 200)


# ---------------------------------------------------------------------------
# Waste containers
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/waste-containers", methods=["POST"])
def create_waste_container():
    require_role(("RadiationSafetyOfficer",))
    data = body()
    isotope_id = req_string(data, "isotope_product_id")
    room_id = req_string(data, "room_id")
    get_or_404(db.isotope_products, isotope_id, "IsotopeProduct")
    get_or_404(db.imaging_rooms, room_id, "ImagingRoom")
    entity = {
        "id": str(uuid.uuid4()),
        "isotope_product_id": isotope_id,
        "room_id": room_id,
        "status": "FILLING",
        "sealed_at_dt": None,
        "sealed_by_user_id": None,
        "certified_at_dt": None,
        "certified_by_user_id": None,
        "intake_activity_mbq": Decimal("0.000"),
        "clearable_after_at_dt": None,
    }
    stamp_new(entity)
    db.waste_containers[entity["id"]] = entity
    return success_object(waste_container_out(entity), 201)


@app.route(f"{PREFIX}/waste-containers", methods=["GET"])
def list_waste_containers():
    require_role(GET_ALL_ROLES)
    return list_response(db.waste_containers, waste_container_out, {
        "isotope_product_id": request.args.get("isotope_product_id"),
        "room_id": request.args.get("room_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/waste-containers/<cid>", methods=["GET"])
def get_waste_container(cid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.waste_containers, cid, "WasteContainer")
    return success_object(waste_container_out(entity), 200)


@app.route(f"{PREFIX}/waste-containers/<cid>/seal", methods=["POST"])
def seal_waste_container(cid):
    user_id, _ = require_role(("RadiationSafetyOfficer",))
    container = get_or_404(db.waste_containers, cid, "WasteContainer")
    data = body()
    expected = req_field(data, "expected_container_version")
    if expected != container["version"]:
        raise_error(ERR_STALE_VERSION, "expected_container_version does not match current version")
    if container["status"] != "FILLING":
        raise_error(ERR_INVALID_STATE, "Container must be FILLING to seal")
    isotope = db.isotope_products[container["isotope_product_id"]]
    now = get_now()
    container["sealed_at_dt"] = now
    container["sealed_by_user_id"] = user_id
    container["clearable_after_at_dt"] = now + timedelta(minutes=10 * float(isotope["half_life_minutes"]))
    container["status"] = "SEALED"
    touch(container)
    return success_object(waste_container_out(container), 200)


@app.route(f"{PREFIX}/waste-containers/<cid>/certify-clearance", methods=["POST"])
def certify_waste_container(cid):
    user_id, _ = require_role(("RadiationSafetyOfficer",))
    container = get_or_404(db.waste_containers, cid, "WasteContainer")
    if container["status"] != "SEALED":
        raise_error(ERR_INVALID_STATE, "Container must be SEALED to certify clearance")
    if user_id == container["sealed_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "Certifier must differ from sealer")
    now = get_now()
    if now < container["clearable_after_at_dt"]:
        raise_error(ERR_WASTE_CLEARANCE_TOO_EARLY, "Container is not yet clearable")
    current = container_current_activity(container, now)
    if current > Decimal("0.05"):
        raise_error(ERR_CLEARANCE_ACTIVITY_EXCEEDED, "current_activity_mbq exceeds 0.05")
    surveys = [s for s in db.radiation_surveys.values()
               if s["room_id"] == container["room_id"] and s["surveyed_at_dt"] >= container["sealed_at_dt"]]
    if not surveys:
        raise_error(ERR_SURVEY_REQUIRED, "No room survey recorded at or after sealed_at")
    latest = None
    for s in db.radiation_surveys.values():
        if s in surveys and (latest is None or s["surveyed_at_dt"] >= latest["surveyed_at_dt"]):
            latest = s
    if latest["result"] != "PASS":
        raise_error(ERR_SURVEY_REQUIRED, "Latest room survey is not PASS")
    container["certified_at_dt"] = now
    container["certified_by_user_id"] = user_id
    container["status"] = "CLEARED"
    touch(container)
    return success_object(waste_container_out(container), 200)


# ---------------------------------------------------------------------------
# Radiation surveys
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/radiation-surveys", methods=["POST"])
def create_radiation_survey():
    user_id, _ = require_role(("RadiationSafetyOfficer",))
    data = body()
    room_id = req_string(data, "room_id")
    ambient = req_number(data, "ambient_dose_rate_usv_h")
    result = req_string(data, "result")
    get_or_404(db.imaging_rooms, room_id, "ImagingRoom")
    if result not in ("PASS", "FAIL"):
        raise_error(ERR_VALIDATION, "result must be PASS or FAIL")
    entity = {
        "id": str(uuid.uuid4()),
        "room_id": room_id,
        "surveyed_at_dt": get_now(),
        "ambient_dose_rate_usv_h": ambient,
        "result": result,
        "performed_by_user_id": user_id,
    }
    stamp_new(entity, append_only=True)
    db.radiation_surveys[entity["id"]] = entity
    return success_object(radiation_survey_out(entity), 201)


@app.route(f"{PREFIX}/radiation-surveys", methods=["GET"])
def list_radiation_surveys():
    require_role(GET_ALL_ROLES)
    return list_response(db.radiation_surveys, radiation_survey_out, {
        "room_id": request.args.get("room_id"),
        "result": request.args.get("result"),
    })


@app.route(f"{PREFIX}/radiation-surveys/<sid>", methods=["GET"])
def get_radiation_survey(sid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.radiation_surveys, sid, "RadiationSurvey")
    return success_object(radiation_survey_out(entity), 200)


# ---------------------------------------------------------------------------
# Spill incidents
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/spill-incidents", methods=["POST"])
def create_spill_incident():
    user_id, _ = require_role(GET_ALL_ROLES)
    data = body()
    room_id = req_string(data, "room_id")
    isotope_id = req_string(data, "isotope_product_id")
    estimated = req_number(data, "estimated_activity_mbq")
    occurred_at = parse_dt(req_field(data, "occurred_at"), "occurred_at")
    room = get_or_404(db.imaging_rooms, room_id, "ImagingRoom")
    isotope = get_or_404(db.isotope_products, isotope_id, "IsotopeProduct")
    classification = "MAJOR" if estimated >= dfrac(isotope["spill_major_threshold_mbq"]) else "MINOR"
    entity = {
        "id": str(uuid.uuid4()),
        "room_id": room_id,
        "isotope_product_id": isotope_id,
        "estimated_activity_mbq": estimated,
        "occurred_at_dt": occurred_at,
        "classification": classification,
        "reported_by_user_id": user_id,
        "status": "REPORTED",
        "contained_at_dt": None,
        "decontaminated_at_dt": None,
        "cleared_at_dt": None,
        "cleared_by_user_id": None,
    }
    stamp_new(entity)
    db.spill_incidents[entity["id"]] = entity
    # Room cascade (PRD §3.6): room -> CONTAMINATED; appointments AUTO_VOIDED;
    # their orders ON_HOLD(SPILL_CONTAMINATION); vials QUARANTINED.
    if room["status"] == "OPERATIONAL":
        room["status"] = "CONTAMINATED"
        touch(room)
    for appt in db.procedure_appointments.values():
        if (appt["room_id"] == room_id and appt["status"] == "BOOKED"
                and appt["end_at_dt"] > occurred_at):
            appt["status"] = "AUTO_VOIDED"
            appt["void_reason"] = entity["id"]
            touch(appt)
            order = db.dose_orders.get(appt["order_id"])
            if order is not None and order["status"] in ("ORDERED", "DOSE_PREPARED"):
                order["hold_previous_status"] = order["status"]
                order["status"] = "ON_HOLD"
                order["hold_reason"] = "SPILL_CONTAMINATION"
                touch(order)
                for vial in db.dose_vials.values():
                    if vial["order_id"] == order["id"] and vial["status"] in ("PREPARED", "CALIBRATED"):
                        vial["status"] = "QUARANTINED"
                        touch(vial)
    return success_object(spill_incident_out(entity), 201)


@app.route(f"{PREFIX}/spill-incidents", methods=["GET"])
def list_spill_incidents():
    require_role(GET_ALL_ROLES)
    return list_response(db.spill_incidents, spill_incident_out, {
        "room_id": request.args.get("room_id"),
        "isotope_product_id": request.args.get("isotope_product_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/spill-incidents/<sid>", methods=["GET"])
def get_spill_incident(sid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.spill_incidents, sid, "SpillIncident")
    return success_object(spill_incident_out(entity), 200)


@app.route(f"{PREFIX}/spill-incidents/<sid>/advance", methods=["POST"])
def advance_spill_incident(sid):
    user_id, _ = require_role(("RadiationSafetyOfficer",))
    incident = get_or_404(db.spill_incidents, sid, "SpillIncident")
    data = body()
    to_state = req_string(data, "to_state")
    if to_state not in ("CONTAINED", "DECONTAMINATED", "CLEARED"):
        raise_error(ERR_VALIDATION, "to_state must be CONTAINED, DECONTAMINATED, or CLEARED")
    now = get_now()
    current = incident["status"]

    if current == "REPORTED" and to_state == "CONTAINED":
        incident["contained_at_dt"] = now
        incident["status"] = "CONTAINED"
        touch(incident)
        return success_object(spill_incident_out(incident), 200)

    if current == "CONTAINED" and to_state == "DECONTAMINATED":
        incident["decontaminated_at_dt"] = now
        incident["status"] = "DECONTAMINATED"
        touch(incident)
        return success_object(spill_incident_out(incident), 200)

    if current == "DECONTAMINATED" and to_state == "CONTAINED":
        surveys = [s for s in db.radiation_surveys.values()
                   if s["room_id"] == incident["room_id"]
                   and s["surveyed_at_dt"] >= incident["decontaminated_at_dt"]]
        if not surveys:
            raise_error(ERR_INVALID_STATE, "No survey recorded at or after decontaminated_at")
        latest = None
        for s in db.radiation_surveys.values():
            if s in surveys and (latest is None or s["surveyed_at_dt"] >= latest["surveyed_at_dt"]):
                latest = s
        if latest["result"] != "FAIL":
            raise_error(ERR_INVALID_STATE, "Recontamination requires a FAIL survey")
        incident["status"] = "CONTAINED"
        touch(incident)
        return success_object(spill_incident_out(incident), 200)

    if current == "DECONTAMINATED" and to_state == "CLEARED":
        # Validation priority: segregation of duties (14) precedes survey (24).
        if user_id == incident["reported_by_user_id"]:
            raise_error(ERR_SEGREGATION_OF_DUTIES, "Clearer must differ from reporter")
        surveys = [s for s in db.radiation_surveys.values()
                   if s["room_id"] == incident["room_id"]
                   and s["surveyed_at_dt"] >= incident["decontaminated_at_dt"]]
        if not surveys:
            raise_error(ERR_SURVEY_REQUIRED, "No room survey recorded at or after decontaminated_at")
        latest = None
        for s in db.radiation_surveys.values():
            if s in surveys and (latest is None or s["surveyed_at_dt"] >= latest["surveyed_at_dt"]):
                latest = s
        if latest["result"] != "PASS":
            raise_error(ERR_SURVEY_REQUIRED, "Latest room survey is not PASS")
        incident["cleared_at_dt"] = now
        incident["cleared_by_user_id"] = user_id
        incident["status"] = "CLEARED"
        touch(incident)
        # Room posture restore if no other non-CLEARED incident references this room.
        room = db.imaging_rooms.get(incident["room_id"])
        if room is not None:
            others = [i for i in db.spill_incidents.values()
                      if i["room_id"] == incident["room_id"] and i["status"] != "CLEARED"]
            if not others and room["status"] == "CONTAMINATED":
                room["status"] = "OPERATIONAL"
                touch(room)
        # Compensation: spill-held orders return; their quarantined vials restore.
        for order in db.dose_orders.values():
            if order["status"] == "ON_HOLD" and order.get("hold_reason") == "SPILL_CONTAMINATION":
                prev = order["hold_previous_status"]
                order["status"] = prev
                order["hold_reason"] = None
                order["hold_previous_status"] = None
                touch(order)
                if prev == "DOSE_PREPARED":
                    for vial in db.dose_vials.values():
                        if vial["order_id"] == order["id"] and vial["status"] == "QUARANTINED":
                            vial["status"] = "CALIBRATED"
                            touch(vial)
        return success_object(spill_incident_out(incident), 200)

    raise_error(ERR_INVALID_STATE, f"Cannot advance from {current} to {to_state}")


# ---------------------------------------------------------------------------
# Patient release instructions
# ---------------------------------------------------------------------------

RELEASE_DOSE_RATE_LIMIT_USV_H = Decimal("70")


@app.route(f"{PREFIX}/patient-release-instructions", methods=["POST"])
def create_patient_release_instruction():
    user_id, _ = require_role(("AuthorizedUser",))
    au = require_entity_backed_au(user_id)
    data = body()
    administration_id = req_string(data, "administration_id")
    variant = req_string(data, "evaluation_variant")
    if variant not in ("ACTIVITY_BASED", "MEASURED_RATE_BASED"):
        raise_error(ERR_VALIDATION, "evaluation_variant must be ACTIVITY_BASED or MEASURED_RATE_BASED")
    admin = get_or_404(db.dose_administrations, administration_id, "DoseAdministration")
    order = db.dose_orders[admin["order_id"]]
    if user_id != order["authorized_user_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "Only the prescribing AuthorizedUser may issue release instructions")
    now = get_now()
    if au["status"] != "ACTIVE" or now >= au["expires_at_dt"]:
        raise_error(ERR_USER_NOT_ACTIVE, "AuthorizedUser is not active")
    for existing in db.patient_release_instructions.values():
        if existing["administration_id"] == administration_id:
            raise_error(ERR_DUPLICATE_RELEASE_INSTRUCTION,
                        "A release instruction already exists for this administration")
    has_rate = "measured_dose_rate_at_1m_usv_h" in data and data["measured_dose_rate_at_1m_usv_h"] is not None
    if variant == "MEASURED_RATE_BASED" and not has_rate:
        raise_error(ERR_VALIDATION, "measured_dose_rate_at_1m_usv_h is required for MEASURED_RATE_BASED")
    if variant == "ACTIVITY_BASED" and has_rate:
        raise_error(ERR_VALIDATION, "measured_dose_rate_at_1m_usv_h must not be supplied for ACTIVITY_BASED")
    isotope = db.isotope_products[order["isotope_product_id"]]
    if variant == "ACTIVITY_BASED":
        releasable = dfrac(admin["assayed_activity_exact_mbq"]) <= dfrac(isotope["release_activity_limit_mbq"])
        measured_rate = None
    else:
        measured_rate = dfrac(data["measured_dose_rate_at_1m_usv_h"])
        releasable = measured_rate <= RELEASE_DOSE_RATE_LIMIT_USV_H
    if not releasable:
        raise_error(ERR_RELEASE_CRITERIA_NOT_MET, "Release criteria not met under the chosen variant")
    entity = {
        "id": str(uuid.uuid4()),
        "administration_id": administration_id,
        "evaluation_variant": variant,
        "measured_dose_rate_at_1m_usv_h": measured_rate,
        "releasable": True,
        "status": "ISSUED",
        "issued_by_user_id": user_id,
    }
    stamp_new(entity)
    db.patient_release_instructions[entity["id"]] = entity
    return success_object(patient_release_instruction_out(entity), 201)


@app.route(f"{PREFIX}/patient-release-instructions", methods=["GET"])
def list_patient_release_instructions():
    require_role(GET_ALL_ROLES)
    return list_response(db.patient_release_instructions, patient_release_instruction_out, {
        "administration_id": request.args.get("administration_id"),
    })


@app.route(f"{PREFIX}/patient-release-instructions/<pid>", methods=["GET"])
def get_patient_release_instruction(pid):
    require_role(GET_ALL_ROLES)
    entity = get_or_404(db.patient_release_instructions, pid, "PatientReleaseInstruction")
    return success_object(patient_release_instruction_out(entity), 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
