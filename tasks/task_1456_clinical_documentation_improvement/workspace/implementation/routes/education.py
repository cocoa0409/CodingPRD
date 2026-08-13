"""Provider education event endpoints (manual recording + listing)."""
from flask import Blueprint, request

import db
from calc import record_education
from errors import raise_error
from helpers import body_ref, list_page, require_program_active
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_enum,
    validate_int_range,
)
from response import success_list, success_object
from serializers import education_event_out

bp = Blueprint("education", __name__)

WRITE_ROLES = {"CDIManager", "CDISpecialist"}
READ_ROLES = {"CDIManager", "CDISpecialist", "ComplianceAuditor"}
PATTERN_TAGS = {
    "LEADING_LANGUAGE",
    "NO_RESPONSE_PATTERN",
    "CLINICALLY_UNSUPPORTED_PATTERN",
    "OVERDUE_PATTERN",
}


@bp.route("/api/provider-education-events", methods=["POST"])
def create_education_event():
    require_roles(WRITE_ROLES)
    body = get_json_body()
    check_known_fields(body, {
        "provider_id", "pattern_tag", "points_deducted", "source_query_id", "note",
    })
    require_fields(body, [
        "provider_id", "pattern_tag", "points_deducted", "source_query_id", "note",
    ])
    provider = body_ref(body, "provider_id", db.providers, "provider")
    pattern_tag = validate_enum(body["pattern_tag"], PATTERN_TAGS, "pattern_tag")
    points = validate_int_range(body["points_deducted"], "points_deducted", 1, 25)
    source_query_id = body["source_query_id"]
    if not isinstance(source_query_id, str) or not source_query_id:
        raise_error(
            "ERR_INVALID_REQUEST",
            "source_query_id is required and must be a string",
        )
    note = body["note"]
    if not isinstance(note, str):
        raise_error("ERR_INVALID_REQUEST", "note must be a string")
    program = db.programs.get(provider["cdi_program_id"])
    require_program_active(program)
    query = db.queries.get(source_query_id)
    if query is None or query["cdi_program_id"] != provider["cdi_program_id"]:
        raise_error(
            "ERR_INVALID_REQUEST",
            "source_query_id does not reference a query within the program",
        )
    event = record_education(provider, pattern_tag, points, source_query_id, note)
    return success_object(education_event_out(event), status=201)


@bp.route("/api/provider-education-events", methods=["GET"])
def list_education_events():
    require_roles(READ_ROLES)
    provider_id = request.args.get("provider_id")
    program_id = request.args.get("cdi_program_id")
    pattern_tag = request.args.get("pattern_tag")
    items = list(db.education_events.values())
    if provider_id is not None:
        items = [e for e in items if e["provider_id"] == provider_id]
    if program_id is not None:
        items = [e for e in items if e["cdi_program_id"] == program_id]
    if pattern_tag is not None:
        items = [e for e in items if e["pattern_tag"] == pattern_tag]
    page, limit, offset, total = list_page(items)
    return success_list([education_event_out(e) for e in page], limit, offset, total)
