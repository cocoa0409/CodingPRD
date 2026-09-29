"""Applicant intake, out-of-state credentials and service records (PRD §3.2)."""
from decimal import Decimal

from flask import Blueprint

import db
import response
import serializers
import validators as v
from constants import (
    ALL_ROLES, CREDENTIAL_STATUSES, MILITARY_ELIGIBLE, MILITARY_STATUSES,
    ROLE_ADMIN, ROLE_APPLICANT, SEVERITIES, TRAINING_CATEGORIES,
)
from middleware import authenticate
from services import lookups

bp = Blueprint("applicants", __name__)


@bp.post("/licensure/applicants")
def create_applicant():
    authenticate([ROLE_ADMIN])
    body = v.body()
    full_name = v.f_string(body, "full_name")
    state_code = v.f_string(body, "state_code", pattern=v.TWO_LETTER_RE)
    residency_months = v.f_int(body, "residency_months", required=False,
                               default=0, minimum=0)
    military_status = v.f_enum(body, "military_status", MILITARY_STATUSES,
                               required=False, default="NONE")

    row = db.make_row({
        "full_name": full_name,
        "state_code": state_code,
        "residency_months": residency_months,
        "military_status": military_status,
        "disciplinary_risk_index_reported": Decimal("0.00"),
        "disciplinary_risk_index_effective": Decimal("0.00"),
        "good_standing_flag": True,
        "fee_waiver_eligible": military_status in MILITARY_ELIGIBLE,
    })
    db.applicants[row["id"]] = row
    return response.object_response(serializers.applicant(row), 201)


@bp.get("/licensure/applicants/<applicant_id>")
def read_applicant(applicant_id):
    user_id, role = authenticate(ALL_ROLES)
    row = lookups.applicant(applicant_id)
    lookups.require_applicant_ownership(role, user_id, row["id"])
    return response.object_response(serializers.applicant(row))


# ---------------------------------------------------------------------------
# out-of-state credentials
# ---------------------------------------------------------------------------
@bp.post("/licensure/applicants/<applicant_id>/out-of-state-credentials")
def create_credential(applicant_id):
    user_id, role = authenticate([ROLE_APPLICANT, ROLE_ADMIN])
    body = v.body()
    issuing_state = v.f_string(body, "issuing_state", pattern=v.TWO_LETTER_RE)
    license_number = v.f_string(body, "license_number")
    scope_elements = v.f_code_array(body, "scope_elements", min_items=0,
                                    max_items=12)
    practice_hours = v.f_int(body, "practice_hours", minimum=0)
    status = v.f_enum(body, "status", CREDENTIAL_STATUSES, required=False,
                      default="ACTIVE")
    verified_good_standing = v.f_bool(body, "verified_good_standing",
                                      required=False, default=False)
    issued_at = v.f_datetime(body, "issued_at")

    applicant = lookups.applicant(applicant_id)
    lookups.require_applicant_ownership(role, user_id, applicant["id"])

    row = db.make_row({
        "applicant_id": applicant["id"],
        "issuing_state": issuing_state,
        "license_number": license_number,
        "scope_elements": scope_elements,
        "practice_hours": practice_hours,
        "status": status,
        "verified_good_standing": verified_good_standing,
        "issued_at": issued_at,
    })
    db.credentials[row["id"]] = row
    return response.object_response(serializers.credential(row), 201)


@bp.get("/licensure/applicants/<applicant_id>/out-of-state-credentials")
def list_credentials(applicant_id):
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    status = response.query_enum("status", CREDENTIAL_STATUSES)
    applicant = lookups.applicant(applicant_id)
    lookups.require_applicant_ownership(role, user_id, applicant["id"])
    rows = [c for c in db.credentials.values()
            if c["applicant_id"] == applicant["id"]
            and (status is None or c["status"] == status)]
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.credential)


# ---------------------------------------------------------------------------
# military training records
# ---------------------------------------------------------------------------
@bp.post("/licensure/applicants/<applicant_id>/military-training-records")
def create_training_record(applicant_id):
    user_id, role = authenticate([ROLE_APPLICANT, ROLE_ADMIN])
    body = v.body()
    category = v.f_enum(body, "category", TRAINING_CATEGORIES)
    documented_hours = v.f_int(body, "documented_hours", minimum=1)
    source_document = v.f_string(body, "source_document")
    verified = v.f_bool(body, "verified", required=False, default=False)

    applicant = lookups.applicant(applicant_id)
    lookups.require_applicant_ownership(role, user_id, applicant["id"])

    row = db.make_row({
        "applicant_id": applicant["id"],
        "category": category,
        "documented_hours": documented_hours,
        "source_document": source_document,
        "verified": verified,
    })
    db.training_records[row["id"]] = row
    return response.object_response(serializers.training_record(row), 201)


@bp.get("/licensure/applicants/<applicant_id>/military-training-records")
def list_training_records(applicant_id):
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    applicant = lookups.applicant(applicant_id)
    lookups.require_applicant_ownership(role, user_id, applicant["id"])
    rows = [r for r in db.training_records.values()
            if r["applicant_id"] == applicant["id"]]
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.training_record)


# ---------------------------------------------------------------------------
# disciplinary history of one applicant
# ---------------------------------------------------------------------------
@bp.get("/licensure/applicants/<applicant_id>/disciplinary-records")
def list_disciplinary_records(applicant_id):
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    resolved = response.query_bool("resolved")
    applicant = lookups.applicant(applicant_id)
    lookups.require_applicant_ownership(role, user_id, applicant["id"])
    rows = [r for r in db.disciplinary_records.values()
            if r["applicant_id"] == applicant["id"]
            and (resolved is None or r["resolved"] is resolved)]
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.disciplinary_record)
