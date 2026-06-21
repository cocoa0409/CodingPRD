"""ProductionBatch routes (PRD §3.2, §3.3). Lifecycle + the bottling cascade."""
from flask import Blueprint, request

import constants as C
import calculations as calc
from db import db, common_fields, touch
from clock import now as clock_now
from errors import (
    err, ERR_INVALID_STATE, ERR_BATCH_HAS_INVENTORY, ERR_WINERY_SUSPENDED,
    ERR_INSUFFICIENT_BULK, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST,
)
from middleware import authenticate, authorize
from response import success
from serialize import public
from domain import recompute_batch_available, recompute_winery_bulk
from ledger_service import append_ledger
from validate import (
    get_json_body, require_str, require_number, require_positive_number,
    require_enum, require_positive_int, get_or_404, resolve_winery_fk,
)
from pagination import paginate, sorted_by_creation

bp = Blueprint("batches", __name__)


def _new_batch(winery_id, lot_code, beverage_class, volume_in_gallons, abv_percent):
    b = common_fields()
    b.update({
        "winery_id": winery_id,
        "lot_code": lot_code,
        "beverage_class": beverage_class,
        "volume_in_gallons": volume_in_gallons,
        "loss_gallons": 0.0,
        "bottled_volume_gallons": 0.0,
        "available_bulk_gallons": volume_in_gallons,
        "abv_percent": abv_percent,
        "status": "FERMENTING",
    })
    return b


@bp.route("/batches", methods=["POST"])
def create_batch():
    _, role = authenticate()
    authorize(role, ["CellarManager", "ComplianceOfficer"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    lot_code = require_str(body, "lot_code")
    beverage_class = require_enum(body, "beverage_class", C.BEVERAGE_CLASSES)
    volume = require_positive_number(body, "volume_in_gallons")
    abv = require_number(body, "abv_percent")
    with db.lock:
        winery = resolve_winery_fk(winery_id)
        b = _new_batch(winery_id, lot_code, beverage_class, volume, abv)
        db.batches[b["id"]] = b
        recompute_winery_bulk(winery)
        touch(winery)
        return success(public(b), status=201)


@bp.route("/batches", methods=["GET"])
def list_batches():
    _, role = authenticate()
    authorize(role, ["CellarManager", "ComplianceOfficer"])
    with db.lock:
        items = list(db.batches.values())
        winery_id = request.args.get("winery_id")
        status = request.args.get("status")
        beverage_class = request.args.get("beverage_class")
        if winery_id is not None:
            items = [b for b in items if b["winery_id"] == winery_id]
        if status is not None:
            items = [b for b in items if b["status"] == status]
        if beverage_class is not None:
            items = [b for b in items if b["beverage_class"] == beverage_class]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(b) for b in page], pagination=pg)


@bp.route("/batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    _, role = authenticate()
    authorize(role, ["CellarManager", "ComplianceOfficer"])
    with db.lock:
        b = get_or_404(db.batches, batch_id)
        return success(public(b))


@bp.route("/batches/<batch_id>/transitions", methods=["POST"])
def transition_batch(batch_id):
    _, role = authenticate()
    authorize(role, ["CellarManager"])
    with db.lock:
        b = get_or_404(db.batches, batch_id)
        body = get_json_body()
        action = require_enum(body, "action", {"BEGIN_AGING", "OPEN_BOTTLING", "CLOSE", "DUMP"})
        winery = db.wineries.get(b["winery_id"])

        if action == "BEGIN_AGING":
            if b["status"] != "FERMENTING":
                raise err(ERR_INVALID_STATE, "Batch is not FERMENTING")
            if b["available_bulk_gallons"] <= 0:
                raise err(ERR_INVALID_STATE, "Batch has no available bulk")
            b["status"] = "AGING"
            touch(b)
            recompute_winery_bulk(winery)
            touch(winery)

        elif action == "DUMP":
            if b["status"] != "FERMENTING":
                raise err(ERR_INVALID_STATE, "Batch is not FERMENTING")
            # no sourced product may still hold inventory
            for p in db.products.values():
                if p.get("source_batch_id") == b["id"] and p["on_hand_bottles"] > 0:
                    raise err(ERR_BATCH_HAS_INVENTORY, "A sourced product still has inventory on hand")
            b["loss_gallons"] = b["volume_in_gallons"]
            recompute_batch_available(b)
            b["status"] = "DUMPED"
            touch(b)
            recompute_winery_bulk(winery)
            touch(winery)

        elif action == "OPEN_BOTTLING":
            if b["status"] != "AGING":
                raise err(ERR_INVALID_STATE, "Batch is not AGING")
            if b["available_bulk_gallons"] <= 0:
                raise err(ERR_INVALID_STATE, "Batch has no available bulk")
            b["status"] = "BOTTLING"
            touch(b)

        else:  # CLOSE
            if b["status"] != "BOTTLING":
                raise err(ERR_INVALID_STATE, "Batch is not BOTTLING")
            # remaining available bulk booked into loss
            b["loss_gallons"] = b["loss_gallons"] + b["available_bulk_gallons"]
            recompute_batch_available(b)
            b["status"] = "CLOSED"
            touch(b)
            recompute_winery_bulk(winery)
            touch(winery)

        return success(public(b))


@bp.route("/batches/<batch_id>/bottling-runs", methods=["POST"])
def bottling_run(batch_id):
    """Taxable removal cascade (PRD §3.3): batch -> product -> premises(excise/ledger)."""
    _, role = authenticate()
    authorize(role, ["CellarManager"])
    with db.lock:
        b = get_or_404(db.batches, batch_id)
        body = get_json_body()
        product_id = require_str(body, "product_id")
        requested_bottles = require_positive_int(body, "requested_bottles")

        winery = db.wineries.get(b["winery_id"])

        # FK resolution (scoped to the batch's winery)
        product = db.products.get(product_id)
        if product is None or product.get("winery_id") != b["winery_id"]:
            raise err(ERR_FK_NOT_FOUND, "Referenced product not found")

        # state: batch must be BOTTLING
        if b["status"] != "BOTTLING":
            raise err(ERR_INVALID_STATE, "Batch is not in BOTTLING")

        # premises suspension gate
        if winery["status"] != "ACTIVE":
            raise err(ERR_WINERY_SUSPENDED, "Winery is suspended")

        # product must source from this batch and not be discontinued
        if product.get("source_batch_id") != b["id"] or product["status"] == "DISCONTINUED":
            raise err(ERR_FK_NOT_FOUND, "Product is not sourced from this batch or is discontinued")

        # bulk sufficiency
        gallons = calc.removal_gallons(requested_bottles, product["bottle_volume_ml"])
        if gallons > b["available_bulk_gallons"]:
            raise err(ERR_INSUFFICIENT_BULK, "Removal exceeds available bulk gallons")

        excise = calc.excise_cents(b["beverage_class"], b["abv_percent"], gallons)

        # CASCADE hop 1: batch
        b["bottled_volume_gallons"] = b["bottled_volume_gallons"] + gallons
        recompute_batch_available(b)
        touch(b)

        # CASCADE hop 2: product mint
        product["on_hand_bottles"] = product["on_hand_bottles"] + requested_bottles
        product["free_bottles"] = product["on_hand_bottles"] - product["allocated_bottles"]
        touch(product)

        # CASCADE hop 3: premises books tax + bulk recompute
        winery["bottled_taxpaid_volume_gallons"] = winery["bottled_taxpaid_volume_gallons"] + gallons
        winery["excise_tax_owed_cents"] = winery["excise_tax_owed_cents"] + excise
        recompute_winery_bulk(winery)
        touch(winery)

        # two ledger entries
        append_ledger(winery["id"], "BOTTLING_REMOVAL", "PRODUCTION_BATCH", b["id"],
                      gallons, 0, f"Bottling removal of {requested_bottles} bottles from batch {b['lot_code']}")
        append_ledger(winery["id"], "EXCISE_ACCRUAL", "PRODUCTION_BATCH", b["id"],
                      gallons, excise, f"Excise accrual on bottling run for batch {b['lot_code']}")

        return success(public(b), status=201)
