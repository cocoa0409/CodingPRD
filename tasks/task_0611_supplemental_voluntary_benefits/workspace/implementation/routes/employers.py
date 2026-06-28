"""Employer endpoints (PRD §3.1).

POST /benefits/employers            (BenefitsAdmin)               -> 201
GET  /benefits/employers/{id}       (all roles)                  -> 200
"""

from flask import Blueprint

import errors
import serializers
from db import db
from middleware import require_roles
from response import success
from validation import get_json_body, require_str, optional_bool, optional_int

bp = Blueprint("employers", __name__)

VALID_PPY = {52, 26, 24, 12}


@bp.route("/benefits/employers", methods=["POST"])
@require_roles("BenefitsAdmin")
def create_employer():
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    # section_125_plan_active defaults to true (PRD §3.1)
    section_125 = optional_bool(body, "section_125_plan_active", default=True)
    # pay_periods_per_year defaults to 52, one of {52,26,24,12} (PRD §3.1)
    ppy = optional_int(body, "pay_periods_per_year", default=52)
    if ppy not in VALID_PPY:
        raise errors.invalid_request("pay_periods_per_year must be one of 52, 26, 24, 12")

    record = {
        "legal_name": legal_name,
        "section_125_plan_active": section_125,
        "pay_periods_per_year": ppy,
        "status": "ACTIVE",
    }
    with db.lock:
        db.employers.insert(record)
    return success(serializers.employer(record), 201)


@bp.route("/benefits/employers/<employer_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Payroll", "Employee")
def get_employer(employer_id):
    record = db.employers.get(employer_id)
    if record is None:
        raise errors.not_found("Employer not found")
    return success(serializers.employer(record), 200)
