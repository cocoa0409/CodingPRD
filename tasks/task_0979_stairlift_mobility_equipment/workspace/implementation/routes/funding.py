"""FundingApplication endpoints."""

from flask import Blueprint, request

import db
from errors import (ApiError, err_not_found, err_invalid_request,
                    err_invalid_state, err_unauthorized)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import (stamp_new, touch, serialize, audit,
                           recompute_customer_outstanding)
# touch is used for funding application + agreement version bumps
from services.calculations import funding_waterfall

bp = Blueprint("funding", __name__)


@bp.post("/stairlift-ops/quotes/<qid>/funding-applications")
def create_funding_application(qid):
    user_id, role = require_role("Customer", "FundingOfficer", "PlatformAdmin")
    quote = db.quotes.get(qid)
    if quote is None:
        raise err_not_found("Quote not found")
    if role == "Customer" and user_id != quote["customer_id"]:
        raise err_unauthorized()
    body = get_json_body(["source_kind", "requested_cents", "priority_rank"])
    source_kind = body["source_kind"]
    requested = body["requested_cents"]
    rank = body["priority_rank"]
    if source_kind not in ("STATE_GRANT", "INSURANCE", "CHARITY",
                           "VETERAN_BENEFIT"):
        raise err_invalid_request("source_kind invalid")
    for name, v in (("requested_cents", requested), ("priority_rank", rank)):
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_invalid_request(f"{name} must be an integer")
    fa = {
        "quote_id": qid,
        "source_kind": source_kind,
        "requested_cents": requested,
        "status": "PENDING",
        "approved_cents": 0,
        "decision_reason": None,
        "priority_rank": rank,
    }
    stamp_new(fa)
    db.funding_applications[fa["id"]] = fa
    return success_object(serialize(fa), 201)


@bp.get("/stairlift-ops/quotes/<qid>/funding-applications")
def list_funding_applications(qid):
    user_id, role = require_role("PlatformAdmin", "FundingOfficer", "Customer",
                                 "SalesRep")
    quote = db.quotes.get(qid)
    if quote is None:
        raise err_not_found("Quote not found")
    if role == "Customer" and user_id != quote["customer_id"]:
        raise err_unauthorized()
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = sorted(
        (f for f in db.funding_applications.values() if f["quote_id"] == qid),
        key=lambda f: f["created_at"])
    if status:
        items = [f for f in items if f["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(f) for f in page], limit, offset, total)


@bp.get("/stairlift-ops/funding-applications/<fid>")
def get_funding_application(fid):
    user_id, role = require_role("PlatformAdmin", "FundingOfficer", "Customer")
    fa = db.funding_applications.get(fid)
    if fa is None:
        raise err_not_found("FundingApplication not found")
    if role == "Customer":
        quote = db.quotes.get(fa["quote_id"])
        if quote is None or user_id != quote["customer_id"]:
            raise err_unauthorized()
    return success_object(serialize(fa))


@bp.post("/stairlift-ops/funding-applications/<fid>/decide")
def decide_funding_application(fid):
    user_id, role = require_role("FundingOfficer")
    fa = db.funding_applications.get(fid)
    if fa is None:
        raise err_not_found("FundingApplication not found")
    if fa["status"] != "PENDING":
        raise err_invalid_state("FundingApplication must be PENDING to decide")
    body = get_json_body(["decision", "decision_reason"])
    decision = body["decision"]
    reason = body["decision_reason"]
    if decision not in ("APPROVED", "PARTIALLY_APPROVED", "DENIED"):
        raise err_invalid_request("decision invalid")
    if not isinstance(reason, str) or not reason:
        raise err_invalid_request("decision_reason required")
    approved_cents = body.get("approved_cents")
    if decision == "APPROVED":
        if approved_cents is None:
            approved_cents = fa["requested_cents"]
        if isinstance(approved_cents, bool) or not isinstance(approved_cents, int):
            raise err_invalid_request("approved_cents must be an integer")
        if approved_cents != fa["requested_cents"]:
            raise err_invalid_request(
                "Full approval requires approved_cents == requested_cents")
        fa["status"] = "APPROVED"
        fa["approved_cents"] = approved_cents
    elif decision == "PARTIALLY_APPROVED":
        if approved_cents is None or isinstance(approved_cents, bool) \
                or not isinstance(approved_cents, int):
            raise err_invalid_request("approved_cents must be an integer")
        if not (0 < approved_cents < fa["requested_cents"]):
            raise err_invalid_request(
                "Partial approval requires 0 < approved_cents < requested_cents")
        fa["status"] = "PARTIALLY_APPROVED"
        fa["approved_cents"] = approved_cents
    else:  # DENIED
        fa["status"] = "DENIED"
        fa["approved_cents"] = 0
    fa["decision_reason"] = reason
    touch(fa)
    audit("FundingApplication", fa["id"], "FUNDING_DECIDED", role,
          {"decision": decision})
    # recompute waterfall on the parent agreement (if one exists for the quote)
    for ag in db.agreements.values():
        if ag["quote_id"] == fa["quote_id"]:
            transitioned = funding_waterfall(ag)
            if transitioned:
                audit("Agreement", ag["id"], "AGREEMENT_FUNDED", "system",
                      {"to": "FUNDED"})
            recompute_customer_outstanding(ag["customer_id"])
            break
    return success_object(serialize(fa))
