"""RestrictedListEntry endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import err, ERR_DUPLICATE_RESTRICTED_ENTRY, ERR_INVALID_STATE
from middleware import require_roles
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           auto_deny_pending)
from util import Body

bp = Blueprint("restricted", __name__)

ROLES = ("ComplianceOfficer", "LegalAdmin")


@bp.post("/restricted-list-entries")
def create_entry():
    require_roles("ComplianceOfficer")
    body = Body()
    ticker = body.get_str("security_ticker")
    note = body.get_str("note", required=False)
    # Duplicate active entry for the same ticker on manual creation (ladder:
    # conflict checks before body schema).
    if ticker is not None and any(e["status"] == "ACTIVE" and e["security_ticker"] == ticker
                                  for e in STORE.restricted_entries.values()):
        raise err(ERR_DUPLICATE_RESTRICTED_ENTRY,
                  "an ACTIVE restricted entry already exists for this ticker")
    body.flush()
    e = new_entity()
    e.update({
        "security_ticker": ticker,
        "deal_id": None,
        "source": "MANUAL",
        "note": note,
        "status": "ACTIVE",
        "removed_reason": None,
    })
    STORE.restricted_entries[e["id"]] = e
    # Manual creation fires the same auto-denial cascade as deal activation.
    auto_deny_pending(ticker)
    return success(serialize(e), 201)


@bp.get("/restricted-list-entries")
def list_entries():
    require_roles(*ROLES)
    items = sort_created(STORE.restricted_entries.values())
    ticker = request.args.get("security_ticker")
    status = request.args.get("status")
    if ticker is not None:
        items = [e for e in items if e["security_ticker"] == ticker]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate([serialize(e) for e in items])


@bp.post("/restricted-list-entries/<eid>/remove")
def remove_entry(eid):
    require_roles("ComplianceOfficer")
    e = get_or_404("restricted_entries", eid, "restricted list entry")
    if e["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "only an ACTIVE entry can be removed")
    e["status"] = "REMOVED"
    e["removed_reason"] = "MANUAL"
    touch(e)
    return success(serialize(e))
