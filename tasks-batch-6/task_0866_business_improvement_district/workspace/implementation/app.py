import os
import uuid
import math
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
import calendar

from flask import Flask, request, jsonify

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ============================================================================
# Constants
# ============================================================================
ROLES = {"DistrictAdministrator", "BoardMember", "TaxCollector", "PropertyOwner", "Ambassador"}

USE_CLASSES = {"RETAIL", "OFFICE", "COMMERCIAL", "MIXED", "INDUSTRIAL",
               "RESIDENTIAL_EXEMPT", "NONPROFIT_EXEMPT"}
EXEMPT_CLASSES = {"RESIDENTIAL_EXEMPT", "NONPROFIT_EXEMPT"}
USE_MULT = {
    "RETAIL": Decimal("1.25"), "MIXED": Decimal("1.15"), "OFFICE": Decimal("1.10"),
    "COMMERCIAL": Decimal("1.00"), "INDUSTRIAL": Decimal("0.90"),
    "RESIDENTIAL_EXEMPT": Decimal("0"), "NONPROFIT_EXEMPT": Decimal("0"),
}
WORKPLAN_CATEGORIES = {"CLEAN", "SAFE", "MARKETING", "ADMIN", "CONTINGENCY"}
AMBASSADOR_ROLES = {"CLEAN", "SAFE", "OUTREACH"}
SR_CATEGORIES = {"CLEAN", "SAFE", "OTHER"}
SR_SOURCES = {"WALK_IN", "PHONE", "THREE_ONE_ONE", "EMAIL"}
PAYMENT_METHODS = {"TAX_ROLL", "ACH", "CHECK", "CARD"}

GRACE_DAYS = 30
PENALTY_PCT = Decimal("0.10")
DAILY_INTEREST_RATE = Decimal("0.0005")
DISPUTE_WINDOW_DAYS = 45
SHIFT_BUFFER_MINUTES = 30

DEFAULT_MIN_ASSESSMENT = 50000
DEFAULT_MAX_ASSESSMENT = 10000000

# ============================================================================
# In-memory store
# ============================================================================
BIDS = {}
PARCELS = {}
FISCAL_YEARS = {}
BUDGETS = {}
WORK_PLAN_LINES = {}
ASSESSMENTS = {}
COLLECTION_ACCOUNTS = {}
PAYMENTS = {}
DISPUTES = {}
PETITIONS = {}
SIGNATURES = {}
AMBASSADORS = {}
SHIFTS = {}
SERVICE_REQUESTS = {}

_SEQ = {"n": 0}
CLOCK = {"dt": None}


def reset_state():
    for d in (BIDS, PARCELS, FISCAL_YEARS, BUDGETS, WORK_PLAN_LINES, ASSESSMENTS,
              COLLECTION_ACCOUNTS, PAYMENTS, DISPUTES, PETITIONS, SIGNATURES,
              AMBASSADORS, SHIFTS, SERVICE_REQUESTS):
        d.clear()
    _SEQ["n"] = 0
    CLOCK["dt"] = parse_dt("2026-05-01T00:00:00Z")


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ============================================================================
# Errors
# ============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ============================================================================
# Time helpers
# ============================================================================
def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_render(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now_iso():
    return iso_render(CLOCK["dt"])


def day_count(as_of_dt, due_dt):
    secs = (as_of_dt - due_dt).total_seconds()
    d = math.floor(secs / 86400.0)
    return max(0, d)


def add_months(dt, months):
    m = dt.month - 1 + int(months)
    y = dt.year + m // 12
    mo = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, mo)[1])
    return dt.replace(year=y, month=mo, day=d)


# ============================================================================
# Numeric helpers
# ============================================================================
def D(x):
    return Decimal(str(x))


def rhu(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        if x == x.to_integral_value():
            return int(x)
        return float(x)
    return x


# ============================================================================
# Envelope helpers
# ============================================================================
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(extra=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    return jsonify({"meta": make_meta(), "response_type": "object", "data": data}), status


def ok_array(items, limit, offset):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    data = [serialize(e) for e in page]
    return jsonify({"meta": make_meta(pag), "response_type": "array", "data": data}), 200


def ok_raw_array(data_list, limit=10, offset=0):
    total = len(data_list)
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": False}
    return jsonify({"meta": make_meta(pag), "response_type": "array", "data": data_list}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


# ============================================================================
# Auth helpers
# ============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    return uid, role


def require(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def body_json():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "Body must be an object")
    return b


def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except Exception:
            raise ApiError("ERR_VALIDATION", 422, "Invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 422, "limit out of range")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except Exception:
            raise ApiError("ERR_VALIDATION", 422, "Invalid offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 422, "offset out of range")
    return limit, offset


# ============================================================================
# Field validation helpers
# ============================================================================
def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, "Missing or invalid field: %s" % key)
    return v


def req_int(body, key, positive=False, nonneg=False):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, "Missing or invalid integer field: %s" % key)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", 422, "Field must be > 0: %s" % key)
    if nonneg and v < 0:
        raise ApiError("ERR_VALIDATION", 422, "Field must be >= 0: %s" % key)
    return v


def req_num(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, "Missing or invalid number field: %s" % key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, "Missing or invalid enum field: %s" % key)
    return v


def req_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, "Missing or invalid boolean field: %s" % key)
    return v


def req_datetime(body, key):
    v = req_str(body, key)
    parse_dt(v)  # validate format
    return v


# ============================================================================
# Existence helpers
# ============================================================================
def get_bid(bid_id):
    o = BIDS.get(bid_id)
    if o is None:
        raise ApiError("ERR_BID_NOT_FOUND", 404, "District not found")
    return o


def get_parcel(pid):
    o = PARCELS.get(pid)
    if o is None:
        raise ApiError("ERR_PARCEL_NOT_FOUND", 404, "Parcel not found")
    return o


def get_fy(fid):
    o = FISCAL_YEARS.get(fid)
    if o is None:
        raise ApiError("ERR_FISCAL_YEAR_NOT_FOUND", 404, "Fiscal year not found")
    return o


def get_budget(bid):
    o = BUDGETS.get(bid)
    if o is None:
        raise ApiError("ERR_BUDGET_NOT_FOUND", 404, "Budget not found")
    return o


def get_assessment(aid):
    o = ASSESSMENTS.get(aid)
    if o is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND", 404, "Assessment not found")
    return o


def get_account(cid):
    o = COLLECTION_ACCOUNTS.get(cid)
    if o is None:
        raise ApiError("ERR_COLLECTION_ACCOUNT_NOT_FOUND", 404, "Collection account not found")
    return o


def get_dispute(did):
    o = DISPUTES.get(did)
    if o is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "Dispute not found")
    return o


def get_petition(pid):
    o = PETITIONS.get(pid)
    if o is None:
        raise ApiError("ERR_PETITION_NOT_FOUND", 404, "Renewal petition not found")
    return o


def get_signature(sid):
    o = SIGNATURES.get(sid)
    if o is None:
        raise ApiError("ERR_SIGNATURE_NOT_FOUND", 404, "Petition signature not found")
    return o


def get_ambassador(aid):
    o = AMBASSADORS.get(aid)
    if o is None:
        raise ApiError("ERR_AMBASSADOR_NOT_FOUND", 404, "Ambassador not found")
    return o


def get_service_request(sid):
    o = SERVICE_REQUESTS.get(sid)
    if o is None:
        raise ApiError("ERR_SERVICE_REQUEST_NOT_FOUND", 404, "Service request not found")
    return o


# ============================================================================
# Entity helpers
# ============================================================================
def new_entity(etype, fields, common=True):
    ts = now_iso()
    e = {"_type": etype, "_seq": next_seq(), "id": str(uuid.uuid4()), "created_at": ts}
    if common:
        e["updated_at"] = ts
        e["version"] = 1
    e.update(fields)
    return e


def touch(e):
    if "version" in e:
        e["version"] += 1
        e["updated_at"] = now_iso()


# ============================================================================
# Serialization
# ============================================================================
def serialize(e):
    if e["_type"] == "CollectionAccount":
        return ser_account(e)
    return {k: num(v) for k, v in e.items() if not k.startswith("_")}


def interest_cents_asof(e, dt):
    principal_out = e["billed_amount_cents"] - e["principal_paid_cents"]
    if principal_out <= 0:
        return 0
    due = parse_dt(e["due_date"])
    dc = day_count(dt, due)
    if dc <= 0:
        return 0
    return rhu(D(principal_out) * DAILY_INTEREST_RATE * D(dc))


def ser_account(e):
    billed = e["billed_amount_cents"]
    ppaid = e["principal_paid_cents"]
    principal_out = billed - ppaid
    if e.get("_frozen"):
        interest = e.get("_frozen_interest", 0)
    else:
        interest = interest_cents_asof(e, CLOCK["dt"])
    balance = principal_out + e["penalty_accrued_cents"] + interest - e["credit_balance_cents"]
    if balance < 0:
        balance = 0
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "assessment_id": e["assessment_id"],
        "billed_amount_cents": billed, "penalty_accrued_cents": e["penalty_accrued_cents"],
        "interest_accrued_cents": interest, "principal_paid_cents": ppaid,
        "total_paid_cents": e["total_paid_cents"], "credit_balance_cents": e["credit_balance_cents"],
        "balance_due_cents": balance, "due_date": e["due_date"],
        "delinquent_since": e["delinquent_since"], "status": e["status"],
    }


# ============================================================================
# Calculations
# ============================================================================
def compute_weighted_base(parcel, bid):
    if parcel["exempt"]:
        return Decimal("0")
    base_points = (D(bid["assessment_weight_value"]) * (D(parcel["assessed_value_cents"]) / Decimal("100"))
                   + D(bid["assessment_weight_frontage"]) * D(parcel["linear_frontage_ft"])
                   + D(bid["assessment_weight_sqft"]) * D(parcel["building_sqft"]))
    return base_points * USE_MULT[parcel["use_class"]]


def active_nonexempt_parcels(bid_id):
    return [p for p in PARCELS.values()
            if p["bid_id"] == bid_id and p["status"] == "ACTIVE" and not p["exempt"]]


def clamp_assessment(raw_dec, bid):
    amt = rhu(raw_dec)
    lo = bid["min_assessment_cents"]
    hi = bid["max_assessment_cents"]
    return min(max(amt, lo), hi)


def basis_fiscal_year(bid_id):
    cands = [fy for fy in FISCAL_YEARS.values()
             if fy["bid_id"] == bid_id and fy["budget_status"] == "ADOPTED"]
    if not cands:
        return None
    return max(cands, key=lambda fy: (parse_dt(fy["end_date"]), parse_dt(fy["created_at"])))


def recompute_allocated_total(budget):
    total = sum(l["allocated_amount_cents"] for l in WORK_PLAN_LINES.values()
                if l["budget_id"] == budget["id"])
    budget["allocated_total_cents"] = total


# ============================================================================
# Routes: logical clock
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    authenticate()
    body = body_json()
    v = body.get("to_iso8601")
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 required")
    CLOCK["dt"] = parse_dt(v)
    return ok_object({}, 200)


# ============================================================================
# Routes: BusinessImprovementDistrict
# ============================================================================
@app.route("/business-improvement-districts", methods=["POST"])
def create_bid():
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    body = body_json()
    name = req_str(body, "name")
    boundary = req_str(body, "boundary_description")
    auth_exp = req_datetime(body, "authorization_expires_at")
    w_val = req_num(body, "assessment_weight_value")
    w_front = req_num(body, "assessment_weight_frontage")
    w_sqft = req_num(body, "assessment_weight_sqft")
    min_a = body.get("min_assessment_cents", DEFAULT_MIN_ASSESSMENT)
    max_a = body.get("max_assessment_cents", DEFAULT_MAX_ASSESSMENT)
    if isinstance(min_a, bool) or not isinstance(min_a, int) or min_a < 0:
        raise ApiError("ERR_VALIDATION", 422, "Invalid min_assessment_cents")
    if isinstance(max_a, bool) or not isinstance(max_a, int) or max_a < 0:
        raise ApiError("ERR_VALIDATION", 422, "Invalid max_assessment_cents")
    e = new_entity("BusinessImprovementDistrict", {
        "name": name, "boundary_description": boundary,
        "authorization_expires_at": auth_exp,
        "assessment_weight_value": w_val, "assessment_weight_frontage": w_front,
        "assessment_weight_sqft": w_sqft, "min_assessment_cents": min_a,
        "max_assessment_cents": max_a, "status": "FORMING",
    })
    BIDS[e["id"]] = e
    return ok_object(serialize(e), 201)


@app.route("/business-improvement-districts/<bid_id>", methods=["GET"])
def get_bid_route(bid_id):
    uid, role = authenticate()
    require(role, ROLES)
    e = get_bid(bid_id)
    return ok_object(serialize(e), 200)


@app.route("/business-improvement-districts/<bid_id>/activate", methods=["POST"])
def activate_bid(bid_id):
    uid, role = authenticate()
    require(role, {"BoardMember"})
    e = get_bid(bid_id)
    if e["status"] != "FORMING":
        raise ApiError("ERR_INVALID_STATE", 409, "District not FORMING")
    has_active = any(p["bid_id"] == bid_id and p["status"] == "ACTIVE" for p in PARCELS.values())
    if not has_active:
        raise ApiError("ERR_VALIDATION", 422, "District must contain at least one ACTIVE parcel")
    if parse_dt(e["authorization_expires_at"]) <= CLOCK["dt"]:
        raise ApiError("ERR_VALIDATION", 422, "authorization_expires_at must be in the future")
    e["status"] = "ACTIVE"
    touch(e)
    return ok_object(serialize(e), 200)


# ============================================================================
# Routes: Parcel
# ============================================================================
@app.route("/business-improvement-districts/<bid_id>/parcels", methods=["POST"])
def create_parcel(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    bid = get_bid(bid_id)
    body = body_json()
    apn = req_str(body, "apn")
    owner_name = req_str(body, "owner_name")
    use_class = req_enum(body, "use_class", USE_CLASSES)
    assessed = req_int(body, "assessed_value_cents", nonneg=True)
    frontage = req_num(body, "linear_frontage_ft")
    sqft = req_num(body, "building_sqft")
    exempt = use_class in EXEMPT_CLASSES
    parcel = new_entity("Parcel", {
        "bid_id": bid_id, "apn": apn, "owner_name": owner_name, "use_class": use_class,
        "assessed_value_cents": assessed, "linear_frontage_ft": frontage,
        "building_sqft": sqft, "exempt": exempt, "weighted_base": Decimal("0"),
        "status": "ACTIVE",
    })
    parcel["weighted_base"] = compute_weighted_base(parcel, bid)
    PARCELS[parcel["id"]] = parcel
    return ok_object(serialize(parcel), 201)


@app.route("/business-improvement-districts/<bid_id>/parcels", methods=["GET"])
def list_parcels(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    get_bid(bid_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    items = [p for p in PARCELS.values() if p["bid_id"] == bid_id]
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    return ok_array(items, limit, offset)


@app.route("/parcels/<pid>", methods=["GET"])
def get_parcel_route(pid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "PropertyOwner"})
    p = get_parcel(pid)
    return ok_object(serialize(p), 200)


@app.route("/parcels/<pid>/withdraw", methods=["POST"])
def withdraw_parcel(pid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    p = get_parcel(pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Parcel not ACTIVE")
    p["status"] = "WITHDRAWN"
    touch(p)
    # cascade: certified assessments with no payments -> cancel + write off + reduce levy
    for a in ASSESSMENTS.values():
        if a["parcel_id"] != pid or a["status"] != "CERTIFIED":
            continue
        acct = next((c for c in COLLECTION_ACCOUNTS.values() if c["assessment_id"] == a["id"]), None)
        if acct is None or acct["total_paid_cents"] != 0:
            continue
        a["status"] = "CANCELLED"
        touch(a)
        acct["status"] = "WRITTEN_OFF"
        acct["_frozen"] = True
        acct["_frozen_interest"] = interest_cents_asof(acct, CLOCK["dt"])
        touch(acct)
        fy = FISCAL_YEARS.get(a["fiscal_year_id"])
        if fy is not None:
            fy["total_certified_levy_cents"] -= a["certified_amount_cents"]
            reevaluate_collection_status(fy)
            touch(fy)
    return ok_object(serialize(p), 200)


def reevaluate_collection_status(fy):
    levy = fy["total_certified_levy_cents"]
    if levy > 0 and fy["collected_to_date_cents"] >= levy:
        fy["collection_status"] = "FULLY_COLLECTED"
    else:
        fy["collection_status"] = "OPEN"


# ============================================================================
# Routes: FiscalYear
# ============================================================================
@app.route("/business-improvement-districts/<bid_id>/fiscal-years", methods=["POST"])
def create_fiscal_year(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    bid = get_bid(bid_id)
    body = body_json()
    year_label = req_str(body, "year_label")
    start_date = req_datetime(body, "start_date")
    end_date = req_datetime(body, "end_date")
    due_date = req_datetime(body, "assessment_due_date")
    ns, ne = parse_dt(start_date), parse_dt(end_date)
    for fy in FISCAL_YEARS.values():
        if fy["bid_id"] != bid_id:
            continue
        es, ee = parse_dt(fy["start_date"]), parse_dt(fy["end_date"])
        if ns < ee and es < ne:  # half-open overlap; adjacency allowed
            raise ApiError("ERR_FISCAL_YEAR_OVERLAP", 409, "Fiscal year interval overlaps existing")
    fy = new_entity("FiscalYear", {
        "bid_id": bid_id, "year_label": year_label, "start_date": start_date,
        "end_date": end_date, "assessment_due_date": due_date, "budget_status": "NONE",
        "total_certified_levy_cents": 0, "collected_to_date_cents": 0,
        "collection_status": "OPEN", "status": "UPCOMING",
    })
    FISCAL_YEARS[fy["id"]] = fy
    return ok_object(serialize(fy), 201)


@app.route("/business-improvement-districts/<bid_id>/fiscal-years", methods=["GET"])
def list_fiscal_years(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    get_bid(bid_id)
    limit, offset = parse_pagination()
    items = [fy for fy in FISCAL_YEARS.values() if fy["bid_id"] == bid_id]
    return ok_array(items, limit, offset)


@app.route("/fiscal-years/<fid>", methods=["GET"])
def get_fiscal_year_route(fid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    fy = get_fy(fid)
    return ok_object(serialize(fy), 200)


@app.route("/fiscal-years/<fid>/financial-report", methods=["GET"])
def financial_report(fid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    fy = get_fy(fid)
    budget = next((b for b in BUDGETS.values() if b["fiscal_year_id"] == fid), None)
    by_category = []
    if budget is not None:
        lines = [l for l in WORK_PLAN_LINES.values() if l["budget_id"] == budget["id"]]
        lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
        for l in lines:
            allocated = l["allocated_amount_cents"]
            spent = l["spent_amount_cents"]
            by_category.append({
                "category": l["category"],
                "allocated_amount_cents": allocated,
                "spent_amount_cents": spent,
                "variance_cents": allocated - spent,
                "variance": allocated - spent,
            })
    data = {
        "fiscal_year_id": fy["id"],
        "total_certified_levy_cents": fy["total_certified_levy_cents"],
        "collected_to_date_cents": fy["collected_to_date_cents"],
        "collection_status": fy["collection_status"],
        "by_category": by_category,
    }
    return ok_object(data, 200)


# ============================================================================
# Routes: Budget / WorkPlanLine
# ============================================================================
@app.route("/fiscal-years/<fid>/budget", methods=["POST"])
def create_budget(fid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    fy = get_fy(fid)
    if any(b["fiscal_year_id"] == fid for b in BUDGETS.values()):
        raise ApiError("ERR_BUDGET_EXISTS", 409, "Budget already exists for fiscal year")
    body = body_json()
    total_exp = req_int(body, "total_expenditure_cents", nonneg=True)
    other_rev = req_int(body, "other_revenue_cents", nonneg=True)
    budget = new_entity("Budget", {
        "fiscal_year_id": fid, "total_expenditure_cents": total_exp,
        "other_revenue_cents": other_rev, "allocated_total_cents": 0,
        "required_levy_cents": total_exp - other_rev, "estimate_rate": None,
        "certified_rate": None, "proposed_at": None, "adopted_at": None, "status": "DRAFT",
    })
    BUDGETS[budget["id"]] = budget
    fy["budget_status"] = "DRAFT"
    touch(fy)
    return ok_object(serialize(budget), 201)


@app.route("/fiscal-years/<fid>/budget", methods=["GET"])
def get_fy_budget(fid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    get_fy(fid)
    items = [b for b in BUDGETS.values() if b["fiscal_year_id"] == fid]
    limit, offset = parse_pagination()
    return ok_array(items, limit, offset)


@app.route("/budgets/<bid>", methods=["GET"])
def get_budget_route(bid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    b = get_budget(bid)
    return ok_object(serialize(b), 200)


@app.route("/budgets/<bid>/work-plan-lines", methods=["POST"])
def add_work_plan_line(bid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    budget = get_budget(bid)
    if budget["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Budget not DRAFT")
    body = body_json()
    category = req_enum(body, "category", WORKPLAN_CATEGORIES)
    if any(l["budget_id"] == bid and l["category"] == category for l in WORK_PLAN_LINES.values()):
        raise ApiError("ERR_DUPLICATE_CATEGORY", 409, "Category already exists in budget")
    allocated = req_int(body, "allocated_amount_cents", nonneg=True)
    line = new_entity("WorkPlanLine", {
        "budget_id": bid, "category": category, "allocated_amount_cents": allocated,
        "spent_amount_cents": 0,
    })
    WORK_PLAN_LINES[line["id"]] = line
    recompute_allocated_total(budget)
    touch(budget)
    return ok_object(serialize(line), 201)


@app.route("/budgets/<bid>/work-plan-lines", methods=["GET"])
def list_work_plan_lines(bid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    get_budget(bid)
    limit, offset = parse_pagination()
    items = [l for l in WORK_PLAN_LINES.values() if l["budget_id"] == bid]
    return ok_array(items, limit, offset)


@app.route("/budgets/<bid>/reallocations", methods=["POST"])
def reallocate(bid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    budget = get_budget(bid)
    if budget["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Budget not DRAFT")
    body = body_json()
    from_cat = req_enum(body, "from_category", WORKPLAN_CATEGORIES)
    to_cat = req_enum(body, "to_category", WORKPLAN_CATEGORIES)
    amount = req_int(body, "amount_cents", positive=True)
    expected = req_int(body, "expected_budget_version")
    from_line = next((l for l in WORK_PLAN_LINES.values()
                      if l["budget_id"] == bid and l["category"] == from_cat), None)
    to_line = next((l for l in WORK_PLAN_LINES.values()
                    if l["budget_id"] == bid and l["category"] == to_cat), None)
    if from_line is None or to_line is None:
        raise ApiError("ERR_INVALID_REALLOCATION", 422, "Unknown category line")
    if amount > from_line["allocated_amount_cents"]:
        raise ApiError("ERR_INVALID_REALLOCATION", 422, "Amount exceeds source allocation")
    if expected != budget["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_budget_version mismatch")
    from_line["allocated_amount_cents"] -= amount
    to_line["allocated_amount_cents"] += amount
    touch(from_line)
    touch(to_line)
    recompute_allocated_total(budget)
    touch(budget)
    return ok_object(serialize(budget), 200)


@app.route("/budgets/<bid>/propose", methods=["POST"])
def propose_budget(bid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    budget = get_budget(bid)
    if budget["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Budget not DRAFT")
    if budget["allocated_total_cents"] != budget["total_expenditure_cents"]:
        raise ApiError("ERR_BUDGET_UNBALANCED", 422, "Allocations must equal total_expenditure_cents")
    if budget["required_levy_cents"] < 0:
        raise ApiError("ERR_NEGATIVE_LEVY", 422, "required_levy_cents must be >= 0")
    fy = get_fy(budget["fiscal_year_id"])
    parcels = active_nonexempt_parcels(fy["bid_id"])
    if not parcels:
        raise ApiError("ERR_VALIDATION", 422, "No ACTIVE non-exempt parcel exists")
    denom = sum((p["weighted_base"] for p in parcels), Decimal("0"))
    rate = D(budget["required_levy_cents"]) / denom
    budget["estimate_rate"] = rate
    bid_obj = BIDS[fy["bid_id"]]
    for p in parcels:
        wb = p["weighted_base"]
        raw = rate * wb
        amt = clamp_assessment(raw, bid_obj)
        a = new_entity("Assessment", {
            "fiscal_year_id": fy["id"], "parcel_id": p["id"], "weighted_base": wb,
            "estimated_amount_cents": amt, "certified_amount_cents": None,
            "certified_at": None, "status": "ESTIMATED",
        })
        ASSESSMENTS[a["id"]] = a
    budget["status"] = "PROPOSED"
    budget["proposed_at"] = now_iso()
    touch(budget)
    fy["budget_status"] = "PROPOSED"
    touch(fy)
    return ok_object(serialize(budget), 200)


@app.route("/budgets/<bid>/revert", methods=["POST"])
def revert_budget(bid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    budget = get_budget(bid)
    if budget["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Budget not PROPOSED")
    fy = get_fy(budget["fiscal_year_id"])
    to_delete = [a["id"] for a in ASSESSMENTS.values()
                 if a["fiscal_year_id"] == fy["id"] and a["status"] == "ESTIMATED"]
    for aid in to_delete:
        del ASSESSMENTS[aid]
    budget["status"] = "DRAFT"
    budget["estimate_rate"] = None
    budget["proposed_at"] = None
    touch(budget)
    fy["budget_status"] = "DRAFT"
    touch(fy)
    return ok_object(serialize(budget), 200)


@app.route("/budgets/<bid>/adopt", methods=["POST"])
def adopt_budget(bid):
    uid, role = authenticate()
    require(role, {"BoardMember"})
    budget = get_budget(bid)
    if budget["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Budget not PROPOSED")
    fy = get_fy(budget["fiscal_year_id"])
    bid_obj = BIDS[fy["bid_id"]]
    if bid_obj["status"] != "ACTIVE":
        raise ApiError("ERR_BID_NOT_ACTIVE", 409, "District not ACTIVE")
    parcels = active_nonexempt_parcels(fy["bid_id"])
    denom = sum((p["weighted_base"] for p in parcels), Decimal("0"))
    rate = (D(budget["required_levy_cents"]) / denom) if denom > 0 else Decimal("0")
    budget["certified_rate"] = rate
    levy_total = 0
    estimated = [a for a in ASSESSMENTS.values()
                 if a["fiscal_year_id"] == fy["id"] and a["status"] == "ESTIMATED"]
    for a in estimated:
        parcel = PARCELS.get(a["parcel_id"])
        if parcel is not None and parcel["status"] == "ACTIVE":
            raw = rate * a["weighted_base"]
            amt = clamp_assessment(raw, bid_obj)
            a["certified_amount_cents"] = amt
            a["certified_at"] = now_iso()
            a["status"] = "CERTIFIED"
            touch(a)
            acct = new_entity("CollectionAccount", {
                "assessment_id": a["id"], "billed_amount_cents": amt,
                "penalty_accrued_cents": 0, "principal_paid_cents": 0,
                "total_paid_cents": 0, "credit_balance_cents": 0,
                "due_date": fy["assessment_due_date"], "delinquent_since": None,
                "status": "BILLED",
            })
            COLLECTION_ACCOUNTS[acct["id"]] = acct
            levy_total += amt
        else:
            a["status"] = "CANCELLED"
            touch(a)
    budget["status"] = "ADOPTED"
    budget["adopted_at"] = now_iso()
    touch(budget)
    fy["total_certified_levy_cents"] = levy_total
    fy["budget_status"] = "ADOPTED"
    fy["status"] = "ACTIVE"
    reevaluate_collection_status(fy)
    touch(fy)
    return ok_object(serialize(budget), 200)


# ============================================================================
# Routes: Assessment
# ============================================================================
@app.route("/assessments/<aid>", methods=["GET"])
def get_assessment_route(aid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "PropertyOwner"})
    a = get_assessment(aid)
    return ok_object(serialize(a), 200)


@app.route("/assessments", methods=["GET"])
def list_assessments():
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "PropertyOwner"})
    limit, offset = parse_pagination()
    parcel_id = request.args.get("parcel_id")
    fy_id = request.args.get("fiscal_year_id")
    status_f = request.args.get("status")
    items = list(ASSESSMENTS.values())
    if parcel_id is not None:
        items = [a for a in items if a["parcel_id"] == parcel_id]
    if fy_id is not None:
        items = [a for a in items if a["fiscal_year_id"] == fy_id]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    return ok_array(items, limit, offset)


@app.route("/assessments/<aid>/collection-account", methods=["GET"])
def get_assessment_account(aid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "TaxCollector", "PropertyOwner"})
    get_assessment(aid)
    items = [c for c in COLLECTION_ACCOUNTS.values() if c["assessment_id"] == aid]
    return ok_array(items, 10, 0)


# ============================================================================
# Routes: CollectionAccount / Payment
# ============================================================================
@app.route("/collection-accounts/<cid>", methods=["GET"])
def get_account_route(cid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "TaxCollector", "PropertyOwner"})
    c = get_account(cid)
    return ok_object(serialize(c), 200)


@app.route("/collection-accounts/<cid>/payoff-quote", methods=["GET"])
def payoff_quote(cid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "TaxCollector", "PropertyOwner"})
    c = get_account(cid)
    as_of = request.args.get("as_of_date")
    if not as_of:
        raise ApiError("ERR_VALIDATION", 422, "as_of_date required")
    as_of_dt = parse_dt(as_of)
    principal_out = c["billed_amount_cents"] - c["principal_paid_cents"]
    interest = interest_cents_asof(c, as_of_dt)
    penalty = c["penalty_accrued_cents"]
    quoted = principal_out + penalty + interest - c["credit_balance_cents"]
    if quoted < 0:
        quoted = 0
    data = {
        "collection_account_id": c["id"], "as_of_date": as_of,
        "principal_outstanding_cents": principal_out, "penalty_cents": penalty,
        "interest_cents": interest, "quoted_balance_cents": quoted,
    }
    return ok_object(data, 200)


def account_owner_parcel_id(account):
    a = ASSESSMENTS.get(account["assessment_id"])
    return a["parcel_id"] if a else None


@app.route("/collection-accounts/<cid>/payments", methods=["POST"])
def post_payment(cid):
    uid, role = authenticate()
    require(role, {"TaxCollector", "PropertyOwner"})
    c = get_account(cid)
    if role == "PropertyOwner":
        if account_owner_parcel_id(c) != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the owning parcel")
    if c["status"] not in ("BILLED", "DELINQUENT"):
        raise ApiError("ERR_INVALID_STATE", 409, "Account not payable")
    body = body_json()
    amount = req_int(body, "amount_cents", positive=True)
    method = body.get("method", "TAX_ROLL")
    if not isinstance(method, str) or method not in PAYMENT_METHODS:
        raise ApiError("ERR_VALIDATION", 422, "Invalid method")

    posted = now_iso()
    principal_out = c["billed_amount_cents"] - c["principal_paid_cents"]
    interest_owed = interest_cents_asof(c, CLOCK["dt"])
    penalty_owed = c["penalty_accrued_cents"]

    remaining = amount
    ai = min(remaining, interest_owed)
    remaining -= ai
    ap = min(remaining, penalty_owed)
    remaining -= ap
    apr = min(remaining, principal_out)
    remaining -= apr

    c["principal_paid_cents"] += apr
    c["penalty_accrued_cents"] -= ap
    c["total_paid_cents"] += amount
    if remaining > 0:
        c["credit_balance_cents"] += remaining

    new_principal_out = c["billed_amount_cents"] - c["principal_paid_cents"]
    fully = (ai >= interest_owed) and (c["penalty_accrued_cents"] == 0) and (new_principal_out == 0)
    if fully:
        c["status"] = "CREDIT" if remaining > 0 else "PAID"
    touch(c)

    payment = new_entity("Payment", {
        "collection_account_id": cid, "amount_cents": amount, "method": method,
        "applied_to_interest_cents": ai, "applied_to_penalty_cents": ap,
        "applied_to_principal_cents": apr, "posted_at": posted,
    }, common=False)
    PAYMENTS[payment["id"]] = payment

    a = ASSESSMENTS.get(c["assessment_id"])
    if a is not None:
        fy = FISCAL_YEARS.get(a["fiscal_year_id"])
        if fy is not None:
            fy["collected_to_date_cents"] += amount
            reevaluate_collection_status(fy)
            touch(fy)
    return ok_object(serialize(payment), 201)


@app.route("/collection-accounts/<cid>/payments", methods=["GET"])
def list_payments(cid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "TaxCollector", "PropertyOwner"})
    get_account(cid)
    limit, offset = parse_pagination()
    items = [p for p in PAYMENTS.values() if p["collection_account_id"] == cid]
    return ok_array(items, limit, offset)


@app.route("/collection-accounts/<cid>/assess-delinquency", methods=["POST"])
def assess_delinquency(cid):
    uid, role = authenticate()
    require(role, {"TaxCollector"})
    c = get_account(cid)
    if c["status"] == "DELINQUENT":
        raise ApiError("ERR_ALREADY_DELINQUENT", 409, "Account already delinquent")
    if c["status"] != "BILLED":
        raise ApiError("ERR_ACCOUNT_NOT_DELINQUENT", 409, "Account not BILLED")
    due = parse_dt(c["due_date"])
    if day_count(CLOCK["dt"], due) <= GRACE_DAYS:
        raise ApiError("ERR_ACCOUNT_NOT_DELINQUENT", 409, "Grace period not passed")
    principal_out = c["billed_amount_cents"] - c["principal_paid_cents"]
    interest = interest_cents_asof(c, CLOCK["dt"])
    balance = principal_out + c["penalty_accrued_cents"] + interest - c["credit_balance_cents"]
    if balance <= 0:
        raise ApiError("ERR_ACCOUNT_NOT_DELINQUENT", 409, "Nothing owed")
    penalty = rhu(D(c["billed_amount_cents"]) * PENALTY_PCT)
    c["penalty_accrued_cents"] = penalty
    c["delinquent_since"] = c["due_date"]
    c["status"] = "DELINQUENT"
    touch(c)
    return ok_object(serialize(c), 200)


@app.route("/collection-accounts/<cid>/write-off", methods=["POST"])
def write_off(cid):
    uid, role = authenticate()
    require(role, {"TaxCollector"})
    c = get_account(cid)
    if c["status"] != "DELINQUENT":
        raise ApiError("ERR_ACCOUNT_NOT_DELINQUENT", 409, "Account not DELINQUENT")
    c["_frozen_interest"] = interest_cents_asof(c, CLOCK["dt"])
    c["_frozen"] = True
    c["status"] = "WRITTEN_OFF"
    touch(c)
    return ok_object(serialize(c), 200)


# ============================================================================
# Routes: Dispute
# ============================================================================
@app.route("/assessments/<aid>/disputes", methods=["POST"])
def file_dispute(aid):
    uid, role = authenticate()
    require(role, {"PropertyOwner"})
    a = get_assessment(aid)
    if a["parcel_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the owning parcel")
    # referential: at most one non-terminal dispute
    terminal = {"RESOLVED_ADJUSTED", "RESOLVED_DENIED", "WITHDRAWN"}
    if any(d["assessment_id"] == aid and d["status"] not in terminal for d in DISPUTES.values()):
        raise ApiError("ERR_DISPUTE_ALREADY_OPEN", 409, "A non-terminal dispute already exists")
    # temporal window (only meaningful once certified)
    if a["certified_at"] is not None:
        cert = parse_dt(a["certified_at"])
        if (CLOCK["dt"] - cert).total_seconds() > DISPUTE_WINDOW_DAYS * 86400.0:
            raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", 422, "Dispute window closed")
    # cross-entity: assessment must be CERTIFIED
    if a["status"] != "CERTIFIED":
        raise ApiError("ERR_ASSESSMENT_NOT_CERTIFIED", 409, "Assessment not CERTIFIED")
    body = body_json()
    claimed = req_int(body, "claimed_value_cents", nonneg=True)
    requested = req_int(body, "requested_amount_cents", nonneg=True)
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid reason")
    d = new_entity("Dispute", {
        "assessment_id": aid, "claimed_value_cents": claimed,
        "requested_amount_cents": requested, "resolved_amount_cents": None,
        "reason": reason, "filed_at": now_iso(), "resolved_at": None, "status": "SUBMITTED",
    })
    DISPUTES[d["id"]] = d
    return ok_object(serialize(d), 201)


@app.route("/assessments/<aid>/disputes", methods=["GET"])
def list_disputes(aid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "PropertyOwner"})
    get_assessment(aid)
    limit, offset = parse_pagination()
    items = [d for d in DISPUTES.values() if d["assessment_id"] == aid]
    return ok_array(items, limit, offset)


@app.route("/disputes/<did>", methods=["GET"])
def get_dispute_route(did):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "PropertyOwner"})
    d = get_dispute(did)
    return ok_object(serialize(d), 200)


DISPUTE_ACTION_ROLE = {
    "REVIEW": "DistrictAdministrator",
    "REQUEST_INFO": "DistrictAdministrator",
    "RESOLVE": "DistrictAdministrator",
    "RESPOND": "PropertyOwner",
    "WITHDRAW": "PropertyOwner",
}


@app.route("/disputes/<did>/transition", methods=["POST"])
def dispute_transition(did):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "PropertyOwner"})
    body = body_json()
    action = body.get("action")
    if action not in DISPUTE_ACTION_ROLE:
        raise ApiError("ERR_VALIDATION", 422, "Invalid action")
    if role != DISPUTE_ACTION_ROLE[action]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this action")
    d = get_dispute(did)
    a = ASSESSMENTS.get(d["assessment_id"])
    # ownership for owner-driven actions
    if action in ("RESPOND", "WITHDRAW"):
        if a is None or a["parcel_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the owning parcel")
    terminal = {"RESOLVED_ADJUSTED", "RESOLVED_DENIED", "WITHDRAWN"}
    if d["status"] in terminal:
        raise ApiError("ERR_DISPUTE_NOT_OPEN", 409, "Dispute already resolved")

    st = d["status"]
    if action == "REVIEW":
        if st != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot review from current state")
        d["status"] = "UNDER_REVIEW"
    elif action == "REQUEST_INFO":
        if st != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot request info from current state")
        d["status"] = "INFO_REQUESTED"
    elif action == "RESPOND":
        if st != "INFO_REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot respond from current state")
        d["status"] = "UNDER_REVIEW"
    elif action == "WITHDRAW":
        if st not in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot withdraw from current state")
        d["status"] = "WITHDRAWN"
        d["resolved_at"] = now_iso()
    elif action == "RESOLVE":
        if st != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot resolve from current state")
        decision = body.get("decision")
        if decision not in ("ADJUSTED", "DENIED"):
            raise ApiError("ERR_VALIDATION", 422, "Invalid decision")
        if decision == "DENIED":
            d["status"] = "RESOLVED_DENIED"
            d["resolved_at"] = now_iso()
        else:
            resolved_amt = req_int(body, "resolved_amount_cents", nonneg=True)
            cert = a["certified_amount_cents"] if a else 0
            if resolved_amt < 0 or (cert is not None and resolved_amt > cert):
                raise ApiError("ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT", 422,
                               "resolved_amount out of range")
            d["status"] = "RESOLVED_ADJUSTED"
            d["resolved_amount_cents"] = resolved_amt
            d["resolved_at"] = now_iso()
            apply_dispute_adjustment(a, resolved_amt)
    touch(d)
    return ok_object(serialize(d), 200)


def apply_dispute_adjustment(assessment, new_amount):
    old_amount = assessment["certified_amount_cents"]
    delta = new_amount - old_amount
    assessment["certified_amount_cents"] = new_amount
    assessment["status"] = "ADJUSTED"
    touch(assessment)
    acct = next((c for c in COLLECTION_ACCOUNTS.values()
                 if c["assessment_id"] == assessment["id"]), None)
    refund = 0
    if acct is not None:
        acct["billed_amount_cents"] = new_amount
        if acct["principal_paid_cents"] > new_amount:
            refund = acct["principal_paid_cents"] - new_amount
            acct["credit_balance_cents"] += refund
            acct["principal_paid_cents"] = new_amount
            acct["status"] = "CREDIT"
        else:
            principal_out = new_amount - acct["principal_paid_cents"]
            if principal_out == 0 and acct["penalty_accrued_cents"] == 0 and acct["status"] in ("BILLED", "DELINQUENT"):
                acct["status"] = "PAID"
        touch(acct)
    fy = FISCAL_YEARS.get(assessment["fiscal_year_id"])
    if fy is not None:
        fy["total_certified_levy_cents"] += delta
        if refund:
            fy["collected_to_date_cents"] -= refund
        reevaluate_collection_status(fy)
        touch(fy)


# ============================================================================
# Routes: RenewalPetition / signatures
# ============================================================================
@app.route("/business-improvement-districts/<bid_id>/renewal-petitions", methods=["POST"])
def open_petition(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    bid = get_bid(bid_id)
    if bid["status"] != "ACTIVE":
        raise ApiError("ERR_BID_NOT_ACTIVE", 409, "District not ACTIVE")
    body = body_json()
    deadline = req_datetime(body, "circulation_deadline")
    threshold = body.get("required_threshold_pct", 0.50)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, "Invalid required_threshold_pct")
    term = body.get("renewal_term_months", 60)
    if isinstance(term, bool) or not isinstance(term, int) or term <= 0:
        raise ApiError("ERR_VALIDATION", 422, "Invalid renewal_term_months")
    petition = new_entity("RenewalPetition", {
        "bid_id": bid_id, "required_threshold_pct": threshold,
        "circulation_deadline": deadline, "renewal_term_months": term,
        "weighted_support_pct": None, "verified_by_user_id": None, "status": "CIRCULATING",
    })
    PETITIONS[petition["id"]] = petition
    bid["status"] = "RENEWAL_PENDING"
    touch(bid)
    return ok_object(serialize(petition), 201)


@app.route("/business-improvement-districts/<bid_id>/renewal-petitions", methods=["GET"])
def list_petitions(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    get_bid(bid_id)
    limit, offset = parse_pagination()
    items = [p for p in PETITIONS.values() if p["bid_id"] == bid_id]
    return ok_array(items, limit, offset)


@app.route("/renewal-petitions/<pid>", methods=["GET"])
def get_petition_route(pid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "PropertyOwner"})
    p = get_petition(pid)
    return ok_object(serialize(p), 200)


@app.route("/renewal-petitions/<pid>/signatures", methods=["POST"])
def sign_petition(pid):
    uid, role = authenticate()
    require(role, {"PropertyOwner"})
    petition = get_petition(pid)
    body = body_json()
    parcel_id = req_str(body, "parcel_id")
    support = req_bool(body, "support")
    # ownership: owner signs for own parcel
    if parcel_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Owner may only sign for own parcel")
    parcel = get_parcel(parcel_id)
    # state: only while circulating
    if petition["status"] != "CIRCULATING":
        raise ApiError("ERR_INVALID_STATE", 409, "Petition not circulating")
    # referential: parcel in petition's district and ACTIVE
    if parcel["bid_id"] != petition["bid_id"] or parcel["status"] != "ACTIVE":
        raise ApiError("ERR_PARCEL_NOT_IN_DISTRICT", 409, "Parcel not an ACTIVE parcel of district")
    # referential: one signature per (petition, parcel)
    if any(s["petition_id"] == pid and s["parcel_id"] == parcel_id for s in SIGNATURES.values()):
        raise ApiError("ERR_ALREADY_SIGNED", 409, "Parcel already signed this petition")
    # temporal: strictly before deadline
    if CLOCK["dt"] >= parse_dt(petition["circulation_deadline"]):
        raise ApiError("ERR_PETITION_DEADLINE_PASSED", 422, "Circulation deadline passed")
    sig = new_entity("PetitionSignature", {
        "petition_id": pid, "parcel_id": parcel_id, "support": support,
        "signed_at": now_iso(),
    }, common=False)
    SIGNATURES[sig["id"]] = sig
    return ok_object(serialize(sig), 201)


@app.route("/petition-signatures", methods=["GET"])
def list_signatures():
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    limit, offset = parse_pagination()
    petition_id = request.args.get("petition_id")
    parcel_id = request.args.get("parcel_id")
    items = list(SIGNATURES.values())
    if petition_id is not None:
        items = [s for s in items if s["petition_id"] == petition_id]
    if parcel_id is not None:
        items = [s for s in items if s["parcel_id"] == parcel_id]
    return ok_array(items, limit, offset)


@app.route("/petition-signatures/<sid>", methods=["GET"])
def get_signature_route(sid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    s = get_signature(sid)
    return ok_object(serialize(s), 200)


@app.route("/renewal-petitions/<pid>/submit", methods=["POST"])
def submit_petition(pid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    petition = get_petition(pid)
    if petition["status"] != "CIRCULATING":
        raise ApiError("ERR_INVALID_STATE", 409, "Petition not circulating")
    if CLOCK["dt"] >= parse_dt(petition["circulation_deadline"]):
        raise ApiError("ERR_PETITION_DEADLINE_PASSED", 422, "Circulation deadline passed")
    petition["status"] = "SUBMITTED"
    touch(petition)
    return ok_object(serialize(petition), 200)


def compute_weighted_support(petition):
    fy = basis_fiscal_year(petition["bid_id"])
    if fy is None:
        return Decimal("0")
    assessments = [a for a in ASSESSMENTS.values()
                   if a["fiscal_year_id"] == fy["id"] and a["status"] in ("CERTIFIED", "ADJUSTED")]
    total = sum(a["certified_amount_cents"] for a in assessments)
    if total == 0:
        return Decimal("0")
    sigs = {}
    for s in SIGNATURES.values():
        if s["petition_id"] == petition["id"]:
            sigs[s["parcel_id"]] = s
    support = sum(a["certified_amount_cents"] for a in assessments
                  if sigs.get(a["parcel_id"]) and sigs[a["parcel_id"]]["support"] is True)
    return (D(support) / D(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@app.route("/renewal-petitions/<pid>/verify", methods=["POST"])
def verify_petition(pid):
    uid, role = authenticate()
    require(role, {"BoardMember"})
    petition = get_petition(pid)
    if petition["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Petition not SUBMITTED")
    pct = compute_weighted_support(petition)
    petition["weighted_support_pct"] = pct
    petition["verified_by_user_id"] = uid
    threshold = D(petition["required_threshold_pct"])
    if pct >= threshold:
        petition["status"] = "VERIFIED"
        touch(petition)
    else:
        petition["status"] = "FAILED"
        touch(petition)
        bid = BIDS.get(petition["bid_id"])
        if bid is not None and bid["status"] == "RENEWAL_PENDING":
            bid["status"] = "EXPIRED"
            touch(bid)
    return ok_object(serialize(petition), 200)


@app.route("/renewal-petitions/<pid>/vote", methods=["POST"])
def vote_petition(pid):
    uid, role = authenticate()
    require(role, {"BoardMember"})
    petition = get_petition(pid)
    if petition["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Petition not VERIFIED")
    if uid == petition["verified_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Verifier may not vote")
    body = body_json()
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError("ERR_VALIDATION", 422, "Invalid decision")
    bid = BIDS.get(petition["bid_id"])
    if decision == "APPROVE":
        petition["status"] = "APPROVED"
        touch(petition)
        if bid is not None:
            new_dt = add_months(parse_dt(bid["authorization_expires_at"]),
                                petition["renewal_term_months"])
            bid["authorization_expires_at"] = iso_render(new_dt)
            bid["status"] = "ACTIVE"
            touch(bid)
    else:
        petition["status"] = "REJECTED"
        touch(petition)
        if bid is not None and bid["status"] == "RENEWAL_PENDING":
            bid["status"] = "EXPIRED"
            touch(bid)
    return ok_object(serialize(petition), 200)


# ============================================================================
# Routes: Ambassador / shifts
# ============================================================================
@app.route("/business-improvement-districts/<bid_id>/ambassadors", methods=["POST"])
def create_ambassador(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    get_bid(bid_id)
    body = body_json()
    name = req_str(body, "name")
    service_role = req_enum(body, "service_role", AMBASSADOR_ROLES)
    amb = new_entity("Ambassador", {
        "bid_id": bid_id, "name": name, "service_role": service_role, "status": "ACTIVE",
    })
    AMBASSADORS[amb["id"]] = amb
    return ok_object(serialize(amb), 201)


@app.route("/ambassadors/<aid>/deactivate", methods=["POST"])
def deactivate_ambassador(aid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    amb = get_ambassador(aid)
    if amb["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Ambassador not ACTIVE")
    amb["status"] = "INACTIVE"
    touch(amb)
    return ok_object(serialize(amb), 200)


@app.route("/business-improvement-districts/<bid_id>/ambassadors", methods=["GET"])
def list_ambassadors(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember"})
    get_bid(bid_id)
    limit, offset = parse_pagination()
    items = [a for a in AMBASSADORS.values() if a["bid_id"] == bid_id]
    return ok_array(items, limit, offset)


@app.route("/ambassadors/<aid>", methods=["GET"])
def get_ambassador_route(aid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "Ambassador"})
    amb = get_ambassador(aid)
    return ok_object(serialize(amb), 200)


@app.route("/ambassadors/<aid>/shifts", methods=["POST"])
def create_shift(aid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator"})
    amb = get_ambassador(aid)
    body = body_json()
    zone = req_str(body, "zone")
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")
    ns, ne = parse_dt(start_at), parse_dt(end_at)
    buffer_secs = SHIFT_BUFFER_MINUTES * 60
    for sh in SHIFTS.values():
        if sh["ambassador_id"] != aid or sh["status"] != "SCHEDULED":
            continue
        es, ee = parse_dt(sh["start_at"]), parse_dt(sh["end_at"])
        # OK only if new fully after with >=buffer gap, or fully before with >=buffer gap
        ok_after = (ns - ee).total_seconds() >= buffer_secs
        ok_before = (es - ne).total_seconds() >= buffer_secs
        if not (ok_after or ok_before):
            raise ApiError("ERR_SHIFT_OVERLAP", 409, "Shift overlaps or within buffer")
    shift = new_entity("AmbassadorShift", {
        "ambassador_id": aid, "zone": zone, "start_at": start_at, "end_at": end_at,
        "status": "SCHEDULED",
    })
    SHIFTS[shift["id"]] = shift
    return ok_object(serialize(shift), 201)


@app.route("/ambassadors/<aid>/shifts", methods=["GET"])
def list_shifts(aid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "Ambassador"})
    get_ambassador(aid)
    limit, offset = parse_pagination()
    items = [s for s in SHIFTS.values() if s["ambassador_id"] == aid]
    return ok_array(items, limit, offset)


# ============================================================================
# Routes: ServiceRequest
# ============================================================================
@app.route("/business-improvement-districts/<bid_id>/service-requests", methods=["POST"])
def create_service_request(bid_id):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "PropertyOwner"})
    get_bid(bid_id)
    body = body_json()
    category = req_enum(body, "category", SR_CATEGORIES)
    source = req_enum(body, "source", SR_SOURCES)
    external_ref = body.get("external_ref")
    if external_ref is not None and not isinstance(external_ref, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid external_ref")
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid description")
    sr = new_entity("ServiceRequest", {
        "bid_id": bid_id, "assigned_ambassador_id": None, "category": category,
        "source": source, "external_ref": external_ref, "description": description,
        "logged_cost_cents": 0, "work_plan_category": None, "status": "OPEN",
    })
    SERVICE_REQUESTS[sr["id"]] = sr
    return ok_object(serialize(sr), 201)


@app.route("/service-requests", methods=["GET"])
def list_service_requests():
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "Ambassador"})
    limit, offset = parse_pagination()
    bid_f = request.args.get("bid_id")
    amb_f = request.args.get("assigned_ambassador_id")
    status_f = request.args.get("status")
    items = list(SERVICE_REQUESTS.values())
    if bid_f is not None:
        items = [s for s in items if s["bid_id"] == bid_f]
    if amb_f is not None:
        items = [s for s in items if s["assigned_ambassador_id"] == amb_f]
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    return ok_array(items, limit, offset)


@app.route("/service-requests/<sid>", methods=["GET"])
def get_service_request_route(sid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "BoardMember", "Ambassador", "PropertyOwner"})
    sr = get_service_request(sid)
    return ok_object(serialize(sr), 200)


SR_ACTION_ROLE = {
    "ASSIGN": "DistrictAdministrator",
    "START": "Ambassador",
    "RESOLVE": "Ambassador",
    "CLOSE": "DistrictAdministrator",
    "CANCEL": "DistrictAdministrator",
}


@app.route("/service-requests/<sid>/transition", methods=["POST"])
def service_request_transition(sid):
    uid, role = authenticate()
    require(role, {"DistrictAdministrator", "Ambassador"})
    body = body_json()
    action = body.get("action")
    if action not in SR_ACTION_ROLE:
        raise ApiError("ERR_VALIDATION", 422, "Invalid action")
    if role != SR_ACTION_ROLE[action]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this action")
    sr = get_service_request(sid)

    if action == "ASSIGN":
        ambassador_id = req_str(body, "ambassador_id")
        amb = get_ambassador(ambassador_id)
        if sr["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Service request not OPEN")
        if amb["bid_id"] != sr["bid_id"] or amb["status"] != "ACTIVE":
            raise ApiError("ERR_AMBASSADOR_NOT_ACTIVE", 409, "Ambassador not ACTIVE in district")
        sr["assigned_ambassador_id"] = ambassador_id
        sr["status"] = "ASSIGNED"
        touch(sr)
    elif action == "START":
        if sr["assigned_ambassador_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the assigned ambassador")
        if sr["status"] != "ASSIGNED":
            raise ApiError("ERR_INVALID_STATE", 409, "Service request not ASSIGNED")
        sr["status"] = "IN_PROGRESS"
        touch(sr)
    elif action == "RESOLVE":
        if sr["assigned_ambassador_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the assigned ambassador")
        if sr["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", 409, "Service request not IN_PROGRESS")
        logged_cost = req_int(body, "logged_cost_cents", nonneg=True)
        wp_category = req_enum(body, "work_plan_category", WORKPLAN_CATEGORIES)
        line = find_workplan_line(sr["bid_id"], wp_category)
        if line is None:
            raise ApiError("ERR_WORK_PLAN_LINE_NOT_FOUND", 404, "No matching work-plan line")
        sr["logged_cost_cents"] = logged_cost
        sr["work_plan_category"] = wp_category
        sr["status"] = "RESOLVED"
        touch(sr)
        line["spent_amount_cents"] += logged_cost
        touch(line)
    elif action == "CLOSE":
        if sr["status"] != "RESOLVED":
            raise ApiError("ERR_INVALID_STATE", 409, "Service request not RESOLVED")
        sr["status"] = "CLOSED"
        touch(sr)
    elif action == "CANCEL":
        if sr["status"] not in ("OPEN", "ASSIGNED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Service request not cancellable")
        sr["status"] = "CANCELLED"
        touch(sr)
    return ok_object(serialize(sr), 200)


def find_workplan_line(bid_id, category):
    fy = basis_fiscal_year(bid_id)
    if fy is None:
        return None
    budget = next((b for b in BUDGETS.values()
                   if b["fiscal_year_id"] == fy["id"] and b["status"] == "ADOPTED"), None)
    if budget is None:
        return None
    return next((l for l in WORK_PLAN_LINES.values()
                 if l["budget_id"] == budget["id"] and l["category"] == category), None)


# ============================================================================
# Boot
# ============================================================================
reset_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
