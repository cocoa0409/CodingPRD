"""
Property & Casualty Third-Party Claims Administration (TPA) API.

Single-file Flask implementation. In-memory storage only; the store starts
empty on every boot. Every behavior traces to workspace/PRD.md.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Adjuster", "ClaimsManager", "FinanceOfficer", "SiuInvestigator", "Vendor"}

COVERAGE_TYPES = {"PROPERTY", "AUTO", "LIABILITY", "WORKERS_COMP"}
VENDOR_TYPES = {"INDEPENDENT_ADJUSTER", "APPRAISER", "CONTRACTOR", "DEFENSE_ATTORNEY"}

OPEN_CLAIM_STATES = {"ASSIGNED", "INVESTIGATING", "EVALUATED", "REOPENED"}
ROLLUP_OPEN_RESERVE_STATES = {"INTAKE", "ASSIGNED", "INVESTIGATING", "EVALUATED", "REOPENED"}

CLAIM_STATUSES = {"INTAKE", "ASSIGNED", "INVESTIGATING", "EVALUATED", "CLOSED", "REOPENED", "CANCELLED"}
PAYMENT_STATUSES = {"PENDING_APPROVAL", "APPROVED", "REJECTED", "ISSUED", "VOID"}
ASSIGNMENT_STATUSES = {"ACTIVE", "COMPLETED", "CANCELLED"}
INVOICE_STATUSES = {"SUBMITTED", "APPROVED", "REJECTED", "PAID", "VOID"}
LITIGATION_STATUSES = {"OPEN", "IN_SUIT", "SETTLED", "DISMISSED", "JUDGMENT"}
SUBROGATION_STATUSES = {"OPEN", "DEMAND_SENT", "NEGOTIATING", "RECOVERED", "CLOSED_NO_RECOVERY"}
SIU_STATUSES = {"OPEN", "CLEARED", "CONFIRMED"}

VENDOR_RATE_CENTS = {
    "INDEPENDENT_ADJUSTER": 12000,
    "APPRAISER": 15000,
    "CONTRACTOR": 0,
    "DEFENSE_ATTORNEY": 35000,
}
MILEAGE_RATE_CENTS = 55
MIN_INVOICE_CENTS = 5000
VENDOR_INVOICE_CAP_CENTS = 2000000
IBNR_TAIL_PCT = Decimal("0.15")
ADJUSTER_TRAVEL_BUFFER = timedelta(minutes=60)

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (reset on every process start)
# ---------------------------------------------------------------------------
DB = {
    "client_accounts": {},
    "policies": {},
    "adjusters": {},
    "vendors": {},
    "claims": {},
    "assignments": {},
    "reserve_changes": {},
    "payments": {},
    "vendor_invoices": {},
    "litigation_cases": {},
    "subrogation_cases": {},
    "siu_referrals": {},
    "bordereau_reports": {},
}
_STATE = {"clock": DEFAULT_CLOCK, "seq": 0}


def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def clock_now():
    return _STATE["clock"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, status, message=None):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, is_list=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


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
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 422, "Invalid datetime")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        err("ERR_INVALID_REQUEST", 422, "Invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(fields, common=True):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["_seq"] = next_seq()
    rec["created_at"] = clock_now()
    if common:
        rec["updated_at"] = clock_now()
        rec["version"] = 1
    return rec


def touch(rec, bump_version=True):
    rec["updated_at"] = clock_now()
    if bump_version and "version" in rec:
        rec["version"] += 1


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Auth / authorization
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", 422, "Body must be an object")
    return body


def require_present(body, name):
    if name not in body or body[name] is None:
        err("ERR_INVALID_REQUEST", 422, f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    v = require_present(body, name)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", 422, f"Field {name} must be a non-empty string")
    return v


def require_int(body, name):
    v = require_present(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 422, f"Field {name} must be an integer")
    return v


def optional_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 422, f"Field {name} must be an integer")
    return v


def require_number(body, name):
    v = require_present(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", 422, f"Field {name} must be a number")
    return v


def optional_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", 422, f"Field {name} must be a number")
    return v


def require_enum(body, name, allowed):
    v = require_str(body, name)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 422, f"Illegal value for {name}")
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def fetch(kind, ident):
    rec = DB[kind].get(ident)
    if rec is None:
        err("ERR_NOT_FOUND", 404, f"{kind[:-1]} not found")
    return rec


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------
def policy_status(policy):
    exp = parse_dt(policy["expiration_date"])
    return "ACTIVE" if clock_now() < exp else "EXPIRED"


def open_claim_count(adjuster_id):
    n = 0
    for c in DB["claims"].values():
        if c.get("assigned_adjuster_id") == adjuster_id and c["status"] in OPEN_CLAIM_STATES:
            n += 1
    return n


def claim_gross_incurred(c):
    return (c["paid_indemnity_cents"] + c["paid_expense_cents"]
            + c["indemnity_reserve_cents"] + c["expense_reserve_cents"])


def claim_net_incurred(c):
    return claim_gross_incurred(c) - c["recovered_cents"]


def claim_developed_gross(c):
    paid_total = c["paid_indemnity_cents"] + c["paid_expense_cents"]
    outstanding = c["indemnity_reserve_cents"] + c["expense_reserve_cents"]
    developed_outstanding = max(outstanding, round_half_up(Decimal(paid_total) * IBNR_TAIL_PCT))
    return paid_total + developed_outstanding


def account_rollup(account_id):
    open_reserve = 0
    gross = 0
    recovered = 0
    for c in DB["claims"].values():
        if c["client_account_id"] != account_id:
            continue
        status = c["status"]
        if status in ROLLUP_OPEN_RESERVE_STATES:
            open_reserve += c["indemnity_reserve_cents"] + c["expense_reserve_cents"]
        if status != "CANCELLED":
            gross += claim_gross_incurred(c)
            recovered += c["recovered_cents"]
    return open_reserve, gross, recovered


# ---------------------------------------------------------------------------
# Serializers with computed fields
# ---------------------------------------------------------------------------
def ser_account(a):
    out = serialize(a)
    o, g, r = account_rollup(a["id"])
    out["open_case_reserve_total_cents"] = o
    out["gross_incurred_total_cents"] = g
    out["recovered_total_cents"] = r
    return out


def ser_policy(p):
    out = serialize(p)
    out["status"] = policy_status(p)
    return out


def ser_adjuster(a):
    out = serialize(a)
    out["open_claim_count"] = open_claim_count(a["id"])
    return out


def ser_vendor(v):
    return serialize(v)


def ser_claim(c):
    out = serialize(c)
    out["gross_incurred_cents"] = claim_gross_incurred(c)
    out["net_incurred_cents"] = claim_net_incurred(c)
    account = DB["client_accounts"].get(c["client_account_id"])
    sla_hours = account["sla_ack_hours"] if account else 0
    due = parse_dt(c["reported_date"]) + timedelta(hours=sla_hours)
    out["sla_ack_due"] = fmt_ts(due)
    ack = c.get("ack_at")
    if ack is None:
        out["sla_ack_met"] = None
    else:
        out["sla_ack_met"] = ack <= due
    return out


def ser_generic(r):
    return serialize(r)


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------
def paginate(items):
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
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    body = get_body()
    to_iso = require_present(body, "to_iso8601")
    _STATE["clock"] = parse_dt(to_iso)
    return ok({}, 200)


# ===========================================================================
# ClientAccount
# ===========================================================================
@app.route("/client-accounts", methods=["POST"])
def create_account():
    _, role = authenticate()
    authorize(role, {"ClaimsManager"})
    body = get_body()
    name = require_str(body, "name")
    account_code = require_str(body, "account_code")
    reserve_default = require_int(body, "reserve_authority_default_cents")
    sla_ack_hours = optional_int(body, "sla_ack_hours", 24)
    sla_contact_hours = optional_int(body, "sla_contact_hours", 72)
    rec = new_record({
        "name": name,
        "account_code": account_code,
        "sla_ack_hours": sla_ack_hours,
        "sla_contact_hours": sla_contact_hours,
        "reserve_authority_default_cents": reserve_default,
    })
    DB["client_accounts"][rec["id"]] = rec
    return ok(ser_account(rec), 201)


@app.route("/client-accounts/<rid>", methods=["GET"])
def get_account(rid):
    authenticate()
    return ok(ser_account(fetch("client_accounts", rid)), 200)


@app.route("/client-accounts", methods=["GET"])
def list_accounts():
    authenticate()
    page, meta = paginate(list(DB["client_accounts"].values()))
    return ok([ser_account(r) for r in page], 200, is_list=True, pagination=meta)


# ===========================================================================
# Policy
# ===========================================================================
@app.route("/policies", methods=["POST"])
def create_policy():
    _, role = authenticate()
    authorize(role, {"ClaimsManager"})
    body = get_body()
    account_id = require_str(body, "client_account_id")
    account = fetch("client_accounts", account_id)  # existence
    policy_number = require_str(body, "policy_number")
    coverage_limit = require_int(body, "coverage_limit_cents")
    per_claim_expense = require_int(body, "per_claim_expense_limit_cents")
    deductible = optional_int(body, "deductible_cents", 0)
    effective = require_present(body, "effective_date")
    expiration = require_present(body, "expiration_date")
    parse_dt(effective)
    parse_dt(expiration)
    rec = new_record({
        "client_account_id": account["id"],
        "policy_number": policy_number,
        "coverage_limit_cents": coverage_limit,
        "deductible_cents": deductible,
        "per_claim_expense_limit_cents": per_claim_expense,
        "effective_date": effective,
        "expiration_date": expiration,
    })
    DB["policies"][rec["id"]] = rec
    return ok(ser_policy(rec), 201)


@app.route("/policies/<rid>", methods=["GET"])
def get_policy(rid):
    authenticate()
    return ok(ser_policy(fetch("policies", rid)), 200)


@app.route("/policies", methods=["GET"])
def list_policies():
    authenticate()
    items = list(DB["policies"].values())
    account_id = request.args.get("client_account_id")
    if account_id is not None:
        items = [p for p in items if p["client_account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if policy_status(p) == status]
    page, meta = paginate(items)
    return ok([ser_policy(r) for r in page], 200, is_list=True, pagination=meta)


# ===========================================================================
# Adjuster
# ===========================================================================
@app.route("/adjusters", methods=["POST"])
def create_adjuster():
    _, role = authenticate()
    authorize(role, {"ClaimsManager"})
    body = get_body()
    name = require_str(body, "name")
    email = require_str(body, "email")
    authority = require_int(body, "authority_limit_cents")
    max_open = optional_int(body, "max_open_claims", 50)
    rec = new_record({
        "name": name,
        "email": email,
        "authority_limit_cents": authority,
        "max_open_claims": max_open,
    })
    DB["adjusters"][rec["id"]] = rec
    return ok(ser_adjuster(rec), 201)


@app.route("/adjusters/<rid>", methods=["GET"])
def get_adjuster(rid):
    authenticate()
    return ok(ser_adjuster(fetch("adjusters", rid)), 200)


@app.route("/adjusters", methods=["GET"])
def list_adjusters():
    authenticate()
    page, meta = paginate(list(DB["adjusters"].values()))
    return ok([ser_adjuster(r) for r in page], 200, is_list=True, pagination=meta)


# ===========================================================================
# Vendor
# ===========================================================================
@app.route("/vendors", methods=["POST"])
def create_vendor():
    _, role = authenticate()
    authorize(role, {"ClaimsManager"})
    body = get_body()
    name = require_str(body, "name")
    vendor_type = require_enum(body, "vendor_type", VENDOR_TYPES)
    coverages = require_present(body, "credentialed_coverages")
    if not isinstance(coverages, list) or any(
        (not isinstance(c, str) or c not in COVERAGE_TYPES) for c in coverages
    ):
        err("ERR_INVALID_REQUEST", 422, "Invalid credentialed_coverages")
    rec = new_record({
        "name": name,
        "vendor_type": vendor_type,
        "credentialed_coverages": list(coverages),
    })
    DB["vendors"][rec["id"]] = rec
    return ok(ser_vendor(rec), 201)


@app.route("/vendors/<rid>", methods=["GET"])
def get_vendor(rid):
    authenticate()
    return ok(ser_vendor(fetch("vendors", rid)), 200)


@app.route("/vendors", methods=["GET"])
def list_vendors():
    authenticate()
    items = list(DB["vendors"].values())
    vt = request.args.get("vendor_type")
    if vt is not None:
        items = [v for v in items if v["vendor_type"] == vt]
    page, meta = paginate(items)
    return ok([ser_vendor(r) for r in page], 200, is_list=True, pagination=meta)


# ===========================================================================
# Claim
# ===========================================================================
@app.route("/claims", methods=["POST"])
def create_claim():
    _, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager"})
    body = get_body()
    policy_id = require_str(body, "policy_id")
    policy = fetch("policies", policy_id)  # existence
    coverage_type = require_enum(body, "coverage_type", COVERAGE_TYPES)
    loss_date = require_present(body, "loss_date")
    reported_date = require_present(body, "reported_date")
    claimant_name = require_str(body, "claimant_name")
    description = require_str(body, "description")
    parse_dt(loss_date)
    parse_dt(reported_date)
    # priority 7: policy must be ACTIVE
    if policy_status(policy) != "ACTIVE":
        err("ERR_POLICY_INACTIVE", 409, "Policy is not active")
    rec = new_record({
        "policy_id": policy["id"],
        "client_account_id": policy["client_account_id"],
        "coverage_type": coverage_type,
        "loss_date": loss_date,
        "reported_date": reported_date,
        "claimant_name": claimant_name,
        "description": description,
        "status": "INTAKE",
        "siu_status": "NONE",
        "assigned_adjuster_id": None,
        "indemnity_reserve_cents": 0,
        "expense_reserve_cents": 0,
        "paid_indemnity_cents": 0,
        "paid_expense_cents": 0,
        "recovered_cents": 0,
        "recovered_indemnity_cents": 0,
        "recovered_expense_cents": 0,
        "ack_at": None,
    })
    DB["claims"][rec["id"]] = rec
    return ok(ser_claim(rec), 201)


@app.route("/claims/<rid>", methods=["GET"])
def get_claim(rid):
    authenticate()
    return ok(ser_claim(fetch("claims", rid)), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    authenticate()
    items = list(DB["claims"].values())
    for field in ("policy_id", "client_account_id", "assigned_adjuster_id", "status", "coverage_type"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_claim(r) for r in page], 200, is_list=True, pagination=meta)


@app.route("/claims/<rid>/financials", methods=["GET"])
def claim_financials(rid):
    authenticate()
    c = fetch("claims", rid)
    paid_total = c["paid_indemnity_cents"] + c["paid_expense_cents"]
    outstanding = c["indemnity_reserve_cents"] + c["expense_reserve_cents"]
    gross_prov = paid_total + outstanding
    dev_out = max(outstanding, round_half_up(Decimal(paid_total) * IBNR_TAIL_PCT))
    gross_dev = paid_total + dev_out
    net = gross_prov - c["recovered_cents"]
    return ok({
        "paid_total_cents": paid_total,
        "outstanding_reserve_cents": outstanding,
        "gross_incurred_provisional_cents": gross_prov,
        "gross_incurred_developed_cents": gross_dev,
        "net_incurred_cents": net,
    }, 200)


# Claim transitions ---------------------------------------------------------
CLAIM_TRANSITIONS = {
    ("INTAKE", "CANCELLED"),
    ("ASSIGNED", "INVESTIGATING"),
    ("INVESTIGATING", "EVALUATED"),
    ("EVALUATED", "CLOSED"),
    ("CLOSED", "REOPENED"),
    ("REOPENED", "EVALUATED"),
    ("REOPENED", "CLOSED"),
}
CLAIM_ROLE_BY_TARGET = {
    "INVESTIGATING": {"Adjuster", "ClaimsManager"},
    "EVALUATED": {"Adjuster", "ClaimsManager"},
    "CLOSED": {"Adjuster", "ClaimsManager"},
    "REOPENED": {"ClaimsManager"},
    "CANCELLED": {"ClaimsManager"},
}


@app.route("/claims/<rid>/transition", methods=["POST"])
def transition_claim(rid):
    _, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager"})
    c = fetch("claims", rid)
    body = get_body()
    to_status = require_str(body, "to_status")
    if to_status not in CLAIM_STATUSES:
        err("ERR_INVALID_REQUEST", 422, "Illegal to_status")
    # transition-specific role
    role_set = CLAIM_ROLE_BY_TARGET.get(to_status)
    if role_set is not None and role not in role_set:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this transition")
    # state legality
    if (c["status"], to_status) not in CLAIM_TRANSITIONS:
        err("ERR_INVALID_STATE", 409, "Illegal claim transition")

    if to_status == "CANCELLED":
        if any(a["claim_id"] == c["id"] for a in DB["assignments"].values()):
            err("ERR_INVALID_STATE", 409, "Claim has assignments")
        if any(p["claim_id"] == c["id"] for p in DB["payments"].values()):
            err("ERR_INVALID_STATE", 409, "Claim has payments")
        c["status"] = "CANCELLED"
        touch(c)
    elif to_status in ("INVESTIGATING", "EVALUATED", "REOPENED"):
        c["status"] = to_status
        touch(c)
    elif to_status == "CLOSED":
        _close_claim(c)

    return ok(ser_claim(c), 200)


def _close_claim(c):
    # preconditions in PRD order: litigation, subrogation, payment, siu
    for l in DB["litigation_cases"].values():
        if l["claim_id"] == c["id"] and l["status"] in ("OPEN", "IN_SUIT"):
            err("ERR_LITIGATION_OPEN", 409, "Open litigation blocks closure")
    for s in DB["subrogation_cases"].values():
        if s["claim_id"] == c["id"] and s["status"] in ("OPEN", "DEMAND_SENT", "NEGOTIATING"):
            err("ERR_SUBROGATION_OPEN", 409, "Open subrogation blocks closure")
    for p in DB["payments"].values():
        if p["claim_id"] == c["id"] and p["status"] in ("PENDING_APPROVAL", "APPROVED"):
            err("ERR_PAYMENT_PENDING", 409, "Pending payment blocks closure")
    if c["siu_status"] == "HELD":
        err("ERR_SIU_HOLD_ACTIVE", 403, "SIU hold blocks closure")
    # cascade: cancel every ACTIVE assignment (each voids its invoices)
    for a in DB["assignments"].values():
        if a["claim_id"] == c["id"] and a["status"] == "ACTIVE":
            _cancel_assignment(a)
    c["indemnity_reserve_cents"] = 0
    c["expense_reserve_cents"] = 0
    c["status"] = "CLOSED"
    touch(c)


# ===========================================================================
# Assignment
# ===========================================================================
@app.route("/assignments", methods=["POST"])
def create_assignment():
    uid, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager"})
    body = get_body()
    claim_id = require_str(body, "claim_id")
    claim = fetch("claims", claim_id)  # existence (left-to-right)
    assignee_type = require_enum(body, "assignee_type", {"ADJUSTER", "VENDOR"})
    adjuster_id = body.get("adjuster_id")
    vendor_id = body.get("vendor_id")
    # existence of provided assignee FKs (body order: adjuster_id then vendor_id)
    adjuster = None
    vendor = None
    if adjuster_id is not None:
        adjuster = fetch("adjusters", adjuster_id)
    if vendor_id is not None:
        vendor = fetch("vendors", vendor_id)
    # well-formedness
    scope = require_str(body, "scope")
    inspection_start = require_present(body, "inspection_start")
    inspection_end = require_present(body, "inspection_end")
    start_dt = parse_dt(inspection_start)
    end_dt = parse_dt(inspection_end)
    if not (end_dt > start_dt):
        err("ERR_INVALID_REQUEST", 422, "inspection_end must be after inspection_start")
    # priority 7: assignee shape
    if assignee_type == "ADJUSTER":
        if adjuster_id is None or vendor_id is not None:
            err("ERR_ASSIGNEE_MISMATCH", 422, "ADJUSTER assignment requires adjuster_id only")
    else:  # VENDOR
        if vendor_id is None or adjuster_id is not None:
            err("ERR_ASSIGNEE_MISMATCH", 422, "VENDOR assignment requires vendor_id only")
    # priority 7: vendor credentialed
    if assignee_type == "VENDOR":
        if claim["coverage_type"] not in vendor["credentialed_coverages"]:
            err("ERR_VENDOR_NOT_CREDENTIALED", 409, "Vendor not credentialed for coverage")

    triggers_ack = (assignee_type == "ADJUSTER" and claim["status"] == "INTAKE")

    # priority 7: policy active (for the ack transition)
    if triggers_ack:
        policy = DB["policies"].get(claim["policy_id"])
        if policy is None or policy_status(policy) != "ACTIVE":
            err("ERR_POLICY_INACTIVE", 409, "Policy is not active")

    # priority 9: scheduling conflict on same assignee
    _check_window_conflict(assignee_type, adjuster_id, vendor_id, start_dt, end_dt)

    # priority 10: adjuster capacity (for the ack transition)
    if triggers_ack:
        if open_claim_count(adjuster_id) >= adjuster["max_open_claims"]:
            err("ERR_ADJUSTER_CAPACITY", 409, "Adjuster at capacity")

    rec = new_record({
        "claim_id": claim["id"],
        "assignee_type": assignee_type,
        "adjuster_id": adjuster_id if assignee_type == "ADJUSTER" else None,
        "vendor_id": vendor_id if assignee_type == "VENDOR" else None,
        "scope": scope,
        "inspection_start": inspection_start,
        "inspection_end": inspection_end,
        "status": "ACTIVE",
    })
    DB["assignments"][rec["id"]] = rec

    if triggers_ack:
        claim["assigned_adjuster_id"] = adjuster_id
        claim["ack_at"] = clock_now()
        claim["status"] = "ASSIGNED"
        touch(claim, bump_version=False)

    return ok(ser_generic(rec), 201)


def _check_window_conflict(assignee_type, adjuster_id, vendor_id, start_dt, end_dt):
    for a in DB["assignments"].values():
        if a["status"] != "ACTIVE":
            continue
        if a["assignee_type"] != assignee_type:
            continue
        if assignee_type == "ADJUSTER":
            if a["adjuster_id"] != adjuster_id:
                continue
        else:
            if a["vendor_id"] != vendor_id:
                continue
        o_start = parse_dt(a["inspection_start"])
        o_end = parse_dt(a["inspection_end"])
        if assignee_type == "ADJUSTER":
            # permitted only if separated by >= 60 minutes on either side
            separated = (start_dt - o_end >= ADJUSTER_TRAVEL_BUFFER) or \
                        (o_start - end_dt >= ADJUSTER_TRAVEL_BUFFER)
            if not separated:
                err("ERR_ASSIGNMENT_WINDOW_CONFLICT", 409, "Adjuster window conflict")
        else:
            # half-open overlap; touching endpoints allowed
            if start_dt < o_end and o_start < end_dt:
                err("ERR_ASSIGNMENT_WINDOW_CONFLICT", 409, "Vendor window conflict")


@app.route("/assignments/<rid>", methods=["GET"])
def get_assignment(rid):
    authenticate()
    return ok(ser_generic(fetch("assignments", rid)), 200)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    authenticate()
    items = list(DB["assignments"].values())
    for field in ("claim_id", "adjuster_id", "vendor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


ASSIGNMENT_ROLE_BY_TARGET = {
    "COMPLETED": {"Adjuster", "ClaimsManager"},
    "CANCELLED": {"Adjuster", "ClaimsManager"},
}


@app.route("/assignments/<rid>/transition", methods=["POST"])
def transition_assignment(rid):
    _, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager"})
    a = fetch("assignments", rid)
    body = get_body()
    to_status = require_str(body, "to_status")
    if to_status not in ASSIGNMENT_STATUSES:
        err("ERR_INVALID_REQUEST", 422, "Illegal to_status")
    role_set = ASSIGNMENT_ROLE_BY_TARGET.get(to_status)
    if role_set is not None and role not in role_set:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this transition")
    if a["status"] != "ACTIVE" or to_status not in ("COMPLETED", "CANCELLED"):
        err("ERR_INVALID_STATE", 409, "Illegal assignment transition")
    if to_status == "COMPLETED":
        a["status"] = "COMPLETED"
        touch(a)
    else:
        _cancel_assignment(a)
    return ok(ser_generic(a), 200)


def _cancel_assignment(a):
    a["status"] = "CANCELLED"
    touch(a)
    for inv in DB["vendor_invoices"].values():
        if inv["assignment_id"] == a["id"] and inv["status"] in ("SUBMITTED", "APPROVED"):
            _void_invoice(inv)


# ===========================================================================
# ReserveChange
# ===========================================================================
def _adjuster_authority(uid, account):
    adj = DB["adjusters"].get(uid)
    if adj is not None:
        return adj["authority_limit_cents"]
    return account["reserve_authority_default_cents"]


@app.route("/reserve-changes", methods=["POST"])
def create_reserve_change():
    uid, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager"})
    body = get_body()
    claim_id = require_str(body, "claim_id")
    claim = fetch("claims", claim_id)
    reserve_type = require_enum(body, "reserve_type", {"INDEMNITY", "EXPENSE"})
    delta = require_int(body, "delta_cents")
    if delta == 0:
        err("ERR_INVALID_REQUEST", 422, "delta_cents must be non-zero")
    reason = require_str(body, "reason")
    expected = require_int(body, "expected_claim_version")
    # state: claim open
    if claim["status"] not in OPEN_CLAIM_STATES:
        err("ERR_CLAIM_NOT_OPEN", 409, "Claim is not open")
    # concurrency
    if expected != claim["version"]:
        err("ERR_STALE_VERSION", 412, "Stale claim version")
    # prospective values
    ind = claim["indemnity_reserve_cents"]
    exp = claim["expense_reserve_cents"]
    if reserve_type == "INDEMNITY":
        ind = max(0, ind + delta)
    else:
        exp = max(0, exp + delta)
    # fiscal: adjuster authority
    if role == "Adjuster":
        account = DB["client_accounts"].get(claim["client_account_id"])
        limit = _adjuster_authority(uid, account)
        if ind + exp > limit:
            err("ERR_RESERVE_AUTHORITY_EXCEEDED", 422, "Reserve exceeds adjuster authority")
    # commit
    claim["indemnity_reserve_cents"] = ind
    claim["expense_reserve_cents"] = exp
    claim["version"] += 1
    touch(claim, bump_version=False)
    rec = new_record({
        "claim_id": claim["id"],
        "reserve_type": reserve_type,
        "delta_cents": delta,
        "reason": reason,
        "resulting_indemnity_reserve_cents": ind,
        "resulting_expense_reserve_cents": exp,
        "actor_role": role,
    }, common=False)
    DB["reserve_changes"][rec["id"]] = rec
    return ok(ser_generic(rec), 201)


@app.route("/reserve-changes/<rid>", methods=["GET"])
def get_reserve_change(rid):
    authenticate()
    return ok(ser_generic(fetch("reserve_changes", rid)), 200)


@app.route("/reserve-changes", methods=["GET"])
def list_reserve_changes():
    authenticate()
    items = list(DB["reserve_changes"].values())
    for field in ("claim_id", "reserve_type"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


# ===========================================================================
# Payment
# ===========================================================================
@app.route("/payments", methods=["POST"])
def create_payment():
    uid, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager"})
    body = get_body()
    claim_id = require_str(body, "claim_id")
    claim = fetch("claims", claim_id)
    payment_type = require_enum(body, "payment_type", {"INDEMNITY"})
    payee_type = require_enum(body, "payee_type", {"CLAIMANT"})
    payee_name = require_str(body, "payee_name")
    amount = require_int(body, "amount_cents")
    if amount <= 0:
        err("ERR_INVALID_REQUEST", 422, "amount_cents must be > 0")
    expected = require_int(body, "expected_claim_version")
    # state
    if claim["status"] not in OPEN_CLAIM_STATES:
        err("ERR_CLAIM_NOT_OPEN", 409, "Claim is not open")
    # concurrency
    if expected != claim["version"]:
        err("ERR_STALE_VERSION", 412, "Stale claim version")
    # requires_manager_approval
    if role == "Adjuster":
        account = DB["client_accounts"].get(claim["client_account_id"])
        limit = _adjuster_authority(uid, account)
        requires = amount > limit
    else:
        requires = False
    rec = new_record({
        "claim_id": claim["id"],
        "payment_type": payment_type,
        "payee_type": payee_type,
        "payee_name": payee_name,
        "amount_cents": amount,
        "status": "PENDING_APPROVAL",
        "requires_manager_approval": requires,
        "approved_by_role": None,
        "issued_at": None,
    })
    DB["payments"][rec["id"]] = rec
    claim["version"] += 1
    touch(claim, bump_version=False)
    return ok(ser_generic(rec), 201)


@app.route("/payments/<rid>", methods=["GET"])
def get_payment(rid):
    authenticate()
    return ok(ser_generic(fetch("payments", rid)), 200)


@app.route("/payments", methods=["GET"])
def list_payments():
    authenticate()
    items = list(DB["payments"].values())
    for field in ("claim_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


PAYMENT_ROLE_BY_TARGET = {
    "APPROVED": {"Adjuster", "ClaimsManager"},
    "REJECTED": {"ClaimsManager"},
    "ISSUED": {"FinanceOfficer"},
    "VOID": {"FinanceOfficer"},
}
PAYMENT_TRANSITIONS = {
    ("PENDING_APPROVAL", "APPROVED"),
    ("PENDING_APPROVAL", "REJECTED"),
    ("APPROVED", "ISSUED"),
    ("APPROVED", "VOID"),
    ("ISSUED", "VOID"),
}


@app.route("/payments/<rid>/transition", methods=["POST"])
def transition_payment(rid):
    _, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager", "FinanceOfficer"})
    p = fetch("payments", rid)
    body = get_body()
    to_status = require_str(body, "to_status")
    if to_status not in PAYMENT_STATUSES:
        err("ERR_INVALID_REQUEST", 422, "Illegal to_status")
    role_set = PAYMENT_ROLE_BY_TARGET.get(to_status)
    if role_set is not None and role not in role_set:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this transition")
    if (p["status"], to_status) not in PAYMENT_TRANSITIONS:
        err("ERR_INVALID_STATE", 409, "Illegal payment transition")

    claim = DB["claims"].get(p["claim_id"])

    if to_status == "APPROVED":
        if claim["status"] not in OPEN_CLAIM_STATES:
            err("ERR_CLAIM_NOT_OPEN", 409, "Claim is not open")
        # priority 10: approval authority
        if p["requires_manager_approval"] and role != "ClaimsManager":
            err("ERR_APPROVAL_AUTHORITY_REQUIRED", 403, "Manager approval required")
        p["status"] = "APPROVED"
        p["approved_by_role"] = role
        touch(p)
    elif to_status == "REJECTED":
        p["status"] = "REJECTED"
        touch(p)
    elif to_status == "ISSUED":
        # state: claim open
        if claim["status"] not in OPEN_CLAIM_STATES:
            err("ERR_CLAIM_NOT_OPEN", 409, "Claim is not open")
        # referential: policy active
        policy = DB["policies"].get(claim["policy_id"])
        if policy is None or policy_status(policy) != "ACTIVE":
            err("ERR_POLICY_INACTIVE", 409, "Policy is not active")
        # fraud
        if claim["siu_status"] == "HELD":
            err("ERR_SIU_HOLD_ACTIVE", 403, "SIU hold active")
        # fiscal: coverage
        amount = p["amount_cents"]
        if amount + claim["paid_indemnity_cents"] - policy["deductible_cents"] > policy["coverage_limit_cents"]:
            err("ERR_COVERAGE_LIMIT_EXCEEDED", 422, "Coverage limit exceeded")
        claim["paid_indemnity_cents"] += amount
        claim["indemnity_reserve_cents"] = max(0, claim["indemnity_reserve_cents"] - amount)
        p["status"] = "ISSUED"
        p["issued_at"] = clock_now()
        touch(p)
        touch(claim, bump_version=False)
    elif to_status == "VOID":
        if p["status"] == "ISSUED":
            amount = p["amount_cents"]
            claim["paid_indemnity_cents"] -= amount
            claim["indemnity_reserve_cents"] += amount
            touch(claim, bump_version=False)
        p["status"] = "VOID"
        touch(p)

    return ok(ser_generic(p), 200)


# ===========================================================================
# VendorInvoice
# ===========================================================================
def _compute_invoice_amount(vendor_type, hours, miles, materials_cents):
    rate = VENDOR_RATE_CENTS[vendor_type]
    base = round_half_up(Decimal(str(hours)) * Decimal(rate))
    mileage = round_half_up(Decimal(str(miles)) * Decimal(MILEAGE_RATE_CENTS))
    subtotal = base + mileage + materials_cents
    return max(MIN_INVOICE_CENTS, min(subtotal, VENDOR_INVOICE_CAP_CENTS))


@app.route("/vendor-invoices", methods=["POST"])
def create_vendor_invoice():
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    body = get_body()
    claim_id = require_str(body, "claim_id")
    fetch("claims", claim_id)
    assignment_id = require_str(body, "assignment_id")
    assignment = fetch("assignments", assignment_id)
    # vendor owns the assignment
    if assignment.get("vendor_id") != uid:
        err("ERR_UNAUTHORIZED", 403, "Vendor does not own the assignment")
    hours = require_number(body, "hours")
    miles = optional_number(body, "miles", 0)
    materials = optional_int(body, "materials_cents", 0)
    vendor = DB["vendors"].get(assignment["vendor_id"])
    amount = _compute_invoice_amount(vendor["vendor_type"], hours, miles, materials)
    rec = new_record({
        "claim_id": claim_id,
        "assignment_id": assignment_id,
        "vendor_id": assignment["vendor_id"],
        "hours": hours,
        "miles": miles,
        "materials_cents": materials,
        "amount_cents": amount,
        "status": "SUBMITTED",
        "approved_by_role": None,
    })
    DB["vendor_invoices"][rec["id"]] = rec
    return ok(ser_generic(rec), 201)


@app.route("/vendor-invoices/<rid>", methods=["GET"])
def get_vendor_invoice(rid):
    authenticate()
    return ok(ser_generic(fetch("vendor_invoices", rid)), 200)


@app.route("/vendor-invoices", methods=["GET"])
def list_vendor_invoices():
    authenticate()
    items = list(DB["vendor_invoices"].values())
    for field in ("claim_id", "vendor_id", "assignment_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [i for i in items if i.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


INVOICE_ROLE_BY_TARGET = {
    "APPROVED": {"ClaimsManager"},
    "REJECTED": {"ClaimsManager"},
    "PAID": {"FinanceOfficer"},
    "VOID": {"FinanceOfficer"},
}
INVOICE_TRANSITIONS = {
    ("SUBMITTED", "APPROVED"),
    ("SUBMITTED", "REJECTED"),
    ("APPROVED", "PAID"),
    ("APPROVED", "VOID"),
}


@app.route("/vendor-invoices/<rid>/transition", methods=["POST"])
def transition_vendor_invoice(rid):
    _, role = authenticate()
    authorize(role, {"ClaimsManager", "FinanceOfficer"})
    inv = fetch("vendor_invoices", rid)
    body = get_body()
    to_status = require_str(body, "to_status")
    if to_status not in INVOICE_STATUSES:
        err("ERR_INVALID_REQUEST", 422, "Illegal to_status")
    role_set = INVOICE_ROLE_BY_TARGET.get(to_status)
    if role_set is not None and role not in role_set:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this transition")
    if (inv["status"], to_status) not in INVOICE_TRANSITIONS:
        err("ERR_INVALID_STATE", 409, "Illegal invoice transition")

    claim = DB["claims"].get(inv["claim_id"])
    amount = inv["amount_cents"]

    if to_status == "APPROVED":
        policy = DB["policies"].get(claim["policy_id"])
        if amount + claim["paid_expense_cents"] + claim["expense_reserve_cents"] > policy["per_claim_expense_limit_cents"]:
            err("ERR_EXPENSE_LIMIT_EXCEEDED", 422, "Expense limit exceeded")
        claim["expense_reserve_cents"] += amount
        inv["status"] = "APPROVED"
        inv["approved_by_role"] = role
        touch(inv)
        touch(claim, bump_version=False)
    elif to_status == "REJECTED":
        inv["status"] = "REJECTED"
        touch(inv)
    elif to_status == "PAID":
        if claim["status"] not in OPEN_CLAIM_STATES:
            err("ERR_CLAIM_NOT_OPEN", 409, "Claim is not open")
        if claim["siu_status"] == "HELD":
            err("ERR_SIU_HOLD_ACTIVE", 403, "SIU hold active")
        claim["paid_expense_cents"] += amount
        claim["expense_reserve_cents"] = max(0, claim["expense_reserve_cents"] - amount)
        inv["status"] = "PAID"
        touch(inv)
        touch(claim, bump_version=False)
    elif to_status == "VOID":
        _void_invoice(inv)

    return ok(ser_generic(inv), 200)


def _void_invoice(inv):
    if inv["status"] == "APPROVED":
        claim = DB["claims"].get(inv["claim_id"])
        if claim is not None:
            claim["expense_reserve_cents"] -= inv["amount_cents"]
            touch(claim, bump_version=False)
    inv["status"] = "VOID"
    touch(inv)


# ===========================================================================
# LitigationCase
# ===========================================================================
@app.route("/litigation-cases", methods=["POST"])
def create_litigation():
    _, role = authenticate()
    authorize(role, {"ClaimsManager"})
    body = get_body()
    claim_id = require_str(body, "claim_id")
    fetch("claims", claim_id)
    defense_vendor_id = body.get("defense_vendor_id")
    if defense_vendor_id is not None:
        fetch("vendors", defense_vendor_id)
    venue = require_str(body, "venue")
    rec = new_record({
        "claim_id": claim_id,
        "defense_vendor_id": defense_vendor_id,
        "venue": venue,
        "status": "OPEN",
    })
    DB["litigation_cases"][rec["id"]] = rec
    return ok(ser_generic(rec), 201)


@app.route("/litigation-cases/<rid>", methods=["GET"])
def get_litigation(rid):
    authenticate()
    return ok(ser_generic(fetch("litigation_cases", rid)), 200)


@app.route("/litigation-cases", methods=["GET"])
def list_litigation():
    authenticate()
    items = list(DB["litigation_cases"].values())
    for field in ("claim_id", "defense_vendor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [l for l in items if l.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


LITIGATION_TRANSITIONS = {
    ("OPEN", "IN_SUIT"),
    ("OPEN", "DISMISSED"),
    ("IN_SUIT", "SETTLED"),
    ("IN_SUIT", "DISMISSED"),
    ("IN_SUIT", "JUDGMENT"),
}


@app.route("/litigation-cases/<rid>/transition", methods=["POST"])
def transition_litigation(rid):
    _, role = authenticate()
    authorize(role, {"ClaimsManager"})
    l = fetch("litigation_cases", rid)
    body = get_body()
    to_status = require_str(body, "to_status")
    if to_status not in LITIGATION_STATUSES:
        err("ERR_INVALID_REQUEST", 422, "Illegal to_status")
    if (l["status"], to_status) not in LITIGATION_TRANSITIONS:
        err("ERR_INVALID_STATE", 409, "Illegal litigation transition")
    l["status"] = to_status
    touch(l)
    return ok(ser_generic(l), 200)


# ===========================================================================
# SubrogationCase
# ===========================================================================
@app.route("/subrogation-cases", methods=["POST"])
def create_subrogation():
    _, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager"})
    body = get_body()
    claim_id = require_str(body, "claim_id")
    fetch("claims", claim_id)
    at_fault_party = require_str(body, "at_fault_party")
    demand = require_int(body, "demand_cents")
    if demand <= 0:
        err("ERR_INVALID_REQUEST", 422, "demand_cents must be > 0")
    rec = new_record({
        "claim_id": claim_id,
        "at_fault_party": at_fault_party,
        "demand_cents": demand,
        "recovered_cents": 0,
        "allocation_method": None,
        "status": "OPEN",
    })
    DB["subrogation_cases"][rec["id"]] = rec
    return ok(ser_generic(rec), 201)


@app.route("/subrogation-cases/<rid>", methods=["GET"])
def get_subrogation(rid):
    authenticate()
    return ok(ser_generic(fetch("subrogation_cases", rid)), 200)


@app.route("/subrogation-cases", methods=["GET"])
def list_subrogation():
    authenticate()
    items = list(DB["subrogation_cases"].values())
    for field in ("claim_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


SUBROGATION_TRANSITIONS = {
    ("OPEN", "DEMAND_SENT"),
    ("DEMAND_SENT", "NEGOTIATING"),
    ("NEGOTIATING", "RECOVERED"),
    ("OPEN", "CLOSED_NO_RECOVERY"),
    ("DEMAND_SENT", "CLOSED_NO_RECOVERY"),
    ("NEGOTIATING", "CLOSED_NO_RECOVERY"),
}
SUBROGATION_ROLE_BY_TARGET = {
    "DEMAND_SENT": {"Adjuster", "ClaimsManager"},
    "NEGOTIATING": {"Adjuster", "ClaimsManager"},
    "CLOSED_NO_RECOVERY": {"Adjuster", "ClaimsManager"},
    "RECOVERED": {"FinanceOfficer"},
}


@app.route("/subrogation-cases/<rid>/transition", methods=["POST"])
def transition_subrogation(rid):
    _, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager", "FinanceOfficer"})
    s = fetch("subrogation_cases", rid)
    body = get_body()
    to_status = require_str(body, "to_status")
    if to_status not in SUBROGATION_STATUSES:
        err("ERR_INVALID_REQUEST", 422, "Illegal to_status")
    role_set = SUBROGATION_ROLE_BY_TARGET.get(to_status)
    if role_set is not None and role not in role_set:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this transition")

    if to_status == "RECOVERED":
        # well-formedness of recovery fields
        recovered = require_int(body, "recovered_cents")
        if recovered <= 0:
            err("ERR_INVALID_REQUEST", 422, "recovered_cents must be > 0")
        allocation_method = require_enum(body, "allocation_method", {"PRO_RATA", "INDEMNITY_FIRST"})
        expected = require_int(body, "expected_claim_version")
        # state
        if (s["status"], to_status) not in SUBROGATION_TRANSITIONS:
            err("ERR_INVALID_STATE", 409, "Illegal subrogation transition")
        claim = DB["claims"].get(s["claim_id"])
        # concurrency
        if expected != claim["version"]:
            err("ERR_STALE_VERSION", 412, "Stale claim version")
        _apply_recovery(claim, s, recovered, allocation_method)
        s["status"] = "RECOVERED"
        s["recovered_cents"] = recovered
        s["allocation_method"] = allocation_method
        touch(s)
    else:
        if (s["status"], to_status) not in SUBROGATION_TRANSITIONS:
            err("ERR_INVALID_STATE", 409, "Illegal subrogation transition")
        s["status"] = to_status
        touch(s)

    return ok(ser_generic(s), 200)


def _apply_recovery(claim, s, recovered, method):
    paid_i = claim["paid_indemnity_cents"]
    paid_e = claim["paid_expense_cents"]
    base = paid_i + paid_e
    if method == "PRO_RATA":
        if base == 0:
            rec_i = recovered
            rec_e = 0
        else:
            rec_i = round_half_up(Decimal(recovered) * Decimal(paid_i) / Decimal(base))
            rec_e = recovered - rec_i
    else:  # INDEMNITY_FIRST
        rec_i = min(recovered, paid_i)
        rec_e = recovered - rec_i
    claim["recovered_indemnity_cents"] += rec_i
    claim["recovered_expense_cents"] += rec_e
    claim["recovered_cents"] += recovered
    touch(claim, bump_version=False)


# ===========================================================================
# SiuReferral
# ===========================================================================
@app.route("/siu-referrals", methods=["POST"])
def create_siu_referral():
    _, role = authenticate()
    authorize(role, {"Adjuster", "ClaimsManager", "SiuInvestigator"})
    body = get_body()
    claim_id = require_str(body, "claim_id")
    claim = fetch("claims", claim_id)
    reason = require_str(body, "reason")
    place_hold = body.get("place_hold", True)
    if not isinstance(place_hold, bool):
        err("ERR_INVALID_REQUEST", 422, "place_hold must be boolean")
    rec = new_record({
        "claim_id": claim_id,
        "reason": reason,
        "place_hold": place_hold,
        "status": "OPEN",
    })
    DB["siu_referrals"][rec["id"]] = rec
    if place_hold:
        claim["siu_status"] = "HELD"
        touch(claim, bump_version=False)
    return ok(ser_generic(rec), 201)


@app.route("/siu-referrals/<rid>", methods=["GET"])
def get_siu_referral(rid):
    authenticate()
    return ok(ser_generic(fetch("siu_referrals", rid)), 200)


@app.route("/siu-referrals", methods=["GET"])
def list_siu_referrals():
    authenticate()
    items = list(DB["siu_referrals"].values())
    for field in ("claim_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


SIU_TRANSITIONS = {
    ("OPEN", "CLEARED"),
    ("OPEN", "CONFIRMED"),
}


@app.route("/siu-referrals/<rid>/transition", methods=["POST"])
def transition_siu_referral(rid):
    _, role = authenticate()
    authorize(role, {"SiuInvestigator"})
    r = fetch("siu_referrals", rid)
    body = get_body()
    to_status = require_str(body, "to_status")
    if to_status not in SIU_STATUSES:
        err("ERR_INVALID_REQUEST", 422, "Illegal to_status")
    if (r["status"], to_status) not in SIU_TRANSITIONS:
        err("ERR_INVALID_STATE", 409, "Illegal SIU transition")
    claim = DB["claims"].get(r["claim_id"])
    if to_status == "CLEARED":
        if claim is not None and claim["siu_status"] == "HELD":
            claim["siu_status"] = "CLEARED"
            touch(claim, bump_version=False)
    else:  # CONFIRMED
        if claim is not None:
            claim["siu_status"] = "CONFIRMED"
            touch(claim, bump_version=False)
    r["status"] = to_status
    touch(r)
    return ok(ser_generic(r), 200)


# ===========================================================================
# BordereauReport
# ===========================================================================
@app.route("/bordereau-reports", methods=["POST"])
def create_bordereau():
    _, role = authenticate()
    authorize(role, {"ClaimsManager", "FinanceOfficer"})
    body = get_body()
    account_id = require_str(body, "client_account_id")
    fetch("client_accounts", account_id)
    period_start = require_present(body, "period_start")
    period_end = require_present(body, "period_end")
    basis = require_enum(body, "basis", {"PROVISIONAL", "DEVELOPED"})
    start_dt = parse_dt(period_start)
    end_dt = parse_dt(period_end)
    if not (end_dt > start_dt):
        err("ERR_INVALID_REQUEST", 422, "period_end must be after period_start")

    count = 0
    total_incurred = 0
    total_paid = 0
    total_recovered = 0
    for c in DB["claims"].values():
        if c["client_account_id"] != account_id:
            continue
        if c["status"] == "CANCELLED":
            continue
        rd = parse_dt(c["reported_date"])
        if not (start_dt <= rd < end_dt):
            continue
        count += 1
        if basis == "DEVELOPED":
            incurred_cents = claim_developed_gross(c)
        else:
            incurred_cents = claim_gross_incurred(c)
        paid_cents = c["paid_indemnity_cents"] + c["paid_expense_cents"]
        total_incurred += round_half_up(Decimal(incurred_cents) / Decimal(100))
        total_paid += round_half_up(Decimal(paid_cents) / Decimal(100))
        total_recovered += round_half_up(Decimal(c["recovered_cents"]) / Decimal(100))

    rec = new_record({
        "client_account_id": account_id,
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
        "total_claim_count": count,
        "total_incurred_dollars": total_incurred,
        "total_paid_dollars": total_paid,
        "total_recovered_dollars": total_recovered,
    })
    DB["bordereau_reports"][rec["id"]] = rec
    return ok(ser_generic(rec), 201)


@app.route("/bordereau-reports/<rid>", methods=["GET"])
def get_bordereau(rid):
    authenticate()
    return ok(ser_generic(fetch("bordereau_reports", rid)), 200)


@app.route("/bordereau-reports", methods=["GET"])
def list_bordereau():
    authenticate()
    items = list(DB["bordereau_reports"].values())
    for field in ("client_account_id", "basis"):
        val = request.args.get(field)
        if val is not None:
            items = [b for b in items if b.get(field) == val]
    page, meta = paginate(items)
    return ok([ser_generic(r) for r in page], 200, is_list=True, pagination=meta)


# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
