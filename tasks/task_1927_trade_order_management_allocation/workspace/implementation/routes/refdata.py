"""Accounts, securities, brokers + their status endpoints (DeskAdmin writes)."""
from flask import Blueprint

import audit
import db
import services as svc
from errors import raise_err
from middleware import ALL_ROLES, body, require_enum, require_roles, require_str
from response import ok_object
from util import public

bp = Blueprint("refdata", __name__)

ACCOUNT_TYPES = ("DISCRETIONARY", "PROPRIETARY", "ERROR")
ASSET_CLASSES = ("EQUITY", "FIXED_INCOME")


# ------------------------------------------------------------- accounts ----
@bp.post("/trading/accounts")
@require_roles("DeskAdmin")
def create_account():
    b = body()
    account_code = require_str(b, "account_code")
    display_name = require_str(b, "display_name")
    account_type = require_enum(b, "account_type", ACCOUNT_TYPES)
    custodian_name = require_str(b, "custodian_name")
    for a in db.store["accounts"].values():
        if a["account_code"] == account_code:
            raise_err("ERR_INVALID_REQUEST", "account_code must be unique")
    rec = svc.new_record()
    rec.update({"account_code": account_code, "display_name": display_name,
                "account_type": account_type, "custodian_name": custodian_name,
                "status": "ACTIVE"})
    db.store["accounts"][rec["id"]] = rec
    audit.record_request("Account", rec["id"], "ACCOUNT_CREATED",
                         f"account_code: {account_code}; account_type: {account_type}")
    return ok_object(public(rec), 201)


@bp.get("/trading/accounts/<accountId>")
@require_roles(*ALL_ROLES)
def get_account(accountId):
    return ok_object(public(svc.fetch("accounts", accountId, "ERR_ACCOUNT_NOT_FOUND")))


@bp.post("/trading/accounts/<accountId>/status")
@require_roles("DeskAdmin")
def set_account_status(accountId):
    b = body()
    to_status = require_enum(b, "to_status", ("ACTIVE", "SUSPENDED"))
    acc = svc.fetch("accounts", accountId, "ERR_ACCOUNT_NOT_FOUND")
    if acc["status"] == to_status:
        raise_err("ERR_INVALID_STATE", f"Account is already {to_status}")
    if to_status == "SUSPENDED":
        svc.suspend_account(acc, automatic=False)
    else:
        acc["status"] = "ACTIVE"
        svc.touch(acc)
        audit.record_request("Account", acc["id"], "ACCOUNT_RESUMED",
                             "status: SUSPENDED -> ACTIVE")
    return ok_object(public(acc))


# ----------------------------------------------------------- securities ----
@bp.post("/trading/securities")
@require_roles("DeskAdmin")
def create_security():
    b = body()
    ticker = require_str(b, "ticker")
    asset_class = require_enum(b, "asset_class", ASSET_CLASSES)
    currency = b.get("currency", "USD")
    if not isinstance(currency, str) or not currency.strip():
        raise_err("ERR_INVALID_REQUEST", "Field 'currency' must be a non-empty string")
    lot_size = b.get("lot_size")
    if not isinstance(lot_size, int) or isinstance(lot_size, bool) or lot_size < 1:
        raise_err("ERR_INVALID_REQUEST", "Field 'lot_size' must be an integer >= 1")
    ref = b.get("reference_price_cents")
    if not isinstance(ref, int) or isinstance(ref, bool) or ref <= 0:
        raise_err("ERR_INVALID_REQUEST", "Field 'reference_price_cents' must be a positive integer")
    for s in db.store["securities"].values():
        if s["ticker"] == ticker:
            raise_err("ERR_INVALID_REQUEST", "ticker must be unique")
    rec = svc.new_record()
    rec.update({"ticker": ticker, "asset_class": asset_class, "currency": currency,
                "lot_size": lot_size, "reference_price_cents": ref, "status": "ACTIVE"})
    db.store["securities"][rec["id"]] = rec
    audit.record_request("Security", rec["id"], "SECURITY_CREATED",
                         f"ticker: {ticker}; asset_class: {asset_class}")
    return ok_object(public(rec), 201)


@bp.get("/trading/securities/<securityId>")
@require_roles(*ALL_ROLES)
def get_security(securityId):
    return ok_object(public(svc.fetch("securities", securityId, "ERR_SECURITY_NOT_FOUND")))


@bp.post("/trading/securities/<securityId>/status")
@require_roles("DeskAdmin")
def set_security_status(securityId):
    b = body()
    to_status = require_enum(b, "to_status", ("ACTIVE", "HALTED"))
    sec = svc.fetch("securities", securityId, "ERR_SECURITY_NOT_FOUND")
    if sec["status"] == to_status:
        raise_err("ERR_INVALID_STATE", f"Security is already {to_status}")
    frm = sec["status"]
    sec["status"] = to_status
    svc.touch(sec)
    action = "SECURITY_HALTED" if to_status == "HALTED" else "SECURITY_RESUMED"
    audit.record_request("Security", sec["id"], action, f"status: {frm} -> {to_status}")
    return ok_object(public(sec))


# --------------------------------------------------------------- brokers ---
@bp.post("/trading/brokers")
@require_roles("DeskAdmin")
def create_broker():
    b = body()
    broker_code = require_str(b, "broker_code")
    display_name = require_str(b, "display_name")
    rate = b.get("commission_rate_bp")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        raise_err("ERR_INVALID_REQUEST", "Field 'commission_rate_bp' must be a positive number")
    classes = b.get("supported_asset_classes")
    if not isinstance(classes, list) or not classes or \
            any(c not in ASSET_CLASSES for c in classes):
        raise_err("ERR_INVALID_REQUEST",
                  "Field 'supported_asset_classes' must be a non-empty array of asset classes")
    for br in db.store["brokers"].values():
        if br["broker_code"] == broker_code:
            raise_err("ERR_INVALID_REQUEST", "broker_code must be unique")
    rec = svc.new_record()
    rec.update({"broker_code": broker_code, "display_name": display_name,
                "commission_rate_bp": rate, "supported_asset_classes": list(classes),
                "status": "ACTIVE"})
    db.store["brokers"][rec["id"]] = rec
    audit.record_request("Broker", rec["id"], "BROKER_CREATED",
                         f"broker_code: {broker_code}; commission_rate_bp: {rate}")
    return ok_object(public(rec), 201)


@bp.get("/trading/brokers/<brokerId>")
@require_roles(*ALL_ROLES)
def get_broker(brokerId):
    return ok_object(public(svc.fetch("brokers", brokerId, "ERR_BROKER_NOT_FOUND")))


@bp.post("/trading/brokers/<brokerId>/status")
@require_roles("DeskAdmin")
def set_broker_status(brokerId):
    b = body()
    to_status = require_enum(b, "to_status", ("ACTIVE", "SUSPENDED"))
    brk = svc.fetch("brokers", brokerId, "ERR_BROKER_NOT_FOUND")
    if brk["status"] == to_status:
        raise_err("ERR_INVALID_STATE", f"Broker is already {to_status}")
    frm = brk["status"]
    brk["status"] = to_status
    svc.touch(brk)
    action = "BROKER_SUSPENDED" if to_status == "SUSPENDED" else "BROKER_RESUMED"
    audit.record_request("Broker", brk["id"], action, f"status: {frm} -> {to_status}")
    return ok_object(public(brk))
