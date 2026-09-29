"""Authorized reseller agreement endpoints (PRD §3.4)."""

from flask import Blueprint

import lookup
from auth import (
    ROLE_BRAND_CHANNEL_MANAGER, ROLE_RESELLER, STAFF_AND_RESELLER, authenticate, require_owner,
)
from envelope import created, ok, ok_list
from errors import fail
from store import new_row, now_iso, serialize, store, touch
from validate import (
    CHANNELS, QUALITY_OBLIGATIONS, body, has, opt_bool, opt_str, req_dt, req_enum,
    req_enum_list, req_str,
)

bp = Blueprint("agreements", __name__)

RESPONSE_DECISIONS = ["COUNTERSIGN", "DECLINE"]


@bp.post("/reseller-agreements")
def draft_agreement():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    reseller_id = req_str(b, "reseller_id")
    policy_id = req_str(b, "policy_id")
    permitted_channels = req_enum_list(b, "permitted_channels", CHANNELS, 1, 4)
    quality_obligations = req_enum_list(b, "quality_obligations", QUALITY_OBLIGATIONS, 0, 4)
    term_ends_at = req_dt(b, "term_ends_at")
    price_terms_included = opt_bool(b, "price_terms_included", False)

    reseller = lookup.reseller(reseller_id)
    lookup.policy(policy_id)
    if price_terms_included:
        fail("ERR_ANTITRUST_PRICE_TERM_IN_AGREEMENT",
             "An authorized reseller agreement may not declare price terms.")
    if reseller["primary_channel"] not in permitted_channels:
        fail("ERR_CHANNEL_NOT_PERMITTED",
             "permitted_channels must contain the reseller's primary_channel.")

    row = new_row({
        "reseller_id": reseller_id,
        "policy_id": policy_id,
        "status": "DRAFT",
        "permitted_channels": permitted_channels,
        "quality_obligations": quality_obligations,
        "term_ends_at": term_ends_at,
        "price_terms_included": price_terms_included,
        "non_negotiation_acknowledged": False,
        "sent_at": None,
        "countersigned_at": None,
        "countersigned_by_user_id": None,
        "activated_at": None,
        "closed_reason": None,
    })
    store.agreements[row["id"]] = row
    return created(serialize(row))


@bp.post("/reseller-agreements/<agreement_id>/send")
def send_agreement(agreement_id):
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    body()
    agreement = lookup.agreement(agreement_id)
    reseller = store.resellers.get(agreement["reseller_id"])
    if agreement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT agreement may be sent.")
    if reseller is None or reseller["authorization_status"] != "APPLIED":
        fail("ERR_INVALID_STATE", "The reseller must be APPLIED for the agreement to be sent.")
    policy = store.policies.get(agreement["policy_id"])
    if policy is None or policy["status"] != "PUBLISHED":
        fail("ERR_POLICY_NOT_PUBLISHED", "The referenced policy must be PUBLISHED at send.")

    agreement["status"] = "SENT"
    agreement["sent_at"] = now_iso()
    touch(agreement)
    reseller["authorization_status"] = "PENDING_AGREEMENT"
    touch(reseller)
    return ok(serialize(agreement))


@bp.post("/reseller-agreements/<agreement_id>/respond")
def respond_agreement(agreement_id):
    ctx = authenticate([ROLE_RESELLER])
    b = body()
    decision = req_enum(b, "decision", RESPONSE_DECISIONS)
    acknowledged = opt_bool(b, "non_negotiation_acknowledged", False)
    decline_reason = opt_str(b, "decline_reason", 0, None)
    agreement = lookup.agreement(agreement_id)
    require_owner(ctx, agreement, reseller_field="reseller_id")
    reseller = store.resellers.get(agreement["reseller_id"])
    if agreement["status"] != "SENT":
        fail("ERR_INVALID_STATE", "Only a SENT agreement may receive a response.")
    if reseller is None or reseller["authorization_status"] != "PENDING_AGREEMENT":
        fail("ERR_INVALID_STATE",
             "The reseller must be PENDING_AGREEMENT to respond to the agreement.")
    if has(b, "counter_price_proposal_cents"):
        fail("ERR_ANTITRUST_NEGOTIATION_PROHIBITED",
             "A price counter-proposal may not be entertained.")

    if decision == "COUNTERSIGN":
        agreement["status"] = "COUNTERSIGNED"
        agreement["countersigned_at"] = now_iso()
        agreement["countersigned_by_user_id"] = ctx.user_id
        agreement["non_negotiation_acknowledged"] = acknowledged
        touch(agreement)
    else:
        agreement["status"] = "DECLINED"
        agreement["closed_reason"] = decline_reason
        touch(agreement)
        reseller["authorization_status"] = "APPLIED"
        reseller["supply_status"] = "HOLD"
        reseller["hold_reason"] = "PENDING_AUTHORIZATION"
        touch(reseller)
    return ok(serialize(agreement))


@bp.post("/reseller-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    body()
    agreement = lookup.agreement(agreement_id)
    if agreement["status"] != "COUNTERSIGNED":
        fail("ERR_INVALID_STATE", "Only a COUNTERSIGNED agreement may be activated.")
    policy = store.policies.get(agreement["policy_id"])
    if policy is None or policy["status"] != "PUBLISHED":
        fail("ERR_POLICY_NOT_PUBLISHED", "The referenced policy must be PUBLISHED at activation.")
    if policy.get("non_negotiation_ack_required") and not agreement["non_negotiation_acknowledged"]:
        fail("ERR_NON_NEGOTIATION_ACK_MISSING",
             "The governing policy requires the non-negotiation acknowledgement.")

    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = now_iso()
    touch(agreement)
    reseller = store.resellers.get(agreement["reseller_id"])
    if reseller is not None:
        reseller["authorization_status"] = "AUTHORIZED"
        reseller["supply_status"] = "OPEN"
        reseller["hold_reason"] = "NONE"
        touch(reseller)
    return ok(serialize(agreement))


@bp.get("/reseller-agreements/<agreement_id>")
def read_agreement(agreement_id):
    ctx = authenticate(STAFF_AND_RESELLER)
    row = lookup.agreement(agreement_id)
    require_owner(ctx, row, reseller_field="reseller_id")
    return ok(serialize(row))


@bp.get("/reseller-agreements")
def list_agreements():
    authenticate(STAFF_AND_RESELLER)
    rows = lookup.filtered("agreements", {
        "reseller_id": "reseller_id",
        "policy_id": "policy_id",
        "status": "status",
    })
    return ok_list(rows)
