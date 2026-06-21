"""Container endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, require_enum, as_int, as_number, as_str,
    get_account_or_404, get_location_or_404, get_container_or_404,
)

bp = Blueprint("containers", __name__)

CONTAINER_TYPES = {"CONSOLE", "BIN"}


@bp.post("/containers")
def create_container():
    _, role = get_auth()
    require_role(role, {"AccountManager", "FieldTechnician"})
    data = body()
    require_present(data, "account_id", "location_id", "container_type",
                    "capacity_kg", "tare_weight_kg")
    account_id = as_str(data["account_id"], "account_id")
    location_id = as_str(data["location_id"], "location_id")
    # Existence left-to-right: account then location.
    get_account_or_404(account_id)
    get_location_or_404(location_id)

    require_enum(data["container_type"], CONTAINER_TYPES, "container_type")
    capacity_kg = as_int(data["capacity_kg"], "capacity_kg")
    if capacity_kg <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "capacity_kg must be > 0")
    tare_weight_kg = as_number(data["tare_weight_kg"], "tare_weight_kg")
    if tare_weight_kg < 0:
        raise err("ERR_INVALID_FIELD_VALUE", "tare_weight_kg must be >= 0")

    container = {
        "account_id": account_id,
        "location_id": location_id,
        "container_type": data["container_type"],
        "capacity_kg": capacity_kg,
        "tare_weight_kg": tare_weight_kg,
        "status": "PLACED",
    }
    stamp_create(container)
    db.containers[container["id"]] = container
    return object_response(serialize(container), 201)


@bp.get("/containers/<container_id>")
def get_container(container_id):
    _, role = get_auth()
    require_role(role, {"AccountManager", "FieldTechnician", "ComplianceOfficer"})
    c = get_container_or_404(container_id)
    return object_response(serialize(c), 200)


@bp.get("/containers")
def list_containers():
    _, role = get_auth()
    require_role(role, {"AccountManager", "FieldTechnician", "ComplianceOfficer"})
    items = list(db.containers.values())
    account_id = request.args.get("account_id")
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if location_id is not None:
        items = [c for c in items if c["location_id"] == location_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(c) for c in page], limit, offset, total, 200)


@bp.post("/containers/<container_id>/retire")
def retire_container(container_id):
    _, role = get_auth()
    require_role(role, {"AccountManager"})
    c = get_container_or_404(container_id)
    c["status"] = "RETIRED"
    touch(c)
    return object_response(serialize(c), 200)
