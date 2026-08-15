"""Manufacturing line endpoints (PRD section 3.3)."""
from flask import Blueprint

from auth import QMS_ADMIN, context, require_role
from domain import list_data, serialize
from envelope import pagination_params, success
from errors import ApiError
from store import DB, new_entity
from validate import get_body, get_or_404, opt_int, opt_str, req_str

bp = Blueprint("lines", __name__)


@bp.post("/api/manufacturing-lines")
def create_line():
    uid, role = context()
    require_role(role, QMS_ADMIN)
    data = get_body()
    line_code = req_str(data, "line_code")
    description = opt_str(data, "description", "")
    buffer_hours = opt_int(data, "changeover_buffer_hours", 24)
    if any(l["line_code"] == line_code for l in DB["lines"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "line_code already exists")
    line = new_entity({
        "line_code": line_code,
        "description": description,
        "changeover_buffer_hours": buffer_hours,
    })
    DB["lines"][line["id"]] = line
    return success(serialize(line), 201)


@bp.get("/api/manufacturing-lines")
def list_lines():
    context()
    items = list_data("lines", [])
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return success([serialize(o) for o in page], 200, pagination={
        "limit": limit, "offset": offset, "total_count": len(items),
        "has_more": offset + len(page) < len(items),
    })


@bp.get("/api/manufacturing-lines/<id>")
def get_line(id):
    context()
    return success(serialize(get_or_404("lines", id)), 200)
