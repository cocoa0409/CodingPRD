"""Recall events: initiate (lot + bottle cascade), recoveries, close."""
from flask import Blueprint, request

from db import store, new_resource, touch, by_creation
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import as_int, get_body, get_or_404, raise_shape, recall_json

bp = Blueprint("recalls", __name__)

CO = ["ComplianceOfficer"]


def _lot_plant(lot):
    line = store.lines.get(lot["line_id"])
    return line["plant_id"] if line else None


@bp.post("/api/plants/<plant_id>/recalls")
@auth(CO)
def create_recall(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()

    # Rung 3 — existence of every listed lot.
    lot_ids = body.get("lot_ids")
    lots = []
    if isinstance(lot_ids, list):
        for lid in lot_ids:
            lot = store.lots.get(lid) if isinstance(lid, str) else None
            if lot is None:
                raise ApiError("ERR_NOT_FOUND", "a lot in lot_ids does not exist", 404)
            lots.append(lot)

    # Rung 8 — cross-plant, then released-state of the scope.
    for lot in lots:
        if _lot_plant(lot) != plant["id"]:
            raise ApiError(
                "ERR_CROSS_PLANT_REFERENCE",
                "a lot in the recall scope belongs to a different plant",
                409,
            )
    for lot in lots:
        if lot["status"] != "RELEASED":
            raise ApiError(
                "ERR_RECALL_LOT_NOT_RELEASED",
                "every lot in the recall scope must be RELEASED",
                409,
            )

    # Rung 9 — empty scope.
    if isinstance(lot_ids, list) and len(lots) == 0:
        raise ApiError("ERR_EMPTY_RECALL_SCOPE", "lot_ids must not be empty", 422)

    # Rung 11 — input shape.
    errs = []
    if not isinstance(body.get("reason"), str) or not body.get("reason"):
        errs.append("reason is required")
    if not isinstance(lot_ids, list):
        errs.append("lot_ids must be an array")
    raise_shape(errs)

    scope_ids = {lot["id"] for lot in lots}
    units_in_scope = sum(lot["produced_units"] or 0 for lot in lots)

    recall = new_resource(
        {
            "plant_id": plant["id"],
            "reason": body.get("reason"),
            "status": "INITIATED",
            "units_in_scope": units_in_scope,
            "units_recovered": 0,
        }
    )
    store.recalls[recall["id"]] = recall

    # Cascade: lots -> RECALLED; their FILLED / WITH_CUSTOMER bottles -> QUARANTINED.
    for lot in lots:
        lot["status"] = "RECALLED"
        lot["recall_id"] = recall["id"]
        touch(lot)
    for b in store.bottles.values():
        if (
            b["plant_id"] == plant["id"]
            and b.get("last_filled_lot_id") in scope_ids
            and b["status"] in ("FILLED", "WITH_CUSTOMER")
        ):
            b["status"] = "QUARANTINED"
            touch(b)
    return ok_object(recall_json(recall), 201)


@bp.get("/api/recalls")
@auth(ALL_ROLES)
def list_recalls():
    items = list(store.recalls.values())
    plant_id = request.args.get("plant_id")
    status = request.args.get("status")
    if plant_id is not None:
        items = [r for r in items if r["plant_id"] == plant_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return ok_list([recall_json(r) for r in by_creation(items)])


@bp.get("/api/plants/<plant_id>/recalls")
@auth(ALL_ROLES)
def list_plant_recalls(plant_id):
    get_or_404(store.plants, plant_id, "plant")
    items = [r for r in store.recalls.values() if r["plant_id"] == plant_id]
    return ok_list([recall_json(r) for r in by_creation(items)])


@bp.get("/api/recalls/<recall_id>")
@auth(ALL_ROLES)
def get_recall(recall_id):
    recall = get_or_404(store.recalls, recall_id, "recall")
    return ok_object(recall_json(recall))


@bp.post("/api/recalls/<recall_id>/recoveries")
@auth(CO)
def post_recovery(recall_id):
    recall = get_or_404(store.recalls, recall_id, "recall")
    if recall["status"] not in ("INITIATED", "RECOVERING"):
        raise err_invalid_state("the recall is closed")
    body = get_body()
    recovered, ok = as_int(body.get("recovered_units"))

    # Rung 10 — may not exceed remaining scope.
    if ok and recall["units_recovered"] + recovered > recall["units_in_scope"]:
        raise ApiError(
            "ERR_RECOVERY_EXCEEDS_SCOPE",
            "the posting would push units_recovered past units_in_scope",
            422,
        )
    # Rung 11 — positivity.
    if not ok or recovered <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "recovered_units must be a positive integer", 400)

    recall["units_recovered"] += recovered
    if recall["status"] == "INITIATED":
        recall["status"] = "RECOVERING"
    touch(recall)
    return ok_object(recall_json(recall))


@bp.post("/api/recalls/<recall_id>/close")
@auth(CO)
def close_recall(recall_id):
    recall = get_or_404(store.recalls, recall_id, "recall")
    if recall["status"] != "RECOVERING":
        raise err_invalid_state("only a RECOVERING recall can be closed")
    if recall["units_recovered"] < recall["units_in_scope"]:
        raise ApiError(
            "ERR_RECOVERY_INCOMPLETE",
            "units_recovered has not reached units_in_scope",
            409,
        )
    recall["status"] = "CLOSED"
    touch(recall)
    # Release the scope's quarantined bottles back to the dirty pool.
    scope_ids = {
        lot["id"] for lot in store.lots.values() if lot.get("recall_id") == recall["id"]
    }
    for b in store.bottles.values():
        if b["status"] == "QUARANTINED" and b.get("last_filled_lot_id") in scope_ids:
            b["status"] = "RETURNED_DIRTY"
            touch(b)
    return ok_object(recall_json(recall))
