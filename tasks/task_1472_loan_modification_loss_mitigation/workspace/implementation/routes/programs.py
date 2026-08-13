from flask import Blueprint, request

import store
from auth import NON_BORROWER_ROLES, authenticate, authorize
from errors import (
    ERR_PROGRAM_OPTION_NOT_FOUND,
    ERR_PROGRAM_RANK_DUPLICATE,
    ERR_VALIDATION,
    raise_err,
)
from services import program_out
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    req_int,
    req_str,
    success_object,
)

bp = Blueprint("programs", __name__)


@bp.route("/program-options", methods=["POST"])
def create_program():
    _, role = authenticate()
    authorize(role, ["ServicingAdmin"])
    body = body_json()
    code = req_str(body, "code")
    waterfall_rank = req_int(body, "waterfall_rank")
    target_dti_bp = req_int(body, "target_dti_bp")
    rate_floor_bp = req_int(body, "rate_floor_bp")
    rate_step_bp = req_int(body, "rate_step_bp")
    max_term_months = req_int(body, "max_term_months")
    max_forbearance_pct_bp = req_int(body, "max_forbearance_pct_bp")
    min_delinquency_days = req_int(body, "min_delinquency_days")
    max_delinquency_days = req_int(body, "max_delinquency_days")

    for p in store.programs.values():
        if p["waterfall_rank"] == waterfall_rank:
            raise_err(ERR_PROGRAM_RANK_DUPLICATE,
                      "waterfall_rank %s already in use" % waterfall_rank)

    rec = new_record()
    rec.update({
        "code": code,
        "waterfall_rank": waterfall_rank,
        "target_dti_bp": target_dti_bp,
        "rate_floor_bp": rate_floor_bp,
        "rate_step_bp": rate_step_bp,
        "max_term_months": max_term_months,
        "max_forbearance_pct_bp": max_forbearance_pct_bp,
        "min_delinquency_days": min_delinquency_days,
        "max_delinquency_days": max_delinquency_days,
        "status": "ACTIVE",
    })
    store.programs[rec["id"]] = rec
    return success_object(program_out(rec), 201)


@bp.route("/program-options", methods=["GET"])
def list_programs():
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    records = list(store.programs.values())
    status = request.args.get("status")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return list_response(records, program_out)


@bp.route("/program-options/<rid>", methods=["GET"])
def get_program(rid):
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    rec = get_or_404(store.programs, rid, ERR_PROGRAM_OPTION_NOT_FOUND, "ProgramOption")
    return success_object(program_out(rec))


@bp.route("/program-options/<rid>/retire", methods=["POST"])
def retire_program(rid):
    _, role = authenticate()
    authorize(role, ["ServicingAdmin"])
    rec = get_or_404(store.programs, rid, ERR_PROGRAM_OPTION_NOT_FOUND, "ProgramOption")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_VALIDATION, "Program option is not ACTIVE")
    rec["status"] = "RETIRED"
    bump(rec)
    return success_object(program_out(rec))
