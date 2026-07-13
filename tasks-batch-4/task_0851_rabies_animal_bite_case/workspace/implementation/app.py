"""Rabies & Animal-Bite Case Management API (Python + Flask, in-memory)."""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"IntakeOfficer", "Epidemiologist", "Veterinarian",
         "AnimalControlOfficer", "Owner", "HealthDeptAdmin"}

DOSE_COST_CENTS = 30000
RIG_COST_CENTS = 120000
STANDARD_DOSES = 4
QUARANTINE_DAYS = 10
CITATION_DUE_DAYS = 30
SURCHARGE_PCT = Decimal("0.085")
BASE_FINES = {
    "QUARANTINE_BREACH": 50000,
    "FAILURE_TO_SURRENDER": 75000,
    "NO_CURRENT_VACCINATION": 25025,
    "UNLICENSED_ANIMAL": 15075,
}
VIOLATION_CODES = set(BASE_FINES.keys())

HIGH_RISK_WILDLIFE = {"BAT", "RACCOON", "SKUNK", "FOX", "COYOTE"}
DOMESTIC_OBSERVABLE = {"DOG", "CAT", "FERRET"}

ANIMAL_SPECIES = {"DOG", "CAT", "FERRET", "BAT", "RACCOON", "SKUNK", "FOX",
                  "COYOTE", "LIVESTOCK", "OTHER"}
ANIMAL_CLASS = {"DOMESTIC", "WILD", "STRAY"}
VACC_STATUS = {"CURRENT", "EXPIRED", "UNKNOWN", "NONE"}
EXPOSURE_TYPE = {"BITE", "SCRATCH", "SALIVA_MUCOSAL"}
BODY_SITE = {"HEAD_NECK", "HAND", "ARM", "TORSO", "LEG", "FOOT"}
WOUND_CATEGORY = {"CATEGORY_I", "CATEGORY_II", "CATEGORY_III"}
FACILITY_TYPE = {"SHELTER", "VET_CLINIC"}
ORDER_TYPE = {"HOME_CONFINEMENT", "FACILITY"}
SPECIMEN_CONDITION = {"SATISFACTORY", "AUTOLYZED", "UNSATISFACTORY"}
TEST_METHOD = {"DFA", "RT_PCR"}
LAB_RESULT = {"POSITIVE", "NEGATIVE", "INDETERMINATE"}
OBSERVATION_OUTCOME = {"PENDING", "HEALTHY", "SYMPTOMATIC", "DECEASED"}
RESOLUTION = {"UPHELD", "DISMISSED"}
WILDLIFE_SPECIES = {"BAT", "RACCOON", "SKUNK", "FOX", "COYOTE", "OTHER"}
WILDLIFE_EXPOSURE_TYPE = {"DIRECT_CONTACT", "BITE", "INDOOR_FOUND_BAT"}
WILDLIFE_DISPOSITION = {"RELEASED", "EUTHANIZED", "ESCAPED", "TESTED"}

ALL_STAFF = ["IntakeOfficer", "Epidemiologist", "Veterinarian",
             "AnimalControlOfficer", "HealthDeptAdmin"]

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; nothing seeded)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.owners = {}
        self.animals = {}
        self.bite_cases = {}
        self.facilities = {}
        self.orders = {}
        self.specimens = {}
        self.peps = {}
        self.citations = {}
        self.regions = {}
        self.wildlife = {}
        self._seq = 0
        self._case_number_seq = 0
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_case_number(self):
        self._case_number_seq += 1
        return "RB-%06d" % self._case_number_seq


db = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_wall():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Invalid datetime: %s" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Invalid datetime: %s" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": fmt_dt(now_wall()),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, meta_extra=None, is_array=False):
    body = {
        "meta": make_meta(meta_extra),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted")


def require_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Body must be an object")
    return body


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def invalid(msg="Invalid request"):
    raise ApiError("ERR_INVALID_REQUEST", 422, msg)


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            invalid("Missing required field: %s" % f)


def check_enum(value, allowed, field):
    if value not in allowed:
        invalid("Illegal value for %s" % field)


def check_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("%s must be an integer" % field)
    if minimum is not None and value < minimum:
        invalid("%s must be >= %s" % (field, minimum))
    return value


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def base_entity():
    ts = now_wall()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_wall()
    entity["version"] = entity["version"] + 1


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def paginate(items):
    items = sorted(items, key=lambda e: e["_seq"])

    def parse_int_arg(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    limit = parse_int_arg("limit", 10)
    offset = parse_int_arg("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + len(page) < total
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": has_more}
    return [serialize(e) for e in page], meta


# ---------------------------------------------------------------------------
# Domain computations
# ---------------------------------------------------------------------------
def compute_risk(case, animal):
    wc = case["wound_category"]
    if wc == "CATEGORY_I":
        risk = "NONE"
    elif animal is None or animal.get("identified") is False or \
            animal.get("status") == "AT_LARGE":
        risk = "HIGH"
    elif animal.get("animal_class") == "WILD" and \
            animal.get("species") in HIGH_RISK_WILDLIFE:
        risk = "HIGH"
    elif animal.get("species") in DOMESTIC_OBSERVABLE:
        if animal.get("vaccination_status") == "CURRENT":
            risk = "LOW"
        else:
            risk = "MODERATE"
    else:
        risk = "MODERATE"
    mapping = {"NONE": "NOT_INDICATED", "LOW": "DEFER",
               "MODERATE": "INITIATE", "HIGH": "INITIATE"}
    return risk, mapping[risk]


def surcharged_line(base):
    return int((Decimal(base) * (Decimal(1) + SURCHARGE_PCT)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def compute_citation_fines(violations):
    base = sum(BASE_FINES[v] for v in violations)
    total = sum(surcharged_line(BASE_FINES[v]) for v in violations)
    return base, total


def compute_boarding(order, facility):
    if order["order_type"] == "HOME_CONFINEMENT":
        return 0
    daily = facility["daily_boarding_cents"]
    if order["status"] == "ACTIVE":
        days = QUARANTINE_DAYS
    else:
        elapsed = order["actual_release_date"] - order["start_date"]
        secs = elapsed.total_seconds()
        days = int(secs // 86400)
        if days < 1:
            days = 1
    return days * daily


def compute_pep_projection(indication, wound_category):
    rig = (indication == "INITIATE") and (wound_category == "CATEGORY_III")
    projected_doses = STANDARD_DOSES if indication == "INITIATE" else 0
    projected_cost = projected_doses * DOSE_COST_CENTS + \
        (RIG_COST_CENTS if rig else 0)
    return rig, projected_doses, projected_cost


def compute_pep_final(pep):
    doses = pep["doses_administered"]
    cost = doses * DOSE_COST_CENTS
    if pep["rig_indicated"] and doses >= 1:
        cost += RIG_COST_CENTS
    return cost


def recompute_owner(owner):
    total = 0
    delinquent = False
    for c in db.citations.values():
        if c["owner_id"] == owner["id"] and \
                c["status"] in ("ISSUED", "CONTESTED", "UPHELD"):
            total += c["total_fine_cents"]
            delinquent = True
    new_status = "DELINQUENT" if (total > 0 or delinquent) else "COMPLIANT"
    if owner["outstanding_fines_cents"] != total or \
            owner["compliance_status"] != new_status:
        owner["outstanding_fines_cents"] = total
        owner["compliance_status"] = new_status
        touch(owner)


def recompute_facility_occupancy(facility):
    if facility is None:
        return
    count = sum(1 for o in db.orders.values()
                if o["facility_id"] == facility["id"] and o["status"] == "ACTIVE")
    if facility["current_occupancy"] != count:
        facility["current_occupancy"] = count
        touch(facility)


def recompute_region_alert(region):
    count = region["confirmed_positive_count"]
    if count == 0:
        region["alert_status"] = "NORMAL"
    elif count < region["positive_threshold"]:
        region["alert_status"] = "ELEVATED"
    else:
        region["alert_status"] = "OUTBREAK"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(store, oid, err):
    ent = store.get(oid)
    if ent is None:
        raise ApiError(err, 404)
    return ent


# ===========================================================================
# OWNERS
# ===========================================================================
@app.route("/api/v1/owners", methods=["POST"])
def create_owner():
    _, role = authenticate()
    authorize(role, ["IntakeOfficer", "HealthDeptAdmin"])
    body = require_body()
    require_fields(body, ["full_name", "phone"])
    o = base_entity()
    o.update({
        "full_name": body["full_name"],
        "phone": body["phone"],
        "address": body.get("address"),
        "license_number": body.get("license_number"),
        "outstanding_fines_cents": 0,
        "compliance_status": "COMPLIANT",
    })
    db.owners[o["id"]] = o
    return success(serialize(o), 201)


@app.route("/api/v1/owners/<oid>", methods=["GET"])
def get_owner(oid):
    _, role = authenticate()
    authorize(role, ALL_STAFF)
    o = get_or_404(db.owners, oid, "ERR_OWNER_NOT_FOUND")
    return success(serialize(o), 200)


# ===========================================================================
# ANIMALS
# ===========================================================================
@app.route("/api/v1/animals", methods=["POST"])
def create_animal():
    _, role = authenticate()
    authorize(role, ["IntakeOfficer", "AnimalControlOfficer", "HealthDeptAdmin"])
    body = require_body()
    # body FK existence
    if body.get("owner_id") is not None:
        get_or_404(db.owners, body["owner_id"], "ERR_OWNER_NOT_FOUND")
    require_fields(body, ["species", "animal_class"])
    check_enum(body["species"], ANIMAL_SPECIES, "species")
    check_enum(body["animal_class"], ANIMAL_CLASS, "animal_class")
    identified = body.get("identified", True)
    if not isinstance(identified, bool):
        invalid("identified must be a boolean")
    vacc = body.get("vaccination_status", "UNKNOWN")
    check_enum(vacc, VACC_STATUS, "vaccination_status")
    expiry = None
    if body.get("rabies_vaccine_expiry") is not None:
        expiry = parse_dt(body["rabies_vaccine_expiry"], "rabies_vaccine_expiry")
    a = base_entity()
    a.update({
        "owner_id": body.get("owner_id"),
        "species": body["species"],
        "animal_class": body["animal_class"],
        "identified": identified,
        "vaccination_status": vacc,
        "rabies_vaccine_expiry": expiry,
        "status": "REPORTED",
        "disposition": "NONE",
        "control_status": "NONE",
    })
    db.animals[a["id"]] = a
    return success(serialize(a), 201)


@app.route("/api/v1/animals/<aid>", methods=["GET"])
def get_animal(aid):
    _, role = authenticate()
    authorize(role, ALL_STAFF)
    a = get_or_404(db.animals, aid, "ERR_ANIMAL_NOT_FOUND")
    return success(serialize(a), 200)


@app.route("/api/v1/animals", methods=["GET"])
def list_animals():
    _, role = authenticate()
    authorize(role, ALL_STAFF)
    items = list(db.animals.values())
    owner_id = request.args.get("owner_id")
    status = request.args.get("status")
    if owner_id is not None:
        items = [a for a in items if a["owner_id"] == owner_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    data, meta = paginate(items)
    return success(data, 200, meta_extra=meta, is_array=True)


@app.route("/api/v1/animals/<aid>/capture", methods=["POST"])
def capture_animal(aid):
    _, role = authenticate()
    authorize(role, ["AnimalControlOfficer", "HealthDeptAdmin"])
    a = get_or_404(db.animals, aid, "ERR_ANIMAL_NOT_FOUND")
    if a["status"] != "AT_LARGE":
        raise ApiError("ERR_INVALID_STATE", 409, "Animal not AT_LARGE")
    a["status"] = "CAPTURED"
    a["control_status"] = "CAPTURED"
    touch(a)
    return success(serialize(a), 200)


@app.route("/api/v1/animals/<aid>/disposition", methods=["POST"])
def animal_disposition(aid):
    _, role = authenticate()
    authorize(role, ["AnimalControlOfficer", "Veterinarian", "HealthDeptAdmin"])
    a = get_or_404(db.animals, aid, "ERR_ANIMAL_NOT_FOUND")
    body = require_body()
    disposition = body.get("disposition")
    escaped = body.get("escaped", False)
    if disposition is not None:
        check_enum(disposition, {"EUTHANIZED", "DECEASED"}, "disposition")
        if a["status"] not in ("REPORTED", "CAPTURED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Animal not in REPORTED/CAPTURED")
        a["status"] = disposition
        a["disposition"] = disposition
        touch(a)
        return success(serialize(a), 200)
    if escaped is True:
        if a["status"] != "REPORTED" or a.get("identified") is not False:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot mark at-large from current state")
        a["status"] = "AT_LARGE"
        touch(a)
        return success(serialize(a), 200)
    invalid("disposition or escaped required")


# ===========================================================================
# BITE CASES
# ===========================================================================
@app.route("/api/v1/bite-cases", methods=["POST"])
def create_bite_case():
    _, role = authenticate()
    authorize(role, ["IntakeOfficer", "HealthDeptAdmin"])
    body = require_body()
    animal = None
    if body.get("animal_id") is not None:
        animal = get_or_404(db.animals, body["animal_id"], "ERR_ANIMAL_NOT_FOUND")
    require_fields(body, ["region_code", "incident_datetime", "exposure_type",
                          "body_site", "wound_category", "victim_name", "victim_age"])
    check_enum(body["exposure_type"], EXPOSURE_TYPE, "exposure_type")
    check_enum(body["body_site"], BODY_SITE, "body_site")
    check_enum(body["wound_category"], WOUND_CATEGORY, "wound_category")
    check_int(body["victim_age"], "victim_age", minimum=0)
    incident_dt = parse_dt(body["incident_datetime"], "incident_datetime")
    prior_vacc = body.get("victim_prior_vaccinated", False)
    if not isinstance(prior_vacc, bool):
        invalid("victim_prior_vaccinated must be a boolean")

    c = base_entity()
    c.update({
        "case_number": db.next_case_number(),
        "region_code": body["region_code"],
        "incident_datetime": incident_dt,
        "exposure_type": body["exposure_type"],
        "body_site": body["body_site"],
        "wound_category": body["wound_category"],
        "victim_name": body["victim_name"],
        "victim_age": body["victim_age"],
        "victim_prior_vaccinated": prior_vacc,
        "animal_id": body.get("animal_id"),
        "status": "OPEN",
    })
    risk, pep_ind = compute_risk(c, animal)
    c["risk_level"] = risk
    c["pep_indication"] = pep_ind
    db.bite_cases[c["id"]] = c
    return success(serialize(c), 201)


@app.route("/api/v1/bite-cases/<cid>", methods=["GET"])
def get_bite_case(cid):
    _, role = authenticate()
    authorize(role, ALL_STAFF)
    c = get_or_404(db.bite_cases, cid, "ERR_CASE_NOT_FOUND")
    return success(serialize(c), 200)


@app.route("/api/v1/bite-cases", methods=["GET"])
def list_bite_cases():
    _, role = authenticate()
    authorize(role, ALL_STAFF)
    items = list(db.bite_cases.values())
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    region_code = request.args.get("region_code")
    if animal_id is not None:
        items = [c for c in items if c["animal_id"] == animal_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if region_code is not None:
        items = [c for c in items if c["region_code"] == region_code]
    data, meta = paginate(items)
    return success(data, 200, meta_extra=meta, is_array=True)


@app.route("/api/v1/bite-cases/<cid>/close", methods=["POST"])
def close_bite_case(cid):
    _, role = authenticate()
    authorize(role, ["Epidemiologist", "HealthDeptAdmin"])
    c = get_or_404(db.bite_cases, cid, "ERR_CASE_NOT_FOUND")
    if c["status"] not in ("CONFIRMED_RABID", "CLEARED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case not resolvable")
    c["status"] = "CLOSED"
    touch(c)
    return success(serialize(c), 200)


# ===========================================================================
# QUARANTINE FACILITIES
# ===========================================================================
@app.route("/api/v1/quarantine-facilities", methods=["POST"])
def create_facility():
    _, role = authenticate()
    authorize(role, ["HealthDeptAdmin"])
    body = require_body()
    require_fields(body, ["name", "facility_type", "capacity", "daily_boarding_cents"])
    check_enum(body["facility_type"], FACILITY_TYPE, "facility_type")
    check_int(body["capacity"], "capacity", minimum=1)
    check_int(body["daily_boarding_cents"], "daily_boarding_cents", minimum=0)
    f = base_entity()
    f.update({
        "name": body["name"],
        "facility_type": body["facility_type"],
        "capacity": body["capacity"],
        "daily_boarding_cents": body["daily_boarding_cents"],
        "current_occupancy": 0,
    })
    db.facilities[f["id"]] = f
    return success(serialize(f), 201)


@app.route("/api/v1/quarantine-facilities/<fid>", methods=["GET"])
def get_facility(fid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "AnimalControlOfficer", "HealthDeptAdmin"])
    f = get_or_404(db.facilities, fid, "ERR_FACILITY_NOT_FOUND")
    return success(serialize(f), 200)


# ===========================================================================
# QUARANTINE ORDERS
# ===========================================================================
def _windows_overlap(a_start, a_end, b_start, b_end):
    # half-open [start,end); adjacency (a_start == b_end or b_start == a_end) is OK
    return a_start < b_end and b_start < a_end


@app.route("/api/v1/bite-cases/<cid>/quarantine-orders", methods=["POST"])
def create_quarantine_order(cid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "AnimalControlOfficer", "HealthDeptAdmin"])
    c = get_or_404(db.bite_cases, cid, "ERR_CASE_NOT_FOUND")
    body = require_body()
    # body FK existence (priority 8) — for present FKs
    animal = None
    if body.get("animal_id") is not None:
        animal = get_or_404(db.animals, body["animal_id"], "ERR_ANIMAL_NOT_FOUND")
    facility = None
    if body.get("facility_id") is not None:
        facility = get_or_404(db.facilities, body["facility_id"], "ERR_FACILITY_NOT_FOUND")
    # well-formedness (priority 10)
    require_fields(body, ["expected_bite_case_version", "animal_id", "order_type"])
    check_int(body["expected_bite_case_version"], "expected_bite_case_version")
    check_enum(body["order_type"], ORDER_TYPE, "order_type")
    order_type = body["order_type"]
    start_date = db.clock
    if body.get("start_date") is not None:
        start_date = parse_dt(body["start_date"], "start_date")
    # facility shape (priority 13) — before OCC
    if order_type == "FACILITY" and facility is None:
        raise ApiError("ERR_FACILITY_REQUIRED", 422, "FACILITY order requires facility_id")
    if order_type == "HOME_CONFINEMENT" and body.get("facility_id") is not None:
        raise ApiError("ERR_FACILITY_REQUIRED", 422,
                       "HOME_CONFINEMENT must not supply facility_id")
    # OCC (priority 15)
    if body["expected_bite_case_version"] != c["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412, "Stale case version")
    # state (priority 30)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Case not OPEN")
    if animal["status"] in ("DECEASED", "EUTHANIZED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Animal deceased/euthanized")
    scheduled_end = start_date + timedelta(days=QUARANTINE_DAYS)
    # animal quarantine overlap (priority 45)
    for o in db.orders.values():
        if o["status"] == "ACTIVE" and o["animal_id"] == animal["id"]:
            if _windows_overlap(start_date, scheduled_end,
                                o["start_date"], o["scheduled_end_date"]):
                raise ApiError("ERR_ANIMAL_QUARANTINE_OVERLAP", 409,
                               "Overlapping active quarantine for animal")
    # facility capacity (priority 50)
    if order_type == "FACILITY":
        events = []
        for o in db.orders.values():
            if o["status"] == "ACTIVE" and o["facility_id"] == facility["id"]:
                s = max(o["start_date"], start_date)
                e = min(o["scheduled_end_date"], scheduled_end)
                if s < e:
                    events.append((s, 1))
                    events.append((e, -1))
        events.sort(key=lambda x: (x[0], x[1]))
        run = 0
        mx = 0
        for _, d in events:
            run += d
            if run > mx:
                mx = run
        if mx + 1 > facility["capacity"]:
            raise ApiError("ERR_FACILITY_AT_CAPACITY", 409, "Facility at capacity")

    o = base_entity()
    o.update({
        "case_id": c["id"],
        "animal_id": animal["id"],
        "facility_id": facility["id"] if facility else None,
        "order_type": order_type,
        "start_date": start_date,
        "scheduled_end_date": scheduled_end,
        "actual_release_date": None,
        "observation_outcome": "PENDING",
        "status": "ACTIVE",
        "boarding_cost_cents": 0,
    })
    o["boarding_cost_cents"] = compute_boarding(o, facility)
    db.orders[o["id"]] = o
    # animal -> UNDER_OBSERVATION
    if animal["status"] in ("REPORTED", "CAPTURED"):
        animal["status"] = "UNDER_OBSERVATION"
        touch(animal)
    # facility occupancy
    if facility is not None:
        recompute_facility_occupancy(facility)
    # case -> OBSERVATION_PENDING + version bump (exactly +1)
    c["status"] = "OBSERVATION_PENDING"
    touch(c)
    return success(serialize(o), 201)


@app.route("/api/v1/quarantine-orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "AnimalControlOfficer", "Epidemiologist",
                     "HealthDeptAdmin"])
    o = get_or_404(db.orders, oid, "ERR_QUARANTINE_ORDER_NOT_FOUND")
    return success(serialize(o), 200)


@app.route("/api/v1/quarantine-orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, ["Veterinarian", "AnimalControlOfficer", "Epidemiologist",
                     "HealthDeptAdmin"])
    items = list(db.orders.values())
    for key in ("case_id", "animal_id", "facility_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    data, meta = paginate(items)
    return success(data, 200, meta_extra=meta, is_array=True)


@app.route("/api/v1/quarantine-orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "HealthDeptAdmin"])
    o = get_or_404(db.orders, oid, "ERR_QUARANTINE_ORDER_NOT_FOUND")
    body = require_body()
    outcome = body.get("observation_outcome")
    if outcome is not None:
        check_enum(outcome, OBSERVATION_OUTCOME, "observation_outcome")
    effective = outcome if outcome is not None else o["observation_outcome"]
    # safety (priority 20)
    if effective in ("SYMPTOMATIC", "DECEASED"):
        raise ApiError("ERR_ANIMAL_SYMPTOMATIC", 409, "Animal symptomatic/deceased")
    # state (priority 30)
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not ACTIVE")
    # temporal (priority 40)
    if db.clock < o["scheduled_end_date"]:
        raise ApiError("ERR_QUARANTINE_NOT_ELAPSED", 409, "Quarantine not elapsed")
    o["status"] = "COMPLETED"
    o["actual_release_date"] = db.clock
    o["observation_outcome"] = effective
    facility = db.facilities.get(o["facility_id"]) if o["facility_id"] else None
    o["boarding_cost_cents"] = compute_boarding(o, facility)
    touch(o)
    animal = db.animals.get(o["animal_id"])
    if animal is not None:
        animal["status"] = "RELEASED"
        animal["disposition"] = "RELEASED"
        touch(animal)
    case = db.bite_cases.get(o["case_id"])
    if case is not None and case["status"] == "OBSERVATION_PENDING":
        case["status"] = "CLEARED"
        touch(case)
    if facility is not None:
        recompute_facility_occupancy(facility)
    return success(serialize(o), 200)


@app.route("/api/v1/quarantine-orders/<oid>/breach", methods=["POST"])
def breach_order(oid):
    _, role = authenticate()
    authorize(role, ["AnimalControlOfficer", "HealthDeptAdmin"])
    o = get_or_404(db.orders, oid, "ERR_QUARANTINE_ORDER_NOT_FOUND")
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not ACTIVE")
    o["status"] = "BREACHED"
    o["actual_release_date"] = db.clock
    facility = db.facilities.get(o["facility_id"]) if o["facility_id"] else None
    o["boarding_cost_cents"] = compute_boarding(o, facility)
    touch(o)
    animal = db.animals.get(o["animal_id"])
    # auto-issue citation to the order's owner
    if animal is not None and animal.get("owner_id"):
        owner = db.owners.get(animal["owner_id"])
        if owner is not None:
            base, total = compute_citation_fines(["QUARANTINE_BREACH"])
            cit = base_entity()
            cit.update({
                "owner_id": owner["id"],
                "case_id": o["case_id"],
                "violations": ["QUARANTINE_BREACH"],
                "base_fine_cents": base,
                "total_fine_cents": total,
                "issued_date": db.clock,
                "due_date": db.clock + timedelta(days=CITATION_DUE_DAYS),
                "status": "ISSUED",
            })
            db.citations[cit["id"]] = cit
            recompute_owner(owner)
    # animal-control seizure linkage
    if animal is not None:
        animal["control_status"] = "DISPATCH_REQUESTED"
        touch(animal)
    if facility is not None:
        recompute_facility_occupancy(facility)
    return success(serialize(o), 200)


@app.route("/api/v1/quarantine-orders/<oid>/convert-to-specimen", methods=["POST"])
def convert_order(oid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "HealthDeptAdmin"])
    o = get_or_404(db.orders, oid, "ERR_QUARANTINE_ORDER_NOT_FOUND")
    body = require_body()
    require_fields(body, ["collected_datetime", "condition"])
    check_enum(body["condition"], SPECIMEN_CONDITION, "condition")
    collected = parse_dt(body["collected_datetime"], "collected_datetime")
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not ACTIVE")
    o["status"] = "CONVERTED_TO_SPECIMEN"
    o["actual_release_date"] = db.clock
    facility = db.facilities.get(o["facility_id"]) if o["facility_id"] else None
    o["boarding_cost_cents"] = compute_boarding(o, facility)
    touch(o)
    animal = db.animals.get(o["animal_id"])
    if animal is not None:
        animal["status"] = "DECEASED"
        animal["disposition"] = "DECEASED"
        touch(animal)
    case = db.bite_cases.get(o["case_id"])
    if case is not None and case["status"] == "OBSERVATION_PENDING":
        case["status"] = "LAB_PENDING"
        touch(case)
    # create specimen
    condition = body["condition"]
    spec = base_entity()
    spec.update({
        "case_id": o["case_id"],
        "animal_id": o["animal_id"],
        "collected_datetime": collected,
        "condition": condition,
        "test_method": None,
        "result": "PENDING",
        "reported_datetime": None,
        "status": "SUBMITTED" if condition == "SATISFACTORY" else "REJECTED",
    })
    db.specimens[spec["id"]] = spec
    if facility is not None:
        recompute_facility_occupancy(facility)
    return success(serialize(o), 200)


# ===========================================================================
# SPECIMENS
# ===========================================================================
@app.route("/api/v1/bite-cases/<cid>/specimens", methods=["POST"])
def create_specimen(cid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "HealthDeptAdmin"])
    c = get_or_404(db.bite_cases, cid, "ERR_CASE_NOT_FOUND")
    body = require_body()
    animal = None
    if body.get("animal_id") is not None:
        animal = get_or_404(db.animals, body["animal_id"], "ERR_ANIMAL_NOT_FOUND")
    require_fields(body, ["animal_id", "collected_datetime", "condition"])
    check_enum(body["condition"], SPECIMEN_CONDITION, "condition")
    collected = parse_dt(body["collected_datetime"], "collected_datetime")
    # animal must be deceased/euthanized (priority 22)
    if animal["status"] not in ("DECEASED", "EUTHANIZED"):
        raise ApiError("ERR_ANIMAL_NOT_DECEASED", 409, "Animal not deceased/euthanized")
    # case state (priority 30)
    if c["status"] not in ("OPEN", "LAB_PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case not OPEN")
    condition = body["condition"]
    spec = base_entity()
    spec.update({
        "case_id": c["id"],
        "animal_id": animal["id"],
        "collected_datetime": collected,
        "condition": condition,
        "test_method": None,
        "result": "PENDING",
        "reported_datetime": None,
        "status": "SUBMITTED" if condition == "SATISFACTORY" else "REJECTED",
    })
    db.specimens[spec["id"]] = spec
    if condition == "SATISFACTORY" and c["status"] == "OPEN":
        c["status"] = "LAB_PENDING"
        touch(c)
    return success(serialize(spec), 201)


@app.route("/api/v1/specimens/<sid>", methods=["GET"])
def get_specimen(sid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "Epidemiologist", "HealthDeptAdmin"])
    s = get_or_404(db.specimens, sid, "ERR_SPECIMEN_NOT_FOUND")
    return success(serialize(s), 200)


@app.route("/api/v1/specimens", methods=["GET"])
def list_specimens():
    _, role = authenticate()
    authorize(role, ["Veterinarian", "Epidemiologist", "HealthDeptAdmin"])
    items = list(db.specimens.values())
    for key in ("case_id", "animal_id"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s[key] == val]
    data, meta = paginate(items)
    return success(data, 200, meta_extra=meta, is_array=True)


@app.route("/api/v1/specimens/<sid>/report-result", methods=["POST"])
def report_result(sid):
    _, role = authenticate()
    authorize(role, ["Veterinarian", "HealthDeptAdmin"])
    s = get_or_404(db.specimens, sid, "ERR_SPECIMEN_NOT_FOUND")
    body = require_body()
    require_fields(body, ["test_method", "result"])
    check_enum(body["test_method"], TEST_METHOD, "test_method")
    check_enum(body["result"], LAB_RESULT, "result")
    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Specimen not SUBMITTED")
    result = body["result"]
    s["status"] = "RESULTED"
    s["result"] = result
    s["test_method"] = body["test_method"]
    s["reported_datetime"] = db.clock
    touch(s)
    case = db.bite_cases.get(s["case_id"])
    if result == "POSITIVE":
        if case is not None and case["status"] == "LAB_PENDING":
            case["status"] = "CONFIRMED_RABID"
            touch(case)
        # force non-terminal PEP recommendations
        for pep in db.peps.values():
            if pep["case_id"] == s["case_id"] and \
                    pep["status"] in ("NOT_INDICATED", "RECOMMENDED", "INITIATED"):
                pep["indication"] = "INITIATE"
                if pep["status"] == "NOT_INDICATED":
                    pep["status"] = "RECOMMENDED"
                rig, pdoses, pcost = compute_pep_projection(
                    "INITIATE", case["wound_category"] if case else "CATEGORY_I")
                pep["rig_indicated"] = rig
                pep["projected_doses"] = pdoses
                pep["projected_cost_cents"] = pcost
                pep["final_cost_cents"] = compute_pep_final(pep)
                touch(pep)
        # surveillance rollup
        if case is not None:
            for region in db.regions.values():
                if region["region_code"] == case["region_code"]:
                    region["confirmed_positive_count"] += 1
                    recompute_region_alert(region)
                    touch(region)
                    break
    elif result == "NEGATIVE":
        if case is not None and case["status"] == "LAB_PENDING":
            case["status"] = "CLEARED"
            touch(case)
    # INDETERMINATE: case stays LAB_PENDING
    return success(serialize(s), 200)


# ===========================================================================
# PEP RECOMMENDATIONS
# ===========================================================================
@app.route("/api/v1/bite-cases/<cid>/pep-recommendations", methods=["POST"])
def create_pep(cid):
    _, role = authenticate()
    authorize(role, ["Epidemiologist", "HealthDeptAdmin"])
    c = get_or_404(db.bite_cases, cid, "ERR_CASE_NOT_FOUND")
    body = require_body()
    require_fields(body, ["expected_bite_case_version"])
    check_int(body["expected_bite_case_version"], "expected_bite_case_version")
    if body["expected_bite_case_version"] != c["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412, "Stale case version")
    indication = c["pep_indication"]
    # supersede prior RECOMMENDED recommendation(s)
    for prior in db.peps.values():
        if prior["case_id"] == c["id"] and prior["status"] == "RECOMMENDED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    rig, pdoses, pcost = compute_pep_projection(indication, c["wound_category"])
    pep = base_entity()
    pep.update({
        "case_id": c["id"],
        "indication": indication,
        "rig_indicated": rig,
        "projected_doses": pdoses,
        "projected_cost_cents": pcost,
        "doses_administered": 0,
        "final_cost_cents": 0,
        "status": "NOT_INDICATED" if indication == "NOT_INDICATED" else "RECOMMENDED",
    })
    db.peps[pep["id"]] = pep
    # case version bump (exactly +1)
    touch(c)
    return success(serialize(pep), 201)


@app.route("/api/v1/bite-cases/<cid>/pep-recommendations", methods=["GET"])
def list_pep(cid):
    _, role = authenticate()
    authorize(role, ["Epidemiologist", "Veterinarian", "HealthDeptAdmin"])
    c = get_or_404(db.bite_cases, cid, "ERR_CASE_NOT_FOUND")
    items = [p for p in db.peps.values() if p["case_id"] == c["id"]]
    data, meta = paginate(items)
    return success(data, 200, meta_extra=meta, is_array=True)


@app.route("/api/v1/pep-recommendations/<pid>/administer-dose", methods=["POST"])
def administer_dose(pid):
    _, role = authenticate()
    authorize(role, ["Epidemiologist", "HealthDeptAdmin"])
    pep = get_or_404(db.peps, pid, "ERR_PEP_NOT_FOUND")
    if pep["status"] == "RECOMMENDED":
        if pep["indication"] not in ("INITIATE", "DEFER"):
            raise ApiError("ERR_INVALID_STATE", 409, "PEP not eligible")
        pep["doses_administered"] = 1
        pep["status"] = "INITIATED"
        if pep["projected_doses"] > 0 and \
                pep["doses_administered"] == pep["projected_doses"]:
            pep["status"] = "COMPLETED"
    elif pep["status"] == "INITIATED":
        if pep["doses_administered"] >= pep["projected_doses"]:
            raise ApiError("ERR_INVALID_STATE", 409, "No doses remaining")
        pep["doses_administered"] += 1
        if pep["doses_administered"] == pep["projected_doses"]:
            pep["status"] = "COMPLETED"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "PEP not in an eligible state")
    pep["final_cost_cents"] = compute_pep_final(pep)
    touch(pep)
    return success(serialize(pep), 200)


@app.route("/api/v1/pep-recommendations/<pid>/discontinue", methods=["POST"])
def discontinue_pep(pid):
    _, role = authenticate()
    authorize(role, ["Epidemiologist", "HealthDeptAdmin"])
    pep = get_or_404(db.peps, pid, "ERR_PEP_NOT_FOUND")
    # cross-entity clearance (priority 25) — before state check
    case = db.bite_cases.get(pep["case_id"])
    cleared = False
    if case is not None:
        animal = db.animals.get(case["animal_id"]) if case.get("animal_id") else None
        if animal is not None and animal["status"] == "RELEASED":
            cleared = True
        if not cleared:
            for s in db.specimens.values():
                if s["case_id"] == case["id"] and s["result"] == "NEGATIVE":
                    cleared = True
                    break
    if not cleared:
        raise ApiError("ERR_ANIMAL_NOT_CLEARED", 409, "Animal not cleared")
    # state (priority 30)
    if pep["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE", 409, "PEP not INITIATED")
    pep["status"] = "DISCONTINUED"
    pep["final_cost_cents"] = compute_pep_final(pep)
    touch(pep)
    return success(serialize(pep), 200)


# ===========================================================================
# CITATIONS
# ===========================================================================
@app.route("/api/v1/citations", methods=["POST"])
def create_citation():
    _, role = authenticate()
    authorize(role, ["AnimalControlOfficer", "HealthDeptAdmin"])
    body = require_body()
    owner = None
    if body.get("owner_id") is not None:
        owner = get_or_404(db.owners, body["owner_id"], "ERR_OWNER_NOT_FOUND")
    if body.get("case_id") is not None:
        get_or_404(db.bite_cases, body["case_id"], "ERR_CASE_NOT_FOUND")
    require_fields(body, ["owner_id", "case_id", "violations"])
    violations = body["violations"]
    if not isinstance(violations, list) or len(violations) == 0:
        invalid("violations must be a non-empty array")
    for v in violations:
        check_enum(v, VIOLATION_CODES, "violations")
    base, total = compute_citation_fines(violations)
    cit = base_entity()
    cit.update({
        "owner_id": body["owner_id"],
        "case_id": body["case_id"],
        "violations": list(violations),
        "base_fine_cents": base,
        "total_fine_cents": total,
        "issued_date": db.clock,
        "due_date": db.clock + timedelta(days=CITATION_DUE_DAYS),
        "status": "ISSUED",
    })
    db.citations[cit["id"]] = cit
    recompute_owner(owner)
    return success(serialize(cit), 201)


def _owner_can_access_citation(uid, role, cit):
    if role == "Owner":
        return cit["owner_id"] == uid
    return True


@app.route("/api/v1/citations/<cit_id>", methods=["GET"])
def get_citation(cit_id):
    uid, role = authenticate()
    authorize(role, ["Owner", "AnimalControlOfficer", "Epidemiologist",
                     "HealthDeptAdmin"])
    cit = get_or_404(db.citations, cit_id, "ERR_CITATION_NOT_FOUND")
    if not _owner_can_access_citation(uid, role, cit):
        raise ApiError("ERR_NOT_CITATION_OWNER", 403, "Not the citation owner")
    return success(serialize(cit), 200)


@app.route("/api/v1/citations", methods=["GET"])
def list_citations():
    uid, role = authenticate()
    authorize(role, ["Owner", "AnimalControlOfficer", "Epidemiologist",
                     "HealthDeptAdmin"])
    items = list(db.citations.values())
    if role == "Owner":
        items = [c for c in items if c["owner_id"] == uid]
    for key in ("owner_id", "case_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    data, meta = paginate(items)
    return success(data, 200, meta_extra=meta, is_array=True)


@app.route("/api/v1/citations/<cit_id>/contest", methods=["POST"])
def contest_citation(cit_id):
    uid, role = authenticate()
    authorize(role, ["Owner", "HealthDeptAdmin"])
    cit = get_or_404(db.citations, cit_id, "ERR_CITATION_NOT_FOUND")
    require_body()
    # state (priority 30) before ownership (priority 60)
    if cit["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Citation not ISSUED")
    if role == "Owner" and cit["owner_id"] != uid:
        raise ApiError("ERR_NOT_CITATION_OWNER", 403, "Not the citation owner")
    cit["status"] = "CONTESTED"
    touch(cit)
    owner = db.owners.get(cit["owner_id"])
    if owner is not None:
        recompute_owner(owner)
    return success(serialize(cit), 200)


@app.route("/api/v1/citations/<cit_id>/resolve", methods=["POST"])
def resolve_citation(cit_id):
    _, role = authenticate()
    authorize(role, ["Epidemiologist", "HealthDeptAdmin"])
    cit = get_or_404(db.citations, cit_id, "ERR_CITATION_NOT_FOUND")
    body = require_body()
    require_fields(body, ["resolution"])
    check_enum(body["resolution"], RESOLUTION, "resolution")
    if cit["status"] != "CONTESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Citation not CONTESTED")
    resolution = body["resolution"]
    cit["status"] = "UPHELD" if resolution == "UPHELD" else "DISMISSED"
    touch(cit)
    owner = db.owners.get(cit["owner_id"])
    if owner is not None:
        recompute_owner(owner)
    return success(serialize(cit), 200)


@app.route("/api/v1/citations/<cit_id>/pay", methods=["POST"])
def pay_citation(cit_id):
    uid, role = authenticate()
    authorize(role, ["Owner", "HealthDeptAdmin"])
    cit = get_or_404(db.citations, cit_id, "ERR_CITATION_NOT_FOUND")
    body = require_body()
    require_fields(body, ["payment_amount_cents"])
    check_int(body["payment_amount_cents"], "payment_amount_cents")
    # state (priority 30)
    if cit["status"] not in ("ISSUED", "UPHELD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Citation not payable")
    # ownership (priority 60)
    if role == "Owner" and cit["owner_id"] != uid:
        raise ApiError("ERR_NOT_CITATION_OWNER", 403, "Not the citation owner")
    # fiscal (priority 70)
    if body["payment_amount_cents"] != cit["total_fine_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422, "Payment amount mismatch")
    cit["status"] = "PAID"
    touch(cit)
    owner = db.owners.get(cit["owner_id"])
    if owner is not None:
        recompute_owner(owner)
    return success(serialize(cit), 200)


# ===========================================================================
# SURVEILLANCE REGIONS & WILDLIFE
# ===========================================================================
@app.route("/api/v1/surveillance-regions", methods=["POST"])
def create_region():
    _, role = authenticate()
    authorize(role, ["HealthDeptAdmin"])
    body = require_body()
    require_fields(body, ["region_code"])
    threshold = body.get("positive_threshold", 3)
    check_int(threshold, "positive_threshold", minimum=1)
    for r in db.regions.values():
        if r["region_code"] == body["region_code"]:
            raise ApiError("ERR_DUPLICATE_REGION_CODE", 409, "Duplicate region_code")
    r = base_entity()
    r.update({
        "region_code": body["region_code"],
        "positive_threshold": threshold,
        "confirmed_positive_count": 0,
        "wildlife_exposure_count": 0,
        "alert_status": "NORMAL",
    })
    db.regions[r["id"]] = r
    return success(serialize(r), 201)


@app.route("/api/v1/surveillance-regions/<rid>", methods=["GET"])
def get_region(rid):
    _, role = authenticate()
    authorize(role, ALL_STAFF)
    r = get_or_404(db.regions, rid, "ERR_REGION_NOT_FOUND")
    return success(serialize(r), 200)


@app.route("/api/v1/surveillance-regions/<rid>/wildlife-exposure-reports",
           methods=["POST"])
def create_wildlife_report(rid):
    _, role = authenticate()
    authorize(role, ["IntakeOfficer", "Epidemiologist", "HealthDeptAdmin"])
    r = get_or_404(db.regions, rid, "ERR_REGION_NOT_FOUND")
    body = require_body()
    require_fields(body, ["species", "exposure_datetime", "exposure_type"])
    check_enum(body["species"], WILDLIFE_SPECIES, "species")
    check_enum(body["exposure_type"], WILDLIFE_EXPOSURE_TYPE, "exposure_type")
    disposition = body.get("disposition", "ESCAPED")
    check_enum(disposition, WILDLIFE_DISPOSITION, "disposition")
    exposure_dt = parse_dt(body["exposure_datetime"], "exposure_datetime")
    rep = base_entity()
    rep.update({
        "region_id": r["id"],
        "species": body["species"],
        "exposure_datetime": exposure_dt,
        "exposure_type": body["exposure_type"],
        "disposition": disposition,
    })
    db.wildlife[rep["id"]] = rep
    r["wildlife_exposure_count"] += 1
    touch(r)
    return success(serialize(rep), 201)


@app.route("/api/v1/surveillance-regions/<rid>/wildlife-exposure-reports",
           methods=["GET"])
def list_wildlife_reports(rid):
    _, role = authenticate()
    authorize(role, ALL_STAFF)
    r = get_or_404(db.regions, rid, "ERR_REGION_NOT_FOUND")
    items = [w for w in db.wildlife.values() if w["region_id"] == r["id"]]
    data, meta = paginate(items)
    return success(data, 200, meta_extra=meta, is_array=True)


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/api/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, ["HealthDeptAdmin"])
    body = require_body()
    require_fields(body, ["to_iso8601"])
    db.clock = parse_dt(body["to_iso8601"], "to_iso8601")
    return success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
