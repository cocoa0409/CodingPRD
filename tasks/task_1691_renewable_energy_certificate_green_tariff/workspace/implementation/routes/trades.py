"""Trade endpoints: proposal, acceptance, settlement, cancel, expire."""

from datetime import timedelta

from flask import Blueprint, request

from errors import raise_err, ERR_VALIDATION, ERR_ACCOUNT_NOT_ACTIVE, \
    ERR_CERTIFICATE_NOT_ACTIVE, ERR_TRADE_STATE_INVALID, ERR_QUANTITY_INVALID, \
    ERR_SETTLEMENT_WINDOW_EXPIRED, ERR_TRADE_NOT_EXPIRED
from store import STORE, new_id, next_seq, now_ts, clock_now
from util import auth, require_role, forbidden, ok_object, body_json, req_str, \
    req_int, req_list, req_enum, get_or_404
from services import add_strike, touch, broker_fee_bps, round_half_up_div
from routes.generators import list_with_serializer

bp = Blueprint("trades", __name__)

SETTLEMENT_WINDOW_DAYS = 5


def serialize_trade(t):
    return {k: v for k, v in t.items() if not k.startswith("_")}


@bp.post("/greenpower/trades")
def create_trade():
    uid, role = auth()
    require_role(role, "BrokerTrader")
    body = body_json()
    # Ownership (raw-value match): the seller account must be the caller's own.
    from_raw = body.get("from_account_id")
    if isinstance(from_raw, str) and uid != from_raw:
        forbidden("A BrokerTrader may only propose trades from their own account")
    from_account_id = req_str(body, "from_account_id")
    to_account_id = req_str(body, "to_account_id")
    items = req_list(body, "items")
    if not items:
        raise_err(ERR_VALIDATION, "items must be a non-empty array")
    parsed_items = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise_err(ERR_VALIDATION, "items[%d] must be an object" % i)
        cid = req_str(item, "certificate_id")
        qty = req_int(item, "quantity_mwh")
        parsed_items.append({"certificate_id": cid, "quantity_mwh": qty})
    unit_price = req_int(body, "unit_price_cents_per_mwh")
    if unit_price <= 0:
        raise_err(ERR_VALIDATION, "unit_price_cents_per_mwh must be a positive integer")
    settlement_mode = req_enum(body, "settlement_mode", {"GROSS", "NET"})

    seller = get_or_404(STORE["accounts"], from_account_id, "Account")
    buyer = get_or_404(STORE["accounts"], to_account_id, "Account")
    certs = [get_or_404(STORE["certificates"], it["certificate_id"], "Certificate")
             for it in parsed_items]
    if seller["account_type"] != "BROKER" or buyer["account_type"] != "BROKER":
        raise_err(ERR_VALIDATION, "Trades may only involve BROKER accounts")
    if seller["status"] != "ACTIVE" or buyer["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE,
                  "Both trade accounts must be in ACTIVE standing")
    for cert in certs:
        if cert["status"] != "ACTIVE" or cert["account_id"] != from_account_id:
            raise_err(ERR_CERTIFICATE_NOT_ACTIVE,
                      "Every trade item certificate must be ACTIVE and held by the seller")
    for it, cert in zip(parsed_items, certs):
        if it["quantity_mwh"] < 1 or it["quantity_mwh"] > cert["quantity_mwh"]:
            raise_err(ERR_QUANTITY_INVALID,
                      "Item quantity_mwh must be between 1 and the certificate quantity")

    now = now_ts()
    trade = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "items": parsed_items,
        "unit_price_cents_per_mwh": unit_price,
        "settlement_mode": settlement_mode,
        "status": "PROPOSED",
        "proposed_at": now,
        "accepted_at": None,
        "settlement_deadline": None,
        "settled_at": None,
        "total_line_cents": None,
        "broker_fee_cents": None,
        "buyer_total_cents": None,
        "seller_proceeds_cents": None,
        "_seq": next_seq(),
    }
    STORE["trades"][trade["id"]] = trade
    return ok_object(serialize_trade(trade), 201)


@bp.get("/greenpower/trades")
def list_trades():
    auth()
    filters = {
        "from_account_id": request.args.get("from_account_id"),
        "to_account_id": request.args.get("to_account_id"),
        "status": request.args.get("status"),
    }
    return list_with_serializer(list(STORE["trades"].values()), filters,
                                serialize_trade)


@bp.get("/greenpower/trades/<tid>")
def get_trade(tid):
    auth()
    trade = get_or_404(STORE["trades"], tid, "Trade")
    return ok_object(serialize_trade(trade))


@bp.post("/greenpower/trades/<tid>/accept")
def accept_trade(tid):
    uid, role = auth()
    require_role(role, "BrokerTrader")
    trade = get_or_404(STORE["trades"], tid, "Trade")
    if uid != trade["to_account_id"]:
        forbidden("Only the buyer may accept this trade")
    buyer = STORE["accounts"].get(trade["to_account_id"])
    if buyer is None or buyer["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "The buyer account is not ACTIVE")
    certs = []
    for it in trade["items"]:
        cert = STORE["certificates"].get(it["certificate_id"])
        if (cert is None or cert["status"] != "ACTIVE"
                or cert["account_id"] != trade["from_account_id"]):
            raise_err(ERR_CERTIFICATE_NOT_ACTIVE,
                      "Every item certificate must still be ACTIVE and held by the seller")
        certs.append(cert)
    if trade["status"] != "PROPOSED":
        raise_err(ERR_TRADE_STATE_INVALID, "Acceptance requires a PROPOSED trade")
    # Atomic lock: all certificates move ACTIVE -> LOCKED together.
    for cert in certs:
        cert["status"] = "LOCKED"
        touch(cert)
    now = now_ts()
    trade["status"] = "ACCEPTED"
    trade["accepted_at"] = now
    trade["settlement_deadline"] = _fmt(clock_now() + timedelta(days=SETTLEMENT_WINDOW_DAYS))
    touch(trade)
    return ok_object(serialize_trade(trade))


def _fmt(dt):
    from store import fmt_ts
    return fmt_ts(dt)


@bp.post("/greenpower/trades/<tid>/settle")
def settle_trade(tid):
    uid, role = auth()
    require_role(role, "BrokerTrader")
    trade = get_or_404(STORE["trades"], tid, "Trade")
    if uid != trade["to_account_id"]:
        forbidden("Only the buyer may settle this trade")
    buyer = STORE["accounts"].get(trade["to_account_id"])
    seller = STORE["accounts"].get(trade["from_account_id"])
    if (buyer is None or buyer["status"] != "ACTIVE"
            or seller is None or seller["status"] != "ACTIVE"):
        raise_err(ERR_ACCOUNT_NOT_ACTIVE,
                  "Both trade accounts must be in ACTIVE standing")
    if trade["status"] != "ACCEPTED":
        raise_err(ERR_TRADE_STATE_INVALID, "Settlement requires an ACCEPTED trade")
    if clock_now() > _parse(trade["settlement_deadline"]):
        raise_err(ERR_SETTLEMENT_WINDOW_EXPIRED,
                  "The settlement deadline has passed")

    now = now_ts()
    total_line_cents = 0
    broker_fee_cents = 0
    for it in trade["items"]:
        cert = STORE["certificates"].get(it["certificate_id"])
        if cert is None:
            continue
        t = it["quantity_mwh"]
        q = cert["quantity_mwh"]
        s = cert["serial_start"]
        e = cert["serial_end"]
        if t == q:
            # Full-quantity transfer: the locked row itself changes hands.
            cert["account_id"] = trade["to_account_id"]
            cert["status"] = "ACTIVE"
            touch(cert)
        else:
            # Partial split: buyer slice is a new row over the leading serials;
            # the seller remainder keeps the original row over the trailing ones.
            slice_cert = {
                "id": new_id(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "generator_id": cert["generator_id"],
                "account_id": trade["to_account_id"],
                "vintage_month": cert["vintage_month"],
                "region_code": cert["region_code"],
                "technology": cert["technology"],
                "serial_prefix": cert["serial_prefix"],
                "serial_start": s,
                "serial_end": s + t - 1,
                "quantity_mwh": t,
                "status": "ACTIVE",
                "_seq": next_seq(),
            }
            STORE["certificates"][slice_cert["id"]] = slice_cert
            cert["serial_start"] = s + t
            cert["serial_end"] = e
            cert["quantity_mwh"] = q - t
            cert["status"] = "ACTIVE"
            touch(cert)
        line_cents = t * trade["unit_price_cents_per_mwh"]
        total_line_cents += line_cents
        # Round each per-line fee half-up BEFORE summation (pinned order).
        broker_fee_cents += round_half_up_div(line_cents * broker_fee_bps(t), 10000)

    trade["total_line_cents"] = total_line_cents
    trade["broker_fee_cents"] = broker_fee_cents
    if trade["settlement_mode"] == "GROSS":
        trade["buyer_total_cents"] = total_line_cents + broker_fee_cents
        trade["seller_proceeds_cents"] = total_line_cents
    else:
        trade["buyer_total_cents"] = total_line_cents
        trade["seller_proceeds_cents"] = total_line_cents - broker_fee_cents
    trade["settled_at"] = now
    trade["status"] = "SETTLED"
    touch(trade)
    return ok_object(serialize_trade(trade))


def _parse(value):
    from util import parse_iso
    return parse_iso(value)


@bp.post("/greenpower/trades/<tid>/cancel")
def cancel_trade(tid):
    uid, role = auth()
    require_role(role, "BrokerTrader")
    trade = get_or_404(STORE["trades"], tid, "Trade")
    if uid != trade["from_account_id"]:
        forbidden("Only the seller may cancel this trade")
    if trade["status"] != "PROPOSED":
        raise_err(ERR_TRADE_STATE_INVALID, "Cancellation requires a PROPOSED trade")
    trade["status"] = "CANCELLED"
    touch(trade)
    return ok_object(serialize_trade(trade))


@bp.post("/greenpower/trades/<tid>/expire")
def expire_trade(tid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    trade = get_or_404(STORE["trades"], tid, "Trade")
    if trade["status"] != "ACCEPTED":
        raise_err(ERR_TRADE_STATE_INVALID, "Expiry requires an ACCEPTED trade")
    if clock_now() <= _parse(trade["settlement_deadline"]):
        raise_err(ERR_TRADE_NOT_EXPIRED,
                  "The settlement deadline has not yet passed")
    for it in trade["items"]:
        cert = STORE["certificates"].get(it["certificate_id"])
        if cert is not None and cert["status"] == "LOCKED":
            cert["status"] = "ACTIVE"
            touch(cert)
    trade["status"] = "EXPIRED"
    touch(trade)
    buyer = STORE["accounts"].get(trade["to_account_id"])
    if buyer is not None:
        add_strike(buyer)
    return ok_object(serialize_trade(trade))
