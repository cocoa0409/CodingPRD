"""Applicant routes (PRD §3.1)."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, gen_id, lock
from core.timeutils import parse_iso_date
from core.validation import require_body, require_field, require_enum
from services.mutations import stamp_create, bump
from services.projections import project_applicant


bp = Blueprint("applicants", __name__)


_DEPENDENT_STATUSES = {"PRIMARY", "SPOUSE", "DEPENDENT", "EXCLUDED"}


@bp.route("/households/<household_id>/applicants", methods=["POST"])
@require_roles("IntakeWorker")
def create_applicant(household_id):
    household = STORE.households.get(household_id)
    if household is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    body = require_body(request)
    full_name = require_field(body, "full_name", kind="string")
    dob = require_field(body, "date_of_birth", kind="string")
    parse_iso_date(dob, "date_of_birth")  # validates format
    dep_status = require_enum(body, "dependent_status", _DEPENDENT_STATUSES)
    is_disabled = body.get("is_disabled", False)
    if not isinstance(is_disabled, bool):
        raise_error("ERR_INVALID_REQUEST", "is_disabled must be a boolean")
    is_pregnant = body.get("is_pregnant", False)
    if not isinstance(is_pregnant, bool):
        raise_error("ERR_INVALID_REQUEST", "is_pregnant must be a boolean")

    with lock():
        aid = gen_id()
        row = {
            "id": aid,
            "household_id": household_id,
            "full_name": full_name,
            "date_of_birth": dob,
            "dependent_status": dep_status,
            "is_disabled": is_disabled,
            "is_pregnant": is_pregnant,
        }
        stamp_create(row)
        STORE.applicants[aid] = row
        # First non-EXCLUDED becomes head_applicant_id if unset
        if household.get("head_applicant_id") is None and dep_status != "EXCLUDED":
            household["head_applicant_id"] = aid
        # Household.size and derivatives are computed lazily; bump household.
        bump(household)

    return success_object(project_applicant(row), status=201)


@bp.route("/households/<household_id>/applicants/<applicant_id>", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "PolicyAdmin")
def get_applicant(household_id, applicant_id):
    household = STORE.households.get(household_id)
    if household is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    row = STORE.applicants.get(applicant_id)
    if row is None or row["household_id"] != household_id:
        raise_error("ERR_NOT_FOUND", "Applicant not found")
    return success_object(project_applicant(row))
