"""State surplus lines programs — the regulatory configuration record (PRD 3.1)."""

from flask import Blueprint

import auth
import serialize
import store
import validation
from envelope import created, ok
from errors import ApiError
from store import db, touch

bp = Blueprint("state_programs", __name__)

ALLOCATION_METHODS = ("HOME_STATE_SINGLE", "ALLOCATED_MULTI")
FILING_FREQUENCIES = ("MONTHLY", "QUARTERLY")


@bp.post("/state-programs")
def create_program():
    auth.require("PlatformAdmin")
    data = validation.body()
    state_code = validation.req_state_code(data, "state_code")
    premium_tax_rate = validation.req_number(data, "premium_tax_rate", minimum=0,
                                             maximum=0.15, max_decimals=6)
    stamping_fee_rate = validation.req_number(data, "stamping_fee_rate", minimum=0,
                                              maximum=0.05, max_decimals=6)
    cap = validation.opt_int(data, "stamping_fee_cap_cents", default=None,
                             minimum=0, nullable=True)
    stamping_office_required = validation.req_bool(data, "stamping_office_required")
    allocation_method = validation.req_enum(data, "allocation_method",
                                            ALLOCATION_METHODS)
    min_declinations = validation.req_int(data, "diligent_search_min_declinations",
                                          minimum=0)
    export_list_exempts_search = validation.req_bool(data, "export_list_exempts_search")
    filing_frequency = validation.req_enum(data, "filing_frequency",
                                           FILING_FREQUENCIES)
    filing_deadline_days = validation.req_int(data, "filing_deadline_days", minimum=0)
    tax_refundable = validation.req_bool(data, "return_premium_tax_refundable")
    stamping_refundable = validation.req_bool(data,
                                              "return_premium_stamping_refundable")
    min_capital = validation.req_int(data, "min_carrier_capital_surplus_cents",
                                     minimum=0)
    notice_codes = validation.req_upper_code_array(data, "required_notice_codes")

    if store.state_program_by_code(state_code) is not None:
        raise ApiError("ERR_STATE_PROGRAM_DUPLICATE",
                       "A state program already exists for %s." % state_code)

    rec = db.insert("state_programs", {
        "state_code": state_code,
        "premium_tax_rate": premium_tax_rate,
        "stamping_fee_rate": stamping_fee_rate,
        "stamping_fee_cap_cents": cap,
        "stamping_office_required": stamping_office_required,
        "allocation_method": allocation_method,
        "diligent_search_min_declinations": min_declinations,
        "export_list_exempts_search": export_list_exempts_search,
        "filing_frequency": filing_frequency,
        "filing_deadline_days": filing_deadline_days,
        "return_premium_tax_refundable": tax_refundable,
        "return_premium_stamping_refundable": stamping_refundable,
        "min_carrier_capital_surplus_cents": min_capital,
        "required_notice_codes": list(notice_codes),
    })
    return created(serialize.public(rec))


@bp.get("/state-programs/<rec_id>")
def get_program(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("state_programs", "state_program", rec_id)
    return ok(serialize.public(rec))


@bp.patch("/state-programs/<rec_id>")
def patch_program(rec_id):
    """Amendment is not retroactive: allocation rows keep their pinned rates."""
    auth.require("PlatformAdmin")
    rec = auth.path_entity("state_programs", "state_program", rec_id)
    data = validation.body()

    if validation.present(data, "premium_tax_rate"):
        rec["premium_tax_rate"] = validation.req_number(
            data, "premium_tax_rate", minimum=0, maximum=0.15, max_decimals=6)
    if validation.present(data, "stamping_fee_rate"):
        rec["stamping_fee_rate"] = validation.req_number(
            data, "stamping_fee_rate", minimum=0, maximum=0.05, max_decimals=6)
    if "stamping_fee_cap_cents" in data:
        rec["stamping_fee_cap_cents"] = validation.opt_int(
            data, "stamping_fee_cap_cents", default=None, minimum=0, nullable=True)
    if validation.present(data, "stamping_office_required"):
        rec["stamping_office_required"] = validation.req_bool(
            data, "stamping_office_required")
    if validation.present(data, "diligent_search_min_declinations"):
        rec["diligent_search_min_declinations"] = validation.req_int(
            data, "diligent_search_min_declinations", minimum=0)
    if validation.present(data, "filing_deadline_days"):
        rec["filing_deadline_days"] = validation.req_int(
            data, "filing_deadline_days", minimum=0)
    if validation.present(data, "required_notice_codes"):
        rec["required_notice_codes"] = list(
            validation.req_upper_code_array(data, "required_notice_codes"))

    touch(rec)
    return ok(serialize.public(rec))
