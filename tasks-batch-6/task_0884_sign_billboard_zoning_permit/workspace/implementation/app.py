"""Sign & Billboard Zoning Permit API — Python/Flask reference implementation.

In-memory only. Logical clock. Registers exactly 44 routes.
"""
import os
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Applicant", "Planner", "ZoningBoard", "Inspector"}

PERMIT_TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 30
RENEWAL_GRACE_DAYS = 30
CURE_PERIOD_DAYS = 30
REMOVAL_COMPLIANCE_DAYS = 15
REGISTRATION_TERM_DAYS = 365
INSPECTION_BUFFER_MINUTES = 60

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

ILLUM_RANK = {"NONE": 0, "EXTERNAL": 1, "DIGITAL_DISPLAY": 2}
ILLUM_SET = {"NONE", "EXTERNAL", "DIGITAL_DISPLAY"}
ZONING_SET = {"COMMERCIAL", "INDUSTRIAL", "RESIDENTIAL", "MIXED_USE"}
SIGN_TYPE_SET = {"WALL", "MONUMENT", "DIGITAL"}
VARIANCE_KIND_SET = {"AREA", "HEIGHT", "SETBACK", "HISTORIC", "ILLUMINATION"}
VIOLATION_KIND_SET = {"NO_PERMIT", "EXCEEDS_PERMIT", "ILLEGAL_ILLUMINATION", "ABANDONED"}

BASE_FEE_BY_TYPE = {"WALL": 15000, "MONUMENT": 25000, "DIGITAL": 50000}
AREA_INCLUDED_SQFT = Decimal("32")
AREA_TIER1_CAP_SQFT = Decimal("100")
AREA_TIER1_RATE_CENTS = Decimal("200")
AREA_TIER2_RATE_CENTS = Decimal("350")
ILLUMINATION_SURCHARGE = {"NONE": 0, "EXTERNAL": 5000, "DIGITAL_DISPLAY": 20000}

BASE_FACE_FEE_CENTS = Decimal("3333")
DIGITAL_FACE_MULTIPLIER = Decimal("1.5")
DECLINE_RATE = 0.20


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.parcels = {}
        self.applicants = {}
        self.inspectors = {}
        self.applications = {}
        self.variances = {}
        self.permits = {}
        self.inspections = {}
        self.ncrs = {}
        self.violations = {}
        self.removal_orders = {}
        self.billboards = {}
        self.leases = {}
        self.clock = DEFAULT_CLOCK
        self.seq = 0


db = DB()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def wall_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": wall_iso()}


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}}
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def parse_dt(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an ISO 8601 datetime")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, f"{field} is not a valid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def ok(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth / validation primitives
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or malformed auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return uid, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be a JSON object")
    return data


def v_str(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{field} is required")
        return None
    v = data[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a non-empty string")
    return v


def v_num(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{field} is required")
        return None
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a number")
    if v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be non-negative")
    return v


def v_int(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{field} is required")
        return None
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an integer")
    if v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be non-negative")
    return v


def v_enum(data, field, allowed, required=True):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"{field} is required")
        return None
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, f"{field} is not a valid enum value")
    return v


def v_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a boolean")
    return v


def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 422, "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 422, "offset must be non-negative")
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda r: (r["created_at"], r["seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pag = {"limit": limit, "offset": offset, "total_count": total,
           "has_more": offset + len(page) < total}
    return page, pag


# ---------------------------------------------------------------------------
# Entity bootstrap helpers
# ---------------------------------------------------------------------------
def make_versioned(rec):
    rec["id"] = new_id()
    rec["created_at"] = db.clock
    rec["updated_at"] = db.clock
    rec["version"] = 1
    rec["seq"] = next_seq()
    return rec


def make_light(rec):
    rec["id"] = new_id()
    rec["created_at"] = db.clock
    rec["seq"] = next_seq()
    return rec


def touch(rec):
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = db.clock


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def permit_fee(sign_type, area, illumination):
    base = BASE_FEE_BY_TYPE[sign_type]
    area = Decimal(str(area))
    billable = max(Decimal("0"), area - AREA_INCLUDED_SQFT)
    tier1 = min(billable, AREA_TIER1_CAP_SQFT - AREA_INCLUDED_SQFT)
    tier2 = max(Decimal("0"), area - AREA_TIER1_CAP_SQFT)
    area_fee = rhu(tier1 * AREA_TIER1_RATE_CENTS + tier2 * AREA_TIER2_RATE_CENTS)
    return base + area_fee + ILLUMINATION_SURCHARGE[illumination]


def registration_fee(is_digital, face_count):
    mult = DIGITAL_FACE_MULTIPLIER if is_digital else Decimal("1")
    per_face = rhu(BASE_FACE_FEE_CENTS * mult)
    return per_face * face_count


def ncr_valuation(ncr):
    now = db.clock
    elapsed_days = (now - ncr["registered_at"]).total_seconds() / 86400.0
    elapsed_years = elapsed_days / 365.0
    period = ncr["amortization_period_years"]
    ov = ncr["original_value_cents"]
    if period and period > 0:
        remaining = max(0.0, 1.0 - elapsed_years / period)
        straight = rhu(Decimal(str(ov)) * Decimal(str(remaining)))
        amortized = elapsed_years >= period
    else:
        straight = 0
        amortized = True
    declining = rhu(Decimal(str(ov * ((1.0 - DECLINE_RATE) ** elapsed_years))))
    status = "AMORTIZED" if amortized else "ACTIVE"
    return straight, declining, status


def parcel_counters(parcel_id):
    max_signs = db.parcels[parcel_id]["max_signs"]
    active = 0
    for p in db.permits.values():
        appn = db.applications.get(p["application_id"])
        if appn and appn["parcel_id"] == parcel_id and p["status"] == "ACTIVE":
            active += 1
    return active, max_signs - active


def granted_variance(application_id, kind):
    for v in db.variances.values():
        if (v["application_id"] == application_id and v["kind"] == kind
                and v["status"] == "GRANTED"):
            return v
    return None


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_parcel(pid):
    p = db.parcels.get(pid)
    if p is None:
        raise ApiError("ERR_PARCEL_NOT_FOUND", 404, "parcel not found")
    return p


def get_application(aid):
    a = db.applications.get(aid)
    if a is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "application not found")
    return a


def get_permit(pid):
    p = db.permits.get(pid)
    if p is None:
        raise ApiError("ERR_PERMIT_NOT_FOUND", 404, "permit not found")
    return p


def get_billboard(bid):
    b = db.billboards.get(bid)
    if b is None:
        raise ApiError("ERR_BILLBOARD_NOT_FOUND", 404, "billboard not found")
    return b


def get_generic(store, rid):
    r = store.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return r


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_parcel(p):
    active, avail = parcel_counters(p["id"])
    return {
        "id": p["id"], "created_at": iso(p["created_at"]),
        "zoning_district": p["zoning_district"],
        "historic_overlay": p["historic_overlay"],
        "corridor_overlay": p["corridor_overlay"],
        "max_sign_area_sqft": p["max_sign_area_sqft"],
        "max_height_ft": p["max_height_ft"],
        "min_setback_ft": p["min_setback_ft"],
        "allowed_illumination": p["allowed_illumination"],
        "max_signs": p["max_signs"],
        "active_permit_count": active,
        "available_sign_slots": avail,
    }


def ser_applicant(a):
    return {"id": a["id"], "created_at": iso(a["created_at"]),
            "name": a["name"], "contact_email": a["contact_email"]}


def ser_inspector(i):
    return {"id": i["id"], "created_at": iso(i["created_at"]), "name": i["name"]}


def _common(rec):
    return {"id": rec["id"], "created_at": iso(rec["created_at"]),
            "updated_at": iso(rec["updated_at"]), "version": rec["version"]}


def ser_application(a):
    d = _common(a)
    d.update({
        "parcel_id": a["parcel_id"], "applicant_id": a["applicant_id"],
        "sign_type": a["sign_type"],
        "requested_area_sqft": a["requested_area_sqft"],
        "requested_height_ft": a["requested_height_ft"],
        "requested_setback_ft": a["requested_setback_ft"],
        "requested_illumination": a["requested_illumination"],
        "provisional_fee_cents": a["provisional_fee_cents"],
        "approved_area_sqft": a["approved_area_sqft"],
        "approved_type": a["approved_type"],
        "approved_illumination": a["approved_illumination"],
        "status": a["status"],
        "dimensional_review": a["dimensional_review"],
        "overlay_review": a["overlay_review"],
    })
    return d


def ser_variance(v):
    d = _common(v)
    d.update({
        "application_id": v["application_id"], "kind": v["kind"],
        "requested_value": v["requested_value"], "justification": v["justification"],
        "recommendation": v["recommendation"],
        "recommended_by_user_id": v["recommended_by_user_id"],
        "decision": v["decision"], "decided_by_user_id": v["decided_by_user_id"],
        "granted_value": v["granted_value"], "status": v["status"],
    })
    return d


def ser_permit(p):
    d = _common(p)
    d.update({
        "application_id": p["application_id"],
        "fee_charged_cents": p["fee_charged_cents"], "fee_paid": p["fee_paid"],
        "fee_refunded_cents": p["fee_refunded_cents"],
        "issued_at": iso(p["issued_at"]), "activated_at": iso(p["activated_at"]),
        "expires_at": iso(p["expires_at"]), "status": p["status"],
    })
    return d


def ser_inspection(i):
    d = _common(i)
    d.update({
        "permit_id": i["permit_id"], "inspector_id": i["inspector_id"],
        "scheduled_start": iso(i["scheduled_start"]),
        "scheduled_end": iso(i["scheduled_end"]),
        "outcome": i["outcome"], "status": i["status"],
    })
    return d


def ser_ncr(n):
    straight, declining, status = ncr_valuation(n)
    d = _common(n)
    d.update({
        "parcel_id": n["parcel_id"], "description": n["description"],
        "original_value_cents": n["original_value_cents"],
        "amortization_period_years": n["amortization_period_years"],
        "registered_at": iso(n["registered_at"]),
        "straight_line_value_cents": straight,
        "declining_balance_value_cents": declining,
        "status": status,
    })
    return d


def ser_violation(v):
    d = _common(v)
    d.update({
        "parcel_id": v["parcel_id"], "permit_id": v["permit_id"], "kind": v["kind"],
        "issued_at": iso(v["issued_at"]), "cure_deadline": iso(v["cure_deadline"]),
        "status": v["status"],
    })
    return d


def ser_removal_order(r):
    return {
        "id": r["id"], "created_at": iso(r["created_at"]),
        "violation_id": r["violation_id"], "issued_at": iso(r["issued_at"]),
        "compliance_deadline": iso(r["compliance_deadline"]), "status": r["status"],
    }


def ser_billboard(b):
    d = _common(b)
    d.update({
        "parcel_id": b["parcel_id"], "operator_id": b["operator_id"],
        "face_count": b["face_count"], "is_digital": b["is_digital"],
        "structure_height_ft": b["structure_height_ft"],
        "registration_status": b["registration_status"],
        "registration_expires_at": iso(b["registration_expires_at"]),
        "registration_fee_collected_cents": b["registration_fee_collected_cents"],
    })
    return d


def ser_lease(l):
    d = _common(l)
    d.update({
        "billboard_id": l["billboard_id"], "lessee_name": l["lessee_name"],
        "start_date": iso(l["start_date"]), "end_date": iso(l["end_date"]),
        "status": l["status"],
    })
    return d


# ---------------------------------------------------------------------------
# Clock & sweeps
# ---------------------------------------------------------------------------
def run_sweep():
    now = db.clock
    for p in db.permits.values():
        if p["status"] == "ACTIVE" and p["expires_at"] and p["expires_at"] <= now:
            p["status"] = "EXPIRED"
            touch(p)
    for b in db.billboards.values():
        if (b["registration_status"] == "REGISTERED" and b["registration_expires_at"]
                and b["registration_expires_at"] <= now):
            b["registration_status"] = "LAPSED"
            touch(b)
            for l in db.leases.values():
                if l["billboard_id"] == b["id"] and l["status"] == "ACTIVE":
                    l["status"] = "SUSPENDED"
                    touch(l)
    for l in db.leases.values():
        if l["status"] == "ACTIVE" and l["end_date"] and l["end_date"] <= now:
            l["status"] = "EXPIRED"
            touch(l)
    for n in db.ncrs.values():
        if n["status"] == "ACTIVE":
            _, _, status = ncr_valuation(n)
            if status == "AMORTIZED":
                n["status"] = "AMORTIZED"
                touch(n)


@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth(["Planner"])
    data = body_json()
    target = data.get("to_iso8601")
    dt = parse_dt(target, "to_iso8601")
    db.clock = dt
    run_sweep()
    return ok({}, "object", 200)


# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------
@app.route("/parcels", methods=["POST"])
def create_parcel():
    auth(["Planner"])
    data = body_json()
    zoning = v_enum(data, "zoning_district", ZONING_SET)
    max_area = v_num(data, "max_sign_area_sqft")
    max_height = v_num(data, "max_height_ft")
    min_setback = v_num(data, "min_setback_ft")
    allowed_illum = v_enum(data, "allowed_illumination", ILLUM_SET)
    max_signs = v_int(data, "max_signs")
    historic = v_bool(data, "historic_overlay", False)
    corridor = v_bool(data, "corridor_overlay", False)
    p = make_light({
        "zoning_district": zoning, "max_sign_area_sqft": max_area,
        "max_height_ft": max_height, "min_setback_ft": min_setback,
        "allowed_illumination": allowed_illum, "max_signs": max_signs,
        "historic_overlay": historic, "corridor_overlay": corridor,
    })
    db.parcels[p["id"]] = p
    return ok(ser_parcel(p), "object", 201)


@app.route("/parcels/<pid>", methods=["GET"])
def read_parcel(pid):
    auth(ROLES)
    p = get_parcel(pid)
    return ok(ser_parcel(p), "object", 200)


# ---------------------------------------------------------------------------
# Applicants / Inspectors
# ---------------------------------------------------------------------------
@app.route("/applicants", methods=["POST"])
def create_applicant():
    auth(["Planner"])
    data = body_json()
    name = v_str(data, "name")
    email = v_str(data, "contact_email")
    a = make_light({"name": name, "contact_email": email})
    db.applicants[a["id"]] = a
    return ok(ser_applicant(a), "object", 201)


@app.route("/inspectors", methods=["POST"])
def create_inspector():
    auth(["Planner"])
    data = body_json()
    name = v_str(data, "name")
    i = make_light({"name": name})
    db.inspectors[i["id"]] = i
    return ok(ser_inspector(i), "object", 201)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@app.route("/applications", methods=["POST"])
def create_application():
    uid, role = auth(["Applicant"])
    data = body_json()
    applicant_id = data.get("applicant_id")
    parcel_id = data.get("parcel_id")
    # ownership (priority 2)
    if applicant_id is not None and applicant_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "applicant_id must equal X-User-ID")
    # existence (priority 3/4) for provided FKs
    if parcel_id is not None:
        get_parcel(parcel_id)
    if applicant_id is not None and applicant_id not in db.applicants:
        raise ApiError("ERR_NOT_FOUND", 404, "applicant not found")
    # body well-formedness (priority 5)
    parcel_id = v_str(data, "parcel_id")
    applicant_id = v_str(data, "applicant_id")
    sign_type = v_enum(data, "sign_type", SIGN_TYPE_SET)
    area = v_num(data, "requested_area_sqft")
    height = v_num(data, "requested_height_ft")
    setback = v_num(data, "requested_setback_ft")
    illum = v_enum(data, "requested_illumination", ILLUM_SET)
    a = make_versioned({
        "parcel_id": parcel_id, "applicant_id": applicant_id, "sign_type": sign_type,
        "requested_area_sqft": area, "requested_height_ft": height,
        "requested_setback_ft": setback, "requested_illumination": illum,
        "provisional_fee_cents": None, "approved_area_sqft": None,
        "approved_type": None, "approved_illumination": None,
        "status": "DRAFT", "dimensional_review": "PENDING", "overlay_review": "PENDING",
    })
    db.applications[a["id"]] = a
    return ok(ser_application(a), "object", 201)


@app.route("/applications/<aid>", methods=["GET"])
def read_application(aid):
    auth(ROLES)
    a = get_application(aid)
    return ok(ser_application(a), "object", 200)


@app.route("/applications", methods=["GET"])
def list_applications():
    auth(ROLES)
    items = list(db.applications.values())
    pid = request.args.get("parcel_id")
    aid = request.args.get("applicant_id")
    status = request.args.get("status")
    if pid is not None:
        items = [x for x in items if x["parcel_id"] == pid]
    if aid is not None:
        items = [x for x in items if x["applicant_id"] == aid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pag = paginate(items)
    return ok([ser_application(x) for x in page], "array", 200, pag)


@app.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    uid, role = auth(["Applicant"])
    a = get_application(aid)
    if a["applicant_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning applicant")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "application is not in DRAFT")
    a["provisional_fee_cents"] = permit_fee(
        a["sign_type"], a["requested_area_sqft"], a["requested_illumination"])
    a["dimensional_review"] = "PENDING"
    a["overlay_review"] = "PENDING"
    a["status"] = "SUBMITTED"
    touch(a)
    return ok(ser_application(a), "object", 200)


@app.route("/applications/<aid>/review", methods=["POST"])
def review_application(aid):
    auth(["Planner"])
    a = get_application(aid)
    data = body_json()
    review_type = v_enum(data, "review_type", {"DIMENSIONAL", "OVERLAY"})
    if review_type == "DIMENSIONAL":
        outcome = v_enum(data, "outcome", {"PASS", "FAIL"})
    else:
        outcome = v_enum(data, "outcome", {"CLEARED", "VARIANCE_REQUIRED"})
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "application not SUBMITTED")
    parcel = db.parcels[a["parcel_id"]]

    if review_type == "DIMENSIONAL":
        if outcome == "PASS":
            # effective area
            av = granted_variance(aid, "AREA")
            eff_area = av["granted_value"] if av else a["requested_area_sqft"]
            if eff_area > parcel["max_sign_area_sqft"]:
                raise ApiError("ERR_SIGN_AREA_EXCEEDED", 409, "effective area exceeds max")
            hv = granted_variance(aid, "HEIGHT")
            eff_height = hv["granted_value"] if hv else a["requested_height_ft"]
            if eff_height > parcel["max_height_ft"]:
                raise ApiError("ERR_SIGN_HEIGHT_EXCEEDED", 409, "effective height exceeds max")
            sv = granted_variance(aid, "SETBACK")
            setback_floor = sv["granted_value"] if sv else parcel["min_setback_ft"]
            if a["requested_setback_ft"] < setback_floor:
                raise ApiError("ERR_SETBACK_INSUFFICIENT", 409, "setback below floor")
            iv = granted_variance(aid, "ILLUMINATION")
            if not iv and ILLUM_RANK[a["requested_illumination"]] > ILLUM_RANK[parcel["allowed_illumination"]]:
                raise ApiError("ERR_ILLUMINATION_NOT_ALLOWED", 409, "illumination not allowed")
            a["dimensional_review"] = "PASS"
        else:
            a["dimensional_review"] = "FAIL"
    else:
        if outcome == "CLEARED":
            if parcel["historic_overlay"] and not granted_variance(aid, "HISTORIC"):
                raise ApiError("ERR_HISTORIC_OVERLAY_REVIEW_REQUIRED", 409,
                               "historic overlay requires granted HISTORIC variance")
            a["overlay_review"] = "CLEARED"
        else:
            a["overlay_review"] = "VARIANCE_REQUIRED"
    touch(a)
    return ok(ser_application(a), "object", 200)


@app.route("/applications/<aid>/decide", methods=["POST"])
def decide_application(aid):
    auth(["Planner"])
    a = get_application(aid)
    data = body_json()
    decision = v_enum(data, "decision", {"APPROVE", "DENY"})
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "application not SUBMITTED")
    if decision == "APPROVE":
        if not (a["dimensional_review"] == "PASS"
                and a["overlay_review"] in ("CLEARED", "VARIANCE_GRANTED")):
            raise ApiError("ERR_INVALID_STATE", 409, "reviews not complete for approval")
        av = granted_variance(aid, "AREA")
        if av and av["granted_value"] is not None:
            a["approved_area_sqft"] = min(a["requested_area_sqft"], av["granted_value"])
        else:
            a["approved_area_sqft"] = a["requested_area_sqft"]
        a["approved_type"] = a["sign_type"]
        a["approved_illumination"] = a["requested_illumination"]
        a["status"] = "APPROVED"
    else:
        a["status"] = "DENIED"
    touch(a)
    return ok(ser_application(a), "object", 200)


# ---------------------------------------------------------------------------
# Variances
# ---------------------------------------------------------------------------
@app.route("/variances", methods=["POST"])
def create_variance():
    uid, role = auth(["Applicant"])
    data = body_json()
    application_id = data.get("application_id")
    if application_id is not None:
        appn = get_application(application_id)
        if appn["applicant_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning applicant")
    application_id = v_str(data, "application_id")
    if application_id not in db.applications:
        get_application(application_id)
    kind = v_enum(data, "kind", VARIANCE_KIND_SET)
    justification = v_str(data, "justification")
    requested_value = v_num(data, "requested_value", required=False)
    v = make_versioned({
        "application_id": application_id, "kind": kind,
        "requested_value": requested_value, "justification": justification,
        "recommendation": None, "recommended_by_user_id": None,
        "decision": None, "decided_by_user_id": None, "granted_value": None,
        "status": "SUBMITTED",
    })
    db.variances[v["id"]] = v
    return ok(ser_variance(v), "object", 201)


@app.route("/variances/<vid>", methods=["GET"])
def read_variance(vid):
    auth(ROLES)
    v = get_generic(db.variances, vid)
    return ok(ser_variance(v), "object", 200)


@app.route("/variances", methods=["GET"])
def list_variances():
    auth(ROLES)
    items = list(db.variances.values())
    aid = request.args.get("application_id")
    status = request.args.get("status")
    if aid is not None:
        items = [x for x in items if x["application_id"] == aid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pag = paginate(items)
    return ok([ser_variance(x) for x in page], "array", 200, pag)


@app.route("/variances/<vid>/recommend", methods=["POST"])
def recommend_variance(vid):
    uid, role = auth(["Planner"])
    v = get_generic(db.variances, vid)
    data = body_json()
    recommendation = v_enum(data, "recommendation", {"RECOMMEND_APPROVE", "RECOMMEND_DENY"})
    if v["status"] not in ("SUBMITTED", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "variance not open for recommendation")
    v["recommendation"] = recommendation
    v["recommended_by_user_id"] = uid
    v["status"] = "UNDER_REVIEW"
    touch(v)
    return ok(ser_variance(v), "object", 200)


@app.route("/variances/<vid>/decide", methods=["POST"])
def decide_variance(vid):
    uid, role = auth(["ZoningBoard"])
    v = get_generic(db.variances, vid)
    data = body_json()
    decision = v_enum(data, "decision", {"GRANT", "DENY", "REVISE"})
    granted_value = v_num(data, "granted_value", required=False)
    if v["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "variance not UNDER_REVIEW")
    if uid == v["recommended_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "decider must differ from recommender")
    v["decision"] = decision
    v["decided_by_user_id"] = uid
    if decision == "GRANT":
        v["granted_value"] = granted_value if granted_value is not None else v["requested_value"]
        v["status"] = "GRANTED"
        appn = db.applications.get(v["application_id"])
        if appn:
            if v["kind"] in ("HISTORIC", "ILLUMINATION"):
                appn["overlay_review"] = "VARIANCE_GRANTED"
            touch(appn)
    elif decision == "DENY":
        v["status"] = "DENIED"
    else:
        v["status"] = "REVISION_REQUESTED"
    touch(v)
    return ok(ser_variance(v), "object", 200)


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------
@app.route("/permits", methods=["POST"])
def issue_permit():
    auth(["Planner"])
    data = body_json()
    application_id = data.get("application_id")
    if application_id is not None:
        appn = get_application(application_id)
    application_id = v_str(data, "application_id")
    appn = get_application(application_id)
    expected_version = v_int(data, "expected_application_version")
    # referential state (priority 7)
    if appn["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_NOT_APPROVED", 409, "application not APPROVED")
    # OCC (priority 13)
    if expected_version != appn["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "application version is stale")
    fee = permit_fee(appn["approved_type"], appn["approved_area_sqft"],
                     appn["approved_illumination"])
    p = make_versioned({
        "application_id": application_id, "fee_charged_cents": fee,
        "fee_paid": False, "fee_refunded_cents": 0,
        "issued_at": db.clock, "activated_at": None, "expires_at": None,
        "status": "ISSUED",
    })
    db.permits[p["id"]] = p
    appn["status"] = "PERMITTED"
    touch(appn)
    return ok(ser_permit(p), "object", 201)


@app.route("/permits/<pid>", methods=["GET"])
def read_permit(pid):
    auth(ROLES)
    p = get_permit(pid)
    return ok(ser_permit(p), "object", 200)


@app.route("/permits", methods=["GET"])
def list_permits():
    auth(ROLES)
    items = list(db.permits.values())
    aid = request.args.get("application_id")
    status = request.args.get("status")
    if aid is not None:
        items = [x for x in items if x["application_id"] == aid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pag = paginate(items)
    return ok([ser_permit(x) for x in page], "array", 200, pag)


def _permit_owner(p):
    appn = db.applications.get(p["application_id"])
    return appn["applicant_id"] if appn else None


@app.route("/permits/<pid>/pay", methods=["POST"])
def pay_permit(pid):
    uid, role = auth(["Applicant"])
    p = get_permit(pid)
    if _permit_owner(p) != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning applicant")
    data = body_json()
    amount = v_int(data, "amount_cents")
    if p["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "permit not ISSUED")
    if amount < p["fee_charged_cents"]:
        raise ApiError("ERR_FEE_NOT_PAID", 402, "amount does not cover fee")
    appn = db.applications[p["application_id"]]
    _, avail = parcel_counters(appn["parcel_id"])
    if avail <= 0:
        raise ApiError("ERR_SIGN_SLOTS_EXHAUSTED", 409, "no available sign slots")
    p["fee_paid"] = True
    p["status"] = "ACTIVE"
    p["activated_at"] = db.clock
    p["expires_at"] = db.clock + timedelta(days=PERMIT_TERM_DAYS)
    touch(p)
    return ok(ser_permit(p), "object", 200)


@app.route("/permits/<pid>/renew", methods=["POST"])
def renew_permit(pid):
    uid, role = auth(["Applicant"])
    p = get_permit(pid)
    if _permit_owner(p) != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning applicant")
    if p["status"] not in ("ACTIVE", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE", 409, "permit not ACTIVE/EXPIRED")
    if not p["fee_paid"]:
        raise ApiError("ERR_INVALID_STATE", 409, "permit fee not paid")
    now = db.clock
    window_open = p["expires_at"] - timedelta(days=RENEWAL_WINDOW_DAYS)
    window_close = p["expires_at"] + timedelta(days=RENEWAL_GRACE_DAYS)
    if now < window_open or now > window_close:
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", 409, "outside renewal window")
    p["expires_at"] = p["expires_at"] + timedelta(days=PERMIT_TERM_DAYS)
    if p["status"] == "EXPIRED":
        p["status"] = "ACTIVE"
    touch(p)
    return ok(ser_permit(p), "object", 200)


@app.route("/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    auth(["Planner"])
    p = get_permit(pid)
    if p["status"] not in ("ISSUED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "permit not ISSUED/ACTIVE")
    p["status"] = "REVOKED"
    p["fee_refunded_cents"] = p["fee_charged_cents"]
    for ins in db.inspections.values():
        if ins["permit_id"] == pid and ins["status"] == "SCHEDULED":
            ins["status"] = "CANCELLED"
            touch(ins)
    touch(p)
    return ok(ser_permit(p), "object", 200)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------
@app.route("/inspections", methods=["POST"])
def create_inspection():
    auth(["Planner"])
    data = body_json()
    permit_id = data.get("permit_id")
    inspector_id = data.get("inspector_id")
    if permit_id is not None:
        get_permit(permit_id)
    if inspector_id is not None and inspector_id not in db.inspectors:
        raise ApiError("ERR_NOT_FOUND", 404, "inspector not found")
    permit_id = v_str(data, "permit_id")
    inspector_id = v_str(data, "inspector_id")
    if inspector_id not in db.inspectors:
        raise ApiError("ERR_NOT_FOUND", 404, "inspector not found")
    start = parse_dt(data.get("scheduled_start"), "scheduled_start")
    end = parse_dt(data.get("scheduled_end"), "scheduled_end")
    permit = get_permit(permit_id)
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_INACTIVE", 409, "permit not ACTIVE")
    buf = timedelta(minutes=INSPECTION_BUFFER_MINUTES)
    for ins in db.inspections.values():
        if ins["inspector_id"] == inspector_id and ins["status"] == "SCHEDULED":
            if start < ins["scheduled_end"] + buf and end > ins["scheduled_start"] - buf:
                raise ApiError("ERR_INSPECTION_OVERLAP", 409, "inspector schedule conflict")
    i = make_versioned({
        "permit_id": permit_id, "inspector_id": inspector_id,
        "scheduled_start": start, "scheduled_end": end,
        "outcome": None, "status": "SCHEDULED",
    })
    db.inspections[i["id"]] = i
    return ok(ser_inspection(i), "object", 201)


@app.route("/inspections/<iid>", methods=["GET"])
def read_inspection(iid):
    auth(ROLES)
    i = get_generic(db.inspections, iid)
    return ok(ser_inspection(i), "object", 200)


@app.route("/inspections", methods=["GET"])
def list_inspections():
    auth(ROLES)
    items = list(db.inspections.values())
    pid = request.args.get("permit_id")
    insp = request.args.get("inspector_id")
    status = request.args.get("status")
    if pid is not None:
        items = [x for x in items if x["permit_id"] == pid]
    if insp is not None:
        items = [x for x in items if x["inspector_id"] == insp]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pag = paginate(items)
    return ok([ser_inspection(x) for x in page], "array", 200, pag)


@app.route("/inspections/<iid>/record", methods=["POST"])
def record_inspection(iid):
    uid, role = auth(["Inspector"])
    i = get_generic(db.inspections, iid)
    if i["inspector_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the assigned inspector")
    data = body_json()
    outcome = v_enum(data, "outcome", {"PASS", "FAIL"})
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "inspection not SCHEDULED")
    i["outcome"] = outcome
    i["status"] = "PASSED" if outcome == "PASS" else "FAILED"
    touch(i)
    return ok(ser_inspection(i), "object", 200)


# ---------------------------------------------------------------------------
# Non-conforming registrations
# ---------------------------------------------------------------------------
@app.route("/non-conforming", methods=["POST"])
def create_ncr():
    auth(["Planner"])
    data = body_json()
    parcel_id = data.get("parcel_id")
    if parcel_id is not None:
        get_parcel(parcel_id)
    parcel_id = v_str(data, "parcel_id")
    get_parcel(parcel_id)
    description = v_str(data, "description")
    original_value = v_int(data, "original_value_cents")
    period = v_int(data, "amortization_period_years")
    n = make_versioned({
        "parcel_id": parcel_id, "description": description,
        "original_value_cents": original_value,
        "amortization_period_years": period,
        "registered_at": db.clock, "status": "ACTIVE",
    })
    db.ncrs[n["id"]] = n
    return ok(ser_ncr(n), "object", 201)


@app.route("/non-conforming/<nid>", methods=["GET"])
def read_ncr(nid):
    auth(ROLES)
    n = get_generic(db.ncrs, nid)
    return ok(ser_ncr(n), "object", 200)


@app.route("/non-conforming", methods=["GET"])
def list_ncr():
    auth(ROLES)
    items = list(db.ncrs.values())
    pid = request.args.get("parcel_id")
    status = request.args.get("status")
    if pid is not None:
        items = [x for x in items if x["parcel_id"] == pid]
    if status is not None:
        items = [x for x in items if ncr_valuation(x)[2] == status]
    page, pag = paginate(items)
    return ok([ser_ncr(x) for x in page], "array", 200, pag)


# ---------------------------------------------------------------------------
# Violations
# ---------------------------------------------------------------------------
@app.route("/violations", methods=["POST"])
def create_violation():
    auth(["Planner"])
    data = body_json()
    parcel_id = data.get("parcel_id")
    permit_id = data.get("permit_id")
    if parcel_id is not None:
        get_parcel(parcel_id)
    if permit_id is not None:
        get_permit(permit_id)
    parcel_id = v_str(data, "parcel_id")
    get_parcel(parcel_id)
    kind = v_enum(data, "kind", VIOLATION_KIND_SET)
    permit_id = v_str(data, "permit_id", required=False)
    v = make_versioned({
        "parcel_id": parcel_id, "permit_id": permit_id, "kind": kind,
        "issued_at": db.clock,
        "cure_deadline": db.clock + timedelta(days=CURE_PERIOD_DAYS),
        "status": "OPEN",
    })
    db.violations[v["id"]] = v
    return ok(ser_violation(v), "object", 201)


@app.route("/violations/<vid>", methods=["GET"])
def read_violation(vid):
    auth(ROLES)
    v = get_generic(db.violations, vid)
    return ok(ser_violation(v), "object", 200)


@app.route("/violations", methods=["GET"])
def list_violations():
    auth(ROLES)
    items = list(db.violations.values())
    pid = request.args.get("parcel_id")
    permit_id = request.args.get("permit_id")
    status = request.args.get("status")
    if pid is not None:
        items = [x for x in items if x["parcel_id"] == pid]
    if permit_id is not None:
        items = [x for x in items if x["permit_id"] == permit_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pag = paginate(items)
    return ok([ser_violation(x) for x in page], "array", 200, pag)


@app.route("/violations/<vid>/cure", methods=["POST"])
def cure_violation(vid):
    auth(["Planner"])
    v = get_generic(db.violations, vid)
    if v["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "violation not OPEN")
    if db.clock > v["cure_deadline"]:
        raise ApiError("ERR_INVALID_STATE", 409, "cure period has passed")
    v["status"] = "CURED"
    touch(v)
    return ok(ser_violation(v), "object", 200)


@app.route("/violations/<vid>/escalate", methods=["POST"])
def escalate_violation(vid):
    auth(["Planner"])
    v = get_generic(db.violations, vid)
    if v["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "violation not OPEN")
    if db.clock <= v["cure_deadline"]:
        raise ApiError("ERR_CURE_PERIOD_ACTIVE", 409, "cure period still active")
    v["status"] = "ESCALATED"
    ro = make_light({
        "violation_id": v["id"], "issued_at": db.clock,
        "compliance_deadline": db.clock + timedelta(days=REMOVAL_COMPLIANCE_DAYS),
        "status": "ISSUED",
    })
    db.removal_orders[ro["id"]] = ro
    if v["permit_id"]:
        p = db.permits.get(v["permit_id"])
        if p and p["status"] in ("ISSUED", "ACTIVE"):
            p["status"] = "REVOKED"
            p["fee_refunded_cents"] = p["fee_charged_cents"]
            for ins in db.inspections.values():
                if ins["permit_id"] == p["id"] and ins["status"] == "SCHEDULED":
                    ins["status"] = "CANCELLED"
                    touch(ins)
            touch(p)
    touch(v)
    return ok(ser_violation(v), "object", 200)


# ---------------------------------------------------------------------------
# Removal orders
# ---------------------------------------------------------------------------
@app.route("/removal-orders/<rid>", methods=["GET"])
def read_removal_order(rid):
    auth(ROLES)
    r = get_generic(db.removal_orders, rid)
    return ok(ser_removal_order(r), "object", 200)


@app.route("/removal-orders", methods=["GET"])
def list_removal_orders():
    auth(ROLES)
    items = list(db.removal_orders.values())
    vid = request.args.get("violation_id")
    if vid is not None:
        items = [x for x in items if x["violation_id"] == vid]
    page, pag = paginate(items)
    return ok([ser_removal_order(x) for x in page], "array", 200, pag)


# ---------------------------------------------------------------------------
# Billboards
# ---------------------------------------------------------------------------
@app.route("/billboards", methods=["POST"])
def create_billboard():
    uid, role = auth(["Applicant"])
    data = body_json()
    operator_id = data.get("operator_id")
    parcel_id = data.get("parcel_id")
    if operator_id is not None and operator_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "operator_id must equal X-User-ID")
    if parcel_id is not None:
        get_parcel(parcel_id)
    if operator_id is not None and operator_id not in db.applicants:
        raise ApiError("ERR_NOT_FOUND", 404, "operator not found")
    parcel_id = v_str(data, "parcel_id")
    operator_id = v_str(data, "operator_id")
    face_count = v_int(data, "face_count")
    is_digital = v_bool(data, "is_digital", False)
    height = v_num(data, "structure_height_ft")
    b = make_versioned({
        "parcel_id": parcel_id, "operator_id": operator_id,
        "face_count": face_count, "is_digital": is_digital,
        "structure_height_ft": height, "registration_status": "UNREGISTERED",
        "registration_expires_at": None, "registration_fee_collected_cents": 0,
    })
    db.billboards[b["id"]] = b
    return ok(ser_billboard(b), "object", 201)


@app.route("/billboards/<bid>", methods=["GET"])
def read_billboard(bid):
    auth(ROLES)
    b = get_billboard(bid)
    return ok(ser_billboard(b), "object", 200)


@app.route("/billboards", methods=["GET"])
def list_billboards():
    auth(ROLES)
    items = list(db.billboards.values())
    pid = request.args.get("parcel_id")
    op = request.args.get("operator_id")
    status = request.args.get("registration_status")
    if pid is not None:
        items = [x for x in items if x["parcel_id"] == pid]
    if op is not None:
        items = [x for x in items if x["operator_id"] == op]
    if status is not None:
        items = [x for x in items if x["registration_status"] == status]
    page, pag = paginate(items)
    return ok([ser_billboard(x) for x in page], "array", 200, pag)


@app.route("/billboards/<bid>/register", methods=["POST"])
def register_billboard(bid):
    uid, role = auth(["Applicant"])
    b = get_billboard(bid)
    if b["operator_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning operator")
    data = body_json()
    amount = v_int(data, "amount_cents")
    fee = registration_fee(b["is_digital"], b["face_count"])
    now = db.clock
    if b["registration_status"] == "REGISTERED":
        # renewal — window must be open (priority 10)
        window_open = b["registration_expires_at"] - timedelta(days=RENEWAL_WINDOW_DAYS)
        if now < window_open:
            raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", 409, "outside renewal window")
        if amount < fee:
            raise ApiError("ERR_FEE_NOT_PAID", 402, "amount does not cover fee")
        b["registration_expires_at"] = b["registration_expires_at"] + timedelta(days=REGISTRATION_TERM_DAYS)
    else:
        # fresh register from UNREGISTERED or LAPSED
        if amount < fee:
            raise ApiError("ERR_FEE_NOT_PAID", 402, "amount does not cover fee")
        b["registration_status"] = "REGISTERED"
        b["registration_expires_at"] = now + timedelta(days=REGISTRATION_TERM_DAYS)
    b["registration_fee_collected_cents"] += fee
    touch(b)
    return ok(ser_billboard(b), "object", 200)


# ---------------------------------------------------------------------------
# Billboard leases
# ---------------------------------------------------------------------------
@app.route("/billboard-leases", methods=["POST"])
def create_lease():
    uid, role = auth(["Applicant"])
    data = body_json()
    billboard_id = data.get("billboard_id")
    if billboard_id is not None:
        b = get_billboard(billboard_id)
        if b["operator_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning operator")
    billboard_id = v_str(data, "billboard_id")
    b = get_billboard(billboard_id)
    lessee_name = v_str(data, "lessee_name")
    start = parse_dt(data.get("start_date"), "start_date")
    end = parse_dt(data.get("end_date"), "end_date")
    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL", 422, "end_date must be after start_date")
    expected_version = v_int(data, "expected_billboard_version")
    # referential state (priority 7)
    if b["registration_status"] != "REGISTERED":
        raise ApiError("ERR_BILLBOARD_NOT_REGISTERED", 409, "billboard not REGISTERED")
    # overlap (priority 9)
    for l in db.leases.values():
        if l["billboard_id"] == billboard_id and l["status"] not in ("TERMINATED", "EXPIRED"):
            if start < l["end_date"] and l["start_date"] < end:
                raise ApiError("ERR_LEASE_OVERLAP", 409, "lease interval overlap")
    # OCC (priority 13)
    if expected_version != b["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "billboard version is stale")
    l = make_versioned({
        "billboard_id": billboard_id, "lessee_name": lessee_name,
        "start_date": start, "end_date": end, "status": "ACTIVE",
    })
    db.leases[l["id"]] = l
    touch(b)
    return ok(ser_lease(l), "object", 201)


@app.route("/billboard-leases/<lid>", methods=["GET"])
def read_lease(lid):
    auth(ROLES)
    l = get_generic(db.leases, lid)
    return ok(ser_lease(l), "object", 200)


@app.route("/billboard-leases", methods=["GET"])
def list_leases():
    auth(ROLES)
    items = list(db.leases.values())
    bid = request.args.get("billboard_id")
    status = request.args.get("status")
    if bid is not None:
        items = [x for x in items if x["billboard_id"] == bid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, pag = paginate(items)
    return ok([ser_lease(x) for x in page], "array", 200, pag)


@app.route("/billboard-leases/<lid>/terminate", methods=["POST"])
def terminate_lease(lid):
    uid, role = auth(["Applicant"])
    l = get_generic(db.leases, lid)
    b = db.billboards.get(l["billboard_id"])
    if not b or b["operator_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning operator")
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "lease not ACTIVE")
    l["status"] = "TERMINATED"
    touch(l)
    return ok(ser_lease(l), "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
