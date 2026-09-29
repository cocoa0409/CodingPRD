"""Substantiation dossiers: evidence, scoring and the reviewer decision (PRD 3.4)."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("substantiation_dossiers", __name__)

READ_ROLES = (
    auth.ROLE_SPECIALIST,
    auth.ROLE_REVIEWER,
    auth.ROLE_APPROVAL,
    auth.ROLE_AUDITOR,
)


@bp.route(PREFIX + "/substantiation-dossiers", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def create_dossier():
    body = validate.body()
    claim_id = validate.req_str(body, "claim_id")
    expected_version = validate.req_int(body, "expected_claim_version")
    summary = validate.req_str(body, "dossier_summary")

    claim = fk_row("claims", claim_id, errors.ERR_CLAIM_NOT_FOUND)

    if expected_version != claim["version"]:
        fail(
            errors.ERR_STALE_CLAIM_VERSION,
            "expected_claim_version %s does not match the claim's current version %s."
            % (expected_version, claim["version"]),
        )

    # Opening a dossier retires whatever draft dossier the claim already had.
    for other in cascade.dossiers_of(claim_id):
        if other["dossier_status"] != "DRAFT":
            continue
        other["dossier_status"] = "SUPERSEDED"
        db.touch(other)

    row = db.base_fields()
    row.update(
        {
            "claim_id": claim_id,
            "dossier_summary": summary,
            "authored_by_user_id": auth.user_id(),
            "dossier_status": "DRAFT",
            "evidence_studies": [],
            "study_count": 0,
            "screening_score": calc.d2(0),
            "final_score": None,
            "reviewed_by_user_id": None,
            "reviewed_at": None,
            "review_decision": None,
            "rejection_reason": None,
        }
    )
    db.insert("dossiers", row)

    # Opening a dossier is a mutation of the parent claim; that is why the guard exists.
    db.touch(claim)

    return response.object_response(serialize.dossier(row), 201)


@bp.route(PREFIX + "/substantiation-dossiers/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_dossier(row_id):
    row = path_row("dossiers", row_id, errors.ERR_DOSSIER_NOT_FOUND)
    return response.object_response(serialize.dossier(row))


@bp.route(PREFIX + "/substantiation-dossiers", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_dossiers():
    return listing("dossiers", serialize.dossier, filters=("claim_id", "dossier_status"))


@bp.route(PREFIX + "/substantiation-dossiers/<row_id>/evidence", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def append_evidence(row_id):
    row = path_row("dossiers", row_id, errors.ERR_DOSSIER_NOT_FOUND)
    body = validate.body()
    study_type = validate.req_enum(body, "study_type", calc.STUDY_TYPES)
    subject_count = validate.req_int(body, "subject_count", ge=0)
    dose_match = validate.req_bool(body, "dose_match")
    peer_reviewed = validate.req_bool(body, "peer_reviewed")
    citation = validate.req_str(body, "citation")

    if row["dossier_status"] != "DRAFT":
        fail(
            errors.ERR_DOSSIER_STATE_INVALID,
            "Evidence may only be appended to a DRAFT dossier.",
        )

    row["evidence_studies"].append(
        {
            "study_type": study_type,
            "subject_count": subject_count,
            "dose_match": dose_match,
            "peer_reviewed": peer_reviewed,
            "citation": citation,
        }
    )
    row["study_count"] += 1
    row["screening_score"] = calc.screening_score(row["evidence_studies"])
    db.touch(row)
    return response.object_response(serialize.dossier(row))


@bp.route(PREFIX + "/substantiation-dossiers/<row_id>/review", methods=["POST"])
@auth.endpoint([auth.ROLE_REVIEWER])
def review_dossier(row_id):
    row = path_row("dossiers", row_id, errors.ERR_DOSSIER_NOT_FOUND)
    body = validate.body()
    decision = validate.req_enum(body, "decision", calc.REVIEW_DECISIONS)
    rejection_reason = validate.opt_str(body, "rejection_reason")

    if row["dossier_status"] != "UNDER_REVIEW":
        fail(
            errors.ERR_DOSSIER_STATE_INVALID,
            "Only a dossier under review may receive a decision.",
        )
    if auth.user_id() == row["authored_by_user_id"]:
        fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The author of a dossier may not review its own evidence.",
        )
    if decision == "ACCEPT":
        frozen = row["final_score"]
        if frozen is None or calc.d2(frozen) < calc.ACCEPTANCE_THRESHOLD:
            fail(
                errors.ERR_SUBSTANTIATION_INSUFFICIENT,
                "The frozen final score is below the 65.00 competent-and-reliable threshold.",
            )

    row["reviewed_by_user_id"] = auth.user_id()
    row["reviewed_at"] = db.now()
    row["review_decision"] = decision

    if decision == "ACCEPT":
        row["dossier_status"] = "ACCEPTED"
        db.touch(row)
    else:
        row["dossier_status"] = "REJECTED"
        row["rejection_reason"] = rejection_reason
        db.touch(row)
        claim = db.get("claims", row["claim_id"])
        if claim is not None and claim["substantiation_status"] == "UNDER_SUBSTANTIATION_REVIEW":
            claim["substantiation_status"] = "REVISION_REQUESTED"
            db.touch(claim)

    return response.object_response(serialize.dossier(row))
