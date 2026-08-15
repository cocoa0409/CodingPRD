"""TranscriptEntry endpoints (PRD 3.8). State machine: PENDING -> POSTED -> VOIDED.

Posting and voiding both run gpa_recompute (calculation 7) for the entry's
institution against the owning student; the student's updated_at refreshes.
"""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_TRANSCRIPT_ENTRY_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calculations import gpa_recompute
from services.core import public, touch
from validate import require_path_resource

bp = Blueprint("transcript_entries", __name__)


@bp.get("/transcript-entries")
def list_transcript_entries():
    return list_response(
        "transcript_entries",
        {
            "enrollment_id": arg("enrollment_id"),
            "institution": arg("institution"),
            "status": arg("status"),
        },
    )


@bp.get("/transcript-entries/<rid>")
def get_transcript_entry(rid):
    return get_one("transcript_entries", rid)


@bp.post("/transcript-entries/<rid>/post")
def post_entry(rid):
    authorized(["CollegeRegistrar"])
    entry = require_path_resource("transcript_entries", rid)
    if entry["status"] != "PENDING":
        raise_error(
            ERR_TRANSCRIPT_ENTRY_INVALID_STATE, "only a PENDING entry can be posted"
        )
    entry["status"] = "POSTED"
    touch(entry)
    enrollment = db["enrollments"][entry["enrollment_id"]]
    gpa_recompute(enrollment["student_id"], entry["institution"])
    return success_object(public(entry))


@bp.post("/transcript-entries/<rid>/void")
def void_entry(rid):
    authorized(["CollegeRegistrar"])
    entry = require_path_resource("transcript_entries", rid)
    if entry["status"] != "POSTED":
        raise_error(ERR_TRANSCRIPT_ENTRY_INVALID_STATE, "only a POSTED entry can be voided")
    entry["status"] = "VOIDED"
    touch(entry)
    enrollment = db["enrollments"][entry["enrollment_id"]]
    # The VOIDED entry is excluded from numerator and denominator.
    gpa_recompute(enrollment["student_id"], entry["institution"])
    return success_object(public(entry))
