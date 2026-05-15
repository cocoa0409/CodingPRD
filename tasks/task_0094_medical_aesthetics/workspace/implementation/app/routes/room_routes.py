"""Room routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_bool, parse_optional_str
from ..response import paginate
from ..services.validation import require_keys, require_str
from ..store import LOCK, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok


_ROOM_KINDS = {"SURGICAL_OR", "PROCEDURE", "TREATMENT"}


def register(app: Flask) -> None:
    @app.route("/aesthetics/rooms", methods=["POST"])
    @require_auth("MedicalDirector")
    def create_room():
        body = get_json_body()
        require_keys(body, ["code", "room_kind"])
        code = require_str(body["code"], "code")
        for r in get_store().rooms.values():
            if r["code"] == code:
                raise ApiError("ERR_INVALID_INPUT", f"code already exists: {code}")
        kind = body["room_kind"]
        if kind not in _ROOM_KINDS:
            raise ApiError("ERR_INVALID_INPUT", "invalid room_kind")
        is_active = body.get("is_active", True)
        if not isinstance(is_active, bool):
            raise ApiError("ERR_INVALID_INPUT", "is_active must be boolean")
        with LOCK:
            room = common_fields_create()
            room.update({
                "code": code,
                "room_kind": kind,
                "is_active": is_active,
            })
            get_store().rooms[room["id"]] = room
        return created(room)

    @app.route("/aesthetics/rooms", methods=["GET"])
    @require_auth("MedicalDirector", "Consultant", "AttendingPhysician", "Nurse")
    def list_rooms():
        limit, offset = parse_limit_offset()
        kind = parse_optional_str("room_kind")
        active = parse_optional_bool("is_active")
        items = list(get_store().rooms.values())
        if kind:
            items = [r for r in items if r["room_kind"] == kind]
        if active is not None:
            items = [r for r in items if r["is_active"] is active]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
