"""Reimbursement endpoints (PRD §3.7): record the wire, post to the plan ledger."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_REIMBURSEMENT_MISMATCH,
)
from middleware import authorized
from response import success_object
from routes.helpers import READ_REIMBURSEMENT, get_one, list_response
from services.accumulation import recompute_aggregate_row
from services.core import new_record, public, touch
from util import norm_dt
from validate import (
    get_body, req_str, req_int, req_datetime, require_path_resource, require_ref,
)

bp = Blueprint("reimbursements", __name__)


@bp.post("/stop-loss/reimbursements")
def create_reimbursement():
    authorized(["PlanAccountant"])
    body = get_body()
    filing_id = req_str(body, "filing_id")
    received = req_int(body, "received_amount_cents", minimum=0)
    received_at = req_datetime(body, "received_at")
    require_ref("filings", filing_id, "filing_id")
    rec = new_record("reimbursements", {
        "filing_id": filing_id,
        "received_amount_cents": received,
        "received_at": norm_dt(received_at),
        "status": "RECEIVED",
    })
    return success_object(public(rec), status=201)


@bp.get("/stop-loss/reimbursements/<rid>")
def get_reimbursement(rid):
    return get_one("reimbursements", rid, READ_REIMBURSEMENT)


@bp.get("/stop-loss/reimbursements")
def list_reimbursements():
    return list_response("reimbursements", READ_REIMBURSEMENT,
                         {"filing_id": request.args.get("filing_id")})


@bp.post("/stop-loss/reimbursements/<rid>/post")
def post_reimbursement(rid):
    authorized(["PlanAccountant"])
    get_body()
    reimb = require_path_resource("reimbursements", rid)
    if reimb["status"] != "RECEIVED":
        raise_error(ERR_INVALID_STATE,
                    f"reimbursement in {reimb['status']} cannot be posted")
    filing = db["filings"].get(reimb["filing_id"])
    if filing is None or filing["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE,
                    "the underlying filing must be APPROVED at posting time")
    # Deliberately strict: short payment or overpayment cannot post at all.
    if reimb["received_amount_cents"] != filing["approved_amount_cents"]:
        raise_error(ERR_REIMBURSEMENT_MISMATCH,
                    "received_amount_cents must equal the filing's approved_amount_cents")

    touch(reimb)
    reimb["status"] = "POSTED"
    # One mutation, two side effects (PRD §3.7): filing APPROVED -> PAID, and the
    # plan's AGGREGATE row nets the reimbursed excess out of unrecovered exposure.
    touch(filing)
    filing["status"] = "PAID"
    contract = db["contracts"].get(filing["contract_id"])
    if contract is not None:
        recompute_aggregate_row(contract)
    return success_object(public(reimb))
