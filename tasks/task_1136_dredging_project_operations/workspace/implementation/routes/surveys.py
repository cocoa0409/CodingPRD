"""Survey endpoints (PRD 3.4): kind gate, acceptance cascade with reach-level
OCC, segregation of duties, supersede chains, removed-quantity identity."""
import uuid

from flask import Blueprint, g

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_REACH_VERSION,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SURVEY_KIND_MISMATCH,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_survey, recompute_removed
from util import (
    as_enum,
    as_int,
    as_num,
    as_str,
    check,
    get_body,
    new_entity,
    req_present,
    touch,
)

bp = Blueprint("surveys", __name__)


@bp.post("/surveys")
@require_roles("SurveyParty")
def create_survey():
    body = get_body()
    # Existence (class 3): reach_id, then the optional self-referential FK.
    reach_id = body.get("reach_id")
    if reach_id is not None and reach_id not in store.reaches:
        raise ApiError(ERR_NOT_FOUND, "Reach not found", 404)
    supersedes = body.get("supersedes_survey_id")
    if supersedes is not None and supersedes not in store.surveys:
        raise ApiError(ERR_NOT_FOUND, "supersedes_survey_id does not reference a Survey", 404)
    # Shape (class 5).
    reach_id = as_str(req_present(body, "reach_id"), "reach_id")
    kind = as_enum(req_present(body, "kind"), "kind", ["PRE_DREDGE", "POST_DREDGE"])
    measured = as_int(req_present(body, "measured_volume_cy"), "measured_volume_cy")
    check(measured >= 0, "measured_volume_cy must be >= 0")
    min_depth = as_num(req_present(body, "min_sounding_depth_ft"), "min_sounding_depth_ft")
    check(min_depth > 0, "min_sounding_depth_ft must be > 0")
    if supersedes is not None:
        supersedes = as_str(supersedes, "supersedes_survey_id")
    reach = store.reaches[reach_id]
    # State gate (class 6): strict kind gate.
    if kind == "PRE_DREDGE" and reach["status"] not in ("PENDING", "PRE_SURVEYED"):
        raise ApiError(
            ERR_SURVEY_KIND_MISMATCH,
            "PRE_DREDGE survey requires reach PENDING or PRE_SURVEYED",
            409,
        )
    if kind == "POST_DREDGE" and reach["status"] != "DREDGING":
        raise ApiError(
            ERR_SURVEY_KIND_MISMATCH, "POST_DREDGE survey requires reach DREDGING", 409
        )
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "reach_id": reach_id,
            "kind": kind,
            "measured_volume_cy": measured,
            "min_sounding_depth_ft": min_depth,
            "supersedes_survey_id": supersedes,
            "submitted_by_user_id": g.user_id,
            "status": "SUBMITTED",
        }
    )
    store.surveys[rec["id"]] = rec
    if kind == "POST_DREDGE":
        # Creating a post-dredge survey pauses dredging pending adjudication.
        reach["status"] = "POST_SURVEY_SUBMITTED"
        touch(reach)
    return ok(serialize_survey(rec), 201)


def _get_survey(sid):
    survey = store.surveys.get(sid)
    if survey is None:
        raise ApiError(ERR_NOT_FOUND, "Survey not found", 404)
    return survey


@bp.get("/surveys/<sid>")
@require_roles(*ALL_ROLES)
def get_survey(sid):
    return ok(serialize_survey(_get_survey(sid)))


@bp.get("/surveys")
@require_roles(*ALL_ROLES)
def list_surveys():
    return list_response(
        store.surveys, serialize_survey, ["reach_id", "kind", "status", "supersedes_survey_id"]
    )


@bp.post("/surveys/<sid>/accept")
@require_roles("OwnerEngineer")
def accept_survey(sid):
    survey = _get_survey(sid)
    reach = store.reaches[survey["reach_id"]]
    body = get_body()
    # Class 4 (OCC) precedes segregation (class 8) per PRD 2.9.
    erv = body.get("expected_reach_version")
    if erv is not None and isinstance(erv, int) and not isinstance(erv, bool):
        if erv != reach["version"]:
            raise ApiError(
                ERR_STALE_REACH_VERSION,
                "expected_reach_version %s does not match current Reach.version %s"
                % (erv, reach["version"]),
                412,
            )
    # Class 5 (shape): the OCC field is required.
    if erv is None or isinstance(erv, bool) or not isinstance(erv, int):
        raise ApiError(
            ERR_INVALID_REQUEST, "expected_reach_version is required and must be an integer", 400
        )
    # Class 6 (state).
    if survey["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED survey can be accepted", 409)
    # Class 8 (segregation of duties).
    if g.user_id == survey["submitted_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "The survey submitter cannot accept it", 403
        )
    survey["status"] = "ACCEPTED"
    touch(survey)
    # Explicit supersede: the referenced survey (same reach+kind, ACCEPTED).
    ref_id = survey["supersedes_survey_id"]
    if ref_id:
        ref = store.surveys.get(ref_id)
        if (
            ref is not None
            and ref["reach_id"] == survey["reach_id"]
            and ref["kind"] == survey["kind"]
            and ref["status"] == "ACCEPTED"
        ):
            ref["status"] = "SUPERSEDED"
            touch(ref)
    # Any other ACCEPTED survey of the same reach+kind is a prior acceptance and
    # becomes SUPERSEDED (only one latest ACCEPTED per kind exists).
    for other in store.surveys.values():
        if (
            other["id"] != survey["id"]
            and other["reach_id"] == survey["reach_id"]
            and other["kind"] == survey["kind"]
            and other["status"] == "ACCEPTED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    # Reach transition by kind.
    if survey["kind"] == "PRE_DREDGE":
        if reach["status"] == "PENDING":
            reach["status"] = "PRE_SURVEYED"
        # On PRE_SURVEYED the reach stays PRE_SURVEYED.
    else:  # POST_DREDGE
        if survey["min_sounding_depth_ft"] >= reach["required_depth_ft"]:
            reach["status"] = "ACCEPTED"  # equality passes
        else:
            reach["status"] = "DREDGING"  # deficiency loop
    recompute_removed(reach)
    touch(reach)
    return ok(serialize_survey(survey))


@bp.post("/surveys/<sid>/reject")
@require_roles("OwnerEngineer")
def reject_survey(sid):
    survey = _get_survey(sid)
    if survey["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED survey can be rejected", 409)
    if g.user_id == survey["submitted_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "The survey submitter cannot reject it", 403
        )
    survey["status"] = "REJECTED"
    touch(survey)
    if survey["kind"] == "POST_DREDGE":
        # A rejected post-dredge survey returns the reach to DREDGING.
        reach = store.reaches[survey["reach_id"]]
        if reach["status"] == "POST_SURVEY_SUBMITTED":
            reach["status"] = "DREDGING"
            touch(reach)
    return ok(serialize_survey(survey))
