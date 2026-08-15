"""Furnace endpoints."""
from flask import Blueprint

import validation as v
from db import store, new_id, new_common
from errors import ApiError
from middleware import ANY_ROLES, get_context, require_roles
from response import created, ok
from services import domain

bp = Blueprint("furnaces", __name__)


@bp.post("/furnaces")
def create_furnace():
    get_context()
    require_roles(["ShopScheduler"])
    body = v.get_body()
    # tier 9: required fields / enum validity
    furnace_code = v.req_string(body, "furnace_code")
    furnace_class = v.req_enum(body, "furnace_class", domain.FURNACE_CLASSES)
    max_load_weight_lb = v.req_int(body, "max_load_weight_lb")
    media = v.req_list(body, "quench_media_supported")
    for m in media:
        if not isinstance(m, str) or m not in domain.QUENCH_MEDIA:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "quench_media_supported members must be one of %s"
                           % ", ".join(domain.QUENCH_MEDIA))
    for f in store.furnaces.values():
        if f["furnace_code"] == furnace_code:
            raise ApiError("ERR_INVALID_REQUEST", 400, "furnace_code must be unique")
    furnace = {
        "id": new_id(),
        "furnace_code": furnace_code,
        "furnace_class": furnace_class,
        "max_load_weight_lb": max_load_weight_lb,
        "quench_media_supported": list(media),
        "qualification_status": "UNQUALIFIED",
        "current_tus_due_at": None,
        "current_calibration_due_at": None,
    }
    new_common(furnace)
    store.furnaces[furnace["id"]] = furnace
    return created(furnace)


@bp.get("/furnaces/<furnace_id>")
def get_furnace(furnace_id):
    get_context()
    require_roles(ANY_ROLES)
    furnace = v.resolve_path(store.furnaces, furnace_id, "ERR_FURNACE_NOT_FOUND")
    # Posture is derived: recomputed against the logical clock on every furnace read.
    domain.recompute_posture(furnace)
    return ok(furnace)
