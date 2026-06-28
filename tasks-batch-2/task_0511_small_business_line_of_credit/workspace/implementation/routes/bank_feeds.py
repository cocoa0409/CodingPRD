"""BankFeed routes (PRD §3.1). Plaid-style cash-flow snapshots."""
from flask import Blueprint, request

import db
import serialize
from common import parse_body, parse_datetime, require_fields, require_int, stamp_create, touch, list_response
from errors import err, ERR_INVALID_REQUEST
from lookups import get_merchant, get_bank_feed
from middleware import auth_and_role
from response import object_response

bp = Blueprint("bank_feeds", __name__)


@bp.post("/merchants/<rid>/bank-feeds")
def ingest_feed(rid):
    auth_and_role(["Underwriter", "Servicer"])
    m = get_merchant(rid)
    body = parse_body()
    require_fields(body, ["plaid_item_id", "pulled_at", "avg_daily_balance_cents",
                          "nsf_count_90d", "deposit_volume_cents"])
    plaid_item_id = body["plaid_item_id"]
    if not isinstance(plaid_item_id, str) or not plaid_item_id:
        raise err(ERR_INVALID_REQUEST, "plaid_item_id must be a non-empty string")
    pulled_dt = parse_datetime(body["pulled_at"])
    if pulled_dt is None:
        raise err(ERR_INVALID_REQUEST, "pulled_at must be a valid ISO8601 instant")
    avg_daily_balance_cents = require_int(body, "avg_daily_balance_cents", minimum=0)
    nsf_count_90d = require_int(body, "nsf_count_90d", minimum=0)
    deposit_volume_cents = require_int(body, "deposit_volume_cents", minimum=0)

    record = {
        "merchant_id": m["id"],
        "plaid_item_id": plaid_item_id,
        "pulled_at": body["pulled_at"],
        "avg_daily_balance_cents": avg_daily_balance_cents,
        "nsf_count_90d": nsf_count_90d,
        "deposit_volume_cents": deposit_volume_cents,
        "status": "FRESH",
    }
    stamp_create(record)
    db.bank_feeds[record["id"]] = record
    return object_response(serialize.bank_feed(record), 201)


@bp.get("/merchants/<rid>/bank-feeds")
def list_feeds(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    get_merchant(rid)
    status = request.args.get("status")
    feeds = [f for f in db.bank_feeds.values() if f["merchant_id"] == rid]
    if status is not None:
        feeds = [f for f in feeds if f["status"] == status]
    return list_response(feeds, serialize.bank_feed)


@bp.post("/bank-feeds/<rid>/mark-stale")
def mark_stale(rid):
    auth_and_role(["Underwriter", "Servicer"])
    f = get_bank_feed(rid)
    f["status"] = "STALE"
    touch(f)
    return object_response(serialize.bank_feed(f), 200)
