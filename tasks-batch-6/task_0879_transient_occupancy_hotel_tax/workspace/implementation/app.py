"""Transient-Occupancy / Hotel-Tax (TOT) Administration API.

Single-file Flask implementation. In-memory storage only; state is wiped on
every fresh process boot. No entity seeding at startup (only the logical
clock's declared default).
"""
import os
import random
import string
import uuid
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
VALID_ROLES = {"TaxAdmin", "Operator", "Auditor"}


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.operators = {}
        self.properties = {}
        self.ota_platforms = {}
        self.ota_agreements = {}
        self.returns = {}
        self.exemptions = {}
        self.remittances = {}
        self.audits = {}
        self.assessments = {}
        self.appeals = {}
        self.liens = {}
        self.refund_claims = {}
        self.ledger = []            # append-only list of dicts
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


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
def now_dt():
    return db.clock


def iso_millis(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 input datetime string into an aware UTC datetime."""
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def whole_months(anchor_dt, clock_dt):
    days = (clock_dt - anchor_dt).days
    if days < 0:
        return 0
    return days // 30


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_common():
    ts = now_dt()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def mutate(entity):
    entity["updated_at"] = now_dt()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": iso_millis(now_dt()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, is_array=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def paginate(items):
    """items: list of already-serialized dicts. Returns (page, pagination_meta)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def sort_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.before_request
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid user context")
    g.user_id = uid
    g.role = role


def require_roles(*roles):
    if g.role not in roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")


def require_owner(operator_id):
    if g.role == "Operator" and g.user_id != operator_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "Operator does not own resource")


def get_json():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return body


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid %s" % field)


def require_non_negative_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a non-negative integer" % field)


def fetch(store_dict, rid):
    ent = store_dict.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Ledger / balance / reconciliation
# ---------------------------------------------------------------------------
def account_balance(operator_id):
    return sum(e["amount_signed_cents"] for e in db.ledger
               if e["operator_id"] == operator_id)


def post_ledger(operator_id, entry_type, amount_signed, source_ref):
    entry = {
        "id": new_id(),
        "created_at": now_dt(),
        "_seq": db.next_seq(),
        "operator_id": operator_id,
        "entry_type": entry_type,
        "amount_signed_cents": amount_signed,
        "source_ref": source_ref,
    }
    db.ledger.append(entry)
    op = db.operators.get(operator_id)
    if op is not None:
        mutate(op)  # balance (a derived field) changed -> version bump
    return entry


def audit_operator_id(assessment):
    audit = db.audits.get(assessment["audit_id"])
    return audit["operator_id"] if audit else None


def has_delinquency_trigger(op):
    oid = op["id"]
    clock = now_dt()
    for r in db.returns.values():
        if (r["operator_id"] == oid
                and r["filing_status"] in ("FILED", "AMENDED")
                and clock > r["due_date"]
                and r["settlement_status"] != "PAID"):
            return True
    for a in db.assessments.values():
        if audit_operator_id(a) == oid and a["status"] in ("ISSUED", "FINAL"):
            return True
    return False


def reconcile_operator(op):
    bal = account_balance(op["id"])
    if op["status"] == "ACTIVE":
        if bal > 0 and has_delinquency_trigger(op):
            op["status"] = "DELINQUENT"
            mutate(op)
    elif op["status"] == "DELINQUENT":
        if bal <= 0:
            op["status"] = "ACTIVE"
            mutate(op)
            for lien in db.liens.values():
                if lien["operator_id"] == op["id"] and lien["status"] == "RECORDED":
                    lien["status"] = "RELEASED"
                    mutate(lien)
    if bal <= 0:
        for a in db.assessments.values():
            if audit_operator_id(a) == op["id"] and a["status"] in ("ISSUED", "FINAL"):
                a["status"] = "SETTLED"
                mutate(a)


# ---------------------------------------------------------------------------
# Tax / settlement computation
# ---------------------------------------------------------------------------
def honored_exemption_total(ret):
    total = 0
    for ex in db.exemptions.values():
        if ex["tax_return_id"] == ret["id"] and ex["status"] in ("CLAIMED", "VERIFIED"):
            total += ex["amount_cents"]
    return total


def compute_tax(ret, bps):
    """Return (tax, exempt_total, gross) using per-line-then-sum rounding.

    Honored exemptions (STANDARD self-report set) are allocated sequentially
    across the lines since exemption claims carry no property_id.
    """
    gross = sum(li["gross_receipts_cents"] for li in ret["line_items"])
    exempt = honored_exemption_total(ret)
    remaining = exempt
    tax = 0
    for li in ret["line_items"]:
        lg = li["gross_receipts_cents"]
        alloc = min(remaining, lg)
        remaining -= alloc
        taxable_line = lg - alloc
        tax += round_half_up(Decimal(taxable_line) * Decimal(bps) / Decimal(10000))
    return tax, exempt, gross


def return_total_due(ret):
    return ret["tax_due_cents"] + ret["penalty_cents"] + ret["interest_cents"]


def return_amount_paid(ret):
    return sum(r["amount_cents"] for r in db.remittances.values()
               if r["tax_return_id"] == ret["id"] and r["status"] == "CLEARED")


def recompute_settlement(ret):
    paid = return_amount_paid(ret)
    total_due = return_total_due(ret)
    if paid <= 0:
        new = "UNPAID"
    elif paid < total_due:
        new = "PARTIAL"
    else:
        new = "PAID"
    if new != ret["settlement_status"]:
        ret["settlement_status"] = new
        mutate(ret)


def compute_penalty_interest(base, due_date, jur):
    months_late = whole_months(due_date, now_dt())
    if months_late <= 0:
        return 0, 0
    rate = Decimal("0.10") + Decimal("0.05") * (months_late - 1)
    if rate > Decimal("0.25"):
        rate = Decimal("0.25")
    penalty = round_half_up(Decimal(base) * rate)
    interest = round_half_up(
        Decimal(base) * Decimal(jur["interest_rate_monthly_bps"]) / Decimal(10000) * months_late
    )
    return penalty, interest


def operator_jurisdiction(op):
    return db.jurisdictions[op["jurisdiction_id"]]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def common_out(ent):
    return {
        "id": ent["id"],
        "created_at": iso_millis(ent["created_at"]),
        "updated_at": iso_millis(ent["updated_at"]),
        "version": ent["version"],
    }


def ser_jurisdiction(j):
    o = common_out(j)
    o.update({
        "name": j["name"],
        "tax_rate_bps": j["tax_rate_bps"],
        "interest_rate_monthly_bps": j["interest_rate_monthly_bps"],
        "refund_interest_monthly_bps": j["refund_interest_monthly_bps"],
        "lien_threshold_cents": j["lien_threshold_cents"],
        "exemption_min_stay_nights": j["exemption_min_stay_nights"],
    })
    return o


def ser_operator(op):
    o = common_out(op)
    o.update({
        "jurisdiction_id": op["jurisdiction_id"],
        "legal_name": op["legal_name"],
        "filing_frequency": op["filing_frequency"],
        "certificate_number": op["certificate_number"],
        "status": op["status"],
        "account_balance_cents": account_balance(op["id"]),
    })
    return o


def ser_property(p):
    o = common_out(p)
    o.update({
        "operator_id": p["operator_id"],
        "name": p["name"],
        "address": p["address"],
        "active": p["active"],
    })
    return o


def ser_platform(p):
    o = common_out(p)
    o.update({"name": p["name"], "registered": p["registered"]})
    return o


def ser_agreement(a):
    o = common_out(a)
    o.update({
        "operator_id": a["operator_id"],
        "platform_id": a["platform_id"],
        "collection_method": a["collection_method"],
        "effective_date": a["effective_date"],
        "end_date": a["end_date"],
        "status": a["status"],
    })
    return o


def ser_return(r):
    o = common_out(r)
    o.update({
        "operator_id": r["operator_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "reporting_method": r["reporting_method"],
        "line_items": r["line_items"],
        "gross_receipts_cents": r["gross_receipts_cents"],
        "exempt_receipts_cents": r["exempt_receipts_cents"],
        "taxable_receipts_cents": r["taxable_receipts_cents"],
        "tax_due_cents": r["tax_due_cents"],
        "penalty_cents": r["penalty_cents"],
        "interest_cents": r["interest_cents"],
        "total_due_cents": return_total_due(r),
        "amount_paid_cents": return_amount_paid(r),
        "due_date": iso_millis(r["due_date"]),
        "filed_at": iso_millis(r["filed_at"]),
        "filing_status": r["filing_status"],
        "settlement_status": r["settlement_status"],
    })
    return o


def ser_exemption(e):
    o = common_out(e)
    o.update({
        "tax_return_id": e["tax_return_id"],
        "exemption_type": e["exemption_type"],
        "guest_ref": e["guest_ref"],
        "stay_nights": e["stay_nights"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
    })
    return o


def ser_remittance(r):
    o = common_out(r)
    o.update({
        "tax_return_id": r["tax_return_id"],
        "ota_agreement_id": r["ota_agreement_id"],
        "remitter": r["remitter"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return o


def ser_audit(a):
    o = common_out(a)
    o.update({
        "operator_id": a["operator_id"],
        "period_start": a["period_start"],
        "period_end": a["period_end"],
        "classification": a["classification"],
        "status": a["status"],
    })
    return o


def ser_assessment(a):
    o = common_out(a)
    o.update({
        "audit_id": a["audit_id"],
        "audited_taxable_cents": a["audited_taxable_cents"],
        "assessed_tax_cents": a["assessed_tax_cents"],
        "self_reported_tax_cents": a["self_reported_tax_cents"],
        "deficiency_cents": a["deficiency_cents"],
        "penalty_cents": a["penalty_cents"],
        "interest_cents": a["interest_cents"],
        "total_assessed_cents": a["total_assessed_cents"],
        "status": a["status"],
    })
    return o


def ser_appeal(a):
    o = common_out(a)
    o.update({
        "assessment_id": a["assessment_id"],
        "grounds": a["grounds"],
        "round_count": a["round_count"],
        "decision": a["decision"],
        "reduced_total_cents": a["reduced_total_cents"],
        "status": a["status"],
    })
    return o


def ser_lien(l):
    o = common_out(l)
    o.update({
        "operator_id": l["operator_id"],
        "amount_cents": l["amount_cents"],
        "status": l["status"],
        "recorded_at": iso_millis(l["recorded_at"]),
    })
    return o


def ser_refund(rc):
    o = common_out(rc)
    o.update({
        "operator_id": rc["operator_id"],
        "tax_return_id": rc["tax_return_id"],
        "reason": rc["reason"],
        "principal_cents": rc["principal_cents"],
        "overpayment_date": rc["overpayment_date"],
        "interest_cents": rc["interest_cents"],
        "total_refund_cents": rc["total_refund_cents"],
        "status": rc["status"],
    })
    return o


def ser_ledger(e):
    return {
        "id": e["id"],
        "created_at": iso_millis(e["created_at"]),
        "operator_id": e["operator_id"],
        "entry_type": e["entry_type"],
        "amount_signed_cents": e["amount_signed_cents"],
        "source_ref": e["source_ref"],
    }


# ---------------------------------------------------------------------------
# Overlap helpers
# ---------------------------------------------------------------------------
def periods_overlap_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    # a_end / b_end may be None (open-ended = +inf)
    if a_end is not None and a_start >= a_end:
        pass
    left = a_start if (b_end is None or a_start < b_end) else None
    a_before_b_end = (b_end is None) or (a_start < b_end)
    b_before_a_end = (a_end is None) or (b_start < a_end)
    return a_before_b_end and b_before_a_end


# ===========================================================================
# Jurisdiction
# ===========================================================================
@app.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    require_roles("TaxAdmin")
    body = get_json()
    require_fields(body, "name", "tax_rate_bps")
    require_non_negative_int(body["tax_rate_bps"], "tax_rate_bps")

    def opt(field, default):
        if field in body and body[field] is not None:
            require_non_negative_int(body[field], field)
            return body[field]
        return default

    j = new_common()
    j.update({
        "name": body["name"],
        "tax_rate_bps": body["tax_rate_bps"],
        "interest_rate_monthly_bps": opt("interest_rate_monthly_bps", 100),
        "refund_interest_monthly_bps": opt("refund_interest_monthly_bps", 50),
        "lien_threshold_cents": opt("lien_threshold_cents", 500000),
        "exemption_min_stay_nights": opt("exemption_min_stay_nights", 30),
    })
    db.jurisdictions[j["id"]] = j
    return ok(ser_jurisdiction(j), 201)


@app.route("/jurisdictions/<jid>", methods=["GET"])
def get_jurisdiction(jid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_jurisdiction(fetch(db.jurisdictions, jid)))


# ===========================================================================
# Operator
# ===========================================================================
@app.route("/operators", methods=["POST"])
def create_operator():
    require_roles("TaxAdmin")
    body = get_json()
    require_fields(body, "jurisdiction_id", "legal_name", "filing_frequency")
    fetch(db.jurisdictions, body["jurisdiction_id"])
    require_enum(body["filing_frequency"], ("MONTHLY", "QUARTERLY"), "filing_frequency")
    op = new_common()
    op.update({
        "jurisdiction_id": body["jurisdiction_id"],
        "legal_name": body["legal_name"],
        "filing_frequency": body["filing_frequency"],
        "certificate_number": None,
        "status": "PENDING",
    })
    db.operators[op["id"]] = op
    return ok(ser_operator(op), 201)


@app.route("/operators", methods=["GET"])
def list_operators():
    require_roles("TaxAdmin", "Operator", "Auditor")
    rows = list(db.operators.values())
    jid = request.args.get("jurisdiction_id")
    status = request.args.get("status")
    if jid:
        rows = [r for r in rows if r["jurisdiction_id"] == jid]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    page, meta = paginate(rows)
    return ok([ser_operator(r) for r in page], is_array=True, pagination=meta)


@app.route("/operators/<oid>", methods=["GET"])
def get_operator(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_operator(fetch(db.operators, oid)))


def _operator_transition(oid, allowed_from, new_status, role="TaxAdmin"):
    require_roles(role)
    op = fetch(db.operators, oid)
    if op["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, "Operator not in a valid state")
    op["status"] = new_status
    mutate(op)
    return op


@app.route("/operators/<oid>/activate", methods=["POST"])
def activate_operator(oid):
    require_roles("TaxAdmin")
    op = fetch(db.operators, oid)
    if op["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Operator not PENDING")
    op["certificate_number"] = "CERT-" + uuid.uuid4().hex[:12].upper()
    op["status"] = "ACTIVE"
    mutate(op)
    return ok(ser_operator(op))


@app.route("/operators/<oid>/suspend", methods=["POST"])
def suspend_operator(oid):
    op = _operator_transition(oid, ("ACTIVE", "DELINQUENT"), "SUSPENDED")
    return ok(ser_operator(op))


@app.route("/operators/<oid>/reinstate", methods=["POST"])
def reinstate_operator(oid):
    require_roles("TaxAdmin")
    op = fetch(db.operators, oid)
    if op["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Operator not SUSPENDED")
    op["status"] = "ACTIVE"
    mutate(op)
    reconcile_operator(op)
    return ok(ser_operator(op))


@app.route("/operators/<oid>/revoke", methods=["POST"])
def revoke_operator(oid):
    op = _operator_transition(oid, ("SUSPENDED",), "REVOKED")
    return ok(ser_operator(op))


@app.route("/operators/<oid>/close", methods=["POST"])
def close_operator(oid):
    require_roles("TaxAdmin")
    op = fetch(db.operators, oid)
    if op["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Operator not ACTIVE")
    if account_balance(op["id"]) != 0:
        raise ApiError("ERR_OPERATOR_NOT_SETTLED", 409, "Balance is not zero")
    for a in db.audits.values():
        if a["operator_id"] == op["id"] and a["status"] in (
                "OPENED", "FIELDWORK", "PROPOSED", "RESPONSE"):
            raise ApiError("ERR_AUDIT_IN_PROGRESS", 409, "Audit in progress")
    op["status"] = "CLOSED"
    mutate(op)
    return ok(ser_operator(op))


@app.route("/operators/<oid>/liens", methods=["POST"])
def record_lien(oid):
    require_roles("TaxAdmin")
    op = fetch(db.operators, oid)
    body = get_json()
    if "expected_operator_version" not in body or body["expected_operator_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_operator_version required")
    if body["expected_operator_version"] != op["version"]:
        raise ApiError("ERR_STALE_OPERATOR_VERSION", 412, "Stale operator version")
    jur = operator_jurisdiction(op)
    bal = account_balance(op["id"])
    if not bal > jur["lien_threshold_cents"]:
        raise ApiError("ERR_BELOW_LIEN_THRESHOLD", 422, "Balance below lien threshold")
    lien = new_common()
    lien.update({
        "operator_id": op["id"],
        "amount_cents": bal,
        "status": "RECORDED",
        "recorded_at": now_dt(),
    })
    db.liens[lien["id"]] = lien
    mutate(op)  # side effect: increments operator version by 1
    return ok(ser_lien(lien), 201)


def _reverse_list(store_dict, parent_field, parent_id, serializer, extra_filter=None):
    rows = [r for r in store_dict.values() if r[parent_field] == parent_id]
    if extra_filter:
        rows = [r for r in rows if extra_filter(r)]
    rows = sort_by_created(rows)
    page, meta = paginate(rows)
    return ok([serializer(r) for r in page], is_array=True, pagination=meta)


@app.route("/operators/<oid>/liens", methods=["GET"])
def list_operator_liens(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.operators, oid)
    status = request.args.get("status")
    return _reverse_list(db.liens, "operator_id", oid, ser_lien,
                         (lambda r: r["status"] == status) if status else None)


@app.route("/operators/<oid>/properties", methods=["GET"])
def list_operator_properties(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.operators, oid)
    return _reverse_list(db.properties, "operator_id", oid, ser_property)


@app.route("/operators/<oid>/ota-agreements", methods=["GET"])
def list_operator_agreements(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.operators, oid)
    return _reverse_list(db.ota_agreements, "operator_id", oid, ser_agreement)


@app.route("/operators/<oid>/returns", methods=["GET"])
def list_operator_returns(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.operators, oid)
    fs = request.args.get("filing_status")
    ss = request.args.get("settlement_status")

    def filt(r):
        if fs and r["filing_status"] != fs:
            return False
        if ss and r["settlement_status"] != ss:
            return False
        return True

    return _reverse_list(db.returns, "operator_id", oid, ser_return, filt)


@app.route("/operators/<oid>/audits", methods=["GET"])
def list_operator_audits(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.operators, oid)
    return _reverse_list(db.audits, "operator_id", oid, ser_audit)


@app.route("/operators/<oid>/refund-claims", methods=["GET"])
def list_operator_refunds(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.operators, oid)
    return _reverse_list(db.refund_claims, "operator_id", oid, ser_refund)


@app.route("/operators/<oid>/ledger-entries", methods=["GET"])
def list_operator_ledger(oid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.operators, oid)
    rows = [e for e in db.ledger if e["operator_id"] == oid]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, meta = paginate(rows)
    return ok([ser_ledger(r) for r in page], is_array=True, pagination=meta)


# ===========================================================================
# Property
# ===========================================================================
@app.route("/properties", methods=["POST"])
def create_property():
    require_roles("TaxAdmin", "Operator")
    body = get_json()
    require_fields(body, "operator_id", "name", "address")
    op = fetch(db.operators, body["operator_id"])
    require_owner(op["id"])
    p = new_common()
    p.update({
        "operator_id": op["id"],
        "name": body["name"],
        "address": body["address"],
        "active": True,
    })
    db.properties[p["id"]] = p
    return ok(ser_property(p), 201)


@app.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_property(fetch(db.properties, pid)))


# ===========================================================================
# OTA Platform & Agreement
# ===========================================================================
@app.route("/ota-platforms", methods=["POST"])
def create_platform():
    require_roles("TaxAdmin")
    body = get_json()
    require_fields(body, "name")
    registered = body.get("registered", True)
    if not isinstance(registered, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "registered must be boolean")
    p = new_common()
    p.update({"name": body["name"], "registered": registered})
    db.ota_platforms[p["id"]] = p
    return ok(ser_platform(p), 201)


@app.route("/ota-platforms/<pid>", methods=["GET"])
def get_platform(pid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_platform(fetch(db.ota_platforms, pid)))


@app.route("/ota-agreements", methods=["POST"])
def create_agreement():
    require_roles("TaxAdmin", "Operator")
    body = get_json()
    require_fields(body, "operator_id", "platform_id", "collection_method", "effective_date")
    op = fetch(db.operators, body["operator_id"])
    fetch(db.ota_platforms, body["platform_id"])
    require_owner(op["id"])
    require_enum(body["collection_method"], ("GROSS", "NET"), "collection_method")
    eff = parse_dt(body["effective_date"])
    end_raw = body.get("end_date")
    end_dt = parse_dt(end_raw) if end_raw is not None else None
    a = new_common()
    a.update({
        "operator_id": op["id"],
        "platform_id": body["platform_id"],
        "collection_method": body["collection_method"],
        "effective_date": body["effective_date"],
        "end_date": end_raw,
        "_eff_dt": eff,
        "_end_dt": end_dt,
        "status": "PROPOSED",
    })
    db.ota_agreements[a["id"]] = a
    return ok(ser_agreement(a), 201)


@app.route("/ota-agreements", methods=["GET"])
def list_agreements():
    require_roles("TaxAdmin", "Operator", "Auditor")
    rows = list(db.ota_agreements.values())
    pid = request.args.get("platform_id")
    oid = request.args.get("operator_id")
    status = request.args.get("status")
    if pid:
        rows = [r for r in rows if r["platform_id"] == pid]
    if oid:
        rows = [r for r in rows if r["operator_id"] == oid]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    page, meta = paginate(rows)
    return ok([ser_agreement(r) for r in page], is_array=True, pagination=meta)


@app.route("/ota-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_agreement(fetch(db.ota_agreements, aid)))


@app.route("/ota-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    require_roles("TaxAdmin")
    a = fetch(db.ota_agreements, aid)
    if a["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement not PROPOSED")
    # temporal overlap (priority 7) then platform-registered (priority 8)
    for other in db.ota_agreements.values():
        if (other["id"] != a["id"] and other["status"] == "ACTIVE"
                and other["operator_id"] == a["operator_id"]
                and other["platform_id"] == a["platform_id"]):
            if intervals_overlap_halfopen(a["_eff_dt"], a["_end_dt"],
                                          other["_eff_dt"], other["_end_dt"]):
                raise ApiError("ERR_AGREEMENT_OVERLAP", 409, "Agreement coverage overlaps")
    platform = db.ota_platforms[a["platform_id"]]
    if not platform["registered"]:
        raise ApiError("ERR_PLATFORM_NOT_REGISTERED", 409, "Platform not registered")
    a["status"] = "ACTIVE"
    mutate(a)
    return ok(ser_agreement(a))


@app.route("/ota-agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(aid):
    require_roles("TaxAdmin")
    a = fetch(db.ota_agreements, aid)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement not ACTIVE")
    a["status"] = "TERMINATED"
    mutate(a)
    return ok(ser_agreement(a))


# ===========================================================================
# Tax Return
# ===========================================================================
def compute_due_date(period_end_dt):
    y, m = period_end_dt.year, period_end_dt.month
    if m == 12:
        ny, nm = y + 1, 1
    else:
        ny, nm = y, m + 1
    last = calendar.monthrange(ny, nm)[1]
    return datetime(ny, nm, last, 0, 0, 0, tzinfo=UTC)


def validate_line_items(line_items):
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "line_items must be a non-empty array")
    for li in line_items:
        if not isinstance(li, dict) or "property_id" not in li or "gross_receipts_cents" not in li:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid line item")
        require_non_negative_int(li["gross_receipts_cents"], "gross_receipts_cents")


@app.route("/returns", methods=["POST"])
def create_return():
    require_roles("TaxAdmin", "Operator")
    body = get_json()
    require_fields(body, "operator_id", "period_start", "period_end", "line_items")
    op = fetch(db.operators, body["operator_id"])
    validate_line_items(body["line_items"])
    for li in body["line_items"]:
        fetch(db.properties, li["property_id"])
    require_owner(op["id"])
    reporting_method = body.get("reporting_method", "NET")
    require_enum(reporting_method, ("GROSS", "NET"), "reporting_method")
    ps = parse_dt(body["period_start"])
    pe = parse_dt(body["period_end"])
    line_items = [{"property_id": li["property_id"],
                   "gross_receipts_cents": li["gross_receipts_cents"]}
                  for li in body["line_items"]]
    gross = sum(li["gross_receipts_cents"] for li in line_items)
    r = new_common()
    r.update({
        "operator_id": op["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "_ps_dt": ps,
        "_pe_dt": pe,
        "reporting_method": reporting_method,
        "line_items": line_items,
        "gross_receipts_cents": gross,
        "exempt_receipts_cents": 0,
        "taxable_receipts_cents": gross,
        "tax_due_cents": 0,
        "penalty_cents": 0,
        "interest_cents": 0,
        "due_date": compute_due_date(pe),
        "filed_at": None,
        "filing_status": "DRAFT",
        "settlement_status": "UNPAID",
    })
    db.returns[r["id"]] = r
    return ok(ser_return(r), 201)


@app.route("/returns/<rid>", methods=["GET"])
def get_return(rid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_return(fetch(db.returns, rid)))


@app.route("/returns/<rid>/file", methods=["POST"])
def file_return(rid):
    require_roles("Operator")
    r = fetch(db.returns, rid)
    require_owner(r["operator_id"])
    if r["filing_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Return not DRAFT")
    op = db.operators[r["operator_id"]]
    if op["status"] not in ("ACTIVE", "DELINQUENT"):
        raise ApiError("ERR_OPERATOR_NOT_ACTIVE", 409, "Operator not ACTIVE/DELINQUENT")
    # period overlap (priority 7) vs FILED/AMENDED returns of same operator
    for other in db.returns.values():
        if (other["id"] != r["id"] and other["operator_id"] == op["id"]
                and other["filing_status"] in ("FILED", "AMENDED")):
            if periods_overlap_closed(r["_ps_dt"], r["_pe_dt"],
                                      other["_ps_dt"], other["_pe_dt"]):
                raise ApiError("ERR_PERIOD_OVERLAP", 409, "Return period overlaps")
    # receipts partition guard (priority 10)
    jur = operator_jurisdiction(op)
    exempt = honored_exemption_total(r)
    if exempt > r["gross_receipts_cents"]:
        raise ApiError("ERR_RECEIPTS_MISMATCH", 422, "Exemptions exceed gross receipts")
    tax, exempt, gross = compute_tax(r, jur["tax_rate_bps"])
    r["gross_receipts_cents"] = gross
    r["exempt_receipts_cents"] = exempt
    r["taxable_receipts_cents"] = gross - exempt
    r["tax_due_cents"] = tax
    penalty, interest = compute_penalty_interest(tax, r["due_date"], jur)
    r["penalty_cents"] = penalty
    r["interest_cents"] = interest
    r["filing_status"] = "FILED"
    r["filed_at"] = now_dt()
    mutate(r)
    post_ledger(op["id"], "TAX_DUE", tax, r["id"])
    if penalty > 0:
        post_ledger(op["id"], "PENALTY", penalty, r["id"])
    if interest > 0:
        post_ledger(op["id"], "INTEREST", interest, r["id"])
    reconcile_operator(op)
    recompute_settlement(r)
    return ok(ser_return(r))


@app.route("/returns/<rid>/amend", methods=["POST"])
def amend_return(rid):
    require_roles("Operator")
    r = fetch(db.returns, rid)
    require_owner(r["operator_id"])
    if r["filing_status"] not in ("FILED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Return not FILED/AMENDED")
    # blocked if covered by an ISSUED/FINAL assessment
    op = db.operators[r["operator_id"]]
    for a in db.assessments.values():
        if audit_operator_id(a) == op["id"] and a["status"] in ("ISSUED", "FINAL"):
            audit = db.audits[a["audit_id"]]
            if periods_overlap_closed(r["_ps_dt"], r["_pe_dt"],
                                      audit["_ps_dt"], audit["_pe_dt"]):
                raise ApiError("ERR_RETURN_UNDER_ASSESSMENT", 409,
                               "Return covered by an assessment")
    body = get_json()
    if "line_items" in body and body["line_items"] is not None:
        validate_line_items(body["line_items"])
        for li in body["line_items"]:
            fetch(db.properties, li["property_id"])
        r["line_items"] = [{"property_id": li["property_id"],
                            "gross_receipts_cents": li["gross_receipts_cents"]}
                           for li in body["line_items"]]
    jur = operator_jurisdiction(op)
    old_tax = r["tax_due_cents"]
    tax, exempt, gross = compute_tax(r, jur["tax_rate_bps"])
    r["gross_receipts_cents"] = gross
    r["exempt_receipts_cents"] = exempt
    r["taxable_receipts_cents"] = gross - exempt
    r["tax_due_cents"] = tax
    r["filing_status"] = "AMENDED"
    mutate(r)
    delta = tax - old_tax
    if delta != 0:
        post_ledger(op["id"], "ADJUSTMENT", delta, r["id"])
        reconcile_operator(op)
    recompute_settlement(r)
    return ok(ser_return(r))


@app.route("/returns/<rid>/exemptions", methods=["GET"])
def list_return_exemptions(rid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.returns, rid)
    status = request.args.get("status")
    return _reverse_list(db.exemptions, "tax_return_id", rid, ser_exemption,
                         (lambda r: r["status"] == status) if status else None)


@app.route("/returns/<rid>/remittances", methods=["GET"])
def list_return_remittances(rid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.returns, rid)
    return _reverse_list(db.remittances, "tax_return_id", rid, ser_remittance)


# ===========================================================================
# Exemption Claim
# ===========================================================================
@app.route("/exemptions", methods=["POST"])
def create_exemption():
    require_roles("TaxAdmin", "Operator")
    body = get_json()
    require_fields(body, "tax_return_id", "exemption_type", "guest_ref", "amount_cents")
    ret = fetch(db.returns, body["tax_return_id"])
    require_owner(ret["operator_id"])
    require_enum(body["exemption_type"],
                 ("LONG_TERM_30DAY", "GOVERNMENT", "NONPROFIT"), "exemption_type")
    require_non_negative_int(body["amount_cents"], "amount_cents")
    stay = body.get("stay_nights", 0)
    if stay is None:
        stay = 0
    require_non_negative_int(stay, "stay_nights")
    e = new_common()
    e.update({
        "tax_return_id": ret["id"],
        "exemption_type": body["exemption_type"],
        "guest_ref": body["guest_ref"],
        "stay_nights": stay,
        "amount_cents": body["amount_cents"],
        "status": "CLAIMED",
    })
    db.exemptions[e["id"]] = e
    return ok(ser_exemption(e), 201)


@app.route("/exemptions/<eid>", methods=["GET"])
def get_exemption(eid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_exemption(fetch(db.exemptions, eid)))


@app.route("/exemptions/<eid>/verify", methods=["POST"])
def verify_exemption(eid):
    require_roles("TaxAdmin")
    e = fetch(db.exemptions, eid)
    if e["status"] != "CLAIMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Exemption not CLAIMED")
    ret = db.returns[e["tax_return_id"]]
    if ret["filing_status"] == "SUPERSEDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Return superseded")
    if e["exemption_type"] == "LONG_TERM_30DAY":
        jur = operator_jurisdiction(db.operators[ret["operator_id"]])
        if e["stay_nights"] < jur["exemption_min_stay_nights"]:
            raise ApiError("ERR_EXEMPTION_INELIGIBLE", 422, "Stay below minimum nights")
    e["status"] = "VERIFIED"
    mutate(e)
    # No receipts movement: CLAIMED and VERIFIED are equally honored in STANDARD.
    return ok(ser_exemption(e))


@app.route("/exemptions/<eid>/reject", methods=["POST"])
def reject_exemption(eid):
    require_roles("TaxAdmin")
    e = fetch(db.exemptions, eid)
    if e["status"] not in ("CLAIMED", "VERIFIED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Exemption not CLAIMED/VERIFIED")
    ret = db.returns[e["tax_return_id"]]
    e["status"] = "REJECTED"
    mutate(e)
    if ret["filing_status"] in ("FILED", "AMENDED"):
        op = db.operators[ret["operator_id"]]
        jur = operator_jurisdiction(op)
        old_tax = ret["tax_due_cents"]
        tax, exempt, gross = compute_tax(ret, jur["tax_rate_bps"])
        ret["exempt_receipts_cents"] = exempt
        ret["taxable_receipts_cents"] = gross - exempt
        ret["tax_due_cents"] = tax
        mutate(ret)
        delta = tax - old_tax
        if delta != 0:
            post_ledger(op["id"], "ADJUSTMENT", delta, ret["id"])
            reconcile_operator(op)
        recompute_settlement(ret)
    return ok(ser_exemption(e))


# ===========================================================================
# Remittance
# ===========================================================================
@app.route("/remittances", methods=["POST"])
def create_remittance():
    require_roles("TaxAdmin", "Operator")
    body = get_json()
    require_fields(body, "tax_return_id", "remitter", "amount_cents")
    ret = fetch(db.returns, body["tax_return_id"])
    ota_agreement_id = body.get("ota_agreement_id")
    if ota_agreement_id is not None:
        fetch(db.ota_agreements, ota_agreement_id)
    require_owner(ret["operator_id"])
    require_enum(body["remitter"], ("OPERATOR", "OTA"), "remitter")
    require_non_negative_int(body["amount_cents"], "amount_cents")
    rem = new_common()
    rem.update({
        "tax_return_id": ret["id"],
        "ota_agreement_id": ota_agreement_id,
        "remitter": body["remitter"],
        "amount_cents": body["amount_cents"],
        "status": "RECEIVED",
    })
    db.remittances[rem["id"]] = rem
    return ok(ser_remittance(rem), 201)


@app.route("/remittances", methods=["GET"])
def list_remittances():
    require_roles("TaxAdmin", "Operator", "Auditor")
    rows = list(db.remittances.values())
    trid = request.args.get("tax_return_id")
    aid = request.args.get("ota_agreement_id")
    status = request.args.get("status")
    if trid:
        rows = [r for r in rows if r["tax_return_id"] == trid]
    if aid:
        rows = [r for r in rows if r["ota_agreement_id"] == aid]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    page, meta = paginate(rows)
    return ok([ser_remittance(r) for r in page], is_array=True, pagination=meta)


@app.route("/remittances/<rid>", methods=["GET"])
def get_remittance(rid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_remittance(fetch(db.remittances, rid)))


@app.route("/remittances/<rid>/clear", methods=["POST"])
def clear_remittance(rid):
    require_roles("TaxAdmin")
    rem = fetch(db.remittances, rid)
    ret = db.returns[rem["tax_return_id"]]
    if rem["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Remittance not RECEIVED")
    if ret["filing_status"] not in ("FILED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Return not FILED/AMENDED")
    # OTA referential (priority 8)
    if rem["remitter"] == "OTA":
        ag = db.ota_agreements.get(rem["ota_agreement_id"]) if rem["ota_agreement_id"] else None
        if ag is None or ag["status"] != "ACTIVE" or not _agreement_covers(ag, ret):
            raise ApiError("ERR_OTA_AGREEMENT_INACTIVE", 409,
                           "OTA agreement inactive or does not cover the period")
    # fiscal cap (priority 11)
    remaining = return_total_due(ret) - return_amount_paid(ret)
    if rem["amount_cents"] > remaining:
        raise ApiError("ERR_REMITTANCE_EXCEEDS_DUE", 422, "Remittance exceeds amount due")
    rem["status"] = "CLEARED"
    mutate(rem)
    op = db.operators[ret["operator_id"]]
    post_ledger(op["id"], "REMITTANCE", -rem["amount_cents"], rem["id"])
    reconcile_operator(op)
    recompute_settlement(ret)
    return ok(ser_remittance(rem))


def _agreement_covers(ag, ret):
    # half-open [effective, end) covering the return period
    if ag["_eff_dt"] > ret["_ps_dt"]:
        return False
    if ag["_end_dt"] is not None and ag["_end_dt"] <= ret["_pe_dt"]:
        return False
    return True


@app.route("/remittances/<rid>/reverse", methods=["POST"])
def reverse_remittance(rid):
    require_roles("TaxAdmin")
    rem = fetch(db.remittances, rid)
    if rem["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", 409, "Remittance not CLEARED")
    ret = db.returns[rem["tax_return_id"]]
    rem["status"] = "REVERSED"
    mutate(rem)
    op = db.operators[ret["operator_id"]]
    post_ledger(op["id"], "REMITTANCE_REVERSAL", rem["amount_cents"], rem["id"])
    reconcile_operator(op)
    recompute_settlement(ret)
    return ok(ser_remittance(rem))


# ===========================================================================
# Audit & Assessment
# ===========================================================================
@app.route("/audits", methods=["POST"])
def create_audit():
    require_roles("Auditor")
    body = get_json()
    require_fields(body, "operator_id", "period_start", "period_end")
    op = fetch(db.operators, body["operator_id"])
    ps = parse_dt(body["period_start"])
    pe = parse_dt(body["period_end"])
    a = new_common()
    a.update({
        "operator_id": op["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "_ps_dt": ps,
        "_pe_dt": pe,
        "classification": "NONE",
        "status": "OPENED",
    })
    db.audits[a["id"]] = a
    return ok(ser_audit(a), 201)


@app.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_audit(fetch(db.audits, aid)))


@app.route("/audits/<aid>/begin-fieldwork", methods=["POST"])
def begin_fieldwork(aid):
    require_roles("Auditor")
    a = fetch(db.audits, aid)
    if a["status"] != "OPENED":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit not OPENED")
    a["status"] = "FIELDWORK"
    mutate(a)
    return ok(ser_audit(a))


def _audited_returns(audit):
    oid = audit["operator_id"]
    result = []
    for r in db.returns.values():
        if (r["operator_id"] == oid and r["filing_status"] in ("FILED", "AMENDED")
                and periods_overlap_closed(r["_ps_dt"], r["_pe_dt"],
                                           audit["_ps_dt"], audit["_pe_dt"])):
            result.append(r)
    return result


@app.route("/audits/<aid>/assessments", methods=["POST"])
def propose_assessment(aid):
    require_roles("Auditor")
    audit = fetch(db.audits, aid)
    if audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit not in FIELDWORK")
    body = get_json()
    require_fields(body, "audited_taxable_cents", "classification")
    require_non_negative_int(body["audited_taxable_cents"], "audited_taxable_cents")
    require_enum(body["classification"], ("NEGLIGENCE", "FRAUD"), "classification")
    returns = _audited_returns(audit)
    if not returns:
        raise ApiError("ERR_NO_RETURNS_IN_PERIOD", 409, "No FILED/AMENDED returns in period")
    op = db.operators[audit["operator_id"]]
    jur = operator_jurisdiction(op)
    audited_taxable = body["audited_taxable_cents"]
    assessed = round_half_up(Decimal(audited_taxable) * Decimal(jur["tax_rate_bps"]) / Decimal(10000))
    self_reported = sum(r["tax_due_cents"] for r in returns)
    deficiency = max(0, assessed - self_reported)
    classification = body["classification"]
    if classification == "NEGLIGENCE":
        penalty = round_half_up(Decimal(deficiency) * Decimal("0.10"))
    else:
        penalty = round_half_up(Decimal(deficiency) * Decimal("0.25"))
    earliest_due = min(r["due_date"] for r in returns)
    months_late = whole_months(earliest_due, now_dt())
    interest = round_half_up(
        Decimal(deficiency) * Decimal(jur["interest_rate_monthly_bps"]) / Decimal(10000) * months_late
    )
    total = deficiency + penalty + interest
    audit["classification"] = classification
    audit["status"] = "PROPOSED"
    mutate(audit)
    a = new_common()
    a.update({
        "audit_id": audit["id"],
        "audited_taxable_cents": audited_taxable,
        "assessed_tax_cents": assessed,
        "self_reported_tax_cents": self_reported,
        "deficiency_cents": deficiency,
        "penalty_cents": penalty,
        "interest_cents": interest,
        "total_assessed_cents": total,
        "status": "PROPOSED",
    })
    db.assessments[a["id"]] = a
    return ok(ser_assessment(a), 201)


@app.route("/audits/<aid>/assessments", methods=["GET"])
def list_audit_assessments(aid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.audits, aid)
    return _reverse_list(db.assessments, "audit_id", aid, ser_assessment)


@app.route("/audits/<aid>/record-response", methods=["POST"])
def record_response(aid):
    require_roles("Auditor")
    a = fetch(db.audits, aid)
    if a["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit not PROPOSED")
    a["status"] = "RESPONSE"
    mutate(a)
    return ok(ser_audit(a))


@app.route("/audits/<aid>/reopen-fieldwork", methods=["POST"])
def reopen_fieldwork(aid):
    require_roles("Auditor")
    a = fetch(db.audits, aid)
    if a["status"] != "RESPONSE":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit not RESPONSE")
    # abandon the still-PROPOSED assessment -> ABATED
    for asmt in db.assessments.values():
        if asmt["audit_id"] == a["id"] and asmt["status"] == "PROPOSED":
            asmt["status"] = "ABATED"
            mutate(asmt)
    a["status"] = "FIELDWORK"
    mutate(a)
    return ok(ser_audit(a))


@app.route("/audits/<aid>/close-no-change", methods=["POST"])
def close_no_change(aid):
    require_roles("Auditor")
    a = fetch(db.audits, aid)
    if a["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit not FIELDWORK")
    a["status"] = "CLOSED_NO_CHANGE"
    mutate(a)
    return ok(ser_audit(a))


@app.route("/assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_assessment(fetch(db.assessments, aid)))


@app.route("/assessments/<aid>/issue", methods=["POST"])
def issue_assessment(aid):
    require_roles("TaxAdmin")
    asmt = fetch(db.assessments, aid)
    audit = db.audits[asmt["audit_id"]]
    if asmt["status"] != "PROPOSED" or audit["status"] not in ("PROPOSED", "RESPONSE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment not issuable")
    asmt["status"] = "ISSUED"
    mutate(asmt)
    audit["status"] = "ISSUED"
    mutate(audit)
    op = db.operators[audit["operator_id"]]
    post_ledger(op["id"], "ASSESSMENT", asmt["total_assessed_cents"], asmt["id"])
    reconcile_operator(op)
    return ok(ser_assessment(asmt))


@app.route("/assessments/<aid>/appeals", methods=["POST"])
def submit_appeal(aid):
    require_roles("Operator")
    asmt = fetch(db.assessments, aid)
    audit = db.audits[asmt["audit_id"]]
    require_owner(audit["operator_id"])
    if asmt["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment not ISSUED")
    body = get_json()
    require_fields(body, "grounds")
    asmt["status"] = "APPEALED"
    mutate(asmt)
    ap = new_common()
    ap.update({
        "assessment_id": asmt["id"],
        "grounds": body["grounds"],
        "round_count": 0,
        "decision": None,
        "reduced_total_cents": None,
        "status": "SUBMITTED",
    })
    db.appeals[ap["id"]] = ap
    return ok(ser_appeal(ap), 201)


@app.route("/assessments/<aid>/appeals", methods=["GET"])
def list_assessment_appeals(aid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    fetch(db.assessments, aid)
    return _reverse_list(db.appeals, "assessment_id", aid, ser_appeal)


# ===========================================================================
# Appeal
# ===========================================================================
@app.route("/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_appeal(fetch(db.appeals, aid)))


@app.route("/appeals/<aid>/begin-review", methods=["POST"])
def begin_review(aid):
    require_roles("TaxAdmin")
    ap = fetch(db.appeals, aid)
    if ap["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appeal not SUBMITTED")
    ap["status"] = "UNDER_REVIEW"
    mutate(ap)
    return ok(ser_appeal(ap))


@app.route("/appeals/<aid>/request-info", methods=["POST"])
def request_info(aid):
    require_roles("TaxAdmin")
    ap = fetch(db.appeals, aid)
    if ap["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Appeal not UNDER_REVIEW")
    ap["status"] = "INFO_REQUESTED"
    mutate(ap)
    return ok(ser_appeal(ap))


@app.route("/appeals/<aid>/provide-info", methods=["POST"])
def provide_info(aid):
    require_roles("Operator")
    ap = fetch(db.appeals, aid)
    asmt = db.assessments[ap["assessment_id"]]
    audit = db.audits[asmt["audit_id"]]
    require_owner(audit["operator_id"])
    if ap["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appeal not INFO_REQUESTED")
    ap["status"] = "UNDER_REVIEW"
    ap["round_count"] += 1
    mutate(ap)
    return ok(ser_appeal(ap))


@app.route("/appeals/<aid>/decide", methods=["POST"])
def decide_appeal(aid):
    require_roles("TaxAdmin")
    ap = fetch(db.appeals, aid)
    asmt = db.assessments[ap["assessment_id"]]
    if ap["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Appeal not UNDER_REVIEW")
    if asmt["status"] != "APPEALED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment not APPEALED")
    body = get_json()
    require_fields(body, "decision")
    require_enum(body["decision"], ("UPHELD", "REDUCED", "ABATED"), "decision")
    decision = body["decision"]
    reduced_total = body.get("reduced_total_cents")
    if decision == "REDUCED":
        if reduced_total is None or not isinstance(reduced_total, int) or isinstance(reduced_total, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "reduced_total_cents required for REDUCED")
        if reduced_total >= asmt["total_assessed_cents"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "reduced_total_cents must be less than total_assessed_cents")
    ap["status"] = "DECIDED"
    ap["decision"] = decision
    if decision == "REDUCED":
        ap["reduced_total_cents"] = reduced_total
    mutate(ap)
    audit = db.audits[asmt["audit_id"]]
    op = db.operators[audit["operator_id"]]
    if decision == "UPHELD":
        asmt["status"] = "FINAL"
        mutate(asmt)
        reconcile_operator(op)
    elif decision == "ABATED":
        asmt["status"] = "ABATED"
        mutate(asmt)
        post_ledger(op["id"], "ABATEMENT", -asmt["total_assessed_cents"], asmt["id"])
        reconcile_operator(op)
    else:  # REDUCED
        asmt["status"] = "FINAL"
        mutate(asmt)
        delta = -(asmt["total_assessed_cents"] - reduced_total)
        if delta != 0:
            post_ledger(op["id"], "ADJUSTMENT", delta, asmt["id"])
        reconcile_operator(op)
    return ok(ser_appeal(ap))


# ===========================================================================
# Refund Claim
# ===========================================================================
@app.route("/refund-claims", methods=["POST"])
def create_refund():
    require_roles("TaxAdmin", "Operator")
    body = get_json()
    require_fields(body, "operator_id", "reason", "principal_cents", "overpayment_date")
    op = fetch(db.operators, body["operator_id"])
    trid = body.get("tax_return_id")
    if trid is not None:
        fetch(db.returns, trid)
    require_owner(op["id"])
    require_enum(body["reason"], ("OVERPAYMENT", "AUDIT_ADJUSTMENT"), "reason")
    require_non_negative_int(body["principal_cents"], "principal_cents")
    overpayment_dt = parse_dt(body["overpayment_date"])
    rc = new_common()
    rc.update({
        "operator_id": op["id"],
        "tax_return_id": trid,
        "reason": body["reason"],
        "principal_cents": body["principal_cents"],
        "overpayment_date": body["overpayment_date"],
        "_overpayment_dt": overpayment_dt,
        "interest_cents": 0,
        "total_refund_cents": 0,
        "status": "REQUESTED",
    })
    db.refund_claims[rc["id"]] = rc
    return ok(ser_refund(rc), 201)


@app.route("/refund-claims", methods=["GET"])
def list_refunds():
    require_roles("TaxAdmin", "Operator", "Auditor")
    rows = list(db.refund_claims.values())
    oid = request.args.get("operator_id")
    trid = request.args.get("tax_return_id")
    status = request.args.get("status")
    if oid:
        rows = [r for r in rows if r["operator_id"] == oid]
    if trid:
        rows = [r for r in rows if r["tax_return_id"] == trid]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    page, meta = paginate(rows)
    return ok([ser_refund(r) for r in page], is_array=True, pagination=meta)


@app.route("/refund-claims/<rid>", methods=["GET"])
def get_refund(rid):
    require_roles("TaxAdmin", "Operator", "Auditor")
    return ok(ser_refund(fetch(db.refund_claims, rid)))


@app.route("/refund-claims/<rid>/approve", methods=["POST"])
def approve_refund(rid):
    require_roles("TaxAdmin")
    rc = fetch(db.refund_claims, rid)
    if rc["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Refund not REQUESTED")
    op = db.operators[rc["operator_id"]]
    credit = -account_balance(op["id"])  # positive = held overpayment credit
    if rc["principal_cents"] > credit:
        raise ApiError("ERR_REFUND_EXCEEDS_OVERPAYMENT", 422, "Refund exceeds overpayment credit")
    jur = operator_jurisdiction(op)
    if rc["reason"] == "OVERPAYMENT":
        anchor = rc["_overpayment_dt"]
    else:
        anchor = rc["created_at"]
    months = whole_months(anchor, now_dt())
    interest = round_half_up(
        Decimal(rc["principal_cents"]) * Decimal(jur["refund_interest_monthly_bps"]) / Decimal(10000) * months
    )
    rc["interest_cents"] = interest
    rc["total_refund_cents"] = rc["principal_cents"] + interest
    rc["status"] = "APPROVED"
    mutate(rc)
    return ok(ser_refund(rc))


@app.route("/refund-claims/<rid>/deny", methods=["POST"])
def deny_refund(rid):
    require_roles("TaxAdmin")
    rc = fetch(db.refund_claims, rid)
    if rc["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Refund not REQUESTED")
    rc["status"] = "DENIED"
    mutate(rc)
    return ok(ser_refund(rc))


@app.route("/refund-claims/<rid>/pay", methods=["POST"])
def pay_refund(rid):
    require_roles("TaxAdmin")
    rc = fetch(db.refund_claims, rid)
    if rc["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Refund not APPROVED")
    rc["status"] = "PAID"
    mutate(rc)
    op = db.operators[rc["operator_id"]]
    post_ledger(op["id"], "REFUND", rc["total_refund_cents"], rc["id"])
    reconcile_operator(op)
    return ok(ser_refund(rc))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("TaxAdmin")
    body = get_json()
    require_fields(body, "to_iso8601")
    db.clock = parse_dt(body["to_iso8601"])
    return ok({})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
