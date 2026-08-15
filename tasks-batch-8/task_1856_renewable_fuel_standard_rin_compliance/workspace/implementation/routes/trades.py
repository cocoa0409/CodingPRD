"""RINTrade endpoints: create, get, list, pay, deliver, verify, cancel, invalidate."""
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    invalid_request, not_found, reference_not_found, invalid_state,
    segregation, vendor_not_approved, verification_window_expired,
    rin_invalidated,
)
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import trade_view
from services import cascade

bp = Blueprint("trades", __name__)

_D_CODES = ("D3", "D4", "D5", "D6")


def _get_trade(trade_id):
    trade = db.rin_trades.get(trade_id)
    if trade is None:
        raise not_found("RIN trade not found")
    return trade


def _touch_account(account):
    account["version"] += 1
    account["updated_at"] = db.now_utc()


@bp.route("/rfs/rin-trades", methods=["POST"])
def create_trade():
    user_id, _ = require_roles("Trader")
    body = json_body()

    account_id = body.get("account_id")
    vendor_id = body.get("vendor_id")
    d_code = body.get("d_code")
    vintage_year = body.get("vintage_year")
    rin_qty = body.get("rin_qty")
    price_per_rin_cents = body.get("price_per_rin_cents")

    # --- Request shape (priority 5) ---
    for field, value in (("account_id", account_id), ("vendor_id", vendor_id),
                         ("d_code", d_code), ("vintage_year", vintage_year),
                         ("rin_qty", rin_qty), ("price_per_rin_cents", price_per_rin_cents)):
        if value is None:
            raise invalid_request(f"{field} is required")
    if d_code not in _D_CODES:
        raise invalid_request("d_code must be one of D3, D4, D5, D6")
    if not isinstance(vintage_year, int) or isinstance(vintage_year, bool):
        raise invalid_request("vintage_year must be an integer")
    if not isinstance(rin_qty, int) or isinstance(rin_qty, bool) or rin_qty <= 0:
        raise invalid_request("rin_qty must be a positive integer")
    if not isinstance(price_per_rin_cents, int) or isinstance(price_per_rin_cents, bool) or price_per_rin_cents <= 0:
        raise invalid_request("price_per_rin_cents must be a positive integer")

    # --- Referential integrity (priority 6) ---
    account = db.compliance_accounts.get(account_id)
    if account is None:
        raise reference_not_found("Referenced account does not exist")
    vendor = db.vendors.get(vendor_id)
    if vendor is None or vendor["account_id"] != account_id:
        raise reference_not_found("Referenced vendor does not exist for this account")

    total_price_cents = rin_qty * price_per_rin_cents
    now = db.now_utc()
    trade = {
        "id": db.new_id(),
        "account_id": account_id,
        "vendor_id": vendor_id,
        "d_code": d_code,
        "vintage_year": vintage_year,
        "rin_qty": rin_qty,
        "price_per_rin_cents": price_per_rin_cents,
        "total_price_cents": total_price_cents,
        "payment_status": "UNPAID",
        "transfer_status": "PENDING",
        "created_by_user_id": user_id,
        "delivered_at": None,
        "verified_by_user_id": None,
        "retention_until": db.retention_until_from(now),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.rin_trades[trade["id"]] = trade

    # Escrow reservation
    account["escrow_reserved_cents"] += total_price_cents
    _touch_account(account)
    return ok_object(trade_view(trade), status=201)


@bp.route("/rfs/rin-trades/<trade_id>", methods=["GET"])
def get_trade(trade_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    return ok_object(trade_view(_get_trade(trade_id)))


@bp.route("/rfs/rin-trades", methods=["GET"])
def list_trades():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    vendor_id = request.args.get("vendor_id")
    rows = list(db.rin_trades.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([trade_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/rin-trades/<trade_id>/pay", methods=["POST"])
def pay_trade(trade_id):
    require_roles("Trader")
    trade = _get_trade(trade_id)
    if trade["payment_status"] != "UNPAID":
        raise invalid_state("Trade is not UNPAID")
    if trade["transfer_status"] != "PENDING":
        raise invalid_state("Trade transfer is not PENDING")

    account = db.compliance_accounts[trade["account_id"]]
    trade["payment_status"] = "PAID"
    trade["version"] += 1
    trade["updated_at"] = db.now_utc()
    account["escrow_reserved_cents"] -= trade["total_price_cents"]
    account["spent_cents"] += trade["total_price_cents"]
    _touch_account(account)
    return ok_object(trade_view(trade))


@bp.route("/rfs/rin-trades/<trade_id>/deliver", methods=["POST"])
def deliver_trade(trade_id):
    require_roles("Trader")
    trade = _get_trade(trade_id)
    if trade["transfer_status"] != "PENDING":
        raise invalid_state("Trade transfer is not PENDING")
    if trade["payment_status"] != "PAID":
        raise invalid_state("Trade must be PAID before delivery")

    now = db.now_utc()
    trade["transfer_status"] = "DELIVERED"
    trade["delivered_at"] = now
    trade["version"] += 1
    trade["updated_at"] = now

    # Mint the PURCHASED lot: gallon_qty 0, equivalence 1.0, separated immediately
    lot = {
        "id": db.new_id(),
        "account_id": trade["account_id"],
        "origin": "PURCHASED",
        "vendor_id": trade["vendor_id"],
        "trade_id": trade["id"],
        "d_code": trade["d_code"],
        "vintage_year": trade["vintage_year"],
        "gallon_qty": 0,
        "equivalence_value": 1.0,
        "rin_qty": trade["rin_qty"],
        "attached_qty": 0,
        "separated_qty": trade["rin_qty"],
        "pending_retired_qty": 0,
        "retired_qty": 0,
        "invalidated_qty": 0,
        "expired_qty": 0,
        "available_qty": trade["rin_qty"],
        "unit_cost_cents": trade["price_per_rin_cents"],
        "status": "ACTIVE",
        "retention_until": db.retention_until_from(now),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.rin_lots[lot["id"]] = lot
    return ok_object(trade_view(trade))


@bp.route("/rfs/rin-trades/<trade_id>/verify", methods=["POST"])
def verify_trade(trade_id):
    user_id, _ = require_roles("ComplianceManager")
    trade = _get_trade(trade_id)

    # Segregation of duties (priority 3): verifier != trade creator
    if user_id == trade["created_by_user_id"]:
        raise segregation("Trade creator may not verify their own trade")

    # State check: transfer must be DELIVERED
    if trade["transfer_status"] == "INVALIDATED":
        raise rin_invalidated("Trade has been INVALIDATED")
    if trade["transfer_status"] != "DELIVERED":
        raise invalid_state("Trade transfer is not DELIVERED")

    # Regulatory gate: vendor must be APPROVED at verification time
    vendor = db.vendors.get(trade["vendor_id"])
    if vendor is None or vendor["diligence_status"] != "APPROVED":
        raise vendor_not_approved("Vendor must be APPROVED to verify a trade")

    # Temporal gate: within 30 days of delivery (exactly the 30th day is inside)
    now = db.now_utc()
    if now > trade["delivered_at"] + timedelta(days=30):
        raise verification_window_expired("Verification window (30 days after delivery) expired")

    trade["transfer_status"] = "VERIFIED"
    trade["verified_by_user_id"] = user_id
    trade["version"] += 1
    trade["updated_at"] = now
    return ok_object(trade_view(trade))


@bp.route("/rfs/rin-trades/<trade_id>/cancel", methods=["POST"])
def cancel_trade(trade_id):
    require_roles("Trader")
    trade = _get_trade(trade_id)
    if trade["transfer_status"] != "PENDING":
        raise invalid_state("Only a PENDING trade can be cancelled")

    account = db.compliance_accounts[trade["account_id"]]
    if trade["payment_status"] == "PAID":
        # Refund: spend refunded, payment -> REFUNDED
        trade["payment_status"] = "REFUNDED"
        account["spent_cents"] -= trade["total_price_cents"]
        _touch_account(account)
    else:
        # Escrow release: payment stays UNPAID
        account["escrow_reserved_cents"] -= trade["total_price_cents"]
        _touch_account(account)

    trade["transfer_status"] = "CANCELLED"
    trade["version"] += 1
    trade["updated_at"] = db.now_utc()
    return ok_object(trade_view(trade))


@bp.route("/rfs/rin-trades/<trade_id>/invalidate", methods=["POST"])
def invalidate_trade(trade_id):
    require_roles("ComplianceManager")
    trade = _get_trade(trade_id)
    if trade["transfer_status"] == "INVALIDATED":
        raise rin_invalidated("Trade is already INVALIDATED")
    if trade["transfer_status"] not in ("DELIVERED", "VERIFIED"):
        raise invalid_state("Only a DELIVERED or VERIFIED trade can be invalidated")

    cascade.invalidate_trade(trade)
    return ok_object(trade_view(trade))
