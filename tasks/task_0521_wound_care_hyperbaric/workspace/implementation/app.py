"""Wound Care & Hyperbaric Center API — Flask entry point."""
import os

from flask import Flask, request

from errors import ApiError
from response import success_object, success_array, error_response
from db import db, new_id, now_iso, STARTUP_CLOCK_DEFAULT
from middleware import get_user_context, require_role
import calc
import services as svc

app = Flask(__name__)
app.url_map.strict_slashes = False


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed"), 404


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_INVALID_REQUEST", str(e)), 400


def api_error(error_id, message=None):
    from errors import err
    raise err(error_id, message)


# ===========================================================================
# Request helpers
# ===========================================================================
def get_body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        api_error("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


ALL_ROLES = {"IntakeCoordinator", "WoundClinician", "HyperbaricTech",
             "PayerLiaison", "AttendingPhysician"}


def auth(allowed):
    """Priority 1 then 2. Returns (user_id, role)."""
    user_id, role = get_user_context()
    require_role(role, allowed)
    return user_id, role


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            api_error("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            api_error("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def _parse_created(v):
    return svc._parse_dt(v["created_at"]) if isinstance(v, dict) else None


def list_response(collection, filters):
    """Filter, sort by created_at asc (tie by seq), paginate."""
    items = list(collection.values())
    for key, val in filters.items():
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    items.sort(key=lambda i: (svc._parse_dt(i["created_at"]), i.get("_seq", 0)))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    page_public = [public(i) for i in page]
    return success_array(page_public, limit, offset, total)


# ---- public projection: strip internal fields ----
def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def common_fields(full=True):
    ts = now_iso()
    base = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if full:
        base["updated_at"] = ts
        base["version"] = 1
    return base


# ---- lookups that raise the right not-found ----
def get_or_404(collection, rid, error_id):
    obj = collection.get(rid)
    if obj is None:
        api_error(error_id)
    return obj


# ---------------------------------------------------------------------------
# Field validation helpers (priority 13 — ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            api_error("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def as_int_ge(body, field, minimum, default=None, required=True):
    if field not in body or body.get(field) is None:
        if required and default is None:
            api_error("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        api_error("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if v < minimum:
        api_error("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return v


def as_number_gt(body, field, threshold):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        api_error("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if not (v > threshold):
        api_error("ERR_INVALID_REQUEST", "%s must be > %s" % (field, threshold))
    return v


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ALL_ROLES)
    body = get_body()
    center_id = body.get("center_id")
    to_iso = body.get("to_iso8601")
    if center_id is None or to_iso is None:
        api_error("ERR_INVALID_REQUEST", "center_id and to_iso8601 required")
    center = get_or_404(db.centers, center_id, "ERR_CENTER_NOT_FOUND")
    center["current_utc"] = to_iso
    svc.touch(center)
    return success_object(public(center), 200)


# ===========================================================================
# Center
# ===========================================================================
@app.route("/wound-care/centers", methods=["POST"])
def create_center():
    auth({"IntakeCoordinator"})
    body = get_body()
    require_fields(body, ["name"])
    entity = common_fields()
    entity.update({"name": body["name"], "current_utc": STARTUP_CLOCK_DEFAULT})
    db.centers[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/centers", methods=["GET"])
def list_centers():
    auth(ALL_ROLES)
    return list_response(db.centers, {})


@app.route("/wound-care/centers/<center_id>", methods=["GET"])
def get_center(center_id):
    auth(ALL_ROLES)
    c = get_or_404(db.centers, center_id, "ERR_CENTER_NOT_FOUND")
    return success_object(public(c), 200)


# ===========================================================================
# Clinician
# ===========================================================================
@app.route("/wound-care/clinicians", methods=["POST"])
def create_clinician():
    auth({"IntakeCoordinator"})
    body = get_body()
    require_fields(body, ["center_id", "name", "role_kind"])
    if body["role_kind"] not in ("WOUND", "HYPERBARIC", "ATTENDING"):
        api_error("ERR_INVALID_REQUEST", "invalid role_kind")
    active = body.get("active", True)
    if not isinstance(active, bool):
        api_error("ERR_INVALID_REQUEST", "active must be boolean")
    get_or_404(db.centers, body["center_id"], "ERR_CENTER_NOT_FOUND")
    entity = common_fields()
    entity.update({
        "center_id": body["center_id"],
        "name": body["name"],
        "role_kind": body["role_kind"],
        "active": active,
    })
    db.clinicians[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/clinicians", methods=["GET"])
def list_clinicians():
    auth(ALL_ROLES)
    return list_response(db.clinicians, {"center_id": request.args.get("center_id")})


@app.route("/wound-care/clinicians/<clinician_id>", methods=["GET"])
def get_clinician(clinician_id):
    auth(ALL_ROLES)
    c = get_or_404(db.clinicians, clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    return success_object(public(c), 200)


# ===========================================================================
# Chamber
# ===========================================================================
@app.route("/wound-care/chambers", methods=["POST"])
def create_chamber():
    auth({"IntakeCoordinator"})
    body = get_body()
    require_fields(body, ["center_id", "label"])
    buffer = as_int_ge(body, "turnover_buffer_minutes", 0, default=30, required=False)
    get_or_404(db.centers, body["center_id"], "ERR_CENTER_NOT_FOUND")
    entity = common_fields()
    entity.update({
        "center_id": body["center_id"],
        "label": body["label"],
        "turnover_buffer_minutes": buffer,
        "occupied_slot_count": 0,
    })
    db.chambers[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/chambers", methods=["GET"])
def list_chambers():
    auth(ALL_ROLES)
    return list_response(db.chambers, {"center_id": request.args.get("center_id")})


@app.route("/wound-care/chambers/<chamber_id>", methods=["GET"])
def get_chamber(chamber_id):
    auth(ALL_ROLES)
    c = get_or_404(db.chambers, chamber_id, "ERR_CHAMBER_NOT_FOUND")
    return success_object(public(c), 200)


# ===========================================================================
# PayerPolicy
# ===========================================================================
@app.route("/wound-care/payer-policies", methods=["POST"])
def create_payer_policy():
    auth({"PayerLiaison"})
    body = get_body()
    require_fields(body, ["center_id", "payer_name"])
    max_hbo = as_int_ge(body, "max_covered_hbo_sessions", 0)
    per_session = as_int_ge(body, "per_session_cents", 0)
    requires_pa = body.get("requires_prior_auth", True)
    if not isinstance(requires_pa, bool):
        api_error("ERR_INVALID_REQUEST", "requires_prior_auth must be boolean")
    threshold = body.get("min_healing_pct_threshold", 50)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        api_error("ERR_INVALID_REQUEST", "min_healing_pct_threshold must be a number")
    get_or_404(db.centers, body["center_id"], "ERR_CENTER_NOT_FOUND")
    entity = common_fields()
    entity.update({
        "center_id": body["center_id"],
        "payer_name": body["payer_name"],
        "requires_prior_auth": requires_pa,
        "max_covered_hbo_sessions": max_hbo,
        "per_session_cents": per_session,
        "min_healing_pct_threshold": threshold,
    })
    db.payer_policies[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/payer-policies", methods=["GET"])
def list_payer_policies():
    auth(ALL_ROLES)
    return list_response(db.payer_policies, {"center_id": request.args.get("center_id")})


@app.route("/wound-care/payer-policies/<policy_id>", methods=["GET"])
def get_payer_policy(policy_id):
    auth(ALL_ROLES)
    p = get_or_404(db.payer_policies, policy_id, "ERR_POLICY_NOT_FOUND")
    return success_object(public(p), 200)


# ===========================================================================
# Patient
# ===========================================================================
@app.route("/wound-care/patients", methods=["POST"])
def create_patient():
    auth({"IntakeCoordinator"})
    body = get_body()
    require_fields(body, ["center_id", "mrn", "full_name", "payer_policy_id"])
    get_or_404(db.centers, body["center_id"], "ERR_CENTER_NOT_FOUND")
    get_or_404(db.payer_policies, body["payer_policy_id"], "ERR_POLICY_NOT_FOUND")
    entity = common_fields()
    entity.update({
        "center_id": body["center_id"],
        "mrn": body["mrn"],
        "full_name": body["full_name"],
        "payer_policy_id": body["payer_policy_id"],
        "latest_wound_area_cm2": 0,
        "status": "INTAKE",
    })
    db.patients[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/patients", methods=["GET"])
def list_patients():
    auth(ALL_ROLES)
    return list_response(db.patients, {
        "center_id": request.args.get("center_id"),
        "payer_policy_id": request.args.get("payer_policy_id"),
    })


@app.route("/wound-care/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    auth(ALL_ROLES)
    p = get_or_404(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    return success_object(public(p), 200)


# ===========================================================================
# Referral
# ===========================================================================
@app.route("/wound-care/referrals", methods=["POST"])
def create_referral():
    auth({"IntakeCoordinator"})
    body = get_body()
    require_fields(body, ["patient_id", "source_provider", "reason"])
    get_or_404(db.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    entity = common_fields()
    entity.update({
        "patient_id": body["patient_id"],
        "source_provider": body["source_provider"],
        "reason": body["reason"],
        "status": "RECEIVED",
    })
    db.referrals[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/referrals", methods=["GET"])
def list_referrals():
    auth(ALL_ROLES)
    return list_response(db.referrals, {"patient_id": request.args.get("patient_id")})


@app.route("/wound-care/referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    auth(ALL_ROLES)
    r = get_or_404(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    return success_object(public(r), 200)


@app.route("/wound-care/referrals/<referral_id>/request-info", methods=["POST"])
def referral_request_info(referral_id):
    auth({"IntakeCoordinator"})
    r = get_or_404(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    if r["status"] != "RECEIVED":
        api_error("ERR_REFERRAL_NOT_RECEIVED")
    r["status"] = "NEEDS_INFO"
    svc.touch(r)
    return success_object(public(r), 200)


@app.route("/wound-care/referrals/<referral_id>/resubmit", methods=["POST"])
def referral_resubmit(referral_id):
    auth({"IntakeCoordinator"})
    r = get_or_404(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    if r["status"] != "NEEDS_INFO":
        api_error("ERR_REFERRAL_NOT_NEEDS_INFO")
    r["status"] = "RECEIVED"
    svc.touch(r)
    return success_object(public(r), 200)


@app.route("/wound-care/referrals/<referral_id>/accept", methods=["POST"])
def referral_accept(referral_id):
    auth({"IntakeCoordinator"})
    r = get_or_404(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    if r["status"] != "RECEIVED":
        api_error("ERR_REFERRAL_NOT_RECEIVED")
    has_assessment = any(
        a["patient_id"] == r["patient_id"] for a in db.wound_assessments.values()
    )
    if not has_assessment:
        api_error("ERR_NO_ASSESSMENT_ON_FILE")
    r["status"] = "ACCEPTED"
    svc.touch(r)
    patient = db.patients.get(r["patient_id"])
    if patient and patient["status"] == "INTAKE":
        patient["status"] = "IN_CARE"
        svc.touch(patient)
    return success_object(public(r), 200)


@app.route("/wound-care/referrals/<referral_id>/decline", methods=["POST"])
def referral_decline(referral_id):
    auth({"IntakeCoordinator"})
    r = get_or_404(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    if r["status"] != "RECEIVED":
        api_error("ERR_REFERRAL_NOT_RECEIVED")
    r["status"] = "DECLINED"
    svc.touch(r)
    return success_object(public(r), 200)


# ===========================================================================
# WoundAssessment (append-only: id + created_at only)
# ===========================================================================
@app.route("/wound-care/wound-assessments", methods=["POST"])
def create_wound_assessment():
    auth({"WoundClinician"})
    body = get_body()
    require_fields(body, ["patient_id", "stage", "length_cm", "width_cm", "tissue_type"])
    if body["stage"] not in ("STAGE_1", "STAGE_2", "STAGE_3", "STAGE_4", "UNSTAGEABLE"):
        api_error("ERR_INVALID_REQUEST", "invalid stage")
    if body["tissue_type"] not in ("GRANULATION", "EPITHELIAL", "SLOUGH", "NECROTIC"):
        api_error("ERR_INVALID_REQUEST", "invalid tissue_type")
    length_cm = as_number_gt(body, "length_cm", 0)
    width_cm = as_number_gt(body, "width_cm", 0)
    infected = body.get("infected", False)
    if not isinstance(infected, bool):
        api_error("ERR_INVALID_REQUEST", "infected must be boolean")
    patient = get_or_404(db.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")

    entity = common_fields(full=False)
    entity.update({
        "patient_id": body["patient_id"],
        "assessed_at": svc.patient_center_clock(patient),
        "stage": body["stage"],
        "length_cm": length_cm,
        "width_cm": width_cm,
        "tissue_type": body["tissue_type"],
        "infected": infected,
        "area_cm2": calc.wound_area(length_cm, width_cm),
        "severity_score": calc.wound_severity_score(
            body["stage"], length_cm, width_cm, body["tissue_type"], infected),
    })
    db.wound_assessments[entity["id"]] = entity

    # refresh Patient.latest_wound_area_cm2 (assessed_at DESC, tie created_at DESC)
    patient_assessments = [
        a for a in db.wound_assessments.values() if a["patient_id"] == patient["id"]
    ]
    patient_assessments.sort(
        key=lambda a: (svc._parse_dt(a["assessed_at"]), svc._parse_dt(a["created_at"])),
        reverse=True,
    )
    latest = patient_assessments[0]
    patient["latest_wound_area_cm2"] = latest["area_cm2"]
    svc.touch(patient)

    # auto-HEAL check on ACTIVE plan(s)
    for plan in db.treatment_plans.values():
        if plan["patient_id"] == patient["id"] and plan["status"] == "ACTIVE":
            actual, _ = svc.compute_healing(plan)
            if (actual is not None and actual >= 100) or patient["latest_wound_area_cm2"] == 0:
                plan["status"] = "HEALED"
                svc.touch(plan)

    return success_object(public(entity), 201)


@app.route("/wound-care/wound-assessments", methods=["GET"])
def list_wound_assessments():
    auth(ALL_ROLES)
    return list_response(db.wound_assessments, {"patient_id": request.args.get("patient_id")})


@app.route("/wound-care/wound-assessments/<assessment_id>", methods=["GET"])
def get_wound_assessment(assessment_id):
    auth(ALL_ROLES)
    a = get_or_404(db.wound_assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    return success_object(public(a), 200)


# ===========================================================================
# PhotoDocument (append-only)
# ===========================================================================
@app.route("/wound-care/photo-documents", methods=["POST"])
def create_photo_document():
    auth({"WoundClinician"})
    body = get_body()
    require_fields(body, ["wound_assessment_id", "patient_id", "image_uri"])
    get_or_404(db.wound_assessments, body["wound_assessment_id"], "ERR_ASSESSMENT_NOT_FOUND")
    patient = get_or_404(db.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    entity = common_fields(full=False)
    entity.update({
        "wound_assessment_id": body["wound_assessment_id"],
        "patient_id": body["patient_id"],
        "image_uri": body["image_uri"],
        "captured_at": svc.patient_center_clock(patient),
    })
    db.photo_documents[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/photo-documents", methods=["GET"])
def list_photo_documents():
    auth(ALL_ROLES)
    return list_response(db.photo_documents, {
        "wound_assessment_id": request.args.get("wound_assessment_id"),
        "patient_id": request.args.get("patient_id"),
    })


@app.route("/wound-care/photo-documents/<photo_id>", methods=["GET"])
def get_photo_document(photo_id):
    auth(ALL_ROLES)
    p = get_or_404(db.photo_documents, photo_id, "ERR_NOT_FOUND")
    return success_object(public(p), 200)


# ===========================================================================
# TreatmentPlan
# ===========================================================================
@app.route("/wound-care/treatment-plans", methods=["POST"])
def create_treatment_plan():
    auth({"WoundClinician"})
    body = get_body()
    require_fields(body, ["patient_id", "baseline_assessment_id"])
    budget = as_int_ge(body, "debridement_supply_budget_cents", 0)
    get_or_404(db.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")
    get_or_404(db.wound_assessments, body["baseline_assessment_id"], "ERR_ASSESSMENT_NOT_FOUND")
    entity = common_fields()
    entity.update({
        "patient_id": body["patient_id"],
        "baseline_assessment_id": body["baseline_assessment_id"],
        "coverage_status": "PENDING",
        "provisional_covered_cents": 0,
        "provisional_hbo_covered_cents": 0,
        "finalized_hbo_covered_cents": 0,
        "debridement_supply_budget_cents": budget,
        "status": "DRAFT",
    })
    db.treatment_plans[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/treatment-plans", methods=["GET"])
def list_treatment_plans():
    auth(ALL_ROLES)
    return list_response(db.treatment_plans, {
        "patient_id": request.args.get("patient_id"),
        "baseline_assessment_id": request.args.get("baseline_assessment_id"),
    })


@app.route("/wound-care/treatment-plans/<plan_id>", methods=["GET"])
def get_treatment_plan(plan_id):
    auth(ALL_ROLES)
    p = get_or_404(db.treatment_plans, plan_id, "ERR_PLAN_NOT_FOUND")
    return success_object(public(p), 200)


@app.route("/wound-care/treatment-plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    auth({"WoundClinician"})
    plan = get_or_404(db.treatment_plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "DRAFT":
        api_error("ERR_PLAN_NOT_DRAFT")
    patient = db.patients.get(plan["patient_id"])
    if not patient or patient["status"] != "IN_CARE":
        api_error("ERR_PATIENT_NOT_IN_CARE")
    if plan["coverage_status"] == "NOT_COVERED":
        api_error("ERR_COVERAGE_DENIED")
    plan["status"] = "ACTIVE"
    svc.touch(plan)
    return success_object(public(plan), 200)


@app.route("/wound-care/treatment-plans/<plan_id>/suspend", methods=["POST"])
def suspend_plan(plan_id):
    auth({"WoundClinician"})
    plan = get_or_404(db.treatment_plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "ACTIVE":
        api_error("ERR_PLAN_NOT_ACTIVE")
    plan["status"] = "SUSPENDED"
    svc.cancel_scheduled_sessions_of_plan(plan)
    svc.recompute_provisional_hbo(plan)
    svc.touch(plan)
    return success_object(public(plan), 200)


@app.route("/wound-care/treatment-plans/<plan_id>/resume", methods=["POST"])
def resume_plan(plan_id):
    auth({"WoundClinician"})
    plan = get_or_404(db.treatment_plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "SUSPENDED":
        api_error("ERR_PLAN_NOT_SUSPENDED")
    patient = db.patients.get(plan["patient_id"])
    if not patient or patient["status"] != "IN_CARE":
        api_error("ERR_PATIENT_NOT_IN_CARE")
    plan["status"] = "ACTIVE"
    svc.touch(plan)
    return success_object(public(plan), 200)


@app.route("/wound-care/treatment-plans/<plan_id>/outcome-report", methods=["POST"])
def outcome_report(plan_id):
    auth({"WoundClinician"})
    plan = get_or_404(db.treatment_plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] not in ("ACTIVE", "SUSPENDED"):
        api_error("ERR_PLAN_NOT_CLOSEABLE")
    open_sessions = any(
        s["treatment_plan_id"] == plan["id"] and s["status"] == "SCHEDULED"
        for s in db.hbo_sessions.values()
    )
    if open_sessions:
        api_error("ERR_OPEN_SESSIONS_EXIST")

    actual, projected = svc.compute_healing(plan)
    final_hbo = svc.finalized_hbo(plan)
    patient = db.patients.get(plan["patient_id"])
    policy = db.payer_policies.get(patient["payer_policy_id"]) if patient else None
    threshold = policy["min_healing_pct_threshold"] if policy else 0
    meets = (actual is not None and actual >= threshold)

    report = common_fields()
    report.update({
        "treatment_plan_id": plan["id"],
        "actual_healing_pct": actual if actual is not None else 0,
        "projected_healing_pct": projected if projected is not None else 0,
        "finalized_hbo_covered_cents": final_hbo,
        "meets_coverage_threshold": meets,
        "status": "FINAL",
    })
    db.outcome_reports[report["id"]] = report

    plan["status"] = "CLOSED"
    plan["finalized_hbo_covered_cents"] = final_hbo
    svc.touch(plan)

    return success_object(public(report), 201)


# ===========================================================================
# PriorAuthorization
# ===========================================================================
@app.route("/wound-care/prior-authorizations", methods=["POST"])
def create_prior_auth():
    auth({"PayerLiaison"})
    body = get_body()
    require_fields(body, ["treatment_plan_id", "clinical_justification"])
    requested = as_int_ge(body, "requested_hbo_sessions", 1)
    get_or_404(db.treatment_plans, body["treatment_plan_id"], "ERR_PLAN_NOT_FOUND")
    entity = common_fields()
    entity.update({
        "treatment_plan_id": body["treatment_plan_id"],
        "requested_hbo_sessions": requested,
        "clinical_justification": body["clinical_justification"],
        "info_request_note": None,
        "status": "SUBMITTED",
    })
    db.prior_authorizations[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/prior-authorizations", methods=["GET"])
def list_prior_auths():
    auth(ALL_ROLES)
    return list_response(db.prior_authorizations,
                         {"treatment_plan_id": request.args.get("treatment_plan_id")})


@app.route("/wound-care/prior-authorizations/<auth_id>", methods=["GET"])
def get_prior_auth(auth_id):
    auth(ALL_ROLES)
    a = get_or_404(db.prior_authorizations, auth_id, "ERR_AUTH_NOT_FOUND")
    return success_object(public(a), 200)


@app.route("/wound-care/prior-authorizations/<auth_id>/request-info", methods=["POST"])
def prior_auth_request_info(auth_id):
    auth({"PayerLiaison"})
    a = get_or_404(db.prior_authorizations, auth_id, "ERR_AUTH_NOT_FOUND")
    if a["status"] != "SUBMITTED":
        api_error("ERR_AUTH_NOT_SUBMITTED")
    body = get_body()
    a["status"] = "ADDITIONAL_INFO_REQUESTED"
    a["info_request_note"] = body.get("info_request_note")
    svc.touch(a)
    return success_object(public(a), 200)


@app.route("/wound-care/prior-authorizations/<auth_id>/resubmit", methods=["POST"])
def prior_auth_resubmit(auth_id):
    auth({"PayerLiaison"})
    a = get_or_404(db.prior_authorizations, auth_id, "ERR_AUTH_NOT_FOUND")
    if a["status"] != "ADDITIONAL_INFO_REQUESTED":
        api_error("ERR_AUTH_NOT_AWAITING_INFO")
    a["status"] = "SUBMITTED"
    svc.touch(a)
    return success_object(public(a), 200)


@app.route("/wound-care/prior-authorizations/<auth_id>/approve", methods=["POST"])
def prior_auth_approve(auth_id):
    auth({"PayerLiaison"})
    a = get_or_404(db.prior_authorizations, auth_id, "ERR_AUTH_NOT_FOUND")
    if a["status"] != "SUBMITTED":
        api_error("ERR_AUTH_NOT_SUBMITTED")
    a["status"] = "APPROVED"
    svc.touch(a)
    plan = db.treatment_plans.get(a["treatment_plan_id"])
    if plan:
        plan["coverage_status"] = "COVERED"
        svc.recompute_provisional_hbo(plan)
        svc.touch(plan)
    return success_object(public(a), 200)


@app.route("/wound-care/prior-authorizations/<auth_id>/deny", methods=["POST"])
def prior_auth_deny(auth_id):
    auth({"PayerLiaison"})
    a = get_or_404(db.prior_authorizations, auth_id, "ERR_AUTH_NOT_FOUND")
    if a["status"] != "SUBMITTED":
        api_error("ERR_AUTH_NOT_SUBMITTED")
    a["status"] = "DENIED"
    svc.touch(a)
    plan = db.treatment_plans.get(a["treatment_plan_id"])
    if plan:
        plan["coverage_status"] = "NOT_COVERED"
        for order in db.supply_orders.values():
            if order["treatment_plan_id"] == plan["id"] and order["status"] == "SUBMITTED":
                order["status"] = "REJECTED"
                svc.touch(order)
                plan["provisional_covered_cents"] -= order["covered_cents"]
        svc.touch(plan)
    return success_object(public(a), 200)


# ===========================================================================
# DebridementProcedure
# ===========================================================================
@app.route("/wound-care/debridement-procedures", methods=["POST"])
def create_debridement():
    auth({"WoundClinician"})
    body = get_body()
    require_fields(body, ["treatment_plan_id", "clinician_id", "window_start", "window_end"])
    plan = get_or_404(db.treatment_plans, body["treatment_plan_id"], "ERR_PLAN_NOT_FOUND")
    clinician = get_or_404(db.clinicians, body["clinician_id"], "ERR_CLINICIAN_NOT_FOUND")

    # priority 6: cross-center
    patient = db.patients.get(plan["patient_id"])
    if not patient or clinician["center_id"] != patient["center_id"]:
        api_error("ERR_CROSS_CENTER_REFERENCE")
    # priority 7: clinician role
    if clinician["role_kind"] != "WOUND":
        api_error("ERR_CLINICIAN_ROLE_MISMATCH")
    # parse intervals (unparseable -> priority 13 ERR_INVALID_REQUEST)
    try:
        ws = svc._parse_dt(body["window_start"])
        we = svc._parse_dt(body["window_end"])
    except Exception:
        api_error("ERR_INVALID_REQUEST", "invalid window datetime")
    # priority 10: temporal overlap (closed interval, no buffer, touching allowed)
    for p in db.debridement_procedures.values():
        if p["clinician_id"] == clinician["id"] and p["status"] == "SCHEDULED":
            ps = svc._parse_dt(p["window_start"])
            pe = svc._parse_dt(p["window_end"])
            if ws < pe and ps < we:
                api_error("ERR_CLINICIAN_SLOT_CONFLICT")

    # priority 13 (field validity) — window_end > window_start
    if not (we > ws):
        api_error("ERR_INVALID_REQUEST", "window_end must be > window_start")

    entity = common_fields()
    entity.update({
        "treatment_plan_id": plan["id"],
        "clinician_id": clinician["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "performed_by_user_id": None,
        "status": "SCHEDULED",
    })
    db.debridement_procedures[entity["id"]] = entity
    return success_object(public(entity), 201)


@app.route("/wound-care/debridement-procedures", methods=["GET"])
def list_debridements():
    auth(ALL_ROLES)
    return list_response(db.debridement_procedures, {
        "treatment_plan_id": request.args.get("treatment_plan_id"),
        "clinician_id": request.args.get("clinician_id"),
    })


@app.route("/wound-care/debridement-procedures/<proc_id>", methods=["GET"])
def get_debridement(proc_id):
    auth(ALL_ROLES)
    p = get_or_404(db.debridement_procedures, proc_id, "ERR_PROC_NOT_FOUND")
    return success_object(public(p), 200)


@app.route("/wound-care/debridement-procedures/<proc_id>/complete", methods=["POST"])
def complete_debridement(proc_id):
    user_id, _ = auth({"WoundClinician"})
    proc = get_or_404(db.debridement_procedures, proc_id, "ERR_PROC_NOT_FOUND")
    if proc["status"] != "SCHEDULED":
        api_error("ERR_PROC_NOT_SCHEDULED")
    plan = db.treatment_plans.get(proc["treatment_plan_id"])
    if not plan or plan["status"] != "ACTIVE":
        api_error("ERR_PLAN_NOT_ACTIVE")
    patient = db.patients.get(plan["patient_id"]) if plan else None
    if not patient or patient["status"] != "IN_CARE":
        api_error("ERR_PATIENT_NOT_IN_CARE")
    proc["status"] = "COMPLETED"
    proc["performed_by_user_id"] = user_id
    svc.touch(proc)
    return success_object(public(proc), 200)


@app.route("/wound-care/debridement-procedures/<proc_id>/cancel", methods=["POST"])
def cancel_debridement(proc_id):
    auth({"WoundClinician"})
    proc = get_or_404(db.debridement_procedures, proc_id, "ERR_PROC_NOT_FOUND")
    if proc["status"] != "SCHEDULED":
        api_error("ERR_PROC_NOT_SCHEDULED")
    proc["status"] = "CANCELLED"
    svc.touch(proc)
    return success_object(public(proc), 200)


# ===========================================================================
# HboSession
# ===========================================================================
@app.route("/wound-care/hbo-sessions", methods=["POST"])
def create_hbo_session():
    auth({"HyperbaricTech"})
    body = get_body()
    require_fields(body, ["treatment_plan_id", "chamber_id", "window_start",
                          "window_end", "treatment_pressure_ata"])
    plan = get_or_404(db.treatment_plans, body["treatment_plan_id"], "ERR_PLAN_NOT_FOUND")
    chamber = get_or_404(db.chambers, body["chamber_id"], "ERR_CHAMBER_NOT_FOUND")

    # priority 4: OCC
    if "expected_plan_version" in body and body["expected_plan_version"] is not None:
        if body["expected_plan_version"] != plan["version"]:
            api_error("ERR_STALE_PLAN_VERSION")

    # priority 6: cross-center
    patient = db.patients.get(plan["patient_id"])
    if not patient or chamber["center_id"] != patient["center_id"]:
        api_error("ERR_CROSS_CENTER_REFERENCE")

    # parse intervals (unparseable -> priority 13 ERR_INVALID_REQUEST)
    try:
        ws = svc._parse_dt(body["window_start"])
        we = svc._parse_dt(body["window_end"])
    except Exception:
        api_error("ERR_INVALID_REQUEST", "invalid window datetime")
    # priority 9: chamber temporal (half-open + right-padded buffer)
    from datetime import timedelta
    buffer = timedelta(minutes=chamber["turnover_buffer_minutes"])
    for s in db.hbo_sessions.values():
        if s["chamber_id"] == chamber["id"] and s["status"] == "SCHEDULED":
            ss = svc._parse_dt(s["window_start"])
            se = svc._parse_dt(s["window_end"])
            if ws < (se + buffer) and ss < (we + buffer):
                api_error("ERR_CHAMBER_SLOT_CONFLICT")

    # priority 11: coverage active
    if plan["coverage_status"] != "COVERED":
        api_error("ERR_COVERAGE_NOT_ACTIVE")

    # priority 13: field validity — window_end > window_start, pressure > 1.0
    if not (we > ws):
        api_error("ERR_INVALID_REQUEST", "window_end must be > window_start")
    pressure = as_number_gt(body, "treatment_pressure_ata", 1.0)

    entity = common_fields()
    entity.update({
        "treatment_plan_id": plan["id"],
        "chamber_id": chamber["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "treatment_pressure_ata": pressure,
        "dive_log_entries": [],
        "status": "SCHEDULED",
    })
    db.hbo_sessions[entity["id"]] = entity
    chamber["occupied_slot_count"] += 1
    svc.touch(chamber)
    svc.recompute_provisional_hbo(plan)
    svc.touch(plan)
    return success_object(public(entity), 201)


@app.route("/wound-care/hbo-sessions", methods=["GET"])
def list_hbo_sessions():
    auth(ALL_ROLES)
    return list_response(db.hbo_sessions, {
        "treatment_plan_id": request.args.get("treatment_plan_id"),
        "chamber_id": request.args.get("chamber_id"),
    })


@app.route("/wound-care/hbo-sessions/<session_id>", methods=["GET"])
def get_hbo_session(session_id):
    auth(ALL_ROLES)
    s = get_or_404(db.hbo_sessions, session_id, "ERR_SESSION_NOT_FOUND")
    return success_object(public(s), 200)


@app.route("/wound-care/hbo-sessions/<session_id>/complete", methods=["POST"])
def complete_hbo_session(session_id):
    auth({"HyperbaricTech"})
    session = get_or_404(db.hbo_sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if session["status"] != "SCHEDULED":
        api_error("ERR_SESSION_NOT_SCHEDULED")
    plan = db.treatment_plans.get(session["treatment_plan_id"])
    if not plan or plan["status"] != "ACTIVE":
        api_error("ERR_PLAN_NOT_ACTIVE")
    body = get_body()
    dive_log = body.get("dive_log_entries")
    if not dive_log or not isinstance(dive_log, list) or len(dive_log) == 0:
        api_error("ERR_EMPTY_DIVE_LOG")
    session["dive_log_entries"] = dive_log
    session["status"] = "COMPLETED"
    svc.touch(session)
    chamber = db.chambers.get(session["chamber_id"])
    if chamber:
        chamber["occupied_slot_count"] -= 1
        svc.touch(chamber)
    svc.recompute_provisional_hbo(plan)
    svc.touch(plan)
    return success_object(public(session), 200)


@app.route("/wound-care/hbo-sessions/<session_id>/cancel", methods=["POST"])
def cancel_hbo_session(session_id):
    auth({"HyperbaricTech"})
    session = get_or_404(db.hbo_sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if session["status"] != "SCHEDULED":
        api_error("ERR_SESSION_NOT_SCHEDULED")
    session["status"] = "CANCELLED"
    svc.touch(session)
    chamber = db.chambers.get(session["chamber_id"])
    if chamber:
        chamber["occupied_slot_count"] -= 1
        svc.touch(chamber)
    plan = db.treatment_plans.get(session["treatment_plan_id"])
    if plan:
        svc.recompute_provisional_hbo(plan)
        svc.touch(plan)
    return success_object(public(session), 200)


# ===========================================================================
# SupplyOrder
# ===========================================================================
def _validate_line_items(line_items):
    if not isinstance(line_items, list) or len(line_items) == 0:
        api_error("ERR_INVALID_REQUEST", "line_items must be a non-empty list")
    for li in line_items:
        if not isinstance(li, dict):
            api_error("ERR_INVALID_REQUEST", "each line item must be an object")
        for f in ("unit_price_cents", "qty", "coverage_rate"):
            if li.get(f) is None:
                api_error("ERR_INVALID_REQUEST", "line item missing %s" % f)
        rate = li["coverage_rate"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            api_error("ERR_INVALID_REQUEST", "coverage_rate must be a number")
        if rate < 0 or rate > 1:
            api_error("ERR_INVALID_REQUEST", "coverage_rate must be in [0,1]")
        for f in ("unit_price_cents", "qty"):
            v = li[f]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                api_error("ERR_INVALID_REQUEST", "%s must be a number" % f)


@app.route("/wound-care/supply-orders", methods=["POST"])
def create_supply_order():
    auth({"WoundClinician"})
    body = get_body()
    require_fields(body, ["treatment_plan_id", "supply_kind", "line_items"])
    plan = get_or_404(db.treatment_plans, body["treatment_plan_id"], "ERR_PLAN_NOT_FOUND")

    # priority 4: OCC
    if "expected_plan_version" in body and body["expected_plan_version"] is not None:
        if body["expected_plan_version"] != plan["version"]:
            api_error("ERR_STALE_PLAN_VERSION")

    # priority 12: budget check (after computing covered_cents)
    # priority 13: field validity — supply_kind, line_items
    if body["supply_kind"] not in ("ADVANCED_DRESSING", "SKIN_GRAFT"):
        api_error("ERR_INVALID_REQUEST", "invalid supply_kind")
    _validate_line_items(body["line_items"])
    covered = calc.supply_reimbursement(body["line_items"])

    if plan["provisional_covered_cents"] + covered > plan["debridement_supply_budget_cents"]:
        api_error("ERR_SUPPLY_BUDGET_EXCEEDED")

    entity = common_fields()
    entity.update({
        "treatment_plan_id": plan["id"],
        "supply_kind": body["supply_kind"],
        "line_items": body["line_items"],
        "covered_cents": covered,
        "status": "SUBMITTED",
    })
    db.supply_orders[entity["id"]] = entity
    plan["provisional_covered_cents"] += covered
    svc.touch(plan)
    return success_object(public(entity), 201)


@app.route("/wound-care/supply-orders", methods=["GET"])
def list_supply_orders():
    auth(ALL_ROLES)
    return list_response(db.supply_orders,
                         {"treatment_plan_id": request.args.get("treatment_plan_id")})


@app.route("/wound-care/supply-orders/<order_id>", methods=["GET"])
def get_supply_order(order_id):
    auth(ALL_ROLES)
    o = get_or_404(db.supply_orders, order_id, "ERR_ORDER_NOT_FOUND")
    return success_object(public(o), 200)


@app.route("/wound-care/supply-orders/<order_id>/approve", methods=["POST"])
def approve_supply_order(order_id):
    auth({"PayerLiaison"})
    o = get_or_404(db.supply_orders, order_id, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "SUBMITTED":
        api_error("ERR_ORDER_NOT_SUBMITTED")
    o["status"] = "APPROVED"
    svc.touch(o)
    return success_object(public(o), 200)


@app.route("/wound-care/supply-orders/<order_id>/reject", methods=["POST"])
def reject_supply_order(order_id):
    auth({"PayerLiaison"})
    o = get_or_404(db.supply_orders, order_id, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "SUBMITTED":
        api_error("ERR_ORDER_NOT_SUBMITTED")
    o["status"] = "REJECTED"
    svc.touch(o)
    plan = db.treatment_plans.get(o["treatment_plan_id"])
    if plan:
        plan["provisional_covered_cents"] -= o["covered_cents"]
        svc.touch(plan)
    return success_object(public(o), 200)


@app.route("/wound-care/supply-orders/<order_id>/cancel", methods=["POST"])
def cancel_supply_order(order_id):
    auth({"WoundClinician"})
    o = get_or_404(db.supply_orders, order_id, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "SUBMITTED":
        api_error("ERR_ORDER_NOT_SUBMITTED")
    o["status"] = "CANCELLED"
    svc.touch(o)
    plan = db.treatment_plans.get(o["treatment_plan_id"])
    if plan:
        plan["provisional_covered_cents"] -= o["covered_cents"]
        svc.touch(plan)
    return success_object(public(o), 200)


# ===========================================================================
# AcuteTransfer
# ===========================================================================
@app.route("/wound-care/acute-transfers", methods=["POST"])
def create_acute_transfer():
    user_id, _ = auth({"AttendingPhysician"})
    body = get_body()
    require_fields(body, ["patient_id", "destination_facility", "clinical_reason"])
    patient = get_or_404(db.patients, body["patient_id"], "ERR_PATIENT_NOT_FOUND")

    # priority 8: segregation of duties — initiator must not have completed any
    # debridement on the patient's plan(s)
    patient_plan_ids = {
        p["id"] for p in db.treatment_plans.values() if p["patient_id"] == patient["id"]
    }
    for proc in db.debridement_procedures.values():
        if (proc["treatment_plan_id"] in patient_plan_ids
                and proc["status"] == "COMPLETED"
                and proc["performed_by_user_id"] == user_id):
            api_error("ERR_SEGREGATION_OF_DUTIES")

    entity = common_fields()
    entity.update({
        "patient_id": patient["id"],
        "destination_facility": body["destination_facility"],
        "clinical_reason": body["clinical_reason"],
        "initiated_by_user_id": user_id,
        "status": "INITIATED",
    })
    db.acute_transfers[entity["id"]] = entity

    # cascade: patient IN_CARE -> TRANSFERRED
    if patient["status"] == "IN_CARE":
        patient["status"] = "TRANSFERRED"
        svc.touch(patient)
    # cascade: patient's ACTIVE plan -> SUSPENDED, cancel its SCHEDULED sessions
    for plan in db.treatment_plans.values():
        if plan["patient_id"] == patient["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "SUSPENDED"
            svc.cancel_scheduled_sessions_of_plan(plan)
            svc.recompute_provisional_hbo(plan)
            svc.touch(plan)

    return success_object(public(entity), 201)


@app.route("/wound-care/acute-transfers", methods=["GET"])
def list_acute_transfers():
    auth(ALL_ROLES)
    return list_response(db.acute_transfers,
                         {"patient_id": request.args.get("patient_id")})


@app.route("/wound-care/acute-transfers/<transfer_id>", methods=["GET"])
def get_acute_transfer(transfer_id):
    auth(ALL_ROLES)
    t = get_or_404(db.acute_transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    return success_object(public(t), 200)


@app.route("/wound-care/acute-transfers/<transfer_id>/accept", methods=["POST"])
def accept_acute_transfer(transfer_id):
    auth({"AttendingPhysician"})
    t = get_or_404(db.acute_transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if t["status"] != "INITIATED":
        api_error("ERR_TRANSFER_NOT_INITIATED")
    t["status"] = "ACCEPTED"
    svc.touch(t)
    return success_object(public(t), 200)


@app.route("/wound-care/acute-transfers/<transfer_id>/cancel", methods=["POST"])
def cancel_acute_transfer(transfer_id):
    auth({"AttendingPhysician"})
    t = get_or_404(db.acute_transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if t["status"] != "INITIATED":
        api_error("ERR_TRANSFER_NOT_INITIATED")
    t["status"] = "CANCELLED"
    svc.touch(t)
    patient = db.patients.get(t["patient_id"])
    if patient and patient["status"] == "TRANSFERRED":
        patient["status"] = "IN_CARE"
        svc.touch(patient)
    return success_object(public(t), 200)


# ===========================================================================
# OutcomeReport (read only)
# ===========================================================================
@app.route("/wound-care/outcome-reports", methods=["GET"])
def list_outcome_reports():
    auth(ALL_ROLES)
    return list_response(db.outcome_reports,
                         {"treatment_plan_id": request.args.get("treatment_plan_id")})


@app.route("/wound-care/outcome-reports/<report_id>", methods=["GET"])
def get_outcome_report(report_id):
    auth(ALL_ROLES)
    r = get_or_404(db.outcome_reports, report_id, "ERR_NOT_FOUND")
    return success_object(public(r), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
