"""Deposit endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..services.deposits import (
    pay_deposit,
    post_deposit,
    raise_dispute,
    resolve_dispute,
)
from ..store import get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.route("/deposits", methods=["POST"])
    @require_auth("Bidder", "AuctionAdmin")
    @with_lock
    def _post_deposit():
        body = get_json_body()
        caller_id, caller_role = current_actor()
        deposit = post_deposit(body, caller_role, caller_id)
        return ok(deposit, 201)

    @app.route("/deposits/<string:deposit_id>", methods=["GET"])
    @require_auth("CourtClerk", "AuctionAdmin", "Bidder")
    @with_lock
    def _get_deposit(deposit_id: str):
        store = get_store()
        deposit = store.deposits.get(deposit_id)
        if deposit is None:
            raise ApiError("ERR_NOT_FOUND", f"Deposit {deposit_id} not found.")
        caller_id, caller_role = current_actor()
        # PRD §2.1: Bidder reads of bidder-owned resources require
        # X-User-ID == deposit.bidder_account_id.
        if caller_role == "Bidder" and deposit.get("bidder_account_id") != caller_id:
            raise ApiError("ERR_AUTH_FORBIDDEN", "Bidder may only read own deposit.")
        return ok(deposit)

    @app.route("/deposits/<string:deposit_id>/pay", methods=["POST"])
    @require_auth("Bidder")
    @with_lock
    def _pay_deposit(deposit_id: str):
        store = get_store()
        if deposit_id not in store.deposits:
            raise ApiError("ERR_NOT_FOUND", f"Deposit {deposit_id} not found.")
        body = get_json_body()
        check_version(store.deposits[deposit_id], body)
        caller_id, caller_role = current_actor()
        return ok(pay_deposit(deposit_id, caller_role, caller_id))

    @app.route("/deposits/<string:deposit_id>/raise-dispute", methods=["POST"])
    @require_auth("Bidder")
    @with_lock
    def _raise(deposit_id: str):
        store = get_store()
        if deposit_id not in store.deposits:
            raise ApiError("ERR_NOT_FOUND", f"Deposit {deposit_id} not found.")
        body = get_json_body()
        check_version(store.deposits[deposit_id], body)
        caller_id, caller_role = current_actor()
        return ok(raise_dispute(deposit_id, body, caller_role, caller_id))

    @app.route("/deposits/<string:deposit_id>/resolve-dispute", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _resolve(deposit_id: str):
        store = get_store()
        if deposit_id not in store.deposits:
            raise ApiError("ERR_NOT_FOUND", f"Deposit {deposit_id} not found.")
        body = get_json_body()
        check_version(store.deposits[deposit_id], body)
        return ok(resolve_dispute(deposit_id, body))
