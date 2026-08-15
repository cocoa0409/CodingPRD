"""Returnable bottles: register, list, read, fill, deliver, return, retire."""
from flask import Blueprint, request

from db import store, new_resource, touch, by_creation
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import bottle_json, get_body, get_or_404, raise_shape

bp = Blueprint("bottles", __name__)

SL = ["SanitationLead"]


@bp.post("/api/plants/<plant_id>/bottles")
@auth(SL)
def create_bottle(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()
    code = body.get("bottle_code")

    # Rung 9 — code uniqueness among the plant's non-RETIRED bottles.
    if isinstance(code, str) and code:
        clash = any(
            b["plant_id"] == plant["id"]
            and b["bottle_code"] == code
            and b["status"] != "RETIRED"
            for b in store.bottles.values()
        )
        if clash:
            raise ApiError(
                "ERR_BOTTLE_CODE_EXISTS",
                "bottle_code is already used by a live bottle of this plant",
                409,
            )

    if not isinstance(code, str) or not code:
        raise_shape(["bottle_code is required"])

    bottle = new_resource(
        {
            "plant_id": plant["id"],
            "bottle_code": code,
            "wash_cycle_count": 0,
            "status": "SANITIZED",
            "last_wash_batch_id": None,
            "current_wash_batch_id": None,
            "last_filled_lot_id": None,
        }
    )
    store.bottles[bottle["id"]] = bottle
    return ok_object(bottle_json(bottle), 201)


@bp.get("/api/bottles")
@auth(ALL_ROLES)
def list_bottles():
    items = list(store.bottles.values())
    for qp in (
        "plant_id",
        "current_wash_batch_id",
        "last_wash_batch_id",
        "last_filled_lot_id",
        "status",
    ):
        val = request.args.get(qp)
        if val is not None:
            items = [b for b in items if b.get(qp) == val]
    return ok_list([bottle_json(b) for b in by_creation(items)])


@bp.get("/api/bottles/<bottle_id>")
@auth(ALL_ROLES)
def get_bottle(bottle_id):
    bottle = get_or_404(store.bottles, bottle_id, "bottle")
    return ok_object(bottle_json(bottle))


@bp.post("/api/bottles/<bottle_id>/fill")
@auth(["ProductionLead"])
def fill_bottle(bottle_id):
    bottle = get_or_404(store.bottles, bottle_id, "bottle")
    body = get_body()

    # Rung 3 — body FK existence.
    lot_id = body.get("lot_id")
    lot = None
    if isinstance(lot_id, str):
        lot = store.lots.get(lot_id)
    if lot_id is not None and lot is None:
        raise ApiError("ERR_NOT_FOUND", "lot_id does not reference an existing lot", 404)

    # Rung 5 — state.
    if bottle["status"] != "SANITIZED":
        raise err_invalid_state("only a SANITIZED bottle can be filled")

    # Rung 6 — sanitation gate first among the business checks: never-washed
    # new stock (null last_wash_batch_id) passes; otherwise the batch's
    # sanitation test must be COMPLETED_PASS.
    last_batch = bottle.get("last_wash_batch_id")
    if last_batch is not None:
        passed = any(
            t["test_type"] == "BOTTLE_SANITATION"
            and t.get("subject_wash_batch_id") == last_batch
            and t["status"] == "COMPLETED_PASS"
            for t in store.lab_tests.values()
        )
        if not passed:
            raise ApiError(
                "ERR_SANITATION_TEST_PENDING",
                "the bottle's last wash batch lacks a COMPLETED_PASS sanitation test",
                409,
            )

    # Rung 8 — cross-plant, then lot released.
    if lot is not None:
        line = store.lines.get(lot["line_id"])
        lot_plant = line["plant_id"] if line else None
        if lot_plant != bottle["plant_id"]:
            raise ApiError(
                "ERR_CROSS_PLANT_REFERENCE",
                "the lot belongs to a different plant than the bottle",
                409,
            )
        if lot["status"] != "RELEASED":
            raise ApiError(
                "ERR_LOT_NOT_RELEASED",
                "the bottle can only be filled from a RELEASED lot",
                409,
            )

    if lot is None:
        raise_shape(["lot_id is required"])

    bottle["status"] = "FILLED"
    bottle["last_filled_lot_id"] = lot["id"]
    touch(bottle)
    return ok_object(bottle_json(bottle))


@bp.post("/api/bottles/<bottle_id>/deliver")
@auth(SL)
def deliver_bottle(bottle_id):
    bottle = get_or_404(store.bottles, bottle_id, "bottle")
    if bottle["status"] != "FILLED":
        raise err_invalid_state("only a FILLED bottle can be delivered")
    bottle["status"] = "WITH_CUSTOMER"
    touch(bottle)
    return ok_object(bottle_json(bottle))


@bp.post("/api/bottles/<bottle_id>/return")
@auth(SL)
def return_bottle(bottle_id):
    bottle = get_or_404(store.bottles, bottle_id, "bottle")
    if bottle["status"] != "WITH_CUSTOMER":
        raise err_invalid_state("only a WITH_CUSTOMER bottle can be returned")
    bottle["status"] = "RETURNED_DIRTY"
    touch(bottle)
    return ok_object(bottle_json(bottle))


@bp.post("/api/bottles/<bottle_id>/retire")
@auth(SL)
def retire_bottle(bottle_id):
    bottle = get_or_404(store.bottles, bottle_id, "bottle")
    if bottle["status"] not in ("RETURNED_DIRTY", "SANITIZED", "QUARANTINED"):
        raise err_invalid_state(
            "only a RETURNED_DIRTY, SANITIZED, or QUARANTINED bottle can be retired"
        )
    bottle["status"] = "RETIRED"
    touch(bottle)
    return ok_object(bottle_json(bottle))
