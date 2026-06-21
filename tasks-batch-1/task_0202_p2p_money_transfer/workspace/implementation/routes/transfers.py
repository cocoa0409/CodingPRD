"""Transfer endpoints: send, fetch, list/filter, cancel."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import ledger, transfer as transfer_svc

bp = Blueprint("transfers", __name__)


@bp.route("/transfers", methods=["POST"])
def create_transfer():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        body = validate.get_json_body()
        sender_id = validate.require_str(body, "sender_account_id")
        recipient_id = validate.require_str(body, "recipient_account_id")
        amount = validate.require_int(body, "amount_cents", minimum=1)
        memo = validate.optional_str(body, "memo", "")
        # (3) existence: body FKs sender then recipient
        sender = db.accounts.get(sender_id)
        if not sender:
            raise err("ERR_NOT_FOUND", "Sender account not found.")
        recipient = db.accounts.get(recipient_id)
        if not recipient:
            raise err("ERR_NOT_FOUND", "Recipient account not found.")
        # (4) ownership: acting holder must be the sender
        if p.user_id != sender_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the sender account owner.")
        # (7) frozen: neither sender nor recipient may be FROZEN
        if sender["status"] == "FROZEN" or recipient["status"] == "FROZEN":
            raise err("ERR_ACCOUNT_FROZEN", "An account in this transfer is frozen.")
        # (8) self-transfer
        if sender_id == recipient_id:
            raise err("ERR_SELF_TRANSFER", "Cannot send to self.")
        # (13/14 limit, 15 funds, risk gate, branch) in service
        t = transfer_svc.create_transfer(sender, recipient, amount, memo)
        return response.ok(models.serialize(t), 201)


@bp.route("/transfers/<t_id>", methods=["GET"])
def get_transfer(t_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "ComplianceOfficer", "PlatformAdmin"})
        t = db.transfers.get(t_id)
        if not t:
            raise err("ERR_NOT_FOUND", "Transfer not found.")
        return response.ok(models.serialize(t))


@bp.route("/transfers", methods=["GET"])
def list_transfers():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "ComplianceOfficer", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.transfers.values())
        for key in ("sender_account_id", "recipient_account_id",
                    "source_money_request_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [t for t in items if t.get(key) == val]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/transfers/<t_id>/cancel", methods=["POST"])
def cancel_transfer(t_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        t = db.transfers.get(t_id)
        if not t:
            raise err("ERR_NOT_FOUND", "Transfer not found.")
        if p.user_id != t["sender_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the sender of this transfer.")
        # cancellable only while SENT and not risk_flagged. A SETTLED/HELD/etc
        # transfer is an invalid state for cancel.
        if t["status"] != "SENT" or t["risk_flagged"]:
            raise err("ERR_INVALID_STATE", "Transfer cannot be cancelled.")
        # In this model a SENT transfer auto-settles in the same request, so no
        # ledger movement persists for a still-SENT row; nothing to reverse.
        t["status"] = "CANCELLED"
        models.touch(t)
        return response.ok(models.serialize(t))
