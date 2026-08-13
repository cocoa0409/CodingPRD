from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object
from errors import raise_err, ERR_RATE_CARD_NOT_FOUND, \
    ERR_BOTTLE_SPEC_NOT_FOUND, ERR_DUPLICATE_CODE
from calc import freight_compute
from services import stamp_new, touch, ser_rate_card
from util import new_id, num_out
from validate import get_body, check_fields

bp = Blueprint("freight", __name__)


def active_rate_card():
    for c in store.freight_rate_cards.values():
        if c["status"] == "ACTIVE":
            return c
    return None


def require_active_card():
    card = active_rate_card()
    if card is None:
        raise_err(ERR_RATE_CARD_NOT_FOUND,
                  "No ACTIVE FreightRateCard exists for freight computation")
    return card


def freight_quote_out(result):
    return {
        "pallets": result["pallets"],
        "trucks": result["trucks"],
        "volume_cm3": result["volume_cm3"],
        "dim_weight_kg": num_out(result["dim_weight_kg"]),
        "actual_weight_kg": num_out(result["actual_weight_kg"]),
        "chargeable_weight_kg": num_out(result["chargeable_weight_kg"]),
        "freight_cost_cents": result["freight_cost_cents"],
    }


@bp.post("/freight-rate-cards")
def create_rate_card():
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    body = check_fields(get_body(), {
        "lane_code": ("str", True),
        "tiers": ("tiers", True),
    })
    for c in store.freight_rate_cards.values():
        if c["lane_code"] == body["lane_code"]:
            raise_err(ERR_DUPLICATE_CODE, "lane_code must be unique")
    # creating a card makes it ACTIVE and flips all others to INACTIVE
    for c in store.freight_rate_cards.values():
        if c["status"] == "ACTIVE":
            c["status"] = "INACTIVE"
            touch(c)
    card = {
        "lane_code": body["lane_code"],
        "tiers": body["tiers"],
        "status": "ACTIVE",
    }
    stamp_new(card, new_id())
    store.freight_rate_cards[card["id"]] = card
    return success_object(ser_rate_card(card), 201)


@bp.get("/freight-rate-cards/<cid>")
def get_rate_card(cid):
    _, role = authenticate()
    require_role(role, ["PlantAdmin", "LogisticsCoordinator"])
    card = store.freight_rate_cards.get(cid)
    if card is None:
        raise_err(ERR_RATE_CARD_NOT_FOUND, "FreightRateCard id does not resolve")
    return success_object(ser_rate_card(card))


@bp.post("/freight-quotes")
def freight_quote():
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    body = check_fields(get_body(), {
        "bottle_spec_id": ("str", True),
        "quantity": ("int", True),
        "shipment_mode": ("enum", True, {"FINISHED_BOTTLES", "PREFORMS"}),
    })
    spec = store.bottle_specs.get(body["bottle_spec_id"])
    if spec is None:
        raise_err(ERR_BOTTLE_SPEC_NOT_FOUND, "BottleSpec id does not resolve")
    card = require_active_card()
    result = freight_compute(spec, body["quantity"], body["shipment_mode"],
                             card["tiers"])
    return success_object(freight_quote_out(result))
