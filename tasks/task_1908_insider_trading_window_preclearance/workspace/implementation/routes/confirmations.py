"""TradeConfirmation endpoints: ingestion with the synchronous matching pass."""
from flask import Blueprint, request

from db import STORE
from middleware import require_roles, insider_owns
from response import success, paginate
from services.core import (new_entity, serialize, sort_created, get_or_404,
                           matching_pass, TRADE_SIDES)
from util import Body, fmt_ts, rhu2, dec

bp = Blueprint("confirmations", __name__)

READ_ROLES = ("Insider", "ComplianceOfficer", "LegalAdmin")


@bp.post("/trade-confirmations")
def create_confirmation():
    require_roles("ComplianceOfficer")
    body = Body()
    person_id = body.get_str("covered_person_id")
    ticker = body.get_str("security_ticker")
    side = body.get_enum("trade_side", TRADE_SIDES)
    quantity = body.get_num("quantity", positive=True, max_dp=4)
    price = body.get_num("price", max_dp=2)
    trade_date = body.get_dt("trade_date")
    broker_ref = body.get_str("broker_ref")
    # Body FK existence (ladder step 4) before the schema flush (step 20).
    if person_id is not None:
        get_or_404("covered_persons", person_id, "covered person")
    body.flush()
    c = new_entity()
    trade_value = rhu2(dec(quantity) * dec(price))
    c.update({
        "covered_person_id": person_id,
        "security_ticker": ticker,
        "trade_side": side,
        "quantity": quantity,
        "price": price,
        "trade_date": fmt_ts(trade_date),
        "broker_ref": broker_ref,
        "status": "RECEIVED",
        "match_preclearance_id": None,
        "match_plan_id": None,
        "flagged_reason": None,
        "trade_value": trade_value,
        "_trade_date_dt": trade_date,
    })
    STORE.trade_confirmations[c["id"]] = c
    # Ingestion runs the matching pass synchronously; RECEIVED is transient
    # here and the response shows the resolved status.
    matching_pass(c)
    return success(serialize(c), 201)


@bp.get("/trade-confirmations/<cid>")
def get_confirmation(cid):
    require_roles(*READ_ROLES)
    c = get_or_404("trade_confirmations", cid, "trade confirmation")
    insider_owns(c["covered_person_id"])
    return success(serialize(c))


@bp.get("/trade-confirmations")
def list_confirmations():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.trade_confirmations.values())
    person_id = request.args.get("covered_person_id")
    plan_id = request.args.get("match_plan_id")
    status = request.args.get("status")
    if person_id is not None:
        items = [c for c in items if c["covered_person_id"] == person_id]
    if plan_id is not None:
        items = [c for c in items if c["match_plan_id"] == plan_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([serialize(c) for c in items])
