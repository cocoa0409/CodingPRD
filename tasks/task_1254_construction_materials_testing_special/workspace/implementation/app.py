#!/usr/bin/env python3
"""Construction Materials Testing & Special Inspection agency API.

Flask implementation. In-memory store; logical clock starting at
2026-05-01T00:00:00Z. All timestamps written from the logical clock.
"""
import os
import re
import uuid
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

_CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK["now"]


def iso_now():
    return _fmt_dt(clock_now())


def _fmt_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_datetime(s):
    """Parse ISO-8601 datetime. Returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def parse_time_hhmm(s):
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"(\d{2}):(\d{2})", s.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi  # minutes since midnight


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not allowed for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_validation(msg="Invalid request"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_invalid_state(msg="Resource not in a state permitting the operation"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


# --------------------------------------------------------------------------
# In-memory store
# --------------------------------------------------------------------------

DB = {
    "projects": {},
    "ssi_revisions": {},
    "scope_items": {},
    "technicians": {},
    "assignments": {},
    "field_tests": {},
    "lab_samples": {},
    "labs": {},
    "ncrs": {},
    "daily_reports": {},
    "discrepancies": {},
}

_SEQ = {"n": 0}


def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]

ROLES = {
    "AgencyAdmin", "ProjectManager", "EngineerOfRecord", "Technician",
    "LabAnalyst", "Contractor", "BuildingOfficial",
}

TEST_METHODS = {"CONCRETE_STRENGTH", "SOIL_COMPACTION", "WELD_VISUAL", "BOLT_TENSION"}
FIELD_TEST_METHODS = {"SOIL_COMPACTION", "WELD_VISUAL", "BOLT_TENSION"}


def new_id():
    return str(uuid.uuid4())


def new_common():
    return {"id": new_id(), "created_at": iso_now(), "updated_at": iso_now(), "version": 1, "_seq": _next_seq()}


def touch(rec):
    rec["updated_at"] = iso_now()
    rec["version"] += 1


# --------------------------------------------------------------------------
# Flask app + envelope helpers
# --------------------------------------------------------------------------

app = Flask(__name__)


def _req_id():
    return "req_" + uuid.uuid4().hex[:24]


def ok_object(data, status=200):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": iso_now()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": iso_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _api_error(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": iso_now()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _not_found(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": iso_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _method_not_allowed(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": iso_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def _unhandled(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": iso_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return uid, role


def require_role(*allowed):
    uid, role = get_auth()
    if role not in allowed:
        raise err_forbidden("Role %s not allowed for this endpoint" % role)
    return uid, role


def get_json():
    if not request.is_json:
        raise err_validation("Request body must be JSON")
    try:
        data = request.get_json()
    except Exception:
        raise err_validation("Malformed JSON body")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_validation("Missing required field: %s" % name)
    return data[name]


def opt_field(data, name, default=None):
    v = data.get(name, default)
    return v if v is not None else default


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str):
        raise err_validation("Field %s must be a string" % name)
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Field %s must be an integer" % name)
    return v


def req_bool(data, name, default=False):
    v = data.get(name, default)
    if not isinstance(v, bool):
        raise err_validation("Field %s must be a boolean" % name)
    return v


def get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
    except Exception:
        raise err_validation("Invalid limit")
    try:
        offset = int(request.args.get("offset", "0"))
    except Exception:
        raise err_validation("Invalid offset")
    if limit < 1 or limit > 100:
        raise err_validation("limit must be between 1 and 100")
    if offset < 0:
        raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def sort_created(records):
    return sorted(records, key=lambda r: r.get("_seq", 0))


def _strip_internal(rec):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    return out


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------

def proj_view(p):
    return _strip_internal(p)


def ssi_view(s):
    return _strip_internal(s)


def scope_view(s):
    return _strip_internal(s)


def tech_view(t):
    return _strip_internal(t)


def asg_view(a):
    return _strip_internal(a)


def ft_view(f):
    return _strip_internal(f)


def ls_view(s):
    return _strip_internal(s)


def lab_view(l):
    return _strip_internal(l)


def ncr_view(n):
    return _strip_internal(n)


def dir_view(d):
    return _strip_internal(d)


def disc_view(d):
    return _strip_internal(d)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_project_or_404(pid):
    p = DB["projects"].get(pid)
    if not p:
        raise err_not_found("Project not found")
    return p


def get_ssi_or_404(sid):
    s = DB["ssi_revisions"].get(sid)
    if not s:
        raise err_not_found("SSI revision not found")
    return s


def get_scope_or_404(sid):
    s = DB["scope_items"].get(sid)
    if not s:
        raise err_not_found("Scope item not found")
    return s


def get_tech_or_404(tid):
    t = DB["technicians"].get(tid)
    if not t:
        raise err_not_found("Technician not found")
    return t


def get_asg_or_404(aid):
    a = DB["assignments"].get(aid)
    if not a:
        raise err_not_found("Assignment not found")
    return a


def get_ft_or_404(fid):
    f = DB["field_tests"].get(fid)
    if not f:
        raise err_not_found("Field test not found")
    return f


def get_ls_or_404(lid):
    s = DB["lab_samples"].get(lid)
    if not s:
        raise err_not_found("Lab sample not found")
    return s


def get_lab_or_404(lid):
    l = DB["labs"].get(lid)
    if not l:
        raise err_not_found("Lab not found")
    return l


def get_ncr_or_404(nid):
    n = DB["ncrs"].get(nid)
    if not n:
        raise err_not_found("NCR not found")
    return n


def get_dir_or_404(did):
    d = DB["daily_reports"].get(did)
    if not d:
        raise err_not_found("Daily report not found")
    return d


def get_disc_or_404(did):
    d = DB["discrepancies"].get(did)
    if not d:
        raise err_not_found("Discrepancy not found")
    return d


# --------------------------------------------------------------------------
# Posture derivation
# --------------------------------------------------------------------------

def recompute_posture(project):
    if project["letter_status"] == "ISSUED":
        project["compliance_posture"] = "LETTER_ISSUED"
        return
    # count open NCRs
    open_count = 0
    for n in DB["ncrs"].values():
        if n["project_id"] == project["id"] and n["status"] in ("OPEN", "CORRECTION_SUBMITTED", "ESCALATED"):
            open_count += 1
    project["open_ncr_count"] = open_count
    if open_count > 0:
        project["compliance_posture"] = "NONCONFORMANCE_OUTSTANDING"
        return
    ready = True
    if project["current_approved_ssi_id"] is None:
        ready = False
    else:
        for s in DB["scope_items"].values():
            if s["ssi_revision_id"] == project["current_approved_ssi_id"]:
                if s["status"] != "SATISFIED":
                    ready = False
                    break
    if ready:
        for d in DB["discrepancies"].values():
            if d["project_id"] == project["id"] and d["status"] in ("RAISED", "RESPONSE_SUBMITTED"):
                ready = False
                break
    if ready:
        for a in DB["assignments"].values():
            if a["project_id"] == project["id"] and a["status"] == "COMPLETED":
                if not a.get("covered_by_dir_id"):
                    ready = False
                    break
    project["compliance_posture"] = "READY_FOR_LETTER" if ready else "IN_PROGRESS"


# --------------------------------------------------------------------------
# Scope completion recalculation
# --------------------------------------------------------------------------

def recompute_scope_completion(scope_item):
    count = 0
    for f in DB["field_tests"].values():
        a = DB["assignments"].get(f["assignment_id"])
        if not a:
            continue
        if a["scope_item_id"] == scope_item["id"] and f["status"] == "RECORDED" and f["result"] == "CONFORMING":
            count += 1
    for s in DB["lab_samples"].values():
        a = DB["assignments"].get(s["assignment_id"])
        if not a:
            continue
        if a["scope_item_id"] == scope_item["id"] and s["status"] == "REPORTED" and s.get("break_result") == "CONFORMING":
            count += 1
    scope_item["completed_count"] = count
    scope_item["status"] = "SATISFIED" if count >= scope_item["required_count"] else "OPEN"


def recompute_scope_and_posture(scope_item, project):
    recompute_scope_completion(scope_item)
    touch(scope_item)
    recompute_posture(project)
    touch(project)


# --------------------------------------------------------------------------
# NCR helpers
# --------------------------------------------------------------------------

REMEDIATION_DAYS = {"MINOR": 30, "MAJOR": 14, "STRUCTURAL": 7}
SEVERITY_BASE = {"MINOR": 20, "MAJOR": 40, "STRUCTURAL": 60}
ESCALATION_THRESHOLD = 70


def next_ncr_number(project_id):
    nums = []
    for n in DB["ncrs"].values():
        if n["project_id"] == project_id:
            try:
                nums.append(int(n["ncr_number"].split("-")[1]))
            except Exception:
                pass
    nxt = (max(nums) + 1) if nums else 1
    return "NCR-%04d" % nxt


def auto_create_ncr(project, source_type, source_id, scope_item_id, severity, description):
    common = new_common()
    detected_dt = clock_now()
    deadline = detected_dt.date() + timedelta(days=REMEDIATION_DAYS[severity])
    ncr = {
        **common,
        "project_id": project["id"],
        "ncr_number": next_ncr_number(project["id"]),
        "source_type": source_type,
        "source_id": source_id,
        "scope_item_id": scope_item_id,
        "description": description,
        "severity": severity,
        "detected_at": _fmt_dt(detected_dt),
        "deadline_date": deadline.isoformat(),
        "rejection_count": 0,
        "correction_note": None,
        "verified_by_technician_id": None,
        "evidence_field_test_id": None,
        "escalation_score": 0,
        "status": "OPEN",
    }
    DB["ncrs"][ncr["id"]] = ncr
    return ncr


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

@app.route("/api/projects", methods=["POST"])
def create_project():
    uid, role = require_role("AgencyAdmin")
    data = get_json()
    name = req_str(data, "name")
    permit = req_str(data, "permit_number")
    jurisdiction = req_str(data, "jurisdiction")
    contractor = req_str(data, "contractor_name")
    bo = req_str(data, "building_official_name")
    for p in DB["projects"].values():
        if p["permit_number"] == permit:
            raise err_validation("Duplicate permit_number")
    common = new_common()
    p = {
        **common,
        "name": name,
        "permit_number": permit,
        "jurisdiction": jurisdiction,
        "contractor_name": contractor,
        "building_official_name": bo,
        "status": "ACTIVE",
        "compliance_posture": "IN_PROGRESS",
        "open_ncr_count": 0,
        "current_approved_ssi_id": None,
        "letter_status": "NONE",
        "letter_issued_at": None,
        "letter_issued_by": None,
        "letter_void_reason": None,
    }
    DB["projects"][p["id"]] = p
    return ok_object(proj_view(p), 201)


@app.route("/api/projects/<pid>", methods=["GET"])
def get_project(pid):
    get_auth()
    p = get_project_or_404(pid)
    return ok_object(proj_view(p))


# --------------------------------------------------------------------------
# SSI revisions + scope items
# --------------------------------------------------------------------------

def _validate_scope_item_input(item):
    if not isinstance(item, dict):
        raise err_validation("scope_items entries must be objects")
    method = req_str(item, "test_method")
    if method not in TEST_METHODS:
        raise err_validation("Invalid test_method")
    description = req_str(item, "description")
    rcl = req_int(item, "required_cert_level")
    if rcl not in (1, 2, 3):
        raise err_validation("required_cert_level must be 1, 2, or 3")
    rc = req_int(item, "required_count")
    if rc < 1:
        raise err_validation("required_count must be >= 1")
    is_structural = req_bool(item, "is_structural", False)
    proctor = item.get("proctor_method", "STANDARD")
    if proctor not in ("STANDARD", "MODIFIED"):
        raise err_validation("Invalid proctor_method")
    std = item.get("standard_max_density_pcf")
    mod = item.get("modified_max_density_pcf")
    if method == "SOIL_COMPACTION":
        if std is None or mod is None:
            raise err_validation("standard_max_density_pcf and modified_max_density_pcf are required for SOIL_COMPACTION")
        if not isinstance(std, (int, float)) or isinstance(std, bool):
            raise err_validation("standard_max_density_pcf must be a number")
        if not isinstance(mod, (int, float)) or isinstance(mod, bool):
            raise err_validation("modified_max_density_pcf must be a number")
    else:
        std = None
        mod = None
    return {
        "test_method": method,
        "description": description,
        "required_cert_level": rcl,
        "required_count": rc,
        "is_structural": is_structural,
        "proctor_method": proctor,
        "standard_max_density_pcf": std,
        "modified_max_density_pcf": mod,
    }


@app.route("/api/projects/<pid>/ssi-revisions", methods=["POST"])
def create_ssi_revision(pid):
    uid, role = require_role("ProjectManager")
    project = get_project_or_404(pid)
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    data = get_json()
    fc = req_int(data, "specified_fc_psi")
    amc = data.get("acceptance_method_concrete", "MOVING_AVERAGE")
    if amc not in ("MOVING_AVERAGE", "INDIVIDUAL_SET"):
        raise err_validation("Invalid acceptance_method_concrete")
    items_in = req_field(data, "scope_items")
    if not isinstance(items_in, list) or len(items_in) < 1:
        raise err_validation("scope_items must be an array with at least one entry")
    validated = [_validate_scope_item_input(x) for x in items_in]
    # revision number per project in created order
    existing = [s for s in DB["ssi_revisions"].values() if s["project_id"] == pid]
    rev_no = len(existing) + 1
    common = new_common()
    rev = {
        **common,
        "project_id": pid,
        "revision_number": rev_no,
        "specified_fc_psi": fc,
        "acceptance_method_concrete": amc,
        "status": "DRAFT",
        "submitted_at": None,
        "approved_at": None,
    }
    DB["ssi_revisions"][rev["id"]] = rev
    for vi in validated:
        sc = new_common()
        item = {
            **sc,
            "ssi_revision_id": rev["id"],
            **vi,
            "completed_count": 0,
            "status": "OPEN",
        }
        DB["scope_items"][item["id"]] = item
    return ok_object(ssi_view(rev), 201)


@app.route("/api/projects/<pid>/ssi-revisions", methods=["GET"])
def list_ssi_revisions(pid):
    get_auth()
    get_project_or_404(pid)
    status_f = request.args.get("status")
    items = [s for s in DB["ssi_revisions"].values() if s["project_id"] == pid]
    if status_f:
        items = [s for s in items if s["status"] == status_f]
    items = sort_created(items)
    return paginate([ssi_view(s) for s in items])


@app.route("/api/ssi-revisions/<sid>", methods=["GET"])
def get_ssi(sid):
    get_auth()
    s = get_ssi_or_404(sid)
    return ok_object(ssi_view(s))


@app.route("/api/ssi-revisions/<sid>/scope-items", methods=["GET"])
def list_scope_items(sid):
    get_auth()
    get_ssi_or_404(sid)
    items = [x for x in DB["scope_items"].values() if x["ssi_revision_id"] == sid]
    items = sort_created(items)
    return paginate([scope_view(x) for x in items])


@app.route("/api/ssi-revisions/<sid>/submit", methods=["POST"])
def submit_ssi(sid):
    uid, role = require_role("ProjectManager")
    rev = get_ssi_or_404(sid)
    project = get_project_or_404(rev["project_id"])
    if rev["status"] != "DRAFT":
        raise err_invalid_state("Revision not in DRAFT")
    items = [x for x in DB["scope_items"].values() if x["ssi_revision_id"] == sid]
    if len(items) < 1:
        raise err_invalid_state("Revision has no scope items")
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    rev["status"] = "SUBMITTED"
    rev["submitted_at"] = iso_now()
    touch(rev)
    return ok_object(ssi_view(rev))


@app.route("/api/ssi-revisions/<sid>/approve", methods=["POST"])
def approve_ssi(sid):
    uid, role = require_role("EngineerOfRecord")
    rev = get_ssi_or_404(sid)
    project = get_project_or_404(rev["project_id"])
    if rev["status"] != "SUBMITTED":
        raise err_invalid_state("Revision not in SUBMITTED")
    data = get_json()
    decision = req_str(data, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise err_validation("decision must be APPROVE or REJECT")
    epv = req_field(data, "expected_project_version")
    if isinstance(epv, bool) or not isinstance(epv, int):
        raise err_validation("expected_project_version must be an integer")
    if epv != project["version"]:
        raise ApiError("ERR_STALE_VERSION", "Stale project version", 412)
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    if decision == "APPROVE":
        # supersede prior approved
        prior_id = project.get("current_approved_ssi_id")
        if prior_id and prior_id in DB["ssi_revisions"]:
            prior = DB["ssi_revisions"][prior_id]
            if prior["status"] == "APPROVED":
                prior["status"] = "SUPERSEDED"
                touch(prior)
        rev["status"] = "APPROVED"
        rev["approved_at"] = iso_now()
        touch(rev)
        project["current_approved_ssi_id"] = rev["id"]
        recompute_posture(project)
        touch(project)
    else:
        rev["status"] = "REJECTED"
        touch(rev)
        touch(project)
    return ok_object(ssi_view(rev))


# --------------------------------------------------------------------------
# Technicians
# --------------------------------------------------------------------------

def _validate_cert(cert):
    if not isinstance(cert, dict):
        raise err_validation("certification must be an object")
    method = req_str(cert, "method")
    if method not in TEST_METHODS:
        raise err_validation("Invalid certification method")
    level = req_int(cert, "level")
    if level not in (1, 2, 3):
        raise err_validation("level must be 1, 2, or 3")
    exp = req_str(cert, "expires_at")
    if parse_date(exp) is None:
        raise err_validation("expires_at must be an ISO date")
    return {"method": method, "level": level, "expires_at": exp}


@app.route("/api/technicians", methods=["POST"])
def create_technician():
    uid, role = require_role("AgencyAdmin")
    data = get_json()
    full_name = req_str(data, "full_name")
    emp_code = req_str(data, "employee_code")
    certs_in = data.get("certifications", [])
    if certs_in is None:
        certs_in = []
    if not isinstance(certs_in, list):
        raise err_validation("certifications must be an array")
    certs = [_validate_cert(c) for c in certs_in]
    for t in DB["technicians"].values():
        if t["employee_code"] == emp_code:
            raise err_validation("Duplicate employee_code")
    common = new_common()
    t = {
        **common,
        "full_name": full_name,
        "employee_code": emp_code,
        "certifications": certs,
        "status": "ACTIVE",
    }
    DB["technicians"][t["id"]] = t
    return ok_object(tech_view(t), 201)


@app.route("/api/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    get_auth()
    t = get_tech_or_404(tid)
    return ok_object(tech_view(t))


@app.route("/api/technicians/<tid>/certifications", methods=["POST"])
def add_cert(tid):
    uid, role = require_role("AgencyAdmin")
    t = get_tech_or_404(tid)
    data = get_json()
    cert = _validate_cert(data)
    t["certifications"].append(cert)
    touch(t)
    return ok_object(tech_view(t), 201)


@app.route("/api/technicians/<tid>/deactivate", methods=["POST"])
def deactivate_technician(tid):
    uid, role = require_role("AgencyAdmin")
    t = get_tech_or_404(tid)
    if t["status"] != "ACTIVE":
        raise err_invalid_state("Technician not ACTIVE")
    t["status"] = "INACTIVE"
    touch(t)
    return ok_object(tech_view(t))


# --------------------------------------------------------------------------
# Assignments
# --------------------------------------------------------------------------

def _windows_overlap(s1, e1, s2, e2):
    # half-open intervals [s1, e1) and [s2, e2)
    return s1 < e2 and s2 < e1


@app.route("/api/assignments", methods=["POST"])
def create_assignment():
    uid, role = require_role("ProjectManager")
    data = get_json()
    project_id = req_str(data, "project_id")
    scope_item_id = req_str(data, "scope_item_id")
    technician_id = req_str(data, "technician_id")
    work_date_s = req_str(data, "work_date")
    start_s = req_str(data, "start_time")
    end_s = req_str(data, "end_time")

    work_date = parse_date(work_date_s)
    if work_date is None:
        raise err_validation("work_date must be ISO date YYYY-MM-DD")
    start_m = parse_time_hhmm(start_s)
    end_m = parse_time_hhmm(end_s)
    if start_m is None or end_m is None:
        raise err_validation("start_time/end_time must be HH:MM")
    if end_m <= start_m:
        raise err_validation("end_time must be after start_time")

    project = get_project_or_404(project_id)
    # technician must exist (tier 3: existence)
    tech = DB["technicians"].get(technician_id)
    if not tech:
        raise err_not_found("Technician not found")
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    # double-booking check (tier 6: temporal occupancy — precedes cross-reference tier 8)
    for a in DB["assignments"].values():
        if a["technician_id"] != technician_id:
            continue
        if a["work_date"] != work_date_s:
            continue
        if a["status"] not in ("REQUESTED", "DISPATCHED"):
            continue
        s2 = parse_time_hhmm(a["start_time"])
        e2 = parse_time_hhmm(a["end_time"])
        if _windows_overlap(start_m, end_m, s2, e2):
            raise ApiError("ERR_TECHNICIAN_DOUBLE_BOOKED", "Technician window overlaps an existing assignment", 409)
    # ERR_SSI_NOT_APPROVED / ERR_REFERENCE_MISMATCH (tier 8: cross-reference scope)
    if project.get("current_approved_ssi_id") is None:
        raise ApiError("ERR_SSI_NOT_APPROVED", "Project has no approved SSI revision", 422)
    scope = DB["scope_items"].get(scope_item_id)
    if not scope:
        raise ApiError("ERR_REFERENCE_MISMATCH", "Scope item does not belong to the current approved revision", 422)
    if scope["ssi_revision_id"] != project["current_approved_ssi_id"]:
        raise ApiError("ERR_REFERENCE_MISMATCH", "Scope item does not belong to the current approved revision", 422)

    common = new_common()
    a = {
        **common,
        "project_id": project_id,
        "scope_item_id": scope_item_id,
        "technician_id": technician_id,
        "ssi_revision_id": project["current_approved_ssi_id"],
        "work_date": work_date_s,
        "start_time": start_s,
        "end_time": end_s,
        "status": "REQUESTED",
        "completion_note": None,
        "completed_at": None,
        "covered_by_dir_id": None,
    }
    DB["assignments"][a["id"]] = a
    return ok_object(asg_view(a), 201)


@app.route("/api/assignments", methods=["GET"])
def list_assignments():
    get_auth()
    items = list(DB["assignments"].values())
    pid = request.args.get("project_id")
    sid = request.args.get("scope_item_id")
    tid = request.args.get("technician_id")
    st = request.args.get("status")
    wd = request.args.get("work_date")
    if pid:
        items = [a for a in items if a["project_id"] == pid]
    if sid:
        items = [a for a in items if a["scope_item_id"] == sid]
    if tid:
        items = [a for a in items if a["technician_id"] == tid]
    if st:
        items = [a for a in items if a["status"] == st]
    if wd:
        items = [a for a in items if a["work_date"] == wd]
    items = sort_created(items)
    return paginate([asg_view(a) for a in items])


@app.route("/api/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    get_auth()
    a = get_asg_or_404(aid)
    return ok_object(asg_view(a))


@app.route("/api/assignments/<aid>/dispatch", methods=["POST"])
def dispatch_assignment(aid):
    uid, role = require_role("ProjectManager")
    a = get_asg_or_404(aid)
    if a["status"] != "REQUESTED":
        raise err_invalid_state("Assignment not in REQUESTED")
    project = get_project_or_404(a["project_id"])
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    tech = get_tech_or_404(a["technician_id"])
    scope = get_scope_or_404(a["scope_item_id"])
    if tech["status"] != "ACTIVE":
        raise ApiError("ERR_TECHNICIAN_INACTIVE", "Technician is INACTIVE", 409)
    cert = None
    for c in tech["certifications"]:
        if c["method"] == scope["test_method"]:
            if cert is None or c["level"] > cert["level"]:
                cert = c
    if cert is None:
        raise ApiError("ERR_CERTIFICATION_MISSING", "No certification for method", 409)
    if cert["level"] < scope["required_cert_level"]:
        raise ApiError("ERR_CERTIFICATION_INSUFFICIENT", "Certification level insufficient", 409)
    cert_exp = parse_date(cert["expires_at"])
    work_d = parse_date(a["work_date"])
    if cert_exp is None or work_d is None or not (cert_exp > work_d):
        raise ApiError("ERR_CERTIFICATION_EXPIRED", "Certification expired", 409)
    a["status"] = "DISPATCHED"
    touch(a)
    return ok_object(asg_view(a))


@app.route("/api/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    uid, role = require_role("ProjectManager")
    a = get_asg_or_404(aid)
    if a["status"] not in ("REQUESTED", "DISPATCHED"):
        raise err_invalid_state("Assignment cannot be cancelled from %s" % a["status"])
    data = get_json() if request.data else {}
    requeue = data.get("requeue", False)
    if requeue is True:
        if a["status"] == "DISPATCHED":
            a["status"] = "REQUESTED"
        else:
            # requeue from REQUESTED -> cancel (no DISPATCHED to return to)
            a["status"] = "CANCELLED"
    else:
        a["status"] = "CANCELLED"
    touch(a)
    return ok_object(asg_view(a))


@app.route("/api/assignments/<aid>/complete", methods=["POST"])
def complete_assignment(aid):
    uid, role = require_role("Technician")
    a = get_asg_or_404(aid)
    if a["technician_id"] != uid:
        raise err_forbidden("Only the assigned technician may complete this assignment")
    if a["status"] != "DISPATCHED":
        raise err_invalid_state("Assignment not in DISPATCHED")
    project = get_project_or_404(a["project_id"])
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    has_ft = any(f["assignment_id"] == aid for f in DB["field_tests"].values())
    has_ls = any(s["assignment_id"] == aid for s in DB["lab_samples"].values())
    if not (has_ft or has_ls):
        raise ApiError("ERR_NO_RESULT_RECORDED", "No result recorded", 409)
    data = get_json() if request.data else {}
    note = data.get("completion_note")
    a["status"] = "COMPLETED"
    a["completed_at"] = iso_now()
    if note is not None:
        a["completion_note"] = note
    touch(a)
    recompute_posture(project)
    touch(project)
    return ok_object(asg_view(a))


# --------------------------------------------------------------------------
# Field tests
# --------------------------------------------------------------------------

def _round_half_up_dec(x, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(x).quantize(q, rounding=ROUND_HALF_UP)


def _round_to_grid_10(value):
    """Round to nearest multiple of 10, half-up."""
    d = Decimal(value) / Decimal(10)
    rounded = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded * 10)


def _evaluate_field_test(scope, measured):
    method = scope["test_method"]
    if method == "SOIL_COMPACTION":
        fdd = measured.get("field_dry_density_pcf")
        if fdd is None or isinstance(fdd, bool) or not isinstance(fdd, (int, float)):
            raise err_validation("measured_values.field_dry_density_pcf must be a number")
        if scope["proctor_method"] == "STANDARD":
            max_density = scope["standard_max_density_pcf"]
            threshold = Decimal("95.0")
        else:
            max_density = scope["modified_max_density_pcf"]
            threshold = Decimal("92.0")
        if not max_density:
            raise err_validation("Scope item lacks reference density")
        pct = (Decimal(str(fdd)) * Decimal(100) / Decimal(str(max_density)))
        pct = pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        result = "CONFORMING" if pct >= threshold else "NONCONFORMING"
        return result, {
            "relative_compaction_pct": float(pct),
            "threshold_pct": float(threshold),
            "proctor_method": scope["proctor_method"],
        }
    elif method == "WELD_VISUAL":
        dc = measured.get("defect_count")
        if dc is None or isinstance(dc, bool) or not isinstance(dc, int):
            raise err_validation("measured_values.defect_count must be an integer")
        result = "CONFORMING" if dc == 0 else "NONCONFORMING"
        return result, {"defect_count": dc}
    elif method == "BOLT_TENSION":
        bt = measured.get("bolts_tested")
        bp = measured.get("bolts_passed")
        if bt is None or isinstance(bt, bool) or not isinstance(bt, int):
            raise err_validation("measured_values.bolts_tested must be an integer")
        if bp is None or isinstance(bp, bool) or not isinstance(bp, int):
            raise err_validation("measured_values.bolts_passed must be an integer")
        result = "CONFORMING" if (bt >= 1 and bp == bt) else "NONCONFORMING"
        return result, {"bolts_tested": bt, "bolts_passed": bp}
    else:
        raise err_validation("Unsupported field test method")


@app.route("/api/field-tests", methods=["POST"])
def create_field_test():
    uid, role = require_role("Technician")
    data = get_json()
    assignment_id = req_str(data, "assignment_id")
    measured = req_field(data, "measured_values")
    if not isinstance(measured, dict):
        raise err_validation("measured_values must be an object")
    a = DB["assignments"].get(assignment_id)
    if not a:
        raise err_not_found("Assignment not found")
    if a["technician_id"] != uid:
        raise err_forbidden("Only the assigned technician may record field tests on this assignment")
    if a["status"] != "DISPATCHED":
        raise err_invalid_state("Assignment not in DISPATCHED")
    project = get_project_or_404(a["project_id"])
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    scope = get_scope_or_404(a["scope_item_id"])
    if scope["test_method"] == "CONCRETE_STRENGTH":
        raise err_validation("CONCRETE_STRENGTH results are recorded via lab samples, not field tests")
    result, details = _evaluate_field_test(scope, measured)

    common = new_common()
    ft = {
        **common,
        "assignment_id": assignment_id,
        "measured_values": measured,
        "test_method": scope["test_method"],
        "technician_id": a["technician_id"],
        "project_id": a["project_id"],
        "result": result,
        "result_details": details,
        "status": "RECORDED",
    }
    DB["field_tests"][ft["id"]] = ft

    if result == "CONFORMING":
        recompute_scope_and_posture(scope, project)
    else:
        severity = "STRUCTURAL" if scope.get("is_structural") else "MAJOR"
        desc = "Nonconforming %s field test on scope item %s" % (scope["test_method"], scope["id"])
        auto_create_ncr(project, "FIELD_TEST", ft["id"], scope["id"], severity, desc)
        recompute_posture(project)
        touch(project)
    return ok_object(ft_view(ft), 201)


@app.route("/api/assignments/<aid>/field-tests", methods=["GET"])
def list_field_tests(aid):
    get_auth()
    get_asg_or_404(aid)
    items = [f for f in DB["field_tests"].values() if f["assignment_id"] == aid]
    items = sort_created(items)
    return paginate([ft_view(f) for f in items])


@app.route("/api/field-tests/<fid>/void", methods=["POST"])
def void_field_test(fid):
    uid, role = require_role("ProjectManager")
    ft = get_ft_or_404(fid)
    if ft["status"] == "VOIDED" or ft["result"] != "CONFORMING":
        raise ApiError("ERR_TEST_NOT_VOIDABLE", "Field test not voidable", 409)
    a = get_asg_or_404(ft["assignment_id"])
    project = get_project_or_404(a["project_id"])
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    scope = get_scope_or_404(a["scope_item_id"])
    ft["status"] = "VOIDED"
    touch(ft)
    recompute_scope_and_posture(scope, project)
    return ok_object(ft_view(ft))


# --------------------------------------------------------------------------
# Labs + Lab samples
# --------------------------------------------------------------------------

@app.route("/api/labs", methods=["POST"])
def create_lab():
    uid, role = require_role("AgencyAdmin")
    data = get_json()
    name = req_str(data, "name")
    code = req_str(data, "lab_code")
    cap = req_int(data, "daily_break_capacity")
    if cap < 1:
        raise err_validation("daily_break_capacity must be >= 1")
    for l in DB["labs"].values():
        if l["lab_code"] == code:
            raise err_validation("Duplicate lab_code")
    common = new_common()
    lab = {**common, "name": name, "lab_code": code, "daily_break_capacity": cap}
    DB["labs"][lab["id"]] = lab
    return ok_object(lab_view(lab), 201)


@app.route("/api/labs/<lid>", methods=["GET"])
def get_lab(lid):
    get_auth()
    lab = get_lab_or_404(lid)
    return ok_object(lab_view(lab))


@app.route("/api/labs/<lid>/lab-samples", methods=["GET"])
def list_lab_samples(lid):
    get_auth()
    get_lab_or_404(lid)
    items = [s for s in DB["lab_samples"].values() if s["lab_id"] == lid]
    bsd = request.args.get("break_scheduled_date")
    if bsd:
        items = [s for s in items if s.get("break_scheduled_date") == bsd]
    items = sort_created(items)
    return paginate([ls_view(s) for s in items])


TOLERANCE_BY_AGE = {7: 6, 28: 24, 56: 48}
TOLERANCE_DEFAULT = 12


@app.route("/api/lab-samples", methods=["POST"])
def create_lab_sample():
    uid, role = require_role("Technician")
    data = get_json()
    assignment_id = req_str(data, "assignment_id")
    lab_id = req_str(data, "lab_id")
    cast_at_s = req_str(data, "cast_at")
    age_days = req_int(data, "required_break_age_days")
    if age_days not in (7, 28, 56):
        raise err_validation("required_break_age_days must be one of 7, 28, 56")
    cast_dt = parse_datetime(cast_at_s)
    if cast_dt is None:
        raise err_validation("cast_at must be ISO8601 datetime")
    a = DB["assignments"].get(assignment_id)
    if not a:
        raise err_not_found("Assignment not found")
    if a["technician_id"] != uid:
        raise err_forbidden("Only the assigned technician may log lab samples on this assignment")
    if a["status"] != "DISPATCHED":
        raise err_invalid_state("Assignment not in DISPATCHED")
    lab = DB["labs"].get(lab_id)
    if not lab:
        raise err_not_found("Lab not found")
    project = get_project_or_404(a["project_id"])
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    scope = get_scope_or_404(a["scope_item_id"])
    if scope["test_method"] != "CONCRETE_STRENGTH":
        raise err_validation("Assignment scope item is not CONCRETE_STRENGTH")

    break_due = cast_dt + timedelta(days=age_days)
    common = new_common()
    s = {
        **common,
        "assignment_id": assignment_id,
        "lab_id": lab_id,
        "cast_at": _fmt_dt(cast_dt),
        "required_break_age_days": age_days,
        "break_due_at": _fmt_dt(break_due),
        "break_scheduled_date": None,
        "broken_at": None,
        "cylinder_strengths_psi": None,
        "set_average_psi": None,
        "age_at_break_hours": None,
        "within_tolerance": None,
        "flagged_out_of_tolerance": None,
        "break_result": None,
        "status": "CAST",
    }
    DB["lab_samples"][s["id"]] = s
    return ok_object(ls_view(s), 201)


@app.route("/api/lab-samples/<sid>", methods=["GET"])
def get_lab_sample(sid):
    get_auth()
    s = get_ls_or_404(sid)
    return ok_object(ls_view(s))


@app.route("/api/assignments/<aid>/lab-samples", methods=["GET"])
def list_assignment_lab_samples(aid):
    get_auth()
    get_asg_or_404(aid)
    items = [s for s in DB["lab_samples"].values() if s["assignment_id"] == aid]
    items = sort_created(items)
    return paginate([ls_view(s) for s in items])


@app.route("/api/lab-samples/<sid>/schedule-break", methods=["POST"])
def schedule_break(sid):
    uid, role = require_role("LabAnalyst")
    s = get_ls_or_404(sid)
    if s["status"] != "CAST":
        raise err_invalid_state("Sample not in CAST")
    data = get_json()
    bsd_s = req_str(data, "break_scheduled_date")
    bsd = parse_date(bsd_s)
    if bsd is None:
        raise err_validation("break_scheduled_date must be ISO date")
    due_dt = parse_datetime(s["break_due_at"])
    if bsd != due_dt.date():
        raise ApiError("ERR_BREAK_DATE_MISMATCH", "break_scheduled_date must equal date(break_due_at)", 422)
    lab = get_lab_or_404(s["lab_id"])
    # capacity check
    load = 0
    for other in DB["lab_samples"].values():
        if other["lab_id"] == lab["id"] and other.get("break_scheduled_date") == bsd_s and other["status"] == "BREAK_SCHEDULED":
            load += 1
    if load >= lab["daily_break_capacity"]:
        raise ApiError("ERR_LAB_DAY_CAPACITY", "Lab day at capacity", 409)
    s["break_scheduled_date"] = bsd_s
    s["status"] = "BREAK_SCHEDULED"
    touch(s)
    return ok_object(ls_view(s))


@app.route("/api/lab-samples/<sid>/record-break", methods=["POST"])
def record_break(sid):
    uid, role = require_role("LabAnalyst")
    s = get_ls_or_404(sid)
    if s["status"] != "BREAK_SCHEDULED":
        raise err_invalid_state("Sample not in BREAK_SCHEDULED")
    data = get_json()
    broken_at_s = req_str(data, "broken_at")
    broken_dt = parse_datetime(broken_at_s)
    if broken_dt is None:
        raise err_validation("broken_at must be ISO8601 datetime")
    strengths = req_field(data, "cylinder_strengths_psi")
    if not isinstance(strengths, list) or len(strengths) < 1:
        raise err_validation("cylinder_strengths_psi must be a non-empty array")
    for v in strengths:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err_validation("cylinder_strengths_psi entries must be numbers")

    a = get_asg_or_404(s["assignment_id"])
    project = get_project_or_404(a["project_id"])
    scope = get_scope_or_404(a["scope_item_id"])
    ssi = get_ssi_or_404(a["ssi_revision_id"])

    # set average on 10-psi grid
    total = sum(Decimal(str(v)) for v in strengths)
    mean = total / Decimal(len(strengths))
    set_avg = _round_to_grid_10(mean)

    # age at break hours
    cast_dt = parse_datetime(s["cast_at"])
    delta_seconds = (broken_dt - cast_dt).total_seconds()
    age_hours = int((Decimal(str(delta_seconds)) / Decimal(3600)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # tolerance
    due_dt = parse_datetime(s["break_due_at"])
    tol_hours = TOLERANCE_BY_AGE.get(s["required_break_age_days"], TOLERANCE_DEFAULT)
    delta_min = abs((broken_dt - due_dt).total_seconds()) / 60.0
    delta_hours_dec = Decimal(str(delta_min)) / Decimal(60)
    within = delta_hours_dec <= Decimal(tol_hours)
    flagged = not within

    # acceptance
    fc = ssi["specified_fc_psi"]
    if fc <= 5000:
        individual_floor = fc - 500
    else:
        individual_floor = int((Decimal(fc) * Decimal("0.90")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # gather set averages of all REPORTED non-discarded samples on the same scope item
    others = []
    for other in DB["lab_samples"].values():
        if other["id"] == s["id"]:
            continue
        oa = DB["assignments"].get(other["assignment_id"])
        if not oa:
            continue
        if oa["scope_item_id"] != scope["id"]:
            continue
        if other["status"] != "REPORTED":
            continue
        if other.get("set_average_psi") is None:
            continue
        others.append(other)
    others_sorted = sorted(others, key=lambda o: (o["break_due_at"], o["created_at"]))

    if ssi["acceptance_method_concrete"] == "MOVING_AVERAGE":
        window_entries = [o["set_average_psi"] for o in others_sorted] + [set_avg]
        # order by break_due_at asc, created_at asc — this sample's break_due_at relative order:
        # rebuild the full ordering including this sample
        all_with_self = list(others_sorted) + [{"break_due_at": s["break_due_at"], "created_at": s["created_at"], "set_average_psi": set_avg, "id": s["id"]}]
        all_sorted = sorted(all_with_self, key=lambda o: (o["break_due_at"], o["created_at"]))
        window = [o["set_average_psi"] for o in all_sorted][-3:]
        win_mean = Decimal(sum(window)) / Decimal(len(window))
        moving_avg = _round_to_grid_10(win_mean)
        conforming = (moving_avg >= fc) and all(w >= individual_floor for w in window)
        break_result = "CONFORMING" if conforming else "NONCONFORMING"
        result_details_extra = {"moving_average_psi": moving_avg, "window": window, "individual_floor": individual_floor}
    else:  # INDIVIDUAL_SET
        break_result = "CONFORMING" if set_avg >= fc else "NONCONFORMING"
        result_details_extra = {"individual_floor": individual_floor}

    s["broken_at"] = _fmt_dt(broken_dt)
    s["cylinder_strengths_psi"] = list(strengths)
    s["set_average_psi"] = set_avg
    s["age_at_break_hours"] = age_hours
    s["within_tolerance"] = within
    s["flagged_out_of_tolerance"] = flagged
    s["break_result"] = break_result
    s["status"] = "REPORTED"
    s["result_details"] = result_details_extra
    touch(s)

    if break_result == "CONFORMING":
        recompute_scope_completion(scope)
        touch(scope)

    if break_result == "NONCONFORMING":
        severity = "STRUCTURAL" if scope.get("is_structural") else "MAJOR"
        desc = "Nonconforming concrete break on scope item %s" % scope["id"]
        auto_create_ncr(project, "LAB_SAMPLE", s["id"], scope["id"], severity, desc)

    if flagged:
        desc = "Break out of tolerance on scope item %s" % scope["id"]
        auto_create_ncr(project, "LAB_SAMPLE", s["id"], scope["id"], "MINOR", desc)

    recompute_posture(project)
    touch(project)
    return ok_object(ls_view(s))


@app.route("/api/lab-samples/<sid>/discard", methods=["POST"])
def discard_sample(sid):
    uid, role = require_role("LabAnalyst")
    s = get_ls_or_404(sid)
    if s["status"] != "CAST":
        raise err_invalid_state("Sample not in CAST")
    s["status"] = "DISCARDED"
    touch(s)
    return ok_object(ls_view(s))


# --------------------------------------------------------------------------
# NCRs
# --------------------------------------------------------------------------

@app.route("/api/projects/<pid>/ncrs", methods=["GET"])
def list_ncrs(pid):
    get_auth()
    get_project_or_404(pid)
    items = [n for n in DB["ncrs"].values() if n["project_id"] == pid]
    st = request.args.get("status")
    sev = request.args.get("severity")
    sci = request.args.get("scope_item_id")
    if st:
        items = [n for n in items if n["status"] == st]
    if sev:
        items = [n for n in items if n["severity"] == sev]
    if sci:
        items = [n for n in items if n["scope_item_id"] == sci]
    items = sort_created(items)
    return paginate([ncr_view(n) for n in items])


@app.route("/api/ncrs/<nid>/submit-correction", methods=["POST"])
def submit_correction(nid):
    uid, role = require_role("Contractor")
    n = get_ncr_or_404(nid)
    if n["status"] not in ("OPEN", "ESCALATED"):
        raise err_invalid_state("NCR not in OPEN or ESCALATED")
    data = get_json()
    note = req_str(data, "correction_note")
    n["correction_note"] = note
    n["status"] = "CORRECTION_SUBMITTED"
    touch(n)
    return ok_object(ncr_view(n))


def _source_technician_id(ncr):
    if ncr["source_type"] == "FIELD_TEST":
        ft = DB["field_tests"].get(ncr["source_id"])
        if ft:
            return ft["technician_id"]
        return None
    else:
        s = DB["lab_samples"].get(ncr["source_id"])
        if not s:
            return None
        a = DB["assignments"].get(s["assignment_id"])
        if not a:
            return None
        return a["technician_id"]


@app.route("/api/ncrs/<nid>/verify", methods=["POST"])
def verify_ncr(nid):
    uid, role = require_role("Technician")
    n = get_ncr_or_404(nid)
    data = get_json()
    outcome = req_str(data, "outcome")
    if outcome not in ("VERIFIED", "REJECTED"):
        raise err_validation("outcome must be VERIFIED or REJECTED")
    if n["status"] != "CORRECTION_SUBMITTED":
        raise err_invalid_state("NCR not in CORRECTION_SUBMITTED")
    # segregation of duties
    source_tech = _source_technician_id(n)
    if source_tech is not None and source_tech == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Verifier must differ from the source result's technician", 409)
    evidence_id = data.get("evidence_field_test_id")
    if outcome == "VERIFIED" and evidence_id is not None:
        ev = DB["field_tests"].get(evidence_id)
        if not ev:
            raise ApiError("ERR_REFERENCE_MISMATCH", "Evidence field test does not resolve", 422)
        if ev["status"] != "RECORDED" or ev["result"] != "CONFORMING":
            raise ApiError("ERR_REFERENCE_MISMATCH", "Evidence field test must be RECORDED and CONFORMING", 422)
        ea = DB["assignments"].get(ev["assignment_id"])
        if not ea or ea["scope_item_id"] != n["scope_item_id"]:
            raise ApiError("ERR_REFERENCE_MISMATCH", "Evidence field test must be on the same scope item", 422)

    project = get_project_or_404(n["project_id"])
    if outcome == "VERIFIED":
        n["status"] = "VERIFIED"
        n["verified_by_technician_id"] = uid
        if evidence_id is not None:
            n["evidence_field_test_id"] = evidence_id
        touch(n)
        recompute_posture(project)
        touch(project)
    else:
        n["status"] = "OPEN"
        n["rejection_count"] += 1
        n["correction_note"] = None
        touch(n)
        recompute_posture(project)
        touch(project)
    return ok_object(ncr_view(n))


# --------------------------------------------------------------------------
# Daily inspection reports
# --------------------------------------------------------------------------

@app.route("/api/daily-reports", methods=["POST"])
def create_daily_report():
    uid, role = require_role("Technician")
    data = get_json()
    project_id = req_str(data, "project_id")
    report_date_s = req_str(data, "report_date")
    assignment_ids = req_field(data, "assignment_ids")
    summary = req_str(data, "summary")
    rd = parse_date(report_date_s)
    if rd is None:
        raise err_validation("report_date must be ISO date")
    if not isinstance(assignment_ids, list):
        raise err_validation("assignment_ids must be an array")
    project = get_project_or_404(project_id)
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    # duplicate
    for d in DB["daily_reports"].values():
        if d["project_id"] == project_id and d["technician_id"] == uid and d["report_date"] == report_date_s:
            raise ApiError("ERR_DUPLICATE_DAILY_REPORT", "A daily report already exists for this triple", 409)
    # validate assignments
    for aid in assignment_ids:
        if not isinstance(aid, str):
            raise err_validation("assignment_ids entries must be strings")
        a = DB["assignments"].get(aid)
        if not a:
            raise ApiError("ERR_REFERENCE_MISMATCH", "Assignment %s does not resolve" % aid, 422)
        if a["technician_id"] != uid:
            raise ApiError("ERR_REFERENCE_MISMATCH", "Assignment belongs to another technician", 422)
        if a["project_id"] != project_id:
            raise ApiError("ERR_REFERENCE_MISMATCH", "Assignment belongs to another project", 422)
        if a["work_date"] != report_date_s:
            raise ApiError("ERR_REFERENCE_MISMATCH", "Assignment work_date does not match report_date", 422)
        if a["status"] != "COMPLETED":
            raise ApiError("ERR_REFERENCE_MISMATCH", "Assignment is not COMPLETED", 422)
        if a.get("covered_by_dir_id"):
            raise ApiError("ERR_REFERENCE_MISMATCH", "Assignment is already covered", 422)

    common = new_common()
    d = {
        **common,
        "project_id": project_id,
        "technician_id": uid,
        "report_date": report_date_s,
        "assignment_ids": list(assignment_ids),
        "summary": summary,
        "status": "SUBMITTED",
        "acknowledged_by": None,
    }
    DB["daily_reports"][d["id"]] = d
    for aid in assignment_ids:
        a = DB["assignments"][aid]
        a["covered_by_dir_id"] = d["id"]
        touch(a)
    recompute_posture(project)
    touch(project)
    return ok_object(dir_view(d), 201)


@app.route("/api/projects/<pid>/daily-reports", methods=["GET"])
def list_daily_reports(pid):
    get_auth()
    get_project_or_404(pid)
    items = [d for d in DB["daily_reports"].values() if d["project_id"] == pid]
    tid = request.args.get("technician_id")
    rd = request.args.get("report_date")
    if tid:
        items = [d for d in items if d["technician_id"] == tid]
    if rd:
        items = [d for d in items if d["report_date"] == rd]
    items = sort_created(items)
    return paginate([dir_view(d) for d in items])


@app.route("/api/daily-reports/<did>/acknowledge", methods=["POST"])
def acknowledge_report(did):
    uid, role = require_role("BuildingOfficial")
    d = get_dir_or_404(did)
    if d["status"] != "SUBMITTED":
        raise err_invalid_state("Report not in SUBMITTED")
    d["status"] = "ACKNOWLEDGED"
    d["acknowledged_by"] = uid
    touch(d)
    return ok_object(dir_view(d))


# --------------------------------------------------------------------------
# Discrepancies
# --------------------------------------------------------------------------

@app.route("/api/discrepancies", methods=["POST"])
def create_discrepancy():
    uid, role = require_role("Technician")
    data = get_json()
    project_id = req_str(data, "project_id")
    subject = req_str(data, "subject")
    description = req_str(data, "description")
    routed_to = req_str(data, "routed_to")
    if routed_to not in ("CONTRACTOR", "ENGINEER"):
        raise err_validation("routed_to must be CONTRACTOR or ENGINEER")
    scope_item_id = data.get("scope_item_id")
    project = get_project_or_404(project_id)
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_COMPLETED", "Project is COMPLETED", 409)
    if scope_item_id is not None:
        sc = DB["scope_items"].get(scope_item_id)
        if not sc:
            raise ApiError("ERR_REFERENCE_MISMATCH", "scope_item_id does not resolve", 422)
        ssi = DB["ssi_revisions"].get(sc["ssi_revision_id"])
        if not ssi or ssi["project_id"] != project_id:
            raise ApiError("ERR_REFERENCE_MISMATCH", "scope_item belongs to another project", 422)
    common = new_common()
    d = {
        **common,
        "project_id": project_id,
        "scope_item_id": scope_item_id,
        "raised_by_technician_id": uid,
        "subject": subject,
        "description": description,
        "routed_to": routed_to,
        "response_text": None,
        "round_count": 1,
        "status": "RAISED",
    }
    DB["discrepancies"][d["id"]] = d
    recompute_posture(project)
    touch(project)
    return ok_object(disc_view(d), 201)


@app.route("/api/projects/<pid>/discrepancies", methods=["GET"])
def list_discrepancies(pid):
    get_auth()
    get_project_or_404(pid)
    items = [d for d in DB["discrepancies"].values() if d["project_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [d for d in items if d["status"] == st]
    items = sort_created(items)
    return paginate([disc_view(d) for d in items])


@app.route("/api/discrepancies/<did>/respond", methods=["POST"])
def respond_discrepancy(did):
    uid, role = require_role("Contractor", "EngineerOfRecord")
    d = get_disc_or_404(did)
    # routing check (priority 2 tier)
    expected_role = "Contractor" if d["routed_to"] == "CONTRACTOR" else "EngineerOfRecord"
    if role != expected_role:
        raise ApiError("ERR_DISCREPANCY_ROUTING", "Caller role does not match routed_to", 403)
    if d["status"] != "RAISED":
        raise err_invalid_state("Ticket not in RAISED")
    data = get_json()
    txt = req_str(data, "response_text")
    d["response_text"] = txt
    d["status"] = "RESPONSE_SUBMITTED"
    touch(d)
    return ok_object(disc_view(d))


@app.route("/api/discrepancies/<did>/resolve", methods=["POST"])
def resolve_discrepancy(did):
    uid, role = require_role("Technician")
    d = get_disc_or_404(did)
    if d["status"] != "RESPONSE_SUBMITTED":
        raise err_invalid_state("Ticket not in RESPONSE_SUBMITTED")
    data = get_json()
    outcome = req_str(data, "outcome")
    if outcome not in ("ACCEPT", "REJECT"):
        raise err_validation("outcome must be ACCEPT or REJECT")
    project = get_project_or_404(d["project_id"])
    if outcome == "ACCEPT":
        d["status"] = "RESOLVED"
        touch(d)
        recompute_posture(project)
        touch(project)
    else:
        d["status"] = "RAISED"
        d["round_count"] += 1
        d["response_text"] = None
        touch(d)
    return ok_object(disc_view(d))


# --------------------------------------------------------------------------
# Final letter
# --------------------------------------------------------------------------

@app.route("/api/projects/<pid>/issue-letter", methods=["POST"])
def issue_letter(pid):
    uid, role = require_role("ProjectManager")
    p = get_project_or_404(pid)
    if p["letter_status"] == "ISSUED":
        raise ApiError("ERR_LETTER_ALREADY_ISSUED", "Letter already issued", 409)
    if p["compliance_posture"] != "READY_FOR_LETTER":
        raise ApiError("ERR_POSTURE_NOT_READY", "Posture is not READY_FOR_LETTER", 409)
    p["letter_status"] = "ISSUED"
    p["letter_issued_at"] = iso_now()
    p["letter_issued_by"] = uid
    p["status"] = "COMPLETED"
    p["compliance_posture"] = "LETTER_ISSUED"
    touch(p)
    return ok_object(proj_view(p))


@app.route("/api/projects/<pid>/void-letter", methods=["POST"])
def void_letter(pid):
    uid, role = require_role("BuildingOfficial")
    p = get_project_or_404(pid)
    if p["letter_status"] != "ISSUED":
        raise ApiError("ERR_NO_LETTER_TO_VOID", "No letter to void", 409)
    data = get_json()
    reason = req_str(data, "void_reason")
    p["letter_status"] = "VOIDED"
    p["letter_void_reason"] = reason
    p["status"] = "ACTIVE"
    recompute_posture(p)
    touch(p)
    return ok_object(proj_view(p))


# --------------------------------------------------------------------------
# Ops / clock
# --------------------------------------------------------------------------

@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = require_role("AgencyAdmin")
    data = get_json()
    to_iso = req_str(data, "to_iso8601")
    dt = parse_datetime(to_iso)
    if dt is None:
        raise err_validation("to_iso8601 must be ISO8601")
    _CLOCK["now"] = dt
    return ok_object({"current_utc": _fmt_dt(_CLOCK["now"])})


@app.route("/api/ops/run-daily-sweep", methods=["POST"])
def run_daily_sweep():
    uid, role = require_role("AgencyAdmin")
    today = clock_now().date()
    escalated = []
    affected_projects = set()
    for n in DB["ncrs"].values():
        if n["status"] != "OPEN":
            continue
        detected_dt = parse_datetime(n["detected_at"])
        detected_date = detected_dt.date()
        days_open = (today - detected_date).days
        if days_open < 0:
            days_open = 0
        deadline_d = parse_date(n["deadline_date"])
        days_past = (today - deadline_d).days
        if days_past < 0:
            days_past = 0
        if n["severity"] == "STRUCTURAL" and days_past > 0:
            score = 100
        else:
            base = SEVERITY_BASE[n["severity"]]
            score = base + 2 * days_open + 3 * days_past + 15 * n["rejection_count"]
            if score > 100:
                score = 100
        n["escalation_score"] = score
        if score >= ESCALATION_THRESHOLD:
            n["status"] = "ESCALATED"
            escalated.append(n["id"])
            affected_projects.add(n["project_id"])
        touch(n)
    for pid in affected_projects:
        p = DB["projects"].get(pid)
        if p:
            recompute_posture(p)
            touch(p)
    return ok_object({"escalated_ncr_ids": escalated})


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
