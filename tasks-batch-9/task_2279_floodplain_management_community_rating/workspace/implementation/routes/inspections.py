"""Post-disaster inspections: assessment and the substantial-damage cascade."""

from flask import Blueprint

from db import db, iso_now, now, to_dt, touch
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response
from services import calc, engine
from validation import (body, lookup, opt_num, pagination, paginate,
                        query_filters, req_num)

bp = Blueprint("inspections", __name__)


@bp.get("/inspections/<inspection_id>")
def read_inspection(inspection_id):
    require(*ALL_ROLES)
    return object_response(lookup("inspection", inspection_id))


@bp.get("/inspections")
def list_inspections():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.inspections.values()), {
        "structure_id": ("structure_id", None),
        "declaration_code": ("declaration_code", None),
        "status": ("status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/inspections/<inspection_id>/assess")
def assess_inspection(inspection_id):
    require("FloodplainAdministrator")
    inspection = lookup("inspection", inspection_id)
    data = body()
    damage_cost = req_num(data, "damage_cost_usd", minimum=0)
    claim_paid = opt_num(data, "claim_paid_amount_usd", default=calc.ZERO, minimum=0)

    if inspection["status"] != "SCHEDULED":
        fail("ERR_INSPECTION_NOT_SCHEDULED")
    if now() > to_dt(inspection["deadline_at"]):
        fail("ERR_INSPECTION_WINDOW_CLOSED")

    structure = db.structures.get(inspection["structure_id"])
    market_value = structure["market_value_usd"] if structure else calc.money(0)
    inspection["damage_cost_usd"] = calc.money(damage_cost)
    inspection["claim_paid_amount_usd"] = calc.money(claim_paid)
    inspection["market_value_at_inspection_usd"] = market_value
    inspection["damage_ratio_pct"] = calc.pct(damage_cost, market_value)
    inspection["status"] = "ASSESSED"
    inspection["assessed_at"] = iso_now()
    touch(inspection)
    return object_response(inspection)


@bp.post("/inspections/<inspection_id>/finalize")
def finalize_inspection(inspection_id):
    require("FloodplainAdministrator")
    inspection = lookup("inspection", inspection_id)
    if inspection["status"] != "ASSESSED":
        fail("ERR_INSPECTION_NOT_ASSESSED")

    inspection["status"] = "FINALIZED"
    inspection["finalized_at"] = iso_now()
    touch(inspection)

    structure = db.structures.get(inspection["structure_id"])
    if structure is not None:
        record = engine.create_record(
            structure, "DAMAGE", "DISASTER_INSPECTION",
            inspection["disaster_event_date"], inspection["damage_cost_usd"],
            inspection["claim_paid_amount_usd"], inspection_id=inspection["id"])
        engine.ledger_effects(structure, record)
    return object_response(inspection)
