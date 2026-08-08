"""
Public-Assistance Fraud & Recovery Unit API — Python + Flask reference implementation.

In-memory only. Fresh state on every process boot (per-test-server isolation).
"""
import os
import re
import string
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

UTC = timezone.utc

# =============================================================================
# In-memory store (reset on every boot)
# =============================================================================
DB = {
    "subjects": {},
    "referrals": {},
    "cases": {},
    "evidence": {},
    "overpayments": {},
    "months": {},
    "disqualifications": {},
    "hearings": {},
    "plans": {},
    "transactions": {},
}

# Logical clock — authoritative "now". Startup default per PRD §2.6.
CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)

_SEQ = 0


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


# =============================================================================
# Enumerations
# =============================================================================
ROLES = {"Intake", "Investigator", "Adjudicator", "RecoveryOfficer", "Supervisor"}
ALL_ROLES = set(ROLES)
PROGRAMS = {"SNAP", "TANF", "MEDICAID"}
SOURCES = {"HOTLINE", "DATA_MATCH", "CASEWORKER", "PUBLIC"}
CLAIM_TYPES = {"IPV", "IHE", "AE"}
EVIDENCE_KINDS = {"DOCUMENT", "INTERVIEW", "DATA_MATCH", "SURVEILLANCE"}
PLAN_METHODS = {"RECOUPMENT", "OFFSET", "COLLECTION"}
TX_METHODS = {"PAYMENT", "OFFSET", "RECOUPMENT"}
REFERRAL_DECISIONS = {"ACCEPT", "REJECT"}
CASE_DECISIONS = {"SUBSTANTIATE", "UNSUBSTANTIATE", "RETURN"}
HEARING_OUTCOMES = {"IPV", "NO_IPV", "DISMISSED"}

PROGRAM_WEIGHT = {"SNAP": 30, "TANF": 20, "MEDICAID": 40}
SOURCE_WEIGHT = {"HOTLINE": 10, "DATA_MATCH": 25, "CASEWORKER": 15, "PUBLIC": 5}

ESTABLISHMENT_THRESHOLD_IPV_CENTS = 0
ESTABLISHMENT_THRESHOLD_NONIPV_CENTS = 12500
INTEREST_MONTHLY_RATE = Decimal("0.01")
PAYMENT_DUE_DAYS = 30
FLOOR_IPV_CENTS = 2000
FLOOR_NONIPV_CENTS = 1000

OP_TERMINAL = {"SATISFIED", "WRITTEN_OFF", "TERMINATED"}
PLAN_TERMINAL = {"COMPLETED", "DEFAULTED", "CANCELLED"}


# =============================================================================
# Errors
# =============================================================================
class AppError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    return AppError(error_id, http_status, message)


# =============================================================================
# Response envelope helpers
# =============================================================================
def _req_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _real_now_iso():
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": _real_now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    has_more = (offset + len(items)) < total
    meta = _meta({"limit": limit, "offset": offset, "total_count": total, "has_more": has_more})
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(AppError)
def _handle_app_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def _handle_generic(e):
    if isinstance(e, AppError):
        return _handle_app_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Internal error: %s" % e},
    }
    return jsonify(body), 400


# =============================================================================
# Auth / RBAC
# =============================================================================
def authn():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authz(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# =============================================================================
# Time helpers
# =============================================================================
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_iso_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def last_day_of_month(year, month):
    if month == 12:
        return 31
    nxt = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=UTC)
    return (nxt - timedelta(days=1)).day


def add_months(dt, n):
    m = dt.month - 1 + n
    y = dt.year + m // 12
    mo = m % 12 + 1
    d = min(dt.day, last_day_of_month(y, mo))
    return dt.replace(year=y, month=mo, day=d)


def full_months_between(start, end):
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < (
        start.day, start.hour, start.minute, start.second, start.microsecond
    ):
        months -= 1
    return max(0, months)


# =============================================================================
# Numeric helpers
# =============================================================================
def rhu(value):
    """Round-half-up to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(a, b):
    if b is None or b <= 0:
        return None
    if a <= 0:
        return 0
    return -(-a // b)


# =============================================================================
# Field / body validation helpers
# =============================================================================
def get_body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return raw


def require_str(body, key):
    if key not in body or not isinstance(body[key], str) or body[key] == "":
        raise err("ERR_VALIDATION", 400, "Missing or invalid field: %s" % key)
    return body[key]


def require_int(body, key, allow_negative=False):
    if key not in body:
        raise err("ERR_VALIDATION", 400, "Missing field: %s" % key)
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", 400, "Field must be an integer: %s" % key)
    if not allow_negative and v < 0:
        raise err("ERR_VALIDATION", 400, "Field must be non-negative: %s" % key)
    return v


def optional_int(body, key, allow_negative=False):
    if key not in body or body[key] is None:
        return None
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", 400, "Field must be an integer: %s" % key)
    if not allow_negative and v < 0:
        raise err("ERR_VALIDATION", 400, "Field must be non-negative: %s" % key)
    return v


def check_enum(value, allowed, key):
    if value not in allowed:
        raise err("ERR_INVALID_ENUM", 422, "Invalid value for %s: %s" % (key, value))
    return value


MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_month_format(s):
    if not isinstance(s, str) or not MONTH_RE.match(s):
        raise err("ERR_INVALID_MONTH_FORMAT", 422, "benefit_month must be YYYY-MM")
    mo = int(s[5:7])
    if mo < 1 or mo > 12:
        raise err("ERR_INVALID_MONTH_FORMAT", 422, "benefit_month month out of range")
    return s


def check_date_format(s, key="date"):
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise err("ERR_INVALID_MONTH_FORMAT", 422, "%s must be YYYY-MM-DD" % key)
    try:
        datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        raise err("ERR_INVALID_MONTH_FORMAT", 422, "%s is not a valid date" % key)
    return s


def check_datetime_format(s, key="datetime"):
    if parse_iso_dt(s) is None:
        raise err("ERR_INVALID_MONTH_FORMAT", 422, "%s must be ISO 8601" % key)
    return s


def paginate_args():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", 400, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", 400, "offset must be an integer")
    if limit < 1 or limit > 100 or offset < 0:
        raise err("ERR_PAGINATION_INVALID", 400, "Pagination out of range")
    return limit, offset


def sort_and_page(items, limit, offset):
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# =============================================================================
# Entity lookups
# =============================================================================
def get_or_404(collection, _id):
    ent = DB[collection].get(_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", 404, "%s not found: %s" % (collection, _id))
    return ent


def touch(ent):
    ent["updated_at"] = CLOCK
    if "version" in ent:
        ent["version"] += 1


def base_fields(with_version=True):
    now = CLOCK
    d = {"id": str(uuid.uuid4()), "created_at": now, "_seq": next_seq()}
    if with_version:
        d["updated_at"] = now
        d["version"] = 1
    return d


# =============================================================================
# Derived computations
# =============================================================================
def subject_derived(subject_id):
    disqs = [d for d in DB["disqualifications"].values() if d["subject_id"] == subject_id]
    imposed = [d for d in disqs if d["status"] == "IMPOSED"]
    if any(d.get("is_permanent") for d in imposed):
        return "PERMANENTLY_DISQUALIFIED", None
    active = [d for d in imposed if d.get("disqualified_until") and d["disqualified_until"] > CLOCK]
    if active:
        until = max(d["disqualified_until"] for d in active)
        return "DISQUALIFIED", until
    return "NONE", None


def op_applied_sums(op_id):
    ai = 0
    ap = 0
    for t in DB["transactions"].values():
        if t["overpayment_id"] == op_id and t["status"] == "POSTED":
            ai += t["applied_to_interest_cents"]
            ap += t["applied_to_principal_cents"]
    return ai, ap


def op_accrued_interest(op):
    if op.get("demand_date") is None:
        return 0
    end = op.get("interest_frozen_at") or CLOCK
    n = full_months_between(op["demand_date"], end)
    if n <= 0:
        return 0
    per_month = rhu(Decimal(op["final_amount_cents"]) * INTEREST_MONTHLY_RATE)
    return n * per_month


def op_balances(op):
    ai, ap = op_applied_sums(op["id"])
    accrued = op_accrued_interest(op)
    out_p = op["final_amount_cents"] - ap
    out_i = accrued - ai
    return accrued, out_p, out_i, ap, ai


def plan_monthly_recoupment(plan, op):
    if plan["method"] != "RECOUPMENT":
        return None
    allot = plan.get("monthly_allotment_cents")
    if allot is None:
        return None
    ct = op["claim_type"]
    rate = Decimal("0.20") if ct == "IPV" else Decimal("0.10")
    floor = FLOOR_IPV_CENTS if ct == "IPV" else FLOOR_NONIPV_CENTS
    pct = rhu(Decimal(allot) * rate)
    _, out_p, _, _, _ = op_balances(op)
    out_p = max(0, out_p)
    return min(out_p, max(floor, pct))


# =============================================================================
# Serializers
# =============================================================================
def ser_subject(s):
    status, until = subject_derived(s["id"])
    return {
        "id": s["id"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
        "name": s["name"],
        "ssn_last4": s["ssn_last4"],
        "primary_program": s["primary_program"],
        "prior_ipv_count": s["prior_ipv_count"],
        "disqualification_status": status,
        "disqualified_until": iso(until),
    }


def ser_referral(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
        "subject_id": r["subject_id"],
        "program": r["program"],
        "source": r["source"],
        "allegation_summary": r["allegation_summary"],
        "priority_score": r["priority_score"],
        "status": r["status"],
    }


def ser_case(c):
    return {
        "id": c["id"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
        "referral_id": c["referral_id"],
        "subject_id": c["subject_id"],
        "program": c["program"],
        "assigned_investigator_id": c["assigned_investigator_id"],
        "status": c["status"],
    }


def ser_evidence(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "case_id": e["case_id"],
        "kind": e["kind"],
        "description": e["description"],
        "document_ref": e["document_ref"],
        "submitted_by_user_id": e["submitted_by_user_id"],
    }


def ser_overpayment(o):
    accrued, out_p, out_i, _, _ = op_balances(o)
    return {
        "id": o["id"],
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
        "case_id": o["case_id"],
        "claim_type": o["claim_type"],
        "status": o["status"],
        "provisional_amount_cents": o["provisional_amount_cents"],
        "final_amount_cents": o["final_amount_cents"],
        "total_adjustments_cents": o["total_adjustments_cents"],
        "accrued_interest_cents": accrued,
        "outstanding_principal_cents": out_p,
        "outstanding_interest_cents": out_i,
        "demand_date": iso(o.get("demand_date")),
        "due_date": iso(o.get("due_date")),
    }


def ser_month(m):
    return {
        "id": m["id"],
        "created_at": iso(m["created_at"]),
        "overpayment_id": m["overpayment_id"],
        "benefit_month": m["benefit_month"],
        "benefits_issued_cents": m["benefits_issued_cents"],
        "benefits_entitled_reported_cents": m["benefits_entitled_reported_cents"],
        "benefits_entitled_verified_cents": m["benefits_entitled_verified_cents"],
        "over_issuance_reported_cents": m["over_issuance_reported_cents"],
        "over_issuance_verified_cents": m["over_issuance_verified_cents"],
    }


def ser_disq(d):
    return {
        "id": d["id"],
        "created_at": iso(d["created_at"]),
        "updated_at": iso(d["updated_at"]),
        "version": d["version"],
        "case_id": d["case_id"],
        "subject_id": d["subject_id"],
        "status": d["status"],
        "penalty_months": d["penalty_months"],
        "is_permanent": d["is_permanent"],
        "imposed_at": iso(d.get("imposed_at")),
        "disqualified_until": iso(d.get("disqualified_until")),
    }


def ser_hearing(h):
    return {
        "id": h["id"],
        "created_at": iso(h["created_at"]),
        "updated_at": iso(h["updated_at"]),
        "version": h["version"],
        "disqualification_id": h["disqualification_id"],
        "scheduled_date": h["scheduled_date"],
        "status": h["status"],
        "outcome": h["outcome"],
        "held_at": iso(h.get("held_at")),
        "decided_by_user_id": h["decided_by_user_id"],
    }


def ser_plan(p):
    op = DB["overpayments"].get(p["overpayment_id"])
    monthly = plan_monthly_recoupment(p, op) if op else None
    out_p = 0
    if op:
        _, out_p, _, _, _ = op_balances(op)
        out_p = max(0, out_p)
    proj_reg = ceil_div(out_p, monthly)
    proj_sched = ceil_div(out_p, p.get("scheduled_monthly_cents"))
    return {
        "id": p["id"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
        "overpayment_id": p["overpayment_id"],
        "subject_id": p["subject_id"],
        "method": p["method"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "monthly_allotment_cents": p.get("monthly_allotment_cents"),
        "scheduled_monthly_cents": p.get("scheduled_monthly_cents"),
        "monthly_recoupment_cents": monthly,
        "projected_months_regulatory": proj_reg,
        "projected_months_scheduled": proj_sched,
        "status": p["status"],
    }


def ser_tx(t):
    return {
        "id": t["id"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
        "recovery_plan_id": t["recovery_plan_id"],
        "overpayment_id": t["overpayment_id"],
        "amount_cents": t["amount_cents"],
        "transaction_date": t["transaction_date"],
        "method": t["method"],
        "applied_to_interest_cents": t["applied_to_interest_cents"],
        "applied_to_principal_cents": t["applied_to_principal_cents"],
        "status": t["status"],
    }


# =============================================================================
# Cascade helpers
# =============================================================================
def recompute_overpayment_final(op):
    verified_sum = 0
    for m in DB["months"].values():
        if m["overpayment_id"] == op["id"]:
            verified_sum += m["over_issuance_verified_cents"]
    op["final_amount_cents"] = verified_sum + op["total_adjustments_cents"]


def maybe_satisfy(op):
    if op["status"] != "IN_RECOVERY":
        return
    _, out_p, out_i, _, _ = op_balances(op)
    if out_p <= 0 and out_i <= 0:
        op["status"] = "SATISFIED"
        op["interest_frozen_at"] = CLOCK
        touch(op)
        for p in DB["plans"].values():
            if p["overpayment_id"] == op["id"] and p["status"] == "ACTIVE":
                p["status"] = "COMPLETED"
                touch(p)


def impose_cascade(disq):
    subject = DB["subjects"][disq["subject_id"]]
    # Hop 0: compute penalty from prior_ipv_count observed BEFORE increment.
    n = subject["prior_ipv_count"]
    if n == 0:
        penalty = 12
        permanent = False
    elif n == 1:
        penalty = 24
        permanent = False
    else:
        penalty = None
        permanent = True
    disq["status"] = "IMPOSED"
    disq["penalty_months"] = penalty
    disq["is_permanent"] = permanent
    disq["imposed_at"] = CLOCK
    disq["disqualified_until"] = add_months(CLOCK, penalty) if penalty is not None else None
    touch(disq)
    # Hop 1: increment subject prior_ipv_count.
    subject["prior_ipv_count"] += 1
    touch(subject)
    # Hop 2: reclassify linked case's non-terminal overpayment(s) to IPV.
    for op in DB["overpayments"].values():
        if op["case_id"] == disq["case_id"] and op["status"] not in OP_TERMINAL:
            if op["claim_type"] != "IPV":
                op["claim_type"] = "IPV"
                touch(op)
            # Hop 3: recompute active recovery plan(s) of that overpayment.
            for p in DB["plans"].values():
                if p["overpayment_id"] == op["id"] and p["status"] == "ACTIVE":
                    touch(p)


# =============================================================================
# ROUTES — Subject
# =============================================================================
@app.route("/fraud-recovery/subjects", methods=["POST"])
def create_subject():
    uid, role = authn()
    authz(role, {"Intake"})
    body = get_body()
    name = require_str(body, "name")
    ssn_last4 = require_str(body, "ssn_last4")
    primary_program = require_str(body, "primary_program")
    check_enum(primary_program, PROGRAMS, "primary_program")
    s = base_fields()
    s.update({
        "name": name,
        "ssn_last4": ssn_last4,
        "primary_program": primary_program,
        "prior_ipv_count": 0,
    })
    DB["subjects"][s["id"]] = s
    return ok(ser_subject(s), 201)


@app.route("/fraud-recovery/subjects/<sid>", methods=["GET"])
def get_subject(sid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    s = get_or_404("subjects", sid)
    return ok(ser_subject(s))


# =============================================================================
# ROUTES — Referral
# =============================================================================
@app.route("/fraud-recovery/referrals", methods=["POST"])
def create_referral():
    uid, role = authn()
    authz(role, {"Intake"})
    body = get_body()
    subject_id = body.get("subject_id")
    if isinstance(subject_id, str) and subject_id:
        get_or_404("subjects", subject_id)
    subject_id = require_str(body, "subject_id")
    get_or_404("subjects", subject_id)
    program = require_str(body, "program")
    source = require_str(body, "source")
    allegation_summary = require_str(body, "allegation_summary")
    check_enum(program, PROGRAMS, "program")
    check_enum(source, SOURCES, "source")
    r = base_fields()
    r.update({
        "subject_id": subject_id,
        "program": program,
        "source": source,
        "allegation_summary": allegation_summary,
        "priority_score": PROGRAM_WEIGHT[program] + SOURCE_WEIGHT[source],
        "status": "RECEIVED",
    })
    DB["referrals"][r["id"]] = r
    return ok(ser_referral(r), 201)


@app.route("/fraud-recovery/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    r = get_or_404("referrals", rid)
    return ok(ser_referral(r))


@app.route("/fraud-recovery/referrals", methods=["GET"])
def list_referrals():
    uid, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = paginate_args()
    items = list(DB["referrals"].values())
    sid = request.args.get("subject_id")
    status = request.args.get("status")
    program = request.args.get("program")
    if sid is not None:
        items = [r for r in items if r["subject_id"] == sid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if program is not None:
        items = [r for r in items if r["program"] == program]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_referral(r) for r in page], limit, offset, total)


@app.route("/fraud-recovery/referrals/<rid>/decide", methods=["POST"])
def decide_referral(rid):
    uid, role = authn()
    authz(role, {"Intake"})
    r = get_or_404("referrals", rid)
    body = get_body()
    decision = require_str(body, "decision")
    check_enum(decision, REFERRAL_DECISIONS, "decision")
    if r["status"] in ("REJECTED", "CONVERTED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Referral already terminal")
    if r["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", 409, "Referral not in RECEIVED")
    r["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    touch(r)
    return ok(ser_referral(r))


# =============================================================================
# ROUTES — Case
# =============================================================================
@app.route("/fraud-recovery/cases", methods=["POST"])
def create_case():
    uid, role = authn()
    authz(role, {"Investigator"})
    body = get_body()
    referral_id = require_str(body, "referral_id")
    r = get_or_404("referrals", referral_id)
    if r["status"] in ("REJECTED", "CONVERTED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Referral already terminal")
    if r["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", 409, "Referral not in ACCEPTED")
    c = base_fields()
    c.update({
        "referral_id": referral_id,
        "subject_id": r["subject_id"],
        "program": r["program"],
        "assigned_investigator_id": None,
        "status": "OPEN",
    })
    DB["cases"][c["id"]] = c
    r["status"] = "CONVERTED"
    touch(r)
    return ok(ser_case(c), 201)


@app.route("/fraud-recovery/cases/<cid>", methods=["GET"])
def get_case(cid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    c = get_or_404("cases", cid)
    return ok(ser_case(c))


@app.route("/fraud-recovery/cases", methods=["GET"])
def list_cases():
    uid, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = paginate_args()
    items = list(DB["cases"].values())
    ref = request.args.get("referral_id")
    sid = request.args.get("subject_id")
    status = request.args.get("status")
    if ref is not None:
        items = [c for c in items if c["referral_id"] == ref]
    if sid is not None:
        items = [c for c in items if c["subject_id"] == sid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_case(c) for c in page], limit, offset, total)


@app.route("/fraud-recovery/cases/<cid>/assign", methods=["POST"])
def assign_case(cid):
    uid, role = authn()
    authz(role, {"Investigator"})
    c = get_or_404("cases", cid)
    body = get_body()
    inv = body.get("investigator_user_id")
    if inv is not None and (not isinstance(inv, str) or inv == ""):
        raise err("ERR_VALIDATION", 400, "investigator_user_id must be a non-empty string")
    if c["status"] in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Case already terminal")
    if c["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", 409, "Case not in OPEN")
    c["assigned_investigator_id"] = inv if inv else uid
    c["status"] = "INVESTIGATION"
    touch(c)
    return ok(ser_case(c))


@app.route("/fraud-recovery/cases/<cid>/submit-review", methods=["POST"])
def submit_review(cid):
    uid, role = authn()
    authz(role, {"Investigator"})
    c = get_or_404("cases", cid)
    if c["status"] in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Case already terminal")
    if c["status"] != "INVESTIGATION":
        raise err("ERR_INVALID_STATE", 409, "Case not in INVESTIGATION")
    has_evidence = any(e["case_id"] == cid for e in DB["evidence"].values())
    if not has_evidence:
        raise err("ERR_NO_EVIDENCE", 409, "Case has no evidence")
    c["status"] = "PENDING_REVIEW"
    touch(c)
    return ok(ser_case(c))


@app.route("/fraud-recovery/cases/<cid>/adjudicate", methods=["POST"])
def adjudicate_case(cid):
    uid, role = authn()
    authz(role, {"Supervisor"})
    c = get_or_404("cases", cid)
    body = get_body()
    decision = require_str(body, "decision")
    check_enum(decision, CASE_DECISIONS, "decision")
    if c["status"] in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Case already terminal")
    if c["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "Case not in PENDING_REVIEW")
    if decision == "RETURN":
        c["status"] = "INVESTIGATION"
    elif decision == "SUBSTANTIATE":
        c["status"] = "SUBSTANTIATED"
    else:  # UNSUBSTANTIATE
        c["status"] = "UNSUBSTANTIATED"
        for op in DB["overpayments"].values():
            if op["case_id"] == cid and op["status"] in ("DRAFT", "CALCULATED"):
                op["status"] = "TERMINATED"
                touch(op)
                for p in DB["plans"].values():
                    if p["overpayment_id"] == op["id"] and p["status"] not in PLAN_TERMINAL:
                        p["status"] = "CANCELLED"
                        touch(p)
    touch(c)
    return ok(ser_case(c))


@app.route("/fraud-recovery/cases/<cid>/evidence", methods=["POST"])
def add_evidence(cid):
    uid, role = authn()
    authz(role, {"Investigator"})
    c = get_or_404("cases", cid)
    body = get_body()
    kind = require_str(body, "kind")
    description = require_str(body, "description")
    document_ref = body.get("document_ref")
    if document_ref is not None and not isinstance(document_ref, str):
        raise err("ERR_VALIDATION", 400, "document_ref must be a string")
    check_enum(kind, EVIDENCE_KINDS, "kind")
    e = base_fields(with_version=False)
    e.update({
        "case_id": cid,
        "kind": kind,
        "description": description,
        "document_ref": document_ref,
        "submitted_by_user_id": uid,
    })
    DB["evidence"][e["id"]] = e
    return ok(ser_evidence(e), 201)


@app.route("/fraud-recovery/cases/<cid>/evidence", methods=["GET"])
def list_evidence(cid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    get_or_404("cases", cid)
    limit, offset = paginate_args()
    items = [e for e in DB["evidence"].values() if e["case_id"] == cid]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_evidence(e) for e in page], limit, offset, total)


# =============================================================================
# ROUTES — Overpayment
# =============================================================================
@app.route("/fraud-recovery/overpayments", methods=["POST"])
def create_overpayment():
    uid, role = authn()
    authz(role, {"Investigator"})
    body = get_body()
    case_id = require_str(body, "case_id")
    get_or_404("cases", case_id)
    claim_type = require_str(body, "claim_type")
    check_enum(claim_type, CLAIM_TYPES, "claim_type")
    o = base_fields()
    o.update({
        "case_id": case_id,
        "claim_type": claim_type,
        "status": "DRAFT",
        "provisional_amount_cents": 0,
        "final_amount_cents": 0,
        "total_adjustments_cents": 0,
        "demand_date": None,
        "due_date": None,
        "interest_frozen_at": None,
    })
    DB["overpayments"][o["id"]] = o
    return ok(ser_overpayment(o), 201)


@app.route("/fraud-recovery/overpayments/<oid>", methods=["GET"])
def get_overpayment(oid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    o = get_or_404("overpayments", oid)
    return ok(ser_overpayment(o))


@app.route("/fraud-recovery/overpayments", methods=["GET"])
def list_overpayments():
    uid, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = paginate_args()
    items = list(DB["overpayments"].values())
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    claim_type = request.args.get("claim_type")
    if case_id is not None:
        items = [o for o in items if o["case_id"] == case_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if claim_type is not None:
        items = [o for o in items if o["claim_type"] == claim_type]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_overpayment(o) for o in page], limit, offset, total)


@app.route("/fraud-recovery/overpayments/<oid>/months", methods=["POST"])
def add_month(oid):
    uid, role = authn()
    authz(role, {"Investigator"})
    o = get_or_404("overpayments", oid)
    body = get_body()
    benefit_month = require_str(body, "benefit_month")
    issued = require_int(body, "benefits_issued_cents")
    reported = require_int(body, "benefits_entitled_reported_cents")
    verified = require_int(body, "benefits_entitled_verified_cents")
    check_month_format(benefit_month)
    for m in DB["months"].values():
        if m["overpayment_id"] == oid and m["benefit_month"] == benefit_month:
            raise err("ERR_DUPLICATE_MONTH", 409, "Duplicate benefit_month")
    m = base_fields(with_version=False)
    m.update({
        "overpayment_id": oid,
        "benefit_month": benefit_month,
        "benefits_issued_cents": issued,
        "benefits_entitled_reported_cents": reported,
        "benefits_entitled_verified_cents": verified,
        "over_issuance_reported_cents": max(0, issued - reported),
        "over_issuance_verified_cents": max(0, issued - verified),
    })
    DB["months"][m["id"]] = m
    return ok(ser_month(m), 201)


@app.route("/fraud-recovery/overpayments/<oid>/months", methods=["GET"])
def list_months(oid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    get_or_404("overpayments", oid)
    limit, offset = paginate_args()
    items = [m for m in DB["months"].values() if m["overpayment_id"] == oid]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_month(m) for m in page], limit, offset, total)


@app.route("/fraud-recovery/overpayments/<oid>/calculate", methods=["POST"])
def calculate_overpayment(oid):
    uid, role = authn()
    authz(role, {"Investigator"})
    o = get_or_404("overpayments", oid)
    if o["status"] in OP_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", 409, "Overpayment already terminal")
    if o["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Overpayment not in DRAFT")
    months = [m for m in DB["months"].values() if m["overpayment_id"] == oid]
    if not months:
        raise err("ERR_NO_OVERPAYMENT_MONTHS", 422, "No overpayment months")
    provisional = sum(m["over_issuance_reported_cents"] for m in months)
    verified = sum(m["over_issuance_verified_cents"] for m in months)
    o["provisional_amount_cents"] = provisional
    o["final_amount_cents"] = verified + o["total_adjustments_cents"]
    o["status"] = "CALCULATED"
    touch(o)
    return ok(ser_overpayment(o))


@app.route("/fraud-recovery/overpayments/<oid>/establish", methods=["POST"])
def establish_overpayment(oid):
    uid, role = authn()
    authz(role, {"Supervisor"})
    o = get_or_404("overpayments", oid)
    if o["status"] in OP_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", 409, "Overpayment already terminal")
    if o["status"] != "CALCULATED":
        raise err("ERR_INVALID_STATE", 409, "Overpayment not in CALCULATED")
    case = DB["cases"].get(o["case_id"])
    if not case or case["status"] != "SUBSTANTIATED":
        raise err("ERR_CASE_NOT_SUBSTANTIATED", 409, "Linked case not SUBSTANTIATED")
    recompute_overpayment_final(o)
    threshold = (ESTABLISHMENT_THRESHOLD_IPV_CENTS if o["claim_type"] == "IPV"
                 else ESTABLISHMENT_THRESHOLD_NONIPV_CENTS)
    if o["final_amount_cents"] < threshold:
        raise err("ERR_BELOW_ESTABLISHMENT_THRESHOLD", 422, "Final amount below threshold")
    o["status"] = "ESTABLISHED"
    touch(o)
    return ok(ser_overpayment(o))


@app.route("/fraud-recovery/overpayments/<oid>/demand", methods=["POST"])
def demand_overpayment(oid):
    uid, role = authn()
    authz(role, {"RecoveryOfficer"})
    o = get_or_404("overpayments", oid)
    if o["status"] in OP_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", 409, "Overpayment already terminal")
    if o["status"] != "ESTABLISHED":
        raise err("ERR_INVALID_STATE", 409, "Overpayment not in ESTABLISHED")
    o["demand_date"] = CLOCK
    o["due_date"] = CLOCK + timedelta(days=PAYMENT_DUE_DAYS)
    o["status"] = "DEMANDED"
    touch(o)
    return ok(ser_overpayment(o))


@app.route("/fraud-recovery/overpayments/<oid>/adjustments", methods=["POST"])
def adjust_overpayment(oid):
    uid, role = authn()
    authz(role, {"Supervisor"})
    o = get_or_404("overpayments", oid)
    body = get_body()
    adjustment = require_int(body, "adjustment_amount_cents", allow_negative=True)
    require_str(body, "reason")
    expected = require_int(body, "expected_overpayment_version", allow_negative=True)
    if expected != o["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_overpayment_version is stale")
    o["total_adjustments_cents"] += adjustment
    recompute_overpayment_final(o)
    touch(o)
    return ok(ser_overpayment(o))


@app.route("/fraud-recovery/overpayments/<oid>/write-off", methods=["POST"])
def write_off_overpayment(oid):
    uid, role = authn()
    authz(role, {"Supervisor"})
    o = get_or_404("overpayments", oid)
    body = get_body()
    require_str(body, "reason")
    if o["status"] in OP_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", 409, "Overpayment already terminal")
    if o["status"] != "IN_RECOVERY":
        raise err("ERR_INVALID_STATE", 409, "Overpayment not in IN_RECOVERY")
    _, out_p, _, _, _ = op_balances(o)
    if out_p <= 0:
        raise err("ERR_INVALID_STATE", 409, "No outstanding principal to write off")
    o["interest_frozen_at"] = CLOCK
    o["status"] = "WRITTEN_OFF"
    touch(o)
    for p in DB["plans"].values():
        if p["overpayment_id"] == oid and p["status"] not in PLAN_TERMINAL:
            p["status"] = "CANCELLED"
            touch(p)
    return ok(ser_overpayment(o))


@app.route("/fraud-recovery/overpayments/<oid>/transactions", methods=["GET"])
def list_overpayment_transactions(oid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    get_or_404("overpayments", oid)
    limit, offset = paginate_args()
    items = [t for t in DB["transactions"].values() if t["overpayment_id"] == oid]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_tx(t) for t in page], limit, offset, total)


# =============================================================================
# ROUTES — Disqualification
# =============================================================================
@app.route("/fraud-recovery/disqualifications", methods=["POST"])
def create_disqualification():
    uid, role = authn()
    authz(role, {"Investigator"})
    body = get_body()
    case_id = require_str(body, "case_id")
    case = get_or_404("cases", case_id)
    status, _ = subject_derived(case["subject_id"])
    if status in ("DISQUALIFIED", "PERMANENTLY_DISQUALIFIED"):
        raise err("ERR_SUBJECT_ALREADY_DISQUALIFIED", 409, "Subject already disqualified")
    d = base_fields()
    d.update({
        "case_id": case_id,
        "subject_id": case["subject_id"],
        "status": "PROPOSED",
        "penalty_months": None,
        "is_permanent": False,
        "imposed_at": None,
        "disqualified_until": None,
    })
    DB["disqualifications"][d["id"]] = d
    return ok(ser_disq(d), 201)


@app.route("/fraud-recovery/disqualifications/<did>", methods=["GET"])
def get_disqualification(did):
    uid, role = authn()
    authz(role, ALL_ROLES)
    d = get_or_404("disqualifications", did)
    return ok(ser_disq(d))


@app.route("/fraud-recovery/disqualifications", methods=["GET"])
def list_disqualifications():
    uid, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = paginate_args()
    items = list(DB["disqualifications"].values())
    case_id = request.args.get("case_id")
    sid = request.args.get("subject_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    if sid is not None:
        items = [d for d in items if d["subject_id"] == sid]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_disq(d) for d in page], limit, offset, total)


@app.route("/fraud-recovery/disqualifications/<did>/refer-adh", methods=["POST"])
def refer_adh(did):
    uid, role = authn()
    authz(role, {"Investigator"})
    d = get_or_404("disqualifications", did)
    if d["status"] in ("DECLINED", "RESCINDED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Disqualification already terminal")
    if d["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", 409, "Disqualification not in PROPOSED")
    case = DB["cases"].get(d["case_id"])
    if not case or case["status"] != "SUBSTANTIATED":
        raise err("ERR_CASE_NOT_SUBSTANTIATED", 409, "Linked case not SUBSTANTIATED")
    d["status"] = "ADH_REFERRED"
    touch(d)
    return ok(ser_disq(d))


@app.route("/fraud-recovery/disqualifications/<did>/rescind", methods=["POST"])
def rescind_disqualification(did):
    uid, role = authn()
    authz(role, {"Supervisor"})
    d = get_or_404("disqualifications", did)
    body = get_body()
    require_str(body, "reason")
    if d["status"] in ("DECLINED", "RESCINDED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Disqualification already terminal")
    if d["status"] != "IMPOSED":
        raise err("ERR_INVALID_STATE", 409, "Disqualification not in IMPOSED")
    d["status"] = "RESCINDED"
    d["disqualified_until"] = None
    touch(d)
    subject = DB["subjects"].get(d["subject_id"])
    if subject:
        subject["prior_ipv_count"] = max(0, subject["prior_ipv_count"] - 1)
        touch(subject)
    return ok(ser_disq(d))


# =============================================================================
# ROUTES — Hearing
# =============================================================================
@app.route("/fraud-recovery/hearings", methods=["POST"])
def create_hearing():
    uid, role = authn()
    authz(role, {"Adjudicator"})
    body = get_body()
    disqualification_id = require_str(body, "disqualification_id")
    d = get_or_404("disqualifications", disqualification_id)
    scheduled_date = require_str(body, "scheduled_date")
    check_datetime_format(scheduled_date, "scheduled_date")
    if d["status"] != "ADH_REFERRED":
        raise err("ERR_ADH_NOT_REFERRED", 409, "Disqualification not ADH_REFERRED")
    h = base_fields()
    h.update({
        "disqualification_id": disqualification_id,
        "scheduled_date": scheduled_date,
        "status": "SCHEDULED",
        "outcome": None,
        "held_at": None,
        "decided_by_user_id": None,
    })
    DB["hearings"][h["id"]] = h
    return ok(ser_hearing(h), 201)


@app.route("/fraud-recovery/hearings/<hid>", methods=["GET"])
def get_hearing(hid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    h = get_or_404("hearings", hid)
    return ok(ser_hearing(h))


@app.route("/fraud-recovery/hearings", methods=["GET"])
def list_hearings():
    uid, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = paginate_args()
    items = list(DB["hearings"].values())
    dq = request.args.get("disqualification_id")
    status = request.args.get("status")
    if dq is not None:
        items = [h for h in items if h["disqualification_id"] == dq]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_hearing(h) for h in page], limit, offset, total)


@app.route("/fraud-recovery/hearings/<hid>/hold", methods=["POST"])
def hold_hearing(hid):
    uid, role = authn()
    authz(role, {"Adjudicator"})
    h = get_or_404("hearings", hid)
    if h["status"] in ("DECIDED_IPV", "DECIDED_NO_IPV", "DISMISSED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Hearing already terminal")
    if h["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", 409, "Hearing not in SCHEDULED")
    h["status"] = "HELD"
    h["held_at"] = CLOCK
    touch(h)
    return ok(ser_hearing(h))


@app.route("/fraud-recovery/hearings/<hid>/decide", methods=["POST"])
def decide_hearing(hid):
    uid, role = authn()
    authz(role, {"Adjudicator"})
    h = get_or_404("hearings", hid)
    body = get_body()
    outcome = require_str(body, "outcome")
    check_enum(outcome, HEARING_OUTCOMES, "outcome")
    if h["status"] in ("DECIDED_IPV", "DECIDED_NO_IPV", "DISMISSED"):
        raise err("ERR_ALREADY_TERMINAL", 409, "Hearing already terminal")
    if h["status"] != "HELD":
        raise err("ERR_INVALID_STATE", 409, "Hearing not in HELD")
    d = DB["disqualifications"].get(h["disqualification_id"])
    case = DB["cases"].get(d["case_id"]) if d else None
    # Segregation of duties.
    if case and case.get("assigned_investigator_id") == uid:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403,
                  "Adjudicator may not be the case's assigned investigator")
    h["decided_by_user_id"] = uid
    if outcome == "IPV":
        h["status"] = "DECIDED_IPV"
        h["outcome"] = "IPV"
        if d and d["status"] == "ADH_REFERRED":
            impose_cascade(d)
    elif outcome == "NO_IPV":
        h["status"] = "DECIDED_NO_IPV"
        h["outcome"] = "NO_IPV"
        if d and d["status"] == "ADH_REFERRED":
            d["status"] = "DECLINED"
            touch(d)
    else:  # DISMISSED
        h["status"] = "DISMISSED"
        h["outcome"] = "DISMISSED"
        if d and d["status"] == "ADH_REFERRED":
            d["status"] = "DECLINED"
            touch(d)
    touch(h)
    return ok(ser_hearing(h))


# =============================================================================
# ROUTES — Recovery Plans / Transactions
# =============================================================================
def _ranges_overlap(s1, e1, s2, e2):
    # Half-open [start, end); None end == +infinity.
    lo = max(s1, s2)
    hi = None
    if e1 is not None and e2 is not None:
        hi = min(e1, e2)
    elif e1 is not None:
        hi = e1
    elif e2 is not None:
        hi = e2
    if hi is None:
        return True
    return lo < hi


@app.route("/fraud-recovery/recovery-plans", methods=["POST"])
def create_recovery_plan():
    uid, role = authn()
    authz(role, {"RecoveryOfficer"})
    body = get_body()
    overpayment_id = require_str(body, "overpayment_id")
    o = get_or_404("overpayments", overpayment_id)
    method = require_str(body, "method")
    start_date = require_str(body, "start_date")
    check_enum(method, PLAN_METHODS, "method")
    end_date = body.get("end_date")
    monthly_allotment = optional_int(body, "monthly_allotment_cents")
    scheduled_monthly = optional_int(body, "scheduled_monthly_cents")
    check_date_format(start_date, "start_date")
    if end_date is not None:
        check_date_format(end_date, "end_date")
    if method == "RECOUPMENT" and monthly_allotment is None:
        raise err("ERR_VALIDATION", 400, "monthly_allotment_cents required for RECOUPMENT")
    # Cross-entity precondition.
    if o["status"] != "DEMANDED":
        raise err("ERR_OVERPAYMENT_NOT_DEMANDED", 409, "Overpayment not DEMANDED")
    # Resolve subject via overpayment -> case -> subject.
    case = DB["cases"].get(o["case_id"])
    subject_id = case["subject_id"] if case else None
    # Overlap check (only RECOUPMENT vs existing ACTIVE RECOUPMENT plans of same subject).
    if method == "RECOUPMENT":
        for p in DB["plans"].values():
            if (p["method"] == "RECOUPMENT" and p["status"] == "ACTIVE"
                    and p["subject_id"] == subject_id):
                if _ranges_overlap(start_date, end_date, p["start_date"], p["end_date"]):
                    raise err("ERR_OVERLAPPING_RECOVERY_PLAN", 409, "Overlapping recovery plan")
    p = base_fields()
    p.update({
        "overpayment_id": overpayment_id,
        "subject_id": subject_id,
        "method": method,
        "start_date": start_date,
        "end_date": end_date,
        "monthly_allotment_cents": monthly_allotment,
        "scheduled_monthly_cents": scheduled_monthly,
        "status": "ACTIVE",
    })
    DB["plans"][p["id"]] = p
    o["status"] = "IN_RECOVERY"
    touch(o)
    return ok(ser_plan(p), 201)


@app.route("/fraud-recovery/recovery-plans/<pid>", methods=["GET"])
def get_recovery_plan(pid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    p = get_or_404("plans", pid)
    return ok(ser_plan(p))


@app.route("/fraud-recovery/recovery-plans", methods=["GET"])
def list_recovery_plans():
    uid, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = paginate_args()
    items = list(DB["plans"].values())
    op = request.args.get("overpayment_id")
    sid = request.args.get("subject_id")
    status = request.args.get("status")
    if op is not None:
        items = [p for p in items if p["overpayment_id"] == op]
    if sid is not None:
        items = [p for p in items if p["subject_id"] == sid]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_plan(p) for p in page], limit, offset, total)


@app.route("/fraud-recovery/recovery-plans/<pid>/default", methods=["POST"])
def default_recovery_plan(pid):
    uid, role = authn()
    authz(role, {"RecoveryOfficer"})
    p = get_or_404("plans", pid)
    if p["status"] in PLAN_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", 409, "Plan already terminal")
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "Plan not ACTIVE")
    o = DB["overpayments"].get(p["overpayment_id"])
    _, out_p, _, _, _ = op_balances(o) if o else (0, 0, 0, 0, 0)
    due = o.get("due_date") if o else None
    if due is None or not (CLOCK > due) or out_p <= 0:
        raise err("ERR_INVALID_STATE", 409, "Default preconditions not met")
    p["status"] = "DEFAULTED"
    touch(p)
    return ok(ser_plan(p))


@app.route("/fraud-recovery/recovery-transactions", methods=["POST"])
def create_transaction():
    uid, role = authn()
    authz(role, {"RecoveryOfficer"})
    body = get_body()
    recovery_plan_id = require_str(body, "recovery_plan_id")
    p = get_or_404("plans", recovery_plan_id)
    amount = require_int(body, "amount_cents")
    transaction_date = require_str(body, "transaction_date")
    method = require_str(body, "method")
    check_enum(method, TX_METHODS, "method")
    check_date_format(transaction_date, "transaction_date")
    o = DB["overpayments"].get(p["overpayment_id"])
    # Plan/overpayment state gate.
    if p["status"] in PLAN_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", 409, "Plan already terminal")
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "Plan not ACTIVE")
    # Temporal: transaction_date on/after plan start_date.
    if transaction_date < p["start_date"]:
        raise err("ERR_TRANSACTION_BEFORE_PLAN_START", 422, "transaction_date before plan start")
    # Fiscal: amount must not exceed total outstanding balance.
    accrued, out_p, out_i, _, _ = op_balances(o)
    out_p = max(0, out_p)
    out_i = max(0, out_i)
    total_outstanding = out_p + out_i
    if amount > total_outstanding:
        raise err("ERR_AMOUNT_EXCEEDS_BALANCE", 422, "amount_cents exceeds outstanding balance")
    applied_interest = min(amount, out_i)
    applied_principal = amount - applied_interest
    t = base_fields()
    t.update({
        "recovery_plan_id": recovery_plan_id,
        "overpayment_id": o["id"],
        "amount_cents": amount,
        "transaction_date": transaction_date,
        "method": method,
        "applied_to_interest_cents": applied_interest,
        "applied_to_principal_cents": applied_principal,
        "status": "POSTED",
    })
    DB["transactions"][t["id"]] = t
    maybe_satisfy(o)
    return ok(ser_tx(t), 201)


@app.route("/fraud-recovery/recovery-plans/<pid>/transactions", methods=["GET"])
def list_plan_transactions(pid):
    uid, role = authn()
    authz(role, ALL_ROLES)
    get_or_404("plans", pid)
    limit, offset = paginate_args()
    items = [t for t in DB["transactions"].values() if t["recovery_plan_id"] == pid]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([ser_tx(t) for t in page], limit, offset, total)


@app.route("/fraud-recovery/recovery-transactions/<tid>/void", methods=["POST"])
def void_transaction(tid):
    uid, role = authn()
    authz(role, {"RecoveryOfficer"})
    t = get_or_404("transactions", tid)
    get_body()  # optional reason
    if t["status"] == "VOIDED":
        raise err("ERR_ALREADY_VOIDED", 409, "Transaction already voided")
    o = DB["overpayments"].get(t["overpayment_id"])
    if not o or o["status"] != "IN_RECOVERY":
        raise err("ERR_INVALID_STATE", 409, "Void only permitted while overpayment IN_RECOVERY")
    t["status"] = "VOIDED"
    touch(t)
    return ok(ser_tx(t))


# =============================================================================
# ROUTES — Reporting
# =============================================================================
@app.route("/fraud-recovery/reports/recovery-summary", methods=["GET"])
def recovery_summary():
    uid, role = authn()
    authz(role, {"Supervisor"})
    program = request.args.get("program")
    claim_type = request.args.get("claim_type")
    total_final = 0
    total_interest = 0
    total_recovered_principal = 0
    total_outstanding = 0
    count = 0
    for o in DB["overpayments"].values():
        if claim_type is not None and o["claim_type"] != claim_type:
            continue
        if program is not None:
            case = DB["cases"].get(o["case_id"])
            if not case or case["program"] != program:
                continue
        accrued, out_p, out_i, applied_p, _ = op_balances(o)
        count += 1
        total_final += o["final_amount_cents"]
        total_interest += accrued
        total_recovered_principal += applied_p
        total_outstanding += max(0, out_p) + max(0, out_i)
    data = {
        "total_final_amount_cents": total_final,
        "total_accrued_interest_cents": total_interest,
        "total_recovered_principal_cents": total_recovered_principal,
        "total_outstanding_cents": total_outstanding,
        "overpayment_count": count,
    }
    return ok(data)


# =============================================================================
# ROUTES — Logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    uid, role = authn()
    authz(role, {"Supervisor"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    parsed = parse_iso_dt(to_iso)
    if parsed is None:
        raise err("ERR_INVALID_MONTH_FORMAT", 422, "to_iso8601 must be ISO 8601")
    if parsed < CLOCK:
        raise err("ERR_CLOCK_BACKWARDS", 422, "Clock may not move backwards")
    CLOCK = parsed
    return ok({"current_utc": iso(CLOCK)})


# =============================================================================
# Health
# =============================================================================
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
