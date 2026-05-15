"""TransferWindow + TransferOffer endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import transfers as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:

    @app.post("/transfer-windows")
    @require_auth("LeagueAdmin")
    @with_lock
    def create_window():
        body = get_json_body()
        return ok(svc.create_window(body), status=201)

    @app.get("/transfer-windows/<wid>")
    @require_auth("LeagueAdmin", "TeamManager")
    @with_lock
    def get_window(wid: str):
        return ok(svc.get_window(wid))

    @app.post("/transfer-offers")
    @require_auth("TeamManager")
    @with_lock
    def propose_offer():
        body = get_json_body()
        return ok(svc.propose_offer(body), status=201)

    @app.get("/transfer-offers/<oid>")
    @require_auth("LeagueAdmin", "TeamManager")
    @with_lock
    def get_offer(oid: str):
        return ok(svc.get_offer(oid))

    @app.post("/transfer-offers/<oid>/counter")
    @require_auth("TeamManager")
    @with_lock
    def counter_offer(oid: str):
        body = get_json_body()
        return ok(svc.counter_offer(oid, body))

    @app.post("/transfer-offers/<oid>/accept")
    @require_auth("TeamManager")
    @with_lock
    def accept_offer(oid: str):
        return ok(svc.accept_offer(oid))

    @app.post("/transfer-offers/<oid>/co-accept")
    @require_auth("TeamManager")
    @with_lock
    def co_accept_offer(oid: str):
        return ok(svc.co_accept_offer(oid))

    @app.post("/transfer-offers/<oid>/reject")
    @require_auth("TeamManager", "LeagueAdmin")
    @with_lock
    def reject_offer(oid: str):
        body = get_json_body()
        return ok(svc.reject_offer(oid, body))

    @app.post("/transfer-offers/<oid>/league-approve")
    @require_auth("LeagueAdmin")
    @with_lock
    def league_approve(oid: str):
        body = get_json_body()
        return ok(svc.league_approve(oid, body))
