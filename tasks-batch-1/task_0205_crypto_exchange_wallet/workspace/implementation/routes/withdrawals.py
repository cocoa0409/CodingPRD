"""Withdrawal submission, screening, travel rule, settlement (§3.6, §3.7)."""
from datetime import timezone

from flask import Blueprint, request

from auth import get_identity, require_roles
from db import db, new_id, next_seq
from errors import err
from response import success
from serializers import withdrawal_out, travel_rule_record_out
from services.common import (
    require_body, required_str, required_number, required_enum, touch,
    available, credit_available, debit_available, credit_held, debit_held,
)
from services.cost_basis import dispose
from services.pagination import paginate
from numeric import D, round_usd

bp = Blueprint("withdrawals", __name__)

TRAVEL_RULE_THRESHOLD_USD = D("3000")
DAILY_CEILING = {"TIER_0": D("0"), "TIER_1": D("1000"), "TIER_2": D("50000"), "TIER_3": D("1000000")}
DAILY_COUNT_STATES = {"SUBMITTED", "SCREENING", "TRAVEL_RULE_HOLD", "APPROVED", "BROADCAST", "COMPLETED"}


def get_withdrawal_or_404(wid):
    w = db.withdrawals.get(wid)
    if w is None:
        raise err("ERR_NOT_FOUND", "Withdrawal not found")
    return w


def _daily_used_usd(account_id):
    now = db.clock.now()
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = D(0)
    for w in db.withdrawals.values():
        if (w["account_id"] == account_id and w["status"] in DAILY_COUNT_STATES
                and w["created_at"] >= day_start):
            total += round_usd(D(w["notional_usd"]))
    return round_usd(total)


@bp.route("/withdrawals", methods=["POST"])
def submit_withdrawal():
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    body = require_body(request.get_json(silent=True))
    account_id = required_str(body, "account_id")
    withdrawal_address_id = required_str(body, "withdrawal_address_id")
    amount = required_number(body, "amount", allow_zero=False)
    replaces_id = body.get("replaces_withdrawal_id")

    # Existence: account first, then address (left-to-right).
    acct = db.accounts.get(account_id)
    if acct is None:
        raise err("ERR_NOT_FOUND", "Account not found")
    if user_id != acct["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this account")
    addr = db.withdrawal_addresses.get(withdrawal_address_id)
    if addr is None:
        raise err("ERR_NOT_FOUND", "Withdrawal address not found")
    if replaces_id is not None:
        if replaces_id not in db.withdrawals:
            raise err("ERR_NOT_FOUND", "Replaced withdrawal not found")

    # Frozen check.
    if acct["account_status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_FROZEN", "Account is frozen")

    # Address active + past activates_at.
    if addr["status"] != "ACTIVE" or db.clock.now() < addr["activates_at"]:
        raise err("ERR_ADDRESS_NOT_ACTIVE", "Target address is not active")

    asset = addr["asset"]
    asset_cfg = db.asset_by_symbol(asset)
    if asset_cfg is None:
        raise err("ERR_NOT_FOUND", "Asset not found")

    # Minimum withdrawal.
    if amount < D(asset_cfg["min_withdrawal_amount"]):
        raise err("ERR_BELOW_MIN_WITHDRAWAL", "Amount below minimum withdrawal")

    # Resubmit / asset match.
    if replaces_id is not None:
        replaced = db.withdrawals[replaces_id]
        if (replaced["status"] != "REJECTED"
                or replaced["account_id"] != account_id
                or replaced["withdrawal_address_id"] != withdrawal_address_id):
            raise err("ERR_RESUBMIT_TARGET_INVALID", "Invalid resubmit target")

    # notional + travel rule.
    notional_usd = round_usd(amount * D(asset_cfg["spot_price_usd"]))
    requires_travel_rule = notional_usd >= TRAVEL_RULE_THRESHOLD_USD

    # Daily ceiling.
    used = _daily_used_usd(account_id)
    ceiling = DAILY_CEILING.get(acct["kyc_tier"], D("0"))
    if used + notional_usd > ceiling:
        raise err("ERR_DAILY_LIMIT_EXCEEDED", "Daily withdrawal ceiling exceeded")

    # Sufficient available to cover amount + network_fee.
    network_fee = D(asset_cfg["network_fee"])
    total_debit = amount + network_fee
    bal = db.get_or_create_balance(account_id, asset)
    if available(bal) < total_debit:
        raise err("ERR_INSUFFICIENT_AVAILABLE", "Insufficient available balance")

    now = db.clock.now()
    w = {
        "id": new_id(),
        "account_id": account_id,
        "withdrawal_address_id": withdrawal_address_id,
        "asset": asset,
        "amount": amount,
        "notional_usd": notional_usd,
        "requires_travel_rule": requires_travel_rule,
        "replaces_withdrawal_id": replaces_id,
        "status": "SUBMITTED",
        "screened_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db.withdrawals[w["id"]] = w
    # Move amount + network_fee from available to held.
    debit_available(bal, total_debit)
    credit_held(bal, total_debit)
    return success(withdrawal_out(w), status=201)


@bp.route("/withdrawals", methods=["GET"])
def list_withdrawals():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator", "ComplianceOfficer"})
    items = list(db.withdrawals.values())
    for key in ("account_id", "withdrawal_address_id", "status", "replaces_withdrawal_id"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    items.sort(key=lambda w: (w["created_at"], w["_seq"]))
    page, pag = paginate(items)
    return success([withdrawal_out(w) for w in page], pagination=pag)


@bp.route("/withdrawals/<wid>", methods=["GET"])
def get_withdrawal(wid):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator", "ComplianceOfficer"})
    w = get_withdrawal_or_404(wid)
    return success(withdrawal_out(w))


@bp.route("/withdrawals/<wid>/screen", methods=["POST"])
def screen(wid):
    user_id, role = get_identity()
    require_roles(role, {"ComplianceOfficer"})
    w = get_withdrawal_or_404(wid)
    if w["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Withdrawal not in SUBMITTED state")
    w["status"] = "SCREENING"
    w["screened_by_user_id"] = user_id
    touch(w)
    return success(withdrawal_out(w))


@bp.route("/withdrawals/<wid>/screen-result", methods=["POST"])
def screen_result(wid):
    user_id, role = get_identity()
    require_roles(role, {"ComplianceOfficer"})
    w = get_withdrawal_or_404(wid)
    body = require_body(request.get_json(silent=True))
    result = required_enum(body, "result", {"CLEAR", "HOLD", "REJECT"})

    if result == "CLEAR":
        if w["status"] != "SCREENING":
            raise err("ERR_INVALID_STATE", "Withdrawal not in SCREENING state")
        if w["requires_travel_rule"]:
            raise err("ERR_TRAVEL_RULE_REQUIRED", "Travel-rule filing required")
        w["status"] = "APPROVED"
        touch(w)
        return success(withdrawal_out(w))

    if result == "HOLD":
        if w["status"] != "SCREENING":
            raise err("ERR_INVALID_STATE", "Withdrawal not in SCREENING state")
        if not w["requires_travel_rule"]:
            raise err("ERR_INVALID_STATE", "Withdrawal does not require travel-rule hold")
        w["status"] = "TRAVEL_RULE_HOLD"
        touch(w)
        return success(withdrawal_out(w))

    # REJECT — permitted from SCREENING or TRAVEL_RULE_HOLD.
    if w["status"] not in ("SCREENING", "TRAVEL_RULE_HOLD"):
        raise err("ERR_INVALID_STATE", "Withdrawal cannot be rejected from its current state")
    asset_cfg = db.asset_by_symbol(w["asset"])
    network_fee = D(asset_cfg["network_fee"])
    total = D(w["amount"]) + network_fee
    bal = db.get_or_create_balance(w["account_id"], w["asset"])
    debit_held(bal, total)
    credit_available(bal, total)
    w["status"] = "REJECTED"
    touch(w)
    return success(withdrawal_out(w))


@bp.route("/withdrawals/<wid>/travel-rule-records", methods=["POST"])
def file_travel_rule(wid):
    user_id, role = get_identity()
    require_roles(role, {"ComplianceOfficer"})
    w = get_withdrawal_or_404(wid)
    body = require_body(request.get_json(silent=True))
    originator_name = required_str(body, "originator_name")
    beneficiary_name = required_str(body, "beneficiary_name")
    beneficiary_vasp = required_str(body, "beneficiary_vasp")

    if w["status"] != "TRAVEL_RULE_HOLD":
        raise err("ERR_INVALID_STATE", "Withdrawal not in TRAVEL_RULE_HOLD state")
    if w.get("screened_by_user_id") == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Filing officer screened this withdrawal")

    now = db.clock.now()
    rec = {
        "id": new_id(),
        "withdrawal_id": wid,
        "originator_name": originator_name,
        "beneficiary_name": beneficiary_name,
        "beneficiary_vasp": beneficiary_vasp,
        "filed_by_user_id": user_id,
        "status": "FILED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db.travel_rule_records[rec["id"]] = rec
    w["status"] = "APPROVED"
    touch(w)
    return success(travel_rule_record_out(rec), status=201)


@bp.route("/travel-rule-records", methods=["GET"])
def list_travel_rule_records():
    user_id, role = get_identity()
    require_roles(role, {"Operator", "ComplianceOfficer"})
    items = list(db.travel_rule_records.values())
    wid = request.args.get("withdrawal_id")
    if wid is not None:
        items = [r for r in items if r["withdrawal_id"] == wid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, pag = paginate(items)
    return success([travel_rule_record_out(r) for r in page], pagination=pag)


@bp.route("/travel-rule-records/<rid>", methods=["GET"])
def get_travel_rule_record(rid):
    user_id, role = get_identity()
    require_roles(role, {"Operator", "ComplianceOfficer"})
    r = db.travel_rule_records.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Travel-rule record not found")
    return success(travel_rule_record_out(r))


@bp.route("/withdrawals/<wid>/broadcast", methods=["POST"])
def broadcast(wid):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    w = get_withdrawal_or_404(wid)
    if w["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Withdrawal not in APPROVED state")
    asset_cfg = db.asset_by_symbol(w["asset"])
    network_fee = D(asset_cfg["network_fee"])
    decimals = asset_cfg["decimals"]
    total = D(w["amount"]) + network_fee
    bal = db.get_or_create_balance(w["account_id"], w["asset"])
    # Debit held (total_amount falls because held falls).
    debit_held(bal, total)
    # Cost-basis disposal for the withdrawn amount (not the fee).
    acct = db.accounts.get(w["account_id"])
    method = acct["cost_basis_method"] if acct else "FIFO"
    proceeds_usd = D(w["notional_usd"])
    dispose(w["account_id"], w["asset"], D(w["amount"]), proceeds_usd, method, decimals)
    w["status"] = "BROADCAST"
    touch(w)
    return success(withdrawal_out(w))


@bp.route("/withdrawals/<wid>/confirm-onchain", methods=["POST"])
def confirm_onchain(wid):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    w = get_withdrawal_or_404(wid)
    if w["status"] != "BROADCAST":
        raise err("ERR_INVALID_STATE", "Withdrawal not in BROADCAST state")
    w["status"] = "COMPLETED"
    touch(w)
    return success(withdrawal_out(w))
