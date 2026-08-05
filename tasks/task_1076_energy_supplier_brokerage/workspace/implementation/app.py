import os
import re
import uuid
import random
import string
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
FIVE_ROLES = {"BrokerAgent", "BrokerManager", "Supplier", "Customer", "OpsAdmin"}

MILLS_TO_CENTS_DIVISOR = 10
MIN_COMMISSION_CENTS = 5000
MAX_COMMISSION_CENTS = 5000000
MIN_BROKER_ADDER_MILLS = 2
DR_PENALTY_PER_KW_CENTS = 2000
RENEWAL_WINDOW_DAYS = 60
DR_BUFFER_DAYS = 14
RATE_ALERT_FACTOR = Decimal("0.9")  # 1 - 0.10

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# In-memory store
# =============================================================================
class DB:
    def __init__(self):
        self.customers = {}
        self.broker_users = {}
        self.suppliers = {}
        self.accounts = {}
        self.authorizations = {}
        self.usage_records = {}
        self.rfps = {}
        self.quotes = {}
        self.contracts = {}
        self.commission_statements = {}
        self.dr_enrollments = {}
        self.market_rates = {}  # (commodity, state_code) -> rate_mills
        self.clock = CLOCK_DEFAULT
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()


# =============================================================================
# Errors
# =============================================================================
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_DUPLICATE_ACCOUNT_NUMBER": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_REFERENTIAL_MISMATCH": 409,
    "ERR_STALE_RFP_VERSION": 412,
    "ERR_ACCOUNT_NOT_VERIFIED": 409,
    "ERR_LOA_SCOPE_INSUFFICIENT": 409,
    "ERR_SUPPLIER_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_NOT_ENROLLED": 409,
    "ERR_LOA_NOT_SIGNED": 409,
    "ERR_NO_USAGE_DATA": 409,
    "ERR_NO_QUOTES": 409,
    "ERR_NO_ACTUAL_USAGE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_RFP_CLOSED": 409,
    "ERR_CONTRACT_OVERLAP": 409,
    "ERR_DR_SEASON_CONFLICT": 409,
    "ERR_DR_SEASON_NOT_STARTED": 409,
    "ERR_RENEWAL_WINDOW_CLOSED": 409,
    "ERR_MARGIN_BELOW_MIN": 409,
    "ERR_APPROVAL_LIMIT_EXCEEDED": 409,
    "ERR_NO_ELIGIBLE_QUOTES": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# =============================================================================
# Time / formatting helpers
# =============================================================================
def iso_z(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_wall():
    return datetime.now(timezone.utc)


def now_iso():
    return iso_z(now_wall())


def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "date must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", f"unparseable date: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, n):
    month_index = dt.month - 1 + n
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def rhu(value):
    """round-half-up a Decimal (or numeric) to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# =============================================================================
# Response envelope
# =============================================================================
def make_meta(pagination=None):
    meta = {"api_request_id": req_id(), "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None, is_array=False):
    body = {
        "meta": make_meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


def err_response(error_id, message):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_STATUS.get(error_id, 400)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", "resource not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_NOT_FOUND", "method not allowed")


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_VALIDATION", f"internal: {e}")


# =============================================================================
# Common bookkeeping
# =============================================================================
def base_record(with_common=True):
    rec = {"id": new_id(), "_seq": db.next_seq(), "created_at": now_iso()}
    if with_common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()


# =============================================================================
# Auth
# =============================================================================
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or not uid.strip() or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "missing X-User-ID or X-User-Role")
    if role not in FIVE_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "malformed X-User-Role")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", "role not permitted for this endpoint")
    principal = resolve_principal(uid, role)
    g.uid = uid
    g.role = role
    g.principal = principal
    return uid, role, principal


def resolve_principal(uid, role):
    if role == "BrokerAgent":
        u = db.broker_users.get(uid)
        if not u or u["staff_role"] != "AGENT":
            raise ApiError("ERR_FORBIDDEN", "not a valid broker agent")
        return u
    if role == "BrokerManager":
        u = db.broker_users.get(uid)
        if not u or u["staff_role"] != "MANAGER":
            raise ApiError("ERR_FORBIDDEN", "not a valid broker manager")
        return u
    if role == "Supplier":
        s = db.suppliers.get(uid)
        if not s:
            raise ApiError("ERR_FORBIDDEN", "not a valid supplier")
        return s
    if role == "Customer":
        c = db.customers.get(uid)
        if not c:
            raise ApiError("ERR_FORBIDDEN", "not a valid customer")
        return c
    # OpsAdmin: opaque
    return None


# =============================================================================
# Body / field validation helpers
# =============================================================================
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise ApiError("ERR_VALIDATION", f"{field} must be a non-empty string")
    return v


def req_int_nonneg(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer")
    if v < 0:
        raise ApiError("ERR_VALIDATION", f"{field} must be non-negative")
    return v


def opt_int_nonneg(data, field, default):
    if field not in data or data[field] is None:
        return default
    return req_int_nonneg(data, field)


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", f"{field} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def req_date(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", f"{field} is required")
    return parse_dt(data[field])


def opt_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"{field} must be a boolean")
    return v


# =============================================================================
# Existence helpers
# =============================================================================
def must_get(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "resource not found")
    return rec


# =============================================================================
# Serialization
# =============================================================================
DATETIME_FIELDS = {
    "expires_at", "signed_at", "due_at", "start_date", "end_date",
    "requested_switch_date", "confirmed_switch_date", "season_start", "season_end",
}


def serialize(rec, extra_computed=None):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso_z(v)
        else:
            out[k] = v
    if extra_computed:
        out.update(extra_computed)
    return out


def account_reserved_dr_kw(account_id):
    total = 0
    for dr in db.dr_enrollments.values():
        if dr["account_id"] == account_id and dr["status"] in ("ENROLLED", "ACTIVE", "PERFORMED"):
            total += dr["committed_kw"]
    return total


def broker_pipeline_cents(broker_user_id):
    total = 0
    for st in db.commission_statements.values():
        contract = db.contracts.get(st["contract_id"])
        if not contract:
            continue
        if contract.get("broker_agent_id") == broker_user_id and st["status"] in (
            "PROVISIONAL", "APPROVED", "TRUED_UP"):
            total += st["net_commission_cents"] or 0
    return total


def ser_account(a):
    return serialize(a, {"reserved_dr_kw": account_reserved_dr_kw(a["id"])})


def ser_broker(u):
    return serialize(u, {"pipeline_commission_cents": broker_pipeline_cents(u["id"])})


# =============================================================================
# Pagination
# =============================================================================
def paginate(records):
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


# =============================================================================
# Calculations
# =============================================================================
def term_multiplier(term_months):
    if term_months <= 12:
        return Decimal("1.00")
    if term_months <= 24:
        return Decimal("1.10")
    return Decimal("1.20")


def estimated_gross_cents(usage_kwh, broker_adder_mills, term_months):
    base = rhu(Decimal(usage_kwh * broker_adder_mills) / Decimal(MILLS_TO_CENTS_DIVISOR))
    tiered = rhu(Decimal(base) * term_multiplier(term_months))
    return min(MAX_COMMISSION_CENTS, max(MIN_COMMISSION_CENTS, tiered))


def actual_gross_cents(usage_rows, broker_adder_mills, term_months):
    # round EACH month first, THEN sum
    per_month = []
    for row in usage_rows:
        per_month.append(
            rhu(Decimal(row["usage_kwh"] * broker_adder_mills) / Decimal(MILLS_TO_CENTS_DIVISOR)))
    summed = sum(per_month)
    tiered = rhu(Decimal(summed) * term_multiplier(term_months))
    return min(MAX_COMMISSION_CENTS, max(MIN_COMMISSION_CENTS, tiered))


def dr_settled_cents(committed_kw, performed_kw, incentive_per_kw_cents):
    if performed_kw >= committed_kw:
        return committed_kw * incentive_per_kw_cents
    shortfall = committed_kw - performed_kw
    return max(0, performed_kw * incentive_per_kw_cents - shortfall * DR_PENALTY_PER_KW_CENTS)


def select_winning_quote(rfp_id):
    candidates = [q for q in db.quotes.values()
                  if q["rfp_id"] == rfp_id and q["status"] == "SHORTLISTED"]
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_QUOTES", "no shortlisted quotes to award")
    candidates.sort(key=lambda q: (
        q["rate_mills_per_kwh"] + q["broker_adder_mills"],
        q["broker_adder_mills"],
        q["created_at"],
        q["_seq"],
    ))
    return candidates[0]


# =============================================================================
# Cascades
# =============================================================================
def void_rfp_quotes(rfp_id):
    for q in db.quotes.values():
        if q["rfp_id"] == rfp_id and q["status"] in ("SUBMITTED", "SHORTLISTED"):
            q["status"] = "VOID"
            touch(q)


def suspend_account(account):
    if account["status"] == "SUSPENDED":
        return
    account["status"] = "SUSPENDED"
    touch(account)
    # cancel open RFPs -> void their quotes
    for r in db.rfps.values():
        if r["account_id"] == account["id"] and r["status"] in ("DRAFT", "OPEN", "BEST_AND_FINAL"):
            r["status"] = "CANCELLED"
            touch(r)
            void_rfp_quotes(r["id"])


# =============================================================================
# ROUTES
# =============================================================================

# ---- Customer ----
@app.route("/customers", methods=["POST"])
def create_customer():
    authenticate({"BrokerAgent", "OpsAdmin"})
    data = get_body()
    legal_name = req_str(data, "legal_name")
    email = req_str(data, "email")
    segment = req_enum(data, "segment", {"RESIDENTIAL", "SMALL_COMMERCIAL", "LARGE_COMMERCIAL"})
    service_state = req_str(data, "service_state")
    rec = base_record()
    rec.update({
        "legal_name": legal_name, "email": email, "segment": segment,
        "service_state": service_state, "status": "ACTIVE",
    })
    db.customers[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "Customer", "OpsAdmin"})
    rec = must_get(db.customers, cid)
    return ok(serialize(rec))


# ---- BrokerUser ----
@app.route("/broker-users", methods=["POST"])
def create_broker_user():
    authenticate({"OpsAdmin"})
    data = get_body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    staff_role = req_enum(data, "staff_role", {"AGENT", "MANAGER"})
    approval_limit = opt_int_nonneg(data, "approval_limit_cents", 0)
    rec = base_record()
    rec.update({
        "full_name": full_name, "email": email, "staff_role": staff_role,
        "approval_limit_cents": approval_limit,
    })
    db.broker_users[rec["id"]] = rec
    return ok(ser_broker(rec), 201)


@app.route("/broker-users/<uid>", methods=["GET"])
def get_broker_user(uid):
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    rec = must_get(db.broker_users, uid)
    return ok(ser_broker(rec))


# ---- Supplier ----
@app.route("/suppliers", methods=["POST"])
def create_supplier():
    authenticate({"OpsAdmin"})
    data = get_body()
    name = req_str(data, "name")
    commodity = req_enum(data, "commodity", {"ELECTRICITY", "GAS"})
    service_states = data.get("service_states")
    if not isinstance(service_states, list) or not all(isinstance(x, str) for x in service_states):
        raise ApiError("ERR_VALIDATION", "service_states must be an array of strings")
    rec = base_record()
    rec.update({
        "name": name, "commodity": commodity,
        "service_states": service_states, "status": "ACTIVE",
    })
    db.suppliers[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "Customer", "OpsAdmin"})
    rec = must_get(db.suppliers, sid)
    return ok(serialize(rec))


@app.route("/suppliers/<sid>/set-status", methods=["POST"])
def set_supplier_status(sid):
    authenticate({"OpsAdmin"})
    rec = must_get(db.suppliers, sid)
    data = get_body()
    target = req_enum(data, "status", {"ACTIVE", "SUSPENDED"})
    if target == rec["status"]:
        raise ApiError("ERR_INVALID_STATE", f"supplier already {target}")
    if target == "SUSPENDED":
        # ACTIVE -> SUSPENDED
        rec["status"] = "SUSPENDED"
        touch(rec)
        for q in db.quotes.values():
            if q["supplier_id"] == sid and q["status"] in ("SUBMITTED", "SHORTLISTED"):
                was_shortlisted = q["status"] == "SHORTLISTED"
                q["status"] = "WITHDRAWN"
                touch(q)
                if was_shortlisted:
                    r = db.rfps.get(q["rfp_id"])
                    if r and r["status"] == "BEST_AND_FINAL":
                        r["status"] = "OPEN"
                        touch(r)
    else:
        # SUSPENDED -> ACTIVE
        rec["status"] = "ACTIVE"
        touch(rec)
    return ok(serialize(rec))


# ---- UtilityAccount ----
@app.route("/accounts", methods=["POST"])
def create_account():
    authenticate({"BrokerAgent"})
    data = get_body()
    customer_id = data.get("customer_id")
    broker_agent_id = data.get("broker_agent_id")
    if isinstance(customer_id, str) and customer_id:
        must_get(db.customers, customer_id)
    if isinstance(broker_agent_id, str) and broker_agent_id:
        must_get(db.broker_users, broker_agent_id)
    customer_id = req_str(data, "customer_id")
    broker_agent_id = req_str(data, "broker_agent_id")
    utility_name = req_str(data, "utility_name")
    account_number = req_str(data, "account_number")
    commodity = req_enum(data, "commodity", {"ELECTRICITY", "GAS"})
    state_code = req_str(data, "state_code")
    est_usage = req_int_nonneg(data, "estimated_annual_usage_kwh")
    # unique account_number per utility_name
    for a in db.accounts.values():
        if a["utility_name"] == utility_name and a["account_number"] == account_number:
            raise ApiError("ERR_DUPLICATE_ACCOUNT_NUMBER", "account_number exists for utility")
    rec = base_record()
    rec.update({
        "customer_id": customer_id, "broker_agent_id": broker_agent_id,
        "utility_name": utility_name, "account_number": account_number,
        "commodity": commodity, "state_code": state_code,
        "estimated_annual_usage_kwh": est_usage, "status": "PENDING_LOA",
    })
    db.accounts[rec["id"]] = rec
    return ok(ser_account(rec), 201)


@app.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "Customer", "OpsAdmin"})
    rec = must_get(db.accounts, aid)
    return ok(ser_account(rec))


@app.route("/accounts", methods=["GET"])
def list_accounts():
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    customer_id = request.args.get("customer_id")
    broker_agent_id = request.args.get("broker_agent_id")
    recs = list(db.accounts.values())
    if customer_id:
        recs = [r for r in recs if r["customer_id"] == customer_id]
    if broker_agent_id:
        recs = [r for r in recs if r["broker_agent_id"] == broker_agent_id]
    page, pg = paginate(recs)
    return ok([ser_account(r) for r in page], 200, pg, True)


@app.route("/accounts/<aid>/verify", methods=["POST"])
def verify_account(aid):
    authenticate({"BrokerAgent"})
    rec = must_get(db.accounts, aid)
    if rec["status"] != "PENDING_LOA":
        raise ApiError("ERR_INVALID_STATE", "account not in PENDING_LOA")
    signed = [
        a for a in db.authorizations.values()
        if a["account_id"] == aid and a["status"] == "SIGNED"
        and a["expires_at"] > db.clock
    ]
    if not signed:
        raise ApiError("ERR_LOA_NOT_SIGNED", "no signed non-expired LOA")
    has_usage = any(u["account_id"] == aid for u in db.usage_records.values())
    if not has_usage:
        raise ApiError("ERR_NO_USAGE_DATA", "no usage records for account")
    rec["status"] = "VERIFIED"
    touch(rec)
    return ok(ser_account(rec))


# ---- Authorization ----
@app.route("/authorizations", methods=["POST"])
def create_authorization():
    authenticate({"BrokerAgent"})
    data = get_body()
    account_id = data.get("account_id")
    if isinstance(account_id, str) and account_id:
        must_get(db.accounts, account_id)
    account_id = req_str(data, "account_id")
    must_get(db.accounts, account_id)
    scope = req_enum(data, "scope", {"USAGE_ONLY", "USAGE_AND_ENROLL"})
    expires_at = req_date(data, "expires_at")
    if expires_at <= db.clock:
        raise ApiError("ERR_VALIDATION", "expires_at must be in the future")
    rec = base_record()
    rec.update({
        "account_id": account_id, "scope": scope, "signed_at": None,
        "expires_at": expires_at, "status": "DRAFT",
    })
    db.authorizations[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/authorizations/<lid>", methods=["GET"])
def get_authorization(lid):
    authenticate({"BrokerAgent", "BrokerManager", "Customer", "OpsAdmin"})
    rec = must_get(db.authorizations, lid)
    return ok(serialize(rec))


@app.route("/authorizations", methods=["GET"])
def list_authorizations():
    authenticate({"BrokerAgent", "BrokerManager", "Customer", "OpsAdmin"})
    account_id = request.args.get("account_id")
    recs = list(db.authorizations.values())
    if account_id:
        recs = [r for r in recs if r["account_id"] == account_id]
    page, pg = paginate(recs)
    return ok([serialize(r) for r in page], 200, pg, True)


@app.route("/authorizations/<lid>/sign", methods=["POST"])
def sign_authorization(lid):
    uid, role, principal = authenticate({"Customer"})
    rec = must_get(db.authorizations, lid)
    account = must_get(db.accounts, rec["account_id"])
    if account["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", "customer does not own the account")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "LOA not in DRAFT")
    if rec["expires_at"] <= db.clock:
        raise ApiError("ERR_VALIDATION", "expires_at must be strictly after now")
    rec["status"] = "SIGNED"
    rec["signed_at"] = db.clock
    touch(rec)
    return ok(serialize(rec))


@app.route("/authorizations/<lid>/revoke", methods=["POST"])
def revoke_authorization(lid):
    uid, role, principal = authenticate({"Customer"})
    rec = must_get(db.authorizations, lid)
    account = must_get(db.accounts, rec["account_id"])
    if account["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", "customer does not own the account")
    if rec["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_STATE", "LOA not in SIGNED")
    rec["status"] = "REVOKED"
    touch(rec)
    suspend_account(account)
    return ok(serialize(rec))


# ---- UsageRecord ----
@app.route("/usage-records", methods=["POST"])
def create_usage_record():
    authenticate({"BrokerAgent", "OpsAdmin"})
    data = get_body()
    account_id = data.get("account_id")
    if isinstance(account_id, str) and account_id:
        must_get(db.accounts, account_id)
    account_id = req_str(data, "account_id")
    must_get(db.accounts, account_id)
    period_month = req_str(data, "period_month")
    if not re.match(r"^\d{4}-\d{2}$", period_month):
        raise ApiError("ERR_VALIDATION", "period_month must be YYYY-MM")
    usage_kwh = req_int_nonneg(data, "usage_kwh")
    source = opt_enum(data, "source", {"UTILITY_EDI", "BROKER_ESTIMATE"}, "UTILITY_EDI")
    is_actual = opt_bool(data, "is_actual", True)
    rec = base_record(with_common=False)
    rec.update({
        "account_id": account_id, "period_month": period_month,
        "usage_kwh": usage_kwh, "source": source, "is_actual": is_actual,
    })
    db.usage_records[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/usage-records/<rid>", methods=["GET"])
def get_usage_record(rid):
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    rec = must_get(db.usage_records, rid)
    return ok(serialize(rec))


@app.route("/usage-records", methods=["GET"])
def list_usage_records():
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    account_id = request.args.get("account_id")
    recs = list(db.usage_records.values())
    if account_id:
        recs = [r for r in recs if r["account_id"] == account_id]
    page, pg = paginate(recs)
    return ok([serialize(r) for r in page], 200, pg, True)


# ---- Rfp ----
@app.route("/rfps", methods=["POST"])
def create_rfp():
    authenticate({"BrokerAgent"})
    data = get_body()
    account_id = data.get("account_id")
    broker_agent_id = data.get("broker_agent_id")
    if isinstance(account_id, str) and account_id:
        must_get(db.accounts, account_id)
    if isinstance(broker_agent_id, str) and broker_agent_id:
        must_get(db.broker_users, broker_agent_id)
    account_id = req_str(data, "account_id")
    must_get(db.accounts, account_id)
    broker_agent_id = req_str(data, "broker_agent_id")
    must_get(db.broker_users, broker_agent_id)
    term_months_requested = req_int_nonneg(data, "term_months_requested")
    green_pct_requested = opt_int_nonneg(data, "green_pct_requested", 0)
    due_at = req_date(data, "due_at")
    rec = base_record()
    rec.update({
        "account_id": account_id, "broker_agent_id": broker_agent_id,
        "term_months_requested": term_months_requested,
        "green_pct_requested": green_pct_requested,
        "due_at": due_at, "status": "DRAFT",
    })
    db.rfps[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/rfps/<rid>", methods=["GET"])
def get_rfp(rid):
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "Customer", "OpsAdmin"})
    rec = must_get(db.rfps, rid)
    return ok(serialize(rec))


@app.route("/rfps", methods=["GET"])
def list_rfps():
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "OpsAdmin"})
    account_id = request.args.get("account_id")
    broker_agent_id = request.args.get("broker_agent_id")
    recs = list(db.rfps.values())
    if account_id:
        recs = [r for r in recs if r["account_id"] == account_id]
    if broker_agent_id:
        recs = [r for r in recs if r["broker_agent_id"] == broker_agent_id]
    page, pg = paginate(recs)
    return ok([serialize(r) for r in page], 200, pg, True)


@app.route("/rfps/<rid>/transition", methods=["POST"])
def transition_rfp(rid):
    authenticate({"BrokerAgent"})
    rec = must_get(db.rfps, rid)
    data = get_body()
    action = req_enum(data, "action", {"OPEN", "BEST_AND_FINAL", "REOPEN", "CANCEL"})
    status = rec["status"]
    if action == "OPEN":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "RFP not in DRAFT")
        account = db.accounts.get(rec["account_id"])
        if not account or account["status"] != "VERIFIED":
            raise ApiError("ERR_ACCOUNT_NOT_VERIFIED", "account not VERIFIED")
        has_scope = any(
            a["account_id"] == rec["account_id"] and a["status"] == "SIGNED"
            and a["scope"] == "USAGE_AND_ENROLL"
            for a in db.authorizations.values())
        if not has_scope:
            raise ApiError("ERR_LOA_SCOPE_INSUFFICIENT", "no SIGNED USAGE_AND_ENROLL LOA")
        rec["status"] = "OPEN"
        touch(rec)
    elif action == "BEST_AND_FINAL":
        if status != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "RFP not in OPEN")
        has_quote = any(
            q["rfp_id"] == rid and q["status"] in ("SUBMITTED", "SHORTLISTED")
            for q in db.quotes.values())
        if not has_quote:
            raise ApiError("ERR_NO_QUOTES", "no SUBMITTED/SHORTLISTED quotes")
        rec["status"] = "BEST_AND_FINAL"
        touch(rec)
    elif action == "REOPEN":
        if status != "BEST_AND_FINAL":
            raise ApiError("ERR_INVALID_STATE", "RFP not in BEST_AND_FINAL")
        rec["status"] = "OPEN"
        touch(rec)
    elif action == "CANCEL":
        if status not in ("OPEN", "BEST_AND_FINAL"):
            raise ApiError("ERR_INVALID_STATE", "RFP cannot be cancelled from this state")
        rec["status"] = "CANCELLED"
        touch(rec)
        void_rfp_quotes(rid)
    return ok(serialize(rec))


# ---- Quote ----
@app.route("/quotes", methods=["POST"])
def create_quote():
    uid, role, principal = authenticate({"Supplier"})
    data = get_body()
    rfp_id = data.get("rfp_id")
    supplier_id = data.get("supplier_id")
    if isinstance(rfp_id, str) and rfp_id:
        must_get(db.rfps, rfp_id)
    if isinstance(supplier_id, str) and supplier_id:
        must_get(db.suppliers, supplier_id)
    rfp_id = req_str(data, "rfp_id")
    rfp = must_get(db.rfps, rfp_id)
    supplier_id = req_str(data, "supplier_id")
    must_get(db.suppliers, supplier_id)
    if supplier_id != uid:
        raise ApiError("ERR_FORBIDDEN", "supplier may only submit its own quote")
    rate = req_int_nonneg(data, "rate_mills_per_kwh")
    term_months = req_int_nonneg(data, "term_months")
    green_pct = opt_int_nonneg(data, "green_pct", 0)
    broker_adder = req_int_nonneg(data, "broker_adder_mills")
    expected_version = req_int_nonneg(data, "expected_rfp_version")
    # state: RFP must be accepting quotes
    if rfp["status"] not in ("OPEN", "BEST_AND_FINAL"):
        raise ApiError("ERR_INVALID_STATE", "RFP not accepting quotes")
    # OCC
    if expected_version != rfp["version"]:
        raise ApiError("ERR_STALE_RFP_VERSION", "expected_rfp_version is stale")
    # temporal: deadline
    if db.clock >= rfp["due_at"]:
        raise ApiError("ERR_RFP_CLOSED", "RFP bidding is closed")
    # fiscal: margin floor
    if broker_adder < MIN_BROKER_ADDER_MILLS:
        raise ApiError("ERR_MARGIN_BELOW_MIN", "broker_adder_mills below minimum")
    rec = base_record()
    rec.update({
        "rfp_id": rfp_id, "supplier_id": supplier_id, "rate_mills_per_kwh": rate,
        "term_months": term_months, "green_pct": green_pct,
        "broker_adder_mills": broker_adder, "status": "SUBMITTED",
    })
    db.quotes[rec["id"]] = rec
    rfp["version"] += 1
    rfp["updated_at"] = now_iso()
    return ok(serialize(rec), 201)


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "OpsAdmin"})
    rec = must_get(db.quotes, qid)
    return ok(serialize(rec))


@app.route("/quotes", methods=["GET"])
def list_quotes():
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "OpsAdmin"})
    rfp_id = request.args.get("rfp_id")
    supplier_id = request.args.get("supplier_id")
    recs = list(db.quotes.values())
    if rfp_id:
        recs = [r for r in recs if r["rfp_id"] == rfp_id]
    if supplier_id:
        recs = [r for r in recs if r["supplier_id"] == supplier_id]
    page, pg = paginate(recs)
    return ok([serialize(r) for r in page], 200, pg, True)


@app.route("/quotes/<qid>/shortlist", methods=["POST"])
def shortlist_quote(qid):
    authenticate({"BrokerAgent"})
    rec = must_get(db.quotes, qid)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "quote not SUBMITTED")
    rfp = db.rfps.get(rec["rfp_id"])
    if not rfp or rfp["status"] not in ("OPEN", "BEST_AND_FINAL"):
        raise ApiError("ERR_INVALID_STATE", "parent RFP not open for shortlisting")
    rec["status"] = "SHORTLISTED"
    touch(rec)
    return ok(serialize(rec))


@app.route("/quotes/<qid>/withdraw", methods=["POST"])
def withdraw_quote(qid):
    uid, role, principal = authenticate({"Supplier"})
    rec = must_get(db.quotes, qid)
    if rec["supplier_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", "supplier does not own this quote")
    if rec["status"] not in ("SUBMITTED", "SHORTLISTED"):
        raise ApiError("ERR_INVALID_STATE", "quote not withdrawable")
    was_shortlisted = rec["status"] == "SHORTLISTED"
    rec["status"] = "WITHDRAWN"
    touch(rec)
    if was_shortlisted:
        rfp = db.rfps.get(rec["rfp_id"])
        if rfp and rfp["status"] == "BEST_AND_FINAL":
            rfp["status"] = "OPEN"
            touch(rfp)
    return ok(serialize(rec))


# ---- Contract ----
@app.route("/contracts", methods=["POST"])
def award_contract():
    authenticate({"BrokerAgent"})
    data = get_body()
    rfp_id = data.get("rfp_id")
    account_id = data.get("account_id")
    if isinstance(rfp_id, str) and rfp_id:
        must_get(db.rfps, rfp_id)
    if isinstance(account_id, str) and account_id:
        must_get(db.accounts, account_id)
    rfp_id = req_str(data, "rfp_id")
    rfp = must_get(db.rfps, rfp_id)
    account_id = req_str(data, "account_id")
    account = must_get(db.accounts, account_id)
    est_usage = req_int_nonneg(data, "estimated_annual_usage_kwh")
    start_date = req_date(data, "start_date")
    requested_switch_date = req_date(data, "requested_switch_date")
    # state: award transitions RFP to AWARDED, defined only from OPEN or BEST_AND_FINAL (§3.3)
    if rfp["status"] not in ("OPEN", "BEST_AND_FINAL"):
        raise ApiError("ERR_INVALID_STATE", "RFP not awardable from this state")
    # referential coherence
    if rfp["account_id"] != account_id:
        raise ApiError("ERR_REFERENTIAL_MISMATCH", "rfp does not belong to account")
    winning = select_winning_quote(rfp_id)
    term_months = winning["term_months"]
    end_date = add_months(start_date, term_months)
    mr = db.market_rates.get((account["commodity"], account["state_code"]))
    rec = base_record()
    rec.update({
        "account_id": account_id,
        "quote_id": winning["id"],
        "supplier_id": winning["supplier_id"],
        "broker_agent_id": rfp["broker_agent_id"],
        "renewed_from_contract_id": None,
        "term_months": term_months,
        "rate_mills_per_kwh": winning["rate_mills_per_kwh"],
        "broker_adder_mills": winning["broker_adder_mills"],
        "rec_adder_mills": 0,
        "green_pct": winning["green_pct"],
        "estimated_annual_usage_kwh": est_usage,
        "start_date": start_date,
        "end_date": end_date,
        "requested_switch_date": requested_switch_date,
        "confirmed_switch_date": None,
        "renewal_window_open": False,
        "rate_alert": "NONE",
        "latest_market_rate_mills": mr,
        "status": "PENDING_CUSTOMER",
    })
    db.contracts[rec["id"]] = rec
    winning["status"] = "AWARDED"
    touch(winning)
    rfp["status"] = "AWARDED"
    touch(rfp)
    return ok(serialize(rec), 201)


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "Customer", "OpsAdmin"})
    rec = must_get(db.contracts, cid)
    return ok(serialize(rec))


@app.route("/contracts", methods=["GET"])
def list_contracts():
    authenticate({"BrokerAgent", "BrokerManager", "Supplier", "Customer", "OpsAdmin"})
    filters = ["account_id", "quote_id", "supplier_id", "broker_agent_id",
               "renewed_from_contract_id"]
    recs = list(db.contracts.values())
    for f in filters:
        val = request.args.get(f)
        if val:
            recs = [r for r in recs if r.get(f) == val]
    page, pg = paginate(recs)
    return ok([serialize(r) for r in page], 200, pg, True)


@app.route("/contracts/<cid>/customer-decision", methods=["POST"])
def contract_customer_decision(cid):
    uid, role, principal = authenticate({"Customer"})
    rec = must_get(db.contracts, cid)
    account = must_get(db.accounts, rec["account_id"])
    if account["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", "customer does not own the contract's account")
    data = get_body()
    decision = req_enum(data, "decision", {"ACCEPT", "REJECT"})
    if rec["status"] != "PENDING_CUSTOMER":
        raise ApiError("ERR_INVALID_STATE", "contract not PENDING_CUSTOMER")
    if decision == "ACCEPT":
        rec["status"] = "PENDING_APPROVAL"
        touch(rec)
    else:
        rec["status"] = "REJECTED"
        touch(rec)
        quote = db.quotes.get(rec["quote_id"])
        if quote and quote["status"] == "AWARDED":
            quote["status"] = "VOID"
            touch(quote)
            rfp = db.rfps.get(quote["rfp_id"])
            if rfp and rfp["status"] == "AWARDED":
                rfp["status"] = "BEST_AND_FINAL"
                touch(rfp)
    return ok(serialize(rec))


@app.route("/contracts/<cid>/approve", methods=["POST"])
def approve_contract(cid):
    uid, role, principal = authenticate({"BrokerManager"})
    rec = must_get(db.contracts, cid)
    if rec["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "contract not PENDING_APPROVAL")
    supplier = db.suppliers.get(rec["supplier_id"])
    if not supplier or supplier["status"] != "ACTIVE":
        raise ApiError("ERR_SUPPLIER_NOT_ACTIVE", "supplier not ACTIVE")
    if rec["broker_adder_mills"] < MIN_BROKER_ADDER_MILLS:
        raise ApiError("ERR_MARGIN_BELOW_MIN", "broker_adder_mills below minimum")
    gross = estimated_gross_cents(
        rec["estimated_annual_usage_kwh"], rec["broker_adder_mills"], rec["term_months"])
    if gross > principal["approval_limit_cents"]:
        raise ApiError("ERR_APPROVAL_LIMIT_EXCEEDED", "gross exceeds approval limit")
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(serialize(rec))


@app.route("/contracts/<cid>/submit-enrollment", methods=["POST"])
def submit_enrollment(cid):
    authenticate({"BrokerAgent"})
    rec = must_get(db.contracts, cid)
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "contract not APPROVED")
    data = get_body()
    # overlap check against other live contracts on the same account
    for other in db.contracts.values():
        if other["id"] == cid:
            continue
        if other["account_id"] != rec["account_id"]:
            continue
        if other["status"] not in ("APPROVED", "ENROLLMENT_SUBMITTED", "ACTIVE"):
            continue
        if rec["start_date"] < other["end_date"] and other["start_date"] < rec["end_date"]:
            raise ApiError("ERR_CONTRACT_OVERLAP", "supply interval overlaps another contract")
    if data.get("requested_switch_date") is not None:
        rec["requested_switch_date"] = parse_dt(data["requested_switch_date"])
    rec["status"] = "ENROLLMENT_SUBMITTED"
    touch(rec)
    # forward commission invariant: create PROVISIONAL statement
    gross = estimated_gross_cents(
        rec["estimated_annual_usage_kwh"], rec["broker_adder_mills"], rec["term_months"])
    st = base_record()
    st.update({
        "contract_id": cid, "basis": "ESTIMATED",
        "gross_commission_cents": gross, "actual_gross_cents": None,
        "true_up_delta_cents": None, "clawback_cents": 0,
        "net_commission_cents": gross, "approved_by_manager_id": None,
        "trued_up_by_manager_id": None, "status": "PROVISIONAL",
    })
    db.commission_statements[st["id"]] = st
    return ok(serialize(rec))


@app.route("/contracts/<cid>/enrollment-result", methods=["POST"])
def enrollment_result(cid):
    authenticate({"OpsAdmin"})
    rec = must_get(db.contracts, cid)
    data = get_body()
    result = req_enum(data, "result", {"CONFIRM", "REJECT"})
    if rec["status"] != "ENROLLMENT_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "contract not ENROLLMENT_SUBMITTED")
    if result == "CONFIRM":
        rec["status"] = "ACTIVE"
        rec["confirmed_switch_date"] = db.clock
        touch(rec)
        account = db.accounts.get(rec["account_id"])
        if account and account["status"] == "VERIFIED":
            account["status"] = "ENROLLED"
            touch(account)
    else:
        rec["status"] = "DROPPED"
        touch(rec)
        for st in db.commission_statements.values():
            if st["contract_id"] == cid and st["status"] == "PROVISIONAL":
                st["status"] = "VOIDED"
                st["net_commission_cents"] = 0
                touch(st)
    return ok(serialize(rec))


@app.route("/contracts/<cid>/add-rec-rider", methods=["POST"])
def add_rec_rider(cid):
    authenticate({"BrokerAgent"})
    rec = must_get(db.contracts, cid)
    data = get_body()
    rec_adder = req_int_nonneg(data, "rec_adder_mills")
    if rec["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", "REC rider only on not-yet-active contract")
    rec["rec_adder_mills"] = rec_adder
    rec["green_pct"] = 100
    touch(rec)
    return ok(serialize(rec))


@app.route("/contracts/<cid>/renew", methods=["POST"])
def renew_contract(cid):
    authenticate({"BrokerAgent"})
    rec = must_get(db.contracts, cid)
    data = get_body()
    start_date = req_date(data, "start_date")
    requested_switch_date = req_date(data, "requested_switch_date")
    est_usage = req_int_nonneg(data, "estimated_annual_usage_kwh")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "contract not ACTIVE")
    if not rec["renewal_window_open"]:
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", "renewal window not open")
    rec["status"] = "RENEWED"
    touch(rec)
    account = db.accounts.get(rec["account_id"])
    mr = None
    if account:
        mr = db.market_rates.get((account["commodity"], account["state_code"]))
    end_date = add_months(start_date, rec["term_months"])
    succ = base_record()
    succ.update({
        "account_id": rec["account_id"],
        "quote_id": rec["quote_id"],
        "supplier_id": rec["supplier_id"],
        "broker_agent_id": rec["broker_agent_id"],
        "renewed_from_contract_id": rec["id"],
        "term_months": rec["term_months"],
        "rate_mills_per_kwh": rec["rate_mills_per_kwh"],
        "broker_adder_mills": rec["broker_adder_mills"],
        "rec_adder_mills": 0,
        "green_pct": rec["green_pct"],
        "estimated_annual_usage_kwh": est_usage,
        "start_date": start_date,
        "end_date": end_date,
        "requested_switch_date": requested_switch_date,
        "confirmed_switch_date": None,
        "renewal_window_open": False,
        "rate_alert": "NONE",
        "latest_market_rate_mills": mr,
        "status": "PENDING_CUSTOMER",
    })
    db.contracts[succ["id"]] = succ
    return ok(serialize(succ), 201)


# ---- CommissionStatement ----
@app.route("/commission-statements/<sid>", methods=["GET"])
def get_statement(sid):
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    rec = must_get(db.commission_statements, sid)
    return ok(serialize(rec))


@app.route("/commission-statements", methods=["GET"])
def list_statements():
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    contract_id = request.args.get("contract_id")
    recs = list(db.commission_statements.values())
    if contract_id:
        recs = [r for r in recs if r["contract_id"] == contract_id]
    page, pg = paginate(recs)
    return ok([serialize(r) for r in page], 200, pg, True)


@app.route("/commission-statements/<sid>/approve", methods=["POST"])
def approve_statement(sid):
    uid, role, principal = authenticate({"BrokerManager"})
    rec = must_get(db.commission_statements, sid)
    if rec["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", "statement not PROVISIONAL")
    contract = db.contracts.get(rec["contract_id"])
    if not contract or contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "parent contract not ACTIVE")
    rec["status"] = "APPROVED"
    rec["approved_by_manager_id"] = uid
    touch(rec)
    return ok(serialize(rec))


@app.route("/commission-statements/<sid>/true-up", methods=["POST"])
def trueup_statement(sid):
    uid, role, principal = authenticate({"BrokerManager"})
    rec = must_get(db.commission_statements, sid)
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "statement not APPROVED")
    if uid == rec["approved_by_manager_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "true-up manager equals approver")
    contract = db.contracts.get(rec["contract_id"])
    account_id = contract["account_id"] if contract else None
    actual_rows = [
        u for u in db.usage_records.values()
        if u["account_id"] == account_id and u["is_actual"] is True
    ]
    if not actual_rows:
        raise ApiError("ERR_NO_ACTUAL_USAGE", "no actual usage records")
    actual_rows.sort(key=lambda u: u["period_month"])
    actual = actual_gross_cents(
        actual_rows, contract["broker_adder_mills"], contract["term_months"])
    rec["basis"] = "ACTUAL"
    rec["actual_gross_cents"] = actual
    rec["true_up_delta_cents"] = actual - rec["gross_commission_cents"]
    rec["clawback_cents"] = max(0, rec["gross_commission_cents"] - actual)
    rec["net_commission_cents"] = actual
    rec["trued_up_by_manager_id"] = uid
    rec["status"] = "TRUED_UP"
    touch(rec)
    return ok(serialize(rec))


# ---- DemandResponseEnrollment ----
@app.route("/dr-enrollments", methods=["POST"])
def create_dr():
    authenticate({"BrokerAgent"})
    data = get_body()
    account_id = data.get("account_id")
    if isinstance(account_id, str) and account_id:
        must_get(db.accounts, account_id)
    account_id = req_str(data, "account_id")
    must_get(db.accounts, account_id)
    program_name = req_str(data, "program_name")
    season_start = req_date(data, "season_start")
    season_end = req_date(data, "season_end")
    committed_kw = req_int_nonneg(data, "committed_kw")
    incentive = req_int_nonneg(data, "incentive_per_kw_cents")
    # season conflict/buffer check against live DR on this account
    buffer = timedelta(days=DR_BUFFER_DAYS)
    for other in db.dr_enrollments.values():
        if other["account_id"] != account_id:
            continue
        if other["status"] not in ("ENROLLED", "ACTIVE", "PERFORMED"):
            continue
        os_, oe = other["season_start"], other["season_end"]
        # closed intervals overlap?
        overlap = season_start <= oe and os_ <= season_end
        if overlap:
            raise ApiError("ERR_DR_SEASON_CONFLICT", "DR season overlaps live season")
        if season_start > oe:
            if (season_start - oe) < buffer:
                raise ApiError("ERR_DR_SEASON_CONFLICT", "DR season within buffer")
        else:  # season_end < os_
            if (os_ - season_end) < buffer:
                raise ApiError("ERR_DR_SEASON_CONFLICT", "DR season within buffer")
    rec = base_record()
    rec.update({
        "account_id": account_id, "program_name": program_name,
        "season_start": season_start, "season_end": season_end,
        "committed_kw": committed_kw, "incentive_per_kw_cents": incentive,
        "performed_kw": None,
        "provisional_incentive_cents": committed_kw * incentive,
        "settled_incentive_cents": None, "status": "ENROLLED",
    })
    db.dr_enrollments[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/dr-enrollments/<did>", methods=["GET"])
def get_dr(did):
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    rec = must_get(db.dr_enrollments, did)
    return ok(serialize(rec))


@app.route("/dr-enrollments", methods=["GET"])
def list_dr():
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    account_id = request.args.get("account_id")
    recs = list(db.dr_enrollments.values())
    if account_id:
        recs = [r for r in recs if r["account_id"] == account_id]
    page, pg = paginate(recs)
    return ok([serialize(r) for r in page], 200, pg, True)


@app.route("/dr-enrollments/<did>/activate", methods=["POST"])
def activate_dr(did):
    authenticate({"OpsAdmin"})
    rec = must_get(db.dr_enrollments, did)
    if rec["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", "DR not ENROLLED")
    account = db.accounts.get(rec["account_id"])
    if not account or account["status"] != "ENROLLED":
        raise ApiError("ERR_ACCOUNT_NOT_ENROLLED", "account not ENROLLED")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(serialize(rec))


@app.route("/dr-enrollments/<did>/record-performance", methods=["POST"])
def record_performance(did):
    authenticate({"OpsAdmin"})
    rec = must_get(db.dr_enrollments, did)
    data = get_body()
    performed_kw = req_int_nonneg(data, "performed_kw")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "DR not ACTIVE")
    if db.clock < rec["season_start"]:
        raise ApiError("ERR_DR_SEASON_NOT_STARTED", "DR season not started")
    rec["performed_kw"] = performed_kw
    rec["status"] = "PERFORMED"
    touch(rec)
    return ok(serialize(rec))


@app.route("/dr-enrollments/<did>/settle", methods=["POST"])
def settle_dr(did):
    authenticate({"BrokerManager"})
    rec = must_get(db.dr_enrollments, did)
    if rec["status"] != "PERFORMED":
        raise ApiError("ERR_INVALID_STATE", "DR not PERFORMED")
    rec["settled_incentive_cents"] = dr_settled_cents(
        rec["committed_kw"], rec["performed_kw"], rec["incentive_per_kw_cents"])
    rec["status"] = "SETTLED"
    touch(rec)
    return ok(serialize(rec))


@app.route("/dr-enrollments/<did>/withdraw", methods=["POST"])
def withdraw_dr(did):
    authenticate({"BrokerAgent"})
    rec = must_get(db.dr_enrollments, did)
    if rec["status"] not in ("ENROLLED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", "DR not withdrawable")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok(serialize(rec))


# ---- Reporting & operations ----
@app.route("/reports/commission-summary", methods=["GET"])
def commission_summary():
    authenticate({"BrokerAgent", "BrokerManager", "OpsAdmin"})
    account_id = request.args.get("account_id")
    if account_id:
        must_get(db.accounts, account_id)
    total = 0
    count = 0
    for st in db.commission_statements.values():
        if st["status"] == "VOIDED":
            continue
        contract = db.contracts.get(st["contract_id"])
        if account_id:
            if not contract or contract["account_id"] != account_id:
                continue
        total += st["net_commission_cents"] or 0
        count += 1
    return ok({"total_net_commission_cents": total, "statement_count": count})


@app.route("/operations/record-market-rate", methods=["POST"])
def record_market_rate():
    authenticate({"OpsAdmin"})
    data = get_body()
    commodity = req_enum(data, "commodity", {"ELECTRICITY", "GAS"})
    state_code = req_str(data, "state_code")
    rate_mills = req_int_nonneg(data, "rate_mills")
    db.market_rates[(commodity, state_code)] = rate_mills
    return ok({"commodity": commodity, "state_code": state_code, "rate_mills": rate_mills})


@app.route("/operations/run-scheduled", methods=["POST"])
def run_scheduled():
    authenticate({"OpsAdmin"})
    expired_loas = 0
    expired_contracts = 0
    renewal_windows_opened = 0
    rate_alerts_raised = 0

    # 1. expire SIGNED LOAs past expires_at
    affected_accounts = set()
    for a in db.authorizations.values():
        if a["status"] == "SIGNED" and a["expires_at"] <= db.clock:
            a["status"] = "EXPIRED"
            touch(a)
            expired_loas += 1
            affected_accounts.add(a["account_id"])
    for acc_id in affected_accounts:
        account = db.accounts.get(acc_id)
        if not account or account["status"] not in ("VERIFIED", "ENROLLED"):
            continue
        remaining = any(
            x["account_id"] == acc_id and x["status"] == "SIGNED"
            for x in db.authorizations.values())
        if not remaining:
            suspend_account(account)

    # 2. expire ACTIVE contracts past end_date
    for c in db.contracts.values():
        if c["status"] == "ACTIVE" and db.clock >= c["end_date"]:
            c["status"] = "EXPIRED"
            touch(c)
            expired_contracts += 1

    # 3. renewal windows + 4. rate alerts on still-ACTIVE contracts
    for c in db.contracts.values():
        if c["status"] != "ACTIVE":
            continue
        changed = False
        if not c["renewal_window_open"]:
            if (c["end_date"] - db.clock) <= timedelta(days=RENEWAL_WINDOW_DAYS):
                c["renewal_window_open"] = True
                renewal_windows_opened += 1
                changed = True
        account = db.accounts.get(c["account_id"])
        if account:
            mr = db.market_rates.get((account["commodity"], account["state_code"]))
            if mr is not None:
                c["latest_market_rate_mills"] = mr
        if c["rate_alert"] != "RATE_DROP" and c["latest_market_rate_mills"] is not None:
            threshold = rhu(Decimal(c["rate_mills_per_kwh"]) * RATE_ALERT_FACTOR)
            if c["latest_market_rate_mills"] < threshold:
                c["rate_alert"] = "RATE_DROP"
                rate_alerts_raised += 1
                changed = True
        if changed:
            touch(c)

    return ok({
        "expired_loas": expired_loas,
        "expired_contracts": expired_contracts,
        "renewal_windows_opened": renewal_windows_opened,
        "rate_alerts_raised": rate_alerts_raised,
    })


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"OpsAdmin"})
    data = get_body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        raise ApiError("ERR_VALIDATION", "to_iso8601 is required")
    db.clock = parse_dt(data["to_iso8601"])
    return ok({"current_utc": iso_z(db.clock)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
