"""Container routes (PRD §3.6): stage, list, dispatch (OCC-guarded)."""
from flask import Blueprint

import errors
import response
import serializers
from db import db, stamp_create, touch
from helpers import (as_enum, as_int, as_number, get_json_body,
                     parse_pagination, paginate, query_arg, require_fields)
from middleware import authenticate, require_roles

bp = Blueprint("containers", __name__)

CATEGORIES = {"FERROUS", "NON_FERROUS"}
CONTAINER_STATUSES = {"STAGED", "DISPATCHED", "CLOSED"}


@bp.route("/yard/containers", methods=["POST"])
def create_container():
    _uid, role = authenticate()
    require_roles(role, {"YardManager"})
    body = get_json_body()
    require_fields(body, ["category", "capacity_lb"])
    category = as_enum(body["category"], "category", CATEGORIES)
    capacity = as_number(body["capacity_lb"], "capacity_lb", positive=True)

    record = {
        "category": category,
        "capacity_lb": capacity,
        "loaded_weight_lb": 0,
        "status": "STAGED",
    }
    stamp_create(record)
    db.containers[record["id"]] = record
    return response.success(serializers.container(record), 201)


@bp.route("/yard/containers/<cid>", methods=["GET"])
def get_container(cid):
    authenticate()
    record = db.containers.get(cid)
    if not record:
        raise errors.not_found("Container not found.")
    return response.success(serializers.container(record), 200)


@bp.route("/yard/containers", methods=["GET"])
def list_containers():
    authenticate()
    limit, offset = parse_pagination()
    category = query_arg("category")
    status = query_arg("status")
    if category is not None and category not in CATEGORIES:
        raise errors.invalid_request("category filter is invalid.")
    if status is not None and status not in CONTAINER_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.containers.values())
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.container(r) for r in page], limit, offset, total)


@bp.route("/yard/containers/<cid>/dispatch", methods=["POST"])
def dispatch_container(cid):
    _uid, role = authenticate()
    require_roles(role, {"YardManager"})
    container = db.containers.get(cid)
    if not container:
        raise errors.not_found("Container not found.")
    # State (priority 4): only from STAGED.
    if container["status"] != "STAGED":
        raise errors.invalid_state("Container is not STAGED.")
    body = get_json_body()
    require_fields(body, ["expected_container_version"])
    expected = as_int(body["expected_container_version"], "expected_container_version")
    # Non-empty container required.
    if not container["loaded_weight_lb"] > 0:
        raise errors.invalid_request("Container is empty; cannot dispatch.")
    # OCC (priority 13): expected version must match current version.
    if expected != container["version"]:
        raise errors.stale_container_version()

    container["status"] = "DISPATCHED"
    touch(container)
    return response.success(serializers.container(container), 200)
