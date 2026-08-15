"""DeductionItem endpoints (PRD §3.4): manual deductions plus reads."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_STATE_TRANSITION
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import (
    new_record, public, recompute_tenancy_money,
    refresh_draft_statement_projection, touch,
)
from validate import (
    get_body, req_enum, req_int, req_str, require_body_ref,
)

bp = Blueprint("deductions", __name__)

MANUAL_SOURCES = ("UNPAID_RENT", "CLEANING", "OTHER")


@bp.post("/pm/deductions")
def create_deduction():
    authorized(["PropertyManager"])
    body = get_body()
    tenancy_id = req_str(body, "tenancy_id")
    # Manual deductions accept only the manual sources; the counted/computed
    # sources are system-created at move-out completion.
    source = req_enum(body, "source", MANUAL_SOURCES)
    description = req_str(body, "description")
    amount_cents = req_int(body, "amount_cents", non_negative=True)
    tenancy = require_body_ref("tenancies", tenancy_id, "tenancy_id")
    if tenancy["status"] not in ("NOTICE_GIVEN", "VACATED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "manual deductions require the tenancy NOTICE_GIVEN or VACATED")
    rec = new_record("deductions", {
        "tenancy_id": tenancy["id"],
        "inspection_item_id": None,
        "statement_id": None,
        "source": source,
        "description": description,
        "quantity": 1,
        "amount_cents": amount_cents,
        "status": "DRAFT",
    })
    recompute_tenancy_money(tenancy["id"])
    refresh_draft_statement_projection(tenancy)
    touch(tenancy)
    return success_object(public(rec), status=201)


@bp.get("/pm/deductions/<rid>")
def get_deduction(rid):
    return get_one("deductions", rid)


@bp.get("/pm/deductions")
def list_deductions():
    return list_response("deductions", {
        "tenancy_id": request.args.get("tenancy_id"),
        "inspection_item_id": request.args.get("inspection_item_id"),
        "statement_id": request.args.get("statement_id"),
        "status": request.args.get("status"),
    })
