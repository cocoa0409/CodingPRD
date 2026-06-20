"""SubstantiationReceipt and LedgerEntry read endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from middleware import get_identity, require_role, get_pagination, paginate
from response import object_response, array_response
from services import serialize
from services.lookup import get_or_404, get_receipt_or_404, filtered_sorted

bp = Blueprint("receipts", __name__)

RECEIPT_ROLES = {"SponsorAdmin", "DonorAdvisor", "ContributionAdmin"}
LEDGER_ROLES = {"SponsorAdmin", "DonorAdvisor", "GrantOfficer", "ComplianceOfficer"}


# ---------------- SubstantiationReceipt ----------------
@bp.get("/daf/receipts/<receipt_id>")
def get_receipt(receipt_id):
    _, role = get_identity()
    require_role(role, RECEIPT_ROLES)
    # PRD 2.5 / 3.9: a missing receipt id returns ERR_RECEIPT_NOT_FOUND.
    receipt = get_receipt_or_404(receipt_id)
    return object_response(serialize.receipt(receipt))


@bp.get("/daf/receipts")
def list_receipts():
    _, role = get_identity()
    require_role(role, RECEIPT_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.receipts, {
        "contribution_id": request.args.get("contribution_id"),
        "donor_account_id": request.args.get("donor_account_id"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.receipt(r) for r in page], meta)


# ---------------- LedgerEntry ----------------
@bp.get("/daf/ledger-entries/<ledger_entry_id>")
def get_ledger_entry(ledger_entry_id):
    _, role = get_identity()
    require_role(role, LEDGER_ROLES)
    entry = get_or_404(db.ledger_entries, ledger_entry_id)
    return object_response(serialize.ledger_entry(entry))


@bp.get("/daf/ledger-entries")
def list_ledger_entries():
    _, role = get_identity()
    require_role(role, LEDGER_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.ledger_entries, {
        "donor_account_id": request.args.get("donor_account_id"),
        "entry_type": request.args.get("entry_type"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.ledger_entry(e) for e in page], meta)
