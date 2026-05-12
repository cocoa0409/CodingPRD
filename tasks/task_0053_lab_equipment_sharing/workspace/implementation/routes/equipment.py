"""Equipment endpoints."""
from flask import Blueprint, request, g

import db
from clock import iso, now, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list


bp = Blueprint("equipment", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


def _require_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise err("ERR_BAD_REQUEST", f"{key} is required and must be a string")
    return v


def _require_int(d, key, lo=None, hi=None):
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_BAD_REQUEST", f"{key} must be an integer")
    if lo is not None and v < lo:
        raise err("ERR_BAD_REQUEST", f"{key} must be >= {lo}")
    if hi is not None and v > hi:
        raise err("ERR_BAD_REQUEST", f"{key} must be <= {hi}")
    return v


def _require_enum(d, key, allowed):
    v = _require_str(d, key)
    if v not in allowed:
        raise err("ERR_BAD_REQUEST", f"{key} must be one of {sorted(allowed)}")
    return v


def _require_iso(d, key):
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise err("ERR_BAD_REQUEST", f"{key} is required (ISO 8601 timestamp)")
    try:
        return parse_iso(v)
    except ValueError:
        raise err("ERR_BAD_REQUEST", f"{key} is not a valid ISO 8601 timestamp")


def _require_array_str(d, key):
    v = d.get(key)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise err("ERR_BAD_REQUEST", f"{key} must be an array of strings")
    return list(v)


@bp.post("/equipment")
@require_auth(roles={"LabOwner"})
def create_equipment():
    body = _get_body()
    lab_id = _require_str(body, "lab_id")
    lab = db.labs.get(lab_id)
    if lab is None:
        raise err("ERR_NOT_FOUND", "lab not found")
    # LabOwner must be the contact_user_id of the lab
    if lab["contact_user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not the lab contact user")

    model = _require_str(body, "model")
    specification = _require_str(body, "specification")
    value_tier = _require_enum(body, "value_tier", {"STANDARD", "HIGH_VALUE"})
    sharing_scope = _require_enum(body, "sharing_scope", {"WITHIN_SCHOOL", "INTER_SCHOOL", "EXTERNAL"})
    slot_granularity = _require_enum(body, "slot_granularity", {"HOUR", "HALF_DAY", "DAY"})
    lead_time_hours = _require_int(body, "lead_time_hours", lo=0)
    single_user_duration_limit_hours = _require_int(body, "single_user_duration_limit_hours", lo=1)
    peak_window_start_hour = _require_int(body, "peak_window_start_hour", lo=0, hi=23)
    peak_window_end_hour = _require_int(body, "peak_window_end_hour", lo=1, hi=24)
    if peak_window_end_hour <= peak_window_start_hour:
        raise err("ERR_BAD_REQUEST", "peak_window_end_hour must be > peak_window_start_hour")

    calibration_cert_id = _require_str(body, "calibration_cert_id")
    calibration_expires_at = _require_iso(body, "calibration_expires_at")
    safety_inspection_cert_id = _require_str(body, "safety_inspection_cert_id")
    safety_inspection_expires_at = _require_iso(body, "safety_inspection_expires_at")
    photo_uri = _require_str(body, "photo_uri")
    operation_manual_uri = _require_str(body, "operation_manual_uri")
    required_training_codes = _require_array_str(body, "required_training_codes")
    allowed_sample_types = _require_array_str(body, "allowed_sample_types")

    # Certificates must be valid at registration time for status=AVAILABLE
    if calibration_expires_at <= now() or safety_inspection_expires_at <= now():
        raise err("ERR_CERTIFICATE_EXPIRED", "certificate expired at registration")

    eq = {
        "lab_id": lab_id,
        "model": model,
        "specification": specification,
        "value_tier": value_tier,
        "sharing_scope": sharing_scope,
        "slot_granularity": slot_granularity,
        "lead_time_hours": lead_time_hours,
        "single_user_duration_limit_hours": single_user_duration_limit_hours,
        "peak_window_start_hour": peak_window_start_hour,
        "peak_window_end_hour": peak_window_end_hour,
        "status": "AVAILABLE",
        "calibration_cert_id": calibration_cert_id,
        "calibration_expires_at": iso(calibration_expires_at),
        "safety_inspection_cert_id": safety_inspection_cert_id,
        "safety_inspection_expires_at": iso(safety_inspection_expires_at),
        "photo_uri": photo_uri,
        "operation_manual_uri": operation_manual_uri,
        "active_billing_rule_id": None,
        "required_training_codes": required_training_codes,
        "allowed_sample_types": allowed_sample_types,
    }
    db.stamp_create(eq)
    db.equipment[eq["id"]] = eq
    return success(db.public(eq), status=201)


@bp.get("/equipment/<equipment_id>")
@require_auth(roles={"PlatformAdmin", "LabOwner", "User"})
def get_equipment(equipment_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    return success(db.public(eq))


@bp.get("/equipment")
@require_auth(roles={"PlatformAdmin", "LabOwner", "User"})
def list_equipment():
    limit, offset = get_pagination()
    lab_id_f = request.args.get("lab_id")
    status_f = request.args.get("status")
    sharing_scope_f = request.args.get("sharing_scope")
    value_tier_f = request.args.get("value_tier")
    items = []
    for eq in db.equipment.values():
        if lab_id_f and eq["lab_id"] != lab_id_f:
            continue
        if status_f and eq["status"] != status_f:
            continue
        if sharing_scope_f and eq["sharing_scope"] != sharing_scope_f:
            continue
        if value_tier_f and eq["value_tier"] != value_tier_f:
            continue
        items.append(eq)
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([db.public(x) for x in page], limit, offset, total)


@bp.put("/equipment/<equipment_id>")
@require_auth(roles={"LabOwner"})
def update_equipment(equipment_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    lab = db.labs.get(eq["lab_id"])
    if lab is None or lab["contact_user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not the lab owner of this equipment")

    body = _get_body()

    # OCC
    if "version" in body and body["version"] is not None:
        if body["version"] != eq["version"]:
            raise err("ERR_VERSION_CONFLICT", "version mismatch")

    # status changes — handle RETIRED separately
    new_status = body.get("status")
    if new_status is not None:
        if new_status not in ("AVAILABLE", "MAINTENANCE", "RETIRED"):
            raise err("ERR_BAD_REQUEST", "status must be AVAILABLE|MAINTENANCE|RETIRED")
        if new_status == "RETIRED":
            if eq["status"] == "RETIRED":
                raise err("ERR_INVALID_STATE", "already RETIRED")
            # No BOOKED/CHECKED_IN reservations remain
            for r in db.reservations.values():
                if r["equipment_id"] == equipment_id and r["status"] in ("BOOKED", "CHECKED_IN"):
                    raise err("ERR_INVALID_STATE", "active reservations exist")
            eq["status"] = "RETIRED"
            # Cascade SCHEDULED maintenance windows -> REJECTED
            for mw in db.maintenance_windows.values():
                if mw["equipment_id"] == equipment_id and mw["status"] == "SCHEDULED":
                    mw["status"] = "REJECTED"
                    db.stamp_update(mw)
        elif new_status == "AVAILABLE":
            # Must have valid certificates
            if parse_iso(eq["calibration_expires_at"]) <= now() or \
               parse_iso(eq["safety_inspection_expires_at"]) <= now():
                raise err("ERR_CERTIFICATE_EXPIRED", "certificate expired")
            eq["status"] = "AVAILABLE"
        else:
            eq["status"] = new_status

    if "single_user_duration_limit_hours" in body and body["single_user_duration_limit_hours"] is not None:
        v = body["single_user_duration_limit_hours"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise err("ERR_BAD_REQUEST", "single_user_duration_limit_hours must be positive integer")
        eq["single_user_duration_limit_hours"] = v
    if "peak_window_start_hour" in body and body["peak_window_start_hour"] is not None:
        v = body["peak_window_start_hour"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 23:
            raise err("ERR_BAD_REQUEST", "peak_window_start_hour must be 0..23")
        eq["peak_window_start_hour"] = v
    if "peak_window_end_hour" in body and body["peak_window_end_hour"] is not None:
        v = body["peak_window_end_hour"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 24:
            raise err("ERR_BAD_REQUEST", "peak_window_end_hour must be 1..24")
        eq["peak_window_end_hour"] = v
    if eq["peak_window_end_hour"] <= eq["peak_window_start_hour"]:
        raise err("ERR_BAD_REQUEST", "peak_window_end_hour must be > peak_window_start_hour")

    db.stamp_update(eq)
    return success(db.public(eq))
