"""FundingSource endpoints: link, fetch, verify, remove."""
import random
import string

from flask import Blueprint

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles
from services import ledger

bp = Blueprint("funding_sources", __name__)


def _mint_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=4))


@bp.route("/funding-sources", methods=["POST"])
def create_funding_source():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        body = validate.get_json_body()
        account_id = validate.require_str(body, "account_id")
        kind = validate.require_enum(body, "kind", {"BANK", "DEBIT"})
        last4 = validate.require_str(body, "last4")
        acct = db.accounts.get(account_id)
        if not acct:
            raise err("ERR_NOT_FOUND", "Account not found.")
        if p.user_id != account_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this account.")
        if not (len(last4) == 4 and last4.isdigit()):
            raise err("ERR_INVALID_REQUEST", "last4 must be exactly 4 digits.")
        fs = {
            "account_id": account_id,
            "kind": kind,
            "last4": last4,
            "status": "PENDING",
            "micro_deposit_code": _mint_code(),
            "is_default_payout": False,
        }
        models._stamp_create(fs)
        db.funding_sources[fs["id"]] = fs
        return response.ok(models.serialize(fs), 201)


@bp.route("/funding-sources/<fs_id>", methods=["GET"])
def get_funding_source(fs_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        fs = db.funding_sources.get(fs_id)
        if not fs:
            raise err("ERR_NOT_FOUND", "Funding source not found.")
        if p.role == "AccountHolder" and p.user_id != fs["account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this funding source.")
        return response.ok(models.serialize(fs))


@bp.route("/funding-sources/<fs_id>/verify", methods=["POST"])
def verify_funding_source(fs_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        fs = db.funding_sources.get(fs_id)
        if not fs:
            raise err("ERR_NOT_FOUND", "Funding source not found.")
        if p.user_id != fs["account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this funding source.")
        if fs["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Funding source is not PENDING.")
        body = validate.get_json_body()
        code = validate.require_str(body, "code")
        if code != fs["micro_deposit_code"]:
            raise err("ERR_VERIFICATION_TOKEN_INVALID", "Micro-deposit code mismatch.")
        fs["status"] = "VERIFIED"
        models.touch(fs)
        ledger.recompute_default_payout(fs["account_id"])
        return response.ok(models.serialize(fs))


@bp.route("/funding-sources/<fs_id>", methods=["DELETE"])
def remove_funding_source(fs_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        fs = db.funding_sources.get(fs_id)
        if not fs:
            raise err("ERR_NOT_FOUND", "Funding source not found.")
        if p.user_id != fs["account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this funding source.")
        if fs["status"] == "REMOVED":
            raise err("ERR_INVALID_STATE", "Funding source already removed.")
        if fs["status"] == "VERIFIED":
            in_use = any(
                w["funding_source_id"] == fs_id and w["status"] == "REQUESTED"
                for w in db.withdrawals.values())
            if in_use:
                raise err("ERR_FUNDING_SOURCE_IN_USE",
                          "Funding source referenced by a REQUESTED withdrawal.")
        fs["status"] = "REMOVED"
        models.touch(fs)
        ledger.recompute_default_payout(fs["account_id"])
        return response.ok(models.serialize(fs))
