"""BackgroundDisclosure endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_enum, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import err_invalid_state, err_invalid_request

bp = Blueprint("background", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
QUESTION_CODES = {"CRIMINAL", "REGULATORY", "FINANCIAL", "CIVIL", "EMPLOYMENT"}


@bp.post("/registration-desk/background-disclosures")
def create_disclosure():
    auth("RegistrationPrincipal")
    data = body()
    req = fk_or_404(store.registration_requests, data.get("registration_request_id"))
    required(data, "registration_request_id")
    qcode = require_enum(required(data, "question_code"), QUESTION_CODES, "question_code")
    answer = required(data, "answer")
    if not isinstance(answer, bool):
        raise err_invalid_request("answer must be a boolean")
    explanation = data.get("explanation_text")
    if answer is True:
        if not isinstance(explanation, str) or len(explanation) < 20:
            raise err_invalid_request(
                "explanation_text is required with min length 20 when answer is true"
            )
    d = new_entity()
    d.update({
        "registration_request_id": req["id"],
        "question_code": qcode,
        "answer": answer,
        "explanation_text": explanation,
        # answer=false rows are stored CLEARED at creation; answer=true enters PENDING_REVIEW.
        "review_status": "PENDING_REVIEW" if answer else "CLEARED",
    })
    store.background_disclosures[d["id"]] = d
    return success_obj(serialize(d), 201)


@bp.get("/registration-desk/background-disclosures")
def list_disclosures():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.background_disclosures,
        (
            ("registration_request_id", "registration_request_id", str),
            ("review_status", "review_status", str),
        ),
    )
    return success_list([serialize(d) for d in page], limit, offset, total)


@bp.get("/registration-desk/background-disclosures/<id>")
def get_disclosure(id):
    auth(*READ_ROLES)
    d = get_or_404(store.background_disclosures, id)
    return success_obj(serialize(d), 200)


@bp.post("/registration-desk/background-disclosures/<id>/review")
def review_disclosure(id):
    auth("ComplianceOfficer")
    d = get_or_404(store.background_disclosures, id)
    if d["review_status"] != "PENDING_REVIEW":
        raise err_invalid_state("only a PENDING_REVIEW disclosure may be reviewed")
    data = body()
    outcome = require_enum(required(data, "outcome"), {"CLEARED", "FLAGGED"}, "outcome")
    d["review_status"] = outcome
    touch(d)
    return success_obj(serialize(d), 200)
