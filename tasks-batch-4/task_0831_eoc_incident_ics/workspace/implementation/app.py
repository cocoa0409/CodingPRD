"""
Emergency Operations Center & Incident Management (ICS) API.
Python + Flask, in-memory store. Boots empty on every process start.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; never seeded)
# ---------------------------------------------------------------------------
incidents = {}
jurisdictions = {}
resource_pools = {}
resource_requests = {}
iaps = {}
tasks = {}
shelters = {}
mutual_aid_requests = {}
damage_assessments = {}
cost_records = {}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


# ---------------------------------------------------------------------------
# Roles / enums
# ---------------------------------------------------------------------------
EOCManager = "EOCManager"
LogisticsChief = "LogisticsChief"
OperationsChief = "OperationsChief"
PlanningChief = "PlanningChief"
FinanceChief = "FinanceChief"
JurisdictionLiaison = "JurisdictionLiaison"
ALL_ROLES = {EOCManager, LogisticsChief, OperationsChief, PlanningChief,
             FinanceChief, JurisdictionLiaison}

HAZARD = {"FLOOD", "WILDFIRE", "HURRICANE", "EARTHQUAKE", "HAZMAT", "PUBLIC_HEALTH"}
DECL_CAT = {"EMERGENCY", "MAJOR_DISASTER"}
RES_TYPE = {"PERSONNEL", "VEHICLE", "EQUIPMENT", "SUPPLY"}
PRIORITY = {"LOW", "MEDIUM", "HIGH"}
INFRA = {"CAT_A_DEBRIS", "CAT_B_PROTECTIVE", "CAT_C_ROADS", "CAT_E_BUILDINGS", "CAT_G_PARKS"}
COST_CAT = {"LABOR", "EQUIPMENT", "MATERIALS", "CONTRACT"}
LEVELS = {"LEVEL_1", "LEVEL_2", "LEVEL_3"}

# Calculation constants
DECLARATION_THRESHOLD = Decimal("5000000")
ENHANCED_DAMAGE_THRESHOLD = Decimal("10000000")
BASE_SHARE_PCT = Decimal("0.75")
ENHANCED_SHARE_PCT = Decimal("0.90")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_VALIDATION": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_RESOURCE_POOL_NOT_FOUND": 404,
    "ERR_RESOURCE_REQUEST_NOT_FOUND": 404,
    "ERR_IAP_NOT_FOUND": 404,
    "ERR_TASK_NOT_FOUND": 404,
    "ERR_SHELTER_NOT_FOUND": 404,
    "ERR_MUTUAL_AID_NOT_FOUND": 404,
    "ERR_DAMAGE_ASSESSMENT_NOT_FOUND": 404,
    "ERR_COST_RECORD_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CROSS_INCIDENT_REFERENCE": 409,
    "ERR_OPERATIONAL_PERIOD_OVERLAP": 409,
    "ERR_DEPLOYMENT_WINDOW_CONFLICT": 409,
    "ERR_RESOURCE_WINDOW_MISMATCH": 409,
    "ERR_INCIDENT_NOT_ACTIVE": 409,
    "ERR_IAP_NOT_PUBLISHED": 409,
    "ERR_REQUEST_NOT_FILLED": 409,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_INSUFFICIENT_RESOURCES": 409,
    "ERR_SHELTER_CAPACITY_EXCEEDED": 409,
    "ERR_SHELTER_OCCUPIED": 409,
    "ERR_INVALID_ACTIVATION_LEVEL": 422,
    "ERR_MISSING_TRANSITION_TARGET": 422,
    "ERR_INCIDENT_NOT_READY_TO_CLOSE": 409,
    "ERR_COST_CEILING_EXCEEDED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers: time, ids, money
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def D(x):
    return Decimal(str(x))


def q2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(t)
    except Exception:
        raise ApiError("ERR_VALIDATION", "invalid datetime")


# ---------------------------------------------------------------------------
# Common-field lifecycle
# ---------------------------------------------------------------------------
def new_common(entity):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Body / query parsing
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(force=True, silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "body must be an object")
    return data


def req_str(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", f"{key} is required")
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"{key} must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"{key} must be a string")
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", f"{key} is invalid")
    return v


def opt_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", f"{key} is invalid")
    return v


def req_int(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", f"{key} is required")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    return v


def opt_int(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    return v


def req_number(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", f"{key} is required")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{key} must be a number")
    return D(v)


def opt_number(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{key} must be a number")
    return D(v)


def opt_bool(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"{key} must be a boolean")
    return v


def get_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit out of range")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Auth / envelope
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid X-User-Role")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this operation")
    return role, uid


def meta(pagination=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = float(v) if isinstance(v, Decimal) else v
    return out


def ok(data, code=200, response_type="object", pagination=None):
    return jsonify({"meta": meta(pagination), "response_type": response_type,
                    "data": data}), code


def obj(entity, code=200):
    return ok(serialize(entity), code=code, response_type="object")


def listing(items):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": offset + limit < total}
    return ok([serialize(e) for e in page], code=200, response_type="array",
              pagination=pagination)


def get_or_404(store, ident, err):
    ent = store.get(ident)
    if ent is None:
        raise ApiError(err)
    return ent


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"}}
    return jsonify(body), 405


@app.route("/", methods=["GET"])
def health():
    return ok({}, code=200)


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def fed_pct(inc):
    if inc["declaration_status"] != "ELIGIBLE":
        return Decimal("0")
    if inc["declaration_category"] == "MAJOR_DISASTER" and \
            inc["total_verified_damage"] >= ENHANCED_DAMAGE_THRESHOLD:
        return ENHANCED_SHARE_PCT
    return BASE_SHARE_PCT


def incident_cost_records(inc_id):
    return [c for c in cost_records.values() if c["incident_id"] == inc_id]


def recompute_costs(inc):
    pct = fed_pct(inc)
    committed = Decimal("0")
    actual = Decimal("0")
    fse = Decimal("0")
    fsa = Decimal("0")
    for c in incident_cost_records(inc["id"]):
        if c["status"] == "ESTIMATED":
            committed += c["estimated_cost"]
            if c["eligible"]:
                fse += q2(c["estimated_cost"] * pct)
        elif c["status"] == "ACTUAL":
            committed += c["actual_cost"]
            actual += c["actual_cost"]
            if c["eligible"]:
                fsa += q2(c["actual_cost"] * pct)
        # VOID excluded
    inc["total_committed_cost"] = q2(committed)
    inc["total_actual_cost"] = q2(actual)
    inc["federal_share_estimated"] = q2(fse)
    inc["federal_share_actual"] = q2(fsa)


def recompute_damage(inc):
    tvd = Decimal("0")
    for a in damage_assessments.values():
        if a["incident_id"] == inc["id"] and a["status"] == "VALIDATED":
            tvd += a["estimated_loss"]
    inc["total_verified_damage"] = q2(tvd)
    inc["declaration_status"] = "ELIGIBLE" if tvd >= DECLARATION_THRESHOLD else "INELIGIBLE"


def recompute_pool(pool):
    reserved = 0
    committed = 0
    for r in resource_requests.values():
        if r["source_pool_id"] == pool["id"]:
            if r["status"] == "SOURCED":
                reserved += r["requested_quantity"]
            elif r["status"] == "FILLED":
                committed += r["requested_quantity"]
    pool["units_reserved"] = reserved
    pool["units_committed"] = committed
    pool["units_available"] = pool["total_units"] - reserved - committed


# ===========================================================================
# Incident
# ===========================================================================
@app.route("/eoc/incidents", methods=["POST"])
def create_incident():
    require_auth([EOCManager])
    body = get_body()
    name = req_str(body, "name")
    hazard = req_enum(body, "hazard_type", HAZARD)
    decl_cat = opt_enum(body, "declaration_category", DECL_CAT, default="EMERGENCY")
    cost_ceiling = opt_number(body, "cost_ceiling", default=D(100000000))
    inc = new_common({
        "name": name,
        "hazard_type": hazard,
        "declaration_category": decl_cat,
        "cost_ceiling": cost_ceiling,
        "op_status": "MONITORING",
        "activation_level": "LEVEL_3",
        "total_committed_cost": D(0),
        "total_actual_cost": D(0),
        "federal_share_estimated": D(0),
        "federal_share_actual": D(0),
        "total_verified_damage": D(0),
        "declaration_status": "INELIGIBLE",
        "current_iap_id": None,
        "activated_at": None,
        "closed_at": None,
    })
    incidents[inc["id"]] = inc
    return obj(inc, 201)


@app.route("/eoc/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    require_auth(ALL_ROLES)
    inc = get_or_404(incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    return obj(inc)


def cancel_task(task):
    """Task -> CANCELLED with cascade hop 2 to backing resource request."""
    task["status"] = "CANCELLED"
    touch(task)
    rr_id = task.get("resource_request_id")
    if rr_id:
        rr = resource_requests.get(rr_id)
        if rr and rr["status"] in ("SOURCED", "FILLED"):
            demobilize_request(rr)


def demobilize_request(rr):
    """Resource request -> DEMOBILIZED with cascade hop 3 pool release."""
    pool = resource_pools.get(rr.get("source_pool_id"))
    prev = rr["status"]
    rr["status"] = "DEMOBILIZED"
    rr["demobilized_at"] = now_iso()
    touch(rr)
    if pool is not None:
        recompute_pool(pool)
        touch(pool)


def check_close_readiness(inc):
    for r in resource_requests.values():
        if r["incident_id"] == inc["id"] and \
                r["status"] in ("SUBMITTED", "NEEDS_INFO", "SOURCED", "FILLED"):
            raise ApiError("ERR_INCIDENT_NOT_READY_TO_CLOSE")
    for s in shelters.values():
        if s["incident_id"] == inc["id"] and s["status"] in ("PLANNED", "OPEN"):
            raise ApiError("ERR_INCIDENT_NOT_READY_TO_CLOSE")
    for c in cost_records.values():
        if c["incident_id"] == inc["id"] and c["status"] == "ESTIMATED":
            raise ApiError("ERR_INCIDENT_NOT_READY_TO_CLOSE")


@app.route("/eoc/incidents/<iid>/transition", methods=["POST"])
def transition_incident(iid):
    require_auth([EOCManager])
    inc = get_or_404(incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    body = get_body()
    to_status = body.get("to_status")
    to_level = body.get("to_activation_level")

    if (to_status is None or to_status == "") and (to_level is None or to_level == ""):
        raise ApiError("ERR_MISSING_TRANSITION_TARGET")

    valid = {("MONITORING", "ACTIVATED"),
             ("ACTIVATED", "DEMOBILIZING"),
             ("DEMOBILIZING", "CLOSED")}

    # Step 5: validate state transition (do not mutate yet)
    if to_status is not None and to_status != "":
        if (inc["op_status"], to_status) not in valid:
            raise ApiError("ERR_INVALID_STATE")

    resulting_status = to_status if (to_status is not None and to_status != "") else inc["op_status"]

    # Step 9: readiness gate for close
    if to_status == "CLOSED":
        check_close_readiness(inc)

    # Step 10: activation-level validity
    if to_level is not None and to_level != "":
        if to_level not in LEVELS or resulting_status != "ACTIVATED":
            raise ApiError("ERR_INVALID_ACTIVATION_LEVEL")

    # Apply op_status side effects
    if to_status is not None and to_status != "":
        if to_status == "ACTIVATED":
            inc["op_status"] = "ACTIVATED"
            inc["activated_at"] = now_iso()
        elif to_status == "DEMOBILIZING":
            inc["op_status"] = "DEMOBILIZING"
            # CASCADE hop 1: cancel live tasks under this incident's IAPs
            incident_iap_ids = {p["id"] for p in iaps.values()
                                if p["incident_id"] == inc["id"]}
            for t in list(tasks.values()):
                if t["iap_id"] in incident_iap_ids and t["status"] in ("PLANNED", "ASSIGNED"):
                    cancel_task(t)
        elif to_status == "CLOSED":
            inc["op_status"] = "CLOSED"
            inc["closed_at"] = now_iso()

    # Apply activation level (parallel dimension)
    if to_level is not None and to_level != "":
        inc["activation_level"] = to_level

    touch(inc)
    return obj(inc)


@app.route("/eoc/incidents/<iid>/situation-report", methods=["GET"])
def situation_report(iid):
    require_auth(ALL_ROLES)
    inc = get_or_404(incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    open_shelter_count = 0
    total_shelter_occupancy = 0
    for s in shelters.values():
        if s["incident_id"] == inc["id"] and s["status"] == "OPEN":
            open_shelter_count += 1
            total_shelter_occupancy += s["current_occupancy"]
    open_request_count = 0
    filled_request_count = 0
    for r in resource_requests.values():
        if r["incident_id"] != inc["id"]:
            continue
        if r["status"] in ("SUBMITTED", "NEEDS_INFO", "SOURCED"):
            open_request_count += 1
        elif r["status"] == "FILLED":
            filled_request_count += 1
    data = {
        "incident_id": inc["id"],
        "op_status": inc["op_status"],
        "activation_level": inc["activation_level"],
        "open_shelter_count": open_shelter_count,
        "total_shelter_occupancy": total_shelter_occupancy,
        "open_request_count": open_request_count,
        "filled_request_count": filled_request_count,
        "total_verified_damage": float(inc["total_verified_damage"]),
        "declaration_status": inc["declaration_status"],
        "total_committed_cost": float(inc["total_committed_cost"]),
        "federal_share_estimated": float(inc["federal_share_estimated"]),
        "federal_share_actual": float(inc["federal_share_actual"]),
    }
    return ok(data, code=200, response_type="object")


@app.route("/eoc/incidents/<iid>/resource-requests", methods=["GET"])
def list_incident_requests(iid):
    require_auth(ALL_ROLES)
    get_or_404(incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    return listing([r for r in resource_requests.values() if r["incident_id"] == iid])


@app.route("/eoc/incidents/<iid>/incident-action-plans", methods=["GET"])
def list_incident_iaps(iid):
    require_auth(ALL_ROLES)
    get_or_404(incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    return listing([p for p in iaps.values() if p["incident_id"] == iid])


@app.route("/eoc/incidents/<iid>/shelters", methods=["GET"])
def list_incident_shelters(iid):
    require_auth(ALL_ROLES)
    get_or_404(incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    return listing([s for s in shelters.values() if s["incident_id"] == iid])


@app.route("/eoc/incidents/<iid>/damage-assessments", methods=["GET"])
def list_incident_damage(iid):
    require_auth(ALL_ROLES)
    get_or_404(incidents, iid, "ERR_INCIDENT_NOT_FOUND")
    return listing([a for a in damage_assessments.values() if a["incident_id"] == iid])


# ===========================================================================
# Jurisdiction
# ===========================================================================
@app.route("/eoc/jurisdictions", methods=["POST"])
def create_jurisdiction():
    require_auth([EOCManager])
    body = get_body()
    name = req_str(body, "name")
    contact_email = opt_str(body, "contact_email", default=None)
    j = new_common({"name": name, "contact_email": contact_email})
    jurisdictions[j["id"]] = j
    return obj(j, 201)


@app.route("/eoc/jurisdictions/<jid>", methods=["GET"])
def get_jurisdiction(jid):
    require_auth(ALL_ROLES)
    j = get_or_404(jurisdictions, jid, "ERR_JURISDICTION_NOT_FOUND")
    return obj(j)


@app.route("/eoc/jurisdictions/<jid>/resource-pools", methods=["GET"])
def list_jurisdiction_pools(jid):
    require_auth(ALL_ROLES)
    get_or_404(jurisdictions, jid, "ERR_JURISDICTION_NOT_FOUND")
    return listing([p for p in resource_pools.values() if p["jurisdiction_id"] == jid])


# ===========================================================================
# ResourcePool
# ===========================================================================
@app.route("/eoc/resource-pools", methods=["POST"])
def create_resource_pool():
    require_auth([LogisticsChief])
    body = get_body()
    jurisdiction_id = req_str(body, "jurisdiction_id")
    resource_type = req_enum(body, "resource_type", RES_TYPE)
    total_units = req_int(body, "total_units")
    if total_units < 1:
        raise ApiError("ERR_VALIDATION", "total_units must be >= 1")
    surge_cap = opt_int(body, "surge_cap", default=None)
    turnaround_hours = opt_int(body, "turnaround_hours", default=0)
    if surge_cap is not None and surge_cap > total_units:
        raise ApiError("ERR_VALIDATION", "surge_cap must be <= total_units")
    if turnaround_hours < 0:
        raise ApiError("ERR_VALIDATION", "turnaround_hours must be >= 0")
    get_or_404(jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    pool = new_common({
        "jurisdiction_id": jurisdiction_id,
        "resource_type": resource_type,
        "total_units": total_units,
        "units_reserved": 0,
        "units_committed": 0,
        "units_available": total_units,
        "surge_cap": surge_cap,
        "turnaround_hours": turnaround_hours,
    })
    resource_pools[pool["id"]] = pool
    return obj(pool, 201)


@app.route("/eoc/resource-pools/<pid>", methods=["GET"])
def get_resource_pool(pid):
    require_auth(ALL_ROLES)
    p = get_or_404(resource_pools, pid, "ERR_RESOURCE_POOL_NOT_FOUND")
    return obj(p)


@app.route("/eoc/resource-pools/<pid>/resource-requests", methods=["GET"])
def list_pool_requests(pid):
    require_auth(ALL_ROLES)
    get_or_404(resource_pools, pid, "ERR_RESOURCE_POOL_NOT_FOUND")
    return listing([r for r in resource_requests.values() if r["source_pool_id"] == pid])


# ===========================================================================
# ResourceRequest (ICS-213RR)
# ===========================================================================
@app.route("/eoc/resource-requests", methods=["POST"])
def create_resource_request():
    require_auth([OperationsChief])
    body = get_body()
    incident_id = req_str(body, "incident_id")
    resource_type = req_enum(body, "resource_type", RES_TYPE)
    requested_quantity = req_int(body, "requested_quantity")
    priority = opt_enum(body, "priority", PRIORITY, default="MEDIUM")
    get_or_404(incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    rr = new_common({
        "incident_id": incident_id,
        "resource_type": resource_type,
        "requested_quantity": requested_quantity,
        "priority": priority,
        "status": "DRAFT",
        "source_pool_id": None,
        "committed_units": 0,
        "deploy_start": None,
        "deploy_end": None,
        "submitted_at": None,
        "sourced_at": None,
        "demobilized_at": None,
    })
    resource_requests[rr["id"]] = rr
    return obj(rr, 201)


# to_status -> required actor role for the shared request-transition endpoint
RR_ACTOR = {
    "SUBMITTED": OperationsChief,
    "NEEDS_INFO": LogisticsChief,
    "SOURCED": LogisticsChief,
    "FILLED": LogisticsChief,
    "DENIED": LogisticsChief,
    "DEMOBILIZED": LogisticsChief,
}


@app.route("/eoc/resource-requests/<rid>/transition", methods=["POST"])
def transition_resource_request(rid):
    role, uid = require_auth([OperationsChief, LogisticsChief])
    body = get_body()
    to_status = req_str(body, "to_status")
    # per-transition actor (authz, before existence)
    actor = RR_ACTOR.get(to_status)
    if actor is not None and role != actor:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this transition")

    rr = get_or_404(resource_requests, rid, "ERR_RESOURCE_REQUEST_NOT_FOUND")
    cur = rr["status"]

    # SOURCED needs a pool that must exist (existence, step 3)
    if to_status == "SOURCED":
        pool_id = body.get("pool_id")
        if not pool_id:
            # no pool referenced -> treat as insufficient resources gate later;
            # but pool_id is required for sourcing.
            pool = None
        else:
            pool = resource_pools.get(pool_id)
            if pool is None:
                raise ApiError("ERR_RESOURCE_POOL_NOT_FOUND")

    # Step 5: valid from-state
    transitions = {
        "SUBMITTED": {"DRAFT", "NEEDS_INFO"},
        "NEEDS_INFO": {"SUBMITTED"},
        "SOURCED": {"SUBMITTED"},
        "FILLED": {"SOURCED"},
        "DENIED": {"SUBMITTED", "NEEDS_INFO"},
        "DEMOBILIZED": {"SOURCED", "FILLED"},
    }
    if to_status not in transitions or cur not in transitions[to_status]:
        raise ApiError("ERR_INVALID_STATE")

    inc = incidents.get(rr["incident_id"])

    if to_status == "SUBMITTED":
        if inc["op_status"] != "ACTIVATED":
            raise ApiError("ERR_INCIDENT_NOT_ACTIVE")
        if rr["requested_quantity"] < 1:
            raise ApiError("ERR_INVALID_QUANTITY")
        rr["submitted_at"] = now_iso()

    elif to_status == "NEEDS_INFO":
        pass

    elif to_status == "SOURCED":
        if pool is None:
            raise ApiError("ERR_RESOURCE_POOL_NOT_FOUND")
        if pool["resource_type"] != rr["resource_type"]:
            raise ApiError("ERR_INSUFFICIENT_RESOURCES")
        if pool["units_available"] < rr["requested_quantity"]:
            raise ApiError("ERR_INSUFFICIENT_RESOURCES")
        rr["source_pool_id"] = pool["id"]
        rr["committed_units"] = rr["requested_quantity"]
        rr["sourced_at"] = now_iso()
        rr["status"] = "SOURCED"
        recompute_pool(pool)
        touch(pool)
        touch(rr)
        return obj(rr)

    elif to_status == "FILLED":
        deploy_start = body.get("deploy_start")
        deploy_end = body.get("deploy_end")
        if not deploy_start or not deploy_end:
            raise ApiError("ERR_VALIDATION", "deploy_start and deploy_end required")
        ds = parse_dt(deploy_start)
        de = parse_dt(deploy_end)
        if not (ds < de):
            raise ApiError("ERR_VALIDATION", "deploy_start must be before deploy_end")
        pool = resource_pools.get(rr["source_pool_id"])
        # aggregate deployment-window capacity check
        effective_cap = pool["surge_cap"] if pool["surge_cap"] is not None else pool["total_units"]
        buf = timedelta(hours=pool["turnaround_hours"])
        used = 0
        for other in resource_requests.values():
            if other["id"] == rr["id"]:
                continue
            if other["source_pool_id"] != pool["id"] or other["status"] != "FILLED":
                continue
            os = parse_dt(other["deploy_start"]) - buf
            oe = parse_dt(other["deploy_end"]) + buf
            # closed-interval overlap between [os, oe] and [ds, de]
            if os <= de and ds <= oe:
                used += other["requested_quantity"]
        if used + rr["requested_quantity"] > effective_cap:
            raise ApiError("ERR_DEPLOYMENT_WINDOW_CONFLICT")
        rr["deploy_start"] = deploy_start
        rr["deploy_end"] = deploy_end
        rr["status"] = "FILLED"
        recompute_pool(pool)
        touch(pool)
        touch(rr)
        return obj(rr)

    elif to_status == "DENIED":
        rr["status"] = "DENIED"
        touch(rr)
        return obj(rr)

    elif to_status == "DEMOBILIZED":
        demobilize_request(rr)
        return obj(rr)

    rr["status"] = to_status
    touch(rr)
    return obj(rr)


# ===========================================================================
# IncidentActionPlan
# ===========================================================================
@app.route("/eoc/incident-action-plans", methods=["POST"])
def create_iap():
    require_auth([PlanningChief])
    body = get_body()
    incident_id = req_str(body, "incident_id")
    op_start = req_str(body, "operational_period_start")
    op_end = req_str(body, "operational_period_end")
    expected_version = req_int(body, "expected_incident_version")
    parse_dt(op_start)
    parse_dt(op_end)
    inc = get_or_404(incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    if expected_version != inc["version"]:
        raise ApiError("ERR_STALE_VERSION")
    plan = new_common({
        "incident_id": incident_id,
        "operational_period_start": op_start,
        "operational_period_end": op_end,
        "status": "DRAFT",
        "published_at": None,
    })
    iaps[plan["id"]] = plan
    touch(inc)  # incident version advances on IAP create (OCC)
    return obj(plan, 201)


@app.route("/eoc/incident-action-plans/<pid>/transition", methods=["POST"])
def transition_iap(pid):
    require_auth([PlanningChief])
    body = get_body()
    to_status = req_str(body, "to_status")
    plan = get_or_404(iaps, pid, "ERR_IAP_NOT_FOUND")
    cur = plan["status"]

    if to_status == "PUBLISHED":
        if cur != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        s = parse_dt(plan["operational_period_start"])
        e = parse_dt(plan["operational_period_end"])
        for other in iaps.values():
            if other["id"] == plan["id"]:
                continue
            if other["incident_id"] != plan["incident_id"] or other["status"] != "PUBLISHED":
                continue
            os_ = parse_dt(other["operational_period_start"])
            oe_ = parse_dt(other["operational_period_end"])
            # half-open overlap: adjacency (start == other's end) allowed
            if s < oe_ and os_ < e:
                raise ApiError("ERR_OPERATIONAL_PERIOD_OVERLAP")
        plan["status"] = "PUBLISHED"
        plan["published_at"] = now_iso()
        touch(plan)
        inc = incidents.get(plan["incident_id"])
        inc["current_iap_id"] = plan["id"]
        touch(inc)
        return obj(plan)

    elif to_status == "CLOSED":
        if cur != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE")
        for t in tasks.values():
            if t["iap_id"] == plan["id"] and t["status"] in ("PLANNED", "ASSIGNED"):
                raise ApiError("ERR_INVALID_STATE")
        plan["status"] = "CLOSED"
        touch(plan)
        return obj(plan)

    raise ApiError("ERR_INVALID_STATE")


# ===========================================================================
# Task (ICS-204)
# ===========================================================================
@app.route("/eoc/tasks", methods=["POST"])
def create_task():
    require_auth([PlanningChief])
    body = get_body()
    iap_id = req_str(body, "iap_id")
    title = req_str(body, "title")
    parent_task_id = opt_str(body, "parent_task_id", default=None)
    resource_request_id = opt_str(body, "resource_request_id", default=None)
    get_or_404(iaps, iap_id, "ERR_IAP_NOT_FOUND")
    if parent_task_id is not None:
        get_or_404(tasks, parent_task_id, "ERR_TASK_NOT_FOUND")
    if resource_request_id is not None:
        get_or_404(resource_requests, resource_request_id, "ERR_RESOURCE_REQUEST_NOT_FOUND")
    t = new_common({
        "iap_id": iap_id,
        "title": title,
        "parent_task_id": parent_task_id,
        "resource_request_id": resource_request_id,
        "status": "PLANNED",
        "assigned_at": None,
        "completed_at": None,
    })
    tasks[t["id"]] = t
    return obj(t, 201)


@app.route("/eoc/tasks/<tid>", methods=["GET"])
def get_task(tid):
    require_auth(ALL_ROLES)
    t = get_or_404(tasks, tid, "ERR_TASK_NOT_FOUND")
    return obj(t)


@app.route("/eoc/tasks", methods=["GET"])
def list_tasks():
    require_auth(ALL_ROLES)
    iap_id = request.args.get("iap_id")
    parent_task_id = request.args.get("parent_task_id")
    resource_request_id = request.args.get("resource_request_id")
    items = []
    for t in tasks.values():
        if iap_id is not None and t["iap_id"] != iap_id:
            continue
        if parent_task_id is not None and t["parent_task_id"] != parent_task_id:
            continue
        if resource_request_id is not None and t["resource_request_id"] != resource_request_id:
            continue
        items.append(t)
    return listing(items)


@app.route("/eoc/tasks/<tid>/transition", methods=["POST"])
def transition_task(tid):
    require_auth([OperationsChief])
    body = get_body()
    to_status = req_str(body, "to_status")
    t = get_or_404(tasks, tid, "ERR_TASK_NOT_FOUND")
    cur = t["status"]

    if to_status == "ASSIGNED":
        if cur != "PLANNED":
            raise ApiError("ERR_INVALID_STATE")
        plan = iaps.get(t["iap_id"])
        rr_id = t.get("resource_request_id")
        rr = resource_requests.get(rr_id) if rr_id else None
        # Step 7: cross-aggregate reference integrity
        if rr is not None and rr["incident_id"] != plan["incident_id"]:
            raise ApiError("ERR_CROSS_INCIDENT_REFERENCE")
        # Step 8: resource-window mismatch (only meaningful once request filled)
        if rr is not None and rr["deploy_end"] is not None:
            if parse_dt(rr["deploy_end"]) < parse_dt(plan["operational_period_start"]):
                raise ApiError("ERR_RESOURCE_WINDOW_MISMATCH")
        # Step 10: cross-entity state gates
        if plan["status"] != "PUBLISHED":
            raise ApiError("ERR_IAP_NOT_PUBLISHED")
        if rr is not None and rr["status"] != "FILLED":
            raise ApiError("ERR_REQUEST_NOT_FILLED")
        t["status"] = "ASSIGNED"
        t["assigned_at"] = now_iso()
        touch(t)
        return obj(t)

    elif to_status == "COMPLETED":
        if cur != "ASSIGNED":
            raise ApiError("ERR_INVALID_STATE")
        t["status"] = "COMPLETED"
        t["completed_at"] = now_iso()
        touch(t)
        return obj(t)

    elif to_status == "CANCELLED":
        if cur not in ("PLANNED", "ASSIGNED"):
            raise ApiError("ERR_INVALID_STATE")
        cancel_task(t)
        return obj(t)

    raise ApiError("ERR_INVALID_STATE")


# ===========================================================================
# Shelter
# ===========================================================================
@app.route("/eoc/shelters", methods=["POST"])
def create_shelter():
    require_auth([OperationsChief])
    body = get_body()
    incident_id = req_str(body, "incident_id")
    name = req_str(body, "name")
    capacity = req_int(body, "capacity")
    if capacity < 1:
        raise ApiError("ERR_VALIDATION", "capacity must be >= 1")
    get_or_404(incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    s = new_common({
        "incident_id": incident_id,
        "name": name,
        "capacity": capacity,
        "current_occupancy": 0,
        "reserved_occupancy": 0,
        "status": "PLANNED",
        "opened_at": None,
        "closed_at": None,
    })
    shelters[s["id"]] = s
    return obj(s, 201)


@app.route("/eoc/shelters/<sid>/transition", methods=["POST"])
def transition_shelter(sid):
    require_auth([OperationsChief])
    body = get_body()
    to_status = req_str(body, "to_status")
    s = get_or_404(shelters, sid, "ERR_SHELTER_NOT_FOUND")
    cur = s["status"]

    if to_status == "OPEN":
        if cur != "PLANNED":
            raise ApiError("ERR_INVALID_STATE")
        inc = incidents.get(s["incident_id"])
        if inc["op_status"] != "ACTIVATED":
            raise ApiError("ERR_INCIDENT_NOT_ACTIVE")
        if s["capacity"] < 1:
            raise ApiError("ERR_VALIDATION")
        s["status"] = "OPEN"
        s["opened_at"] = now_iso()
        touch(s)
        return obj(s)

    elif to_status == "CLOSED":
        if cur != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        if s["current_occupancy"] != 0 or s["reserved_occupancy"] != 0:
            raise ApiError("ERR_SHELTER_OCCUPIED")
        s["status"] = "CLOSED"
        s["closed_at"] = now_iso()
        touch(s)
        return obj(s)

    raise ApiError("ERR_INVALID_STATE")


@app.route("/eoc/shelters/<sid>/occupancy", methods=["POST"])
def shelter_occupancy(sid):
    require_auth([OperationsChief])
    body = get_body()
    s = get_or_404(shelters, sid, "ERR_SHELTER_NOT_FOUND")
    if s["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    check_in = opt_int(body, "check_in", default=0)
    check_out = opt_int(body, "check_out", default=0)
    reserve = opt_int(body, "reserve", default=0)
    release_reserve = opt_int(body, "release_reserve", default=0)
    new_current = s["current_occupancy"] + check_in - check_out
    new_reserved = s["reserved_occupancy"] + reserve - release_reserve
    if new_current < 0 or new_reserved < 0:
        raise ApiError("ERR_VALIDATION", "occupancy cannot go below zero")
    if new_current + new_reserved > s["capacity"]:
        raise ApiError("ERR_SHELTER_CAPACITY_EXCEEDED")
    s["current_occupancy"] = new_current
    s["reserved_occupancy"] = new_reserved
    touch(s)
    return obj(s)


# ===========================================================================
# MutualAidRequest (EMAC)
# ===========================================================================
@app.route("/eoc/mutual-aid-requests", methods=["POST"])
def create_mutual_aid():
    require_auth([LogisticsChief])
    body = get_body()
    incident_id = req_str(body, "incident_id")
    to_jurisdiction_id = req_str(body, "to_jurisdiction_id")
    resource_type = req_enum(body, "resource_type", RES_TYPE)
    requested_units = req_int(body, "requested_units")
    get_or_404(incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    get_or_404(jurisdictions, to_jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    m = new_common({
        "incident_id": incident_id,
        "to_jurisdiction_id": to_jurisdiction_id,
        "resource_type": resource_type,
        "requested_units": requested_units,
        "offered_units": 0,
        "countered_units": 0,
        "accepted_units": 0,
        "status": "REQUESTED",
        "resolved_at": None,
    })
    mutual_aid_requests[m["id"]] = m
    return obj(m, 201)


@app.route("/eoc/mutual-aid-requests/<mid>", methods=["GET"])
def get_mutual_aid(mid):
    require_auth(ALL_ROLES)
    m = get_or_404(mutual_aid_requests, mid, "ERR_MUTUAL_AID_NOT_FOUND")
    return obj(m)


@app.route("/eoc/mutual-aid-requests", methods=["GET"])
def list_mutual_aid():
    require_auth(ALL_ROLES)
    incident_id = request.args.get("incident_id")
    to_jurisdiction_id = request.args.get("to_jurisdiction_id")
    items = []
    for m in mutual_aid_requests.values():
        if incident_id is not None and m["incident_id"] != incident_id:
            continue
        if to_jurisdiction_id is not None and m["to_jurisdiction_id"] != to_jurisdiction_id:
            continue
        items.append(m)
    return listing(items)


MAR_ACTOR = {
    "OFFERED": JurisdictionLiaison,
    "COUNTERED": LogisticsChief,
    "ACCEPTED": LogisticsChief,
    "DECLINED": LogisticsChief,
    "WITHDRAWN": LogisticsChief,
}


@app.route("/eoc/mutual-aid-requests/<mid>/transition", methods=["POST"])
def transition_mutual_aid(mid):
    role, uid = require_auth([LogisticsChief, JurisdictionLiaison])
    body = get_body()
    to_status = req_str(body, "to_status")
    actor = MAR_ACTOR.get(to_status)
    if actor is not None and role != actor:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this transition")

    m = get_or_404(mutual_aid_requests, mid, "ERR_MUTUAL_AID_NOT_FOUND")

    # Step 4: ownership for liaison-driven offers
    if role == JurisdictionLiaison and uid != m["to_jurisdiction_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    cur = m["status"]
    valid = {
        "OFFERED": {"REQUESTED", "COUNTERED"},
        "COUNTERED": {"OFFERED"},
        "ACCEPTED": {"OFFERED"},
        "DECLINED": {"OFFERED"},
        "WITHDRAWN": {"REQUESTED"},
    }
    if to_status not in valid or cur not in valid[to_status]:
        raise ApiError("ERR_INVALID_STATE")

    if to_status == "OFFERED":
        offered_units = req_int(body, "offered_units")
        if offered_units < 1:
            raise ApiError("ERR_INVALID_QUANTITY")
        m["offered_units"] = offered_units
        m["status"] = "OFFERED"
        touch(m)
        return obj(m)

    elif to_status == "COUNTERED":
        countered_units = req_int(body, "countered_units")
        if countered_units < 1:
            raise ApiError("ERR_INVALID_QUANTITY")
        m["countered_units"] = countered_units
        m["status"] = "COUNTERED"
        touch(m)
        return obj(m)

    elif to_status == "ACCEPTED":
        inc = incidents.get(m["incident_id"])
        if inc["op_status"] != "ACTIVATED":
            raise ApiError("ERR_INCIDENT_NOT_ACTIVE")
        m["accepted_units"] = m["offered_units"]
        m["status"] = "ACCEPTED"
        m["resolved_at"] = now_iso()
        touch(m)
        return obj(m)

    elif to_status == "DECLINED":
        m["status"] = "DECLINED"
        m["resolved_at"] = now_iso()
        touch(m)
        return obj(m)

    elif to_status == "WITHDRAWN":
        m["status"] = "WITHDRAWN"
        m["resolved_at"] = now_iso()
        touch(m)
        return obj(m)

    raise ApiError("ERR_INVALID_STATE")


# ===========================================================================
# DamageAssessment
# ===========================================================================
@app.route("/eoc/damage-assessments", methods=["POST"])
def create_damage_assessment():
    require_auth([PlanningChief])
    body = get_body()
    incident_id = req_str(body, "incident_id")
    site_name = req_str(body, "site_name")
    estimated_loss = req_number(body, "estimated_loss")
    infrastructure_category = req_enum(body, "infrastructure_category", INFRA)
    if estimated_loss < 0:
        raise ApiError("ERR_VALIDATION", "estimated_loss must be >= 0")
    get_or_404(incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    a = new_common({
        "incident_id": incident_id,
        "site_name": site_name,
        "estimated_loss": estimated_loss,
        "infrastructure_category": infrastructure_category,
        "status": "DRAFT",
        "validated_at": None,
    })
    damage_assessments[a["id"]] = a
    return obj(a, 201)


@app.route("/eoc/damage-assessments/<aid>/transition", methods=["POST"])
def transition_damage_assessment(aid):
    require_auth([PlanningChief])
    body = get_body()
    to_status = req_str(body, "to_status")
    a = get_or_404(damage_assessments, aid, "ERR_DAMAGE_ASSESSMENT_NOT_FOUND")

    if to_status == "VALIDATED":
        if a["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        a["status"] = "VALIDATED"
        a["validated_at"] = now_iso()
        touch(a)
        inc = incidents.get(a["incident_id"])
        recompute_damage(inc)
        recompute_costs(inc)  # pct may have changed with declaration_status
        touch(inc)
        return obj(a)

    elif to_status == "REJECTED":
        if a["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        a["status"] = "REJECTED"
        touch(a)
        return obj(a)

    raise ApiError("ERR_INVALID_STATE")


# ===========================================================================
# CostRecord (FEMA-PA)
# ===========================================================================
@app.route("/eoc/cost-records", methods=["POST"])
def create_cost_record():
    require_auth([FinanceChief])
    body = get_body()
    incident_id = req_str(body, "incident_id")
    category = req_enum(body, "category", COST_CAT)
    estimated_cost = req_number(body, "estimated_cost")
    resource_request_id = opt_str(body, "resource_request_id", default=None)
    eligible = opt_bool(body, "eligible", default=True)
    expected_version = req_int(body, "expected_incident_version")
    if estimated_cost < 0:
        raise ApiError("ERR_VALIDATION", "estimated_cost must be >= 0")
    inc = get_or_404(incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    if resource_request_id is not None:
        get_or_404(resource_requests, resource_request_id, "ERR_RESOURCE_REQUEST_NOT_FOUND")
    # Step 6: OCC
    if expected_version != inc["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # Step 11: fiscal ceiling
    if inc["total_committed_cost"] + estimated_cost > inc["cost_ceiling"]:
        raise ApiError("ERR_COST_CEILING_EXCEEDED")
    c = new_common({
        "incident_id": incident_id,
        "resource_request_id": resource_request_id,
        "category": category,
        "estimated_cost": estimated_cost,
        "actual_cost": None,
        "eligible": eligible,
        "status": "ESTIMATED",
        "finalized_at": None,
    })
    cost_records[c["id"]] = c
    recompute_costs(inc)
    touch(inc)  # incident version advances on cost-record create (OCC + ledger)
    return obj(c, 201)


@app.route("/eoc/cost-records/<cid>", methods=["GET"])
def get_cost_record(cid):
    require_auth(ALL_ROLES)
    c = get_or_404(cost_records, cid, "ERR_COST_RECORD_NOT_FOUND")
    return obj(c)


@app.route("/eoc/cost-records", methods=["GET"])
def list_cost_records():
    require_auth(ALL_ROLES)
    incident_id = request.args.get("incident_id")
    resource_request_id = request.args.get("resource_request_id")
    items = []
    for c in cost_records.values():
        if incident_id is not None and c["incident_id"] != incident_id:
            continue
        if resource_request_id is not None and c["resource_request_id"] != resource_request_id:
            continue
        items.append(c)
    return listing(items)


@app.route("/eoc/cost-records/<cid>/transition", methods=["POST"])
def transition_cost_record(cid):
    require_auth([FinanceChief])
    body = get_body()
    to_status = req_str(body, "to_status")
    c = get_or_404(cost_records, cid, "ERR_COST_RECORD_NOT_FOUND")
    cur = c["status"]

    if to_status == "ACTUAL":
        if cur != "ESTIMATED":
            raise ApiError("ERR_INVALID_STATE")
        actual_cost = req_number(body, "actual_cost")
        if actual_cost < 0:
            raise ApiError("ERR_VALIDATION", "actual_cost must be >= 0")
        c["actual_cost"] = actual_cost
        c["status"] = "ACTUAL"
        c["finalized_at"] = now_iso()
        touch(c)
        inc = incidents.get(c["incident_id"])
        recompute_costs(inc)
        touch(inc)
        return obj(c)

    elif to_status == "VOID":
        if cur not in ("ESTIMATED", "ACTUAL"):
            raise ApiError("ERR_INVALID_STATE")
        c["status"] = "VOID"
        touch(c)
        inc = incidents.get(c["incident_id"])
        recompute_costs(inc)
        touch(inc)
        return obj(c)

    raise ApiError("ERR_INVALID_STATE")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
