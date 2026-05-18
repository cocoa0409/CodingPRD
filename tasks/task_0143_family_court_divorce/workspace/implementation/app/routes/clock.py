"""Logical-clock endpoints (PRD §2.6)."""
from flask import Blueprint

from app.auth import require_roles
from app.envelope import success
from app.errors import ApiError
from app.serializers import clock_view
from app import store
from app.store import lock, parse_iso
from app.util import get_json_body


bp = Blueprint("clock", __name__)


@bp.get("/_clock")
def read_clock():
    require_roles(
        "PlatformAdmin", "Petitioner", "Respondent", "Judge", "Mediator", "AttorneyOfRecord"
    )
    return success(clock_view(store.now()))


@bp.post("/_clock/advance")
def advance_clock():
    require_roles("PlatformAdmin")
    body = get_json_body()
    target = parse_iso(body.get("to_timestamp"))
    if target is None:
        raise ApiError("ERR_CLOCK_NOT_MONOTONE", 409, "Invalid or missing to_timestamp")
    with lock():
        if target < store.now():
            raise ApiError(
                "ERR_CLOCK_NOT_MONOTONE",
                409,
                "to_timestamp is earlier than current clock",
            )
        store.clock.advance_to(target)
        return success(clock_view(store.now()))
