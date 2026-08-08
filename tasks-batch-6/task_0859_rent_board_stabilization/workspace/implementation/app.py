import os
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD / PRD)
# ---------------------------------------------------------------------------
BANKED_CAP_PCT = Decimal("0.16")
HARDSHIP_CAP_PCT = Decimal("0.08")
TREBLE_MULTIPLIER = 3
MONTHLY_INTEREST_RATE = Decimal("0.0075")
LATE_REG_PENALTY_CENTS = 50000
FAIL_FILE_PENALTY_CENTS = 100000
SUBSTANTIAL_DECREASE_PCT = Decimal("0.25")
MINOR_DECREASE_PCT = Decimal("0.10")
RELOCATION_MIN_CENTS = 500000
DECONTROL_RENT_THRESHOLD_CENTS = 500000
COOLING_OFF_DAYS = 30
HEARING_BUFFER_MINUTES = 30

ROLES = {"Landlord", "Tenant", "HearingOfficer", "RentBoardClerk", "ComplianceOfficer"}

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process boot; no seeding)
# ---------------------------------------------------------------------------
db = {
    "landlords": {},
    "tenants": {},
    "officers": {},
    "units": {},
    "registrations": {},
    "tenancies": {},
    "agas": {},
    "petitions": {},
    "hearings": {},
    "claims": {},
    "buyouts": {},
    "exemptions": {},
    "penalties": {},
}

clock = {"now": CLOCK_DEFAULT}
_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "units": "ERR_UNIT_NOT_FOUND",
    "landlords": "ERR_LANDLORD_NOT_FOUND",
    "tenants": "ERR_TENANT_NOT_FOUND",
    "officers": "ERR_HEARING_OFFICER_NOT_FOUND",
    "petitions": "ERR_PETITION_NOT_FOUND",
    "hearings": "ERR_HEARING_NOT_FOUND",
    "claims": "ERR_SERVICE_CLAIM_NOT_FOUND",
    "buyouts": "ERR_BUYOUT_NOT_FOUND",
    "exemptions": "ERR_EXEMPTION_NOT_FOUND",
    "penalties": "ERR_PENALTY_NOT_FOUND",
    "tenancies": "ERR_TENANCY_NOT_FOUND",
    "registrations": "ERR_REGISTRATION_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Time helpers (all timestamps rendered from the logical clock)
# ---------------------------------------------------------------------------
def render_dt(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return clock["now"]


def now_iso():
    return render_dt(clock["now"])


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    raw = s.strip()
    try:
        v = raw
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def rhu(value):
    """Round a Decimal half-up to a whole integer (cents)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def q4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def base_entity():
    ts = now_iso()
    return {
        "id": str(uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(e):
    e["version"] = e.get("version", 1) + 1
    e["updated_at"] = now_iso()


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def respond(data, code=200, rtype="object", pagination=None):
    return jsonify({"meta": _meta(pagination), "response_type": rtype, "data": data}), code


def respond_obj(entity, code=200):
    return respond(serialize(entity), code, "object")


def respond_list(entities):
    page, pag = paginate(entities)
    return respond([serialize(e) for e in page], 200, "array", pag)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "invalid %s" % name)


def paginate(items):
    items = sorted(items, key=lambda e: e["_seq"])
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10 if limit_raw is None else parse_int_param(limit_raw, "limit")
    offset = 0 if offset_raw is None else parse_int_param(offset_raw, "offset")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


def find(store_key, rid, err_id=None):
    e = db[store_key].get(rid)
    if e is None:
        raise ApiError(err_id or NOT_FOUND[store_key], 404, "%s not found" % store_key)
    return e


# ---------------------------------------------------------------------------
# Validation field helpers (ERR_VALIDATION)
# ---------------------------------------------------------------------------
def req(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing field: %s" % key)
    return body[key]


def req_str(body, key):
    v = req(body, key)
    if not is_str(v) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "invalid string: %s" % key)
    return v


def req_int(body, key, positive=False, nonneg=False):
    v = req(body, key)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, "invalid integer: %s" % key)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", 400, "must be > 0: %s" % key)
    if nonneg and v < 0:
        raise ApiError("ERR_VALIDATION", 400, "must be >= 0: %s" % key)
    return v


def req_num(body, key, nonneg=False):
    v = req(body, key)
    if not is_num(v):
        raise ApiError("ERR_VALIDATION", 400, "invalid number: %s" % key)
    if nonneg and v < 0:
        raise ApiError("ERR_VALIDATION", 400, "must be >= 0: %s" % key)
    return v


def req_bool(body, key):
    v = req(body, key)
    if not is_bool(v):
        raise ApiError("ERR_VALIDATION", 400, "invalid boolean: %s" % key)
    return v


def req_enum(body, key, allowed):
    v = req(body, key)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "invalid enum: %s" % key)
    return v


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def active_tenancies_of_unit(unit_id):
    return [t for t in db["tenancies"].values()
            if t["unit_id"] == unit_id and t["status"] == "ACTIVE"]


def active_tenancy_for(unit_id, tenant_id):
    for t in db["tenancies"].values():
        if t["unit_id"] == unit_id and t["tenant_id"] == tenant_id and t["status"] == "ACTIVE":
            return t
    return None


def cascade_rent(unit):
    """Mirror the unit's current lawful rent onto its ACTIVE tenancies."""
    for t in active_tenancies_of_unit(unit["id"]):
        t["monthly_rent_cents"] = unit["current_lawful_rent_cents"]
        touch(t)


def check_unique_email(store_key, email):
    for e in db[store_key].values():
        if e.get("email") == email:
            raise ApiError("ERR_VALIDATION", 400, "email already exists")


# ===========================================================================
# ACTORS / CONFIG
# ===========================================================================
@app.route("/rent-board/landlords", methods=["POST"])
def create_landlord():
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk"})
    b = get_body()
    name = req_str(b, "name")
    email = req_str(b, "email")
    lic = req_str(b, "business_license_no")
    check_unique_email("landlords", email)
    e = base_entity()
    e.update({
        "name": name,
        "email": email,
        "business_license_no": lic,
        "escrow_committed_cents": 0,
    })
    db["landlords"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/landlords/<rid>", methods=["GET"])
def get_landlord(rid):
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk", "Landlord", "ComplianceOfficer"})
    return respond_obj(find("landlords", rid))


@app.route("/rent-board/tenants", methods=["POST"])
def create_tenant():
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk"})
    b = get_body()
    name = req_str(b, "name")
    email = req_str(b, "email")
    phone = req_str(b, "phone")
    check_unique_email("tenants", email)
    e = base_entity()
    e.update({"name": name, "email": email, "phone": phone})
    db["tenants"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/tenants/<rid>", methods=["GET"])
def get_tenant(rid):
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk", "Tenant", "Landlord"})
    return respond_obj(find("tenants", rid))


@app.route("/rent-board/hearing-officers", methods=["POST"])
def create_officer():
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk"})
    b = get_body()
    name = req_str(b, "name")
    email = req_str(b, "email")
    active = True
    if "active" in b and b["active"] is not None:
        if not is_bool(b["active"]):
            raise ApiError("ERR_VALIDATION", 400, "invalid boolean: active")
        active = b["active"]
    check_unique_email("officers", email)
    e = base_entity()
    e.update({"name": name, "email": email, "active": active})
    db["officers"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/hearing-officers/<rid>", methods=["GET"])
def get_officer(rid):
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk", "HearingOfficer"})
    return respond_obj(find("officers", rid))


@app.route("/rent-board/aga-determinations", methods=["POST"])
def create_aga():
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk"})
    b = get_body()
    year = req_int(b, "effective_year")
    cpi = req_num(b, "cpi_pct")
    aga = req_num(b, "aga_pct", nonneg=True)
    eff_from = req_str(b, "effective_from")
    eff_to = req_str(b, "effective_to")
    for a in db["agas"].values():
        if a["effective_year"] == year:
            raise ApiError("ERR_VALIDATION", 400, "effective_year already exists")
    # AGADetermination is immutable: only id + created_at, no updated_at/version.
    e = {
        "id": str(uuid4()),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "effective_year": year,
        "cpi_pct": cpi,
        "aga_pct": aga,
        "effective_from": eff_from,
        "effective_to": eff_to,
    }
    db["agas"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/aga-determinations", methods=["GET"])
def list_aga():
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk", "Landlord"})
    items = list(db["agas"].values())
    yr = request.args.get("effective_year")
    if yr is not None:
        yv = parse_int_param(yr, "effective_year")
        items = [a for a in items if a["effective_year"] == yv]
    return respond_list(items)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk"})
    b = get_body()
    to_iso = req_str(b, "to_iso8601")
    clock["now"] = parse_dt(to_iso)
    return respond({}, 200, "object")


# ===========================================================================
# UNITS
# ===========================================================================
@app.route("/rent-board/units", methods=["POST"])
def create_unit():
    uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk"})
    b = get_body()
    landlord_id = req_str(b, "landlord_id")
    address = req_str(b, "address")
    bedrooms = req_int(b, "bedrooms", nonneg=True)
    base_rent = req_int(b, "base_rent_cents", positive=True)
    # ownership: a landlord may only register a unit for itself
    if role == "Landlord" and landlord_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    find("landlords", landlord_id)
    e = base_entity()
    e.update({
        "landlord_id": landlord_id,
        "address": address,
        "bedrooms": bedrooms,
        "base_rent_cents": base_rent,
        "current_lawful_rent_cents": base_rent,
        "banked_pct": 0,
        "stabilization_status": "STABILIZED",
        "decrease_active": False,
    })
    db["units"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/units/<rid>", methods=["GET"])
def get_unit(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "Tenant", "HearingOfficer", "ComplianceOfficer"})
    return respond_obj(find("units", rid))


@app.route("/rent-board/units", methods=["GET"])
def list_units():
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "ComplianceOfficer"})
    items = list(db["units"].values())
    lid = request.args.get("landlord_id")
    if lid is not None:
        items = [u for u in items if u["landlord_id"] == lid]
    return respond_list(items)


@app.route("/rent-board/units/<rid>/registrations", methods=["POST"])
def create_registration(rid):
    uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk"})
    unit = find("units", rid)
    b = get_body()
    year = req_int(b, "registration_year")
    declared = req_int(b, "declared_rent_cents", positive=True)
    expected = req_int(b, "expected_unit_version")
    # OCC (last)
    if expected != unit["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale unit version")
    # supersede prior ACTIVE registration
    for r in db["registrations"].values():
        if r["unit_id"] == rid and r["status"] == "ACTIVE":
            r["status"] = "SUPERSEDED"
            touch(r)
    e = base_entity()
    e.update({
        "unit_id": rid,
        "registration_year": year,
        "declared_rent_cents": declared,
        "status": "ACTIVE",
        "filed_by": uid,
    })
    db["registrations"][e["id"]] = e
    touch(unit)
    return respond_obj(e, 201)


@app.route("/rent-board/units/<rid>/registrations", methods=["GET"])
def list_registrations(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "ComplianceOfficer"})
    find("units", rid)
    items = [r for r in db["registrations"].values() if r["unit_id"] == rid]
    return respond_list(items)


@app.route("/rent-board/units/<rid>/rent-adjustments", methods=["POST"])
def rent_adjustment(rid):
    uid, role = authenticate()
    authorize(role, {"Landlord"})
    unit = find("units", rid)
    # ownership (path resource loaded)
    if unit["landlord_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    b = get_body()
    effective_date = req_str(b, "effective_date")
    proposed = req_int(b, "proposed_new_rent_cents")
    apply_banked = req_bool(b, "apply_banked")
    expected = req_int(b, "expected_unit_version")
    eff_dt = parse_dt(effective_date)
    # unit must be stabilized
    if unit["stabilization_status"] != "STABILIZED":
        raise ApiError("ERR_UNIT_NOT_STABILIZED", 409, "unit not stabilized")
    # select AGA by calendar year of effective_date
    aga = None
    for a in db["agas"].values():
        if a["effective_year"] == eff_dt.year:
            aga = a
            break
    if aga is None:
        raise ApiError("ERR_NO_AGA_DETERMINATION", 422, "no AGA determination for year")
    prior = unit["current_lawful_rent_cents"]
    aga_pct = Decimal(str(aga["aga_pct"]))
    banked = Decimal(str(unit["banked_pct"]))
    if apply_banked:
        allowable_pct = min(aga_pct + banked, BANKED_CAP_PCT)
    else:
        allowable_pct = aga_pct
    max_new = rhu(Decimal(prior) * (Decimal(1) + allowable_pct))
    # two-sided boundary
    if proposed > max_new or proposed < prior:
        raise ApiError("ERR_INCREASE_EXCEEDS_ALLOWABLE", 422, "increase exceeds allowable")
    # OCC (last)
    if expected != unit["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale unit version")
    # apply
    taken_pct = (Decimal(proposed) - Decimal(prior)) / Decimal(prior)
    if not apply_banked:
        banked_delta = max(Decimal(0), aga_pct - taken_pct)
        new_banked = min(q4(banked + banked_delta), BANKED_CAP_PCT)
    else:
        consumed = max(Decimal(0), taken_pct - aga_pct)
        new_banked = max(Decimal(0), q4(banked - consumed))
    unit["current_lawful_rent_cents"] = proposed
    unit["banked_pct"] = float(new_banked)
    cascade_rent(unit)
    touch(unit)
    return respond_obj(unit, 200)


@app.route("/rent-board/units/<rid>/exemptions", methods=["GET"])
def list_unit_exemptions(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "ComplianceOfficer"})
    find("units", rid)
    items = [e for e in db["exemptions"].values() if e["unit_id"] == rid]
    return respond_list(items)


# ===========================================================================
# TENANCIES
# ===========================================================================
@app.route("/rent-board/tenancies", methods=["POST"])
def create_tenancy():
    uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk"})
    b = get_body()
    unit_id = req_str(b, "unit_id")
    tenant_id = req_str(b, "tenant_id")
    unit = find("units", unit_id)
    if role == "Landlord" and unit["landlord_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    find("tenants", tenant_id)
    start_date = req_str(b, "start_date")
    end_date = b.get("end_date")
    if end_date is not None and not is_str(end_date):
        raise ApiError("ERR_VALIDATION", 400, "invalid end_date")
    start_dt = parse_dt(start_date)
    end_dt = parse_dt(end_date) if end_date else None
    # unit must be stabilized
    if unit["stabilization_status"] != "STABILIZED":
        raise ApiError("ERR_UNIT_NOT_STABILIZED", 409, "unit not stabilized")
    # occupancy overlap (half-open, adjacency allowed)
    new_end_val = end_dt if end_dt else datetime.max.replace(tzinfo=UTC)
    for t in active_tenancies_of_unit(unit_id):
        s = t["_start_dt"]
        e_val = t["_end_dt"] if t["_end_dt"] else datetime.max.replace(tzinfo=UTC)
        if start_dt < e_val and s < new_end_val:
            raise ApiError("ERR_UNIT_OCCUPIED", 409, "unit occupied")
    e = base_entity()
    e.update({
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
        "monthly_rent_cents": unit["current_lawful_rent_cents"],
        "status": "ACTIVE",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db["tenancies"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/tenancies/<rid>", methods=["GET"])
def get_tenancy(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "Tenant"})
    return respond_obj(find("tenancies", rid))


@app.route("/rent-board/tenancies", methods=["GET"])
def list_tenancies():
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk"})
    items = list(db["tenancies"].values())
    unit_id = request.args.get("unit_id")
    tenant_id = request.args.get("tenant_id")
    if unit_id is not None:
        items = [t for t in items if t["unit_id"] == unit_id]
    if tenant_id is not None:
        items = [t for t in items if t["tenant_id"] == tenant_id]
    return respond_list(items)


@app.route("/rent-board/tenancies/<rid>/end", methods=["POST"])
def end_tenancy(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk"})
    t = find("tenancies", rid)
    b = get_body()
    if t["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "tenancy not active")
    end_date = b.get("end_date")
    if end_date is not None:
        if not is_str(end_date):
            raise ApiError("ERR_VALIDATION", 400, "invalid end_date")
        t["_end_dt"] = parse_dt(end_date)
    else:
        end_date = now_iso()
        t["_end_dt"] = now_dt()
    t["end_date"] = end_date
    t["status"] = "ENDED"
    touch(t)
    return respond_obj(t, 200)


# ===========================================================================
# PETITIONS
# ===========================================================================
@app.route("/rent-board/petitions", methods=["POST"])
def create_petition():
    uid, role = authenticate()
    authorize(role, {"Landlord"})
    b = get_body()
    # ownership: landlord may only file naming itself (body-id compare, pre-existence)
    landlord_id = b.get("landlord_id")
    if landlord_id is not None and is_str(landlord_id) and landlord_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    unit_id = req_str(b, "unit_id")
    landlord_id = req_str(b, "landlord_id")
    if landlord_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    ptype = req_enum(b, "petition_type", {"CAPITAL_IMPROVEMENT", "HARDSHIP"})
    find("units", unit_id)
    find("landlords", landlord_id)
    requested_cost = None
    amortization = None
    requested_pct = None
    if ptype == "CAPITAL_IMPROVEMENT":
        requested_cost = req_int(b, "requested_cost_cents", positive=True)
        amortization = req_int(b, "amortization_months", positive=True)
    else:
        requested_pct = req_num(b, "requested_pct")
    e = base_entity()
    e.update({
        "unit_id": unit_id,
        "landlord_id": landlord_id,
        "petition_type": ptype,
        "requested_cost_cents": requested_cost,
        "amortization_months": amortization,
        "requested_pct": requested_pct,
        "status": "DRAFT",
        "granted_amount_cents": 0,
        "revision_count": 0,
    })
    db["petitions"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/petitions/<rid>/submit", methods=["POST"])
def submit_petition(rid):
    uid, role = authenticate()
    authorize(role, {"Landlord"})
    p = find("petitions", rid)
    if p["landlord_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    if p["status"] not in ("DRAFT", "NEEDS_REVISION"):
        raise ApiError("ERR_INVALID_STATE", 409, "cannot submit from state")
    if p["status"] == "NEEDS_REVISION":
        p["revision_count"] += 1
    p["status"] = "SUBMITTED"
    touch(p)
    return respond_obj(p, 200)


@app.route("/rent-board/petitions/<rid>/review", methods=["POST"])
def review_petition(rid):
    _uid, role = authenticate()
    authorize(role, {"HearingOfficer"})
    p = find("petitions", rid)
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "cannot review from state")
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return respond_obj(p, 200)


@app.route("/rent-board/petitions/<rid>/request-revision", methods=["POST"])
def request_revision(rid):
    _uid, role = authenticate()
    authorize(role, {"HearingOfficer"})
    p = find("petitions", rid)
    if p["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "cannot request revision from state")
    p["status"] = "NEEDS_REVISION"
    touch(p)
    return respond_obj(p, 200)


@app.route("/rent-board/petitions/<rid>/hearings", methods=["POST"])
def schedule_hearing(rid):
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk"})
    p = find("petitions", rid)
    b = get_body()
    officer_id = req_str(b, "officer_id")
    officer = find("officers", officer_id)
    scheduled_start = req_str(b, "scheduled_start")
    scheduled_end = req_str(b, "scheduled_end")
    s_dt = parse_dt(scheduled_start)
    e_dt = parse_dt(scheduled_end)
    if e_dt <= s_dt:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end must be after scheduled_start")
    # petition must be UNDER_REVIEW
    if p["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PETITION_NOT_UNDER_REVIEW", 409, "petition not under review")
    # officer overlap (half-open + buffer)
    buf = timedelta(minutes=HEARING_BUFFER_MINUTES)
    for h in db["hearings"].values():
        if h["officer_id"] == officer_id and h["status"] == "SCHEDULED":
            hs = h["_sched_start"]
            he = h["_sched_end"]
            if s_dt < he + buf and hs < e_dt + buf:
                raise ApiError("ERR_OFFICER_UNAVAILABLE", 409, "officer unavailable")
    h = base_entity()
    h.update({
        "petition_id": rid,
        "officer_id": officer_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "decision": None,
        "_sched_start": s_dt,
        "_sched_end": e_dt,
    })
    db["hearings"][h["id"]] = h
    p["status"] = "HEARING_SCHEDULED"
    touch(p)
    return respond_obj(h, 201)


@app.route("/rent-board/petitions/<rid>", methods=["GET"])
def get_petition(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "HearingOfficer"})
    return respond_obj(find("petitions", rid))


@app.route("/rent-board/petitions", methods=["GET"])
def list_petitions():
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "HearingOfficer"})
    items = list(db["petitions"].values())
    unit_id = request.args.get("unit_id")
    landlord_id = request.args.get("landlord_id")
    if unit_id is not None:
        items = [p for p in items if p["unit_id"] == unit_id]
    if landlord_id is not None:
        items = [p for p in items if p["landlord_id"] == landlord_id]
    return respond_list(items)


def compute_full_passthrough(petition, unit):
    if petition["petition_type"] == "CAPITAL_IMPROVEMENT":
        monthly_amortized = rhu(Decimal(petition["requested_cost_cents"]) /
                                Decimal(petition["amortization_months"]))
        bedrooms = unit["bedrooms"]
        if bedrooms <= 1:
            cap_pct = Decimal("0.05")
        elif bedrooms <= 3:
            cap_pct = Decimal("0.06")
        else:
            cap_pct = Decimal("0.07")
        monthly_cap = rhu(Decimal(unit["base_rent_cents"]) * cap_pct)
        return min(monthly_amortized, monthly_cap)
    else:
        requested = rhu(Decimal(unit["current_lawful_rent_cents"]) *
                        Decimal(str(petition["requested_pct"])))
        hardship_cap = rhu(Decimal(unit["current_lawful_rent_cents"]) * HARDSHIP_CAP_PCT)
        return min(requested, hardship_cap)


# ===========================================================================
# HEARINGS
# ===========================================================================
@app.route("/rent-board/hearings/<rid>/decide", methods=["POST"])
def decide_hearing(rid):
    _uid, role = authenticate()
    authorize(role, {"HearingOfficer"})
    h = find("hearings", rid)
    b = get_body()
    decision = req_enum(b, "decision", {"GRANT", "PARTIAL", "DENY"})
    p = db["petitions"].get(h["petition_id"])
    if h["status"] != "SCHEDULED" or (p and p["status"] != "HEARING_SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409, "hearing not decidable")
    unit = db["units"].get(p["unit_id"])
    full = compute_full_passthrough(p, unit)
    if decision == "GRANT":
        granted = full
    elif decision == "PARTIAL":
        granted = req_int(b, "granted_amount_cents")
        if not (0 < granted < full):
            raise ApiError("ERR_INVALID_GRANT_AMOUNT", 422, "invalid grant amount")
    else:  # DENY
        granted = 0
    h["status"] = "HELD"
    h["decision"] = decision
    touch(h)
    if decision == "DENY":
        p["status"] = "DENIED"
        p["granted_amount_cents"] = 0
        touch(p)
    else:
        p["granted_amount_cents"] = granted
        p["status"] = "GRANTED" if decision == "GRANT" else "PARTIAL"
        touch(p)
        unit["current_lawful_rent_cents"] += granted
        cascade_rent(unit)
        touch(unit)
    return respond_obj(h, 200)


@app.route("/rent-board/hearings/<rid>", methods=["GET"])
def get_hearing(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "HearingOfficer"})
    return respond_obj(find("hearings", rid))


@app.route("/rent-board/hearings", methods=["GET"])
def list_hearings():
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk", "HearingOfficer"})
    items = list(db["hearings"].values())
    petition_id = request.args.get("petition_id")
    officer_id = request.args.get("officer_id")
    if petition_id is not None:
        items = [h for h in items if h["petition_id"] == petition_id]
    if officer_id is not None:
        items = [h for h in items if h["officer_id"] == officer_id]
    return respond_list(items)


# ===========================================================================
# SERVICE CLAIMS
# ===========================================================================
@app.route("/rent-board/service-claims", methods=["POST"])
def create_claim():
    uid, role = authenticate()
    authorize(role, {"Tenant"})
    b = get_body()
    tenant_id = b.get("tenant_id")
    if tenant_id is not None and is_str(tenant_id) and tenant_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    unit_id = req_str(b, "unit_id")
    tenant_id = req_str(b, "tenant_id")
    if tenant_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    claim_type = req_enum(b, "claim_type", {"HEAT", "WATER", "MAINTENANCE", "PEST"})
    severity = req_enum(b, "severity", {"MINOR", "SUBSTANTIAL"})
    find("units", unit_id)
    find("tenants", tenant_id)
    # tenant must be the unit's ACTIVE tenant
    if active_tenancy_for(unit_id, tenant_id) is None:
        raise ApiError("ERR_TENANT_NOT_LINKED", 422, "tenant not linked to unit")
    e = base_entity()
    e.update({
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "claim_type": claim_type,
        "severity": severity,
        "status": "OPEN",
        "ordered_decrease_pct": None,
        "decrease_amount_cents": 0,
        "pre_decrease_rent_cents": None,
    })
    db["claims"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/service-claims/<rid>/investigate", methods=["POST"])
def investigate_claim(rid):
    _uid, role = authenticate()
    authorize(role, {"HearingOfficer", "RentBoardClerk"})
    c = find("claims", rid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "claim not open")
    c["status"] = "INVESTIGATING"
    touch(c)
    return respond_obj(c, 200)


@app.route("/rent-board/service-claims/<rid>/decide", methods=["POST"])
def decide_claim(rid):
    _uid, role = authenticate()
    authorize(role, {"HearingOfficer"})
    c = find("claims", rid)
    b = get_body()
    disposition = req_enum(b, "disposition", {"SUBSTANTIATE", "DISMISS"})
    if c["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_STATE", 409, "claim not investigating")
    if disposition == "DISMISS":
        c["status"] = "DISMISSED"
        touch(c)
        return respond_obj(c, 200)
    # SUBSTANTIATE: requires an ACTIVE tenancy for the claiming tenant
    if active_tenancy_for(c["unit_id"], c["tenant_id"]) is None:
        raise ApiError("ERR_TENANT_NOT_LINKED", 422, "tenant not linked to unit")
    unit = db["units"][c["unit_id"]]
    pre = unit["current_lawful_rent_cents"]
    pct = SUBSTANTIAL_DECREASE_PCT if c["severity"] == "SUBSTANTIAL" else MINOR_DECREASE_PCT
    decrease = rhu(Decimal(pre) * pct)
    c["pre_decrease_rent_cents"] = pre
    c["ordered_decrease_pct"] = float(pct)
    c["decrease_amount_cents"] = decrease
    c["status"] = "SUBSTANTIATED"
    touch(c)
    unit["current_lawful_rent_cents"] = pre - decrease
    unit["decrease_active"] = True
    cascade_rent(unit)
    touch(unit)
    return respond_obj(c, 200)


@app.route("/rent-board/service-claims/<rid>/restore", methods=["POST"])
def restore_claim(rid):
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk", "HearingOfficer"})
    c = find("claims", rid)
    if c["status"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE", 409, "claim not substantiated")
    unit = db["units"][c["unit_id"]]
    if not unit["decrease_active"]:
        raise ApiError("ERR_INVALID_STATE", 409, "unit decrease not active")
    unit["current_lawful_rent_cents"] = c["pre_decrease_rent_cents"]
    unit["decrease_active"] = False
    cascade_rent(unit)
    touch(unit)
    c["status"] = "RESTORED"
    touch(c)
    return respond_obj(c, 200)


@app.route("/rent-board/service-claims/<rid>", methods=["GET"])
def get_claim(rid):
    _uid, role = authenticate()
    authorize(role, {"Tenant", "Landlord", "RentBoardClerk", "HearingOfficer"})
    return respond_obj(find("claims", rid))


@app.route("/rent-board/service-claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "HearingOfficer"})
    items = list(db["claims"].values())
    unit_id = request.args.get("unit_id")
    tenant_id = request.args.get("tenant_id")
    if unit_id is not None:
        items = [c for c in items if c["unit_id"] == unit_id]
    if tenant_id is not None:
        items = [c for c in items if c["tenant_id"] == tenant_id]
    return respond_list(items)


# ===========================================================================
# BUYOUTS
# ===========================================================================
@app.route("/rent-board/buyouts", methods=["POST"])
def create_buyout():
    uid, role = authenticate()
    authorize(role, {"Landlord"})
    b = get_body()
    landlord_id = b.get("landlord_id")
    if landlord_id is not None and is_str(landlord_id) and landlord_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    unit_id = req_str(b, "unit_id")
    landlord_id = req_str(b, "landlord_id")
    if landlord_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    tenant_id = req_str(b, "tenant_id")
    find("units", unit_id)
    find("landlords", landlord_id)
    find("tenants", tenant_id)
    offer = req_int(b, "offer_amount_cents", positive=True)
    relocation = req_int(b, "relocation_amount_cents", nonneg=True)
    if active_tenancy_for(unit_id, tenant_id) is None:
        raise ApiError("ERR_TENANT_NOT_LINKED", 422, "tenant not linked to unit")
    e = base_entity()
    e.update({
        "unit_id": unit_id,
        "landlord_id": landlord_id,
        "tenant_id": tenant_id,
        "offer_amount_cents": offer,
        "relocation_amount_cents": relocation,
        "disclosure_acknowledged": False,
        "status": "DRAFT",
        "filed_at": None,
        "rescind_deadline": None,
        "_rescind_dt": None,
    })
    db["buyouts"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/buyouts/<rid>/file", methods=["POST"])
def file_buyout(rid):
    uid, role = authenticate()
    authorize(role, {"Landlord"})
    bo = find("buyouts", rid)
    if bo["landlord_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    b = get_body()
    if bo["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "buyout not in draft")
    disclosure = b.get("disclosure_acknowledged")
    if disclosure is not True:
        raise ApiError("ERR_DISCLOSURE_REQUIRED", 422, "disclosure required")
    if bo["relocation_amount_cents"] < RELOCATION_MIN_CENTS:
        raise ApiError("ERR_RELOCATION_BELOW_MINIMUM", 422, "relocation below minimum")
    filed_dt = now_dt()
    rescind_dt = filed_dt + timedelta(days=COOLING_OFF_DAYS)
    bo["disclosure_acknowledged"] = True
    bo["status"] = "FILED"
    bo["filed_at"] = render_dt(filed_dt)
    bo["rescind_deadline"] = render_dt(rescind_dt)
    bo["_rescind_dt"] = rescind_dt
    touch(bo)
    landlord = db["landlords"][bo["landlord_id"]]
    landlord["escrow_committed_cents"] += bo["relocation_amount_cents"]
    touch(landlord)
    return respond_obj(bo, 200)


@app.route("/rent-board/buyouts/<rid>/rescind", methods=["POST"])
def rescind_buyout(rid):
    uid, role = authenticate()
    authorize(role, {"Tenant"})
    bo = find("buyouts", rid)
    if bo["tenant_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    if bo["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "buyout not filed")
    if now_dt() > bo["_rescind_dt"]:
        raise ApiError("ERR_COOLING_OFF_EXPIRED", 409, "cooling-off expired")
    bo["status"] = "RESCINDED"
    touch(bo)
    landlord = db["landlords"][bo["landlord_id"]]
    landlord["escrow_committed_cents"] -= bo["relocation_amount_cents"]
    touch(landlord)
    return respond_obj(bo, 200)


@app.route("/rent-board/buyouts/<rid>/complete", methods=["POST"])
def complete_buyout(rid):
    _uid, role = authenticate()
    authorize(role, {"RentBoardClerk"})
    bo = find("buyouts", rid)
    if bo["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "buyout not filed")
    if now_dt() < bo["_rescind_dt"]:
        raise ApiError("ERR_COOLING_OFF_NOT_ELAPSED", 409, "cooling-off not elapsed")
    bo["status"] = "COMPLETED"
    touch(bo)
    landlord = db["landlords"][bo["landlord_id"]]
    landlord["escrow_committed_cents"] -= bo["relocation_amount_cents"]
    touch(landlord)
    # cascade: end the tenant's ACTIVE tenancy on the unit
    t = active_tenancy_for(bo["unit_id"], bo["tenant_id"])
    if t is not None:
        completion = now_dt()
        t["status"] = "ENDED"
        t["end_date"] = render_dt(completion)
        t["_end_dt"] = completion
        touch(t)
    return respond_obj(bo, 200)


@app.route("/rent-board/buyouts/<rid>", methods=["GET"])
def get_buyout(rid):
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk", "Tenant"})
    return respond_obj(find("buyouts", rid))


@app.route("/rent-board/buyouts", methods=["GET"])
def list_buyouts():
    _uid, role = authenticate()
    authorize(role, {"Landlord", "RentBoardClerk"})
    items = list(db["buyouts"].values())
    unit_id = request.args.get("unit_id")
    landlord_id = request.args.get("landlord_id")
    tenant_id = request.args.get("tenant_id")
    if unit_id is not None:
        items = [x for x in items if x["unit_id"] == unit_id]
    if landlord_id is not None:
        items = [x for x in items if x["landlord_id"] == landlord_id]
    if tenant_id is not None:
        items = [x for x in items if x["tenant_id"] == tenant_id]
    return respond_list(items)


# ===========================================================================
# EXEMPTIONS
# ===========================================================================
@app.route("/rent-board/exemptions", methods=["POST"])
def create_exemption():
    _uid, role = authenticate()
    authorize(role, {"Landlord"})
    b = get_body()
    unit_id = req_str(b, "unit_id")
    find("units", unit_id)
    etype = req_enum(b, "exemption_type",
                     {"SUBSTANTIAL_REHAB", "OWNER_OCCUPIED", "VACANCY_DECONTROL", "NEW_CONSTRUCTION"})
    vacancy_rent = b.get("vacancy_rent_cents")
    if vacancy_rent is not None and not is_int(vacancy_rent):
        raise ApiError("ERR_VALIDATION", 400, "invalid vacancy_rent_cents")
    effective_date = b.get("effective_date")
    if effective_date is not None and not is_str(effective_date):
        raise ApiError("ERR_VALIDATION", 400, "invalid effective_date")
    e = base_entity()
    e.update({
        "unit_id": unit_id,
        "exemption_type": etype,
        "status": "REQUESTED",
        "effective_date": None,
        "vacancy_rent_cents": vacancy_rent,
    })
    db["exemptions"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/exemptions/<rid>/decide", methods=["POST"])
def decide_exemption(rid):
    _uid, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    ex = find("exemptions", rid)
    b = get_body()
    decision = req_enum(b, "decision", {"APPROVE", "DENY"})
    effective_date = b.get("effective_date")
    if effective_date is not None and not is_str(effective_date):
        raise ApiError("ERR_VALIDATION", 400, "invalid effective_date")
    if ex["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "exemption not requested")
    unit = db["units"][ex["unit_id"]]
    if decision == "DENY":
        ex["status"] = "DENIED"
        touch(ex)
        return respond_obj(ex, 200)
    # APPROVE
    if unit["stabilization_status"] != "STABILIZED":
        raise ApiError("ERR_UNIT_NOT_STABILIZED", 409, "unit not stabilized")
    if ex["exemption_type"] == "VACANCY_DECONTROL":
        if len(active_tenancies_of_unit(unit["id"])) > 0:
            raise ApiError("ERR_UNIT_NOT_VACANT", 409, "unit not vacant")
        vr = ex["vacancy_rent_cents"]
        if vr is None or vr < DECONTROL_RENT_THRESHOLD_CENTS:
            raise ApiError("ERR_DECONTROL_THRESHOLD_NOT_MET", 422, "decontrol threshold not met")
        unit["stabilization_status"] = "DECONTROLLED"
    else:
        unit["stabilization_status"] = "EXEMPT"
    touch(unit)
    if effective_date is not None:
        ex["effective_date"] = effective_date
    ex["status"] = "APPROVED"
    touch(ex)
    return respond_obj(ex, 200)


# ===========================================================================
# PENALTIES
# ===========================================================================
@app.route("/rent-board/penalties", methods=["POST"])
def create_penalty():
    uid, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    b = get_body()
    unit_id = req_str(b, "unit_id")
    landlord_id = req_str(b, "landlord_id")
    find("units", unit_id)
    find("landlords", landlord_id)
    ptype = req_enum(b, "penalty_type", {"OVERCHARGE", "LATE_REGISTRATION", "FAILURE_TO_FILE"})
    months = None
    monthly = None
    willful = False
    if ptype == "LATE_REGISTRATION":
        assessed = LATE_REG_PENALTY_CENTS
    elif ptype == "FAILURE_TO_FILE":
        assessed = FAIL_FILE_PENALTY_CENTS
    else:
        months = req_int(b, "months_overcharged", nonneg=True)
        monthly = req_int(b, "monthly_overcharge_cents", nonneg=True)
        if "willful" in b and b["willful"] is not None:
            if not is_bool(b["willful"]):
                raise ApiError("ERR_VALIDATION", 400, "invalid willful")
            willful = b["willful"]
        base = months * monthly
        if willful:
            assessed = base * TREBLE_MULTIPLIER
        else:
            per_month_interest = rhu(Decimal(monthly) * MONTHLY_INTEREST_RATE)
            interest_total = per_month_interest * months
            assessed = base + interest_total
    e = base_entity()
    e.update({
        "unit_id": unit_id,
        "landlord_id": landlord_id,
        "penalty_type": ptype,
        "months_overcharged": months,
        "monthly_overcharge_cents": monthly,
        "willful": willful,
        "assessed_amount_cents": assessed,
        "status": "ASSESSED",
        "assessed_by": uid,
        "confirmed_by": None,
    })
    db["penalties"][e["id"]] = e
    return respond_obj(e, 201)


@app.route("/rent-board/penalties/<rid>/confirm", methods=["POST"])
def confirm_penalty(rid):
    uid, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    p = find("penalties", rid)
    if p["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "penalty not assessed")
    if uid == p["assessed_by"]:
        raise ApiError("ERR_SOD_VIOLATION", 403, "segregation of duties violation")
    p["status"] = "CONFIRMED"
    p["confirmed_by"] = uid
    touch(p)
    return respond_obj(p, 200)


@app.route("/rent-board/penalties/<rid>", methods=["GET"])
def get_penalty(rid):
    _uid, role = authenticate()
    authorize(role, {"ComplianceOfficer", "RentBoardClerk", "Landlord"})
    return respond_obj(find("penalties", rid))


@app.route("/rent-board/penalties", methods=["GET"])
def list_penalties():
    _uid, role = authenticate()
    authorize(role, {"ComplianceOfficer", "RentBoardClerk", "Landlord"})
    items = list(db["penalties"].values())
    unit_id = request.args.get("unit_id")
    landlord_id = request.args.get("landlord_id")
    if unit_id is not None:
        items = [x for x in items if x["unit_id"] == unit_id]
    if landlord_id is not None:
        items = [x for x in items if x["landlord_id"] == landlord_id]
    return respond_list(items)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
