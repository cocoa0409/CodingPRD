"""Tow assistance routes — contract + tow events."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format
from ..common import bump, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import (
    enforce_boater_owns,
    get_boater,
    get_marina,
    get_slip,
    get_tow_contract,
    parse_required_iso,
)
from ..pricing import tow_event_charge
from ..response import respond
from ..serializers import tow_contract_view, tow_event_view
from ..store import store


bp = Blueprint("tow", __name__, url_prefix="/marinas")


VALID_TIERS = {"BASIC", "PREMIUM"}


@bp.post("/<marina_id>/boaters/<boater_id>/tow-contracts")
@require_auth("Boater", "DockMaster")
def create_contract(marina_id: str, boater_id: str):
    body = get_json_body()
    require_fields(body, "tier")
    tier = body["tier"]
    if tier not in VALID_TIERS:
        raise ApiError("ERR_BAD_REQUEST", "tier must be BASIC or PREMIUM")
    with store.lock:
        get_marina(marina_id)
        boater = get_boater(marina_id, boater_id)
        enforce_boater_owns(boater_id)
        contract = {
            "marina_id": marina_id,
            "boater_id": boater["id"],
            "tier": tier,
            "tows_remaining": 2 if tier == "BASIC" else -1,
            "status": "ACTIVE",
        }
        stamp_new(contract)
        store.tow_contracts[contract["id"]] = contract
    return respond(tow_contract_view(contract), 201)


@bp.get("/<marina_id>/tow-contracts/<contract_id>")
@require_auth("Boater", "DockMaster", "BillingClerk")
def fetch_contract(marina_id: str, contract_id: str):
    with store.lock:
        get_marina(marina_id)
        contract = get_tow_contract(marina_id, contract_id)
        if g.user_role == "Boater":
            enforce_boater_owns(contract["boater_id"])
        return respond(tow_contract_view(contract), 200)


@bp.post("/<marina_id>/tow-contracts/<contract_id>/tow-events")
@require_auth("DockMaster")
def create_tow_event(marina_id: str, contract_id: str):
    body = get_json_body()
    require_fields(body, "occurred_at", "from_position", "to_slip_id")
    occurred_at = parse_required_iso(body, "occurred_at")
    with store.lock:
        get_marina(marina_id)
        contract = get_tow_contract(marina_id, contract_id)
        dest_slip = get_slip(marina_id, body["to_slip_id"])
        if dest_slip.get("status") != "AVAILABLE":
            raise ApiError("ERR_TOW_DEST_UNAVAILABLE", "Destination slip is not AVAILABLE")
        charge, new_remaining = tow_event_charge(
            tier=contract["tier"],
            tows_remaining=int(contract["tows_remaining"]),
        )
        contract["tows_remaining"] = new_remaining
        bump(contract)
        event = {
            "contract_id": contract["id"],
            "occurred_at": iso_format(occurred_at),
            "from_position": body["from_position"],
            "to_slip_id": dest_slip["id"],
            "charge_cents": charge,
        }
        stamp_new(event, with_common=False)
        store.tow_events[event["id"]] = event
    return respond(tow_event_view(event), 201)
