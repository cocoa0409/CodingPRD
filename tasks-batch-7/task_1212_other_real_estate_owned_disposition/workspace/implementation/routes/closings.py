"""ClosingStatement endpoints: draft with computed economics, settle, void."""
from decimal import Decimal

import db
import domain
from domain import closing_json, sort_entities, CLOSING_COST_FLAT
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_date, paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg
from util import pdate, q2


def create_closing():
    require_roles("OREOSpecialist")
    d = body()
    offer_id = req_str(d, "offer_id")
    closing_date = req_date(d, "closing_date")
    o = get_or_404(db.offers, offer_id, "Offer")
    if o["status"] != "ACCEPTED":
        raise ApiError("ERR_OFFER_NOT_ACCEPTED", 409,
                       "Closing statements require an ACCEPTED offer")
    p = db.properties[o["property_id"]]
    env_open, title_open = domain.issue_counts(p["id"])
    if env_open > 0:
        raise ApiError("ERR_ENVIRONMENTAL_ISSUE_OPEN", 409,
                       "An open environmental issue blocks closing")
    if pdate(closing_date) > domain.holding_deadline(p):
        raise ApiError("ERR_CLOSING_BEYOND_DEADLINE", 422,
                       "closing_date is after the property's holding_deadline")
    if title_open > 0:
        raise ApiError("ERR_TITLE_ISSUE_OPEN", 409, "An open title issue blocks closing")
    contract_price = o["current_price"]
    commission_total = domain.commission_tiered(contract_price, p["property_type"], o["financing_type"])
    listing_share, selling_share = domain.commission_split(commission_total)
    net_proceeds = q2(contract_price - commission_total - CLOSING_COST_FLAT)
    carrying = domain.carrying_value(p)
    gain_loss = q2(net_proceeds - carrying)
    recognized, deferred = domain.recognition_variant(
        o["financing_type"], o["down_payment"], gain_loss, contract_price)
    c = domain.base_entity()
    c.update({
        "offer_id": offer_id,
        "property_id": o["property_id"],
        "closing_date": closing_date,
        "contract_price": contract_price,
        "commission_total": commission_total,
        "listing_broker_share": listing_share,
        "selling_broker_share": selling_share,
        "closing_cost_flat": CLOSING_COST_FLAT,
        "net_proceeds": net_proceeds,
        "carrying_value_at_closing": carrying,
        "gain_loss": gain_loss,
        "recognized_gain_at_settlement": recognized,
        "deferred_gain": deferred,
        "status": "DRAFT",
    })
    db.closings[c["id"]] = c
    return success(closing_json(c), 201)


def list_closings():
    require_roles(*ALL_ROLES)
    oid = request_arg("offer_id")
    pid = request_arg("property_id")
    status = request_arg("status")
    items = [c for c in db.closings.values()
             if (oid is None or c["offer_id"] == oid)
             and (pid is None or c["property_id"] == pid)
             and (status is None or c["status"] == status)]
    return paginate(sort_entities(items), closing_json)


def get_closing(entity_id):
    require_roles(*ALL_ROLES)
    return success(closing_json(get_or_404(db.closings, entity_id, "Closing statement")))


def settle_closing(entity_id):
    require_roles("CreditOfficer")
    c = get_or_404(db.closings, entity_id, "Closing statement")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_CLOSING_INVALID_STATE", 409, "Only a DRAFT closing can be settled")
    o = db.offers[c["offer_id"]]
    p = db.properties[c["property_id"]]
    c["status"] = "SETTLED"
    domain.bump(c)
    o["status"] = "CLOSED"
    domain.bump(o)
    domain.ledger_append(p["id"], "PROCEEDS", c["net_proceeds"], "Sale proceeds",
                         closing_statement_id=c["id"])
    if c["gain_loss"] > 0:
        domain.ledger_append(p["id"], "GAIN_RECOGNIZED", c["recognized_gain_at_settlement"],
                             "Gain recognized at settlement", closing_statement_id=c["id"])
    else:
        domain.ledger_append(p["id"], "LOSS_RECOGNIZED", -abs(c["recognized_gain_at_settlement"]),
                             "Loss recognized at settlement", closing_statement_id=c["id"])
    p["lifecycle_status"] = "DISPOSED"
    domain.bump(p)
    return success(closing_json(c), 200)


def void_closing(entity_id):
    require_roles("OREOCommittee")
    c = get_or_404(db.closings, entity_id, "Closing statement")
    if c["status"] != "SETTLED":
        raise ApiError("ERR_CLOSING_INVALID_STATE", 409, "Only a SETTLED closing can be voided")
    o = db.offers[c["offer_id"]]
    p = db.properties[c["property_id"]]
    # Compensating reversal entries; the ledger never edits the original rows.
    domain.ledger_append(p["id"], "PROCEEDS", -c["net_proceeds"], "Void: reverse sale proceeds",
                         closing_statement_id=c["id"])
    if c["gain_loss"] > 0:
        domain.ledger_append(p["id"], "GAIN_RECOGNIZED", -c["recognized_gain_at_settlement"],
                             "Void: reverse recognized gain", closing_statement_id=c["id"])
    else:
        domain.ledger_append(p["id"], "LOSS_RECOGNIZED", abs(c["recognized_gain_at_settlement"]),
                             "Void: reverse recognized loss", closing_statement_id=c["id"])
    c["status"] = "VOID"
    domain.bump(c)
    o["status"] = "ACCEPTED"
    domain.bump(o)
    p["lifecycle_status"] = "UNDER_CONTRACT"
    domain.bump(p)
    return success(closing_json(c), 200)
