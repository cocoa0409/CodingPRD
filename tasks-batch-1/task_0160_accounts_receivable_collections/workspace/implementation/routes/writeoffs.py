"""Write-off / bad-debt endpoints (PRD §3.6, §2.8 SoD)."""
from flask import Blueprint

import db
from errors import (
    err, ERR_INVALID_STATE, ERR_DISPUTE_BLOCKS_WRITEOFF, ERR_SOD_VIOLATION,
    ERR_WRITEOFF_AMOUNT_MISMATCH,
)
from middleware import get_identity, authorize
from response import success
from services import domain, lookup
from services.common import (
    stamp_create, touch, get_json_body, require_str, require_int, require_enum,
)

bp = Blueprint("writeoffs", __name__)

REASON_CODES = {"UNCOLLECTIBLE", "SETTLEMENT", "BANKRUPTCY", "SMALL_BALANCE"}


def _invoice_has_active_dispute(invoice_id):
    for d in db.disputes.values():
        if d["invoice_id"] == invoice_id and d["status"] in ("OPEN", "UNDER_REVIEW"):
            return True
    return False


@bp.route("/ar/write-offs", methods=["POST"])
def create_writeoff():
    user_id, role = get_identity()
    authorize(role, ["COLLECTIONS_AGENT", "AR_MANAGER"])
    body = get_json_body()
    invoice_id = require_str(body, "invoice_id")
    invoice = lookup.get_invoice(invoice_id)
    amount = require_int(body, "amount_cents", minimum=1)
    reason = require_enum(body, "reason_code", REASON_CODES)

    # dispute block (priority 8) before amount match (priority 16)
    if _invoice_has_active_dispute(invoice_id):
        raise err(ERR_DISPUTE_BLOCKS_WRITEOFF, "invoice has an open/under-review dispute")

    # amount must equal dunnable balance exactly (priority 16)
    if amount != domain.dunnable(invoice):
        raise err(ERR_WRITEOFF_AMOUNT_MISMATCH, "write-off amount must equal dunnable balance")

    w = {
        "invoice_id": invoice_id,
        "amount_cents": amount,
        "reason_code": reason,
        "approved": False,
        "created_by": user_id,
    }
    stamp_create(w)
    db.write_offs[w["id"]] = w
    return success(domain.serialize_writeoff(w), status=201)


@bp.route("/ar/write-offs/<wid>/approve", methods=["POST"])
def approve(wid):
    user_id, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    w = lookup.get_writeoff(wid)
    invoice = lookup.get_invoice(w["invoice_id"])

    # state (priority 6): not already approved; invoice OPEN or PARTIAL
    if w["approved"]:
        raise err(ERR_INVALID_STATE, "write-off already approved")
    if invoice["status"] not in ("OPEN", "PARTIAL"):
        raise err(ERR_INVALID_STATE, "invoice not in OPEN/PARTIAL")

    # dispute block (priority 8)
    if _invoice_has_active_dispute(w["invoice_id"]):
        raise err(ERR_DISPUTE_BLOCKS_WRITEOFF, "invoice has an open/under-review dispute")

    # SoD (priority 9): approver must differ from creator
    if w.get("created_by") == user_id:
        raise err(ERR_SOD_VIOLATION, "approver must differ from creator")

    # amount must still equal dunnable balance (priority 16)
    if w["amount_cents"] != domain.dunnable(invoice):
        raise err(ERR_WRITEOFF_AMOUNT_MISMATCH, "write-off amount no longer matches balance")

    # approve + cascade
    w["approved"] = True
    touch(w)

    invoice["balance_cents"] = 0
    invoice["status"] = "WRITTEN_OFF"
    touch(invoice)

    customer = db.customers.get(invoice["customer_id"])
    if customer is not None:
        customer["bad_debt_total_cents"] += w["amount_cents"]
        touch(customer)
        domain.recompute_customer(customer, recompute_stage=True, already_touched=True)

    return success(domain.serialize_writeoff(w), status=200)


@bp.route("/ar/write-offs/<wid>", methods=["GET"])
def get_writeoff(wid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AUDITOR"])
    w = lookup.get_writeoff(wid)
    return success(domain.serialize_writeoff(w), status=200)
