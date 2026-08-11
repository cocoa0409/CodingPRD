from flask import Blueprint, g, request

import constants as C
import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import (agency_of_ori, body_row, check_billing_freeze, check_parent_version,
                     check_segregation, path_row, require_record_state)
from store import db
from timeutil import add_days

bp = Blueprint("determinations", __name__)


@bp.post("/livescan/fitness-determinations")
def issue_determination():
    data = V.body()
    submission = (
        body_row("submissions", data["submission_id"]) if data.get("submission_id") else None
    )
    outcome = V.req_string(data, "outcome")
    expected_submission_version = V.req_int(data, "expected_submission_version")
    if submission is None:
        V.bad_request("submission_id is required")
    V.enum_value("outcome", outcome, C.OUTCOMES)

    ori = db.oris[submission["ori_id"]]
    check_billing_freeze(agency_of_ori(ori))
    check_parent_version(submission, expected_submission_version)

    basis = None
    for response in db.chr_responses.values():
        if response["submission_id"] != submission["id"]:
            continue
        if response["destination"] != "STATE" or response["routing_status"] != "ROUTED":
            continue
        basis = response
        break

    row = db.create(
        "determinations",
        {
            "submission_id": submission["id"],
            "ori_id": submission["ori_id"],
            "basis_response_id": basis["id"] if basis else None,
            "outcome": outcome,
            "issued_by_user_id": g.user_id,
            "resolved_by_user_id": None,
            "status": "ISSUED",
            "challenge_count": 0,
            "challenge_filed_at": None,
            "issued_at": db.now(),
        },
    )
    db.touch(submission)
    return object_response(serializers.determination(row), 201)


@bp.get("/livescan/fitness-determinations/<id>")
def read_determination(id):
    return object_response(serializers.determination(path_row("determinations", id)))


@bp.get("/livescan/fitness-determinations")
def list_determinations():
    rows = list(db.determinations.values())
    for field in ("submission_id", "ori_id", "basis_response_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(rows, serializers.determination)


@bp.post("/livescan/fitness-determinations/<id>/challenges")
def file_challenge(id):
    determination = path_row("determinations", id)
    data = V.body()
    V.req_string(data, "grounds")

    require_record_state(
        determination["status"] in ("ISSUED", "REAFFIRMED"),
        "determination is %s" % determination["status"],
    )
    if db.now() > add_days(determination["issued_at"], C.CHALLENGE_FILING_WINDOW_DAYS):
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED", "the 21-day challenge window has closed")
    if determination["challenge_count"] >= C.CHALLENGE_MAX_CYCLES:
        raise ApiError("ERR_CHALLENGE_LIMIT_REACHED", "two challenges have already been filed")

    determination["status"] = "CHALLENGED"
    determination["challenge_count"] += 1
    determination["challenge_filed_at"] = db.now()
    db.touch(determination)
    return object_response(serializers.determination(determination))


@bp.post("/livescan/fitness-determinations/<id>/challenge-resolutions")
def resolve_challenge(id):
    determination = path_row("determinations", id)
    data = V.body()
    resolution = V.req_string(data, "resolution")
    if resolution == "AMEND" and not V.present(data, "amended_outcome"):
        V.bad_request("amended_outcome is required when the resolution is AMEND")
    amended_outcome = V.opt_string(data, "amended_outcome")
    V.enum_value("resolution", resolution, C.RESOLUTIONS)
    if amended_outcome is not None:
        V.enum_value("amended_outcome", amended_outcome, C.OUTCOMES)

    require_record_state(
        determination["status"] == "CHALLENGED", "determination is %s" % determination["status"]
    )
    check_segregation(determination["issued_by_user_id"])

    if resolution == "REAFFIRM":
        determination["status"] = "REAFFIRMED"
        determination["challenge_filed_at"] = None
    else:
        determination["status"] = "AMENDED"
        determination["outcome"] = amended_outcome
    determination["resolved_by_user_id"] = g.user_id
    db.touch(determination)
    return object_response(serializers.determination(determination))
