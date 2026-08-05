"""Victim Services & Compensation Program API (task_0892).

Single-file Flask implementation. In-memory stores, logical clock, integer-cents
arithmetic. Boots empty on every process start (no seeding).
"""
import os
import uuid
import secrets
import string
import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ProgramAdmin", "IntakeCounselor", "Adjudicator",
         "FinanceOfficer", "RecoveryOfficer", "AppealsOfficer"}
ALL_ROLES = ROLES

WAGE_REPLACEMENT_RATE = Decimal("0.6667")
WEEKLY_MAX_CENTS = 120000
FILING_DEADLINE_DAYS = 365
APPEAL_WINDOW_DAYS = 30

CRIME_TYPES = {"ASSAULT", "HOMICIDE", "DOMESTIC_VIOLENCE", "DUI",
               "ROBBERY", "SEXUAL_ASSAULT", "OTHER"}
COOPERATION = {"PENDING", "COOPERATIVE", "NONCOOPERATIVE"}
CATEGORIES = {"MEDICAL", "LOST_WAGE", "FUNERAL", "MENTAL_HEALTH"}
SOURCE_TYPES = {"HEALTH_INSURANCE", "AUTO_INSURANCE", "LIFE_INSURANCE",
                "EMPLOYER_BENEFIT", "RESTITUTION", "OTHER_PUBLIC"}
PAYEE_TYPES = {"VICTIM", "MEDICAL_PROVIDER", "FUNERAL_HOME", "MENTAL_HEALTH_PROVIDER"}

CAT_CAP_FIELD = {
    "MEDICAL": "medical_cap_cents",
    "LOST_WAGE": "lost_wage_cap_cents",
    "FUNERAL": "funeral_cap_cents",
    "MENTAL_HEALTH": "mental_health_cap_cents",
}

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
programs = {}
cases = {}
claims = {}
collateral_sources = {}
awards = {}
disbursements = {}
recoveries = {}
receipts = {}
appeals = {}
notifications = {}

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK = datetime.datetime(2026, 5, 1, 0, 0, 0)


def render_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now_ts():
    return render_ts(CLOCK)


def parse_instant(s):
    """Parse an ISO-8601 instant into a naive-UTC datetime."""
    if not isinstance(s, str) or not s.strip():
        raise ApiError("ERR_VALIDATION", 400, "invalid timestamp")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(t)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "invalid timestamp")
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(s):
    """Parse the calendar date from an ISO-8601 date/datetime string."""
    if not isinstance(s, str) or len(s) < 10:
        raise ApiError("ERR_VALIDATION", 400, "invalid date")
    try:
        return datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "invalid date")


def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors & response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def gen_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def make_meta(pagination=None):
    meta = {"api_request_id": gen_request_id(),
            "api_request_timestamp": render_ts(CLOCK)}
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, code=200, response_type="object", pagination=None):
    body = {"meta": make_meta(pagination),
            "response_type": response_type,
            "data": data}
    return jsonify(body), code


def err_response(error_id, http_status, message):
    body = {"meta": make_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, uid, role):
        self.uid = uid
        self.role = role


def authctx():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unknown credentials")
    return Ctx(uid, role)


def require(role, allowed):
    if isinstance(allowed, str):
        allowed = {allowed}
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")


def check_status_role(to_status, mapping, role):
    """Per-target-status role enforcement (only when to_status is a known target)."""
    if to_status in mapping and role not in mapping[to_status]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this transition")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "body must be an object")
    return data


def v_err(msg="validation error"):
    raise ApiError("ERR_VALIDATION", 400, msg)


def need_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        v_err("missing or invalid field: %s" % key)
    return v


def need_int(body, key, min_val=None, gt=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        v_err("missing or invalid integer: %s" % key)
    if min_val is not None and v < min_val:
        v_err("%s below minimum" % key)
    if gt is not None and not v > gt:
        v_err("%s must be > %s" % (key, gt))
    return v


def opt_int(body, key, min_val=None, gt=None):
    if body.get(key) is None:
        return None
    return need_int(body, key, min_val=min_val, gt=gt)


def need_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        v_err("missing or invalid enum: %s" % key)
    return v


def need_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        v_err("missing or invalid boolean: %s" % key)
    return v


def need_date(body, key):
    v = body.get(key)
    if not isinstance(v, str):
        v_err("missing or invalid date: %s" % key)
    parse_date(v)
    return v


def opt_date(body, key):
    if body.get(key) is None:
        return None
    return need_date(body, key)


def resolve_fk(body, key, store, not_found_err, required=True):
    v = body.get(key)
    if v is None:
        if required:
            v_err("missing required reference: %s" % key)
        return None
    if not isinstance(v, str):
        v_err("invalid reference: %s" % key)
    obj = store.get(v)
    if obj is None:
        raise ApiError(not_found_err, 404, "%s not found" % key)
    return obj


def path_lookup(store, ident, not_found_err):
    obj = store.get(ident)
    if obj is None:
        raise ApiError(not_found_err, 404, "resource not found")
    return obj


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except Exception:
            v_err("invalid limit")
        if limit < 1 or limit > 100:
            v_err("limit out of bounds")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except Exception:
            v_err("invalid offset")
        if offset < 0:
            v_err("offset out of bounds")
    return limit, offset


def paginate(items, serialize):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": offset + len(page) < total}
    return ok([serialize(o) for o in page], 200, "array", pagination)


# ---------------------------------------------------------------------------
# Common create / mutate helpers
# ---------------------------------------------------------------------------
def new_common():
    return {"id": str(uuid.uuid4()),
            "created_at": now_ts(),
            "updated_at": now_ts(),
            "version": 1,
            "_seq": next_seq()}


def bump(entity):
    entity["version"] += 1
    entity["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# Cross-aggregate lookups & derived figures
# ---------------------------------------------------------------------------
def award_program(award):
    case = cases.get(award["case_id"])
    if not case:
        return None
    return programs.get(case["program_id"])


def bump_program_for_award(award):
    prog = award_program(award)
    if prog:
        bump(prog)


def award_amount_paid(award_id):
    return sum(d["amount_cents"] for d in disbursements.values()
               if d["award_id"] == award_id and d["status"] == "PAID")


def award_payment_status(award):
    paid = award_amount_paid(award["id"])
    net = award["net_award_cents"]
    if paid <= 0:
        return "UNPAID"
    if paid < net:
        return "PARTIALLY_PAID"
    return "FULLY_PAID"


def recovery_recovered(recovery_id):
    return sum(r["amount_cents"] for r in receipts.values()
               if r["recovery_id"] == recovery_id and r["status"] == "RECORDED")


def prog_committed(pid):
    total = 0
    for a in awards.values():
        c = cases.get(a["case_id"])
        if c and c["program_id"] == pid:
            total += a["net_award_cents"]
    return total


def prog_disbursed(pid):
    total = 0
    for d in disbursements.values():
        if d["status"] != "PAID":
            continue
        a = awards.get(d["award_id"])
        if not a:
            continue
        c = cases.get(a["case_id"])
        if c and c["program_id"] == pid:
            total += d["amount_cents"]
    return total


def prog_recovered(pid):
    total = 0
    for r in receipts.values():
        if r["status"] != "RECORDED":
            continue
        rec = recoveries.get(r["recovery_id"])
        if not rec:
            continue
        c = cases.get(rec["case_id"])
        if c and c["program_id"] == pid:
            total += r["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def wage_assessed_base(claim):
    per_week = round_half_up(min(Decimal(claim["weekly_wage_cents"]) * WAGE_REPLACEMENT_RATE,
                                 Decimal(WEEKLY_MAX_CENTS)))
    return per_week * claim["num_weeks"]


def claim_offset(claim_id, statuses):
    return sum(cs["amount_cents"] for cs in collateral_sources.values()
               if cs["claim_id"] == claim_id and cs["status"] in statuses)


def compute_claim_provisional(claim):
    if claim["category"] == "LOST_WAGE":
        base = wage_assessed_base(claim)
    else:
        base = claim["claimed_amount_cents"]
    offset = claim_offset(claim["id"], {"DECLARED", "CONFIRMED"})
    claim["assessed_base_cents"] = base
    claim["collateral_offset_cents"] = offset
    claim["net_claim_cents"] = max(0, base - offset)


def compute_claim_final(claim):
    if claim["category"] == "LOST_WAGE":
        base = wage_assessed_base(claim)
    else:
        base = claim["verified_amount_cents"]
    offset = claim_offset(claim["id"], {"CONFIRMED"})
    claim["assessed_base_cents"] = base
    claim["collateral_offset_cents"] = offset
    claim["net_claim_cents"] = max(0, base - offset)


def compute_award_figures(case):
    prog = programs.get(case["program_id"])
    approved = [c for c in claims.values()
                if c["case_id"] == case["id"] and c["status"] == "APPROVED"]
    gross = 0
    for cat in CATEGORIES:
        cat_total = sum(c["net_claim_cents"] for c in approved if c["category"] == cat)
        cap = prog[CAT_CAP_FIELD[cat]]
        gross += min(cat_total, cap)
    collateral = sum(c["collateral_offset_cents"] for c in approved)
    net = max(0, min(gross, prog["overall_case_cap_cents"]))
    return gross, collateral, net


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def add_notification(case_id, channel, event_type, message):
    nid = str(uuid.uuid4())
    notifications[nid] = {"id": nid, "case_id": case_id, "channel": channel,
                          "event_type": event_type, "message": message,
                          "created_at": now_ts(), "_seq": next_seq()}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_program(p):
    pid = p["id"]
    committed = prog_committed(pid)
    return {
        "id": pid, "name": p["name"], "fiscal_year": p["fiscal_year"],
        "total_budget_cents": p["total_budget_cents"],
        "overall_case_cap_cents": p["overall_case_cap_cents"],
        "medical_cap_cents": p["medical_cap_cents"],
        "lost_wage_cap_cents": p["lost_wage_cap_cents"],
        "funeral_cap_cents": p["funeral_cap_cents"],
        "mental_health_cap_cents": p["mental_health_cap_cents"],
        "status": p["status"],
        "budget_committed_cents": committed,
        "budget_disbursed_cents": prog_disbursed(pid),
        "budget_recovered_cents": prog_recovered(pid),
        "budget_available_cents": p["total_budget_cents"] - committed,
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_case(c):
    return {k: c[k] for k in (
        "id", "program_id", "victim_name", "incident_date", "crime_type",
        "reported_to_le", "le_report_date", "cooperation_status", "filing_date",
        "status", "eligibility_status", "denied_at", "denied_by_user_id",
        "created_at", "updated_at", "version")}


def ser_claim(c):
    return {k: c[k] for k in (
        "id", "case_id", "category", "claimed_amount_cents", "weekly_wage_cents",
        "num_weeks", "disability_start_date", "disability_end_date",
        "verified_amount_cents", "assessed_base_cents", "collateral_offset_cents",
        "net_claim_cents", "status", "denied_at", "denied_by_user_id",
        "created_at", "updated_at", "version")}


def ser_collateral(c):
    return {k: c[k] for k in (
        "id", "claim_id", "source_type", "amount_cents", "coverage_start_date",
        "coverage_end_date", "status", "created_at", "updated_at", "version")}


def ser_award(a):
    return {
        "id": a["id"], "case_id": a["case_id"],
        "gross_award_cents": a["gross_award_cents"],
        "collateral_offset_cents": a["collateral_offset_cents"],
        "net_award_cents": a["net_award_cents"],
        "amount_paid_cents": award_amount_paid(a["id"]),
        "approval_status": a["approval_status"],
        "payment_status": award_payment_status(a),
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_disbursement(d):
    return {k: d[k] for k in (
        "id", "award_id", "payee_type", "amount_cents", "pay_run_date",
        "status", "created_at", "updated_at", "version")}


def ser_recovery(r):
    out = {k: r[k] for k in (
        "id", "case_id", "offender_name", "ordered_amount_cents",
        "status", "created_at", "updated_at", "version")}
    out["recovered_amount_cents"] = recovery_recovered(r["id"])
    return out


def ser_receipt(r):
    return {k: r[k] for k in (
        "id", "recovery_id", "amount_cents", "received_date", "status",
        "created_at", "updated_at", "version")}


def ser_appeal(a):
    return {k: a[k] for k in (
        "id", "case_id", "claim_id", "appeal_reason", "filed_at", "status",
        "decided_by_user_id", "created_at", "updated_at", "version")}


def ser_notification(n):
    return {k: n[k] for k in (
        "id", "case_id", "channel", "event_type", "message", "created_at")}


# ===========================================================================
# PROGRAM
# ===========================================================================
@app.post("/compensation/programs")
def create_program():
    ctx = authctx()
    require(ctx.role, "ProgramAdmin")
    body = get_body()
    name = need_str(body, "name")
    fiscal_year = need_int(body, "fiscal_year")
    total_budget = need_int(body, "total_budget_cents", min_val=0)
    overall_cap = need_int(body, "overall_case_cap_cents", min_val=0)
    med = need_int(body, "medical_cap_cents", min_val=0)
    wage = need_int(body, "lost_wage_cap_cents", min_val=0)
    fun = need_int(body, "funeral_cap_cents", min_val=0)
    mh = need_int(body, "mental_health_cap_cents", min_val=0)
    p = new_common()
    p.update({"name": name, "fiscal_year": fiscal_year,
              "total_budget_cents": total_budget, "overall_case_cap_cents": overall_cap,
              "medical_cap_cents": med, "lost_wage_cap_cents": wage,
              "funeral_cap_cents": fun, "mental_health_cap_cents": mh,
              "status": "OPEN"})
    programs[p["id"]] = p
    return ok(ser_program(p), 201)


@app.get("/compensation/programs/<pid>")
def get_program(pid):
    authctx()
    p = path_lookup(programs, pid, "ERR_PROGRAM_NOT_FOUND")
    return ok(ser_program(p), 200)


@app.get("/compensation/programs")
def list_programs():
    authctx()
    status = request.args.get("status")
    items = [p for p in programs.values() if status is None or p["status"] == status]
    return paginate(items, ser_program)


@app.post("/compensation/programs/<pid>/transition")
def transition_program(pid):
    ctx = authctx()
    require(ctx.role, "ProgramAdmin")
    body = get_body()
    to_status = body.get("to_status")
    p = path_lookup(programs, pid, "ERR_PROGRAM_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")
    if not (p["status"] == "OPEN" and to_status == "CLOSED"):
        raise ApiError("ERR_INVALID_STATE", 409, "invalid program transition")
    # precondition: no award under this program's cases in CALCULATED/APPROVED
    for a in awards.values():
        c = cases.get(a["case_id"])
        if c and c["program_id"] == pid and a["approval_status"] in ("CALCULATED", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE", 409, "program has non-finalized awards")
    p["status"] = "CLOSED"
    bump(p)
    return ok(ser_program(p), 200)


# ===========================================================================
# VICTIM CASE
# ===========================================================================
@app.post("/compensation/cases")
def create_case():
    ctx = authctx()
    require(ctx.role, "IntakeCounselor")
    body = get_body()
    program = resolve_fk(body, "program_id", programs, "ERR_PROGRAM_NOT_FOUND")
    if program["status"] == "CLOSED":
        raise ApiError("ERR_PROGRAM_CLOSED", 409, "program is closed")
    victim_name = need_str(body, "victim_name")
    incident_date = need_date(body, "incident_date")
    crime_type = need_enum(body, "crime_type", CRIME_TYPES)
    reported = need_bool(body, "reported_to_le")
    le_report_date = opt_date(body, "le_report_date")
    if body.get("cooperation_status") is None:
        cooperation = "PENDING"
    else:
        cooperation = need_enum(body, "cooperation_status", COOPERATION)
    filing_date = need_date(body, "filing_date")
    c = new_common()
    c.update({"program_id": program["id"], "victim_name": victim_name,
              "incident_date": incident_date, "crime_type": crime_type,
              "reported_to_le": reported, "le_report_date": le_report_date,
              "cooperation_status": cooperation, "filing_date": filing_date,
              "status": "DRAFT", "eligibility_status": "UNDETERMINED",
              "denied_at": None, "denied_by_user_id": None})
    cases[c["id"]] = c
    return ok(ser_case(c), 201)


@app.get("/compensation/cases/<cid>")
def get_case(cid):
    authctx()
    c = path_lookup(cases, cid, "ERR_CASE_NOT_FOUND")
    return ok(ser_case(c), 200)


@app.get("/compensation/cases")
def list_cases():
    authctx()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = [c for c in cases.values()
             if (program_id is None or c["program_id"] == program_id)
             and (status is None or c["status"] == status)]
    return paginate(items, ser_case)


CASE_TRANSITION_ROLES = {
    "SUBMITTED": {"IntakeCounselor"},
    "UNDER_REVIEW": {"Adjudicator"},
    "ELIGIBLE": {"Adjudicator"},
    "INELIGIBLE": {"Adjudicator"},
    "CLOSED": {"Adjudicator"},
}


@app.post("/compensation/cases/<cid>/transition")
def transition_case(cid):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, {"IntakeCounselor", "Adjudicator"})
    check_status_role(to_status, CASE_TRANSITION_ROLES, ctx.role)
    c = path_lookup(cases, cid, "ERR_CASE_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")

    # optional cooperation_status update carried on the transition
    if body.get("cooperation_status") is not None:
        c["cooperation_status"] = need_enum(body, "cooperation_status", COOPERATION)

    cur = c["status"]
    valid = {
        ("DRAFT", "SUBMITTED"), ("SUBMITTED", "UNDER_REVIEW"),
        ("UNDER_REVIEW", "ELIGIBLE"), ("UNDER_REVIEW", "INELIGIBLE"),
        ("ELIGIBLE", "CLOSED"),
    }
    if (cur, to_status) not in valid:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid case transition")

    if to_status == "ELIGIBLE":
        if not (c["reported_to_le"] is True and c["cooperation_status"] == "COOPERATIVE"):
            raise ApiError("ERR_ELIGIBILITY_CRITERIA_NOT_MET", 422, "criteria not met")
        days = (parse_date(c["filing_date"]) - parse_date(c["incident_date"])).days
        if not (0 <= days <= FILING_DEADLINE_DAYS):
            raise ApiError("ERR_FILING_DEADLINE_PASSED", 422, "filing deadline passed")
        c["status"] = "ELIGIBLE"
        c["eligibility_status"] = "ELIGIBLE"
        bump(c)
        add_notification(c["id"], "VINE", "ELIGIBILITY_DECISION",
                         "Case ruled eligible")
    elif to_status == "INELIGIBLE":
        c["status"] = "INELIGIBLE"
        c["eligibility_status"] = "INELIGIBLE"
        c["denied_at"] = now_ts()
        c["denied_by_user_id"] = ctx.uid
        bump(c)
        add_notification(c["id"], "VINE", "ELIGIBILITY_DECISION",
                         "Case ruled ineligible")
    elif to_status == "CLOSED":
        case_awards = [a for a in awards.values() if a["case_id"] == c["id"]]
        for a in case_awards:
            if not (a["approval_status"] == "FINALIZED"
                    and award_payment_status(a) == "FULLY_PAID"):
                raise ApiError("ERR_INVALID_STATE", 409, "awards not fully paid")
        c["status"] = "CLOSED"
        bump(c)
    else:  # SUBMITTED / UNDER_REVIEW
        c["status"] = to_status
        bump(c)
    return ok(ser_case(c), 200)


@app.get("/compensation/cases/<cid>/notifications")
def list_case_notifications(cid):
    authctx()
    path_lookup(cases, cid, "ERR_CASE_NOT_FOUND")
    items = [n for n in notifications.values() if n["case_id"] == cid]
    return paginate(items, ser_notification)


# ===========================================================================
# CLAIM
# ===========================================================================
@app.post("/compensation/claims")
def create_claim():
    ctx = authctx()
    require(ctx.role, "IntakeCounselor")
    body = get_body()
    case = resolve_fk(body, "case_id", cases, "ERR_CASE_NOT_FOUND")
    category = need_enum(body, "category", CATEGORIES)
    claimed = opt_int(body, "claimed_amount_cents", min_val=0)
    weekly = opt_int(body, "weekly_wage_cents", min_val=0)
    num_weeks = opt_int(body, "num_weeks", min_val=0)
    dstart = opt_date(body, "disability_start_date")
    dend = opt_date(body, "disability_end_date")
    c = new_common()
    c.update({"case_id": case["id"], "category": category,
              "claimed_amount_cents": claimed, "weekly_wage_cents": weekly,
              "num_weeks": num_weeks, "disability_start_date": dstart,
              "disability_end_date": dend, "verified_amount_cents": None,
              "assessed_base_cents": None, "collateral_offset_cents": None,
              "net_claim_cents": None, "status": "DRAFT",
              "denied_at": None, "denied_by_user_id": None})
    claims[c["id"]] = c
    return ok(ser_claim(c), 201)


@app.get("/compensation/claims/<clid>")
def get_claim(clid):
    authctx()
    c = path_lookup(claims, clid, "ERR_CLAIM_NOT_FOUND")
    return ok(ser_claim(c), 200)


@app.get("/compensation/claims")
def list_claims():
    authctx()
    case_id = request.args.get("case_id")
    category = request.args.get("category")
    status = request.args.get("status")
    items = [c for c in claims.values()
             if (case_id is None or c["case_id"] == case_id)
             and (category is None or c["category"] == category)
             and (status is None or c["status"] == status)]
    return paginate(items, ser_claim)


CLAIM_TRANSITION_ROLES = {
    "SUBMITTED": {"IntakeCounselor"},
    "UNDER_REVIEW": {"Adjudicator"},
    "APPROVED": {"Adjudicator"},
    "DENIED": {"Adjudicator"},
}


def wage_periods_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end)
    return a_start < b_end and b_start < a_end


@app.post("/compensation/claims/<clid>/transition")
def transition_claim(clid):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, {"IntakeCounselor", "Adjudicator"})
    check_status_role(to_status, CLAIM_TRANSITION_ROLES, ctx.role)
    c = path_lookup(claims, clid, "ERR_CLAIM_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")

    cur = c["status"]
    valid = {("DRAFT", "SUBMITTED"), ("SUBMITTED", "UNDER_REVIEW"),
             ("UNDER_REVIEW", "APPROVED"), ("UNDER_REVIEW", "DENIED")}
    if (cur, to_status) not in valid:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid claim transition")

    if to_status == "SUBMITTED":
        # required inputs (ERR_VALIDATION) first
        if c["category"] == "LOST_WAGE":
            if (c["weekly_wage_cents"] is None or c["num_weeks"] is None
                    or c["disability_start_date"] is None or c["disability_end_date"] is None):
                v_err("lost-wage inputs required")
            a_start = parse_date(c["disability_start_date"])
            a_end = parse_date(c["disability_end_date"])
            for other in claims.values():
                if other["id"] == c["id"]:
                    continue
                if other["case_id"] != c["case_id"] or other["category"] != "LOST_WAGE":
                    continue
                if other["status"] == "DENIED":
                    continue
                if other["disability_start_date"] is None or other["disability_end_date"] is None:
                    continue
                b_start = parse_date(other["disability_start_date"])
                b_end = parse_date(other["disability_end_date"])
                if wage_periods_overlap(a_start, a_end, b_start, b_end):
                    raise ApiError("ERR_WAGE_PERIOD_OVERLAP", 409, "wage period overlap")
        else:
            if c["claimed_amount_cents"] is None:
                v_err("claimed_amount_cents required")
        c["status"] = "SUBMITTED"
        compute_claim_provisional(c)
        bump(c)
    elif to_status == "UNDER_REVIEW":
        c["status"] = "UNDER_REVIEW"
        bump(c)
    elif to_status == "APPROVED":
        case = cases.get(c["case_id"])
        if not case or case["status"] != "ELIGIBLE":
            raise ApiError("ERR_CASE_NOT_ELIGIBLE", 409, "case not eligible")
        if c["category"] != "LOST_WAGE":
            verified = need_int(body, "verified_amount_cents", min_val=0)
            c["verified_amount_cents"] = verified
        c["status"] = "APPROVED"
        compute_claim_final(c)
        bump(c)
    elif to_status == "DENIED":
        c["status"] = "DENIED"
        c["net_claim_cents"] = 0
        c["denied_at"] = now_ts()
        c["denied_by_user_id"] = ctx.uid
        bump(c)
        add_notification(c["case_id"], "EMAIL", "CLAIM_DECISION", "Claim denied")
    return ok(ser_claim(c), 200)


# ===========================================================================
# COLLATERAL SOURCE
# ===========================================================================
@app.post("/compensation/collateral-sources")
def create_collateral():
    ctx = authctx()
    require(ctx.role, "IntakeCounselor")
    body = get_body()
    claim = resolve_fk(body, "claim_id", claims, "ERR_CLAIM_NOT_FOUND")
    source_type = need_enum(body, "source_type", SOURCE_TYPES)
    amount = need_int(body, "amount_cents", min_val=0)
    cstart = opt_date(body, "coverage_start_date")
    cend = opt_date(body, "coverage_end_date")
    cs = new_common()
    cs.update({"claim_id": claim["id"], "source_type": source_type,
               "amount_cents": amount, "coverage_start_date": cstart,
               "coverage_end_date": cend, "status": "DECLARED"})
    collateral_sources[cs["id"]] = cs
    return ok(ser_collateral(cs), 201)


@app.get("/compensation/collateral-sources/<csid>")
def get_collateral(csid):
    authctx()
    cs = path_lookup(collateral_sources, csid, "ERR_COLLATERAL_SOURCE_NOT_FOUND")
    return ok(ser_collateral(cs), 200)


@app.get("/compensation/collateral-sources")
def list_collateral():
    authctx()
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    items = [cs for cs in collateral_sources.values()
             if (claim_id is None or cs["claim_id"] == claim_id)
             and (status is None or cs["status"] == status)]
    return paginate(items, ser_collateral)


COLLATERAL_TRANSITION_ROLES = {"CONFIRMED": {"Adjudicator"}, "WAIVED": {"Adjudicator"}}


def closed_intervals_overlap(a_start, a_end, b_start, b_end):
    # closed [start, end]; sharing a boundary date counts as overlap
    return a_start <= b_end and b_start <= a_end


@app.post("/compensation/collateral-sources/<csid>/transition")
def transition_collateral(csid):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, "Adjudicator")
    check_status_role(to_status, COLLATERAL_TRANSITION_ROLES, ctx.role)
    cs = path_lookup(collateral_sources, csid, "ERR_COLLATERAL_SOURCE_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")
    if cs["status"] != "DECLARED" or to_status not in ("CONFIRMED", "WAIVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "invalid collateral transition")

    if to_status == "CONFIRMED":
        has_window = cs["coverage_start_date"] is not None and cs["coverage_end_date"] is not None
        if has_window:
            a_start = parse_date(cs["coverage_start_date"])
            a_end = parse_date(cs["coverage_end_date"])
            for other in collateral_sources.values():
                if other["id"] == cs["id"]:
                    continue
                if other["claim_id"] != cs["claim_id"]:
                    continue
                if other["status"] != "CONFIRMED" or other["source_type"] != cs["source_type"]:
                    continue
                if other["coverage_start_date"] is None or other["coverage_end_date"] is None:
                    continue
                b_start = parse_date(other["coverage_start_date"])
                b_end = parse_date(other["coverage_end_date"])
                if closed_intervals_overlap(a_start, a_end, b_start, b_end):
                    raise ApiError("ERR_COLLATERAL_PERIOD_OVERLAP", 409, "collateral overlap")
        cs["status"] = "CONFIRMED"
    else:
        cs["status"] = "WAIVED"
    bump(cs)
    return ok(ser_collateral(cs), 200)


# ===========================================================================
# AWARD
# ===========================================================================
@app.post("/compensation/awards")
def create_award():
    ctx = authctx()
    require(ctx.role, "Adjudicator")
    body = get_body()
    case = resolve_fk(body, "case_id", cases, "ERR_CASE_NOT_FOUND")
    program = programs.get(case["program_id"])
    # PRD 3.6 order: program closed -> case eligible -> OCC -> budget
    if program["status"] == "CLOSED":
        raise ApiError("ERR_PROGRAM_CLOSED", 409, "program is closed")
    if case["status"] != "ELIGIBLE":
        raise ApiError("ERR_CASE_NOT_ELIGIBLE", 409, "case not eligible")
    expected = body.get("expected_program_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        v_err("expected_program_version required")
    if expected != program["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale program version")

    gross, collateral, net = compute_award_figures(case)
    if net + prog_committed(program["id"]) > program["total_budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 422, "budget exceeded")

    a = new_common()
    a.update({"case_id": case["id"], "gross_award_cents": gross,
              "collateral_offset_cents": collateral, "net_award_cents": net,
              "approval_status": "CALCULATED"})
    awards[a["id"]] = a
    bump(program)  # commit budget & advance OCC version
    return ok(ser_award(a), 201)


@app.get("/compensation/awards/<aid>")
def get_award(aid):
    authctx()
    a = path_lookup(awards, aid, "ERR_AWARD_NOT_FOUND")
    return ok(ser_award(a), 200)


@app.get("/compensation/awards")
def list_awards():
    authctx()
    case_id = request.args.get("case_id")
    items = [a for a in awards.values() if case_id is None or a["case_id"] == case_id]
    return paginate(items, ser_award)


AWARD_TRANSITION_ROLES = {"APPROVED": {"Adjudicator"}, "FINALIZED": {"FinanceOfficer"}}


@app.post("/compensation/awards/<aid>/transition")
def transition_award(aid):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, {"Adjudicator", "FinanceOfficer"})
    check_status_role(to_status, AWARD_TRANSITION_ROLES, ctx.role)
    a = path_lookup(awards, aid, "ERR_AWARD_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")

    cur = a["approval_status"]
    if (cur, to_status) == ("CALCULATED", "APPROVED"):
        if not a["net_award_cents"] > 0:
            raise ApiError("ERR_NO_ELIGIBLE_CLAIMS", 422, "no eligible claims")
        a["approval_status"] = "APPROVED"
        bump(a)
        bump_program_for_award(a)
        add_notification(a["case_id"], "LETTER", "CLAIM_DECISION", "Award approved")
    elif (cur, to_status) == ("APPROVED", "FINALIZED"):
        a["approval_status"] = "FINALIZED"
        bump(a)
        bump_program_for_award(a)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid award transition")
    return ok(ser_award(a), 200)


# ===========================================================================
# DISBURSEMENT
# ===========================================================================
@app.post("/compensation/disbursements")
def create_disbursement():
    ctx = authctx()
    require(ctx.role, "FinanceOfficer")
    body = get_body()
    award = resolve_fk(body, "award_id", awards, "ERR_AWARD_NOT_FOUND")
    if award["approval_status"] not in ("APPROVED", "FINALIZED"):
        raise ApiError("ERR_AWARD_NOT_APPROVED", 409, "award not approved")
    payee_type = need_enum(body, "payee_type", PAYEE_TYPES)
    amount = need_int(body, "amount_cents", gt=0)
    pay_run_date = need_date(body, "pay_run_date")
    existing = sum(d["amount_cents"] for d in disbursements.values()
                   if d["award_id"] == award["id"] and d["status"] in ("SCHEDULED", "PAID"))
    if existing + amount > award["net_award_cents"]:
        raise ApiError("ERR_DISBURSEMENT_EXCEEDS_AWARD", 422, "disbursement exceeds award")
    d = new_common()
    d.update({"award_id": award["id"], "payee_type": payee_type,
              "amount_cents": amount, "pay_run_date": pay_run_date,
              "status": "SCHEDULED"})
    disbursements[d["id"]] = d
    return ok(ser_disbursement(d), 201)


@app.get("/compensation/disbursements/<did>")
def get_disbursement(did):
    authctx()
    d = path_lookup(disbursements, did, "ERR_DISBURSEMENT_NOT_FOUND")
    return ok(ser_disbursement(d), 200)


@app.get("/compensation/disbursements")
def list_disbursements():
    authctx()
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    items = [d for d in disbursements.values()
             if (award_id is None or d["award_id"] == award_id)
             and (status is None or d["status"] == status)]
    return paginate(items, ser_disbursement)


@app.post("/compensation/disbursements/<did>/transition")
def transition_disbursement(did):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, "FinanceOfficer")
    d = path_lookup(disbursements, did, "ERR_DISBURSEMENT_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")
    award = awards.get(d["award_id"])
    cur = d["status"]

    if (cur, to_status) == ("SCHEDULED", "PAID"):
        if not award or award["approval_status"] not in ("APPROVED", "FINALIZED"):
            raise ApiError("ERR_AWARD_NOT_APPROVED", 409, "award not approved")
        d["status"] = "PAID"
        bump(d)
        bump(award)  # amount_paid / payment_status re-derived
        bump_program_for_award(award)
        add_notification(award["case_id"], "VINE", "PAYMENT", "Disbursement paid")
    elif (cur, to_status) == ("SCHEDULED", "VOID"):
        d["status"] = "VOID"
        bump(d)
        if award:
            bump_program_for_award(award)
    elif (cur, to_status) == ("PAID", "CLAWED_BACK"):
        d["status"] = "CLAWED_BACK"
        bump(d)
        if award:
            bump(award)
            bump_program_for_award(award)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid disbursement transition")
    return ok(ser_disbursement(d), 200)


# ===========================================================================
# RESTITUTION RECOVERY
# ===========================================================================
@app.post("/compensation/recoveries")
def create_recovery():
    ctx = authctx()
    require(ctx.role, "RecoveryOfficer")
    body = get_body()
    case = resolve_fk(body, "case_id", cases, "ERR_CASE_NOT_FOUND")
    offender = need_str(body, "offender_name")
    ordered = need_int(body, "ordered_amount_cents", min_val=0)
    r = new_common()
    r.update({"case_id": case["id"], "offender_name": offender,
              "ordered_amount_cents": ordered, "status": "ORDERED"})
    recoveries[r["id"]] = r
    return ok(ser_recovery(r), 201)


@app.get("/compensation/recoveries/<rid>")
def get_recovery(rid):
    authctx()
    r = path_lookup(recoveries, rid, "ERR_RECOVERY_NOT_FOUND")
    return ok(ser_recovery(r), 200)


@app.get("/compensation/recoveries")
def list_recoveries():
    authctx()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    items = [r for r in recoveries.values()
             if (case_id is None or r["case_id"] == case_id)
             and (status is None or r["status"] == status)]
    return paginate(items, ser_recovery)


@app.post("/compensation/recoveries/<rid>/transition")
def transition_recovery(rid):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, "RecoveryOfficer")
    r = path_lookup(recoveries, rid, "ERR_RECOVERY_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")
    cur = r["status"]
    valid = {("ORDERED", "COLLECTING"), ("COLLECTING", "SATISFIED"),
             ("ORDERED", "WRITTEN_OFF"), ("COLLECTING", "WRITTEN_OFF")}
    if (cur, to_status) not in valid:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid recovery transition")
    if to_status == "SATISFIED":
        if recovery_recovered(r["id"]) < r["ordered_amount_cents"]:
            raise ApiError("ERR_INVALID_STATE", 409, "recovery not fully collected")
    r["status"] = to_status
    bump(r)
    return ok(ser_recovery(r), 200)


# ===========================================================================
# RECOVERY RECEIPT
# ===========================================================================
@app.post("/compensation/recoveries/<rid>/receipts")
def create_receipt(rid):
    ctx = authctx()
    require(ctx.role, "RecoveryOfficer")
    recovery = path_lookup(recoveries, rid, "ERR_RECOVERY_NOT_FOUND")
    body = get_body()
    amount = need_int(body, "amount_cents", gt=0)
    received_date = need_date(body, "received_date")
    rc = new_common()
    rc.update({"recovery_id": recovery["id"], "amount_cents": amount,
               "received_date": received_date, "status": "RECORDED"})
    receipts[rc["id"]] = rc
    bump(recovery)  # recovered_amount_cents raised
    case = cases.get(recovery["case_id"])
    if case:
        prog = programs.get(case["program_id"])
        if prog:
            bump(prog)  # budget_recovered_cents raised
    return ok(ser_receipt(rc), 201)


@app.get("/compensation/recoveries/<rid>/receipts")
def list_receipts(rid):
    authctx()
    path_lookup(recoveries, rid, "ERR_RECOVERY_NOT_FOUND")
    status = request.args.get("status")
    items = [r for r in receipts.values()
             if r["recovery_id"] == rid and (status is None or r["status"] == status)]
    return paginate(items, ser_receipt)


@app.post("/compensation/receipts/<rcid>/transition")
def transition_receipt(rcid):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, "RecoveryOfficer")
    rc = path_lookup(receipts, rcid, "ERR_RECEIPT_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")
    if not (rc["status"] == "RECORDED" and to_status == "VOID"):
        raise ApiError("ERR_INVALID_STATE", 409, "invalid receipt transition")
    rc["status"] = "VOID"
    bump(rc)
    recovery = recoveries.get(rc["recovery_id"])
    if recovery:
        bump(recovery)
        case = cases.get(recovery["case_id"])
        if case:
            prog = programs.get(case["program_id"])
            if prog:
                bump(prog)
    return ok(ser_receipt(rc), 200)


# ===========================================================================
# APPEAL
# ===========================================================================
def appeal_target_denied_at(appeal):
    if appeal["claim_id"]:
        claim = claims.get(appeal["claim_id"])
        return claim["denied_at"] if claim else None
    case = cases.get(appeal["case_id"])
    return case["denied_at"] if case else None


def appeal_target_denied_by(appeal):
    if appeal["claim_id"]:
        claim = claims.get(appeal["claim_id"])
        return claim["denied_by_user_id"] if claim else None
    case = cases.get(appeal["case_id"])
    return case["denied_by_user_id"] if case else None


@app.post("/compensation/appeals")
def create_appeal():
    ctx = authctx()
    require(ctx.role, "IntakeCounselor")
    body = get_body()
    case = resolve_fk(body, "case_id", cases, "ERR_CASE_NOT_FOUND")
    claim = resolve_fk(body, "claim_id", claims, "ERR_CLAIM_NOT_FOUND", required=False)
    if claim is not None and claim["case_id"] != case["id"]:
        raise ApiError("ERR_REFERENCE_MISMATCH", 409, "claim does not belong to case")
    appeal_reason = need_str(body, "appeal_reason")

    # appeal window (temporal) — basis is the target's denied_at
    basis = claim["denied_at"] if claim is not None else case["denied_at"]
    if basis is not None:
        days = (CLOCK.date() - parse_date(basis)).days
        if days > APPEAL_WINDOW_DAYS:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED", 422, "appeal window expired")

    a = new_common()
    a.update({"case_id": case["id"], "claim_id": claim["id"] if claim else None,
              "appeal_reason": appeal_reason, "filed_at": now_ts(),
              "status": "FILED", "decided_by_user_id": None})
    appeals[a["id"]] = a
    return ok(ser_appeal(a), 201)


@app.get("/compensation/appeals/<apid>")
def get_appeal(apid):
    authctx()
    a = path_lookup(appeals, apid, "ERR_APPEAL_NOT_FOUND")
    return ok(ser_appeal(a), 200)


@app.get("/compensation/appeals")
def list_appeals():
    authctx()
    case_id = request.args.get("case_id")
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    items = [a for a in appeals.values()
             if (case_id is None or a["case_id"] == case_id)
             and (claim_id is None or a["claim_id"] == claim_id)
             and (status is None or a["status"] == status)]
    return paginate(items, ser_appeal)


@app.post("/compensation/appeals/<apid>/transition")
def transition_appeal(apid):
    ctx = authctx()
    body = get_body()
    to_status = body.get("to_status")
    require(ctx.role, "AppealsOfficer")
    a = path_lookup(appeals, apid, "ERR_APPEAL_NOT_FOUND")
    if to_status is None:
        v_err("to_status required")
    cur = a["status"]
    valid = {("FILED", "UNDER_REVIEW"), ("UNDER_REVIEW", "GRANTED"),
             ("UNDER_REVIEW", "DENIED")}
    if (cur, to_status) not in valid:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid appeal transition")

    if to_status == "UNDER_REVIEW":
        a["status"] = "UNDER_REVIEW"
        bump(a)
        return ok(ser_appeal(a), 200)

    # GRANTED / DENIED — segregation of duties
    denier = appeal_target_denied_by(a)
    if denier is not None and ctx.uid == denier:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "segregation of duties")

    if to_status == "DENIED":
        a["status"] = "DENIED"
        a["decided_by_user_id"] = ctx.uid
        bump(a)
        add_notification(a["case_id"], "LETTER", "APPEAL_DECISION", "Appeal denied")
        return ok(ser_appeal(a), 200)

    # GRANTED — reopen cascade
    a["status"] = "GRANTED"
    a["decided_by_user_id"] = ctx.uid
    bump(a)
    case = cases.get(a["case_id"])
    if case and case["status"] == "INELIGIBLE":
        case["status"] = "UNDER_REVIEW"
        case["eligibility_status"] = "UNDETERMINED"
        case["denied_at"] = None
        bump(case)
    if case:
        for cl in claims.values():
            if cl["case_id"] == case["id"] and cl["status"] == "DENIED":
                cl["status"] = "UNDER_REVIEW"
                cl["denied_at"] = None
                cl["denied_by_user_id"] = None
                bump(cl)
        add_notification(case["id"], "VINE", "CASE_REOPENED", "Case reopened")
        add_notification(case["id"], "VINE", "APPEAL_DECISION", "Appeal granted")
    return ok(ser_appeal(a), 200)


# ===========================================================================
# NOTIFICATION (read only)
# ===========================================================================
@app.get("/compensation/notifications/<nid>")
def get_notification(nid):
    authctx()
    n = path_lookup(notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    return ok(ser_notification(n), 200)


# ===========================================================================
# LOGICAL CLOCK (test driver)
# ===========================================================================
@app.post("/compensation/_clock/set_current_utc")
def set_clock():
    ctx = authctx()
    require(ctx.role, "ProgramAdmin")
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        v_err("to_iso8601 required")
    global CLOCK
    CLOCK = parse_instant(raw)
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
