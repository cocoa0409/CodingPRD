"""StateRegistration endpoints (PRD 3.3)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_DUPLICATE_REGISTRATION,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.employers import get_employer_or_404
from services.serializers import serialize_registration
from util import (
    apply_filters,
    get_json_body,
    is_int,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("registrations", __name__)

AGENCIES = {"SIT_WITHHOLDING", "SUTA", "NEW_HIRE_DIRECTORY"}


def get_registration_or_404(registration_id: str) -> dict:
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise_err(ERR_NOT_FOUND, "StateRegistration id does not exist")
    return reg


@bp.route("/household-payroll/employers/<employer_id>/registrations", methods=["POST"])
@require_roles("PayrollAdmin")
def create_registration(employer_id: str, _user_id: str, _role: str):
    employer = get_employer_or_404(employer_id)
    body = get_json_body()
    state_code = require_string(body, "state_code")
    agency = require_enum(body, "agency", AGENCIES)
    expected = require_field(body, "expected_employer_version")
    if not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_employer_version must be an integer")

    # OCC runs before any state-machine evaluation (pipeline step 5).
    if expected != employer["version"]:
        raise_err(ERR_STALE_VERSION, "expected_employer_version does not match the employer version")

    if employer["status"] not in ("ONBOARDING", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Registration create requires employer ONBOARDING or ACTIVE")

    for reg in db.registrations.values():
        if (reg["employer_id"] == employer_id
                and reg["state_code"] == state_code
                and reg["agency"] == agency):
            raise_err(
                ERR_DUPLICATE_REGISTRATION,
                "A non-terminal registration for (employer, state_code, agency) exists",
            )

    reg = {
        "employer_id": employer_id,
        "state_code": state_code,
        "agency": agency,
        "agency_account_number": None,
        "status": "DRAFT",
        "submitted_at": None,
    }
    db.stamp_new(reg)
    db.registrations[reg["id"]] = reg
    db.touch(employer)  # creation increments the parent employer's version
    return success_object(serialize_registration(reg), 201)


@bp.route("/household-payroll/registrations/<registration_id>/submit", methods=["POST"])
@require_roles("PayrollAdmin")
def submit_registration(registration_id: str, _user_id: str, _role: str):
    reg = get_registration_or_404(registration_id)
    if reg["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT registration can be submitted")
    reg["status"] = "SUBMITTED"
    reg["submitted_at"] = db.now_iso()
    db.touch(reg)
    return success_object(serialize_registration(reg))


@bp.route("/household-payroll/registrations/<registration_id>/activate", methods=["POST"])
@require_roles("PayrollAdmin")
def activate_registration(registration_id: str, _user_id: str, _role: str):
    reg = get_registration_or_404(registration_id)
    body = get_json_body()
    account_number = require_string(body, "agency_account_number")
    if reg["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED registration can be activated")
    reg["status"] = "ACTIVE"
    reg["agency_account_number"] = account_number
    db.touch(reg)

    # First ACTIVE registration flips the employer ONBOARDING -> ACTIVE.
    employer = db.employers.get(reg["employer_id"])
    if employer is not None and employer["status"] == "ONBOARDING":
        employer["status"] = "ACTIVE"
        db.touch(employer)
    return success_object(serialize_registration(reg))


@bp.route("/household-payroll/employers/<employer_id>/registrations", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_registrations(employer_id: str, _user_id: str, _role: str):
    employer = get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer["id"])
    limit, offset = parse_pagination()
    items = [r for r in db.registrations.values() if r["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["state_code", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_registration(r) for r in page], limit, offset, total)
