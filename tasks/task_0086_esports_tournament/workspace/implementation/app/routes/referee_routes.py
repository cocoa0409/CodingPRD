"""Referee endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import referees as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:

    @app.post("/referees")
    @require_auth("LeagueAdmin")
    @with_lock
    def create_referee():
        body = get_json_body()
        return ok(svc.create_referee(body), status=201)

    @app.get("/referees/<rfid>")
    @require_auth("LeagueAdmin", "TeamManager")
    @with_lock
    def get_referee(rfid: str):
        return ok(svc.get_referee(rfid))

    @app.patch("/referees/<rfid>")
    @require_auth("LeagueAdmin")
    @with_lock
    def patch_referee(rfid: str):
        body = get_json_body()
        return ok(svc.patch_referee(rfid, body))
