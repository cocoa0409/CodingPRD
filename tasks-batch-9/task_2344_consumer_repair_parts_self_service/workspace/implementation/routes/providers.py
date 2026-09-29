"""The independent repair provider programme (PRD 3.8)."""
from flask import Blueprint

import db
from db import base_row, setf, touch
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, FAILURE_ANALYSIS_ENGINEER, PROGRAM_ADMIN, \
    REPAIR_PROVIDER_TECH, SAFETY_REVIEWER, check_provider_scope, endpoint
from response import collection, created, ok
from routes.helpers import filter_eq, find_profile, get_cert, get_provider
from serializers import active_cert_count, cert_json, provider_json, required_cert_count
from services.compliance import revoke_valid_assessments_for_provider
from services.providers import VARIANTS, band_for_score, compute_score, stricter_tier
from validation import F, int_range, query_enum, read_body

bp = Blueprint("providers", __name__)

ACCESS_TIERS = ("TIER_1_UNRESTRICTED", "TIER_2_SAFETY", "TIER_3_STANDARD")
COURSE_CODES = ("CRS_BATTERY_SAFETY", "CRS_HIGH_VOLTAGE", "CRS_PAIRING_CALIBRATION",
                "CRS_GENERAL_REPAIR")
DECISIONS = ("AUTHORIZE", "SUSPEND", "REINSTATE", "REVOKE")
CERT_CREDIT_COST = 2
PASSING_SCORE = 70

PROVIDER_READ_ROLES = [PROGRAM_ADMIN, SAFETY_REVIEWER, COMPLIANCE_OFFICER,
                       REPAIR_PROVIDER_TECH, FAILURE_ANALYSIS_ENGINEER]
CERT_READ_ROLES = [PROGRAM_ADMIN, COMPLIANCE_OFFICER, REPAIR_PROVIDER_TECH]


@bp.post("/repair-providers")
@endpoint([PROGRAM_ADMIN])
def create_provider():
    body = read_body([
        F("legal_name", "string", required=True),
        F("region_code", "string", required=True),
        F("requested_access_tier", "enum", required=True, enum=ACCESS_TIERS),
        F("technician_count", "int", required=True),
    ])
    int_range(body["technician_count"], "technician_count", 1, 500)
    profile = find_profile(body["region_code"])

    row = base_row()
    row.update({
        "legal_name": body["legal_name"],
        "region_code": profile["region_code"],
        "requested_access_tier": body["requested_access_tier"],
        "technician_count": body["technician_count"],
        "authorization_status": "APPLIED",
        "parts_access_tier": None,
        "training_credit_granted_total": 0,
        "training_credit_balance": 0,
        "training_credit_forfeited_total": 0,
        "attested_compliance_score": None,
        "suspension_reason": None,
    })
    db.db.providers.add(row)
    return created(provider_json(row))


@bp.get("/repair-providers/<provider_id>")
@endpoint(PROVIDER_READ_ROLES)
def read_provider(provider_id):
    return ok(provider_json(get_provider(provider_id)))


@bp.get("/repair-providers")
@endpoint(PROVIDER_READ_ROLES)
def list_providers():
    rows = db.db.providers.all()
    for field in ("region_code", "authorization_status", "parts_access_tier"):
        rows = filter_eq(rows, field)
    return collection(rows, provider_json)


@bp.post("/repair-providers/<provider_id>/begin-training")
@endpoint([PROGRAM_ADMIN])
def begin_training(provider_id):
    body = read_body([F("training_credit_grant", "int", required=True)])
    int_range(body["training_credit_grant"], "training_credit_grant", 2, None)
    provider = get_provider(provider_id)

    if provider["authorization_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    grant = body["training_credit_grant"]
    setf(provider, "authorization_status", "TRAINING_IN_PROGRESS")
    setf(provider, "training_credit_granted_total",
         provider.get("training_credit_granted_total", 0) + grant)
    setf(provider, "training_credit_balance",
         provider.get("training_credit_balance", 0) + grant)
    touch(provider)
    return ok(provider_json(provider))


@bp.post("/repair-providers/<provider_id>/authorization-decision")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER])
def authorization_decision(provider_id):
    body = read_body([
        F("decision", "enum", required=True, enum=DECISIONS),
        F("decision_reason", "string"),
        F("granted_access_tier", "enum", enum=ACCESS_TIERS),
    ])
    provider = get_provider(provider_id)
    decision = body["decision"]
    status = provider["authorization_status"]

    expected_source = {
        "AUTHORIZE": ("TRAINING_IN_PROGRESS",),
        "REINSTATE": ("SUSPENDED",),
        "SUSPEND": ("AUTHORIZED",),
        "REVOKE": ("APPLIED", "TRAINING_IN_PROGRESS", "AUTHORIZED", "SUSPENDED"),
    }[decision]
    if status not in expected_source:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if decision in ("AUTHORIZE", "REINSTATE"):
        if active_cert_count(provider["id"]) < required_cert_count(provider):
            raise ApiError("ERR_TRAINING_COVERAGE_INSUFFICIENT")
        result = compute_score(provider, "ROLLING_ATTESTED")
        requested = body["granted_access_tier"] or provider["requested_access_tier"]
        setf(provider, "attested_compliance_score", result["score"])
        setf(provider, "parts_access_tier",
             stricter_tier(requested, band_for_score(result["score"])))
        setf(provider, "authorization_status", "AUTHORIZED")
        if decision == "REINSTATE":
            setf(provider, "suspension_reason", None)
    elif decision == "SUSPEND":
        setf(provider, "authorization_status", "SUSPENDED")
        setf(provider, "suspension_reason", body["decision_reason"])
        revoke_valid_assessments_for_provider(provider["id"])
    else:
        setf(provider, "authorization_status", "REVOKED")
        setf(provider, "parts_access_tier", None)
        balance = provider.get("training_credit_balance", 0)
        setf(provider, "training_credit_forfeited_total",
             provider.get("training_credit_forfeited_total", 0) + balance)
        setf(provider, "training_credit_balance", 0)

    touch(provider)
    return ok(provider_json(provider))


@bp.get("/repair-providers/<provider_id>/compliance-score")
@endpoint([PROGRAM_ADMIN, COMPLIANCE_OFFICER, REPAIR_PROVIDER_TECH])
def compliance_score(provider_id):
    variant = query_enum("variant", VARIANTS, default="ROLLING_ATTESTED")
    provider = get_provider(provider_id)
    # PRD 2.1: ownership checks on any provider-scoped resource compare the
    # resolved provider against the resource's provider id.
    check_provider_scope(provider["id"])
    result = compute_score(provider, variant)
    result["provider_id"] = provider["id"]
    return ok(result)


@bp.get("/repair-providers/<provider_id>/training-certifications")
@endpoint(CERT_READ_ROLES)
def list_provider_certs(provider_id):
    get_provider(provider_id)
    rows = [c for c in db.db.certs.all() if c["provider_id"] == provider_id]
    for field in ("technician_user_id", "course_code", "status"):
        rows = filter_eq(rows, field)
    return collection(rows, cert_json)


# --------------------------------------------------------------------------
# training certifications
# --------------------------------------------------------------------------

@bp.get("/training-certifications/<certification_id>")
@endpoint(CERT_READ_ROLES)
def read_cert(certification_id):
    return ok(cert_json(get_cert(certification_id)))


@bp.get("/training-certifications")
@endpoint(CERT_READ_ROLES)
def list_certs():
    rows = db.db.certs.all()
    for field in ("provider_id", "technician_user_id", "course_code", "status"):
        rows = filter_eq(rows, field)
    return collection(rows, cert_json)


@bp.post("/training-certifications")
@endpoint([PROGRAM_ADMIN, REPAIR_PROVIDER_TECH])
def create_cert():
    body = read_body([
        F("provider_id", "string", required=True),
        F("technician_user_id", "string", required=True),
        F("course_code", "enum", required=True, enum=COURSE_CODES),
        F("valid_from", "datetime", required=True),
        F("valid_until", "datetime", required=True),
        F("exam_score", "int", required=True),
    ])
    int_range(body["exam_score"], "exam_score", 0, 100)
    if body["valid_until"] < body["valid_from"]:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "valid_until precedes valid_from.")

    provider = get_provider(body["provider_id"])
    check_provider_scope(provider["id"])

    if provider["authorization_status"] not in ("TRAINING_IN_PROGRESS", "AUTHORIZED"):
        raise ApiError("ERR_PROVIDER_NOT_ACCEPTING_CERTS")

    at = db.now()
    if body["valid_until"] <= at or body["exam_score"] < PASSING_SCORE:
        raise ApiError("ERR_CERTIFICATION_ALREADY_EXPIRED")

    if provider.get("training_credit_balance", 0) < CERT_CREDIT_COST:
        raise ApiError("ERR_TRAINING_CREDIT_INSUFFICIENT")

    for existing in db.ordered(db.db.certs.all()):
        if existing["status"] != "ACTIVE":
            continue
        if existing["technician_user_id"] != body["technician_user_id"]:
            continue
        if existing["course_code"] != body["course_code"]:
            continue
        # Both bounds inclusive, so touching windows collide.
        if body["valid_from"] <= existing["valid_until"] \
                and existing["valid_from"] <= body["valid_until"]:
            raise ApiError("ERR_CERTIFICATION_WINDOW_OVERLAP")

    row = base_row()
    row.update({
        "provider_id": provider["id"],
        "technician_user_id": body["technician_user_id"],
        "course_code": body["course_code"],
        "valid_from": body["valid_from"],
        "valid_until": body["valid_until"],
        "exam_score": body["exam_score"],
        "status": "ACTIVE",
        "credits_consumed": CERT_CREDIT_COST,
        "void_reason": None,
    })
    db.db.certs.add(row)

    setf(provider, "training_credit_balance",
         provider.get("training_credit_balance", 0) - CERT_CREDIT_COST)
    touch(provider)
    return created(cert_json(row))


@bp.post("/training-certifications/<certification_id>/void")
@endpoint([PROGRAM_ADMIN])
def void_cert(certification_id):
    body = read_body([F("void_reason", "string")])
    cert = get_cert(certification_id)

    if cert["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    provider = db.db.providers.get(cert["provider_id"])
    if provider is not None and provider["authorization_status"] == "REVOKED":
        raise ApiError("ERR_CREDIT_RESTORE_FORBIDDEN")

    setf(cert, "status", "VOIDED")
    setf(cert, "credits_consumed", 0)
    setf(cert, "void_reason", body["void_reason"])

    if provider is not None:
        setf(provider, "training_credit_balance",
             provider.get("training_credit_balance", 0) + CERT_CREDIT_COST)
        touch(provider)
        if provider["authorization_status"] == "AUTHORIZED" \
                and active_cert_count(provider["id"]) < required_cert_count(provider):
            setf(provider, "authorization_status", "SUSPENDED")
            setf(provider, "suspension_reason", "CERT_COVERAGE_LOST")
            revoke_valid_assessments_for_provider(provider["id"])

    return ok(cert_json(cert))
