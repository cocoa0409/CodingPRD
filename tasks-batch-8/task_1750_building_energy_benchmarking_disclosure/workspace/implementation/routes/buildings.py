"""Building endpoints: register, get, list (covered list), OCC patch, archive,
per-cycle compliance summary."""
from flask import Blueprint, request

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import (parse_body, json_object, require_path_entity,
                        is_integer)
from validation import validate_schema

bp = Blueprint("buildings", __name__)


@bp.post("/v1/buildings")
def create_building():
    uid, role = get_context()
    require_roles(["BuildingOwner", "ComplianceOfficer"])
    body = parse_body({
        "address": ("string", True, None),
        "gross_floor_area_sqft": ("integer", True, None),
        "property_type": ("string", True, core.PROPERTY_TYPES),
        "owner_id": ("string", False, None),
    }, allow_empty=False)
    if body["gross_floor_area_sqft"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "gross_floor_area_sqft must be greater than zero")
    if role == "BuildingOwner":
        owner_id = uid
    else:
        owner_id = body.get("owner_id")
        if not owner_id:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "owner_id is required when created by a ComplianceOfficer")
        if owner_id not in store.owners:
            raise ApiError("ERR_NOT_FOUND", 404, "Referenced owner does not exist")
    building = db.new_common({
        "id": db.new_id(),
        "owner_id": owner_id,
        "address": body["address"],
        "gross_floor_area_sqft": body["gross_floor_area_sqft"],
        "property_type": body["property_type"],
        "status": "ACTIVE",
    })
    store.buildings[building["id"]] = building
    return created(building)


@bp.get("/v1/buildings/<building_id>")
def get_building(building_id):
    get_context()
    building = require_path_entity(store.buildings, building_id)
    return ok(building)


@bp.get("/v1/buildings")
def list_buildings():
    get_context()
    rows = list(store.buildings.values())
    rows = paginate.filter(rows, "owner_id")
    rows = paginate.filter(rows, "property_type")
    covered_cycle_id = request.args.get("covered_in_cycle_id")
    if covered_cycle_id is not None:
        cycle = store.cycles.get(covered_cycle_id)
        if cycle is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Referenced cycle does not exist")
        rows = [b for b in rows if core.covered(b, cycle)]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.patch("/v1/buildings/<building_id>")
def patch_building(building_id):
    uid, role = get_context()
    require_roles(["BuildingOwner", "ComplianceOfficer"])
    building = require_path_entity(store.buildings, building_id)
    if role == "BuildingOwner" and building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this building")
    body = json_object()
    # OCC (tier 5) before other input semantics.
    expected = body.get("expected_building_version")
    if not is_integer(expected):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_building_version is required and must be an integer")
    if expected != building["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_building_version does not match the current version")
    validate_schema(body, {
        "expected_building_version": ("integer", True, None),
        "address": ("string", False, None),
        "gross_floor_area_sqft": ("integer", False, None),
        "property_type": ("string", False, core.PROPERTY_TYPES),
    })
    if "gross_floor_area_sqft" in body and body["gross_floor_area_sqft"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "gross_floor_area_sqft must be greater than zero")
    area_changed = ("gross_floor_area_sqft" in body
                    and body["gross_floor_area_sqft"] != building["gross_floor_area_sqft"])
    for field in ("address", "gross_floor_area_sqft", "property_type"):
        if field in body:
            building[field] = body[field]
    db.touch(building)
    if area_changed:
        # Recompute site_eui on the building's DRAFT|FLAGGED reports against the new area.
        for r in store.reports.values():
            if r["building_id"] == building["id"] and r["status"] in ("DRAFT", "FLAGGED"):
                r["site_eui"] = core.compute_site_eui(r["aggregated_kbtu"], building)
                db.touch(r)
    return ok(building)


@bp.post("/v1/buildings/<building_id>/archive")
def archive_building(building_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    building = require_path_entity(store.buildings, building_id)
    if building["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an ACTIVE building can be archived")
    for f in store.fines.values():
        if f["building_id"] == building["id"] and f["status"] in ("ASSESSED", "NOTICED"):
            raise ApiError("ERR_OPEN_FINES_EXIST", 409,
                           "Building has fine assessments in ASSESSED or NOTICED")
    for r in store.reports.values():
        if r["building_id"] == building["id"] and r["status"] in ("DRAFT", "SUBMITTED", "FLAGGED"):
            raise ApiError("ERR_OPEN_REPORTS_EXIST", 409,
                           "Building has reports in DRAFT, SUBMITTED, or FLAGGED")
    building["status"] = "ARCHIVED"
    db.touch(building)
    return ok(building)


@bp.get("/v1/buildings/<building_id>/compliance-summary")
def compliance_summary(building_id):
    get_context()
    building = require_path_entity(store.buildings, building_id)
    cycle_id = request.args.get("cycle_id")
    if not cycle_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "cycle_id query parameter is required")
    cycle = store.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced cycle does not exist")
    report = core.report_for(building["id"], cycle["id"])
    outstanding, settled, projected = core.owner_exposures(building["owner_id"])
    # Latest verified report across cycles (max cycle_year), for score/label context.
    verified = []
    for r in store.reports.values():
        if r["building_id"] != building["id"] or r.get("verified_at") is None:
            continue
        rc = store.cycles.get(r["cycle_id"])
        if rc is None:
            continue
        verified.append((rc["cycle_year"], r["created_at"], r["_seq"], r))
    verified.sort(key=lambda t: (t[0], t[1], t[2]))
    latest = verified[-1][3] if verified else None
    return ok({
        "covered": core.covered(building, cycle),
        "report_status": report["status"] if report else None,
        "outstanding_fines_cents": outstanding,
        "settled_exposure_cents": settled,
        "projected_exposure_cents": projected,
        "latest_score_as_reported": latest["score_as_reported"] if latest else None,
        "latest_label_grade": latest["label_grade"] if latest else None,
        "effective_deadline_at": db.iso_logical(core.effective_deadline(building["id"], cycle)),
    })
