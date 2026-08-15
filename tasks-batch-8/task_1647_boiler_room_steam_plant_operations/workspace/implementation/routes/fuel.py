"""FuelDelivery endpoints: record deliveries (append-only; feeds the
compensating fuel ledger), list/get."""
from flask import Blueprint

import resolve
import store
from auth import authenticate, authorize
from errors import raise_err, ERR_INVALID_REQUEST
from services import delivery_json, deliveries_of, plant_fuel_receive
from util import (
    body_json,
    list_response,
    new_journal_record,
    opt_num,
    req_dt,
    req_num,
    req_str,
    success_object,
    touch,
)

bp = Blueprint("fuel", __name__)

READERS = ["PlantManager", "Operator"]


@bp.post("/plants/<plantId>/fuel-deliveries")
def create_delivery(plantId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    body = body_json()
    delivered_at = req_dt(body, "delivered_at")
    quantity = req_num(body, "quantity_gal")
    supplier = req_str(body, "supplier")
    if quantity <= 0:
        raise_err(ERR_INVALID_REQUEST, "quantity_gal must be greater than zero")
    price = opt_num(body, "price_per_gal", None)
    rec = new_journal_record()
    rec.update({
        "plant_id": plant["id"],
        "delivered_at": delivered_at,
        "quantity_gal": quantity,
        "supplier": supplier,
        # price_per_gal is not part of the declared entity surface; it is kept
        # internal and feeds the steam-trap loss calculation when present.
        "_price_per_gal": price,
    })
    store.fuel_deliveries[rec["id"]] = rec
    plant_fuel_receive(plant, quantity)
    touch(plant)
    return success_object(delivery_json(rec), 201)


@bp.get("/plants/<plantId>/fuel-deliveries/<deliveryId>")
def get_delivery(plantId, deliveryId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    rec = resolve.delivery(plant, deliveryId)
    return success_object(delivery_json(rec))


@bp.get("/plants/<plantId>/fuel-deliveries")
def list_deliveries(plantId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    recs = deliveries_of(plant["id"])
    return list_response(recs, delivery_json)
