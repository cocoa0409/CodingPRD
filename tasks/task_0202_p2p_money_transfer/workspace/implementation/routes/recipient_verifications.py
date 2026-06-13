"""RecipientVerification endpoints: start, confirm (boundary: at/after expiry -> EXPIRED)."""
import random
import string
from datetime import timedelta

from flask import Blueprint

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles

bp = Blueprint("recipient_verifications", __name__)


def _mint_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=12))


@bp.route("/recipient-verifications", methods=["POST"])
def create_recipient_verification():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        body = validate.get_json_body()
        account_id = validate.require_str(body, "account_id")
        channel = validate.require_enum(body, "channel", {"EMAIL", "SMS"})
        acct = db.accounts.get(account_id)
        if not acct:
            raise err("ERR_NOT_FOUND", "Account not found.")
        if p.user_id != account_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this account.")
        # one live verification per (account, channel): a prior PENDING within its
        # window (now < expires_at) blocks a new one.
        now = db.now()
        for r in db.recipient_verifications.values():
            if (r["account_id"] == account_id and r["channel"] == channel
                    and r["status"] == "PENDING" and now < r["expires_at"]):
                raise err("ERR_VERIFICATION_ALREADY_PENDING",
                          "A live verification already exists for this channel.")
        rv = {
            "account_id": account_id,
            "channel": channel,
            "status": "PENDING",
            "confirm_token": _mint_token(),
            "expires_at": now + timedelta(hours=24),
        }
        models._stamp_lean(rv)
        db.recipient_verifications[rv["id"]] = rv
        return response.ok(models.serialize(rv), 201)


@bp.route("/recipient-verifications/<rv_id>/confirm", methods=["POST"])
def confirm_recipient_verification(rv_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        rv = db.recipient_verifications.get(rv_id)
        if not rv:
            raise err("ERR_NOT_FOUND", "Recipient verification not found.")
        acct = db.accounts.get(rv["account_id"])
        if p.user_id != rv["account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this verification.")
        if rv["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Verification is not PENDING.")
        body = validate.get_json_body()
        token = validate.require_str(body, "token")
        if token != rv["confirm_token"]:
            raise err("ERR_VERIFICATION_TOKEN_INVALID", "Token mismatch.")
        # token correct: boundary decides CONFIRMED vs EXPIRED.
        now = db.now()
        if now < rv["expires_at"]:
            rv["status"] = "CONFIRMED"
            if acct is not None and not acct["is_recipient_verified"]:
                acct["is_recipient_verified"] = True
                models.touch(acct)
        else:
            rv["status"] = "EXPIRED"
        return response.ok(models.serialize(rv))
