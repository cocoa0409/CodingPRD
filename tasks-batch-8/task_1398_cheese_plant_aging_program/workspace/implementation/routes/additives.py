"""Additive lot resources (PRD 3.1)."""

from flask import request

from calc import ADDITIVE_KINDS
from db import STORES, new_record, touch
from errors import invalid_request, invalid_state
from helpers import auth, body, f_dt, f_enum, f_num, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp

bp = make_bp("additive_lots")

GET_ROLES = ("PlantAdmin", "Cheesemaker", "QAGrader", "MakePlanner")


@bp.post("/plant/plants/<plantId>/additive-lots")
def create_lot(plantId):
    auth("PlantAdmin")
    b = body()
    kind = f_enum(b, "kind", ADDITIVE_KINDS)
    supplier_lot_no = f_str(b, "supplier_lot_no")
    expires_raw, expires_dt = f_dt(b, "expires_at")
    quantity_initial = f_num(b, "quantity_initial", positive=True)
    plant = get_or_404("plants", plantId, "plant")
    # supplier_lot_no is unique per (plant, kind); duplicate receipts rejected.
    for lot in STORES["additive_lots"].values():
        if (
            lot["plant_id"] == plant["id"]
            and lot["kind"] == kind
            and lot["supplier_lot_no"] == supplier_lot_no
        ):
            invalid_request(
                f"supplier_lot_no '{supplier_lot_no}' already exists for this plant and kind"
            )
    rec = new_record()
    rec.update(
        plant_id=plant["id"],
        kind=kind,
        supplier_lot_no=supplier_lot_no,
        expires_at=expires_raw,
        _expires_dt=expires_dt,
        quantity_initial=quantity_initial,
        quantity_on_hand=quantity_initial,
        status="QUARANTINE",
    )
    STORES["additive_lots"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/plant/additive-lots/<additiveLotId>")
def get_lot(additiveLotId):
    auth(*GET_ROLES)
    rec = get_or_404("additive_lots", additiveLotId, "additive lot")
    return success(serialize(rec))


@bp.get("/plant/additive-lots")
def list_lots():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "additive_lots",
        [
            ("plant_id", request.args.get("plant_id")),
            ("kind", request.args.get("kind")),
            ("status", request.args.get("status")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/additive-lots/<additiveLotId>/release")
def release_lot(additiveLotId):
    auth("QAGrader")
    body(required=False)
    rec = get_or_404("additive_lots", additiveLotId, "additive lot")
    if rec["status"] != "QUARANTINE":
        invalid_state("Only a QUARANTINE lot may be released")
    rec["status"] = "RELEASED"
    touch(rec)
    return success(serialize(rec))


@bp.post("/plant/additive-lots/<additiveLotId>/recall")
def recall_lot(additiveLotId):
    auth("QAGrader")
    body(required=False)
    rec = get_or_404("additive_lots", additiveLotId, "additive lot")
    if rec["status"] not in ("QUARANTINE", "RELEASED"):
        invalid_state("Only a QUARANTINE or RELEASED lot may be recalled")
    rec["status"] = "RECALLED"
    touch(rec)
    return success(serialize(rec))
