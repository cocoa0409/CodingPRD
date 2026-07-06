"""LedgerEntry read-only surface."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ADMIN
from errors import raise_err, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_REQUEST
from response import envelope_object, envelope_array
from services import pagination
from services.serializers import ledger_entry_dto
from db import parse_iso

bp = Blueprint("ledger", __name__)


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger():
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.ledger_entries.values())
    for k in ("member_id", "exchange_id", "redemption_id", "entry_kind"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x.get(k) == v]
    # LedgerEntries have no version/updated_at; sort by created_at ASC.
    ordered = sorted(items, key=lambda e: (parse_iso(e["created_at"]),
                                           e.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return envelope_array([ledger_entry_dto(e) for e in window], limit, offset, total)


@bp.route("/ledger-entries/<lid>", methods=["GET"])
def get_ledger(lid):
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    e = db.ledger_entries.get(lid)
    if e is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "LedgerEntry not found")
    return envelope_object(ledger_entry_dto(e), status=200)
