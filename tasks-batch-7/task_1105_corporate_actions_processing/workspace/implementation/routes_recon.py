"""Custodian statements, recon breaks, and entitlement read views (PRD 3.9)."""

from flask import Blueprint

import db
import util
import errors as errmod
from errors import ApiError
from helpers import (respond, respond_list, require_roles, body, req_str,
                     req_enum, req_date, paginate, apply_filters, stamp_new,
                     touch)
from recon import reconcile_statement

bp = Blueprint("recon", __name__)

ALL = ("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
       "AccountHolder ClaimsExaminer CustodianFeed").split()


# ---------------------------------------------------------------------------
# custodian statements
# ---------------------------------------------------------------------------

@bp.post("/api/custodian-statements")
def create_statement():
    require_roles("CustodianFeed")
    data = body()
    # --- priority 3: shape ---
    source_id = req_str(data, "source_id")
    start_s, start = req_date(data, "coverage_start_date")
    end_s, end = req_date(data, "coverage_end_date")
    if start > end:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "coverage_start_date must not fall after coverage_end_date")
    if "lines" not in data or data["lines"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400, "Required field missing: lines")
    lines = data["lines"]
    if not isinstance(lines, list):
        raise ApiError(errmod.E_INVALID_REQUEST, 400, "lines must be an array")
    norm_lines = []
    for raw in lines:
        if not isinstance(raw, dict):
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "each statement line must be an object")
        account_id = raw.get("account_id")
        security_id = raw.get("security_id")
        quantity = raw.get("quantity")
        if not isinstance(account_id, str) or not account_id.strip():
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "line account_id must be a non-empty string")
        if not isinstance(security_id, str) or not security_id.strip():
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "line security_id must be a non-empty string")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "line quantity must be a number")
        cash_cents = raw.get("cash_cents")
        if cash_cents is not None and (isinstance(cash_cents, bool)
                                       or not isinstance(cash_cents, int)):
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "line cash_cents must be an integer")
        event_id = raw.get("event_id")
        if event_id is not None and not isinstance(event_id, str):
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "line event_id must be a string")
        norm_lines.append({
            "account_id": account_id,
            "security_id": security_id,
            "quantity": quantity,
            "cash_cents": cash_cents,
            "event_id": event_id,
        })
    # --- priority 4: existence ---
    source = db.get("event_sources", source_id)
    if source is None:
        raise ApiError(errmod.E_EVENT_SOURCE_NOT_FOUND, 404, "Event source not found")
    for line in norm_lines:
        if db.get("accounts", line["account_id"]) is None:
            raise ApiError(errmod.E_ACCOUNT_NOT_FOUND, 404, "Account not found")
        if db.get("securities", line["security_id"]) is None:
            raise ApiError(errmod.E_SECURITY_NOT_FOUND, 404, "Security not found")
        if line["event_id"] is not None and db.get("events", line["event_id"]) is None:
            raise ApiError(errmod.E_EVENT_NOT_FOUND, 404, "Event not found")
    # --- priority 9: coverage overlap (closed intervals, per source) ---
    for other in db.all_rows("custodian_statements"):
        if other["source_id"] != source_id:
            continue
        o_start = util.parse_date_iso(other["coverage_start_date"])
        o_end = util.parse_date_iso(other["coverage_end_date"])
        if start <= o_end and o_start <= end:
            raise ApiError(errmod.E_STATEMENT_COVERAGE_OVERLAP, 409,
                           "Coverage window overlaps another statement from "
                           "this source")
    # --- priority 11: source must be CUSTODIAN ---
    if source["source_type"] != "CUSTODIAN":
        raise ApiError(errmod.E_SOURCE_NOT_CUSTODIAN, 422,
                       "Statement source must be a CUSTODIAN source")
    # --- create + synchronous reconciliation ---
    statement = {
        "source_id": source_id,
        "coverage_start_date": start_s,
        "coverage_end_date": end_s,
        "lines": norm_lines,
        "status": "RECEIVED",
    }
    stamp_new(statement)
    db.insert("custodian_statements", statement)
    reconcile_statement(statement)
    statement["status"] = "RECONCILED"
    touch(statement)
    return respond(db.public(statement), 201)


@bp.get("/api/custodian-statements")
def list_statements():
    require_roles(*ALL)
    rows = apply_filters(db.all_rows("custodian_statements"), [
        ("source_id", "source_id"),
        ("status", "status"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/custodian-statements/<rid>")
def get_statement(rid):
    require_roles(*ALL)
    rec = db.get("custodian_statements", rid)
    if rec is None:
        raise ApiError(errmod.E_CUSTODIAN_STATEMENT_NOT_FOUND, 404,
                       "Custodian statement not found")
    return respond(db.public(rec), 200)


# ---------------------------------------------------------------------------
# recon breaks
# ---------------------------------------------------------------------------

@bp.get("/api/recon-breaks")
def list_breaks():
    require_roles(*ALL)
    rows = apply_filters(db.all_rows("recon_breaks"), [
        ("statement_id", "statement_id"),
        ("event_id", "event_id"),
        ("account_id", "account_id"),
        ("security_id", "security_id"),
        ("break_type", "break_type"),
        ("status", "status"),
        ("auto_claim_id", "auto_claim_id"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/recon-breaks/<rid>")
def get_break(rid):
    require_roles(*ALL)
    rec = db.get("recon_breaks", rid)
    if rec is None:
        raise ApiError(errmod.E_RECON_BREAK_NOT_FOUND, 404, "Recon break not found")
    return respond(db.public(rec), 200)


@bp.post("/api/recon-breaks/<rid>/resolve")
def resolve_break(rid):
    require_roles("OperationsManager")
    data = body()
    resolution = req_enum(data, "resolution", ["RESOLVED", "WRITTEN_OFF"])
    note = data.get("resolution_note")
    if not isinstance(note, str) or not note.strip():
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "resolution_note is required on manual resolve")
    rec = db.get("recon_breaks", rid)
    if rec is None:
        raise ApiError(errmod.E_RECON_BREAK_NOT_FOUND, 404, "Recon break not found")
    if rec["status"] != "OPEN":
        raise ApiError(errmod.E_RECON_BREAK_NOT_OPEN, 409,
                       "Resolve requires an OPEN break")
    rec["resolution_note"] = note
    if resolution == "RESOLVED":
        rec["resolution"] = "MANUAL"
        rec["status"] = "RESOLVED"
    else:
        rec["resolution"] = "WRITTEN_OFF"
        rec["status"] = "WRITTEN_OFF"
    touch(rec)
    return respond(db.public(rec), 200)


# ---------------------------------------------------------------------------
# entitlements (read-only views)
# ---------------------------------------------------------------------------

@bp.get("/api/entitlements")
def list_entitlements():
    require_roles(*ALL)
    rows = apply_filters(db.all_rows("entitlements"), [
        ("event_id", "event_id"),
        ("account_id", "account_id"),
        ("status", "status"),
        ("supersedes_entitlement_id", "supersedes_entitlement_id"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/entitlements/<rid>")
def get_entitlement(rid):
    require_roles(*ALL)
    rec = db.get("entitlements", rid)
    if rec is None:
        raise ApiError(errmod.E_ENTITLEMENT_NOT_FOUND, 404, "Entitlement not found")
    return respond(db.public(rec), 200)
