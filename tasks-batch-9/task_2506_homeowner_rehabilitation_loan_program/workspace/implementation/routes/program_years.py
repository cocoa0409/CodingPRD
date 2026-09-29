"""Program year endpoints (PRD 3.1, 2.9)."""

from flask import Blueprint

import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import serializers

bp = Blueprint("program_years", __name__)

READ_ROLES = middleware.STAFF_ROLES


@bp.post(API_PREFIX + "/program-years")
@middleware.roles(middleware.PROGRAM_MANAGER)
def create_program_year():
    body = validation.json_body()
    fiscal_year = validation.field_int(body, "fiscal_year", minimum=2020, maximum=2035)
    ami = validation.field_int(body, "ami_median_income_cents", minimum=1)
    max_loan = validation.field_int(body, "max_loan_amount_cents", minimum=1)
    allocation = validation.field_int(body, "allocation_budget_cents", minimum=1)

    for existing in db.program_years.values():
        if existing["fiscal_year"] == fiscal_year:
            fail(errors.ERR_INVALID_REQUEST, "Field 'fiscal_year' must be unique.")

    row = db.new_row()
    row.update(
        {
            "fiscal_year": fiscal_year,
            "ami_median_income_cents": ami,
            "max_loan_amount_cents": max_loan,
            "allocation_budget_cents": allocation,
            "program_income_balance_cents": 0,
        }
    )
    db.program_years[row["id"]] = row
    return response.object_response(serializers.program_year(row), 201)


@bp.get(API_PREFIX + "/program-years/<program_year_id>")
@middleware.roles(*READ_ROLES)
def read_program_year(program_year_id):
    row = validation.path_row(
        db.program_years, program_year_id, errors.ERR_PROGRAM_YEAR_NOT_FOUND
    )
    return response.object_response(serializers.program_year(row))


@bp.get(API_PREFIX + "/program-years")
@middleware.roles(*READ_ROLES)
def list_program_years():
    fiscal_year = validation.filter_int("fiscal_year")
    rows = [
        row
        for row in db.program_years.values()
        if fiscal_year is None or row["fiscal_year"] == fiscal_year
    ]
    return paging.collection(rows, serializers.program_year)
