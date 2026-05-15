"""BidderAccount endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..services.bidder_accounts import clear_account, create_bidder_account, get_account
from ..store import get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.route("/bidder-accounts", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _create_bidder():
        body = get_json_body()
        account = create_bidder_account(body)
        return ok(account, 201)

    @app.route("/bidder-accounts/<string:account_id>", methods=["GET"])
    @require_auth("AuctionAdmin", "CourtClerk", "Bidder")
    @with_lock
    def _get_bidder(account_id: str):
        # Bidder may only read own account
        caller_id, caller_role = current_actor()
        store = get_store()
        if account_id not in store.bidder_accounts:
            raise ApiError("ERR_NOT_FOUND", f"BidderAccount {account_id} not found.")
        if caller_role == "Bidder" and caller_id != account_id:
            raise ApiError("ERR_AUTH_FORBIDDEN", "Bidder may read only own account.")
        return ok(get_account(account_id))

    @app.route("/bidder-accounts/<string:account_id>/clear", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _clear_bidder(account_id: str):
        store = get_store()
        if account_id not in store.bidder_accounts:
            raise ApiError("ERR_NOT_FOUND", f"BidderAccount {account_id} not found.")
        body = get_json_body()
        check_version(store.bidder_accounts[account_id], body)
        return ok(clear_account(account_id, body))
