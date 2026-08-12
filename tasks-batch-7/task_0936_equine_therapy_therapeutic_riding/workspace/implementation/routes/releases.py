"""Physician releases and functional assessments (PRD §3.1, §3.2)."""

from flask import Blueprint, request

from core import timeutil as T
from core.constants import (
    ASSESSMENT_MAX_SCORE,
    ASSESSMENT_MIN_SCORE,
    ASSESSMENT_TYPES,
    INDEPENDENCE_CREW_MATRIX,
    REASSESSMENT_INTERVAL_DAYS,
    RELEASE_VALIDITY_DAYS,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, endpoint, pagination, paginate, query_enum, validate_body,
)
from core.lookups import resource_or_404, rider_or_404
from core.store import all_rows, clock, new_row, touch
from domain import derive, serialize

bp = Blueprint("releases", __name__)

RELEASE_STATUSES = ["ACTIVE", "EXPIRED", "REVOKED", "SUPERSEDED"]
ASSESSMENT_ROW_STATUSES = ["RECORDED", "SUPERSEDED"]


def _check_occ(parent, supplied):
    """Rung 44 - deliberately the last rung on the ladder."""
    if supplied != parent["version"]:
        fail("ERR_STALE_VERSION",
             "Expected version %s but the stored version is %s."
             % (supplied, parent["version"]))


# --------------------------------------------------------------- releases
@bp.post("/riders/<rider_id>/medical-releases")
@endpoint(["IntakeCoordinator", "ProgramAdmin"])
def file_release(rider_id):
    payload = validate_body([
        Field("signed_on", "date", required=True),
        Field("physician_name", "string", required=True),
        Field("cleared_condition_codes", "string_array", required=True),
        Field("expected_rider_version", "int", required=True),
    ])
    rider = rider_or_404(rider_id)
    _check_occ(rider, payload["expected_rider_version"])

    prior = derive.active_release(rider_id)
    signed_on = T.parse_date(payload["signed_on"])
    row = new_row("medical_releases")
    row.update({
        "rider_id": rider_id,
        "signed_on": payload["signed_on"],
        "physician_name": payload["physician_name"],
        "cleared_condition_codes": list(payload["cleared_condition_codes"]),
        "expires_at": T.derived(T.plus_days(T.date_to_instant(signed_on),
                                            RELEASE_VALIDITY_DAYS)),
        "revoked_at": None,
        "superseded_at": None,
    })
    if prior is not None:
        prior["superseded_at"] = clock.stamp()
        touch(prior)
    touch(rider)
    return object_response(serialize.medical_release(row), 201)


@bp.get("/medical-releases")
@endpoint(["IntakeCoordinator", "ProgramAdmin", "Instructor"])
def list_releases():
    limit, offset = pagination()
    status = query_enum("status", RELEASE_STATUSES)
    rider_id = request.args.get("rider_id")
    rows = all_rows("medical_releases")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    if status is not None:
        rows = [r for r in rows if derive.release_status(r) == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.medical_release(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/medical-releases/<release_id>")
@endpoint(["IntakeCoordinator", "ProgramAdmin", "Instructor"])
def read_release(release_id):
    row = resource_or_404("medical_releases", release_id)
    return object_response(serialize.medical_release(row))


@bp.post("/medical-releases/<release_id>/revoke")
@endpoint(["ProgramAdmin"])
def revoke_release(release_id):
    validate_body([Field("reason", "string", required=True)])
    row = resource_or_404("medical_releases", release_id)
    if derive.release_status(row) != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE release may be revoked.")
    row["revoked_at"] = clock.stamp()
    touch(row)
    return object_response(serialize.medical_release(row))


# ------------------------------------------------------------ assessments
def _independence_level(combined_score):
    if combined_score >= 17:
        return "LEVEL_4"
    if combined_score >= 12:
        return "LEVEL_3"
    if combined_score >= 7:
        return "LEVEL_2"
    return "LEVEL_1"


@bp.post("/riders/<rider_id>/assessments")
@endpoint(["Instructor", "ProgramAdmin"])
def file_assessment(rider_id):
    payload = validate_body([
        Field("assessment_type", "enum", required=True, members=ASSESSMENT_TYPES),
        Field("performed_on", "date", required=True),
        Field("balance_score", "int", required=True,
              minimum=ASSESSMENT_MIN_SCORE, maximum=ASSESSMENT_MAX_SCORE),
        Field("trunk_control_score", "int", required=True,
              minimum=ASSESSMENT_MIN_SCORE, maximum=ASSESSMENT_MAX_SCORE),
        # Rung 7 declares no numeric bound on rider_weight_lb, so none is invented.
        Field("rider_weight_lb", "number", required=True),
        Field("backriding_required", "bool", required=True),
        Field("expected_rider_version", "int", required=True),
    ])
    rider = rider_or_404(rider_id)
    _check_occ(rider, payload["expected_rider_version"])

    prior = derive.recorded_assessment(rider_id)
    combined = payload["balance_score"] + payload["trunk_control_score"]
    level = _independence_level(combined)
    crew = INDEPENDENCE_CREW_MATRIX[level]
    performed_on = T.parse_date(payload["performed_on"])
    next_due = T.derived(T.plus_days(T.date_to_instant(performed_on),
                                     REASSESSMENT_INTERVAL_DAYS))

    row = new_row("assessments")
    row.update({
        "rider_id": rider_id,
        "assessment_type": payload["assessment_type"],
        "performed_on": payload["performed_on"],
        "balance_score": payload["balance_score"],
        "trunk_control_score": payload["trunk_control_score"],
        "rider_weight_lb": payload["rider_weight_lb"],
        "backriding_required": payload["backriding_required"],
        "combined_score": combined,
        "independence_level": level,
        "required_sidewalker_count": crew["required_sidewalker_count"],
        "requires_leader": crew["requires_leader"],
        "sidewalker_hold_type": crew["sidewalker_hold_type"],
        "next_due_at": next_due,
        "status": "RECORDED",
    })
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    rider["independence_level"] = level
    rider["required_sidewalker_count"] = crew["required_sidewalker_count"]
    rider["requires_leader"] = crew["requires_leader"]
    rider["sidewalker_hold_type"] = crew["sidewalker_hold_type"]
    rider["backriding_required"] = payload["backriding_required"]
    rider["assessment_next_due_at"] = next_due
    touch(rider)
    return object_response(serialize.assessment(row), 201)


@bp.get("/assessments")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def list_assessments():
    limit, offset = pagination()
    status = query_enum("status", ASSESSMENT_ROW_STATUSES)
    rider_id = request.args.get("rider_id")
    rows = all_rows("assessments")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.assessment(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/assessments/<assessment_id>")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def read_assessment(assessment_id):
    row = resource_or_404("assessments", assessment_id)
    return object_response(serialize.assessment(row))
