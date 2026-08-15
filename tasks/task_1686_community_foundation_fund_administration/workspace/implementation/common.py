"""Shared foundation: in-memory store, logical clock, envelope, errors, auth, helpers."""
import itertools
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from functools import wraps

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; no seeding)
# ---------------------------------------------------------------------------
STORE = {
    "funds": {},
    "agreements": {},
    "advisors": {},
    "contributions": {},
    "lots": {},
    "pools": {},
    "holdings": {},
    "events": {},
    "grantees": {},
    "grants": {},
    "disbursements": {},
    "runs": {},
    "snapshots": {},
    "fees": {},
    "programs": {},
    "members": {},
    "applications": {},
    "scores": {},
    "awards": {},
    "statements": {},
}

# Logical clock: starts exactly at 2026-08-01T00:00:00Z, never wall-clock.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Global insertion sequence (tie-break for identical logical timestamps).
SEQ = itertools.count(1)

CENT = Decimal("0.01")
U4 = Decimal("0.0001")

ROLES = {
    "FoundationAdmin", "GiftOfficer", "ComplianceOfficer", "FinanceOfficer",
    "ProgramOfficer", "InvestmentManager", "Advisor", "Applicant",
    "CommitteeMember",
}
ALL_ROLES = tuple(sorted(ROLES))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Time helpers (all timestamps read from the logical clock)
# ---------------------------------------------------------------------------
def now():
    return CLOCK["now"]


def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="timestamp"):
    """Parse ISO-8601 into an aware UTC datetime; ERR_FIELD_CONSTRAINT on failure."""
    if not isinstance(value, str) or not value.strip():
        err("ERR_FIELD_CONSTRAINT", 422, f"{field} must be an ISO 8601 timestamp")
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        # Fallback for unusual but valid shapes
        try:
            from dateutil import parser as _dup  # type: ignore
            dt = _dup.parse(value)
        except Exception:
            err("ERR_FIELD_CONSTRAINT", 422, f"{field} must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    if m == 2:
        leap = (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0))
        dmax = 29 if leap else 28
    elif m in (4, 6, 9, 11):
        dmax = 30
    else:
        dmax = 31
    return dt.replace(year=y, month=m, day=min(dt.day, dmax))


def months_between(la, cur):
    """Whole calendar months between two instants (PRD inactivity formula)."""
    m = (cur.year - la.year) * 12 + (cur.month - la.month)
    if cur.day < la.day:
        m -= 1
    return m


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def D(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool) or x is None:
        raise InvalidOperation
    if isinstance(x, (int, float)):
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x.strip())
    raise InvalidOperation


def q2(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def q4(x):
    return x.quantize(U4, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_ts(now()),
    }


def success(data, rtype="object", code=200, pagination=None):
    body = {"meta": _meta(), "response_type": rtype, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def error_body(e):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }


# ---------------------------------------------------------------------------
# Auth (priority 1: headers; priority 2: role permission)
# ---------------------------------------------------------------------------
def get_ctx():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT", 400,
            "X-User-ID and X-User-Role headers are required and role must be a declared role")
    return uid, role


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = get_ctx()
            if role not in roles:
                err("ERR_FORBIDDEN", 403, "Role is not permitted for this endpoint")
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Request body / field extraction
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def req_present(data, name):
    v = data.get(name)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        err("ERR_FIELD_CONSTRAINT", 422, f"{name} is required")
    return v


def req_decimal(data, name):
    v = data.get(name)
    if v is None:
        err("ERR_FIELD_CONSTRAINT", 422, f"{name} is required")
    try:
        return D(v)
    except (InvalidOperation, ValueError, AttributeError):
        err("ERR_FIELD_CONSTRAINT", 422, f"{name} must be a number")


def opt_decimal(data, name, default):
    v = data.get(name)
    if v is None:
        return default
    try:
        return D(v)
    except (InvalidOperation, ValueError, AttributeError):
        err("ERR_FIELD_CONSTRAINT", 422, f"{name} must be a number")


def req_int(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_FIELD_CONSTRAINT", 422, f"{name} must be an integer")
    return v


def opt_int(data, name, default):
    v = data.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_FIELD_CONSTRAINT", 422, f"{name} must be an integer")
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if v not in allowed:
        err("ERR_FIELD_CONSTRAINT", 422, f"{name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Resource scaffolding
# ---------------------------------------------------------------------------
def new_resource(common_fields=True):
    r = {
        "id": str(uuid.uuid4()),
        "created_at": now(),
        "_seq": next(SEQ),
    }
    if common_fields:
        r["updated_at"] = r["created_at"]
        r["version"] = 1
    return r


def touch(r):
    """Refresh updated_at and bump version (primary resources only)."""
    r["updated_at"] = now()
    r["version"] = r.get("version", 0) + 1


def serialize(r):
    out = {}
    for k, v in r.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, datetime):
            out[k] = fmt_ts(v)
        elif isinstance(v, list):
            out[k] = [
                float(x) if isinstance(x, Decimal)
                else fmt_ts(x) if isinstance(x, datetime) else x
                for x in v
            ]
        else:
            out[k] = v
    return out


def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def list_response(items, view_fn):
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    page, pag = paginate(ordered)
    return success([view_fn(r) for r in page], rtype="array", pagination=pag)


# ---------------------------------------------------------------------------
# Lookup helpers (path existence -> ERR_NOT_FOUND, body refs -> ERR_REFERENCE_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_path(collection, rid):
    r = STORE[collection].get(rid)
    if r is None:
        err("ERR_NOT_FOUND", 404, f"Resource {rid} does not exist")
    return r


def get_ref(collection, rid, what="reference"):
    r = STORE[collection].get(rid)
    if r is None:
        err("ERR_REFERENCE_NOT_FOUND", 404, f"Referenced {what} {rid} does not exist")
    return r


# ---------------------------------------------------------------------------
# Domain shared helpers
# ---------------------------------------------------------------------------
def executed_agreement(fund_id):
    for a in STORE["agreements"].values():
        if a["fund_id"] == fund_id and a["status"] == "EXECUTED":
            return a
    return None


def pool_unit_price(pool):
    if pool["units_outstanding"] <= 0:
        return None
    return q4(pool["nav"] / pool["units_outstanding"])


def fund_holdings(fund_id):
    return [h for h in STORE["holdings"].values() if h["fund_id"] == fund_id]


def fund_invested_units(fund_id):
    total = Decimal("0")
    for h in fund_holdings(fund_id):
        total += h["units_held"]
    return q4(total)


def fund_invested_mv(fund_id):
    total = Decimal("0")
    for h in fund_holdings(fund_id):
        price = pool_unit_price(STORE["pools"][h["pool_id"]])
        if price is not None:
            total += h["units_held"] * price
    return q2(total)


def fund_view(f):
    inv_units = fund_invested_units(f["id"])
    imv = fund_invested_mv(f["id"])
    total_mv = q2(f["cash_balance"] + imv)
    if f["endowed"]:
        remaining = f["current_spending_allowance"] - f["allowance_used"]
        if remaining < 0:
            remaining = Decimal("0")
        spendable = q2(min(f["cash_balance"], remaining))
    else:
        spendable = q2(f["cash_balance"])
    la = f["last_activity_at"]
    inactivity = months_between(la, now()) if la is not None else None
    return {
        "id": f["id"],
        "fund_name": f["fund_name"],
        "fund_type": f["fund_type"],
        "status": f["status"],
        "endowed": f["endowed"],
        "cash_balance": float(q2(f["cash_balance"])),
        "invested_units": float(inv_units),
        "invested_market_value": float(imv),
        "total_market_value": float(total_mv),
        "spendable_balance": float(spendable),
        "current_spending_allowance": float(q2(f["current_spending_allowance"])),
        "allowance_used": float(q2(f["allowance_used"])),
        "inception_date": fmt_ts(f["inception_date"]),
        "last_activity_at": fmt_ts(la),
        "inactivity_months": inactivity,
        "created_at": fmt_ts(f["created_at"]),
        "updated_at": fmt_ts(f["updated_at"]),
        "version": f["version"],
    }


def reactivate_if_inactive(fund):
    """INACTIVE -> ACTIVE on qualifying activity; caller refreshes last_activity_at."""
    if fund["status"] == "INACTIVE":
        fund["status"] = "ACTIVE"


def evaluate_time_transitions():
    """Auto-transitions fired by a logical-clock advance (PRD §2.5)."""
    cur = now()
    # Funds: DONOR_ADVISED only; one transition per fund per advance.
    for f in list(STORE["funds"].values()):
        if f["fund_type"] != "DONOR_ADVISED":
            continue
        agr = executed_agreement(f["id"])
        if agr is None:
            continue
        la = f["last_activity_at"]
        if la is None:
            continue
        m = months_between(la, cur)
        if f["status"] == "ACTIVE" and m >= agr["inactivity_trigger_months"]:
            f["status"] = "INACTIVE"
            touch(f)
        elif f["status"] == "INACTIVE" and m >= (
            agr["inactivity_trigger_months"] + agr["dormancy_trigger_months"]
        ):
            f["status"] = "DORMANT"
            has_successor = any(
                a for a in STORE["advisors"].values()
                if a["fund_id"] == f["id"]
                and a["advisor_kind"] == "SUCCESSOR"
                and a["status"] in ("ACTIVE", "INVITED")
            )
            if not has_successor:
                # Dormancy sweep: cash-ledger movement only, no disbursement record.
                f["cash_balance"] = Decimal("0.00")
            for gr in STORE["grants"].values():
                if gr["fund_id"] == f["id"] and gr["status"] in (
                    "DRAFT", "SUBMITTED", "RETURNED",
                ):
                    gr["status"] = "DENIED"
                    gr["decided_at"] = cur
                    touch(gr)
            touch(f)
    # Grantees: CLEARED -> EXPIRED at cleared_at + 12 months.
    for gr in list(STORE["grantees"].values()):
        if gr["due_diligence_status"] == "CLEARED" and gr["cleared_at"] is not None:
            if cur >= add_months(gr["cleared_at"], 12):
                gr["due_diligence_status"] = "EXPIRED"
                touch(gr)
