"""Shared request helpers: body parsing, validation, pagination, ledger reconciliation."""
from flask import request

from db import db, new_id, touch
from errors import err
from response import now_iso, success_array


def get_json_body():
    """Parse the JSON body; tolerate empty body for no-input endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Body is not valid JSON")
    if body is None:
        # Body present but unparseable
        if request.data.strip():
            raise err("ERR_INVALID_REQUEST", "Body is not valid JSON")
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def parse_pagination():
    """Read limit/offset query params with defaults (10/0), min 1 max 100 for limit."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate_and_respond(items, serializer):
    """Sort by created_at ASC (canonical), then paginate. items already filtered."""
    items_sorted = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    limit, offset = parse_pagination()
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    data = [serializer(x) for x in page]
    return success_array(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Ledger reconciliation (PRD §2.9)
# ---------------------------------------------------------------------------
def append_ledger_entry(linguist, assignment_id, entry_type, amount_cents, reason):
    """Append a PayoutLedgerEntry and reconcile linguist.committed_payout_cents."""
    entry = {
        "id": new_id(),
        "created_at": now_iso(),
        "linguist_id": linguist["id"],
        "assignment_id": assignment_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reason": reason,
    }
    db.payout_ledger[entry["id"]] = entry
    linguist["committed_payout_cents"] = linguist["committed_payout_cents"] + amount_cents
    touch(linguist)
    return entry
