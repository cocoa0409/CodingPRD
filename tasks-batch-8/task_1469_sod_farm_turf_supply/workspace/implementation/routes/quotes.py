"""Quotes: creation with the pricing ladder, supersede, accept -> Order."""
from flask import Blueprint, request

import calc
import db
from auth import require_roles
from db import common_fields
from errors import (err, ERR_ALREADY_TERMINAL, ERR_DELIVERY_DATE_TOO_SOON,
                    ERR_INVALID_ENUM, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_QUOTE_EXPIRED, ERR_ZONE_SPLIT_MISMATCH)
from serialize import pub_order, pub_quote
from util import (as_int, as_str, body, ok, ok_list, paged, pagination,
                  parse_date, require, sort_created)

bp = Blueprint("quotes", __name__)

GRADES = {"PREMIUM", "STANDARD", "ECONOMY"}
SETTLEMENTS = {"CARD", "CASH_CHECK"}


def _get_quote(qid):
    quote = db.store.quotes.get(qid)
    if quote is None:
        raise err(ERR_NOT_FOUND, f"quote {qid} not found")
    return quote


@bp.route("/quotes", methods=["POST"])
def create_quote():
    require_roles("SalesRep")
    payload = body()
    # tier 3: body FK existence — customer first, then each line's variety
    customer_id = as_str(require(payload, "customer_id"), "customer_id")
    customer = db.store.customers.get(customer_id)
    if customer is None:
        raise err(ERR_NOT_FOUND, f"customer {customer_id} not found")
    lines_raw = payload.get("lines")
    if isinstance(lines_raw, list):
        for ln in lines_raw:
            if isinstance(ln, dict) and ln.get("variety_id") is not None:
                if not isinstance(ln["variety_id"], str) \
                        or ln["variety_id"] not in db.store.variety_configs:
                    raise err(ERR_NOT_FOUND, f"variety {ln.get('variety_id')} not found")
    # tier 4: request shape
    delivery_date = parse_date(require(payload, "delivery_date"), "delivery_date")
    z1 = as_int(require(payload, "z1_pallets"), "z1_pallets", minimum=0)
    z2 = as_int(require(payload, "z2_pallets"), "z2_pallets", minimum=0)
    z3 = as_int(require(payload, "z3_pallets"), "z3_pallets", minimum=0)
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    lines = []
    for ln in lines_raw:
        if not isinstance(ln, dict):
            raise err(ERR_INVALID_REQUEST, "each line must be an object")
        variety_id = as_str(require(ln, "variety_id"), "lines[].variety_id")
        pallet_count = as_int(require(ln, "pallet_count"), "lines[].pallet_count", minimum=1)
        shortfall_slabs = as_int(require(ln, "shortfall_slabs"), "lines[].shortfall_slabs", minimum=0)
        shortfall_rolls = as_int(require(ln, "shortfall_rolls"), "lines[].shortfall_rolls", minimum=0)
        if "grade" not in ln or ln["grade"] is None:
            raise err(ERR_INVALID_REQUEST, "lines[].grade is required")
        lines.append({
            "variety_id": variety_id,
            "grade": ln["grade"],
            "pallet_count": pallet_count,
            "shortfall_slabs": shortfall_slabs,
            "shortfall_rolls": shortfall_rolls,
        })
    if "settlement_method" not in payload or payload["settlement_method"] is None:
        raise err(ERR_INVALID_REQUEST, "settlement_method is required")
    # tier 5: enum membership
    if payload["settlement_method"] not in SETTLEMENTS:
        raise err(ERR_INVALID_ENUM, "settlement_method must be CARD or CASH_CHECK")
    for ln in lines:
        if ln["grade"] not in GRADES:
            raise err(ERR_INVALID_ENUM, f"grade must be one of {sorted(GRADES)}")
    settlement = payload["settlement_method"]
    # line yields (positive, as for harvest batches)
    cfg = calc.current_config()
    if cfg is None:
        raise err(ERR_INVALID_REQUEST, "no current price config exists")
    for ln in lines:
        _, y = calc.line_yield_sqft(cfg, ln["pallet_count"], ln["grade"],
                                    ln["shortfall_slabs"], ln["shortfall_rolls"])
        if y <= 0:
            raise err(ERR_INVALID_REQUEST, "each line's yield_sqft must be positive")
    # tier 9: temporal — delivery date not in the past
    if delivery_date < db.today():
        raise err(ERR_DELIVERY_DATE_TOO_SOON,
                  "delivery_date must not be before the current clock date")
    pricing = calc.price_quote(cfg, settlement, z1, z2, z3, lines)
    # tier 10: route mix reconciles with the line total
    if z1 + z2 + z3 != pricing["total_pallets"]:
        raise err(ERR_ZONE_SPLIT_MISMATCH,
                  f"zone split {z1}+{z2}+{z3} != total_pallets {pricing['total_pallets']}")
    quote = common_fields()
    quote.update({
        "customer_id": customer_id,
        "price_config_id": cfg["id"],
        "delivery_date": delivery_date,
        "settlement_method": settlement,
        "z1_pallets": z1,
        "z2_pallets": z2,
        "z3_pallets": z3,
        "lines": lines,
        "_line_yields": pricing["line_yields"],
        "total_pallets": pricing["total_pallets"],
        "capacity_zone": pricing["capacity_zone"],
        "turf_sqft": pricing["turf_sqft"],
        "freight_amount": pricing["freight_amount"],
        "pre_discount_subtotal": pricing["pre_discount_subtotal"],
        "volume_tier": pricing["volume_tier"],
        "volume_discount": pricing["volume_discount"],
        "card_fee": pricing["card_fee"],
        "total_price": pricing["total_price"],
        "additive_total": pricing["additive_total"],
        "cash_price": pricing["cash_price"],
        "status": "DRAFT",
        "superseded_by_id": None,
    })
    # one draft per customer: the new draft supersedes the old
    for other in db.store.quotes.values():
        if other["customer_id"] == customer_id and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = quote["id"]
            db.bump(other)
    db.store.quotes[quote["id"]] = quote
    return ok(pub_quote(quote), 201)


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    require_roles("SalesRep", "FarmManager")
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    price_config_id = request.args.get("price_config_id")
    items = sort_created(db.store.quotes.values())
    if customer_id is not None:
        items = [q for q in items if q["customer_id"] == customer_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    if price_config_id is not None:
        items = [q for q in items if q["price_config_id"] == price_config_id]
    page, total = paged(items, limit, offset)
    return ok_list([pub_quote(q) for q in page], total, limit, offset)


@bp.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    require_roles("SalesRep", "FarmManager")
    return ok(pub_quote(_get_quote(qid)), 200)


@bp.route("/quotes/<qid>/accept", methods=["POST"])
def accept_quote(qid):
    require_roles("SalesRep")
    quote = _get_quote(qid)
    # tier 6: terminal guard — an already-ACCEPTED quote is terminal
    if quote["status"] == "ACCEPTED":
        raise err(ERR_ALREADY_TERMINAL, f"quote {qid} is already accepted")
    # tier 7: from-state — SUPERSEDED / EXPIRED quotes cannot be accepted
    if quote["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, f"quote {qid} is {quote['status']}")
    # tier 9: temporal — accept on/after a passed delivery date expires the quote
    if quote["delivery_date"] < db.today():
        quote["status"] = "EXPIRED"
        db.bump(quote)
        raise err(ERR_QUOTE_EXPIRED, f"quote {qid} delivery date has passed")
    customer = db.store.customers.get(quote["customer_id"])
    quote["status"] = "ACCEPTED"
    db.bump(quote)
    order = common_fields()
    order.update({
        "quote_id": quote["id"],
        "customer_id": quote["customer_id"],
        "price_config_id": quote["price_config_id"],
        "delivery_date": quote["delivery_date"],
        "settlement_method": quote["settlement_method"],
        "freight_zone": customer["freight_zone"] if customer else None,
        "capacity_zone": quote["capacity_zone"],
        "turf_sqft": quote["turf_sqft"],
        "freight_amount": quote["freight_amount"],
        "pre_discount_subtotal": quote["pre_discount_subtotal"],
        "volume_tier": quote["volume_tier"],
        "volume_discount": quote["volume_discount"],
        "card_fee": quote["card_fee"],
        "total_price": quote["total_price"],
        "total_pallets": quote["total_pallets"],
        "delivery_window_start": None,
        "delivery_window_end": None,
        "status": "PLACED",
        "payment_status": "PENDING",
        "crew_referral_status": "NONE",
        "delivered_sqft": 0,
        "actual_delivered_at": None,
        "freshness_hours": None,
        "install_started_at": None,
        "installed_at": None,
        "chargeable_amount": quote["total_price"],
        "delivery_flagged": False,
    })
    db.store.orders[order["id"]] = order
    return ok(pub_order(order), 201)


@bp.route("/quotes/<qid>/orders", methods=["GET"])
def list_quote_orders(qid):
    require_roles("SalesRep", "FarmManager")
    _get_quote(qid)
    limit, offset = pagination()
    items = sort_created(o for o in db.store.orders.values() if o["quote_id"] == qid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_order(o) for o in page], total, limit, offset)
