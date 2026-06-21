from datetime import datetime, timezone

from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success, paginated
from services.common import parse_pagination, page
from services import serialize

bp = Blueprint("misc", __name__)


@bp.get("/donation-records/<did>")
@require("SettlementManager", "StoreAdmin")
def get_donation(did):
    d = store.donation_records.get(did)
    if d is None:
        raise err("ERR_NOT_FOUND", "Donation record not found")
    return success(serialize.donation_out(d), 200)


@bp.get("/donation-records")
@require("SettlementManager", "StoreAdmin")
def list_donations():
    limit, offset = parse_pagination()
    recs = list(store.donation_records.values())
    consignor_id = request.args.get("consignor_id")
    disposition = request.args.get("disposition")
    if consignor_id is not None:
        recs = [d for d in recs if d["consignor_id"] == consignor_id]
    if disposition is not None:
        recs = [d for d in recs if d["disposition"] == disposition]
    window, total = page(recs, limit, offset)
    return paginated([serialize.donation_out(d) for d in window], limit, offset, total)


def _parse_iso(value):
    """Parse an ISO 8601 instant; accepts a trailing Z or explicit offset."""
    if not isinstance(value, str) or value.strip() == "":
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
@require("StoreAdmin")
def set_clock():
    body = request.get_json(force=True, silent=True) or {}
    if not isinstance(body, dict) or "to_iso8601" not in body:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 required")
    dt = _parse_iso(body["to_iso8601"])
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    store.clock.set(dt)
    return success({}, 200)
