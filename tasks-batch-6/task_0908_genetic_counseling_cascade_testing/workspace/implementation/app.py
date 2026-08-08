"""
Genetic Counseling & Cascade Testing API — Python + Flask reference implementation.

In-memory only (dicts keyed by id). No seeding: the store starts empty on every
boot; tests build all preconditions through the declared API surface.
"""
import os
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLES = {"GeneticCounselor", "LabTechnician", "BillingSpecialist", "ProgramAdmin"}
ALL_ROLES = ROLES

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "families": {},
    "counselors": {},
    "labs": {},
    "counseling_cases": {},
    "pedigree_members": {},
    "consent_records": {},
    "counseling_sessions": {},
    "test_orders": {},
    "test_results": {},
    "cascade_invitations": {},
    "insurance_claims": {},
    "surveillance_plans": {},
    "referrals": {},
}

_SEQ = {"n": 0}

# Logical clock: startup default is exactly 2026-05-01T00:00:00Z.
LOGICAL_CLOCK = {"dt": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid4())


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(datetime.now(timezone.utc))


def clock_iso():
    return iso(LOGICAL_CLOCK["dt"])


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def strip_private(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, code=200, list_meta=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": meta(list_meta), "response_type": rtype, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta(),
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
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or malformed X-User-ID header")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or malformed X-User-Role header")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def verr(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def require(body, name):
    if name not in body or body[name] is None:
        verr(f"Missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = require(body, name)
    if not isinstance(v, str) or v == "":
        verr(f"Field {name} must be a non-empty string")
    return v


def req_int(body, name, minimum=None):
    v = require(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        verr(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        verr(f"Field {name} must be >= {minimum}")
    return v


def req_enum(body, name, choices):
    v = require(body, name)
    if v not in choices:
        verr(f"Field {name} must be one of {sorted(choices)}")
    return v


def opt_enum(body, name, choices, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if v not in choices:
        verr(f"Field {name} must be one of {sorted(choices)}")
    return v


def req_rate(body, name):
    v = require(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        verr(f"Field {name} must be a number")
    if v < 0 or v > 1:
        verr(f"Field {name} must be between 0 and 1 inclusive")
    return v


def req_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        verr(f"Field {name} must be a boolean")
    return v


def parse_dt(value, field):
    if not isinstance(value, str):
        verr(f"Field {field} must be an ISO 8601 datetime string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        verr(f"Field {field} is not a valid ISO 8601 datetime")


# ---------------------------------------------------------------------------
# Entity lifecycle
# ---------------------------------------------------------------------------
def base_entity(fields):
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    return ent


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def lookup(coll, _id, err_id):
    ent = DB[coll].get(_id)
    if ent is None:
        raise ApiError(err_id, 404, f"{err_id}")
    return ent


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def rhu_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(value):
    return float(Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def recompute_family(family):
    fid = family["id"]
    invs = [i for i in DB["cascade_invitations"].values() if i["family_id"] == fid]
    reserved = sum(i["estimated_cost_cents"] for i in invs if i["status"] == "SENT")
    spent = sum(i["estimated_cost_cents"] for i in invs if i["status"] == "ACCEPTED")
    budget = family["outreach_budget_cents"]
    sent_count = sum(1 for i in invs if i["status"] != "DRAFT")
    cases = [
        c for c in DB["counseling_cases"].values()
        if c["family_id"] == fid and c.get("originating_invitation_id")
    ]
    cases_count = len(cases)
    uptake = rhu4(Decimal(cases_count) / Decimal(sent_count)) if sent_count > 0 else 0.0
    family["outreach_reserved_cents"] = reserved
    family["outreach_spent_cents"] = spent
    family["outreach_available_cents"] = budget - reserved - spent
    family["cascade_invitations_sent_count"] = sent_count
    family["cascade_cases_count"] = cases_count
    family["cascade_uptake_pct"] = uptake
    touch(family)


def recompute_lab_load(lab):
    lid = lab["id"]
    load = sum(
        1 for o in DB["test_orders"].values()
        if o["lab_id"] == lid and o["status"] == "SUBMITTED"
    )
    lab["current_processing_load"] = load
    touch(lab)


def recompute_case_sessions(case):
    cid = case["id"]
    used = sum(
        1 for s in DB["counseling_sessions"].values()
        if s["counseling_case_id"] == cid
        and s["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW")
    )
    case["sessions_used"] = used
    case["sessions_remaining"] = case["covered_sessions"] - used
    touch(case)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
POP_BASELINE = Decimal("0.05")
PER_UNIT = Decimal("0.05")
ASHKENAZI_BONUS = Decimal("0.10")
RISK_CAP = Decimal("0.99")
UNINFORMATIVE_FACTOR = Decimal("0.5")
CONFIRMED_CARRIER = Decimal("0.99")
HIGH_THRESHOLD = 0.20
MODERATE_THRESHOLD = 0.10

DEGREE_WEIGHT = {1: Decimal("1.0"), 2: Decimal("0.5"), 3: Decimal("0.25")}


def onset_multiplier(age):
    if age is None:
        return 1
    if age < 40:
        return 3
    if age < 50:
        return 2
    return 1


def compute_prior_risk(case):
    members = [
        m for m in DB["pedigree_members"].values()
        if m["counseling_case_id"] == case["id"]
    ]
    units = Decimal("0")
    for m in members:
        if m.get("affected") and m.get("relationship") != "SELF":
            w = DEGREE_WEIGHT.get(m.get("degree"), Decimal("0"))
            units += w * onset_multiplier(m.get("age_of_onset"))
    raw = POP_BASELINE + units * PER_UNIT
    bonus = ASHKENAZI_BONUS if case.get("ancestry") == "ASHKENAZI_JEWISH" else Decimal("0")
    capped = min(RISK_CAP, raw + bonus)
    return rhu4(capped)


def compute_risk_tier(prior, residual):
    r = residual if residual is not None else prior
    if r is None:
        return None
    if r >= HIGH_THRESHOLD:
        return "HIGH"
    if r >= MODERATE_THRESHOLD:
        return "MODERATE"
    return "LOW"


def carrier_from_classification(classification):
    if classification in ("PATHOGENIC", "LIKELY_PATHOGENIC"):
        return "POSITIVE_PATHOGENIC"
    if classification in ("BENIGN", "LIKELY_BENIGN"):
        return "NEGATIVE"
    return "VUS"


def compute_residual_risk(case, carrier_result):
    if carrier_result == "POSITIVE_PATHOGENIC":
        return float(CONFIRMED_CARRIER)
    if carrier_result == "NEGATIVE":
        if case.get("familial_variant_known"):
            return float(POP_BASELINE)
        prior = case.get("prior_risk_pct") or 0.0
        return rhu4(Decimal(str(prior)) * UNINFORMATIVE_FACTOR)
    # VUS: unchanged
    return case.get("prior_risk_pct")


INVITATION_BASE = {"LETTER": 500, "EMAIL": 100, "PHONE": 800}
DEGREE_SURCHARGE = {1: 0, 2: 200, 3: 400}


def invitation_cost(contact_method, degree):
    return INVITATION_BASE[contact_method] + DEGREE_SURCHARGE[degree]


INTERVAL_BY_TIER = {"HIGH": 6, "MODERATE": 12, "LOW": 24}


# ---------------------------------------------------------------------------
# Temporal overlap (strict: touching endpoints are adjacent, not overlapping)
# ---------------------------------------------------------------------------
def overlaps(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
SEX = {"MALE", "FEMALE", "OTHER"}
ANCESTRY = {"ASHKENAZI_JEWISH", "EUROPEAN", "AFRICAN", "ASIAN", "HISPANIC", "OTHER"}
REL_TO_PROBAND = {"PROBAND", "FIRST_DEGREE", "SECOND_DEGREE", "THIRD_DEGREE"}
PEDIGREE_REL = {
    "SELF", "PARENT", "SIBLING", "CHILD", "GRANDPARENT",
    "AUNT_UNCLE", "COUSIN", "NIECE_NEPHEW", "HALF_SIBLING",
}
CONSENT_TYPE = {"TESTING", "RESULT_DISCLOSURE", "CASCADE_CONTACT", "DATA_SHARING"}
SESSION_TYPE = {"PRE_TEST", "DISCLOSURE", "FOLLOW_UP"}
CLASSIFICATION = {"PATHOGENIC", "LIKELY_PATHOGENIC", "VUS", "LIKELY_BENIGN", "BENIGN"}
INVITE_REL = {
    "PARENT", "SIBLING", "CHILD", "GRANDPARENT",
    "AUNT_UNCLE", "COUSIN", "NIECE_NEPHEW", "HALF_SIBLING",
}
CONTACT_METHOD = {"LETTER", "EMAIL", "PHONE"}
SPECIALTY = {
    "BREAST_SURGERY", "GI_ONCOLOGY", "GYN_ONCOLOGY",
    "CARDIOLOGY", "ENDOCRINOLOGY", "HIGH_RISK_CLINIC",
}
URGENCY = {"ROUTINE", "URGENT"}
DEG_TO_REL = {1: "FIRST_DEGREE", 2: "SECOND_DEGREE", 3: "THIRD_DEGREE"}


# ---------------------------------------------------------------------------
# List / pagination helper
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    try:
        limit = 10 if limit is None else int(limit)
    except (TypeError, ValueError):
        verr("limit must be an integer")
    try:
        offset = 0 if offset is None else int(offset)
    except (TypeError, ValueError):
        verr("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    list_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [strip_private(e) for e in page], list_meta


def out(entity):
    return strip_private(entity)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    value = require(body, "to_iso8601")
    dt = parse_dt(value, "to_iso8601")
    LOGICAL_CLOCK["dt"] = dt.astimezone(timezone.utc)
    return ok({}, 200)


# ===========================================================================
# Family
# ===========================================================================
@app.route("/families", methods=["POST"])
def create_family():
    _uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    name = req_str(body, "family_name")
    budget = req_int(body, "outreach_budget_cents", minimum=0)
    fam = base_entity({
        "family_name": name,
        "outreach_budget_cents": budget,
        "outreach_reserved_cents": 0,
        "outreach_spent_cents": 0,
        "outreach_available_cents": budget,
        "cascade_invitations_sent_count": 0,
        "cascade_cases_count": 0,
        "cascade_uptake_pct": 0.0,
    })
    DB["families"][fam["id"]] = fam
    return ok(out(fam), 201)


@app.route("/families/<fid>", methods=["GET"])
def get_family(fid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    fam = lookup("families", fid, "ERR_FAMILY_NOT_FOUND")
    return ok(out(fam), 200)


# ===========================================================================
# Counselor
# ===========================================================================
@app.route("/counselors", methods=["POST"])
def create_counselor():
    _uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    full_name = req_str(body, "full_name")
    npi = req_str(body, "npi")
    c = base_entity({"full_name": full_name, "npi": npi})
    DB["counselors"][c["id"]] = c
    return ok(out(c), 201)


@app.route("/counselors/<cid>", methods=["GET"])
def get_counselor(cid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = lookup("counselors", cid, "ERR_COUNSELOR_NOT_FOUND")
    return ok(out(c), 200)


# ===========================================================================
# Lab
# ===========================================================================
@app.route("/labs", methods=["POST"])
def create_lab():
    _uid, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    lab_name = req_str(body, "lab_name")
    cap = req_int(body, "max_concurrent_capacity", minimum=1)
    turn = req_int(body, "turnaround_days", minimum=0)
    lab = base_entity({
        "lab_name": lab_name,
        "max_concurrent_capacity": cap,
        "turnaround_days": turn,
        "current_processing_load": 0,
    })
    DB["labs"][lab["id"]] = lab
    return ok(out(lab), 201)


@app.route("/labs/<lid>", methods=["GET"])
def get_lab(lid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    lab = lookup("labs", lid, "ERR_LAB_NOT_FOUND")
    return ok(out(lab), 200)


# ===========================================================================
# CounselingCase
# ===========================================================================
def _new_case(fields):
    base = {
        "family_id": None,
        "assigned_counselor_id": None,
        "originating_invitation_id": None,
        "patient_name": None,
        "patient_dob": None,
        "sex": None,
        "ancestry": None,
        "relationship_to_proband": "PROBAND",
        "referral_reason": None,
        "familial_variant_known": False,
        "covered_sessions": 0,
        "prior_risk_pct": None,
        "residual_risk_pct": None,
        "risk_tier": None,
        "carrier_result": None,
        "sessions_used": 0,
        "sessions_remaining": 0,
        "clinical_status": "INTAKE",
        "billing_status": "UNBILLED",
    }
    base.update(fields)
    case = base_entity(base)
    return case


@app.route("/counseling-cases", methods=["POST"])
def create_case():
    uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    # existence (priority 3) for provided FKs, left to right
    if isinstance(body.get("family_id"), str) and body["family_id"]:
        lookup("families", body["family_id"], "ERR_FAMILY_NOT_FOUND")
    if isinstance(body.get("assigned_counselor_id"), str) and body["assigned_counselor_id"]:
        lookup("counselors", body["assigned_counselor_id"], "ERR_COUNSELOR_NOT_FOUND")
    # body validation (priority 6)
    family_id = req_str(body, "family_id")
    counselor_id = req_str(body, "assigned_counselor_id")
    patient_name = req_str(body, "patient_name")
    patient_dob = req_str(body, "patient_dob")
    sex = req_enum(body, "sex", SEX)
    ancestry = req_enum(body, "ancestry", ANCESTRY)
    referral_reason = req_str(body, "referral_reason")
    covered = req_int(body, "covered_sessions", minimum=0)
    rel = opt_enum(body, "relationship_to_proband", REL_TO_PROBAND, "PROBAND")
    fvk = req_bool(body, "familial_variant_known", False)
    case = _new_case({
        "family_id": family_id,
        "assigned_counselor_id": counselor_id,
        "patient_name": patient_name,
        "patient_dob": patient_dob,
        "sex": sex,
        "ancestry": ancestry,
        "relationship_to_proband": rel,
        "referral_reason": referral_reason,
        "familial_variant_known": fvk,
        "covered_sessions": covered,
        "sessions_remaining": covered,
    })
    DB["counseling_cases"][case["id"]] = case
    return ok(out(case), 201)


@app.route("/counseling-cases", methods=["GET"])
def list_cases():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["counseling_cases"].values())
    fam = request.args.get("family_id")
    cslr = request.args.get("assigned_counselor_id")
    orig = request.args.get("originating_invitation_id")
    if fam is not None:
        items = [c for c in items if c["family_id"] == fam]
    if cslr is not None:
        items = [c for c in items if c["assigned_counselor_id"] == cslr]
    if orig is not None:
        items = [c for c in items if c.get("originating_invitation_id") == orig]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/counseling-cases/<cid>", methods=["GET"])
def get_case(cid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    case = lookup("counseling_cases", cid, "ERR_CASE_NOT_FOUND")
    return ok(out(case), 200)


@app.route("/counseling-cases/<cid>/assess-risk", methods=["POST"])
def assess_risk(cid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    case = lookup("counseling_cases", cid, "ERR_CASE_NOT_FOUND")
    if case["clinical_status"] != "INTAKE":
        raise ApiError("ERR_CASE_INVALID_CLINICAL_STATE", 409, "Case must be INTAKE to assess risk")
    members = [m for m in DB["pedigree_members"].values() if m["counseling_case_id"] == cid]
    if not members:
        raise ApiError("ERR_PEDIGREE_EMPTY", 409, "Case has no pedigree members")
    prior = compute_prior_risk(case)
    case["prior_risk_pct"] = prior
    case["risk_tier"] = compute_risk_tier(prior, case.get("residual_risk_pct"))
    case["clinical_status"] = "RISK_ASSESSED"
    touch(case)
    return ok(out(case), 200)


@app.route("/counseling-cases/<cid>/withdraw", methods=["POST"])
def withdraw_case(cid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    case = lookup("counseling_cases", cid, "ERR_CASE_NOT_FOUND")
    if case["clinical_status"] == "WITHDRAWN":
        raise ApiError("ERR_CASE_INVALID_CLINICAL_STATE", 409, "Case already withdrawn")
    case["clinical_status"] = "WITHDRAWN"
    touch(case)
    return ok(out(case), 200)


# ===========================================================================
# PedigreeMember
# ===========================================================================
@app.route("/pedigree-members", methods=["POST"])
def create_pedigree_member():
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    if isinstance(body.get("counseling_case_id"), str) and body["counseling_case_id"]:
        lookup("counseling_cases", body["counseling_case_id"], "ERR_CASE_NOT_FOUND")
    if isinstance(body.get("related_member_id"), str) and body["related_member_id"]:
        lookup("pedigree_members", body["related_member_id"], "ERR_PEDIGREE_MEMBER_NOT_FOUND")
    case_id = req_str(body, "counseling_case_id")
    relationship = req_enum(body, "relationship", PEDIGREE_REL)
    degree = require(body, "degree")
    if isinstance(degree, bool) or not isinstance(degree, int) or degree not in (0, 1, 2, 3):
        verr("degree must be one of 0,1,2,3")
    if "affected" not in body or body["affected"] is None:
        verr("Missing required field: affected")
    affected = body["affected"]
    if not isinstance(affected, bool):
        verr("affected must be a boolean")
    age_of_onset = body.get("age_of_onset")
    if age_of_onset is not None and (isinstance(age_of_onset, bool) or not isinstance(age_of_onset, int)):
        verr("age_of_onset must be an integer")
    deceased = req_bool(body, "deceased", False)
    related_member_id = body.get("related_member_id")
    if related_member_id is not None and not isinstance(related_member_id, str):
        verr("related_member_id must be a string")
    # Structural: SELF must be degree 0
    if relationship == "SELF" and degree != 0:
        verr("A SELF pedigree member must have degree 0")
    is_at_risk = (relationship != "SELF") and (degree in (1, 2)) and (not deceased)
    member = base_entity({
        "counseling_case_id": case_id,
        "related_member_id": related_member_id,
        "relationship": relationship,
        "degree": degree,
        "affected": affected,
        "age_of_onset": age_of_onset,
        "deceased": deceased,
        "is_at_risk": is_at_risk,
    })
    DB["pedigree_members"][member["id"]] = member
    return ok(out(member), 201)


@app.route("/pedigree-members", methods=["GET"])
def list_pedigree_members():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["pedigree_members"].values())
    case_id = request.args.get("counseling_case_id")
    related = request.args.get("related_member_id")
    if case_id is not None:
        items = [m for m in items if m["counseling_case_id"] == case_id]
    if related is not None:
        items = [m for m in items if m.get("related_member_id") == related]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/pedigree-members/<mid>", methods=["GET"])
def get_pedigree_member(mid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    m = lookup("pedigree_members", mid, "ERR_PEDIGREE_MEMBER_NOT_FOUND")
    return ok(out(m), 200)


# ===========================================================================
# ConsentRecord
# ===========================================================================
@app.route("/consent-records", methods=["POST"])
def create_consent():
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    if isinstance(body.get("counseling_case_id"), str) and body["counseling_case_id"]:
        lookup("counseling_cases", body["counseling_case_id"], "ERR_CASE_NOT_FOUND")
    case_id = req_str(body, "counseling_case_id")
    consent_type = req_enum(body, "consent_type", CONSENT_TYPE)
    rec = base_entity({
        "counseling_case_id": case_id,
        "consent_type": consent_type,
        "signed_at": None,
        "status": "PENDING",
    })
    DB["consent_records"][rec["id"]] = rec
    return ok(out(rec), 201)


@app.route("/consent-records", methods=["GET"])
def list_consent():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["consent_records"].values())
    case_id = request.args.get("counseling_case_id")
    if case_id is not None:
        items = [c for c in items if c["counseling_case_id"] == case_id]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/consent-records/<cid>", methods=["GET"])
def get_consent(cid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = lookup("consent_records", cid, "ERR_CONSENT_NOT_FOUND")
    return ok(out(rec), 200)


@app.route("/consent-records/<cid>/sign", methods=["POST"])
def sign_consent(cid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    rec = lookup("consent_records", cid, "ERR_CONSENT_NOT_FOUND")
    if rec["status"] != "PENDING":
        raise ApiError("ERR_CONSENT_INVALID_STATE", 409, "Consent must be PENDING to sign")
    rec["status"] = "SIGNED"
    rec["signed_at"] = clock_iso()
    touch(rec)
    return ok(out(rec), 200)


@app.route("/consent-records/<cid>/revoke", methods=["POST"])
def revoke_consent(cid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    rec = lookup("consent_records", cid, "ERR_CONSENT_NOT_FOUND")
    if rec["status"] != "SIGNED":
        raise ApiError("ERR_CONSENT_INVALID_STATE", 409, "Consent must be SIGNED to revoke")
    if _case_has_disclosed_result(rec["counseling_case_id"]):
        raise ApiError("ERR_CONSENT_LOCKED_BY_DISCLOSURE", 409,
                       "Cannot revoke consent once a result has been disclosed")
    rec["status"] = "REVOKED"
    touch(rec)
    return ok(out(rec), 200)


def _case_has_disclosed_result(case_id):
    order_ids = {o["id"] for o in DB["test_orders"].values() if o["counseling_case_id"] == case_id}
    for r in DB["test_results"].values():
        if r["test_order_id"] in order_ids and r["status"] == "DISCLOSED":
            return True
    return False


# ===========================================================================
# CounselingSession
# ===========================================================================
@app.route("/counseling-sessions", methods=["POST"])
def create_session():
    uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    # existence (priority 3)
    if isinstance(body.get("counseling_case_id"), str) and body["counseling_case_id"]:
        lookup("counseling_cases", body["counseling_case_id"], "ERR_CASE_NOT_FOUND")
    if isinstance(body.get("counselor_id"), str) and body["counselor_id"]:
        lookup("counselors", body["counselor_id"], "ERR_COUNSELOR_NOT_FOUND")
    # ownership (priority 4): counselor books only own sessions
    if isinstance(body.get("counselor_id"), str) and body["counselor_id"]:
        if body["counselor_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                           "Counselor may only book their own sessions")
    # body validation (priority 6)
    case_id = req_str(body, "counseling_case_id")
    counselor_id = req_str(body, "counselor_id")
    session_type = req_enum(body, "session_type", SESSION_TYPE)
    start_raw = req_str(body, "scheduled_start")
    end_raw = req_str(body, "scheduled_end")
    start_dt = parse_dt(start_raw, "scheduled_start")
    end_dt = parse_dt(end_raw, "scheduled_end")
    if not (end_dt > start_dt):
        verr("scheduled_end must be strictly after scheduled_start")
    case = DB["counseling_cases"][case_id]
    # state (priority 7): case must not be withdrawn
    if case["clinical_status"] == "WITHDRAWN":
        raise ApiError("ERR_CASE_INVALID_CLINICAL_STATE", 409,
                       "Cannot book a session on a withdrawn case")
    # temporal (priority 10): counselor double-booking (strict overlap)
    for s in DB["counseling_sessions"].values():
        if s["counselor_id"] == counselor_id and s["status"] != "CANCELLED":
            s_start = parse_dt(s["scheduled_start"], "scheduled_start")
            s_end = parse_dt(s["scheduled_end"], "scheduled_end")
            if overlaps(start_dt, end_dt, s_start, s_end):
                raise ApiError("ERR_COUNSELOR_DOUBLE_BOOKED", 409,
                               "Counselor already has an overlapping session")
    # fiscal (priority 12): session credit
    if case["sessions_remaining"] <= 0:
        raise ApiError("ERR_NO_SESSION_CREDITS", 402, "No remaining session credits")
    session = base_entity({
        "counseling_case_id": case_id,
        "counselor_id": counselor_id,
        "session_type": session_type,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "status": "SCHEDULED",
    })
    DB["counseling_sessions"][session["id"]] = session
    recompute_case_sessions(case)
    return ok(out(session), 201)


@app.route("/counseling-sessions", methods=["GET"])
def list_sessions():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["counseling_sessions"].values())
    case_id = request.args.get("counseling_case_id")
    counselor_id = request.args.get("counselor_id")
    if case_id is not None:
        items = [s for s in items if s["counseling_case_id"] == case_id]
    if counselor_id is not None:
        items = [s for s in items if s["counselor_id"] == counselor_id]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/counseling-sessions/<sid>", methods=["GET"])
def get_session(sid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    s = lookup("counseling_sessions", sid, "ERR_SESSION_NOT_FOUND")
    return ok(out(s), 200)


@app.route("/counseling-sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    s = lookup("counseling_sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session must be SCHEDULED")
    s["status"] = "COMPLETED"
    touch(s)
    return ok(out(s), 200)


@app.route("/counseling-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    s = lookup("counseling_sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session must be SCHEDULED")
    s["status"] = "CANCELLED"
    touch(s)
    case = DB["counseling_cases"].get(s["counseling_case_id"])
    if case:
        recompute_case_sessions(case)
    return ok(out(s), 200)


@app.route("/counseling-sessions/<sid>/no-show", methods=["POST"])
def noshow_session(sid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    s = lookup("counseling_sessions", sid, "ERR_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session must be SCHEDULED")
    s["status"] = "NO_SHOW"
    touch(s)
    return ok(out(s), 200)


# ===========================================================================
# TestOrder
# ===========================================================================
@app.route("/test-orders", methods=["POST"])
def create_order():
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    if isinstance(body.get("counseling_case_id"), str) and body["counseling_case_id"]:
        lookup("counseling_cases", body["counseling_case_id"], "ERR_CASE_NOT_FOUND")
    if isinstance(body.get("lab_id"), str) and body["lab_id"]:
        lookup("labs", body["lab_id"], "ERR_LAB_NOT_FOUND")
    case_id = req_str(body, "counseling_case_id")
    lab_id = req_str(body, "lab_id")
    panel_name = req_str(body, "panel_name")
    list_price = req_int(body, "list_price_cents", minimum=0)
    start_raw = req_str(body, "processing_start")
    end_raw = req_str(body, "processing_end")
    start_dt = parse_dt(start_raw, "processing_start")
    end_dt = parse_dt(end_raw, "processing_end")
    if not (end_dt > start_dt):
        verr("processing_end must be strictly after processing_start")
    cpt_codes = body.get("cpt_codes", [])
    if cpt_codes is None:
        cpt_codes = []
    if not isinstance(cpt_codes, list) or not all(isinstance(x, str) for x in cpt_codes):
        verr("cpt_codes must be an array of strings")
    order = base_entity({
        "counseling_case_id": case_id,
        "lab_id": lab_id,
        "panel_name": panel_name,
        "cpt_codes": cpt_codes,
        "list_price_cents": list_price,
        "processing_start": start_raw,
        "processing_end": end_raw,
        "status": "DRAFT",
    })
    DB["test_orders"][order["id"]] = order
    return ok(out(order), 201)


@app.route("/test-orders", methods=["GET"])
def list_orders():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["test_orders"].values())
    case_id = request.args.get("counseling_case_id")
    lab_id = request.args.get("lab_id")
    if case_id is not None:
        items = [o for o in items if o["counseling_case_id"] == case_id]
    if lab_id is not None:
        items = [o for o in items if o["lab_id"] == lab_id]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/test-orders/<oid>", methods=["GET"])
def get_order(oid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    o = lookup("test_orders", oid, "ERR_ORDER_NOT_FOUND")
    return ok(out(o), 200)


@app.route("/test-orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    order = lookup("test_orders", oid, "ERR_ORDER_NOT_FOUND")
    case = DB["counseling_cases"].get(order["counseling_case_id"])
    lab = DB["labs"].get(order["lab_id"])
    # state (priority 7)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "Order must be DRAFT to submit")
    if not case or case["clinical_status"] != "RISK_ASSESSED":
        raise ApiError("ERR_CASE_INVALID_CLINICAL_STATE", 409, "Case must be RISK_ASSESSED")
    # consent (priority 8)
    if not _case_has_signed_testing_consent(order["counseling_case_id"]):
        raise ApiError("ERR_CONSENT_REQUIRED", 409, "A SIGNED TESTING consent is required")
    # lab capacity (priority 10)
    start_dt = parse_dt(order["processing_start"], "processing_start")
    end_dt = parse_dt(order["processing_end"], "processing_end")
    overlapping = 0
    for o in DB["test_orders"].values():
        if o["id"] == order["id"]:
            continue
        if o["lab_id"] == lab["id"] and o["status"] == "SUBMITTED":
            o_start = parse_dt(o["processing_start"], "processing_start")
            o_end = parse_dt(o["processing_end"], "processing_end")
            if overlaps(start_dt, end_dt, o_start, o_end):
                overlapping += 1
    if overlapping >= lab["max_concurrent_capacity"]:
        raise ApiError("ERR_LAB_CAPACITY_EXCEEDED", 409, "Lab concurrent capacity exceeded")
    order["status"] = "SUBMITTED"
    touch(order)
    recompute_lab_load(lab)
    case["clinical_status"] = "TESTING"
    touch(case)
    return ok(out(order), 200)


def _case_has_signed_testing_consent(case_id):
    for c in DB["consent_records"].values():
        if (c["counseling_case_id"] == case_id and c["consent_type"] == "TESTING"
                and c["status"] == "SIGNED"):
            return True
    return False


@app.route("/test-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    order = lookup("test_orders", oid, "ERR_ORDER_NOT_FOUND")
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "Order cannot be cancelled")
    order["status"] = "CANCELLED"
    touch(order)
    lab = DB["labs"].get(order["lab_id"])
    if lab:
        recompute_lab_load(lab)
    return ok(out(order), 200)


# ===========================================================================
# TestResult
# ===========================================================================
@app.route("/test-results", methods=["POST"])
def create_result():
    _uid, role = authenticate()
    authorize(role, {"LabTechnician"})
    body = get_body()
    if isinstance(body.get("test_order_id"), str) and body["test_order_id"]:
        lookup("test_orders", body["test_order_id"], "ERR_ORDER_NOT_FOUND")
    order_id = req_str(body, "test_order_id")
    gene = req_str(body, "gene")
    variant = req_str(body, "variant")
    classification = req_enum(body, "classification", CLASSIFICATION)
    order = DB["test_orders"][order_id]
    if order["status"] != "SUBMITTED":
        raise ApiError("ERR_ORDER_INVALID_STATE", 409, "Order must be SUBMITTED to enter a result")
    result = base_entity({
        "test_order_id": order_id,
        "gene": gene,
        "variant": variant,
        "classification": classification,
        "is_actionable": None,
        "status": "PENDING",
    })
    DB["test_results"][result["id"]] = result
    order["status"] = "RESULTED"
    touch(order)
    lab = DB["labs"].get(order["lab_id"])
    if lab:
        recompute_lab_load(lab)
    return ok(out(result), 201)


@app.route("/test-results", methods=["GET"])
def list_results():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["test_results"].values())
    order_id = request.args.get("test_order_id")
    if order_id is not None:
        items = [r for r in items if r["test_order_id"] == order_id]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/test-results/<rid>", methods=["GET"])
def get_result(rid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    r = lookup("test_results", rid, "ERR_RESULT_NOT_FOUND")
    return ok(out(r), 200)


@app.route("/test-results/<rid>/release", methods=["POST"])
def release_result(rid):
    uid, role = authenticate()
    authorize(role, {"LabTechnician"})
    result = lookup("test_results", rid, "ERR_RESULT_NOT_FOUND")
    order = DB["test_orders"].get(result["test_order_id"])
    # ownership (priority 4) before state (priority 7)
    if not order or order["lab_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting lab does not own the parent order")
    if result["status"] != "PENDING":
        raise ApiError("ERR_RESULT_INVALID_STATE", 409, "Result must be PENDING to release")
    result["status"] = "RELEASED"
    result["is_actionable"] = result["classification"] in ("PATHOGENIC", "LIKELY_PATHOGENIC")
    touch(result)
    return ok(out(result), 200)


@app.route("/test-results/<rid>/disclose", methods=["POST"])
def disclose_result(rid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    result = lookup("test_results", rid, "ERR_RESULT_NOT_FOUND")
    order = DB["test_orders"].get(result["test_order_id"])
    case = DB["counseling_cases"].get(order["counseling_case_id"]) if order else None
    # state (priority 7): result RELEASED, then case TESTING
    if result["status"] != "RELEASED":
        raise ApiError("ERR_RESULT_INVALID_STATE", 409, "Result must be RELEASED to disclose")
    if not case or case["clinical_status"] != "TESTING":
        raise ApiError("ERR_CASE_INVALID_CLINICAL_STATE", 409, "Case must be TESTING")
    # A: result -> DISCLOSED
    result["status"] = "DISCLOSED"
    touch(result)
    # B: carrier_result + residual + tier; case -> DISCLOSED
    carrier = carrier_from_classification(result["classification"])
    case["carrier_result"] = carrier
    case["residual_risk_pct"] = compute_residual_risk(case, carrier)
    case["risk_tier"] = compute_risk_tier(case.get("prior_risk_pct"), case.get("residual_risk_pct"))
    case["clinical_status"] = "DISCLOSED"
    touch(case)
    # C: if actionable, auto-create ACTIVE surveillance plan; case -> SURVEILLANCE
    if result["is_actionable"]:
        tier = case["risk_tier"]
        plan = base_entity({
            "counseling_case_id": case["id"],
            "risk_tier": tier,
            "modalities": [],
            "screening_interval_months": INTERVAL_BY_TIER[tier],
            "status": "ACTIVE",
        })
        DB["surveillance_plans"][plan["id"]] = plan
        case["clinical_status"] = "SURVEILLANCE"
        touch(case)
        # D: if plan risk_tier HIGH, auto-create PENDING referral
        if tier == "HIGH":
            referral = base_entity({
                "counseling_case_id": case["id"],
                "surveillance_plan_id": plan["id"],
                "specialty": "HIGH_RISK_CLINIC",
                "reason": "Auto-generated from high-risk surveillance plan",
                "urgency": "ROUTINE",
                "status": "PENDING",
            })
            DB["referrals"][referral["id"]] = referral
    return ok(out(result), 200)


# ===========================================================================
# CascadeInvitation
# ===========================================================================
@app.route("/cascade-invitations", methods=["POST"])
def create_invitation():
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    if isinstance(body.get("family_id"), str) and body["family_id"]:
        lookup("families", body["family_id"], "ERR_FAMILY_NOT_FOUND")
    if isinstance(body.get("proband_case_id"), str) and body["proband_case_id"]:
        lookup("counseling_cases", body["proband_case_id"], "ERR_CASE_NOT_FOUND")
    if isinstance(body.get("pedigree_member_id"), str) and body["pedigree_member_id"]:
        lookup("pedigree_members", body["pedigree_member_id"], "ERR_PEDIGREE_MEMBER_NOT_FOUND")
    family_id = req_str(body, "family_id")
    proband_case_id = req_str(body, "proband_case_id")
    pedigree_member_id = req_str(body, "pedigree_member_id")
    relative_name = req_str(body, "relative_name")
    relationship = req_enum(body, "relationship", INVITE_REL)
    degree = require(body, "degree")
    if isinstance(degree, bool) or not isinstance(degree, int) or degree not in (1, 2, 3):
        verr("degree must be one of 1,2,3")
    contact_method = req_enum(body, "contact_method", CONTACT_METHOD)
    expires_raw = req_str(body, "expires_at")
    parse_dt(expires_raw, "expires_at")
    cost = invitation_cost(contact_method, degree)
    inv = base_entity({
        "family_id": family_id,
        "proband_case_id": proband_case_id,
        "pedigree_member_id": pedigree_member_id,
        "relative_name": relative_name,
        "relationship": relationship,
        "degree": degree,
        "contact_method": contact_method,
        "estimated_cost_cents": cost,
        "expires_at": expires_raw,
        "status": "DRAFT",
    })
    DB["cascade_invitations"][inv["id"]] = inv
    return ok(out(inv), 201)


@app.route("/cascade-invitations", methods=["GET"])
def list_invitations():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["cascade_invitations"].values())
    family_id = request.args.get("family_id")
    proband = request.args.get("proband_case_id")
    member = request.args.get("pedigree_member_id")
    if family_id is not None:
        items = [i for i in items if i["family_id"] == family_id]
    if proband is not None:
        items = [i for i in items if i["proband_case_id"] == proband]
    if member is not None:
        items = [i for i in items if i["pedigree_member_id"] == member]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/cascade-invitations/<iid>", methods=["GET"])
def get_invitation(iid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    i = lookup("cascade_invitations", iid, "ERR_INVITATION_NOT_FOUND")
    return ok(out(i), 200)


def _proband_has_actionable_disclosed(case_id):
    order_ids = {o["id"] for o in DB["test_orders"].values() if o["counseling_case_id"] == case_id}
    for r in DB["test_results"].values():
        if (r["test_order_id"] in order_ids and r["status"] == "DISCLOSED"
                and r.get("is_actionable")):
            return True
    return False


@app.route("/cascade-invitations/<iid>/send", methods=["POST"])
def send_invitation(iid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    inv = lookup("cascade_invitations", iid, "ERR_INVITATION_NOT_FOUND")
    # state (priority 7)
    if inv["status"] not in ("DRAFT", "DECLINED"):
        raise ApiError("ERR_INVITATION_INVALID_STATE", 409, "Invitation must be DRAFT or DECLINED to send")
    # actionable (priority 9)
    if not _proband_has_actionable_disclosed(inv["proband_case_id"]):
        raise ApiError("ERR_RESULT_NOT_ACTIONABLE", 409,
                       "Proband must have a DISCLOSED actionable result")
    # fiscal budget (priority 12)
    family = DB["families"].get(inv["family_id"])
    if not family or family["outreach_available_cents"] < inv["estimated_cost_cents"]:
        raise ApiError("ERR_OUTREACH_BUDGET_EXCEEDED", 402, "Insufficient outreach budget")
    inv["status"] = "SENT"
    touch(inv)
    recompute_family(family)
    return ok(out(inv), 200)


@app.route("/cascade-invitations/<iid>/decline", methods=["POST"])
def decline_invitation(iid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    inv = lookup("cascade_invitations", iid, "ERR_INVITATION_NOT_FOUND")
    if inv["status"] != "SENT":
        raise ApiError("ERR_INVITATION_INVALID_STATE", 409, "Invitation must be SENT to decline")
    inv["status"] = "DECLINED"
    touch(inv)
    family = DB["families"].get(inv["family_id"])
    if family:
        recompute_family(family)
    return ok(out(inv), 200)


@app.route("/cascade-invitations/<iid>/accept", methods=["POST"])
def accept_invitation(iid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    inv = lookup("cascade_invitations", iid, "ERR_INVITATION_NOT_FOUND")
    if inv["status"] != "SENT":
        raise ApiError("ERR_INVITATION_INVALID_STATE", 409, "Invitation must be SENT to accept")
    body = get_body()
    patient_dob = body.get("patient_dob")
    if patient_dob is not None and not isinstance(patient_dob, str):
        verr("patient_dob must be a string")
    covered = body.get("covered_sessions")
    if covered is None:
        covered = 0
    elif isinstance(covered, bool) or not isinstance(covered, int) or covered < 0:
        verr("covered_sessions must be a non-negative integer")
    inv["status"] = "ACCEPTED"
    touch(inv)
    proband = DB["counseling_cases"].get(inv["proband_case_id"])
    new_case = _new_case({
        "family_id": inv["family_id"],
        "assigned_counselor_id": proband["assigned_counselor_id"] if proband else None,
        "originating_invitation_id": inv["id"],
        "patient_name": inv["relative_name"],
        "patient_dob": patient_dob,
        "sex": proband["sex"] if proband else None,
        "ancestry": proband["ancestry"] if proband else None,
        "relationship_to_proband": DEG_TO_REL.get(inv["degree"], "PROBAND"),
        "referral_reason": "Cascade testing from accepted invitation",
        "familial_variant_known": True,
        "covered_sessions": covered,
        "sessions_remaining": covered,
    })
    DB["counseling_cases"][new_case["id"]] = new_case
    family = DB["families"].get(inv["family_id"])
    if family:
        recompute_family(family)
    return ok(out(inv), 200)


@app.route("/cascade-invitations/<iid>/expire", methods=["POST"])
def expire_invitation(iid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    inv = lookup("cascade_invitations", iid, "ERR_INVITATION_NOT_FOUND")
    if inv["status"] != "SENT":
        raise ApiError("ERR_INVITATION_INVALID_STATE", 409, "Invitation must be SENT to expire")
    expires_dt = parse_dt(inv["expires_at"], "expires_at")
    if LOGICAL_CLOCK["dt"] < expires_dt:
        raise ApiError("ERR_INVITATION_NOT_EXPIRABLE", 409,
                       "Invitation cannot expire before expires_at")
    inv["status"] = "EXPIRED"
    touch(inv)
    family = DB["families"].get(inv["family_id"])
    if family:
        recompute_family(family)
    return ok(out(inv), 200)


# ===========================================================================
# InsuranceClaim
# ===========================================================================
@app.route("/insurance-claims", methods=["POST"])
def create_claim():
    _uid, role = authenticate()
    authorize(role, {"BillingSpecialist"})
    body = get_body()
    if isinstance(body.get("counseling_case_id"), str) and body["counseling_case_id"]:
        lookup("counseling_cases", body["counseling_case_id"], "ERR_CASE_NOT_FOUND")
    if isinstance(body.get("test_order_id"), str) and body["test_order_id"]:
        lookup("test_orders", body["test_order_id"], "ERR_ORDER_NOT_FOUND")
    case_id = req_str(body, "counseling_case_id")
    order_id = req_str(body, "test_order_id")
    payer_name = req_str(body, "payer_name")
    member_number = req_str(body, "member_number")
    coverage_pct = req_rate(body, "coverage_pct")
    estimated_allowed_rate = req_rate(body, "estimated_allowed_rate")
    line_items = require(body, "line_items")
    if not isinstance(line_items, list) or len(line_items) == 0:
        verr("line_items must be a non-empty array")
    for li in line_items:
        if not isinstance(li, dict) or "cpt" not in li or "billed_cents" not in li:
            verr("each line item must have cpt and billed_cents")
        if not isinstance(li["cpt"], str):
            verr("line item cpt must be a string")
        if isinstance(li["billed_cents"], bool) or not isinstance(li["billed_cents"], int):
            verr("line item billed_cents must be an integer")
    # uniqueness (priority 11)
    for c in DB["insurance_claims"].values():
        if c["counseling_case_id"] == case_id and c["status"] != "VOID":
            raise ApiError("ERR_CLAIM_ALREADY_EXISTS", 409, "A non-VOID claim already exists")
    billed_total = sum(li["billed_cents"] for li in line_items)
    claim = base_entity({
        "counseling_case_id": case_id,
        "test_order_id": order_id,
        "payer_name": payer_name,
        "member_number": member_number,
        "coverage_pct": coverage_pct,
        "estimated_allowed_rate": estimated_allowed_rate,
        "line_items": line_items,
        "billed_total_cents": billed_total,
        "estimated_allowed_cents": None,
        "final_allowed_cents": None,
        "patient_responsibility_cents": None,
        "status": "DRAFT",
    })
    DB["insurance_claims"][claim["id"]] = claim
    case = DB["counseling_cases"][case_id]
    case["billing_status"] = "PENDING_AUTH"
    touch(case)
    return ok(out(claim), 201)


@app.route("/insurance-claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["insurance_claims"].values())
    case_id = request.args.get("counseling_case_id")
    order_id = request.args.get("test_order_id")
    if case_id is not None:
        items = [c for c in items if c["counseling_case_id"] == case_id]
    if order_id is not None:
        items = [c for c in items if c["test_order_id"] == order_id]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/insurance-claims/<cid>", methods=["GET"])
def get_claim(cid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = lookup("insurance_claims", cid, "ERR_CLAIM_NOT_FOUND")
    return ok(out(c), 200)


@app.route("/insurance-claims/<cid>/authorize", methods=["POST"])
def authorize_claim(cid):
    _uid, role = authenticate()
    authorize(role, {"BillingSpecialist"})
    claim = lookup("insurance_claims", cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "Claim must be DRAFT to authorize")
    est = rhu_int(Decimal(claim["billed_total_cents"]) * Decimal(str(claim["estimated_allowed_rate"])))
    claim["estimated_allowed_cents"] = est
    claim["status"] = "AUTHORIZED"
    touch(claim)
    case = DB["counseling_cases"].get(claim["counseling_case_id"])
    if case:
        case["billing_status"] = "AUTHORIZED"
        touch(case)
    return ok(out(claim), 200)


@app.route("/insurance-claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    _uid, role = authenticate()
    authorize(role, {"BillingSpecialist"})
    claim = lookup("insurance_claims", cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "AUTHORIZED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "Claim must be AUTHORIZED to submit")
    claim["status"] = "SUBMITTED"
    touch(claim)
    case = DB["counseling_cases"].get(claim["counseling_case_id"])
    if case:
        case["billing_status"] = "BILLED"
        touch(case)
    return ok(out(claim), 200)


@app.route("/insurance-claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    _uid, role = authenticate()
    authorize(role, {"BillingSpecialist"})
    claim = lookup("insurance_claims", cid, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    outcome = req_enum(body, "outcome", {"PAID", "DENIED"})
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "Claim must be SUBMITTED to adjudicate")
    case = DB["counseling_cases"].get(claim["counseling_case_id"])
    if outcome == "PAID":
        line_allowed = require(body, "line_allowed_cents")
        if not isinstance(line_allowed, list) or len(line_allowed) == 0:
            verr("line_allowed_cents must be a non-empty array")
        for x in line_allowed:
            if isinstance(x, bool) or not isinstance(x, int):
                verr("line_allowed_cents entries must be integers")
        final_allowed = sum(line_allowed)
        coverage = Decimal(str(claim["coverage_pct"]))
        patient = sum(
            rhu_int(Decimal(x) * (Decimal("1") - coverage)) for x in line_allowed
        )
        claim["final_allowed_cents"] = final_allowed
        claim["patient_responsibility_cents"] = patient
        claim["status"] = "PAID"
        touch(claim)
        if case:
            case["billing_status"] = "PAID"
            touch(case)
    else:  # DENIED
        claim["final_allowed_cents"] = 0
        claim["patient_responsibility_cents"] = 0
        claim["status"] = "DENIED"
        touch(claim)
        if case:
            case["billing_status"] = "DENIED"
            touch(case)
    return ok(out(claim), 200)


@app.route("/insurance-claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    _uid, role = authenticate()
    authorize(role, {"BillingSpecialist"})
    claim = lookup("insurance_claims", cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] not in ("DRAFT", "AUTHORIZED"):
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "Claim must be DRAFT or AUTHORIZED to void")
    claim["status"] = "VOID"
    touch(claim)
    case = DB["counseling_cases"].get(claim["counseling_case_id"])
    if case:
        case["billing_status"] = "UNBILLED"
        touch(case)
    return ok(out(claim), 200)


# ===========================================================================
# SurveillancePlan
# ===========================================================================
@app.route("/surveillance-plans", methods=["POST"])
def create_plan():
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    if isinstance(body.get("counseling_case_id"), str) and body["counseling_case_id"]:
        lookup("counseling_cases", body["counseling_case_id"], "ERR_CASE_NOT_FOUND")
    case_id_raw = body.get("counseling_case_id")
    case = DB["counseling_cases"].get(case_id_raw) if isinstance(case_id_raw, str) else None
    # OCC (priority 5): if a version is supplied and mismatches, reject before body validation
    exp = body.get("expected_counseling_case_version")
    if case is not None and exp is not None and not isinstance(exp, bool) and isinstance(exp, int):
        if exp != case["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "Stale counseling case version")
    # body validation (priority 6)
    case_id = req_str(body, "counseling_case_id")
    expected = require(body, "expected_counseling_case_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        verr("expected_counseling_case_version must be an integer")
    modalities = body.get("modalities", [])
    if modalities is None:
        modalities = []
    if not isinstance(modalities, list) or not all(isinstance(x, str) for x in modalities):
        verr("modalities must be an array of strings")
    case = DB["counseling_cases"][case_id]
    # In case OCC was skipped above due to type edge, enforce now
    if expected != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale counseling case version")
    # state (priority 7)
    if case["clinical_status"] != "DISCLOSED":
        raise ApiError("ERR_CASE_INVALID_CLINICAL_STATE", 409, "Case must be DISCLOSED")
    # supersede prior ACTIVE plan
    for p in DB["surveillance_plans"].values():
        if p["counseling_case_id"] == case_id and p["status"] == "ACTIVE":
            p["status"] = "SUPERSEDED"
            touch(p)
    tier = case["risk_tier"]
    plan = base_entity({
        "counseling_case_id": case_id,
        "risk_tier": tier,
        "modalities": modalities,
        "screening_interval_months": INTERVAL_BY_TIER.get(tier),
        "status": "ACTIVE",
    })
    DB["surveillance_plans"][plan["id"]] = plan
    case["clinical_status"] = "SURVEILLANCE"
    touch(case)
    return ok(out(plan), 201)


@app.route("/surveillance-plans", methods=["GET"])
def list_plans():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["surveillance_plans"].values())
    case_id = request.args.get("counseling_case_id")
    if case_id is not None:
        items = [p for p in items if p["counseling_case_id"] == case_id]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/surveillance-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    p = lookup("surveillance_plans", pid, "ERR_PLAN_NOT_FOUND")
    return ok(out(p), 200)


@app.route("/surveillance-plans/<pid>/close", methods=["POST"])
def close_plan(pid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    plan = lookup("surveillance_plans", pid, "ERR_PLAN_NOT_FOUND")
    body = get_body()
    outcome = req_enum(body, "outcome", {"COMPLETED", "CANCELLED"})
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "Plan must be ACTIVE to close")
    plan["status"] = outcome
    touch(plan)
    return ok(out(plan), 200)


# ===========================================================================
# Referral
# ===========================================================================
@app.route("/referrals", methods=["POST"])
def create_referral():
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    body = get_body()
    if isinstance(body.get("counseling_case_id"), str) and body["counseling_case_id"]:
        lookup("counseling_cases", body["counseling_case_id"], "ERR_CASE_NOT_FOUND")
    if isinstance(body.get("surveillance_plan_id"), str) and body["surveillance_plan_id"]:
        lookup("surveillance_plans", body["surveillance_plan_id"], "ERR_PLAN_NOT_FOUND")
    case_id = req_str(body, "counseling_case_id")
    specialty = req_enum(body, "specialty", SPECIALTY)
    reason = req_str(body, "reason")
    urgency = opt_enum(body, "urgency", URGENCY, "ROUTINE")
    plan_id = body.get("surveillance_plan_id")
    if plan_id is not None and not isinstance(plan_id, str):
        verr("surveillance_plan_id must be a string")
    referral = base_entity({
        "counseling_case_id": case_id,
        "surveillance_plan_id": plan_id,
        "specialty": specialty,
        "reason": reason,
        "urgency": urgency,
        "status": "PENDING",
    })
    DB["referrals"][referral["id"]] = referral
    return ok(out(referral), 201)


@app.route("/referrals", methods=["GET"])
def list_referrals():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(DB["referrals"].values())
    case_id = request.args.get("counseling_case_id")
    plan_id = request.args.get("surveillance_plan_id")
    if case_id is not None:
        items = [r for r in items if r["counseling_case_id"] == case_id]
    if plan_id is not None:
        items = [r for r in items if r.get("surveillance_plan_id") == plan_id]
    data, list_meta = paginate(items)
    return ok(data, 200, list_meta)


@app.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    r = lookup("referrals", rid, "ERR_REFERRAL_NOT_FOUND")
    return ok(out(r), 200)


@app.route("/referrals/<rid>/close", methods=["POST"])
def close_referral(rid):
    _uid, role = authenticate()
    authorize(role, {"GeneticCounselor"})
    referral = lookup("referrals", rid, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    outcome = req_enum(body, "outcome", {"COMPLETED", "CANCELLED"})
    if referral["status"] != "PENDING":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "Referral must be PENDING to close")
    referral["status"] = outcome
    touch(referral)
    return ok(out(referral), 200)


# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
