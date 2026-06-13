"""Quote endpoints + rate-lock lifecycle (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import (stamp_create, touch, public, get_json,
                             paginate, require_fields, positive_int)
from services.clock import expire_quotes, parse_iso
from services import calculations

bp = Blueprint("quotes", __name__)

PAYOUT_METHODS = {"BANK", "CASH_PICKUP", "WALLET"}


def prevailing_fx_rate(corridor_id):
    """Prevailing rate (PRD §3.1): latest effective_at <= clock; tie broken by
    later-created winning (created seq desc).
    """
    now = db.get_clock()
    candidates = []
    for fx in db.fx_rates.values():
        if fx["corridor_id"] != corridor_id:
            continue
        if parse_iso(fx["effective_at"]) <= now:
            candidates.append(fx)
    if not candidates:
        return None
    # latest effective_at, then later-created (higher seq) wins.
    candidates.sort(key=lambda f: (parse_iso(f["effective_at"]), f["_seq"]))
    return candidates[-1]


@bp.route("/quotes", methods=["POST"])
def create_quote():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    body = get_json()
    require_fields(body, ["corridor_id", "sender_id", "send_principal_minor",
                          "payout_method"])
    # Existence first, left-to-right (PRD §2.6): corridor then sender.
    corridor = db.corridors.get(body["corridor_id"])
    if corridor is None:
        raise err("ERR_NOT_FOUND", "Corridor not found")
    sender = db.senders.get(body["sender_id"])
    if sender is None:
        raise err("ERR_NOT_FOUND", "Sender not found")
    # Body well-formedness (priority 4): positive amount, valid enum.
    principal = positive_int(body, "send_principal_minor")
    if body["payout_method"] not in PAYOUT_METHODS:
        raise err("ERR_INVALID_REQUEST", "payout_method must be BANK/CASH_PICKUP/WALLET")
    # Business: blocked sender (priority 8) then payout-method support (priority 9).
    if sender["status"] == "BLOCKED":
        raise err("ERR_SENDER_BLOCKED", "Sender is blocked by a confirmed sanctions match")
    if body["payout_method"] not in corridor["enabled_payout_methods"]:
        raise err("ERR_PAYOUT_METHOD_NOT_SUPPORTED",
                  "payout_method not enabled for this corridor")

    quote = {
        "corridor_id": corridor["id"],
        "sender_id": sender["id"],
        "send_principal_minor": principal,
        "payout_method": body["payout_method"],
        "mid_rate_micro": None,
        "locked_rate_micro": None,
        "fee_minor": None,
        "recipient_amount_minor": None,
        "total_pay_minor": None,
        "locked_at": None,
        "expires_at": None,
        "status": "DRAFT",
    }
    stamp_create(quote)
    db.quotes[quote["id"]] = quote
    return success(public(quote), 201)


@bp.route("/quotes/<quote_id>", methods=["GET"])
def get_quote(quote_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer"})
    expire_quotes()
    quote = db.quotes.get(quote_id)
    if quote is None:
        raise err("ERR_NOT_FOUND", "Quote not found")
    return success(public(quote), 200)


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer"})
    expire_quotes()
    items = list(db.quotes.values())
    sid = request.args.get("sender_id")
    cid = request.args.get("corridor_id")
    st = request.args.get("status")
    if sid is not None:
        items = [q for q in items if q["sender_id"] == sid]
    if cid is not None:
        items = [q for q in items if q["corridor_id"] == cid]
    if st is not None:
        items = [q for q in items if q["status"] == st]
    page, meta = paginate(items)
    return success([public(q) for q in page], 200, pagination=meta)


@bp.route("/quotes/<quote_id>/lock", methods=["POST"])
def lock_quote(quote_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    expire_quotes()
    quote = db.quotes.get(quote_id)
    if quote is None:
        raise err("ERR_NOT_FOUND", "Quote not found")
    # State precondition (priority 6): only DRAFT -> LOCKED is declared.
    if quote["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT quote can be locked")
    corridor = db.corridors[quote["corridor_id"]]
    # Corridor must be ACTIVE (priority 7).
    if corridor["status"] != "ACTIVE":
        raise err("ERR_CORRIDOR_SUSPENDED", "Corridor is suspended")
    # No overlapping live lock for the same (sender, corridor) (priority 12).
    now = db.get_clock()
    for q in db.quotes.values():
        if q["id"] == quote["id"]:
            continue
        if (q["sender_id"] == quote["sender_id"]
                and q["corridor_id"] == quote["corridor_id"]
                and q["status"] == "LOCKED"
                and q.get("expires_at")
                and parse_iso(q["expires_at"]) > now):
            raise err("ERR_RATE_LOCK_OVERLAP",
                      "An active rate lock already exists for this sender+corridor")

    fx = prevailing_fx_rate(corridor["id"])
    mid = fx["mid_rate_micro"] if fx else 0

    locked_at = now
    expires_at = locked_at + _seconds(corridor["rate_lock_ttl_seconds"])
    locked_rate = calculations.locked_rate(mid, corridor)
    fee = calculations.quote_fee(quote["send_principal_minor"], corridor)
    recip = calculations.recipient_amount(quote["send_principal_minor"], locked_rate)

    quote["mid_rate_micro"] = mid
    quote["locked_rate_micro"] = locked_rate
    quote["fee_minor"] = fee
    quote["recipient_amount_minor"] = recip
    quote["total_pay_minor"] = quote["send_principal_minor"] + fee
    quote["locked_at"] = _iso(locked_at)
    quote["expires_at"] = _iso(expires_at)
    quote["status"] = "LOCKED"
    touch(quote)
    return success(public(quote), 200)


def _seconds(s):
    from datetime import timedelta
    return timedelta(seconds=s)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
