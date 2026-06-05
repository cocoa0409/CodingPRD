"""Read/list routes for CleanerPayout and LedgerEntry."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (require_resource, parse_pagination, paginate)
from response import success, list_success

bp = Blueprint("payouts_ledger", __name__)


@bp.route("/cleaning/cleaner-payouts/<pid>", methods=["GET"])
def get_payout(pid):
    principal = authenticate()
    authorize(principal, {"Cleaner", "PlatformAdmin"})
    rec = require_resource(db.cleaner_payouts, pid, "cleaner_payout")
    if principal.role == "Cleaner" and principal.user_id != rec["cleaner_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "payout is not for this cleaner")
    return success(S.cleaner_payout(rec), status=200)


@bp.route("/cleaning/cleaner-payouts", methods=["GET"])
def list_payouts():
    principal = authenticate()
    authorize(principal, {"Cleaner", "PlatformAdmin"})
    limit, offset = parse_pagination()
    records = list(db.cleaner_payouts.values())
    for key in ("cleaner_id", "booking_id"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    if principal.role == "Cleaner":
        records = [r for r in records if r["cleaner_id"] == principal.user_id]
    page, total = paginate(records, limit, offset)
    return list_success([S.cleaner_payout(r) for r in page], limit, offset, total)


@bp.route("/cleaning/ledger-entries/<lid>", methods=["GET"])
def get_ledger_entry(lid):
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    rec = require_resource(db.ledger_entries, lid, "ledger_entry")
    if principal.role == "Customer" and principal.user_id != rec["customer_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "ledger entry is not for this customer")
    return success(S.ledger_entry(rec), status=200)


@bp.route("/cleaning/ledger-entries", methods=["GET"])
def list_ledger_entries():
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    records = list(db.ledger_entries.values())
    for key in ("customer_id", "booking_id", "kind"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    if principal.role == "Customer":
        records = [r for r in records if r["customer_id"] == principal.user_id]
    page, total = paginate(records, limit, offset)
    return list_success([S.ledger_entry(r) for r in page], limit, offset, total)
