"""Desk setup routes: logical clock, securities, accounts, position lots,
event sources, source notifications."""

from flask import Blueprint, request

import db
import util
import errors as errmod
from errors import ApiError
from helpers import (respond, respond_list, require_roles, body, req_str,
                     opt_int, req_int, req_enum, req_date, paginate,
                     apply_filters, stamp_new, stamp_immutable, touch)
from domain import SOURCE_TYPES, EVENT_TYPES, recompute_account

bp = Blueprint("setup", __name__)


# ---------------------------------------------------------------------------
# logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("DeskAdministrator")
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: to_iso8601")
    try:
        dt = util.parse_datetime_iso(raw)
    except ValueError:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "to_iso8601 must be an ISO 8601 datetime")
    util.set_clock(dt)
    return respond({"current_utc": util.fmt_clock(dt)}, 200)


# ---------------------------------------------------------------------------
# securities
# ---------------------------------------------------------------------------

@bp.post("/api/securities")
def create_security():
    require_roles("DeskAdministrator")
    data = body()
    ticker = req_str(data, "ticker")
    cusip = req_str(data, "cusip")
    name = req_str(data, "name")
    for s in db.all_rows("securities"):
        if s["ticker"] == ticker or s["cusip"] == cusip:
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "ticker and cusip must be unique across all securities")
    rec = {"ticker": ticker, "cusip": cusip, "name": name, "status": "ACTIVE"}
    stamp_new(rec)
    db.insert("securities", rec)
    return respond(db.public(rec), 201)


@bp.get("/api/securities")
def list_securities():
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rows = apply_filters(db.all_rows("securities"), [("status", "status")])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/securities/<rid>")
def get_security(rid):
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rec = db.get("securities", rid)
    if rec is None:
        raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404, "Security not found")
    return respond(db.public(rec), 200)


@bp.put("/api/securities/<rid>")
def update_security(rid):
    require_roles("DeskAdministrator")
    data = body()
    status = req_enum(data, "status", ["ACTIVE", "SUSPENDED"])
    rec = db.get("securities", rid)
    if rec is None:
        raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404, "Security not found")
    valid = (rec["status"] == "ACTIVE" and status == "SUSPENDED") or \
            (rec["status"] == "SUSPENDED" and status == "ACTIVE")
    if not valid:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Invalid security status transition")
    rec["status"] = status
    touch(rec)
    return respond(db.public(rec), 200)


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------

@bp.post("/api/accounts")
def create_account():
    require_roles("DeskAdministrator")
    data = body()
    account_number = req_str(data, "account_number")
    holder_name = req_str(data, "holder_name")
    opening = opt_int(data, "opening_cash_cents", 0)
    for a in db.all_rows("accounts"):
        if a["account_number"] == account_number:
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "account_number must be unique across accounts")
    rec = {
        "account_number": account_number,
        "holder_name": holder_name,
        "opening_cash_cents": opening,
        "cash_balance_cents": opening,
        "total_cost_basis_cents": 0,
        "pending_entitlement_count": 0,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.insert("accounts", rec)
    return respond(db.public(rec), 201)


@bp.get("/api/accounts")
def list_accounts():
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rows = apply_filters(db.all_rows("accounts"), [("status", "status")])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/accounts/<rid>")
def get_account(rid):
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rec = db.get("accounts", rid)
    if rec is None:
        raise ApiError(errmod.E_ACCOUNT_NOT_FOUND, 404, "Account not found")
    return respond(db.public(rec), 200)


@bp.put("/api/accounts/<rid>")
def update_account(rid):
    require_roles("OperationsManager")
    data = body()
    status = req_enum(data, "status", ["ACTIVE", "FROZEN", "CLOSED"])
    rec = db.get("accounts", rid)
    if rec is None:
        raise ApiError(errmod.E_ACCOUNT_NOT_FOUND, 404, "Account not found")
    valid = (rec["status"], status) in [
        ("ACTIVE", "FROZEN"), ("FROZEN", "ACTIVE"),
        ("ACTIVE", "CLOSED"), ("FROZEN", "CLOSED"),
    ]
    if not valid:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Invalid account status transition")
    if status == "CLOSED":
        # guarded: no OPEN lot with quantity > 0 and no PROJECTED/FIRM entitlement
        for lot in db.all_rows("position_lots"):
            if (lot["account_id"] == rid and lot["status"] == "OPEN"
                    and util.dec_of(lot["quantity"]) > 0):
                raise ApiError(errmod.E_ACCOUNT_NOT_SETTLED, 409,
                               "Account has OPEN position lots")
        for ent in db.all_rows("entitlements"):
            if ent["account_id"] == rid and ent["status"] in ("PROJECTED", "FIRM"):
                raise ApiError(errmod.E_ACCOUNT_NOT_SETTLED, 409,
                               "Account has pending entitlements")
    rec["status"] = status
    touch(rec)
    return respond(db.public(rec), 200)


# ---------------------------------------------------------------------------
# position lots
# ---------------------------------------------------------------------------

@bp.post("/api/position-lots")
def create_lot():
    require_roles("DeskAdministrator")
    data = body()
    account_id = req_str(data, "account_id")
    security_id = req_str(data, "security_id")
    if "quantity" not in data or data["quantity"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400, "Required field missing: quantity")
    quantity = data["quantity"]
    acquisition_date, _ = req_date(data, "acquisition_date")
    basis = req_int(data, "cost_basis_total_cents")
    # quantity: number > 0 with at most 4 decimal places
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
        raise ApiError(errmod.E_LOT_QUANTITY_INVALID, 400,
                       "quantity must be a number")
    q = util.D(quantity)
    if q <= 0 or -q.as_tuple().exponent > 4:
        raise ApiError(errmod.E_LOT_QUANTITY_INVALID, 400,
                       "quantity must be > 0 with no more than 4 decimal places")
    # body FK existence in declared field order: account_id, then security_id
    if db.get("accounts", account_id) is None:
        raise ApiError(errmod.E_ACCOUNT_NOT_FOUND, 404, "Account not found")
    if db.get("securities", security_id) is None:
        raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404, "Security not found")
    rec = {
        "account_id": account_id,
        "security_id": security_id,
        "origin_booking_id": None,
        "quantity": float(q),
        "acquisition_date": acquisition_date,
        "cost_basis_total_cents": basis,
        "status": "OPEN",
    }
    stamp_new(rec)
    db.insert("position_lots", rec)
    recompute_account(account_id)
    return respond(db.public(rec), 201)


@bp.get("/api/position-lots")
def list_lots():
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rows = apply_filters(db.all_rows("position_lots"), [
        ("account_id", "account_id"),
        ("security_id", "security_id"),
        ("origin_booking_id", "origin_booking_id"),
        ("status", "status"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/position-lots/<rid>")
def get_lot(rid):
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rec = db.get("position_lots", rid)
    if rec is None:
        raise ApiError(errmod.E_POSITION_LOT_NOT_FOUND, 404, "Position lot not found")
    return respond(db.public(rec), 200)


# ---------------------------------------------------------------------------
# event sources
# ---------------------------------------------------------------------------

@bp.post("/api/event-sources")
def create_source():
    require_roles("DeskAdministrator")
    data = body()
    name = req_str(data, "name")
    source_type = req_enum(data, "source_type", SOURCE_TYPES)
    weight = req_int(data, "reliability_weight")
    if weight < 0:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "reliability_weight must be a non-negative integer")
    rec = {"name": name, "source_type": source_type, "reliability_weight": weight}
    stamp_new(rec)
    db.insert("event_sources", rec)
    return respond(db.public(rec), 201)


@bp.get("/api/event-sources")
def list_sources():
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rows = apply_filters(db.all_rows("event_sources"), [("source_type", "source_type")])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/event-sources/<rid>")
def get_source(rid):
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rec = db.get("event_sources", rid)
    if rec is None:
        raise ApiError(errmod.E_EVENT_SOURCE_NOT_FOUND, 404, "Event source not found")
    return respond(db.public(rec), 200)


# ---------------------------------------------------------------------------
# source notifications
# ---------------------------------------------------------------------------

@bp.post("/api/source-notifications")
def create_notification():
    require_roles("VendorFeed")
    data = body()
    source_id = req_str(data, "source_id")
    security_id = req_str(data, "security_id")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    record_date, _ = req_date(data, "record_date")
    if "announced_terms" not in data or data["announced_terms"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: announced_terms")
    announced_terms = data["announced_terms"]
    if not isinstance(announced_terms, dict):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "announced_terms must be an object")
    # body FK existence in declared field order: source_id, then security_id
    if db.get("event_sources", source_id) is None:
        raise ApiError(errmod.E_EVENT_SOURCE_NOT_FOUND, 404, "Event source not found")
    if db.get("securities", security_id) is None:
        raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404, "Security not found")
    rec = {
        "source_id": source_id,
        "security_id": security_id,
        "event_type": event_type,
        "record_date": record_date,
        "announced_terms": announced_terms,
        "status": "RECEIVED",
    }
    stamp_immutable(rec)
    db.insert("source_notifications", rec)
    return respond(db.public(rec), 201)


@bp.get("/api/source-notifications")
def list_notifications():
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rows = apply_filters(db.all_rows("source_notifications"), [
        ("source_id", "source_id"),
        ("security_id", "security_id"),
        ("status", "status"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/source-notifications/<rid>")
def get_notification(rid):
    require_roles(*("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
                    "AccountHolder ClaimsExaminer CustodianFeed").split())
    rec = db.get("source_notifications", rid)
    if rec is None:
        raise ApiError(errmod.E_SOURCE_NOTIFICATION_NOT_FOUND, 404,
                       "Source notification not found")
    return respond(db.public(rec), 200)


@bp.post("/api/source-notifications/<rid>/reject")
def reject_notification(rid):
    require_roles("EventAnalyst")
    rec = db.get("source_notifications", rid)
    if rec is None:
        raise ApiError(errmod.E_SOURCE_NOTIFICATION_NOT_FOUND, 404,
                       "Source notification not found")
    if rec["status"] != "RECEIVED":
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Only a RECEIVED notification can be rejected")
    rec["status"] = "REJECTED"  # immutable record: no updated_at/version fields
    return respond(db.public(rec), 200)
