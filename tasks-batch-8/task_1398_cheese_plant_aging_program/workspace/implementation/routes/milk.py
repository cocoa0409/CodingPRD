"""Milk intake resources (PRD 3.2)."""

from flask import request

from calc import SCC_MAX
from db import STORES, new_record, touch
from errors import ApiError, invalid_state
from helpers import (
    auth,
    body,
    f_bool,
    f_dt,
    f_int,
    f_num,
    f_str,
    filter_and_page,
    get_or_404,
)
from response import serialize, success
from routes import make_bp

bp = make_bp("milk_intakes")

GET_ROLES = ("PlantAdmin", "MakePlanner", "Cheesemaker", "MilkReceiver", "QAGrader")


@bp.post("/plant/plants/<plantId>/milk-intakes")
def create_intake(plantId):
    auth("MilkReceiver")
    b = body()
    hauler_ticket = f_str(b, "hauler_ticket")
    received_raw, _received_dt = f_dt(b, "received_at")
    volume_liters = f_num(b, "volume_liters", positive=True)
    fat_pct = f_num(b, "fat_pct", non_negative=True)
    protein_pct = f_num(b, "protein_pct", non_negative=True)
    scc = f_int(b, "somatic_cell_count", non_negative=True)
    antibiotics = f_bool(b, "antibiotics_detected", required=False, default=False)
    plant = get_or_404("plants", plantId, "plant")
    rec = new_record()
    rec.update(
        plant_id=plant["id"],
        hauler_ticket=hauler_ticket,
        received_at=received_raw,
        volume_liters=volume_liters,
        fat_pct=fat_pct,
        protein_pct=protein_pct,
        somatic_cell_count=scc,
        antibiotics_detected=antibiotics,
        status="RECEIVED",
        consumed_liters=0,
    )
    STORES["milk_intakes"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/plant/milk-intakes/<milkIntakeId>")
def get_intake(milkIntakeId):
    auth(*GET_ROLES)
    rec = get_or_404("milk_intakes", milkIntakeId, "milk intake")
    return success(serialize(rec))


@bp.get("/plant/milk-intakes")
def list_intakes():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "milk_intakes",
        [
            ("plant_id", request.args.get("plant_id")),
            ("status", request.args.get("status")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/milk-intakes/<milkIntakeId>/accept")
def accept_intake(milkIntakeId):
    auth("MilkReceiver")
    rec = get_or_404("milk_intakes", milkIntakeId, "milk intake")
    if rec["status"] != "RECEIVED":
        invalid_state("Milk intake is not RECEIVED")
    # Safety gates, evaluated in this order (PRD 3.2): SCC first, then
    # antibiotics. Exactly 400000 passes; anything strictly above fails.
    if rec["somatic_cell_count"] > SCC_MAX:
        raise ApiError("ERR_SCC_LIMIT", 422, "somatic_cell_count exceeds 400000")
    if rec["antibiotics_detected"]:
        raise ApiError("ERR_ANTIBIOTIC_POSITIVE", 422, "antibiotics detected")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return success(serialize(rec))


@bp.post("/plant/milk-intakes/<milkIntakeId>/reject")
def reject_intake(milkIntakeId):
    auth("MilkReceiver")
    rec = get_or_404("milk_intakes", milkIntakeId, "milk intake")
    if rec["status"] != "RECEIVED":
        invalid_state("Milk intake is not RECEIVED")
    rec["status"] = "REJECTED"
    touch(rec)
    return success(serialize(rec))
