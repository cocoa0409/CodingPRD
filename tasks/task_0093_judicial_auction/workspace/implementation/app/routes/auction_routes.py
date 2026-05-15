"""Auction endpoints."""
from __future__ import annotations

from flask import Flask, request

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services.auctions import cancel_auction, open_auction, system_rollback
from ..services.bids import list_bids_for_auction
from ..services.masking import project_auction, project_bid
from ..store import get_store
from ._helpers import check_version, get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.route("/auctions/<string:auction_id>", methods=["GET"])
    @require_auth("CourtClerk", "AuctionAdmin", "Bidder", "Observer")
    @with_lock
    def _get_auction(auction_id: str):
        store = get_store()
        auction = store.auctions.get(auction_id)
        if auction is None:
            raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
        caller_id, caller_role = current_actor()
        projected = project_auction(auction, caller_role)
        return ok(projected)

    @app.route("/auctions/<string:auction_id>/open", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _open(auction_id: str):
        store = get_store()
        auction = store.auctions.get(auction_id)
        if auction is None:
            raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
        body = get_json_body()
        check_version(auction, body)
        return ok(open_auction(auction_id))

    @app.route("/auctions/<string:auction_id>/cancel", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _cancel(auction_id: str):
        store = get_store()
        auction = store.auctions.get(auction_id)
        if auction is None:
            raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
        body = get_json_body()
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ApiError("ERR_VALIDATION", "reason must be a non-empty string.")
        check_version(auction, body)
        return ok(cancel_auction(auction_id, reason))

    @app.route("/auctions/<string:auction_id>/bids", methods=["GET"])
    @require_auth("CourtClerk", "AuctionAdmin", "Bidder", "Observer")
    @with_lock
    def _list_bids(auction_id: str):
        store = get_store()
        if auction_id not in store.auctions:
            raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
        caller_id, caller_role = current_actor()
        validity = request.args.get("validity")
        bids = list_bids_for_auction(auction_id, validity, caller_role, caller_id)
        # Project each bid for masking
        bids_projected = [project_bid(b, caller_role, caller_id) for b in bids]
        limit, offset = parse_limit_offset()
        return ok_list(bids_projected, limit, offset)

    @app.route("/auctions/<string:auction_id>/system-rollback", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _system_rollback(auction_id: str):
        store = get_store()
        auction = store.auctions.get(auction_id)
        if auction is None:
            raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
        body = get_json_body()
        check_version(auction, body)
        last_n = body.get("last_n_bids")
        fault_reason = body.get("fault_reason")
        if not isinstance(last_n, int) or isinstance(last_n, bool):
            raise ApiError("ERR_VALIDATION", "last_n_bids must be an integer.")
        if not isinstance(fault_reason, str):
            raise ApiError("ERR_VALIDATION", "fault_reason must be a string.")
        return ok(system_rollback(auction_id, last_n, fault_reason))
