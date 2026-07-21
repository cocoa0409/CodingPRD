"""Payout endpoints (PRD 3.10). Creation lives on the campaign blueprint."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import domain

bp = Blueprint("payouts", __name__)

READ_ROLES = [
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_CAMPAIGN_MANAGER,
    config.ROLE_FINANCE_REVIEWER,
]
PAYOUT_STATUSES = [
    "REQUESTED",
    "UNDER_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "REJECTED",
    "RELEASED",
    "VOIDED",
    "SUPERSEDED",
]


def _campaign_of(payout):
    return store.campaigns.get(payout["campaign_id"])


@bp.get("/api/payouts/<payout_id>")
def read_payout(payout_id):
    user_id, role = authorize(READ_ROLES)
    rec = domain.get_payout(payout_id)
    campaign = _campaign_of(rec)
    if campaign is not None:
        domain.require_actor_owns_campaign(user_id, role, campaign)
    return response.object_response(domain.ser_payout(rec))


@bp.get("/api/payouts")
def list_payouts():
    authorize(READ_ROLES)
    limit, offset = v.pagination()
    campaign_id = v.q("campaign_id")
    status = v.q_enum("status", PAYOUT_STATUSES)
    rows = list(store.payouts.values())
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_payout, limit, offset)


@bp.post("/api/payouts/<payout_id>/review")
def review_payout(payout_id):
    user_id, _role = authorize([config.ROLE_FINANCE_REVIEWER])
    rec = domain.get_payout(payout_id)
    if rec["status"] != "REQUESTED":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "UNDER_REVIEW"
    rec["reviewed_by_user_id"] = user_id
    db.touch(rec)
    return response.object_response(domain.ser_payout(rec))


@bp.post("/api/payouts/<payout_id>/request-changes")
def request_changes_payout(payout_id):
    authorize([config.ROLE_FINANCE_REVIEWER])
    body = v.get_body()
    note = v.opt_str(body, "note")
    rec = domain.get_payout(payout_id)
    if rec["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "CHANGES_REQUESTED"
    if note is not None:
        rec["note"] = note
    db.touch(rec)
    return response.object_response(domain.ser_payout(rec))


@bp.post("/api/payouts/<payout_id>/resubmit")
def resubmit_payout(payout_id):
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    amount_cents = v.req_int(body, "amount_cents", minimum=1)
    note = v.opt_str(body, "note")
    rec = domain.get_payout(payout_id)
    campaign = _campaign_of(rec)
    if campaign is not None:
        domain.require_manager_owns_campaign(user_id, campaign)
    if rec["status"] != "CHANGES_REQUESTED":
        raise_error("ERR_INVALID_STATE")
    if amount_cents < config.MIN_PAYOUT_CENTS:
        raise_error("ERR_PAYOUT_BELOW_MINIMUM")
    domain.refresh_campaign(campaign)
    # Balance measured with this payout's reservation re-computed at the new amount.
    available_after = (
        campaign["available_balance_cents"] + rec["amount_cents"] - amount_cents
    )
    if available_after < 0:
        raise_error("ERR_INSUFFICIENT_CAMPAIGN_BALANCE")
    rec["amount_cents"] = amount_cents
    if note is not None:
        rec["note"] = note
    rec["status"] = "REQUESTED"
    rec["requested_by_user_id"] = user_id
    rec["reviewed_by_user_id"] = None
    db.touch(rec)
    domain.refresh_campaign(campaign)
    return response.object_response(domain.ser_payout(rec))


@bp.post("/api/payouts/<payout_id>/approve")
def approve_payout(payout_id):
    user_id, _role = authorize([config.ROLE_FINANCE_REVIEWER])
    rec = domain.get_payout(payout_id)
    if rec["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE")
    # PRD 2.8 step 8: segregation of duties.
    if user_id == rec["reviewed_by_user_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES")
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = user_id
    db.touch(rec)
    return response.object_response(domain.ser_payout(rec))


@bp.post("/api/payouts/<payout_id>/reject")
def reject_payout(payout_id):
    authorize([config.ROLE_FINANCE_REVIEWER])
    body = v.get_body()
    note = v.opt_str(body, "note")
    rec = domain.get_payout(payout_id)
    if rec["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "REJECTED"
    if note is not None:
        rec["note"] = note
    db.touch(rec)
    campaign = _campaign_of(rec)
    if campaign is not None:
        domain.refresh_campaign(campaign)
    return response.object_response(domain.ser_payout(rec))


@bp.post("/api/payouts/<payout_id>/release")
def release_payout(payout_id):
    authorize([config.ROLE_PLATFORM_ADMIN])
    rec = domain.get_payout(payout_id)
    if rec["status"] != "APPROVED":
        raise_error("ERR_INVALID_STATE")
    campaign = _campaign_of(rec)
    organization = (
        store.organizations.get(campaign["organization_id"]) if campaign else None
    )
    # PRD 2.8 step 15: payout account readiness.
    if organization is None or organization["payout_account_status"] != "VERIFIED":
        raise_error("ERR_ORGANIZATION_PAYOUT_UNVERIFIED")
    rec["status"] = "RELEASED"
    rec["released_at"] = db.now_iso()
    db.touch(rec)
    db.touch(campaign)
    domain.refresh_campaign(campaign)
    return response.object_response(domain.ser_payout(rec))


@bp.post("/api/payouts/<payout_id>/void")
def void_payout(payout_id):
    authorize([config.ROLE_PLATFORM_ADMIN])
    body = v.get_body()
    v.opt_str(body, "reason")
    rec = domain.get_payout(payout_id)
    if rec["status"] != "RELEASED":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "VOIDED"
    db.touch(rec)
    campaign = _campaign_of(rec)
    if campaign is not None:
        db.touch(campaign)
        domain.refresh_campaign(campaign)
    return response.object_response(domain.ser_payout(rec))
