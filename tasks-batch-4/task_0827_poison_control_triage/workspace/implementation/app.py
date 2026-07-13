"""Poison Control & Toxicology Triage API — Flask implementation.

All state is in-memory (see db.py) and wiped on every process start.
"""
import os
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify

from db import db, new_id
import errors
from errors import ApiError, raise_err

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Specialist", "Toxicologist", "SurveillanceOfficer", "SystemAdmin"}

SUBSTANCE_CATEGORIES = {"ANALGESIC", "HOUSEHOLD_CHEMICAL", "PESTICIDE", "PLANT",
                        "PHARMACEUTICAL", "HYDROCARBON", "HEAVY_METAL"}
ROUTES = {"INGESTION", "INHALATION", "DERMAL", "OCULAR", "INJECTION"}
FACILITY_TYPES = {"ED", "URGENT_CARE", "ICU", "CLINIC"}
FACILITY_STATUSES = {"ACCEPTING", "DIVERTING", "OFFLINE"}
RISK_TIERS = {"MINIMAL", "MODERATE", "SEVERE", "CRITICAL"}
MANAGEMENT_SETTINGS = {"HOME", "ED"}
CREDENTIALS = {"SPI", "TOXICOLOGIST"}
PATIENT_SEXES = {"MALE", "FEMALE", "UNKNOWN"}
DISPOSITION_TYPES = {"HOME_MANAGEMENT", "ED_REFERRAL"}
NOTE_TYPES = {"INTAKE", "CLINICAL", "INTERPRETER", "DISPOSITION", "FOLLOWUP"}
COMPLETE_OUTCOMES = {"RESOLVED", "WORSENED", "NO_ANSWER"}

ROUTE_BIOAVAILABILITY = {"INGESTION": Decimal("1.0"), "INHALATION": Decimal("0.8"),
                         "DERMAL": Decimal("0.4"), "OCULAR": Decimal("0.3"),
                         "INJECTION": Decimal("1.0")}
INTERACTION_WEIGHT = {"MINIMAL": Decimal("0.5"), "MODERATE": Decimal("1.0"),
                      "SEVERE": Decimal("1.25"), "CRITICAL": Decimal("1.5")}
SPECIALIST_RATE_UNITS = {"MINIMAL": 1, "MODERATE": 2, "SEVERE": 3, "CRITICAL": 4}
CONSULT_BASE_UNITS = Decimal("2")
FOLLOWUP_WINDOW_MINUTES = 30
FOLLOWUP_RETRY_INTERVAL_HOURS = 6
FOLLOWUP_SPECIALIST_BUFFER_MINUTES = 15
CO_INGESTANT_MULTIPLIER = Decimal("1.15")

TWO = Decimal("0.01")


# ---------------------------------------------------------------------------
# Decimal / datetime helpers
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def round2(d):
    return d.quantize(TWO, rounding=ROUND_HALF_UP)


def to_num(d):
    """Convert a stored Decimal to a JSON-friendly number."""
    if d is None:
        return None
    if isinstance(d, Decimal):
        f = float(d)
        return int(f) if f.is_integer() else f
    return d


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(),
         "api_request_timestamp": datetime.now(timezone.utc).strftime(
             "%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, pagination=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": _meta(pagination), "response_type": rtype, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_RESOURCE_NOT_FOUND", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return uid, role


def require(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise_err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing / field validation
# ---------------------------------------------------------------------------
def get_body():
    if request.data and request.data.strip():
        body = request.get_json(silent=True)
        if body is None or not isinstance(body, dict):
            raise_err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return body
    return {}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, field):
    if field not in body or not isinstance(body[field], str):
        raise_err(errors.ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return body[field]


def req_enum(body, field, allowed):
    if field not in body or not isinstance(body[field], str) or body[field] not in allowed:
        raise_err(errors.ERR_INVALID_REQUEST, f"Missing or invalid enum: {field}")
    return body[field]


def req_number(body, field):
    if field not in body or not _is_number(body[field]):
        raise_err(errors.ERR_INVALID_REQUEST, f"Missing or invalid number: {field}")
    return body[field]


def req_int(body, field):
    if field not in body or not isinstance(body[field], int) or isinstance(body[field], bool):
        raise_err(errors.ERR_INVALID_REQUEST, f"Missing or invalid integer: {field}")
    return body[field]


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise_err(errors.ERR_INVALID_REQUEST, f"Invalid boolean: {field}")
    return body[field]


def req_dt(body, field):
    if field not in body or not isinstance(body[field], str):
        raise_err(errors.ERR_INVALID_REQUEST, f"Missing or invalid datetime: {field}")
    dt = parse_dt(body[field])
    if dt is None:
        raise_err(errors.ERR_INVALID_REQUEST, f"Invalid datetime: {field}")
    return dt


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def stamp_new(entity, with_version=True):
    now = db.now()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["_seq"] = db.next_seq()
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = db.now()
    entity["version"] = entity.get("version", 1) + 1


def common_out(entity, with_version=True):
    out = {"id": entity["id"], "created_at": fmt_dt(entity["created_at"])}
    if with_version:
        out["updated_at"] = fmt_dt(entity["updated_at"])
        out["version"] = entity["version"]
    return out


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise_err(errors.ERR_VALIDATION, "Invalid pagination parameters")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return page, meta


# ---------------------------------------------------------------------------
# Cross-entity computed helpers
# ---------------------------------------------------------------------------
def active_assessment(case_id):
    cands = [a for a in db.risk_assessments.values()
             if a["case_id"] == case_id and a["status"] != "SUPERSEDED"]
    if not cands:
        return None
    return max(cands, key=lambda a: a["_seq"])


def active_disposition(case_id):
    cands = [d for d in db.dispositions.values()
             if d["case_id"] == case_id and d["status"] == "ACTIVE"]
    if not cands:
        return None
    return max(cands, key=lambda d: d["_seq"])


def case_exposures(case_id):
    return [e for e in db.exposures.values() if e["case_id"] == case_id]


def case_calls(case_id):
    return [c for c in db.follow_up_calls.values() if c["case_id"] == case_id]


def case_pending_followups(case_id):
    return sum(1 for c in db.follow_up_calls.values()
               if c["case_id"] == case_id and c["status"] in ("SCHEDULED", "ATTEMPTED"))


def case_risk_tier(case_id):
    a = active_assessment(case_id)
    return a["risk_tier"] if a else None


def substance_case_count(sub_id):
    return sum(1 for r in db.npds_reports.values()
               if r["primary_substance_id"] == sub_id and r["report_status"] == "SUBMITTED")


def facility_active_consults(fac_id):
    return sum(1 for c in db.facility_consults.values()
               if c["facility_id"] == fac_id and c["status"] == "ACTIVE")


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def band(score):
    if score < Decimal("0.25"):
        return "MINIMAL"
    if score < Decimal("0.75"):
        return "MODERATE"
    if score < Decimal("1.5"):
        return "SEVERE"
    return "CRITICAL"


def compute_toxicity(exposure, case, substance):
    route = exposure["route"]
    bioavail = ROUTE_BIOAVAILABILITY[route]
    if exposure.get("confirmed_dose_mg") is not None:
        dose_mg = D(exposure["confirmed_dose_mg"])
    else:
        dose_mg = D(exposure["dose_range_high_mg"])
    eff_dose = dose_mg * bioavail
    dose_per_kg = eff_dose / D(case["patient_weight_kg"])
    dose_ratio = dose_per_kg / D(substance["toxic_dose_mg_per_kg"])
    onset = D(substance["onset_hours"])
    tse = D(exposure["time_since_exposure_hours"])
    if tse <= onset:
        time_factor = Decimal("1.0")
    else:
        windows = int(((tse - onset) / onset).quantize(Decimal("1"), rounding=ROUND_FLOOR))
        time_factor = Decimal("1.0") - Decimal("0.1") * windows
        if time_factor < Decimal("0.5"):
            time_factor = Decimal("0.5")
    score = round2(dose_ratio * time_factor)
    return score, band(score)


def recompute_exposure(exposure):
    case = db.cases[exposure["case_id"]]
    substance = db.substances.get(exposure["substance_id"])
    if substance is None:
        return
    score, sb = compute_toxicity(exposure, case, substance)
    exposure["toxicity_score"] = score
    exposure["severity_band"] = sb


def compute_aggregate(case_id):
    exps = case_exposures(case_id)
    scores = [e["toxicity_score"] for e in exps]
    agg_max = max(scores)
    tier = band(agg_max)
    contribs = []
    count_ge = 0
    for e in exps:
        s = e["toxicity_score"]
        w = INTERACTION_WEIGHT[band(s)]
        contribs.append(round2(s * w))
        if s >= Decimal("0.25"):
            count_ge += 1
    mult = CO_INGESTANT_MULTIPLIER if count_ge >= 2 else Decimal("1.00")
    total = sum(contribs, Decimal("0"))
    agg_add = round2(total * mult)
    return agg_max, agg_add, tier


def select_protocol(tier):
    cands = [p for p in db.protocols.values() if p["risk_tier"] == tier]
    if not cands:
        return None
    cands.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return cands[0]["id"]


def compute_billing(consult, case):
    tier = case_risk_tier(consult["case_id"])
    rate = SPECIALIST_RATE_UNITS.get(tier, 0)
    specialist_units = round2(D(rate) * D(consult["consult_duration_minutes"]) / D(60))
    gross = round2(CONSULT_BASE_UNITS + specialist_units)
    if gross < Decimal("5"):
        discount = Decimal("0.00")
    elif gross < Decimal("10"):
        discount = Decimal("0.10")
    else:
        discount = Decimal("0.20")
    return round2(gross * (Decimal("1") - discount))


def npds_outcome(add):
    if add < Decimal("0.5"):
        return "MINOR"
    if add < Decimal("1.5"):
        return "MODERATE"
    return "MAJOR"


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_substance(s):
    out = common_out(s)
    out.update({"name": s["name"], "category": s["category"],
                "toxic_dose_mg_per_kg": s["toxic_dose_mg_per_kg"],
                "onset_hours": s["onset_hours"], "reference_route": s["reference_route"],
                "aggregate_case_count": substance_case_count(s["id"])})
    return out


def ser_facility(f):
    out = common_out(f)
    out.update({"name": f["name"], "facility_type": f["facility_type"],
                "status": f["status"], "consult_capacity": f["consult_capacity"],
                "active_consult_count": facility_active_consults(f["id"])})
    return out


def ser_protocol(p):
    out = common_out(p)
    out.update({"risk_tier": p["risk_tier"], "management_setting": p["management_setting"],
                "followup_count": p["followup_count"],
                "followup_interval_hours": p["followup_interval_hours"],
                "requires_toxicologist": p["requires_toxicologist"]})
    return out


def ser_specialist(s):
    out = common_out(s)
    out.update({"full_name": s["full_name"], "credential": s["credential"],
                "certification_active": s["certification_active"]})
    return out


def ser_case(c):
    out = common_out(c)
    out.update({"patient_age_years": c["patient_age_years"],
                "patient_weight_kg": c["patient_weight_kg"],
                "patient_sex": c["patient_sex"], "chief_complaint": c["chief_complaint"],
                "interpreter_required": c["interpreter_required"],
                "interpreter_language": c["interpreter_language"],
                "intake_specialist_id": c["intake_specialist_id"],
                "status": c["status"], "risk_tier": case_risk_tier(c["id"]),
                "pending_followup_count": case_pending_followups(c["id"]),
                "resolved_at": fmt_dt(c["resolved_at"])})
    return out


def ser_exposure(e):
    out = common_out(e)
    out.update({"case_id": e["case_id"], "substance_id": e["substance_id"],
                "route": e["route"], "dose_range_low_mg": e["dose_range_low_mg"],
                "dose_range_high_mg": e["dose_range_high_mg"],
                "time_since_exposure_hours": e["time_since_exposure_hours"],
                "confirmed_dose_mg": to_num(e["confirmed_dose_mg"]),
                "identified": e["identified"],
                "toxicity_score": to_num(e["toxicity_score"]),
                "severity_band": e["severity_band"]})
    return out


def ser_assessment(a):
    out = common_out(a)
    out.update({"case_id": a["case_id"], "protocol_id": a["protocol_id"],
                "aggregate_score_max": to_num(a["aggregate_score_max"]),
                "aggregate_score_additive": to_num(a["aggregate_score_additive"]),
                "risk_tier": a["risk_tier"], "status": a["status"]})
    return out


def ser_disposition(d):
    out = common_out(d)
    out.update({"case_id": d["case_id"], "risk_assessment_id": d["risk_assessment_id"],
                "disposition_type": d["disposition_type"], "facility_id": d["facility_id"],
                "status": d["status"]})
    return out


def ser_call(c):
    out = common_out(c)
    out.update({"case_id": c["case_id"], "assigned_specialist_id": c["assigned_specialist_id"],
                "sequence_index": c["sequence_index"],
                "scheduled_start": fmt_dt(c["scheduled_start"]),
                "scheduled_end": fmt_dt(c["scheduled_end"]),
                "attempt_count": c["attempt_count"], "status": c["status"],
                "outcome": c["outcome"]})
    return out


def ser_consult(c):
    out = common_out(c)
    out.update({"case_id": c["case_id"], "facility_id": c["facility_id"],
                "requesting_specialist_id": c["requesting_specialist_id"],
                "consult_duration_minutes": c["consult_duration_minutes"],
                "confirmed_dose_mg": to_num(c["confirmed_dose_mg"]),
                "billing_units": to_num(c["billing_units"]), "status": c["status"]})
    return out


def ser_report(r):
    out = common_out(r)
    out.update({"case_id": r["case_id"], "primary_substance_id": r["primary_substance_id"],
                "medical_outcome": r["medical_outcome"], "report_status": r["report_status"],
                "reported_at": fmt_dt(r["reported_at"])})
    return out


def ser_note(n):
    out = common_out(n, with_version=False)
    out.update({"case_id": n["case_id"], "author_ref": n["author_ref"],
                "note_type": n["note_type"], "body": n["body"]})
    return out


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_case_or_404(case_id):
    c = db.cases.get(case_id)
    if c is None:
        raise_err(errors.ERR_CASE_NOT_FOUND, "Exposure case not found")
    return c


def get_or_resource_404(store, rid):
    obj = store.get(rid)
    if obj is None:
        raise_err(errors.ERR_RESOURCE_NOT_FOUND, "Resource not found")
    return obj


# ===========================================================================
# Config endpoints (SystemAdmin)
# ===========================================================================
@app.route("/substances", methods=["POST"])
def create_substance():
    require({"SystemAdmin"})
    body = get_body()
    name = req_str(body, "name")
    category = req_enum(body, "category", SUBSTANCE_CATEGORIES)
    toxic = req_number(body, "toxic_dose_mg_per_kg")
    onset = req_number(body, "onset_hours")
    route = req_enum(body, "reference_route", ROUTES)
    if toxic <= 0:
        raise_err(errors.ERR_VALIDATION, "toxic_dose_mg_per_kg must be > 0")
    if onset <= 0:
        raise_err(errors.ERR_VALIDATION, "onset_hours must be > 0")
    s = {"name": name, "category": category, "toxic_dose_mg_per_kg": toxic,
         "onset_hours": onset, "reference_route": route}
    stamp_new(s)
    db.substances[s["id"]] = s
    return ok(ser_substance(s), 201)


@app.route("/substances/<sid>", methods=["GET"])
def get_substance(sid):
    require({"SystemAdmin", "Specialist", "Toxicologist", "SurveillanceOfficer"})
    s = get_or_resource_404(db.substances, sid)
    return ok(ser_substance(s), 200)


@app.route("/healthcare-facilities", methods=["POST"])
def create_facility():
    require({"SystemAdmin"})
    body = get_body()
    name = req_str(body, "name")
    ftype = req_enum(body, "facility_type", FACILITY_TYPES)
    status = body.get("status", "ACCEPTING")
    if status is None:
        status = "ACCEPTING"
    if status not in FACILITY_STATUSES:
        raise_err(errors.ERR_INVALID_REQUEST, "Invalid facility status")
    capacity = req_int(body, "consult_capacity")
    if capacity < 1:
        raise_err(errors.ERR_VALIDATION, "consult_capacity must be >= 1")
    f = {"name": name, "facility_type": ftype, "status": status,
         "consult_capacity": capacity}
    stamp_new(f)
    db.facilities[f["id"]] = f
    return ok(ser_facility(f), 201)


@app.route("/healthcare-facilities/<fid>", methods=["GET"])
def get_facility(fid):
    require({"SystemAdmin", "Specialist", "Toxicologist", "SurveillanceOfficer"})
    f = get_or_resource_404(db.facilities, fid)
    return ok(ser_facility(f), 200)


@app.route("/protocols", methods=["POST"])
def create_protocol():
    require({"SystemAdmin"})
    body = get_body()
    tier = req_enum(body, "risk_tier", RISK_TIERS)
    setting = req_enum(body, "management_setting", MANAGEMENT_SETTINGS)
    fcount = req_int(body, "followup_count")
    finterval = req_number(body, "followup_interval_hours")
    requires_tox = opt_bool(body, "requires_toxicologist", False)
    if fcount < 0:
        raise_err(errors.ERR_VALIDATION, "followup_count must be >= 0")
    if finterval <= 0:
        raise_err(errors.ERR_VALIDATION, "followup_interval_hours must be > 0")
    p = {"risk_tier": tier, "management_setting": setting, "followup_count": fcount,
         "followup_interval_hours": finterval, "requires_toxicologist": requires_tox}
    stamp_new(p)
    db.protocols[p["id"]] = p
    return ok(ser_protocol(p), 201)


@app.route("/specialists", methods=["POST"])
def create_specialist():
    require({"SystemAdmin"})
    body = get_body()
    full_name = req_str(body, "full_name")
    credential = req_enum(body, "credential", CREDENTIALS)
    cert_active = opt_bool(body, "certification_active", True)
    s = {"full_name": full_name, "credential": credential,
         "certification_active": cert_active}
    stamp_new(s)
    db.specialists[s["id"]] = s
    return ok(ser_specialist(s), 201)


# ===========================================================================
# Exposure cases
# ===========================================================================
@app.route("/exposure-cases", methods=["POST"])
def create_case():
    uid, role = require({"Specialist", "Toxicologist"})
    body = get_body()
    age = req_number(body, "patient_age_years")
    weight = req_number(body, "patient_weight_kg")
    sex = req_enum(body, "patient_sex", PATIENT_SEXES)
    complaint = req_str(body, "chief_complaint")
    interp_required = opt_bool(body, "interpreter_required", False)
    interp_lang = body.get("interpreter_language")
    if interp_lang is not None and not isinstance(interp_lang, str):
        raise_err(errors.ERR_INVALID_REQUEST, "Invalid interpreter_language")
    if age < 0:
        raise_err(errors.ERR_VALIDATION, "patient_age_years must be >= 0")
    if weight <= 0:
        raise_err(errors.ERR_VALIDATION, "patient_weight_kg must be > 0")
    if interp_required and not interp_lang:
        raise_err(errors.ERR_INTERPRETER_LANGUAGE_REQUIRED,
                  "interpreter_language required when interpreter_required is true")
    c = {"patient_age_years": age, "patient_weight_kg": weight, "patient_sex": sex,
         "chief_complaint": complaint, "interpreter_required": interp_required,
         "interpreter_language": interp_lang if interp_lang is not None else None,
         "intake_specialist_id": uid, "status": "INTAKE", "resolved_at": None}
    stamp_new(c)
    db.cases[c["id"]] = c
    return ok(ser_case(c), 201)


@app.route("/exposure-cases/<cid>", methods=["GET"])
def get_case(cid):
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    c = get_case_or_404(cid)
    return ok(ser_case(c), 200)


@app.route("/exposure-cases", methods=["GET"])
def list_cases():
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    items = list(db.cases.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    intake = request.args.get("intake_specialist_id")
    if intake is not None:
        items = [c for c in items if c["intake_specialist_id"] == intake]
    page, meta = paginate(items)
    return ok([ser_case(c) for c in page], 200, meta)


@app.route("/exposure-cases/<cid>/triage", methods=["POST"])
def triage_case(cid):
    require({"Specialist", "Toxicologist"})
    c = get_case_or_404(cid)
    if c["status"] != "INTAKE":
        raise_err(errors.ERR_INVALID_STATE, "Case is not in INTAKE")
    exps = case_exposures(cid)
    if len(exps) < 1:
        raise_err(errors.ERR_NO_EXPOSURES, "Case has no exposures")
    if not all(e["identified"] for e in exps):
        raise_err(errors.ERR_VALIDATION, "All exposures must be identified")
    c["status"] = "TRIAGED"
    touch(c)
    return ok(ser_case(c), 200)


@app.route("/exposure-cases/<cid>/close", methods=["POST"])
def close_case(cid):
    uid, role = require({"Specialist", "Toxicologist"})
    c = get_case_or_404(cid)
    if c["status"] == "RESOLVED":
        # any Specialist/Toxicologist may close a resolved case
        pass
    elif c["status"] == "REFERRED":
        # only Toxicologist may close a referred case, and its consult must be terminal
        if role != "Toxicologist":
            raise_err(errors.ERR_INVALID_STATE, "Referred case requires Toxicologist to close")
        consults = [x for x in db.facility_consults.values() if x["case_id"] == cid]
        if not all(x["status"] in ("CLOSED", "CANCELLED") for x in consults):
            raise_err(errors.ERR_INVALID_STATE, "Facility consult not yet closed/cancelled")
    else:
        raise_err(errors.ERR_INVALID_STATE, "Case cannot be closed from its current state")
    # cancel any still-scheduled/attempted follow-ups
    for call in case_calls(cid):
        if call["status"] in ("SCHEDULED", "ATTEMPTED"):
            call["status"] = "CANCELLED"
            touch(call)
    c["status"] = "CLOSED"
    touch(c)
    return ok(ser_case(c), 200)


# ===========================================================================
# Exposures
# ===========================================================================
@app.route("/exposure-cases/<cid>/exposures", methods=["POST"])
def create_exposure(cid):
    require({"Specialist", "Toxicologist"})
    c = get_case_or_404(cid)
    body = get_body()
    substance_id = req_str(body, "substance_id")
    route = req_enum(body, "route", ROUTES)
    low = req_number(body, "dose_range_low_mg")
    high = req_number(body, "dose_range_high_mg")
    tse = req_number(body, "time_since_exposure_hours")
    if low < 0:
        raise_err(errors.ERR_VALIDATION, "dose_range_low_mg must be >= 0")
    if high < low:
        raise_err(errors.ERR_VALIDATION, "dose_range_high_mg must be >= dose_range_low_mg")
    if tse < 0:
        raise_err(errors.ERR_VALIDATION, "time_since_exposure_hours must be >= 0")
    substance = db.substances.get(substance_id)
    if substance is None:
        raise_err(errors.ERR_REFERENCE_NOT_FOUND, "Substance not found")
    e = {"case_id": cid, "substance_id": substance_id, "route": route,
         "dose_range_low_mg": low, "dose_range_high_mg": high,
         "time_since_exposure_hours": tse, "confirmed_dose_mg": None,
         "identified": True, "toxicity_score": Decimal("0"), "severity_band": "MINIMAL"}
    stamp_new(e)
    recompute_exposure(e)
    db.exposures[e["id"]] = e
    # adding an exposure to a MONITORING case triggers RETRIAGE
    if c["status"] == "MONITORING":
        a = active_assessment(cid)
        if a is not None:
            a["status"] = "SUPERSEDED"
            touch(a)
        d = active_disposition(cid)
        if d is not None:
            d["status"] = "SUPERSEDED"
            touch(d)
        c["status"] = "RETRIAGE"
    # adding an exposure advances the case version (OCC)
    touch(c)
    return ok(ser_exposure(e), 201)


@app.route("/exposures/<eid>", methods=["GET"])
def get_exposure(eid):
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    e = get_or_resource_404(db.exposures, eid)
    return ok(ser_exposure(e), 200)


@app.route("/exposures", methods=["GET"])
def list_exposures():
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    items = list(db.exposures.values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [e for e in items if e["case_id"] == cid]
    sid = request.args.get("substance_id")
    if sid is not None:
        items = [e for e in items if e["substance_id"] == sid]
    page, meta = paginate(items)
    return ok([ser_exposure(e) for e in page], 200, meta)


# ===========================================================================
# Risk assessments
# ===========================================================================
@app.route("/exposure-cases/<cid>/risk-assessments", methods=["POST"])
def create_assessment(cid):
    require({"Specialist", "Toxicologist"})
    c = get_case_or_404(cid)
    body = get_body()
    expected = req_int(body, "expected_case_version")
    if c["status"] not in ("TRIAGED", "RETRIAGE"):
        raise_err(errors.ERR_INVALID_STATE, "Case is not in a state permitting risk assessment")
    if expected != c["version"]:
        raise_err(errors.ERR_STALE_CASE_VERSION, "Case version is stale")
    exps = case_exposures(cid)
    if len(exps) < 1:
        raise_err(errors.ERR_NO_EXPOSURES, "Case has no exposures")
    agg_max, agg_add, tier = compute_aggregate(cid)
    protocol_id = select_protocol(tier)
    # supersede prior active assessment
    prior = active_assessment(cid)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    a = {"case_id": cid, "protocol_id": protocol_id, "aggregate_score_max": agg_max,
         "aggregate_score_additive": agg_add, "risk_tier": tier, "status": "COMPLETED"}
    stamp_new(a)
    db.risk_assessments[a["id"]] = a
    # advance case version by one
    touch(c)
    return ok(ser_assessment(a), 201)


@app.route("/risk-assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    a = get_or_resource_404(db.risk_assessments, aid)
    return ok(ser_assessment(a), 200)


@app.route("/risk-assessments", methods=["GET"])
def list_assessments():
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    items = list(db.risk_assessments.values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [a for a in items if a["case_id"] == cid]
    pid = request.args.get("protocol_id")
    if pid is not None:
        items = [a for a in items if a["protocol_id"] == pid]
    page, meta = paginate(items)
    return ok([ser_assessment(a) for a in page], 200, meta)


@app.route("/risk-assessments/<aid>/finalize", methods=["POST"])
def finalize_assessment(aid):
    uid, role = require({"Specialist", "Toxicologist"})
    a = get_or_resource_404(db.risk_assessments, aid)
    if a["status"] != "COMPLETED":
        raise_err(errors.ERR_INVALID_STATE, "Assessment is not COMPLETED")
    protocol = db.protocols.get(a["protocol_id"]) if a["protocol_id"] else None
    if protocol is not None and protocol["requires_toxicologist"] and role != "Toxicologist":
        raise_err(errors.ERR_TOXICOLOGIST_REQUIRED, "Toxicologist role required to finalize")
    if a["protocol_id"] is None:
        raise_err(errors.ERR_NO_PROTOCOL, "No protocol matched the assessment's risk tier")
    a["status"] = "FINALIZED"
    touch(a)
    return ok(ser_assessment(a), 200)


# ===========================================================================
# Dispositions
# ===========================================================================
@app.route("/exposure-cases/<cid>/dispositions", methods=["POST"])
def create_disposition(cid):
    require({"Specialist", "Toxicologist"})
    c = get_case_or_404(cid)
    body = get_body()
    ra_id = req_str(body, "risk_assessment_id")
    dtype = req_enum(body, "disposition_type", DISPOSITION_TYPES)
    facility_id = body.get("facility_id")
    if facility_id is not None and not isinstance(facility_id, str):
        raise_err(errors.ERR_INVALID_REQUEST, "Invalid facility_id")
    # FK existence: risk_assessment (must belong to case)
    assessment = db.risk_assessments.get(ra_id)
    if assessment is None or assessment["case_id"] != cid:
        raise_err(errors.ERR_REFERENCE_NOT_FOUND, "Risk assessment not found")
    # FK existence: facility (if provided)
    if facility_id is not None:
        if db.facilities.get(facility_id) is None:
            raise_err(errors.ERR_REFERENCE_NOT_FOUND, "Facility not found")
    # state: case must be TRIAGED or RETRIAGE
    if c["status"] not in ("TRIAGED", "RETRIAGE"):
        raise_err(errors.ERR_INVALID_STATE, "Case is not in a state permitting disposition")
    # referenced assessment must be FINALIZED
    if assessment["status"] != "FINALIZED":
        raise_err(errors.ERR_INVALID_STATE, "Referenced risk assessment is not FINALIZED")
    # safety gate (checked before facility-pairing)
    if dtype == "HOME_MANAGEMENT" and assessment["risk_tier"] not in ("MINIMAL", "MODERATE"):
        raise_err(errors.ERR_UNSAFE_DISPOSITION, "Home management not allowed for this risk tier")
    # facility-pairing rule
    if dtype == "ED_REFERRAL" and facility_id is None:
        raise_err(errors.ERR_DISPOSITION_FACILITY_MISMATCH, "ED_REFERRAL requires facility_id")
    if dtype == "HOME_MANAGEMENT" and facility_id is not None:
        raise_err(errors.ERR_DISPOSITION_FACILITY_MISMATCH, "HOME_MANAGEMENT must not have facility_id")
    # supersede prior active disposition
    prior = active_disposition(cid)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    d = {"case_id": cid, "risk_assessment_id": ra_id, "disposition_type": dtype,
         "facility_id": facility_id if facility_id is not None else None, "status": "ACTIVE"}
    stamp_new(d)
    db.dispositions[d["id"]] = d
    if dtype == "HOME_MANAGEMENT":
        c["status"] = "MONITORING"
        _run_followup_schedule(c, assessment)
    else:
        c["status"] = "REFERRED"
    touch(c)
    return ok(ser_disposition(d), 201)


def _run_followup_schedule(case, assessment):
    protocol = db.protocols.get(assessment["protocol_id"]) if assessment["protocol_id"] else None
    if protocol is None:
        return
    n = protocol["followup_count"]
    interval = protocol["followup_interval_hours"]
    now = db.now()
    for i in range(n):
        start = now + timedelta(hours=float(interval) * (i + 1))
        end = start + timedelta(minutes=FOLLOWUP_WINDOW_MINUTES)
        call = {"case_id": case["id"], "assigned_specialist_id": case["intake_specialist_id"],
                "sequence_index": i, "scheduled_start": start, "scheduled_end": end,
                "attempt_count": 0, "status": "SCHEDULED", "outcome": None}
        stamp_new(call)
        db.follow_up_calls[call["id"]] = call


@app.route("/dispositions/<did>", methods=["GET"])
def get_disposition(did):
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    d = get_or_resource_404(db.dispositions, did)
    return ok(ser_disposition(d), 200)


@app.route("/dispositions", methods=["GET"])
def list_dispositions():
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    items = list(db.dispositions.values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [d for d in items if d["case_id"] == cid]
    ra = request.args.get("risk_assessment_id")
    if ra is not None:
        items = [d for d in items if d["risk_assessment_id"] == ra]
    fac = request.args.get("facility_id")
    if fac is not None:
        items = [d for d in items if d["facility_id"] == fac]
    page, meta = paginate(items)
    return ok([ser_disposition(d) for d in page], 200, meta)


# ===========================================================================
# Follow-up calls
# ===========================================================================
def _intervals_overlap_halfopen(s1, e1, s2, e2):
    # half-open [s,e): conflict when they share any instant; adjacency allowed
    return s1 < e2 and s2 < e1


def _gap_minutes(s1, e1, s2, e2):
    # gap between two closed intervals; negative/zero if they touch or overlap
    if s1 >= e2:
        return (s1 - e2).total_seconds() / 60.0
    if s2 >= e1:
        return (s2 - e1).total_seconds() / 60.0
    return -1.0  # overlapping


@app.route("/exposure-cases/<cid>/follow-up-calls", methods=["POST"])
def create_followup(cid):
    require({"Specialist", "Toxicologist"})
    c = get_case_or_404(cid)
    body = get_body()
    spec_id = req_str(body, "assigned_specialist_id")
    seq = req_int(body, "sequence_index")
    start = req_dt(body, "scheduled_start")
    end = req_dt(body, "scheduled_end")
    if seq < 0:
        raise_err(errors.ERR_VALIDATION, "sequence_index must be >= 0")
    # 1) case-overlap (half-open)
    for other in case_calls(cid):
        if other["status"] in ("SCHEDULED", "ATTEMPTED"):
            if _intervals_overlap_halfopen(start, end, other["scheduled_start"], other["scheduled_end"]):
                raise_err(errors.ERR_FOLLOWUP_OVERLAP, "Follow-up window overlaps an existing call")
    # 2) specialist double-booking (closed interval + 15-minute buffer, across all cases)
    for other in db.follow_up_calls.values():
        if other["assigned_specialist_id"] == spec_id and other["status"] in ("SCHEDULED", "ATTEMPTED"):
            gap = _gap_minutes(start, end, other["scheduled_start"], other["scheduled_end"])
            if gap < FOLLOWUP_SPECIALIST_BUFFER_MINUTES:
                raise_err(errors.ERR_SPECIALIST_DOUBLE_BOOKED,
                          "Assigned specialist is double-booked")
    # 3) window well-formedness
    if not (end > start):
        raise_err(errors.ERR_INVALID_WINDOW, "scheduled_end must be after scheduled_start")
    call = {"case_id": cid, "assigned_specialist_id": spec_id, "sequence_index": seq,
            "scheduled_start": start, "scheduled_end": end, "attempt_count": 0,
            "status": "SCHEDULED", "outcome": None}
    stamp_new(call)
    db.follow_up_calls[call["id"]] = call
    return ok(ser_call(call), 201)


@app.route("/follow-up-calls/<fid>", methods=["GET"])
def get_followup(fid):
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    call = get_or_resource_404(db.follow_up_calls, fid)
    return ok(ser_call(call), 200)


@app.route("/follow-up-calls", methods=["GET"])
def list_followups():
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    items = list(db.follow_up_calls.values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [c for c in items if c["case_id"] == cid]
    spec = request.args.get("assigned_specialist_id")
    if spec is not None:
        items = [c for c in items if c["assigned_specialist_id"] == spec]
    page, meta = paginate(items)
    return ok([ser_call(c) for c in page], 200, meta)


@app.route("/follow-up-calls/<fid>/attempt", methods=["POST"])
def attempt_followup(fid):
    require({"Specialist", "Toxicologist"})
    call = get_or_resource_404(db.follow_up_calls, fid)
    case = db.cases.get(call["case_id"])
    if call["status"] != "SCHEDULED" or (case and case["status"] == "CLOSED"):
        raise_err(errors.ERR_INVALID_STATE, "Call cannot be attempted")
    call["attempt_count"] += 1
    call["status"] = "ATTEMPTED"
    touch(call)
    return ok(ser_call(call), 200)


@app.route("/follow-up-calls/<fid>/complete", methods=["POST"])
def complete_followup(fid):
    require({"Specialist", "Toxicologist"})
    call = get_or_resource_404(db.follow_up_calls, fid)
    body = get_body()
    outcome = req_enum(body, "outcome", COMPLETE_OUTCOMES)
    if call["status"] != "ATTEMPTED":
        raise_err(errors.ERR_INVALID_STATE, "Call is not ATTEMPTED")
    case = db.cases[call["case_id"]]
    if outcome == "NO_ANSWER" and call["attempt_count"] < 3:
        # revert to SCHEDULED, push window forward by retry interval from now
        now = db.now()
        duration = call["scheduled_end"] - call["scheduled_start"]
        call["scheduled_start"] = now + timedelta(hours=FOLLOWUP_RETRY_INTERVAL_HOURS)
        call["scheduled_end"] = call["scheduled_start"] + duration
        call["status"] = "SCHEDULED"
        touch(call)
        return ok(ser_call(call), 200)
    # terminal completion
    if outcome == "NO_ANSWER":
        call["outcome"] = "LOST_TO_FOLLOWUP"
    else:
        call["outcome"] = outcome
    call["status"] = "COMPLETED"
    touch(call)
    if outcome == "WORSENED":
        # drive case to RETRIAGE, superseding active assessment + disposition
        a = active_assessment(case["id"])
        if a is not None:
            a["status"] = "SUPERSEDED"
            touch(a)
        d = active_disposition(case["id"])
        if d is not None:
            d["status"] = "SUPERSEDED"
            touch(d)
        if case["status"] == "MONITORING":
            case["status"] = "RETRIAGE"
            touch(case)
    elif outcome == "RESOLVED":
        calls = case_calls(case["id"])
        all_terminal = all(x["status"] in ("COMPLETED", "CANCELLED") for x in calls)
        none_worsened = all(x["outcome"] != "WORSENED" for x in calls)
        if case["status"] == "MONITORING" and all_terminal and none_worsened:
            case["status"] = "RESOLVED"
            case["resolved_at"] = db.now()
            a = active_assessment(case["id"])
            if a is not None and a["status"] == "COMPLETED":
                a["status"] = "FINALIZED"
                touch(a)
            touch(case)
    return ok(ser_call(call), 200)


# ===========================================================================
# Facility consults
# ===========================================================================
@app.route("/facility-consults", methods=["POST"])
def create_consult():
    uid, role = require({"Toxicologist"})
    body = get_body()
    case_id = req_str(body, "case_id")
    facility_id = req_str(body, "facility_id")
    duration = req_number(body, "consult_duration_minutes")
    if duration <= 0:
        raise_err(errors.ERR_VALIDATION, "consult_duration_minutes must be > 0")
    case = db.cases.get(case_id)
    if case is None:
        raise_err(errors.ERR_REFERENCE_NOT_FOUND, "Case not found")
    facility = db.facilities.get(facility_id)
    if facility is None:
        raise_err(errors.ERR_REFERENCE_NOT_FOUND, "Facility not found")
    if facility["status"] != "ACCEPTING":
        raise_err(errors.ERR_FACILITY_NOT_ACCEPTING, "Facility is not accepting consults")
    if facility_active_consults(facility_id) >= facility["consult_capacity"]:
        raise_err(errors.ERR_FACILITY_AT_CAPACITY, "Facility is at consult capacity")
    consult = {"case_id": case_id, "facility_id": facility_id,
               "requesting_specialist_id": uid, "consult_duration_minutes": duration,
               "confirmed_dose_mg": None, "billing_units": Decimal("0"), "status": "ACTIVE"}
    stamp_new(consult)
    db.facility_consults[consult["id"]] = consult
    return ok(ser_consult(consult), 201)


@app.route("/facility-consults/<cid>", methods=["GET"])
def get_consult(cid):
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    consult = get_or_resource_404(db.facility_consults, cid)
    return ok(ser_consult(consult), 200)


@app.route("/facility-consults", methods=["GET"])
def list_consults():
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    items = list(db.facility_consults.values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [c for c in items if c["case_id"] == cid]
    fac = request.args.get("facility_id")
    if fac is not None:
        items = [c for c in items if c["facility_id"] == fac]
    spec = request.args.get("requesting_specialist_id")
    if spec is not None:
        items = [c for c in items if c["requesting_specialist_id"] == spec]
    page, meta = paginate(items)
    return ok([ser_consult(c) for c in page], 200, meta)


@app.route("/facility-consults/<cid>/close", methods=["POST"])
def close_consult(cid):
    require({"Toxicologist"})
    consult = get_or_resource_404(db.facility_consults, cid)
    body = get_body()
    confirmed = req_number(body, "confirmed_dose_mg")
    if consult["status"] != "ACTIVE":
        raise_err(errors.ERR_INVALID_STATE, "Consult is not ACTIVE")
    if confirmed < 0:
        raise_err(errors.ERR_VALIDATION, "confirmed_dose_mg must be >= 0")
    case = db.cases.get(consult["case_id"])
    # billing computed first, keyed on current (pre-recompute) risk tier
    consult["billing_units"] = compute_billing(consult, case)
    consult["confirmed_dose_mg"] = confirmed
    consult["status"] = "CLOSED"
    touch(consult)
    if case is not None:
        _close_consult_cascade(case, confirmed)
    return ok(ser_consult(consult), 200)


def _close_consult_cascade(case, confirmed):
    # hop 1: set confirmed dose on every exposure and recompute CONFIRMED variant
    for e in case_exposures(case["id"]):
        e["confirmed_dose_mg"] = confirmed
        recompute_exposure(e)
        touch(e)
    # hop 2: recompute active assessment aggregates + risk_tier
    a = active_assessment(case["id"])
    if a is not None and case_exposures(case["id"]):
        agg_max, agg_add, tier = compute_aggregate(case["id"])
        a["aggregate_score_max"] = agg_max
        a["aggregate_score_additive"] = agg_add
        a["risk_tier"] = tier
        touch(a)
    new_tier = a["risk_tier"] if a is not None else None
    # hop 3: escalation to CRITICAL from MONITORING
    escalated = False
    if new_tier == "CRITICAL" and case["status"] == "MONITORING":
        d = active_disposition(case["id"])
        if d is not None and d["disposition_type"] == "HOME_MANAGEMENT":
            d["status"] = "SUPERSEDED"
            touch(d)
        for call in case_calls(case["id"]):
            if call["status"] in ("SCHEDULED", "ATTEMPTED"):
                call["status"] = "CANCELLED"
                touch(call)
        case["status"] = "REFERRED"
        touch(case)
        escalated = True
    # settle: referred case whose consult closed with no home follow-ups scheduled -> RESOLVED
    if not escalated and case["status"] == "REFERRED":
        pending = case_pending_followups(case["id"])
        if pending == 0:
            case["status"] = "RESOLVED"
            case["resolved_at"] = db.now()
            touch(case)


# ===========================================================================
# NPDS reports
# ===========================================================================
@app.route("/npds-reports", methods=["POST"])
def create_report():
    require({"SurveillanceOfficer"})
    body = get_body()
    case_id = req_str(body, "case_id")
    substance_id = req_str(body, "primary_substance_id")
    case = db.cases.get(case_id)
    if case is None:
        raise_err(errors.ERR_REFERENCE_NOT_FOUND, "Case not found")
    substance = db.substances.get(substance_id)
    if substance is None:
        raise_err(errors.ERR_REFERENCE_NOT_FOUND, "Substance not found")
    a = active_assessment(case_id)
    if a is None:
        raise_err(errors.ERR_NO_ACTIVE_ASSESSMENT, "Case has no active risk assessment")
    outcome = npds_outcome(a["aggregate_score_additive"])
    r = {"case_id": case_id, "primary_substance_id": substance_id,
         "medical_outcome": outcome, "report_status": "SUBMITTED",
         "reported_at": db.now()}
    stamp_new(r)
    db.npds_reports[r["id"]] = r
    return ok(ser_report(r), 201)


@app.route("/npds-reports/<rid>", methods=["GET"])
def get_report(rid):
    require({"SurveillanceOfficer", "Toxicologist"})
    r = get_or_resource_404(db.npds_reports, rid)
    return ok(ser_report(r), 200)


@app.route("/npds-reports", methods=["GET"])
def list_reports():
    require({"SurveillanceOfficer", "Toxicologist"})
    items = list(db.npds_reports.values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [r for r in items if r["case_id"] == cid]
    sub = request.args.get("primary_substance_id")
    if sub is not None:
        items = [r for r in items if r["primary_substance_id"] == sub]
    page, meta = paginate(items)
    return ok([ser_report(r) for r in page], 200, meta)


@app.route("/npds-reports/<rid>/retract", methods=["POST"])
def retract_report(rid):
    require({"SurveillanceOfficer", "Toxicologist"})
    r = get_or_resource_404(db.npds_reports, rid)
    if r["report_status"] != "SUBMITTED":
        raise_err(errors.ERR_INVALID_STATE, "Report is not SUBMITTED")
    r["report_status"] = "RETRACTED"
    touch(r)
    return ok(ser_report(r), 200)


# ===========================================================================
# Case notes
# ===========================================================================
@app.route("/exposure-cases/<cid>/notes", methods=["POST"])
def create_note(cid):
    uid, role = require({"Specialist", "Toxicologist"})
    c = get_case_or_404(cid)
    body = get_body()
    note_type = req_enum(body, "note_type", NOTE_TYPES)
    note_body = req_str(body, "body")
    n = {"case_id": cid, "author_ref": uid, "note_type": note_type, "body": note_body}
    stamp_new(n, with_version=False)
    db.case_notes[n["id"]] = n
    return ok(ser_note(n), 201)


@app.route("/exposure-cases/<cid>/notes", methods=["GET"])
def list_notes(cid):
    require({"Specialist", "Toxicologist", "SurveillanceOfficer"})
    get_case_or_404(cid)
    items = [n for n in db.case_notes.values() if n["case_id"] == cid]
    page, meta = paginate(items)
    return ok([ser_note(n) for n in page], 200, meta)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require({"SystemAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        raise_err(errors.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    db.clock = dt
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
