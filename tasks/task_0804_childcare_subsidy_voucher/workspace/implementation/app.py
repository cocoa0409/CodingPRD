import os
import random
import string
import uuid
import calendar
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_ROLES = {"Family", "Provider", "CaseWorker", "ProgramAdmin"}

MIN_WEEKLY_ACTIVITY_HOURS = 20
REDETERMINATION_MONTHS = 12
MAX_PAID_ABSENCE_DAYS = 5
COPAY_BANDS = [
    (Decimal("0.50"), 2),
    (Decimal("0.75"), 5),
    (Decimal("1.00"), 8),
    (Decimal("1.25"), 10),
]

CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

ACTIVITY_TYPES = {"WORK", "EDUCATION", "JOB_SEARCH"}
DET_TYPES = {"INITIAL", "REDETERMINATION"}
PROVIDER_TYPES = {"CENTER", "FAMILY_HOME"}
CARE_LEVELS = {"INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"}
LICENSE_ACTIONS = {"VERIFY", "REJECT", "REVOKE", "RENEW"}

# ---------------------------------------------------------------------------
# In-memory store (reset on every process boot; NO seeding)
# ---------------------------------------------------------------------------
LOCK = threading.RLock()

families = {}
parent_activities = {}
income_standards = {}
determinations = {}
providers = {}
rate_ceilings = {}
authorizations = {}
attendance = {}
payments = {}
claims = {}

_seq_counter = 0
CLOCK = None  # datetime


def reset_state():
    global _seq_counter, CLOCK
    families.clear()
    parent_activities.clear()
    income_standards.clear()
    determinations.clear()
    providers.clear()
    rate_ceilings.clear()
    authorizations.clear()
    attendance.clear()
    payments.clear()
    claims.clear()
    _seq_counter = 0
    CLOCK = parse_dt(CLOCK_DEFAULT)


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


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
# Time helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc) if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    mo = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, mo)[1])
    return dt.replace(year=y, month=mo, day=d)


def round_half_up(numerator, denominator):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}


def respond(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized user context")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        return {}
    return b


def _missing(key):
    raise ApiError("ERR_VALIDATION", 400, f"Missing or invalid field: {key}")


def get_str(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    v = body[key]
    if not isinstance(v, str) or v == "":
        _missing(key)
    return v


def get_int(body, key, required=True, default=None, min_val=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        _missing(key)
    if min_val is not None and v < min_val:
        _missing(key)
    return v


def get_enum(body, key, choices, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    v = body[key]
    if not isinstance(v, str) or v not in choices:
        _missing(key)
    return v


def get_datetime(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    v = body[key]
    try:
        parse_dt(v)
    except Exception:
        _missing(key)
    return v


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid limit")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid offset")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return page, pag


def sorted_by_seq(items):
    return sorted(items, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_full():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def base_light():
    return {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def must_get(store, key):
    if key not in store:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return store[key]


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cascade_suspend_reject_attendance(auth_id):
    for r in attendance.values():
        if r["authorization_id"] == auth_id and r["status"] == "SUBMITTED":
            r["status"] = "REJECTED"
            touch(r)


def cascade_provider_revoke(provider_id):
    for a in authorizations.values():
        if a["provider_id"] == provider_id and a["status"] == "ACTIVE":
            a["status"] = "SUSPENDED"
            touch(a)
            cascade_suspend_reject_attendance(a["id"])


def cascade_determination_denied(det_id):
    for a in authorizations.values():
        if a["determination_id"] == det_id and a["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            a["status"] = "TERMINATED"
            touch(a)


def expiry_sweep():
    for p in providers.values():
        if p["license_status"] == "LICENSED" and parse_dt(p["license_expiry_date"]) < CLOCK:
            p["license_status"] = "EXPIRED"
            touch(p)
    for a in authorizations.values():
        if a["status"] == "ACTIVE" and parse_dt(a["end_date"]) < CLOCK:
            a["status"] = "EXPIRED"
            touch(a)
    for d in determinations.values():
        if d["status"] == "APPROVED" and d.get("redetermination_due_date") and parse_dt(d["redetermination_due_date"]) < CLOCK:
            d["status"] = "EXPIRED"
            touch(d)


# ===========================================================================
# FAMILY
# ===========================================================================
@app.route("/ccdf/families", methods=["POST"])
def create_family():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        body = get_body()
        applicant_name = get_str(body, "applicant_name")
        household_size = get_int(body, "household_size", min_val=1)
        gross = get_int(body, "monthly_gross_income_cents", min_val=0)
        self_emp = get_int(body, "monthly_self_employment_income_cents", required=False, default=0, min_val=0)
        state_code = get_str(body, "state_code")
        rec = base_full()
        rec.update({
            "applicant_name": applicant_name,
            "household_size": household_size,
            "monthly_gross_income_cents": gross,
            "monthly_self_employment_income_cents": self_emp,
            "state_code": state_code,
            "status": "PENDING",
            "active_authorization_id": None,
            "total_copay_charged_cents": 0,
        })
        families[rec["id"]] = rec
        return respond(serialize(rec), status=201)


@app.route("/ccdf/families/<fid>", methods=["GET"])
def get_family(fid):
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Family", "CaseWorker", "ProgramAdmin"})
        rec = must_get(families, fid)
        if role == "Family" and rec["id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner")
        return respond(serialize(rec))


# ===========================================================================
# PARENT ACTIVITY
# ===========================================================================
@app.route("/ccdf/parent-activities", methods=["POST"])
def create_parent_activity():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        body = get_body()
        family_id = get_str(body, "family_id")
        activity_type = get_enum(body, "activity_type", ACTIVITY_TYPES)
        weekly_hours = get_int(body, "weekly_hours", min_val=0)
        must_get(families, family_id)
        rec = base_light()
        rec.update({
            "family_id": family_id,
            "activity_type": activity_type,
            "weekly_hours": weekly_hours,
        })
        parent_activities[rec["id"]] = rec
        return respond(serialize(rec), status=201)


@app.route("/ccdf/parent-activities/<pid>", methods=["GET"])
def get_parent_activity(pid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker", "ProgramAdmin"})
        rec = must_get(parent_activities, pid)
        return respond(serialize(rec))


@app.route("/ccdf/parent-activities", methods=["GET"])
def list_parent_activities():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker", "ProgramAdmin"})
        items = list(parent_activities.values())
        family_id = request.args.get("family_id")
        if family_id is not None:
            items = [r for r in items if r["family_id"] == family_id]
        items = sorted_by_seq(items)
        page, pag = paginate(items)
        return respond([serialize(r) for r in page], response_type="array", pagination=pag)


# ===========================================================================
# INCOME STANDARD
# ===========================================================================
@app.route("/ccdf/income-standards", methods=["POST"])
def create_income_standard():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        body = get_body()
        household_size = get_int(body, "household_size", min_val=1)
        entry = get_int(body, "entry_monthly_limit_cents", min_val=0)
        exit_ = get_int(body, "exit_monthly_limit_cents", min_val=0)
        state_code = get_str(body, "state_code")
        rec = base_light()
        rec.update({
            "household_size": household_size,
            "entry_monthly_limit_cents": entry,
            "exit_monthly_limit_cents": exit_,
            "state_code": state_code,
        })
        income_standards[rec["id"]] = rec
        return respond(serialize(rec), status=201)


def find_income_standard(household_size, state_code):
    matches = [r for r in income_standards.values()
               if r["household_size"] == household_size and r["state_code"] == state_code]
    if not matches:
        return None
    return sorted_by_seq(matches)[-1]


# ===========================================================================
# ELIGIBILITY DETERMINATION
# ===========================================================================
@app.route("/ccdf/determinations", methods=["POST"])
def create_determination():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        body = get_body()
        family_id = get_str(body, "family_id")
        det_type = get_enum(body, "determination_type", DET_TYPES)
        must_get(families, family_id)
        rec = base_full()
        rec.update({
            "family_id": family_id,
            "determination_type": det_type,
            "countable_income_cents": 0,
            "income_eligible": False,
            "activity_eligible": False,
            "result": None,
            "monthly_copay_cents": 0,
            "effective_date": None,
            "redetermination_due_date": None,
            "status": "PENDING",
        })
        determinations[rec["id"]] = rec
        return respond(serialize(rec), status=201)


@app.route("/ccdf/determinations/<did>/finalize", methods=["POST"])
def finalize_determination(did):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        det = must_get(determinations, did)
        if det["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Determination not PENDING")
        family = families[det["family_id"]]
        standard = find_income_standard(family["household_size"], family["state_code"])
        if standard is None:
            raise ApiError("ERR_NO_INCOME_STANDARD", 422, "No income standard for household")

        if det["determination_type"] == "INITIAL":
            countable = family["monthly_gross_income_cents"]
            limit = standard["entry_monthly_limit_cents"]
        else:
            countable = family["monthly_gross_income_cents"] + family["monthly_self_employment_income_cents"]
            limit = standard["exit_monthly_limit_cents"]

        income_eligible = countable <= limit
        total_hours = sum(a["weekly_hours"] for a in parent_activities.values()
                          if a["family_id"] == family["id"])
        activity_eligible = total_hours >= MIN_WEEKLY_ACTIVITY_HOURS

        det["countable_income_cents"] = countable
        det["income_eligible"] = income_eligible
        det["activity_eligible"] = activity_eligible

        if not (income_eligible and activity_eligible):
            det["result"] = "DENIED"
            det["monthly_copay_cents"] = 0
            det["status"] = "DENIED"
            touch(det)
            family["status"] = "INELIGIBLE"
            touch(family)
            cascade_determination_denied(det["id"])
            return respond(serialize(det))

        # Approved: compute sliding-fee copay, keyed on ratio vs ENTRY limit
        entry_limit = standard["entry_monthly_limit_cents"]
        ratio = Decimal(countable) / Decimal(entry_limit) if entry_limit > 0 else Decimal("999")
        pct = None
        for max_ratio, band_pct in COPAY_BANDS:
            if ratio <= max_ratio:
                pct = band_pct
                break
        if pct is None:
            pct = COPAY_BANDS[-1][1]
        monthly_copay = round_half_up(countable * pct, 100)

        det["result"] = "APPROVED"
        det["monthly_copay_cents"] = monthly_copay
        det["status"] = "APPROVED"
        det["effective_date"] = fmt_dt(CLOCK)
        det["redetermination_due_date"] = fmt_dt(add_months(CLOCK, REDETERMINATION_MONTHS))
        touch(det)
        family["status"] = "ELIGIBLE"
        touch(family)
        return respond(serialize(det))


@app.route("/ccdf/determinations/<did>", methods=["GET"])
def get_determination(did):
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Family", "CaseWorker", "ProgramAdmin"})
        rec = must_get(determinations, did)
        if role == "Family" and rec["family_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner")
        return respond(serialize(rec))


@app.route("/ccdf/determinations", methods=["GET"])
def list_determinations():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker", "ProgramAdmin"})
        items = list(determinations.values())
        family_id = request.args.get("family_id")
        if family_id is not None:
            items = [r for r in items if r["family_id"] == family_id]
        items = sorted_by_seq(items)
        page, pag = paginate(items)
        return respond([serialize(r) for r in page], response_type="array", pagination=pag)


# ===========================================================================
# PROVIDER
# ===========================================================================
@app.route("/ccdf/providers", methods=["POST"])
def create_provider():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        body = get_body()
        name = get_str(body, "name")
        provider_type = get_enum(body, "provider_type", PROVIDER_TYPES)
        rate = get_int(body, "published_daily_rate_cents", min_val=0)
        license_expiry = get_datetime(body, "license_expiry_date")
        state_code = get_str(body, "state_code")
        rec = base_full()
        rec.update({
            "name": name,
            "provider_type": provider_type,
            "published_daily_rate_cents": rate,
            "license_expiry_date": license_expiry,
            "license_status": "PENDING_VERIFICATION",
            "state_code": state_code,
            "total_net_paid_cents": 0,
        })
        providers[rec["id"]] = rec
        return respond(serialize(rec), status=201)


@app.route("/ccdf/providers/<pid>/license", methods=["POST"])
def provider_license(pid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        body = get_body()
        action = get_enum(body, "action", LICENSE_ACTIONS)
        prov = must_get(providers, pid)

        if action == "VERIFY":
            if prov["license_status"] != "PENDING_VERIFICATION":
                raise ApiError("ERR_INVALID_STATE", 409, "Provider not PENDING_VERIFICATION")
            if parse_dt(prov["license_expiry_date"]) > CLOCK:
                prov["license_status"] = "LICENSED"
            else:
                raise ApiError("ERR_INVALID_STATE", 409, "License already lapsed")
        elif action == "REJECT":
            if prov["license_status"] != "PENDING_VERIFICATION":
                raise ApiError("ERR_INVALID_STATE", 409, "Provider not PENDING_VERIFICATION")
            prov["license_status"] = "REJECTED"
        elif action == "REVOKE":
            if prov["license_status"] != "LICENSED":
                raise ApiError("ERR_INVALID_STATE", 409, "Provider not LICENSED")
            prov["license_status"] = "REVOKED"
            touch(prov)
            cascade_provider_revoke(prov["id"])
            return respond(serialize(prov))
        elif action == "RENEW":
            if prov["license_status"] != "EXPIRED":
                raise ApiError("ERR_INVALID_STATE", 409, "Provider not EXPIRED")
            new_expiry = get_datetime(body, "license_expiry_date")
            if parse_dt(new_expiry) > CLOCK:
                prov["license_expiry_date"] = new_expiry
                prov["license_status"] = "LICENSED"
            else:
                raise ApiError("ERR_INVALID_STATE", 409, "Renewal expiry not in the future")

        touch(prov)
        return respond(serialize(prov))


@app.route("/ccdf/providers/<pid>", methods=["GET"])
def get_provider(pid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"Family", "Provider", "CaseWorker", "ProgramAdmin"})
        rec = must_get(providers, pid)
        return respond(serialize(rec))


# ===========================================================================
# RATE CEILING
# ===========================================================================
def rate_ceilings_overlap(a_start, a_end, b_start, b_end):
    # closed intervals: shared endpoint counts as overlap
    return a_start <= b_end and b_start <= a_end


@app.route("/ccdf/rate-ceilings", methods=["POST"])
def create_rate_ceiling():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        body = get_body()
        provider_type = get_enum(body, "provider_type", PROVIDER_TYPES)
        care_level = get_enum(body, "care_level", CARE_LEVELS)
        max_rate = get_int(body, "max_daily_rate_cents", min_val=0)
        eff_start = get_datetime(body, "effective_start")
        eff_end = get_datetime(body, "effective_end")
        state_code = get_str(body, "state_code")

        ns, ne = parse_dt(eff_start), parse_dt(eff_end)
        for existing in rate_ceilings.values():
            if (existing["provider_type"] == provider_type
                    and existing["care_level"] == care_level
                    and existing["state_code"] == state_code):
                es, ee = parse_dt(existing["effective_start"]), parse_dt(existing["effective_end"])
                if rate_ceilings_overlap(ns, ne, es, ee):
                    raise ApiError("ERR_RATE_CEILING_OVERLAP", 409, "Overlapping rate ceiling")

        rec = base_light()
        rec.update({
            "provider_type": provider_type,
            "care_level": care_level,
            "max_daily_rate_cents": max_rate,
            "effective_start": eff_start,
            "effective_end": eff_end,
            "state_code": state_code,
        })
        rate_ceilings[rec["id"]] = rec
        return respond(serialize(rec), status=201)


@app.route("/ccdf/rate-ceilings", methods=["GET"])
def list_rate_ceilings():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker", "ProgramAdmin"})
        items = list(rate_ceilings.values())
        pt = request.args.get("provider_type")
        cl = request.args.get("care_level")
        if pt is not None:
            items = [r for r in items if r["provider_type"] == pt]
        if cl is not None:
            items = [r for r in items if r["care_level"] == cl]
        items = sorted_by_seq(items)
        page, pag = paginate(items)
        return respond([serialize(r) for r in page], response_type="array", pagination=pag)


def select_rate_ceiling(provider_type, care_level, state_code, start_date):
    sd = parse_dt(start_date)
    matches = []
    for r in rate_ceilings.values():
        if (r["provider_type"] == provider_type
                and r["care_level"] == care_level
                and r["state_code"] == state_code):
            es, ee = parse_dt(r["effective_start"]), parse_dt(r["effective_end"])
            if es <= sd <= ee:
                matches.append(r)
    if not matches:
        return None
    matches.sort(key=lambda r: (parse_dt(r["effective_start"]), r["_seq"]))
    return matches[-1]


# ===========================================================================
# AUTHORIZATION
# ===========================================================================
def auth_intervals_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end); adjacency allowed
    return a_start < b_end and b_start < a_end


@app.route("/ccdf/authorizations", methods=["POST"])
def create_authorization():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        body = get_body()
        family_id = get_str(body, "family_id")
        provider_id = get_str(body, "provider_id")
        determination_id = get_str(body, "determination_id")
        child_name = get_str(body, "child_name")
        care_level = get_enum(body, "care_level", CARE_LEVELS)
        start_date = get_datetime(body, "start_date")
        end_date = get_datetime(body, "end_date")
        days_per_month = get_int(body, "authorized_days_per_month", min_val=1)
        expected_version = get_int(body, "expected_family_version", min_val=0)

        # existence, left to right
        family = must_get(families, family_id)
        provider = must_get(providers, provider_id)
        determination = must_get(determinations, determination_id)

        # business: overlap first
        ns, ne = parse_dt(start_date), parse_dt(end_date)
        for existing in authorizations.values():
            if (existing["family_id"] == family_id
                    and existing["child_name"] == child_name
                    and existing["status"] in ("PENDING", "ACTIVE", "SUSPENDED")):
                es, ee = parse_dt(existing["start_date"]), parse_dt(existing["end_date"])
                if auth_intervals_overlap(ns, ne, es, ee):
                    raise ApiError("ERR_AUTHORIZATION_OVERLAP", 409, "Overlapping authorization")

        # rate ceiling coverage
        ceiling = select_rate_ceiling(provider["provider_type"], care_level, provider["state_code"], start_date)
        if ceiling is None:
            raise ApiError("ERR_NO_RATE_CEILING", 422, "No rate ceiling covers start_date")

        # OCC
        if expected_version != family["version"]:
            raise ApiError("ERR_STALE_FAMILY_VERSION", 412, "Stale family version")

        authorized_daily_rate = min(provider["published_daily_rate_cents"], ceiling["max_daily_rate_cents"])
        monthly_copay = determination["monthly_copay_cents"]
        estimated = max(0, authorized_daily_rate * days_per_month - monthly_copay)

        rec = base_full()
        rec.update({
            "family_id": family_id,
            "provider_id": provider_id,
            "determination_id": determination_id,
            "child_name": child_name,
            "care_level": care_level,
            "start_date": start_date,
            "end_date": end_date,
            "authorized_days_per_month": days_per_month,
            "authorized_daily_rate_cents": authorized_daily_rate,
            "monthly_copay_cents": monthly_copay,
            "estimated_monthly_payment_cents": estimated,
            "status": "PENDING",
        })
        authorizations[rec["id"]] = rec

        # supersede prior ACTIVE authorization for same child_name
        for existing in authorizations.values():
            if (existing["id"] != rec["id"]
                    and existing["family_id"] == family_id
                    and existing["child_name"] == child_name
                    and existing["status"] == "ACTIVE"):
                existing["status"] = "TERMINATED"
                touch(existing)

        family["active_authorization_id"] = rec["id"]
        touch(family)

        return respond(serialize(rec), status=201)


@app.route("/ccdf/authorizations/<aid>/activate", methods=["POST"])
def activate_authorization(aid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        auth = must_get(authorizations, aid)
        if auth["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Authorization not PENDING")
        det = determinations[auth["determination_id"]]
        prov = providers[auth["provider_id"]]
        if det["family_id"] != auth["family_id"]:
            raise ApiError("ERR_DETERMINATION_FAMILY_MISMATCH", 409, "Determination family mismatch")
        if prov["license_status"] != "LICENSED":
            raise ApiError("ERR_PROVIDER_NOT_LICENSED", 409, "Provider not licensed")
        if det["status"] != "APPROVED":
            raise ApiError("ERR_DETERMINATION_NOT_APPROVED", 409, "Determination not approved")
        auth["status"] = "ACTIVE"
        touch(auth)
        return respond(serialize(auth))


@app.route("/ccdf/authorizations/<aid>/suspend", methods=["POST"])
def suspend_authorization(aid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker", "ProgramAdmin"})
        auth = must_get(authorizations, aid)
        if auth["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Authorization not ACTIVE")
        auth["status"] = "SUSPENDED"
        touch(auth)
        cascade_suspend_reject_attendance(auth["id"])
        return respond(serialize(auth))


@app.route("/ccdf/authorizations/<aid>/reinstate", methods=["POST"])
def reinstate_authorization(aid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        auth = must_get(authorizations, aid)
        if auth["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", 409, "Authorization not SUSPENDED")
        prov = providers[auth["provider_id"]]
        if prov["license_status"] != "LICENSED":
            raise ApiError("ERR_PROVIDER_NOT_LICENSED", 409, "Provider not licensed")
        auth["status"] = "ACTIVE"
        touch(auth)
        return respond(serialize(auth))


@app.route("/ccdf/authorizations/<aid>/terminate", methods=["POST"])
def terminate_authorization(aid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        auth = must_get(authorizations, aid)
        if auth["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Authorization not ACTIVE or SUSPENDED")
        auth["status"] = "TERMINATED"
        touch(auth)
        return respond(serialize(auth))


@app.route("/ccdf/authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Family", "Provider", "CaseWorker", "ProgramAdmin"})
        auth = must_get(authorizations, aid)
        if role == "Family" and auth["family_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner")
        if role == "Provider" and auth["provider_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner")
        return respond(serialize(auth))


@app.route("/ccdf/authorizations", methods=["GET"])
def list_authorizations():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker", "ProgramAdmin"})
        items = list(authorizations.values())
        for key in ("family_id", "provider_id", "determination_id"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r[key] == val]
        items = sorted_by_seq(items)
        page, pag = paginate(items)
        return respond([serialize(r) for r in page], response_type="array", pagination=pag)


# ===========================================================================
# ATTENDANCE RECORD
# ===========================================================================
def days_in_service_month(service_month):
    parts = service_month.split("-")
    if len(parts) != 2:
        raise ApiError("ERR_VALIDATION", 400, "Invalid service_month")
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "Invalid service_month")
    if not (1 <= month <= 12) or len(parts[0]) != 4:
        raise ApiError("ERR_VALIDATION", 400, "Invalid service_month")
    return calendar.monthrange(year, month)[1]


@app.route("/ccdf/attendance-records", methods=["POST"])
def create_attendance():
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Provider"})
        body = get_body()
        authorization_id = get_str(body, "authorization_id")
        service_month = get_str(body, "service_month")
        # validate service_month format
        days_in_service_month(service_month)
        present_days = get_int(body, "present_days", min_val=0)
        absent_days = get_int(body, "absent_days", min_val=0)

        auth = must_get(authorizations, authorization_id)
        # ownership: provider must own the authorization's provider
        if auth["provider_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner of authorization")

        # duplicate check
        for r in attendance.values():
            if r["authorization_id"] == authorization_id and r["service_month"] == service_month:
                raise ApiError("ERR_DUPLICATE_ATTENDANCE", 409, "Duplicate attendance for month")

        rec = base_full()
        rec.update({
            "authorization_id": authorization_id,
            "service_month": service_month,
            "present_days": present_days,
            "absent_days": absent_days,
            "payable_days": 0,
            "status": "SUBMITTED",
        })
        attendance[rec["id"]] = rec
        return respond(serialize(rec), status=201)


@app.route("/ccdf/attendance-records/<rid>/approve", methods=["POST"])
def approve_attendance(rid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        rec = must_get(attendance, rid)
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Attendance not SUBMITTED")
        auth = authorizations[rec["authorization_id"]]
        if auth["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Authorization not ACTIVE")
        total_days = rec["present_days"] + rec["absent_days"]
        if total_days > days_in_service_month(rec["service_month"]):
            raise ApiError("ERR_INVALID_ATTENDANCE_DAYS", 422, "Attendance days exceed month")

        payable_days = rec["present_days"] + min(rec["absent_days"], MAX_PAID_ABSENCE_DAYS)
        rate = auth["authorized_daily_rate_cents"]
        monthly_copay = auth["monthly_copay_cents"]
        days_per_month = auth["authorized_days_per_month"]

        gross = rate * payable_days
        daily_copay = round_half_up(monthly_copay, days_per_month)
        copay_deducted = daily_copay * payable_days
        net = max(0, gross - copay_deducted)

        rec["payable_days"] = payable_days
        rec["status"] = "APPROVED"
        touch(rec)

        provider = providers[auth["provider_id"]]
        family = families[auth["family_id"]]

        pay = base_full()
        pay.update({
            "attendance_record_id": rec["id"],
            "provider_id": auth["provider_id"],
            "family_id": auth["family_id"],
            "service_month": rec["service_month"],
            "gross_amount_cents": gross,
            "copay_deducted_cents": copay_deducted,
            "net_provider_payment_cents": net,
            "status": "PAID",
        })
        payments[pay["id"]] = pay

        provider["total_net_paid_cents"] += net
        touch(provider)
        family["total_copay_charged_cents"] += copay_deducted
        touch(family)

        return respond(serialize(rec))


@app.route("/ccdf/attendance-records/<rid>/reject", methods=["POST"])
def reject_attendance(rid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"CaseWorker"})
        rec = must_get(attendance, rid)
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Attendance not SUBMITTED")
        rec["status"] = "REJECTED"
        touch(rec)
        return respond(serialize(rec))


@app.route("/ccdf/attendance-records/<rid>/resubmit", methods=["POST"])
def resubmit_attendance(rid):
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Provider"})
        rec = must_get(attendance, rid)
        auth = authorizations[rec["authorization_id"]]
        if auth["provider_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner of authorization")
        if rec["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Attendance not REJECTED")
        if auth["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Authorization not ACTIVE")
        body = get_body()
        present_days = get_int(body, "present_days", required=False, default=None, min_val=0)
        absent_days = get_int(body, "absent_days", required=False, default=None, min_val=0)
        if present_days is not None:
            rec["present_days"] = present_days
        if absent_days is not None:
            rec["absent_days"] = absent_days
        rec["status"] = "SUBMITTED"
        touch(rec)
        return respond(serialize(rec))


@app.route("/ccdf/attendance-records/<rid>", methods=["GET"])
def get_attendance(rid):
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Provider", "CaseWorker", "ProgramAdmin"})
        rec = must_get(attendance, rid)
        if role == "Provider":
            auth = authorizations[rec["authorization_id"]]
            if auth["provider_id"] != uid:
                raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner")
        return respond(serialize(rec))


@app.route("/ccdf/attendance-records", methods=["GET"])
def list_attendance():
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Provider", "CaseWorker", "ProgramAdmin"})
        items = list(attendance.values())
        authorization_id = request.args.get("authorization_id")
        if authorization_id is not None:
            items = [r for r in items if r["authorization_id"] == authorization_id]
        if role == "Provider":
            items = [r for r in items
                     if authorizations[r["authorization_id"]]["provider_id"] == uid]
        items = sorted_by_seq(items)
        page, pag = paginate(items)
        return respond([serialize(r) for r in page], response_type="array", pagination=pag)


# ===========================================================================
# PAYMENT
# ===========================================================================
@app.route("/ccdf/payments/<pid>/reverse", methods=["POST"])
def reverse_payment(pid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        pay = must_get(payments, pid)
        if pay["status"] != "PAID":
            raise ApiError("ERR_INVALID_STATE", 409, "Payment not PAID")
        pay["status"] = "REVERSED"
        touch(pay)

        provider = providers[pay["provider_id"]]
        family = families[pay["family_id"]]
        provider["total_net_paid_cents"] -= pay["net_provider_payment_cents"]
        touch(provider)
        family["total_copay_charged_cents"] -= pay["copay_deducted_cents"]
        touch(family)

        claim = base_full()
        claim.update({
            "provider_id": pay["provider_id"],
            "payment_id": pay["id"],
            "amount_cents": pay["net_provider_payment_cents"],
            "recovered_amount_cents": 0,
            "reason": "PAYMENT_REVERSAL",
            "status": "OPEN",
        })
        claims[claim["id"]] = claim

        return respond(serialize(pay))


@app.route("/ccdf/payments/<pid>", methods=["GET"])
def get_payment(pid):
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Provider", "CaseWorker", "ProgramAdmin"})
        rec = must_get(payments, pid)
        if role == "Provider" and rec["provider_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner")
        return respond(serialize(rec))


@app.route("/ccdf/payments", methods=["GET"])
def list_payments():
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Provider", "CaseWorker", "ProgramAdmin"})
        items = list(payments.values())
        arid = request.args.get("attendance_record_id")
        pfilter = request.args.get("provider_id")
        if arid is not None:
            items = [r for r in items if r["attendance_record_id"] == arid]
        if pfilter is not None:
            items = [r for r in items if r["provider_id"] == pfilter]
        if role == "Provider":
            items = [r for r in items if r["provider_id"] == uid]
        items = sorted_by_seq(items)
        page, pag = paginate(items)
        return respond([serialize(r) for r in page], response_type="array", pagination=pag)


# ===========================================================================
# OVERPAYMENT CLAIM
# ===========================================================================
@app.route("/ccdf/overpayment-claims/<cid>/record-recovery", methods=["POST"])
def record_recovery(cid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        claim = must_get(claims, cid)
        if claim["status"] not in ("OPEN", "RECOVERING"):
            raise ApiError("ERR_INVALID_STATE", 409, "Claim not OPEN or RECOVERING")
        body = get_body()
        amount = get_int(body, "recovered_amount_cents", min_val=0)
        if amount <= 0:
            raise ApiError("ERR_VALIDATION", 400, "recovered_amount_cents must be positive")
        running = claim["recovered_amount_cents"] + amount
        if running > claim["amount_cents"]:
            raise ApiError("ERR_RECOVERY_EXCEEDS_CLAIM", 422, "Recovery exceeds claim amount")
        claim["recovered_amount_cents"] = running
        if running == claim["amount_cents"]:
            claim["status"] = "RECOVERED"
        else:
            claim["status"] = "RECOVERING"
        touch(claim)
        return respond(serialize(claim))


@app.route("/ccdf/overpayment-claims/<cid>/waive", methods=["POST"])
def waive_claim(cid):
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        claim = must_get(claims, cid)
        if claim["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim not OPEN")
        claim["status"] = "WAIVED"
        touch(claim)
        return respond(serialize(claim))


@app.route("/ccdf/overpayment-claims/<cid>", methods=["GET"])
def get_claim(cid):
    with LOCK:
        uid, role = authenticate()
        authorize(role, {"Provider", "ProgramAdmin"})
        rec = must_get(claims, cid)
        if role == "Provider" and rec["provider_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Not owner")
        return respond(serialize(rec))


@app.route("/ccdf/overpayment-claims", methods=["GET"])
def list_claims():
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        items = list(claims.values())
        pfilter = request.args.get("provider_id")
        payfilter = request.args.get("payment_id")
        if pfilter is not None:
            items = [r for r in items if r["provider_id"] == pfilter]
        if payfilter is not None:
            items = [r for r in items if r["payment_id"] == payfilter]
        items = sorted_by_seq(items)
        page, pag = paginate(items)
        return respond([serialize(r) for r in page], response_type="array", pagination=pag)


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/ccdf/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    with LOCK:
        _, role = authenticate()
        authorize(role, {"ProgramAdmin"})
        body = get_body()
        to_iso = get_datetime(body, "to_iso8601")
        CLOCK = parse_dt(to_iso)
        expiry_sweep()
        return respond({})


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
reset_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
