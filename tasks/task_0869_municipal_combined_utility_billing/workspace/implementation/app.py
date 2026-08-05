import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, make_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory data store (wiped on every process start; never seeded).
# ---------------------------------------------------------------------------
DB = {
    "rate_schedules": {},
    "accounts": {},
    "meters": {},
    "readings": {},
    "bills": {},
    "payments": {},
    "budget_plans": {},
    "deposits": {},
    "arrangements": {},
    "adjustments": {},
    "shutoff_orders": {},
    "lien_transfers": {},
    "moratorium_windows": {},
}

_SEQ = {"n": 0}
CLOCK = {"value": "2026-05-01T00:00:00Z"}

ROLES = {
    "BillingSpecialist",
    "MeterTech",
    "CollectionsOfficer",
    "AssistanceCaseworker",
    "Supervisor",
    "Customer",
}

# Constants
NET_DUE_DAYS = 20
DELINQUENCY_GRACE_DAYS = 21
LIEN_MIN_ARREARS_CENTS = 10000
DEFAULT_SEWER_RATE = 250
DEFAULT_WATER_TIER1_RATE = 315


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
# Helpers
# ---------------------------------------------------------------------------
def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def rand_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_ms_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_str():
    return CLOCK["value"]


def parse_dt(s):
    if s is None:
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def add_days_render(s, days):
    dt = parse_dt(s) + timedelta(days=days)
    if "." in s:
        base = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    else:
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return base + "Z"


def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_entity(fields, common=True):
    ent = dict(fields)
    ent["id"] = str(uuid.uuid4())
    ent["created_at"] = clock_str()
    ent["_seq"] = next_seq()
    if common:
        ent["updated_at"] = clock_str()
        ent["version"] = 1
    return ent


def touch(ent):
    ent["updated_at"] = clock_str()
    if "version" in ent:
        ent["version"] += 1


def serialize(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def envelope(data, response_type, status, extra_meta=None):
    meta = {"api_request_id": rand_req_id(), "api_request_timestamp": now_ms_iso()}
    if extra_meta:
        meta.update(extra_meta)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = make_response(jsonify(body), status)
    resp.headers["Connection"] = "close"
    return resp


def ok_object(ent, status=200):
    return envelope(serialize(ent), "object", status)


def ok_array(items, extra_meta):
    return envelope([serialize(e) for e in items], "array", 200, extra_meta)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return envelope(
        {"error_id": err.error_id, "message": err.message}, "error", err.http_status
    )


@app.errorhandler(404)
def handle_404(err):
    return envelope(
        {"error_id": "ERR_RESOURCE_NOT_FOUND", "message": "not found"}, "error", 404
    )


@app.errorhandler(405)
def handle_405(err):
    return envelope(
        {"error_id": "ERR_VALIDATION", "message": "method not allowed"}, "error", 405
    )


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or malformed auth headers")
    return uid, role


def require(*roles):
    uid, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")
    return uid, role


def customer_owns(uid, role, account_id):
    if role == "Customer" and account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer may only access own account")


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "body must be a JSON object")
    return body


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_VALIDATION", 422, f"missing required field: {n}")


def check_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"invalid {field}: {value}")


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_account(aid):
    a = DB["accounts"].get(aid)
    if a is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    return a


def get_meter(mid):
    m = DB["meters"].get(mid)
    if m is None:
        raise ApiError("ERR_METER_NOT_FOUND", 404, "meter not found")
    return m


def get_bill(bid):
    b = DB["bills"].get(bid)
    if b is None:
        raise ApiError("ERR_BILL_NOT_FOUND", 404, "bill not found")
    return b


def get_resource(coll, rid):
    r = DB[coll].get(rid)
    if r is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "resource not found")
    return r


def account_active_or_raise(acct):
    if acct["status"] in ("FINALED", "LIEN_TRANSFERRED"):
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "account is not mutable")


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------
def select_schedule(service_type, period_start):
    ps = parse_dt(period_start)
    cands = [
        s
        for s in DB["rate_schedules"].values()
        if s["service_type"] == service_type
        and s.get("active", True)
        and parse_dt(s["effective_date"]) <= ps
    ]
    if not cands:
        return None
    cands.sort(key=lambda s: (parse_dt(s["effective_date"]), s["_seq"]))
    return cands[-1]


def meter_consumption(meter):
    rs = [r for r in DB["readings"].values() if r["meter_id"] == meter["id"]]
    rs.sort(key=lambda r: (parse_dt(r["read_date"]), r["_seq"]))
    if not rs:
        return meter.get("estimated_monthly_units", 0) or 0, "ESTIMATED"
    latest = rs[-1]
    if latest["read_type"] == "ESTIMATED":
        return meter.get("estimated_monthly_units", 0) or 0, "ESTIMATED"
    prev = rs[-2]["reading_value"] if len(rs) >= 2 else 0
    return latest["reading_value"] - prev, "ACTUAL"


def tier_vol_raw(consumption, tiers):
    """Marginal block volumetric charge (in cents, Decimal, unrounded)."""
    vol = Decimal(0)
    lower = 0
    c = consumption
    for t in tiers:
        upper = t.get("upper_bound_units")
        if upper is None:
            block = max(0, c - lower)
        else:
            block = max(0, min(c, upper) - lower)
        vol += (Decimal(block) / Decimal(1000)) * Decimal(t["rate_cents_per_1000"])
        if upper is None:
            break
        lower = upper
        if c <= upper:
            break
    return vol


def compute_bill_charges(acct, period_start):
    meters = [
        m
        for m in DB["meters"].values()
        if m["account_id"] == acct["id"] and m["status"] == "ACTIVE"
    ]
    meters.sort(key=lambda m: m["_seq"])

    per_meter = {}
    water_cons = 0
    any_est = False
    for m in meters:
        if m["service_type"] in ("WATER", "ELECTRIC"):
            cons, basis = meter_consumption(m)
            per_meter[m["id"]] = cons
            if basis == "ESTIMATED":
                any_est = True
            if m["service_type"] == "WATER":
                water_cons += cons

    lines = []
    for m in meters:
        st = m["service_type"]
        sched = select_schedule(st, period_start)
        if st in ("WATER", "ELECTRIC"):
            cons = per_meter[m["id"]]
            if sched is None:
                charge = 0
            else:
                vol = tier_vol_raw(cons, sched.get("tiers") or [])
                charge = rhu(Decimal(sched["fixed_charge_cents"]) + vol)
            lines.append(
                {"service_type": st, "consumption_units": cons, "charge_cents": charge}
            )
        elif st == "SEWER":
            if sched is None:
                lines.append(
                    {"service_type": "SEWER", "consumption_units": 0, "charge_cents": 0}
                )
            else:
                cap = sched.get("sewer_cap_units")
                billable = water_cons if cap is None else min(water_cons, cap)
                rate = sched.get("sewer_rate_cents_per_1000") or 0
                vol = (Decimal(billable) / Decimal(1000)) * Decimal(rate)
                charge = rhu(Decimal(sched["fixed_charge_cents"]) + vol)
                lines.append(
                    {
                        "service_type": "SEWER",
                        "consumption_units": billable,
                        "charge_cents": charge,
                    }
                )
        else:  # REFUSE
            charge = int(sched["fixed_charge_cents"]) if sched else 0
            lines.append(
                {"service_type": "REFUSE", "consumption_units": 0, "charge_cents": charge}
            )

    pre_discount = sum(l["charge_cents"] for l in lines)
    disc_pct = acct.get("assistance_discount_pct") or 0
    assistance_credit = rhu(Decimal(str(disc_pct)) * Decimal(pre_discount)) if disc_pct else 0
    actual = pre_discount - assistance_credit
    read_basis = "ESTIMATED" if any_est else "ACTUAL"
    return {
        "line_charges": lines,
        "pre_discount_total_cents": pre_discount,
        "assistance_credit_cents": assistance_credit,
        "actual_charges_cents": actual,
        "read_basis": read_basis,
        "water_consumption": water_cons,
    }


# ---------------------------------------------------------------------------
# Balance recomputation
# ---------------------------------------------------------------------------
def recompute_balances(acct):
    bills = [b for b in DB["bills"].values() if b["account_id"] == acct["id"]]
    current = sum(b["total_due_cents"] - b["amount_paid_cents"] for b in bills)
    current += acct.get("_levelization_cents", 0)
    acct["current_balance_cents"] = current
    acct["delinquent_balance_cents"] = sum(
        b["total_due_cents"] - b["amount_paid_cents"]
        for b in bills
        if b["collection_status"] == "DELINQUENT"
    )
    acct["deposit_on_hand_cents"] = sum(
        d["amount_cents"]
        for d in DB["deposits"].values()
        if d["account_id"] == acct["id"] and d["status"] == "HELD"
    )
    acct["updated_at"] = clock_str()


def recompute_bill_payment_status(bill):
    if bill["amount_paid_cents"] <= 0:
        bill["payment_status"] = "UNPAID"
    elif bill["amount_paid_cents"] >= bill["total_due_cents"]:
        bill["payment_status"] = "PAID"
    else:
        bill["payment_status"] = "PARTIAL"


def paginate(items):
    limit = 10
    offset = 0
    lr = request.args.get("limit")
    orr = request.args.get("offset")
    if lr is not None:
        try:
            limit = int(lr)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "invalid limit")
        if limit < 1:
            raise ApiError("ERR_VALIDATION", 422, "limit below 1")
        if limit > 100:
            limit = 100
    if orr is not None:
        try:
            offset = int(orr)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "invalid offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 422, "invalid offset")
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


def sorted_by_created(items):
    return sorted(items, key=lambda e: e["_seq"])


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    require_fields(body, "to_iso8601")
    CLOCK["value"] = body["to_iso8601"]
    return envelope({}, "object", 200)


# ===========================================================================
# RATE SCHEDULES
# ===========================================================================
@app.route("/rate-schedules", methods=["POST"])
def create_rate_schedule():
    require("BillingSpecialist")
    body = get_body()
    require_fields(body, "service_type", "unit", "fixed_charge_cents", "effective_date")
    check_enum(body["service_type"], {"WATER", "SEWER", "ELECTRIC", "REFUSE"}, "service_type")
    check_enum(body["unit"], {"GALLON", "KWH", "FLAT"}, "unit")
    if not isinstance(body["fixed_charge_cents"], int) or body["fixed_charge_cents"] < 0:
        raise ApiError("ERR_VALIDATION", 422, "fixed_charge_cents must be >= 0")
    sched = new_entity(
        {
            "service_type": body["service_type"],
            "unit": body["unit"],
            "fixed_charge_cents": body["fixed_charge_cents"],
            "tiers": body.get("tiers") or [],
            "sewer_rate_cents_per_1000": body.get("sewer_rate_cents_per_1000"),
            "sewer_cap_units": body.get("sewer_cap_units"),
            "effective_date": body["effective_date"],
            "active": body.get("active", True),
        }
    )
    DB["rate_schedules"][sched["id"]] = sched
    return ok_object(sched, 201)


@app.route("/rate-schedules/<rid>", methods=["GET"])
def get_rate_schedule(rid):
    require("BillingSpecialist", "CollectionsOfficer", "AssistanceCaseworker", "MeterTech", "Supervisor")
    s = DB["rate_schedules"].get(rid)
    if s is None:
        raise ApiError("ERR_RATE_SCHEDULE_NOT_FOUND", 404, "rate schedule not found")
    return ok_object(s)


# ===========================================================================
# ACCOUNTS
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    require("BillingSpecialist")
    body = get_body()
    require_fields(body, "account_holder_name", "service_address", "occupant_type")
    check_enum(body["occupant_type"], {"RESIDENTIAL", "COMMERCIAL"}, "occupant_type")
    pac = body.get("prior_annual_charges_cents", 0) or 0
    if not isinstance(pac, int) or pac < 0:
        raise ApiError("ERR_VALIDATION", 422, "prior_annual_charges_cents invalid")
    acct = new_entity(
        {
            "account_holder_name": body["account_holder_name"],
            "service_address": body["service_address"],
            "occupant_type": body["occupant_type"],
            "prior_annual_charges_cents": pac,
            "status": "ACTIVE",
            "assistance_program": None,
            "assistance_discount_pct": 0,
            "current_balance_cents": 0,
            "delinquent_balance_cents": 0,
            "deposit_on_hand_cents": 0,
            "move_out_date": None,
            "_levelization_cents": 0,
        }
    )
    DB["accounts"][acct["id"]] = acct
    return ok_object(acct, 201)


@app.route("/accounts/<aid>", methods=["GET"])
def fetch_account(aid):
    uid, role = require(
        "BillingSpecialist", "CollectionsOfficer", "AssistanceCaseworker", "MeterTech", "Supervisor", "Customer"
    )
    acct = get_account(aid)
    customer_owns(uid, role, aid)
    return ok_object(acct)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    require("BillingSpecialist", "CollectionsOfficer", "AssistanceCaseworker")
    items = list(DB["accounts"].values())
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/accounts/<aid>/assistance", methods=["POST"])
def enroll_assistance(aid):
    require("AssistanceCaseworker")
    acct = get_account(aid)
    account_active_or_raise(acct)
    body = get_body()
    require_fields(body, "program", "discount_pct")
    check_enum(body["program"], {"LIHEAP", "LIFELINE", "SENIOR"}, "program")
    dp = body["discount_pct"]
    if not isinstance(dp, (int, float)) or isinstance(dp, bool) or dp < 0:
        raise ApiError("ERR_VALIDATION", 422, "invalid discount_pct")
    acct["assistance_program"] = body["program"]
    acct["assistance_discount_pct"] = dp
    touch(acct)
    return ok_object(acct)


@app.route("/accounts/<aid>/finalize", methods=["POST"])
def finalize_account(aid):
    require("BillingSpecialist")
    acct = get_account(aid)
    if acct["status"] in ("FINALED", "LIEN_TRANSFERRED"):
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "account already closed")
    body = get_body()
    require_fields(body, "period_start", "period_end")
    period_start = body["period_start"]
    period_end = body["period_end"]

    # link 1: generate final bill
    calc = compute_bill_charges(acct, period_start)
    bill = new_entity(
        {
            "account_id": acct["id"],
            "period_start": period_start,
            "period_end": period_end,
            "due_date": add_days_render(period_end, NET_DUE_DAYS),
            "budget_billed": False,
            "read_basis": calc["read_basis"],
            "line_charges": calc["line_charges"],
            "pre_discount_total_cents": calc["pre_discount_total_cents"],
            "assistance_credit_cents": calc["assistance_credit_cents"],
            "actual_charges_cents": calc["actual_charges_cents"],
            "total_due_cents": calc["actual_charges_cents"],
            "amount_paid_cents": 0,
            "payment_status": "UNPAID",
            "collection_status": "CURRENT",
        }
    )
    DB["bills"][bill["id"]] = bill

    # cancel ACTIVE budget plan, settle deferred into final bill
    for plan in DB["budget_plans"].values():
        if plan["account_id"] == acct["id"] and plan["status"] == "ACTIVE":
            deferred = plan["cumulative_actual_cents"] - plan["cumulative_budgeted_cents"]
            plan["deferred_balance_cents"] = deferred
            plan["status"] = "CANCELLED"
            touch(plan)
            bill["total_due_cents"] += deferred

    recompute_bill_payment_status(bill)
    recompute_balances(acct)

    # deposit settlement (oldest-first by created_at)
    final_balance = acct["current_balance_cents"]
    held = [
        d
        for d in DB["deposits"].values()
        if d["account_id"] == acct["id"] and d["status"] == "HELD"
    ]
    held.sort(key=lambda d: d["_seq"])
    for dep in held:
        applied = min(dep["amount_cents"], max(0, final_balance))
        refunded = dep["amount_cents"] - applied
        dep["applied_cents"] = applied
        dep["refunded_cents"] = refunded
        dep["status"] = "APPLIED" if applied > 0 else "REFUNDED"
        touch(dep)
        final_balance -= applied
        bill["amount_paid_cents"] += applied
        recompute_bill_payment_status(bill)
        if refunded > 0:
            refund = new_entity(
                {
                    "account_id": acct["id"],
                    "amount_cents": refunded,
                    "payment_date": clock_str(),
                    "method": "CHECK",
                    "allocation": [],
                    "status": "POSTED",
                }
            )
            DB["payments"][refund["id"]] = refund
    touch(bill)

    # meters removed, account finalized
    for m in DB["meters"].values():
        if m["account_id"] == acct["id"] and m["status"] == "ACTIVE":
            m["status"] = "REMOVED"
            touch(m)

    acct["move_out_date"] = clock_str()
    acct["status"] = "FINALED"
    recompute_balances(acct)
    touch(acct)
    return ok_object(bill, 201)


# ===========================================================================
# METERS
# ===========================================================================
@app.route("/accounts/<aid>/meters", methods=["POST"])
def add_meter(aid):
    require("BillingSpecialist")
    acct = get_account(aid)
    account_active_or_raise(acct)
    body = get_body()
    require_fields(body, "service_type")
    check_enum(body["service_type"], {"WATER", "SEWER", "ELECTRIC", "REFUSE"}, "service_type")
    emu = body.get("estimated_monthly_units", 0) or 0
    if not isinstance(emu, int) or emu < 0:
        raise ApiError("ERR_VALIDATION", 422, "estimated_monthly_units invalid")
    meter = new_entity(
        {
            "account_id": aid,
            "service_type": body["service_type"],
            "estimated_monthly_units": emu,
            "status": "ACTIVE",
        }
    )
    DB["meters"][meter["id"]] = meter
    return ok_object(meter, 201)


@app.route("/accounts/<aid>/meters", methods=["GET"])
def list_meters(aid):
    require("BillingSpecialist", "MeterTech", "CollectionsOfficer", "AssistanceCaseworker")
    get_account(aid)
    items = sorted_by_created(
        [m for m in DB["meters"].values() if m["account_id"] == aid]
    )
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/meters/<mid>", methods=["GET"])
def fetch_meter(mid):
    require("BillingSpecialist", "MeterTech")
    return ok_object(get_meter(mid))


@app.route("/meters/<mid>/readings", methods=["POST"])
def add_reading(mid):
    require("MeterTech")
    meter = get_meter(mid)
    body = get_body()
    require_fields(body, "read_date", "reading_value", "read_type")
    check_enum(body["read_type"], {"ACTUAL", "ESTIMATED"}, "read_type")
    rv = body["reading_value"]
    if not isinstance(rv, int) or isinstance(rv, bool) or rv < 0:
        raise ApiError("ERR_VALIDATION", 422, "reading_value must be >= 0")
    if body["read_type"] == "ACTUAL":
        existing = [r for r in DB["readings"].values() if r["meter_id"] == mid]
        if existing:
            existing.sort(key=lambda r: (parse_dt(r["read_date"]), r["_seq"]))
            latest = existing[-1]
            if rv < latest["reading_value"]:
                raise ApiError("ERR_READING_REGRESSION", 422, "dial regression")
    reading = new_entity(
        {
            "meter_id": mid,
            "read_date": body["read_date"],
            "reading_value": rv,
            "read_type": body["read_type"],
        },
        common=False,
    )
    DB["readings"][reading["id"]] = reading
    return ok_object(reading, 201)


@app.route("/meters/<mid>/readings", methods=["GET"])
def list_readings(mid):
    require("BillingSpecialist", "MeterTech")
    get_meter(mid)
    items = sorted_by_created(
        [r for r in DB["readings"].values() if r["meter_id"] == mid]
    )
    page, meta = paginate(items)
    return ok_array(page, meta)


# ===========================================================================
# BILLS
# ===========================================================================
def periods_overlap(s1, e1, s2, e2):
    # half-open [s,e): overlap iff s1 < e2 and s2 < e1
    return parse_dt(s1) < parse_dt(e2) and parse_dt(s2) < parse_dt(e1)


@app.route("/accounts/<aid>/bills", methods=["POST"])
def create_bill(aid):
    require("BillingSpecialist")
    acct = get_account(aid)
    account_active_or_raise(acct)
    body = get_body()
    require_fields(body, "period_start", "period_end")
    period_start = body["period_start"]
    period_end = body["period_end"]
    budget_billed = bool(body.get("budget_billed", False))

    plan = None
    if budget_billed:
        plans = [
            p
            for p in DB["budget_plans"].values()
            if p["account_id"] == aid and p["status"] == "ACTIVE"
        ]
        if not plans:
            raise ApiError("ERR_NO_ACTIVE_PLAN", 409, "no active budget-billing plan")
        plan = sorted_by_created(plans)[-1]

    for b in DB["bills"].values():
        if b["account_id"] == aid and periods_overlap(
            period_start, period_end, b["period_start"], b["period_end"]
        ):
            raise ApiError("ERR_PERIOD_OVERLAP", 409, "bill period overlaps existing bill")

    calc = compute_bill_charges(acct, period_start)
    if budget_billed:
        total_due = plan["monthly_budget_cents"]
    else:
        total_due = calc["actual_charges_cents"]

    bill = new_entity(
        {
            "account_id": aid,
            "period_start": period_start,
            "period_end": period_end,
            "due_date": add_days_render(period_end, NET_DUE_DAYS),
            "budget_billed": budget_billed,
            "read_basis": calc["read_basis"],
            "line_charges": calc["line_charges"],
            "pre_discount_total_cents": calc["pre_discount_total_cents"],
            "assistance_credit_cents": calc["assistance_credit_cents"],
            "actual_charges_cents": calc["actual_charges_cents"],
            "total_due_cents": total_due,
            "amount_paid_cents": 0,
            "payment_status": "UNPAID",
            "collection_status": "CURRENT",
        }
    )
    DB["bills"][bill["id"]] = bill

    if budget_billed:
        plan["cumulative_budgeted_cents"] += plan["monthly_budget_cents"]
        plan["cumulative_actual_cents"] += calc["actual_charges_cents"]
        touch(plan)

    recompute_balances(acct)
    return ok_object(bill, 201)


@app.route("/bills/<bid>", methods=["GET"])
def fetch_bill(bid):
    uid, role = require(
        "BillingSpecialist", "CollectionsOfficer", "AssistanceCaseworker", "Customer"
    )
    bill = get_bill(bid)
    customer_owns(uid, role, bill["account_id"])
    return ok_object(bill)


@app.route("/accounts/<aid>/bills", methods=["GET"])
def list_bills(aid):
    uid, role = require(
        "BillingSpecialist", "CollectionsOfficer", "AssistanceCaseworker", "Customer"
    )
    get_account(aid)
    customer_owns(uid, role, aid)
    items = [b for b in DB["bills"].values() if b["account_id"] == aid]
    cs = request.args.get("collection_status")
    ps = request.args.get("payment_status")
    if cs:
        items = [b for b in items if b["collection_status"] == cs]
    if ps:
        items = [b for b in items if b["payment_status"] == ps]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/bills/<bid>/mark-delinquent", methods=["POST"])
def mark_delinquent(bid):
    require("CollectionsOfficer")
    bill = get_bill(bid)
    if bill["collection_status"] != "CURRENT":
        raise ApiError("ERR_INVALID_STATE", 409, "bill not CURRENT")
    if bill["payment_status"] == "PAID":
        raise ApiError("ERR_BILL_ALREADY_PAID", 409, "bill already paid")
    now = parse_dt(clock_str())
    due = parse_dt(bill["due_date"])
    if (now - due) < timedelta(days=DELINQUENCY_GRACE_DAYS):
        raise ApiError("ERR_NOT_YET_DELINQUENT", 409, "grace not elapsed")
    bill["collection_status"] = "DELINQUENT"
    touch(bill)
    acct = DB["accounts"][bill["account_id"]]
    if acct["status"] == "ACTIVE":
        acct["status"] = "DELINQUENT"
    recompute_balances(acct)
    touch(acct)
    return ok_object(bill)


# ===========================================================================
# PAYMENTS
# ===========================================================================
def apply_recovery(acct):
    """After a payment reduces delinquent balance to 0, recover account/meters."""
    recompute_balances(acct)
    if acct["delinquent_balance_cents"] == 0 and acct["status"] in ("DELINQUENT", "SHUTOFF"):
        for so in DB["shutoff_orders"].values():
            if so["account_id"] == acct["id"] and so["status"] == "SCHEDULED":
                so["status"] = "CANCELLED"
                touch(so)
        if acct["status"] == "SHUTOFF":
            for m in DB["meters"].values():
                if m["account_id"] == acct["id"] and m["status"] == "REMOVED":
                    m["status"] = "ACTIVE"
                    touch(m)
        acct["status"] = "ACTIVE"
        touch(acct)


@app.route("/accounts/<aid>/payments", methods=["POST"])
def create_payment(aid):
    uid, role = require("BillingSpecialist", "Customer")
    acct = get_account(aid)
    customer_owns(uid, role, aid)
    account_active_or_raise(acct)
    body = get_body()
    require_fields(body, "amount_cents", "method")
    check_enum(body["method"], {"CASH", "CARD", "ACH", "CHECK"}, "method")
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError("ERR_VALIDATION", 422, "amount_cents must be > 0")

    candidates = [
        b
        for b in DB["bills"].values()
        if b["account_id"] == aid
        and b["payment_status"] in ("UNPAID", "PARTIAL")
        and b["collection_status"] != "IN_LIEN"
    ]
    candidates.sort(key=lambda b: (parse_dt(b["period_end"]), b["_seq"]))

    remaining = amount
    plan_allocs = []
    for b in candidates:
        due = b["total_due_cents"] - b["amount_paid_cents"]
        take = min(remaining, due)
        if take > 0:
            plan_allocs.append((b, take))
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422, "payment exceeds open balance")

    allocation = []
    for b, take in plan_allocs:
        b["amount_paid_cents"] += take
        recompute_bill_payment_status(b)
        if b["collection_status"] == "DELINQUENT" and (
            b["total_due_cents"] - b["amount_paid_cents"] == 0
        ):
            b["collection_status"] = "CURRENT"
        touch(b)
        allocation.append({"bill_id": b["id"], "applied_cents": take})

    payment = new_entity(
        {
            "account_id": aid,
            "amount_cents": amount,
            "payment_date": body.get("payment_date") or clock_str(),
            "method": body["method"],
            "allocation": allocation,
            "status": "POSTED",
        }
    )
    DB["payments"][payment["id"]] = payment
    apply_recovery(acct)
    return ok_object(payment, 201)


@app.route("/accounts/<aid>/payments", methods=["GET"])
def list_payments(aid):
    uid, role = require("BillingSpecialist", "CollectionsOfficer", "Customer")
    get_account(aid)
    customer_owns(uid, role, aid)
    items = sorted_by_created(
        [p for p in DB["payments"].values() if p["account_id"] == aid]
    )
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/payments/<pid>/reverse", methods=["POST"])
def reverse_payment(pid):
    require("BillingSpecialist")
    payment = DB["payments"].get(pid)
    if payment is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "payment not found")
    if payment["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", 409, "payment not POSTED")
    for alloc in payment["allocation"]:
        bill = DB["bills"].get(alloc["bill_id"])
        if bill is None:
            continue
        bill["amount_paid_cents"] -= alloc["applied_cents"]
        if bill["amount_paid_cents"] < 0:
            bill["amount_paid_cents"] = 0
        recompute_bill_payment_status(bill)
        touch(bill)
    payment["status"] = "REVERSED"
    touch(payment)
    acct = DB["accounts"][payment["account_id"]]
    recompute_balances(acct)
    touch(acct)
    return ok_object(payment)


# ===========================================================================
# BUDGET BILLING
# ===========================================================================
@app.route("/accounts/<aid>/budget-billing-plan", methods=["POST"])
def create_budget_plan(aid):
    require("BillingSpecialist")
    acct = get_account(aid)
    account_active_or_raise(acct)
    body = get_body()
    require_fields(body, "plan_year")
    py = body["plan_year"]
    if not isinstance(py, int) or isinstance(py, bool):
        raise ApiError("ERR_VALIDATION", 422, "invalid plan_year")
    monthly = rhu(Decimal(acct["prior_annual_charges_cents"]) / Decimal(12))
    plan = new_entity(
        {
            "account_id": aid,
            "plan_year": py,
            "monthly_budget_cents": monthly,
            "cumulative_budgeted_cents": 0,
            "cumulative_actual_cents": 0,
            "deferred_balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    DB["budget_plans"][plan["id"]] = plan
    return ok_object(plan, 201)


@app.route("/accounts/<aid>/budget-billing-plan", methods=["GET"])
def list_budget_plans(aid):
    uid, role = require("BillingSpecialist", "CollectionsOfficer", "Customer")
    get_account(aid)
    customer_owns(uid, role, aid)
    items = sorted_by_created(
        [p for p in DB["budget_plans"].values() if p["account_id"] == aid]
    )
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/budget-billing-plans/<pid>/true-up", methods=["POST"])
def true_up_plan(pid):
    require("BillingSpecialist")
    plan = get_resource("budget_plans", pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "plan not ACTIVE")
    deferred = plan["cumulative_actual_cents"] - plan["cumulative_budgeted_cents"]
    plan["deferred_balance_cents"] = deferred
    plan["status"] = "TRUED_UP"
    touch(plan)
    acct = DB["accounts"][plan["account_id"]]
    acct["_levelization_cents"] = acct.get("_levelization_cents", 0) + deferred
    recompute_balances(acct)
    touch(acct)
    return ok_object(plan)


# ===========================================================================
# DEPOSITS
# ===========================================================================
@app.route("/accounts/<aid>/deposits", methods=["POST"])
def create_deposit(aid):
    require("BillingSpecialist")
    acct = get_account(aid)
    account_active_or_raise(acct)
    body = get_body()
    require_fields(body, "amount_cents", "reason")
    check_enum(body["reason"], {"NEW_SERVICE", "DELINQUENCY", "COMMERCIAL"}, "reason")
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError("ERR_VALIDATION", 422, "amount_cents must be > 0")
    dep = new_entity(
        {
            "account_id": aid,
            "amount_cents": amount,
            "reason": body["reason"],
            "applied_cents": 0,
            "refunded_cents": 0,
            "status": "HELD",
        }
    )
    DB["deposits"][dep["id"]] = dep
    recompute_balances(acct)
    return ok_object(dep, 201)


@app.route("/accounts/<aid>/deposits", methods=["GET"])
def list_deposits(aid):
    require("BillingSpecialist", "CollectionsOfficer")
    get_account(aid)
    items = sorted_by_created(
        [d for d in DB["deposits"].values() if d["account_id"] == aid]
    )
    page, meta = paginate(items)
    return ok_array(page, meta)


# ===========================================================================
# PAYMENT ARRANGEMENTS
# ===========================================================================
@app.route("/accounts/<aid>/payment-arrangements", methods=["POST"])
def create_arrangement(aid):
    require("AssistanceCaseworker")
    acct = get_account(aid)
    body = get_body()
    require_fields(body, "total_arranged_cents", "installment_count", "expected_account_version")
    total = body["total_arranged_cents"]
    count = body["installment_count"]
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        raise ApiError("ERR_VALIDATION", 422, "total_arranged_cents must be > 0")
    if not isinstance(count, int) or isinstance(count, bool) or count < 2:
        raise ApiError("ERR_VALIDATION", 422, "installment_count must be >= 2")
    if body["expected_account_version"] != acct["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_account_version mismatch")

    for arr in DB["arrangements"].values():
        if arr["account_id"] == aid and arr["status"] == "ACTIVE":
            arr["status"] = "SUPERSEDED"
            touch(arr)

    installment = rhu(Decimal(total) / Decimal(count))
    arrangement = new_entity(
        {
            "account_id": aid,
            "total_arranged_cents": total,
            "installment_count": count,
            "installment_amount_cents": installment,
            "status": "ACTIVE",
        }
    )
    DB["arrangements"][arrangement["id"]] = arrangement
    touch(acct)  # increments account.version by 1
    return ok_object(arrangement, 201)


@app.route("/accounts/<aid>/payment-arrangements", methods=["GET"])
def list_arrangements(aid):
    uid, role = require("AssistanceCaseworker", "CollectionsOfficer", "Customer")
    get_account(aid)
    customer_owns(uid, role, aid)
    items = [a for a in DB["arrangements"].values() if a["account_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/payment-arrangements/<pid>/record-missed", methods=["POST"])
def record_missed(pid):
    require("CollectionsOfficer")
    arr = get_resource("arrangements", pid)
    if arr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "arrangement not ACTIVE")
    arr["status"] = "DEFAULTED"
    touch(arr)
    acct = DB["accounts"][arr["account_id"]]
    if acct["status"] == "ACTIVE":
        acct["status"] = "DELINQUENT"
    for b in DB["bills"].values():
        if (
            b["account_id"] == acct["id"]
            and b["payment_status"] in ("UNPAID", "PARTIAL")
            and b["collection_status"] == "CURRENT"
        ):
            b["collection_status"] = "DELINQUENT"
            touch(b)
    so = new_entity(
        {
            "account_id": acct["id"],
            "scheduled_date": clock_str(),
            "reason": "ARRANGEMENT_DEFAULT",
            "origin": "CASCADE",
            "status": "SCHEDULED",
        }
    )
    DB["shutoff_orders"][so["id"]] = so
    recompute_balances(acct)
    touch(acct)
    return ok_object(arr)


@app.route("/payment-arrangements/<pid>/reinstate", methods=["POST"])
def reinstate_arrangement(pid):
    require("AssistanceCaseworker")
    arr = get_resource("arrangements", pid)
    if arr["status"] != "DEFAULTED":
        raise ApiError("ERR_INVALID_STATE", 409, "arrangement not DEFAULTED")
    arr["status"] = "ACTIVE"
    touch(arr)
    acct = DB["accounts"][arr["account_id"]]
    for so in DB["shutoff_orders"].values():
        if (
            so["account_id"] == acct["id"]
            and so["status"] == "SCHEDULED"
            and so["origin"] == "CASCADE"
        ):
            so["status"] = "CANCELLED"
            touch(so)
    recompute_balances(acct)
    if arr["total_arranged_cents"] >= acct["delinquent_balance_cents"] and acct["status"] == "DELINQUENT":
        acct["status"] = "ACTIVE"
        touch(acct)
    return ok_object(arr)


# ===========================================================================
# ADJUSTMENTS
# ===========================================================================
@app.route("/bills/<bid>/adjustments", methods=["POST"])
def request_adjustment(bid):
    uid, role = require("AssistanceCaseworker")
    bill = get_bill(bid)
    body = get_body()
    require_fields(body, "adjustment_type")
    check_enum(body["adjustment_type"], {"LEAK", "ESTIMATE_CORRECTION", "GOODWILL"}, "adjustment_type")
    relief = body.get("relief_method")
    if relief is not None:
        check_enum(relief, {"SEWER_RELIEF", "TIER_REPRICE"}, "relief_method")
    adj = new_entity(
        {
            "bill_id": bid,
            "adjustment_type": body["adjustment_type"],
            "relief_method": relief,
            "baseline_units": body.get("baseline_units", 0) or 0,
            "goodwill_amount_cents": body.get("goodwill_amount_cents", 0) or 0,
            "credit_cents": 0,
            "requested_by": uid,
            "approved_by": None,
            "status": "REQUESTED",
        }
    )
    DB["adjustments"][adj["id"]] = adj
    return ok_object(adj, 201)


@app.route("/bills/<bid>/adjustments", methods=["GET"])
def list_adjustments(bid):
    require("AssistanceCaseworker", "BillingSpecialist", "Supervisor")
    get_bill(bid)
    items = sorted_by_created(
        [a for a in DB["adjustments"].values() if a["bill_id"] == bid]
    )
    page, meta = paginate(items)
    return ok_array(page, meta)


def water_consumption_of_bill(bill):
    return sum(
        l["consumption_units"]
        for l in bill["line_charges"]
        if l["service_type"] == "WATER"
    )


def compute_adjustment_credit(adj, bill, acct):
    atype = adj["adjustment_type"]
    if atype == "GOODWILL":
        return adj["goodwill_amount_cents"]
    if atype == "ESTIMATE_CORRECTION":
        recomputed = compute_bill_charges(acct, bill["period_start"])
        return max(0, bill["actual_charges_cents"] - recomputed["actual_charges_cents"])
    # LEAK
    water_cons = water_consumption_of_bill(bill)
    excess = max(0, water_cons - adj["baseline_units"])
    sched = select_schedule("WATER", bill["period_start"])
    tiers = (sched.get("tiers") if sched else None) or []
    relief = adj["relief_method"]
    if relief == "SEWER_RELIEF":
        sewer_sched = select_schedule("SEWER", bill["period_start"])
        rate = (
            sewer_sched.get("sewer_rate_cents_per_1000")
            if sewer_sched and sewer_sched.get("sewer_rate_cents_per_1000") is not None
            else DEFAULT_SEWER_RATE
        )
        return rhu(Decimal(rate) * Decimal(excess) / Decimal(1000))
    if relief == "TIER_REPRICE":
        seg = tier_vol_raw(water_cons, tiers) - tier_vol_raw(adj["baseline_units"], tiers)
        actual_on_excess = rhu(seg)
        tier1 = tiers[0]["rate_cents_per_1000"] if tiers else DEFAULT_WATER_TIER1_RATE
        repriced = rhu(Decimal(excess) / Decimal(1000) * Decimal(tier1))
        return actual_on_excess - repriced
    return 0


@app.route("/adjustments/<adjid>/approve", methods=["POST"])
def approve_adjustment(adjid):
    uid, role = require("Supervisor")
    adj = get_resource("adjustments", adjid)
    if adj["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "adjustment not REQUESTED")
    if uid == adj["requested_by"]:
        raise ApiError("ERR_SOD_VIOLATION", 403, "approver must differ from requester")
    bill = DB["bills"].get(adj["bill_id"])
    acct = DB["accounts"].get(bill["account_id"])
    credit = compute_adjustment_credit(adj, bill, acct)
    adj["credit_cents"] = credit
    adj["approved_by"] = uid
    adj["status"] = "APPROVED"
    touch(adj)
    bill["amount_paid_cents"] += credit
    recompute_bill_payment_status(bill)
    touch(bill)
    recompute_balances(acct)
    touch(acct)
    return ok_object(adj)


@app.route("/adjustments/<adjid>/reject", methods=["POST"])
def reject_adjustment(adjid):
    uid, role = require("Supervisor")
    adj = get_resource("adjustments", adjid)
    if adj["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "adjustment not REQUESTED")
    if uid == adj["requested_by"]:
        raise ApiError("ERR_SOD_VIOLATION", 403, "approver must differ from requester")
    adj["approved_by"] = uid
    adj["status"] = "REJECTED"
    touch(adj)
    return ok_object(adj)


# ===========================================================================
# SHUTOFF ORDERS
# ===========================================================================
@app.route("/accounts/<aid>/shutoff-orders", methods=["POST"])
def create_shutoff(aid):
    require("CollectionsOfficer")
    acct = get_account(aid)
    body = get_body()
    require_fields(body, "scheduled_date")
    reason = body.get("reason", "DELINQUENCY") or "DELINQUENCY"
    check_enum(reason, {"DELINQUENCY", "ARRANGEMENT_DEFAULT"}, "reason")
    if acct["status"] != "DELINQUENT" or acct["delinquent_balance_cents"] <= 0:
        raise ApiError("ERR_NO_DELINQUENT_BALANCE", 409, "no positive delinquent balance")
    so = new_entity(
        {
            "account_id": aid,
            "scheduled_date": body["scheduled_date"],
            "reason": reason,
            "origin": "MANUAL",
            "status": "SCHEDULED",
        }
    )
    DB["shutoff_orders"][so["id"]] = so
    return ok_object(so, 201)


@app.route("/accounts/<aid>/shutoff-orders", methods=["GET"])
def list_shutoffs(aid):
    require("CollectionsOfficer", "MeterTech")
    get_account(aid)
    items = [s for s in DB["shutoff_orders"].values() if s["account_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok_array(page, meta)


def moratorium_covers(acct_id, scheduled_date):
    sd = parse_dt(scheduled_date)
    for w in DB["moratorium_windows"].values():
        if w["status"] != "ACTIVE":
            continue
        if w["scope"] == "SYSTEM" or (w["scope"] == "ACCOUNT" and w["account_id"] == acct_id):
            if parse_dt(w["start_date"]) <= sd <= parse_dt(w["end_date"]):
                return True
    return False


@app.route("/shutoff-orders/<sid>/execute", methods=["POST"])
def execute_shutoff(sid):
    require("MeterTech")
    so = get_resource("shutoff_orders", sid)
    if so["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "shutoff order not SCHEDULED")
    acct = DB["accounts"][so["account_id"]]
    if moratorium_covers(acct["id"], so["scheduled_date"]):
        raise ApiError("ERR_MORATORIUM_ACTIVE", 403, "moratorium blocks execution")
    if acct["status"] != "DELINQUENT" or acct["delinquent_balance_cents"] <= 0:
        raise ApiError("ERR_NO_DELINQUENT_BALANCE", 409, "account cured")
    so["status"] = "EXECUTED"
    touch(so)
    acct["status"] = "SHUTOFF"
    for m in DB["meters"].values():
        if (
            m["account_id"] == acct["id"]
            and m["service_type"] in ("WATER", "ELECTRIC")
            and m["status"] == "ACTIVE"
        ):
            m["status"] = "REMOVED"
            touch(m)
    touch(acct)
    return ok_object(so)


# ===========================================================================
# LIEN TRANSFERS
# ===========================================================================
@app.route("/accounts/<aid>/lien-transfers", methods=["POST"])
def create_lien(aid):
    require("CollectionsOfficer")
    acct = get_account(aid)
    body = get_body()
    require_fields(body, "tax_parcel_ref")
    if acct["delinquent_balance_cents"] < LIEN_MIN_ARREARS_CENTS:
        raise ApiError("ERR_INSUFFICIENT_ARREARS", 409, "arrears below minimum")
    lien = new_entity(
        {
            "account_id": aid,
            "amount_cents": acct["delinquent_balance_cents"],
            "tax_parcel_ref": body["tax_parcel_ref"],
            "status": "PENDING",
        }
    )
    DB["lien_transfers"][lien["id"]] = lien
    return ok_object(lien, 201)


@app.route("/accounts/<aid>/lien-transfers", methods=["GET"])
def list_liens(aid):
    require("CollectionsOfficer", "BillingSpecialist")
    get_account(aid)
    items = [l for l in DB["lien_transfers"].values() if l["account_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [l for l in items if l["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/lien-transfers/<lid>/certify", methods=["POST"])
def certify_lien(lid):
    require("CollectionsOfficer")
    lien = get_resource("lien_transfers", lid)
    if lien["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "lien not PENDING")
    acct = DB["accounts"][lien["account_id"]]
    if acct["status"] not in ("DELINQUENT", "SHUTOFF"):
        raise ApiError("ERR_INVALID_STATE", 409, "account not DELINQUENT/SHUTOFF")
    if acct["delinquent_balance_cents"] < LIEN_MIN_ARREARS_CENTS:
        raise ApiError("ERR_INSUFFICIENT_ARREARS", 409, "arrears below minimum")
    lien["amount_cents"] = acct["delinquent_balance_cents"]
    lien["status"] = "TRANSFERRED"
    touch(lien)
    for b in DB["bills"].values():
        if b["account_id"] == acct["id"] and b["collection_status"] == "DELINQUENT":
            b["collection_status"] = "IN_LIEN"
            touch(b)
    acct["status"] = "LIEN_TRANSFERRED"
    recompute_balances(acct)
    touch(acct)
    return ok_object(lien)


# ===========================================================================
# MORATORIUM WINDOWS
# ===========================================================================
@app.route("/moratorium-windows", methods=["POST"])
def create_moratorium():
    require("CollectionsOfficer")
    body = get_body()
    require_fields(body, "scope", "start_date", "end_date", "reason")
    check_enum(body["scope"], {"SYSTEM", "ACCOUNT"}, "scope")
    check_enum(body["reason"], {"WEATHER", "MEDICAL", "LEGISLATIVE"}, "reason")
    account_id = body.get("account_id")
    if body["scope"] == "ACCOUNT":
        if not account_id:
            raise ApiError("ERR_VALIDATION", 422, "account_id required for ACCOUNT scope")
        get_account(account_id)
    else:
        account_id = None

    if body["scope"] == "SYSTEM":
        ns = parse_dt(body["start_date"])
        ne = parse_dt(body["end_date"])
        for w in DB["moratorium_windows"].values():
            if w["scope"] == "SYSTEM" and w["status"] == "ACTIVE":
                es = parse_dt(w["start_date"])
                ee = parse_dt(w["end_date"])
                # closed intervals conflict if they overlap OR touch
                if ns <= ee and es <= ne:
                    raise ApiError("ERR_MORATORIUM_OVERLAP", 409, "system moratorium overlap")

    win = new_entity(
        {
            "account_id": account_id,
            "scope": body["scope"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "reason": body["reason"],
            "status": "ACTIVE",
        }
    )
    DB["moratorium_windows"][win["id"]] = win
    return ok_object(win, 201)


@app.route("/accounts/<aid>/moratorium-windows", methods=["GET"])
def list_moratoria(aid):
    require("CollectionsOfficer", "MeterTech")
    get_account(aid)
    items = [w for w in DB["moratorium_windows"].values() if w["account_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [w for w in items if w["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/moratorium-windows/<wid>", methods=["GET"])
def fetch_moratorium(wid):
    require("CollectionsOfficer", "MeterTech")
    w = DB["moratorium_windows"].get(wid)
    if w is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "moratorium window not found")
    return ok_object(w)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
