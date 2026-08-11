"""Raw ingredient lots and the void of a consumption record."""

from decimal import Decimal
from flask import Blueprint

from . import constants as C
from . import lookup
from .auth import authorize
from .cascades import ingredient_quarantine_cascade
from .envelope import list_response, object_response
from .errors import ApiError
from .store import base_record, collection_sorted, db, touch
from .util import dec, round2
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_bool,
)

bp = Blueprint("ingredients", __name__)

READ_ROLES = ("ProductionOperator", "QaManager", "ComplianceOfficer", "PlatformAdmin")


@bp.post("/ingredient-lots")
def create_ingredient_lot():
    authorize("ProductionOperator", "PlatformAdmin")
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field(
                "ingredient_type", "enum", required=True, members=C.INGREDIENT_TYPES
            ),
            field("supplier_lot_code", "string", required=True),
            field("received_on_date", "datetime", required=True),
            field("expiry_date", "datetime", required=True),
            field("quantity_received", "number", required=True, positive=True),
        ],
    )
    quantity = round2(data["quantity_received"])
    record = base_record()
    record.update(
        {
            "ingredient_type": data["ingredient_type"],
            "supplier_lot_code": data["supplier_lot_code"],
            "received_on_date": data["received_on_date"],
            "expiry_date": data["expiry_date"],
            "quantity_received": quantity,
            "quantity_consumed": Decimal("0.00"),
            "quantity_available": quantity,
            "status": "AVAILABLE",
            "quarantine_cleared_count": 0,
            "pre_quarantine_status": None,
        }
    )
    db.ingredient_lots[record["id"]] = record
    return object_response(record, 201)


@bp.post("/ingredient-lots/<id>/quarantine")
def quarantine_ingredient_lot(id):
    authorize("ComplianceOfficer", "PlatformAdmin")
    lot = lookup.ingredient_lot(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if lot["status"] not in ("AVAILABLE", "PARTIALLY_CONSUMED", "CONSUMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an AVAILABLE, PARTIALLY_CONSUMED or CONSUMED lot may be quarantined.",
        )
    lot["pre_quarantine_status"] = lot["status"]
    lot["status"] = "QUARANTINED"
    touch(lot)
    ingredient_quarantine_cascade(lot)
    return object_response(lot)


@bp.post("/ingredient-lots/<id>/clear-quarantine")
def clear_ingredient_lot_quarantine(id):
    authorize("ComplianceOfficer", "PlatformAdmin")
    lot = lookup.ingredient_lot(id)
    body_dict()
    if lot["status"] != "QUARANTINED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a QUARANTINED lot may be cleared."
        )
    lot["status"] = lot["pre_quarantine_status"] or "AVAILABLE"
    lot["pre_quarantine_status"] = None
    lot["quarantine_cleared_count"] = int(lot["quarantine_cleared_count"]) + 1
    touch(lot)
    return object_response(lot)


@bp.get("/ingredient-lots/<id>")
def read_ingredient_lot(id):
    authorize(*READ_ROLES)
    return object_response(lookup.ingredient_lot(id))


@bp.get("/ingredient-lots/<id>/uses")
def list_ingredient_lot_uses(id):
    authorize(*READ_ROLES)
    lot = lookup.ingredient_lot(id)
    voided = query_bool("voided")
    limit, offset = pagination()
    rows = collection_sorted(
        db.batch_ingredient_uses,
        lambda u: u["ingredient_lot_id"] == lot["id"]
        and (voided is None or bool(u["voided"]) == voided),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/batch-ingredient-uses/<id>/void")
def void_ingredient_use(id):
    authorize("ProductionOperator", "PlatformAdmin")
    use = lookup.batch_ingredient_use(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if use["voided"]:
        raise ApiError(
            "ERR_INVALID_STATE", "This consumption record has already been voided."
        )

    use["voided"] = True
    use["voided_at"] = db.clock
    touch(use)

    lot = db.ingredient_lots.get(use["ingredient_lot_id"])
    if lot is not None:
        quantity = dec(use["quantity_used"])
        lot["quantity_consumed"] = round2(dec(lot["quantity_consumed"]) - quantity)
        lot["quantity_available"] = round2(dec(lot["quantity_available"]) + quantity)
        touch(lot)
    return object_response(use)
