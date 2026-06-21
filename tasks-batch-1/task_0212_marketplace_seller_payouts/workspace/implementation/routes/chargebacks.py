"""Chargeback endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, parse_iso8601, err,
)
from errors import (
    ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_REPRESENTMENT_WINDOW_CLOSED,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from services.entity import stamp_create, touch
from services.ledger import post_ledger_entry, HOLD_AVAILABLE, HOLD_REVERSED
from services.seller import refresh_seller_derived

bp = Blueprint("chargebacks", __name__)

# Flat non-refundable chargeback fee (PRD §3.7).
CHARGEBACK_FEE_CENTS = 1500
# Representment window: receipt + 7 days (server-set).
REPRESENTMENT_WINDOW_DAYS = 7


@bp.post("/chargebacks")
def create_chargeback():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    body = get_json_body()
    require_fields(body, ["order_id"])
    order = fetch(db.orders, body["order_id"])
    seller = db.sellers[order["seller_id"]]

    now = db.now()
    due = now + timedelta(days=REPRESENTMENT_WINDOW_DAYS)
    chargeback = {
        "order_id": order["id"],
        "seller_id": order["seller_id"],
        "chargeback_status": "RECEIVED",
        "dispute_fee_cents": CHARGEBACK_FEE_CENTS,
        "clawback_cents": 0,
        "representment_due_at": _iso(due),
    }
    stamp_create(chargeback)
    db.chargebacks[chargeback["id"]] = chargeback

    # Immediately levy the flat fee as a negative CHARGEBACK_FEE entry (AVAILABLE
    # bucket so it nets against available proceeds), then reconcile (PRD §3.7).
    post_ledger_entry(
        seller_id=order["seller_id"],
        source_type="CHARGEBACK_FEE",
        source_id=chargeback["id"],
        amount_cents=-CHARGEBACK_FEE_CENTS,
        hold_state=HOLD_AVAILABLE,
        memo="Chargeback fee",
    )
    refresh_seller_derived(seller)
    return success(chargeback, status=201)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.get("/chargebacks/<chargeback_id>")
def get_chargeback(chargeback_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    cb = fetch(db.chargebacks, chargeback_id)
    ensure_seller_owns(role, user_id, cb["seller_id"])
    return success(cb)


@bp.get("/chargebacks")
def list_chargebacks():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.chargebacks.values())
    if role == ROLE_SELLER:
        items = [c for c in items if c["seller_id"] == user_id]
    for key in ("order_id", "seller_id", "chargeback_status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)


@bp.post("/chargebacks/<chargeback_id>/represent")
def represent(chargeback_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER])
    cb = fetch(db.chargebacks, chargeback_id)
    ensure_seller_owns(role, user_id, cb["seller_id"])
    # State guard (PRD §3.7): only from RECEIVED.
    if cb["chargeback_status"] != "RECEIVED":
        raise err(ERR_INVALID_STATE, "Representment only valid from RECEIVED.")
    # Window: allowed only if current_utc <= representment_due_at (inclusive).
    now = db.now()
    due = parse_iso8601(cb["representment_due_at"])
    if now > due:
        raise err(ERR_REPRESENTMENT_WINDOW_CLOSED,
                  "Representment window has closed.")
    cb["chargeback_status"] = "REPRESENTED"
    touch(cb)
    return success(cb)


@bp.post("/chargebacks/<chargeback_id>/decision")
def decision(chargeback_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    cb = fetch(db.chargebacks, chargeback_id)
    body = get_json_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("WON", "LOST"):
        raise err(ERR_INVALID_REQUEST, "outcome must be WON or LOST.")

    order = db.orders[cb["order_id"]]
    seller = db.sellers[cb["seller_id"]]
    status = cb["chargeback_status"]

    if outcome == "WON":
        # WON is reachable only from REPRESENTED (PRD §3.7).
        if status != "REPRESENTED":
            raise err(ERR_INVALID_STATE, "WON only valid from REPRESENTED.")
        # Reverse any previously posted full-gross clawback; the dispute fee is
        # NOT refunded.
        _reverse_clawback_if_posted(cb, order, seller)
        cb["chargeback_status"] = "WON"
        touch(cb)
        refresh_seller_derived(seller)
        return success(cb)

    # outcome == LOST. Reachable from REPRESENTED, or directly from RECEIVED once
    # the representment deadline has passed with no representment filed.
    if status == "REPRESENTED":
        pass
    elif status == "RECEIVED":
        now = db.now()
        due = parse_iso8601(cb["representment_due_at"])
        if now <= due:
            # Deadline not yet passed — cannot go RECEIVED->LOST yet.
            raise err(ERR_INVALID_STATE,
                      "RECEIVED->LOST requires the representment deadline to have passed.")
    else:
        raise err(ERR_INVALID_STATE, "LOST not valid from the current state.")

    _apply_lost(cb, order, seller)
    cb["chargeback_status"] = "LOST"
    touch(cb)
    refresh_seller_derived(seller)
    return success(cb)


def _apply_lost(cb, order, seller):
    """Full-gross reversal on LOST (PRD §3.7)."""
    clawback = order["gross_amount_cents"]
    cb["clawback_cents"] = clawback
    if order["clawback_status"] == "NONE":
        state = HOLD_AVAILABLE if order["settlement_status"] == "AVAILABLE" else "PENDING"
        post_ledger_entry(
            seller_id=cb["seller_id"],
            source_type="CHARGEBACK_CLAWBACK",
            source_id=order["id"],
            amount_cents=-clawback,
            hold_state=state,
            memo="Chargeback clawback (full gross)",
        )
        order["clawback_status"] = "CHARGEBACK_CLAWED"
        touch(order)


def _reverse_clawback_if_posted(cb, order, seller):
    """On WON, reverse any previously posted CHARGEBACK_CLAWBACK for this order.

    A chargeback that reached WON did so from REPRESENTED, so no LOST clawback
    was posted yet; this is a defensive no-op unless one exists."""
    for e in list(db.ledger_entries.values()):
        if (e["source_type"] == "CHARGEBACK_CLAWBACK" and e["source_id"] == order["id"]
                and e["hold_state"] != HOLD_REVERSED and e["amount_cents"] < 0):
            # Post a compensating positive entry restoring the gross.
            post_ledger_entry(
                seller_id=cb["seller_id"],
                source_type="CHARGEBACK_CLAWBACK",
                source_id=order["id"],
                amount_cents=-e["amount_cents"],
                hold_state=e["hold_state"],
                memo="Chargeback clawback reversal (WON)",
            )
            if order["clawback_status"] == "CHARGEBACK_CLAWED":
                order["clawback_status"] = "NONE"
                touch(order)
