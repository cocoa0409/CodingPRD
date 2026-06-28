"""Zone endpoints (PRD 3.1).

Creating the FIRST zone on a project advances design_status DRAFT->ZONED and
increments the project version. A zone's transformer_id must reference a
transformer in the same project (else ERR_CROSS_PROJECT_REFERENCE).
"""

from flask import Blueprint

from common import (
    get_json_body,
    paginate,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_project, get_transformer, get_zone
from middleware import get_auth, require_role
from response import success
from services.serialize import ser_add_on, ser_fixture, ser_zone

bp = Blueprint("zones", __name__)

READ_ROLES = {"LightingDesigner", "InstallTech", "OperationsAdmin"}


@bp.post("/projects/<pid>/zones")
def create_zone(pid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    p = get_project(pid)
    body = get_json_body()
    require_fields(body, ["transformer_id", "label"])
    transformer_id = require_string(body, "transformer_id")
    label = require_string(body, "label")
    # Existence of the referenced transformer (priority 3).
    t = get_transformer(transformer_id)
    # Cross-project referential integrity (priority 5).
    if t["project_id"] != pid:
        raise err(
            "ERR_CROSS_PROJECT_REFERENCE",
            "Transformer belongs to a different project.",
        )
    # Design must not be locked (no new zones once locked, until INSTALLED).
    if p["design_status"] == "DESIGN_LOCKED" and p["commercial_status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Design is locked; no new zones.")

    record = stamp_new(
        {
            "project_id": pid,
            "transformer_id": transformer_id,
            "label": label,
            "zone_load_va": 0,
        }
    )
    db.zones[record["id"]] = record

    # First zone on the project advances design_status DRAFT->ZONED.
    if p["design_status"] == "DRAFT":
        p["design_status"] = "ZONED"
        touch(p)

    return success(ser_zone(record), status=201)


@bp.get("/zones/<zid>")
def read_zone(zid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    z = get_zone(zid)
    return success(ser_zone(z), status=200)


@bp.get("/projects/<pid>/zones")
def list_project_zones(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [z for z in db.zones.values() if z["project_id"] == pid]
    data, pagination = paginate(items, ser_zone)
    return success(data, status=200, pagination=pagination)


@bp.get("/zones/<zid>/fixtures")
def list_zone_fixtures(zid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_zone(zid)
    items = [f for f in db.fixtures.values() if f.get("zone_id") == zid]
    data, pagination = paginate(items, ser_fixture)
    return success(data, status=200, pagination=pagination)


@bp.get("/zones/<zid>/add-ons")
def list_zone_add_ons(zid):
    _, role = get_auth()
    require_role(
        role, {"ControlProgrammer", "LightingDesigner", "OperationsAdmin"}
    )
    get_zone(zid)
    items = [a for a in db.add_ons.values() if a.get("zone_id") == zid]
    data, pagination = paginate(items, ser_add_on)
    return success(data, status=200, pagination=pagination)
