"""Vessel routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..common import get_json_body, positive_int, positive_number, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import enforce_boater_owns, get_boater, get_marina, get_vessel
from ..response import respond
from ..serializers import vessel_view
from ..store import store


bp = Blueprint("vessels", __name__, url_prefix="/marinas")


@bp.post("/<marina_id>/boaters/<boater_id>/vessels")
@require_auth("Boater", "DockMaster")
def create_vessel(marina_id: str, boater_id: str):
    body = get_json_body()
    require_fields(body, "name", "loa_feet", "beam_feet", "draft_feet")
    loa = positive_number(body["loa_feet"], "loa_feet")
    beam = positive_number(body["beam_feet"], "beam_feet")
    draft = positive_number(body["draft_feet"], "draft_feet")
    holding = body.get("holding_tank_gallons")
    if holding is not None:
        holding = positive_int(holding, "holding_tank_gallons", allow_zero=True)
    with store.lock:
        get_marina(marina_id)
        get_boater(marina_id, boater_id)
        enforce_boater_owns(boater_id)
        vessel = {
            "marina_id": marina_id,
            "boater_id": boater_id,
            "name": body["name"],
            "loa_feet": loa,
            "beam_feet": beam,
            "draft_feet": draft,
            "holding_tank_gallons": holding,
        }
        stamp_new(vessel)
        store.vessels[vessel["id"]] = vessel
    return respond(vessel_view(vessel), 201)


@bp.get("/<marina_id>/vessels/<vessel_id>")
@require_auth("Boater", "DockMaster", "BillingClerk")
def fetch_vessel(marina_id: str, vessel_id: str):
    with store.lock:
        get_marina(marina_id)
        vessel = get_vessel(marina_id, vessel_id)
        if g.user_role == "Boater":
            enforce_boater_owns(vessel["boater_id"])
        return respond(vessel_view(vessel), 200)
