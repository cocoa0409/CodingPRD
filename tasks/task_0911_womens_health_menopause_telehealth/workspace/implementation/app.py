"""
Women's Health & Menopause Telehealth API — Flask reference implementation.

In-memory only. Store starts empty on every boot. No seeding of entities.
Logical clock drives all minted timestamps (default 2026-05-01T00:00:00Z).
"""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_instant():
    return fmt_instant(CLOCK)


def clock_date():
    return CLOCK.date()


def now_date_str():
    return CLOCK.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "patients": {},
    "providers": {},
    "policies": {},
    "intakes": {},
    "visits": {},
    "prescriptions": {},
    "lab_orders": {},
    "refills": {},
    "subscriptions": {},
    "charges": {},
    "care_plans": {},
    "messages": {},
}

_SEQ = 0


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def common_fields():
    ts = now_instant()
    return {"created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def touch(ent):
    ent["updated_at"] = now_instant()
    ent["version"] = ent.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Errors / responses
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def meta(pagination=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_instant()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    return (
        jsonify({"meta": meta(pagination), "response_type": response_type, "data": data}),
        status,
    )


@app.errorhandler(ApiError)
def handle_api_error(e):
    return (
        jsonify(
            {
                "meta": meta(),
                "response_type": "error",
                "data": {"error_id": e.error_id, "message": e.message},
            }
        ),
        e.http_status,
    )


@app.errorhandler(404)
def handle_404(e):
    return (
        jsonify(
            {
                "meta": meta(),
                "response_type": "error",
                "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
            }
        ),
        404,
    )


@app.errorhandler(405)
def handle_405(e):
    return (
        jsonify(
            {
                "meta": meta(),
                "response_type": "error",
                "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
            }
        ),
        405,
    )


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
ROLES = {"Patient", "Provider", "BillingAdmin", "CareCoordinator"}
ALL_ROLES = ["Patient", "Provider", "BillingAdmin", "CareCoordinator"]


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", 401, "Missing or invalid auth context")
    return uid, role


def require(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body helpers / validation
# ---------------------------------------------------------------------------
def body_json():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return b


def verr(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def require_present(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            verr("Missing required field: %s" % f)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        verr("Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        verr("Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        verr("Field %s must be >= %s" % (field, minimum))
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        verr("Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        verr("Field %s must be a number" % field)
    return v


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def serialize(kind, ent):
    if kind == "care_plans":
        d = pub(ent)
        rp, pp, st = compute_adherence(ent)
        d["realized_pdc"] = rp
        d["projected_pdc"] = pp
        d["adherence_status"] = st
        return d
    return pub(ent)


# ---------------------------------------------------------------------------
# Pagination + list helpers
# ---------------------------------------------------------------------------
def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            verr("limit must be an integer")
        if limit < 1 or limit > 100:
            verr("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            verr("offset must be an integer")
        if offset < 0:
            verr("offset must be >= 0")
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


def list_response(kind, items):
    page, pagination = paginate(items)
    data = [serialize(kind, e) for e in page]
    return ok(data, 200, "array", pagination)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(kind, _id, err):
    ent = DB[kind].get(_id)
    if ent is None:
        raise ApiError(err, 404, "%s not found" % kind)
    return ent


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
CASH_DISCOUNT_RATE = Decimal("0.10")


def price(billing_mode, allowed, policy):
    """Return (responsibility, deductible_applied, insurance_paid)."""
    if billing_mode == "CASH":
        resp = int((Decimal(allowed) * (Decimal("1") - CASH_DISCOUNT_RATE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return resp, 0, 0
    # INSURANCE
    if policy is None:
        # No coverage on record: patient responsible for full allowed amount.
        return allowed, 0, 0
    rem = policy["remaining_deductible_cents"]
    ded_portion = min(rem, allowed)
    after = allowed - ded_portion
    coins = int((Decimal(after) * Decimal(str(policy["coinsurance_rate"]))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    pre = ded_portion + coins
    oop_room = policy["out_of_pocket_max_cents"] - policy["oop_accumulated_cents"]
    resp = min(pre, oop_room)
    ded_applied = ded_portion
    insurance_paid = allowed - resp
    return resp, ded_applied, insurance_paid


def patient_policy(patient_id):
    for p in DB["policies"].values():
        if p["patient_id"] == patient_id:
            return p
    return None


def create_charge(patient, billable_kind, billable_id, allowed_amount):
    billing_mode = patient["billing_mode"]
    policy = patient_policy(patient["id"]) if billing_mode == "INSURANCE" else None
    ch = common_fields()
    ch["id"] = new_id()
    ch["patient_id"] = patient["id"]
    ch["billable_kind"] = billable_kind
    ch["billable_id"] = billable_id
    ch["insurance_policy_id"] = policy["id"] if policy else None
    ch["billing_mode"] = billing_mode
    ch["allowed_amount_cents"] = allowed_amount
    resp, _ded, _paid = price(billing_mode, allowed_amount, policy)
    ch["estimated_patient_responsibility_cents"] = resp
    ch["final_patient_responsibility_cents"] = None
    ch["insurance_paid_cents"] = None
    ch["deductible_applied_cents"] = None
    ch["status"] = "ESTIMATED"
    DB["charges"][ch["id"]] = ch
    return ch


# ---------------------------------------------------------------------------
# Adherence
# ---------------------------------------------------------------------------
def refills_of(prescription_id):
    return [r for r in DB["refills"].values() if r["prescription_id"] == prescription_id]


def compute_adherence(care_plan):
    presc = DB["prescriptions"].get(care_plan["prescription_id"])
    if presc is None:
        return 0.0, 0.0, "NON_ADHERENT"
    start = date.fromisoformat(presc["coverage_start_date"])
    elapsed = max(1, (clock_date() - start).days)
    rf = refills_of(presc["id"])
    supplied_realized = sum(r["days_supply"] for r in rf if r["status"] == "FULFILLED")
    pending = sum(1 for r in rf if r["status"] in ("REQUESTED", "APPROVED"))
    supplied_projected = supplied_realized + presc["days_supply_per_fill"] * pending
    realized = (Decimal(min(supplied_realized, elapsed)) / Decimal(elapsed)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    projected = (Decimal(min(supplied_projected, elapsed)) / Decimal(elapsed)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    rp = float(realized)
    pp = float(projected)
    if rp < 0.80:
        st = "NON_ADHERENT"
    elif rp < 0.90:
        st = "AT_RISK"
    else:
        st = "ADHERENT"
    return rp, pp, st


# ---------------------------------------------------------------------------
# Care-plan messages
# ---------------------------------------------------------------------------
def append_message(care_plan_id, author_kind, message_type, body):
    m = {"id": new_id(), "created_at": now_instant(), "_seq": next_seq()}
    m["care_plan_id"] = care_plan_id
    m["author_kind"] = author_kind
    m["message_type"] = message_type
    m["body"] = body
    DB["messages"][m["id"]] = m
    return m


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def deny_refill(refill, reason):
    refill["status"] = "DENIED"
    refill["denial_reason"] = reason
    touch(refill)
    presc = DB["prescriptions"].get(refill["prescription_id"])
    if presc and presc.get("care_plan_id"):
        append_message(presc["care_plan_id"], "SYSTEM", "DENIAL_NOTICE", reason or "refill denied")


def suspend_prescription(presc, denial_reason="prescription suspended", suspension_notice=False):
    presc["status"] = "SUSPENDED"
    touch(presc)
    if suspension_notice and presc.get("care_plan_id"):
        append_message(presc["care_plan_id"], "SYSTEM", "SUSPENSION_NOTICE", "prescription suspended")
    for r in refills_of(presc["id"]):
        if r["status"] == "REQUESTED":
            deny_refill(r, denial_reason)


def reverse_charge_effects(charge):
    """Restore policy accumulators and mark charge REVERSED."""
    if charge["billing_mode"] == "INSURANCE" and charge.get("insurance_policy_id"):
        policy = DB["policies"].get(charge["insurance_policy_id"])
        if policy:
            ded = charge.get("deductible_applied_cents") or 0
            resp = charge.get("final_patient_responsibility_cents") or 0
            policy["remaining_deductible_cents"] += ded
            policy["consumed_deductible_cents"] -= ded
            policy["oop_accumulated_cents"] -= resp
            touch(policy)
    charge["status"] = "REVERSED"
    touch(charge)


# ===========================================================================
# ROUTES
# ===========================================================================

# --- Logical clock ---
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    uid, role = auth()
    require(role, ["BillingAdmin"])
    body = body_json()
    require_present(body, ["to_iso8601"])
    try:
        CLOCK = parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        verr("to_iso8601 must be a valid ISO-8601 instant")
    return ok({}, 200, "object")


# --- Patients ---
@app.route("/patients", methods=["POST"])
def create_patient():
    uid, role = auth()
    require(role, ["CareCoordinator"])
    body = body_json()
    require_present(body, ["full_name", "email", "date_of_birth", "state_code", "billing_mode", "menopause_stage"])
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    dob = require_str(body, "date_of_birth")
    state_code = require_str(body, "state_code")
    billing_mode = require_enum(body, "billing_mode", {"CASH", "INSURANCE"})
    menopause_stage = require_enum(body, "menopause_stage", {"PERIMENOPAUSE", "MENOPAUSE", "POSTMENOPAUSE", "UNKNOWN"})
    for p in DB["patients"].values():
        if p["email"] == email:
            verr("email already in use")
    ent = common_fields()
    ent["id"] = new_id()
    ent["full_name"] = full_name
    ent["email"] = email
    ent["date_of_birth"] = dob
    ent["state_code"] = state_code
    ent["billing_mode"] = billing_mode
    ent["menopause_stage"] = menopause_stage
    DB["patients"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


@app.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("patients", pid, "ERR_PATIENT_NOT_FOUND")
    return ok(pub(ent), 200, "object")


# --- Providers ---
@app.route("/providers", methods=["POST"])
def create_provider():
    uid, role = auth()
    require(role, ["CareCoordinator"])
    body = body_json()
    require_present(body, ["full_name", "specialty", "npi", "visit_fee_cents"])
    full_name = require_str(body, "full_name")
    specialty = require_enum(body, "specialty", {"GYNECOLOGY", "ENDOCRINOLOGY", "FAMILY_MEDICINE"})
    npi = require_str(body, "npi")
    visit_fee = require_int(body, "visit_fee_cents", minimum=0)
    ent = common_fields()
    ent["id"] = new_id()
    ent["full_name"] = full_name
    ent["specialty"] = specialty
    ent["npi"] = npi
    ent["visit_fee_cents"] = visit_fee
    DB["providers"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


# --- Insurance policies ---
@app.route("/patients/<pid>/insurance-policies", methods=["POST"])
def create_policy(pid):
    uid, role = auth()
    require(role, ["BillingAdmin"])
    patient = get_or_404("patients", pid, "ERR_PATIENT_NOT_FOUND")
    body = body_json()
    require_present(body, ["payer_name", "deductible_cents", "coinsurance_rate", "out_of_pocket_max_cents"])
    payer_name = require_str(body, "payer_name")
    deductible = require_int(body, "deductible_cents", minimum=0)
    coins_rate = require_number(body, "coinsurance_rate")
    if coins_rate < 0 or coins_rate > 1:
        verr("coinsurance_rate must be between 0 and 1")
    oop_max = require_int(body, "out_of_pocket_max_cents", minimum=0)
    if patient_policy(pid) is not None:
        raise ApiError("ERR_POLICY_ALREADY_EXISTS", 409, "Patient already has an insurance policy")
    ent = common_fields()
    ent["id"] = new_id()
    ent["patient_id"] = pid
    ent["payer_name"] = payer_name
    ent["deductible_cents"] = deductible
    ent["remaining_deductible_cents"] = deductible
    ent["consumed_deductible_cents"] = 0
    ent["coinsurance_rate"] = coins_rate
    ent["out_of_pocket_max_cents"] = oop_max
    ent["oop_accumulated_cents"] = 0
    DB["policies"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


@app.route("/patients/<pid>/insurance-policies", methods=["GET"])
def list_policies(pid):
    uid, role = auth()
    require(role, ALL_ROLES)
    get_or_404("patients", pid, "ERR_PATIENT_NOT_FOUND")
    items = [p for p in DB["policies"].values() if p["patient_id"] == pid]
    return list_response("policies", items)


# --- Intake assessments ---
DOMAINS = {"VASOMOTOR", "SLEEP", "MOOD", "GENITOURINARY", "COGNITIVE"}
CONDITIONS = {"BREAST_CANCER_HISTORY", "VTE_HISTORY", "UNDIAGNOSED_BLEEDING", "STROKE_HISTORY", "NONE"}
ABSOLUTE = {"BREAST_CANCER_HISTORY", "VTE_HISTORY", "UNDIAGNOSED_BLEEDING", "STROKE_HISTORY"}
DOMAIN_WEIGHT = {
    "VASOMOTOR": Decimal("1.0"),
    "SLEEP": Decimal("0.833"),
    "MOOD": Decimal("0.667"),
    "GENITOURINARY": Decimal("0.75"),
    "COGNITIVE": Decimal("0.6"),
}


@app.route("/patients/<pid>/intake-assessments", methods=["POST"])
def create_intake(pid):
    uid, role = auth()
    require(role, ["Patient"])
    patient = get_or_404("patients", pid, "ERR_PATIENT_NOT_FOUND")
    body = body_json()
    require_present(body, ["symptom_ratings", "reported_conditions"])
    ratings = body["symptom_ratings"]
    conditions = body["reported_conditions"]
    if not isinstance(ratings, list):
        verr("symptom_ratings must be an array")
    for r in ratings:
        if not isinstance(r, dict) or "domain" not in r or "severity" not in r:
            verr("each symptom rating requires domain and severity")
        if r["domain"] not in DOMAINS:
            verr("invalid symptom domain")
        sev = r["severity"]
        if isinstance(sev, bool) or not isinstance(sev, int) or sev < 0 or sev > 10:
            verr("severity must be an integer 0..10")
    if not isinstance(conditions, list):
        verr("reported_conditions must be an array")
    for c in conditions:
        if c not in CONDITIONS:
            verr("invalid reported condition")
    ent = common_fields()
    ent["id"] = new_id()
    ent["patient_id"] = pid
    ent["symptom_ratings"] = ratings
    ent["reported_conditions"] = conditions
    ent["symptom_severity_score"] = None
    ent["has_absolute_contraindication"] = None
    ent["submitted_at"] = None
    ent["status"] = "DRAFT"
    DB["intakes"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


@app.route("/intake-assessments/<iid>/submit", methods=["POST"])
def submit_intake(iid):
    uid, role = auth()
    require(role, ["Patient"])
    ent = get_or_404("intakes", iid, "ERR_INTAKE_NOT_FOUND")
    if ent["status"] != "DRAFT":
        raise ApiError("ERR_INTAKE_INVALID_STATE", 409, "Intake must be DRAFT to submit")
    # symptom severity score: round each per-domain contribution first, then sum, then round total
    total = Decimal("0")
    for r in ent["symptom_ratings"]:
        w = DOMAIN_WEIGHT[r["domain"]]
        contribution = (Decimal(r["severity"]) * w).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += contribution
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ent["symptom_severity_score"] = float(total)
    has_contra = any(c in ABSOLUTE for c in ent["reported_conditions"])
    ent["has_absolute_contraindication"] = has_contra
    ent["submitted_at"] = now_instant()
    ent["status"] = "FLAGGED" if has_contra else "CLEARED"
    touch(ent)
    return ok(pub(ent), 200, "object")


@app.route("/intake-assessments/<iid>/clear", methods=["POST"])
def clear_intake(iid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("intakes", iid, "ERR_INTAKE_NOT_FOUND")
    if ent["status"] != "FLAGGED":
        raise ApiError("ERR_INTAKE_INVALID_STATE", 409, "Intake must be FLAGGED to clear")
    ent["status"] = "CLEARED"
    touch(ent)
    return ok(pub(ent), 200, "object")


@app.route("/intake-assessments/<iid>", methods=["GET"])
def get_intake(iid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("intakes", iid, "ERR_INTAKE_NOT_FOUND")
    return ok(pub(ent), 200, "object")


@app.route("/patients/<pid>/intake-assessments", methods=["GET"])
def list_intakes(pid):
    uid, role = auth()
    require(role, ALL_ROLES)
    get_or_404("patients", pid, "ERR_PATIENT_NOT_FOUND")
    items = [i for i in DB["intakes"].values() if i["patient_id"] == pid]
    return list_response("intakes", items)


# --- Visits ---
@app.route("/visits", methods=["POST"])
def create_visit():
    uid, role = auth()
    require(role, ["Patient"])
    body = body_json()
    require_present(body, ["patient_id", "provider_id", "intake_assessment_id", "scheduled_start", "scheduled_end"])
    patient_id = require_str(body, "patient_id")
    provider_id = require_str(body, "provider_id")
    intake_id = require_str(body, "intake_assessment_id")
    sstart = require_str(body, "scheduled_start")
    send = require_str(body, "scheduled_end")
    try:
        dstart = parse_iso(sstart)
        dend = parse_iso(send)
    except (ValueError, TypeError):
        verr("scheduled_start/scheduled_end must be ISO-8601 instants")
    # existence (left to right)
    patient = get_or_404("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    get_or_404("providers", provider_id, "ERR_PROVIDER_NOT_FOUND")
    intake = get_or_404("intakes", intake_id, "ERR_INTAKE_NOT_FOUND")
    # ownership / mismatch
    if patient_id != uid or intake["patient_id"] != patient_id:
        raise ApiError("ERR_PATIENT_MISMATCH", 422, "Body foreign key does not belong to the acting patient")
    # intake must be submitted
    if intake["status"] not in ("CLEARED", "FLAGGED"):
        raise ApiError("ERR_INTAKE_NOT_SUBMITTED", 409, "Intake must be submitted (CLEARED or FLAGGED)")
    # provider slot overlap (half-open) — Conflict B high side
    for v in DB["visits"].values():
        if v["provider_id"] == provider_id and v["status"] == "SCHEDULED":
            vs = parse_iso(v["scheduled_start"])
            ve = parse_iso(v["scheduled_end"])
            if dstart < ve and vs < dend:
                raise ApiError("ERR_PROVIDER_SLOT_OVERLAP", 409, "Visit slot overlaps another scheduled visit")
    # past-due membership — Conflict B low side
    for s in DB["subscriptions"].values():
        if s["patient_id"] == patient_id and s["status"] == "PAST_DUE":
            raise ApiError("ERR_SUBSCRIPTION_PAST_DUE", 402, "Patient has a past-due subscription")
    ent = common_fields()
    ent["id"] = new_id()
    ent["patient_id"] = patient_id
    ent["provider_id"] = provider_id
    ent["intake_assessment_id"] = intake_id
    ent["scheduled_start"] = sstart
    ent["scheduled_end"] = send
    ent["visit_charge_id"] = None
    ent["status"] = "SCHEDULED"
    DB["visits"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


@app.route("/visits/<vid>/complete", methods=["POST"])
def complete_visit(vid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("visits", vid, "ERR_VISIT_NOT_FOUND")
    if ent["status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_INVALID_STATE", 409, "Visit must be SCHEDULED to complete")
    patient = DB["patients"][ent["patient_id"]]
    provider = DB["providers"][ent["provider_id"]]
    charge = create_charge(patient, "VISIT", ent["id"], provider["visit_fee_cents"])
    ent["status"] = "COMPLETED"
    ent["visit_charge_id"] = charge["id"]
    touch(ent)
    return ok(pub(ent), 200, "object")


@app.route("/visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    uid, role = auth()
    require(role, ["Patient"])
    ent = get_or_404("visits", vid, "ERR_VISIT_NOT_FOUND")
    if ent["status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_INVALID_STATE", 409, "Visit must be SCHEDULED to cancel")
    ent["status"] = "CANCELLED"
    touch(ent)
    return ok(pub(ent), 200, "object")


@app.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("visits", vid, "ERR_VISIT_NOT_FOUND")
    return ok(pub(ent), 200, "object")


@app.route("/visits", methods=["GET"])
def list_visits():
    uid, role = auth()
    require(role, ALL_ROLES)
    items = list(DB["visits"].values())
    for key in ("patient_id", "provider_id", "intake_assessment_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    return list_response("visits", items)


# --- Prescriptions ---
HRT_TYPES = {"ESTROGEN_PATCH", "ESTROGEN_ORAL", "PROGESTERONE", "COMBINED", "VAGINAL_ESTROGEN"}
COVERAGE_BUFFER_DAYS = 7
INTAKE_VALIDITY_DAYS = 90


@app.route("/prescriptions", methods=["POST"])
def create_prescription():
    uid, role = auth()
    require(role, ["Provider"])
    body = body_json()
    require_present(body, ["visit_id", "hrt_type", "days_supply_per_fill", "total_refills_authorized",
                           "lab_required_before_refill", "coverage_days", "refill_price_cents"])
    visit_id = require_str(body, "visit_id")
    hrt_type = require_enum(body, "hrt_type", HRT_TYPES)
    days_supply = require_int(body, "days_supply_per_fill", minimum=1)
    total_refills = require_int(body, "total_refills_authorized", minimum=0)
    lab_required = body["lab_required_before_refill"]
    if not isinstance(lab_required, bool):
        verr("lab_required_before_refill must be a boolean")
    coverage_days = require_int(body, "coverage_days", minimum=0)
    refill_price = require_int(body, "refill_price_cents", minimum=0)
    # existence of visit (body FK)
    visit = get_or_404("visits", visit_id, "ERR_VISIT_NOT_FOUND")
    intake = DB["intakes"].get(visit["intake_assessment_id"])
    # visit COMPLETED and intake CLEARED
    if visit["status"] != "COMPLETED" or intake is None or intake["status"] != "CLEARED":
        raise ApiError("ERR_INTAKE_NOT_CLEARED", 409, "Prescription requires a COMPLETED visit with a CLEARED intake")
    # intake validity (within 90 days) — per PRD prose, before coverage window
    submitted = parse_iso(intake["submitted_at"])
    if (clock_date() - submitted.date()).days > INTAKE_VALIDITY_DAYS:
        raise ApiError("ERR_INTAKE_EXPIRED", 409, "Intake older than 90 days")
    # coverage window conflict for same patient + hrt_type
    patient_id = visit["patient_id"]
    new_start = clock_date()
    new_end = new_start + timedelta(days=coverage_days)
    for pr in DB["prescriptions"].values():
        if pr["patient_id"] == patient_id and pr["hrt_type"] == hrt_type and pr["status"] in ("ACTIVE", "SUSPENDED"):
            es = date.fromisoformat(pr["coverage_start_date"])
            ee = date.fromisoformat(pr["coverage_end_date"])
            if new_start > ee:
                gap = (new_start - ee).days
                conflict = gap < COVERAGE_BUFFER_DAYS
            elif es > new_end:
                gap = (es - new_end).days
                conflict = gap < COVERAGE_BUFFER_DAYS
            else:
                conflict = True  # overlap or touching
            if conflict:
                raise ApiError("ERR_COVERAGE_WINDOW_CONFLICT", 409, "Coverage window conflicts with an existing prescription")
    # create prescription
    ent = common_fields()
    ent["id"] = new_id()
    ent["patient_id"] = patient_id
    ent["provider_id"] = uid
    ent["visit_id"] = visit_id
    ent["care_plan_id"] = None
    ent["hrt_type"] = hrt_type
    ent["days_supply_per_fill"] = days_supply
    ent["total_refills_authorized"] = total_refills
    ent["refills_remaining"] = total_refills
    ent["lab_required_before_refill"] = lab_required
    ent["coverage_days"] = coverage_days
    ent["coverage_start_date"] = new_start.isoformat()
    ent["coverage_end_date"] = new_end.isoformat()
    ent["last_fill_date"] = None
    ent["refill_price_cents"] = refill_price
    ent["status"] = "ACTIVE"
    DB["prescriptions"][ent["id"]] = ent
    # auto-create care plan
    cp = common_fields()
    cp["id"] = new_id()
    cp["patient_id"] = patient_id
    cp["prescription_id"] = ent["id"]
    DB["care_plans"][cp["id"]] = cp
    ent["care_plan_id"] = cp["id"]
    return ok(pub(ent), 201, "object")


@app.route("/prescriptions/<prid>/suspend", methods=["POST"])
def suspend_rx(prid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    if ent["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_INVALID_STATE", 409, "Prescription must be ACTIVE to suspend")
    suspend_prescription(ent, "prescription suspended", suspension_notice=False)
    return ok(pub(ent), 200, "object")


@app.route("/prescriptions/<prid>/reactivate", methods=["POST"])
def reactivate_rx(prid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    if ent["status"] != "SUSPENDED":
        raise ApiError("ERR_PRESCRIPTION_INVALID_STATE", 409, "Prescription must be SUSPENDED to reactivate")
    if ent["lab_required_before_refill"] and not has_normal_lab(ent["id"]):
        raise ApiError("ERR_LAB_REQUIRED_BEFORE_REFILL", 409, "A REVIEWED NORMAL lab is required")
    for s in DB["subscriptions"].values():
        if s["patient_id"] == ent["patient_id"] and s["status"] == "PAST_DUE":
            raise ApiError("ERR_SUBSCRIPTION_PAST_DUE", 402, "Patient has a past-due subscription")
    ent["status"] = "ACTIVE"
    touch(ent)
    if ent.get("care_plan_id"):
        append_message(ent["care_plan_id"], "SYSTEM", "GENERAL", "prescription reactivated")
    return ok(pub(ent), 200, "object")


@app.route("/prescriptions/<prid>/discontinue", methods=["POST"])
def discontinue_rx(prid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    if ent["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_PRESCRIPTION_INVALID_STATE", 409, "Prescription must be ACTIVE or SUSPENDED to discontinue")
    ent["status"] = "DISCONTINUED"
    touch(ent)
    # cascade: cancel PENDING labs
    for lab in DB["lab_orders"].values():
        if lab["prescription_id"] == ent["id"] and lab["status"] == "PENDING":
            lab["status"] = "CANCELLED"
            touch(lab)
    # cascade: deny open refills (REQUESTED or APPROVED)
    for r in refills_of(ent["id"]):
        if r["status"] in ("REQUESTED", "APPROVED"):
            deny_refill(r, "prescription discontinued")
    return ok(pub(ent), 200, "object")


@app.route("/prescriptions/<prid>", methods=["GET"])
def get_rx(prid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    return ok(pub(ent), 200, "object")


@app.route("/prescriptions", methods=["GET"])
def list_rx():
    uid, role = auth()
    require(role, ALL_ROLES)
    items = list(DB["prescriptions"].values())
    for key in ("patient_id", "provider_id", "visit_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    return list_response("prescriptions", items)


# --- Lab orders ---
PANEL_TYPES = {"LIPID", "HORMONE", "LIVER", "MAMMOGRAM"}


def has_normal_lab(prescription_id):
    for lab in DB["lab_orders"].values():
        if lab["prescription_id"] == prescription_id and lab["status"] == "REVIEWED" and lab["result"] == "NORMAL":
            return True
    return False


@app.route("/prescriptions/<prid>/lab-orders", methods=["POST"])
def create_lab(prid):
    uid, role = auth()
    require(role, ["Provider"])
    presc = get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    body = body_json()
    require_present(body, ["panel_type"])
    panel = require_enum(body, "panel_type", PANEL_TYPES)
    ent = common_fields()
    ent["id"] = new_id()
    ent["prescription_id"] = prid
    ent["panel_type"] = panel
    ent["result"] = None
    ent["resulted_at"] = None
    ent["status"] = "PENDING"
    DB["lab_orders"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


@app.route("/lab-orders/<lid>/resolve", methods=["POST"])
def resolve_lab(lid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("lab_orders", lid, "ERR_LAB_ORDER_NOT_FOUND")
    body = body_json()
    require_present(body, ["result"])
    result = require_enum(body, "result", {"NORMAL", "ABNORMAL"})
    if ent["status"] != "PENDING":
        raise ApiError("ERR_LAB_ORDER_INVALID_STATE", 409, "Lab order must be PENDING to resolve")
    ent["result"] = result
    ent["resulted_at"] = now_date_str()
    ent["status"] = "REVIEWED"
    touch(ent)
    if result == "ABNORMAL":
        presc = DB["prescriptions"].get(ent["prescription_id"])
        if presc and presc["status"] == "ACTIVE":
            suspend_prescription(presc, "prescription suspended", suspension_notice=False)
    return ok(pub(ent), 200, "object")


@app.route("/lab-orders/<lid>", methods=["GET"])
def get_lab(lid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("lab_orders", lid, "ERR_LAB_ORDER_NOT_FOUND")
    return ok(pub(ent), 200, "object")


@app.route("/prescriptions/<prid>/lab-orders", methods=["GET"])
def list_labs(prid):
    uid, role = auth()
    require(role, ALL_ROLES)
    get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    items = [l for l in DB["lab_orders"].values() if l["prescription_id"] == prid]
    return list_response("lab_orders", items)


# --- Refills ---
def maybe_expire(presc):
    if presc["status"] == "ACTIVE" and clock_date() > date.fromisoformat(presc["coverage_end_date"]):
        presc["status"] = "EXPIRED"
        touch(presc)


@app.route("/prescriptions/<prid>/refills", methods=["POST"])
def request_refill(prid):
    uid, role = auth()
    require(role, ["Patient"])
    presc = get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    maybe_expire(presc)
    if presc["refills_remaining"] < 1:
        raise ApiError("ERR_NO_REFILLS_REMAINING", 409, "No refills remaining")
    ent = common_fields()
    ent["id"] = new_id()
    ent["prescription_id"] = prid
    ent["days_supply"] = None
    ent["fill_date"] = None
    ent["charge_id"] = None
    ent["denial_reason"] = None
    ent["status"] = "REQUESTED"
    DB["refills"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


@app.route("/refills/<rid>/approve", methods=["POST"])
def approve_refill(rid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("refills", rid, "ERR_REFILL_NOT_FOUND")
    presc = DB["prescriptions"][ent["prescription_id"]]
    if ent["status"] != "REQUESTED":
        raise ApiError("ERR_REFILL_INVALID_STATE", 409, "Refill must be REQUESTED to approve")
    maybe_expire(presc)
    # Conflict A high side: prescription-active before lab check
    if presc["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE", 409, "Prescription must be ACTIVE")
    if presc["lab_required_before_refill"] and not has_normal_lab(presc["id"]):
        raise ApiError("ERR_LAB_REQUIRED_BEFORE_REFILL", 409, "A REVIEWED NORMAL lab is required")
    ent["status"] = "APPROVED"
    touch(ent)
    return ok(pub(ent), 200, "object")


@app.route("/refills/<rid>/deny", methods=["POST"])
def deny_refill_ep(rid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("refills", rid, "ERR_REFILL_NOT_FOUND")
    if ent["status"] != "REQUESTED":
        raise ApiError("ERR_REFILL_INVALID_STATE", 409, "Refill must be REQUESTED to deny")
    body = body_json()
    reason = body.get("denial_reason")
    if reason is not None and not isinstance(reason, str):
        verr("denial_reason must be a string")
    deny_refill(ent, reason if reason else "refill denied")
    return ok(pub(ent), 200, "object")


@app.route("/refills/<rid>/fulfill", methods=["POST"])
def fulfill_refill(rid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("refills", rid, "ERR_REFILL_NOT_FOUND")
    presc = DB["prescriptions"][ent["prescription_id"]]
    if ent["status"] != "APPROVED":
        raise ApiError("ERR_REFILL_INVALID_STATE", 409, "Refill must be APPROVED to fulfill")
    if presc["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE", 409, "Prescription must be ACTIVE")
    patient = DB["patients"][presc["patient_id"]]
    ent["days_supply"] = presc["days_supply_per_fill"]
    ent["fill_date"] = now_date_str()
    charge = create_charge(patient, "REFILL", ent["id"], presc["refill_price_cents"])
    ent["charge_id"] = charge["id"]
    ent["status"] = "FULFILLED"
    touch(ent)
    presc["refills_remaining"] -= 1
    presc["last_fill_date"] = ent["fill_date"]
    touch(presc)
    return ok(pub(ent), 200, "object")


@app.route("/refills/<rid>/reverse", methods=["POST"])
def reverse_refill(rid):
    uid, role = auth()
    require(role, ["Provider"])
    ent = get_or_404("refills", rid, "ERR_REFILL_NOT_FOUND")
    if ent["status"] != "FULFILLED":
        raise ApiError("ERR_REFILL_INVALID_STATE", 409, "Refill must be FULFILLED to reverse")
    ent["status"] = "REVERSED"
    touch(ent)
    presc = DB["prescriptions"][ent["prescription_id"]]
    presc["refills_remaining"] += 1
    touch(presc)
    if ent.get("charge_id"):
        charge = DB["charges"].get(ent["charge_id"])
        if charge:
            if charge["status"] == "ESTIMATED":
                charge["status"] = "VOID"
                touch(charge)
            elif charge["status"] == "ADJUDICATED":
                reverse_charge_effects(charge)
    return ok(pub(ent), 200, "object")


@app.route("/refills/<rid>", methods=["GET"])
def get_refill(rid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("refills", rid, "ERR_REFILL_NOT_FOUND")
    return ok(pub(ent), 200, "object")


@app.route("/prescriptions/<prid>/refills", methods=["GET"])
def list_refills(prid):
    uid, role = auth()
    require(role, ALL_ROLES)
    get_or_404("prescriptions", prid, "ERR_PRESCRIPTION_NOT_FOUND")
    items = [r for r in DB["refills"].values() if r["prescription_id"] == prid]
    return list_response("refills", items)


# --- Subscriptions ---
PLAN_FEE = {"ESSENTIAL": 3900, "PLUS": 7900}


@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = auth()
    require(role, ["Patient"])
    body = body_json()
    require_present(body, ["patient_id", "plan_tier", "expected_patient_version"])
    patient_id = require_str(body, "patient_id")
    patient = get_or_404("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    # OCC before subscription business logic
    epv = body["expected_patient_version"]
    if isinstance(epv, bool) or not isinstance(epv, int):
        verr("expected_patient_version must be an integer")
    if epv != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION", 412, "expected_patient_version does not match patient version")
    plan_tier = require_enum(body, "plan_tier", {"ESSENTIAL", "PLUS"})
    # supersede prior ACTIVE/PAST_DUE
    for s in DB["subscriptions"].values():
        if s["patient_id"] == patient_id and s["status"] in ("ACTIVE", "PAST_DUE"):
            s["status"] = "SUPERSEDED"
            touch(s)
    touch(patient)  # increments Patient.version by 1
    ent = common_fields()
    ent["id"] = new_id()
    ent["patient_id"] = patient_id
    ent["plan_tier"] = plan_tier
    ent["monthly_fee_cents"] = PLAN_FEE[plan_tier]
    ent["started_at"] = now_instant()
    ent["status"] = "ACTIVE"
    DB["subscriptions"][ent["id"]] = ent
    return ok(pub(ent), 201, "object")


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = auth()
    require(role, ["Patient"])
    ent = get_or_404("subscriptions", sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if ent["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE", 409, "Subscription must be ACTIVE or PAST_DUE to cancel")
    ent["status"] = "CANCELLED"
    touch(ent)
    # cascade: suspend patient's ACTIVE prescriptions (each with SUSPENSION_NOTICE)
    for pr in DB["prescriptions"].values():
        if pr["patient_id"] == ent["patient_id"] and pr["status"] == "ACTIVE":
            suspend_prescription(pr, "prescription suspended", suspension_notice=True)
    return ok(pub(ent), 200, "object")


@app.route("/subscriptions/<sid>/mark-past-due", methods=["POST"])
def mark_past_due(sid):
    uid, role = auth()
    require(role, ["BillingAdmin"])
    ent = get_or_404("subscriptions", sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if ent["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE", 409, "Subscription must be ACTIVE to mark past due")
    ent["status"] = "PAST_DUE"
    touch(ent)
    return ok(pub(ent), 200, "object")


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("subscriptions", sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    return ok(pub(ent), 200, "object")


@app.route("/patients/<pid>/subscriptions", methods=["GET"])
def list_subscriptions(pid):
    uid, role = auth()
    require(role, ALL_ROLES)
    get_or_404("patients", pid, "ERR_PATIENT_NOT_FOUND")
    items = [s for s in DB["subscriptions"].values() if s["patient_id"] == pid]
    return list_response("subscriptions", items)


# --- Charges ---
@app.route("/charges/<cid>/adjudicate", methods=["POST"])
def adjudicate_charge(cid):
    uid, role = auth()
    require(role, ["BillingAdmin"])
    ent = get_or_404("charges", cid, "ERR_CHARGE_NOT_FOUND")
    if ent["status"] != "ESTIMATED":
        raise ApiError("ERR_CHARGE_INVALID_STATE", 409, "Charge must be ESTIMATED to adjudicate")
    allowed = ent["allowed_amount_cents"]
    if ent["billing_mode"] == "CASH":
        resp, ded, paid = price("CASH", allowed, None)
        ent["final_patient_responsibility_cents"] = resp
        ent["insurance_paid_cents"] = 0
        ent["deductible_applied_cents"] = 0
    else:
        policy = DB["policies"].get(ent["insurance_policy_id"]) if ent.get("insurance_policy_id") else None
        resp, ded, paid = price("INSURANCE", allowed, policy)
        ent["final_patient_responsibility_cents"] = resp
        ent["insurance_paid_cents"] = paid
        ent["deductible_applied_cents"] = ded
        if policy:
            policy["remaining_deductible_cents"] -= ded
            policy["consumed_deductible_cents"] += ded
            policy["oop_accumulated_cents"] += resp
            touch(policy)
    ent["status"] = "ADJUDICATED"
    touch(ent)
    return ok(pub(ent), 200, "object")


@app.route("/charges/<cid>/reverse", methods=["POST"])
def reverse_charge(cid):
    uid, role = auth()
    require(role, ["BillingAdmin"])
    ent = get_or_404("charges", cid, "ERR_CHARGE_NOT_FOUND")
    if ent["status"] != "ADJUDICATED":
        raise ApiError("ERR_CHARGE_INVALID_STATE", 409, "Charge must be ADJUDICATED to reverse")
    reverse_charge_effects(ent)
    return ok(pub(ent), 200, "object")


@app.route("/charges/<cid>", methods=["GET"])
def get_charge(cid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("charges", cid, "ERR_CHARGE_NOT_FOUND")
    return ok(pub(ent), 200, "object")


@app.route("/charges", methods=["GET"])
def list_charges():
    uid, role = auth()
    require(role, ALL_ROLES)
    items = list(DB["charges"].values())
    for key in ("patient_id", "billable_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    return list_response("charges", items)


# --- Care plans ---
@app.route("/care-plans/<cpid>", methods=["GET"])
def get_care_plan(cpid):
    uid, role = auth()
    require(role, ALL_ROLES)
    ent = get_or_404("care_plans", cpid, "ERR_CARE_PLAN_NOT_FOUND")
    return ok(serialize("care_plans", ent), 200, "object")


@app.route("/care-plans", methods=["GET"])
def list_care_plans():
    uid, role = auth()
    require(role, ALL_ROLES)
    items = list(DB["care_plans"].values())
    for key in ("patient_id", "prescription_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    return list_response("care_plans", items)


# --- Care-plan messages ---
MESSAGE_TYPES = {"GENERAL", "ADHERENCE_OUTREACH", "SUSPENSION_NOTICE", "DENIAL_NOTICE"}
ROLE_TO_AUTHOR = {"Patient": "PATIENT", "Provider": "PROVIDER", "CareCoordinator": "CARE_COORDINATOR"}


@app.route("/care-plans/<cpid>/messages", methods=["POST"])
def create_message(cpid):
    uid, role = auth()
    require(role, ["Patient", "Provider", "CareCoordinator"])
    get_or_404("care_plans", cpid, "ERR_CARE_PLAN_NOT_FOUND")
    body = body_json()
    require_present(body, ["body"])
    text = require_str(body, "body")
    message_type = body.get("message_type", "GENERAL")
    if message_type is None:
        message_type = "GENERAL"
    if message_type not in MESSAGE_TYPES:
        verr("invalid message_type")
    m = append_message(cpid, ROLE_TO_AUTHOR[role], message_type, text)
    return ok(pub(m), 201, "object")


@app.route("/care-plans/<cpid>/messages", methods=["GET"])
def list_messages(cpid):
    uid, role = auth()
    require(role, ALL_ROLES)
    get_or_404("care_plans", cpid, "ERR_CARE_PLAN_NOT_FOUND")
    items = [m for m in DB["messages"].values() if m["care_plan_id"] == cpid]
    return list_response("messages", items)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
