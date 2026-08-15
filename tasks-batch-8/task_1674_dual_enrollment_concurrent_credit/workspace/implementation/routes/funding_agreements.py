"""FundingAgreement endpoints (PRD 3.7). Unique on (high_school_id, college_term_id)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_DUPLICATE_FUNDING_AGREEMENT
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, public
from validate import (
    get_body,
    opt_int,
    req_enum,
    req_int,
    req_str,
    require_body_ref,
)

bp = Blueprint("funding_agreements", __name__)

FUNDING_MODELS = {"STATE_PROGRAM", "DISTRICT_CONTRACT", "FAMILY_RESPONSIBLE"}


@bp.post("/funding-agreements")
def create_funding_agreement():
    authorized(["DualCreditAdmin"])
    body = get_body()
    high_school_id = req_str(body, "high_school_id")
    college_term_id = req_str(body, "college_term_id")
    funding_model = req_enum(body, "funding_model", FUNDING_MODELS)
    tuition_cents_per_credit = req_int(body, "tuition_cents_per_credit", minimum=1)
    state_rate_cents_per_credit = opt_int(
        body, "state_rate_cents_per_credit", default=0, minimum=0
    )
    district_cap_cents = opt_int(body, "district_cap_cents", default=0, minimum=0)

    # Priority 5: body FKs in declared input order.
    require_body_ref("high_schools", high_school_id, "high_school_id")
    require_body_ref("terms", college_term_id, "college_term_id")

    # Priority 15: at most one agreement per (high_school_id, college_term_id).
    for a in db["funding_agreements"].values():
        if (
            a["high_school_id"] == high_school_id
            and a["college_term_id"] == college_term_id
        ):
            raise_error(
                ERR_DUPLICATE_FUNDING_AGREEMENT,
                "a funding agreement already exists for this school and term",
            )

    rec = new_record(
        "funding_agreements",
        {
            "high_school_id": high_school_id,
            "college_term_id": college_term_id,
            "funding_model": funding_model,
            "tuition_cents_per_credit": tuition_cents_per_credit,
            "state_rate_cents_per_credit": state_rate_cents_per_credit,
            "district_cap_cents": district_cap_cents,
        },
    )
    return success_object(public(rec), status=201)


@bp.get("/funding-agreements")
def list_funding_agreements():
    return list_response(
        "funding_agreements",
        {
            "high_school_id": arg("high_school_id"),
            "college_term_id": arg("college_term_id"),
        },
    )


@bp.get("/funding-agreements/<rid>")
def get_funding_agreement(rid):
    return get_one("funding_agreements", rid)
