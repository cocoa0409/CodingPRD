"""Business units (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from services.core import make_record, pub_business_unit
from validate import get_body, req_str, opt_int, get_resource

bp = Blueprint("business_units", __name__)

ADMIN = ["DiversityAdmin"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "BusinessUnitLead", "Auditor"]


@bp.route("/api/v1/business-units", methods=["POST"])
def create_business_unit():
    authorized(ADMIN)
    body = get_body()
    name = req_str(body, "name")
    code = req_str(body, "code")
    lead_user_id = req_str(body, "lead_user_id")
    inclusion_min = opt_int(body, "inclusion_min_diverse_bidders", 1, minimum=0, maximum=10)
    # code is unique across all business units (immutable after creation)
    for existing in db["business_units"].values():
        if existing["code"] == code:
            raise_error(ERR_INVALID_REQUEST, f"business unit code already in use: {code}")
    rec = make_record({
        "name": name,
        "code": code,
        "lead_user_id": lead_user_id,
        "inclusion_min_diverse_bidders": inclusion_min,
        "lifetime_imported_spend_cents": 0,
        "lifetime_voided_spend_cents": 0,
    })
    db["business_units"][rec["id"]] = rec
    return success_object(pub_business_unit(rec), status=201)


@bp.route("/api/v1/business-units/<rid>", methods=["GET"])
def get_business_unit(rid):
    authorized(READERS)
    rec = get_resource("business_units", rid)
    return success_object(pub_business_unit(rec))
