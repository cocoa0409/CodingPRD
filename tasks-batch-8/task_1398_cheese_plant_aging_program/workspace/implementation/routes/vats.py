"""Vat resources (PRD 3.1, 3.3, 3.4)."""

from flask import request

from db import STORES, new_record, touch
from errors import invalid_request, invalid_state
from helpers import auth, body, f_int, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp
from services import active_makes_on_vat, rederive_vat_status

bp = make_bp("vats")

GET_ROLES = ("PlantAdmin", "MakePlanner", "Cheesemaker")


@bp.post("/plant/plants/<plantId>/vats")
def create_vat(plantId):
    auth("PlantAdmin")
    b = body()
    code = f_str(b, "code")
    capacity_liters = f_int(b, "capacity_liters", positive=True)
    plant = get_or_404("plants", plantId, "plant")
    for v in STORES["vats"].values():
        if v["plant_id"] == plant["id"] and v["code"] == code:
            invalid_request(f"Vat code '{code}' already exists for this plant")
    rec = new_record()
    rec.update(
        plant_id=plant["id"],
        code=code,
        capacity_liters=capacity_liters,
        cip_clean=True,
        status="IDLE",
    )
    STORES["vats"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/plant/vats/<vatId>")
def get_vat(vatId):
    auth(*GET_ROLES)
    rec = get_or_404("vats", vatId, "vat")
    return success(serialize(rec))


@bp.get("/plant/vats")
def list_vats():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "vats",
        [
            ("plant_id", request.args.get("plant_id")),
            ("status", request.args.get("status")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/vats/<vatId>/cip")
def cip_vat(vatId):
    auth("Cheesemaker")
    body(required=False)
    rec = get_or_404("vats", vatId, "vat")
    if rec["status"] != "CLEANING":
        invalid_state("Vat is not CLEANING")
    rec["cip_clean"] = True
    # With a booking queue still active the vat returns to BOOKED, not IDLE
    # (the vat is IDLE only when its last active make is gone, PRD 3.3).
    if active_makes_on_vat(rec["id"]):
        rec["status"] = "BOOKED"
    else:
        rec["status"] = "IDLE"
    touch(rec)
    return success(serialize(rec))


@bp.post("/plant/vats/<vatId>/decommission")
def decommission_vat(vatId):
    auth("PlantAdmin")
    body(required=False)
    rec = get_or_404("vats", vatId, "vat")
    if rec["status"] != "IDLE" or active_makes_on_vat(rec["id"]):
        invalid_state("Only an IDLE vat with no active make sheets may be decommissioned")
    rec["status"] = "DECOMMISSIONED"
    touch(rec)
    return success(serialize(rec))
