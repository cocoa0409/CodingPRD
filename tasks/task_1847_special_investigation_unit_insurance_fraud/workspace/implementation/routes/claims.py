"""Claim endpoints (PRD §3.1).

Payment coordination is statutory: delay is permitted only while the linked
case is actively investigated, and delay_until is capped per state.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_CASE_NOT_IN_REQUIRED_STATE,
    ERR_DELAY_WINDOW_EXCEEDED,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_case, pub_claim, pub_referral
from services.cascade import cases_for_claim, non_terminal_case_for_claim
from services.scoring import delay_cap_until
from util import (
    apply_filters,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    fk_or_404,
    require_int,
    require_state_code,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("claims", __name__)


@bp.post("/siu/claims")
@require_roles("Adjuster")
def create_claim(_user_id: str, _role: str):
    body = get_json_body()
    policy_number = require_string(body, "policy_number")
    state_code = require_state_code(body, "state_code")
    adjuster_id = require_string(body, "adjuster_id")
    claimed_amount_cents = require_int(body, "claimed_amount_cents")
    fk_or_404(db.adjusters, adjuster_id, "Adjuster")
    claim = {
        "policy_number": policy_number,
        "state_code": state_code,
        "adjuster_id": adjuster_id,
        "claimed_amount_cents": claimed_amount_cents,
        "status": "PENDING",
        "payment_hold_reason": None,
        "paid_amount_cents": 0,
    }
    db.stamp_new(claim)
    db.claims[claim["id"]] = claim
    return success_object(pub_claim(claim), 201)


@bp.get("/siu/claims/<claimId>")
@require_roles("All")
def get_claim(claimId: str, _user_id: str, _role: str):
    claim = path_or_404(db.claims, claimId, "Claim")
    return success_object(pub_claim(claim))


@bp.get("/siu/claims")
@require_roles("All")
def list_claims(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.claims.values()), ["status", "state_code", "adjuster_id"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_claim(c) for c in page], limit, offset, total)


@bp.post("/siu/claims/<claimId>/pay")
@require_roles("Adjuster")
def pay_claim(claimId: str, _user_id: str, _role: str):
    get_json_body()
    claim = path_or_404(db.claims, claimId, "Claim")
    # Rung 5: the claim itself must be PENDING.
    if claim.get("status") != "PENDING":
        raise_err(ERR_INVALID_STATE, "Claim must be PENDING to be paid")
    # Rung 6: a non-terminal case blocks payment.
    if non_terminal_case_for_claim(claim["id"]) is not None:
        raise_err(ERR_CASE_NOT_IN_REQUIRED_STATE, "A non-terminal SIU case exists for this claim")
    claim["status"] = "PAID"
    claim["paid_amount_cents"] = int(claim.get("claimed_amount_cents", 0))
    db.touch(claim)
    return success_object(pub_claim(claim))


@bp.post("/siu/claims/<claimId>/close-claim")
@require_roles("Adjuster")
def close_claim(claimId: str, _user_id: str, _role: str):
    get_json_body()
    claim = path_or_404(db.claims, claimId, "Claim")
    if claim.get("status") != "PENDING":
        raise_err(ERR_INVALID_STATE, "Claim must be PENDING to be closed")
    claim["status"] = "CLOSED"
    db.touch(claim)
    return success_object(pub_claim(claim))


@bp.post("/siu/claims/<claimId>/delay-payment")
@require_roles("Adjuster")
def delay_payment(claimId: str, _user_id: str, _role: str):
    body = get_json_body()
    delay_until = require_ts(body, "delay_until")
    require_string(body, "reason")
    claim = path_or_404(db.claims, claimId, "Claim")
    if claim.get("status") != "UNDER_SIU_REVIEW":
        raise_err(ERR_INVALID_STATE, "Claim must be UNDER_SIU_REVIEW to delay payment")
    # The statutory window is enforced against the logical clock; an excessive
    # delay_until is rejected ERR_DELAY_WINDOW_EXCEEDED.
    requested = db.parse_instant(delay_until)
    cap_until = delay_cap_until(claim.get("state_code"), db.clock.now)
    if requested > cap_until:
        raise_err(ERR_DELAY_WINDOW_EXCEEDED, "delay_until exceeds the state statutory cap")
    # The claim's case must be actively investigated.
    case = non_terminal_case_for_claim(claim["id"])
    if case is None or case.get("status") not in ("UNDER_INVESTIGATION", "EUO_PENDING", "DECISION_PENDING"):
        raise_err(
            ERR_CASE_NOT_IN_REQUIRED_STATE,
            "Case must be UNDER_INVESTIGATION, EUO_PENDING, or DECISION_PENDING",
        )
    claim["status"] = "PAYMENT_DELAYED"
    db.touch(claim)
    return success_object(pub_claim(claim))


@bp.post("/siu/claims/<claimId>/release-delay")
@require_roles("Adjuster")
def release_delay(claimId: str, _user_id: str, _role: str):
    get_json_body()
    claim = path_or_404(db.claims, claimId, "Claim")
    if claim.get("status") != "PAYMENT_DELAYED":
        raise_err(ERR_INVALID_STATE, "Claim must be PAYMENT_DELAYED to release the delay")
    claim["status"] = "UNDER_SIU_REVIEW"
    db.touch(claim)
    return success_object(pub_claim(claim))


@bp.get("/siu/claims/<claimId>/cases")
@require_roles("All")
def list_claim_cases(claimId: str, _user_id: str, _role: str):
    claim = path_or_404(db.claims, claimId, "Claim")
    limit, offset = parse_pagination()
    items = sort_created(cases_for_claim(claim["id"]))
    page, total = page_of(items, limit, offset)
    return success_list([pub_case(c) for c in page], limit, offset, total)


@bp.get("/siu/claims/<claimId>/referrals")
@require_roles("All")
def list_claim_referrals(claimId: str, _user_id: str, _role: str):
    claim = path_or_404(db.claims, claimId, "Claim")
    limit, offset = parse_pagination()
    items = sort_created(
        [r for r in db.referrals.values() if r.get("claim_id") == claim["id"]]
    )
    page, total = page_of(items, limit, offset)
    return success_list([pub_referral(r) for r in page], limit, offset, total)
