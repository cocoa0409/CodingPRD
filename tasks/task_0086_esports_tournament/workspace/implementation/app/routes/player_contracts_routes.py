"""PlayerContract endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import player_contracts as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:

    @app.post("/player-contracts")
    @require_auth("TeamManager")
    @with_lock
    def create_contract():
        body = get_json_body()
        return ok(svc.create_contract(body), status=201)

    @app.get("/player-contracts/<cid>")
    @require_auth("LeagueAdmin", "TeamManager", "Player")
    @with_lock
    def get_contract(cid: str):
        return ok(svc.get_contract(cid))

    @app.post("/player-contracts/<cid>/identity-verifications")
    @require_auth("LeagueAdmin")
    @with_lock
    def file_identity(cid: str):
        body = get_json_body()
        return ok(svc.file_identity_verification(cid, body), status=201)

    @app.post("/player-contracts/<cid>/initiate-signing")
    @require_auth("TeamManager")
    @with_lock
    def initiate_signing(cid: str):
        return ok(svc.initiate_signing(cid))

    @app.post("/player-contracts/<cid>/sign")
    @require_auth("Player", "TeamManager", "LeagueAdmin")
    @with_lock
    def sign_contract(cid: str):
        return ok(svc.sign_contract(cid))

    @app.post("/player-contracts/<cid>/amendments")
    @require_auth("TeamManager")
    @with_lock
    def amend_contract(cid: str):
        body = get_json_body()
        return ok(svc.file_amendment(cid, body), status=201)

    @app.post("/player-contracts/<cid>/amendments/<aid>/approve")
    @require_auth("LeagueAdmin")
    @with_lock
    def approve_amendment(cid: str, aid: str):
        return ok(svc.approve_amendment(cid, aid))

    @app.post("/player-contracts/<cid>/terminate")
    @require_auth("LeagueAdmin")
    @with_lock
    def terminate_contract(cid: str):
        body = get_json_body()
        return ok(svc.terminate_contract(cid, body))
