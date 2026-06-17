"""InstallCrew endpoints: create, fetch, list, deactivate, list crew slots."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import require_roles
from response import created, ok, ok_list
from services import serialize
from services.helpers import (
    CATEGORIES,
    body,
    is_int,
    pagination,
    paginate,
    require_fields,
    require_int_min,
    sort_by_created,
)

bp = Blueprint("crews", __name__)


@bp.post("/flooring/install-crews")
@require_roles("Scheduler", "Admin")
def create_crew():
    data = body()
    require_fields(data, ["name", "skill_categories", "daily_sqft_capacity"])
    name = data["name"]
    skill_categories = data["skill_categories"]
    if not isinstance(name, str):
        raise err("ERR_INVALID_REQUEST", "name must be a string.")
    if not isinstance(skill_categories, list) or len(skill_categories) < 1:
        raise err("ERR_INVALID_REQUEST", "skill_categories must be a non-empty array.")
    for cat in skill_categories:
        if cat not in CATEGORIES:
            raise err("ERR_INVALID_REQUEST", "skill_categories elements must be valid categories.")

    daily_sqft_capacity = data["daily_sqft_capacity"]
    if not is_int(daily_sqft_capacity) or daily_sqft_capacity <= 0:
        raise err("ERR_INVALID_REQUEST", "daily_sqft_capacity must be an integer > 0.")

    buffer_minutes = data.get("buffer_minutes", 0)
    if not is_int(buffer_minutes) or buffer_minutes < 0:
        raise err("ERR_INVALID_REQUEST", "buffer_minutes must be an integer >= 0.")

    with db.lock:
        record = stamp_create(
            {
                "name": name,
                "skill_categories": list(skill_categories),
                "daily_sqft_capacity": daily_sqft_capacity,
                "buffer_minutes": buffer_minutes,
                "status": "AVAILABLE",
            }
        )
        db.install_crews[record["id"]] = record
    return created(serialize.crew_view(record))


@bp.get("/flooring/install-crews/<cid>")
@require_roles("Admin", "Scheduler")
def get_crew(cid):
    with db.lock:
        c = db.install_crews.get(cid)
        if c is None:
            raise err("ERR_NOT_FOUND", "Crew not found.")
        return ok(serialize.crew_view(c))


@bp.get("/flooring/install-crews")
@require_roles("Admin", "Scheduler")
def list_crews():
    limit, offset = pagination()
    status = request.args.get("status")
    with db.lock:
        items = list(db.install_crews.values())
        if status is not None:
            items = [c for c in items if c["status"] == status]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.crew_view(c) for c in page]
    return ok_list(views, limit, offset, total)


@bp.post("/flooring/install-crews/<cid>/deactivate")
@require_roles("Scheduler", "Admin")
def deactivate_crew(cid):
    with db.lock:
        c = db.install_crews.get(cid)
        if c is None:
            raise err("ERR_NOT_FOUND", "Crew not found.")
        if c["status"] != "AVAILABLE":
            raise err("ERR_INVALID_STATE", "Only an AVAILABLE crew can be deactivated.")
        for s in db.install_slots.values():
            if s["crew_id"] == cid and s["status"] == "SCHEDULED":
                raise err("ERR_INVALID_STATE", "Crew has a SCHEDULED slot and cannot be deactivated.")
        c["status"] = "INACTIVE"
        touch(c)
        return ok(serialize.crew_view(c))


@bp.get("/flooring/install-crews/<cid>/install-slots")
@require_roles("Admin", "Scheduler")
def list_crew_slots(cid):
    limit, offset = pagination()
    with db.lock:
        c = db.install_crews.get(cid)
        if c is None:
            raise err("ERR_NOT_FOUND", "Crew not found.")
        items = [s for s in db.install_slots.values() if s["crew_id"] == cid]
        items = sort_by_created(items)
        page, total = paginate(items, limit, offset)
        views = [serialize.slot_view(s) for s in page]
    return ok_list(views, limit, offset, total)
