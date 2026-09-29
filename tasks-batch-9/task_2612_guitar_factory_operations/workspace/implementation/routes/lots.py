"""Tonewood lots: receipt, permits, drying, conditioning, release (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import validate as v
from constants import (CITES_APPENDICES, LOT_STATUSES, MOISTURE_MAX_PCT,
                       MOISTURE_MIN_PCT, PERMIT_STATUSES, SPECIES_CODES)
from envelope import object_response, paginate
from errors import ApiError
from serialize import lot_view
from store import LOTS, ROOMS, new_record, now_utc, touch

bp = Blueprint("lots", __name__)

ZERO = Decimal("0.00")


def _room_guard(room):
    if room["climate_status"] == "QUARANTINED":
        raise ApiError("ERR_ROOM_QUARANTINED", "the storage room is quarantined")


def _moisture_guard(lot):
    moisture = Decimal(lot["moisture_content_pct"])
    if moisture < MOISTURE_MIN_PCT or moisture > MOISTURE_MAX_PCT:
        raise ApiError("ERR_MOISTURE_OUT_OF_BAND",
                       "moisture_content_pct is outside the 6.0-8.0 band")


@bp.post("/tonewood-lots")
def create_lot():
    auth.require(auth.WOOD_BUYER)
    body = v.body()
    lot_code = v.get_str(body, "lot_code", min_len=1, max_len=64)
    species = v.get_enum(body, "species_code", SPECIES_CODES)
    appendix = v.get_enum(body, "cites_appendix", CITES_APPENDICES)
    received = v.get_dec(body, "board_feet_received", gt=0, scale=2)
    moisture = v.get_dec(body, "moisture_content_pct", minimum=2.0,
                         maximum=30.0)
    room_id = v.get_id(body, "storage_room_id")
    permit_number = v.get_str(body, "permit_number", required=False, min_len=1,
                              max_len=40)
    room = v.fetch(ROOMS, room_id, "ERR_STORAGE_ROOM_NOT_FOUND")
    if room["room_type"] not in ("DRY_STORE", "KILN"):
        v.bad("storage_room_id must name a DRY_STORE or KILN room")
    v.unique_code(LOTS, "lot_code", lot_code)
    _room_guard(room)

    protected = appendix != "NONE"
    rec = new_record(LOTS, {
        "lot_code": lot_code,
        "species_code": species,
        "cites_appendix": appendix,
        "permit_number": permit_number,
        "permit_status": "PENDING" if protected else "NOT_REQUIRED",
        "attested_by_user_id": None,
        "board_feet_received": calc.bf(received),
        "board_feet_kerf_loss": ZERO,
        "board_feet_available": calc.bf(received),
        "board_feet_unassigned": ZERO,
        "board_feet_reserved": ZERO,
        "board_feet_consumed": ZERO,
        "board_feet_scrapped": ZERO,
        "moisture_at_receipt_pct": moisture,
        "moisture_content_pct": moisture,
        "storage_room_id": room_id,
        "status": "PERMIT_HOLD" if protected else "RECEIVED",
    })
    return object_response(lot_view(rec), 201)


@bp.get("/tonewood-lots/<lot_id>")
def read_lot(lot_id):
    auth.require_staff()
    return object_response(lot_view(
        v.fetch(LOTS, lot_id, "ERR_TONEWOOD_LOT_NOT_FOUND")))


@bp.get("/tonewood-lots")
def list_lots():
    auth.require_staff()
    rows = v.apply_filters(list(LOTS.values()), [
        ("storage_room_id", v.filter_value("storage_room_id")),
        ("species_code", v.filter_enum("species_code", SPECIES_CODES)),
        ("cites_appendix", v.filter_enum("cites_appendix", CITES_APPENDICES)),
        ("permit_status", v.filter_enum("permit_status", PERMIT_STATUSES)),
        ("status", v.filter_enum("status", LOT_STATUSES)),
    ])
    rows.sort(key=lambda r: r["lot_code"])
    return paginate(rows, lot_view)


@bp.post("/tonewood-lots/<lot_id>/attest-permit")
def attest_permit(lot_id):
    user_id, _ = auth.require(auth.COMPLIANCE_OFFICER)
    body = v.body()
    permit_number = v.get_str(body, "permit_number", min_len=1, max_len=40)
    lot = v.fetch(LOTS, lot_id, "ERR_TONEWOOD_LOT_NOT_FOUND")
    if lot["status"] != "PERMIT_HOLD":
        raise ApiError("ERR_LOT_STATE_INVALID",
                       "attestation is only accepted from PERMIT_HOLD")
    lot["permit_number"] = permit_number
    lot["permit_status"] = "VERIFIED"
    lot["attested_by_user_id"] = user_id
    lot["status"] = "RECEIVED"
    touch(lot)
    return object_response(lot_view(lot))


@bp.post("/tonewood-lots/<lot_id>/reject")
def reject_lot(lot_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    body = v.body()
    v.get_str(body, "reason", required=False)
    lot = v.fetch(LOTS, lot_id, "ERR_TONEWOOD_LOT_NOT_FOUND")
    if lot["status"] in ("DEPLETED", "REJECTED"):
        raise ApiError("ERR_LOT_STATE_INVALID",
                       "a DEPLETED or REJECTED lot cannot be rejected")
    lot["permit_status"] = "INVALID"
    lot["status"] = "REJECTED"
    touch(lot)
    domain.reject_lot_cascade(lot)
    return object_response(lot_view(lot))


@bp.post("/tonewood-lots/<lot_id>/moisture-readings")
def moisture_reading(lot_id):
    auth.require(auth.WOOD_BUYER, auth.PLANT_ADMIN)
    body = v.body()
    moisture = v.get_dec(body, "moisture_content_pct", minimum=2.0,
                         maximum=30.0)
    lot = v.fetch(LOTS, lot_id, "ERR_TONEWOOD_LOT_NOT_FOUND")
    if lot["status"] not in ("RECEIVED", "KILN_DRYING"):
        raise ApiError("ERR_LOT_STATE_INVALID",
                       "moisture readings are only accepted while drying")
    lot["moisture_content_pct"] = moisture
    lot["status"] = "KILN_DRYING"
    touch(lot)
    return object_response(lot_view(lot))


@bp.post("/tonewood-lots/<lot_id>/condition")
def condition_lot(lot_id):
    auth.require(auth.WOOD_BUYER)
    lot = v.fetch(LOTS, lot_id, "ERR_TONEWOOD_LOT_NOT_FOUND")
    if lot["status"] not in ("RECEIVED", "KILN_DRYING"):
        raise ApiError("ERR_LOT_STATE_INVALID",
                       "conditioning is accepted from RECEIVED or KILN_DRYING")
    room = ROOMS.get(lot["storage_room_id"])
    if room is not None:
        _room_guard(room)
        if room["climate_status"] != "IN_SPEC":
            raise ApiError("ERR_ROOM_CLIMATE_OUT_OF_SPEC",
                           "the storage room is out of spec")
    _moisture_guard(lot)
    lot["status"] = "CONDITIONED"
    touch(lot)
    return object_response(lot_view(lot))


@bp.post("/tonewood-lots/<lot_id>/release")
def release_lot(lot_id):
    auth.require(auth.WOOD_BUYER)
    lot = v.fetch(LOTS, lot_id, "ERR_TONEWOOD_LOT_NOT_FOUND")
    if lot["status"] != "CONDITIONED":
        raise ApiError("ERR_LOT_STATE_INVALID",
                       "release is only accepted from CONDITIONED")
    if lot["permit_status"] not in ("NOT_REQUIRED", "VERIFIED"):
        raise ApiError("ERR_CITES_PERMIT_UNVERIFIED",
                       "the CITES permit is not verified")
    _moisture_guard(lot)
    lot["status"] = "RELEASED"
    touch(lot)
    return object_response(lot_view(lot))
