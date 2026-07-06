"""Charitable Gaming License API — Flask reference implementation.

In-memory only. The store starts empty on every boot; no entities are seeded.
All business time is driven by a logical clock (default 2026-05-01T00:00:00Z).
"""

import os
import re
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
ROLES = ("Regulator", "OrgOfficer", "Supplier")

NONPROFIT_TYPES = ("501C3", "501C4", "501C8", "501C10", "501C19", "OTHER")
QUALIFYING_NONPROFIT_TYPES = ("501C3", "501C4", "501C8", "501C10", "501C19")
ELIGIBILITY_MIN_MONTHS = 36

LICENSE_TYPES = ("BINGO", "RAFFLE", "COMBINED")
ANNUAL_PRIZE_LIMIT_CENTS = {"BINGO": 1000000, "RAFFLE": 2000000, "COMBINED": 3000000}

OCCASION_TYPES = ("BINGO", "RAFFLE")
PER_OCCASION_PRIZE_CAP_CENTS = {"BINGO": 800000, "RAFFLE": 1500000}

EQUIPMENT_TYPES = ("BINGO_BLOWER", "FLASHBOARD", "RAFFLE_DRUM", "CARD_MINDER")

VIOLATION_TYPES = ("LATE_REPORT", "PRIZE_LIMIT_EXCEEDED", "UNREGISTERED_EQUIPMENT", "PROCEEDS_MISUSE")
POINTS_BY_TYPE = {"LATE_REPORT": 3, "PRIZE_LIMIT_EXCEEDED": 6, "UNREGISTERED_EQUIPMENT": 5, "PROCEEDS_MISUSE": 10}
SUSPENSION_POINT_THRESHOLD = 10
REPORT_GRACE_DAYS = 7

ADMIN_ALLOWANCE_PCT = "0.15"
REGULATORY_FEE_PCT = "0.05"

EQUIPMENT_BUFFER = timedelta(days=1)

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# =============================================================================
# In-memory store
# =============================================================================
DB = {
    "organizations": {},
    "licenses": {},
    "occasions": {},
    "suppliers": {},
    "equipment": {},
    "equipment_allocations": {},
    "financial_reports": {},
    "violations": {},
    "renewals": {},
}
_SEQ = 0
CLOCK = None  # datetime (naive UTC)


def reset_state():
    global _SEQ, CLOCK
    for c in DB.values():
        c.clear()
    _SEQ = 0
    CLOCK = parse_dt(DEFAULT_CLOCK)


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =============================================================================
# Time helpers
# =============================================================================
def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_wall_millis():
    dt = datetime.now(timezone.utc).replace(tzinfo=None)
    return fmt_dt(dt)


def last_day_of_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    mo = m % 12 + 1
    d = min(dt.day, last_day_of_month(y, mo))
    return dt.replace(year=y, month=mo, day=d)


# =============================================================================
# Envelope helpers
# =============================================================================
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": now_wall_millis()}


def resp_object(data, code=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), code


def resp_array(items, limit, offset, total):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + limit) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# =============================================================================
# Entity plumbing
# =============================================================================
def new_entity(collection, fields):
    global _SEQ
    _SEQ += 1
    eid = str(uuid.uuid4())
    ent = dict(fields)
    ent["id"] = eid
    ent["created_at"] = CLOCK
    ent["updated_at"] = CLOCK
    ent["version"] = 1
    ent["_seq"] = _SEQ
    DB[collection][eid] = ent
    return ent


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = CLOCK


def sorted_items(collection, predicate=None):
    items = [e for e in DB[collection].values() if (predicate is None or predicate(e))]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return items


# =============================================================================
# Auth / RBAC / lookup
# =============================================================================
def auth():
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role missing or invalid")
    uid = request.headers.get("X-User-ID")
    return role, uid


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


def lookup(collection, eid):
    ent = DB[collection].get(eid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def forbidden():
    raise ApiError("ERR_FORBIDDEN", 403, "Actor does not own this resource")


def org_of_license(lic):
    return lic["organization_id"]


def check_org_ownership(role, uid, org_id):
    if role == "OrgOfficer" and uid != org_id:
        forbidden()


def check_supplier_ownership(role, uid, supplier_id):
    if role == "Supplier" and uid != supplier_id:
        forbidden()


# =============================================================================
# Body validation helpers
# =============================================================================
def get_body():
    raw = request.get_data()
    if not raw or not raw.strip():
        return {}
    body = request.get_json(silent=True, force=True)
    if body is None:
        raise ApiError("ERR_VALIDATION", 422, "Malformed JSON body")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Body must be an object")
    return body


def _validation(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        _validation("Missing or invalid field: %s" % key)
    return v


def req_int(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        _validation("Missing or invalid integer field: %s" % key)
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        _validation("Invalid enum value for %s" % key)
    return v


def req_datetime(body, key):
    v = body.get(key)
    if not isinstance(v, str):
        _validation("Missing or invalid datetime field: %s" % key)
    try:
        return parse_dt(v), v
    except Exception:
        _validation("Unparseable datetime for %s" % key)


def get_pagination():
    def to_int(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = to_int("limit", 10)
    offset = to_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate_and_respond(items_ser):
    limit, offset = get_pagination()
    total = len(items_ser)
    page = items_ser[offset:offset + limit]
    return resp_array(page, limit, offset, total)


# =============================================================================
# Computed values & serialization
# =============================================================================
def compute_months_active(org):
    inc = parse_dt(org["incorporation_date"])
    ma = (CLOCK.year - inc.year) * 12 + (CLOCK.month - inc.month)
    if CLOCK.day < inc.day:
        ma -= 1
    return max(0, ma)


def compute_eligibility(org):
    ma = compute_months_active(org)
    ok = (
        org["nonprofit_type"] in QUALIFYING_NONPROFIT_TYPES
        and ma >= ELIGIBILITY_MIN_MONTHS
        and org["good_standing"] is True
    )
    return "ELIGIBLE" if ok else "INELIGIBLE"


def ser_org(o):
    return {
        "id": o["id"],
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
        "legal_name": o["legal_name"],
        "ein": o["ein"],
        "nonprofit_type": o["nonprofit_type"],
        "incorporation_date": o["incorporation_date"],
        "good_standing": o["good_standing"],
        "state_code": o["state_code"],
        "months_active": compute_months_active(o),
        "eligibility_status": compute_eligibility(o),
    }


def ser_license(l):
    remaining = l["annual_prize_limit_cents"] - l["prize_committed_cents"] - l["prize_settled_cents"]
    return {
        "id": l["id"],
        "created_at": fmt_dt(l["created_at"]),
        "updated_at": fmt_dt(l["updated_at"]),
        "version": l["version"],
        "organization_id": l["organization_id"],
        "license_type": l["license_type"],
        "contact_email": l["contact_email"],
        "venue_name": l["venue_name"],
        "status": l["status"],
        "effective_date": fmt_dt(l["effective_date"]),
        "expiration_date": fmt_dt(l["expiration_date"]),
        "annual_prize_limit_cents": l["annual_prize_limit_cents"],
        "prize_committed_cents": l["prize_committed_cents"],
        "prize_settled_cents": l["prize_settled_cents"],
        "prize_allowance_remaining_cents": remaining,
        "total_violation_points_active": l["total_violation_points_active"],
    }


def ser_occasion(o):
    return {
        "id": o["id"],
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
        "license_id": o["license_id"],
        "occasion_type": o["occasion_type"],
        "scheduled_start": o["scheduled_start"],
        "scheduled_end": o["scheduled_end"],
        "venue_name": o["venue_name"],
        "planned_gross_cents": o["planned_gross_cents"],
        "planned_prize_pool_cents": o["planned_prize_pool_cents"],
        "planned_expenses_cents": o["planned_expenses_cents"],
        "gross_receipts_cents": o["gross_receipts_cents"],
        "prizes_paid_cents": o["prizes_paid_cents"],
        "expenses_cents": o["expenses_cents"],
        "net_proceeds_cents": o["net_proceeds_cents"],
        "status": o["status"],
    }


def ser_supplier(s):
    return {
        "id": s["id"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
        "business_name": s["business_name"],
        "state_code": s["state_code"],
        "status": s["status"],
    }


def ser_equipment(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
        "supplier_id": e["supplier_id"],
        "equipment_type": e["equipment_type"],
        "serial_number": e["serial_number"],
        "status": e["status"],
    }


def ser_allocation(a):
    return {
        "id": a["id"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
        "equipment_id": a["equipment_id"],
        "occasion_id": a["occasion_id"],
        "start_date": a["start_date"],
        "end_date": a["end_date"],
        "status": a["status"],
    }


def round_half_up_pct(cents, pct):
    return int((Decimal(cents) * Decimal(pct)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_financial_report(fr):
    ps = parse_dt(fr["period_start"])
    pe = parse_dt(fr["period_end"])
    tg = tp = te = 0
    for occ in DB["occasions"].values():
        if occ["license_id"] != fr["license_id"] or occ["status"] != "REPORTED":
            continue
        ss = parse_dt(occ["scheduled_start"])
        if ps <= ss <= pe:
            tg += occ["gross_receipts_cents"] or 0
            tp += occ["prizes_paid_cents"] or 0
            te += occ["expenses_cents"] or 0
    net = tg - tp - te
    admin = round_half_up_pct(net, ADMIN_ALLOWANCE_PCT)
    reg = round_half_up_pct(net, REGULATORY_FEE_PCT)
    charitable_min = net - admin - reg
    if net > 0:
        ratio = float(
            (Decimal(fr["charitable_use_cents"]) / Decimal(net)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        )
    else:
        ratio = 0
    return {
        "total_gross_cents": tg,
        "total_prizes_cents": tp,
        "total_expenses_cents": te,
        "net_proceeds_cents": net,
        "admin_allowance_cents": admin,
        "regulatory_fee_cents": reg,
        "charitable_minimum_cents": charitable_min,
        "charitable_use_ratio": ratio,
    }


def ser_financial_report(fr):
    comp = compute_financial_report(fr)
    out = {
        "id": fr["id"],
        "created_at": fmt_dt(fr["created_at"]),
        "updated_at": fmt_dt(fr["updated_at"]),
        "version": fr["version"],
        "license_id": fr["license_id"],
        "period_start": fr["period_start"],
        "period_end": fr["period_end"],
        "charitable_use_cents": fr["charitable_use_cents"],
        "status": fr["status"],
    }
    out.update(comp)
    return out


def ser_violation(v):
    return {
        "id": v["id"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
        "license_id": v["license_id"],
        "violation_type": v["violation_type"],
        "points": v["points"],
        "source": v["source"],
        "status": v["status"],
    }


def ser_renewal(r):
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
        "license_id": r["license_id"],
        "requested_term_months": r["requested_term_months"],
        "status": r["status"],
    }


# =============================================================================
# Cascades & side effects
# =============================================================================
def cancel_occasion_internal(occ):
    """Drive a SCHEDULED occasion to CANCELLED: release prize commit + release allocations."""
    occ["status"] = "CANCELLED"
    touch(occ)
    lic = DB["licenses"].get(occ["license_id"])
    if lic is not None:
        lic["prize_committed_cents"] -= occ["planned_prize_pool_cents"]
        touch(lic)
    for alloc in sorted_items("equipment_allocations",
                              lambda a: a["occasion_id"] == occ["id"] and a["status"] == "ACTIVE"):
        alloc["status"] = "RELEASED"
        touch(alloc)


def cascade_cancel_scheduled(lic):
    for occ in sorted_items("occasions",
                            lambda o: o["license_id"] == lic["id"] and o["status"] == "SCHEDULED"):
        cancel_occasion_internal(occ)


def leave_active(lic, new_status):
    lic["status"] = new_status
    touch(lic)
    cascade_cancel_scheduled(lic)


def recompute_violation_points(lic):
    total = sum(
        v["points"]
        for v in DB["violations"].values()
        if v["license_id"] == lic["id"] and v["status"] == "OPEN"
    )
    if total != lic["total_violation_points_active"]:
        lic["total_violation_points_active"] = total
        touch(lic)


def maybe_auto_suspend(lic):
    if lic["status"] == "ACTIVE" and lic["total_violation_points_active"] >= SUSPENSION_POINT_THRESHOLD:
        leave_active(lic, "SUSPENDED")


def advance_clock_expiries():
    for lic in sorted_items("licenses",
                            lambda l: l["status"] == "ACTIVE"
                            and l["expiration_date"] is not None
                            and CLOCK > l["expiration_date"]):
        leave_active(lic, "EXPIRED")


# =============================================================================
# Organization endpoints
# =============================================================================
@app.route("/organizations", methods=["POST"])
def create_organization():
    role, uid = auth()
    authorize(role, ["Regulator"])
    body = get_body()
    legal_name = req_str(body, "legal_name")
    ein = req_str(body, "ein")
    nonprofit_type = req_enum(body, "nonprofit_type", NONPROFIT_TYPES)
    _, inc_raw = req_datetime(body, "incorporation_date")
    state_code = req_str(body, "state_code")
    good_standing = body.get("good_standing", True)
    if not isinstance(good_standing, bool):
        _validation("good_standing must be a boolean")
    org = new_entity("organizations", {
        "legal_name": legal_name,
        "ein": ein,
        "nonprofit_type": nonprofit_type,
        "incorporation_date": inc_raw,
        "good_standing": good_standing,
        "state_code": state_code,
    })
    return resp_object(ser_org(org), 201)


@app.route("/organizations/<oid>", methods=["GET"])
def get_organization(oid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    org = lookup("organizations", oid)
    return resp_object(ser_org(org))


@app.route("/organizations/<oid>/licenses", methods=["GET"])
def list_org_licenses(oid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    lookup("organizations", oid)
    items = sorted_items("licenses", lambda l: l["organization_id"] == oid)
    return paginate_and_respond([ser_license(x) for x in items])


# =============================================================================
# License endpoints
# =============================================================================
@app.route("/licenses", methods=["POST"])
def create_license():
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    body = get_body()
    organization_id = req_str(body, "organization_id")
    license_type = req_enum(body, "license_type", LICENSE_TYPES)
    contact_email = req_str(body, "contact_email")
    venue_name = req_str(body, "venue_name")
    lookup("organizations", organization_id)
    check_org_ownership(role, uid, organization_id)
    lic = new_entity("licenses", {
        "organization_id": organization_id,
        "license_type": license_type,
        "contact_email": contact_email,
        "venue_name": venue_name,
        "status": "DRAFT",
        "effective_date": None,
        "expiration_date": None,
        "annual_prize_limit_cents": ANNUAL_PRIZE_LIMIT_CENTS[license_type],
        "prize_committed_cents": 0,
        "prize_settled_cents": 0,
        "total_violation_points_active": 0,
    })
    return resp_object(ser_license(lic), 201)


@app.route("/licenses/<lid>", methods=["GET"])
def get_license(lid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    lic = lookup("licenses", lid)
    return resp_object(ser_license(lic))


@app.route("/licenses/<lid>/occasions", methods=["GET"])
def list_license_occasions(lid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    lookup("licenses", lid)
    items = sorted_items("occasions", lambda o: o["license_id"] == lid)
    return paginate_and_respond([ser_occasion(x) for x in items])


@app.route("/licenses/<lid>/financial-reports", methods=["GET"])
def list_license_reports(lid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    lookup("licenses", lid)
    items = sorted_items("financial_reports", lambda f: f["license_id"] == lid)
    return paginate_and_respond([ser_financial_report(x) for x in items])


@app.route("/licenses/<lid>/violations", methods=["GET"])
def list_license_violations(lid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    lookup("licenses", lid)
    items = sorted_items("violations", lambda v: v["license_id"] == lid)
    return paginate_and_respond([ser_violation(x) for x in items])


@app.route("/licenses/<lid>/renewals", methods=["GET"])
def list_license_renewals(lid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    lookup("licenses", lid)
    items = sorted_items("renewals", lambda r: r["license_id"] == lid)
    return paginate_and_respond([ser_renewal(x) for x in items])


@app.route("/licenses/<lid>", methods=["PATCH"])
def patch_license(lid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    lic = lookup("licenses", lid)
    check_org_ownership(role, uid, lic["organization_id"])
    body = get_body()
    expected = req_int(body, "expected_license_version")
    if expected != lic["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_license_version does not match")
    if "contact_email" in body:
        v = body["contact_email"]
        if not isinstance(v, str) or v == "":
            _validation("Invalid contact_email")
        lic["contact_email"] = v
    if "venue_name" in body:
        v = body["venue_name"]
        if not isinstance(v, str) or v == "":
            _validation("Invalid venue_name")
        lic["venue_name"] = v
    touch(lic)
    return resp_object(ser_license(lic))


@app.route("/licenses/<lid>/submit", methods=["POST"])
def submit_license(lid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    lic = lookup("licenses", lid)
    check_org_ownership(role, uid, lic["organization_id"])
    if lic["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "License not in DRAFT")
    lic["status"] = "SUBMITTED"
    touch(lic)
    return resp_object(ser_license(lic))


@app.route("/licenses/<lid>/approve", methods=["POST"])
def approve_license(lid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    lic = lookup("licenses", lid)
    if lic["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "License not in SUBMITTED")
    org = DB["organizations"].get(lic["organization_id"])
    if org is None or compute_eligibility(org) != "ELIGIBLE":
        raise ApiError("ERR_ORG_NOT_ELIGIBLE", 409, "Organization is not eligible")
    lic["status"] = "ACTIVE"
    lic["effective_date"] = CLOCK
    lic["expiration_date"] = add_months(CLOCK, 12)
    touch(lic)
    return resp_object(ser_license(lic))


@app.route("/licenses/<lid>/suspend", methods=["POST"])
def suspend_license(lid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    lic = lookup("licenses", lid)
    if lic["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "License not ACTIVE")
    leave_active(lic, "SUSPENDED")
    return resp_object(ser_license(lic))


@app.route("/licenses/<lid>/reinstate", methods=["POST"])
def reinstate_license(lid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    lic = lookup("licenses", lid)
    if lic["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "License not SUSPENDED")
    if lic["total_violation_points_active"] >= SUSPENSION_POINT_THRESHOLD:
        raise ApiError("ERR_OUTSTANDING_VIOLATIONS", 409, "Outstanding violation points")
    lic["status"] = "ACTIVE"
    touch(lic)
    return resp_object(ser_license(lic))


# =============================================================================
# Occasion endpoints
# =============================================================================
@app.route("/occasions", methods=["POST"])
def create_occasion():
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    body = get_body()
    license_id = req_str(body, "license_id")
    occasion_type = req_enum(body, "occasion_type", OCCASION_TYPES)
    start_dt, start_raw = req_datetime(body, "scheduled_start")
    end_dt, end_raw = req_datetime(body, "scheduled_end")
    venue_name = req_str(body, "venue_name")
    planned_gross = req_int(body, "planned_gross_cents")
    planned_pool = req_int(body, "planned_prize_pool_cents")
    planned_expenses = req_int(body, "planned_expenses_cents")
    lic = lookup("licenses", license_id)
    check_org_ownership(role, uid, lic["organization_id"])
    if not (end_dt > start_dt):
        raise ApiError("ERR_OCCASION_TIME_INVALID", 422, "scheduled_end must be after scheduled_start")
    # overlap against non-CANCELLED occasions on same license (half-open)
    for other in DB["occasions"].values():
        if other["license_id"] != license_id or other["status"] == "CANCELLED":
            continue
        os_ = parse_dt(other["scheduled_start"])
        oe_ = parse_dt(other["scheduled_end"])
        if start_dt < oe_ and os_ < end_dt:
            raise ApiError("ERR_OCCASION_OVERLAP", 409, "Occasion window overlaps existing occasion")
    occ = new_entity("occasions", {
        "license_id": license_id,
        "occasion_type": occasion_type,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "venue_name": venue_name,
        "planned_gross_cents": planned_gross,
        "planned_prize_pool_cents": planned_pool,
        "planned_expenses_cents": planned_expenses,
        "gross_receipts_cents": None,
        "prizes_paid_cents": None,
        "expenses_cents": None,
        "net_proceeds_cents": None,
        "status": "SCHEDULED",
    })
    lic["prize_committed_cents"] += planned_pool
    touch(lic)
    return resp_object(ser_occasion(occ), 201)


@app.route("/occasions/<oid>", methods=["GET"])
def get_occasion(oid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    occ = lookup("occasions", oid)
    return resp_object(ser_occasion(occ))


@app.route("/occasions/<oid>/allocations", methods=["GET"])
def list_occasion_allocations(oid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer", "Supplier"])
    lookup("occasions", oid)
    items = sorted_items("equipment_allocations", lambda a: a["occasion_id"] == oid)
    return paginate_and_respond([ser_allocation(x) for x in items])


@app.route("/occasions/<oid>/hold", methods=["POST"])
def hold_occasion(oid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    occ = lookup("occasions", oid)
    lic = DB["licenses"][occ["license_id"]]
    check_org_ownership(role, uid, lic["organization_id"])
    if occ["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Occasion not SCHEDULED")
    if lic["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409, "License not ACTIVE")
    occ["status"] = "HELD"
    occ["net_proceeds_cents"] = (
        occ["planned_gross_cents"] - occ["planned_prize_pool_cents"] - occ["planned_expenses_cents"]
    )
    touch(occ)
    return resp_object(ser_occasion(occ))


@app.route("/occasions/<oid>/report", methods=["POST"])
def report_occasion(oid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    occ = lookup("occasions", oid)
    lic = DB["licenses"][occ["license_id"]]
    check_org_ownership(role, uid, lic["organization_id"])
    body = get_body()
    gross = req_int(body, "gross_receipts_cents")
    prizes = req_int(body, "prizes_paid_cents")
    expenses = req_int(body, "expenses_cents")
    if occ["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Occasion not HELD")
    if lic["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409, "License not ACTIVE")
    # occasion prize allowance
    per_cap = PER_OCCASION_PRIZE_CAP_CENTS[occ["occasion_type"]]
    committed_other = lic["prize_committed_cents"] - occ["planned_prize_pool_cents"]
    annual_remaining_for_this = lic["annual_prize_limit_cents"] - lic["prize_settled_cents"] - committed_other
    allowance = min(per_cap, annual_remaining_for_this)
    if prizes > allowance:
        raise ApiError("ERR_PRIZE_LIMIT_EXCEEDED", 409, "prizes_paid_cents exceeds allowance")
    # apply
    occ["status"] = "REPORTED"
    occ["gross_receipts_cents"] = gross
    occ["prizes_paid_cents"] = prizes
    occ["expenses_cents"] = expenses
    occ["net_proceeds_cents"] = gross - prizes - expenses
    touch(occ)
    lic["prize_committed_cents"] -= occ["planned_prize_pool_cents"]
    lic["prize_settled_cents"] += prizes
    touch(lic)
    # late report -> auto violation
    sched_end = parse_dt(occ["scheduled_end"])
    if CLOCK > sched_end + timedelta(days=REPORT_GRACE_DAYS):
        new_entity("violations", {
            "license_id": lic["id"],
            "violation_type": "LATE_REPORT",
            "points": POINTS_BY_TYPE["LATE_REPORT"],
            "source": "AUTO",
            "status": "OPEN",
        })
        recompute_violation_points(lic)
        maybe_auto_suspend(lic)
    return resp_object(ser_occasion(occ))


@app.route("/occasions/<oid>/cancel", methods=["POST"])
def cancel_occasion(oid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    occ = lookup("occasions", oid)
    lic = DB["licenses"][occ["license_id"]]
    check_org_ownership(role, uid, lic["organization_id"])
    if occ["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Occasion not SCHEDULED")
    cancel_occasion_internal(occ)
    return resp_object(ser_occasion(occ))


# =============================================================================
# Supplier endpoints
# =============================================================================
@app.route("/suppliers", methods=["POST"])
def create_supplier():
    role, uid = auth()
    authorize(role, ["Regulator"])
    body = get_body()
    business_name = req_str(body, "business_name")
    state_code = req_str(body, "state_code")
    sup = new_entity("suppliers", {
        "business_name": business_name,
        "state_code": state_code,
        "status": "PENDING",
    })
    return resp_object(ser_supplier(sup), 201)


@app.route("/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    role, uid = auth()
    authorize(role, ["Regulator", "Supplier"])
    sup = lookup("suppliers", sid)
    return resp_object(ser_supplier(sup))


@app.route("/suppliers/<sid>/equipment", methods=["GET"])
def list_supplier_equipment(sid):
    role, uid = auth()
    authorize(role, ["Regulator", "Supplier"])
    lookup("suppliers", sid)
    items = sorted_items("equipment", lambda e: e["supplier_id"] == sid)
    return paginate_and_respond([ser_equipment(x) for x in items])


@app.route("/suppliers/<sid>/register", methods=["POST"])
def register_supplier(sid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    sup = lookup("suppliers", sid)
    if sup["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Supplier not PENDING")
    sup["status"] = "REGISTERED"
    touch(sup)
    return resp_object(ser_supplier(sup))


# =============================================================================
# Equipment endpoints
# =============================================================================
@app.route("/equipment", methods=["POST"])
def create_equipment():
    role, uid = auth()
    authorize(role, ["Supplier"])
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    equipment_type = req_enum(body, "equipment_type", EQUIPMENT_TYPES)
    serial_number = req_str(body, "serial_number")
    sup = lookup("suppliers", supplier_id)
    check_supplier_ownership(role, uid, supplier_id)
    if sup["status"] != "REGISTERED":
        raise ApiError("ERR_SUPPLIER_NOT_REGISTERED", 409, "Supplier not REGISTERED")
    for e in DB["equipment"].values():
        if e["supplier_id"] == supplier_id and e["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_SERIAL", 409, "Serial number already registered")
    eq = new_entity("equipment", {
        "supplier_id": supplier_id,
        "equipment_type": equipment_type,
        "serial_number": serial_number,
        "status": "REGISTERED",
    })
    return resp_object(ser_equipment(eq), 201)


@app.route("/equipment/<eid>", methods=["GET"])
def get_equipment(eid):
    role, uid = auth()
    authorize(role, ["Regulator", "Supplier", "OrgOfficer"])
    eq = lookup("equipment", eid)
    return resp_object(ser_equipment(eq))


@app.route("/equipment/<eid>/allocations", methods=["GET"])
def list_equipment_allocations(eid):
    role, uid = auth()
    authorize(role, ["Regulator", "Supplier", "OrgOfficer"])
    lookup("equipment", eid)
    items = sorted_items("equipment_allocations", lambda a: a["equipment_id"] == eid)
    return paginate_and_respond([ser_allocation(x) for x in items])


@app.route("/equipment/<eid>/retire", methods=["POST"])
def retire_equipment(eid):
    role, uid = auth()
    authorize(role, ["Supplier"])
    eq = lookup("equipment", eid)
    check_supplier_ownership(role, uid, eq["supplier_id"])
    if eq["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Equipment not REGISTERED")
    eq["status"] = "RETIRED"
    touch(eq)
    return resp_object(ser_equipment(eq))


# =============================================================================
# EquipmentAllocation endpoints
# =============================================================================
@app.route("/equipment-allocations", methods=["POST"])
def create_allocation():
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    body = get_body()
    equipment_id = req_str(body, "equipment_id")
    occasion_id = req_str(body, "occasion_id")
    start_dt, start_raw = req_datetime(body, "start_date")
    end_dt, end_raw = req_datetime(body, "end_date")
    eq = lookup("equipment", equipment_id)
    occ = lookup("occasions", occasion_id)
    lic = DB["licenses"][occ["license_id"]]
    check_org_ownership(role, uid, lic["organization_id"])
    if end_dt < start_dt:
        raise ApiError("ERR_ALLOCATION_DATE_INVALID", 422, "end_date before start_date")
    if lic["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409, "License not ACTIVE")
    if eq["status"] != "REGISTERED":
        raise ApiError("ERR_EQUIPMENT_NOT_REGISTERED", 409, "Equipment not REGISTERED")
    # buffer overlap against ACTIVE allocations of the same equipment (closed intervals)
    for other in DB["equipment_allocations"].values():
        if other["equipment_id"] != equipment_id or other["status"] != "ACTIVE":
            continue
        os_ = parse_dt(other["start_date"])
        oe_ = parse_dt(other["end_date"])
        separated = (start_dt - oe_ > EQUIPMENT_BUFFER) or (os_ - end_dt > EQUIPMENT_BUFFER)
        if not separated:
            raise ApiError("ERR_EQUIPMENT_ALLOCATION_CONFLICT", 409, "Allocation conflicts within buffer")
    alloc = new_entity("equipment_allocations", {
        "equipment_id": equipment_id,
        "occasion_id": occasion_id,
        "start_date": start_raw,
        "end_date": end_raw,
        "status": "ACTIVE",
    })
    return resp_object(ser_allocation(alloc), 201)


@app.route("/equipment-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer", "Supplier"])
    alloc = lookup("equipment_allocations", aid)
    return resp_object(ser_allocation(alloc))


@app.route("/equipment-allocations/<aid>/release", methods=["POST"])
def release_allocation(aid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    alloc = lookup("equipment_allocations", aid)
    occ = DB["occasions"][alloc["occasion_id"]]
    lic = DB["licenses"][occ["license_id"]]
    check_org_ownership(role, uid, lic["organization_id"])
    if alloc["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Allocation not ACTIVE")
    alloc["status"] = "RELEASED"
    touch(alloc)
    return resp_object(ser_allocation(alloc))


# =============================================================================
# FinancialReport endpoints
# =============================================================================
@app.route("/financial-reports", methods=["POST"])
def create_financial_report():
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    body = get_body()
    license_id = req_str(body, "license_id")
    ps_dt, ps_raw = req_datetime(body, "period_start")
    pe_dt, pe_raw = req_datetime(body, "period_end")
    charitable_use = req_int(body, "charitable_use_cents")
    lic = lookup("licenses", license_id)
    check_org_ownership(role, uid, lic["organization_id"])
    if not (pe_dt > ps_dt):
        raise ApiError("ERR_REPORT_PERIOD_INVALID", 422, "period_end must be after period_start")
    fr = new_entity("financial_reports", {
        "license_id": license_id,
        "period_start": ps_raw,
        "period_end": pe_raw,
        "charitable_use_cents": charitable_use,
        "status": "DRAFT",
    })
    return resp_object(ser_financial_report(fr), 201)


@app.route("/financial-reports/<fid>", methods=["GET"])
def get_financial_report(fid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    fr = lookup("financial_reports", fid)
    return resp_object(ser_financial_report(fr))


@app.route("/financial-reports/<fid>/submit", methods=["POST"])
def submit_financial_report(fid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    fr = lookup("financial_reports", fid)
    lic = DB["licenses"][fr["license_id"]]
    check_org_ownership(role, uid, lic["organization_id"])
    if fr["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Report not DRAFT")
    comp = compute_financial_report(fr)
    if fr["charitable_use_cents"] < comp["charitable_minimum_cents"]:
        raise ApiError("ERR_CHARITABLE_MINIMUM_NOT_MET", 409, "charitable_use below minimum")
    fr["status"] = "SUBMITTED"
    touch(fr)
    return resp_object(ser_financial_report(fr))


@app.route("/financial-reports/<fid>/accept", methods=["POST"])
def accept_financial_report(fid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    fr = lookup("financial_reports", fid)
    if fr["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report not SUBMITTED")
    fr["status"] = "ACCEPTED"
    touch(fr)
    return resp_object(ser_financial_report(fr))


@app.route("/financial-reports/<fid>/reject", methods=["POST"])
def reject_financial_report(fid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    fr = lookup("financial_reports", fid)
    if fr["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report not SUBMITTED")
    fr["status"] = "REJECTED"
    touch(fr)
    return resp_object(ser_financial_report(fr))


@app.route("/financial-reports/<fid>/revise", methods=["POST"])
def revise_financial_report(fid):
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    fr = lookup("financial_reports", fid)
    lic = DB["licenses"][fr["license_id"]]
    check_org_ownership(role, uid, lic["organization_id"])
    if fr["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report not REJECTED")
    fr["status"] = "DRAFT"
    touch(fr)
    return resp_object(ser_financial_report(fr))


# =============================================================================
# Violation endpoints
# =============================================================================
@app.route("/violations", methods=["POST"])
def create_violation():
    role, uid = auth()
    authorize(role, ["Regulator"])
    body = get_body()
    license_id = req_str(body, "license_id")
    violation_type = req_enum(body, "violation_type", VIOLATION_TYPES)
    lic = lookup("licenses", license_id)
    new_entity("violations", {
        "license_id": license_id,
        "violation_type": violation_type,
        "points": POINTS_BY_TYPE[violation_type],
        "source": "MANUAL",
        "status": "OPEN",
    })
    recompute_violation_points(lic)
    maybe_auto_suspend(lic)
    # return the created violation
    created = [v for v in DB["violations"].values() if v["license_id"] == license_id]
    created.sort(key=lambda v: v["_seq"])
    return resp_object(ser_violation(created[-1]), 201)


@app.route("/violations/<vid>", methods=["GET"])
def get_violation(vid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    v = lookup("violations", vid)
    return resp_object(ser_violation(v))


@app.route("/violations/<vid>/waive", methods=["POST"])
def waive_violation(vid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    v = lookup("violations", vid)
    if v["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation not OPEN")
    v["status"] = "WAIVED"
    touch(v)
    lic = DB["licenses"].get(v["license_id"])
    if lic is not None:
        recompute_violation_points(lic)
    return resp_object(ser_violation(v))


# =============================================================================
# Renewal endpoints
# =============================================================================
@app.route("/renewals", methods=["POST"])
def create_renewal():
    role, uid = auth()
    authorize(role, ["OrgOfficer"])
    body = get_body()
    license_id = req_str(body, "license_id")
    expected = req_int(body, "expected_license_version")
    requested_term_months = body.get("requested_term_months", 12)
    if isinstance(requested_term_months, bool) or not isinstance(requested_term_months, int):
        _validation("requested_term_months must be an integer")
    lic = lookup("licenses", license_id)
    check_org_ownership(role, uid, lic["organization_id"])
    if expected != lic["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_license_version does not match")
    # supersede prior REQUESTED renewals for this license
    for r in sorted_items("renewals", lambda x: x["license_id"] == license_id and x["status"] == "REQUESTED"):
        r["status"] = "SUPERSEDED"
        touch(r)
    renewal = new_entity("renewals", {
        "license_id": license_id,
        "requested_term_months": requested_term_months,
        "status": "REQUESTED",
    })
    touch(lic)  # renewal-create advances the license version
    return resp_object(ser_renewal(renewal), 201)


@app.route("/renewals/<rid>", methods=["GET"])
def get_renewal(rid):
    role, uid = auth()
    authorize(role, ["Regulator", "OrgOfficer"])
    r = lookup("renewals", rid)
    return resp_object(ser_renewal(r))


@app.route("/renewals/<rid>/approve", methods=["POST"])
def approve_renewal(rid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    r = lookup("renewals", rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Renewal not REQUESTED")
    lic = DB["licenses"][r["license_id"]]
    base = lic["expiration_date"] if lic["expiration_date"] is not None else CLOCK
    if CLOCK > base:
        base = CLOCK
    lic["expiration_date"] = add_months(base, r["requested_term_months"])
    if lic["status"] == "EXPIRED":
        lic["status"] = "ACTIVE"
    touch(lic)
    r["status"] = "APPROVED"
    touch(r)
    return resp_object(ser_renewal(r))


@app.route("/renewals/<rid>/deny", methods=["POST"])
def deny_renewal(rid):
    role, uid = auth()
    authorize(role, ["Regulator"])
    r = lookup("renewals", rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Renewal not REQUESTED")
    r["status"] = "DENIED"
    touch(r)
    return resp_object(ser_renewal(r))


# =============================================================================
# Logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    role, uid = auth()
    authorize(role, ["Regulator"])
    body = get_body()
    _, _raw = req_datetime(body, "to_iso8601")
    CLOCK = parse_dt(body["to_iso8601"])
    advance_clock_expiries()
    return resp_object({})


# =============================================================================
# Bootstrap
# =============================================================================
reset_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
