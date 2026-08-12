"""Clock, PlantUnit, Personnel endpoints."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_CLOCK_REGRESSION, ERR_UNIT_CODE_EXISTS,
    ERR_EMPLOYEE_REF_EXISTS,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_int, f_num, f_bool, f_enum, f_list, f_day, fmt_day,
)
from services import (
    new_entity, touch, get_unit, get_person, study_of_unit, compute_study_dues,
    recompute_unit, sweep, ser_unit, ser_personnel, sorted_rows,
)

bp = Blueprint("core", __name__)

QUALIFICATIONS = ["MECHANICAL", "CHEMICAL", "ELECTRICAL", "PROCESS", "HAZOP_LEADER", "PSSR_CERTIFIED"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/psm/_clock/set_current_utc")
@require_roles("PsmAdmin")
def set_clock():
    b = body_json()
    raw = b.get("to_iso8601")
    if raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: to_iso8601", 400)
    from helpers import parse_day
    day = parse_day(raw)
    if day is None:
        raise ApiError(ERR_INVALID_REQUEST, "Field to_iso8601 must be a valid ISO 8601 instant", 400)
    if day < store.clock:
        raise ApiError(ERR_CLOCK_REGRESSION, "Logical clock cannot move backward", 409)
    store.clock = day
    sweep()
    return ok({"current_utc": fmt_day(store.clock)}, 200)


# ---------------------------------------------------------------------------
# PlantUnit
# ---------------------------------------------------------------------------

def _unit_config(b, existing=None):
    """Validate/merge unit config fields. `existing` None -> create (required fields)."""
    creating = existing is None
    out = {}
    if creating:
        out["name"] = f_str(b, "name")
        out["unit_code"] = f_str(b, "unit_code")
        out["pha_cycle_months"] = f_int(b, "pha_cycle_months", lo=12, hi=60)
    else:
        if "name" in b:
            out["name"] = f_str(b, "name")
        if "pha_cycle_months" in b:
            out["pha_cycle_months"] = f_int(b, "pha_cycle_months", lo=12, hi=60)
    for fname in ("temp_moc_max_days", "max_extensions", "extension_max_days", "total_temp_cap_days"):
        if fname in b:
            out[fname] = f_int(b, fname)
    if "training_coverage_threshold_pct" in b:
        out["training_coverage_threshold_pct"] = f_num(b, "training_coverage_threshold_pct")
    return out


@bp.post("/psm/units")
@require_roles("PsmAdmin")
def create_unit():
    b = body_json()
    cfg = _unit_config(b)
    if any(u["unit_code"] == cfg["unit_code"] for u in store.units.values()):
        raise ApiError(ERR_UNIT_CODE_EXISTS, "unit_code already taken", 409)
    u = new_entity()
    u.update({
        "name": cfg["name"],
        "unit_code": cfg["unit_code"],
        "pha_cycle_months": cfg["pha_cycle_months"],
        "temp_moc_max_days": cfg.get("temp_moc_max_days", 180),
        "max_extensions": cfg.get("max_extensions", 2),
        "extension_max_days": cfg.get("extension_max_days", 90),
        "total_temp_cap_days": cfg.get("total_temp_cap_days", 360),
        "training_coverage_threshold_pct": cfg.get("training_coverage_threshold_pct", 100.00),
        "open_action_count": 0,
        "overdue_action_count": 0,
        "process_safety_index": 0,
        "psm_posture": "NORMAL",
    })
    store.units[u["id"]] = u
    return ok(ser_unit(u), 201)


@bp.get("/psm/units")
@require_roles(*ALL_ROLES)
def list_units():
    limit, offset = pagination_params()
    rows = [ser_unit(u) for u in sorted_rows(store.units.values())]
    return ok_list(rows, limit, offset)


@bp.get("/psm/units/<uid>")
@require_roles(*ALL_ROLES)
def get_one_unit(uid):
    return ok(ser_unit(get_unit(uid)), 200)


@bp.patch("/psm/units/<uid>")
@require_roles("PsmAdmin")
def update_unit(uid):
    u = get_unit(uid)
    b = body_json()
    cfg = _unit_config(b, existing=u)
    u.update(cfg)
    touch(u)
    study = study_of_unit(u["id"])
    if study is not None:
        before = (study["nominal_next_due"], study["risk_accelerated_due"], study["effective_next_due"])
        compute_study_dues(study, u)
        after = (study["nominal_next_due"], study["risk_accelerated_due"], study["effective_next_due"])
        if after != before:
            touch(study)
    recompute_unit(u)
    return ok(ser_unit(u), 200)


# ---------------------------------------------------------------------------
# Personnel
# ---------------------------------------------------------------------------

@bp.post("/psm/personnel")
@require_roles("PsmAdmin")
def create_personnel():
    b = body_json()
    full_name = f_str(b, "full_name")
    employee_ref = f_str(b, "employee_ref")
    quals = f_list(b, "qualifications", required=False) or []
    for q in quals:
        if q not in QUALIFICATIONS:
            raise ApiError(ERR_INVALID_REQUEST, f"Unknown qualification: {q}", 400)
    active = f_bool(b, "active", required=False)
    if any(p["employee_ref"] == employee_ref for p in store.personnel.values()):
        raise ApiError(ERR_EMPLOYEE_REF_EXISTS, "employee_ref already taken", 409)
    p = new_entity()
    p.update({
        "full_name": full_name,
        "employee_ref": employee_ref,
        "qualifications": list(quals),
        "active": True if active is None else active,
    })
    store.personnel[p["id"]] = p
    return ok(ser_personnel(p), 201)


@bp.get("/psm/personnel")
@require_roles(*ALL_ROLES)
def list_personnel():
    limit, offset = pagination_params()
    rows = [ser_personnel(p) for p in sorted_rows(store.personnel.values())]
    return ok_list(rows, limit, offset)


@bp.get("/psm/personnel/<pid>")
@require_roles(*ALL_ROLES)
def get_one_personnel(pid):
    return ok(ser_personnel(get_person(pid)), 200)
