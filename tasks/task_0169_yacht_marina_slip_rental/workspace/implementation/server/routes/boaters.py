"""Boater routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..common import get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import enforce_boater_owns, get_boater, get_marina
from ..response import respond
from ..serializers import boater_view
from ..store import store


bp = Blueprint("boaters", __name__, url_prefix="/marinas")


@bp.post("/<marina_id>/boaters")
@require_auth("DockMaster")
def create_boater(marina_id: str):
    body = get_json_body()
    require_fields(body, "name")
    with store.lock:
        get_marina(marina_id)
        boater = {
            "marina_id": marina_id,
            "name": body["name"],
            "deposit_balance_cents": 0,
            "status": "ACTIVE",
        }
        stamp_new(boater)
        store.boaters[boater["id"]] = boater
    return respond(boater_view(boater), 201)


@bp.get("/<marina_id>/boaters/<boater_id>")
@require_auth("DockMaster", "BillingClerk", "Boater")
def fetch_boater(marina_id: str, boater_id: str):
    with store.lock:
        get_marina(marina_id)
        boater = get_boater(marina_id, boater_id)
        # Boater can only see their own record
        enforce_boater_owns(boater_id)
        return respond(boater_view(boater), 200)
