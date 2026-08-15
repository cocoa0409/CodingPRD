"""FundingRequestLine endpoints (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_CONTRACT_NOT_CERTIFIED,
    ERR_CROSS_ENTITY_MISMATCH, ERR_CONTRACT_CAPACITY_EXCEEDED,
)
from middleware import get_caller, check_role, check_applicant_scope
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record
from validate import (
    get_body, check_allowed, req_str, req_int, require_ref,
)

bp = Blueprint("funding_request_lines", __name__, url_prefix="/erate")

CREATE_FIELDS = {"funding_request_id", "contract_id", "eligible_service_id",
                 "requested_pre_discount_cents"}


@bp.post("/funding-request-lines")
def create_line():
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    body = get_body()
    # Tier 3 ownership via the funding request's applicant chain.
    raw_request_id = body.get("funding_request_id")
    if isinstance(raw_request_id, str):
        req = db["funding_requests"].get(raw_request_id)
        if req is not None:
            check_applicant_scope(caller, req["applicant_id"])
    check_allowed(body, CREATE_FIELDS)
    funding_request_id = req_str(body, "funding_request_id")
    contract_id = req_str(body, "contract_id")
    eligible_service_id = req_str(body, "eligible_service_id")
    requested = req_int(body, "requested_pre_discount_cents", positive=True)
    # Existence in declared body order.
    freq = require_ref("funding_requests", funding_request_id, "funding_request_id")
    contract = require_ref("contracts", contract_id, "contract_id")
    service = require_ref("eligible_services", eligible_service_id, "eligible_service_id")
    # State gates.
    if freq["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "lines may only be added while the request is DRAFT")
    if contract["status"] != "CERTIFIED":
        raise_error(ERR_CONTRACT_NOT_CERTIFIED, "contract is not CERTIFIED")
    # Cross-entity referential consistency.
    if contract["applicant_id"] != freq["applicant_id"]:
        raise_error(ERR_CROSS_ENTITY_MISMATCH,
                    "contract applicant differs from the request applicant")
    if service["funding_cycle_id"] != freq["funding_cycle_id"]:
        raise_error(ERR_CROSS_ENTITY_MISMATCH,
                    "eligible service is not in the request's funding cycle inventory")
    if contract["category"] != service["category"]:
        raise_error(ERR_CROSS_ENTITY_MISMATCH,
                    "contract category differs from the service's category")
    # Fiscal guard last: contract eligible-cost capacity across its lines.
    consumed = sum(
        l["requested_pre_discount_cents"]
        for l in db["funding_request_lines"].values()
        if l["contract_id"] == contract_id and l["status"] != "CANCELLED"
    )
    if consumed + requested > contract["total_eligible_cents"]:
        raise_error(ERR_CONTRACT_CAPACITY_EXCEEDED,
                    "line requests would exceed the contract's eligible cost ceiling")
    rec = new_record("funding_request_lines", {
        "funding_request_id": funding_request_id,
        "contract_id": contract_id,
        "eligible_service_id": eligible_service_id,
        "category": service["category"],  # copied at creation, immutable thereafter
        "requested_pre_discount_cents": requested,
        "committed_pre_discount_cents": 0,
        "committed_share_cents": 0,
        "reimbursed_cents": 0,
        "remaining_reimbursable_cents": 0,
        "invoice_deadline_date": None,
        "status": "PENDING",
        "denial_reason": None,
    })
    return success_object(public(rec), 201)


@bp.get("/funding-request-lines")
def list_lines():
    return list_collection("funding_request_lines", {
        "funding_request_id": request.args.get("funding_request_id"),
        "contract_id": request.args.get("contract_id"),
        "eligible_service_id": request.args.get("eligible_service_id"),
        "status": request.args.get("status"),
    })


@bp.get("/funding-request-lines/<rid>")
def get_line(rid):
    return get_one("funding_request_lines", rid)
