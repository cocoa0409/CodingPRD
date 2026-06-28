"""Fixture endpoints (PRD 3.2, 3.6).

assign-zone is the platform's most carefully guarded write. Validation order
(PRD 2.10): existence(3) -> request-shape(4) -> cross-project(5) ->
state(6) -> OCC(7) -> capacity ceiling(12).
"""

from flask import Blueprint

from common import (
    get_json_body,
    optional_int_ge,
    paginate,
    require_enum,
    require_fields,
    require_int,
    require_int_ge,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_fixture, get_project, get_zone
from middleware import get_auth, require_role
from response import success
from services.load import (
    recompute_project_loads,
    recompute_transformer,
    recompute_zone,
    transformer_committed,
    transformer_for_zone,
)
from services.serialize import ser_fixture

bp = Blueprint("fixtures", __name__)

READ_ROLES = {"LightingDesigner", "InstallTech", "Customer", "OperationsAdmin"}
CATEGORIES = {"PATH", "SPOT", "WELL", "STEP", "AUDIO", "SECURITY"}


@bp.post("/fixtures")
def create_fixture():
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    body = get_json_body()
    require_fields(
        body,
        ["project_id", "model_code", "category", "wattage_w", "purchase_price_cents"],
    )
    project_id = require_string(body, "project_id")
    model_code = require_string(body, "model_code")
    category = require_enum(body, "category", CATEGORIES)
    wattage_w = require_int_ge(body, "wattage_w", 0)
    purchase_price_cents = require_int_ge(body, "purchase_price_cents", 0)
    warranty_months = optional_int_ge(body, "warranty_months", 1, 60)
    get_project(project_id)

    record = stamp_new(
        {
            "zone_id": None,
            "project_id": project_id,
            "model_code": model_code,
            "category": category,
            "wattage_w": wattage_w,
            "purchase_price_cents": purchase_price_cents,
            "warranty_months": warranty_months,
            "installed_at": None,
            "status": "PLANNED",
        }
    )
    db.fixtures[record["id"]] = record
    return success(ser_fixture(record), status=201)


@bp.get("/fixtures/<fid>")
def read_fixture(fid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    f = get_fixture(fid)
    return success(ser_fixture(f), status=200)


@bp.get("/projects/<pid>/fixtures")
def list_project_fixtures(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [f for f in db.fixtures.values() if f["project_id"] == pid]
    data, pagination = paginate(items, ser_fixture)
    return success(data, status=200, pagination=pagination)


@bp.post("/fixtures/<fid>/assign-zone")
def assign_zone(fid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    # Existence: fixture in path (3).
    f = get_fixture(fid)
    body = get_json_body()
    # Request shape (4): both fields required; version must be an integer.
    require_fields(body, ["zone_id", "expected_transformer_version"])
    zone_id = require_string(body, "zone_id")
    expected_version = require_int(body, "expected_transformer_version")
    # Existence: target zone (3, body FK).
    zone = get_zone(zone_id)

    # Cross-project (5): zone must belong to the fixture's project.
    if zone["project_id"] != f["project_id"]:
        raise err(
            "ERR_CROSS_PROJECT_REFERENCE",
            "Zone belongs to a different project than the fixture.",
        )

    project = db.projects[f["project_id"]]

    # State (6): fixture must be PLANNED; project must not be DESIGN_LOCKED
    # (until commercial reaches INSTALLED).
    if f["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Fixture is not PLANNED.")
    if (
        project["design_status"] == "DESIGN_LOCKED"
        and project["commercial_status"] != "INSTALLED"
    ):
        raise err("ERR_INVALID_STATE", "Design is locked; no reassignment.")

    transformer = transformer_for_zone(zone)

    # OCC (7): expected_transformer_version must match.
    if expected_version != transformer["version"]:
        raise err(
            "ERR_STALE_TRANSFORMER_VERSION",
            "expected_transformer_version does not match the transformer.",
        )

    # Capacity ceiling (12): post-action committed must be <= usable.
    # Fixture is not yet in this zone, so its wattage is additive.
    prospective = transformer_committed(transformer) + f["wattage_w"]
    if prospective > transformer["usable_capacity_va"]:
        raise err(
            "ERR_TRANSFORMER_CAPACITY_EXCEEDED",
            "Assignment would exceed the transformer's usable capacity.",
        )

    # Commit: set zone, recompute zone/transformer/project loads. The target
    # transformer's version is incremented by one (OCC + recompute share the
    # same bump via touch in recompute_transformer; force the bump explicitly).
    f["zone_id"] = zone_id
    touch(f)
    recompute_zone(zone)
    recompute_transformer(transformer, bump_version_always=True)
    recompute_project_loads(project)
    return success(ser_fixture(f), status=200)


@bp.post("/fixtures/<fid>/remove")
def remove_fixture(fid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    f = get_fixture(fid)
    if f["status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Fixture is not INSTALLED.")
    f["status"] = "REMOVED"
    touch(f)
    # Recompute downward: zone, transformer, project.
    zone = db.zones.get(f.get("zone_id"))
    if zone is not None:
        recompute_zone(zone)
        transformer = transformer_for_zone(zone)
        if transformer is not None:
            recompute_transformer(transformer)
    recompute_project_loads(db.projects[f["project_id"]])
    return success(ser_fixture(f), status=200)
