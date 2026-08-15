"""Engineer, JigSetup, CraneResource, and CraneSlot endpoints."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CRANE_SLOT_OVERLAP, \
    ERR_SLOT_IN_PAST, ERR_STALE_CRANE_VERSION
from middleware import authenticate, require_role, get_or_404, INTERNAL_ROLES
from response import success, success_list
from services import serializers
from util import as_dt, as_enum, as_fk, as_int, as_str, body, paginate

bp = Blueprint("master_data", __name__)

SEAL_AUTHORITIES = {"TRUSS_ONLY", "TRUSS_AND_PANEL"}
COMPONENT_TYPES = {"FLOOR_TRUSS", "ROOF_TRUSS", "WALL_PANEL"}
PLATE_CLASSES = {"P20", "P18", "P16"}
CRANE_CLASSES = {"LIGHT", "STANDARD", "HEAVY"}
SLOT_PURPOSES = {"BUILD_PICK", "LOAD_PICK"}
SLOT_STATES = {"BOOKED", "COMPLETED", "CANCELLED"}
CRANE_STATES = {"ACTIVE", "OUT_OF_SERVICE"}


# ---------------------------------------------------------------------------
# Engineers
# ---------------------------------------------------------------------------

@bp.route("/plant/engineers", methods=["POST"])
def create_engineer():
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    data = body()
    rec = db.new_record({
        "full_name": as_str(data.get("full_name"), "full_name", required=True),
        "license_number": as_str(data.get("license_number"), "license_number", required=True),
        "license_state": as_str(data.get("license_state"), "license_state", required=True),
        "license_expiry": as_dt(data.get("license_expiry"), "license_expiry", required=True),
        "seal_authority": as_enum(data.get("seal_authority"), "seal_authority", SEAL_AUTHORITIES, required=True),
    })
    db.engineers[rec["id"]] = rec
    return success(serializers.engineer(rec), status=201)


@bp.route("/plant/engineers/<eid>", methods=["GET"])
def get_engineer(eid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.engineer(get_or_404(db.engineers, eid, "engineer")))


@bp.route("/plant/engineers", methods=["GET"])
def list_engineers():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.engineers.values())
    raw = request.args.get("license_state")
    if raw is not None:
        records = [e for e in records if e["license_state"] == raw]
    page, meta = paginate(records)
    return success_list([serializers.engineer(e) for e in page], meta)


# ---------------------------------------------------------------------------
# Jig setups (immutable; common_fields false: id + created_at only)
# ---------------------------------------------------------------------------

@bp.route("/plant/jig-setups", methods=["POST"])
def create_jig():
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    data = body()
    setup_code = as_str(data.get("setup_code"), "setup_code", required=True)
    component_type = as_enum(data.get("component_type_supported"), "component_type_supported",
                             COMPONENT_TYPES, required=True)
    plate_class = as_enum(data.get("plate_class"), "plate_class", PLATE_CLASSES, required=True)
    changeover = data.get("changeover_minutes_from")
    if changeover is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: changeover_minutes_from")
    if not isinstance(changeover, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "changeover_minutes_from must be an object")
    cleaned = {}
    for key, value in changeover.items():
        if not isinstance(key, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "changeover_minutes_from keys must be strings")
        cleaned[key] = as_int(value, f"changeover_minutes_from[{key}]", required=True)
    rec = db.new_record({
        "setup_code": setup_code,
        "component_type_supported": component_type,
        "plate_class": plate_class,
        "changeover_minutes_from": cleaned,
    }, common=False)
    db.jig_setups[rec["id"]] = rec
    return success(serializers.jig_setup(rec), status=201)


@bp.route("/plant/jig-setups/<jid>", methods=["GET"])
def get_jig(jid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.jig_setup(get_or_404(db.jig_setups, jid, "jig setup")))


@bp.route("/plant/jig-setups", methods=["GET"])
def list_jigs():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.jig_setups.values())
    raw = request.args.get("component_type_supported")
    if raw is not None:
        records = [j for j in records if j["component_type_supported"] == raw]
    page, meta = paginate(records)
    return success_list([serializers.jig_setup(j) for j in page], meta)


# ---------------------------------------------------------------------------
# Cranes
# ---------------------------------------------------------------------------

@bp.route("/plant/cranes", methods=["POST"])
def create_crane():
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    data = body()
    rec = db.new_record({
        "crane_code": as_str(data.get("crane_code"), "crane_code", required=True),
        "capacity_lbs": as_int(data.get("capacity_lbs"), "capacity_lbs", required=True),
        "crane_class": as_enum(data.get("crane_class"), "crane_class", CRANE_CLASSES, required=True),
        "hourly_rate_cents": as_int(data.get("hourly_rate_cents"), "hourly_rate_cents", required=True),
        "status": "ACTIVE",
    })
    db.cranes[rec["id"]] = rec
    return success(serializers.crane(rec), status=201)


@bp.route("/plant/cranes/<cid>", methods=["GET"])
def get_crane(cid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.crane(get_or_404(db.cranes, cid, "crane")))


@bp.route("/plant/cranes", methods=["GET"])
def list_cranes():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.cranes.values())
    raw_status = request.args.get("status")
    if raw_status is not None:
        records = [c for c in records if c["status"] == raw_status]
    raw_class = request.args.get("crane_class")
    if raw_class is not None:
        records = [c for c in records if c["crane_class"] == raw_class]
    page, meta = paginate(records)
    return success_list([serializers.crane(c) for c in page], meta)


@bp.route("/plant/cranes/<cid>/transition", methods=["POST"])
def crane_transition(cid):
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    rec = get_or_404(db.cranes, cid, "crane")
    data = body()
    to_state = as_enum(data.get("to_state"), "to_state", CRANE_STATES, required=True)
    if (rec["status"], to_state) not in (("ACTIVE", "OUT_OF_SERVICE"), ("OUT_OF_SERVICE", "ACTIVE")):
        raise ApiError(ERR_INVALID_STATE, 409, f"crane transition {rec['status']} -> {to_state} is not declared")
    rec["status"] = to_state
    db.touch(rec)
    return success(serializers.crane(rec))


# ---------------------------------------------------------------------------
# Crane slots: buffered half-open intervals (calculation crane_slot_feasibility)
# ---------------------------------------------------------------------------

@bp.route("/plant/crane-slots", methods=["POST"])
def create_crane_slot():
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    data = body()
    # Existence layer: body FKs in declared input order.
    crane = as_fk(data.get("crane_id"), "crane_id", db.cranes, "crane")
    batch_ref = as_fk(data.get("production_batch_id"), "production_batch_id",
                      db.production_batches, "production batch")
    load_ref = as_fk(data.get("delivery_load_id"), "delivery_load_id",
                     db.delivery_loads, "delivery load")
    # Schema layer.
    if crane is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: crane_id")
    purpose = as_enum(data.get("purpose"), "purpose", SLOT_PURPOSES, required=True)
    start_at = as_dt(data.get("start_at"), "start_at", required=True)
    end_at = as_dt(data.get("end_at"), "end_at", required=True)
    expected_crane_version = as_int(data.get("expected_crane_version"), "expected_crane_version", required=True)
    if end_at <= start_at:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_at must be strictly after start_at")
    # OCC (priority 6).
    if expected_crane_version != crane["version"]:
        raise ApiError(ERR_STALE_CRANE_VERSION, 412, "crane version has advanced since last read")
    # Buffered half-open overlap (priority 21); CANCELLED slots occupy nothing.
    from datetime import timedelta
    buffer = timedelta(minutes=30)
    for existing in db.crane_slots.values():
        if existing["crane_id"] != crane["id"] or existing["status"] not in ("BOOKED", "COMPLETED"):
            continue
        if not (start_at >= existing["end_at"] + buffer or end_at <= existing["start_at"] - buffer):
            raise ApiError(ERR_CRANE_SLOT_OVERLAP, 409, "slot violates the buffered interval rule on this crane")
    # Crane must be ACTIVE (priority 22).
    if crane["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "crane is not ACTIVE")
    # Slot must not start in the past (priority 33); equal to the clock is valid.
    if start_at < db.get_clock():
        raise ApiError(ERR_SLOT_IN_PAST, 422, "start_at is before the current logical clock")
    rec = db.new_record({
        "crane_id": crane["id"],
        "purpose": purpose,
        "production_batch_id": batch_ref["id"] if batch_ref else None,
        "delivery_load_id": load_ref["id"] if load_ref else None,
        "start_at": start_at,
        "end_at": end_at,
        "status": "BOOKED",
    })
    db.crane_slots[rec["id"]] = rec
    db.touch(crane)  # booking increments the crane's version
    return success(serializers.crane_slot(rec), status=201)


@bp.route("/plant/crane-slots/<sid>", methods=["GET"])
def get_crane_slot(sid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.crane_slot(get_or_404(db.crane_slots, sid, "crane slot")))


@bp.route("/plant/crane-slots", methods=["GET"])
def list_crane_slots():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.crane_slots.values())
    for field in ("crane_id", "production_batch_id", "delivery_load_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [s for s in records if s[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.crane_slot(s) for s in page], meta)


@bp.route("/plant/crane-slots/<sid>/transition", methods=["POST"])
def crane_slot_transition(sid):
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    rec = get_or_404(db.crane_slots, sid, "crane slot")
    data = body()
    to_state = as_enum(data.get("to_state"), "to_state", SLOT_STATES, required=True)
    if (rec["status"], to_state) not in (("BOOKED", "COMPLETED"), ("BOOKED", "CANCELLED")):
        raise ApiError(ERR_INVALID_STATE, 409, f"crane slot transition {rec['status']} -> {to_state} is not declared")
    rec["status"] = to_state
    db.touch(rec)
    return success(serializers.crane_slot(rec))
