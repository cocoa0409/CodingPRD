"""ChallengeParticipation endpoint (PRD §3.5)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import require_roles
from response import success
from services import serializers
from services.cascade import complete_participation, participation_progress
from services.common import (
    check_employee_scope, get_challenge_or_404, get_enrollment_or_404,
    parse_body, require_fields, stamp_new, touch,
)

bp = Blueprint("participations", __name__)


@bp.post("/wellness/challenge-participations")
@require_roles("Employee")
def join_challenge():
    body = parse_body()
    vals = require_fields(body, [
        ("challenge_id", "string", True),
        ("enrollment_id", "string", True),
    ])
    challenge = get_challenge_or_404(vals["challenge_id"])
    enr = get_enrollment_or_404(vals["enrollment_id"])
    check_employee_scope(enr)
    if enr["participation_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE",
            "Joining a challenge requires an ACTIVE enrollment",
        )
    if challenge["status"] not in ("PUBLISHED", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Challenge must be PUBLISHED or ACTIVE to join",
        )
    # duplicate-participation uniqueness (stage 8) precedes the referential
    # program-match rule (stage 10) per PRD §2.6 ordering
    if any(
        p["challenge_id"] == challenge["id"] and p["enrollment_id"] == enr["id"]
        for p in DB.participations.values()
    ):
        raise ApiError(
            "ERR_PARTICIPATION_EXISTS",
            "A participation already exists for this (challenge, enrollment)",
        )
    program = DB.programs[challenge["program_id"]]
    if program["status"] == "SETTLED":
        raise ApiError(
            "ERR_PROGRAM_ALREADY_SETTLED",
            "No new participations against a SETTLED program",
        )
    if enr["program_id"] != challenge["program_id"]:
        raise ApiError(
            "ERR_CHALLENGE_PROGRAM_MISMATCH",
            "Enrollment and challenge belong to different programs",
        )
    rec = stamp_new({
        "challenge_id": challenge["id"],
        "enrollment_id": enr["id"],
        "progress_quantity": 0,
        "status": "JOINED",
    })
    DB.participations[rec["id"]] = rec
    # backfill progress from already-accepted in-window events
    rec["progress_quantity"] = participation_progress(rec, challenge)
    touch(rec)
    if rec["progress_quantity"] >= challenge["goal_quantity"]:
        complete_participation(rec, challenge)
    return success(serializers.participation(rec), status=201)
