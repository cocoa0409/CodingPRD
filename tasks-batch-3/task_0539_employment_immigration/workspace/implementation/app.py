"""Employment-Based Immigration (PERM/LCA & H-1B) API.

Single-file Flask implementation. In-memory storage only; the store starts
empty on every boot and nothing is seeded/persisted.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory data store (keyed by id). Starts EMPTY on every process boot.
# ---------------------------------------------------------------------------
DB = {
    "employers": {},
    "pwds": {},
    "perm_cases": {},
    "recruitment_steps": {},
    "lcas": {},
    "beneficiaries": {},
    "cap_programs": {},
    "registrations": {},
    "h1b_petitions": {},
    "i140_petitions": {},
}

# Logical clock: startup default is exactly 2026-05-01T00:00:00Z.
CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_SEQ = 0

ROLES = {"EmployerAgent", "DOLAnalyst", "USCISOfficer", "ComplianceAuditor"}

# Calculation constants
BASE_FILING_FEE_CENTS = 46000
FRAUD_FEE_CENTS = 50000
ACWIA_SMALL_CENTS = 75000
ACWIA_LARGE_CENTS = 150000
ACWIA_SIZE_THRESHOLD = 25
PL_SIZE_THRESHOLD = 50
PL_114_113_FEE_CENTS = 400000
RECRUITMENT_MIN_DAYS = 30
QUIET_PERIOD_DAYS = 30
PERM_VALIDITY_DAYS = 180
RFE_RESPONSE_DAYS = 87
PAF_DOC_WEIGHT = 25

WAGE_LEVELS = {"LEVEL_I", "LEVEL_II", "LEVEL_III", "LEVEL_IV"}
WAGE_SOURCES = {"OES", "EMPLOYER_SURVEY"}
STEP_TYPES = {"JOB_ORDER", "NEWSPAPER_AD", "PROFESSIONAL_JOURNAL",
              "EMPLOYER_WEBSITE", "JOB_FAIR"}
I140_CATEGORIES = {"EB1", "EB2", "EB3"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class AppError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise AppError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _fmt(dt):
    """Format an aware UTC datetime as ISO-8601 with 3 fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Canonical string of the logical clock (used for system timestamps)."""
    return _fmt(CLOCK)


def clock_iso(dt=None):
    """Format a clock-derived business instant (filed_date, priority_date,
    quiet_period_end, rfe_due_date, current_utc, ...).

    These fields carry logical-clock instants, which the PRD renders without
    fractional digits (e.g. the clock starts at `2026-05-01T00:00:00Z`). To
    stay consistent with that representation and with client-supplied dates
    (which are echoed verbatim), whole-second instants serialize without a
    fractional part; sub-second instants fall back to 3 fractional digits.
    (Only created_at/updated_at/api_request_timestamp keep the mandated
    3-digit fractional form via _fmt, per PRD §2.4.)"""
    dt = (dt if dt is not None else CLOCK).astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def real_now_iso():
    return _fmt(datetime.now(timezone.utc))


def parse_dt(s):
    if s is None:
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


def make(_type, **fields):
    d = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_type": _type,
        "_seq": next_seq(),
    }
    d.update(fields)
    return d


def bump(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {"api_request_id": gen_req_id(),
            "api_request_timestamp": real_now_iso()}


def ok(data, status=200, response_type="object", list_meta=None):
    meta = base_meta()
    if list_meta:
        meta.update(list_meta)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


@app.errorhandler(AppError)
def handle_app_error(e):
    body = {"meta": base_meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(HTTPException)
def handle_http_error(e):
    error_id = "ERR_NOT_FOUND" if e.code == 404 else "ERR_VALIDATION"
    if e.code == 405:
        error_id = "ERR_NOT_FOUND"
    body = {"meta": base_meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": e.name}}
    return jsonify(body), e.code


@app.errorhandler(Exception)
def handle_unexpected(e):
    body = {"meta": base_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": str(e)}}
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth / RBAC helpers
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "missing or unknown auth headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


def check_owner(role, user_id, employer_id):
    """EmployerAgent may only act on resources whose employer_id == its id."""
    if role == "EmployerAgent" and employer_id != user_id:
        err("ERR_UNAUTHORIZED", 403, "employer ownership check failed")


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def bad(msg="invalid body"):
    err("ERR_VALIDATION", 400, msg)


def req_str(body, f):
    v = body.get(f)
    if not isinstance(v, str) or v == "":
        bad(f"{f} is required")
    return v


def req_int(body, f, mn=None, mx=None):
    v = body.get(f)
    if isinstance(v, bool) or not isinstance(v, int):
        bad(f"{f} must be an integer")
    if mn is not None and v < mn:
        bad(f"{f} must be >= {mn}")
    if mx is not None and v > mx:
        bad(f"{f} must be <= {mx}")
    return v


def opt_int(body, f, default, mn=None, mx=None):
    if f not in body or body[f] is None:
        return default
    return req_int(body, f, mn, mx)


def opt_bool(body, f, default=False):
    if f not in body or body[f] is None:
        return default
    v = body[f]
    if not isinstance(v, bool):
        bad(f"{f} must be a boolean")
    return v


def req_enum(body, f, allowed):
    v = req_str(body, f)
    if v not in allowed:
        bad(f"{f} is not a valid value")
    return v


def req_dt(body, f):
    v = body.get(f)
    if not isinstance(v, str) or v == "":
        bad(f"{f} is required")
    try:
        parse_dt(v)
    except Exception:
        bad(f"{f} is not a valid datetime")
    return v


def resolve(store_key, value):
    """Existence resolution: if value present & non-null but unresolved -> 404."""
    if value is None:
        return None
    obj = DB[store_key].get(value)
    if obj is None:
        err("ERR_NOT_FOUND", 404, f"referenced resource not found: {value}")
    return obj


def load_or_404(store_key, rid):
    obj = DB[store_key].get(rid)
    if obj is None:
        err("ERR_NOT_FOUND", 404, "resource not found")
    return obj


def round_half_up(numerator):
    return int((Decimal(numerator) / Decimal(40)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Computed-field / serialization
# ---------------------------------------------------------------------------
def lca_required_wage(lca):
    if lca["status"] == "DRAFT":
        return max(lca["prevailing_wage_cents"], lca["offered_wage_cents"])
    return lca["_locked_required"]


def lca_aggregate(lca):
    total = 0
    for area in lca["worksite_areas"]:
        area_wage = lca["area_wage_map"][area]
        total += round_half_up(area_wage * lca["hours_per_week"])
    return total


def lca_paf_score(lca):
    score = 0
    for flag in ("has_wage_rate", "has_prevailing_wage_doc",
                 "has_notice_of_filing", "has_actual_wage_memo"):
        if lca[flag]:
            score += PAF_DOC_WEIGHT
    return score


def beneficiary_status_code(ben):
    valid_until = ben["status_valid_until"]
    if valid_until is None:
        return "NONE"
    if CLOCK < parse_dt(valid_until):
        return "H1B_ACTIVE"
    return "H1B_EXPIRED"


def cap_available(prog):
    return prog["selection_quota"] - prog["selected_count"]


def serialize(d):
    out = {k: v for k, v in d.items() if not k.startswith("_")}
    t = d["_type"]
    if t == "lca":
        out["required_wage_cents"] = lca_required_wage(d)
        out["aggregate_wage_obligation_cents"] = lca_aggregate(d)
        out["paf_completeness_score"] = lca_paf_score(d)
    elif t == "beneficiary":
        out["current_status_code"] = beneficiary_status_code(d)
    elif t == "cap_program":
        out["available_seats"] = cap_available(d)
    return out


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10)) if args.get("limit") is not None else 10
    except (TypeError, ValueError):
        bad("limit must be an integer")
    try:
        offset = int(args.get("offset", 0)) if args.get("offset") is not None else 0
    except (TypeError, ValueError):
        bad("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda d: (parse_dt(d["created_at"]), d["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    meta = {"limit": limit, "offset": offset,
            "total_count": total, "has_more": has_more}
    return [serialize(d) for d in page], meta


def list_response(items):
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


# ---------------------------------------------------------------------------
# Beneficiary recompute (derived status fields)
# ---------------------------------------------------------------------------
def recompute_beneficiary(bid):
    ben = DB["beneficiaries"].get(bid)
    if ben is None:
        return
    approved_h1b = [p for p in DB["h1b_petitions"].values()
                    if p["beneficiary_id"] == bid and p["status"] == "APPROVED"]
    if approved_h1b:
        best = max(approved_h1b, key=lambda p: parse_dt(p["employment_end"]))
        new_valid = best["employment_end"]
    else:
        new_valid = None
    approved_i140 = [p for p in DB["i140_petitions"].values()
                     if p["beneficiary_id"] == bid and p["status"] == "APPROVED"]
    if approved_i140:
        best_pd = min(approved_i140,
                      key=lambda p: (parse_dt(p["priority_date"]), p["_seq"]))
        new_pd = best_pd["priority_date"]
    else:
        new_pd = None
    changed = (new_valid != ben["status_valid_until"]) or (new_pd != ben["priority_date"])
    ben["status_valid_until"] = new_valid
    ben["priority_date"] = new_pd
    if changed:
        bump(ben)


def revert_perm_to_draft(pc):
    """System revert on PWD supersede. Only meaningful for RECRUITING/QUIET_PERIOD."""
    if pc["status"] not in ("RECRUITING", "QUIET_PERIOD"):
        return
    for step in DB["recruitment_steps"].values():
        if step["perm_case_id"] == pc["id"] and step["status"] == "ACTIVE":
            step["status"] = "VOID"
            bump(step)
    if pc["status"] == "RECRUITING":
        pc["recruitment_start"] = None
    else:  # QUIET_PERIOD
        pc["recruitment_start"] = None
        pc["recruitment_end"] = None
        pc["quiet_period_end"] = None
    pc["status"] = "DRAFT"
    bump(pc)


# ===========================================================================
# EMPLOYERS
# ===========================================================================
@app.route("/employers", methods=["POST"])
def create_employer():
    _uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    fein = req_str(body, "fein")
    legal_name = req_str(body, "legal_name")
    employee_count = req_int(body, "employee_count", mn=1)
    h1b_dependent = opt_bool(body, "h1b_dependent", False)
    emp = make("employer", fein=fein, legal_name=legal_name,
               employee_count=employee_count, h1b_dependent=h1b_dependent,
               total_wage_obligation_cents=0)
    DB["employers"][emp["id"]] = emp
    return ok(serialize(emp), 201)


@app.route("/employers/<rid>", methods=["GET"])
def get_employer(rid):
    authenticate()
    return ok(serialize(load_or_404("employers", rid)))


# ===========================================================================
# PREVAILING WAGE DETERMINATIONS
# ===========================================================================
@app.route("/prevailing-wage-determinations", methods=["POST"])
def create_pwd():
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    employer_id = body.get("employer_id")
    if employer_id is not None:
        check_owner(role, uid, employer_id)
    resolve("employers", employer_id)          # existence (left-to-right)
    employer_id = req_str(body, "employer_id")
    soc_code = req_str(body, "soc_code")
    job_title = req_str(body, "job_title")
    area_code = req_str(body, "area_code")
    wage_level = req_enum(body, "wage_level", WAGE_LEVELS)
    wage_source = req_enum(body, "wage_source", WAGE_SOURCES)
    oes_wage_cents = req_int(body, "oes_wage_cents", mn=0)
    survey_wage_cents = None
    if wage_source == "EMPLOYER_SURVEY":
        survey_wage_cents = req_int(body, "survey_wage_cents", mn=0)
    elif body.get("survey_wage_cents") is not None:
        survey_wage_cents = req_int(body, "survey_wage_cents", mn=0)
    validity_start = req_dt(body, "validity_start")
    validity_end = req_dt(body, "validity_end")
    if parse_dt(validity_end) <= parse_dt(validity_start):
        bad("validity_end must be after validity_start")
    pwd = make("pwd", employer_id=employer_id, soc_code=soc_code,
               job_title=job_title, area_code=area_code, wage_level=wage_level,
               wage_source=wage_source, oes_wage_cents=oes_wage_cents,
               survey_wage_cents=survey_wage_cents, prevailing_wage_cents=None,
               validity_start=validity_start, validity_end=validity_end,
               status="PENDING")
    DB["pwds"][pwd["id"]] = pwd
    return ok(serialize(pwd), 201)


@app.route("/prevailing-wage-determinations/<rid>", methods=["GET"])
def get_pwd(rid):
    authenticate()
    return ok(serialize(load_or_404("pwds", rid)))


@app.route("/prevailing-wage-determinations", methods=["GET"])
def list_pwd():
    authenticate()
    items = list(DB["pwds"].values())
    emp = request.args.get("employer_id")
    st = request.args.get("status")
    if emp is not None:
        items = [d for d in items if d["employer_id"] == emp]
    if st is not None:
        items = [d for d in items if d["status"] == st]
    return list_response(items)


@app.route("/prevailing-wage-determinations/<rid>/transitions", methods=["POST"])
def transition_pwd(rid):
    _uid, role = authenticate()
    require_role(role, {"DOLAnalyst"})
    body = get_body()
    to_status = body.get("to_status")
    pwd = load_or_404("pwds", rid)                       # existence
    # body well-formedness (priority 4)
    if not isinstance(to_status, str) or to_status == "":
        bad("to_status is required")
    if "expected_employer_version" not in body or body["expected_employer_version"] is None:
        bad("expected_employer_version is required")
    expected = body["expected_employer_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        bad("expected_employer_version must be an integer")
    if pwd["wage_source"] == "EMPLOYER_SURVEY" and pwd["survey_wage_cents"] is None:
        bad("survey_wage_cents required for EMPLOYER_SURVEY")
    employer = DB["employers"].get(pwd["employer_id"])
    # OCC (priority 6)
    if employer is None or expected != employer["version"]:
        err("ERR_STALE_VERSION", 412, "expected_employer_version mismatch")
    # state legality (priority 7). Only ISSUED is an API-driven target.
    if to_status != "ISSUED" or pwd["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "transition not defined from current state")
    # execute issuance
    if pwd["wage_source"] == "OES":
        pwd["prevailing_wage_cents"] = pwd["oes_wage_cents"]
    else:
        pwd["prevailing_wage_cents"] = pwd["survey_wage_cents"]
    # supersede competing ISSUED PWDs (same employer, soc_code, area_code)
    for other in list(DB["pwds"].values()):
        if (other["id"] != pwd["id"]
                and other["employer_id"] == pwd["employer_id"]
                and other["soc_code"] == pwd["soc_code"]
                and other["area_code"] == pwd["area_code"]
                and other["status"] == "ISSUED"):
            other["status"] = "SUPERSEDED"
            bump(other)
            for pc in list(DB["perm_cases"].values()):
                if pc["pwd_id"] == other["id"] and pc["status"] in ("DRAFT", "RECRUITING", "QUIET_PERIOD"):
                    revert_perm_to_draft(pc)
    pwd["status"] = "ISSUED"
    bump(pwd)
    bump(employer)  # increments Employer.version by 1
    return ok(serialize(pwd))


# ===========================================================================
# PERM CASES
# ===========================================================================
@app.route("/perm-cases", methods=["POST"])
def create_perm_case():
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    employer_id = body.get("employer_id")
    if employer_id is not None:
        check_owner(role, uid, employer_id)
    resolve("employers", employer_id)
    resolve("pwds", body.get("pwd_id"))
    employer_id = req_str(body, "employer_id")
    pwd_id = req_str(body, "pwd_id")
    job_title = req_str(body, "job_title")
    offered = req_int(body, "offered_wage_cents", mn=0)
    pc = make("perm_case", employer_id=employer_id, pwd_id=pwd_id,
              job_title=job_title, offered_wage_cents=offered,
              recruitment_start=None, recruitment_end=None,
              quiet_period_end=None, filed_date=None, priority_date=None,
              status="DRAFT")
    DB["perm_cases"][pc["id"]] = pc
    return ok(serialize(pc), 201)


@app.route("/perm-cases/<rid>", methods=["GET"])
def get_perm_case(rid):
    authenticate()
    return ok(serialize(load_or_404("perm_cases", rid)))


@app.route("/perm-cases", methods=["GET"])
def list_perm_cases():
    authenticate()
    items = list(DB["perm_cases"].values())
    for key in ("employer_id", "pwd_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    return list_response(items)


PERM_TARGET_ROLE = {
    "RECRUITING": "EmployerAgent", "QUIET_PERIOD": "EmployerAgent",
    "FILED": "EmployerAgent", "AUDIT": "DOLAnalyst",
    "CERTIFIED": "DOLAnalyst", "DENIED": "DOLAnalyst",
}


@app.route("/perm-cases/<rid>/transitions", methods=["POST"])
def transition_perm_case(rid):
    uid, role = authenticate()
    require_role(role, set(PERM_TARGET_ROLE.values()))
    body = get_body()
    to_status = body.get("to_status")
    if isinstance(to_status, str) and to_status in PERM_TARGET_ROLE \
            and role != PERM_TARGET_ROLE[to_status]:
        err("ERR_UNAUTHORIZED", 403, "role not permitted for this transition")
    pc = load_or_404("perm_cases", rid)
    check_owner(role, uid, pc["employer_id"])
    if not isinstance(to_status, str) or to_status == "":
        bad("to_status is required")

    if to_status == "RECRUITING":
        if pc["status"] != "DRAFT":
            err("ERR_INVALID_STATE", 409, "not in DRAFT")
        pwd = DB["pwds"].get(pc["pwd_id"])
        if pwd is None or pwd["status"] != "ISSUED":
            err("ERR_PWD_NOT_ISSUED", 409, "referenced PWD not ISSUED")
        if pc["offered_wage_cents"] < pwd["prevailing_wage_cents"]:
            err("ERR_WAGE_BELOW_PREVAILING", 422, "offered wage below prevailing")
        pc["recruitment_start"] = clock_iso()
        pc["status"] = "RECRUITING"
        bump(pc)
    elif to_status == "QUIET_PERIOD":
        if pc["status"] != "RECRUITING":
            err("ERR_INVALID_STATE", 409, "not in RECRUITING")
        if (CLOCK - parse_dt(pc["recruitment_start"])) < timedelta(days=RECRUITMENT_MIN_DAYS):
            err("ERR_RECRUITMENT_TOO_SHORT", 422, "recruitment ran too short")
        active = [s for s in DB["recruitment_steps"].values()
                  if s["perm_case_id"] == pc["id"] and s["status"] == "ACTIVE"]
        job_orders = sum(1 for s in active if s["step_type"] == "JOB_ORDER")
        news = sum(1 for s in active if s["step_type"] == "NEWSPAPER_AD")
        if not (job_orders >= 1 and news >= 2):
            err("ERR_RECRUITMENT_INCOMPLETE", 422, "recruitment record incomplete")
        pc["recruitment_end"] = clock_iso()
        pc["quiet_period_end"] = clock_iso(CLOCK + timedelta(days=QUIET_PERIOD_DAYS))
        pc["status"] = "QUIET_PERIOD"
        bump(pc)
    elif to_status == "FILED":
        if pc["status"] == "QUIET_PERIOD":
            if CLOCK < parse_dt(pc["quiet_period_end"]):
                err("ERR_QUIET_PERIOD_NOT_ELAPSED", 422, "quiet period not elapsed")
            if CLOCK > parse_dt(pc["recruitment_start"]) + timedelta(days=PERM_VALIDITY_DAYS):
                err("ERR_PERM_VALIDITY_EXPIRED", 422, "PERM validity window expired")
            pc["filed_date"] = clock_iso()
            pc["priority_date"] = pc["filed_date"]
            pc["status"] = "FILED"
            bump(pc)
        elif pc["status"] == "AUDIT":
            pc["status"] = "FILED"
            bump(pc)
        else:
            err("ERR_INVALID_STATE", 409, "cannot file from current state")
    elif to_status == "AUDIT":
        if pc["status"] != "FILED":
            err("ERR_INVALID_STATE", 409, "not in FILED")
        pc["status"] = "AUDIT"
        bump(pc)
    elif to_status == "CERTIFIED":
        if pc["status"] != "FILED":
            err("ERR_INVALID_STATE", 409, "not in FILED")
        pc["status"] = "CERTIFIED"
        bump(pc)
    elif to_status == "DENIED":
        if pc["status"] not in ("FILED", "AUDIT"):
            err("ERR_INVALID_STATE", 409, "not in FILED/AUDIT")
        pc["status"] = "DENIED"
        bump(pc)
        for i in list(DB["i140_petitions"].values()):
            if i["perm_case_id"] == pc["id"] and i["status"] in ("DRAFT", "SUBMITTED"):
                prev = i["status"]
                i["status"] = "DENIED"
                bump(i)
                if prev == "SUBMITTED":
                    recompute_beneficiary(i["beneficiary_id"])
    else:
        err("ERR_INVALID_STATE", 409, "unknown target state")
    return ok(serialize(pc))


# ===========================================================================
# RECRUITMENT STEPS
# ===========================================================================
@app.route("/recruitment-steps", methods=["POST"])
def create_recruitment_step():
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    pc = resolve("perm_cases", body.get("perm_case_id"))
    if pc is not None:
        check_owner(role, uid, pc["employer_id"])
    perm_case_id = req_str(body, "perm_case_id")
    step_type = req_enum(body, "step_type", STEP_TYPES)
    start_date = req_dt(body, "start_date")
    end_date = req_dt(body, "end_date")
    if parse_dt(end_date) < parse_dt(start_date):
        bad("end_date must be >= start_date")
    # closed-interval overlap with same-type ACTIVE steps on this case
    ns, ne = parse_dt(start_date), parse_dt(end_date)
    for s in DB["recruitment_steps"].values():
        if (s["perm_case_id"] == perm_case_id and s["status"] == "ACTIVE"
                and s["step_type"] == step_type):
            es, ee = parse_dt(s["start_date"]), parse_dt(s["end_date"])
            if ns <= ee and es <= ne:  # closed intervals: touching conflicts
                err("ERR_RECRUITMENT_STEP_OVERLAP", 409, "recruitment step overlap")
    step = make("recruitment_step", perm_case_id=perm_case_id, step_type=step_type,
                start_date=start_date, end_date=end_date, status="ACTIVE")
    DB["recruitment_steps"][step["id"]] = step
    return ok(serialize(step), 201)


@app.route("/recruitment-steps/<rid>", methods=["GET"])
def get_recruitment_step(rid):
    authenticate()
    return ok(serialize(load_or_404("recruitment_steps", rid)))


@app.route("/recruitment-steps", methods=["GET"])
def list_recruitment_steps():
    authenticate()
    items = list(DB["recruitment_steps"].values())
    for key in ("perm_case_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    return list_response(items)


# ===========================================================================
# LCAs
# ===========================================================================
@app.route("/lcas", methods=["POST"])
def create_lca():
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    employer_id = body.get("employer_id")
    if employer_id is not None:
        check_owner(role, uid, employer_id)
    resolve("employers", employer_id)
    employer_id = req_str(body, "employer_id")
    soc_code = req_str(body, "soc_code")
    worksite_areas = body.get("worksite_areas")
    if not isinstance(worksite_areas, list) or len(worksite_areas) < 1 \
            or not all(isinstance(a, str) for a in worksite_areas):
        bad("worksite_areas must be a non-empty list of strings")
    area_wage_map = body.get("area_wage_map")
    if not isinstance(area_wage_map, dict):
        bad("area_wage_map is required")
    for area in worksite_areas:
        if area not in area_wage_map:
            bad("area_wage_map must cover every worksite area")
        v = area_wage_map[area]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            bad("area_wage_map values must be non-negative integers")
    offered = req_int(body, "offered_wage_cents", mn=0)
    prevailing = req_int(body, "prevailing_wage_cents", mn=0)
    hours = opt_int(body, "hours_per_week", 40, mn=1, mx=40)
    validity_start = req_dt(body, "validity_start")
    validity_end = req_dt(body, "validity_end")
    if parse_dt(validity_end) <= parse_dt(validity_start):
        bad("validity_end must be after validity_start")
    lca = make("lca", employer_id=employer_id, soc_code=soc_code,
               worksite_areas=list(worksite_areas), area_wage_map=dict(area_wage_map),
               offered_wage_cents=offered, prevailing_wage_cents=prevailing,
               hours_per_week=hours, validity_start=validity_start,
               validity_end=validity_end,
               has_wage_rate=opt_bool(body, "has_wage_rate", False),
               has_prevailing_wage_doc=opt_bool(body, "has_prevailing_wage_doc", False),
               has_notice_of_filing=opt_bool(body, "has_notice_of_filing", False),
               has_actual_wage_memo=opt_bool(body, "has_actual_wage_memo", False),
               paf_status="OPEN", status="DRAFT", _locked_required=None)
    DB["lcas"][lca["id"]] = lca
    return ok(serialize(lca), 201)


@app.route("/lcas/<rid>", methods=["GET"])
def get_lca(rid):
    authenticate()
    return ok(serialize(load_or_404("lcas", rid)))


@app.route("/lcas", methods=["GET"])
def list_lcas():
    authenticate()
    items = list(DB["lcas"].values())
    for key in ("employer_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    return list_response(items)


@app.route("/lcas/<rid>", methods=["PATCH"])
def patch_lca(rid):
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    lca = load_or_404("lcas", rid)
    check_owner(role, uid, lca["employer_id"])
    body = get_body()
    updates = {}
    if "prevailing_wage_cents" in body and body["prevailing_wage_cents"] is not None:
        updates["prevailing_wage_cents"] = req_int(body, "prevailing_wage_cents", mn=0)
    if "offered_wage_cents" in body and body["offered_wage_cents"] is not None:
        updates["offered_wage_cents"] = req_int(body, "offered_wage_cents", mn=0)
    if "hours_per_week" in body and body["hours_per_week"] is not None:
        updates["hours_per_week"] = req_int(body, "hours_per_week", mn=1, mx=40)
    if "area_wage_map" in body and body["area_wage_map"] is not None:
        awm = body["area_wage_map"]
        if not isinstance(awm, dict):
            bad("area_wage_map must be an object")
        for area in lca["worksite_areas"]:
            if area not in awm:
                bad("area_wage_map must cover every worksite area")
            v = awm[area]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                bad("area_wage_map values must be non-negative integers")
        updates["area_wage_map"] = dict(awm)
    for flag in ("has_wage_rate", "has_prevailing_wage_doc",
                 "has_notice_of_filing", "has_actual_wage_memo"):
        if flag in body and body[flag] is not None:
            updates[flag] = opt_bool(body, flag, lca[flag])
    if lca["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "LCA is not editable outside DRAFT")
    lca.update(updates)
    bump(lca)
    return ok(serialize(lca))


LCA_TARGET_ROLE = {"CERTIFIED": "DOLAnalyst", "WITHDRAWN": "EmployerAgent"}


@app.route("/lcas/<rid>/transitions", methods=["POST"])
def transition_lca(rid):
    uid, role = authenticate()
    require_role(role, set(LCA_TARGET_ROLE.values()))
    body = get_body()
    to_status = body.get("to_status")
    if isinstance(to_status, str) and to_status in LCA_TARGET_ROLE \
            and role != LCA_TARGET_ROLE[to_status]:
        err("ERR_UNAUTHORIZED", 403, "role not permitted for this transition")
    lca = load_or_404("lcas", rid)
    check_owner(role, uid, lca["employer_id"])
    if not isinstance(to_status, str) or to_status == "":
        bad("to_status is required")

    if to_status == "CERTIFIED":
        if lca["status"] != "DRAFT":
            err("ERR_INVALID_STATE", 409, "not in DRAFT")
        if lca["offered_wage_cents"] < lca["prevailing_wage_cents"]:
            err("ERR_WAGE_BELOW_PREVAILING", 422, "offered wage below prevailing")
        locked = max(lca["prevailing_wage_cents"], lca["offered_wage_cents"])
        lca["_locked_required"] = locked
        lca["status"] = "CERTIFIED"
        bump(lca)
        employer = DB["employers"].get(lca["employer_id"])
        if employer is not None:
            employer["total_wage_obligation_cents"] += locked
            bump(employer)
    elif to_status == "WITHDRAWN":
        if lca["status"] != "CERTIFIED":
            err("ERR_INVALID_STATE", 409, "not in CERTIFIED")
        employer = DB["employers"].get(lca["employer_id"])
        if employer is not None:
            employer["total_wage_obligation_cents"] -= lca["_locked_required"]
            bump(employer)
        lca["status"] = "WITHDRAWN"
        bump(lca)
        for p in list(DB["h1b_petitions"].values()):
            if p["lca_id"] == lca["id"] and p["status"] in ("DRAFT", "SUBMITTED", "RFE_ISSUED"):
                prev = p["status"]
                p["status"] = "DENIED"
                bump(p)
                if prev in ("SUBMITTED", "RFE_ISSUED"):
                    recompute_beneficiary(p["beneficiary_id"])
    else:
        err("ERR_INVALID_STATE", 409, "unknown target state")
    return ok(serialize(lca))


@app.route("/lcas/<rid>/audit-paf", methods=["POST"])
def audit_paf(rid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceAuditor"})
    lca = load_or_404("lcas", rid)
    score = lca_paf_score(lca)
    lca["paf_status"] = "COMPLETE" if score == 100 else "DEFICIENT"
    bump(lca)
    return ok(serialize(lca))


# ===========================================================================
# BENEFICIARIES
# ===========================================================================
@app.route("/beneficiaries", methods=["POST"])
def create_beneficiary():
    _uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    full_name = req_str(body, "full_name")
    passport_number = req_str(body, "passport_number")
    ben = make("beneficiary", full_name=full_name,
               passport_number=passport_number,
               status_valid_until=None, priority_date=None)
    DB["beneficiaries"][ben["id"]] = ben
    return ok(serialize(ben), 201)


@app.route("/beneficiaries/<rid>", methods=["GET"])
def get_beneficiary(rid):
    authenticate()
    return ok(serialize(load_or_404("beneficiaries", rid)))


# ===========================================================================
# CAP PROGRAMS
# ===========================================================================
@app.route("/cap-programs", methods=["POST"])
def create_cap_program():
    _uid, role = authenticate()
    require_role(role, {"USCISOfficer"})
    body = get_body()
    fiscal_year = req_int(body, "fiscal_year")
    selection_quota = req_int(body, "selection_quota", mn=0)
    for p in DB["cap_programs"].values():
        if p["fiscal_year"] == fiscal_year:
            bad("fiscal_year must be unique across programs")
    prog = make("cap_program", fiscal_year=fiscal_year,
                selection_quota=selection_quota, selected_count=0,
                lottery_run=False)
    DB["cap_programs"][prog["id"]] = prog
    return ok(serialize(prog), 201)


@app.route("/cap-programs/<rid>", methods=["GET"])
def get_cap_program(rid):
    authenticate()
    return ok(serialize(load_or_404("cap_programs", rid)))


@app.route("/cap-programs/<rid>/run-lottery", methods=["POST"])
def run_lottery(rid):
    _uid, role = authenticate()
    require_role(role, {"USCISOfficer"})
    prog = load_or_404("cap_programs", rid)
    if prog["lottery_run"]:
        err("ERR_INVALID_STATE", 409, "lottery already run")
    candidates = [r for r in DB["registrations"].values()
                  if r["fiscal_year"] == prog["fiscal_year"] and r["status"] == "SUBMITTED"]
    candidates.sort(key=lambda d: (parse_dt(d["created_at"]), d["_seq"]))
    available = prog["selection_quota"] - prog["selected_count"]
    for i, r in enumerate(candidates):
        if i < available:
            r["status"] = "SELECTED"
        else:
            r["status"] = "NOT_SELECTED"
        bump(r)
    prog["selected_count"] = sum(
        1 for r in DB["registrations"].values()
        if r["fiscal_year"] == prog["fiscal_year"] and r["status"] == "SELECTED")
    prog["lottery_run"] = True
    bump(prog)
    return ok(serialize(prog))


# ===========================================================================
# H1B REGISTRATIONS
# ===========================================================================
@app.route("/h1b-registrations", methods=["POST"])
def create_registration():
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    employer_id = body.get("employer_id")
    if employer_id is not None:
        check_owner(role, uid, employer_id)
    resolve("employers", employer_id)
    resolve("beneficiaries", body.get("beneficiary_id"))
    employer_id = req_str(body, "employer_id")
    beneficiary_id = req_str(body, "beneficiary_id")
    fiscal_year = req_int(body, "fiscal_year")
    if not any(p["fiscal_year"] == fiscal_year for p in DB["cap_programs"].values()):
        bad("fiscal_year must match an existing cap program")
    for r in DB["registrations"].values():
        if (r["employer_id"] == employer_id and r["beneficiary_id"] == beneficiary_id
                and r["fiscal_year"] == fiscal_year):
            err("ERR_DUPLICATE_REGISTRATION", 409, "duplicate registration")
    reg = make("registration", employer_id=employer_id, beneficiary_id=beneficiary_id,
               fiscal_year=fiscal_year, status="SUBMITTED")
    DB["registrations"][reg["id"]] = reg
    return ok(serialize(reg), 201)


@app.route("/h1b-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    authenticate()
    return ok(serialize(load_or_404("registrations", rid)))


@app.route("/h1b-registrations", methods=["GET"])
def list_registrations():
    authenticate()
    items = list(DB["registrations"].values())
    for key in ("employer_id", "beneficiary_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    fy = request.args.get("fiscal_year")
    if fy is not None:
        try:
            fy_int = int(fy)
        except (TypeError, ValueError):
            bad("fiscal_year must be an integer")
        items = [d for d in items if d["fiscal_year"] == fy_int]
    return list_response(items)


@app.route("/h1b-registrations/<rid>/transitions", methods=["POST"])
def transition_registration(rid):
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    to_status = body.get("to_status")
    reg = load_or_404("registrations", rid)
    check_owner(role, uid, reg["employer_id"])
    if not isinstance(to_status, str) or to_status == "":
        bad("to_status is required")
    if to_status == "WITHDRAWN":
        if reg["status"] != "SELECTED":
            err("ERR_INVALID_STATE", 409, "not in SELECTED")
        if any(p["registration_id"] == reg["id"] for p in DB["h1b_petitions"].values()):
            err("ERR_REGISTRATION_HAS_PETITION", 409, "registration has a petition")
        reg["status"] = "WITHDRAWN"
        bump(reg)
        for prog in DB["cap_programs"].values():
            if prog["fiscal_year"] == reg["fiscal_year"]:
                prog["selected_count"] -= 1
                bump(prog)
                break
    else:
        err("ERR_INVALID_STATE", 409, "unknown target state")
    return ok(serialize(reg))


# ===========================================================================
# H1B PETITIONS
# ===========================================================================
def compute_filing_fee(employer, is_amended):
    fee = BASE_FILING_FEE_CENTS
    if not is_amended:
        fee += FRAUD_FEE_CENTS
        if employer["employee_count"] <= ACWIA_SIZE_THRESHOLD:
            fee += ACWIA_SMALL_CENTS
        else:
            fee += ACWIA_LARGE_CENTS
        if employer["employee_count"] > PL_SIZE_THRESHOLD and employer["h1b_dependent"]:
            fee += PL_114_113_FEE_CENTS
    return fee


@app.route("/h1b-petitions", methods=["POST"])
def create_h1b_petition():
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    employer_id = body.get("employer_id")
    if employer_id is not None:
        check_owner(role, uid, employer_id)
    employer = resolve("employers", employer_id)
    resolve("lcas", body.get("lca_id"))
    resolve("beneficiaries", body.get("beneficiary_id"))
    resolve("registrations", body.get("registration_id"))
    employer_id = req_str(body, "employer_id")
    lca_id = req_str(body, "lca_id")
    beneficiary_id = req_str(body, "beneficiary_id")
    registration_id = req_str(body, "registration_id")
    worksite_area = req_str(body, "worksite_area")
    employment_start = req_dt(body, "employment_start")
    employment_end = req_dt(body, "employment_end")
    if parse_dt(employment_end) <= parse_dt(employment_start):
        bad("employment_end must be after employment_start")
    is_amended = opt_bool(body, "is_amended", False)
    fee = compute_filing_fee(employer, is_amended)
    pet = make("h1b_petition", employer_id=employer_id, lca_id=lca_id,
               beneficiary_id=beneficiary_id, registration_id=registration_id,
               worksite_area=worksite_area, employment_start=employment_start,
               employment_end=employment_end, is_amended=is_amended,
               filing_fee_cents=fee, rfe_status="NONE", rfe_issued_date=None,
               rfe_due_date=None, rfe_response_date=None, status="DRAFT")
    DB["h1b_petitions"][pet["id"]] = pet
    return ok(serialize(pet), 201)


@app.route("/h1b-petitions/<rid>", methods=["GET"])
def get_h1b_petition(rid):
    authenticate()
    return ok(serialize(load_or_404("h1b_petitions", rid)))


@app.route("/h1b-petitions", methods=["GET"])
def list_h1b_petitions():
    authenticate()
    items = list(DB["h1b_petitions"].values())
    for key in ("employer_id", "lca_id", "beneficiary_id", "registration_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    return list_response(items)


H1B_TARGET_ROLE = {
    "SUBMITTED": "EmployerAgent", "RFE_ISSUED": "USCISOfficer",
    "APPROVED": "USCISOfficer", "DENIED": "USCISOfficer",
}


@app.route("/h1b-petitions/<rid>/transitions", methods=["POST"])
def transition_h1b_petition(rid):
    uid, role = authenticate()
    require_role(role, set(H1B_TARGET_ROLE.values()))
    body = get_body()
    to_status = body.get("to_status")
    if isinstance(to_status, str) and to_status in H1B_TARGET_ROLE \
            and role != H1B_TARGET_ROLE[to_status]:
        err("ERR_UNAUTHORIZED", 403, "role not permitted for this transition")
    pet = load_or_404("h1b_petitions", rid)
    check_owner(role, uid, pet["employer_id"])
    if not isinstance(to_status, str) or to_status == "":
        bad("to_status is required")

    if to_status == "SUBMITTED":
        if pet["status"] == "DRAFT":
            lca = DB["lcas"].get(pet["lca_id"])
            if lca is None or lca["status"] != "CERTIFIED":
                err("ERR_LCA_NOT_CERTIFIED", 409, "referenced LCA not CERTIFIED")
            reg = DB["registrations"].get(pet["registration_id"])
            if reg is None or reg["status"] != "SELECTED":
                err("ERR_REGISTRATION_NOT_SELECTED", 409, "registration not SELECTED")
            if pet["worksite_area"] not in lca["worksite_areas"]:
                err("ERR_WORKSITE_NOT_COVERED", 409, "worksite not covered by LCA")
            pet["status"] = "SUBMITTED"
            bump(pet)
        elif pet["status"] == "RFE_ISSUED":
            if CLOCK > parse_dt(pet["rfe_due_date"]):
                err("ERR_RFE_EXPIRED", 422, "RFE response past due date")
            pet["rfe_status"] = "RESPONDED"
            pet["rfe_response_date"] = clock_iso()
            pet["status"] = "SUBMITTED"
            bump(pet)
        else:
            err("ERR_INVALID_STATE", 409, "cannot submit from current state")
    elif to_status == "RFE_ISSUED":
        if pet["status"] != "SUBMITTED":
            err("ERR_INVALID_STATE", 409, "not in SUBMITTED")
        pet["rfe_status"] = "ISSUED"
        pet["rfe_issued_date"] = clock_iso()
        pet["rfe_due_date"] = clock_iso(CLOCK + timedelta(days=RFE_RESPONSE_DAYS))
        pet["status"] = "RFE_ISSUED"
        bump(pet)
    elif to_status == "APPROVED":
        if pet["status"] != "SUBMITTED":
            err("ERR_INVALID_STATE", 409, "not in SUBMITTED")
        ns, ne = parse_dt(pet["employment_start"]), parse_dt(pet["employment_end"])
        for other in DB["h1b_petitions"].values():
            if (other["id"] != pet["id"] and other["status"] == "APPROVED"
                    and other["beneficiary_id"] == pet["beneficiary_id"]
                    and other["worksite_area"] == pet["worksite_area"]):
                os_, oe = parse_dt(other["employment_start"]), parse_dt(other["employment_end"])
                if ns < oe and os_ < ne:  # half-open overlap; adjacency allowed
                    err("ERR_EMPLOYMENT_OVERLAP", 409, "employment interval overlap")
        pet["status"] = "APPROVED"
        bump(pet)
        recompute_beneficiary(pet["beneficiary_id"])
    elif to_status == "DENIED":
        if pet["status"] != "SUBMITTED":
            err("ERR_INVALID_STATE", 409, "not in SUBMITTED")
        pet["status"] = "DENIED"
        bump(pet)
        recompute_beneficiary(pet["beneficiary_id"])
    else:
        err("ERR_INVALID_STATE", 409, "unknown target state")
    return ok(serialize(pet))


# ===========================================================================
# I140 PETITIONS
# ===========================================================================
@app.route("/i140-petitions", methods=["POST"])
def create_i140_petition():
    uid, role = authenticate()
    require_role(role, {"EmployerAgent"})
    body = get_body()
    employer_id = body.get("employer_id")
    if employer_id is not None:
        check_owner(role, uid, employer_id)
    resolve("employers", employer_id)
    resolve("beneficiaries", body.get("beneficiary_id"))
    if body.get("perm_case_id") is not None:
        resolve("perm_cases", body.get("perm_case_id"))
    employer_id = req_str(body, "employer_id")
    beneficiary_id = req_str(body, "beneficiary_id")
    category = req_enum(body, "category", I140_CATEGORIES)
    perm_case_id = body.get("perm_case_id")
    if perm_case_id is not None and not isinstance(perm_case_id, str):
        bad("perm_case_id must be a string")
    pet = make("i140_petition", employer_id=employer_id,
               perm_case_id=perm_case_id, beneficiary_id=beneficiary_id,
               category=category, filed_date=None, priority_date=None,
               status="DRAFT")
    DB["i140_petitions"][pet["id"]] = pet
    return ok(serialize(pet), 201)


@app.route("/i140-petitions/<rid>", methods=["GET"])
def get_i140_petition(rid):
    authenticate()
    return ok(serialize(load_or_404("i140_petitions", rid)))


@app.route("/i140-petitions", methods=["GET"])
def list_i140_petitions():
    authenticate()
    items = list(DB["i140_petitions"].values())
    for key in ("employer_id", "perm_case_id", "beneficiary_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    return list_response(items)


I140_TARGET_ROLE = {
    "SUBMITTED": "EmployerAgent", "APPROVED": "USCISOfficer", "DENIED": "USCISOfficer",
}


@app.route("/i140-petitions/<rid>/transitions", methods=["POST"])
def transition_i140_petition(rid):
    uid, role = authenticate()
    require_role(role, set(I140_TARGET_ROLE.values()))
    body = get_body()
    to_status = body.get("to_status")
    if isinstance(to_status, str) and to_status in I140_TARGET_ROLE \
            and role != I140_TARGET_ROLE[to_status]:
        err("ERR_UNAUTHORIZED", 403, "role not permitted for this transition")
    pet = load_or_404("i140_petitions", rid)
    check_owner(role, uid, pet["employer_id"])
    if not isinstance(to_status, str) or to_status == "":
        bad("to_status is required")

    if to_status == "SUBMITTED":
        if pet["status"] != "DRAFT":
            err("ERR_INVALID_STATE", 409, "not in DRAFT")
        if pet["perm_case_id"] is not None:
            pc = DB["perm_cases"].get(pet["perm_case_id"])
            if pc is None or pc["status"] != "CERTIFIED":
                err("ERR_PERM_NOT_CERTIFIED", 409, "referenced PERM not CERTIFIED")
        pet["filed_date"] = clock_iso()
        if pet["perm_case_id"] is not None and pet["category"] in ("EB2", "EB3"):
            pet["priority_date"] = DB["perm_cases"][pet["perm_case_id"]]["priority_date"]
        else:
            pet["priority_date"] = pet["filed_date"]
        pet["status"] = "SUBMITTED"
        bump(pet)
    elif to_status == "APPROVED":
        if pet["status"] != "SUBMITTED":
            err("ERR_INVALID_STATE", 409, "not in SUBMITTED")
        pet["status"] = "APPROVED"
        bump(pet)
        recompute_beneficiary(pet["beneficiary_id"])
    elif to_status == "DENIED":
        if pet["status"] != "SUBMITTED":
            err("ERR_INVALID_STATE", 409, "not in SUBMITTED")
        pet["status"] = "DENIED"
        bump(pet)
        recompute_beneficiary(pet["beneficiary_id"])
    else:
        err("ERR_INVALID_STATE", 409, "unknown target state")
    return ok(serialize(pet))


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or to_iso == "":
        bad("to_iso8601 is required")
    try:
        new_clock = parse_dt(to_iso)
    except Exception:
        bad("to_iso8601 is not a valid datetime")
    global CLOCK
    CLOCK = new_clock
    # Evaluate due expiries (order: PWD, LCA, then RFE deadlines).
    for pwd in list(DB["pwds"].values()):
        if pwd["status"] == "ISSUED" and CLOCK > parse_dt(pwd["validity_end"]):
            pwd["status"] = "EXPIRED"
            bump(pwd)
    for lca in list(DB["lcas"].values()):
        if lca["status"] == "CERTIFIED" and CLOCK > parse_dt(lca["validity_end"]):
            lca["status"] = "EXPIRED"
            bump(lca)
    for pet in list(DB["h1b_petitions"].values()):
        if pet["status"] == "RFE_ISSUED" and pet["rfe_due_date"] \
                and CLOCK > parse_dt(pet["rfe_due_date"]):
            pet["status"] = "DENIED"
            bump(pet)
            recompute_beneficiary(pet["beneficiary_id"])
    return ok({"current_utc": clock_iso()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
