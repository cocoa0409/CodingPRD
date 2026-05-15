"""Bid placement endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..services.bids import place_bid
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.route("/bids", methods=["POST"])
    @require_auth("Bidder")
    @with_lock
    def _place_bid():
        body = get_json_body()
        caller_id, _ = current_actor()
        bid = place_bid(body, caller_id)
        return ok(bid, 201)
