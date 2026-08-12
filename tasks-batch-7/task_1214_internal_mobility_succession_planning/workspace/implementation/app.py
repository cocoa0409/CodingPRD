"""Internal Mobility & Succession Planning API (Flask, in-memory).

Task 1214. Mounted under /talent. All recorded timestamps derive from the
logical clock (default 2026-05-01T00:00:00Z), driven by
POST /talent/_clock/set_current_utc.
"""
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request, jsonify
from flask.json.provider import DefaultJSONProvider

import store as S

app = Flask(__name__)
app.url_map.strict_slashes = False


class _JSONProvider(DefaultJSONProvider):
    @staticmethod
    def _default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return DefaultJSONProvider.default(obj)

    def dumps(self, obj, **kwargs):
        kwargs.setdefault("default", self._default)
        return super().dumps(obj, **kwargs)


app.json = _JSONProvider(app)

ALL_ROLES = ["HRAdmin", "HRBusinessPartner", "TalentManager", "Manager", "Employee"]


# ---------------------------------------------------------------------------
# Error type + response envelope (SCAFFOLD §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(extra=None):
    m = {"api_request_id": S.request_id(), "api_request_timestamp": S.meta_timestamp()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def list_ok(rows, limit, offset, serializer):
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    data = [serializer(r) for r in page]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok(data, 200, "array", meta_extra)


@app.errorhandler(ApiError)
def handle_api_error(err):
    S.reset_request_dirty()
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    S.reset_request_dirty()
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    S.reset_request_dirty()
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_500(e):
    S.reset_request_dirty()
    app.logger.exception(e)
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"}}
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Request lifecycle: serialize requests (atomic cascades) + dirty-set hygiene
# ---------------------------------------------------------------------------
@app.before_request
def _begin():
    S.request_lock.acquire()
    S.reset_request_dirty()


@app.teardown_request
def _end(exc):
    S.reset_request_dirty()
    S.request_lock.release()


# ---------------------------------------------------------------------------
# Auth (PRD §2.1) — X-User-ID + X-User-Role on every request.
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in S.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unrecognized X-User-Role / X-User-ID headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted on this endpoint")


# ---------------------------------------------------------------------------
# Body validation (PRD §2.8 step 3) — required fields, enum members, no
# undeclared fields, scalar constraints; all failures ERR_INVALID_REQUEST.
# ---------------------------------------------------------------------------
def body(allowed_fields):
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for key in data:
        if key not in allowed_fields:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Undeclared field: {key}")
    return data


def req_field(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return data[field]


def v_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a non-empty string")
    return value


def v_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"Field {field} must be one of {sorted(allowed)}")
    return value


def v_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be <= {maximum}")
    return value


def v_date(value, field):
    if S.parse_date(value) is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO date (YYYY-MM-DD)")
    return value


def v_datetime(value, field):
    if S.parse_dt(value) is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 datetime")
    return value


def parse_pagination():
    args = request.args
    limit, offset = 10, 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Lookup helpers (path resolution, left to right)
# ---------------------------------------------------------------------------
def get_employee(eid):
    e = S.employees.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    return e


def get_role(rid):
    r = S.critical_roles.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CriticalRole not found")
    return r


def get_entry(eid):
    e = S.successor_entries.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "SuccessorEntry not found")
    return e


def get_plan(pid):
    p = S.development_plans.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DevelopmentPlan not found")
    return p


def get_vacancy(vid):
    v = S.vacancies.get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Vacancy not found")
    return v


def get_posting(pid):
    p = S.postings.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "InternalPosting not found")
    return p


def get_application(aid):
    a = S.applications.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PostingApplication not found")
    return a


def get_session(sid):
    s = S.calibration_sessions.get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CalibrationSession not found")
    return s


def get_cal_entry(eid):
    e = S.calibration_entries.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CalibrationEntry not found")
    return e


def get_cycle(cid):
    c = S.hipo_cycles.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "HiPoProgramCycle not found")
    return c


def get_nomination(nid):
    n = S.hipo_nominations.get(nid)
    if n is None:
        raise ApiError("ERR_NOT_FOUND", 404, "HiPoNomination not found")
    return n


def get_assessment(aid):
    a = S.retention_assessments.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "RetentionAssessment not found")
    return a


def get_snapshot(sid):
    s = S.diversity_snapshots.get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DiversitySnapshot not found")
    return s


# ===========================================================================
# Employee endpoints
# ===========================================================================
@app.route("/talent/employees", methods=["POST"])
def create_employee():
    uid, role = authenticate()
    authorize(role, ["HRAdmin"])
    data = body({"employee_code", "full_name", "department", "job_level", "hire_date",
                 "performance_rating", "demographic_group", "current_manager_id"})
    code = v_str(req_field(data, "employee_code"), "employee_code")
    full_name = v_str(req_field(data, "full_name"), "full_name")
    department = v_str(req_field(data, "department"), "department")
    job_level = v_int(req_field(data, "job_level"), "job_level", 1, 10)
    hire_date = v_date(req_field(data, "hire_date"), "hire_date")
    rating = v_enum(req_field(data, "performance_rating"), "performance_rating",
                    S.PERFORMANCE_RATINGS)
    demo = v_enum(data.get("demographic_group", "UNDISCLOSED"), "demographic_group",
                  S.DEMOGRAPHIC_GROUPS)
    manager_id = data.get("current_manager_id")
    if manager_id is not None:
        v_str(manager_id, "current_manager_id")
    # uniqueness of employee_code across all employees
    if any(e["employee_code"] == code for e in S.employees.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "employee_code must be unique")
    if manager_id is not None:
        mgr = S.employees.get(manager_id)
        if mgr is None:
            raise ApiError("ERR_NOT_FOUND", 404, "current_manager_id does not resolve")
        if mgr["employment_status"] != "ACTIVE":
            raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", 409, "Manager must be ACTIVE")
    emp = S.stamp_new({
        "id": S.new_id(),
        "employee_code": code,
        "full_name": full_name,
        "department": department,
        "job_level": job_level,
        "hire_date": hire_date,
        "demographic_group": demo,
        "performance_rating": rating,
        "rating_history": [],
        "current_manager_id": manager_id,
        "employment_status": "ACTIVE",
    })
    S.employees[emp["id"]] = emp
    S.commit()
    return ok(S.ser_employee(emp), 201)


@app.route("/talent/employees", methods=["GET"])
def list_employees():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.employees.values())
    if "department" in args:
        rows = [e for e in rows if e["department"] == args["department"]]
    if "employment_status" in args:
        rows = [e for e in rows if e["employment_status"] == args["employment_status"]]
    if "current_manager_id" in args:
        rows = [e for e in rows if e["current_manager_id"] == args["current_manager_id"]]
    return list_ok(rows, limit, offset, S.ser_employee)


@app.route("/talent/employees/<eid>", methods=["GET"])
def get_employee_ep(eid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_employee(get_employee(eid)))


@app.route("/talent/employees/<eid>/terminate", methods=["POST"])
def terminate_employee(eid):
    uid, role = authenticate()
    authorize(role, ["HRAdmin"])
    body(set())
    emp = get_employee(eid)
    if emp["employment_status"] != "ACTIVE":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Employee already TERMINATED")
    now = S.now_dt()

    # L1: the termination itself
    emp["employment_status"] = "TERMINATED"
    S.mark(emp)

    # L2: roles whose ACTIVE incumbent this was become VACANT
    vacated_roles = []
    for r in S.critical_roles.values():
        if r["incumbent_employee_id"] == emp["id"] and r["status"] == "ACTIVE":
            r["status"] = "VACANT"
            r["incumbent_employee_id"] = None
            S.mark(r)
            vacated_roles.append(r)

    # L3: auto-create a vacancy per newly VACANT role
    for r in vacated_roles:
        v = S.stamp_new({
            "id": S.new_id(),
            "critical_role_id": r["id"],
            "status": "OPEN",
            "fill_deadline": now + timedelta(days=S.FILL_WINDOW_DAYS),
            "filled_by_employee_id": None,
            "fill_source": None,
            "closed_reason": None,
        })
        S.vacancies[v["id"]] = v

    # L4: the employee's non-terminal slate entries become REMOVED
    affected_role_ids = []
    for e in S.successor_entries.values():
        if e["employee_id"] == emp["id"] and e["status"] in ("DRAFT", "ACTIVE", "SUSPENDED"):
            e["status"] = "REMOVED"
            S.mark(e)
            if e["critical_role_id"] not in affected_role_ids:
                affected_role_ids.append(e["critical_role_id"])

    # L5/L6: bench + posture recompute per affected role; newly-set alerts
    # fire the BENCH_THIN_AUTO retention cascade (inside recompute).
    for rid in affected_role_ids:
        S.recompute_role_bench(S.critical_roles[rid])

    # L7: non-terminal applications -> WITHDRAWN; nominations -> REMOVED
    for a in S.applications.values():
        if a["employee_id"] == emp["id"] and a["status"] not in (
                "OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED", "WITHDRAWN"):
            _leave_hold(a)
            a["status"] = "WITHDRAWN"
            S.mark(a)
    touched_cycles = set()
    for n in S.hipo_nominations.values():
        if n["employee_id"] == emp["id"] and n["status"] in (
                "NOMINATED", "ENDORSED", "ACTIVE", "UNDER_REVIEW"):
            n["status"] = "REMOVED"
            S.mark(n)
            touched_cycles.add(n["cycle_id"])
    for cid in touched_cycles:
        S.mark(S.hipo_cycles[cid])  # enrolled_count recomputed

    S.commit()
    return ok(S.ser_employee(emp))


def _leave_hold(a):
    """Clear hold bookkeeping when an application leaves MANAGER_HOLD."""
    if a["status"] == "MANAGER_HOLD":
        a["hold_at"] = None
        a["hold_expires_at"] = None
        a["hold_reason"] = None
        emp = S.employees.get(a["employee_id"])
        if emp is not None:
            S.mark(emp)  # active_hold_count recomputed (-1)


# ===========================================================================
# CriticalRole endpoints
# ===========================================================================
@app.route("/talent/critical-roles", methods=["POST"])
def create_role():
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"role_title", "department", "criticality_tier", "assessment_method"})
    title = v_str(req_field(data, "role_title"), "role_title")
    department = v_str(req_field(data, "department"), "department")
    tier = v_enum(req_field(data, "criticality_tier"), "criticality_tier", S.CRITICALITY_TIERS)
    method = v_enum(req_field(data, "assessment_method"), "assessment_method",
                    S.ASSESSMENT_METHODS_ROLE)
    r = S.stamp_new({
        "id": S.new_id(),
        "role_title": title,
        "department": department,
        "criticality_tier": tier,
        "assessment_method": method,
        "incumbent_employee_id": None,
        "status": "PROPOSED",
        "bench_strength": Decimal("0.00"),
        "bench_posture": "EMPTY",
        "posture_alert": False,
    })
    S.critical_roles[r["id"]] = r
    S.commit()
    return ok(S.ser_role(r), 201)


@app.route("/talent/critical-roles", methods=["GET"])
def list_roles():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.critical_roles.values())
    if "department" in args:
        rows = [r for r in rows if r["department"] == args["department"]]
    if "status" in args:
        rows = [r for r in rows if r["status"] == args["status"]]
    if "bench_posture" in args:
        rows = [r for r in rows if r["bench_posture"] == args["bench_posture"]]
    if "incumbent_employee_id" in args:
        rows = [r for r in rows if r["incumbent_employee_id"] == args["incumbent_employee_id"]]
    return list_ok(rows, limit, offset, S.ser_role)


@app.route("/talent/critical-roles/<rid>", methods=["GET"])
def get_role_ep(rid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_role(get_role(rid)))


def _occ_field(data):
    """Body-phase validation of the OCC field: non-optional, integer (400)."""
    expected = req_field(data, "expected_critical_role_version")
    v_int(expected, "expected_critical_role_version")
    return expected


def _check_occ(data, role):
    """Priority-6 OCC check, run after path resolution and state checks."""
    if data["expected_critical_role_version"] != role["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_critical_role_version does not match the role's current version")


@app.route("/talent/critical-roles/<rid>", methods=["PATCH"])
def patch_role(rid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"role_title", "department", "criticality_tier",
                 "expected_critical_role_version"})
    if "role_title" in data:
        v_str(data["role_title"], "role_title")
    if "department" in data:
        v_str(data["department"], "department")
    if "criticality_tier" in data:
        v_enum(data["criticality_tier"], "criticality_tier", S.CRITICALITY_TIERS)
    _occ_field(data)
    r = get_role(rid)
    _check_occ(data, r)
    if "role_title" in data:
        r["role_title"] = data["role_title"]
    if "department" in data:
        r["department"] = data["department"]
    if "criticality_tier" in data:
        r["criticality_tier"] = data["criticality_tier"]
    S.mark(r)
    S.commit()
    return ok(S.ser_role(r))


@app.route("/talent/critical-roles/<rid>/activate", methods=["POST"])
def activate_role(rid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"incumbent_employee_id"})
    incumbent = v_str(req_field(data, "incumbent_employee_id"), "incumbent_employee_id")
    r = get_role(rid)
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_ROLE_INVALID_STATE", 409, "Role is not PROPOSED")
    emp = S.employees.get(incumbent)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "incumbent_employee_id does not resolve")
    if emp["employment_status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", 409, "Incumbent must be an ACTIVE employee")
    r["incumbent_employee_id"] = incumbent
    r["status"] = "ACTIVE"
    S.mark(r)
    S.commit()
    return ok(S.ser_role(r))


@app.route("/talent/critical-roles/<rid>/retire", methods=["POST"])
def retire_role(rid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    r = get_role(rid)
    if r["status"] not in ("ACTIVE", "VACANT"):
        raise ApiError("ERR_ROLE_INVALID_STATE", 409, "Role cannot be retired from its status")
    for e in S.successor_entries.values():
        if e["critical_role_id"] == r["id"] and e["status"] in ("DRAFT", "ACTIVE", "SUSPENDED"):
            e["status"] = "REMOVED"
            S.mark(e)
    for v in S.vacancies.values():
        if v["critical_role_id"] == r["id"] and v["status"] == "OPEN":
            v["status"] = "CLOSED_UNFILLED"
            S.mark(v)
            for p in S.postings.values():
                if p["vacancy_id"] == v["id"] and p["status"] == "OPEN":
                    _close_posting(p)
    r["status"] = "RETIRED"
    S.mark(r)
    S.commit()
    return ok(S.ser_role(r))


def _close_posting(p):
    """OPEN posting -> CLOSED, rejecting its non-terminal applications."""
    p["status"] = "CLOSED"
    S.mark(p)
    for a in S.applications.values():
        if a["posting_id"] == p["id"] and a["status"] not in (
                "OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED", "WITHDRAWN"):
            _leave_hold(a)
            a["status"] = "REJECTED"
            S.mark(a)


# ===========================================================================
# SuccessorEntry endpoints
# ===========================================================================
@app.route("/talent/critical-roles/<rid>/successors", methods=["POST"])
def create_successor(rid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"employee_id", "readiness_rating", "slate_position",
                 "supersede_entry_id", "expected_critical_role_version"})
    employee_id = v_str(req_field(data, "employee_id"), "employee_id")
    readiness = v_enum(req_field(data, "readiness_rating"), "readiness_rating",
                       S.READINESS_RATINGS)
    slate_position = data.get("slate_position")
    if slate_position is not None:
        v_int(slate_position, "slate_position", 1, S.SLATE_MAX)
    supersede_id = data.get("supersede_entry_id")
    if supersede_id is not None:
        v_str(supersede_id, "supersede_entry_id")
    _occ_field(data)

    r = get_role(rid)
    # state: adding to a RETIRED role is rejected
    if r["status"] == "RETIRED":
        raise ApiError("ERR_ROLE_INVALID_STATE", 409, "Cannot add to a RETIRED role")
    # OCC guard
    _check_occ(data, r)
    # candidate must be an ACTIVE employee
    cand = S.employees.get(employee_id)
    if cand is None:
        raise ApiError("ERR_NOT_FOUND", 404, "employee_id does not resolve")
    if cand["employment_status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", 409, "Candidate must be an ACTIVE employee")
    # supersede target resolution
    target = None
    if supersede_id is not None:
        target = S.successor_entries.get(supersede_id)
        if target is None or target["critical_role_id"] != r["id"]:
            raise ApiError("ERR_NOT_FOUND", 404, "supersede_entry_id does not resolve on this role")
        if target["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_SUCCESSOR_INVALID_STATE", 409,
                           "Cannot supersede a terminal entry")
    # business constraints evaluated against the post-supersede slate
    current = S.non_terminal_entries(r["id"])
    effective = [e for e in current if target is None or e["id"] != target["id"]]
    if any(e["employee_id"] == employee_id for e in effective):
        raise ApiError("ERR_DUPLICATE_SLATE_ENTRY", 409,
                       "Employee already holds a non-terminal entry on this slate")
    if target is None and len(current) >= S.SLATE_MAX:
        raise ApiError("ERR_SLATE_FULL", 409, "Slate already holds SLATE_MAX entries")
    if slate_position is None:
        if target is not None:
            slate_position = target["slate_position"]  # inherit on supersede
        else:
            taken = {e["slate_position"] for e in effective}
            slate_position = next((p for p in range(1, S.SLATE_MAX + 1) if p not in taken), None)
    elif any(e["slate_position"] == slate_position for e in effective):
        raise ApiError("ERR_SLATE_POSITION_TAKEN", 409,
                       "slate_position is occupied on this slate")

    if target is not None:
        was_active = target["status"] == "ACTIVE"
        target["status"] = "REMOVED"
        S.mark(target)
    else:
        was_active = False

    entry = S.stamp_new({
        "id": S.new_id(),
        "critical_role_id": r["id"],
        "employee_id": employee_id,
        "readiness_rating": readiness,
        "slate_position": slate_position,
        "readiness_score": Decimal("0.00"),
        "status": "DRAFT",
        "suspension_reason": None,
        "supersedes_entry_id": target["id"] if target is not None else None,
    })
    entry["readiness_score"] = S.compute_readiness_score(entry)
    S.successor_entries[entry["id"]] = entry
    S.mark(r)  # slate creation increments the role version once
    if was_active:
        S.recompute_role_bench(r)  # supersede removed an ACTIVE entry
    S.commit()
    return ok(S.ser_successor(entry), 201)


@app.route("/talent/successors", methods=["GET"])
def list_successors():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.successor_entries.values())
    if "critical_role_id" in args:
        rows = [e for e in rows if e["critical_role_id"] == args["critical_role_id"]]
    if "employee_id" in args:
        rows = [e for e in rows if e["employee_id"] == args["employee_id"]]
    if "status" in args:
        rows = [e for e in rows if e["status"] == args["status"]]
    return list_ok(rows, limit, offset, S.ser_successor)


@app.route("/talent/successors/<eid>", methods=["GET"])
def get_successor_ep(eid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_successor(get_entry(eid)))


@app.route("/talent/successors/<eid>", methods=["PATCH"])
def patch_successor(eid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"readiness_rating", "status", "suspension_reason"})
    if not data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Nothing to update")
    if "readiness_rating" in data:
        v_enum(data["readiness_rating"], "readiness_rating", S.READINESS_RATINGS)
    target_status = data.get("status")
    if target_status is not None:
        v_enum(target_status, "status",
               {"DRAFT", "ACTIVE", "SUSPENDED", "REMOVED", "PROMOTED"})
    suspension_reason = data.get("suspension_reason")
    if suspension_reason is not None:
        v_enum(suspension_reason, "suspension_reason", S.SUSPENSION_REASONS)
    if target_status == "SUSPENDED" and suspension_reason is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "suspension_reason is required when suspending")

    entry = get_entry(eid)
    # entry-state check precedes the role-status check (PRD §3.2)
    if target_status == "ACTIVE":
        if entry["status"] not in ("DRAFT", "SUSPENDED"):
            raise ApiError("ERR_SUCCESSOR_INVALID_STATE", 409,
                           "Entry cannot be activated from its status")
        r = S.critical_roles[entry["critical_role_id"]]
        if r["status"] not in ("ACTIVE", "VACANT"):
            raise ApiError("ERR_ROLE_NOT_ACTIVE", 409,
                           "Role is not ACTIVE or VACANT")
    elif target_status == "SUSPENDED":
        if entry["status"] != "ACTIVE":
            raise ApiError("ERR_SUCCESSOR_INVALID_STATE", 409,
                           "Only an ACTIVE entry can be suspended")
    elif target_status is not None:
        raise ApiError("ERR_SUCCESSOR_INVALID_STATE", 409,
                       f"Cannot drive an entry to {target_status} via PATCH")
    else:
        # attribute-only update; terminal entries are frozen
        if entry["status"] in ("REMOVED", "PROMOTED"):
            raise ApiError("ERR_SUCCESSOR_INVALID_STATE", 409,
                           "Terminal entries cannot be updated")

    if "readiness_rating" in data:
        entry["readiness_rating"] = data["readiness_rating"]
    if target_status == "ACTIVE":
        entry["status"] = "ACTIVE"
        entry["suspension_reason"] = None
    elif target_status == "SUSPENDED":
        entry["status"] = "SUSPENDED"
        entry["suspension_reason"] = suspension_reason
    S.mark(entry)
    S.recompute_entry_score(entry)
    S.recompute_role_bench(S.critical_roles[entry["critical_role_id"]])
    S.commit()
    return ok(S.ser_successor(entry))


@app.route("/talent/successors/<eid>/remove", methods=["POST"])
def remove_successor(eid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    entry = get_entry(eid)
    if entry["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_SUCCESSOR_INVALID_STATE", 409, "Entry is terminal")
    was_active = entry["status"] == "ACTIVE"
    entry["status"] = "REMOVED"
    S.mark(entry)
    if was_active:
        S.recompute_role_bench(S.critical_roles[entry["critical_role_id"]])
    S.commit()
    return ok(S.ser_successor(entry))


# ===========================================================================
# DevelopmentPlan endpoints
# ===========================================================================
@app.route("/talent/successors/<eid>/development-plan", methods=["POST"])
def create_plan(eid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"target_readiness"})
    target = v_enum(req_field(data, "target_readiness"), "target_readiness",
                    S.READINESS_RATINGS)
    entry = get_entry(eid)
    if S.plan_of_entry(entry["id"]) is not None:
        raise ApiError("ERR_PLAN_ALREADY_EXISTS", 409,
                       "Successor entry already has a development plan")
    plan = S.stamp_new({
        "id": S.new_id(),
        "successor_entry_id": entry["id"],
        "target_readiness": target,
        "completion_pct": 0,
        "status": "DRAFT",
    })
    S.development_plans[plan["id"]] = plan
    S.recompute_entry_score(entry)  # plan create is a score trigger
    S.commit()
    return ok(S.ser_plan(plan), 201)


@app.route("/talent/successors/<eid>/development-plan", methods=["GET"])
def get_plan_of_entry(eid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    entry = get_entry(eid)
    limit, offset = parse_pagination()
    plan = S.plan_of_entry(entry["id"])
    rows = [plan] if plan is not None else []
    return list_ok(rows, limit, offset, S.ser_plan)


@app.route("/talent/development-plans/<pid>", methods=["PATCH"])
def patch_plan(pid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"completion_pct", "status"})
    if not data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Nothing to update")
    if "completion_pct" in data:
        v_int(data["completion_pct"], "completion_pct", 0, 100)
    target_status = data.get("status")
    if target_status is not None:
        v_enum(target_status, "status", {"DRAFT", "ACTIVE", "COMPLETED", "ABANDONED"})

    plan = get_plan(pid)
    entry = S.successor_entries[plan["successor_entry_id"]]

    if target_status == "ACTIVE":
        if plan["status"] != "DRAFT":
            raise ApiError("ERR_PLAN_INVALID_STATE", 409, "Plan is not DRAFT")
        if entry["status"] != "ACTIVE":
            raise ApiError("ERR_SUCCESSOR_INVALID_STATE", 409,
                           "Successor entry is not ACTIVE")
    elif target_status == "COMPLETED":
        if plan["status"] != "ACTIVE":
            raise ApiError("ERR_PLAN_INVALID_STATE", 409, "Plan is not ACTIVE")
        # completeness gate reads the post-update completion_pct
        new_pct = data.get("completion_pct", plan["completion_pct"])
        if new_pct != 100:
            raise ApiError("ERR_PLAN_INCOMPLETE", 409, "completion_pct is not 100")
    elif target_status == "ABANDONED":
        if plan["status"] not in ("DRAFT", "ACTIVE"):
            raise ApiError("ERR_PLAN_INVALID_STATE", 409, "Plan cannot be abandoned")
    elif target_status is not None:
        raise ApiError("ERR_PLAN_INVALID_STATE", 409,
                       f"Cannot drive a plan to {target_status} via PATCH")

    if "completion_pct" in data:
        plan["completion_pct"] = data["completion_pct"]
    if target_status is not None:
        plan["status"] = target_status
    S.mark(plan)
    # completion auto-upgrades the entry's readiness_rating when the target
    # outranks the current band (READY_NOW > READY_1_2 > READY_3_PLUS)
    if target_status == "COMPLETED":
        rank = {"READY_NOW": 0, "READY_1_2": 1, "READY_3_PLUS": 2}
        if rank[plan["target_readiness"]] < rank[entry["readiness_rating"]]:
            entry["readiness_rating"] = plan["target_readiness"]
    S.recompute_entry_score(entry)
    S.recompute_role_bench(S.critical_roles[entry["critical_role_id"]])
    S.commit()
    return ok(S.ser_plan(plan))


# ===========================================================================
# Vacancy endpoints
# ===========================================================================
@app.route("/talent/vacancies", methods=["GET"])
def list_vacancies():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.vacancies.values())
    if "critical_role_id" in args:
        rows = [v for v in rows if v["critical_role_id"] == args["critical_role_id"]]
    if "status" in args:
        rows = [v for v in rows if v["status"] == args["status"]]
    if "filled_by_employee_id" in args:
        rows = [v for v in rows if v["filled_by_employee_id"] == args["filled_by_employee_id"]]
    return list_ok(rows, limit, offset, S.ser_vacancy)


@app.route("/talent/vacancies/<vid>", methods=["GET"])
def get_vacancy_ep(vid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_vacancy(get_vacancy(vid)))


@app.route("/talent/vacancies/<vid>/fill-from-slate", methods=["POST"])
def fill_from_slate(vid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    v = get_vacancy(vid)
    if v["status"] != "OPEN":
        raise ApiError("ERR_VACANCY_NOT_OPEN", 409, "Vacancy is not OPEN")
    if S.now_dt() > v["fill_deadline"]:  # fill window is INCLUSIVE of the deadline
        raise ApiError("ERR_FILL_WINDOW_EXPIRED", 409, "Fill window has expired")
    entry = S.select_slate_fill(v)
    if entry is None:
        raise ApiError("ERR_NO_ELIGIBLE_SUCCESSOR", 409, "No eligible successor on the slate")

    entry["status"] = "PROMOTED"
    S.mark(entry)
    v["status"] = "FILLED"
    v["fill_source"] = "SUCCESSION_SLATE"
    v["filled_by_employee_id"] = entry["employee_id"]
    S.mark(v)
    r = S.critical_roles[v["critical_role_id"]]
    r["status"] = "ACTIVE"
    r["incumbent_employee_id"] = entry["employee_id"]
    S.mark(r)
    S.recompute_role_bench(r)  # the promoted entry left the ACTIVE slate
    S.commit()
    return ok(S.ser_vacancy(v))


@app.route("/talent/vacancies/<vid>/close", methods=["POST"])
def close_vacancy(vid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"closed_reason"})
    reason = data.get("closed_reason")
    if reason is not None:
        v_enum(reason, "closed_reason", S.CLOSED_REASONS)
    v = get_vacancy(vid)
    if v["status"] != "OPEN":
        raise ApiError("ERR_VACANCY_NOT_OPEN", 409, "Vacancy is not OPEN")
    v["status"] = "CLOSED_UNFILLED"
    v["closed_reason"] = reason
    S.mark(v)
    for p in S.postings.values():
        if p["vacancy_id"] == v["id"] and p["status"] == "OPEN":
            _close_posting(p)
    S.commit()
    return ok(S.ser_vacancy(v))


# ===========================================================================
# InternalPosting endpoints
# ===========================================================================
@app.route("/talent/vacancies/<vid>/postings", methods=["POST"])
def create_posting(vid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"title", "planned_open_date", "planned_close_date",
                 "min_tenure_months", "min_job_level"})
    title = v_str(req_field(data, "title"), "title")
    open_date = v_date(req_field(data, "planned_open_date"), "planned_open_date")
    close_date = v_date(req_field(data, "planned_close_date"), "planned_close_date")
    if S.parse_date(close_date) < S.parse_date(open_date):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "planned_close_date must not be earlier than planned_open_date")
    min_tenure = v_int(data.get("min_tenure_months", 12), "min_tenure_months", 0)
    min_level = v_int(data.get("min_job_level", 1), "min_job_level", 1, 10)
    v = get_vacancy(vid)
    p = S.stamp_new({
        "id": S.new_id(),
        "vacancy_id": v["id"],
        "title": title,
        "min_tenure_months": min_tenure,
        "min_job_level": min_level,
        "planned_open_date": open_date,
        "planned_close_date": close_date,
        "status": "DRAFT",
    })
    S.postings[p["id"]] = p
    S.commit()
    return ok(S.ser_posting(p), 201)


@app.route("/talent/postings", methods=["GET"])
def list_postings():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.postings.values())
    if "vacancy_id" in args:
        rows = [p for p in rows if p["vacancy_id"] == args["vacancy_id"]]
    if "status" in args:
        rows = [p for p in rows if p["status"] == args["status"]]
    return list_ok(rows, limit, offset, S.ser_posting)


@app.route("/talent/postings/<pid>", methods=["GET"])
def get_posting_ep(pid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_posting(get_posting(pid)))


@app.route("/talent/postings/<pid>/publish", methods=["POST"])
def publish_posting(pid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    p = get_posting(pid)
    if p["status"] != "DRAFT":
        raise ApiError("ERR_POSTING_INVALID_STATE", 409, "Posting is not DRAFT")
    v = S.vacancies[p["vacancy_id"]]
    if v["status"] != "OPEN":
        raise ApiError("ERR_VACANCY_NOT_OPEN", 409, "Vacancy is not OPEN")
    new_open, new_close = S.parse_date(p["planned_open_date"]), S.parse_date(p["planned_close_date"])
    for other in S.postings.values():
        if other["id"] == p["id"] or other["vacancy_id"] != v["id"] or other["status"] != "OPEN":
            continue
        # CLOSED date-interval semantics: shared boundary dates conflict.
        o_open, o_close = S.parse_date(other["planned_open_date"]), S.parse_date(other["planned_close_date"])
        if new_open <= o_close and o_open <= new_close:
            raise ApiError("ERR_POSTING_WINDOW_CONFLICT", 409,
                           "Posting window overlaps another OPEN posting of the vacancy")
    p["status"] = "OPEN"
    S.mark(p)
    S.commit()
    return ok(S.ser_posting(p))


@app.route("/talent/postings/<pid>/close", methods=["POST"])
def close_posting_ep(pid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    p = get_posting(pid)
    if p["status"] == "OPEN":
        _close_posting(p)
    elif p["status"] == "DRAFT":
        p["status"] = "CANCELLED"
        S.mark(p)
    else:
        raise ApiError("ERR_POSTING_INVALID_STATE", 409,
                       "Only OPEN or DRAFT postings can be closed")
    S.commit()
    return ok(S.ser_posting(p))


# ===========================================================================
# PostingApplication endpoints
# ===========================================================================
@app.route("/talent/postings/<pid>/applications", methods=["POST"])
def apply_posting(pid):
    uid, role = authenticate()
    authorize(role, ["Employee"])
    body(set())
    p = get_posting(pid)
    applicant = S.employees.get(uid)
    if applicant is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Caller does not resolve to an employee")
    if p["status"] != "OPEN":
        raise ApiError("ERR_POSTING_INVALID_STATE", 409, "Posting is not OPEN")
    if applicant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", 409, "Applicant is not ACTIVE")
    tenure = S.months_between(S.parse_date(applicant["hire_date"]), S.now_dt())
    if tenure < p["min_tenure_months"]:
        raise ApiError("ERR_TENURE_REQUIREMENT", 409, "Insufficient tenure")
    if applicant["job_level"] < p["min_job_level"]:
        raise ApiError("ERR_JOB_LEVEL_REQUIREMENT", 409, "Insufficient job level")
    if any(a["posting_id"] == p["id"] and a["employee_id"] == uid and a["status"] not in (
            "OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED", "WITHDRAWN")
            for a in S.applications.values()):
        raise ApiError("ERR_DUPLICATE_APPLICATION", 409,
                       "A non-terminal application already exists on this posting")
    now = S.now_dt()
    a = S.stamp_new({
        "id": S.new_id(),
        "posting_id": p["id"],
        "employee_id": uid,
        "submitted_at": now,
        "consent_deadline": now + timedelta(days=S.CONSENT_WINDOW_DAYS),
        # applicants with no current manager skip the consent step entirely
        "status": "PENDING_MANAGER_CONSENT" if applicant["current_manager_id"]
                  else "CONSENT_GRANTED",
        "hold_reason": None,
        "hold_at": None,
        "hold_expires_at": None,
    })
    S.applications[a["id"]] = a
    S.commit()
    return ok(S.ser_application(a), 201)


@app.route("/talent/applications", methods=["GET"])
def list_applications():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.applications.values())
    if "posting_id" in args:
        rows = [a for a in rows if a["posting_id"] == args["posting_id"]]
    if "employee_id" in args:
        rows = [a for a in rows if a["employee_id"] == args["employee_id"]]
    if "status" in args:
        rows = [a for a in rows if a["status"] == args["status"]]
    return list_ok(rows, limit, offset, S.ser_application)


@app.route("/talent/applications/<aid>", methods=["GET"])
def get_application_ep(aid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_application(get_application(aid)))


def _manager_gate(a, uid):
    """State -> reporting-manager ownership -> consent window (strict)."""
    if a["status"] != "PENDING_MANAGER_CONSENT":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       "Application is not PENDING_MANAGER_CONSENT")
    applicant = S.employees[a["employee_id"]]
    if applicant["current_manager_id"] != uid:
        raise ApiError("ERR_NOT_REPORTING_MANAGER", 403,
                       "Caller is not the applicant's current manager")
    if S.now_dt() >= a["consent_deadline"]:  # strict: at the deadline the window is closed
        raise ApiError("ERR_CONSENT_WINDOW_CLOSED", 409, "Consent window has closed")
    return applicant


@app.route("/talent/applications/<aid>/consent", methods=["POST"])
def consent_application(aid):
    uid, role = authenticate()
    authorize(role, ["Manager"])
    body(set())
    a = get_application(aid)
    _manager_gate(a, uid)
    a["status"] = "CONSENT_GRANTED"
    S.mark(a)
    S.commit()
    return ok(S.ser_application(a))


@app.route("/talent/applications/<aid>/hold", methods=["POST"])
def hold_application(aid):
    uid, role = authenticate()
    authorize(role, ["Manager"])
    data = body({"hold_reason"})
    reason = v_enum(req_field(data, "hold_reason"), "hold_reason", S.HOLD_REASONS)
    a = get_application(aid)
    applicant = _manager_gate(a, uid)
    if S.employee_active_hold_count(applicant["id"]) >= S.MAX_ACTIVE_HOLDS:
        raise ApiError("ERR_HOLD_LIMIT_REACHED", 409,
                       "Applicant already carries the maximum active holds")
    now = S.now_dt()
    a["status"] = "MANAGER_HOLD"
    a["hold_reason"] = reason
    a["hold_at"] = now
    a["hold_expires_at"] = now + timedelta(days=S.HOLD_DURATION_DAYS)
    S.mark(a)
    S.mark(applicant)  # active_hold_count recomputes (+1)
    S.commit()
    return ok(S.ser_application(a))


@app.route("/talent/applications/<aid>/release-hold", methods=["POST"])
def release_hold(aid):
    uid, role = authenticate()
    authorize(role, ["Manager"])
    body(set())
    a = get_application(aid)
    if a["status"] != "MANAGER_HOLD":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "Application is not on hold")
    applicant = S.employees[a["employee_id"]]
    if applicant["current_manager_id"] != uid:
        raise ApiError("ERR_NOT_REPORTING_MANAGER", 403,
                       "Caller is not the applicant's current manager")
    _leave_hold(a)
    a["status"] = "CONSENT_GRANTED"
    S.mark(a)
    S.commit()
    return ok(S.ser_application(a))


@app.route("/talent/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    uid, role = authenticate()
    authorize(role, ["Employee"])
    body(set())
    a = get_application(aid)
    if a["status"] in ("OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED", "WITHDRAWN"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "Application is terminal")
    if a["employee_id"] != uid:
        raise ApiError("ERR_APPLICANT_NOT_SELF", 403, "Application belongs to another employee")
    _leave_hold(a)
    a["status"] = "WITHDRAWN"
    S.mark(a)
    S.commit()
    return ok(S.ser_application(a))


@app.route("/talent/applications/<aid>/advance", methods=["POST"])
def advance_application(aid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"target_state"})
    target = v_enum(req_field(data, "target_state"), "target_state", S.APPLICATION_STATUSES)
    a = get_application(aid)
    if target == "INTERVIEWING":
        if a["status"] != "CONSENT_GRANTED":
            raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                           "INTERVIEWING requires CONSENT_GRANTED")
    elif target == "OFFER_EXTENDED":
        if a["status"] != "INTERVIEWING":
            raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                           "OFFER_EXTENDED requires INTERVIEWING")
        p = S.postings[a["posting_id"]]
        if p["status"] != "OPEN":
            raise ApiError("ERR_POSTING_INVALID_STATE", 409, "Posting is not OPEN")
        v = S.vacancies[p["vacancy_id"]]
        if v["status"] != "OPEN":
            raise ApiError("ERR_VACANCY_NOT_OPEN", 409, "Vacancy is not OPEN")
    elif target == "REJECTED":
        if a["status"] not in ("CONSENT_GRANTED", "INTERVIEWING"):
            raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                           "REJECTED requires CONSENT_GRANTED or INTERVIEWING")
    else:
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409,
                       f"target_state {target} is not a valid advance target")
    a["status"] = target
    S.mark(a)
    S.commit()
    return ok(S.ser_application(a))


@app.route("/talent/applications/<aid>/respond-offer", methods=["POST"])
def respond_offer(aid):
    uid, role = authenticate()
    authorize(role, ["Employee"])
    data = body({"decision"})
    decision = v_enum(req_field(data, "decision"), "decision", S.DECISIONS)
    a = get_application(aid)
    if a["status"] != "OFFER_EXTENDED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "No offer is outstanding")
    if a["employee_id"] != uid:
        raise ApiError("ERR_APPLICANT_NOT_SELF", 403, "Application belongs to another employee")
    if decision == "DECLINE":
        a["status"] = "OFFER_DECLINED"
        S.mark(a)
        S.commit()
        return ok(S.ser_application(a))

    # ACCEPT — the posting-channel fill cascade
    a["status"] = "OFFER_ACCEPTED"
    S.mark(a)
    p = S.postings[a["posting_id"]]
    v = S.vacancies[p["vacancy_id"]]
    v["status"] = "FILLED"
    v["fill_source"] = "INTERNAL_POSTING"
    v["filled_by_employee_id"] = uid
    S.mark(v)
    r = S.critical_roles[v["critical_role_id"]]
    r["status"] = "ACTIVE"
    r["incumbent_employee_id"] = uid
    S.mark(r)
    if p["status"] == "OPEN":
        p["status"] = "CLOSED"
        S.mark(p)
    for other in S.applications.values():
        if other["id"] != a["id"] and other["posting_id"] == p["id"] and other["status"] not in (
                "OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED", "WITHDRAWN"):
            _leave_hold(other)
            other["status"] = "REJECTED"
            S.mark(other)
    # the applicant's own slate entry on this role is promoted
    for e in S.successor_entries.values():
        if (e["critical_role_id"] == r["id"] and e["employee_id"] == uid
                and e["status"] in ("ACTIVE", "SUSPENDED")):
            e["status"] = "PROMOTED"
            S.mark(e)
    S.recompute_role_bench(r)
    S.commit()
    return ok(S.ser_application(a))


@app.route("/talent/consent-deadlines/process", methods=["POST"])
def process_consent_deadlines():
    uid, role = authenticate()
    authorize(role, ["HRAdmin"])
    body(set())
    now = S.now_dt()
    advanced_consent = 0
    advanced_hold = 0
    for a in S.applications.values():
        if a["status"] == "PENDING_MANAGER_CONSENT" and a["consent_deadline"] <= now:
            a["status"] = "CONSENT_GRANTED"  # manager silence is deemed consent
            S.mark(a)
            advanced_consent += 1
        elif a["status"] == "MANAGER_HOLD" and a["hold_expires_at"] <= now:
            _leave_hold(a)
            a["status"] = "CONSENT_GRANTED"
            S.mark(a)
            advanced_hold += 1
    S.commit()
    return ok({"advanced_consent_count": advanced_consent,
               "advanced_hold_count": advanced_hold})


# ===========================================================================
# CalibrationSession / CalibrationEntry endpoints
# ===========================================================================
@app.route("/talent/calibration-sessions", methods=["POST"])
def create_session():
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    data = body({"name", "department_scope", "scheduled_start", "scheduled_end"})
    name = v_str(req_field(data, "name"), "name")
    scope = v_str(req_field(data, "department_scope"), "department_scope")
    start_raw = v_datetime(req_field(data, "scheduled_start"), "scheduled_start")
    end_raw = v_datetime(req_field(data, "scheduled_end"), "scheduled_end")
    start, end = S.parse_dt(start_raw), S.parse_dt(end_raw)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scheduled_end must be later than scheduled_start")
    for s in S.calibration_sessions.values():
        if s["department_scope"] != scope or s["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        # HALF-OPEN windows [start, end): adjacency is allowed
        if start < s["_end"] and s["_start"] < end:
            raise ApiError("ERR_SESSION_WINDOW_CONFLICT", 409,
                           "Session window overlaps another session of the department")
    s = S.stamp_new({
        "id": S.new_id(),
        "name": name,
        "department_scope": scope,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "status": "SCHEDULED",
        "_start": start,
        "_end": end,
    })
    S.calibration_sessions[s["id"]] = s
    S.commit()
    return ok(S.ser_session(s), 201)


@app.route("/talent/calibration-sessions", methods=["GET"])
def list_sessions():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.calibration_sessions.values())
    if "department_scope" in args:
        rows = [s for s in rows if s["department_scope"] == args["department_scope"]]
    if "status" in args:
        rows = [s for s in rows if s["status"] == args["status"]]
    return list_ok(rows, limit, offset, S.ser_session)


@app.route("/talent/calibration-sessions/<sid>", methods=["GET"])
def get_session_ep(sid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_session(get_session(sid)))


@app.route("/talent/calibration-sessions/<sid>/start", methods=["POST"])
def start_session(sid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    body(set())
    s = get_session(sid)
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not SCHEDULED")
    s["status"] = "IN_PROGRESS"
    S.mark(s)
    S.commit()
    return ok(S.ser_session(s))


@app.route("/talent/calibration-sessions/<sid>/finalize", methods=["POST"])
def finalize_session(sid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    body(set())
    s = get_session(sid)
    if s["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not IN_PROGRESS")
    entries = [e for e in S.calibration_entries.values() if e["session_id"] == s["id"]]
    if len(entries) < 1:
        raise ApiError("ERR_SESSION_EMPTY", 409, "Session has no entries")
    ratified = [e for e in entries if e["status"] in ("RATIFIED", "APPLIED")]
    if len(ratified) != len(entries):
        raise ApiError("ERR_UNRATIFIED_ENTRIES_REMAIN", 409,
                       "Every entry must be ratified before finalize")

    # L1: apply every ratified entry
    now_iso = S.now_iso()
    updated_employees = set()
    for e in entries:
        e["status"] = "APPLIED"
        S.mark(e)
        # L2: write the calibrated rating + append to rating_history
        emp = S.employees[e["employee_id"]]
        emp["performance_rating"] = e["calibrated_rating"]
        emp["rating_history"].append({
            "rating": e["calibrated_rating"],
            "applied_at": now_iso,
            "session_id": s["id"],
        })
        S.mark(emp)
        updated_employees.add(emp["id"])

    # L3: ACTIVE/SUSPENDED successor entries of updated employees recompute
    touched_role_ids = set()
    for e in S.successor_entries.values():
        if e["employee_id"] in updated_employees and e["status"] in ("ACTIVE", "SUSPENDED"):
            S.recompute_entry_score(e)
            touched_role_ids.add(e["critical_role_id"])

    # L4: bench recompute on every role whose slate saw a score change
    for rid in touched_role_ids:
        S.recompute_role_bench(S.critical_roles[rid])

    s["status"] = "FINALIZED"
    S.mark(s)
    S.commit()
    return ok(S.ser_session(s))


@app.route("/talent/calibration-sessions/<sid>/entries", methods=["POST"])
def create_cal_entry(sid):
    uid, role = authenticate()
    authorize(role, ["Manager"])
    data = body({"employee_id", "proposed_rating"})
    employee_id = v_str(req_field(data, "employee_id"), "employee_id")
    proposed = v_enum(req_field(data, "proposed_rating"), "proposed_rating",
                      S.PERFORMANCE_RATINGS)
    s = get_session(sid)
    emp = S.employees.get(employee_id)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "employee_id does not resolve")
    if s["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not IN_PROGRESS")
    if emp["current_manager_id"] != uid:
        raise ApiError("ERR_NOT_REPORTING_MANAGER", 403,
                       "Caller is not the subject's current manager")
    if any(e["session_id"] == s["id"] and e["employee_id"] == employee_id
           for e in S.calibration_entries.values()):
        raise ApiError("ERR_DUPLICATE_SESSION_SUBJECT", 409,
                       "Employee already has an entry in this session")
    e = S.stamp_new({
        "id": S.new_id(),
        "session_id": s["id"],
        "employee_id": employee_id,
        "proposed_rating": proposed,
        "proposed_by_manager_id": uid,
        "calibrated_rating": None,
        "challenge_count": 0,
        "status": "PROPOSED",
    })
    S.calibration_entries[e["id"]] = e
    S.commit()
    return ok(S.ser_cal_entry(e), 201)


@app.route("/talent/calibration-entries", methods=["GET"])
def list_cal_entries():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.calibration_entries.values())
    if "session_id" in args:
        rows = [e for e in rows if e["session_id"] == args["session_id"]]
    if "employee_id" in args:
        rows = [e for e in rows if e["employee_id"] == args["employee_id"]]
    if "proposed_by_manager_id" in args:
        rows = [e for e in rows if e["proposed_by_manager_id"] == args["proposed_by_manager_id"]]
    if "status" in args:
        rows = [e for e in rows if e["status"] == args["status"]]
    return list_ok(rows, limit, offset, S.ser_cal_entry)


@app.route("/talent/calibration-entries/<eid>", methods=["GET"])
def get_cal_entry_ep(eid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_cal_entry(get_cal_entry(eid)))


@app.route("/talent/calibration-entries/<eid>/challenge", methods=["POST"])
def challenge_entry(eid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    body(set())
    e = get_cal_entry(eid)
    if e["status"] != "PROPOSED":
        raise ApiError("ERR_ENTRY_INVALID_STATE", 409, "Entry is not PROPOSED")
    s = S.calibration_sessions[e["session_id"]]
    if s["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not IN_PROGRESS")
    e["status"] = "CHALLENGED"
    e["challenge_count"] += 1
    S.mark(e)
    S.commit()
    return ok(S.ser_cal_entry(e))


@app.route("/talent/calibration-entries/<eid>/revise", methods=["POST"])
def revise_entry(eid):
    uid, role = authenticate()
    authorize(role, ["Manager"])
    data = body({"proposed_rating"})
    proposed = v_enum(req_field(data, "proposed_rating"), "proposed_rating",
                      S.PERFORMANCE_RATINGS)
    e = get_cal_entry(eid)
    if e["status"] != "CHALLENGED":
        raise ApiError("ERR_ENTRY_INVALID_STATE", 409, "Entry is not CHALLENGED")
    s = S.calibration_sessions[e["session_id"]]
    if s["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not IN_PROGRESS")
    if e["proposed_by_manager_id"] != uid:
        raise ApiError("ERR_NOT_ENTRY_PROPOSER", 403, "Only the proposer may revise")
    e["proposed_rating"] = proposed
    e["status"] = "PROPOSED"
    S.mark(e)
    S.commit()
    return ok(S.ser_cal_entry(e))


@app.route("/talent/calibration-entries/<eid>/ratify", methods=["POST"])
def ratify_entry(eid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    data = body({"final_rating"})
    final = v_enum(req_field(data, "final_rating"), "final_rating", S.PERFORMANCE_RATINGS)
    e = get_cal_entry(eid)
    if e["status"] not in ("PROPOSED", "CHALLENGED"):
        raise ApiError("ERR_ENTRY_INVALID_STATE", 409,
                       "Entry is not PROPOSED or CHALLENGED")
    s = S.calibration_sessions[e["session_id"]]
    if s["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session is not IN_PROGRESS")
    if e["proposed_by_manager_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Ratifier must differ from the proposing manager")
    e["calibrated_rating"] = final
    e["status"] = "RATIFIED"
    S.mark(e)
    S.commit()
    return ok(S.ser_cal_entry(e))


# ===========================================================================
# HiPoProgramCycle / HiPoNomination endpoints
# ===========================================================================
@app.route("/talent/hipo-cycles", methods=["POST"])
def create_cycle():
    uid, role = authenticate()
    authorize(role, ["HRAdmin"])
    data = body({"cycle_name", "capacity"})
    name = v_str(req_field(data, "cycle_name"), "cycle_name")
    capacity = v_int(req_field(data, "capacity"), "capacity", 1)
    if any(c["cycle_name"] == name for c in S.hipo_cycles.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "cycle_name must be unique")
    c = S.stamp_new({
        "id": S.new_id(),
        "cycle_name": name,
        "capacity": capacity,
        "status": "OPEN",
    })
    S.hipo_cycles[c["id"]] = c
    S.commit()
    return ok(S.ser_cycle(c), 201)


@app.route("/talent/hipo-cycles", methods=["GET"])
def list_cycles():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.hipo_cycles.values())
    if "status" in args:
        rows = [c for c in rows if c["status"] == args["status"]]
    return list_ok(rows, limit, offset, S.ser_cycle)


@app.route("/talent/hipo-cycles/<cid>", methods=["GET"])
def get_cycle_ep(cid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_cycle(get_cycle(cid)))


@app.route("/talent/hipo-cycles/<cid>/close", methods=["POST"])
def close_cycle(cid):
    uid, role = authenticate()
    authorize(role, ["HRAdmin"])
    body(set())
    c = get_cycle(cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_INVALID_STATE", 409, "Cycle is not OPEN")
    affected_employees = set()
    for n in S.hipo_nominations.values():
        if n["cycle_id"] != c["id"]:
            continue
        if n["status"] in ("ACTIVE", "UNDER_REVIEW"):
            n["status"] = "GRADUATED"
            S.mark(n)
            affected_employees.add(n["employee_id"])
        elif n["status"] in ("NOMINATED", "ENDORSED"):
            n["status"] = "REJECTED"
            S.mark(n)
    for emp_id in affected_employees:
        S.mark(S.employees[emp_id])  # is_high_potential recomputes
    c["status"] = "CLOSED"
    S.mark(c)  # enrolled_count recomputes to 0
    S.commit()
    return ok(S.ser_cycle(c))


@app.route("/talent/hipo-cycles/<cid>/nominations", methods=["POST"])
def create_nomination(cid):
    uid, role = authenticate()
    authorize(role, ["Manager"])
    data = body({"employee_id"})
    employee_id = v_str(req_field(data, "employee_id"), "employee_id")
    c = get_cycle(cid)
    emp = S.employees.get(employee_id)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "employee_id does not resolve")
    if c["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_INVALID_STATE", 409, "Cycle is not OPEN")
    if emp["current_manager_id"] != uid:
        raise ApiError("ERR_NOT_REPORTING_MANAGER", 403,
                       "Caller is not the nominee's current manager")
    if emp["employment_status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", 409, "Nominee is not ACTIVE")
    if any(n["cycle_id"] == c["id"] and n["employee_id"] == employee_id
           and n["status"] in ("NOMINATED", "ENDORSED", "ACTIVE", "UNDER_REVIEW")
           for n in S.hipo_nominations.values()):
        raise ApiError("ERR_DUPLICATE_NOMINATION", 409,
                       "Nominee already has a non-terminal nomination in this cycle")
    n = S.stamp_new({
        "id": S.new_id(),
        "cycle_id": c["id"],
        "employee_id": employee_id,
        "nominated_by_manager_id": uid,
        "endorsed_by_id": None,
        "review_count": 0,
        "status": "NOMINATED",
    })
    S.hipo_nominations[n["id"]] = n
    S.commit()
    return ok(S.ser_nomination(n), 201)


@app.route("/talent/hipo-nominations", methods=["GET"])
def list_nominations():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.hipo_nominations.values())
    if "cycle_id" in args:
        rows = [n for n in rows if n["cycle_id"] == args["cycle_id"]]
    if "employee_id" in args:
        rows = [n for n in rows if n["employee_id"] == args["employee_id"]]
    if "nominated_by_manager_id" in args:
        rows = [n for n in rows if n["nominated_by_manager_id"] == args["nominated_by_manager_id"]]
    if "status" in args:
        rows = [n for n in rows if n["status"] == args["status"]]
    return list_ok(rows, limit, offset, S.ser_nomination)


@app.route("/talent/hipo-nominations/<nid>", methods=["GET"])
def get_nomination_ep(nid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_nomination(get_nomination(nid)))


@app.route("/talent/hipo-nominations/<nid>/endorse", methods=["POST"])
def endorse_nomination(nid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    n = get_nomination(nid)
    if n["status"] != "NOMINATED":
        raise ApiError("ERR_NOMINATION_INVALID_STATE", 409, "Nomination is not NOMINATED")
    c = S.hipo_cycles[n["cycle_id"]]
    if c["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_INVALID_STATE", 409, "Cycle is not OPEN")
    if n["nominated_by_manager_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Endorser must differ from the nominator")
    n["endorsed_by_id"] = uid
    n["status"] = "ENDORSED"
    S.mark(n)
    S.commit()
    return ok(S.ser_nomination(n))


@app.route("/talent/hipo-nominations/<nid>/reject", methods=["POST"])
def reject_nomination(nid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    n = get_nomination(nid)
    if n["status"] != "NOMINATED":
        raise ApiError("ERR_NOMINATION_INVALID_STATE", 409, "Nomination is not NOMINATED")
    n["status"] = "REJECTED"
    S.mark(n)
    S.commit()
    return ok(S.ser_nomination(n))


@app.route("/talent/hipo-nominations/<nid>/enroll", methods=["POST"])
def enroll_nomination(nid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    body(set())
    n = get_nomination(nid)
    if n["status"] != "ENDORSED":
        raise ApiError("ERR_NOMINATION_INVALID_STATE", 409, "Nomination is not ENDORSED")
    c = S.hipo_cycles[n["cycle_id"]]
    if c["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_INVALID_STATE", 409, "Cycle is not OPEN")
    if S.cycle_enrolled_count(c["id"]) >= c["capacity"]:
        raise ApiError("ERR_PROGRAM_AT_CAPACITY", 409, "Cycle is at capacity")
    n["status"] = "ACTIVE"
    S.mark(n)
    S.mark(c)  # enrolled_count recomputes (+1)
    S.mark(S.employees[n["employee_id"]])  # is_high_potential recomputes
    S.commit()
    return ok(S.ser_nomination(n))


@app.route("/talent/hipo-nominations/<nid>/remove", methods=["POST"])
def remove_nomination(nid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    body(set())
    n = get_nomination(nid)
    if n["status"] != "ACTIVE":
        raise ApiError("ERR_NOMINATION_INVALID_STATE", 409, "Nomination is not ACTIVE")
    n["status"] = "REMOVED"
    S.mark(n)
    S.mark(S.hipo_cycles[n["cycle_id"]])  # enrolled_count recomputes (-1)
    S.mark(S.employees[n["employee_id"]])  # is_high_potential recomputes
    S.commit()
    return ok(S.ser_nomination(n))


@app.route("/talent/hipo-nominations/<nid>/start-review", methods=["POST"])
def start_review(nid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    body(set())
    n = get_nomination(nid)
    if n["status"] != "ACTIVE":
        raise ApiError("ERR_NOMINATION_INVALID_STATE", 409, "Nomination is not ACTIVE")
    n["status"] = "UNDER_REVIEW"
    S.mark(n)
    S.commit()
    return ok(S.ser_nomination(n))


@app.route("/talent/hipo-nominations/<nid>/complete-review", methods=["POST"])
def complete_review(nid):
    uid, role = authenticate()
    authorize(role, ["TalentManager"])
    data = body({"outcome"})
    outcome = v_enum(req_field(data, "outcome"), "outcome", S.REVIEW_OUTCOMES)
    n = get_nomination(nid)
    if n["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_NOMINATION_INVALID_STATE", 409, "Nomination is not UNDER_REVIEW")
    n["review_count"] += 1  # every completed review counts
    if outcome == "RETAIN":
        n["status"] = "ACTIVE"
    else:
        n["status"] = "REMOVED"
        S.mark(S.hipo_cycles[n["cycle_id"]])  # seat freed
        S.mark(S.employees[n["employee_id"]])  # is_high_potential recomputes
    S.mark(n)
    S.commit()
    return ok(S.ser_nomination(n))


# ===========================================================================
# RetentionAssessment endpoints
# ===========================================================================
@app.route("/talent/employees/<eid>/retention-assessments", methods=["POST"])
def create_assessment(eid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"assessment_method"})
    method = v_enum(req_field(data, "assessment_method"), "assessment_method",
                    S.ASSESSMENT_METHODS_RISK)
    emp = get_employee(eid)
    score, level = S.compute_risk(emp["id"], method)
    a = S.stamp_new({
        "id": S.new_id(),
        "employee_id": emp["id"],
        "assessment_method": method,
        "trigger_source": "MANUAL",
        "risk_score": score,
        "risk_level": level,
        "action_type": None,
        "action_deadline": None,
        "status": "OPEN",
    })
    S.retention_assessments[a["id"]] = a
    S.commit()
    return ok(S.ser_assessment(a), 201)


@app.route("/talent/retention-assessments", methods=["GET"])
def list_assessments():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.retention_assessments.values())
    if "employee_id" in args:
        rows = [a for a in rows if a["employee_id"] == args["employee_id"]]
    if "status" in args:
        rows = [a for a in rows if a["status"] == args["status"]]
    if "risk_level" in args:
        rows = [a for a in rows if a["risk_level"] == args["risk_level"]]
    if "trigger_source" in args:
        rows = [a for a in rows if a["trigger_source"] == args["trigger_source"]]
    return list_ok(rows, limit, offset, S.ser_assessment)


@app.route("/talent/retention-assessments/<aid>", methods=["GET"])
def get_assessment_ep(aid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_assessment(get_assessment(aid)))


@app.route("/talent/retention-assessments/<aid>/plan-action", methods=["POST"])
def plan_action(aid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"action_type", "action_deadline"})
    action_type = v_enum(req_field(data, "action_type"), "action_type", S.ACTION_TYPES)
    deadline = v_datetime(req_field(data, "action_deadline"), "action_deadline")
    a = get_assessment(aid)
    if a["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE", 409,
                       "Plan-action requires OPEN or ESCALATED")
    a["action_type"] = action_type
    a["action_deadline"] = deadline
    a["status"] = "ACTION_PLANNED"
    S.mark(a)
    S.commit()
    return ok(S.ser_assessment(a))


@app.route("/talent/retention-assessments/<aid>/escalate", methods=["POST"])
def escalate_assessment(aid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    body(set())
    a = get_assessment(aid)
    if a["status"] != "ACTION_PLANNED":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE", 409,
                       "Escalate requires ACTION_PLANNED")
    if a["risk_level"] not in ("HIGH", "CRITICAL"):
        raise ApiError("ERR_RISK_NOT_ESCALATABLE", 409,
                       "Only HIGH or CRITICAL risk can be escalated")
    a["status"] = "ESCALATED"
    S.mark(a)
    S.commit()
    return ok(S.ser_assessment(a))


@app.route("/talent/retention-assessments/<aid>/close", methods=["POST"])
def close_assessment(aid):
    uid, role = authenticate()
    authorize(role, ["HRBusinessPartner"])
    data = body({"outcome"})
    outcome = v_enum(req_field(data, "outcome"), "outcome", S.ASSESSMENT_CLOSE_OUTCOMES)
    a = get_assessment(aid)
    if outcome == "MITIGATED":
        if a["status"] != "ACTION_PLANNED":
            raise ApiError("ERR_ASSESSMENT_INVALID_STATE", 409,
                           "MITIGATED requires ACTION_PLANNED")
        score, level = S.compute_risk(a["employee_id"], a["assessment_method"])
        if level not in ("LOW", "MEDIUM"):
            raise ApiError("ERR_RISK_STILL_HIGH", 409, "Recomputed risk is still elevated")
        a["risk_score"] = score
        a["risk_level"] = level
        a["status"] = "MITIGATED"
    else:  # DISMISSED
        if a["status"] != "OPEN":
            raise ApiError("ERR_ASSESSMENT_INVALID_STATE", 409,
                           "DISMISSED requires OPEN")
        a["status"] = "DISMISSED"
    S.mark(a)
    S.commit()
    return ok(S.ser_assessment(a))


# ===========================================================================
# DiversitySnapshot endpoints
# ===========================================================================
@app.route("/talent/diversity-snapshots", methods=["POST"])
def create_snapshot():
    uid, role = authenticate()
    authorize(role, ["HRAdmin"])
    data = body({"scope_type", "scope_ref"})
    scope_type = v_enum(req_field(data, "scope_type"), "scope_type", S.SCOPE_TYPES)
    scope_ref = v_str(req_field(data, "scope_ref"), "scope_ref")

    total = 0
    underrep = 0
    index = None
    if scope_type == "DEPARTMENT":
        weighted_sum = Decimal("0")
        weight_total = 0
        for r in S.critical_roles.values():
            if r["department"] != scope_ref or r["status"] not in ("ACTIVE", "VACANT"):
                continue
            entries = S.active_entries(r["id"])
            if not entries:
                continue  # only roles with >= 1 ACTIVE entry participate
            role_total = len(entries)
            role_under = sum(1 for e in entries
                             if S.employees[e["employee_id"]]["demographic_group"]
                             in S.UNDERREPRESENTED_GROUPS)
            w = S.TIER_WEIGHT[r["criticality_tier"]]
            weighted_sum += w * (Decimal(role_under) / Decimal(role_total))
            weight_total += w
            total += role_total
            underrep += role_under
        if weight_total > 0:
            index = S.rhu(weighted_sum / Decimal(weight_total) * 100, 2)
    else:  # HIPO_CYCLE
        population = [n for n in S.hipo_nominations.values()
                      if n["cycle_id"] == scope_ref
                      and n["status"] in ("ACTIVE", "UNDER_REVIEW", "GRADUATED")]
        total = len(population)
        underrep = sum(1 for n in population
                       if S.employees[n["employee_id"]]["demographic_group"]
                       in S.UNDERREPRESENTED_GROUPS)
        if total > 0:
            index = S.rhu(Decimal(underrep) / Decimal(total) * 100, 2)

    s = S.stamp_append_only({
        "id": S.new_id(),
        "scope_type": scope_type,
        "scope_ref": scope_ref,
        "total_subjects": total,
        "underrepresented_count": underrep,
        "diversity_index": index,
    })
    S.diversity_snapshots[s["id"]] = s
    return ok(S.ser_snapshot(s), 201)


@app.route("/talent/diversity-snapshots", methods=["GET"])
def list_snapshots():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    rows = list(S.diversity_snapshots.values())
    if "scope_type" in args:
        rows = [s for s in rows if s["scope_type"] == args["scope_type"]]
    return list_ok(rows, limit, offset, S.ser_snapshot)


@app.route("/talent/diversity-snapshots/<sid>", methods=["GET"])
def get_snapshot_ep(sid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(S.ser_snapshot(get_snapshot(sid)))


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.route("/talent/_clock/set_current_utc", methods=["POST"])
def set_clock_ep():
    uid, role = authenticate()
    authorize(role, ["HRAdmin"])
    data = body({"to_iso8601"})
    raw = v_datetime(req_field(data, "to_iso8601"), "to_iso8601")
    S.set_clock(S.parse_dt(raw))
    S.commit()
    return ok({"current_utc": S.iso(S.now_dt())})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
