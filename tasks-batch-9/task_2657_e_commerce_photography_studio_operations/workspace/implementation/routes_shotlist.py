"""Shot-list items: definition against a style, assignment to a call sheet and
the producer's waiver."""
from flask import Blueprint

from core import (
    ANGLE_CODES, ASSET_KINDS, ITEM_STATES, authorize, by_created, created, db,
    fail, get_body, new_row, ok, ok_list, page_params, paginate, qbool, qenum,
    qstr, touch, vbool, venum, vint, vstr,
)
from logic import find
from serialize import item_out

bp = Blueprint("shotlist", __name__)

# Which station types may carry which asset kind (PRD 3.6).
STATION_ADMITS = {
    "ON_MODEL": ("MODEL",),
    "STILL_ANGLE": ("MANNEQUIN", "STILL_LIFE"),
    "DETAIL": ("MANNEQUIN", "STILL_LIFE"),
    "VIDEO": ("MODEL", "STILL_LIFE"),
}


@bp.post("/shot-list-items")
def create_item():
    authorize("Producer")
    body = get_body()
    style_id = vstr(body, "style_id", minlen=1)
    asset_kind = venum(body, "asset_kind", ASSET_KINDS)
    angle_code = venum(body, "angle_code", ANGLE_CODES)
    estimated_minutes = vint(body, "estimated_minutes", minimum=1, maximum=480)
    expected_style_version = vint(body, "expected_style_version", minimum=0)
    required = vbool(body, "required", required=False, default=True)

    style = find(db.styles, style_id, "ERR_STYLE_NOT_FOUND")
    if expected_style_version != style["version"]:
        fail("ERR_STALE_STYLE_VERSION")

    for other in db.items.values():
        if (other["style_id"] == style["id"]
                and other["asset_kind"] == asset_kind
                and other["angle_code"] == angle_code
                and other["item_state"] != "WAIVED"):
            fail("ERR_DUPLICATE_SHOT_ITEM")

    row = new_row({
        "style_id": style["id"],
        "session_id": None,
        "asset_kind": asset_kind,
        "angle_code": angle_code,
        "required": required,
        "estimated_minutes": estimated_minutes,
        "item_state": "PLANNED",
        "allocated_cost_cents": 0,
    })
    db.items[row["id"]] = row
    touch(style)
    return created(item_out(row))


@bp.post("/shot-list-items/<item_id>/assign")
def assign_item(item_id):
    authorize("Producer")
    body = get_body()
    session_id = vstr(body, "session_id", minlen=1)

    item = find(db.items, item_id, "ERR_SHOT_ITEM_NOT_FOUND")
    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")

    if session["session_state"] != "BOOKED":
        fail("ERR_SESSION_NOT_BOOKED")
    if item["item_state"] != "PLANNED":
        fail("ERR_SHOT_ITEM_NOT_ASSIGNABLE")

    station = db.stations.get(session["station_id"])
    admitted = STATION_ADMITS.get(item["asset_kind"], ())
    if station is None or station["station_type"] not in admitted:
        fail("ERR_STATION_TYPE_MISMATCH")

    item["item_state"] = "ASSIGNED"
    item["session_id"] = session["id"]
    touch(item)

    style = db.styles.get(item["style_id"])
    if item["required"] and style is not None and style["content_state"] == "SAMPLE_READY":
        style["content_state"] = "SCHEDULED"
        touch(style)
    return ok(item_out(item))


@bp.post("/shot-list-items/<item_id>/waive")
def waive_item(item_id):
    authorize("Producer")
    body = get_body()
    vstr(body, "reason", required=False, default=None, maxlen=2000)

    item = find(db.items, item_id, "ERR_SHOT_ITEM_NOT_FOUND")
    if item["item_state"] not in ("PLANNED", "BLOCKED"):
        fail("ERR_SHOT_ITEM_NOT_ASSIGNABLE")

    was_required = item["required"]
    item["item_state"] = "WAIVED"
    touch(item)

    if was_required:
        style = db.styles.get(item["style_id"])
        if style is not None:
            touch(style)
    return ok(item_out(item))


@bp.get("/shot-list-items/<item_id>")
def read_item(item_id):
    authorize("StudioAdmin", "Producer", "Photographer")
    row = find(db.items, item_id, "ERR_SHOT_ITEM_NOT_FOUND")
    return ok(item_out(row))


@bp.get("/shot-list-items")
def list_items():
    authorize("StudioAdmin", "Producer", "Photographer")
    limit, offset = page_params()
    style_id = qstr("style_id")
    session_id = qstr("session_id")
    item_state = qenum("item_state", ITEM_STATES)
    asset_kind = qenum("asset_kind", ASSET_KINDS)
    required = qbool("required")

    rows = list(db.items.values())
    if style_id is not None:
        rows = [r for r in rows if r["style_id"] == style_id]
    if session_id is not None:
        rows = [r for r in rows if r.get("session_id") == session_id]
    if item_state is not None:
        rows = [r for r in rows if r["item_state"] == item_state]
    if asset_kind is not None:
        rows = [r for r in rows if r["asset_kind"] == asset_kind]
    if required is not None:
        rows = [r for r in rows if r["required"] == required]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([item_out(r) for r in page], limit, offset, total)
