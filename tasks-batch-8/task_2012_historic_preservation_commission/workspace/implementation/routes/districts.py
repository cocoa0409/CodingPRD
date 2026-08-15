"""Districts and design guideline sets (PRD 3.1).

Pipeline order (PRD 2.8): headers (1) -> body shape (1) -> role (2) ->
existence (3) -> state (5) -> business rules (6-10).
"""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE
from middleware import get_caller, check_role_allowed, ALL_ROLES, authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch
from util import CLOCK
from validate import (
    get_body, req_str, req_enum, req_sections, require_path_resource,
)

bp = Blueprint("districts", __name__, url_prefix="/preservation")

SIGNIFICANCE_TIERS = {"LOCAL", "LANDMARK", "ICONIC"}
DISTRICT_STATUSES = {"ACTIVE", "BOUNDARY_REVIEW"}
STAFF = ["PreservationStaff"]


@bp.post("/districts")
def create_district():
    caller = get_caller()
    body = get_body()
    name = req_str(body, "name")
    boundary_description = req_str(body, "boundary_description")
    significance_tier = req_enum(body, "significance_tier", SIGNIFICANCE_TIERS)
    check_role_allowed(caller, STAFF)
    rec = new_record("districts", {
        "name": name,
        "boundary_description": boundary_description,
        "significance_tier": significance_tier,
        "status": "ACTIVE",
        "contributing_count": 0,
        "total_inventory_count": 0,
        "preservation_posture": "STABLE",
    })
    return success_object(public(rec), status=201)


@bp.get("/districts")
def list_districts():
    filters = {"status": request.args.get("status")}
    return list_response("districts", filters)


@bp.get("/districts/<rid>")
def get_district(rid):
    return get_one("districts", rid)


@bp.patch("/districts/<rid>")
def patch_district(rid):
    caller = get_caller()
    body = get_body()
    # Shape validation first (layer 1), then role (layer 2), then existence (3).
    new_status = None
    if "status" in body and body["status"] is not None:
        new_status = req_enum(body, "status", DISTRICT_STATUSES)
    new_boundary = None
    if "boundary_description" in body and body["boundary_description"] is not None:
        new_boundary = req_str(body, "boundary_description")
    new_tier = None
    if "significance_tier" in body and body["significance_tier"] is not None:
        new_tier = req_enum(body, "significance_tier", SIGNIFICANCE_TIERS)
    check_role_allowed(caller, STAFF)
    district = require_path_resource("districts", rid)

    updated = False
    if new_status is not None:
        district["status"] = new_status  # ACTIVE <-> BOUNDARY_REVIEW; same-value write is a no-op
        updated = True
    if new_boundary is not None:
        district["boundary_description"] = new_boundary
        updated = True
    if new_tier is not None:
        district["significance_tier"] = new_tier
        updated = True
    if updated:
        # Each update call increments the district's version by one.
        touch(district)
    return success_object(public(district))


@bp.get("/districts/<rid>/properties")
def list_district_properties(rid):
    authorized(ALL_ROLES)
    require_path_resource("districts", rid)
    items = [p for p in db["properties"].values() if p.get("district_id") == rid]
    return list_response("properties", items=items)


@bp.post("/districts/<rid>/guideline-sets")
def create_guideline_set(rid):
    caller = get_caller()
    body = get_body()
    title = req_str(body, "title")
    sections = req_sections(body, "sections")
    check_role_allowed(caller, STAFF)
    require_path_resource("districts", rid)
    prior_count = sum(
        1 for gs in db["guideline_sets"].values() if gs.get("district_id") == rid
    )
    rec = new_record("guideline_sets", {
        "district_id": rid,
        "title": title,
        "sections": sections,
        "version_no": prior_count + 1,
        "adopted_at": None,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/districts/<rid>/guideline-sets")
def list_guideline_sets(rid):
    authorized(ALL_ROLES)
    require_path_resource("districts", rid)
    items = [gs for gs in db["guideline_sets"].values() if gs.get("district_id") == rid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [gs for gs in items if gs.get("status") == status_filter]
    return list_response("guideline_sets", items=items)


@bp.post("/guideline-sets/<rid>/adopt")
def adopt_guideline_set(rid):
    caller = authorized(STAFF)
    gs = require_path_resource("guideline_sets", rid)
    if gs["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot adopt a guideline set in status {gs['status']}")
    # The district's previously ADOPTED set (if any) becomes SUPERSEDED.
    for other in db["guideline_sets"].values():
        if (
            other.get("district_id") == gs["district_id"]
            and other.get("status") == "ADOPTED"
            and other["id"] != gs["id"]
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    gs["status"] = "ADOPTED"
    gs["adopted_at"] = CLOCK.now_iso()
    touch(gs)
    return success_object(public(gs))
