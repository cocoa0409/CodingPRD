"""Lessee routes: register / read / suspend / reinstate (§3.1, §3.8)."""
from __future__ import annotations

import re

from flask import Blueprint, g

from ..auth import require_auth
from ..common import as_string, bump, get_json_body, require_fields, stamp_new
from ..constants import (
    DEFAULT_THRESHOLD_CENTS,
    SUSPEND_THRESHOLD_CENTS,
    VALID_BASE_JURISDICTIONS,
)
from ..errors import ApiError
from ..response import respond
from ..serializers import lessee_view
from ..store import store


bp = Blueprint("lessees", __name__, url_prefix="/lessees")


_DOT_RE = re.compile(r"^\d{6,8}$")


@bp.post("")
@require_auth("FleetManager")
def create_lessee():
    body = get_json_body()
    require_fields(body, "legal_name", "dot_number", "base_jurisdiction")
    legal_name = as_string(body["legal_name"], "legal_name", min_len=1, max_len=120, trim=True)
    dot_number = body["dot_number"]
    if not isinstance(dot_number, str) or not _DOT_RE.match(dot_number):
        raise ApiError("ERR_VALIDATION", "dot_number must be 6..8 digits")
    base_j = body["base_jurisdiction"]
    if base_j not in VALID_BASE_JURISDICTIONS:
        raise ApiError("ERR_VALIDATION", f"base_jurisdiction must be one of {sorted(VALID_BASE_JURISDICTIONS)}")

    with store.lock:
        for existing in store.lessees.values():
            if existing.get("dot_number") == dot_number:
                raise ApiError("ERR_VALIDATION", "dot_number already exists")
        lessee = {
            "legal_name": legal_name,
            "dot_number": dot_number,
            "base_jurisdiction": base_j,
            "account_status": "ACTIVE",
            "outstanding_balance_cents": 0,
        }
        stamp_new(lessee)
        store.lessees[lessee["id"]] = lessee
    return respond(lessee_view(lessee), 201)


@bp.get("/<lessee_id>")
@require_auth("FleetManager", "TaxAdmin", "ClaimAdjuster", "VendorOps", "Lessee")
def get_lessee(lessee_id: str):
    with store.lock:
        lessee = store.lessees.get(lessee_id)
        if lessee is None:
            raise ApiError("ERR_NOT_FOUND", "Lessee not found")
        if g.user_role == "Lessee" and g.user_id != lessee_id:
            raise ApiError("ERR_FORBIDDEN", "Lessee may only read their own record")
        return respond(lessee_view(lessee), 200)


@bp.post("/<lessee_id>/suspend")
@require_auth("FleetManager")
def suspend_lessee(lessee_id: str):
    with store.lock:
        lessee = store.lessees.get(lessee_id)
        if lessee is None:
            raise ApiError("ERR_NOT_FOUND", "Lessee not found")
        if lessee["account_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Lessee is not ACTIVE")
        if int(lessee["outstanding_balance_cents"]) < SUSPEND_THRESHOLD_CENTS:
            raise ApiError("ERR_INVALID_STATE", "Balance below suspend threshold")
        lessee["account_status"] = "SUSPENDED"
        bump(lessee)

        # Cascade: every ACTIVE lease for this lessee at or above default threshold becomes DEFAULTED.
        if int(lessee["outstanding_balance_cents"]) >= DEFAULT_THRESHOLD_CENTS:
            for la in list(store.lease_agreements.values()):
                if la.get("lessee_id") != lessee_id:
                    continue
                if la.get("lease_state") != "ACTIVE":
                    continue
                la["lease_state"] = "DEFAULTED"
                bump(la)
                # Vehicle -> GROUNDED
                v = store.vehicles.get(la["vehicle_id"])
                if v is not None:
                    v["vehicle_status"] = "GROUNDED"
                    bump(v)
                # FuelCards under this lease -> BLOCKED
                for card in store.fuel_cards.values():
                    if card.get("lease_agreement_id") != la["id"]:
                        continue
                    if card.get("card_status") == "CLOSED":
                        continue
                    card["card_status"] = "BLOCKED"
                    bump(card)
    return respond(lessee_view(lessee), 200)


@bp.post("/<lessee_id>/reinstate")
@require_auth("FleetManager")
def reinstate_lessee(lessee_id: str):
    with store.lock:
        lessee = store.lessees.get(lessee_id)
        if lessee is None:
            raise ApiError("ERR_NOT_FOUND", "Lessee not found")
        if lessee["account_status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", "Lessee is not SUSPENDED")
        if int(lessee["outstanding_balance_cents"]) >= SUSPEND_THRESHOLD_CENTS:
            raise ApiError("ERR_INVALID_STATE", "Balance not below suspend threshold")
        lessee["account_status"] = "ACTIVE"
        bump(lessee)
    return respond(lessee_view(lessee), 200)
