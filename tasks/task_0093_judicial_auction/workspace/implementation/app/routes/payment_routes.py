"""Payment endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..services.payments import (
    extend_payment,
    forfeit_payment,
    get_payment_for_read,
    settle_payment,
)
from ..store import get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.route("/payments/<string:payment_id>", methods=["GET"])
    @require_auth("CourtClerk", "AuctionAdmin", "Bidder")
    @with_lock
    def _get_payment(payment_id: str):
        caller_id, caller_role = current_actor()
        store = get_store()
        payment = store.payments.get(payment_id)
        if payment is None:
            raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")
        # Bidder may only read own payment
        if caller_role == "Bidder":
            confirmation = store.confirmations.get(payment["confirmation_id"])
            auction = store.auctions.get(confirmation["auction_id"]) if confirmation else None
            winner_id = auction.get("outcome_winner_account_id") if auction else None
            if winner_id != caller_id:
                raise ApiError("ERR_AUTH_FORBIDDEN", "Bidder may read only own payment.")
        return ok(get_payment_for_read(payment_id))

    @app.route("/payments/<string:payment_id>/settle", methods=["POST"])
    @require_auth("Bidder")
    @with_lock
    def _settle(payment_id: str):
        store = get_store()
        if payment_id not in store.payments:
            raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")
        body = get_json_body()
        check_version(store.payments[payment_id], body)
        caller_id, _ = current_actor()
        return ok(settle_payment(payment_id, body, caller_id))

    @app.route("/payments/<string:payment_id>/extend", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _extend(payment_id: str):
        store = get_store()
        if payment_id not in store.payments:
            raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")
        body = get_json_body()
        check_version(store.payments[payment_id], body)
        return ok(extend_payment(payment_id, body))

    @app.route("/payments/<string:payment_id>/forfeit", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _forfeit(payment_id: str):
        store = get_store()
        if payment_id not in store.payments:
            raise ApiError("ERR_NOT_FOUND", f"Payment {payment_id} not found.")
        body = get_json_body()
        check_version(store.payments[payment_id], body)
        return ok(forfeit_payment(payment_id))
