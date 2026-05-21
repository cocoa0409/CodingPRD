"""FuelCard routes — issuance under a lease + read (§3.3)."""
from __future__ import annotations

import re

from flask import Blueprint, g

from ..auth import require_auth
from ..common import as_int, bump, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import fuel_card_view
from ..store import store


bp = Blueprint("fuel_cards", __name__)


_PAN4_RE = re.compile(r"^\d{4}$")


@bp.post("/lease-agreements/<lease_id>/fuel-cards")
@require_auth("FleetManager")
def issue_card(lease_id: str):
    body = get_json_body()
    require_fields(body, "card_pan_last4", "monthly_limit_cents")
    pan4 = body["card_pan_last4"]
    if not isinstance(pan4, str) or not _PAN4_RE.match(pan4):
        raise ApiError("ERR_VALIDATION", "card_pan_last4 must be exactly 4 digits")
    limit = as_int(body["monthly_limit_cents"], "monthly_limit_cents", min_value=50_000, max_value=1_000_000)

    with store.lock:
        if lease_id not in store.lease_agreements:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")

        card = {
            "lease_agreement_id": lease_id,
            "card_pan_last4": pan4,
            "monthly_limit_cents": limit,
            "card_status": "ACTIVE",
            "current_period_spend_cents": 0,
        }
        stamp_new(card)
        store.fuel_cards[card["id"]] = card
    return respond(fuel_card_view(card), 201)


@bp.get("/fuel-cards/<card_id>")
@require_auth("FleetManager", "TaxAdmin", "VendorOps", "Lessee")
def get_card(card_id: str):
    with store.lock:
        card = store.fuel_cards.get(card_id)
        if card is None:
            raise ApiError("ERR_NOT_FOUND", "FuelCard not found")
        if g.user_role == "Lessee":
            lease = store.lease_agreements.get(card["lease_agreement_id"])
            if lease is None or lease.get("lessee_id") != g.user_id:
                raise ApiError("ERR_FORBIDDEN", "Lessee may only read their own fuel cards")
        return respond(fuel_card_view(card), 200)
