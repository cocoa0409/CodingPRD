"""TenantRequirement intake/withdrawal + stateless match evaluations."""
from flask import Blueprint

from db import store, new_entity, public
from errors import ApiError, ERR_INVALID_TIME_RANGE, ERR_INVALID_STATE
from middleware import (
    authenticate, body, require_fields, check_enums, get_path, USE_TYPES, ALL_ROLES,
)
from response import success_object
from services import cascades

bp = Blueprint("requirements", __name__)


@bp.post("/api/tenant-requirements")
def create_requirement():
    uid, _ = authenticate(["TenantRep"])
    b = body()
    require_fields(b, [
        ("tenant_name", "string", True),
        ("use_type", "string", True),
        ("min_sf", "int", True),
        ("max_sf", "int", True),
        ("min_clear_height_ft", "number", True),
        ("min_dock_doors", "int", True),
        ("min_power_amps", "int", True),
        ("min_yard_depth_ft", "int", True),
        ("target_submarket", "string", True),
        ("required_delivery_date", "datetime", True),
    ])
    check_enums(b, [("use_type", USE_TYPES)])
    # Priority 7: min_sf must be > 0 and <= max_sf (PRD §3.1 -> 422).
    if b["min_sf"] <= 0 or b["min_sf"] > b["max_sf"]:
        raise ApiError(ERR_INVALID_TIME_RANGE,
                       "min_sf must be greater than zero and no greater than max_sf", 422)
    from services.calc import D
    ent = new_entity({
        "tenant_name": b["tenant_name"],
        "use_type": b["use_type"],
        "min_sf": b["min_sf"],
        "max_sf": b["max_sf"],
        "min_clear_height_ft": D(b["min_clear_height_ft"]),
        "min_dock_doors": b["min_dock_doors"],
        "min_power_amps": b["min_power_amps"],
        "min_yard_depth_ft": b["min_yard_depth_ft"],
        "target_submarket": b["target_submarket"],
        "required_delivery_date": b["required_delivery_date"],
        "tenant_rep_id": uid,
        "status": "ACTIVE",
    })
    store.requirements[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/api/tenant-requirements/<rid>")
def get_requirement(rid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.requirements, rid, "tenant requirement")))


@bp.post("/api/tenant-requirements/<rid>/withdraw")
def withdraw_requirement(rid):
    uid, _ = authenticate(["TenantRep"])
    req = get_path(store.requirements, rid, "tenant requirement")
    # Priority 3: representative ownership.
    if req["tenant_rep_id"] != uid:
        from errors import ERR_FORBIDDEN
        raise ApiError(ERR_FORBIDDEN, "X-User-ID does not own this requirement", 403)
    if req["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot withdraw a requirement in status {req['status']}", 409)
    cascades.withdraw_requirement_cascade(req)
    return success_object(public(req))
