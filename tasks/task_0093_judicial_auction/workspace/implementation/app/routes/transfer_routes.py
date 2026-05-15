"""TransferOrder endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..services.transfers import (
    block_transfer,
    complete_handover,
    confirm_completion,
    create_transfer_order,
    notify_agency,
)
from ..store import get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.route("/transfer-orders", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _create_transfer():
        body = get_json_body()
        return ok(create_transfer_order(body), 201)

    @app.route("/transfer-orders/<string:transfer_order_id>/notify-agency", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _notify(transfer_order_id: str):
        store = get_store()
        if transfer_order_id not in store.transfer_orders:
            raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_order_id} not found.")
        body = get_json_body()
        check_version(store.transfer_orders[transfer_order_id], body)
        return ok(notify_agency(transfer_order_id))

    @app.route("/transfer-orders/<string:transfer_order_id>/complete-handover", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _complete_handover(transfer_order_id: str):
        store = get_store()
        if transfer_order_id not in store.transfer_orders:
            raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_order_id} not found.")
        body = get_json_body()
        check_version(store.transfer_orders[transfer_order_id], body)
        return ok(complete_handover(transfer_order_id, body))

    @app.route("/transfer-orders/<string:transfer_order_id>/confirm-completion", methods=["POST"])
    @require_auth("CourtClerk")
    @with_lock
    def _confirm_completion(transfer_order_id: str):
        store = get_store()
        if transfer_order_id not in store.transfer_orders:
            raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_order_id} not found.")
        body = get_json_body()
        check_version(store.transfer_orders[transfer_order_id], body)
        return ok(confirm_completion(transfer_order_id))

    @app.route("/transfer-orders/<string:transfer_order_id>/block", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _block(transfer_order_id: str):
        store = get_store()
        if transfer_order_id not in store.transfer_orders:
            raise ApiError("ERR_NOT_FOUND", f"TransferOrder {transfer_order_id} not found.")
        body = get_json_body()
        check_version(store.transfer_orders[transfer_order_id], body)
        return ok(block_transfer(transfer_order_id, body))
