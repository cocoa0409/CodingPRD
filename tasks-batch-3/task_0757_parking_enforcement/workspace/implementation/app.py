"""
Municipal Parking-Enforcement & Citation Issuance API.

Single-file Flask implementation. In-memory storage only (Python dicts keyed by
id). No seeding: the store starts empty on every boot. Every behavior traces to a
verbatim sentence of PRD.md.
"""

import os
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculations and PRD §3)
# ---------------------------------------------------------------------------
ROLES = {"Admin", "EnforcementOfficer", "Supervisor", "HearingOfficer", "Motorist"}

REPEAT_TIER_0_MULT = Decimal("1.0")
REPEAT_TIER_1_MULT = Decimal("1.5")
REPEAT_TIER_2PLUS_MULT = Decimal("2.0")
ZONE_SURCHARGE = {"DOWNTOWN": 2000, "RESIDENTIAL": 0, "SCHOOL": 5000}
MIN_FINE_CENTS = 2500
MAX_FINE_CENTS = 25000

SCOFFLAW_UNPAID_THRESHOLD = 3
BOOT_BALANCE_THRESHOLD_CENTS = 50000
TOW_BALANCE_THRESHOLD_CENTS = 100000

BOOT_FEE_CENTS = 7500
TOW_FEE_CENTS = 15000
ADMIN_FEE_PCT = Decimal("0.085")

ROOM_BUFFER_MIN = 15  # minutes turnaround
# Shift buffer is 0 (bare half-open intervals)

PATROL_ZONES = {"DOWNTOWN", "RESIDENTIAL", "SCHOOL"}
ISSUED_VIA = {"LPR", "HANDHELD"}
PAYMENT_METHODS = {"CARD", "ECHECK"}
ORDER_TYPES = {"BOOT", "TOW"}
DECISIONS = {"UPHELD", "DISMISSED"}

NF = {
    "officer": "ERR_OFFICER_NOT_FOUND",
    "beat": "ERR_BEAT_NOT_FOUND",
    "violation_code": "ERR_VIOLATION_CODE_NOT_FOUND",
    "hearing_room": "ERR_HEARING_ROOM_NOT_FOUND",
    "shift": "ERR_SHIFT_NOT_FOUND",
    "vehicle": "ERR_VEHICLE_NOT_FOUND",
    "citation": "ERR_CITATION_NOT_FOUND",
    "payment": "ERR_PAYMENT_NOT_FOUND",
    "contest": "ERR_CONTEST_NOT_FOUND",
    "hearing": "ERR_HEARING_NOT_FOUND",
    "boot_tow_order": "ERR_BOOT_TOW_ORDER_NOT_FOUND",
    "registration_hold": "ERR_REGISTRATION_HOLD_NOT_FOUND",
}

# ---------------------------------------------------------------------------
# In-memory stores (empty on boot — never seeded)
# ---------------------------------------------------------------------------
officers = {}
beats = {}
violation_codes = {}
hearing_rooms = {}
shifts = {}
vehicles = {}
citations = {}
payments = {}
contests = {}
hearings = {}
boot_tow_orders = {}
registration_holds = {}

_seq_counter = 0
# Logical clock — starts at 2026-03-01T00:00:00Z; never falls back to wall time.
_clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_uuid():
    import uuid
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_common():
    ts = fmt(now())
    return {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_config():
    return {
        "id": new_uuid(),
        "created_at": fmt(now()),
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at and increment version (mutation)."""
    entity["version"] += 1
    entity["updated_at"] = fmt(now())


# ---------------------------------------------------------------------------
# Response envelope helpers
# ---------------------------------------------------------------------------
def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": fmt(now())}


def respond(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    meta = meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    uid = request.headers.get("X-User-ID")
    return role, uid


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_exists(store, rid, key):
    """Existence check for a provided reference. None -> skip (deferred)."""
    if rid is None:
        return None
    obj = store.get(rid)
    if obj is None:
        raise ApiError(NF[key], 404, "Referenced %s does not exist" % key)
    return obj


def bad(msg="Validation failed", status=400):
    raise ApiError("ERR_VALIDATION", status, msg)


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit out of bounds")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset out of bounds")
    return limit, offset


def list_response(items):
    """items: list of entity dicts. Sort by created_at asc (seq tiebreak), paginate."""
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return respond([serialize(e) for e in page], 200, "array", pagination)


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def settled_paid(c):
    total = c.get("_waived", 0)
    for p in payments.values():
        if p["citation_id"] == c["id"] and p["status"] == "SETTLED":
            total += p["amount_cents"]
    return total


def pending_paid(c):
    total = 0
    for p in payments.values():
        if p["citation_id"] == c["id"] and p["status"] == "PENDING":
            total += p["amount_cents"]
    return total


def recompute_citation(c):
    paid = settled_paid(c)
    c["amount_paid_cents"] = paid
    if c["status"] == "DISMISSED":
        c["amount_due_cents"] = 0
    else:
        c["amount_due_cents"] = max(0, c["fine_amount_cents"] - paid)


def recompute_vehicle(v):
    # Refresh each of the vehicle's citations first.
    veh_citations = [c for c in citations.values() if c["vehicle_id"] == v["id"]]
    for c in veh_citations:
        recompute_citation(c)

    unpaid = [c for c in veh_citations if c["status"] in ("ISSUED", "UPHELD")]
    outstanding = 0
    projected = 0
    for c in unpaid:
        paid = c["amount_paid_cents"]
        pending = pending_paid(c)
        outstanding += max(0, c["fine_amount_cents"] - paid)
        projected += max(0, c["fine_amount_cents"] - paid - pending)
    count = len(unpaid)

    if outstanding >= TOW_BALANCE_THRESHOLD_CENTS:
        scofflaw = "TOW_ELIGIBLE"
    elif outstanding >= BOOT_BALANCE_THRESHOLD_CENTS:
        scofflaw = "BOOT_ELIGIBLE"
    elif count >= SCOFFLAW_UNPAID_THRESHOLD:
        scofflaw = "SCOFFLAW"
    else:
        scofflaw = "NONE"

    # De-escalation cascade: any event dropping to NONE/SCOFFLAW cancels a still
    # ORDERED order (an APPLIED order is not auto-cancelled) and clears its hold.
    if scofflaw in ("NONE", "SCOFFLAW"):
        for o in boot_tow_orders.values():
            if o["vehicle_id"] == v["id"] and o["status"] == "ORDERED":
                o["status"] = "CANCELLED"
                touch(o)
                for h in registration_holds.values():
                    if h["boot_tow_order_id"] == o["id"] and h["status"] == "PLACED":
                        h["status"] = "CLEARED"
                        touch(h)

    has_hold = any(
        h["vehicle_id"] == v["id"] and h["status"] == "PLACED"
        for h in registration_holds.values()
    )

    old_gating = (
        v.get("outstanding_balance_cents"),
        v.get("unpaid_citation_count"),
        v.get("scofflaw_status"),
        v.get("has_active_registration_hold"),
    )
    new_gating = (outstanding, count, scofflaw, has_hold)

    v["outstanding_balance_cents"] = outstanding
    v["projected_balance_cents"] = projected
    v["unpaid_citation_count"] = count
    v["scofflaw_status"] = scofflaw
    v["has_active_registration_hold"] = has_hold

    if old_gating != new_gating:
        touch(v)


def maybe_auto_escalate(v):
    """After a citation issue only: create an AUTO boot/tow order + hold when the
    vehicle is BOOT_ELIGIBLE or TOW_ELIGIBLE and no active order exists."""
    if v["scofflaw_status"] not in ("BOOT_ELIGIBLE", "TOW_ELIGIBLE"):
        return
    active = any(
        o["vehicle_id"] == v["id"] and o["status"] in ("ORDERED", "APPLIED")
        for o in boot_tow_orders.values()
    )
    if active:
        return
    order_type = "BOOT" if v["scofflaw_status"] == "BOOT_ELIGIBLE" else "TOW"
    create_order(v, order_type, origin="AUTO")
    recompute_vehicle(v)


def create_order(v, order_type, origin):
    order = new_common()
    order.update({
        "vehicle_id": v["id"],
        "order_type": order_type,
        "origin": origin,
        "fee_cents": BOOT_FEE_CENTS if order_type == "BOOT" else TOW_FEE_CENTS,
        "release_total_cents": None,
        "status": "ORDERED",
    })
    boot_tow_orders[order["id"]] = order
    hold = new_common()
    hold.update({
        "vehicle_id": v["id"],
        "boot_tow_order_id": order["id"],
        "reason": "BOOT_TOW_ESCALATION",
        "status": "PLACED",
    })
    registration_holds[hold["id"]] = hold
    return order


# ---------------------------------------------------------------------------
# Overlap checks
# ---------------------------------------------------------------------------
def check_shift_overlap(officer_id, s2, e2):
    for x in shifts.values():
        if x["officer_id"] != officer_id or x["status"] != "OPEN":
            continue
        if s2 < x["_send"] and x["_sstart"] < e2:
            raise ApiError("ERR_SHIFT_OVERLAP", 409, "New shift overlaps an OPEN shift of the same officer")


def check_room_overlap(room_id, s2, e2, exclude_hearing_id=None):
    buffer_secs = ROOM_BUFFER_MIN * 60
    from datetime import timedelta
    buf = timedelta(seconds=buffer_secs)
    for x in hearings.values():
        if x["room_id"] != room_id or x["status"] != "SCHEDULED":
            continue
        if exclude_hearing_id is not None and x["id"] == exclude_hearing_id:
            continue
        if s2 < (x["_send"] + buf) and (x["_sstart"] - buf) < e2:
            raise ApiError("ERR_ROOM_UNAVAILABLE", 409, "Hearing time violates the buffered room-availability window")


# =============================================================================
# Configuration endpoints (Admin)
# =============================================================================
@app.route("/officers", methods=["POST"])
def create_officer():
    auth({"Admin"})
    body = get_body()
    badge = body.get("badge_number")
    name = body.get("full_name")
    if not isinstance(badge, str) or badge == "" or not isinstance(name, str) or name == "":
        bad("badge_number and full_name are required strings")
    o = new_common()
    o.update({"badge_number": badge, "full_name": name})
    officers[o["id"]] = o
    return respond(serialize(o), 201)


@app.route("/officers/<oid>", methods=["GET"])
def get_officer(oid):
    auth(ROLES)
    o = require_exists(officers, oid, "officer")
    return respond(serialize(o), 200)


@app.route("/beats", methods=["POST"])
def create_beat():
    auth({"Admin"})
    body = get_body()
    beat_code = body.get("beat_code")
    name = body.get("name")
    zone = body.get("patrol_zone")
    if not isinstance(beat_code, str) or beat_code == "" or not isinstance(name, str) or name == "":
        bad("beat_code and name are required strings")
    if zone not in PATROL_ZONES:
        bad("patrol_zone must be one of DOWNTOWN, RESIDENTIAL, SCHOOL")
    b = new_config()
    b.update({"beat_code": beat_code, "name": name, "patrol_zone": zone})
    beats[b["id"]] = b
    return respond(serialize(b), 201)


@app.route("/beats/<bid>", methods=["GET"])
def get_beat(bid):
    auth(ROLES)
    b = require_exists(beats, bid, "beat")
    return respond(serialize(b), 200)


@app.route("/violation-codes", methods=["POST"])
def create_violation_code():
    auth({"Admin"})
    body = get_body()
    code = body.get("code")
    desc = body.get("description")
    base = body.get("base_fine_cents")
    booting = body.get("is_booting_eligible")
    if not isinstance(code, str) or code == "" or not isinstance(desc, str) or desc == "":
        bad("code and description are required strings")
    if not is_int(base) or base < 0:
        bad("base_fine_cents must be an integer >= 0")
    if not isinstance(booting, bool):
        bad("is_booting_eligible must be a boolean")
    vc = new_common()
    vc.update({
        "code": code,
        "description": desc,
        "base_fine_cents": base,
        "is_booting_eligible": booting,
        "status": "ACTIVE",
    })
    violation_codes[vc["id"]] = vc
    return respond(serialize(vc), 201)


@app.route("/violation-codes/<vid>", methods=["GET"])
def get_violation_code(vid):
    auth(ROLES)
    vc = require_exists(violation_codes, vid, "violation_code")
    return respond(serialize(vc), 200)


@app.route("/violation-codes/<vid>/retire", methods=["POST"])
def retire_violation_code(vid):
    auth({"Admin"})
    vc = require_exists(violation_codes, vid, "violation_code")
    if vc["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation code is not ACTIVE")
    vc["status"] = "RETIRED"
    touch(vc)
    return respond(serialize(vc), 200)


@app.route("/hearing-rooms", methods=["POST"])
def create_hearing_room():
    auth({"Admin"})
    body = get_body()
    room_code = body.get("room_code")
    name = body.get("name")
    if not isinstance(room_code, str) or room_code == "" or not isinstance(name, str) or name == "":
        bad("room_code and name are required strings")
    r = new_config()
    r.update({"room_code": room_code, "name": name})
    hearing_rooms[r["id"]] = r
    return respond(serialize(r), 201)


@app.route("/hearing-rooms/<rid>", methods=["GET"])
def get_hearing_room(rid):
    auth(ROLES)
    r = require_exists(hearing_rooms, rid, "hearing_room")
    return respond(serialize(r), 200)


# =============================================================================
# Shifts (EnforcementOfficer)
# =============================================================================
@app.route("/shifts", methods=["POST"])
def create_shift():
    role, uid = auth({"EnforcementOfficer"})
    body = get_body()
    officer_id = body.get("officer_id")
    beat_id = body.get("beat_id")
    s_start = body.get("scheduled_start")
    s_end = body.get("scheduled_end")

    # Existence (body FKs in declared order)
    require_exists(officers, officer_id, "officer")
    require_exists(beats, beat_id, "beat")

    # Ownership (only when officer_id resolved)
    if officer_id is not None and uid != officer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "X-User-ID must equal the shift's officer_id")

    # Temporal (needs parsed valid interval)
    parsed_ok = False
    ps = pe = None
    if isinstance(s_start, str) and isinstance(s_end, str):
        try:
            ps = parse_iso(s_start)
            pe = parse_iso(s_end)
            parsed_ok = pe > ps
        except (ValueError, TypeError):
            parsed_ok = False
    if parsed_ok and officer_id is not None:
        check_shift_overlap(officer_id, ps, pe)

    # Field-level validation
    if officer_id is None or beat_id is None:
        bad("officer_id and beat_id are required")
    if not isinstance(s_start, str) or not isinstance(s_end, str):
        bad("scheduled_start and scheduled_end are required")
    try:
        ps = parse_iso(s_start)
        pe = parse_iso(s_end)
    except (ValueError, TypeError):
        bad("scheduled_start/scheduled_end must be ISO 8601")
    if not pe > ps:
        bad("scheduled_end must be strictly after scheduled_start")

    s = new_common()
    s.update({
        "officer_id": officer_id,
        "beat_id": beat_id,
        "scheduled_start": s_start,
        "scheduled_end": s_end,
        "status": "OPEN",
        "gross_citation_count": None,
        "net_citation_count": None,
        "citations_per_hour": None,
        "closed_at": None,
        "_sstart": ps,
        "_send": pe,
    })
    shifts[s["id"]] = s
    return respond(serialize(s), 201)


@app.route("/shifts/<sid>", methods=["GET"])
def get_shift(sid):
    auth(ROLES)
    s = require_exists(shifts, sid, "shift")
    return respond(serialize(s), 200)


@app.route("/shifts", methods=["GET"])
def list_shifts():
    auth(ROLES)
    items = list(shifts.values())
    for field in ("officer_id", "beat_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s[field] == val]
    return list_response(items)


@app.route("/shifts/<sid>/close", methods=["POST"])
def close_shift(sid):
    role, uid = auth({"EnforcementOfficer"})
    s = require_exists(shifts, sid, "shift")
    if uid != s["officer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "X-User-ID must equal the shift's officer_id")
    if s["status"] != "OPEN":
        raise ApiError("ERR_SHIFT_NOT_OPEN", 409, "Shift is not OPEN")

    shift_citations = [c for c in citations.values() if c["shift_id"] == s["id"]]
    gross = len(shift_citations)
    net = len([c for c in shift_citations if c["status"] not in ("VOID", "DISMISSED")])
    secs = (s["_send"] - s["_sstart"]).total_seconds()
    hours = Decimal(secs) / Decimal(3600)
    if net == 0:
        cph = Decimal("0.00")
    else:
        cph = (Decimal(net) / hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s["gross_citation_count"] = gross
    s["net_citation_count"] = net
    s["citations_per_hour"] = float(cph)
    s["status"] = "CLOSED"
    s["closed_at"] = fmt(now())
    touch(s)
    return respond(serialize(s), 200)


# =============================================================================
# Vehicles
# =============================================================================
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    auth({"Admin", "Supervisor", "EnforcementOfficer"})
    body = get_body()
    plate = body.get("plate")
    state = body.get("state")
    if not isinstance(plate, str) or plate == "":
        bad("plate is required")
    if not isinstance(state, str) or len(state) != 2:
        bad("state must be a two-letter code")
    v = new_common()
    v.update({
        "plate": plate,
        "state": state,
        "outstanding_balance_cents": 0,
        "projected_balance_cents": 0,
        "unpaid_citation_count": 0,
        "scofflaw_status": "NONE",
        "has_active_registration_hold": False,
    })
    vehicles[v["id"]] = v
    return respond(serialize(v), 201)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    auth(ROLES)
    v = require_exists(vehicles, vid, "vehicle")
    return respond(serialize(v), 200)


@app.route("/vehicles/<vid>/adjustments", methods=["POST"])
def vehicle_adjustment(vid):
    auth({"Supervisor"})
    body = get_body()
    v = require_exists(vehicles, vid, "vehicle")
    citation_id = body.get("citation_id")
    c = require_exists(citations, citation_id, "citation")

    # OCC (concurrency, priority 5)
    expected = body.get("expected_vehicle_version")
    if expected is not None:
        if expected != v["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_vehicle_version does not match")

    waive = body.get("waive_amount_cents")

    # Fiscal bound (priority 9): waiver must not exceed citation's amount_due
    if c is not None and is_int(waive):
        if waive > c["amount_due_cents"]:
            raise ApiError("ERR_ADJUSTMENT_EXCEEDS_BALANCE", 422, "Waiver exceeds the citation's amount_due")

    # Field-level (priority 10)
    if citation_id is None:
        bad("citation_id is required")
    if expected is None:
        bad("expected_vehicle_version is required")
    if not is_int(waive) or waive < 1:
        bad("waive_amount_cents must be an integer >= 1")
    if c["vehicle_id"] != v["id"]:
        bad("citation does not belong to this vehicle")

    c["_waived"] = c.get("_waived", 0) + waive
    recompute_citation(c)
    touch(c)
    recompute_vehicle(v)
    return respond(serialize(v), 200)


# =============================================================================
# Citations
# =============================================================================
def repeat_index(vehicle_id, violation_code_id):
    return len([
        c for c in citations.values()
        if c["vehicle_id"] == vehicle_id
        and c["violation_code_id"] == violation_code_id
        and c["status"] != "VOID"
    ])


def compute_fine(vehicle_id, violation_code, beat):
    n = repeat_index(vehicle_id, violation_code["id"])
    if n == 0:
        tier = REPEAT_TIER_0_MULT
    elif n == 1:
        tier = REPEAT_TIER_1_MULT
    else:
        tier = REPEAT_TIER_2PLUS_MULT
    scaled = int((Decimal(violation_code["base_fine_cents"]) * tier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    raw = scaled + ZONE_SURCHARGE[beat["patrol_zone"]]
    return min(max(raw, MIN_FINE_CENTS), MAX_FINE_CENTS)


@app.route("/citations", methods=["POST"])
def create_citation():
    role, uid = auth({"EnforcementOfficer"})
    body = get_body()
    vehicle_id = body.get("vehicle_id")
    shift_id = body.get("shift_id")
    violation_code_id = body.get("violation_code_id")
    issued_via = body.get("issued_via")
    evidence = body.get("evidence_photo_url")

    # Existence (body FKs in declared order: vehicle, shift, violation_code)
    v = require_exists(vehicles, vehicle_id, "vehicle")
    s = require_exists(shifts, shift_id, "shift")
    vc = require_exists(violation_codes, violation_code_id, "violation_code")

    # Ownership (only when shift resolved)
    if s is not None and uid != s["officer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "X-User-ID must equal the shift's officer_id")

    # State: shift must be OPEN
    if s is not None and s["status"] != "OPEN":
        raise ApiError("ERR_SHIFT_NOT_OPEN", 409, "Shift is not OPEN")

    # Eligibility: violation code must be ACTIVE
    if vc is not None and vc["status"] != "ACTIVE":
        raise ApiError("ERR_VIOLATION_CODE_RETIRED", 422, "Violation code is RETIRED")

    # Field-level
    if vehicle_id is None or shift_id is None or violation_code_id is None:
        bad("vehicle_id, shift_id, violation_code_id are required")
    if issued_via not in ISSUED_VIA:
        bad("issued_via must be one of LPR, HANDHELD")
    if not isinstance(evidence, str) or evidence == "":
        bad("evidence_photo_url is required")

    beat = beats[s["beat_id"]]
    c = new_common()
    c.update({
        "vehicle_id": vehicle_id,
        "shift_id": shift_id,
        "violation_code_id": violation_code_id,
        "officer_id": s["officer_id"],
        "beat_id": s["beat_id"],
        "issued_via": issued_via,
        "evidence_photo_url": evidence,
        "fine_amount_cents": 0,
        "amount_paid_cents": 0,
        "amount_due_cents": 0,
        "status": "ISSUED",
        "issued_at": fmt(now()),
        "_waived": 0,
        "_paid_by": None,
    })
    c["fine_amount_cents"] = compute_fine(vehicle_id, vc, beat)
    recompute_citation(c)
    citations[c["id"]] = c
    recompute_vehicle(v)
    maybe_auto_escalate(v)
    return respond(serialize(c), 201)


@app.route("/citations/<cid>", methods=["GET"])
def get_citation(cid):
    auth(ROLES)
    c = require_exists(citations, cid, "citation")
    return respond(serialize(c), 200)


@app.route("/citations", methods=["GET"])
def list_citations():
    auth(ROLES)
    items = list(citations.values())
    for field in ("vehicle_id", "shift_id", "violation_code_id", "officer_id", "beat_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c[field] == val]
    return list_response(items)


@app.route("/citations/<cid>/reassess", methods=["POST"])
def reassess_citation(cid):
    auth({"Supervisor"})
    body = get_body()
    c = require_exists(citations, cid, "citation")

    expected = body.get("expected_citation_version")
    if expected is not None and expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_citation_version does not match")

    new_fine = body.get("new_fine_amount_cents")

    # Fiscal bound (priority 9): reassessed fine within [MIN, MAX] -> ERR_VALIDATION 422
    if is_int(new_fine):
        if new_fine < MIN_FINE_CENTS or new_fine > MAX_FINE_CENTS:
            bad("Reassessed fine out of [MIN_FINE_CENTS, MAX_FINE_CENTS]", 422)

    # Field-level
    if expected is None:
        bad("expected_citation_version is required")
    if not is_int(new_fine):
        bad("new_fine_amount_cents must be an integer")

    c["fine_amount_cents"] = min(max(new_fine, MIN_FINE_CENTS), MAX_FINE_CENTS)
    recompute_citation(c)
    touch(c)
    v = vehicles[c["vehicle_id"]]
    recompute_vehicle(v)
    return respond(serialize(c), 200)


@app.route("/citations/<cid>/void", methods=["POST"])
def void_citation(cid):
    auth({"Supervisor"})
    c = require_exists(citations, cid, "citation")
    if c["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Citation is not ISSUED")
    c["status"] = "VOID"
    recompute_citation(c)
    touch(c)
    v = vehicles[c["vehicle_id"]]
    recompute_vehicle(v)
    return respond(serialize(c), 200)


# =============================================================================
# Payments (Motorist)
# =============================================================================
@app.route("/payments", methods=["POST"])
def create_payment():
    auth({"Motorist"})
    body = get_body()
    citation_id = body.get("citation_id")
    c = require_exists(citations, citation_id, "citation")

    # State: citation must be payable (ISSUED or UPHELD)
    if c is not None and c["status"] not in ("ISSUED", "UPHELD"):
        raise ApiError("ERR_CITATION_NOT_PAYABLE", 409, "Citation is not payable")

    amount = body.get("amount_cents")
    # Fiscal bound: 1..amount_due at creation
    if c is not None and is_int(amount):
        if amount < 1 or amount > c["amount_due_cents"]:
            raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422, "amount_cents not within 1..amount_due")

    # Field-level
    if citation_id is None:
        bad("citation_id is required")
    if not is_int(amount):
        bad("amount_cents must be an integer")
    method = body.get("method")
    if method not in PAYMENT_METHODS:
        bad("method must be one of CARD, ECHECK")

    p = new_common()
    p.update({
        "citation_id": citation_id,
        "amount_cents": amount,
        "method": method,
        "status": "PENDING",
    })
    payments[p["id"]] = p
    # Recompute vehicle projected (pending payment lowers projected only)
    recompute_vehicle(vehicles[c["vehicle_id"]])
    return respond(serialize(p), 201)


@app.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    auth(ROLES)
    p = require_exists(payments, pid, "payment")
    return respond(serialize(p), 200)


@app.route("/payments", methods=["GET"])
def list_payments():
    auth(ROLES)
    items = list(payments.values())
    for field in ("citation_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p[field] == val]
    return list_response(items)


@app.route("/payments/<pid>/settle", methods=["POST"])
def settle_payment(pid):
    auth({"Motorist"})
    p = require_exists(payments, pid, "payment")
    c = citations[p["citation_id"]]
    if p["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment is not PENDING")
    if c["status"] not in ("ISSUED", "UPHELD"):
        raise ApiError("ERR_CITATION_NOT_PAYABLE", 409, "Citation is not payable")

    p["status"] = "SETTLED"
    touch(p)
    recompute_citation(c)
    touch(c)
    if c["amount_paid_cents"] >= c["fine_amount_cents"]:
        c["status"] = "PAID"
        c["_paid_by"] = p["id"]
        recompute_citation(c)
    recompute_vehicle(vehicles[c["vehicle_id"]])
    return respond(serialize(p), 200)


@app.route("/payments/<pid>/refund", methods=["POST"])
def refund_payment(pid):
    auth({"Supervisor"})
    p = require_exists(payments, pid, "payment")
    c = citations[p["citation_id"]]
    if p["status"] != "SETTLED":
        raise ApiError("ERR_PAYMENT_NOT_REFUNDABLE", 409, "Payment is not SETTLED")

    p["status"] = "REFUNDED"
    touch(p)
    # If the citation was made PAID by this very payment, revert to ISSUED.
    if c["status"] == "PAID" and c.get("_paid_by") == p["id"]:
        c["status"] = "ISSUED"
        c["_paid_by"] = None
    recompute_citation(c)
    touch(c)
    recompute_vehicle(vehicles[c["vehicle_id"]])
    return respond(serialize(p), 200)


# =============================================================================
# Contests (Motorist)
# =============================================================================
@app.route("/contests", methods=["POST"])
def create_contest():
    auth({"Motorist"})
    body = get_body()
    citation_id = body.get("citation_id")
    c = require_exists(citations, citation_id, "citation")

    # State: citation must be ISSUED (contestable); no non-terminal contest exists
    if c is not None:
        if c["status"] != "ISSUED":
            raise ApiError("ERR_CITATION_NOT_CONTESTABLE", 409, "Citation is not contestable")
        existing = [
            ct for ct in contests.values()
            if ct["citation_id"] == c["id"] and ct["status"] in ("SUBMITTED", "HEARING_SCHEDULED")
        ]
        if existing:
            raise ApiError("ERR_CONTEST_ALREADY_EXISTS", 409, "A non-terminal contest already exists")

    grounds = body.get("grounds")
    if citation_id is None:
        bad("citation_id is required")
    if not isinstance(grounds, str) or grounds == "":
        bad("grounds is required")

    ct = new_common()
    ct.update({
        "citation_id": citation_id,
        "grounds": grounds,
        "status": "SUBMITTED",
    })
    contests[ct["id"]] = ct
    c["status"] = "CONTESTED"
    recompute_citation(c)
    touch(c)
    recompute_vehicle(vehicles[c["vehicle_id"]])
    return respond(serialize(ct), 201)


@app.route("/contests/<ctid>", methods=["GET"])
def get_contest(ctid):
    auth(ROLES)
    ct = require_exists(contests, ctid, "contest")
    return respond(serialize(ct), 200)


@app.route("/contests", methods=["GET"])
def list_contests():
    auth(ROLES)
    items = list(contests.values())
    for field in ("citation_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [ct for ct in items if ct[field] == val]
    return list_response(items)


# =============================================================================
# Hearings (HearingOfficer)
# =============================================================================
@app.route("/hearings", methods=["POST"])
def create_hearing():
    auth({"HearingOfficer"})
    body = get_body()
    contest_id = body.get("contest_id")
    room_id = body.get("room_id")
    s_start = body.get("scheduled_start")
    s_end = body.get("scheduled_end")

    ct = require_exists(contests, contest_id, "contest")
    require_exists(hearing_rooms, room_id, "hearing_room")

    # State: contest must be SUBMITTED
    if ct is not None and ct["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Contest is not SUBMITTED")

    # Temporal (needs valid interval + resolved room)
    ps = pe = None
    parsed_ok = False
    if isinstance(s_start, str) and isinstance(s_end, str):
        try:
            ps = parse_iso(s_start)
            pe = parse_iso(s_end)
            parsed_ok = pe > ps
        except (ValueError, TypeError):
            parsed_ok = False
    if parsed_ok and room_id is not None:
        check_room_overlap(room_id, ps, pe)

    # Field-level
    if contest_id is None or room_id is None:
        bad("contest_id and room_id are required")
    if not isinstance(s_start, str) or not isinstance(s_end, str):
        bad("scheduled_start and scheduled_end are required")
    try:
        ps = parse_iso(s_start)
        pe = parse_iso(s_end)
    except (ValueError, TypeError):
        bad("scheduled_start/scheduled_end must be ISO 8601")
    if not pe > ps:
        bad("scheduled_end must be strictly after scheduled_start")

    h = new_common()
    h.update({
        "contest_id": contest_id,
        "room_id": room_id,
        "scheduled_start": s_start,
        "scheduled_end": s_end,
        "adjournment_count": 0,
        "decision": None,
        "status": "SCHEDULED",
        "_sstart": ps,
        "_send": pe,
    })
    hearings[h["id"]] = h
    ct["status"] = "HEARING_SCHEDULED"
    touch(ct)
    return respond(serialize(h), 201)


@app.route("/hearings/<hid>", methods=["GET"])
def get_hearing(hid):
    auth(ROLES)
    h = require_exists(hearings, hid, "hearing")
    return respond(serialize(h), 200)


@app.route("/hearings", methods=["GET"])
def list_hearings():
    auth(ROLES)
    items = list(hearings.values())
    for field in ("contest_id", "room_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [h for h in items if h[field] == val]
    return list_response(items)


@app.route("/hearings/<hid>/adjourn", methods=["POST"])
def adjourn_hearing(hid):
    auth({"HearingOfficer"})
    body = get_body()
    h = require_exists(hearings, hid, "hearing")
    if h["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Hearing is not SCHEDULED")

    s_start = body.get("scheduled_start")
    s_end = body.get("scheduled_end")

    # Temporal (exclude self), then field-level
    ps = pe = None
    parsed_ok = False
    if isinstance(s_start, str) and isinstance(s_end, str):
        try:
            ps = parse_iso(s_start)
            pe = parse_iso(s_end)
            parsed_ok = pe > ps
        except (ValueError, TypeError):
            parsed_ok = False
    if parsed_ok:
        check_room_overlap(h["room_id"], ps, pe, exclude_hearing_id=h["id"])

    if not isinstance(s_start, str) or not isinstance(s_end, str):
        bad("scheduled_start and scheduled_end are required")
    try:
        ps = parse_iso(s_start)
        pe = parse_iso(s_end)
    except (ValueError, TypeError):
        bad("scheduled_start/scheduled_end must be ISO 8601")
    if not pe > ps:
        bad("scheduled_end must be strictly after scheduled_start")

    h["scheduled_start"] = s_start
    h["scheduled_end"] = s_end
    h["_sstart"] = ps
    h["_send"] = pe
    h["adjournment_count"] += 1
    touch(h)
    return respond(serialize(h), 200)


@app.route("/hearings/<hid>/decide", methods=["POST"])
def decide_hearing(hid):
    auth({"HearingOfficer"})
    body = get_body()
    h = require_exists(hearings, hid, "hearing")
    if h["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Hearing is not SCHEDULED")
    decision = body.get("decision")
    if decision not in DECISIONS:
        raise ApiError("ERR_HEARING_DECISION_INVALID", 422, "decision must be UPHELD or DISMISSED")

    h["decision"] = decision
    h["status"] = "HELD"
    touch(h)

    ct = contests[h["contest_id"]]
    c = citations[ct["citation_id"]]
    if decision == "UPHELD":
        ct["status"] = "CLOSED_UPHELD"
        touch(ct)
        c["status"] = "UPHELD"
    else:
        ct["status"] = "CLOSED_DISMISSED"
        touch(ct)
        c["status"] = "DISMISSED"
    recompute_citation(c)
    touch(c)
    recompute_vehicle(vehicles[c["vehicle_id"]])
    return respond(serialize(h), 200)


# =============================================================================
# Boot / Tow orders (Supervisor)
# =============================================================================
@app.route("/boot-tow-orders", methods=["POST"])
def create_boot_tow_order():
    auth({"Supervisor"})
    body = get_body()
    vehicle_id = body.get("vehicle_id")
    v = require_exists(vehicles, vehicle_id, "vehicle")

    # State (priority 6): only one active order per vehicle
    if v is not None:
        active = any(
            o["vehicle_id"] == v["id"] and o["status"] in ("ORDERED", "APPLIED")
            for o in boot_tow_orders.values()
        )
        if active:
            raise ApiError("ERR_BOOT_ALREADY_ACTIVE", 409, "An ORDERED/APPLIED order already exists")

    # Eligibility (priority 8): vehicle must be BOOT/TOW eligible
    if v is not None and v["scofflaw_status"] not in ("BOOT_ELIGIBLE", "TOW_ELIGIBLE"):
        raise ApiError("ERR_VEHICLE_NOT_BOOT_ELIGIBLE", 422, "Vehicle is not boot/tow eligible")

    order_type = body.get("order_type")
    if vehicle_id is None:
        bad("vehicle_id is required")
    if order_type not in ORDER_TYPES:
        bad("order_type must be one of BOOT, TOW")

    order = create_order(v, order_type, origin="MANUAL")
    recompute_vehicle(v)
    return respond(serialize(order), 201)


@app.route("/boot-tow-orders/<oid>", methods=["GET"])
def get_boot_tow_order(oid):
    auth(ROLES)
    o = require_exists(boot_tow_orders, oid, "boot_tow_order")
    return respond(serialize(o), 200)


@app.route("/boot-tow-orders", methods=["GET"])
def list_boot_tow_orders():
    auth(ROLES)
    items = list(boot_tow_orders.values())
    for field in ("vehicle_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [o for o in items if o[field] == val]
    return list_response(items)


@app.route("/boot-tow-orders/<oid>/apply", methods=["POST"])
def apply_boot_tow_order(oid):
    auth({"Supervisor"})
    o = require_exists(boot_tow_orders, oid, "boot_tow_order")
    if o["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not ORDERED")
    o["status"] = "APPLIED"
    touch(o)
    return respond(serialize(o), 200)


@app.route("/boot-tow-orders/<oid>/release", methods=["POST"])
def release_boot_tow_order(oid):
    auth({"Supervisor"})
    o = require_exists(boot_tow_orders, oid, "boot_tow_order")
    if o["status"] not in ("ORDERED", "APPLIED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not ORDERED or APPLIED")

    subtotal = 0
    for c in citations.values():
        if c["vehicle_id"] == o["vehicle_id"] and c["status"] in ("ISSUED", "UPHELD"):
            subtotal += c["amount_due_cents"]
    admin_fee = int((Decimal(subtotal) * ADMIN_FEE_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    o["release_total_cents"] = subtotal + o["fee_cents"] + admin_fee
    o["status"] = "RELEASED"
    touch(o)
    return respond(serialize(o), 200)


# =============================================================================
# Registration Holds (read-only)
# =============================================================================
@app.route("/registration-holds/<rid>", methods=["GET"])
def get_registration_hold(rid):
    auth(ROLES)
    h = require_exists(registration_holds, rid, "registration_hold")
    return respond(serialize(h), 200)


@app.route("/registration-holds", methods=["GET"])
def list_registration_holds():
    auth(ROLES)
    items = list(registration_holds.values())
    for field in ("vehicle_id", "boot_tow_order_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [h for h in items if h[field] == val]
    return list_response(items)


# =============================================================================
# Logical clock (test-driving)
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_endpoint():
    auth({"Admin"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        bad("to_iso8601 is required")
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        bad("to_iso8601 must be ISO 8601")
    set_clock(dt)
    return respond({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
