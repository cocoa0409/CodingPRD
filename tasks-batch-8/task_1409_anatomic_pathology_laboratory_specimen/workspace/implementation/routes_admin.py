"""Admin-surface routes: patients, pathologists, coverage windows,
reflex rules, and the test-driving logical clock."""
from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    qparam,
    auth, require_role, payload, ok, paginate,
    need_str, need_enum, need_int, need_dt, opt_bool, occ_int, now,
)
import calc
from calc import new_entity, bump

bp = Blueprint("admin", __name__)


def _not_found(what="Resource"):
    raise ApiError("ERR_NOT_FOUND", 404, "%s does not exist" % what)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@bp.post("/pathology/patients")
def create_patient():
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    mrn = need_str(body, "mrn")
    full_name = need_str(body, "full_name")
    dob = need_str(body, "date_of_birth")
    from helpers import valid_date_str
    if not valid_date_str(dob):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "date_of_birth must be YYYY-MM-DD")
    if any(p["mrn"] == mrn for p in db.patients.values()):
        raise ApiError("ERR_DUPLICATE_MRN", 409, "mrn already registered")
    p = new_entity()
    p.update({"mrn": mrn, "full_name": full_name, "date_of_birth": dob})
    db.patients[p["id"]] = p
    return ok(calc.ser_patient(p), status=201)


@bp.get("/pathology/patients/<pid>")
def get_patient(pid):
    auth()
    p = db.patients.get(pid)
    if p is None:
        _not_found("Patient")
    return ok(calc.ser_patient(p))

# ---------------------------------------------------------------------------
# Pathologists
# ---------------------------------------------------------------------------

@bp.post("/pathology/pathologists")
def create_pathologist():
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    full_name = need_str(body, "full_name")
    subs = body.get("subspecialties")
    if not isinstance(subs, list) or len(subs) == 0 \
            or any(s not in calc.SUBSPECIALTIES for s in subs):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "subspecialties must be a non-empty array of valid members")
    active = opt_bool(body, "active", True)
    p = new_entity()
    p.update({"full_name": full_name, "subspecialties": list(subs),
              "active": active, "last_assigned_at": None})
    db.pathologists[p["id"]] = p
    return ok(calc.ser_pathologist(p), status=201)


@bp.get("/pathology/pathologists/<pid>")
def get_pathologist(pid):
    auth()
    p = db.pathologists.get(pid)
    if p is None:
        _not_found("Pathologist")
    return ok(calc.ser_pathologist(p))

# ---------------------------------------------------------------------------
# Coverage windows
# ---------------------------------------------------------------------------

@bp.post("/pathology/pathologists/<pid>/coverage-windows")
def create_coverage_window(pid):
    from datetime import timedelta
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    window_type = need_enum(body, "window_type", calc.WINDOW_TYPES)
    start_at = need_dt(body, "start_at")
    end_at = need_dt(body, "end_at")
    if not end_at > start_at:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "end_at must be strictly after start_at")
    p = db.pathologists.get(pid)
    if p is None:
        _not_found("Pathologist")
    existing = [w for w in db.coverage_windows.values()
                if w["pathologist_id"] == pid and w["status"] == "ACTIVE"]
    if window_type == "CONSULT_SERVICE":
        # half-open [start, end) overlap; touching endpoints allowed
        for w in existing:
            if w["window_type"] != "CONSULT_SERVICE":
                continue
            if start_at < w["end_at"] and w["start_at"] < end_at:
                raise ApiError("ERR_COVERAGE_WINDOW_OVERLAP", 409,
                               "CONSULT_SERVICE window overlaps an existing one")
    else:  # UNAVAILABLE: >= 60 minutes buffer from every ACTIVE CONSULT_SERVICE
        for w in existing:
            if w["window_type"] != "CONSULT_SERVICE":
                continue
            gap = max(start_at - w["end_at"], w["start_at"] - end_at)
            if gap < timedelta(minutes=60):
                raise ApiError("ERR_UNAVAILABILITY_BUFFER_VIOLATION", 409,
                               "UNAVAILABLE window too close to consult duty")
    w = new_entity()
    w.update({"pathologist_id": pid, "window_type": window_type,
              "start_at": start_at, "end_at": end_at, "status": "ACTIVE"})
    db.coverage_windows[w["id"]] = w
    return ok(calc.ser_coverage_window(w), status=201)


@bp.get("/pathology/pathologists/<pid>/coverage-windows")
def list_coverage_windows(pid):
    auth()
    p = db.pathologists.get(pid)
    if p is None:
        _not_found("Pathologist")
    items = [w for w in db.coverage_windows.values() if w["pathologist_id"] == pid]
    status = qparam("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, meta = paginate(items)
    return ok([calc.ser_coverage_window(w) for w in page],
              response_type="array", pagination=meta)


@bp.post("/pathology/coverage-windows/<wid>/cancel")
def cancel_coverage_window(wid):
    _, role = auth()
    require_role(role, "LabAdmin")
    w = db.coverage_windows.get(wid)
    if w is None:
        _not_found("CoverageWindow")
    if w["status"] != "ACTIVE":
        raise ApiError("ERR_COVERAGE_WINDOW_NOT_ACTIVE", 409,
                       "coverage window is not ACTIVE")
    w["status"] = "CANCELLED"
    bump(w)
    return ok(calc.ser_coverage_window(w))

# ---------------------------------------------------------------------------
# Reflex rules
# ---------------------------------------------------------------------------

def _check_duplicate_rule(trigger, result, followup, active, exclude_id=None):
    if not active:
        return
    for r in db.reflex_rules.values():
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["active"] and r["trigger_stain_type"] == trigger \
                and r["trigger_result"] == result \
                and r["followup_stain_type"] == followup:
            raise ApiError("ERR_DUPLICATE_REFLEX_RULE", 409,
                           "an ACTIVE rule with the same trigger/result/"
                           "followup triple already exists")


@bp.post("/pathology/reflex-rules")
def create_reflex_rule():
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    name = need_str(body, "name")
    trigger = need_enum(body, "trigger_stain_type", calc.STAIN_TYPES)
    result = need_enum(body, "trigger_result", calc.RESULT_VALUES)
    followup = need_enum(body, "followup_stain_type", calc.STAIN_TYPES)
    priority = need_int(body, "priority")
    active = opt_bool(body, "active", True)
    if followup == trigger:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "followup_stain_type must differ from trigger_stain_type")
    _check_duplicate_rule(trigger, result, followup, active)
    r = new_entity()
    r.update({"name": name, "trigger_stain_type": trigger,
              "trigger_result": result, "followup_stain_type": followup,
              "priority": priority, "active": active})
    db.reflex_rules[r["id"]] = r
    return ok(calc.ser_reflex_rule(r), status=201)


@bp.get("/pathology/reflex-rules/<rid>")
def get_reflex_rule(rid):
    auth()
    r = db.reflex_rules.get(rid)
    if r is None:
        _not_found("ReflexRule")
    return ok(calc.ser_reflex_rule(r))


@bp.get("/pathology/reflex-rules")
def list_reflex_rules():
    auth()
    items = list(db.reflex_rules.values())
    active = qparam("active")
    if active is not None:
        want = active.lower() == "true"
        items = [r for r in items if r["active"] == want]
    page, meta = paginate(items)
    return ok([calc.ser_reflex_rule(r) for r in page],
              response_type="array", pagination=meta)


@bp.put("/pathology/reflex-rules/<rid>")
def update_reflex_rule(rid):
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    expected = occ_int(body, "expected_reflex_rule_version")
    # validate any provided optional fields (merged with stored values below)
    name = body.get("name")
    if name is not None and (not isinstance(name, str) or name == ""):
        raise ApiError("ERR_INVALID_REQUEST", 400, "name must be a non-empty string")
    trigger = body.get("trigger_stain_type")
    if trigger is not None and trigger not in calc.STAIN_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid trigger_stain_type")
    result = body.get("trigger_result")
    if result is not None and result not in calc.RESULT_VALUES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid trigger_result")
    followup = body.get("followup_stain_type")
    if followup is not None and followup not in calc.STAIN_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid followup_stain_type")
    priority = body.get("priority")
    if priority is not None and (isinstance(priority, bool)
                                 or not isinstance(priority, int)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "priority must be an integer")
    active = body.get("active")
    if active is not None and not isinstance(active, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "active must be a boolean")
    r = db.reflex_rules.get(rid)
    if r is None:
        _not_found("ReflexRule")
    # merged post-update values for the shape rule followup != trigger
    m_trigger = trigger if trigger is not None else r["trigger_stain_type"]
    m_followup = followup if followup is not None else r["followup_stain_type"]
    if m_trigger == m_followup:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "followup_stain_type must differ from trigger_stain_type")
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_reflex_rule_version does not match the "
                       "rule's current version")
    m_result = result if result is not None else r["trigger_result"]
    m_active = active if active is not None else r["active"]
    _check_duplicate_rule(m_trigger, m_result, m_followup, m_active,
                          exclude_id=r["id"])
    if name is not None:
        r["name"] = name
    if trigger is not None:
        r["trigger_stain_type"] = trigger
    if result is not None:
        r["trigger_result"] = result
    if followup is not None:
        r["followup_stain_type"] = followup
    if priority is not None:
        r["priority"] = priority
    if active is not None:
        r["active"] = active
    bump(r)
    return ok(calc.ser_reflex_rule(r))


@bp.post("/pathology/reflex-rules/<rid>/deactivate")
def deactivate_reflex_rule(rid):
    _, role = auth()
    require_role(role, "LabAdmin")
    r = db.reflex_rules.get(rid)
    if r is None:
        _not_found("ReflexRule")
    r["active"] = False
    bump(r)
    return ok(calc.ser_reflex_rule(r))

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/pathology/_clock/set_current_utc")
def set_clock():
    from helpers import need_dt as _need_dt, ts as _ts
    _, role = auth()
    require_role(role, "LabAdmin")
    body = payload()
    to = _need_dt(body, "to_iso8601")
    db.clock = to
    calc.run_clock_sweep()
    return ok({"current_utc": _ts(to)})
