"""Transformer endpoints (PRD 2.5, 3.1, 3.6)."""

from flask import Blueprint

from common import (
    get_json_body,
    paginate,
    require_fields,
    require_int_ge,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_project, get_transformer
from middleware import get_auth, require_role
from response import success
from services.calc import usable_capacity
from services.serialize import ser_transformer, ser_zone

bp = Blueprint("transformers", __name__)

READ_ROLES = {"LightingDesigner", "InstallTech", "OperationsAdmin"}


@bp.post("/transformers")
def create_transformer():
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    body = get_json_body()
    require_fields(body, ["project_id", "model_code", "rated_capacity_va"])
    project_id = require_string(body, "project_id")
    model_code = require_string(body, "model_code")
    rated = require_int_ge(body, "rated_capacity_va", 1)
    get_project(project_id)

    record = stamp_new(
        {
            "project_id": project_id,
            "model_code": model_code,
            "rated_capacity_va": rated,
            "usable_capacity_va": usable_capacity(rated),
            "committed_load_va": 0,
            "status": "STAGED",
        }
    )
    db.transformers[record["id"]] = record
    return success(ser_transformer(record), status=201)


@bp.get("/transformers/<tid>")
def read_transformer(tid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    t = get_transformer(tid)
    return success(ser_transformer(t), status=200)


@bp.get("/projects/<pid>/transformers")
def list_project_transformers(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [t for t in db.transformers.values() if t["project_id"] == pid]
    data, pagination = paginate(items, ser_transformer)
    return success(data, status=200, pagination=pagination)


@bp.get("/transformers/<tid>/zones")
def list_transformer_zones(tid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_transformer(tid)
    items = [z for z in db.zones.values() if z.get("transformer_id") == tid]
    data, pagination = paginate(items, ser_zone)
    return success(data, status=200, pagination=pagination)


@bp.post("/transformers/<tid>/decommission")
def decommission_transformer(tid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    t = get_transformer(tid)
    # Decommission requires ENERGIZED and no live fixtures on any fed zone.
    if t["status"] != "ENERGIZED":
        raise err(
            "ERR_TRANSFORMER_NOT_ENERGIZED",
            "Transformer is not ENERGIZED.",
        )
    zone_ids = {z["id"] for z in db.zones.values() if z.get("transformer_id") == tid}
    for f in db.fixtures.values():
        if f.get("zone_id") in zone_ids and f["status"] in {"PLANNED", "INSTALLED"}:
            raise err(
                "ERR_TRANSFORMER_NOT_ENERGIZED",
                "A fed zone still has a planned/installed fixture.",
            )
    t["status"] = "DECOMMISSIONED"
    touch(t)
    return success(ser_transformer(t), status=200)
