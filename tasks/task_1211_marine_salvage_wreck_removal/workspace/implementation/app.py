#!/usr/bin/env python3
"""Marine Salvage & Wreck Removal API — reference implementation (Flask, in-memory)."""

import os
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from fractions import Fraction

from flask import Flask, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml / PRD.md)
# ---------------------------------------------------------------------------

ROLES = {
    "SalvageMaster",
    "ContractsOfficer",
    "MarineSurveyor",
    "EnvironmentalOfficer",
    "OperationsDirector",
    "Arbitrator",
    "InsurerSurveyor",
}

CASUALTY_TYPES = {"GROUNDING", "COLLISION", "FIRE", "SUNK"}
RISK_TIERS = {"TIER_1", "TIER_2", "TIER_3"}
PLAN_METHODS = {"REFLOAT", "LIGHTERING", "TOWAGE", "WRECK_REMOVAL"}
EQUIP_CLASSES = {"TUG", "CRANE_BARGE", "PONTOON", "OIL_RESPONSE"}
CONTRACT_FORMS = {"FIXED_PRICE", "NO_CURE_NO_PAY"}
AGENCY_TYPES = {"COAST_GUARD", "PORT_AUTHORITY", "ENV_AGENCY"}
CHARTER_PURPOSES = {"SALVAGE", "POLLUTION_RESPONSE"}
PHASE_TYPES = {"MOBILIZATION", "LIGHTERING", "REFLOAT", "TOWAGE", "WRECK_REMOVAL", "DEMOBILIZATION"}
POLLUTANT_CLASSES = {"OIL_PERSISTENT", "OIL_NON_PERSISTENT", "CHEMICAL", "DEBRIS"}
PROPERTY_TYPES = {"BUNKERS", "CARGO", "VESSEL_HULL", "WRECK_DEBRIS"}
ENTRY_TYPES = {"DAILY_LOG", "COST_LOG", "POLLUTION_REPORT", "SURVEY_REPORT"}
DISPOSE_METHODS = {"REDELIVER", "SELL", "SCRAP"}
DISBURSE_MODES = {"RELEASE", "APPLY_TO_AWARD"}
TERMINATE_REASONS = {"MUTUAL", "NO_CURE"}
REVIEW_OUTCOMES = {"ACCEPT", "DEFICIENT"}

TIER_ORDER = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}

PERMIT_MAP = {
    "MOBILIZATION": ["PORT_AUTHORITY"],
    "LIGHTERING": ["COAST_GUARD", "ENV_AGENCY"],
    "REFLOAT": ["COAST_GUARD"],
    "TOWAGE": ["COAST_GUARD"],
    "WRECK_REMOVAL": ["COAST_GUARD", "ENV_AGENCY"],
    "DEMOBILIZATION": ["PORT_AUTHORITY"],
}

RISK_ADD = {
    "GROUNDING": Fraction(5, 100),
    "COLLISION": Fraction(8, 100),
    "FIRE": Fraction(10, 100),
    "SUNK": Fraction(15, 100),
}
ENV_ADD = {
    "TIER_1": Fraction(5, 100),
    "TIER_2": Fraction(10, 100),
    "TIER_3": Fraction(20, 100),
}
POLLUTANT_MULT = {
    "OIL_PERSISTENT": Fraction(15, 10),
    "OIL_NON_PERSISTENT": Fraction(12, 10),
    "CHEMICAL": Fraction(18, 10),
    "DEBRIS": Fraction(1, 1),
}

T1_CAP = 100000000
T2_CAP = 500000000
PROVISIONAL_PCT = Fraction(12, 100)
SECURITY_MULTIPLIER = Fraction(125, 100)
FIXED_SECURITY_PCT = Fraction(30, 100)
STANDBY_FACTOR = Fraction(1, 2)
DEMURRAGE_FACTOR = Fraction(3, 2)
SCOPIC_UPLIFT_MULT = Fraction(125, 100)
OVERRUN_MULT = Fraction(110, 100)
WEATHER_BUFFER = timedelta(hours=6)

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

OPEN_POLLUTION_STATUSES = {"REPORTED", "ESCALATED", "CONTAINED"}
ACTIVE_CHARTER_STATUSES = {"BOOKED", "ON_HIRE", "STANDBY_WEATHER", "STANDBY_ENV"}
TERMINAL_CONTRACT_STATUSES = {"SETTLED", "TERMINATED"}
TERMINAL_PHASE_STATUSES = {"COMPLETE", "ABORTED"}
TERMINAL_CUSTODY_STATUSES = {"REDELIVERED", "SOLD", "DISPOSED"}

# ---------------------------------------------------------------------------
# In-memory store (fresh per process; no seeding)
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.casualties = {}
        self.assessments = {}
        self.plans = {}
        self.contracts = {}
        self.securities = {}
        self.permits = {}
        self.assets = {}
        self.charters = {}
        self.windows = {}
        self.phases = {}
        self.pollution_events = {}
        self.properties = {}
        self.storage_sites = {}
        self.awards = {}
        self.doc_packs = {}
        self.doc_entries = {}


db = Store()

# ---------------------------------------------------------------------------
# Errors and envelope
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return fmt_ts(datetime.now(timezone.utc))


def new_request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(22))


def success(data, code=200, is_list=False, pagination=None):
    meta = {"api_request_id": new_request_id(), "api_request_timestamp": wall_now()}
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": {"api_request_id": new_request_id(), "api_request_timestamp": wall_now()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": {"api_request_id": new_request_id(), "api_request_timestamp": wall_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": {"api_request_id": new_request_id(), "api_request_timestamp": wall_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": {"api_request_id": new_request_id(), "api_request_timestamp": wall_now()},
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error."},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth (priority 1 & 2)
# ---------------------------------------------------------------------------


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers are required and role must be a declared role.")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN_ROLE", 403, "The declared role is not authorized for this endpoint.")


ALL_ROLES = list(ROLES)

# ---------------------------------------------------------------------------
# Serialization / entity helpers
# ---------------------------------------------------------------------------


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        else:
            out[k] = v
    return out


def mint(fields):
    db.seq += 1
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    e["created_at"] = db.clock
    e["updated_at"] = db.clock
    e["version"] = 1
    e["_seq"] = db.seq
    return e


def touch(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = db.clock


def get_or_404(table, entity_id, label="resource"):
    e = table.get(entity_id)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Referenced %s does not exist." % label)
    return e


def list_response(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success([serialize(e) for e in page], 200, is_list=True, pagination=pagination)


def filter_by(items, field, value):
    if value is None:
        return items
    return [e for e in items if e.get(field) == value]

# ---------------------------------------------------------------------------
# Schema validators (priority 0)
# ---------------------------------------------------------------------------


def body_dict():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return b


def _inv(msg):
    err("ERR_INVALID_REQUEST", 400, msg)


def f_str(b, k, required=True, default=None):
    v = b.get(k)
    if v is None:
        if required:
            _inv("Missing required field: %s" % k)
        return default
    if not isinstance(v, str):
        _inv("Field %s must be a string." % k)
    return v


def f_enum(b, k, allowed, required=True, default=None):
    v = b.get(k)
    if v is None:
        if required:
            _inv("Missing required field: %s" % k)
        return default
    if not isinstance(v, str) or v not in allowed:
        _inv("Field %s must be one of %s." % (k, sorted(allowed)))
    return v


def f_int(b, k, required=True, minimum=None, default=None):
    v = b.get(k)
    if v is None:
        if required:
            _inv("Missing required field: %s" % k)
        return default
    if not isinstance(v, int) or isinstance(v, bool):
        _inv("Field %s must be an integer." % k)
    if minimum is not None and v < minimum:
        _inv("Field %s is below its minimum." % k)
    return v


def f_num(b, k, required=True, minimum=None, strict_min=False, default=None):
    v = b.get(k)
    if v is None:
        if required:
            _inv("Missing required field: %s" % k)
        return default
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        _inv("Field %s must be a number." % k)
    if minimum is not None:
        if strict_min and not (v > minimum):
            _inv("Field %s must be greater than %s." % (k, minimum))
        if not strict_min and v < minimum:
            _inv("Field %s must be at least %s." % (k, minimum))
    return v


def f_bool(b, k, required=True, default=None):
    v = b.get(k)
    if v is None:
        if required:
            _inv("Missing required field: %s" % k)
        return default
    if not isinstance(v, bool):
        _inv("Field %s must be a boolean." % k)
    return v


def parse_dt_value(v, k):
    if not isinstance(v, str):
        _inv("Field %s must be an ISO 8601 datetime string." % k)
    s = v
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _inv("Field %s must be an ISO 8601 datetime string." % k)


def f_dt(b, k, required=True, default=None):
    v = b.get(k)
    if v is None:
        if required:
            _inv("Missing required field: %s" % k)
        return default
    return parse_dt_value(v, k)


def f_list(b, k, required=True, non_empty=False, default=None):
    v = b.get(k)
    if v is None:
        if required:
            _inv("Missing required field: %s" % k)
        return default
    if not isinstance(v, list):
        _inv("Field %s must be an array." % k)
    if non_empty and len(v) == 0:
        _inv("Field %s must be a non-empty array." % k)
    return v

# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def rhu(fr):
    """Round half up a Fraction to an integer."""
    return int((fr.numerator * 2 + fr.denominator) // (2 * fr.denominator))


def whole_hours(delta):
    return int(delta.total_seconds() // 3600)

# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def contracts_of_casualty(casualty_id):
    return sorted(
        [c for c in db.contracts.values() if c["casualty_id"] == casualty_id],
        key=lambda e: e["_seq"],
    )


def nonterminal_contract(casualty_id):
    cs = [c for c in contracts_of_casualty(casualty_id) if c["status"] not in TERMINAL_CONTRACT_STATUSES]
    return cs[-1] if cs else None


def latest_contract(casualty_id):
    cs = contracts_of_casualty(casualty_id)
    return cs[-1] if cs else None


def latest_approved_assessment(casualty_id):
    approved = [a for a in db.assessments.values()
                if a["casualty_id"] == casualty_id and a["status"] == "APPROVED"]
    if not approved:
        return None
    return max(approved, key=lambda a: a["casualty_seq"])


def latest_assessment(casualty_id):
    rows = [a for a in db.assessments.values() if a["casualty_id"] == casualty_id]
    if not rows:
        return None
    return max(rows, key=lambda a: a["casualty_seq"])


def rederive_asset_status(asset):
    active = any(
        ch["equipment_asset_id"] == asset["id"] and ch["status"] in ACTIVE_CHARTER_STATUSES
        for ch in db.charters.values()
    )
    new = "CHARTERED" if active else "AVAILABLE"
    if asset["status"] != new:
        asset["status"] = new
        touch(asset)


def recompute_site_allocated(site):
    alloc = sum(
        p["quantity_tonnes"]
        for p in db.properties.values()
        if p.get("storage_site_id") == site["id"]
        and p["custody_status"] in ("SECURED_ASHORE", "LIENED")
    )
    if site["allocated_tonnes"] != alloc:
        site["allocated_tonnes"] = alloc
        touch(site)


def booked_hours(ch):
    return whole_hours(ch["window_end"] - ch["window_start"])


def booked_days(ch):
    return rhu(Fraction(booked_hours(ch), 24))


def recompute_provisional_exposure(event):
    total = 0
    for ch in db.charters.values():
        if (ch["purpose"] == "POLLUTION_RESPONSE"
                and ch.get("pollution_event_id") == event["id"]
                and ch["casualty_id"] == event["casualty_id"]):
            asset = db.assets.get(ch["equipment_asset_id"])
            if asset is None:
                continue
            line = rhu(Fraction(asset["day_rate_cents"]) * SCOPIC_UPLIFT_MULT) * booked_days(ch)
            total += line
    if event["provisional_exposure_cents"] != total:
        event["provisional_exposure_cents"] = total
        touch(event)


def find_award_and_scopic_contract(casualty_id):
    """Return (award, contract) for the casualty's latest contract that has an award."""
    for c in reversed(contracts_of_casualty(casualty_id)):
        award = next((a for a in db.awards.values() if a["contract_id"] == c["id"]), None)
        if award is not None:
            return award, c
    return None, latest_contract(casualty_id)


def recompute_special_compensation(event):
    if event["final_exposure_cents"] is None:
        return
    award, contract = find_award_and_scopic_contract(event["casualty_id"])
    if contract is not None and contract["scopic_clause_included"] and award is not None:
        payable = max(0, event["final_exposure_cents"] - award["computed_amount_cents"])
    else:
        payable = event["final_exposure_cents"]
    if event["special_compensation_payable_cents"] != payable:
        event["special_compensation_payable_cents"] = payable
        touch(event)


def recompute_posture(casualty):
    open_events = [e for e in db.pollution_events.values()
                   if e["casualty_id"] == casualty["id"] and e["status"] in OPEN_POLLUTION_STATUSES]
    if any(e["tier"] in ("TIER_2", "TIER_3") for e in open_events):
        new = "ENV_HOLD"
    elif any(e["tier"] == "TIER_1" for e in open_events):
        new = "ENV_WATCH"
    else:
        new = "ENV_CLEAR"
    old = casualty["env_posture"]
    if new == old:
        return
    casualty["env_posture"] = new
    touch(casualty)
    if new == "ENV_HOLD":
        # CASCADE A link 2: every ACTIVE phase of this casualty's contracts -> ENV_SUSPENDED
        for ph in db.phases.values():
            ct = db.contracts.get(ph["contract_id"])
            if ct is None or ct["casualty_id"] != casualty["id"]:
                continue
            if ph["status"] != "ACTIVE":
                continue
            ph["status"] = "ENV_SUSPENDED"
            touch(ph)
            # CASCADE A link 3: linked ON_HIRE charters -> STANDBY_ENV
            for chid in ph["charter_ids"] or []:
                ch = db.charters.get(chid)
                if ch is not None and ch["status"] == "ON_HIRE":
                    ch["status"] = "STANDBY_ENV"
                    ch["_standby_open"] = db.clock
                    touch(ch)


def close_standby_interval(ch):
    if ch.get("_standby_open") is not None:
        ch["standby_hours"] = ch.get("standby_hours", 0) + whole_hours(db.clock - ch["_standby_open"])
        ch["_standby_open"] = None


def compute_charter_cost(ch):
    """Runs at off-hire: day buckets and total_cost_cents (pinned rounding order)."""
    asset = db.assets[ch["equipment_asset_id"]]
    booked = booked_hours(ch)
    elapsed = whole_hours(ch["off_hire_at"] - ch["on_hire_at"])
    dem_hours = max(0, elapsed - booked)
    standby = ch.get("standby_hours", 0)
    active = elapsed - standby - dem_hours
    dem_days = rhu(Fraction(dem_hours, 24))
    std_days = rhu(Fraction(standby, 24))
    act_days = rhu(Fraction(active, 24))
    rate = asset["day_rate_cents"]
    total = (act_days * rhu(Fraction(rate))
             + std_days * rhu(Fraction(rate) * STANDBY_FACTOR)
             + dem_days * rhu(Fraction(rate) * DEMURRAGE_FACTOR))
    ch["active_days"] = act_days
    ch["standby_days"] = std_days
    ch["demurrage_days"] = dem_days
    ch["total_cost_cents"] = total


def recompute_contract_costs(casualty_id):
    total = sum(
        ch["total_cost_cents"] or 0
        for ch in db.charters.values()
        if ch["casualty_id"] == casualty_id and ch["status"] == "OFF_HIRE"
    )
    for c in contracts_of_casualty(casualty_id):
        changed = False
        if c["cost_to_date_cents"] != total:
            c["cost_to_date_cents"] = total
            changed = True
        if c["form"] == "FIXED_PRICE":
            threshold = rhu(Fraction(c["fixed_price_cents"]) * OVERRUN_MULT)
            flag = total > threshold
            if c["overrun_flag"] != flag:
                c["overrun_flag"] = flag
                changed = True
        elif c["overrun_flag"]:
            c["overrun_flag"] = False
            changed = True
        if changed:
            touch(c)


def off_hire_charter(ch):
    """Shared off-hire logic (manual action and termination cascade)."""
    close_standby_interval(ch)
    ch["off_hire_at"] = db.clock
    ch["status"] = "OFF_HIRE"
    compute_charter_cost(ch)
    touch(ch)
    asset = db.assets.get(ch["equipment_asset_id"])
    if asset is not None:
        rederive_asset_status(asset)
    recompute_contract_costs(ch["casualty_id"])
    if ch["purpose"] == "POLLUTION_RESPONSE" and ch.get("pollution_event_id"):
        ev = db.pollution_events.get(ch["pollution_event_id"])
        if ev is not None:
            recompute_provisional_exposure(ev)


def casualty_lifecycle_lift(casualty, from_state, to_state):
    if casualty["lifecycle_status"] == from_state:
        casualty["lifecycle_status"] = to_state
        touch(casualty)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = body_dict()
    to = f_dt(body, "to_iso8601")
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    db.clock = to
    expired_permits = []
    for p in sorted(db.permits.values(), key=lambda e: e["_seq"]):
        if p["status"] in ("REQUESTED", "GRANTED", "SUSPENDED") and to > p["valid_to"]:
            p["status"] = "EXPIRED"
            touch(p)
            expired_permits.append(p["id"])
    expired_windows = []
    for w in sorted(db.windows.values(), key=lambda e: e["_seq"]):
        if w["status"] == "OPEN" and to > w["window_end"]:
            w["status"] = "EXPIRED"
            touch(w)
            expired_windows.append(w["id"])
    return success({
        "current_utc": fmt_ts(db.clock),
        "expired_permit_ids": expired_permits,
        "expired_window_ids": expired_windows,
    })


# ---------------------------------------------------------------------------
# Casualties
# ---------------------------------------------------------------------------


@app.route("/casualties", methods=["POST"])
def create_casualty():
    body = body_dict()
    vessel_name = f_str(body, "vessel_name")
    casualty_type = f_enum(body, "casualty_type", CASUALTY_TYPES)
    declared = f_int(body, "declared_salved_value_cents", minimum=1)
    position = f_str(body, "position")
    note = f_str(body, "pollutant_inventory_note", required=False, default="")
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    cas = mint({
        "vessel_name": vessel_name,
        "casualty_type": casualty_type,
        "declared_salved_value_cents": declared,
        "position": position,
        "pollutant_inventory_note": note,
        "lifecycle_status": "REPORTED",
        "env_posture": "ENV_CLEAR",
    })
    db.casualties[cas["id"]] = cas
    return success(serialize(cas), 201)


@app.route("/casualties", methods=["GET"])
def list_casualties():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.casualties.values())
    items = filter_by(items, "lifecycle_status", request.args.get("lifecycle_status"))
    items = filter_by(items, "env_posture", request.args.get("env_posture"))
    return list_response(items)


@app.route("/casualties/<casualty_id>", methods=["GET"])
def get_casualty(casualty_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    cas = get_or_404(db.casualties, casualty_id, "casualty")
    return success(serialize(cas))


@app.route("/casualties/<casualty_id>/close", methods=["POST"])
def close_casualty(casualty_id):
    _, role = authenticate()
    authorize(role, ["OperationsDirector"])
    cas = get_or_404(db.casualties, casualty_id, "casualty")
    if cas["lifecycle_status"] == "CLOSED":
        err("ERR_ALREADY_TERMINAL", 409, "Casualty is already CLOSED.")
    if cas["lifecycle_status"] != "OPERATIONS_COMPLETE":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Casualty must be OPERATIONS_COMPLETE to close.")
    for c in contracts_of_casualty(casualty_id):
        if c["status"] not in TERMINAL_CONTRACT_STATUSES:
            err("ERR_CASUALTY_NOT_CLOSABLE", 422,
                "Every contract of the casualty must be SETTLED or TERMINATED.")
    for ev in db.pollution_events.values():
        if ev["casualty_id"] == casualty_id and ev["status"] in OPEN_POLLUTION_STATUSES:
            err("ERR_CASUALTY_NOT_CLOSABLE", 422,
                "Open pollution events block casualty closure.")
    cas["lifecycle_status"] = "CLOSED"
    touch(cas)
    return success(serialize(cas))


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------


@app.route("/assessments", methods=["POST"])
def create_assessment():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    expected_version = f_int(body, "expected_casualty_version")
    tier = f_enum(body, "pollution_risk_tier", RISK_TIERS)
    wreck = f_bool(body, "wreck_removal_required")
    est_cost = f_int(body, "estimated_cost_cents", minimum=1)
    notes = f_str(body, "notes", required=False, default="")
    uid, role = authenticate()
    authorize(role, ["MarineSurveyor"])
    cas = get_or_404(db.casualties, casualty_id, "casualty")
    # OCC (priority 11)
    if expected_version != cas["version"]:
        err("ERR_STALE_CASUALTY_VERSION", 412,
            "expected_casualty_version does not match the casualty's current version.")
    seqs = [a["casualty_seq"] for a in db.assessments.values() if a["casualty_id"] == casualty_id]
    next_seq = (max(seqs) + 1) if seqs else 1
    # Supersede SUBMITTED siblings
    for a in db.assessments.values():
        if a["casualty_id"] == casualty_id and a["status"] == "SUBMITTED":
            a["status"] = "SUPERSEDED"
            touch(a)
    a = mint({
        "casualty_id": casualty_id,
        "casualty_seq": next_seq,
        "assessor_id": uid,
        "pollution_risk_tier": tier,
        "wreck_removal_required": wreck,
        "estimated_cost_cents": est_cost,
        "notes": notes,
        "status": "SUBMITTED",
        "reviewer_id": None,
    })
    db.assessments[a["id"]] = a
    touch(cas)  # creation increments the casualty's version
    return success(serialize(a), 201)


@app.route("/assessments", methods=["GET"])
def list_assessments():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.assessments.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    a = get_or_404(db.assessments, assessment_id, "assessment")
    return success(serialize(a))


def _assessment_review(assessment_id, outcome):
    uid, role = authenticate()
    authorize(role, ["OperationsDirector"])
    a = get_or_404(db.assessments, assessment_id, "assessment")
    # SoD (priority 4) before state (priority 5)
    if uid == a["assessor_id"]:
        err("ERR_SOD_VIOLATION", 403, "Reviewer must differ from the assessment's assessor.")
    if a["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
        err("ERR_ALREADY_TERMINAL", 409, "Assessment is in a terminal state.")
    if a["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Assessment is not SUBMITTED.")
    a["status"] = outcome
    a["reviewer_id"] = uid
    touch(a)
    if outcome == "APPROVED":
        cas = db.casualties.get(a["casualty_id"])
        if cas is not None:
            casualty_lifecycle_lift(cas, "REPORTED", "ASSESSED")
    return success(serialize(a))


@app.route("/assessments/<assessment_id>/approve", methods=["POST"])
def approve_assessment(assessment_id):
    return _assessment_review(assessment_id, "APPROVED")


@app.route("/assessments/<assessment_id>/reject", methods=["POST"])
def reject_assessment(assessment_id):
    return _assessment_review(assessment_id, "REJECTED")


# ---------------------------------------------------------------------------
# Salvage plans
# ---------------------------------------------------------------------------


@app.route("/plans", methods=["POST"])
def create_plan():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    method = f_enum(body, "method", PLAN_METHODS)
    classes = f_list(body, "required_equipment_classes", non_empty=True)
    for c in classes:
        if not isinstance(c, str) or c not in EQUIP_CLASSES:
            _inv("required_equipment_classes entries must be valid equipment classes.")
    uid, role = authenticate()
    authorize(role, ["SalvageMaster"])
    get_or_404(db.casualties, casualty_id, "casualty")
    plan = mint({
        "casualty_id": casualty_id,
        "drafter_id": uid,
        "method": method,
        "required_equipment_classes": classes,
        "status": "DRAFT",
        "approver_id": None,
    })
    db.plans[plan["id"]] = plan
    return success(serialize(plan), 201)


@app.route("/plans", methods=["GET"])
def list_plans():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.plans.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    plan = get_or_404(db.plans, plan_id, "plan")
    return success(serialize(plan))


@app.route("/plans/<plan_id>/submit", methods=["POST"])
def submit_plan(plan_id):
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    plan = get_or_404(db.plans, plan_id, "plan")
    if plan["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a DRAFT plan can be submitted.")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return success(serialize(plan))


@app.route("/plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    uid, role = authenticate()
    authorize(role, ["OperationsDirector"])
    plan = get_or_404(db.plans, plan_id, "plan")
    if uid == plan["drafter_id"]:
        err("ERR_SOD_VIOLATION", 403, "Approver must differ from the plan's drafter.")
    if plan["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a SUBMITTED plan can be approved.")
    if latest_approved_assessment(plan["casualty_id"]) is None:
        err("ERR_ASSESSMENT_NOT_APPROVED", 422,
            "No APPROVED assessment exists for the casualty.")
    plan["status"] = "APPROVED"
    plan["approver_id"] = uid
    touch(plan)
    cas = db.casualties.get(plan["casualty_id"])
    if cas is not None:
        casualty_lifecycle_lift(cas, "ASSESSED", "PLANNED")
    return success(serialize(plan))


@app.route("/plans/<plan_id>/reject", methods=["POST"])
def reject_plan(plan_id):
    _, role = authenticate()
    authorize(role, ["OperationsDirector"])
    plan = get_or_404(db.plans, plan_id, "plan")
    if plan["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a SUBMITTED plan can be rejected.")
    plan["status"] = "DRAFT"
    touch(plan)
    return success(serialize(plan))


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@app.route("/contracts", methods=["POST"])
def create_contract():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    plan_id = f_str(body, "plan_id")
    form = f_enum(body, "form", CONTRACT_FORMS)
    fixed = body.get("fixed_price_cents")
    if form == "FIXED_PRICE":
        fixed = f_int(body, "fixed_price_cents", minimum=1)
    else:
        if fixed is not None:
            _inv("fixed_price_cents is forbidden unless form is FIXED_PRICE.")
    scopic = f_bool(body, "scopic_clause_included", required=False, default=False)
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    get_or_404(db.casualties, casualty_id, "casualty")
    get_or_404(db.plans, plan_id, "plan")
    if nonterminal_contract(casualty_id) is not None:
        err("ERR_DUPLICATE_ACTIVE_CONTRACT", 409,
            "Casualty already has a non-terminal contract.")
    c = mint({
        "casualty_id": casualty_id,
        "plan_id": plan_id,
        "form": form,
        "fixed_price_cents": fixed if form == "FIXED_PRICE" else None,
        "scopic_clause_included": scopic,
        "status": "DRAFT",
        "negotiation_round": 0,
        "provisional_award_cents": None,
        "security_required_cents": None,
        "cost_to_date_cents": 0,
        "overrun_flag": False,
        "terminate_reason": None,
    })
    db.contracts[c["id"]] = c
    return success(serialize(c), 201)


@app.route("/contracts", methods=["GET"])
def list_contracts():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.contracts.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "plan_id", request.args.get("plan_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


def _get_contract_any(contract_id):
    c = get_or_404(db.contracts, contract_id, "contract")
    return c


@app.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(_get_contract_any(contract_id)))


@app.route("/contracts/<contract_id>/offer", methods=["POST"])
def offer_contract(contract_id):
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = _get_contract_any(contract_id)
    if c["status"] in TERMINAL_CONTRACT_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state.")
    if c["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a DRAFT contract can be offered.")
    c["status"] = "OFFERED"
    c["negotiation_round"] = 1
    touch(c)
    return success(serialize(c))


@app.route("/contracts/<contract_id>/counter", methods=["POST"])
def counter_contract(contract_id):
    body = body_dict()
    expected = f_int(body, "expected_contract_version")
    if "terms_note" in body and body["terms_note"] is not None and not isinstance(body["terms_note"], str):
        _inv("terms_note must be a string.")
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = _get_contract_any(contract_id)
    if c["status"] in TERMINAL_CONTRACT_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state.")
    if c["status"] not in ("OFFERED", "COUNTERED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Counter-offer requires OFFERED or COUNTERED status.")
    if expected != c["version"]:
        err("ERR_STALE_CONTRACT_VERSION", 412,
            "expected_contract_version does not match the contract's current version.")
    c["status"] = "COUNTERED" if c["status"] == "OFFERED" else "OFFERED"
    c["negotiation_round"] += 1
    touch(c)
    return success(serialize(c))


@app.route("/contracts/<contract_id>/sign", methods=["POST"])
def sign_contract(contract_id):
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = _get_contract_any(contract_id)
    if c["status"] in TERMINAL_CONTRACT_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state.")
    if c["status"] not in ("OFFERED", "COUNTERED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Sign requires OFFERED or COUNTERED status.")
    latest = latest_assessment(c["casualty_id"])
    if latest is None or latest["status"] != "APPROVED":
        err("ERR_ASSESSMENT_NOT_APPROVED", 422,
            "The latest-created assessment of the casualty is not APPROVED.")
    plan = db.plans.get(c["plan_id"])
    if plan is None or plan["status"] != "APPROVED":
        err("ERR_PLAN_NOT_APPROVED", 422, "The contract's plan is not APPROVED.")
    cas = db.casualties[c["casualty_id"]]
    if c["form"] == "NO_CURE_NO_PAY":
        provisional = rhu(Fraction(cas["declared_salved_value_cents"]) * PROVISIONAL_PCT)
        security = rhu(Fraction(provisional) * SECURITY_MULTIPLIER)
    else:
        provisional = c["fixed_price_cents"]
        security = rhu(Fraction(c["fixed_price_cents"]) * FIXED_SECURITY_PCT)
    c["provisional_award_cents"] = provisional
    c["security_required_cents"] = security
    c["status"] = "SIGNED"
    touch(c)
    casualty_lifecycle_lift(cas, "PLANNED", "CONTRACTED")
    return success(serialize(c))


@app.route("/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = _get_contract_any(contract_id)
    if c["status"] in TERMINAL_CONTRACT_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state.")
    if c["status"] != "SIGNED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a SIGNED contract can be activated.")
    # Safety gate (priority 6) before fiscal gate (priority 10)
    latest = latest_approved_assessment(c["casualty_id"])
    if latest is not None and latest["pollution_risk_tier"] == "TIER_3":
        ok = any(
            p["casualty_id"] == c["casualty_id"]
            and p["agency_type"] == "ENV_AGENCY"
            and p["status"] == "GRANTED"
            for p in db.permits.values()
        )
        if not ok:
            err("ERR_ENV_CLEARANCE_REQUIRED", 422,
                "TIER_3 assessment requires a GRANTED ENV_AGENCY permit.")
    required = c["security_required_cents"] or 0
    covered = any(
        s["contract_id"] == c["id"] and s["held_cents"] >= required
        for s in db.securities.values()
    )
    if not covered:
        err("ERR_SECURITY_INSUFFICIENT", 422,
            "No deposit holds at least the required security amount.")
    c["status"] = "ACTIVE"
    touch(c)
    return success(serialize(c))


@app.route("/contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    body = body_dict()
    reason = f_enum(body, "reason", TERMINATE_REASONS)
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = _get_contract_any(contract_id)
    if c["status"] in TERMINAL_CONTRACT_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state.")
    if c["status"] in ("PERFORMANCE_COMPLETE", "AWARD_FINAL"):
        err("ERR_TERMINATION_NOT_ALLOWED", 422,
            "Termination is not available from PERFORMANCE_COMPLETE or AWARD_FINAL.")
    if c["status"] == "ACTIVE":
        if reason == "MUTUAL":
            err("ERR_TERMINATION_NOT_ALLOWED", 422,
                "Mutual termination from ACTIVE is forbidden.")
        if c["form"] != "NO_CURE_NO_PAY":
            err("ERR_NO_CURE_REQUIRES_NCNP", 422,
                "No-cure termination requires a NO_CURE_NO_PAY contract.")
    else:
        # DRAFT / OFFERED / COUNTERED / SIGNED: only MUTUAL is defined
        if reason != "MUTUAL":
            err("ERR_INVALID_STATE_TRANSITION", 409,
                "NO_CURE termination is only available from ACTIVE.")
    c["status"] = "TERMINATED"
    c["terminate_reason"] = reason
    touch(c)
    if reason == "NO_CURE":
        # Termination cascade
        for ph in db.phases.values():
            if ph["contract_id"] == c["id"] and ph["status"] in (
                    "PLANNED", "ACTIVE", "WEATHER_HOLD", "ENV_SUSPENDED"):
                ph["status"] = "ABORTED"
                touch(ph)
        for ch in sorted(db.charters.values(), key=lambda e: e["_seq"]):
            if ch["casualty_id"] != c["casualty_id"]:
                continue
            if ch["status"] in ("ON_HIRE", "STANDBY_WEATHER", "STANDBY_ENV"):
                off_hire_charter(ch)
            elif ch["status"] == "BOOKED":
                ch["status"] = "CANCELLED"
                touch(ch)
                asset = db.assets.get(ch["equipment_asset_id"])
                if asset is not None:
                    rederive_asset_status(asset)
    return success(serialize(c))


@app.route("/contracts/<contract_id>/settle", methods=["POST"])
def settle_contract(contract_id):
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = _get_contract_any(contract_id)
    if c["status"] in TERMINAL_CONTRACT_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state.")
    if c["status"] != "AWARD_FINAL":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an AWARD_FINAL contract can settle.")
    # Priority 8 (docs) before priority 10 (security)
    for pack in db.doc_packs.values():
        if pack["contract_id"] == c["id"] and pack["status"] != "ACCEPTED":
            err("ERR_DOCS_NOT_ACCEPTED", 422,
                "Every DocPack of the contract must be ACCEPTED.")
    for s in db.securities.values():
        if s["contract_id"] == c["id"] and s["status"] != "CLOSED":
            err("ERR_SECURITY_DISBURSE_NOT_ALLOWED", 422,
                "Every SecurityDeposit of the contract must be CLOSED.")
    c["status"] = "SETTLED"
    touch(c)
    return success(serialize(c))


# ---------------------------------------------------------------------------
# Securities
# ---------------------------------------------------------------------------


@app.route("/securities", methods=["POST"])
def create_security():
    body = body_dict()
    contract_id = f_str(body, "contract_id")
    lodged = f_int(body, "lodged_amount_cents", minimum=1)
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = get_or_404(db.contracts, contract_id, "contract")
    if c["status"] != "SIGNED":
        err("ERR_CONTRACT_NOT_ACTIVE", 422,
            "Security may only be lodged against a SIGNED contract.")
    s = mint({
        "contract_id": contract_id,
        "lodged_amount_cents": lodged,
        "held_cents": lodged,
        "released_cents": 0,
        "applied_cents": 0,
        "status": "LODGED",
    })
    db.securities[s["id"]] = s
    return success(serialize(s), 201)


@app.route("/securities", methods=["GET"])
def list_securities():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.securities.values())
    items = filter_by(items, "contract_id", request.args.get("contract_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/securities/<security_id>", methods=["GET"])
def get_security(security_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.securities, security_id, "security")))


@app.route("/securities/<security_id>/disburse", methods=["POST"])
def disburse_security(security_id):
    body = body_dict()
    mode = f_enum(body, "mode", DISBURSE_MODES)
    amount = f_int(body, "amount_cents", minimum=1)
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    s = get_or_404(db.securities, security_id, "security")
    if s["status"] == "CLOSED":
        err("ERR_ALREADY_TERMINAL", 409, "Security deposit is CLOSED.")
    c = db.contracts.get(s["contract_id"])
    # Mode legality (fiscal) before amount check (fiscal); scaffold precondition order
    if mode == "RELEASE":
        if c is None or c["status"] not in ("SETTLED", "TERMINATED"):
            err("ERR_SECURITY_DISBURSE_NOT_ALLOWED", 422,
                "RELEASE requires the contract to be SETTLED or TERMINATED.")
    else:  # APPLY_TO_AWARD
        award = next((a for a in db.awards.values() if a["contract_id"] == s["contract_id"]), None)
        if award is None or award["status"] != "PAID":
            err("ERR_SECURITY_DISBURSE_NOT_ALLOWED", 422,
                "APPLY_TO_AWARD requires the contract's award to be PAID.")
    if amount > s["held_cents"]:
        err("ERR_SECURITY_DISBURSE_EXCEEDS_HELD", 422,
            "Disburse amount exceeds held_cents.")
    s["held_cents"] -= amount
    if mode == "RELEASE":
        s["released_cents"] += amount
    else:
        s["applied_cents"] += amount
    s["status"] = "CLOSED" if s["held_cents"] == 0 else "PARTIALLY_DISBURSED"
    touch(s)
    return success(serialize(s))


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------


@app.route("/permits", methods=["POST"])
def create_permit():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    agency = f_enum(body, "agency_type", AGENCY_TYPES)
    valid_from = f_dt(body, "valid_from")
    valid_to = f_dt(body, "valid_to")
    if not valid_to > valid_from:
        _inv("valid_to must be later than valid_from.")
    _, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    get_or_404(db.casualties, casualty_id, "casualty")
    p = mint({
        "casualty_id": casualty_id,
        "agency_type": agency,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "REQUESTED",
    })
    db.permits[p["id"]] = p
    return success(serialize(p), 201)


@app.route("/permits", methods=["GET"])
def list_permits():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.permits.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "agency_type", request.args.get("agency_type"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.permits, permit_id, "permit")))


def _permit_action(permit_id, allowed_from, to_state):
    _, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    p = get_or_404(db.permits, permit_id, "permit")
    if p["status"] in ("REVOKED", "EXPIRED"):
        err("ERR_ALREADY_TERMINAL", 409, "Permit is in a terminal state.")
    if p["status"] not in allowed_from:
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Permit state %s does not permit this action." % p["status"])
    p["status"] = to_state
    touch(p)
    return success(serialize(p))


@app.route("/permits/<permit_id>/grant", methods=["POST"])
def grant_permit(permit_id):
    return _permit_action(permit_id, {"REQUESTED"}, "GRANTED")


@app.route("/permits/<permit_id>/suspend", methods=["POST"])
def suspend_permit(permit_id):
    return _permit_action(permit_id, {"GRANTED"}, "SUSPENDED")


@app.route("/permits/<permit_id>/reinstate", methods=["POST"])
def reinstate_permit(permit_id):
    return _permit_action(permit_id, {"SUSPENDED"}, "GRANTED")


@app.route("/permits/<permit_id>/revoke", methods=["POST"])
def revoke_permit(permit_id):
    return _permit_action(permit_id, {"GRANTED", "SUSPENDED"}, "REVOKED")


# ---------------------------------------------------------------------------
# Equipment assets
# ---------------------------------------------------------------------------


@app.route("/equipment-assets", methods=["POST"])
def create_asset():
    body = body_dict()
    asset_class = f_enum(body, "asset_class", EQUIP_CLASSES)
    day_rate = f_int(body, "day_rate_cents", minimum=1)
    max_hs = f_num(body, "max_hs_meters", minimum=0, strict_min=True)
    _, role = authenticate()
    authorize(role, ["OperationsDirector"])
    a = mint({
        "asset_class": asset_class,
        "day_rate_cents": day_rate,
        "max_hs_meters": max_hs,
        "status": "AVAILABLE",
    })
    db.assets[a["id"]] = a
    return success(serialize(a), 201)


@app.route("/equipment-assets", methods=["GET"])
def list_assets():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.assets.values())
    items = filter_by(items, "asset_class", request.args.get("asset_class"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/equipment-assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.assets, asset_id, "asset")))


# ---------------------------------------------------------------------------
# Equipment charters
# ---------------------------------------------------------------------------


@app.route("/charters", methods=["POST"])
def create_charter():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    asset_id = f_str(body, "equipment_asset_id")
    window_start = f_dt(body, "window_start")
    window_end = f_dt(body, "window_end")
    if not window_end > window_start:
        _inv("window_end must be later than window_start.")
    purpose = f_enum(body, "purpose", CHARTER_PURPOSES)
    pollution_event_id = body.get("pollution_event_id")
    if purpose == "POLLUTION_RESPONSE":
        if pollution_event_id is None:
            _inv("pollution_event_id is required when purpose is POLLUTION_RESPONSE.")
        if not isinstance(pollution_event_id, str):
            _inv("pollution_event_id must be a string.")
    else:
        if pollution_event_id is not None:
            _inv("pollution_event_id must be null unless purpose is POLLUTION_RESPONSE.")
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    get_or_404(db.casualties, casualty_id, "casualty")
    asset = get_or_404(db.assets, asset_id, "equipment asset")
    event = None
    if pollution_event_id is not None:
        event = get_or_404(db.pollution_events, pollution_event_id, "pollution event")
    # Priority 7: half-open overlap on the same asset
    for other in db.charters.values():
        if other["equipment_asset_id"] != asset_id:
            continue
        if other["status"] not in ACTIVE_CHARTER_STATUSES:
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            err("ERR_CHARTER_OVERLAP", 409,
                "Booked window overlaps another active charter on the same asset.")
    # Priority 8: contract operable and asset class within plan requirements
    c = nonterminal_contract(casualty_id)
    if c is None or c["status"] not in ("SIGNED", "ACTIVE", "PERFORMANCE_COMPLETE"):
        err("ERR_CONTRACT_NOT_ACTIVE", 422,
            "The casualty's contract must be SIGNED, ACTIVE, or PERFORMANCE_COMPLETE to book a charter.")
    plan = db.plans.get(c["plan_id"])
    if plan is None or asset["asset_class"] not in plan["required_equipment_classes"]:
        err("ERR_ASSET_CLASS_NOT_REQUIRED", 422,
            "The asset's class is not in the contract plan's required equipment classes.")
    ch = mint({
        "casualty_id": casualty_id,
        "equipment_asset_id": asset_id,
        "pollution_event_id": pollution_event_id,
        "purpose": purpose,
        "window_start": window_start,
        "window_end": window_end,
        "status": "BOOKED",
        "on_hire_at": None,
        "off_hire_at": None,
        "standby_hours": 0,
        "active_days": None,
        "standby_days": None,
        "demurrage_days": None,
        "total_cost_cents": None,
        "linked_phase_id": None,
        "_standby_open": None,
    })
    db.charters[ch["id"]] = ch
    if asset["status"] != "CHARTERED":
        asset["status"] = "CHARTERED"
        touch(asset)
    if event is not None:
        recompute_provisional_exposure(event)
    return success(serialize(ch), 201)


@app.route("/charters", methods=["GET"])
def list_charters():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.charters.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "equipment_asset_id", request.args.get("equipment_asset_id"))
    items = filter_by(items, "pollution_event_id", request.args.get("pollution_event_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/charters/<charter_id>", methods=["GET"])
def get_charter(charter_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.charters, charter_id, "charter")))


@app.route("/charters/<charter_id>/on-hire", methods=["POST"])
def on_hire_charter(charter_id):
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    ch = get_or_404(db.charters, charter_id, "charter")
    if ch["status"] in ("OFF_HIRE", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Charter is in a terminal state.")
    if ch["status"] != "BOOKED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a BOOKED charter can go on hire.")
    # Priority 7 (window) before priority 8 (contract state)
    now = db.clock
    if not (now >= ch["window_start"] and now < ch["window_end"]):
        err("ERR_CHARTER_WINDOW_NOT_OPEN", 422,
            "The logical clock is outside the booked window.")
    c = nonterminal_contract(ch["casualty_id"])
    if c is None or c["status"] not in ("ACTIVE", "PERFORMANCE_COMPLETE"):
        err("ERR_CONTRACT_NOT_ACTIVE", 422,
            "The casualty's contract must be ACTIVE or PERFORMANCE_COMPLETE for on-hire.")
    ch["status"] = "ON_HIRE"
    ch["on_hire_at"] = now
    touch(ch)
    return success(serialize(ch))


@app.route("/charters/<charter_id>/off-hire", methods=["POST"])
def off_hire_charter_endpoint(charter_id):
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    ch = get_or_404(db.charters, charter_id, "charter")
    if ch["status"] in ("OFF_HIRE", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Charter is in a terminal state.")
    if ch["status"] not in ("ON_HIRE", "STANDBY_WEATHER", "STANDBY_ENV"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only an ON_HIRE or standby charter can go off hire.")
    off_hire_charter(ch)
    return success(serialize(ch))


# ---------------------------------------------------------------------------
# Weather windows
# ---------------------------------------------------------------------------


@app.route("/weather-windows", methods=["POST"])
def create_window():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    window_start = f_dt(body, "window_start")
    window_end = f_dt(body, "window_end")
    if not window_end > window_start:
        _inv("window_end must be later than window_start.")
    hs = f_num(body, "forecast_hs_meters", minimum=0)
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    get_or_404(db.casualties, casualty_id, "casualty")
    w = mint({
        "casualty_id": casualty_id,
        "window_start": window_start,
        "window_end": window_end,
        "forecast_hs_meters": hs,
        "status": "OPEN",
    })
    db.windows[w["id"]] = w
    return success(serialize(w), 201)


@app.route("/weather-windows", methods=["GET"])
def list_windows():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.windows.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/weather-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.windows, window_id, "weather window")))


# ---------------------------------------------------------------------------
# Operation phases
# ---------------------------------------------------------------------------


@app.route("/phases", methods=["POST"])
def create_phase():
    body = body_dict()
    contract_id = f_str(body, "contract_id")
    phase_type = f_enum(body, "phase_type", PHASE_TYPES)
    duration = f_int(body, "planned_duration_hours", minimum=1)
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    c = get_or_404(db.contracts, contract_id, "contract")
    if c["status"] != "ACTIVE":
        err("ERR_CONTRACT_NOT_ACTIVE", 422, "Phases are created under an ACTIVE contract.")
    ph = mint({
        "contract_id": contract_id,
        "phase_type": phase_type,
        "planned_duration_hours": duration,
        "status": "PLANNED",
        "weather_window_id": None,
        "charter_ids": [],
        "activated_at": None,
    })
    db.phases[ph["id"]] = ph
    return success(serialize(ph), 201)


@app.route("/phases", methods=["GET"])
def list_phases():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.phases.values())
    items = filter_by(items, "contract_id", request.args.get("contract_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/phases/<phase_id>", methods=["GET"])
def get_phase(phase_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.phases, phase_id, "phase")))


@app.route("/phases/<phase_id>/activate", methods=["POST"])
def activate_phase(phase_id):
    body = body_dict()
    window_id = f_str(body, "weather_window_id")
    charter_ids = f_list(body, "charter_ids", non_empty=True)
    for cid in charter_ids:
        if not isinstance(cid, str):
            _inv("charter_ids entries must be strings.")
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    ph = get_or_404(db.phases, phase_id, "phase")
    window = get_or_404(db.windows, window_id, "weather window")
    charters = [get_or_404(db.charters, cid, "charter") for cid in charter_ids]
    # Priority 5: phase state
    if ph["status"] in TERMINAL_PHASE_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Phase is in a terminal state.")
    if ph["status"] != "PLANNED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a PLANNED phase can be activated.")
    contract = db.contracts.get(ph["contract_id"])
    casualty = db.casualties.get(contract["casualty_id"]) if contract else None
    now = db.clock
    # Priority 6: safety gates
    if casualty is not None and casualty["env_posture"] == "ENV_HOLD":
        err("ERR_ENV_HOLD_ACTIVE", 422, "Casualty environmental posture is ENV_HOLD.")
    if window["status"] != "OPEN":
        err("ERR_WEATHER_WINDOW_INFEASIBLE", 422, "Weather window is not OPEN.")
    hs_limit = min(db.assets[ch["equipment_asset_id"]]["max_hs_meters"] for ch in charters)
    if window["forecast_hs_meters"] > hs_limit:
        err("ERR_WEATHER_LIMIT_EXCEEDED", 422,
            "Forecast significant wave height exceeds the attached assets' limits.")
    planned_end = now + timedelta(hours=ph["planned_duration_hours"])
    if now < window["window_start"] + WEATHER_BUFFER or planned_end > window["window_end"] - WEATHER_BUFFER:
        err("ERR_WEATHER_WINDOW_INFEASIBLE", 422,
            "Planned execution does not fit inside the weather window with 6h buffers.")
    # Priority 7: permit gates
    for agency in PERMIT_MAP[ph["phase_type"]]:
        of_type = [p for p in db.permits.values()
                   if p["casualty_id"] == contract["casualty_id"]
                   and p["agency_type"] == agency]
        grants = [p for p in of_type if p["status"] == "GRANTED"]
        if not grants:
            # A permit swept to EXPIRED by the clock fails the validity check
            # like any other out-of-window permit (PRD 3.5).
            if any(p["status"] == "EXPIRED" for p in of_type):
                err("ERR_PERMIT_NOT_VALID", 422,
                    "The %s permit has expired." % agency)
            err("ERR_PERMIT_MISSING", 422,
                "No GRANTED %s permit exists for the casualty." % agency)
        if not any(p["valid_from"] <= now and p["valid_to"] >= planned_end for p in grants):
            err("ERR_PERMIT_NOT_VALID", 422,
                "The %s permit does not cover the planned execution window." % agency)
    # Priority 8: charter linkage
    for ch in charters:
        if ch["casualty_id"] != contract["casualty_id"] or ch["status"] != "ON_HIRE":
            err("ERR_INVALID_STATE_TRANSITION", 409,
                "Attached charters must belong to the casualty and be ON_HIRE.")
    ph["status"] = "ACTIVE"
    ph["weather_window_id"] = window_id
    ph["charter_ids"] = list(charter_ids)
    ph["activated_at"] = now
    touch(ph)
    for ch in charters:
        ch["linked_phase_id"] = ph["id"]
        touch(ch)
    if casualty is not None:
        casualty_lifecycle_lift(casualty, "CONTRACTED", "IN_OPERATION")
    return success(serialize(ph))


def _phase_charters(ph):
    return [db.charters[cid] for cid in (ph["charter_ids"] or []) if cid in db.charters]


@app.route("/phases/<phase_id>/hold-weather", methods=["POST"])
def hold_weather_phase(phase_id):
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    ph = get_or_404(db.phases, phase_id, "phase")
    if ph["status"] in TERMINAL_PHASE_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Phase is in a terminal state.")
    if ph["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an ACTIVE phase can be held for weather.")
    ph["status"] = "WEATHER_HOLD"
    touch(ph)
    for ch in _phase_charters(ph):
        if ch["status"] == "ON_HIRE":
            ch["status"] = "STANDBY_WEATHER"
            ch["_standby_open"] = db.clock
            touch(ch)
    return success(serialize(ph))


@app.route("/phases/<phase_id>/resume", methods=["POST"])
def resume_phase(phase_id):
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    ph = get_or_404(db.phases, phase_id, "phase")
    if ph["status"] in TERMINAL_PHASE_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Phase is in a terminal state.")
    if ph["status"] not in ("WEATHER_HOLD", "ENV_SUSPENDED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only a WEATHER_HOLD or ENV_SUSPENDED phase can resume.")
    contract = db.contracts.get(ph["contract_id"])
    casualty = db.casualties.get(contract["casualty_id"]) if contract else None
    if casualty is not None and casualty["env_posture"] == "ENV_HOLD":
        err("ERR_ENV_HOLD_ACTIVE", 422, "Casualty environmental posture is ENV_HOLD.")
    from_standby = "STANDBY_WEATHER" if ph["status"] == "WEATHER_HOLD" else "STANDBY_ENV"
    ph["status"] = "ACTIVE"
    touch(ph)
    for ch in _phase_charters(ph):
        if ch["status"] == from_standby:
            close_standby_interval(ch)
            ch["status"] = "ON_HIRE"
            touch(ch)
    return success(serialize(ph))


@app.route("/phases/<phase_id>/complete", methods=["POST"])
def complete_phase(phase_id):
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    ph = get_or_404(db.phases, phase_id, "phase")
    if ph["status"] in TERMINAL_PHASE_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Phase is in a terminal state.")
    if ph["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an ACTIVE phase can complete.")
    ph["status"] = "COMPLETE"
    touch(ph)
    # CASCADE B link 1: every phase terminal (and at least one exists) -> contract PERFORMANCE_COMPLETE
    contract = db.contracts.get(ph["contract_id"])
    if contract is not None and contract["status"] == "ACTIVE":
        phases = [p for p in db.phases.values() if p["contract_id"] == contract["id"]]
        if phases and all(p["status"] in TERMINAL_PHASE_STATUSES for p in phases):
            contract["status"] = "PERFORMANCE_COMPLETE"
            touch(contract)
            # CASCADE B link 2: casualty IN_OPERATION -> OPERATIONS_COMPLETE
            casualty = db.casualties.get(contract["casualty_id"])
            if casualty is not None:
                casualty_lifecycle_lift(casualty, "IN_OPERATION", "OPERATIONS_COMPLETE")
    return success(serialize(ph))


# ---------------------------------------------------------------------------
# Pollution events
# ---------------------------------------------------------------------------


@app.route("/pollution-events", methods=["POST"])
def create_pollution_event():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    pollutant_class = f_enum(body, "pollutant_class", POLLUTANT_CLASSES)
    tier = f_enum(body, "tier", RISK_TIERS)
    volume = f_num(body, "est_volume_m3", minimum=0)
    _, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    cas = get_or_404(db.casualties, casualty_id, "casualty")
    ev = mint({
        "casualty_id": casualty_id,
        "pollutant_class": pollutant_class,
        "tier": tier,
        "est_volume_m3": volume,
        "status": "REPORTED",
        "provisional_exposure_cents": 0,
        "final_exposure_cents": None,
        "special_compensation_payable_cents": 0,
    })
    db.pollution_events[ev["id"]] = ev
    recompute_posture(cas)
    return success(serialize(ev), 201)


@app.route("/pollution-events", methods=["GET"])
def list_pollution_events():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.pollution_events.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/pollution-events/<event_id>", methods=["GET"])
def get_pollution_event(event_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.pollution_events, event_id, "pollution event")))


@app.route("/pollution-events/<event_id>/escalate", methods=["POST"])
def escalate_pollution_event(event_id):
    body = body_dict()
    new_tier = f_enum(body, "new_tier", RISK_TIERS)
    _, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    ev = get_or_404(db.pollution_events, event_id, "pollution event")
    if ev["status"] == "VERIFIED_CLEAN":
        err("ERR_ALREADY_TERMINAL", 409, "Pollution event is VERIFIED_CLEAN.")
    if ev["status"] not in ("REPORTED", "CONTAINED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only a REPORTED or CONTAINED event can be escalated.")
    if TIER_ORDER[new_tier] <= TIER_ORDER[ev["tier"]]:
        err("ERR_POLLUTION_TIER_NOT_RAISED", 422,
            "new_tier must be strictly higher than the current tier.")
    ev["tier"] = new_tier
    ev["status"] = "ESCALATED"
    touch(ev)
    cas = db.casualties.get(ev["casualty_id"])
    if cas is not None:
        recompute_posture(cas)
    return success(serialize(ev))


@app.route("/pollution-events/<event_id>/contain", methods=["POST"])
def contain_pollution_event(event_id):
    _, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    ev = get_or_404(db.pollution_events, event_id, "pollution event")
    if ev["status"] == "VERIFIED_CLEAN":
        err("ERR_ALREADY_TERMINAL", 409, "Pollution event is VERIFIED_CLEAN.")
    if ev["status"] not in ("REPORTED", "ESCALATED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only a REPORTED or ESCALATED event can be contained.")
    ev["status"] = "CONTAINED"
    touch(ev)
    cas = db.casualties.get(ev["casualty_id"])
    if cas is not None:
        recompute_posture(cas)
    return success(serialize(ev))


@app.route("/pollution-events/<event_id>/verify-clean", methods=["POST"])
def verify_clean_pollution_event(event_id):
    _, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    ev = get_or_404(db.pollution_events, event_id, "pollution event")
    if ev["status"] == "VERIFIED_CLEAN":
        err("ERR_ALREADY_TERMINAL", 409, "Pollution event is VERIFIED_CLEAN.")
    if ev["status"] != "CONTAINED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only a CONTAINED event can be verified clean.")
    actual = sum(
        ch["total_cost_cents"] or 0
        for ch in db.charters.values()
        if ch["purpose"] == "POLLUTION_RESPONSE"
        and ch.get("pollution_event_id") == ev["id"]
        and ch["casualty_id"] == ev["casualty_id"]
        and ch["status"] == "OFF_HIRE"
    )
    ev["final_exposure_cents"] = rhu(Fraction(actual) * POLLUTANT_MULT[ev["pollutant_class"]])
    ev["status"] = "VERIFIED_CLEAN"
    touch(ev)
    recompute_special_compensation(ev)
    cas = db.casualties.get(ev["casualty_id"])
    if cas is not None:
        recompute_posture(cas)
    return success(serialize(ev))


# ---------------------------------------------------------------------------
# Recovered property
# ---------------------------------------------------------------------------


@app.route("/properties", methods=["POST"])
def create_property():
    body = body_dict()
    casualty_id = f_str(body, "casualty_id")
    property_type = f_enum(body, "property_type", PROPERTY_TYPES)
    quantity = f_num(body, "quantity_tonnes", minimum=0, strict_min=True)
    declared = f_int(body, "declared_value_cents", minimum=0)
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    get_or_404(db.casualties, casualty_id, "casualty")
    c = nonterminal_contract(casualty_id)
    if c is None or c["status"] not in ("ACTIVE", "PERFORMANCE_COMPLETE"):
        err("ERR_CONTRACT_NOT_ACTIVE", 422,
            "Logging property requires the casualty's contract ACTIVE or PERFORMANCE_COMPLETE.")
    p = mint({
        "casualty_id": casualty_id,
        "storage_site_id": None,
        "property_type": property_type,
        "quantity_tonnes": quantity,
        "declared_value_cents": declared,
        "verified_value_cents": None,
        "custody_status": "SALVED",
        "documentation_status": "PENDING_SURVEY",
        "redelivered_tonnes": 0,
        "sold_tonnes": 0,
        "disposed_tonnes": 0,
        "in_custody_tonnes": quantity,
        "lien_amount_cents": 0,
        "surveyor_id": None,
    })
    db.properties[p["id"]] = p
    return success(serialize(p), 201)


@app.route("/properties", methods=["GET"])
def list_properties():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.properties.values())
    items = filter_by(items, "casualty_id", request.args.get("casualty_id"))
    items = filter_by(items, "custody_status", request.args.get("custody_status"))
    items = filter_by(items, "storage_site_id", request.args.get("storage_site_id"))
    return list_response(items)


@app.route("/properties/<property_id>", methods=["GET"])
def get_property(property_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.properties, property_id, "property")))


@app.route("/properties/<property_id>/secure-ashore", methods=["POST"])
def secure_ashore_property(property_id):
    body = body_dict()
    site_id = f_str(body, "storage_site_id")
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    p = get_or_404(db.properties, property_id, "property")
    site = get_or_404(db.storage_sites, site_id, "storage site")
    if p["custody_status"] in TERMINAL_CUSTODY_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Property lot is in terminal custody.")
    if p["custody_status"] != "SALVED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a SALVED lot can be secured ashore.")
    if site["allocated_tonnes"] + p["quantity_tonnes"] > site["capacity_tonnes"]:
        err("ERR_STORAGE_CAPACITY_EXCEEDED", 409,
            "Storage site aggregate capacity would be exceeded.")
    p["custody_status"] = "SECURED_ASHORE"
    p["storage_site_id"] = site_id
    touch(p)
    recompute_site_allocated(site)
    return success(serialize(p))


@app.route("/properties/<property_id>/survey", methods=["POST"])
def survey_property(property_id):
    body = body_dict()
    verified = f_int(body, "verified_value_cents", minimum=0)
    uid, role = authenticate()
    authorize(role, ["MarineSurveyor"])
    p = get_or_404(db.properties, property_id, "property")
    if p["documentation_status"] == "VALUE_VERIFIED":
        err("ERR_ALREADY_TERMINAL", 409, "Documentation is VALUE_VERIFIED (terminal).")
    if p["documentation_status"] != "PENDING_SURVEY":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a PENDING_SURVEY lot can be surveyed.")
    p["documentation_status"] = "SURVEYED"
    p["verified_value_cents"] = verified
    p["surveyor_id"] = uid
    touch(p)
    return success(serialize(p))


@app.route("/properties/<property_id>/verify-value", methods=["POST"])
def verify_value_property(property_id):
    uid, role = authenticate()
    authorize(role, ["OperationsDirector"])
    p = get_or_404(db.properties, property_id, "property")
    if p["surveyor_id"] is not None and uid == p["surveyor_id"]:
        err("ERR_SOD_VIOLATION", 403, "Verifier must differ from the lot's surveyor.")
    if p["documentation_status"] == "VALUE_VERIFIED":
        err("ERR_ALREADY_TERMINAL", 409, "Documentation is VALUE_VERIFIED (terminal).")
    if p["documentation_status"] != "SURVEYED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a SURVEYED lot can be value-verified.")
    p["documentation_status"] = "VALUE_VERIFIED"
    touch(p)
    return success(serialize(p))


@app.route("/properties/<property_id>/lien", methods=["POST"])
def lien_property(property_id):
    body = body_dict()
    lien_amount = f_int(body, "lien_amount_cents", minimum=1)
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    p = get_or_404(db.properties, property_id, "property")
    if p["custody_status"] in TERMINAL_CUSTODY_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Property lot is in terminal custody.")
    if p["custody_status"] != "SECURED_ASHORE":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a SECURED_ASHORE lot can be liened.")
    cas = db.casualties.get(p["casualty_id"])
    if cas is None or cas["lifecycle_status"] not in ("IN_OPERATION", "OPERATIONS_COMPLETE"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Liens require the casualty to be IN_OPERATION or OPERATIONS_COMPLETE.")
    p["custody_status"] = "LIENED"
    p["lien_amount_cents"] = lien_amount
    touch(p)
    return success(serialize(p))


@app.route("/properties/<property_id>/dispose", methods=["POST"])
def dispose_property(property_id):
    body = body_dict()
    method = f_enum(body, "method", DISPOSE_METHODS)
    tonnes = f_num(body, "tonnes", minimum=0, strict_min=True)
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    p = get_or_404(db.properties, property_id, "property")
    cas = db.casualties.get(p["casualty_id"])
    contract = latest_contract(p["casualty_id"])
    # Priority 5: custody from-state and terminal precedence
    if p["custody_status"] in TERMINAL_CUSTODY_STATUSES:
        err("ERR_ALREADY_TERMINAL", 409, "Property lot is in terminal custody.")
    if p["custody_status"] == "SALVED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "The lot must be secured ashore before disposition.")
    custody = p["custody_status"]  # SECURED_ASHORE or LIENED

    def eligible():
        return (cas is not None and cas["lifecycle_status"] == "OPERATIONS_COMPLETE") or (
            contract is not None and contract["status"] == "TERMINATED")

    # Branch gates (scaffold precondition order per from-state transition)
    if method == "REDELIVER":
        if custody == "LIENED":
            err("ERR_LIEN_ACTIVE", 422, "Redelivery is blocked while the lot is liened.")
        if not eligible():
            err("ERR_INVALID_STATE_TRANSITION", 409,
                "The lot is not disposition-eligible (casualty OPERATIONS_COMPLETE or contract TERMINATED required).")
        if p["documentation_status"] != "VALUE_VERIFIED":
            err("ERR_INVALID_STATE_TRANSITION", 409,
                "Redelivery requires VALUE_VERIFIED documentation.")
    elif method == "SELL":
        if custody == "SECURED_ASHORE":
            if not eligible():
                err("ERR_INVALID_STATE_TRANSITION", 409,
                    "The lot is not disposition-eligible (casualty OPERATIONS_COMPLETE or contract TERMINATED required).")
            if p["documentation_status"] != "VALUE_VERIFIED":
                err("ERR_INVALID_STATE_TRANSITION", 409,
                    "Sale requires VALUE_VERIFIED documentation.")
            award = None
            if contract is not None:
                award = next((a for a in db.awards.values() if a["contract_id"] == contract["id"]), None)
            if award is None or award["status"] != "PAID":
                err("ERR_LIEN_ACTIVE", 422,
                    "An ordinary sale requires the contract award to be PAID.")
        else:  # LIENED: lien sale
            if contract is None or contract["status"] != "TERMINATED":
                err("ERR_LIEN_ACTIVE", 422,
                    "A lien sale requires the contract to be TERMINATED.")
            if p["documentation_status"] != "VALUE_VERIFIED":
                err("ERR_INVALID_STATE_TRANSITION", 409,
                    "Sale requires VALUE_VERIFIED documentation.")
    else:  # SCRAP
        if custody == "LIENED":
            err("ERR_INVALID_STATE_TRANSITION", 409, "A liened lot cannot be scrapped.")
        if not eligible():
            err("ERR_INVALID_STATE_TRANSITION", 409,
                "The lot is not disposition-eligible (casualty OPERATIONS_COMPLETE or contract TERMINATED required).")
        if p["documentation_status"] not in ("SURVEYED", "VALUE_VERIFIED"):
            err("ERR_INVALID_STATE_TRANSITION", 409,
                "Scrapping requires SURVEYED or VALUE_VERIFIED documentation.")
    # Tonnage (priority 9)
    if tonnes > p["in_custody_tonnes"]:
        err("ERR_QUANTITY_EXCEEDS_REMAINING", 422,
            "Dispose tonnes exceed the remaining in-custody tonnage.")
    was_liened = p["custody_status"] == "LIENED"
    if method == "REDELIVER":
        p["redelivered_tonnes"] += tonnes
    elif method == "SELL":
        p["sold_tonnes"] += tonnes
    else:
        p["disposed_tonnes"] += tonnes
    p["in_custody_tonnes"] -= tonnes
    if abs(p["in_custody_tonnes"]) < 1e-9:
        p["in_custody_tonnes"] = 0
    terminal = p["in_custody_tonnes"] == 0
    if terminal:
        p["custody_status"] = {"REDELIVER": "REDELIVERED", "SELL": "SOLD", "SCRAP": "DISPOSED"}[method]
        if was_liened:
            p["lien_amount_cents"] = 0
    touch(p)
    if terminal and p.get("storage_site_id"):
        site = db.storage_sites.get(p["storage_site_id"])
        if site is not None:
            recompute_site_allocated(site)
    return success(serialize(p))


# ---------------------------------------------------------------------------
# Storage sites
# ---------------------------------------------------------------------------


@app.route("/storage-sites", methods=["POST"])
def create_storage_site():
    body = body_dict()
    name = f_str(body, "name")
    capacity = f_num(body, "capacity_tonnes", minimum=0, strict_min=True)
    _, role = authenticate()
    authorize(role, ["OperationsDirector"])
    s = mint({"name": name, "capacity_tonnes": capacity, "allocated_tonnes": 0})
    db.storage_sites[s["id"]] = s
    return success(serialize(s), 201)


@app.route("/storage-sites", methods=["GET"])
def list_storage_sites():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(list(db.storage_sites.values()))


@app.route("/storage-sites/<site_id>", methods=["GET"])
def get_storage_site(site_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.storage_sites, site_id, "storage site")))


# ---------------------------------------------------------------------------
# Salvage awards
# ---------------------------------------------------------------------------


def compute_final_award(contract):
    if contract["form"] == "FIXED_PRICE":
        return contract["fixed_price_cents"]
    casualty = db.casualties[contract["casualty_id"]]
    V = sum(
        p["verified_value_cents"] or 0
        for p in db.properties.values()
        if p["casualty_id"] == contract["casualty_id"]
        and p["documentation_status"] == "VALUE_VERIFIED"
    )
    base = (Fraction(10, 100) * min(V, T1_CAP)
            + Fraction(8, 100) * max(0, min(V, T2_CAP) - T1_CAP)
            + Fraction(6, 100) * max(0, V - T2_CAP))
    risk = RISK_ADD[casualty["casualty_type"]]
    max_tier = 0
    for ev in db.pollution_events.values():
        if ev["casualty_id"] == contract["casualty_id"]:
            max_tier = max(max_tier, TIER_ORDER[ev["tier"]])
    env = ENV_ADD["TIER_%d" % max_tier] if max_tier else Fraction(0)
    enhanced = rhu(base * (1 + risk + env))
    return min(enhanced, V)


@app.route("/contracts/<contract_id>/award", methods=["POST"])
def create_award(contract_id):
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    c = get_or_404(db.contracts, contract_id, "contract")
    if c["status"] != "PERFORMANCE_COMPLETE":
        err("ERR_CONTRACT_NOT_ACTIVE", 422,
            "Award computation requires PERFORMANCE_COMPLETE.")
    for p in db.properties.values():
        if p["casualty_id"] == c["casualty_id"] and p["documentation_status"] != "VALUE_VERIFIED":
            err("ERR_PROPERTIES_NOT_VERIFIED", 422,
                "Every recovered lot must be VALUE_VERIFIED before award computation.")
    if any(a["contract_id"] == c["id"] for a in db.awards.values()):
        err("ERR_AWARD_ALREADY_EXISTS", 409, "The contract already has its salvage award.")
    computed = compute_final_award(c)
    a = mint({
        "contract_id": c["id"],
        "status": "COMPUTED",
        "computed_amount_cents": computed,
        "agreed_amount_cents": None,
        "awarded_amount_cents": None,
        "paid_amount_cents": None,
        "appeal_count": 0,
    })
    db.awards[a["id"]] = a
    # Re-net special compensation on events whose final exposure exists
    for ev in db.pollution_events.values():
        if ev["casualty_id"] == c["casualty_id"] and ev["final_exposure_cents"] is not None:
            recompute_special_compensation(ev)
    return success(serialize(a), 201)


@app.route("/awards", methods=["GET"])
def list_awards():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.awards.values())
    items = filter_by(items, "contract_id", request.args.get("contract_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/awards/<award_id>", methods=["GET"])
def get_award(award_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.awards, award_id, "award")))


@app.route("/awards/<award_id>/agree", methods=["POST"])
def agree_award(award_id):
    body = body_dict()
    agreed = f_int(body, "agreed_amount_cents", minimum=0)
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    a = get_or_404(db.awards, award_id, "award")
    if a["status"] == "PAID":
        err("ERR_ALREADY_TERMINAL", 409, "Award is PAID (terminal).")
    if a["status"] != "COMPUTED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a COMPUTED award can be agreed.")
    a["status"] = "AGREED"
    a["agreed_amount_cents"] = agreed
    touch(a)
    return success(serialize(a))


@app.route("/awards/<award_id>/submit-arbitration", methods=["POST"])
def submit_arbitration_award(award_id):
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    a = get_or_404(db.awards, award_id, "award")
    if a["status"] == "PAID":
        err("ERR_ALREADY_TERMINAL", 409, "Award is PAID (terminal).")
    if a["status"] != "COMPUTED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only a COMPUTED award can be referred to arbitration.")
    c = db.contracts.get(a["contract_id"])
    for p in db.properties.values():
        if c is not None and p["casualty_id"] == c["casualty_id"] \
                and p["custody_status"] not in TERMINAL_CUSTODY_STATUSES:
            err("ERR_PROPERTIES_NOT_DISPOSED", 422,
                "Every lot of the casualty must be in terminal custody before arbitration.")
    a["status"] = "IN_ARBITRATION"
    touch(a)
    return success(serialize(a))


@app.route("/awards/<award_id>/decide", methods=["POST"])
def decide_award(award_id):
    body = body_dict()
    awarded = f_int(body, "awarded_amount_cents", minimum=0)
    _, role = authenticate()
    authorize(role, ["Arbitrator"])
    a = get_or_404(db.awards, award_id, "award")
    if a["status"] == "PAID":
        err("ERR_ALREADY_TERMINAL", 409, "Award is PAID (terminal).")
    if a["status"] not in ("IN_ARBITRATION", "APPEALED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only an IN_ARBITRATION or APPEALED award can be decided.")
    a["status"] = "AWARDED"
    a["awarded_amount_cents"] = awarded
    touch(a)
    return success(serialize(a))


@app.route("/awards/<award_id>/appeal", methods=["POST"])
def appeal_award(award_id):
    body = body_dict()
    f_str(body, "grounds")
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    a = get_or_404(db.awards, award_id, "award")
    if a["status"] == "PAID":
        err("ERR_ALREADY_TERMINAL", 409, "Award is PAID (terminal).")
    if a["status"] != "AWARDED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an AWARDED award can be appealed.")
    a["status"] = "APPEALED"
    a["appeal_count"] += 1
    touch(a)
    return success(serialize(a))


@app.route("/awards/<award_id>/mark-paid", methods=["POST"])
def mark_paid_award(award_id):
    _, role = authenticate()
    authorize(role, ["ContractsOfficer"])
    a = get_or_404(db.awards, award_id, "award")
    if a["status"] == "PAID":
        err("ERR_ALREADY_TERMINAL", 409, "Award is PAID (terminal).")
    if a["status"] not in ("AGREED", "AWARDED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Only an AGREED or AWARDED award can be marked paid.")
    if a["status"] == "AGREED":
        a["paid_amount_cents"] = a["agreed_amount_cents"]
    else:
        a["paid_amount_cents"] = a["awarded_amount_cents"]
    a["status"] = "PAID"
    touch(a)
    c = db.contracts.get(a["contract_id"])
    if c is not None:
        if c["status"] == "PERFORMANCE_COMPLETE":
            c["status"] = "AWARD_FINAL"
            touch(c)
        # Lien lift cascade
        touched_sites = set()
        for p in db.properties.values():
            if p["casualty_id"] == c["casualty_id"] and p["custody_status"] == "LIENED":
                p["custody_status"] = "SECURED_ASHORE"
                p["lien_amount_cents"] = 0
                touch(p)
                if p.get("storage_site_id"):
                    touched_sites.add(p["storage_site_id"])
        for sid in touched_sites:
            site = db.storage_sites.get(sid)
            if site is not None:
                recompute_site_allocated(site)
    return success(serialize(a))


# ---------------------------------------------------------------------------
# Doc packs and entries
# ---------------------------------------------------------------------------


def evaluate_pack(pack):
    contract = db.contracts.get(pack["contract_id"])
    required = []
    if contract is not None:
        casualty_id = contract["casualty_id"]
        for ph in db.phases.values():
            if ph["contract_id"] == contract["id"] and ph.get("activated_at") is not None \
                    and ph["status"] in ("ACTIVE", "WEATHER_HOLD", "ENV_SUSPENDED", "COMPLETE", "ABORTED"):
                required.append(("DAILY_LOG", ph["id"]))
        for ch in db.charters.values():
            if ch["casualty_id"] == casualty_id and ch["status"] == "OFF_HIRE":
                required.append(("COST_LOG", ch["id"]))
        for ev in db.pollution_events.values():
            if ev["casualty_id"] == casualty_id:
                required.append(("POLLUTION_REPORT", ev["id"]))
        for p in db.properties.values():
            if p["casualty_id"] == casualty_id \
                    and p["documentation_status"] in ("SURVEYED", "VALUE_VERIFIED"):
                required.append(("SURVEY_REPORT", p["id"]))
    entries = [e for e in db.doc_entries.values() if e["doc_pack_id"] == pack["id"]]
    covered = {(e["entry_type"], e["ref_id"]) for e in entries}
    satisfied = sum(1 for item in required if item in covered)
    required_count = len(required)
    if required_count == 0:
        pct = 0
    else:
        raw = 100.0 * satisfied / required_count
        pct = int(raw) if raw == int(raw) else round(raw, 2)
    changed = (pack["required_count"] != required_count
               or pack["satisfied_count"] != satisfied
               or pack["completeness_pct"] != pct)
    pack["required_count"] = required_count
    pack["satisfied_count"] = satisfied
    pack["completeness_pct"] = pct
    return changed


@app.route("/doc-packs", methods=["POST"])
def create_doc_pack():
    body = body_dict()
    contract_id = f_str(body, "contract_id")
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    c = get_or_404(db.contracts, contract_id, "contract")
    if c["status"] not in ("ACTIVE", "PERFORMANCE_COMPLETE", "AWARD_FINAL"):
        err("ERR_CONTRACT_NOT_ACTIVE", 422,
            "A doc pack requires the contract ACTIVE, PERFORMANCE_COMPLETE, or AWARD_FINAL.")
    for pack in db.doc_packs.values():
        if pack["contract_id"] == contract_id and pack["status"] != "ACCEPTED":
            err("ERR_DUPLICATE_OPEN_DOC_PACK", 409,
                "The contract already has a non-ACCEPTED doc pack.")
    pack = mint({
        "contract_id": contract_id,
        "status": "COMPILING",
        "required_count": 0,
        "satisfied_count": 0,
        "completeness_pct": 0,
        "review_notes": None,
    })
    db.doc_packs[pack["id"]] = pack
    evaluate_pack(pack)
    return success(serialize(pack), 201)


@app.route("/doc-packs", methods=["GET"])
def list_doc_packs():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(db.doc_packs.values())
    items = filter_by(items, "contract_id", request.args.get("contract_id"))
    items = filter_by(items, "status", request.args.get("status"))
    return list_response(items)


@app.route("/doc-packs/<pack_id>", methods=["GET"])
def get_doc_pack(pack_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(serialize(get_or_404(db.doc_packs, pack_id, "doc pack")))


ENTRY_REF_TABLES = {
    "DAILY_LOG": "phases",
    "COST_LOG": "charters",
    "POLLUTION_REPORT": "pollution_events",
    "SURVEY_REPORT": "properties",
}


def entry_ref_qualifies(entry_type, ref, casualty_id):
    if entry_type == "DAILY_LOG":
        return (ref["contract_id"] in {c["id"] for c in contracts_of_casualty(casualty_id)}
                and db.contracts.get(ref["contract_id"]) is not None
                and db.contracts[ref["contract_id"]]["casualty_id"] == casualty_id
                and ref.get("activated_at") is not None
                and ref["status"] in ("ACTIVE", "WEATHER_HOLD", "ENV_SUSPENDED", "COMPLETE", "ABORTED"))
    if entry_type == "COST_LOG":
        return ref["casualty_id"] == casualty_id and ref["status"] == "OFF_HIRE"
    if entry_type == "POLLUTION_REPORT":
        return ref["casualty_id"] == casualty_id
    if entry_type == "SURVEY_REPORT":
        return ref["casualty_id"] == casualty_id \
            and ref["documentation_status"] in ("SURVEYED", "VALUE_VERIFIED")
    return False


@app.route("/doc-packs/<pack_id>/entries", methods=["POST"])
def create_doc_entry(pack_id):
    body = body_dict()
    entry_type = f_enum(body, "entry_type", ENTRY_TYPES)
    ref_id = f_str(body, "ref_id")
    entry_date = f_dt(body, "entry_date")
    summary = f_str(body, "summary")
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    pack = get_or_404(db.doc_packs, pack_id, "doc pack")
    table = getattr(db, ENTRY_REF_TABLES[entry_type])
    ref = table.get(ref_id)
    if ref is None:
        # Exists but of the wrong entity type -> ERR_DOC_ENTRY_INVALID;
        # exists nowhere -> ERR_NOT_FOUND (priority 3 body reference).
        known = any(ref_id in getattr(db, t) for t in
                    ("phases", "charters", "pollution_events", "properties"))
        if known:
            err("ERR_DOC_ENTRY_INVALID", 422,
                "The referenced record is of the wrong entity type for this entry_type.")
        err("ERR_NOT_FOUND", 404, "Referenced record does not exist.")
    if pack["status"] == "ACCEPTED":
        err("ERR_ALREADY_TERMINAL", 409, "Doc pack is ACCEPTED (terminal).")
    if pack["status"] != "COMPILING":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Entries may only be appended while the pack is COMPILING.")
    contract = db.contracts.get(pack["contract_id"])
    casualty_id = contract["casualty_id"] if contract else None
    if casualty_id is None or not entry_ref_qualifies(entry_type, ref, casualty_id):
        err("ERR_DOC_ENTRY_INVALID", 422,
            "The referenced record is of the wrong type, casualty, or qualifying state.")
    db.seq += 1
    entry = {
        "id": str(uuid.uuid4()),
        "created_at": db.clock,
        "_seq": db.seq,
        "doc_pack_id": pack_id,
        "entry_type": entry_type,
        "ref_id": ref_id,
        "entry_date": entry_date,
        "summary": summary,
    }
    db.doc_entries[entry["id"]] = entry
    if evaluate_pack(pack):
        touch(pack)
    return success(serialize(entry), 201)


@app.route("/doc-packs/<pack_id>/entries", methods=["GET"])
def list_doc_entries(pack_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(db.doc_packs, pack_id, "doc pack")
    items = [e for e in db.doc_entries.values() if e["doc_pack_id"] == pack_id]
    return list_response(items)


@app.route("/doc-packs/<pack_id>/submit", methods=["POST"])
def submit_doc_pack(pack_id):
    _, role = authenticate()
    authorize(role, ["SalvageMaster"])
    pack = get_or_404(db.doc_packs, pack_id, "doc pack")
    if pack["status"] == "ACCEPTED":
        err("ERR_ALREADY_TERMINAL", 409, "Doc pack is ACCEPTED (terminal).")
    if pack["status"] != "COMPILING":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a COMPILING pack can be submitted.")
    evaluate_pack(pack)  # freeze counters at submit evaluation
    if pack["completeness_pct"] != 100:
        err("ERR_DOC_INCOMPLETE", 422, "Doc pack completeness must be exactly 100.")
    pack["status"] = "SUBMITTED"
    touch(pack)
    return success(serialize(pack))


@app.route("/doc-packs/<pack_id>/review", methods=["POST"])
def review_doc_pack(pack_id):
    body = body_dict()
    outcome = f_enum(body, "outcome", REVIEW_OUTCOMES)
    notes = f_str(body, "notes", required=False, default=None)
    _, role = authenticate()
    authorize(role, ["InsurerSurveyor"])
    pack = get_or_404(db.doc_packs, pack_id, "doc pack")
    if pack["status"] == "ACCEPTED":
        err("ERR_ALREADY_TERMINAL", 409, "Doc pack is ACCEPTED (terminal).")
    if pack["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only a SUBMITTED pack can be reviewed.")
    pack["status"] = "ACCEPTED" if outcome == "ACCEPT" else "COMPILING"
    pack["review_notes"] = notes
    touch(pack)
    return success(serialize(pack))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
