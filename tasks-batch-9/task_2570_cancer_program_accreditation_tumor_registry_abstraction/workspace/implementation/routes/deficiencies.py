"""Standard deficiency citation, corrective-action response and escalation."""

from flask import Blueprint

import db
import services
import spec
import validate
from db import add_days, all_of, clock_date, fmt_date, mark, parse_date
from errors import ApiError, invalid
from middleware import ANY_ROLE, actor, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("deficiencies", __name__)


@bp.post(PREFIX + "/deficiencies")
@endpoint(["CoCSurveyor"])
def cite_deficiency():
    body = validate.body()
    program_id = validate.f_str(body, "program_id")
    standard_code = validate.f_str(body, "standard_code")
    severity = validate.f_enum(body, "severity", spec.SEVERITIES)
    cited_on = validate.f_date(body, "cited_on")
    evidence_reference = validate.f_str(body, "evidence_reference",
                                        required=False)
    source_measure_id = validate.f_str(body, "source_measure_id",
                                       required=False)
    if cited_on > clock_date():
        raise invalid("cited_on may not be later than the logical clock date.")

    program = need("program", program_id, "ERR_PROGRAM_NOT_FOUND")
    if source_measure_id is not None:
        need("measure", source_measure_id, "ERR_MEASURE_NOT_FOUND")

    deficiency = services.cite_deficiency(
        program, standard_code, severity, cited_on,
        evidence_reference=evidence_reference,
        source_measure_id=source_measure_id)
    return ok(deficiency, 201)


@bp.get(PREFIX + "/deficiencies")
@endpoint(ANY_ROLE)
def list_deficiencies():
    program_id = validate.q_str("program_id")
    source_measure_id = validate.q_str("source_measure_id")
    severity = validate.q_enum("severity", spec.SEVERITIES)
    deficiency_state = validate.q_enum("deficiency_state",
                                       spec.DEFICIENCY_STATES)
    items = all_of("deficiency")
    if program_id is not None:
        items = [d for d in items if d["program_id"] == program_id]
    if source_measure_id is not None:
        items = [d for d in items
                 if d["source_measure_id"] == source_measure_id]
    if severity is not None:
        items = [d for d in items if d["severity"] == severity]
    if deficiency_state is not None:
        items = [d for d in items if d["deficiency_state"] == deficiency_state]
    return page(items)


@bp.get(PREFIX + "/deficiencies/<deficiency_id>")
@endpoint(ANY_ROLE)
def read_deficiency(deficiency_id):
    deficiency = need("deficiency", deficiency_id, "ERR_DEFICIENCY_NOT_FOUND")
    return ok(deficiency)


@bp.post(PREFIX + "/deficiencies/<deficiency_id>/response")
@endpoint(["AccreditationCoordinator"])
def file_response(deficiency_id):
    body = validate.body()
    response_narrative = validate.f_str(body, "response_narrative")
    evidence_reference = validate.f_str(body, "evidence_reference",
                                        required=False)

    deficiency = need("deficiency", deficiency_id, "ERR_DEFICIENCY_NOT_FOUND")
    if deficiency["deficiency_state"] not in ("CITED", "RESPONSE_REJECTED"):
        raise ApiError("ERR_DEFICIENCY_NOT_RESPONDABLE")
    due = parse_date(deficiency["response_due_date"])
    if due is not None and clock_date() > due:
        raise ApiError("ERR_DEFICIENCY_RESPONSE_WINDOW_CLOSED")

    mark(deficiency)
    deficiency["response_narrative"] = response_narrative
    if evidence_reference is not None:
        deficiency["evidence_reference"] = evidence_reference
    deficiency["deficiency_state"] = "RESPONSE_SUBMITTED"
    deficiency["_responded_by_user_id"] = actor()
    return ok(deficiency)


@bp.post(PREFIX + "/deficiencies/<deficiency_id>/response-review")
@endpoint(["CoCSurveyor"])
def review_response(deficiency_id):
    body = validate.body()
    outcome = validate.f_enum(body, "outcome", ("ACCEPTED", "REJECTED"))
    reviewer_notes = validate.f_str(body, "reviewer_notes", required=False)

    deficiency = need("deficiency", deficiency_id, "ERR_DEFICIENCY_NOT_FOUND")
    if deficiency["deficiency_state"] != "RESPONSE_SUBMITTED":
        raise ApiError("ERR_DEFICIENCY_NOT_UNDER_REVIEW")
    if actor() == deficiency.get("_responded_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    program = db.get("program", deficiency["program_id"])

    mark(deficiency)
    if reviewer_notes is not None:
        deficiency["reviewer_notes"] = reviewer_notes

    if outcome == "ACCEPTED":
        deficiency["deficiency_state"] = "RESOLVED"
        if program is not None:
            services.refresh_program_aggregates(program)
        return ok(deficiency)

    if deficiency["escalation_count"] + 1 >= spec.DEFICIENCY_ESCALATION_MAX:
        services.escalate_deficiency(deficiency)
        return ok(deficiency)

    deficiency["escalation_count"] = deficiency["escalation_count"] + 1
    due = parse_date(deficiency["response_due_date"])
    if due is not None:
        deficiency["response_due_date"] = fmt_date(
            add_days(due, spec.RESPONSE_WINDOW_EXTENSION_DAYS))
    deficiency["deficiency_state"] = "RESPONSE_REJECTED"
    return ok(deficiency)
