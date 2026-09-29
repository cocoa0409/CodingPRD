"""State-of-charge reservations (PRD 3.2)."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from numeric import r3
from services import core

bp = Blueprint("reservations", __name__)

PURPOSES = ("ENERGY_ARBITRAGE", "ANCILLARY", "CAPACITY")
STATUSES = ("HELD", "CONSUMED", "RELEASED", "EXPIRED")


@bp.post("/soc-reservations")
def create_reservation():
    middleware.authorize("MarketTrader", "AssetManager")
    body = v.json_body()

    asset_id = v.ident(body, "asset_id")
    purpose = v.enum(body, "purpose", PURPOSES)
    reserved_mwh = v.num(body, "reserved_mwh", gt=0)
    start_raw, start = v.timestamp(body, "window_start")
    end_raw, end = v.timestamp(body, "window_end")
    expected_version = v.integer(body, "expected_asset_version")
    if not end > start:
        raise errors.bad_request(
            "Field 'window_end' must be strictly later than 'window_start'.")

    asset = core.get_asset(asset_id)

    if expected_version != asset["version"]:
        raise ApiError(errors.ERR_STALE_ASSET_VERSION, 412,
                       "The asset has been modified since it was last read.")
    core.gate_lockout(asset)
    core.gate_market_available(asset)

    now = db.clock_now()
    core.reservation_waterfall(asset, purpose, reserved_mwh, start, end, now)

    reservation = db.new_row()
    reservation.update({
        "asset_id": asset_id,
        "purpose": purpose,
        "reserved_mwh": r3(reserved_mwh),
        "window_start": start_raw,
        "window_end": end_raw,
        "expected_asset_version": expected_version,
        "priority_rank": core.PRIORITY_RANKS[purpose],
        "status": "HELD",
        "consumed_mwh": 0.0,
        "released_reason": None,
    })
    db.reservations[reservation["id"]] = reservation

    core.recompute_pool(asset)
    db.touch(asset)
    return response.created(db.serialize(reservation))


@bp.get("/soc-reservations/<reservation_id>")
def read_reservation(reservation_id):
    middleware.any_role()
    reservation = core.get_reservation(reservation_id)
    return response.ok(db.serialize(reservation))


@bp.get("/soc-reservations")
def list_reservations():
    middleware.any_role()
    limit, offset = v.pagination()
    asset_id = v.query_str("asset_id")
    purpose = v.query_enum("purpose", PURPOSES)
    status = v.query_enum("status", STATUSES)

    rows = list(db.reservations.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if purpose is not None:
        rows = [r for r in rows if r["purpose"] == purpose]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/soc-reservations/<reservation_id>/release")
def release_reservation(reservation_id):
    middleware.authorize("MarketTrader", "AssetManager")
    reservation = core.get_reservation(reservation_id)

    if reservation["status"] != "HELD":
        raise ApiError(errors.ERR_RESERVATION_NOT_HELD, 409,
                       "The reservation is not HELD.")
    live = [b for b in core.bids_of_reservation(reservation_id)
            if b["status"] in ("SUBMITTED", "CLEARED")]
    if live:
        raise ApiError(errors.ERR_RESERVATION_NOT_HELD, 409,
                       "Live market exposure still references this reservation.")

    reservation["status"] = "RELEASED"
    reservation["released_reason"] = "OPERATOR_RELEASE"
    db.touch(reservation)

    core.withdraw_bids_of_reservation(reservation, ("DRAFT",), "TRADER_WITHDRAWAL")

    asset = db.assets.get(reservation["asset_id"])
    if asset is not None:
        core.recompute_pool(asset)
        db.touch(asset)
    return response.ok(db.serialize(reservation))
