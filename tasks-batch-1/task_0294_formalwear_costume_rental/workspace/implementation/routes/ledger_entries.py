"""LedgerEntry read endpoints (PRD §2.9)."""
from flask import Blueprint, request

import db
from errors import err, ERR_FORBIDDEN
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers

bp = Blueprint("ledger_entries", __name__)


@bp.route("/ledger-entries/<lid>", methods=["GET"])
def get_ledger_entry(lid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    entry = helpers.find("LedgerEntry", lid)
    if role == "Customer" and user_id != entry["customer_id"]:
        raise err(ERR_FORBIDDEN, "Customer may only access their own ledger entries")
    return success(views.ledger_entry_view(entry))


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    limit, offset = helpers.parse_pagination()
    records = list(db.ledger_entries.values())
    if role == "Customer":
        records = [e for e in records if e["customer_id"] == user_id]
    customer_id = request.args.get("customer_id")
    reservation_id = request.args.get("reservation_id")
    entry_type = request.args.get("entry_type")
    if customer_id is not None:
        records = [e for e in records if e["customer_id"] == customer_id]
    if reservation_id is not None:
        records = [e for e in records if e["reservation_id"] == reservation_id]
    if entry_type is not None:
        records = [e for e in records if e["entry_type"] == entry_type]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.ledger_entry_view(e) for e in page], limit, offset, total)
