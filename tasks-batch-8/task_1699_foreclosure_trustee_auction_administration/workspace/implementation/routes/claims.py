"""SurplusClaim routes: filing (claims window), list, review (SoD).

Filing order (PRD §3.9): schema (filed_date == clock date) -> case state
(SOLD|DEED_RECORDED) -> claims deadline (close + 180d).
Review order: schema -> claim FILED (derived) -> reviewer != filer (SoD,
before any decision is examined) -> decision value checks.
"""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import stamp_new, touch
from errors import (err_invalid_request, err_invalid_case_state,
                    err_invalid_claim_state, err_claims_deadline,
                    err_segregation)
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services import calc
from services.domain import (get_case, get_claim, view, claim_view,
                             claim_derived_status, case_claims, closed_sale)
from services.validate import (get_body, check_unknown, req_string, req_int,
                               req_enum, req_date, opt_string)
from util import format_date

bp = Blueprint("claims", __name__)

CLAIMANT_TYPES = ("JUNIOR_LIENHOLDER", "BORROWER", "JUDGMENT_CREDITOR")
CLAIMABLE_STATES = ("SOLD", "DEED_RECORDED")


@bp.route("/api/foreclosure-cases/<case_id>/surplus-claims", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def file_claim(user_id, role, case_id):
    case = get_case(case_id)
    body = get_body()
    check_unknown(body, {"claimant_name", "claimant_type", "priority_rank",
                         "claimed_amount_cents", "filed_date"})
    claimant_name = req_string(body, "claimant_name")
    claimant_type = req_enum(body, "claimant_type", CLAIMANT_TYPES)
    # no documented minimum on priority_rank (tier 1 is senior-most; any
    # integer is a valid tier label)
    priority_rank = req_int(body, "priority_rank")
    claimed = req_int(body, "claimed_amount_cents", minimum=1)
    filed_date = req_date(body, "filed_date")
    # clock consistency (§2.5): filed_date must equal the clock date
    if filed_date != db.CLOCK.now_date():
        raise err_invalid_request("filed_date must equal the current clock date")
    # the case-state check runs before the deadline check (PRD §3.9)
    if case["lifecycle_status"] not in CLAIMABLE_STATES:
        raise err_invalid_case_state("claims require the case in SOLD or DEED_RECORDED")
    sale = closed_sale(case["id"])
    if sale is None or not sale.get("closed_at"):
        raise err_invalid_case_state("no closed sale on the case")
    close_date = db._parse_iso(sale["closed_at"]).date()
    if filed_date > close_date + timedelta(days=calc.CLAIMS_WINDOW_DAYS):
        # filing exactly on the 180th day is acceptable
        raise err_claims_deadline()
    claim = {
        "foreclosure_case_id": case["id"],
        "claimant_name": claimant_name,
        "claimant_type": claimant_type,
        "priority_rank": priority_rank,
        "claimed_amount_cents": claimed,
        "filed_date": format_date(filed_date),
        "approved_amount_cents": None,
        "paid_cents": 0,
        "status": "FILED",
        "denial_reason": None,
        "filed_by_user_id": user_id,  # segregation-of-duties anchor
    }
    stamp_new(claim)
    db.surplus_claims[claim["id"]] = claim
    return success_object(claim_view(claim), status=201)


@bp.route("/api/foreclosure-cases/<case_id>/surplus-claims", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Beneficiary")
def list_claims(user_id, role, case_id):
    get_case(case_id)
    items = case_claims(case_id)
    status = request.args.get("status")
    if status is not None:
        # filters match the surfaced (derived) status
        items = [c for c in items if claim_derived_status(c) == status]
    limit, offset = parse_pagination(request.args)
    page = [claim_view(c) for c in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/surplus-claims/<claim_id>/review", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def review_claim(user_id, role, claim_id):
    claim = get_claim(claim_id)
    body = get_body()
    check_unknown(body, {"decision", "approved_amount_cents", "denial_reason"})
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    approved_amount = body.get("approved_amount_cents")
    denial_reason = opt_string(body, "denial_reason")
    if claim_derived_status(claim) != "FILED":
        raise err_invalid_claim_state("claim is not FILED")
    # segregation of duties: rejected before any decision is examined
    if user_id == claim["filed_by_user_id"]:
        raise err_segregation()
    if decision == "APPROVE":
        if isinstance(approved_amount, bool) or not isinstance(approved_amount, int):
            raise err_invalid_request("approved_amount_cents is required for APPROVE")
        if approved_amount <= 0 or approved_amount > claim["claimed_amount_cents"]:
            raise err_invalid_request("approved_amount_cents must be > 0 and <= claimed_amount_cents")
        claim["approved_amount_cents"] = approved_amount
        claim["status"] = "APPROVED"
        touch(claim)
    else:  # DENY
        if denial_reason is None or denial_reason.strip() == "":
            raise err_invalid_request("denial_reason must be non-empty for DENY")
        claim["status"] = "DENIED"
        claim["denial_reason"] = denial_reason
        touch(claim)
    return success_object(claim_view(claim))
