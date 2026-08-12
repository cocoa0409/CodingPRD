#!/usr/bin/env python3
"""HOA Architectural Review API - in-memory Flask implementation (PRD workspace/PRD.md).

Storage is process-local dicts only; the store starts empty on every boot.
Logical clock defaults to 2026-05-01T00:00:00Z and never uses wall-clock time.
"""

import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------- clock ----
_clock = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def logical_now():
    return _clock["now"]


def logical_today():
    return _clock["now"].date()


def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    s = value.strip()
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_str(value):
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise ValueError("not an ISO date (YYYY-MM-DD)")
    return date.fromisoformat(value.strip())


# ---------------------------------------------------------------- errors ---
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(logical_now()),
    }


def respond_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def respond_list(items, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return respond_error(err)


@app.errorhandler(404)
def _handle_404(_e):
    return respond_error(ApiError("ERR_INVALID_REQUEST", 404, "Route not found"))


@app.errorhandler(405)
def _handle_405(_e):
    return respond_error(ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed"))


@app.errorhandler(500)
def _handle_500(_e):
    return respond_error(ApiError("ERR_INVALID_REQUEST", 500, "Internal server error"))


# ------------------------------------------------------------------ store --
db = {
    "associations": {},
    "owners": {},
    "properties": {},
    "applications": {},
    "attachments": {},
    "votes": {},
    "appeals": {},
    "permits": {},
    "blackouts": {},
    "inspections": {},
    "violations": {},
    "fines": {},
    "liens": {},
    "variances": {},
}
_seq = {"n": 0}


def new_record(fields):
    _seq["n"] += 1
    ts = fmt_ts(logical_now())
    rec = {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}
    rec.update(fields)
    rec["_seq"] = _seq["n"]
    return rec


def touch(rec):
    rec["updated_at"] = fmt_ts(logical_now())
    rec["version"] += 1


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_recs(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


# ------------------------------------------------------------------- auth --
ROLE_MANAGER = "Manager"
ROLE_HOMEOWNER = "Homeowner"
ROLE_COMMITTEE = "CommitteeMember"
ROLE_BOARD = "BoardMember"
ROLE_INSPECTOR = "Inspector"
ALL_ROLES = {ROLE_MANAGER, ROLE_HOMEOWNER, ROLE_COMMITTEE, ROLE_BOARD, ROLE_INSPECTOR}


def authenticate():
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and the role must be declared")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s is not permitted on this operation" % role)


# --------------------------------------------------------- body validation -
def v_string(name):
    def check(v):
        if not isinstance(v, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % name)
        return v
    return check


def v_int(name, minimum=None, maximum=None):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % name)
        if minimum is not None and v < minimum:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be >= %d" % (name, minimum))
        if maximum is not None and v > maximum:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be <= %d" % (name, maximum))
        return v
    return check


def v_bool(name):
    def check(v):
        if not isinstance(v, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a boolean" % name)
        return v
    return check


def v_enum(name, members):
    def check(v):
        if not isinstance(v, str) or v not in members:
            raise ApiError("ERR_INVALID_ENUM", 400,
                           "Field '%s' must be one of %s" % (name, sorted(members)))
        return v
    return check


def v_date(name):
    def check(v):
        try:
            return parse_date_str(v).isoformat()
        except (ValueError, AttributeError):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Field '%s' must be an ISO date YYYY-MM-DD" % name)
    return check


def v_datetime(name):
    def check(v):
        if not isinstance(v, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an ISO 8601 string" % name)
        try:
            return parse_dt(v)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an ISO 8601 datetime" % name)
    return check


def v_str_list(name):
    def check(v):
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a list of strings" % name)
        return list(v)
    return check


def validate_body(spec):
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    unknown = [k for k in data if k not in spec]
    if unknown:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown body field(s): %s" % ", ".join(sorted(unknown)))
    out = {}
    for name, (required, validator) in spec.items():
        if name not in data or data[name] is None:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field '%s'" % name)
            continue
        out[name] = validator(data[name])
    return out


# -------------------------------------------------------------- existence --
def get_association(aid):
    rec = db["associations"].get(aid)
    if rec is None:
        raise ApiError("ERR_ASSOCIATION_NOT_FOUND", 404, "Association %s does not exist" % aid)
    return rec


def get_owner(oid):
    rec = db["owners"].get(oid)
    if rec is None:
        raise ApiError("ERR_OWNER_NOT_FOUND", 404, "Owner %s does not exist" % oid)
    return rec


def get_property(pid):
    rec = db["properties"].get(pid)
    if rec is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", 404, "Property %s does not exist" % pid)
    return rec


def get_application(aid):
    rec = db["applications"].get(aid)
    if rec is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application %s does not exist" % aid)
    return rec


def get_permit(pid):
    rec = db["permits"].get(pid)
    if rec is None:
        raise ApiError("ERR_PERMIT_NOT_FOUND", 404, "ConstructionPermit %s does not exist" % pid)
    return rec


def get_inspection(iid):
    rec = db["inspections"].get(iid)
    if rec is None:
        raise ApiError("ERR_INSPECTION_NOT_FOUND", 404, "Inspection %s does not exist" % iid)
    return rec


def get_violation(vid):
    rec = db["violations"].get(vid)
    if rec is None:
        raise ApiError("ERR_VIOLATION_NOT_FOUND", 404, "Violation %s does not exist" % vid)
    return rec


def get_fine(fid):
    rec = db["fines"].get(fid)
    if rec is None:
        raise ApiError("ERR_FINE_NOT_FOUND", 404, "Fine %s does not exist" % fid)
    return rec


def get_lien(lid):
    rec = db["liens"].get(lid)
    if rec is None:
        raise ApiError("ERR_LIEN_NOT_FOUND", 404, "Lien %s does not exist" % lid)
    return rec


def get_appeal(aid):
    rec = db["appeals"].get(aid)
    if rec is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND", 404, "Appeal %s does not exist" % aid)
    return rec


def association_of_property(prop):
    return db["associations"].get(prop["association_id"])


def property_of_application(app_rec):
    return db["properties"].get(app_rec["property_id"])


def fine_of_violation(violation_id):
    for f in db["fines"].values():
        if f["violation_id"] == violation_id:
            return f
    return None


# ------------------------------------------------------------- pagination --
def paginate(items):
    total = len(items)
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return items[offset:offset + limit], total, limit, offset


def list_response(recs):
    ordered = sorted_recs(recs)
    page, total, limit, offset = paginate(ordered)
    return respond_list([pub(r) for r in page], total, limit, offset)


def enum_filter(param, members):
    raw = request.args.get(param)
    if raw is None:
        return None
    if raw not in members:
        raise ApiError("ERR_INVALID_ENUM", 400, "Query parameter '%s' must be one of %s"
                       % (param, sorted(members)))
    return raw


# ------------------------------------------------------------ calculations -
def countable_days(a, b, mode):
    """Days d with a < d <= b; CALENDAR counts all, BUSINESS counts Mon-Fri."""
    if b <= a:
        return 0
    if mode == "CALENDAR":
        return (b - a).days
    n = 0
    d = a + timedelta(days=1)
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def fine_increment(fine, k):
    """Per-day increment for day index k (1-based), rounded half up per day."""
    if fine["mode_snapshot"] == "SIMPLE_DAILY":
        return fine["daily_rate_cents"]
    if k <= fine["grace_days_snapshot"]:
        return fine["daily_rate_cents"]
    raw = Decimal(fine["daily_rate_cents"] * fine["escalation_multiplier_bp_snapshot"]) / Decimal(10000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def accrual_addition(fine, target):
    """(total_increment, days_applied) for days in (accrued_through_date, target]."""
    start = parse_dt(fine["started_at"]).date()
    through = date.fromisoformat(fine["accrued_through_date"])
    if target <= through:
        return 0, 0
    k0 = (through - start).days + 1
    k1 = (target - start).days
    total = 0
    for k in range(k0, k1 + 1):
        total += fine_increment(fine, k)
    return total, k1 - k0 + 1


def accrue_fine_to(fine, target, touch_it=True):
    add, n = accrual_addition(fine, target)
    if n == 0:
        return False
    fine["accrued_cents"] += add
    fine["accrued_through_date"] = target.isoformat()
    fine["outstanding_cents"] = fine["accrued_cents"] - fine["settled_cents"] - fine["waived_cents"]
    if touch_it:
        touch(fine)
    return True


def recompute_property(prop):
    bal = 0
    for v in db["violations"].values():
        if v["property_id"] == prop["id"]:
            f = fine_of_violation(v["id"])
            if f is not None:
                bal += f["outstanding_cents"]
    cnt = 0
    for p in db["permits"].values():
        if p["status"] == "ACTIVE":
            ap = db["applications"].get(p["application_id"])
            if ap is not None and ap["property_id"] == prop["id"]:
                cnt += 1
    filed = any(l["property_id"] == prop["id"] and l["status"] == "FILED"
                for l in db["liens"].values())
    posture = "LIENED" if filed else ("FINES_OUTSTANDING" if bal > 0 else "CLEAR")
    if (prop["outstanding_fine_balance_cents"] != bal
            or prop["open_permit_count"] != cnt
            or prop["compliance_posture"] != posture):
        prop["outstanding_fine_balance_cents"] = bal
        prop["open_permit_count"] = cnt
        prop["compliance_posture"] = posture
        touch(prop)


def check_window_conflicts(assoc_id, prop_id, s, e, exclude_permit_id=None):
    """8a ERR_WINDOW_OVERLAP (half-open permits) then 8b ERR_BLACKOUT_CONFLICT (closed)."""
    for p in db["permits"].values():
        if p["status"] != "ACTIVE" or p["id"] == exclude_permit_id:
            continue
        ap = db["applications"].get(p["application_id"])
        if ap is None or ap["property_id"] != prop_id:
            continue
        ps = date.fromisoformat(p["window_start"])
        pe = date.fromisoformat(p["window_end"])
        if s < pe and ps < e:
            raise ApiError("ERR_WINDOW_OVERLAP", 409,
                           "Window overlaps another ACTIVE permit on the same property")
    for b in db["blackouts"].values():
        if b["association_id"] != assoc_id:
            continue
        bs = date.fromisoformat(b["start_date"])
        be = date.fromisoformat(b["end_date"])
        if s <= be and e > bs:
            raise ApiError("ERR_BLACKOUT_CONFLICT", 422,
                           "Window intersects a blackout period")


def create_permit(app_rec):
    permit = new_record({
        "application_id": app_rec["id"],
        "window_start": app_rec["requested_window_start"],
        "window_end": app_rec["requested_window_end"],
        "contractor_name": "",
        "contractor_license": "",
        "status": "ACTIVE",
        "completed_at": None,
    })
    db["permits"][permit["id"]] = permit
    prop = property_of_application(app_rec)
    if prop is not None:
        recompute_property(prop)
    return permit


def create_violation(prop, assoc, kind, description,
                     application_id="", source_inspection_id="", source_permit_id=""):
    d = logical_today()
    viol = new_record({
        "property_id": prop["id"],
        "application_id": application_id,
        "source_inspection_id": source_inspection_id,
        "source_permit_id": source_permit_id,
        "kind": kind,
        "description": description,
        "status": "OPEN",
        "remediation_deadline": (d + timedelta(days=assoc["remediation_days"])).isoformat(),
        "escalated_at": None,
        "remediated_at": None,
    })
    db["violations"][viol["id"]] = viol
    fine = new_record({
        "violation_id": viol["id"],
        "mode_snapshot": assoc["fine_mode"],
        "base_cents": assoc["base_fine_cents"],
        "daily_rate_cents": assoc["daily_fine_cents"],
        "grace_days_snapshot": assoc["grace_days"],
        "escalation_multiplier_bp_snapshot": assoc["escalation_multiplier_bp"],
        "accrued_cents": assoc["base_fine_cents"],
        "accrued_through_date": d.isoformat(),
        "settled_cents": 0,
        "waived_cents": 0,
        "outstanding_cents": assoc["base_fine_cents"],
        "status": "ACCRUING",
        "started_at": fmt_ts(logical_now()),
        "stopped_at": None,
        "settled_at": None,
    })
    db["fines"][fine["id"]] = fine
    recompute_property(prop)
    return viol, fine


def stop_fine(fine):
    """Accrue to current date (if ACCRUING), then halt accrual."""
    if fine["status"] != "ACCRUING":
        return
    accrue_fine_to(fine, logical_today(), touch_it=False)
    fine["status"] = "STOPPED"
    fine["stopped_at"] = fmt_ts(logical_now())
    fine["outstanding_cents"] = fine["accrued_cents"] - fine["settled_cents"] - fine["waived_cents"]
    touch(fine)


# ======================================================================
# Associations
# ======================================================================
@app.route("/arc/associations", methods=["POST"], strict_slashes=False)
def create_association():
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    vals = validate_body({
        "name": (True, v_string("name")),
        "statutory_response_days": (True, v_int("statutory_response_days", minimum=1)),
        "counting_mode": (True, v_enum("counting_mode", {"CALENDAR", "BUSINESS"})),
        "fine_mode": (True, v_enum("fine_mode", {"SIMPLE_DAILY", "TIERED_ESCALATION"})),
        "base_fine_cents": (True, v_int("base_fine_cents", minimum=0)),
        "daily_fine_cents": (True, v_int("daily_fine_cents", minimum=0)),
        "grace_days": (False, v_int("grace_days", minimum=0)),
        "escalation_multiplier_bp": (False, v_int("escalation_multiplier_bp", minimum=10000)),
        "lien_threshold_cents": (True, v_int("lien_threshold_cents", minimum=1)),
        "lien_min_age_days": (False, v_int("lien_min_age_days", minimum=0)),
        "committee_size": (True, v_int("committee_size", minimum=1)),
        "quorum_min": (True, v_int("quorum_min", minimum=1)),
        "supermajority_required": (False, v_bool("supermajority_required")),
        "max_window_days": (True, v_int("max_window_days", minimum=1)),
        "default_window_days": (False, v_int("default_window_days")),
        "remediation_days": (False, v_int("remediation_days", minimum=0)),
        "appeal_window_days": (False, v_int("appeal_window_days", minimum=1)),
    })
    if vals["quorum_min"] > vals["committee_size"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "quorum_min must be <= committee_size")
    rec = new_record({
        "name": vals["name"],
        "statutory_response_days": vals["statutory_response_days"],
        "counting_mode": vals["counting_mode"],
        "fine_mode": vals["fine_mode"],
        "base_fine_cents": vals["base_fine_cents"],
        "daily_fine_cents": vals["daily_fine_cents"],
        "grace_days": vals.get("grace_days", 0),
        "escalation_multiplier_bp": vals.get("escalation_multiplier_bp", 10000),
        "lien_threshold_cents": vals["lien_threshold_cents"],
        "lien_min_age_days": vals.get("lien_min_age_days", 0),
        "committee_size": vals["committee_size"],
        "quorum_min": vals["quorum_min"],
        "supermajority_required": vals.get("supermajority_required", True),
        "max_window_days": vals["max_window_days"],
        "default_window_days": vals.get("default_window_days", 90),
        "remediation_days": vals.get("remediation_days", 7),
        "appeal_window_days": vals.get("appeal_window_days", 30),
    })
    db["associations"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/associations/<aid>", methods=["GET"], strict_slashes=False)
def read_association(aid):
    authenticate()
    return respond_object(pub(get_association(aid)))


# ======================================================================
# Owners
# ======================================================================
@app.route("/arc/associations/<aid>/owners", methods=["POST"], strict_slashes=False)
def create_owner(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    assoc = get_association(aid)
    vals = validate_body({
        "full_name": (True, v_string("full_name")),
        "email": (True, v_string("email")),
    })
    rec = new_record({
        "association_id": assoc["id"],
        "full_name": vals["full_name"],
        "email": vals["email"],
    })
    db["owners"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/associations/<aid>/owners", methods=["GET"], strict_slashes=False)
def list_owners(aid):
    authenticate()
    assoc = get_association(aid)
    return list_response([o for o in db["owners"].values() if o["association_id"] == assoc["id"]])


@app.route("/arc/owners/<oid>", methods=["GET"], strict_slashes=False)
def read_owner(oid):
    authenticate()
    return respond_object(pub(get_owner(oid)))


@app.route("/arc/owners/<oid>/properties", methods=["GET"], strict_slashes=False)
def list_owner_properties(oid):
    authenticate()
    owner = get_owner(oid)
    return list_response([p for p in db["properties"].values() if p["primary_owner_id"] == owner["id"]])


@app.route("/arc/owners/<oid>/applications", methods=["GET"], strict_slashes=False)
def list_owner_applications(oid):
    authenticate()
    owner = get_owner(oid)
    return list_response([a for a in db["applications"].values() if a["owner_id"] == owner["id"]])


@app.route("/arc/owners/<oid>/votes", methods=["GET"], strict_slashes=False)
def list_owner_votes(oid):
    authenticate()
    owner = get_owner(oid)
    return list_response([v for v in db["votes"].values() if v["voter_owner_id"] == owner["id"]])


# ======================================================================
# Properties
# ======================================================================
@app.route("/arc/associations/<aid>/properties", methods=["POST"], strict_slashes=False)
def create_property(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    assoc = get_association(aid)
    vals = validate_body({
        "lot_number": (True, v_string("lot_number")),
        "address": (True, v_string("address")),
        "primary_owner_id": (True, v_string("primary_owner_id")),
    })
    owner = get_owner(vals["primary_owner_id"])
    rec = new_record({
        "association_id": assoc["id"],
        "primary_owner_id": owner["id"],
        "lot_number": vals["lot_number"],
        "address": vals["address"],
        "outstanding_fine_balance_cents": 0,
        "open_permit_count": 0,
        "compliance_posture": "CLEAR",
    })
    db["properties"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/associations/<aid>/properties", methods=["GET"], strict_slashes=False)
def list_properties(aid):
    authenticate()
    assoc = get_association(aid)
    return list_response([p for p in db["properties"].values() if p["association_id"] == assoc["id"]])


@app.route("/arc/properties/<pid>", methods=["GET"], strict_slashes=False)
def read_property(pid):
    authenticate()
    return respond_object(pub(get_property(pid)))


# ======================================================================
# Blackout periods
# ======================================================================
@app.route("/arc/associations/<aid>/blackouts", methods=["POST"], strict_slashes=False)
def create_blackout(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    assoc = get_association(aid)
    vals = validate_body({
        "start_date": (True, v_date("start_date")),
        "end_date": (True, v_date("end_date")),
        "reason": (False, v_string("reason")),
    })
    if vals["end_date"] < vals["start_date"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_date must be on or after start_date")
    rec = new_record({
        "association_id": assoc["id"],
        "start_date": vals["start_date"],
        "end_date": vals["end_date"],
        "reason": vals.get("reason", ""),
    })
    db["blackouts"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/associations/<aid>/blackouts", methods=["GET"], strict_slashes=False)
def list_blackouts(aid):
    authenticate()
    assoc = get_association(aid)
    return list_response([b for b in db["blackouts"].values() if b["association_id"] == assoc["id"]])


# ======================================================================
# Variances
# ======================================================================
@app.route("/arc/associations/<aid>/variances", methods=["POST"], strict_slashes=False)
def create_variance(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    assoc = get_association(aid)
    vals = validate_body({
        "application_id": (True, v_string("application_id")),
        "guideline_section": (True, v_string("guideline_section")),
        "deviation_description": (True, v_string("deviation_description")),
    })
    app_rec = get_application(vals["application_id"])
    if app_rec["status"] not in ("APPROVED_WITH_CONDITIONS", "DEEMED_APPROVED"):
        raise ApiError("ERR_PRECEDENT_NOT_APPROVED", 422,
                       "Variance must reference an approved application")
    rec = new_record({
        "association_id": assoc["id"],
        "application_id": app_rec["id"],
        "guideline_section": vals["guideline_section"],
        "deviation_description": vals["deviation_description"],
        "recorded_at": fmt_ts(logical_now()),
    })
    db["variances"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/associations/<aid>/variances", methods=["GET"], strict_slashes=False)
def list_variances(aid):
    authenticate()
    assoc = get_association(aid)
    recs = [v for v in db["variances"].values() if v["association_id"] == assoc["id"]]
    section = request.args.get("guideline_section")
    if section is not None:
        recs = [v for v in recs if v["guideline_section"] == section]
    return list_response(recs)


@app.route("/arc/applications/<aid>/variances", methods=["GET"], strict_slashes=False)
def list_application_variances(aid):
    authenticate()
    app_rec = get_application(aid)
    return list_response([v for v in db["variances"].values() if v["application_id"] == app_rec["id"]])


# ======================================================================
# Applications
# ======================================================================
PROJECT_TYPES = {"ADDITION", "FENCE", "PAINT", "ROOF", "SOLAR", "OTHER"}
APPLICATION_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
    "APPROVED_WITH_CONDITIONS", "DENIED", "DEEMED_APPROVED",
    "UNDER_APPEAL", "APPEAL_DENIED",
}


@app.route("/arc/properties/<pid>/applications", methods=["POST"], strict_slashes=False)
def create_application(pid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    prop = get_property(pid)
    vals = validate_body({
        "owner_id": (True, v_string("owner_id")),
        "project_type": (True, v_enum("project_type", PROJECT_TYPES)),
        "guideline_section": (True, v_string("guideline_section")),
        "description": (True, v_string("description")),
        "requested_window_start": (True, v_date("requested_window_start")),
        "requested_window_end": (True, v_date("requested_window_end")),
    })
    if vals["requested_window_end"] <= vals["requested_window_start"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "requested_window_end must be later than requested_window_start")
    owner = get_owner(vals["owner_id"])
    if vals["owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Applicant owner_id must equal X-User-ID")
    assoc = association_of_property(prop)
    wlen = (date.fromisoformat(vals["requested_window_end"])
            - date.fromisoformat(vals["requested_window_start"])).days
    if wlen > assoc["max_window_days"]:
        raise ApiError("ERR_WINDOW_TOO_LONG", 422,
                       "Requested window exceeds max_window_days")
    rec = new_record({
        "property_id": prop["id"],
        "owner_id": owner["id"],
        "project_type": vals["project_type"],
        "guideline_section": vals["guideline_section"],
        "description": vals["description"],
        "requested_window_start": vals["requested_window_start"],
        "requested_window_end": vals["requested_window_end"],
        "status": "DRAFT",
        "submitted_at": None,
        "review_started_at": None,
        "applicant_hold_days": 0,
        "decision_outcome": "NONE",
        "decision_reason": "",
        "conditions": [],
        "decided_at": None,
        "_revision_date": None,
    })
    db["applications"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/applications/<aid>", methods=["GET"], strict_slashes=False)
def read_application(aid):
    authenticate()
    return respond_object(pub(get_application(aid)))


@app.route("/arc/properties/<pid>/applications", methods=["GET"], strict_slashes=False)
def list_property_applications(pid):
    authenticate()
    prop = get_property(pid)
    recs = [a for a in db["applications"].values() if a["property_id"] == prop["id"]]
    status = enum_filter("status", APPLICATION_STATUSES)
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    return list_response(recs)


# ======================================================================
# Attachments
# ======================================================================
ATTACHMENT_KINDS = {"DRAWING", "MATERIAL_SAMPLE"}


@app.route("/arc/applications/<aid>/attachments", methods=["POST"], strict_slashes=False)
def create_attachment(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    app_rec = get_application(aid)
    vals = validate_body({
        "kind": (True, v_enum("kind", ATTACHMENT_KINDS)),
        "label": (True, v_string("label")),
        "uri": (True, v_string("uri")),
    })
    if app_rec["owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Homeowner does not own this application")
    if app_rec["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Attachments are accepted only while DRAFT or REVISION_REQUESTED")
    rec = new_record({
        "application_id": app_rec["id"],
        "kind": vals["kind"],
        "label": vals["label"],
        "uri": vals["uri"],
    })
    db["attachments"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/applications/<aid>/attachments", methods=["GET"], strict_slashes=False)
def list_attachments(aid):
    authenticate()
    app_rec = get_application(aid)
    recs = [a for a in db["attachments"].values() if a["application_id"] == app_rec["id"]]
    kind = enum_filter("kind", ATTACHMENT_KINDS)
    if kind is not None:
        recs = [a for a in recs if a["kind"] == kind]
    return list_response(recs)


# ======================================================================
# Application lifecycle actions
# ======================================================================
@app.route("/arc/applications/<aid>/submit", methods=["POST"], strict_slashes=False)
def submit_application(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    app_rec = get_application(aid)
    validate_body({})
    if app_rec["owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Homeowner does not own this application")
    if app_rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT application can be submitted")
    prop = property_of_application(app_rec)
    if prop["compliance_posture"] == "LIENED":
        raise ApiError("ERR_PROPERTY_LIENED", 409,
                       "Submission blocked: property posture is LIENED")
    kinds = {a["kind"] for a in db["attachments"].values() if a["application_id"] == app_rec["id"]}
    if "DRAWING" not in kinds or "MATERIAL_SAMPLE" not in kinds:
        raise ApiError("ERR_INCOMPLETE_SUBMISSION", 422,
                       "Application requires at least one DRAWING and one MATERIAL_SAMPLE attachment")
    app_rec["status"] = "SUBMITTED"
    if app_rec["submitted_at"] is None:
        app_rec["submitted_at"] = fmt_ts(logical_now())
    touch(app_rec)
    return respond_object(pub(app_rec))


@app.route("/arc/applications/<aid>/start-review", methods=["POST"], strict_slashes=False)
def start_review(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    app_rec = get_application(aid)
    validate_body({})
    if app_rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SUBMITTED application can enter review")
    app_rec["status"] = "UNDER_REVIEW"
    app_rec["review_started_at"] = fmt_ts(logical_now())
    touch(app_rec)
    return respond_object(pub(app_rec))


@app.route("/arc/applications/<aid>/request-revision", methods=["POST"], strict_slashes=False)
def request_revision(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_COMMITTEE})
    app_rec = get_application(aid)
    validate_body({"revision_notes": (True, v_string("revision_notes"))})
    if app_rec["owner_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Committee member is the applicant of this application")
    if app_rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Revisions can be requested only while UNDER_REVIEW")
    app_rec["status"] = "REVISION_REQUESTED"
    app_rec["_revision_date"] = logical_today()
    touch(app_rec)
    return respond_object(pub(app_rec))


@app.route("/arc/applications/<aid>/resubmit", methods=["POST"], strict_slashes=False)
def resubmit_application(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    app_rec = get_application(aid)
    validate_body({})
    if app_rec["owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Only the applicant may resubmit")
    if app_rec["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REVISION_REQUESTED application can be resubmitted")
    if app_rec["_revision_date"] is not None:
        hold = (logical_today() - app_rec["_revision_date"]).days
        if hold > 0:
            app_rec["applicant_hold_days"] += hold
    app_rec["_revision_date"] = None
    app_rec["status"] = "UNDER_REVIEW"
    touch(app_rec)
    return respond_object(pub(app_rec))


# ======================================================================
# Committee votes
# ======================================================================
BALLOTS = {"APPROVE", "DENY", "ABSTAIN"}


@app.route("/arc/applications/<aid>/votes", methods=["POST"], strict_slashes=False)
def cast_vote(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_COMMITTEE})
    app_rec = get_application(aid)
    vals = validate_body({"ballot": (True, v_enum("ballot", BALLOTS))})
    if app_rec["owner_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Committee member is the applicant of this application")
    if app_rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Ballots are accepted only while UNDER_REVIEW")
    existing = None
    for v in db["votes"].values():
        if v["application_id"] == app_rec["id"] and v["voter_owner_id"] == uid:
            existing = v
            break
    if existing is not None:
        existing["ballot"] = vals["ballot"]
        existing["recast_count"] += 1
        touch(existing)
        return respond_object(pub(existing), 201)
    rec = new_record({
        "application_id": app_rec["id"],
        "voter_owner_id": uid,
        "ballot": vals["ballot"],
        "cast_at": fmt_ts(logical_now()),
        "recast_count": 0,
    })
    db["votes"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/applications/<aid>/votes", methods=["GET"], strict_slashes=False)
def list_votes(aid):
    authenticate()
    app_rec = get_application(aid)
    return list_response([v for v in db["votes"].values() if v["application_id"] == app_rec["id"]])


# ======================================================================
# Decision
# ======================================================================
@app.route("/arc/applications/<aid>/decide", methods=["POST"], strict_slashes=False)
def decide_application(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    app_rec = get_application(aid)
    vals = validate_body({
        "conditions": (False, v_str_list("conditions")),
        "denial_reason": (False, v_string("denial_reason")),
    })
    if app_rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an UNDER_REVIEW application can be decided")
    prop = property_of_application(app_rec)
    assoc = association_of_property(prop)
    a = d = x = 0
    for v in db["votes"].values():
        if v["application_id"] != app_rec["id"]:
            continue
        if v["ballot"] == "APPROVE":
            a += 1
        elif v["ballot"] == "DENY":
            d += 1
        elif v["ballot"] == "ABSTAIN":
            x += 1
    if assoc["supermajority_required"]:
        approved = (a + d > 0) and (3 * a >= 2 * (a + d))
    else:
        approved = a > d
    if approved:
        check_window_conflicts(
            assoc["id"], prop["id"],
            date.fromisoformat(app_rec["requested_window_start"]),
            date.fromisoformat(app_rec["requested_window_end"]),
        )
    if (a + d + x) < assoc["quorum_min"]:
        raise ApiError("ERR_QUORUM_NOT_MET", 422, "Ballots cast are below quorum_min")
    app_rec["decided_at"] = fmt_ts(logical_now())
    if approved:
        app_rec["status"] = "APPROVED_WITH_CONDITIONS"
        app_rec["decision_outcome"] = "APPROVED"
        app_rec["conditions"] = vals.get("conditions", [])
        touch(app_rec)
        create_permit(app_rec)
    else:
        app_rec["status"] = "DENIED"
        app_rec["decision_outcome"] = "DENIED"
        app_rec["decision_reason"] = vals.get("denial_reason", "")
        touch(app_rec)
    return respond_object(pub(app_rec))


@app.route("/arc/applications/<aid>/conditions", methods=["POST"], strict_slashes=False)
def amend_conditions(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_COMMITTEE})
    app_rec = get_application(aid)
    vals = validate_body({
        "conditions": (True, v_str_list("conditions")),
        "expected_application_version": (True, v_int("expected_application_version")),
    })
    if app_rec["owner_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Committee member is the applicant of this application")
    if app_rec["status"] != "APPROVED_WITH_CONDITIONS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Conditions can be amended only while APPROVED_WITH_CONDITIONS")
    if vals["expected_application_version"] != app_rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_application_version does not match the current version")
    app_rec["conditions"] = vals["conditions"]
    touch(app_rec)
    return respond_object(pub(app_rec))


# ======================================================================
# Appeals
# ======================================================================
@app.route("/arc/applications/<aid>/appeals", methods=["POST"], strict_slashes=False)
def file_appeal(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    app_rec = get_application(aid)
    vals = validate_body({"grounds": (True, v_string("grounds"))})
    if app_rec["owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Only the applicant may appeal")
    if app_rec["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DENIED application can be appealed")
    prop = property_of_application(app_rec)
    assoc = association_of_property(prop)
    decided_date = parse_dt(app_rec["decided_at"]).date()
    if (logical_today() - decided_date).days > assoc["appeal_window_days"]:
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED", 422,
                       "Appeal filed after the appeal window closed")
    rec = new_record({
        "application_id": app_rec["id"],
        "grounds": vals["grounds"],
        "status": "PENDING",
        "board_note": "",
        "decided_by_owner_id": None,
        "filed_at": fmt_ts(logical_now()),
        "decided_at": None,
    })
    db["appeals"][rec["id"]] = rec
    app_rec["status"] = "UNDER_APPEAL"
    touch(app_rec)
    return respond_object(pub(rec), 201)


@app.route("/arc/applications/<aid>/appeals", methods=["GET"], strict_slashes=False)
def list_appeals(aid):
    authenticate()
    app_rec = get_application(aid)
    return list_response([a for a in db["appeals"].values() if a["application_id"] == app_rec["id"]])


@app.route("/arc/appeals/<aid>/decide", methods=["POST"], strict_slashes=False)
def decide_appeal(aid):
    uid, role = authenticate()
    require_role(role, {ROLE_BOARD})
    appeal = get_appeal(aid)
    vals = validate_body({
        "outcome": (True, v_enum("outcome", {"UPHELD", "OVERRULED"})),
        "board_note": (False, v_string("board_note")),
    })
    app_rec = get_application(appeal["application_id"])
    if app_rec["owner_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Board member is the applicant of the appealed application")
    for v in db["votes"].values():
        if v["application_id"] == app_rec["id"] and v["voter_owner_id"] == uid:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                           "Board member cast a committee vote on the appealed application")
    if appeal["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PENDING appeal can be decided")
    prop = property_of_application(app_rec)
    assoc = association_of_property(prop)
    if vals["outcome"] == "UPHELD":
        check_window_conflicts(
            assoc["id"], prop["id"],
            date.fromisoformat(app_rec["requested_window_start"]),
            date.fromisoformat(app_rec["requested_window_end"]),
        )
    appeal["status"] = vals["outcome"]
    appeal["board_note"] = vals.get("board_note", "")
    appeal["decided_by_owner_id"] = uid
    appeal["decided_at"] = fmt_ts(logical_now())
    touch(appeal)
    if vals["outcome"] == "UPHELD":
        app_rec["status"] = "APPROVED_WITH_CONDITIONS"
        app_rec["decision_outcome"] = "APPROVED"
        app_rec["decided_at"] = fmt_ts(logical_now())
        touch(app_rec)
        create_permit(app_rec)
    else:
        app_rec["status"] = "APPEAL_DENIED"
        touch(app_rec)
    return respond_object(pub(appeal))


# ======================================================================
# Permits
# ======================================================================
@app.route("/arc/permits/<pid>", methods=["GET"], strict_slashes=False)
def read_permit(pid):
    authenticate()
    return respond_object(pub(get_permit(pid)))


@app.route("/arc/applications/<aid>/permits", methods=["GET"], strict_slashes=False)
def list_application_permits(aid):
    authenticate()
    app_rec = get_application(aid)
    return list_response([p for p in db["permits"].values() if p["application_id"] == app_rec["id"]])


@app.route("/arc/permits/<pid>/contractor-change", methods=["POST"], strict_slashes=False)
def contractor_change(pid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    permit = get_permit(pid)
    vals = validate_body({
        "contractor_name": (True, v_string("contractor_name")),
        "contractor_license": (True, v_string("contractor_license")),
        "expected_permit_version": (True, v_int("expected_permit_version")),
    })
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contractor can be changed only while ACTIVE")
    if vals["expected_permit_version"] != permit["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_permit_version does not match the current version")
    permit["contractor_name"] = vals["contractor_name"]
    permit["contractor_license"] = vals["contractor_license"]
    touch(permit)
    return respond_object(pub(permit))


@app.route("/arc/permits/<pid>/extensions", methods=["POST"], strict_slashes=False)
def extend_permit(pid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER, ROLE_HOMEOWNER})
    permit = get_permit(pid)
    vals = validate_body({"new_window_end": (True, v_date("new_window_end"))})
    app_rec = get_application(permit["application_id"])
    prop = property_of_application(app_rec)
    assoc = association_of_property(prop)
    if role == ROLE_HOMEOWNER and app_rec["owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Homeowner does not own the permit's application")
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE permit can be extended")
    start = date.fromisoformat(permit["window_start"])
    current_end = date.fromisoformat(permit["window_end"])
    new_end = date.fromisoformat(vals["new_window_end"])
    if new_end <= current_end:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "new_window_end must be later than the current window_end")
    check_window_conflicts(assoc["id"], prop["id"], start, new_end,
                           exclude_permit_id=permit["id"])
    if (new_end - start).days > assoc["max_window_days"]:
        raise ApiError("ERR_WINDOW_TOO_LONG", 422, "Extended window exceeds max_window_days")
    permit["window_end"] = vals["new_window_end"]
    touch(permit)
    return respond_object(pub(permit))


# ======================================================================
# Inspections
# ======================================================================
@app.route("/arc/permits/<pid>/request-inspection", methods=["POST"], strict_slashes=False)
def request_inspection(pid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    permit = get_permit(pid)
    validate_body({})
    app_rec = get_application(permit["application_id"])
    if app_rec["owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Caller must own the parent application")
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Inspections can be requested only while the permit is ACTIVE")
    attempt = sum(1 for i in db["inspections"].values() if i["permit_id"] == permit["id"]) + 1
    rec = new_record({
        "permit_id": permit["id"],
        "attempt_no": attempt,
        "status": "SCHEDULED",
        "result_notes": "",
        "scheduled_at": fmt_ts(logical_now()),
        "recorded_at": None,
    })
    db["inspections"][rec["id"]] = rec
    return respond_object(pub(rec), 201)


@app.route("/arc/permits/<pid>/inspections", methods=["GET"], strict_slashes=False)
def list_permit_inspections(pid):
    authenticate()
    permit = get_permit(pid)
    return list_response([i for i in db["inspections"].values() if i["permit_id"] == permit["id"]])


@app.route("/arc/inspections/<iid>", methods=["GET"], strict_slashes=False)
def read_inspection(iid):
    authenticate()
    return respond_object(pub(get_inspection(iid)))


@app.route("/arc/inspections/<iid>/record", methods=["POST"], strict_slashes=False)
def record_inspection(iid):
    uid, role = authenticate()
    require_role(role, {ROLE_INSPECTOR})
    insp = get_inspection(iid)
    vals = validate_body({
        "result": (True, v_enum("result", {"PASS", "FAIL"})),
        "result_notes": (False, v_string("result_notes")),
    })
    if insp["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SCHEDULED inspection can be recorded")
    insp["result_notes"] = vals.get("result_notes", "")
    insp["recorded_at"] = fmt_ts(logical_now())
    permit = get_permit(insp["permit_id"])
    app_rec = get_application(permit["application_id"])
    prop = property_of_application(app_rec)
    assoc = association_of_property(prop)
    if vals["result"] == "PASS":
        insp["status"] = "PASSED"
        touch(insp)
        if permit["status"] in ("ACTIVE", "EXPIRED"):
            was_expired = permit["status"] == "EXPIRED"
            permit["status"] = "COMPLETED"
            permit["completed_at"] = fmt_ts(logical_now())
            touch(permit)
            if was_expired:
                for v in db["violations"].values():
                    if (v["source_permit_id"] == permit["id"]
                            and v["status"] in ("OPEN", "ESCALATED")):
                        v["status"] = "REMEDIATED"
                        v["remediated_at"] = fmt_ts(logical_now())
                        touch(v)
                        f = fine_of_violation(v["id"])
                        if f is not None and f["status"] == "ACCRUING":
                            stop_fine(f)
                recompute_property(prop)
            recompute_property(prop)
    else:
        insp["status"] = "FAILED_REMEDIATION"
        touch(insp)
        create_violation(
            prop, assoc, "CONDITION_BREACH",
            insp["result_notes"] or "Inspection failed",
            application_id=app_rec["id"],
            source_inspection_id=insp["id"],
            source_permit_id=permit["id"],
        )
    return respond_object(pub(insp))


@app.route("/arc/inspections/<iid>/reschedule", methods=["POST"], strict_slashes=False)
def reschedule_inspection(iid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    insp = get_inspection(iid)
    validate_body({})
    if insp["status"] != "FAILED_REMEDIATION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a FAILED_REMEDIATION inspection can be rescheduled")
    gate_ok = False
    for v in db["violations"].values():
        if v["source_inspection_id"] == insp["id"]:
            gate_ok = (v["status"] == "REMEDIATED")
            break
    if not gate_ok:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The violation created by this inspection is not REMEDIATED")
    insp["status"] = "SCHEDULED"
    insp["attempt_no"] += 1
    insp["scheduled_at"] = fmt_ts(logical_now())
    insp["recorded_at"] = None
    touch(insp)
    return respond_object(pub(insp))


# ======================================================================
# Violations
# ======================================================================
VIOLATION_KINDS = {"UNAPPROVED_WORK", "CONDITION_BREACH", "INCOMPLETE_CONSTRUCTION"}
VIOLATION_STATUSES = {"OPEN", "ESCALATED", "REMEDIATED"}


@app.route("/arc/properties/<pid>/violations", methods=["POST"], strict_slashes=False)
def report_violation(pid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    prop = get_property(pid)
    vals = validate_body({
        "kind": (True, v_enum("kind", VIOLATION_KINDS)),
        "description": (True, v_string("description")),
        "application_id": (False, v_string("application_id")),
    })
    app_id = vals.get("application_id", "")
    if app_id:
        get_application(app_id)
    assoc = association_of_property(prop)
    viol, fine = create_violation(prop, assoc, vals["kind"], vals["description"],
                                  application_id=app_id)
    return respond_object(pub(viol), 201)


@app.route("/arc/violations/<vid>", methods=["GET"], strict_slashes=False)
def read_violation(vid):
    authenticate()
    return respond_object(pub(get_violation(vid)))


@app.route("/arc/properties/<pid>/violations", methods=["GET"], strict_slashes=False)
def list_property_violations(pid):
    authenticate()
    prop = get_property(pid)
    recs = [v for v in db["violations"].values() if v["property_id"] == prop["id"]]
    status = enum_filter("status", VIOLATION_STATUSES)
    if status is not None:
        recs = [v for v in recs if v["status"] == status]
    return list_response(recs)


@app.route("/arc/applications/<aid>/violations", methods=["GET"], strict_slashes=False)
def list_application_violations(aid):
    authenticate()
    app_rec = get_application(aid)
    return list_response([v for v in db["violations"].values() if v["application_id"] == app_rec["id"]])


@app.route("/arc/permits/<pid>/violations", methods=["GET"], strict_slashes=False)
def list_permit_violations(pid):
    authenticate()
    permit = get_permit(pid)
    return list_response([v for v in db["violations"].values() if v["source_permit_id"] == permit["id"]])


@app.route("/arc/inspections/<iid>/violations", methods=["GET"], strict_slashes=False)
def list_inspection_violations(iid):
    authenticate()
    insp = get_inspection(iid)
    return list_response([v for v in db["violations"].values() if v["source_inspection_id"] == insp["id"]])


@app.route("/arc/violations/<vid>/remediate", methods=["POST"], strict_slashes=False)
def remediate_violation(vid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    viol = get_violation(vid)
    validate_body({"remediation_note": (False, v_string("remediation_note"))})
    prop = get_property(viol["property_id"])
    if prop["primary_owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Only the property's primary owner may remediate this violation")
    if viol["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN or ESCALATED violation can be remediated")
    viol["status"] = "REMEDIATED"
    viol["remediated_at"] = fmt_ts(logical_now())
    touch(viol)
    fine = fine_of_violation(viol["id"])
    if fine is not None and fine["status"] == "ACCRUING":
        stop_fine(fine)
    recompute_property(prop)
    return respond_object(pub(viol))


# ======================================================================
# Fines
# ======================================================================
@app.route("/arc/violations/<vid>/fines", methods=["GET"], strict_slashes=False)
def list_violation_fines(vid):
    authenticate()
    viol = get_violation(vid)
    return list_response([f for f in db["fines"].values() if f["violation_id"] == viol["id"]])


@app.route("/arc/fines/<fid>/settle", methods=["POST"], strict_slashes=False)
def settle_fine(fid):
    uid, role = authenticate()
    require_role(role, {ROLE_HOMEOWNER})
    fine = get_fine(fid)
    vals = validate_body({"amount_cents": (True, v_int("amount_cents", minimum=0))})
    viol = get_violation(fine["violation_id"])
    prop = get_property(viol["property_id"])
    if prop["primary_owner_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Only the property's primary owner may settle this fine")
    if fine["status"] not in ("ACCRUING", "STOPPED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACCRUING or STOPPED fine can be settled")
    add, n = (0, 0)
    if fine["status"] == "ACCRUING":
        add, n = accrual_addition(fine, logical_today())
    prospective_outstanding = (fine["accrued_cents"] + add
                               - fine["settled_cents"] - fine["waived_cents"])
    if vals["amount_cents"] != prospective_outstanding:
        raise ApiError("ERR_SETTLEMENT_AMOUNT_MISMATCH", 422,
                       "amount_cents must equal the fine's outstanding_cents exactly")
    if n:
        accrue_fine_to(fine, logical_today(), touch_it=False)
    fine["settled_cents"] = vals["amount_cents"]
    fine["outstanding_cents"] = 0
    fine["status"] = "SETTLED"
    fine["settled_at"] = fmt_ts(logical_now())
    touch(fine)
    recompute_property(prop)
    return respond_object(pub(fine))


@app.route("/arc/fines/<fid>/waive", methods=["POST"], strict_slashes=False)
def waive_fine(fid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    fine = get_fine(fid)
    vals = validate_body({
        "amount_cents": (True, v_int("amount_cents", minimum=0)),
        "reason": (True, v_string("reason")),
    })
    if fine["status"] not in ("ACCRUING", "STOPPED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACCRUING or STOPPED fine can be waived")
    if vals["amount_cents"] > fine["outstanding_cents"]:
        raise ApiError("ERR_WAIVER_EXCEEDS_OUTSTANDING", 422,
                       "amount_cents exceeds the fine's outstanding_cents")
    fine["waived_cents"] += vals["amount_cents"]
    fine["outstanding_cents"] = fine["accrued_cents"] - fine["settled_cents"] - fine["waived_cents"]
    touch(fine)
    viol = get_violation(fine["violation_id"])
    prop = get_property(viol["property_id"])
    recompute_property(prop)
    return respond_object(pub(fine))


# ======================================================================
# Liens
# ======================================================================
@app.route("/arc/properties/<pid>/liens", methods=["GET"], strict_slashes=False)
def list_property_liens(pid):
    authenticate()
    prop = get_property(pid)
    return list_response([l for l in db["liens"].values() if l["property_id"] == prop["id"]])


@app.route("/arc/liens/<lid>/satisfy", methods=["POST"], strict_slashes=False)
def satisfy_lien(lid):
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    lien = get_lien(lid)
    validate_body({})
    if lien["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a FILED lien can be satisfied")
    prop = get_property(lien["property_id"])
    recompute_property(prop)
    if prop["outstanding_fine_balance_cents"] != 0:
        raise ApiError("ERR_LIEN_BALANCE_OUTSTANDING", 409,
                       "Property outstanding balance must be zero to satisfy the lien")
    lien["status"] = "SATISFIED"
    lien["satisfied_at"] = fmt_ts(logical_now())
    touch(lien)
    recompute_property(prop)
    return respond_object(pub(lien))


# ======================================================================
# Test-driving system endpoints
# ======================================================================
@app.route("/arc/_clock/set_current_utc", methods=["POST"], strict_slashes=False)
def set_clock():
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    vals = validate_body({"to_iso8601": (True, v_datetime("to_iso8601"))})
    _clock["now"] = vals["to_iso8601"]
    return respond_object({"current_utc": fmt_ts(_clock["now"])})


@app.route("/arc/_sweeps/daily", methods=["POST"], strict_slashes=False)
def run_daily_sweep():
    uid, role = authenticate()
    require_role(role, {ROLE_MANAGER})
    validate_body({})
    t = logical_today()
    counts = {
        "applications_deemed_approved": 0,
        "fines_accrued": 0,
        "violations_escalated": 0,
        "liens_filed": 0,
        "permits_expired": 0,
    }
    # (1) deemed approvals
    for app_rec in sorted_recs(db["applications"].values()):
        if app_rec["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            continue
        prop = property_of_application(app_rec)
        assoc = association_of_property(prop)
        submitted_date = parse_dt(app_rec["submitted_at"]).date()
        elapsed = (countable_days(submitted_date, t, assoc["counting_mode"])
                   - app_rec["applicant_hold_days"])
        if elapsed >= assoc["statutory_response_days"]:
            app_rec["status"] = "DEEMED_APPROVED"
            app_rec["decision_outcome"] = "APPROVED"
            app_rec["decided_at"] = fmt_ts(logical_now())
            touch(app_rec)
            create_permit(app_rec)
            counts["applications_deemed_approved"] += 1
    # (2) fine accrual
    for fine in sorted_recs(db["fines"].values()):
        if fine["status"] != "ACCRUING":
            continue
        if accrue_fine_to(fine, t):
            counts["fines_accrued"] += 1
            viol = db["violations"].get(fine["violation_id"])
            if viol is not None:
                prop = db["properties"].get(viol["property_id"])
                if prop is not None:
                    recompute_property(prop)
    # (3) violation escalation
    for viol in sorted_recs(db["violations"].values()):
        if viol["status"] != "OPEN":
            continue
        if t > date.fromisoformat(viol["remediation_deadline"]):
            viol["status"] = "ESCALATED"
            viol["escalated_at"] = fmt_ts(logical_now())
            touch(viol)
            counts["violations_escalated"] += 1
    # (4) lien auto-file
    for prop in sorted_recs(db["properties"].values()):
        assoc = association_of_property(prop)
        if any(l["property_id"] == prop["id"] and l["status"] == "FILED"
               for l in db["liens"].values()):
            continue
        recompute_property(prop)
        if prop["outstanding_fine_balance_cents"] < assoc["lien_threshold_cents"]:
            continue
        unpaid = []
        for v in db["violations"].values():
            if v["property_id"] != prop["id"]:
                continue
            f = fine_of_violation(v["id"])
            if f is not None and f["outstanding_cents"] > 0:
                unpaid.append(f)
        if not unpaid:
            continue
        oldest = min(parse_dt(f["started_at"]).date() for f in unpaid)
        if (t - oldest).days < assoc["lien_min_age_days"]:
            continue
        lien = new_record({
            "property_id": prop["id"],
            "amount_at_filing_cents": prop["outstanding_fine_balance_cents"],
            "filed_at": fmt_ts(logical_now()),
            "status": "FILED",
            "satisfied_at": None,
        })
        db["liens"][lien["id"]] = lien
        counts["liens_filed"] += 1
        recompute_property(prop)
    # (5) permit expiry
    for permit in sorted_recs(db["permits"].values()):
        if permit["status"] != "ACTIVE":
            continue
        if t <= date.fromisoformat(permit["window_end"]):
            continue
        if any(i["permit_id"] == permit["id"] and i["status"] == "PASSED"
               for i in db["inspections"].values()):
            continue
        permit["status"] = "EXPIRED"
        touch(permit)
        app_rec = db["applications"].get(permit["application_id"])
        if app_rec is not None:
            prop = property_of_application(app_rec)
            assoc = association_of_property(prop)
            create_violation(prop, assoc, "INCOMPLETE_CONSTRUCTION",
                             "Permit window expired with construction incomplete",
                             application_id=app_rec["id"],
                             source_permit_id=permit["id"])
        counts["permits_expired"] += 1
    return respond_object(counts)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
