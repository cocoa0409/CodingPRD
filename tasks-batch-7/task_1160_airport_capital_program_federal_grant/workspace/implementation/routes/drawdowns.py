"""Reimbursement requests (drawdowns)."""
from flask import Blueprint, g, request

from auth import ALL_ROLES, require
from domain import drawdown_amounts, ser_reimbursement
from errors import ApiError, err_invalid_state, err_validation
from store import DB
from util import (body, get_or_404, new_entity, respond, respond_list, touch)

bp = Blueprint("drawdowns", __name__)


def _get_request(rid):
    return get_or_404(DB.reimbursements, rid, "ReimbursementRequest")


@bp.route("/aip/reimbursement-requests", methods=["POST"])
@require("FinanceOfficer")
def create_drawdown():
    b = body()
    if "grant_id" not in b or b["grant_id"] is None:
        raise err_validation("Missing required field: grant_id")
    grant = get_or_404(DB.grants, b["grant_id"], "Grant")
    if "invoice_ids" not in b or b["invoice_ids"] is None:
        raise err_validation("Missing required field: invoice_ids")
    invoice_ids = b["invoice_ids"]
    if not isinstance(invoice_ids, list):
        raise err_validation("invoice_ids must be an array")
    invoices = []
    for iid in invoice_ids:
        invoices.append(get_or_404(DB.invoices, iid, "Invoice"))
    if len(invoice_ids) == 0 or len(set(invoice_ids)) != len(invoice_ids):
        raise ApiError("ERR_EMPTY_SELECTION", 422,
                       "invoice_ids must be non-empty with no duplicates")
    for inv in invoices:
        contract = DB.contracts.get(inv["contract_id"])
        if inv["status"] != "VERIFIED" or contract is None or \
                contract["grant_id"] != grant["id"]:
            raise ApiError("ERR_INVOICE_NOT_VERIFIABLE", 422,
                           "Every invoice must be VERIFIED and on a contract "
                           "of this grant")
    total_net, federal = drawdown_amounts(
        invoices, grant["federal_share_pct_dec"])
    req = new_entity()
    req.update({"grant_id": grant["id"], "invoice_ids": list(invoice_ids),
                "total_net": total_net, "federal_amount": federal,
                "prepared_by_user_id": g.user_id,
                "certified_by_user_id": None, "status": "DRAFT"})
    DB.reimbursements[req["id"]] = req
    for inv in invoices:
        inv["status"] = "INCLUDED"
        inv["drawdown_id"] = req["id"]
        touch(inv)
    return respond(ser_reimbursement(req), 201)


@bp.route("/aip/reimbursement-requests", methods=["GET"])
@require(*ALL_ROLES)
def list_drawdowns():
    items = list(DB.reimbursements.values())
    grant_id = request.args.get("grant_id")
    status = request.args.get("status")
    if grant_id is not None:
        items = [r for r in items if r["grant_id"] == grant_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return respond_list(items, ser_reimbursement)


@bp.route("/aip/reimbursement-requests/<requestId>", methods=["GET"])
@require(*ALL_ROLES)
def get_drawdown(requestId):
    return respond(ser_reimbursement(_get_request(requestId)))


@bp.route("/aip/reimbursement-requests/<requestId>/certify", methods=["POST"])
@require("ComplianceOfficer")
def certify_drawdown(requestId):
    req = _get_request(requestId)
    if req["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT drawdown can be certified")
    if g.user_id == req["prepared_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Drawdown certifier must differ from the preparer")
    req["certified_by_user_id"] = g.user_id
    req["status"] = "CERTIFIED"
    touch(req)
    return respond(ser_reimbursement(req))


@bp.route("/aip/reimbursement-requests/<requestId>/submit", methods=["POST"])
@require("FinanceOfficer")
def submit_drawdown(requestId):
    req = _get_request(requestId)
    if req["status"] != "CERTIFIED":
        raise err_invalid_state("Only a CERTIFIED drawdown can be submitted")
    grant = DB.grants[req["grant_id"]]
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE", 409,
                       "Drawdown submission requires an ACTIVE grant")
    for iid in req["invoice_ids"]:
        inv = DB.invoices.get(iid)
        contract = DB.contracts.get(inv["contract_id"]) if inv else None
        if inv is None or inv["status"] != "INCLUDED" or \
                (contract and contract["dbe_posture"] == "NON_COMPLIANT"):
            raise ApiError("ERR_PAYMENTS_WITHHELD_DBE", 422,
                           "An included invoice is withheld or its contract "
                           "is DBE NON_COMPLIANT")
    available = grant["federal_obligated"] - grant["federal_drawn"]
    if req["federal_amount"] > available:
        raise ApiError("ERR_FEDERAL_FUNDS_INSUFFICIENT", 402,
                       "federal_amount exceeds grant.federal_available")
    req["status"] = "SUBMITTED"
    touch(req)
    return respond(ser_reimbursement(req))


@bp.route("/aip/reimbursement-requests/<requestId>/approve", methods=["POST"])
@require("FAAManager")
def approve_drawdown(requestId):
    req = _get_request(requestId)
    if req["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED drawdown can be approved")
    grant = DB.grants[req["grant_id"]]
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE", 409,
                       "Drawdown approval requires an ACTIVE grant")
    available = grant["federal_obligated"] - grant["federal_drawn"]
    if req["federal_amount"] > available:
        raise ApiError("ERR_FEDERAL_FUNDS_INSUFFICIENT", 402,
                       "federal_amount exceeds grant.federal_available")
    req["status"] = "APPROVED"
    touch(req)
    grant["federal_drawn"] += req["federal_amount"]
    touch(grant)
    for iid in req["invoice_ids"]:
        inv = DB.invoices.get(iid)
        if inv is not None and inv["status"] == "INCLUDED":
            inv["status"] = "PAID"
            touch(inv)
    return respond(ser_reimbursement(req))


@bp.route("/aip/reimbursement-requests/<requestId>/return", methods=["POST"])
@require("FAAManager")
def return_drawdown(requestId):
    req = _get_request(requestId)
    if req["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED drawdown can be returned")
    req["status"] = "DRAFT"
    req["certified_by_user_id"] = None
    touch(req)
    return respond(ser_reimbursement(req))
