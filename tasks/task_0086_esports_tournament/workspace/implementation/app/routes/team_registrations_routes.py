"""TeamRegistration endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import team_registrations as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:

    @app.post("/tournaments/<tid>/team-registrations")
    @require_auth("TeamManager")
    @with_lock
    def create_team_registration(tid: str):
        body = get_json_body()
        return ok(svc.create_team_registration(tid, body), status=201)

    @app.get("/team-registrations/<rid>")
    @require_auth("LeagueAdmin", "TeamManager")
    @with_lock
    def get_team_registration(rid: str):
        return ok(svc.get_team_registration(rid))

    @app.post("/team-registrations/<rid>/pay-entry-fee")
    @require_auth("TeamManager")
    @with_lock
    def pay_entry_fee(rid: str):
        body = get_json_body()
        return ok(svc.pay_entry_fee(rid, body))

    @app.post("/team-registrations/<rid>/withdraw")
    @require_auth("TeamManager")
    @with_lock
    def withdraw(rid: str):
        return ok(svc.withdraw(rid))
