"""Core plumbing: in-memory store, logical clock, response envelope, auth,
field validators, derived calculations, serializers, and cascade helpers.

Storage is strictly in-memory module state. Nothing is seeded at startup;
the store begins empty and the logical clock begins at 2026-08-01T00:00:00Z.
"""
import json
import re
import uuid
import itertools
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import request, jsonify

getcontext().prec = 60

ROLES = {"PortfolioDirector", "AssetManager", "PropertyManager",
         "InvestmentCommittee", "Lender", "Analyst"}
ALL_ROLES = ["PortfolioDirector", "AssetManager", "PropertyManager",
             "InvestmentCommittee", "Lender", "Analyst"]

REVENUE_CATS = ["RENT_REVENUE", "PARKING_REVENUE", "OTHER_REVENUE"]
EXPENSE_CATS = ["CAM_EXPENSE", "TAX_EXPENSE", "INSURANCE_EXPENSE", "UTILITIES_EXPENSE",
                "MANAGEMENT_FEE_EXPENSE", "OTHER_OPEX"]
NON_CAPITAL_CATS = REVENUE_CATS + EXPENSE_CATS
ALL_CATS = NON_CAPITAL_CATS + ["CAPITAL"]

ASSET_CLASSES = {"OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY"}
SPACE_TYPES = {"OFFICE_SUITE", "RETAIL_BAY", "INDUSTRIAL_BAY", "APARTMENT_UNIT"}
COVENANT_TYPES = {"MIN_DSCR", "MAX_LTV", "MIN_DEBT_YIELD"}
TEST_FREQS = {"QUARTERLY", "ANNUAL"}
VALUATION_METHODS = {"EXTERNAL_APPRAISAL", "INTERNAL_CAP"}
TRIGGER_TYPES = {"REFINANCE", "HOLD", "SELL"}
SALE_ACTIONS = {"CONTRACT", "CLOSE", "DELIST"}

PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]$")
LIVE_LOAN_STATUSES = {"CURRENT", "WATCH", "DEFAULT"}
TERMINAL_LOAN_STATUSES = {"DEFAULT", "REFINANCED", "PAID_OFF"}


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


class Store:
    """The entire database: plain dicts keyed by id, plus the logical clock."""

    def __init__(self):
        self.portfolios = {}
        self.managers = {}
        self.assets = {}
        self.plans = {}
        self.budget_lines = {}
        self.actuals = {}
        self.projects = {}
        self.draws = {}
        self.strategies = {}
        self.loans = {}
        self.covenants = {}
        self.covenant_tests = {}
        self.valuations = {}
        self.scorecards = {}
        self.reforecasts = {}
        self.decisions = {}
        self.lender_reports = {}
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = itertools.count(1)    # insertion ordering (created_at tiebreak)
        self.tick = itertools.count(1)   # mutation ordering (finalization recency)


store = Store()


def tick():
    return next(store.tick)


def clock_now():
    return store.clock


def clock_date():
    return store.clock.date()


def _fmt_dt(dt):
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"


def now_iso():
    return _fmt_dt(store.clock)


def fmt_clock(dt):
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return _fmt_dt(dt)


def parse_iso8601(s):
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def new_req_id():
    return "req_" + uuid.uuid4().hex[:24]


def _meta():
    return {"api_request_id": new_req_id(), "api_request_timestamp": now_iso()}


def success_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def success_list(items, total, limit, offset):
    meta = _meta()
    meta.update({"limit": limit, "offset": offset, "total_count": total,
                 "has_more": (offset + len(items)) < total})
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def success_array(items, status=201):
    return jsonify({"meta": _meta(), "response_type": "array", "data": items}), status


def error_response(err):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": err.error_id, "message": err.message}}), err.status


def bad_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def forbidden(msg="Role is not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def conflict(error_id, msg):
    return ApiError(error_id, 409, msg)


def unprocessable(error_id, msg):
    return ApiError(error_id, 422, msg)


def stale(error_id, msg):
    return ApiError(error_id, 412, msg)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def auth_user():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (uid is None or not isinstance(uid, str) or uid.strip() == ""
            or role is None or role not in ROLES):
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are required; role must be a declared role")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise forbidden()


# ---------------------------------------------------------------------------
# Body and field validators
# ---------------------------------------------------------------------------

def body():
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise bad_request("Request body must be a JSON object")
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def req_value(b, name):
    if name not in b or b[name] is None:
        raise bad_request(f"Missing required field: {name}")
    return b[name]


def req_str(b, name):
    v = req_value(b, name)
    if not isinstance(v, str) or v == "":
        raise bad_request(f"Field {name} must be a non-empty string")
    return v


def req_int(b, name):
    v = req_value(b, name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise bad_request(f"Field {name} must be an integer")
    return v


def req_pos_int(b, name):
    v = req_int(b, name)
    if v <= 0:
        raise bad_request(f"Field {name} must be a positive integer")
    return v


def req_nonneg_int(b, name):
    v = req_int(b, name)
    if v < 0:
        raise bad_request(f"Field {name} must be a non-negative integer")
    return v


def opt_int(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, int) or isinstance(v, bool):
        raise bad_request(f"Field {name} must be an integer")
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], str):
        raise bad_request(f"Field {name} must be a string")
    return b[name]


def opt_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], bool):
        raise bad_request(f"Field {name} must be a boolean")
    return b[name]


def req_enum(b, name, allowed):
    v = req_value(b, name)
    if not isinstance(v, str) or v not in allowed:
        raise bad_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_date(b, name):
    v = req_value(b, name)
    if not isinstance(v, str):
        raise bad_request(f"Field {name} must be an ISO date string")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise bad_request(f"Field {name} must be an ISO date string (YYYY-MM-DD)")


def req_period(b, name):
    v = req_value(b, name)
    if not isinstance(v, str) or not PERIOD_RE.match(v):
        raise bad_request(f"Field {name} must match the format YYYY-Qn with n in 1..4")
    return v


def get_or_404(coll, rid, what="resource"):
    if not isinstance(rid, str) or rid not in coll:
        raise not_found(f"{what} not found")
    return coll[rid]


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def new_record():
    ts = now_iso()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next(store.seq)}


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise bad_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise bad_request("offset must be an integer")
    return max(1, min(100, limit)), max(0, offset)


def list_response(records, serializer):
    records = sorted(records, key=lambda r: r["_seq"])
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Rounding (half-up to a whole unit; floor only where the spec says so)
# ---------------------------------------------------------------------------

def rhu_div(numer, denom):
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Collection scans
# ---------------------------------------------------------------------------

def assets_of_portfolio(pid):
    return [a for a in store.assets.values() if a["portfolio_id"] == pid]


def assets_of_manager(mid):
    return [a for a in store.assets.values() if a["property_manager_id"] == mid]


def plans_of_asset(aid):
    return [p for p in store.plans.values() if p["asset_id"] == aid]


def lines_of_plan(pid):
    return sorted((l for l in store.budget_lines.values() if l["plan_id"] == pid),
                  key=lambda r: r["_seq"])


def reports_of_plan(pid):
    return [r for r in store.actuals.values() if r["plan_id"] == pid]


def projects_of_plan(pid):
    return [p for p in store.projects.values() if p["plan_id"] == pid]


def projects_of_asset(aid):
    return [p for p in store.projects.values() if p["asset_id"] == aid]


def draws_of_project(pid):
    return [d for d in store.draws.values() if d["project_id"] == pid]


def strategies_of_asset(aid):
    return [s for s in store.strategies.values() if s["asset_id"] == aid]


def loans_of_asset(aid):
    return [l for l in store.loans.values() if l["asset_id"] == aid]


def covenants_of_loan(lid):
    return [c for c in store.covenants.values() if c["loan_id"] == lid]


def tests_of_covenant(cid):
    return [t for t in store.covenant_tests.values() if t["covenant_id"] == cid]


def valuations_of_asset(aid):
    return [v for v in store.valuations.values() if v["asset_id"] == aid]


def scorecards_of_asset(aid):
    return [s for s in store.scorecards.values() if s["asset_id"] == aid]


def scorecards_of_manager(mid):
    return [s for s in store.scorecards.values() if s["property_manager_id"] == mid]


def reforecasts_of_plan(pid):
    return [r for r in store.reforecasts.values() if r["plan_id"] == pid]


def decisions_of_asset(aid):
    return [d for d in store.decisions.values() if d["asset_id"] == aid]


def reports_of_loan(lid):
    return [r for r in store.lender_reports.values() if r["loan_id"] == lid]


# ---------------------------------------------------------------------------
# Derived calculations
# ---------------------------------------------------------------------------

def project_drawn(project):
    return sum(d["amount_cents"] for d in draws_of_project(project["id"])
               if d["status"] == "RELEASED")


def plan_capital_buckets(plan):
    projs = projects_of_plan(plan["id"])
    reserved = sum(p["approved_amount_cents"] - project_drawn(p)
                   for p in projs if p["status"] in ("APPROVED", "IN_PROGRESS"))
    drawn = sum(project_drawn(p)
                for p in projs if p["status"] in ("APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"))
    total_cap = sum(l["budget_amount_cents"] for l in lines_of_plan(plan["id"])
                    if l["category"] == "CAPITAL")
    return total_cap, reserved, drawn, total_cap - reserved - drawn


def annualized_noi_for_plan(plan):
    """TRAILING_ACTUALS variant over the given plan's lines; None when M == 0."""
    lines = [l for l in lines_of_plan(plan["id"])
             if l["has_actual"] and l["category"] in NON_CAPITAL_CATS]
    m = len({l["month_index"] for l in lines})
    if m == 0:
        return None
    ytd = sum(l["actual_amount_cents"] if l["category"] in REVENUE_CATS
              else -l["actual_amount_cents"] for l in lines)
    return rhu_div(ytd * 12, m)


def annualized_noi(asset):
    pid = asset.get("current_plan_id")
    if not pid:
        return None
    plan = store.plans.get(pid)
    if plan is None or plan["status"] != "APPROVED":
        return None
    return annualized_noi_for_plan(plan)


def annual_debt_service(loan):
    return rhu_div(loan["principal_balance_cents"] * loan["annual_interest_rate_bps"], 10000)


def portfolio_posture(portfolio_id):
    ids = {a["id"] for a in assets_of_portfolio(portfolio_id) if a["status"] != "SOLD"}
    watch = sum(1 for l in store.loans.values() if l["asset_id"] in ids and l["status"] == "WATCH")
    default = sum(1 for l in store.loans.values() if l["asset_id"] in ids and l["status"] == "DEFAULT")
    if default >= 1 or watch >= 2:
        return "RESTRICTED"
    if watch == 1:
        return "ELEVATED"
    return "NORMAL"


def portfolio_total_value(portfolio_id):
    return sum(a["current_value_cents"] or 0 for a in assets_of_portfolio(portfolio_id)
               if a["status"] in ("OWNED", "LISTED_FOR_SALE"))


def months_between(d1, d2):
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) - (1 if d2.day < d1.day else 0)


def fiscal_month(plan):
    asset = store.assets.get(plan["asset_id"])
    port = store.portfolios.get(asset["portfolio_id"]) if asset else None
    if port is None:
        return 0
    d = clock_date()
    return (d.year - plan["fiscal_year"]) * 12 + (d.month - port["fiscal_year_start_month"]) + 1


def manager_composite_avg(manager_id):
    cards = [s for s in scorecards_of_manager(manager_id) if s["status"] == "FINALIZED"]
    if not cards:
        return None
    cards.sort(key=lambda s: s.get("_finalized_tick", s["_seq"]), reverse=True)
    top = cards[:4]
    mean = (Decimal(sum(c["composite_score"] for c in top)) / Decimal(len(top))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(mean)


def latest_confirmed_valuation(asset_id):
    vals = [v for v in valuations_of_asset(asset_id) if v["status"] == "CONFIRMED"]
    if not vals:
        return None
    vals.sort(key=lambda v: (v["effective_date"], v["_seq"]))
    return vals[-1]


def active_loan(asset_id):
    loans = [l for l in loans_of_asset(asset_id) if l["status"] in LIVE_LOAN_STATUSES]
    if not loans:
        return None
    loans.sort(key=lambda l: l["_seq"])
    return loans[-1]


def quarter_end_for(year, q):
    return {1: date(year, 3, 31), 2: date(year, 6, 30),
            3: date(year, 9, 30), 4: date(year, 12, 31)}[q]


def parse_period(label):
    return int(label[:4]), int(label[-1])


def prev_quarter(year, q):
    return (year, q - 1) if q > 1 else (year - 1, 4)


def spend_vector(amount, s, e):
    span = e - s + 1
    monthly = amount // span
    return {m: (amount - monthly * (span - 1) if m == e else monthly)
            for m in range(s, e + 1)}


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_project(project):
    """System cascade cancel; the caller owns the plan version bump."""
    project["status"] = "CANCELLED"
    touch(project)
    for d in draws_of_project(project["id"]):
        if d["status"] in ("REQUESTED", "APPROVED"):
            d["status"] = "REJECTED"
            touch(d)


def close_plan(plan):
    plan["status"] = "CLOSED"
    touch(plan)
    for p in projects_of_plan(plan["id"]):
        if p["status"] in ("PROPOSED", "APPROVED", "IN_PROGRESS"):
            cancel_project(p)
    for rf in reforecasts_of_plan(plan["id"]):
        if rf["status"] in ("DRAFT", "SUBMITTED"):
            rf["status"] = "REJECTED"
            touch(rf)


def waive_loan_covenants(loan):
    for c in covenants_of_loan(loan["id"]):
        if c["status"] in ("ACTIVE", "IN_BREACH"):
            c["status"] = "WAIVED"
            c["last_breach_at"] = None
            touch(c)


def maybe_cure_loan(loan):
    if loan["status"] == "WATCH" and not any(
            c["status"] == "IN_BREACH" for c in covenants_of_loan(loan["id"])):
        loan["status"] = "CURRENT"
        touch(loan)


# ---------------------------------------------------------------------------
# Serializers (computed fields resolved here)
# ---------------------------------------------------------------------------

def ser_portfolio(p):
    out = pub(p)
    out["risk_posture"] = portfolio_posture(p["id"])
    out["total_value_cents"] = portfolio_total_value(p["id"])
    return out


def ser_manager(m):
    out = pub(m)
    out["composite_score_avg"] = manager_composite_avg(m["id"])
    return out


def ser_asset(a):
    out = pub(a)
    out["current_annualized_noi_cents"] = annualized_noi(a)
    return out


def ser_plan(p):
    out = pub(p)
    lines = lines_of_plan(p["id"])
    rev = sum(l["budget_amount_cents"] for l in lines if l["category"] in REVENUE_CATS)
    opex = sum(l["budget_amount_cents"] for l in lines if l["category"] in EXPENSE_CATS)
    total_cap, reserved, drawn, available = plan_capital_buckets(p)
    ytd = 0
    for l in lines:
        if l["has_actual"] and l["category"] in NON_CAPITAL_CATS:
            ytd += l["actual_amount_cents"] if l["category"] in REVENUE_CATS else -l["actual_amount_cents"]
    out["total_revenue_budget_cents"] = rev
    out["total_opex_budget_cents"] = opex
    out["total_capital_budget_cents"] = total_cap
    out["budgeted_noi_cents"] = rev - opex
    out["ytd_actual_noi_cents"] = ytd
    out["reserved_capital_cents"] = reserved
    out["drawn_capital_cents"] = drawn
    out["available_capital_cents"] = available
    return out


def ser_line(l):
    out = pub(l)
    if l["has_actual"]:
        diff = l["actual_amount_cents"] - l["budget_amount_cents"]
        out["variance_cents"] = diff
        b = l["budget_amount_cents"]
        if b > 0:
            out["variance_bps"] = rhu_div(diff * 10000, b)
        elif l["actual_amount_cents"] == 0:
            out["variance_bps"] = 0
        else:
            out["variance_bps"] = 1000000
    else:
        out["variance_cents"] = None
        out["variance_bps"] = None
    return out


def ser_report(r):
    return pub(r)


def ser_project(p):
    out = pub(p)
    aa = p["approved_amount_cents"]
    if aa is None:
        out["monthly_spend_cents"] = None
        out["final_month_spend_cents"] = None
    else:
        span = p["sched_end_month"] - p["sched_start_month"] + 1
        monthly = aa // span
        out["monthly_spend_cents"] = monthly
        out["final_month_spend_cents"] = aa - monthly * (span - 1)
    out["drawn_cents"] = project_drawn(p)
    return out


def ser_draw(d):
    return pub(d)


def ser_strategy(s):
    return pub(s)


def ser_loan(l):
    return pub(l)


def ser_covenant(c):
    return pub(c)


def ser_covenant_test(t):
    # Append-only record: id + created_at only (no updated_at / version).
    return {"id": t["id"], "covenant_id": t["covenant_id"], "period_label": t["period_label"],
            "measured_value_bps": t["measured_value_bps"],
            "annualized_noi_cents_used": t["annualized_noi_cents_used"],
            "result": t["result"], "created_at": t["created_at"]}


def ser_valuation(v):
    return pub(v)


def ser_scorecard(s):
    return pub(s)


def ser_reforecast(r):
    return pub(r)


def ser_decision(d):
    return pub(d)


def ser_lender_report(r):
    return pub(r)
