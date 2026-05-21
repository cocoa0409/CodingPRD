"""FuelCardTransaction routes — post + reverse (§3.3)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..calculations import (
    card_spend_in_window_of,
    is_txn_ifta_eligible_for,
    quarter_window,
    recompute_card_spend,
)
from ..clock import iso_format, now, parse_iso
from ..common import as_int, as_number, bump, get_json_body, require_fields, stamp_new
from ..constants import VALID_BASE_JURISDICTIONS
from ..errors import ApiError
from ..response import respond
from ..serializers import fuel_card_txn_view
from ..store import store


bp = Blueprint("fuel_card_transactions", __name__, url_prefix="/fuel-card-transactions")


@bp.post("")
@require_auth("FleetManager", "VendorOps")
def post_txn():
    body = get_json_body()
    require_fields(body, "fuel_card_id", "posted_at", "jurisdiction", "gallons", "amount_cents")
    card_id = body["fuel_card_id"]
    try:
        posted_at = parse_iso(body["posted_at"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    jurisdiction = body["jurisdiction"]
    if jurisdiction not in VALID_BASE_JURISDICTIONS:
        raise ApiError("ERR_VALIDATION", f"jurisdiction must be one of {sorted(VALID_BASE_JURISDICTIONS)}")
    gallons = as_number(body["gallons"], "gallons", gt=0, le=200)
    amount = as_int(body["amount_cents"], "amount_cents", min_value=1, max_value=100_000)

    with store.lock:
        card = store.fuel_cards.get(card_id)
        if card is None:
            raise ApiError("ERR_NOT_FOUND", "FuelCard not found")
        lease = store.lease_agreements.get(card["lease_agreement_id"])
        if lease is None:
            raise ApiError("ERR_NOT_FOUND", "LeaseAgreement not found")

        # Priority 6 (state) — implicitly via ERR_CARD_INACTIVE business_referential check
        if card.get("card_status") != "ACTIVE" or lease.get("lease_state") != "ACTIVE":
            raise ApiError("ERR_CARD_INACTIVE", "Card or lease is not ACTIVE")

        # Priority 11: temporal — closed-quarter window for this lessee
        lessee_id = lease["lessee_id"]
        for q in store.ifta_quarters.values():
            if q.get("lessee_id") != lessee_id:
                continue
            if q.get("filing_status") != "CLOSED":
                continue
            w_start, w_end = quarter_window(int(q["year"]), int(q["quarter"]))
            if w_start <= posted_at <= w_end:
                raise ApiError("ERR_QUARTER_CLOSED", "Posted at falls inside a closed IFTA quarter")

        # Priority 13: fiscal — monthly cap
        existing_spend = card_spend_in_window_of(card, posted_at)
        if existing_spend + amount > int(card["monthly_limit_cents"]):
            raise ApiError("ERR_CARD_LIMIT_EXCEEDED", "Adding txn would exceed monthly cap")

        txn = {
            "fuel_card_id": card_id,
            "posted_at": iso_format(posted_at),
            "jurisdiction": jurisdiction,
            "gallons": gallons,
            "amount_cents": amount,
            "txn_status": "POSTED",
            "ifta_eligible": is_txn_ifta_eligible_for(card),
        }
        stamp_new(txn, with_common=False)
        store.fuel_card_transactions[txn["id"]] = txn

        # Refresh card.current_period_spend_cents using "now" calendar month, per §3.3
        recompute_card_spend(card, now())
        bump(card)

    return respond(fuel_card_txn_view(txn), 201)


@bp.post("/<txn_id>/reverse")
@require_auth("FleetManager")
def reverse_txn(txn_id: str):
    with store.lock:
        txn = store.fuel_card_transactions.get(txn_id)
        if txn is None:
            raise ApiError("ERR_NOT_FOUND", "FuelCardTransaction not found")
        if txn.get("txn_status") != "POSTED":
            raise ApiError("ERR_INVALID_STATE", "Transaction is not POSTED")

        txn["txn_status"] = "REVERSED"

        card = store.fuel_cards.get(txn["fuel_card_id"])
        if card is not None:
            recompute_card_spend(card, now())
            bump(card)
    return respond(fuel_card_txn_view(txn), 200)
