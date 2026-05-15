"""Classroom endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..store import common_fields_create, get_store
from ..services.serializers import serialize_classroom
from ._helpers import created, get_json_body, with_lock


def register(app: Flask) -> None:
    @app.post("/training/classrooms")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_classroom():
        body = get_json_body()
        name = body.get("name")
        cap = body.get("capacity")
        sbm = body.get("setup_buffer_minutes", 30)

        if not isinstance(name, str) or not name:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "name required.", http_status=422)
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "capacity must be integer.", http_status=422)
        if cap < 1:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "capacity must be >=1.", http_status=422)
        try:
            sbm = int(sbm)
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "setup_buffer_minutes must be integer.", http_status=422)
        if not (0 <= sbm <= 240):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "setup_buffer_minutes out of range.", http_status=422)

        store = get_store()
        if name in store.classroom_name_uniq:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "classroom name not unique.", http_status=422)

        base = common_fields_create()
        row = {
            **base,
            "name": name,
            "capacity": cap,
            "status": "ACTIVE",
            "setup_buffer_minutes": sbm,
        }
        store.classrooms[base["id"]] = row
        store.classroom_name_uniq[name] = base["id"]
        return created(serialize_classroom(row))
