"""
Restitution & Court-Fee Collection API — Python + Flask, in-memory only.

Boots empty on every process start; no seeding, no disk persistence.
Storage is Python dicts keyed by id; a fresh process wipes all state.
"""
import math
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify, g

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"CollectionsClerk", "CollectionsSupervisor", "FinanceOfficer", "SystemAdmin"}

OBLIGATION_TYPES = {"RESTITUTION", "COURT_FEE", "FINE", "SURCHARGE"}
DEFAULT_PRIORITY_RANK = {"RESTITUTION": 1, "COURT_FEE": 2, "FINE": 3, "SURCHARGE": 4}
ALLOCATION_METHODS = {"STATUTORY_PRIORITY", "PRO_RATA"}
ABILITY_METHODS = {"NET_DISPOSABLE", "GROSS_INCOME"}

ABILITY_TO_PAY_RATE = Decimal("0.10")
MIN_INSTALLMENT_CENTS = 2500
DELINQUENCY_GRACE_DAYS = 30
PLAN_DUE_INTERVAL_DAYS = 30
WRITEOFF_AGE_DAYS = 1825
MAX_MONTHLY_WITHHOLD_CENTS = 50000

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.cases = {}
        self.victims = {}
        self.obligations = {}
        self.payment_plans = {}
        self.payments = {}
        self.disbursements = {}
        self.wage_assignments = {}
        self.enforcement_actions = {}
        self.waiver_requests = {}
        self.amnesty_programs = {}
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
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def now():
    return db.clock


def iso_millis(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 date/datetime into an aware UTC datetime, or raise 400."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def floor_days(later, earlier):
    return math.floor((later - earlier).total_seconds() / 86400.0)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def make_meta(pagination=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": iso_millis(now())}
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


def base_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_role(allowed):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid X-User-Role")
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "role not permitted")
    return role


def user_id():
    return request.headers.get("X-User-ID")


ALL_ROLES = ROLES  # any authenticated role may read


# ---------------------------------------------------------------------------
# Body helpers (well-formedness)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "body must be a JSON object")
    return body


def require_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing field: %s" % field)
    return body[field]


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be an integer" % field)
    return value


def require_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a non-empty string" % field)
    return v


def require_pos_int(body, field):
    v = as_int(require_present(body, field), field)
    if v <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be > 0" % field)
    return v


def require_nonneg_int(body, field):
    v = as_int(require_present(body, field), field)
    if v < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be >= 0" % field)
    return v


def require_enum(body, field, allowed):
    v = require_present(body, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s invalid" % field)
    return v


# ---------------------------------------------------------------------------
# Existence resolution (left-to-right)
# ---------------------------------------------------------------------------
def resolve(collection, ident):
    rec = collection.get(ident)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return rec


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------
def ob_balance(ob):
    if ob["status"] in ("WRITTEN_OFF", "WAIVED"):
        return 0
    return max(0, ob["assessed_amount_cents"] - ob["paid_amount_cents"] - ob["waived_amount_cents"])


def case_obligations(case_id):
    return [o for o in db.obligations.values() if o["case_id"] == case_id]


def reconcile_case(case):
    obs = case_obligations(case["id"])
    total_assessed = sum(o["assessed_amount_cents"] for o in obs)
    total_paid = sum(o["paid_amount_cents"] for o in obs)
    total_waived = sum(o["waived_amount_cents"] for o in obs)
    total_written_off = 0
    for o in obs:
        if o["status"] == "WRITTEN_OFF":
            total_written_off += max(
                0, o["assessed_amount_cents"] - o["paid_amount_cents"] - o["waived_amount_cents"]
            )
    balance = sum(
        ob_balance(o) for o in obs if o["status"] not in ("WRITTEN_OFF", "WAIVED")
    )
    case["total_assessed_cents"] = total_assessed
    case["total_paid_cents"] = total_paid
    case["total_waived_cents"] = total_waived
    case["total_written_off_cents"] = total_written_off
    case["balance_cents"] = balance
    case["status"] = "SATISFIED" if (total_assessed > 0 and balance == 0) else "OPEN"


def victim_payable(victim_id):
    collected = 0
    for p in db.payments.values():
        if p["status"] != "POSTED":
            continue
        for line in p["allocations"]:
            ob = db.obligations.get(line["obligation_id"])
            if ob and ob["obligation_type"] == "RESTITUTION" and ob["victim_id"] == victim_id:
                collected += line["amount_cents"]
    disbursed = sum(
        d["amount_cents"]
        for d in db.disbursements.values()
        if d["victim_id"] == victim_id and d["status"] == "PENDING"
    )
    return max(0, collected - disbursed)


def refresh_obligation_status(ob):
    """Toggle OUTSTANDING/PARTIALLY_PAID/SATISFIED based on paid+waived (payment/reversal path)."""
    if ob["status"] in ("WAIVED", "WRITTEN_OFF"):
        return
    tot = ob["paid_amount_cents"] + ob["waived_amount_cents"]
    if tot >= ob["assessed_amount_cents"]:
        ob["status"] = "SATISFIED"
    elif tot > 0:
        ob["status"] = "PARTIALLY_PAID"
    else:
        ob["status"] = "OUTSTANDING"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def ser_common(rec):
    return {
        "id": rec["id"],
        "created_at": iso_millis(rec["created_at"]),
        "updated_at": iso_millis(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_case(c):
    d = ser_common(c)
    d.update(
        {
            "case_number": c["case_number"],
            "defendant_name": c["defendant_name"],
            "status": c["status"],
            "delinquency_status": c["delinquency_status"],
            "total_assessed_cents": c["total_assessed_cents"],
            "total_paid_cents": c["total_paid_cents"],
            "total_waived_cents": c["total_waived_cents"],
            "total_written_off_cents": c["total_written_off_cents"],
            "balance_cents": c["balance_cents"],
        }
    )
    return d


def ser_victim(v):
    d = ser_common(v)
    d.update({"name": v["name"], "payable_balance_cents": victim_payable(v["id"])})
    return d


def ser_obligation(o):
    d = ser_common(o)
    d.update(
        {
            "case_id": o["case_id"],
            "victim_id": o["victim_id"],
            "obligation_type": o["obligation_type"],
            "assessed_amount_cents": o["assessed_amount_cents"],
            "priority_rank": o["priority_rank"],
            "paid_amount_cents": o["paid_amount_cents"],
            "waived_amount_cents": o["waived_amount_cents"],
            "balance_cents": ob_balance(o),
            "status": o["status"],
        }
    )
    return d


def ser_plan(p):
    d = ser_common(p)
    d.update(
        {
            "case_id": p["case_id"],
            "monthly_income_cents": p["monthly_income_cents"],
            "monthly_expenses_cents": p["monthly_expenses_cents"],
            "ability_to_pay_method": p["ability_to_pay_method"],
            "monthly_amount_cents": p["monthly_amount_cents"],
            "next_due_date": iso_millis(p["next_due_date"]) if p["next_due_date"] else None,
            "missed_payment_count": p["missed_payment_count"],
            "status": p["status"],
        }
    )
    return d


def ser_payment(p):
    d = ser_common(p)
    d.update(
        {
            "case_id": p["case_id"],
            "amount_cents": p["amount_cents"],
            "allocation_method": p["allocation_method"],
            "allocations": [
                {"obligation_id": a["obligation_id"], "amount_cents": a["amount_cents"]}
                for a in p["allocations"]
            ],
            "status": p["status"],
        }
    )
    return d


def ser_disbursement(x):
    d = ser_common(x)
    d.update(
        {
            "victim_id": x["victim_id"],
            "case_id": x["case_id"],
            "amount_cents": x["amount_cents"],
            "status": x["status"],
        }
    )
    return d


def ser_wage(w):
    d = ser_common(w)
    d.update(
        {
            "case_id": w["case_id"],
            "employer_name": w["employer_name"],
            "monthly_withhold_cents": w["monthly_withhold_cents"],
            "effective_start_date": w["effective_start_date_raw"],
            "effective_end_date": w["effective_end_date_raw"],
            "status": w["status"],
        }
    )
    return d


def ser_enforcement(e):
    d = ser_common(e)
    d.update(
        {
            "case_id": e["case_id"],
            "type": e["type"],
            "amount_cents": e["amount_cents"],
            "status": e["status"],
        }
    )
    return d


def ser_waiver(w):
    d = ser_common(w)
    d.update(
        {
            "case_id": w["case_id"],
            "obligation_id": w["obligation_id"],
            "requested_amount_cents": w["requested_amount_cents"],
            "requested_by_user_id": w["requested_by_user_id"],
            "approved_by_user_id": w["approved_by_user_id"],
            "status": w["status"],
        }
    )
    return d


def ser_amnesty(a):
    d = ser_common(a)
    d.update(
        {
            "name": a["name"],
            "start_date": a["start_date_raw"],
            "end_date": a["end_date_raw"],
            "waiver_pct": a["waiver_pct"],
        }
    )
    return d


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid limit")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid offset")
        if offset < 0:
            offset = 0

    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# ===========================================================================
# CASE
# ===========================================================================
@app.route("/collections/cases", methods=["POST"])
def create_case():
    require_role({"CollectionsClerk"})
    body = get_body()
    case_number = require_str(body, "case_number")
    defendant_name = require_str(body, "defendant_name")
    # uniqueness (tier 10)
    for c in db.cases.values():
        if c["case_number"] == case_number:
            raise ApiError("ERR_CASE_NUMBER_TAKEN", 409, "case_number already used")
    rec = base_record()
    rec.update(
        {
            "case_number": case_number,
            "defendant_name": defendant_name,
            "status": "OPEN",
            "delinquency_status": "CURRENT",
            "total_assessed_cents": 0,
            "total_paid_cents": 0,
            "total_waived_cents": 0,
            "total_written_off_cents": 0,
            "balance_cents": 0,
        }
    )
    db.cases[rec["id"]] = rec
    return ok(ser_case(rec), 201)


@app.route("/collections/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_role(ALL_ROLES)
    c = resolve(db.cases, case_id)
    reconcile_case(c)
    return ok(ser_case(c), 200)


# ===========================================================================
# VICTIM
# ===========================================================================
@app.route("/collections/victims", methods=["POST"])
def create_victim():
    require_role({"CollectionsClerk"})
    body = get_body()
    name = require_str(body, "name")
    rec = base_record()
    rec.update({"name": name})
    db.victims[rec["id"]] = rec
    return ok(ser_victim(rec), 201)


@app.route("/collections/victims/<victim_id>", methods=["GET"])
def get_victim(victim_id):
    require_role(ALL_ROLES)
    v = resolve(db.victims, victim_id)
    return ok(ser_victim(v), 200)


# ===========================================================================
# OBLIGATION
# ===========================================================================
@app.route("/collections/obligations", methods=["POST"])
def create_obligation():
    require_role({"CollectionsClerk"})
    body = get_body()
    # existence (tier 3): body FKs left-to-right (case_id then victim_id if present)
    case = None
    if body.get("case_id") is not None:
        case = resolve(db.cases, body["case_id"])
    if body.get("victim_id") is not None:
        resolve(db.victims, body["victim_id"])
    # well-formedness (tier 4)
    require_present(body, "case_id")
    case = resolve(db.cases, body["case_id"])
    obligation_type = require_enum(body, "obligation_type", OBLIGATION_TYPES)
    assessed = require_pos_int(body, "assessed_amount_cents")
    priority_rank = body.get("priority_rank")
    if priority_rank is not None:
        priority_rank = as_int(priority_rank, "priority_rank")
    victim_id = body.get("victim_id")
    # referential business rule (tier 7): victim pairing
    if obligation_type == "RESTITUTION":
        if victim_id is None:
            raise ApiError("ERR_VICTIM_REQUIRED", 422, "victim_id required for RESTITUTION")
    else:
        if victim_id is not None:
            raise ApiError("ERR_VICTIM_REQUIRED", 422, "victim_id forbidden for non-restitution")
    if priority_rank is None:
        priority_rank = DEFAULT_PRIORITY_RANK[obligation_type]

    rec = base_record()
    rec.update(
        {
            "case_id": case["id"],
            "victim_id": victim_id,
            "obligation_type": obligation_type,
            "assessed_amount_cents": assessed,
            "priority_rank": priority_rank,
            "paid_amount_cents": 0,
            "waived_amount_cents": 0,
            "status": "OUTSTANDING",
        }
    )
    db.obligations[rec["id"]] = rec
    reconcile_case(case)
    touch(case)
    return ok(ser_obligation(rec), 201)


@app.route("/collections/obligations/<obligation_id>", methods=["GET"])
def get_obligation(obligation_id):
    require_role(ALL_ROLES)
    o = resolve(db.obligations, obligation_id)
    return ok(ser_obligation(o), 200)


@app.route("/collections/obligations", methods=["GET"])
def list_obligations():
    require_role(ALL_ROLES)
    items = list(db.obligations.values())
    case_id = request.args.get("case_id")
    victim_id = request.args.get("victim_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [o for o in items if o["case_id"] == case_id]
    if victim_id is not None:
        items = [o for o in items if o["victim_id"] == victim_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, pg = paginate(items)
    return ok([ser_obligation(o) for o in page], 200, pagination=pg, is_array=True)


@app.route("/collections/obligations/<obligation_id>/write-off", methods=["POST"])
def write_off(obligation_id):
    require_role({"CollectionsSupervisor"})
    o = resolve(db.obligations, obligation_id)
    # aging (tier 10) — PRD §3.7 does not define an ERR_INVALID_STATE gate for
    # write-off; the two documented rejections are aging then balance.
    age = floor_days(now(), o["created_at"])
    if age < WRITEOFF_AGE_DAYS:
        raise ApiError("ERR_WRITEOFF_TOO_EARLY", 409, "obligation not old enough")
    if ob_balance(o) <= 0:
        raise ApiError("ERR_NOTHING_TO_WRITE_OFF", 409, "nothing to write off")
    o["status"] = "WRITTEN_OFF"
    touch(o)
    case = db.cases[o["case_id"]]
    reconcile_case(case)
    touch(case)
    return ok(ser_obligation(o), 200)


# ===========================================================================
# PAYMENT PLAN
# ===========================================================================
def compute_installment(method, income, expenses, case_balance):
    if method == "NET_DISPOSABLE":
        basis = max(0, income - expenses)
    else:  # GROSS_INCOME
        basis = income
    raw = int((Decimal(basis) * ABILITY_TO_PAY_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    monthly = max(MIN_INSTALLMENT_CENTS, raw)
    monthly = min(monthly, case_balance)
    return monthly


@app.route("/collections/payment-plans", methods=["POST"])
def create_plan():
    require_role({"CollectionsClerk"})
    body = get_body()
    # existence (tier 3)
    if body.get("case_id") is not None:
        resolve(db.cases, body["case_id"])
    # well-formedness (tier 4)
    require_present(body, "case_id")
    case = resolve(db.cases, body["case_id"])
    income = require_nonneg_int(body, "monthly_income_cents")
    expenses = require_nonneg_int(body, "monthly_expenses_cents")
    method = require_enum(body, "ability_to_pay_method", ABILITY_METHODS)
    expected = as_int(require_present(body, "expected_case_version"), "expected_case_version")
    # OCC (tier 5)
    if expected != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412, "stale case version")

    reconcile_case(case)
    monthly = compute_installment(method, income, expenses, case["balance_cents"])

    # supersede any still-PROPOSED plan on this case
    for p in db.payment_plans.values():
        if p["case_id"] == case["id"] and p["status"] == "PROPOSED":
            p["status"] = "SUPERSEDED"
            touch(p)

    rec = base_record()
    rec.update(
        {
            "case_id": case["id"],
            "monthly_income_cents": income,
            "monthly_expenses_cents": expenses,
            "ability_to_pay_method": method,
            "monthly_amount_cents": monthly,
            "next_due_date": None,
            "missed_payment_count": 0,
            "status": "PROPOSED",
        }
    )
    db.payment_plans[rec["id"]] = rec
    # plan creation increments case version by 1
    touch(case)
    return ok(ser_plan(rec), 201)


@app.route("/collections/payment-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    require_role(ALL_ROLES)
    p = resolve(db.payment_plans, plan_id)
    return ok(ser_plan(p), 200)


@app.route("/collections/payment-plans", methods=["GET"])
def list_plans():
    require_role(ALL_ROLES)
    items = list(db.payment_plans.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    page, pg = paginate(items)
    return ok([ser_plan(p) for p in page], 200, pagination=pg, is_array=True)


@app.route("/collections/payment-plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    require_role({"CollectionsSupervisor"})
    p = resolve(db.payment_plans, plan_id)
    if p["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not PROPOSED")
    case = db.cases[p["case_id"]]
    reconcile_case(case)
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", 409, "case not open")
    for other in db.payment_plans.values():
        if other["case_id"] == case["id"] and other["status"] == "ACTIVE":
            raise ApiError("ERR_ACTIVE_PLAN_EXISTS", 409, "case already has active plan")
    p["status"] = "ACTIVE"
    p["next_due_date"] = now() + timedelta(days=PLAN_DUE_INTERVAL_DAYS)
    touch(p)
    return ok(ser_plan(p), 200)


@app.route("/collections/payment-plans/<plan_id>/reinstate", methods=["POST"])
def reinstate_plan(plan_id):
    require_role({"CollectionsSupervisor"})
    p = resolve(db.payment_plans, plan_id)
    if p["status"] != "DEFAULTED":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not DEFAULTED")
    case = db.cases[p["case_id"]]
    reconcile_case(case)
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", 409, "case not open")
    p["status"] = "ACTIVE"
    p["missed_payment_count"] = 0
    p["next_due_date"] = now() + timedelta(days=PLAN_DUE_INTERVAL_DAYS)
    touch(p)
    case["delinquency_status"] = "CURRENT"
    touch(case)
    return ok(ser_plan(p), 200)


# ===========================================================================
# PAYMENT
# ===========================================================================
def allocate_payment(case, amount, method):
    candidates = [
        o
        for o in case_obligations(case["id"])
        if o["status"] in ("OUTSTANDING", "PARTIALLY_PAID") and ob_balance(o) > 0
    ]
    candidates.sort(key=lambda o: (o["priority_rank"], o["created_at"], o["_seq"]))
    lines = []
    if method == "STATUTORY_PRIORITY":
        remaining = amount
        for o in candidates:
            if remaining <= 0:
                break
            alloc = min(remaining, ob_balance(o))
            if alloc > 0:
                lines.append((o, alloc))
                remaining -= alloc
    else:  # PRO_RATA
        total = sum(ob_balance(o) for o in candidates)
        allocs = {}
        if total > 0:
            for o in candidates:
                allocs[o["id"]] = (amount * ob_balance(o)) // total
            remainder = amount - sum(allocs.values())
            i = 0
            while remainder > 0 and i < len(candidates):
                allocs[candidates[i]["id"]] += 1
                remainder -= 1
                i += 1
        for o in candidates:
            a = allocs.get(o["id"], 0)
            if a > 0:
                lines.append((o, a))
    return lines


@app.route("/collections/payments", methods=["POST"])
def create_payment():
    require_role({"CollectionsClerk"})
    body = get_body()
    if body.get("case_id") is not None:
        resolve(db.cases, body["case_id"])
    require_present(body, "case_id")
    case = resolve(db.cases, body["case_id"])
    amount = require_pos_int(body, "amount_cents")
    method = require_enum(body, "allocation_method", ALLOCATION_METHODS)
    # fiscal (tier 11)
    reconcile_case(case)
    if amount > case["balance_cents"]:
        raise ApiError("ERR_AMOUNT_EXCEEDS_BALANCE", 409, "payment exceeds case balance")

    lines = allocate_payment(case, amount, method)

    rec = base_record()
    rec.update(
        {
            "case_id": case["id"],
            "amount_cents": amount,
            "allocation_method": method,
            "allocations": [],
            "status": "POSTED",
        }
    )
    for o, alloc in lines:
        o["paid_amount_cents"] += alloc
        refresh_obligation_status(o)
        touch(o)
        rec["allocations"].append({"obligation_id": o["id"], "amount_cents": alloc})
    db.payments[rec["id"]] = rec

    reconcile_case(case)
    touch(case)
    # active plan completes when case balance reaches 0
    if case["balance_cents"] == 0 and case["total_assessed_cents"] > 0:
        for p in db.payment_plans.values():
            if p["case_id"] == case["id"] and p["status"] == "ACTIVE":
                p["status"] = "COMPLETED"
                touch(p)
    return ok(ser_payment(rec), 201)


@app.route("/collections/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    require_role(ALL_ROLES)
    p = resolve(db.payments, payment_id)
    return ok(ser_payment(p), 200)


@app.route("/collections/payments", methods=["GET"])
def list_payments():
    require_role(ALL_ROLES)
    items = list(db.payments.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    page, pg = paginate(items)
    return ok([ser_payment(p) for p in page], 200, pagination=pg, is_array=True)


@app.route("/collections/payments/<payment_id>/reverse", methods=["POST"])
def reverse_payment(payment_id):
    require_role({"CollectionsSupervisor"})
    p = resolve(db.payments, payment_id)
    if p["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", 409, "payment not POSTED")
    # fiscal (tier 11): reversal must keep each affected victim payable >= 0
    reversed_by_victim = {}
    for line in p["allocations"]:
        ob = db.obligations.get(line["obligation_id"])
        if ob and ob["obligation_type"] == "RESTITUTION" and ob["victim_id"] is not None:
            reversed_by_victim[ob["victim_id"]] = (
                reversed_by_victim.get(ob["victim_id"], 0) + line["amount_cents"]
            )
    for vid, amt in reversed_by_victim.items():
        if victim_payable(vid) - amt < 0:
            raise ApiError(
                "ERR_AMOUNT_EXCEEDS_BALANCE", 409, "reversal would drive victim payable below 0"
            )
    # apply compensation
    touched_cases = set()
    for line in p["allocations"]:
        ob = db.obligations.get(line["obligation_id"])
        if ob is None:
            continue
        ob["paid_amount_cents"] -= line["amount_cents"]
        if ob["paid_amount_cents"] < 0:
            ob["paid_amount_cents"] = 0
        refresh_obligation_status(ob)
        touch(ob)
        touched_cases.add(ob["case_id"])
    p["status"] = "REVERSED"
    p["allocations"] = []
    touch(p)
    case = db.cases[p["case_id"]]
    touched_cases.add(case["id"])
    for cid in touched_cases:
        c = db.cases.get(cid)
        if c:
            reconcile_case(c)
            touch(c)
    return ok(ser_payment(p), 200)


# ===========================================================================
# DISBURSEMENT
# ===========================================================================
@app.route("/collections/disbursements", methods=["POST"])
def create_disbursement():
    require_role({"FinanceOfficer"})
    body = get_body()
    # existence: body order [victim_id, case_id]
    if body.get("victim_id") is not None:
        resolve(db.victims, body["victim_id"])
    if body.get("case_id") is not None:
        resolve(db.cases, body["case_id"])
    require_present(body, "victim_id")
    victim = resolve(db.victims, body["victim_id"])
    require_present(body, "case_id")
    resolve(db.cases, body["case_id"])
    amount = require_pos_int(body, "amount_cents")
    # fiscal (tier 11)
    if amount > victim_payable(victim["id"]):
        raise ApiError("ERR_AMOUNT_EXCEEDS_BALANCE", 409, "disbursement exceeds victim payable")
    rec = base_record()
    rec.update(
        {
            "victim_id": victim["id"],
            "case_id": body["case_id"],
            "amount_cents": amount,
            "status": "PENDING",
        }
    )
    db.disbursements[rec["id"]] = rec
    return ok(ser_disbursement(rec), 201)


@app.route("/collections/disbursements/<disbursement_id>", methods=["GET"])
def get_disbursement(disbursement_id):
    require_role(ALL_ROLES)
    d = resolve(db.disbursements, disbursement_id)
    return ok(ser_disbursement(d), 200)


@app.route("/collections/disbursements", methods=["GET"])
def list_disbursements():
    require_role(ALL_ROLES)
    items = list(db.disbursements.values())
    victim_id = request.args.get("victim_id")
    case_id = request.args.get("case_id")
    if victim_id is not None:
        items = [d for d in items if d["victim_id"] == victim_id]
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    page, pg = paginate(items)
    return ok([ser_disbursement(d) for d in page], 200, pagination=pg, is_array=True)


@app.route("/collections/disbursements/<disbursement_id>/void", methods=["POST"])
def void_disbursement(disbursement_id):
    require_role({"FinanceOfficer"})
    d = resolve(db.disbursements, disbursement_id)
    if d["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "disbursement not PENDING")
    d["status"] = "VOIDED"
    touch(d)
    return ok(ser_disbursement(d), 200)


# ===========================================================================
# WAGE ASSIGNMENT
# ===========================================================================
def intervals_overlap_closed(s1, e1, s2, e2):
    return s1 <= e2 and s2 <= e1


@app.route("/collections/wage-assignments", methods=["POST"])
def create_wage():
    require_role({"FinanceOfficer"})
    body = get_body()
    if body.get("case_id") is not None:
        resolve(db.cases, body["case_id"])
    require_present(body, "case_id")
    case = resolve(db.cases, body["case_id"])
    employer = require_str(body, "employer_name")
    withhold = require_pos_int(body, "monthly_withhold_cents")
    start_raw = require_present(body, "effective_start_date")
    end_raw = require_present(body, "effective_end_date")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    # date range (tier 8)
    if end_dt < start_dt:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "effective_end_date before start")
    # capacity (tier 10): overlapping ACTIVE assignments of same case
    total = withhold
    for w in db.wage_assignments.values():
        if w["case_id"] == case["id"] and w["status"] == "ACTIVE":
            if intervals_overlap_closed(start_dt, end_dt, w["effective_start_date"], w["effective_end_date"]):
                total += w["monthly_withhold_cents"]
    if total > MAX_MONTHLY_WITHHOLD_CENTS:
        raise ApiError("ERR_WITHHOLD_CAPACITY_EXCEEDED", 409, "withhold capacity exceeded")
    rec = base_record()
    rec.update(
        {
            "case_id": case["id"],
            "employer_name": employer,
            "monthly_withhold_cents": withhold,
            "effective_start_date": start_dt,
            "effective_end_date": end_dt,
            "effective_start_date_raw": start_raw,
            "effective_end_date_raw": end_raw,
            "status": "ACTIVE",
        }
    )
    db.wage_assignments[rec["id"]] = rec
    return ok(ser_wage(rec), 201)


@app.route("/collections/wage-assignments/<wage_id>", methods=["GET"])
def get_wage(wage_id):
    require_role(ALL_ROLES)
    w = resolve(db.wage_assignments, wage_id)
    return ok(ser_wage(w), 200)


@app.route("/collections/wage-assignments", methods=["GET"])
def list_wage():
    require_role(ALL_ROLES)
    items = list(db.wage_assignments.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [w for w in items if w["case_id"] == case_id]
    page, pg = paginate(items)
    return ok([ser_wage(w) for w in page], 200, pagination=pg, is_array=True)


@app.route("/collections/wage-assignments/<wage_id>/terminate", methods=["POST"])
def terminate_wage(wage_id):
    require_role({"FinanceOfficer"})
    w = resolve(db.wage_assignments, wage_id)
    if w["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "wage assignment not ACTIVE")
    w["status"] = "TERMINATED"
    touch(w)
    return ok(ser_wage(w), 200)


# ===========================================================================
# ENFORCEMENT ACTION
# ===========================================================================
@app.route("/collections/enforcement-actions/<action_id>", methods=["GET"])
def get_enforcement(action_id):
    require_role(ALL_ROLES)
    e = resolve(db.enforcement_actions, action_id)
    return ok(ser_enforcement(e), 200)


@app.route("/collections/enforcement-actions", methods=["GET"])
def list_enforcement():
    require_role(ALL_ROLES)
    items = list(db.enforcement_actions.values())
    case_id = request.args.get("case_id")
    type_f = request.args.get("type")
    if case_id is not None:
        items = [e for e in items if e["case_id"] == case_id]
    if type_f is not None:
        items = [e for e in items if e["type"] == type_f]
    page, pg = paginate(items)
    return ok([ser_enforcement(e) for e in page], 200, pagination=pg, is_array=True)


@app.route("/collections/enforcement-actions/<action_id>/lift", methods=["POST"])
def lift_enforcement(action_id):
    require_role({"CollectionsSupervisor"})
    e = resolve(db.enforcement_actions, action_id)
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "enforcement action not ACTIVE")
    case = db.cases[e["case_id"]]
    if case["delinquency_status"] != "CURRENT":
        raise ApiError("ERR_CASE_STILL_DELINQUENT", 409, "case still delinquent")
    e["status"] = "LIFTED"
    touch(e)
    return ok(ser_enforcement(e), 200)


# ===========================================================================
# WAIVER REQUEST
# ===========================================================================
@app.route("/collections/waiver-requests", methods=["POST"])
def create_waiver():
    require_role({"CollectionsClerk", "CollectionsSupervisor"})
    body = get_body()
    # existence: case_id then obligation_id
    if body.get("case_id") is not None:
        resolve(db.cases, body["case_id"])
    if body.get("obligation_id") is not None:
        resolve(db.obligations, body["obligation_id"])
    require_present(body, "case_id")
    case = resolve(db.cases, body["case_id"])
    require_present(body, "obligation_id")
    ob = resolve(db.obligations, body["obligation_id"])
    amount = require_pos_int(body, "requested_amount_cents")
    # referential (tier 7): obligation must belong to case
    if ob["case_id"] != case["id"]:
        raise ApiError("ERR_OBLIGATION_CASE_MISMATCH", 422, "obligation does not belong to case")
    rec = base_record()
    rec.update(
        {
            "case_id": case["id"],
            "obligation_id": ob["id"],
            "requested_amount_cents": amount,
            "requested_by_user_id": user_id(),
            "approved_by_user_id": None,
            "status": "REQUESTED",
        }
    )
    db.waiver_requests[rec["id"]] = rec
    return ok(ser_waiver(rec), 201)


@app.route("/collections/waiver-requests/<waiver_id>", methods=["GET"])
def get_waiver(waiver_id):
    require_role(ALL_ROLES)
    w = resolve(db.waiver_requests, waiver_id)
    return ok(ser_waiver(w), 200)


@app.route("/collections/waiver-requests", methods=["GET"])
def list_waivers():
    require_role(ALL_ROLES)
    items = list(db.waiver_requests.values())
    case_id = request.args.get("case_id")
    obligation_id = request.args.get("obligation_id")
    if case_id is not None:
        items = [w for w in items if w["case_id"] == case_id]
    if obligation_id is not None:
        items = [w for w in items if w["obligation_id"] == obligation_id]
    page, pg = paginate(items)
    return ok([ser_waiver(w) for w in page], 200, pagination=pg, is_array=True)


def active_amnesty_for(clock_dt):
    for a in db.amnesty_programs.values():
        if a["start_date"] <= clock_dt < a["end_date"]:
            return a
    return None


@app.route("/collections/waiver-requests/<waiver_id>/approve", methods=["POST"])
def approve_waiver(waiver_id):
    approver = require_role({"CollectionsSupervisor"})
    w = resolve(db.waiver_requests, waiver_id)
    # state (tier 6)
    if w["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "waiver not REQUESTED")
    # SOD (tier 9)
    if user_id() is not None and user_id() == w["requested_by_user_id"]:
        raise ApiError("ERR_SOD_CONFLICT", 409, "approver equals requester")
    # temporal (amnesty coverage)
    program = active_amnesty_for(now())
    if program is None:
        raise ApiError("ERR_NO_ACTIVE_AMNESTY", 409, "no active amnesty window")
    ob = db.obligations[w["obligation_id"]]
    # balance ceiling (tier 11)
    if w["requested_amount_cents"] > ob_balance(ob):
        raise ApiError("ERR_WAIVER_EXCEEDS_BALANCE", 409, "waiver exceeds obligation balance")
    # amnesty cap (tier 10)
    cap = int(
        (Decimal(ob["assessed_amount_cents"]) * Decimal(str(program["waiver_pct"]))).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    if w["requested_amount_cents"] > cap:
        raise ApiError("ERR_WAIVER_EXCEEDS_AMNESTY_CAP", 409, "waiver exceeds amnesty cap")

    w["status"] = "APPROVED"
    w["approved_by_user_id"] = approver_id_from_request()
    touch(w)
    ob["waived_amount_cents"] += w["requested_amount_cents"]
    if ob["paid_amount_cents"] + ob["waived_amount_cents"] >= ob["assessed_amount_cents"]:
        ob["status"] = "WAIVED"
    else:
        refresh_obligation_status(ob)
    touch(ob)
    case = db.cases[ob["case_id"]]
    reconcile_case(case)
    touch(case)
    return ok(ser_waiver(w), 200)


def approver_id_from_request():
    return user_id()


@app.route("/collections/waiver-requests/<waiver_id>/deny", methods=["POST"])
def deny_waiver(waiver_id):
    require_role({"CollectionsSupervisor"})
    w = resolve(db.waiver_requests, waiver_id)
    if w["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "waiver not REQUESTED")
    if user_id() is not None and user_id() == w["requested_by_user_id"]:
        raise ApiError("ERR_SOD_CONFLICT", 409, "denier equals requester")
    w["status"] = "DENIED"
    touch(w)
    return ok(ser_waiver(w), 200)


# ===========================================================================
# AMNESTY PROGRAM
# ===========================================================================
@app.route("/collections/amnesty-programs", methods=["POST"])
def create_amnesty():
    require_role({"SystemAdmin"})
    body = get_body()
    name = require_str(body, "name")
    start_raw = require_present(body, "start_date")
    end_raw = require_present(body, "end_date")
    pct = require_present(body, "waiver_pct")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "waiver_pct must be a number")
    if not (0 < pct <= 1):
        raise ApiError("ERR_INVALID_REQUEST", 400, "waiver_pct must be in (0, 1]")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    # date range (tier 8): end strictly after start
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be after start_date")
    # overlap (tier 10): half-open intervals
    for a in db.amnesty_programs.values():
        if start_dt < a["end_date"] and a["start_date"] < end_dt:
            raise ApiError("ERR_AMNESTY_WINDOW_OVERLAP", 409, "amnesty window overlaps")
    rec = base_record()
    rec.update(
        {
            "name": name,
            "start_date": start_dt,
            "end_date": end_dt,
            "start_date_raw": start_raw,
            "end_date_raw": end_raw,
            "waiver_pct": pct,
        }
    )
    db.amnesty_programs[rec["id"]] = rec
    return ok(ser_amnesty(rec), 201)


@app.route("/collections/amnesty-programs/<program_id>", methods=["GET"])
def get_amnesty(program_id):
    require_role(ALL_ROLES)
    a = resolve(db.amnesty_programs, program_id)
    return ok(ser_amnesty(a), 200)


# ===========================================================================
# SYSTEM / REPORTING
# ===========================================================================
@app.route("/collections/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role({"SystemAdmin"})
    body = get_body()
    to_iso = require_present(body, "to_iso8601")
    dt = parse_dt(to_iso)
    db.clock = dt
    return ok({"current_utc": iso_millis(db.clock)}, 200)


@app.route("/collections/delinquency-sweep", methods=["POST"])
def delinquency_sweep():
    require_role({"SystemAdmin"})
    defaulted_plan_ids = []
    enforcement_action_ids = []
    plans = sorted(
        db.payment_plans.values(), key=lambda p: (p["created_at"], p["_seq"])
    )
    for p in plans:
        if p["status"] != "ACTIVE" or p["next_due_date"] is None:
            continue
        days_past_due = floor_days(now(), p["next_due_date"])
        if days_past_due >= DELINQUENCY_GRACE_DAYS:
            p["status"] = "DEFAULTED"
            p["missed_payment_count"] += 1
            touch(p)
            defaulted_plan_ids.append(p["id"])
            case = db.cases[p["case_id"]]
            case["delinquency_status"] = "DELINQUENT"
            reconcile_case(case)
            touch(case)
            # cascade: CIVIL_JUDGMENT then LICENSE_HOLD
            cj = base_record()
            cj.update(
                {
                    "case_id": case["id"],
                    "type": "CIVIL_JUDGMENT",
                    "amount_cents": case["balance_cents"],
                    "status": "ACTIVE",
                }
            )
            db.enforcement_actions[cj["id"]] = cj
            enforcement_action_ids.append(cj["id"])
            lh = base_record()
            lh.update(
                {
                    "case_id": case["id"],
                    "type": "LICENSE_HOLD",
                    "amount_cents": 0,
                    "status": "ACTIVE",
                }
            )
            db.enforcement_actions[lh["id"]] = lh
            enforcement_action_ids.append(lh["id"])
    return ok(
        {
            "defaulted_plan_ids": defaulted_plan_ids,
            "enforcement_action_ids": enforcement_action_ids,
        },
        200,
    )


@app.route("/collections/reports/aging", methods=["GET"])
def aging_report():
    require_role(ALL_ROLES)
    case_id = request.args.get("case_id")
    buckets = {
        "bucket_0_30_cents": 0,
        "bucket_31_90_cents": 0,
        "bucket_91_365_cents": 0,
        "bucket_366_plus_cents": 0,
        "writeoff_eligible_cents": 0,
    }
    for o in db.obligations.values():
        if o["status"] not in ("OUTSTANDING", "PARTIALLY_PAID"):
            continue
        if case_id is not None and o["case_id"] != case_id:
            continue
        bal = ob_balance(o)
        if bal <= 0:
            continue
        age = floor_days(now(), o["created_at"])
        if age >= WRITEOFF_AGE_DAYS:
            buckets["writeoff_eligible_cents"] += bal
        elif age >= 366:
            buckets["bucket_366_plus_cents"] += bal
        elif age >= 91:
            buckets["bucket_91_365_cents"] += bal
        elif age >= 31:
            buckets["bucket_31_90_cents"] += bal
        else:
            buckets["bucket_0_30_cents"] += bal
    return ok(buckets, 200)


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 405


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
