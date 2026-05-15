"""Tournament endpoints."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services import tournaments as svc
from .. services.serializers import serialize_tournament
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:

    @app.post("/tournaments")
    @require_auth("LeagueAdmin")
    @with_lock
    def create_tournament():
        body = get_json_body()
        t = svc.create_tournament(body)
        return ok(t, status=201)

    @app.get("/tournaments/<tid>")
    @require_auth("LeagueAdmin", "TeamManager", "Referee", "Player")
    @with_lock
    def get_tournament(tid: str):
        return ok(svc.get_tournament(tid))

    @app.get("/tournaments")
    @require_auth("LeagueAdmin", "TeamManager", "Referee", "Player")
    @with_lock
    def list_tournaments():
        status = request.args.get("status")
        region = request.args.get("region")
        limit, offset = parse_limit_offset()
        rows, _total = svc.list_tournaments(status, region, limit, offset)
        return ok_list([serialize_tournament(r) for r in rows], limit, offset)

    @app.post("/tournaments/<tid>/open-registration")
    @require_auth("LeagueAdmin")
    @with_lock
    def open_registration(tid: str):
        return ok(svc.open_registration(tid))

    @app.post("/tournaments/<tid>/lock-rosters")
    @require_auth("LeagueAdmin")
    @with_lock
    def lock_rosters(tid: str):
        return ok(svc.lock_rosters(tid))

    @app.post("/tournaments/<tid>/publish-bracket")
    @require_auth("LeagueAdmin")
    @with_lock
    def publish_bracket(tid: str):
        return ok(svc.publish_bracket(tid))

    @app.post("/tournaments/<tid>/start")
    @require_auth("LeagueAdmin")
    @with_lock
    def start_tournament(tid: str):
        return ok(svc.start_tournament(tid))

    @app.post("/tournaments/<tid>/complete")
    @require_auth("LeagueAdmin")
    @with_lock
    def complete_tournament(tid: str):
        return ok(svc.complete_tournament(tid))

    @app.post("/tournaments/<tid>/finalize-prize-pool")
    @require_auth("LeagueAdmin")
    @with_lock
    def finalize_prize_pool(tid: str):
        rows = svc.finalize_prize_pool(tid)
        from flask import jsonify
        from ..response import success_envelope, paginate
        sliced, pag = paginate(rows, limit=max(1, len(rows)), offset=0)
        body = success_envelope(sliced, response_type="array", pagination=pag)
        return jsonify(body), 200

    @app.post("/tournaments/<tid>/distribute-prizes")
    @require_auth("LeagueAdmin")
    @with_lock
    def distribute_prizes(tid: str):
        return ok(svc.distribute_prizes(tid))

    @app.post("/tournaments/<tid>/cancel")
    @require_auth("LeagueAdmin")
    @with_lock
    def cancel_tournament(tid: str):
        body = get_json_body()
        return ok(svc.cancel_tournament(tid, body.get("reason", "")))

    @app.post("/tournaments/<tid>/crowdfund-contributions")
    @require_auth("LeagueAdmin")
    @with_lock
    def add_crowdfund(tid: str):
        body = get_json_body()
        row = svc.add_crowdfund_contribution(tid, body)
        return ok(row, status=201)
