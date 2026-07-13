"""Street Sweeping & Posted-Restriction Schedule API.

Flask + in-memory storage. State is wiped on every process start (per-test-server
isolation restarts this process before each test). No seeding at startup.
"""
import os
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"PublicWorksAdmin", "RouteDispatcher", "SignageInspector",
         "EnforcementOfficer", "Resident"}
ALL_ROLES = list(ROLES)

BASE_FINE_CENTS = 6000
FINE_CAP_CENTS = 20000
LBS_PER_TON = 2000
MAKEUP_OFFSET_DAYS = 7
SHIFT_BUFFER_MINUTES = 30

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (reset on every boot)
# ---------------------------------------------------------------------------
DB = {
    "routes": {}, "blocks": {}, "equipment": {}, "shifts": {},
    "sweep_events": {}, "suspensions": {}, "citations": {},
    "residents": {}, "complaints": {},
}
_SEQ = {"n": 0}
CLOCK = {"now": CLOCK_DEFAULT}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_dt():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# Time / formatting helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(now_dt())


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime value.")
    t = s.strip()
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "Invalid ISO8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid date value.")
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "Invalid YYYY-MM-DD date.")


def parse_hhmm(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "Invalid HH:MM time.")
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ApiError("ERR_VALIDATION", 422, "Invalid HH:MM time.")
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "Invalid HH:MM time.")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ApiError("ERR_VALIDATION", 422, "HH:MM out of range.")
    return h * 3600 + m * 60


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)  # 10^-places
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Errors and response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def success(data, code=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), code


def list_response(items, limit, offset, total):
    pag = {"limit": limit, "offset": offset, "total_count": total,
           "has_more": offset + len(items) < total}
    body = {"meta": _meta(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found."}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized credentials.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    return uid, role


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        b = request.get_json(force=True, silent=True)
    except Exception:
        b = None
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return b


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_present(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a non-empty string.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be one of {sorted(allowed)}.")
    return v


def require_int_field(body, field, minimum=None):
    v = body.get(field)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be >= {minimum}.")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a boolean.")
    return v


# ---------------------------------------------------------------------------
# Entity / mutation helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = now_iso()
    import uuid
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def get_or_404(store, _id, error_id):
    ent = DB[store].get(_id)
    if ent is None:
        raise ApiError(error_id, 404, f"Resource not found: {_id}")
    return ent


def paginate(query_items):
    """query_items: list already filtered. Returns (page, limit, offset, total)."""
    total = len(query_items)
    try:
        limit = request.args.get("limit")
        limit = 10 if limit is None else int(limit)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "limit must be an integer.")
    try:
        offset = request.args.get("offset")
        offset = 0 if offset is None else int(offset)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "offset must be an integer.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(query_items, key=lambda e: e["_seq"])
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common_out(e):
    return {"id": e["id"], "created_at": e["created_at"],
            "updated_at": e["updated_at"], "version": e["version"]}


def ser_route(e):
    o = _common_out(e)
    o.update({"name": e["name"], "zone_code": e["zone_code"],
              "sweep_weekday": e["sweep_weekday"], "sweep_ordinal": e["sweep_ordinal"],
              "status": e["status"], "completed_block_count": e["completed_block_count"]})
    return o


def block_sign_enforceable(e):
    if e["sign_status"] != "VERIFIED":
        return False
    if not e["sign_expires_at"]:
        return False
    return now_dt() < parse_dt(e["sign_expires_at"])


def ser_block(e):
    o = _common_out(e)
    o.update({"route_id": e["route_id"], "block_label": e["block_label"],
              "side": e["side"], "restriction_start_local": e["restriction_start_local"],
              "restriction_end_local": e["restriction_end_local"],
              "linear_feet": e["linear_feet"], "enforcement_enabled": e["enforcement_enabled"],
              "sign_status": e["sign_status"], "sign_posted_at": e["sign_posted_at"],
              "sign_expires_at": e["sign_expires_at"],
              "sign_enforceable": block_sign_enforceable(e),
              "pending_citation_cents": e["pending_citation_cents"]})
    return o


def ser_equipment(e):
    o = _common_out(e)
    o.update({"unit_number": e["unit_number"], "type": e["type"],
              "hopper_capacity_lbs": e["hopper_capacity_lbs"],
              "odometer_miles": e["odometer_miles"], "status": e["status"]})
    return o


def ser_shift(e):
    o = _common_out(e)
    o.update({"equipment_id": e["equipment_id"], "operator_name": e["operator_name"],
              "shift_date": e["shift_date"], "start_utc": e["start_utc"],
              "end_utc": e["end_utc"], "status": e["status"],
              "total_debris_lbs": e["total_debris_lbs"],
              "gross_tonnage": e["gross_tonnage"], "net_tonnage": e["net_tonnage"]})
    return o


def ser_sweep(e):
    o = _common_out(e)
    o.update({"block_id": e["block_id"], "shift_id": e["shift_id"],
              "original_event_id": e["original_event_id"],
              "scheduled_date": e["scheduled_date"],
              "window_start_utc": e["window_start_utc"],
              "window_end_utc": e["window_end_utc"], "status": e["status"],
              "debris_lbs": e["debris_lbs"], "completed_at": e["completed_at"],
              "is_makeup": e["is_makeup"],
              "notified_resident_count": e["notified_resident_count"]})
    return o


def ser_suspension(e):
    o = _common_out(e)
    o.update({"reason": e["reason"], "scope": e["scope"], "route_id": e["route_id"],
              "start_date": e["start_date"], "end_date": e["end_date"],
              "status": e["status"], "suspended_event_count": e["suspended_event_count"]})
    return o


def ser_citation(e):
    o = _common_out(e)
    o.update({"block_id": e["block_id"], "sweep_event_id": e["sweep_event_id"],
              "plate": e["plate"], "scanned_at_utc": e["scanned_at_utc"],
              "issued_at": e["issued_at"], "status": e["status"],
              "amount_due_cents": e["amount_due_cents"],
              "paid_amount_cents": e["paid_amount_cents"],
              "issuing_officer_id": e["issuing_officer_id"],
              "adjudicator_id": e["adjudicator_id"],
              "prior_upheld_count": e["prior_upheld_count"],
              "days_late": e["days_late"]})
    return o


def ser_resident(e):
    o = _common_out(e)
    o.update({"email": e["email"], "full_name": e["full_name"],
              "home_block_id": e["home_block_id"], "notify_opt_in": e["notify_opt_in"]})
    return o


def ser_complaint(e):
    o = _common_out(e)
    o.update({"resident_id": e["resident_id"], "block_id": e["block_id"],
              "category": e["category"],
              "linked_sweep_event_id": e["linked_sweep_event_id"],
              "status": e["status"], "resolution_note": e["resolution_note"]})
    return o


# ---------------------------------------------------------------------------
# Derived-quantity recompute
# ---------------------------------------------------------------------------
def recompute_shift(shift):
    swept = [e for e in DB["sweep_events"].values()
             if e["shift_id"] == shift["id"] and e["status"] == "SWEPT"]
    gross_lbs = sum(e["debris_lbs"] for e in swept)
    # net: latest SWEPT event per block (greatest completed_at, tie greatest created_at)
    winners = {}
    for e in swept:
        b = e["block_id"]
        cur = winners.get(b)
        if cur is None or (e["completed_at"], e["created_at"]) > (cur["completed_at"], cur["created_at"]):
            winners[b] = e
    net_lbs = sum(e["debris_lbs"] for e in winners.values())
    shift["total_debris_lbs"] = gross_lbs
    shift["gross_tonnage"] = float(round_half_up(Decimal(gross_lbs) / Decimal(LBS_PER_TON), 3))
    shift["net_tonnage"] = float(round_half_up(Decimal(net_lbs) / Decimal(LBS_PER_TON), 3))
    touch(shift)


def recompute_block_pending(block):
    total = sum(c["amount_due_cents"] for c in DB["citations"].values()
                if c["block_id"] == block["id"] and c["status"] in ("ISSUED", "CONTESTED"))
    if block["pending_citation_cents"] != total:
        block["pending_citation_cents"] = total
        touch(block)
    else:
        # still a reconciliation mutation point, but value unchanged -> no version bump
        block["pending_citation_cents"] = total


def compute_fine(prior_upheld_count, days_late):
    if prior_upheld_count == 0:
        mult = Decimal("1.0")
    elif prior_upheld_count <= 2:
        mult = Decimal("1.5")
    else:
        mult = Decimal("2.0")
    if days_late <= 0:
        late = 0
    elif days_late <= 15:
        late = 1500
    elif days_late <= 30:
        late = 3000
    else:
        late = 5000
    product = int(round_half_up(Decimal(BASE_FINE_CENTS + late) * mult, 0))
    return min(product, FINE_CAP_CENTS)


# ===========================================================================
# ROUTES
# ===========================================================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ---- Logical clock ----
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"PublicWorksAdmin", "RouteDispatcher", "SignageInspector", "EnforcementOfficer"})
    body = get_body()
    require_present(body, ["to_iso8601"])
    CLOCK["now"] = parse_dt(body["to_iso8601"])
    return success({}, 200, "object")


# ---- Route ----
@app.route("/api/routes", methods=["POST"])
def create_route():
    require_auth({"RouteDispatcher"})
    body = get_body()
    require_present(body, ["name", "zone_code", "sweep_weekday"])
    require_str(body, "name")
    require_str(body, "zone_code")
    require_enum(body, "sweep_weekday", {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"})
    ordinal = body.get("sweep_ordinal")
    if ordinal is not None:
        if not is_int(ordinal) or not (1 <= ordinal <= 5):
            raise ApiError("ERR_VALIDATION", 422, "sweep_ordinal must be null or 1..5.")
    status = body.get("status", "ACTIVE")
    if status is None:
        status = "ACTIVE"
    if status not in ("ACTIVE", "INACTIVE"):
        raise ApiError("ERR_VALIDATION", 422, "status must be ACTIVE or INACTIVE.")
    e = new_common()
    e.update({"name": body["name"], "zone_code": body["zone_code"],
              "sweep_weekday": body["sweep_weekday"], "sweep_ordinal": ordinal,
              "status": status, "completed_block_count": 0})
    DB["routes"][e["id"]] = e
    return success(ser_route(e), 201)


@app.route("/api/routes/<rid>", methods=["GET"])
def get_route(rid):
    require_auth(ALL_ROLES)
    e = get_or_404("routes", rid, "ERR_ROUTE_NOT_FOUND")
    return success(ser_route(e), 200)


# ---- Block ----
@app.route("/api/blocks", methods=["POST"])
def create_block():
    require_auth({"RouteDispatcher"})
    body = get_body()
    require_present(body, ["route_id", "block_label", "side",
                           "restriction_start_local", "restriction_end_local", "linear_feet"])
    require_str(body, "route_id")
    require_str(body, "block_label")
    require_enum(body, "side", {"ODD", "EVEN", "BOTH"})
    start = parse_hhmm(body["restriction_start_local"])
    end = parse_hhmm(body["restriction_end_local"])
    if end <= start:
        raise ApiError("ERR_VALIDATION", 422, "restriction_end_local must be after start.")
    require_int_field(body, "linear_feet", minimum=1)
    enforcement_enabled = optional_bool(body, "enforcement_enabled", True)
    # existence
    get_or_404("routes", body["route_id"], "ERR_ROUTE_NOT_FOUND")
    e = new_common()
    e.update({"route_id": body["route_id"], "block_label": body["block_label"],
              "side": body["side"],
              "restriction_start_local": body["restriction_start_local"],
              "restriction_end_local": body["restriction_end_local"],
              "linear_feet": body["linear_feet"],
              "enforcement_enabled": enforcement_enabled,
              "sign_status": "UNPOSTED", "sign_posted_at": None,
              "sign_expires_at": None, "pending_citation_cents": 0})
    DB["blocks"][e["id"]] = e
    return success(ser_block(e), 201)


@app.route("/api/blocks/<bid>", methods=["GET"])
def get_block(bid):
    require_auth(ALL_ROLES)
    e = get_or_404("blocks", bid, "ERR_BLOCK_NOT_FOUND")
    return success(ser_block(e), 200)


@app.route("/api/blocks", methods=["GET"])
def list_blocks():
    require_auth(ALL_ROLES)
    items = list(DB["blocks"].values())
    route_id = request.args.get("route_id")
    if route_id is not None:
        items = [e for e in items if e["route_id"] == route_id]
    page, limit, offset, total = paginate(items)
    return list_response([ser_block(e) for e in page], limit, offset, total)


@app.route("/api/blocks/<bid>/post-sign", methods=["POST"])
def post_sign(bid):
    require_auth({"SignageInspector"})
    body = get_body()
    require_present(body, ["expected_block_version", "sign_expires_at"])
    if not is_int(body["expected_block_version"]):
        raise ApiError("ERR_VALIDATION", 422, "expected_block_version must be an integer.")
    parse_dt(body["sign_expires_at"])  # validate format
    e = get_or_404("blocks", bid, "ERR_BLOCK_NOT_FOUND")
    # OCC (priority 13)
    if body["expected_block_version"] != e["version"]:
        raise ApiError("ERR_STALE_BLOCK_VERSION", 412, "Block version is stale.")
    e["sign_posted_at"] = now_iso()
    e["sign_expires_at"] = body["sign_expires_at"]
    e["sign_status"] = "POSTED"
    touch(e)
    return success(ser_block(e), 200)


@app.route("/api/blocks/<bid>/verify-sign", methods=["POST"])
def verify_sign(bid):
    require_auth({"SignageInspector"})
    e = get_or_404("blocks", bid, "ERR_BLOCK_NOT_FOUND")
    if e["sign_status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Sign must be POSTED to verify.")
    e["sign_status"] = "VERIFIED"
    touch(e)
    return success(ser_block(e), 200)


# ---- Equipment ----
@app.route("/api/equipment", methods=["POST"])
def create_equipment():
    require_auth({"RouteDispatcher"})
    body = get_body()
    require_present(body, ["unit_number", "type", "hopper_capacity_lbs"])
    require_str(body, "unit_number")
    require_enum(body, "type", {"MECHANICAL", "REGENERATIVE_AIR", "VACUUM"})
    require_int_field(body, "hopper_capacity_lbs", minimum=1)
    odometer = body.get("odometer_miles", 0)
    if odometer is None:
        odometer = 0
    if not is_int(odometer) or odometer < 0:
        raise ApiError("ERR_VALIDATION", 422, "odometer_miles must be a non-negative integer.")
    e = new_common()
    e.update({"unit_number": body["unit_number"], "type": body["type"],
              "hopper_capacity_lbs": body["hopper_capacity_lbs"],
              "odometer_miles": odometer, "status": "AVAILABLE"})
    DB["equipment"][e["id"]] = e
    return success(ser_equipment(e), 201)


@app.route("/api/equipment/<eid>", methods=["GET"])
def get_equipment(eid):
    require_auth(ALL_ROLES)
    e = get_or_404("equipment", eid, "ERR_EQUIPMENT_NOT_FOUND")
    return success(ser_equipment(e), 200)


# ---- Shift ----
@app.route("/api/shifts", methods=["POST"])
def create_shift():
    require_auth({"RouteDispatcher"})
    body = get_body()
    require_present(body, ["equipment_id", "operator_name", "shift_date", "start_utc", "end_utc"])
    require_str(body, "equipment_id")
    require_str(body, "operator_name")
    parse_date(body["shift_date"])
    start = parse_dt(body["start_utc"])
    end = parse_dt(body["end_utc"])
    if end <= start:
        raise ApiError("ERR_VALIDATION", 422, "end_utc must be after start_utc.")
    # existence
    equip = get_or_404("equipment", body["equipment_id"], "ERR_EQUIPMENT_NOT_FOUND")
    # overlap: closed interval expanded by 30-min buffer on each side
    buf = timedelta(minutes=SHIFT_BUFFER_MINUTES)
    for other in DB["shifts"].values():
        if other["equipment_id"] != equip["id"]:
            continue
        os_ = parse_dt(other["start_utc"])
        oe = parse_dt(other["end_utc"])
        if (start - buf) <= oe and os_ <= (end + buf):
            raise ApiError("ERR_SHIFT_OVERLAP", 409, "Shift overlaps another on this equipment.")
    e = new_common()
    e.update({"equipment_id": equip["id"], "operator_name": body["operator_name"],
              "shift_date": body["shift_date"], "start_utc": body["start_utc"],
              "end_utc": body["end_utc"], "status": "PLANNED",
              "total_debris_lbs": 0, "gross_tonnage": 0.0, "net_tonnage": 0.0})
    DB["shifts"][e["id"]] = e
    return success(ser_shift(e), 201)


@app.route("/api/shifts/<sid>", methods=["GET"])
def get_shift(sid):
    require_auth(ALL_ROLES)
    e = get_or_404("shifts", sid, "ERR_SHIFT_NOT_FOUND")
    return success(ser_shift(e), 200)


@app.route("/api/shifts", methods=["GET"])
def list_shifts():
    require_auth(ALL_ROLES)
    items = list(DB["shifts"].values())
    equipment_id = request.args.get("equipment_id")
    if equipment_id is not None:
        items = [e for e in items if e["equipment_id"] == equipment_id]
    page, limit, offset, total = paginate(items)
    return list_response([ser_shift(e) for e in page], limit, offset, total)


@app.route("/api/shifts/<sid>/start", methods=["POST"])
def start_shift(sid):
    require_auth({"RouteDispatcher"})
    e = get_or_404("shifts", sid, "ERR_SHIFT_NOT_FOUND")
    if e["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift must be PLANNED to start.")
    equip = DB["equipment"].get(e["equipment_id"])
    if equip is None or equip["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Equipment must be AVAILABLE to start shift.")
    e["status"] = "IN_PROGRESS"
    touch(e)
    equip["status"] = "IN_SERVICE"
    touch(equip)
    return success(ser_shift(e), 200)


@app.route("/api/shifts/<sid>/close", methods=["POST"])
def close_shift(sid):
    require_auth({"RouteDispatcher"})
    e = get_or_404("shifts", sid, "ERR_SHIFT_NOT_FOUND")
    if e["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift must be IN_PROGRESS to close.")
    recompute_shift(e)
    e["status"] = "CLOSED"
    touch(e)
    equip = DB["equipment"].get(e["equipment_id"])
    if equip is not None:
        equip["status"] = "AVAILABLE"
        touch(equip)
    return success(ser_shift(e), 200)


# ---- SweepEvent ----
@app.route("/api/sweep-events", methods=["POST"])
def create_sweep_event():
    require_auth({"RouteDispatcher"})
    body = get_body()
    require_present(body, ["block_id", "scheduled_date", "window_start_utc", "window_end_utc"])
    require_str(body, "block_id")
    parse_date(body["scheduled_date"])
    ws = parse_dt(body["window_start_utc"])
    we = parse_dt(body["window_end_utc"])
    if we <= ws:
        raise ApiError("ERR_VALIDATION", 422, "window_end_utc must be after window_start_utc.")
    block = get_or_404("blocks", body["block_id"], "ERR_BLOCK_NOT_FOUND")
    # overlap: half-open, live states SCHEDULED/SWEPT on same block
    for other in DB["sweep_events"].values():
        if other["block_id"] != block["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "SWEPT"):
            continue
        os_ = parse_dt(other["window_start_utc"])
        oe = parse_dt(other["window_end_utc"])
        if ws < oe and os_ < we:  # half-open overlap
            raise ApiError("ERR_SWEEP_OVERLAP", 409, "Sweep window overlaps a live sweep.")
    e = new_common()
    e.update({"block_id": block["id"], "shift_id": None, "original_event_id": None,
              "scheduled_date": body["scheduled_date"],
              "window_start_utc": body["window_start_utc"],
              "window_end_utc": body["window_end_utc"], "status": "SCHEDULED",
              "debris_lbs": None, "completed_at": None, "is_makeup": False,
              "notified_resident_count": 0})
    DB["sweep_events"][e["id"]] = e
    return success(ser_sweep(e), 201)


@app.route("/api/sweep-events/<sid>", methods=["GET"])
def get_sweep_event(sid):
    require_auth(ALL_ROLES)
    e = get_or_404("sweep_events", sid, "ERR_SWEEP_EVENT_NOT_FOUND")
    return success(ser_sweep(e), 200)


@app.route("/api/sweep-events", methods=["GET"])
def list_sweep_events():
    require_auth(ALL_ROLES)
    items = list(DB["sweep_events"].values())
    for key in ("block_id", "shift_id", "original_event_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_sweep(e) for e in page], limit, offset, total)


@app.route("/api/sweep-events/<sid>/complete", methods=["POST"])
def complete_sweep(sid):
    require_auth({"RouteDispatcher"})
    body = get_body()
    require_present(body, ["shift_id", "debris_lbs"])
    require_str(body, "shift_id")
    require_int_field(body, "debris_lbs", minimum=0)
    # existence: event (path) then shift (body)
    e = get_or_404("sweep_events", sid, "ERR_SWEEP_EVENT_NOT_FOUND")
    shift = get_or_404("shifts", body["shift_id"], "ERR_SHIFT_NOT_FOUND")
    # state: event SCHEDULED, then shift IN_PROGRESS
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Sweep event must be SCHEDULED to complete.")
    if shift["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SHIFT_NOT_IN_PROGRESS", 409, "Referenced shift is not IN_PROGRESS.")
    # capacity (strict >)
    equip = DB["equipment"].get(shift["equipment_id"])
    cap = equip["hopper_capacity_lbs"] if equip else 0
    if shift["total_debris_lbs"] + body["debris_lbs"] > cap:
        raise ApiError("ERR_SHIFT_CAPACITY_EXCEEDED", 409, "Debris exceeds hopper capacity.")
    # apply
    e["status"] = "SWEPT"
    e["debris_lbs"] = body["debris_lbs"]
    e["completed_at"] = now_iso()
    e["shift_id"] = shift["id"]
    touch(e)
    recompute_shift(shift)
    block = DB["blocks"].get(e["block_id"])
    if block is not None:
        route = DB["routes"].get(block["route_id"])
        if route is not None:
            route["completed_block_count"] += 1
            touch(route)
    return success(ser_sweep(e), 200)


@app.route("/api/sweep-events/<sid>/miss", methods=["POST"])
def miss_sweep(sid):
    require_auth({"RouteDispatcher"})
    get_body()  # optional reason
    e = get_or_404("sweep_events", sid, "ERR_SWEEP_EVENT_NOT_FOUND")
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Sweep event must be SCHEDULED to miss.")
    e["status"] = "MISSED"
    touch(e)
    # auto-create makeup event
    offset = timedelta(days=MAKEUP_OFFSET_DAYS)
    makeup_date = (now_dt().date() + offset)
    new_ws = parse_dt(e["window_start_utc"]) + offset
    new_we = parse_dt(e["window_end_utc"]) + offset
    m = new_common()
    m.update({"block_id": e["block_id"], "shift_id": None, "original_event_id": e["id"],
              "scheduled_date": makeup_date.strftime("%Y-%m-%d"),
              "window_start_utc": fmt_dt(new_ws), "window_end_utc": fmt_dt(new_we),
              "status": "SCHEDULED", "debris_lbs": None, "completed_at": None,
              "is_makeup": True, "notified_resident_count": 0})
    DB["sweep_events"][m["id"]] = m
    return success(ser_sweep(e), 200)


@app.route("/api/sweep-events/<sid>/void", methods=["POST"])
def void_sweep(sid):
    require_auth({"RouteDispatcher"})
    get_body()  # optional reason
    e = get_or_404("sweep_events", sid, "ERR_SWEEP_EVENT_NOT_FOUND")
    if e["status"] != "SWEPT":
        raise ApiError("ERR_INVALID_STATE", 409, "Sweep event must be SWEPT to void.")
    shift = DB["shifts"].get(e["shift_id"])
    e["status"] = "VOIDED"
    touch(e)
    if shift is not None:
        recompute_shift(shift)
    block = DB["blocks"].get(e["block_id"])
    if block is not None:
        route = DB["routes"].get(block["route_id"])
        if route is not None:
            route["completed_block_count"] -= 1
            touch(route)
    return success(ser_sweep(e), 200)


@app.route("/api/sweep-events/<sid>/notify", methods=["POST"])
def notify_sweep(sid):
    require_auth({"RouteDispatcher"})
    get_body()  # optional channel
    e = get_or_404("sweep_events", sid, "ERR_SWEEP_EVENT_NOT_FOUND")
    count = sum(1 for r in DB["residents"].values()
                if r["home_block_id"] == e["block_id"] and r["notify_opt_in"])
    e["notified_resident_count"] = count
    touch(e)
    return success(ser_sweep(e), 200)


# ---- Suspension ----
@app.route("/api/suspensions", methods=["POST"])
def create_suspension():
    require_auth({"PublicWorksAdmin"})
    body = get_body()
    require_present(body, ["reason", "scope", "start_date", "end_date"])
    require_enum(body, "reason", {"HOLIDAY", "LEAF_SEASON", "WEATHER", "OTHER"})
    scope = require_enum(body, "scope", {"SYSTEM", "ROUTE"})
    route_id = body.get("route_id")
    if scope == "ROUTE" and not route_id:
        raise ApiError("ERR_SUSPENSION_SCOPE_INVALID", 422, "scope ROUTE requires route_id.")
    if scope == "SYSTEM" and route_id is not None:
        raise ApiError("ERR_SUSPENSION_SCOPE_INVALID", 422, "scope SYSTEM must omit route_id.")
    sd = parse_date(body["start_date"])
    ed = parse_date(body["end_date"])
    if ed < sd:
        raise ApiError("ERR_VALIDATION", 422, "end_date must be on or after start_date.")
    # existence (route when scoped)
    if scope == "ROUTE":
        get_or_404("routes", route_id, "ERR_ROUTE_NOT_FOUND")
    e = new_common()
    e.update({"reason": body["reason"], "scope": scope,
              "route_id": route_id if scope == "ROUTE" else None,
              "start_date": body["start_date"], "end_date": body["end_date"],
              "status": "SCHEDULED", "suspended_event_count": 0})
    DB["suspensions"][e["id"]] = e
    return success(ser_suspension(e), 201)


@app.route("/api/suspensions/<sid>", methods=["GET"])
def get_suspension(sid):
    require_auth(ALL_ROLES)
    e = get_or_404("suspensions", sid, "ERR_SUSPENSION_NOT_FOUND")
    return success(ser_suspension(e), 200)


@app.route("/api/suspensions", methods=["GET"])
def list_suspensions():
    require_auth(ALL_ROLES)
    items = list(DB["suspensions"].values())
    for key in ("route_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_suspension(e) for e in page], limit, offset, total)


@app.route("/api/suspensions/<sid>/activate", methods=["POST"])
def activate_suspension(sid):
    require_auth({"PublicWorksAdmin"})
    susp = get_or_404("suspensions", sid, "ERR_SUSPENSION_NOT_FOUND")
    if susp["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Suspension must be SCHEDULED to activate.")
    start_d = susp["start_date"]
    end_d = susp["end_date"]
    count = 0
    for ev in list(DB["sweep_events"].values()):
        if ev["status"] != "SCHEDULED":
            continue
        if not (start_d <= ev["scheduled_date"] <= end_d):
            continue
        # scope check
        if susp["scope"] == "ROUTE":
            block = DB["blocks"].get(ev["block_id"])
            if block is None or block["route_id"] != susp["route_id"]:
                continue
        # hop 1: suspend event
        ev["status"] = "SUSPENDED"
        touch(ev)
        count += 1
        # hop 2: dismiss ISSUED citations tied to this event
        for cit in DB["citations"].values():
            if cit["sweep_event_id"] == ev["id"] and cit["status"] == "ISSUED":
                cit["status"] = "DISMISSED"
                touch(cit)
                # hop 3: recompute block pending
                block = DB["blocks"].get(cit["block_id"])
                if block is not None:
                    recompute_block_pending(block)
    susp["suspended_event_count"] = count
    susp["status"] = "ACTIVE"
    touch(susp)
    return success(ser_suspension(susp), 200)


@app.route("/api/suspensions/<sid>/lift", methods=["POST"])
def lift_suspension(sid):
    require_auth({"PublicWorksAdmin"})
    susp = get_or_404("suspensions", sid, "ERR_SUSPENSION_NOT_FOUND")
    if susp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Suspension must be ACTIVE to lift.")
    susp["status"] = "LIFTED"
    touch(susp)
    return success(ser_suspension(susp), 200)


# ---- Citation ----
def _seconds_of_day(dt):
    return dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1_000_000


@app.route("/api/citations", methods=["POST"])
def create_citation():
    uid, role = require_auth({"EnforcementOfficer"})
    body = get_body()
    require_present(body, ["block_id", "plate", "scanned_at_utc"])
    require_str(body, "block_id")
    require_str(body, "plate")
    scanned = parse_dt(body["scanned_at_utc"])
    sweep_event_id = body.get("sweep_event_id")
    # existence: block, then sweep_event (if provided)
    block = get_or_404("blocks", body["block_id"], "ERR_BLOCK_NOT_FOUND")
    if sweep_event_id is not None:
        get_or_404("sweep_events", sweep_event_id, "ERR_SWEEP_EVENT_NOT_FOUND")
    # signage enforceability (priority 8)
    if not (block_sign_enforceable(block) and block["enforcement_enabled"]):
        raise ApiError("ERR_SIGNAGE_NOT_ENFORCEABLE", 422, "Block signage is not enforceable.")
    # suspension coverage (priority 9)
    scanned_date = scanned.date().strftime("%Y-%m-%d")
    for susp in DB["suspensions"].values():
        if susp["status"] != "ACTIVE":
            continue
        if not (susp["start_date"] <= scanned_date <= susp["end_date"]):
            continue
        if susp["scope"] == "SYSTEM" or susp["route_id"] == block["route_id"]:
            raise ApiError("ERR_SWEEP_SUSPENDED", 409, "An active suspension covers this date.")
    # restriction window (priority 10, half-open time-of-day)
    ws = parse_hhmm(block["restriction_start_local"])
    we = parse_hhmm(block["restriction_end_local"])
    tod = _seconds_of_day(scanned)
    if not (ws <= tod < we):
        raise ApiError("ERR_OUTSIDE_RESTRICTION_WINDOW", 422,
                       "scanned_at_utc outside the restriction window.")
    # prior upheld count (same plate, UPHELD/PAID; all existing precede this one)
    prior = sum(1 for c in DB["citations"].values()
                if c["plate"] == body["plate"] and c["status"] in ("UPHELD", "PAID"))
    amount = compute_fine(prior, 0)
    e = new_common()
    e.update({"block_id": block["id"], "sweep_event_id": sweep_event_id,
              "plate": body["plate"], "scanned_at_utc": body["scanned_at_utc"],
              "issued_at": now_iso(), "status": "ISSUED",
              "amount_due_cents": amount, "paid_amount_cents": None,
              "issuing_officer_id": uid, "adjudicator_id": None,
              "prior_upheld_count": prior, "days_late": None})
    DB["citations"][e["id"]] = e
    block["pending_citation_cents"] += amount
    touch(block)
    return success(ser_citation(e), 201)


@app.route("/api/citations/<cid>", methods=["GET"])
def get_citation(cid):
    require_auth(ALL_ROLES)
    e = get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND")
    return success(ser_citation(e), 200)


@app.route("/api/citations", methods=["GET"])
def list_citations():
    require_auth(ALL_ROLES)
    items = list(DB["citations"].values())
    for key in ("block_id", "sweep_event_id", "plate", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_citation(e) for e in page], limit, offset, total)


@app.route("/api/citations/<cid>/contest", methods=["POST"])
def contest_citation(cid):
    require_auth({"EnforcementOfficer"})
    get_body()  # optional reason
    e = get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND")
    if e["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Citation must be ISSUED to contest.")
    e["status"] = "CONTESTED"
    touch(e)
    return success(ser_citation(e), 200)


@app.route("/api/citations/<cid>/adjudicate", methods=["POST"])
def adjudicate_citation(cid):
    uid, role = require_auth({"EnforcementOfficer"})
    body = get_body()
    require_present(body, ["decision"])
    decision = require_enum(body, "decision", {"UPHOLD", "DISMISS"})
    e = get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND")
    if e["status"] != "CONTESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Citation must be CONTESTED to adjudicate.")
    if uid == e["issuing_officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Issuing officer may not adjudicate their own citation.")
    e["adjudicator_id"] = uid
    e["status"] = "UPHELD" if decision == "UPHOLD" else "DISMISSED"
    touch(e)
    block = DB["blocks"].get(e["block_id"])
    if block is not None:
        block["pending_citation_cents"] -= e["amount_due_cents"]
        touch(block)
    return success(ser_citation(e), 200)


@app.route("/api/citations/<cid>/pay", methods=["POST"])
def pay_citation(cid):
    require_auth({"EnforcementOfficer"})
    get_body()
    e = get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND")
    if e["status"] not in ("ISSUED", "UPHELD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Citation must be ISSUED or UPHELD to pay.")
    was_issued = e["status"] == "ISSUED"
    issued = parse_dt(e["issued_at"])
    secs = (now_dt() - issued).total_seconds()
    days = int(secs // 86400)
    e["days_late"] = days
    e["paid_amount_cents"] = compute_fine(e["prior_upheld_count"], days)
    e["status"] = "PAID"
    touch(e)
    if was_issued:
        block = DB["blocks"].get(e["block_id"])
        if block is not None:
            block["pending_citation_cents"] -= e["amount_due_cents"]
            touch(block)
    return success(ser_citation(e), 200)


# ---- Resident ----
@app.route("/api/residents", methods=["POST"])
def create_resident():
    require_auth({"RouteDispatcher"})
    body = get_body()
    require_present(body, ["email", "full_name", "home_block_id"])
    require_str(body, "email")
    require_str(body, "full_name")
    require_str(body, "home_block_id")
    notify_opt_in = optional_bool(body, "notify_opt_in", True)
    get_or_404("blocks", body["home_block_id"], "ERR_BLOCK_NOT_FOUND")
    e = new_common()
    e.update({"email": body["email"], "full_name": body["full_name"],
              "home_block_id": body["home_block_id"], "notify_opt_in": notify_opt_in})
    DB["residents"][e["id"]] = e
    return success(ser_resident(e), 201)


@app.route("/api/residents/<rid>", methods=["GET"])
def get_resident(rid):
    require_auth(ALL_ROLES)
    e = get_or_404("residents", rid, "ERR_RESIDENT_NOT_FOUND")
    return success(ser_resident(e), 200)


@app.route("/api/residents", methods=["GET"])
def list_residents():
    require_auth(ALL_ROLES)
    items = list(DB["residents"].values())
    home_block_id = request.args.get("home_block_id")
    if home_block_id is not None:
        items = [e for e in items if e["home_block_id"] == home_block_id]
    page, limit, offset, total = paginate(items)
    return list_response([ser_resident(e) for e in page], limit, offset, total)


# ---- Complaint ----
@app.route("/api/complaints", methods=["POST"])
def create_complaint():
    uid, role = require_auth({"Resident"})
    body = get_body()
    require_present(body, ["resident_id", "block_id", "category"])
    require_str(body, "resident_id")
    require_str(body, "block_id")
    require_enum(body, "category", {"MISSED_BLOCK", "DEBRIS_LEFT", "SIGN_DAMAGED", "OTHER"})
    linked = body.get("linked_sweep_event_id")
    # existence: resident, block, linked sweep event
    get_or_404("residents", body["resident_id"], "ERR_RESIDENT_NOT_FOUND")
    get_or_404("blocks", body["block_id"], "ERR_BLOCK_NOT_FOUND")
    if linked is not None:
        get_or_404("sweep_events", linked, "ERR_SWEEP_EVENT_NOT_FOUND")
    # ownership (priority 5)
    if body["resident_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Residents may only file their own complaints.")
    e = new_common()
    e.update({"resident_id": body["resident_id"], "block_id": body["block_id"],
              "category": body["category"], "linked_sweep_event_id": linked,
              "status": "OPEN", "resolution_note": None})
    DB["complaints"][e["id"]] = e
    return success(ser_complaint(e), 201)


@app.route("/api/complaints/<cid>", methods=["GET"])
def get_complaint(cid):
    require_auth(ALL_ROLES)
    e = get_or_404("complaints", cid, "ERR_COMPLAINT_NOT_FOUND")
    return success(ser_complaint(e), 200)


@app.route("/api/complaints", methods=["GET"])
def list_complaints():
    require_auth(ALL_ROLES)
    items = list(DB["complaints"].values())
    for key in ("resident_id", "block_id", "linked_sweep_event_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_complaint(e) for e in page], limit, offset, total)


@app.route("/api/complaints/<cid>/resolve", methods=["POST"])
def resolve_complaint(cid):
    require_auth({"RouteDispatcher"})
    body = get_body()
    e = get_or_404("complaints", cid, "ERR_COMPLAINT_NOT_FOUND")
    if e["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint must be OPEN or REOPENED to resolve.")
    e["status"] = "RESOLVED"
    e["resolution_note"] = body.get("resolution_note")
    touch(e)
    return success(ser_complaint(e), 200)


@app.route("/api/complaints/<cid>/reject", methods=["POST"])
def reject_complaint(cid):
    require_auth({"RouteDispatcher"})
    body = get_body()
    e = get_or_404("complaints", cid, "ERR_COMPLAINT_NOT_FOUND")
    if e["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint must be OPEN to reject.")
    e["status"] = "REJECTED"
    e["resolution_note"] = body.get("resolution_note")
    touch(e)
    return success(ser_complaint(e), 200)


@app.route("/api/complaints/<cid>/reopen", methods=["POST"])
def reopen_complaint(cid):
    uid, role = require_auth({"Resident"})
    get_body()  # optional reason
    e = get_or_404("complaints", cid, "ERR_COMPLAINT_NOT_FOUND")
    # ownership (priority 5) before state (priority 6)
    if e["resident_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Residents may only reopen their own complaints.")
    if e["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint must be RESOLVED to reopen.")
    e["status"] = "REOPENED"
    touch(e)
    return success(ser_complaint(e), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
