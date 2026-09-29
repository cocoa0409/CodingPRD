"""CollateralPosting post / return endpoints (PRD 3.5)."""

from flask import Blueprint

import domain
import fetch
import serializers as ser
import validators as v
from db import db, now_iso
from errors import fail
from middleware import RISK_POLICY_ADMIN, endpoint, touch
from response import ok

bp = Blueprint("postings", __name__)


@bp.post("/fuel/collateral-postings/<posting_id>/post")
@endpoint(RISK_POLICY_ADMIN)
def post_collateral(posting_id):
    data = v.body()
    amount = v.get_number(data, "amount_usd", minimum=0, places=2)

    posting = fetch.posting(posting_id)
    if posting["status"] != "REQUIRED":
        fail("ERR_POSTING_INVALID_STATE",
             "Only a REQUIRED posting may be satisfied; this one is %s." % posting["status"])

    instrument = db.instruments.get(posting["hedge_instrument_id"])
    if instrument is None or instrument["trade_status"] != "EXECUTED":
        fail("ERR_INSTRUMENT_INVALID_TRADE_STATE",
             "The covered trade must still be EXECUTED to accept collateral.")

    if amount < posting["required_amount_usd"]:
        fail("ERR_COLLATERAL_SHORTFALL",
             "amount_usd %s does not cover the frozen requirement of %s."
             % (amount, posting["required_amount_usd"]))

    posting["status"] = "POSTED"
    posting["posted_amount_usd"] = amount
    posting["posted_at"] = now_iso()
    touch(posting)
    touch(db.counterparties.get(posting["counterparty_id"]))
    touch(instrument)
    return ok(ser.posting(posting))


@bp.post("/fuel/collateral-postings/<posting_id>/return")
@endpoint(RISK_POLICY_ADMIN)
def return_collateral(posting_id):
    data = v.body()
    v.get_string(data, "return_reason", min_len=1)

    posting = fetch.posting(posting_id)
    if posting["status"] != "POSTED":
        fail("ERR_POSTING_INVALID_STATE",
             "Only a POSTED row may be returned; this one is %s." % posting["status"])

    instrument = db.instruments.get(posting["hedge_instrument_id"])
    allowed = False
    if instrument is not None:
        if instrument["trade_status"] in ("SETTLED", "TERMINATED"):
            allowed = True
        elif instrument["margin_requirement_usd"] < domain.instrument_collateral_posted(instrument):
            allowed = True
    if not allowed:
        fail("ERR_POSTING_INVALID_STATE",
             "Collateral may only be returned once the trade has settled or terminated, "
             "or once the margin requirement has fallen below the posted collateral.")

    posting["status"] = "RETURNED"
    posting["returned_at"] = now_iso()
    touch(posting)
    touch(db.counterparties.get(posting["counterparty_id"]))
    touch(instrument)
    return ok(ser.posting(posting))
