"""Urban Forestry & Tree Permit API — Python + Flask reference implementation.

All storage is in-memory (dicts keyed by id). The store starts empty on every
boot; no entity is ever seeded or preloaded. Time-sensitive domain decisions use
a server-controlled logical clock (default 2026-03-01T00:00:00Z).
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ForestryAdmin", "ForestryStaff", "Arborist", "Inspector", "Applicant", "Contractor"}

CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

CONDITION_CLASSES = {"GOOD", "FAIR", "POOR", "DEAD"}
INSPECTION_TYPES = {"ROUTINE", "RISK", "POST_STORM"}
PERMIT_TYPES = {"REMOVAL", "PRUNING"}
DECISIONS = {"APPROVE", "DENY", "REQUEST_INFO"}
MITIGATION_METHODS = {"REPLACEMENT_COST", "APPRAISED_VALUE"}
WORK_TYPES = {"REMOVAL", "PRUNING", "EMERGENCY_REMOVAL"}
SEVERITIES = {"MINOR", "MAJOR", "SEVERE"}
CONTRACTOR_STATUSES = {"ACTIVE", "SUSPENDED"}

REPLACEMENT_SITE_FACTOR = Decimal("1.075")
BASAL_AREA_FACTOR = Decimal("0.5454")
CONDITION_FACTOR = {
    "GOOD": Decimal("1.0"),
    "FAIR": Decimal("0.75"),
    "POOR": Decimal("0.5"),
    "DEAD": Decimal("0.25"),
}
TARGET_BONUS = 3
SCORE_CAP = 16

# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.zones = {}
        self.species = {}
        self.trees = {}
        self.inspections = {}
        self.permits = {}
        self.contractors = {}
        self.work_orders = {}
        self.dig_tickets = {}
        self.storm_events = {}
        self.plantings = {}
        self.clock = parse_dt(CLOCK_DEFAULT)
        self.total_outstanding_mitigation_cents = 0
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return db.clock


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def to_number(dec):
    """Convert a Decimal to a JSON-friendly number (int when integral)."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok_object(data, code=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_array(items, limit, offset, total, has_more, code=200):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = has_more
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {field}")
    return v


def req_number(body, field):
    v = body.get(field)
    if not is_number(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {field}")
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {field}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {field}")
    return v


def req_enum(body, field, allowed):
    if field not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing field: {field}")
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid field: {field}")
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, f"Invalid enum value for {field}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {field}")
    try:
        return parse_dt(v), v
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid datetime: {field}")


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(store, ident, error_id):
    ent = store.get(ident)
    if ent is None:
        raise ApiError(error_id, 404, "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Entity creation / mutation
# ---------------------------------------------------------------------------
def base_fields(versioned=True):
    ts = now_iso()
    d = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": db.next_seq()}
    if versioned:
        d["updated_at"] = ts
        d["version"] = 1
    return d


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            limit = 10
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items):
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    data = [serialize(e) for e in page]
    return ok_array(data, limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Domain calculations
# ---------------------------------------------------------------------------
def compute_required_replacement_count(permit_type, dbh):
    if permit_type == "PRUNING":
        return 0
    if dbh < 8.0:
        return 0
    elif dbh < 18.0:
        return 1
    elif dbh < 30.0:
        return 2
    return 3


def compute_mitigation_fee(permit_type, method, count, species, tree):
    if permit_type == "PRUNING":
        return 0
    if method == "REPLACEMENT_COST":
        base = Decimal(str(species["base_replacement_value_dollars"]))
        per_tree_cents = round_half_up(base * REPLACEMENT_SITE_FACTOR * 100, 0)
        return int(per_tree_cents) * count
    else:  # APPRAISED_VALUE
        dbh = Decimal(str(tree["dbh_inches"]))
        trunk_area = BASAL_AREA_FACTOR * (dbh * dbh)
        cf = CONDITION_FACTOR[tree["condition_class"]]
        appraisal = Decimal(str(species["base_appraisal_value_per_sqin"]))
        fee = round_half_up(appraisal * trunk_area * cf * 100, 0)
        return int(fee)


def risk_band(score):
    if score <= 3:
        return "LOW"
    if score <= 7:
        return "MODERATE"
    if score <= 11:
        return "HIGH"
    return "SEVERE"


def health_from_rating(rating):
    if rating == "SEVERE":
        return "HAZARD"
    if rating == "HIGH":
        return "DECLINING"
    return "HEALTHY"


# ---------------------------------------------------------------------------
# Zone recompute (canopy + counts) — one authoritative pass, bumps version
# ---------------------------------------------------------------------------
def recompute_zone(zone_id):
    zone = db.zones.get(zone_id)
    if zone is None:
        return
    live = Decimal(0)
    tree_count = 0
    high_risk = 0
    for t in db.trees.values():
        if t["zone_id"] != zone_id:
            continue
        if t["health_status"] != "REMOVED":
            tree_count += 1
            sp = db.species.get(t["species_id"])
            if sp is not None:
                live += Decimal(str(sp["mature_canopy_sqm"]))
            if t["risk_rating"] in ("HIGH", "SEVERE"):
                high_risk += 1
    for r in db.plantings.values():
        if r["target_zone_id"] == zone_id and r["status"] == "ESTABLISHED":
            sp = db.species.get(r["species_id"])
            if sp is not None:
                live += Decimal(str(sp["mature_canopy_sqm"]))

    area = Decimal(str(zone["area_sqm"]))
    pct = round_half_up(live / area * 100, 2)
    target = Decimal(str(zone["target_canopy_pct"]))
    status = "MEETS" if pct >= target else "DEFICIT"

    zone["live_canopy_sqm"] = to_number(live)
    zone["current_canopy_pct"] = to_number(pct)
    zone["canopy_status"] = status
    zone["tree_count"] = tree_count
    zone["high_risk_tree_count"] = high_risk
    touch(zone)


# ---------------------------------------------------------------------------
# Dig ticket lazy expiry
# ---------------------------------------------------------------------------
def lazy_expire_ticket(ticket):
    if ticket["status"] in ("REQUESTED", "VALID"):
        if clock_now() >= parse_dt(ticket["valid_to"]):
            ticket["status"] = "EXPIRED"


# ===========================================================================
# ZONES
# ===========================================================================
@app.route("/forestry/zones", methods=["POST"])
def create_zone():
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    body = get_body()
    name = req_str(body, "name")
    target = req_number(body, "target_canopy_pct")
    area = req_number(body, "area_sqm")
    if not (0 <= target <= 100):
        raise ApiError("ERR_INVALID_REQUEST", 400, "target_canopy_pct out of range")
    if not (area > 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "area_sqm must be > 0")
    zone = base_fields()
    zone.update({
        "name": name,
        "target_canopy_pct": target,
        "area_sqm": area,
        "live_canopy_sqm": 0,
        "current_canopy_pct": 0,
        "canopy_status": "DEFICIT",
        "high_risk_tree_count": 0,
        "tree_count": 0,
    })
    db.zones[zone["id"]] = zone
    return ok_object(serialize(zone), 201)


@app.route("/forestry/zones/<zid>", methods=["GET"])
def get_zone(zid):
    _, role = authenticate()
    authorize(role, ROLES)
    zone = get_or_404(db.zones, zid, "ERR_ZONE_NOT_FOUND")
    return ok_object(serialize(zone))


# ===========================================================================
# SPECIES
# ===========================================================================
@app.route("/forestry/species", methods=["POST"])
def create_species():
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    body = get_body()
    name = req_str(body, "name")
    is_protected_species = req_bool(body, "is_protected_species")
    is_native = req_bool(body, "is_native")
    mature = req_number(body, "mature_canopy_sqm")
    base_repl = req_number(body, "base_replacement_value_dollars")
    base_appr = req_number(body, "base_appraisal_value_per_sqin")
    min_spacing = req_number(body, "min_spacing_m")
    for label, val in (("mature_canopy_sqm", mature), ("base_replacement_value_dollars", base_repl),
                       ("base_appraisal_value_per_sqin", base_appr), ("min_spacing_m", min_spacing)):
        if val < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"{label} must be >= 0")
    sp = base_fields(versioned=False)
    sp.update({
        "name": name,
        "is_protected_species": is_protected_species,
        "is_native": is_native,
        "mature_canopy_sqm": mature,
        "base_replacement_value_dollars": base_repl,
        "base_appraisal_value_per_sqin": base_appr,
        "min_spacing_m": min_spacing,
    })
    db.species[sp["id"]] = sp
    return ok_object(serialize(sp), 201)


@app.route("/forestry/species/<sid>", methods=["GET"])
def get_species(sid):
    _, role = authenticate()
    authorize(role, ROLES)
    sp = get_or_404(db.species, sid, "ERR_SPECIES_NOT_FOUND")
    return ok_object(serialize(sp))


# ===========================================================================
# TREES
# ===========================================================================
@app.route("/forestry/trees", methods=["POST"])
def create_tree():
    _, role = authenticate()
    authorize(role, {"ForestryStaff"})
    body = get_body()
    zone_id = req_str(body, "zone_id")
    species_id = req_str(body, "species_id")
    dbh = req_number(body, "dbh_inches")
    canopy_radius = req_number(body, "canopy_radius_m")
    latitude = req_number(body, "latitude")
    longitude = req_number(body, "longitude")
    condition_class = req_enum(body, "condition_class", CONDITION_CLASSES)
    if not (dbh > 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "dbh_inches must be > 0")
    if canopy_radius < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "canopy_radius_m must be >= 0")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    species = get_or_404(db.species, species_id, "ERR_SPECIES_NOT_FOUND")

    is_protected = (dbh >= 8.0) or bool(species["is_protected_species"])
    tree = base_fields()
    tree.update({
        "zone_id": zone_id,
        "species_id": species_id,
        "dbh_inches": dbh,
        "canopy_radius_m": canopy_radius,
        "latitude": latitude,
        "longitude": longitude,
        "condition_class": condition_class,
        "is_protected": is_protected,
        "health_status": "HEALTHY",
        "risk_rating": "NONE",
        "prior_risk_rating": "NONE",
        "prior_health_status": "HEALTHY",
        "current_inspection_id": None,
    })
    db.trees[tree["id"]] = tree
    recompute_zone(zone_id)
    return ok_object(serialize(tree), 201)


@app.route("/forestry/trees/<tid>", methods=["GET"])
def get_tree(tid):
    _, role = authenticate()
    authorize(role, ROLES)
    tree = get_or_404(db.trees, tid, "ERR_TREE_NOT_FOUND")
    return ok_object(serialize(tree))


@app.route("/forestry/trees", methods=["GET"])
def list_trees():
    _, role = authenticate()
    authorize(role, ROLES)
    args = request.args
    items = list(db.trees.values())
    if "zone_id" in args:
        items = [t for t in items if t["zone_id"] == args.get("zone_id")]
    if "species_id" in args:
        items = [t for t in items if t["species_id"] == args.get("species_id")]
    if "health_status" in args:
        items = [t for t in items if t["health_status"] == args.get("health_status")]
    if "is_protected" in args:
        val = args.get("is_protected").lower() in ("true", "1")
        items = [t for t in items if bool(t["is_protected"]) == val]
    return list_response(items)


@app.route("/forestry/trees/<tid>/inspections", methods=["POST"])
def create_inspection(tid):
    _, role = authenticate()
    authorize(role, {"Inspector"})
    tree = get_or_404(db.trees, tid, "ERR_TREE_NOT_FOUND")
    body = get_body()
    expected_version = req_int(body, "expected_tree_version")
    inspection_type = req_enum(body, "inspection_type", INSPECTION_TYPES)
    likelihood = req_int(body, "likelihood_score")
    consequence = req_int(body, "consequence_score")
    target_rating = req_int(body, "target_rating")
    for label, v in (("likelihood_score", likelihood), ("consequence_score", consequence),
                     ("target_rating", target_rating)):
        if not (1 <= v <= 4):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"{label} must be between 1 and 4")

    # OCC
    if expected_version != tree["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_tree_version does not match current tree version")

    prov_score = likelihood * consequence
    prov_rating = risk_band(prov_score)

    insp = base_fields()
    insp.update({
        "tree_id": tid,
        "inspection_type": inspection_type,
        "likelihood_score": likelihood,
        "consequence_score": consequence,
        "target_rating": target_rating,
        "provisional_risk_score": prov_score,
        "provisional_risk_rating": prov_rating,
        "final_risk_score": None,
        "final_risk_rating": None,
        "status": "DRAFT",
    })
    db.inspections[insp["id"]] = insp
    tree["current_inspection_id"] = insp["id"]
    touch(tree)
    return ok_object(serialize(insp), 201)


@app.route("/forestry/trees/<tid>/inspections", methods=["GET"])
def list_tree_inspections(tid):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.trees, tid, "ERR_TREE_NOT_FOUND")
    items = [i for i in db.inspections.values() if i["tree_id"] == tid]
    return list_response(items)


# ===========================================================================
# INSPECTIONS
# ===========================================================================
@app.route("/forestry/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    _, role = authenticate()
    authorize(role, ROLES)
    insp = get_or_404(db.inspections, iid, "ERR_INSPECTION_NOT_FOUND")
    return ok_object(serialize(insp))


@app.route("/forestry/inspections/<iid>/finalize", methods=["POST"])
def finalize_inspection(iid):
    _, role = authenticate()
    authorize(role, {"Inspector"})
    insp = get_or_404(db.inspections, iid, "ERR_INSPECTION_NOT_FOUND")
    if insp["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection not in a finalizable state")

    final_score = min(
        insp["likelihood_score"] * insp["consequence_score"]
        + (TARGET_BONUS if insp["target_rating"] >= 3 else 0),
        SCORE_CAP,
    )
    final_rating = risk_band(final_score)

    tree = db.trees[insp["tree_id"]]
    tree["prior_risk_rating"] = tree["risk_rating"]
    tree["prior_health_status"] = tree["health_status"]
    tree["risk_rating"] = final_rating
    tree["health_status"] = health_from_rating(final_rating)
    touch(tree)
    recompute_zone(tree["zone_id"])

    insp["final_risk_score"] = final_score
    insp["final_risk_rating"] = final_rating
    insp["status"] = "FINALIZED"
    touch(insp)
    return ok_object(serialize(insp))


@app.route("/forestry/inspections/<iid>/dispute", methods=["POST"])
def dispute_inspection(iid):
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    insp = get_or_404(db.inspections, iid, "ERR_INSPECTION_NOT_FOUND")
    if insp["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection is not FINALIZED")
    tree = db.trees[insp["tree_id"]]
    if tree.get("current_inspection_id") != insp["id"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Only the latest finalized inspection may be disputed")

    tree["risk_rating"] = tree["prior_risk_rating"]
    tree["health_status"] = tree["prior_health_status"]
    touch(tree)
    recompute_zone(tree["zone_id"])

    insp["status"] = "DISPUTED"
    touch(insp)
    return ok_object(serialize(insp))


# ===========================================================================
# PERMITS
# ===========================================================================
@app.route("/forestry/permits", methods=["POST"])
def create_permit():
    uid, role = authenticate()
    authorize(role, {"Applicant"})
    body = get_body()
    tree_id = req_str(body, "tree_id")
    permit_type = req_enum(body, "permit_type", PERMIT_TYPES)
    reason = req_str(body, "reason")
    get_or_404(db.trees, tree_id, "ERR_TREE_NOT_FOUND")

    permit = base_fields()
    permit.update({
        "tree_id": tree_id,
        "permit_type": permit_type,
        "reason": reason,
        "requested_by_user_id": uid,
        "status": "DRAFT",
        "mitigation_method": None,
        "required_replacement_count": 0,
        "mitigation_fee_cents": 0,
        "fee_paid": False,
        "fee_paid_cents": 0,
        "review_notes": None,
        "_fee_outstanding": False,
    })
    db.permits[permit["id"]] = permit
    return ok_object(serialize(permit), 201)


@app.route("/forestry/permits/<pid>", methods=["GET"])
def get_permit(pid):
    _, role = authenticate()
    authorize(role, ROLES)
    permit = get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    return ok_object(serialize(permit))


@app.route("/forestry/permits", methods=["GET"])
def list_permits():
    _, role = authenticate()
    authorize(role, ROLES)
    args = request.args
    items = list(db.permits.values())
    if "tree_id" in args:
        items = [p for p in items if p["tree_id"] == args.get("tree_id")]
    if "status" in args:
        items = [p for p in items if p["status"] == args.get("status")]
    return list_response(items)


def _require_permit_owner(permit, uid):
    if permit["requested_by_user_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Applicant does not own this permit")


@app.route("/forestry/permits/<pid>/submit", methods=["POST"])
def submit_permit(pid):
    uid, role = authenticate()
    authorize(role, {"Applicant"})
    permit = get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    _require_permit_owner(permit, uid)
    if permit["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit not in DRAFT")
    tree = db.trees[permit["tree_id"]]
    if not tree["is_protected"]:
        raise ApiError("ERR_TREE_NOT_PROTECTED", 422, "Only a protected tree requires a permit")
    permit["status"] = "UNDER_REVIEW"
    touch(permit)
    return ok_object(serialize(permit))


@app.route("/forestry/permits/<pid>/review", methods=["POST"])
def review_permit(pid):
    _, role = authenticate()
    authorize(role, {"Arborist"})
    permit = get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    if permit["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit not in UNDER_REVIEW")

    review_notes = body.get("review_notes")
    if review_notes is not None:
        permit["review_notes"] = review_notes

    if decision == "DENY":
        permit["status"] = "DENIED"
        touch(permit)
        return ok_object(serialize(permit))
    if decision == "REQUEST_INFO":
        permit["status"] = "INFO_REQUESTED"
        touch(permit)
        return ok_object(serialize(permit))

    # APPROVE
    tree = db.trees[permit["tree_id"]]
    species = db.species[tree["species_id"]]
    if permit["permit_type"] == "REMOVAL":
        # inspection gate
        cur = tree.get("current_inspection_id")
        insp = db.inspections.get(cur) if cur else None
        if insp is None or insp["status"] != "FINALIZED":
            raise ApiError("ERR_INSPECTION_REQUIRED", 422, "REMOVAL approval requires a FINALIZED current inspection")
        # mitigation method
        if "mitigation_method" not in body or body.get("mitigation_method") is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "mitigation_method is required for REMOVAL approval")
        method = body.get("mitigation_method")
        if not isinstance(method, str) or method not in MITIGATION_METHODS:
            raise ApiError("ERR_INVALID_ENUM", 422, "Invalid mitigation_method")
        count = compute_required_replacement_count("REMOVAL", tree["dbh_inches"])
        fee = compute_mitigation_fee("REMOVAL", method, count, species, tree)
        permit["mitigation_method"] = method
        permit["required_replacement_count"] = count
        permit["mitigation_fee_cents"] = fee
        # create replacement plantings
        for i in range(1, count + 1):
            planting = base_fields()
            planting.update({
                "permit_id": permit["id"],
                "species_id": tree["species_id"],
                "target_zone_id": tree["zone_id"],
                "sequence_index": i,
                "status": "REQUIRED",
            })
            db.plantings[planting["id"]] = planting
        db.total_outstanding_mitigation_cents += fee
        permit["_fee_outstanding"] = True
    else:  # PRUNING
        permit["mitigation_method"] = None
        permit["required_replacement_count"] = 0
        permit["mitigation_fee_cents"] = 0

    permit["status"] = "APPROVED"
    touch(permit)
    return ok_object(serialize(permit))


@app.route("/forestry/permits/<pid>/provide-info", methods=["POST"])
def provide_info(pid):
    uid, role = authenticate()
    authorize(role, {"Applicant"})
    permit = get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    _require_permit_owner(permit, uid)
    if permit["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit not in INFO_REQUESTED")
    permit["status"] = "UNDER_REVIEW"
    touch(permit)
    return ok_object(serialize(permit))


@app.route("/forestry/permits/<pid>/pay-fee", methods=["POST"])
def pay_fee(pid):
    uid, role = authenticate()
    authorize(role, {"Applicant"})
    permit = get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    _require_permit_owner(permit, uid)
    body = get_body()
    amount = req_int(body, "amount_cents")
    if amount != permit["mitigation_fee_cents"]:
        raise ApiError("ERR_FEE_AMOUNT_MISMATCH", 422, "amount_cents must equal mitigation_fee_cents")
    permit["fee_paid"] = True
    permit["fee_paid_cents"] = amount
    touch(permit)
    return ok_object(serialize(permit))


@app.route("/forestry/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    _, role = authenticate()
    authorize(role, {"Arborist"})
    permit = get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    if permit["status"] != "APPROVED":
        raise ApiError("ERR_PERMIT_NOT_APPROVED", 409, "Permit must be APPROVED to issue")
    if not permit["fee_paid"]:
        raise ApiError("ERR_FEE_UNPAID", 402, "Permit fee must be paid before issuance")
    permit["status"] = "ISSUED"
    touch(permit)
    return ok_object(serialize(permit))


@app.route("/forestry/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    permit = get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    if permit["status"] not in ("APPROVED", "ISSUED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Only APPROVED or ISSUED permits may be revoked")
    body = get_body()
    if body.get("reason") is not None:
        permit["review_notes"] = permit.get("review_notes")  # reason is optional metadata, not persisted field
    if permit.get("_fee_outstanding"):
        db.total_outstanding_mitigation_cents -= permit["mitigation_fee_cents"]
        permit["_fee_outstanding"] = False
    permit["status"] = "REVOKED"
    touch(permit)
    return ok_object(serialize(permit))


@app.route("/forestry/permits/<pid>/replacement-plantings", methods=["GET"])
def list_permit_plantings(pid):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    items = [r for r in db.plantings.values() if r["permit_id"] == pid]
    return list_response(items)


# ===========================================================================
# REPLACEMENT PLANTINGS
# ===========================================================================
@app.route("/forestry/replacement-plantings/<rid>", methods=["GET"])
def get_planting(rid):
    _, role = authenticate()
    authorize(role, ROLES)
    r = get_or_404(db.plantings, rid, "ERR_REPLACEMENT_NOT_FOUND")
    return ok_object(serialize(r))


@app.route("/forestry/replacement-plantings", methods=["GET"])
def list_plantings():
    _, role = authenticate()
    authorize(role, ROLES)
    args = request.args
    items = list(db.plantings.values())
    if "permit_id" in args:
        items = [r for r in items if r["permit_id"] == args.get("permit_id")]
    if "species_id" in args:
        items = [r for r in items if r["species_id"] == args.get("species_id")]
    if "target_zone_id" in args:
        items = [r for r in items if r["target_zone_id"] == args.get("target_zone_id")]
    if "status" in args:
        items = [r for r in items if r["status"] == args.get("status")]
    return list_response(items)


@app.route("/forestry/replacement-plantings/<rid>/plant", methods=["POST"])
def plant_planting(rid):
    _, role = authenticate()
    authorize(role, {"ForestryStaff"})
    r = get_or_404(db.plantings, rid, "ERR_REPLACEMENT_NOT_FOUND")
    if r["status"] != "REQUIRED":
        raise ApiError("ERR_INVALID_STATE", 409, "Planting is not REQUIRED")
    permit = db.permits.get(r["permit_id"])
    if permit is None or permit["status"] not in ("APPROVED", "ISSUED", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Parent permit not in a plantable state")
    r["status"] = "PLANTED"
    touch(r)
    return ok_object(serialize(r))


@app.route("/forestry/replacement-plantings/<rid>/establish", methods=["POST"])
def establish_planting(rid):
    _, role = authenticate()
    authorize(role, {"Inspector"})
    r = get_or_404(db.plantings, rid, "ERR_REPLACEMENT_NOT_FOUND")
    if r["status"] != "PLANTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Planting is not PLANTED")
    r["status"] = "ESTABLISHED"
    touch(r)
    recompute_zone(r["target_zone_id"])
    return ok_object(serialize(r))


# ===========================================================================
# CONTRACTORS
# ===========================================================================
@app.route("/forestry/contractors", methods=["POST"])
def create_contractor():
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    body = get_body()
    name = req_str(body, "name")
    license_number = req_str(body, "license_number")
    _, license_expiry = req_datetime(body, "license_expiry")
    is_certified = req_bool(body, "is_certified_arborist")
    status = "ACTIVE"
    if "status" in body and body.get("status") is not None:
        status = req_enum(body, "status", CONTRACTOR_STATUSES)
    contractor = base_fields()
    contractor.update({
        "name": name,
        "license_number": license_number,
        "license_expiry": license_expiry,
        "is_certified_arborist": is_certified,
        "status": status,
    })
    db.contractors[contractor["id"]] = contractor
    return ok_object(serialize(contractor), 201)


@app.route("/forestry/contractors/<cid>", methods=["GET"])
def get_contractor(cid):
    _, role = authenticate()
    authorize(role, ROLES)
    c = get_or_404(db.contractors, cid, "ERR_CONTRACTOR_NOT_FOUND")
    return ok_object(serialize(c))


# ===========================================================================
# WORK ORDERS
# ===========================================================================
def _intervals_overlap_half_open(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/forestry/work-orders", methods=["POST"])
def create_work_order():
    _, role = authenticate()
    authorize(role, {"ForestryStaff"})
    body = get_body()
    tree_id = req_str(body, "tree_id")
    contractor_id = req_str(body, "contractor_id")
    work_type = req_enum(body, "work_type", WORK_TYPES)
    start_dt, scheduled_start = req_datetime(body, "scheduled_start")
    end_dt, scheduled_end = req_datetime(body, "scheduled_end")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_REQUEST", 400, "scheduled_end must be after scheduled_start")

    permit_id = body.get("permit_id")

    # FK resolution
    tree = get_or_404(db.trees, tree_id, "ERR_TREE_NOT_FOUND")
    contractor = get_or_404(db.contractors, contractor_id, "ERR_CONTRACTOR_NOT_FOUND")
    permit = None
    if work_type in ("REMOVAL", "PRUNING"):
        if permit_id is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "permit_id is required for REMOVAL/PRUNING work orders")
        if not isinstance(permit_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "permit_id must be a string")
        permit = get_or_404(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")

    # Business authorization by work type
    if work_type == "EMERGENCY_REMOVAL":
        permit_id = None  # emergency work is not authorized by a permit
        active_storm = None
        now = clock_now()
        for se in db.storm_events.values():
            if se["affected_zone_id"] == tree["zone_id"] and se["status"] == "ACTIVE":
                ws = parse_dt(se["window_start"])
                we = parse_dt(se["window_end"])
                if ws <= now <= we:
                    active_storm = se
                    break
        if active_storm is None:
            raise ApiError("ERR_EMERGENCY_NOT_DECLARED", 422,
                           "EMERGENCY_REMOVAL requires an ACTIVE storm event covering the tree's zone")
    else:
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Referenced permit must be ISSUED")

    # Double-booking (half-open) against CREATED/IN_PROGRESS work orders of same contractor
    for wo in db.work_orders.values():
        if wo["contractor_id"] != contractor_id:
            continue
        if wo["status"] not in ("CREATED", "IN_PROGRESS"):
            continue
        if _intervals_overlap_half_open(start_dt, end_dt,
                                        parse_dt(wo["scheduled_start"]), parse_dt(wo["scheduled_end"])):
            raise ApiError("ERR_CONTRACTOR_DOUBLE_BOOKED", 409, "Contractor is double-booked")

    # Contractor must be ACTIVE at create
    if contractor["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACTOR_LICENSE_EXPIRED", 422, "Assigned contractor is SUSPENDED")

    wo = base_fields()
    wo.update({
        "tree_id": tree_id,
        "permit_id": permit_id,
        "contractor_id": contractor_id,
        "work_type": work_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "CREATED",
    })
    db.work_orders[wo["id"]] = wo
    return ok_object(serialize(wo), 201)


@app.route("/forestry/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    _, role = authenticate()
    authorize(role, ROLES)
    wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    return ok_object(serialize(wo))


@app.route("/forestry/work-orders", methods=["GET"])
def list_work_orders():
    _, role = authenticate()
    authorize(role, ROLES)
    args = request.args
    items = list(db.work_orders.values())
    if "tree_id" in args:
        items = [w for w in items if w["tree_id"] == args.get("tree_id")]
    if "permit_id" in args:
        items = [w for w in items if w["permit_id"] == args.get("permit_id")]
    if "contractor_id" in args:
        items = [w for w in items if w["contractor_id"] == args.get("contractor_id")]
    if "status" in args:
        items = [w for w in items if w["status"] == args.get("status")]
    return list_response(items)


def _require_wo_owner(wo, uid):
    if wo["contractor_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Contractor does not own this work order")


@app.route("/forestry/work-orders/<wid>/start", methods=["POST"])
def start_work_order(wid):
    uid, role = authenticate()
    authorize(role, {"Contractor"})
    wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    _require_wo_owner(wo, uid)
    if wo["status"] != "CREATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not CREATED")

    now = clock_now()
    # Safety: a VALID in-window dig ticket must exist (outranks license check)
    has_valid = False
    for tk in db.dig_tickets.values():
        if tk["work_order_id"] != wid:
            continue
        lazy_expire_ticket(tk)
        if tk["status"] == "VALID" and parse_dt(tk["valid_from"]) <= now < parse_dt(tk["valid_to"]):
            has_valid = True
            break
    if not has_valid:
        raise ApiError("ERR_DIG_TICKET_INVALID", 409, "No VALID in-window dig ticket for this work order")

    # Referential: contractor ACTIVE with unexpired license
    contractor = db.contractors[wo["contractor_id"]]
    if contractor["status"] != "ACTIVE" or now >= parse_dt(contractor["license_expiry"]):
        raise ApiError("ERR_CONTRACTOR_LICENSE_EXPIRED", 422, "Contractor license expired or not ACTIVE")

    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return ok_object(serialize(wo))


@app.route("/forestry/work-orders/<wid>/complete", methods=["POST"])
def complete_work_order(wid):
    uid, role = authenticate()
    authorize(role, {"Contractor"})
    wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    _require_wo_owner(wo, uid)
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not IN_PROGRESS")

    wo["status"] = "COMPLETED"
    touch(wo)

    if wo["work_type"] in ("REMOVAL", "EMERGENCY_REMOVAL"):
        tree = db.trees.get(wo["tree_id"])
        if tree is not None:
            tree["health_status"] = "REMOVED"
            touch(tree)
            recompute_zone(tree["zone_id"])

    if wo["permit_id"] is not None:
        permit = db.permits.get(wo["permit_id"])
        if permit is not None and permit["status"] == "ISSUED":
            permit["status"] = "CLOSED"
            if permit.get("_fee_outstanding"):
                db.total_outstanding_mitigation_cents -= permit["mitigation_fee_cents"]
                permit["_fee_outstanding"] = False
            touch(permit)

    return ok_object(serialize(wo))


@app.route("/forestry/work-orders/<wid>/abort", methods=["POST"])
def abort_work_order(wid):
    _, role = authenticate()
    authorize(role, {"ForestryStaff"})
    wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    if wo["status"] not in ("CREATED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", 409, "Work order cannot be aborted from its current state")
    wo["status"] = "ABORTED"
    touch(wo)
    return ok_object(serialize(wo))


# ===========================================================================
# DIG TICKETS (811)
# ===========================================================================
@app.route("/forestry/work-orders/<wid>/dig-tickets", methods=["POST"])
def create_dig_ticket(wid):
    uid, role = authenticate()
    authorize(role, {"Contractor"})
    wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    _require_wo_owner(wo, uid)
    body = get_body()
    ticket_number = req_str(body, "ticket_number")
    vf_dt, valid_from = req_datetime(body, "valid_from")
    vt_dt, valid_to = req_datetime(body, "valid_to")
    if not (vt_dt > vf_dt):
        raise ApiError("ERR_DIG_WINDOW_INVALID", 422, "valid_to must be strictly after valid_from")
    tk = base_fields()
    tk.update({
        "work_order_id": wid,
        "ticket_number": ticket_number,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "REQUESTED",
    })
    db.dig_tickets[tk["id"]] = tk
    return ok_object(serialize(tk), 201)


@app.route("/forestry/work-orders/<wid>/dig-tickets", methods=["GET"])
def list_dig_tickets(wid):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    items = [t for t in db.dig_tickets.values() if t["work_order_id"] == wid]
    for t in items:
        lazy_expire_ticket(t)
    return list_response(items)


@app.route("/forestry/dig-tickets/<tid>", methods=["GET"])
def get_dig_ticket(tid):
    _, role = authenticate()
    authorize(role, ROLES)
    tk = get_or_404(db.dig_tickets, tid, "ERR_DIG_TICKET_NOT_FOUND")
    lazy_expire_ticket(tk)
    return ok_object(serialize(tk))


@app.route("/forestry/dig-tickets/<tid>/mark-valid", methods=["POST"])
def mark_valid_dig_ticket(tid):
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    tk = get_or_404(db.dig_tickets, tid, "ERR_DIG_TICKET_NOT_FOUND")
    lazy_expire_ticket(tk)
    if tk["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Dig ticket is not REQUESTED")
    tk["status"] = "VALID"
    touch(tk)
    return ok_object(serialize(tk))


# ===========================================================================
# STORM EVENTS
# ===========================================================================
def _intervals_overlap_closed(s1, e1, s2, e2):
    return s1 <= e2 and s2 <= e1


@app.route("/forestry/storm-events", methods=["POST"])
def create_storm_event():
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    body = get_body()
    zone_id = req_str(body, "affected_zone_id")
    severity = req_enum(body, "severity", SEVERITIES)
    ws_dt, window_start = req_datetime(body, "window_start")
    we_dt, window_end = req_datetime(body, "window_end")
    get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if not (we_dt > ws_dt):
        raise ApiError("ERR_INVALID_REQUEST", 400, "window_end must be strictly after window_start")

    for se in db.storm_events.values():
        if se["affected_zone_id"] == zone_id and se["status"] == "ACTIVE":
            if _intervals_overlap_closed(ws_dt, we_dt,
                                         parse_dt(se["window_start"]), parse_dt(se["window_end"])):
                raise ApiError("ERR_STORM_OVERLAP", 409, "Overlapping ACTIVE storm event on this zone")

    se = base_fields()
    se.update({
        "affected_zone_id": zone_id,
        "severity": severity,
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
    })
    db.storm_events[se["id"]] = se
    return ok_object(serialize(se), 201)


@app.route("/forestry/storm-events/<sid>", methods=["GET"])
def get_storm_event(sid):
    _, role = authenticate()
    authorize(role, ROLES)
    se = get_or_404(db.storm_events, sid, "ERR_STORM_EVENT_NOT_FOUND")
    return ok_object(serialize(se))


@app.route("/forestry/storm-events", methods=["GET"])
def list_storm_events():
    _, role = authenticate()
    authorize(role, ROLES)
    args = request.args
    items = list(db.storm_events.values())
    if "affected_zone_id" in args:
        items = [s for s in items if s["affected_zone_id"] == args.get("affected_zone_id")]
    if "status" in args:
        items = [s for s in items if s["status"] == args.get("status")]
    return list_response(items)


@app.route("/forestry/storm-events/<sid>/close", methods=["POST"])
def close_storm_event(sid):
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    se = get_or_404(db.storm_events, sid, "ERR_STORM_EVENT_NOT_FOUND")
    if se["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Storm event is not ACTIVE")
    se["status"] = "CLOSED"
    touch(se)
    return ok_object(serialize(se))


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/forestry/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"ForestryAdmin"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 is required")
    try:
        db.clock = parse_dt(to_iso)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid to_iso8601 instant")
    return ok_object({})


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
db = DB()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
