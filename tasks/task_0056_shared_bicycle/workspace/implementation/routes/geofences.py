"""Geofence endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

from db import LOCK, geofences, new_id, regions
from errors import (
    ERR_INVALID_POLYGON,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_role
from response import success_list, success_object
from services.geometry import validate_polygon
from services.validators import (
    ensure_enum,
    get_json_body,
    parse_pagination,
)
from time_utils import now_iso


bp = Blueprint("geofences", __name__)

GEOFENCE_KINDS = {"ALLOWED_PARKING", "RESTRICTED", "FORBIDDEN"}


def _serialize_geofence(g: dict) -> dict:
    return dict(g)


@bp.post("/regions/<region_id>/geofences")
def create_geofence(region_id):
    require_role("Admin")
    if region_id not in regions:
        raise_err(ERR_NOT_FOUND, "Region not found")
    body = get_json_body()
    label = body.get("label")
    if not isinstance(label, str) or not label:
        raise_err(ERR_VALIDATION, "label is required")
    if "kind" not in body:
        raise_err(ERR_VALIDATION, "kind is required")
    kind = ensure_enum(body["kind"], "kind", GEOFENCE_KINDS)
    polygon = body.get("polygon")
    try:
        validate_polygon(polygon)
    except ValueError as exc:
        raise_err(ERR_INVALID_POLYGON, str(exc))
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise_err(ERR_VALIDATION, "active must be a boolean")

    with LOCK:
        fid = new_id()
        fence = {
            "id": fid,
            "region_id": region_id,
            "label": label,
            "kind": kind,
            "polygon": polygon,
            "active": active,
            "revision": 1,
            "created_at": now_iso(),
        }
        geofences[fid] = fence
    return success_object(_serialize_geofence(fence), status=201)


@bp.patch("/geofences/<geofence_id>")
def patch_geofence(geofence_id):
    require_role("Admin")
    fence = geofences.get(geofence_id)
    if fence is None:
        raise_err(ERR_NOT_FOUND, "Geofence not found")
    body = get_json_body()
    mutated = False
    with LOCK:
        if "polygon" in body:
            try:
                validate_polygon(body["polygon"])
            except ValueError as exc:
                raise_err(ERR_INVALID_POLYGON, str(exc))
            fence["polygon"] = body["polygon"]
            mutated = True
        if "kind" in body:
            kind = ensure_enum(body["kind"], "kind", GEOFENCE_KINDS)
            if kind != fence["kind"]:
                fence["kind"] = kind
                mutated = True
        if "active" in body:
            active = body["active"]
            if not isinstance(active, bool):
                raise_err(ERR_VALIDATION, "active must be a boolean")
            if active != fence.get("active"):
                fence["active"] = active
                mutated = True
        if mutated:
            fence["revision"] = int(fence.get("revision", 1)) + 1
    return success_object(_serialize_geofence(fence))


@bp.get("/regions/<region_id>/geofences")
def list_geofences(region_id):
    require_role("Admin", "Operator", "FieldStaff", "Rider")
    if region_id not in regions:
        raise_err(ERR_NOT_FOUND, "Region not found")
    from flask import request
    kind_filter = request.args.get("kind")
    active_filter = request.args.get("active")
    if active_filter is not None:
        if active_filter.lower() in ("true", "1"):
            active_bool = True
        elif active_filter.lower() in ("false", "0"):
            active_bool = False
        else:
            raise_err(ERR_VALIDATION, "active filter must be a boolean")
    else:
        active_bool = None

    fences = [f for f in geofences.values() if f.get("region_id") == region_id]
    if kind_filter is not None:
        if kind_filter not in GEOFENCE_KINDS:
            raise_err(ERR_VALIDATION, "kind filter invalid")
        fences = [f for f in fences if f.get("kind") == kind_filter]
    if active_bool is not None:
        fences = [f for f in fences if f.get("active") == active_bool]
    fences.sort(key=lambda f: f["created_at"])

    limit, offset = parse_pagination()
    total = len(fences)
    window = fences[offset:offset + limit]
    return success_list(
        [_serialize_geofence(f) for f in window],
        limit=limit,
        offset=offset,
        total_count=total,
    )
