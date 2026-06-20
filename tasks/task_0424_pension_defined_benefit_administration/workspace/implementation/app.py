"""
Pension / Defined-Benefit Plan Administration (PBGC) API.

Single-file Flask implementation. In-memory storage only (Python dicts keyed by
id). Store starts EMPTY on every boot; no seeding, no preloaded entities.
"""

import os
import re
import uuid
import random
import string
import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# Constants (from SCAFFOLD calculations / PRD §3)
# =============================================================================
MEASUREMENT_DATE_CONST = datetime.date(2025, 1, 1)
COMP_LIMIT_CENTS = 33000000
CLIFF_YEARS = 3
FULL_VEST_YEARS = 7
ANNUITY_CONVERSION_FACTOR = Decimal("12.0")

BASE_JS_FACTOR = Decimal("1.00")
SURVIVOR_LOAD = Decimal("0.12")
AGE_DIFF_LOAD = Decimal("0.005")
FACTOR_FLOOR = Decimal("0.70")
FACTOR_CEIL = Decimal("1.00")

SLA_ANNUITY_FACTOR = Decimal("12.5")
SEGMENT_FACTOR_65_PLUS = Decimal("12.4")
SEGMENT_FACTOR_60_64 = Decimal("11.9")
SEGMENT_FACTOR_55_59 = Decimal("10.8")
RELATIVE_VALUE_FLOOR = Decimal("0.95")

EARLY_RETIREMENT_AGE = 55

FLAT_RATE_PER_HEAD_CENTS = 10100
VARIABLE_RATE = Decimal("0.0052")
VARIABLE_CAP_PER_HEAD_CENTS = 65200

RESTRICTED_FLOOR = Decimal("0.60")
OPEN_FLOOR = Decimal("0.80")

ROLES = {"PlanSponsor", "PlanActuary", "BenefitsAdministrator"}

# =============================================================================
# In-memory data store (empty on boot)
# =============================================================================
class Store:
    def __init__(self):
        self.plans = {}
        self.participants = {}
        self.compensations = {}
        self.service_adjustments = {}
        self.filings = {}
        self.premiums = {}
        self.elections = {}
        self.qdros = {}
        self.payments = {}
        self.spousal_consents = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_PARTICIPANT_NOT_ELIGIBLE": 409,
    "ERR_PARTICIPANT_NOT_VESTED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_FUNDING_RESTRICTED": 409,
    "ERR_SPOUSAL_CONSENT_REQUIRED": 409,
    "ERR_RELATIVE_VALUE_FAILED": 409,
    "ERR_QDRO_TOO_LATE": 409,
    "ERR_QDRO_OVER_ALLOCATED": 409,
    "ERR_QDRO_PENDING": 409,
    "ERR_BENEFIT_NOT_AVAILABLE": 409,
    "ERR_NO_COLA_CONFIGURED": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)


# =============================================================================
# Response envelope helpers
# =============================================================================
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _now_iso():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_response(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return ok(items, status=200, response_type="array", pagination=pagination)


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)},
    }
    return jsonify(body), 422


# =============================================================================
# Auth / RBAC
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip() or not role or not role.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed authentication headers.")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header.")
    g.user_id = uid
    g.role = role


def require_roles(*allowed):
    if g.role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this endpoint.")


# =============================================================================
# Rounding / numeric helpers
# =============================================================================
def round_half_up(value):
    """Round a Decimal to the nearest integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_ratio(value, places):
    q = Decimal(10) ** -places
    return float(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


# =============================================================================
# Common field bookkeeping
# =============================================================================
def new_common(light=False):
    """Create the common server fields. light=True for append-only/immutable
    records (ServiceCreditAdjustment, SpousalConsent) which carry only id +
    created_at."""
    now = _now_iso()
    rec = {"id": str(uuid.uuid4()), "created_at": now}
    rec["_seq"] = db.next_seq()
    if not light:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = _now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal fields (those starting with _) for output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# =============================================================================
# Request body parsing helpers
# =============================================================================
def get_body():
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
        if data is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}.")
    return body[name]


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string.")
    return v


def require_int(body, name, non_negative=True):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer.")
    if non_negative and v < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be non-negative.")
    return v


def require_number(body, name, non_negative=True):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number.")
    if non_negative and v < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be non-negative.")
    return v


def require_enum(body, name, allowed):
    v = require_str(body, name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}.")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean.")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def parse_date(value, field):
    """Parse an ISO-8601 date or datetime string into a date object."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO-8601 date.")
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "T" in value or " " in value:
            dt = datetime.datetime.fromisoformat(s)
            return dt.date()
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO-8601 date.")


def require_date(body, name):
    v = require_field(body, name)
    parse_date(v, name)  # validation
    return v  # store the original string


# =============================================================================
# Pagination
# =============================================================================
def get_pagination():
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit_v < 1:
            limit_v = 1
        if limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v


def paginate_and_sort(records):
    """Sort by creation order ascending and paginate."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], total, limit, offset


# =============================================================================
# Lookups
# =============================================================================
def get_plan(plan_id):
    p = db.plans.get(plan_id)
    if not p:
        raise err("ERR_NOT_FOUND", "Plan not found.")
    return p


def get_participant(pid):
    p = db.participants.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", "Participant not found.")
    return p


def get_filing(fid):
    f = db.filings.get(fid)
    if not f:
        raise err("ERR_NOT_FOUND", "Filing not found.")
    return f


def get_premium(pid):
    p = db.premiums.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", "Premium filing not found.")
    return p


def get_election(eid):
    e = db.elections.get(eid)
    if not e:
        raise err("ERR_NOT_FOUND", "Election not found.")
    return e


def get_qdro(qid):
    q = db.qdros.get(qid)
    if not q:
        raise err("ERR_NOT_FOUND", "QDRO not found.")
    return q


def get_payment(pid):
    p = db.payments.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", "Payment not found.")
    return p


# =============================================================================
# Date / age helpers
# =============================================================================
def to_date(s):
    return parse_date(s, "date")


def whole_age_at(dob_str, as_of_str):
    dob = to_date(dob_str)
    as_of = to_date(as_of_str)
    years = as_of.year - dob.year
    if (as_of.month, as_of.day) < (dob.month, dob.day):
        years -= 1
    return years


# =============================================================================
# Calculations
# =============================================================================
def calc_service_credit(participant):
    hire = to_date(participant["hire_date"])
    if participant["employment_status"] == "TERMINATED" and participant.get("termination_date"):
        measurement = to_date(participant["termination_date"])
    else:
        measurement = MEASUREMENT_DATE_CONST
    raw_days = (measurement - hire).days
    raw_years = Decimal(raw_days) / Decimal("365.25")
    # floor(raw_years * 2) / 2 -- round DOWN to nearest half-year
    elapsed_halves = (raw_years * 2).to_integral_value(rounding=ROUND_DOWN)
    elapsed = elapsed_halves / Decimal(2)
    adj = Decimal("0")
    for a in db.service_adjustments.values():
        if a["participant_id"] == participant["id"]:
            adj += Decimal(str(a["delta_service_years"]))
    credited = elapsed + adj
    if credited < 0:
        credited = Decimal("0")
    participant["credited_service_years"] = float(credited)
    return credited


def calc_vesting(participant):
    y = Decimal(str(participant["credited_service_years"]))
    if y < CLIFF_YEARS:
        vested_pct = Decimal("0.00")
        status = "UNVESTED"
    elif y < FULL_VEST_YEARS:
        floor_y = int(y.to_integral_value(rounding=ROUND_DOWN))
        vested_pct = Decimal("0.20") * (floor_y - 2)
        status = "PARTIALLY_VESTED"
    else:
        vested_pct = Decimal("1.00")
        status = "FULLY_VESTED"
    participant["vested_pct"] = round_ratio(vested_pct, 2)
    participant["vesting_status"] = status


def calc_final_average_pay(participant):
    rows = [c for c in db.compensations.values() if c["participant_id"] == participant["id"]]
    rows.sort(key=lambda r: r["plan_year"])
    if not rows:
        participant["final_average_pay_cents"] = 0
        return
    if len(rows) >= 3:
        best_sum = None
        # consecutive windows of length 3; tie-break earliest starting plan_year
        for i in range(len(rows) - 2):
            window = rows[i:i + 3]
            s = sum(r["capped_comp_cents"] for r in window)
            if best_sum is None or s > best_sum:
                best_sum = s
        fap = round_half_up(Decimal(best_sum) / Decimal(3))
    else:
        total = sum(r["capped_comp_cents"] for r in rows)
        fap = round_half_up(Decimal(total) / Decimal(len(rows)))
    participant["final_average_pay_cents"] = fap


def calc_cash_balance(participant):
    """Build a running hypothetical account from pay credits + interest credits.

    The account is accumulated chronologically over the participant's
    compensation years: each year's capped compensation * pay-credit rate is
    added, and the running balance is interest-credited each year.
    """
    plan = db.plans.get(participant["plan_id"])
    if not plan:
        participant["cash_balance_account_cents"] = 0
        return
    pay_credit = Decimal(str(plan.get("cb_pay_credit_rate") or 0))
    interest = Decimal(str(plan.get("cb_interest_crediting_rate") or 0))
    rows = [c for c in db.compensations.values() if c["participant_id"] == participant["id"]]
    rows.sort(key=lambda r: r["plan_year"])
    account = Decimal("0")
    for r in rows:
        # interest-credit the existing balance forward one year, then add this
        # year's pay credit
        account = account * (Decimal("1") + interest)
        account += Decimal(r["capped_comp_cents"]) * pay_credit
    participant["cash_balance_account_cents"] = round_half_up(account)


def recompute_participant(participant):
    calc_service_credit(participant)
    calc_vesting(participant)
    plan = db.plans.get(participant["plan_id"])
    if plan and plan.get("benefit_formula_type") == "FINAL_AVERAGE_PAY":
        calc_final_average_pay(participant)
    elif plan and plan.get("benefit_formula_type") == "CASH_BALANCE":
        calc_cash_balance(participant)


def calc_benefit_formula(plan, participant):
    if plan["benefit_formula_type"] == "FINAL_AVERAGE_PAY":
        fap = Decimal(participant.get("final_average_pay_cents") or 0)
        rate = Decimal(str(plan.get("fap_accrual_rate") or 0))
        service = Decimal(str(participant["credited_service_years"]))
        vested = Decimal(str(participant["vested_pct"]))
        gross = round_half_up(fap * rate * service * vested / Decimal(12))
    else:  # CASH_BALANCE
        account = Decimal(participant.get("cash_balance_account_cents") or 0)
        vested = Decimal(str(participant["vested_pct"]))
        gross = round_half_up(account * vested / ANNUITY_CONVERSION_FACTOR / Decimal(12))
    return gross


def calc_js_reduction(election, participant, gross):
    form = election["payment_form"]
    if form in ("SINGLE_LIFE", "LUMP_SUM"):
        return gross
    # JOINT_AND_SURVIVOR
    asd = election["annuity_start_date"]
    p_age = whole_age_at(participant["date_of_birth"], asd)
    s_age = whole_age_at(election["spouse_date_of_birth"], asd)
    age_diff = Decimal(p_age - s_age)
    js_pct = Decimal(str(election["js_survivor_pct"]))
    factor = BASE_JS_FACTOR - (js_pct * SURVIVOR_LOAD) - (age_diff * AGE_DIFF_LOAD)
    if factor < FACTOR_FLOOR:
        factor = FACTOR_FLOOR
    if factor > FACTOR_CEIL:
        factor = FACTOR_CEIL
    return round_half_up(Decimal(gross) * factor)


def calc_lump_sum_apv(election, participant, gross):
    annual = Decimal(gross) * Decimal(12)
    sla_pv = round_half_up(annual * SLA_ANNUITY_FACTOR)
    age = whole_age_at(participant["date_of_birth"], election["annuity_start_date"])
    if age >= 65:
        ls_factor = SEGMENT_FACTOR_65_PLUS
    elif age >= 60:
        ls_factor = SEGMENT_FACTOR_60_64
    else:
        ls_factor = SEGMENT_FACTOR_55_59
    ls_value = round_half_up(annual * ls_factor)
    if sla_pv == 0:
        rv = 0.0
    else:
        rv = round_ratio(Decimal(ls_value) / Decimal(sla_pv), 4)
    return ls_value, sla_pv, rv


def calc_qdro_split_all(participant, base):
    """Walk QUALIFIED awards in created_at ASC order and assign carve-outs.
    Returns total carved."""
    awards = [q for q in db.qdros.values()
              if q["participant_id"] == participant["id"] and q["status"] == "QUALIFIED"]
    awards.sort(key=lambda q: (q["_seq"],))
    remaining = base
    for award in awards:
        if award["split_method"] == "PERCENTAGE":
            carve = round_half_up(Decimal(base) * Decimal(str(award["award_pct"])))
        else:  # SHARED_INTEREST
            carve = min(award["award_fixed_monthly_cents"], remaining)
        award["alternate_payee_monthly_cents"] = carve
        touch(award)
        remaining = remaining - carve
    return base - remaining


def calc_cola(payment, plan):
    cur = Decimal(payment["current_monthly_cents"])
    grown = round_half_up(cur * (Decimal("1") + Decimal(str(plan["cola_pct"]))))
    payment["current_monthly_cents"] = grown
    payment["cola_applied_count"] += 1


def calc_aftap(filing):
    target = Decimal(filing["funding_target_cents"])
    if target == 0:
        filing["aftap_pct"] = 0.0
        return
    filing["aftap_pct"] = round_ratio(
        Decimal(filing["plan_assets_cents"]) / target, 4)


def calc_pbgc_premium(filing):
    pc = filing["participant_count"]
    flat = pc * FLAT_RATE_PER_HEAD_CENTS
    raw_variable = round_half_up(Decimal(filing["unfunded_vested_benefits_cents"]) * VARIABLE_RATE)
    cap = pc * VARIABLE_CAP_PER_HEAD_CENTS
    variable = min(raw_variable, cap)
    filing["flat_rate_premium_cents"] = flat
    filing["variable_rate_premium_cents"] = variable
    filing["total_premium_cents"] = flat + variable


# =============================================================================
# Funding posture derivation
# =============================================================================
def derive_funding_posture(plan):
    """Recompute funding_posture from CERTIFIED filings (greatest plan_year,
    tie-break greatest created_at)."""
    certified = [f for f in db.filings.values()
                 if f["plan_id"] == plan["id"] and f["status"] == "CERTIFIED"]
    if not certified:
        plan["funding_posture"] = "OPEN"
        plan["latest_certified_filing_id"] = None
        return
    # greatest plan_year, tie-break greatest created_at (use _seq as proxy for created order)
    latest = max(certified, key=lambda f: (f["plan_year"], f["_seq"]))
    plan["latest_certified_filing_id"] = latest["id"]
    a = Decimal(str(latest["aftap_pct"]))
    if a >= OPEN_FLOOR:
        plan["funding_posture"] = "OPEN"
    elif a >= RESTRICTED_FLOOR:
        plan["funding_posture"] = "RESTRICTED"
    else:
        plan["funding_posture"] = "FROZEN"


# =============================================================================
# Routes: PensionPlan
# =============================================================================
@app.route("/plans", methods=["POST"])
def create_plan():
    authenticate()
    require_roles("PlanSponsor")
    body = get_body()
    plan_name = require_str(body, "plan_name")
    ein_psn = require_str(body, "ein_psn")
    formula_type = require_enum(body, "benefit_formula_type", {"FINAL_AVERAGE_PAY", "CASH_BALANCE"})

    nra = body.get("normal_retirement_age", 65)
    if nra is None:
        nra = 65
    if isinstance(nra, bool) or not isinstance(nra, int) or nra < 0:
        raise err("ERR_INVALID_REQUEST", "normal_retirement_age must be a non-negative integer.")

    cola = body.get("cola_pct", 0.0)
    if cola is None:
        cola = 0.0
    if isinstance(cola, bool) or not isinstance(cola, (int, float)) or cola < 0:
        raise err("ERR_INVALID_REQUEST", "cola_pct must be a non-negative number.")

    def opt_num(name):
        v = body.get(name)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise err("ERR_INVALID_REQUEST", f"{name} must be a non-negative number.")
        return v

    fap_rate = opt_num("fap_accrual_rate")
    cb_pay = opt_num("cb_pay_credit_rate")
    cb_int = opt_num("cb_interest_crediting_rate")

    # Uniqueness: ein_psn global
    for p in db.plans.values():
        if p["ein_psn"] == ein_psn:
            raise err("ERR_DUPLICATE_RESOURCE", "ein_psn already exists.")

    rec = new_common()
    rec.update({
        "plan_name": plan_name,
        "ein_psn": ein_psn,
        "benefit_formula_type": formula_type,
        "normal_retirement_age": nra,
        "cola_pct": cola,
        "fap_accrual_rate": fap_rate,
        "cb_pay_credit_rate": cb_pay,
        "cb_interest_crediting_rate": cb_int,
        "funding_posture": "OPEN",
        "latest_certified_filing_id": None,
        "status": "ACTIVE",
    })
    db.plans[rec["id"]] = rec
    return ok(public(rec), status=201)


@app.route("/plans/<plan_id>", methods=["GET"])
def get_plan_route(plan_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    plan = get_plan(plan_id)
    return ok(public(plan))


@app.route("/plans/<plan_id>/terminate", methods=["POST"])
def terminate_plan(plan_id):
    authenticate()
    require_roles("PlanSponsor")
    plan = get_plan(plan_id)
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan is not ACTIVE.")
    if plan["funding_posture"] == "RESTRICTED":
        raise err("ERR_FUNDING_RESTRICTED", "A RESTRICTED plan cannot be voluntarily terminated.")
    plan["status"] = "TERMINATING"
    touch(plan)
    # cascade: every IN_PAY or SUSPENDED payment under the plan -> TERMINATED
    for pay in db.payments.values():
        if pay["plan_id"] == plan_id and pay["status"] in ("IN_PAY", "SUSPENDED"):
            pay["status"] = "TERMINATED"
            touch(pay)
    return ok(public(plan))


# =============================================================================
# Routes: Participant
# =============================================================================
@app.route("/plans/participants", methods=["POST"])
def create_participant():
    authenticate()
    require_roles("BenefitsAdministrator")
    body = get_body()
    plan_id = require_str(body, "plan_id")
    ssn_last4 = require_str(body, "ssn_last4")
    dob = require_date(body, "date_of_birth")
    hire = require_date(body, "hire_date")

    plan = get_plan(plan_id)

    # Uniqueness: ssn_last4 per plan
    for p in db.participants.values():
        if p["plan_id"] == plan_id and p["ssn_last4"] == ssn_last4:
            raise err("ERR_DUPLICATE_RESOURCE", "ssn_last4 already exists in this plan.")

    rec = new_common()
    rec.update({
        "plan_id": plan_id,
        "ssn_last4": ssn_last4,
        "date_of_birth": dob,
        "hire_date": hire,
        "credited_service_years": 0.0,
        "final_average_pay_cents": 0,
        "cash_balance_account_cents": 0,
        "vesting_status": "UNVESTED",
        "vested_pct": 0.0,
        "employment_status": "ACTIVE",
        "termination_date": None,
    })
    db.participants[rec["id"]] = rec
    recompute_participant(rec)
    return ok(public(rec), status=201)


@app.route("/plans/participants/<participant_id>", methods=["GET"])
def get_participant_route(participant_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    p = get_participant(participant_id)
    return ok(public(p))


@app.route("/plans/participants", methods=["GET"])
def list_participants():
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    plan_id = request.args.get("plan_id")
    emp = request.args.get("employment_status")
    vest = request.args.get("vesting_status")
    recs = list(db.participants.values())
    if plan_id is not None:
        recs = [r for r in recs if r["plan_id"] == plan_id]
    if emp is not None:
        recs = [r for r in recs if r["employment_status"] == emp]
    if vest is not None:
        recs = [r for r in recs if r["vesting_status"] == vest]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


@app.route("/plans/participants/<participant_id>/terminate", methods=["POST"])
def terminate_participant(participant_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    p = get_participant(participant_id)
    body = get_body()
    term_date = require_date(body, "termination_date")
    if p["employment_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Participant is not ACTIVE.")
    if to_date(term_date) < to_date(p["hire_date"]):
        raise err("ERR_INVALID_REQUEST", "termination_date must be on or after hire_date.")
    p["employment_status"] = "TERMINATED"
    p["termination_date"] = term_date
    recompute_participant(p)
    touch(p)
    return ok(public(p))


@app.route("/plans/participants/<participant_id>/record-death", methods=["POST"])
def record_death(participant_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    p = get_participant(participant_id)
    if p["employment_status"] not in ("ACTIVE", "TERMINATED", "RETIRED"):
        raise err("ERR_INVALID_STATE", "Participant cannot transition to DECEASED.")
    p["employment_status"] = "DECEASED"
    touch(p)
    # cascade: any IN_PAY benefit payment for this participant -> TERMINATED
    for pay in db.payments.values():
        if pay["participant_id"] == participant_id and pay["status"] in ("IN_PAY", "SUSPENDED"):
            pay["status"] = "TERMINATED"
            touch(pay)
    return ok(public(p))


# =============================================================================
# Routes: AnnualCompensation
# =============================================================================
@app.route("/plans/compensation", methods=["POST"])
def create_compensation():
    authenticate()
    require_roles("BenefitsAdministrator")
    body = get_body()
    participant_id = require_str(body, "participant_id")
    plan_year = require_int(body, "plan_year")
    gross = require_int(body, "gross_comp_cents")

    p = get_participant(participant_id)

    # Uniqueness: plan_year per participant
    for c in db.compensations.values():
        if c["participant_id"] == participant_id and c["plan_year"] == plan_year:
            raise err("ERR_DUPLICATE_RESOURCE", "plan_year already exists for this participant.")

    rec = new_common()
    rec.update({
        "participant_id": participant_id,
        "plan_year": plan_year,
        "gross_comp_cents": gross,
        "capped_comp_cents": min(gross, COMP_LIMIT_CENTS),
    })
    db.compensations[rec["id"]] = rec
    recompute_participant(p)
    touch(p)
    return ok(public(rec), status=201)


@app.route("/plans/participants/<participant_id>/compensation", methods=["GET"])
def list_compensation(participant_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    get_participant(participant_id)
    recs = [c for c in db.compensations.values() if c["participant_id"] == participant_id]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


# =============================================================================
# Routes: ServiceCreditAdjustment
# =============================================================================
@app.route("/plans/service-adjustments", methods=["POST"])
def create_service_adjustment():
    authenticate()
    require_roles("BenefitsAdministrator")
    body = get_body()
    participant_id = require_str(body, "participant_id")
    kind = require_enum(body, "adjustment_kind",
                        {"MILITARY_BUYBACK", "BREAK_IN_SERVICE", "PRIOR_SERVICE_GRANT"})
    # delta may be negative (signed)
    delta = body.get("delta_service_years")
    if delta is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: delta_service_years.")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
        raise err("ERR_INVALID_REQUEST", "delta_service_years must be a number.")

    p = get_participant(participant_id)

    rec = new_common(light=True)
    rec.update({
        "participant_id": participant_id,
        "adjustment_kind": kind,
        "delta_service_years": delta,
        "applied": True,
    })
    db.service_adjustments[rec["id"]] = rec
    recompute_participant(p)
    touch(p)
    return ok(public(rec), status=201)


@app.route("/plans/participants/<participant_id>/service-adjustments", methods=["GET"])
def list_service_adjustments(participant_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    get_participant(participant_id)
    recs = [a for a in db.service_adjustments.values() if a["participant_id"] == participant_id]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


# =============================================================================
# Routes: PlanYearFiling
# =============================================================================
@app.route("/plans/filings", methods=["POST"])
def create_filing():
    authenticate()
    require_roles("PlanActuary")
    body = get_body()
    plan_id = require_str(body, "plan_id")
    plan_year = require_int(body, "plan_year")
    assets = require_int(body, "plan_assets_cents")
    target = require_int(body, "funding_target_cents")

    get_plan(plan_id)

    # Uniqueness: plan_year per plan
    for f in db.filings.values():
        if f["plan_id"] == plan_id and f["plan_year"] == plan_year:
            raise err("ERR_DUPLICATE_RESOURCE", "plan_year already exists for this plan.")

    rec = new_common()
    rec.update({
        "plan_id": plan_id,
        "plan_year": plan_year,
        "plan_assets_cents": assets,
        "funding_target_cents": target,
        "aftap_pct": 0.0,
        "status": "DRAFT",
    })
    calc_aftap(rec)
    db.filings[rec["id"]] = rec
    return ok(public(rec), status=201)


@app.route("/plans/filings/<filing_id>", methods=["GET"])
def get_filing_route(filing_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    f = get_filing(filing_id)
    return ok(public(f))


@app.route("/plans/filings", methods=["GET"])
def list_filings():
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    recs = list(db.filings.values())
    if plan_id is not None:
        recs = [r for r in recs if r["plan_id"] == plan_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


@app.route("/plans/filings/<filing_id>/certify", methods=["POST"])
def certify_filing(filing_id):
    authenticate()
    require_roles("PlanActuary")
    f = get_filing(filing_id)
    body = get_body()
    expected = require_int(body, "expected_plan_version")
    plan = db.plans.get(f["plan_id"])
    if not plan:
        raise err("ERR_NOT_FOUND", "Plan not found.")
    if f["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Filing is not DRAFT.")
    if f["funding_target_cents"] <= 0:
        raise err("ERR_INVALID_REQUEST", "funding_target_cents must be greater than zero.")
    # OCC check
    if expected != plan["version"]:
        raise err("ERR_STALE_VERSION", "Plan version is stale.")

    f["status"] = "CERTIFIED"
    calc_aftap(f)
    touch(f)
    # supersede earlier CERTIFIED filings with plan_year <= this filing's plan_year
    for other in db.filings.values():
        if (other["id"] != f["id"] and other["plan_id"] == plan["id"]
                and other["status"] == "CERTIFIED"
                and other["plan_year"] <= f["plan_year"]):
            other["status"] = "SUPERSEDED"
            touch(other)
    derive_funding_posture(plan)
    plan["version"] += 1
    plan["updated_at"] = _now_iso()
    return ok(public(f))


# =============================================================================
# Routes: PbgcPremiumFiling
# =============================================================================
@app.route("/plans/premiums", methods=["POST"])
def create_premium():
    authenticate()
    require_roles("PlanActuary", "PlanSponsor")
    body = get_body()
    plan_id = require_str(body, "plan_id")
    premium_year = require_int(body, "premium_year")
    count = require_int(body, "participant_count")
    uvb = require_int(body, "unfunded_vested_benefits_cents")

    get_plan(plan_id)

    # Uniqueness: premium_year per plan
    for p in db.premiums.values():
        if p["plan_id"] == plan_id and p["premium_year"] == premium_year:
            raise err("ERR_DUPLICATE_RESOURCE", "premium_year already exists for this plan.")

    rec = new_common()
    rec.update({
        "plan_id": plan_id,
        "premium_year": premium_year,
        "participant_count": count,
        "unfunded_vested_benefits_cents": uvb,
        "flat_rate_premium_cents": 0,
        "variable_rate_premium_cents": 0,
        "total_premium_cents": 0,
    })
    calc_pbgc_premium(rec)
    db.premiums[rec["id"]] = rec
    return ok(public(rec), status=201)


@app.route("/plans/premiums/<premium_id>", methods=["GET"])
def get_premium_route(premium_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    p = get_premium(premium_id)
    return ok(public(p))


@app.route("/plans/premiums", methods=["GET"])
def list_premiums():
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    plan_id = request.args.get("plan_id")
    premium_year = request.args.get("premium_year")
    recs = list(db.premiums.values())
    if plan_id is not None:
        recs = [r for r in recs if r["plan_id"] == plan_id]
    if premium_year is not None:
        try:
            py = int(premium_year)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "premium_year must be an integer.")
        recs = [r for r in recs if r["premium_year"] == py]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


# =============================================================================
# Routes: BenefitElection
# =============================================================================
@app.route("/plans/elections", methods=["POST"])
def create_election():
    authenticate()
    require_roles("BenefitsAdministrator")
    body = get_body()
    participant_id = require_str(body, "participant_id")
    payment_form = require_enum(body, "payment_form",
                                {"SINGLE_LIFE", "JOINT_AND_SURVIVOR", "LUMP_SUM"})
    asd = require_date(body, "annuity_start_date")

    p = get_participant(participant_id)

    js_pct = None
    spouse_dob = None
    if payment_form == "JOINT_AND_SURVIVOR":
        js_pct = body.get("js_survivor_pct")
        if js_pct is None:
            raise err("ERR_INVALID_REQUEST", "js_survivor_pct is required for JOINT_AND_SURVIVOR.")
        if isinstance(js_pct, bool) or not isinstance(js_pct, (int, float)):
            raise err("ERR_INVALID_REQUEST", "js_survivor_pct must be a number.")
        if float(js_pct) not in (0.50, 0.75, 1.00):
            raise err("ERR_INVALID_REQUEST", "js_survivor_pct must be 0.50, 0.75, or 1.00.")
        if "spouse_date_of_birth" not in body or body["spouse_date_of_birth"] is None:
            raise err("ERR_INVALID_REQUEST", "spouse_date_of_birth is required for JOINT_AND_SURVIVOR.")
        spouse_dob = require_date(body, "spouse_date_of_birth")

    rec = new_common()
    rec.update({
        "participant_id": participant_id,
        "plan_id": p["plan_id"],
        "payment_form": payment_form,
        "js_survivor_pct": js_pct,
        "spouse_date_of_birth": spouse_dob,
        "annuity_start_date": asd,
        "gross_accrued_monthly_cents": None,
        "js_reduced_monthly_cents": None,
        "lump_sum_value_cents": None,
        "relative_value_pct": None,
        "submitted_by_user_id": None,
        "status": "DRAFT",
    })
    db.elections[rec["id"]] = rec
    return ok(public(rec), status=201)


@app.route("/plans/elections/<election_id>", methods=["GET"])
def get_election_route(election_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    e = get_election(election_id)
    return ok(public(e))


@app.route("/plans/participants/<participant_id>/elections", methods=["GET"])
def list_participant_elections(participant_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    get_participant(participant_id)
    status = request.args.get("status")
    recs = [e for e in db.elections.values() if e["participant_id"] == participant_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


@app.route("/plans/elections/<election_id>/submit", methods=["POST"])
def submit_election(election_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    e = get_election(election_id)
    if e["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Election is not DRAFT.")
    p = get_participant(e["participant_id"])
    plan = db.plans.get(e["plan_id"])
    # Eligibility gates in PRD order
    if p["employment_status"] != "TERMINATED":
        raise err("ERR_PARTICIPANT_NOT_ELIGIBLE", "Participant must be TERMINATED.")
    if p["vesting_status"] != "FULLY_VESTED":
        raise err("ERR_PARTICIPANT_NOT_VESTED", "Participant must be FULLY_VESTED.")
    if e["payment_form"] == "LUMP_SUM" and plan and plan["funding_posture"] == "FROZEN":
        raise err("ERR_FUNDING_RESTRICTED", "A FROZEN plan cannot accept a lump-sum election.")
    age_at_asd = whole_age_at(p["date_of_birth"], e["annuity_start_date"])
    if age_at_asd < EARLY_RETIREMENT_AGE:
        raise err("ERR_BENEFIT_NOT_AVAILABLE", "Attained age below early-retirement age.")

    # Benefit math
    gross = calc_benefit_formula(plan, p)
    e["gross_accrued_monthly_cents"] = gross
    e["js_reduced_monthly_cents"] = calc_js_reduction(e, p, gross)
    if e["payment_form"] == "LUMP_SUM":
        ls_value, _sla, rv = calc_lump_sum_apv(e, p, gross)
        e["lump_sum_value_cents"] = ls_value
        e["relative_value_pct"] = rv
    e["submitted_by_user_id"] = g.user_id

    e["status"] = "SUBMITTED"
    # auto-route to SPOUSAL_CONSENT_PENDING for J&S / LUMP_SUM
    if e["payment_form"] in ("JOINT_AND_SURVIVOR", "LUMP_SUM"):
        e["status"] = "SPOUSAL_CONSENT_PENDING"
    touch(e)
    return ok(public(e))


@app.route("/plans/elections/<election_id>/approve", methods=["POST"])
def approve_election(election_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    e = get_election(election_id)
    if e["status"] not in ("SUBMITTED", "SPOUSAL_CONSENT_PENDING"):
        raise err("ERR_INVALID_STATE", "Election is not awaiting approval.")

    if e["status"] == "SUBMITTED":
        # SINGLE_LIFE direct-approval path
        if e["payment_form"] != "SINGLE_LIFE":
            # J&S / LUMP_SUM should be in SPOUSAL_CONSENT_PENDING; reaching here
            # means it isn't approvable from SUBMITTED.
            raise err("ERR_INVALID_STATE", "Election requires spousal consent routing.")
        if g.user_id == e["submitted_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from submitter.")
    else:  # SPOUSAL_CONSENT_PENDING
        consent = next((c for c in db.spousal_consents.values()
                        if c["election_id"] == election_id and c["waives_qjsa"] is True), None)
        if not consent:
            raise err("ERR_SPOUSAL_CONSENT_REQUIRED", "A spousal consent waiving QJSA is required.")
        if e["payment_form"] == "LUMP_SUM":
            rv = e.get("relative_value_pct")
            if rv is None or Decimal(str(rv)) < RELATIVE_VALUE_FLOOR:
                raise err("ERR_RELATIVE_VALUE_FAILED", "Relative value below floor.")
        if g.user_id == e["submitted_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from submitter.")

    e["status"] = "APPROVED"
    touch(e)
    return ok(public(e))


@app.route("/plans/elections/<election_id>/reject", methods=["POST"])
def reject_election(election_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    e = get_election(election_id)
    if e["status"] not in ("SUBMITTED", "SPOUSAL_CONSENT_PENDING"):
        raise err("ERR_INVALID_STATE", "Election cannot be rejected from its current state.")
    e["status"] = "REJECTED"
    touch(e)
    return ok(public(e))


@app.route("/plans/elections/<election_id>/reopen", methods=["POST"])
def reopen_election(election_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    e = get_election(election_id)
    if e["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED election may be re-opened.")
    # no BenefitPayment created for this election
    if any(pay["election_id"] == election_id for pay in db.payments.values()):
        raise err("ERR_INVALID_STATE", "A payment already exists for this election.")
    e["status"] = "DRAFT"
    e["gross_accrued_monthly_cents"] = None
    e["js_reduced_monthly_cents"] = None
    e["lump_sum_value_cents"] = None
    e["relative_value_pct"] = None
    e["submitted_by_user_id"] = None
    touch(e)
    return ok(public(e))


@app.route("/plans/elections/<election_id>/commence", methods=["POST"])
def commence_election(election_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    e = get_election(election_id)
    if e["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED election may be commenced.")
    p = get_participant(e["participant_id"])
    # all QdroAward for participant must be QUALIFIED or REJECTED (no DRAFT/SUBMITTED)
    for q in db.qdros.values():
        if q["participant_id"] == p["id"] and q["status"] in ("DRAFT", "SUBMITTED"):
            raise err("ERR_QDRO_PENDING", "A QDRO is still pending for the participant.")

    e["status"] = "COMMENCED"
    touch(e)

    # payment_setup: base = js_reduced - sum(QUALIFIED alternate_payee carve-outs)
    base = e["js_reduced_monthly_cents"] or 0
    carved = sum(q.get("alternate_payee_monthly_cents") or 0
                 for q in db.qdros.values()
                 if q["participant_id"] == p["id"] and q["status"] == "QUALIFIED")
    base_monthly = max(0, base - carved)

    pay = new_common()
    pay.update({
        "election_id": e["id"],
        "participant_id": p["id"],
        "plan_id": e["plan_id"],
        "base_monthly_cents": base_monthly,
        "current_monthly_cents": 0,
        "cola_applied_count": 0,
        "status": "PENDING_SETUP",
    })
    db.payments[pay["id"]] = pay

    # cascade: participant TERMINATED -> RETIRED
    if p["employment_status"] == "TERMINATED":
        p["employment_status"] = "RETIRED"
        touch(p)
    return ok(public(e))


@app.route("/plans/elections/<election_id>/spousal-consent", methods=["POST"])
def create_spousal_consent(election_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    e = get_election(election_id)
    body = get_body()
    dob = require_date(body, "consenting_spouse_dob")
    notary = require_str(body, "notary_reference")
    waives = require_bool(body, "waives_qjsa")

    # The DOB-match rule applies only when the election actually carries a
    # spouse_date_of_birth (JOINT_AND_SURVIVOR). A LUMP_SUM election has no
    # spouse_date_of_birth (PRD §3.4: it is ignored for non-J&S forms), yet it
    # still requires a SpousalConsent to be approved — so when the election has
    # no spouse_date_of_birth there is nothing to match against and the consent
    # is accepted.
    if e.get("spouse_date_of_birth") is not None and to_date(dob) != to_date(e["spouse_date_of_birth"]):
        raise err("ERR_INVALID_REQUEST", "consenting_spouse_dob must match the election spouse_date_of_birth.")

    rec = new_common(light=True)
    rec.update({
        "election_id": election_id,
        "consenting_spouse_dob": dob,
        "notary_reference": notary,
        "waives_qjsa": waives,
    })
    db.spousal_consents[rec["id"]] = rec
    return ok(public(rec), status=201)


@app.route("/plans/elections/<election_id>/spousal-consent", methods=["GET"])
def list_spousal_consents(election_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    get_election(election_id)
    recs = [c for c in db.spousal_consents.values() if c["election_id"] == election_id]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


# =============================================================================
# Routes: QdroAward
# =============================================================================
@app.route("/plans/qdros", methods=["POST"])
def create_qdro():
    authenticate()
    require_roles("BenefitsAdministrator")
    body = get_body()
    participant_id = require_str(body, "participant_id")
    kind = require_enum(body, "alternate_payee_kind", {"SPOUSE", "FORMER_SPOUSE", "CHILD"})
    split_method = require_enum(body, "split_method", {"PERCENTAGE", "SHARED_INTEREST"})

    p = get_participant(participant_id)

    award_pct = body.get("award_pct")
    award_fixed = body.get("award_fixed_monthly_cents")
    if award_pct is not None:
        if isinstance(award_pct, bool) or not isinstance(award_pct, (int, float)) or award_pct < 0:
            raise err("ERR_INVALID_REQUEST", "award_pct must be a non-negative number.")
    if award_fixed is not None:
        if isinstance(award_fixed, bool) or not isinstance(award_fixed, int) or award_fixed < 0:
            raise err("ERR_INVALID_REQUEST", "award_fixed_monthly_cents must be a non-negative integer.")

    rec = new_common()
    rec.update({
        "participant_id": participant_id,
        "plan_id": p["plan_id"],
        "alternate_payee_kind": kind,
        "split_method": split_method,
        "award_pct": award_pct,
        "award_fixed_monthly_cents": award_fixed,
        "alternate_payee_monthly_cents": None,
        "status": "DRAFT",
    })
    db.qdros[rec["id"]] = rec
    return ok(public(rec), status=201)


@app.route("/plans/participants/<participant_id>/qdros", methods=["GET"])
def list_participant_qdros(participant_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    get_participant(participant_id)
    status = request.args.get("status")
    recs = [q for q in db.qdros.values() if q["participant_id"] == participant_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


@app.route("/plans/qdros/<qdro_id>/submit", methods=["POST"])
def submit_qdro(qdro_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    q = get_qdro(qdro_id)
    if q["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "QDRO is not DRAFT.")
    if q["split_method"] == "PERCENTAGE":
        pct = q.get("award_pct")
        if pct is None or not (0 < pct <= 1):
            raise err("ERR_INVALID_REQUEST", "award_pct must be in (0, 1] for PERCENTAGE.")
    else:  # SHARED_INTEREST
        fixed = q.get("award_fixed_monthly_cents")
        if fixed is None or fixed <= 0:
            raise err("ERR_INVALID_REQUEST", "award_fixed_monthly_cents must be > 0 for SHARED_INTEREST.")
    q["status"] = "SUBMITTED"
    touch(q)
    return ok(public(q))


@app.route("/plans/qdros/<qdro_id>/qualify", methods=["POST"])
def qualify_qdro(qdro_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    q = get_qdro(qdro_id)
    if q["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "QDRO is not SUBMITTED.")
    participant_id = q["participant_id"]
    # no COMMENCED election yet for the participant
    if any(e["participant_id"] == participant_id and e["status"] == "COMMENCED"
           for e in db.elections.values()):
        raise err("ERR_QDRO_TOO_LATE", "A COMMENCED election already exists for the participant.")
    # cumulative QUALIFIED award_pct + this <= 1.0 for PERCENTAGE
    if q["split_method"] == "PERCENTAGE":
        cumulative = Decimal("0")
        for other in db.qdros.values():
            if (other["participant_id"] == participant_id and other["status"] == "QUALIFIED"
                    and other["split_method"] == "PERCENTAGE" and other.get("award_pct") is not None):
                cumulative += Decimal(str(other["award_pct"]))
        if cumulative + Decimal(str(q["award_pct"])) > Decimal("1.0"):
            raise err("ERR_QDRO_OVER_ALLOCATED", "Cumulative award_pct would exceed 1.0.")

    q["status"] = "QUALIFIED"
    touch(q)
    # compute alternate_payee_monthly_cents across all QUALIFIED awards for the
    # participant, based on the participant's election js_reduced base.
    _recompute_qdro_carves(participant_id)
    return ok(public(q))


def _recompute_qdro_carves(participant_id):
    """Recompute alternate_payee_monthly_cents for all QUALIFIED awards of a
    participant. Base = js_reduced_monthly_cents of the participant's most
    relevant election (the SUBMITTED/SPOUSAL/APPROVED/COMMENCED one with a
    computed benefit)."""
    p = db.participants.get(participant_id)
    if not p:
        return
    base = None
    candidates = [e for e in db.elections.values()
                  if e["participant_id"] == participant_id
                  and e.get("js_reduced_monthly_cents") is not None]
    if candidates:
        # prefer the latest-created election with a computed benefit
        candidates.sort(key=lambda e: e["_seq"])
        base = candidates[-1]["js_reduced_monthly_cents"]
    if base is None:
        base = 0
    calc_qdro_split_all(p, base)


@app.route("/plans/qdros/<qdro_id>/reject", methods=["POST"])
def reject_qdro(qdro_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    q = get_qdro(qdro_id)
    if q["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "QDRO is not SUBMITTED.")
    q["status"] = "REJECTED"
    touch(q)
    return ok(public(q))


@app.route("/plans/qdros/<qdro_id>/amend", methods=["POST"])
def amend_qdro(qdro_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    q = get_qdro(qdro_id)
    if q["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Only a REJECTED QDRO may be amended.")
    q["status"] = "DRAFT"
    q["alternate_payee_monthly_cents"] = None
    touch(q)
    return ok(public(q))


# =============================================================================
# Routes: BenefitPayment
# =============================================================================
@app.route("/plans/payments/<payment_id>", methods=["GET"])
def get_payment_route(payment_id):
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    p = get_payment(payment_id)
    return ok(public(p))


@app.route("/plans/payments", methods=["GET"])
def list_payments():
    authenticate()
    require_roles("PlanSponsor", "PlanActuary", "BenefitsAdministrator")
    election_id = request.args.get("election_id")
    participant_id = request.args.get("participant_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    recs = list(db.payments.values())
    if election_id is not None:
        recs = [r for r in recs if r["election_id"] == election_id]
    if participant_id is not None:
        recs = [r for r in recs if r["participant_id"] == participant_id]
    if plan_id is not None:
        recs = [r for r in recs if r["plan_id"] == plan_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    items, total, limit, offset = paginate_and_sort(recs)
    return list_response(items, total, limit, offset)


@app.route("/plans/payments/<payment_id>/activate", methods=["POST"])
def activate_payment(payment_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    pay = get_payment(payment_id)
    if pay["status"] != "PENDING_SETUP":
        raise err("ERR_INVALID_STATE", "Payment is not PENDING_SETUP.")
    e = db.elections.get(pay["election_id"])
    if not e or e["status"] != "COMMENCED":
        raise err("ERR_INVALID_STATE", "Owning election is not COMMENCED.")
    p = db.participants.get(pay["participant_id"])
    if not p or p["employment_status"] != "RETIRED":
        raise err("ERR_PARTICIPANT_NOT_ELIGIBLE", "Participant must be RETIRED.")
    pay["status"] = "IN_PAY"
    pay["current_monthly_cents"] = pay["base_monthly_cents"]
    touch(pay)
    return ok(public(pay))


@app.route("/plans/payments/<payment_id>/suspend", methods=["POST"])
def suspend_payment(payment_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    pay = get_payment(payment_id)
    if pay["status"] != "IN_PAY":
        raise err("ERR_INVALID_STATE", "Payment is not IN_PAY.")
    pay["status"] = "SUSPENDED"
    touch(pay)
    return ok(public(pay))


@app.route("/plans/payments/<payment_id>/resume", methods=["POST"])
def resume_payment(payment_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    pay = get_payment(payment_id)
    if pay["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Payment is not SUSPENDED.")
    pay["status"] = "IN_PAY"
    touch(pay)
    return ok(public(pay))


@app.route("/plans/payments/<payment_id>/apply-cola", methods=["POST"])
def apply_cola(payment_id):
    authenticate()
    require_roles("BenefitsAdministrator")
    pay = get_payment(payment_id)
    if pay["status"] != "IN_PAY":
        raise err("ERR_INVALID_STATE", "Payment is not IN_PAY.")
    plan = db.plans.get(pay["plan_id"])
    if not plan or Decimal(str(plan["cola_pct"])) <= 0:
        raise err("ERR_NO_COLA_CONFIGURED", "Plan has no COLA configured.")
    calc_cola(pay, plan)
    touch(pay)
    return ok(public(pay))


# =============================================================================
# Health
# =============================================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
