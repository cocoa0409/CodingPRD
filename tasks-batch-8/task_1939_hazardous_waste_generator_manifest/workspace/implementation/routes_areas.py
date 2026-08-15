"""AccumulationArea endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from core import base_entity
from db import store
from errors import invalid_request, not_found
from middleware import require_roles
from response import success_list, success_object
from validators import reject_unknown_fields, req_enum, req_str, require_fields, require_object

bp = Blueprint("areas", __name__)

ALL_ROLES = ("EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent")

_AREA_TYPES = {"SATELLITE", "CENTRAL_90DAY"}


def _parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def area_view(a: dict) -> dict:
    return dict(a)


@bp.route("/hazwaste/accumulation-areas", methods=["POST"])
def create_area():
    user_id, _ = require_roles("WasteCoordinator")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"site_id", "name", "area_type"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["site_id", "name", "area_type"])
    site_id = req_str(body, "site_id")
    name = req_str(body, "name")
    area_type = req_enum(body, "area_type", _AREA_TYPES)

    if site_id not in store.sites:
        raise not_found("site not found")

    a = base_entity()
    a.update({"site_id": site_id, "name": name, "area_type": area_type})
    store.areas[a["id"]] = a
    return success_object(area_view(a), status=201)


@bp.route("/hazwaste/accumulation-areas", methods=["GET"])
def list_areas():
    require_roles(*ALL_ROLES)
    limit, offset = _parse_pagination()
    site_id = request.args.get("site_id")
    items = list(store.areas.values())
    if site_id is not None:
        items = [a for a in items if a["site_id"] == site_id]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([area_view(a) for a in page], limit, offset, total)


@bp.route("/hazwaste/accumulation-areas/<areaId>", methods=["GET"])
def get_area(areaId: str):
    require_roles(*ALL_ROLES)
    a = store.areas.get(areaId)
    if a is None:
        raise not_found("area not found")
    return success_object(area_view(a))
