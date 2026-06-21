"""Withdrawal whitelist addresses (§3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import get_identity, require_roles
from db import db, new_id, next_seq
from errors import err
from response import success
from serializers import withdrawal_address_out
from services.common import require_body, required_str, touch
from services.pagination import paginate

bp = Blueprint("withdrawal_addresses", __name__)

HOLD_HOURS = 24
LIVE_WITHDRAWAL_STATES = {"SUBMITTED", "SCREENING", "TRAVEL_RULE_HOLD", "APPROVED", "BROADCAST"}


def get_address_or_404(addr_id):
    a = db.withdrawal_addresses.get(addr_id)
    if a is None:
        raise err("ERR_NOT_FOUND", "Withdrawal address not found")
    return a


@bp.route("/withdrawal-addresses", methods=["POST"])
def add_address():
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    body = require_body(request.get_json(silent=True))
    account_id = required_str(body, "account_id")
    asset = required_str(body, "asset")
    chain_address = required_str(body, "chain_address")
    label = required_str(body, "label")
    if "expected_account_version" not in body or body["expected_account_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_account_version")
    expected_version = body["expected_account_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_account_version must be an integer")

    acct = db.accounts.get(account_id)
    if acct is None:
        raise err("ERR_NOT_FOUND", "Account not found")
    if user_id != acct["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this account")
    if db.asset_by_symbol(asset) is None:
        raise err("ERR_NOT_FOUND", "Asset not found")

    # Hold-window overlap (half-open [created_at, activates_at)) on the triple.
    now = db.clock.now()
    for existing in db.withdrawal_addresses.values():
        if (existing["account_id"] == account_id and existing["asset"] == asset
                and existing["chain_address"] == chain_address
                and existing["status"] != "REMOVED"):
            if existing["created_at"] <= now < existing["activates_at"]:
                raise err("ERR_ADDRESS_HOLD_OVERLAP", "Address still inside its 24h hold window")

    # OCC against account version.
    if expected_version != acct["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", "Stale account version")

    activates_at = now + timedelta(hours=HOLD_HOURS)
    addr = {
        "id": new_id(),
        "account_id": account_id,
        "asset": asset,
        "chain_address": chain_address,
        "label": label,
        "status": "PENDING_HOLD",
        "activates_at": activates_at,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db.withdrawal_addresses[addr["id"]] = addr
    # Adding an address bumps the account version.
    touch(acct)
    return success(withdrawal_address_out(addr), status=201)


@bp.route("/withdrawal-addresses", methods=["GET"])
def list_addresses():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator", "ComplianceOfficer"})
    items = list(db.withdrawal_addresses.values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [a for a in items if a["account_id"] == acct]
    asset = request.args.get("asset")
    if asset is not None:
        items = [a for a in items if a["asset"] == asset]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, pag = paginate(items)
    return success([withdrawal_address_out(a) for a in page], pagination=pag)


@bp.route("/withdrawal-addresses/<addr_id>", methods=["GET"])
def get_address(addr_id):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator", "ComplianceOfficer"})
    a = get_address_or_404(addr_id)
    return success(withdrawal_address_out(a))


@bp.route("/withdrawal-addresses/<addr_id>/activate", methods=["POST"])
def activate_address(addr_id):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    a = get_address_or_404(addr_id)
    if user_id != a["account_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this address")
    if a["status"] != "PENDING_HOLD":
        raise err("ERR_INVALID_STATE", "Address is not PENDING_HOLD")
    if db.clock.now() < a["activates_at"]:
        raise err("ERR_INVALID_STATE", "Security hold has not elapsed")
    a["status"] = "ACTIVE"
    touch(a)
    return success(withdrawal_address_out(a))


@bp.route("/withdrawal-addresses/<addr_id>", methods=["DELETE"])
def remove_address(addr_id):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    a = get_address_or_404(addr_id)
    if user_id != a["account_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this address")
    if a["status"] not in ("ACTIVE", "PENDING_HOLD"):
        raise err("ERR_INVALID_STATE", "Address cannot be removed from its current state")
    # No live withdrawal may target this address.
    for w in db.withdrawals.values():
        if w["withdrawal_address_id"] == addr_id and w["status"] in LIVE_WITHDRAWAL_STATES:
            raise err("ERR_INVALID_STATE", "A live withdrawal still targets this address")
    a["status"] = "REMOVED"
    touch(a)
    return success(withdrawal_address_out(a))
