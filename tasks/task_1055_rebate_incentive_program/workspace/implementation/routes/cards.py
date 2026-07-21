"""Virtual card endpoints (4) - PRD §3.8."""
from flask import Blueprint, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err

bp = Blueprint("cards", __name__)

READ_ROLES = ("ProgramAdmin", "FinanceOfficer", "Dealer", "Consumer")


def _claim_of_card(card):
    payout = db.payouts.get(card["payout_id"])
    if payout is None:
        return None, None
    return payout, db.claims.get(payout["claim_id"])


@bp.get("/api/virtual-cards/<cid>")
@mw.require(*READ_ROLES)
def read_card(cid):
    return resp.ok(ser.virtual_card(db.get_card(cid)))


@bp.get("/api/virtual-cards")
@mw.require(*READ_ROLES)
def list_cards():
    items = db.by_created(list(db.virtual_cards.values()))
    for field in ("payout_id", "status"):
        value = request.args.get(field)
        if value:
            items = [c for c in items if c[field] == value]
    return resp.paginated(items, ser.virtual_card)


@bp.post("/api/virtual-cards/<cid>/activate")
@mw.require("Dealer", "Consumer")
def activate_card(cid):
    card = db.get_card(cid)
    payout, claim = _claim_of_card(card)
    if claim is not None:
        mw.owns(claim["claimant_id"])

    if card["status"] != "ISSUED" or payout is None or payout["status"] != "RELEASED":
        raise err("ERR_CARD_NOT_ACTIVE")

    card["status"] = "ACTIVATED"
    card["last_activity_at"] = db.now()
    db.touch(card)
    return resp.ok(ser.virtual_card(card))


@bp.post("/api/virtual-cards/<cid>/spend")
@mw.require("Dealer", "Consumer")
def spend_card(cid):
    card = db.get_card(cid)
    payout, claim = _claim_of_card(card)
    if claim is not None:
        mw.owns(claim["claimant_id"])

    data = mw.body()
    amount = mw.as_int(data, "amount_cents")
    mw.as_string(data, "merchant_name")

    # (9) state
    if card["status"] not in ("ACTIVATED", "PARTIALLY_USED") \
            or payout is None or payout["status"] != "RELEASED":
        raise err("ERR_CARD_NOT_ACTIVE")

    # (15) spend bound
    remaining = card["remaining_balance_cents"]
    if amount <= 0 or amount > remaining:
        raise err("ERR_INSUFFICIENT_CARD_BALANCE")

    if amount < remaining:
        card["remaining_balance_cents"] = remaining - amount
        card["status"] = "PARTIALLY_USED"
        card["last_activity_at"] = db.now()
        db.touch(card)
    else:
        card["remaining_balance_cents"] = 0
        card["status"] = "EXHAUSTED"
        card["last_activity_at"] = db.now()
        db.touch(card)
        if payout["status"] == "RELEASED":
            payout["status"] = "CLEARED"
            db.touch(payout)

    return resp.ok(ser.virtual_card(card))
