"""Unit routes — create, get, reserve, release, renovation, split, merge."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request, g

import db
from errors import err
from clock import now, parse_iso, to_utc_midnight
from middleware import require_auth
from response import success
from services.lookups import get_building, get_unit_in_building, get_tenant
from services.validation import (
    require_body, get_body, require_str, require_int, require_number,
    require_enum, require_iso, opt_iso, round_2dp, num_2dp_match,
)
from services.unit_status import update_status, update_unit_by_id, update_all
from services.money import D, round_half_up
from services.calendar_utils import closed_interval_overlap_half_open
from services.lease_checks import lease_overlaps_renovation_for_unit
from services.audit import record as audit_record


bp = Blueprint("units", __name__)

ORIENTATIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
USAGE_TYPES = {"OFFICE", "RETAIL", "WAREHOUSE", "FB"}


def _unit_public(u: dict) -> dict:
    # Refresh derived status before returning
    update_status(u)
    return db.public(u)


@bp.post("/buildings/<building_id>/units")
@require_auth(roles={"PropertyManager"})
def create_unit(building_id):
    b = get_building(building_id)
    body = require_body(request)
    floor = require_int(body, "floor", min_value=1, max_value=b["floors_count"])
    code = require_str(body, "code")
    area = require_number(body, "area_sqm", gt=0)
    orientation = require_enum(body, "orientation", ORIENTATIONS)
    usage_type = require_enum(body, "usage_type", USAGE_TYPES)
    rent_ref = require_number(body, "rent_reference_per_sqm", gt=0)

    # Code unique per building
    for u in db.units.values():
        if u.get("building_id") == building_id and u.get("code") == code and not u.get("_retired"):
            raise err("ERR_UNIT_CODE_CONFLICT", f"Unit code {code} already exists in building")

    unit = {
        "building_id": building_id,
        "parent_unit_id": None,
        "floor": floor,
        "code": code,
        "area_sqm": float(round_2dp(area)),
        "orientation": orientation,
        "usage_type": usage_type,
        "rent_reference_per_sqm": float(round_2dp(rent_ref)),
        "status": "VACANT",
        "renovation_start_date": None,
        "renovation_end_date": None,
        "_retired": False,
        "_reserved": False,
    }
    db.stamp_create(unit)
    db.units[unit["id"]] = unit
    update_status(unit)
    return success(_unit_public(unit), status=201)


@bp.get("/buildings/<building_id>/units/<unit_id>")
@require_auth(roles={"PropertyManager", "LeasingAgent", "FinanceOfficer", "Tenant"})
def get_unit_route(building_id, unit_id):
    u = get_unit_in_building(building_id, unit_id)
    role = g.user_role
    # Tenant: must have a lease relationship with this unit
    if role == "Tenant":
        tid = g.user_id
        owns = any(
            le.get("tenant_id") == tid and le.get("unit_id") == unit_id
            for le in db.leases.values()
        )
        if not owns:
            raise err("ERR_FORBIDDEN", "Tenant has no lease relationship with this unit")
    return success(_unit_public(u))


@bp.post("/buildings/<building_id>/units/<unit_id>/reserve")
@require_auth(roles={"LeasingAgent"})
def reserve_unit(building_id, unit_id):
    u = get_unit_in_building(building_id, unit_id)
    body = get_body(request)
    tenant_id = require_str(body, "tenant_id")
    # FK existence
    get_tenant(tenant_id)
    # State precondition: derived status must be VACANT
    update_status(u)
    if u["status"] != "VACANT":
        raise err("ERR_INVALID_STATE", f"Unit must be VACANT to reserve (current: {u['status']})")
    # No overlapping non-terminated lease on this unit (per scaffold's ERR_UNIT_NOT_AVAILABLE)
    from services.lease_checks import overlapping_lease_exists
    # Any non-terminated lease: pass a wide window or check existence directly.
    # We treat "overlap" loosely: simply forbid reservation if any active lease exists.
    has_active = any(
        le.get("unit_id") == unit_id and le.get("status") in {"SIGNED", "ACTIVE", "AMENDMENT_PENDING", "TERMINATING"}
        for le in db.leases.values()
    )
    if has_active:
        raise err("ERR_UNIT_NOT_AVAILABLE", "Unit has active lease and cannot be reserved")
    u["_reserved"] = True
    u["_reserved_tenant_id"] = tenant_id
    db.stamp_update(u)
    update_status(u)
    return success(_unit_public(u))


@bp.post("/buildings/<building_id>/units/<unit_id>/release-reservation")
@require_auth(roles={"LeasingAgent"})
def release_reservation(building_id, unit_id):
    u = get_unit_in_building(building_id, unit_id)
    # Reject if any DRAFT or SIGNED lease references this unit
    for le in db.leases.values():
        if le.get("unit_id") == unit_id and le.get("status") in {"DRAFT", "SIGNED"}:
            raise err("ERR_LEASE_DEPENDENCY", "A DRAFT or SIGNED lease references this unit")
    u["_reserved"] = False
    u["_reserved_tenant_id"] = None
    db.stamp_update(u)
    update_status(u)
    return success(_unit_public(u))


@bp.post("/buildings/<building_id>/units/<unit_id>/start-renovation")
@require_auth(roles={"PropertyManager"})
def start_renovation(building_id, unit_id):
    u = get_unit_in_building(building_id, unit_id)
    body = require_body(request)
    rs = require_iso(body, "renovation_start_date")
    re = require_iso(body, "renovation_end_date")
    update_status(u)
    if u["status"] != "VACANT":
        raise err("ERR_INVALID_STATE", f"Unit must be VACANT (current: {u['status']})")
    if not (re > rs):
        raise err("ERR_INVALID_DATE_RANGE", "renovation_end_date must be > renovation_start_date")
    # Conflict with non-terminated leases on this unit
    extended_end = re + timedelta(days=1)
    if lease_overlaps_renovation_for_unit(unit_id, rs, extended_end):
        raise err("ERR_RENOVATION_LEASE_CONFLICT",
                  "Renovation window overlaps a non-terminated lease")
    u["renovation_start_date"] = parse_iso(body["renovation_start_date"]).isoformat()
    # Store using ISO format that our serializer produces
    from clock import iso
    u["renovation_start_date"] = iso(rs)
    u["renovation_end_date"] = iso(re)
    db.stamp_update(u)
    update_status(u)
    return success(_unit_public(u))


@bp.post("/buildings/<building_id>/units/<unit_id>/finish-renovation")
@require_auth(roles={"PropertyManager"})
def finish_renovation(building_id, unit_id):
    u = get_unit_in_building(building_id, unit_id)
    u["renovation_start_date"] = None
    u["renovation_end_date"] = None
    db.stamp_update(u)
    update_status(u)
    return success(_unit_public(u))


@bp.post("/buildings/<building_id>/units/<unit_id>/split")
@require_auth(roles={"PropertyManager"})
def split_unit(building_id, unit_id):
    parent = get_unit_in_building(building_id, unit_id)
    body = require_body(request)
    children = body.get("child_units")
    if not isinstance(children, list) or len(children) < 2:
        raise err("ERR_VALIDATION", "child_units must be a list with at least 2 entries")
    update_status(parent)
    if parent["status"] != "VACANT":
        raise err("ERR_INVALID_STATE", f"Parent unit must be VACANT (current: {parent['status']})")

    # Validate each child and compute sum
    parsed = []
    total_area = Decimal("0")
    seen_codes = set()
    for i, c in enumerate(children):
        if not isinstance(c, dict):
            raise err("ERR_VALIDATION", "child_units entries must be objects")
        floor = c.get("floor", parent["floor"])
        if isinstance(floor, bool) or not isinstance(floor, int):
            raise err("ERR_VALIDATION", "child_units[].floor must be integer")
        code = c.get("code")
        if not isinstance(code, str) or not code.strip():
            raise err("ERR_VALIDATION", "child_units[].code must be a non-empty string")
        area = c.get("area_sqm")
        if isinstance(area, bool) or not isinstance(area, (int, float)) or area <= 0:
            raise err("ERR_VALIDATION", "child_units[].area_sqm must be a positive number")
        orientation = c.get("orientation", parent["orientation"])
        if orientation not in ORIENTATIONS:
            raise err("ERR_VALIDATION", f"child_units[].orientation invalid")
        usage_type = c.get("usage_type", parent["usage_type"])
        if usage_type not in USAGE_TYPES:
            raise err("ERR_VALIDATION", "child_units[].usage_type invalid")
        if code in seen_codes:
            raise err("ERR_UNIT_CODE_CONFLICT", f"Duplicate code in child_units: {code}")
        seen_codes.add(code)
        total_area += D(area)
        parsed.append({
            "floor": floor, "code": code, "area_sqm": float(round_2dp(area)),
            "orientation": orientation, "usage_type": usage_type,
        })

    # Area sum check to 2dp
    if round_2dp(total_area) != round_2dp(parent["area_sqm"]):
        raise err("ERR_AREA_SUM_MISMATCH",
                  "Sum of child_units areas must equal parent area to 2 dp")

    # Code conflict check across building (excluding retired units; the parent will be retired)
    for c in parsed:
        for u in db.units.values():
            if u["id"] == parent["id"]:
                continue
            if u.get("building_id") != building_id:
                continue
            if u.get("_retired"):
                continue
            if u.get("code") == c["code"]:
                raise err("ERR_UNIT_CODE_CONFLICT",
                          f"Unit code {c['code']} already exists in building")

    # All checks pass — perform split
    parent["_retired"] = True
    parent["_reserved"] = False
    db.stamp_update(parent)
    update_status(parent)

    created = []
    for c in parsed:
        u = {
            "building_id": building_id,
            "parent_unit_id": parent["id"],
            "floor": c["floor"],
            "code": c["code"],
            "area_sqm": c["area_sqm"],
            "orientation": c["orientation"],
            "usage_type": c["usage_type"],
            "rent_reference_per_sqm": parent["rent_reference_per_sqm"],
            "status": "VACANT",
            "renovation_start_date": None,
            "renovation_end_date": None,
            "_retired": False,
            "_reserved": False,
        }
        db.stamp_create(u)
        db.units[u["id"]] = u
        update_status(u)
        created.append(_unit_public(u))

    audit_record(
        subject_kind="UNIT", subject_id=parent["id"], action="UNIT_SPLIT",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"parent_unit_id": parent["id"],
                 "child_unit_ids": [u["id"] for u in created]},
    )
    # Return array of children
    from response import success_list
    return success_list(created, limit=len(created), offset=0,
                        total_count=len(created), status=201)


@bp.post("/buildings/<building_id>/units/merge")
@require_auth(roles={"PropertyManager"})
def merge_units(building_id):
    get_building(building_id)
    body = require_body(request)
    source_ids = body.get("source_unit_ids")
    merged_code = body.get("merged_code")
    if not isinstance(source_ids, list) or len(source_ids) < 2:
        raise err("ERR_VALIDATION", "source_unit_ids must have >= 2 entries")
    if not isinstance(merged_code, str) or not merged_code.strip():
        raise err("ERR_VALIDATION", "merged_code must be a non-empty string")

    # Existence + must belong to building
    sources = []
    for uid in source_ids:
        u = db.units.get(uid)
        if u is None:
            raise err("ERR_NOT_FOUND", f"Unit {uid} not found")
        if u.get("building_id") != building_id:
            raise err("ERR_NOT_FOUND", f"Unit {uid} does not belong to building {building_id}")
        sources.append(u)

    # State precondition: all VACANT
    for u in sources:
        update_status(u)
        if u["status"] != "VACANT":
            raise err("ERR_INVALID_STATE",
                      f"Source unit {u['id']} must be VACANT (current: {u['status']})")
    # Same building and floor
    floors = {u["floor"] for u in sources}
    if len(floors) != 1:
        raise err("ERR_MERGE_LAYOUT_INVALID", "All source units must share the same floor")

    # Code conflict (excluding retired)
    for u in db.units.values():
        if u.get("building_id") != building_id:
            continue
        if u.get("_retired"):
            continue
        if u["id"] in {s["id"] for s in sources}:
            continue
        if u.get("code") == merged_code:
            raise err("ERR_UNIT_CODE_CONFLICT", f"Unit code {merged_code} already in use")

    total_area = sum(D(u["area_sqm"]) for u in sources)
    # area-weighted average rent_reference, rounded to 2dp
    if total_area == 0:
        weighted = Decimal("0")
    else:
        weighted_sum = sum(D(u["area_sqm"]) * D(u["rent_reference_per_sqm"]) for u in sources)
        weighted = weighted_sum / total_area
    avg_rent_ref = float(round_2dp(weighted))

    # Retire sources
    for u in sources:
        u["_retired"] = True
        u["_reserved"] = False
        db.stamp_update(u)
        update_status(u)

    # Inherit usage_type/orientation from first source (PRD doesn't specify; use first)
    first = sources[0]
    merged = {
        "building_id": building_id,
        "parent_unit_id": None,
        "floor": first["floor"],
        "code": merged_code,
        "area_sqm": float(round_2dp(total_area)),
        "orientation": first["orientation"],
        "usage_type": first["usage_type"],
        "rent_reference_per_sqm": avg_rent_ref,
        "status": "VACANT",
        "renovation_start_date": None,
        "renovation_end_date": None,
        "_retired": False,
        "_reserved": False,
    }
    db.stamp_create(merged)
    db.units[merged["id"]] = merged
    update_status(merged)

    audit_record(
        subject_kind="UNIT", subject_id=merged["id"], action="UNIT_MERGED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"source_unit_ids": [u["id"] for u in sources],
                 "merged_unit_id": merged["id"]},
    )
    return success(_unit_public(merged), status=201)
