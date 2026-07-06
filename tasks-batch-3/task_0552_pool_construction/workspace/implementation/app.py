"""
Pool Construction & Remodel API — Python + Flask reference implementation.

All state is held in-memory (module-level dicts). Nothing is seeded at startup:
every entity is created by clients through the declared endpoints. A fresh process
(start.sh) begins with completely empty storage.
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
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# In-memory storage (wiped on every process boot — no persistence anywhere)
# ---------------------------------------------------------------------------
STORE = {
    "pool_projects": {},
    "design_plans": {},
    "phase_gates": {},
    "inspections": {},
    "subcontractors": {},
    "crew_assignments": {},
    "change_orders": {},
    "draw_requests": {},
    "punch_items": {},
}

_SEQ = {"n": 0}
# Server logical clock (§2.9). Default reads exactly 2026-05-01T00:00:00Z and never
# falls back to real wall-clock time. Used only for crew interval/overlap/cure reasoning.
LOGICAL_CLOCK = {"value": "2026-05-01T00:00:00Z"}

KNOWN_ROLES = {"BuilderPM", "Designer", "Owner", "Inspector", "Subcontractor"}

SEQUENCE_INDEX = {"EXCAVATION": 1, "STEEL": 2, "PLUMBING": 3, "GUNITE": 4, "PLASTER": 5}
PHASES = set(SEQUENCE_INDEX.keys())
TRADES = {"EXCAVATOR", "STEEL", "PLUMBER", "GUNITE", "PLASTER", "GENERAL"}
CO_CATEGORIES = {"PUMP", "HEATER", "LIGHTING", "WATER_FEATURE", "CLEANER", "SCOPE"}
SEVERITIES = {"MINOR", "MAJOR", "SAFETY"}
POOL_TYPES = {"GUNITE", "REMODEL"}

COMPLETION_FACTORS = {
    "PENDING": Decimal("0.0"),
    "IN_PROGRESS": Decimal("0.5"),
    "INSPECTION_PENDING": Decimal("0.8"),
    "PASSED": Decimal("1.0"),
    "FAILED": Decimal("0.0"),
}
RETAINAGE_PCT = Decimal("0.10")
CURE_BUFFER = timedelta(hours=24)

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_POSTURE_STOP_WORK": 409,
    "ERR_POSTURE_HOLD": 409,
    "ERR_DESIGN_ALREADY_EXISTS": 409,
    "ERR_DESIGN_NOT_APPROVED": 409,
    "ERR_PERMIT_NOT_ISSUED": 409,
    "ERR_PHASE_ALREADY_EXISTS": 409,
    "ERR_PHASE_SEQUENCE": 409,
    "ERR_PHASE_NOT_IN_PROGRESS": 409,
    "ERR_PHASE_NOT_ACTIVE": 409,
    "ERR_PHASE_NOT_PASSED": 409,
    "ERR_SUBCONTRACTOR_DOUBLE_BOOKED": 409,
    "ERR_SITE_OCCUPIED": 409,
    "ERR_CURE_BUFFER": 409,
    "ERR_SUBCONTRACTOR_INACTIVE": 409,
    "ERR_CHANGE_ORDER_NOT_APPROVED": 409,
    "ERR_DRAW_EXCEEDS_CONTRACT": 409,
    "ERR_OPEN_PUNCH_ITEMS": 409,
    "ERR_NOT_STARTUP_READY": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def rhu(value):
    """Round a Decimal/number half-up to an integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round a Decimal/number half-up to 2 decimal places, returned as Decimal."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", t)
        if not m:
            raise
        base, frac, tz = m.groups()
        if frac:
            frac = (frac + "000000")[:7]  # '.' + up to 6 digits
        else:
            frac = ""
        dt = datetime.fromisoformat(base + frac + tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def common_fields():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def touch(entity):
    """Record a stored-field mutation on a non-project entity."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def touch_project_meta(project):
    """Project construction_status / derived change: bump updated_at only (no version bump)."""
    project["updated_at"] = now_iso()


def bump_project_version(project):
    """Explicit ledger-affecting write: bump project version (§2.5)."""
    project["updated_at"] = now_iso()
    project["version"] += 1


# ---------------------------------------------------------------------------
# Body-field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", "%s is required" % name)
    return body[name]


def req_int(body, name, positive=False):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", "%s must be greater than zero" % name)
    return v


def req_num(body, name, positive=False):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", "%s must be a number" % name)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", "%s must be greater than zero" % name)
    return v


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "%s must be a string" % name)
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", "%s has an illegal value" % name)
    return v


def opt_enum(body, name, allowed):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", "%s has an illegal value" % name)
    return v


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "%s must be a string" % name)
    return v


# ---------------------------------------------------------------------------
# Auth / lookup
# ---------------------------------------------------------------------------
def require_auth():
    role = request.headers.get("X-User-Role")
    if role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role missing or unrecognized")
    uid = request.headers.get("X-User-ID")
    return uid, role


def must_get(coll, eid):
    if not isinstance(eid, str):
        raise ApiError("ERR_NOT_FOUND", "resource not found")
    e = STORE[coll].get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "resource not found")
    return e


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "role not authorized for this operation")


def check_owner(role, uid, project):
    if role == "Owner" and uid != project.get("owner_user_id"):
        raise ApiError("ERR_FORBIDDEN", "owner ownership check failed")


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------
def project_gates(pid):
    return [g for g in STORE["phase_gates"].values() if g["pool_project_id"] == pid]


def project_punches(pid):
    return [p for p in STORE["punch_items"].values() if p["pool_project_id"] == pid]


def project_applied_cos(pid):
    return [c for c in STORE["change_orders"].values()
            if c["pool_project_id"] == pid and c["status"] == "APPLIED"]


def project_funded_draws(pid):
    return [d for d in STORE["draw_requests"].values()
            if d["pool_project_id"] == pid and d["status"] == "FUNDED"]


def project_design(pid):
    for d in STORE["design_plans"].values():
        if d["pool_project_id"] == pid:
            return d
    return None


def gate_inspection_attempts(gate_id):
    return sum(1 for i in STORE["inspections"].values()
               if i["phase_gate_id"] == gate_id and i["status"] in ("PASSED", "FAILED"))


def compute_ledger(project):
    pid = project["id"]
    contract_amount = project["contract_price_cents"] + sum(
        c["applied_delta_cents"] for c in project_applied_cos(pid))
    funded = project_funded_draws(pid)
    retainage_held = sum(d["retainage_cents"] for d in funded if not d["retainage_released"])
    disbursed = sum(d["net_disbursed_cents"] for d in funded) + sum(
        d["retainage_cents"] for d in funded if d["retainage_released"])
    remaining = contract_amount - disbursed - retainage_held
    return {
        "contract_amount_cents": contract_amount,
        "amount_disbursed_cents": disbursed,
        "retainage_held_cents": retainage_held,
        "amount_remaining_cents": remaining,
    }


def compute_posture(pid, exempt_gate_id=None):
    gates = project_gates(pid)
    if any(g["status"] == "FAILED" and g["id"] != exempt_gate_id for g in gates):
        return "STOP_WORK"
    punches = project_punches(pid)
    if any(p["status"] == "OPEN" and p["severity"] == "SAFETY" for p in punches):
        return "STOP_WORK"
    project = STORE["pool_projects"][pid]
    if compute_ledger(project)["amount_remaining_cents"] < 0:
        return "STOP_WORK"
    if any(p["status"] == "OPEN" and p["severity"] == "MAJOR" for p in punches):
        return "HOLD"
    return "OPEN"


def compute_current_phase(pid):
    gates = sorted(project_gates(pid), key=lambda g: SEQUENCE_INDEX[g["phase"]])
    if not gates:
        return "NONE"
    if all(g["status"] == "PASSED" for g in gates):
        return "STARTUP"
    for g in gates:
        if g["status"] != "PASSED":
            return g["phase"]
    return "STARTUP"


def compute_design_status(pid):
    d = project_design(pid)
    if d is None:
        return "NO_DESIGN"
    if d["status"] == "DRAFT":
        return "NO_DESIGN" if d["revision_count"] == 0 else "IN_DESIGN"
    if d["status"] == "RENDERED_3D":
        return "IN_DESIGN"
    # OWNER_APPROVED
    return "PERMITTED" if d["permit_status"] == "ISSUED" else "DESIGN_APPROVED"


def compute_committed_hours(sub_id):
    total = Decimal("0")
    for c in STORE["crew_assignments"].values():
        if c["subcontractor_id"] == sub_id and c["status"] in ("SCHEDULED", "COMPLETED"):
            total += Decimal(str(c["duration_hours"]))
    return float(rhu2(total))


def compute_reliability_projected(sub_id):
    rel = [c for c in STORE["crew_assignments"].values()
           if c["subcontractor_id"] == sub_id and c["status"] in ("SCHEDULED", "COMPLETED")]
    total = len(rel)
    if total == 0:
        return 100
    good = 0
    for c in rel:
        gate = STORE["phase_gates"].get(c["phase_gate_id"])
        if gate is not None and gate["status"] != "FAILED":
            good += 1
    return rhu(Decimal(100 * good) / Decimal(total))


def compute_reliability_realized(sub_id):
    rel = [c for c in STORE["crew_assignments"].values()
           if c["subcontractor_id"] == sub_id and c["status"] == "COMPLETED"]
    total = len(rel)
    if total == 0:
        return 100
    good = 0
    for c in rel:
        gate = STORE["phase_gates"].get(c["phase_gate_id"])
        if gate is not None and gate["status"] == "PASSED" and gate_inspection_attempts(gate["id"]) == 1:
            good += 1
    return rhu(Decimal(100 * good) / Decimal(total))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _base(entity):
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }


def serialize_project(p):
    out = _base(p)
    out.update({
        "owner_name": p["owner_name"],
        "owner_user_id": p["owner_user_id"],
        "site_address": p["site_address"],
        "pool_type": p["pool_type"],
        "contract_price_cents": p["contract_price_cents"],
        "pool_gallons": p["pool_gallons"],
        "construction_status": p["construction_status"],
        "current_phase": compute_current_phase(p["id"]),
        "design_status": compute_design_status(p["id"]),
        "posture": compute_posture(p["id"]),
    })
    out.update(compute_ledger(p))
    return out


def serialize_design(d):
    out = _base(d)
    out.update({
        "pool_project_id": d["pool_project_id"],
        "length_ft": d["length_ft"],
        "width_ft": d["width_ft"],
        "avg_depth_ft": d["avg_depth_ft"],
        "status": d["status"],
        "permit_status": d["permit_status"],
        "jurisdiction": d["jurisdiction"],
        "permit_number": d["permit_number"],
        "revision_count": d["revision_count"],
    })
    return out


def serialize_gate(g):
    out = _base(g)
    out.update({
        "pool_project_id": g["pool_project_id"],
        "phase": g["phase"],
        "sequence_index": SEQUENCE_INDEX[g["phase"]],
        "budget_cents": g["budget_cents"],
        "status": g["status"],
        "inspection_attempts": gate_inspection_attempts(g["id"]),
    })
    return out


def serialize_inspection(i):
    out = _base(i)
    out.update({
        "pool_project_id": i["pool_project_id"],
        "phase_gate_id": i["phase_gate_id"],
        "inspector_name": i["inspector_name"],
        "scheduled_at": i["scheduled_at"],
        "status": i["status"],
        "result_notes": i["result_notes"],
    })
    return out


def serialize_sub(s):
    out = _base(s)
    out.update({
        "company_name": s["company_name"],
        "trade": s["trade"],
        "status": s["status"],
        "committed_crew_hours": compute_committed_hours(s["id"]),
        "reliability_projected": compute_reliability_projected(s["id"]),
        "reliability_realized": compute_reliability_realized(s["id"]),
    })
    return out


def serialize_crew(c):
    out = _base(c)
    out.update({
        "pool_project_id": c["pool_project_id"],
        "subcontractor_id": c["subcontractor_id"],
        "phase_gate_id": c["phase_gate_id"],
        "start_at": c["start_at"],
        "end_at": c["end_at"],
        "duration_hours": c["duration_hours"],
        "status": c["status"],
    })
    return out


def serialize_change_order(c):
    out = _base(c)
    out.update({
        "pool_project_id": c["pool_project_id"],
        "category": c["category"],
        "description": c["description"],
        "price_delta_cents": c["price_delta_cents"],
        "phase": c["phase"],
        "applied_delta_cents": c["applied_delta_cents"],
        "status": c["status"],
    })
    return out


def serialize_draw(d):
    out = _base(d)
    out.update({
        "pool_project_id": d["pool_project_id"],
        "phase_gate_id": d["phase_gate_id"],
        "requested_cents": d["requested_cents"],
        "provisional_eligible_cents": d["provisional_eligible_cents"],
        "eligible_cents": d["eligible_cents"],
        "retainage_cents": d["retainage_cents"],
        "net_disbursed_cents": d["net_disbursed_cents"],
        "retainage_released": d["retainage_released"],
        "status": d["status"],
    })
    return out


def serialize_punch(p):
    out = _base(p)
    out.update({
        "pool_project_id": p["pool_project_id"],
        "description": p["description"],
        "severity": p["severity"],
        "status": p["status"],
    })
    return out


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}


def respond_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_array(items, limit, offset, total_count):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_collection(coll, serialize, filters):
    limit, offset = get_pagination()
    items = list(STORE[coll].values())
    for field, value in filters.items():
        if value is not None:
            items = [e for e in items if e.get(field) == value]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    window = items[offset: offset + limit]
    return respond_array([serialize(e) for e in window], limit, offset, total)


# ===========================================================================
# PoolProject
# ===========================================================================
@app.route("/pool-build/pool-projects", methods=["POST"])
def create_project():
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    body = get_body()
    owner_name = req_str(body, "owner_name")
    owner_user_id = req_str(body, "owner_user_id")
    site_address = req_str(body, "site_address")
    pool_type = opt_enum(body, "pool_type", POOL_TYPES) or "GUNITE"
    contract_price_cents = req_int(body, "contract_price_cents", positive=True)
    pool_gallons = req_int(body, "pool_gallons")

    p = common_fields()
    p.update({
        "owner_name": owner_name,
        "owner_user_id": owner_user_id,
        "site_address": site_address,
        "pool_type": pool_type,
        "contract_price_cents": contract_price_cents,
        "pool_gallons": pool_gallons,
        "construction_status": "NOT_STARTED",
    })
    STORE["pool_projects"][p["id"]] = p
    return respond_object(serialize_project(p), 201)


@app.route("/pool-build/pool-projects/<pid>", methods=["GET"])
def get_project(pid):
    require_auth()
    p = must_get("pool_projects", pid)
    return respond_object(serialize_project(p))


@app.route("/pool-build/pool-projects/<pid>/transition", methods=["POST"])
def transition_project(pid):
    uid, role = require_auth()
    require_role(role, {"BuilderPM", "Owner"})
    body = get_body()
    action = body.get("action")
    # action-specific authorization (before existence)
    if action == "ORIENT":
        require_role(role, {"BuilderPM"})
    elif action == "CLOSE":
        require_role(role, {"Owner"})
    p = must_get("pool_projects", pid)
    if action in ("ORIENT", "CLOSE"):
        check_owner(role, uid, p)
    if action not in ("ORIENT", "CLOSE"):
        raise ApiError("ERR_VALIDATION", "unknown action")

    if action == "ORIENT":
        if p["construction_status"] != "STARTUP_READY":
            raise ApiError("ERR_NOT_STARTUP_READY", "project is not STARTUP_READY")
        p["construction_status"] = "ORIENTED"
        touch_project_meta(p)
    else:  # CLOSE
        if p["construction_status"] != "ORIENTED":
            raise ApiError("ERR_INVALID_STATE", "project is not ORIENTED")
        open_punches = sum(1 for x in project_punches(pid) if x["status"] == "OPEN")
        if open_punches != 0:
            raise ApiError("ERR_OPEN_PUNCH_ITEMS", "open punch items remain")
        p["construction_status"] = "CLOSED"
        touch_project_meta(p)
    return respond_object(serialize_project(p))


# ===========================================================================
# DesignPlan
# ===========================================================================
@app.route("/pool-build/design-plans", methods=["POST"])
def create_design():
    uid, role = require_auth()
    require_role(role, {"Designer"})
    body = get_body()
    pool_project_id = req_field(body, "pool_project_id")
    must_get("pool_projects", pool_project_id)
    length_ft = req_num(body, "length_ft", positive=True)
    width_ft = req_num(body, "width_ft", positive=True)
    avg_depth_ft = req_num(body, "avg_depth_ft", positive=True)
    # uniqueness guard: one DesignPlan per project
    if project_design(pool_project_id) is not None:
        raise ApiError("ERR_DESIGN_ALREADY_EXISTS", "a design plan already exists for this project")

    d = common_fields()
    d.update({
        "pool_project_id": pool_project_id,
        "length_ft": length_ft,
        "width_ft": width_ft,
        "avg_depth_ft": avg_depth_ft,
        "status": "DRAFT",
        "permit_status": "NONE",
        "jurisdiction": None,
        "permit_number": None,
        "revision_count": 0,
    })
    STORE["design_plans"][d["id"]] = d
    return respond_object(serialize_design(d), 201)


@app.route("/pool-build/design-plans/<did>", methods=["GET"])
def get_design(did):
    require_auth()
    d = must_get("design_plans", did)
    return respond_object(serialize_design(d))


@app.route("/pool-build/design-plans", methods=["GET"])
def list_designs():
    require_auth()
    return list_collection("design_plans", serialize_design,
                           {"pool_project_id": request.args.get("pool_project_id")})


DESIGN_ACTION_ROLE = {
    "RENDER": "Designer",
    "APPROVE": "Owner",
    "REQUEST_REVISION": "Owner",
    "SUBMIT_PERMIT": "Designer",
    "ISSUE_PERMIT": "Inspector",
    "REJECT_PERMIT": "Inspector",
}


@app.route("/pool-build/design-plans/<did>/transition", methods=["POST"])
def transition_design(did):
    uid, role = require_auth()
    require_role(role, {"Designer", "Owner", "Inspector"})
    body = get_body()
    action = body.get("action")
    if action in DESIGN_ACTION_ROLE:
        require_role(role, {DESIGN_ACTION_ROLE[action]})
    d = must_get("design_plans", did)
    project = STORE["pool_projects"].get(d["pool_project_id"])
    if action in ("APPROVE", "REQUEST_REVISION") and project is not None:
        check_owner(role, uid, project)
    if action not in DESIGN_ACTION_ROLE:
        raise ApiError("ERR_VALIDATION", "unknown action")

    if action == "RENDER":
        if d["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "design is not in DRAFT")
        d["status"] = "RENDERED_3D"
        touch(d)

    elif action == "APPROVE":
        if d["status"] != "RENDERED_3D":
            raise ApiError("ERR_INVALID_STATE", "design is not RENDERED_3D")
        d["status"] = "OWNER_APPROVED"
        touch(d)

    elif action == "REQUEST_REVISION":
        if d["status"] == "RENDERED_3D":
            d["status"] = "DRAFT"
            d["revision_count"] += 1
            touch(d)
        elif d["status"] == "OWNER_APPROVED":
            if d["permit_status"] not in ("NONE", "REJECTED"):
                raise ApiError("ERR_INVALID_STATE", "cannot revise a design whose permit is submitted or issued")
            d["status"] = "DRAFT"
            d["revision_count"] += 1
            touch(d)
        else:
            raise ApiError("ERR_INVALID_STATE", "design cannot be revised from its current state")

    elif action == "SUBMIT_PERMIT":
        if d["permit_status"] not in ("NONE", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE", "permit cannot be submitted from its current state")
        if d["status"] != "OWNER_APPROVED":
            raise ApiError("ERR_DESIGN_NOT_APPROVED", "design must be OWNER_APPROVED to submit for permit")
        jurisdiction = opt_str(body, "jurisdiction")
        d["permit_status"] = "SUBMITTED"
        if jurisdiction is not None:
            d["jurisdiction"] = jurisdiction
        touch(d)

    elif action == "ISSUE_PERMIT":
        if d["permit_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "permit is not SUBMITTED")
        permit_number = opt_str(body, "permit_number")
        d["permit_status"] = "ISSUED"
        if permit_number is not None:
            d["permit_number"] = permit_number
        touch(d)

    elif action == "REJECT_PERMIT":
        if d["permit_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "permit is not SUBMITTED")
        d["permit_status"] = "REJECTED"
        touch(d)

    return respond_object(serialize_design(d))


# ===========================================================================
# PhaseGate
# ===========================================================================
@app.route("/pool-build/phase-gates", methods=["POST"])
def create_phase_gate():
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    body = get_body()
    pool_project_id = req_field(body, "pool_project_id")
    project = must_get("pool_projects", pool_project_id)
    phase = req_enum(body, "phase", PHASES)
    budget_cents = req_int(body, "budget_cents")
    # referential: design must be PERMITTED
    if compute_design_status(pool_project_id) != "PERMITTED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", "project permit is not issued")
    # uniqueness: one gate per phase
    if any(g["phase"] == phase for g in project_gates(pool_project_id)):
        raise ApiError("ERR_PHASE_ALREADY_EXISTS", "a phase gate already exists for this phase")

    g = common_fields()
    g.update({
        "pool_project_id": pool_project_id,
        "phase": phase,
        "budget_cents": budget_cents,
        "status": "PENDING",
    })
    STORE["phase_gates"][g["id"]] = g
    return respond_object(serialize_gate(g), 201)


@app.route("/pool-build/phase-gates/<gid>", methods=["GET"])
def get_phase_gate(gid):
    require_auth()
    g = must_get("phase_gates", gid)
    return respond_object(serialize_gate(g))


@app.route("/pool-build/phase-gates", methods=["GET"])
def list_phase_gates():
    require_auth()
    return list_collection("phase_gates", serialize_gate,
                           {"pool_project_id": request.args.get("pool_project_id")})


@app.route("/pool-build/phase-gates/<gid>/start", methods=["POST"])
def start_phase_gate(gid):
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    g = must_get("phase_gates", gid)
    pid = g["pool_project_id"]

    # state legality
    if g["status"] not in ("PENDING", "FAILED"):
        raise ApiError("ERR_INVALID_STATE", "phase gate cannot be started from its current state")

    is_rework = g["status"] == "FAILED"
    # posture (rework exempts this gate's own FAILED status)
    posture = compute_posture(pid, exempt_gate_id=gid if is_rework else None)
    if posture == "STOP_WORK":
        raise ApiError("ERR_POSTURE_STOP_WORK", "project posture is STOP_WORK")
    if posture == "HOLD":
        raise ApiError("ERR_POSTURE_HOLD", "project posture is HOLD")

    # referential: permit issued
    if compute_design_status(pid) != "PERMITTED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", "project permit is not issued")

    # referential: all lower-sequence gates PASSED
    seq = SEQUENCE_INDEX[g["phase"]]
    for other in project_gates(pid):
        if SEQUENCE_INDEX[other["phase"]] < seq and other["status"] != "PASSED":
            raise ApiError("ERR_PHASE_SEQUENCE", "a lower-sequence phase is not yet PASSED")

    g["status"] = "IN_PROGRESS"
    touch(g)
    project = STORE["pool_projects"][pid]
    if project["construction_status"] == "NOT_STARTED":
        project["construction_status"] = "IN_CONSTRUCTION"
        touch_project_meta(project)
    return respond_object(serialize_gate(g))


# ===========================================================================
# Inspection
# ===========================================================================
@app.route("/pool-build/inspections", methods=["POST"])
def create_inspection():
    uid, role = require_auth()
    require_role(role, {"Inspector"})
    body = get_body()
    pool_project_id = req_field(body, "pool_project_id")
    project = must_get("pool_projects", pool_project_id)
    phase_gate_id = req_field(body, "phase_gate_id")
    gate = must_get("phase_gates", phase_gate_id)
    inspector_name = req_str(body, "inspector_name")
    scheduled_at = req_str(body, "scheduled_at")

    # posture: STOP_WORK blocks; HOLD does not
    if compute_posture(pool_project_id) == "STOP_WORK":
        raise ApiError("ERR_POSTURE_STOP_WORK", "project posture is STOP_WORK")

    # gate must be IN_PROGRESS
    if gate["status"] != "IN_PROGRESS":
        raise ApiError("ERR_PHASE_NOT_IN_PROGRESS", "phase gate is not IN_PROGRESS")

    i = common_fields()
    i.update({
        "pool_project_id": pool_project_id,
        "phase_gate_id": phase_gate_id,
        "inspector_name": inspector_name,
        "scheduled_at": scheduled_at,
        "status": "SCHEDULED",
        "result_notes": None,
    })
    STORE["inspections"][i["id"]] = i
    # side effect: gate IN_PROGRESS -> INSPECTION_PENDING
    gate["status"] = "INSPECTION_PENDING"
    touch(gate)
    return respond_object(serialize_inspection(i), 201)


@app.route("/pool-build/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    require_auth()
    i = must_get("inspections", iid)
    return respond_object(serialize_inspection(i))


@app.route("/pool-build/inspections", methods=["GET"])
def list_inspections():
    require_auth()
    return list_collection("inspections", serialize_inspection, {
        "pool_project_id": request.args.get("pool_project_id"),
        "phase_gate_id": request.args.get("phase_gate_id"),
    })


def release_retainage(project):
    for d in project_funded_draws(project["id"]):
        if not d["retainage_released"]:
            d["retainage_released"] = True
            touch(d)


@app.route("/pool-build/inspections/<iid>/record", methods=["POST"])
def record_inspection(iid):
    uid, role = require_auth()
    require_role(role, {"Inspector"})
    i = must_get("inspections", iid)
    body = get_body()
    outcome = req_enum(body, "outcome", {"PASS", "FAIL", "CANCEL"})
    # state legality
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "inspection is not SCHEDULED")
    result_notes = opt_str(body, "result_notes")

    gate = STORE["phase_gates"].get(i["phase_gate_id"])
    project = STORE["pool_projects"].get(i["pool_project_id"])

    if outcome == "PASS":
        i["status"] = "PASSED"
        if result_notes is not None:
            i["result_notes"] = result_notes
        touch(i)
        if gate is not None and gate["status"] == "INSPECTION_PENDING":
            gate["status"] = "PASSED"
            touch(gate)
            # PLASTER pass with all gates PASSED -> STARTUP_READY + retainage release
            if (gate["phase"] == "PLASTER" and project is not None
                    and project["construction_status"] == "IN_CONSTRUCTION"
                    and all(x["status"] == "PASSED" for x in project_gates(project["id"]))):
                project["construction_status"] = "STARTUP_READY"
                release_retainage(project)
                touch_project_meta(project)

    elif outcome == "FAIL":
        i["status"] = "FAILED"
        if result_notes is not None:
            i["result_notes"] = result_notes
        touch(i)
        if gate is not None and gate["status"] == "INSPECTION_PENDING":
            gate["status"] = "FAILED"
            touch(gate)

    else:  # CANCEL
        i["status"] = "CANCELLED"
        if result_notes is not None:
            i["result_notes"] = result_notes
        touch(i)
        if gate is not None and gate["status"] == "INSPECTION_PENDING":
            gate["status"] = "IN_PROGRESS"
            touch(gate)

    return respond_object(serialize_inspection(i))


# ===========================================================================
# Subcontractor
# ===========================================================================
@app.route("/pool-build/subcontractors", methods=["POST"])
def create_subcontractor():
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    body = get_body()
    company_name = req_str(body, "company_name")
    trade = req_enum(body, "trade", TRADES)
    s = common_fields()
    s.update({"company_name": company_name, "trade": trade, "status": "ACTIVE"})
    STORE["subcontractors"][s["id"]] = s
    return respond_object(serialize_sub(s), 201)


@app.route("/pool-build/subcontractors/<sid>", methods=["GET"])
def get_subcontractor(sid):
    require_auth()
    s = must_get("subcontractors", sid)
    return respond_object(serialize_sub(s))


@app.route("/pool-build/subcontractors/<sid>/transition", methods=["POST"])
def transition_subcontractor(sid):
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    s = must_get("subcontractors", sid)
    body = get_body()
    action = body.get("action")
    if action not in ("SUSPEND", "REACTIVATE"):
        raise ApiError("ERR_VALIDATION", "unknown action")
    if action == "SUSPEND":
        if s["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "subcontractor is not ACTIVE")
        s["status"] = "SUSPENDED"
    else:
        if s["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", "subcontractor is not SUSPENDED")
        s["status"] = "ACTIVE"
    touch(s)
    return respond_object(serialize_sub(s))


# ===========================================================================
# CrewAssignment
# ===========================================================================
def _intervals_overlap(s1, e1, s2, e2):
    # half-open [start, end): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


@app.route("/pool-build/crew-assignments", methods=["POST"])
def create_crew_assignment():
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    body = get_body()
    pool_project_id = req_field(body, "pool_project_id")
    must_get("pool_projects", pool_project_id)
    subcontractor_id = req_field(body, "subcontractor_id")
    sub = must_get("subcontractors", subcontractor_id)
    phase_gate_id = req_field(body, "phase_gate_id")
    gate = must_get("phase_gates", phase_gate_id)
    start_raw = req_str(body, "start_at")
    end_raw = req_str(body, "end_at")
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "start_at/end_at must be ISO 8601 datetimes")
    if not (start_dt < end_dt):
        raise ApiError("ERR_INVALID_INTERVAL", "end_at must be strictly after start_at")

    # posture: STOP_WORK and HOLD both block
    posture = compute_posture(pool_project_id)
    if posture == "STOP_WORK":
        raise ApiError("ERR_POSTURE_STOP_WORK", "project posture is STOP_WORK")
    if posture == "HOLD":
        raise ApiError("ERR_POSTURE_HOLD", "project posture is HOLD")

    # temporal guard 1: same subcontractor double-booking
    for c in STORE["crew_assignments"].values():
        if c["status"] == "CANCELLED":
            continue
        if c["subcontractor_id"] == subcontractor_id and _intervals_overlap(
                start_dt, end_dt, c["_start_dt"], c["_end_dt"]):
            raise ApiError("ERR_SUBCONTRACTOR_DOUBLE_BOOKED", "subcontractor is double-booked")

    # temporal guard 2: site capacity (same project, capacity 1)
    for c in STORE["crew_assignments"].values():
        if c["status"] == "CANCELLED":
            continue
        if c["pool_project_id"] == pool_project_id and _intervals_overlap(
                start_dt, end_dt, c["_start_dt"], c["_end_dt"]):
            raise ApiError("ERR_SITE_OCCUPIED", "site is occupied for this interval")

    # temporal guard 3: gunite->plaster cure buffer
    if gate["phase"] == "PLASTER":
        for c in STORE["crew_assignments"].values():
            if c["status"] == "CANCELLED":
                continue
            if c["pool_project_id"] != pool_project_id:
                continue
            other_gate = STORE["phase_gates"].get(c["phase_gate_id"])
            if other_gate is not None and other_gate["phase"] == "GUNITE":
                if start_dt < c["_end_dt"] + CURE_BUFFER:
                    raise ApiError("ERR_CURE_BUFFER", "plaster crew must start >= 24h after gunite end")

    # eligibility guard: subcontractor must be ACTIVE
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBCONTRACTOR_INACTIVE", "subcontractor is not ACTIVE")

    duration = float(rhu2(Decimal((end_dt - start_dt).total_seconds()) / Decimal(3600)))
    c = common_fields()
    c.update({
        "pool_project_id": pool_project_id,
        "subcontractor_id": subcontractor_id,
        "phase_gate_id": phase_gate_id,
        "start_at": start_raw,
        "end_at": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "duration_hours": duration,
        "status": "SCHEDULED",
    })
    STORE["crew_assignments"][c["id"]] = c
    return respond_object(serialize_crew(c), 201)


@app.route("/pool-build/crew-assignments/<cid>", methods=["GET"])
def get_crew_assignment(cid):
    require_auth()
    c = must_get("crew_assignments", cid)
    return respond_object(serialize_crew(c))


@app.route("/pool-build/crew-assignments", methods=["GET"])
def list_crew_assignments():
    require_auth()
    return list_collection("crew_assignments", serialize_crew, {
        "pool_project_id": request.args.get("pool_project_id"),
        "subcontractor_id": request.args.get("subcontractor_id"),
        "phase_gate_id": request.args.get("phase_gate_id"),
    })


@app.route("/pool-build/crew-assignments/<cid>/transition", methods=["POST"])
def transition_crew_assignment(cid):
    uid, role = require_auth()
    require_role(role, {"Subcontractor", "BuilderPM"})
    body = get_body()
    action = body.get("action")
    # action-specific role checks (before existence)
    if action == "COMPLETE":
        require_role(role, {"Subcontractor"})
    c = must_get("crew_assignments", cid)
    # ownership for subcontractor
    if role == "Subcontractor" and uid != c["subcontractor_id"]:
        raise ApiError("ERR_FORBIDDEN", "subcontractor ownership check failed")
    if action not in ("COMPLETE", "CANCEL"):
        raise ApiError("ERR_VALIDATION", "unknown action")

    if action == "COMPLETE":
        if c["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "crew assignment is not SCHEDULED")
        gate = STORE["phase_gates"].get(c["phase_gate_id"])
        if gate is None or gate["status"] not in ("IN_PROGRESS", "INSPECTION_PENDING"):
            raise ApiError("ERR_PHASE_NOT_ACTIVE", "referenced phase gate is not active")
        c["status"] = "COMPLETED"
        touch(c)
    else:  # CANCEL
        if c["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "crew assignment is not SCHEDULED")
        c["status"] = "CANCELLED"
        touch(c)

    return respond_object(serialize_crew(c))


# ===========================================================================
# ChangeOrder
# ===========================================================================
@app.route("/pool-build/change-orders", methods=["POST"])
def create_change_order():
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    body = get_body()
    pool_project_id = req_field(body, "pool_project_id")
    must_get("pool_projects", pool_project_id)
    category = req_enum(body, "category", CO_CATEGORIES)
    description = req_str(body, "description")
    price_delta_cents = req_int(body, "price_delta_cents")
    phase = opt_enum(body, "phase", PHASES)

    c = common_fields()
    c.update({
        "pool_project_id": pool_project_id,
        "category": category,
        "description": description,
        "price_delta_cents": price_delta_cents,
        "phase": phase,
        "applied_delta_cents": 0,
        "status": "PROPOSED",
    })
    STORE["change_orders"][c["id"]] = c
    return respond_object(serialize_change_order(c), 201)


@app.route("/pool-build/change-orders/<cid>", methods=["GET"])
def get_change_order(cid):
    require_auth()
    c = must_get("change_orders", cid)
    return respond_object(serialize_change_order(c))


@app.route("/pool-build/change-orders", methods=["GET"])
def list_change_orders():
    require_auth()
    return list_collection("change_orders", serialize_change_order,
                           {"pool_project_id": request.args.get("pool_project_id")})


CO_ACTION_ROLE = {"APPROVE": "Owner", "REJECT": "Owner", "APPLY": "BuilderPM", "REVERSE": "BuilderPM"}


def _discount_pct(cumulative_pre):
    if cumulative_pre < 500000:
        return Decimal("0.00")
    if cumulative_pre < 1500000:
        return Decimal("0.03")
    return Decimal("0.05")


@app.route("/pool-build/change-orders/<cid>/transition", methods=["POST"])
def transition_change_order(cid):
    uid, role = require_auth()
    require_role(role, {"Owner", "BuilderPM"})
    body = get_body()
    action = body.get("action")
    if action in CO_ACTION_ROLE:
        require_role(role, {CO_ACTION_ROLE[action]})
    c = must_get("change_orders", cid)
    project = STORE["pool_projects"].get(c["pool_project_id"])
    if action in ("APPROVE", "REJECT") and project is not None:
        check_owner(role, uid, project)
    if action not in CO_ACTION_ROLE:
        raise ApiError("ERR_VALIDATION", "unknown action")

    if action == "APPROVE":
        if c["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE", "change order is not PROPOSED")
        c["status"] = "APPROVED"
        touch(c)

    elif action == "REJECT":
        if c["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE", "change order is not PROPOSED")
        c["status"] = "REJECTED"
        touch(c)

    elif action == "APPLY":
        if c["status"] != "APPROVED":
            raise ApiError("ERR_CHANGE_ORDER_NOT_APPROVED", "change order is not APPROVED")
        pid = c["pool_project_id"]
        cumulative_pre = sum(
            x["price_delta_cents"] for x in project_applied_cos(pid)
            if x["id"] != c["id"] and x["price_delta_cents"] > 0)
        pct = _discount_pct(cumulative_pre)
        if c["price_delta_cents"] > 0:
            applied = rhu(Decimal(c["price_delta_cents"]) * (Decimal(1) - pct))
        else:
            applied = c["price_delta_cents"]
        c["applied_delta_cents"] = applied
        c["status"] = "APPLIED"
        touch(c)
        if c["phase"] is not None:
            for g in project_gates(pid):
                if g["phase"] == c["phase"]:
                    g["budget_cents"] += applied
                    touch(g)
                    break
        if project is not None:
            bump_project_version(project)

    elif action == "REVERSE":
        if c["status"] != "APPLIED":
            raise ApiError("ERR_INVALID_STATE", "change order is not APPLIED")
        pid = c["pool_project_id"]
        applied = c["applied_delta_cents"]
        c["status"] = "REVERSED"
        touch(c)
        if c["phase"] is not None:
            for g in project_gates(pid):
                if g["phase"] == c["phase"]:
                    g["budget_cents"] -= applied
                    touch(g)
                    break
        if project is not None:
            bump_project_version(project)

    return respond_object(serialize_change_order(c))


# ===========================================================================
# DrawRequest
# ===========================================================================
def _compute_eligible(gate, requested_cents):
    factor = COMPLETION_FACTORS[gate["status"]]
    phase_earned = rhu(Decimal(gate["budget_cents"]) * factor)
    return max(0, min(phase_earned, requested_cents))


@app.route("/pool-build/draw-requests", methods=["POST"])
def create_draw_request():
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    body = get_body()
    pool_project_id = req_field(body, "pool_project_id")
    project = must_get("pool_projects", pool_project_id)
    phase_gate_id = req_field(body, "phase_gate_id")
    gate = must_get("phase_gates", phase_gate_id)
    requested_cents = req_int(body, "requested_cents", positive=True)
    expected_version = req_int(body, "expected_pool_project_version")

    # OCC
    if expected_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION", "expected_pool_project_version is stale")

    # posture: STOP_WORK blocks; HOLD does not
    if compute_posture(pool_project_id) == "STOP_WORK":
        raise ApiError("ERR_POSTURE_STOP_WORK", "project posture is STOP_WORK")

    provisional = _compute_eligible(gate, requested_cents)
    d = common_fields()
    d.update({
        "pool_project_id": pool_project_id,
        "phase_gate_id": phase_gate_id,
        "requested_cents": requested_cents,
        "provisional_eligible_cents": provisional,
        "eligible_cents": 0,
        "retainage_cents": 0,
        "net_disbursed_cents": 0,
        "retainage_released": False,
        "status": "REQUESTED",
    })
    STORE["draw_requests"][d["id"]] = d
    bump_project_version(project)
    return respond_object(serialize_draw(d), 201)


@app.route("/pool-build/draw-requests/<did>", methods=["GET"])
def get_draw_request(did):
    require_auth()
    d = must_get("draw_requests", did)
    return respond_object(serialize_draw(d))


@app.route("/pool-build/draw-requests", methods=["GET"])
def list_draw_requests():
    require_auth()
    return list_collection("draw_requests", serialize_draw, {
        "pool_project_id": request.args.get("pool_project_id"),
        "phase_gate_id": request.args.get("phase_gate_id"),
    })


DRAW_ACTION_ROLE = {"APPROVE": "Owner", "REJECT": "Owner", "FUND": "BuilderPM"}


@app.route("/pool-build/draw-requests/<did>/transition", methods=["POST"])
def transition_draw_request(did):
    uid, role = require_auth()
    require_role(role, {"Owner", "BuilderPM"})
    body = get_body()
    action = body.get("action")
    if action in DRAW_ACTION_ROLE:
        require_role(role, {DRAW_ACTION_ROLE[action]})
    d = must_get("draw_requests", did)
    project = STORE["pool_projects"].get(d["pool_project_id"])
    if action in ("APPROVE", "REJECT") and project is not None:
        check_owner(role, uid, project)
    if action not in DRAW_ACTION_ROLE:
        raise ApiError("ERR_VALIDATION", "unknown action")

    if action == "APPROVE":
        if d["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "draw is not REQUESTED")
        d["status"] = "APPROVED"
        touch(d)

    elif action == "REJECT":
        if d["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "draw is not REQUESTED")
        d["status"] = "REJECTED"
        touch(d)

    elif action == "FUND":
        if d["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "draw is not APPROVED")
        gate = STORE["phase_gates"].get(d["phase_gate_id"])
        if gate is None or gate["status"] != "PASSED":
            raise ApiError("ERR_PHASE_NOT_PASSED", "referenced phase gate is not PASSED")
        eligible = _compute_eligible(gate, d["requested_cents"])
        retainage = rhu(Decimal(eligible) * RETAINAGE_PCT)
        net = eligible - retainage
        remaining = compute_ledger(project)["amount_remaining_cents"]
        if net > remaining:
            raise ApiError("ERR_DRAW_EXCEEDS_CONTRACT", "net disbursement exceeds contract remaining")
        d["eligible_cents"] = eligible
        d["retainage_cents"] = retainage
        d["net_disbursed_cents"] = net
        d["status"] = "FUNDED"
        touch(d)
        bump_project_version(project)

    return respond_object(serialize_draw(d))


# ===========================================================================
# PunchItem
# ===========================================================================
@app.route("/pool-build/punch-items", methods=["POST"])
def create_punch_item():
    uid, role = require_auth()
    require_role(role, {"Inspector", "Owner"})
    body = get_body()
    pool_project_id = req_field(body, "pool_project_id")
    project = must_get("pool_projects", pool_project_id)
    check_owner(role, uid, project)
    description = req_str(body, "description")
    severity = req_enum(body, "severity", SEVERITIES)

    p = common_fields()
    p.update({
        "pool_project_id": pool_project_id,
        "description": description,
        "severity": severity,
        "status": "OPEN",
    })
    STORE["punch_items"][p["id"]] = p
    # posture is derived from open punch items; nothing further to mutate.
    return respond_object(serialize_punch(p), 201)


@app.route("/pool-build/punch-items/<pid>", methods=["GET"])
def get_punch_item(pid):
    require_auth()
    p = must_get("punch_items", pid)
    return respond_object(serialize_punch(p))


@app.route("/pool-build/punch-items", methods=["GET"])
def list_punch_items():
    require_auth()
    return list_collection("punch_items", serialize_punch,
                           {"pool_project_id": request.args.get("pool_project_id")})


@app.route("/pool-build/punch-items/<pid>/resolve", methods=["POST"])
def resolve_punch_item(pid):
    uid, role = require_auth()
    require_role(role, {"BuilderPM", "Owner"})
    body = get_body()
    action = body.get("action")
    if action == "WAIVE":
        require_role(role, {"Owner"})
    p = must_get("punch_items", pid)
    project = STORE["pool_projects"].get(p["pool_project_id"])
    if role == "Owner" and project is not None:
        check_owner(role, uid, project)
    if action not in ("RESOLVE", "WAIVE"):
        raise ApiError("ERR_VALIDATION", "unknown action")
    if p["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "punch item is not OPEN")

    p["status"] = "RESOLVED" if action == "RESOLVE" else "WAIVED"
    touch(p)
    # posture is derived; recomputes automatically on next read.
    return respond_object(serialize_punch(p))


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = require_auth()
    require_role(role, {"BuilderPM"})
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    try:
        parse_dt(to_iso8601)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime")
    LOGICAL_CLOCK["value"] = to_iso8601
    return respond_object({})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
