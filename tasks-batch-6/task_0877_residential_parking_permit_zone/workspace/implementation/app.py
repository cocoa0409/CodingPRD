import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Global constants
# ---------------------------------------------------------------------------
PROOF_VALIDITY_DAYS = 365
RENEWAL_WINDOW_DAYS = 60
REVOKE_UPHELD_THRESHOLD = 3
REFUND_ADMIN_FEE_CENTS = 2000
REPEAT_THRESHOLD = 2
ESCALATION_MULTIPLIER = 2
MIN_FINE_CENTS = 2500
MAX_FINE_CENTS = 25000
BASE_FINE_CENTS = {"NO_PERMIT": 7500, "EXPIRED_PERMIT": 5000, "ZONE_VIOLATION": 5000}
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"
MONTHS_PER_YEAR = 12

ROLES = {"Resident", "ParkingClerk", "PermitSupervisor", "EnforcementOfficer", "Anonymous"}

OCCUPYING = {"ACTIVE", "SUSPENDED", "RENEWAL_PENDING"}

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
DB = {
    "zones": {},
    "households": {},
    "vehicles": {},
    "proofs": {},
    "applications": {},
    "permits": {},
    "passes": {},
    "waitlist": {},
    "citations": {},
    "complaints": {},
}
_SEQ = {"n": 0}
CLOCK = {"now": None}


def reset_clock():
    CLOCK["now"] = parse_dt(CLOCK_DEFAULT_UTC)


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    txt = s.strip()
    t = txt
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso_z(dt):
    """Render a datetime as ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}" + "Z"


def now():
    return CLOCK["now"]


def now_str():
    return iso_z(CLOCK["now"])


def fiscal_year_end_on_or_after(dt):
    cand = datetime(dt.year, 3, 31, 23, 59, 59, 0, tzinfo=UTC)
    if cand >= dt:
        return cand
    return datetime(dt.year + 1, 3, 31, 23, 59, 59, 0, tzinfo=UTC)


def next_fiscal_year_end_after(dt):
    cand = datetime(dt.year, 3, 31, 23, 59, 59, 0, tzinfo=UTC)
    if cand > dt:
        return cand
    return datetime(dt.year + 1, 3, 31, 23, 59, 59, 0, tzinfo=UTC)


def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def base_entity():
    ts = now_str()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(e):
    e["updated_at"] = now_str()
    e["version"] = e.get("version", 1) + 1


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": iso_z(datetime.now(UTC))}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, list_meta=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": meta(list_meta), "response_type": rtype, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(e: ApiError):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_VALIDATION", 400, str(e)))


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def get_body():
    raw = request.get_data()
    if not raw:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        err("ERR_VALIDATION", 400, "Malformed JSON body")
    if not isinstance(body, dict):
        err("ERR_VALIDATION", 400, "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            err("ERR_VALIDATION", 400, f"Missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        err("ERR_VALIDATION", 400, f"Invalid value for {field}")


def require_nonneg_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        err("ERR_VALIDATION", 400, f"{field} must be a non-negative integer")
    return value


def require_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool):
        err("ERR_VALIDATION", 400, f"{field} must be an integer")
    return value


def parse_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        err("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        err("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, serialize):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    lm = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serialize(x) for x in page], 200, lm)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def find(coll, rid):
    return DB[coll].get(rid)


def get_or_404(coll, rid):
    ent = DB[coll].get(rid)
    if ent is None:
        err("ERR_NOT_FOUND", 404, f"{coll} not found")
    return ent


# ---------------------------------------------------------------------------
# Computed quantities
# ---------------------------------------------------------------------------
def zone_active_count(zone_id):
    return sum(
        1 for p in DB["permits"].values()
        if p["zone_id"] == zone_id and p["status"] in OCCUPYING
    )


def household_active_count(household_id):
    return sum(
        1 for p in DB["permits"].values()
        if p["household_id"] == household_id and p["status"] in OCCUPYING
    )


def zone_fees_collected(zone_id):
    return sum(
        p.get("fee_paid_cents", 0) for p in DB["permits"].values()
        if p["zone_id"] == zone_id
    )


def zone_fees_refunded(zone_id):
    return sum(
        p.get("refund_amount_cents", 0) for p in DB["permits"].values()
        if p["zone_id"] == zone_id and p["status"] == "REFUNDED"
    )


def zone_waitlist_count(zone_id):
    return sum(
        1 for w in DB["waitlist"].values()
        if w["zone_id"] == zone_id and w["status"] == "WAITING"
    )


def permit_upheld_count(permit_id):
    return sum(
        1 for c in DB["citations"].values()
        if c.get("permit_id") == permit_id and c["status"] == "UPHELD"
    )


def waitlist_position(entry):
    # A non-WAITING entry has no live rank. The only non-WAITING transition in
    # this system is PROMOTED, and promotion always selects position 1, so 1 is
    # the correct frozen rank (and keeps position a positive integer for reads).
    if entry["status"] != "WAITING":
        return 1
    waiting = [
        w for w in DB["waitlist"].values()
        if w["zone_id"] == entry["zone_id"] and w["status"] == "WAITING"
    ]
    waiting.sort(key=lambda w: w["_seq"])
    for idx, w in enumerate(waiting):
        if w["id"] == entry["id"]:
            return idx + 1
    return 1


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_zone(z):
    d = common(z)
    d.update({
        "name": z["name"],
        "zone_code": z["zone_code"],
        "permit_capacity": z["permit_capacity"],
        "max_permits_per_household": z["max_permits_per_household"],
        "guest_pass_daily_limit": z["guest_pass_daily_limit"],
        "permit_annual_fee_cents": z["permit_annual_fee_cents"],
        "visitor_pass_fee_cents": z["visitor_pass_fee_cents"],
        "status": z["status"],
        "active_permit_count": zone_active_count(z["id"]),
        "waitlist_count": zone_waitlist_count(z["id"]),
        "fees_collected_cents": zone_fees_collected(z["id"]),
        "fees_refunded_cents": zone_fees_refunded(z["id"]),
    })
    return d


def ser_household(h):
    d = common(h)
    d.update({
        "zone_id": h["zone_id"],
        "unit_address": h["unit_address"],
        "resident_name": h["resident_name"],
        "contact_email": h["contact_email"],
        "status": h["status"],
        "proof_status": h["proof_status"],
        "proof_verified_at": h["proof_verified_at"],
        "proof_expires_at": h["proof_expires_at"],
        "active_permit_count": household_active_count(h["id"]),
    })
    return d


def ser_vehicle(v):
    d = common(v)
    d.update({
        "household_id": v["household_id"],
        "license_plate": v["license_plate"],
        "make": v["make"],
        "model": v["model"],
        "status": v["status"],
    })
    return d


def ser_proof(p):
    d = common(p)
    d.update({
        "household_id": p["household_id"],
        "document_type": p["document_type"],
        "status": p["status"],
        "reviewer_user_id": p["reviewer_user_id"],
        "verified_at": p["verified_at"],
        "expires_at": p["expires_at"],
    })
    return d


def ser_application(a):
    d = common(a)
    d.update({
        "zone_id": a["zone_id"],
        "household_id": a["household_id"],
        "vehicle_id": a["vehicle_id"],
        "status": a["status"],
        "reviewer_user_id": a["reviewer_user_id"],
        "decided_by_user_id": a["decided_by_user_id"],
        "denial_reason": a["denial_reason"],
        "permit_id": a["permit_id"],
    })
    return d


def ser_permit(p):
    d = common(p)
    d.update({
        "application_id": p["application_id"],
        "zone_id": p["zone_id"],
        "household_id": p["household_id"],
        "vehicle_id": p["vehicle_id"],
        "permit_number": p["permit_number"],
        "license_plate": p["license_plate"],
        "status": p["status"],
        "issued_at": p["issued_at"],
        "expires_at": p["expires_at"],
        "fee_paid_cents": p["fee_paid_cents"],
        "refund_amount_cents": p["refund_amount_cents"],
        "refund_type": p["refund_type"],
        "upheld_citation_count": permit_upheld_count(p["id"]),
        "transferred_to_permit_id": p["transferred_to_permit_id"],
    })
    return d


def ser_pass(v):
    d = common(v)
    d.update({
        "household_id": v["household_id"],
        "permit_id": v["permit_id"],
        "pass_type": v["pass_type"],
        "guest_plate": v["guest_plate"],
        "valid_from": v["valid_from"],
        "valid_until": v["valid_until"],
        "status": v["status"],
        "fee_charged_cents": v["fee_charged_cents"],
    })
    return d


def ser_waitlist(w):
    d = common(w)
    d.update({
        "zone_id": w["zone_id"],
        "application_id": w["application_id"],
        "household_id": w["household_id"],
        "position": waitlist_position(w),
        "status": w["status"],
    })
    return d


def ser_citation(c):
    d = common(c)
    d.update({
        "zone_id": c["zone_id"],
        "permit_id": c["permit_id"],
        "license_plate": c["license_plate"],
        "violation_type": c["violation_type"],
        "fine_amount_cents": c["fine_amount_cents"],
        "fine_variant": c["fine_variant"],
        "prior_upheld_count": c["prior_upheld_count"],
        "status": c["status"],
        "issuing_officer_id": c["issuing_officer_id"],
        "adjudicator_id": c["adjudicator_id"],
    })
    return d


def ser_complaint(c):
    d = common(c)
    d.update({
        "zone_id": c["zone_id"],
        "complaint_type": c["complaint_type"],
        "target_plate": c["target_plate"],
        "description": c["description"],
        "status": c["status"],
        "resolution_note": c["resolution_note"],
        "created_citation_id": c["created_citation_id"],
    })
    return d


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def permit_issuance_fee(zone, issued_dt, expires_dt):
    monthly_rate = rhu(Decimal(zone["permit_annual_fee_cents"]) / Decimal(MONTHS_PER_YEAR))
    remaining_months = (expires_dt.year * 12 + expires_dt.month) - (
        issued_dt.year * 12 + issued_dt.month
    )
    return monthly_rate * remaining_months


def permit_refund_amount(permit, refund_type):
    issued = parse_dt(permit["issued_at"])
    expires = parse_dt(permit["expires_at"])
    total_days = (expires.date() - issued.date()).days
    remaining_days = max(0, (expires.date() - now().date()).days)
    if total_days <= 0:
        prorated = 0
    else:
        prorated = rhu(Decimal(permit["fee_paid_cents"]) * Decimal(remaining_days) / Decimal(total_days))
    if refund_type == "VOLUNTARY":
        return max(0, prorated - REFUND_ADMIN_FEE_CENTS)
    return prorated


def citation_fine(zone_id, license_plate, violation_type):
    base = BASE_FINE_CENTS[violation_type]
    prior = sum(
        1 for c in DB["citations"].values()
        if c["license_plate"] == license_plate
        and c["zone_id"] == zone_id
        and c["status"] == "UPHELD"
    )
    if prior < REPEAT_THRESHOLD:
        return base, "STANDARD", prior
    raw = base * (ESCALATION_MULTIPLIER ** (prior - REPEAT_THRESHOLD + 1))
    fine = max(MIN_FINE_CENTS, min(raw, MAX_FINE_CENTS))
    return fine, "REPEAT_OFFENDER", prior


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------
def resident_owns_household(role, uid, household_id):
    if role == "Resident" and household_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only act on its own household")


def citation_owner_household(c):
    pid = c.get("permit_id")
    if not pid:
        return None
    p = DB["permits"].get(pid)
    if not p:
        return None
    return p["household_id"]


# ---------------------------------------------------------------------------
# Permit minting & issuance
# ---------------------------------------------------------------------------
def mint_permit(application, zone):
    issued = now()
    expires = fiscal_year_end_on_or_after(issued)
    fee = permit_issuance_fee(zone, issued, expires)
    vehicle = DB["vehicles"].get(application["vehicle_id"])
    plate = vehicle["license_plate"] if vehicle else None
    permit = base_entity()
    permit.update({
        "application_id": application["id"],
        "zone_id": zone["id"],
        "household_id": application["household_id"],
        "vehicle_id": application["vehicle_id"],
        "permit_number": "PERMIT-" + uuid.uuid4().hex[:10].upper(),
        "license_plate": plate,
        "status": "ACTIVE",
        "issued_at": iso_z(issued),
        "expires_at": iso_z(expires),
        "fee_paid_cents": fee,
        "refund_amount_cents": 0,
        "refund_type": None,
        "transferred_to_permit_id": None,
    })
    DB["permits"][permit["id"]] = permit
    application["permit_id"] = permit["id"]
    return permit


def check_permit_period_overlap(vehicle_id, issued_dt, expires_dt, exclude_permit_id=None):
    for p in DB["permits"].values():
        if p["vehicle_id"] != vehicle_id:
            continue
        if p["status"] not in OCCUPYING:
            continue
        if exclude_permit_id and p["id"] == exclude_permit_id:
            continue
        p_iss = parse_dt(p["issued_at"])
        p_exp = parse_dt(p["expires_at"])
        # closed-interval intersection
        if issued_dt <= p_exp and p_iss <= expires_dt:
            err("ERR_PERMIT_PERIOD_OVERLAP", 409, "Vehicle already holds an overlapping permit")


def try_promote_oldest(zone):
    """Attempt to promote the single oldest WAITING entry. Returns True on promotion."""
    waiting = [
        w for w in DB["waitlist"].values()
        if w["zone_id"] == zone["id"] and w["status"] == "WAITING"
    ]
    if not waiting:
        return False
    if zone_active_count(zone["id"]) >= zone["permit_capacity"]:
        return False
    waiting.sort(key=lambda w: w["_seq"])
    entry = waiting[0]
    household = DB["households"].get(entry["household_id"])
    if not household or household["proof_status"] != "VERIFIED":
        return False
    if household_active_count(household["id"]) >= zone["max_permits_per_household"]:
        return False
    application = DB["applications"].get(entry["application_id"])
    if not application:
        return False
    entry["status"] = "PROMOTED"
    touch(entry)
    application["status"] = "APPROVED"
    application["decided_by_user_id"] = "system"
    mint_permit(application, zone)
    touch(application)
    touch(zone)  # issuance bumps zone version
    return True


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Clock ----
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        parsed = parse_dt(body["to_iso8601"])
    except Exception:
        err("ERR_VALIDATION", 400, "Invalid to_iso8601")
    CLOCK["now"] = parsed
    return ok({}, 200)


# ---- Zones ----
@app.route("/zones", methods=["POST"])
def create_zone():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    body = get_body()
    require_fields(body, [
        "name", "zone_code", "permit_capacity", "max_permits_per_household",
        "guest_pass_daily_limit", "permit_annual_fee_cents", "visitor_pass_fee_cents",
    ])
    require_nonneg_int(body["permit_capacity"], "permit_capacity")
    require_nonneg_int(body["max_permits_per_household"], "max_permits_per_household")
    require_nonneg_int(body["guest_pass_daily_limit"], "guest_pass_daily_limit")
    require_nonneg_int(body["permit_annual_fee_cents"], "permit_annual_fee_cents")
    require_nonneg_int(body["visitor_pass_fee_cents"], "visitor_pass_fee_cents")
    for z in DB["zones"].values():
        if z["zone_code"] == body["zone_code"]:
            err("ERR_VALIDATION", 400, "zone_code must be unique")
    zone = base_entity()
    zone.update({
        "name": body["name"],
        "zone_code": body["zone_code"],
        "permit_capacity": body["permit_capacity"],
        "max_permits_per_household": body["max_permits_per_household"],
        "guest_pass_daily_limit": body["guest_pass_daily_limit"],
        "permit_annual_fee_cents": body["permit_annual_fee_cents"],
        "visitor_pass_fee_cents": body["visitor_pass_fee_cents"],
        "status": "ACTIVE",
    })
    DB["zones"][zone["id"]] = zone
    return ok(ser_zone(zone), 201)


@app.route("/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    zone = get_or_404("zones", zone_id)
    return ok(ser_zone(zone), 200)


@app.route("/zones/<zone_id>/suspend", methods=["POST"])
def suspend_zone(zone_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    zone = get_or_404("zones", zone_id)
    if zone["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Zone is not ACTIVE")
    zone["status"] = "SUSPENDED"
    touch(zone)
    # CASCADE: ACTIVE/RENEWAL_PENDING permits -> SUSPENDED; their ACTIVE passes -> CANCELLED
    for p in DB["permits"].values():
        if p["zone_id"] == zone_id and p["status"] in ("ACTIVE", "RENEWAL_PENDING"):
            p["status"] = "SUSPENDED"
            touch(p)
            for vp in DB["passes"].values():
                if vp["permit_id"] == p["id"] and vp["status"] == "ACTIVE":
                    vp["status"] = "CANCELLED"
                    touch(vp)
    return ok(ser_zone(zone), 200)


@app.route("/zones/<zone_id>/reactivate", methods=["POST"])
def reactivate_zone(zone_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    zone = get_or_404("zones", zone_id)
    if zone["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Zone is not SUSPENDED")
    zone["status"] = "ACTIVE"
    touch(zone)
    for p in DB["permits"].values():
        if p["zone_id"] == zone_id and p["status"] == "SUSPENDED":
            hh = DB["households"].get(p["household_id"])
            if hh and hh["proof_status"] == "VERIFIED":
                p["status"] = "ACTIVE"
                touch(p)
    return ok(ser_zone(zone), 200)


@app.route("/zones/<zone_id>/run-expiry", methods=["POST"])
def run_expiry(zone_id):
    uid, role = get_auth()
    require_roles(role, {"ParkingClerk"})
    zone = get_or_404("zones", zone_id)
    cur = now()
    # 1) proof expiry: households in zone whose proof passed proof_expires_at
    for h in DB["households"].values():
        if h["zone_id"] != zone_id:
            continue
        if h["proof_status"] == "VERIFIED" and h.get("proof_expires_at"):
            if cur > parse_dt(h["proof_expires_at"]):
                h["proof_status"] = "EXPIRED"
                touch(h)
                for p in DB["permits"].values():
                    if p["household_id"] == h["id"] and p["status"] == "ACTIVE":
                        p["status"] = "SUSPENDED"
                        touch(p)
    # 2) permit expiry -> free slot -> promote
    freed = 0
    permits_by_seq = sorted(DB["permits"].values(), key=lambda p: p["_seq"])
    for p in permits_by_seq:
        if p["zone_id"] != zone_id:
            continue
        if p["status"] in OCCUPYING and cur > parse_dt(p["expires_at"]):
            p["status"] = "EXPIRED"
            touch(p)
            touch(zone)
            freed += 1
    # 3) visitor pass expiry
    for vp in DB["passes"].values():
        h = DB["households"].get(vp["household_id"])
        if not h or h["zone_id"] != zone_id:
            continue
        if vp["status"] == "ACTIVE" and cur >= parse_dt(vp["valid_until"]):
            vp["status"] = "EXPIRED"
            touch(vp)
    # 4) promotions for freed slots
    for _ in range(freed):
        if not try_promote_oldest(zone):
            break
    return ok(ser_zone(zone), 200)


# ---- Households ----
@app.route("/households", methods=["POST"])
def create_household():
    body = get_body()
    require_fields(body, ["zone_id", "unit_address", "resident_name", "contact_email"])
    zone = get_or_404("zones", body["zone_id"])
    h = base_entity()
    h.update({
        "zone_id": body["zone_id"],
        "unit_address": body["unit_address"],
        "resident_name": body["resident_name"],
        "contact_email": body["contact_email"],
        "status": "ACTIVE",
        "proof_status": "UNVERIFIED",
        "proof_verified_at": None,
        "proof_expires_at": None,
    })
    DB["households"][h["id"]] = h
    return ok(ser_household(h), 201)


@app.route("/households/<household_id>", methods=["GET"])
def get_household(household_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    h = get_or_404("households", household_id)
    if role == "Resident" and household_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only read its own household")
    return ok(ser_household(h), 200)


@app.route("/households", methods=["GET"])
def list_households():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk"})
    zone_id = request.args.get("zone_id")
    items = [h for h in DB["households"].values() if not zone_id or h["zone_id"] == zone_id]
    return paginate(items, ser_household)


# ---- Vehicles ----
@app.route("/households/<household_id>/vehicles", methods=["POST"])
def create_vehicle(household_id):
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    if household_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only register vehicles for its own household")
    h = get_or_404("households", household_id)
    body = get_body()
    require_fields(body, ["license_plate", "make", "model"])
    for v in DB["vehicles"].values():
        if v["household_id"] == household_id and v["status"] == "ACTIVE" and v["license_plate"] == body["license_plate"]:
            err("ERR_VALIDATION", 400, "license_plate must be unique among active vehicles")
    v = base_entity()
    v.update({
        "household_id": household_id,
        "license_plate": body["license_plate"],
        "make": body["make"],
        "model": body["model"],
        "status": "ACTIVE",
    })
    DB["vehicles"][v["id"]] = v
    return ok(ser_vehicle(v), 201)


@app.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    v = get_or_404("vehicles", vehicle_id)
    if role == "Resident" and v["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only read its own vehicles")
    return ok(ser_vehicle(v), 200)


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    household_id = request.args.get("household_id")
    items = list(DB["vehicles"].values())
    if household_id:
        items = [v for v in items if v["household_id"] == household_id]
    if role == "Resident":
        items = [v for v in items if v["household_id"] == uid]
    return paginate(items, ser_vehicle)


# ---- Proof submissions ----
@app.route("/households/<household_id>/proof-submissions", methods=["POST"])
def create_proof(household_id):
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    if household_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only submit proof for its own household")
    h = get_or_404("households", household_id)
    body = get_body()
    require_fields(body, ["document_type"])
    require_enum(body["document_type"], {"LEASE", "UTILITY_BILL", "DEED", "ID_CARD"}, "document_type")
    p = base_entity()
    p.update({
        "household_id": household_id,
        "document_type": body["document_type"],
        "status": "PENDING",
        "reviewer_user_id": None,
        "verified_at": None,
        "expires_at": None,
    })
    DB["proofs"][p["id"]] = p
    return ok(ser_proof(p), 201)


@app.route("/proof-submissions/<proof_id>", methods=["GET"])
def get_proof(proof_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    p = get_or_404("proofs", proof_id)
    if role == "Resident" and p["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only read its own proof submissions")
    return ok(ser_proof(p), 200)


@app.route("/proof-submissions", methods=["GET"])
def list_proofs():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    household_id = request.args.get("household_id")
    items = list(DB["proofs"].values())
    if household_id:
        items = [p for p in items if p["household_id"] == household_id]
    if role == "Resident":
        items = [p for p in items if p["household_id"] == uid]
    return paginate(items, ser_proof)


@app.route("/proof-submissions/<proof_id>/review", methods=["POST"])
def review_proof(proof_id):
    uid, role = get_auth()
    require_roles(role, {"ParkingClerk"})
    p = get_or_404("proofs", proof_id)
    body = get_body()
    require_fields(body, ["outcome"])
    require_enum(body["outcome"], {"VERIFIED", "REJECTED"}, "outcome")
    if p["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Proof submission is not PENDING")
    h = DB["households"].get(p["household_id"])
    p["reviewer_user_id"] = uid
    if body["outcome"] == "VERIFIED":
        cur = now()
        expires = cur + timedelta(days=PROOF_VALIDITY_DAYS)
        p["status"] = "VERIFIED"
        p["verified_at"] = iso_z(cur)
        p["expires_at"] = iso_z(expires)
        if h:
            h["proof_status"] = "VERIFIED"
            h["proof_verified_at"] = iso_z(cur)
            h["proof_expires_at"] = iso_z(expires)
            touch(h)
    else:
        p["status"] = "REJECTED"
    touch(p)
    return ok(ser_proof(p), 200)


# ---- Permit applications ----
@app.route("/permit-applications", methods=["POST"])
def create_application():
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    body = get_body()
    require_fields(body, ["zone_id", "household_id", "vehicle_id"])
    resident_owns_household(role, uid, body["household_id"])
    zone = get_or_404("zones", body["zone_id"])
    household = get_or_404("households", body["household_id"])
    vehicle = get_or_404("vehicles", body["vehicle_id"])
    # referential: vehicle must be ACTIVE and belong to household
    if vehicle["status"] != "ACTIVE" or vehicle["household_id"] != household["id"]:
        err("ERR_VEHICLE_HOUSEHOLD_MISMATCH", 409, "Vehicle is not an active vehicle of the household")
    # duplicate open application for same household + vehicle
    for a in DB["applications"].values():
        if a["household_id"] == household["id"] and a["vehicle_id"] == vehicle["id"] \
                and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "WAITLISTED"):
            err("ERR_DUPLICATE_APPLICATION", 409, "An open application for this household and vehicle already exists")
    a = base_entity()
    a.update({
        "zone_id": body["zone_id"],
        "household_id": body["household_id"],
        "vehicle_id": body["vehicle_id"],
        "status": "SUBMITTED",
        "reviewer_user_id": None,
        "decided_by_user_id": None,
        "denial_reason": None,
        "permit_id": None,
    })
    DB["applications"][a["id"]] = a
    return ok(ser_application(a), 201)


@app.route("/permit-applications/<application_id>", methods=["GET"])
def get_application(application_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    a = get_or_404("applications", application_id)
    if role == "Resident" and a["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only read its own applications")
    return ok(ser_application(a), 200)


@app.route("/permit-applications", methods=["GET"])
def list_applications():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    items = list(DB["applications"].values())
    for key in ("zone_id", "household_id", "vehicle_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    if role == "Resident":
        items = [a for a in items if a["household_id"] == uid]
    return paginate(items, ser_application)


@app.route("/permit-applications/<application_id>/review", methods=["POST"])
def review_application(application_id):
    uid, role = get_auth()
    require_roles(role, {"ParkingClerk"})
    a = get_or_404("applications", application_id)
    if a["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Application is not SUBMITTED")
    household = DB["households"].get(a["household_id"])
    zone = DB["zones"].get(a["zone_id"])
    if not household or household["proof_status"] != "VERIFIED":
        err("ERR_PROOF_NOT_VERIFIED", 422, "Household proof is not verified")
    if zone and zone["status"] != "ACTIVE":
        err("ERR_ZONE_SUSPENDED", 409, "Zone is suspended")
    if household["status"] != "ACTIVE":
        err("ERR_HOUSEHOLD_SUSPENDED", 409, "Household is suspended")
    a["status"] = "UNDER_REVIEW"
    a["reviewer_user_id"] = uid
    touch(a)
    return ok(ser_application(a), 200)


@app.route("/permit-applications/<application_id>/approve", methods=["POST"])
def approve_application(application_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    a = get_or_404("applications", application_id)
    body = get_body()
    require_fields(body, ["expected_zone_version"])
    require_int(body["expected_zone_version"], "expected_zone_version")
    zone = DB["zones"].get(a["zone_id"])
    household = DB["households"].get(a["household_id"])
    # state
    if a["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    # business-safety
    if not household or household["proof_status"] != "VERIFIED":
        err("ERR_PROOF_NOT_VERIFIED", 422, "Household proof is not verified")
    if zone and zone["status"] != "ACTIVE":
        err("ERR_ZONE_SUSPENDED", 409, "Zone is suspended")
    if household["status"] != "ACTIVE":
        err("ERR_HOUSEHOLD_SUSPENDED", 409, "Household is suspended")
    # temporal: permit-period overlap
    issued = now()
    expires = fiscal_year_end_on_or_after(issued)
    check_permit_period_overlap(a["vehicle_id"], issued, expires)
    # constraint: vehicle cap
    if household_active_count(household["id"]) >= zone["max_permits_per_household"]:
        err("ERR_HOUSEHOLD_VEHICLE_CAP", 409, "Household is at its vehicle cap")
    # density
    if zone_active_count(zone["id"]) >= zone["permit_capacity"]:
        err("ERR_ZONE_AT_CAPACITY", 409, "Zone is at capacity")
    # OCC
    if body["expected_zone_version"] != zone["version"]:
        err("ERR_ZONE_VERSION_CONFLICT", 412, "Stale expected_zone_version")
    # issue
    permit = mint_permit(a, zone)
    a["status"] = "APPROVED"
    a["decided_by_user_id"] = uid
    touch(a)
    touch(zone)
    return ok(ser_permit(permit), 201)


@app.route("/permit-applications/<application_id>/waitlist", methods=["POST"])
def waitlist_application(application_id):
    uid, role = get_auth()
    require_roles(role, {"ParkingClerk"})
    a = get_or_404("applications", application_id)
    if a["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    zone = DB["zones"].get(a["zone_id"])
    if zone and zone["status"] != "ACTIVE":
        err("ERR_ZONE_SUSPENDED", 409, "Zone is suspended")
    if zone_active_count(zone["id"]) < zone["permit_capacity"]:
        err("ERR_INVALID_STATE", 409, "Zone is not at capacity; cannot waitlist")
    a["status"] = "WAITLISTED"
    touch(a)
    w = base_entity()
    w.update({
        "zone_id": a["zone_id"],
        "application_id": a["id"],
        "household_id": a["household_id"],
        "status": "WAITING",
    })
    DB["waitlist"][w["id"]] = w
    return ok(ser_waitlist(w), 201)


@app.route("/permit-applications/<application_id>/deny", methods=["POST"])
def deny_application(application_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    a = get_or_404("applications", application_id)
    body = get_body()
    require_fields(body, ["denial_reason"])
    if a["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    a["status"] = "DENIED"
    a["denial_reason"] = body["denial_reason"]
    a["decided_by_user_id"] = uid
    touch(a)
    return ok(ser_application(a), 200)


# ---- Permits ----
@app.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    p = get_or_404("permits", permit_id)
    if role == "Resident" and p["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only read its own permits")
    return ok(ser_permit(p), 200)


@app.route("/permits", methods=["GET"])
def list_permits():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    items = list(DB["permits"].values())
    for key in ("zone_id", "household_id", "vehicle_id", "application_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    if role == "Resident":
        items = [p for p in items if p["household_id"] == uid]
    return paginate(items, ser_permit)


@app.route("/permits/<permit_id>/renew", methods=["POST"])
def renew_permit(permit_id):
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    p = get_or_404("permits", permit_id)
    if p["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only renew its own permits")
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Permit is not ACTIVE")
    expires = parse_dt(p["expires_at"])
    window_start = expires - timedelta(days=RENEWAL_WINDOW_DAYS)
    if now() < window_start:
        err("ERR_RENEWAL_WINDOW", 422, "Renewal requested outside the renewal window")
    p["status"] = "RENEWAL_PENDING"
    touch(p)
    return ok(ser_permit(p), 200)


@app.route("/permits/<permit_id>/renew-approve", methods=["POST"])
def renew_approve_permit(permit_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    p = get_or_404("permits", permit_id)
    body = get_body()
    require_fields(body, ["expected_permit_version"])
    require_int(body["expected_permit_version"], "expected_permit_version")
    if p["status"] != "RENEWAL_PENDING":
        err("ERR_INVALID_STATE", 409, "Permit is not RENEWAL_PENDING")
    household = DB["households"].get(p["household_id"])
    if not household or household["proof_status"] != "VERIFIED":
        err("ERR_PROOF_NOT_VERIFIED", 422, "Household proof is not verified")
    if body["expected_permit_version"] != p["version"]:
        err("ERR_PERMIT_VERSION_CONFLICT", 412, "Stale expected_permit_version")
    zone = DB["zones"].get(p["zone_id"])
    new_expires = next_fiscal_year_end_after(parse_dt(p["expires_at"]))
    p["status"] = "ACTIVE"
    p["expires_at"] = iso_z(new_expires)
    p["fee_paid_cents"] += zone["permit_annual_fee_cents"]
    touch(p)
    return ok(ser_permit(p), 200)


@app.route("/permits/<permit_id>/transfer", methods=["POST"])
def transfer_permit(permit_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    p = get_or_404("permits", permit_id)
    body = get_body()
    require_fields(body, ["vehicle_id"])
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Permit is not ACTIVE")
    vehicle = get_or_404("vehicles", body["vehicle_id"])
    if vehicle["status"] != "ACTIVE" or vehicle["household_id"] != p["household_id"]:
        err("ERR_VEHICLE_HOUSEHOLD_MISMATCH", 409, "Target vehicle is not an active vehicle of the same household")
    issued = parse_dt(p["issued_at"])
    expires = parse_dt(p["expires_at"])
    check_permit_period_overlap(vehicle["id"], issued, expires, exclude_permit_id=p["id"])
    successor = base_entity()
    successor.update({
        "application_id": p["application_id"],
        "zone_id": p["zone_id"],
        "household_id": p["household_id"],
        "vehicle_id": vehicle["id"],
        "permit_number": "PERMIT-" + uuid.uuid4().hex[:10].upper(),
        "license_plate": vehicle["license_plate"],
        "status": "ACTIVE",
        "issued_at": p["issued_at"],
        "expires_at": p["expires_at"],
        "fee_paid_cents": p["fee_paid_cents"],
        "refund_amount_cents": 0,
        "refund_type": None,
        "transferred_to_permit_id": None,
    })
    DB["permits"][successor["id"]] = successor
    p["status"] = "TRANSFERRED"
    p["transferred_to_permit_id"] = successor["id"]
    touch(p)
    return ok(ser_permit(successor), 201)


@app.route("/permits/<permit_id>/refund", methods=["POST"])
def refund_permit(permit_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    p = get_or_404("permits", permit_id)
    body = get_body()
    require_fields(body, ["refund_type"])
    require_enum(body["refund_type"], {"VOLUNTARY", "ADMINISTRATIVE"}, "refund_type")
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "Permit is not ACTIVE or SUSPENDED")
    amount = permit_refund_amount(p, body["refund_type"])
    p["status"] = "REFUNDED"
    p["refund_amount_cents"] = amount
    p["refund_type"] = body["refund_type"]
    touch(p)
    zone = DB["zones"].get(p["zone_id"])
    touch(zone)
    try_promote_oldest(zone)
    return ok(ser_permit(p), 200)


@app.route("/permits/<permit_id>/revoke", methods=["POST"])
def revoke_permit(permit_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor"})
    p = get_or_404("permits", permit_id)
    get_body()  # reason optional
    if p["status"] not in ("ACTIVE", "SUSPENDED", "RENEWAL_PENDING"):
        err("ERR_INVALID_STATE", 409, "Permit cannot be revoked from its current state")
    _do_revoke(p)
    return ok(ser_permit(p), 200)


def _do_revoke(p):
    p["status"] = "REVOKED"
    touch(p)
    zone = DB["zones"].get(p["zone_id"])
    touch(zone)
    try_promote_oldest(zone)


# ---- Visitor passes ----
@app.route("/visitor-passes", methods=["POST"])
def create_pass():
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    body = get_body()
    require_fields(body, ["household_id", "permit_id", "pass_type", "guest_plate", "valid_from", "valid_until"])
    require_enum(body["pass_type"], {"GUEST_DAILY", "TEMPORARY"}, "pass_type")
    resident_owns_household(role, uid, body["household_id"])
    try:
        vf = parse_dt(body["valid_from"])
        vu = parse_dt(body["valid_until"])
    except Exception:
        err("ERR_VALIDATION", 400, "Invalid valid_from/valid_until")
    if vu <= vf:
        err("ERR_VALIDATION", 400, "valid_until must be after valid_from")
    household = get_or_404("households", body["household_id"])
    permit = get_or_404("permits", body["permit_id"])
    if permit["status"] != "ACTIVE" or permit["household_id"] != household["id"]:
        err("ERR_PERMIT_HOUSEHOLD_MISMATCH", 409, "Permit is not an active permit owned by the household")
    # overlap: same household + guest_plate, existing ACTIVE pass, half-open intervals
    for vp in DB["passes"].values():
        if vp["household_id"] == household["id"] and vp["guest_plate"] == body["guest_plate"] and vp["status"] == "ACTIVE":
            e_vf = parse_dt(vp["valid_from"])
            e_vu = parse_dt(vp["valid_until"])
            if vf < e_vu and e_vf < vu:
                err("ERR_VISITOR_PASS_OVERLAP", 409, "New pass overlaps an existing active pass")
    zone = DB["zones"].get(household["zone_id"])
    if body["pass_type"] == "GUEST_DAILY":
        day = vf.date()
        used = sum(
            1 for vp in DB["passes"].values()
            if vp["household_id"] == household["id"]
            and vp["pass_type"] == "GUEST_DAILY"
            and vp["status"] in ("ACTIVE", "EXPIRED")
            and parse_dt(vp["valid_from"]).date() == day
        )
        if used >= zone["guest_pass_daily_limit"]:
            err("ERR_GUEST_PASS_LIMIT", 409, "Guest pass daily limit reached")
        fee = 0
    else:
        fee = zone["visitor_pass_fee_cents"]
    vp = base_entity()
    vp.update({
        "household_id": body["household_id"],
        "permit_id": body["permit_id"],
        "pass_type": body["pass_type"],
        "guest_plate": body["guest_plate"],
        "valid_from": body["valid_from"],
        "valid_until": body["valid_until"],
        "status": "ACTIVE",
        "fee_charged_cents": fee,
    })
    DB["passes"][vp["id"]] = vp
    return ok(ser_pass(vp), 201)


@app.route("/visitor-passes/<pass_id>", methods=["GET"])
def get_pass(pass_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    vp = get_or_404("passes", pass_id)
    if role == "Resident" and vp["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only read its own visitor passes")
    return ok(ser_pass(vp), 200)


@app.route("/visitor-passes", methods=["GET"])
def list_passes():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    items = list(DB["passes"].values())
    for key in ("household_id", "permit_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    if role == "Resident":
        items = [v for v in items if v["household_id"] == uid]
    return paginate(items, ser_pass)


@app.route("/visitor-passes/<pass_id>/cancel", methods=["POST"])
def cancel_pass(pass_id):
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    vp = get_or_404("passes", pass_id)
    if vp["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only cancel its own visitor passes")
    if vp["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Visitor pass is not ACTIVE")
    vp["status"] = "CANCELLED"
    touch(vp)
    return ok(ser_pass(vp), 200)


# ---- Waitlist ----
@app.route("/waitlist-entries/<entry_id>", methods=["GET"])
def get_waitlist(entry_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    w = get_or_404("waitlist", entry_id)
    if role == "Resident" and w["household_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Resident may only read its own waitlist entries")
    return ok(ser_waitlist(w), 200)


@app.route("/waitlist-entries", methods=["GET"])
def list_waitlist():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "Resident"})
    items = list(DB["waitlist"].values())
    for key in ("zone_id", "application_id", "household_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w[key] == val]
    if role == "Resident":
        items = [w for w in items if w["household_id"] == uid]
    return paginate(items, ser_waitlist)


# ---- Citations ----
@app.route("/citations", methods=["POST"])
def create_citation():
    uid, role = get_auth()
    require_roles(role, {"EnforcementOfficer"})
    body = get_body()
    require_fields(body, ["zone_id", "license_plate", "violation_type"])
    require_enum(body["violation_type"], {"NO_PERMIT", "EXPIRED_PERMIT", "ZONE_VIOLATION"}, "violation_type")
    zone = get_or_404("zones", body["zone_id"])
    permit_id = body.get("permit_id")
    if permit_id is not None:
        get_or_404("permits", permit_id)
    fine, variant, prior = citation_fine(zone["id"], body["license_plate"], body["violation_type"])
    c = base_entity()
    c.update({
        "zone_id": body["zone_id"],
        "permit_id": permit_id,
        "license_plate": body["license_plate"],
        "violation_type": body["violation_type"],
        "fine_amount_cents": fine,
        "fine_variant": variant,
        "prior_upheld_count": prior,
        "status": "ISSUED",
        "issuing_officer_id": uid,
        "adjudicator_id": None,
    })
    DB["citations"][c["id"]] = c
    return ok(ser_citation(c), 201)


@app.route("/citations/<citation_id>", methods=["GET"])
def get_citation(citation_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    c = get_or_404("citations", citation_id)
    return ok(ser_citation(c), 200)


@app.route("/citations", methods=["GET"])
def list_citations():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    items = list(DB["citations"].values())
    for key in ("zone_id", "permit_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return paginate(items, ser_citation)


@app.route("/citations/<citation_id>/pay", methods=["POST"])
def pay_citation(citation_id):
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    c = get_or_404("citations", citation_id)
    if c["status"] not in ("ISSUED", "UPHELD"):
        err("ERR_INVALID_STATE", 409, "Citation cannot be paid from its current state")
    c["status"] = "PAID"
    touch(c)
    return ok(ser_citation(c), 200)


@app.route("/citations/<citation_id>/dispute", methods=["POST"])
def dispute_citation(citation_id):
    uid, role = get_auth()
    require_roles(role, {"Resident"})
    c = get_or_404("citations", citation_id)
    if c["status"] != "ISSUED":
        err("ERR_INVALID_STATE", 409, "Citation is not ISSUED")
    c["status"] = "DISPUTED"
    touch(c)
    return ok(ser_citation(c), 200)


@app.route("/citations/<citation_id>/adjudicate", methods=["POST"])
def adjudicate_citation(citation_id):
    uid, role = get_auth()
    require_roles(role, {"EnforcementOfficer"})
    c = get_or_404("citations", citation_id)
    body = get_body()
    require_fields(body, ["outcome"])
    require_enum(body["outcome"], {"UPHELD", "DISMISSED"}, "outcome")
    if c["status"] != "DISPUTED":
        err("ERR_INVALID_STATE", 409, "Citation is not DISPUTED")
    if uid == c["issuing_officer_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Adjudicator must differ from issuing officer")
    c["adjudicator_id"] = uid
    if body["outcome"] == "DISMISSED":
        c["status"] = "DISMISSED"
        touch(c)
        return ok(ser_citation(c), 200)
    # UPHELD
    c["status"] = "UPHELD"
    touch(c)
    pid = c.get("permit_id")
    if pid:
        permit = DB["permits"].get(pid)
        if permit and permit_upheld_count(pid) >= REVOKE_UPHELD_THRESHOLD \
                and permit["status"] in ("ACTIVE", "SUSPENDED", "RENEWAL_PENDING"):
            _do_revoke(permit)
    return ok(ser_citation(c), 200)


# ---- Complaints ----
@app.route("/complaints", methods=["POST"])
def create_complaint():
    uid, role = get_auth()
    require_roles(role, {"Resident", "EnforcementOfficer"})
    body = get_body()
    require_fields(body, ["zone_id", "complaint_type", "description"])
    require_enum(body["complaint_type"], {"ILLEGAL_PARKING", "PERMIT_ABUSE", "SIGNAGE", "OTHER"}, "complaint_type")
    zone = get_or_404("zones", body["zone_id"])
    c = base_entity()
    c.update({
        "zone_id": body["zone_id"],
        "complaint_type": body["complaint_type"],
        "target_plate": body.get("target_plate"),
        "description": body["description"],
        "status": "OPEN",
        "resolution_note": None,
        "created_citation_id": None,
    })
    DB["complaints"][c["id"]] = c
    return ok(ser_complaint(c), 201)


@app.route("/complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    c = get_or_404("complaints", complaint_id)
    return ok(ser_complaint(c), 200)


@app.route("/complaints", methods=["GET"])
def list_complaints():
    uid, role = get_auth()
    require_roles(role, {"PermitSupervisor", "ParkingClerk", "EnforcementOfficer", "Resident"})
    items = list(DB["complaints"].values())
    for key in ("zone_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    return paginate(items, ser_complaint)


@app.route("/complaints/<complaint_id>/resolve", methods=["POST"])
def resolve_complaint(complaint_id):
    uid, role = get_auth()
    require_roles(role, {"EnforcementOfficer"})
    c = get_or_404("complaints", complaint_id)
    body = get_body()
    require_fields(body, ["outcome"])
    require_enum(body["outcome"], {"RESOLVED", "DISMISSED", "ESCALATED"}, "outcome")
    if c["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Complaint is not OPEN")
    outcome = body["outcome"]
    if outcome == "ESCALATED":
        if not c.get("target_plate"):
            err("ERR_ESCALATION_REQUIRES_PLATE", 422, "Escalation requires a target_plate")
        fine, variant, prior = citation_fine(c["zone_id"], c["target_plate"], "ZONE_VIOLATION")
        cit = base_entity()
        cit.update({
            "zone_id": c["zone_id"],
            "permit_id": None,
            "license_plate": c["target_plate"],
            "violation_type": "ZONE_VIOLATION",
            "fine_amount_cents": fine,
            "fine_variant": variant,
            "prior_upheld_count": prior,
            "status": "ISSUED",
            "issuing_officer_id": uid,
            "adjudicator_id": None,
        })
        DB["citations"][cit["id"]] = cit
        c["status"] = "ESCALATED"
        c["created_citation_id"] = cit["id"]
        c["resolution_note"] = body.get("resolution_note")
    else:
        c["status"] = outcome
        c["resolution_note"] = body.get("resolution_note")
    touch(c)
    return ok(ser_complaint(c), 200)


# ---------------------------------------------------------------------------
reset_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
