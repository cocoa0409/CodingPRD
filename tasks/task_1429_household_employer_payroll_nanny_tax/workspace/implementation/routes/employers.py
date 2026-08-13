"""HouseholdEmployer endpoints (PRD 3.2)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REGISTRATION_INACTIVE,
    ERR_STATE_RULES_MISSING,
    ERR_PAY_FREQUENCY_NONCOMPLIANT,
)
from middleware import require_roles, check_employer_ownership
from response import success_object
from services.posture import pack_for_state
from services.serializers import serialize_employer
from util import (
    get_json_body,
    optional_int,
    require_enum,
    require_fein,
    require_string,
)

bp = Blueprint("employers", __name__)

PAY_FREQUENCIES = {"WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"}
# Most frequent -> least frequent
FREQUENCY_RANK = {"WEEKLY": 0, "BIWEEKLY": 1, "SEMIMONTHLY": 2, "MONTHLY": 3}


def get_employer_or_404(employer_id: str) -> dict:
    employer = db.employers.get(employer_id)
    if employer is None:
        raise_err(ERR_NOT_FOUND, "HouseholdEmployer id does not exist")
    return employer


@bp.route("/household-payroll/employers", methods=["POST"])
@require_roles("PayrollAdmin")
def create_employer(_user_id: str, _role: str):
    body = get_json_body()
    legal_name = require_string(body, "legal_name")
    primary_state_code = require_string(body, "primary_state_code")
    fein = require_fein(body, "fein")
    pay_frequency = require_enum(body, "pay_frequency", PAY_FREQUENCIES)
    prior_year = optional_int(body, "prior_year_schedule_h_cents", 0, 0)

    pack = pack_for_state(primary_state_code)
    if pack is None:
        raise_err(ERR_STATE_RULES_MISSING, "No StateRulePack exists for the primary state")
    if FREQUENCY_RANK[pay_frequency] > FREQUENCY_RANK[pack["min_pay_frequency"]]:
        raise_err(
            ERR_PAY_FREQUENCY_NONCOMPLIANT,
            "pay_frequency is less frequent than the state's min_pay_frequency",
        )

    employer = {
        "legal_name": legal_name,
        "primary_state_code": primary_state_code,
        "fein": fein,
        "pay_frequency": pay_frequency,
        "prior_year_schedule_h_cents": prior_year,
        "status": "ONBOARDING",
    }
    db.stamp_new(employer)
    db.employers[employer["id"]] = employer
    return success_object(serialize_employer(employer), 201)


@bp.route("/household-payroll/employers/<employer_id>", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def get_employer(employer_id: str, _user_id: str, _role: str):
    employer = get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer["id"])
    return success_object(serialize_employer(employer))


@bp.route("/household-payroll/employers/<employer_id>/suspend", methods=["POST"])
@require_roles("ComplianceOfficer")
def suspend_employer(employer_id: str, _user_id: str, _role: str):
    employer = get_employer_or_404(employer_id)
    if employer["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE employer can be suspended")
    employer["status"] = "SUSPENDED"
    db.touch(employer)
    return success_object(serialize_employer(employer))


@bp.route("/household-payroll/employers/<employer_id>/reinstate", methods=["POST"])
@require_roles("ComplianceOfficer")
def reinstate_employer(employer_id: str, _user_id: str, _role: str):
    employer = get_employer_or_404(employer_id)
    if employer["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Only a SUSPENDED employer can be reinstated")
    for reg in db.registrations.values():
        if (reg["employer_id"] == employer_id
                and reg["state_code"] == employer["primary_state_code"]
                and reg["status"] != "ACTIVE"):
            raise_err(
                ERR_REGISTRATION_INACTIVE,
                "A registration for the primary state is not ACTIVE",
            )
    employer["status"] = "ACTIVE"
    db.touch(employer)
    return success_object(serialize_employer(employer))
