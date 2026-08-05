import os
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


def parse_dt(s):
    """Parse an ISO-8601 string (with optional trailing Z / offset) to aware UTC datetime."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_dt(dt):
    """Render a datetime as ISO-8601 UTC with exactly three fractional digits and Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


_clock = {"now": parse_dt(DEFAULT_CLOCK_ISO)}


def now():
    return _clock["now"]


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "jurisdictions": {},
    "filers": {},
    "filing_periods": {},
    "statements": {},
    "gift_reports": {},
    "recusals": {},
    "penalties": {},
    "complaints": {},
    "investigations": {},
    "training_records": {},
}
_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_rec(extra):
    t = now()
    rec = {
        "id": str(uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"Registrar", "Filer", "EthicsOfficer", "Investigator", "Adjudicator", "Public"}

FILER_CATEGORIES = {"ELECTED", "APPOINTED", "SENIOR_STAFF", "CANDIDATE"}
FILER_STATUSES = {"ACTIVE", "INACTIVE", "SEPARATED"}
STATEMENT_TYPES = {"ANNUAL", "TRANSACTIONAL"}
PERIOD_STATUSES = {"OPEN", "CLOSED"}
REDACTION_LEVELS = {"FULL", "REDACTED"}
GIFT_KINDS = {"GIFT", "TRAVEL"}
SCREEN_DECISIONS = {"SCREENED", "DISMISSED"}
ADJ_DECISIONS = {"SUSTAINED", "NOT_SUSTAINED"}

DELINQUENCY_BLOCK_THRESHOLD_CENTS = 10000
TRAINING_VALIDITY_DAYS = 365
MILEAGE_RATE = Decimal("65.5")
CATEGORY_MULT = {
    "ELECTED": Decimal("2.0"),
    "APPOINTED": Decimal("1.5"),
    "SENIOR_STAFF": Decimal("1.0"),
    "CANDIDATE": Decimal("1.0"),
}


class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": render_dt(now())}


def ok(data, status=200, response_type="object", pagination=None):
    m = _meta()
    if pagination:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    m = _meta()
    body = {"meta": m, "response_type": "error", "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http


@app.errorhandler(404)
def handle_404(e):
    m = _meta()
    body = {"meta": m, "response_type": "error", "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    m = _meta()
    body = {"meta": m, "response_type": "error", "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"}}
    return jsonify(body), 405


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Auth / body helpers
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s not permitted for this operation" % role)
    return uid, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def require(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % f)


def check_enum(value, allowed, field):
    if value is not None and value not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "Illegal value for %s" % field)


def nonneg_int(body, field):
    if field in body and body[field] is not None:
        v = body[field]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ApiError("ERR_VALIDATION", 400, "%s must be a non-negative integer" % field)


def paginate(items):
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_PAGINATION_INVALID", 400, "Invalid pagination parameters")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", 400, "Pagination out of bounds")
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pg = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return page, pg


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def ser(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = render_dt(v)
        else:
            out[k] = v
    return out


def compute_training_status(filer_id):
    completed = [t for t in db["training_records"].values()
                 if t["filer_id"] == filer_id and t["completed_at"] is not None]
    if any(t["expires_at"] is not None and t["expires_at"] > now() for t in completed):
        return "CURRENT"
    if completed:
        return "LAPSED"
    return "NONE"


def ser_filer(f):
    d = ser(f)
    d["training_status"] = compute_training_status(f["id"])
    return d


def compute_training_state(t):
    if t["completed_at"] is None:
        return "ENROLLED"
    if t["expires_at"] is not None and now() >= t["expires_at"]:
        return "EXPIRED"
    return "COMPLETED"


def ser_training(t):
    d = ser(t)
    d["status"] = compute_training_state(t)
    return d


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    rec = db[coll].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


def fk_or_404(coll, rid):
    if rid is None:
        return None
    rec = db[coll].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource not found")
    return rec


def owner_check(uid, filer_id):
    if uid != filer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting filer does not own this resource")


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def provisional_penalty(days_late, jur):
    return jur["penalty_base_fee_cents"] + jur["penalty_daily_rate_cents"] * days_late


def final_penalty(days_late, jur, category):
    base = jur["penalty_base_fee_cents"]
    daily = jur["penalty_daily_rate_cents"]
    cap = jur["penalty_cap_cents"]
    if days_late <= 30:
        tier = daily
    elif days_late <= 90:
        tier = daily * 2
    else:
        tier = daily * 3
    raw = Decimal(base) + Decimal(tier) * Decimal(days_late) * CATEGORY_MULT[category]
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(cap, rounded)


def travel_gross(legs):
    total = 0
    for leg in legs:
        raw = Decimal(leg["nights"]) * Decimal(leg["nightly_rate_cents"]) + Decimal(leg["miles"]) * MILEAGE_RATE
        total += int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


def compute_days_late(submitted_dt, due_dt):
    if submitted_dt <= due_dt:
        return False, 0
    diff = (submitted_dt - due_dt).total_seconds()
    import math
    return True, int(math.ceil(diff / 86400.0))


def recompute_filer_ledger(filer):
    total = sum(p["assessed_amount_cents"] for p in db["penalties"].values()
                if p["filer_id"] == filer["id"] and p["status"] == "ASSESSED")
    filer["outstanding_penalty_cents"] = total
    filer["compliance_status"] = "COMPLIANT" if total <= DELINQUENCY_BLOCK_THRESHOLD_CENTS else "DELINQUENT"


def statements_of_filer(filer_id):
    return [s for s in db["statements"].values() if s["filer_id"] == filer_id]


# ===========================================================================
# Jurisdiction
# ===========================================================================
@app.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    auth({"Registrar"})
    body = get_body()
    require(body, ["name"])
    for f in ["gift_single_limit_cents", "gift_annual_source_limit_cents",
              "penalty_base_fee_cents", "penalty_daily_rate_cents", "penalty_cap_cents"]:
        nonneg_int(body, f)
    rec = new_rec({
        "name": body["name"],
        "gift_single_limit_cents": body.get("gift_single_limit_cents", 5000),
        "gift_annual_source_limit_cents": body.get("gift_annual_source_limit_cents", 25000),
        "penalty_base_fee_cents": body.get("penalty_base_fee_cents", 5000),
        "penalty_daily_rate_cents": body.get("penalty_daily_rate_cents", 250),
        "penalty_cap_cents": body.get("penalty_cap_cents", 50000),
    })
    db["jurisdictions"][rec["id"]] = rec
    return ok(ser(rec), 201)


@app.route("/jurisdictions/<rid>", methods=["GET"])
def get_jurisdiction(rid):
    auth({"Registrar", "EthicsOfficer", "Filer"})
    rec = get_or_404("jurisdictions", rid)
    return ok(ser(rec), 200)


# ===========================================================================
# Filer
# ===========================================================================
@app.route("/filers", methods=["POST"])
def create_filer():
    auth({"Registrar"})
    body = get_body()
    require(body, ["jurisdiction_id", "full_name", "official_title", "filer_category"])
    check_enum(body["filer_category"], FILER_CATEGORIES, "filer_category")
    fk_or_404("jurisdictions", body["jurisdiction_id"])
    rec = new_rec({
        "jurisdiction_id": body["jurisdiction_id"],
        "full_name": body["full_name"],
        "official_title": body["official_title"],
        "filer_category": body["filer_category"],
        "email": body.get("email"),
        "status": "ACTIVE",
        "compliance_status": "COMPLIANT",
        "outstanding_penalty_cents": 0,
        "reportable_gift_total_cents": 0,
        "open_recusal_count": 0,
    })
    db["filers"][rec["id"]] = rec
    return ok(ser_filer(rec), 201)


@app.route("/filers/<rid>", methods=["GET"])
def get_filer(rid):
    auth({"Registrar", "EthicsOfficer", "Filer", "Investigator", "Adjudicator"})
    rec = get_or_404("filers", rid)
    return ok(ser_filer(rec), 200)


@app.route("/filers", methods=["GET"])
def list_filers():
    auth({"Registrar", "EthicsOfficer"})
    items = list(db["filers"].values())
    jid = request.args.get("jurisdiction_id")
    st = request.args.get("status")
    if jid is not None:
        items = [f for f in items if f["jurisdiction_id"] == jid]
    if st is not None:
        items = [f for f in items if f["status"] == st]
    page, pg = paginate(items)
    return ok([ser_filer(f) for f in page], 200, "array", pg)


@app.route("/filers/<rid>/status", methods=["PATCH"])
def patch_filer_status(rid):
    auth({"Registrar"})
    body = get_body()
    require(body, ["status"])
    check_enum(body["status"], FILER_STATUSES, "status")
    rec = get_or_404("filers", rid)
    rec["status"] = body["status"]
    touch(rec)
    return ok(ser_filer(rec), 200)


# ===========================================================================
# FilingPeriod
# ===========================================================================
@app.route("/filing-periods", methods=["POST"])
def create_filing_period():
    auth({"Registrar"})
    body = get_body()
    require(body, ["jurisdiction_id", "statement_type", "coverage_start", "coverage_end", "due_at"])
    check_enum(body["statement_type"], STATEMENT_TYPES, "statement_type")
    check_enum(body.get("status"), PERIOD_STATUSES, "status")
    fk_or_404("jurisdictions", body["jurisdiction_id"])
    try:
        cs = parse_dt(body["coverage_start"])
        ce = parse_dt(body["coverage_end"])
        parse_dt(body["due_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime field")
    # priority 11: closed-interval overlap for same jurisdiction+statement_type
    for p in db["filing_periods"].values():
        if p["jurisdiction_id"] == body["jurisdiction_id"] and p["statement_type"] == body["statement_type"]:
            pcs = parse_dt(p["coverage_start"])
            pce = parse_dt(p["coverage_end"])
            if cs <= pce and pcs <= ce:  # closed overlap (touching conflicts)
                raise ApiError("ERR_PERIOD_OVERLAP", 409, "Coverage interval overlaps an existing period")
    rec = new_rec({
        "jurisdiction_id": body["jurisdiction_id"],
        "label": body.get("label"),
        "statement_type": body["statement_type"],
        "coverage_start": body["coverage_start"],
        "coverage_end": body["coverage_end"],
        "due_at": body["due_at"],
        "status": body.get("status", "OPEN"),
    })
    db["filing_periods"][rec["id"]] = rec
    return ok(ser(rec), 201)


@app.route("/filing-periods/<rid>", methods=["GET"])
def get_filing_period(rid):
    auth({"Registrar", "EthicsOfficer", "Filer"})
    rec = get_or_404("filing_periods", rid)
    return ok(ser(rec), 200)


@app.route("/filing-periods", methods=["GET"])
def list_filing_periods():
    auth({"Registrar", "EthicsOfficer", "Filer"})
    items = list(db["filing_periods"].values())
    jid = request.args.get("jurisdiction_id")
    stype = request.args.get("statement_type")
    if jid is not None:
        items = [p for p in items if p["jurisdiction_id"] == jid]
    if stype is not None:
        items = [p for p in items if p["statement_type"] == stype]
    page, pg = paginate(items)
    return ok([ser(p) for p in page], 200, "array", pg)


# ===========================================================================
# Statement
# ===========================================================================
@app.route("/statements", methods=["POST"])
def create_statement():
    uid, _ = auth({"Filer"})
    body = get_body()
    require(body, ["filer_id", "filing_period_id"])
    check_enum(body.get("redaction_level"), REDACTION_LEVELS, "redaction_level")
    filer = fk_or_404("filers", body["filer_id"])
    period = fk_or_404("filing_periods", body["filing_period_id"])
    if body.get("supersedes_statement_id") is not None:
        fk_or_404("statements", body["supersedes_statement_id"])
    owner_check(uid, filer["id"])
    # priority 12: duplicate (at most one non-SUPERSEDED per filer+period)
    for s in db["statements"].values():
        if s["filer_id"] == filer["id"] and s["filing_period_id"] == period["id"] and s["status"] != "SUPERSEDED":
            raise ApiError("ERR_DUPLICATE_STATEMENT", 409, "A non-superseded statement already exists for this filer and period")
    # priority 17: period must be OPEN
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED", 409, "Filing period is closed")
    rec = new_rec({
        "filer_id": filer["id"],
        "filing_period_id": period["id"],
        "supersedes_statement_id": body.get("supersedes_statement_id"),
        "statement_type": period["statement_type"],
        "content": body.get("content"),
        "status": "DRAFT",
        "submitted_at": None,
        "due_at_snapshot": None,
        "is_late": False,
        "days_late": 0,
        "correction_round": 0,
        "public_status": "NOT_PUBLISHED",
        "published_at": None,
        "redaction_level": body.get("redaction_level", "FULL"),
    })
    db["statements"][rec["id"]] = rec
    return ok(ser(rec), 201)


@app.route("/statements/<rid>", methods=["GET"])
def get_statement(rid):
    auth({"Registrar", "EthicsOfficer", "Filer", "Public"})
    rec = get_or_404("statements", rid)
    return ok(ser(rec), 200)


@app.route("/statements", methods=["GET"])
def list_statements():
    auth({"Registrar", "EthicsOfficer", "Filer", "Public"})
    items = list(db["statements"].values())
    for key in ["filer_id", "filing_period_id", "supersedes_statement_id", "status"]:
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    public = request.args.get("public")
    if public is not None and str(public).lower() == "true":
        items = [s for s in items if s["public_status"] == "PUBLISHED"]
    page, pg = paginate(items)
    return ok([ser(s) for s in page], 200, "array", pg)


@app.route("/statements/<rid>/submit", methods=["POST"])
def submit_statement(rid):
    uid, _ = auth({"Filer"})
    get_body()
    st = get_or_404("statements", rid)
    owner_check(uid, st["filer_id"])
    if st["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError("ERR_INVALID_STATE", 409, "Statement cannot be submitted from its current state")
    initial = st["status"] == "DRAFT"
    filer = db["filers"][st["filer_id"]]
    period = db["filing_periods"][st["filing_period_id"]]
    # filer must be ACTIVE
    if filer["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Filer is not ACTIVE")
    # training must be CURRENT (priority 9)
    if compute_training_status(filer["id"]) != "CURRENT":
        raise ApiError("ERR_TRAINING_NOT_CURRENT", 422, "Filer training is not current")
    if initial:
        # delinquency gate (priority 14)
        if filer["outstanding_penalty_cents"] > DELINQUENCY_BLOCK_THRESHOLD_CENTS:
            raise ApiError("ERR_FILER_DELINQUENT", 402, "Filer outstanding penalties exceed the delinquency threshold")
        # period must be OPEN (priority 17)
        if period["status"] != "OPEN":
            raise ApiError("ERR_PERIOD_CLOSED", 409, "Filing period is closed")

    submitted = now()
    st["submitted_at"] = submitted
    if st["due_at_snapshot"] is None:
        st["due_at_snapshot"] = period["due_at"]
    due_dt = parse_dt(st["due_at_snapshot"])
    is_late, days_late = compute_days_late(submitted, due_dt)
    st["is_late"] = is_late
    st["days_late"] = days_late
    st["status"] = "SUBMITTED"
    touch(st)

    if initial and is_late:
        jur = db["jurisdictions"][filer["jurisdiction_id"]]
        pen = new_rec({
            "filer_id": filer["id"],
            "statement_id": st["id"],
            "investigation_id": None,
            "penalty_type": "LATE_FILING",
            "provisional_amount_cents": provisional_penalty(days_late, jur),
            "assessed_amount_cents": 0,
            "days_late": days_late,
            "status": "ACCRUING",
        })
        db["penalties"][pen["id"]] = pen
    return ok(ser(st), 200)


@app.route("/statements/<rid>/accept", methods=["POST"])
def accept_statement(rid):
    auth({"EthicsOfficer"})
    get_body()
    st = get_or_404("statements", rid)
    if st["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not SUBMITTED")
    st["status"] = "ACCEPTED"
    touch(st)

    filer = db["filers"][st["filer_id"]]
    jur = db["jurisdictions"][filer["jurisdiction_id"]]
    # finalize linked ACCRUING LATE_FILING penalty (cascade)
    linked = [p for p in db["penalties"].values()
              if p["statement_id"] == st["id"] and p["penalty_type"] == "LATE_FILING" and p["status"] == "ACCRUING"]
    if linked:
        pen = linked[0]
        old_compliance = filer["compliance_status"]
        pen["assessed_amount_cents"] = final_penalty(st["days_late"], jur, filer["filer_category"])
        pen["days_late"] = st["days_late"]
        pen["status"] = "ASSESSED"
        touch(pen)
        recompute_filer_ledger(filer)
        touch(filer)
        if old_compliance != "DELINQUENT" and filer["compliance_status"] == "DELINQUENT":
            for s in statements_of_filer(filer["id"]):
                if s["public_status"] == "PUBLISHED":
                    s["public_status"] = "WITHHELD"
                    touch(s)

    # amendment cascade: supersede the prior accepted statement
    if st.get("supersedes_statement_id"):
        prior = db["statements"].get(st["supersedes_statement_id"])
        if prior is not None and prior["status"] == "ACCEPTED":
            prior["status"] = "SUPERSEDED"
            prior["public_status"] = "NOT_PUBLISHED"
            touch(prior)
    return ok(ser(st), 200)


@app.route("/statements/<rid>/return", methods=["POST"])
def return_statement(rid):
    auth({"EthicsOfficer"})
    get_body()
    st = get_or_404("statements", rid)
    if st["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not SUBMITTED")
    st["status"] = "RETURNED_FOR_CORRECTION"
    st["correction_round"] += 1
    touch(st)
    return ok(ser(st), 200)


@app.route("/statements/<rid>/publish", methods=["POST"])
def publish_statement(rid):
    auth({"Registrar"})
    body = get_body()
    require(body, ["expected_statement_version"])
    if isinstance(body["expected_statement_version"], bool) or not isinstance(body["expected_statement_version"], int):
        raise ApiError("ERR_VALIDATION", 400, "expected_statement_version must be an integer")
    check_enum(body.get("redaction_level"), REDACTION_LEVELS, "redaction_level")
    st = get_or_404("statements", rid)
    if st["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not ACCEPTED")
    if body["expected_statement_version"] != st["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Statement version has advanced since it was last read")
    if body.get("redaction_level") is not None:
        st["redaction_level"] = body["redaction_level"]
    st["public_status"] = "PUBLISHED"
    st["published_at"] = now()
    touch(st)
    return ok(ser(st), 200)


# ===========================================================================
# GiftReport
# ===========================================================================
@app.route("/gift-reports", methods=["POST"])
def create_gift_report():
    uid, _ = auth({"Filer"})
    body = get_body()
    require(body, ["filer_id", "source_name", "gift_kind", "received_at"])
    check_enum(body["gift_kind"], GIFT_KINDS, "gift_kind")
    nonneg_int(body, "fair_market_value_cents")
    nonneg_int(body, "consideration_paid_cents")
    legs = body.get("travel_legs", [])
    if legs is not None and not isinstance(legs, list):
        raise ApiError("ERR_VALIDATION", 400, "travel_legs must be an array")
    if legs:
        for leg in legs:
            if not isinstance(leg, dict):
                raise ApiError("ERR_VALIDATION", 400, "each travel leg must be an object")
            for lf in ["nights", "nightly_rate_cents", "miles"]:
                v = leg.get(lf)
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise ApiError("ERR_VALIDATION", 400, "travel leg %s must be a non-negative integer" % lf)
    try:
        parse_dt(body["received_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid received_at")
    filer = fk_or_404("filers", body["filer_id"])
    owner_check(uid, filer["id"])
    # filer must be ACTIVE
    if filer["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Filer is not ACTIVE")
    # training current (priority 9)
    if compute_training_status(filer["id"]) != "CURRENT":
        raise ApiError("ERR_TRAINING_NOT_CURRENT", 422, "Filer training is not current")
    # payload shape (priority 18)
    kind = body["gift_kind"]
    if kind == "GIFT":
        if not body.get("fair_market_value_cents"):
            raise ApiError("ERR_INVALID_GIFT_KIND_PAYLOAD", 400, "GIFT requires a positive fair_market_value_cents")
    else:  # TRAVEL
        if not legs:
            raise ApiError("ERR_INVALID_GIFT_KIND_PAYLOAD", 400, "TRAVEL requires a non-empty travel_legs array")

    consideration = body.get("consideration_paid_cents", 0)
    if kind == "GIFT":
        gross = body.get("fair_market_value_cents", 0)
    else:
        gross = travel_gross(legs)
    reportable = max(0, gross - consideration)

    jur = db["jurisdictions"][filer["jurisdiction_id"]]
    # single-gift limit (priority 13)
    if reportable > jur["gift_single_limit_cents"]:
        raise ApiError("ERR_GIFT_LIMIT_EXCEEDED", 422, "Single-gift reportable value exceeds the limit")
    # annual per-source aggregate (priority 15)
    year = parse_dt(body["received_at"]).year
    existing = sum(g["reportable_value_cents"] for g in db["gift_reports"].values()
                   if g["filer_id"] == filer["id"]
                   and g["source_name"] == body["source_name"]
                   and g["status"] != "DISPOSED"
                   and parse_dt(g["received_at"]).year == year)
    if existing + reportable > jur["gift_annual_source_limit_cents"]:
        raise ApiError("ERR_GIFT_ANNUAL_LIMIT_EXCEEDED", 422, "Annual per-source gift aggregate exceeds the limit")

    rec = new_rec({
        "filer_id": filer["id"],
        "source_name": body["source_name"],
        "gift_kind": kind,
        "fair_market_value_cents": body.get("fair_market_value_cents", 0),
        "consideration_paid_cents": consideration,
        "travel_legs": legs if legs else [],
        "received_at": body["received_at"],
        "reportable_value_cents": reportable,
        "disclosed_gross_cents": gross,
        "status": "REPORTED",
    })
    db["gift_reports"][rec["id"]] = rec
    filer["reportable_gift_total_cents"] += reportable
    touch(filer)
    return ok(ser(rec), 201)


@app.route("/gift-reports/<rid>", methods=["GET"])
def get_gift_report(rid):
    auth({"Registrar", "EthicsOfficer", "Filer", "Public"})
    rec = get_or_404("gift_reports", rid)
    return ok(ser(rec), 200)


@app.route("/gift-reports", methods=["GET"])
def list_gift_reports():
    auth({"Registrar", "EthicsOfficer", "Filer", "Public"})
    items = list(db["gift_reports"].values())
    for key in ["filer_id", "status"]:
        val = request.args.get(key)
        if val is not None:
            items = [g for g in items if g.get(key) == val]
    page, pg = paginate(items)
    return ok([ser(g) for g in page], 200, "array", pg)


@app.route("/gift-reports/<rid>/dispose", methods=["POST"])
def dispose_gift_report(rid):
    uid, _ = auth({"Filer"})
    get_body()
    rec = get_or_404("gift_reports", rid)
    owner_check(uid, rec["filer_id"])
    if rec["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Gift report is not REPORTED")
    rec["status"] = "DISPOSED"
    touch(rec)
    filer = db["filers"][rec["filer_id"]]
    filer["reportable_gift_total_cents"] -= rec["reportable_value_cents"]
    touch(filer)
    return ok(ser(rec), 200)


# ===========================================================================
# RecusalEntry
# ===========================================================================
@app.route("/recusals", methods=["POST"])
def create_recusal():
    uid, _ = auth({"Filer"})
    body = get_body()
    require(body, ["filer_id", "matter_id", "effective_start", "effective_end"])
    try:
        es = parse_dt(body["effective_start"])
        ee = parse_dt(body["effective_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid recusal interval")
    filer = fk_or_404("filers", body["filer_id"])
    owner_check(uid, filer["id"])
    # priority 10: half-open overlap with existing DECLARED recusal same (filer, matter)
    for r in db["recusals"].values():
        if r["filer_id"] == filer["id"] and r["matter_id"] == body["matter_id"] and r["status"] == "DECLARED":
            rs = parse_dt(r["effective_start"])
            re = parse_dt(r["effective_end"])
            if es < re and rs < ee:  # half-open overlap
                raise ApiError("ERR_RECUSAL_OVERLAP", 409, "Recusal interval overlaps an existing declared recusal")
    rec = new_rec({
        "filer_id": filer["id"],
        "matter_id": body["matter_id"],
        "matter_description": body.get("matter_description"),
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "reason": body.get("reason"),
        "status": "DECLARED",
    })
    db["recusals"][rec["id"]] = rec
    filer["open_recusal_count"] += 1
    touch(filer)
    return ok(ser(rec), 201)


@app.route("/recusals/<rid>", methods=["GET"])
def get_recusal(rid):
    auth({"Registrar", "EthicsOfficer", "Filer", "Public"})
    rec = get_or_404("recusals", rid)
    return ok(ser(rec), 200)


@app.route("/recusals", methods=["GET"])
def list_recusals():
    auth({"Registrar", "EthicsOfficer", "Filer", "Public"})
    items = list(db["recusals"].values())
    for key in ["filer_id", "matter_id", "status"]:
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, pg = paginate(items)
    return ok([ser(r) for r in page], 200, "array", pg)


@app.route("/recusals/<rid>/resolve", methods=["POST"])
def resolve_recusal(rid):
    uid, _ = auth({"Filer"})
    get_body()
    rec = get_or_404("recusals", rid)
    owner_check(uid, rec["filer_id"])
    if rec["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE", 409, "Recusal is not DECLARED")
    rec["status"] = "RESOLVED"
    touch(rec)
    filer = db["filers"][rec["filer_id"]]
    filer["open_recusal_count"] -= 1
    touch(filer)
    return ok(ser(rec), 200)


# ===========================================================================
# Penalty
# ===========================================================================
@app.route("/penalties/<rid>", methods=["GET"])
def get_penalty(rid):
    auth({"Registrar", "EthicsOfficer", "Filer"})
    rec = get_or_404("penalties", rid)
    return ok(ser(rec), 200)


@app.route("/penalties", methods=["GET"])
def list_penalties():
    auth({"Registrar", "EthicsOfficer", "Filer"})
    items = list(db["penalties"].values())
    for key in ["filer_id", "statement_id", "investigation_id", "status", "penalty_type"]:
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, pg = paginate(items)
    return ok([ser(p) for p in page], 200, "array", pg)


@app.route("/penalties/<rid>/pay", methods=["POST"])
def pay_penalty(rid):
    uid, _ = auth({"Filer"})
    get_body()
    pen = get_or_404("penalties", rid)
    owner_check(uid, pen["filer_id"])
    if pen["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Penalty is not ASSESSED")
    filer = db["filers"][pen["filer_id"]]
    old_compliance = filer["compliance_status"]
    pen["status"] = "PAID"
    touch(pen)
    recompute_filer_ledger(filer)
    touch(filer)
    if old_compliance == "DELINQUENT" and filer["compliance_status"] == "COMPLIANT":
        for s in statements_of_filer(filer["id"]):
            if s["public_status"] == "WITHHELD":
                s["public_status"] = "PUBLISHED"
                touch(s)
    return ok(ser(pen), 200)


@app.route("/penalties/<rid>/waive", methods=["POST"])
def waive_penalty(rid):
    auth({"EthicsOfficer"})
    get_body()
    pen = get_or_404("penalties", rid)
    if pen["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Penalty is not ASSESSED")
    filer = db["filers"][pen["filer_id"]]
    pen["status"] = "WAIVED"
    touch(pen)
    recompute_filer_ledger(filer)
    touch(filer)
    return ok(ser(pen), 200)


# ===========================================================================
# Complaint
# ===========================================================================
@app.route("/complaints", methods=["POST"])
def create_complaint():
    auth({"EthicsOfficer", "Public"})
    body = get_body()
    require(body, ["filer_id", "allegation"])
    fk_or_404("filers", body["filer_id"])
    if body.get("statement_id") is not None:
        fk_or_404("statements", body["statement_id"])
    rec = new_rec({
        "filer_id": body["filer_id"],
        "statement_id": body.get("statement_id"),
        "complainant_ref": body.get("complainant_ref"),
        "allegation": body["allegation"],
        "status": "FILED",
    })
    db["complaints"][rec["id"]] = rec
    return ok(ser(rec), 201)


@app.route("/complaints/<rid>", methods=["GET"])
def get_complaint(rid):
    auth({"Registrar", "EthicsOfficer", "Investigator", "Adjudicator"})
    rec = get_or_404("complaints", rid)
    return ok(ser(rec), 200)


@app.route("/complaints", methods=["GET"])
def list_complaints():
    auth({"Registrar", "EthicsOfficer", "Investigator", "Adjudicator"})
    items = list(db["complaints"].values())
    for key in ["filer_id", "statement_id", "status"]:
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, pg = paginate(items)
    return ok([ser(c) for c in page], 200, "array", pg)


@app.route("/complaints/<rid>/screen", methods=["POST"])
def screen_complaint(rid):
    auth({"EthicsOfficer"})
    body = get_body()
    require(body, ["decision"])
    check_enum(body["decision"], SCREEN_DECISIONS, "decision")
    rec = get_or_404("complaints", rid)
    if rec["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint is not FILED")
    rec["status"] = body["decision"]  # SCREENED or DISMISSED
    touch(rec)
    return ok(ser(rec), 200)


# ===========================================================================
# Investigation
# ===========================================================================
@app.route("/complaints/<cid>/investigations", methods=["POST"])
def open_investigation(cid):
    uid, _ = auth({"Investigator"})
    get_body()
    complaint = get_or_404("complaints", cid)
    if complaint["status"] != "SCREENED":
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint is not SCREENED")
    rec = new_rec({
        "complaint_id": complaint["id"],
        "filer_id": complaint["filer_id"],
        "assigned_investigator_id": uid,
        "adjudicator_id": None,
        "findings": None,
        "recommended_sanction_cents": 0,
        "final_sanction_cents": 0,
        "status": "OPEN",
    })
    db["investigations"][rec["id"]] = rec
    return ok(ser(rec), 201)


@app.route("/investigations/<rid>", methods=["GET"])
def get_investigation(rid):
    auth({"Registrar", "EthicsOfficer", "Investigator", "Adjudicator"})
    rec = get_or_404("investigations", rid)
    return ok(ser(rec), 200)


@app.route("/investigations", methods=["GET"])
def list_investigations():
    auth({"Registrar", "EthicsOfficer", "Investigator", "Adjudicator"})
    items = list(db["investigations"].values())
    for key in ["complaint_id", "filer_id", "status"]:
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    page, pg = paginate(items)
    return ok([ser(i) for i in page], 200, "array", pg)


@app.route("/investigations/<rid>/adjudicate", methods=["POST"])
def adjudicate_investigation(rid):
    uid, _ = auth({"Adjudicator"})
    body = get_body()
    require(body, ["decision"])
    check_enum(body["decision"], ADJ_DECISIONS, "decision")
    nonneg_int(body, "recommended_sanction_cents")
    inv = get_or_404("investigations", rid)
    if inv["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Investigation is not OPEN")
    complaint = db["complaints"][inv["complaint_id"]]
    if complaint["status"] != "SCREENED":
        raise ApiError("ERR_INVALID_STATE", 409, "Parent complaint is not SCREENED")
    # SoD (priority 8)
    if uid == inv["assigned_investigator_id"]:
        raise ApiError("ERR_SOD_CONFLICT", 409, "Adjudicator must differ from the assigned investigator")

    inv["adjudicator_id"] = uid
    if body.get("findings") is not None:
        inv["findings"] = body["findings"]
    recommended = body.get("recommended_sanction_cents", 0)
    inv["recommended_sanction_cents"] = recommended

    if body["decision"] == "SUSTAINED":
        filer = db["filers"][inv["filer_id"]]
        jur = db["jurisdictions"][filer["jurisdiction_id"]]
        final_sanction = min(jur["penalty_cap_cents"], recommended)
        inv["final_sanction_cents"] = final_sanction
        inv["status"] = "SUSTAINED"
        touch(inv)
        # complaint SCREENED -> SUBSTANTIATED
        complaint["status"] = "SUBSTANTIATED"
        touch(complaint)
        # flag subject statement if present
        if complaint.get("statement_id"):
            subj = db["statements"].get(complaint["statement_id"])
            if subj is not None and subj["status"] == "ACCEPTED":
                subj["status"] = "FLAGGED"
                if subj["public_status"] == "PUBLISHED":
                    subj["public_status"] = "WITHHELD"
                touch(subj)
        # create SANCTION penalty already ASSESSED
        pen = new_rec({
            "filer_id": filer["id"],
            "statement_id": None,
            "investigation_id": inv["id"],
            "penalty_type": "SANCTION",
            "provisional_amount_cents": 0,
            "assessed_amount_cents": final_sanction,
            "days_late": 0,
            "status": "ASSESSED",
        })
        db["penalties"][pen["id"]] = pen
        recompute_filer_ledger(filer)
        touch(filer)
    else:  # NOT_SUSTAINED
        inv["status"] = "NOT_SUSTAINED"
        touch(inv)
        complaint["status"] = "DISMISSED"
        touch(complaint)
    return ok(ser(inv), 200)


@app.route("/investigations/<rid>/reopen", methods=["POST"])
def reopen_investigation(rid):
    auth({"EthicsOfficer"})
    get_body()
    inv = get_or_404("investigations", rid)
    if inv["status"] != "NOT_SUSTAINED":
        raise ApiError("ERR_INVALID_STATE", 409, "Investigation is not NOT_SUSTAINED")
    inv["status"] = "OPEN"
    touch(inv)
    complaint = db["complaints"].get(inv["complaint_id"])
    if complaint is not None and complaint["status"] == "DISMISSED":
        complaint["status"] = "SCREENED"
        touch(complaint)
    return ok(ser(inv), 200)


# ===========================================================================
# TrainingRecord
# ===========================================================================
@app.route("/training-records", methods=["POST"])
def create_training_record():
    uid, _ = auth({"Filer"})
    body = get_body()
    require(body, ["filer_id", "course_code"])
    filer = fk_or_404("filers", body["filer_id"])
    owner_check(uid, filer["id"])
    rec = new_rec({
        "filer_id": filer["id"],
        "course_code": body["course_code"],
        "enrolled_at": now(),
        "completed_at": None,
        "expires_at": None,
        "certificate_no": None,
    })
    db["training_records"][rec["id"]] = rec
    return ok(ser_training(rec), 201)


@app.route("/training-records/<rid>", methods=["GET"])
def get_training_record(rid):
    auth({"Registrar", "EthicsOfficer", "Filer"})
    rec = get_or_404("training_records", rid)
    return ok(ser_training(rec), 200)


@app.route("/training-records", methods=["GET"])
def list_training_records():
    auth({"Registrar", "EthicsOfficer", "Filer"})
    items = list(db["training_records"].values())
    fid = request.args.get("filer_id")
    st = request.args.get("status")
    if fid is not None:
        items = [t for t in items if t["filer_id"] == fid]
    if st is not None:
        items = [t for t in items if compute_training_state(t) == st]
    page, pg = paginate(items)
    return ok([ser_training(t) for t in page], 200, "array", pg)


@app.route("/training-records/<rid>/complete", methods=["POST"])
def complete_training_record(rid):
    uid, _ = auth({"Filer"})
    get_body()
    rec = get_or_404("training_records", rid)
    owner_check(uid, rec["filer_id"])
    if compute_training_state(rec) != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Training record is not ENROLLED")
    completed = now()
    rec["completed_at"] = completed
    rec["expires_at"] = completed + timedelta(days=TRAINING_VALIDITY_DAYS)
    rec["certificate_no"] = "CERT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    touch(rec)
    return ok(ser_training(rec), 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"Registrar"})
    body = get_body()
    require(body, ["to_iso8601"])
    try:
        _clock["now"] = parse_dt(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_iso8601")
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
