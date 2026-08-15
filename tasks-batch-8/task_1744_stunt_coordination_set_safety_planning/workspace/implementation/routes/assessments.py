"""RiskAssessment: create (OCC), submit, approve, reject, revise."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_assessment,
    gate_posture_setup_or_active,
    screening_score_of,
    screening_band,
    board_score_of,
    serialize_assessment,
    stamp_new,
    stamp_mutable,
    touch,
    default_sort_key,
)
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_VERSION,
    ERR_SEQUENCE_INVALID_STATE,
    ERR_ASSESSMENT_INVALID_STATE,
    ERR_CATEGORY_SCORE_MISMATCH,
    ERR_CROSS_PRODUCTION_REFERENCE,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_nonempty_string,
    v_int,
    v_rating,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("assessments", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
COORD = ["StuntCoordinator"]
SAFETY = ["SafetyOfficer"]

LOCKED_OUT_SEQUENCE_STATES = ("EXECUTED", "REVIEWED", "CANCELLED")


@bp.post("/api/risk-assessments")
def create_assessment():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "sequence_id": (v_string, True, None),
            "severity_rating": (v_rating, True, None),
            "likelihood_rating": (v_rating, True, None),
            "mitigation_notes": (v_string, False, ""),
            "expected_sequence_version": (v_int, True, None),
        },
    )
    user_id, role = auth()
    require_role(role, COORD)

    get_production(data["production_id"])
    seq = get_sequence(data["sequence_id"])

    # OCC (tier 4) precedes the posture gate (tier 5)
    if data["expected_sequence_version"] != seq["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_sequence_version does not match the sequence's current "
                  "version", 412)

    prod = get_production(seq["production_id"])
    gate_posture_setup_or_active(prod)

    if seq["status"] in LOCKED_OUT_SEQUENCE_STATES:
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "Cannot create an assessment against an EXECUTED, REVIEWED, or "
                  "CANCELLED sequence", 409)

    if seq["production_id"] != data["production_id"]:
        raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                  "production_id must equal the sequence's production", 422)

    assessment = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": data["production_id"],
                "sequence_id": seq["id"],
                "assessor_user_id": user_id,
                "severity_rating": data["severity_rating"],
                "likelihood_rating": data["likelihood_rating"],
                "mitigation_notes": data["mitigation_notes"],
                "screening_score": screening_score_of(
                    data["severity_rating"], data["likelihood_rating"]
                ),
                "status": "DRAFT",
                "supersedes_assessment_id": None,
                "rejection_reason": None,
            }
        )
    )
    store.assessments[assessment["id"]] = assessment
    touch(seq)  # assessment creation advances the sequence version
    return ok(serialize_assessment(assessment), 201)


@bp.get("/api/risk-assessments")
def list_assessments():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    sequence_id = request.args.get("sequence_id")
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_assessment_id")
    items = []
    for a in store.assessments.values():
        if production_id is not None and a["production_id"] != production_id:
            continue
        if sequence_id is not None and a["sequence_id"] != sequence_id:
            continue
        if status is not None and a["status"] != status:
            continue
        if supersedes is not None and a["supersedes_assessment_id"] != supersedes:
            continue
        items.append(a)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_assessment(a) for a in page], total, limit, offset)


@bp.get("/api/risk-assessments/<aid>")
def get_one_assessment(aid):
    _, role = auth()
    require_role(role, READ_ROLES)
    assessment = get_assessment(aid)
    return ok(serialize_assessment(assessment), 200)


@bp.post("/api/risk-assessments/<aid>/submit")
def submit_assessment(aid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, COORD)
    assessment = get_assessment(aid)
    if user_id != assessment["assessor_user_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "Only the assessment's author may submit it", 403)
    prod = get_production(assessment["production_id"])
    gate_posture_setup_or_active(prod)
    if assessment["status"] != "DRAFT":
        raise err(ERR_ASSESSMENT_INVALID_STATE, "submit requires status DRAFT", 409)
    seq = get_sequence(assessment["sequence_id"])
    if seq["status"] in LOCKED_OUT_SEQUENCE_STATES:
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "The sequence no longer accepts assessment submissions", 409)
    if screening_band(assessment["screening_score"]) != seq["risk_category"]:
        raise err(ERR_CATEGORY_SCORE_MISMATCH,
                  "Screening band does not equal the sequence's declared "
                  "risk_category", 422)
    assessment["status"] = "SUBMITTED"
    touch(assessment)
    return ok(serialize_assessment(assessment), 200)


@bp.post("/api/risk-assessments/<aid>/approve")
def approve_assessment(aid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, SAFETY)
    assessment = get_assessment(aid)
    prod = get_production(assessment["production_id"])
    gate_posture_setup_or_active(prod)
    if assessment["status"] != "SUBMITTED":
        raise err(ERR_ASSESSMENT_INVALID_STATE, "approve requires status SUBMITTED", 409)
    if user_id == assessment["assessor_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "The assessment's author may not approve it", 403)

    seq = get_sequence(assessment["sequence_id"])
    # supersede the previously APPROVED assessment of this sequence, if any
    priors = [
        a for a in store.assessments.values()
        if a["sequence_id"] == seq["id"]
        and a["status"] == "APPROVED"
        and a["id"] != assessment["id"]
    ]
    priors.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for prior in priors:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    assessment["supersedes_assessment_id"] = priors[-1]["id"] if priors else None
    assessment["status"] = "APPROVED"
    touch(assessment)

    # re-pin and recompute the board score; readiness invalidated
    seq["current_assessment_id"] = assessment["id"]
    seq["board_score"] = board_score_of(assessment, seq["hazard_class"])
    if seq["status"] in ("READY", "SAFETY_HOLD"):
        seq["status"] = "SAFETY_HOLD"
    touch(seq)
    return ok(serialize_assessment(assessment), 200)


@bp.post("/api/risk-assessments/<aid>/reject")
def reject_assessment(aid):
    body = get_body()
    data = validate_payload(body, {"reason": (v_nonempty_string, True, None)})
    _, role = auth()
    require_role(role, SAFETY)
    assessment = get_assessment(aid)
    prod = get_production(assessment["production_id"])
    gate_posture_setup_or_active(prod)
    if assessment["status"] != "SUBMITTED":
        raise err(ERR_ASSESSMENT_INVALID_STATE, "reject requires status SUBMITTED", 409)
    assessment["status"] = "REJECTED"
    assessment["rejection_reason"] = data["reason"]
    touch(assessment)
    return ok(serialize_assessment(assessment), 200)


@bp.post("/api/risk-assessments/<aid>/revise")
def revise_assessment(aid):
    body = get_body()
    data = validate_payload(
        body,
        {
            "severity_rating": (v_rating, True, None),
            "likelihood_rating": (v_rating, True, None),
            "mitigation_notes": (v_string, False, ""),
        },
    )
    user_id, role = auth()
    require_role(role, COORD)
    assessment = get_assessment(aid)
    if user_id != assessment["assessor_user_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "Only the assessment's author may revise it", 403)
    prod = get_production(assessment["production_id"])
    gate_posture_setup_or_active(prod)
    if assessment["status"] != "REJECTED":
        raise err(ERR_ASSESSMENT_INVALID_STATE, "revise requires status REJECTED", 409)
    assessment["severity_rating"] = data["severity_rating"]
    assessment["likelihood_rating"] = data["likelihood_rating"]
    assessment["mitigation_notes"] = data["mitigation_notes"]
    assessment["screening_score"] = screening_score_of(
        data["severity_rating"], data["likelihood_rating"]
    )
    assessment["rejection_reason"] = None
    assessment["status"] = "DRAFT"
    touch(assessment)
    return ok(serialize_assessment(assessment), 200)
