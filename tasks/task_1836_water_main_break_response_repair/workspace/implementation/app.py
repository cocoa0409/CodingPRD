#!/usr/bin/env python3
"""Water Main Break Response & Repair API — in-memory Flask implementation.

Built from PRD.md + SCAFFOLD.yaml. In-memory stores only; nothing is seeded
at startup. Logical clock starts at 2026-08-01T00:00:00Z and advances only
via POST /_clock/set_current_utc.
"""
import calendar
import math
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================================
# Logical clock
# =========================================================================
_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def subtract_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) - months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# =========================================================================
# In-memory store (starts empty; no seeding)
# =========================================================================
db = {
    "pipe_segments": {},
    "valves": {},
    "pressure_anomalies": {},
    "break_reports": {},
    "isolation_events": {},
    "crews": {},
    "work_orders": {},
    "advisories": {},
    "wq_tests": {},
    "restoration_jobs": {},
    "traffic_permits": {},
    "damage_claims": {},
}
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_entity():
    t = clock_now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(e):
    e["updated_at"] = clock_now()
    e["version"] += 1


def ser(e):
    out = {}
    for k, v in e.items():
        if k.startswith("_"):
            continue
        out[k] = fmt_ts(v) if isinstance(v, datetime) else v
    return out


# =========================================================================
# Errors and response envelope
# =========================================================================
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def meta_base():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {
        "api_request_id": rid,
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def err_response(error_id, status, message):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e.error_id, e.status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return err_response("ERR_NOT_FOUND", 404, "The requested resource was not found")


@app.errorhandler(405)
def _handle_405(e):
    return err_response("ERR_NOT_FOUND", 404, "The requested resource was not found")


@app.errorhandler(Exception)
def _handle_generic(e):
    return err_response("ERR_INTERNAL", 500, str(e))


def ok_object(data, status=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), status


def ok_list(items):
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
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": m, "response_type": "array", "data": page}), 200


def sorted_rows(rows):
    return sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))


# =========================================================================
# Auth (X-User-ID / X-User-Role)
# =========================================================================
ALL_ROLES = [
    "Dispatcher", "CrewLead", "WaterQualityOfficer",
    "ClaimsAdjuster", "PublicWorksEngineer", "System",
]


def auth_user(allowed_roles):
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role:
        raise ApiError("ERR_MISSING_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       f"Role '{role}' is not authorized for this endpoint")
    return uid


# =========================================================================
# Field validation helpers (ERR_VALIDATION, tier: existence/validity)
# =========================================================================
def body_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def v_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field '{field}' is required and must be a non-empty string")
    return v


def v_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' must be <= {maximum}")
    return v


def v_num(body, field, minimum=None, exclusive_min=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field '{field}' is required and must be a number")
    if minimum is not None:
        if exclusive_min and not v > minimum:
            raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' must be > {minimum}")
        if not exclusive_min and v < minimum:
            raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' must be >= {minimum}")
    return v


def v_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def v_dt(body, field):
    dt = parse_dt(body.get(field))
    if dt is None:
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field '{field}' must be an ISO 8601 datetime string")
    return dt


def get_or_404(collection, rid):
    e = db[collection].get(rid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Resource '{rid}' does not exist")
    return e


# =========================================================================
# Domain constants and calculation helpers
# =========================================================================
MATERIALS = {"CAST_IRON", "DUCTILE_IRON", "PVC", "AC", "STEEL"}
BREAK_SOURCES = {"CUSTOMER_CALL", "SENSOR_SCADA", "CREW_OBSERVATION"}
BREAK_TYPES = {"CIRCUMFERENTIAL", "SPLIT", "BLOWOUT"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
ANOMALY_TYPES = {"PRESSURE_DROP", "FLOW_SPIKE"}
EQUIPMENT_CLASSES = {"LIGHT", "HEAVY"}
CONTROL_PLANS = {"LANE_CLOSURE", "FULL_CLOSURE", "FLAGGING"}
COLIFORM_RESULTS = {"PASS", "FAIL"}

ADVISORY_OUTAGE_THRESHOLD = 500
MIN_CHLORINE_MG_L = Decimal("0.20")
MIN_SAMPLE_SPACING = timedelta(hours=20)
CLAIM_FILING_WINDOW = timedelta(days=90)
RESTORATION_DEADLINE = timedelta(days=14)
CORRELATION_WINDOW = timedelta(hours=6)
TRAVEL_BUFFER = timedelta(minutes=60)
REPEAT_WINDOW_MONTHS = 36

OFFICIAL_STATES = {"REPAIRED", "RESTORED", "CLOSED"}
PROVISIONAL_STATES = {"CONFIRMED", "ISOLATED", "IN_REPAIR",
                      "REPAIRED", "RESTORED", "CLOSED"}
ACTIVE_WO_STATES = {"DRAFT", "DISPATCHED", "ON_SITE"}

RATE_PER_FT = [(8, 12000), (16, 18000), (None, 25000)]  # d<8, d<=16, d>16
TYPE_MULTIPLIER = {"CIRCUMFERENTIAL": Decimal("1.0"),
                   "SPLIT": Decimal("1.25"), "BLOWOUT": Decimal("1.6")}
KIT_FEE = {"CIRCUMFERENTIAL": 40000, "SPLIT": 85000, "BLOWOUT": 150000}
EST_HOURS = {"CIRCUMFERENTIAL": 4, "SPLIT": 6, "BLOWOUT": 10}
MATERIAL_WASTE_FACTOR = Decimal("1.10")


def rate_per_ft(diameter):
    if diameter < 8:
        return 12000
    if diameter <= 16:
        return 18000
    return 25000


def round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_break_rollups(b):
    bid = b["id"]
    repair = sum(w["actual_cost_cents"] or 0
                 for w in db["work_orders"].values()
                 if w["break_report_id"] == bid and w["work_status"] == "REPAIR_COMPLETE")
    wo_ids = {w["id"] for w in db["work_orders"].values()
              if w["break_report_id"] == bid}
    restoration = sum(j["patch_cost_cents"] or 0
                      for j in db["restoration_jobs"].values()
                      if j["work_order_id"] in wo_ids
                      and j["restoration_status"] == "COMPLETED")
    liability = sum(c["approved_amount_cents"] or 0
                    for c in db["damage_claims"].values()
                    if c["break_report_id"] == bid and c["claim_status"] == "APPROVED")
    paid = sum(c["approved_amount_cents"] or 0
               for c in db["damage_claims"].values()
               if c["break_report_id"] == bid and c["claim_status"] == "PAID")
    b["total_repair_cost_cents"] = repair
    b["total_restoration_cost_cents"] = restoration
    b["claims_liability_cents"] = liability
    b["total_claims_paid_cents"] = paid
    b["total_cost_cents"] = repair + restoration + paid


def recompute_segment_counts(seg, derive_condition):
    """Recompute 36-month repeat-break counts at the logical clock now.

    derive_condition: only True on ops runs (confirm recomputes counts only).
    Returns True when the segment record changed (version then bumped).
    """
    now = clock_now()
    window_start = subtract_months(now, REPEAT_WINDOW_MONTHS)
    official = 0
    provisional = 0
    for b in db["break_reports"].values():
        if b["pipe_segment_id"] != seg["id"]:
            continue
        ca = b["confirmed_at"]
        if ca is None or not (window_start <= ca <= now):
            continue
        st = b["break_status"]
        if st in OFFICIAL_STATES:
            official += 1
        if st in PROVISIONAL_STATES:
            provisional += 1
    changed = False
    if seg["repeat_break_count_36mo"] != official:
        seg["repeat_break_count_36mo"] = official
        changed = True
    if seg["provisional_break_count_36mo"] != provisional:
        seg["provisional_break_count_36mo"] = provisional
        changed = True
    if derive_condition and seg["condition_status"] not in ("PROGRAMMED", "REPLACED"):
        if official >= 3:
            target = "CANDIDATE"
        elif official == 2:
            target = "WATCH"
        else:
            target = "NONE"
        if seg["condition_status"] != target:
            seg["condition_status"] = target
            changed = True
    if changed:
        touch(seg)
    return changed


def crew_window_overlap(crew_id, t):
    """Occupied interval [window_start, window_end + 60min), closed start."""
    for w in db["work_orders"].values():
        if w["crew_id"] != crew_id or w["work_status"] not in ("DISPATCHED", "ON_SITE"):
            continue
        ws = w["dispatch_window_start"]
        we = w["dispatch_window_end"]
        if ws is None or we is None:
            continue
        if ws <= t < we + TRAVEL_BUFFER:
            return True
    return False


def equipment_sufficient(crew, required_class):
    if required_class == "LIGHT":
        return True
    return crew["equipment_class"] == "HEAVY"


def crew_eligible(crew, required_class, t):
    return (crew["crew_status"] == "AVAILABLE"
            and equipment_sufficient(crew, required_class)
            and not crew_window_overlap(crew["id"], t))


def zone_dedup_extent(valves):
    zones = {}
    for v in valves:
        z = v["coverage_zone"]
        zones[z] = max(zones.get(z, 0), v["customers_served"])
    return sum(zones.values())


def issued_advisory_for(break_id):
    for a in db["advisories"].values():
        if a["break_report_id"] == break_id and a["advisory_status"] == "ISSUED":
            return a
    return None


def maybe_auto_advisory(b, extent):
    if extent >= ADVISORY_OUTAGE_THRESHOLD and issued_advisory_for(b["id"]) is None:
        adv = new_entity()
        adv.update({
            "break_report_id": b["id"],
            "issue_reason": "AUTO_OUTAGE_THRESHOLD",
            "advisory_status": "ISSUED",
            "issued_by_user_id": "system",
            "lifted_by_user_id": None,
            "issued_at": clock_now(),
            "lifted_at": None,
            "consecutive_pass_count": 0,
            "last_sample_at": None,
        })
        db["advisories"][adv["id"]] = adv


# =========================================================================
# PipeSegment routes
# =========================================================================
@app.route("/pipe-segments", methods=["POST"])
def create_pipe_segment():
    auth_user(["PublicWorksEngineer"])
    body = body_json()
    segment_ref = v_str(body, "segment_ref")
    material = v_enum(body, "material", MATERIALS)
    diameter = v_int(body, "diameter_inches", minimum=1)
    install_year = v_int(body, "install_year")
    for s in db["pipe_segments"].values():
        if s["segment_ref"] == segment_ref:
            raise ApiError("ERR_VALIDATION", 400,
                           f"segment_ref '{segment_ref}' already exists")
    seg = new_entity()
    seg.update({
        "segment_ref": segment_ref,
        "material": material,
        "diameter_inches": diameter,
        "install_year": install_year,
        "condition_status": "NONE",
        "repeat_break_count_36mo": 0,
        "provisional_break_count_36mo": 0,
        "replaced_at": None,
    })
    db["pipe_segments"][seg["id"]] = seg
    return ok_object(ser(seg), 201)


@app.route("/pipe-segments/<sid>", methods=["GET"])
def get_pipe_segment(sid):
    auth_user(ALL_ROLES)
    return ok_object(ser(get_or_404("pipe_segments", sid)))


@app.route("/pipe-segments/<sid>/valves", methods=["GET"])
def list_segment_valves(sid):
    auth_user(ALL_ROLES)
    get_or_404("pipe_segments", sid)
    rows = [v for v in db["valves"].values() if v["pipe_segment_id"] == sid]
    return ok_list([ser(v) for v in sorted_rows(rows)])


@app.route("/pipe-segments/<sid>/pressure-anomalies", methods=["GET"])
def list_segment_anomalies(sid):
    auth_user(ALL_ROLES)
    get_or_404("pipe_segments", sid)
    rows = [a for a in db["pressure_anomalies"].values()
            if a["pipe_segment_id"] == sid]
    return ok_list([ser(a) for a in sorted_rows(rows)])


@app.route("/pipe-segments/<sid>/break-reports", methods=["GET"])
def list_segment_breaks(sid):
    auth_user(ALL_ROLES)
    get_or_404("pipe_segments", sid)
    rows = [b for b in db["break_reports"].values()
            if b["pipe_segment_id"] == sid]
    return ok_list([ser(b) for b in sorted_rows(rows)])


@app.route("/pipe-segments/<sid>/program-replacement", methods=["POST"])
def program_replacement(sid):
    auth_user(["PublicWorksEngineer"])
    seg = get_or_404("pipe_segments", sid)
    if seg["condition_status"] != "CANDIDATE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CANDIDATE segment can be programmed for replacement")
    seg["condition_status"] = "PROGRAMMED"
    touch(seg)
    return ok_object(ser(seg))


@app.route("/pipe-segments/<sid>/mark-replaced", methods=["POST"])
def mark_replaced(sid):
    auth_user(["PublicWorksEngineer"])
    seg = get_or_404("pipe_segments", sid)
    if seg["condition_status"] != "PROGRAMMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROGRAMMED segment can be marked replaced")
    seg["condition_status"] = "REPLACED"
    seg["replaced_at"] = clock_now()
    touch(seg)
    return ok_object(ser(seg))


# =========================================================================
# Valve routes
# =========================================================================
@app.route("/valves", methods=["POST"])
def create_valve():
    auth_user(["PublicWorksEngineer"])
    body = body_json()
    valve_code = v_str(body, "valve_code")
    pipe_segment_id = v_str(body, "pipe_segment_id")
    coverage_zone = v_str(body, "coverage_zone")
    customers_served = v_int(body, "customers_served", minimum=1)
    get_or_404("pipe_segments", pipe_segment_id)
    for v in db["valves"].values():
        if v["valve_code"] == valve_code:
            raise ApiError("ERR_VALIDATION", 400,
                           f"valve_code '{valve_code}' already exists")
    valve = new_entity()
    valve.update({
        "valve_code": valve_code,
        "pipe_segment_id": pipe_segment_id,
        "coverage_zone": coverage_zone,
        "customers_served": customers_served,
        "valve_status": "OPEN",
    })
    db["valves"][valve["id"]] = valve
    return ok_object(ser(valve), 201)


# =========================================================================
# PressureAnomaly routes
# =========================================================================
@app.route("/pressure-anomalies", methods=["POST"])
def create_pressure_anomaly():
    auth_user(["System"])
    body = body_json()
    pipe_segment_id = v_str(body, "pipe_segment_id")
    anomaly_type = v_enum(body, "anomaly_type", ANOMALY_TYPES)
    observed_at = v_dt(body, "observed_at")
    magnitude_pct = v_int(body, "magnitude_pct", minimum=1, maximum=100)
    get_or_404("pipe_segments", pipe_segment_id)
    a = new_entity()
    a.update({
        "pipe_segment_id": pipe_segment_id,
        "anomaly_type": anomaly_type,
        "observed_at": observed_at,
        "magnitude_pct": magnitude_pct,
        "correlated_break_report_id": None,
        "correlation_status": "UNCORRELATED",
    })
    db["pressure_anomalies"][a["id"]] = a
    return ok_object(ser(a), 201)


# =========================================================================
# BreakReport routes
# =========================================================================
@app.route("/break-reports", methods=["POST"])
def create_break_report():
    auth_user(["Dispatcher"])
    body = body_json()
    location_description = v_str(body, "location_description")
    source = v_enum(body, "source", BREAK_SOURCES)
    b = new_entity()
    b.update({
        "location_description": location_description,
        "source": source,
        "pipe_segment_id": None,
        "break_type": None,
        "severity": None,
        "break_status": "REPORTED",
        "confirmed_at": None,
        "repaired_at": None,
        "customers_out_of_service": 0,
        "total_repair_cost_cents": 0,
        "total_restoration_cost_cents": 0,
        "claims_liability_cents": 0,
        "total_claims_paid_cents": 0,
        "total_cost_cents": 0,
    })
    db["break_reports"][b["id"]] = b
    return ok_object(ser(b), 201)


@app.route("/break-reports/<bid>", methods=["GET"])
def get_break_report(bid):
    auth_user(ALL_ROLES)
    return ok_object(ser(get_or_404("break_reports", bid)))


@app.route("/break-reports/<bid>/confirm", methods=["POST"])
def confirm_break_report(bid):
    auth_user(["Dispatcher"])
    b = get_or_404("break_reports", bid)
    body = body_json()
    pipe_segment_id = v_str(body, "pipe_segment_id")
    break_type = v_enum(body, "break_type", BREAK_TYPES)
    severity = v_enum(body, "severity", SEVERITIES)
    seg = get_or_404("pipe_segments", pipe_segment_id)
    if b["break_status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REPORTED break report can be confirmed")
    if seg["condition_status"] == "REPLACED":
        raise ApiError("ERR_SEGMENT_REPLACED", 409,
                       "Cannot confirm a break against a REPLACED segment")
    b["break_status"] = "CONFIRMED"
    b["pipe_segment_id"] = pipe_segment_id
    b["break_type"] = break_type
    b["severity"] = severity
    b["confirmed_at"] = clock_now()
    touch(b)
    # Newly confirmed break is immediately visible to the segment's
    # provisional count (condition posture itself is ops-run derived only).
    recompute_segment_counts(seg, derive_condition=False)
    return ok_object(ser(b))


@app.route("/break-reports/<bid>/false-alarm", methods=["POST"])
def false_alarm_break_report(bid):
    auth_user(["Dispatcher"])
    b = get_or_404("break_reports", bid)
    if b["break_status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REPORTED break report can be marked false alarm")
    b["break_status"] = "FALSE_ALARM"
    touch(b)
    return ok_object(ser(b))


@app.route("/break-reports/<bid>/correlate", methods=["POST"])
def correlate_break_report(bid):
    auth_user(["Dispatcher"])
    b = get_or_404("break_reports", bid)
    body = body_json()
    anomaly_id = v_str(body, "pressure_anomaly_id")
    a = get_or_404("pressure_anomalies", anomaly_id)
    if b["break_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Break report must be CONFIRMED to correlate an anomaly")
    if a["correlation_status"] != "UNCORRELATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Anomaly is already correlated")
    if a["pipe_segment_id"] != b["pipe_segment_id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH", 409,
                       "Anomaly's segment differs from the break's segment")
    if abs(a["observed_at"] - b["created_at"]) > CORRELATION_WINDOW:
        raise ApiError("ERR_CORRELATION_WINDOW", 409,
                       "Anomaly observed more than 6 hours from break creation")
    a["correlated_break_report_id"] = b["id"]
    a["correlation_status"] = "CORRELATED"
    touch(a)
    return ok_object(ser(a))


@app.route("/break-reports/<bid>/close", methods=["POST"])
def close_break_report(bid):
    auth_user(["PublicWorksEngineer"])
    b = get_or_404("break_reports", bid)
    if b["break_status"] != "RESTORED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a RESTORED break report can be closed")
    if issued_advisory_for(b["id"]) is not None:
        raise ApiError("ERR_ADVISORY_STILL_ACTIVE", 409,
                       "An ISSUED advisory still exists for this break")
    for c in db["damage_claims"].values():
        if (c["break_report_id"] == b["id"]
                and c["claim_status"] in ("SUBMITTED", "APPROVED")):
            raise ApiError("ERR_CLAIMS_OPEN", 409,
                           "Open (SUBMITTED or APPROVED) claims exist for this break")
    b["break_status"] = "CLOSED"
    touch(b)
    return ok_object(ser(b))


@app.route("/break-reports/<bid>/isolation-events", methods=["GET"])
def list_break_isolations(bid):
    auth_user(ALL_ROLES)
    get_or_404("break_reports", bid)
    rows = [e for e in db["isolation_events"].values()
            if e["break_report_id"] == bid]
    return ok_list([ser(e) for e in sorted_rows(rows)])


@app.route("/break-reports/<bid>/pressure-anomalies", methods=["GET"])
def list_break_anomalies(bid):
    auth_user(ALL_ROLES)
    get_or_404("break_reports", bid)
    rows = [a for a in db["pressure_anomalies"].values()
            if a["correlated_break_report_id"] == bid]
    return ok_list([ser(a) for a in sorted_rows(rows)])


@app.route("/break-reports/<bid>/work-orders", methods=["GET"])
def list_break_work_orders(bid):
    auth_user(ALL_ROLES)
    get_or_404("break_reports", bid)
    rows = [w for w in db["work_orders"].values() if w["break_report_id"] == bid]
    return ok_list([ser(w) for w in sorted_rows(rows)])


@app.route("/break-reports/<bid>/advisories", methods=["GET"])
def list_break_advisories(bid):
    auth_user(ALL_ROLES)
    get_or_404("break_reports", bid)
    rows = [a for a in db["advisories"].values() if a["break_report_id"] == bid]
    return ok_list([ser(a) for a in sorted_rows(rows)])


@app.route("/break-reports/<bid>/traffic-permits", methods=["GET"])
def list_break_permits(bid):
    auth_user(ALL_ROLES)
    get_or_404("break_reports", bid)
    rows = [p for p in db["traffic_permits"].values()
            if p["break_report_id"] == bid]
    return ok_list([ser(p) for p in sorted_rows(rows)])


@app.route("/break-reports/<bid>/damage-claims", methods=["GET"])
def list_break_claims(bid):
    auth_user(ALL_ROLES)
    get_or_404("break_reports", bid)
    rows = [c for c in db["damage_claims"].values()
            if c["break_report_id"] == bid]
    return ok_list([ser(c) for c in sorted_rows(rows)])


# =========================================================================
# IsolationEvent routes
# =========================================================================
@app.route("/isolation-events", methods=["POST"])
def create_isolation_event():
    auth_user(["Dispatcher"])
    body = body_json()
    break_report_id = v_str(body, "break_report_id")
    valve_ids = body.get("valve_ids")
    if (not isinstance(valve_ids, list) or not valve_ids
            or any(not isinstance(x, str) or not x for x in valve_ids)):
        raise ApiError("ERR_VALIDATION", 400,
                       "Field 'valve_ids' must be a non-empty array of valve id strings")
    expected = body.get("expected_break_report_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 400,
                       "Field 'expected_break_report_version' is required and must be an integer")
    b = get_or_404("break_reports", break_report_id)
    if expected != b["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_break_report_version does not match the break's current version")
    if b["break_status"] not in ("CONFIRMED", "REPAIRED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Isolation can only be planned for a CONFIRMED or REPAIRED break")
    for e in db["isolation_events"].values():
        if e["break_report_id"] == b["id"] and e["isolation_status"] == "PLANNED":
            e["isolation_status"] = "SUPERSEDED"
            touch(e)
    ev = new_entity()
    ev.update({
        "break_report_id": b["id"],
        "valve_ids": list(valve_ids),
        "outage_extent_customers": None,
        "isolation_status": "PLANNED",
        "executed_at": None,
        "restored_at": None,
    })
    db["isolation_events"][ev["id"]] = ev
    touch(b)  # plan creation legitimately advances the break's version
    return ok_object(ser(ev), 201)


@app.route("/isolation-events/<iid>/execute", methods=["POST"])
def execute_isolation_event(iid):
    auth_user(["Dispatcher"])
    ev = get_or_404("isolation_events", iid)
    if ev["isolation_status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PLANNED isolation event can be executed")
    b = db["break_reports"][ev["break_report_id"]]
    if b["break_status"] not in ("CONFIRMED", "REPAIRED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Parent break must be CONFIRMED or REPAIRED to execute an isolation")
    valves = []
    seen = set()
    for vid in ev["valve_ids"]:
        if vid in seen:
            continue
        seen.add(vid)
        valves.append(get_or_404("valves", vid))
    for v in valves:
        if v["pipe_segment_id"] != b["pipe_segment_id"]:
            raise ApiError("ERR_CROSS_REFERENCE_MISMATCH", 409,
                           f"Valve '{v['id']}' does not serve the break's segment")
    for v in valves:
        if v["valve_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409,
                           f"Valve '{v['id']}' is not OPEN")
    for v in valves:
        v["valve_status"] = "CLOSED"
        touch(v)
    extent = zone_dedup_extent(valves)
    ev["outage_extent_customers"] = extent
    ev["executed_at"] = clock_now()
    ev["isolation_status"] = "EXECUTED"
    touch(ev)
    b["break_status"] = "ISOLATED"
    b["customers_out_of_service"] = extent
    touch(b)
    maybe_auto_advisory(b, extent)
    return ok_object(ser(ev))


# =========================================================================
# Crew routes
# =========================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    auth_user(["Dispatcher"])
    body = body_json()
    crew_name = v_str(body, "crew_name")
    crew_size = v_int(body, "crew_size", minimum=1)
    equipment_class = v_enum(body, "equipment_class", EQUIPMENT_CLASSES)
    hourly_rate_cents = v_int(body, "hourly_rate_cents", minimum=1)
    for c in db["crews"].values():
        if c["crew_name"] == crew_name:
            raise ApiError("ERR_VALIDATION", 400,
                           f"crew_name '{crew_name}' already exists")
    c = new_entity()
    c.update({
        "crew_name": crew_name,
        "crew_size": crew_size,
        "equipment_class": equipment_class,
        "hourly_rate_cents": hourly_rate_cents,
        "crew_status": "AVAILABLE",
        "completed_job_count": 0,
    })
    db["crews"][c["id"]] = c
    return ok_object(ser(c), 201)


@app.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    auth_user(ALL_ROLES)
    return ok_object(ser(get_or_404("crews", cid)))


# =========================================================================
# WorkOrder routes
# =========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    auth_user(["Dispatcher"])
    body = body_json()
    break_report_id = v_str(body, "break_report_id")
    est_pipe_length_ft = v_int(body, "est_pipe_length_ft", minimum=1)
    b = get_or_404("break_reports", break_report_id)
    if b["break_status"] not in ("CONFIRMED", "ISOLATED", "REPAIRED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Work orders require the break to be CONFIRMED, ISOLATED, or REPAIRED")
    for w in db["work_orders"].values():
        if (w["break_report_id"] == b["id"]
                and w["work_status"] in ACTIVE_WO_STATES):
            raise ApiError("ERR_DUPLICATE_ACTIVE_WORK_ORDER", 409,
                           "Break already has an active work order")
    seg = db["pipe_segments"][b["pipe_segment_id"]]
    d = seg["diameter_inches"]
    required_equipment_class = (
        "HEAVY" if (d > 12 or b["break_type"] == "BLOWOUT") else "LIGHT")
    required_clamp_kit = "CLAMP_A" if d < 8 else ("CLAMP_B" if d <= 16 else "CLAMP_C")
    w = new_entity()
    w.update({
        "break_report_id": b["id"],
        "est_pipe_length_ft": est_pipe_length_ft,
        "crew_id": None,
        "work_status": "DRAFT",
        "required_equipment_class": required_equipment_class,
        "required_clamp_kit": required_clamp_kit,
        "estimated_cost_cents": None,
        "actual_cost_cents": None,
        "cost_variance_cents": None,
        "dispatch_window_start": None,
        "dispatch_window_end": None,
    })
    db["work_orders"][w["id"]] = w
    return ok_object(ser(w), 201)


@app.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    auth_user(ALL_ROLES)
    return ok_object(ser(get_or_404("work_orders", wid)))


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    auth_user(ALL_ROLES)
    break_filter = request.args.get("break_report_id")
    crew_filter = request.args.get("crew_id")
    rows = list(db["work_orders"].values())
    if break_filter is not None:
        rows = [w for w in rows if w["break_report_id"] == break_filter]
    if crew_filter is not None:
        rows = [w for w in rows if w["crew_id"] == crew_filter]
    return ok_list([ser(w) for w in sorted_rows(rows)])


@app.route("/work-orders/<wid>/dispatch", methods=["POST"])
def dispatch_work_order(wid):
    auth_user(["Dispatcher"])
    w = get_or_404("work_orders", wid)
    body = body_json()
    crew_id = body.get("crew_id")
    if crew_id is not None and not isinstance(crew_id, str):
        raise ApiError("ERR_VALIDATION", 400, "Field 'crew_id' must be a string")
    explicit_crew = None
    if crew_id:
        explicit_crew = get_or_404("crews", crew_id)
    if w["work_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT work order can be dispatched")
    b = db["break_reports"][w["break_report_id"]]
    now = clock_now()
    if explicit_crew is not None:
        # Crew-related ineligibility (temporal tier) precedes the
        # break-isolation structural guard per the validation ordering.
        if not crew_eligible(explicit_crew, w["required_equipment_class"], now):
            raise ApiError("ERR_CREW_DOUBLE_BOOKED", 409,
                           "Named crew is not available for this dispatch")
        crew = explicit_crew
    else:
        if b["break_status"] != "ISOLATED":
            raise ApiError("ERR_BREAK_NOT_ISOLATED", 409,
                           "Work order can only be dispatched while the break is ISOLATED")
        pool = [c for c in db["crews"].values()
                if crew_eligible(c, w["required_equipment_class"], now)]
        if not pool:
            raise ApiError("ERR_NO_CREW_AVAILABLE", 409,
                           "No AVAILABLE crew with sufficient equipment class and a free window")
        pool.sort(key=lambda c: (c["completed_job_count"], c["created_at"], c["_seq"]))
        crew = pool[0]
    if explicit_crew is not None and b["break_status"] != "ISOLATED":
        raise ApiError("ERR_BREAK_NOT_ISOLATED", 409,
                       "Work order can only be dispatched while the break is ISOLATED")
    est_hours = EST_HOURS[b["break_type"]]
    seg = db["pipe_segments"][b["pipe_segment_id"]]
    product = (Decimal(w["est_pipe_length_ft"]) * Decimal(rate_per_ft(seg["diameter_inches"]))
               * TYPE_MULTIPLIER[b["break_type"]])
    estimated = (round_half_up_cents(product)
                 + KIT_FEE[b["break_type"]]
                 + crew["hourly_rate_cents"] * est_hours)
    w["crew_id"] = crew["id"]
    w["work_status"] = "DISPATCHED"
    w["dispatch_window_start"] = now
    w["dispatch_window_end"] = now + timedelta(hours=est_hours)
    w["estimated_cost_cents"] = estimated
    touch(w)
    crew["crew_status"] = "DISPATCHED"
    touch(crew)
    return ok_object(ser(w))


def _crew_ownership_check(uid, w):
    if w["crew_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Acting CrewLead's X-User-ID must equal the work order's crew_id")


@app.route("/work-orders/<wid>/arrive", methods=["POST"])
def arrive_work_order(wid):
    uid = auth_user(["CrewLead"])
    w = get_or_404("work_orders", wid)
    _crew_ownership_check(uid, w)
    if w["work_status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DISPATCHED work order can be marked on site")
    w["work_status"] = "ON_SITE"
    touch(w)
    b = db["break_reports"][w["break_report_id"]]
    if b["break_status"] == "ISOLATED":
        b["break_status"] = "IN_REPAIR"
        touch(b)
    return ok_object(ser(w))


@app.route("/work-orders/<wid>/complete", methods=["POST"])
def complete_work_order(wid):
    uid = auth_user(["CrewLead"])
    w = get_or_404("work_orders", wid)
    _crew_ownership_check(uid, w)
    body = body_json()
    v_num(body, "actual_pipe_length_ft", minimum=0, exclusive_min=True)
    labor_hours = v_num(body, "labor_hours", minimum=0)
    materials_used = body.get("materials_used")
    if not isinstance(materials_used, list):
        raise ApiError("ERR_VALIDATION", 400,
                       "Field 'materials_used' is required and must be an array")
    lines = []
    for item in materials_used:
        if not isinstance(item, dict):
            raise ApiError("ERR_VALIDATION", 400,
                           "Each materials_used line must be an object")
        if ("quantity" not in item or isinstance(item["quantity"], bool)
                or not isinstance(item["quantity"], (int, float))
                or not math.isfinite(item["quantity"]) or item["quantity"] <= 0):
            raise ApiError("ERR_VALIDATION", 400,
                           "Each materials_used line requires a positive numeric 'quantity'")
        up = item.get("unit_price_cents")
        if isinstance(up, bool) or not isinstance(up, int) or up < 0:
            raise ApiError("ERR_VALIDATION", 400,
                           "Each materials_used line requires a non-negative integer 'unit_price_cents'")
        lines.append((item["quantity"], up))
    if w["work_status"] != "ON_SITE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ON_SITE work order can be completed")
    crew = db["crews"][w["crew_id"]]
    labor_cents = round_half_up_cents(
        Decimal(str(labor_hours)) * Decimal(crew["hourly_rate_cents"]))
    materials_cents = sum(
        round_half_up_cents(Decimal(str(q)) * Decimal(up) * MATERIAL_WASTE_FACTOR)
        for q, up in lines)
    actual = labor_cents + materials_cents
    w["actual_cost_cents"] = actual
    w["cost_variance_cents"] = actual - (w["estimated_cost_cents"] or 0)
    w["work_status"] = "REPAIR_COMPLETE"
    touch(w)
    crew["crew_status"] = "AVAILABLE"
    crew["completed_job_count"] += 1
    touch(crew)
    b = db["break_reports"][w["break_report_id"]]
    now = clock_now()
    b["break_status"] = "REPAIRED"
    b["repaired_at"] = now
    b["customers_out_of_service"] = 0
    # Restore the break's EXECUTED isolation: valves reopen.
    for ev in db["isolation_events"].values():
        if (ev["break_report_id"] == b["id"]
                and ev["isolation_status"] == "EXECUTED"):
            ev["isolation_status"] = "RESTORED"
            ev["restored_at"] = now
            touch(ev)
            for vid in dict.fromkeys(ev["valve_ids"]):
                v = db["valves"].get(vid)
                if v is not None and v["valve_status"] != "OPEN":
                    v["valve_status"] = "OPEN"
                    touch(v)
    recompute_break_rollups(b)
    touch(b)
    # Auto-create the PENDING restoration job for the completed work order.
    job = new_entity()
    job.update({
        "work_order_id": w["id"],
        "restoration_status": "PENDING",
        "scheduled_start": None,
        "scheduled_end": None,
        "traffic_permit_id": None,
        "patch_cost_cents": None,
        "completed_at": None,
    })
    db["restoration_jobs"][job["id"]] = job
    return ok_object(ser(w))


@app.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel_work_order(wid):
    auth_user(["Dispatcher"])
    w = get_or_404("work_orders", wid)
    if w["work_status"] not in ("DRAFT", "DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT or DISPATCHED work order can be cancelled")
    if w["work_status"] == "DISPATCHED" and w["crew_id"] is not None:
        crew = db["crews"].get(w["crew_id"])
        if crew is not None and crew["crew_status"] != "AVAILABLE":
            crew["crew_status"] = "AVAILABLE"
            touch(crew)
        w["dispatch_window_start"] = None
        w["dispatch_window_end"] = None
    w["work_status"] = "CANCELLED"
    touch(w)
    return ok_object(ser(w))


# =========================================================================
# BoilWaterAdvisory / WaterQualityTest routes
# =========================================================================
@app.route("/boil-water-advisories", methods=["POST"])
def create_advisory():
    uid = auth_user(["WaterQualityOfficer"])
    body = body_json()
    break_report_id = v_str(body, "break_report_id")
    b = get_or_404("break_reports", break_report_id)
    if b["break_status"] not in ("CONFIRMED", "ISOLATED", "IN_REPAIR", "REPAIRED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Advisories require the break to be CONFIRMED, ISOLATED, IN_REPAIR, or REPAIRED")
    if issued_advisory_for(b["id"]) is not None:
        raise ApiError("ERR_ADVISORY_ALREADY_OPEN", 409,
                       "An ISSUED advisory already exists for this break")
    adv = new_entity()
    adv.update({
        "break_report_id": b["id"],
        "issue_reason": "MANUAL",
        "advisory_status": "ISSUED",
        "issued_by_user_id": uid,
        "lifted_by_user_id": None,
        "issued_at": clock_now(),
        "lifted_at": None,
        "consecutive_pass_count": 0,
        "last_sample_at": None,
    })
    db["advisories"][adv["id"]] = adv
    return ok_object(ser(adv), 201)


@app.route("/boil-water-advisories/<aid>", methods=["GET"])
def get_advisory(aid):
    auth_user(ALL_ROLES)
    return ok_object(ser(get_or_404("advisories", aid)))


@app.route("/boil-water-advisories/<aid>/lift", methods=["POST"])
def lift_advisory(aid):
    uid = auth_user(["WaterQualityOfficer"])
    adv = get_or_404("advisories", aid)
    if adv["advisory_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ISSUED advisory can be lifted")
    if adv["consecutive_pass_count"] < 2:
        raise ApiError("ERR_ADVISORY_TESTS_INSUFFICIENT", 409,
                       "Advisory lift requires consecutive_pass_count >= 2")
    if uid == adv["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "The officer who issued an advisory may not lift it")
    adv["advisory_status"] = "LIFTED"
    adv["lifted_at"] = clock_now()
    adv["lifted_by_user_id"] = uid
    touch(adv)
    return ok_object(ser(adv))


@app.route("/water-quality-tests", methods=["POST"])
def create_wq_test():
    auth_user(["WaterQualityOfficer"])
    body = body_json()
    advisory_id = v_str(body, "advisory_id")
    sampled_at = v_dt(body, "sampled_at")
    chlorine = body.get("chlorine_residual_mg_l")
    if (isinstance(chlorine, bool) or not isinstance(chlorine, (int, float))
            or not math.isfinite(chlorine)):
        raise ApiError("ERR_VALIDATION", 400,
                       "Field 'chlorine_residual_mg_l' is required and must be a number")
    coliform_result = v_enum(body, "coliform_result", COLIFORM_RESULTS)
    adv = get_or_404("advisories", advisory_id)
    if adv["advisory_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Samples can only be recorded against an ISSUED advisory")
    if sampled_at < adv["issued_at"]:
        raise ApiError("ERR_VALIDATION", 400,
                       "sampled_at must not be earlier than the advisory's issued_at")
    if (adv["last_sample_at"] is not None
            and sampled_at < adv["last_sample_at"] + MIN_SAMPLE_SPACING):
        raise ApiError("ERR_TEST_SAMPLE_TOO_SOON", 409,
                       "Samples on the same advisory must be at least 20 hours apart")
    outcome = ("PASS" if (coliform_result == "PASS"
                          and Decimal(str(chlorine)) >= MIN_CHLORINE_MG_L)
               else "FAIL")
    t = new_entity()
    t.update({
        "advisory_id": adv["id"],
        "sampled_at": sampled_at,
        "chlorine_residual_mg_l": chlorine,
        "coliform_result": coliform_result,
        "test_outcome": outcome,
    })
    db["wq_tests"][t["id"]] = t
    if outcome == "PASS":
        adv["consecutive_pass_count"] += 1
    else:
        adv["consecutive_pass_count"] = 0
    adv["last_sample_at"] = sampled_at
    touch(adv)
    return ok_object(ser(t), 201)


@app.route("/boil-water-advisories/<aid>/tests", methods=["GET"])
def list_advisory_tests(aid):
    auth_user(ALL_ROLES)
    get_or_404("advisories", aid)
    rows = [t for t in db["wq_tests"].values() if t["advisory_id"] == aid]
    return ok_list([ser(t) for t in sorted_rows(rows)])


# =========================================================================
# RestorationJob routes
# =========================================================================
@app.route("/restoration-jobs/<jid>", methods=["GET"])
def get_restoration_job(jid):
    auth_user(ALL_ROLES)
    return ok_object(ser(get_or_404("restoration_jobs", jid)))


@app.route("/restoration-jobs", methods=["GET"])
def list_restoration_jobs():
    auth_user(ALL_ROLES)
    wo_filter = request.args.get("work_order_id")
    permit_filter = request.args.get("traffic_permit_id")
    rows = list(db["restoration_jobs"].values())
    if wo_filter is not None:
        rows = [j for j in rows if j["work_order_id"] == wo_filter]
    if permit_filter is not None:
        rows = [j for j in rows if j["traffic_permit_id"] == permit_filter]
    return ok_list([ser(j) for j in sorted_rows(rows)])


@app.route("/restoration-jobs/<jid>/schedule", methods=["POST"])
def schedule_restoration_job(jid):
    auth_user(["Dispatcher"])
    job = get_or_404("restoration_jobs", jid)
    body = body_json()
    scheduled_start = v_dt(body, "scheduled_start")
    scheduled_end = v_dt(body, "scheduled_end")
    traffic_permit_id = v_str(body, "traffic_permit_id")
    if scheduled_start >= scheduled_end:
        raise ApiError("ERR_VALIDATION", 400,
                       "scheduled_start must be before scheduled_end")
    permit = get_or_404("traffic_permits", traffic_permit_id)
    if job["restoration_status"] not in ("PENDING", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PENDING or OVERDUE restoration job can be scheduled")
    if permit["permit_status"] != "APPROVED":
        raise ApiError("ERR_PERMIT_NOT_APPROVED", 409,
                       "Referenced traffic permit is not APPROVED")
    wo = db["work_orders"][job["work_order_id"]]
    if permit["break_report_id"] != wo["break_report_id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH", 409,
                       "Permit belongs to a different break than the restoration job")
    if not (permit["valid_from"] <= scheduled_start
            and permit["valid_to"] >= scheduled_end):
        raise ApiError("ERR_PERMIT_WINDOW_MISMATCH", 409,
                       "Permit validity window does not fully cover the scheduled window")
    job["scheduled_start"] = scheduled_start
    job["scheduled_end"] = scheduled_end
    job["traffic_permit_id"] = traffic_permit_id
    job["restoration_status"] = "SCHEDULED"
    touch(job)
    return ok_object(ser(job))


@app.route("/restoration-jobs/<jid>/complete", methods=["POST"])
def complete_restoration_job(jid):
    auth_user(["Dispatcher"])
    job = get_or_404("restoration_jobs", jid)
    body = body_json()
    patch_cost_cents = body.get("patch_cost_cents")
    if isinstance(patch_cost_cents, bool) or not isinstance(patch_cost_cents, int):
        raise ApiError("ERR_VALIDATION", 400,
                       "Field 'patch_cost_cents' is required and must be an integer")
    if job["restoration_status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED or OVERDUE restoration job can be completed")
    if patch_cost_cents < 0:
        raise ApiError("ERR_INVALID_AMOUNT", 400,
                       "patch_cost_cents must be at least zero")
    job["restoration_status"] = "COMPLETED"
    job["patch_cost_cents"] = patch_cost_cents
    job["completed_at"] = clock_now()
    touch(job)
    wo = db["work_orders"][job["work_order_id"]]
    b = db["break_reports"][wo["break_report_id"]]
    recompute_break_rollups(b)
    wo_ids = {w["id"] for w in db["work_orders"].values()
              if w["break_report_id"] == b["id"]}
    all_completed = all(
        j["restoration_status"] == "COMPLETED"
        for j in db["restoration_jobs"].values()
        if j["work_order_id"] in wo_ids)
    if all_completed and b["break_status"] == "REPAIRED":
        b["break_status"] = "RESTORED"
    touch(b)
    return ok_object(ser(job))


# =========================================================================
# TrafficPermit routes
# =========================================================================
@app.route("/traffic-permits", methods=["POST"])
def create_traffic_permit():
    auth_user(["Dispatcher"])
    body = body_json()
    break_report_id = v_str(body, "break_report_id")
    street_block = v_str(body, "street_block")
    valid_from = v_dt(body, "valid_from")
    valid_to = v_dt(body, "valid_to")
    control_plan = v_enum(body, "control_plan", CONTROL_PLANS)
    if valid_from >= valid_to:
        raise ApiError("ERR_VALIDATION", 400, "valid_from must be before valid_to")
    get_or_404("break_reports", break_report_id)
    for p in db["traffic_permits"].values():
        if (p["street_block"] == street_block
                and p["permit_status"] in ("APPLIED", "APPROVED")
                and p["valid_from"] < valid_to
                and valid_from < p["valid_to"]):
            raise ApiError("ERR_PERMIT_OVERLAP", 409,
                           "Half-open overlap with an existing APPLIED/APPROVED permit on this street block")
    p = new_entity()
    p.update({
        "break_report_id": break_report_id,
        "street_block": street_block,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "control_plan": control_plan,
        "permit_status": "APPLIED",
    })
    db["traffic_permits"][p["id"]] = p
    return ok_object(ser(p), 201)


@app.route("/traffic-permits/<pid>/approve", methods=["POST"])
def approve_traffic_permit(pid):
    auth_user(["PublicWorksEngineer"])
    p = get_or_404("traffic_permits", pid)
    if p["permit_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPLIED permit can be approved")
    p["permit_status"] = "APPROVED"
    touch(p)
    return ok_object(ser(p))


# =========================================================================
# DamageClaim routes
# =========================================================================
@app.route("/damage-claims", methods=["POST"])
def create_damage_claim():
    auth_user(["Dispatcher"])
    body = body_json()
    break_report_id = v_str(body, "break_report_id")
    claimant_name = v_str(body, "claimant_name")
    claimed = body.get("claimed_amount_cents")
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise ApiError("ERR_VALIDATION", 400,
                       "Field 'claimed_amount_cents' is required and must be an integer")
    b = get_or_404("break_reports", break_report_id)
    if b["break_status"] in ("REPORTED", "FALSE_ALARM"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Claims require the break to be CONFIRMED or later")
    if clock_now() > b["confirmed_at"] + CLAIM_FILING_WINDOW:
        raise ApiError("ERR_CLAIM_FILED_LATE", 409,
                       "Claim filed more than 90 days after break confirmation")
    if claimed <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 400,
                       "claimed_amount_cents must be greater than zero")
    c = new_entity()
    c.update({
        "break_report_id": break_report_id,
        "claimant_name": claimant_name,
        "claimed_amount_cents": claimed,
        "claim_status": "SUBMITTED",
        "approved_amount_cents": None,
    })
    db["damage_claims"][c["id"]] = c
    return ok_object(ser(c), 201)


@app.route("/damage-claims/<cid>/approve", methods=["POST"])
def approve_damage_claim(cid):
    auth_user(["ClaimsAdjuster"])
    c = get_or_404("damage_claims", cid)
    body = body_json()
    approved = body.get("approved_amount_cents")
    if isinstance(approved, bool) or not isinstance(approved, int):
        raise ApiError("ERR_VALIDATION", 400,
                       "Field 'approved_amount_cents' is required and must be an integer")
    if c["claim_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED claim can be approved")
    if approved <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 400,
                       "approved_amount_cents must be greater than zero")
    if approved > c["claimed_amount_cents"]:
        raise ApiError("ERR_AMOUNT_EXCEEDS_CLAIMED", 409,
                       "approved_amount_cents must not exceed claimed_amount_cents")
    c["claim_status"] = "APPROVED"
    c["approved_amount_cents"] = approved
    touch(c)
    b = db["break_reports"][c["break_report_id"]]
    recompute_break_rollups(b)
    touch(b)
    return ok_object(ser(c))


@app.route("/damage-claims/<cid>/deny", methods=["POST"])
def deny_damage_claim(cid):
    auth_user(["ClaimsAdjuster"])
    c = get_or_404("damage_claims", cid)
    if c["claim_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED claim can be denied")
    c["claim_status"] = "DENIED"
    touch(c)
    return ok_object(ser(c))


@app.route("/damage-claims/<cid>/pay", methods=["POST"])
def pay_damage_claim(cid):
    auth_user(["ClaimsAdjuster"])
    c = get_or_404("damage_claims", cid)
    if c["claim_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED claim can be paid")
    c["claim_status"] = "PAID"
    touch(c)
    b = db["break_reports"][c["break_report_id"]]
    recompute_break_rollups(b)
    touch(b)
    return ok_object(ser(c))


@app.route("/damage-claims/<cid>/void", methods=["POST"])
def void_damage_claim(cid):
    auth_user(["ClaimsAdjuster"])
    c = get_or_404("damage_claims", cid)
    if c["claim_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED claim can be voided")
    c["claim_status"] = "VOIDED"
    touch(c)
    b = db["break_reports"][c["break_report_id"]]
    recompute_break_rollups(b)
    touch(b)
    return ok_object(ser(c))


# =========================================================================
# Logical clock and operations checkpoint
# =========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth_user(["System"])
    body = body_json()
    dt = v_dt(body, "to_iso8601")
    _clock["now"] = dt
    return ok_object({"current_utc": fmt_ts(dt)})


@app.route("/ops-runs", methods=["POST"])
def ops_run():
    auth_user(["System"])
    now = clock_now()
    expired_permit_ids = []
    for p in db["traffic_permits"].values():
        if (p["permit_status"] in ("APPLIED", "APPROVED")
                and p["valid_to"] <= now):
            p["permit_status"] = "EXPIRED"
            touch(p)
            expired_permit_ids.append(p["id"])
    overdue_restoration_ids = []
    for j in db["restoration_jobs"].values():
        if j["restoration_status"] not in ("PENDING", "SCHEDULED"):
            continue
        wo = db["work_orders"][j["work_order_id"]]
        b = db["break_reports"][wo["break_report_id"]]
        if (b["repaired_at"] is not None
                and b["repaired_at"] + RESTORATION_DEADLINE < now):
            j["restoration_status"] = "OVERDUE"
            touch(j)
            overdue_restoration_ids.append(j["id"])
    updated_segment_ids = []
    for seg in db["pipe_segments"].values():
        if seg["condition_status"] == "REPLACED":
            continue
        if recompute_segment_counts(seg, derive_condition=True):
            updated_segment_ids.append(seg["id"])
    return ok_object({
        "expired_permit_ids": expired_permit_ids,
        "overdue_restoration_ids": overdue_restoration_ids,
        "updated_segment_ids": updated_segment_ids,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
