import os
import math
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# In-memory store (starts empty on every boot)
# =============================================================================
DB = {
    "accounts": {},
    "quotes": {},
    "line_items": {},
    "jobs": {},
    "furnaces": {},
    "batches": {},
    "crews": {},
    "appointments": {},
    "claims": {},
    "remakes": {},
}

_seq_counter = 0

# Logical clock — starts at fixed instant, never falls back to wall time.
LOGICAL_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def now():
    return LOGICAL_CLOCK


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ROLES = {"ShopAdmin", "Estimator", "Contractor", "Fabricator", "Scheduler"}

# =============================================================================
# Calculation constants
# =============================================================================
MIN_BILLABLE_SQFT = Decimal("4.0")
RATE = {"ANNEALED": 800, "TEMPERED": 1400, "LAMINATED": 2000, "INSULATED": 2600}
THICKNESS_MULT = {6: Decimal("1.0"), 10: Decimal("1.25"), 12: Decimal("1.5")}
EDGE_RATE = {"NONE": 0, "POLISHED": 150, "BEVELED": 300}
PRODUCT_FEE = {"SHOWER_ENCLOSURE": 5000, "STOREFRONT": 8000,
               "CUSTOM_MIRROR": 2000, "TABLETOP": 1500}
TIER_DISCOUNT_PCT = {"WALK_IN": Decimal("0.0"), "BRONZE": Decimal("0.05"),
                     "SILVER": Decimal("0.10"), "GOLD": Decimal("0.15")}
QUOTE_VALID_DAYS = 30
WARRANTY_DAYS = 365
FAB_BASE_DAYS = 3
STD_THROUGHPUT_SQFT_PER_DAY = 50
INSTALL_DAYS = 2
REMAKE_SURCHARGE_CENTS = 2500

PRODUCT_TYPES = set(PRODUCT_FEE.keys())
GLASS_TYPES = set(RATE.keys())
EDGE_TYPES = set(EDGE_RATE.keys())
THICKNESSES = {6, 10, 12}


def rhu(value, decimals=0):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-decimals)  # 10^-decimals
    return value.quantize(q, rounding=ROUND_HALF_UP)


# =============================================================================
# Auth
# =============================================================================
def authenticate():
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown role")
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def require(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# =============================================================================
# Response envelope
# =============================================================================
def make_meta(extra=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    meta = {"api_request_id": rid, "api_request_timestamp": iso(now())}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = make_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


# =============================================================================
# Input helpers
# =============================================================================
def get_body():
    if not request.data:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {f}")


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_INVALID", 400, "limit invalid")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_PAGINATION_INVALID", 400, "limit out of bounds")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_INVALID", 400, "offset invalid")
        if offset < 0:
            raise ApiError("ERR_PAGINATION_INVALID", 400, "offset out of bounds")
    return limit, offset


def paginate(records, serializer, limit, offset):
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(r) for r in page], total


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


def base_record():
    return {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }


# =============================================================================
# Pricing / calculations
# =============================================================================
def line_billable(li):
    area = rhu(Decimal(str(li["width_in"])) * Decimal(str(li["height_in"])) / Decimal(144), 2)
    return max(area, MIN_BILLABLE_SQFT)


def line_pricing(li):
    billable = line_billable(li)
    rate_term = Decimal(RATE[li["glass_type"]]) * THICKNESS_MULT[li["thickness_mm"]] + Decimal(EDGE_RATE[li["edge_work"]])
    unit_price = int(rhu(billable * rate_term, 0)) + PRODUCT_FEE[li["product_type"]]
    line_total = unit_price * li["quantity"]
    return billable, unit_price, line_total


def lines_of_quote(quote_id):
    return [li for li in DB["line_items"].values() if li["quote_id"] == quote_id]


def lines_of_job(job):
    return lines_of_quote(job["quote_id"])


def job_fab_sqft_dec(job):
    total = Decimal("0")
    for li in lines_of_job(job):
        total += line_billable(li) * Decimal(li["quantity"])
    return total


def compute_quote_totals(quote):
    account = DB["accounts"][quote["contractor_account_id"]]
    tier_pct = TIER_DISCOUNT_PCT[account["tier"]]
    subtotal = 0
    total = 0
    for li in lines_of_quote(quote["id"]):
        _, _, line_total = line_pricing(li)
        subtotal += line_total
        total += int(rhu(Decimal(line_total) * (Decimal(1) - tier_pct), 0))
    discount = subtotal - total
    return subtotal, total, discount


def quoted_lead_days(quote):
    fab = Decimal("0")
    for li in lines_of_quote(quote["id"]):
        fab += line_billable(li) * Decimal(li["quantity"])
    fab_days = math.ceil(fab / Decimal(STD_THROUGHPUT_SQFT_PER_DAY))
    return FAB_BASE_DAYS + fab_days + INSTALL_DAYS


def committed_lead_days(job):
    backlog = Decimal("0")
    for b in DB["batches"].values():
        if b["status"] == "SCHEDULED":
            backlog += Decimal(str(b["total_sqft"]))
    combined = backlog + job_fab_sqft_dec(job)
    fab_days = math.ceil(combined / Decimal(STD_THROUGHPUT_SQFT_PER_DAY))
    return FAB_BASE_DAYS + fab_days + INSTALL_DAYS


def job_final_total(job):
    account = DB["accounts"][job["contractor_account_id"]]
    tier_pct = TIER_DISCOUNT_PCT[account["tier"]]
    total = 0
    for li in lines_of_job(job):
        if li["status"] == "INSTALLED":
            _, _, line_total = line_pricing(li)
            total += int(rhu(Decimal(line_total) * (Decimal(1) - tier_pct), 0))
    billable_remakes = sum(1 for r in DB["remakes"].values()
                           if r["job_id"] == job["id"] and r["billable_to_contractor"])
    total += REMAKE_SURCHARGE_CENTS * billable_remakes
    return total


def batch_total_sqft(job):
    total = Decimal("0")
    for li in lines_of_job(job):
        if li["status"] == "FABRICATING":
            total += line_billable(li) * Decimal(li["quantity"])
    return rhu(total, 2)


def dec_to_num(d):
    # Return int when integral, else float — for JSON numeric output.
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# =============================================================================
# Serializers
# =============================================================================
def common(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_account(a):
    d = common(a)
    used = a["credit_used_cents"]
    d.update({
        "company_name": a["company_name"],
        "tier": a["tier"],
        "credit_limit_cents": a["credit_limit_cents"],
        "credit_used_cents": used,
        "available_credit_cents": a["credit_limit_cents"] - used,
        "status": a["status"],
    })
    return d


def ser_quote(q):
    d = common(q)
    if q["status"] == "DRAFT" and q.get("subtotal_cents") is None:
        subtotal = total = discount = None
    else:
        subtotal = q.get("subtotal_cents")
        total = q.get("total_cents")
        discount = q.get("discount_cents")
    d.update({
        "contractor_account_id": q["contractor_account_id"],
        "status": q["status"],
        "revision_number": q["revision_number"],
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": total,
        "quoted_lead_days": q.get("quoted_lead_days"),
        "valid_until": iso(q.get("valid_until")),
        "ordered_job_id": q.get("ordered_job_id"),
    })
    return d


def ser_line(li):
    billable, unit_price, line_total = line_pricing(li)
    d = common(li)
    d.update({
        "quote_id": li["quote_id"],
        "product_type": li["product_type"],
        "glass_type": li["glass_type"],
        "thickness_mm": li["thickness_mm"],
        "width_in": li["width_in"],
        "height_in": li["height_in"],
        "quantity": li["quantity"],
        "edge_work": li["edge_work"],
        "requires_safety_glazing": li["requires_safety_glazing"],
        "billable_sqft": dec_to_num(billable),
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "status": li["status"],
    })
    return d


def ser_job(j):
    d = common(j)
    d.update({
        "quote_id": j["quote_id"],
        "contractor_account_id": j["contractor_account_id"],
        "status": j["status"],
        "fabrication_status": j["fabrication_status"],
        "install_status": j["install_status"],
        "job_fab_sqft": dec_to_num(job_fab_sqft_dec(j)),
        "committed_lead_days": j["committed_lead_days"],
        "credit_hold_cents": j["credit_hold_cents"],
        "final_total_cents": job_final_total(j),
    })
    return d


def ser_furnace(f):
    d = common(f)
    d.update({
        "name": f["name"],
        "max_batch_sqft": f["max_batch_sqft"],
        "cooldown_minutes": f["cooldown_minutes"],
        "reserved_sqft": dec_to_num(Decimal(str(f["reserved_sqft"]))),
    })
    return d


def ser_batch(b):
    d = common(b)
    d.update({
        "furnace_id": b["furnace_id"],
        "job_id": b["job_id"],
        "scheduled_start": iso(b["scheduled_start"]),
        "scheduled_end": iso(b["scheduled_end"]),
        "total_sqft": dec_to_num(Decimal(str(b["total_sqft"]))),
        "status": b["status"],
    })
    return d


def ser_crew(c):
    d = common(c)
    d.update({"name": c["name"], "certified_products": c["certified_products"]})
    return d


def ser_appt(a):
    d = common(a)
    d.update({
        "crew_id": a["crew_id"],
        "job_id": a["job_id"],
        "window_start": iso(a["window_start"]),
        "window_end": iso(a["window_end"]),
        "status": a["status"],
    })
    return d


def ser_claim(c):
    d = common(c)
    d.update({
        "job_id": c["job_id"],
        "line_item_id": c["line_item_id"],
        "claim_type": c["claim_type"],
        "cause": c["cause"],
        "billable_to_contractor": c["billable_to_contractor"],
        "status": c["status"],
        "remake_order_id": c.get("remake_order_id"),
    })
    return d


def ser_remake(r):
    d = common(r)
    d.update({
        "claim_report_id": r["claim_report_id"],
        "job_id": r["job_id"],
        "line_item_id": r["line_item_id"],
        "billable_to_contractor": r["billable_to_contractor"],
        "remake_cost_cents": r["remake_cost_cents"],
        "status": r["status"],
    })
    return d


# =============================================================================
# Lookup helpers
# =============================================================================
def find(coll, _id):
    rec = DB[coll].get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


# =============================================================================
# ContractorAccount endpoints
# =============================================================================
@app.route("/contractor-accounts", methods=["POST"])
def create_account():
    _uid, role = authenticate()
    require(role, {"ShopAdmin"})
    body = get_body()
    require_fields(body, ["company_name", "tier", "credit_limit_cents"])
    if body["tier"] not in TIER_DISCOUNT_PCT:
        raise ApiError("ERR_VALIDATION", 400, "Illegal tier")
    limit = body["credit_limit_cents"]
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ApiError("ERR_VALIDATION", 400, "credit_limit_cents must be >= 0 integer")
    rec = base_record()
    rec.update({
        "company_name": body["company_name"],
        "tier": body["tier"],
        "credit_limit_cents": limit,
        "credit_used_cents": 0,
        "status": "ACTIVE",
    })
    DB["accounts"][rec["id"]] = rec
    return ok(ser_account(rec), 201)


@app.route("/contractor-accounts/<aid>", methods=["GET"])
def get_account(aid):
    _uid, role = authenticate()
    require(role, {"ShopAdmin", "Estimator", "Contractor", "Fabricator", "Scheduler"})
    rec = find("accounts", aid)
    return ok(ser_account(rec))


@app.route("/contractor-accounts/<aid>/set-status", methods=["POST"])
def set_account_status(aid):
    _uid, role = authenticate()
    require(role, {"ShopAdmin"})
    rec = find("accounts", aid)
    body = get_body()
    require_fields(body, ["status"])
    new_status = body["status"]
    if new_status not in {"ACTIVE", "ON_HOLD", "SUSPENDED"}:
        raise ApiError("ERR_VALIDATION", 400, "Illegal status")
    allowed = {
        ("ACTIVE", "ON_HOLD"), ("ON_HOLD", "ACTIVE"),
        ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"),
    }
    if (rec["status"], new_status) not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409, "Illegal status transition")
    rec["status"] = new_status
    touch(rec)
    return ok(ser_account(rec))


# =============================================================================
# Quote endpoints
# =============================================================================
@app.route("/quotes", methods=["POST"])
def create_quote():
    _uid, role = authenticate()
    require(role, {"Estimator"})
    body = get_body()
    require_fields(body, ["contractor_account_id"])
    find("accounts", body["contractor_account_id"])
    rec = base_record()
    rec.update({
        "contractor_account_id": body["contractor_account_id"],
        "status": "DRAFT",
        "revision_number": 1,
        "subtotal_cents": None,
        "discount_cents": None,
        "total_cents": None,
        "quoted_lead_days": None,
        "valid_until": None,
        "ordered_job_id": None,
    })
    DB["quotes"][rec["id"]] = rec
    return ok(ser_quote(rec), 201)


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    _uid, role = authenticate()
    require(role, {"Estimator", "Contractor", "ShopAdmin"})
    rec = find("quotes", qid)
    return ok(ser_quote(rec))


@app.route("/quotes", methods=["GET"])
def list_quotes():
    _uid, role = authenticate()
    require(role, {"Estimator", "Contractor", "ShopAdmin"})
    limit, offset = get_pagination()
    recs = list(DB["quotes"].values())
    acc = request.args.get("contractor_account_id")
    if acc is not None:
        recs = [r for r in recs if r["contractor_account_id"] == acc]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    items, total = paginate(recs, ser_quote, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/quotes/<qid>/line-items", methods=["POST"])
def add_line_item(qid):
    _uid, role = authenticate()
    require(role, {"Estimator"})
    quote = find("quotes", qid)
    body = get_body()
    require_fields(body, ["product_type", "glass_type", "thickness_mm",
                          "width_in", "height_in", "quantity"])
    if body["product_type"] not in PRODUCT_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "Illegal product_type")
    if body["glass_type"] not in GLASS_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "Illegal glass_type")
    thickness = body["thickness_mm"]
    if not isinstance(thickness, int) or isinstance(thickness, bool) or thickness not in THICKNESSES:
        raise ApiError("ERR_VALIDATION", 400, "thickness_mm must be one of 6, 10, 12")
    edge = body.get("edge_work", "NONE")
    if edge is None:
        edge = "NONE"
    if edge not in EDGE_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "Illegal edge_work")
    width = body["width_in"]
    height = body["height_in"]
    if not _is_number(width) or width <= 0:
        raise ApiError("ERR_VALIDATION", 400, "width_in must be > 0")
    if not _is_number(height) or height <= 0:
        raise ApiError("ERR_VALIDATION", 400, "height_in must be > 0")
    quantity = body["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise ApiError("ERR_VALIDATION", 400, "quantity must be >= 1")
    safety = body.get("requires_safety_glazing", False)
    if safety is None:
        safety = False
    if not isinstance(safety, bool):
        raise ApiError("ERR_VALIDATION", 400, "requires_safety_glazing must be boolean")
    # State legality: quote must be DRAFT to add lines.
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Quote is not in DRAFT")
    rec = base_record()
    rec.update({
        "quote_id": qid,
        "product_type": body["product_type"],
        "glass_type": body["glass_type"],
        "thickness_mm": thickness,
        "width_in": width,
        "height_in": height,
        "quantity": quantity,
        "edge_work": edge,
        "requires_safety_glazing": safety,
        "status": "SPEC",
        "installed_at": None,
    })
    DB["line_items"][rec["id"]] = rec
    return ok(ser_line(rec), 201)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@app.route("/quotes/<qid>/line-items", methods=["GET"])
def list_line_items(qid):
    _uid, role = authenticate()
    require(role, {"Estimator", "Contractor", "ShopAdmin"})
    find("quotes", qid)
    limit, offset = get_pagination()
    recs = [li for li in DB["line_items"].values() if li["quote_id"] == qid]
    items, total = paginate(recs, ser_line, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/quotes/<qid>/send", methods=["POST"])
def send_quote(qid):
    _uid, role = authenticate()
    require(role, {"Estimator"})
    quote = find("quotes", qid)
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Quote must be DRAFT to send")
    lines = lines_of_quote(qid)
    if len(lines) < 1:
        raise ApiError("ERR_QUOTE_EMPTY", 422, "Quote has no line items")
    subtotal, total, discount = compute_quote_totals(quote)
    quote["subtotal_cents"] = subtotal
    quote["total_cents"] = total
    quote["discount_cents"] = discount
    quote["quoted_lead_days"] = quoted_lead_days(quote)
    quote["valid_until"] = quote["created_at"] + timedelta(days=QUOTE_VALID_DAYS)
    quote["status"] = "SENT"
    touch(quote)
    return ok(ser_quote(quote))


@app.route("/quotes/<qid>/revise", methods=["POST"])
def revise_quote(qid):
    _uid, role = authenticate()
    require(role, {"Estimator"})
    quote = find("quotes", qid)
    if quote["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Quote must be SENT to revise")
    quote["status"] = "DRAFT"
    quote["revision_number"] += 1
    quote["quoted_lead_days"] = None
    quote["valid_until"] = None
    touch(quote)
    return ok(ser_quote(quote))


@app.route("/quotes/<qid>/accept", methods=["POST"])
def accept_quote(qid):
    uid, role = authenticate()
    require(role, {"Contractor"})
    quote = find("quotes", qid)
    # ownership
    if uid != quote["contractor_account_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Contractor may only accept its own quote")
    body = get_body()
    account = find("accounts", quote["contractor_account_id"])
    # state legality
    if quote["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Quote must be SENT to accept")
    # business checks in pinned order: account-active, expiry, credit, stale-version
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Contractor account not ACTIVE")
    if now() > quote["valid_until"]:
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "Quote has expired")
    available = account["credit_limit_cents"] - account["credit_used_cents"]
    if available < quote["total_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 409, "Credit limit exceeded")
    expected = body.get("expected_account_version")
    if expected is not None and expected != account["version"]:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION", 412, "Account version is stale")

    # Create job
    job = base_record()
    job.update({
        "quote_id": qid,
        "contractor_account_id": account["id"],
        "status": "ACTIVE",
        "fabrication_status": "PENDING",
        "install_status": "NOT_READY",
        "committed_lead_days": None,
        "credit_hold_cents": quote["total_cents"],
    })
    job["committed_lead_days"] = committed_lead_days(job)
    DB["jobs"][job["id"]] = job

    quote["status"] = "ORDERED"
    quote["ordered_job_id"] = job["id"]
    touch(quote)

    account["credit_used_cents"] += job["credit_hold_cents"]
    touch(account)

    for li in lines_of_quote(qid):
        if li["status"] == "SPEC":
            li["status"] = "FABRICATING"
            touch(li)

    return ok(ser_quote(quote))


# =============================================================================
# Job endpoints
# =============================================================================
@app.route("/jobs/<jid>", methods=["GET"])
def get_job(jid):
    _uid, role = authenticate()
    require(role, {"Estimator", "Fabricator", "Scheduler", "ShopAdmin", "Contractor"})
    job = find("jobs", jid)
    return ok(ser_job(job))


@app.route("/jobs", methods=["GET"])
def list_jobs():
    _uid, role = authenticate()
    require(role, {"Estimator", "Fabricator", "Scheduler", "ShopAdmin", "Contractor"})
    limit, offset = get_pagination()
    recs = list(DB["jobs"].values())
    qf = request.args.get("quote_id")
    if qf is not None:
        recs = [r for r in recs if r["quote_id"] == qf]
    af = request.args.get("contractor_account_id")
    if af is not None:
        recs = [r for r in recs if r["contractor_account_id"] == af]
    items, total = paginate(recs, ser_job, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    _uid, role = authenticate()
    require(role, {"ShopAdmin"})
    job = find("jobs", jid)
    if job["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Job must be ACTIVE to cancel")
    job["status"] = "CANCELLED"
    touch(job)
    # Release credit hold
    account = DB["accounts"].get(job["contractor_account_id"])
    if account is not None:
        account["credit_used_cents"] -= job["credit_hold_cents"]
        touch(account)
    # Cancel scheduled batches (release furnace reservation)
    for b in DB["batches"].values():
        if b["job_id"] == jid and b["status"] == "SCHEDULED":
            b["status"] = "CANCELLED"
            touch(b)
            furnace = DB["furnaces"].get(b["furnace_id"])
            if furnace is not None:
                furnace["reserved_sqft"] = float(
                    Decimal(str(furnace["reserved_sqft"])) - Decimal(str(b["total_sqft"])))
                touch(furnace)
    # Cancel scheduled appointments
    for a in DB["appointments"].values():
        if a["job_id"] == jid and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            touch(a)
    return ok(ser_job(job))


# =============================================================================
# TemperingFurnace endpoints
# =============================================================================
@app.route("/tempering-furnaces", methods=["POST"])
def create_furnace():
    _uid, role = authenticate()
    require(role, {"ShopAdmin"})
    body = get_body()
    require_fields(body, ["name", "max_batch_sqft"])
    mbs = body["max_batch_sqft"]
    if not _is_number(mbs) or mbs <= 0:
        raise ApiError("ERR_VALIDATION", 400, "max_batch_sqft must be > 0")
    cooldown = body.get("cooldown_minutes", 60)
    if cooldown is None:
        cooldown = 60
    if not isinstance(cooldown, int) or isinstance(cooldown, bool) or cooldown < 0:
        raise ApiError("ERR_VALIDATION", 400, "cooldown_minutes must be a non-negative integer")
    rec = base_record()
    rec.update({
        "name": body["name"],
        "max_batch_sqft": mbs,
        "cooldown_minutes": cooldown,
        "reserved_sqft": 0,
    })
    DB["furnaces"][rec["id"]] = rec
    return ok(ser_furnace(rec), 201)


@app.route("/tempering-furnaces/<fid>", methods=["GET"])
def get_furnace(fid):
    _uid, role = authenticate()
    require(role, {"Fabricator", "ShopAdmin"})
    rec = find("furnaces", fid)
    return ok(ser_furnace(rec))


# =============================================================================
# TemperingBatch endpoints
# =============================================================================
@app.route("/tempering-batches", methods=["POST"])
def create_batch():
    _uid, role = authenticate()
    require(role, {"Fabricator"})
    body = get_body()
    require_fields(body, ["job_id", "furnace_id", "scheduled_start", "scheduled_end"])
    job = find("jobs", body["job_id"])
    furnace = find("furnaces", body["furnace_id"])
    try:
        start = parse_iso(body["scheduled_start"])
        end = parse_iso(body["scheduled_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end must be after scheduled_start")

    total = batch_total_sqft(job)
    # Empty batch check
    if total <= 0:
        raise ApiError("ERR_EMPTY_BATCH", 422, "No FABRICATING line items for this job")
    # Furnace window conflict (with cooldown buffer) — half-open windows extended.
    cooldown = timedelta(minutes=furnace["cooldown_minutes"])
    for b in DB["batches"].values():
        if b["furnace_id"] != furnace["id"] or b["status"] != "SCHEDULED":
            continue
        es = b["scheduled_start"]
        ee = b["scheduled_end"]
        # ok if fully separated by cooldown either side
        if start >= ee + cooldown or end + cooldown <= es:
            continue
        raise ApiError("ERR_FURNACE_WINDOW_CONFLICT", 409, "Furnace window conflict")
    # Capacity check
    if total > Decimal(str(furnace["max_batch_sqft"])):
        raise ApiError("ERR_BATCH_CAPACITY_EXCEEDED", 422, "Batch exceeds furnace capacity")

    rec = base_record()
    rec.update({
        "furnace_id": furnace["id"],
        "job_id": job["id"],
        "scheduled_start": start,
        "scheduled_end": end,
        "total_sqft": dec_to_num(total),
        "status": "SCHEDULED",
    })
    DB["batches"][rec["id"]] = rec
    furnace["reserved_sqft"] = float(Decimal(str(furnace["reserved_sqft"])) + total)
    touch(furnace)
    if job["fabrication_status"] == "PENDING":
        job["fabrication_status"] = "IN_FABRICATION"
        touch(job)
    return ok(ser_batch(rec), 201)


@app.route("/tempering-batches/<bid>", methods=["GET"])
def get_batch(bid):
    _uid, role = authenticate()
    require(role, {"Fabricator", "ShopAdmin"})
    rec = find("batches", bid)
    return ok(ser_batch(rec))


@app.route("/tempering-batches", methods=["GET"])
def list_batches():
    _uid, role = authenticate()
    require(role, {"Fabricator", "ShopAdmin"})
    limit, offset = get_pagination()
    recs = list(DB["batches"].values())
    ff = request.args.get("furnace_id")
    if ff is not None:
        recs = [r for r in recs if r["furnace_id"] == ff]
    jf = request.args.get("job_id")
    if jf is not None:
        recs = [r for r in recs if r["job_id"] == jf]
    sf = request.args.get("status")
    if sf is not None:
        recs = [r for r in recs if r["status"] == sf]
    items, total = paginate(recs, ser_batch, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/tempering-batches/<bid>/complete", methods=["POST"])
def complete_batch(bid):
    _uid, role = authenticate()
    require(role, {"Fabricator"})
    batch = find("batches", bid)
    if batch["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch must be SCHEDULED to complete")
    batch["status"] = "DONE"
    touch(batch)
    job = DB["jobs"][batch["job_id"]]
    for li in lines_of_job(job):
        if li["status"] == "FABRICATING":
            li["status"] = "FABRICATED"
            touch(li)
    furnace = DB["furnaces"].get(batch["furnace_id"])
    if furnace is not None:
        furnace["reserved_sqft"] = float(
            Decimal(str(furnace["reserved_sqft"])) - Decimal(str(batch["total_sqft"])))
        touch(furnace)
    lines = lines_of_job(job)
    if lines and all(li["status"] == "FABRICATED" for li in lines) and job["fabrication_status"] == "IN_FABRICATION":
        job["fabrication_status"] = "COMPLETE"
        if job["install_status"] == "NOT_READY":
            job["install_status"] = "READY"
        touch(job)
    return ok(ser_batch(batch))


@app.route("/tempering-batches/<bid>/cancel", methods=["POST"])
def cancel_batch(bid):
    _uid, role = authenticate()
    require(role, {"Fabricator"})
    batch = find("batches", bid)
    if batch["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch must be SCHEDULED to cancel")
    batch["status"] = "CANCELLED"
    touch(batch)
    furnace = DB["furnaces"].get(batch["furnace_id"])
    if furnace is not None:
        furnace["reserved_sqft"] = float(
            Decimal(str(furnace["reserved_sqft"])) - Decimal(str(batch["total_sqft"])))
        touch(furnace)
    return ok(ser_batch(batch))


# =============================================================================
# InstallCrew endpoints
# =============================================================================
@app.route("/install-crews", methods=["POST"])
def create_crew():
    _uid, role = authenticate()
    require(role, {"ShopAdmin"})
    body = get_body()
    require_fields(body, ["name", "certified_products"])
    certs = body["certified_products"]
    if not isinstance(certs, list) or any(c not in PRODUCT_TYPES for c in certs):
        raise ApiError("ERR_VALIDATION", 400, "Illegal certified_products")
    rec = base_record()
    rec.update({"name": body["name"], "certified_products": certs})
    DB["crews"][rec["id"]] = rec
    return ok(ser_crew(rec), 201)


# =============================================================================
# InstallAppointment endpoints
# =============================================================================
@app.route("/install-appointments", methods=["POST"])
def create_appointment():
    _uid, role = authenticate()
    require(role, {"Scheduler"})
    body = get_body()
    require_fields(body, ["job_id", "crew_id", "window_start", "window_end"])
    job = find("jobs", body["job_id"])
    crew = find("crews", body["crew_id"])
    try:
        start = parse_iso(body["window_start"])
        end = parse_iso(body["window_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400, "window_end must be after window_start")

    lines = lines_of_job(job)
    # Safety glazing (422) first
    for li in lines:
        if li["requires_safety_glazing"] and li["glass_type"] not in {"TEMPERED", "LAMINATED"}:
            raise ApiError("ERR_SAFETY_GLAZING_REQUIRED", 422, "Safety glazing required")
    # Fabrication complete
    if job["fabrication_status"] != "COMPLETE":
        raise ApiError("ERR_FABRICATION_INCOMPLETE", 409, "Job fabrication not complete")
    # Crew certified for every product type present in the job
    job_products = {li["product_type"] for li in lines}
    if any(p not in set(crew["certified_products"]) for p in job_products):
        raise ApiError("ERR_CREW_NOT_CERTIFIED", 409, "Crew not certified for a product type")
    # Crew double-booking (half-open overlap)
    for a in DB["appointments"].values():
        if a["crew_id"] != crew["id"] or a["status"] != "SCHEDULED":
            continue
        if start < a["window_end"] and a["window_start"] < end:
            raise ApiError("ERR_CREW_DOUBLE_BOOKED", 409, "Crew double booked")

    rec = base_record()
    rec.update({
        "crew_id": crew["id"],
        "job_id": job["id"],
        "window_start": start,
        "window_end": end,
        "status": "SCHEDULED",
    })
    DB["appointments"][rec["id"]] = rec
    if job["install_status"] == "READY":
        job["install_status"] = "SCHEDULED"
        touch(job)
    return ok(ser_appt(rec), 201)


@app.route("/install-appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    _uid, role = authenticate()
    require(role, {"Scheduler", "ShopAdmin"})
    rec = find("appointments", aid)
    return ok(ser_appt(rec))


@app.route("/install-appointments", methods=["GET"])
def list_appointments():
    _uid, role = authenticate()
    require(role, {"Scheduler", "ShopAdmin"})
    limit, offset = get_pagination()
    recs = list(DB["appointments"].values())
    cf = request.args.get("crew_id")
    if cf is not None:
        recs = [r for r in recs if r["crew_id"] == cf]
    jf = request.args.get("job_id")
    if jf is not None:
        recs = [r for r in recs if r["job_id"] == jf]
    sf = request.args.get("status")
    if sf is not None:
        recs = [r for r in recs if r["status"] == sf]
    items, total = paginate(recs, ser_appt, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/install-appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    _uid, role = authenticate()
    require(role, {"Scheduler"})
    appt = find("appointments", aid)
    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment must be SCHEDULED to complete")
    appt["status"] = "COMPLETED"
    touch(appt)
    job = DB["jobs"][appt["job_id"]]
    for li in lines_of_job(job):
        if li["status"] == "FABRICATED":
            li["status"] = "INSTALLED"
            li["installed_at"] = now()
            touch(li)
    if job["install_status"] == "SCHEDULED":
        job["install_status"] = "INSTALLED"
        touch(job)
    if job["fabrication_status"] == "COMPLETE" and job["status"] == "ACTIVE":
        job["status"] = "CLOSED"
        touch(job)
    return ok(ser_appt(appt))


# =============================================================================
# ClaimReport endpoints
# =============================================================================
@app.route("/claim-reports", methods=["POST"])
def create_claim():
    uid, role = authenticate()
    require(role, {"Scheduler", "Fabricator", "Contractor"})
    body = get_body()
    require_fields(body, ["job_id", "line_item_id", "claim_type", "cause"])
    job = find("jobs", body["job_id"])
    # Contractor ownership on the job
    if role == "Contractor" and uid != job["contractor_account_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Contractor may only claim on its own job")
    line = find("line_items", body["line_item_id"])
    if line["quote_id"] != job["quote_id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Line item does not belong to job")
    claim_type = body["claim_type"]
    if claim_type not in {"BREAKAGE", "WARRANTY_DEFECT"}:
        raise ApiError("ERR_VALIDATION", 400, "Illegal claim_type")
    if not isinstance(body["cause"], str):
        raise ApiError("ERR_VALIDATION", 400, "cause must be a string")
    billable = body.get("billable_to_contractor", False)
    if billable is None:
        billable = False
    if not isinstance(billable, bool):
        raise ApiError("ERR_VALIDATION", 400, "billable_to_contractor must be boolean")

    # Warranty window then target-state checks
    if claim_type == "WARRANTY_DEFECT" and line["status"] == "INSTALLED":
        installed_at = line.get("installed_at")
        if installed_at is not None and now() > installed_at + timedelta(days=WARRANTY_DAYS):
            raise ApiError("ERR_CLAIM_WINDOW_EXPIRED", 409, "Warranty window expired")
    if claim_type == "WARRANTY_DEFECT":
        if line["status"] != "INSTALLED":
            raise ApiError("ERR_CLAIM_TARGET_INVALID", 409, "Target line not INSTALLED")
    else:  # BREAKAGE
        if line["status"] not in {"FABRICATED", "INSTALLED"}:
            raise ApiError("ERR_CLAIM_TARGET_INVALID", 409, "Target line not claimable")

    rec = base_record()
    rec.update({
        "job_id": job["id"],
        "line_item_id": line["id"],
        "claim_type": claim_type,
        "cause": body["cause"],
        "billable_to_contractor": billable,
        "status": "FILED",
        "remake_order_id": None,
    })
    DB["claims"][rec["id"]] = rec
    return ok(ser_claim(rec), 201)


@app.route("/claim-reports/<cid>", methods=["GET"])
def get_claim(cid):
    _uid, role = authenticate()
    require(role, {"Scheduler", "Fabricator", "ShopAdmin", "Contractor"})
    rec = find("claims", cid)
    return ok(ser_claim(rec))


@app.route("/claim-reports", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    require(role, {"Scheduler", "Fabricator", "ShopAdmin", "Contractor"})
    limit, offset = get_pagination()
    recs = list(DB["claims"].values())
    lf = request.args.get("line_item_id")
    if lf is not None:
        recs = [r for r in recs if r["line_item_id"] == lf]
    jf = request.args.get("job_id")
    if jf is not None:
        recs = [r for r in recs if r["job_id"] == jf]
    sf = request.args.get("status")
    if sf is not None:
        recs = [r for r in recs if r["status"] == sf]
    items, total = paginate(recs, ser_claim, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/claim-reports/<cid>/review", methods=["POST"])
def review_claim(cid):
    _uid, role = authenticate()
    require(role, {"ShopAdmin"})
    claim = find("claims", cid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in {"APPROVE", "REJECT"}:
        raise ApiError("ERR_VALIDATION", 400, "Illegal decision")
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim must be FILED to review")

    if decision == "REJECT":
        claim["status"] = "REJECTED"
        touch(claim)
        return ok(ser_claim(claim))

    # APPROVE cascade
    claim["status"] = "APPROVED"
    line = DB["line_items"][claim["line_item_id"]]
    job = DB["jobs"][claim["job_id"]]
    was_installed = line["status"] == "INSTALLED"
    # hop 1: line -> BROKEN
    line["status"] = "BROKEN"
    touch(line)
    # hop 2: create RemakeOrder
    _, unit_price, _ = line_pricing(line)
    remake = base_record()
    remake.update({
        "claim_report_id": claim["id"],
        "job_id": job["id"],
        "line_item_id": line["id"],
        "billable_to_contractor": claim["billable_to_contractor"],
        "remake_cost_cents": unit_price + REMAKE_SURCHARGE_CENTS,
        "status": "PENDING",
    })
    DB["remakes"][remake["id"]] = remake
    claim["remake_order_id"] = remake["id"]
    touch(claim)
    if job["fabrication_status"] == "COMPLETE":
        job["fabrication_status"] = "REOPENED"
        touch(job)
    if was_installed:
        if job["install_status"] == "INSTALLED":
            job["install_status"] = "ON_HOLD"
            touch(job)
        if job["status"] == "CLOSED":
            job["status"] = "ACTIVE"
            touch(job)
    # hop 3: billable surcharge
    if claim["billable_to_contractor"]:
        account = DB["accounts"].get(job["contractor_account_id"])
        if account is not None:
            account["credit_used_cents"] += REMAKE_SURCHARGE_CENTS
            touch(account)
        job["credit_hold_cents"] += REMAKE_SURCHARGE_CENTS
        touch(job)
    return ok(ser_claim(claim))


# =============================================================================
# RemakeOrder endpoints
# =============================================================================
@app.route("/remake-orders/<rid>", methods=["GET"])
def get_remake(rid):
    _uid, role = authenticate()
    require(role, {"Fabricator", "Scheduler", "ShopAdmin"})
    rec = find("remakes", rid)
    return ok(ser_remake(rec))


@app.route("/remake-orders", methods=["GET"])
def list_remakes():
    _uid, role = authenticate()
    require(role, {"Fabricator", "Scheduler", "ShopAdmin"})
    limit, offset = get_pagination()
    recs = list(DB["remakes"].values())
    cf = request.args.get("claim_report_id")
    if cf is not None:
        recs = [r for r in recs if r["claim_report_id"] == cf]
    jf = request.args.get("job_id")
    if jf is not None:
        recs = [r for r in recs if r["job_id"] == jf]
    lf = request.args.get("line_item_id")
    if lf is not None:
        recs = [r for r in recs if r["line_item_id"] == lf]
    sf = request.args.get("status")
    if sf is not None:
        recs = [r for r in recs if r["status"] == sf]
    items, total = paginate(recs, ser_remake, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/remake-orders/<rid>/complete", methods=["POST"])
def complete_remake(rid):
    _uid, role = authenticate()
    require(role, {"Fabricator"})
    remake = find("remakes", rid)
    if remake["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Remake must be PENDING to complete")
    remake["status"] = "COMPLETE"
    touch(remake)
    line = DB["line_items"][remake["line_item_id"]]
    if line["status"] == "BROKEN":
        line["status"] = "FABRICATED"
        touch(line)
    job = DB["jobs"][remake["job_id"]]
    lines = lines_of_job(job)
    if lines and all(li["status"] in {"FABRICATED", "INSTALLED"} for li in lines) and job["fabrication_status"] == "REOPENED":
        job["fabrication_status"] = "COMPLETE"
        touch(job)
    return ok(ser_remake(remake))


# =============================================================================
# Clock endpoint
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require(role, {"ShopAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    global LOGICAL_CLOCK
    try:
        LOGICAL_CLOCK = parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_iso8601")
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
