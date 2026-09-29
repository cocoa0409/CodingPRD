"""Household registration, correction and income certification (PRD 3.1)."""

from flask import Blueprint

import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import calc, serializers
from services import constants as C

bp = Blueprint("applicants", __name__)

READ_ROLES = (
    middleware.INTAKE_SPECIALIST,
    middleware.REHAB_SPECIALIST,
    middleware.LOAN_OFFICER,
    middleware.PROGRAM_MANAGER,
)


@bp.post(API_PREFIX + "/applicants")
@middleware.roles(middleware.INTAKE_SPECIALIST)
def create_applicant():
    body = validation.json_body()
    program_year = validation.body_fk(
        body, "program_year_id", db.program_years, errors.ERR_PROGRAM_YEAR_NOT_FOUND
    )
    program_year_id = validation.field_id(body, "program_year_id")
    full_name = validation.field_str(body, "full_name")
    email = validation.field_str(body, "email")
    household_size = validation.field_int(body, "household_size", minimum=1, maximum=8)
    method = validation.field_enum(body, "income_calc_method", C.INCOME_CALC_METHODS)
    wage = validation.field_int(body, "wage_income_cents", minimum=0)
    benefit = validation.field_int(
        body, "benefit_income_cents", required=False, default=0, minimum=0
    )
    actual_asset = validation.field_int(
        body, "actual_asset_income_cents", required=False, default=0, minimum=0
    )
    assets = validation.field_int(
        body, "household_assets_cents", required=False, default=0, minimum=0
    )
    dependents = validation.field_int(
        body, "dependents_count", required=False, default=0, minimum=0
    )
    elderly = validation.field_bool(body, "elderly_household", default=False)

    for existing in db.applicants.values():
        if existing["email"] == email:
            fail(errors.ERR_INVALID_REQUEST, "Field 'email' must be unique.")

    row = db.new_row()
    row.update(
        {
            "program_year_id": program_year["id"] if program_year else program_year_id,
            "full_name": full_name,
            "email": email,
            "household_size": household_size,
            "dependents_count": dependents,
            "elderly_household": elderly,
            "wage_income_cents": wage,
            "benefit_income_cents": benefit,
            "actual_asset_income_cents": actual_asset,
            "household_assets_cents": assets,
            "income_calc_method": method,
            "annual_income_cents": None,
            "income_limit_cents": None,
            "ami_percent": None,
            "income_category": None,
            "eligibility_status": "APPLIED",
            "verified_by_user_id": None,
        }
    )
    db.applicants[row["id"]] = row
    return response.object_response(serializers.applicant(row), 201)


@bp.patch(API_PREFIX + "/applicants/<applicant_id>")
@middleware.roles(middleware.INTAKE_SPECIALIST)
def patch_applicant(applicant_id):
    row = validation.path_row(db.applicants, applicant_id, errors.ERR_APPLICANT_NOT_FOUND)
    body = validation.json_body()

    updates = {}
    if "income_calc_method" in body and body["income_calc_method"] is not None:
        updates["income_calc_method"] = validation.field_enum(
            body, "income_calc_method", C.INCOME_CALC_METHODS
        )
    for key in (
        "wage_income_cents",
        "benefit_income_cents",
        "actual_asset_income_cents",
        "household_assets_cents",
        "dependents_count",
    ):
        if key in body and body[key] is not None:
            updates[key] = validation.field_int(body, key, minimum=0)
    if "household_size" in body and body["household_size"] is not None:
        updates["household_size"] = validation.field_int(
            body, "household_size", minimum=1, maximum=8
        )
    if "elderly_household" in body and body["elderly_household"] is not None:
        updates["elderly_household"] = validation.field_bool(
            body, "elderly_household", required=True
        )

    if row["eligibility_status"] != "APPLIED":
        fail(errors.ERR_INVALID_STATE, "The household record is frozen after certification.")

    row.update(updates)
    db.touch(row)
    return response.object_response(serializers.applicant(row))


@bp.post(API_PREFIX + "/applicants/<applicant_id>/verify-income")
@middleware.roles(middleware.INTAKE_SPECIALIST)
def verify_income(applicant_id):
    row = validation.path_row(db.applicants, applicant_id, errors.ERR_APPLICANT_NOT_FOUND)
    if row["eligibility_status"] != "APPLIED":
        fail(errors.ERR_INVALID_STATE, "Household income has already been certified.")
    program_year = db.program_years.get(row["program_year_id"])
    if program_year is None:
        fail(errors.ERR_PROGRAM_YEAR_NOT_FOUND)

    figures = calc.applicant_income(row, program_year)
    row.update(figures)
    row["eligibility_status"] = (
        "INELIGIBLE" if figures["income_category"] == "OVER_INCOME" else "INCOME_VERIFIED"
    )
    row["verified_by_user_id"] = middleware.user_id()
    db.touch(row)
    return response.object_response(serializers.applicant(row))


@bp.get(API_PREFIX + "/applicants/<applicant_id>")
@middleware.roles(*READ_ROLES)
def read_applicant(applicant_id):
    row = validation.path_row(db.applicants, applicant_id, errors.ERR_APPLICANT_NOT_FOUND)
    return response.object_response(serializers.applicant(row))


@bp.get(API_PREFIX + "/applicants")
@middleware.roles(*READ_ROLES)
def list_applicants():
    program_year_id = validation.filter_str("program_year_id")
    status = validation.filter_enum("eligibility_status", C.ELIGIBILITY_STATUSES)
    category = validation.filter_enum("income_category", C.INCOME_CATEGORIES)
    rows = []
    for row in db.applicants.values():
        if program_year_id is not None and row["program_year_id"] != program_year_id:
            continue
        if status is not None and row["eligibility_status"] != status:
            continue
        if category is not None and row["income_category"] != category:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.applicant)
