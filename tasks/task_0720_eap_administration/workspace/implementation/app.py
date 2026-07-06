import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify, g

from errors import ApiError, err

app = Flask(__name__)

# ============================================================================
# Logical clock
# ============================================================================
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"


class Clock:
    def __init__(self):
        self.now_dt = parse_iso(CLOCK_DEFAULT)

    def set(self, iso):
        self.now_dt = parse_iso(iso)

    def now(self):
        return self.now_dt


def parse_iso(s):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", "invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


# ============================================================================
# In-memory store
# ============================================================================
class DB:
    def __init__(self):
        self.contracts = {}
        self.plans = {}
        self.employees = {}
        self.dependents = {}
        self.cases = {}
        self.sessions = {}
        self.providers = {}
        self.referrals = {}
        self.crisis = {}
        self.claims = {}
        self.wellness = {}
        self.reports = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()
clock = Clock()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def common_fields_new():
    now = clock.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = clock.now()
    if "version" in rec:
        rec["version"] += 1


# ============================================================================
# Response envelope
# ============================================================================
def meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_iso(clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def err_response(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(err("ERR_NOT_FOUND", "resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return err_response(err("ERR_NOT_FOUND", "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError("ERR_INVALID_REQUEST", 422, str(e)))


# ============================================================================
# Auth / RBAC
# ============================================================================
ROLES = {"ProgramAdmin", "CareCoordinator", "CrisisCounselor", "Provider", "Employer"}


def get_auth():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or unrecognized X-User-Role")
    return role, user_id


def require_role(allowed):
    role, user_id = get_auth()
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "role %s not permitted" % role)
    return role, user_id


# ============================================================================
# Body / param helpers
# ============================================================================
def get_body():
    if request.data and len(request.data) > 0:
        try:
            b = request.get_json(force=True, silent=True)
        except Exception:
            b = None
    else:
        b = request.get_json(force=True, silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
    return b


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % f)


def as_int(val, name, minv=None, maxv=None):
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minv is not None and val < minv:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minv))
    if maxv is not None and val > maxv:
        raise err("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maxv))
    return val


def check_enum(val, name, allowed):
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, sorted(allowed)))
    return val


def pagination_params():
    args = request.args
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items):
    items = sorted(items, key=lambda r: r["_seq"])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


def list_response(records, serializer):
    page, pag = paginate(records)
    data = [serializer(r) for r in page]
    return ok(data, 200, "array", pag)


# ============================================================================
# Computed helpers
# ============================================================================
def contract_sessions_committed(contract_id, completed_only=False):
    count = 0
    statuses = {"COMPLETED"} if completed_only else {"SCHEDULED", "COMPLETED"}
    for s in db.sessions.values():
        case = db.cases.get(s["case_id"])
        if not case:
            continue
        if case["contract_id"] == contract_id and s["status"] in statuses:
            count += 1
    return count


def utilization_rate(committed, cap):
    if cap == 0:
        return 0.0
    q = (Decimal(committed) / Decimal(cap)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def case_sessions_used(case_id):
    return sum(
        1 for s in db.sessions.values()
        if s["case_id"] == case_id and s["status"] in ("SCHEDULED", "COMPLETED")
    )


def employee_worklife_used(employee_id):
    count = 0
    for r in db.referrals.values():
        if r["employee_id"] != employee_id:
            continue
        if r["referral_type"] in ("WORKLIFE", "LEGAL", "FINANCIAL") and r["status"] not in ("CANCELLED", "DENIED"):
            count += 1
    return count


def provider_active_referral_count(provider_id):
    return sum(
        1 for r in db.referrals.values()
        if r["provider_id"] == provider_id and r["status"] in ("REQUESTED", "ACCEPTED")
    )


# ============================================================================
# Serializers
# ============================================================================
def base_ser(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_iso(rec["created_at"]),
        "updated_at": fmt_iso(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_contract(c):
    committed = contract_sessions_committed(c["id"])
    d = base_ser(c)
    d.update({
        "employer_name": c["employer_name"],
        "sessions_per_issue": c["sessions_per_issue"],
        "annual_session_cap": c["annual_session_cap"],
        "crisis_sla_minutes": c["crisis_sla_minutes"],
        "session_rate_cents": c["session_rate_cents"],
        "annual_reimbursement_budget_cents": c["annual_reimbursement_budget_cents"],
        "reporting_min_cohort": c["reporting_min_cohort"],
        "status": c["status"],
        "sessions_committed": committed,
        "utilization_rate": utilization_rate(committed, c["annual_session_cap"]),
    })
    return d


def ser_contract_with_basis(c, basis):
    committed_only = basis == "verified"
    committed = contract_sessions_committed(c["id"], completed_only=committed_only)
    d = ser_contract(c)
    d["sessions_committed"] = committed
    d["utilization_rate"] = utilization_rate(committed, c["annual_session_cap"])
    return d


def ser_plan(p):
    d = base_ser(p)
    d.update({
        "contract_id": p["contract_id"],
        "name": p["name"],
        "worklife_referrals_per_year": p["worklife_referrals_per_year"],
        "copay_cents": p["copay_cents"],
        "status": p["status"],
    })
    return d


def ser_employee(e):
    d = base_ser(e)
    d.update({
        "contract_id": e["contract_id"],
        "plan_id": e["plan_id"],
        "full_name": e["full_name"],
        "external_ref": e["external_ref"],
        "eligibility_status": e["eligibility_status"],
        "grace_until": fmt_iso(e["grace_until"]) if e["grace_until"] else None,
        "worklife_referrals_used": employee_worklife_used(e["id"]),
    })
    return d


def ser_dependent(d_):
    out = base_ser(d_)
    out.update({
        "employee_id": d_["employee_id"],
        "full_name": d_["full_name"],
        "relationship": d_["relationship"],
        "eligibility_status": d_["eligibility_status"],
    })
    return out


def ser_case(c):
    used = case_sessions_used(c["id"])
    if c["funding_status"] == "EXHAUSTED":
        remaining = 0
    else:
        allot = c["session_allotment"] if c["session_allotment"] is not None else 0
        remaining = max(0, allot - used)
    d = base_ser(c)
    d.update({
        "contract_id": c["contract_id"],
        "employee_id": c["employee_id"],
        "dependent_id": c["dependent_id"],
        "presenting_issue": c["presenting_issue"],
        "clinical_status": c["clinical_status"],
        "funding_status": c["funding_status"],
        "session_allotment": c["session_allotment"],
        "sessions_used": used,
        "sessions_remaining": remaining,
    })
    return d


def ser_session(s):
    d = base_ser(s)
    d.update({
        "case_id": s["case_id"],
        "provider_id": s["provider_id"],
        "scheduled_for": fmt_iso(s["scheduled_for"]),
        "duration_minutes": s["duration_minutes"],
        "status": s["status"],
    })
    return d


def ser_provider(p):
    d = base_ser(p)
    d.update({
        "full_name": p["full_name"],
        "network_status": p["network_status"],
        "specialties": list(p["specialties"]),
        "accepting": p["accepting"],
        "active_referral_count": provider_active_referral_count(p["id"]),
    })
    return d


def ser_referral(r):
    d = base_ser(r)
    d.update({
        "case_id": r["case_id"],
        "employee_id": r["employee_id"],
        "provider_id": r["provider_id"],
        "referral_type": r["referral_type"],
        "status": r["status"],
    })
    return d


def crisis_sla_breached(cc):
    contract = db.contracts.get(cc["contract_id"])
    sla = contract["crisis_sla_minutes"] if contract else 15
    if cc["triaged_at"] is not None:
        elapsed = cc["triaged_at"] - cc["opened_at"]
    else:
        elapsed = clock.now() - cc["opened_at"]
    elapsed_min = int(elapsed.total_seconds() // 60)
    return elapsed_min > sla


def ser_crisis(cc):
    d = base_ser(cc)
    d.update({
        "contract_id": cc["contract_id"],
        "employee_id": cc["employee_id"],
        "opened_at": fmt_iso(cc["opened_at"]),
        "severity": cc["severity"],
        "triaged_at": fmt_iso(cc["triaged_at"]) if cc["triaged_at"] else None,
        "sla_breached": crisis_sla_breached(cc),
        "status": cc["status"],
        "disposition": cc["disposition"],
    })
    return d


def ser_claim(c):
    d = base_ser(c)
    d.update({
        "contract_id": c["contract_id"],
        "session_id": c["session_id"],
        "provider_id": c["provider_id"],
        "billed_cents": c["billed_cents"],
        "provisional_cents": c["provisional_cents"],
        "final_cents": c["final_cents"],
        "status": c["status"],
    })
    return d


def ser_wellness(w):
    d = base_ser(w)
    d.update({
        "employee_id": w["employee_id"],
        "activity_type": w["activity_type"],
        "points": w["points"],
        "completed_on": fmt_iso(w["completed_on"]),
    })
    return d


def ser_report(r):
    return {
        "id": r["id"],
        "created_at": fmt_iso(r["created_at"]),
        "contract_id": r["contract_id"],
        "period_start": fmt_iso(r["period_start"]),
        "period_end": fmt_iso(r["period_end"]),
        "total_cases": r["total_cases"],
        "distinct_employees": r["distinct_employees"],
        "issue_breakdown": r["issue_breakdown"],
        "suppressed": r["suppressed"],
    }


# ============================================================================
# Lookups
# ============================================================================
def get_or_404(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return rec


PRESENTING_ISSUES = {"STRESS", "RELATIONSHIP", "SUBSTANCE", "GRIEF", "FINANCIAL_STRESS", "OTHER"}

# ============================================================================
# Calculations
# ============================================================================
OON_FACTOR_NUM = 7
OON_FACTOR_DEN = 10


def claim_provisional(claim):
    session = db.sessions.get(claim["session_id"])
    provider = db.providers.get(claim["provider_id"])
    contract = db.contracts.get(claim["contract_id"])
    case = db.cases.get(session["case_id"]) if session else None
    plan = None
    employee = None
    if case:
        employee = db.employees.get(case["employee_id"])
    if employee:
        plan = db.plans.get(employee["plan_id"])
    copay = plan["copay_cents"] if plan else 0

    base = contract["session_rate_cents"]
    if provider and provider["network_status"] == "OUT_OF_NETWORK":
        base = (base * OON_FACTOR_NUM) // OON_FACTOR_DEN  # floor
    gross = min(claim["billed_cents"], base)
    return max(0, gross - copay)


def claim_final(claim):
    contract_id = claim["contract_id"]
    contract = db.contracts.get(contract_id)
    others = [
        c for c in db.claims.values()
        if c["contract_id"] == contract_id
        and c["id"] != claim["id"]
        and c["status"] in ("APPROVED", "PAID")
    ]
    others.sort(key=lambda c: c["_seq"])
    spent = sum((c["final_cents"] or 0) for c in others)
    remaining = max(0, contract["annual_reimbursement_budget_cents"] - spent)
    return min(claim["provisional_cents"], remaining)


def select_provider(required_specialty, excluded_id=None):
    candidates = []
    for p in db.providers.values():
        if not p["accepting"]:
            continue
        if p["network_status"] != "IN_NETWORK":
            continue
        if required_specialty not in p["specialties"]:
            continue
        if excluded_id is not None and p["id"] == excluded_id:
            continue
        candidates.append(p)
    if not candidates:
        raise err("ERR_NO_PROVIDER_AVAILABLE", "no provider available")
    candidates.sort(key=lambda p: (provider_active_referral_count(p["id"]), p["created_at"], p["_seq"]))
    return candidates[0]


# ============================================================================
# Clock endpoint
# ============================================================================
@app.route("/eap/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role({"ProgramAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    clock.set(body["to_iso8601"])
    return ok({}, 200)


# ============================================================================
# EmployerContract
# ============================================================================
@app.route("/eap/contracts", methods=["POST"])
def create_contract():
    require_role({"ProgramAdmin"})
    body = get_body()
    require_fields(body, ["employer_name", "sessions_per_issue", "annual_session_cap",
                          "session_rate_cents", "annual_reimbursement_budget_cents"])
    if not isinstance(body["employer_name"], str):
        raise err("ERR_INVALID_REQUEST", "employer_name must be a string")
    spi = as_int(body["sessions_per_issue"], "sessions_per_issue", 1, 12)
    cap = as_int(body["annual_session_cap"], "annual_session_cap", 1)
    rate = as_int(body["session_rate_cents"], "session_rate_cents", 0)
    budget = as_int(body["annual_reimbursement_budget_cents"], "annual_reimbursement_budget_cents", 0)
    sla = body.get("crisis_sla_minutes", 15)
    if sla is None:
        sla = 15
    sla = as_int(sla, "crisis_sla_minutes", 1)
    cohort = body.get("reporting_min_cohort", 5)
    if cohort is None:
        cohort = 5
    cohort = as_int(cohort, "reporting_min_cohort", 1)

    c = common_fields_new()
    c.update({
        "employer_name": body["employer_name"],
        "sessions_per_issue": spi,
        "annual_session_cap": cap,
        "crisis_sla_minutes": sla,
        "session_rate_cents": rate,
        "annual_reimbursement_budget_cents": budget,
        "reporting_min_cohort": cohort,
        "status": "ACTIVE",
    })
    db.contracts[c["id"]] = c
    return ok(ser_contract(c), 201)


@app.route("/eap/contracts", methods=["GET"])
def list_contracts():
    require_role({"ProgramAdmin"})
    status = request.args.get("status")
    items = [c for c in db.contracts.values() if status is None or c["status"] == status]
    return list_response(items, ser_contract)


@app.route("/eap/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_role({"ProgramAdmin", "Employer"})
    c = get_or_404(db.contracts, cid)
    return ok(ser_contract(c), 200)


@app.route("/eap/contracts/<cid>/utilization", methods=["GET"])
def get_contract_utilization(cid):
    require_role({"ProgramAdmin", "Employer"})
    c = get_or_404(db.contracts, cid)
    basis = request.args.get("basis", "committed")
    if basis not in ("committed", "verified"):
        raise err("ERR_INVALID_REQUEST", "basis must be committed or verified")
    return ok(ser_contract_with_basis(c, basis), 200)


def revoke_cascade_for_case(case):
    """hop 2: cancel SCHEDULED sessions; hop 3: reject SUBMITTED/UNDER_REVIEW claims."""
    for s in db.sessions.values():
        if s["case_id"] == case["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
            # sessions_committed is computed; cancelling removes it from the count.
            for cl in db.claims.values():
                if cl["session_id"] == s["id"] and cl["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                    cl["status"] = "REJECTED"
                    touch(cl)


def contract_revoke_cascade(contract):
    for case in db.cases.values():
        if case["contract_id"] == contract["id"] and case["funding_status"] == "AUTHORIZED":
            case["funding_status"] = "REVOKED"
            touch(case)
            revoke_cascade_for_case(case)


def check_occ(contract, body):
    require_fields(body, ["expected_contract_version"])
    ecv = body["expected_contract_version"]
    if isinstance(ecv, bool) or not isinstance(ecv, int):
        raise err("ERR_INVALID_REQUEST", "expected_contract_version must be an integer")
    if ecv != contract["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", "stale contract version")


@app.route("/eap/contracts/<cid>/suspend", methods=["POST"])
def suspend_contract(cid):
    require_role({"ProgramAdmin"})
    c = get_or_404(db.contracts, cid)
    body = get_body()
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "contract not ACTIVE")
    check_occ(c, body)
    c["status"] = "SUSPENDED"
    touch(c)
    contract_revoke_cascade(c)
    return ok(ser_contract(c), 200)


@app.route("/eap/contracts/<cid>/reinstate", methods=["POST"])
def reinstate_contract(cid):
    require_role({"ProgramAdmin"})
    c = get_or_404(db.contracts, cid)
    body = get_body()
    if c["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "contract not SUSPENDED")
    check_occ(c, body)
    c["status"] = "ACTIVE"
    touch(c)
    return ok(ser_contract(c), 200)


@app.route("/eap/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    require_role({"ProgramAdmin"})
    c = get_or_404(db.contracts, cid)
    body = get_body()
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "contract not ACTIVE or SUSPENDED")
    check_occ(c, body)
    was_active = c["status"] == "ACTIVE"
    c["status"] = "TERMINATED"
    touch(c)
    if was_active:
        contract_revoke_cascade(c)
    else:
        # from SUSPENDED: cascade already fired at suspend; spec lists no cascade here
        pass
    return ok(ser_contract(c), 200)


# ============================================================================
# Reports
# ============================================================================
@app.route("/eap/contracts/<cid>/reports", methods=["POST"])
def build_report(cid):
    require_role({"ProgramAdmin", "Employer"})
    c = get_or_404(db.contracts, cid)
    body = get_body()
    require_fields(body, ["period_start", "period_end"])
    ps = parse_iso(body["period_start"])
    pe = parse_iso(body["period_end"])
    if not (ps < pe):
        raise err("ERR_INVALID_WINDOW", "period_start must be before period_end")

    window = [
        case for case in db.cases.values()
        if case["contract_id"] == cid and ps <= case["created_at"] < pe
    ]
    total_cases = len(window)
    distinct_emps = len(set(case["employee_id"] for case in window))
    min_cohort = c["reporting_min_cohort"]

    if distinct_emps < min_cohort:
        suppressed = True
        issue_breakdown = {issue: -1 for issue in PRESENTING_ISSUES}
    else:
        suppressed = False
        issue_breakdown = {}
        for issue in PRESENTING_ISSUES:
            cell_cases = [case for case in window if case["presenting_issue"] == issue]
            cell_distinct = len(set(case["employee_id"] for case in cell_cases))
            if cell_distinct < min_cohort:
                issue_breakdown[issue] = -1
            else:
                issue_breakdown[issue] = len(cell_cases)

    r = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": db.next_seq(),
        "contract_id": cid,
        "period_start": ps,
        "period_end": pe,
        "total_cases": total_cases,
        "distinct_employees": distinct_emps,
        "issue_breakdown": issue_breakdown,
        "suppressed": suppressed,
    }
    db.reports[r["id"]] = r
    return ok(ser_report(r), 201)


@app.route("/eap/reports", methods=["GET"])
def list_reports():
    require_role({"ProgramAdmin", "Employer"})
    contract_id = request.args.get("contract_id")
    items = [r for r in db.reports.values() if contract_id is None or r["contract_id"] == contract_id]
    return list_response(items, ser_report)


@app.route("/eap/reports/<rid>", methods=["GET"])
def get_report(rid):
    require_role({"ProgramAdmin", "Employer"})
    r = get_or_404(db.reports, rid)
    return ok(ser_report(r), 200)


# ============================================================================
# BenefitPlan
# ============================================================================
@app.route("/eap/plans", methods=["POST"])
def create_plan():
    require_role({"ProgramAdmin"})
    body = get_body()
    require_fields(body, ["contract_id", "name"])
    contract = db.contracts.get(body["contract_id"])
    if contract is None:
        raise err("ERR_NOT_FOUND", "contract not found")
    if not isinstance(body["name"], str):
        raise err("ERR_INVALID_REQUEST", "name must be a string")
    wl = body.get("worklife_referrals_per_year", 3)
    if wl is None:
        wl = 3
    wl = as_int(wl, "worklife_referrals_per_year", 0)
    copay = body.get("copay_cents", 0)
    if copay is None:
        copay = 0
    copay = as_int(copay, "copay_cents", 0)

    p = common_fields_new()
    p.update({
        "contract_id": body["contract_id"],
        "name": body["name"],
        "worklife_referrals_per_year": wl,
        "copay_cents": copay,
        "status": "DRAFT",
    })
    db.plans[p["id"]] = p
    return ok(ser_plan(p), 201)


@app.route("/eap/plans", methods=["GET"])
def list_plans():
    require_role({"ProgramAdmin", "Employer"})
    contract_id = request.args.get("contract_id")
    items = [p for p in db.plans.values() if contract_id is None or p["contract_id"] == contract_id]
    return list_response(items, ser_plan)


@app.route("/eap/plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_role({"ProgramAdmin", "Employer"})
    p = get_or_404(db.plans, pid)
    return ok(ser_plan(p), 200)


@app.route("/eap/plans/<pid>/publish", methods=["POST"])
def publish_plan(pid):
    require_role({"ProgramAdmin"})
    p = get_or_404(db.plans, pid)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "plan not DRAFT")
    p["status"] = "PUBLISHED"
    touch(p)
    return ok(ser_plan(p), 200)


# ============================================================================
# Employee
# ============================================================================
@app.route("/eap/employees", methods=["POST"])
def create_employee():
    require_role({"ProgramAdmin"})
    body = get_body()
    require_fields(body, ["contract_id", "plan_id", "full_name", "external_ref"])
    contract = db.contracts.get(body["contract_id"])
    if contract is None:
        raise err("ERR_NOT_FOUND", "contract not found")
    plan = db.plans.get(body["plan_id"])
    if plan is None:
        raise err("ERR_NOT_FOUND", "plan not found")
    if not isinstance(body["full_name"], str) or not isinstance(body["external_ref"], str):
        raise err("ERR_INVALID_REQUEST", "full_name and external_ref must be strings")
    # referential: plan belongs to contract
    if plan["contract_id"] != body["contract_id"]:
        raise err("ERR_REFERENTIAL_MISMATCH", "plan does not belong to contract")
    # plan must be published
    if plan["status"] != "PUBLISHED":
        raise err("ERR_PLAN_NOT_PUBLISHED", "plan not published")
    # unique external_ref within contract
    for e in db.employees.values():
        if e["contract_id"] == body["contract_id"] and e["external_ref"] == body["external_ref"]:
            raise err("ERR_DUPLICATE_EXTERNAL_REF", "external_ref already exists in contract")

    e = common_fields_new()
    e.update({
        "contract_id": body["contract_id"],
        "plan_id": body["plan_id"],
        "full_name": body["full_name"],
        "external_ref": body["external_ref"],
        "eligibility_status": "ELIGIBLE",
        "grace_until": None,
    })
    db.employees[e["id"]] = e
    return ok(ser_employee(e), 201)


@app.route("/eap/employees", methods=["GET"])
def list_employees():
    require_role({"ProgramAdmin", "CareCoordinator"})
    contract_id = request.args.get("contract_id")
    plan_id = request.args.get("plan_id")
    items = [
        e for e in db.employees.values()
        if (contract_id is None or e["contract_id"] == contract_id)
        and (plan_id is None or e["plan_id"] == plan_id)
    ]
    return list_response(items, ser_employee)


@app.route("/eap/employees/<eid>", methods=["GET"])
def get_employee(eid):
    role, _ = require_role({"ProgramAdmin", "CareCoordinator", "Employer"})
    if role == "Employer":
        raise err("ERR_CONFIDENTIALITY_BLOCKED", "employer may not read PII")
    e = get_or_404(db.employees, eid)
    return ok(ser_employee(e), 200)


@app.route("/eap/employees/<eid>/eligibility", methods=["POST"])
def set_eligibility(eid):
    require_role({"ProgramAdmin"})
    e = get_or_404(db.employees, eid)
    body = get_body()
    require_fields(body, ["eligibility_status"])
    status = check_enum(body["eligibility_status"], "eligibility_status", {"ELIGIBLE", "GRACE", "INELIGIBLE"})
    e["eligibility_status"] = status
    if status == "GRACE":
        gu = body.get("grace_until")
        e["grace_until"] = parse_iso(gu) if gu else None
    else:
        e["grace_until"] = None
    touch(e)
    return ok(ser_employee(e), 200)


# ============================================================================
# Dependent
# ============================================================================
@app.route("/eap/dependents", methods=["POST"])
def create_dependent():
    require_role({"ProgramAdmin", "CareCoordinator"})
    body = get_body()
    require_fields(body, ["employee_id", "full_name", "relationship"])
    emp = db.employees.get(body["employee_id"])
    if emp is None:
        raise err("ERR_NOT_FOUND", "employee not found")
    if not isinstance(body["full_name"], str):
        raise err("ERR_INVALID_REQUEST", "full_name must be a string")
    rel = check_enum(body["relationship"], "relationship", {"SPOUSE", "CHILD", "OTHER"})

    d = common_fields_new()
    d.update({
        "employee_id": body["employee_id"],
        "full_name": body["full_name"],
        "relationship": rel,
        "eligibility_status": "ELIGIBLE",
    })
    db.dependents[d["id"]] = d
    return ok(ser_dependent(d), 201)


@app.route("/eap/dependents", methods=["GET"])
def list_dependents():
    require_role({"ProgramAdmin", "CareCoordinator"})
    employee_id = request.args.get("employee_id")
    items = [d for d in db.dependents.values() if employee_id is None or d["employee_id"] == employee_id]
    return list_response(items, ser_dependent)


@app.route("/eap/dependents/<did>", methods=["GET"])
def get_dependent(did):
    require_role({"ProgramAdmin", "CareCoordinator"})
    d = get_or_404(db.dependents, did)
    return ok(ser_dependent(d), 200)


# ============================================================================
# Case
# ============================================================================
@app.route("/eap/cases", methods=["POST"])
def create_case():
    require_role({"CareCoordinator"})
    body = get_body()
    require_fields(body, ["contract_id", "employee_id", "presenting_issue"])
    contract = db.contracts.get(body["contract_id"])
    if contract is None:
        raise err("ERR_NOT_FOUND", "contract not found")
    emp = db.employees.get(body["employee_id"])
    if emp is None:
        raise err("ERR_NOT_FOUND", "employee not found")
    dependent_id = body.get("dependent_id")
    dep = None
    if dependent_id is not None:
        dep = db.dependents.get(dependent_id)
        if dep is None:
            raise err("ERR_NOT_FOUND", "dependent not found")
    issue = check_enum(body["presenting_issue"], "presenting_issue", PRESENTING_ISSUES)
    if dep is not None and dep["employee_id"] != body["employee_id"]:
        raise err("ERR_DEPENDENT_NOT_UNDER_EMPLOYEE", "dependent not under employee")

    c = common_fields_new()
    c.update({
        "contract_id": body["contract_id"],
        "employee_id": body["employee_id"],
        "dependent_id": dependent_id,
        "presenting_issue": issue,
        "clinical_status": "INTAKE",
        "funding_status": "PENDING",
        "session_allotment": None,
    })
    db.cases[c["id"]] = c
    return ok(ser_case(c), 201)


@app.route("/eap/cases", methods=["GET"])
def list_cases():
    require_role({"ProgramAdmin", "CareCoordinator"})
    contract_id = request.args.get("contract_id")
    employee_id = request.args.get("employee_id")
    dependent_id = request.args.get("dependent_id")
    items = [
        c for c in db.cases.values()
        if (contract_id is None or c["contract_id"] == contract_id)
        and (employee_id is None or c["employee_id"] == employee_id)
        and (dependent_id is None or c["dependent_id"] == dependent_id)
    ]
    return list_response(items, ser_case)


@app.route("/eap/cases/<cid>", methods=["GET"])
def get_case(cid):
    role, _ = require_role({"ProgramAdmin", "CareCoordinator", "Employer"})
    if role == "Employer":
        raise err("ERR_CONFIDENTIALITY_BLOCKED", "employer may not read PII")
    c = get_or_404(db.cases, cid)
    return ok(ser_case(c), 200)


@app.route("/eap/cases/<cid>/authorize", methods=["POST"])
def authorize_case(cid):
    require_role({"CareCoordinator"})
    case = get_or_404(db.cases, cid)
    body = get_body()
    contract = db.contracts.get(case["contract_id"])
    emp = db.employees.get(case["employee_id"])
    # state: must be PENDING funding and INTAKE clinical
    if case["funding_status"] != "PENDING" or case["clinical_status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "case not in authorizable state")
    # OCC
    check_occ(contract, body)
    # contract active
    if contract["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "contract not active")
    # employee eligible
    if emp["eligibility_status"] not in ("ELIGIBLE", "GRACE"):
        raise err("ERR_EMPLOYEE_INELIGIBLE", "employee ineligible")
    # annual cap
    committed = contract_sessions_committed(contract["id"])
    if committed + contract["sessions_per_issue"] > contract["annual_session_cap"]:
        raise err("ERR_ANNUAL_CAP_EXCEEDED", "annual cap exceeded")

    case["session_allotment"] = contract["sessions_per_issue"]
    case["funding_status"] = "AUTHORIZED"
    case["clinical_status"] = "OPEN"
    touch(case)
    return ok(ser_case(case), 200)


@app.route("/eap/cases/<cid>/revoke", methods=["POST"])
def revoke_case(cid):
    require_role({"ProgramAdmin"})
    case = get_or_404(db.cases, cid)
    if case["funding_status"] not in ("AUTHORIZED", "EXHAUSTED"):
        raise err("ERR_INVALID_STATE", "case not in revocable funding state")
    if case["clinical_status"] == "CLOSED":
        raise err("ERR_INVALID_STATE", "case is closed")
    case["funding_status"] = "REVOKED"
    touch(case)
    revoke_cascade_for_case(case)
    return ok(ser_case(case), 200)


@app.route("/eap/cases/<cid>/close", methods=["POST"])
def close_case(cid):
    require_role({"CareCoordinator"})
    case = get_or_404(db.cases, cid)
    if case["clinical_status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "case not OPEN")
    has_scheduled = any(
        s["case_id"] == case["id"] and s["status"] == "SCHEDULED"
        for s in db.sessions.values()
    )
    if has_scheduled:
        raise err("ERR_CASE_HAS_OPEN_SESSIONS", "case has scheduled sessions")
    case["clinical_status"] = "CLOSED"
    touch(case)
    return ok(ser_case(case), 200)


# ============================================================================
# CounselingSession
# ============================================================================
def intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.route("/eap/cases/<cid>/sessions", methods=["POST"])
def create_session(cid):
    require_role({"CareCoordinator"})
    case = get_or_404(db.cases, cid)
    body = get_body()
    require_fields(body, ["provider_id", "scheduled_for"])
    provider = db.providers.get(body["provider_id"])
    if provider is None:
        raise err("ERR_NOT_FOUND", "provider not found")
    scheduled_for = parse_iso(body["scheduled_for"])
    duration = body.get("duration_minutes", 50)
    if duration is None:
        duration = 50
    duration = as_int(duration, "duration_minutes", 30, 120)

    # state: must be AUTHORIZED to schedule
    if case["funding_status"] == "EXHAUSTED":
        raise err("ERR_ALLOTMENT_EXHAUSTED", "allotment exhausted")
    if case["funding_status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", "case not authorized")

    # allotment check (priority 14)
    used = case_sessions_used(case["id"])
    if case["session_allotment"] is not None and used >= case["session_allotment"]:
        raise err("ERR_ALLOTMENT_EXHAUSTED", "allotment exhausted")

    # temporal: not in past (priority 10)
    if scheduled_for < clock.now():
        raise err("ERR_SESSION_IN_PAST", "scheduled_for is in the past")

    new_start = scheduled_for
    new_end = scheduled_for + timedelta(minutes=duration)

    # provider double-book (priority 11)
    for s in db.sessions.values():
        if s["provider_id"] == provider["id"] and s["status"] == "SCHEDULED":
            s_start = s["scheduled_for"]
            s_end = s_start + timedelta(minutes=s["duration_minutes"])
            if intervals_overlap(new_start, new_end, s_start, s_end):
                raise err("ERR_PROVIDER_DOUBLE_BOOKED", "provider double-booked")

    # case same-day (priority 11.5)
    new_day = new_start.astimezone(timezone.utc).date()
    for s in db.sessions.values():
        if s["case_id"] == case["id"] and s["status"] == "SCHEDULED":
            if s["scheduled_for"].astimezone(timezone.utc).date() == new_day:
                raise err("ERR_CASE_SAME_DAY_SESSION", "case already has a session that day")

    s = common_fields_new()
    s.update({
        "case_id": case["id"],
        "provider_id": provider["id"],
        "scheduled_for": scheduled_for,
        "duration_minutes": duration,
        "status": "SCHEDULED",
    })
    db.sessions[s["id"]] = s

    # may exhaust funding
    new_used = case_sessions_used(case["id"])
    if case["session_allotment"] is not None and new_used >= case["session_allotment"]:
        case["funding_status"] = "EXHAUSTED"
        touch(case)

    return ok(ser_session(s), 201)


@app.route("/eap/sessions", methods=["GET"])
def list_sessions():
    require_role({"ProgramAdmin", "CareCoordinator"})
    case_id = request.args.get("case_id")
    provider_id = request.args.get("provider_id")
    items = [
        s for s in db.sessions.values()
        if (case_id is None or s["case_id"] == case_id)
        and (provider_id is None or s["provider_id"] == provider_id)
    ]
    return list_response(items, ser_session)


@app.route("/eap/sessions/<sid>", methods=["GET"])
def get_session(sid):
    require_role({"ProgramAdmin", "CareCoordinator"})
    s = get_or_404(db.sessions, sid)
    return ok(ser_session(s), 200)


@app.route("/eap/sessions/<sid>/status", methods=["POST"])
def session_status(sid):
    require_role({"CareCoordinator", "Provider"})
    s = get_or_404(db.sessions, sid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = check_enum(body["to_status"], "to_status", {"COMPLETED", "NO_SHOW", "CANCELLED"})
    if s["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "session not SCHEDULED")
    s["status"] = to_status
    touch(s)
    return ok(ser_session(s), 200)


# ============================================================================
# Provider
# ============================================================================
@app.route("/eap/providers", methods=["POST"])
def create_provider():
    require_role({"ProgramAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "specialties"])
    if not isinstance(body["full_name"], str):
        raise err("ERR_INVALID_REQUEST", "full_name must be a string")
    specialties = body["specialties"]
    if not isinstance(specialties, list):
        raise err("ERR_INVALID_REQUEST", "specialties must be a list")
    for sp in specialties:
        check_enum(sp, "specialties", PRESENTING_ISSUES)
    network = body.get("network_status", "IN_NETWORK")
    if network is None:
        network = "IN_NETWORK"
    network = check_enum(network, "network_status", {"IN_NETWORK", "OUT_OF_NETWORK"})
    accepting = body.get("accepting", True)
    if accepting is None:
        accepting = True
    if not isinstance(accepting, bool):
        raise err("ERR_INVALID_REQUEST", "accepting must be a boolean")

    p = common_fields_new()
    p.update({
        "full_name": body["full_name"],
        "network_status": network,
        "specialties": list(specialties),
        "accepting": accepting,
    })
    db.providers[p["id"]] = p
    return ok(ser_provider(p), 201)


@app.route("/eap/providers", methods=["GET"])
def list_providers():
    require_role({"ProgramAdmin", "CareCoordinator"})
    accepting = request.args.get("accepting")
    items = list(db.providers.values())
    if accepting is not None:
        want = accepting.lower() == "true"
        items = [p for p in items if p["accepting"] == want]
    return list_response(items, ser_provider)


@app.route("/eap/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require_role({"ProgramAdmin", "CareCoordinator", "Provider"})
    p = get_or_404(db.providers, pid)
    return ok(ser_provider(p), 200)


# ============================================================================
# Referral
# ============================================================================
@app.route("/eap/referrals", methods=["POST"])
def create_referral():
    require_role({"CareCoordinator"})
    body = get_body()
    require_fields(body, ["employee_id", "referral_type", "required_specialty"])
    emp = db.employees.get(body["employee_id"])
    if emp is None:
        raise err("ERR_NOT_FOUND", "employee not found")
    case_id = body.get("case_id")
    if case_id is not None:
        if db.cases.get(case_id) is None:
            raise err("ERR_NOT_FOUND", "case not found")
    rtype = check_enum(body["referral_type"], "referral_type", {"CLINICAL", "WORKLIFE", "LEGAL", "FINANCIAL"})
    required_specialty = check_enum(body["required_specialty"], "required_specialty", PRESENTING_ISSUES)

    # referential: specialty resolvable against provider network
    resolvable = any(required_specialty in p["specialties"] for p in db.providers.values())
    if not resolvable:
        raise err("ERR_REFERENTIAL_MISMATCH", "specialty not resolvable")

    # work-life cap (priority 15)
    if rtype in ("WORKLIFE", "LEGAL", "FINANCIAL"):
        plan = db.plans.get(emp["plan_id"])
        cap = plan["worklife_referrals_per_year"] if plan else 0
        used = employee_worklife_used(emp["id"])
        if used + 1 > cap:
            raise err("ERR_WORKLIFE_CAP_EXCEEDED", "work-life cap exceeded")

    provider = select_provider(required_specialty)

    r = common_fields_new()
    r.update({
        "case_id": case_id,
        "employee_id": body["employee_id"],
        "provider_id": provider["id"],
        "referral_type": rtype,
        "status": "REQUESTED",
        "required_specialty": required_specialty,
        "_last_declined_provider": None,
    })
    db.referrals[r["id"]] = r
    return ok(ser_referral(r), 201)


@app.route("/eap/referrals", methods=["GET"])
def list_referrals():
    require_role({"ProgramAdmin", "CareCoordinator", "Provider"})
    case_id = request.args.get("case_id")
    employee_id = request.args.get("employee_id")
    provider_id = request.args.get("provider_id")
    items = [
        r for r in db.referrals.values()
        if (case_id is None or r["case_id"] == case_id)
        and (employee_id is None or r["employee_id"] == employee_id)
        and (provider_id is None or r["provider_id"] == provider_id)
    ]
    return list_response(items, ser_referral)


@app.route("/eap/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    require_role({"ProgramAdmin", "CareCoordinator", "Provider"})
    r = get_or_404(db.referrals, rid)
    return ok(ser_referral(r), 200)


@app.route("/eap/referrals/<rid>/accept", methods=["POST"])
def accept_referral(rid):
    role, user_id = require_role({"Provider"})
    r = get_or_404(db.referrals, rid)
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "referral not REQUESTED")
    if r["provider_id"] != user_id:
        raise err("ERR_NOT_ASSIGNED_PROVIDER", "not the assigned provider")
    r["status"] = "ACCEPTED"
    touch(r)
    return ok(ser_referral(r), 200)


@app.route("/eap/referrals/<rid>/decline", methods=["POST"])
def decline_referral(rid):
    role, user_id = require_role({"Provider"})
    r = get_or_404(db.referrals, rid)
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "referral not REQUESTED")
    if r["provider_id"] != user_id:
        raise err("ERR_NOT_ASSIGNED_PROVIDER", "not the assigned provider")
    r["status"] = "DECLINED"
    r["_last_declined_provider"] = r["provider_id"]
    r["provider_id"] = None
    touch(r)
    return ok(ser_referral(r), 200)


@app.route("/eap/referrals/<rid>/reassign", methods=["POST"])
def reassign_referral(rid):
    require_role({"CareCoordinator"})
    r = get_or_404(db.referrals, rid)
    if r["status"] != "DECLINED":
        raise err("ERR_INVALID_STATE", "referral not DECLINED")
    # need required specialty to re-select; infer from original required specialty.
    # We stored none, so re-derive from any provider that can serve — but spec says
    # reassign uses provider-selection with the just-declined excluded. We must know
    # the required specialty. Store it at creation.
    required_specialty = r.get("required_specialty")
    excluded = r.get("_last_declined_provider")
    provider = select_provider(required_specialty, excluded_id=excluded)
    r["provider_id"] = provider["id"]
    r["status"] = "REQUESTED"
    touch(r)
    return ok(ser_referral(r), 200)


@app.route("/eap/referrals/<rid>/complete", methods=["POST"])
def complete_referral(rid):
    role, user_id = require_role({"Provider"})
    r = get_or_404(db.referrals, rid)
    if r["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "referral not ACCEPTED")
    if r["provider_id"] != user_id:
        raise err("ERR_NOT_ASSIGNED_PROVIDER", "not the assigned provider")
    r["status"] = "COMPLETED"
    touch(r)
    return ok(ser_referral(r), 200)


@app.route("/eap/referrals/<rid>/cancel", methods=["POST"])
def cancel_referral(rid):
    require_role({"CareCoordinator"})
    r = get_or_404(db.referrals, rid)
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "referral not REQUESTED")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(ser_referral(r), 200)


# ============================================================================
# CrisisContact
# ============================================================================
@app.route("/eap/crisis-contacts", methods=["POST"])
def create_crisis():
    require_role({"CrisisCounselor"})
    body = get_body()
    require_fields(body, ["contract_id", "severity"])
    contract = db.contracts.get(body["contract_id"])
    if contract is None:
        raise err("ERR_NOT_FOUND", "contract not found")
    employee_id = body.get("employee_id")
    if employee_id is not None:
        if db.employees.get(employee_id) is None:
            raise err("ERR_NOT_FOUND", "employee not found")
    severity = check_enum(body["severity"], "severity", {"LOW", "MODERATE", "HIGH", "IMMINENT"})

    cc = common_fields_new()
    cc.update({
        "contract_id": body["contract_id"],
        "employee_id": employee_id,
        "opened_at": clock.now(),
        "severity": severity,
        "triaged_at": None,
        "status": "OPEN",
        "disposition": None,
    })
    db.crisis[cc["id"]] = cc
    return ok(ser_crisis(cc), 201)


@app.route("/eap/crisis-contacts", methods=["GET"])
def list_crisis():
    require_role({"ProgramAdmin", "CrisisCounselor"})
    contract_id = request.args.get("contract_id")
    employee_id = request.args.get("employee_id")
    items = [
        cc for cc in db.crisis.values()
        if (contract_id is None or cc["contract_id"] == contract_id)
        and (employee_id is None or cc["employee_id"] == employee_id)
    ]
    return list_response(items, ser_crisis)


@app.route("/eap/crisis-contacts/<ccid>", methods=["GET"])
def get_crisis(ccid):
    require_role({"ProgramAdmin", "CrisisCounselor"})
    cc = get_or_404(db.crisis, ccid)
    return ok(ser_crisis(cc), 200)


@app.route("/eap/crisis-contacts/<ccid>/triage", methods=["POST"])
def triage_crisis(ccid):
    require_role({"CrisisCounselor"})
    cc = get_or_404(db.crisis, ccid)
    body = get_body()
    require_fields(body, ["disposition"])
    disp = check_enum(body["disposition"], "disposition",
                      {"SELF_HELP", "ROUTINE_REFERRAL", "URGENT_REFERRAL", "EMERGENCY_DISPATCH"})
    if cc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "crisis contact not OPEN")
    cc["triaged_at"] = clock.now()
    cc["disposition"] = disp
    cc["status"] = "TRIAGED"
    touch(cc)
    return ok(ser_crisis(cc), 200)


@app.route("/eap/crisis-contacts/<ccid>/escalate", methods=["POST"])
def escalate_crisis(ccid):
    require_role({"CrisisCounselor"})
    cc = get_or_404(db.crisis, ccid)
    body = get_body()
    require_fields(body, ["required_specialty"])
    required_specialty = check_enum(body["required_specialty"], "required_specialty", PRESENTING_ISSUES)
    if cc["status"] != "TRIAGED":
        raise err("ERR_INVALID_STATE", "crisis contact not TRIAGED")
    if cc["disposition"] not in ("URGENT_REFERRAL", "EMERGENCY_DISPATCH"):
        raise err("ERR_DISPOSITION_NOT_ESCALATABLE", "disposition not escalatable")
    provider = select_provider(required_specialty)
    cc["status"] = "ESCALATED"
    touch(cc)
    # create CLINICAL referral
    r = common_fields_new()
    r.update({
        "case_id": None,
        "employee_id": cc["employee_id"],
        "provider_id": provider["id"],
        "referral_type": "CLINICAL",
        "status": "REQUESTED",
        "required_specialty": required_specialty,
        "_last_declined_provider": None,
    })
    db.referrals[r["id"]] = r
    return ok(ser_crisis(cc), 200)


@app.route("/eap/crisis-contacts/<ccid>/resolve", methods=["POST"])
def resolve_crisis(ccid):
    require_role({"CrisisCounselor"})
    cc = get_or_404(db.crisis, ccid)
    if cc["status"] not in ("TRIAGED", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "crisis contact not resolvable")
    if cc["status"] == "TRIAGED":
        # IMMINENT severity overrides direct-resolve branch
        if cc["severity"] == "IMMINENT":
            raise err("ERR_IMMINENT_REQUIRES_ESCALATION", "imminent requires escalation")
        if cc["disposition"] not in ("SELF_HELP", "ROUTINE_REFERRAL"):
            raise err("ERR_DISPOSITION_NOT_RESOLVABLE", "disposition not resolvable")
    cc["status"] = "RESOLVED"
    touch(cc)
    return ok(ser_crisis(cc), 200)


# ============================================================================
# Claim
# ============================================================================
@app.route("/eap/claims", methods=["POST"])
def create_claim():
    role, user_id = require_role({"Provider"})
    body = get_body()
    require_fields(body, ["contract_id", "session_id", "billed_cents"])
    contract = db.contracts.get(body["contract_id"])
    if contract is None:
        raise err("ERR_NOT_FOUND", "contract not found")
    session = db.sessions.get(body["session_id"])
    if session is None:
        raise err("ERR_NOT_FOUND", "session not found")
    billed = as_int(body["billed_cents"], "billed_cents", 0)

    # referential: session's case traces to claim's contract
    case = db.cases.get(session["case_id"])
    if case is None or case["contract_id"] != body["contract_id"]:
        raise err("ERR_REFERENTIAL_MISMATCH", "session not under claim contract")

    # at most one live (non-REJECTED) claim per session
    for cl in db.claims.values():
        if cl["session_id"] == body["session_id"] and cl["status"] != "REJECTED":
            raise err("ERR_CLAIM_ALREADY_CLAIMED", "claim already exists for session")

    c = common_fields_new()
    c.update({
        "contract_id": body["contract_id"],
        "session_id": body["session_id"],
        "provider_id": session["provider_id"],
        "billed_cents": billed,
        "provisional_cents": 0,
        "final_cents": None,
        "status": "SUBMITTED",
    })
    c["provisional_cents"] = claim_provisional(c)
    db.claims[c["id"]] = c
    return ok(ser_claim(c), 201)


@app.route("/eap/claims", methods=["GET"])
def list_claims():
    require_role({"ProgramAdmin", "Provider"})
    contract_id = request.args.get("contract_id")
    session_id = request.args.get("session_id")
    provider_id = request.args.get("provider_id")
    items = [
        c for c in db.claims.values()
        if (contract_id is None or c["contract_id"] == contract_id)
        and (session_id is None or c["session_id"] == session_id)
        and (provider_id is None or c["provider_id"] == provider_id)
    ]
    return list_response(items, ser_claim)


@app.route("/eap/claims/<clid>", methods=["GET"])
def get_claim(clid):
    require_role({"ProgramAdmin", "Provider"})
    c = get_or_404(db.claims, clid)
    return ok(ser_claim(c), 200)


@app.route("/eap/claims/<clid>/review", methods=["POST"])
def review_claim(clid):
    require_role({"ProgramAdmin"})
    c = get_or_404(db.claims, clid)
    if c["status"] not in ("SUBMITTED", "RESUBMITTED"):
        raise err("ERR_INVALID_STATE", "claim not submittable for review")
    session = db.sessions.get(c["session_id"])
    if session is None or session["status"] != "COMPLETED":
        raise err("ERR_SESSION_NOT_COMPLETED", "session not completed")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return ok(ser_claim(c), 200)


@app.route("/eap/claims/<clid>/approve", methods=["POST"])
def approve_claim(clid):
    require_role({"ProgramAdmin"})
    c = get_or_404(db.claims, clid)
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "claim not under review")
    contract = db.contracts.get(c["contract_id"])
    if contract["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "contract not active")
    c["final_cents"] = claim_final(c)
    c["status"] = "APPROVED"
    touch(c)
    return ok(ser_claim(c), 200)


@app.route("/eap/claims/<clid>/reject", methods=["POST"])
def reject_claim(clid):
    require_role({"ProgramAdmin"})
    c = get_or_404(db.claims, clid)
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "claim not under review")
    c["status"] = "REJECTED"
    c["final_cents"] = None
    touch(c)
    return ok(ser_claim(c), 200)


@app.route("/eap/claims/<clid>/resubmit", methods=["POST"])
def resubmit_claim(clid):
    role, user_id = require_role({"Provider"})
    c = get_or_404(db.claims, clid)
    body = get_body()
    require_fields(body, ["billed_cents"])
    billed = as_int(body["billed_cents"], "billed_cents", 0)
    if c["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "claim not REJECTED")
    c["billed_cents"] = billed
    c["status"] = "RESUBMITTED"
    c["provisional_cents"] = claim_provisional(c)
    touch(c)
    return ok(ser_claim(c), 200)


@app.route("/eap/claims/<clid>/pay", methods=["POST"])
def pay_claim(clid):
    require_role({"ProgramAdmin"})
    c = get_or_404(db.claims, clid)
    if c["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "claim not APPROVED")
    c["status"] = "PAID"
    touch(c)
    return ok(ser_claim(c), 200)


# ============================================================================
# WellnessActivity
# ============================================================================
@app.route("/eap/wellness-activities", methods=["POST"])
def create_wellness():
    require_role({"ProgramAdmin", "CareCoordinator"})
    body = get_body()
    require_fields(body, ["employee_id", "activity_type", "points", "completed_on"])
    emp = db.employees.get(body["employee_id"])
    if emp is None:
        raise err("ERR_NOT_FOUND", "employee not found")
    activity_type = check_enum(body["activity_type"], "activity_type",
                               {"SCREENING", "WEBINAR", "CHALLENGE", "COACHING"})
    points = as_int(body["points"], "points", 0, 100)
    completed_on = parse_iso(body["completed_on"])

    w = common_fields_new()
    w.update({
        "employee_id": body["employee_id"],
        "activity_type": activity_type,
        "points": points,
        "completed_on": completed_on,
    })
    db.wellness[w["id"]] = w
    return ok(ser_wellness(w), 201)


@app.route("/eap/wellness-activities", methods=["GET"])
def list_wellness():
    require_role({"ProgramAdmin", "CareCoordinator"})
    employee_id = request.args.get("employee_id")
    items = [w for w in db.wellness.values() if employee_id is None or w["employee_id"] == employee_id]
    return list_response(items, ser_wellness)


@app.route("/eap/wellness-activities/<wid>", methods=["GET"])
def get_wellness(wid):
    require_role({"ProgramAdmin", "CareCoordinator"})
    w = get_or_404(db.wellness, wid)
    return ok(ser_wellness(w), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
