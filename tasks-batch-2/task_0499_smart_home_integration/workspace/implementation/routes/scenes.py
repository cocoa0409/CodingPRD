"""Automation scene programming (PRD §3.6)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import domain

bp = Blueprint("scenes", __name__)

READ_ROLES = {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "SupportEngineer", "Client"}


def _scene_in_project(project_id, scene_id):
    h.get_or_404(db.projects, project_id)
    scene = db.scenes.get(scene_id)
    if scene is None or scene["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Scene not found in project")
    return scene


def _device_ids_on_project(project_id):
    return {d["id"] for d in domain.devices_for_project(project_id)}


@bp.post("/projects/<project_id>/scenes")
def create_scene(project_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    project = h.get_or_404(db.projects, project_id)
    body = h.get_body()
    name = h.require_str(body, "name")
    device_ids = h.require(body, "device_ids")
    if not isinstance(device_ids, list) or not all(isinstance(x, str) for x in device_ids):
        raise err("ERR_INVALID_REQUEST", "device_ids must be an array of strings")
    action_count = h.require_int(body, "action_count", minimum=1)
    # name unique among non-ARCHIVED scenes of the project (well-formedness)
    for s in db.scenes.values():
        if s["project_id"] == project_id and s["status"] != "ARCHIVED" and s["name"] == name:
            raise err("ERR_INVALID_REQUEST", "Scene name must be unique among non-archived scenes")
    # referential integrity (priority 6): every device_id must be on this project's rack
    on_project = _device_ids_on_project(project_id)
    for did in device_ids:
        if did not in on_project:
            raise err("ERR_REFERENTIAL_INTEGRITY", "device_ids must all belong to the project's rack")
    entity = {
        "project_id": project_id,
        "name": name,
        "device_ids": list(device_ids),
        "status": "DRAFT",
        "action_count": action_count,
    }
    db.stamp_create(entity)
    db.scenes[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>/scenes")
def list_scenes(project_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h.get_or_404(db.projects, project_id)
    limit, offset = h.parse_pagination()
    status = request.args.get("status")
    items = [s for s in db.scenes.values() if s["project_id"] == project_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(s) for s in page], limit, offset, total)


@bp.get("/projects/<project_id>/scenes/<scene_id>")
def get_scene(project_id, scene_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    scene = _scene_in_project(project_id, scene_id)
    return success(h.public(scene))


@bp.post("/projects/<project_id>/scenes/<scene_id>/validate")
def validate_scene(project_id, scene_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    scene = _scene_in_project(project_id, scene_id)
    if scene["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT scene may be validated")
    # action_count >= 1
    if scene["action_count"] < 1:
        raise err("ERR_EMPTY_SCENE", "Scene has no actions")
    # every device belongs to this project's rack
    on_project = _device_ids_on_project(project_id)
    for did in scene["device_ids"]:
        if did not in on_project:
            raise err("ERR_SCENE_DEVICE_MISMATCH", "Scene device not on this project's rack")
    # at least one controller
    has_controller = any(
        db.devices.get(did, {}).get("is_controller") for did in scene["device_ids"]
    )
    if not has_controller:
        raise err("ERR_NO_CONTROLLER_IN_SCENE", "Scene has no controller device")
    scene["status"] = "VALIDATED"
    db.touch(scene)
    return success(h.public(scene))


@bp.post("/projects/<project_id>/scenes/<scene_id>/deploy")
def deploy_scene(project_id, scene_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    scene = _scene_in_project(project_id, scene_id)
    if scene["status"] != "VALIDATED":
        raise err("ERR_INVALID_STATE", "Only a VALIDATED scene may be deployed")
    for did in scene["device_ids"]:
        d = db.devices.get(did)
        if d is None or d["status"] != "ONLINE":
            raise err("ERR_SCENE_DEVICE_NOT_ONLINE", "All scene devices must be ONLINE")
    scene["status"] = "DEPLOYED"
    db.touch(scene)
    return success(h.public(scene))


@bp.post("/projects/<project_id>/scenes/<scene_id>/revise")
def revise_scene(project_id, scene_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    scene = _scene_in_project(project_id, scene_id)
    if scene["status"] != "VALIDATED":
        raise err("ERR_INVALID_STATE", "Only a VALIDATED scene may be revised")
    scene["status"] = "DRAFT"
    db.touch(scene)
    return success(h.public(scene))


@bp.post("/projects/<project_id>/scenes/<scene_id>/archive")
def archive_scene(project_id, scene_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    scene = _scene_in_project(project_id, scene_id)
    if scene["status"] not in ("DRAFT", "VALIDATED"):
        raise err("ERR_INVALID_STATE", "Only a DRAFT or VALIDATED scene may be archived")
    scene["status"] = "ARCHIVED"
    db.touch(scene)
    return success(h.public(scene))
