"""Newborn Screening Program API — Python/Flask reference implementation.

All state is held in-memory (module-level dicts keyed by id). The store starts
empty on every boot; every entity is created by tests through the declared API.
"""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# =====================================================================
# In-memory store
# =====================================================================
facilities = {}
infants = {}
specimens = {}
screens = {}
recollection_orders = {}
follow_up_cases = {}
specialty_clinics = {}
referrals = {}
confirmatory_appointments = {}
assay_runs = {}

# Logical clock — startup default 2026-03-01T00:00:00Z, held until advanced.
CLOCK = {}


def _init_clock():
    dt = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    CLOCK["dt"] = dt
    CLOCK["str"] = fmt_dt(dt)


# =====================================================================
# Constants
# =====================================================================
ROLES = {"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator",
         "SpecialtyClinician", "ProgramAdmin"}

# specimen_acceptability / timeliness
REQUIRED_SPOTS = 4
MIN_COLLECTION_AGE_HOURS = 24
MAX_COLLECTION_AGE_HOURS = 48
TERM_WEEKS = 37
MAX_TRANSIT_HOURS = 96
MAX_TRANSIT_ONTIME_HOURS = 24
MAX_REPORT_TURNAROUND_HOURS = 120

# followup_priority_score weights
W_CRITICAL = 50
W_PRETERM = 20
W_LOWBIRTH = 15
W_CONFIRMED = 40
W_REPEAT_NORMAL = 30
PRETERM_WEEKS = 34
LOW_BIRTH_WEIGHT_GRAMS = 1500

# cchd
CCHD_FAIL_BELOW = 90
CCHD_PASS_AT = 95
CCHD_DIFF_MAX = 3

# windows / buffers
RECOLLECTION_WINDOW_DAYS = 30
REPEAT_WINDOW_DAYS = 30
ASSAY_BUFFER_MINUTES = 30


# =====================================================================
# Errors
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# =====================================================================
# Helpers: datetime / formatting
# =====================================================================
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime; raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value, places):
    """Round half up to given decimal places, return float."""
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


# =====================================================================
# Helpers: envelope
# =====================================================================
def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": now_iso()}


def serialize(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def obj_response(data, status=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), status


def entity_response(obj, status=200):
    return obj_response(serialize(obj), status)


def array_response(items, limit, offset, total, has_more, status=200):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = has_more
    body = {"meta": m, "response_type": "array",
            "data": [serialize(i) for i in items]}
    return jsonify(body), status


def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paged(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    return array_response(page, limit, offset, total, has_more)


# =====================================================================
# Helpers: common fields / mutation
# =====================================================================
def new_common():
    return {"id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1}


def touch(obj):
    obj["version"] += 1
    obj["updated_at"] = now_iso()


# =====================================================================
# Helpers: auth
# =====================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers.")
    return uid, role


def require_auth(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint.")
    return uid, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return body


# =====================================================================
# Helpers: field validation
# =====================================================================
def _type_ok(value, kind):
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "num":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "datetime":
        if not isinstance(value, str):
            return False
        try:
            parse_dt(value)
            return True
        except ValueError:
            return False
    return False


def require_fields(body, specs):
    """specs: list of (name, kind). Raise ERR_INVALID_REQUEST on missing/mistyped."""
    for name, kind in specs:
        if name not in body or body[name] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field '{name}'.")
        if not _type_ok(body[name], kind):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{name}' has the wrong type.")


def optional_type(body, name, kind):
    if name in body and body[name] is not None and not _type_ok(body[name], kind):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{name}' has the wrong type.")


def require_enum(body, name, allowed):
    if body.get(name) not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, f"Field '{name}' is not a valid value.")


# =====================================================================
# Business helpers
# =====================================================================
def recompute_disposition(screen):
    m = screen["metabolic_status"]
    h = screen["hearing_status"]
    c = screen["cchd_status"]
    if m == "PRESUMPTIVE_POSITIVE" or h == "REFER" or c == "FAIL":
        d = "FLAGGED"
    elif m == "REPORTED_NORMAL" and h == "PASS" and c == "PASS":
        d = "CLEARED"
    elif m == "CANCELLED":
        d = "CANCELLED"
    else:
        d = "PENDING"
    screen["overall_disposition"] = d


def compute_priority(infant, critical_flag_count, variant, outcome=None):
    preterm = 1 if infant["gestational_age_weeks"] < PRETERM_WEEKS else 0
    low = 1 if infant["birth_weight_grams"] < LOW_BIRTH_WEIGHT_GRAMS else 0
    base = W_CRITICAL * critical_flag_count + W_PRETERM * preterm + W_LOWBIRTH * low
    if variant == "INITIAL":
        return base
    confirmed = 1 if outcome == "CONFIRMED" else 0
    repeat_norm = 1 if outcome == "NORMAL" else 0
    return base + W_CONFIRMED * confirmed - W_REPEAT_NORMAL * repeat_norm


def open_follow_up_case(infant, screen, critical_flag_count):
    case = new_common()
    case.update({
        "infant_id": infant["id"],
        "screen_id": screen["id"],
        "case_type": "SHORT_TERM",
        "critical_flag_count": critical_flag_count,
        "repeat_count": 0,
        "opened_at_clock": CLOCK["str"],
        "_opened_dt": CLOCK["dt"],
        "priority_variant": "INITIAL",
        "priority_score": 0,
        "status": "OPEN",
    })
    case["priority_score"] = compute_priority(infant, critical_flag_count, "INITIAL")
    follow_up_cases[case["id"]] = case
    infant["open_case_count"] += 1
    infant["followup_status"] = "ACTIVE"
    touch(infant)
    return case


def has_open_case_for_screen(screen_id):
    for c in follow_up_cases.values():
        if c["screen_id"] == screen_id and c["status"] not in ("RESOLVED_NORMAL", "CLOSED"):
            return True
    return False


def dec_open_case_count(infant):
    infant["open_case_count"] -= 1
    if infant["open_case_count"] <= 0:
        infant["open_case_count"] = 0
        infant["followup_status"] = "CLEAR"
    touch(infant)


def refusal_cascade(infant):
    """Void all non-terminal specimens of the infant and unwind dependents."""
    non_terminal = ("COLLECTED", "RECEIVED", "SATISFACTORY", "IN_TESTING")
    for spec in list(specimens.values()):
        if spec["infant_id"] != infant["id"] or spec["status"] not in non_terminal:
            continue
        prev = spec["status"]
        spec["status"] = "VOIDED"
        touch(spec)
        # cancel any ORDERED recollection order for this specimen
        for ro in recollection_orders.values():
            if ro["specimen_id"] == spec["id"] and ro["status"] == "ORDERED":
                ro["status"] = "CANCELLED"
                touch(ro)
                infant["open_recollection_count"] -= 1
                touch(infant)
        # IN_TESTING void cancels the screen and closes its cases
        if prev == "IN_TESTING":
            for screen in screens.values():
                if screen["specimen_id"] != spec["id"]:
                    continue
                screen["metabolic_status"] = "CANCELLED"
                recompute_disposition(screen)
                touch(screen)
                for case in follow_up_cases.values():
                    if case["screen_id"] == screen["id"] and case["status"] in ("OPEN", "REPEAT_REQUESTED"):
                        case["status"] = "CLOSED"
                        touch(case)
                        dec_open_case_count(infant)


# =====================================================================
# Health
# =====================================================================
@app.get("/")
def health():
    return jsonify({"status": "ok"}), 200


# =====================================================================
# Logical clock
# =====================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    require_auth({"ProgramAdmin"})
    body = get_body()
    require_fields(body, [("to_iso8601", "datetime")])
    dt = parse_dt(body["to_iso8601"])
    CLOCK["dt"] = dt
    CLOCK["str"] = fmt_dt(dt)
    return obj_response({"current_utc": CLOCK["str"]}, 200)


# =====================================================================
# Facilities
# =====================================================================
@app.post("/nbs/facilities")
def create_facility():
    require_auth({"ProgramAdmin"})
    body = get_body()
    require_fields(body, [("name", "str"), ("facility_type", "str"), ("state_region", "str")])
    require_enum(body, "facility_type", {"HOSPITAL", "BIRTHING_CENTER", "LAB"})
    fac = new_common()
    fac.update({
        "name": body["name"],
        "facility_type": body["facility_type"],
        "state_region": body["state_region"],
        "total_booked_minutes": 0,
    })
    facilities[fac["id"]] = fac
    return entity_response(fac, 201)


@app.get("/nbs/facilities/<fid>")
def get_facility(fid):
    require_auth({"LabTechnician", "ProgramAdmin"})
    fac = facilities.get(fid)
    if fac is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND", 404, "Facility not found.")
    return entity_response(fac)


# =====================================================================
# Infants
# =====================================================================
@app.post("/nbs/infants")
def create_infant():
    uid, role = require_auth({"BirthFacilityUser", "ProgramAdmin"})
    body = get_body()
    facility_id = body.get("facility_id")
    # ownership (priority 3) before existence
    if role == "BirthFacilityUser" and isinstance(facility_id, str) and facility_id != uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Facility does not belong to the acting user.")
    # existence (priority 4)
    if isinstance(facility_id, str) and facility_id not in facilities:
        raise ApiError("ERR_FACILITY_NOT_FOUND", 404, "Facility not found.")
    # shape (priority 5)
    require_fields(body, [("facility_id", "str"), ("birth_datetime", "datetime"),
                          ("gestational_age_weeks", "int"), ("birth_weight_grams", "int"),
                          ("sex", "str")])
    optional_type(body, "multiple_birth", "bool")
    require_enum(body, "sex", {"M", "F", "U"})
    inf = new_common()
    inf.update({
        "facility_id": body["facility_id"],
        "birth_datetime": body["birth_datetime"],
        "_birth_dt": parse_dt(body["birth_datetime"]),
        "gestational_age_weeks": body["gestational_age_weeks"],
        "birth_weight_grams": body["birth_weight_grams"],
        "sex": body["sex"],
        "multiple_birth": bool(body.get("multiple_birth", False)),
        "consent_status": "PENDING",
        "current_specimen_id": None,
        "open_recollection_count": 0,
        "open_case_count": 0,
        "followup_status": "CLEAR",
    })
    infants[inf["id"]] = inf
    return entity_response(inf, 201)


@app.get("/nbs/infants/<iid>")
def get_infant(iid):
    require_auth({"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator", "ProgramAdmin"})
    inf = infants.get(iid)
    if inf is None:
        raise ApiError("ERR_INFANT_NOT_FOUND", 404, "Infant not found.")
    return entity_response(inf)


@app.get("/nbs/infants")
def list_infants():
    require_auth({"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator", "ProgramAdmin"})
    facility_id = request.args.get("facility_id")
    consent_status = request.args.get("consent_status")
    items = []
    for inf in infants.values():
        if facility_id is not None and inf["facility_id"] != facility_id:
            continue
        if consent_status is not None and inf["consent_status"] != consent_status:
            continue
        items.append(inf)
    return paged(items)


@app.post("/nbs/infants/<iid>/consent")
def record_consent(iid):
    uid, role = require_auth({"BirthFacilityUser"})
    body = get_body()
    # ownership (priority 3) before existence
    inf = infants.get(iid)
    if inf is not None and inf["facility_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Infant does not belong to the acting facility.")
    if inf is None:
        raise ApiError("ERR_INFANT_NOT_FOUND", 404, "Infant not found.")
    require_fields(body, [("decision", "str"), ("recorded_by", "str")])
    optional_type(body, "religious_exemption", "bool")
    require_enum(body, "decision", {"CONSENT", "REFUSAL"})
    if body["decision"] == "CONSENT":
        inf["consent_status"] = "CONSENTED"
        touch(inf)
    else:
        inf["consent_status"] = "REFUSED"
        touch(inf)
        refusal_cascade(inf)
    return entity_response(inf)


# =====================================================================
# Specimens
# =====================================================================
@app.post("/nbs/specimens")
def create_specimen():
    uid, role = require_auth({"BirthFacilityUser"})
    body = get_body()
    infant_id = body.get("infant_id")
    # ownership (priority 3)
    inf = infants.get(infant_id) if isinstance(infant_id, str) else None
    if inf is not None and inf["facility_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Infant does not belong to the acting facility.")
    # existence (priority 4)
    if isinstance(infant_id, str) and infant_id not in infants:
        raise ApiError("ERR_INFANT_NOT_FOUND", 404, "Infant not found.")
    # shape (priority 5)
    require_fields(body, [("infant_id", "str"), ("specimen_type", "str"),
                          ("collection_datetime", "datetime"),
                          ("expected_infant_version", "int")])
    require_enum(body, "specimen_type", {"INITIAL", "REPEAT"})
    inf = infants[infant_id]
    # consent safety (priority 7)
    if inf["consent_status"] == "REFUSED":
        raise ApiError("ERR_CONSENT_REFUSED", 409, "Infant consent has been refused.")
    # temporal (priority 10)
    collection_dt = parse_dt(body["collection_datetime"])
    if collection_dt < inf["_birth_dt"]:
        raise ApiError("ERR_COLLECTION_BEFORE_BIRTH", 422, "Collection precedes birth.")
    # OCC (priority 12)
    if body["expected_infant_version"] != inf["version"]:
        raise ApiError("ERR_STALE_INFANT_VERSION", 412, "Infant version is stale.")

    spec = new_common()
    age = rhu((collection_dt - inf["_birth_dt"]).total_seconds() / 3600.0, 2)
    spec.update({
        "infant_id": infant_id,
        "specimen_type": body["specimen_type"],
        "collection_datetime": body["collection_datetime"],
        "_collection_dt": collection_dt,
        "received_datetime": None,
        "reported_datetime": None,
        "blood_spot_count": None,
        "collection_age_hours": age,
        "transit_time_hours": None,
        "acceptability": None,
        "timeliness_provisional": None,
        "timeliness_final": None,
        "status": "COLLECTED",
    })
    specimens[spec["id"]] = spec
    inf["current_specimen_id"] = spec["id"]
    touch(inf)
    if spec["specimen_type"] == "REPEAT":
        for ro in recollection_orders.values():
            parent = specimens.get(ro["specimen_id"])
            if parent and parent["infant_id"] == infant_id and ro["status"] == "ORDERED":
                ro["status"] = "COLLECTED"
                touch(ro)
                inf["open_recollection_count"] -= 1
                touch(inf)
    return entity_response(spec, 201)


@app.get("/nbs/specimens/<sid>")
def get_specimen(sid):
    require_auth({"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator", "ProgramAdmin"})
    spec = specimens.get(sid)
    if spec is None:
        raise ApiError("ERR_SPECIMEN_NOT_FOUND", 404, "Specimen not found.")
    return entity_response(spec)


@app.get("/nbs/specimens")
def list_specimens():
    require_auth({"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator", "ProgramAdmin"})
    infant_id = request.args.get("infant_id")
    status = request.args.get("status")
    specimen_type = request.args.get("specimen_type")
    items = []
    for spec in specimens.values():
        if infant_id is not None and spec["infant_id"] != infant_id:
            continue
        if status is not None and spec["status"] != status:
            continue
        if specimen_type is not None and spec["specimen_type"] != specimen_type:
            continue
        items.append(spec)
    return paged(items)


@app.post("/nbs/specimens/<sid>/receive")
def receive_specimen(sid):
    require_auth({"LabTechnician"})
    body = get_body()
    # existence (priority 4)
    spec = specimens.get(sid)
    if spec is None:
        raise ApiError("ERR_SPECIMEN_NOT_FOUND", 404, "Specimen not found.")
    # shape (priority 5)
    require_fields(body, [("received_datetime", "datetime"), ("blood_spot_count", "int")])
    # state (priority 6)
    if spec["status"] in ("TESTED", "UNSATISFACTORY", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Specimen is already terminal.")
    if spec["status"] != "COLLECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Specimen is not awaiting receipt.")
    inf = infants[spec["infant_id"]]
    # consent safety (priority 7)
    if inf["consent_status"] == "REFUSED":
        raise ApiError("ERR_CONSENT_REFUSED", 409, "Infant consent has been refused.")
    # temporal (priority 10)
    received_dt = parse_dt(body["received_datetime"])
    if received_dt < spec["_collection_dt"]:
        raise ApiError("ERR_RECEIVED_BEFORE_COLLECTION", 422, "Receipt precedes collection.")

    spec["received_datetime"] = body["received_datetime"]
    spec["_received_dt"] = received_dt
    spec["blood_spot_count"] = body["blood_spot_count"]
    transit = rhu((received_dt - spec["_collection_dt"]).total_seconds() / 3600.0, 2)
    spec["transit_time_hours"] = transit

    # acceptability determination (first-match-wins, top to bottom)
    age = spec["collection_age_hours"]
    if spec["blood_spot_count"] < REQUIRED_SPOTS:
        acceptability = "UNSAT_QUANTITY"
    elif age < MIN_COLLECTION_AGE_HOURS and inf["gestational_age_weeks"] >= TERM_WEEKS:
        acceptability = "UNSAT_EARLY"
    elif transit > MAX_TRANSIT_HOURS:
        acceptability = "UNSAT_TRANSIT"
    else:
        acceptability = "SATISFACTORY"
    spec["acceptability"] = acceptability

    if acceptability == "SATISFACTORY":
        spec["status"] = "SATISFACTORY"
        on_time = (age >= MIN_COLLECTION_AGE_HOURS and age <= MAX_COLLECTION_AGE_HOURS
                   and transit <= MAX_TRANSIT_ONTIME_HOURS)
        spec["timeliness_provisional"] = "ON_TIME" if on_time else "LATE"
        touch(spec)
    else:
        spec["status"] = "UNSATISFACTORY"
        touch(spec)
        ro = new_common()
        ro.update({
            "specimen_id": spec["id"],
            "reason": acceptability,
            "deadline_datetime": fmt_dt(CLOCK["dt"] + timedelta(days=RECOLLECTION_WINDOW_DAYS)),
            "status": "ORDERED",
        })
        recollection_orders[ro["id"]] = ro
        inf["open_recollection_count"] += 1
        touch(inf)
    return entity_response(spec)


@app.get("/nbs/specimens/<sid>/recollection-orders")
def list_recollection_orders(sid):
    require_auth({"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator", "ProgramAdmin"})
    if sid not in specimens:
        raise ApiError("ERR_SPECIMEN_NOT_FOUND", 404, "Specimen not found.")
    items = [ro for ro in recollection_orders.values() if ro["specimen_id"] == sid]
    return paged(items)


# =====================================================================
# Screens
# =====================================================================
@app.post("/nbs/screens")
def create_screen():
    require_auth({"LabTechnician"})
    body = get_body()
    specimen_id = body.get("specimen_id")
    # existence (priority 4)
    if isinstance(specimen_id, str) and specimen_id not in specimens:
        raise ApiError("ERR_SPECIMEN_NOT_FOUND", 404, "Specimen not found.")
    # shape (priority 5)
    require_fields(body, [("specimen_id", "str")])
    spec = specimens[specimen_id]
    # state (priority 6)
    if spec["status"] != "SATISFACTORY":
        raise ApiError("ERR_SPECIMEN_NOT_SATISFACTORY", 409, "Specimen is not SATISFACTORY.")
    inf = infants[spec["infant_id"]]
    # consent safety (priority 7)
    if inf["consent_status"] == "REFUSED":
        raise ApiError("ERR_CONSENT_REFUSED", 409, "Infant consent has been refused.")

    screen = new_common()
    screen.update({
        "specimen_id": specimen_id,
        "metabolic_status": "PENDING",
        "hearing_status": "NOT_DONE",
        "cchd_status": "NOT_DONE",
        "spo2_right_hand": None,
        "spo2_foot": None,
        "critical_analyte_count": 0,
        "overall_disposition": "PENDING",
    })
    screens[screen["id"]] = screen
    spec["status"] = "IN_TESTING"
    touch(spec)
    return entity_response(screen, 201)


@app.get("/nbs/screens/<scid>")
def get_screen(scid):
    require_auth({"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator", "ProgramAdmin"})
    screen = screens.get(scid)
    if screen is None:
        raise ApiError("ERR_SCREEN_NOT_FOUND", 404, "Screen not found.")
    return entity_response(screen)


@app.get("/nbs/screens")
def list_screens():
    require_auth({"BirthFacilityUser", "LabTechnician", "FollowUpCoordinator", "ProgramAdmin"})
    specimen_id = request.args.get("specimen_id")
    items = [s for s in screens.values()
             if specimen_id is None or s["specimen_id"] == specimen_id]
    return paged(items)


@app.post("/nbs/screens/<scid>/report-metabolic")
def report_metabolic(scid):
    require_auth({"LabTechnician"})
    body = get_body()
    # existence (priority 4)
    screen = screens.get(scid)
    if screen is None:
        raise ApiError("ERR_SCREEN_NOT_FOUND", 404, "Screen not found.")
    # shape (priority 5)
    require_fields(body, [("metabolic_result", "str")])
    optional_type(body, "critical_analyte_count", "int")
    require_enum(body, "metabolic_result", {"NORMAL", "BORDERLINE", "PRESUMPTIVE_POSITIVE"})
    spec = specimens[screen["specimen_id"]]
    # state (priority 6)
    if screen["metabolic_status"] != "PENDING" or spec["status"] != "IN_TESTING":
        raise ApiError("ERR_INVALID_STATE", 409, "Metabolic result cannot be reported now.")

    result = body["metabolic_result"]
    inf = infants[spec["infant_id"]]
    # stamp reported time from the logical clock; specimen -> TESTED
    spec["reported_datetime"] = CLOCK["str"]
    spec["status"] = "TESTED"
    turnaround = (CLOCK["dt"] - inf["_birth_dt"]).total_seconds() / 3600.0
    spec["timeliness_final"] = "TIMELY" if turnaround <= MAX_REPORT_TURNAROUND_HOURS else "DELAYED"
    touch(spec)

    if result == "NORMAL":
        screen["metabolic_status"] = "REPORTED_NORMAL"
    elif result == "BORDERLINE":
        screen["metabolic_status"] = "BORDERLINE"
    else:
        screen["metabolic_status"] = "PRESUMPTIVE_POSITIVE"
        screen["critical_analyte_count"] = body.get("critical_analyte_count") or 0
    recompute_disposition(screen)
    touch(screen)

    if result == "PRESUMPTIVE_POSITIVE":
        open_follow_up_case(inf, screen, screen["critical_analyte_count"])

    # a REPEAT specimen reaching TESTED advances a REPEAT_REQUESTED case
    if spec["specimen_type"] == "REPEAT":
        for case in follow_up_cases.values():
            if case["infant_id"] == inf["id"] and case["status"] == "REPEAT_REQUESTED":
                case["status"] = "REPEAT_RECEIVED"
                touch(case)
    return entity_response(screen)


@app.post("/nbs/screens/<scid>/point-of-care")
def point_of_care(scid):
    uid, role = require_auth({"BirthFacilityUser"})
    body = get_body()
    # ownership (priority 3) before existence
    screen = screens.get(scid)
    if screen is not None:
        spec = specimens[screen["specimen_id"]]
        inf = infants[spec["infant_id"]]
        if inf["facility_id"] != uid:
            raise ApiError("ERR_NOT_OWNER", 403, "Screen does not belong to the acting facility.")
    # existence (priority 4)
    if screen is None:
        raise ApiError("ERR_SCREEN_NOT_FOUND", 404, "Screen not found.")
    # shape (priority 5)
    require_fields(body, [("component", "str")])
    require_enum(body, "component", {"HEARING", "CCHD"})
    component = body["component"]

    if component == "HEARING":
        require_fields(body, [("hearing_result", "str")])
        require_enum(body, "hearing_result", {"PASS", "REFER"})
        # state (priority 6)
        if screen["hearing_status"] != "NOT_DONE":
            raise ApiError("ERR_INVALID_STATE", 409, "Hearing already reported.")
        if body["hearing_result"] == "PASS":
            screen["hearing_status"] = "PASS"
            recompute_disposition(screen)
            touch(screen)
        else:
            screen["hearing_status"] = "REFER"
            recompute_disposition(screen)
            touch(screen)
            if not has_open_case_for_screen(screen["id"]):
                open_follow_up_case(inf, screen, 0)
    else:  # CCHD
        require_fields(body, [("spo2_right_hand", "int"), ("spo2_foot", "int")])
        # state (priority 6)
        if screen["cchd_status"] != "NOT_DONE":
            raise ApiError("ERR_INVALID_STATE", 409, "CCHD already reported.")
        rh = body["spo2_right_hand"]
        ft = body["spo2_foot"]
        screen["spo2_right_hand"] = rh
        screen["spo2_foot"] = ft
        lower = min(rh, ft)
        diff = abs(rh - ft)
        if lower < CCHD_FAIL_BELOW:
            result = "FAIL"
        elif lower >= CCHD_PASS_AT and diff <= CCHD_DIFF_MAX:
            result = "PASS"
        else:
            result = "RETEST"
        screen["cchd_status"] = result
        recompute_disposition(screen)
        touch(screen)
        if result == "FAIL" and not has_open_case_for_screen(screen["id"]):
            open_follow_up_case(inf, screen, 0)
    return entity_response(screen)


# =====================================================================
# Follow-up cases
# =====================================================================
@app.get("/nbs/follow-up-cases/<cid>")
def get_case(cid):
    require_auth({"FollowUpCoordinator", "LabTechnician", "ProgramAdmin"})
    case = follow_up_cases.get(cid)
    if case is None:
        raise ApiError("ERR_FOLLOWUP_CASE_NOT_FOUND", 404, "Follow-up case not found.")
    return entity_response(case)


@app.get("/nbs/follow-up-cases")
def list_cases():
    require_auth({"FollowUpCoordinator", "LabTechnician", "ProgramAdmin"})
    infant_id = request.args.get("infant_id")
    screen_id = request.args.get("screen_id")
    status = request.args.get("status")
    items = []
    for case in follow_up_cases.values():
        if infant_id is not None and case["infant_id"] != infant_id:
            continue
        if screen_id is not None and case["screen_id"] != screen_id:
            continue
        if status is not None and case["status"] != status:
            continue
        items.append(case)
    return paged(items)


@app.post("/nbs/follow-up-cases/<cid>/request-repeat")
def request_repeat(cid):
    require_auth({"FollowUpCoordinator"})
    body = get_body()
    # existence (priority 4)
    case = follow_up_cases.get(cid)
    if case is None:
        raise ApiError("ERR_FOLLOWUP_CASE_NOT_FOUND", 404, "Follow-up case not found.")
    optional_type(body, "note", "str")
    # state (priority 6) / duplication (priority 9)
    if case["status"] in ("RESOLVED_NORMAL", "CLOSED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Case is already terminal.")
    if case["status"] == "REPEAT_REQUESTED":
        raise ApiError("ERR_DUPLICATE_REPEAT_PENDING", 409, "A repeat is already pending.")
    if case["status"] not in ("OPEN", "REPEAT_RECEIVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case cannot accept a repeat request.")
    # temporal window (priority 10)
    deadline = case["_opened_dt"] + timedelta(days=REPEAT_WINDOW_DAYS)
    if CLOCK["dt"] > deadline:
        raise ApiError("ERR_REPEAT_WINDOW_EXPIRED", 409, "Repeat window has expired.")
    case["status"] = "REPEAT_REQUESTED"
    case["repeat_count"] += 1
    touch(case)
    return entity_response(case)


@app.post("/nbs/follow-up-cases/<cid>/resolve")
def resolve_case(cid):
    require_auth({"FollowUpCoordinator"})
    body = get_body()
    # existence (priority 4)
    case = follow_up_cases.get(cid)
    if case is None:
        raise ApiError("ERR_FOLLOWUP_CASE_NOT_FOUND", 404, "Follow-up case not found.")
    # shape (priority 5)
    require_fields(body, [("outcome", "str")])
    require_enum(body, "outcome", {"NORMAL", "CONFIRMED"})
    outcome = body["outcome"]
    # state (priority 6)
    if case["status"] in ("RESOLVED_NORMAL", "CLOSED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Case is already terminal.")
    if case["status"] not in ("OPEN", "REPEAT_RECEIVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case cannot be resolved now.")
    inf = infants[case["infant_id"]]
    # referential (priority 8)
    if outcome == "CONFIRMED":
        completed = any(r["follow_up_case_id"] == cid and r["status"] == "COMPLETED"
                        for r in referrals.values())
        if not completed:
            raise ApiError("ERR_REFERRALS_UNRESOLVED", 409, "No completed referral for the case.")

    case["priority_variant"] = "REVISED"
    case["priority_score"] = compute_priority(inf, case["critical_flag_count"], "REVISED", outcome)
    if outcome == "NORMAL":
        case["status"] = "RESOLVED_NORMAL"
        touch(case)
        dec_open_case_count(inf)
    else:  # CONFIRMED
        case["case_type"] = "LONG_TERM"
        case["status"] = "LONG_TERM_MONITORING"
        touch(case)
    return entity_response(case)


# =====================================================================
# Referrals
# =====================================================================
@app.post("/nbs/referrals")
def create_referral():
    require_auth({"FollowUpCoordinator"})
    body = get_body()
    case_id = body.get("follow_up_case_id")
    clinic_id = body.get("specialty_clinic_id")
    # existence (priority 4), left to right
    if isinstance(case_id, str) and case_id not in follow_up_cases:
        raise ApiError("ERR_FOLLOWUP_CASE_NOT_FOUND", 404, "Follow-up case not found.")
    if isinstance(clinic_id, str) and clinic_id not in specialty_clinics:
        raise ApiError("ERR_SPECIALTY_CLINIC_NOT_FOUND", 404, "Specialty clinic not found.")
    # shape (priority 5)
    require_fields(body, [("follow_up_case_id", "str"), ("specialty_clinic_id", "str"),
                          ("referral_reason", "str")])
    require_enum(body, "referral_reason", {"METABOLIC_GENETICS", "AUDIOLOGY", "CARDIOLOGY"})
    clinic = specialty_clinics[clinic_id]
    # referential (priority 8)
    if body["referral_reason"] != clinic["specialty"]:
        raise ApiError("ERR_CLINIC_SPECIALTY_MISMATCH", 422, "Referral reason does not match clinic specialty.")
    # duplication (priority 9)
    for r in referrals.values():
        if r["follow_up_case_id"] == case_id and r["status"] in ("REQUESTED", "SCHEDULED"):
            raise ApiError("ERR_DUPLICATE_OPEN_REFERRAL", 409, "Case already has an open referral.")

    ref = new_common()
    ref.update({
        "follow_up_case_id": case_id,
        "specialty_clinic_id": clinic_id,
        "referral_reason": body["referral_reason"],
        "status": "REQUESTED",
    })
    referrals[ref["id"]] = ref
    return entity_response(ref, 201)


@app.get("/nbs/referrals/<rid>")
def get_referral(rid):
    require_auth({"FollowUpCoordinator", "SpecialtyClinician", "ProgramAdmin"})
    ref = referrals.get(rid)
    if ref is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", 404, "Referral not found.")
    return entity_response(ref)


@app.get("/nbs/referrals")
def list_referrals():
    require_auth({"FollowUpCoordinator", "SpecialtyClinician", "ProgramAdmin"})
    case_id = request.args.get("follow_up_case_id")
    clinic_id = request.args.get("specialty_clinic_id")
    status = request.args.get("status")
    items = []
    for r in referrals.values():
        if case_id is not None and r["follow_up_case_id"] != case_id:
            continue
        if clinic_id is not None and r["specialty_clinic_id"] != clinic_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    return paged(items)


@app.post("/nbs/referrals/<rid>/resolve")
def resolve_referral(rid):
    require_auth({"FollowUpCoordinator"})
    body = get_body()
    # existence (priority 4)
    ref = referrals.get(rid)
    if ref is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", 404, "Referral not found.")
    # shape (priority 5)
    require_fields(body, [("outcome", "str")])
    require_enum(body, "outcome", {"COMPLETED", "NO_SHOW", "DECLINED"})
    outcome = body["outcome"]
    # state (priority 6)
    if ref["status"] in ("COMPLETED", "DECLINED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Referral is already terminal.")
    if outcome in ("COMPLETED", "NO_SHOW"):
        if ref["status"] != "SCHEDULED":
            raise ApiError("ERR_REFERRAL_NOT_SCHEDULED", 409, "Referral is not scheduled.")
    else:  # DECLINED
        if ref["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Referral cannot be declined now.")

    if outcome == "COMPLETED":
        # referential (priority 8)
        has_completed = any(a["referral_id"] == rid and a["status"] == "COMPLETED"
                            for a in confirmatory_appointments.values())
        if not has_completed:
            raise ApiError("ERR_APPOINTMENT_NOT_COMPLETED", 409, "No completed appointment for the referral.")
        ref["status"] = "COMPLETED"
        touch(ref)
    elif outcome == "NO_SHOW":
        ref["status"] = "NO_SHOW"
        touch(ref)
        for a in confirmatory_appointments.values():
            if a["referral_id"] == rid and a["status"] == "SCHEDULED":
                a["status"] = "NO_SHOW"
                touch(a)
    else:  # DECLINED
        ref["status"] = "DECLINED"
        touch(ref)
    return entity_response(ref)


# =====================================================================
# Specialty clinics
# =====================================================================
@app.post("/nbs/specialty-clinics")
def create_specialty_clinic():
    require_auth({"ProgramAdmin"})
    body = get_body()
    require_fields(body, [("name", "str"), ("specialty", "str"), ("concurrent_capacity", "int")])
    require_enum(body, "specialty", {"METABOLIC_GENETICS", "AUDIOLOGY", "CARDIOLOGY"})
    if body["concurrent_capacity"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "concurrent_capacity must be at least 1.")
    clinic = new_common()
    clinic.update({
        "name": body["name"],
        "specialty": body["specialty"],
        "concurrent_capacity": body["concurrent_capacity"],
    })
    specialty_clinics[clinic["id"]] = clinic
    return entity_response(clinic, 201)


# =====================================================================
# Confirmatory appointments
# =====================================================================
@app.post("/nbs/confirmatory-appointments")
def create_appointment():
    require_auth({"FollowUpCoordinator"})
    body = get_body()
    referral_id = body.get("referral_id")
    # existence (priority 4)
    if isinstance(referral_id, str) and referral_id not in referrals:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", 404, "Referral not found.")
    # shape (priority 5)
    require_fields(body, [("referral_id", "str"), ("start_datetime", "datetime"),
                          ("end_datetime", "datetime")])
    ref = referrals[referral_id]
    start_dt = parse_dt(body["start_datetime"])
    end_dt = parse_dt(body["end_datetime"])
    # temporal (priority 10)
    if not (end_dt > start_dt):
        raise ApiError("ERR_INTERVAL_END_BEFORE_START", 422, "end_datetime must be after start_datetime.")
    # capacity (priority 11)
    clinic_id = ref["specialty_clinic_id"]
    clinic = specialty_clinics[clinic_id]
    overlapping = 0
    for a in confirmatory_appointments.values():
        if a["specialty_clinic_id"] == clinic_id and a["status"] == "SCHEDULED":
            if a["_start_dt"] < end_dt and start_dt < a["_end_dt"]:
                overlapping += 1
    if overlapping >= clinic["concurrent_capacity"]:
        raise ApiError("ERR_CLINIC_CAPACITY_EXCEEDED", 409, "Clinic capacity exceeded.")

    appt = new_common()
    appt.update({
        "referral_id": referral_id,
        "specialty_clinic_id": clinic_id,
        "start_datetime": body["start_datetime"],
        "_start_dt": start_dt,
        "end_datetime": body["end_datetime"],
        "_end_dt": end_dt,
        "status": "SCHEDULED",
    })
    confirmatory_appointments[appt["id"]] = appt
    if ref["status"] in ("REQUESTED", "NO_SHOW"):
        ref["status"] = "SCHEDULED"
        touch(ref)
    return entity_response(appt, 201)


@app.get("/nbs/referrals/<rid>/confirmatory-appointments")
def list_appointments(rid):
    require_auth({"FollowUpCoordinator", "SpecialtyClinician", "ProgramAdmin"})
    if rid not in referrals:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", 404, "Referral not found.")
    items = [a for a in confirmatory_appointments.values() if a["referral_id"] == rid]
    return paged(items)


@app.post("/nbs/confirmatory-appointments/<aid>/complete")
def complete_appointment(aid):
    uid, role = require_auth({"SpecialtyClinician"})
    body = get_body()
    # ownership (priority 3) before existence
    appt = confirmatory_appointments.get(aid)
    if appt is not None and appt["specialty_clinic_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Appointment does not belong to the acting clinic.")
    # existence (priority 4)
    if appt is None:
        raise ApiError("ERR_APPOINTMENT_NOT_FOUND", 404, "Appointment not found.")
    optional_type(body, "attended", "bool")
    # state (priority 6)
    if appt["status"] in ("COMPLETED", "NO_SHOW"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Appointment is already terminal.")
    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment cannot be completed now.")
    appt["status"] = "COMPLETED"
    touch(appt)
    return entity_response(appt)


# =====================================================================
# Assay runs
# =====================================================================
@app.post("/nbs/assay-runs")
def create_assay_run():
    require_auth({"LabTechnician"})
    body = get_body()
    facility_id = body.get("facility_id")
    # existence (priority 4)
    if isinstance(facility_id, str) and facility_id not in facilities:
        raise ApiError("ERR_FACILITY_NOT_FOUND", 404, "Facility not found.")
    # shape (priority 5)
    require_fields(body, [("facility_id", "str"), ("instrument_code", "str"),
                          ("start_datetime", "datetime"), ("end_datetime", "datetime")])
    fac = facilities[facility_id]
    start_dt = parse_dt(body["start_datetime"])
    end_dt = parse_dt(body["end_datetime"])
    # temporal (priority 10)
    if not (end_dt > start_dt):
        raise ApiError("ERR_INTERVAL_END_BEFORE_START", 422, "end_datetime must be after start_datetime.")
    # instrument exclusivity + buffer (priority 11)
    buffer = timedelta(minutes=ASSAY_BUFFER_MINUTES)
    for r in assay_runs.values():
        if (r["facility_id"] == facility_id and r["instrument_code"] == body["instrument_code"]
                and r["status"] != "CANCELLED"):
            if r["_start_dt"] < end_dt + buffer and start_dt - buffer < r["_end_dt"]:
                raise ApiError("ERR_INSTRUMENT_BUSY", 409, "Instrument is busy within the buffer window.")

    duration = int((end_dt - start_dt).total_seconds() // 60)
    run = new_common()
    run.update({
        "facility_id": facility_id,
        "instrument_code": body["instrument_code"],
        "start_datetime": body["start_datetime"],
        "_start_dt": start_dt,
        "end_datetime": body["end_datetime"],
        "_end_dt": end_dt,
        "duration_minutes": duration,
        "status": "SCHEDULED",
    })
    assay_runs[run["id"]] = run
    fac["total_booked_minutes"] += duration
    touch(fac)
    return entity_response(run, 201)


@app.get("/nbs/assay-runs/<rid>")
def get_assay_run(rid):
    require_auth({"LabTechnician", "ProgramAdmin"})
    run = assay_runs.get(rid)
    if run is None:
        raise ApiError("ERR_ASSAY_RUN_NOT_FOUND", 404, "Assay run not found.")
    return entity_response(run)


@app.get("/nbs/assay-runs")
def list_assay_runs():
    require_auth({"LabTechnician", "ProgramAdmin"})
    facility_id = request.args.get("facility_id")
    instrument_code = request.args.get("instrument_code")
    status = request.args.get("status")
    items = []
    for r in assay_runs.values():
        if facility_id is not None and r["facility_id"] != facility_id:
            continue
        if instrument_code is not None and r["instrument_code"] != instrument_code:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    return paged(items)


@app.post("/nbs/assay-runs/<rid>/cancel")
def cancel_assay_run(rid):
    require_auth({"LabTechnician"})
    body = get_body()
    # existence (priority 4)
    run = assay_runs.get(rid)
    if run is None:
        raise ApiError("ERR_ASSAY_RUN_NOT_FOUND", 404, "Assay run not found.")
    optional_type(body, "reason", "str")
    # state (priority 6)
    if run["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Assay run is already cancelled.")
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assay run cannot be cancelled now.")
    run["status"] = "CANCELLED"
    touch(run)
    fac = facilities.get(run["facility_id"])
    if fac is not None:
        fac["total_booked_minutes"] -= run["duration_minutes"]
        touch(fac)
    return entity_response(run)


# =====================================================================
# Program timeliness summary
# =====================================================================
@app.get("/nbs/program/timeliness-summary")
def timeliness_summary():
    require_auth({"ProgramAdmin"})
    state_region = request.args.get("state_region")
    # group eligible specimens by facility
    by_facility = {}
    eligible_total = 0
    for spec in specimens.values():
        if spec["specimen_type"] != "INITIAL" or spec["timeliness_final"] is None:
            continue
        inf = infants.get(spec["infant_id"])
        if inf is None:
            continue
        fac = facilities.get(inf["facility_id"])
        if fac is None:
            continue
        if state_region is not None and fac["state_region"] != state_region:
            continue
        eligible_total += 1
        entry = by_facility.setdefault(fac["id"], {"timely": 0, "total": 0})
        entry["total"] += 1
        if spec["timeliness_final"] == "TIMELY":
            entry["timely"] += 1

    if not by_facility:
        program_rate = None
    else:
        rates = [rhu(100.0 * e["timely"] / e["total"], 1) for e in by_facility.values()]
        program_rate = rhu(sum(rates) / len(rates), 1)

    data = {
        "program_rate": program_rate,
        "facility_count": len(by_facility),
        "eligible_specimen_count": eligible_total,
    }
    return obj_response(data)


# =====================================================================
# Entrypoint
# =====================================================================
_init_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
