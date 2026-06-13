"""ComplianceLedgerEntry routes (PRD §3.12). Read-only audit log."""
from flask import Blueprint, request

from db import db
from middleware import authenticate, authorize
from response import success
from serialize import public
from validate import get_or_404
from pagination import paginate, sorted_by_creation

bp = Blueprint("ledger", __name__)


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger():
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    with db.lock:
        items = list(db.ledger_entries.values())
        winery_id = request.args.get("winery_id")
        entry_type = request.args.get("entry_type")
        subject_type = request.args.get("subject_type")
        subject_id = request.args.get("subject_id")
        if winery_id is not None:
            items = [e for e in items if e["winery_id"] == winery_id]
        if entry_type is not None:
            items = [e for e in items if e["entry_type"] == entry_type]
        if subject_type is not None:
            items = [e for e in items if e["subject_type"] == subject_type]
        if subject_id is not None:
            items = [e for e in items if e["subject_id"] == subject_id]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(e) for e in page], pagination=pg)


@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger(entry_id):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    with db.lock:
        e = get_or_404(db.ledger_entries, entry_id)
        return success(public(e))
