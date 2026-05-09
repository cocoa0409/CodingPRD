from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_LOT_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_LOT_INVALID_STATE,
    ERR_DISPUTE_INVALID_STATE,
    ERR_BIDDER_RESTRICTED,
    ERR_IDENTITY_MISMATCH,
    ERR_INVALID_REFUND_AMOUNT,
    ERR_DISPUTE_WINDOW_EXPIRED,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_FOUND,
)
from middleware import require_role
from response import success
from routes._helpers import get_json_body, require_string, require_int, require_enum
from services import calc
from services.lot_service import (
    serialize_dispute,
    bump,
    transition_disputed_refund,
    transition_disputed_relist,
    transition_disputed_denied,
    _find_active_invoice,
)

bp = Blueprint("disputes", __name__)


@bp.post("/lots/<lot_id>/disputes")
def file_dispute(lot_id):
    user_id, _ = require_role({"Bidder"})
    body = get_json_body()
    filed_by = require_enum(body, "filed_by", {"BIDDER", "SELLER"})
    reason = require_string(body, "reason", min_len=1, max_len=500)
    evidence = body.get("evidence", [])
    if not isinstance(evidence, list):
        raise_err(ERR_INVALID_REQUEST, "evidence must be an array")
    for item in evidence:
        if not isinstance(item, dict) or "url" not in item or "kind" not in item:
            raise_err(ERR_INVALID_REQUEST, "evidence items must be {url, kind}")
    if "claimed_refund_amount_cents" not in body:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: claimed_refund_amount_cents")
    claimed = body["claimed_refund_amount_cents"]
    if not isinstance(claimed, int) or isinstance(claimed, bool) or claimed < 0:
        raise_err(ERR_INVALID_REQUEST, "claimed_refund_amount_cents must be a non-negative integer")
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    if lot["status"] != "SOLD":
        raise_err(ERR_LOT_INVALID_STATE)
    bidder = db.bidders.get(user_id)
    if bidder is None:
        raise_err(ERR_IDENTITY_MISMATCH)
    if bidder["status"] in ("RESTRICTED", "SUSPENDED"):
        raise_err(ERR_BIDDER_RESTRICTED)
    if user_id != lot.get("winning_bidder_id"):
        raise_err(ERR_IDENTITY_MISMATCH)
    invoice = _find_active_invoice(lot["id"])
    if invoice is None:
        raise_err(ERR_INVOICE_NOT_FOUND)
    if invoice["status"] != "PAID":
        raise_err(ERR_LOT_INVALID_STATE)
    if lot.get("delivered_at") is None:
        raise_err(ERR_LOT_INVALID_STATE)
    now = db.now()
    if now > lot["delivered_at"] + timedelta(seconds=calc.DISPUTE_WINDOW_SECONDS):
        raise_err(ERR_DISPUTE_WINDOW_EXPIRED)
    if claimed > invoice["buyer_total_cents"]:
        raise_err(ERR_INVALID_REQUEST, "claimed_refund_amount_cents exceeds buyer_total_cents")
    did = db.gen_id()
    d = {
        "id": did,
        "lot_id": lot_id,
        "invoice_id": invoice["id"],
        "filed_by": filed_by,
        "filer_user_id": user_id,
        "reason": reason,
        "evidence": evidence,
        "claimed_refund_amount_cents": claimed,
        "status": "FILED",
        "resolution_outcome": None,
        "resolution_refund_amount_cents": 0,
        "arbitrator_user_id": None,
        "filed_at": now,
        "review_started_at": None,
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.disputes[did] = d
    lot["status"] = "DISPUTED"
    bump(lot)
    return success(serialize_dispute(d), http_status=201)


@bp.post("/lots/<lot_id>/disputes/<dispute_id>/start-review")
def start_review(lot_id, dispute_id):
    user_id, _ = require_role({"ArbitratorOps"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    d = db.disputes.get(dispute_id)
    if d is None or d["lot_id"] != lot_id:
        raise_err(ERR_DISPUTE_NOT_FOUND)
    if d["status"] != "FILED":
        raise_err(ERR_DISPUTE_INVALID_STATE)
    d["status"] = "UNDER_REVIEW"
    d["arbitrator_user_id"] = user_id
    d["review_started_at"] = db.now()
    bump(d)
    return success(serialize_dispute(d))


@bp.post("/lots/<lot_id>/disputes/<dispute_id>/resolve")
def resolve_dispute(lot_id, dispute_id):
    require_role({"ArbitratorOps"})
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"REFUND", "RELIST", "DENIED"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    d = db.disputes.get(dispute_id)
    if d is None or d["lot_id"] != lot_id:
        raise_err(ERR_DISPUTE_NOT_FOUND)
    if d["status"] != "UNDER_REVIEW":
        raise_err(ERR_DISPUTE_INVALID_STATE)
    invoice = db.invoices.get(d["invoice_id"])
    if invoice is None:
        raise_err(ERR_INVOICE_NOT_FOUND)
    refund_amount = body.get("resolution_refund_amount_cents")
    # Priority 14: refund amount validation
    if outcome == "REFUND":
        if refund_amount is None:
            raise_err(ERR_INVALID_REFUND_AMOUNT)
        if not isinstance(refund_amount, int) or isinstance(refund_amount, bool):
            raise_err(ERR_INVALID_REFUND_AMOUNT)
        if refund_amount <= 0:
            raise_err(ERR_INVALID_REFUND_AMOUNT)
        if refund_amount > invoice["buyer_total_cents"]:
            raise_err(ERR_INVALID_REFUND_AMOUNT)
    else:
        if refund_amount is not None and refund_amount != 0:
            raise_err(ERR_INVALID_REFUND_AMOUNT)
        refund_amount = 0
    d["resolution_outcome"] = outcome
    d["resolution_refund_amount_cents"] = refund_amount
    d["resolved_at"] = db.now()
    if outcome == "REFUND":
        d["status"] = "RESOLVED_REFUND"
        bump(d)
        transition_disputed_refund(lot, d)
    elif outcome == "RELIST":
        d["status"] = "RESOLVED_RELIST"
        bump(d)
        transition_disputed_relist(lot, d)
    else:
        d["status"] = "RESOLVED_DENIED"
        bump(d)
        transition_disputed_denied(lot, d)
    return success(serialize_dispute(d))
