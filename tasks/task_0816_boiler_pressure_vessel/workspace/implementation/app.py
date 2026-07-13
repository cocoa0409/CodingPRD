import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Logical clock
# =============================================================================
CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return CLOCK


# =============================================================================
# In-memory stores (start empty on every boot; no seeding)
# =============================================================================
jurisdictions = {}
insurance_companies = {}
owners = {}
inspectors = {}
vessels = {}
policies = {}
inspections = {}
reports = {}
deficiencies = {}
repair_orders = {}
fee_invoices = {}
certificates = {}
incidents = {}

NEXT_ORD = 0
JUR_SEQ = {}  # jurisdiction_id -> last assigned sequence number

ROLES = {"JurisdictionAdmin", "Owner", "Inspector"}

# =============================================================================
# Calculation constants
# =============================================================================
BASE_FEE_BY_CLASS = {"POWER_BOILER": 20000, "HEATING_BOILER": 10000, "PRESSURE_VESSEL": 15000}
DEFICIENCY_SURCHARGE_PER = 2500
INCIDENT_SPECIAL_SURCHARGE = 30000

BASE_BY_CLASS = {"POWER_BOILER": 30, "HEATING_BOILER": 15, "PRESSURE_VESSEL": 20}
CRIT_WEIGHT = 8
NONCRIT_WEIGHT = 3
INCIDENT_PENALTY_PER = 25
SUSPENDED_PENALTY = 40
CLEAN_BONUS = 10

INTERVAL_BY_CLASS = {"POWER_BOILER": 12, "HEATING_BOILER": 12, "PRESSURE_VESSEL": 24}

VESSEL_CLASSES = {"POWER_BOILER", "HEATING_BOILER", "PRESSURE_VESSEL"}
INSPECTOR_TYPES = {"JURISDICTION", "INSURANCE"}
INSPECTION_TYPES = {"INTERNAL", "EXTERNAL", "SPECIAL"}
DEFICIENCY_SEVERITIES = {"CRITICAL", "NON_CRITICAL"}
INCIDENT_SEVERITIES = {"MINOR", "CRITICAL"}
NONTERMINAL_DEF = {"OPEN", "UNDER_REPAIR", "REINSPECTION"}


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# =============================================================================
# Datetime helpers
# =============================================================================
def parse_dt(value):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def add_months(dt, months):
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    day = min(dt.day, days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


# =============================================================================
# Record helpers
# =============================================================================
def base_record(common=True):
    global NEXT_ORD
    r = {"id": str(uuid.uuid4()), "created_at": now(), "_ord": NEXT_ORD}
    NEXT_ORD += 1
    if common:
        r["updated_at"] = now()
        r["version"] = 1
    return r


def touch(record):
    record["updated_at"] = now()
    if "version" in record:
        record["version"] += 1


def ser(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        out[k] = fmt_dt(v) if isinstance(v, datetime) else v
    return out


# =============================================================================
# Response envelope
# =============================================================================
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": fmt_dt(now())}
    if extra:
        m.update(extra)
    return m


def respond_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_array(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return jsonify({"meta": _meta(meta_extra), "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# =============================================================================
# Auth / validation helpers
# =============================================================================
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "role not permitted")
    return role, uid


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", 400, "body must be an object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            err("ERR_INVALID_REQUEST", 400, f"missing required field: {f}")


def get_or_404(store, key):
    if key not in store:
        err("ERR_NOT_FOUND", 404, "resource not found")
    return store[key]


def check_enum(value, allowed, field):
    if value not in allowed:
        err("ERR_INVALID_REQUEST", 400, f"invalid value for {field}")


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            err("ERR_INVALID_REQUEST", 400, "invalid limit")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", 400, "limit out of range")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            err("ERR_INVALID_REQUEST", 400, "invalid offset")
        if offset < 0:
            err("ERR_INVALID_REQUEST", 400, "offset out of range")
    return limit, offset


def list_response(records):
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_ord"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return respond_array([ser(r) for r in page], limit, offset, total)


# =============================================================================
# Domain calculations
# =============================================================================
def mawp_tier(p):
    if p <= 15:
        return 0
    if p <= 150:
        return 4500
    if p <= 600:
        return 12000
    return 25000


def compute_fee(vessel, jurisdiction, noncrit_count, is_special, final):
    lines = [BASE_FEE_BY_CLASS[vessel["vessel_class"]], mawp_tier(vessel["mawp_psig"])]
    if final:
        lines.append(DEFICIENCY_SURCHARGE_PER * noncrit_count)
        lines.append(INCIDENT_SPECIAL_SURCHARGE if is_special else 0)
    else:
        lines.append(0)
        lines.append(0)
    admin = Decimal(str(jurisdiction["admin_fee_pct"]))
    total = 0
    for line in lines:
        if line == 0:
            continue
        per = (Decimal(line) * (Decimal(1) + admin)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(per)
    return total


def vessel_deficiencies(vid, states=None):
    result = []
    for d in deficiencies.values():
        if d["vessel_id"] != vid:
            continue
        if states is None or d["status"] in states:
            result.append(d)
    return result


def clean_bonus(vessel):
    vid = vessel["id"]
    terminal = [i for i in inspections.values()
                if i["vessel_id"] == vid and i.get("result_recorded_at") is not None]
    if not terminal:
        return 0
    latest = max(terminal, key=lambda i: (i["result_recorded_at"], i["_ord"]))
    if latest["status"] != "PASSED":
        return 0
    attached = [d for d in deficiencies.values() if d["inspection_id"] == latest["id"]]
    if len(attached) == 0:
        return CLEAN_BONUS
    return 0


def risk_variant(vessel, include_states):
    cls = vessel["vessel_class"]
    base = BASE_BY_CLASS[cls]
    age_days = (now() - vessel["installed_at"]).days
    age_years = age_days // 365
    if age_years < 5:
        age_factor = 0
    elif age_years < 15:
        age_factor = 10
    elif age_years < 30:
        age_factor = 20
    else:
        age_factor = 35
    defs = vessel_deficiencies(vessel["id"], include_states)
    crit = sum(1 for d in defs if d["severity"] == "CRITICAL")
    noncrit = sum(1 for d in defs if d["severity"] == "NON_CRITICAL")
    deficiency_weight = CRIT_WEIGHT * crit + NONCRIT_WEIGHT * noncrit
    cutoff = now() - timedelta(days=365)
    incident_count = sum(1 for i in incidents.values()
                         if i["vessel_id"] == vessel["id"] and cutoff <= i["occurred_at"] <= now())
    incident_penalty = INCIDENT_PENALTY_PER * incident_count
    bonus = clean_bonus(vessel)
    raw = base + age_factor + deficiency_weight + incident_penalty - bonus
    if vessel["service_status"] == "SUSPENDED":
        raw += SUSPENDED_PENALTY
    return max(0, min(100, raw))


def recompute_counts(vessel):
    nonterm = vessel_deficiencies(vessel["id"], NONTERMINAL_DEF)
    vessel["open_deficiency_count"] = len(nonterm)
    vessel["open_critical_deficiency_count"] = sum(1 for d in nonterm if d["severity"] == "CRITICAL")


def recompute_vessel(vessel):
    recompute_counts(vessel)
    vessel["risk_score_standard"] = risk_variant(vessel, {"OPEN", "UNDER_REPAIR"})
    vessel["risk_score_forecast"] = risk_variant(vessel, {"OPEN", "UNDER_REPAIR", "REINSPECTION"})


# =============================================================================
# Shared state-transition helpers
# =============================================================================
def revoke_certificate(cert):
    """ACTIVE -> REVOKED with cascade: cancel vessel's SCHEDULED non-SPECIAL
    inspections and clear vessel.current_certificate_id."""
    cert["status"] = "REVOKED"
    touch(cert)
    vessel = vessels.get(cert["vessel_id"])
    if vessel is not None:
        for insp in inspections.values():
            if (insp["vessel_id"] == vessel["id"]
                    and insp["status"] == "SCHEDULED"
                    and insp["inspection_type"] != "SPECIAL"):
                insp["status"] = "CANCELLED"
                touch(insp)
        if vessel.get("current_certificate_id") == cert["id"]:
            vessel["current_certificate_id"] = None


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    CLOCK = parse_dt(body["to_iso8601"])
    return respond_object({"now": fmt_dt(CLOCK)}, 200)


# =============================================================================
# Jurisdictions
# =============================================================================
@app.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["code", "name"])
    code = body["code"]
    if not isinstance(code, str) or len(code) != 2 or not code.isalpha() or not code.isupper():
        err("ERR_INVALID_REQUEST", 400, "code must be two uppercase letters")
    admin_fee_pct = body.get("admin_fee_pct", 0.075)
    if admin_fee_pct is None:
        admin_fee_pct = 0.075
    if not isinstance(admin_fee_pct, (int, float)) or isinstance(admin_fee_pct, bool):
        err("ERR_INVALID_REQUEST", 400, "admin_fee_pct must be a number")
    if admin_fee_pct < 0 or admin_fee_pct > 1:
        err("ERR_INVALID_REQUEST", 400, "admin_fee_pct out of range")
    interval_override = body.get("interval_months_override", None)
    if interval_override is not None:
        if not isinstance(interval_override, int) or isinstance(interval_override, bool) or interval_override < 1:
            err("ERR_INVALID_REQUEST", 400, "interval_months_override invalid")
    for j in jurisdictions.values():
        if j["code"] == code:
            err("ERR_DUPLICATE_UNIQUE_FIELD", 409, "duplicate jurisdiction code")
    r = base_record()
    r.update({
        "code": code,
        "name": body["name"],
        "admin_fee_pct": admin_fee_pct,
        "interval_months_override": interval_override,
        "collected_fees_cents": 0,
    })
    jurisdictions[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/jurisdictions", methods=["GET"])
def list_jurisdictions():
    authenticate(ROLES)
    items = list(jurisdictions.values())
    code = request.args.get("code")
    if code is not None:
        items = [j for j in items if j["code"] == code]
    return list_response(items)


@app.route("/jurisdictions/<jurisdiction_id>", methods=["GET"])
def get_jurisdiction(jurisdiction_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(jurisdictions, jurisdiction_id)), 200)


# =============================================================================
# Insurance companies
# =============================================================================
@app.route("/insurance-companies", methods=["POST"])
def create_insurance_company():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["name", "nb_accreditation_number"])
    for c in insurance_companies.values():
        if c["nb_accreditation_number"] == body["nb_accreditation_number"]:
            err("ERR_DUPLICATE_UNIQUE_FIELD", 409, "duplicate nb_accreditation_number")
    r = base_record()
    r.update({"name": body["name"], "nb_accreditation_number": body["nb_accreditation_number"]})
    insurance_companies[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/insurance-companies", methods=["GET"])
def list_insurance_companies():
    authenticate(ROLES)
    return list_response(list(insurance_companies.values()))


@app.route("/insurance-companies/<insurance_company_id>", methods=["GET"])
def get_insurance_company(insurance_company_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(insurance_companies, insurance_company_id)), 200)


# =============================================================================
# Owners
# =============================================================================
@app.route("/owners", methods=["POST"])
def create_owner():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["name", "contact_email"])
    r = base_record()
    r.update({"name": body["name"], "contact_email": body["contact_email"]})
    owners[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/owners", methods=["GET"])
def list_owners():
    authenticate(ROLES)
    return list_response(list(owners.values()))


@app.route("/owners/<owner_id>", methods=["GET"])
def get_owner(owner_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(owners, owner_id)), 200)


# =============================================================================
# Inspectors
# =============================================================================
@app.route("/inspectors", methods=["POST"])
def create_inspector():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["name", "commission_number", "inspector_type"])
    check_enum(body["inspector_type"], INSPECTOR_TYPES, "inspector_type")
    itype = body["inspector_type"]
    ins_co = body.get("insurance_company_id", None)
    comm_jur = body.get("commissioning_jurisdiction_id", None)
    if itype == "INSURANCE":
        if ins_co is None:
            err("ERR_INVALID_REQUEST", 400, "insurance_company_id required for INSURANCE inspector")
    else:  # JURISDICTION
        if ins_co is not None:
            err("ERR_INVALID_REQUEST", 400, "insurance_company_id must be null for JURISDICTION inspector")
    # body FK existence
    if ins_co is not None:
        get_or_404(insurance_companies, ins_co)
    if comm_jur is not None:
        get_or_404(jurisdictions, comm_jur)
    # uniqueness
    for i in inspectors.values():
        if i["commission_number"] == body["commission_number"]:
            err("ERR_DUPLICATE_UNIQUE_FIELD", 409, "duplicate commission_number")
    r = base_record()
    r.update({
        "name": body["name"],
        "commission_number": body["commission_number"],
        "inspector_type": itype,
        "insurance_company_id": ins_co,
        "commissioning_jurisdiction_id": comm_jur,
        "status": "PENDING",
    })
    inspectors[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/inspectors", methods=["GET"])
def list_inspectors():
    authenticate(ROLES)
    items = list(inspectors.values())
    for field in ("insurance_company_id", "commissioning_jurisdiction_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [i for i in items if i.get(field) == val]
    return list_response(items)


@app.route("/inspectors/<inspector_id>", methods=["GET"])
def get_inspector(inspector_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(inspectors, inspector_id)), 200)


@app.route("/inspectors/<inspector_id>/commission", methods=["POST"])
def commission_inspector(inspector_id):
    authenticate({"JurisdictionAdmin"})
    insp = get_or_404(inspectors, inspector_id)
    if insp["status"] not in ("PENDING", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "inspector cannot be commissioned from current state")
    if insp["status"] == "PENDING":
        if insp.get("commissioning_jurisdiction_id") is None:
            err("ERR_INVALID_STATE", 409, "commissioning_jurisdiction_id not set")
        if insp["inspector_type"] == "INSURANCE" and insp.get("insurance_company_id") is None:
            err("ERR_INVALID_STATE", 409, "insurance_company_id not set")
    insp["status"] = "COMMISSIONED"
    touch(insp)
    return respond_object(ser(insp), 200)


@app.route("/inspectors/<inspector_id>/suspend", methods=["POST"])
def suspend_inspector(inspector_id):
    authenticate({"JurisdictionAdmin"})
    insp = get_or_404(inspectors, inspector_id)
    if insp["status"] != "COMMISSIONED":
        err("ERR_INVALID_STATE", 409, "inspector not COMMISSIONED")
    insp["status"] = "SUSPENDED"
    touch(insp)
    return respond_object(ser(insp), 200)


# =============================================================================
# Vessels
# =============================================================================
@app.route("/vessels", methods=["POST"])
def create_vessel():
    role, uid = authenticate({"Owner"})
    body = get_body()
    require_fields(body, ["owner_id", "jurisdiction_id", "manufacturer",
                          "national_board_number", "vessel_class", "mawp_psig", "installed_at"])
    check_enum(body["vessel_class"], VESSEL_CLASSES, "vessel_class")
    mawp = body["mawp_psig"]
    if not isinstance(mawp, int) or isinstance(mawp, bool) or mawp < 1:
        err("ERR_INVALID_REQUEST", 400, "mawp_psig must be an integer >= 1")
    installed_at = parse_dt(body["installed_at"])
    # existence (body FKs, left to right)
    get_or_404(owners, body["owner_id"])
    get_or_404(jurisdictions, body["jurisdiction_id"])
    # ownership
    if body["owner_id"] != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "owner_id must equal caller id")
    # uniqueness
    for v in vessels.values():
        if v["national_board_number"] == body["national_board_number"]:
            err("ERR_DUPLICATE_UNIQUE_FIELD", 409, "duplicate national_board_number")
    r = base_record()
    r.update({
        "owner_id": body["owner_id"],
        "jurisdiction_id": body["jurisdiction_id"],
        "manufacturer": body["manufacturer"],
        "national_board_number": body["national_board_number"],
        "vessel_class": body["vessel_class"],
        "mawp_psig": mawp,
        "installed_at": installed_at,
        "jurisdiction_number": None,
        "registration_status": "DRAFT",
        "service_status": "NOT_IN_SERVICE",
        "current_certificate_id": None,
        "open_deficiency_count": 0,
        "open_critical_deficiency_count": 0,
        "risk_score_standard": None,
        "risk_score_forecast": None,
    })
    vessels[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/vessels", methods=["GET"])
def list_vessels():
    authenticate(ROLES)
    items = list(vessels.values())
    for field in ("owner_id", "jurisdiction_id", "current_certificate_id",
                  "registration_status", "service_status"):
        val = request.args.get(field)
        if val is not None:
            items = [v for v in items if v.get(field) == val]
    return list_response(items)


@app.route("/vessels/<vessel_id>", methods=["GET"])
def get_vessel(vessel_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(vessels, vessel_id)), 200)


@app.route("/vessels/<vessel_id>/register", methods=["POST"])
def register_vessel(vessel_id):
    authenticate({"JurisdictionAdmin"})
    vessel = get_or_404(vessels, vessel_id)
    if vessel["registration_status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "vessel not DRAFT")
    jur = jurisdictions[vessel["jurisdiction_id"]]
    seq = JUR_SEQ.get(jur["id"], 0) + 1
    JUR_SEQ[jur["id"]] = seq
    vessel["jurisdiction_number"] = f"{jur['code']}-{seq:06d}"
    vessel["registration_status"] = "REGISTERED"
    touch(vessel)
    return respond_object(ser(vessel), 200)


@app.route("/vessels/<vessel_id>/retire", methods=["POST"])
def retire_vessel(vessel_id):
    authenticate({"JurisdictionAdmin"})
    vessel = get_or_404(vessels, vessel_id)
    if vessel["registration_status"] != "REGISTERED":
        err("ERR_INVALID_STATE", 409, "vessel not REGISTERED")
    if vessel["service_status"] == "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "cannot retire a SUSPENDED vessel")
    # cascade: revoke ACTIVE certificate
    if vessel.get("current_certificate_id"):
        cert = certificates.get(vessel["current_certificate_id"])
        if cert is not None and cert["status"] == "ACTIVE":
            revoke_certificate(cert)
    vessel["registration_status"] = "RETIRED"
    vessel["service_status"] = "OUT_OF_SERVICE"
    touch(vessel)
    return respond_object(ser(vessel), 200)


@app.route("/vessels/<vessel_id>/reinstate", methods=["POST"])
def reinstate_vessel(vessel_id):
    authenticate({"JurisdictionAdmin"})
    vessel = get_or_404(vessels, vessel_id)
    if vessel["service_status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "vessel not SUSPENDED")
    passed_special = any(
        i["vessel_id"] == vessel_id and i["inspection_type"] == "SPECIAL" and i["status"] == "PASSED"
        for i in inspections.values()
    )
    if not passed_special:
        err("ERR_INVALID_STATE", 409, "no PASSED SPECIAL inspection")
    if vessel["open_critical_deficiency_count"] != 0:
        err("ERR_INVALID_STATE", 409, "open critical deficiency remains")
    vessel["service_status"] = "IN_SERVICE"
    recompute_vessel(vessel)
    touch(vessel)
    return respond_object(ser(vessel), 200)


@app.route("/vessels/<vessel_id>/incidents", methods=["POST"])
def file_incident(vessel_id):
    role, uid = authenticate({"Owner", "JurisdictionAdmin"})
    vessel = get_or_404(vessels, vessel_id)
    if role == "Owner" and vessel["owner_id"] != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "not the vessel owner")
    body = get_body()
    require_fields(body, ["severity", "occurred_at", "narrative"])
    check_enum(body["severity"], INCIDENT_SEVERITIES, "severity")
    occurred_at = parse_dt(body["occurred_at"])
    r = base_record()
    r.update({
        "vessel_id": vessel_id,
        "triggered_inspection_id": None,
        "severity": body["severity"],
        "occurred_at": occurred_at,
        "narrative": body["narrative"],
    })
    incidents[r["id"]] = r

    if body["severity"] == "CRITICAL" and vessel["service_status"] in ("IN_SERVICE", "RESTRICTED"):
        # 1. suspend
        vessel["service_status"] = "SUSPENDED"
        # 2. revoke ACTIVE certificate (cascade cancels scheduled non-special inspections)
        if vessel.get("current_certificate_id"):
            cert = certificates.get(vessel["current_certificate_id"])
            if cert is not None and cert["status"] == "ACTIVE":
                revoke_certificate(cert)
        # 3. auto-create SPECIAL inspection AFTER revoke cascade
        insp = base_record()
        jur = jurisdictions[vessel["jurisdiction_id"]]
        insp.update({
            "vessel_id": vessel_id,
            "inspector_id": None,
            "inspection_type": "SPECIAL",
            "is_special": True,
            "scheduled_start": now(),
            "scheduled_end": now(),
            "status": "SCHEDULED",
            "provisional_fee_cents": compute_fee(vessel, jur, 0, False, final=False),
            "result_recorded_at": None,
        })
        inspections[insp["id"]] = insp
        r["triggered_inspection_id"] = insp["id"]
        # 4. recompute risk + version bump
        recompute_vessel(vessel)
        touch(vessel)
    else:
        # non-cascading incident: still affects risk (incident penalty counts all severities)
        recompute_vessel(vessel)

    return respond_object(ser(r), 201)


# =============================================================================
# Insurance policies
# =============================================================================
@app.route("/insurance-policies", methods=["POST"])
def create_policy():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["vessel_id", "insurance_company_id", "coverage_start", "coverage_end"])
    coverage_start = parse_dt(body["coverage_start"])
    coverage_end = parse_dt(body["coverage_end"])
    get_or_404(vessels, body["vessel_id"])
    get_or_404(insurance_companies, body["insurance_company_id"])
    # coverage overlap (closed interval; touching endpoints conflict)
    for p in policies.values():
        if p["vessel_id"] == body["vessel_id"] and p["status"] == "ACTIVE":
            if coverage_start <= p["coverage_end"] and p["coverage_start"] <= coverage_end:
                err("ERR_POLICY_COVERAGE_OVERLAP", 409, "policy coverage overlap")
    r = base_record()
    r.update({
        "vessel_id": body["vessel_id"],
        "insurance_company_id": body["insurance_company_id"],
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "status": "ACTIVE",
    })
    policies[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/insurance-policies", methods=["GET"])
def list_policies():
    authenticate(ROLES)
    items = list(policies.values())
    for field in ("vessel_id", "insurance_company_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    return list_response(items)


@app.route("/insurance-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(policies, policy_id)), 200)


@app.route("/insurance-policies/<policy_id>/cancel", methods=["POST"])
def cancel_policy(policy_id):
    authenticate({"JurisdictionAdmin"})
    policy = get_or_404(policies, policy_id)
    if policy["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "policy not ACTIVE")
    policy["status"] = "CANCELLED"
    touch(policy)
    return respond_object(ser(policy), 200)


@app.route("/insurance-policies/<policy_id>/expire", methods=["POST"])
def expire_policy(policy_id):
    authenticate({"JurisdictionAdmin"})
    policy = get_or_404(policies, policy_id)
    if policy["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "policy not ACTIVE")
    if not (now() > policy["coverage_end"]):
        err("ERR_POLICY_NOT_EXPIRABLE", 409, "policy not yet past coverage_end")
    policy["status"] = "EXPIRED"
    touch(policy)
    return respond_object(ser(policy), 200)


# =============================================================================
# Inspections
# =============================================================================
@app.route("/inspections", methods=["POST"])
def schedule_inspection():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["vessel_id", "inspector_id", "inspection_type",
                          "scheduled_start", "scheduled_end"])
    check_enum(body["inspection_type"], INSPECTION_TYPES, "inspection_type")
    scheduled_start = parse_dt(body["scheduled_start"])
    scheduled_end = parse_dt(body["scheduled_end"])
    vessel = get_or_404(vessels, body["vessel_id"])
    inspector = get_or_404(inspectors, body["inspector_id"])
    itype = body["inspection_type"]
    # business safety: vessel inspectable
    if vessel["registration_status"] != "REGISTERED":
        err("ERR_VESSEL_NOT_INSPECTABLE", 409, "vessel not REGISTERED")
    if vessel["service_status"] in ("SUSPENDED", "OUT_OF_SERVICE") and itype != "SPECIAL":
        err("ERR_VESSEL_NOT_INSPECTABLE", 409, "vessel not inspectable in current service state")
    # business referential: inspector commissioning / coordination
    if inspector["inspector_type"] == "JURISDICTION":
        if not (inspector["status"] == "COMMISSIONED"
                and inspector.get("commissioning_jurisdiction_id") == vessel["jurisdiction_id"]):
            err("ERR_INSPECTOR_NOT_COMMISSIONED", 409, "inspector not commissioned in jurisdiction")
    else:  # INSURANCE
        ok = (inspector["status"] == "COMMISSIONED"
              and inspector.get("commissioning_jurisdiction_id") == vessel["jurisdiction_id"])
        if ok:
            policy_ok = any(
                p["vessel_id"] == vessel["id"]
                and p["status"] == "ACTIVE"
                and p["insurance_company_id"] == inspector.get("insurance_company_id")
                and p["coverage_start"] <= scheduled_start <= p["coverage_end"]
                for p in policies.values()
            )
            ok = policy_ok
        if not ok:
            err("ERR_INSURANCE_COORDINATION_INVALID", 409, "insurance coordination invalid")
    # business temporal: inspector double-booking (half-open)
    for other in inspections.values():
        if other["inspector_id"] == inspector["id"] and other["status"] != "CANCELLED":
            if scheduled_start < other["scheduled_end"] and other["scheduled_start"] < scheduled_end:
                err("ERR_INSPECTOR_DOUBLE_BOOKED", 409, "inspector double booked")
    r = base_record()
    jur = jurisdictions[vessel["jurisdiction_id"]]
    r.update({
        "vessel_id": vessel["id"],
        "inspector_id": inspector["id"],
        "inspection_type": itype,
        "is_special": itype == "SPECIAL",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "provisional_fee_cents": compute_fee(vessel, jur, 0, False, final=False),
        "result_recorded_at": None,
    })
    inspections[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/inspections", methods=["GET"])
def list_inspections():
    authenticate(ROLES)
    items = list(inspections.values())
    for field in ("vessel_id", "inspector_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [i for i in items if i.get(field) == val]
    return list_response(items)


@app.route("/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(inspections, inspection_id)), 200)


@app.route("/inspections/<inspection_id>/result", methods=["POST"])
def record_result(inspection_id):
    role, uid = authenticate({"Inspector"})
    insp = get_or_404(inspections, inspection_id)
    # ownership: acting inspector == assigned inspector
    if insp["inspector_id"] != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "not the assigned inspector")
    body = get_body()
    require_fields(body, ["result"])
    check_enum(body["result"], {"PASS", "PASS_WITH_DEFICIENCIES", "FAIL"}, "result")
    if insp["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "inspection not SCHEDULED")
    result = body["result"]
    attached = [d for d in deficiencies.values()
                if d["inspection_id"] == inspection_id and d["status"] != "WITHDRAWN"]
    crit = [d for d in attached if d["severity"] == "CRITICAL"]
    noncrit = [d for d in attached if d["severity"] == "NON_CRITICAL"]
    vessel = vessels[insp["vessel_id"]]
    if result == "PASS":
        if len(attached) != 0:
            err("ERR_INVALID_STATE", 409, "PASS requires no attached deficiencies")
        insp["status"] = "PASSED"
        insp["result_recorded_at"] = now()
    elif result == "PASS_WITH_DEFICIENCIES":
        if not (len(noncrit) >= 1 and len(crit) == 0):
            err("ERR_INVALID_STATE", 409, "PASS_WITH_DEFICIENCIES requires >=1 NON_CRITICAL and 0 CRITICAL")
        insp["status"] = "PASSED_WITH_DEFICIENCIES"
        insp["result_recorded_at"] = now()
        if vessel["service_status"] == "IN_SERVICE":
            vessel["service_status"] = "RESTRICTED"
    else:  # FAIL
        if len(crit) < 1:
            err("ERR_INVALID_STATE", 409, "FAIL requires >=1 CRITICAL deficiency")
        insp["status"] = "FAILED"
        insp["result_recorded_at"] = now()
        if vessel["service_status"] == "IN_SERVICE":
            vessel["service_status"] = "OUT_OF_SERVICE"
    touch(insp)
    recompute_vessel(vessel)
    return respond_object(ser(insp), 200)


@app.route("/inspections/<inspection_id>/deficiencies", methods=["POST"])
def raise_deficiency(inspection_id):
    authenticate({"Inspector"})
    insp = get_or_404(inspections, inspection_id)
    body = get_body()
    require_fields(body, ["severity", "description"])
    check_enum(body["severity"], DEFICIENCY_SEVERITIES, "severity")
    if insp["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "deficiencies may only be raised while SCHEDULED")
    r = base_record()
    r.update({
        "inspection_id": inspection_id,
        "vessel_id": insp["vessel_id"],
        "repair_order_id": None,
        "severity": body["severity"],
        "description": body["description"],
        "status": "OPEN",
    })
    deficiencies[r["id"]] = r
    vessel = vessels[insp["vessel_id"]]
    recompute_vessel(vessel)
    return respond_object(ser(r), 201)


@app.route("/inspections/<inspection_id>/national-board-report", methods=["POST"])
def file_nb_report(inspection_id):
    role, uid = authenticate({"Inspector"})
    insp = get_or_404(inspections, inspection_id)
    body = get_body()
    require_fields(body, ["report_number", "findings_summary"])
    for rep in reports.values():
        if rep["report_number"] == body["report_number"]:
            err("ERR_DUPLICATE_UNIQUE_FIELD", 409, "duplicate report_number")
    r = base_record(common=False)
    r.update({
        "inspection_id": inspection_id,
        "report_number": body["report_number"],
        "filed_by_inspector_id": uid,
        "findings_summary": body["findings_summary"],
    })
    reports[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/inspections/<inspection_id>/cancel", methods=["POST"])
def cancel_inspection(inspection_id):
    authenticate({"JurisdictionAdmin"})
    insp = get_or_404(inspections, inspection_id)
    if insp["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "inspection not SCHEDULED")
    insp["status"] = "CANCELLED"
    touch(insp)
    return respond_object(ser(insp), 200)


# =============================================================================
# National Board reports
# =============================================================================
@app.route("/national-board-reports", methods=["GET"])
def list_nb_reports():
    authenticate(ROLES)
    items = list(reports.values())
    for field in ("inspection_id", "filed_by_inspector_id"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    return list_response(items)


@app.route("/national-board-reports/<report_id>", methods=["GET"])
def get_nb_report(report_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(reports, report_id)), 200)


# =============================================================================
# Deficiencies
# =============================================================================
@app.route("/deficiencies", methods=["GET"])
def list_deficiencies():
    authenticate(ROLES)
    items = list(deficiencies.values())
    for field in ("inspection_id", "vessel_id", "repair_order_id", "status", "severity"):
        val = request.args.get(field)
        if val is not None:
            items = [d for d in items if d.get(field) == val]
    return list_response(items)


@app.route("/deficiencies/<deficiency_id>", methods=["GET"])
def get_deficiency(deficiency_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(deficiencies, deficiency_id)), 200)


@app.route("/deficiencies/<deficiency_id>/reinspect", methods=["POST"])
def reinspect_deficiency(deficiency_id):
    role, uid = authenticate({"Inspector"})
    deficiency = get_or_404(deficiencies, deficiency_id)
    body = get_body()
    require_fields(body, ["outcome"])
    check_enum(body["outcome"], {"PASS", "FAIL"}, "outcome")
    if deficiency["status"] != "REINSPECTION":
        err("ERR_INVALID_STATE", 409, "deficiency not in REINSPECTION")
    origin = inspections.get(deficiency["inspection_id"])
    origin_inspector = origin["inspector_id"] if origin else None
    if origin_inspector is not None and origin_inspector == uid:
        err("ERR_SEGREGATION_OF_DUTIES", 409, "reinspecting inspector raised the deficiency")
    vessel = vessels[deficiency["vessel_id"]]
    if body["outcome"] == "PASS":
        deficiency["status"] = "CLEARED"
        touch(deficiency)
        recompute_vessel(vessel)
        if vessel["open_deficiency_count"] == 0 and vessel["service_status"] == "RESTRICTED":
            vessel["service_status"] = "IN_SERVICE"
            recompute_vessel(vessel)
    else:  # FAIL
        deficiency["status"] = "OPEN"
        deficiency["repair_order_id"] = None
        touch(deficiency)
        recompute_vessel(vessel)
    return respond_object(ser(deficiency), 200)


@app.route("/deficiencies/<deficiency_id>/withdraw", methods=["POST"])
def withdraw_deficiency(deficiency_id):
    role, uid = authenticate({"Inspector"})
    deficiency = get_or_404(deficiencies, deficiency_id)
    origin = inspections.get(deficiency["inspection_id"])
    origin_inspector = origin["inspector_id"] if origin else None
    if origin_inspector != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "only the raising inspector may withdraw")
    if deficiency["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "deficiency not OPEN")
    deficiency["status"] = "WITHDRAWN"
    touch(deficiency)
    vessel = vessels[deficiency["vessel_id"]]
    recompute_vessel(vessel)
    return respond_object(ser(deficiency), 200)


# =============================================================================
# Repair orders
# =============================================================================
@app.route("/repair-orders", methods=["POST"])
def create_repair_order():
    role, uid = authenticate({"Owner"})
    body = get_body()
    require_fields(body, ["vessel_id", "deficiency_ids", "description"])
    if not isinstance(body["deficiency_ids"], list):
        err("ERR_INVALID_REQUEST", 400, "deficiency_ids must be an array")
    vessel = get_or_404(vessels, body["vessel_id"])
    for did in body["deficiency_ids"]:
        get_or_404(deficiencies, did)
    # ownership
    if vessel["owner_id"] != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "not the vessel owner")
    # business constraint: all deficiencies belong to vessel and are OPEN
    for did in body["deficiency_ids"]:
        d = deficiencies[did]
        if d["vessel_id"] != vessel["id"] or d["status"] != "OPEN":
            err("ERR_DEFICIENCY_NOT_REPAIRABLE", 409, "deficiency not repairable")
    r = base_record()
    r.update({
        "vessel_id": vessel["id"],
        "deficiency_ids": list(body["deficiency_ids"]),
        "description": body["description"],
        "status": "IN_PROGRESS",
    })
    repair_orders[r["id"]] = r
    for did in body["deficiency_ids"]:
        d = deficiencies[did]
        d["status"] = "UNDER_REPAIR"
        d["repair_order_id"] = r["id"]
        touch(d)
    recompute_vessel(vessel)
    return respond_object(ser(r), 201)


@app.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    authenticate(ROLES)
    items = list(repair_orders.values())
    for field in ("vessel_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [ro for ro in items if ro.get(field) == val]
    return list_response(items)


@app.route("/repair-orders/<repair_order_id>", methods=["GET"])
def get_repair_order(repair_order_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(repair_orders, repair_order_id)), 200)


@app.route("/repair-orders/<repair_order_id>/complete", methods=["POST"])
def complete_repair_order(repair_order_id):
    role, uid = authenticate({"Owner"})
    ro = get_or_404(repair_orders, repair_order_id)
    vessel = vessels[ro["vessel_id"]]
    # ownership
    if vessel["owner_id"] != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "not the vessel owner")
    if ro["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "repair order not IN_PROGRESS")
    ro["status"] = "COMPLETED"
    touch(ro)
    for d in deficiencies.values():
        if d["repair_order_id"] == ro["id"] and d["status"] == "UNDER_REPAIR":
            d["status"] = "REINSPECTION"
            touch(d)
    recompute_vessel(vessel)
    return respond_object(ser(ro), 200)


@app.route("/repair-orders/<repair_order_id>/cancel", methods=["POST"])
def cancel_repair_order(repair_order_id):
    authenticate({"Owner"})
    ro = get_or_404(repair_orders, repair_order_id)
    if ro["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "repair order not IN_PROGRESS")
    ro["status"] = "CANCELLED"
    touch(ro)
    vessel = vessels.get(ro["vessel_id"])
    for d in deficiencies.values():
        if d["repair_order_id"] == ro["id"] and d["status"] == "UNDER_REPAIR":
            d["status"] = "OPEN"
            d["repair_order_id"] = None
            touch(d)
    if vessel is not None:
        recompute_vessel(vessel)
    return respond_object(ser(ro), 200)


# =============================================================================
# Fee invoices
# =============================================================================
@app.route("/fee-invoices", methods=["POST"])
def create_fee_invoice():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["vessel_id", "inspection_id"])
    vessel = get_or_404(vessels, body["vessel_id"])
    insp = get_or_404(inspections, body["inspection_id"])
    jur = jurisdictions[vessel["jurisdiction_id"]]
    noncrit_count = sum(1 for d in deficiencies.values()
                        if d["inspection_id"] == insp["id"]
                        and d["severity"] == "NON_CRITICAL"
                        and d["status"] != "WITHDRAWN")
    amount = compute_fee(vessel, jur, noncrit_count, insp["is_special"], final=True)
    r = base_record()
    r.update({
        "vessel_id": vessel["id"],
        "inspection_id": insp["id"],
        "certificate_id": None,
        "amount_cents": amount,
        "amount_paid_cents": 0,
        "refunded_cents": 0,
        "status": "UNPAID",
    })
    fee_invoices[r["id"]] = r
    return respond_object(ser(r), 201)


@app.route("/fee-invoices", methods=["GET"])
def list_fee_invoices():
    authenticate(ROLES)
    items = list(fee_invoices.values())
    for field in ("vessel_id", "inspection_id", "certificate_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [f for f in items if f.get(field) == val]
    return list_response(items)


@app.route("/fee-invoices/<fee_invoice_id>", methods=["GET"])
def get_fee_invoice(fee_invoice_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(fee_invoices, fee_invoice_id)), 200)


@app.route("/fee-invoices/<fee_invoice_id>/pay", methods=["POST"])
def pay_fee_invoice(fee_invoice_id):
    role, uid = authenticate({"Owner"})
    inv = get_or_404(fee_invoices, fee_invoice_id)
    vessel = vessels[inv["vessel_id"]]
    if vessel["owner_id"] != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "not the vessel owner")
    if inv["status"] != "UNPAID":
        err("ERR_INVALID_STATE", 409, "invoice not UNPAID")
    inv["status"] = "PAID"
    inv["amount_paid_cents"] = inv["amount_cents"]
    touch(inv)
    jur = jurisdictions[vessel["jurisdiction_id"]]
    jur["collected_fees_cents"] += inv["amount_cents"]
    return respond_object(ser(inv), 200)


@app.route("/fee-invoices/<fee_invoice_id>/refund", methods=["POST"])
def refund_fee_invoice(fee_invoice_id):
    authenticate({"JurisdictionAdmin"})
    inv = get_or_404(fee_invoices, fee_invoice_id)
    if inv["status"] != "PAID":
        err("ERR_INVALID_STATE", 409, "invoice not PAID")
    for cert in certificates.values():
        if cert["fee_invoice_id"] == inv["id"] and cert["status"] == "ACTIVE":
            err("ERR_INVALID_STATE", 409, "an ACTIVE certificate references this invoice")
    inv["status"] = "REFUNDED"
    inv["refunded_cents"] = inv["amount_cents"]
    touch(inv)
    vessel = vessels[inv["vessel_id"]]
    jur = jurisdictions[vessel["jurisdiction_id"]]
    jur["collected_fees_cents"] -= inv["amount_cents"]
    return respond_object(ser(inv), 200)


@app.route("/fee-invoices/<fee_invoice_id>/void", methods=["POST"])
def void_fee_invoice(fee_invoice_id):
    authenticate({"JurisdictionAdmin"})
    inv = get_or_404(fee_invoices, fee_invoice_id)
    if inv["status"] != "UNPAID":
        err("ERR_INVALID_STATE", 409, "invoice not UNPAID")
    inv["status"] = "VOID"
    touch(inv)
    return respond_object(ser(inv), 200)


# =============================================================================
# Certificates
# =============================================================================
@app.route("/certificates", methods=["POST"])
def issue_certificate():
    authenticate({"JurisdictionAdmin"})
    body = get_body()
    require_fields(body, ["vessel_id", "inspection_id", "fee_invoice_id", "expected_vessel_version"])
    if not isinstance(body["expected_vessel_version"], int) or isinstance(body["expected_vessel_version"], bool):
        err("ERR_INVALID_REQUEST", 400, "expected_vessel_version must be an integer")
    supersedes_id = body.get("supersedes_certificate_id", None)
    # existence (body FKs)
    vessel = get_or_404(vessels, body["vessel_id"])
    insp = get_or_404(inspections, body["inspection_id"])
    inv = get_or_404(fee_invoices, body["fee_invoice_id"])
    supersedes_cert = None
    if supersedes_id is not None:
        supersedes_cert = get_or_404(certificates, supersedes_id)
    # state: inspection must be PASSED or PASSED_WITH_DEFICIENCIES
    if insp["status"] not in ("PASSED", "PASSED_WITH_DEFICIENCIES"):
        err("ERR_INVALID_STATE", 409, "inspection not in a passing state")
    if supersedes_cert is not None and supersedes_cert["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "superseded certificate not ACTIVE")
    # OCC (priority 5, 412)
    if body["expected_vessel_version"] != vessel["version"]:
        err("ERR_STALE_VESSEL_VERSION", 412, "stale vessel version")
    # business safety: no open critical deficiency
    if vessel["open_critical_deficiency_count"] != 0:
        err("ERR_CRITICAL_DEFICIENCY_OPEN", 409, "vessel has open critical deficiency")
    # business fiscal: fee invoice PAID and matching
    if not (inv["status"] == "PAID"
            and inv["vessel_id"] == body["vessel_id"]
            and inv["inspection_id"] == body["inspection_id"]):
        err("ERR_FEE_NOT_PAID", 402, "fee invoice not paid or mismatched")

    r = base_record()
    valid_from = now()
    interval = vessel_interval_months(vessel)
    valid_until = add_months(valid_from, interval)
    r.update({
        "vessel_id": vessel["id"],
        "inspection_id": insp["id"],
        "fee_invoice_id": inv["id"],
        "supersedes_certificate_id": supersedes_id,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
    })
    certificates[r["id"]] = r
    inv["certificate_id"] = r["id"]
    touch(inv)
    if supersedes_cert is not None:
        supersedes_cert["status"] = "SUPERSEDED"
        touch(supersedes_cert)
    vessel["current_certificate_id"] = r["id"]
    # first issuance on NOT_IN_SERVICE resting on PASSED inspection with no crit deficiency
    if (vessel["service_status"] == "NOT_IN_SERVICE"
            and insp["status"] == "PASSED"
            and vessel["open_critical_deficiency_count"] == 0):
        vessel["service_status"] = "IN_SERVICE"
        recompute_vessel(vessel)
    touch(vessel)
    return respond_object(ser(r), 201)


def vessel_interval_months(vessel):
    jur = jurisdictions[vessel["jurisdiction_id"]]
    if jur.get("interval_months_override") is not None:
        return jur["interval_months_override"]
    return INTERVAL_BY_CLASS[vessel["vessel_class"]]


@app.route("/certificates", methods=["GET"])
def list_certificates():
    authenticate(ROLES)
    items = list(certificates.values())
    for field in ("vessel_id", "inspection_id", "fee_invoice_id", "supersedes_certificate_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    return list_response(items)


@app.route("/certificates/<certificate_id>", methods=["GET"])
def get_certificate(certificate_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(certificates, certificate_id)), 200)


@app.route("/certificates/<certificate_id>/revoke", methods=["POST"])
def revoke_cert_endpoint(certificate_id):
    authenticate({"JurisdictionAdmin"})
    cert = get_or_404(certificates, certificate_id)
    if cert["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "certificate not ACTIVE")
    revoke_certificate(cert)
    return respond_object(ser(cert), 200)


@app.route("/certificates/<certificate_id>/expire", methods=["POST"])
def expire_cert_endpoint(certificate_id):
    authenticate({"JurisdictionAdmin"})
    cert = get_or_404(certificates, certificate_id)
    if cert["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "certificate not ACTIVE")
    if now() < cert["valid_until"]:
        err("ERR_CERTIFICATE_NOT_DUE", 409, "certificate not yet due")
    cert["status"] = "EXPIRED"
    touch(cert)
    vessel = vessels.get(cert["vessel_id"])
    if vessel is not None and vessel.get("current_certificate_id") == cert["id"]:
        vessel["current_certificate_id"] = None
    return respond_object(ser(cert), 200)


# =============================================================================
# Incidents (reads)
# =============================================================================
@app.route("/incidents", methods=["GET"])
def list_incidents():
    authenticate(ROLES)
    items = list(incidents.values())
    for field in ("vessel_id", "triggered_inspection_id", "severity"):
        val = request.args.get(field)
        if val is not None:
            items = [i for i in items if i.get(field) == val]
    return list_response(items)


@app.route("/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    authenticate(ROLES)
    return respond_object(ser(get_or_404(incidents, incident_id)), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
