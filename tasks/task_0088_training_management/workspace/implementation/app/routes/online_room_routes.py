"""OnlineRoom endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..store import common_fields_create, get_store
from ..services.serializers import serialize_online_room
from ._helpers import created, get_json_body, with_lock


def register(app: Flask) -> None:
    @app.post("/training/online-rooms")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_online_room():
        body = get_json_body()
        platform = body.get("platform")
        join_url = body.get("join_url")
        max_participants = body.get("max_participants")

        if not isinstance(platform, str) or not platform:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "platform required.", http_status=422)
        if not isinstance(join_url, str) or not join_url:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "join_url required.", http_status=422)
        try:
            max_participants = int(max_participants)
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "max_participants must be integer.", http_status=422)
        if max_participants < 1:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "max_participants must be >=1.", http_status=422)

        base = common_fields_create()
        row = {
            **base,
            "platform": platform,
            "join_url": join_url,
            "max_participants": max_participants,
            "status": "ACTIVE",
        }
        get_store().online_rooms[base["id"]] = row
        return created(serialize_online_room(row))
