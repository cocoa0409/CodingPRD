"""Subscriber + wallet-entry endpoints (PRD §3.2)."""
from flask import Blueprint, request, g

from db import db
from common import (new_record, serialize, get_body, require_str, require_int,
                    require_enum, must_exist, paginate)
from middleware import authenticate, require_roles, require_owner_subscriber
from response import success, list_success, format_iso
from errors import err, ERR_DUPLICATE_EMAIL
from services.ledger import create_wallet_entry

bp = Blueprint("subscribers", __name__)

WALLET_KINDS = {"REFUND_CREDIT", "WINBACK_CREDIT", "PERIOD_DEBIT", "ADJUSTMENT"}


def _serialize_wallet_entry(entry):
    return {
        "id": entry["id"],
        "created_at": format_iso(entry["created_at"]),
        "subscriber_id": entry["subscriber_id"],
        "amount_cents": entry["amount_cents"],
        "kind": entry["kind"],
        "source_ref_id": entry.get("source_ref_id"),
    }


@bp.post("/subscribers")
def create_subscriber():
    authenticate()
    require_roles("Subscriber", "CurationAdmin")
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")

    for s in db.subscribers.values():
        if s["email"] == email:
            raise err(ERR_DUPLICATE_EMAIL, "Subscriber email already exists.")

    subscriber = new_record({
        "email": email,
        "full_name": full_name,
        "wallet_balance_cents": 0,
    })
    db.subscribers[subscriber["id"]] = subscriber
    return success(serialize(subscriber), status=201)


@bp.get("/subscribers/<sid>")
def get_subscriber(sid):
    authenticate()
    require_roles("Subscriber", "CurationAdmin", "BillingOperator")
    subscriber = must_exist(db.subscribers, sid, "Subscriber")
    require_owner_subscriber(sid)
    return success(serialize(subscriber))


@bp.get("/subscribers/<sid>/wallet-entries")
def list_wallet_entries(sid):
    authenticate()
    require_roles("Subscriber", "CurationAdmin", "BillingOperator")
    must_exist(db.subscribers, sid, "Subscriber")
    require_owner_subscriber(sid)
    records = [e for e in db.wallet_entries.values() if e["subscriber_id"] == sid]
    page, limit, offset, total = paginate(records)
    return list_success([_serialize_wallet_entry(r) for r in page], limit, offset, total)


@bp.post("/subscribers/<sid>/wallet-entries")
def create_wallet_entry_route(sid):
    authenticate()
    require_roles("BillingOperator")
    must_exist(db.subscribers, sid, "Subscriber")
    body = get_body()
    amount_cents = require_int(body, "amount_cents")
    kind = require_enum(body, "kind", WALLET_KINDS)
    source_ref_id = body.get("source_ref_id")
    entry = create_wallet_entry(sid, amount_cents, kind, source_ref_id)
    return success(_serialize_wallet_entry(entry), status=201)
