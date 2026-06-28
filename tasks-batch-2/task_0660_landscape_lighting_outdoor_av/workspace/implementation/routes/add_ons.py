"""AddOnModule endpoints (PRD 3.8).

A zone-powered add-on draws power_draw_va from its zone's transformer when
ACTIVE. Activation is subject to the same capacity ceiling as fixture
assignment (ERR_TRANSFORMER_CAPACITY_EXCEEDED). Self-powered add-ons (zone_id
null) draw nothing.
"""

from flask import Blueprint

from common import (
    get_json_body,
    optional_string,
    paginate,
    require_enum,
    require_fields,
    require_int_ge,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_add_on, get_project, get_zone
from middleware import get_auth, require_role
from response import success
from services.load import (
    recompute_project_loads,
    recompute_transformer,
    transformer_committed,
    transformer_for_zone,
)
from services.serialize import ser_add_on

bp = Blueprint("add_ons", __name__)

READ_ROLES = {"ControlProgrammer", "LightingDesigner", "OperationsAdmin"}
KINDS = {"AUDIO", "SECURITY"}


@bp.post("/add-ons")
def create_add_on():
    _, role = get_auth()
    require_role(role, {"ControlProgrammer", "LightingDesigner"})
    body = get_json_body()
    require_fields(body, ["project_id", "kind", "power_draw_va"])
    project_id = require_string(body, "project_id")
    kind = require_enum(body, "kind", KINDS)
    power_draw_va = require_int_ge(body, "power_draw_va", 0)
    zone_id = optional_string(body, "zone_id", None)
    get_project(project_id)
    if zone_id is not None:
        # Existence of the referenced zone (priority 3).
        get_zone(zone_id)

    record = stamp_new(
        {
            "project_id": project_id,
            "zone_id": zone_id,
            "kind": kind,
            "power_draw_va": power_draw_va,
            "status": "PROPOSED",
        }
    )
    db.add_ons[record["id"]] = record
    return success(ser_add_on(record), status=201)


@bp.get("/add-ons/<aid>")
def read_add_on(aid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    a = get_add_on(aid)
    return success(ser_add_on(a), status=200)


@bp.get("/projects/<pid>/add-ons")
def list_project_add_ons(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [a for a in db.add_ons.values() if a["project_id"] == pid]
    data, pagination = paginate(items, ser_add_on)
    return success(data, status=200, pagination=pagination)


@bp.post("/add-ons/<aid>/activate")
def activate_add_on(aid):
    _, role = get_auth()
    require_role(role, {"ControlProgrammer"})
    a = get_add_on(aid)
    if a["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Add-on is not PROPOSED.")
    project = db.projects[a["project_id"]]
    if project["commercial_status"] != "INSTALLED":
        raise err("ERR_PROJECT_NOT_INSTALLED", "Project is not INSTALLED.")

    zone_id = a.get("zone_id")
    if zone_id is not None:
        zone = db.zones.get(zone_id)
        transformer = transformer_for_zone(zone)
        # Capacity ceiling: post-action committed must be <= usable. The add-on
        # is not yet ACTIVE, so its draw is additive.
        prospective = transformer_committed(transformer) + a["power_draw_va"]
        if prospective > transformer["usable_capacity_va"]:
            raise err(
                "ERR_TRANSFORMER_CAPACITY_EXCEEDED",
                "Activation would exceed the transformer's usable capacity.",
            )
        a["status"] = "ACTIVE"
        touch(a)
        recompute_transformer(transformer)
        recompute_project_loads(project)
    else:
        a["status"] = "ACTIVE"
        touch(a)
    return success(ser_add_on(a), status=200)


@bp.post("/add-ons/<aid>/remove")
def remove_add_on(aid):
    _, role = get_auth()
    require_role(role, {"ControlProgrammer"})
    a = get_add_on(aid)
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Add-on is not ACTIVE.")
    zone_id = a.get("zone_id")
    a["status"] = "REMOVED"
    touch(a)
    if zone_id is not None:
        zone = db.zones.get(zone_id)
        if zone is not None:
            transformer = transformer_for_zone(zone)
            if transformer is not None:
                recompute_transformer(transformer)
            recompute_project_loads(db.projects[a["project_id"]])
    return success(ser_add_on(a), status=200)
