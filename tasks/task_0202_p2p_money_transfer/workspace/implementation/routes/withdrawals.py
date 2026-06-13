"""Withdrawal endpoints: create (OCC-guarded, fee), fetch, list, settle/cancel/fail."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import ledger
from services import withdrawal as wd_svc

bp = Blueprint("withdrawals", __name__)


@bp.route("/withdrawals", methods=["POST"])
def create_withdrawal():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        body = validate.get_json_body()
        account_id = validate.require_str(body, "account_id")
        funding_source_id = validate.require_str(body, "funding_source_id")
        gross = validate.require_int(body, "gross_amount_cents", minimum=1)
        speed = validate.require_enum(body, "speed", {"INSTANT", "STANDARD"})
        expected_version = validate.require_int(body, "expected_account_version")
        # (3) existence: account then funding source
        acct = db.accounts.get(account_id)
        if not acct:
            raise err("ERR_NOT_FOUND", "Account not found.")
        fs = db.funding_sources.get(funding_source_id)
        if not fs:
            raise err("ERR_NOT_FOUND", "Funding source not found.")
        # (4) ownership
        if p.user_id != account_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the account owner.")
        # (7) frozen
        if acct["status"] == "FROZEN":
            raise err("ERR_ACCOUNT_FROZEN", "Account is frozen.")
        # (10) funding source VERIFIED and owned by the account
        if fs["account_id"] != account_id or fs["status"] != "VERIFIED":
            raise err("ERR_FUNDING_SOURCE_NOT_VERIFIED",
                      "Funding source not verified or not owned by account.")
        # (15) sufficient funds
        if acct["available_balance_cents"] < gross:
            raise err("ERR_INSUFFICIENT_FUNDS", "Insufficient funds.")
        # (16) OCC: expected_account_version must match current version
        if expected_version != acct["version"]:
            raise err("ERR_STALE_ACCOUNT_VERSION", "Stale account version.")

        fee, net = wd_svc.compute_fee(gross, speed)
        w = {
            "account_id": account_id,
            "funding_source_id": funding_source_id,
            "gross_amount_cents": gross,
            "speed": speed,
            "fee_cents": fee,
            "net_amount_cents": net,
            "status": "PAID" if speed == "INSTANT" else "REQUESTED",
        }
        models._stamp_create(w)
        db.withdrawals[w["id"]] = w
        # DEBIT full gross (source_kind WITHDRAWAL); recompute balance; bump version
        ledger.post_ledger(account_id, "DEBIT", gross, "WITHDRAWAL", w["id"], "withdrawal")
        ledger.recompute_account(acct)
        models.touch(acct)  # version increments by one on every successful create
        return response.ok(models.serialize(w), 201)


@bp.route("/withdrawals/<w_id>", methods=["GET"])
def get_withdrawal(w_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        w = db.withdrawals.get(w_id)
        if not w:
            raise err("ERR_NOT_FOUND", "Withdrawal not found.")
        if p.role == "AccountHolder" and p.user_id != w["account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this withdrawal.")
        return response.ok(models.serialize(w))


@bp.route("/withdrawals", methods=["GET"])
def list_withdrawals():
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.withdrawals.values())
        for key in ("account_id", "funding_source_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [w for w in items if w.get(key) == val]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/withdrawals/<w_id>/settle", methods=["POST"])
def settle_withdrawal(w_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"PlatformAdmin"})
        w = db.withdrawals.get(w_id)
        if not w:
            raise err("ERR_NOT_FOUND", "Withdrawal not found.")
        if w["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Withdrawal is not REQUESTED.")
        w["status"] = "PAID"
        models.touch(w)
        # no balance change; gross was debited at creation
        return response.ok(models.serialize(w))


@bp.route("/withdrawals/<w_id>/cancel", methods=["POST"])
def cancel_withdrawal(w_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"AccountHolder"})
        w = db.withdrawals.get(w_id)
        if not w:
            raise err("ERR_NOT_FOUND", "Withdrawal not found.")
        if p.user_id != w["account_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this withdrawal.")
        if w["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Withdrawal is not REQUESTED.")
        _refund(w, "CANCELLED")
        return response.ok(models.serialize(w))


@bp.route("/withdrawals/<w_id>/fail", methods=["POST"])
def fail_withdrawal(w_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"PlatformAdmin"})
        w = db.withdrawals.get(w_id)
        if not w:
            raise err("ERR_NOT_FOUND", "Withdrawal not found.")
        if w["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Withdrawal is not REQUESTED.")
        _refund(w, "FAILED")
        return response.ok(models.serialize(w))


def _refund(w, terminal_status):
    """Compensating CREDIT of full gross (source_kind ADJUSTMENT); recompute balance.

    The withdrawal flips to its terminal status BEFORE recompute so the gross no
    longer counts toward held_balance (compute_held only counts REQUESTED withdrawals).
    The compensating CREDIT restores available, mirroring the debit taken at creation.
    """
    acct = db.accounts.get(w["account_id"])
    w["status"] = terminal_status
    models.touch(w)
    ledger.post_ledger(w["account_id"], "CREDIT", w["gross_amount_cents"],
                       "ADJUSTMENT", None, "withdrawal refund")
    if acct is not None:
        ledger.recompute_account(acct)
        models.touch(acct)
