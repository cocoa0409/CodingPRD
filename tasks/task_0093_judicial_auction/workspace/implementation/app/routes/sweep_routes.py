"""Periodic refund-sweep endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services.deposits import sweep_refunds
from ._helpers import ok, with_lock


def register(app: Flask) -> None:
    @app.route("/_sweep/refunds", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _sweep():
        count = sweep_refunds()
        return ok({"refunded_count": count}, 200)
