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
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": CLOCK_DEFAULT}


def clock():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "species": {},
    "animals": {},
    "quarantine": {},
    "customers": {},
    "permits": {},
    "sales": {},
    "claims": {},
    "batches": {},
    "subscriptions": {},
    "shipments": {},
    "builds": {},
    "expos": {},
    "assignments": {},
    "recalls": {},
}

NF = {
    "species": "ERR_SPECIES_NOT_FOUND",
    "animals": "ERR_ANIMAL_NOT_FOUND",
    "quarantine": "ERR_QUARANTINE_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "sales": "ERR_SALE_NOT_FOUND",
    "claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
    "batches": "ERR_FEEDER_BATCH_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "builds": "ERR_HABITAT_BUILD_NOT_FOUND",
    "expos": "ERR_EXPO_NOT_FOUND",
    "assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "recalls": "ERR_RECALL_NOT_FOUND",
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


ROLES = {"StoreManager", "VetTech", "SalesAssociate", "Customer"}

# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
REG_SURCHARGE = {
    "NONE": Decimal("0.00"),
    "CLASS_I": Decimal("0.05"),
    "CLASS_II": Decimal("0.10"),
    "CLASS_III": Decimal("0.15"),
}
LOYALTY = {"STANDARD": Decimal("0.00"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
EXPO_DISCOUNT = Decimal("0.08")
SIZE_MULT = {"SMALL": Decimal("1.00"), "MEDIUM": Decimal("1.25"), "LARGE": Decimal("1.50")}
DEPOSIT_PCT = Decimal("0.30")
MIN_PASS_CHECKS = 2
INSTALL_BUFFER = timedelta(minutes=60)
PERMIT_RANK = {"CLASS_I": 1, "CLASS_II": 2, "CLASS_III": 3}

FEEDER_TYPES = {"CRICKET", "DUBIA", "MOUSE_PINKY", "MOUSE_ADULT", "RAT"}
FEEDER_SIZES = {"SMALL", "MEDIUM", "LARGE"}


def rhu(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


def err(error_id, status, message=""):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_real():
    return datetime.now(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    if not isinstance(value, str) or not value:
        raise ValueError("bad datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def rand_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def envelope(response_type, data, pagination=None):
    meta = {"api_request_id": rand_id(), "api_request_timestamp": iso(now_real())}
    if pagination:
        meta.update(pagination)
    return {"meta": meta, "response_type": response_type, "data": data}


def serialize(obj):
    if isinstance(obj, datetime):
        return iso(obj)
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    return obj


def ok(entity, code=200):
    return jsonify(envelope("object", serialize(entity))), code


def ok_empty(code=200):
    return jsonify(envelope("object", {})), code


def ok_list(items, limit, offset, total):
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return jsonify(envelope("array", [serialize(i) for i in items], pag)), 200


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid.strip() == "" or role is None or role.strip() == "":
        err("ERR_UNAUTHENTICATED", 401, "missing authentication headers")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "role not permitted")
    return uid, role


def check_owner(role, uid, owner_customer_id):
    if role == "Customer" and uid != owner_customer_id:
        err("ERR_UNAUTHORIZED", 403, "not owner")


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------
def new_entity(kind, fields):
    now = now_real()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    DB[kind][ent["id"]] = ent
    return ent


def touch(ent):
    ent["updated_at"] = now_real()
    ent["version"] += 1


def get_or_404(kind, ident):
    ent = DB[kind].get(ident)
    if ent is None:
        err(NF[kind], 404, "not found")
    return ent


def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def validation(msg="invalid"):
    err("ERR_VALIDATION", 400, msg)


def req_str(b, key):
    v = b.get(key)
    if not is_str(v):
        validation("field %s must be a string" % key)
    return v


def opt_str(b, key, default=None):
    if key not in b or b.get(key) is None:
        return default
    v = b.get(key)
    if not is_str(v):
        validation("field %s must be a string" % key)
    return v


def req_int(b, key, minimum=None):
    v = b.get(key)
    if not is_int(v):
        validation("field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        validation("field %s must be >= %s" % (key, minimum))
    return v


def req_num(b, key):
    v = b.get(key)
    if not is_num(v):
        validation("field %s must be a number" % key)
    return v


def req_enum(b, key, allowed):
    v = b.get(key)
    if not is_str(v) or v not in allowed:
        validation("field %s must be one of %s" % (key, sorted(allowed)))
    return v


def opt_enum(b, key, allowed, default):
    if key not in b or b.get(key) is None:
        return default
    return req_enum(b, key, allowed)


def opt_bool(b, key, default):
    if key not in b or b.get(key) is None:
        return default
    v = b.get(key)
    if not is_bool(v):
        validation("field %s must be a boolean" % key)
    return v


def req_dt(b, key):
    v = b.get(key)
    try:
        return parse_dt(v)
    except Exception:
        validation("field %s must be an ISO-8601 datetime" % key)


def opt_dt(b, key, default=None):
    if key not in b or b.get(key) is None:
        return default
    return req_dt(b, key)


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except Exception:
            err("ERR_INVALID_PAGINATION", 400, "limit must be an integer")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except Exception:
            err("ERR_INVALID_PAGINATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100 or offset < 0:
        err("ERR_INVALID_PAGINATION", 400, "pagination out of range")
    return limit, offset


def sort_seq(items):
    return sorted(items, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Species care-sheet projection
# ---------------------------------------------------------------------------
def care_sheet(sp):
    return {
        "care_temp_low_c": sp["care_temp_low_c"],
        "care_temp_high_c": sp["care_temp_high_c"],
        "care_humidity_low_pct": sp["care_humidity_low_pct"],
        "care_humidity_high_pct": sp["care_humidity_high_pct"],
        "feed_interval_days": sp["feed_interval_days"],
        "care_feeder_type": sp["care_feeder_type"],
    }


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def compute_sale_price(animal, species, customer, sold_at_expo, final):
    base = animal["list_price_cents"]
    surcharge = rhu(Decimal(base) * REG_SURCHARGE[species["permit_class"]])
    disc_pct = Decimal("0")
    if final:
        disc_pct += LOYALTY[customer["loyalty_tier"]]
    if sold_at_expo:
        disc_pct += EXPO_DISCOUNT
    discount = rhu(Decimal(base + surcharge) * disc_pct)
    gross = base + surcharge - discount
    return max(gross, animal["acquisition_cost_cents"])


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["StoreManager"])
    b = body()
    v = b.get("to_iso8601")
    try:
        dt = parse_dt(v)
    except Exception:
        validation("to_iso8601 must be an ISO-8601 datetime")
    CLOCK["now"] = dt
    return ok_empty(200)


# ===========================================================================
# SPECIES
# ===========================================================================
@app.route("/species", methods=["POST"])
def create_species():
    require(["StoreManager"])
    b = body()
    common_name = req_str(b, "common_name")
    scientific_name = req_str(b, "scientific_name")
    is_regulated = opt_bool(b, "is_regulated", False)
    permit_class = opt_enum(b, "permit_class", {"NONE", "CLASS_I", "CLASS_II", "CLASS_III"}, "NONE")
    if is_regulated and permit_class == "NONE":
        validation("regulated species requires a real permit_class")
    if not is_regulated and permit_class != "NONE":
        validation("non-regulated species must have permit_class NONE")
    min_quarantine_days = req_int(b, "min_quarantine_days", 0)
    warranty_days = req_int(b, "warranty_days", 0)
    care_temp_low_c = req_num(b, "care_temp_low_c")
    care_temp_high_c = req_num(b, "care_temp_high_c")
    care_humidity_low_pct = req_int(b, "care_humidity_low_pct")
    care_humidity_high_pct = req_int(b, "care_humidity_high_pct")
    feed_interval_days = req_int(b, "feed_interval_days")
    care_feeder_type = req_enum(b, "care_feeder_type", FEEDER_TYPES)
    sp = new_entity("species", {
        "common_name": common_name,
        "scientific_name": scientific_name,
        "is_regulated": is_regulated,
        "permit_class": permit_class,
        "min_quarantine_days": min_quarantine_days,
        "warranty_days": warranty_days,
        "care_temp_low_c": care_temp_low_c,
        "care_temp_high_c": care_temp_high_c,
        "care_humidity_low_pct": care_humidity_low_pct,
        "care_humidity_high_pct": care_humidity_high_pct,
        "feed_interval_days": feed_interval_days,
        "care_feeder_type": care_feeder_type,
    })
    return ok(sp, 201)


@app.route("/species/<sid>", methods=["GET"])
def get_species(sid):
    require(ROLES)
    return ok(get_or_404("species", sid))


@app.route("/species", methods=["GET"])
def list_species():
    require(ROLES)
    limit, offset = get_pagination()
    items = list(DB["species"].values())
    if "is_regulated" in request.args:
        want = request.args["is_regulated"].lower() == "true"
        items = [s for s in items if s["is_regulated"] == want]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/species/<sid>/care-sheet", methods=["GET"])
def get_care_sheet(sid):
    require(ROLES)
    sp = get_or_404("species", sid)
    return ok(care_sheet(sp))


# ===========================================================================
# ANIMALS
# ===========================================================================
@app.route("/animals", methods=["POST"])
def create_animal():
    uid, role = require(["StoreManager"])
    b = body()
    sid = b.get("species_id")
    if is_str(sid) and sid not in DB["species"]:
        err("ERR_SPECIES_NOT_FOUND", 404, "species not found")
    species_id = req_str(b, "species_id")
    if species_id not in DB["species"]:
        err("ERR_SPECIES_NOT_FOUND", 404, "species not found")
    morph = req_str(b, "morph")
    sex = opt_enum(b, "sex", {"MALE", "FEMALE", "UNKNOWN"}, "UNKNOWN")
    acquisition_cost_cents = req_int(b, "acquisition_cost_cents", 0)
    list_price_cents = req_int(b, "list_price_cents", 0)
    hatch_date = opt_dt(b, "hatch_date")
    a = new_entity("animals", {
        "species_id": species_id,
        "morph": morph,
        "sex": sex,
        "acquisition_cost_cents": acquisition_cost_cents,
        "list_price_cents": list_price_cents,
        "acquired_by_user_id": uid,
        "hatch_date": hatch_date,
        "health_status": "HEALTHY",
        "status": "INTAKE",
        "quarantine_record_id": None,
    })
    return ok(a, 201)


@app.route("/animals/<aid>", methods=["GET"])
def get_animal(aid):
    require(ROLES)
    return ok(get_or_404("animals", aid))


@app.route("/animals", methods=["GET"])
def list_animals():
    require(ROLES)
    limit, offset = get_pagination()
    items = list(DB["animals"].values())
    if "species_id" in request.args:
        items = [a for a in items if a["species_id"] == request.args["species_id"]]
    if "status" in request.args:
        items = [a for a in items if a["status"] == request.args["status"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/animals/<aid>/start-quarantine", methods=["POST"])
def start_quarantine(aid):
    uid, role = require(["VetTech"])
    a = get_or_404("animals", aid)
    if a["status"] != "INTAKE":
        err("ERR_INVALID_STATE", 409, "animal not in INTAKE")
    sp = DB["species"][a["species_id"]]
    start_at = clock()
    required_until = start_at + timedelta(days=sp["min_quarantine_days"])
    qr = new_entity("quarantine", {
        "animal_id": a["id"],
        "start_at": start_at,
        "required_until": required_until,
        "status": "OPEN",
        "health_checks": [],
        "passed_checks_count": 0,
    })
    a["status"] = "QUARANTINE"
    a["quarantine_record_id"] = qr["id"]
    touch(a)
    return ok(qr, 201)


@app.route("/animals/<aid>/mark-deceased", methods=["POST"])
def mark_deceased(aid):
    uid, role = require(["VetTech"])
    a = get_or_404("animals", aid)
    b = body()
    opt_str(b, "notes")
    if a["status"] not in ("QUARANTINE", "AVAILABLE"):
        err("ERR_INVALID_STATE", 409, "animal cannot be marked deceased from its current state")
    a["status"] = "DECEASED"
    a["health_status"] = "DECEASED"
    touch(a)
    qrid = a.get("quarantine_record_id")
    if qrid:
        qr = DB["quarantine"].get(qrid)
        if qr and qr["status"] == "OPEN":
            qr["status"] = "FAILED"
            touch(qr)
    return ok(a, 200)


@app.route("/animals/<aid>/quarantine-record", methods=["GET"])
def get_animal_qr(aid):
    require(ROLES)
    get_or_404("animals", aid)
    limit, offset = get_pagination()
    items = sort_seq([q for q in DB["quarantine"].values() if q["animal_id"] == aid])
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/quarantine-records/<qid>", methods=["GET"])
def get_qr(qid):
    require(ROLES)
    return ok(get_or_404("quarantine", qid))


@app.route("/quarantine-records/<qid>/health-checks", methods=["POST"])
def add_health_check(qid):
    uid, role = require(["VetTech"])
    qr = get_or_404("quarantine", qid)
    b = body()
    result = req_enum(b, "result", {"PASS", "FAIL", "TREAT"})
    weight_grams = None
    if "weight_grams" in b and b.get("weight_grams") is not None:
        weight_grams = req_num(b, "weight_grams")
    notes = opt_str(b, "notes")
    qr["health_checks"].append({
        "check_at": clock(),
        "result": result,
        "weight_grams": weight_grams,
        "vet_user_id": uid,
        "notes": notes,
    })
    qr["passed_checks_count"] = sum(1 for h in qr["health_checks"] if h["result"] == "PASS")
    touch(qr)
    return ok(qr, 201)


@app.route("/quarantine-records/<qid>/clear", methods=["POST"])
def clear_qr(qid):
    uid, role = require(["VetTech"])
    qr = get_or_404("quarantine", qid)
    if qr["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "quarantine record not OPEN")
    if clock() < qr["required_until"] or qr["passed_checks_count"] < MIN_PASS_CHECKS:
        err("ERR_QUARANTINE_NOT_COMPLETE", 409, "quarantine not complete")
    qr["status"] = "CLEARED"
    touch(qr)
    a = DB["animals"].get(qr["animal_id"])
    if a and a["status"] == "QUARANTINE":
        a["status"] = "AVAILABLE"
        touch(a)
    return ok(qr, 200)


# ===========================================================================
# CUSTOMERS / PERMITS
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    require(["SalesAssociate", "StoreManager"])
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    loyalty_tier = opt_enum(b, "loyalty_tier", {"STANDARD", "SILVER", "GOLD"}, "STANDARD")
    for c in DB["customers"].values():
        if c["email"] == email:
            validation("email must be unique")
    cust = new_entity("customers", {
        "full_name": full_name,
        "email": email,
        "loyalty_tier": loyalty_tier,
        "wallet_credit_cents": 0,
    })
    return ok(cust, 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    cust = get_or_404("customers", cid)
    check_owner(role, uid, cust["id"])
    return ok(cust)


@app.route("/customers/<cid>/permits", methods=["POST"])
def create_permit(cid):
    uid, role = require(["Customer", "SalesAssociate"])
    cust = get_or_404("customers", cid)
    check_owner(role, uid, cust["id"])
    b = body()
    permit_number = req_str(b, "permit_number")
    permit_class = req_enum(b, "permit_class", {"CLASS_I", "CLASS_II", "CLASS_III"})
    issued_date = req_dt(b, "issued_date")
    expiry_date = req_dt(b, "expiry_date")
    p = new_entity("permits", {
        "customer_id": cust["id"],
        "permit_number": permit_number,
        "permit_class": permit_class,
        "issued_date": issued_date,
        "expiry_date": expiry_date,
        "status": "PENDING_VERIFICATION",
        "verified_at": None,
        "verified_by_user_id": None,
    })
    return ok(p, 201)


@app.route("/customers/<cid>/permits", methods=["GET"])
def list_customer_permits(cid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    cust = get_or_404("customers", cid)
    check_owner(role, uid, cust["id"])
    limit, offset = get_pagination()
    items = sort_seq([p for p in DB["permits"].values() if p["customer_id"] == cid])
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/permits/<pid>", methods=["GET"])
def get_permit(pid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    p = get_or_404("permits", pid)
    check_owner(role, uid, p["customer_id"])
    return ok(p)


@app.route("/permits/<pid>/verify", methods=["POST"])
def verify_permit(pid):
    uid, role = require(["StoreManager"])
    p = get_or_404("permits", pid)
    if p["status"] != "PENDING_VERIFICATION":
        err("ERR_INVALID_STATE", 409, "permit not pending verification")
    if clock() >= p["expiry_date"]:
        err("ERR_PERMIT_EXPIRED", 422, "permit already expired")
    p["status"] = "VERIFIED"
    p["verified_at"] = clock()
    p["verified_by_user_id"] = uid
    touch(p)
    return ok(p)


@app.route("/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    uid, role = require(["StoreManager"])
    p = get_or_404("permits", pid)
    if p["status"] != "VERIFIED":
        err("ERR_INVALID_STATE", 409, "permit not verified")
    p["status"] = "REVOKED"
    touch(p)
    for sale in DB["sales"].values():
        if sale["status"] == "CONFIRMED" and sale.get("permit_id") == pid:
            animal = DB["animals"].get(sale["animal_id"])
            species = DB["species"].get(animal["species_id"]) if animal else None
            if species and species["is_regulated"]:
                sale["status"] = "VOIDED"
                touch(sale)
                if animal and animal["status"] == "RESERVED":
                    animal["status"] = "AVAILABLE"
                    touch(animal)
    return ok(p)


# ===========================================================================
# SALES
# ===========================================================================
@app.route("/sales", methods=["POST"])
def create_sale():
    uid, role = require(["SalesAssociate"])
    b = body()
    aid = b.get("animal_id")
    if is_str(aid) and aid not in DB["animals"]:
        err("ERR_ANIMAL_NOT_FOUND", 404, "animal not found")
    cid = b.get("customer_id")
    if is_str(cid) and cid not in DB["customers"]:
        err("ERR_CUSTOMER_NOT_FOUND", 404, "customer not found")
    pid = b.get("permit_id")
    if is_str(pid) and pid not in DB["permits"]:
        err("ERR_PERMIT_NOT_FOUND", 404, "permit not found")
    animal_id = req_str(b, "animal_id")
    customer_id = req_str(b, "customer_id")
    permit_id = opt_str(b, "permit_id")
    sold_at_expo = opt_bool(b, "sold_at_expo", False)
    animal = get_or_404("animals", animal_id)
    customer = get_or_404("customers", customer_id)
    species = DB["species"][animal["species_id"]]
    provisional = compute_sale_price(animal, species, customer, sold_at_expo, final=False)
    sale = new_entity("sales", {
        "animal_id": animal_id,
        "customer_id": customer_id,
        "permit_id": permit_id,
        "sold_at_expo": sold_at_expo,
        "status": "DRAFT",
        "provisional_price_cents": provisional,
        "sale_price_cents": None,
        "confirmed_at": None,
        "warranty_expires_at": None,
        "created_by_user_id": uid,
    })
    return ok(sale, 201)


@app.route("/sales/<sid>", methods=["GET"])
def get_sale(sid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    sale = get_or_404("sales", sid)
    check_owner(role, uid, sale["customer_id"])
    return ok(sale)


@app.route("/sales", methods=["GET"])
def list_sales():
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    limit, offset = get_pagination()
    items = list(DB["sales"].values())
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == uid]
    for f in ("animal_id", "customer_id", "permit_id", "status"):
        if f in request.args:
            items = [s for s in items if s.get(f) == request.args[f]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/sales/<sid>/confirm", methods=["POST"])
def confirm_sale(sid):
    uid, role = require(["SalesAssociate"])
    sale = get_or_404("sales", sid)
    if sale["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "sale not in DRAFT")
    animal = DB["animals"].get(sale["animal_id"])
    if not animal or animal["status"] != "AVAILABLE":
        err("ERR_ANIMAL_NOT_AVAILABLE", 409, "animal not available")
    species = DB["species"][animal["species_id"]]
    customer = DB["customers"][sale["customer_id"]]
    if species["is_regulated"]:
        pid = sale.get("permit_id")
        if not pid:
            err("ERR_PERMIT_REQUIRED", 422, "permit required for regulated species")
        permit = DB["permits"].get(pid)
        if not permit:
            err("ERR_PERMIT_REQUIRED", 422, "permit required for regulated species")
        if permit["status"] != "VERIFIED" or \
                PERMIT_RANK.get(permit["permit_class"], 0) < PERMIT_RANK.get(species["permit_class"], 0):
            err("ERR_PERMIT_NOT_VERIFIED", 422, "permit not verified or insufficient class")
        if clock() >= permit["expiry_date"]:
            err("ERR_PERMIT_EXPIRED", 422, "permit expired")
    final_price = compute_sale_price(animal, species, customer, sale["sold_at_expo"], final=True)
    animal["status"] = "RESERVED"
    touch(animal)
    sale["status"] = "CONFIRMED"
    sale["sale_price_cents"] = final_price
    sale["confirmed_at"] = clock()
    sale["warranty_expires_at"] = clock() + timedelta(days=species["warranty_days"])
    touch(sale)
    return ok(sale)


@app.route("/sales/<sid>/fulfill", methods=["POST"])
def fulfill_sale(sid):
    uid, role = require(["SalesAssociate"])
    sale = get_or_404("sales", sid)
    if sale["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "sale not CONFIRMED")
    animal = DB["animals"].get(sale["animal_id"])
    if not animal or animal["status"] != "RESERVED":
        err("ERR_INVALID_STATE", 409, "animal not RESERVED")
    sale["status"] = "FULFILLED"
    touch(sale)
    animal["status"] = "SOLD"
    touch(animal)
    return ok(sale)


@app.route("/sales/<sid>/void", methods=["POST"])
def void_sale(sid):
    uid, role = require(["SalesAssociate"])
    sale = get_or_404("sales", sid)
    if sale["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "sale not CONFIRMED")
    sale["status"] = "VOIDED"
    touch(sale)
    animal = DB["animals"].get(sale["animal_id"])
    if animal and animal["status"] == "RESERVED":
        animal["status"] = "AVAILABLE"
        touch(animal)
    return ok(sale)


# ===========================================================================
# WARRANTY CLAIMS
# ===========================================================================
@app.route("/sales/<sid>/warranty-claims", methods=["POST"])
def create_claim(sid):
    uid, role = require(["Customer"])
    sale = get_or_404("sales", sid)
    check_owner(role, uid, sale["customer_id"])
    b = body()
    claim_type = req_enum(b, "claim_type", {"DOA", "EARLY_DEATH"})
    reason = req_str(b, "reason")
    if sale["status"] != "FULFILLED":
        err("ERR_INVALID_STATE", 409, "sale not FULFILLED")
    claim = new_entity("claims", {
        "sale_id": sale["id"],
        "claim_type": claim_type,
        "reason": reason,
        "status": "SUBMITTED",
        "resolution": None,
        "refund_cents": None,
        "replacement_animal_id": None,
        "approved_by_user_id": None,
    })
    return ok(claim, 201)


@app.route("/warranty-claims/<wid>", methods=["GET"])
def get_claim(wid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    claim = get_or_404("claims", wid)
    sale = DB["sales"].get(claim["sale_id"])
    check_owner(role, uid, sale["customer_id"] if sale else None)
    return ok(claim)


@app.route("/warranty-claims", methods=["GET"])
def list_claims():
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    limit, offset = get_pagination()
    items = list(DB["claims"].values())
    if role == "Customer":
        items = [c for c in items if DB["sales"].get(c["sale_id"], {}).get("customer_id") == uid]
    if "sale_id" in request.args:
        items = [c for c in items if c["sale_id"] == request.args["sale_id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


def compute_refund(claim, sale, species):
    if claim["claim_type"] == "DOA":
        return sale["sale_price_cents"]
    warranty_days = species["warranty_days"]
    if warranty_days <= 0:
        return 0
    delta = sale["warranty_expires_at"] - clock()
    secs = delta.total_seconds()
    remaining_days = 0 if secs <= 0 else math.ceil(secs / 86400.0)
    return rhu(Decimal(sale["sale_price_cents"]) * Decimal(remaining_days) / Decimal(warranty_days))


@app.route("/warranty-claims/<wid>/approve", methods=["POST"])
def approve_claim(wid):
    uid, role = require(["StoreManager"])
    claim = get_or_404("claims", wid)
    if claim["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "claim not SUBMITTED")
    sale = DB["sales"].get(claim["sale_id"])
    if not sale or sale["status"] != "FULFILLED":
        err("ERR_INVALID_STATE", 409, "sale not FULFILLED")
    animal = DB["animals"].get(sale["animal_id"])
    if animal and uid == animal.get("acquired_by_user_id"):
        err("ERR_SEGREGATION_OF_DUTIES", 403, "approver cannot be acquirer")
    if clock() > sale["warranty_expires_at"]:
        err("ERR_WARRANTY_EXPIRED", 422, "warranty expired")
    species = DB["species"][animal["species_id"]]
    claim["status"] = "APPROVED"
    claim["approved_by_user_id"] = uid
    claim["refund_cents"] = compute_refund(claim, sale, species)
    touch(claim)
    return ok(claim)


@app.route("/warranty-claims/<wid>/deny", methods=["POST"])
def deny_claim(wid):
    uid, role = require(["StoreManager"])
    claim = get_or_404("claims", wid)
    b = body()
    opt_str(b, "reason")
    if claim["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "claim not SUBMITTED")
    claim["status"] = "DENIED"
    touch(claim)
    return ok(claim)


@app.route("/warranty-claims/<wid>/resolve", methods=["POST"])
def resolve_claim(wid):
    uid, role = require(["StoreManager"])
    claim = get_or_404("claims", wid)
    b = body()
    resolution = req_enum(b, "resolution", {"REFUND", "REPLACEMENT", "CREDIT"})
    if claim["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "claim not APPROVED")
    sale = DB["sales"].get(claim["sale_id"])
    customer = DB["customers"].get(sale["customer_id"]) if sale else None
    if resolution == "REPLACEMENT":
        rep_id = b.get("replacement_animal_id")
        if not is_str(rep_id):
            validation("replacement_animal_id required for REPLACEMENT")
        rep = DB["animals"].get(rep_id)
        if rep is None:
            err("ERR_ANIMAL_NOT_FOUND", 404, "replacement animal not found")
        if rep["status"] != "AVAILABLE":
            err("ERR_ANIMAL_NOT_AVAILABLE", 409, "replacement animal not available")
        rep["status"] = "SOLD"
        touch(rep)
        claim["replacement_animal_id"] = rep_id
        sale["status"] = "CLOSED"
        touch(sale)
    elif resolution == "REFUND":
        sale["status"] = "REFUNDED"
        touch(sale)
        customer["wallet_credit_cents"] += claim["refund_cents"]
        touch(customer)
    else:  # CREDIT
        customer["wallet_credit_cents"] += claim["refund_cents"]
        touch(customer)
        sale["status"] = "CLOSED"
        touch(sale)
    claim["resolution"] = resolution
    claim["status"] = "RESOLVED"
    touch(claim)
    return ok(claim)


# ===========================================================================
# FEEDER BATCHES
# ===========================================================================
@app.route("/feeder-batches", methods=["POST"])
def create_batch():
    require(["StoreManager"])
    b = body()
    feeder_type = req_enum(b, "feeder_type", FEEDER_TYPES)
    size = req_enum(b, "size", FEEDER_SIZES)
    quantity_on_hand = req_int(b, "quantity_on_hand", 0)
    unit_price_cents = req_int(b, "unit_price_cents", 0)
    received_date = req_dt(b, "received_date")
    expiry_date = req_dt(b, "expiry_date")
    batch = new_entity("batches", {
        "feeder_type": feeder_type,
        "size": size,
        "quantity_on_hand": quantity_on_hand,
        "unit_price_cents": unit_price_cents,
        "received_date": received_date,
        "expiry_date": expiry_date,
        "status": "AVAILABLE",
    })
    return ok(batch, 201)


@app.route("/feeder-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require(["StoreManager", "SalesAssociate"])
    return ok(get_or_404("batches", bid))


@app.route("/feeder-batches", methods=["GET"])
def list_batches():
    require(["StoreManager", "SalesAssociate"])
    limit, offset = get_pagination()
    items = list(DB["batches"].values())
    if "feeder_type" in request.args:
        items = [x for x in items if x["feeder_type"] == request.args["feeder_type"]]
    if "status" in request.args:
        items = [x for x in items if x["status"] == request.args["status"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


# ===========================================================================
# FEEDER SUBSCRIPTIONS / SHIPMENTS
# ===========================================================================
@app.route("/feeder-subscriptions", methods=["POST"])
def create_subscription():
    uid, role = require(["Customer", "SalesAssociate"])
    b = body()
    cid = b.get("customer_id")
    if is_str(cid) and cid not in DB["customers"]:
        err("ERR_CUSTOMER_NOT_FOUND", 404, "customer not found")
    customer_id = req_str(b, "customer_id")
    customer = get_or_404("customers", customer_id)
    check_owner(role, uid, customer["id"])
    feeder_type = req_enum(b, "feeder_type", FEEDER_TYPES)
    size = req_enum(b, "size", FEEDER_SIZES)
    quantity_per_shipment = req_int(b, "quantity_per_shipment", 1)
    cadence_days = req_int(b, "cadence_days", 1)
    sub = new_entity("subscriptions", {
        "customer_id": customer_id,
        "feeder_type": feeder_type,
        "size": size,
        "quantity_per_shipment": quantity_per_shipment,
        "cadence_days": cadence_days,
        "next_ship_date": clock(),
        "status": "ACTIVE",
        "price_last_shipment_cents": None,
    })
    return ok(sub, 201)


@app.route("/feeder-subscriptions/<subid>", methods=["GET"])
def get_subscription(subid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    sub = get_or_404("subscriptions", subid)
    check_owner(role, uid, sub["customer_id"])
    return ok(sub)


@app.route("/feeder-subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    limit, offset = get_pagination()
    items = list(DB["subscriptions"].values())
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == uid]
    if "customer_id" in request.args:
        items = [s for s in items if s["customer_id"] == request.args["customer_id"]]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args["status"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/feeder-subscriptions/<subid>/pause", methods=["POST"])
def pause_subscription(subid):
    uid, role = require(["Customer"])
    sub = get_or_404("subscriptions", subid)
    check_owner(role, uid, sub["customer_id"])
    if sub["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "subscription not ACTIVE")
    sub["status"] = "PAUSED"
    touch(sub)
    return ok(sub)


@app.route("/feeder-subscriptions/<subid>/resume", methods=["POST"])
def resume_subscription(subid):
    uid, role = require(["Customer"])
    sub = get_or_404("subscriptions", subid)
    check_owner(role, uid, sub["customer_id"])
    if sub["status"] not in ("PAUSED", "HELD"):
        err("ERR_INVALID_STATE", 409, "subscription not PAUSED/HELD")
    sub["status"] = "ACTIVE"
    touch(sub)
    return ok(sub)


@app.route("/feeder-subscriptions/<subid>/cancel", methods=["POST"])
def cancel_subscription(subid):
    uid, role = require(["Customer"])
    sub = get_or_404("subscriptions", subid)
    check_owner(role, uid, sub["customer_id"])
    if sub["status"] not in ("ACTIVE", "PAUSED", "HELD"):
        err("ERR_INVALID_STATE", 409, "subscription not cancellable")
    sub["status"] = "CANCELLED"
    touch(sub)
    return ok(sub)


@app.route("/feeder-subscriptions/<subid>/shipments", methods=["POST"])
def create_shipment(subid):
    uid, role = require(["SalesAssociate"])
    sub = get_or_404("subscriptions", subid)
    qty = sub["quantity_per_shipment"]
    ft = sub["feeder_type"]
    sz = sub["size"]
    matching = [
        x for x in DB["batches"].values()
        if x["feeder_type"] == ft and x["size"] == sz
    ]
    # Eligible stock = matching batches that are neither recalled nor expired
    # (a DEPLETED batch is still eligible — it is neither recalled nor expired).
    eligible = [
        x for x in matching
        if x["status"] != "RECALLED" and x["expiry_date"] > clock()
    ]
    if not eligible:
        err("ERR_FEEDER_RECALLED", 409, "no eligible feeder stock")
    candidates = [
        x for x in eligible
        if x["status"] == "AVAILABLE" and x["quantity_on_hand"] > 0
    ]
    total_available = sum(x["quantity_on_hand"] for x in candidates)
    if total_available < qty:
        err("ERR_INSUFFICIENT_FEEDER_STOCK", 409, "insufficient feeder stock")
    candidates.sort(key=lambda x: (x["expiry_date"], x["_seq"]))
    remaining = qty
    allocations = []
    unit_mult = SIZE_MULT[sz]
    for batch in candidates:
        if remaining <= 0:
            break
        take = min(remaining, batch["quantity_on_hand"])
        unit_cost = rhu(Decimal(batch["unit_price_cents"]) * unit_mult)
        allocations.append({
            "batch_id": batch["id"],
            "quantity": take,
            "unit_cost_cents": unit_cost,
        })
        batch["quantity_on_hand"] -= take
        if batch["quantity_on_hand"] == 0:
            batch["status"] = "DEPLETED"
        touch(batch)
        remaining -= take
    shipment_cost = sum(line["quantity"] * line["unit_cost_cents"] for line in allocations)
    ship = new_entity("shipments", {
        "subscription_id": sub["id"],
        "feeder_type": ft,
        "size": sz,
        "quantity": qty,
        "allocations": allocations,
        "shipment_cost_cents": shipment_cost,
        "status": "SHIPPED",
        "reversed_reason": None,
    })
    sub["price_last_shipment_cents"] = shipment_cost
    sub["next_ship_date"] = sub["next_ship_date"] + timedelta(days=sub["cadence_days"])
    touch(sub)
    return ok(ship, 201)


@app.route("/feeder-subscriptions/<subid>/shipments", methods=["GET"])
def list_subscription_shipments(subid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    sub = get_or_404("subscriptions", subid)
    check_owner(role, uid, sub["customer_id"])
    limit, offset = get_pagination()
    items = sort_seq([s for s in DB["shipments"].values() if s["subscription_id"] == subid])
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/shipments/<shid>", methods=["GET"])
def get_shipment(shid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    ship = get_or_404("shipments", shid)
    if role == "Customer":
        sub = DB["subscriptions"].get(ship["subscription_id"])
        check_owner(role, uid, sub["customer_id"] if sub else None)
    return ok(ship)


@app.route("/shipments/<shid>/reverse", methods=["POST"])
def reverse_shipment(shid):
    uid, role = require(["SalesAssociate"])
    ship = get_or_404("shipments", shid)
    if ship["status"] != "SHIPPED":
        err("ERR_INVALID_STATE", 409, "shipment not SHIPPED")
    for line in ship["allocations"]:
        batch = DB["batches"].get(line["batch_id"])
        if batch is None:
            continue
        batch["quantity_on_hand"] += line["quantity"]
        if batch["status"] == "DEPLETED" and batch["quantity_on_hand"] > 0:
            batch["status"] = "AVAILABLE"
        touch(batch)
    ship["status"] = "REVERSED"
    ship["reversed_reason"] = "MANUAL"
    touch(ship)
    return ok(ship)


# ===========================================================================
# HABITAT BUILDS
# ===========================================================================
@app.route("/habitat-builds", methods=["POST"])
def create_build():
    uid, role = require(["Customer", "SalesAssociate"])
    b = body()
    cid = b.get("customer_id")
    if is_str(cid) and cid not in DB["customers"]:
        err("ERR_CUSTOMER_NOT_FOUND", 404, "customer not found")
    customer_id = req_str(b, "customer_id")
    customer = get_or_404("customers", customer_id)
    check_owner(role, uid, customer["id"])
    spec_summary = req_str(b, "spec_summary")
    quote_cents = req_int(b, "quote_cents", 0)
    build = new_entity("builds", {
        "customer_id": customer_id,
        "spec_summary": spec_summary,
        "quote_cents": quote_cents,
        "deposit_cents": None,
        "change_orders_total_cents": 0,
        "deposit_paid": False,
        "status": "QUOTED",
        "installer_id": None,
        "install_start_at": None,
        "install_end_at": None,
        "final_invoice_cents": None,
    })
    return ok(build, 201)


@app.route("/habitat-builds/<hid>", methods=["GET"])
def get_build(hid):
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    build = get_or_404("builds", hid)
    check_owner(role, uid, build["customer_id"])
    return ok(build)


@app.route("/habitat-builds", methods=["GET"])
def list_builds():
    uid, role = require(["StoreManager", "SalesAssociate", "Customer"])
    limit, offset = get_pagination()
    items = list(DB["builds"].values())
    if role == "Customer":
        items = [x for x in items if x["customer_id"] == uid]
    if "customer_id" in request.args:
        items = [x for x in items if x["customer_id"] == request.args["customer_id"]]
    if "status" in request.args:
        items = [x for x in items if x["status"] == request.args["status"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/habitat-builds/<hid>/pay-deposit", methods=["POST"])
def pay_deposit(hid):
    uid, role = require(["Customer"])
    build = get_or_404("builds", hid)
    check_owner(role, uid, build["customer_id"])
    if build["status"] != "QUOTED":
        err("ERR_INVALID_STATE", 409, "build not QUOTED")
    build["deposit_cents"] = rhu(Decimal(build["quote_cents"]) * DEPOSIT_PCT)
    build["deposit_paid"] = True
    build["status"] = "DEPOSIT_PAID"
    touch(build)
    return ok(build)


@app.route("/habitat-builds/<hid>/start", methods=["POST"])
def start_build(hid):
    uid, role = require(["SalesAssociate"])
    build = get_or_404("builds", hid)
    if build["status"] != "DEPOSIT_PAID":
        err("ERR_INVALID_STATE", 409, "build not DEPOSIT_PAID")
    build["status"] = "IN_PROGRESS"
    touch(build)
    return ok(build)


@app.route("/habitat-builds/<hid>/change-orders", methods=["POST"])
def change_order(hid):
    uid, role = require(["Customer"])
    build = get_or_404("builds", hid)
    check_owner(role, uid, build["customer_id"])
    b = body()
    delta_cents = req_int(b, "delta_cents")
    expected = req_int(b, "expected_habitat_build_version")
    if build["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "build not IN_PROGRESS")
    if expected != build["version"]:
        err("ERR_STALE_VERSION", 412, "stale habitat build version")
    build["change_orders_total_cents"] += delta_cents
    build["status"] = "CHANGE_REQUESTED"
    touch(build)
    return ok(build)


@app.route("/habitat-builds/<hid>/approve-change", methods=["POST"])
def approve_change(hid):
    uid, role = require(["SalesAssociate"])
    build = get_or_404("builds", hid)
    if build["status"] != "CHANGE_REQUESTED":
        err("ERR_INVALID_STATE", 409, "build not CHANGE_REQUESTED")
    build["status"] = "IN_PROGRESS"
    touch(build)
    return ok(build)


@app.route("/habitat-builds/<hid>/schedule-install", methods=["POST"])
def schedule_install(hid):
    uid, role = require(["SalesAssociate"])
    build = get_or_404("builds", hid)
    b = body()
    installer_id = req_str(b, "installer_id")
    install_start_at = req_dt(b, "install_start_at")
    install_end_at = req_dt(b, "install_end_at")
    for other in DB["builds"].values():
        if other["id"] == build["id"]:
            continue
        if other.get("installer_id") != installer_id:
            continue
        if other.get("install_start_at") is None or other.get("install_end_at") is None:
            continue
        os_, oe = other["install_start_at"], other["install_end_at"]
        ok_gap = (install_start_at >= oe + INSTALL_BUFFER) or (os_ >= install_end_at + INSTALL_BUFFER)
        if not ok_gap:
            err("ERR_INSTALL_BUFFER_CONFLICT", 409, "install buffer conflict")
    build["installer_id"] = installer_id
    build["install_start_at"] = install_start_at
    build["install_end_at"] = install_end_at
    touch(build)
    return ok(build)


@app.route("/habitat-builds/<hid>/deliver", methods=["POST"])
def deliver_build(hid):
    uid, role = require(["SalesAssociate"])
    build = get_or_404("builds", hid)
    if build["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "build not IN_PROGRESS")
    if build.get("install_start_at") is None:
        err("ERR_INVALID_STATE", 409, "install not scheduled")
    build["final_invoice_cents"] = (
        build["quote_cents"] + build["change_orders_total_cents"] - build["deposit_cents"]
    )
    build["status"] = "DELIVERED"
    touch(build)
    return ok(build)


@app.route("/habitat-builds/<hid>/cancel", methods=["POST"])
def cancel_build(hid):
    uid, role = require(["Customer"])
    build = get_or_404("builds", hid)
    check_owner(role, uid, build["customer_id"])
    if build["status"] not in ("QUOTED", "DEPOSIT_PAID", "IN_PROGRESS", "CHANGE_REQUESTED"):
        err("ERR_INVALID_STATE", 409, "build not cancellable")
    build["status"] = "CANCELLED"
    touch(build)
    return ok(build)


# ===========================================================================
# EXPOS / ASSIGNMENTS
# ===========================================================================
@app.route("/expos", methods=["POST"])
def create_expo():
    require(["StoreManager"])
    b = body()
    name = req_str(b, "name")
    venue = req_str(b, "venue")
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    venue_capacity = req_int(b, "venue_capacity", 0)
    if end_at <= start_at:
        validation("end_at must be after start_at")
    expo = new_entity("expos", {
        "name": name,
        "venue": venue,
        "start_at": start_at,
        "end_at": end_at,
        "venue_capacity": venue_capacity,
        "status": "SCHEDULED",
    })
    return ok(expo, 201)


@app.route("/expos/<eid>", methods=["GET"])
def get_expo(eid):
    require(["StoreManager", "SalesAssociate", "Customer"])
    return ok(get_or_404("expos", eid))


@app.route("/expos", methods=["GET"])
def list_expos():
    require(["StoreManager", "SalesAssociate", "Customer"])
    limit, offset = get_pagination()
    items = list(DB["expos"].values())
    if "status" in request.args:
        items = [x for x in items if x["status"] == request.args["status"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/expos/<eid>/open", methods=["POST"])
def open_expo(eid):
    require(["StoreManager"])
    expo = get_or_404("expos", eid)
    if expo["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "expo not SCHEDULED")
    expo["status"] = "OPEN"
    touch(expo)
    return ok(expo)


@app.route("/expos/<eid>/close", methods=["POST"])
def close_expo(eid):
    require(["StoreManager"])
    expo = get_or_404("expos", eid)
    if expo["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "expo not OPEN")
    expo["status"] = "CLOSED"
    touch(expo)
    for asg in DB["assignments"].values():
        if asg["expo_id"] == eid and asg["status"] == "ASSIGNED":
            asg["status"] = "ENDED"
            touch(asg)
    return ok(expo)


@app.route("/expos/<eid>/cancel", methods=["POST"])
def cancel_expo(eid):
    require(["StoreManager"])
    expo = get_or_404("expos", eid)
    if expo["status"] not in ("SCHEDULED", "OPEN"):
        err("ERR_INVALID_STATE", 409, "expo not cancellable")
    expo["status"] = "CANCELLED"
    touch(expo)
    for asg in DB["assignments"].values():
        if asg["expo_id"] == eid and asg["status"] == "ASSIGNED":
            asg["status"] = "CANCELLED"
            touch(asg)
    return ok(expo)


def windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.route("/expos/<eid>/assignments", methods=["POST"])
def create_assignment(eid):
    uid, role = require(["SalesAssociate"])
    expo = get_or_404("expos", eid)
    b = body()
    aid = b.get("animal_id")
    if is_str(aid) and aid not in DB["animals"]:
        err("ERR_ANIMAL_NOT_FOUND", 404, "animal not found")
    animal_id = req_str(b, "animal_id")
    animal = get_or_404("animals", animal_id)
    if animal["status"] != "AVAILABLE":
        err("ERR_ANIMAL_NOT_AVAILABLE", 409, "animal not available")
    for asg in DB["assignments"].values():
        if asg["animal_id"] == animal_id and asg["status"] == "ASSIGNED":
            other = DB["expos"].get(asg["expo_id"])
            if other and windows_overlap(expo["start_at"], expo["end_at"],
                                         other["start_at"], other["end_at"]):
                err("ERR_EXPO_OVERLAP", 409, "expo window overlap")
    assigned_count = sum(1 for a in DB["assignments"].values()
                         if a["expo_id"] == eid and a["status"] == "ASSIGNED")
    if assigned_count >= expo["venue_capacity"]:
        err("ERR_EXPO_CAPACITY_EXCEEDED", 409, "expo capacity exceeded")
    asg = new_entity("assignments", {
        "expo_id": eid,
        "animal_id": animal_id,
        "status": "ASSIGNED",
    })
    return ok(asg, 201)


@app.route("/expos/<eid>/assignments", methods=["GET"])
def list_expo_assignments(eid):
    require(["StoreManager", "SalesAssociate", "Customer"])
    get_or_404("expos", eid)
    limit, offset = get_pagination()
    items = sort_seq([a for a in DB["assignments"].values() if a["expo_id"] == eid])
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/expo-assignments/<asid>", methods=["GET"])
def get_assignment(asid):
    require(["StoreManager", "SalesAssociate", "Customer"])
    return ok(get_or_404("assignments", asid))


@app.route("/expo-assignments", methods=["GET"])
def list_assignments():
    require(["StoreManager", "SalesAssociate", "Customer"])
    limit, offset = get_pagination()
    items = list(DB["assignments"].values())
    if "animal_id" in request.args:
        items = [a for a in items if a["animal_id"] == request.args["animal_id"]]
    if "expo_id" in request.args:
        items = [a for a in items if a["expo_id"] == request.args["expo_id"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


# ===========================================================================
# RECALLS
# ===========================================================================
@app.route("/recalls", methods=["POST"])
def create_recall():
    uid, role = require(["StoreManager"])
    b = body()
    reason = req_str(b, "reason")
    target_feeder_type = req_enum(b, "target_feeder_type", FEEDER_TYPES)
    affected = b.get("affected_batch_ids")
    if not isinstance(affected, list) or not all(is_str(x) for x in affected):
        validation("affected_batch_ids must be a list of ids")
    batches = []
    for bid in affected:
        batch = DB["batches"].get(bid)
        if batch is None:
            err("ERR_FEEDER_BATCH_NOT_FOUND", 404, "feeder batch not found")
        batches.append(batch)
    for batch in batches:
        if batch["feeder_type"] != target_feeder_type:
            validation("batch does not match target_feeder_type")
    recall = new_entity("recalls", {
        "reason": reason,
        "target_feeder_type": target_feeder_type,
        "affected_batch_ids": list(affected),
        "opened_by_user_id": uid,
        "closed_by_user_id": None,
        "status": "OPEN",
    })
    affected_set = set(affected)
    for batch in batches:
        batch["status"] = "RECALLED"
        batch["quantity_on_hand"] = 0
        touch(batch)
    for ship in DB["shipments"].values():
        if ship["status"] != "SHIPPED":
            continue
        if any(line["batch_id"] in affected_set for line in ship["allocations"]):
            ship["status"] = "REVERSED"
            ship["reversed_reason"] = "RECALL"
            touch(ship)
            sub = DB["subscriptions"].get(ship["subscription_id"])
            if sub:
                if sub["status"] == "ACTIVE":
                    sub["status"] = "HELD"
                    touch(sub)
                customer = DB["customers"].get(sub["customer_id"])
                if customer:
                    customer["wallet_credit_cents"] += ship["shipment_cost_cents"]
                    touch(customer)
    return ok(recall, 201)


@app.route("/recalls/<rid>", methods=["GET"])
def get_recall(rid):
    require(["StoreManager", "SalesAssociate"])
    return ok(get_or_404("recalls", rid))


@app.route("/recalls", methods=["GET"])
def list_recalls():
    require(["StoreManager", "SalesAssociate"])
    limit, offset = get_pagination()
    items = list(DB["recalls"].values())
    if "status" in request.args:
        items = [x for x in items if x["status"] == request.args["status"]]
    items = sort_seq(items)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


@app.route("/recalls/<rid>/close", methods=["POST"])
def close_recall(rid):
    uid, role = require(["StoreManager"])
    recall = get_or_404("recalls", rid)
    if recall["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "recall not OPEN")
    if uid == recall["opened_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "closer must differ from opener")
    recall["status"] = "CLOSED"
    recall["closed_by_user_id"] = uid
    touch(recall)
    return ok(recall)


# ===========================================================================
# Error handlers
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(envelope("error", {"error_id": e.error_id, "message": e.message})), e.status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(envelope("error", {"error_id": "ERR_NOT_FOUND", "message": "not found"})), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(envelope("error", {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"})), 404


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return jsonify(envelope("error", {"error_id": "ERR_INTERNAL", "message": str(e)})), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
