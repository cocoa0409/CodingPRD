"""Clients and vendor method profiles (PRD 3.1)."""
from flask import Blueprint

import auth
import clock
import db
import derived
import response
import schema
import views
from errors import fail
from schema import Field
from . import support

bp = Blueprint("clients", __name__)

RETENTION_MODES = ("DELETE_ON_COMPLETE", "RETAIN_90_DAYS", "RETAIN_WITH_CONSENT")
INTEGRATION_STATES = ("SANDBOX", "LIVE", "SUSPENDED")
METHOD_CODES = ("DOCUMENT_SCAN", "DATABASE_CHECK", "BIOMETRIC_COMPARISON",
                "KNOWLEDGE_BASED", "VOUCHING_ATTESTATION", "AGE_ESTIMATION")
AGE_BANDS = ("U13", "B13_15", "B16_17", "B18_20", "A21_PLUS")

CLIENT_CREATE_FIELDS = (
    Field("name", "string", required=True, min_len=1, max_len=120),
    Field("home_jurisdiction_code", "string", required=True, regex=r"[A-Z]{2}"),
    Field("biometric_retention_mode", "string", required=True, enum=RETENTION_MODES),
    Field("daily_session_quota", "int", required=True, minimum=1),
    Field("granted_review_credits", "int", required=True, minimum=0),
)

CLIENT_PATCH_FIELDS = (
    Field("integration_state", "string", enum=INTEGRATION_STATES),
    Field("biometric_retention_mode", "string", enum=RETENTION_MODES),
    Field("daily_session_quota", "int", minimum=1),
    Field("granted_review_credits", "int", minimum=0),
)

PROFILE_FIELDS = (
    Field("method_code", "string", required=True, enum=METHOD_CODES),
    Field("vendor_code", "string", required=True, min_len=1, max_len=24),
    Field("assurance_weight", "int", required=True, minimum=1, maximum=100),
    Field("acceptance_floor_bps", "int", required=True, minimum=0, maximum=10000),
    Field("far_bps", "int", required=True, minimum=0, maximum=10000),
    Field("frr_bps", "int", required=True, minimum=0, maximum=10000),
    Field("strong_evidence", "bool", required=True),
    Field("cost_cents", "int", required=True, minimum=0),
    Field("estimation_mae_months", "int", default=0, minimum=0),
    Field("band_accuracy_bps", "object", default=None),
)


@bp.post("/idv/clients")
def create_client():
    auth.authenticate((auth.PLATFORM_ADMIN,))
    values = schema.validate(schema.read_body(), CLIENT_CREATE_FIELDS)
    record = {
        "name": values["name"],
        "home_jurisdiction_code": values["home_jurisdiction_code"],
        "integration_state": "SANDBOX",
        "biometric_retention_mode": values["biometric_retention_mode"],
        "daily_session_quota": values["daily_session_quota"],
        "granted_review_credits": values["granted_review_credits"],
    }
    db.insert(db.CLIENTS, record)
    return response.object_response(views.client_view(record), 201)


@bp.patch("/idv/clients/<client_id>")
def patch_client(client_id):
    auth.authenticate((auth.PLATFORM_ADMIN,))
    client = db.get(db.CLIENTS, client_id)
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    values = schema.validate(schema.read_body(), CLIENT_PATCH_FIELDS)
    if not values:
        fail("ERR_INVALID_REQUEST", "At least one mutable field is required.")
    for key, value in values.items():
        client[key] = value
    db.touch(client)
    return response.object_response(views.client_view(client))


@bp.get("/idv/clients/<client_id>")
def read_client(client_id):
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER, auth.CLIENT_INTEGRATOR))
    client = db.get(db.CLIENTS, client_id)
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    auth.require_own_client(caller, client["id"])
    return response.object_response(views.client_view(client))


@bp.post("/idv/method-profiles")
def create_method_profile():
    auth.authenticate((auth.PLATFORM_ADMIN,))
    values = schema.validate(schema.read_body(), PROFILE_FIELDS)
    band_accuracy = values.get("band_accuracy_bps")
    if band_accuracy is None:
        band_accuracy = {}
    for band, accuracy in band_accuracy.items():
        if band not in AGE_BANDS:
            fail("ERR_INVALID_REQUEST", "band_accuracy_bps contains an unsupported band: %s" % band)
        if not isinstance(accuracy, int) or isinstance(accuracy, bool):
            fail("ERR_INVALID_REQUEST", "band_accuracy_bps values must be integers.")
        if accuracy < 0 or accuracy > 10000:
            fail("ERR_INVALID_REQUEST", "band_accuracy_bps values must be between 0 and 10000.")
    for existing in db.METHOD_PROFILES.values():
        if (existing["method_code"] == values["method_code"]
                and existing["vendor_code"] == values["vendor_code"]):
            fail("ERR_METHOD_PROFILE_DUPLICATE")
    record = {
        "method_code": values["method_code"],
        "vendor_code": values["vendor_code"],
        "assurance_weight": values["assurance_weight"],
        "acceptance_floor_bps": values["acceptance_floor_bps"],
        "far_bps": values["far_bps"],
        "frr_bps": values["frr_bps"],
        "strong_evidence": values["strong_evidence"],
        "cost_cents": values["cost_cents"],
        "estimation_mae_months": values["estimation_mae_months"],
        "band_accuracy_bps": dict(band_accuracy),
        "bias_state": "CLEARED",
        "restricted_at": None,
    }
    db.insert(db.METHOD_PROFILES, record)
    return response.object_response(views.method_profile_view(record), 201)


@bp.get("/idv/method-profiles/<profile_id>")
def read_method_profile(profile_id):
    auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER, auth.CLIENT_INTEGRATOR))
    profile = db.get(db.METHOD_PROFILES, profile_id)
    if profile is None:
        fail("ERR_METHOD_PROFILE_NOT_FOUND")
    return response.object_response(views.method_profile_view(profile))


@bp.get("/idv/method-profiles/<profile_id>/bias-audits")
def list_profile_bias_audits(profile_id):
    auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER))
    profile = db.get(db.METHOD_PROFILES, profile_id)
    if profile is None:
        fail("ERR_METHOD_PROFILE_NOT_FOUND")
    state = support.enum_filter("state", ("COLLECTING", "EVALUATED", "REMEDIATION_REQUIRED", "REMEDIATED"))
    records = derived.bias_audits_of_profile(profile_id)
    if state is not None:
        records = [a for a in records if a["state"] == state]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.bias_audit_view(a) for a in page], limit, offset, total)
