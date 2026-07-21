"""Escheat record (2) and budget entry (2) read endpoints, plus the clock hook (1)."""
from flask import Blueprint, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err

bp = Blueprint("ledger", __name__)


@bp.get("/api/escheat-records/<rid>")
@mw.require("ProgramAdmin", "FinanceOfficer")
def read_escheat_record(rid):
    return resp.ok(ser.escheat_record(db.get_escheat_record(rid)))


@bp.get("/api/escheat-records")
@mw.require("ProgramAdmin", "FinanceOfficer")
def list_escheat_records():
    items = db.by_created(list(db.escheat_records.values()))
    for field in ("payout_id", "program_id", "jurisdiction"):
        value = request.args.get(field)
        if value:
            items = [r for r in items if r[field] == value]
    return resp.paginated(items, ser.escheat_record)


@bp.get("/api/budget-entries/<eid>")
@mw.require("ProgramAdmin", "ClaimsProcessor", "FinanceOfficer")
def read_budget_entry(eid):
    return resp.ok(ser.budget_entry(db.get_budget_entry(eid)))


@bp.get("/api/budget-entries")
@mw.require("ProgramAdmin", "ClaimsProcessor", "FinanceOfficer")
def list_budget_entries():
    items = db.by_created(list(db.budget_entries.values()))
    for field in ("program_id", "claim_id", "entry_type"):
        value = request.args.get(field)
        if value:
            items = [e for e in items if e[field] == value]
    return resp.paginated(items, ser.budget_entry)


@bp.post("/_clock/set_current_utc")
@mw.require("ProgramAdmin")
def set_clock():
    data = mw.body()
    target = mw.as_datetime(data, "to_iso8601")
    db.set_clock(target)
    return resp.ok({"current_utc": db.iso(db.now())})
