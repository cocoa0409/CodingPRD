"""Match endpoints."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_int, parse_limit_offset
from ..services import matches as svc
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:

    @app.get("/matches/<mid>")
    @require_auth("LeagueAdmin", "TeamManager", "Referee", "Player")
    @with_lock
    def get_match(mid: str):
        return ok(svc.get_match(mid))

    @app.get("/tournaments/<tid>/matches")
    @require_auth("LeagueAdmin", "TeamManager", "Referee", "Player")
    @with_lock
    def list_matches(tid: str):
        round_num = parse_int(request.args.get("round"))
        status = request.args.get("status")
        limit, offset = parse_limit_offset()
        rows = svc.list_matches(tid, round_num, status)
        return ok_list(rows, limit, offset)

    @app.patch("/matches/<mid>")
    @require_auth("LeagueAdmin")
    @with_lock
    def patch_match(mid: str):
        body = get_json_body()
        return ok(svc.patch_match(mid, body))

    @app.post("/matches/<mid>/assign-referee")
    @require_auth("LeagueAdmin")
    @with_lock
    def assign_referee(mid: str):
        body = get_json_body()
        return ok(svc.assign_referee(mid, body))

    @app.post("/matches/<mid>/start-draft")
    @require_auth("Referee")
    @with_lock
    def start_draft(mid: str):
        return ok(svc.start_draft(mid))

    @app.post("/matches/<mid>/draft-events")
    @require_auth("Referee")
    @with_lock
    def append_draft_event(mid: str):
        body = get_json_body()
        return ok(svc.append_draft_event(mid, body), status=201)

    @app.get("/matches/<mid>/draft-events")
    @require_auth("LeagueAdmin", "TeamManager", "Referee", "Player")
    @with_lock
    def list_draft_events(mid: str):
        limit, offset = parse_limit_offset()
        rows = svc.list_draft_events(mid)
        return ok_list(rows, limit, offset)

    @app.post("/matches/<mid>/complete-draft")
    @require_auth("Referee")
    @with_lock
    def complete_draft(mid: str):
        return ok(svc.complete_draft(mid))

    @app.post("/matches/<mid>/report-result")
    @require_auth("Referee")
    @with_lock
    def report_result(mid: str):
        body = get_json_body()
        return ok(svc.report_result(mid, body))

    @app.post("/matches/<mid>/forfeit")
    @require_auth("Referee", "LeagueAdmin")
    @with_lock
    def forfeit_match(mid: str):
        body = get_json_body()
        return ok(svc.forfeit_match(mid, body))
