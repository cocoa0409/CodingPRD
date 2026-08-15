"""FabricRoll endpoints (PRD §3.3, ledger semantics §2.9)."""

from decimal import Decimal

from flask import Blueprint

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_MATERIALS_PLANNER
from response import success_object
from util import get_body, req_str, req_int, req_num, req_enum, req_country
from errors import invalid_request, invalid_state
from services.calc import round_dec
from services.core import base_record, touch, public, get_fabric_roll

bp = Blueprint("fabric_rolls", __name__)

QC_RESULTS = {"PASS", "FAIL"}


@bp.route("/fabric-rolls", methods=["POST"])
def create_fabric_roll():
    require_roles([ROLE_MATERIALS_PLANNER])
    body = get_body()
    roll_code = req_str(body, "roll_code")
    fabric_code = req_str(body, "fabric_code")
    origin_country = req_country(body, "origin_country")
    cost_cents_per_yard = req_int(body, "cost_cents_per_yard", min_v=0)
    received_yards = req_num(body, "received_yards", gt=0)
    if any(r["roll_code"] == roll_code for r in store.fabric_rolls.values()):
        raise invalid_request("roll_code must be unique")

    rec = base_record()
    rec.update({
        "roll_code": roll_code,
        "fabric_code": fabric_code,
        "origin_country": origin_country,
        "cost_cents_per_yard": cost_cents_per_yard,
        "received_yards": round_dec(received_yards, 2),
        "usable_yards": Decimal("0"),
        "allocated_yards": Decimal("0"),
        "consumed_yards": Decimal("0"),
        "available_yards": Decimal("0"),
        "status": "RECEIVED",
    })
    store.fabric_rolls[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fabric-rolls/<roll_id>", methods=["GET"])
def get_fabric_roll_endpoint(roll_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_fabric_roll(roll_id)))


@bp.route("/fabric-rolls/<roll_id>/record-qc", methods=["POST"])
def record_fabric_qc(roll_id):
    require_roles([ROLE_MATERIALS_PLANNER])
    roll = get_fabric_roll(roll_id)
    body = get_body()
    result = req_enum(body, "result", QC_RESULTS)
    if roll["status"] != "RECEIVED":
        raise invalid_state("fabric roll must be RECEIVED to record QC")
    if result == "PASS":
        roll["status"] = "AVAILABLE"
        roll["usable_yards"] = roll["received_yards"]
    else:
        roll["status"] = "REJECTED"
        roll["usable_yards"] = Decimal("0")
    roll["available_yards"] = (
        roll["usable_yards"] - roll["allocated_yards"] - roll["consumed_yards"])
    touch(roll)
    return success_object(public(roll))
