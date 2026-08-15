"""Contract endpoints: drafting, certification with SoD, termination cascade (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_BID_NOT_AWARDED, ERR_CROSS_ENTITY_MISMATCH, ERR_CONTRACT_TERM_OVERLAP,
    ERR_SOD_CONTRACT_CERTIFIER,
)
from middleware import get_caller, check_role, check_applicant_scope
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record, touch, retain_document, recompute_request_total
from util import CLOCK, parse_date
from validate import (
    get_body, check_allowed, req_str, req_int, req_enum, req_date,
    require_ref, require_path_resource,
)

bp = Blueprint("contracts", __name__, url_prefix="/erate")

CATEGORIES = ("CATEGORY_ONE", "CATEGORY_TWO")

CREATE_FIELDS = {"applicant_id", "service_provider_id", "posting_id",
                 "winning_bid_id", "category", "total_eligible_cents",
                 "service_start_date", "service_end_date"}


def _terms_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap: a shared endpoint date counts as overlap."""
    return a_start <= b_end and b_start <= a_end


def _certified_overlap_exists(applicant_id, provider_id, category, start, end,
                              exclude_contract_id=None):
    for other in db["contracts"].values():
        if exclude_contract_id is not None and other["id"] == exclude_contract_id:
            continue
        if other["status"] != "CERTIFIED":
            continue
        if (other["applicant_id"] == applicant_id
                and other["service_provider_id"] == provider_id
                and other["category"] == category
                and _terms_overlap(parse_date(start), parse_date(end),
                                   parse_date(other["service_start_date"]),
                                   parse_date(other["service_end_date"]))):
            return True
    return False


@bp.post("/contracts")
def create_contract():
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    body = get_body()
    raw_applicant = body.get("applicant_id")
    if isinstance(raw_applicant, str):
        check_applicant_scope(caller, raw_applicant)
    check_allowed(body, CREATE_FIELDS)
    applicant_id = req_str(body, "applicant_id")
    service_provider_id = req_str(body, "service_provider_id")
    posting_id = req_str(body, "posting_id")
    winning_bid_id = req_str(body, "winning_bid_id")
    category = req_enum(body, "category", CATEGORIES)
    total_eligible_cents = req_int(body, "total_eligible_cents", positive=True)
    service_start_date = req_date(body, "service_start_date")
    service_end_date = req_date(body, "service_end_date")
    if parse_date(service_end_date) < parse_date(service_start_date):
        raise_error(ERR_INVALID_REQUEST,
                    "service_end_date precedes service_start_date")
    # Existence, in declared body order.
    require_ref("applicants", applicant_id, "applicant_id")
    require_ref("service_providers", service_provider_id, "service_provider_id")
    posting = require_ref("procurement_postings", posting_id, "posting_id")
    bid = require_ref("bids", winning_bid_id, "winning_bid_id")
    # Tier-4 check deferred until refs resolve: ceiling equals the winning bid price.
    if total_eligible_cents != bid["eligible_price_cents"]:
        raise_error(ERR_INVALID_REQUEST,
                    "total_eligible_cents differs from the winning bid's eligible price")
    # State gate: the posting must be AWARDED.
    if posting["status"] != "AWARDED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "posting is not AWARDED")
    # Structural: closed-interval term overlap vs other CERTIFIED contracts.
    if _certified_overlap_exists(applicant_id, service_provider_id, category,
                                 service_start_date, service_end_date):
        raise_error(ERR_CONTRACT_TERM_OVERLAP,
                    "term overlaps a CERTIFIED contract for the same applicant, provider and category")
    # Cross-entity referential consistency.
    if winning_bid_id != posting["selected_bid_id"]:
        raise_error(ERR_BID_NOT_AWARDED,
                    "winning_bid_id differs from the posting's selected bid")
    if service_provider_id != bid["service_provider_id"]:
        raise_error(ERR_CROSS_ENTITY_MISMATCH,
                    "service_provider_id is not the winning bid's provider")
    if category != posting["category"]:
        raise_error(ERR_CROSS_ENTITY_MISMATCH,
                    "category differs from the posting's category")
    if applicant_id != posting["applicant_id"]:
        raise_error(ERR_CROSS_ENTITY_MISMATCH,
                    "applicant_id differs from the posting's applicant")
    rec = new_record("contracts", {
        "applicant_id": applicant_id,
        "service_provider_id": service_provider_id,
        "posting_id": posting_id,
        "winning_bid_id": winning_bid_id,
        "category": category,
        "total_eligible_cents": total_eligible_cents,
        "service_start_date": service_start_date,
        "service_end_date": service_end_date,
        "status": "DRAFT",
        "certified_date": None,
        "certified_by_user_id": None,
    })
    return success_object(public(rec), 201)


@bp.get("/contracts")
def list_contracts():
    return list_collection("contracts", {
        "applicant_id": request.args.get("applicant_id"),
        "service_provider_id": request.args.get("service_provider_id"),
        "posting_id": request.args.get("posting_id"),
        "winning_bid_id": request.args.get("winning_bid_id"),
        "status": request.args.get("status"),
    })


@bp.get("/contracts/<rid>")
def get_contract(rid):
    return get_one("contracts", rid)


@bp.post("/contracts/<rid>/certify")
def certify(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCertifier"])
    existing = db["contracts"].get(rid)
    if existing is not None:
        check_applicant_scope(caller, existing["applicant_id"])
    body = get_body()
    check_allowed(body, set())
    contract = require_path_resource("contracts", rid)
    if contract["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "contract is not DRAFT")
    posting = db["procurement_postings"][contract["posting_id"]]
    # Segregation of duties: the bid selector may not certify the contract.
    if caller.user_id == posting["selected_by_user_id"]:
        raise_error(ERR_SOD_CONTRACT_CERTIFIER,
                    "contract certifier must differ from the bid selector")
    # Re-check closed-interval term overlap at certification time.
    if _certified_overlap_exists(contract["applicant_id"],
                                 contract["service_provider_id"],
                                 contract["category"],
                                 contract["service_start_date"],
                                 contract["service_end_date"],
                                 exclude_contract_id=rid):
        raise_error(ERR_CONTRACT_TERM_OVERLAP,
                    "term overlaps a CERTIFIED contract for the same applicant, provider and category")
    contract["status"] = "CERTIFIED"
    contract["certified_date"] = CLOCK.today().isoformat()
    contract["certified_by_user_id"] = caller.user_id
    retain_document("CONTRACT", rid, posting["funding_cycle_id"],
                    "CONTRACT_CERTIFICATION")
    touch(contract)
    return success_object(public(contract))


@bp.post("/contracts/<rid>/terminate")
def terminate(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCertifier"])
    existing = db["contracts"].get(rid)
    if existing is not None:
        check_applicant_scope(caller, existing["applicant_id"])
    body = get_body()
    check_allowed(body, {"reason"})
    contract = require_path_resource("contracts", rid)
    if contract["status"] != "CERTIFIED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "contract is not CERTIFIED")
    contract["status"] = "TERMINATED"
    # LINK1: every PENDING/COMMITTED line on this contract -> CANCELLED.
    affected_request_ids = set()
    for line in db["funding_request_lines"].values():
        if line["contract_id"] != rid or line["status"] not in ("PENDING", "COMMITTED"):
            continue
        was_committed = line["status"] == "COMMITTED"
        line["status"] = "CANCELLED"
        line["denial_reason"] = "CONTRACT_TERMINATED"
        if was_committed:
            # remaining forced to 0; reimbursed preserved as historical record.
            line["remaining_reimbursable_cents"] = 0
        touch(line)
        affected_request_ids.add(line["funding_request_id"])
    # LINK2/LINK3: release is implicit (the committed ledger derives from
    # COMMITTED lines); recompute request totals; close emptied COMMITTED requests.
    for request_id in affected_request_ids:
        freq = db["funding_requests"][request_id]
        before = freq["committed_total_share_cents"]
        recompute_request_total(freq)
        total_changed = freq["committed_total_share_cents"] != before
        closes = (
            freq["status"] == "COMMITTED"
            and not any(l["status"] == "COMMITTED"
                        for l in db["funding_request_lines"].values()
                        if l["funding_request_id"] == request_id)
        )
        if closes:
            freq["status"] = "CLOSED"
        if total_changed or closes:
            touch(freq)
    posting = db["procurement_postings"][contract["posting_id"]]
    retain_document("CONTRACT", rid, posting["funding_cycle_id"],
                    "CONTRACT_TERMINATION")
    touch(contract)
    return success_object(public(contract))
