"""InterchangeMapping endpoints."""

import uuid

from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_PART_NOT_FOUND, ERR_MODEL_NOT_FOUND,
    ERR_INTERCHANGE_NOT_FOUND, ERR_DUPLICATE_INTERCHANGE,
)
from middleware import require_role
from response import success
from services.serializers import mapping_view
from validators import (
    get_json_body, require_fields, check_string, check_enum,
    parse_limit_offset, paginate,
)

bp = Blueprint("interchange", __name__)

TIERS = {"DIRECT", "ADAPTED"}


@bp.post("/api/interchange-mappings")
def create_mapping():
    require_role({"InventoryPlanner"})
    body = get_json_body()
    require_fields(body, ["hard_part_id", "transmission_model_id", "tier"])
    check_string(body["hard_part_id"], "hard_part_id")
    check_string(body["transmission_model_id"], "transmission_model_id")
    check_enum(body["tier"], "tier", TIERS)

    # FK existence, left to right.
    if body["hard_part_id"] not in db.hard_parts:
        raise ApiError(ERR_PART_NOT_FOUND, "HardPart id does not exist", 404)
    if body["transmission_model_id"] not in db.transmission_models:
        raise ApiError(ERR_MODEL_NOT_FOUND, "TransmissionModel id does not exist", 404)

    for m in db.interchange_mappings.values():
        if (
            m["hard_part_id"] == body["hard_part_id"]
            and m["transmission_model_id"] == body["transmission_model_id"]
        ):
            raise ApiError(
                ERR_DUPLICATE_INTERCHANGE,
                "(hard_part_id, transmission_model_id) mapping already exists",
                409,
            )

    x = {
        "id": str(uuid.uuid4()),
        "hard_part_id": body["hard_part_id"],
        "transmission_model_id": body["transmission_model_id"],
        "tier": body["tier"],
        "created_at": db.now(),
    }
    db.interchange_mappings[x["id"]] = x
    return success(mapping_view(x), "object", 201)


@bp.get("/api/interchange-mappings")
def list_mappings():
    require_role({"Any"})
    items = list(db.interchange_mappings.values())
    hp = request.args.get("hard_part_id")
    tm = request.args.get("transmission_model_id")
    if hp is not None:
        items = [m for m in items if m["hard_part_id"] == hp]
    if tm is not None:
        items = [m for m in items if m["transmission_model_id"] == tm]
    items.sort(key=lambda m: m["created_at"])
    limit, offset = parse_limit_offset(request.args)
    page, pg = paginate(items, limit, offset)
    return success([mapping_view(m) for m in page], "array", 200, pg)


@bp.get("/api/interchange-mappings/<mid>")
def get_mapping(mid):
    require_role({"Any"})
    m = db.interchange_mappings.get(mid)
    if m is None:
        raise ApiError(
            ERR_INTERCHANGE_NOT_FOUND, "InterchangeMapping id does not exist", 404
        )
    return success(mapping_view(m), "object", 200)
