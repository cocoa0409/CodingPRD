"""
Air Quality Permit & Emissions Inventory API.

In-memory Flask implementation. All state lives in module-level dicts and is
wiped on every fresh process start (the test harness re-launches start.sh before
every test). No seeding: every entity is created through the API.
"""

import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
FACILITIES = {}
SOURCES = {}
PERMITS = {}
NOTICES = {}
INVENTORIES = {}
LINE_ITEMS = {}
STACK_TESTS = {}
CEM_BLOCKS = {}
EXCEEDANCES = {}
COMPLAINTS = {}
INSPECTIONS = {}
ENFORCEMENTS = {}

_SEQ = 0

# Logical clock — startup default per PRD 2.6
CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

RECOGNIZED_ROLES = {
    "FacilityOperator", "PermitReviewer", "Inspector",
    "EnforcementOfficer", "Anonymous",
}
FOUR = ("FacilityOperator", "PermitReviewer", "Inspector", "EnforcementOfficer")
AGENCY3 = ("PermitReviewer", "Inspector", "EnforcementOfficer")

# Calculation constants
LBS_PER_TON = 2000
TITLE_V_PTE_THRESHOLD_TPY = 100
TIER1_RATE_CENTS = 4500
TIER2_RATE_CENTS = 4000
TIER3_RATE_CENTS = 3500
MIN_FEE_CENTS = 50000
SMALL_EMITTER_CEILING_CENTS = 100000
SMALL_EMITTER_DISCOUNT = Decimal("0.10")
LATE_SURCHARGE_PCT = Decimal("0.15")
BASE_PENALTY_CENTS = 250000
DAILY_ESCALATION_CENTS = 50000
PENALTY_CAP_CENTS = 2500000
REPORT_DEADLINE_HOURS = 72
STACK_TEST_BUFFER_DAYS = 7


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Helpers: time / ids / sequence
# ---------------------------------------------------------------------------
def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_dt(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def rhu(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def rhu_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def new_entity(**fields):
    e = {
        "id": new_id(),
        "created_at": CLOCK,
        "updated_at": CLOCK,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(e):
    e["updated_at"] = CLOCK
    e["version"] += 1


def serialize(e):
    out = {}
    for k, v in e.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": req_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def success(data, code=200, is_array=False, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(*allowed):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized role")
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")
    return uid, role


def body_json():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return b


# ---------------------------------------------------------------------------
# Body validation helpers (ERR_INVALID_REQUEST is priority 18 / lowest)
# ---------------------------------------------------------------------------
def v_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", 400, "Missing or empty field: %s" % key)
    return v


def v_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", 400, "Invalid value for %s" % key)
    return v


def v_num(body, key, cond=None, condmsg=""):
    v = body.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, "Missing or invalid number: %s" % key)
    if cond is not None and not cond(v):
        raise err("ERR_INVALID_REQUEST", 400, "Out of range: %s %s" % (key, condmsg))
    return v


def v_int(body, key, lo, hi):
    v = body.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, "Missing or invalid integer: %s" % key)
    if v < lo or v > hi:
        raise err("ERR_INVALID_REQUEST", 400, "Out of range integer: %s" % key)
    return v


def v_dt(body, key):
    v = body.get(key)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 400, "Missing datetime: %s" % key)
    try:
        return parse_dt(v)
    except Exception:
        raise err("ERR_INVALID_REQUEST", 400, "Malformed datetime: %s" % key)


def get_or_404(store, rid):
    if rid is None:
        raise err("ERR_NOT_FOUND", 404, "Resource not found")
    e = store.get(rid)
    if e is None:
        raise err("ERR_NOT_FOUND", 404, "Resource not found")
    return e


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def _pag_int(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def paginate(items):
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    limit = _pag_int("limit", 10, 1, 100)
    offset = _pag_int("offset", 0, 0, None)
    page = items[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return [serialize(e) for e in page], meta_extra


def list_response(items):
    data, meta_extra = paginate(items)
    return success(data, 200, is_array=True, meta_extra=meta_extra)


# ---------------------------------------------------------------------------
# Domain calculations
# ---------------------------------------------------------------------------
def recompute_facility_pte(f):
    total = Decimal("0")
    for s in SOURCES.values():
        if s["facility_id"] == f["id"] and s["lifecycle_status"] != "SHUTDOWN":
            total += Decimal(str(s["uncontrolled_pte_tpy"]))
    pte = float(total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    f["potential_to_emit_tpy"] = pte
    if pte >= TITLE_V_PTE_THRESHOLD_TPY:
        f["permit_track"] = "TITLE_V"
    elif pte > 0:
        f["permit_track"] = "PERMIT_BY_RULE"
    else:
        f["permit_track"] = "UNPERMITTED"


def facility_source_ids(facility_id):
    return {s["id"] for s in SOURCES.values() if s["facility_id"] == facility_id}


def facility_exceedances(facility_id):
    sids = facility_source_ids(facility_id)
    return [e for e in EXCEEDANCES.values() if e["source_id"] in sids]


def facility_enforcements(facility_id):
    return [a for a in ENFORCEMENTS.values() if a["facility_id"] == facility_id]


def derive_compliance(facility_id):
    actions = facility_enforcements(facility_id)
    if any(a["status"] == "PENALTY_ASSESSED" for a in actions):
        return "SUSPENDED"
    if any(a["status"] in ("INITIATED", "PAID") for a in actions):
        return "ENFORCEMENT"
    if any(e["status"] in ("OPEN", "REPORTED_LATE") for e in facility_exceedances(facility_id)):
        return "DEVIATION"
    return "COMPLIANT"


def reconcile_facility(f):
    """Recompute derived posture fields in place. Returns True if anything changed."""
    new_count = sum(
        1 for e in facility_exceedances(f["id"])
        if e["status"] in ("OPEN", "REPORTED_LATE")
    )
    new_status = derive_compliance(f["id"])
    if new_count != f["open_exceedance_count"] or new_status != f["compliance_status"]:
        f["open_exceedance_count"] = new_count
        f["compliance_status"] = new_status
        return True
    return False


def compute_source_pte(max_rate, hours, control_eff):
    uncontrolled = rhu(max_rate * hours / LBS_PER_TON, 3)
    controlled = rhu(uncontrolled * (1 - control_eff), 3)
    return uncontrolled, controlled


def inventory_total(inventory_id):
    s = Decimal("0")
    for li in LINE_ITEMS.values():
        if li["inventory_id"] == inventory_id:
            s += Decimal(str(li["reported_tons"]))
    return float(s.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def emissions_fee(total_tons, variant, certified_at=None, due_at=None):
    t = Decimal(str(total_tons))
    gross = Decimal("0")
    gross += min(t, Decimal(25)) * TIER1_RATE_CENTS
    if t > 25:
        gross += (min(t, Decimal(100)) - Decimal(25)) * TIER2_RATE_CENTS
    if t > 100:
        gross += (t - Decimal(100)) * TIER3_RATE_CENTS
    cents = int(gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    cents = max(cents, MIN_FEE_CENTS)
    if cents < SMALL_EMITTER_CEILING_CENTS:
        cents = int((Decimal(cents) * (Decimal("1") - SMALL_EMITTER_DISCOUNT)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    if variant == "assessed" and certified_at is not None and due_at is not None:
        if certified_at >= due_at:
            cents = int((Decimal(cents) * (Decimal("1") + LATE_SURCHARGE_PCT)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
    return cents


def governing_exceedance(facility_id):
    evs = [e for e in facility_exceedances(facility_id)
           if e["status"] in ("OPEN", "REPORTED_LATE")]
    if not evs:
        return None
    evs.sort(key=lambda e: (e["detected_at"], e["_seq"]))
    return evs[-1]


def compute_penalty(action):
    sev = 1
    days_late = 0
    if action["origin"] == "LATE_EXCEEDANCE":
        ge = governing_exceedance(action["facility_id"])
        if ge is not None:
            m = ge.get("magnitude_pct") or 0
            if m > 10:
                sev = 2
            if m > 50:
                sev = 3
            if ge.get("reported_at") is not None and ge.get("detected_at") is not None:
                delta = ge["reported_at"] - ge["detected_at"]
                days_late = int(delta.total_seconds() // 86400)
                if days_late < 0:
                    days_late = 0
    penalty = BASE_PENALTY_CENTS * sev + DAILY_ESCALATION_CENTS * days_late
    return min(penalty, PENALTY_CAP_CENTS)


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------
def require_owner(uid, role, facility_id):
    if role == "FacilityOperator" and uid != facility_id:
        raise err("ERR_NOT_FACILITY_OWNER", 403, "Not the owning facility")


def occ_check(f, body):
    """Priority 17: expected_facility_version must equal facility.version.
    Present-and-wrong -> 412. Missing/invalid falls through to body validation (400)."""
    efv = body.get("expected_facility_version")
    if isinstance(efv, int) and not isinstance(efv, bool):
        if efv != f["version"]:
            raise err("ERR_STALE_FACILITY_VERSION", 412, "Stale facility version")


# ===========================================================================
# FACILITIES
# ===========================================================================
@app.route("/facilities", methods=["POST"])
def create_facility():
    auth("FacilityOperator")
    body = body_json()
    name = v_str(body, "name")
    operator_name = v_str(body, "operator_name")
    county = v_str(body, "county")
    f = new_entity(
        name=name,
        operator_name=operator_name,
        county=county,
        permit_track="UNPERMITTED",
        potential_to_emit_tpy=0.0,
        compliance_status="COMPLIANT",
        open_exceedance_count=0,
        fee_balance_cents=0,
    )
    FACILITIES[f["id"]] = f
    return success(serialize(f), 201)


@app.route("/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    auth(*FOUR)
    f = get_or_404(FACILITIES, fid)
    return success(serialize(f), 200)


@app.route("/facilities", methods=["GET"])
def list_facilities():
    auth(*AGENCY3)
    county = request.args.get("county")
    cstatus = request.args.get("compliance_status")
    items = list(FACILITIES.values())
    if county is not None:
        items = [f for f in items if f["county"] == county]
    if cstatus is not None:
        items = [f for f in items if f["compliance_status"] == cstatus]
    return list_response(items)


# ===========================================================================
# SOURCES
# ===========================================================================
@app.route("/sources", methods=["POST"])
def create_source():
    uid, role = auth("FacilityOperator")
    body = body_json()
    fid = body.get("facility_id")
    # priority 3: ownership (compares header to claimed facility_id)
    if fid is not None:
        require_owner(uid, role, fid)
    # priority 4: existence
    if fid is not None:
        f = get_or_404(FACILITIES, fid)
    else:
        f = None
    # priority 17: OCC
    if f is not None:
        occ_check(f, body)
    # priority 18: body validation
    fid = v_str(body, "facility_id")
    f = get_or_404(FACILITIES, fid)
    source_type = v_enum(body, "source_type",
                         {"BOILER", "GENERATOR", "FLARE", "PROCESS_VENT", "STORAGE_TANK"})
    pollutant = v_enum(body, "pollutant", {"NOX", "SO2", "CO", "PM", "VOC"})
    max_rate = v_num(body, "max_hourly_rate_lbs", lambda x: x > 0, "> 0")
    hours = v_int(body, "operating_hours_per_year", 1, 8760)
    ce = body.get("control_efficiency", 0)
    if ce is None:
        ce = 0
    if not isinstance(ce, (int, float)) or isinstance(ce, bool) or ce < 0 or ce >= 1:
        raise err("ERR_INVALID_REQUEST", 400, "control_efficiency must be 0 <= x < 1")
    permit_limit = v_num(body, "permit_limit_ppm", lambda x: x > 0, "> 0")
    if not (isinstance(body.get("expected_facility_version"), int)
            and not isinstance(body.get("expected_facility_version"), bool)):
        raise err("ERR_INVALID_REQUEST", 400, "expected_facility_version required")

    uncontrolled, controlled = compute_source_pte(max_rate, hours, ce)
    s = new_entity(
        facility_id=fid,
        source_type=source_type,
        pollutant=pollutant,
        max_hourly_rate_lbs=max_rate,
        operating_hours_per_year=hours,
        control_efficiency=ce,
        permit_limit_ppm=permit_limit,
        uncontrolled_pte_tpy=uncontrolled,
        controlled_pte_tpy=controlled,
        lifecycle_status="REGISTERED",
        monitoring_status="UNMONITORED",
    )
    SOURCES[s["id"]] = s
    recompute_facility_pte(f)
    touch(f)
    return success(serialize(s), 201)


@app.route("/sources/<sid>", methods=["GET"])
def get_source(sid):
    auth(*FOUR)
    s = get_or_404(SOURCES, sid)
    return success(serialize(s), 200)


@app.route("/facilities/<fid>/sources", methods=["GET"])
def list_facility_sources(fid):
    auth(*FOUR)
    get_or_404(FACILITIES, fid)
    items = [s for s in SOURCES.values() if s["facility_id"] == fid]
    return list_response(items)


@app.route("/sources/<sid>/permit", methods=["POST"])
def source_permit(sid):
    auth("PermitReviewer")
    s = get_or_404(SOURCES, sid)
    if s["lifecycle_status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", 409, "Source not REGISTERED")
    s["lifecycle_status"] = "PERMITTED"
    touch(s)
    return success(serialize(s), 200)


@app.route("/sources/<sid>/start-operating", methods=["POST"])
def source_start_operating(sid):
    auth("FacilityOperator")
    s = get_or_404(SOURCES, sid)
    if s["lifecycle_status"] != "PERMITTED":
        raise err("ERR_INVALID_STATE", 409, "Source not PERMITTED")
    f = FACILITIES.get(s["facility_id"])
    if f is not None and f["compliance_status"] == "SUSPENDED":
        raise err("ERR_FACILITY_SUSPENDED", 409, "Facility suspended")
    s["lifecycle_status"] = "OPERATING"
    touch(s)
    return success(serialize(s), 200)


@app.route("/sources/<sid>/shutdown", methods=["POST"])
def source_shutdown(sid):
    auth("FacilityOperator")
    s = get_or_404(SOURCES, sid)
    if s["lifecycle_status"] not in ("PERMITTED", "OPERATING", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", 409, "Source cannot be shut down from this state")
    s["lifecycle_status"] = "SHUTDOWN"
    touch(s)
    f = FACILITIES.get(s["facility_id"])
    if f is not None:
        recompute_facility_pte(f)
        touch(f)
    return success(serialize(s), 200)


@app.route("/sources/<sid>/cem-data", methods=["POST"])
def create_cem(sid):
    auth("Inspector")
    s = get_or_404(SOURCES, sid)
    body = body_json()
    period_start = v_dt(body, "period_start")
    period_end = v_dt(body, "period_end")
    avg = v_num(body, "avg_concentration_ppm", lambda x: x >= 0, ">= 0")
    is_exc = avg > s["permit_limit_ppm"]
    blk = new_entity(
        source_id=sid,
        period_start=period_start,
        period_end=period_end,
        avg_concentration_ppm=avg,
        is_exceedance=is_exc,
    )
    CEM_BLOCKS[blk["id"]] = blk
    if s["monitoring_status"] != "CEM_ACTIVE":
        s["monitoring_status"] = "CEM_ACTIVE"
        touch(s)
    return success(serialize(blk), 201)


@app.route("/sources/<sid>/cem-data", methods=["GET"])
def list_cem(sid):
    auth(*FOUR)
    get_or_404(SOURCES, sid)
    items = [b for b in CEM_BLOCKS.values() if b["source_id"] == sid]
    return list_response(items)


@app.route("/sources/<sid>/exceedances", methods=["GET"])
def list_source_exceedances(sid):
    auth(*FOUR)
    get_or_404(SOURCES, sid)
    items = [e for e in EXCEEDANCES.values() if e["source_id"] == sid]
    return list_response(items)


@app.route("/sources/<sid>/stack-tests", methods=["GET"])
def list_source_stack_tests(sid):
    auth(*FOUR)
    get_or_404(SOURCES, sid)
    items = [t for t in STACK_TESTS.values() if t["source_id"] == sid]
    return list_response(items)


# ===========================================================================
# PERMITS
# ===========================================================================
@app.route("/permits", methods=["POST"])
def create_permit():
    auth("FacilityOperator")
    body = body_json()
    fid = v_str(body, "facility_id")
    get_or_404(FACILITIES, fid)
    permit_type = v_enum(body, "permit_type", {"PERMIT_BY_RULE", "TITLE_V"})
    p = new_entity(
        facility_id=fid,
        permit_type=permit_type,
        status="DRAFT",
        issued_at=None,
        renewal_count=0,
    )
    PERMITS[p["id"]] = p
    return success(serialize(p), 201)


@app.route("/permits/<pid>", methods=["GET"])
def get_permit(pid):
    auth(*FOUR)
    p = get_or_404(PERMITS, pid)
    return success(serialize(p), 200)


@app.route("/facilities/<fid>/permits", methods=["GET"])
def list_facility_permits(fid):
    auth(*FOUR)
    get_or_404(FACILITIES, fid)
    items = [p for p in PERMITS.values() if p["facility_id"] == fid]
    return list_response(items)


@app.route("/permits/<pid>/submit", methods=["POST"])
def permit_submit(pid):
    uid, role = auth("FacilityOperator")
    p = get_or_404(PERMITS, pid)
    require_owner(uid, role, p["facility_id"])
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Permit not DRAFT")
    f = FACILITIES.get(p["facility_id"])
    if f is None or p["permit_type"] != f["permit_track"]:
        raise err("ERR_PERMIT_TRACK_MISMATCH", 422, "permit_type must match facility permit_track")
    p["status"] = "SUBMITTED"
    touch(p)
    return success(serialize(p), 200)


@app.route("/permits/<pid>/begin-review", methods=["POST"])
def permit_begin_review(pid):
    auth("PermitReviewer")
    p = get_or_404(PERMITS, pid)
    if p["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Permit not SUBMITTED")
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return success(serialize(p), 200)


@app.route("/permits/<pid>/return-for-revision", methods=["POST"])
def permit_return(pid):
    auth("PermitReviewer")
    p = get_or_404(PERMITS, pid)
    if p["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "Permit not UNDER_REVIEW")
    p["status"] = "DRAFT"
    touch(p)
    return success(serialize(p), 200)


def _latest_notice_for_permit(pid):
    notices = [n for n in NOTICES.values() if n["permit_id"] == pid]
    if not notices:
        return None
    notices.sort(key=lambda n: n["_seq"])
    return notices[-1]


@app.route("/permits/<pid>/open-public-notice", methods=["POST"])
def permit_open_notice(pid):
    auth("PermitReviewer")
    p = get_or_404(PERMITS, pid)
    if p["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "Permit not UNDER_REVIEW")
    notice = _latest_notice_for_permit(pid)
    if notice is None:
        raise err("ERR_INVALID_STATE", 409, "No public notice exists for this permit")
    p["status"] = "PUBLIC_NOTICE"
    touch(p)
    if notice["status"] != "OPEN":
        notice["status"] = "OPEN"
        touch(notice)
    return success(serialize(p), 200)


@app.route("/permits/<pid>/issue", methods=["POST"])
def permit_issue(pid):
    auth("PermitReviewer")
    p = get_or_404(PERMITS, pid)
    if p["status"] != "PUBLIC_NOTICE":
        raise err("ERR_INVALID_STATE", 409, "Permit not in PUBLIC_NOTICE")
    notice = _latest_notice_for_permit(pid)
    if notice is None or notice["status"] != "CLOSED":
        raise err("ERR_NOTICE_NOT_CLOSED", 409, "Linked public notice is not CLOSED")
    p["status"] = "ISSUED"
    p["issued_at"] = CLOCK
    touch(p)
    f = FACILITIES.get(p["facility_id"])
    if f is not None and f["permit_track"] == "TITLE_V":
        for s in SOURCES.values():
            if s["facility_id"] == f["id"] and s["lifecycle_status"] == "REGISTERED":
                s["lifecycle_status"] = "PERMITTED"
                touch(s)
    return success(serialize(p), 200)


@app.route("/permits/<pid>/start-renewal", methods=["POST"])
def permit_start_renewal(pid):
    auth("FacilityOperator")
    p = get_or_404(PERMITS, pid)
    if p["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", 409, "Permit not ISSUED")
    p["status"] = "RENEWAL_PENDING"
    touch(p)
    return success(serialize(p), 200)


@app.route("/permits/<pid>/complete-renewal", methods=["POST"])
def permit_complete_renewal(pid):
    auth("PermitReviewer")
    p = get_or_404(PERMITS, pid)
    if p["status"] != "RENEWAL_PENDING":
        raise err("ERR_INVALID_STATE", 409, "Permit not RENEWAL_PENDING")
    p["status"] = "ISSUED"
    p["renewal_count"] += 1
    p["issued_at"] = CLOCK
    touch(p)
    return success(serialize(p), 200)


# ===========================================================================
# PUBLIC NOTICES
# ===========================================================================
def _intervals_overlap_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@app.route("/public-notices", methods=["POST"])
def create_notice():
    auth("PermitReviewer")
    body = body_json()
    pid = v_str(body, "permit_id")
    p = get_or_404(PERMITS, pid)
    open_at = body.get("comment_open_at")
    close_at = body.get("comment_close_at")
    # parse for overlap (priority 9); malformed falls to interval/body checks
    parsed_open = parsed_close = None
    try:
        if isinstance(open_at, str):
            parsed_open = parse_dt(open_at)
        if isinstance(close_at, str):
            parsed_close = parse_dt(close_at)
    except Exception:
        parsed_open = parsed_close = None
    # priority 9: window overlap vs other notices on permits of the same facility
    if parsed_open is not None and parsed_close is not None:
        facility_id = p["facility_id"]
        fac_permit_ids = {pp["id"] for pp in PERMITS.values() if pp["facility_id"] == facility_id}
        for n in NOTICES.values():
            if n["permit_id"] in fac_permit_ids:
                if _intervals_overlap_closed(parsed_open, parsed_close,
                                             n["comment_open_at"], n["comment_close_at"]):
                    raise err("ERR_NOTICE_WINDOW_OVERLAP", 409, "Comment window overlaps another notice")
    # priority 13: interval validity
    o = v_dt(body, "comment_open_at")
    c = v_dt(body, "comment_close_at")
    if not (c > o):
        raise err("ERR_INVALID_INTERVAL", 422, "comment_close_at must be after comment_open_at")
    n = new_entity(
        permit_id=pid,
        comment_open_at=o,
        comment_close_at=c,
        comment_count=0,
        status="OPEN",
    )
    NOTICES[n["id"]] = n
    return success(serialize(n), 201)


@app.route("/public-notices/<nid>", methods=["GET"])
def get_notice(nid):
    auth(*FOUR)
    n = get_or_404(NOTICES, nid)
    return success(serialize(n), 200)


@app.route("/permits/<pid>/public-notices", methods=["GET"])
def list_permit_notices(pid):
    auth(*FOUR)
    get_or_404(PERMITS, pid)
    items = [n for n in NOTICES.values() if n["permit_id"] == pid]
    return list_response(items)


@app.route("/public-notices/<nid>/comment", methods=["POST"])
def notice_comment(nid):
    auth("Anonymous")
    n = get_or_404(NOTICES, nid)
    # priority 16: open comment window
    if n["status"] != "OPEN" or CLOCK >= n["comment_close_at"]:
        raise err("ERR_COMMENT_WINDOW_CLOSED", 409, "Comment window is closed")
    body = body_json()
    v_str(body, "comment_text")
    n["comment_count"] += 1
    touch(n)
    return success(serialize(n), 201)


@app.route("/public-notices/<nid>/close", methods=["POST"])
def notice_close(nid):
    auth("PermitReviewer")
    n = get_or_404(NOTICES, nid)
    if n["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", 409, "Notice not OPEN")
    n["status"] = "CLOSED"
    touch(n)
    return success(serialize(n), 200)


# ===========================================================================
# INVENTORIES
# ===========================================================================
@app.route("/inventories", methods=["POST"])
def create_inventory():
    auth("FacilityOperator")
    body = body_json()
    fid = v_str(body, "facility_id")
    get_or_404(FACILITIES, fid)
    year = body.get("reporting_year")
    # priority 14: unique reporting year per facility (when year is an int)
    if isinstance(year, int) and not isinstance(year, bool):
        for inv in INVENTORIES.values():
            if inv["facility_id"] == fid and inv["reporting_year"] == year:
                raise err("ERR_DUPLICATE_INVENTORY_YEAR", 409, "Duplicate reporting year")
    # priority 18: body validation
    year = v_int(body, "reporting_year", 2000, 2100)
    due_at = v_dt(body, "due_at")
    inv = new_entity(
        facility_id=fid,
        reporting_year=year,
        status="DRAFT",
        total_emissions_tons=0.0,
        estimated_fee_cents=0,
        assessed_fee_cents=0,
        certified_at=None,
        due_at=due_at,
    )
    INVENTORIES[inv["id"]] = inv
    return success(serialize(inv), 201)


@app.route("/inventories/<iid>", methods=["GET"])
def get_inventory(iid):
    auth(*FOUR)
    inv = get_or_404(INVENTORIES, iid)
    return success(serialize(inv), 200)


@app.route("/facilities/<fid>/inventories", methods=["GET"])
def list_facility_inventories(fid):
    auth(*FOUR)
    get_or_404(FACILITIES, fid)
    items = [i for i in INVENTORIES.values() if i["facility_id"] == fid]
    year = request.args.get("reporting_year")
    if year is not None:
        try:
            y = int(year)
            items = [i for i in items if i["reporting_year"] == y]
        except ValueError:
            items = []
    return list_response(items)


@app.route("/line-items", methods=["POST"])
def create_line_item():
    auth("FacilityOperator")
    body = body_json()
    iid = v_str(body, "inventory_id")
    inv = get_or_404(INVENTORIES, iid)
    sid = v_str(body, "source_id")
    get_or_404(SOURCES, sid)
    if inv["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Inventory not DRAFT")
    method = v_enum(body, "method", {"ESTIMATED", "STACK_TEST", "CEM"})
    reported = v_num(body, "reported_tons", lambda x: x >= 0, ">= 0")
    reported = rhu(reported, 3)
    li = new_entity(
        inventory_id=iid,
        source_id=sid,
        method=method,
        reported_tons=reported,
    )
    LINE_ITEMS[li["id"]] = li
    return success(serialize(li), 201)


@app.route("/line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    auth(*FOUR)
    li = get_or_404(LINE_ITEMS, lid)
    return success(serialize(li), 200)


@app.route("/line-items", methods=["GET"])
def list_line_items():
    auth(*FOUR)
    items = list(LINE_ITEMS.values())
    iid = request.args.get("inventory_id")
    sid = request.args.get("source_id")
    if iid is not None:
        items = [li for li in items if li["inventory_id"] == iid]
    if sid is not None:
        items = [li for li in items if li["source_id"] == sid]
    return list_response(items)


@app.route("/inventories/<iid>/submit", methods=["POST"])
def inventory_submit(iid):
    uid, role = auth("FacilityOperator")
    inv = get_or_404(INVENTORIES, iid)
    require_owner(uid, role, inv["facility_id"])
    if inv["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Inventory not DRAFT")
    has_items = any(li["inventory_id"] == iid for li in LINE_ITEMS.values())
    if not has_items:
        raise err("ERR_NO_LINE_ITEMS", 409, "Inventory has no line items")
    total = inventory_total(iid)
    inv["total_emissions_tons"] = total
    inv["estimated_fee_cents"] = emissions_fee(total, "estimated")
    inv["status"] = "SUBMITTED"
    touch(inv)
    return success(serialize(inv), 200)


@app.route("/inventories/<iid>/reject", methods=["POST"])
def inventory_reject(iid):
    auth("PermitReviewer")
    inv = get_or_404(INVENTORIES, iid)
    if inv["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Inventory not SUBMITTED")
    inv["status"] = "DRAFT"
    touch(inv)
    return success(serialize(inv), 200)


@app.route("/inventories/<iid>/certify", methods=["POST"])
def inventory_certify(iid):
    auth("PermitReviewer")
    inv = get_or_404(INVENTORIES, iid)
    body = body_json()
    # priority 5: state
    if inv["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Inventory not SUBMITTED")
    f = FACILITIES.get(inv["facility_id"])
    # priority 6: facility not suspended
    if f is not None and f["compliance_status"] == "SUSPENDED":
        raise err("ERR_FACILITY_SUSPENDED", 409, "Facility suspended")
    # priority 8: no unresolved exceedance on referenced sources
    ref_sources = {li["source_id"] for li in LINE_ITEMS.values() if li["inventory_id"] == iid}
    for e in EXCEEDANCES.values():
        if e["source_id"] in ref_sources and e["status"] in ("OPEN", "REPORTED_LATE"):
            raise err("ERR_UNRESOLVED_EXCEEDANCE", 409, "Unresolved exceedance on inventory source")
    # priority 17: OCC
    if f is not None:
        occ_check(f, body)
    # priority 18: body (expected_facility_version required)
    if not (isinstance(body.get("expected_facility_version"), int)
            and not isinstance(body.get("expected_facility_version"), bool)):
        raise err("ERR_INVALID_REQUEST", 400, "expected_facility_version required")

    total = inventory_total(iid)
    inv["total_emissions_tons"] = total
    inv["certified_at"] = CLOCK
    inv["assessed_fee_cents"] = emissions_fee(total, "assessed", CLOCK, inv["due_at"])
    inv["status"] = "CERTIFIED"
    touch(inv)
    if f is not None:
        f["fee_balance_cents"] += inv["assessed_fee_cents"]
        touch(f)
    return success(serialize(inv), 200)


@app.route("/inventories/<iid>/amend", methods=["POST"])
def inventory_amend(iid):
    uid, role = auth("FacilityOperator")
    inv = get_or_404(INVENTORIES, iid)
    require_owner(uid, role, inv["facility_id"])
    if inv["status"] != "CERTIFIED":
        raise err("ERR_INVALID_STATE", 409, "Inventory not CERTIFIED")
    f = FACILITIES.get(inv["facility_id"])
    if f is not None and f["compliance_status"] == "SUSPENDED":
        raise err("ERR_FACILITY_SUSPENDED", 409, "Facility suspended")
    assessed = inv["assessed_fee_cents"]
    inv["status"] = "AMENDED"
    inv["assessed_fee_cents"] = 0
    touch(inv)
    if f is not None:
        f["fee_balance_cents"] -= assessed
        touch(f)
    return success(serialize(inv), 200)


# ===========================================================================
# STACK TESTS
# ===========================================================================
@app.route("/stack-tests", methods=["POST"])
def create_stack_test():
    auth("Inspector")
    body = body_json()
    sid = v_str(body, "source_id")
    get_or_404(SOURCES, sid)
    start = body.get("scheduled_start")
    end = body.get("scheduled_end")
    p_start = p_end = None
    try:
        if isinstance(start, str):
            p_start = parse_dt(start)
        if isinstance(end, str):
            p_end = parse_dt(end)
    except Exception:
        p_start = p_end = None
    # priority 10: conflict (overlap or within 7-day buffer) on the same source
    if p_start is not None and p_end is not None:
        buffer = timedelta(days=STACK_TEST_BUFFER_DAYS)
        for t in STACK_TESTS.values():
            if t["source_id"] != sid:
                continue
            ex_s = t["scheduled_start"]
            ex_e = t["scheduled_end"]
            if p_end <= ex_s:
                sep = ex_s - p_end
            elif ex_e <= p_start:
                sep = p_start - ex_e
            else:
                sep = timedelta(0)  # overlap
            if sep < buffer:
                raise err("ERR_STACK_TEST_CONFLICT", 409, "Stack test window conflict")
    # priority 13: interval validity
    s = v_dt(body, "scheduled_start")
    e = v_dt(body, "scheduled_end")
    if not (e >= s):
        raise err("ERR_INVALID_INTERVAL", 422, "scheduled_end must not be before scheduled_start")
    st = new_entity(
        source_id=sid,
        scheduled_start=s,
        scheduled_end=e,
        measured_rate_lbs=None,
        status="SCHEDULED",
    )
    STACK_TESTS[st["id"]] = st
    return success(serialize(st), 201)


@app.route("/stack-tests/<tid>", methods=["GET"])
def get_stack_test(tid):
    auth(*FOUR)
    st = get_or_404(STACK_TESTS, tid)
    return success(serialize(st), 200)


@app.route("/stack-tests/<tid>/conduct", methods=["POST"])
def stack_test_conduct(tid):
    auth("Inspector")
    st = get_or_404(STACK_TESTS, tid)
    if st["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", 409, "Stack test not SCHEDULED")
    if CLOCK < st["scheduled_start"]:
        raise err("ERR_INVALID_STATE", 409, "Clock has not reached scheduled_start")
    body = body_json()
    measured = v_num(body, "measured_rate_lbs")
    st["measured_rate_lbs"] = measured
    s = SOURCES.get(st["source_id"])
    if measured <= s["max_hourly_rate_lbs"]:
        st["status"] = "PASSED"
        touch(st)
        if s["monitoring_status"] != "STACK_TESTED":
            s["monitoring_status"] = "STACK_TESTED"
            touch(s)
    else:
        st["status"] = "FAILED"
        touch(st)
        mag = rhu((measured - s["max_hourly_rate_lbs"]) / s["max_hourly_rate_lbs"] * 100, 2)
        ev = new_entity(
            source_id=s["id"],
            event_type="EXCEEDANCE",
            detected_at=CLOCK,
            magnitude_pct=mag,
            reported_at=None,
            status="OPEN",
            _enforcement_action_id=None,
        )
        EXCEEDANCES[ev["id"]] = ev
        f = FACILITIES.get(s["facility_id"])
        if f is not None and reconcile_facility(f):
            touch(f)
    return success(serialize(st), 200)


# ===========================================================================
# EXCEEDANCES
# ===========================================================================
@app.route("/exceedances", methods=["POST"])
def create_exceedance():
    auth("Inspector")
    body = body_json()
    sid = v_str(body, "source_id")
    s = get_or_404(SOURCES, sid)
    event_type = v_enum(body, "event_type", {"EXCEEDANCE", "DEVIATION"})
    detected_at = v_dt(body, "detected_at")
    mag = body.get("magnitude_pct", 0)
    if mag is None:
        mag = 0
    if not isinstance(mag, (int, float)) or isinstance(mag, bool) or mag < 0:
        raise err("ERR_INVALID_REQUEST", 400, "magnitude_pct must be >= 0")
    ev = new_entity(
        source_id=sid,
        event_type=event_type,
        detected_at=detected_at,
        magnitude_pct=mag,
        reported_at=None,
        status="OPEN",
        _enforcement_action_id=None,
    )
    EXCEEDANCES[ev["id"]] = ev
    f = FACILITIES.get(s["facility_id"])
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(ev), 201)


@app.route("/exceedances/<eid>", methods=["GET"])
def get_exceedance(eid):
    auth(*FOUR)
    ev = get_or_404(EXCEEDANCES, eid)
    return success(serialize(ev), 200)


@app.route("/exceedances/<eid>/report", methods=["POST"])
def exceedance_report(eid):
    uid, role = auth("FacilityOperator")
    ev = get_or_404(EXCEEDANCES, eid)
    s = SOURCES.get(ev["source_id"])
    facility_id = s["facility_id"] if s is not None else None
    require_owner(uid, role, facility_id)
    if ev["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", 409, "Exceedance not OPEN")
    ev["reported_at"] = CLOCK
    deadline = ev["detected_at"] + timedelta(hours=REPORT_DEADLINE_HOURS)
    f = FACILITIES.get(facility_id)
    if CLOCK <= deadline:
        ev["status"] = "REPORTED"
        touch(ev)
    else:
        ev["status"] = "REPORTED_LATE"
        touch(ev)
        action = new_entity(
            facility_id=facility_id,
            action_type="NOTICE_OF_VIOLATION",
            origin="LATE_EXCEEDANCE",
            penalty_cents=0,
            variance_start=None,
            variance_end=None,
            status="INITIATED",
        )
        ENFORCEMENTS[action["id"]] = action
        ev["_enforcement_action_id"] = action["id"]
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(ev), 200)


@app.route("/exceedances/<eid>/resolve", methods=["POST"])
def exceedance_resolve(eid):
    auth("Inspector")
    ev = get_or_404(EXCEEDANCES, eid)
    if ev["status"] not in ("REPORTED", "REPORTED_LATE"):
        raise err("ERR_INVALID_STATE", 409, "Exceedance not in a reported state")
    if ev["status"] == "REPORTED_LATE":
        action_id = ev.get("_enforcement_action_id")
        action = ENFORCEMENTS.get(action_id) if action_id else None
        if action is None or action["status"] not in ("DISMISSED", "CLOSED", "PAID"):
            raise err("ERR_INVALID_STATE", 409, "Linked enforcement action not resolved")
    ev["status"] = "RESOLVED"
    touch(ev)
    s = SOURCES.get(ev["source_id"])
    f = FACILITIES.get(s["facility_id"]) if s is not None else None
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(ev), 200)


# ===========================================================================
# COMPLAINTS
# ===========================================================================
@app.route("/complaints", methods=["POST"])
def create_complaint():
    auth("Anonymous")
    body = body_json()
    fid = v_str(body, "facility_id")
    get_or_404(FACILITIES, fid)
    description = v_str(body, "description")
    severity = v_enum(body, "severity", {"LOW", "MEDIUM", "HIGH"})
    c = new_entity(
        facility_id=fid,
        description=description,
        severity=severity,
        status="RECEIVED",
    )
    COMPLAINTS[c["id"]] = c
    return success(serialize(c), 201)


@app.route("/complaints/<cid>", methods=["GET"])
def get_complaint(cid):
    auth(*FOUR)
    c = get_or_404(COMPLAINTS, cid)
    return success(serialize(c), 200)


@app.route("/facilities/<fid>/complaints", methods=["GET"])
def list_facility_complaints(fid):
    auth(*AGENCY3)
    get_or_404(FACILITIES, fid)
    items = [c for c in COMPLAINTS.values() if c["facility_id"] == fid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@app.route("/complaints/<cid>/dismiss", methods=["POST"])
def complaint_dismiss(cid):
    auth("Inspector")
    c = get_or_404(COMPLAINTS, cid)
    if c["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", 409, "Complaint not RECEIVED")
    c["status"] = "DISMISSED"
    touch(c)
    return success(serialize(c), 200)


# ===========================================================================
# INSPECTIONS
# ===========================================================================
@app.route("/inspections", methods=["POST"])
def create_inspection():
    auth("Inspector")
    body = body_json()
    fid = v_str(body, "facility_id")
    get_or_404(FACILITIES, fid)
    complaint_id = body.get("complaint_id")
    complaint = None
    if complaint_id is not None:
        complaint = get_or_404(COMPLAINTS, complaint_id)
    start = body.get("scheduled_start")
    end = body.get("scheduled_end")
    p_start = p_end = None
    try:
        if isinstance(start, str):
            p_start = parse_dt(start)
        if isinstance(end, str):
            p_end = parse_dt(end)
    except Exception:
        p_start = p_end = None
    # priority 11: inspection overlap on same facility (half-open [start,end))
    if p_start is not None and p_end is not None:
        for insp in INSPECTIONS.values():
            if insp["facility_id"] != fid:
                continue
            if p_start < insp["scheduled_end"] and insp["scheduled_start"] < p_end:
                raise err("ERR_INSPECTION_OVERLAP", 409, "Inspection window overlaps another")
    # priority 13: interval validity
    s = v_dt(body, "scheduled_start")
    e = v_dt(body, "scheduled_end")
    if not (e >= s):
        raise err("ERR_INVALID_INTERVAL", 422, "scheduled_end must not be before scheduled_start")
    insp = new_entity(
        facility_id=fid,
        complaint_id=complaint_id,
        scheduled_start=s,
        scheduled_end=e,
        outcome="PENDING",
        status="SCHEDULED",
    )
    INSPECTIONS[insp["id"]] = insp
    if complaint is not None and complaint["status"] == "RECEIVED":
        complaint["status"] = "INSPECTION_SCHEDULED"
        touch(complaint)
    return success(serialize(insp), 201)


@app.route("/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    auth(*FOUR)
    insp = get_or_404(INSPECTIONS, iid)
    return success(serialize(insp), 200)


@app.route("/facilities/<fid>/inspections", methods=["GET"])
def list_facility_inspections(fid):
    auth(*FOUR)
    get_or_404(FACILITIES, fid)
    items = [i for i in INSPECTIONS.values() if i["facility_id"] == fid]
    return list_response(items)


@app.route("/complaints/<cid>/inspections", methods=["GET"])
def list_complaint_inspections(cid):
    auth(*FOUR)
    get_or_404(COMPLAINTS, cid)
    items = [i for i in INSPECTIONS.values() if i["complaint_id"] == cid]
    return list_response(items)


@app.route("/inspections/<iid>/complete", methods=["POST"])
def inspection_complete(iid):
    auth("Inspector")
    insp = get_or_404(INSPECTIONS, iid)
    if insp["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", 409, "Inspection not SCHEDULED")
    body = body_json()
    outcome = v_enum(body, "outcome", {"PASS", "FAIL"})
    insp["status"] = "COMPLETED"
    insp["outcome"] = outcome
    touch(insp)
    if insp["complaint_id"] is not None:
        c = COMPLAINTS.get(insp["complaint_id"])
        if c is not None and c["status"] == "INSPECTION_SCHEDULED":
            c["status"] = "CLOSED"
            touch(c)
    if outcome == "FAIL":
        action = new_entity(
            facility_id=insp["facility_id"],
            action_type="NOTICE_OF_VIOLATION",
            origin="INSPECTION_FAIL",
            penalty_cents=0,
            variance_start=None,
            variance_end=None,
            status="INITIATED",
        )
        ENFORCEMENTS[action["id"]] = action
        f = FACILITIES.get(insp["facility_id"])
        if f is not None and reconcile_facility(f):
            touch(f)
    return success(serialize(insp), 200)


# ===========================================================================
# ENFORCEMENT ACTIONS
# ===========================================================================
@app.route("/enforcement-actions", methods=["POST"])
def create_enforcement():
    auth("EnforcementOfficer")
    body = body_json()
    fid = v_str(body, "facility_id")
    get_or_404(FACILITIES, fid)
    action_type = v_enum(body, "action_type", {"NOTICE_OF_VIOLATION", "VARIANCE", "PENALTY"})
    origin = body.get("origin", "MANUAL")
    if origin is None:
        origin = "MANUAL"
    if origin not in ("MANUAL", "LATE_EXCEEDANCE", "INSPECTION_FAIL"):
        raise err("ERR_INVALID_REQUEST", 400, "Invalid origin")
    vs = None
    ve = None
    if body.get("variance_start") is not None:
        vs = v_dt(body, "variance_start")
    if body.get("variance_end") is not None:
        ve = v_dt(body, "variance_end")
    action = new_entity(
        facility_id=fid,
        action_type=action_type,
        origin=origin,
        penalty_cents=0,
        variance_start=vs,
        variance_end=ve,
        status="INITIATED",
    )
    ENFORCEMENTS[action["id"]] = action
    f = FACILITIES.get(fid)
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(action), 201)


@app.route("/enforcement-actions/<aid>", methods=["GET"])
def get_enforcement(aid):
    auth(*FOUR)
    action = get_or_404(ENFORCEMENTS, aid)
    return success(serialize(action), 200)


@app.route("/facilities/<fid>/enforcement-actions", methods=["GET"])
def list_facility_enforcements(fid):
    auth(*FOUR)
    get_or_404(FACILITIES, fid)
    items = [a for a in ENFORCEMENTS.values() if a["facility_id"] == fid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


@app.route("/enforcement-actions/<aid>/assess-penalty", methods=["POST"])
def enforcement_assess_penalty(aid):
    auth("EnforcementOfficer")
    action = get_or_404(ENFORCEMENTS, aid)
    if action["status"] != "INITIATED" or action["action_type"] not in ("NOTICE_OF_VIOLATION", "PENALTY"):
        raise err("ERR_INVALID_STATE", 409, "Action cannot be penalized from this state/type")
    action["penalty_cents"] = compute_penalty(action)
    action["status"] = "PENALTY_ASSESSED"
    touch(action)
    fid = action["facility_id"]
    # cascade: OPERATING sources -> SUSPENDED, ISSUED permits -> REVOKED
    for s in SOURCES.values():
        if s["facility_id"] == fid and s["lifecycle_status"] == "OPERATING":
            s["lifecycle_status"] = "SUSPENDED"
            touch(s)
    for p in PERMITS.values():
        if p["facility_id"] == fid and p["status"] == "ISSUED":
            p["status"] = "REVOKED"
            touch(p)
    f = FACILITIES.get(fid)
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(action), 200)


@app.route("/enforcement-actions/<aid>/grant-variance", methods=["POST"])
def enforcement_grant_variance(aid):
    auth("EnforcementOfficer")
    action = get_or_404(ENFORCEMENTS, aid)
    if action["status"] != "INITIATED" or action["action_type"] != "VARIANCE":
        raise err("ERR_INVALID_STATE", 409, "Action cannot be granted a variance from this state/type")
    body = body_json()
    if body.get("variance_start") is not None:
        action["variance_start"] = v_dt(body, "variance_start")
    if body.get("variance_end") is not None:
        action["variance_end"] = v_dt(body, "variance_end")
    if action["variance_start"] is None or action["variance_end"] is None:
        raise err("ERR_INVALID_REQUEST", 400, "variance_start and variance_end are required")
    if not (action["variance_start"] < action["variance_end"]):
        raise err("ERR_INVALID_INTERVAL", 422, "variance_start must be before variance_end")
    action["status"] = "VARIANCE_GRANTED"
    touch(action)
    f = FACILITIES.get(action["facility_id"])
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(action), 200)


@app.route("/enforcement-actions/<aid>/dismiss", methods=["POST"])
def enforcement_dismiss(aid):
    auth("EnforcementOfficer")
    action = get_or_404(ENFORCEMENTS, aid)
    if action["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", 409, "Action not INITIATED")
    action["status"] = "DISMISSED"
    touch(action)
    f = FACILITIES.get(action["facility_id"])
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(action), 200)


@app.route("/enforcement-actions/<aid>/pay", methods=["POST"])
def enforcement_pay(aid):
    uid, role = auth("FacilityOperator")
    action = get_or_404(ENFORCEMENTS, aid)
    require_owner(uid, role, action["facility_id"])
    if action["status"] != "PENALTY_ASSESSED":
        raise err("ERR_INVALID_STATE", 409, "Action not PENALTY_ASSESSED")
    action["status"] = "PAID"
    touch(action)
    fid = action["facility_id"]
    for s in SOURCES.values():
        if s["facility_id"] == fid and s["lifecycle_status"] == "SUSPENDED":
            s["lifecycle_status"] = "OPERATING"
            touch(s)
    f = FACILITIES.get(fid)
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(action), 200)


@app.route("/enforcement-actions/<aid>/close", methods=["POST"])
def enforcement_close(aid):
    auth("EnforcementOfficer")
    action = get_or_404(ENFORCEMENTS, aid)
    if action["status"] != "PAID":
        raise err("ERR_INVALID_STATE", 409, "Action not PAID")
    action["status"] = "CLOSED"
    touch(action)
    f = FACILITIES.get(action["facility_id"])
    if f is not None and reconcile_facility(f):
        touch(f)
    return success(serialize(action), 200)


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth("PermitReviewer", "Inspector", "EnforcementOfficer", "FacilityOperator")
    body = body_json()
    global CLOCK
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise err("ERR_INVALID_REQUEST", 400, "to_iso8601 required")
    try:
        CLOCK = parse_dt(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", 400, "Malformed to_iso8601")
    return success({}, 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
