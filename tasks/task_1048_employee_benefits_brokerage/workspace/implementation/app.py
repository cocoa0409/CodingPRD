"""
Employee-Benefits Brokerage & Consulting API.

A single-file Flask implementation. In-memory storage only (Python dicts keyed
by id). The store starts empty on every boot; no seeding. Every behaviour traces
to a PRD sentence. See workspace/PRD.md.
"""

import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants (§1.3 / PRD §3)
# ---------------------------------------------------------------------------
ROLES = {"BenefitsConsultant", "CarrierRep", "ComplianceOfficer",
         "ClientContact", "PlatformAdmin"}

ALE_THRESHOLD = 50
AFFORDABILITY_PCT = Decimal("0.0912")
FPL_ANNUAL_CENTS = 1506000

COMMISSION_TIER1_CENTS = 6000000
COMMISSION_TIER2_CENTS = 12000000
BASE_MULT = Decimal("1.00")
COMMISSION_TIER1_MULT = Decimal("1.05")
COMMISSION_TIER2_MULT = Decimal("1.10")
LINE_MULT = {"MEDICAL": Decimal("1.00"), "DENTAL": Decimal("0.90"),
             "VISION": Decimal("0.85"), "LIFE": Decimal("0.95")}
TIER_FACTOR = {"EMPLOYEE_ONLY": Decimal("1.00"), "EMPLOYEE_SPOUSE": Decimal("2.00"),
               "EMPLOYEE_CHILD": Decimal("1.75"), "FAMILY": Decimal("2.85")}
RENEWAL_FLOOR_PCT = Decimal("0.50")

CLOCK_DEFAULT_ISO = "2026-07-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
clients = {}
census_members = {}
campaigns = {}
quotes = {}
policies = {}
renewals = {}
windows = {}
elections = {}
filings = {}
stoploss = {}

_seq_counter = 0
_clock = None  # logical clock (datetime, tz-aware)


def _reset_clock():
    global _clock
    _clock = parse_dt(CLOCK_DEFAULT_ISO)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_str():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def gen_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_dt(s):
    """Parse an ISO 8601 date or datetime string into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        # bare date fallback
        dt = datetime.fromisoformat(v + "T00:00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_dec(x):
    return Decimal(str(x))


def rhu(value):
    """Round a Decimal to whole cents, half-up, returning an int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_record(fields):
    rec = {
        "id": gen_id(),
        "created_at": now_str(),
        "updated_at": None,
        "version": 1,
        "_seq": next_seq(),
    }
    rec["updated_at"] = rec["created_at"]
    rec.update(fields)
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_str()


def get_json_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


# ---------------------------------------------------------------------------
# Response envelope (§2.2)
# ---------------------------------------------------------------------------
def build_meta(extra=None):
    meta = {"api_request_id": gen_request_id(), "api_request_timestamp": now_str()}
    if extra:
        meta.update(extra)
    return meta


def respond(data, response_type, status, meta_extra=None):
    body = {"meta": build_meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC (§2.1, §2.7)
# ---------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    return role, user_id


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def must_exist(store, rid):
    if rid is None or rid not in store:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return store[rid]


# ---------------------------------------------------------------------------
# Field-shape helpers (§2.7 priority 14)
# ---------------------------------------------------------------------------
def require_present(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_FIELD", 422, f"Missing required field: {f}")


def as_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_FIELD", 422, f"Field {field} must be an integer")
    return v


# ---------------------------------------------------------------------------
# Pagination (§2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(store, serialize, filters=None):
    items = list(store.values())
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [it for it in items if it.get(key) == val]
    items.sort(key=lambda r: r["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    data = [serialize(it) for it in page]
    meta_extra = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": has_more}
    return respond(data, "array", 200, meta_extra)


COMMON_OUT = ["id", "created_at", "updated_at", "version"]


def base_out(rec, fields):
    out = {k: rec[k] for k in COMMON_OUT}
    for f in fields:
        out[f] = rec.get(f)
    return out


# ---------------------------------------------------------------------------
# Computed reporting (§2.8, §3.1)
# ---------------------------------------------------------------------------
def compute_client(c):
    cid = c["id"]
    fte = sum(1 for m in census_members.values()
              if m["client_id"] == cid and m["status"] == "ACTIVE"
              and m["employment_type"] == "FULL_TIME")
    emp = sum(1 for m in census_members.values()
              if m["client_id"] == cid and m["status"] == "ACTIVE")
    enrolled = sum(1 for e in elections.values()
                   if e["status"] == "CONFIRMED"
                   and windows.get(e["window_id"], {}).get("client_id") == cid)
    active_prem = sum(p["monthly_premium_cents"] for p in policies.values()
                      if p["client_id"] == cid and p["lifecycle_status"] == "ACTIVE")
    ytd = sum(p["finalized_commission_cents"] for p in policies.values()
              if p["client_id"] == cid and p["commission_status"] == "FINALIZED")
    return fte, emp, (fte >= ALE_THRESHOLD), enrolled, active_prem, ytd


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_client(c):
    fte, emp, is_ale, enrolled, active_prem, ytd = compute_client(c)
    out = base_out(c, ["legal_name", "ein", "industry", "fiscal_year_end_month"])
    out["full_time_equivalent_count"] = fte
    out["employee_count"] = emp
    out["is_ale"] = is_ale
    out["enrolled_headcount"] = enrolled
    out["active_premium_total_cents"] = active_prem
    out["ytd_commission_cents"] = ytd
    return out


def ser_census(m):
    return base_out(m, ["client_id", "full_name", "birth_date", "annual_salary_cents",
                        "monthly_contribution_cents", "employment_type",
                        "affordable_rate_of_pay", "affordable_fpl", "status"])


def ser_campaign(x):
    return base_out(x, ["client_id", "coverage_line", "target_effective_date", "status"])


def ser_quote(q):
    return base_out(q, ["campaign_id", "carrier_name", "monthly_premium_cents",
                        "commission_rate_pct", "status"])


def ser_policy(p):
    return base_out(p, ["client_id", "quote_id", "coverage_line", "carrier_name",
                        "effective_date", "expiration_date", "original_premium_cents",
                        "monthly_premium_cents", "commission_rate_pct",
                        "estimated_commission_cents", "finalized_commission_cents",
                        "commission_status", "renewal_status", "lifecycle_status"])


def ser_renewal(r):
    return base_out(r, ["policy_id", "initial_offer_premium_cents",
                        "current_offer_premium_cents", "proposing_side",
                        "round_count", "agreed_premium_cents", "status"])


def ser_window(w):
    return base_out(w, ["client_id", "plan_year", "opens_at", "closes_at",
                        "total_confirmed_cents", "status"])


def ser_election(e):
    return base_out(e, ["window_id", "census_member_id", "policy_id", "coverage_tier",
                        "monthly_cost_cents", "status"])


def ser_filing(f):
    return base_out(f, ["client_id", "filing_type", "plan_year", "due_date",
                        "prepared_by_user_id", "certified_by_user_id", "status"])


def ser_stoploss(s):
    reimbursed = max(0, s["cumulative_claims_cents"] - s["attachment_point_cents"])
    wellness = rhu(to_dec(s["wellness_credit_pct"]) * Decimal(s["cumulative_claims_cents"]))
    out = base_out(s, ["client_id", "attachment_point_cents", "aggregate_limit_cents",
                       "wellness_credit_pct", "cumulative_claims_cents"])
    out["reimbursed_cents"] = reimbursed
    out["wellness_credit_cents"] = wellness
    out["total_recovery_cents"] = reimbursed + wellness
    return out


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_affordability(annual_salary_cents, monthly_contribution_cents):
    rate_thr = rhu(AFFORDABILITY_PCT * (Decimal(annual_salary_cents) / Decimal(12)))
    fpl_thr = rhu(AFFORDABILITY_PCT * (Decimal(FPL_ANNUAL_CENTS) / Decimal(12)))
    return (monthly_contribution_cents <= rate_thr,
            monthly_contribution_cents <= fpl_thr)


def estimate_commission(p):
    annual = p["monthly_premium_cents"] * 12
    base = Decimal(annual) * to_dec(p["commission_rate_pct"])
    if annual >= COMMISSION_TIER2_CENTS:
        vm = COMMISSION_TIER2_MULT
    elif annual >= COMMISSION_TIER1_CENTS:
        vm = COMMISSION_TIER1_MULT
    else:
        vm = BASE_MULT
    lm = LINE_MULT[p["coverage_line"]]
    return rhu(base * vm * lm)


def finalize_commission_value(p):
    eff = parse_dt(p["effective_date"])
    months = (_clock.year - eff.year) * 12 + (_clock.month - eff.month)
    months = max(0, months)
    lm = LINE_MULT[p["coverage_line"]]
    return rhu(Decimal(p["monthly_premium_cents"]) * to_dec(p["commission_rate_pct"])
               * Decimal(months) * lm)


def election_cost(p, tier):
    return rhu(Decimal(p["monthly_premium_cents"]) * TIER_FACTOR[tier])


# ===========================================================================
# CLIENT
# ===========================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    body = get_json_body()
    # field-shape (priority 14)
    require_present(body, ["legal_name", "ein", "industry", "fiscal_year_end_month"])
    m = body["fiscal_year_end_month"]
    if isinstance(m, bool) or not isinstance(m, int) or m < 1 or m > 12:
        raise ApiError("ERR_INVALID_FIELD", 422, "fiscal_year_end_month must be 1..12")
    # duplicate EIN (priority 16)
    if any(c["ein"] == body["ein"] for c in clients.values()):
        raise ApiError("ERR_DUPLICATE_EIN", 409, "EIN already in use")
    rec = new_record({
        "legal_name": body["legal_name"],
        "ein": body["ein"],
        "industry": body["industry"],
        "fiscal_year_end_month": m,
    })
    clients[rec["id"]] = rec
    return respond(ser_client(rec), "object", 201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    authenticate()
    return respond(ser_client(must_exist(clients, cid)), "object", 200)


@app.route("/clients", methods=["GET"])
def list_clients():
    authenticate()
    return list_response(clients, ser_client)


# ===========================================================================
# CENSUS MEMBER
# ===========================================================================
@app.route("/census-members", methods=["POST"])
def create_census():
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    body = get_json_body()
    # existence (priority 4) — only for a supplied FK
    if body.get("client_id") is not None:
        must_exist(clients, body["client_id"])
    # field-shape
    require_present(body, ["client_id", "full_name", "birth_date", "annual_salary_cents",
                           "monthly_contribution_cents", "employment_type"])
    aff_rop, aff_fpl = compute_affordability(body["annual_salary_cents"],
                                             body["monthly_contribution_cents"])
    rec = new_record({
        "client_id": body["client_id"],
        "full_name": body["full_name"],
        "birth_date": body["birth_date"],
        "annual_salary_cents": body["annual_salary_cents"],
        "monthly_contribution_cents": body["monthly_contribution_cents"],
        "employment_type": body["employment_type"],
        "affordable_rate_of_pay": aff_rop,
        "affordable_fpl": aff_fpl,
        "status": "ACTIVE",
    })
    census_members[rec["id"]] = rec
    return respond(ser_census(rec), "object", 201)


@app.route("/census-members/<mid>", methods=["GET"])
def get_census(mid):
    authenticate()
    return respond(ser_census(must_exist(census_members, mid)), "object", 200)


@app.route("/census-members", methods=["GET"])
def list_census():
    authenticate()
    return list_response(census_members, ser_census,
                         {"client_id": request.args.get("client_id")})


@app.route("/census-members/<mid>/terminate", methods=["POST"])
def terminate_census(mid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    m = must_exist(census_members, mid)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Member not ACTIVE")
    m["status"] = "TERMINATED"
    touch(m)
    return respond(ser_census(m), "object", 200)


# ===========================================================================
# MARKETING CAMPAIGN
# ===========================================================================
@app.route("/campaigns", methods=["POST"])
def create_campaign():
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    body = get_json_body()
    if body.get("client_id") is not None:
        must_exist(clients, body["client_id"])
    require_present(body, ["client_id", "coverage_line", "target_effective_date"])
    rec = new_record({
        "client_id": body["client_id"],
        "coverage_line": body["coverage_line"],
        "target_effective_date": body["target_effective_date"],
        "status": "DRAFT",
    })
    campaigns[rec["id"]] = rec
    return respond(ser_campaign(rec), "object", 201)


@app.route("/campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    authenticate()
    return respond(ser_campaign(must_exist(campaigns, cid)), "object", 200)


@app.route("/campaigns", methods=["GET"])
def list_campaigns():
    authenticate()
    return list_response(campaigns, ser_campaign,
                         {"client_id": request.args.get("client_id")})


@app.route("/campaigns/<cid>/open", methods=["POST"])
def open_campaign(cid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    c = must_exist(campaigns, cid)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Campaign not DRAFT")
    c["status"] = "OPEN"
    touch(c)
    return respond(ser_campaign(c), "object", 200)


# ===========================================================================
# CARRIER QUOTE
# ===========================================================================
@app.route("/quotes", methods=["POST"])
def create_quote():
    role, _ = authenticate()
    authorize(role, {"CarrierRep"})
    body = get_json_body()
    if body.get("campaign_id") is not None:
        must_exist(campaigns, body["campaign_id"])
    require_present(body, ["campaign_id", "carrier_name", "monthly_premium_cents",
                           "commission_rate_pct"])
    prem = body["monthly_premium_cents"]
    if isinstance(prem, bool) or not isinstance(prem, int) or prem < 1:
        raise ApiError("ERR_INVALID_FIELD", 422, "monthly_premium_cents must be >= 1")
    rate = body["commission_rate_pct"]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) \
            or rate < 0 or rate > 1:
        raise ApiError("ERR_INVALID_FIELD", 422, "commission_rate_pct must be in [0,1]")
    rec = new_record({
        "campaign_id": body["campaign_id"],
        "carrier_name": body["carrier_name"],
        "monthly_premium_cents": prem,
        "commission_rate_pct": rate,
        "status": "SUBMITTED",
    })
    quotes[rec["id"]] = rec
    return respond(ser_quote(rec), "object", 201)


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    authenticate()
    return respond(ser_quote(must_exist(quotes, qid)), "object", 200)


@app.route("/quotes", methods=["GET"])
def list_quotes():
    authenticate()
    return list_response(quotes, ser_quote,
                         {"campaign_id": request.args.get("campaign_id")})


@app.route("/quotes/<qid>/select", methods=["POST"])
def select_quote(qid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    q = must_exist(quotes, qid)
    campaign = campaigns.get(q["campaign_id"])
    if q["status"] != "SUBMITTED" or campaign is None or campaign["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Quote not SUBMITTED or campaign not OPEN")
    q["status"] = "SELECTED"
    touch(q)
    campaign["status"] = "CLOSED"
    touch(campaign)
    for sib in quotes.values():
        if sib["campaign_id"] == campaign["id"] and sib["id"] != q["id"] \
                and sib["status"] == "SUBMITTED":
            sib["status"] = "DECLINED"
            touch(sib)
    return respond(ser_quote(q), "object", 200)


# ===========================================================================
# POLICY
# ===========================================================================
@app.route("/policies", methods=["POST"])
def create_policy():
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    body = get_json_body()
    # existence (priority 4)
    if body.get("client_id") is not None:
        must_exist(clients, body["client_id"])
    quote = None
    if body.get("quote_id") is not None:
        quote = must_exist(quotes, body["quote_id"])
    # quote referential (priority 9)
    if quote is not None and body.get("client_id") is not None:
        campaign = campaigns.get(quote["campaign_id"])
        if quote["status"] != "SELECTED" or campaign is None \
                or campaign["client_id"] != body["client_id"]:
            raise ApiError("ERR_QUOTE_NOT_SELECTED", 409,
                           "Quote is not SELECTED or not on a campaign of this client")
    # field-shape (priority 14)
    require_present(body, ["client_id", "quote_id", "effective_date", "expiration_date"])
    eff = parse_dt(body["effective_date"])
    exp = parse_dt(body["expiration_date"])
    if not (exp > eff):
        raise ApiError("ERR_INVALID_FIELD", 422,
                       "expiration_date must be after effective_date")
    campaign = campaigns.get(quote["campaign_id"])
    rec = new_record({
        "client_id": body["client_id"],
        "quote_id": body["quote_id"],
        "coverage_line": campaign["coverage_line"],
        "carrier_name": quote["carrier_name"],
        "effective_date": body["effective_date"],
        "expiration_date": body["expiration_date"],
        "original_premium_cents": quote["monthly_premium_cents"],
        "monthly_premium_cents": quote["monthly_premium_cents"],
        "commission_rate_pct": quote["commission_rate_pct"],
        "estimated_commission_cents": 0,
        "finalized_commission_cents": 0,
        "commission_status": "PENDING",
        "renewal_status": "NONE",
        "lifecycle_status": "BOUND",
    })
    rec["estimated_commission_cents"] = estimate_commission(rec)
    policies[rec["id"]] = rec
    return respond(ser_policy(rec), "object", 201)


@app.route("/policies/<pid>", methods=["GET"])
def get_policy(pid):
    authenticate()
    return respond(ser_policy(must_exist(policies, pid)), "object", 200)


@app.route("/policies", methods=["GET"])
def list_policies():
    authenticate()
    return list_response(policies, ser_policy,
                         {"client_id": request.args.get("client_id"),
                          "quote_id": request.args.get("quote_id")})


@app.route("/policies/<pid>/activate", methods=["POST"])
def activate_policy(pid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    p = must_exist(policies, pid)
    if p["lifecycle_status"] != "BOUND":
        raise ApiError("ERR_INVALID_STATE", 409, "Policy not BOUND")
    # coverage overlap (priority 12) — closed interval, touching conflicts
    eff = parse_dt(p["effective_date"])
    exp = parse_dt(p["expiration_date"])
    for other in policies.values():
        if other["id"] == p["id"]:
            continue
        if other["client_id"] != p["client_id"] \
                or other["coverage_line"] != p["coverage_line"] \
                or other["lifecycle_status"] != "ACTIVE":
            continue
        o_eff = parse_dt(other["effective_date"])
        o_exp = parse_dt(other["expiration_date"])
        if eff <= o_exp and o_eff <= exp:
            raise ApiError("ERR_COVERAGE_OVERLAP", 409,
                           "Overlaps an ACTIVE policy of same client and coverage line")
    p["lifecycle_status"] = "ACTIVE"
    touch(p)
    return respond(ser_policy(p), "object", 200)


@app.route("/policies/<pid>/terminate", methods=["POST"])
def terminate_policy(pid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    p = must_exist(policies, pid)
    if p["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Policy not ACTIVE")
    p["lifecycle_status"] = "TERMINATED"
    touch(p)
    return respond(ser_policy(p), "object", 200)


@app.route("/policies/<pid>/finalize-commission", methods=["POST"])
def finalize_commission(pid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    p = must_exist(policies, pid)
    if p["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Policy not ACTIVE")
    p["finalized_commission_cents"] = finalize_commission_value(p)
    p["commission_status"] = "FINALIZED"
    touch(p)
    return respond(ser_policy(p), "object", 200)


# ===========================================================================
# RENEWAL
# ===========================================================================
@app.route("/renewals", methods=["POST"])
def create_renewal():
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    body = get_json_body()
    # existence (priority 4)
    policy = None
    if body.get("policy_id") is not None:
        policy = must_exist(policies, body["policy_id"])
    # state (priority 5): policy ACTIVE
    if policy is not None and policy["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Policy not ACTIVE")
    # concurrency (priority 6): expected_policy_version matches
    if policy is not None and body.get("expected_policy_version") is not None:
        if body["expected_policy_version"] != policy["version"]:
            raise ApiError("ERR_STALE_POLICY_VERSION", 412,
                           "expected_policy_version does not match current Policy.version")
    # field-shape (priority 14)
    require_present(body, ["policy_id", "expected_policy_version",
                           "initial_offer_premium_cents"])
    offer = body["initial_offer_premium_cents"]
    if isinstance(offer, bool) or not isinstance(offer, int) or offer < 1:
        raise ApiError("ERR_INVALID_FIELD", 422,
                       "initial_offer_premium_cents must be >= 1")
    rec = new_record({
        "policy_id": body["policy_id"],
        "initial_offer_premium_cents": offer,
        "current_offer_premium_cents": offer,
        "proposing_side": "CARRIER",
        "round_count": 0,
        "agreed_premium_cents": 0,
        "status": "OPEN",
    })
    renewals[rec["id"]] = rec
    # side effects on policy
    policy["version"] += 1
    policy["updated_at"] = now_str()
    policy["renewal_status"] = "RENEWING"
    return respond(ser_renewal(rec), "object", 201)


@app.route("/renewals/<rid>", methods=["GET"])
def get_renewal(rid):
    authenticate()
    return respond(ser_renewal(must_exist(renewals, rid)), "object", 200)


@app.route("/renewals", methods=["GET"])
def list_renewals():
    authenticate()
    return list_response(renewals, ser_renewal,
                         {"policy_id": request.args.get("policy_id")})


@app.route("/renewals/<rid>/counter", methods=["POST"])
def counter_renewal(rid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant", "CarrierRep"})
    r = must_exist(renewals, rid)
    actor_side = "BROKER" if role == "BenefitsConsultant" else "CARRIER"
    # state (priority 5)
    if r["status"] == "OPEN":
        pass
    elif r["status"] == "NEGOTIATING":
        if actor_side == r["proposing_side"]:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A side may not counter its own standing offer")
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Renewal not open for counters")
    body = get_json_body()
    require_present(body, ["proposed_premium_cents"])
    r["current_offer_premium_cents"] = body["proposed_premium_cents"]
    r["proposing_side"] = actor_side
    r["round_count"] += 1
    r["status"] = "NEGOTIATING"
    touch(r)
    return respond(ser_renewal(r), "object", 200)


@app.route("/renewals/<rid>/settle", methods=["POST"])
def settle_renewal(rid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    r = must_exist(renewals, rid)
    # state (priority 5)
    if r["status"] not in ("OPEN", "NEGOTIATING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Renewal not settleable")
    body = get_json_body()
    action = body.get("action")
    # field-shape (priority 14)
    if action not in ("ACCEPT", "DECLINE"):
        raise ApiError("ERR_INVALID_FIELD", 422, "action must be ACCEPT or DECLINE")
    policy = policies.get(r["policy_id"])
    if action == "ACCEPT":
        # renewal floor (priority 15)
        floor = rhu(RENEWAL_FLOOR_PCT * Decimal(policy["original_premium_cents"]))
        if r["current_offer_premium_cents"] < floor:
            raise ApiError("ERR_PREMIUM_BELOW_FLOOR", 409,
                           "Current offer is below the renewal floor")
        r["status"] = "AGREED"
        r["agreed_premium_cents"] = r["current_offer_premium_cents"]
        touch(r)
        policy["monthly_premium_cents"] = r["agreed_premium_cents"]
        policy["renewal_status"] = "RENEWED"
        policy["estimated_commission_cents"] = estimate_commission(policy)
        touch(policy)
    else:  # DECLINE
        r["status"] = "DECLINED"
        touch(r)
        policy["renewal_status"] = "NONE"
        touch(policy)
    return respond(ser_renewal(r), "object", 200)


# ===========================================================================
# ENROLLMENT WINDOW
# ===========================================================================
@app.route("/enrollment-windows", methods=["POST"])
def create_window():
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    body = get_json_body()
    if body.get("client_id") is not None:
        must_exist(clients, body["client_id"])
    # window overlap (priority 11) — half-open [opens_at, closes_at), strict
    if body.get("opens_at") is not None and body.get("closes_at") is not None \
            and body.get("client_id") is not None:
        try:
            opens = parse_dt(body["opens_at"])
            closes = parse_dt(body["closes_at"])
        except (ValueError, TypeError):
            opens = closes = None
        if opens is not None and closes is not None:
            for w in windows.values():
                if w["client_id"] != body["client_id"]:
                    continue
                w_opens = parse_dt(w["opens_at"])
                w_closes = parse_dt(w["closes_at"])
                if opens < w_closes and w_opens < closes:
                    raise ApiError("ERR_WINDOW_OVERLAP", 409,
                                   "Window overlaps an existing window for this client")
    # field-shape (priority 14)
    require_present(body, ["client_id", "plan_year", "opens_at", "closes_at"])
    opens = parse_dt(body["opens_at"])
    closes = parse_dt(body["closes_at"])
    if not (closes > opens):
        raise ApiError("ERR_INVALID_FIELD", 422, "closes_at must be after opens_at")
    rec = new_record({
        "client_id": body["client_id"],
        "plan_year": body["plan_year"],
        "opens_at": body["opens_at"],
        "closes_at": body["closes_at"],
        "total_confirmed_cents": 0,
        "status": "SCHEDULED",
    })
    windows[rec["id"]] = rec
    return respond(ser_window(rec), "object", 201)


@app.route("/enrollment-windows/<wid>", methods=["GET"])
def get_window(wid):
    authenticate()
    return respond(ser_window(must_exist(windows, wid)), "object", 200)


@app.route("/enrollment-windows", methods=["GET"])
def list_windows():
    authenticate()
    return list_response(windows, ser_window,
                         {"client_id": request.args.get("client_id")})


@app.route("/enrollment-windows/<wid>/open", methods=["POST"])
def open_window(wid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    w = must_exist(windows, wid)
    if w["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not SCHEDULED")
    if _clock < parse_dt(w["opens_at"]):
        raise ApiError("ERR_WINDOW_NOT_YET_OPEN", 409, "Clock has not reached opens_at")
    w["status"] = "OPEN"
    touch(w)
    return respond(ser_window(w), "object", 200)


@app.route("/enrollment-windows/<wid>/finalize", methods=["POST"])
def finalize_window(wid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    w = must_exist(windows, wid)
    if w["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not OPEN")
    if _clock < parse_dt(w["closes_at"]):
        raise ApiError("ERR_WINDOW_NOT_CLOSED", 409, "Clock has not reached closes_at")
    # cascade: confirm still-SELECTED elections
    for e in elections.values():
        if e["window_id"] == w["id"] and e["status"] == "SELECTED":
            policy = policies.get(e["policy_id"])
            e["monthly_cost_cents"] = election_cost(policy, e["coverage_tier"])
            e["status"] = "CONFIRMED"
            touch(e)
    total = sum(e["monthly_cost_cents"] for e in elections.values()
                if e["window_id"] == w["id"] and e["status"] == "CONFIRMED")
    w["total_confirmed_cents"] = total
    w["status"] = "FINALIZED"
    touch(w)
    return respond(ser_window(w), "object", 200)


# ===========================================================================
# ELECTION
# ===========================================================================
def _election_ownership(user_id, window):
    if window is not None and window["client_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "ClientContact may only act on its own client's resources")


@app.route("/elections", methods=["POST"])
def create_election():
    role, user_id = authenticate()
    authorize(role, {"ClientContact"})
    body = get_json_body()
    window = windows.get(body.get("window_id")) if body.get("window_id") else None
    # ownership (priority 3)
    _election_ownership(user_id, window)
    # existence (priority 4)
    if body.get("window_id") is not None:
        window = must_exist(windows, body["window_id"])
    member = None
    if body.get("census_member_id") is not None:
        member = must_exist(census_members, body["census_member_id"])
    policy = None
    if body.get("policy_id") is not None:
        policy = must_exist(policies, body["policy_id"])
    require_present(body, ["window_id", "census_member_id", "policy_id", "coverage_tier"])
    # state (priority 5): window OPEN
    if window["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment window not OPEN")
    # client consistency (priority 10)
    if not (window["client_id"] == member["client_id"] == policy["client_id"]):
        raise ApiError("ERR_CLIENT_MISMATCH", 409,
                       "window, member and policy must belong to the same client")
    rec = new_record({
        "window_id": body["window_id"],
        "census_member_id": body["census_member_id"],
        "policy_id": body["policy_id"],
        "coverage_tier": body["coverage_tier"],
        "monthly_cost_cents": 0,
        "status": "SELECTED",
    })
    elections[rec["id"]] = rec
    return respond(ser_election(rec), "object", 201)


@app.route("/elections/<eid>", methods=["GET"])
def get_election(eid):
    authenticate()
    return respond(ser_election(must_exist(elections, eid)), "object", 200)


@app.route("/elections", methods=["GET"])
def list_elections():
    authenticate()
    return list_response(elections, ser_election,
                         {"window_id": request.args.get("window_id"),
                          "census_member_id": request.args.get("census_member_id"),
                          "policy_id": request.args.get("policy_id")})


@app.route("/elections/<eid>/confirm", methods=["POST"])
def confirm_election(eid):
    role, user_id = authenticate()
    authorize(role, {"ClientContact"})
    e = elections.get(eid)
    if e is not None:
        _election_ownership(user_id, windows.get(e["window_id"]))
    e = must_exist(elections, eid)
    window = windows.get(e["window_id"])
    policy = policies.get(e["policy_id"])
    if e["status"] != "SELECTED" or window["status"] != "OPEN" \
            or policy["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Election not SELECTED, or window not OPEN, or policy not ACTIVE")
    e["monthly_cost_cents"] = election_cost(policy, e["coverage_tier"])
    e["status"] = "CONFIRMED"
    touch(e)
    return respond(ser_election(e), "object", 200)


@app.route("/elections/<eid>/waive", methods=["POST"])
def waive_election(eid):
    role, user_id = authenticate()
    authorize(role, {"ClientContact"})
    e = elections.get(eid)
    if e is not None:
        _election_ownership(user_id, windows.get(e["window_id"]))
    e = must_exist(elections, eid)
    window = windows.get(e["window_id"])
    if e["status"] != "SELECTED" or window["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Election not SELECTED or window not OPEN")
    e["status"] = "WAIVED"
    touch(e)
    return respond(ser_election(e), "object", 200)


@app.route("/elections/<eid>/withdraw", methods=["POST"])
def withdraw_election(eid):
    role, user_id = authenticate()
    authorize(role, {"ClientContact"})
    e = elections.get(eid)
    if e is not None:
        _election_ownership(user_id, windows.get(e["window_id"]))
    e = must_exist(elections, eid)
    if e["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Election not CONFIRMED")
    e["status"] = "WITHDRAWN"
    touch(e)
    return respond(ser_election(e), "object", 200)


# ===========================================================================
# COMPLIANCE FILING
# ===========================================================================
@app.route("/filings", methods=["POST"])
def create_filing():
    role, _ = authenticate()
    authorize(role, {"ComplianceOfficer"})
    body = get_json_body()
    if body.get("client_id") is not None:
        must_exist(clients, body["client_id"])
    require_present(body, ["client_id", "filing_type", "plan_year", "due_date"])
    rec = new_record({
        "client_id": body["client_id"],
        "filing_type": body["filing_type"],
        "plan_year": body["plan_year"],
        "due_date": body["due_date"],
        "prepared_by_user_id": None,
        "certified_by_user_id": None,
        "status": "DRAFT",
    })
    filings[rec["id"]] = rec
    return respond(ser_filing(rec), "object", 201)


@app.route("/filings/<fid>", methods=["GET"])
def get_filing(fid):
    authenticate()
    return respond(ser_filing(must_exist(filings, fid)), "object", 200)


@app.route("/filings", methods=["GET"])
def list_filings():
    authenticate()
    return list_response(filings, ser_filing,
                         {"client_id": request.args.get("client_id")})


@app.route("/filings/<fid>/prepare", methods=["POST"])
def prepare_filing(fid):
    role, user_id = authenticate()
    authorize(role, {"ComplianceOfficer"})
    f = must_exist(filings, fid)
    if f["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Filing not DRAFT")
    f["prepared_by_user_id"] = user_id
    f["status"] = "PREPARED"
    touch(f)
    return respond(ser_filing(f), "object", 200)


@app.route("/filings/<fid>/certify", methods=["POST"])
def certify_filing(fid):
    role, user_id = authenticate()
    authorize(role, {"ComplianceOfficer"})
    f = must_exist(filings, fid)
    # state (priority 5)
    if f["status"] != "PREPARED":
        raise ApiError("ERR_INVALID_STATE", 409, "Filing not PREPARED")
    # segregation of duties (priority 7)
    if user_id == f["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Certifier must differ from preparer")
    # active-coverage referential (priority 8)
    has_active = any(p["client_id"] == f["client_id"]
                     and p["lifecycle_status"] == "ACTIVE" for p in policies.values())
    if not has_active:
        raise ApiError("ERR_NO_ACTIVE_COVERAGE", 409,
                       "Client has no ACTIVE policy")
    f["certified_by_user_id"] = user_id
    f["status"] = "CERTIFIED"
    touch(f)
    return respond(ser_filing(f), "object", 200)


@app.route("/filings/<fid>/file", methods=["POST"])
def file_filing(fid):
    role, _ = authenticate()
    authorize(role, {"ComplianceOfficer"})
    f = must_exist(filings, fid)
    if f["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Filing not CERTIFIED")
    if _clock <= parse_dt(f["due_date"]):
        f["status"] = "FILED"
    else:
        f["status"] = "LATE"
    touch(f)
    return respond(ser_filing(f), "object", 200)


# ===========================================================================
# STOP-LOSS POLICY
# ===========================================================================
@app.route("/stop-loss-policies", methods=["POST"])
def create_stoploss():
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    body = get_json_body()
    if body.get("client_id") is not None:
        must_exist(clients, body["client_id"])
    require_present(body, ["client_id", "attachment_point_cents",
                           "aggregate_limit_cents", "wellness_credit_pct"])
    ap = body["attachment_point_cents"]
    if isinstance(ap, bool) or not isinstance(ap, int) or ap < 1:
        raise ApiError("ERR_INVALID_FIELD", 422, "attachment_point_cents must be >= 1")
    rec = new_record({
        "client_id": body["client_id"],
        "attachment_point_cents": ap,
        "aggregate_limit_cents": body["aggregate_limit_cents"],
        "wellness_credit_pct": body["wellness_credit_pct"],
        "cumulative_claims_cents": 0,
    })
    stoploss[rec["id"]] = rec
    return respond(ser_stoploss(rec), "object", 201)


@app.route("/stop-loss-policies/<sid>", methods=["GET"])
def get_stoploss(sid):
    authenticate()
    return respond(ser_stoploss(must_exist(stoploss, sid)), "object", 200)


@app.route("/stop-loss-policies", methods=["GET"])
def list_stoploss():
    authenticate()
    return list_response(stoploss, ser_stoploss,
                         {"client_id": request.args.get("client_id")})


@app.route("/stop-loss-policies/<sid>/record-claim", methods=["POST"])
def record_claim(sid):
    role, _ = authenticate()
    authorize(role, {"BenefitsConsultant"})
    s = must_exist(stoploss, sid)
    body = get_json_body()
    require_present(body, ["claim_amount_cents"])
    s["cumulative_claims_cents"] += body["claim_amount_cents"]
    touch(s)
    return respond(ser_stoploss(s), "object", 200)


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = authenticate()
    authorize(role, {"PlatformAdmin"})
    global _clock
    body = get_json_body()
    require_present(body, ["to_iso8601"])
    _clock = parse_dt(body["to_iso8601"])
    return respond({}, "object", 200)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
_reset_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
