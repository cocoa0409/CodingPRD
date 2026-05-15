"""Lot endpoints — PRD §4 / SCAFFOLD §1.5."""
from __future__ import annotations

from flask import Flask, request

from ..auth import current_actor, require_auth
from ..clock import parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services.lots import (
    add_inspection_window,
    announce_lot,
    create_lot,
    withdraw_lot,
)
from ..store import get_store
from ._helpers import check_version, get_json_body, ok, ok_list, with_lock


def _enrich_lot(lot: dict) -> dict:
    """Decorate the lot response with sibling-Auction references.

    The PRD says registration creates the first sibling Auction; surface
    its id (and the full auctions list) so callers can navigate to it
    without a separate /auctions?lot_id= lookup (which the PRD does not
    define).
    """
    store = get_store()
    siblings = [a for a in store.auctions.values() if a.get("lot_id") == lot["id"]]
    siblings.sort(key=lambda a: int(a.get("round_number") or 0))
    enriched = dict(lot)
    enriched["auctions"] = [{"id": a["id"], "round_number": a.get("round_number")} for a in siblings]
    if siblings:
        # current auction = the one matching lot.round_number (or last)
        current_round = int(lot.get("round_number") or 1)
        current = next(
            (a for a in siblings if int(a.get("round_number") or 0) == current_round),
            siblings[-1],
        )
        enriched["current_auction_id"] = current["id"]
        # first-round auction id (round_number 1)
        first = next(
            (a for a in siblings if int(a.get("round_number") or 0) == 1),
            siblings[0],
        )
        enriched["first_auction_id"] = first["id"]
        enriched["auction_id"] = enriched["current_auction_id"]
    else:
        enriched["current_auction_id"] = None
        enriched["first_auction_id"] = None
        enriched["auction_id"] = None
    return enriched


def register(app: Flask) -> None:
    @app.route("/lots", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _create_lot():
        body = get_json_body()
        lot = create_lot(body)
        return ok(_enrich_lot(lot), 201)

    @app.route("/lots", methods=["GET"])
    @require_auth("CourtClerk", "AuctionAdmin", "Bidder", "Observer")
    @with_lock
    def _list_lots():
        store = get_store()
        items = list(store.lots.values())
        status_filter = request.args.get("status")
        if status_filter:
            items = [l for l in items if l.get("status") == status_filter]
        items.sort(key=lambda r: r.get("created_at") or "")
        limit, offset = parse_limit_offset()
        enriched = [_enrich_lot(l) for l in items]
        return ok_list(enriched, limit, offset)

    @app.route("/lots/<string:lot_id>", methods=["GET"])
    @require_auth("CourtClerk", "AuctionAdmin", "Bidder", "Observer")
    @with_lock
    def _get_lot(lot_id: str):
        store = get_store()
        lot = store.lots.get(lot_id)
        if lot is None:
            raise ApiError("ERR_NOT_FOUND", f"Lot {lot_id} not found.")
        return ok(_enrich_lot(lot))

    @app.route("/lots/<string:lot_id>/announce", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _announce(lot_id: str):
        store = get_store()
        lot = store.lots.get(lot_id)
        if lot is None:
            raise ApiError("ERR_NOT_FOUND", f"Lot {lot_id} not found.")
        body = get_json_body()
        check_version(lot, body)
        result = announce_lot(lot_id)
        return ok(_enrich_lot(result))

    @app.route("/lots/<string:lot_id>/inspection-windows", methods=["POST"])
    @require_auth("CourtClerk", "AuctionAdmin")
    @with_lock
    def _add_insp_window(lot_id: str):
        store = get_store()
        lot = store.lots.get(lot_id)
        if lot is None:
            raise ApiError("ERR_NOT_FOUND", f"Lot {lot_id} not found.")
        body = get_json_body()
        result = add_inspection_window(lot_id, body)
        return ok(_enrich_lot(result), 201)

    @app.route("/lots/<string:lot_id>/withdraw", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _withdraw(lot_id: str):
        store = get_store()
        lot = store.lots.get(lot_id)
        if lot is None:
            raise ApiError("ERR_NOT_FOUND", f"Lot {lot_id} not found.")
        body = get_json_body()
        check_version(lot, body)
        result = withdraw_lot(lot_id, reason=body.get("reason"))
        return ok(_enrich_lot(result))
