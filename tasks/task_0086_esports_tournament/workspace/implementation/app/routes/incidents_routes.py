"""MatchIncident endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import incidents as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:

    @app.post("/match-incidents")
    @require_auth("Referee")
    @with_lock
    def file_incident():
        body = get_json_body()
        return ok(svc.file_incident(body), status=201)

    @app.get("/match-incidents/<iid>")
    @require_auth("LeagueAdmin", "TeamManager", "Referee")
    @with_lock
    def get_incident(iid: str):
        return ok(svc.get_incident(iid))

    @app.post("/match-incidents/<iid>/assign")
    @require_auth("LeagueAdmin")
    @with_lock
    def assign_incident(iid: str):
        return ok(svc.assign_incident(iid))

    @app.post("/match-incidents/<iid>/rule")
    @require_auth("LeagueAdmin")
    @with_lock
    def rule_incident(iid: str):
        body = get_json_body()
        return ok(svc.rule_incident(iid, body))

    @app.post("/match-incidents/<iid>/appeal")
    @require_auth("TeamManager")
    @with_lock
    def appeal_incident(iid: str):
        body = get_json_body()
        return ok(svc.appeal_incident(iid, body))

    @app.post("/match-incidents/<iid>/appeal-decide")
    @require_auth("LeagueAdmin")
    @with_lock
    def decide_appeal(iid: str):
        body = get_json_body()
        return ok(svc.decide_appeal(iid, body))

    @app.post("/match-incidents/<iid>/close")
    @require_auth("LeagueAdmin")
    @with_lock
    def close_incident(iid: str):
        return ok(svc.close_incident(iid))
