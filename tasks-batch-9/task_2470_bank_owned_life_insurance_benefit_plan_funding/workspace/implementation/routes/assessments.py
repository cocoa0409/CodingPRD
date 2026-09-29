"""Annual risk assessment and board reporting (PRD 3.9)."""

from flask import Blueprint

import calc
from errors import ApiError
from response import collection_response, resource_response
from store import create_record, db, touch
from validation import (
    authorize,
    find_assessment,
    find_capital_position,
    get_id,
    get_int,
    get_string,
    guard_terminal,
    guard_transition,
    json_body,
    pagination,
    query_enum,
    query_int,
    query_str,
)

bp = Blueprint("assessments", __name__)

ASSESSMENT_STATUSES = ("COMPILED", "BOARD_SUBMITTED", "BOARD_ACCEPTED", "RETURNED")
TERMINAL = ("BOARD_ACCEPTED",)
READ_ROLES = ("RiskOfficer", "BoardSecretary", "TreasuryController")


@bp.post("/risk-assessments")
def compile_assessment():
    authorize(("RiskOfficer",))
    body = json_body()
    capital_position_id = get_id(body, "capital_position_id")
    assessment_year = get_int(body, "assessment_year")

    find_capital_position(capital_position_id)
    for existing in db.risk_assessments.values():
        if int(existing["assessment_year"]) == assessment_year:
            raise ApiError("ERR_ASSESSMENT_YEAR_DUPLICATE")
    calc.tier1_capital(required=True)

    counts = calc.risk_assessment_counts()
    fields = {
        "capital_position_id": capital_position_id,
        "assessment_year": assessment_year,
        "status": "COMPILED",
        "compiled_at": db.now(),
        "board_note": None,
    }
    fields.update(counts)
    assessment = create_record(db.risk_assessments, fields)
    return resource_response(assessment, 201)


@bp.get("/risk-assessments")
def list_assessments():
    authorize(READ_ROLES)
    limit, offset = pagination()
    capital_position_id = query_str("capital_position_id")
    status = query_enum("status", ASSESSMENT_STATUSES)
    assessment_year = query_int("assessment_year")
    rows = []
    for assessment in db.risk_assessments.values():
        if (
            capital_position_id is not None
            and assessment["capital_position_id"] != capital_position_id
        ):
            continue
        if status is not None and assessment["status"] != status:
            continue
        if assessment_year is not None and int(assessment["assessment_year"]) != assessment_year:
            continue
        rows.append(assessment)
    return collection_response(rows, limit, offset)


@bp.get("/risk-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authorize(READ_ROLES)
    return resource_response(find_assessment(assessment_id))


@bp.post("/risk-assessments/<assessment_id>/submit-to-board")
def submit_to_board(assessment_id):
    authorize(("RiskOfficer",))
    assessment = find_assessment(assessment_id)
    guard_terminal(assessment["status"], TERMINAL)
    guard_transition(assessment["status"] in ("COMPILED", "RETURNED"))
    if assessment["status"] == "RETURNED":
        # a returned report is measured against the world as it now stands
        assessment.update(calc.risk_assessment_counts())
    assessment["status"] = "BOARD_SUBMITTED"
    touch(assessment)
    return resource_response(assessment)


@bp.post("/risk-assessments/<assessment_id>/accept")
def accept_assessment(assessment_id):
    authorize(("BoardSecretary",))
    body = json_body()
    board_note = get_string(body, "board_note")
    assessment = find_assessment(assessment_id)
    guard_terminal(assessment["status"], TERMINAL)
    guard_transition(assessment["status"] == "BOARD_SUBMITTED")
    assessment["status"] = "BOARD_ACCEPTED"
    assessment["board_note"] = board_note
    touch(assessment)
    return resource_response(assessment)


@bp.post("/risk-assessments/<assessment_id>/return")
def return_assessment(assessment_id):
    authorize(("BoardSecretary",))
    body = json_body()
    board_note = get_string(body, "board_note")
    assessment = find_assessment(assessment_id)
    guard_terminal(assessment["status"], TERMINAL)
    guard_transition(assessment["status"] == "BOARD_SUBMITTED")
    assessment["status"] = "RETURNED"
    assessment["board_note"] = board_note
    touch(assessment)
    return resource_response(assessment)
