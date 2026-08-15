"""Script version lifecycle endpoints."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import lookup, ser_script, touch
from util import body, req_enum, req_int

bp = Blueprint("scripts", __name__)

DECISIONS = ("APPROVE", "REQUEST_REVISION", "REJECT")


@bp.get("/script-versions/<sid>")
def get_script(sid):
    auth(ALL_ROLES)
    return ok(ser_script(lookup("scripts", sid)))


@bp.post("/script-versions/<sid>/submit")
def submit_script(sid):
    auth(["Curator"])
    script = lookup("scripts", sid)
    if script["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DRAFT script can be submitted"
        )
    script["status"] = "IN_REVIEW"
    touch(script)
    return ok(ser_script(script))


@bp.post("/script-versions/<sid>/review")
def review_script(sid):
    auth(["Curator"])
    script = lookup("scripts", sid)
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    score_raw = data.get("accuracy_score")
    if score_raw is not None and (
        not isinstance(score_raw, int)
        or isinstance(score_raw, bool)
        or score_raw < 0
        or score_raw > 100
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "accuracy_score must be an integer 0-100"
        )
    notes = data.get("reviewer_notes")
    if notes is not None and not isinstance(notes, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "reviewer_notes must be a string")
    if script["status"] != "IN_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an IN_REVIEW script can be reviewed"
        )
    if decision == "APPROVE":
        # PRD 3.2: a missing score is rejected with ERR_REVIEW_SCORE_TOO_LOW.
        if score_raw is None or score_raw < 80:
            raise ApiError(
                "ERR_REVIEW_SCORE_TOO_LOW",
                422,
                "APPROVE requires accuracy_score >= 80",
            )
        script["accuracy_score"] = score_raw
        script["reviewer_notes"] = notes
        script["status"] = "APPROVED"
    elif decision == "REQUEST_REVISION":
        script["status"] = "DRAFT"
    else:  # REJECT
        script["status"] = "REJECTED"
    touch(script)
    return ok(ser_script(script))


@bp.post("/script-versions/<sid>/publish")
def publish_script(sid):
    auth(["MuseumAdmin"])
    script = lookup("scripts", sid)
    data = body()
    expected = req_int(data, "expected_route_version")
    if script["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an APPROVED script can be published"
        )
    route = lookup("routes", script["route_id"])
    if expected != route["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_route_version does not match the route's current version",
        )
    for other in DB["scripts"].values():
        if (
            other["route_id"] == route["id"]
            and other["id"] != script["id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    script["status"] = "PUBLISHED"
    touch(script)
    route["published_script_id"] = script["id"]
    touch(route)
    return ok(ser_script(script))
