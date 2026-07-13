"""Vital Records Registration API — single-file Flask implementation.

In-memory storage only. Boots clean on every process start (per-test isolation).
All behavior traces to workspace/PRD.md.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock (§2.4). Defaults to 2026-03-01T00:00:00Z at every boot.
# ---------------------------------------------------------------------------
UTC = timezone.utc
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)}


def now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# In-memory stores (§ start empty every boot; no seeding).
# ---------------------------------------------------------------------------
DB = {
    "Facility": {},
    "Certifier": {},
    "VitalEvent": {},
    "MedicalCertification": {},
    "Amendment": {},
    "PaternityAcknowledgment": {},
    "CertifiedCopyRequest": {},
    "ApostilleRequest": {},
    "DelayedRegistrationPacket": {},
    "StatisticsReport": {},
}

NOT_FOUND = {
    "Facility": "ERR_FACILITY_NOT_FOUND",
    "Certifier": "ERR_CERTIFIER_NOT_FOUND",
    "VitalEvent": "ERR_VITAL_EVENT_NOT_FOUND",
    "MedicalCertification": "ERR_CERTIFICATION_NOT_FOUND",
    "Amendment": "ERR_AMENDMENT_NOT_FOUND",
    "PaternityAcknowledgment": "ERR_PATERNITY_NOT_FOUND",
    "CertifiedCopyRequest": "ERR_COPY_REQUEST_NOT_FOUND",
    "ApostilleRequest": "ERR_APOSTILLE_NOT_FOUND",
    "DelayedRegistrationPacket": "ERR_PACKET_NOT_FOUND",
    "StatisticsReport": "ERR_REPORT_NOT_FOUND",
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
ROLES = {"StateRegistrar", "FacilityFiler", "MedicalCertifier", "Applicant"}
FACILITY_TYPES = {"HOSPITAL", "FUNERAL_HOME", "BIRTHING_CENTER"}
CERTIFIER_TYPES = {"PHYSICIAN", "MEDICAL_EXAMINER", "CORONER"}
EVENT_TYPES = {"BIRTH", "DEATH", "FETAL_DEATH"}
SEXES = {"MALE", "FEMALE", "UNDETERMINED"}
MANNERS = {"NATURAL", "ACCIDENT", "SUICIDE", "HOMICIDE",
           "PENDING_INVESTIGATION", "UNDETERMINED"}
AMENDMENT_TYPES = {"DEMOGRAPHIC", "MEDICAL"}
RELATIONSHIPS = {"SELF", "PARENT", "CHILD", "SPOUSE", "SIBLING",
                 "LEGAL_GUARDIAN", "LEGAL_REPRESENTATIVE", "OTHER", "GENEALOGIST"}
CATEGORIES = {"STANDARD", "VETERAN", "INDIGENT"}
ID_DOC_TYPES = {"DRIVERS_LICENSE", "PASSPORT", "STATE_ID", "MILITARY_ID"}
APOSTILLE_TYPES = {"APOSTILLE", "EXEMPLIFIED"}
PACKET_TYPES = {"DELAYED", "FOREIGN"}
ELIGIBLE_RELATIONSHIPS = {"SELF", "PARENT", "CHILD", "SPOUSE", "SIBLING",
                          "LEGAL_GUARDIAN", "LEGAL_REPRESENTATIVE"}

# Calculation constants (§1.3 / §3)
STATUTORY_WINDOW_DAYS = {"BIRTH": 10, "DEATH": 5, "FETAL_DEATH": 5}
DELAYED_BASE_FEE_CENTS = 2000
PER_DAY_SURCHARGE_CENTS = 100
MAX_SURCHARGE_CENTS = 5000
SEARCH_FEE_CENTS = 1500
ADDITIONAL_COPY_CENTS = 800
EXPEDITE_SURCHARGE_CENTS = 1900
INFORMATIONAL_COPY_CENTS = 1000
PUBLIC_THRESHOLD_YEARS = {"BIRTH": 75, "DEATH": 25, "FETAL_DEATH": 25}
STATE_SHARE_PCT = Decimal("0.45")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Response envelope (§2.2)
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {"api_request_id": gen_req_id(),
            "api_request_timestamp": fmt_dt(now())}


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = fmt_dt(v) if isinstance(v, datetime) else v
    return out


def ok(data, response_type="object", status=200, extra_meta=None):
    meta = base_meta()
    if extra_meta:
        meta.update(extra_meta)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def obj(entity, status=200):
    return ok(serialize(entity), "object", status)


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = base_meta()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    return jsonify({"meta": base_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_VITAL_EVENT_NOT_FOUND",
                             "message": "Not found"}}), 404


@app.errorhandler(405)
def handle_405(_e):
    return jsonify({"meta": base_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_INVALID_STATE",
                             "message": "Method not allowed"}}), 405


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return jsonify({"meta": base_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_INTERNAL", "message": str(err)}}), 500


# ---------------------------------------------------------------------------
# Auth (§2.1, validation priorities 1-3)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid credentials")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Body helpers / field validation (priority 5 shape -> 400)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return data


def bad_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        bad_request(f"{name} is required and must be a string")
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        bad_request(f"{name} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        bad_request(f"{name} must be one of {sorted(allowed)}")
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        bad_request(f"{name} is required and must be an integer")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        bad_request(f"{name} is required and must be a boolean")
    return v


def opt_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, bool):
        bad_request(f"{name} must be a boolean")
    return v


def req_dt(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        bad_request(f"{name} is required and must be an ISO 8601 datetime string")
    try:
        return parse_dt(v)
    except Exception:
        bad_request(f"{name} must be a valid ISO 8601 datetime")


# ---------------------------------------------------------------------------
# Existence (priority 4 -> 404)
# ---------------------------------------------------------------------------
def get_or_404(kind, rid):
    ent = DB[kind].get(rid)
    if ent is None:
        raise ApiError(NOT_FOUND[kind], 404, f"{kind} {rid} not found")
    return ent


def ref_or_404(kind, rid):
    """Resolve a body-referenced id if present; raise the entity's 404."""
    if rid is None:
        return None
    if not isinstance(rid, str) or rid not in DB[kind]:
        raise ApiError(NOT_FOUND[kind], 404, f"{kind} {rid} not found")
    return DB[kind][rid]


# ---------------------------------------------------------------------------
# Mutation helpers (§2.4 / §2.5)
# ---------------------------------------------------------------------------
def touch(entity):
    """Refresh updated_at only (no version bump)."""
    entity["updated_at"] = now()


def bump(entity):
    """Refresh updated_at and increment version by one."""
    entity["updated_at"] = now()
    entity["version"] = entity["version"] + 1


def new_common():
    t = now()
    return {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t,
            "version": 1, "_seq": next_seq()}


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def registration_delay_fee(event_type, event_date, filed_at, foreign_born):
    window = STATUTORY_WINDOW_DAYS[event_type]
    days_late = int((filed_at - event_date).total_seconds() // 86400)
    if foreign_born:
        registration_type = "FOREIGN"
    elif days_late > window:
        registration_type = "DELAYED"
    else:
        registration_type = "TIMELY"
    if registration_type == "TIMELY":
        fee = 0
    else:
        overage = max(0, days_late - window)
        fee = DELAYED_BASE_FEE_CENTS + min(MAX_SURCHARGE_CENTS,
                                           PER_DAY_SURCHARGE_CENTS * overage)
    return days_late, registration_type, fee


def copy_eligibility(event, relationship):
    age_years = int((now() - event["event_date"]).total_seconds() // (365 * 86400))
    threshold = PUBLIC_THRESHOLD_YEARS[event["event_type"]]
    if age_years >= threshold:
        return "INFORMATIONAL"
    if relationship in ELIGIBLE_RELATIONSHIPS:
        return "CERTIFIED"
    raise ApiError("ERR_NOT_ELIGIBLE", 403, "Requester not eligible for confidential record")


def certified_copy_fee(copy_class, copy_count, expedite, category):
    if copy_class == "CERTIFIED":
        base = SEARCH_FEE_CENTS + ADDITIONAL_COPY_CENTS * (copy_count - 1)
        gross = base + (EXPEDITE_SURCHARGE_CENTS if expedite else 0)
        if category == "VETERAN":
            return 0
        if category == "INDIGENT":
            return round_half_up(Decimal(gross) / Decimal(2))
        return gross
    # INFORMATIONAL
    gross = INFORMATIONAL_COPY_CENTS * copy_count + (EXPEDITE_SURCHARGE_CENTS if expedite else 0)
    return gross


# ---------------------------------------------------------------------------
# Listing (§2.3)
# ---------------------------------------------------------------------------
def paginate_and_list(kind, filters):
    items = [e for e in DB[kind].values()]
    for key, val in filters.items():
        if val is not None:
            items = [e for e in items if str(e.get(key)) == str(val)]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)

    def parse_limit():
        raw = request.args.get("limit")
        if raw is None:
            return 10
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return 10
        if v < 1:
            return 1
        if v > 100:
            return 100
        return v

    def parse_offset():
        raw = request.args.get("offset")
        if raw is None:
            return 0
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return 0
        return max(0, v)

    limit = parse_limit()
    offset = parse_offset()
    page = items[offset:offset + limit]
    has_more = offset + len(page) < total
    meta = {"limit": limit, "offset": offset,
            "total_count": total, "has_more": has_more}
    return ok([serialize(e) for e in page], "array", 200, extra_meta=meta)


# ===========================================================================
# Clock admin
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    authenticate({"StateRegistrar"})
    body = get_body()
    CLOCK["now"] = req_dt(body, "to_iso8601")
    return ok({}, "object", 200)


# ===========================================================================
# Facility
# ===========================================================================
@app.route("/facilities", methods=["POST"])
def create_facility():
    authenticate({"StateRegistrar"})
    body = get_body()
    ent = new_common()
    ent.update({
        "_kind": "Facility",
        "name": req_str(body, "name"),
        "facility_type": req_enum(body, "facility_type", FACILITY_TYPES),
        "jurisdiction_code": req_str(body, "jurisdiction_code"),
        "npi": req_str(body, "npi"),
        "active": opt_bool(body, "active", True),
        "registered_count": 0,
    })
    DB["Facility"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/facilities/<rid>", methods=["GET"])
def get_facility(rid):
    authenticate(ROLES)
    return obj(get_or_404("Facility", rid))


# ===========================================================================
# Certifier
# ===========================================================================
@app.route("/certifiers", methods=["POST"])
def create_certifier():
    authenticate({"StateRegistrar"})
    body = get_body()
    ent = new_common()
    ent.update({
        "_kind": "Certifier",
        "name": req_str(body, "name"),
        "certifier_type": req_enum(body, "certifier_type", CERTIFIER_TYPES),
        "license_number": req_str(body, "license_number"),
        "jurisdiction_code": req_str(body, "jurisdiction_code"),
        "active": opt_bool(body, "active", True),
        "locked_certification_count": 0,
    })
    DB["Certifier"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/certifiers/<rid>", methods=["GET"])
def get_certifier(rid):
    authenticate({"StateRegistrar", "MedicalCertifier", "FacilityFiler"})
    return obj(get_or_404("Certifier", rid))


# ===========================================================================
# VitalEvent
# ===========================================================================
@app.route("/vital-events", methods=["POST"])
def create_vital_event():
    authenticate({"FacilityFiler"})
    body = get_body()
    # existence (facility_id) before shape, but must be present to resolve
    if "facility_id" in body and body.get("facility_id") is not None:
        ref_or_404("Facility", body.get("facility_id"))
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    event_date = req_dt(body, "event_date")
    subject_last_name = req_str(body, "subject_last_name")
    subject_first_name = req_str(body, "subject_first_name")
    sex = req_enum(body, "sex", SEXES)
    jurisdiction_code = req_str(body, "jurisdiction_code")
    facility_id = req_str(body, "facility_id")
    place_of_event = req_str(body, "place_of_event")
    foreign_born = opt_bool(body, "foreign_born", False)
    ref_or_404("Facility", facility_id)

    ent = new_common()
    ent.update({
        "_kind": "VitalEvent",
        "event_type": event_type,
        "event_date": event_date,
        "subject_last_name": subject_last_name,
        "subject_first_name": subject_first_name,
        "sex": sex,
        "jurisdiction_code": jurisdiction_code,
        "facility_id": facility_id,
        "place_of_event": place_of_event,
        "foreign_born": foreign_born,
        "status": "DRAFT",
        "registration_type": None,
        "days_late": 0,
        "delayed_fee_cents": 0,
        "certification_required": event_type in ("DEATH", "FETAL_DEATH"),
        "filed_at": None,
        "registered_at": None,
        "state_file_number": None,
        "paternity_established": False,
        "father_last_name": None,
        "father_first_name": None,
        "cause_of_death_amended": False,
        "amendment_count": 0,
        "copies_issued_count": 0,
        "fees_collected_cents": 0,
    })
    DB["VitalEvent"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/vital-events/<rid>", methods=["GET"])
def get_vital_event(rid):
    authenticate(ROLES)
    return obj(get_or_404("VitalEvent", rid))


@app.route("/vital-events", methods=["GET"])
def list_vital_events():
    authenticate({"StateRegistrar", "FacilityFiler"})
    filters = {
        "facility_id": request.args.get("facility_id"),
        "status": request.args.get("status"),
        "event_type": request.args.get("event_type"),
        "jurisdiction_code": request.args.get("jurisdiction_code"),
        "registration_type": request.args.get("registration_type"),
    }
    return paginate_and_list("VitalEvent", filters)


def _do_file(event):
    event_type = event["event_type"]
    event["filed_at"] = now()
    days_late, reg_type, fee = registration_delay_fee(
        event_type, event["event_date"], event["filed_at"], event["foreign_born"])
    event["days_late"] = days_late
    event["registration_type"] = reg_type
    event["delayed_fee_cents"] = fee
    event["status"] = "FILED"
    touch(event)  # file does not bump version (§2.5 -> per-workflow, no version listed)


@app.route("/vital-events/<rid>/file", methods=["POST"])
def file_vital_event(rid):
    uid, _role = authenticate({"FacilityFiler"})
    event = get_or_404("VitalEvent", rid)
    if uid != event["facility_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Filer does not own this event")
    if event["status"] == "RETURNED":
        event["status"] = "DRAFT"  # RETURNED reopens to DRAFT then files
    elif event["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Event not in a fileable state")
    _do_file(event)
    return obj(event)


@app.route("/vital-events/<rid>/register", methods=["POST"])
def register_vital_event(rid):
    authenticate({"StateRegistrar"})
    event = get_or_404("VitalEvent", rid)
    if event["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event not in FILED state")

    cert = None
    if event["certification_required"]:
        cert = _find_certification_for_event(event["id"])
        if cert is None or cert["status"] != "CERTIFIED":
            raise ApiError("ERR_CERTIFICATION_REQUIRED", 409,
                           "A CERTIFIED medical certification is required")
    if event["registration_type"] in ("DELAYED", "FOREIGN"):
        if not _has_accepted_packet(event["id"]):
            raise ApiError("ERR_DELAYED_REGISTRATION_REQUIRED", 409,
                           "An ACCEPTED delayed-registration packet is required")

    event["registered_at"] = now()
    year = event["registered_at"].year
    seq = 1 + sum(1 for e in DB["VitalEvent"].values()
                  if e["id"] != event["id"]
                  and e["jurisdiction_code"] == event["jurisdiction_code"]
                  and e["event_type"] == event["event_type"]
                  and e["status"] in ("REGISTERED", "AMENDED"))
    event["state_file_number"] = f"{year}-{event['event_type']}-{seq:06d}"
    event["status"] = "REGISTERED"

    facility = DB["Facility"].get(event["facility_id"])
    if facility is not None:
        facility["registered_count"] += 1
        bump(facility)

    if event["certification_required"] and cert is not None:
        cert["status"] = "LOCKED"
        bump(cert)
        certifier = DB["Certifier"].get(cert["certifier_id"])
        if certifier is not None:
            certifier["locked_certification_count"] += 1
            bump(certifier)

    bump(event)
    return obj(event)


@app.route("/vital-events/<rid>/return", methods=["POST"])
def return_vital_event(rid):
    authenticate({"StateRegistrar"})
    event = get_or_404("VitalEvent", rid)
    if event["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event not in FILED state")
    event["status"] = "RETURNED"
    touch(event)
    return obj(event)


@app.route("/vital-events/<rid>/void", methods=["POST"])
def void_vital_event(rid):
    authenticate({"StateRegistrar"})
    event = get_or_404("VitalEvent", rid)
    if event["status"] not in ("REGISTERED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Event not in a voidable state")
    event["status"] = "VOIDED"
    facility = DB["Facility"].get(event["facility_id"])
    if facility is not None:
        facility["registered_count"] -= 1
        bump(facility)
    for copy in DB["CertifiedCopyRequest"].values():
        if copy["vital_event_id"] == event["id"] and copy["status"] == "ISSUED":
            event["copies_issued_count"] -= 1
            event["fees_collected_cents"] -= copy["fee_total_cents"]
    bump(event)
    return obj(event)


# ===========================================================================
# MedicalCertification
# ===========================================================================
def _find_certification_for_event(event_id):
    for c in DB["MedicalCertification"].values():
        if c["vital_event_id"] == event_id:
            return c
    return None


@app.route("/certifications", methods=["POST"])
def create_certification():
    authenticate({"MedicalCertifier"})
    body = get_body()
    # existence (left-to-right: vital_event_id then certifier_id)
    if "vital_event_id" in body and body.get("vital_event_id") is not None:
        ref_or_404("VitalEvent", body.get("vital_event_id"))
    if "certifier_id" in body and body.get("certifier_id") is not None:
        ref_or_404("Certifier", body.get("certifier_id"))
    vital_event_id = req_str(body, "vital_event_id")
    certifier_id = req_str(body, "certifier_id")
    cause_of_death = req_str(body, "cause_of_death")
    manner_of_death = req_enum(body, "manner_of_death", MANNERS)
    event = ref_or_404("VitalEvent", vital_event_id)
    ref_or_404("Certifier", certifier_id)

    if event["event_type"] not in ("DEATH", "FETAL_DEATH"):
        raise ApiError("ERR_NOT_DEATH_EVENT", 409,
                       "Certification only for DEATH/FETAL_DEATH events")
    if _find_certification_for_event(vital_event_id) is not None:
        raise ApiError("ERR_DUPLICATE_CERTIFICATION", 409,
                       "Event already has a certification")

    ent = new_common()
    ent.update({
        "_kind": "MedicalCertification",
        "vital_event_id": vital_event_id,
        "certifier_id": certifier_id,
        "cause_of_death": cause_of_death,
        "manner_of_death": manner_of_death,
        "status": "PENDING",
        "certified_at": None,
        "amendment_count": 0,
    })
    DB["MedicalCertification"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/certifications/<rid>", methods=["GET"])
def get_certification(rid):
    authenticate({"StateRegistrar", "MedicalCertifier", "FacilityFiler"})
    return obj(get_or_404("MedicalCertification", rid))


@app.route("/certifications", methods=["GET"])
def list_certifications():
    authenticate({"StateRegistrar", "MedicalCertifier"})
    filters = {
        "vital_event_id": request.args.get("vital_event_id"),
        "certifier_id": request.args.get("certifier_id"),
        "status": request.args.get("status"),
    }
    return paginate_and_list("MedicalCertification", filters)


@app.route("/certifications/<rid>/certify", methods=["POST"])
def certify(rid):
    uid, _role = authenticate({"MedicalCertifier"})
    cert = get_or_404("MedicalCertification", rid)
    if uid != cert["certifier_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Certifier does not own this certification")
    if cert["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Certification not in PENDING state")
    cert["certified_at"] = now()
    cert["status"] = "CERTIFIED"
    bump(cert)
    return obj(cert)


# ===========================================================================
# Amendment
# ===========================================================================
@app.route("/amendments", methods=["POST"])
def create_amendment():
    authenticate({"StateRegistrar"})
    body = get_body()
    if "vital_event_id" in body and body.get("vital_event_id") is not None:
        ref_or_404("VitalEvent", body.get("vital_event_id"))
    if "target_certification_id" in body and body.get("target_certification_id") is not None:
        ref_or_404("MedicalCertification", body.get("target_certification_id"))
    vital_event_id = req_str(body, "vital_event_id")
    amendment_type = req_enum(body, "amendment_type", AMENDMENT_TYPES)
    field_name = req_str(body, "field_name")
    new_value = req_str(body, "new_value")
    reason = req_str(body, "reason")
    target_certification_id = body.get("target_certification_id")
    ref_or_404("VitalEvent", vital_event_id)

    if amendment_type == "MEDICAL":
        if not target_certification_id:
            raise ApiError("ERR_AMENDMENT_TARGET_REQUIRED", 422,
                           "MEDICAL amendment requires target_certification_id")
        ref_or_404("MedicalCertification", target_certification_id)
    else:  # DEMOGRAPHIC
        if target_certification_id:
            raise ApiError("ERR_AMENDMENT_TARGET_REQUIRED", 422,
                           "DEMOGRAPHIC amendment must omit target_certification_id")

    ent = new_common()
    ent.update({
        "_kind": "Amendment",
        "vital_event_id": vital_event_id,
        "amendment_type": amendment_type,
        "target_certification_id": target_certification_id if amendment_type == "MEDICAL" else None,
        "field_name": field_name,
        "new_value": new_value,
        "reason": reason,
        "evidence_required": False,
        "status": "DRAFT",
    })
    DB["Amendment"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/amendments/<rid>", methods=["GET"])
def get_amendment(rid):
    authenticate({"StateRegistrar", "Applicant"})
    return obj(get_or_404("Amendment", rid))


@app.route("/amendments", methods=["GET"])
def list_amendments():
    authenticate({"StateRegistrar"})
    filters = {
        "vital_event_id": request.args.get("vital_event_id"),
        "target_certification_id": request.args.get("target_certification_id"),
        "status": request.args.get("status"),
    }
    return paginate_and_list("Amendment", filters)


@app.route("/amendments/<rid>/submit", methods=["POST"])
def submit_amendment(rid):
    authenticate({"StateRegistrar"})
    amd = get_or_404("Amendment", rid)
    if amd["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Amendment not submittable")
    event = get_or_404("VitalEvent", amd["vital_event_id"])
    if event["status"] not in ("REGISTERED", "AMENDED"):
        raise ApiError("ERR_EVENT_NOT_REGISTERED", 409, "Target event not registered")
    amd["evidence_required"] = now() > event["registered_at"] + timedelta(days=365)
    amd["status"] = "SUBMITTED"
    bump(amd)
    return obj(amd)


@app.route("/amendments/<rid>/approve", methods=["POST"])
def approve_amendment(rid):
    authenticate({"StateRegistrar"})
    body = get_body()
    amd = get_or_404("Amendment", rid)
    expected = req_int(body, "expected_vital_event_version")
    if amd["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Amendment not in SUBMITTED state")
    event = get_or_404("VitalEvent", amd["vital_event_id"])
    if event["status"] not in ("REGISTERED", "AMENDED"):
        raise ApiError("ERR_EVENT_NOT_REGISTERED", 409, "Target event not registered")
    if expected != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION", 412, "Stale expected_vital_event_version")

    amd["status"] = "APPROVED"
    if amd["amendment_type"] == "DEMOGRAPHIC":
        event[amd["field_name"]] = amd["new_value"]
        event["amendment_count"] += 1
        event["status"] = "AMENDED"
        bump(event)
    else:  # MEDICAL
        cert = DB["MedicalCertification"].get(amd["target_certification_id"])
        if cert is not None:
            cert["cause_of_death"] = amd["new_value"]
            cert["amendment_count"] += 1
            cert["status"] = "AMENDED"
            bump(cert)
        event["cause_of_death_amended"] = True
        event["amendment_count"] += 1
        event["status"] = "AMENDED"
        bump(event)
    bump(amd)
    return obj(amd)


@app.route("/amendments/<rid>/reject", methods=["POST"])
def reject_amendment(rid):
    authenticate({"StateRegistrar"})
    amd = get_or_404("Amendment", rid)
    if amd["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Amendment not in SUBMITTED state")
    amd["status"] = "REJECTED"
    bump(amd)
    return obj(amd)


# ===========================================================================
# PaternityAcknowledgment
# ===========================================================================
@app.route("/paternity-acknowledgments", methods=["POST"])
def create_paternity():
    uid, _role = authenticate({"StateRegistrar", "Applicant"})
    body = get_body()
    if "vital_event_id" in body and body.get("vital_event_id") is not None:
        ref_or_404("VitalEvent", body.get("vital_event_id"))
    vital_event_id = req_str(body, "vital_event_id")
    father_last_name = req_str(body, "father_last_name")
    father_first_name = req_str(body, "father_first_name")
    mother_consent = req_bool(body, "mother_consent")
    ref_or_404("VitalEvent", vital_event_id)

    ent = new_common()
    ent.update({
        "_kind": "PaternityAcknowledgment",
        "vital_event_id": vital_event_id,
        "father_last_name": father_last_name,
        "father_first_name": father_first_name,
        "mother_consent": mother_consent,
        "filed_by_user_id": uid,
        "status": "DRAFT",
        "acknowledged_at": None,
        "rescission_deadline": None,
    })
    DB["PaternityAcknowledgment"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/paternity-acknowledgments/<rid>", methods=["GET"])
def get_paternity(rid):
    authenticate({"StateRegistrar", "Applicant"})
    return obj(get_or_404("PaternityAcknowledgment", rid))


@app.route("/paternity-acknowledgments", methods=["GET"])
def list_paternity():
    authenticate({"StateRegistrar"})
    filters = {
        "vital_event_id": request.args.get("vital_event_id"),
        "status": request.args.get("status"),
    }
    return paginate_and_list("PaternityAcknowledgment", filters)


@app.route("/paternity-acknowledgments/<rid>/acknowledge", methods=["POST"])
def acknowledge_paternity(rid):
    authenticate({"StateRegistrar"})
    pat = get_or_404("PaternityAcknowledgment", rid)
    if pat["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Acknowledgment not in DRAFT state")
    event = get_or_404("VitalEvent", pat["vital_event_id"])
    if event["event_type"] != "BIRTH":
        raise ApiError("ERR_NOT_BIRTH_EVENT", 409, "Referenced event is not a BIRTH")
    if event["status"] not in ("REGISTERED", "AMENDED"):
        raise ApiError("ERR_EVENT_NOT_REGISTERED", 409, "Referenced event not registered")
    if not pat["mother_consent"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Mother consent required")

    pat["acknowledged_at"] = now()
    pat["rescission_deadline"] = pat["acknowledged_at"] + timedelta(days=60)
    pat["status"] = "ACKNOWLEDGED"
    bump(pat)

    event["father_last_name"] = pat["father_last_name"]
    event["father_first_name"] = pat["father_first_name"]
    event["paternity_established"] = True
    bump(event)
    return obj(pat)


@app.route("/paternity-acknowledgments/<rid>/rescind", methods=["POST"])
def rescind_paternity(rid):
    authenticate({"StateRegistrar", "Applicant"})
    pat = get_or_404("PaternityAcknowledgment", rid)
    if pat["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Acknowledgment not in ACKNOWLEDGED state")
    if now() > pat["rescission_deadline"]:
        raise ApiError("ERR_RESCISSION_WINDOW_CLOSED", 409, "Rescission window closed")
    pat["status"] = "RESCINDED"
    bump(pat)

    event = DB["VitalEvent"].get(pat["vital_event_id"])
    if event is not None:
        event["father_last_name"] = None
        event["father_first_name"] = None
        event["paternity_established"] = False
        bump(event)
    return obj(pat)


@app.route("/paternity-acknowledgments/<rid>/finalize", methods=["POST"])
def finalize_paternity(rid):
    authenticate({"StateRegistrar"})
    pat = get_or_404("PaternityAcknowledgment", rid)
    if pat["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Acknowledgment not in ACKNOWLEDGED state")
    if not (now() > pat["rescission_deadline"]):
        raise ApiError("ERR_RESCISSION_WINDOW_OPEN", 409, "Rescission window still open")
    pat["status"] = "FINALIZED"
    bump(pat)
    return obj(pat)


# ===========================================================================
# CertifiedCopyRequest
# ===========================================================================
@app.route("/certified-copy-requests", methods=["POST"])
def create_copy_request():
    authenticate({"Applicant", "StateRegistrar"})
    body = get_body()
    if "vital_event_id" in body and body.get("vital_event_id") is not None:
        ref_or_404("VitalEvent", body.get("vital_event_id"))
    vital_event_id = req_str(body, "vital_event_id")
    requester_name = req_str(body, "requester_name")
    requester_relationship = req_enum(body, "requester_relationship", RELATIONSHIPS)
    requester_category = opt_enum(body, "requester_category", CATEGORIES, "STANDARD")
    id_document_type = req_enum(body, "id_document_type", ID_DOC_TYPES)
    copy_count = req_int(body, "copy_count")
    expedite = opt_bool(body, "expedite", False)
    ref_or_404("VitalEvent", vital_event_id)

    if copy_count < 1:
        raise ApiError("ERR_INVALID_COPY_COUNT", 422, "copy_count must be >= 1")

    ent = new_common()
    ent.update({
        "_kind": "CertifiedCopyRequest",
        "vital_event_id": vital_event_id,
        "requester_name": requester_name,
        "requester_relationship": requester_relationship,
        "requester_category": requester_category,
        "id_document_type": id_document_type,
        "copy_count": copy_count,
        "expedite": expedite,
        "id_verified": False,
        "copy_class": None,
        "fee_total_cents": 0,
        "status": "SUBMITTED",
        "issued_at": None,
    })
    DB["CertifiedCopyRequest"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/certified-copy-requests/<rid>", methods=["GET"])
def get_copy_request(rid):
    authenticate({"StateRegistrar", "Applicant"})
    return obj(get_or_404("CertifiedCopyRequest", rid))


@app.route("/certified-copy-requests", methods=["GET"])
def list_copy_requests():
    authenticate({"StateRegistrar", "Applicant"})
    filters = {
        "vital_event_id": request.args.get("vital_event_id"),
        "status": request.args.get("status"),
    }
    return paginate_and_list("CertifiedCopyRequest", filters)


@app.route("/certified-copy-requests/<rid>/verify-id", methods=["POST"])
def verify_id(rid):
    authenticate({"StateRegistrar"})
    copy = get_or_404("CertifiedCopyRequest", rid)
    if copy["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Copy request not in SUBMITTED state")
    copy["id_verified"] = True
    copy["status"] = "ID_VERIFIED"
    bump(copy)
    return obj(copy)


@app.route("/certified-copy-requests/<rid>/issue", methods=["POST"])
def issue_copy(rid):
    authenticate({"StateRegistrar"})
    body = get_body()
    copy = get_or_404("CertifiedCopyRequest", rid)
    expected = req_int(body, "expected_vital_event_version")
    # state precedence: SUBMITTED -> ERR_ID_NOT_VERIFIED; terminal -> ERR_INVALID_STATE
    if copy["status"] == "SUBMITTED":
        raise ApiError("ERR_ID_NOT_VERIFIED", 409, "Copy request must be ID_VERIFIED")
    if copy["status"] != "ID_VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Copy request not issuable")
    event = get_or_404("VitalEvent", copy["vital_event_id"])
    if event["status"] not in ("REGISTERED", "AMENDED"):
        raise ApiError("ERR_EVENT_NOT_REGISTERED", 409, "Referenced event not registered")
    copy_class = copy_eligibility(event, copy["requester_relationship"])
    if expected != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION", 412, "Stale expected_vital_event_version")

    copy["copy_class"] = copy_class
    copy["fee_total_cents"] = certified_copy_fee(
        copy_class, copy["copy_count"], copy["expedite"], copy["requester_category"])
    copy["issued_at"] = now()
    copy["status"] = "ISSUED"
    bump(copy)

    event["copies_issued_count"] += 1
    event["fees_collected_cents"] += copy["fee_total_cents"]
    bump(event)
    return obj(copy)


@app.route("/certified-copy-requests/<rid>/deny", methods=["POST"])
def deny_copy(rid):
    authenticate({"StateRegistrar"})
    copy = get_or_404("CertifiedCopyRequest", rid)
    if copy["status"] not in ("SUBMITTED", "ID_VERIFIED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Copy request not deniable")
    copy["status"] = "DENIED"
    bump(copy)
    return obj(copy)


# ===========================================================================
# ApostilleRequest
# ===========================================================================
@app.route("/apostille-requests", methods=["POST"])
def create_apostille():
    authenticate({"Applicant", "StateRegistrar"})
    body = get_body()
    if "certified_copy_request_id" in body and body.get("certified_copy_request_id") is not None:
        ref_or_404("CertifiedCopyRequest", body.get("certified_copy_request_id"))
    certified_copy_request_id = req_str(body, "certified_copy_request_id")
    destination_country = req_str(body, "destination_country")
    apostille_type = req_enum(body, "apostille_type", APOSTILLE_TYPES)
    ref_or_404("CertifiedCopyRequest", certified_copy_request_id)

    ent = new_common()
    ent.update({
        "_kind": "ApostilleRequest",
        "certified_copy_request_id": certified_copy_request_id,
        "destination_country": destination_country,
        "apostille_type": apostille_type,
        "status": "SUBMITTED",
        "authenticated_at": None,
    })
    DB["ApostilleRequest"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/apostille-requests/<rid>", methods=["GET"])
def get_apostille(rid):
    authenticate({"StateRegistrar", "Applicant"})
    return obj(get_or_404("ApostilleRequest", rid))


@app.route("/apostille-requests", methods=["GET"])
def list_apostille():
    authenticate({"StateRegistrar"})
    filters = {
        "certified_copy_request_id": request.args.get("certified_copy_request_id"),
        "status": request.args.get("status"),
    }
    return paginate_and_list("ApostilleRequest", filters)


@app.route("/apostille-requests/<rid>/authenticate", methods=["POST"])
def authenticate_apostille(rid):
    authenticate({"StateRegistrar"})
    ap = get_or_404("ApostilleRequest", rid)
    if ap["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Apostille not in SUBMITTED state")
    copy = get_or_404("CertifiedCopyRequest", ap["certified_copy_request_id"])
    if copy["status"] != "ISSUED":
        raise ApiError("ERR_COPY_NOT_ISSUED", 409, "Referenced copy not ISSUED")
    ap["authenticated_at"] = now()
    ap["status"] = "AUTHENTICATED"
    bump(ap)
    return obj(ap)


@app.route("/apostille-requests/<rid>/reject", methods=["POST"])
def reject_apostille(rid):
    authenticate({"StateRegistrar"})
    ap = get_or_404("ApostilleRequest", rid)
    if ap["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Apostille not in SUBMITTED state")
    ap["status"] = "REJECTED"
    bump(ap)
    return obj(ap)


# ===========================================================================
# DelayedRegistrationPacket
# ===========================================================================
def _has_accepted_packet(event_id):
    for p in DB["DelayedRegistrationPacket"].values():
        if p["vital_event_id"] == event_id and p["status"] == "ACCEPTED":
            return True
    return False


@app.route("/delayed-registration-packets", methods=["POST"])
def create_packet():
    authenticate({"FacilityFiler", "StateRegistrar"})
    body = get_body()
    if "vital_event_id" in body and body.get("vital_event_id") is not None:
        ref_or_404("VitalEvent", body.get("vital_event_id"))
    vital_event_id = req_str(body, "vital_event_id")
    packet_type = req_enum(body, "packet_type", PACKET_TYPES)
    documentary_evidence_count = req_int(body, "documentary_evidence_count")
    hearing_start = req_dt(body, "hearing_start")
    hearing_end = req_dt(body, "hearing_end")
    hearing_jurisdiction_code = req_str(body, "hearing_jurisdiction_code")
    ref_or_404("VitalEvent", vital_event_id)

    if not (hearing_end > hearing_start):
        raise ApiError("ERR_INVALID_REQUEST", 400, "hearing_end must be after hearing_start")
    if documentary_evidence_count < 1:
        raise ApiError("ERR_INVALID_COPY_COUNT", 422, "documentary_evidence_count must be >= 1")

    ent = new_common()
    ent.update({
        "_kind": "DelayedRegistrationPacket",
        "vital_event_id": vital_event_id,
        "packet_type": packet_type,
        "documentary_evidence_count": documentary_evidence_count,
        "hearing_start": hearing_start,
        "hearing_end": hearing_end,
        "hearing_jurisdiction_code": hearing_jurisdiction_code,
        "status": "SUBMITTED",
        "accepted_at": None,
    })
    DB["DelayedRegistrationPacket"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/delayed-registration-packets/<rid>", methods=["GET"])
def get_packet(rid):
    authenticate({"StateRegistrar", "FacilityFiler"})
    return obj(get_or_404("DelayedRegistrationPacket", rid))


@app.route("/delayed-registration-packets", methods=["GET"])
def list_packets():
    authenticate({"StateRegistrar"})
    filters = {
        "vital_event_id": request.args.get("vital_event_id"),
        "status": request.args.get("status"),
    }
    return paginate_and_list("DelayedRegistrationPacket", filters)


@app.route("/delayed-registration-packets/<rid>/accept", methods=["POST"])
def accept_packet(rid):
    authenticate({"StateRegistrar"})
    packet = get_or_404("DelayedRegistrationPacket", rid)
    if packet["status"] == "RETURNED":
        packet["status"] = "SUBMITTED"  # reopen a returned packet
        bump(packet)
        return obj(packet)
    if packet["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Packet not in an acceptable state")

    buffer = timedelta(minutes=15)
    for other in DB["DelayedRegistrationPacket"].values():
        if other["id"] == packet["id"]:
            continue
        if other["hearing_jurisdiction_code"] != packet["hearing_jurisdiction_code"]:
            continue
        if other["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        if (packet["hearing_start"] <= other["hearing_end"] + buffer
                and other["hearing_start"] <= packet["hearing_end"] + buffer):
            raise ApiError("ERR_HEARING_SLOT_CONFLICT", 409, "Hearing slot conflict")

    packet["accepted_at"] = now()
    packet["status"] = "ACCEPTED"
    bump(packet)
    return obj(packet)


@app.route("/delayed-registration-packets/<rid>/return", methods=["POST"])
def return_packet(rid):
    authenticate({"StateRegistrar"})
    packet = get_or_404("DelayedRegistrationPacket", rid)
    if packet["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Packet not in SUBMITTED state")
    packet["status"] = "RETURNED"
    bump(packet)
    return obj(packet)


# ===========================================================================
# StatisticsReport
# ===========================================================================
@app.route("/statistics-reports", methods=["POST"])
def create_report():
    authenticate({"StateRegistrar"})
    body = get_body()
    jurisdiction_code = req_str(body, "jurisdiction_code")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")

    # overlap check (half-open); adjacency allowed
    for other in DB["StatisticsReport"].values():
        if other["jurisdiction_code"] != jurisdiction_code:
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 409, "Report period overlaps existing")

    birth_count = death_count = fetal_death_count = 0
    for e in DB["VitalEvent"].values():
        if (e["jurisdiction_code"] == jurisdiction_code
                and e["status"] in ("REGISTERED", "AMENDED")
                and period_start <= e["event_date"] < period_end):
            if e["event_type"] == "BIRTH":
                birth_count += 1
            elif e["event_type"] == "DEATH":
                death_count += 1
            elif e["event_type"] == "FETAL_DEATH":
                fetal_death_count += 1

    copies = []
    for c in DB["CertifiedCopyRequest"].values():
        if c["status"] != "ISSUED":
            continue
        ev = DB["VitalEvent"].get(c["vital_event_id"])
        if ev is None or ev["jurisdiction_code"] != jurisdiction_code:
            continue
        if c["issued_at"] is not None and period_start <= c["issued_at"] < period_end:
            copies.append(c)
    copies.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total_fees = sum(c["fee_total_cents"] for c in copies)
    remittance = sum(round_half_up(Decimal(c["fee_total_cents"]) * STATE_SHARE_PCT)
                     for c in copies)

    ent = new_common()
    ent.update({
        "_kind": "StatisticsReport",
        "jurisdiction_code": jurisdiction_code,
        "period_start": period_start,
        "period_end": period_end,
        "birth_count": birth_count,
        "death_count": death_count,
        "fetal_death_count": fetal_death_count,
        "total_fees_collected_cents": total_fees,
        "state_remittance_cents": remittance,
    })
    DB["StatisticsReport"][ent["id"]] = ent
    return obj(ent, 201)


@app.route("/statistics-reports/<rid>", methods=["GET"])
def get_report(rid):
    authenticate({"StateRegistrar"})
    return obj(get_or_404("StatisticsReport", rid))


@app.route("/statistics-reports", methods=["GET"])
def list_reports():
    authenticate({"StateRegistrar"})
    filters = {"jurisdiction_code": request.args.get("jurisdiction_code")}
    return paginate_and_list("StatisticsReport", filters)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
