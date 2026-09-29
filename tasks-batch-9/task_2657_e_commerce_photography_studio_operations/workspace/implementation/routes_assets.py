"""Assets: on-set ingest and CMS delivery."""
from flask import Blueprint

from core import (
    ASSET_STATES, actor_id, authorize, by_created, created, db, fail, get_body,
    new_row, now, ok, ok_list, page_params, paginate, qenum, qstr, touch,
    vobject, vint, vstr,
)
from cascade import cascade_asset_delivered, cascade_asset_ingested
from logic import find
from routes_sessions import photographer_gate
from serialize import asset_out

bp = Blueprint("assets", __name__)


def expand_name(style, angle_code, sequence_number):
    """The naming pattern's expansion is exactly style_number, '_', angle_code,
    '_', then the sequence number zero-padded to three digits."""
    return "%s_%s_%03d" % (style["style_number"], angle_code, sequence_number)


@bp.post("/assets")
def ingest_asset():
    authorize("Photographer")
    body = get_body()
    shot_list_item_id = vstr(body, "shot_list_item_id", minlen=1)
    file_name = vstr(body, "file_name", minlen=1, maxlen=300)
    sequence_number = vint(body, "sequence_number", minimum=1, maximum=999)
    metadata_tags = vobject(body, "metadata_tags")

    item = find(db.items, shot_list_item_id, "ERR_SHOT_ITEM_NOT_FOUND")

    session = db.sessions.get(item.get("session_id")) if item.get("session_id") else None
    if session is None:
        fail("ERR_NOT_BOOKED_ON_SESSION")
    photographer_gate(session)

    if session["session_state"] != "SHOOTING":
        fail("ERR_SESSION_NOT_SHOOTING")
    if item["item_state"] not in ("ASSIGNED", "CAPTURED"):
        fail("ERR_SHOT_ITEM_NOT_ASSIGNABLE")

    station = db.stations.get(session["station_id"])
    calibrated_until = station.get("calibrated_until") if station else None
    if calibrated_until is None or calibrated_until <= now():
        fail("ERR_STATION_CALIBRATION_EXPIRED")

    if session["color_check_state"] == "FAIL":
        fail("ERR_COLOR_CHECK_FAILED")

    if any(a["file_name"] == file_name for a in db.assets.values()):
        fail("ERR_DUPLICATE_CODE", "file_name '%s' already exists." % file_name)

    style = db.styles.get(item["style_id"])
    if style is None:
        fail("ERR_STYLE_NOT_FOUND")
    if file_name != expand_name(style, item["angle_code"], sequence_number):
        fail("ERR_ASSET_NAMING_VIOLATION",
             "file_name must be '%s'."
             % expand_name(style, item["angle_code"], sequence_number))

    profile = db.asset_profiles.get(style["asset_profile_id"])
    required_keys = profile["required_metadata_keys"] if profile else []
    for key in required_keys:
        value = metadata_tags.get(key)
        if not isinstance(value, str) or value == "":
            fail("ERR_ASSET_METADATA_INCOMPLETE",
                 "metadata_tags is missing a non-empty value for '%s'." % key)

    row = new_row({
        "shot_list_item_id": item["id"],
        "session_id": item["session_id"],
        "file_name": file_name,
        "sequence_number": sequence_number,
        "metadata_tags": dict(metadata_tags),
        "captured_by_talent_id": actor_id(),
        "asset_state": "INGESTED",
        "cms_asset_key": None,
        "delivered_at": None,
    })
    db.assets[row["id"]] = row
    cascade_asset_ingested(item)
    return created(asset_out(row))


@bp.post("/assets/<asset_id>/deliver")
def deliver_asset(asset_id):
    authorize("ContentOps")
    body = get_body()
    vstr(body, "cms_collection", required=False, default=None, maxlen=200)

    asset = find(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
    if asset["asset_state"] != "APPROVED":
        fail("ERR_ASSET_NOT_APPROVED")

    item = db.items.get(asset["shot_list_item_id"])
    style = db.styles.get(item["style_id"]) if item else None

    asset["asset_state"] = "DELIVERED"
    asset["delivered_at"] = now()
    if style is not None:
        asset["cms_asset_key"] = "%s/%s/%s" % (
            style["category"], style["style_number"], asset["file_name"])
    touch(asset)

    cascade_asset_delivered(asset, item, style)
    return ok(asset_out(asset))


@bp.get("/assets/<asset_id>")
def read_asset(asset_id):
    authorize("StudioAdmin", "Producer", "Photographer", "Retoucher",
              "QCReviewer", "ContentOps")
    row = find(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
    return ok(asset_out(row))


@bp.get("/assets")
def list_assets():
    authorize("StudioAdmin", "Producer", "Photographer", "Retoucher",
              "QCReviewer", "ContentOps")
    limit, offset = page_params()
    shot_list_item_id = qstr("shot_list_item_id")
    session_id = qstr("session_id")
    captured_by_talent_id = qstr("captured_by_talent_id")
    asset_state = qenum("asset_state", ASSET_STATES)

    rows = list(db.assets.values())
    if shot_list_item_id is not None:
        rows = [r for r in rows if r["shot_list_item_id"] == shot_list_item_id]
    if session_id is not None:
        rows = [r for r in rows if r.get("session_id") == session_id]
    if captured_by_talent_id is not None:
        rows = [r for r in rows if r.get("captured_by_talent_id") == captured_by_talent_id]
    if asset_state is not None:
        rows = [r for r in rows if r["asset_state"] == asset_state]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([asset_out(r) for r in page], limit, offset, total)
