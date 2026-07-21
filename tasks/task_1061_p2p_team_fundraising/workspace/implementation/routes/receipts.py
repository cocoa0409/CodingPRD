"""Tax receipt endpoints (PRD 3.6)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import domain

bp = Blueprint("receipts", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
RECEIPT_STATUSES = ["ISSUED", "VOIDED"]
WRITE_ROLES = [config.ROLE_CAMPAIGN_MANAGER, config.ROLE_PLATFORM_ADMIN]


@bp.get("/api/receipts/<receipt_id>")
def read_receipt(receipt_id):
    authorize(PUBLIC)
    rec = domain.get_receipt(receipt_id)
    return response.object_response(domain.ser_receipt(rec))


@bp.get("/api/receipts")
def list_receipts():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    donation_id = v.q("donation_id")
    campaign_id = v.q("campaign_id")
    status = v.q_enum("status", RECEIPT_STATUSES)
    rows = list(store.receipts.values())
    if donation_id is not None:
        rows = [r for r in rows if r["donation_id"] == donation_id]
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_receipt, limit, offset)


@bp.post("/api/receipts/<receipt_id>/void")
def void_receipt(receipt_id):
    user_id, role = authorize(WRITE_ROLES)
    rec = domain.get_receipt(receipt_id)
    campaign = store.campaigns.get(rec["campaign_id"])
    if campaign is not None:
        domain.require_actor_owns_campaign(user_id, role, campaign)
    if rec["status"] != "ISSUED":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "VOIDED"
    rec["voided_at"] = db.now_iso()
    db.touch(rec)
    return response.object_response(domain.ser_receipt(rec))


@bp.post("/api/receipts/<receipt_id>/reissue")
def reissue_receipt(receipt_id):
    user_id, role = authorize(WRITE_ROLES)
    rec = domain.get_receipt(receipt_id)
    campaign = store.campaigns.get(rec["campaign_id"])
    if campaign is not None:
        domain.require_actor_owns_campaign(user_id, role, campaign)
    if rec["status"] != "VOIDED":
        raise_error("ERR_INVALID_STATE")
    donation = store.donations.get(rec["donation_id"])
    if donation is None or donation["payment_status"] != "SETTLED":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "ISSUED"
    rec["issued_at"] = db.now_iso()
    rec["voided_at"] = None
    rec["reissue_count"] = rec["reissue_count"] + 1
    db.touch(rec)
    return response.object_response(domain.ser_receipt(rec))
