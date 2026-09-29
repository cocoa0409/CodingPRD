"""Programs: the commission base (PRD 3.2)."""

from flask import Blueprint

import errors
import serializers
from db import db, base_record
from errors import fail
from response import obj
from routes.common import auth, need
from services import calc
from validation import (body, fmt_date, opt_bool, opt_int, req_date, req_enum, req_int,
                        req_str)

bp = Blueprint("programs", __name__)


@bp.route("/recruitment/programs", methods=["POST"])
def create_program():
    auth("RecruitmentOfficer")
    data = body()
    code = req_str(data, "code", min_len=2, max_len=32)
    name = req_str(data, "name", min_len=1)
    level = req_enum(data, "level", calc.PROGRAM_LEVELS)
    annual_tuition_cents = req_int(data, "annual_tuition_cents", minimum=1)
    term_start_date = req_date(data, "term_start_date")
    census_date = req_date(data, "census_date")
    persistence_check_date = req_date(data, "persistence_check_date")
    commission_eligible = opt_bool(data, "commission_eligible", default=True)
    max_commission_bps = opt_int(data, "max_commission_bps", minimum=0, maximum=5000,
                                 default=1000)

    if census_date < term_start_date or not (persistence_check_date > census_date):
        fail(errors.ERR_TERM_WINDOW_INVALID, "The program date set is not coherent")
    for existing in db.programs.values():
        if existing["code"] == code:
            fail(errors.ERR_DUPLICATE_RESOURCE, "Program code '%s' already exists" % code)

    record = base_record()
    record.update({
        "code": code,
        "name": name,
        "level": level,
        "annual_tuition_cents": annual_tuition_cents,
        "term_start_date": fmt_date(term_start_date),
        "census_date": fmt_date(census_date),
        "persistence_check_date": fmt_date(persistence_check_date),
        "commission_eligible": commission_eligible,
        "max_commission_bps": max_commission_bps,
    })
    db.programs[record["id"]] = record
    return obj(serializers.program(record), 201)


@bp.route("/recruitment/programs/<program_id>", methods=["GET"])
def read_program(program_id):
    auth("RecruitmentOfficer", "ComplianceOfficer", "FinanceOfficer", "Registrar",
         "AgencyOwner")
    record = need(db.programs, program_id, errors.ERR_PROGRAM_NOT_FOUND)
    return obj(serializers.program(record))
