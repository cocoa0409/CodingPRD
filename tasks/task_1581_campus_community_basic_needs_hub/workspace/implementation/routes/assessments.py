"""Confidential intake assessment lifecycle (PRD 3.2)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_CLIENT_NOT_ACTIVE,
    ERR_ASSESSMENT_NOT_EDITABLE, ERR_CONSENT_REQUIRED, ERR_STALE_VERSION,
    ERR_NOT_FOUND,
)
from middleware import (
    authenticate, authorize, check_client_scope, check_confidential_wall,
)
from response import success_object
from routes.helpers import list_response
from services import calculations as calc
from services.core import new_record, touch, serialize_assessment
from util import CLOCK, fmt_ts
from validate import (
    get_body, req_int, req_enum, req_bool, require_path_resource,
)

bp = Blueprint("assessments", __name__)

HOUSING_STATUSES = ["STABLE", "COST_BURDENED", "UNSTABLE", "HOMELESS"]
ASSESSMENT_READ_ROLES = ["Client", "IntakeCoordinator", "BenefitsCounselor", "GrantReviewer", "HubAdmin"]
EDITABLE_FIELDS = [
    "household_size", "monthly_income_cents", "earned_income_cents", "shelter_cost_cents",
    "housing_status", "dependents_under_18", "receives_snap", "receives_childcare_subsidy",
    "food_insecurity_score", "consent_confidential",
]


def _validate_assessment_domains(rec):
    """Numeric domain re-validation (submit time; ERR_INVALID_REQUEST)."""
    if not isinstance(rec["household_size"], int) or rec["household_size"] < 1:
        raise_error(ERR_INVALID_REQUEST, "household_size must be >= 1")
    if not isinstance(rec["monthly_income_cents"], int) or rec["monthly_income_cents"] < 0:
        raise_error(ERR_INVALID_REQUEST, "monthly_income_cents must be >= 0")
    earned = rec["earned_income_cents"]
    if not isinstance(earned, int) or earned < 0 or earned > rec["monthly_income_cents"]:
        raise_error(ERR_INVALID_REQUEST, "earned_income_cents must be within [0, monthly_income_cents]")
    if not isinstance(rec["shelter_cost_cents"], int) or rec["shelter_cost_cents"] < 0:
        raise_error(ERR_INVALID_REQUEST, "shelter_cost_cents must be >= 0")
    if rec["housing_status"] not in HOUSING_STATUSES:
        raise_error(ERR_INVALID_REQUEST, "invalid housing_status")
    dep = rec["dependents_under_18"]
    if not isinstance(dep, int) or dep < 0 or dep >= rec["household_size"]:
        raise_error(ERR_INVALID_REQUEST, "dependents_under_18 must be >= 0 and < household_size")
    if not isinstance(rec["receives_snap"], bool) or not isinstance(rec["receives_childcare_subsidy"], bool):
        raise_error(ERR_INVALID_REQUEST, "receives flags must be boolean")
    if not isinstance(rec["food_insecurity_score"], int) or not (0 <= rec["food_insecurity_score"] <= 6):
        raise_error(ERR_INVALID_REQUEST, "food_insecurity_score must be in 0..6")
    if not isinstance(rec["consent_confidential"], bool):
        raise_error(ERR_INVALID_REQUEST, "consent_confidential must be boolean")


def _get_client_and_assessment(cid, aid):
    client = require_path_resource("clients", cid, "client")
    assessment = db["assessments"].get(aid)
    if assessment is None or assessment["client_id"] != client["id"]:
        raise_error(ERR_NOT_FOUND, f"assessment id not found under client: {aid}")
    return client, assessment


@bp.post("/clients/<cid>/assessments")
def create_assessment(cid):
    caller = authenticate()
    authorize(caller, ["Client", "IntakeCoordinator"])
    client = require_path_resource("clients", cid, "client")
    check_client_scope(caller, client["id"])
    # Drafting for an EXITED client fails (state gate precedes body shape checks)
    if client["status"] == "EXITED":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "cannot draft an assessment for an EXITED client")
    body = get_body()
    rec_fields = {
        "household_size": req_int(body, "household_size"),
        "monthly_income_cents": req_int(body, "monthly_income_cents"),
        "earned_income_cents": body.get("earned_income_cents", 0),
        "shelter_cost_cents": body.get("shelter_cost_cents", 0),
        "housing_status": req_enum(body, "housing_status", HOUSING_STATUSES),
        "dependents_under_18": req_int(body, "dependents_under_18"),
        "receives_snap": req_bool(body, "receives_snap"),
        "receives_childcare_subsidy": req_bool(body, "receives_childcare_subsidy"),
        "food_insecurity_score": req_int(body, "food_insecurity_score"),
        "consent_confidential": req_bool(body, "consent_confidential"),
    }
    if not isinstance(rec_fields["earned_income_cents"], int) or isinstance(rec_fields["earned_income_cents"], bool):
        raise_error(ERR_INVALID_REQUEST, "earned_income_cents must be an integer")
    if not isinstance(rec_fields["shelter_cost_cents"], int) or isinstance(rec_fields["shelter_cost_cents"], bool):
        raise_error(ERR_INVALID_REQUEST, "shelter_cost_cents must be an integer")
    rec_fields["client_id"] = client["id"]
    _validate_assessment_domains(rec_fields)
    rec = new_record("assessments", {
        **rec_fields,
        "status": "DRAFT",
        "income_ratio": None,
        "eligibility_band": None,
        "submitted_at": None,
        "verified_at": None,
        "verified_by": None,
        "expires_at": None,
        "return_notes": None,
        "_ratio": None,
    })
    return success_object(serialize_assessment(rec), status=201)


@bp.get("/assessments")
def list_assessments():
    caller = authenticate()
    authorize(caller, ASSESSMENT_READ_ROLES, confidential=True)
    check_confidential_wall(caller)
    filters = {
        "client_id": request.args.get("client_id"),
        "status": request.args.get("status"),
        "verified_by": request.args.get("verified_by"),
    }
    scope = None
    if caller.role == "Client":
        scope = lambda rec: rec["client_id"] == caller.user_id
    return list_response("assessments", filters, serializer=serialize_assessment, scope_fn=scope)


@bp.get("/assessments/<aid>")
def get_assessment(aid):
    caller = authenticate()
    authorize(caller, ASSESSMENT_READ_ROLES, confidential=True)
    assessment = require_path_resource("assessments", aid, "assessment")
    check_client_scope(caller, assessment["client_id"])
    check_confidential_wall(caller)
    return success_object(serialize_assessment(assessment))


@bp.post("/clients/<cid>/assessments/<aid>/submit")
def submit_assessment(cid, aid):
    caller = authenticate()
    authorize(caller, ["Client", "IntakeCoordinator"])
    client, assessment = _get_client_and_assessment(cid, aid)
    check_client_scope(caller, client["id"])
    if assessment["status"] != "DRAFT":
        raise_error(ERR_ASSESSMENT_NOT_EDITABLE, "only a DRAFT assessment can be submitted")
    if assessment["consent_confidential"] is not True:
        raise_error(ERR_CONSENT_REQUIRED, "submission requires consent_confidential == true")
    _validate_assessment_domains(assessment)
    ratio, band = calc.compute_eligibility(
        assessment["household_size"], assessment["monthly_income_cents"], assessment["housing_status"])
    assessment["_ratio"] = ratio
    assessment["income_ratio"] = None  # serialized from _ratio
    assessment["eligibility_band"] = band
    assessment["submitted_at"] = CLOCK.now_iso()
    assessment["status"] = "SUBMITTED"
    touch(assessment)
    return success_object(serialize_assessment(assessment))


@bp.post("/clients/<cid>/assessments/<aid>/verify")
def verify_assessment(cid, aid):
    caller = authenticate()
    authorize(caller, ["IntakeCoordinator"])
    client, assessment = _get_client_and_assessment(cid, aid)
    if assessment["status"] != "SUBMITTED":
        raise_error(ERR_ASSESSMENT_NOT_EDITABLE, "only a SUBMITTED assessment can be verified")
    body = get_body()
    # OCC (priority 7): immediately after state admission, before business rules
    expected = body.get("expected_client_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_client_version is required")
    if expected != client["version"]:
        raise_error(ERR_STALE_VERSION, "expected_client_version does not match the client's current version")
    if client["status"] not in ("INTAKE_PENDING", "ACTIVE"):
        raise_error(ERR_CLIENT_NOT_ACTIVE, "verify requires the client to be INTAKE_PENDING or ACTIVE")
    now = CLOCK.now()
    assessment["verified_at"] = CLOCK.now_iso()
    assessment["verified_by"] = caller.user_id
    assessment["expires_at"] = fmt_ts(now + timedelta(days=365))
    assessment["status"] = "VERIFIED"
    touch(assessment)
    # Any other VERIFIED assessment of this client -> SUPERSEDED
    for other in list(db["assessments"].values()):
        if other["client_id"] == client["id"] and other["id"] != assessment["id"] \
                and other["status"] == "VERIFIED":
            other["status"] = "SUPERSEDED"
            touch(other)
    # First verification flips INTAKE_PENDING -> ACTIVE; every verification bumps Client.version
    if client["status"] == "INTAKE_PENDING":
        client["status"] = "ACTIVE"
    touch(client)
    return success_object(serialize_assessment(assessment))


@bp.post("/clients/<cid>/assessments/<aid>/return")
def return_assessment(cid, aid):
    caller = authenticate()
    authorize(caller, ["IntakeCoordinator"])
    client, assessment = _get_client_and_assessment(cid, aid)
    if assessment["status"] != "SUBMITTED":
        raise_error(ERR_ASSESSMENT_NOT_EDITABLE, "only a SUBMITTED assessment can be returned")
    body = get_body()
    notes = body.get("return_notes")
    if notes is None or not isinstance(notes, str):
        raise_error(ERR_INVALID_REQUEST, "return_notes is required")
    assessment["return_notes"] = notes
    assessment["status"] = "RETURNED"
    touch(assessment)
    return success_object(serialize_assessment(assessment))


@bp.post("/clients/<cid>/assessments/<aid>/revise")
def revise_assessment(cid, aid):
    caller = authenticate()
    authorize(caller, ["Client", "IntakeCoordinator"])
    client, assessment = _get_client_and_assessment(cid, aid)
    check_client_scope(caller, client["id"])
    if assessment["status"] != "RETURNED":
        raise_error(ERR_ASSESSMENT_NOT_EDITABLE, "only a RETURNED assessment can be revised")
    body = get_body()
    # Optional payload fields overwrite in place; types checked, domains re-validated at submit
    for field in EDITABLE_FIELDS:
        if field not in body:
            continue
        v = body[field]
        if field in ("household_size", "monthly_income_cents", "earned_income_cents",
                     "shelter_cost_cents", "dependents_under_18", "food_insecurity_score"):
            if v is None or isinstance(v, bool) or not isinstance(v, int):
                raise_error(ERR_INVALID_REQUEST, f"invalid integer field: {field}")
        elif field in ("receives_snap", "receives_childcare_subsidy", "consent_confidential"):
            if not isinstance(v, bool):
                raise_error(ERR_INVALID_REQUEST, f"invalid boolean field: {field}")
        elif field == "housing_status":
            if not isinstance(v, str):
                raise_error(ERR_INVALID_REQUEST, "invalid housing_status")
        assessment[field] = v
    # Frozen figures clear until the next submit
    assessment["_ratio"] = None
    assessment["income_ratio"] = None
    assessment["eligibility_band"] = None
    assessment["status"] = "DRAFT"
    touch(assessment)
    return success_object(serialize_assessment(assessment))
