"""Pre-match communication logging and compliance adjudication."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import FACULTY_ROLES, acting_id, acting_role, endpoint
from envelope import object_response
from errors import ApiError
from store import insert, must_find, new_row, now_iso, rows, touch
from validators import body, fk, q_enum, q_str, req_enum, req_str
from routes.common import keep, listing

bp = Blueprint("comms", __name__)

CHANNELS = ("EMAIL", "PHONE", "IN_PERSON")
COMPLIANCE_STATUSES = ("CLEAN", "FLAGGED", "CLEARED")


@bp.post("/communication-logs")
@endpoint("ProgramDirector", "ProgramCoordinator", "Interviewer", "CommitteeMember")
def create_log():
    payload = body()
    application = fk(payload, "application_id", "applications")
    author = fk(payload, "author_faculty_id", "faculty_members")
    if application is None:
        req_str(payload, "application_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    channel = req_enum(payload, "channel", CHANNELS)
    text = req_str(payload, "body", max_len=2000)

    author_id = author["id"] if author is not None else None
    if author_id is None and acting_role() in FACULTY_ROLES:
        author_id = acting_id()

    program = helpers.program_of_application(application)
    contains, status = calc.compliance_scan(text, program)

    row = new_row(
        application_id=application["id"],
        author_faculty_id=author_id,
        channel=channel,
        body=text,
        contains_ranking_intent=contains,
        compliance_status=status,
        sent_at=now_iso(),
        resolution_note=None,
    )
    insert("communication_logs", row)
    return object_response(serializers.communication_log(row), 201)


@bp.get("/communication-logs")
@endpoint("ProgramDirector", "ProgramCoordinator", "ComplianceOfficer", "NrmpAdmin")
def list_logs():
    items = rows("communication_logs")
    items = keep(items, "application_id", q_str("application_id"))
    items = keep(items, "author_faculty_id", q_str("author_faculty_id"))
    items = keep(items, "channel", q_enum("channel", CHANNELS))
    items = keep(items, "compliance_status", q_enum("compliance_status", COMPLIANCE_STATUSES))
    return listing(items, serializers.communication_log)


@bp.get("/communication-logs/<log_id>")
@endpoint("ProgramDirector", "ProgramCoordinator", "ComplianceOfficer", "NrmpAdmin")
def read_log(log_id):
    return object_response(
        serializers.communication_log(must_find("communication_logs", log_id))
    )


@bp.post("/communication-logs/<log_id>/resolve")
@endpoint("ComplianceOfficer")
def resolve_log(log_id):
    log = must_find("communication_logs", log_id)
    payload = body()
    note = req_str(payload, "resolution_note", max_len=2000)

    helpers.require_state(log, "compliance_status", ("FLAGGED",))

    log["compliance_status"] = "CLEARED"
    log["resolution_note"] = note
    touch(log)
    return object_response(serializers.communication_log(log))
