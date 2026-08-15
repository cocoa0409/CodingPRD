from decimal import Decimal

from flask import Blueprint, request

from auth import parse_auth, require_role
from db import store
from envelope import ok, paginate
from errors import (not_found, conflict, ERR_INVALID_STATE, ERR_OBLIGATION_DUPLICATE)
from routes.generators import get_generator
from util import (get_body, check_unknown, req_string, req_int, req_number,
                  new_record, serialize, sort_key, touch, parse_month)
from errors import invalid_request
from services import settlement
from services.credit import refresh_credit

bp = Blueprint("obligations", __name__)


def get_obligation(oid):
    o = store.obligations.get(oid)
    if o is None:
        raise not_found("capacity obligation not found")
    return o


@bp.post("/market/obligations")
def create_obligation():
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"generator_asset_id", "delivery_period", "obligated_mw",
                         "capacity_rate_cents_per_mw"})
    gen_id = req_string(body, "generator_asset_id")
    delivery_period = req_string(body, "delivery_period")
    if parse_month(delivery_period) is None:
        raise invalid_request("delivery_period must be a YYYY-MM month")
    obligated_mw = req_number(body, "obligated_mw", minimum=Decimal(0), min_exclusive=True)
    rate = req_int(body, "capacity_rate_cents_per_mw")

    gen = get_generator(gen_id)
    for o in store.obligations.values():
        if (o["generator_asset_id"] == gen["id"]
                and o["delivery_period"] == delivery_period
                and o["status"] in ("ACTIVE", "AT_RISK")):
            raise conflict(ERR_OBLIGATION_DUPLICATE,
                           "an open obligation exists for this generator and period")

    expected = min(obligated_mw, Decimal(gen["availability_mw"]))
    status = "AT_RISK" if expected < obligated_mw else "ACTIVE"
    rec = new_record()
    rec.update({
        "generator_asset_id": gen["id"],
        "delivery_period": delivery_period,
        "obligated_mw": obligated_mw,
        "capacity_rate_cents_per_mw": rate,
        "expected_output_mw": expected,
        "accrued_penalty_cents": 0,
        "accrued_bonus_cents": 0,
        "gross_revenue_cents": None,
        "charged_penalty_cents": None,
        "forgiven_penalty_cents": None,
        "status": status,
    })
    store.obligations[rec["id"]] = rec
    if status == "AT_RISK":
        refresh_credit(store.participants[gen["market_participant_id"]])
    return ok(serialize(rec), status=201)


@bp.get("/market/obligations/<obligationId>")
def get_one(obligationId):
    parse_auth()
    return ok(serialize(get_obligation(obligationId)))


@bp.get("/market/obligations")
def list_obligations():
    parse_auth()
    rows = sorted(store.obligations.values(), key=sort_key)
    gen_id = request.args.get("generator_asset_id")
    status = request.args.get("status")
    if gen_id is not None:
        rows = [r for r in rows if r["generator_asset_id"] == gen_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])


@bp.post("/market/obligations/<obligationId>/close")
def close_obligation(obligationId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    obl = get_obligation(obligationId)
    if obl["status"] not in ("ACTIVE", "AT_RISK"):
        raise conflict(ERR_INVALID_STATE, "obligation is already closed")
    was_at_risk = obl["status"] == "AT_RISK"
    settlement.capacity_stop_loss_close(obl)
    obl["status"] = "CLOSED"
    touch(obl)
    if was_at_risk:
        gen = store.generators[obl["generator_asset_id"]]
        refresh_credit(store.participants[gen["market_participant_id"]])
    return ok(serialize(obl))
