import os
import uuid
import random
import string
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from PRD / SCAFFOLD calculation tables)
# ---------------------------------------------------------------------------
VENDOR_DISCOUNT_BPS = 150
VENDOR_DISCOUNT_CAP_CENTS = 100000
NEGLIGENCE_PENALTY_BPS = 2500
LATE_FILING_PENALTY_BPS = 1000
LATE_FILING_PENALTY_CAP_CENTS = 500000
MONTHLY_INTEREST_BPS = 100
REFUND_GRACE_DAYS = 90
DAILY_INTEREST_BPS = 3
NEXUS_THRESHOLD_CENTS = 10000000
APPEAL_WINDOW_DAYS = 60

READ_ROLES = ["TaxAdmin", "TaxAuditor", "AppealsOfficer", "Taxpayer"]
KNOWN_ROLES = {"TaxAdmin", "TaxAuditor", "AppealsOfficer", "Taxpayer", "Anonymous"}

ENTITY_TYPES = {"SOLE_PROP", "LLC", "CORP", "PARTNERSHIP"}
FILING_FREQS = {"MONTHLY", "QUARTERLY", "ANNUAL"}
EXEMPTION_TYPES = {"RESALE", "GOVERNMENT", "NONPROFIT", "MANUFACTURING"}
REMITTANCE_TYPES = {"PAYMENT", "PREPAYMENT"}
AUDIT_TYPES = {"FIELD_AUDIT", "NEXUS_DISCOVERY"}
ASSESSMENT_TYPES = {"AUDIT_DEFICIENCY", "LATE_FILING"}
REFUND_REASONS = {"TAXPAYER_ERROR", "AUDIT_ADJUSTMENT"}

# ---------------------------------------------------------------------------
# In-memory stores (wiped on every process boot)
# ---------------------------------------------------------------------------
db = {
    "taxpayers": {},
    "jurisdictions": {},
    "returns": {},
    "certificates": {},
    "remittances": {},
    "audits": {},
    "assessments": {},
    "appeals": {},
    "refunds": {},
}
_seq_counter = [0]

# Logical clock — default per PRD §2.5
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now_dt():
    return CLOCK["now"]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % ms) + "Z"


def parse_instant(s):
    """Parse an ISO-8601 string (with optional Z / fractional / date-only)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(s):
    return parse_instant(s).date()


def clock_date():
    return now_dt().astimezone(timezone.utc).date()


# ---------------------------------------------------------------------------
# Money helpers (integer cents, round-half-up)
# ---------------------------------------------------------------------------
def rhu_div(numer, denom):
    """round_half_up(numer / denom) -> int cents."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


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
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _base_meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": fmt_ts(now_dt())}


def ok(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def err_response(e):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(ApiError("ERR_VALIDATION", 400, "Unknown route"))


@app.errorhandler(405)
def handle_405(e):
    return err_response(ApiError("ERR_VALIDATION", 400, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError("ERR_VALIDATION", 400, "Internal error: %s" % e))


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    """Return (user_id, role). Raise if headers missing."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing authentication headers")
    return uid, role


def require(allowed_roles):
    """Authenticate and authorize; return (user_id, role)."""
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s not permitted" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % f)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_pos_int(body, field):
    v = body.get(field)
    if not is_int(v) or v <= 0:
        raise ApiError("ERR_VALIDATION", 400, "%s must be a positive integer" % field)
    return v


def require_nonneg_int(body, field):
    v = body.get(field)
    if not is_int(v) or v < 0:
        raise ApiError("ERR_VALIDATION", 400, "%s must be a non-negative integer" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "%s out of range" % field)
    return v


# ---------------------------------------------------------------------------
# Common entity scaffolding
# ---------------------------------------------------------------------------
def new_common():
    ts = now_dt()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(obj):
    obj["updated_at"] = now_dt()
    obj["version"] += 1


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, serializer):
    items = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serializer(o) for o in page], 200, "array", pagination)


# ---------------------------------------------------------------------------
# Balance ledger (derived on read)
# ---------------------------------------------------------------------------
def compute_balance(taxpayer_id):
    total = 0
    for r in db["returns"].values():
        if r["taxpayer_id"] == taxpayer_id and r["status"] in ("FILED", "ASSESSED"):
            total += r.get("net_return_due_cents") or 0
    for a in db["assessments"].values():
        if a["taxpayer_id"] == taxpayer_id and a["status"] in ("ISSUED", "AFFIRMED"):
            total += a.get("total_due_cents") or 0
    for m in db["remittances"].values():
        if m["taxpayer_id"] == taxpayer_id:
            total -= m.get("applied_amount_cents") or 0
    for f in db["refunds"].values():
        if f["taxpayer_id"] == taxpayer_id and f["status"] == "APPROVED":
            total -= f.get("refund_total_cents") or 0
    return total


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_common(o, out):
    out["id"] = o["id"]
    out["created_at"] = fmt_ts(o["created_at"])
    out["updated_at"] = fmt_ts(o["updated_at"])
    out["version"] = o["version"]
    return out


def ser_taxpayer(o):
    out = {
        "legal_name": o["legal_name"],
        "entity_type": o["entity_type"],
        "email": o["email"],
        "filing_frequency": o["filing_frequency"],
        "account_status": o["account_status"],
        "nexus_status": o["nexus_status"],
        "suspend_reason": o["suspend_reason"],
        "activated_at": fmt_ts(o["activated_at"]),
        "account_balance_cents": compute_balance(o["id"]),
    }
    return ser_common(o, out)


def ser_jurisdiction(o):
    out = {
        "code": o["code"],
        "name": o["name"],
        "rate_bps": o["rate_bps"],
        "active": o["active"],
    }
    return ser_common(o, out)


def ser_return(o):
    out = {
        "taxpayer_id": o["taxpayer_id"],
        "exemption_certificate_id": o["exemption_certificate_id"],
        "period_key": o["period_key"],
        "period_start_date": o["period_start_date"],
        "period_end_date": o["period_end_date"],
        "filing_due_date": o["filing_due_date"],
        "lines": o["lines"],
        "status": o["status"],
        "filed_at": fmt_ts(o["filed_at"]),
        "total_taxable_cents": o["total_taxable_cents"],
        "tax_due_cents": o["tax_due_cents"],
        "vendor_discount_cents": o["vendor_discount_cents"],
        "net_return_due_cents": o["net_return_due_cents"],
    }
    return ser_common(o, out)


def ser_certificate(o):
    out = {
        "taxpayer_id": o["taxpayer_id"],
        "exemption_type": o["exemption_type"],
        "certificate_number": o["certificate_number"],
        "effective_date": o["effective_date"],
        "expiry_date": o["expiry_date"],
    }
    return ser_common(o, out)


def ser_remittance(o):
    out = {
        "taxpayer_id": o["taxpayer_id"],
        "applied_return_id": o["applied_return_id"],
        "remittance_type": o["remittance_type"],
        "amount_cents": o["amount_cents"],
        "applied_amount_cents": o["applied_amount_cents"],
        "unapplied_amount_cents": o["amount_cents"] - o["applied_amount_cents"],
        "received_at": fmt_ts(o["received_at"]),
    }
    return ser_common(o, out)


def ser_audit(o):
    out = {
        "taxpayer_id": o["taxpayer_id"],
        "audit_type": o["audit_type"],
        "period_key": o["period_key"],
        "gross_receipts_cents": o["gross_receipts_cents"],
        "nexus_established": o["nexus_established"],
        "status": o["status"],
        "opened_by_user_id": o["opened_by_user_id"],
        "closed_at": fmt_ts(o["closed_at"]),
    }
    return ser_common(o, out)


def ser_assessment(o):
    out = {
        "taxpayer_id": o["taxpayer_id"],
        "audit_id": o["audit_id"],
        "return_id": o["return_id"],
        "assessment_type": o["assessment_type"],
        "tax_deficiency_cents": o["tax_deficiency_cents"],
        "original_due_date": o["original_due_date"],
        "penalty_cents": o["penalty_cents"],
        "interest_cents": o["interest_cents"],
        "total_due_cents": o["total_due_cents"],
        "status": o["status"],
        "issued_by_user_id": o["issued_by_user_id"],
        "issued_at": fmt_ts(o["issued_at"]),
    }
    return ser_common(o, out)


def ser_appeal(o):
    out = {
        "assessment_id": o["assessment_id"],
        "grounds": o["grounds"],
        "status": o["status"],
        "info_request_note": o["info_request_note"],
        "filed_at": fmt_ts(o["filed_at"]),
        "decided_by_user_id": o["decided_by_user_id"],
        "decided_at": fmt_ts(o["decided_at"]),
    }
    return ser_common(o, out)


def ser_refund(o):
    out = {
        "taxpayer_id": o["taxpayer_id"],
        "return_id": o["return_id"],
        "claim_amount_cents": o["claim_amount_cents"],
        "reason": o["reason"],
        "overpayment_date": o["overpayment_date"],
        "status": o["status"],
        "interest_cents": o["interest_cents"],
        "refund_total_cents": o["refund_total_cents"],
        "approved_at": fmt_ts(o["approved_at"]),
    }
    return ser_common(o, out)


# ---------------------------------------------------------------------------
# Lookup helpers (existence)
# ---------------------------------------------------------------------------
def get_or_404(store, oid, error_id):
    obj = db[store].get(oid)
    if obj is None:
        raise ApiError(error_id, 404, "%s not found" % oid)
    return obj


def owner_of_appeal(appeal):
    assessment = db["assessments"].get(appeal["assessment_id"])
    return assessment["taxpayer_id"] if assessment else None


def enforce_owner(role, uid, owner_taxpayer_id):
    """When acting as Taxpayer, the resource must be owned by the caller."""
    if role == "Taxpayer" and owner_taxpayer_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not the owner of this resource")


# ===========================================================================
# JURISDICTIONS
# ===========================================================================
@app.route("/tax/jurisdictions", methods=["POST"])
def create_jurisdiction():
    require(["TaxAdmin"])
    body = get_body()
    require_fields(body, ["code", "name", "rate_bps"])
    if not isinstance(body["code"], str) or not isinstance(body["name"], str):
        raise ApiError("ERR_VALIDATION", 400, "code/name must be strings")
    rate = body["rate_bps"]
    if not is_int(rate) or rate < 0:
        raise ApiError("ERR_VALIDATION", 400, "rate_bps must be >= 0")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise ApiError("ERR_VALIDATION", 400, "active must be boolean")
    for j in db["jurisdictions"].values():
        if j["code"] == body["code"]:
            raise ApiError("ERR_DUPLICATE_JURISDICTION", 409, "Duplicate jurisdiction code")
    obj = new_common()
    obj.update({"code": body["code"], "name": body["name"], "rate_bps": rate, "active": active})
    db["jurisdictions"][obj["id"]] = obj
    return ok(ser_jurisdiction(obj), 201)


@app.route("/tax/jurisdictions/<oid>", methods=["GET"])
def get_jurisdiction(oid):
    require(READ_ROLES)
    obj = get_or_404("jurisdictions", oid, "ERR_JURISDICTION_NOT_FOUND")
    return ok(ser_jurisdiction(obj), 200)


@app.route("/tax/jurisdictions", methods=["GET"])
def list_jurisdictions():
    require(READ_ROLES)
    items = list(db["jurisdictions"].values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [j for j in items if j["active"] == want]
    return list_response(items, ser_jurisdiction)


# ===========================================================================
# TAXPAYERS
# ===========================================================================
@app.route("/tax/taxpayers", methods=["POST"])
def create_taxpayer():
    # Public registration — no auth required.
    body = get_body()
    require_fields(body, ["legal_name", "entity_type", "email", "filing_frequency"])
    if not isinstance(body["legal_name"], str) or not isinstance(body["email"], str):
        raise ApiError("ERR_VALIDATION", 400, "legal_name/email must be strings")
    require_enum(body, "entity_type", ENTITY_TYPES)
    require_enum(body, "filing_frequency", FILING_FREQS)
    obj = new_common()
    obj.update({
        "legal_name": body["legal_name"],
        "entity_type": body["entity_type"],
        "email": body["email"],
        "filing_frequency": body["filing_frequency"],
        "account_status": "PENDING",
        "nexus_status": "NONE",
        "suspend_reason": None,
        "activated_at": None,
    })
    db["taxpayers"][obj["id"]] = obj
    return ok(ser_taxpayer(obj), 201)


@app.route("/tax/taxpayers/<oid>", methods=["GET"])
def get_taxpayer(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("taxpayers", oid, "ERR_TAXPAYER_NOT_FOUND")
    enforce_owner(role, uid, obj["id"])
    return ok(ser_taxpayer(obj), 200)


@app.route("/tax/taxpayers", methods=["GET"])
def list_taxpayers():
    require(["TaxAdmin", "TaxAuditor", "AppealsOfficer"])
    items = list(db["taxpayers"].values())
    status = request.args.get("account_status")
    if status is not None:
        items = [t for t in items if t["account_status"] == status]
    return list_response(items, ser_taxpayer)


@app.route("/tax/taxpayers/<oid>/activate", methods=["POST"])
def activate_taxpayer(oid):
    require(["TaxAdmin"])
    obj = get_or_404("taxpayers", oid, "ERR_TAXPAYER_NOT_FOUND")
    st = obj["account_status"]
    if st == "PENDING":
        obj["account_status"] = "ACTIVE"
        obj["activated_at"] = now_dt()
    elif st == "SUSPENDED":
        obj["account_status"] = "ACTIVE"
        obj["suspend_reason"] = None
    else:
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not in PENDING/SUSPENDED")
    touch(obj)
    return ok(ser_taxpayer(obj), 200)


@app.route("/tax/taxpayers/<oid>/suspend", methods=["POST"])
def suspend_taxpayer(oid):
    require(["TaxAdmin"])
    body = get_body()
    require_fields(body, ["suspend_reason"])
    if not isinstance(body["suspend_reason"], str):
        raise ApiError("ERR_VALIDATION", 400, "suspend_reason must be a string")
    obj = get_or_404("taxpayers", oid, "ERR_TAXPAYER_NOT_FOUND")
    if obj["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not ACTIVE")
    obj["account_status"] = "SUSPENDED"
    obj["suspend_reason"] = body["suspend_reason"]
    touch(obj)
    return ok(ser_taxpayer(obj), 200)


# ===========================================================================
# RETURNS
# ===========================================================================
def validate_lines(lines):
    if not isinstance(lines, list):
        raise ApiError("ERR_VALIDATION", 400, "lines must be an array")
    clean = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError("ERR_VALIDATION", 400, "line must be an object")
        for f in ("jurisdiction_id", "gross_sales_cents", "exempt_sales_cents", "deduction_cents"):
            if f not in ln or ln[f] is None:
                raise ApiError("ERR_VALIDATION", 400, "line missing %s" % f)
        for f in ("gross_sales_cents", "exempt_sales_cents", "deduction_cents"):
            if not is_int(ln[f]) or ln[f] < 0:
                raise ApiError("ERR_VALIDATION", 400, "line %s must be non-negative integer" % f)
        clean.append({
            "jurisdiction_id": ln["jurisdiction_id"],
            "gross_sales_cents": ln["gross_sales_cents"],
            "exempt_sales_cents": ln["exempt_sales_cents"],
            "deduction_cents": ln["deduction_cents"],
            "rate_bps": None,
            "taxable_cents": None,
            "line_tax_cents": None,
        })
    return clean


def validate_line_jurisdictions(lines):
    for ln in lines:
        j = db["jurisdictions"].get(ln["jurisdiction_id"])
        if j is None or not j["active"]:
            raise ApiError("ERR_JURISDICTION_NOT_FOUND", 404, "Jurisdiction not found or inactive")


@app.route("/tax/returns", methods=["POST"])
def create_return():
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["taxpayer_id", "period_key", "period_start_date",
                          "period_end_date", "filing_due_date", "lines"])
    lines = validate_lines(body["lines"])
    for f in ("period_start_date", "period_end_date", "filing_due_date"):
        try:
            parse_date(body[f])
        except Exception:
            raise ApiError("ERR_VALIDATION", 400, "%s must be an ISO date" % f)
    enforce_owner(role, uid, body["taxpayer_id"])
    # existence (left-to-right): taxpayer, then certificate, then jurisdictions
    get_or_404("taxpayers", body["taxpayer_id"], "ERR_TAXPAYER_NOT_FOUND")
    cert_id = body.get("exemption_certificate_id")
    cert = None
    if cert_id is not None:
        cert = get_or_404("certificates", cert_id, "ERR_CERTIFICATE_NOT_FOUND")
    validate_line_jurisdictions(lines)

    p_start = parse_date(body["period_start_date"])
    p_end = parse_date(body["period_end_date"])
    # period overlap (closed interval) against same taxpayer's returns
    for r in db["returns"].values():
        if r["taxpayer_id"] != body["taxpayer_id"]:
            continue
        rs = parse_date(r["period_start_date"])
        re = parse_date(r["period_end_date"])
        if p_start <= re and rs <= p_end:
            raise ApiError("ERR_PERIOD_OVERLAP", 409, "Period overlaps an existing return")

    # certificate owner then validity
    if cert is not None:
        if cert["taxpayer_id"] != body["taxpayer_id"]:
            raise ApiError("ERR_CERTIFICATE_OWNER_MISMATCH", 409, "Certificate owner mismatch")
        eff = parse_date(cert["effective_date"])
        exp = parse_date(cert["expiry_date"])
        if not (eff <= p_end < exp):
            raise ApiError("ERR_CERTIFICATE_EXPIRED", 409, "Certificate not valid at period_end_date")

    obj = new_common()
    obj.update({
        "taxpayer_id": body["taxpayer_id"],
        "exemption_certificate_id": cert_id,
        "period_key": body["period_key"],
        "period_start_date": body["period_start_date"],
        "period_end_date": body["period_end_date"],
        "filing_due_date": body["filing_due_date"],
        "lines": lines,
        "status": "DRAFT",
        "filed_at": None,
        "total_taxable_cents": None,
        "tax_due_cents": None,
        "vendor_discount_cents": None,
        "net_return_due_cents": None,
    })
    db["returns"][obj["id"]] = obj
    return ok(ser_return(obj), 201)


@app.route("/tax/returns/<oid>", methods=["GET"])
def get_return(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("returns", oid, "ERR_RETURN_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    return ok(ser_return(obj), 200)


@app.route("/tax/returns", methods=["GET"])
def list_returns():
    uid, role = require(READ_ROLES)
    items = list(db["returns"].values())
    if role == "Taxpayer":
        items = [r for r in items if r["taxpayer_id"] == uid]
    for key in ("taxpayer_id", "exemption_certificate_id", "status", "period_key"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r.get(key) == v]
    return list_response(items, ser_return)


def compute_return_tax(ret):
    total_taxable = 0
    tax_due = 0
    for ln in ret["lines"]:
        j = db["jurisdictions"].get(ln["jurisdiction_id"])
        rate = j["rate_bps"] if j else 0
        taxable = max(0, ln["gross_sales_cents"] - ln["exempt_sales_cents"] - ln["deduction_cents"])
        line_tax = rhu_div(taxable * rate, 10000)
        ln["rate_bps"] = rate
        ln["taxable_cents"] = taxable
        ln["line_tax_cents"] = line_tax
        total_taxable += taxable
        tax_due += line_tax
    ret["total_taxable_cents"] = total_taxable
    ret["tax_due_cents"] = tax_due


def compute_vendor_discount(ret, taxpayer):
    timely = clock_date() <= parse_date(ret["filing_due_date"])
    if timely and taxpayer["account_status"] == "ACTIVE":
        disc = min(rhu_div(ret["tax_due_cents"] * VENDOR_DISCOUNT_BPS, 10000),
                   VENDOR_DISCOUNT_CAP_CENTS)
    else:
        disc = 0
    ret["vendor_discount_cents"] = disc
    ret["net_return_due_cents"] = ret["tax_due_cents"] - disc


@app.route("/tax/returns/<oid>/file", methods=["POST"])
def file_return(oid):
    uid, role = require(["Taxpayer"])
    obj = get_or_404("returns", oid, "ERR_RETURN_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    if obj["status"] not in ("DRAFT", "AMENDING"):
        raise ApiError("ERR_RETURN_NOT_DRAFT", 409, "Return not in DRAFT/AMENDING")
    taxpayer = db["taxpayers"].get(obj["taxpayer_id"])
    if not taxpayer or taxpayer["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Owning taxpayer not ACTIVE")
    compute_return_tax(obj)
    compute_vendor_discount(obj, taxpayer)
    obj["status"] = "FILED"
    obj["filed_at"] = now_dt()
    touch(obj)
    return ok(ser_return(obj), 200)


@app.route("/tax/returns/<oid>/amend", methods=["POST"])
def amend_return(oid):
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["expected_return_version", "lines"])
    if not is_int(body["expected_return_version"]):
        raise ApiError("ERR_VALIDATION", 400, "expected_return_version must be an integer")
    lines = validate_lines(body["lines"])
    obj = get_or_404("returns", oid, "ERR_RETURN_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    if obj["status"] != "FILED":
        raise ApiError("ERR_RETURN_NOT_FILED", 409, "Return not FILED")
    if body["expected_return_version"] != obj["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_return_version mismatch")
    # no OPEN audit for same taxpayer + period_key
    for a in db["audits"].values():
        if (a["taxpayer_id"] == obj["taxpayer_id"] and a["period_key"] == obj["period_key"]
                and a["status"] == "OPEN"):
            raise ApiError("ERR_AUDIT_OPEN_ON_PERIOD", 409, "Open audit on this period")
    validate_line_jurisdictions(lines)
    obj["lines"] = lines
    obj["status"] = "AMENDING"
    # cascade: un-apply remittances applied to this return
    for m in db["remittances"].values():
        if m["applied_return_id"] == obj["id"]:
            m["applied_amount_cents"] = 0
            m["applied_return_id"] = None
            touch(m)
    touch(obj)
    return ok(ser_return(obj), 200)


# ===========================================================================
# EXEMPTION CERTIFICATES
# ===========================================================================
@app.route("/tax/exemption-certificates", methods=["POST"])
def create_certificate():
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["taxpayer_id", "exemption_type", "certificate_number",
                          "effective_date", "expiry_date"])
    require_enum(body, "exemption_type", EXEMPTION_TYPES)
    for f in ("effective_date", "expiry_date"):
        try:
            parse_date(body[f])
        except Exception:
            raise ApiError("ERR_VALIDATION", 400, "%s must be an ISO date" % f)
    enforce_owner(role, uid, body["taxpayer_id"])
    get_or_404("taxpayers", body["taxpayer_id"], "ERR_TAXPAYER_NOT_FOUND")
    eff = parse_date(body["effective_date"])
    exp = parse_date(body["expiry_date"])
    for c in db["certificates"].values():
        if c["taxpayer_id"] != body["taxpayer_id"] or c["exemption_type"] != body["exemption_type"]:
            continue
        ceff = parse_date(c["effective_date"])
        cexp = parse_date(c["expiry_date"])
        # half-open overlap
        if eff < cexp and ceff < exp:
            raise ApiError("ERR_CERTIFICATE_OVERLAP", 409, "Certificate validity overlap")
    obj = new_common()
    obj.update({
        "taxpayer_id": body["taxpayer_id"],
        "exemption_type": body["exemption_type"],
        "certificate_number": body["certificate_number"],
        "effective_date": body["effective_date"],
        "expiry_date": body["expiry_date"],
    })
    db["certificates"][obj["id"]] = obj
    return ok(ser_certificate(obj), 201)


@app.route("/tax/exemption-certificates/<oid>", methods=["GET"])
def get_certificate(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("certificates", oid, "ERR_CERTIFICATE_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    return ok(ser_certificate(obj), 200)


@app.route("/tax/exemption-certificates", methods=["GET"])
def list_certificates():
    uid, role = require(READ_ROLES)
    items = list(db["certificates"].values())
    if role == "Taxpayer":
        items = [c for c in items if c["taxpayer_id"] == uid]
    for key in ("taxpayer_id", "exemption_type"):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if c.get(key) == v]
    return list_response(items, ser_certificate)


# ===========================================================================
# REMITTANCES
# ===========================================================================
@app.route("/tax/remittances", methods=["POST"])
def create_remittance():
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["taxpayer_id", "remittance_type", "amount_cents"])
    require_enum(body, "remittance_type", REMITTANCE_TYPES)
    require_pos_int(body, "amount_cents")
    enforce_owner(role, uid, body["taxpayer_id"])
    get_or_404("taxpayers", body["taxpayer_id"], "ERR_TAXPAYER_NOT_FOUND")
    obj = new_common()
    obj.update({
        "taxpayer_id": body["taxpayer_id"],
        "applied_return_id": None,
        "remittance_type": body["remittance_type"],
        "amount_cents": body["amount_cents"],
        "applied_amount_cents": 0,
        "received_at": now_dt(),
    })
    db["remittances"][obj["id"]] = obj
    return ok(ser_remittance(obj), 201)


@app.route("/tax/remittances/<oid>", methods=["GET"])
def get_remittance(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("remittances", oid, "ERR_REMITTANCE_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    return ok(ser_remittance(obj), 200)


@app.route("/tax/remittances", methods=["GET"])
def list_remittances():
    uid, role = require(READ_ROLES)
    items = list(db["remittances"].values())
    if role == "Taxpayer":
        items = [m for m in items if m["taxpayer_id"] == uid]
    for key in ("taxpayer_id", "applied_return_id", "remittance_type"):
        v = request.args.get(key)
        if v is not None:
            items = [m for m in items if m.get(key) == v]
    return list_response(items, ser_remittance)


@app.route("/tax/remittances/<oid>/apply", methods=["POST"])
def apply_remittance(oid):
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["applied_return_id", "apply_amount_cents"])
    require_pos_int(body, "apply_amount_cents")
    obj = get_or_404("remittances", oid, "ERR_REMITTANCE_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    target = get_or_404("returns", body["applied_return_id"], "ERR_RETURN_NOT_FOUND")
    if target["status"] != "FILED":
        raise ApiError("ERR_RETURN_NOT_FILED", 409, "Target return not FILED")
    request_amt = body["apply_amount_cents"]
    unapplied = obj["amount_cents"] - obj["applied_amount_cents"]
    already = sum(m["applied_amount_cents"] for m in db["remittances"].values()
                  if m["applied_return_id"] == target["id"] and m["id"] != obj["id"])
    room = (target["net_return_due_cents"] or 0) - already
    if request_amt > unapplied or request_amt > room:
        raise ApiError("ERR_OVERAPPLICATION", 422, "Applied amount exceeds available room")
    obj["applied_amount_cents"] += request_amt
    obj["applied_return_id"] = target["id"]
    touch(obj)
    return ok(ser_remittance(obj), 200)


# ===========================================================================
# AUDITS
# ===========================================================================
@app.route("/tax/audits", methods=["POST"])
def create_audit():
    uid, role = require(["TaxAuditor"])
    body = get_body()
    require_fields(body, ["taxpayer_id", "audit_type", "period_key"])
    require_enum(body, "audit_type", AUDIT_TYPES)
    gross = body.get("gross_receipts_cents")
    nexus_established = None
    if body["audit_type"] == "NEXUS_DISCOVERY":
        if not is_int(gross) or gross < 0:
            raise ApiError("ERR_VALIDATION", 400, "gross_receipts_cents required for NEXUS_DISCOVERY")
        nexus_established = gross >= NEXUS_THRESHOLD_CENTS
    else:
        if gross is not None and not is_int(gross):
            raise ApiError("ERR_VALIDATION", 400, "gross_receipts_cents must be integer")
    get_or_404("taxpayers", body["taxpayer_id"], "ERR_TAXPAYER_NOT_FOUND")
    obj = new_common()
    obj.update({
        "taxpayer_id": body["taxpayer_id"],
        "audit_type": body["audit_type"],
        "period_key": body["period_key"],
        "gross_receipts_cents": gross,
        "nexus_established": nexus_established,
        "status": "OPEN",
        "opened_by_user_id": uid,
        "closed_at": None,
    })
    db["audits"][obj["id"]] = obj
    return ok(ser_audit(obj), 201)


@app.route("/tax/audits/<oid>", methods=["GET"])
def get_audit(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("audits", oid, "ERR_AUDIT_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    return ok(ser_audit(obj), 200)


@app.route("/tax/audits", methods=["GET"])
def list_audits():
    uid, role = require(READ_ROLES)
    items = list(db["audits"].values())
    if role == "Taxpayer":
        items = [a for a in items if a["taxpayer_id"] == uid]
    for key in ("taxpayer_id", "status", "audit_type"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a.get(key) == v]
    return list_response(items, ser_audit)


def compute_assessment_penalty_interest(assessment):
    base = assessment["tax_deficiency_cents"]
    due = parse_date(assessment["original_due_date"])
    issued_d = assessment["issued_at"].astimezone(timezone.utc).date()
    months_late = (issued_d - due).days // 30
    if assessment["assessment_type"] == "AUDIT_DEFICIENCY":
        penalty = rhu_div(base * NEGLIGENCE_PENALTY_BPS, 10000)
    else:
        penalty = min(rhu_div(base * LATE_FILING_PENALTY_BPS, 10000),
                      LATE_FILING_PENALTY_CAP_CENTS)
    interest = rhu_div((base + penalty) * MONTHLY_INTEREST_BPS * months_late, 10000)
    assessment["penalty_cents"] = penalty
    assessment["interest_cents"] = interest
    assessment["total_due_cents"] = base + penalty + interest


def void_open_refunds_for_return(return_id):
    for f in db["refunds"].values():
        if f["return_id"] == return_id and f["status"] == "OPEN":
            f["status"] = "VOIDED"
            touch(f)


@app.route("/tax/audits/<oid>/close", methods=["POST"])
def close_audit(oid):
    uid, role = require(["TaxAuditor"])
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("ASSESSED", "NO_CHANGE"):
        raise ApiError("ERR_VALIDATION", 400, "outcome must be ASSESSED or NO_CHANGE")
    if outcome == "ASSESSED":
        tdef = body.get("tax_deficiency_cents")
        if not is_int(tdef) or tdef <= 0:
            raise ApiError("ERR_VALIDATION", 400, "tax_deficiency_cents must be > 0")
        if not body.get("original_due_date"):
            raise ApiError("ERR_VALIDATION", 400, "original_due_date required")
        try:
            parse_date(body["original_due_date"])
        except Exception:
            raise ApiError("ERR_VALIDATION", 400, "original_due_date must be an ISO date")
    obj = get_or_404("audits", oid, "ERR_AUDIT_NOT_FOUND")
    if obj["status"] != "OPEN":
        raise ApiError("ERR_AUDIT_NOT_OPEN", 409, "Audit not OPEN")

    if outcome == "NO_CHANGE":
        obj["status"] = "CLOSED_NO_CHANGE"
        obj["closed_at"] = now_dt()
        if obj["audit_type"] == "NEXUS_DISCOVERY" and obj["nexus_established"]:
            tp = db["taxpayers"].get(obj["taxpayer_id"])
            if tp:
                tp["nexus_status"] = "ESTABLISHED"
                touch(tp)
        touch(obj)
        return ok(ser_audit(obj), 200)

    # outcome == ASSESSED
    return_id = body.get("return_id")
    ret = None
    if return_id is not None:
        ret = get_or_404("returns", return_id, "ERR_RETURN_NOT_FOUND")
    # link 1: create ISSUED Assessment
    assessment = new_common()
    assessment.update({
        "taxpayer_id": obj["taxpayer_id"],
        "audit_id": obj["id"],
        "return_id": return_id,
        "assessment_type": "AUDIT_DEFICIENCY",
        "tax_deficiency_cents": body["tax_deficiency_cents"],
        "original_due_date": body["original_due_date"],
        "penalty_cents": None,
        "interest_cents": None,
        "total_due_cents": None,
        "status": "ISSUED",
        "issued_by_user_id": obj["opened_by_user_id"],
        "issued_at": now_dt(),
    })
    compute_assessment_penalty_interest(assessment)
    db["assessments"][assessment["id"]] = assessment
    # link 2/3: drive return FILED -> ASSESSED, void OPEN refunds on it
    if ret is not None and ret["status"] == "FILED":
        ret["status"] = "ASSESSED"
        touch(ret)
        void_open_refunds_for_return(ret["id"])
    obj["status"] = "CLOSED_ASSESSED"
    obj["closed_at"] = now_dt()
    touch(obj)
    return ok(ser_audit(obj), 200)


# ===========================================================================
# ASSESSMENTS
# ===========================================================================
@app.route("/tax/assessments", methods=["POST"])
def create_assessment():
    uid, role = require(["TaxAuditor"])
    body = get_body()
    require_fields(body, ["taxpayer_id", "assessment_type", "tax_deficiency_cents",
                          "original_due_date"])
    require_enum(body, "assessment_type", ASSESSMENT_TYPES)
    require_pos_int(body, "tax_deficiency_cents")
    try:
        parse_date(body["original_due_date"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "original_due_date must be an ISO date")
    get_or_404("taxpayers", body["taxpayer_id"], "ERR_TAXPAYER_NOT_FOUND")
    return_id = body.get("return_id")
    if return_id is not None:
        get_or_404("returns", return_id, "ERR_RETURN_NOT_FOUND")
    obj = new_common()
    obj.update({
        "taxpayer_id": body["taxpayer_id"],
        "audit_id": None,
        "return_id": return_id,
        "assessment_type": body["assessment_type"],
        "tax_deficiency_cents": body["tax_deficiency_cents"],
        "original_due_date": body["original_due_date"],
        "penalty_cents": None,
        "interest_cents": None,
        "total_due_cents": None,
        "status": "ISSUED",
        "issued_by_user_id": uid,
        "issued_at": now_dt(),
    })
    compute_assessment_penalty_interest(obj)
    db["assessments"][obj["id"]] = obj
    return ok(ser_assessment(obj), 201)


@app.route("/tax/assessments/<oid>", methods=["GET"])
def get_assessment(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("assessments", oid, "ERR_ASSESSMENT_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    return ok(ser_assessment(obj), 200)


@app.route("/tax/assessments", methods=["GET"])
def list_assessments():
    uid, role = require(READ_ROLES)
    items = list(db["assessments"].values())
    if role == "Taxpayer":
        items = [a for a in items if a["taxpayer_id"] == uid]
    for key in ("taxpayer_id", "audit_id", "return_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a.get(key) == v]
    return list_response(items, ser_assessment)


# ===========================================================================
# APPEALS
# ===========================================================================
@app.route("/tax/appeals", methods=["POST"])
def create_appeal():
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["assessment_id", "grounds"])
    assessment = get_or_404("assessments", body["assessment_id"], "ERR_ASSESSMENT_NOT_FOUND")
    enforce_owner(role, uid, assessment["taxpayer_id"])
    if assessment["status"] != "ISSUED":
        raise ApiError("ERR_ASSESSMENT_NOT_ISSUED", 409, "Assessment not ISSUED")
    issued_d = assessment["issued_at"].astimezone(timezone.utc).date()
    if (clock_date() - issued_d).days > APPEAL_WINDOW_DAYS:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", 409, "Appeal window closed")
    obj = new_common()
    obj.update({
        "assessment_id": body["assessment_id"],
        "grounds": body["grounds"],
        "status": "SUBMITTED",
        "info_request_note": None,
        "filed_at": now_dt(),
        "decided_by_user_id": None,
        "decided_at": None,
    })
    db["appeals"][obj["id"]] = obj
    return ok(ser_appeal(obj), 201)


@app.route("/tax/appeals/<oid>", methods=["GET"])
def get_appeal(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("appeals", oid, "ERR_APPEAL_NOT_FOUND")
    enforce_owner(role, uid, owner_of_appeal(obj))
    return ok(ser_appeal(obj), 200)


@app.route("/tax/appeals", methods=["GET"])
def list_appeals():
    uid, role = require(READ_ROLES)
    items = list(db["appeals"].values())
    if role == "Taxpayer":
        items = [a for a in items if owner_of_appeal(a) == uid]
    for key in ("assessment_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a.get(key) == v]
    return list_response(items, ser_appeal)


@app.route("/tax/appeals/<oid>/request-info", methods=["POST"])
def request_info_appeal(oid):
    uid, role = require(["AppealsOfficer"])
    body = get_body()
    require_fields(body, ["info_request_note"])
    obj = get_or_404("appeals", oid, "ERR_APPEAL_NOT_FOUND")
    if obj["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_NOT_OPEN", 409, "Appeal not SUBMITTED")
    obj["status"] = "INFO_REQUESTED"
    obj["info_request_note"] = body["info_request_note"]
    touch(obj)
    return ok(ser_appeal(obj), 200)


@app.route("/tax/appeals/<oid>/respond", methods=["POST"])
def respond_appeal(oid):
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["response_note"])
    obj = get_or_404("appeals", oid, "ERR_APPEAL_NOT_FOUND")
    enforce_owner(role, uid, owner_of_appeal(obj))
    if obj["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INFO_NOT_REQUESTED", 409, "Appeal not INFO_REQUESTED")
    obj["status"] = "SUBMITTED"
    touch(obj)
    return ok(ser_appeal(obj), 200)


@app.route("/tax/appeals/<oid>/decide", methods=["POST"])
def decide_appeal(oid):
    uid, role = require(["AppealsOfficer"])
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("ALLOW", "DENY"):
        raise ApiError("ERR_VALIDATION", 400, "outcome must be ALLOW or DENY")
    obj = get_or_404("appeals", oid, "ERR_APPEAL_NOT_FOUND")
    if obj["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_NOT_OPEN", 409, "Appeal not SUBMITTED")
    assessment = db["assessments"].get(obj["assessment_id"])
    if assessment and uid == assessment["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Decider issued the assessment")
    obj["decided_by_user_id"] = uid
    obj["decided_at"] = now_dt()
    if outcome == "ALLOW":
        obj["status"] = "ALLOWED"
        if assessment and assessment["status"] == "ISSUED":
            assessment["status"] = "ABATED"
            touch(assessment)
            rid = assessment.get("return_id")
            if rid:
                ret = db["returns"].get(rid)
                if ret and ret["status"] == "ASSESSED":
                    ret["status"] = "FILED"
                    touch(ret)
    else:
        obj["status"] = "DENIED"
        if assessment and assessment["status"] == "ISSUED":
            assessment["status"] = "AFFIRMED"
            touch(assessment)
    touch(obj)
    return ok(ser_appeal(obj), 200)


# ===========================================================================
# REFUND CLAIMS
# ===========================================================================
@app.route("/tax/refund-claims", methods=["POST"])
def create_refund():
    uid, role = require(["Taxpayer"])
    body = get_body()
    require_fields(body, ["taxpayer_id", "return_id", "claim_amount_cents", "reason",
                          "overpayment_date", "expected_return_version"])
    require_enum(body, "reason", REFUND_REASONS)
    require_pos_int(body, "claim_amount_cents")
    if not is_int(body["expected_return_version"]):
        raise ApiError("ERR_VALIDATION", 400, "expected_return_version must be an integer")
    try:
        parse_date(body["overpayment_date"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "overpayment_date must be an ISO date")
    enforce_owner(role, uid, body["taxpayer_id"])
    get_or_404("taxpayers", body["taxpayer_id"], "ERR_TAXPAYER_NOT_FOUND")
    ret = get_or_404("returns", body["return_id"], "ERR_RETURN_NOT_FOUND")
    if body["expected_return_version"] != ret["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_return_version mismatch")
    # supersede prior OPEN claim for the same return
    for f in db["refunds"].values():
        if f["return_id"] == ret["id"] and f["status"] == "OPEN":
            f["status"] = "SUPERSEDED"
            touch(f)
    # creating a claim advances the return's version
    touch(ret)
    obj = new_common()
    obj.update({
        "taxpayer_id": body["taxpayer_id"],
        "return_id": body["return_id"],
        "claim_amount_cents": body["claim_amount_cents"],
        "reason": body["reason"],
        "overpayment_date": body["overpayment_date"],
        "status": "OPEN",
        "interest_cents": None,
        "refund_total_cents": None,
        "approved_at": None,
    })
    db["refunds"][obj["id"]] = obj
    return ok(ser_refund(obj), 201)


@app.route("/tax/refund-claims/<oid>", methods=["GET"])
def get_refund(oid):
    uid, role = require(READ_ROLES)
    obj = get_or_404("refunds", oid, "ERR_REFUND_NOT_FOUND")
    enforce_owner(role, uid, obj["taxpayer_id"])
    return ok(ser_refund(obj), 200)


@app.route("/tax/refund-claims", methods=["GET"])
def list_refunds():
    uid, role = require(READ_ROLES)
    items = list(db["refunds"].values())
    if role == "Taxpayer":
        items = [f for f in items if f["taxpayer_id"] == uid]
    for key in ("taxpayer_id", "return_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [f for f in items if f.get(key) == v]
    return list_response(items, ser_refund)


def compute_refund_interest(refund):
    principal = refund["claim_amount_cents"]
    approve_d = clock_date()
    if refund["reason"] == "TAXPAYER_ERROR":
        created_d = refund["created_at"].astimezone(timezone.utc).date()
        days_since = (approve_d - created_d).days
        chargeable = max(0, days_since - REFUND_GRACE_DAYS)
        interest = rhu_div(principal * DAILY_INTEREST_BPS * chargeable, 10000)
    else:  # AUDIT_ADJUSTMENT
        over_d = parse_date(refund["overpayment_date"])
        days = (approve_d - over_d).days
        interest = rhu_div(principal * DAILY_INTEREST_BPS * days, 10000)
    refund["interest_cents"] = interest
    refund["refund_total_cents"] = principal + interest


@app.route("/tax/refund-claims/<oid>/approve", methods=["POST"])
def approve_refund(oid):
    uid, role = require(["TaxAdmin"])
    obj = get_or_404("refunds", oid, "ERR_REFUND_NOT_FOUND")
    if obj["status"] != "OPEN":
        raise ApiError("ERR_REFUND_NOT_OPEN", 409, "Refund not OPEN")
    tp = db["taxpayers"].get(obj["taxpayer_id"])
    if tp and tp["account_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Owning taxpayer is SUSPENDED")
    compute_refund_interest(obj)
    obj["status"] = "APPROVED"
    obj["approved_at"] = now_dt()
    touch(obj)
    return ok(ser_refund(obj), 200)


@app.route("/tax/refund-claims/<oid>/deny", methods=["POST"])
def deny_refund(oid):
    uid, role = require(["TaxAdmin"])
    get_body()  # deny_reason optional
    obj = get_or_404("refunds", oid, "ERR_REFUND_NOT_FOUND")
    if obj["status"] != "OPEN":
        raise ApiError("ERR_REFUND_NOT_OPEN", 409, "Refund not OPEN")
    obj["status"] = "DENIED"
    touch(obj)
    return ok(ser_refund(obj), 200)


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["TaxAdmin"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        CLOCK["now"] = parse_instant(body["to_iso8601"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be a valid ISO-8601 instant")
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
