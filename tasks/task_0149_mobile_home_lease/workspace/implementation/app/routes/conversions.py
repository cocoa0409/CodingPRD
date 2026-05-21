"""ConversionRequest routes: open (POST /lots/{lot_id}/conversion-requests),
accept/reject by resident, finalize by park manager, get.
"""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import ApiError
from ..responses import success_response
from ..services.calculations import conversion_offer_meets_threshold
from ..services.entities import (
    get_conversion_or_404,
    get_lot_or_404,
    get_resident_body_or_404,
    init_common_fields,
    touch,
)
from ..services.serialization import serialize_conversion
from ..store import store
from ..validation import get_json_body, require_int, require_string


bp = Blueprint("conversions", __name__)


@bp.route("/lots/<lot_id>/conversion-requests", methods=["POST"])
@require_auth("ParkManager")
def open_conversion(lot_id: str):
    lot = get_lot_or_404(lot_id)
    body = get_json_body()
    buyer = require_string(body, "prospective_buyer_resident_id")
    offer_price = require_int(body, "offer_price_cents", strict_positive=True)

    # Body-resource existence
    get_resident_body_or_404(buyer)

    # Conversion requires PARK_OWNED lot
    if lot["ownership_mode"] != "PARK_OWNED":
        raise ApiError("ERR_LOT_ALREADY_RESIDENT_OWNED", "Lot is not PARK_OWNED.")

    with store.lock:
        c = init_common_fields({
            "lot_id": lot_id,
            "prospective_buyer_resident_id": buyer,
            "offer_price_cents": int(offer_price),
            "status": "OFFERED",
        })
        store.conversion_requests[c["id"]] = c

    return success_response(serialize_conversion(c), status=201)


@bp.route("/conversion-requests/<conv_id>/accept", methods=["POST"])
@require_auth("Resident")
def accept_conversion(conv_id: str):
    c = get_conversion_or_404(conv_id)
    user_id = g.user_id

    # Ownership check (priority 5)
    if c["prospective_buyer_resident_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", "You are not the prospective buyer.")

    with store.lock:
        if c["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", "Conversion is not in OFFERED state.")
        lot = store.lots.get(c["lot_id"])
        if lot is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Lot missing.")
        if lot["ownership_mode"] != "PARK_OWNED":
            raise ApiError("ERR_LOT_ALREADY_RESIDENT_OWNED", "Lot is no longer PARK_OWNED.")
        # Find home on the lot (its assessed value)
        home = _find_home_on_lot(lot["id"])
        if home is None:
            raise ApiError("ERR_INVALID_STATE", "No home present on this lot for buyout valuation.")
        # Priority 18 / threshold rule
        if not conversion_offer_meets_threshold(c["offer_price_cents"], home["assessed_value_cents"]):
            raise ApiError("ERR_BUYOUT_UNDERVALUED", "Offer price is below assessed value.")
        c["status"] = "ACCEPTED"
        touch(c)

    return success_response(serialize_conversion(c), status=200)


@bp.route("/conversion-requests/<conv_id>/reject", methods=["POST"])
@require_auth("Resident")
def reject_conversion(conv_id: str):
    c = get_conversion_or_404(conv_id)
    user_id = g.user_id

    if c["prospective_buyer_resident_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", "You are not the prospective buyer.")

    with store.lock:
        if c["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", "Conversion is not in OFFERED state.")
        c["status"] = "REJECTED"
        touch(c)

    return success_response(serialize_conversion(c), status=200)


@bp.route("/conversion-requests/<conv_id>/finalize", methods=["POST"])
@require_auth("ParkManager")
def finalize_conversion(conv_id: str):
    c = get_conversion_or_404(conv_id)

    with store.lock:
        if c["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", "Conversion is not in ACCEPTED state.")
        lot = store.lots.get(c["lot_id"])
        if lot is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Lot missing.")
        if lot["ownership_mode"] != "PARK_OWNED":
            raise ApiError("ERR_LOT_ALREADY_RESIDENT_OWNED", "Lot is already RESIDENT_OWNED.")

        # Cascade
        lot["ownership_mode"] = "RESIDENT_OWNED"
        touch(lot)
        # Park.ownership_pool_count -= 1
        park = store.parks.get(lot["park_id"])
        if park is not None:
            park["ownership_pool_count"] = max(0, park.get("ownership_pool_count", 0) - 1)
            touch(park)
        # Home.owner_resident_id := buyer
        home = _find_home_on_lot(lot["id"])
        if home is not None:
            home["owner_resident_id"] = c["prospective_buyer_resident_id"]
            touch(home)
        # If lot has no current_lease_id: create CURRENT lease
        if lot.get("current_lease_id") is None:
            from ..services.entities import init_common_fields as _init
            from ..clock import clock as _clock
            successor = _init({
                "lot_id": lot["id"],
                "resident_id": c["prospective_buyer_resident_id"],
                "monthly_rent_cents": int(lot["base_rent_cents"]),
                "start_date": _clock.iso_now(),
                "status": "CURRENT",
                "outstanding_balance_cents": 0,
                "predecessor_lease_id": None,
            })
            store.leases[successor["id"]] = successor
            lot["current_lease_id"] = successor["id"]
            touch(lot)

        c["status"] = "CLOSED"
        touch(c)

    return success_response(serialize_conversion(c), status=200)


@bp.route("/conversion-requests/<conv_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_conversion(conv_id: str):
    c = get_conversion_or_404(conv_id)
    return success_response(serialize_conversion(c), status=200)


def _find_home_on_lot(lot_id: str):
    for h in store.homes.values():
        if h.get("lot_id") == lot_id:
            return h
    return None


__all__ = ["bp"]
