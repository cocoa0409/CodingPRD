"""Credit / refund claims (BAD_DEBT, EXPORT)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from errors import raise_err
from store import DB
from auth import (
    require_roles, ALL_READ_ROLES, body_dict, req_str, req_int, req_enum,
    req_str_list, new_entity, touch, get_or_404, public, paginate,
)
from response import success_object, success_list
from utiltime import now_dt
import services

bp = Blueprint("claims", __name__)

CLAIM_FIELDS = ["registration_id", "return_id", "claim_type", "claimed_cents",
                "event_ids", "justification", "submitted_by_user_id",
                "reviewed_by_user_id", "eligible_cents", "approved_cents",
                "applied_cents", "reversed_cents", "status"]


def ser_claim(c):
    return public(c, CLAIM_FIELDS)


@bp.post("/credit-claims")
def create_claim():
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    registration_id = req_str(body, "registration_id")
    return_id = req_str(body, "return_id")
    claim_type = req_enum(body, "claim_type", {"BAD_DEBT", "EXPORT"})
    claimed_cents = req_int(body, "claimed_cents", minimum=1)
    event_ids = req_str_list(body, "event_ids")
    justification = req_str(body, "justification")
    reg = get_or_404(DB.registrations, registration_id, "Registration")
    ret = get_or_404(DB.returns, return_id, "TaxReturn")
    events = [get_or_404(DB.events, eid, "TaxableEvent") for eid in event_ids]
    # Registrant-chain integrity first, then registration/jurisdiction alignment.
    ret_reg = DB.registrations[ret["registration_id"]]
    if ret_reg["registrant_id"] != reg["registrant_id"]:
        raise_err(errors.ERR_CROSS_REGISTRANT,
                  "The referenced return belongs to a different registrant chain")
    for e in events:
        if e["registration_id"] != registration_id:
            raise_err(errors.ERR_CROSS_REGISTRANT,
                      "A referenced event belongs to a different registrant chain")
    if ret["registration_id"] != registration_id:
        raise_err(errors.ERR_REG_JUR_MISMATCH,
                  "claim.return_id must belong to the claim's registration")
    claim = new_entity({
        "registration_id": registration_id,
        "return_id": return_id,
        "claim_type": claim_type,
        "claimed_cents": claimed_cents,
        "event_ids": list(event_ids),
        "justification": justification,
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "eligible_cents": 0,
        "approved_cents": None,
        "applied_cents": 0,
        "reversed_cents": 0,
        "status": "DRAFT",
        "_reversed_at": None,
    })
    DB.claims[claim["id"]] = claim
    return success_object(ser_claim(claim), 201)


@bp.get("/credit-claims/<cid>")
def get_claim(cid):
    require_roles(ALL_READ_ROLES)
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    return success_object(ser_claim(claim))


@bp.get("/credit-claims")
def list_claims():
    require_roles(ALL_READ_ROLES)
    items = list(DB.claims.values())
    for param in ("registration_id", "return_id", "status", "claim_type"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    data, limit, offset, total = paginate(items, ser_claim)
    return success_list(data, limit, offset, total)


@bp.post("/credit-claims/<cid>/submit")
def submit_claim(cid):
    uid, _role = require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    if claim["status"] != "DRAFT":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Claim in status {claim['status']} cannot be submitted")
    ret = DB.returns[claim["return_id"]]
    if ret["filing_status"] != "FILED":
        raise_err(errors.ERR_INVALID_STATE,
                  "The claim's return must be FILED before the claim is submitted")
    today = now_dt().date()
    filed_date = ret["_filed_dt"].date()
    if claim["claim_type"] == "BAD_DEBT" and today < filed_date + timedelta(days=services.MIN_AGE_DAYS):
        raise_err(errors.ERR_BAD_DEBT_TOO_EARLY,
                  "BAD_DEBT claims open 183 days after the return was filed")
    if today > filed_date + timedelta(days=services.MAX_AGE_DAYS):
        raise_err(errors.ERR_CLAIM_WINDOW_EXPIRED,
                  "The claim window (731 days after filing) has expired")
    events = [DB.events[eid] for eid in claim["event_ids"]]
    listed = set(claim["event_ids"])
    for other in DB.claims.values():
        if other["id"] == claim["id"]:
            continue
        if other["status"] in services.LIVE_CLAIM_STATUSES:
            if listed & set(other["event_ids"]):
                raise_err(errors.ERR_EVENT_ALREADY_CLAIMED,
                          "An event is already listed on another live claim")
    if claim["claim_type"] == "EXPORT":
        if any(not e["is_export"] for e in events):
            raise_err(errors.ERR_EXPORT_DOC_MISSING,
                      "EXPORT claims may only list events with is_export == true")
    eligible = sum(
        e["tax_cents"] for e in events
        if e["status"] in ("RETURNED", "ADJUSTED")
        and e["registration_id"] == claim["registration_id"]
        and e["jurisdiction_id"] == ret["jurisdiction_id"]
    )
    claim["eligible_cents"] = eligible
    claim["submitted_by_user_id"] = uid
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success_object(ser_claim(claim))


@bp.post("/credit-claims/<cid>/approve")
def approve_claim(cid):
    uid, _role = require_roles(["TaxReviewer", "ComplianceAdmin"])
    body = body_dict()
    approved_cents = req_int(body, "approved_cents", minimum=1)
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    if claim["status"] != "SUBMITTED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Claim in status {claim['status']} cannot be approved")
    if uid == claim["submitted_by_user_id"]:
        raise_err(errors.ERR_SOD,
                  "The approver must differ from the submitter (segregation of duties)")
    ceiling = min(claim["claimed_cents"], claim["eligible_cents"], services.CLAIM_CAP_CENTS)
    if approved_cents > ceiling:
        raise_err(errors.ERR_CLAIM_EXCEEDS_ELIGIBLE,
                  "approved_cents exceeds min(claimed, eligible, CLAIM_CAP)")
    claim["approved_cents"] = approved_cents
    claim["reviewed_by_user_id"] = uid
    claim["status"] = "APPROVED"
    touch(claim)
    return success_object(ser_claim(claim))


@bp.post("/credit-claims/<cid>/deny")
def deny_claim(cid):
    uid, _role = require_roles(["TaxReviewer", "ComplianceAdmin"])
    body = body_dict()
    req_str(body, "reason")
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    if claim["status"] != "SUBMITTED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Claim in status {claim['status']} cannot be denied")
    if uid == claim["submitted_by_user_id"]:
        raise_err(errors.ERR_SOD,
                  "The denier must differ from the submitter (segregation of duties)")
    claim["reviewed_by_user_id"] = uid
    claim["status"] = "DENIED"
    touch(claim)
    return success_object(ser_claim(claim))


@bp.post("/credit-claims/<cid>/resubmit")
def resubmit_claim(cid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    if claim["status"] != "DENIED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Claim in status {claim['status']} cannot be resubmitted")
    claim["status"] = "DRAFT"
    claim["submitted_by_user_id"] = None
    claim["reviewed_by_user_id"] = None
    claim["eligible_cents"] = 0
    touch(claim)
    return success_object(ser_claim(claim))


@bp.post("/credit-claims/<cid>/withdraw")
def withdraw_claim(cid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    if claim["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Claim in status {claim['status']} cannot be withdrawn")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return success_object(ser_claim(claim))


@bp.post("/credit-claims/<cid>/apply")
def apply_claim(cid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    if claim["status"] != "APPROVED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Claim in status {claim['status']} cannot be applied")
    ret = DB.returns[claim["return_id"]]
    jurisdiction = DB.jurisdictions[ret["jurisdiction_id"]]
    if services.audit_hold_blocks(ret["registration_id"], ret["jurisdiction_id"],
                                  ret["period"], jurisdiction["return_frequency"]):
        raise_err(errors.ERR_AUDIT_HOLD,
                  "An audit records hold covers the claim return's period")
    claim["applied_cents"] = claim["approved_cents"]
    claim["status"] = "APPLIED"
    touch(claim)
    ret["credits_cents"] += claim["applied_cents"]
    reg = DB.registrations[ret["registration_id"]]
    registrant = DB.registrants[reg["registrant_id"]]
    services._apply_settlement(ret, registrant)
    services.recompute_rollup(registrant["id"])
    return success_object(ser_claim(claim))


@bp.post("/credit-claims/<cid>/reverse")
def reverse_claim(cid):
    require_roles(["TaxReviewer", "ComplianceAdmin"])
    body = body_dict()
    amount = req_int(body, "amount_cents", minimum=1)
    claim = get_or_404(DB.claims, cid, "CreditClaim")
    if claim["status"] != "APPLIED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Claim in status {claim['status']} cannot be reversed")
    if amount > claim["applied_cents"] - claim["reversed_cents"]:
        raise_err(errors.ERR_REVERSE_EXCEEDS_APPLIED,
                  "The reversal exceeds the not-yet-reversed applied amount")
    claim["reversed_cents"] += amount
    if claim["reversed_cents"] >= claim["applied_cents"]:
        claim["status"] = "REVERSED"
        claim["_reversed_at"] = now_dt()
    touch(claim)
    ret = DB.returns[claim["return_id"]]
    ret["credits_cents"] -= amount
    reg = DB.registrations[ret["registration_id"]]
    registrant = DB.registrants[reg["registrant_id"]]
    services._apply_settlement(ret, registrant)
    services.recompute_rollup(registrant["id"])
    services.recompute_bond_requirement(reg)
    services.refresh_deficiency(reg)
    return success_object(ser_claim(claim))
