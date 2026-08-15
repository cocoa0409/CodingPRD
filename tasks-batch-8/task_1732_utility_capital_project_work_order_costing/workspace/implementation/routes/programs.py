"""CapitalProgram endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_PROGRAM_HAS_OPEN_WORK_ORDERS,
)
from middleware import authorized
from response import success_object
from services.core import (
    new_record, touch, serialize_program, program_work_orders,
    WO_NON_TERMINAL_FOR_PROGRAM_CLOSE,
)
from validate import (
    get_body, req_str, req_int, req_num, req_enum, require_path_resource,
)
from routes.helpers import list_response, get_one

bp = Blueprint("capital_programs", __name__)


@bp.route("/ucp/capital-programs", methods=["POST"])
def create_program():
    caller = authorized(["SystemAdmin"])
    body = get_body()
    # Priority 4 — request shape.
    code = req_str(body, "code")
    fiscal_year = req_int(body, "fiscal_year")
    authorized_amount_cents = req_int(body, "authorized_amount_cents", positive=True)
    debt_rate = req_num(body, "afudc_debt_rate_pct", non_negative=True)
    equity_rate = req_num(body, "afudc_equity_rate_pct", non_negative=True)
    debt_weight = req_num(body, "afudc_debt_weight_pct", minimum=0, maximum=100)
    afudc_method = req_enum(body, "afudc_method", ["HALF_MONTH", "FULL_MONTH"])
    ciac_method = req_enum(body, "ciac_method", ["NET_OF_CIAC", "GROSS_WITH_CONTRA"])
    # Budget code unique across all programs.
    for p in db["capital_programs"].values():
        if p["code"] == code:
            raise_error(ERR_VALIDATION, f"duplicate program code: {code}")

    rec = new_record()
    rec.update({
        "code": code,
        "fiscal_year": fiscal_year,
        "authorized_amount_cents": authorized_amount_cents,
        "afudc_debt_rate_pct": debt_rate,
        "afudc_equity_rate_pct": equity_rate,
        "afudc_debt_weight_pct": debt_weight,
        "afudc_method": afudc_method,
        "ciac_method": ciac_method,
        "status": "OPEN",
        "expense_writeoff_cents": 0,
    })
    db["capital_programs"][rec["id"]] = rec
    return success_object(serialize_program(rec), status=201)


@bp.route("/ucp/capital-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    return get_one("capital_programs", serialize_program, program_id)


@bp.route("/ucp/capital-programs", methods=["GET"])
def list_programs():
    filters = {
        "fiscal_year": request.args.get("fiscal_year"),
        "status": request.args.get("status"),
    }
    return list_response("capital_programs", serialize_program, filters)


@bp.route("/ucp/capital-programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    authorized(["Controller"])
    program = require_path_resource("capital_programs", program_id)
    # Priority 7 — state legality.
    if program["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "program is not OPEN")
    # Priority 10 — every work order must be terminal.
    for wo in program_work_orders(program["id"]):
        if wo["status"] in WO_NON_TERMINAL_FOR_PROGRAM_CLOSE:
            raise_error(
                ERR_PROGRAM_HAS_OPEN_WORK_ORDERS,
                "program has work orders in a non-terminal state",
            )
    program["status"] = "CLOSED"
    touch(program)
    return success_object(serialize_program(program))
