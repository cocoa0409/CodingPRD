"""Regulators, roles, role requirements, curricula, curriculum versions, effectiveness."""
from flask import Blueprint

from db import new_entity, now, store, touch
from errors import ApiError, bad_request, not_found
from middleware import require_any_authenticated, require_roles
from response import (get_body, list_response, opt_decimal, opt_dt, opt_enum,
                      opt_int, opt_str, pub, req_decimal, req_dt, req_enum,
                      req_int, req_str, success)
from services import create_assignment, covering_assignment_exists

bp = Blueprint("admin", __name__)

DEADLINE_MODES = ("CALENDAR", "BUSINESS_DAYS")
RECURRENCES = ("INITIAL_ONLY", "VALIDITY_CYCLE")
CRITICALITIES = ("HARD", "SOFT")
EVIDENCE_REQS = ("NONE", "CERTIFICATE", "PROCTORED_CERTIFICATE")
REGULATOR_STATUSES = ("ACTIVE", "RETIRED")
CURRICULUM_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")


def get_regulator(rid):
    r = store.regulators.get(rid)
    if r is None:
        raise not_found("regulator not found")
    return r


def get_role(rid):
    r = store.roles.get(rid)
    if r is None:
        raise not_found("role not found")
    return r


def get_requirement(rid):
    r = store.requirements.get(rid)
    if r is None:
        raise not_found("requirement not found")
    return r


def get_curriculum(cid):
    c = store.curricula.get(cid)
    if c is None:
        raise not_found("curriculum not found")
    return c


def curriculum_view(c):
    """Serialize with the computed effective_recordkeeping_years (override beats regulator)."""
    out = pub(c)
    reg = store.regulators.get(c["regulator_id"])
    if c["recordkeeping_years_override"] is not None:
        out["effective_recordkeeping_years"] = c["recordkeeping_years_override"]
    else:
        out["effective_recordkeeping_years"] = reg["recordkeeping_years"] if reg else None
    return out


# ------------------------------------------------------------------ regulators

@bp.post("/regulators")
def create_regulator():
    require_roles("ComplianceAdmin")
    body = get_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    mode = req_enum(body, "deadline_mode", DEADLINE_MODES)
    keep_years = req_int(body, "recordkeeping_years", 1, 25)
    interval = opt_int(body, "escalation_interval_days", 1, 90, 10)
    reminder = opt_int(body, "reminder_days_before_due", 0, 30, 7)
    for r in store.regulators.values():
        if r["code"] == code:
            raise bad_request("code must be unique across regulators")
    r = new_entity()
    r.update({
        "code": code, "name": name, "deadline_mode": mode,
        "recordkeeping_years": keep_years,
        "escalation_interval_days": interval,
        "reminder_days_before_due": reminder,
        "status": "ACTIVE",
    })
    store.regulators[r["id"]] = r
    return success(pub(r), "object", 201)


@bp.get("/regulators/<rid>")
def read_regulator(rid):
    require_any_authenticated()
    return success(pub(get_regulator(rid)))


@bp.patch("/regulators/<rid>")
def update_regulator(rid):
    require_roles("ComplianceAdmin")
    body = get_body()
    if "deadline_mode" in body:
        raise bad_request("deadline_mode is immutable and never accepted by PATCH")
    expected = req_int(body, "expected_regulator_version")
    name = opt_str(body, "name") if "name" in body else None
    keep_years = opt_int(body, "recordkeeping_years", 1, 25)
    interval = opt_int(body, "escalation_interval_days", 1, 90)
    reminder = opt_int(body, "reminder_days_before_due", 0, 30)
    status = opt_enum(body, "status", REGULATOR_STATUSES)
    r = get_regulator(rid)
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", "regulator version is stale")
    if status is not None and status != r["status"]:
        if not (r["status"] == "ACTIVE" and status == "RETIRED"):
            raise ApiError("ERR_INVALID_STATE", "illegal regulator status transition")
    changed = False
    if name is not None and name != r["name"]:
        r["name"] = name
        changed = True
    if keep_years is not None and keep_years != r["recordkeeping_years"]:
        r["recordkeeping_years"] = keep_years
        changed = True
    if interval is not None and interval != r["escalation_interval_days"]:
        r["escalation_interval_days"] = interval
        changed = True
    if reminder is not None and reminder != r["reminder_days_before_due"]:
        r["reminder_days_before_due"] = reminder
        changed = True
    if status is not None and status != r["status"]:
        r["status"] = status
        changed = True
    touch(r)  # every successful PATCH increments version by 1
    return success(pub(r))


# ---------------------------------------------------------------------- roles

@bp.post("/roles")
def create_role():
    require_roles("ComplianceAdmin")
    body = get_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    for r in store.roles.values():
        if r["code"] == code:
            raise bad_request("code must be unique across roles")
    r = new_entity()
    r.update({"code": code, "name": name, "status": "ACTIVE"})
    store.roles[r["id"]] = r
    return success(pub(r), "object", 201)


@bp.get("/roles/<rid>")
def read_role(rid):
    require_any_authenticated()
    return success(pub(get_role(rid)))


@bp.post("/roles/<rid>/retire")
def retire_role(rid):
    require_roles("ComplianceAdmin")
    r = get_role(rid)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "only an ACTIVE role can be retired")
    r["status"] = "RETIRED"
    touch(r)
    return success(pub(r))


@bp.get("/roles/<rid>/employees")
def role_employees(rid):
    require_any_authenticated()
    get_role(rid)
    emps = [e for e in store.employees.values() if e["current_role_id"] == rid]
    emps.sort(key=lambda e: e["created_at"])
    return list_response(emps)


# -------------------------------------------------------------- requirements

@bp.post("/roles/<rid>/requirements")
def create_requirement(rid):
    require_roles("ComplianceAdmin")
    body = get_body()
    curriculum_id = req_str(body, "curriculum_id")
    recurrence = req_enum(body, "recurrence", RECURRENCES)
    due_in_days = req_int(body, "due_in_days", 1, 365)
    criticality = req_enum(body, "criticality", CRITICALITIES)
    role = get_role(rid)
    curr = store.curricula.get(curriculum_id)
    if curr is None:
        raise not_found("curriculum not found")
    for r in store.requirements.values():
        if (r["role_id"] == rid and r["curriculum_id"] == curriculum_id
                and r["status"] == "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_ACTIVE_REQUIREMENT",
                           "an ACTIVE requirement already exists for this role and curriculum")
    if curr["status"] != "ACTIVE":
        raise ApiError("ERR_CURRICULUM_NOT_ACTIVE", "curriculum must be ACTIVE")
    req = new_entity()
    req.update({
        "role_id": rid, "curriculum_id": curriculum_id, "recurrence": recurrence,
        "due_in_days": due_in_days, "criticality": criticality, "status": "ACTIVE",
    })
    store.requirements[req["id"]] = req
    # REQUIREMENT_SWEEP: seed every ACTIVE/ON_LEAVE employee currently holding the role.
    emps = [e for e in store.employees.values()
            if e["current_role_id"] == rid and e["status"] in ("ACTIVE", "ON_LEAVE")]
    emps.sort(key=lambda e: e["created_at"])
    for emp in emps:
        if not covering_assignment_exists(emp["id"], curriculum_id):
            create_assignment(emp, req, "REQUIREMENT_SWEEP")
    return success(pub(req), "object", 201)


@bp.get("/roles/<rid>/requirements")
def list_role_requirements(rid):
    require_any_authenticated()
    get_role(rid)
    reqs = [r for r in store.requirements.values() if r["role_id"] == rid]
    reqs.sort(key=lambda r: r["created_at"])
    return list_response(reqs)


@bp.post("/requirements/<rid>/retire")
def retire_requirement(rid):
    require_roles("ComplianceAdmin")
    r = get_requirement(rid)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "only an ACTIVE requirement can be retired")
    r["status"] = "RETIRED"
    touch(r)
    return success(pub(r))


@bp.get("/curricula/<cid>/requirements")
def list_curriculum_requirements(cid):
    require_any_authenticated()
    get_curriculum(cid)
    reqs = [r for r in store.requirements.values() if r["curriculum_id"] == cid]
    reqs.sort(key=lambda r: r["created_at"])
    return list_response(reqs)


# ------------------------------------------------------------------ curricula

@bp.post("/curricula")
def create_curriculum():
    require_roles("ComplianceAdmin")
    body = get_body()
    regulator_id = req_str(body, "regulator_id")
    code = req_str(body, "code")
    title = req_str(body, "title")
    passing = req_decimal(body, "passing_score_pct", 0, 100, 2)
    validity = req_int(body, "validity_months", 1, 120)
    evidence = req_enum(body, "evidence_requirement", EVIDENCE_REQS)
    max_attempts = opt_int(body, "max_attempts", 1, 10, 3)
    override = None
    if "recordkeeping_years_override" in body and body["recordkeeping_years_override"] is not None:
        override = req_int(body, "recordkeeping_years_override", 1, 25)
    reg = store.regulators.get(regulator_id)
    if reg is None:
        raise not_found("regulator not found")
    for c in store.curricula.values():
        if c["code"] == code:
            raise bad_request("code must be unique across curricula")
    if reg["status"] != "ACTIVE":
        raise ApiError("ERR_REGULATOR_RETIRED", "regulator is RETIRED")
    c = new_entity()
    c.update({
        "regulator_id": regulator_id, "code": code, "title": title,
        "passing_score_pct": passing, "validity_months": validity,
        "max_attempts": max_attempts, "evidence_requirement": evidence,
        "recordkeeping_years_override": override,
        "status": "DRAFT",
    })
    store.curricula[c["id"]] = c
    return success(curriculum_view(c), "object", 201)


@bp.get("/curricula")
def list_curricula():
    require_any_authenticated()
    from flask import request
    from response import pagination_params
    reg_filter = request.args.get("regulator_id")
    items = [c for c in store.curricula.values()
             if reg_filter is None or c["regulator_id"] == reg_filter]
    items.sort(key=lambda c: c["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success([curriculum_view(c) for c in page], "array", 200, {
        "limit": limit, "offset": offset, "total_count": total,
        "has_more": (offset + len(page)) < total,
    })


@bp.get("/curricula/<cid>")
def read_curriculum(cid):
    require_any_authenticated()
    return success(curriculum_view(get_curriculum(cid)))


@bp.patch("/curricula/<cid>")
def update_curriculum(cid):
    require_roles("ComplianceAdmin")
    body = get_body()
    expected = req_int(body, "expected_curriculum_version")
    passing = opt_decimal(body, "passing_score_pct", 0, 100, 2)
    validity = opt_int(body, "validity_months", 1, 120)
    max_attempts = opt_int(body, "max_attempts", 1, 10)
    override_marker = object()
    override = override_marker
    if "recordkeeping_years_override" in body:
        v = body["recordkeeping_years_override"]
        if v is None:
            override = None  # JSON null clears the override
        else:
            override = req_int(body, "recordkeeping_years_override", 1, 25)
    status = opt_enum(body, "status", CURRICULUM_STATUSES)
    c = get_curriculum(cid)
    if expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", "curriculum version is stale")
    if status is not None and status != c["status"]:
        legal = ((c["status"] == "DRAFT" and status in ("ACTIVE", "RETIRED"))
                 or (c["status"] == "ACTIVE" and status == "RETIRED"))
        if not legal:
            raise ApiError("ERR_INVALID_STATE", "illegal curriculum status transition")
        if c["status"] == "DRAFT" and status == "ACTIVE":
            # Regulatory gates, in PRD order: effective version first, then regulator.
            t = now()
            effective = any(v["curriculum_id"] == cid and v["effective_from"] <= t
                            and (v["effective_to"] is None or v["effective_to"] > t)
                            for v in store.versions.values())
            if not effective:
                raise ApiError("ERR_NO_EFFECTIVE_VERSION",
                               "no currently-effective curriculum version")
            reg = store.regulators.get(c["regulator_id"])
            if reg is None or reg["status"] != "ACTIVE":
                raise ApiError("ERR_REGULATOR_RETIRED", "owning regulator is RETIRED")
    if passing is not None:
        c["passing_score_pct"] = passing
    if validity is not None:
        c["validity_months"] = validity
    if max_attempts is not None:
        c["max_attempts"] = max_attempts
    if override is not override_marker:
        c["recordkeeping_years_override"] = override
    if status is not None and status != c["status"]:
        c["status"] = status
    touch(c)
    return success(curriculum_view(c))


@bp.post("/curricula/<cid>/versions")
def create_version(cid):
    require_roles("ComplianceAdmin")
    body = get_body()
    version_no = req_int(body, "version_no", 1)
    eff_from = req_dt(body, "effective_from")
    eff_to = opt_dt(body, "effective_to")
    content_uri = req_str(body, "content_uri")
    c = get_curriculum(cid)
    if c["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE", "versions cannot be added to a RETIRED curriculum")
    for v in store.versions.values():
        if v["curriculum_id"] == cid and v["version_no"] == version_no:
            raise ApiError("ERR_VERSION_NUMBER_CONFLICT", "version_no already used")
    # Half-open windows [from, to): touching is allowed, true overlap is not.
    for v in store.versions.values():
        if v["curriculum_id"] != cid:
            continue
        new_end = eff_to if eff_to is not None else None
        old_end = v["effective_to"]
        overlap = (old_end is None or eff_from < old_end) and \
                  (new_end is None or v["effective_from"] < new_end)
        if overlap:
            raise ApiError("ERR_VERSION_WINDOW_OVERLAP", "version window overlaps an existing version")
    v = new_entity()
    v.update({
        "curriculum_id": cid, "version_no": version_no,
        "effective_from": eff_from, "effective_to": eff_to,
        "content_uri": content_uri,
    })
    store.versions[v["id"]] = v
    return success(pub(v), "object", 201)


@bp.get("/curricula/<cid>/versions")
def list_versions(cid):
    require_any_authenticated()
    get_curriculum(cid)
    vs = [v for v in store.versions.values() if v["curriculum_id"] == cid]
    vs.sort(key=lambda v: v["created_at"])
    return list_response(vs)


@bp.get("/curricula/<cid>/effectiveness")
def curriculum_effectiveness(cid):
    require_any_authenticated()
    get_curriculum(cid)
    from services import effectiveness
    return success(effectiveness(cid))
