"""DisciplinaryCase endpoints: due process, sanction and revocation (PRD 3.12)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CERTIFICANT,
    ROLE_ETHICS_OFFICER,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    opt_str,
    peek_body,
    present,
    req_enum,
    req_int,
    req_str,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import cascades, derive, lookup
from util import add_months

bp = Blueprint("discipline", __name__)

ALLEGATION_TYPES = ("CREDENTIAL_MISUSE", "EXAM_MISCONDUCT", "CEU_FALSIFICATION",
                    "ETHICS_VIOLATION")
DECISION_OUTCOMES = ("DISMISSED", "SANCTIONED", "REVOKED")


@bp.post("/disciplinary-cases")
@api
def open_case():
    actor = authenticate([ROLE_ETHICS_OFFICER])
    raw = peek_body()

    # Layer 4: the respondent resolves before the body is validated.
    certificant = lookup.certificant((raw or {}).get("certificant_id"))

    body = ensure_body(raw)
    allegation_type = req_enum(body, "allegation_type", ALLEGATION_TYPES)
    description = req_str(body, "description")

    # Layer 17.
    if certificant["status"] == "REVOKED":
        raise ApiError("ERR_CERTIFICANT_ALREADY_REVOKED")

    case = new_record(
        certificant_id=certificant["id"],
        allegation_type=allegation_type,
        description=description,
        status="OPENED",
        response_round=0,
        response_text=None,
        outcome=None,
        sanction_months=None,
        decided_on=None,
        opened_by_user_id=actor.user_id,
    )
    mark_created(case)
    DB.cases[case["id"]] = case
    return created_response(serialize.case(case))


@bp.get("/disciplinary-cases/<case_id>")
@api
def read_case(case_id):
    authenticate([ROLE_ETHICS_OFFICER, ROLE_PROGRAM_ADMIN, ROLE_CERTIFICANT])
    return object_response(serialize.case(lookup.case(case_id)))


@bp.get("/disciplinary-cases")
@api
def list_cases():
    authenticate([ROLE_ETHICS_OFFICER, ROLE_PROGRAM_ADMIN])
    limit, offset = read_pagination()
    rows = ordered(DB.cases.values())
    rows = apply_filters(rows, {
        "certificant_id": "certificant_id",
        "allegation_type": "allegation_type",
        "status": "status",
        "outcome": "outcome",
    })
    return paginate(rows, serialize.case, limit, offset)


@bp.post("/disciplinary-cases/<case_id>/request-response")
@api
def request_response(case_id):
    authenticate([ROLE_ETHICS_OFFICER])
    case = lookup.case(case_id)
    body = ensure_body(peek_body())
    opt_str(body, "request_note")

    # Layer 12.
    if case["status"] not in ("OPENED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE")

    certificant = DB.certificants[case["certificant_id"]]
    # Layer 17.
    if certificant["status"] == "REVOKED":
        raise ApiError("ERR_CERTIFICANT_ALREADY_REVOKED")

    case["status"] = "RESPONSE_REQUESTED"
    touch(case)
    return object_response(serialize.case(case))


@bp.post("/disciplinary-cases/<case_id>/respond")
@api
def respond_to_case(case_id):
    actor = authenticate([ROLE_CERTIFICANT])
    case = lookup.case(case_id)
    certificant = DB.certificants[case["certificant_id"]]

    # Layer 6: the respondent is the Candidate behind the credential.
    if certificant["candidate_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    body = ensure_body(peek_body())
    response_text = req_str(body, "response_text")

    # Layer 12.
    if case["status"] != "RESPONSE_REQUESTED":
        raise ApiError("ERR_INVALID_STATE")

    case["status"] = "UNDER_REVIEW"
    case["response_round"] += 1
    case["response_text"] = response_text
    touch(case)
    return object_response(serialize.case(case))


@bp.post("/disciplinary-cases/<case_id>/decide")
@api
def decide_case(case_id):
    actor = authenticate([ROLE_ETHICS_OFFICER])
    case = lookup.case(case_id)
    body = ensure_body(peek_body())
    outcome = req_enum(body, "outcome", DECISION_OUTCOMES)
    opt_str(body, "decision_note")

    # Layer 7: sanction_months is present exactly when the outcome sanctions.
    if outcome == "SANCTIONED":
        sanction_months = req_int(body, "sanction_months", minimum=1, maximum=60)
    else:
        if present(body, "sanction_months"):
            raise ApiError("ERR_INVALID_REQUEST")
        sanction_months = None

    # Layer 12.
    if case["status"] not in ("OPENED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE")

    certificant = DB.certificants[case["certificant_id"]]
    # Layer 17: a revoked credential admits no further disciplinary action.
    if certificant["status"] == "REVOKED":
        raise ApiError("ERR_CERTIFICANT_ALREADY_REVOKED")

    # Layer 19: the officer who brought the case may not end the credential.
    if outcome == "REVOKED" and case["opened_by_user_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # Layer 40.
    if outcome in ("SANCTIONED", "REVOKED") and case["response_round"] < 1:
        raise ApiError("ERR_DUE_PROCESS_INCOMPLETE")

    # PRD 3.12: only the sanction branch demands an ACTIVE respondent.
    if outcome == "SANCTIONED" and certificant["status"] != "ACTIVE":
        raise ApiError("ERR_CERTIFICANT_NOT_ACTIVE")

    case["outcome"] = outcome
    case["sanction_months"] = sanction_months
    case["decided_on"] = DB.now()
    case["status"] = "CLOSED"
    touch(case)

    if outcome == "SANCTIONED":
        certificant["status"] = "SUSPENDED"
        certificant["suspension_until"] = add_months(DB.now(), sanction_months)
        touch(certificant)
        derive.refresh_certificant_projection(certificant)
    elif outcome == "REVOKED":
        cascades.cascade_revocation(certificant)

    return object_response(serialize.case(case))
