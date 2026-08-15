"""Ledger entry read endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles
from response import success_object, success_list
from routes.helpers import get_or_404, paginate, serialize_common

bp = Blueprint("ledger", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]


@bp.route("/api/ledger-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    entry = get_or_404(db.ledger_entries, entry_id, "RevenueLedgerEntry")
    return success_object(serialize_common(entry))


@bp.route("/api/ledger-entries", methods=["GET"])
def list_entries():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "loan_id": request.args.get("loan_id"),
        "owner_id": request.args.get("owner_id"),
        "period": request.args.get("period"),
        "entry_type": request.args.get("entry_type"),
    }
    # Entity-backed scoping for OwnerRep
    if role == "OwnerRep":
        if filters["owner_id"] and filters["owner_id"] != user_id:
            raise errors.make_error(errors.ERR_FORBIDDEN, "OwnerRep must pass own id as owner_id filter")
        filters["owner_id"] = user_id

    items = list(db.ledger_entries.values())
    for key in ("loan_id", "owner_id", "period", "entry_type"):
        if filters[key]:
            items = [e for e in items if e.get(key) == filters[key]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(e) for e in page], limit, offset, total)
