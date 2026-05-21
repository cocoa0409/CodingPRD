"""Waitlist routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format
from ..common import get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import (
    enforce_boater_owns,
    get_boater,
    get_marina,
    get_vessel,
    get_waitlist_entry,
    next_waitlist_seq,
    parse_required_iso,
)
from ..response import respond
from ..serializers import waitlist_view
from ..store import store


bp = Blueprint("waitlist", __name__, url_prefix="/marinas")


@bp.post("/<marina_id>/waitlist")
@require_auth("Boater")
def create_waitlist(marina_id: str):
    body = get_json_body()
    require_fields(body, "boater_id", "vessel_id", "requested_check_in", "requested_check_out")
    req_in = parse_required_iso(body, "requested_check_in")
    req_out = parse_required_iso(body, "requested_check_out")
    if not (req_out > req_in):
        raise ApiError(
            "ERR_INVALID_DATE_RANGE",
            "requested_check_out must be strictly after requested_check_in",
        )
    liveaboard = bool(body.get("liveaboard", False))
    with store.lock:
        get_marina(marina_id)
        boater = get_boater(marina_id, body["boater_id"])
        enforce_boater_owns(boater["id"])
        vessel = get_vessel(marina_id, body["vessel_id"])
        if vessel.get("boater_id") != boater["id"]:
            raise ApiError("ERR_NOT_FOUND", "Vessel does not belong to the named boater")

        seq = next_waitlist_seq(marina_id)
        entry = {
            "marina_id": marina_id,
            "boater_id": boater["id"],
            "vessel_id": vessel["id"],
            "requested_check_in": iso_format(req_in),
            "requested_check_out": iso_format(req_out),
            "liveaboard": liveaboard,
            "sequence_no": seq,
            "status": "QUEUED",
            "promoted_reservation_id": None,
        }
        stamp_new(entry, with_common=False)
        store.waitlist[entry["id"]] = entry
    return respond(waitlist_view(entry), 201)


@bp.get("/<marina_id>/waitlist/<waitlist_id>")
@require_auth("Boater", "DockMaster")
def fetch_waitlist(marina_id: str, waitlist_id: str):
    with store.lock:
        get_marina(marina_id)
        entry = get_waitlist_entry(marina_id, waitlist_id)
        if g.user_role == "Boater":
            enforce_boater_owns(entry["boater_id"])
        return respond(waitlist_view(entry), 200)


@bp.post("/<marina_id>/waitlist/<waitlist_id>/cancel")
@require_auth("Boater")
def cancel_waitlist(marina_id: str, waitlist_id: str):
    with store.lock:
        get_marina(marina_id)
        entry = get_waitlist_entry(marina_id, waitlist_id)
        enforce_boater_owns(entry["boater_id"])
        if entry.get("status") != "QUEUED":
            raise ApiError("ERR_INVALID_STATE", "Waitlist entry is not QUEUED")
        entry["status"] = "CANCELLED"
        return respond(waitlist_view(entry), 200)
