"""Pack units, sealing and shipping (PRD 3.9)."""

from flask import Blueprint, g

import enums
from db import db, new_record, sorted_records, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services import calc
from services.lookup import (
    cert_doc_or_404,
    guard_disposition,
    lot_pack_units,
    pack_unit_or_404,
    production_lot_or_404,
    require_unique,
    spec_for_lot,
)
from util import dec
from validate import (
    field_bool,
    field_int,
    field_num,
    field_str,
    paginate,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("pack_units", __name__)

PACKABLE_LOT_STATES = ("CERTIFIED", "PACKED")


def _lot_of(pack):
    lot = db.production_lots.get(pack["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")
    return lot


@bp.post("/pack-units")
@endpoint("ShippingClerk")
def create_pack_unit():
    body = g.body
    production_lot_id = field_str(body, "production_lot_id")
    certification_document_id = field_str(body, "certification_document_id")
    label_serial = field_str(body, "label_serial")
    net_weight_kg = field_num(body, "net_weight_kg", required=False, exclusive_min=0)
    actual_count = field_int(body, "actual_count", required=False, minimum=0)
    label_fields_complete = field_bool(
        body, "label_fields_complete", required=False, default=False
    )

    lot = production_lot_or_404(production_lot_id)
    cert = cert_doc_or_404(certification_document_id)

    spec = spec_for_lot(lot)
    pack_mode = spec["packaging_mode"]
    if pack_mode == "BY_COUNT" and actual_count is None:
        raise ApiError("ERR_VALIDATION", "actual_count is required for a BY_COUNT part.")
    if pack_mode == "BY_WEIGHT" and net_weight_kg is None:
        raise ApiError("ERR_VALIDATION", "net_weight_kg is required for a BY_WEIGHT part.")

    require_unique("pack_units", "label_serial", label_serial)

    guard_disposition(lot)

    # PRD 3.9 declares no lot process_state gate on pack opening; the gate lives
    # on sealing, which is where pieces actually leave the lot.
    if cert["production_lot_id"] != production_lot_id:
        raise ApiError("ERR_CERT_LOT_MISMATCH")

    pack = new_record(
        {
            "production_lot_id": production_lot_id,
            "certification_document_id": certification_document_id,
            "label_serial": label_serial,
            "pack_mode": pack_mode,
            "net_weight_kg": net_weight_kg if pack_mode == "BY_WEIGHT" else None,
            "actual_count": actual_count if pack_mode == "BY_COUNT" else None,
            "declared_count": calc.declared_count(
                pack_mode, actual_count, net_weight_kg, spec["pieces_per_kg"]
            ),
            "count_tolerance_pieces": calc.count_tolerance_pieces(
                spec["nominal_pack_count"], spec["count_tolerance_pct"]
            ),
            "label_fields_complete": bool(label_fields_complete),
            "status": "OPEN",
            "sealed_at": None,
            "shipped_at": None,
            "recall_reason": None,
        }
    )
    db.pack_units[pack["id"]] = pack
    return created(pack)


@bp.get("/pack-units/<pack_id>")
@endpoint(ANY_ROLE)
def get_pack_unit(pack_id):
    return ok(pack_unit_or_404(pack_id))


@bp.get("/pack-units")
@endpoint(ANY_ROLE)
def list_pack_units():
    limit, offset = pagination()
    production_lot_id = query_str("production_lot_id")
    certification_document_id = query_str("certification_document_id")
    status = query_enum("status", enums.PACK_UNIT_STATUSES)

    records = sorted_records(db.pack_units.values())
    if production_lot_id is not None:
        records = [r for r in records if r["production_lot_id"] == production_lot_id]
    if certification_document_id is not None:
        records = [
            r
            for r in records
            if r["certification_document_id"] == certification_document_id
        ]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/pack-units/<pack_id>/seal")
@endpoint("ShippingClerk")
def seal_pack_unit(pack_id):
    pack = pack_unit_or_404(pack_id)
    lot = _lot_of(pack)
    guard_disposition(lot)

    if pack["status"] != "OPEN":
        raise ApiError("ERR_INVALID_PACK_UNIT_STATE")
    if lot["process_state"] not in PACKABLE_LOT_STATES:
        raise ApiError("ERR_INVALID_LOT_STATE")

    spec = spec_for_lot(lot)
    declared = int(pack["declared_count"])
    tolerance = int(pack["count_tolerance_pieces"])
    if abs(declared - int(spec["nominal_pack_count"])) > tolerance:
        raise ApiError("ERR_PACK_COUNT_OUT_OF_TOLERANCE")
    if declared > int(lot["available_count"]):
        raise ApiError("ERR_PIECE_COUNT_INVALID")

    pack["status"] = "SEALED"
    pack["sealed_at"] = db.now_iso()
    touch(pack)

    lot["packed_count"] = int(lot["packed_count"]) + declared
    lot["available_count"] = int(lot["available_count"]) - declared
    lot["process_state"] = "PACKED"
    touch(lot)
    return ok(pack)


@bp.post("/pack-units/<pack_id>/reopen")
@endpoint("ShippingClerk")
def reopen_pack_unit(pack_id):
    field_str(g.body, "reason", allow_empty=True)

    pack = pack_unit_or_404(pack_id)
    lot = _lot_of(pack)
    guard_disposition(lot)

    if pack["status"] != "SEALED":
        raise ApiError("ERR_INVALID_PACK_UNIT_STATE")
    if lot["process_state"] != "PACKED":
        raise ApiError("ERR_INVALID_LOT_STATE")

    declared = int(pack["declared_count"])
    pack["status"] = "OPEN"
    pack["sealed_at"] = None
    touch(pack)

    lot["packed_count"] = int(lot["packed_count"]) - declared
    lot["available_count"] = int(lot["available_count"]) + declared
    siblings = [p for p in lot_pack_units(lot["id"]) if p["id"] != pack["id"]]
    if not any(p["status"] in ("SEALED", "SHIPPED", "RECALLED") for p in siblings):
        lot["process_state"] = "CERTIFIED"
    touch(lot)
    return ok(pack)


@bp.post("/pack-units/<pack_id>/ship")
@endpoint("ShippingClerk")
def ship_pack_unit(pack_id):
    pack = pack_unit_or_404(pack_id)
    lot = _lot_of(pack)
    guard_disposition(lot)

    if pack["status"] != "SEALED":
        raise ApiError("ERR_INVALID_PACK_UNIT_STATE")
    if lot["process_state"] != "PACKED":
        raise ApiError("ERR_INVALID_LOT_STATE")

    cert = db.certification_documents.get(pack["certification_document_id"])
    if cert is None or cert["production_lot_id"] != lot["id"]:
        raise ApiError("ERR_CERT_LOT_MISMATCH")
    if cert["status"] != "ISSUED":
        raise ApiError("ERR_CERT_NOT_ISSUED")

    if not pack["label_fields_complete"]:
        raise ApiError("ERR_PACK_LABEL_INCOMPLETE")

    pack["status"] = "SHIPPED"
    pack["shipped_at"] = db.now_iso()
    touch(pack)

    packs = lot_pack_units(lot["id"])
    if packs and all(p["status"] == "SHIPPED" for p in packs):
        lot["process_state"] = "SHIPPED"
        touch(lot)
    return ok(pack)
