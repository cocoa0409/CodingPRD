"""Bird & Aviary Supply API — single-file Flask implementation.

In-memory only. Boots empty on every invocation (no seeding).
All structural names (headers, envelope, error ids, pagination) trace to PRD.md /
SCAFFOLD.yaml.
"""

import os
import math
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculations)
# ---------------------------------------------------------------------------
DAY_SECONDS = 86400
QUARANTINE_MIN_DAYS = 14
CLEANING_BUFFER_SECONDS = 12 * 3600
LATE_FEE_CENTS = 2000

TIER_BASE_CENTS = {"STANDARD": 4000, "PREMIUM": 7000}
PER_BIRD_CENTS = 1500
FRESH_SURCHARGE_CENTS = 2500
CLUB_DISCOUNT_PCT = {"NONE": "0", "SILVER": "0.10", "GOLD": "0.20"}

SPECIES_RISK = {"I": 40, "II": 25, "III": 15, "NONE": 5}
IMPORT_PENALTY = 20
FAILED_TEST_PENALTY = 15
RETEST_PENALTY = 5
QUARANTINE_FAIL_THRESHOLD = 60

ROLES = {"Customer", "AviaryStaff", "ComplianceOfficer", "StoreManager"}
ALL_ROLES = ["StoreManager", "AviaryStaff", "ComplianceOfficer", "Customer"]

CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
customers = {}
species = {}
permits = {}
birds = {}
quarantines = {}
cages = {}
reservations = {}
stations = {}
appointments = {}
subscriptions = {}
inventory = {}
orders = {}

logical_clock = CLOCK_DEFAULT
_seq_counter = 0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Helpers: time & formatting
# ---------------------------------------------------------------------------
def now_wall():
    return datetime.now(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def nights_between(a, b):
    secs = (b - a).total_seconds()
    n = math.ceil(secs / DAY_SECONDS)
    return max(1, n)


def round_half_up(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_common():
    ts = now_wall()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_wall()


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": iso(now_wall()),
    }


def respond_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def respond_list(items, limit, offset, total, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.error_id},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC / body helpers
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_MISSING_USER_CONTEXT", 400)
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403)
    return uid, role


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return data


def must_get(store, key, err):
    if not isinstance(key, str) or key not in store:
        raise ApiError(err, 404)
    return store[key]


def owner_check(resource, uid, role):
    if role == "Customer" and resource.get("customer_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def req_enum(body, field, choices):
    v = body.get(field)
    if v not in choices:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(e) for e in page], limit, offset, total


# ---------------------------------------------------------------------------
# Lazy permit expiry sweep (PRD §2.7 / §2.10)
# ---------------------------------------------------------------------------
def recompute_listed(sp):
    sp["listed_bird_count"] = sum(
        1 for b in birds.values()
        if b["species_id"] == sp["id"] and b["status"] == "LISTED"
    )


def cascade_restrict(sp):
    """Species -> RESTRICTED; LISTED birds -> SUSPENDED; recompute count."""
    sp["status"] = "RESTRICTED"
    for b in birds.values():
        if b["species_id"] == sp["id"] and b["status"] == "LISTED":
            b["status"] = "SUSPENDED"
            touch(b)
    recompute_listed(sp)
    touch(sp)


@app.before_request
def apply_permit_expiries():
    for p in list(permits.values()):
        if p["status"] == "APPROVED" and logical_clock >= p["valid_until"]:
            p["status"] = "EXPIRED"
            touch(p)
            sp = species.get(p["species_id"])
            if sp is not None:
                cascade_restrict(sp)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_subscription_charge(tier, bird_count, fresh_feed, club_tier):
    subtotal = TIER_BASE_CENTS[tier] + PER_BIRD_CENTS * bird_count
    if fresh_feed:
        subtotal += FRESH_SURCHARGE_CENTS
    pct = Decimal(CLUB_DISCOUNT_PCT[club_tier])
    return round_half_up(Decimal(subtotal) * (Decimal(1) - pct))


def compute_invoice_total(line_items):
    total = 0
    for line in line_items:
        sub = line["unit_price_cents"] * line["quantity"]
        tax = round_half_up(Decimal(sub) * Decimal(str(line["tax_rate"])))
        total += sub + tax
    return total


def species_base_risk(sp):
    return SPECIES_RISK[sp["cites_appendix"]]


def final_risk(sp, rec):
    return (
        species_base_risk(sp)
        + FAILED_TEST_PENALTY * rec["failed_test_count"]
        + RETEST_PENALTY * rec["retest_count"]
    )


def recompute_cage_status(cage):
    if cage["status"] == "OUT_OF_SERVICE":
        return
    cage["status"] = "OCCUPIED" if cage["current_occupancy"] >= cage["capacity"] else "AVAILABLE"


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(ALL_ROLES)
    body = get_body()
    global logical_clock
    logical_clock = parse_dt(body.get("to_iso8601"))
    return respond_object({}, 200)


# ===========================================================================
# CUSTOMERS
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    require_auth(["StoreManager"])
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    c = new_common()
    c.update({
        "full_name": full_name,
        "email": email,
        "club_tier": "NONE",
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
    })
    customers[c["id"]] = c
    return respond_object(serialize(c), 201)


@app.route("/customers", methods=["GET"])
def list_customers():
    require_auth(ALL_ROLES)
    page, limit, offset, total = paginate(list(customers.values()))
    return respond_list(page, limit, offset, total)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_auth(ALL_ROLES)
    c = must_get(customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    return respond_object(serialize(c))


@app.route("/customers/<cid>/club-membership", methods=["POST"])
def set_club(cid):
    require_auth(["StoreManager"])
    body = get_body()
    c = must_get(customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    tier = req_enum(body, "club_tier", ("NONE", "SILVER", "GOLD"))
    c["club_tier"] = tier
    touch(c)
    return respond_object(serialize(c))


@app.route("/customers/<cid>/wallet/adjustments", methods=["POST"])
def wallet_adjust(cid):
    require_auth(["StoreManager"])
    body = get_body()
    c = must_get(customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    amount = req_int(body, "amount_cents")
    c["wallet_credit_cents"] += amount
    touch(c)
    return respond_object(serialize(c))


@app.route("/customers/<cid>/suspend", methods=["POST"])
def suspend_customer(cid):
    require_auth(["StoreManager"])
    c = must_get(customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    c["status"] = "SUSPENDED"
    touch(c)
    return respond_object(serialize(c))


# ===========================================================================
# SPECIES
# ===========================================================================
@app.route("/species", methods=["POST"])
def create_species():
    require_auth(["ComplianceOfficer"])
    body = get_body()
    common_name = req_str(body, "common_name")
    scientific_name = req_str(body, "scientific_name")
    appendix = req_enum(body, "cites_appendix", ("I", "II", "III", "NONE"))
    sp = new_common()
    sp.update({
        "common_name": common_name,
        "scientific_name": scientific_name,
        "cites_appendix": appendix,
        "permit_required": appendix in ("I", "II", "III"),
        "status": "ACTIVE",
        "listed_bird_count": 0,
    })
    species[sp["id"]] = sp
    return respond_object(serialize(sp), 201)


@app.route("/species", methods=["GET"])
def list_species():
    require_auth(ALL_ROLES)
    page, limit, offset, total = paginate(list(species.values()))
    return respond_list(page, limit, offset, total)


@app.route("/species/<sid>", methods=["GET"])
def get_species(sid):
    require_auth(ALL_ROLES)
    sp = must_get(species, sid, "ERR_SPECIES_NOT_FOUND")
    return respond_object(serialize(sp))


@app.route("/species/<sid>/permits", methods=["GET"])
def species_permits(sid):
    require_auth(ALL_ROLES)
    must_get(species, sid, "ERR_SPECIES_NOT_FOUND")
    items = [p for p in permits.values() if p["species_id"] == sid]
    page, limit, offset, total = paginate(items)
    return respond_list(page, limit, offset, total)


# ===========================================================================
# CITES PERMITS
# ===========================================================================
@app.route("/cites-permits", methods=["POST"])
def create_permit():
    require_auth(["ComplianceOfficer"])
    body = get_body()
    species_id = body.get("species_id")
    must_get(species, species_id, "ERR_SPECIES_NOT_FOUND")
    permit_number = req_str(body, "permit_number")
    valid_until = parse_dt(body.get("valid_until"))
    p = new_common()
    p.update({
        "species_id": species_id,
        "permit_number": permit_number,
        "valid_until": valid_until,
        "status": "DRAFT",
    })
    permits[p["id"]] = p
    return respond_object(serialize(p), 201)


@app.route("/cites-permits/<pid>", methods=["GET"])
def get_permit(pid):
    require_auth(ALL_ROLES)
    p = must_get(permits, pid, "ERR_PERMIT_NOT_FOUND")
    return respond_object(serialize(p))


@app.route("/cites-permits/<pid>/submit", methods=["POST"])
def submit_permit(pid):
    require_auth(["ComplianceOfficer"])
    p = must_get(permits, pid, "ERR_PERMIT_NOT_FOUND")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    p["status"] = "SUBMITTED"
    touch(p)
    return respond_object(serialize(p))


@app.route("/cites-permits/<pid>/return-for-revision", methods=["POST"])
def return_permit(pid):
    require_auth(["ComplianceOfficer"])
    p = must_get(permits, pid, "ERR_PERMIT_NOT_FOUND")
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    p["status"] = "DRAFT"
    touch(p)
    return respond_object(serialize(p))


@app.route("/cites-permits/<pid>/approve", methods=["POST"])
def approve_permit(pid):
    require_auth(["ComplianceOfficer"])
    p = must_get(permits, pid, "ERR_PERMIT_NOT_FOUND")
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if not (p["valid_until"] > logical_clock):
        raise ApiError("ERR_PERMIT_EXPIRED_INPUT", 400)
    p["status"] = "APPROVED"
    touch(p)
    sp = species.get(p["species_id"])
    if sp is not None:
        sp["status"] = "ACTIVE"
        touch(sp)
    return respond_object(serialize(p))


@app.route("/cites-permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    require_auth(["ComplianceOfficer"])
    p = must_get(permits, pid, "ERR_PERMIT_NOT_FOUND")
    if p["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    p["status"] = "REVOKED"
    touch(p)
    sp = species.get(p["species_id"])
    if sp is not None:
        cascade_restrict(sp)
    return respond_object(serialize(p))


# ===========================================================================
# BIRDS
# ===========================================================================
@app.route("/birds", methods=["POST"])
def create_bird():
    require_auth(["AviaryStaff"])
    body = get_body()
    species_id = body.get("species_id")
    must_get(species, species_id, "ERR_SPECIES_NOT_FOUND")
    band_code = req_str(body, "band_code")
    list_price = req_int(body, "list_price_cents")
    imported = body.get("imported", False)
    if not isinstance(imported, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    b = new_common()
    b.update({
        "species_id": species_id,
        "housing_cage_id": None,
        "band_code": band_code,
        "imported": imported,
        "list_price_cents": list_price,
        "provisional_risk_score": None,
        "final_risk_score": None,
        "status": "INTAKE",
    })
    birds[b["id"]] = b
    return respond_object(serialize(b), 201)


@app.route("/birds", methods=["GET"])
def list_birds():
    require_auth(ALL_ROLES)
    items = list(birds.values())
    sp_filter = request.args.get("species_id")
    cage_filter = request.args.get("housing_cage_id")
    if sp_filter is not None:
        items = [b for b in items if b["species_id"] == sp_filter]
    if cage_filter is not None:
        items = [b for b in items if b["housing_cage_id"] == cage_filter]
    page, limit, offset, total = paginate(items)
    return respond_list(page, limit, offset, total)


@app.route("/birds/<bid>", methods=["GET"])
def get_bird(bid):
    require_auth(ALL_ROLES)
    b = must_get(birds, bid, "ERR_BIRD_NOT_FOUND")
    return respond_object(serialize(b))


@app.route("/birds/<bid>/quarantine-records", methods=["GET"])
def bird_quarantines(bid):
    require_auth(ALL_ROLES)
    must_get(birds, bid, "ERR_BIRD_NOT_FOUND")
    items = [q for q in quarantines.values() if q["bird_id"] == bid]
    page, limit, offset, total = paginate(items)
    return respond_list(page, limit, offset, total)


@app.route("/birds/<bid>/start-quarantine", methods=["POST"])
def start_quarantine(bid):
    require_auth(["AviaryStaff"])
    body = get_body()
    b = must_get(birds, bid, "ERR_BIRD_NOT_FOUND")
    cage_id = body.get("cage_id")
    cage = must_get(cages, cage_id, "ERR_CAGE_NOT_FOUND")
    if b["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE", 409)
    if cage["cage_class"] != "HOUSING" or cage["current_occupancy"] >= cage["capacity"]:
        raise ApiError("ERR_NO_HOUSING_CAPACITY", 409)
    sp = species[b["species_id"]]
    rec = new_common()
    rec.update({
        "bird_id": b["id"],
        "opened_at": logical_clock,
        "min_clear_at": logical_clock + timedelta(seconds=QUARANTINE_MIN_DAYS * DAY_SECONDS),
        "failed_test_count": 0,
        "retest_count": 0,
        "status": "OPEN",
    })
    quarantines[rec["id"]] = rec
    b["housing_cage_id"] = cage["id"]
    b["status"] = "IN_QUARANTINE"
    b["provisional_risk_score"] = species_base_risk(sp) + (IMPORT_PENALTY if b["imported"] else 0)
    touch(b)
    cage["current_occupancy"] += 1
    recompute_cage_status(cage)
    touch(cage)
    return respond_object(serialize(b))


@app.route("/birds/<bid>/list-for-sale", methods=["POST"])
def list_for_sale(bid):
    require_auth(["AviaryStaff"])
    b = must_get(birds, bid, "ERR_BIRD_NOT_FOUND")
    if b["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", 409)
    sp = species[b["species_id"]]
    if sp["status"] != "ACTIVE":
        raise ApiError("ERR_SPECIES_RESTRICTED", 409)
    if sp["permit_required"]:
        ok = any(
            p["species_id"] == sp["id"] and p["status"] == "APPROVED"
            and p["valid_until"] > logical_clock
            for p in permits.values()
        )
        if not ok:
            raise ApiError("ERR_PERMIT_NOT_APPROVED", 409)
    b["status"] = "LISTED"
    touch(b)
    recompute_listed(sp)
    touch(sp)
    return respond_object(serialize(b))


@app.route("/birds/<bid>/relist", methods=["POST"])
def relist_bird(bid):
    require_auth(["AviaryStaff"])
    b = must_get(birds, bid, "ERR_BIRD_NOT_FOUND")
    if b["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409)
    sp = species[b["species_id"]]
    if sp["status"] != "ACTIVE":
        raise ApiError("ERR_SPECIES_RESTRICTED", 409)
    b["status"] = "LISTED"
    touch(b)
    recompute_listed(sp)
    touch(sp)
    return respond_object(serialize(b))


@app.route("/birds/<bid>/sell", methods=["POST"])
def sell_bird(bid):
    require_auth(["AviaryStaff"])
    body = get_body()
    b = must_get(birds, bid, "ERR_BIRD_NOT_FOUND")
    buyer_id = body.get("buyer_customer_id")
    buyer = must_get(customers, buyer_id, "ERR_CUSTOMER_NOT_FOUND")
    if b["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    sp = species[b["species_id"]]
    if sp["status"] != "ACTIVE":
        raise ApiError("ERR_SPECIES_RESTRICTED", 409)
    if buyer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409)
    b["status"] = "SOLD"
    cage = cages.get(b["housing_cage_id"]) if b["housing_cage_id"] else None
    b["housing_cage_id"] = None
    touch(b)
    recompute_listed(sp)
    touch(sp)
    if cage is not None:
        cage["current_occupancy"] = max(0, cage["current_occupancy"] - 1)
        recompute_cage_status(cage)
        touch(cage)
    return respond_object(serialize(b))


# ===========================================================================
# QUARANTINE RECORDS
# ===========================================================================
@app.route("/quarantine-records/<qid>", methods=["GET"])
def get_quarantine(qid):
    require_auth(ALL_ROLES)
    rec = must_get(quarantines, qid, "ERR_QUARANTINE_NOT_FOUND")
    return respond_object(serialize(rec))


@app.route("/quarantine-records/<qid>/start-test", methods=["POST"])
def start_test(qid):
    require_auth(["AviaryStaff"])
    rec = must_get(quarantines, qid, "ERR_QUARANTINE_NOT_FOUND")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_QUARANTINE_NOT_OPEN", 409)
    rec["status"] = "UNDER_TEST"
    touch(rec)
    return respond_object(serialize(rec))


@app.route("/quarantine-records/<qid>/record-test-result", methods=["POST"])
def record_test_result(qid):
    require_auth(["AviaryStaff"])
    body = get_body()
    rec = must_get(quarantines, qid, "ERR_QUARANTINE_NOT_FOUND")
    result = req_enum(body, "result", ("FAIL", "RETEST"))
    if rec["status"] != "UNDER_TEST":
        raise ApiError("ERR_QUARANTINE_NOT_OPEN", 409)
    if result == "FAIL":
        rec["failed_test_count"] += 1
    else:  # RETEST
        rec["retest_count"] += 1
        rec["status"] = "OPEN"
    touch(rec)
    return respond_object(serialize(rec))


@app.route("/quarantine-records/<qid>/clear", methods=["POST"])
def clear_quarantine(qid):
    require_auth(["AviaryStaff"])
    rec = must_get(quarantines, qid, "ERR_QUARANTINE_NOT_FOUND")
    if rec["status"] not in ("OPEN", "UNDER_TEST"):
        raise ApiError("ERR_INVALID_STATE", 409)
    if logical_clock < rec["min_clear_at"]:
        raise ApiError("ERR_QUARANTINE_TOO_EARLY", 409)
    b = birds[rec["bird_id"]]
    sp = species[b["species_id"]]
    fr = final_risk(sp, rec)
    if fr >= QUARANTINE_FAIL_THRESHOLD:
        raise ApiError("ERR_RISK_TOO_HIGH_TO_CLEAR", 409)
    rec["status"] = "CLEARED"
    touch(rec)
    b["final_risk_score"] = fr
    b["status"] = "CLEARED"
    touch(b)
    return respond_object(serialize(rec))


@app.route("/quarantine-records/<qid>/fail", methods=["POST"])
def fail_quarantine(qid):
    require_auth(["AviaryStaff"])
    rec = must_get(quarantines, qid, "ERR_QUARANTINE_NOT_FOUND")
    if rec["status"] not in ("OPEN", "UNDER_TEST"):
        raise ApiError("ERR_INVALID_STATE", 409)
    b = birds[rec["bird_id"]]
    sp = species[b["species_id"]]
    rec["status"] = "FAILED"
    touch(rec)
    b["final_risk_score"] = final_risk(sp, rec)
    b["status"] = "REJECTED"
    cage = cages.get(b["housing_cage_id"]) if b["housing_cage_id"] else None
    b["housing_cage_id"] = None
    touch(b)
    if cage is not None:
        cage["current_occupancy"] = max(0, cage["current_occupancy"] - 1)
        recompute_cage_status(cage)
        touch(cage)
    return respond_object(serialize(rec))


# ===========================================================================
# CAGE UNITS
# ===========================================================================
@app.route("/cage-units", methods=["POST"])
def create_cage():
    require_auth(["StoreManager"])
    body = get_body()
    label = req_str(body, "label")
    cage_class = req_enum(body, "cage_class", ("HOUSING", "BOARDING"))
    capacity = req_int(body, "capacity")
    if capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    nightly = body.get("nightly_rate_cents", 0)
    if isinstance(nightly, bool) or not isinstance(nightly, int):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    cage = new_common()
    cage.update({
        "label": label,
        "cage_class": cage_class,
        "capacity": capacity,
        "nightly_rate_cents": nightly,
        "current_occupancy": 0,
        "status": "AVAILABLE",
    })
    cages[cage["id"]] = cage
    return respond_object(serialize(cage), 201)


@app.route("/cage-units", methods=["GET"])
def list_cages():
    require_auth(ALL_ROLES)
    page, limit, offset, total = paginate(list(cages.values()))
    return respond_list(page, limit, offset, total)


@app.route("/cage-units/<cid>", methods=["GET"])
def get_cage(cid):
    require_auth(ALL_ROLES)
    cage = must_get(cages, cid, "ERR_CAGE_NOT_FOUND")
    return respond_object(serialize(cage))


@app.route("/cage-units/<cid>", methods=["PATCH"])
def patch_cage(cid):
    require_auth(["StoreManager"])
    body = get_body()
    cage = must_get(cages, cid, "ERR_CAGE_NOT_FOUND")
    expected = req_int(body, "expected_cage_version")
    if expected != cage["version"]:
        raise ApiError("ERR_STALE_CAGE_VERSION", 412)
    if "nightly_rate_cents" in body:
        v = body["nightly_rate_cents"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ApiError("ERR_INVALID_REQUEST", 400)
        cage["nightly_rate_cents"] = v
    if "capacity" in body:
        v = body["capacity"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400)
        cage["capacity"] = v
    if "status" in body:
        v = body["status"]
        if v not in ("AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE"):
            raise ApiError("ERR_INVALID_REQUEST", 400)
        cage["status"] = v
    touch(cage)
    return respond_object(serialize(cage))


# ===========================================================================
# BOARDING RESERVATIONS
# ===========================================================================
@app.route("/boarding-reservations", methods=["POST"])
def create_reservation():
    uid, role = require_auth(["Customer"])
    body = get_body()
    customer_id = body.get("customer_id")
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    must_get(customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    cage_id = body.get("cage_id")
    cage = must_get(cages, cage_id, "ERR_CAGE_NOT_FOUND")
    planned_in = parse_dt(body.get("planned_check_in"))
    planned_out = parse_dt(body.get("planned_check_out"))
    if not (planned_out > planned_in):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    # cage time conflict (12h buffer, non-cancelled reservations on the cage)
    for r in reservations.values():
        if r["cage_id"] != cage_id or r["status"] == "CANCELLED":
            continue
        a_in, a_out = planned_in, planned_out
        b_in, b_out = r["planned_check_in"], r["planned_check_out"]
        buf = timedelta(seconds=CLEANING_BUFFER_SECONDS)
        if a_in < (b_out + buf) and b_in < (a_out + buf):
            raise ApiError("ERR_CAGE_TIME_CONFLICT", 409)
    provisional = cage["nightly_rate_cents"] * nights_between(planned_in, planned_out)
    r = new_common()
    r.update({
        "customer_id": customer_id,
        "cage_id": cage_id,
        "planned_check_in": planned_in,
        "planned_check_out": planned_out,
        "actual_check_out": None,
        "provisional_cost_cents": provisional,
        "final_cost_cents": None,
        "status": "RESERVED",
    })
    reservations[r["id"]] = r
    return respond_object(serialize(r), 201)


@app.route("/boarding-reservations", methods=["GET"])
def list_reservations():
    require_auth(ALL_ROLES)
    items = list(reservations.values())
    cf = request.args.get("customer_id")
    kf = request.args.get("cage_id")
    if cf is not None:
        items = [r for r in items if r["customer_id"] == cf]
    if kf is not None:
        items = [r for r in items if r["cage_id"] == kf]
    page, limit, offset, total = paginate(items)
    return respond_list(page, limit, offset, total)


@app.route("/boarding-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    require_auth(ALL_ROLES)
    r = must_get(reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    return respond_object(serialize(r))


@app.route("/boarding-reservations/<rid>/check-in", methods=["POST"])
def check_in(rid):
    require_auth(["AviaryStaff"])
    r = must_get(reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    if r["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    cage = cages[r["cage_id"]]
    if (logical_clock < r["planned_check_in"]
            or cage["status"] == "OUT_OF_SERVICE"
            or cage["current_occupancy"] >= cage["capacity"]):
        raise ApiError("ERR_NO_BOARDING_CAPACITY", 409)
    r["status"] = "CHECKED_IN"
    touch(r)
    cage["current_occupancy"] += 1
    recompute_cage_status(cage)
    touch(cage)
    return respond_object(serialize(r))


@app.route("/boarding-reservations/<rid>/check-out", methods=["POST"])
def check_out(rid):
    require_auth(["AviaryStaff"])
    r = must_get(reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    if r["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409)
    cage = cages[r["cage_id"]]
    actual_out = logical_clock
    nights = nights_between(r["planned_check_in"], actual_out)
    late = LATE_FEE_CENTS if actual_out > r["planned_check_out"] else 0
    final_cost = cage["nightly_rate_cents"] * nights + late
    cust = customers[r["customer_id"]]
    if cust["wallet_credit_cents"] - final_cost < 0:
        raise ApiError("ERR_INSUFFICIENT_WALLET", 402)
    cust["wallet_credit_cents"] -= final_cost
    touch(cust)
    r["actual_check_out"] = actual_out
    r["final_cost_cents"] = final_cost
    r["status"] = "CHECKED_OUT"
    touch(r)
    cage["current_occupancy"] = max(0, cage["current_occupancy"] - 1)
    recompute_cage_status(cage)
    touch(cage)
    return respond_object(serialize(r))


@app.route("/boarding-reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    uid, role = require_auth(["Customer"])
    r = must_get(reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    owner_check(r, uid, role)
    if r["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    r["status"] = "CANCELLED"
    touch(r)
    return respond_object(serialize(r))


# ===========================================================================
# GROOMING STATIONS
# ===========================================================================
@app.route("/grooming-stations", methods=["POST"])
def create_station():
    require_auth(["StoreManager"])
    body = get_body()
    label = req_str(body, "label")
    svc = body.get("service_types")
    if not isinstance(svc, list) or any(s not in ("WING_TRIM", "NAIL_TRIM") for s in svc):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    st = new_common()
    st.update({"label": label, "service_types": svc, "status": "OPEN"})
    stations[st["id"]] = st
    return respond_object(serialize(st), 201)


@app.route("/grooming-stations", methods=["GET"])
def list_stations():
    require_auth(ALL_ROLES)
    page, limit, offset, total = paginate(list(stations.values()))
    return respond_list(page, limit, offset, total)


@app.route("/grooming-stations/<sid>", methods=["GET"])
def get_station(sid):
    require_auth(ALL_ROLES)
    st = must_get(stations, sid, "ERR_STATION_NOT_FOUND")
    return respond_object(serialize(st))


@app.route("/grooming-stations/<sid>/close", methods=["POST"])
def close_station(sid):
    require_auth(["StoreManager"])
    st = must_get(stations, sid, "ERR_STATION_NOT_FOUND")
    st["status"] = "CLOSED"
    touch(st)
    return respond_object(serialize(st))


# ===========================================================================
# GROOMING APPOINTMENTS
# ===========================================================================
@app.route("/grooming-appointments", methods=["POST"])
def create_appointment():
    uid, role = require_auth(["Customer"])
    body = get_body()
    customer_id = body.get("customer_id")
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    must_get(customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    station_id = body.get("grooming_station_id")
    st = must_get(stations, station_id, "ERR_STATION_NOT_FOUND")
    service_type = req_enum(body, "service_type", ("WING_TRIM", "NAIL_TRIM"))
    slot_start = parse_dt(body.get("slot_start"))
    slot_end = parse_dt(body.get("slot_end"))
    fee = req_int(body, "fee_cents")
    if not (slot_end > slot_start):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    # service offered / station open (PRD §3.6 narrative: before time conflict)
    if st["status"] != "OPEN" or service_type not in st["service_types"]:
        raise ApiError("ERR_SERVICE_NOT_OFFERED", 409)
    # station time conflict (half-open, no buffer; adjacency allowed)
    for a in appointments.values():
        if a["grooming_station_id"] != station_id or a["status"] == "CANCELLED":
            continue
        if slot_start < a["slot_end"] and a["slot_start"] < slot_end:
            raise ApiError("ERR_STATION_TIME_CONFLICT", 409)
    ap = new_common()
    ap.update({
        "customer_id": customer_id,
        "grooming_station_id": station_id,
        "service_type": service_type,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "fee_cents": fee,
        "status": "BOOKED",
    })
    appointments[ap["id"]] = ap
    return respond_object(serialize(ap), 201)


@app.route("/grooming-appointments", methods=["GET"])
def list_appointments():
    require_auth(ALL_ROLES)
    items = list(appointments.values())
    cf = request.args.get("customer_id")
    sf = request.args.get("grooming_station_id")
    if cf is not None:
        items = [a for a in items if a["customer_id"] == cf]
    if sf is not None:
        items = [a for a in items if a["grooming_station_id"] == sf]
    page, limit, offset, total = paginate(items)
    return respond_list(page, limit, offset, total)


@app.route("/grooming-appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    require_auth(ALL_ROLES)
    ap = must_get(appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    return respond_object(serialize(ap))


@app.route("/grooming-appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    require_auth(["AviaryStaff"])
    ap = must_get(appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    if ap["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409)
    cust = customers[ap["customer_id"]]
    if cust["wallet_credit_cents"] - ap["fee_cents"] < 0:
        raise ApiError("ERR_INSUFFICIENT_WALLET", 402)
    cust["wallet_credit_cents"] -= ap["fee_cents"]
    touch(cust)
    ap["status"] = "COMPLETED"
    touch(ap)
    return respond_object(serialize(ap))


@app.route("/grooming-appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    uid, role = require_auth(["Customer"])
    ap = must_get(appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    owner_check(ap, uid, role)
    if ap["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409)
    ap["status"] = "CANCELLED"
    touch(ap)
    return respond_object(serialize(ap))


@app.route("/grooming-appointments/<aid>/no-show", methods=["POST"])
def no_show_appointment(aid):
    require_auth(["AviaryStaff"])
    ap = must_get(appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    if ap["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if logical_clock < ap["slot_end"]:
        raise ApiError("ERR_INVALID_STATE", 409)
    ap["status"] = "NO_SHOW"
    touch(ap)
    return respond_object(serialize(ap))


# ===========================================================================
# FEED SUBSCRIPTIONS
# ===========================================================================
@app.route("/feed-subscriptions", methods=["POST"])
def create_subscription():
    uid, role = require_auth(["Customer"])
    body = get_body()
    customer_id = body.get("customer_id")
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    cust = must_get(customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    fresh_feed = body.get("fresh_feed", False)
    if not isinstance(fresh_feed, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    fresh_item = None
    if fresh_feed:
        fresh_item = must_get(inventory, body.get("fresh_item_id"), "ERR_INVENTORY_NOT_FOUND")
    tier = req_enum(body, "tier", ("STANDARD", "PREMIUM"))
    bird_count = req_int(body, "bird_count")
    if bird_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    # inventory (13) -> wallet (14) -> suspension (15)
    if fresh_feed and fresh_item["quantity_on_hand"] < bird_count:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409)
    charge = compute_subscription_charge(tier, bird_count, fresh_feed, cust["club_tier"])
    if cust["wallet_credit_cents"] - charge < 0:
        raise ApiError("ERR_INSUFFICIENT_WALLET", 402)
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409)
    # commit
    cust["wallet_credit_cents"] -= charge
    touch(cust)
    if fresh_feed:
        fresh_item["quantity_on_hand"] -= bird_count
        fresh_item["quantity_allocated"] += bird_count
        touch(fresh_item)
    sub = new_common()
    sub.update({
        "customer_id": customer_id,
        "tier": tier,
        "bird_count": bird_count,
        "fresh_feed": fresh_feed,
        "fresh_item_id": fresh_item["id"] if fresh_feed else None,
        "monthly_charge_cents": charge,
        "created_charge_cents": charge,
        "status": "ACTIVE",
    })
    subscriptions[sub["id"]] = sub
    return respond_object(serialize(sub), 201)


@app.route("/feed-subscriptions", methods=["GET"])
def list_subscriptions():
    require_auth(ALL_ROLES)
    items = list(subscriptions.values())
    cf = request.args.get("customer_id")
    ff = request.args.get("fresh_item_id")
    if cf is not None:
        items = [s for s in items if s["customer_id"] == cf]
    if ff is not None:
        items = [s for s in items if s["fresh_item_id"] == ff]
    page, limit, offset, total = paginate(items)
    return respond_list(page, limit, offset, total)


@app.route("/feed-subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    require_auth(ALL_ROLES)
    s = must_get(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    return respond_object(serialize(s))


@app.route("/feed-subscriptions/<sid>/pause", methods=["POST"])
def pause_subscription(sid):
    uid, role = require_auth(["Customer"])
    s = must_get(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    owner_check(s, uid, role)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409)
    s["status"] = "PAUSED"
    if s["fresh_feed"]:
        item = inventory[s["fresh_item_id"]]
        item["quantity_allocated"] = max(0, item["quantity_allocated"] - s["bird_count"])
        item["quantity_on_hand"] += s["bird_count"]
        touch(item)
    touch(s)
    return respond_object(serialize(s))


@app.route("/feed-subscriptions/<sid>/resume", methods=["POST"])
def resume_subscription(sid):
    uid, role = require_auth(["Customer"])
    s = must_get(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    owner_check(s, uid, role)
    if s["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if s["fresh_feed"]:
        item = inventory[s["fresh_item_id"]]
        if item["quantity_on_hand"] < s["bird_count"]:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409)
        item["quantity_on_hand"] -= s["bird_count"]
        item["quantity_allocated"] += s["bird_count"]
        touch(item)
    s["status"] = "ACTIVE"
    touch(s)
    return respond_object(serialize(s))


@app.route("/feed-subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = require_auth(["Customer"])
    body = get_body()
    s = must_get(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    owner_check(s, uid, role)
    if s["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    refund_wallet = body.get("refund_wallet", False)
    if not isinstance(refund_wallet, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    was_active = s["status"] == "ACTIVE"
    s["status"] = "CANCELLED"
    if refund_wallet and was_active:
        cust = customers[s["customer_id"]]
        cust["wallet_credit_cents"] += s["created_charge_cents"]
        touch(cust)
    if was_active and s["fresh_feed"]:
        item = inventory[s["fresh_item_id"]]
        item["quantity_allocated"] = max(0, item["quantity_allocated"] - s["bird_count"])
        item["quantity_on_hand"] += s["bird_count"]
        touch(item)
    touch(s)
    return respond_object(serialize(s))


# ===========================================================================
# INVENTORY ITEMS
# ===========================================================================
@app.route("/inventory-items", methods=["POST"])
def create_inventory():
    require_auth(["StoreManager"])
    body = get_body()
    sku = req_str(body, "sku")
    feed_kind = req_enum(body, "feed_kind", ("DRY", "FRESH"))
    qty = req_int(body, "quantity_on_hand")
    if qty < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    item = new_common()
    item.update({
        "sku": sku,
        "feed_kind": feed_kind,
        "quantity_on_hand": qty,
        "quantity_allocated": 0,
    })
    inventory[item["id"]] = item
    return respond_object(serialize(item), 201)


@app.route("/inventory-items", methods=["GET"])
def list_inventory():
    require_auth(ALL_ROLES)
    page, limit, offset, total = paginate(list(inventory.values()))
    return respond_list(page, limit, offset, total)


@app.route("/inventory-items/<iid>", methods=["GET"])
def get_inventory(iid):
    require_auth(ALL_ROLES)
    item = must_get(inventory, iid, "ERR_INVENTORY_NOT_FOUND")
    return respond_object(serialize(item))


@app.route("/inventory-items/<iid>/restock", methods=["POST"])
def restock_inventory(iid):
    require_auth(["StoreManager"])
    body = get_body()
    item = must_get(inventory, iid, "ERR_INVENTORY_NOT_FOUND")
    units = req_int(body, "units")
    if units < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    item["quantity_on_hand"] += units
    touch(item)
    return respond_object(serialize(item))


# ===========================================================================
# SPECIAL ORDERS
# ===========================================================================
def validate_line_items(line_items):
    if not isinstance(line_items, list):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    for line in line_items:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400)
        up = line.get("unit_price_cents")
        qty = line.get("quantity")
        tr = line.get("tax_rate")
        if isinstance(up, bool) or not isinstance(up, int):
            raise ApiError("ERR_INVALID_REQUEST", 400)
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise ApiError("ERR_INVALID_REQUEST", 400)
        if isinstance(tr, bool) or not isinstance(tr, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", 400)


@app.route("/special-orders", methods=["POST"])
def create_order():
    uid, role = require_auth(["Customer"])
    body = get_body()
    customer_id = body.get("customer_id")
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    cust = must_get(customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    cage_item_id = body.get("cage_item_id")
    item = must_get(inventory, cage_item_id, "ERR_INVENTORY_NOT_FOUND")
    build_qty = req_int(body, "build_qty")
    if build_qty < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    line_items = body.get("line_items")
    validate_line_items(line_items)
    # inventory (13) -> suspension (15)
    if item["quantity_on_hand"] < build_qty:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409)
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409)
    invoice = compute_invoice_total(line_items)
    item["quantity_on_hand"] -= build_qty
    item["quantity_allocated"] += build_qty
    touch(item)
    o = new_common()
    o.update({
        "customer_id": customer_id,
        "cage_item_id": cage_item_id,
        "build_qty": build_qty,
        "line_items": line_items,
        "invoice_total_cents": invoice,
        "payment_status": "UNPAID",
        "build_status": "QUEUED",
    })
    orders[o["id"]] = o
    return respond_object(serialize(o), 201)


@app.route("/special-orders", methods=["GET"])
def list_orders():
    require_auth(ALL_ROLES)
    items = list(orders.values())
    cf = request.args.get("customer_id")
    kf = request.args.get("cage_item_id")
    if cf is not None:
        items = [o for o in items if o["customer_id"] == cf]
    if kf is not None:
        items = [o for o in items if o["cage_item_id"] == kf]
    page, limit, offset, total = paginate(items)
    return respond_list(page, limit, offset, total)


@app.route("/special-orders/<oid>", methods=["GET"])
def get_order(oid):
    require_auth(ALL_ROLES)
    o = must_get(orders, oid, "ERR_ORDER_NOT_FOUND")
    return respond_object(serialize(o))


@app.route("/special-orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    uid, role = require_auth(["Customer"])
    o = must_get(orders, oid, "ERR_ORDER_NOT_FOUND")
    owner_check(o, uid, role)
    if o["payment_status"] != "UNPAID":
        raise ApiError("ERR_ORDER_ALREADY_PAID", 409)
    if o["build_status"] == "CANCELLED":
        raise ApiError("ERR_ORDER_CANCELLED", 409)
    cust = customers[o["customer_id"]]
    if cust["wallet_credit_cents"] < o["invoice_total_cents"]:
        raise ApiError("ERR_INSUFFICIENT_WALLET", 402)
    cust["wallet_credit_cents"] -= o["invoice_total_cents"]
    touch(cust)
    o["payment_status"] = "PAID"
    touch(o)
    return respond_object(serialize(o))


@app.route("/special-orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    require_auth(["StoreManager"])
    o = must_get(orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["payment_status"] != "PAID" or o["build_status"] != "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409)
    cust = customers[o["customer_id"]]
    cust["wallet_credit_cents"] += o["invoice_total_cents"]
    touch(cust)
    o["payment_status"] = "REFUNDED"
    touch(o)
    return respond_object(serialize(o))


@app.route("/special-orders/<oid>/start-build", methods=["POST"])
def start_build(oid):
    require_auth(["StoreManager"])
    o = must_get(orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["build_status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE", 409)
    o["build_status"] = "IN_BUILD"
    touch(o)
    return respond_object(serialize(o))


@app.route("/special-orders/<oid>/mark-built", methods=["POST"])
def mark_built(oid):
    require_auth(["StoreManager"])
    o = must_get(orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["build_status"] != "IN_BUILD":
        raise ApiError("ERR_INVALID_STATE", 409)
    o["build_status"] = "BUILT"
    touch(o)
    return respond_object(serialize(o))


@app.route("/special-orders/<oid>/deliver", methods=["POST"])
def deliver_order(oid):
    require_auth(["StoreManager"])
    o = must_get(orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["build_status"] != "BUILT":
        raise ApiError("ERR_INVALID_STATE", 409)
    if o["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_PAID", 409)
    o["build_status"] = "DELIVERED"
    touch(o)
    item = inventory.get(o["cage_item_id"])
    if item is not None:
        item["quantity_allocated"] = max(0, item["quantity_allocated"] - o["build_qty"])
        touch(item)
    return respond_object(serialize(o))


@app.route("/special-orders/<oid>/cancel-build", methods=["POST"])
def cancel_build(oid):
    require_auth(["StoreManager"])
    o = must_get(orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["build_status"] not in ("QUEUED", "IN_BUILD"):
        raise ApiError("ERR_INVALID_STATE", 409)
    o["build_status"] = "CANCELLED"
    touch(o)
    item = inventory.get(o["cage_item_id"])
    if item is not None:
        item["quantity_allocated"] = max(0, item["quantity_allocated"] - o["build_qty"])
        item["quantity_on_hand"] += o["build_qty"]
        touch(item)
    return respond_object(serialize(o))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
