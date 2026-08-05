"""Men's Health & Hormone (TRT/ED) Clinic API — Flask reference implementation.

In-memory only. Logical clock. Deterministic timestamps.
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
# Logical clock
# ---------------------------------------------------------------------------
CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(CLOCK)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "clinicians": {},
    "pharmacists": {},
    "patients": {},
    "membership_plans": {},
    "memberships": {},
    "draw_stations": {},
    "lab_panels": {},
    "lab_draw_appointments": {},
    "telehealth_visits": {},
    "treatment_plans": {},
    "dose_titrations": {},
    "prescriptions": {},
    "refill_orders": {},
    "adverse_events": {},
}
_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_record(store, fields):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now_iso()
    rec["updated_at"] = now_iso()
    rec["version"] = 1
    rec["_seq"] = next_seq()
    store[rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(items, limit, offset, total):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
ROLES = {"ClinicAdmin", "Clinician", "Pharmacist", "Patient"}


def require(*allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "Missing or invalid X-User-ID / X-User-Role header")
    if allowed_roles and role not in allowed_roles:
        err("ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this operation")
    return uid, role


ALL_ROLES = ("ClinicAdmin", "Clinician", "Pharmacist", "Patient")


# ---------------------------------------------------------------------------
# Body helpers / validation
# ---------------------------------------------------------------------------
def get_body():
    if request.is_json:
        b = request.get_json(silent=True)
        if isinstance(b, dict):
            return b
    else:
        b = request.get_json(silent=True)
        if isinstance(b, dict):
            return b
    return {}


def _present(body, name):
    return name in body and body[name] is not None


def v_str(body, name, required=True):
    if not _present(body, name):
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str) or (required and v == ""):
        err("ERR_VALIDATION", 400, f"Field {name} must be a non-empty string")
    return v


def v_int(body, name, required=True, minimum=None, default=None):
    if not _present(body, name):
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 400, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, f"Field {name} out of range")
    return v


def v_num(body, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", 400, f"Field {name} must be a number")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, f"Field {name} out of range")
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", 400, f"Field {name} out of range")
    return v


def v_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if v not in allowed:
        err("ERR_VALIDATION", 400, f"Field {name} must be one of {sorted(allowed)}")
    return v


def v_bool(body, name, required=False, default=None):
    if not _present(body, name):
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 400, f"Field {name} must be a boolean")
    return v


def v_datetime(body, name, required=True):
    if not _present(body, name):
        if required:
            err("ERR_VALIDATION", 400, f"Missing required field: {name}")
        return None
    v = body[name]
    try:
        parse_iso(v)
    except Exception:
        err("ERR_VALIDATION", 400, f"Field {name} must be an ISO8601 datetime")
    return v


def must_exist(store, rid):
    if rid is None or rid not in store:
        err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return store[rid]


def exists_body_ref(store, body, name):
    """If a body id field is present, verify it resolves (404). Returns record or None."""
    if _present(body, name):
        rid = body[name]
        if not isinstance(rid, str) or rid not in store:
            err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
        return store[rid]
    return None


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def paginate_params():
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
    return limit, offset


def list_response(store, filters=None):
    items = list(store.values())
    if filters:
        for field, val in filters.items():
            if val is not None:
                items = [r for r in items if r.get(field) == val]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = paginate_params()
    page = items[offset:offset + limit]
    return respond_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def rhu(dec_value):
    return int(Decimal(dec_value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def patient_membership(patient_id):
    for m in DB["memberships"].values():
        if m["patient_id"] == patient_id:
            return m
    return None


def within_window(drawn_at_str, days=90):
    try:
        dt = parse_iso(drawn_at_str)
    except Exception:
        return False
    if dt > CLOCK:
        return False
    return (CLOCK - dt) <= timedelta(days=days)


def reviewed_panels_for(patient_id):
    return [p for p in DB["lab_panels"].values()
            if p["patient_id"] == patient_id and p["status"] == "REVIEWED"]


def latest_reviewed_panel(patient_id):
    panels = reviewed_panels_for(patient_id)
    if not panels:
        return None

    def keyfn(p):
        try:
            d = parse_iso(p.get("drawn_at")) if p.get("drawn_at") else datetime.min.replace(tzinfo=timezone.utc)
        except Exception:
            d = datetime.min.replace(tzinfo=timezone.utc)
        return (d, p["created_at"], p["_seq"])

    return max(panels, key=keyfn)


def tiered_drug_cost(unit_price_cents, units):
    t1 = min(units, 4)
    t2 = min(max(units - 4, 0), 10 - 4)
    t3 = max(units - 10, 0)
    tier2_unit = rhu(Decimal(unit_price_cents) * Decimal("0.90"))
    tier3_unit = rhu(Decimal(unit_price_cents) * Decimal("0.80"))
    return t1 * unit_price_cents + t2 * tier2_unit + t3 * tier3_unit


def refill_charge(prescription, plan, units):
    gross = tiered_drug_cost(prescription["unit_price_cents"], units)
    cs = 1500 if prescription.get("is_controlled", True) else 0
    discount = rhu(Decimal(gross) * Decimal(str(plan["refill_discount_pct"])))
    subtotal = gross + cs - discount
    return min(max(subtotal, 1000), 100000)


# ---- Cascades -------------------------------------------------------------
def revoke_prescription_cascade(pres):
    """Set prescription REVOKED and cancel its PENDING_REVIEW refill orders."""
    pres["status"] = "REVOKED"
    touch(pres)
    for ro in DB["refill_orders"].values():
        if ro["prescription_id"] == pres["id"] and ro["status"] == "PENDING_REVIEW":
            ro["status"] = "CANCELLED"
            touch(ro)


def suspend_plan_cascade(plan):
    """Suspend a plan (if in a suspendable state) with full cascade."""
    if plan["status"] not in {"DRAFT", "ACTIVE", "TITRATION_PENDING", "MONITORING_HOLD"}:
        return
    plan["status"] = "SUSPENDED"
    touch(plan)
    # Cancel any PROPOSED titrations for this plan.
    for t in DB["dose_titrations"].values():
        if t["plan_id"] == plan["id"] and t["status"] == "PROPOSED":
            t["status"] = "CANCELLED"
            touch(t)
    # Revoke ISSUED/SUSPENDED prescriptions linked to the plan (cascades refills).
    for pres in DB["prescriptions"].values():
        if pres["plan_id"] == plan["id"] and pres["status"] in {"ISSUED", "SUSPENDED"}:
            revoke_prescription_cascade(pres)


def hold_plan_cascade(plan):
    """Move an ACTIVE plan to MONITORING_HOLD and suspend its ISSUED prescriptions."""
    plan["status"] = "MONITORING_HOLD"
    touch(plan)
    for pres in DB["prescriptions"].values():
        if pres["plan_id"] == plan["id"] and pres["status"] == "ISSUED":
            pres["status"] = "SUSPENDED"
            touch(pres)


# ===========================================================================
# Clinicians
# ===========================================================================
@app.route("/clinic/clinicians", methods=["POST"])
def create_clinician():
    require("ClinicAdmin")
    body = get_body()
    rec = new_record(DB["clinicians"], {
        "full_name": v_str(body, "full_name"),
        "npi": v_str(body, "npi"),
        "dea_number": v_str(body, "dea_number"),
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/clinicians/<rid>", methods=["GET"])
def get_clinician(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["clinicians"], rid)))


# ===========================================================================
# Pharmacists
# ===========================================================================
@app.route("/clinic/pharmacists", methods=["POST"])
def create_pharmacist():
    require("ClinicAdmin")
    body = get_body()
    rec = new_record(DB["pharmacists"], {
        "full_name": v_str(body, "full_name"),
        "license_number": v_str(body, "license_number"),
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/pharmacists/<rid>", methods=["GET"])
def get_pharmacist(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["pharmacists"], rid)))


# ===========================================================================
# Patients
# ===========================================================================
@app.route("/clinic/patients", methods=["POST"])
def create_patient():
    require("ClinicAdmin", "Clinician")
    body = get_body()
    rec = new_record(DB["patients"], {
        "full_name": v_str(body, "full_name"),
        "date_of_birth": v_str(body, "date_of_birth"),
        "sex": v_enum(body, "sex", {"MALE", "OTHER"}),
        "email": v_str(body, "email"),
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/patients/<rid>", methods=["GET"])
def get_patient(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["patients"], rid)))


@app.route("/clinic/patients/<rid>/monitoring-summary", methods=["GET"])
def monitoring_summary(rid):
    require("ClinicAdmin", "Clinician")
    must_exist(DB["patients"], rid)
    panels = [p for p in reviewed_panels_for(rid) if within_window(p.get("drawn_at"))]

    def panel_risk(p):
        hct = p.get("hematocrit_pct") or 0.0
        psa = p.get("psa_ng_ml") or 0.0
        tt = p.get("total_testosterone_ng_dl")
        s = (8 * max(0, math.floor(hct - 50))
             + 15 * math.ceil(max(0.0, psa - 3.0))
             + (25 if (tt is not None and tt < 300) else 0))
        return min(100, s)

    if panels:
        def keyfn(p):
            try:
                d = parse_iso(p.get("drawn_at"))
            except Exception:
                d = datetime.min.replace(tzinfo=timezone.utc)
            return (d, p["created_at"], p["_seq"])
        latest = max(panels, key=keyfn)
        provisional = panel_risk(latest)
        total = sum(panel_risk(p) for p in panels)
        comprehensive = rhu(Decimal(total) / Decimal(len(panels)))
        status = "CURRENT"
    else:
        provisional = 0
        comprehensive = 0
        status = "OVERDUE"

    return respond_object({
        "provisional_risk_score": provisional,
        "comprehensive_risk_score": comprehensive,
        "monitoring_status": status,
        "reviewed_panels_in_window": len(panels),
    })


# ===========================================================================
# Membership Plans
# ===========================================================================
@app.route("/clinic/membership-plans", methods=["POST"])
def create_membership_plan():
    require("ClinicAdmin")
    body = get_body()
    rec = new_record(DB["membership_plans"], {
        "tier": v_enum(body, "tier", {"CORE", "PLUS", "ELITE"}),
        "monthly_fee_cents": v_int(body, "monthly_fee_cents", minimum=0),
        "cycle_days": v_int(body, "cycle_days", minimum=1),
        "included_refills_per_cycle": v_int(body, "included_refills_per_cycle", minimum=0),
        "included_lab_draw_credits": v_int(body, "included_lab_draw_credits", minimum=0),
        "refill_discount_pct": v_num(body, "refill_discount_pct", minimum=0.0, maximum=1.0),
        "titration_visit_fee_cents": v_int(body, "titration_visit_fee_cents", minimum=0),
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/membership-plans/<rid>", methods=["GET"])
def get_membership_plan(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["membership_plans"], rid)))


# ===========================================================================
# Memberships
# ===========================================================================
@app.route("/clinic/memberships", methods=["POST"])
def create_membership():
    require("ClinicAdmin")
    body = get_body()
    exists_body_ref(DB["patients"], body, "patient_id")
    exists_body_ref(DB["membership_plans"], body, "plan_id")
    patient_id = v_str(body, "patient_id")
    plan_id = v_str(body, "plan_id")
    plan = must_exist(DB["membership_plans"], plan_id)
    rec = new_record(DB["memberships"], {
        "patient_id": patient_id,
        "plan_id": plan_id,
        "subscription_status": "TRIAL",
        "payment_status": "CURRENT",
        "lab_draw_credits_remaining": plan["included_lab_draw_credits"],
        "cycle_anchor_date": now_iso(),
        "last_change_charge_cents": 0,
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/memberships/<rid>", methods=["GET"])
def get_membership(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["memberships"], rid)))


@app.route("/clinic/memberships", methods=["GET"])
def list_memberships():
    require(*ALL_ROLES)
    return list_response(DB["memberships"], {
        "patient_id": request.args.get("patient_id"),
        "plan_id": request.args.get("plan_id"),
    })


@app.route("/clinic/memberships/<rid>/activate", methods=["POST"])
def activate_membership(rid):
    require("ClinicAdmin")
    m = must_exist(DB["memberships"], rid)
    if m["subscription_status"] != "TRIAL":
        err("ERR_INVALID_STATE", 409, "Membership not in TRIAL")
    m["subscription_status"] = "ACTIVE"
    touch(m)
    return respond_object(serialize(m))


@app.route("/clinic/memberships/<rid>/record-payment", methods=["POST"])
def record_payment(rid):
    require("ClinicAdmin")
    m = must_exist(DB["memberships"], rid)
    body = get_body()
    outcome = v_enum(body, "outcome", {"SUCCEEDED", "FAILED"})
    if outcome == "FAILED":
        if m["payment_status"] != "CURRENT":
            err("ERR_INVALID_STATE", 409, "Payment status not CURRENT")
        m["payment_status"] = "DELINQUENT"
    else:  # SUCCEEDED
        if m["payment_status"] != "DELINQUENT":
            err("ERR_INVALID_STATE", 409, "Payment status not DELINQUENT")
        m["payment_status"] = "CURRENT"
    touch(m)
    return respond_object(serialize(m))


@app.route("/clinic/memberships/<rid>/change-plan", methods=["POST"])
def change_plan(rid):
    require("ClinicAdmin")
    m = must_exist(DB["memberships"], rid)
    body = get_body()
    exists_body_ref(DB["membership_plans"], body, "new_plan_id")
    new_plan_id = v_str(body, "new_plan_id")
    new_plan = must_exist(DB["membership_plans"], new_plan_id)
    old_plan = must_exist(DB["membership_plans"], m["plan_id"])

    anchor = parse_iso(m["cycle_anchor_date"])
    cycle_end = anchor + timedelta(days=old_plan["cycle_days"])
    days_remaining = math.floor((cycle_end - CLOCK).total_seconds() / 86400.0)
    if days_remaining < 0:
        days_remaining = 0

    old_credit_line = rhu(Decimal(old_plan["monthly_fee_cents"]) * Decimal(days_remaining)
                          / Decimal(old_plan["cycle_days"]))
    new_charge_line = rhu(Decimal(new_plan["monthly_fee_cents"]) * Decimal(days_remaining)
                          / Decimal(new_plan["cycle_days"]))
    net = new_charge_line - old_credit_line

    m["plan_id"] = new_plan_id
    m["last_change_charge_cents"] = net
    touch(m)
    return respond_object(serialize(m))


@app.route("/clinic/memberships/<rid>/cancel", methods=["POST"])
def cancel_membership(rid):
    require("ClinicAdmin")
    m = must_exist(DB["memberships"], rid)
    if m["subscription_status"] not in {"TRIAL", "ACTIVE"}:
        err("ERR_INVALID_STATE", 409, "Membership not cancellable")
    m["subscription_status"] = "CANCELLED"
    touch(m)
    return respond_object(serialize(m))


# ===========================================================================
# Draw Stations
# ===========================================================================
@app.route("/clinic/draw-stations", methods=["POST"])
def create_draw_station():
    require("ClinicAdmin")
    body = get_body()
    rec = new_record(DB["draw_stations"], {
        "name": v_str(body, "name"),
        "concurrent_capacity": v_int(body, "concurrent_capacity", minimum=0),
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/draw-stations/<rid>", methods=["GET"])
def get_draw_station(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["draw_stations"], rid)))


# ===========================================================================
# Lab Panels
# ===========================================================================
@app.route("/clinic/lab-panels", methods=["POST"])
def create_lab_panel():
    require("Clinician")
    body = get_body()
    exists_body_ref(DB["patients"], body, "patient_id")
    exists_body_ref(DB["clinicians"], body, "clinician_id")
    rec = new_record(DB["lab_panels"], {
        "patient_id": v_str(body, "patient_id"),
        "clinician_id": v_str(body, "clinician_id"),
        "panel_type": v_enum(body, "panel_type", {"BASELINE", "MONITORING"}),
        "total_testosterone_ng_dl": None,
        "psa_ng_ml": None,
        "hematocrit_pct": None,
        "drawn_at": None,
        "is_unsafe": False,
        "status": "ORDERED",
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/lab-panels/<rid>", methods=["GET"])
def get_lab_panel(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["lab_panels"], rid)))


@app.route("/clinic/lab-panels", methods=["GET"])
def list_lab_panels():
    require(*ALL_ROLES)
    return list_response(DB["lab_panels"], {
        "patient_id": request.args.get("patient_id"),
        "clinician_id": request.args.get("clinician_id"),
    })


@app.route("/clinic/lab-panels/<rid>/draw", methods=["POST"])
def draw_lab_panel(rid):
    require("Clinician", "ClinicAdmin")
    p = must_exist(DB["lab_panels"], rid)
    if p["status"] != "ORDERED":
        err("ERR_INVALID_STATE", 409, "Panel not in ORDERED")
    p["status"] = "DRAWN"
    touch(p)
    return respond_object(serialize(p))


@app.route("/clinic/lab-panels/<rid>/result", methods=["POST"])
def result_lab_panel(rid):
    require("Clinician")
    p = must_exist(DB["lab_panels"], rid)
    body = get_body()
    tt = v_int(body, "total_testosterone_ng_dl")
    psa = v_num(body, "psa_ng_ml")
    hct = v_num(body, "hematocrit_pct")
    drawn_at = v_datetime(body, "drawn_at")
    if p["status"] != "DRAWN":
        err("ERR_PANEL_NOT_RESULTED", 409, "Panel not in DRAWN")
    p["total_testosterone_ng_dl"] = tt
    p["psa_ng_ml"] = psa
    p["hematocrit_pct"] = hct
    p["drawn_at"] = drawn_at
    p["status"] = "RESULTED"
    touch(p)
    return respond_object(serialize(p))


@app.route("/clinic/lab-panels/<rid>/review", methods=["POST"])
def review_lab_panel(rid):
    require("Clinician")
    p = must_exist(DB["lab_panels"], rid)
    if p["status"] != "RESULTED":
        err("ERR_PANEL_NOT_RESULTED", 409, "Panel not in RESULTED")
    hct = p.get("hematocrit_pct") or 0.0
    psa = p.get("psa_ng_ml") or 0.0
    p["is_unsafe"] = (hct >= 54.0) or (psa >= 4.0)
    p["status"] = "REVIEWED"
    touch(p)
    if p["is_unsafe"]:
        for plan in list(DB["treatment_plans"].values()):
            if plan["patient_id"] == p["patient_id"] and plan["status"] == "ACTIVE":
                hold_plan_cascade(plan)
    return respond_object(serialize(p))


# ===========================================================================
# Lab-Draw Appointments
# ===========================================================================
def _overlaps_half_open(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/clinic/lab-draw-appointments", methods=["POST"])
def create_lab_draw_appointment():
    require("Patient", "ClinicAdmin", "Clinician")
    body = get_body()
    exists_body_ref(DB["patients"], body, "patient_id")
    exists_body_ref(DB["draw_stations"], body, "draw_station_id")
    patient_id = v_str(body, "patient_id")
    station_id = v_str(body, "draw_station_id")
    start_at = v_datetime(body, "start_at")
    end_at = v_datetime(body, "end_at")
    station = must_exist(DB["draw_stations"], station_id)

    # Guard 1 (PRD §3.4 order): lab-draw credit availability.
    m = patient_membership(patient_id)
    if m is None or m["lab_draw_credits_remaining"] < 1:
        err("ERR_INSUFFICIENT_LAB_DRAW_CREDITS", 402, "No lab-draw credits remaining")

    # Guard 2: station concurrency.
    s1, e1 = parse_iso(start_at), parse_iso(end_at)
    overlap_count = 0
    for a in DB["lab_draw_appointments"].values():
        if a["draw_station_id"] == station_id and a["status"] == "SCHEDULED":
            s2, e2 = parse_iso(a["start_at"]), parse_iso(a["end_at"])
            if _overlaps_half_open(s1, e1, s2, e2):
                overlap_count += 1
    if overlap_count >= station["concurrent_capacity"]:
        err("ERR_DRAW_STATION_AT_CAPACITY", 409, "Draw station at capacity")

    rec = new_record(DB["lab_draw_appointments"], {
        "patient_id": patient_id,
        "draw_station_id": station_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
    })
    m["lab_draw_credits_remaining"] -= 1
    touch(m)
    return respond_object(serialize(rec), 201)


@app.route("/clinic/lab-draw-appointments/<rid>", methods=["GET"])
def get_lab_draw_appointment(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["lab_draw_appointments"], rid)))


@app.route("/clinic/lab-draw-appointments", methods=["GET"])
def list_lab_draw_appointments():
    require(*ALL_ROLES)
    return list_response(DB["lab_draw_appointments"], {
        "patient_id": request.args.get("patient_id"),
        "draw_station_id": request.args.get("draw_station_id"),
    })


@app.route("/clinic/lab-draw-appointments/<rid>/complete", methods=["POST"])
def complete_lab_draw_appointment(rid):
    require("Clinician", "ClinicAdmin")
    a = must_exist(DB["lab_draw_appointments"], rid)
    if a["status"] != "SCHEDULED":
        err("ERR_APPOINTMENT_NOT_SCHEDULED", 409, "Appointment not SCHEDULED")
    a["status"] = "COMPLETED"
    touch(a)
    return respond_object(serialize(a))


@app.route("/clinic/lab-draw-appointments/<rid>/cancel", methods=["POST"])
def cancel_lab_draw_appointment(rid):
    require("Patient", "ClinicAdmin", "Clinician")
    a = must_exist(DB["lab_draw_appointments"], rid)
    if a["status"] != "SCHEDULED":
        err("ERR_APPOINTMENT_NOT_SCHEDULED", 409, "Appointment not SCHEDULED")
    a["status"] = "CANCELLED"
    touch(a)
    m = patient_membership(a["patient_id"])
    if m is not None:
        m["lab_draw_credits_remaining"] += 1
        touch(m)
    return respond_object(serialize(a))


# ===========================================================================
# Telehealth Visits
# ===========================================================================
@app.route("/clinic/telehealth-visits", methods=["POST"])
def create_telehealth_visit():
    require("Patient", "ClinicAdmin")
    body = get_body()
    exists_body_ref(DB["patients"], body, "patient_id")
    exists_body_ref(DB["clinicians"], body, "clinician_id")
    patient_id = v_str(body, "patient_id")
    clinician_id = v_str(body, "clinician_id")
    start_at = v_datetime(body, "start_at")
    end_at = v_datetime(body, "end_at")
    reason = v_str(body, "reason", required=False)

    s1, e1 = parse_iso(start_at), parse_iso(end_at)
    buffer = timedelta(minutes=15)
    for v in DB["telehealth_visits"].values():
        if v["clinician_id"] == clinician_id and v["status"] == "SCHEDULED":
            s2, e2 = parse_iso(v["start_at"]), parse_iso(v["end_at"])
            # Reject when the clear gap between the two intervals is < 15 min
            # (overlap yields a negative gap and is also rejected).
            gap = max(s1, s2) - min(e1, e2)
            if gap < buffer:
                err("ERR_CLINICIAN_DOUBLE_BOOKED", 409, "Clinician double-booked")

    rec = new_record(DB["telehealth_visits"], {
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
        "status": "SCHEDULED",
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/telehealth-visits/<rid>", methods=["GET"])
def get_telehealth_visit(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["telehealth_visits"], rid)))


@app.route("/clinic/telehealth-visits", methods=["GET"])
def list_telehealth_visits():
    require(*ALL_ROLES)
    return list_response(DB["telehealth_visits"], {
        "patient_id": request.args.get("patient_id"),
        "clinician_id": request.args.get("clinician_id"),
    })


@app.route("/clinic/telehealth-visits/<rid>/complete", methods=["POST"])
def complete_telehealth_visit(rid):
    require("Clinician")
    v = must_exist(DB["telehealth_visits"], rid)
    if v["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Visit not SCHEDULED")
    v["status"] = "COMPLETED"
    touch(v)
    return respond_object(serialize(v))


@app.route("/clinic/telehealth-visits/<rid>/cancel", methods=["POST"])
def cancel_telehealth_visit(rid):
    require("Patient", "ClinicAdmin", "Clinician")
    v = must_exist(DB["telehealth_visits"], rid)
    if v["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Visit not SCHEDULED")
    v["status"] = "CANCELLED"
    touch(v)
    return respond_object(serialize(v))


# ===========================================================================
# Treatment Plans
# ===========================================================================
@app.route("/clinic/treatment-plans", methods=["POST"])
def create_treatment_plan():
    require("Clinician")
    body = get_body()
    exists_body_ref(DB["patients"], body, "patient_id")
    exists_body_ref(DB["clinicians"], body, "clinician_id")
    exists_body_ref(DB["lab_panels"], body, "baseline_panel_id")
    rec = new_record(DB["treatment_plans"], {
        "patient_id": v_str(body, "patient_id"),
        "clinician_id": v_str(body, "clinician_id"),
        "baseline_panel_id": v_str(body, "baseline_panel_id"),
        "protocol_type": v_enum(body, "protocol_type", {"TRT_INJECTION", "TRT_TOPICAL", "ED_THERAPY"}),
        "starting_dose_mg": v_num(body, "starting_dose_mg"),
        "current_dose_mg": None,
        "round_index": 0,
        "status": "DRAFT",
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/treatment-plans/<rid>", methods=["GET"])
def get_treatment_plan(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["treatment_plans"], rid)))


@app.route("/clinic/treatment-plans", methods=["GET"])
def list_treatment_plans():
    require(*ALL_ROLES)
    return list_response(DB["treatment_plans"], {
        "patient_id": request.args.get("patient_id"),
        "clinician_id": request.args.get("clinician_id"),
        "baseline_panel_id": request.args.get("baseline_panel_id"),
    })


@app.route("/clinic/treatment-plans/<rid>/activate", methods=["POST"])
def activate_treatment_plan(rid):
    uid, role = require("Clinician")
    plan = must_exist(DB["treatment_plans"], rid)
    # PRD §3.5 ordering: membership ACTIVE -> DRAFT -> baseline REVIEWED -> clinician owns.
    m = patient_membership(plan["patient_id"])
    if m is None or m["subscription_status"] != "ACTIVE":
        err("ERR_MEMBERSHIP_NOT_ACTIVE", 409, "Patient membership not ACTIVE")
    if plan["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Plan not in DRAFT")
    baseline = must_exist(DB["lab_panels"], plan["baseline_panel_id"])
    if baseline["status"] != "REVIEWED":
        err("ERR_BASELINE_NOT_REVIEWED", 409, "Baseline panel not REVIEWED")
    if plan["clinician_id"] != uid:
        err("ERR_CLINICIAN_MISMATCH", 403, "Acting clinician does not own the plan")
    plan["status"] = "ACTIVE"
    plan["current_dose_mg"] = plan["starting_dose_mg"]
    touch(plan)
    return respond_object(serialize(plan))


@app.route("/clinic/treatment-plans/<rid>/titrations", methods=["POST"])
def propose_titration(rid):
    require("Clinician")
    plan = must_exist(DB["treatment_plans"], rid)
    body = get_body()
    proposed = v_num(body, "proposed_dose_mg")
    expected_version = v_int(body, "expected_plan_version")
    # OCC (priority before state check per §2.8).
    if expected_version != plan["version"]:
        err("ERR_STALE_VERSION", 412, "expected_plan_version does not match")
    if plan["status"] != "ACTIVE":
        err("ERR_PLAN_NOT_ACTIVE", 409, "Plan not ACTIVE")
    titration = new_record(DB["dose_titrations"], {
        "plan_id": plan["id"],
        "round_index": plan["round_index"] + 1,
        "previous_dose_mg": plan["current_dose_mg"],
        "proposed_dose_mg": proposed,
        "applied": False,
        "status": "PROPOSED",
    })
    plan["status"] = "TITRATION_PENDING"
    touch(plan)
    return respond_object(serialize(titration), 201)


@app.route("/clinic/treatment-plans/<rid>/titrations", methods=["GET"])
def list_titrations(rid):
    require(*ALL_ROLES)
    must_exist(DB["treatment_plans"], rid)
    return list_response(DB["dose_titrations"], {"plan_id": rid})


@app.route("/clinic/treatment-plans/<rid>/titrations/<tid>/confirm", methods=["POST"])
def confirm_titration(rid, tid):
    require("Clinician")
    plan = must_exist(DB["treatment_plans"], rid)
    titration = must_exist(DB["dose_titrations"], tid)
    if titration["plan_id"] != rid:
        err("ERR_NOT_FOUND", 404, "Titration does not belong to plan")
    if plan["status"] != "TITRATION_PENDING":
        err("ERR_TITRATION_NOT_PENDING", 409, "Plan not TITRATION_PENDING")
    latest = latest_reviewed_panel(plan["patient_id"])
    if latest is None or (latest.get("hematocrit_pct") or 0.0) >= 54.0:
        err("ERR_HEMATOCRIT_UNSAFE", 422, "Latest reviewed hematocrit unsafe")
    titration["status"] = "CONFIRMED"
    titration["applied"] = True
    touch(titration)
    plan["current_dose_mg"] = titration["proposed_dose_mg"]
    plan["round_index"] = titration["round_index"]
    plan["status"] = "ACTIVE"
    touch(plan)
    return respond_object(serialize(titration))


@app.route("/clinic/treatment-plans/<rid>/suspend", methods=["POST"])
def suspend_treatment_plan(rid):
    require("Clinician", "ClinicAdmin")
    plan = must_exist(DB["treatment_plans"], rid)
    if plan["status"] not in {"DRAFT", "ACTIVE", "TITRATION_PENDING", "MONITORING_HOLD"}:
        err("ERR_INVALID_STATE", 409, "Plan not suspendable")
    suspend_plan_cascade(plan)
    return respond_object(serialize(plan))


@app.route("/clinic/treatment-plans/<rid>/resume", methods=["POST"])
def resume_treatment_plan(rid):
    require("Clinician")
    plan = must_exist(DB["treatment_plans"], rid)
    if plan["status"] != "MONITORING_HOLD":
        err("ERR_INVALID_STATE", 409, "Plan not in MONITORING_HOLD")
    latest = latest_reviewed_panel(plan["patient_id"])
    if latest is None or latest.get("is_unsafe", False):
        err("ERR_HEMATOCRIT_UNSAFE", 422, "Latest reviewed panel unsafe")
    plan["status"] = "ACTIVE"
    touch(plan)
    for pres in DB["prescriptions"].values():
        if pres["plan_id"] == plan["id"] and pres["status"] == "SUSPENDED":
            pres["status"] = "ISSUED"
            touch(pres)
    return respond_object(serialize(plan))


# ===========================================================================
# Prescriptions
# ===========================================================================
@app.route("/clinic/prescriptions", methods=["POST"])
def create_prescription():
    uid, role = require("Clinician")
    body = get_body()
    exists_body_ref(DB["treatment_plans"], body, "plan_id")
    exists_body_ref(DB["patients"], body, "patient_id")
    plan_id = v_str(body, "plan_id")
    patient_id = v_str(body, "patient_id")
    drug_name = v_str(body, "drug_name")
    unit_price = v_int(body, "unit_price_cents", minimum=0)
    qty_per_fill = v_int(body, "quantity_per_fill", minimum=0)
    refills_auth = v_int(body, "refills_authorized", minimum=0)
    is_controlled = v_bool(body, "is_controlled", required=False, default=True)
    plan = must_exist(DB["treatment_plans"], plan_id)

    if patient_id != plan["patient_id"]:
        err("ERR_PATIENT_MISMATCH", 409, "Prescription patient does not match plan patient")
    if plan["clinician_id"] != uid:
        err("ERR_CLINICIAN_MISMATCH", 403, "Acting clinician does not own the plan")
    has_recent = any(within_window(p.get("drawn_at")) for p in reviewed_panels_for(patient_id))
    if not has_recent:
        err("ERR_MONITORING_OVERDUE", 422, "No reviewed lab panel within monitoring window")

    rec = new_record(DB["prescriptions"], {
        "plan_id": plan_id,
        "patient_id": patient_id,
        "prescriber_id": uid,
        "drug_name": drug_name,
        "unit_price_cents": unit_price,
        "quantity_per_fill": qty_per_fill,
        "refills_authorized": refills_auth,
        "refills_remaining": refills_auth,
        "is_controlled": is_controlled,
        "status": "ISSUED",
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/prescriptions/<rid>", methods=["GET"])
def get_prescription(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["prescriptions"], rid)))


@app.route("/clinic/prescriptions", methods=["GET"])
def list_prescriptions():
    require(*ALL_ROLES)
    return list_response(DB["prescriptions"], {
        "plan_id": request.args.get("plan_id"),
        "patient_id": request.args.get("patient_id"),
        "prescriber_id": request.args.get("prescriber_id"),
    })


@app.route("/clinic/prescriptions/<rid>/revoke", methods=["POST"])
def revoke_prescription(rid):
    require("Clinician")
    pres = must_exist(DB["prescriptions"], rid)
    if pres["status"] not in {"ISSUED", "SUSPENDED"}:
        err("ERR_INVALID_STATE", 409, "Prescription not revocable")
    revoke_prescription_cascade(pres)
    return respond_object(serialize(pres))


# ===========================================================================
# Refill Orders
# ===========================================================================
@app.route("/clinic/refill-orders", methods=["POST"])
def create_refill_order():
    require("Patient", "ClinicAdmin")
    body = get_body()
    exists_body_ref(DB["prescriptions"], body, "prescription_id")
    exists_body_ref(DB["memberships"], body, "membership_id")
    exists_body_ref(DB["patients"], body, "patient_id")
    prescription_id = v_str(body, "prescription_id")
    membership_id = v_str(body, "membership_id")
    patient_id = v_str(body, "patient_id")
    requested_qty = v_int(body, "requested_quantity_units", minimum=0)
    expected_version = v_int(body, "expected_prescription_version")

    pres = must_exist(DB["prescriptions"], prescription_id)
    membership = must_exist(DB["memberships"], membership_id)

    # OCC first (§3.6 order).
    if expected_version != pres["version"]:
        err("ERR_STALE_VERSION", 412, "expected_prescription_version does not match")
    if pres["status"] in {"SUSPENDED", "REVOKED"}:
        err("ERR_PRESCRIPTION_SUSPENDED", 409, "Prescription suspended or revoked")
    if membership["subscription_status"] != "ACTIVE":
        err("ERR_MEMBERSHIP_NOT_ACTIVE", 409, "Membership not ACTIVE")
    if membership["payment_status"] != "CURRENT":
        err("ERR_MEMBERSHIP_DELINQUENT", 402, "Membership delinquent")

    plan = must_exist(DB["membership_plans"], membership["plan_id"])
    provisional = refill_charge(pres, plan, requested_qty)

    rec = new_record(DB["refill_orders"], {
        "prescription_id": prescription_id,
        "membership_id": membership_id,
        "patient_id": patient_id,
        "requested_quantity_units": requested_qty,
        "dispensed_quantity_units": None,
        "provisional_charge_cents": provisional,
        "final_charge_cents": None,
        "status": "PENDING_REVIEW",
    })
    touch(pres)  # prescription version advances on refill creation
    return respond_object(serialize(rec), 201)


@app.route("/clinic/refill-orders/<rid>", methods=["GET"])
def get_refill_order(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["refill_orders"], rid)))


@app.route("/clinic/refill-orders", methods=["GET"])
def list_refill_orders():
    require(*ALL_ROLES)
    return list_response(DB["refill_orders"], {
        "prescription_id": request.args.get("prescription_id"),
        "membership_id": request.args.get("membership_id"),
        "patient_id": request.args.get("patient_id"),
    })


@app.route("/clinic/refill-orders/<rid>/dispense", methods=["POST"])
def dispense_refill_order(rid):
    require("Pharmacist")
    ro = must_exist(DB["refill_orders"], rid)
    body = get_body()
    dispensed_qty = v_int(body, "dispensed_quantity_units", minimum=0)
    if ro["status"] != "PENDING_REVIEW":
        err("ERR_REFILL_NOT_DISPENSABLE", 409, "Refill order not PENDING_REVIEW")
    pres = must_exist(DB["prescriptions"], ro["prescription_id"])
    if pres["status"] in {"SUSPENDED", "REVOKED"}:
        err("ERR_PRESCRIPTION_SUSPENDED", 409, "Prescription suspended or revoked")
    if pres["refills_remaining"] < 1:
        err("ERR_NO_REFILLS_REMAINING", 409, "No refills remaining")

    membership = must_exist(DB["memberships"], ro["membership_id"])
    plan = must_exist(DB["membership_plans"], membership["plan_id"])
    ro["dispensed_quantity_units"] = dispensed_qty
    ro["final_charge_cents"] = refill_charge(pres, plan, dispensed_qty)
    ro["status"] = "DISPENSED"
    touch(ro)
    pres["refills_remaining"] -= 1
    if pres["refills_remaining"] == 0:
        pres["status"] = "EXHAUSTED"
    touch(pres)
    return respond_object(serialize(ro))


@app.route("/clinic/refill-orders/<rid>/cancel", methods=["POST"])
def cancel_refill_order(rid):
    require("Patient", "ClinicAdmin", "Clinician")
    ro = must_exist(DB["refill_orders"], rid)
    if ro["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE", 409, "Refill order not PENDING_REVIEW")
    ro["status"] = "CANCELLED"
    touch(ro)
    return respond_object(serialize(ro))


@app.route("/clinic/refill-orders/<rid>/reverse", methods=["POST"])
def reverse_refill_order(rid):
    require("Pharmacist")
    ro = must_exist(DB["refill_orders"], rid)
    if ro["status"] != "DISPENSED":
        err("ERR_INVALID_STATE", 409, "Refill order not DISPENSED")
    ro["status"] = "REVERSED"
    touch(ro)
    pres = must_exist(DB["prescriptions"], ro["prescription_id"])
    pres["refills_remaining"] += 1
    if pres["status"] == "EXHAUSTED" and pres["refills_remaining"] > 0:
        pres["status"] = "ISSUED"
    touch(pres)
    return respond_object(serialize(ro))


# ===========================================================================
# Adverse Events
# ===========================================================================
@app.route("/clinic/adverse-events", methods=["POST"])
def create_adverse_event():
    require("Clinician", "Patient")
    body = get_body()
    exists_body_ref(DB["patients"], body, "patient_id")
    exists_body_ref(DB["treatment_plans"], body, "plan_id")
    if _present(body, "reported_by"):
        exists_body_ref(DB["clinicians"], body, "reported_by")
    rec = new_record(DB["adverse_events"], {
        "patient_id": v_str(body, "patient_id"),
        "plan_id": v_str(body, "plan_id"),
        "reported_by": v_str(body, "reported_by", required=False),
        "description": v_str(body, "description"),
        "severity": None,
        "status": "REPORTED",
    })
    return respond_object(serialize(rec), 201)


@app.route("/clinic/adverse-events/<rid>", methods=["GET"])
def get_adverse_event(rid):
    require(*ALL_ROLES)
    return respond_object(serialize(must_exist(DB["adverse_events"], rid)))


@app.route("/clinic/adverse-events", methods=["GET"])
def list_adverse_events():
    require(*ALL_ROLES)
    return list_response(DB["adverse_events"], {
        "patient_id": request.args.get("patient_id"),
        "plan_id": request.args.get("plan_id"),
        "reported_by": request.args.get("reported_by"),
    })


@app.route("/clinic/adverse-events/<rid>/triage", methods=["POST"])
def triage_adverse_event(rid):
    uid, role = require("Clinician")
    ev = must_exist(DB["adverse_events"], rid)
    body = get_body()
    severity = v_enum(body, "severity", {"MILD", "SEVERE"})
    if ev["status"] != "REPORTED":
        err("ERR_INVALID_STATE", 409, "Adverse event not REPORTED")
    plan = must_exist(DB["treatment_plans"], ev["plan_id"])
    if uid == plan["clinician_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Reviewer must differ from prescribing clinician")
    ev["severity"] = severity
    if severity == "MILD":
        ev["status"] = "MILD_LOGGED"
        touch(ev)
    else:  # SEVERE
        ev["status"] = "SEVERE_ESCALATED"
        touch(ev)
        suspend_plan_cascade(plan)
    return respond_object(serialize(ev))


@app.route("/clinic/adverse-events/<rid>/resolve", methods=["POST"])
def resolve_adverse_event(rid):
    require("Clinician")
    ev = must_exist(DB["adverse_events"], rid)
    if ev["status"] not in {"MILD_LOGGED", "SEVERE_ESCALATED"}:
        err("ERR_INVALID_STATE", 409, "Adverse event not triaged")
    ev["status"] = "RESOLVED"
    touch(ev)
    return respond_object(serialize(ev))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/clinic/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    require("ClinicAdmin")
    body = get_body()
    to_iso = v_str(body, "to_iso8601")
    try:
        CLOCK = parse_iso(to_iso)
    except Exception:
        err("ERR_VALIDATION", 400, "to_iso8601 is not a valid ISO8601 datetime")
    return respond_object({"current_utc": now_iso()})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
