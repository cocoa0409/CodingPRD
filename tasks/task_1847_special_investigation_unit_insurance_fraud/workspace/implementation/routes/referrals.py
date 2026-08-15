"""Red-flag referral endpoints (PRD §3.2): intake, scoring, triage, disposition."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CLAIM_ALREADY_UNDER_SIU,
    ERR_CASE_ALREADY_OPEN,
    ERR_DUPLICATE_LINK_INVALID,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_case, pub_referral
from services.cascade import claim_put_under_review, non_terminal_case_for_claim
from services.scoring import compute_referral_score
from constants import CODE_WEIGHT, SUBMITTED_BY_ROLES
from util import (
    apply_filters,
    fk_or_404,
    get_json_body,
    optional_field,
    page_of,
    parse_pagination,
    path_or_404,
    require_enum,
    require_string,
    require_string_list,
    sort_created,
)

bp = Blueprint("referrals", __name__)


def _new_case_from_referral(referral: dict) -> dict:
    now = db.clock.now
    case = {
        "claim_id": referral["claim_id"],
        "opened_by_referral_id": referral["id"],
        "case_number": db.mint_case_number(now),
        "status": "INTAKE",
        "priority": referral.get("score_band"),
        "suspicion_score": referral.get("suspicion_score"),
        "investigation_deadline_at": None,
        "decision_due_at": None,
        "assigned_investigator_id": None,
        "substantiated_fraud_cents": 0,
        "euo_required": False,
        "bureau_referral_required": False,
        "closed_reason": None,
        "_no_show_total": 0,
    }
    db.stamp_new(case)
    db.cases[case["id"]] = case
    return case


@bp.post("/siu/referrals")
@require_roles("Adjuster", "SIUInvestigator")
def create_referral(_user_id: str, _role: str):
    body = get_json_body()
    claim_id = require_string(body, "claim_id")
    submitted_by_role = require_enum(body, "submitted_by_role", SUBMITTED_BY_ROLES)
    red_flag_codes = require_string_list(body, "red_flag_codes", allowed=set(CODE_WEIGHT))
    narrative = require_string(body, "narrative")
    claim = fk_or_404(db.claims, claim_id, "Claim")
    score, band = compute_referral_score(red_flag_codes, claim)
    referral = {
        "claim_id": claim["id"],
        "submitted_by_role": submitted_by_role,
        "red_flag_codes": red_flag_codes,
        "narrative": narrative,
        "suspicion_score": score,
        "score_band": band,
        "status": "SUBMITTED",
        "decline_reason": None,
        "duplicate_of_referral_id": None,
    }
    db.stamp_new(referral)
    db.referrals[referral["id"]] = referral
    return success_object(pub_referral(referral), 201)


@bp.get("/siu/referrals/<referralId>")
@require_roles("All")
def get_referral(referralId: str, _user_id: str, _role: str):
    referral = path_or_404(db.referrals, referralId, "RedFlagReferral")
    return success_object(pub_referral(referral))


@bp.get("/siu/referrals")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def list_referrals(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(
        list(db.referrals.values()),
        ["status", "claim_id", "score_band", "duplicate_of_referral_id"],
    )
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_referral(r) for r in page], limit, offset, total)


@bp.post("/siu/referrals/<referralId>/triage")
@require_roles("SIUManager")
def triage_referral(referralId: str, _user_id: str, _role: str):
    body = get_json_body()
    modifier_overrides = optional_field(body, "modifier_overrides")
    if modifier_overrides is not None:
        if not isinstance(modifier_overrides, dict):
            raise_err(ERR_INVALID_REQUEST, "Field modifier_overrides must be an object")
        for key, value in modifier_overrides.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise_err(ERR_INVALID_REQUEST, "modifier_overrides values must be integers")
    referral = path_or_404(db.referrals, referralId, "RedFlagReferral")
    if referral.get("status") != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Referral must be SUBMITTED to be triaged")
    claim = db.claims.get(referral.get("claim_id")) or {}
    score, band = compute_referral_score(
        referral.get("red_flag_codes") or [], claim, modifier_overrides=modifier_overrides
    )
    referral["suspicion_score"] = score
    referral["score_band"] = band
    referral["status"] = "TRIAGED"
    db.touch(referral)
    return success_object(pub_referral(referral))


@bp.post("/siu/referrals/<referralId>/accept")
@require_roles("SIUManager")
def accept_referral(referralId: str, _user_id: str, _role: str):
    get_json_body()
    referral = path_or_404(db.referrals, referralId, "RedFlagReferral")
    if referral.get("status") != "TRIAGED":
        raise_err(ERR_INVALID_STATE, "Referral must be TRIAGED to be accepted")
    claim = db.claims.get(referral.get("claim_id"))
    if claim is None:
        raise_err(ERR_INVALID_STATE, "Referral claim is missing")
    # State group (§2.6 rung 5): the claim must still be PENDING.
    if claim.get("status") != "PENDING":
        raise_err(ERR_CLAIM_ALREADY_UNDER_SIU, "Claim is already under SIU review or beyond")
    # Business constraint (rung 7): at most one non-terminal case per claim.
    if non_terminal_case_for_claim(claim["id"]) is not None:
        raise_err(ERR_CASE_ALREADY_OPEN, "A non-terminal SIU case already exists for this claim")
    case = _new_case_from_referral(referral)
    referral["status"] = "ACCEPTED"
    db.touch(referral)
    claim_put_under_review(claim)
    return success_object(pub_case(case), 201)


@bp.post("/siu/referrals/<referralId>/decline")
@require_roles("SIUManager")
def decline_referral(referralId: str, _user_id: str, _role: str):
    body = get_json_body()
    decline_reason = require_string(body, "decline_reason")
    referral = path_or_404(db.referrals, referralId, "RedFlagReferral")
    if referral.get("status") != "TRIAGED":
        raise_err(ERR_INVALID_STATE, "Referral must be TRIAGED to be declined")
    referral["status"] = "DECLINED"
    referral["decline_reason"] = decline_reason
    db.touch(referral)
    return success_object(pub_referral(referral))


@bp.post("/siu/referrals/<referralId>/link-duplicate")
@require_roles("SIUManager")
def link_duplicate(referralId: str, _user_id: str, _role: str):
    body = get_json_body()
    duplicate_of = require_string(body, "duplicate_of_referral_id")
    referral = path_or_404(db.referrals, referralId, "RedFlagReferral")
    target = fk_or_404(db.referrals, duplicate_of, "RedFlagReferral")
    if referral.get("status") != "TRIAGED":
        raise_err(ERR_INVALID_STATE, "Referral must be TRIAGED to be linked")
    if target.get("status") != "ACCEPTED" or target.get("claim_id") != referral.get("claim_id"):
        raise_err(
            ERR_DUPLICATE_LINK_INVALID,
            "duplicate_of must reference an ACCEPTED referral for the same claim",
        )
    referral["status"] = "DUPLICATE_LINKED"
    referral["duplicate_of_referral_id"] = target["id"]
    db.touch(referral)
    return success_object(pub_referral(referral))
