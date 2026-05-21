"""Slip routes — create, read, and patch status (PATCH requires If-Match)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..common import (
    bump,
    check_if_match,
    get_json_body,
    positive_int,
    positive_number,
    require_fields,
    stamp_new,
)
from ..errors import ApiError
from ..marina_helpers import get_marina, get_slip
from ..response import respond
from ..serializers import slip_view
from ..store import store


bp = Blueprint("slips", __name__, url_prefix="/marinas")


VALID_SLIP_STATUSES = {"AVAILABLE", "MAINTENANCE", "RETIRED"}


@bp.post("/<marina_id>/slips")
@require_auth("DockMaster")
def create_slip(marina_id: str):
    body = get_json_body()
    require_fields(body, "code", "length_feet", "beam_feet", "depth_feet", "flat_daily_charge_cents")
    code = body["code"]
    if not isinstance(code, str) or not code:
        raise ApiError("ERR_BAD_REQUEST", "code must be a non-empty string")
    length = positive_number(body["length_feet"], "length_feet")
    beam = positive_number(body["beam_feet"], "beam_feet")
    depth = positive_number(body["depth_feet"], "depth_feet")
    flat = positive_int(body["flat_daily_charge_cents"], "flat_daily_charge_cents", allow_zero=True)
    liveaboard_allowed = bool(body.get("liveaboard_allowed", False))

    with store.lock:
        get_marina(marina_id)
        # Code unique within marina
        for s in store.slips.values():
            if s.get("marina_id") == marina_id and s.get("code") == code:
                raise ApiError("ERR_BAD_REQUEST", "Slip code must be unique within marina")
        slip = {
            "marina_id": marina_id,
            "code": code,
            "length_feet": length,
            "beam_feet": beam,
            "depth_feet": depth,
            "flat_daily_charge_cents": flat,
            "liveaboard_allowed": liveaboard_allowed,
            "status": "AVAILABLE",
        }
        stamp_new(slip)
        store.slips[slip["id"]] = slip
    return respond(slip_view(slip), 201)


@bp.get("/<marina_id>/slips/<slip_id>")
@require_auth("DockMaster", "BillingClerk", "Boater")
def fetch_slip(marina_id: str, slip_id: str):
    with store.lock:
        get_marina(marina_id)
        slip = get_slip(marina_id, slip_id)
        return respond(slip_view(slip), 200)


@bp.patch("/<marina_id>/slips/<slip_id>/status")
@require_auth("DockMaster")
def patch_slip_status(marina_id: str, slip_id: str):
    body = get_json_body()
    require_fields(body, "status")
    new_status = body["status"]
    if new_status not in VALID_SLIP_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid slip status: {new_status}")
    with store.lock:
        get_marina(marina_id)
        slip = get_slip(marina_id, slip_id)
        # If-Match required for PATCH
        check_if_match(slip)
        slip["status"] = new_status
        bump(slip)
        return respond(slip_view(slip), 200)
