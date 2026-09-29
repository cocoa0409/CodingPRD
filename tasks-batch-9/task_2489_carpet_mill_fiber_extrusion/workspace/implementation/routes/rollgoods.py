"""Roll goods: quality inspection over the two orthogonal status dimensions (PRD 3.7)."""

from flask import Blueprint

from db import store, touch
from errors import ApiError
from routes.common import authenticate, fetch, listing, ok
from services import cascades, ledgers
from validators import json_body, req_enum

bp = Blueprint("rollgoods", __name__)

QA_STATUSES = ("PENDING", "PASSED", "HELD", "FAILED")
INVENTORY_STATUSES = (
    "IN_PROCESS",
    "AVAILABLE",
    "COMMITTED",
    "DEPLETED",
    "SCRAPPED",
)
ROLL_SHADE_BANDS = ("A", "B", "C", "SOLUTION")

WRITE_ROLES = ("QALabTechnician", "PlantAdmin")
READ_ROLES = (
    "QALabTechnician",
    "MillPlanner",
    "DyeHouseOperator",
    "ExtrusionOperator",
    "PlantAdmin",
)


@bp.post("/mill/roll-goods/<roll_good_id>/qa-disposition")
def qa_disposition(roll_good_id):
    authenticate(WRITE_ROLES)
    body = json_body()
    choice = req_enum(body, "disposition", ("RELEASE", "HOLD", "SCRAP"))

    roll = fetch("roll_goods", roll_good_id)

    if choice == "RELEASE":
        # Rung 8 — state legality on both dimensions.
        if roll["qa_status"] not in ("PENDING", "HELD"):
            raise ApiError(
                "ERR_INVALID_STATE", "Only a PENDING or HELD roll may be released"
            )
        run = store.runs.get(roll["production_run_id"])
        if run is None or run["status"] not in ("BACKED", "RELEASED"):
            raise ApiError("ERR_RUN_NOT_BACKED", "The producing run is not BACKED or RELEASED")
        if roll.get("dye_lot_id"):
            lot = store.dye_lots.get(roll["dye_lot_id"])
            if lot is None or lot["status"] != "APPROVED":
                raise ApiError(
                    "ERR_DYE_LOT_NOT_APPROVED", "The roll's dye lot is not APPROVED"
                )

        roll["qa_status"] = "PASSED"
        if roll["inventory_status"] == "IN_PROCESS":
            roll["inventory_status"] = "AVAILABLE"
        touch(roll)

        # Cascade: the run's first passed roll releases the run.
        if run["status"] == "BACKED":
            run["status"] = "RELEASED"
            touch(run)
        return ok("roll_good", roll)

    if choice == "HOLD":
        # Rung 8 — HOLD is only reachable from PENDING.
        if roll["qa_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Only a PENDING roll may be held")
        roll["qa_status"] = "HELD"
        touch(roll)
        return ok("roll_good", roll)

    # SCRAP
    if roll["qa_status"] not in ("PENDING", "HELD", "PASSED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a PENDING, HELD or PASSED roll may be scrapped"
        )
    if roll["inventory_status"] in ("DEPLETED", "SCRAPPED"):
        raise ApiError(
            "ERR_ROLL_ALREADY_DEPLETED",
            "A depleted or already scrapped roll cannot be scrapped",
        )

    voided = cascades.scrap_roll(roll)
    cascades.reconcile_orders_of_lines(voided)
    if roll.get("dye_lot_id"):
        lot = store.dye_lots.get(roll["dye_lot_id"])
        if lot is not None:
            ledgers.recompute_dye_lot_yards(lot)
    return ok("roll_good", roll)


@bp.get("/mill/roll-goods/<roll_good_id>")
def read_roll(roll_good_id):
    authenticate(READ_ROLES)
    return ok("roll_good", fetch("roll_goods", roll_good_id))


@bp.get("/mill/roll-goods")
def list_rolls():
    authenticate(READ_ROLES)
    return listing(
        "roll_good",
        "roll_goods",
        enum_filters={
            "qa_status": QA_STATUSES,
            "inventory_status": INVENTORY_STATUSES,
            "shade_band": ROLL_SHADE_BANDS,
        },
        value_filters=("production_run_id", "dye_lot_id", "parent_roll_id"),
    )
