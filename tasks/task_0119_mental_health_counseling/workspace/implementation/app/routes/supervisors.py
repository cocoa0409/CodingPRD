"""Supervisor routes."""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import require_roles
from ..clock import now
from ..errors import err_not_found
from ..helpers import (
    assert_bool,
    assert_string,
    new_uuid,
    require_json_object,
)
from ..responses import created, ok
from ..services.serialize import serialize_supervisor
from ..store import store

bp = Blueprint("supervisors", __name__, url_prefix="/practice/supervisors")


@bp.post("")
@require_roles("PracticeAdmin")
def create_supervisor(**_):
    body = require_json_object()
    full_name = assert_string(body.get("full_name"), "full_name")
    home_state_code = assert_string(body.get("home_state_code"), "home_state_code", pattern=r"^[A-Z]{2}$")
    active = assert_bool(body.get("active"), "active", required=False)
    if active is None:
        active = True
    s = store()
    with s.lock:
        sid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": sid,
            "full_name": full_name,
            "home_state_code": home_state_code,
            "active": bool(active),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.supervisors[sid] = row
        return created(serialize_supervisor(row))


@bp.get("/<sid>")
@require_roles("PracticeAdmin", "Supervisor")
def get_supervisor(sid: str, **_):
    s = store()
    row = s.supervisors.get(sid)
    if row is None:
        raise err_not_found("Supervisor not found")
    return ok(serialize_supervisor(row))
