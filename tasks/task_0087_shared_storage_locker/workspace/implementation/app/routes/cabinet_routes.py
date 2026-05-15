"""Cabinet routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services import cabinets as svc
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.post("/cabinets")
    @require_auth("Operator")
    @with_lock
    def create_cabinet():
        return ok(svc.create_cabinet(get_json_body()), status=201)

    @app.get("/cabinets/<cabinet_id>")
    @require_auth("Operator", "Renter")
    @with_lock
    def get_cabinet(cabinet_id: str):
        return ok(svc.get_cabinet(cabinet_id))

    @app.get("/cabinets")
    @require_auth("Operator", "Renter")
    @with_lock
    def list_cabinets():
        online_status = request.args.get("online_status")
        capacity_alert_level = request.args.get("capacity_alert_level")
        limit, offset = parse_limit_offset()
        items = svc.list_cabinets(online_status, capacity_alert_level)
        return ok_list(items, limit, offset)

    @app.patch("/cabinets/<cabinet_id>")
    @require_auth("Operator")
    @with_lock
    def update_cabinet(cabinet_id: str):
        return ok(svc.update_cabinet(cabinet_id, get_json_body()))

    @app.post("/cabinets/<cabinet_id>/heartbeat")
    @require_auth("Operator")
    @with_lock
    def heartbeat_cabinet(cabinet_id: str):
        return ok(svc.heartbeat_cabinet(cabinet_id))

    @app.get("/cabinets/<cabinet_id>/redistribution-suggestion")
    @require_auth("Operator")
    @with_lock
    def redistribution_suggestion(cabinet_id: str):
        return ok(svc.redistribution_suggestion(cabinet_id))
