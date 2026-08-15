"""Storage slots and finished-goods lots: put-away, withdraw, dispositions
(PRD §3.7)."""

from datetime import date as date_cls

from flask import request

import services as svc
from db import STORE, bump, logical_now, new_record
from errors import ApiError
from middleware import ALL_ROLES, PLANT_ROLES, endpoint
from response import list_response, ok_object
from routes import bp
from serializers import lot_out, slot_out
from util import (
    DEEP_SHELF_LIFE_THRESHOLD_DAYS,
    TEMPERATURE_CLASSES,
    ZONES,
    as_enum,
    as_positive_int,
    as_string,
    body_dict,
    req_present,
)


# ---------------------------------------------------------------------------
# Storage slots
# ---------------------------------------------------------------------------

@bp.route("/plant/storage-slots", methods=["POST"])
@endpoint({"PlantManager"})
def create_slot(user_id, role):
    body = body_dict(request.get_json(silent=True))
    slot_code = as_string(req_present(body, "slot_code"), "slot_code")
    zone = as_enum(req_present(body, "zone"), "zone", ZONES)
    temp_class = as_enum(
        req_present(body, "temperature_class"), "temperature_class", TEMPERATURE_CLASSES
    )
    capacity = as_positive_int(req_present(body, "capacity_cases"), "capacity_cases")
    for existing in STORE["slots"].values():
        if existing["slot_code"] == slot_code:
            raise ApiError("ERR_INVALID_REQUEST", "slot_code must be unique")

    rec = new_record()
    rec.update(
        slot_code=slot_code,
        zone=zone,
        temperature_class=temp_class,
        capacity_cases=capacity,
    )
    STORE["slots"][rec["id"]] = rec
    return ok_object(slot_out(rec), 201)


@bp.route("/plant/storage-slots", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_slots(user_id, role):
    return list_response(list(STORE["slots"].values()), slot_out)


@bp.route("/plant/storage-slots/<slotId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_slot(user_id, role, slotId):
    return ok_object(slot_out(svc.require_record("slots", slotId, "StorageSlot")))


# ---------------------------------------------------------------------------
# Finished-goods lots: reads
# ---------------------------------------------------------------------------

def _lot_in_customer_scope(user_id, lot):
    order = svc.order_of_lot(lot)
    svc.assert_customer_scope(user_id, order)


@bp.route("/plant/lots", methods=["GET"])
@endpoint(ALL_ROLES)
def list_lots(user_id, role):
    batch_id = request.args.get("batch_id")
    slot_id = request.args.get("slot_id")
    status = request.args.get("status")
    recs = list(STORE["lots"].values())
    if role == "CoPackCustomer":
        if batch_id is not None:
            batch = STORE["batches"].get(batch_id)
            if batch is not None:
                svc.assert_customer_scope(user_id, svc.order_of_batch(batch))
        recs = [
            l
            for l in recs
            if (svc.order_of_lot(l) is not None and svc.order_of_lot(l)["copack_customer_id"] == user_id)
        ]
    if batch_id is not None:
        recs = [l for l in recs if l["batch_id"] == batch_id]
    if slot_id is not None:
        recs = [l for l in recs if l["slot_id"] == slot_id]
    if status is not None:
        recs = [l for l in recs if l["release_status"] == status]
    return list_response(recs, lot_out)


@bp.route("/plant/lots/<lotId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_lot(user_id, role, lotId):
    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    if role == "CoPackCustomer":
        _lot_in_customer_scope(user_id, lot)
    return ok_object(lot_out(lot))


# ---------------------------------------------------------------------------
# Put-away and withdrawal
# ---------------------------------------------------------------------------

@bp.route("/plant/lots/<lotId>/put-away", methods=["POST"])
@endpoint({"WarehouseLead"})
def put_away(user_id, role, lotId):
    body = body_dict(request.get_json(silent=True))
    slot_id = as_string(req_present(body, "slot_id"), "slot_id")
    cases = as_positive_int(req_present(body, "cases"), "cases")

    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    slot = svc.require_record("slots", slot_id, "StorageSlot")

    # state (stage 8)
    if lot["release_status"] not in ("QA_PENDING", "RELEASED", "QUARANTINED"):
        raise ApiError(
            "ERR_LOT_STATE", "Put-away is allowed only from QA_PENDING, RELEASED or QUARANTINED"
        )
    if lot["slot_id"] is not None and lot["slot_id"] != slot["id"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "The first put-away pinned this lot's slot immutably"
        )
    # capacity / structural (stage 11): slot capacity, then temperature class
    if svc.slot_occupied(slot["id"]) + cases > slot["capacity_cases"]:
        raise ApiError(
            "ERR_STORAGE_CAPACITY_EXCEEDED", "Put-away would exceed the slot's capacity_cases"
        )
    recipe = svc.recipe_of_lot(lot)
    if (
        recipe is not None
        and recipe["shelf_life_days"] > DEEP_SHELF_LIFE_THRESHOLD_DAYS
        and slot["temperature_class"] != "DEEP"
    ):
        raise ApiError(
            "ERR_TEMPERATURE_CLASS_MISMATCH",
            "Lots of recipes with shelf_life_days > 545 require DEEP storage",
        )

    if lot["slot_id"] is None:
        lot["slot_id"] = slot["id"]
    lot["stored_cases"] += cases
    bump(lot)
    return ok_object(lot_out(lot))


@bp.route("/plant/lots/<lotId>/withdraw", methods=["POST"])
@endpoint({"WarehouseLead"})
def withdraw(user_id, role, lotId):
    body = body_dict(request.get_json(silent=True))
    cases = as_positive_int(req_present(body, "cases"), "cases")
    purpose = as_string(req_present(body, "purpose"), "purpose")

    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    # state (stage 8)
    if lot["release_status"] != "RELEASED":
        raise ApiError("ERR_LOT_STATE", "Withdrawal requires the lot to be RELEASED")
    # temporal (stage 10): SHIPMENT blocked after final_expiry_date
    if purpose == "SHIPMENT":
        _, final = svc.lot_expiry_dates(lot)
        if final is None:
            raise ApiError("ERR_LOT_EXPIRED", "Lot has no verified expiry date")
        y, m, d = (int(x) for x in final.split("-"))
        if logical_now().date() > date_cls(y, m, d):
            raise ApiError("ERR_LOT_EXPIRED", "Current logical date is past final_expiry_date")
    # capacity (stage 11)
    if cases > lot["stored_cases"]:
        raise ApiError("ERR_INSUFFICIENT_CASES", "Withdraw cases exceed stored_cases")

    lot["stored_cases"] -= cases
    lot["withdrawn_total"] += cases
    if purpose == "SHIPMENT":
        lot["cases_shipped"] += cases
        lot["_ship_events"].append({"cases": cases, "at": logical_now()})
    bump(lot)
    # auto-deplete when the last case leaves the shelf (RELEASED -> DEPLETED)
    if svc.lot_cases_on_hand(lot) == 0 and lot["release_status"] == "RELEASED":
        lot["release_status"] = "DEPLETED"
        bump(lot)
    return ok_object(lot_out(lot))


# ---------------------------------------------------------------------------
# Lot dispositions
# ---------------------------------------------------------------------------

@bp.route("/plant/lots/<lotId>/quarantine", methods=["POST"])
@endpoint({"QATechnician"})
def quarantine_lot(user_id, role, lotId):
    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    if lot["release_status"] != "RELEASED":
        raise ApiError("ERR_LOT_STATE", "Only a RELEASED lot can be quarantined")
    lot["release_status"] = "QUARANTINED"
    bump(lot)
    # order.releasable_cases is derived from RELEASED lots, so it falls automatically.
    return ok_object(lot_out(lot))


@bp.route("/plant/lots/<lotId>/release", methods=["POST"])
@endpoint({"QAManager"})
def release_lot(user_id, role, lotId):
    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    batch = svc.get_batch(lot["batch_id"])
    # segregation of duties (stage 3, evaluated once the resource is loaded):
    # the releaser must differ from every CCP performer on the batch
    for check in svc.checks_of_batch(lot["batch_id"]):
        if check["performed_by_user_id"] == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The releaser must differ from every CCP performer on the batch",
            )
    # state (stage 8): lot from-state, then batch must be COMPLETED
    if lot["release_status"] not in ("QA_PENDING", "QUARANTINED"):
        raise ApiError(
            "ERR_LOT_STATE", "Only a QA_PENDING or QUARANTINED lot can be released"
        )
    if batch is None or batch["status"] != "COMPLETED":
        raise ApiError("ERR_BATCH_STATE", "The lot's batch must be COMPLETED")
    # critical-control safety (stage 9): latest check of each type exists and is PASS
    for check_type in ("METAL_DETECTOR", "XRAY"):
        latest = svc.latest_check(lot["batch_id"], check_type)
        if latest is None or latest["result"] != "PASS":
            raise ApiError(
                "ERR_CCP_NOT_CURRENT",
                "The latest %s check on the batch must exist and be PASS" % check_type,
            )
    # temporal (stage 10): current logical date on or before final_expiry_date
    _, final = svc.lot_expiry_dates(lot)
    if final is None:
        raise ApiError("ERR_LOT_EXPIRED", "Lot has no verified expiry date")
    y, m, d = (int(x) for x in final.split("-"))
    if logical_now().date() > date_cls(y, m, d):
        raise ApiError("ERR_LOT_EXPIRED", "Current logical date is past final_expiry_date")

    lot["release_status"] = "RELEASED"
    bump(lot)
    # releasable_cases and billed_amount_cents are derived and recompute on read.
    return ok_object(lot_out(lot))


@bp.route("/plant/lots/<lotId>/reject", methods=["POST"])
@endpoint({"QAManager"})
def reject_lot(user_id, role, lotId):
    body = body_dict(request.get_json(silent=True))
    as_string(req_present(body, "reason"), "reason")
    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    if lot["release_status"] not in ("QA_PENDING", "QUARANTINED"):
        raise ApiError("ERR_LOT_STATE", "Only a QA_PENDING or QUARANTINED lot can be rejected")
    lot["release_status"] = "REJECTED"
    bump(lot)
    return ok_object(lot_out(lot))


@bp.route("/plant/lots/<lotId>/rework", methods=["POST"])
@endpoint({"QAManager"})
def rework_lot(user_id, role, lotId):
    body = body_dict(request.get_json(silent=True))
    as_string(req_present(body, "reason"), "reason")
    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    if lot["release_status"] != "REJECTED":
        raise ApiError("ERR_LOT_STATE", "Only a REJECTED lot can be sent to rework")
    lot["release_status"] = "QA_PENDING"
    bump(lot)
    return ok_object(lot_out(lot))


@bp.route("/plant/lots/<lotId>/recall", methods=["POST"])
@endpoint({"QAManager"})
def recall_lot(user_id, role, lotId):
    body = body_dict(request.get_json(silent=True))
    as_string(req_present(body, "reason"), "reason")
    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    if lot["release_status"] not in ("RELEASED", "QUARANTINED"):
        raise ApiError("ERR_LOT_STATE", "Only a RELEASED or QUARANTINED lot can be recalled")
    lot["release_status"] = "RECALLED"
    bump(lot)
    return ok_object(lot_out(lot))
