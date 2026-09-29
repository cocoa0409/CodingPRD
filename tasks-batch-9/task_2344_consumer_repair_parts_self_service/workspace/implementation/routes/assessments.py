"""Self-repair eligibility rulings (PRD 3.5)."""
from flask import Blueprint, g

import db
from db import base_row
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, PROGRAM_ADMIN, REPAIR_PROVIDER_TECH, \
    SAFETY_REVIEWER, SELF_REPAIR_CUSTOMER, check_provider_scope, endpoint
from response import collection, created, ok
from routes.helpers import filter_eq, find_profile, get_assessment, get_model, get_part, \
    get_provider
from serializers import assessment_json
from services.eligibility import classify_warranty, decide, risk_index, side_outputs
from util import days
from validation import F, read_body

bp = Blueprint("assessments", __name__)

REQUESTER_CLASSES = ("SELF_REPAIR_CONSUMER", "AUTHORIZED_PROVIDER")
VALIDITY_DAYS = 60

READ_ROLES = [PROGRAM_ADMIN, SAFETY_REVIEWER, COMPLIANCE_OFFICER, SELF_REPAIR_CUSTOMER,
              REPAIR_PROVIDER_TECH]


@bp.post("/eligibility-assessments")
@endpoint([SELF_REPAIR_CUSTOMER, REPAIR_PROVIDER_TECH, PROGRAM_ADMIN])
def create_assessment():
    body = read_body([
        F("model_id", "string", required=True),
        F("part_id", "string", required=True),
        F("region_code", "string", required=True),
        F("requester_class", "enum", required=True, enum=REQUESTER_CLASSES),
        F("provider_id", "string"),
    ])
    if body["requester_class"] == "AUTHORIZED_PROVIDER" and body["provider_id"] is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "provider_id is required for an AUTHORIZED_PROVIDER request.")

    model = get_model(body["model_id"])
    part = get_part(body["part_id"])
    profile = find_profile(body["region_code"])
    provider = None
    if body["provider_id"] is not None:
        provider = get_provider(body["provider_id"])

    check_provider_scope(body["provider_id"])

    decision, tool_rental_part_id = decide(model, part, profile, body["requester_class"])
    pinned_revision_id, liability_warning_version = side_outputs(model)

    row = base_row()
    row.update({
        "model_id": model["id"],
        "part_id": part["id"],
        "provider_id": provider["id"] if provider is not None else None,
        "pinned_manual_revision_id": pinned_revision_id,
        "region_code": profile["region_code"],
        "requester_class": body["requester_class"],
        "requester_user_id": g.user_id,
        "decision": decision,
        "warranty_impact_class": classify_warranty(
            model, part, provider, body["requester_class"]),
        "self_repair_risk_index": risk_index(model, part),
        "liability_warning_version": liability_warning_version,
        "tool_rental_part_id": tool_rental_part_id,
        "status": "VALID",
        "expires_at": None,
    })
    row["expires_at"] = row["created_at"] + days(VALIDITY_DAYS)
    db.db.assessments.add(row)
    return created(assessment_json(row))


@bp.get("/eligibility-assessments/<assessment_id>")
@endpoint(READ_ROLES)
def read_assessment(assessment_id):
    return ok(assessment_json(get_assessment(assessment_id)))


@bp.get("/eligibility-assessments")
@endpoint(READ_ROLES)
def list_assessments():
    rows = db.db.assessments.all()
    for field in ("model_id", "part_id", "provider_id", "pinned_manual_revision_id",
                  "decision", "status"):
        rows = filter_eq(rows, field)
    return collection(rows, assessment_json)
