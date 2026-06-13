"""Dispute + Reversal endpoints.

Dispute lifecycle: OPEN <-> NEEDS_INFO, OPEN -> {UPHELD, DENIED}.
Uphold fires the depth-3 cascade: Reversal + transfer REVERSED + ledger + +35 recipient risk.
Segregation: officer must not be opener, sender, or recipient of the transfer.
"""
from datetime import timedelta

from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import ledger

bp = Blueprint("disputes", __name__)

DISPUTE_WINDOW_DAYS = 60


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        body = validate.get_json_body()
        transfer_id = validate.require_str(body, "transfer_id")
        opener_id = validate.require_str(body, "opener_account_id")
        reason = validate.require_enum(body, "reason",
                                       {"UNAUTHORIZED", "NOT_RECEIVED", "DUPLICATE"})
        transfer = db.transfers.get(transfer_id)
        if not transfer:
            raise err("ERR_NOT_FOUND", "Transfer not found.")
        opener = db.accounts.get(opener_id)
        if not opener:
            raise err("ERR_NOT_FOUND", "Opener account not found.")
        # ownership: opener is the sender who paid the transfer, and must be the caller
        if p.user_id != opener_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the opener account owner.")
        if transfer["sender_account_id"] != opener_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Opener is not the transfer sender.")
        # dispute window: transfer SETTLED and now <= settled_at + 60d inclusive
        if transfer["status"] != "SETTLED" or transfer["settled_at"] is None:
            raise err("ERR_DISPUTE_WINDOW_CLOSED", "Transfer is not SETTLED.")
        now = db.now()
        if now > transfer["settled_at"] + timedelta(days=DISPUTE_WINDOW_DAYS):
            raise err("ERR_DISPUTE_WINDOW_CLOSED", "Dispute window has closed.")
        d = {
            "transfer_id": transfer_id,
            "opener_account_id": opener_id,
            "reason": reason,
            "status": "OPEN",
            "resolver_user_id": None,
            "reversal_id": None,
        }
        models._stamp_create(d)
        db.disputes[d["id"]] = d
        return response.ok(models.serialize(d), 201)


@bp.route("/disputes/<d_id>", methods=["GET"])
def get_dispute(d_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "ComplianceOfficer", "PlatformAdmin"})
        d = db.disputes.get(d_id)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        return response.ok(models.serialize(d))


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "ComplianceOfficer", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.disputes.values())
        for key in ("transfer_id", "opener_account_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [d for d in items if d.get(key) == val]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


def _segregation_dispute(principal, dispute, transfer):
    """Officer must not be opener, sender, or recipient of the disputed transfer."""
    if principal.user_id in (dispute["opener_account_id"],
                             transfer["sender_account_id"],
                             transfer["recipient_account_id"]):
        raise err("ERR_SEGREGATION_OF_DUTIES", "Officer is a party to the dispute.")


@bp.route("/disputes/<d_id>/request-info", methods=["POST"])
def request_info(d_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer"})
        d = db.disputes.get(d_id)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        transfer = db.transfers.get(d["transfer_id"])
        _segregation_dispute(p, d, transfer)
        if d["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Dispute is not OPEN.")
        d["status"] = "NEEDS_INFO"
        models.touch(d)
        return response.ok(models.serialize(d))


@bp.route("/disputes/<d_id>/provide-info", methods=["POST"])
def provide_info(d_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        d = db.disputes.get(d_id)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        if p.user_id != d["opener_account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the opener may provide info.")
        if d["status"] != "NEEDS_INFO":
            raise err("ERR_INVALID_STATE", "Dispute is not NEEDS_INFO.")
        d["status"] = "OPEN"
        models.touch(d)
        return response.ok(models.serialize(d))


@bp.route("/disputes/<d_id>/uphold", methods=["POST"])
def uphold(d_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer"})
        d = db.disputes.get(d_id)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        transfer = db.transfers.get(d["transfer_id"])
        _segregation_dispute(p, d, transfer)
        if d["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Dispute is not OPEN.")
        # underlying transfer must still be SETTLED
        if transfer["status"] != "SETTLED":
            raise err("ERR_INVALID_STATE", "Underlying transfer is not SETTLED.")
        sender = db.accounts[transfer["sender_account_id"]]      # opener/sender
        recipient = db.accounts[transfer["recipient_account_id"]]
        amount = transfer["amount_cents"]

        reversal = {
            "transfer_id": transfer["id"],
            "dispute_id": d["id"],
            "amount_cents": amount,
            "status": "APPLIED",
        }
        models._stamp_create(reversal)
        db.reversals[reversal["id"]] = reversal
        d["reversal_id"] = reversal["id"]

        # cascade: transfer SETTLED -> REVERSED
        transfer["status"] = "REVERSED"
        models.touch(transfer)
        # claw funds: DEBIT recipient, CREDIT opener/sender (source_kind REVERSAL)
        ledger.post_ledger(recipient["id"], "DEBIT", amount, "REVERSAL",
                           reversal["id"], "chargeback")
        ledger.post_ledger(sender["id"], "CREDIT", amount, "REVERSAL",
                           reversal["id"], "chargeback refund")
        ledger.recompute_account(recipient)
        ledger.recompute_account(sender)
        ledger.adjust_risk(recipient, ledger.RISK_CHARGEBACK_DELTA)
        models.touch(recipient)
        models.touch(sender)

        d["status"] = "UPHELD"
        d["resolver_user_id"] = p.user_id
        models.touch(d)
        return response.ok(models.serialize(d))


@bp.route("/disputes/<d_id>/deny", methods=["POST"])
def deny(d_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer"})
        d = db.disputes.get(d_id)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        transfer = db.transfers.get(d["transfer_id"])
        _segregation_dispute(p, d, transfer)
        if d["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Dispute is not OPEN.")
        opener = db.accounts.get(d["opener_account_id"])
        if opener is not None:
            ledger.adjust_risk(opener, ledger.RISK_DENIED_DELTA)
            models.touch(opener)
        d["status"] = "DENIED"
        d["resolver_user_id"] = p.user_id
        models.touch(d)
        return response.ok(models.serialize(d))


# ---- Reversal reads -------------------------------------------------------
rev_bp = Blueprint("reversals", __name__)


@rev_bp.route("/reversals/<r_id>", methods=["GET"])
def get_reversal(r_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer", "PlatformAdmin", "AccountHolder"})
        r = db.reversals.get(r_id)
        if not r:
            raise err("ERR_NOT_FOUND", "Reversal not found.")
        if p.role == "AccountHolder":
            t = db.transfers.get(r["transfer_id"])
            if not t or (p.user_id != t["sender_account_id"]
                         and p.user_id != t["recipient_account_id"]):
                raise err("ERR_NOT_RESOURCE_OWNER", "Not a party to this reversal.")
        return response.ok(models.serialize(r))


@rev_bp.route("/reversals", methods=["GET"])
def list_reversals():
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.reversals.values())
        for key in ("transfer_id", "dispute_id"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r.get(key) == val]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)
