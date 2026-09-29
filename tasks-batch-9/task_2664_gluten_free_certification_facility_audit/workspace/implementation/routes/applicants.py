"""Applicant registration and read."""

from flask import Blueprint

import db
import middleware as mw
import query
import response
from constants import READ_APPLICANTS, ROLE_PROGRAM_ADMIN

bp = Blueprint("applicants", __name__)


@bp.post("/gfco/applicants")
def create_applicant():
    mw.authenticate([ROLE_PROGRAM_ADMIN])
    data = mw.body()
    legal_name = mw.req_str(data, "legal_name")
    contact_email = mw.req_str(data, "contact_email")
    country_code = mw.req_country(data, "country_code")
    row = db.insert(
        db.applicants,
        {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "country_code": country_code,
            "current_cycle_started_on": None,
            "open_nc_penalty_points": 0,
            "active_certified_product_count": 0,
            "suspended_certificate_count": 0,
            "revoked_certificate_count": 0,
            "substantiated_complaint_count_rolling": 0,
            "substantiated_complaint_count_cycle": 0,
            "posture_score_rolling_12m": 100,
            "posture_score_cycle": 100,
            "compliance_posture": "GOOD_STANDING",
            "fee_balance_cents": 0,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/applicants/<applicant_id>")
def get_applicant(applicant_id):
    mw.authenticate(READ_APPLICANTS)
    return response.ok(response.serialize(query.fetch("applicant", applicant_id)))
