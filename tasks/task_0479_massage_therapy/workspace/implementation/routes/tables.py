"""Tables/rooms (PRD §3.1)."""
from flask import Blueprint

import db
import helpers as h
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authenticate, require_role

bp = Blueprint("tables", __name__)


@bp.post("/practice/tables")
def create_table():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    body = h.get_body()

    label = h.as_str(h.require(body, "label"), "label")
    room = h.as_str(h.require(body, "room"), "room")
    turnover_buffer_minutes = h.opt(body, "turnover_buffer_minutes", 15)
    turnover_buffer_minutes = h.as_int(turnover_buffer_minutes, "turnover_buffer_minutes", minimum=0, maximum=120)
    supports_prenatal = h.opt(body, "supports_prenatal", False)
    if not isinstance(supports_prenatal, bool):
        raise ApiError(*ERR_INVALID_REQUEST, message="supports_prenatal must be boolean")

    # label unique among non-archived tables
    for t in db.tables.values():
        if not t["archived"] and t["label"] == label:
            raise ApiError(*ERR_INVALID_REQUEST, message="label not unique")

    ent = h.new_entity({
        "label": label,
        "room": room,
        "turnover_buffer_minutes": turnover_buffer_minutes,
        "supports_prenatal": supports_prenatal,
        "archived": False,
    })
    db.tables[ent["id"]] = ent
    return response.success(h.public(ent), status=201)


@bp.get("/practice/tables")
def list_tables():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    limit, offset = h.get_pagination()
    include_archived = h.get_bool_flag("include_archived")
    items = [t for t in db.tables.values() if include_archived or not t["archived"]]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(t) for t in page], limit, offset, total)


@bp.get("/practice/tables/<id>")
def get_table(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    ent = h.resolve(db.tables, id)
    return response.success(h.public(ent))
